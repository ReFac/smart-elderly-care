"""Long-term care insurance case register; decisions come from the responsible payer."""

from datetime import date

from .care.records import append_record, iso_date, lookup, text_field
from .profile_fields import address_fields

STAGES = {
    "登记参保": "已参保",
    "登记申请": "已申请",
    "登记评估结论": "已评估",
    "登记待遇核定": "待遇已核定",
    "补录已核定待遇": "待遇已核定",
    "登记未予核定": "未予核定",
    "登记复评申请": "复评中",
    "登记待遇终止": "待遇已终止",
}
ALLOWED = {
    "": ("登记参保", "补录已核定待遇"),
    "已参保": ("登记申请", "补录已核定待遇"),
    "已申请": ("登记评估结论", "登记未予核定"),
    "已评估": ("登记待遇核定", "登记未予核定", "登记复评申请"),
    "待遇已核定": ("登记复评申请", "登记待遇终止"),
    "未予核定": ("登记复评申请", "登记申请"),
    "复评中": ("登记评估结论", "登记未予核定"),
    "待遇已终止": ("登记申请", "补录已核定待遇"),
}
GRADES = tuple(f"{i}级" for i in range(6)) + ("其他书面等级",)
INSURANCE_TYPES = ("城乡居民", "城镇职工")
SERVICES = ("机构护理", "居家护理", "社区护理", "其他核定方式")


def catalog():
    return {"stages": ALLOWED, "grades": GRADES, "services": SERVICES, "insuranceTypes": INSURANCE_TYPES}


def record(state, p, actor, today):
    person = lookup(state, "residents", p.get("residentId"))
    if person.get("status") not in ("在住", "待入住", "未入住", "新档案"):
        raise ValueError("归档长辈资料仅供查阅")
    events = state.setdefault("longCareEvents", [])
    last = next((r for r in reversed(events) if r["residentId"] == person["id"]), {})
    event = p.get("event")
    if event not in ALLOWED.get(last.get("status", ""), ()):
        raise ValueError("该办理阶段不适用，请刷新长护险档案")
    day = iso_date(p.get("date"), "经办日期")
    if day > today or day < last.get("date", ""):
        raise ValueError("经办日期不能晚于今日，也不能早于上一笔办理")
    region = p.get("region", last.get("region"))
    loc, label = address_fields(region, birthplace=True)
    if not loc["codes"]:
        raise ValueError("请选择参保统筹地区")
    reference = text_field(
        p.get("reference"), "参保/受理/结论文书编号", required=True, limit=100
    )
    insurance = p.get("insuranceType", last.get("insuranceType", ""))
    if insurance not in ("", *INSURANCE_TYPES):
        raise ValueError("请选择有效的参保险种")
    grade = p.get("grade", "")
    if event in ("登记评估结论", "补录已核定待遇"):
        if grade not in GRADES:
            raise ValueError("请按正式文书选择评估等级")
    elif grade:
        raise ValueError("当前环节不能登记录入评估等级")
    service = p.get("service", "")
    start = p.get("startsOn", "")
    end = p.get("endsOn", "")
    if event in ("登记待遇核定", "补录已核定待遇"):
        if service not in SERVICES:
            raise ValueError("请选择文书核定的护理服务方式")
        start = iso_date(start, "待遇起始日期")
        end = iso_date(end, "待遇截止日期") if end else ""
        if end and end < start:
            raise ValueError("待遇截止日不能早于起始日")
    elif service or start or end:
        raise ValueError("当前环节不能录入待遇有效期")
    note = text_field(
        p.get("note"),
        "文书补充",
        required=grade == "其他书面等级" or service == "其他核定方式",
        limit=300,
    )
    append_record(
        state,
        "longCareEvents",
        residentId=person["id"],
        date=day,
        event=event,
        status=STAGES[event],
        region=loc,
        regionLabel=label,
        reference=reference,
        grade=grade,
        insuranceType=insurance,
        service=service,
        startsOn=start,
        endsOn=end,
        note=note,
        actorId=actor["id"],
        operator=actor["displayName"],
    )
    return "登记长护险办理 · " + event


def status_text(record, today):
    """Display validity separately from the official decision and the case stage."""
    if record.get("status") != "待遇已核定":
        return record["status"]
    day = date.fromisoformat(today)
    if day < date.fromisoformat(record["startsOn"]):
        return "待遇待生效"
    if record.get("endsOn") and day > date.fromisoformat(record["endsOn"]):
        return "待遇有效期已届满"
    return "待遇有效期内"
