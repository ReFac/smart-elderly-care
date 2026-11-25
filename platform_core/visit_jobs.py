"""Durable, per-operator document delegation. Only the existing signed command can file a visit."""

from contextlib import closing
from hashlib import sha256
import json
import logging
import re

from . import access, medical_visits
from .provider import task_usage


def upload_task(store, token, origin, batch):
    """A chat turn or standalone upload can start a task but can never authorize its documents."""
    if not origin and not batch:
        return None
    with closing(store.connect()) as db:
        actor = store.actor(db, token)
        if origin:
            from .agents import chat
            return chat.upload_task(db, actor["id"], origin)
        if not isinstance(batch, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", batch):
            raise ValueError("上传组编号无效")
        return task_usage.identifier("upload", actor["id"], batch)


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS dossier_visit_jobs(
        draft TEXT PRIMARY KEY REFERENCES dossier_visit_drafts(id),
        sessionHash TEXT NOT NULL, fields TEXT NOT NULL, visitId TEXT NOT NULL, fixedDate TEXT NOT NULL,
        taskId TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('queued','running','ready','failed')),
        error TEXT NOT NULL DEFAULT '')""")
    db.execute("CREATE INDEX IF NOT EXISTS visit_jobs_state ON dossier_visit_jobs(state)")


def enqueue(db, draft, token, fields, visit_id, fixed_date, task_id=None):
    if draft["mode"] != "ai":
        raise ValueError("只有已同意识别的就诊资料可以加入整理队列")
    task_id = task_id or task_usage.identifier("visit", draft["resident_id"], draft["id"])
    db.execute("""INSERT INTO dossier_visit_jobs(draft,sessionHash,fields,visitId,fixedDate,taskId,state)
                  VALUES(?,?,?,?,?,?,?) ON CONFLICT(draft) DO NOTHING""",
               (draft["id"], sha256(token.encode("ascii")).hexdigest(), json.dumps(fields, ensure_ascii=False),
                visit_id, fixed_date, task_id, "ready" if draft["result"] else "queued"))
    return dict(db.execute("SELECT draft AS draftId,state,taskId FROM dossier_visit_jobs WHERE draft=?",
                           (draft["id"],)).fetchone())


def _session(store, db, job, draft):
    # A job cannot borrow another employee's session after a logout, transfer or role change.
    actor = access.account_from_session_hash(db, job["sessionHash"])
    if not actor or actor["id"] != draft["actor"]:
        raise PermissionError("原经办会话已失效，请重新登录后继续")
    actor = store.scoped_actor(db, actor)
    row = db.execute("SELECT data,revision FROM workspace WHERE id=1").fetchone()
    person = medical_visits._authorize(json.loads(row["data"]), db, actor, draft["resident_id"])
    if person["name"] != draft["resident_name"]:
        raise PermissionError("长辈身份已变更，请重新核对资料")
    return actor, person["name"], row["revision"]


def run_next(store):
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        job = db.execute("SELECT * FROM dossier_visit_jobs WHERE state='queued' ORDER BY rowid LIMIT 1").fetchone()
        if not job:
            return False
        db.execute("UPDATE dossier_visit_jobs SET state='running',error='' WHERE draft=?", (job["draft"],))
    error = ""
    try:
        with closing(store.connect()) as db:
            db.execute("BEGIN")
            draft = db.execute("SELECT * FROM dossier_visit_drafts WHERE id=?", (job["draft"],)).fetchone()
            _session(store, db, job, draft)
            files = []
            for item in (() if draft["result"] else json.loads(draft["attachments"])):
                raw, digest = db.execute("SELECT original,image_hash FROM dossier_visit_originals WHERE resident_id=? AND id=?",
                                         (draft["resident_id"], item["id"])).fetchone()
                files.append((raw, digest, item))
        medical_visits._complete(store, None, draft, files, json.loads(job["fields"]),
                                 job["visitId"], job["fixedDate"], lambda db: _session(store, db, job, draft),
                                 task_id=job["taskId"])
    except PermissionError:
        error = "原经办会话或档案权限已变化，请重新登录并核对。"
    except Exception:
        # Provider receipts and sources remain in their existing secure ledgers.
        logging.getLogger(__name__).warning("就诊资料任务未完成，任务号 %s", job["taskId"])
        error = "整理未完成，请核对服务状态和调用明细后再继续；原件已保存。"
    with closing(store.connect()) as db, db:
        db.execute("UPDATE dossier_visit_jobs SET state=?,error=? WHERE draft=?",
                   ("failed" if error else "ready", error, job["draft"]))
    return True


def dispatch(store, stopped):
    # The server holds the database's single-instance lock before starting this worker.
    # OCR and extraction retain their own once-only reservations when a process restarts.
    with closing(store.connect()) as db, db:
        db.execute("UPDATE dossier_visit_jobs SET state='queued' WHERE state='running'")
    while not stopped.is_set():
        store.visit_job_wakeup.clear()
        try:
            while not stopped.is_set() and run_next(store):
                pass
        except Exception:
            logging.getLogger(__name__).exception("暂时无法领取就诊资料任务")
            stopped.wait(3)
            continue
        if not stopped.is_set():
            # A committed upload wakes the worker immediately. Poll only as a fallback.
            store.visit_job_wakeup.wait(60)


def visible(store, token, draft_id="", *, retry=False, attachment_id=""):
    result = _visible(store, token, draft_id, retry, attachment_id)
    if retry and result.get("state") == "queued":
        store.visit_job_wakeup.set()
    return result


def _visible(store, token, draft_id, retry, attachment_id):
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE" if retry else "BEGIN")
        actor = store.actor(db, token)
        for permission in ("medical", "medical.write", "clinical"):
            access.require(actor, permission)
        state, revision = db.execute("SELECT data,revision FROM workspace WHERE id=1").fetchone()
        state = json.loads(state)
        fields = "d.id, d.resident_id, d.resident_name, j.state, j.error, j.taskId"
        if draft_id:
            fields += ", d.result, d.attachments"
        query = f"""SELECT {fields} FROM dossier_visit_drafts d
                   JOIN dossier_visit_jobs j ON j.draft=d.id WHERE d.actor=?
                   AND NOT EXISTS(SELECT 1 FROM dossier_visit_records r WHERE r.resident_id=d.resident_id AND r.group_key=d.group_key)"""
        result = []
        for row in db.execute(query + (" AND d.id=?" if draft_id else "") + " ORDER BY d.rowid DESC",
                              (actor["id"], draft_id) if draft_id else (actor["id"],)):
            try:
                person = medical_visits._authorize(state, db, actor, row["resident_id"])
            except (PermissionError, ValueError, FileNotFoundError):
                continue
            if person["name"] != row["resident_name"]:
                continue
            item = {"draftId": row["id"], "taskId": row["taskId"], "state": row["state"],
                    "residentId": row["resident_id"], "error": row["error"]}
            if draft_id:
                if retry and row["state"] == "failed":
                    db.execute("UPDATE dossier_visit_jobs SET state='queued',error='',sessionHash=? WHERE draft=?",
                               (sha256(token.encode("ascii")).hexdigest(), draft_id))
                    item.update(state="queued", error="")
                if row["state"] == "ready":
                    manifest = json.loads(row["attachments"])
                    item["draft"] = {**json.loads(row["result"]), "draftId": draft_id, "mode": "ai",
                                     "residentId": row["resident_id"], "attachments": manifest, "revision": revision}
                    if attachment_id and any(att["id"] == attachment_id for att in manifest):
                        return tuple(db.execute("SELECT original,mime FROM dossier_visit_originals WHERE id=? AND resident_id=?",
                                                (attachment_id, row["resident_id"])).fetchone())
                if attachment_id:
                    break
                return item
            result.append(item)
        if draft_id:
            raise FileNotFoundError("找不到当前经办人可核对的整理任务")
        return {"items": result}
