"""Authenticated DeepSeek search and connectivity checks with fixed destinations."""

from http.client import HTTPException
from ipaddress import ip_address
import json
import re
import socket
import ssl
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from . import model_name
from .deepseek import NoRedirect


MODELS_URL = "https://api.deepseek.com/models"
SEARCH_URL = "https://api.deepseek.com/v1/tools/search"
MAX_RESULTS = 5
MAX_RESULTS_BYTES = 8192
MAX_RESPONSE_BYTES = 192 * 1024

MESSAGES = {
    "credentials": "平台的 DeepSeek 凭据尚未配置或验证失败，请联系管理员。",
    "query": "请输入 1 至 128 个字符的公开搜索词。",
    "timeout": "连接 DeepSeek 超时，请稍后重试。",
    "network": "无法连接 DeepSeek，请检查机构服务器的网络。",
    "rejected": "DeepSeek 拒绝了本次请求，请稍后重试或联系管理员。",
    "balance": "DeepSeek 平台余额不足，请联系管理员。",
    "rate_limited": "联网请求太频繁，请稍后再试。",
    "invalid_response": "DeepSeek 返回的数据不完整，请稍后重试。",
    "invalid_sources": "此次搜索未获得可显示的公开网页，请更换关键词。",
    "model_unavailable": "已连接 DeepSeek，当前凭据无法访问机构配置的模型。",
}


class WebSearchError(ValueError):
    """billed denotes one billable standalone search, zero, or an unknown outcome."""

    def __init__(self, code, *, billed=False):
        super().__init__(MESSAGES[code])
        self.code = code
        self.billed = billed


def _request(endpoint, key, payload=None):
    if not isinstance(key, str) or not key or not re.fullmatch(r"[!-~]+", key):
        raise WebSearchError("credentials")
    data = (
        json.dumps(payload, ensure_ascii=False).encode()
        if payload is not None
        else None
    )
    headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(endpoint, headers=headers, data=data)
    unknown = None if data is not None else False
    try:
        with build_opener(NoRedirect()).open(
            request, timeout=15 if data else 5
        ) as response:
            if response.status != 200:
                raise WebSearchError("rejected")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise WebSearchError("invalid_response", billed=unknown)
        result = json.loads(raw)
    except HTTPError as exc:
        exc.close()
        code = {
            401: "credentials",
            402: "balance",
            408: "timeout",
            429: "rate_limited",
            504: "timeout",
        }.get(exc.code, "rejected")
        # A provider HTTP error is explicitly unbilled. A local connection loss may
        # instead have happened after the provider completed the submitted search.
        raise WebSearchError(code) from None
    except URLError as exc:
        code = "timeout" if isinstance(exc.reason, TimeoutError) else "network"
        if isinstance(
            exc.reason,
            (socket.gaierror, ssl.SSLCertVerificationError, ConnectionRefusedError),
        ):
            unknown = False
        raise WebSearchError(code, billed=unknown) from None
    except TimeoutError:
        raise WebSearchError("timeout", billed=unknown) from None
    except (HTTPException, OSError):
        raise WebSearchError("network", billed=unknown) from None
    except WebSearchError:
        raise
    except (ValueError, RecursionError):
        raise WebSearchError("invalid_response", billed=unknown) from None
    if not isinstance(result, dict):
        raise WebSearchError("invalid_response", billed=unknown)
    return result


def probe(key):
    """Check the TLS endpoint, authentication and configured model without inference."""
    models = _request(MODELS_URL, key).get("data")
    if not isinstance(models, list):
        raise WebSearchError("invalid_response")
    model = model_name()
    if not any(isinstance(item, dict) and item.get("id") == model for item in models):
        raise WebSearchError("model_unavailable")
    return {"connected": True, "model": model}


def _public_url(value):
    # Links are returned for display only. The service does not visit search results.
    if not isinstance(value, str) or not 1 <= len(value) <= 2048 or "\\" in value:
        return False
    if any(
        char.isspace() or unicodedata.category(char).startswith("C") for char in value
    ):
        return False
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        if (
            parts.scheme not in ("https", "http")
            or parts.username is not None
            or not host
        ):
            return False
        if parts.port == 0 or "%" in host:
            return False
        try:
            address = ip_address(host)
            return address.is_global and not address.is_multicast
        except ValueError:
            pass
        labels = host.split(".")
        if len(labels) < 2 or host.endswith(
            (".localhost", ".local", ".lan", ".internal", ".home.arpa")
        ):
            return False
        # Browsers interpret a numeric last label (including 0x…) as an IPv4 address.
        if re.fullmatch(r"[0-9]+|0x[0-9a-f]*", labels[-1]):
            return False
        return all(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", s) for s in labels
        )
    except (ValueError, UnicodeError):
        return False


def _label(value, limit):
    if not isinstance(value, str):
        return ""
    value = "".join(
        " " if unicodedata.category(c).startswith("C") else c for c in value
    )
    return " ".join(value.split())[:limit]


def search(key, query):
    """Send the explicit public search query only. An empty list is an unbilled miss."""
    if not isinstance(query, str):
        raise WebSearchError("query")
    query = query.strip()
    if not 1 <= len(query) <= 128 or any(
        unicodedata.category(c) in ("Cc", "Cs") for c in query
    ):
        raise WebSearchError("query")
    rows = _request(
        SEARCH_URL, key, {"query": query, "count": MAX_RESULTS, "need_content": False}
    ).get("results")
    if not isinstance(rows, list):
        raise WebSearchError("invalid_response", billed=None)
    visible, seen = [], set()
    for entry in rows[:MAX_RESULTS]:
        if not isinstance(entry, dict):
            continue
        url = entry.get("url")
        if not _public_url(url) or url in seen:
            continue
        item = {
            "title": _label(entry.get("title"), 160) or urlsplit(url).hostname,
            "url": url,
            "snippet": _label(entry.get("snippet"), 320),
        }
        size = len(
            json.dumps(
                [*visible, item], ensure_ascii=False, separators=(",", ":")
            ).encode()
        )
        if size <= MAX_RESULTS_BYTES:
            visible.append(item)
            seen.add(url)
    if rows and not visible:
        raise WebSearchError("invalid_sources", billed=True)
    return visible
