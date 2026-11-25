"""DeerFlow skill loading and read-only MCP sessions for pre-authorized callbacks."""

import asyncio
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from deerflow.skills.frontmatter import split_skill_markdown
from deerflow.skills.parser import parse_skill_file
from deerflow.skills.types import SkillCategory


def skill_metadata(path, source, name, *, metadata_only):
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
    entry = {"name": skill.name, "description": skill.description.strip(), "allowedTools": skill.allowed_tools,
             "grant": metadata.get("workspace-permission", "assistants")}
    if not metadata_only:
        entry["instructions"] = parts.body.strip()
    return entry

def read_skill(source, name, *, metadata_only=False):
    with TemporaryDirectory() as directory:
        path = Path(directory, "SKILL.md")
        path.write_text(source, encoding="utf-8")
        return skill_metadata(path, source, name, metadata_only=metadata_only)


def skill_tools(request):
    from deerflow.skills.catalog import SkillCatalog
    from deerflow.skills.describe import build_describe_skill_tool
    from deerflow.skills.types import Skill
    from deerflow.sandbox.tools import read_file_tool
    from langchain_core.utils.function_calling import convert_to_openai_tool

    catalog = SkillCatalog(tuple(
        Skill(name=name, description=description, license=None, skill_dir=Path(name), skill_file=Path(name, "SKILL.md"),
              relative_path=Path(name), category=SkillCategory.PUBLIC, allowed_tools=allowed, enabled=True)
        for name, description, allowed in request.get("catalog", ())
    ))
    describe = build_describe_skill_tool(catalog)
    if "query" not in request:
        return [convert_to_openai_tool(tool) for tool in (describe, read_file_tool)]
    result = describe.invoke({"type": "tool_call", "id": uuid4().hex, "name": describe.name,
                              "args": {"name": request["query"]}})
    return result.update["messages"][0].content


def read_skill_member(request):
    """Give the upstream reader a private copy of the one file the host approved."""
    from deerflow.config.paths import get_paths
    from deerflow.runtime.user_context import DEFAULT_USER_ID
    from deerflow.sandbox.tools import get_sandbox_provider, read_file_tool
    from langchain.tools import ToolRuntime

    thread = uuid4().hex
    with TemporaryDirectory() as directory:
        data = {name + "_path": str(Path(directory, name)) for name in ("workspace", "uploads", "outputs")}
        uploads = Path(data["uploads_path"])
        uploads.mkdir()
        file = uploads / "SKILL.md"
        file.write_bytes(request["source"].encode("utf-8"))
        if "grant" in request:
            metadata = skill_metadata(file, request["source"], request["name"], metadata_only=True)
            if metadata["grant"] != request["grant"]:
                raise ValueError("技能权限已更新，请重新提问")
        runtime = ToolRuntime(state={"thread_data": data}, context={"thread_id": thread},
                              config={"configurable": {"thread_id": thread}}, stream_writer=lambda _: None,
                              tool_call_id=None, store=None)
        try:
            return read_file_tool.func(runtime=runtime, path="/mnt/user-data/uploads/SKILL.md",
                                       start_line=request.get("start_line"), end_line=request.get("end_line"))
        finally:
            if sandbox := runtime.state.get("sandbox"):
                get_sandbox_provider().release(sandbox["sandbox_id"])
            get_paths().delete_thread_dir(thread, user_id=DEFAULT_USER_ID)


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


def public_search(query):
    """Invoke DeerFlow's native search on the public topic approved by the host."""
    from deerflow.community.ddg_search.tools import web_search_tool

    result = json.loads(web_search_tool.invoke({"query": query, "max_results": 5}))
    if result.get("error") == "No results found":
        return {"results": []}
    if "error" in result:
        return {"error": "network"}
    return {"results": [
        {"title": str(row["title"])[:640], "url": str(row["url"])[:2049],
         "snippet": str(row["content"])[:1600]}
        for row in result["results"][:5]
    ]}
