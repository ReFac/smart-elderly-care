"""Read an authenticated speaker's saved assistant reply with configured TTS."""

from contextlib import closing
from hashlib import sha256
from http.client import HTTPException
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener
from uuid import uuid4

from . import active, audio_adapters, deepseek, latest, local_time, read_key
from .media import ENDPOINT, record_late_charge

CHUNK = 600


def synthesize(key, text):
    body = json.dumps(
        {"text": text, "voice_id": "stella", "format": "wav", "filter_markdown": True}
    ).encode()
    req = Request(
        ENDPOINT + "tts",
        data=body,
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "audio/wav",
        },
    )
    with build_opener(deepseek.NoRedirect()).open(req, timeout=90) as res:
        return audio_adapters.wave_bytes(res)


def listen(store, token, payload, *, transport=None):
    from ..agents import chat
    from ..agents import chat_progress

    piece_key = "sentence" if "sentence" in payload else "part"
    if set(payload) != {"region", "scopeKey", "generation", "requestId", piece_key}:
        raise ValueError("请选择当前对话中的一条答复")
    part, request = payload[piece_key], payload["requestId"]
    progressive = piece_key == "sentence"
    if (
        type(part) is not int
        or not 0 <= part < (chat_progress.MAX_SENTENCES if progressive else 20)
        or not isinstance(request, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", request)
    ):
        raise ValueError("朗读位置无效")

    def authorized(db):
        actor, scope, _, _, _, thread = chat.conversation(
            store, db, token, payload["region"], payload["scopeKey"]
        )
        if not thread or thread["generation"] != payload["generation"]:
            raise PermissionError("对话已变化，请重新打开健康助理")
        row = db.execute(
            "SELECT answer,voice_receipt FROM assistant_turns WHERE actor=? AND scope=? AND generation=? AND request=?",
            (actor["id"], scope, thread["generation"], request),
        ).fetchone()
        uid = actor["id"]
        if row:
            if not row["voice_receipt"]:
                raise PermissionError("只有按住说话发送的语音答复可以朗读")
            if not progressive:
                return uid, row[0][part * CHUNK : (part + 1) * CHUNK]
            pieces = chat_progress.sentences(row[0], final=True)
            if part < len(pieces):
                return uid, pieces[part]
            raise ValueError("已到答复结尾")
        if progressive and thread["pending"] == request:
            piece = chat_progress.pending(store, uid, scope, thread["generation"], request, part)
            if piece:
                return uid, piece
        raise PermissionError("此账号无法朗读该答复")

    now = store.now()
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        uid, piece = authorized(db)
        if not piece:
            raise ValueError("已到答复结尾")
        plan = latest(db)
        if not active(plan, local_time(now).date().isoformat()):
            raise chat.Unavailable("机构云端套餐未启用，暂时无法朗读")
        try:
            service = audio_adapters.options("tts")
            key = service.key() if service else read_key()
        except (OSError, ValueError):
            raise chat.Unavailable("机构朗读服务配置不可用") from None
        signature = [uid, request, part, piece]
        if progressive:
            signature.append(piece_key)
        fingerprint = sha256(json.dumps(signature).encode()).hexdigest()
        if db.execute(
            """SELECT 1 FROM media_usage WHERE kind='tts' AND fingerprint=?
            AND state<>'rejected' AND NOT (state='reconciled' AND charged=0)""",
            (fingerprint,),
        ).fetchone():
            raise ValueError("这段朗读已请求，请查看当前答复")
        if db.execute(
            "SELECT 1 FROM media_usage WHERE kind='tts' AND actor=? AND state='pending' AND at>?",
            (uid, int(now.timestamp()) - 120),
        ).fetchone():
            raise ValueError("上一段朗读正在生成")
        ref = uuid4().hex
        units = sum(
            2 if "\u3400" <= c <= "\u9fff" or 0x20000 <= ord(c) <= 0x323AF else 1
            for c in piece
        )
        db.execute(
            """INSERT INTO media_usage(id,plan,kind,actor,fingerprint,at,state,reserved,reference,feature)
                      VALUES(?,?,'tts',?,?,?,'pending',?,?,'assistant.readAloud')""",
            (ref, plan["id"], uid, fingerprint, int(now.timestamp()), units, request),
        )
    try:
        if service and transport is None:
            raw = audio_adapters.synthesize(service, key, piece)
        else:
            raw = (transport or synthesize)(key, piece)
        status = "complete"
    except HTTPError as err:
        status = "rejected" if err.code in deepseek.REJECTED_HTTP else "uncertain"
        err.close()
    except (OSError, URLError, HTTPException, ValueError):
        status = "uncertain"
    with closing(store.connect()) as db, db:
        settled = db.execute(
            "UPDATE media_usage SET state=?,charged=? WHERE id=? AND state='pending'",
            (status, units if status == "complete" else 0, ref),
        ).rowcount
        if not settled and status == "complete":
            record_late_charge(db, ref, units)
    if not settled:
        raise chat.Unavailable("这段朗读已进入平台对账")
    if status != "complete":
        raise chat.Unavailable("朗读服务暂未返回可播放的音频")
    with closing(store.connect()) as db, db:
        authorized(db)
    return raw
