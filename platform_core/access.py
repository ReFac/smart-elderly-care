"""Local accounts, revocable sessions and owner-managed institution settings."""

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import time
from uuid import uuid4

from . import portal, staff_scope

from .access_policy import (
    DEFAULT_UI,
    PERMISSIONS,
    PRESETS,
    ROUTE_GRANTS,
    allowed_actions,
    authorize,
    can_view_audit,
    has,
    manages_accounts,
    require,
    resolve_routes,
    visible_data,
)

__all__ = [
    "init",
    "login",
    "logout",
    "authenticate",
    "account",
    "apply",
    "project",
    "authorize",
    "can_view_audit",
    "has",
    "require",
    "LoginThrottled",
]
SESSION_LIFETIME = 12 * 60 * 60
WINDOW = 15 * 60
MAX_FAILURES = 8
DUMMY_SALT = b"nh-account-dummy"
DEFAULT_MODEL = "deepseek-chat"


class LoginThrottled(PermissionError):
    """The same account has exceeded its failed sign-in budget."""


def _password(value):
    if not isinstance(value, str) or not 10 <= len(value) <= 128:
        raise ValueError("密码长度须为 10 至 128 个字符")
    return value


def _digest(password, salt):
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32
    )


def _token_hash(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _owner_password(db):
    configured = os.environ.get("NH_OWNER_PASSWORD")
    if configured:
        return _password(configured)
    filename = db.execute("PRAGMA database_list").fetchone()[2]
    if not filename:
        return secrets.token_urlsafe(24)
    path = Path(filename).parent / ".owner-password"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # Reuse an interrupted, local bootstrap safely. Never follow symlinks.
        fd = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
        with os.fdopen(fd, "r", encoding="utf-8") as source:
            info = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or not stat.S_ISREG(path.lstat().st_mode)
                or not os.path.samestat(info, path.lstat())
                or (
                    os.name == "posix"
                    and (info.st_uid != os.getuid() or info.st_mode & 0o077)
                )
            ):
                raise RuntimeError("首次登录密码文件须归当前用户所有且权限为 0600")
            return _password(source.read(132).strip())
    value = secrets.token_urlsafe(24)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        output.write(value + "\n")
        output.flush()
        os.fsync(output.fileno())
    return value


def init(db):
    """Initialize inside the caller's write transaction. No default shared password."""
    db.execute("""CREATE TABLE IF NOT EXISTS accounts (
      id TEXT PRIMARY KEY, username TEXT UNIQUE COLLATE NOCASE NOT NULL,
      display_name TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('owner','staff','family')),
      role TEXT NOT NULL, permissions TEXT NOT NULL DEFAULT '[]', resident_id TEXT NOT NULL DEFAULT '',
      enabled INTEGER NOT NULL DEFAULT 1, salt BLOB NOT NULL, password_hash BLOB NOT NULL,
      family_services INTEGER NOT NULL DEFAULT 0 CHECK(family_services IN (0,1)))""")
    if "family_services" not in {
        r[1] for r in db.execute("PRAGMA table_info(accounts)")
    }:
        db.execute(
            "ALTER TABLE accounts ADD COLUMN family_services INTEGER NOT NULL DEFAULT 0 CHECK(family_services IN (0,1))"
        )
    if "portal_scopes" not in {r[1] for r in db.execute("PRAGMA table_info(accounts)")}:
        db.execute(
            "ALTER TABLE accounts ADD COLUMN portal_scopes TEXT NOT NULL DEFAULT '[]'"
        )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS one_owner ON accounts(kind) WHERE kind='owner'"
    )
    db.execute("""CREATE TABLE IF NOT EXISTS sessions (
      token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
      expires INTEGER NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS sessions_account ON sessions(account_id)")
    db.execute("""CREATE TABLE IF NOT EXISTS login_failures (
      subject TEXT PRIMARY KEY, since INTEGER NOT NULL, attempts INTEGER NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS institution_settings (
      id INTEGER PRIMARY KEY CHECK(id=1), visual TEXT NOT NULL, deepseek_enabled INTEGER NOT NULL,
      deepseek_model TEXT NOT NULL)""")
    db.execute(
        "INSERT OR IGNORE INTO institution_settings VALUES(1,?,0,?)",
        (json.dumps(DEFAULT_UI, ensure_ascii=False), DEFAULT_MODEL),
    )
    if not db.execute("SELECT 1 FROM accounts WHERE kind='owner'").fetchone():
        salt = secrets.token_bytes(16)
        db.execute(
            """INSERT INTO accounts(id,username,display_name,kind,role,salt,password_hash)
                   VALUES(?,?,?,?,?,?,?)""",
            (
                uuid4().hex,
                "owner",
                "总管理员",
                "owner",
                "总管理员",
                salt,
                _digest(_owner_password(db), salt),
            ),
        )


def migrate_branding(db):
    visual = json.loads(
        db.execute("SELECT visual FROM institution_settings WHERE id=1").fetchone()[0]
    )
    for key, old in (("brandName", "颐和医养"), ("institutionName", "颐和康养中心")):
        if visual.get(key) == old:
            visual[key] = DEFAULT_UI[key]
    db.execute(
        "UPDATE institution_settings SET visual=? WHERE id=1",
        (json.dumps(visual, ensure_ascii=False),),
    )


def _public(row):
    user = {
        "id": row["id"],
        "username": row["username"],
        "displayName": row["display_name"],
        "kind": row["kind"],
        "role": row["role"],
        "residentId": row["resident_id"],
        "enabled": bool(row["enabled"]),
        "permissions": list(PERMISSIONS)
        if row["kind"] == "owner"
        else json.loads(row["permissions"]),
    }
    user["routes"] = resolve_routes(user)
    if user["kind"] == "family":
        user["familyServices"] = bool(row["family_services"])
        user["portalSelf"] = user["role"] == "入住长者"
        user["portalScopes"] = json.loads(row["portal_scopes"])
    return user


def account(db, account_id):
    row = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    return _public(row) if row else None


def login(db, username, password):
    # Caller commits failed attempt counts as well as successful logins.
    if (
        not isinstance(username, str)
        or len(username) > 64
        or not isinstance(password, str)
        or len(password) > 128
    ):
        raise PermissionError("账号或密码不正确，或账号已停用")
    now = int(time.time())
    row = db.execute(
        "SELECT * FROM accounts WHERE username=?", (username.strip(),)
    ).fetchone()
    subject = row["id"] if row else "unknown"
    db.execute("DELETE FROM login_failures WHERE since<=?", (now - WINDOW,))
    failed = db.execute(
        "SELECT attempts FROM login_failures WHERE subject=?", (subject,)
    ).fetchone()
    if failed and failed[0] >= MAX_FAILURES:
        raise LoginThrottled("登录尝试过多，请在 15 分钟后重试")
    computed = _digest(password, row["salt"] if row else DUMMY_SALT)
    if (
        not row
        or not hmac.compare_digest(computed, row["password_hash"])
        or not row["enabled"]
    ):
        db.execute(
            """INSERT INTO login_failures(subject,since,attempts) VALUES(?,?,1)
                   ON CONFLICT(subject) DO UPDATE SET attempts=attempts+1""",
            (subject, now),
        )
        raise PermissionError("账号或密码不正确，或账号已停用")
    token = secrets.token_urlsafe(32)
    db.execute("DELETE FROM login_failures WHERE subject=?", (subject,))
    db.execute("DELETE FROM sessions WHERE expires <= ?", (now,))
    db.execute(
        "INSERT INTO sessions VALUES(?,?,?)",
        (_token_hash(token), row["id"], now + SESSION_LIFETIME),
    )
    return token, _public(row)


def _valid_token(token):
    return isinstance(token, str) and len(token) == 43 and token.isascii()


def authenticate(db, token):
    if not _valid_token(token):
        return None
    row = db.execute(
        """SELECT a.* FROM accounts a JOIN sessions s ON a.id=s.account_id
                   WHERE s.token_hash=? AND s.expires>? AND a.enabled=1""",
        (_token_hash(token), int(time.time())),
    ).fetchone()
    return _public(row) if row else None


def logout(db, token):
    if _valid_token(token):
        db.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))


def _required(value, label, maxlen=60):
    if not isinstance(value, str) or not 0 < len(value.strip()) <= maxlen:
        raise ValueError(f"请填写有效的{label}（最多 {maxlen} 字）")
    return value.strip()


def _staff_grants(role, permissions):
    if not isinstance(role, str) or role not in PRESETS:
        raise ValueError("请选择已有岗位模板")
    values = PRESETS[role] if permissions is None else permissions
    if not isinstance(values, list) or not all(
        isinstance(p, str) and p in PERMISSIONS for p in values
    ):
        raise ValueError("员工权限列表包含无效权限")
    result = set(values)
    if "medical.write" in result:
        result.add("medical")
    return [p for p in PERMISSIONS if p in result]


def _assignable(user):
    return (
        set(PERMISSIONS)
        if user["kind"] == "owner"
        else set(user["permissions"]) - {"staff.manage", "clinical.rules"}
    )


def _within_account_scope(user, target, assignable, area_check):
    return user["kind"] == "owner" or (
        target["kind"] == "staff"
        and target["id"] != user["id"]
        and set(target["permissions"]) <= assignable
        and (area_check is None or area_check(target))
    )


def _target(db, payload, user, area_check):
    target_id = payload.get("id")
    target = account(db, target_id) if isinstance(target_id, str) else None
    if user["kind"] != "owner" and (
        not target
        or not _within_account_scope(user, target, _assignable(user), area_check)
    ):
        raise PermissionError("未找到可管理的员工账号")
    if not target:
        raise ValueError("未找到该账号")
    return target


def _account_definition(user, p, target=None):
    kind = target["kind"] if target else p.get("kind")
    if user["kind"] != "owner" and kind != "staff":
        raise PermissionError("受托管理仅适用于员工账号")
    if kind == "family":
        if "portalSelf" in p and type(p["portalSelf"]) is not bool:
            raise ValueError("请核对绑定身份")
        return (
            kind,
            (
                target["role"]
                if target
                else "入住长者"
                if p.get("portalSelf")
                else "亲属"
            ),
            [],
        )
    if kind != "staff":
        raise ValueError("请选择员工或亲属账号")
    role = p.get("role", target["role"] if target else "护工")
    previous = target["permissions"] if target and target["role"] == role else None
    grants = _staff_grants(role, p.get("permissions", previous))
    if not set(grants) <= _assignable(user):
        raise PermissionError("授权项目超出本人可分配的范围")
    return kind, role, grants


def _family_services(p, kind, current=False):
    if "familyServices" not in p:
        return current
    if kind != "family" or type(p["familyServices"]) is not bool:
        raise ValueError("服务记录授权须为亲属账号的开关选项")
    return p["familyServices"]


def preview(db, user, payload, facility_policy=None):
    if not manages_accounts(user):
        raise PermissionError("此账号没有对应的管理权限")
    if not isinstance(payload, dict) or set(payload) - {
        "id",
        "kind",
        "role",
        "permissions",
    }:
        raise ValueError("权限预览字段无效")
    area_check = staff_scope.boundary(db, user, facility_policy)
    target = _target(db, payload, user, area_check) if "id" in payload else None
    if target and "kind" in payload and payload["kind"] != target["kind"]:
        raise ValueError("账号身份不可更改")
    if (
        target
        and target["kind"] == "family"
        and ("role" in payload or "permissions" in payload)
    ):
        raise ValueError("亲属账号不能授予员工权限")
    kind, role, grants = _account_definition(user, payload, target)
    draft = {"kind": kind, "role": role, "permissions": grants}
    if (
        target
        and area_check
        and not area_check({**target, **draft, "routes": resolve_routes(draft)})
    ):
        raise PermissionError("拟分配岗位的区域超出本人可管理的范围")
    return {
        **draft,
        "routes": resolve_routes(draft),
        "allowedActions": allowed_actions(draft),
    }


def _create(db, state, p, user, area_check):
    kind, role, grants = _account_definition(user, p)
    family_services = _family_services(p, kind)
    scopes = portal.scopes(p, kind)
    username = _required(p.get("username"), "登录名", 40).lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,39}", username):
        raise ValueError("登录名须为 3–40 位字母、数字、点、下划线或短横线")
    display = _required(p.get("displayName"), "姓名")
    password = _password(p.get("password"))
    resident_id = ""
    if kind == "family":
        resident_id = p.get("residentId")
        if not any(r["id"] == resident_id for r in state["residents"]):
            raise ValueError("请选择亲属已获授权的长者")
    elif p.get("residentId"):
        raise ValueError("员工账号无需绑定亲属关系")
    salt = secrets.token_bytes(16)
    account_id = uuid4().hex
    try:
        with staff_scope.verify_change(db, area_check, lambda: account(db, account_id)):
            db.execute(
                """INSERT INTO accounts(id,username,display_name,kind,role,permissions,resident_id,salt,password_hash,family_services,portal_scopes)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    account_id,
                    username,
                    display,
                    kind,
                    role,
                    json.dumps(grants),
                    resident_id,
                    salt,
                    _digest(password, salt),
                    int(family_services),
                    json.dumps(scopes),
                ),
            )
    except sqlite3.IntegrityError as error:
        raise ValueError("此登录名已被使用") from error
    return (
        f"创建{role}账号 {username}"
        + "".join("，授予" + portal.SCOPES[k] for k in scopes)
        + ("，授予已完成服务记录查阅权限" if family_services else "")
    )


def _update(db, p, target, user):
    if target["kind"] == "owner" or set(p) - {
        "id",
        "displayName",
        "role",
        "permissions",
        "enabled",
        "familyServices",
        "portalScopes",
    }:
        raise ValueError("只可修改员工或亲属的姓名、启用状态及员工岗位权限")
    enabled = p.get("enabled", target["enabled"])
    if type(enabled) is not bool:
        raise ValueError("启用状态无效")
    display = _required(p.get("displayName", target["displayName"]), "姓名")
    if target["kind"] == "family" and ("role" in p or "permissions" in p):
        raise ValueError("亲属账号不能授予员工权限")
    _, role, grants = _account_definition(user, p, target)
    family_services = _family_services(
        p, target["kind"], target.get("familyServices", False)
    )
    previous_scopes = target.get("portalScopes", [])
    scopes = portal.scopes(p, target["kind"], previous_scopes)
    db.execute(
        "UPDATE accounts SET display_name=?,role=?,permissions=?,enabled=?,family_services=?,portal_scopes=? WHERE id=?",
        (
            display,
            role,
            json.dumps(grants),
            int(enabled),
            int(family_services),
            json.dumps(scopes),
            target["id"],
        ),
    )
    if not enabled:
        db.execute("DELETE FROM sessions WHERE account_id=?", (target["id"],))
    changes = []
    for key, label in portal.SCOPES.items():
        if (key in scopes) != (key in previous_scopes):
            changes.append(("授予" if key in scopes else "收回") + label)
    if display != target["displayName"]:
        changes.append(f"姓名改为{display}")
    if role != target["role"]:
        changes.append(f"岗位改为{role}")
    for sign, keys in (
        ("授予", set(grants) - set(target["permissions"])),
        ("收回", set(target["permissions"]) - set(grants)),
    ):
        if keys:
            changes.append(sign + "、".join(PERMISSIONS[k] for k in sorted(keys)))
    if enabled != target["enabled"]:
        changes.append("启用" if enabled else "停用")
    if family_services != target.get("familyServices", False):
        changes.append(
            ("授予" if family_services else "收回") + "已完成服务记录查阅权限"
        )
    return f"更新账号 {target['username']}：" + "，".join(changes or ["保存当前配置"])


def _change_password(db, p, target):
    new_password = _password(p.get("password"))
    if target["kind"] == "owner":
        current = p.get("currentPassword")
        row = db.execute(
            "SELECT salt,password_hash FROM accounts WHERE id=?", (target["id"],)
        ).fetchone()
        if (
            not isinstance(current, str)
            or len(current) > 128
            or not hmac.compare_digest(
                _digest(current, row["salt"]), row["password_hash"]
            )
        ):
            raise ValueError("当前总管理员密码不正确")
    _replace_password(db, target, new_password)
    return f"重设 {target['username']} 的密码并结束旧会话"


def _settings(db, p):
    row = db.execute("SELECT * FROM institution_settings WHERE id=1").fetchone()
    visual = json.loads(row["visual"])
    known = set(DEFAULT_UI)
    if not p or set(p) - known:
        raise ValueError("设置内容无效")
    for key in ("brandName", "institutionName"):
        if key in p:
            visual[key] = _required(p[key], "名称", 30)
    if "theme" in p:
        if p["theme"] not in ("forest", "ocean", "plum"):
            raise ValueError("主题无效")
        visual["theme"] = p["theme"]
    if "hiddenRoutes" in p:
        routes = p["hiddenRoutes"]
        if not isinstance(routes, list) or not all(
            isinstance(r, str) and r in ROUTE_GRANTS and r != "overview" for r in routes
        ):
            raise ValueError("可见模块设置无效")
        visual["hiddenRoutes"] = list(dict.fromkeys(routes))
    db.execute(
        "UPDATE institution_settings SET visual=? WHERE id=1",
        (json.dumps(visual, ensure_ascii=False),),
    )
    return "更新机构界面设置"


def apply(db, state, action, payload, user, facility_policy=None):
    authorize(user, action, payload, state)
    area_check = staff_scope.boundary(db, user, facility_policy)
    if action == "access.create":
        return _create(db, state, payload, user, area_check)
    if action == "access.update":
        target = _target(db, payload, user, area_check)
        with staff_scope.verify_change(
            db, area_check, lambda: account(db, target["id"])
        ):
            return _update(db, payload, target, user)
    if action == "access.password":
        return _change_password(db, payload, _target(db, payload, user, area_check))
    if action == "access.settings":
        return _settings(db, payload)
    raise ValueError("未登记的账号管理操作")


def project(db, state, user, facility_policy=None):
    filtered = visible_data(state, user)
    row = db.execute("SELECT * FROM institution_settings WHERE id=1").fetchone()
    filtered.update(
        user=user,
        uiSettings=json.loads(row["visual"]),
        allowedActions=allowed_actions(user),
    )
    if user["kind"] == "family":
        portal.project(filtered, state, user)
    if user["kind"] == "family" and user.get("familyServices"):
        tasks = (
            r
            for r in state.get("tasks", ())
            if r["residentId"] == user["residentId"] and r["status"] == "已完成"
        )
        latest = sorted(
            tasks,
            key=lambda r: (
                r.get("completedAt") or r["date"],
                r["date"],
                r.get("time", ""),
                r["id"],
            ),
            reverse=True,
        )
        filtered["familyServiceHistory"] = [
            {k: r[k] for k in ("date", "time", "title", "completedAt") if k in r}
            for r in latest[:30]
        ]
    if manages_accounts(user):
        area_check = staff_scope.boundary(db, user, facility_policy)
        assignable = _assignable(user)
        accounts = (
            _public(row)
            for row in db.execute("SELECT * FROM accounts ORDER BY kind DESC,username")
        )
        owner = user["kind"] == "owner"
        filtered.update(
            accounts=[
                {**a, "allowedActions": allowed_actions(a)}
                for a in accounts
                if _within_account_scope(user, a, assignable, area_check)
            ],
            permissionOptions={
                key: label for key, label in PERMISSIONS.items() if key in assignable
            },
            rolePresets={
                role: [p for p in grants if p in assignable]
                for role, grants in PRESETS.items()
            },
            accessManagement={
                "scope": "institution" if owner else "staff",
                "canBindFamily": owner,
            },
        )
    return filtered


def change_own_password(db, user, payload):
    if set(payload) != {"currentPassword", "newPassword"}:
        raise ValueError("请提交本人当前密码和新密码")
    new_password = _password(payload["newPassword"])
    current = payload["currentPassword"]
    row = db.execute(
        "SELECT salt,password_hash FROM accounts WHERE id=?", (user["id"],)
    ).fetchone()
    if (
        not isinstance(current, str)
        or len(current) > 128
        or not hmac.compare_digest(_digest(current, row["salt"]), row["password_hash"])
    ):
        raise ValueError("当前密码不正确")
    if new_password == current:
        raise ValueError("新密码须与当前密码不同")
    _replace_password(db, user, new_password)
    return f"{user['username']}修改了本人密码并结束所有登录会话"


def _replace_password(db, target, new_password):
    salt = secrets.token_bytes(16)
    db.execute(
        "UPDATE accounts SET salt=?,password_hash=? WHERE id=?",
        (salt, _digest(new_password, salt), target["id"]),
    )
    db.execute("DELETE FROM sessions WHERE account_id=?", (target["id"],))
    db.execute("DELETE FROM login_failures WHERE subject=?", (target["id"],))
