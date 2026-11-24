"""Apply a persisted branch assignment to workspace rows and authenticated commands."""

import json

from . import facility

# These ledgers are maintained for the institution as a whole.
INSTITUTION_GRANTS = {"inventory", "shifts", "reports", "clinical.rules"}


def bound(user):
    return user.get("kind") == "staff" and "campusIds" in (
        user.get("facilityScope") or {}
    )


def effective(user, supplied):
    """Intersect a local assignment with the deployment's optional area policy."""
    if not isinstance(supplied, dict):
        raise PermissionError("区域授权无效")
    merged = dict(supplied)
    local = user.get("facilityScope", {}).get("campusIds")
    if local is not None:
        remote = merged.get("campusIds", local)
        if not isinstance(remote, (list, tuple)) or not all(
            isinstance(x, str) for x in remote
        ):
            raise PermissionError("分院授权无效")
        merged["campusIds"] = [key for key in local if key in remote]
    return merged


def allowed_beds(db, user, *, include_rooms=False):
    if not bound(user) and not (include_rooms and user.get("facilityScope")):
        return None
    acl = facility._access(db, user, environment=True)
    where, args = facility._restrictions(acl)
    return {
        r[0]
        for r in db.execute(
            "SELECT beds.bedId FROM "
            + facility.ROOM_TABLE
            + " JOIN facility_beds beds ON beds.roomId=r.id"
            + where,
            args,
        )
    }


def resident_ids(state, beds):
    last_beds = {
        r["residentId"]: r.get("bedId") or r.get("beforeBedId")
        for r in state.get("bedMoves", ())
    }
    return {
        r["id"]
        for r in state["residents"]
        if (r.get("bedId") or last_beds.get(r["id"])) in beds
    }


def current_residents(db, user):
    if not bound(user):
        return None
    state = json.loads(
        db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
    )
    return resident_ids(state, allowed_beds(db, user))


def require_resident(db, user, resident_id, state=None):
    beds = allowed_beds(db, user, include_rooms=True)
    if beds is None:
        return
    if state is None:
        state = json.loads(
            db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
        )
    if resident_id not in resident_ids(state, beds):
        raise PermissionError("长者不在本人获授权的分院范围内")


def require_document(db, user, document_id):
    if user.get("facilityScope"):
        row = db.execute(
            "SELECT resident_id FROM dossier_documents WHERE id=?", (document_id,)
        ).fetchone()
        require_resident(db, user, row[0] if row else None)


def projection(db, state, user):
    beds = allowed_beds(db, user)
    if beds is None:
        return state
    residents = resident_ids(state, beds)
    campuses = user["facilityScope"]["campusIds"]
    result = {}
    # Unknown row collections stay private until their ownership relationship is declared.
    for key, rows in state.items():
        if key == "beds":
            result[key] = [r for r in rows if r["id"] in beds]
        elif key == "residents":
            result[key] = [r for r in rows if r["id"] in residents]
        elif key == "inquiries":
            result[key] = [
                r for r in rows if r.get("campusId", facility.HOME_CAMPUS) in campuses
            ]
        elif key in ("drugRules", "suggestions"):
            # Suggestions produced by a run are checked against its saved region by Store.
            result[key] = rows
        elif key == "handovers":
            result[key] = [
                r
                for r in rows
                if r.get("residentId") in residents
                or (
                    user["id"] in (r.get("senderId"), r.get("assigneeId"))
                    and r.get("draftScope") == "personal"
                    and "draftResidentIds" in r
                    and set(r["draftResidentIds"]) <= residents
                )
            ]
        else:
            result[key] = [r for r in rows if r.get("residentId") in residents]
    return result


def authorize_command(db, user, action, payload, state):
    if not bound(user):
        return
    from . import activity

    if action.startswith(("agent.", "access.")) or action in (
        "account.changePassword",
        "ops.review",
    ):
        return
    beds = allowed_beds(db, user)
    residents = resident_ids(state, beds)

    def person(rid):
        if rid not in residents:
            raise PermissionError("业务记录不在本人获授权的分院范围内")

    if payload.get("residentId"):
        person(payload["residentId"])
    if payload.get("bedId") and payload["bedId"] not in beds:
        raise PermissionError("床位不在本人获授权的分院范围内")
    if action in ("care.admit", "gw.ingest"):
        if payload.get("bedId") not in beds:
            raise PermissionError("请选择获授权的床位")
        if payload.get("inquiryId") and not any(
            r["id"] == payload["inquiryId"]
            and r.get("campusId", facility.HOME_CAMPUS)
            in user["facilityScope"]["campusIds"]
            for r in state["inquiries"]
        ):
            raise PermissionError("入住意向不在本人分院")
        return
    if action == "care.inquire":
        if len(user["facilityScope"]["campusIds"]) != 1 and not payload.get("campusId"):
            raise PermissionError("接待登记须指明一个获授权的分院")
        return
    if action in ("gw.review", "gw.confirm", "gw.dismiss"):
        table, key = (
            ("gateway_alert", "alertId")
            if action == "gw.review"
            else ("gateway_voice", "proposalId")
        )
        row = db.execute(
            f"SELECT bed_id,resident_id FROM {table} WHERE id=?", (payload.get(key),)
        ).fetchone()
        if not row or row[0] not in beds:
            raise PermissionError("事件不在本人获授权的分院范围内")
        if action != "gw.review":
            person(row[1])
        return
    if action == "gw.propose":
        person(
            next(
                (
                    r["residentId"]
                    for r in state["tasks"]
                    if r["id"] == payload.get("taskId")
                ),
                None,
            )
        )
        return
    if action in ("care.acceptHandover", "care.withdrawHandover"):
        records = projection(db, state, user)["handovers"]
        if not any(r["id"] == payload.get("handoverId") for r in records):
            raise PermissionError("交班不在本人获授权的分院范围内")
        return
    if action == "care.handover":
        # The handover module checks the intersection of sender and recipient areas.
        return
    if action in activity.PERSON_ACTIONS:
        person(payload.get("residentId"))
        return
    if action in activity.RELATED:
        field, collection = activity.RELATED[action]
        person(
            next(
                (
                    r.get("residentId")
                    for r in state[collection]
                    if r["id"] == payload.get(field)
                ),
                None,
            )
        )
        return
    raise PermissionError("该操作需要全机构授权")
