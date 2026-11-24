"""Resolve display-only room numbers and positions from records visible to this reader."""

import json

STAFF_FIELDS = (
    ("actorId", "actorName"),
    ("operatorId", "operator"),
    ("assigneeId", "assignee"),
    ("senderId", "senderName"),
    ("assignedBy", "assignedByName"),
    ("reportedBy", "reportedByName"),
    ("reviewerId", "reviewer"),
    ("", "staff"),
    ("", "signedByName"),
    ("", "recordedBy"),
    ("", "requester"),
    ("", "publisherName"),
)


def recipient_positions(db, result):
    ids = [row["id"] for row in result["recipients"]]
    result["positions"] = {
        key: (
            role if role != "自定义" else "、".join(json.loads(duties)) or "岗位未登记"
        )
        for key, role, duties in db.execute(
            "SELECT id,role,staff_duties FROM accounts WHERE id IN (SELECT value FROM json_each(?))",
            (json.dumps(ids),),
        )
    }
    return result


def project(db, state, data, user, logs):
    visible = {p["id"] for p in data.get("residents", ())}
    if user["kind"] == "family" and not (
        user.get("portalSelf") or user.get("familyServices") or user.get("portalScopes")
    ):
        visible.clear()
    beds = {r["id"]: r.get("bedId") for r in state["residents"] if r["id"] in visible}
    numbers = dict(
        db.execute(
            "SELECT b.bedId,r.number FROM facility_beds b JOIN facility_rooms r ON r.id=b.roomId"
        )
    )
    data["residentRooms"] = {
        rid: numbers.get(bid, "") for rid, bid in beds.items() if bid
    }
    if user["kind"] == "family":
        return
    ids, names = {user["id"]}, set()
    for doc in data.get("medicalDocuments", ()):
        review = doc.get("summary") or {}
        if review.get("reviewerId"):
            ids.add(review["reviewerId"])
    # Consult only names and identifiers already present in this actor's business projection.
    for rows in (logs, *(v for v in data.values() if isinstance(v, list))):
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key, label in STAFF_FIELDS:
                if isinstance(row.get(key), str) and row[key]:
                    ids.add(row[key])
                if isinstance(row.get(label), str) and row[label]:
                    names.add(row[label])
    matches = db.execute(
        """SELECT id,display_name,role,staff_duties,campus_id FROM accounts WHERE kind IN ('staff','owner')
           AND (id IN (SELECT value FROM json_each(?)) OR display_name IN (SELECT value FROM json_each(?)))""",
        (json.dumps(sorted(ids)), json.dumps(sorted(names))),
    )
    scope = user.get("facilityScope") or {}
    campuses = scope.get("campusIds")
    roles, by_name = {}, {}
    for aid, name, role, duties, campus in matches:
        position = (
            role if role != "自定义" else "、".join(json.loads(duties)) or "岗位未登记"
        )
        if aid in ids:
            roles[aid] = position
        if name in names:
            # A free-text historical name can be shared by employees from different branches.
            allowed = aid in ids or (
                not any(k in scope for k in ("buildingIds", "floorIds", "roomIds"))
                and (campuses is None or campus in campuses)
            )
            by_name.setdefault(name, set()).add(position if allowed else "")
    data["staffPositions"] = {
        "ids": roles,
        "names": {
            n: next(iter(r)) for n, r in by_name.items() if len(r) == 1 and "" not in r
        },
    }
