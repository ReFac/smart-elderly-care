"""Match reception numbers to contacts in the reception site's own directory."""

from collections import defaultdict
import hashlib
import hmac
import json
import secrets
import unicodedata

from . import facility
from .profile_fields import phone_number


def links(db, state, phones):
    from .lead_contacts import PHONE_TEXT, SELF_LABEL

    result = defaultdict(set)
    beds = {b["id"]: b.get("label", "") for b in state["beds"]}
    branches = dict(
        db.execute(
            "SELECT fb.bedId,b.campusId FROM "
            + facility.ROOM_TABLE
            + " JOIN facility_beds fb ON fb.roomId=r.id"
        )
    )
    people = {r["id"]: r for r in state["residents"] if r.get("status") != "归档到期"}

    def add(number, rid, relation, contact=""):
        phone, person = phone_number(number), people.get(rid)
        if phone not in phones or not person:
            return
        bed = person.get("bedId")
        campus = (
            branches.get(bed)
            or person.get("registeredCampusId")
            or facility.HOME_CAMPUS
        )
        result[campus, phone].add(
            (rid, person.get("name", ""), beds.get(bed, ""), relation, contact)
        )

    for p in people.values():
        legacy = unicodedata.normalize("NFKC", p.get("contact") or "")
        for match in PHONE_TEXT.finditer(legacy):
            add(
                match[0],
                p["id"],
                "本人" if SELF_LABEL.search(legacy[: match.start()]) else "登记联系人",
            )
    for rid, basic, household in db.execute(
        "SELECT resident_id,basic,household FROM dossier_profiles"
    ):
        add(json.loads(basic).get("phone"), rid, "本人")
        for member in json.loads(household).get("familyMembers", ()):
            add(
                member.get("phone"),
                rid,
                member.get("relationship") or member.get("kind") or "家属",
                member.get("name", ""),
            )
    for rid, details in db.execute("SELECT resident_id,details FROM dossier_relatives"):
        contact = json.loads(details)
        add(
            contact.get("phone"),
            rid,
            contact.get("relationship") or "家属",
            contact.get("name", ""),
        )
    for kind, role, rid, name, username, campus, destination in db.execute(
        """SELECT a.kind,a.role,a.resident_id,a.display_name,a.username,a.campus_id,c.destination
           FROM accounts a LEFT JOIN identity_contacts c ON c.account_id=a.id AND c.channel='sms' AND c.verified>=0"""
    ):
        for number in (username, destination):
            phone = phone_number(number)
            if phone not in phones:
                continue
            if kind == "family":
                add(
                    number,
                    rid,
                    "本人" if role == "入住长者" else "家属",
                    "" if role == "入住长者" else name,
                )
            elif kind in ("staff", "owner"):
                result[campus or facility.HOME_CAMPUS, phone].add(
                    ("", "", "", role, name)
                )
    return {
        k: [
            dict(residentId=r, residentName=n, bed=b, relation=t, contact=c)
            for r, n, b, t, c in sorted(v)
        ]
        for k, v in result.items()
    }


def matches_phone(row, phone):
    if "phone" in row:
        return row["phone"] == phone
    if not row.get("archiveSalt"):
        return False
    candidate = hashlib.sha256((row["archiveSalt"] + phone).encode()).hexdigest()
    return hmac.compare_digest(candidate, row["archivePhoneDigest"])


def expire(state, day):
    """Keep only a contact-suppression marker when a closed case ages out."""
    from datetime import date, timedelta

    cutoff = (date.fromisoformat(day) - timedelta(days=365)).isoformat()
    due = {
        r["id"]
        for r in state.get("leadContacts", ())
        if r["status"] == "已归档"
        and "0001" < str(r.get("archivedAt") or "")[:10] <= cutoff
    }
    if not due:
        return 0
    for row in state["leadContacts"]:
        if row["id"] in due:
            marker = {k: row[k] for k in ("id", "campusId", "callbackStopped")}
            salt = secrets.token_hex(24)
            marker["archiveSalt"] = salt
            marker["archivePhoneDigest"] = hashlib.sha256((salt + row["phone"]).encode()).hexdigest()
            row.clear()
            row.update(marker, status="归档到期")
    for key in ("leadEvents", "visitBookings"):
        state[key] = [r for r in state.get(key, ()) if r["leadId"] not in due]
    return len(due)
