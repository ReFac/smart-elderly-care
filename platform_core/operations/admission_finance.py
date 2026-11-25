"""Post the first service bill and keep security deposits distinct from prepaid fees."""

from datetime import date, timedelta
from decimal import Decimal

from .. import access_policy
from . import billing, billing_cycles, payment_terms
from .charges import line
from .records import currency_amount, lookup, new_id, whole_number

TERMS = {
    "depositMonths", "paymentMode", "offlinePayment", "feeItems", "reminderDays",
    "securityMode", "allocateSecurityFromPrepaid",
}


def authorize(actor, payload):
    default_months = 0 if payload.get("stayType") == "trial" else 1
    if (
        payload.get("paymentMode") == "offline"
        or payload.get("allocateSecurityFromPrepaid") is True
        or payload.get("feeItems")
        or payload.get("depositMonths", default_months) != default_months
        or payload.get("reminderDays", 3) != 3
        or payload.get("securityMode", "none") != "none"
    ):
        access_policy.require(actor, "finance")


def terms(payload, *, trial=False):
    mode = payload.get("paymentMode", "temporary")
    if mode not in ("standard", "offline", "temporary"):
        raise ValueError("请选择已缴费、人工登记已收或欠费临时入住")
    months = whole_number(payload.get("depositMonths", 0 if trial else 1), "押金月数", zero=True)
    days = whole_number(payload.get("reminderDays", 3), "提前提醒天数", zero=True)
    security = payload.get("securityMode", "none")
    if months > 3 or days > 30 or security not in ("none", "overdue"):
        raise ValueError("押金限 0–3 个月，提前提醒限 0–30 天")
    if (not months and security != "none") or (trial and (months or payload.get("feeItems"))):
        raise ValueError("请核对押金与账单费用配置，试住只登记整次试住费用")
    if mode != "offline" and "offlinePayment" in payload:
        raise ValueError("人工实收凭证须选择人工登记已收")
    allocation = payload.get("allocateSecurityFromPrepaid", False)
    if type(allocation) is not bool or (allocation and (mode != "standard" or not months)):
        raise ValueError("只可在已缴费模式下确认预缴资金转存押金")
    return dict(depositMonths=months, reminderDays=days, securityMode=security,
                feeItems=payload.get("feeItems", []))


def security_bill(resident, bill, months, today, monthly_amount):
    total = currency_amount(Decimal(str(monthly_amount)) * months, "入住押金")
    if not total:
        return None
    return dict(
        id=new_id("bill"), kind="security", residentId=resident["id"], month=bill["month"],
        date=today, billingDate=bill["billingDate"], startDate=bill["startDate"], endDate="",
        relatedBillId=bill["id"], amount=float(total), paid=0, balance=float(total), status="待缴费",
        depositMonths=months, depositUnitPrice=monthly_amount,
        lineItems=[line("security", "入住押金", "月", months, monthly_amount)],
    )


def post(state, resident, payload, today, *, preview=False):
    trial = resident.get("stayType") == "trial"
    settings = terms(payload, trial=trial)
    resident["admissionTerms"] = settings
    for collection in ("bills", "payments", "deposits", "depositEntries"):
        state.setdefault(collection, [])
    account = billing.get_account(state, resident["id"])
    initial_credit = Decimal(str(account["amount"]))
    if trial:
        bill = billing.record_trial_fee(state, resident, today)
        security = None
        next_date = ""
    else:
        first = billing_cycles.monthly_start(resident)
        bill = billing.quote_bill(state, dict(residentId=resident["id"], month=first[:7],
                                               billingDate=first), max(first, today))
        bill.update(id=new_id("bill"), date=today)
        start = date.fromisoformat(first)
        next_date = billing_cycles.next_anchor(start, resident["billingDay"]).isoformat()
        monthly_base = start if billing_cycles.anchor(start, resident["billingDay"]) == start else date.fromisoformat(next_date)
        full_period = monthly_base.isoformat()
        base = 0
        if settings["depositMonths"]:
            security_basis = {
                **state,
                "leaves": [],
                "residents": [
                    {**resident, "admissionTerms": {**settings, "feeItems": [
                        row for row in settings["feeItems"] if row["code"] != "reduction"
                    ]}} if row["id"] == resident["id"] else row
                    for row in state["residents"]
                ],
            }
            monthly = billing.quote_bill(security_basis, dict(residentId=resident["id"],
                                          month=full_period[:7], billingDate=full_period), max(full_period, today))
            base = monthly["amount"]
        state["bills"].insert(0, bill)
        security = security_bill(resident, bill, settings["depositMonths"], today, base)
        if security:
            state["bills"].insert(0, security)
        billing.apply_deposit(state, account, today)
        if security and payload.get("allocateSecurityFromPrepaid") is True:
            allocated = min(Decimal(str(account["amount"])), Decimal(str(security["balance"])))
            if allocated:
                account["amount"] = float(Decimal(str(account["amount"])) - allocated)
                billing.credit(state, security, allocated, "预缴转押金", today)
    due = [bill, *([security] if security else [])]
    total_due = sum((Decimal(str(row["balance"])) for row in due), Decimal(0))
    mode = payload.get("paymentMode", "temporary")
    if not preview:
        if mode == "standard" and total_due:
            raise ValueError("首期应收尚未结清，可登记已收或明确办理欠费临时入住")
        if mode == "offline":
            receive(state, due, payload.get("offlinePayment"), today)
        resident["admissionPayment"] = {
            "billId": bill["id"], "securityBillId": security["id"] if security else "",
            "mode": mode,
        }
    return {
        "bill": bill, "securityBill": security, "depositAmount": security["amount"] if security else 0,
        "dueAmount": float(total_due), "admittedAt": resident.get("formalizedAt") or resident["admittedAt"],
        "nextBillingDate": next_date, "prepaidAmount": float(initial_credit - Decimal(str(account["amount"]))),
    }


def receive(state, bills, payload, today):
    if not isinstance(payload, dict) or set(payload) != {"amount", "method", "channel"}:
        raise ValueError("人工登记须填写实际支付方式和实收金额")
    amount = currency_amount(payload["amount"], "实收金额", zero=False)
    method, channel = payment_terms.offline(payload)
    if channel not in ("现金", "银行转账", "银联刷卡"):
        raise ValueError("在线支付请使用已结算的商户付款凭证")
    due = sum((Decimal(str(bill["balance"])) for bill in bills), Decimal(0))
    if amount < due or not due:
        raise ValueError("实收须结清首期应付金额，部分支付请选择欠费临时入住后登记")
    receipt = new_id("cash")
    rate = payment_terms.rate_for(state, channel)
    allocated = Decimal(0)
    for bill in bills:
        portion = Decimal(str(bill["balance"]))
        if portion:
            row = billing.credit(state, bill, portion, method, today)
            allocated += portion
            exact_fee = payment_terms.fee(allocated, rate) - payment_terms.fee(allocated - portion, rate)
            row.update(receiptId=receipt, channel=channel, grossAmount=float(amount),
                       originBillId=bill["id"], **payment_terms.accounting(portion, exact_fee, rate))
    surplus = amount - allocated
    if surplus:
        account = billing.get_account(state, bills[0]["residentId"])
        account["amount"] = float(Decimal(str(account["amount"])) + surplus)
        extra_fee = payment_terms.fee(amount, rate) - payment_terms.fee(allocated, rate)
        state["depositEntries"].insert(0, dict(
            id=new_id("receipt"), residentId=account["residentId"], date=today,
            amount=float(surplus), method=method, channel=channel, receiptId=receipt,
            grossAmount=float(amount), originBillId=bills[0]["id"],
            **payment_terms.accounting(surplus, extra_fee, rate),
        ))
        billing.apply_deposit(state, account, today)


def use_security(state, resident, bill, today):
    if (resident.get("admissionTerms", {}).get("securityMode") != "overdue"
        or bill.get("kind") != "monthly" or not bill.get("billingDate")
        or bill["billingDate"] >= today or not bill["balance"]):
        return None
    deposit_id = resident.get("admissionPayment", {}).get("securityBillId")
    if not deposit_id:
        return None
    deposit = lookup(state, "bills", deposit_id, "押金凭证")
    if deposit.get("kind") != "security" or deposit["residentId"] != resident["id"]:
        raise ValueError("押金凭证与长辈不匹配")
    remaining = Decimal(str(deposit["paid"])) - Decimal(str(deposit.get("refundedSecurity", 0))) - sum(
        (Decimal(str(row["amount"])) for row in state["payments"] if row.get("securityBillId") == deposit_id),
        Decimal(0),
    )
    amount = min(remaining, Decimal(str(bill["balance"])))
    if amount <= 0:
        return None
    credit = billing.credit(state, bill, amount, "押金冲抵", today)
    credit["securityBillId"] = deposit_id
    return credit


def admission_date(payload, today, earliest=None):
    value = payload.get("admittedAt") or today
    try:
        normalized = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("请选择有效的入住日期") from None
    if value != normalized.isoformat() or value > today or (earliest and value < earliest):
        raise ValueError("入住日期应在有效入住范围内且不能晚于今天")
    return value


def reminder_dates(resident, today):
    first = billing_cycles.monthly_start(resident)
    if not first or "admissionTerms" not in resident or resident["status"] != "在住":
        return []
    now = date.fromisoformat(today)
    start = date.fromisoformat(first)
    if start >= now:
        due = start
    elif billing_cycles.anchor(now, resident["billingDay"]) == now:
        due = now
    else:
        due = billing_cycles.next_anchor(now, resident["billingDay"])
    result = []
    if due == now:
        result.append((today, "due"))
        due = billing_cycles.next_anchor(now, resident["billingDay"])
    lead = resident["admissionTerms"]["reminderDays"]
    if lead and due - timedelta(days=lead) <= now < due:
        result.append((due.isoformat(), "advance"))
    return result


def project_status(state, data):
    by_id = {row["id"]: row for row in state["bills"]}
    files = {row["id"]: row.get("admissionPayment") for row in state["residents"]}
    residents = []
    for resident in data["residents"]:
        payment = files.get(resident["id"])
        if payment and resident.get("status") == "在住":
            bills = [by_id[key] for key in (payment["billId"], payment["securityBillId"]) if key in by_id]
            if bills:
                unpaid = any(bill["balance"] for bill in bills)
                status = "欠费临时入住" if unpaid else "已结清"
                resident = {**resident, "admissionStatus": status}
        residents.append(resident)
    data["residents"] = residents


def configure(state, payload):
    if set(payload) != {"residentId", "reminderDays", "securityMode"}:
        raise ValueError("请选择长辈及账单提醒设置")
    resident = lookup(state, "residents", payload["residentId"], "长辈档案")
    settings = resident.get("admissionTerms")
    if not settings or resident["status"] != "在住" or resident.get("stayType") != "formal":
        raise ValueError("此设置仅用于已登记入住收费约定的在住长辈")
    changed = terms({"depositMonths": settings["depositMonths"], "reminderDays": payload["reminderDays"],
                     "securityMode": payload["securityMode"]})
    for key in ("reminderDays", "securityMode"):
        settings[key] = changed[key]
    return "已更新本长辈的账单提醒与押金抵扣规则"
