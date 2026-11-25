"""A single bounded provider call. Only controlled task vocabulary may leave the host."""

from dataclasses import dataclass
from http.client import HTTPException
import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import token_receipt

ENDPOINT = "https://api.deepseek.com/chat/completions"
MAX_REPLY_BYTES = 32 * 1024
REJECTED_HTTP = frozenset((400, 401, 402, 403, 404, 405, 413, 415, 422, 429))

# Match short domain phrases locally, including common aliases. Never splice user text
# or institution records into a model prompt. New vocabulary is an explicit code change.
SIGNALS = {
    "care": (
        "交班",
        "签收",
        "接班",
        "交接",
        "照护",
        "护理",
        "工单",
        "评估",
        "巡房",
        "巡视",
        "复评",
        "照料",
        "护理计划",
    ),
    "inventory": (
        "库存",
        "物资",
        "补货",
        "领用",
        "耗材",
        "仓储",
        "采购",
        "盘点",
        "缺货",
        "消耗",
    ),
    "finance": (
        "财务",
        "欠费",
        "账单",
        "账款",
        "营收",
        "收入",
        "实收",
        "收款",
        "入款",
        "收费",
        "结算",
        "经营",
        "对账",
        "收款",
    ),
}


def request_body(model, goal, specialists):
    tags = []
    for item in specialists:
        for word in SIGNALS.get(item.key, ()):
            if word in goal:
                tags.append((goal.index(word), word))
    if not tags:
        return None
    domains = [item.key for item in specialists]
    prompt = {
        "allowed": domains,
        "signals": list(dict.fromkeys(word for _, word in sorted(tags)))[:12],
    }
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": 'Route nursing-home task signals to matching allowed domains only. Return JSON as {"ids":["care"]}. No prose.',
            },
            {
                "role": "user",
                "content": json.dumps(
                    prompt, ensure_ascii=False, separators=(",", ":")
                ),
            },
        ],
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "max_tokens": 32,
        "stream": False,
    }


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def send(key, body, *, timeout=8):
    request = Request(
        ENDPOINT,
        method="POST",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
        raw = response.read(MAX_REPLY_BYTES + 1)
        if len(raw) > MAX_REPLY_BYTES:
            raise ValueError("模型响应超出范围")
        return json.loads(raw)


def stream(key, body, received, *, timeout=60):
    """Relay only answer text and return the same final receipt shape as send()."""
    payload = {**body, "stream": True, "stream_options": {"include_usage": True}}
    req = Request(
        ENDPOINT, method="POST", data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                 "Accept": "text/event-stream"},
    )
    with build_opener(NoRedirect()).open(req, timeout=timeout) as response:
        return read_chat_stream(response, received)


def data_lines(response):
    transferred = 0
    while raw := response.readline(MAX_REPLY_BYTES + 1):
        transferred += len(raw)
        if len(raw) > MAX_REPLY_BYTES or transferred > 2 * 1024 * 1024:
            raise ValueError("云端回复超出流式限制")
        if raw.startswith(b"data:"):
            yield raw[5:].strip()


def read_chat_stream(response, received, *, allow_terminal_eof=False):
    pieces, finish, usage = [], None, None
    length = 0
    for data in data_lines(response):
        if data == b"[DONE]":
            if finish is not None:
                break
            raise ValueError("云端回复缺少结束状态")
        chunk = json.loads(data)
        if chunk.get("usage") is not None:
            usage = chunk["usage"]
        for choice in chunk.get("choices", []):
            delta = choice.get("delta") or {}
            part = delta.get("content")
            if choice.get("index", 0) != 0 or delta.get("tool_calls"):
                raise ValueError("文字回复流格式无效")
            if part:
                if not isinstance(part, str):
                    raise ValueError("云端回复分段无效")
                length += len(part)
                if length > 12000:
                    raise ValueError("云端回复文字过长")
                pieces.append(part)
                if finish is None:
                    received(part)
            if choice.get("finish_reason") is not None:
                finish = choice["finish_reason"]
    else:
        if not (allow_terminal_eof and finish is not None and usage):
            raise ValueError("云端回复流提前结束")
    return {"usage": usage, "choices": [{
        "finish_reason": finish, "message": {"content": "".join(pieces)},
    }]}


@dataclass(frozen=True)
class Outcome:
    status: str
    reason: str
    tokens: int = 0
    ids: tuple = ()
    receipt: token_receipt.TokenReceipt | None = None


def complete(transport, key, body, allowed, *, allowance=1_000_000):
    try:
        result = transport(key, body)
    except HTTPError as err:
        err.close()
        if err.code in REJECTED_HTTP:
            return Outcome("closed", "provider_rejected")
        return Outcome("uncertain", "provider_unavailable")
    except (HTTPException, URLError, OSError, ValueError, RecursionError):
        return Outcome("uncertain", "provider_unavailable")
    receipt = token_receipt.read(result, allowance)
    if receipt is None:
        return Outcome("uncertain", "usage_unknown")
    try:
        choice = result["choices"][0]
        if choice["finish_reason"] != "stop":
            raise ValueError
        content = json.loads(choice["message"]["content"])
        if set(content) != {"ids"}:
            raise ValueError
        ids = content["ids"]
        if not isinstance(ids, list) or not 1 <= len(ids) <= len(allowed):
            raise ValueError
        if not all(isinstance(key, str) and key in allowed for key in ids) or len(
            set(ids)
        ) != len(ids):
            raise ValueError
    except (KeyError, IndexError, TypeError, ValueError, RecursionError):
        return Outcome("closed", "invalid_output", receipt.total, receipt=receipt)
    return Outcome("ok", "ready", receipt.total, tuple(ids), receipt)
