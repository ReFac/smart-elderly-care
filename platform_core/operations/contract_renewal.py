"""Extend paid renewal periods and derive contract reminders from settled records."""

from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from .billing_cycles import monthly_start
from .records import new_id
from ..access_policy import has, select_fields

RENEWAL_TENDER = {"线下登记", "线下刷卡登记", "微信支付", "支付宝", "预交金冲抵"}


def has_security(person):
    months = person.get("admissionTerms", {}).get("depositMonths")
    if type(months) is int:
        return months > 0
    return bool(person.get("admissionPayment", {}).get("securityBillId"))


def record(state, person, end_date, today, *, source, bill=None, payment=None):
    previous = person.get("endDate", "")
    entry = dict(
        id=new_id("renewal"), residentId=person["id"], previousEndDate=previous,
        endDate=end_date, date=today, source=source,
    )
    if bill:
        entry.update(billId=bill["id"], paymentId=payment["id"])
        bill["contractRenewal"] = select_fields(entry, ("previousEndDate", "endDate", "date"))
    else:
        person.pop("contractRenewalAnchorDay", None)
    person["endDate"] = end_date
    state.setdefault("contractRenewals", []).insert(0, entry)


def after_credit(state, bill, payment, today):
    if (payment["method"] not in RENEWAL_TENDER or bill.get("kind") != "monthly"
        or bill["balance"] or not bill.get("amount") or bill.get("contractRenewal")):
        return
    person = next((r for r in state["residents"] if r["id"] == bill["residentId"]), None)
    if not person or person["status"] != "在住" or person.get("stayType") == "trial":
        return
    current, start, end = person.get("endDate"), bill.get("startDate"), bill.get("endDate")
    if not (current and start and end and end > current):
        return
    if start == monthly_start(person) or bill["id"] == person.get("admissionPayment", {}).get("billId"):
        return
    # A security withdrawal creates a review reminder, even when other tender clears the bill.
    paid = sum((Decimal(str(row["amount"])) for row in state["payments"]
                if row.get("billId") == bill["id"] and row.get("method") in RENEWAL_TENDER), Decimal(0))
    if paid < Decimal(str(bill["amount"])):
        return
    try:
        expiry = date.fromisoformat(current)
        cycle_start = date.fromisoformat(start)
    except (TypeError, ValueError):
        return
    if cycle_start - timedelta(days=1) > expiry:
        return
    anchor = person.get("contractRenewalAnchorDay", expiry.day)
    year, month = expiry.year + (expiry.month == 12), expiry.month % 12 + 1
    changed = date(year, month, min(anchor, monthrange(year, month)[1]))
    person["contractRenewalAnchorDay"] = anchor
    record(state, person, changed.isoformat(), today, source="payment", bill=bill, payment=payment)


def reminder_for(person, today, security_date=None):
    if person.get("status") != "在住" or person.get("stayType") == "trial":
        return None
    end = person.get("endDate")
    if end and end <= today:
        return {"reason": "expired", "at": end}
    if has_security(person):
        return {"reason": "securityUsed", "at": security_date} if security_date else None
    if end and end <= (date.fromisoformat(today) + timedelta(days=30)).isoformat():
        return {"reason": "upcoming", "at": end}
    return None


def security_used_today(state, today):
    return {
        row["residentId"]: row["date"]
        for row in state.get("payments", ())
        if row.get("date") == today and row.get("method") == "押金冲抵" and row.get("securityBillId")
    }


def project(state, data, user, today):
    finance = has(user, "finance")
    if not (finance or has(user, "intake")):
        return
    fields = ("id", "previousEndDate", "endDate", "date", "source", *(("billId",) if finance else ()))
    people = {r["id"]: r for r in state["residents"]}
    eligible = {r["id"] for r in data["residents"]}
    history = defaultdict(list)
    for entry in state.get("contractRenewals", ()):
        if entry["residentId"] in eligible:
            history[entry["residentId"]].append(select_fields(entry, fields))
    used = security_used_today(state, today)
    data["residents"] = [
        {**row, "renewalHistory": history[row["id"]],
         "renewalReminder": reminder_for(people[row["id"]], today, used.get(row["id"]))}
        for row in data["residents"]
    ]
    data.pop("contractRenewals", None)
