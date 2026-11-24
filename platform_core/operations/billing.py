"""按入住记录计费，登记到账、冲抵和核销凭证。"""

from datetime import date
from decimal import Decimal

from .charges import invoice_lines
from .records import (
    currency_amount,
    get_resident,
    lookup,
    month_bounds,
    new_id,
    parse_day,
    whole_number,
)


CARE_RATES = {"自理": 20, "半失能": 45, "失能": 70}


def get_account(state, resident_id):
    for account in state["deposits"]:
        if account["residentId"] == resident_id:
            return account
    account = dict(id=new_id("acct"), residentId=resident_id, amount=0)
    state["deposits"].append(account)
    return account


def credit(state, bill, amount, method, today):
    balance = Decimal(str(bill["balance"])) - amount
    bill["balance"] = float(balance)
    bill["paid"] = float(Decimal(str(bill["amount"])) - balance)
    bill["status"] = "已结清" if not balance else "部分缴费"
    state["payments"].insert(
        0,
        dict(
            id=new_id("pay"),
            billId=bill["id"],
            residentId=bill["residentId"],
            amount=float(amount),
            method=method,
            date=today,
        ),
    )


def apply_deposit(state, account, today):
    available = Decimal(str(account["amount"]))
    debt = sorted(
        (
            b
            for b in state["bills"]
            if b["residentId"] == account["residentId"] and b["balance"]
        ),
        key=lambda b: b["month"],
    )
    for bill in debt:
        if not available:
            break
        amount = min(available, Decimal(str(bill["balance"])))
        credit(state, bill, amount, "预交金冲抵", today)
        available -= amount
    account["amount"] = float(available)


def deposit(state, payload, today):
    resident = get_resident(state, payload)
    amount = currency_amount(payload.get("amount"), "预交金额", zero=False)
    account = get_account(state, resident["id"])
    account["amount"] = float(Decimal(str(account["amount"])) + amount)
    state["depositEntries"].insert(
        0,
        dict(
            id=new_id("receipt"),
            residentId=resident["id"],
            amount=float(amount),
            date=today,
        ),
    )
    apply_deposit(state, account, today)
    return f"登记{resident['name']}预交金 ¥{amount:.2f}，已核对欠款"


def pay(state, payload, today):
    bill = lookup(state, "bills", payload.get("billId"), "账单")
    amount = currency_amount(payload.get("amount"), "核销金额", zero=False)
    if payload.get("method", "线下登记") != "线下登记":
        raise ValueError("本地账单只支持已核实的线下收款登记")
    if amount > Decimal(str(bill["balance"])):
        raise ValueError("核销金额超过本单待缴余额")
    credit(state, bill, amount, "线下登记", today)
    return f"为 {bill['month']} 账单登记线下核销 ¥{amount:.2f}"


def leave_dates(state, resident_id, begin, end):
    away = set()
    for entry in state.get("leaves", []):
        if entry["residentId"] != resident_id:
            continue
        first = max(begin, parse_day(entry["startDate"]))
        last = min(end, parse_day(entry["endDate"]))
        away.update(range(first.toordinal(), last.toordinal() + 1))
    return away


def quote_bill(state, payload, today):
    resident = get_resident(state, payload)
    month = payload.get("month")
    first, last = month_bounds(month, today)
    if any(
        b["residentId"] == resident["id"] and b["month"] == month
        for b in state["bills"]
    ):
        raise ValueError("该长者本月已有账单")
    if not resident.get("admittedAt"):
        raise ValueError("该档案没有可计费的入住记录")
    arrival = parse_day(resident["admittedAt"])
    discharge = resident.get("dischargedAt")
    if resident["status"] == "已退住" and not discharge:
        raise ValueError("退住档案缺少退住日期")
    begin = max(arrival, first)
    end = min(parse_day(discharge), last) if discharge else last
    days = (end - begin).days + 1
    if days < 1:
        raise ValueError("该长者在此账期没有入住记录")
    parts, bed_total, care_total, leave = charge_segments(
        state, resident, payload, begin, end
    )
    last_part = parts[-1]
    package_fee = currency_amount(payload.get("packageFee", 0), "月套餐费")
    lines = invoice_lines(parts, package_fee, payload.get("items", []), days, leave)
    amount = currency_amount(
        sum(Decimal(str(item["amount"])) for item in lines), "账单合计"
    )
    bill = dict(
        residentId=resident["id"],
        month=month,
        bedFee=last_part["bedFee"],
        careFee=last_part["careFee"],
        bedTotal=float(bed_total),
        careTotal=float(care_total),
        segments=parts,
        lineItems=lines,
        manualOverrides=[k for k in ("bedFee", "careFee", "leaveDays") if k in payload],
        packageFee=float(package_fee),
        leaveDays=leave,
        serviceDays=days,
        bedId=last_part["bedId"],
        careLevel=last_part["level"],
        startDate=begin.isoformat(),
        endDate=end.isoformat(),
        amount=float(amount),
        paid=0,
        balance=float(amount),
        status="待缴费" if amount else "已结清",
        date=today,
    )
    return bill


def generate_bill(state, payload, today):
    bill = quote_bill(state, payload, today)
    bill["id"] = new_id("bill")
    resident = get_resident(state, payload)
    state["bills"].insert(0, bill)
    apply_deposit(state, get_account(state, resident["id"]), today)
    return f"生成{resident['name']} {bill['month']} 账单 ¥{bill['amount']:.2f}，待缴 ¥{bill['balance']:.2f}"


def charge_segments(state, resident, p, begin, end):
    """Use the last effective move/approval of each day, including the discharge day."""
    rid = resident["id"]
    beds = {b["id"]: b for b in state["beds"]}
    moves = sorted(
        (
            m
            for m in state.get("bedMoves", [])
            if m["residentId"] == rid and m.get("date")
        ),
        key=lambda m: m["date"],
    )
    plans = sorted(
        (
            r
            for r in state.get("plans", [])
            if r["residentId"] == rid
            and r.get("reviewedAt")
            and r["status"] == "已派发"
        ),
        key=lambda r: r["reviewedAt"],
    )
    levels = {
        a["id"]: a["level"]
        for a in state.get("assessments", [])
        if a.get("level") in CARE_RATES
    }
    bed_id = (moves[0].get("beforeBedId") if moves else None) or resident.get(
        "bedId", ""
    )
    level = next(
        (
            m["initialCareLevel"]
            for m in moves
            if m.get("initialCareLevel") in CARE_RATES
        ),
        None,
    )
    level = (
        level
        or (plans[0].get("previousCareLevel") if plans else None)
        or resident["level"]
    )
    rate = beds.get(bed_id, {}).get("dailyRate", 60)
    move_i = plan_i = 0
    entries = []
    days = range(begin.toordinal(), end.toordinal() + 1)
    for ordinal in days:
        day = date.fromordinal(ordinal).isoformat()
        while move_i < len(moves) and moves[move_i]["date"] <= day:
            move = moves[move_i]
            if move.get("bedId"):
                bed_id = move["bedId"]
                rate = move.get(
                    "bedDailyRate", beds.get(bed_id, {}).get("dailyRate", 60)
                )
            move_i += 1
        while plan_i < len(plans) and plans[plan_i]["reviewedAt"] <= day:
            plan = plans[plan_i]
            level = plan.get("careLevel") or levels.get(plan.get("assessmentId"), level)
            plan_i += 1
        bed_fee = currency_amount(p.get("bedFee", rate), "每日床位费")
        care_fee = currency_amount(
            p.get("careFee", CARE_RATES.get(level, 45)), "每日护理费"
        )
        entries.append((bed_id, level, bed_fee, care_fee))
    away = leave_dates(state, rid, begin, end)
    leave = whole_number(p.get("leaveDays", len(away)), "请假天数", zero=True)
    if leave > len(days):
        raise ValueError("请假天数超过实际入住天数")
    if leave != len(away):
        if len({day[3] for day in entries}) > 1:
            raise ValueError(
                "本月有多段护理单价，请按实际日期补全请假台账，或确认统一护理日费"
            )
        # A flat agreed care fee makes the financial result independent of the chosen dates.
        ranked = sorted(days, key=lambda n: (n not in away, -n))
        away = set(ranked[:leave])
    parts = []
    old = None
    bed_total = care_total = Decimal(0)
    for ordinal, charges in zip(days, entries):
        bed_id, level, bed_fee, care_fee = charges
        day = date.fromordinal(ordinal).isoformat()
        if charges != old:
            parts.append(
                dict(
                    start=day,
                    end=day,
                    bedId=bed_id,
                    bedLabel=beds.get(bed_id, {}).get("label", bed_id),
                    level=level,
                    bedFee=float(bed_fee),
                    careFee=float(care_fee),
                    days=0,
                    leaveDays=0,
                )
            )
            old = charges
        part = parts[-1]
        part["end"] = day
        part["days"] += 1
        part["leaveDays"] += int(ordinal in away)
        bed_total += bed_fee
        if ordinal not in away:
            care_total += care_fee
    return parts, bed_total, care_total, leave
