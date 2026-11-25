"""Curated, read-only MCP connectors for the institutional assistant.

The official SDK owns discovery, negotiation and transport. Only an operator can
register a server. Model-visible arguments are limited to typed reference values.
"""
import asyncio
from contextlib import AsyncExitStack
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import stat
import sys
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore
from urllib.parse import urlsplit

from .. import access_policy

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "docs/examples/workspace-mcp.json"
if not DEFAULT_CONFIG.is_file():
    DEFAULT_CONFIG = Path(__file__).parent / "bundled/workspace-mcp.json"
ID = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,39}")
CLOCK = r"(?:[01][0-9]|2[0-3]):[0-5][0-9]"
SLOTS = BoundedSemaphore(2)
MAX_OUTPUT = 8192
TIMEOUT = 12


def _fields(definitions):
    fields = {}
    if not isinstance(definitions, dict) or len(definitions) > 10:
        raise ValueError("MCP 工具参数配置无效")
    for name, rule in definitions.items():
        if not ID.fullmatch(name) or not isinstance(rule, dict):
            raise ValueError("MCP 工具参数配置无效")
        kind = rule.get("type")
        if kind == "string" and rule.get("format") == "time":
            fields[name] = {"type": "string", "pattern": "^" + CLOCK + "$"}
        elif kind == "string":
            choices = rule.get("enum")
            if not isinstance(choices, list) or not 1 <= len(choices) <= 100 or not all(
                isinstance(choice, str) and 0 < len(choice) <= 80 for choice in choices
            ):
                raise ValueError("MCP 文本参数需要运营方指定选项")
            fields[name] = {"type": "string", "enum": choices}
        elif kind == "integer":
            lo, hi = rule.get("minimum"), rule.get("maximum")
            if type(lo) is not int or type(hi) is not int or not -10_000 <= lo <= hi <= 10_000:
                raise ValueError("MCP 数值参数需要指定范围")
            fields[name] = {"type": "integer", "minimum": lo, "maximum": hi}
        elif kind == "boolean":
            fields[name] = {"type": "boolean"}
        else:
            raise ValueError("MCP 参数类型无效")
    return fields


@dataclass(frozen=True)
class Tool:
    server: str
    remote: str
    title: str
    description: str
    grant: str
    keywords: tuple
    endpoint: dict
    schema: dict
    fixed: dict

    @property
    def name(self):
        return f"mcp_{self.server}_{self.remote}"

    def function(self):
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                  "parameters": deepcopy(self.schema)}}

    def read(self):
        return self.execute({})

    def execute(self, arguments):
        fields = self.schema["properties"]
        if (not isinstance(arguments, dict) or set(arguments) - fields.keys()
                or not set(self.schema["required"]).issubset(arguments)):
            raise ValueError("MCP 工具参数不在授权范围")
        for name, value in arguments.items():
            spec = fields[name]
            if spec["type"] == "integer":
                valid = type(value) is int and spec["minimum"] <= value <= spec["maximum"]
            elif spec["type"] == "boolean":
                valid = type(value) is bool
            elif "enum" in spec:
                valid = isinstance(value, str) and value in spec["enum"]
            else:
                valid = isinstance(value, str) and re.fullmatch(CLOCK, value) is not None
            if not valid:
                raise ValueError("MCP 工具参数不在授权范围")
        if not SLOTS.acquire(blocking=False):
            raise ValueError("机构工具正在处理其他查询，请稍后再试")
        try:
            return asyncio.run(_invoke(self, {**self.fixed, **arguments}))
        except (ImportError, TimeoutError) as exc:
            raise ValueError("机构工具尚未安装或连接超时，请联系管理员") from exc
        except Exception:
            raise ValueError("机构工具未能完成本次查询，请重试或联系管理员") from None
        finally:
            SLOTS.release()


def _endpoint(config):
    transport = config.get("transport", "stdio")
    if transport == "stdio":
        command = config.get("command")
        args = config.get("args", [])
        if not isinstance(command, str) or (command != "python" and not Path(command).is_absolute()):
            raise ValueError("请配置 MCP 服务的可执行文件绝对路径")
        if not isinstance(args, list) or len(args) > 32 or not all(isinstance(arg, str) and len(arg) <= 1024 for arg in args):
            raise ValueError("MCP 服务启动参数无效")
        return {"command": sys.executable if command == "python" else command, "args": args}
    if transport == "streamable-http":
        url = urlsplit(config["url"])
        local = url.hostname in {"localhost", "127.0.0.1", "::1"}
        if (not url.hostname or url.username is not None or url.password is not None or url.query or url.fragment
                or not (local and url.scheme in {"http", "https"} or url.scheme == "https" and config.get("trust") == "institution")):
            raise ValueError("MCP 网络地址须为本机或明确授权的机构 HTTPS 服务")
        return {"url": url.geturl()}
    raise ValueError("未知的 MCP 传输方式")


@lru_cache(maxsize=4)
def _load(path, stamp):
    with path.open("rb") as handle:
        metadata = os.fstat(handle.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o022 or (
            hasattr(os, "geteuid") and metadata.st_uid not in {0, os.geteuid()}
        ):
            raise ValueError("MCP 服务配置须由运营方管理")
        raw = handle.read(65537)
    if len(raw) > 65536:
        raise ValueError("MCP 服务配置过大")
    servers = json.loads(raw)["mcpServers"]
    if not isinstance(servers, dict) or len(servers) > 16:
        raise ValueError("MCP 服务配置无效")
    tools = {}
    for server, config in servers.items():
        if not ID.fullmatch(server):
            raise ValueError("MCP 服务名称无效")
        endpoint = _endpoint(config)
        for remote, rule in config["tools"].items():
            if not ID.fullmatch(remote) or rule["grant"] not in access_policy.PERMISSIONS:
                raise ValueError("MCP 工具或岗位权限配置无效")
            fields = _fields(rule.get("parameters", {}))
            required, fixed = rule.get("required", []), rule.get("fixed", {})
            if (not isinstance(required, list) or not set(required) <= fields.keys()
                    or not isinstance(fixed, dict) or fixed.keys() & fields.keys()):
                raise ValueError("MCP 固定参数或必填参数无效")
            title, description, keywords = rule["title"], rule["description"], rule["keywords"]
            if not (isinstance(title, str) and 0 < len(title) <= 60 and isinstance(description, str)
                    and 0 < len(description) <= 260 and isinstance(keywords, list) and 0 < len(keywords) <= 24
                    and all(isinstance(word, str) and 0 < len(word) <= 50 for word in keywords)):
                raise ValueError("MCP 工具说明无效")
            schema = {"type": "object", "properties": fields, "required": required, "additionalProperties": False}
            tool = Tool(server, remote, title, description, rule["grant"], tuple(keywords), endpoint, schema, fixed)
            if len(tool.name) > 64 or tool.name in tools or len(tools) >= 64:
                raise ValueError("MCP 工具目录名称冲突或过长")
            tools[tool.name] = tool
    return tuple(tools.values())


def _authorized(user):
    if not access_policy.has(user, "assistants") or user["kind"] not in {"owner", "staff"}:
        return ()
    path = Path(os.environ.get("NH_MCP_CONFIG") or DEFAULT_CONFIG)
    try:
        stamp = path.stat()
        tools = _load(path, (stamp.st_ino, stamp.st_ctime_ns, stamp.st_size))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return ()
    return tuple(tool for tool in tools if access_policy.has(user, tool.grant))


def catalog(user):
    return [{"name": t.name, "server": t.server, "title": t.title, "description": t.description}
            for t in _authorized(user)]


def tools_for(user, text=None):
    tools = _authorized(user)
    if text is None:
        return tools[:6]
    return tuple(tool for tool in tools
                 if any(term in text for term in (*tool.keywords, tool.title, tool.name)))[:6]


async def _invoke(tool, arguments):
    # Load the optional SDK on the first real call. Other workspaces and the
    # account/login paths need neither a subprocess nor these dependencies.
    runtime = ROOT / ".local/harness-runtime"
    if runtime.is_dir() and str(runtime) not in sys.path:
        sys.path.append(str(runtime))
    import mcp
    from mcp import Client, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamable_http_client

    async with asyncio.timeout(TIMEOUT), AsyncExitStack() as stack:
        if "url" in tool.endpoint:
            from httpx2 import AsyncClient
            from httpx2 import URL
            approved_url = URL(tool.endpoint["url"])

            async def check_endpoint(request):
                if request.url != approved_url:
                    raise ValueError("MCP 服务地址已经变化")

            http = await stack.enter_async_context(AsyncClient(
                timeout=TIMEOUT, trust_env=False, follow_redirects=False,
                event_hooks={"request": [check_endpoint]},
            ))
            transport = streamable_http_client(tool.endpoint["url"], http_client=http, max_sse_event_size=65536)
        else:
            directory = stack.enter_context(TemporaryDirectory(prefix="nh-reference-"))
            env = {"HOME": directory, "PATH": os.defpath, "PYTHONNOUSERSITE": "1",
                   "PYTHONPATH": str(Path(mcp.__file__).resolve().parent.parent)}
            params = StdioServerParameters(**tool.endpoint, cwd=directory, env=env)
            errors = stack.enter_context(open(os.devnull, "w"))
            transport = stdio_client(params, errlog=errors)
        client = await stack.enter_async_context(Client(transport, read_timeout_seconds=TIMEOUT, cache=None))
        cursor = None
        for _ in range(4):
            listing = await client.list_tools(cursor=cursor)
            descriptor = next((item for item in listing.tools if item.name == tool.remote), None)
            if descriptor is not None:
                break
            cursor = listing.next_cursor
            if not cursor:
                break
        if descriptor is None or not descriptor.annotations or descriptor.annotations.read_only_hint is not True:
            raise ValueError("服务未声明此授权工具为只读")
        response = await client.call_tool(tool.remote, arguments)
        if response.is_error:
            raise ValueError("MCP 工具未能处理请求")
        value = response.structured_content
        if value is None:
            value = [item.text for item in response.content if item.type == "text"]
        if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_OUTPUT:
            raise ValueError("MCP 工具返回的数据过多")
        return value
