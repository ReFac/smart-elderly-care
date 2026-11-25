"""Institution-configured civil-affairs filing checklist and immutable supporting originals."""

from contextlib import closing
from datetime import timedelta
import json
from uuid import uuid4

from .. import access, activity, campus_access, care_areas, dossier
from .dispatch import unrestricted
from .records import month_bounds, parse_day

KINDS = {
    "idFront": "身份证正面",
    "idBack": "身份证反面",
    "household": "户口本",
    "invoice": "发票",
}
DEFAULT = {"minimumDays": 30, "invoiceMonths": 1}
ACTIONS = ("ops.subsidyRules", "ops.subsidyMaterial", "ops.subsidyList")


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS subsidy_policy (
        id INTEGER PRIMARY KEY CHECK(id=1), minimum_days INTEGER NOT NULL, invoice_months INTEGER NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS subsidy_materials (
        id TEXT PRIMARY KEY, resident_id TEXT NOT NULL, kind TEXT NOT NULL, month TEXT NOT NULL,
        name TEXT NOT NULL, mime TEXT NOT NULL, digest TEXT NOT NULL, original BLOB NOT NULL,
        at TEXT NOT NULL, actor TEXT NOT NULL)""")
    db.execute(
        "CREATE INDEX IF NOT EXISTS subsidy_material_by_person ON subsidy_materials(resident_id,kind,month)"
    )
    db.execute("""CREATE TABLE IF NOT EXISTS subsidy_claims (
        id TEXT PRIMARY KEY, batch TEXT NOT NULL, month TEXT NOT NULL, resident_id TEXT NOT NULL,
        snapshot TEXT NOT NULL, at TEXT NOT NULL, actor TEXT NOT NULL, UNIQUE(month,resident_id))""")
    for table in ("subsidy_materials", "subsidy_claims"):
        for operation in ("UPDATE", "DELETE"):
            db.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_no_{operation}
                BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, '已留存的申报原件和清单不可改写'); END""")


def policy(db):
    row = db.execute(
        "SELECT minimum_days,invoice_months FROM subsidy_policy WHERE id=1"
    ).fetchone()
    return {"minimumDays": row[0], "invoiceMonths": row[1]} if row else DEFAULT.copy()


def invoice_months(first, count, admitted):
    months = []
    month = first
    for _ in range(count):
        end = month - timedelta(days=1)
        if end < admitted:
            break
        months.append(end.isoformat()[:7])
        month = end.replace(day=1)
    return sorted(months)


def registry(db, state, user, month, today):
    access.require(user, "finance")
    first, last = month_bounds(month, today)
    last = min(last, parse_day(today))
    rules = policy(db)
    allowed = campus_access.allowed_beds(db, user, include_rooms=True)
    people = (
        campus_access.resident_ids(state, allowed, user)
        if allowed is not None
        else None
    )
    docs = {}
    columns = "id,resident_id,kind,month,name,mime,digest,at,actor"
    scope = "resident_id IN (SELECT value FROM json_each(?))"
    args = () if people is None else (json.dumps(list(people)),)
    scope_where = " WHERE " + scope if people is not None else ""
    documents_sql = (
        "SELECT " + columns + " FROM subsidy_materials WHERE rowid IN "
        "(SELECT max(rowid) FROM subsidy_materials"
        + scope_where
        + " GROUP BY resident_id,kind,month)"
    )
    for doc in db.execute(documents_sql, args):
        docs.setdefault(doc["resident_id"], {})[(doc["kind"], doc["month"])] = dict(doc)
    scope_and = " AND " + scope if people is not None else ""
    prior = {
        r[0]
        for r in db.execute(
            "SELECT DISTINCT resident_id FROM subsidy_claims WHERE month<?" + scope_and,
            (month, *args),
        )
    }
    filed = {}
    claim_sql = (
        "SELECT resident_id,batch,snapshot,at,actor FROM subsidy_claims WHERE month=?"
    )
    for claim in db.execute(claim_sql + scope_and, (month, *args)):
        filed[claim["resident_id"]] = {
            "batch": claim["batch"],
            "at": claim["at"],
            "actor": claim["actor"],
            "record": json.loads(claim["snapshot"]),
        }
    bed_ids = {b["id"] for b in state["beds"] if allowed is None or b["id"] in allowed}
    locations = care_areas.bed_directory(db, bed_ids)
    labels = {b["id"]: b["label"] for b in state["beds"] if b["id"] in bed_ids}
    recent_beds = {}
    for move in state.get("bedMoves", ()):
        rid = move["residentId"]
        day = move.get("date", "")
        if day <= last.isoformat() and day >= recent_beds.get(rid, ("", ""))[0]:
            recent_beds[rid] = (day, move.get("bedId") or move.get("beforeBedId"))
    rows = []
    for p in state["residents"]:
        rid = p["id"]
        if people is not None and rid not in people:
            continue
        if rid in filed:
            claim = filed.pop(rid)
            rows.append({**claim.pop("record"), "claim": claim})
            continue
        if (
            p.get("stayType") == "trial"
            or not p.get("admittedAt")
            or p.get("status") not in ("在住", "已退住")
        ):
            continue
        admitted = parse_day(p.get("formalizedAt") or p["admittedAt"])
        eligible = admitted + timedelta(days=rules["minimumDays"] - 1)
        if eligible > last or (
            p.get("dischargedAt")
            and p["dischargedAt"] < max(first, eligible).isoformat()
        ):
            continue
        invoices = invoice_months(first, rules["invoiceMonths"], admitted)
        documents = docs.get(rid, {})
        required = [(kind, "") for kind in ("idFront", "idBack", "household")] + [
            ("invoice", m) for m in invoices
        ]
        material = [documents[k] for k in required if k in documents]
        missing = [
            KINDS[kind] + (" " + m if m else "")
            for kind, m in required
            if (kind, m) not in documents
        ]
        bed_id = recent_beds.get(rid, ("", p.get("bedId")))[1]
        location = locations.get(bed_id, {})
        rows.append(
            {
                "residentId": rid,
                "name": p["name"],
                "admitted": admitted.isoformat(),
                "eligibleMonth": eligible.isoformat()[:7],
                "campus": location.get("campusName", ""),
                "building": location.get("buildingName", ""),
                "floor": location.get("floorLabel", ""),
                "room": location.get("roomNumber", ""),
                "bed": labels.get(bed_id, ""),
                "buildingId": location.get("buildingId", ""),
                "floorId": location.get("floorId", ""),
                "roomId": location.get("roomId", ""),
                "type": "续报" if rid in prior else "首次申报",
                "materials": material,
                "invoiceMonths": invoices,
                "missing": missing,
                "claim": None,
            }
        )
    # Retain signed-off records when the live resident folder is subsequently archived.
    for claim in filed.values():
        rows.append({**claim.pop("record"), "claim": claim})
    return {
        "rows": rows,
        "rules": rules,
        "canConfigure": unrestricted(user),
        "month": month,
    }


def read(store, token, month):
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        user = store.actor(db, token)
        access.require(user, "finance")
        record = db.execute(
            "SELECT data, revision FROM workspace WHERE id=1"
        ).fetchone()
        today = store.now().date().isoformat()
        return {
            **registry(db, json.loads(record[0]), user, month or today[:7], today),
            "revision": record[1],
        }


def original(store, token, document_id):
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        user = store.actor(db, token)
        access.require(user, "finance")
        meta = db.execute(
            "SELECT resident_id,mime FROM subsidy_materials WHERE id=?", (document_id,)
        ).fetchone()
        if not meta:
            raise ValueError("找不到材料原件")
        campus_access.require_resident(db, user, meta[0])
        revision = db.execute(
            "UPDATE workspace SET revision=revision+1 WHERE id=1 RETURNING revision"
        ).fetchone()[0]
        activity.write(
            db,
            revision,
            store.now().isoformat(timespec="seconds"),
            "ops.readSubsidyMaterial",
            "查阅补贴申报原件",
            user,
            {"residentId": meta[0]},
            {},
        )
        binary = db.execute(
            "SELECT original FROM subsidy_materials WHERE id=?", (document_id,)
        ).fetchone()[0]
        return binary, meta[1]


def command(db, state, user, action, p, now):
    access.require(user, "finance")
    day = now.date().isoformat()
    at = now.isoformat(timespec="seconds")
    if action == "ops.subsidyRules":
        if not unrestricted(user):
            raise PermissionError("请由全院财务负责人设置机构申报规则")
        days, months = p.get("minimumDays"), p.get("invoiceMonths")
        if (
            type(days) is not int
            or not 1 <= days <= 365
            or type(months) is not int
            or not 0 <= months <= 12
        ):
            raise ValueError("入住天数限 1–365；需核对的前期发票限 0–12 个月")
        db.execute(
            "INSERT OR REPLACE INTO subsidy_policy VALUES(1,?,?)", (days, months)
        )
        return f"更新补贴备料规则：满 {days} 日，核对前 {months} 个月发票"
    month = p.get("month")
    data = registry(db, state, user, month, day)
    rows = {r["residentId"]: r for r in data["rows"]}
    if action == "ops.subsidyMaterial":
        rid, kind = p.get("residentId"), p.get("kind")
        if (
            not isinstance(rid, str)
            or rid not in rows
            or not isinstance(kind, str)
            or kind not in KINDS
        ):
            raise ValueError("请选择已获授权且符合本期规则的长辈与材料类型")
        if rows[rid]["claim"]:
            raise ValueError("该长辈本期清单已经生成")
        invoice = p.get("invoiceMonth", "")
        if (kind == "invoice" and invoice not in rows[rid]["invoiceMonths"]) or (
            kind != "invoice" and invoice
        ):
            raise ValueError("发票月份不属于此期备料范围")
        name = p.get("fileName")
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= 120
            or any(ord(c) < 32 or c in "/\\" for c in name)
        ):
            raise ValueError("原件名称无效")
        raw, mime, digest = dossier.photo_payload(p, allow_pdf=True)
        if not raw:
            raise ValueError("请选择 PDF、JPEG 或 PNG 原件")
        if any(
            m["kind"] == kind
            and m["month"] == invoice
            and m["name"] == name
            and m["digest"] == digest
            for m in rows[rid]["materials"]
        ):
            return "已留存相同原件，本次沿用当前版本"
        if mime == "application/pdf":
            from .. import pdf_original

            pdf_original.pages(raw)
        db.execute(
            "INSERT INTO subsidy_materials VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                uuid4().hex,
                rid,
                kind,
                invoice,
                name,
                mime,
                digest,
                raw,
                at,
                user["displayName"],
            ),
        )
        return f"留存 {rows[rid]['name']} 的{KINDS[kind]}原件"
    ids = p.get("residentIds")
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= 1000
        or not all(isinstance(r, str) for r in ids)
    ):
        raise ValueError("请选择本期需生成清单的长辈，单批最多 1000 人")
    if len(ids) != len(set(ids)) or any(
        r not in rows or rows[r]["missing"] or rows[r]["claim"] for r in ids
    ):
        raise ValueError("包含重复、未获授权、材料不齐或已列入本期清单的长辈")
    batch = uuid4().hex
    for rid in ids:
        snapshot = {**rows[rid], "rules": data["rules"]}
        db.execute(
            "INSERT INTO subsidy_claims VALUES(?,?,?,?,?,?,?)",
            (
                uuid4().hex,
                batch,
                month,
                rid,
                json.dumps(snapshot, ensure_ascii=False),
                at,
                user["displayName"],
            ),
        )
    return f"生成 {month} 民政补贴申报材料清单（{len(ids)} 人，批次 {batch[:8]}）"
