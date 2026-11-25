"""Classify account records with the resident lifecycle visible to the directory reader."""

from . import portal
from .care.residency import TRIAL_PENDING


def stay_status(person):
    if not person:
        return "档案不在名册"
    status = person.get("status")
    if status == "在住":
        return "试住中" if person.get("stayType") == "trial" else "正式在住"
    if status in ("未入住", TRIAL_PENDING, "已退住"):
        return status
    return "档案不在名册"


def category(account, residents):
    if portal.is_customer(account):
        return {"directoryGroup": "registered"}
    if account["kind"] == "family":
        return {
            "directoryGroup": "stay",
            "directoryStay": stay_status(residents.get(account["residentId"])),
        }
    return {"directoryGroup": account["kind"]}


def by_phone(store, token, payload):
    """Resolve an exact SMS contact within the actor's manageable directory."""
    from contextlib import closing
    from . import access, identity, staff_scope

    with closing(store.connect()) as db:
        actor = store.actor(db, token)
        if not access.manages_accounts(actor):
            raise PermissionError("Account management permission required.")
        if not isinstance(payload, dict) or set(payload) != {"phone"}:
            raise ValueError("Enter a complete phone number.")
        destination = identity.destination("sms", payload["phone"])
        assignable = access._assignable(actor)
        scope = staff_scope.boundary(db, actor, store.facility_policy)
        records = db.execute(
            """SELECT a.* FROM identity_contacts c JOIN accounts a ON a.id=c.account_id
               WHERE c.channel='sms' AND c.destination=? AND c.verified>=0
               ORDER BY a.username""", (destination,))
        return {"accountIds":[r["id"] for r in records
                             if access._within_account_scope(actor, access._public(r), assignable, scope)]}
