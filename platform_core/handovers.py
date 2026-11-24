"""Shift handovers preserve a dated workload snapshot and one named receipt."""

import json
import re

from . import access
from .care.records import append_record, get_resident, lookup, text_field


def recipients(db, actor):
    access.require(actor, "care")
    rows = db.execute(
        """SELECT id, username, display_name, kind, permissions FROM accounts
        WHERE enabled=1 AND kind IN ('staff','owner') AND id<>?
        ORDER BY display_name, username""",
        (actor["id"],),
    )
    return {
        "recipients": [
            {
                "id": row["id"],
                "username": row["username"],
                "displayName": row["display_name"],
            }
            for row in rows
            if row["kind"] == "owner" or "care" in json.loads(row["permissions"])
        ]
    }


def workload(state, resident_id, today, include_vitals):
    result = {"pendingToday": 0, "completedToday": 0, "overdue": 0}
    for task in state["tasks"]:
        if resident_id and task["residentId"] != resident_id:
            continue
        if task["date"] == today and task["status"] == "已完成":
            result["completedToday"] += 1
        elif task["date"] == today and task["status"] == "待执行":
            result["pendingToday"] += 1
        elif task["date"] < today and task["status"] == "待执行":
            result["overdue"] += 1
    if include_vitals:
        result["openVitals"] = sum(
            v["status"] == "待复核"
            and (not resident_id or v["residentId"] == resident_id)
            for v in state["vitals"]
        )
    return result


def create(db, state, payload, actor, now):
    assigned = "assigneeId" in payload
    if set(payload) - {"assigneeId" if assigned else "assignee", "residentId", "note"}:
        raise ValueError("交班表单含有未知字段")
    resident_id = text_field(payload.get("residentId"), "长者编号", limit=100)
    if resident_id:
        get_resident(state, resident_id)
    receiver = None
    if assigned:
        account_id = text_field(
            payload["assigneeId"], "接班账号", required=True, limit=100
        )
        receiver = access.account(db, account_id)
        if (
            not receiver
            or not receiver["enabled"]
            or receiver["kind"] not in ("staff", "owner")
            or receiver["id"] == actor["id"]
            or not access.has(receiver, "care")
        ):
            raise ValueError("请选择另一位在岗且具有照护权限的接班账号")
        assignee = receiver["displayName"]
    else:
        # Old clients submit a name with no stable account identity.
        assignee = text_field(payload.get("assignee"), "接班人", required=True)
    today = now.date().isoformat()
    counts = workload(
        state,
        resident_id,
        today,
        access.has(actor, "clinical") and access.has(receiver, "clinical"),
    )
    summary = (
        f"当日待执行 {counts['pendingToday']} 项，逾期待执行 {counts['overdue']} 项，"
        f"当日已完成 {counts['completedToday']} 项。"
    )
    append_record(
        state,
        "handovers",
        date=today,
        residentId=resident_id,
        senderId=actor["id"],
        senderName=actor["displayName"],
        assigneeId=receiver["id"] if receiver else "",
        assignee=assignee,
        createdAt=now.isoformat(timespec="seconds"),
        snapshot=counts,
        summary=summary,
        note=text_field(payload.get("note"), "交接要点"),
        status="待签收" if assigned else "历史记录",
    )
    if assigned:
        return f"{actor['displayName']}向{assignee}提交班次交接"
    return f"{actor['displayName']}为{assignee}登记历史交班记录"


def pending_record(state, payload):
    record = lookup(
        state,
        "handovers",
        text_field(payload.get("handoverId"), "交班记录编号", required=True, limit=100),
    )
    if not record.get("assigneeId"):
        raise ValueError("历史交班记录没有指定接班账号")
    if record["status"] != "待签收":
        raise ValueError(f"交班记录{record['status']}，请核对最新状态")
    return record


def accept(state, payload, actor, now):
    if set(payload) - {"handoverId", "note"}:
        raise ValueError("签收表单含有未知字段")
    record = pending_record(state, payload)
    if record["assigneeId"] != actor["id"]:
        raise PermissionError("仅指定的接班账号可以签收")
    record.update(
        status="已签收",
        acceptedAt=now.isoformat(timespec="seconds"),
        acceptedById=actor["id"],
        acceptedByName=actor["displayName"],
        receiptNote=text_field(payload.get("note"), "签收备注"),
    )
    return f"{actor['displayName']}签收了{record['senderName']}的班次交接"


def withdraw(state, payload, actor, now):
    if set(payload) - {"handoverId", "reason"}:
        raise ValueError("撤回表单含有未知字段")
    record = pending_record(state, payload)
    if record["senderId"] != actor["id"]:
        raise PermissionError("仅原交班人可以撤回")
    record.update(
        status="已撤回",
        withdrawnAt=now.isoformat(timespec="seconds"),
        withdrawnById=actor["id"],
        withdrawnByName=actor["displayName"],
        withdrawReason=text_field(payload.get("reason"), "撤回原因", required=True),
    )
    return f"{actor['displayName']}撤回了交给{record['assignee']}的班次交接"


def visible(record, include_vitals):
    row = dict(record)
    if not row.get("assigneeId"):
        row["status"] = "历史记录"
    if include_vitals:
        return row
    if "snapshot" in row:
        row["snapshot"] = {
            k: v for k, v in row["snapshot"].items() if k != "openVitals"
        }
    else:
        # Previous versions embedded the clinical count in the generated summary.
        match = re.match(
            r"今日照护工单 \d+ 项，已完成 \d+ 项，待完成 \d+ 项。",
            row.get("summary", ""),
        )
        row["summary"] = match[0] if match else "历史交班记录"
    return row
