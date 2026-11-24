"""评估、照护计划、工单派发和服务抽检。"""

from datetime import time

from .records import (
    append_record,
    care_level,
    get_resident,
    iso_date,
    lookup,
    offset_date,
    required_field,
    text_field,
)
from .residency import active_card
from .scales import GROUPS, score_scale


SERVICE_ITEMS = {
    "生活起居": "起居照护协助",
    "院内活动": "院内活动陪伴",
    "日常沟通": "日常沟通陪伴",
}


def match_staff(state, resident, day, campus_id=None):
    ward = lookup(state, "beds", resident["bedId"])["ward"]
    candidates = {
        s["staff"]
        for s in state.get("shifts", [])
        if s["date"] == day
        and s["area"] == ward
        and (campus_id is None or s.get("campusId", "campus-main") == campus_id)
    }
    if not candidates:
        raise ValueError("今天本区尚无排班，请指定负责照护的人员。")
    outstanding = {person: 0 for person in candidates}
    for task in state["tasks"]:
        if (
            task["date"] == day
            and task["status"] == "待执行"
            and task["assignee"] in outstanding
        ):
            outstanding[task["assignee"]] += 1
    return min(candidates, key=lambda person: (outstanding[person], person))


def assess(state, p, today):
    resident = get_resident(state, p.get("residentId"))
    level = care_level(p.get("level"))
    note = required_field(p, "note", "评估结果与照护需求")
    assigned = text_field(p.get("assignee"), "照护责任人")
    source = "人工指定" if assigned else "同区当日排班与待办量"
    observations = p.get("observations", {})
    if not isinstance(observations, dict) or any(
        key not in SERVICE_ITEMS or value not in ("可独立完成", "需协助", "待观察")
        for key, value in observations.items()
    ):
        raise ValueError("请核对生活能力观察项目和选项。")
    items = [
        title
        for key, title in SERVICE_ITEMS.items()
        if observations.get(key) == "需协助"
    ]
    method = text_field(p.get("source") or "线上采集", "采集来源")
    scale = score_scale(p["scale"], method, today) if "scale" in p else None
    historical = bool(
        scale
        and any(
            a["residentId"] == resident["id"]
            and a.get("scale", {}).get("assessedOn", a["date"]) > scale["assessedOn"]
            for a in state["assessments"]
        )
    )
    assignee = assigned or (
        ""
        if historical
        else match_staff(state, resident, today, p.get("matchCampusId"))
    )
    if scale:
        for group, subtotal in scale["subtotals"].items():
            if subtotal < sum(GROUPS[group].values()):
                items.append(f"核对{group}支持需求")
    if not items:
        items = ["执行个体照护计划"]
    review = iso_date(p.get("reviewDate") or offset_date(today, 30), "复评日")
    if not historical and review <= today:
        raise ValueError("复评日须晚于今天。")
    record = append_record(
        state,
        "assessments",
        residentId=resident["id"],
        level=level,
        note=note,
        assignee=assignee,
        date=today,
        reviewDate="" if historical else review,
        observations=observations,
        assignmentSource=source,
        source=method,
        recordedBy=text_field(p.get("operator"), "登记人"),
        **({"scale": scale, "historyOnly": historical} if scale else {}),
    )
    if historical:
        return f"已归档{resident['name']}较早的评估原表"
    # The account that approves the plan confirms the institutional care level.
    for old_plan in state["plans"]:
        if old_plan["residentId"] == resident["id"] and old_plan["status"] == "待复核":
            old_plan["status"] = "已取消"
    append_record(
        state,
        "plans",
        residentId=resident["id"],
        assessmentId=record["id"],
        title=f"{resident['name']}的{level}照护计划",
        note=note,
        status="待复核",
        assignee=assignee,
        assignmentSource=source,
        items=items,
        date=today,
        reviewDate=review,
    )
    return f"保存{resident['name']}的评估，已生成待复核照护计划"


def append_task(state, resident_id, title, assignee, day, clock, kind, **fields):
    return append_record(
        state,
        "tasks",
        residentId=resident_id,
        title=title,
        assignee=assignee,
        date=day,
        time=clock,
        kind=kind,
        status="待执行",
        **fields,
    )


def approve_plan(state, p, today):
    plan = lookup(state, "plans", p.get("planId"))
    if plan["status"] != "待复核":
        raise ValueError("仅待复核计划可派发。")
    reviewer = required_field(p, "reviewer", "复核人")
    resident = get_resident(state, plan["residentId"])
    assessment = lookup(state, "assessments", plan["assessmentId"])
    for task in state["tasks"]:
        if (
            task["residentId"] == resident["id"]
            and task.get("planId")
            and task["status"] == "待执行"
        ):
            task["status"] = "已取消"
    plan.update(
        status="已派发",
        reviewer=reviewer,
        reviewedAt=today,
        previousCareLevel=resident["level"],
        careLevel=assessment["level"],
    )
    resident.update(level=assessment["level"])
    for title in plan.get("items", ["执行个体照护计划"]):
        append_task(
            state,
            resident["id"],
            title,
            plan["assignee"],
            today,
            "09:00",
            "计划照护",
            planId=plan["id"],
            note=plan["note"],
        )
    append_task(
        state,
        resident["id"],
        "护理需求复评",
        plan["assignee"],
        max(today, plan["reviewDate"]),
        "10:00",
        "复评提醒",
        planId=plan["id"],
    )
    return f"{reviewer}复核{resident['name']}的照护计划，派发照护及复评工单"


def add_task(state, p, today):
    resident = get_resident(state, p.get("residentId"))
    day = iso_date(p.get("date") or today, "执行日期")
    if day < today:
        raise ValueError("新工单日期须为今天或未来日期。")
    clock = p.get("time") or "09:00"
    try:
        clock = time.fromisoformat(clock).strftime("%H:%M")
    except (TypeError, ValueError):
        raise ValueError("执行时间须为有效时刻。") from None
    from .timeline import routine_selection

    title = required_field(p, "title", "工单名称")
    kind = text_field(p.get("kind") or "日常照护", "任务类型")
    group = routine_selection(p.get("routineActivity", "auto"), kind, title)
    append_task(
        state,
        resident["id"],
        title,
        required_field(p, "assignee", "责任人"),
        day,
        clock,
        kind,
        note=text_field(p.get("note"), "执行说明"),
        **({"routineActivity": group} if group != "auto" else {}),
    )
    return f"为{resident['name']}派发工单「{title}」"


def complete_task(state, p, today):
    task = lookup(state, "tasks", p.get("taskId"))
    resident = get_resident(state, task["residentId"])
    if task["status"] != "待执行" or task["date"] > today:
        raise ValueError("仅当日或逾期待执行工单可完成。")
    if p.get("bedId") and resident["bedId"] != p["bedId"]:
        raise ValueError("床头卡与长者当前床位不符。")
    if "cardCode" in p:
        if (
            not p.get("bedId")
            or not p["cardCode"]
            or p["cardCode"] != active_card(state, resident)
        ):
            raise ValueError("床头卡已失效或与工单不符，请重新核验当前卡。")
        if task["date"] != today:
            raise ValueError("床旁核验仅受理今天的待执行工单。")
    operator = required_field(p, "operator", "执行人")
    task.update(
        status="已完成",
        operator=operator,
        **({"operatorId": p["operatorId"]} if p.get("operatorId") else {}),
        completedAt=today,
        note=text_field(p.get("note") or task.get("note"), "执行记录"),
        checkedBedId=p.get("bedId") or "",
        checkedCardCode=p.get("cardCode") or "",
    )
    return f"{operator}完成{resident['name']}的「{task['title']}」"


def quality(state, p, today):
    task = lookup(state, "tasks", p.get("taskId"))
    if task["status"] != "已完成":
        raise ValueError("请选择已完成的工单进行质控。")
    reviewer = required_field(p, "reviewer", "抽检人")
    rating = p.get("rating")
    if rating not in (None, ""):
        try:
            rating = int(str(rating))
            if not 1 <= rating <= 5:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("满意度请填写 1 至 5 分。") from None
    append_record(
        state,
        "qualityChecks",
        taskId=task["id"],
        residentId=task["residentId"],
        reviewer=reviewer,
        date=today,
        note=required_field(p, "note", "抽检结论"),
        rating=rating or None,
    )
    return f"{reviewer}完成「{task['title']}」的质量抽检"
