"""Local accounts, revocable sessions and owner-managed institution settings."""

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from uuid import uuid4

from . import campus_access, identity, portal, staff_scope
from .secure_storage import INTEGRITY_ERRORS

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
DEFAULT_MODEL = "deepseek-flash"


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


DUTIES = (
    "入住接待",
    "日常照护",
    "临床护理",
    "康复支持",
    "财务结算",
    "后勤物资",
    "运营管理",
    "家属联络",
)


def _duties(payload, kind, current=()):
    values = payload.get("staffDuties", list(current))
    if (
        not isinstance(values, list)
        or any(v not in DUTIES for v in values)
        or (kind != "staff" and values)
    ):
        raise ValueError("请选择员工职责")
    return [v for v in DUTIES if v in values]


def init(db, initial_owner_password=None):
    """Existing credentials retain only their salted scrypt verifier."""
    db.execute("PRAGMA secure_delete=ON")
    db.execute("DROP TABLE IF EXISTS storage_bootstrap")
    db.execute("""CREATE TABLE IF NOT EXISTS accounts (
      id TEXT PRIMARY KEY, username TEXT UNIQUE COLLATE NOCASE NOT NULL,
      display_name TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('owner','staff','family')),
      role TEXT NOT NULL, permissions TEXT NOT NULL DEFAULT '[]', resident_id TEXT NOT NULL DEFAULT '',
      enabled INTEGER NOT NULL DEFAULT 1, salt BLOB NOT NULL, password_hash BLOB NOT NULL,
      family_services INTEGER NOT NULL DEFAULT 0 CHECK(family_services IN (0,1)))""")
    identity.init(db)
    from . import staff_employment

    staff_employment.init(db)
    if "activation_pending" not in {
        r[1] for r in db.execute("PRAGMA table_info(accounts)")
    }:
        db.execute(
            "ALTER TABLE accounts ADD COLUMN activation_pending INTEGER NOT NULL DEFAULT 0"
        )
    if "staff_duties" not in {r[1] for r in db.execute("PRAGMA table_info(accounts)")}:
        db.execute(
            "ALTER TABLE accounts ADD COLUMN staff_duties TEXT NOT NULL DEFAULT '[]'"
        )
    if "family_services" not in {
        r[1] for r in db.execute("PRAGMA table_info(accounts)")
    }:
        db.execute(
            "ALTER TABLE accounts ADD COLUMN family_services INTEGER NOT NULL DEFAULT 0 CHECK(family_services IN (0,1))"
        )
    if "campus_id" not in {r[1] for r in db.execute("PRAGMA table_info(accounts)")}:
        db.execute("ALTER TABLE accounts ADD COLUMN campus_id TEXT")
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
                _digest(
                    _password(
                        initial_owner_password
                        or os.environ.get("NH_OWNER_PASSWORD")
                        or secrets.token_urlsafe(32)
                    ),
                    salt,
                ),
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
        "activationPending": bool(row["activation_pending"]),
        "permissions": list(PERMISSIONS)
        if row["kind"] == "owner"
        else json.loads(row["permissions"]),
    }
    if row["kind"] == "staff":
        user["staffDuties"] = json.loads(row["staff_duties"])
    if row["kind"] == "staff" and row["campus_id"]:
        user["facilityScope"] = {"campusIds": [row["campus_id"]]}
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


def _campus(db, user, p, kind, target=None):
    local = (target or {}).get("facilityScope", {}).get("campusIds", [])
    granted = user.get("facilityScope", {}).get("campusIds")
    default = local[0] if local else ""
    if target is None and granted:
        default = granted[0]
    key = p.get("campusId", default)
    if not isinstance(key, str) or (key and kind != "staff"):
        raise ValueError("分院授权仅适用于员工账号")
    if granted is not None and key not in granted:
        raise PermissionError("只能为员工分配获授权的分院")
    if (
        key
        and not db.execute(
            "SELECT 1 FROM facility_campuses WHERE id=?", (key,)
        ).fetchone()
    ):
        raise ValueError("请选择已登记的分院")
    return key


def preview(db, user, payload, facility_policy=None):
    if not manages_accounts(user):
        raise PermissionError("此账号没有对应的管理权限")
    if not isinstance(payload, dict) or set(payload) - {
        "id",
        "kind",
        "role",
        "permissions",
        "campusId",
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
    campus = _campus(db, user, payload, kind, target)
    if campus:
        draft["facilityScope"] = {"campusIds": [campus]}
    if (
        target
        and area_check
        and not area_check({**target, **draft, "routes": resolve_routes(draft)})
    ):
        raise PermissionError("拟分配岗位的区域超出本人可管理的范围")
    return {
        **draft,
        "permissions": [g for g in grants if has(draft, g)],
        "routes": resolve_routes(draft),
        "allowedActions": allowed_actions(draft),
    }


def _create(db, state, p, user, area_check):
    kind, role, grants = _account_definition(user, p)
    campus = _campus(db, user, p, kind)
    family_services = _family_services(p, kind)
    scopes = portal.scopes(p, kind, portal_self=role == "入住长者")
    username = _required(p.get("username"), "登录名", 40).lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,39}", username):
        raise ValueError("登录名须为 3–40 位字母、数字、点、下划线或短横线")
    display = _required(p.get("displayName"), "姓名")
    invitation = p.get("invitation")
    if invitation is not None:
        if (
            "password" in p
            or not isinstance(invitation, dict)
            or set(invitation) != {"channel", "destination"}
        ):
            raise ValueError("请指定本人激活账号的验证方式")
        invite_to = identity.destination(
            invitation["channel"], invitation["destination"]
        )
        password = secrets.token_urlsafe(32)
    else:
        password = _password(p.get("password"))
    duties = _duties(p, kind)
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
                """INSERT INTO accounts(id,username,display_name,kind,role,permissions,resident_id,salt,password_hash,family_services,portal_scopes,campus_id)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                    campus or None,
                ),
            )
            db.execute(
                "UPDATE accounts SET staff_duties=? WHERE id=?",
                (json.dumps(duties), account_id),
            )
            if invitation:
                db.execute(
                    "UPDATE accounts SET activation_pending=1 WHERE id=?", (account_id,)
                )
                db.execute(
                    "INSERT INTO identity_contacts VALUES(?,?,?,0)",
                    (account_id, invitation["channel"], invite_to),
                )
    except INTEGRITY_ERRORS as error:
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
        "staffDuties",
        "invitation",
        "portalScopes",
        "campusId",
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
    campus = _campus(db, user, p, target["kind"], target)
    previous_scopes = target.get("portalScopes", [])
    scopes = portal.scopes(p, target["kind"], previous_scopes, portal_self=target.get("portalSelf", False))
    db.execute(
        "UPDATE accounts SET display_name=?,role=?,permissions=?,enabled=?,family_services=?,portal_scopes=?,campus_id=? WHERE id=?",
        (
            display,
            role,
            json.dumps(grants),
            int(enabled),
            int(family_services),
            json.dumps(scopes),
            campus or None,
            target["id"],
        ),
    )
    duties = _duties(p, target["kind"], target.get("staffDuties", ()))
    db.execute(
        "UPDATE accounts SET staff_duties=? WHERE id=?",
        (json.dumps(duties), target["id"]),
    )
    if "invitation" in p:
        invitation = p["invitation"]
        if (
            not target["activationPending"]
            or not isinstance(invitation, dict)
            or set(invitation) != {"channel", "destination"}
        ):
            raise PermissionError("仅待首次激活的账号可由账号管理人员更正邀请地址")
        address = identity.destination(invitation["channel"], invitation["destination"])
        db.execute("DELETE FROM identity_contacts WHERE account_id=?", (target["id"],))
        db.execute(
            "DELETE FROM identity_challenges WHERE account_id=?", (target["id"],)
        )
        db.execute(
            "INSERT INTO identity_contacts VALUES(?,?,?,0)",
            (target["id"], invitation["channel"], address),
        )
    if not enabled:
        db.execute(
            "DELETE FROM identity_challenges WHERE account_id=?", (target["id"],)
        )
        db.execute("DELETE FROM sessions WHERE account_id=?", (target["id"],))
    changes = ["已更新待激活邀请渠道"] if "invitation" in p else []
    if duties != target.get("staffDuties", []):
        changes.append("已更新岗位职责")
    if (target.get("facilityScope", {}).get("campusIds") or [""])[0] != campus:
        changes.append(
            "分院授权调整为"
            + (
                db.execute(
                    "SELECT name FROM facility_campuses WHERE id=?", (campus,)
                ).fetchone()[0]
                if campus
                else "全机构"
            )
        )
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
        raise PermissionError("密码须由账号本人通过验证码设置")
    if action == "access.settings":
        return _settings(db, payload)
    raise ValueError("未登记的账号管理操作")


def project(db, state, user, facility_policy=None):
    projected = campus_access.projection(db, state, user)
    filtered = visible_data(projected, user)
    if user["kind"] in ("staff", "owner") and (has(user, "care") or has(user, "intake")):
        from .care.residency import current_cards

        filtered["currentBedCards"] = current_cards(state, projected.get("residents", ()))
    if filtered.get("referrals"):
        # Receipts stay visible. Their historical payload is served only after a current consent check.
        filtered["referrals"] = [
            {
                **ref,
                "exports": [
                    {k: v for k, v in entry.items() if k != "content"}
                    for entry in ref.get("exports", [])
                ],
            }
            for ref in filtered["referrals"]
        ]
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
    if (
        manages_accounts(user)
        or has(user, "intake")
        or has(user, "shifts")
        or campus_access.bound(user)
    ) and db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='facility_campuses'"
    ).fetchone():
        filtered["campusOptions"] = [
            dict(r)
            for r in db.execute("SELECT id,name FROM facility_campuses ORDER BY rowid")
            if not campus_access.bound(user)
            or r["id"] in user["facilityScope"]["campusIds"]
        ]
    if manages_accounts(user):
        area_check = staff_scope.boundary(db, user, facility_policy)
        assignable = _assignable(user)
        accounts = (
            _public(row)
            for row in db.execute("SELECT * FROM accounts ORDER BY kind DESC,username")
        )
        paydays = dict(db.execute("SELECT account_id,payday FROM staff_paydays"))
        owner = user["kind"] == "owner"
        filtered.update(
            accounts=[
                {**a, "allowedActions": allowed_actions(a), **({"payday": paydays[a["id"]]} if a["id"] in paydays else {})}
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
                "staffDuties": list(DUTIES),
            },
        )
    return filtered


def change_own_password(db, user, payload):
    raise ValueError("请通过本人已绑定的邮箱或手机验证码修改密码")


def _replace_password(db, target, new_password):
    salt = secrets.token_bytes(16)
    db.execute(
        "UPDATE accounts SET salt=?,password_hash=? WHERE id=?",
        (salt, _digest(new_password, salt), target["id"]),
    )
    db.execute("DELETE FROM sessions WHERE account_id=?", (target["id"],))
    db.execute("DELETE FROM login_failures WHERE subject=?", (target["id"],))
