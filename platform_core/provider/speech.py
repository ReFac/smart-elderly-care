"""Validate the paid speech tool's two encodings and bind a transcript to one care task."""

from contextlib import closing
import io
import json
import wave
import zlib

from .. import access
from ..care.records import lookup
from . import media


# Ogg uses a non-reflected CRC-32 without initial/final XOR. The standard library
# routine uses reflected bytes and the same polynomial (RFC 3533, section 6).
REVERSED_BITS = bytes(int(f"{n:08b}"[::-1], 2) for n in range(256))


def fix_page_checksum(data, start, end):
    pos = start + 22
    data[pos : pos + 4] = bytes(4)
    crc = zlib.crc32(data[start:end].translate(REVERSED_BITS), 0xFFFFFFFF) ^ 0xFFFFFFFF
    data[pos : pos + 4] = crc.to_bytes(4, "big").translate(REVERSED_BITS)


def audio_spec(raw):
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
                seconds = (n + rate - 1) // rate
        except (wave.Error, EOFError):
            raise ValueError("无法读取 WAV 音频") from None
        return "speech.wav", "audio/wav", seconds, safe.getvalue()
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
    return "speech.ogg", "audio/ogg", (samples + 47999) // 48000, bytes(upload)


def recognize(store, token, task_id, raw, consent):
    if consent is not True:
        raise ValueError("请确认提交这段录音给 DeepSeek 转写")

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
    filename, mime, seconds, upload = audio_spec(raw)

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
        seconds,
        filename,
        mime,
        authorize,
        parse,
        reference=task_id,
        upload=upload,
    )
    if not result["text"]:
        raise ValueError("DeepSeek 未识别到可用语音，请重新录制或手工录入")
    return result
