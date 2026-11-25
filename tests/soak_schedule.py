"""Independent expected roster/calendar and cold-restore checks for the 200-bed soak.

Call seed_schedule after seed_beds, before starting the real institutional server.
Keep its returned synthetic manifest outside the live database. The verifier only
reads the original; all restoration happens in new temporary directories.
"""

from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from platform_core import secure_storage
from platform_core.backups.cloud import hash_file
from test_account_directory import PASSWORD


ZONE = ZoneInfo("Asia/Shanghai")
MINUTE = timedelta(minutes=1)
DAY = timedelta(days=1)
DAILY = (
    ("早间巡查", "06:30", "patrol", []),
    ("早餐", "07:30", "meal", ["小米粥", "蒸蛋"]),
    ("午餐", "11:30", "meal", ["米饭", "冬瓜"]),
    ("晚餐", "17:30", "meal", ["面条", "青菜"]),
    ("晚间巡查", "20:30", "patrol", []),
)


def seed_schedule(store):
    """Set up recurring work using normal commands, without manually ticking any worker."""
    now = store.now().astimezone(ZONE)
    with closing(store.connect()) as db:
        state = json.loads(db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0])
        beds = state["beds"]
        people = sorted(b["residentId"] for b in beds if b.get("residentId"))
        if (len(beds), len(people), len(set(people))) != (200, 180, 180):
            raise ValueError("Expected isolated 200-bed / 180-occupant fixture")
        if (db.execute("SELECT count(*) FROM scheduled_work_rules").fetchone()[0]
                or db.execute("SELECT count(*) FROM daily_life_attendance").fetchone()[0]
                or any(t.get("mealKind") for t in state["tasks"]) or state["leaves"]):
            raise ValueError("The fixture already has schedules, meal bookings or leave")
    token, _ = store.login("owner", PASSWORD)
    rules = []
    first_probe = now.replace(second=0, microsecond=0) + 2 * MINUTE
    # Two residents per hourly probe check rolling dispatch without generating a
    # whole-institution care order each hour. Five full rounds cover all residents.
    specs = [(name, clock, kind, menu, None) for name, clock, kind, menu in DAILY]
    for hour in range(24):
        due = first_probe + timedelta(hours=hour)
        specs.append((f"小时巡查 {hour + 1:02}", due.strftime("%H:%M"), "patrol", [],
                      people[hour * 2 : hour * 2 + 2]))
    try:
        for name, clock, kind, menu, cohort in specs:
            first = datetime.combine(now.date(), time.fromisoformat(clock), ZONE)
            if first < now:
                first += DAY
            scope = {"kind": "residents", "residentIds": cohort} if cohort else {"kind": "all"}
            fields = dict(title=name, time=clock, kind=kind, scope=scope, startDate=first.date().isoformat())
            if menu:
                fields.update(mealKind=name, menu=menu)
            store.execute("care.saveSchedule", fields, store.version(token)["revision"], token)
            with closing(store.connect()) as db:
                rid, = db.execute("SELECT id FROM scheduled_work_rules WHERE json_extract(config,'$.title')=?",
                                  (name,)).fetchone()
            rules.append({"id": rid, "name": name, "first": int(first.timestamp()), "cohort": cohort,
                          "menu": menu})
    finally:
        store.logout(token)
    return {"resident_ids": people, "beds": len(beds), "rules": rules}


def expected_occurrences(manifest, end):
    """Calendar expectation depends solely on pre-run fixture data and the window end."""
    for rule in manifest["rules"]:
        due = datetime.fromtimestamp(rule["first"], ZONE)
        while due.timestamp() <= end:
            yield rule, due
            due += DAY


def check_work(db, state, manifest, end):
    runs = {(r["scheduleId"], r["day"]): r for r in db.execute("SELECT * FROM scheduled_work_runs")}
    by_day = defaultdict(list)
    for task in state["tasks"]:
        if task.get("scheduleId"):
            by_day[task["scheduleId"], task["date"]].append(task)
    occurrences, problems = [], []
    expected_keys = set()
    for rule, due in expected_occurrences(manifest, end):
        key = (rule["id"], due.date().isoformat())
        expected_keys.add(key)
        recipients = rule["cohort"] or manifest["resident_ids"]
        run, tasks = runs.get(key), by_day[key]
        counts = Counter(t["residentId"] for t in tasks)
        errors = []
        delay = None
        if run is None:
            errors.append("missing dispatch receipt")
        else:
            delay = int(datetime.fromisoformat(run["releasedAt"]).timestamp() - due.timestamp())
            valid = (run["count"] == len(recipients) and run["status"] == "released"
                     and run["time"] == due.strftime("%H:%M"))
            if not valid:
                errors.append("incorrect dispatch receipt")
            if delay < 0 or delay > 60:
                errors.append("dispatch outside 0–60 second timing window")
        if counts != Counter(recipients):
            errors.append("roster mismatch")
        if any(t.get("occurrenceId") != (run["id"] if run else None) or not t.get("scheduledBedId")
               or not t.get("scheduledRoomId") or t["time"] != due.strftime("%H:%M")
               or t["title"] != rule["name"] or (rule["menu"] and
                   (t.get("mealKind") != rule["name"] or t.get("menu") != rule["menu"])) for t in tasks):
            errors.append("incorrect task details or receipt linkage")
        record = {"name": rule["name"], "due": due.isoformat(), "delay_s": delay,
                  "expected": len(recipients), "issued": len(tasks),
                  "missing": len(set(recipients) - counts.keys()),
                  "unexpected": len(counts.keys() - set(recipients)),
                  "duplicates": len(tasks) - len(counts)}
        occurrences.append(record)
        problems.extend(f"{due.date()} {rule['name']}: {error}" for error in errors)
    # Ignore legitimate next-day work arriving during final validation grace.
    # Also test the reverse direction: unplanned receipts/tasks within the window.
    clocks = {r["id"]: datetime.fromtimestamp(r["first"], ZONE).time() for r in manifest["rules"]}
    for rid, day in (runs.keys() | by_day.keys()) - expected_keys:
        if rid not in clocks or datetime.combine(date.fromisoformat(day), clocks[rid], ZONE).timestamp() <= end:
            problems.append("unexpected schedule/day")
    return {"ok": not problems, "receipts": sum(row["delay_s"] is not None for row in occurrences),
            "expected_runs": len(occurrences), "expected_tasks": sum(row["expected"] for row in occurrences),
            "issued_tasks": sum(row["issued"] for row in occurrences), "occurrences": occurrences,
            "errors": problems}


def cold_check(packet, key, manifest, point):
    """Authenticate/decrypt and inspect the independently restored business data."""
    if hash_file(packet) != point["digest"] or packet.stat().st_size != point["bytes"]:
        raise ValueError("packet digest or size disagrees with catalog")
    with TemporaryDirectory(prefix="soak-cold-restore-") as tmp:
        target = Path(tmp) / "cold.sqlite3"
        info = secure_storage.restore_snapshot(packet, target, key)
        with closing(secure_storage.open_database(target, secure_storage.read_key(key))) as db:
            state = json.loads(db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0])
            residents = {p["id"]: p["bedId"] for p in state["residents"] if p["status"] == "在住"}
            occupied = {b["residentId"]: b["id"] for b in state["beds"] if b.get("residentId")}
            if (point["revision"] != info["revision"] or len(state["beds"]) != manifest["beds"]
                    or set(occupied) != set(manifest["resident_ids"]) or occupied != residents):
                raise ValueError("restored census or revision mismatch")
            if {r[0] for r in db.execute("SELECT id FROM scheduled_work_rules")} != {r["id"] for r in manifest["rules"]}:
                raise ValueError("restored schedule definitions differ from fixture")
            # The worker marks the slot's capture time before copying the database.
            # Require receipts already due for a full worker cycle. Also check that
            # newer receipts contained in the same consistent snapshot have all tasks.
            events = check_work(db, state, manifest, point["captured"] - 60)
            if not events["ok"]:
                raise ValueError("restored work inconsistent: " + ", ".join(events["errors"][:2]))
            restored_runs = db.execute("SELECT id,count FROM scheduled_work_runs").fetchall()
            totals = Counter(t["occurrenceId"] for t in state["tasks"] if t.get("scheduleId"))
            if totals != Counter({r["id"]: r["count"] for r in restored_runs}):
                raise ValueError("restored task counts do not match occurrence receipts")
    return {"revision": info["revision"], "occupied": len(occupied), "beds": len(state["beds"]),
            "verified_receipts": len(restored_runs), "verified_tasks": sum(totals.values())}


def verify_schedule(db_path, manifest, start_epoch, end_epoch, *, restore=True):
    """Compare live receipts against real calendar deadlines. Never create a backup."""
    db_path = Path(db_path)
    key = secure_storage.key_location(db_path)
    if end_epoch < start_epoch:
        raise ValueError("end precedes start")
    first_day = datetime.fromtimestamp(start_epoch, ZONE).date()
    final_day = datetime.fromtimestamp(end_epoch, ZONE).date()
    with closing(secure_storage.open_database(db_path, secure_storage.read_key(key))) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        state = json.loads(db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0])
        work = check_work(db, state, manifest, end_epoch)
        catalog = {r["request"]: dict(r) for r in db.execute("SELECT * FROM backup_points")}
    backups, problems = [], []
    if any(not name.startswith("slot:") for name in catalog):
        problems.append("unexpected backup/repair record")
    folder = db_path.parent / (db_path.name + ".snapshots")
    for offset in range((final_day - first_day).days + 1):
        day = first_day + offset * DAY
        slot = int(datetime.combine(day, time.min, ZONE).timestamp())
        point = catalog.get(f"slot:{slot}")
        item = {"day": day.isoformat(), "state": point["state"] if point else "missing"}
        backups.append(item)
        if not point or point["state"] != "ready" or not point["captured"]:
            problems.append(f"{day}: scheduled backup unavailable")
            continue
        delay = max(0, point["captured"] - max(start_epoch, slot))
        item.update(bytes=point["bytes"], attempts=point["attempts"], captured=point["captured"],
                    revision=point["revision"], delay_s=round(delay, 2))
        if point["captured"] < slot or delay > 60:
            problems.append(f"{day}: capture outside expected 60 second window")
        if restore:
            try:
                item["restored"] = cold_check(folder / (point["id"] + ".akbak"), key, manifest, point)
            except Exception as error:
                problems.append(f"{day}: restore failed ({type(error).__name__}: {error})")
    return {"ok": work["ok"] and not problems, "work": work, "backups": backups,
            "restore_verified": restore and not problems, "backup_errors": problems}
