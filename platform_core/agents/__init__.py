"""Single-institution agent runs and durable, permission-checked approval checkpoints."""

import json
from uuid import uuid4

from . import runtime
from .contracts import SPECIALISTS, contract
from .. import access_policy as policy
from ..activity import for_person
from ..operations.records import text_field, new_id


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS agent_runs (
        id TEXT PRIMARY KEY, actor TEXT NOT NULL, request TEXT NOT NULL, args TEXT NOT NULL,
        actorName TEXT NOT NULL, started TEXT NOT NULL, revision INTEGER NOT NULL,
        status TEXT NOT NULL, artifacts TEXT NOT NULL, UNIQUE(actor,request))""")
    db.execute("""CREATE TABLE IF NOT EXISTS agent_events (
        runId TEXT NOT NULL REFERENCES agent_runs(id), seq INTEGER NOT NULL, at TEXT NOT NULL,
        agent TEXT NOT NULL, event TEXT NOT NULL, message TEXT NOT NULL, parent TEXT NOT NULL,
        PRIMARY KEY(runId,seq))""")
    db.execute("""CREATE TABLE IF NOT EXISTS agent_audit_scope (
        runId TEXT PRIMARY KEY REFERENCES agent_runs(id),
        grants TEXT NOT NULL, residentId TEXT NOT NULL, room TEXT NOT NULL)""")


def audit_context(db, run_id):
    row = db.execute(
        "SELECT residentId,room FROM agent_audit_scope WHERE runId=?", (run_id,)
    ).fetchone()
    return {"agentRunId": run_id, **(dict(row) if row else {})}


def specialists(user):
    if not policy.has(user, "assistants"):
        return ()
    return tuple(item for item in SPECIALISTS if policy.has(user, item.grant))


def capabilities(user):
    policy.require(user, "assistants")
    return contract(user, specialists(user))


class Trace:
    def __init__(self, db, run_id, at):
        self.db, self.run_id, self.at = db, run_id, at
        self.seq = db.execute(
            "SELECT COALESCE(MAX(seq),0) FROM agent_events WHERE runId=?", (run_id,)
        ).fetchone()[0]

    def append(self, agent, event, message, parent=""):
        self.seq += 1
        self.db.execute(
            "INSERT INTO agent_events VALUES (?,?,?,?,?,?,?)",
            (self.run_id, self.seq, self.at, agent, event, message, parent),
        )


def summary(row):
    args = json.loads(row["args"])
    return dict(
        id=row["id"],
        actorName=row["actorName"],
        started=row["started"],
        goal=args["goal"],
        residentId=args["residentId"],
        status=row["status"],
        sourceRevision=row["revision"],
        agents=[a["agent"] for a in json.loads(row["artifacts"])],
    )


def visible(row, user):
    return (user["kind"] == "owner" or row["actor"] == user["id"]) and all(
        a["agent"] in {s.key for s in specialists(user)}
        for a in json.loads(row["artifacts"])
    )


def listing(db, user):
    if not specialists(user):
        return []
    query = "SELECT * FROM agent_runs"
    args = ()
    if user["kind"] != "owner":
        query += " WHERE actor=?"
        args = (user["id"],)
    result = []
    for row in db.execute(query + " ORDER BY rowid DESC", args):
        if visible(row, user):
            result.append(summary(row))
        if len(result) == 80:
            break
    return result


def get_row(db, user, run_id):
    policy.require(user, "assistants")
    row = db.execute("SELECT * FROM agent_runs WHERE id=?", (run_id,)).fetchone()
    if not row or not visible(row, user):
        raise FileNotFoundError("找不到可访问的协作任务")
    return row


def detail(db, user, run_id):
    row = get_row(db, user, run_id)
    return {
        **summary(row),
        "artifacts": json.loads(row["artifacts"]),
        "events": [
            dict(x)
            for x in db.execute(
                "SELECT * FROM agent_events WHERE runId=? ORDER BY seq", (run_id,)
            )
        ],
    }


def apply(db, state, action, payload, user, now, revision, planning=None):
    at = now.isoformat(timespec="seconds")
    today = now.date().isoformat()
    if action == "agent.start":
        goal = text_field(payload, "goal", "任务目标", 500)
        request = text_field(payload, "requestId", "请求标识", 100)
        resident = payload.get("residentId", "")
        scope = payload.get("scope", "auto")
        if not isinstance(resident, str) or not isinstance(scope, str):
            raise ValueError("任务范围无效")
        arguments = dict(goal=goal, residentId=resident, scope=scope)
        if payload.get("planning", "local") not in ("platform", "local"):
            raise ValueError("规划模式无效")
        if payload.get("planning") == "platform":
            arguments["planning"] = "platform"
        args = json.dumps(arguments, ensure_ascii=False)
        prior = db.execute(
            "SELECT * FROM agent_runs WHERE actor=? AND request=?",
            (user["id"], request),
        ).fetchone()
        if prior:
            if prior["args"] != args:
                raise ValueError("请求标识已被另一项任务使用")
            get_row(db, user, prior["id"])
            return "已登记同一协作任务", prior["id"]
        run_id = "run-" + uuid4().hex
        db.execute(
            "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                user["id"],
                request,
                args,
                user["displayName"],
                at,
                revision,
                "awaiting_approval",
                "[]",
            ),
        )
        log = Trace(db, run_id, at)
        log.append("coordinator", "run.started", "开始处理委托")
        if planning:
            log.append(
                "coordinator",
                "planner.selected",
                planning["model"]
                if planning["mode"] == "deepseek"
                else "本地规则 · " + planning["reason"],
            )
        outputs = runtime.execute(
            goal,
            specialists(user),
            scope,
            state,
            resident,
            today,
            log,
            provider_plan=planning,
        )
        db.execute(
            "UPDATE agent_runs SET artifacts=? WHERE id=?",
            (json.dumps(outputs, ensure_ascii=False), run_id),
        )
        involved = {artifact["agent"] for artifact in outputs}
        grants = " ".join(spec.grant for spec in SPECIALISTS if spec.key in involved)
        # Mixed-domain and whole-institution work never belongs to an individual room.
        target = outputs[0]["residentId"] if involved == {"care"} else ""
        context = for_person(state, target)
        db.execute(
            "INSERT INTO agent_audit_scope(runId,grants,residentId,room) VALUES(?,?,?,?)",
            (run_id, grants, context["residentId"], context["room"]),
        )
        return "协作任务已生成待确认简报", run_id
    row = get_row(db, user, payload.get("runId"))
    if row["status"] != "awaiting_approval":
        raise ValueError("此任务已处理")
    log = Trace(db, row["id"], at)
    if action == "agent.publish":
        for artifact in json.loads(row["artifacts"]):
            state["suggestions"].insert(
                0,
                {
                    **artifact,
                    "id": new_id("suggest"),
                    "runId": row["id"],
                    "ruleVersion": 1,
                    "date": row["started"][:10],
                    "status": "待审核",
                    "reviewNote": "",
                },
            )
        status = "published"
        message = "已将协作简报发布到建议台账"
    elif action == "agent.cancel":
        status = "cancelled"
        message = "已取消协作简报发布"
    else:
        raise ValueError("未登记的协作动作")
    db.execute("UPDATE agent_runs SET status=? WHERE id=?", (status, row["id"]))
    log.append("coordinator", "run." + status, user["displayName"] + " · " + message)
    return message, row["id"]
