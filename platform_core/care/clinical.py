"""用药复核、执行凭证、体征上报和交班。"""

from datetime import datetime
import re

from . import drug_rules

from .records import append_record, get_resident, lookup, required_field, text_field


def medication_warnings(state, resident, name, interaction_note, exclude_id=None):
    warnings = []
    allergens = re.split(r"[,，、;；\n]+", resident["allergies"])
    if any(
        term.strip() and term.strip().casefold() in name.casefold()
        for term in allergens
    ):
        warnings.append("药品名称与档案过敏记录匹配，请核对。")
    if any(
        m["residentId"] == resident["id"]
        and m["id"] != exclude_id
        and m["status"] in ("待复核", "待执行")
        and m["name"].casefold() == name.casefold()
        for m in state["medications"]
    ):
        warnings.append("同名药品已有待处理记录，请复核是否重复。")
    for rule in drug_rules.matching(state, resident["id"], name, exclude_id):
        warnings.append(
            f"配伍复核（{rule['version']}，{rule['drugA']} / {rule['drugB']}）：{rule['message']}〔{rule['source']}〕"
        )
    if interaction_note:
        warnings.append(f"人工标记的配伍核查事项：{interaction_note}")
    return warnings


def refresh_medication_warnings(state, resident):
    for med in state["medications"]:
        if med["residentId"] != resident["id"] or med["status"] not in (
            "待复核",
            "待执行",
        ):
            continue
        warnings = medication_warnings(
            state, resident, med["name"], med.get("interactionNote", ""), med["id"]
        )
        if set(warnings) - set(med["warnings"]):
            med["status"] = "待复核"
        med["warnings"] = warnings


def update_drug_rules(state, p, today, change):
    result = change(state, p, today)
    for resident in state["residents"]:
        if resident["status"] == "在住":
            refresh_medication_warnings(state, resident)
    return result


def publish_drug_rule(state, p, today):
    return update_drug_rules(state, p, today, drug_rules.publish)


def retire_drug_rule(state, p, today):
    return update_drug_rules(state, p, today, drug_rules.retire)


def add_medication(state, p, today):
    resident = get_resident(state, p.get("residentId"))
    name = required_field(p, "name", "药品名")
    instruction = required_field(p, "instruction", "医嘱或执行说明")
    interaction = text_field(p.get("interactionNote"), "配伍核查事项")
    warnings = medication_warnings(state, resident, name, interaction)
    scheduled = text_field(p.get("scheduledAt"), "医嘱给药时间", limit=16)
    if scheduled:
        try:
            if (
                datetime.strptime(scheduled, "%Y-%m-%dT%H:%M").strftime(
                    "%Y-%m-%dT%H:%M"
                )
                != scheduled
            ):
                raise ValueError
        except ValueError:
            raise ValueError("请填写日期和24小时制的给药时间。") from None
    append_record(
        state,
        "medications",
        residentId=resident["id"],
        name=name,
        instruction=instruction,
        scheduledAt=scheduled,
        prescribedBy=text_field(p.get("operator"), "登记人"),
        assignee=text_field(p.get("assignee"), "责任人"),
        date=today,
        warnings=warnings,
        interactionNote=interaction,
        status="待复核",
    )
    refresh_medication_warnings(state, resident)
    return f"登记{resident['name']}的用药计划「{name}」，等待人工复核"


def review_medication(state, p, today):
    record = lookup(state, "medications", p.get("medicationId"))
    resident = get_resident(state, record["residentId"])
    if record["status"] != "待复核":
        raise ValueError("该用药记录不在待复核状态。")
    reviewer = required_field(p, "reviewer", "复核人")
    warnings = medication_warnings(
        state, resident, record["name"], record.get("interactionNote", ""), record["id"]
    )
    note = text_field(p.get("note"), "核查意见", required=bool(warnings))
    record.update(
        status="待执行",
        reviewer=reviewer,
        reviewedAt=today,
        note=note,
        warnings=warnings,
    )
    record.setdefault("reviews", []).append(
        dict(
            reviewer=reviewer,
            date=today,
            note=note,
            warnings=list(warnings),
            ruleIds=[
                r["id"]
                for r in drug_rules.matching(
                    state, resident["id"], record["name"], record["id"]
                )
            ],
        )
    )
    return f"{reviewer}复核了{resident['name']}的用药记录"


def give_medication(state, p, today):
    record = lookup(state, "medications", p.get("medicationId"))
    resident = get_resident(state, record["residentId"])
    if record["status"] != "待执行":
        raise ValueError("请先完成人工核查，已执行记录不可再次执行。")
    operator = required_field(p, "operator", "执行人")
    warnings = medication_warnings(
        state, resident, record["name"], record.get("interactionNote", ""), record["id"]
    )
    if set(warnings) - set(record["warnings"]):
        raise ValueError("发现新增风险，请重新登记并核查用药计划。")
    record.update(
        status="已执行",
        operator=operator,
        executedAt=today,
        executedTime=p.get("nowLocal", today),
        executionNote=text_field(p.get("executionNote"), "实际执行补充"),
    )
    refresh_medication_warnings(state, resident)
    return f"{operator}记录了{resident['name']}的给药执行凭证"


def vital(state, p, today):
    resident = get_resident(state, p.get("residentId"))
    metric = required_field(p, "metric", "指标")
    raw_value = p.get("value")
    value = text_field(
        str(raw_value) if type(raw_value) in (float, int) else raw_value,
        "实测值",
        required=True,
        limit=80,
    )
    abnormal = p.get("abnormal", False)
    if not isinstance(abnormal, bool):
        raise ValueError("异常标记须为布尔值。")
    append_record(
        state,
        "vitals",
        residentId=resident["id"],
        metric=metric,
        value=value,
        unit=text_field(p.get("unit"), "单位"),
        abnormal=abnormal,
        status="待复核" if abnormal else "已记录",
        date=today,
        operator=text_field(p.get("operator") or "值班人员", "记录人"),
        note=text_field(p.get("note"), "情况说明"),
    )
    return f"登记{resident['name']}的{metric}" + ("并上报异常" if abnormal else "")


def resolve_vital(state, p, today):
    record = lookup(state, "vitals", p.get("vitalId"))
    if record["status"] != "待复核":
        raise ValueError("仅待复核异常可登记处置情况。")
    operator = required_field(p, "operator", "处置人")
    record.update(
        status="已处理",
        resolvedAt=today,
        resolvedBy=operator,
        resolution=required_field(p, "note", "处置记录"),
    )
    return f"{operator}完成{record['metric']}异常复核"


def handover(state, p, today):
    assignee = required_field(p, "assignee", "接班人")
    resident_id = p.get("residentId") or ""
    if resident_id:
        get_resident(state, resident_id)

    def relevant(row):
        return not resident_id or row["residentId"] == resident_id

    tasks = [
        t
        for t in state["tasks"]
        if relevant(t) and t["date"] == today and t["status"] != "已取消"
    ]
    completed = sum(t["status"] == "已完成" for t in tasks)
    alerts = sum(relevant(v) and v["status"] == "待复核" for v in state["vitals"])
    summary = f"今日照护工单 {len(tasks)} 项，已完成 {completed} 项，待完成 {len(tasks) - completed} 项。待复核体征异常 {alerts} 项。"
    append_record(
        state,
        "handovers",
        date=today,
        residentId=resident_id,
        assignee=assignee,
        note=text_field(p.get("note"), "交班补充"),
        summary=summary,
    )
    return f"为{assignee}生成并登记当日交班记录"
