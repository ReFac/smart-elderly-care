"""按入住记录计费，登记到账、冲抵和核销凭证。"""

from decimal import Decimal

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


def leave_count(state, resident_id, begin, end):
    away = set()
    for entry in state.get("leaves", []):
        if entry["residentId"] != resident_id:
            continue
        first = max(begin, parse_day(entry["startDate"]))
        last = min(end, parse_day(entry["endDate"]))
        away.update(range(first.toordinal(), last.toordinal() + 1))
    return len(away)


def generate_bill(state, payload, today):
    resident = get_resident(state, payload)
    month = payload.get("month")
    first, last = month_bounds(month, today)
    if any(
        b["residentId"] == resident["id"] and b["month"] == month
        for b in state["bills"]
    ):
        raise ValueError("该长者本月已有账单")
    arrival = parse_day(resident.get("admittedAt"))
    discharge = resident.get("dischargedAt")
    if resident["status"] == "已退住" and not discharge:
        raise ValueError("退住档案缺少退住日期")
    begin = max(arrival, first)
    end = min(parse_day(discharge), last) if discharge else last
    days = (end - begin).days + 1
    if days < 1:
        raise ValueError("该长者在此账期没有入住记录")
    bed = next(
        (b for b in state.get("beds", []) if b["id"] == resident.get("bedId")), {}
    )
    bed_fee = currency_amount(
        payload.get("bedFee", bed.get("dailyRate", 60)), "每日床位费"
    )
    care_fee = currency_amount(
        payload.get("careFee", CARE_RATES.get(resident["level"], 45)), "每日护理费"
    )
    package_fee = currency_amount(payload.get("packageFee", 0), "月套餐费")
    calculated_leave = leave_count(state, resident["id"], begin, end)
    leave = whole_number(
        payload.get("leaveDays", calculated_leave), "请假天数", zero=True
    )
    if leave > days:
        raise ValueError("请假天数超过实际入住天数")
    amount = currency_amount(
        bed_fee * days + care_fee * (days - leave) + package_fee, "账单合计"
    )
    bill = dict(
        id=new_id("bill"),
        residentId=resident["id"],
        month=month,
        bedFee=float(bed_fee),
        careFee=float(care_fee),
        packageFee=float(package_fee),
        leaveDays=leave,
        serviceDays=days,
        bedId=resident.get("bedId", ""),
        careLevel=resident["level"],
        startDate=begin.isoformat(),
        endDate=end.isoformat(),
        amount=float(amount),
        paid=0,
        balance=float(amount),
        status="待缴费" if amount else "已结清",
        date=today,
    )
    state["bills"].insert(0, bill)
    apply_deposit(state, get_account(state, resident["id"]), today)
    return f"生成{resident['name']} {month} 账单 ¥{amount:.2f}，待缴 ¥{bill['balance']:.2f}"
