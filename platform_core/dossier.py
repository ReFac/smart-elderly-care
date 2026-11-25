"""长辈扩展档案、亲属自助和不可替换的医疗照片。写操作由 Store 的事务包裹。"""

import base64
import binascii
import hashlib
import json
import re
import struct
import uuid
import zlib
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import access, document_ocr, family_contacts, pdf_original, profile_fields
from .dossier_summary import sign_summary, summary_draft as summary_draft
from .care.clinical import refresh_medication_warnings
from .care.records import append_record, lookup

MAX_IMAGE = 8 * 1024 * 1024
BASIC = {
    "phone": 40,
    "birthDate": 10,
    "birthplace": 120,
    "nativePlace": 120,
    "address": 300,
    "occupation": 80,
    "education": 80,
    "language": 80,
    "maritalStatus": 40,
}
HOUSEHOLD = {
    "siblings": 500,
    "children": 500,
    "livingArrangement": 300,
    "incomeSource": 180,
    "economicNotes": 500,
}
KIN = {
    "name": 60,
    "relationship": 40,
    "phone": 40,
    "idNumber": 18,
    "address": 300,
    "wechat": 80,
    "email": 150,
    "emergencyNote": 300,
}
CATEGORIES = (
    "CT",
    "其他影像检查",
    "诊断记录",
    "检验报告",
    "出院小结",
    "病史补录",
    "其他医疗文书",
)
METHODS = ("手工描述", "人工核对的 OCR 转录", *document_ocr.STAGED)


def init(db):
    statements = (
        """CREATE TABLE IF NOT EXISTS dossier_profiles
           (resident_id TEXT PRIMARY KEY, basic TEXT NOT NULL, household TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS dossier_relatives
           (account_id TEXT PRIMARY KEY, resident_id TEXT NOT NULL, details TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS dossier_documents (
           id TEXT PRIMARY KEY, resident_id TEXT NOT NULL, request_id TEXT NOT NULL,
           fingerprint TEXT NOT NULL, event_date TEXT NOT NULL, recorded_date TEXT NOT NULL,
           metadata TEXT NOT NULL, mime TEXT, original BLOB, image_hash TEXT,
           UNIQUE(resident_id,request_id), UNIQUE(resident_id,image_hash),
           UNIQUE(resident_id,fingerprint))""",
        """CREATE INDEX IF NOT EXISTS dossier_document_original_digest ON dossier_documents(image_hash)""",
        """CREATE INDEX IF NOT EXISTS dossier_document_chronology
           ON dossier_documents(resident_id,event_date DESC)""",
        """CREATE TRIGGER IF NOT EXISTS dossier_document_no_delete BEFORE DELETE ON dossier_documents
           BEGIN SELECT RAISE(ABORT,'医疗原件和摘要不可删除'); END""",
        """CREATE TRIGGER IF NOT EXISTS dossier_document_no_update BEFORE UPDATE ON dossier_documents
           BEGIN SELECT RAISE(ABORT,'医疗原件和摘要不可覆盖'); END""",
    )
    for statement in statements:
        db.execute(statement)
    document_ocr.init(db)


def pack(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def text(payload, key, limit, required=False):
    value = payload.get(key, "")
    if (
        not isinstance(value, str)
        or len(value) > limit
        or any(ord(ch) < 32 and ch not in "\n\r\t" for ch in value)
    ):
        raise ValueError(f"{key} 格式或长度有误")
    value = value.strip()
    if required and not value:
        raise ValueError(f"必填字段 {key} 为空")
    return value


def calendar_day(value, label, today):
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value
    ):
        raise ValueError(f"{label}应填写年月日")
    try:
        day = date.fromisoformat(value)
    except ValueError as err:
        raise ValueError(f"{label}无效") from err
    if day > date.fromisoformat(today):
        raise ValueError(f"{label}不能晚于今天")
    return day


def years_old(birth, day):
    return day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day))


def edit_profile(db, state, p, user, today, *, temporary=False):
    if not temporary:
        access.require(user, "intake")
    resident = lookup(state, "residents", p.get("residentId"))
    name = text(p, "name", 60, True)
    existing = db.execute(
        "SELECT basic,household FROM dossier_profiles WHERE resident_id=?",
        (resident["id"],),
    ).fetchone()
    basic, household = (json.loads(x) for x in existing) if existing else ({}, {})
    basic.update(
        {
            k: text(p, k, v)
            for k, v in BASIC.items()
            if k in p
            and k not in ("language", "education", "maritalStatus", "occupation")
        }
    )
    if "phone" in p and basic["phone"]:
        normalized = profile_fields.phone_number(basic["phone"], mobile=True)
        if not normalized:
            raise ValueError("请核对长辈本人手机号；境外号码请填写国家区号")
        basic["phone"] = normalized
    if set(p) & HOUSEHOLD.keys():
        access.require(user, "relatives")
        household.update(
            {
                k: text(p, k, v)
                for k, v in HOUSEHOLD.items()
                if k in p and k != "livingArrangement"
            }
        )
    profile_fields.update_profile(basic, household, p, user)
    if "familyContact" in p:
        access.require(user, "relatives")
        family_contacts.update(household, p["familyContact"], today)
    age = p.get("age", resident.get("age"))
    if basic.get("birthDate"):
        age = years_old(
            calendar_day(basic["birthDate"], "出生日期", today),
            date.fromisoformat(today),
        )
    if age not in ("", None):
        if not re.fullmatch(r"[0-9]{1,3}", str(age)) or int(age) > 125:
            raise ValueError("年龄须在 0–125 岁范围内")
        age = int(age)
    else:
        age = None
    resident.update(name=name, age=age)
    db.execute(
        """INSERT INTO dossier_profiles VALUES(?,?,?) ON CONFLICT(resident_id)
               DO UPDATE SET basic=excluded.basic,household=excluded.household""",
        (resident["id"], pack(basic), pack(household)),
    )
    return f"更新长辈档案 {resident['id']} 的登记资料"


def masked(number):
    return number[:3] + "*" * 11 + number[-4:] if number else ""


def check_identity(value):
    if not value:
        return
    if not re.fullmatch(r"[0-9]{17}[0-9X]", value):
        raise ValueError("身份证号应为 18 位，末位可以是 X")
    weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    check = sum(int(d) * w for d, w in zip(value[:17], weights)) % 11
    if value[-1] != "10X98765432"[check]:
        raise ValueError("请核对身份证校验位")
    try:
        date.fromisoformat(value[6:10] + "-" + value[10:12] + "-" + value[12:14])
    except ValueError as err:
        raise ValueError("请核对身份证号码中的日期") from err


def edit_relative(db, state, p, user, today):
    if user["kind"] == "family":
        if (
            p.get("accountId", user["id"]) != user["id"]
            or p.get("residentId", user["residentId"]) != user["residentId"]
        ):
            raise PermissionError("仅可更新本人绑定的亲属资料")
        subject = user
    elif user["kind"] == "owner":
        subject = access.account(db, p.get("accountId"))
        if (
            not subject
            or subject["kind"] != "family"
            or not subject["residentId"]
            or subject.get("portalSelf")
            or not subject["enabled"]
        ):
            raise ValueError("请选择有效的已绑定亲属账号")
        if p.get("residentId", subject["residentId"]) != subject["residentId"]:
            raise ValueError("亲属绑定与长辈档案不一致")
    else:
        raise PermissionError("亲属资料由本人或 Owner 维护")
    resident = lookup(state, "residents", subject["residentId"])
    saved = db.execute(
        "SELECT details FROM dossier_relatives WHERE account_id=? AND resident_id=?",
        (subject["id"], resident["id"]),
    ).fetchone()
    values = json.loads(saved[0]) if saved else {}
    if "relationship" in p:
        profile_fields.enumeration(
            p,
            "relationship",
            profile_fields.catalog("dossier-choices")["relationship"],
            values.get("relationship", ""),
        )
    values.update({k: text(p, k, n) for k, n in KIN.items() if k in p})
    profile_fields.addresses(values, p, (("addressRegion", "address", False),))
    for key in ("name", "relationship", "phone"):
        text(values, key, KIN[key], True)
    if (
        not re.fullmatch(r"\+?[\d ()-]+", values["phone"])
        or not 5 <= sum(c.isdigit() for c in values["phone"]) <= 18
    ):
        raise ValueError("请核对联系电话")
    values["idNumber"] = values.get("idNumber", "").upper()
    check_identity(values["idNumber"])
    if values.get("email") and not re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+", values["email"]
    ):
        raise ValueError("请核对电子邮箱")
    db.execute(
        """INSERT INTO dossier_relatives VALUES(?,?,?) ON CONFLICT(account_id)
               DO UPDATE SET details=excluded.details,resident_id=excluded.resident_id""",
        (subject["id"], resident["id"], pack(values)),
    )
    return f"更新长辈 {resident['id']} 的亲属联系档案"


def png_dimensions(raw):
    offset = 8
    dimensions = None
    has_data = False
    while offset + 12 <= len(raw):
        size = int.from_bytes(raw[offset : offset + 4], "big")
        kind = raw[offset + 4 : offset + 8]
        end = offset + 8 + size
        if end + 4 > len(raw) or zlib.crc32(raw[offset + 4 : end]) != int.from_bytes(
            raw[end : end + 4], "big"
        ):
            break
        if offset == 8:
            if kind != b"IHDR" or size != 13:
                break
            dimensions = struct.unpack(">II", raw[offset + 8 : offset + 16])
        elif kind == b"IHDR":
            break
        if kind == b"IDAT" and size:
            has_data = True
        if kind == b"IEND":
            if size == 0 and has_data and end + 4 == len(raw):
                return dimensions
            break
        offset = end + 4
    raise ValueError("PNG 文件结构不完整")


def jpeg_dimensions(raw):
    offset = 2
    dims = None
    while offset + 4 < len(raw) and raw[offset] == 255:
        while offset < len(raw) and raw[offset] == 255:
            offset += 1
        if offset + 3 > len(raw):
            break
        kind = raw[offset]
        length = int.from_bytes(raw[offset + 1 : offset + 3], "big")
        end = offset + 1 + length
        if length < 2 or end > len(raw):
            break
        if kind in (192, 193, 194):
            if length < 11:
                break
            height, width = struct.unpack(">HH", raw[offset + 4 : offset + 8])
            dims = (width, height)
        if kind == 218:
            if dims and end < len(raw) - 2 and raw[-2:] == b"\xff\xd9":
                return dims
            break
        offset = end
    raise ValueError("JPEG 文件结构不完整")


def photo_payload(p, *, allow_pdf=False):
    encoded = p.get("imageBase64", "")
    if not encoded:
        return None, None, None
    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_IMAGE + 2) // 3):
        raise ValueError("原件最大为 8 MiB")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as err:
        raise ValueError("原件编码无效") from err
    if not 0 < len(raw) <= MAX_IMAGE:
        raise ValueError("原件最大为 8 MiB")
    if allow_pdf and raw.startswith(b"%PDF-"):
        if p.get("mime", "application/pdf") != "application/pdf":
            raise ValueError("PDF 格式和声明类型不一致")
        return raw, "application/pdf", hashlib.sha256(raw).hexdigest()
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
        width, height = png_dimensions(raw)
    elif raw.startswith(b"\xff\xd8"):
        mime = "image/jpeg"
        width, height = jpeg_dimensions(raw)
    else:
        raise ValueError(
            "请上传 PDF、PNG 或 JPEG 原件" if allow_pdf else "请上传 PNG 或 JPEG 原图"
        )
    if p.get("mime", mime) != mime:
        raise ValueError("照片格式和声明类型不一致")
    if (
        min(width, height) < 1
        or max(width, height) > 24000
        or width * height > 100_000_000
    ):
        raise ValueError("图片尺寸超出可查看范围")
    return raw, mime, hashlib.sha256(raw).hexdigest()


def archive_document(db, state, p, user, today, *, return_id=False):
    access.require(user, "medical.write")
    resident = lookup(state, "residents", p.get("residentId"))
    rid = resident["id"]
    key = text(p, "requestId", 100, True)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", key):
        raise ValueError("存档请求编号无效")
    event_date = calendar_day(p.get("eventDate"), "文书日期", today).isoformat()
    kind = text(p, "category", 30, True)
    if kind not in CATEGORIES:
        raise ValueError("请选择文书类型")
    method = text(p, "method", 30) or METHODS[0]
    if method not in METHODS:
        raise ValueError("请选择有效的描述来源")
    source = text(p, "source", 200, True)
    staging = method in document_ocr.STAGED
    description = text(p, "description", 8000, not staging)
    if staging and description:
        raise ValueError("请先留存原件，识别后再核对文字")
    pending = text(p, "pending", 2000)
    raw, mime, digest = photo_payload(p, allow_pdf=True)
    if not raw and (kind != "病史补录" or method != METHODS[0]):
        raise ValueError("该类文书需要同时留存原件")
    # 指纹按业务输入计算。登录人和重试日期不改变同一原件的一次性概括。
    fingerprint = hashlib.sha256(
        pack([kind, event_date, source, method, description, pending, digest]).encode()
    ).hexdigest()
    match = db.execute(
        """SELECT id,fingerprint FROM dossier_documents WHERE resident_id=? AND
                       (request_id=? OR fingerprint=? OR image_hash=?)""",
        (rid, key, fingerprint, digest),
    ).fetchall()
    if match:
        if all(row[1] == fingerprint for row in match):
            message = f"确认长辈 {rid} 的文书已存档，沿用原概括"
            return (message, match[0][0]) if return_id else message
        raise ValueError("该请求编号或原图已存档，请查看已有概括")
    summary = {
        "eventDate": event_date,
        "source": source,
        "documentType": kind,
        "sourceFacts": description,
        "pending": pending or "未填写",
        "reviewedBy": user["displayName"],
        "reviewerId": user["id"],
        "method": method,
        "version": 1,
    }
    meta = {
        "category": kind,
        "source": source,
        "summary": None if staging else summary,
        "method": method,
        "bytes": len(raw) if raw else 0,
        "filename": text(p, "filename", 200) if raw else "",
    }
    if raw:
        meta["pageCount"] = pdf_original.pages(raw) if mime == "application/pdf" else 1
    did = uuid.uuid4().hex
    db.execute(
        """INSERT INTO dossier_documents
               (id,resident_id,request_id,fingerprint,event_date,recorded_date,metadata,mime,original,image_hash)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            did,
            rid,
            key,
            fingerprint,
            event_date,
            today,
            pack(meta),
            mime,
            raw,
            digest,
        ),
    )
    message = (
        f"为长辈 {rid} 留存医疗原件，等待识别"
        if staging
        else f"为长辈 {rid} 存档医疗文书并保存概括"
    )
    return (message, did) if return_id else message


def review_document(db, state, p, user, today):
    for grant in ("medical.write", "medical", "clinical"):
        access.require(user, grant)
    if set(p) - {"reviewedPages"} != {
        "residentId",
        "documentId",
        "verifiedName",
        "sourceFacts",
        "pending",
        "method",
        "changes",
    }:
        raise ValueError("文书核对字段无效")
    did, raw_meta = document_ocr.source(db, p)
    meta = json.loads(raw_meta)
    page_count = meta.get("pageCount", 1)
    checked = p.get("reviewedPages", [1] if page_count == 1 else [])
    if (
        not isinstance(checked, list)
        or len(checked) != page_count
        or any(type(value) is not int for value in checked)
        or sorted(checked) != list(range(1, page_count + 1))
    ):
        raise ValueError("请逐页核对全部原件")
    resident = lookup(state, "residents", p["residentId"])
    if text(p, "verifiedName", 60, True) != resident["name"]:
        raise ValueError("请核对原件姓名与当前长辈")
    facts = text(p, "sourceFacts", 8000, True)
    pending = text(p, "pending", 2000)
    changes = p["changes"]
    if not isinstance(changes, list) or len(changes) > len(document_ocr.FIELDS):
        raise ValueError("请逐项选择要回填的档案字段")
    fingerprint = hashlib.sha256(pack(p).encode()).hexdigest()
    prior = db.execute(
        "SELECT review FROM dossier_document_reviews WHERE document_id=?", (did,)
    ).fetchone()
    if prior:
        if json.loads(prior[0])["fingerprint"] == fingerprint:
            return "该原件已完成同一复核，沿用既有概括"
        raise ValueError("该原件已有人工核对结果")
    row = db.execute(
        "SELECT result FROM dossier_ocr_jobs WHERE document_id=? AND published=1",
        (did,),
    ).fetchone()
    ocr = json.loads(row[0]) if row else {}
    method = p["method"]
    expected = (
        "DeepSeek OCR 人工核对"
        if ocr.get("engine") == document_ocr.METHOD
        else "院内 OCR 人工核对"
    )
    if method not in (expected, "手工描述") or (
        method != "手工描述" and ocr.get("state") != "recognized"
    ):
        raise ValueError("请选择与实际识别结果相符的文字来源")
    identity_mismatch = any(
        c["field"] == "name" and c["value"] != resident["name"]
        for c in document_ocr.normalized_candidates(ocr.get("candidates", []))
    )
    if changes and identity_mismatch:
        raise ValueError("原文识别姓名与档案不同，请先核实身份，本次仅可留存文书")
    recorded = {}
    for item in changes:
        required = {"field", "value", "previous", "line"}
        if not isinstance(item, dict) or set(item) not in (
            required,
            required | {"page"},
        ):
            raise ValueError("请逐项确认回填值、原值和来源")
        key, line = item["field"], item["line"]
        page = item.get("page", 1)
        if type(page) is not int or not 1 <= page <= meta.get("pageCount", 1):
            raise ValueError("原件页码无效")
        if (
            not isinstance(key, str)
            or key not in document_ocr.FIELDS
            or key in recorded
        ):
            raise ValueError("回填字段无效或重复")
        value = text(item, "value", 1000, True)
        previous = resident.get(key) or ""
        if item["previous"] != previous:
            raise ValueError("已有档案内容发生变化，请重新核对")
        if line is not None and (
            type(line) is not int
            or method == "手工描述"
            or not any(
                c["line"] == line and c.get("page", 1) == page and c["field"] == key
                for c in ocr.get("candidates", [])
            )
        ):
            raise ValueError("候选字段的原文行号无效")
        recorded[key] = {"before": previous, "after": value, "page": page, "line": line}
    event = db.execute(
        "SELECT event_date FROM dossier_documents WHERE id=?", (did,)
    ).fetchone()[0]
    reviewed = {
        "eventDate": event,
        "source": meta["source"],
        "documentType": meta["category"],
        "sourceFacts": facts,
        "pending": pending or "未填写",
        "reviewedBy": user["displayName"],
        "reviewerId": user["id"],
        "method": method,
        "version": 1,
    }
    receipt = {
        "summary": reviewed,
        "changes": recorded,
        "reviewedPages": sorted(checked),
        "identityMatch": not identity_mismatch,
        "reviewDate": today,
        "fingerprint": fingerprint,
    }
    db.execute(
        "INSERT INTO dossier_document_reviews(document_id,review) VALUES(?,?)",
        (did, pack(receipt)),
    )
    if recorded:
        resident.update({k: v["after"] for k, v in recorded.items()})
        append_record(
            state,
            "archives",
            residentId=resident["id"],
            date=today,
            source="医疗原件逐项复核",
            documentId=did,
            reviewer=user["displayName"],
            summary=resident.get("summary") or facts,
            allergies=resident.get("allergies", ""),
            risk=resident.get("risk", ""),
        )
        if "allergies" in recorded:
            refresh_medication_warnings(state, resident)
    return f"核对长辈 {resident['id']} 的文书概括" + (
        "并回填" + "、".join(document_ocr.FIELDS[k] for k in recorded)
        if recorded
        else ""
    )


HANDLERS = {
    "dossier.ocr": document_ocr.publish,
    "dossier.signSummary": sign_summary,
    "dossier.reviewDocument": review_document,
    "dossier.profile": edit_profile,
    "dossier.relative": edit_relative,
}


def apply(db, state, action, payload, user, today):
    return HANDLERS[action](db, state, payload, user, today)


def project_roster(db, data, user):
    """Add summaries scoped to the visible staff roster after all business modules are loaded."""
    if user["kind"] == "family":
        return
    residents = {r["id"]: r for r in data.get("residents", []) if r.get("status") != "归档到期"}
    if not residents:
        return
    visible = json.dumps(list(residents))
    if access.has(user, "finance") or access.has(user, "intake"):
        for rid, kind, did, at, details in db.execute(
            """SELECT resident_id,kind,id,at,reviewed_fields FROM subsidy_materials WHERE rowid IN (
                 SELECT MAX(rowid) FROM subsidy_materials
                 WHERE resident_id IN (SELECT value FROM json_each(?))
                 AND kind IN ('idFront','idBack','household') GROUP BY resident_id,kind)""",
            (visible,),
        ):
            fields = json.loads(details)
            if "idNumber" in fields:
                fields["idNumber"] = masked(fields["idNumber"])
            residents[rid].setdefault("credentialMaterials", {})[kind] = {"id": did, "at": at, "fields": fields}
    if access.has(user, "medical") or access.has(user, "clinical"):
        # The roster needs only the latest verified labels, never source notes or older diagnoses.
        for rid, payload in db.execute(
            """SELECT resident_id,refs FROM resident_health_notes WHERE rowid IN (
                 SELECT MAX(rowid) FROM resident_health_notes WHERE kind='chronic'
                 AND resident_id IN (SELECT value FROM json_each(?)) GROUP BY resident_id)""",
            (visible,),
        ):
            entry = json.loads(payload)
            residents[rid]["chronicRegistration"] = {
                "status": entry["status"], "names": [item["name"] for item in entry["items"]]
            }


def project(db, data, user, today=None):
    """仅在基础快照完成权限投影后调用；原图独立读取。"""
    day = (
        date.fromisoformat(today)
        if today
        else datetime.now(ZoneInfo("Asia/Shanghai")).date()
    )
    residents = {r["id"]: r for r in data.get("residents", [])}
    data.update(dossierProfiles=[], medicalDocuments=[], relativeProfiles=[])
    if user["kind"] != "family" and any(
        access.has(user, p) for p in ("residents", "intake", "relatives")
    ):
        for rid, basic, household in db.execute(
            "SELECT resident_id,basic,household FROM dossier_profiles"
        ):
            if rid not in residents:
                continue
            entry = {"residentId": rid}
            if access.has(user, "residents") or access.has(user, "intake"):
                entry.update(json.loads(basic))
                if entry.get("birthDate") and "age" in residents[rid]:
                    residents[rid]["age"] = years_old(
                        date.fromisoformat(entry["birthDate"]), day
                    )
            if access.has(user, "relatives"):
                entry.update(json.loads(household))
            data["dossierProfiles"].append(entry)
    if user["kind"] != "family" and access.has(user, "medical"):
        for (
            did,
            rid,
            event,
            recorded,
            meta,
            mime,
            digest,
            ocr_status,
            ocr_error,
            review,
        ) in db.execute(
            """SELECT d.id,d.resident_id,d.event_date,d.recorded_date,d.metadata,d.mime,d.image_hash,
                    json_extract(j.result,'$.state'),json_extract(j.result,'$.error'),r.review
               FROM dossier_documents d LEFT JOIN dossier_ocr_jobs j ON j.document_id=d.id AND j.published=1
               LEFT JOIN dossier_document_reviews r ON r.document_id=d.id
               ORDER BY d.event_date DESC,d.rowid DESC"""
        ):
            if rid in residents:
                metadata = json.loads(meta)
                if metadata.get("method") in document_ocr.STAGED:
                    metadata["imageHash"] = digest
                    metadata["ocr"] = {
                        "state": ocr_status or "queued",
                        "error": ocr_error or "",
                    }
                if review:
                    receipt = json.loads(review)
                    metadata.update(
                        summary=receipt["summary"],
                        reviewChanges=receipt["changes"],
                        reviewDate=receipt["reviewDate"],
                        reviewedPages=receipt.get("reviewedPages", [1]),
                    )
                data["medicalDocuments"].append(
                    {
                        "id": did,
                        "residentId": rid,
                        "eventDate": event,
                        "recordedDate": recorded,
                        "hasImage": bool(mime),
                        "mime": mime,
                        **metadata,
                    }
                )
    if user["kind"] == "family" or access.has(user, "relatives"):
        sql = "SELECT account_id,resident_id,details FROM dossier_relatives"
        args = ()
        if user["kind"] == "family":
            sql += " WHERE account_id=? AND resident_id=?"
            args = (user["id"], user["residentId"])
        for aid, rid, details in db.execute(sql, args):
            if rid not in residents:
                continue
            row = json.loads(details)
            if user["kind"] == "staff":
                row["idNumber"] = masked(row.get("idNumber", ""))
            data["relativeProfiles"].append(
                {"accountId": aid, "residentId": rid, **row}
            )
    return data


def photo(db, document_id, user):
    if user["kind"] == "family":
        raise PermissionError("原件需要医疗档案权限")
    access.require(user, "medical")
    record = db.execute(
        "SELECT original,mime FROM dossier_documents WHERE id=? AND mime IS NOT NULL",
        (document_id,),
    ).fetchone()
    if not record:
        raise FileNotFoundError("找不到医疗原件")
    return tuple(record)
