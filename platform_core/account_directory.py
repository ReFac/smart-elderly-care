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
