"""Operator-managed OpenAI audio and compatible speech gateways."""

from dataclasses import dataclass
import json
import os
import re
from urllib.request import Request
from uuid import uuid4

from . import connection

MAX_AUDIO = 20 * 1024 * 1024
OPENAI_AUDIO = {
    "asr": ("transcriptions", "gpt-transcribe"),
    "tts": ("speech", ""),
}
LABELS = {"deepseek": "DeepSeek", "openai": "OpenAI", "compatible": "兼容语音服务"}


@dataclass(frozen=True)
class AudioService:
    provider: str
    url: str
    model: str
    key_env: str
    voice: str = ""

    def key(self):
        return connection.environment_key(
            self.key_env, required=self.provider == "openai"
        )


def selected(kind):
    return (
        os.environ.get(f"NH_{kind.upper()}_PROVIDER", "deepseek").strip().lower()
        or "deepseek"
    )


def setting(name, default=""):
    value = os.environ.get(name, default).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", value):
        raise ValueError(f"语音服务配置无效（{name}）")
    return value


def options(kind):
    provider = selected(kind)
    if provider == "deepseek":
        return None
    prefix = f"NH_{kind.upper()}"
    if provider == "openai":
        path, model = OPENAI_AUDIO[kind]
        url = f"https://api.openai.com/v1/audio/{path}"
        key_env = "OPENAI_API_KEY"
    elif provider == "compatible":
        url = connection.endpoint(os.environ.get(prefix + "_ENDPOINT", "").strip())
        model = ""
        key_env = prefix + "_API_KEY"
    else:
        raise ValueError(f"语音服务配置无效（{prefix}_PROVIDER）")
    voice = setting("NH_TTS_VOICE", "alloy") if kind == "tts" else ""
    return AudioService(
        provider, url, setting(prefix + "_MODEL", model), key_env, voice
    )


def audio_request(url, body, content_type, accepts, key):
    headers = {"Content-Type": content_type, "Accept": accepts}
    if key:
        headers["Authorization"] = "Bearer " + key
    return Request(url, data=body, headers=headers, method="POST")


def transcribe(service, key, raw, filename, mime, duration_ms):
    boundary = "elderly-care-" + uuid4().hex
    fields = {"model": service.model, "response_format": "json"}
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        for name, value in fields.items()
    ]
    parts.extend(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {mime}\r\n\r\n".encode(),
            raw,
            f"\r\n--{boundary}--\r\n".encode(),
        )
    )
    req = audio_request(
        service.url,
        b"".join(parts),
        "multipart/form-data; boundary=" + boundary,
        "application/json",
        key,
    )
    limit = 256 * 1024
    with connection.open_request(req, timeout=185) as res:
        body = res.read(limit + 1)
        request_id = res.headers.get("x-request-id")
    if len(body) > limit:
        raise ValueError("识别回复超过上限")
    result = json.loads(body)
    if (
        not isinstance(result, dict)
        or "error" in result
        or not isinstance(result.get("text"), str)
    ):
        raise ValueError("识别回复无效")
    request_id = request_id or result.get("request_id") or result.get("id")
    if not isinstance(request_id, str) or not re.fullmatch(
        r"[A-Za-z0-9_.:-]{1,180}", request_id
    ):
        request_id = "local:" + uuid4().hex
    # Compatible gateways rarely return duration in a consistent unit. Meter the validated recording.
    return {
        "text": result["text"],
        "duration_ms": duration_ms,
        "request_id": request_id,
    }


def wave_bytes(res):
    audio = res.read(MAX_AUDIO + 1)
    if (
        len(audio) > MAX_AUDIO
        or len(audio) < 44
        or audio[:4] != b"RIFF"
        or audio[8:12] != b"WAVE"
    ):
        raise ValueError("朗读服务未返回完整音频")
    size = int.from_bytes(audio[4:8], "little")
    if size not in (0, 0xFFFFFFFF) and size + 8 > len(audio):
        raise ValueError("朗读音频传输中断")
    return audio


def synthesize(service, key, text):
    body = json.dumps(
        {
            "model": service.model,
            "input": text,
            "voice": service.voice,
            "response_format": "wav",
        }
    ).encode()
    req = audio_request(service.url, body, "application/json", "audio/wav", key)
    with connection.open_request(req, timeout=90) as res:
        return wave_bytes(res)
