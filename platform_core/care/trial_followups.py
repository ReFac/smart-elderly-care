"""Assign failed trial stays to an identifiable employee and retain the signed contact report."""

from .. import access, campus_access
from ..operations.records import currency_amount
from .records import append_record, iso_date, lookup, offset_date, required_field
from .residency import trial_days


def settings(state):
    rows = state.get("trialPolicies")
    return (
        {k: rows[0][k] for k in ("days", "fee")} if rows else {"days": 3, "fee": None}
    )


def configure(state, payload):
    if set(payload) != {"days", "fee"}:
        raise ValueError("请核对试住天数和单次总价")
    days = trial_days(payload["days"])
    fee = payload["fee"]
    if fee is not None:
        fee = float(currency_amount(fee, "试住总价"))
    state["trialPolicies"] = [{"id": "institution", "days": days, "fee": fee}]
    return "更新机构试住天数与单次收费约定"


def eligible(user):
    return user["kind"] in ("staff", "owner") and "residents" in user["routes"]


def recipients(db, state, user, resident_id, policy):
    access.require(user, "intake")
    campus_access.require_resident(db, user, resident_id, state)
    resident = lookup(state, "residents", resident_id)
    if resident.get("stayType") != "trial":
        raise ValueError("请选择试住档案")
    result = []
    for row in db.execute(
        "SELECT * FROM accounts WHERE enabled=1 AND kind IN ('staff','owner') ORDER BY display_name,username"
    ):
        employee = access._public(row)
        if policy is not None:
            employee["facilityScope"] = campus_access.effective(
                employee, policy(db, employee)
            )
        if eligible(employee):
            try:
                campus_access.require_resident(db, employee, resident_id, state)
            except PermissionError:
                continue
            result.append({
                k: employee[k] for k in ("id", "displayName", "username", "role", "staffDuties")
                if k in employee
            })
    return result


def assign(db, state, user, payload, now, policy):
    if set(payload) != {"residentId", "reason", "assigneeId", "dueDate"}:
        raise ValueError("请选择回访人员、计划日期并填写未入住原因")
    rid = payload["residentId"]
    due = iso_date(payload["dueDate"], "计划回访日")
    day = now.date().isoformat()
    if not day <= due < offset_date(day, 365):
        raise ValueError("计划回访日须在今天至本次档案保留期内")
    selected = next(
        (
            r
            for r in recipients(db, state, user, rid, policy)
            if r["id"] == payload["assigneeId"]
        ),
        None,
    )
    if not selected:
        raise ValueError("请选择可查阅该试住档案的在岗回访人员")
    state.setdefault("trialFollowups", [])
    if any(r["residentId"] == rid for r in state["trialFollowups"]):
        raise ValueError("本次试住已派发回访")
    append_record(
        state,
        "trialFollowups",
        residentId=rid,
        assigneeId=selected["id"],
        assignee=selected["displayName"],
        assignedBy=user["id"],
        assignedByName=user["displayName"],
        assignedAt=now.isoformat(timespec="seconds"),
        dueDate=due,
        reason=required_field(payload, "reason", "未入住原因"),
        status="待回访",
    )


METHODS = ("电话", "微信", "面谈", "上门", "其他")
OUTCOMES = ("有再次入住意向", "暂缓入住", "无入住意向", "未能联系", "其他")


def complete(db, state, user, payload, now):
    if set(payload) != {"taskId", "method", "outcome", "feedback", "nextSteps"}:
        raise ValueError("请完整填写回访报告")
    task = lookup(state, "trialFollowups", payload["taskId"])
    if task["assigneeId"] != user["id"]:
        raise PermissionError("只有指定回访人员可以提交报告")
    campus_access.require_resident(db, user, task["residentId"], state)
    if lookup(state, "residents", task["residentId"])["status"] == "归档到期":
        raise ValueError("这份试住档案已到保管期限")
    if task["status"] != "待回访":
        raise ValueError("这份回访报告已经提交")
    if payload["method"] not in METHODS or payload["outcome"] not in OUTCOMES:
        raise ValueError("请选择回访方式和结果")
    report = {
        k: required_field(payload, k, label)
        for k, label in (("feedback", "沟通经过与反馈"), ("nextSteps", "后续安排"))
    }
    task.update(
        report={**report, "method": payload["method"], "outcome": payload["outcome"]},
        status="已回访",
        reportedBy=user["id"],
        reportedByName=user["displayName"],
        reportedAt=now.isoformat(timespec="seconds"),
    )
    return "提交试住回访报告"


def reassign(db, state, user, payload, now, policy):
    if set(payload) != {"taskId", "assigneeId"}:
        raise ValueError("请选择新的回访人员")
    task = lookup(state, "trialFollowups", payload["taskId"])
    if task["status"] != "待回访":
        raise ValueError("仅待回访的任务可改派")
    options = recipients(db, state, user, task["residentId"], policy)
    selected = next((r for r in options if r["id"] == payload["assigneeId"]), None)
    if not selected or selected["id"] == task["assigneeId"]:
        raise ValueError("请选择另一名具备该档案权限的在岗人员")
    task.update(
        assigneeId=selected["id"],
        assignee=selected["displayName"],
        assignedBy=user["id"],
        assignedByName=user["displayName"],
        assignedAt=now.isoformat(timespec="seconds"),
    )
    return "改派试住回访任务"


def project(db, state, user, data):
    if access.has(user, "intake"):
        data["trialSettings"] = settings(state)
    if not eligible(user):
        data.pop("trialFollowups", None)
        return
    beds = campus_access.allowed_beds(db, user, include_rooms=True)
    permitted = (
        campus_access.resident_ids(state, beds, user) if beds is not None else None
    )
    live_ids = {r["id"] for r in state["residents"] if r["status"] != "归档到期"}
    data["trialFollowups"] = [
        task
        for task in state.get("trialFollowups", ())
        if (access.has(user, "intake") or task["assigneeId"] == user["id"])
        and task["residentId"] in live_ids
        and (permitted is None or task["residentId"] in permitted)
    ]
