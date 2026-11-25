"""按入住记录计费，登记到账、冲抵和核销凭证。"""

from datetime import date
from decimal import Decimal

from . import billing_cycles, contract_renewal, payment_terms
from .charges import invoice_lines, line
from .records import (
    currency_amount,
    get_resident,
    lookup,
    new_id,
    parse_day,
    text_field,
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
    row = dict(
        id=new_id("pay"),
        billId=bill["id"],
        residentId=bill["residentId"],
        amount=float(amount),
        method=method,
        date=today,
    )
    state["payments"].insert(0, row)
    contract_renewal.after_credit(state, bill, row, today)
    return row


def apply_deposit(state, account, today):
    available = Decimal(str(account["amount"]))
    debt = sorted(
        (
            b
            for b in state["bills"]
            if b["residentId"] == account["residentId"] and b["balance"] and b.get("kind") != "security"
        ),
        key=lambda b: (
            b.get("billingDate") or b.get("startDate") or b["month"],
            {"trial": 0, "security": 2}.get(b.get("kind"), 1),
        ),
    )
    for bill in debt:
        if not available:
            break
        amount = min(available, Decimal(str(bill["balance"])))
        credit(state, bill, amount, "预交金冲抵", today)
        available -= amount
    account["amount"] = float(available)


def post_receipt(
    state, *, resident_id, bill, amount, method, channel, day, rate, origin
):
    """Allocate one tender and its fee exactly once across bill and advance ledgers."""
    account = get_account(state, resident_id)
    apply_deposit(state, account, day)
    applied = min(amount, Decimal(str(bill["balance"]))) if bill else Decimal(0)
    surplus = amount - applied
    total_fee = payment_terms.fee(amount, rate)
    applied_fee = payment_terms.fee(applied, rate)
    common = dict(
        **origin,
        channel=channel,
        grossAmount=float(amount),
        originBillId=bill["id"] if bill else "",
    )
    if applied:
        payment = credit(state, bill, applied, method, day)
        payment.update(common, **payment_terms.accounting(applied, applied_fee, rate))
    if surplus:
        account["amount"] = float(Decimal(str(account["amount"])) + surplus)
        state["depositEntries"].insert(
            0,
            dict(
                id=new_id("receipt"),
                residentId=resident_id,
                amount=float(surplus),
                date=day,
                method=method,
                **common,
                **payment_terms.accounting(surplus, total_fee - applied_fee, rate),
            ),
        )
        apply_deposit(state, account, day)
    return dict(
        billAmount=float(applied),
        depositAmount=float(surplus),
        **payment_terms.accounting(amount, total_fee, rate),
    )


def manual_receipt(state, payload, today, bill, resident_id):
    amount = currency_amount(payload.get("amount"), "实收金额", zero=False)
    method, channel = payment_terms.offline(payload)
    ref, duplicate = payment_terms.manual_reference(
        state,
        payload,
        bill_id=bill["id"] if bill else "",
        resident_id=resident_id,
        amount=amount,
        method=method,
        channel=channel,
    )
    if duplicate:
        return "已登记同一笔实收凭证"
    origin = dict(paymentRef=ref or new_id("manual"), receiptId=new_id("cash"))
    day = today
    if channel in ("微信支付", "支付宝"):
        from . import settlements

        day = settlements.paid_day(payload.get("paidDate"), today)
        txn = text_field(payload, "transactionId", "渠道交易号", 100)
        merchant = text_field(payload, "merchantOrder", "商户订单号", 100)
        if bill:
            receipt, added = settlements.settle(
                state,
                {**payload, "source": "线下核对商户成功交易", "paidDate": day},
                today,
                verification="线下登记核对",
            )
            return (
                "登记" if added else "已核对同一笔"
            ) + f"{channel}实收 ¥{receipt['amount']:.2f}"
        for entry in state["depositEntries"]:
            if entry.get("channel") == channel and (
                entry.get("transactionId") == txn
                or entry.get("merchantOrder") == merchant
            ):
                if (
                    not entry.get("originBillId")
                    and entry["residentId"] == resident_id
                    and entry.get("transactionId") == txn
                    and entry.get("merchantOrder") == merchant
                    and entry["amount"] == float(amount)
                    and entry["date"] == day
                ):
                    return "已登记同一笔预缴凭证"
                raise ValueError("此笔交易已有凭证，请核对所关联账单")
        if any(
            order["id"] == merchant for order in state.get("paymentOrders", ())
        ) or any(
            r["channel"] == channel
            and (r["transactionId"] == txn or r["merchantOrder"] == merchant)
            for r in state.get("channelReceipts", ())
        ):
            raise ValueError("此订单已关联账单，请在原账单核对到账")
        origin.update(transactionId=txn, merchantOrder=merchant)
    if bill and (
        not bill["balance"]
        or (
            amount > Decimal(str(bill["balance"]))
            and payload.get("carrySurplus") is not True
        )
    ):
        raise ValueError("请核对本单余额并确认将超额款转入预缴金")
    allocation = post_receipt(
        state,
        resident_id=resident_id,
        bill=bill,
        amount=amount,
        method=method,
        channel=channel,
        day=day,
        rate=payment_terms.rate_for(state, channel),
        origin=origin,
    )
    return (
        f"{method}（{channel}）实收 ¥{amount:.2f}，机构承担手续费 ¥{allocation['feeAmount']:.2f}，"
        f"净入账 ¥{allocation['netAmount']:.2f}，转入预缴 ¥{allocation['depositAmount']:.2f}"
    )


def deposit(state, payload, today):
    resident = get_resident(state, payload)
    return manual_receipt(state, payload, today, None, resident["id"])


def pay(state, payload, today):
    bill = lookup(state, "bills", payload.get("billId"), "账单")
    return manual_receipt(state, payload, today, bill, bill["residentId"])


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
    cycle = billing_cycles.selected_period(resident, payload, today)
    resident_bills = (b for b in state["bills"] if b["residentId"] == resident["id"])
    if billing_cycles.billed(resident_bills, cycle):
        raise ValueError("该长辈本账期已有账单")
    begin, end = parse_day(cycle["startDate"]), parse_day(cycle["endDate"])
    days = (end - begin).days + 1
    parts, bed_total, care_total, leave = charge_segments(
        state, resident, payload, begin, end
    )
    last_part = parts[-1]
    package_fee = currency_amount(payload.get("packageFee", 0), "月套餐费")
    extras = payload.get("items", [])
    if not isinstance(extras, list):
        raise ValueError("请核对本期的费用明细")
    agreement = resident.get("admissionTerms", {}).get("feeItems", [])
    lines = invoice_lines(parts, package_fee, [*agreement, *extras], days, leave)
    amount = currency_amount(
        sum(Decimal(str(item["amount"])) for item in lines), "账单合计"
    )
    bill = dict(
        **cycle,
        kind="monthly",
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


def record_trial_fee(state, resident, today):
    """Post the agreed package once, within the trial admission transaction."""
    if any(
        b["residentId"] == resident["id"] and b.get("kind") == "trial"
        for b in state["bills"]
    ):
        raise ValueError("本次试住已登记一次性费用")
    price = currency_amount(resident["trialPrice"], "一次性试住费用")
    fee = float(price)
    bill = dict(
        id=new_id("bill"),
        kind="trial",
        residentId=resident["id"],
        month=resident["admittedAt"][:7],
        billingDate=resident["admittedAt"],
        date=today,
        startDate=resident["admittedAt"],
        endDate=resident["trialEndsAt"],
        trialPrice=fee,
        amount=fee,
        paid=0,
        balance=fee,
        status="待缴费" if fee else "已结清",
        lineItems=[line("trial", "一次性试住费", "次", 1, price)],
    )
    state["bills"].insert(0, bill)
    apply_deposit(state, get_account(state, resident["id"]), today)
    return bill


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
