"""Private, once-per-original OCR. Only literal labelled lines become profile candidates."""

from contextlib import closing
import json
import re
import time
import uuid

from . import access, pdf_original
from .provider import media

METHOD = "DeepSeek OCR"
LEGACY_METHOD = "院内 OCR"
STAGED = (METHOD, LEGACY_METHOD)
FIELDS = {"summary": "病史摘要", "allergies": "过敏史", "risk": "高危要点"}
LABELS = {
    "name": r"(?:患者姓名|姓名|patient name|name)",
    "summary": r"(?:出院诊断|主要诊断|诊断|病史摘要|diagnosis|discharge diagnosis|history)",
    "allergies": r"(?:药物过敏史|过敏史|过敏原|allergies|allergy)",
    "risk": r"(?:高危要点|高危提示|风险提示|风险因素|risk factors|risk)",
}
PATTERNS = {
    k: re.compile(r"^" + p + r"\s*[:：]\s*(.+)$", re.I) for k, p in LABELS.items()
}


class RecognitionError(ValueError):
    """An error suitable for displaying alongside the archived document."""


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS dossier_ocr_jobs (
        document_id TEXT PRIMARY KEY REFERENCES dossier_documents(id),
        lease TEXT NOT NULL, started REAL NOT NULL, result TEXT, published INTEGER NOT NULL DEFAULT 0)""")
    db.execute("""CREATE TABLE IF NOT EXISTS dossier_document_reviews (
        document_id TEXT PRIMARY KEY REFERENCES dossier_documents(id), review TEXT NOT NULL)""")
    for operation in ("UPDATE", "DELETE"):
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS dossier_review_no_{operation.lower()}
            BEFORE {operation} ON dossier_document_reviews
            BEGIN SELECT RAISE(ABORT,'医疗文书复核不可覆盖或删除'); END""")


# Rich layout markers have normalized coordinates. Plain lines deliberately have no location.
MARKER = re.compile(
    r"<[｜|]ref[｜|]>(.*?)<[｜|]/ref[｜|]>\s*<[｜|]box[｜|]>(.*?)<[｜|]/box[｜|]>", re.S
)
REGION_TYPES = {
    "text",
    "title",
    "header",
    "footer",
    "figure",
    "image",
    "table",
    "paragraph",
    "equation",
    "code",
    "caption",
}


def page_text(page, number, width, height):
    result, candidates = [], []

    def add_lines(value, box):
        for text in value.splitlines():
            if not (text := text.strip()):
                continue
            line = {"line": len(result) + 1, "page": number, "text": text, "box": box}
            result.append(line)
            for field, pattern in PATTERNS.items():
                if match := pattern.match(text):
                    candidates.append(
                        {
                            "field": field,
                            "value": match[1].strip(),
                            "line": line["line"],
                            "page": number,
                        }
                    )
                    break

    last = 0
    matches = list(MARKER.finditer(page["text"]))
    for i, m in enumerate(matches):
        add_lines(page["text"][last : m.start()], None)
        try:
            regions = json.loads(m.group(2))
        except (ValueError, RecursionError):
            regions = None
        box = None
        if (
            isinstance(regions, list)
            and regions
            and isinstance(regions[0], list)
            and len(regions[0]) == 4
        ):
            x1, y1, x2, y2 = regions[0]
            if (
                all(type(v) is int and 0 <= v <= 1000 for v in regions[0])
                and x1 < x2
                and y1 < y2
            ):
                box = [
                    round(x1 * width / 1000),
                    round(y1 * height / 1000),
                    round((x2 - x1) * width / 1000),
                    round((y2 - y1) * height / 1000),
                ]
        label = m.group(1).strip()
        last = m.end()
        if label.lower() in REGION_TYPES:
            last = matches[i + 1].start() if i + 1 < len(matches) else len(page["text"])
            add_lines(page["text"][m.end() : last].strip() or label, box)
        else:
            add_lines(label, box)
    add_lines(page["text"][last:], None)
    return result, candidates


def parse_result(obj, width, height, page_count=1):
    if (
        obj["object"] != "ocr.result"
        or obj["purpose"] != "text_recognition"
        or type(obj["page_count"]) is not int
        or obj["page_count"] != page_count
        or not isinstance(obj["pages"], list)
        or len(obj["pages"]) != page_count
    ):
        raise ValueError("识别回执页数与原件不符")
    records = {}
    for page in obj["pages"]:
        index = page["index"]
        if (
            type(index) is not int
            or not 0 <= index < page_count
            or index in records
            or not isinstance(page["text"], str)
            or page.get("finish_reason") not in ("stop", "length")
        ):
            raise ValueError("识别回执页码或内容无效")
        records[index] = page
    result = {
        "engine": METHOD,
        "pageCount": page_count,
        "pages": [],
        "lines": [],
        "candidates": [],
    }
    for index in range(page_count):
        page = records[index]
        lines, candidates = page_text(page, index + 1, width, height)
        state = (
            "partial"
            if page["finish_reason"] == "length"
            else "complete"
            if lines
            else "blank"
        )
        result["pages"].append({"page": index + 1, "state": state})
        result["lines"].extend(lines)
        if state == "complete":
            result["candidates"].extend(candidates)
        else:
            # An incomplete page can still identify a different resident.
            result["candidates"].extend(c for c in candidates if c["field"] == "name")
    result["state"] = "recognized" if result["lines"] else "failed"
    if page_count == 1 and (
        result["pages"][0]["state"] == "partial"
        or len(result["lines"]) > 500
        or sum(len(line["text"]) for line in result["lines"]) > 16000
    ):
        result.update(state="failed", lines=[], candidates=[])
        result["error"] = "该页未得到完整可核对的文字，请按原件手工补录"
    if result["state"] == "failed" and "error" not in result:
        result["error"] = "未识别到可核对的文字，请按原件手工补录"
    return result, page_count, obj["id"]


def recognize(store, token, raw, authorize, *, feature="dossier.documentOcr"):
    from .dossier import jpeg_dimensions, png_dimensions

    if raw.startswith(b"%PDF-"):
        page_count = pdf_original.pages(raw)
        filename, mime = "document.pdf", "application/pdf"
        width = height = (
            1000  # PDF boxes stay in DeepSeek's normalized page coordinates.
        )
    else:
        png = raw.startswith(b"\x89PNG")
        width, height = png_dimensions(raw) if png else jpeg_dimensions(raw)
        if width * height > 20_000_000:
            raise RecognitionError("原件超出单页识别上限，可核对原图后手工补录")
        page_count = 1
        filename, mime = (
            ("document.png", "image/png") if png else ("document.jpg", "image/jpeg")
        )
    return media.execute(
        store,
        token,
        "ocr",
        raw,
        page_count,
        filename,
        mime,
        authorize,
        lambda obj: parse_result(obj, width, height, page_count),
        feature=feature,
    )


def source(db, p):
    if not isinstance(p, dict):
        raise ValueError("文书请求格式无效")
    key = "imageHash" if "imageHash" in p else "documentId"
    column, pattern = (
        ("image_hash", r"[a-f0-9]{64}")
        if key == "imageHash"
        else ("id", r"[a-f0-9]{32}")
    )
    if (
        not isinstance(p.get(key), str)
        or not re.fullmatch(pattern, p[key])
        or not isinstance(p.get("residentId"), str)
    ):
        raise ValueError("请指定长者与文书原件")
    record = db.execute(
        f"SELECT id,metadata FROM dossier_documents WHERE {column}=? AND resident_id=?",
        (p[key], p["residentId"]),
    ).fetchone()
    if not record or json.loads(record[1]).get("method") not in STAGED:
        raise ValueError("未找到该长者可复核的 OCR 原件")
    return record


def prepare(store, token, p, revision):
    """Reserve under a short lock; perform image processing outside the shared write transaction."""
    from .store import Conflict

    if not isinstance(p, dict) or not (
        set(p)
        in (
            {"residentId", "documentId", "consent"},
            {"residentId", "imageHash", "consent"},
        )
        and p.get("consent") is True
    ):
        raise ValueError("请确认本次将文书原件提交 DeepSeek 识别")

    def authorize(db, session):
        from .campus_access import require_resident

        actor = store.actor(db, session)
        access.require(actor, "medical.write")
        from .care.archive_retention import require_ai_eligible

        state = json.loads(
            db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
        )
        require_resident(db, actor, p["residentId"], state)
        require_ai_eligible(state, p["residentId"])
        return actor

    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        authorize(db, token)
        if (
            type(revision) is not int
            or db.execute("SELECT revision FROM workspace").fetchone()[0] != revision
        ):
            raise Conflict("数据已更新，请重新核对原件")
        did, _ = source(db, p)
        if db.execute(
            "SELECT 1 FROM dossier_document_reviews WHERE document_id=?", (did,)
        ).fetchone():
            raise ValueError("此原件已完成复核")
        # Identical original bytes can exist in more than one resident's chart. Share the
        # immutable engine output only. Publication, corrections and sign-off stay separate.
        digest = db.execute(
            "SELECT image_hash FROM dossier_documents WHERE id=?", (did,)
        ).fetchone()[0]
        job = db.execute(
            """
            SELECT j.document_id,j.result,j.started FROM dossier_ocr_jobs j
            JOIN dossier_documents d ON d.id=j.document_id WHERE d.image_hash=?
             AND json_extract(j.result,'$.state')='recognized'
             AND (j.document_id=? OR json_extract(j.result,'$.engine')=?)
            ORDER BY j.started DESC LIMIT 1""",
            (digest, did, METHOD),
        ).fetchone()
        now, lease = time.time(), uuid.uuid4().hex
        if job:
            if job["document_id"] != did:
                db.execute(
                    """INSERT INTO dossier_ocr_jobs(document_id,lease,started,result)
                          VALUES(?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET result=excluded.result""",
                    (did, lease, now, job["result"]),
                )
            return
        busy = db.execute(
            """SELECT 1 FROM dossier_ocr_jobs j JOIN dossier_documents d ON j.document_id=d.id
                    WHERE d.image_hash=? AND j.result IS NULL AND j.started>?""",
            (digest, now - 240),
        ).fetchone()
        if busy:
            raise ValueError("此原件正在识别，请稍后查看")
        db.execute(
            """INSERT INTO dossier_ocr_jobs(document_id,lease,started) VALUES(?,?,?)
                    ON CONFLICT(document_id) DO UPDATE SET lease=excluded.lease,started=excluded.started,result=NULL,published=0""",
            (did, lease, now),
        )
        raw = db.execute(
            "SELECT original FROM dossier_documents WHERE id=?", (did,)
        ).fetchone()[0]
    try:
        result = recognize(store, token, raw, authorize)
    except PermissionError:
        with closing(store.connect()) as db, db:
            db.execute(
                "DELETE FROM dossier_ocr_jobs WHERE document_id=? AND lease=? AND result IS NULL",
                (did, lease),
            )
        raise
    except (OSError, ValueError) as err:
        reason = str(err) if isinstance(err, ValueError) else "识别配置暂不可用"
        result = {
            "state": "failed",
            "error": reason,
            "engine": METHOD,
            "lines": [],
            "candidates": [],
        }
    with closing(store.connect()) as db, db:
        db.execute(
            "UPDATE dossier_ocr_jobs SET result=? WHERE document_id=? AND lease=?",
            (json.dumps(result, ensure_ascii=False), did, lease),
        )


def publish(db, state, p, user, today):
    access.require(user, "medical.write")
    from .campus_access import require_resident

    require_resident(db, user, p["residentId"], state)
    did = source(db, p)[0]
    job = db.execute(
        "SELECT result FROM dossier_ocr_jobs WHERE document_id=?", (did,)
    ).fetchone()
    if not job or not job[0]:
        raise ValueError("原件尚未生成识别结果")
    db.execute("UPDATE dossier_ocr_jobs SET published=1 WHERE document_id=?", (did,))
    return (
        "原件已留存，识别完成待人工核对"
        if json.loads(job[0])["state"] == "recognized"
        else "原件已留存，识别未完成待人工补录"
    )


def detail(db, user, document_id):
    access.require(user, "medical")
    row = db.execute(
        """SELECT j.result FROM dossier_documents d
        LEFT JOIN dossier_ocr_jobs j ON j.document_id=d.id AND j.published=1
        WHERE d.id=? AND json_extract(d.metadata,'$.method') IN (?,?)""",
        (document_id, *STAGED),
    ).fetchone()
    if not row:
        raise FileNotFoundError("找不到可核对的 OCR 原件")
    return (
        json.loads(row[0])
        if row[0]
        else {"state": "queued", "lines": [], "candidates": []}
    )
