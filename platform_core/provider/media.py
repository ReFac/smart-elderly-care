"""Paid OCR pages and ASR seconds, metered independently from chat tokens."""

from contextlib import closing
from hashlib import sha256
from http.client import HTTPException
import json
from uuid import uuid4
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import audio_adapters, deepseek, latest, local_time, read_key

ENDPOINT = "https://api.deepseek.com/v1/tools/"
UNITS = {"ocr": "页", "asr": "秒"}


class MediaError(ValueError):
    """A safe provider error; an uncertain delivery must be reconciled before another upload."""

    def __init__(self, message, *, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS media_quota (
        plan INTEGER NOT NULL, kind TEXT NOT NULL, units INTEGER NOT NULL,
        PRIMARY KEY(plan,kind))""")
    db.execute("""CREATE TABLE IF NOT EXISTS media_usage (
        id TEXT PRIMARY KEY, plan INTEGER NOT NULL, kind TEXT NOT NULL,
        actor TEXT NOT NULL, fingerprint TEXT NOT NULL, at INTEGER NOT NULL,
        state TEXT NOT NULL, reserved INTEGER NOT NULL, charged INTEGER NOT NULL DEFAULT 0,
        result TEXT, vendor_id TEXT, original BLOB, reference TEXT NOT NULL DEFAULT '')""")
    if "feature" not in {r[1] for r in db.execute("PRAGMA table_info(media_usage)")}:
        db.execute("ALTER TABLE media_usage ADD COLUMN feature TEXT")
    db.execute("CREATE INDEX IF NOT EXISTS media_usage_by_time ON media_usage(at)")
    db.execute(
        "CREATE INDEX IF NOT EXISTS media_lookup ON media_usage(kind,fingerprint,state)"
    )
    db.execute("""CREATE TABLE IF NOT EXISTS media_policy (
        id INTEGER PRIMARY KEY CHECK (id=1), ocr INTEGER NOT NULL, asr INTEGER NOT NULL,
        asr_unlimited INTEGER NOT NULL DEFAULT 0 CHECK (asr_unlimited IN (0,1)))""")
    if "asr_unlimited" not in {r[1] for r in db.execute("PRAGMA table_info(media_policy)")}:
        db.execute("""ALTER TABLE media_policy ADD COLUMN asr_unlimited INTEGER NOT NULL
                   DEFAULT 0 CHECK (asr_unlimited IN (0,1))""")
    db.execute("INSERT OR IGNORE INTO media_policy(id,ocr,asr) VALUES(1,1,1)")


def amounts(db, plan, kind):
    used, held = db.execute(
        """SELECT coalesce(sum(charged),0),coalesce(sum(
        CASE WHEN state IN ('pending','uncertain') THEN reserved ELSE 0 END),0)
        FROM media_usage WHERE plan=? AND kind=?""",
        (plan, kind),
    ).fetchone()
    quota = db.execute(
        "SELECT units FROM media_quota WHERE plan=? AND kind=?", (plan, kind)
    ).fetchone()
    limit = quota[0] if quota else 0
    if kind == "asr" and db.execute("SELECT asr_unlimited FROM media_policy WHERE id=1").fetchone()[0]:
        limit = None
    return {
        "limit": limit,
        "used": used,
        "held": held,
        "unit": UNITS[kind],
    }


def can_reserve(meter, units):
    limit = meter["limit"]
    return limit is None or meter["used"] + meter["held"] + units <= limit


def grant(db, plan, kind, units):
    if type(units) is not int or not 0 <= units <= 1_000_000_000:
        raise ValueError("识别额度须为非负整数")
    meter = amounts(db, plan, kind)
    if units < meter["used"] + meter["held"]:
        raise ValueError("额度不能低于实际使用和在途预留")
    db.execute("INSERT OR REPLACE INTO media_quota VALUES(?,?,?)", (plan, kind, units))
    if kind == "asr":
        db.execute("UPDATE media_policy SET asr_unlimited=0 WHERE id=1")


def allow_unlimited_asr(db):
    db.execute("UPDATE media_policy SET asr_unlimited=1 WHERE id=1")


def overview(db):
    plan = latest(db)
    switches = db.execute("SELECT ocr,asr FROM media_policy WHERE id=1").fetchone()
    return {
        k: {**amounts(db, plan["id"] if plan else 0, k), "enabled": bool(switches[k])}
        for k in UNITS
    }


def configure(db, user, p):
    if user["kind"] != "owner":
        raise PermissionError("仅总管理员可控制机构识别工具")
    if set(p) != set(UNITS) or not all(type(v) is bool for v in p.values()):
        raise ValueError("识别开关无效")
    db.execute("UPDATE media_policy SET ocr=?,asr=? WHERE id=1", (p["ocr"], p["asr"]))
    return "更新识别开关，OCR {}、ASR {}".format(
        "启用" if p["ocr"] else "停用", "启用" if p["asr"] else "停用"
    )


def reconcile(db, call, charged, now):
    row = db.execute("SELECT * FROM media_usage WHERE id=?", (call,)).fetchone()
    if not row or not (
        row["state"] == "uncertain"
        or (row["state"] == "pending" and now.timestamp() - row["at"] > 600)
    ):
        raise ValueError("此识别调用无需对账")
    if type(charged) is not int or not 0 <= charged <= row["reserved"]:
        raise ValueError("结算数量超出预留")
    db.execute(
        "UPDATE media_usage SET state='reconciled',charged=? WHERE id=?",
        (charged, call),
    )


def record_late_charge(db, call, units):
    # A successful supplier receipt can arrive after an operator closed the reservation.
    # Preserve that settlement state and count the confirmed usage without creating another call.
    db.execute(
        "UPDATE media_usage SET charged=max(charged,?) WHERE id=? AND state='reconciled'",
        (units, call),
    )


def invoke(kind, raw, filename, mime, key):
    boundary = "elderly-care-" + uuid4().hex
    data = bytearray()
    if kind == "ocr":
        data.extend(
            f'--{boundary}\r\nContent-Disposition: form-data; name="purpose"\r\n\r\ntext_recognition\r\n'.encode()
        )
    data.extend(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode()
    )
    data.extend(raw)
    data.extend(f"\r\n--{boundary}--\r\n".encode())
    req = Request(
        ENDPOINT + kind,
        data=bytes(data),
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "multipart/form-data; boundary=" + boundary,
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        limit = (32 if kind == "ocr" else 4) * 1024 * 1024
        with build_opener(NoRedirect()).open(req, timeout=185) as reply:
            body = reply.read(limit + 1)
        if len(body) > limit:
            raise MediaError("识别回复超过上限，请核对渠道用量", uncertain=True)
        obj = json.loads(body)
        if not isinstance(obj, dict):
            raise ValueError
        if "error" in obj:
            raise MediaError("DeepSeek 未提供可核对的用量回执，请先对账或手工录入", uncertain=True)
        return obj
    except HTTPError as e:
        e.close()
        raise MediaError(
            f"DeepSeek 返回 HTTP {e.code}，请检查服务额度与文件格式",
            uncertain=e.code not in deepseek.REJECTED_HTTP,
        ) from None
    except (URLError, TimeoutError, HTTPException, OSError):
        raise MediaError(
            "识别连接中断，结果待平台对账；原件仍保留", uncertain=True
        ) from None
    except (ValueError, UnicodeError) as e:
        if isinstance(e, MediaError):
            raise
        raise MediaError(
            "识别回复格式未知，请平台核对渠道用量", uncertain=True
        ) from None


def invoke_asr(service, raw, filename, mime, key, duration_ms):
    try:
        return audio_adapters.transcribe(service, key, raw, filename, mime, duration_ms)
    except HTTPError as e:
        e.close()
        raise MediaError(
            f"语音服务返回 HTTP {e.code}，请联系平台运营方",
            uncertain=e.code not in deepseek.REJECTED_HTTP,
        ) from None
    except (OSError, HTTPException):
        raise MediaError("识别连接中断，结果待平台对账；原件仍保留", uncertain=True) from None
    except (ValueError, TypeError):
        raise MediaError("识别回复格式未知，请平台核对渠道用量", uncertain=True) from None


def audit_asr(db, actor, task, now, summary, scope):
    from .. import activity

    if scope is None:
        data = json.loads(
            db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
        )
        person = next(
            (t.get("residentId") for t in data["tasks"] if t["id"] == task), ""
        )
        scope = activity.for_person(data, person)
    revision = db.execute(
        "UPDATE workspace SET revision=revision+1 WHERE id=1 RETURNING revision"
    ).fetchone()[0]
    activity.write(
        db,
        revision,
        now.isoformat(timespec="seconds"),
        "media.asr" if not task.startswith("agent:") else "media.agentVoice",
        summary,
        actor,
        scope,
        {},
    )


def execute(
    store,
    token,
    kind,
    raw,
    reserve,
    filename,
    mime,
    authorize,
    parse,
    feature,
    reference="",
    upload=None,
    audit_scope=None,
    duration_ms=None,
):
    """Persist the outbound reservation first. A crash or lost reply never causes an automatic re-send."""
    now = store.now()
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        actor = authorize(db, token)
        identity = (
            (actor["id"] + "\0" + reference + "\0").encode() if kind == "asr" else b""
        )
        digest = sha256(identity + raw).hexdigest()
        prior = db.execute(
            """SELECT id,state,result FROM media_usage WHERE kind=? AND fingerprint=?
             AND (state IN ('complete','pending','uncertain') OR
                  (state='reconciled' AND charged>0)) ORDER BY rowid DESC LIMIT 1""",
            (kind, digest),
        ).fetchone()
        if prior:
            if prior["state"] == "complete":
                if feature in ("assistant.documentOcr", "access.resumeOcr"):
                    db.execute("UPDATE media_usage SET original=? WHERE id=? AND original IS NULL",
                               (raw, prior["id"]))
                return json.loads(prior["result"])
            if prior["state"] == "reconciled":
                raise ValueError("该原件已对账扣费，请按保留的原件人工核对")
            raise ValueError("识别正在处理或待平台核对，请稍后查看")
        plan = latest(db)
        day = local_time(now).date().isoformat()
        if (
            not plan
            or not plan["enabled"]
            or not plan["startsOn"] <= day <= plan["expiresOn"]
        ):
            raise ValueError("机构识别套餐尚未开通或已到期")
        if not db.execute("SELECT ocr,asr FROM media_policy WHERE id=1").fetchone()[
            kind
        ]:
            raise PermissionError("总管理员已停用该识别工具")
        meter = amounts(db, plan["id"], kind)
        if not can_reserve(meter, reserve):
            raise ValueError("机构识别套餐剩余额度不足，请联系平台运营方")
        try:
            service = audio_adapters.options("asr") if kind == "asr" else None
            key = service.key() if service else read_key()
        except (OSError, ValueError):
            raise MediaError("平台托管凭据不可用，请联系平台运营方") from None
        label = audio_adapters.LABELS[service.provider] if service else "DeepSeek"
        call = uuid4().hex
        if kind == "asr":
            from .. import history

            history.watch(db, "media.asr")
        db.execute(
            """INSERT INTO media_usage (id,plan,kind,actor,fingerprint,at,state,reserved,original,reference,feature)
          VALUES(?,?,?,?,?,?,'pending',?,?,?,?)""",
            (
                call,
                plan["id"],
                kind,
                actor["id"],
                digest,
                int(now.timestamp()),
                reserve,
                raw if kind == "asr" or feature in ("assistant.documentOcr", "access.resumeOcr") else None,
                reference,
                feature,
            ),
        )
        if kind == "asr":
            audit_asr(
                db,
                actor,
                reference,
                now,
                f"保存语音原件，提交 {label} 转写",
                audit_scope,
            )
    try:
        audio = upload if upload is not None else raw
        obj = (
            invoke_asr(service, audio, filename, mime, key, duration_ms)
            if service
            else invoke(kind, audio, filename, mime, key)
        )
        result, units, source_id = parse(obj)
        if kind == "asr":
            result["transcriptId"] = call
        if (
            type(units) is not int
            or not 1 <= units <= reserve
            or not isinstance(source_id, str)
            or not 0 < len(source_id) <= 200
        ):
            raise ValueError("识别用量或回执不符")
    except (ValueError, KeyError, TypeError, OverflowError) as e:
        firm = isinstance(e, MediaError) and not e.uncertain
        with closing(store.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if kind == "asr":
                history.watch(db, "media.asr")
            db.execute(
                "UPDATE media_usage SET state=? WHERE id=? AND state='pending'",
                ("failed" if firm else "uncertain", call),
            )
            if kind == "asr":
                audit_asr(
                    db,
                    actor,
                    reference,
                    store.now(),
                    "登记语音转写失败或待核对回执",
                    audit_scope,
                )
        raise (
            e
            if isinstance(e, MediaError)
            else MediaError("回复无法完整核对，请平台核实渠道回执", uncertain=True)
        ) from None
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if kind == "asr":
            history.watch(db, "media.asr")
        settled = db.execute(
            """UPDATE media_usage SET state='complete',result=?,charged=?,vendor_id=?
                         WHERE id=? AND state='pending'""",
            (json.dumps(result, ensure_ascii=False), units, source_id, call),
        ).rowcount
        if not settled:
            record_late_charge(db, call, units)
        elif kind == "asr":
            audit_asr(
                db,
                actor,
                reference,
                store.now(),
                f"记录 {label} 语音转写回执",
                audit_scope,
            )
    if not settled:
        raise ValueError("识别已进入平台对账")
    with closing(store.connect()) as db:
        authorize(db, token)
    return result
