"""Operator-configured HTTP transport for model and media adapters."""

import ipaddress
import json
import os
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from ..operational_secrets import valid_key
from .deepseek import NoRedirect


def _loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def endpoint(value):
    if (
        not isinstance(value, str)
        or not value
        or not value.isascii()
        or any(ord(char) <= 32 or ord(char) == 127 or char in "\\?#" for char in value)
    ):
        raise ValueError("服务地址格式无效")
    try:
        parts = urlsplit(value)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise ValueError("服务地址格式无效") from None
    if (
        not host
        or parts.username is not None
        or "%" in host
        or port == 0
        or (
            parts.scheme != "https" and not (parts.scheme == "http" and _loopback(host))
        )
    ):
        raise ValueError("服务地址须使用 HTTPS，本机地址可使用 HTTP")
    return value


def environment_key(name, *, required=True):
    value = os.environ.get(name, "").strip()
    if not value and not required:
        return ""
    if not valid_key(value):
        raise ValueError("平台服务凭据不可用")
    return value


def open_request(request, *, timeout):
    parts = urlsplit(endpoint(request.full_url))
    handlers = [NoRedirect()]
    if _loopback(parts.hostname):
        handlers.append(ProxyHandler({}))
    return build_opener(*handlers).open(request, timeout=timeout)


def json_request(url, body, headers, *, timeout, max_bytes=32 * 1024):
    request = Request(
        url,
        method="POST",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **headers,
        },
    )
    with open_request(request, timeout=timeout) as response:
        raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("模型响应超出范围")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("模型响应格式无效")
    return result
