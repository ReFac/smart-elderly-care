"""Single-institution agent runs and durable, permission-checked approval checkpoints."""

import json
from uuid import uuid4

from . import region
from .contracts import SPECIALISTS, contract
from .. import access_policy as policy
from ..activity import for_person
from ..operations.records import text_field, new_id


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS agent_runs (
        id TEXT PRIMARY KEY, actor TEXT NOT NULL, request TEXT NOT NULL, args TEXT NOT NULL,
        actorName TEXT NOT NULL, started TEXT NOT NULL, revision INTEGER NOT NULL,
        status TEXT NOT NULL, artifacts TEXT NOT NULL, UNIQUE(actor,request))""")
    db.execute("""CREATE TABLE IF NOT EXISTS agent_regions (
        runId TEXT PRIMARY KEY REFERENCES agent_runs(id), snapshot TEXT NOT NULL)""")
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
    area = json.loads(row["regionSnapshot"]) if row["regionSnapshot"] else None
    return dict(
        region={k: v for k, v in area.items() if k not in ("roomIds", "residentIds")}
        if area
        else None,
        id=row["id"],
        actorName=row["actorName"],
        started=row["started"],
        goal=args["goal"],
        residentId=args["residentId"],
        status=row["status"],
        sourceRevision=row["revision"],
        agents=[a["agent"] for a in json.loads(row["artifacts"])],
    )


RUN_SELECT = "SELECT r.*,a.snapshot AS regionSnapshot FROM agent_runs r LEFT JOIN agent_regions a ON a.runId=r.id"


def region_visible(db, user, run_id):
    if not user.get("facilityScope") and isinstance(
        user.get("facilityScope", {}), dict
    ):
        return True
    row = db.execute(
        "SELECT snapshot FROM agent_regions WHERE runId=?", (run_id,)
    ).fetchone()
    return region.visible(db, user, json.loads(row[0]) if row else None)


def visible(db, row, user, permitted=None):
    area = json.loads(row["regionSnapshot"]) if row["regionSnapshot"] else None
    return (
        region.visible(db, user, area, permitted)
        and (user["kind"] == "owner" or row["actor"] == user["id"])
        and all(
            a["agent"] in {s.key for s in specialists(user)}
            for a in json.loads(row["artifacts"])
        )
    )


def listing(db, user):
    if not specialists(user):
        return []
    query = RUN_SELECT
    args = ()
    if user["kind"] != "owner":
        query += " WHERE r.actor=?"
        args = (user["id"],)
    from ..campus_access import current_residents

    permitted = current_residents(db, user)
    result = []
    for row in db.execute(query + " ORDER BY r.rowid DESC", args):
        if visible(db, row, user, permitted):
            result.append(summary(row))
        if len(result) == 80:
            break
    return result


def get_row(db, user, run_id):
    policy.require(user, "assistants")
    row = db.execute(RUN_SELECT + " WHERE r.id=?", (run_id,)).fetchone()
    if not row or not visible(db, row, user):
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


def preflight(db, state, user, payload):
    policy.require(user, "assistants")
    goal = text_field(payload, "goal", "任务目标", 500)
    request = text_field(payload, "requestId", "请求标识", 100)
    resident = payload.get("residentId", "")
    scope = payload.get("scope", "auto")
    mode = payload.get("planning", "local")
    if (
        not isinstance(resident, str)
        or len(resident) > 100
        or not isinstance(scope, str)
        or mode not in ("local", "platform")
    ):
        raise ValueError("任务范围或规划模式无效")
    selected = region.selection(payload["region"]) if "region" in payload else None
    args = dict(goal=goal, residentId=resident, scope=scope)
    if "voiceTranscriptId" in payload:
        from ..provider.speech import require_agent_receipt

        require_agent_receipt(db, user, selected, payload["voiceTranscriptId"])
        args["voiceTranscriptId"] = payload["voiceTranscriptId"]
    if mode == "platform":
        args["planning"] = mode
    if selected:
        args["region"] = selected
    encoded = json.dumps(args, ensure_ascii=False)
    prior = db.execute(
        "SELECT id,args FROM agent_runs WHERE actor=? AND request=?",
        (user["id"], request),
    ).fetchone()
    if prior:
        if json.loads(prior["args"]) != args:
            raise ValueError("请求标识已被另一项任务使用")
        get_row(db, user, prior["id"])
        return {
            "prior": prior["id"],
            "args": args,
            "request": request,
            "specs": (),
            "fingerprintScope": encoded,
        }
    resolved = region.resolve(db, state, user, selected)
    specs = tuple(
        s for s in specialists(user) if not resolved or s.key in ("care", "finance")
    )
    if not specs or (scope != "auto" and scope not in {s.key for s in specs}):
        raise PermissionError("此范围或岗位未授权所选专员")
    if resident:
        if not any(s.key == "care" for s in specs) or scope not in ("auto", "care"):
            raise PermissionError("指定长者的任务需要照护权限")
        if resolved and resident not in resolved["residentIds"]:
            raise PermissionError("该长者当前不在所选区域")
        if not any(
            r["id"] == resident and r["status"] == "在住" for r in state["residents"]
        ):
            raise ValueError("请选择有效的在住长者")
    return {
        "prior": None,
        "args": args,
        "request": request,
        "encoded": encoded,
        "resolved": resolved,
        "specs": specs,
        "fingerprintScope": encoded,
    }


def apply(db, state, action, payload, user, now, revision, planning=None):
    at = now.isoformat(timespec="seconds")
    if action == "agent.start":
        check = preflight(db, state, user, payload)
        if check["prior"]:
            return "已登记同一协作任务", check["prior"]
        resolved = check["resolved"]
        run_id = "run-" + uuid4().hex
        db.execute(
            "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                user["id"],
                check["request"],
                check["encoded"],
                user["displayName"],
                at,
                revision,
                "awaiting_approval",
                "[]",
            ),
        )
        log = Trace(db, run_id, at)
        log.append("coordinator", "run.started", "开始处理委托")
        if resolved:
            region.save(db, run_id, resolved)
            log.append("coordinator", "region.selected", resolved["label"])
        if not planning or planning.get("mode") != "deepseek":
            raise ValueError("请先生成云端业务简报")
        if (
            planning["actor"] != user["id"]
            or planning["region"] != resolved
            or any(
                item["agent"] not in {spec.key for spec in check["specs"]}
                for item in planning["artifacts"]
            )
        ):
            raise PermissionError("授权范围已变化，请重新生成")
        log.append("coordinator", "planner.selected", planning["model"])
        for event in planning["events"]:
            log.append(*event)
        outputs = planning["artifacts"]
        db.execute(
            "UPDATE agent_runs SET artifacts=? WHERE id=?",
            (json.dumps(outputs, ensure_ascii=False), run_id),
        )
        involved = {artifact["agent"] for artifact in outputs}
        grants = " ".join(spec.grant for spec in SPECIALISTS if spec.key in involved)
        # Mixed-domain and whole-institution work never belongs to an individual room.
        target = outputs[0]["residentId"] if involved == {"care"} else ""
        context = for_person(state, target)
        if resolved and not target and resolved["roomId"]:
            context["room"] = resolved["label"]
        db.execute(
            "INSERT INTO agent_audit_scope(runId,grants,residentId,room) VALUES(?,?,?,?)",
            (run_id, grants, context["residentId"], context["room"]),
        )
        return "协作任务已生成待确认简报", run_id
    row = get_row(db, user, payload.get("runId"))
    if "region" in payload:
        raise ValueError("审核必须使用运行时锁定的区域")
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
                    "region": summary(row)["region"],
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
