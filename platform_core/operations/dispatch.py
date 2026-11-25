"""Reviewed supply assignments and institution-wide staff notices."""

import json
import re

from .. import access_policy
from .records import lookup, new_id, parse_day, text_field


def unrestricted(user):
    return not any(
        key in (user.get("facilityScope") or {})
        for key in ("campusIds", "buildingIds", "floorIds", "roomIds")
    )


def manages_supplies(user):
    return unrestricted(user) and access_policy.has(user, "inventory")


def project(db, state, user, data):
    if user["kind"] not in ("owner", "staff"):
        return
    data["staffNotices"] = state.get("staffNotices", [])
    manager = manages_supplies(user)
    data["supplyOrders"] = [
        row
        for row in state.get("supplyOrders", [])
        if manager or row["assigneeId"] == user["id"]
    ]
    if manager:
        data["supplyAssignees"] = [
            dict(id=row[0], label=row[1], role=row[2])
            for row in db.execute(
                "SELECT id,display_name,role FROM accounts WHERE enabled=1 "
                "AND activation_pending=0 AND kind IN ('staff','owner') ORDER BY display_name,id"
            )
        ]


def verify_proposal(store, db, token, user, command, payload):
    kinds = {
        "ops.supplyOrder": ("workOrder", "inventory"),
        "ops.publishNotice": ("notice", "inbox"),
        "care.addTask": ("workOrder", "care"),
    }
    if command not in kinds or (
        command == "care.addTask" and "assistantActionId" not in payload
    ):
        return
    from ..agents.chat_context import scope

    ref = payload.get("assistantActionId")
    if not isinstance(ref, str) or not re.fullmatch(r"[a-f0-9]{64}", ref):
        raise ValueError("需要先在对话中明确提出并审核这项建议")
    kind, route = kinds[command]
    row = db.execute(
        "SELECT t.scope,t.action FROM assistant_turns t JOIN assistant_threads h "
        "USING(actor,scope,generation) WHERE t.actor=? AND json_extract(t.action,'$.id')=? "
        "AND json_extract(t.action,'$.kind')=? AND json_extract(t.action,'$.route')=?",
        (user["id"], ref, kind, route),
    ).fetchone()
    if not row:
        raise PermissionError("没有可在本次对话中发布的建议，请重新提问")
    _, key, routes, _, area = scope(
        store, db, token, json.loads(row["action"]).get("region")
    )
    if key != row["scope"] or route not in routes:
        raise PermissionError("建议的业务范围已经变化，请重新提问")
    if area and (
        route != "care" or payload.get("residentId") not in area["residentIds"]
    ):
        raise PermissionError("请选择本次对话区域中的长辈")


def source_reference(state, payload, user):
    """A review can publish once even after a tab reload or delivery retry."""
    if "assistantActionId" not in payload:
        return {}
    ref = payload["assistantActionId"]
    for collection in ("supplyOrders", "staffNotices", "tasks"):
        if any(
            r.get("assistantActionId") == ref and r.get("publisherId") == user["id"]
            for r in state.get(collection, ())
        ):
            raise ValueError("这项建议已经发布，请查看办理记录")
    return {"assistantActionId": ref, "publisherId": user["id"]}


def apply(db, state, action, payload, user, now):
    if user["kind"] not in ("owner", "staff"):
        raise PermissionError("仅在岗员工可以办理")
    timestamp = now.isoformat(timespec="seconds")
    if action == "ops.finishSupplyOrder":
        order = lookup(state, "supplyOrders", payload.get("orderId"), "物资工单")
        if order["assigneeId"] != user["id"] and not manages_supplies(user):
            raise PermissionError("仅执行人或物资管理人员可完成该工单")
        if order["status"] != "待执行":
            raise ValueError("该工单已完成")
        order.update(
            status="已完成", completedAt=timestamp, completedBy=user["displayName"]
        )
        return f"完成物资工单「{order['title']}」"
    if not unrestricted(user):
        raise PermissionError("此项发布需要全机构权限")
    source = source_reference(state, payload, user)
    title = text_field(payload, "title", "标题", 100)
    body = text_field(payload, "description", "内容", 2000)
    row = dict(
        id=new_id("dispatch"),
        title=title,
        description=body,
        createdAt=timestamp,
        publisher=user["displayName"],
        **source,
    )
    if action == "ops.publishNotice":
        state.setdefault("staffNotices", []).insert(0, row)
        return f"已向全体员工发布「{title}」"
    assignee = db.execute(
        "SELECT id,display_name FROM accounts WHERE id=? AND kind IN ('staff','owner') "
        "AND enabled=1 AND activation_pending=0",
        (payload.get("assigneeId"),),
    ).fetchone()
    if not assignee:
        raise ValueError("请选择在岗且已激活的执行人")
    due = parse_day(payload.get("dueDate"))
    if due < now.date():
        raise ValueError("执行日期须为今天或未来日期")
    item_id = payload.get("itemId") or ""
    if item_id:
        lookup(state, "inventory", item_id, "护理用具")
    row.update(
        assigneeId=assignee[0],
        assignee=assignee[1],
        dueDate=due.isoformat(),
        itemId=item_id,
        status="待执行",
    )
    state.setdefault("supplyOrders", []).insert(0, row)
    return f"发布物资工单「{title}」，由{assignee[1]}执行"
