"""Capture only rows touched on this transaction's connection. Never duplicate binary originals or credentials."""

import json

RETENTION_DAYS = 60
WINDOW = RETENTION_DAYS * 86400

# Physical tables belonging to business domains. Unknown infrastructure tables are private by default.
PREFIXES = {
    "facility": ("facility_",),
    "dossier": ("dossier_",),
    "access": (
        "accounts",
        "institution_settings",
        "media_policy",
        "family_round_preferences",
        "staff_contract_versions",
        "staff_paydays",
    ),
    "family": ("family_round_",),
    "account": ("accounts",),
    "agent": ("agent_",),
    "rounds": (
        "rounds_policy",
        "rounds_modes",
        "rounds_observations",
        "rounds_reports",
        "rounds_staff_inbox",
        "rounds_priorities",
        "family_round_messages",
    ),
    "gw": ("gateway_",),
    "backup": ("backup_",),
    "platform": ("api_", "media_"),
    "media": ("media_usage",),
    "document": ("protected_documents",),
    "storage": ("storage_assets",),
}
SECRET = {
    "password",
    "salt",
    "password_hash",
    "token_hash",
    "lease",
    "token",
    "key",
    "download_token",
}
JSON_COLUMNS = {
    "visual",
    "config",
    "items",
    "issuedRooms",
    "basic",
    "household",
    "details",
    "metadata",
    "permissions",
    "portal_scopes",
    "result",
    "review",
    "args",
    "snapshot",
    "artifacts",
    "candidates",
    "specialistIds",
}
BINARY = {"original", "data", "packet"}
MISSING = object()


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def literal(value):
    return "'" + value.replace("'", "''") + "'"


def watch(db, action):
    """Start an in-memory row journal inside the caller's write transaction."""
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='history_commits'"
    ).fetchone():
        return
    db.execute(
        "CREATE TEMP TABLE IF NOT EXISTS history_capture(tbl TEXT, ident TEXT, was TEXT, became TEXT)"
    )
    db.execute("DELETE FROM temp.history_capture")
    # The shell used for an offline plan grant has no workspace at all on a blank DB.
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='workspace'").fetchone():
        db.execute("""CREATE TEMP TRIGGER IF NOT EXISTS history_state AFTER UPDATE OF data ON main.workspace
            WHEN OLD.data IS NOT NEW.data BEGIN
            INSERT INTO history_capture VALUES('workspace','1',OLD.data,NEW.data); END""")
    prefixes = PREFIXES.get(action.partition(".")[0], ())
    if action in ("care.proposeGroupActivity", "care.confirmGroupActivity", "care.confirmScheduledMeal"):
        prefixes = ("daily_life_",)
    if action in ("care.saveSchedule", "care.setScheduleEnabled", "care.scheduleMenu", "care.releaseSchedules"):
        prefixes = ("scheduled_work_",)
    if action == "care.confirmMedRound":
        prefixes = ("medication_round_receipts",)
    if action in ("care.healthNote", "dossier.signHealthIntro"):
        prefixes = ("resident_health_notes",)
    if action in ("care.reportMedication", "portal.reportMedication"):
        prefixes = ("resident_medication_reports",)
    if action in ("backup.apply", "history.undo"):
        prefixes = (*tuple(k for group in PREFIXES.values() for k in group), "daily_life_", "resident_health_notes", "resident_medication_reports", "medication_round_receipts", "legacy_bed_cards", "scheduled_work_")
    if not prefixes:
        return
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        if table == "backup_exports" or not table.startswith(prefixes):
            continue
        fields = list(db.execute("PRAGMA table_info(" + quote(table) + ")"))
        keys = sorted((f for f in fields if f[5]), key=lambda f: f[5])
        if not keys:
            continue

        def col(alias, field):
            name = field[1]
            value = alias + "." + quote(name)
            if name in BINARY:
                return "length(" + value + ")"
            if field[2].upper() == "BLOB":
                return "hex(" + value + ")"
            return value

        def image(alias):
            pairs = []
            for f in fields:
                if f[1] not in SECRET:
                    name = f[1] + "Bytes" if f[1] in BINARY else f[1]
                    pairs.extend((literal(name), col(alias, f)))
            return "json_object(" + ",".join(pairs) + ")"

        for op, old, new, alias in [
            ("INSERT", "NULL", image("NEW"), "NEW"),
            ("UPDATE", image("OLD"), image("NEW"), "NEW"),
            ("DELETE", image("OLD"), "NULL", "OLD"),
        ]:
            keyparts = [col(alias, f) for f in keys]
            ident = (
                keyparts[0]
                if len(keyparts) == 1
                else "json_array(" + ",".join(keyparts) + ")"
            )
            name = quote("history_" + table + "_" + op)
            db.execute(f"""CREATE TEMP TRIGGER IF NOT EXISTS {name} AFTER {op} ON main.{quote(table)}
                       BEGIN INSERT INTO history_capture VALUES({literal(table)},{ident},{old},{new}); END""")


def normalize(row):
    if row is None:
        return None
    parsed = json.loads(row)
    for field in parsed.keys() & JSON_COLUMNS:
        if isinstance(parsed[field], str):
            try:
                parsed[field] = json.loads(parsed[field])
            except ValueError:
                pass
    return parsed


def fields(collection, identity, before, after, path=()):
    if before == after:
        return
    if isinstance(before, dict) and isinstance(after, dict):
        for field in sorted(before.keys() | after.keys()):
            yield from fields(
                collection,
                identity,
                before.get(field, MISSING),
                after.get(field, MISSING),
                (*path, field),
            )
        return
    item = {
        "collection": collection,
        "entityId": str(identity),
        "path": list(path),
        "kind": "add"
        if before is MISSING
        else "remove"
        if after is MISSING
        else "edit",
    }
    if before is not MISSING:
        item["before"] = before
    if after is not MISSING:
        item["after"] = after
    yield item


def keyed(rows):
    if not isinstance(rows, list) or any(
        not isinstance(r, dict) or "id" not in r for r in rows
    ):
        return None
    index = {str(r["id"]): r for r in rows}
    return index if len(index) == len(rows) else None


def collect(db, current, previous):
    people = {s.get("residentId") for s in (current, previous)} - {None, ""}
    rooms = {s.get("roomId") for s in (current, previous)} - {None, ""}
    changes = []
    campuses = {s.get("campusId") for s in (current, previous)} - {None, ""}
    for scope in (current, previous):
        rooms.update(scope.get("roomIds", ()))
    captured = db.execute(
        "SELECT 1 FROM sqlite_temp_master WHERE name='history_capture'"
    ).fetchone()
    maps = {}
    states = []

    def targets(collection, identity, source):
        if not isinstance(source, dict):
            return
        if collection == "residents":
            people.add(identity)
        if collection == "facility_rooms":
            rooms.add(identity)
        if collection == "medication_round_receipts" and isinstance(source.get("details"), dict):
            people.add(source["details"]["residentId"])
            rooms.add(source["details"]["roomId"])
        if collection == "daily_life_signatures" and source.get("eventId"):
            # Signing may occur after the original registration or after a move.
            # Keep the actual event rooms even if nobody was marked present.
            for campus, room in db.execute(
                """SELECT DISTINCT e.campusId,i.roomId FROM daily_life_events e
                JOIN daily_life_invitees i ON i.eventId=e.id WHERE e.id=?""",
                (source["eventId"],),
            ):
                campuses.add(campus)
                rooms.add(room)
        for key in ("campusId", "campus_id"):
            if source.get(key):
                campuses.add(source[key])
        if collection == "agent_regions" and isinstance(source.get("snapshot"), dict):
            region = source["snapshot"]
            rooms.update(region.get("roomIds", ()))
            people.update(region.get("residentIds", ()))
            if region.get("campusId"):
                campuses.add(region["campusId"])
        if collection == "facility_campuses":
            campuses.add(identity)
        if collection == "gateway_alert":
            people.update(
                r for r in source.get("candidates", []) if isinstance(r, str) and r
            )
            if source.get("resident_hint"):
                people.add(source["resident_hint"])
        who = source.get("residentId") or source.get("resident_id")
        if who:
            people.add(who)
        for key in ("roomId", "room_id", "executionRoomId", "previousRoomId"):
            if source.get(key):
                rooms.add(source[key])
        for key in ("bedId", "bed_id", "beforeBedId", "afterBedId", "executionBedId"):
            if source.get(key):
                maps[source[key]] = None

    def record(collection, identity, old, new):
        targets(collection, identity, old)
        targets(collection, identity, new)
        if (
            collection == "dossier_profiles"
            and old is MISSING
            and isinstance(new, dict)
        ):
            # Keep the physical insertion known while allowing a later change to a different profile field.
            empty = {"resident_id": identity, "basic": {}, "household": {}}
            if new != empty:
                changes.extend(
                    {**c, "createdRow": True}
                    for c in fields(collection, identity, empty, new)
                )
                return
        changes.extend(fields(collection, identity, old, new))

    if captured:
        # Collapse multiple writes to one row in the same command to its net change.
        touched = {}
        for table, identity, was, became in db.execute(
            "SELECT * FROM temp.history_capture ORDER BY rowid"
        ):
            key = (table, identity)
            touched[key] = (touched[key][0] if key in touched else was, became)
        for (table, identity), (was, became) in touched.items():
            if table == "workspace":
                old, new = json.loads(was), json.loads(became)
                states.extend((old, new))
                for collection in sorted(old.keys() | new.keys()):
                    if old.get(collection) == new.get(collection):
                        continue
                    a, b = (
                        keyed(old.get(collection, [])),
                        keyed(new.get(collection, [])),
                    )
                    if a is None or b is None:
                        record(
                            collection,
                            "",
                            old.get(collection, MISSING),
                            new.get(collection, MISSING),
                        )
                        continue
                    positions = (
                        {key: n for n, key in enumerate(a)},
                        {key: n for n, key in enumerate(b)},
                    )
                    for key in sorted(a.keys() | b.keys()):
                        if a.get(key) != b.get(key):
                            record(
                                collection,
                                key,
                                a.get(key, MISSING),
                                b.get(key, MISSING),
                            )
                            if key not in a:
                                changes[-1]["afterIndex"] = positions[1][key]
                            elif key not in b:
                                changes[-1]["beforeIndex"] = positions[0][key]
                    # Order is relevant for priority lists and exports with no row value changes.
                    common = a.keys() & b.keys()
                    if [k for k in a if k in common] != [k for k in b if k in common]:
                        changes.append(
                            {
                                "collection": collection,
                                "entityId": "",
                                "path": [],
                                "kind": "order",
                                "before": list(a),
                                "after": list(b),
                            }
                        )
            elif was != became:
                record(
                    table,
                    identity,
                    normalize(was) if was is not None else MISSING,
                    normalize(became) if became is not None else MISSING,
                )
    if people and not states:
        row = db.execute("SELECT data FROM workspace WHERE id=1").fetchone()
        if row:
            states = [json.loads(row[0])]
    for state in states:
        for resident in state.get("residents", ()):
            if resident.get("id") in people and resident.get("bedId"):
                maps[resident["bedId"]] = None
    if maps:
        rooms.update(
            r[0]
            for r in db.execute(
                "SELECT DISTINCT roomId FROM facility_beds WHERE bedId IN (SELECT value FROM json_each(?))",
                (dump(list(maps)),),
            )
        )
    return changes, sorted(people), sorted(rooms), sorted(campuses)
