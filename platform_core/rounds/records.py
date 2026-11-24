"""Read and record changes to an individual resident's current stay."""

from datetime import date, timedelta
from hashlib import sha256
import json
from uuid import uuid4

from .. import access, activity, campus_access, history
from .report import build


def workspace(db):
    revision, data = db.execute(
        "SELECT revision,data FROM workspace WHERE id=1"
    ).fetchone()
    return revision, json.loads(data)


def staff(user):
    if user["kind"] not in ("owner", "staff") or not any(
        access.has(user, p) for p in ("care", "clinical")
    ):
        raise PermissionError("巡查档案需要照护或临床权限")


def locate(db, state, user, rid):
    staff(user)
    campus_access.require_resident(db, user, rid, state)
    person = next((r for r in state["residents"] if r["id"] == rid), None)
    if not person:
        raise FileNotFoundError("未找到长者")
    if person["status"] != "在住":
        raise ValueError("仅在住长者可使用巡查档案")
    return current_stay(state, person)


def current_stay(state, person):
    move = next(
        (
            m
            for m in reversed(state.get("bedMoves", ()))
            if m["residentId"] == person["id"]
        ),
        {},
    )
    start = move.get("date") or person.get("admittedAt", "")
    transfer = start if move.get("beforeBedId") else ""
    since = (
        (date.fromisoformat(transfer) + timedelta(days=1)).isoformat()
        if transfer
        else start
    )
    return {
        **person,
        "_stayId": move.get("id", ""),
        "_fromDay": since,
        "_transferDay": transfer,
    }


def active(person):
    return person.get("status") == "在住" and bool(person.get("bedId"))


def policy(db):
    r = db.execute("SELECT * FROM rounds_policy WHERE singleton=1").fetchone()
    return {
        "enabled": bool(r["enabled"]),
        "intervalMinutes": r["interval_min"],
        "defaultMode": r["default_mode"],
        "notifyAt": r["notify_at"],
        "nextRunAt": r["next_at"] if r["enabled"] else None,
        "lastRunAt": r["last_at"],
    }


def mode(db, rid):
    r = db.execute("SELECT mode FROM rounds_modes WHERE resident=?", (rid,)).fetchone()
    return r[0] if r else "inherit"


def latest(db, person, day=None):
    sql = "SELECT payload FROM rounds_reports WHERE resident=? AND bed=? AND json_extract(payload,'$.stayId')=?"
    args = [person["id"], person.get("bedId", ""), person["_stayId"]]
    if day:
        sql += " AND day=?"
        args.append(day)
    r = db.execute(
        sql + " ORDER BY created_at DESC,rowid DESC LIMIT 1", args
    ).fetchone()
    return json.loads(r[0]) if r else None


def visible_report(report, user):
    if not report:
        return None
    clinical = access.has(user, "clinical")
    output = dict(report)
    for field in ("changes", "suggestions"):
        output[field] = [
            item
            for item in report[field]
            if item["permission"] != "clinical" or clinical
        ]
    if not clinical:
        output["cough"] = None
    return output


def card(db, person, user):
    selection = mode(db, person["id"])
    return {
        "residentId": person["id"],
        "mode": selection,
        "effectiveMode": policy(db)["defaultMode"]
        if selection == "inherit"
        else selection,
        "canGenerate": active(person),
        "canConfigure": access.has(user, "care") and active(person),
        "canObserve": access.has(user, "clinical") and active(person),
        "latest": visible_report(latest(db, person), user),
    }


def audit(db, now, action, summary, actor, state, rid, comment=""):
    revision = db.execute("SELECT revision FROM workspace WHERE id=1").fetchone()[0] + 1
    db.execute("UPDATE workspace SET revision=? WHERE id=1", (revision,))
    scope = activity.for_person(state, rid) if rid else {}
    activity.write(
        db,
        revision,
        now.isoformat(),
        action,
        summary,
        actor,
        scope,
        {},
        comment=comment,
    )
    return revision


def make_report(db, state, person, now, actor, comment=""):
    data = build(db, state, person, now)
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = sha256(raw.encode()).hexdigest()
    last = db.execute(
        """SELECT fingerprint FROM rounds_reports WHERE resident=? AND bed=? AND day=?
                         ORDER BY created_at DESC,rowid DESC LIMIT 1""",
        (person["id"], data["bedId"], data["day"]),
    ).fetchone()
    if last and last[0] == digest:
        return False
    history.watch(db, "rounds.generate")
    data.update(id=uuid4().hex, generatedAt=now.isoformat())
    db.execute(
        "INSERT INTO rounds_reports VALUES(?,?,?,?,?,?,?)",
        (
            data["id"],
            person["id"],
            data["bedId"],
            data["day"],
            data["generatedAt"],
            digest,
            json.dumps(data, ensure_ascii=False),
        ),
    )
    audit(
        db,
        now,
        "rounds.generate",
        "生成长者巡查摘要",
        actor,
        state,
        person["id"],
        comment,
    )
    return True


def inbox_query(db, state, beds, clinical, today=None):
    # Current membership is resolved once, including moves back to the same bed.
    moves = {m["residentId"]: m["id"] for m in state.get("bedMoves", ())}
    permitted = [
        [r["id"], r.get("bedId", ""), moves.get(r["id"], ""), r.get("name", "")]
        for r in state["residents"]
        if active(r) and (beds is None or r["bedId"] in beds)
    ]
    fields = (
        "COUNT(*)"
        if today
        else "i.*, p.name AS resident_name,json_extract(r.payload,'$.today') AS today,COUNT(*) OVER() AS total"
    )
    stmt = (
        """WITH permitted(id,bed,stay,name) AS (
               SELECT json_extract(value,'$[0]'),json_extract(value,'$[1]'),
                      json_extract(value,'$[2]'),json_extract(value,'$[3]') FROM json_each(?))
              SELECT """
        + fields
        + """ FROM permitted p JOIN rounds_staff_inbox i ON p.id=i.resident
              JOIN rounds_reports r ON r.id=i.report AND r.bed=p.bed AND json_extract(r.payload,'$.stayId')=p.stay"""
    )
    stmt += """ WHERE (? OR EXISTS(SELECT 1 FROM json_each(i.signals) WHERE value IN ('pending','carry')))"""
    if today:
        return db.execute(
            stmt + " AND i.day=?", (json.dumps(permitted), clinical, today)
        )
    return db.execute(
        stmt + " ORDER BY i.day DESC,i.delivered_at DESC,i.resident LIMIT 100",
        (json.dumps(permitted), clinical),
    )
