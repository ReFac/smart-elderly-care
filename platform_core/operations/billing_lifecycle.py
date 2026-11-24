"""Record scheduled billing reminders and allocate eligible security deposits."""

from collections import defaultdict
from contextlib import closing
from hashlib import sha256
import json
from zoneinfo import ZoneInfo

from .. import access_policy
from . import admission_finance
from .records import parse_day

LOCAL = ZoneInfo("Asia/Shanghai")
ACTION = "ops.billingLifecycle"
SERVICE = {
    "id": "billing-lifecycle",
    "displayName": "账单定时服务",
    "username": "billing-lifecycle",
    "role": "系统",
}
NOTICES = {
    "advance": ("月费缴费提醒", "请在本期约定账单日核对账单并办理缴费。"),
    "due": ("月费账单日", "本期已到约定账单日，请核对缴费情况。"),
    "security": (
        "已办理押金冲抵",
        "本期月费已使用押金冲抵，请联系机构核对本期账单及押金余额。",
    ),
    "securityIssue": (
        "押金凭证待核对",
        "未能验证本长者的押金凭证，请核对入住收费凭证。",
    ),
}
FAMILY_FIELDS = ("id", "billingDate", "date", "kind", "title", "message")
FINANCE_FIELDS = (*FAMILY_FIELDS, "residentId", "billId", "amount")


def _active(resident):
    return (
        resident.get("status") == "在住"
        and resident.get("stayType") != "trial"
        and resident.get("admissionTerms")
    )


def _notice(
    state, recorded, resident_id, billing_date, today, kind, bill=None, amount=None
):
    key = (resident_id, billing_date, kind)
    if key in recorded:
        return 0
    recorded.add(key)
    digest = sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()[:24]
    title, message = NOTICES[kind]
    row = {
        "id": "billing-" + digest,
        "residentId": resident_id,
        "billingDate": billing_date,
        "date": today,
        "kind": kind,
        "title": title,
        "message": message,
    }
    if bill:
        row["billId"] = bill["id"]
    if amount is not None:
        row["amount"] = amount
    state.setdefault("billingNotices", []).append(row)
    return 1


def _monthly_bills(state, residents, today):
    by_person = defaultdict(list)
    for bill in state["bills"]:
        rid = bill.get("residentId")
        day = bill.get("billingDate")
        if rid not in residents or bill.get("kind") != "monthly" or not day:
            continue
        try:
            parse_day(day)
        except ValueError:
            # A legacy invoice with no verified calendar date can still be paid manually.
            continue
        if day <= today:
            by_person[rid].append(bill)
    for rows in by_person.values():
        rows.sort(key=lambda bill: (bill["billingDate"], bill["id"]))
    return by_person


def _process(state, recorded, resident, bills, today):
    rid = resident["id"]
    by_date = {bill["billingDate"]: bill for bill in bills}
    reminders = set(admission_finance.reminder_dates(resident, today))
    # Catch up after downtime, including the day an overdue invoice is first entered.
    reminders.update(
        (bill["billingDate"], "due")
        for bill in bills
        if bill["balance"] > 0 or bill["billingDate"] == today
    )
    count = sum(
        _notice(state, recorded, rid, day, today, kind, by_date.get(day))
        for day, kind in sorted(reminders)
    )
    allocations = 0
    for bill in bills:
        day = bill["billingDate"]
        try:
            credit = admission_finance.use_security(state, resident, bill, today)
        except ValueError:
            count += _notice(state, recorded, rid, day, today, "securityIssue", bill)
        else:
            if credit:
                allocations += 1
                count += _notice(
                    state, recorded, rid, day, today, "security", bill, credit["amount"]
                )
    return count, allocations


def tick(store):
    from .. import activity, history
    from ..store import encode

    day = store.now().astimezone(LOCAL).date().isoformat()
    writes = 0
    with closing(store.connect()) as db, db:
        revision = db.execute("SELECT revision FROM workspace WHERE id=1").fetchone()[0]
        if getattr(store, "_billing_lifecycle_checked", None) == (day, revision):
            return 0
        db.execute("BEGIN IMMEDIATE")
        now = store.now().astimezone(LOCAL)
        day = now.date().isoformat()
        row = db.execute("SELECT revision,data FROM workspace WHERE id=1").fetchone()
        revision, state = row["revision"], json.loads(row["data"])
        recorded = {
            (row["residentId"], row["billingDate"], row["kind"])
            for row in state.get("billingNotices", ())
        }
        residents = {r["id"]: r for r in state["residents"] if _active(r)}
        monthly_bills = _monthly_bills(state, residents, day)
        for rid, resident in residents.items():
            count, allocations = _process(
                state, recorded, resident, monthly_bills[rid], day
            )
            if not count and not allocations:
                continue
            history.watch(db, ACTION)
            revision += 1
            db.execute(
                "UPDATE workspace SET revision=?,data=? WHERE id=1",
                (revision, encode(state)),
            )
            activity.write(
                db,
                revision,
                now.isoformat(timespec="seconds"),
                ACTION,
                f"生成 {count} 条账单提醒，登记 {allocations} 笔押金冲抵",
                SERVICE,
                {"residentId": rid, "bedId": resident.get("bedId")},
                {},
            )
            writes += count + allocations
    store._billing_lifecycle_checked = (day, revision)
    return writes


def project(state, data, user, today):
    """Attach an authorized view of notifications to the current workspace snapshot."""
    data["billingNotices"] = []
    family = user.get("kind") == "family"
    if family:
        rid = user.get("residentId")
        if (
            "billingNotices" not in user.get("portalScopes", ())
            or not rid
            or not any(r["id"] == rid and _active(r) for r in state["residents"])
        ):
            return
        visible = {rid}
        fields = FAMILY_FIELDS
    elif access_policy.has(user, "finance"):
        visible = {r["id"] for r in data.get("residents", ())}
        fields = FINANCE_FIELDS
    else:
        return
    rows = [
        access_policy.select_fields(row, fields)
        for row in state.get("billingNotices", ())
        if row["residentId"] in visible
        and row["date"] <= today
        and (not family or row["kind"] != "securityIssue")
    ]
    if not family:
        bills = {
            (bill["residentId"], bill["billingDate"]): bill["id"]
            for bill in data.get("bills", ())
            if bill.get("kind") == "monthly" and bill.get("billingDate")
        }
        for row in rows:
            billed = bills.get((row["residentId"], row["billingDate"]))
            if billed and not row.get("billId"):
                row["billId"] = billed
    data["billingNotices"] = sorted(
        rows, key=lambda row: (row["date"], row["billingDate"], row["id"]), reverse=True
    )
