"""Local screening, follow-up and externally acknowledged referral records."""

from uuid import UUID

from .records import (
    append_record,
    get_resident,
    iso_date,
    lookup,
    required_field,
    text_field,
)


def screen(state, p, today):
    resident = get_resident(state, p.get("residentId"))
    subject = required_field(p, "subject", "筛查项目")
    finding = required_field(p, "finding", "观察或筛查结果")
    operator = required_field(p, "operator", "筛查登记人")
    state.setdefault("followups", [])
    append_record(
        state,
        "followups",
        residentId=resident["id"],
        subject=subject,
        finding=finding,
        openedBy=operator,
        date=today,
        status="待分级",
    )
    return f"登记{resident['name']}的筛查结果，等待分级安排"


def schedule_followup(state, p, today):
    state.setdefault("followups", [])
    row = lookup(state, "followups", p.get("followupId"))
    if row["status"] != "待分级":
        raise ValueError("仅待分级筛查可以安排干预。")
    risk = p.get("priority")
    if risk not in ("常规随访", "重点跟进", "优先复核"):
        raise ValueError("请选择人员确认的跟进级别。")
    due = iso_date(p.get("dueDate"), "预约日期")
    if due < today:
        raise ValueError("预约日期不能早于今天。")
    target = text_field(p.get("assessmentId"), "评估编号", limit=100)
    if (
        target
        and lookup(state, "assessments", target)["residentId"] != row["residentId"]
    ):
        raise ValueError("评估记录与当前长者不符。")
    row.update(
        priority=risk,
        basis=required_field(p, "basis", "分级依据"),
        assessmentId=target,
        intervention=required_field(p, "intervention", "干预安排"),
        assignee=required_field(p, "assignee", "责任人"),
        dueDate=due,
        gradedBy=required_field(p, "operator", "分级登记人"),
        gradedAt=today,
        status="待随访",
    )
    return "已安排筛查后的干预与随访"


def finish_followup(state, p, today):
    state.setdefault("followups", [])
    row = lookup(state, "followups", p.get("followupId"))
    if row["status"] != "待随访":
        raise ValueError("请先完成分级并安排随访；已评价的记录不能重复办理。")
    action = required_field(p, "actual", "实际干预与随访")
    outcome = required_field(p, "outcome", "效果评价")
    operator = required_field(p, "operator", "随访记录人")
    row.update(
        actual=action,
        outcome=outcome,
        finishedBy=operator,
        finishedAt=today,
        status="已评价",
    )
    return "已保留实际干预、随访结果与效果评价"


def refer(state, p, today):
    person = lookup(state, "residents", p.get("residentId"))
    kind = p.get("kind")
    if kind not in ("院外转介", "出院衔接"):
        raise ValueError("请选择转介或出院衔接。")
    target = required_field(p, "destination", "接收单位")
    channel = p.get("channel") or "医联体"
    if channel not in ("医联体", "基层公卫", "长护险经办", "其他机构"):
        raise ValueError("请选择接收机构所属渠道。")
    summary = required_field(p, "summary", "交接情况与后续安排")
    operator = required_field(p, "operator", "交接人")
    assessment_id = text_field(p.get("assessmentId"), "依据评估编号", limit=100)
    if (
        assessment_id
        and lookup(state, "assessments", assessment_id)["residentId"] != person["id"]
    ):
        raise ValueError("交接所引评估与长者不符。")
    state.setdefault("referrals", [])
    append_record(
        state,
        "referrals",
        residentId=person["id"],
        kind=kind,
        destination=target,
        channel=channel,
        residentName=person["name"],
        summary=summary,
        assessmentId=assessment_id,
        date=today,
        operator=operator,
        allergies=person.get("allergies", ""),
        risk=person.get("risk", ""),
        status="待接收回执",
    )
    return f"登记{person['name']}的{kind}，等待接收回执"


def receive_referral(state, p, today):
    state.setdefault("referrals", [])
    ref = lookup(state, "referrals", p.get("referralId"))
    if ref["status"] != "待接收回执":
        raise ValueError("该交接已登记回执。")
    ref.update(
        receivedBy=required_field(p, "receiver", "接收方联系人"),
        receipt=required_field(p, "receipt", "回执编号或核实记录"),
        recordedBy=required_field(p, "operator", "本院登记人"),
        receivedAt=today,
        status="已登记回执",
    )
    return f"登记{ref['destination']}的交接回执"


SCOPES = ("姓名与交接摘要", "姓名、交接摘要和过敏及风险记录")


def referral_consent(state, p, today):
    state.setdefault("referrals", [])
    ref = lookup(state, "referrals", p.get("referralId"))
    decision = p.get("decision")
    scope = p.get("scope") if decision == "同意" else ""
    if decision not in ("同意", "撤回") or (decision == "同意" and scope not in SCOPES):
        raise ValueError("请明确本次授权或撤回、本人同意的共享范围。")
    history = ref.get("consents", [])
    if decision == "撤回" and (not history or history[-1]["decision"] != "同意"):
        raise ValueError("该交接当前没有有效授权。")
    entry = dict(
        decision=decision,
        scope=scope,
        date=today,
        basis=required_field(p, "basis", "本人授权或撤回的核验记录编号"),
        operator=required_field(p, "operator", "登记人"),
    )
    ref.setdefault("consents", []).append(entry)
    return f"已记录长者本人{decision}向{ref['destination']}共享交接资料"


def export_referral(state, p, today):
    state.setdefault("referrals", [])
    ref = lookup(state, "referrals", p.get("referralId"))
    consents = ref.get("consents", [])
    if not consents or consents[-1]["decision"] != "同意":
        raise ValueError("请先登记长者对本次接收单位与共享范围的有效授权。")
    consent = consents[-1]
    operator = required_field(p, "operator", "导出人")
    try:
        export_id = str(UUID(p.get("exportId", "")))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("导出凭证编号无效。") from None
    if any(e["id"] == export_id for e in ref.get("exports", [])):
        raise ValueError("已有本次导出凭证。")
    content = dict(
        version="1.0",
        referralId=ref["id"],
        exportId=export_id,
        residentName=ref.get("residentName")
        or lookup(state, "residents", ref["residentId"])["name"],
        channel=ref.get("channel", "其他机构"),
        destination=ref["destination"],
        handoff=ref["kind"],
        summary=ref["summary"],
        date=ref["date"],
        consentScope=consent["scope"],
    )
    if consent["scope"] == SCOPES[1]:
        content.update(allergies=ref["allergies"], risk=ref["risk"])
    entry = dict(
        id=export_id,
        operator=operator,
        date=today,
        consentNumber=len(consents),
        content=content,
    )
    ref.setdefault("exports", []).append(entry)
    return f"已生成发往{ref['destination']}的本地交接数据包"
