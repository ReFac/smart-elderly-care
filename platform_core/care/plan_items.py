"""Reviewed service-plan revisions and their recurring dispatch rules."""

from collections import Counter
from datetime import date
import json
import re
from uuid import uuid4

from .records import append_record, get_resident, lookup, offset_date, text_field

CATEGORIES = ("生活照料", "健康观察", "康复支持", "服务设施", "其他")
ROLES = ("护工", "护士", "护士长", "院长", "日常照护", "临床护理", "康复支持")


def normalized(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 40:
        raise ValueError("照护计划须含 1 至 40 个项目")
    items, names = [], set()
    for row in value:
        if not isinstance(row, dict) or set(row) != {
            "title",
            "category",
            "period",
            "weekday",
            "count",
            "times",
            "roles",
            "assignee",
            "enabled",
        }:
            raise ValueError("请核对计划项目字段")
        title = text_field(row["title"], "项目名称", required=True, limit=80)
        assignee = text_field(row["assignee"], "执行人员", required=True, limit=80)
        if (
            title in names
            or row["category"] not in CATEGORIES
            or row["period"] not in ("once", "daily", "weekly")
        ):
            raise ValueError("请核对项目名称、分类和执行周期，项目名称须唯一")
        if (
            type(row["enabled"]) is not bool
            or type(row["count"]) is not int
            or not 1 <= row["count"] <= 12
        ):
            raise ValueError("单个项目每天可安排 1 至 12 次")
        if type(row["weekday"]) is not int or not 1 <= row["weekday"] <= 7:
            raise ValueError("请选择有效的星期")
        times, roles = row["times"], row["roles"]
        if (
            not isinstance(times, list)
            or (times and len(times) != row["count"])
            or any(
                not isinstance(t, str)
                or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", t)
                for t in times
            )
            or len(set(times)) != len(times)
        ):
            raise ValueError("指定时点时须逐次选择互不重复的时刻")
        if (
            not isinstance(roles, list)
            or not roles
            or any(r not in ROLES for r in roles)
            or len(set(roles)) != len(roles)
        ):
            raise ValueError("请勾选可执行的护理岗位")
        names.add(title)
        items.append(
            {**row, "title": title, "assignee": assignee, "times": sorted(times)}
        )
    if not any(row["enabled"] for row in items):
        raise ValueError("请至少启用一个照护项目")
    return items


def revise(state, p, today):
    source = lookup(state, "plans", p.get("planId"))
    resident = get_resident(state, source["residentId"])
    items = normalized(p.get("serviceItems"))
    if source["status"] not in ("已派发", "待复核") or source.get("supersededBy"):
        raise ValueError("仅可调整当前生效或待复核的计划")
    if source.get("serviceItems") == items:
        raise ValueError("项目设置没有变化")
    draft = source
    if source["status"] == "已派发":
        if any(
            r["residentId"] == resident["id"] and r["status"] == "待复核"
            for r in state["plans"]
        ):
            raise ValueError("已有待复核计划，请打开现有草稿继续调整")
        draft = append_record(
            state,
            "plans",
            **{
                key: source[key]
                for key in (
                    "residentId",
                    "assessmentId",
                    "title",
                    "note",
                    "assignee",
                    "reviewDate",
                )
            },
        )
        draft.update(
            date=today,
            status="待复核",
            previousPlanId=source["id"],
            assignmentSource=source.get("assignmentSource", "人工指定"),
        )
    draft.update(
        serviceItems=items,
        items=[r["title"] for r in items if r["enabled"]],
        modifiedBy=p["operator"],
        modifiedAt=today,
    )
    return f"保存{resident['name']}的照护项目调整，等待复核"


def first_day(state, plan, today):
    from .plans import append_task

    completed = Counter(
        (t["title"], t["time"])
        for t in state["tasks"]
        if t.get("planId")
        and t["residentId"] == plan["residentId"]
        and t["date"] == today
        and t["status"] == "已完成"
    )
    for item in plan["serviceItems"]:
        if not item["enabled"] or (
            item["period"] == "weekly"
            and item["weekday"] != date.fromisoformat(today).isoweekday()
        ):
            continue
        for clock in item["times"] or [""] * item["count"]:
            key = (item["title"], clock)
            if completed[key]:
                completed[key] -= 1
                continue
            append_task(
                state,
                plan["residentId"],
                item["title"],
                item["assignee"],
                today,
                clock,
                "计划照护",
                planId=plan["id"],
                note=plan["note"],
                allowedRoles=item["roles"],
            )


def sync_rules(db, state, plan_id, actor, now):
    """Start future occurrences only upon approval; keep old receipts and previous approved versions."""
    plan = lookup(state, "plans", plan_id)
    resident = plan["residentId"]
    disable_rules(db, resident, actor, now)
    tomorrow = offset_date(now.date().isoformat(), 1)
    for item in plan.get("serviceItems", []):
        if not item["enabled"] or item["period"] == "once":
            continue
        for slot, clock in enumerate(item["times"] or [""] * item["count"], start=1):
            rule = dict(
                title=item["title"],
                kind="care",
                assignee=item["assignee"],
                assigneeId="",
                assigneeRole="",
                weekdays=[item["weekday"]]
                if item["period"] == "weekly"
                else list(range(1, 8)),
                time=clock or "00:00",
                startDate=tomorrow,
                endDate="",
                scope={"kind": "residents", "residentIds": [resident]},
                mealKind="",
                menu=[],
                weeklyMenus={},
                note=plan["note"],
                enabled=True,
                planId=plan_id,
                planResident=resident,
                planTime=clock,
                planSlot=slot,
                allowedRoles=item["roles"],
            )
            db.execute(
                "INSERT INTO scheduled_work_rules VALUES(?,?,?,?,?,?)",
                (
                    uuid4().hex,
                    json.dumps(rule, ensure_ascii=False),
                    actor["id"],
                    now.isoformat(),
                    actor["id"],
                    now.isoformat(),
                ),
            )


def disable_rules(db, resident, actor, now):
    db.execute(
        """UPDATE scheduled_work_rules SET config=json_set(config,'$.enabled',json('false')),
               updatedBy=?,updatedAt=? WHERE json_extract(config,'$.planResident')=?
               AND json_extract(config,'$.enabled')=1""",
        (actor["id"], now.isoformat(), resident),
    )
