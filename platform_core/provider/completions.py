"""Normalize hosted chat contracts for the metered application runtime."""

import json
import os
import re
from urllib.request import Request

from . import connection, deepseek


CHAT_ENDPOINTS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
}
KEY_NAMES = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GEMINI_API_KEY",
}
ANTHROPIC_FINISH = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "refusal": "content_filter",
}
GEMINI_REASONING_MODELS = re.compile(r"(?:models/)?gemini-(?:2\.5|[3-9]\d*)(?:[.-]|$)")


def provider_name():
    return os.environ.get("NH_CHAT_PROVIDER", "deepseek").strip().lower()


def model_name(default):
    kind = provider_name()
    if kind == "deepseek":
        return default
    model = os.environ.get("NH_CHAT_MODEL", "").strip()
    if kind in CHAT_ENDPOINTS and re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9./:_-]{0,179}", model
    ):
        return model
    return ""


def read_key():
    kind = provider_name()
    if not model_name("") or kind not in KEY_NAMES:
        raise ValueError("平台模型配置无效")
    name = KEY_NAMES[kind]
    if kind == "google" and not os.environ.get(name, "").strip():
        name = "GOOGLE_API_KEY"
    return connection.environment_key(name)


def _gemini_reasoning_model(kind, body):
    return kind == "google" and GEMINI_REASONING_MODELS.match(body["model"])


def output_budget(body):
    # Gemini's maximum covers billed reasoning and the visible answer together.
    extra = 2048 if _gemini_reasoning_model(provider_name(), body) else 0
    return body["max_tokens"] + extra


def _anthropic_body(body):
    instructions, messages = [], []
    for message in body["messages"]:
        role = message["role"]
        content = message.get("content")
        if role == "system":
            instructions.append(content)
            continue
        if role == "tool":
            role = "user"
            blocks = [
                {
                    "type": "tool_result",
                    "tool_use_id": message["tool_call_id"],
                    "content": content,
                }
            ]
        else:
            blocks = [{"type": "text", "text": content}] if content else []
            for call in message.get("tool_calls", []):
                function = call["function"]
                arguments = json.loads(function["arguments"])
                if not isinstance(arguments, dict):
                    raise ValueError("工具参数须为 JSON 对象")
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call["id"],
                        "name": function["name"],
                        "input": arguments,
                    }
                )
        if blocks:
            if messages and messages[-1]["role"] == role:
                messages[-1]["content"].extend(blocks)
            else:
                messages.append({"role": role, "content": blocks})
    if body.get("response_format") == {"type": "json_object"}:
        instructions.append(
            "输出单个符合要求的 JSON 对象，省略 Markdown 围栏和其他文字。"
        )
    request = {
        "model": body["model"],
        "max_tokens": body["max_tokens"],
        "messages": messages,
    }
    if instructions:
        request["system"] = "\n\n".join(instructions)
    tools = []
    for tool in body.get("tools", []):
        function = tool["function"]
        tools.append(
            {
                "name": function["name"],
                "description": function["description"],
                "input_schema": function["parameters"],
            }
        )
    if tools:
        request["tools"] = tools
        choice = body.get("tool_choice", "auto")
        request["tool_choice"] = {"type": "any" if choice == "required" else choice}
    return request


def _anthropic_usage(fields):
    if not isinstance(fields, dict):
        return None
    regular = fields.get("input_tokens")
    cache_writes = fields.get("cache_creation_input_tokens", 0)
    cache_reads = fields.get("cache_read_input_tokens", 0)
    output = fields.get("output_tokens")
    if any(
        type(value) is not int or value < 0
        for value in (regular, cache_writes, cache_reads, output)
    ):
        return None
    uncached = regular + cache_writes
    prompt = uncached + cache_reads
    return {
        "prompt_tokens": prompt,
        "completion_tokens": output,
        "total_tokens": prompt + output,
        "prompt_cache_hit_tokens": cache_reads,
        "prompt_cache_miss_tokens": uncached,
    }


def _anthropic_response(raw):
    result = {"usage": _anthropic_usage(raw.get("usage"))}
    blocks = raw.get("content")
    if not isinstance(blocks, list) or any(
        not isinstance(block, dict) for block in blocks
    ):
        return result
    message, pieces, calls = {"role": "assistant"}, [], []
    for block in blocks:
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            pieces.append(block["text"])
        if block.get("type") == "tool_use":
            identifier, name, arguments = (
                block.get("id"),
                block.get("name"),
                block.get("input"),
            )
            if (
                not isinstance(identifier, str)
                or not isinstance(name, str)
                or not isinstance(arguments, dict)
            ):
                return result
            calls.append(
                {
                    "id": identifier,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }
            )
    message["content"] = "".join(pieces) if pieces else None
    if calls:
        message["tool_calls"] = calls
    stop_reason = raw.get("stop_reason")
    finish = ANTHROPIC_FINISH.get(stop_reason) if isinstance(stop_reason, str) else None
    result["choices"] = [{"finish_reason": finish, "message": message}]
    return result


def _request(kind, key, body):
    if kind not in CHAT_ENDPOINTS:
        raise ValueError("平台模型配置无效")
    url = CHAT_ENDPOINTS[kind]
    if kind == "anthropic":
        return (
            url,
            _anthropic_body(body),
            {"x-api-key": key, "anthropic-version": "2023-06-01"},
        )
    payload = {
        field: body[field]
        for field in ("model", "messages", "tools", "tool_choice", "response_format")
        if field in body
    }
    payload["max_completion_tokens" if kind == "openai" else "max_tokens"] = (
        output_budget(body)
    )
    if _gemini_reasoning_model(kind, body):
        payload["reasoning_effort"] = "minimal"
    if kind == "openai":
        payload["store"] = False
    return url, payload, {"Authorization": "Bearer " + key}


def send(key, body, *, timeout=8):
    kind = provider_name()
    if kind == "deepseek":
        return deepseek.send(key, body, timeout=timeout)
    response = connection.json_request(*_request(kind, key, body), timeout=timeout)
    return _anthropic_response(response) if kind == "anthropic" else response


def _anthropic_stream(response, received):
    usage, pieces, finish = {}, [], None
    length = 0
    for line in deepseek.data_lines(response):
        event = json.loads(line)
        kind = event.get("type")
        if kind == "message_start":
            usage.update(event["message"]["usage"])
            usage.pop("output_tokens", None)
        elif kind == "message_delta":
            usage.update(event.get("usage", {}))
            finish = event["delta"].get("stop_reason") or finish
        elif kind == "message_stop" and finish:
            return _anthropic_response(
                {
                    "usage": usage,
                    "stop_reason": finish,
                    "content": [{"type": "text", "text": "".join(pieces)}],
                }
            )
        elif kind == "error":
            raise ValueError("云端回复流提前结束")
        elif kind in ("content_block_start", "content_block_delta"):
            block = event["content_block" if kind == "content_block_start" else "delta"]
            if block.get("type") == "tool_use":
                raise ValueError("文字回复流格式无效")
            if block.get("type") in ("text", "text_delta"):
                part = block["text"]
                if not isinstance(part, str):
                    raise ValueError("云端回复分段无效")
                length += len(part)
                if length > 12000:
                    raise ValueError("云端回复文字过长")
                if part:
                    pieces.append(part)
                    received(part)
    raise ValueError("云端回复流提前结束")


def stream(key, body, received, *, timeout=None):
    kind = provider_name()
    if kind == "deepseek":
        options = {"timeout": timeout} if timeout is not None else {}
        return deepseek.stream(key, body, received, **options)
    url, payload, headers = _request(kind, key, body)
    payload["stream"] = True
    if kind != "anthropic":
        payload["stream_options"] = {"include_usage": True}
    request = Request(
        url,
        method="POST",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            **headers,
        },
    )
    with connection.open_request(request, timeout=timeout or 60) as response:
        if kind == "anthropic":
            return _anthropic_stream(response, received)
        return deepseek.read_chat_stream(
            response, received, allow_terminal_eof=kind == "google"
        )
