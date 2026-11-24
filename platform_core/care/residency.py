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


TRIAL_PENDING = "试住到期待确认"


def vacant_bed(state, bed_id):
    bed = lookup(state, "beds", bed_id)
    if bed["residentId"] or bed["status"] != "空闲":
        raise ValueError("该床位已被占用，请选择空闲床位。")
    return bed


def make_card_code(sequence):
    """EAN-8 本地卡号。编号对应一次床位分配，不复用已注销卡。"""
    return ean8(2000000 + sequence)


def ean8(number):
    digits = str(number)
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
            return ""
    historical = resident.get("legacyBedCard") or {}
    if historical.get("bedId") == resident.get("bedId"):
        return historical.get("code", "")
    return ""


def current_cards(state, residents):
    """Resolve the latest verified card using the original, unfiltered ledger positions."""
    people = {
        p["id"]: p for p in residents if p.get("status") == "在住" and p.get("bedId")
    }
    occupied = {b["id"]: b.get("residentId") for b in state["beds"]}
    result = {
        rid: p["legacyBedCard"] for rid, p in people.items() if p.get("legacyBedCard")
    }
    for index, move in enumerate(state.get("bedMoves", ()), 1):
        rid = move["residentId"]
        if rid not in people:
            continue
        if move.get("bedId"):
            result[rid] = {
                "bedId": move["bedId"],
                "code": move.get("cardCode") or make_card_code(index),
            }
        else:
            result.pop(rid, None)
    return {
        rid: card
        for rid, card in result.items()
        if card["bedId"] == people[rid]["bedId"] and occupied.get(card["bedId"]) == rid
    }


def move(state, resident, today, kind, old_bed=None, new_bed=None):
    card_code = make_card_code(len(state["bedMoves"]) + 1) if new_bed else ""
    rates = {"bedDailyRate": new_bed.get("dailyRate", 60)} if new_bed else {}
    if kind == "入住":
        rates["initialCareLevel"] = resident["level"]
        rates["stayType"] = resident["stayType"]
    if old_bed and old_bed.get("residentId") == resident["id"]:
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


def register(state, p, today):
    """Create an independent dossier before this stay can occupy a bed."""
    inquiry = lookup(state, "inquiries", p["inquiryId"]) if p.get("inquiryId") else None
    if inquiry and (inquiry["status"] != "待跟进" or inquiry.get("residentId")):
        raise ValueError("该历史咨询已关联档案。")
    name = text_field(
        p.get("name") or (inquiry and inquiry["name"]),
        "长者姓名",
        required=True,
        limit=60,
    )
    kind = p.get("kind", "new")
    if kind not in ("new", "archive") or p.get("bedId"):
        raise ValueError("请选择新档案或归档老人，床位在建档后分配。")
    archived = kind == "archive"
    prior = iso_date(p.get("archiveDate") or today, "归档日期") if archived else ""
    if prior and not offset_date(today, -365) < prior <= today:
        raise ValueError("归档日期须在最近 365 天内。")
    age = p.get("age")
    if age not in ("", None):
        try:
            age = int(str(age))
            if not 0 <= age <= 125:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("请选择 0 至 125 岁的年龄。") from None
    else:
        age = None
    gender = p.get("gender") or "未登记"
    if gender not in ("未登记", "男", "女"):
        raise ValueError("请选择性别。")
    resident = append_record(
        state,
        "residents",
        name=name,
        bedId="",
        level=care_level(p.get("level") or "自理"),
        status="已退住" if archived else "未入住",
        age=age,
        gender=gender,
        allergies="",
        risk="",
        contact=inquiry.get("contact", "") if inquiry else "",
        admittedAt="",
        endDate="",
        dischargedAt=prior,
        summary="",
        inquiryId=inquiry["id"] if inquiry else "",
        registeredAt=today,
        registeredCampusId=p.get("campusId", ""),
    )
    if archived:
        resident["archiveUntil"] = offset_date(prior, 365)
    if inquiry:
        inquiry.update(status="已建档", residentId=resident["id"])
    return ("登记归档老人" if archived else "建立待入住档案") + name


def date_archive(state, p, today):
    from .archive_retention import expiry

    person = lookup(state, "residents", p.get("residentId"))
    if person["status"] != "已退住" or expiry(person):
        raise ValueError("仅可为缺少有效退住日期的历史档案补登日期。")
    date = iso_date(p.get("archiveDate"), "凭证上的退住日期")
    if date > today:
        raise ValueError("退住日期不应晚于今日。")
    person.update(dischargedAt=date, archiveUntil=offset_date(date, 365))
    return "依据原凭证补登记归档日期"


def file_archive(state, p, today):
    person = lookup(state, "residents", p.get("residentId"))
    if person["status"] != "未入住":
        raise ValueError("请从未入住档案封存历史资料；在住长者须先办理退住。")
    day = iso_date(p.get("archiveDate"), "原退住或归档日期")
    if not offset_date(today, -365) < day <= today:
        raise ValueError("归档日期须在最近 365 天内。")
    person.update(status="已退住", dischargedAt=day, archiveUntil=offset_date(day, 365))
    return "封存历史档案 " + person["name"]


def trial_days(value):
    from ..operations.records import whole_number

    days = whole_number(value, "试住天数")
    if days > 365:
        raise ValueError("请选择 1 至 365 天的试住时长。")
    return days


def monthly_billing_day(value, today):
    from ..operations.records import whole_number

    if value in (None, ""):
        return int(today[-2:])
    day = whole_number(value, "月付账单日")
    if day > 31:
        raise ValueError("月付账单日须为 1 至 31 日。")
    return day


def contract_end(value, today):
    if value in (None, ""):
        return ""
    end = iso_date(value, "合同到期日")
    if end < today:
        raise ValueError("合同到期日不能早于今天。")
    return end


def admit(state, p, today, *, preview=False):
    from ..operations import admission_finance

    if not p.get("residentId") or set(p) - {
        "residentId",
        "bedId",
        "level",
        "endDate",
        "stayType",
        "billingDay",
        "trialDays",
        "trialPrice",
        "admittedAt",
    } - admission_finance.TERMS:
        raise ValueError("请先建立长者档案，办理入住时只选择已有未入住档案。")
    resident = lookup(state, "residents", p["residentId"])
    if resident["status"] != "未入住" or resident.get("bedId"):
        raise ValueError(
            "请选择未入住档案。在住长者请转床，归档老人再次入住须建立本次档案。"
        )
    bed = vacant_bed(state, p.get("bedId"))
    arrival = admission_finance.admission_date(p, today)
    if any(bed["id"] in (move.get("bedId"), move.get("beforeBedId")) and move["date"] > arrival
           for move in state.get("bedMoves", ())):
        raise ValueError("入住日期早于该床位最近的占用变化，请确认入住房间和日期")
    level = care_level(p.get("level") or resident["level"])
    stay_type = p.get("stayType", "formal")
    if stay_type not in ("formal", "trial"):
        raise ValueError("请选择正式入住或试住。")
    terms = {}
    if stay_type == "trial":
        from ..operations.records import currency_amount

        defaults = (state.get("trialPolicies") or [{}])[0]
        days = trial_days(p.get("trialDays", defaults.get("days", 3)))
        price = p.get("trialPrice", defaults.get("fee"))
        if price in (None, ""):
            raise ValueError("请填写本次试住总价；免费试住请明确填写 0 元。")
        terms.update(
            trialDays=days,
            trialEndsAt=offset_date(arrival, days - 1),
            trialPrice=float(currency_amount(price, "试住总价")),
        )
        if terms["trialEndsAt"] < today:
            raise ValueError("试住结束日期已过，请核对入住日期和天数")
    elif {"trialDays", "trialPrice"} & p.keys():
        raise ValueError("正式入住请使用月付账期。")
    if stay_type == "formal" or p.get("billingDay") not in (None, ""):
        terms["billingDay"] = monthly_billing_day(p.get("billingDay"), arrival)
    resident.update(
        status="在住",
        stayType=stay_type,
        admittedAt=arrival,
        endDate=contract_end(p.get("endDate"), arrival),
        level=level,
        **terms,
    )
    move(state, resident, arrival, "入住", new_bed=bed)
    inquiry = next(
        (r for r in state["inquiries"] if r["id"] == resident.get("inquiryId")), None
    )
    if inquiry:
        inquiry["status"] = "已入住"
    quote = admission_finance.post(state, resident, p, today, preview=preview)
    if preview:
        return quote
    if stay_type == "trial":
        return (
            f"为{resident['name']}办理{days}天试住，分配{bed['label']}，"
            f"试住至{terms['trialEndsAt']}，整次费用 ¥{terms['trialPrice']:.2f}"
        )
    return f"为{resident['name']}办理正式入住，分配{bed['label']}，月付账单日为每月{terms['billingDay']}日"


def undecided_trial(state, resident_id):
    resident = lookup(state, "residents", resident_id)
    if resident.get("stayType") != "trial" or resident["status"] not in (
        "在住",
        TRIAL_PENDING,
    ):
        raise ValueError("请选择尚未确认入住结果的试住档案。")
    return resident


def confirm_stay(state, p, today, *, preview=False):
    from ..operations import admission_finance

    if not p.get("residentId") or set(p) - {
        "residentId",
        "billingDay",
        "endDate",
        "bedId",
        "admittedAt",
    } - admission_finance.TERMS:
        raise ValueError("请从长者档案确认试住转正式入住。")
    resident = undecided_trial(state, p["residentId"])
    new_bed = current = None
    if resident.get("bedId"):
        current = lookup(state, "beds", resident["bedId"])
        if current["residentId"] != resident["id"]:
            raise ValueError("试住床位登记已改变，请核对当前床位。")
        if p.get("bedId") and p["bedId"] != current["id"]:
            new_bed = vacant_bed(state, p["bedId"])
    else:
        if not p.get("bedId"):
            raise ValueError("试住床位已释放，请选择当前空闲床位。")
        new_bed = vacant_bed(state, p["bedId"])
    formal = admission_finance.admission_date(p, today, resident["admittedAt"])
    if not current and formal != today:
        raise ValueError("试住床位已释放，请从今日重新登记正式入住")
    first_regular_day = max(formal, resident.get("trialEndsAt") or formal)
    billing_day = monthly_billing_day(p.get("billingDay", resident.get("billingDay")), first_regular_day)
    resident.update(
        status="在住",
        stayType="formal",
        formalizedAt=formal,
        billingDay=billing_day,
        endDate=contract_end(p.get("endDate", resident.get("endDate")), today),
    )
    if new_bed:
        move(
            state,
            resident,
            today,
            "转床" if current else "确认入住",
            old_bed=current,
            new_bed=new_bed,
        )
    quote = admission_finance.post(state, resident, p, today, preview=preview)
    if preview:
        return quote
    return f"为{resident['name']}办理试住转正式入住，月付账单日为每月{billing_day}日"


def transfer(state, p, today):
    resident = get_resident(state, p.get("residentId"))
    if "fromBedId" in p and p["fromBedId"] != resident["bedId"]:
        raise ValueError("原床位已改变，请重新核对转床。")
    new_bed = vacant_bed(state, p.get("bedId"))
    old_bed = lookup(state, "beds", resident["bedId"])
    move(state, resident, today, "转床", old_bed, new_bed)
    return f"{resident['name']}从{old_bed['label']}转至{new_bed['label']}"


def discharge(state, p, today):
    resident = get_resident(state, p.get("residentId"))
    if resident.get("stayType") == "trial":
        raise ValueError("试住未转正式，请办理试住离院并指派回访。")
    note = text_field(p.get("note"), "退住说明")
    return release_bed(state, resident, today, note)


def end_trial(state, p, today):
    resident = undecided_trial(state, p.get("residentId"))
    reason = required_field(p, "reason", "试住未转正式原因")
    release_bed(state, resident, today, reason)
    return f"{resident['name']}试住未转正式，已退床归档并派发回访"


def release_bed(state, resident, today, note):
    old_bed = None
    if resident.get("bedId"):
        old_bed = lookup(state, "beds", resident["bedId"])
        move(state, resident, today, "退住", old_bed=old_bed)
    resident.update(
        status="已退住",
        dischargedAt=today,
        archiveUntil=offset_date(today, 365),
        dischargeNote=note,
    )
    for collection in ("tasks", "plans", "medications"):
        for entry in state[collection]:
            if entry["residentId"] == resident["id"] and entry["status"] in (
                "待执行",
                "待复核",
            ):
                entry["status"] = "已取消"
    return f"{resident['name']}办理退住" + (
        f"，释放{old_bed['label']}" if old_bed else ""
    )


def renew(state, p, today):
    from ..operations import contract_renewal

    resident = get_resident(state, p.get("residentId"))
    if resident.get("stayType") == "trial":
        raise ValueError("试住长者请在转正式时确定合同期限。")
    if not resident.get("endDate"):
        raise ValueError("当前合同为无期限，无需续住。")
    if p.get("endDate") == "":
        contract_renewal.record(state, resident, "", today, source="manual")
        return f"将{resident['name']}的入住合同续为无期限"
    end_date = iso_date(p.get("endDate"), "续住到期日")
    if end_date <= max(today, resident["endDate"]):
        raise ValueError("续住到期日须晚于今天及当前到期日。")
    contract_renewal.record(state, resident, end_date, today, source="manual")
    return f"将{resident['name']}的入住期限延长至{end_date}"


def leave(state, p, today):
    resident = get_resident(state, p.get("residentId"))
    start = iso_date(p.get("startDate"), "请假开始日")
    end = iso_date(p.get("endDate"), "请假结束日")
    if not resident["admittedAt"] <= start <= end or (
        resident.get("endDate") and end > resident["endDate"]
    ):
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
