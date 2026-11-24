"""Keep the room at the time of the action, including both rooms for transfers."""

import json

from . import access, campus_access, history


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS audit (
        revision INTEGER PRIMARY KEY, at TEXT NOT NULL, action TEXT NOT NULL, summary TEXT NOT NULL
    )""")
    existing = {row[1] for row in db.execute("PRAGMA table_info(audit)")}
    for name in (
        "actorId",
        "actorName",
        "actorPosition",
        "actorLogin",
        "residentId",
        "room",
        "previousRoom",
        "agentRunId",
    ):
        if name not in existing:
            db.execute(f"ALTER TABLE audit ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
    db.execute("CREATE INDEX IF NOT EXISTS audit_actor ON audit(actorId,revision)")
    db.execute("CREATE INDEX IF NOT EXISTS audit_room ON audit(room,revision)")
    history.init(db)


# Resolve audit context from the actual business target, never from unrelated form fields.
RELATED = {
    "care.reassignTrialFollowup": ("taskId", "trialFollowups"),
    "care.finishTrialFollowup": ("taskId", "trialFollowups"),
    "care.approvePlan": ("planId", "plans"),
    "care.completeTask": ("taskId", "tasks"),
    "care.quality": ("taskId", "tasks"),
    "portal.feedback": ("taskId", "tasks"),
    "care.giveMedication": ("medicationId", "medications"),
    "care.reviewMedication": ("medicationId", "medications"),
    "care.resolveVital": ("vitalId", "vitals"),
    "care.acceptHandover": ("handoverId", "handovers"),
    "care.withdrawHandover": ("handoverId", "handovers"),
    "ops.pay": ("billId", "bills"),
    "ops.importReceipt": ("billId", "bills"),
    "ops.remindBill": ("billId", "bills"),
    "ops.paymentOrder": ("billId", "bills"),
    "care.scheduleFollowup": ("followupId", "followups"),
    "care.finishFollowup": ("followupId", "followups"),
    "care.receiveReferral": ("referralId", "referrals"),
    "care.referralConsent": ("referralId", "referrals"),
    "care.exportReferral": ("referralId", "referrals"),
    "ops.review": ("id", "suggestions"),
}
PERSON_ACTIONS = {
    "care.confirmMedRound",
    "care.healthNote",
    "dossier.signHealthIntro",
    "care.fileArchive",
    "care.dateArchive",
    "ltci.record",
    "care.admit",
    "care.confirmStay",
    "care.endTrial",
    "care.transfer",
    "care.renew",
    "care.discharge",
    "care.leave",
    "care.assess",
    "care.addTask",
    "care.handover",
    "care.addMedication",
    "care.vital",
    "care.archive",
    "ops.bill",
    "ops.deposit",
    "ops.residentBillingPolicy",
    "dossier.document",
    "care.screen",
    "care.refer",
    "dossier.ocr",
    "dossier.reviewDocument",
    "dossier.confirmVisit",
    "dossier.signSummary",
    "dossier.profile",
    "family.consent",
    "family.subscribe",
    "family.read",
}


def for_person(data, resident_id):
    person = next((r for r in data["residents"] if r["id"] == resident_id), {})
    bed = next((b for b in data["beds"] if b["id"] == person.get("bedId")), {})
    room = f"{bed['ward']} / {bed['label'].rsplit('-', 1)[0]}" if bed else ""
    return {"residentId": person.get("id", ""), "room": room}


def locate(db, data, action, payload, actor):
    if action in ("facility.updateRoom", "facility.setLayout"):
        from .facility import floor, room

        if action == "facility.updateRoom":
            place = room(db, data, actor, payload.get("roomId"))
            label = " / ".join((place["campusName"], place["buildingName"], place["floorLabel"], place["number"]))
            return {"room": label, "roomId": place["id"], "campusId": place["campusId"]}
        place = floor(db, data, actor, payload.get("floorId"))
        label = " / ".join((place["campusName"], place["buildingName"], place["label"]))
        return {"room": label, "roomIds": [r["id"] for r in place["rooms"]], "campusId": place["campusId"]}
    if action.startswith("care.area") and isinstance(payload.get("buildingId"), str):
        building = db.execute(
            "SELECT name,campusId FROM facility_building_directory WHERE id=?", (payload["buildingId"],)
        ).fetchone()
        return {"room": building["name"], "campusId": building["campusId"]} if building else {}
    if action == "care.confirmScheduledMeal":
        selected = payload.get("entries")
        if isinstance(selected, list):
            ids = {
                row["taskId"] for row in selected
                if isinstance(row, dict) and isinstance(row.get("taskId"), str)
            }
            tasks = [task for task in data["tasks"] if task["id"] in ids]
            people = sorted({task["residentId"] for task in tasks})
            rooms = sorted({task["scheduledRoomId"] for task in tasks if task.get("scheduledRoomId")})
            campuses = sorted({task["scheduledCampusId"] for task in tasks if task.get("scheduledCampusId")})
            result = {"residentIds": people, "roomIds": rooms, "campusIds": campuses}
            if len(people) == 1:
                result.update(for_person(data, people[0]))
            return result
    if action == "care.timelineSettings":
        if payload.get("residentId"):
            return for_person(data, payload["residentId"])
        if isinstance(payload.get("roomId"), str) and payload["roomId"]:
            from .facility import room

            place = room(db, data, actor, payload["roomId"])
            return {
                "room": " / ".join(
                    (
                        place["campusName"],
                        place["buildingName"],
                        place["floorLabel"],
                        place["number"],
                    )
                )
            }
    if action in RELATED:
        key, collection = RELATED[action]
        target = next((r for r in data.get(collection, ()) if r["id"] == payload.get(key)), {})
        return for_person(data, target.get("residentId"))
    if action in PERSON_ACTIONS or (
        action == "ops.suggest" and payload.get("category") == "日常照护"
    ):
        return for_person(data, payload.get("residentId"))
    if action == "dossier.relative":
        account = (
            actor
            if actor["kind"] == "family"
            else access.account(db, payload.get("accountId", ""))
        )
        return for_person(data, account["residentId"]) if account else {}
    return {}


def write(
    db,
    revision,
    timestamp,
    action,
    summary,
    actor,
    current,
    previous,
    *,
    comment="",
    undo_of=None,
):
    position = actor.get("role", "")
    if position == "自定义":
        position = "、".join(actor.get("staffDuties", []))
    db.execute(
        """INSERT INTO audit(revision,at,action,summary,actorId,actorName,actorLogin,residentId,room,previousRoom,agentRunId,actorPosition)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            revision,
            timestamp,
            action,
            summary,
            actor["id"],
            actor["displayName"],
            actor["username"],
            current.get("residentId") or previous.get("residentId") or "",
            current.get("room") or previous.get("room") or "",
            previous.get("room") or "",
            current.get("agentRunId", ""),
            position,
        ),
    )
    return history.record(
        db, revision, timestamp, action, actor, current, previous, comment, undo_of
    )


def page(db, user, room="", actor="", before=None, limit=50):
    access.require(user, "audit")
    filters, params = [], []
    for value in (room, actor):
        if not isinstance(value, str) or len(value) > 150:
            raise ValueError("筛选值过长")
    if campus_access.bound(user):
        state = json.loads(
            db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
        )
        permitted = campus_access.resident_ids(
            state, campus_access.allowed_beds(db, user), user
        )
        clause = "a.residentId IN (SELECT value FROM json_each(?)) OR a.action LIKE 'agent.%'"
        params.append(json.dumps(sorted(permitted)))
        campuses = campus_access.registration_campuses(user)
        if campuses and access.has(user, "intake"):
            clause += """ OR (a.action LIKE 'leads.%' AND EXISTS (
                SELECT 1 FROM history_targets t WHERE t.revision=a.revision AND t.kind='campus')
                AND NOT EXISTS (SELECT 1 FROM history_targets t WHERE t.revision=a.revision
                AND t.kind='campus' AND t.entity NOT IN (SELECT value FROM json_each(?))))"""
            params.append(json.dumps(campuses))
        filters.append("(" + clause + ")")
    if room:
        filters.append("(instr(a.room,?)>0 OR instr(a.previousRoom,?)>0)")
        params.extend((room, room))
    if actor:
        filters.append(
            "(a.actorId=? OR instr(a.actorName,?)>0 OR instr(a.actorLogin,?)>0)"
        )
        params.extend((actor, actor, actor))
    if before is not None:
        if type(before) is not int or before <= 0:
            raise ValueError("分页游标无效")
        filters.append("a.revision < ?")
        params.append(before)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("每页应为 1 到 100 条")
    where = " WHERE " + " AND ".join(filters) if filters else ""
    visible = []
    query = """SELECT a.*, r.actor AS agentInitiator, s.grants AS agentGrants
               FROM audit a LEFT JOIN agent_audit_scope s ON s.runId=a.agentRunId
               LEFT JOIN agent_runs r ON r.id=s.runId"""
    for record in db.execute(query + where + " ORDER BY a.revision DESC", params):
        item = dict(record)
        initiator = item.pop("agentInitiator")
        grants = (item.pop("agentGrants") or "").split()
        if user.get("facilityScope") and item["action"].startswith("agent."):
            from .agents import region_visible

            if not region_visible(db, user, item["agentRunId"]):
                continue
        if access.can_view_audit(
            user, item["action"], agent_initiator=initiator, agent_grants=grants
        ):
            visible.append(item)
            if len(visible) > limit:
                break
    return {
        "rows": visible[:limit],
        "nextBefore": visible[limit - 1]["revision"] if len(visible) > limit else None,
    }
