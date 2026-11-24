"""Bound room-level Agent discovery and proposals to one current, authorized location."""

from . import access_policy, facility
from .care.records import text_field
from .care.residency import active_card

PROPOSAL_PATH = "/api/agent/room-proposals"
TRANSCRIPT = "区域 Agent 草稿 · 请核对照护工单及拟写入的执行记录。"
PROPOSAL_FIELDS = {"roomId", "taskId", "note", "requestId"}


def page_number(value, maximum, minimum=0):
    if type(value) is int:
        number = value
    elif (
        isinstance(value, str)
        and value.isascii()
        and value.isdecimal()
        and len(value) <= 7
    ):
        number = int(value)
    else:
        raise ValueError("分页参数须为整数")
    if not minimum <= number <= maximum:
        raise ValueError("分页参数超出范围")
    return number


def scope(db, state, user, value):
    room_id = text_field(value, "房间编号", required=True, limit=100)
    return facility.scope(db, state, user, roomId=room_id)


def residents_with_allocation(state, region):
    resident_ids = set(region["residentIds"])
    return {
        r["id"]
        for r in state["residents"]
        if r["id"] in resident_ids and active_card(state, r)
    }


def eligible(task, resident_ids, today):
    return (
        task["residentId"] in resident_ids
        and task["status"] == "待执行"
        and task["date"] <= today
    )


def pending(db, task_id):
    return (
        db.execute(
            "SELECT 1 FROM gateway_voice WHERE task_id=? AND status='待确认'",
            (task_id,),
        ).fetchone()
        is not None
    )


def room_context(db, state, user, query, today):
    if not isinstance(query, dict) or set(query) - {"roomId", "limit", "offset"}:
        raise ValueError("房间查询参数无效")
    limit = page_number(query.get("limit", 12), 30, 1)
    offset = page_number(query.get("offset", 0), 1_000_000)
    region = scope(db, state, user, query.get("roomId"))
    targets = []
    more = None
    if all(access_policy.has(user, grant) for grant in ("assistants", "care", "voice")):
        resident_ids = residents_with_allocation(state, region)
        candidates = sorted(
            (t for t in state["tasks"] if eligible(t, resident_ids, today)),
            key=lambda t: (t["date"], t.get("time", ""), t["id"]),
        )
        skipped = 0
        for task in candidates:
            if pending(db, task["id"]):
                continue
            if skipped < offset:
                skipped += 1
                continue
            if len(targets) == limit:
                more = offset + limit
                break
            targets.append(
                {
                    "type": "task",
                    "id": task["id"],
                    "residentId": task["residentId"],
                    "label": task["title"],
                    "date": task["date"],
                    "action": "gw.propose",
                    "proposalPath": PROPOSAL_PATH,
                    "field": "note",
                    "requiresHumanConfirmation": True,
                }
            )
    return {
        "region": {
            k: region[k]
            for k in ("institutionId", "buildingId", "floorId", "roomId", "label")
        },
        "readTools": ["rooms.search", "rooms.context", "rooms.tour"],
        "targets": targets,
        "nextOffset": more,
        "version": 1,
    }


def validate_proposal(db, state, user, payload, today):
    """Return the narrow gw.propose envelope inside the caller's business write transaction."""
    for grant in ("assistants", "care", "voice"):
        access_policy.require(user, grant)
    if not isinstance(payload, dict) or set(payload) != PROPOSAL_FIELDS:
        raise ValueError("区域草稿只接受房间编号、工单编号、执行记录和申请编号")
    region = scope(db, state, user, payload["roomId"])
    task_id = text_field(payload["taskId"], "工单编号", required=True, limit=240)
    request = text_field(payload["requestId"], "申请编号", required=True, limit=160)
    note = text_field(payload["note"], "拟写入的执行记录", required=True, limit=1000)
    proposal = {
        "taskId": task_id,
        "requestId": request,
        "note": note,
        "transcript": TRANSCRIPT,
        "targetAction": "care.completeTask",
    }
    receipt = db.execute(
        """SELECT task_id,note,transcript,bed_id FROM gateway_voice
                          WHERE requester_id=? AND request_id=?""",
        (user["id"], request),
    ).fetchone()
    if receipt:
        if (receipt["task_id"], receipt["note"], receipt["transcript"]) != (
            task_id,
            note,
            TRANSCRIPT,
        ) or receipt["bed_id"] not in region["bedIds"]:
            raise ValueError("该申请编号已对应其他房间或不同改动")
        return proposal
    task = next((t for t in state["tasks"] if t["id"] == task_id), None)
    if not task or not eligible(task, residents_with_allocation(state, region), today):
        raise FileNotFoundError("所选房间没有该项可提议的待执行工单")
    if pending(db, task_id):
        raise ValueError("此工单已有待确认申请")
    return proposal
