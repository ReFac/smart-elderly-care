"""Validate the paid speech tool's two encodings and bind transcripts to their authorized care task or Agent region."""

from contextlib import closing
from hashlib import sha256
import io
import json
import wave
import zlib

from .. import access
from ..care.records import lookup
from . import audio_adapters, media


# Ogg uses a non-reflected CRC-32 without initial/final XOR. The standard library
# routine uses reflected bytes and the same polynomial (RFC 3533, section 6).
REVERSED_BITS = bytes(int(f"{n:08b}"[::-1], 2) for n in range(256))


def fix_page_checksum(data, start, end):
    pos = start + 22
    data[pos : pos + 4] = bytes(4)
    crc = zlib.crc32(data[start:end].translate(REVERSED_BITS), 0xFFFFFFFF) ^ 0xFFFFFFFF
    data[pos : pos + 4] = crc.to_bytes(4, "big").translate(REVERSED_BITS)


def audio_spec(raw):
    filename, mime, ms, upload = audio_details(raw)
    return filename, mime, (ms + 999) // 1000, upload


def audio_details(raw):
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 8 * 1024 * 1024:
        raise ValueError("录音大小须在 8 MiB 以内")
    if raw.startswith(b"RIFF"):
        try:
            with wave.open(io.BytesIO(raw), "rb") as source:
                n = source.getnframes()
                rate = source.getframerate()
                channels = source.getnchannels()
                if (
                    source.getsampwidth() != 2
                    or rate not in (8000, 16000, 22050, 24000, 32000, 44100, 48000)
                    or channels not in (1, 2)
                    or not 0 < n <= rate * 120
                ):
                    raise ValueError("请选择 120 秒以内的 16 位 PCM WAV 录音")
                pcm = source.readframes(n)
                if len(pcm) != n * 2 * channels:
                    raise ValueError("WAV 音频不完整")
                # Rebuild from sample frames; RIFF tags may contain names and comments.
                safe = io.BytesIO()
                with wave.open(safe, "wb") as output:
                    output.setparams(source.getparams())
                    output.writeframes(pcm)
                ms = (n * 1000 + rate - 1) // rate
        except (wave.Error, EOFError):
            raise ValueError("无法读取 WAV 音频") from None
        return "speech.wav", "audio/wav", ms, safe.getvalue()
    offset = 0
    stream = preskip = last = None
    eos = tags_done = False
    tag_bytes = 0
    upload = bytearray(raw)
    while offset < len(raw):
        head = raw[offset : offset + 27]
        if len(head) != 27 or head[:5] != b"OggS\0" or eos:
            raise ValueError("请选择完整的单轨 Ogg Opus 或 16 位 PCM WAV 录音")
        end = offset + 27 + head[26]
        size = sum(raw[offset + 27 : end])
        if end + size > len(raw) or end > len(raw):
            raise ValueError("Ogg 音频不完整")
        if offset == 0:
            packet = raw[end : end + size]
            if (
                not head[5] & 2
                or len(packet) < 19
                or not packet.startswith(b"OpusHead")
                or packet[9] not in (1, 2)
            ):
                raise ValueError("Ogg 文件须使用单声道或双声道 Opus 编码")
            preskip = int.from_bytes(packet[10:12], "little")
            stream = head[14:18]
            if len(packet) != (19 if packet[18] == 0 else 21 + packet[9]):
                raise ValueError("Opus 声道映射格式无效")
        elif not tags_done:
            # Remove the second packet's OpusTags vendor, comments, artwork and padding.
            # Keeping its size preserves all lacing, page sequence and audio packets.
            pos = end
            for length in raw[offset + 27 : end]:
                if tag_bytes == 0 and (
                    length < 16 or raw[pos : pos + 8] != b"OpusTags"
                ):
                    raise ValueError("录音缺少有效的 Opus 标签头")
                keep = 8 if tag_bytes == 0 else 0
                upload[pos + keep : pos + length] = bytes(length - keep)
                tag_bytes += length
                pos += length
                if length < 255:
                    tags_done = True
                    break
            fix_page_checksum(upload, offset, end + size)
        if head[14:18] != stream:
            raise ValueError("请使用单个音频流")
        eos = bool(head[5] & 4)
        last = int.from_bytes(head[6:14], "little", signed=True)
        offset = end + size
    samples = last - preskip if eos else 0
    if not tags_done or not 0 < samples <= 120 * 48000:
        raise ValueError("录音时长须在 120 秒以内")
    return "speech.ogg", "audio/ogg", (samples + 47) // 48, bytes(upload)


def recognize(store, token, task_id, raw, consent):
    if consent is not True:
        raise ValueError("请确认由机构配置的语音服务转写这段录音")

    def authorize(db, session):
        from ..campus_access import require_resident

        user = store.actor(db, session)
        access.require(user, "care")
        access.require(user, "voice")
        state = json.loads(
            db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
        )
        task = lookup(state, "tasks", task_id)
        require_resident(db, user, task["residentId"], state)
        person = lookup(state, "residents", task["residentId"])
        if (
            person["status"] != "在住"
            or task["status"] != "待执行"
            or task["date"] > store.now().date().isoformat()
        ):
            raise ValueError("请选择当前可办理的照护工单")
        return user

    with closing(store.connect()) as db:
        authorize(db, token)
    return transcribe(store, token, task_id, raw, authorize, feature="care.taskAsr")


def agent_capability(db, now):
    from . import configured, latest, local_time

    plan = latest(db)
    today = local_time(now).date().isoformat()
    status = "available"
    if (
        not plan
        or not plan["enabled"]
        or not plan["startsOn"] <= today <= plan["expiresOn"]
    ):
        status = "inactive"
    elif not db.execute("SELECT asr FROM media_policy WHERE id=1").fetchone()[0]:
        status = "disabled"
    else:
        allowance = media.amounts(db, plan["id"], "asr")
        if not media.can_reserve(allowance, 1):
            status = "exhausted"
        else:
            try:
                service = audio_adapters.options("asr")
                if service:
                    service.key()
                elif not configured():
                    status = "unconfigured"
            except (OSError, ValueError):
                status = "unconfigured"
    return {
        "path": "/api/agent/voice/transcriptions",
        "method": "POST",
        "regionFields": ["campusId", "buildingId", "floorId", "roomId"],
        "state": status,
        "maxSeconds": 120,
        "requiresConsent": True,
        "provider": audio_adapters.LABELS.get(audio_adapters.selected("asr"), "机构语音服务"),
    }


def agent_context(db, user, selected):
    from .. import agents
    from ..agents import region

    if user["kind"] not in ("owner", "staff"):
        raise PermissionError("仅在岗工作人员可使用 Agent 工作台")
    access.require(user, "assistants")
    access.require(user, "voice")
    area = region.resolve(db, region.EMPTY_STATE, user, selected)
    domains = [
        s.key
        for s in agents.specialists(user)
        if not area or s.key in ("care", "finance")
    ]
    if not domains:
        raise PermissionError("此岗位在所选区域没有可用的专员")
    rooms = area["roomIds"] if area else []
    # Different effective room or specialist permissions cannot replay an old transcript.
    identity = json.dumps(
        [selected, domains, rooms], sort_keys=True, separators=(",", ":")
    )
    return "agent:" + ",".join(domains) + ":" + sha256(
        identity.encode()
    ).hexdigest(), area


def chat_voice_context(db, user, selected):
    from .. import campus_access, facility
    from ..agents import region

    if user["kind"] not in ("owner", "staff"):
        raise PermissionError("此账号没有语音输入权限")
    access.require(user, "voice")
    chosen = (
        facility.scope(db, region.EMPTY_STATE, user, agent=True, **selected)
        if selected
        else None
    )
    assigned = campus_access.allowed_beds(db, user, include_rooms=True)
    signature = json.dumps(
        [
            user["id"],
            sorted(user["permissions"]),
            user.get("facilityScope"),
            sorted(assigned) if assigned is not None else None,
            chosen and chosen["roomIds"],
        ],
        sort_keys=True,
    ).encode()
    selection = json.dumps(selected, sort_keys=True, separators=(",", ":"))
    return "chat-voice:" + sha256(signature).hexdigest() + ":" + selection, chosen


def can_read_agent_history(db, user, revision):
    from .. import agents

    if not access.has(user, "voice"):
        return False
    row = db.execute(
        """SELECT m.reference FROM history_targets t JOIN media_usage m ON m.id=t.entity
        WHERE t.kind='entity/media_usage' AND t.revision=? AND m.actor=?""",
        (revision, user["id"]),
    ).fetchone()
    if not row:
        return False
    if row[0].startswith("chat-voice:"):
        try:
            return (
                chat_voice_context(db, user, json.loads(row[0].split(":", 2)[2]))[0]
                == row[0]
            )
        except (ValueError, PermissionError, FileNotFoundError, IndexError):
            return False
    parts = row[0].split(":")
    return (
        len(parts) == 3
        and parts[0] == "agent"
        and set(parts[1].split(",")) <= {s.key for s in agents.specialists(user)}
    )


def recognize_agent(store, token, selected, raw, consent, *, conversation=False):
    from ..agents import region

    if consent is not True:
        raise ValueError("请确认由机构配置的语音服务转写这段录音")
    selected = region.selection(selected) if selected is not None else None
    context = chat_voice_context if conversation else agent_context
    with closing(store.connect()) as db:
        reference, area = context(db, store.actor(db, token), selected)
    audit_scope = {}
    if area:
        audit_scope = {"roomIds": area["roomIds"], "campusId": area["campusId"]}
        if area.get("roomId"):
            audit_scope["room"] = area["label"]

    def authorize(db, session):
        user = store.actor(db, session)
        current, _ = context(db, user, selected)
        if current != reference:
            raise PermissionError("工作区域或语音权限已变化，请重新核对")
        return user

    return transcribe(
        store,
        token,
        reference,
        raw,
        authorize,
        audit_scope,
        feature="assistant.voiceAsr" if conversation else "agent.voiceAsr",
    )


def require_agent_receipt(db, user, selected, receipt):
    reference, _ = agent_context(db, user, selected)
    if (
        not isinstance(receipt, str)
        or len(receipt) != 32
        or not db.execute(
            """SELECT 1 FROM media_usage WHERE id=? AND actor=? AND reference=?
             AND kind='asr' AND state='complete'""",
            (receipt, user["id"], reference),
        ).fetchone()
    ):
        raise ValueError("语音回执与经办人或工作区域不匹配")


def require_chat_receipt(db, user, selected, receipt):
    from ..agents import region

    selected = region.selection(selected) if selected else None
    reference, _ = chat_voice_context(db, user, selected)
    if (
        not isinstance(receipt, str)
        or len(receipt) != 32
        or not db.execute(
            """SELECT 1 FROM media_usage WHERE id=? AND actor=? AND reference=?
               AND kind='asr' AND state='complete' AND feature='assistant.voiceAsr'""",
            (receipt, user["id"], reference),
        ).fetchone()
    ):
        raise PermissionError("朗读只用于本人在当前对话里按住说话的语音消息")


def transcribe(store, token, reference, raw, authorize, audit_scope=None, *, feature):
    filename, mime, duration_ms, upload = audio_details(raw)

    def parse(obj):
        words = obj["text"]
        ms = obj["duration_ms"]
        if (
            not isinstance(words, str)
            or len(words) > 16000
            or type(ms) is not int
            or not 0 < ms <= 120000
        ):
            raise ValueError("转写回执无效")
        return (
            {"text": words.strip(), "durationMs": ms},
            (ms + 999) // 1000,
            obj["request_id"],
        )

    result = media.execute(
        store,
        token,
        "asr",
        raw,
        (duration_ms + 999) // 1000,
        filename,
        mime,
        authorize,
        parse,
        feature=feature,
        reference=reference,
        upload=upload,
        audit_scope=audit_scope,
        duration_ms=duration_ms,
    )
    if not result["text"]:
        raise ValueError("语音服务未识别到可用语音，请重新录制或手工录入")
    return result
