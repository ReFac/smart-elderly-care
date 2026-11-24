"""Retain the working archive for 365 days; preserve evidentiary originals and ledger references."""

from contextlib import closing
from datetime import date, timedelta
import json

from .records import lookup

ARCHIVED = "已退住"
EXPIRED = "归档到期"


def expiry(person):
    if person.get("status") != ARCHIVED or not person.get("dischargedAt"):
        return ""
    try:
        return (
            date.fromisoformat(person["dischargedAt"]) + timedelta(days=365)
        ).isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""  # Preserve an undated legacy archive until its date is established.


def writable(state, resident_id):
    person = lookup(state, "residents", resident_id)
    if person["status"] in (ARCHIVED, EXPIRED):
        raise ValueError("归档老人档案只读。")
    return person


def require_ai_eligible(state, resident_id):
    if lookup(state, "residents", resident_id)["status"] != "在住":
        raise ValueError("仅在住长者可使用档案 AI 处理。")


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS archive_expirations(
        resident TEXT PRIMARY KEY, expired_on TEXT NOT NULL)""")


def clear_due(db, state, day, resident_id=None):
    """Clear only mutable profile data. The caller commits its own audit and workspace version."""
    expired = [
        r
        for r in state["residents"]
        if (not resident_id or r["id"] == resident_id)
        and (expires := expiry(r))
        and expires <= day
    ]
    for r in expired:
        rid = r["id"]
        db.execute(
            "INSERT OR IGNORE INTO archive_expirations VALUES (?,?)",
            (rid, expiry(r)),
        )
        db.execute("DELETE FROM dossier_profiles WHERE resident_id=?", (rid,))
        db.execute("DELETE FROM dossier_relatives WHERE resident_id=?", (rid,))
        db.execute(
            "UPDATE family_round_preferences SET allowed=0,subscribed=0,generation=generation+1 WHERE resident_id=? AND (allowed=1 OR subscribed=1)",
            (rid,),
        )
        for q in state["inquiries"]:
            if q.get("residentId") == rid or q["id"] == r.get("inquiryId"):
                q.update(name="已到期档案", contact="", note="")
        for task in state.get("trialFollowups", ()):
            if task["residentId"] == rid:
                task.pop("report", None)
                task.pop("reason", None)
                task["status"] = "归档到期"
        # Settlements, clinical originals and audit commits still refer to this ID.
        # Remove names, contact fields and all unrecognised mutable profile fields.
        historical = {
            k: r[k]
            for k in (
                "id",
                "admittedAt",
                "dischargedAt",
                "endDate",
                "level",
                "billingDay",
                "formalizedAt",
                "trialEndsAt",
                "stayType",
            )
            if k in r
        }
        r.clear()
        r.update(historical, name="已到期档案", bedId="", status=EXPIRED)
    return [r["id"] for r in expired]


def maintain(store):
    now = store.now()
    day = now.date().isoformat()
    if getattr(store, "_archive_checked", None) == day:
        return
    from .. import activity

    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        revision, raw = db.execute(
            "SELECT revision,data FROM workspace WHERE id=1"
        ).fetchone()
        state = json.loads(raw)
        expired = clear_due(db, state, day)
        for rid in expired:
            revision += 1
            activity.write(
                db,
                revision,
                now.isoformat(),
                "archive.expire",
                "归档满 365 天，清理日常档案资料",
                {
                    "id": "archive-service",
                    "displayName": "档案保管服务",
                    "username": "archive-service",
                },
                {"residentId": rid},
                {},
            )
        if expired:
            db.execute(
                "UPDATE workspace SET revision=?,data=? WHERE id=1",
                (
                    revision,
                    json.dumps(state, ensure_ascii=False, separators=(",", ":")),
                ),
            )
    store._archive_checked = day


def after_restore(db, now):
    # The staged migration may have expired a resident the live institution has never seen.
    db.execute("""INSERT OR IGNORE INTO archive_expirations
        SELECT resident,expired_on FROM incoming.archive_expirations""")
    state = json.loads(
        db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
    )
    if clear_due(db, state, now.date().isoformat()):
        db.execute(
            "UPDATE workspace SET data=? WHERE id=1",
            (json.dumps(state, ensure_ascii=False, separators=(",", ":")),),
        )
