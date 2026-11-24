"""Platform-funded DeepSeek planning. One hosted workspace database owns one entitlement."""

import hashlib
import json
import os
import stat
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .. import access_policy
from ..agents import specialists
from . import deepseek, late_receipts, search_usage
from .late_receipts import late_usage as late_usage, unsettled as unsettled

DEFAULT_MODEL = "deepseek-flash"
ZONE = ZoneInfo("Asia/Shanghai")
PENDING_SECONDS = 90


def init(db):
    from . import generation, media, round_priorities

    media.init(db)
    round_priorities.init(db)
    db.execute("""CREATE TABLE IF NOT EXISTS api_plans (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, tokenLimit INTEGER NOT NULL,
        startsOn TEXT NOT NULL, expiresOn TEXT NOT NULL, enabled INTEGER NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS api_usage (
        actor TEXT NOT NULL, request TEXT NOT NULL, planId INTEGER NOT NULL REFERENCES api_plans(id),
        fingerprint TEXT NOT NULL, model TEXT NOT NULL, createdAt INTEGER NOT NULL,
        status TEXT NOT NULL, allowance INTEGER NOT NULL, charged INTEGER NOT NULL DEFAULT 0,
        specialistIds TEXT NOT NULL DEFAULT '[]', reason TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(actor,request))""")
    db.execute("CREATE INDEX IF NOT EXISTS api_usage_plan ON api_usage(planId)")
    search_usage.init(db)
    late_receipts.init(db)
    generation.init(db)


def local_time(now=None):
    return now.astimezone(ZONE) if now else datetime.now(ZONE)


def latest(db):
    return db.execute("SELECT * FROM api_plans ORDER BY id DESC LIMIT 1").fetchone()


def usage(db, plan_id):
    row = db.execute(
        """SELECT COALESCE(SUM(u.charged + COALESCE(l.verified-l.original,0)),0),
            COALESCE(SUM(CASE WHEN u.status IN ('pending','uncertain') THEN u.allowance
                WHEN l.verified IS NULL AND l.reported>l.original THEN l.reported-l.original ELSE 0 END),0)
            FROM api_usage u LEFT JOIN api_late_usage l ON l.actor=u.actor AND l.request=u.request
            WHERE u.planId=?""",
        (plan_id,),
    ).fetchone()
    return row[0], row[1]


def grant(db, name, limit, expires, now=None):
    """Called solely by operator CLI in a write transaction after payment is verified."""
    today = local_time(now).date().isoformat()
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
        raise ValueError("套餐名称须为 1 至 60 字")
    if type(limit) is not int or not 1 <= limit <= 1_000_000_000:
        raise ValueError("套餐额度须为 1 至 10 亿 token")
    if (
        not isinstance(expires, str)
        or date.fromisoformat(expires).isoformat() != expires
        or expires < today
    ):
        raise ValueError("到期日期应为当日或之后的 YYYY-MM-DD")
    previous = latest(db)
    if previous and previous["expiresOn"] >= today:
        if limit < sum(usage(db, previous["id"])):
            raise ValueError("套餐额度低于本期已用和预留的合计")
        db.execute(
            "UPDATE api_plans SET name=?,tokenLimit=?,expiresOn=?,enabled=1 WHERE id=?",
            (name.strip(), limit, expires, previous["id"]),
        )
    else:
        db.execute(
            "INSERT INTO api_plans(name,tokenLimit,startsOn,expiresOn,enabled) VALUES(?,?,?,?,1)",
            (name.strip(), limit, today, expires),
        )


def disable(db):
    plan = latest(db)
    if plan:
        db.execute("UPDATE api_plans SET enabled=0 WHERE id=?", (plan["id"],))


def reconcile(db, actor, request, actual, now=None):
    """Settle an uncertain reservation using the platform's provider billing records."""
    row = db.execute(
        "SELECT * FROM api_usage WHERE actor=? AND request=?", (actor, request)
    ).fetchone()
    if not row or type(actual) is not int or not 0 <= actual <= row["allowance"]:
        raise ValueError("实际用量必须在已登记的本笔预留范围内")
    settled = local_time(now)
    if db.execute(
        """UPDATE api_late_usage SET verified=?,verifiedAt=?
          WHERE actor=? AND request=? AND verified IS NULL""",
        (actual, int(settled.timestamp()), actor, request),
    ).rowcount:
        return
    if not (
        row["status"] == "uncertain"
        or (
            row["status"] == "pending"
            and row["createdAt"] + PENDING_SECONDS < settled.timestamp()
        )
    ):
        raise ValueError("仅结果不明、已超时或收到未核对的迟到回执时可结算")
    db.execute(
        "UPDATE api_usage SET status='closed',reason='reconciled',charged=? WHERE actor=? AND request=?",
        (actual, actor, request),
    )


def model_name():
    return DEFAULT_MODEL


def key_file():
    path = os.environ.get("NH_DEEPSEEK_KEY_FILE")
    if not path:
        return None
    return Path(path)


def private_file(metadata):
    return (
        os.name == "posix"
        and stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == os.geteuid()
        and not metadata.st_mode & 0o077
        and 0 < metadata.st_size <= 512
    )


def backend_vault_enabled():
    return bool(
        os.environ.get("NH_PLATFORM_VAULT") or "NH_DEEPSEEK_KEY_FILE" not in os.environ
    )


def configured():
    from .. import operational_secrets, secure_storage

    if os.environ.get("DEEPSEEK_API_KEY", "").strip():
        return True
    try:
        if path := key_file():
            return private_file(path.lstat())
        if backend_vault_enabled():
            with closing(
                operational_secrets.connect(operational_secrets.vault_path())
            ) as db:
                return (
                    db.execute("SELECT 1 FROM secrets WHERE name='deepseek'").fetchone()
                    is not None
                )
    except (OSError, ValueError, secure_storage.cipherdb.Error):
        pass
    return False


def read_key():
    from .. import operational_secrets, secure_storage

    value = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not value and (path := key_file()):
        if os.name != "posix":
            raise ValueError("平台凭据文件权限无效")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if not private_file(os.fstat(fd)):
                raise ValueError("平台凭据文件权限无效")
            raw = stream.read(513)
    elif not value and backend_vault_enabled():
        try:
            raw = operational_secrets.read_value(
                operational_secrets.vault_path(), "deepseek"
            )
        except (OSError, ValueError, secure_storage.cipherdb.Error):
            raise ValueError("平台运维密库不可用") from None
    else:
        raw = b""
    if not value:
        try:
            value = raw.decode("ascii").strip()
        except UnicodeDecodeError:
            raise ValueError("平台凭据格式无效") from None
    if not operational_secrets.valid_key(value):
        raise ValueError("平台凭据不可用")
    return value


def media_overview(db):
    from .media import overview

    return overview(db)


def status(db, user, now=None):
    access_policy.require(user, "assistants")
    today = local_time(now).date().isoformat()
    plan = latest(db)
    used, held = usage(db, plan["id"]) if plan else (0, 0)
    model = model_name()
    reason = "available"
    if not specialists(user):
        reason = "no_scope"
    elif (
        not plan
        or not plan["enabled"]
        or not plan["startsOn"] <= today <= plan["expiresOn"]
    ):
        reason = "inactive"
    elif used + held >= plan["tokenLimit"]:
        reason = "exhausted"
    elif not model or not configured():
        reason = "unconfigured"
    result = {"state": reason, "available": reason == "available", "model": model}
    if user["kind"] == "owner":
        result.update(
            planName=plan["name"] if plan else "",
            expiresOn=plan["expiresOn"] if plan else "",
            tokenLimit=plan["tokenLimit"] if plan else 0,
            tokensUsed=used,
            tokensReserved=held,
            media=media_overview(db),
            readAloud=dict(db.execute("""SELECT COALESCE(sum(charged),0) AS characters,
                COALESCE(sum(CASE WHEN state IN ('pending','uncertain') THEN reserved ELSE 0 END),0) AS held
                FROM media_usage WHERE plan=? AND kind='tts'""", (plan["id"] if plan else 0,)).fetchone()),
            webSearch=search_usage.overview(db, plan["id"] if plan else None),
        )
    return result


def decision(mode, reason, model, ids=()):
    return {"mode": mode, "reason": reason, "model": model, "specialistIds": list(ids)}


def replay(row, allowed, fingerprint, now):
    if row["fingerprint"] != fingerprint:
        raise ValueError("该规划请求编号已对应另一项目标")
    if (
        row["status"] == "pending"
        and row["createdAt"] + PENDING_SECONDS >= now.timestamp()
    ):
        raise ValueError("该云端规划正在处理，请稍后重试")
    ids = json.loads(row["specialistIds"])
    if ids and not set(ids) <= set(allowed):
        raise PermissionError("此任务涉及的部分业务域授权已收回")
    if row["status"] == "ok":
        return decision("deepseek", "ready", row["model"], ids)
    return decision("unavailable", row["reason"] or "uncertain", row["model"])


def plan(
    connect,
    authorize,
    goal,
    request_id,
    *,
    now=None,
    transport=None,
    allowed_specs=None,
    scope_key="",
):
    when = local_time(now)
    if not isinstance(goal, str) or not 1 <= len(goal.strip()) <= 500:
        raise ValueError("任务目标须为 1 至 500 字")
    if not isinstance(request_id, str) or not 1 <= len(request_id.strip()) <= 100:
        raise ValueError("规划请求编号无效")
    goal, request_id = goal.strip(), request_id.strip()
    identity = json.dumps([goal, scope_key], ensure_ascii=False) if scope_key else goal
    fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    with closing(connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        user = authorize(db)
        access_policy.require(user, "assistants")
        specs = specialists(user)
        if allowed_specs is not None:
            granted = {s.key for s in allowed_specs}
            specs = tuple(s for s in specs if s.key in granted)
        allowed = tuple(s.key for s in specs)
        if not allowed:
            raise PermissionError("尚未分配协作业务域")
        uid = user["id"]
        previous = db.execute(
            "SELECT * FROM api_usage WHERE actor=? AND request=?", (uid, request_id)
        ).fetchone()
        if previous:
            return replay(previous, allowed, fingerprint, when)
        cap = status(db, user, when)
        model = cap["model"]
        if not cap["available"]:
            return decision("unavailable", cap["state"], model)
        body = deepseek.request_body(model, goal, specs)
        if body is None:
            return decision("unavailable", "no_signal", model)
        try:
            key = read_key()
        except (OSError, ValueError):
            return decision("unavailable", "unconfigured", model)
        entitlement = latest(db)
        # Each UTF-8 byte can represent at most one byte-fallback token.
        allowance = (
            len(json.dumps(body["messages"], ensure_ascii=False).encode())
            + body["max_tokens"]
            + 128
        )
        if sum(usage(db, entitlement["id"])) + allowance > entitlement["tokenLimit"]:
            return decision("unavailable", "exhausted", model)
        db.execute(
            """INSERT INTO api_usage
            (actor,request,planId,fingerprint,model,createdAt,status,allowance)
            VALUES(?,?,?,?,?,?,'pending',?)""",
            (
                uid,
                request_id,
                entitlement["id"],
                fingerprint,
                model,
                int(when.timestamp()),
                allowance,
            ),
        )
    # The network call never holds a workspace transaction. Unknown billing keeps its reservation.
    outcome = deepseek.complete(transport or deepseek.send, key, body, allowed)
    with closing(connect()) as db, db:
        receipt = db.execute(
            """UPDATE api_usage SET status=?,charged=?,specialistIds=?,reason=?
            WHERE actor=? AND request=? AND status='pending'""",
            (
                outcome.status,
                outcome.tokens,
                json.dumps(outcome.ids),
                outcome.reason,
                uid,
                request_id,
            ),
        )
        if not receipt.rowcount:
            late_usage(
                db,
                uid,
                request_id,
                outcome.tokens,
                when,
                confirmed_zero=outcome.reason == "provider_rejected",
            )
    with closing(connect()) as db, db:
        db.execute("BEGIN")
        current = authorize(db)
        access_policy.require(current, "assistants")
        if current["id"] != uid:
            raise PermissionError("会话身份已更改")
        row = db.execute(
            "SELECT * FROM api_usage WHERE actor=? AND request=?", (uid, request_id)
        ).fetchone()
        return replay(row, [s.key for s in specialists(current)], fingerprint, when)
