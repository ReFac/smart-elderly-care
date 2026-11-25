"""DeerFlow skill loading and read-only MCP sessions for pre-authorized callbacks."""

import asyncio
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from deerflow.skills.frontmatter import split_skill_markdown
from deerflow.skills.parser import parse_skill_file
from deerflow.skills.types import SkillCategory


def read_skill(source, name, *, metadata_only=False):
    # Parse exactly the bytes approved by the host, not a path supplied by a model.
    with TemporaryDirectory() as directory:
        path = Path(directory, "SKILL.md")
        path.write_text(source, encoding="utf-8")
        skill = parse_skill_file(path, SkillCategory.PUBLIC)
        if not skill or skill.name != name or getattr(skill, "required_secrets", ()):
            raise ValueError("技能包无效或需要额外凭据")
        parts, error = split_skill_markdown(source)
        if error:
            raise ValueError("技能正文格式无效")
        if len(parts.frontmatter_text.encode()) > 8192:
            raise ValueError("技能元数据过长")
        metadata = parts.metadata.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("技能元数据格式无效")
        entry = {"name": skill.name, "description": skill.description.strip(),
                 "grant": metadata.get("workspace-permission", "assistants")}
        if not metadata_only:
            entry["instructions"] = parts.body.strip()
        return entry


async def call_mcp(request):
    from deerflow.config.extensions_config import McpServerConfig
    from deerflow.mcp.client import build_server_params
    from langchain_mcp_adapters.client import MultiServerMCPClient
    import httpx

    endpoint = request["endpoint"]
    server = request["server"]
    async with asyncio.timeout(12), AsyncExitStack() as stack:
        if "url" in endpoint:
            config = McpServerConfig(type="http", url=endpoint["url"])
            params = build_server_params(server, config)
            approved = httpx.URL(config.url)

            async def exact_url(req):
                if req.url != approved:
                    raise ValueError("MCP 请求地址改变")

            def http_client(**options):
                return httpx.AsyncClient(**{**options, "trust_env": False, "follow_redirects": False,
                                            "event_hooks": {"request": [exact_url]}})

            params["httpx_client_factory"] = http_client
        else:
            directory = stack.enter_context(TemporaryDirectory(prefix="careops-mcp-"))
            config = McpServerConfig(type="stdio", **endpoint, cwd=directory,
                                     env={"HOME": directory, "PATH": os.defpath, "PYTHONNOUSERSITE": "1",
                                          "PYTHONPATH": request["serverLibraries"]})
            params = build_server_params(server, config)
        client = MultiServerMCPClient({server: params})
        session = await stack.enter_async_context(client.session(server))
        cursor = None
        for _ in range(4):
            listing = await session.list_tools(cursor=cursor)
            tool = next((t for t in listing.tools if t.name == request["remote"]), None)
            if tool is not None or not listing.nextCursor:
                break
            cursor = listing.nextCursor
        if tool is None or not tool.annotations or tool.annotations.readOnlyHint is not True:
            raise ValueError("服务未声明此工具为只读")
        response = await session.call_tool(tool.name, request["arguments"])
        if response.isError:
            raise ValueError("MCP 请求失败")
        value = response.structuredContent
        if value is None:
            value = [item.text for item in response.content if item.type == "text"]
        if len(json.dumps(value, ensure_ascii=False).encode()) > 8192:
            raise ValueError("MCP 返回内容过长")
        return value
