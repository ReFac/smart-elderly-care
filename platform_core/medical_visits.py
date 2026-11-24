"""Prepare one resident's encounter and atomically sign the reviewed chart entry."""

from contextlib import closing
from hashlib import sha256
import json
import re
from uuid import uuid4

from . import access, campus_access, dossier, pdf_original
from .care import archive_retention
from .care.records import lookup
from . import visit_extraction

MAX_FILES = 12
MAX_BYTES = 24 * 1024 * 1024
CATEGORIES = ("就诊记录", "CT影像", "检查报告", "处方", "医嘱", "其他")
FIELDS = {
    "eventDate": 10,
    "facility": 200,
    "department": 200,
    "reason": 4000,
    "diagnosis": 4000,
    "historyMeds": 4000,
    "prescriptions": 4000,
    "tests": 4000,
    "orders": 4000,
    "followUp": 4000,
}


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS dossier_visit_originals(
        id TEXT PRIMARY KEY, resident_id TEXT NOT NULL, image_hash TEXT NOT NULL,
        original BLOB NOT NULL, mime TEXT NOT NULL, UNIQUE(resident_id,image_hash))""")
    db.execute("""CREATE TABLE IF NOT EXISTS dossier_visit_drafts(
        id TEXT PRIMARY KEY, resident_id TEXT NOT NULL, actor TEXT NOT NULL, request TEXT NOT NULL,
        fingerprint TEXT NOT NULL, group_key TEXT NOT NULL, resident_name TEXT NOT NULL,
        mode TEXT NOT NULL, attachments TEXT NOT NULL, result TEXT, UNIQUE(actor,request))""")
    db.execute("""CREATE TABLE IF NOT EXISTS dossier_visit_records(
        id TEXT PRIMARY KEY, resident_id TEXT NOT NULL, group_key TEXT NOT NULL,
        metadata TEXT NOT NULL, UNIQUE(resident_id,group_key))""")
    for table in ("dossier_visit_originals", "dossier_visit_records"):
        for op in ("UPDATE", "DELETE"):
            db.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_no_{op} BEFORE {op}
                ON {table} BEGIN SELECT RAISE(ABORT,'就诊原件及签认记录不可覆盖'); END""")


def _fields(raw, today, *, date_required=False, signed=False):
    if not isinstance(raw, dict) or raw.keys() - FIELDS.keys():
        raise ValueError("请核对就诊记录的结构字段")
    fields = {k: dossier.text(raw, k, size) for k, size in FIELDS.items()}
    if date_required or fields["eventDate"]:
        dossier.calendar_day(fields["eventDate"], "就诊日期", today)
    if signed and not any(
        fields[k] for k in FIELDS if k not in ("eventDate", "facility", "department")
    ):
        raise ValueError("请至少核对并填写一项就诊经过、用药、检查或医嘱")
    return fields


def _authorize(state, db, actor, rid):
    if actor["kind"] not in ("staff", "owner"):
        raise PermissionError("仅在岗医疗档案经办人可整理就诊资料")
    for permission in ("medical", "medical.write", "clinical"):
        access.require(actor, permission)
    campus_access.require_resident(db, actor, rid, state)
    return archive_retention.writable(state, rid)


def _session(store, db, token, rid):
    actor = store.actor(db, token)
    row = db.execute("SELECT data,revision FROM workspace WHERE id=1").fetchone()
    person = _authorize(json.loads(row[0]), db, actor, rid)
    return actor, person["name"], row[1]


def _attachments(items, mode):
    if (
        not isinstance(items, list)
        or len(items) > MAX_FILES
        or (mode == "ai" and not items)
    ):
        raise ValueError("一次只能整理同一位长者的一组就诊资料，最多 12 份")
    files, seen, size = [], set(), 0
    for item in items:
        if not isinstance(item, dict) or item.keys() != {
            "category",
            "filename",
            "mime",
            "imageBase64",
        }:
            raise ValueError("请逐份选择原件和文书类型")
        if item["category"] not in CATEGORIES:
            raise ValueError("请选择有效的就诊附件类型")
        filename = dossier.text(item, "filename", 200, True)
        raw, mime, digest = dossier.photo_payload(item, allow_pdf=True)
        if not raw or not mime or not digest:
            raise ValueError("请提供完整就诊原件")
        if digest in seen:
            raise ValueError("同一组就诊资料中有重复原件，请保留一份")
        seen.add(digest)
        size += len(raw)
        if size > MAX_BYTES:
            raise ValueError("每组就诊原件合计最多 24 MiB")
        count = pdf_original.pages(raw) if mime == "application/pdf" else 1
        files.append(
            (
                raw,
                digest,
                {
                    "filename": filename,
                    "category": item["category"],
                    "mime": mime,
                    "bytes": len(raw),
                    "pageCount": count,
                },
            )
        )
    return files


def _digest(value):
    return sha256(dossier.pack(value).encode()).hexdigest()


def _stage(db, rid, actor, request, name, mode, fields, files):
    signature = _digest(
        [rid, mode, fields, [(digest, meta) for _, digest, meta in files]]
    )
    old = db.execute(
        "SELECT * FROM dossier_visit_drafts WHERE actor=? AND request=?",
        (actor, request),
    ).fetchone()
    if old:
        if old["fingerprint"] != signature or old["resident_name"] != name:
            raise ValueError(
                "本组资料已绑定其他内容或姓名已更正，请重新选取本次就诊资料"
            )
        return old
    manifest = []
    for raw, digest, meta in files:
        did = uuid4().hex
        db.execute(
            """INSERT INTO dossier_visit_originals(id,resident_id,image_hash,original,mime)
            VALUES(?,?,?,?,?) ON CONFLICT(resident_id,image_hash) DO NOTHING""",
            (did, rid, digest, raw, meta["mime"]),
        )
        (did,) = db.execute(
            "SELECT id FROM dossier_visit_originals WHERE resident_id=? AND image_hash=?",
            (rid, digest),
        ).fetchone()
        manifest.append({**meta, "id": did})
    key = (
        _digest(sorted(item["id"] for item in manifest))
        if files
        else _digest([actor, request])
    )
    if db.execute(
        "SELECT 1 FROM dossier_visit_records WHERE resident_id=? AND group_key=?",
        (rid, key),
    ).fetchone():
        raise ValueError("这组就诊资料已经签认，请查看档案中的既有病例")
    did = uuid4().hex
    db.execute(
        """INSERT INTO dossier_visit_drafts
        (id,resident_id,actor,request,fingerprint,group_key,resident_name,mode,attachments)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        (did, rid, actor, request, signature, key, name, mode, dossier.pack(manifest)),
    )
    return db.execute(
        "SELECT * FROM dossier_visit_drafts WHERE id=?", (did,)
    ).fetchone()


def preview(store, token, rid, p):
    """Keep originals before cloud OCR. A draft is visible only to its operator."""
    from .store import Conflict

    if not isinstance(p, dict) or p.keys() - {
        "mode",
        "attachments",
        "fields",
        "requestId",
        "consent",
        "revision",
    }:
        raise ValueError("请核对本组就诊资料")
    mode = p.get("mode")
    if mode not in ("ai", "manual") or (mode == "ai" and p.get("consent") is not True):
        raise ValueError("请确认将一位长者同一次就诊的资料提交 DeepSeek 整理")
    request = dossier.text(p, "requestId", 100, True)
    if not re.fullmatch(r"[a-zA-Z0-9._-]{1,100}", request):
        raise ValueError("就诊请求编号无效")
    with closing(store.connect()) as db:
        _session(store, db, token, rid)
    today = store.now().date().isoformat()
    fields = _fields(p.get("fields", {}), today, date_required=mode == "manual")
    files = _attachments(p.get("attachments", []), mode)
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        actor, name, revision = _session(store, db, token, rid)
        if type(p.get("revision")) is not int or p["revision"] != revision:
            raise Conflict("档案已更新，请重新核对所选长者后继续")
        draft = _stage(db, rid, actor["id"], request, name, mode, fields, files)
    manifest = json.loads(draft["attachments"])
    did = draft["id"]
    if not draft["result"]:

        def authorize(db, session):
            user, current_name, _ = _session(store, db, session, rid)
            if user["id"] != actor["id"] or current_name != name:
                raise PermissionError("经办人或长者身份发生变化，请重新核对")
            return user

        result = {
            "fields": fields,
            "warnings": [],
            "sourceRefs": {},
            "identityConflict": False,
        }
        if mode == "ai":
            result = visit_extraction.organize(
                store, token, actor["id"], rid, name, files, manifest, fields, authorize
            )
        with closing(store.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            authorize(db, token)
            db.execute(
                "UPDATE dossier_visit_drafts SET result=? WHERE id=? AND result IS NULL",
                (dossier.pack(result), did),
            )
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        actor, current_name, revision = _session(store, db, token, rid)
        if current_name != name:
            raise ValueError("长者姓名已更新，请重新核对本组资料")
        ready = db.execute(
            "SELECT result FROM dossier_visit_drafts WHERE id=? AND actor=?",
            (did, actor["id"]),
        ).fetchone()
        return {
            **json.loads(ready[0]),
            "draftId": did,
            "residentId": rid,
            "mode": mode,
            "attachments": manifest,
            "revision": revision,
        }


def confirm(db, state, p, user, now):
    if (
        not isinstance(p, dict)
        or set(p) != {"residentId", "draftId", "fields", "confirmed"}
        or p["confirmed"] is not True
    ):
        raise ValueError("请先核对本次就诊整理内容再确认添加病例")
    draft = db.execute(
        "SELECT * FROM dossier_visit_drafts WHERE id=? AND actor=? AND resident_id=?",
        (p["draftId"], user["id"], p["residentId"]),
    ).fetchone()
    if not draft or not draft["result"]:
        raise ValueError("本次就诊草稿未完成，或不属于此操作人")
    rid = draft["resident_id"]
    person = _authorize(state, db, user, rid)
    result = json.loads(draft["result"])
    if person["name"] != draft["resident_name"] or result["identityConflict"]:
        raise ValueError("就诊资料与所选长者或就诊时间不一致，请重新分组")
    fields = _fields(
        p["fields"], now.date().isoformat(), date_required=True, signed=True
    )
    prior = db.execute(
        "SELECT id,metadata FROM dossier_visit_records WHERE resident_id=? AND group_key=?",
        (rid, draft["group_key"]),
    ).fetchone()
    if prior:
        if prior[0] == draft["id"] and json.loads(prior[1])["fields"] == fields:
            return "这次就诊已经签认存档"
        raise ValueError("这组就诊资料已经签认，请查看档案中的既有病例")
    record = {
        "mode": draft["mode"],
        "fields": fields,
        "attachments": json.loads(draft["attachments"]),
        "sourceRefs": result["sourceRefs"],
        "reviewer": user["displayName"],
        "reviewerId": user["id"],
        "reviewerRole": user["role"],
        "recordedAt": now.isoformat(timespec="seconds"),
    }
    db.execute(
        "INSERT INTO dossier_visit_records VALUES(?,?,?,?)",
        (draft["id"], rid, draft["group_key"], dossier.pack(record)),
    )
    return "已将本次就诊病例签认并归入长者档案"


def project(db, data, user):
    data["medicalVisits"] = []
    if user["kind"] == "family" or not access.has(user, "medical"):
        return
    visible = [p["id"] for p in data.get("residents", ())]
    rows = db.execute(
        """SELECT id,resident_id,metadata FROM dossier_visit_records
        WHERE resident_id IN (SELECT value FROM json_each(?))
        ORDER BY json_extract(metadata,'$.fields.eventDate') DESC,rowid DESC""",
        (json.dumps(visible),),
    )
    data["medicalVisits"] = [
        {"id": did, "residentId": rid, **json.loads(meta)} for did, rid, meta in rows
    ]


def original(store, token, attachment_id):
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        actor = store.actor(db, token)
        access.require(actor, "medical")
        if actor["kind"] == "family":
            raise PermissionError("医疗原件需要工作人员的档案权限")
        row = db.execute(
            """SELECT o.resident_id FROM dossier_visit_originals o WHERE o.id=?
            AND EXISTS(SELECT 1 FROM dossier_visit_records r,json_each(r.metadata,'$.attachments') a
            WHERE r.resident_id=o.resident_id AND json_extract(a.value,'$.id')=o.id)""",
            (attachment_id,),
        ).fetchone()
        if not row:
            raise FileNotFoundError("找不到已签认的就诊原件")
        campus_access.require_resident(db, actor, row[0])
        state = json.loads(
            db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
        )
        if lookup(state, "residents", row[0])["status"] == archive_retention.EXPIRED:
            raise FileNotFoundError("档案已到期")
        return tuple(
            db.execute(
                "SELECT original,mime FROM dossier_visit_originals WHERE id=?",
                (attachment_id,),
            ).fetchone()
        )
