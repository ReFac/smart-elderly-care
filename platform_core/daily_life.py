"""Group activity rosters, signed attendance and resident-specific daily life receipts."""

from contextlib import closing
from datetime import date
from hashlib import sha256
import json
import re
from uuid import uuid4
from zoneinfo import ZoneInfo

from . import access_policy as access, campus_access, facility, portal
from .care import archive_retention
from .care.records import iso_date, lookup, text_field


LOCAL = ZoneInfo("Asia/Shanghai")
MEALS = ("早餐", "午餐", "晚餐")
KINDS = (*MEALS, "集体活动")
FIELDS = {
    "requestId",
    "campusId",
    "roomId",
    "kind",
    "day",
    "startsAt",
    "endsAt",
    "details",
}


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS daily_life_events(
        id TEXT PRIMARY KEY, campusId TEXT NOT NULL, roomId TEXT NOT NULL,
        day TEXT NOT NULL, kind TEXT NOT NULL, startsAt TEXT NOT NULL, endsAt TEXT NOT NULL,
        details TEXT NOT NULL, proposedById TEXT NOT NULL, proposedBy TEXT NOT NULL, proposedAt TEXT NOT NULL,
        requestId TEXT NOT NULL, fingerprint TEXT NOT NULL, scopeKey TEXT NOT NULL,
        UNIQUE(proposedById,requestId), UNIQUE(campusId,scopeKey,kind,day,startsAt))""")
    db.execute("""CREATE TABLE IF NOT EXISTS daily_life_invitees(
        eventId TEXT NOT NULL REFERENCES daily_life_events(id), residentId TEXT NOT NULL,
        roomId TEXT NOT NULL, roomNumber TEXT NOT NULL, bedId TEXT NOT NULL, bedLabel TEXT NOT NULL,
        PRIMARY KEY(eventId,residentId))""")
    db.execute("""CREATE TABLE IF NOT EXISTS daily_life_attendance(
        eventId TEXT NOT NULL, residentId TEXT NOT NULL, kind TEXT NOT NULL, day TEXT NOT NULL,
        intake TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(eventId,residentId),
        FOREIGN KEY(eventId,residentId) REFERENCES daily_life_invitees(eventId,residentId))""")
    db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS daily_life_one_meal
        ON daily_life_attendance(residentId,day,kind) WHERE kind IN ('早餐','午餐','晚餐')""")
    db.execute("""CREATE INDEX IF NOT EXISTS daily_life_resident_day
        ON daily_life_attendance(residentId,day)""")
    db.execute("""CREATE TABLE IF NOT EXISTS daily_life_signatures(
        eventId TEXT PRIMARY KEY REFERENCES daily_life_events(id),
        confirmedById TEXT NOT NULL, confirmedBy TEXT NOT NULL, confirmedAt TEXT NOT NULL,
        confirmedByPosition TEXT NOT NULL DEFAULT '')""")
    for table, field in (
        ("daily_life_attendance", "intake"),
        ("daily_life_signatures", "confirmedByPosition"),
    ):
        if field not in {c[1] for c in db.execute(f"PRAGMA table_info({table})")}:
            db.execute(
                f"ALTER TABLE {table} ADD COLUMN {field} TEXT NOT NULL DEFAULT ''"
            )
    for table in (
        "daily_life_events",
        "daily_life_invitees",
        "daily_life_attendance",
        "daily_life_signatures",
    ):
        for op in ("UPDATE", "DELETE"):
            db.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_no_{op} BEFORE {op} ON {table}
                BEGIN SELECT RAISE(ABORT,'已登记的活动凭证不可覆盖'); END""")


def _staff(user, *grants):
    if user["kind"] not in ("staff", "owner") or not any(
        access.has(user, k) for k in grants
    ):
        raise PermissionError("此账号没有本次生活活动的办理权限")


def _places(db, state, user, campus_id, room_id):
    acl = facility._access(db, user, environment=True)
    atlas = facility._directory(db, state, user, acl)
    campuses = [{k: c[k] for k in ("id", "name")} for c in atlas["campuses"]]
    chosen = campus_id or (campuses[0]["id"] if campuses else "")
    if chosen and chosen not in {c["id"] for c in campuses}:
        raise PermissionError("所选分院不在本人授权范围")
    rooms = facility._meta(db, acl, campusId=chosen) if chosen else []
    if room_id and room_id not in {r["id"] for r in rooms}:
        raise PermissionError("请选择本人工作区域内的房间")
    return campuses, chosen, rooms


def _participants(db, state, user, rooms, day):
    if not rooms:
        return []
    by_room = {r["id"]: r for r in rooms}
    placements = dict(db.execute("SELECT bedId,roomId FROM facility_beds"))
    beds = {r["id"]: r for r in state["beds"]}
    allowed = campus_access.allowed_beds(db, user, include_rooms=True)
    away = {
        r["residentId"]
        for r in state["leaves"]
        if r["startDate"] <= day <= r["endDate"]
    }
    # Reconstruct the last known allocation on the day for a retrospectively recorded meal.
    historical = {
        r["residentId"]: r["bedId"] for r in state["bedMoves"] if r["date"] <= day
    }
    moved = {r["residentId"] for r in state["bedMoves"]}
    result = []
    for r in state["residents"]:
        rid, current = r["id"], r.get("bedId")
        if (
            r["status"] != "在住"
            or rid in away
            or not current
            or beds.get(current, {}).get("residentId") != rid
            or (r.get("admittedAt") or "") > day
            or (allowed is not None and current not in allowed)
        ):
            continue
        bed = historical.get(rid, "" if rid in moved else current)
        room = by_room.get(placements.get(bed))
        if room and bed in beds:
            result.append(
                {
                    "id": rid,
                    "name": r["name"],
                    "bedId": bed,
                    "bedLabel": beds[bed]["label"],
                    "roomId": room["id"],
                    "roomNumber": room["number"],
                }
            )
    return sorted(result, key=lambda x: (x["roomNumber"], x["bedLabel"], x["id"]))


def _cohort(db, state, user, campus, room, day):
    _, chosen, rooms = _places(db, state, user, campus, room)
    rooms = [r for r in rooms if not room or r["id"] == room]
    return chosen, rooms, _participants(db, state, user, rooms, day)


def _checked_fields(p, now):
    if not isinstance(p, dict) or set(p) != FIELDS:
        raise ValueError("请核对活动范围、时间及内容")
    fields = dict(p)
    for key in ("campusId", "roomId", "requestId"):
        fields[key] = text_field(
            p[key], "活动编号或地点", required=key != "roomId", limit=100
        )
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", fields["requestId"]):
        raise ValueError("活动请求编号无效")
    if p["kind"] not in KINDS:
        raise ValueError("请选择早餐、午餐、晚餐或集体活动")
    fields["day"] = iso_date(p["day"], "活动日期")
    if fields["day"] > now.date().isoformat():
        raise ValueError("请选择今天或此前实际举办活动的日期")
    for k in ("startsAt", "endsAt"):
        if not isinstance(p[k], str) or not re.fullmatch(
            r"(?:[01]\d|2[0-3]):[0-5]\d", p[k]
        ):
            raise ValueError("请使用北京时间的小时和分钟")
    if p["startsAt"] >= p["endsAt"]:
        raise ValueError("同日活动的结束时间须晚于开始时间")
    fields["details"] = text_field(
        p["details"], "供应餐食或活动名称", required=True, limit=500
    )
    return fields


def _save_event(db, state, user, payload, now):
    p = _checked_fields(payload, now)
    digest = sha256(
        json.dumps(p, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    old = db.execute(
        "SELECT id,fingerprint FROM daily_life_events WHERE proposedById=? AND requestId=?",
        (user["id"], p["requestId"]),
    ).fetchone()
    if old:
        if old[1] != digest:
            raise ValueError("提交编号已用于其他活动")
        _places(db, state, user, p["campusId"], p["roomId"])
        return old[0]
    campus, rooms, people = _cohort(
        db, state, user, p["campusId"], p["roomId"], p["day"]
    )
    if not people:
        raise ValueError("所选区域及日期没有可登记的在院长者")
    scope = sha256(json.dumps(sorted(r["id"] for r in rooms)).encode()).hexdigest()
    duplicate = db.execute(
        """SELECT 1 FROM daily_life_events
        WHERE campusId=? AND scopeKey=? AND kind=? AND day=? AND startsAt=?""",
        (campus, scope, p["kind"], p["day"], p["startsAt"]),
    ).fetchone()
    if duplicate:
        raise ValueError("该范围和时段已登记同类活动，请查阅待确认活动或签认凭证")
    event = uuid4().hex
    db.execute(
        """INSERT INTO daily_life_events(id,campusId,roomId,day,kind,startsAt,endsAt,
        details,proposedById,proposedBy,proposedAt,requestId,fingerprint,scopeKey)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            event,
            campus,
            p["roomId"],
            p["day"],
            p["kind"],
            p["startsAt"],
            p["endsAt"],
            p["details"],
            user["id"],
            user["displayName"],
            now.isoformat(timespec="seconds"),
            p["requestId"],
            digest,
            scope,
        ),
    )
    db.executemany(
        "INSERT INTO daily_life_invitees VALUES(?,?,?,?,?,?)",
        [
            (event, r["id"], r["roomId"], r["roomNumber"], r["bedId"], r["bedLabel"])
            for r in people
        ],
    )
    return event


def propose(db, state, user, p, now):
    _staff(user, "care", "care.groupConfirm")
    _save_event(db, state, user, p, now.astimezone(LOCAL))
    return "已登记集体活动，结束后由获授权人员确认实际参加者"


def _visible_residents(db, state, user):
    if state is None:
        state = json.loads(
            db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
        )
    beds = campus_access.allowed_beds(db, user, include_rooms=True)
    allowed = (
        campus_access.resident_ids(state, beds, user) if beds is not None else None
    )
    return {
        r["id"]: r["name"]
        for r in state["residents"]
        if r["status"] != archive_retention.EXPIRED
        and (allowed is None or r["id"] in allowed)
    }


def _guests(db, event_id):
    return [
        dict(r)
        for r in db.execute(
            """SELECT residentId AS id,bedId,bedLabel,roomId,roomNumber
        FROM daily_life_invitees WHERE eventId=? ORDER BY roomNumber,bedLabel,residentId""",
            (event_id,),
        )
    ]


def _allowed_group(guests, rooms, names):
    return bool(guests) and all(
        r["roomId"] in rooms and r["id"] in names for r in guests
    )


def _ready(event, now):
    return (event["day"], event["endsAt"]) <= (
        now.date().isoformat(),
        now.strftime("%H:%M"),
    )


def confirm(db, state, user, p, now):
    _staff(user, "care.groupConfirm")
    now = now.astimezone(LOCAL)
    if not isinstance(p, dict) or p.get("confirmed") is not True:
        raise ValueError("请确认实际参加本次活动的长者名单")
    ids = p.get("residentIds")
    if (
        not isinstance(ids, list)
        or any(not isinstance(k, str) or not k for k in ids)
        or len(set(ids)) != len(ids)
    ):
        raise ValueError("请逐人核对实际参加名单")
    if set(p) - {"mealIntake"} == {"eventId", "residentIds", "confirmed"}:
        event_id = text_field(p["eventId"], "活动编号", required=True, limit=100)
    else:
        event_id = _save_event(
            db,
            state,
            user,
            {
                k: v
                for k, v in p.items()
                if k not in ("residentIds", "confirmed", "mealIntake")
            },
            now,
        )
    e = db.execute("SELECT * FROM daily_life_events WHERE id=?", (event_id,)).fetchone()
    if not e:
        raise FileNotFoundError("该活动不存在或不在授权范围")
    _, _, rooms = _places(db, state, user, e["campusId"], e["roomId"])
    guests = _guests(db, event_id)
    if not _allowed_group(
        guests, {r["id"] for r in rooms}, _visible_residents(db, state, user)
    ):
        raise PermissionError("整份活动名单须由有相应区域权限的人员核对")
    if not _ready(e, now):
        raise ValueError("活动结束后才能确认参加名单")
    selected = set(ids)
    if not selected <= {r["id"] for r in guests}:
        raise ValueError("实际参加者必须属于本次活动的待确认名单")
    intake = p.get("mealIntake", {})
    if (
        not isinstance(intake, dict)
        or intake.keys() - selected
        or (intake and e["kind"] not in MEALS)
    ):
        raise ValueError("仅可为参加本餐的长者填写实际进食情况")
    intake = {
        rid: text_field(intake.get(rid), "个人实际进食", limit=300) for rid in selected
    }
    signed = db.execute(
        "SELECT confirmedById FROM daily_life_signatures WHERE eventId=?", (event_id,)
    ).fetchone()
    if signed:
        previous = dict(
            db.execute(
                "SELECT residentId,intake FROM daily_life_attendance WHERE eventId=?",
                (event_id,),
            )
        )
        if signed[0] == user["id"] and intake == previous:
            return "本次活动已经核对，沿用原参加凭证"
        raise ValueError("本次活动已由经办人确认，请查看签认凭证")
    if (
        e["kind"] in MEALS
        and db.execute(
            """SELECT 1 FROM daily_life_attendance
        WHERE day=? AND kind=? AND residentId IN (SELECT value FROM json_each(?)) LIMIT 1""",
            (e["day"], e["kind"], json.dumps(ids)),
        ).fetchone()
    ):
        raise ValueError("名单中已有长者签认了当天这顿饭，请对照个人记录并排除重复者")
    db.executemany(
        "INSERT INTO daily_life_attendance VALUES(?,?,?,?,?)",
        [(event_id, rid, e["kind"], e["day"], intake[rid]) for rid in sorted(ids)],
    )
    position = (
        user["role"]
        if user["role"] != "自定义"
        else "、".join(user.get("staffDuties", ()))
    )
    db.execute(
        "INSERT INTO daily_life_signatures VALUES(?,?,?,?,?)",
        (
            event_id,
            user["id"],
            user["displayName"],
            now.isoformat(timespec="seconds"),
            position,
        ),
    )
    return f"已核对{e['kind']}实际参加 {len(ids)} 人，排除 {len(guests) - len(ids)} 人"


EVENT_FIELDS = (
    "id",
    "campusId",
    "roomId",
    "kind",
    "day",
    "startsAt",
    "endsAt",
    "details",
    "proposedBy",
    "proposedById",
)


def _pending(db, state, user, now, rooms, campus="", room="", count_only=False):
    if not rooms:
        return []
    names = _visible_residents(db, state, user)
    rows = db.execute(
        """SELECT e.* FROM daily_life_events e
        LEFT JOIN daily_life_signatures s ON s.eventId=e.id
        WHERE s.eventId IS NULL AND (?='' OR e.campusId=?) AND (?='' OR e.roomId=?)
        ORDER BY e.day DESC,e.startsAt DESC,e.id""",
        (campus, campus, room, room),
    )
    result = []
    for e in rows:
        ready = _ready(e, now)
        if count_only and not ready:
            continue
        guests = _guests(db, e["id"])
        if _allowed_group(guests, rooms, names):
            if count_only:
                result.append(e["campusId"])
            else:
                result.append(
                    {
                        **{k: e[k] for k in EVENT_FIELDS},
                        "ready": ready,
                        "residents": [{**r, "name": names[r["id"]]} for r in guests],
                    }
                )
    return result


def pending_count(db, state, user, now):
    if user["kind"] not in ("owner", "staff") or not access.has(
        user, "care.groupConfirm"
    ):
        return 0
    now = now.astimezone(LOCAL)
    if not db.execute(
        """SELECT 1 FROM daily_life_events e WHERE (day,endsAt) <= (?,?)
            AND NOT EXISTS (SELECT 1 FROM daily_life_signatures s WHERE s.eventId=e.id) LIMIT 1""",
        (now.date().isoformat(), now.strftime("%H:%M")),
    ).fetchone():
        return 0
    rooms = facility._meta(db, facility._access(db, user, environment=True))
    return len(
        _pending(
            db,
            state,
            user,
            now,
            {r["id"] for r in rooms},
            count_only=True,
        )
    )


def roster(store, token, campus_id="", room_id="", day=""):
    now = store.now().astimezone(LOCAL)
    day = iso_date(day, "活动日期") if day else now.date().isoformat()
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        user = store.actor(db, token)
        _staff(user, "care", "care.groupConfirm")
        rev, data = db.execute(
            "SELECT revision,data FROM workspace WHERE id=1"
        ).fetchone()
        state = json.loads(data)
        if not campus_id and not room_id and access.has(user, "care.groupConfirm"):
            accessible = facility._meta(
                db, facility._access(db, user, environment=True)
            )
            due = _pending(
                db, state, user, now, {r["id"] for r in accessible}, count_only=True
            )
            campus_id = due[0] if due else ""
        campuses, campus, rooms = _places(db, state, user, campus_id, room_id)
        selected = [r for r in rooms if not room_id or r["id"] == room_id]
        ids = {r["id"] for r in selected}
        receipts = [
            dict(r)
            for r in db.execute(
                """SELECT e.id,e.kind,e.day,e.startsAt,e.endsAt,e.details,
            s.confirmedBy,s.confirmedById,s.confirmedByPosition,s.confirmedAt,COUNT(a.residentId) AS attendedCount,
            COUNT(i.residentId)-COUNT(a.residentId) AS excludedCount FROM daily_life_events e
            JOIN daily_life_signatures s ON s.eventId=e.id JOIN daily_life_invitees i ON i.eventId=e.id
            LEFT JOIN daily_life_attendance a ON a.eventId=i.eventId AND a.residentId=i.residentId
            WHERE e.campusId=? AND e.day=? AND i.roomId IN (SELECT value FROM json_each(?))
            GROUP BY e.id ORDER BY e.startsAt DESC,e.id""",
                (campus, day, json.dumps(sorted(ids))),
            )
        ]
        return {
            "revision": rev,
            "campusId": campus,
            "roomId": room_id,
            "day": day,
            "campuses": campuses,
            "rooms": [
                {
                    "id": r["id"],
                    "label": " / ".join(
                        (r["buildingName"], r["floorLabel"], r["number"] + " 房")
                    ),
                }
                for r in rooms
            ],
            "residents": _participants(db, state, user, selected, day),
            "pending": _pending(db, state, user, now, ids, campus, room_id),
            "receipts": receipts,
        }


def resident_events(db, resident_id, start_day, end_day):
    """Signed individual attendance only; the menu identifies food served at the event."""
    return [
        dict(r)
        for r in db.execute(
            """SELECT e.id,e.kind,e.day,e.startsAt,e.endsAt,e.details,a.intake,
        i.roomId,i.roomNumber,s.confirmedAt,s.confirmedBy,s.confirmedById,s.confirmedByPosition
        FROM daily_life_attendance a
        JOIN daily_life_events e ON a.eventId=e.id JOIN daily_life_invitees i USING(eventId,residentId)
        JOIN daily_life_signatures s ON s.eventId=e.id WHERE a.residentId=? AND a.day BETWEEN ? AND ?
        ORDER BY a.day DESC,e.startsAt DESC,e.id""",
            (resident_id, str(start_day), str(end_day)),
        )
    ]


def timeline(store, token, rid, start="", end=""):
    today = store.now().astimezone(LOCAL).date()
    end = iso_date(end, "结束日期") if end else today.isoformat()
    start = (
        iso_date(start, "开始日期")
        if start
        else date.fromordinal(
            max(1, date.fromisoformat(end).toordinal() - 29)
        ).isoformat()
    )
    if start > end:
        raise ValueError("开始日期应早于或等于结束日期")
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        user = store.actor(db, token)
        personal = user["kind"] == "family"
        if personal:
            portal.require_personal_health(user, rid)
        else:
            _staff(
                user, "care", "clinical", "residents", "medical", "care.groupConfirm"
            )
        state = json.loads(
            db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
        )
        campus_access.require_resident(db, user, rid, state)
        if lookup(state, "residents", rid)["status"] == archive_retention.EXPIRED:
            raise FileNotFoundError("档案已到期")
        events = resident_events(db, rid, start, end)
        if not personal and user.get("facilityScope"):
            rooms = {
                room["id"] for room in facility._meta(db, facility._access(db, user, environment=True))
            }
            events = [event for event in events if event["roomId"] in rooms]
        if personal:
            fields = (
                "kind",
                "day",
                "startsAt",
                "endsAt",
                "details",
                "intake",
                "roomNumber",
                "confirmedAt",
                "confirmedBy",
                "confirmedByPosition",
            )
            events = [{key: event[key] for key in fields} for event in events]
        return {"events": events}
