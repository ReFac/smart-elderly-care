"""Rank care checks using a fixed vocabulary, a single metered call and no personal data."""

from contextlib import closing
import json
from uuid import uuid4

from .. import access, history, provider, rounds
from . import deepseek

CHECKS = {
    "past_due": "先核对已过计划时刻的工单，确认有无漏记或仍需跟进。",
    "upcoming": "核对本日其余待执行工单的时段及经办安排。",
    "completed": "交班时核对今日已登记完成的照护记录。",
}


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS rounds_priorities (
        report TEXT PRIMARY KEY, actor TEXT NOT NULL, request TEXT UNIQUE NOT NULL,
        generated_at TEXT NOT NULL, result TEXT NOT NULL DEFAULT '')""")


def candidates(report):
    today = report["today"]
    return [
        code
        for code, enabled in (
            ("past_due", today["overdue"] > 0),
            ("upcoming", today["pending"] > today["overdue"]),
            ("completed", today["completed"] > 0),
        )
        if enabled
    ]


def context(store, db, token, rid, report_id):
    actor = store.actor(db, token)
    access.require(actor, "assistants")
    access.require(actor, "care")
    revision, state = rounds.workspace(db)
    person = rounds.locate(db, state, actor, rid)
    report = rounds.latest(db, person)
    if not report or report["id"] != report_id:
        from ..store import Conflict

        raise Conflict("简报或床位已更新，请重新打开当前简报")
    return actor, revision, state, report


def view(db, actor, report, now):
    codes = candidates(report)
    row = db.execute(
        """SELECT p.generated_at,u.status,u.specialistIds,u.model,u.reason
        FROM rounds_priorities p JOIN api_usage u ON u.actor=p.actor AND u.request=p.request
        WHERE p.report=?""",
        (report["id"],),
    ).fetchone()
    if row:
        ids = json.loads(row["specialistIds"]) if row["status"] == "ok" else []
        return {
            "available": False,
            "status": row["status"],
            "reason": row["reason"],
            "generatedAt": row["generated_at"],
            "model": row["model"],
            "items": [CHECKS[x] for x in dict.fromkeys([*ids, *codes]) if x in codes]
            if ids
            else [],
        }
    return {
        "available": len(codes) >= 2
        and report["day"] == now.date().isoformat()
        and provider.status(db, actor, now)["available"],
        "items": [],
    }


def read(store, token, rid, report_id):
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        actor, _, _, report = context(store, db, token, rid, report_id)
        return view(db, actor, report, store.now())


def generate(store, token, rid, data, *, transport=None):
    from ..store import Conflict

    if (
        not isinstance(data, dict)
        or set(data) - {"reportId", "confirmed", "revision", "comment"}
        or data.get("confirmed") is not True
    ):
        raise ValueError("请确认将核对类别发送至 DeepSeek 并使用机构额度")
    comment = history.comment_text(data.get("comment", ""))
    now = store.now()
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        actor, rev, state, report = context(store, db, token, rid, data.get("reportId"))
        saved = view(db, actor, report, now)
        if "status" in saved:
            return saved
        if type(data.get("revision")) is not int or data["revision"] != rev:
            raise Conflict("工作台已更新，请刷新简报")
        if not saved["available"]:
            raise ValueError("当前简报缺少可排序的事项或机构套餐未就绪")
        codes = candidates(report)
        model = provider.model_name()
        body = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": 'Order provided care handover checks by review priority. Return JSON {"ids":[...]} using only the supplied codes.',
                },
                {"role": "user", "content": json.dumps(codes, separators=(",", ":"))},
            ],
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "max_tokens": 48,
            "stream": False,
        }
        plan = provider.latest(db)
        hold = len(json.dumps(body["messages"]).encode()) + body["max_tokens"] + 128
        if sum(provider.usage(db, plan["id"])) + hold > plan["tokenLimit"]:
            raise ValueError("本期套餐可用额度不足")
        key = provider.read_key()
        request = "rounds/" + uuid4().hex
        db.execute(
            """INSERT INTO api_usage(actor,request,planId,fingerprint,model,createdAt,status,allowance)
            VALUES(?,?,?,?,?,?,'pending',?)""",
            (
                actor["id"],
                request,
                plan["id"],
                report["id"],
                model,
                int(now.timestamp()),
                hold,
            ),
        )
        history.watch(db, "rounds.prioritize")
        db.execute(
            "INSERT INTO rounds_priorities(report,actor,request,generated_at) VALUES(?,?,?,?)",
            (report["id"], actor["id"], request, now.isoformat()),
        )
        rounds.audit(
            db,
            now,
            "rounds.prioritize",
            "确认 DeepSeek 对照护核对项排序",
            actor,
            state,
            rid,
            comment,
        )
    result = deepseek.complete(transport or deepseek.send, key, body, codes)
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        history.watch(db, "rounds.priorityResult")
        receipt = db.execute(
            """UPDATE api_usage SET status=?,reason=?,charged=?,specialistIds=?
            WHERE actor=? AND request=? AND status='pending'""",
            (
                result.status,
                result.reason,
                result.tokens,
                json.dumps(result.ids),
                actor["id"],
                request,
            ),
        )
        if not receipt.rowcount:
            provider.late_usage(
                db,
                actor["id"],
                request,
                result.tokens,
                store.now(),
                confirmed_zero=result.reason == "provider_rejected",
            )
            result = deepseek.Outcome("closed", "reconciled")
        db.execute(
            "UPDATE rounds_priorities SET generated_at=?,result=? WHERE report=?",
            (
                store.now().isoformat(),
                json.dumps({"status": result.status, "ids": result.ids}),
                report["id"],
            ),
        )
        rounds.audit(
            db,
            store.now(),
            "rounds.priorityResult",
            "DeepSeek 核对项排序已生成"
            if result.status == "ok"
            else "DeepSeek 核对项排序未完成",
            rounds.AGENT,
            state,
            rid,
        )
    return read(store, token, rid, report["id"])
