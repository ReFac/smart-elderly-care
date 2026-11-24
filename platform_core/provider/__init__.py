"""Platform-funded DeepSeek planning. One hosted workspace database owns one entitlement."""

import hashlib
import json
import os
import re
import stat
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .. import access_policy
from ..agents import specialists
from . import deepseek

DEFAULT_MODEL = "deepseek-flash"
ZONE = ZoneInfo("Asia/Shanghai")
PENDING_SECONDS = 90


def init(db):
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


def local_time(now=None):
    return now.astimezone(ZONE) if now else datetime.now(ZONE)


def latest(db):
    return db.execute("SELECT * FROM api_plans ORDER BY id DESC LIMIT 1").fetchone()


def usage(db, plan_id):
    row = db.execute(
        """SELECT COALESCE(SUM(charged),0),COALESCE(SUM(
                CASE WHEN status IN ('pending','uncertain') THEN allowance ELSE 0 END),0)
            FROM api_usage WHERE planId=?""",
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
    if not row or not (
        row["status"] == "uncertain"
        or (
            row["status"] == "pending"
            and row["createdAt"] + PENDING_SECONDS < local_time(now).timestamp()
        )
    ):
        raise ValueError("只有结果不明或已超时的预留可结算")
    if type(actual) is not int or not 0 <= actual <= row["allowance"]:
        raise ValueError("实际用量必须在本笔预留范围内")
    db.execute(
        "UPDATE api_usage SET status='closed',reason='reconciled',charged=? WHERE actor=? AND request=?",
        (actual, actor, request),
    )


def model_name():
    value = os.environ.get("NH_DEEPSEEK_MODEL", DEFAULT_MODEL)
    return value if re.fullmatch(r"[A-Za-z0-9._-]{1,80}", value) else ""


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


def configured():
    if os.environ.get("DEEPSEEK_API_KEY", "").strip():
        return True
    path = key_file()
    try:
        return path is not None and private_file(path.lstat())
    except OSError:
        return False


def read_key():
    value = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not value and os.name == "posix" and (path := key_file()):
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
            if not private_file(os.fstat(stream.fileno())):
                raise ValueError("平台凭据文件权限无效")
            value = stream.read(513).decode("ascii").strip()
    if (
        not value
        or len(value) > 512
        or not value.isascii()
        or any(c.isspace() for c in value)
    ):
        raise ValueError("平台凭据不可用")
    return value


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
    return decision("local", row["reason"] or "uncertain", row["model"])


def plan(connect, authorize, goal, request_id, *, now=None, transport=None):
    when = local_time(now)
    if not isinstance(goal, str) or not 1 <= len(goal.strip()) <= 500:
        raise ValueError("任务目标须为 1 至 500 字")
    if not isinstance(request_id, str) or not 1 <= len(request_id.strip()) <= 100:
        raise ValueError("规划请求编号无效")
    goal, request_id = goal.strip(), request_id.strip()
    fingerprint = hashlib.sha256(goal.encode("utf-8")).hexdigest()
    with closing(connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        user = authorize(db)
        access_policy.require(user, "assistants")
        specs = specialists(user)
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
            return decision("local", cap["state"], model)
        body = deepseek.request_body(model, goal, specs)
        if body is None:
            return decision("local", "no_signal", model)
        try:
            key = read_key()
        except (OSError, ValueError):
            return decision("local", "unconfigured", model)
        entitlement = latest(db)
        # Each UTF-8 byte can represent at most one byte-fallback token.
        allowance = (
            len(json.dumps(body["messages"], ensure_ascii=False).encode())
            + body["max_tokens"]
            + 128
        )
        if sum(usage(db, entitlement["id"])) + allowance > entitlement["tokenLimit"]:
            return decision("local", "exhausted", model)
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
        db.execute(
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
