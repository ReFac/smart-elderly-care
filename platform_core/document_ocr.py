"""Private, once-per-original OCR. Only literal labelled lines become profile candidates."""

from contextlib import closing
import csv
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sysconfig
import time
import uuid

from . import access

METHOD = "院内 OCR"
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


def parse_tsv(output):
    lines = {}
    for row in csv.DictReader(
        io.StringIO(output), delimiter="\t", quoting=csv.QUOTE_NONE
    ):
        if row["level"] != "5" or not (word := row["text"].strip()):
            continue
        key = tuple(row[k] for k in ("page_num", "block_num", "par_num", "line_num"))
        words = lines.setdefault(key, [])
        words.append(
            (
                word,
                max(0, min(100, float(row["conf"]))),
                int(row["left"]),
                int(row["top"]),
                int(row["width"]),
                int(row["height"]),
            )
        )
    result, candidates = [], []
    for key, words in lines.items():
        # Tesseract returns Chinese characters as separate words; retain spaces in Latin text.
        text = " ".join(w[0] for w in words)
        text = re.sub(r"(?<=[\u3400-\u9fff]) +(?=[\u3400-\u9fff])", "", text)
        left, top = min(w[2] for w in words), min(w[3] for w in words)
        line = {
            "line": len(result) + 1,
            "page": int(key[0]),
            "text": text,
            "confidence": round(sum(w[1] for w in words) / len(words)),
            "box": [
                left,
                top,
                max(w[2] + w[4] for w in words) - left,
                max(w[3] + w[5] for w in words) - top,
            ],
        }
        result.append(line)
        for field, pattern in PATTERNS.items():
            match = pattern.match(text)
            if match:
                candidates.append(
                    {"field": field, "value": match[1].strip(), "line": line["line"]}
                )
                break
    if not result:
        raise RecognitionError("原件未识别出可核对的文字")
    if len(result) > 500 or sum(len(r["text"]) for r in result) > 16000:
        raise RecognitionError("识别文本超出单页上限，请核对原图并手工录入")
    return {
        "state": "recognized",
        "engine": "Tesseract · chi_sim+eng",
        "lines": result,
        "candidates": candidates,
    }


def recognize(raw):
    from .dossier import jpeg_dimensions, png_dimensions

    width, height = (
        png_dimensions(raw) if raw.startswith(b"\x89PNG") else jpeg_dimensions(raw)
    )
    if width * height > 20_000_000:
        raise RecognitionError(
            "原件已保存。图像超过院内单页识别上限，可核对原图后手工补录"
        )
    env = {"PATH": os.defpath, "OMP_THREAD_LIMIT": "1"}
    binary = shutil.which("tesseract")
    if not binary:
        local = Path(__file__).resolve().parents[1] / ".local/ocr/usr"
        binary = local / "bin/tesseract"
        if not binary.is_file():
            raise RecognitionError("院内 OCR 引擎未安装，可核对原图后手工补录")
        env["LD_LIBRARY_PATH"] = str(
            local / "lib" / (sysconfig.get_config_var("MULTIARCH") or "")
        )
        env["TESSDATA_PREFIX"] = str(local / "share/tesseract-ocr/5/tessdata")
    proc = subprocess.run(
        [str(binary), "stdin", "stdout", "-l", "chi_sim+eng", "--psm", "6", "tsv"],
        input=raw,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=25,
    )
    if proc.returncode or b"Failed loading language" in proc.stderr:
        raise RecognitionError("院内引擎未能识别原件，请核对语言包或手工录入")
    if len(proc.stdout) > 2_000_000:
        raise RecognitionError("单页识别内容过多，可手工核对原图")
    return parse_tsv(proc.stdout.decode("utf-8"))


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
    if not record or json.loads(record[1]).get("method") != METHOD:
        raise ValueError("未找到该长者可复核的院内 OCR 原件")
    return record


def prepare(store, token, p, revision):
    """Reserve under a short lock; perform image processing outside the shared write transaction."""
    from .store import Conflict

    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        access.require(store.actor(db, token), "medical.write")
        if (
            type(revision) is not int
            or db.execute("SELECT revision FROM workspace").fetchone()[0] != revision
        ):
            raise Conflict("数据已更新，请重新核对原件")
        if not isinstance(p, dict) or set(p) not in (
            {"residentId", "documentId"},
            {"residentId", "imageHash"},
        ):
            raise ValueError("文书识别字段无效")
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
            ORDER BY (j.result IS NOT NULL) DESC,j.started DESC LIMIT 1""",
            (digest,),
        ).fetchone()
        now, lease = time.time(), uuid.uuid4().hex
        if job and job["result"]:
            if job["document_id"] != did:
                db.execute(
                    """INSERT INTO dossier_ocr_jobs(document_id,lease,started,result)
                    VALUES(?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET result=excluded.result""",
                    (did, lease, now, job["result"]),
                )
            return
        if job and now - job["started"] < 90:
            raise ValueError("此原件正在识别，请稍后查看")
        db.execute(
            """INSERT INTO dossier_ocr_jobs(document_id,lease,started) VALUES(?,?,?)
            ON CONFLICT(document_id) DO UPDATE SET lease=excluded.lease,started=excluded.started""",
            (did, lease, now),
        )
        raw = db.execute(
            "SELECT original FROM dossier_documents WHERE id=?", (did,)
        ).fetchone()[0]
    try:
        result = recognize(raw)
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        subprocess.TimeoutExpired,
        csv.Error,
    ) as err:
        reason = (
            str(err)
            if isinstance(err, RecognitionError)
            else "识别未完成，可核对原图后手工录入"
        )
        result = {"state": "failed", "error": reason, "lines": [], "candidates": []}
    with closing(store.connect()) as db, db:
        db.execute(
            "UPDATE dossier_ocr_jobs SET result=? WHERE document_id=? AND lease=?",
            (json.dumps(result, ensure_ascii=False), did, lease),
        )


def publish(db, state, p, user, today):
    access.require(user, "medical.write")
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
        WHERE d.id=? AND json_extract(d.metadata,'$.method')=?""",
        (document_id, METHOD),
    ).fetchone()
    if not row:
        raise FileNotFoundError("找不到可核对的 OCR 原件")
    return (
        json.loads(row[0])
        if row[0]
        else {"state": "queued", "lines": [], "candidates": []}
    )
