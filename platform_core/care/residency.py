"""接待、床位分配、床头卡与长者档案。"""

from .clinical import refresh_medication_warnings
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


def vacant_bed(state, bed_id):
    bed = lookup(state, "beds", bed_id)
    if bed["residentId"] or bed["status"] != "空闲":
        raise ValueError("该床位已被占用，请选择空闲床位。")
    return bed


def make_card_code(sequence):
    """EAN-8 本地卡号。编号对应一次床位分配，不复用已注销卡。"""
    digits = str(2000000 + sequence)
    if len(digits) != 7:
        raise ValueError("本地床头卡编号已用尽。")
    checksum = sum(
        int(digit) * (3 if i % 2 == 0 else 1) for i, digit in enumerate(digits)
    )
    return digits + str(-checksum % 10)


def active_card(state, resident):
    for index in range(len(state["bedMoves"]) - 1, -1, -1):
        move = state["bedMoves"][index]
        if move["residentId"] == resident["id"]:
            if move["bedId"] and move["bedId"] == resident["bedId"]:
                return move.get("cardCode") or make_card_code(index + 1)
            break
    return ""


def move(state, resident, today, kind, old_bed=None, new_bed=None):
    card_code = make_card_code(len(state["bedMoves"]) + 1) if new_bed else ""
    rates = {"bedDailyRate": new_bed.get("dailyRate", 60)} if new_bed else {}
    if kind == "入住":
        rates["initialCareLevel"] = resident["level"]
    if old_bed:
        old_bed.update(residentId="", status="空闲")
    if new_bed:
        new_bed.update(residentId=resident["id"], status="已入住")
    resident["bedId"] = new_bed["id"] if new_bed else ""
    append_record(
        state,
        "bedMoves",
        residentId=resident["id"],
        date=today,
        kind=kind,
        beforeBedId=old_bed["id"] if old_bed else "",
        bedId=resident["bedId"],
        cardCode=card_code,
        **rates,
    )


def inquire(state, p, today):
    name = required_field(p, "name", "意向长者姓名")
    append_record(
        state,
        "inquiries",
        **({"campusId": p["campusId"]} if "campusId" in p else {}),
        name=name,
        contact=text_field(p.get("contact"), "联系方式"),
        note=text_field(p.get("note"), "接待记录"),
        date=today,
        status="待跟进",
    )
    return f"登记了{name}的入住意向"


def admit(state, p, today):
    inquiry = lookup(state, "inquiries", p["inquiryId"]) if p.get("inquiryId") else None
    if inquiry and inquiry["status"] != "待跟进":
        raise ValueError("这条意向已办理入住。")
    name = text_field(
        p.get("name") or (inquiry and inquiry["name"]),
        "长者姓名",
        required=True,
        limit=60,
    )
    bed = vacant_bed(state, p.get("bedId"))
    level = care_level(p.get("level") or "自理")
    end_date = iso_date(p.get("endDate") or offset_date(today, 365), "入住到期日")
    if end_date < today:
        raise ValueError("入住到期日不能早于今天。")
    age = p.get("age")
    if age not in ("", None):
        try:
            age = int(str(age))
            if not 0 <= age <= 125:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("请输入有效年龄。") from None
    else:
        age = None
    resident = append_record(
        state,
        "residents",
        name=name,
        bedId="",
        level=level,
        status="在住",
        age=age,
        gender=text_field(p.get("gender") or "未登记", "性别"),
        allergies=text_field(p.get("allergies"), "过敏史"),
        risk=text_field(p.get("risk"), "风险要点"),
        contact=text_field(
            p.get("contact") or (inquiry and inquiry["contact"]), "联系人"
        ),
        admittedAt=today,
        endDate=end_date,
        dischargedAt="",
        summary="",
        inquiryId=inquiry["id"] if inquiry else "",
    )
    move(state, resident, today, "入住", new_bed=bed)
    if inquiry:
        inquiry.update(status="已入住", residentId=resident["id"])
    return f"为{name}办理入住，分配{bed['label']}"


def transfer(state, p, today):
    resident = get_resident(state, p.get("residentId"))
    new_bed = vacant_bed(state, p.get("bedId"))
    old_bed = lookup(state, "beds", resident["bedId"])
    move(state, resident, today, "转床", old_bed, new_bed)
    return f"{resident['name']}从{old_bed['label']}转至{new_bed['label']}"


def discharge(state, p, today):
    resident = get_resident(state, p.get("residentId"))
    note = text_field(p.get("note"), "退住说明")
    old_bed = lookup(state, "beds", resident["bedId"])
    move(state, resident, today, "退住", old_bed=old_bed)
    resident.update(status="已退住", dischargedAt=today, dischargeNote=note)
    for collection in ("tasks", "plans", "medications"):
        for entry in state[collection]:
            if entry["residentId"] == resident["id"] and entry["status"] in (
                "待执行",
                "待复核",
            ):
                entry["status"] = "已取消"
    return f"{resident['name']}办理退住，释放{old_bed['label']}"


def renew(state, p, today):
    resident = get_resident(state, p.get("residentId"))
    end_date = iso_date(p.get("endDate"), "续住到期日")
    if end_date <= max(today, resident["endDate"]):
        raise ValueError("续住到期日须晚于今天及当前到期日。")
    resident["endDate"] = end_date
    return f"将{resident['name']}的入住期限延长至{end_date}"


def leave(state, p, today):
    resident = get_resident(state, p.get("residentId"))
    start = iso_date(p.get("startDate"), "请假开始日")
    end = iso_date(p.get("endDate"), "请假结束日")
    if not resident["admittedAt"] <= start <= end <= resident["endDate"]:
        raise ValueError("请假区间须在入住期限内，且结束日不早于开始日。")
    if any(
        x["residentId"] == resident["id"]
        and x["startDate"] <= end
        and x["endDate"] >= start
        for x in state["leaves"]
    ):
        raise ValueError("该时段与已有请假记录重叠。")
    append_record(
        state,
        "leaves",
        residentId=resident["id"],
        startDate=start,
        endDate=end,
        date=today,
        reason=text_field(p.get("reason"), "请假原因"),
    )
    return f"登记{resident['name']}从{start}至{end}的请假，保留床位"


def archive(state, p, today):
    resident = lookup(state, "residents", p.get("residentId"))
    summary = required_field(p, "summary", "档案摘要")
    reviewer = required_field(p, "reviewer", "核对人")
    allergies = text_field(p.get("allergies", resident["allergies"]), "过敏史")
    risk = text_field(p.get("risk", resident["risk"]), "高危要点")
    append_record(
        state,
        "archives",
        date=today,
        residentId=resident["id"],
        reviewer=reviewer,
        summary=summary,
        allergies=allergies,
        risk=risk,
    )
    resident.update(summary=summary, allergies=allergies, risk=risk)
    # 修改过敏史后，未执行医嘱回到人工复核。档案不能静默改变已核查结果。
    refresh_medication_warnings(state, resident)
    return f"{reviewer}核对并回填{resident['name']}的档案摘要"
