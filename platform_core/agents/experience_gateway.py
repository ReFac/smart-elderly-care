"""Short-lived, revocable handoff of one reviewed writing skill to a local Gateway."""

from contextlib import closing
from hashlib import sha256
import os
import re
import secrets
import time

from .. import access
from . import growth


def enabled():
    return os.environ.get("NH_EXPERIENCE_GATEWAY") == "1"


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS agent_rule_gateway_tickets (
        digest TEXT PRIMARY KEY, session TEXT NOT NULL, campus TEXT NOT NULL, topic TEXT NOT NULL,
        version INTEGER NOT NULL, gateway_owner TEXT NOT NULL, expires INTEGER NOT NULL,
        UNIQUE(session,campus,topic,gateway_owner))""")


def _approved(db, actor, body):
    campus, topic = growth._area_and_topic(db, actor, body)
    if not growth._can_review(actor):
        raise PermissionError("同步到 Gateway 需要规则审核权限")
    version, _ = growth._current(db, campus, topic)
    if type(body.get("version")) is not int or body["version"] != version or version == 0:
        raise ValueError("请选择当前已批准的技能版本")
    artifact = growth._released_skill(db, campus, topic, version)
    if not artifact:
        raise ValueError("旧版本尚未保留经过 DeerFlow 检查的原件")
    return {"campus": campus, "name": "careops-" + topic, "version": version,
            "digest": artifact["digest"], "document": artifact["document"]}


def issue(store, token, body):
    if not enabled():
        raise PermissionError("本机构未启用 Gateway 同步")
    growth._body(body, ("campusId", "topic", "version", "gatewayOwner", "confirm"))
    owner = body.get("gatewayOwner")
    if body.get("confirm") is not True or not isinstance(owner, str) or not re.fullmatch(r"[A-Za-z0-9._@-]{1,128}", owner):
        raise ValueError("请确认目标 Gateway 账号")
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        actor = store.actor(db, token)
        approved = _approved(db, actor, body)
        init(db)
        now = int(time.time())
        ticket = secrets.token_urlsafe(32)
        db.execute("DELETE FROM agent_rule_gateway_tickets WHERE expires<=?", (now,))
        db.execute("INSERT OR REPLACE INTO agent_rule_gateway_tickets VALUES(?,?,?,?,?,?,?)",
                   (sha256(ticket.encode()).hexdigest(), access._token_hash(token), approved["campus"], body["topic"],
                    approved["version"], owner, now + 300))
        growth._audit(db, approved["campus"], body["topic"], "gateway-export", actor,
                      store.now().isoformat(timespec="seconds"), approved["version"])
        return {"ticket": ticket, "expires": now + 300, "digest": approved["digest"], "gatewayOwner": owner}


def exchange(store, body):
    if not enabled():
        raise PermissionError("本机构未启用 Gateway 同步")
    growth._body(body, ("ticket", "gatewayOwner"))
    ticket = body.get("ticket")
    if (not isinstance(ticket, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", ticket)
            or not isinstance(body.get("gatewayOwner"), str)):
        raise PermissionError("无效的技能同步凭证")
    with closing(store.connect()) as db:
        db.execute("BEGIN")
        init(db)
        row = db.execute("""SELECT * FROM agent_rule_gateway_tickets WHERE digest=? AND expires>?
            AND gateway_owner=?""", (sha256(ticket.encode()).hexdigest(), int(time.time()), body.get("gatewayOwner"))).fetchone()
        actor = access.account_from_session_hash(db, row["session"]) if row else None
        if not actor:
            raise PermissionError("凭证已失效或账号不匹配")
        return _approved(db, store.scoped_actor(db, actor),
                         {"campusId": row["campus"], "topic": row["topic"], "version": row["version"]})
