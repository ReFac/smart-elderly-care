"""Issue cards for imported residents with reciprocal beds and no allocation ledger."""

import json

from .residency import ean8


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS legacy_bed_cards(
        id INTEGER PRIMARY KEY AUTOINCREMENT CHECK(id BETWEEN 1 AND 999999),
        resident_id TEXT NOT NULL, bed_id TEXT NOT NULL,
        recorded_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        source TEXT NOT NULL DEFAULT '系统根据历史在住档案和床位双向一致补发',
        UNIQUE(resident_id,bed_id))""")
    for verb in ("UPDATE", "DELETE"):
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS legacy_bed_cards_no_{verb}
            BEFORE {verb} ON legacy_bed_cards BEGIN SELECT RAISE(ABORT,'历史补卡凭证须保留'); END""")
    backfill(db)


def backfill(db):
    raw = db.execute("SELECT data FROM workspace WHERE id=1").fetchone()
    if not raw:
        return
    state = json.loads(raw[0])
    movements = {m["residentId"] for m in state.get("bedMoves", ())}
    occupants = {b["id"]: b.get("residentId") for b in state.get("beds", ())}
    changed = False
    for person in state.get("residents", ()):
        rid, bed = person["id"], person.get("bedId")
        if (
            person.get("status") != "在住"
            or rid in movements
            or not bed
            or occupants.get(bed) != rid
        ):
            continue
        registered = db.execute(
            "SELECT id FROM legacy_bed_cards WHERE resident_id=? AND bed_id=?",
            (rid, bed),
        ).fetchone()
        if not registered:
            sequence = db.execute(
                "INSERT INTO legacy_bed_cards(resident_id,bed_id) VALUES(?,?)",
                (rid, bed),
            ).lastrowid
        else:
            sequence = registered[0]
        # 1xxxxxx is reserved for verified historical allocations. Movement cards start at 2000001.
        card = {"bedId": bed, "code": ean8(1000000 + sequence)}
        if person.get("legacyBedCard") != card:
            person["legacyBedCard"] = card
            changed = True
    if changed:
        db.execute(
            "UPDATE workspace SET data=? WHERE id=1",
            (json.dumps(state, ensure_ascii=False, separators=(",", ":")),),
        )
