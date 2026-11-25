"""Retain the working archive for 365 days; preserve evidentiary originals and ledger references."""

from contextlib import closing
from datetime import date, timedelta
import json
import os

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
        raise ValueError("仅在住长辈可使用档案 AI 处理。")


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS archive_expirations(
        resident TEXT PRIMARY KEY, expired_on TEXT NOT NULL)""")


def init_profile(db):
    setting = os.environ.get("NH_INSTITUTION_PROFILE", "residential")
    if setting not in ("residential", "licensed-medical"):
        raise ValueError("NH_INSTITUTION_PROFILE 应为 residential 或 licensed-medical")
    db.execute("""CREATE TABLE IF NOT EXISTS clinical_archive_policy(
        id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT NOT NULL CHECK(mode='licensed-medical'))""")
    db.execute("""CREATE TABLE IF NOT EXISTS clinical_archive_reviews(
        resident TEXT PRIMARY KEY, due_on TEXT NOT NULL)""")
    if setting == "licensed-medical":
        installation = db.execute("SELECT mode FROM workspace_installation WHERE id=1").fetchone()
        if not installation or installation[0] != "empty":
            raise ValueError("医疗机构部署须使用已核实的正式机构库，不能使用演示库")
        db.execute("INSERT OR IGNORE INTO clinical_archive_policy VALUES(1,'licensed-medical')")
    return db.execute("SELECT 1 FROM clinical_archive_policy WHERE id=1").fetchone() is not None


def clinical_hold(db):
    return bool(db.execute("SELECT 1 FROM clinical_archive_policy WHERE id=1").fetchone())


def formal_institution(db):
    row = db.execute("SELECT mode FROM workspace_installation WHERE id=1").fetchone()
    # Historical installations may predate the mode marker. Only a verified demo
    # may discard the mutable profile after a year.
    return row is None or row[0] != "demo"


def clear_due(db, state, day, resident_id=None):
    """Clear only mutable profile data. The caller commits its own audit and workspace version."""
    expired = [
        r
        for r in state["residents"]
        if (not resident_id or r["id"] == resident_id)
        and (expires := expiry(r))
        and expires <= day
    ]
    if expired and (formal_institution(db) or clinical_hold(db)):
        # A discharge from the care home is not a clinical encounter/discharge date.
        # Preserve the identity linkage until the records officer classifies the records.
        for r in expired:
            db.execute("INSERT OR IGNORE INTO clinical_archive_reviews VALUES (?,?)", (r["id"], expiry(r)))
            db.execute("""UPDATE family_round_preferences SET allowed=0,subscribed=0,generation=generation+1
                    WHERE resident_id=? AND (allowed=1 OR subscribed=1)""", (r["id"],))
        return []
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
    if store._archive_checked == store.now().date().isoformat():
        return
    with store._daily_maintenance_lock:
        now = store.now()
        day = now.date().isoformat()
        if store._archive_checked != day:
            _maintain(store, now, day)
            store._archive_checked = day


def _maintain(store, now, day):
    from .. import activity, lead_directory

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
        closed = lead_directory.expire(state, day)
        if closed:
            revision += 1
            activity.write(db, revision, now.isoformat(), "leads.expire", f"{closed} 条意向客户归档满 365 天",
                           {"id":"archive-service", "displayName":"档案保管服务", "username":"archive-service"}, {}, {})
        if expired or closed:
            db.execute(
                "UPDATE workspace SET revision=?,data=? WHERE id=1",
                (
                    revision,
                    json.dumps(state, ensure_ascii=False, separators=(",", ":")),
                ),
            )


def after_restore(db, now):
    # The staged migration may have expired a resident the live institution has never seen.
    db.execute("""INSERT OR IGNORE INTO archive_expirations
        SELECT resident,expired_on FROM incoming.archive_expirations""")
    state = json.loads(
        db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
    )
    from . import trial_expiry

    day = now.date().isoformat()
    overdue = trial_expiry.due(state, day)
    for person in overdue:
        trial_expiry.release(state, person)
    from .. import lead_directory
    expired_leads = lead_directory.expire(state, day)
    if clear_due(db, state, day) or overdue or expired_leads:
        db.execute(
            "UPDATE workspace SET data=? WHERE id=1",
            (json.dumps(state, ensure_ascii=False, separators=(",", ":")),),
        )
