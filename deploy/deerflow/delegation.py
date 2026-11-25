"""Delegate a host-authorized plan through DeerFlow's registered task tool."""

import asyncio
from threading import Lock
from uuid import uuid4

from deerflow.agents.factory import create_deerflow_agent
from deerflow.config import get_app_config
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import DEFAULT_USER_ID
from deerflow.subagents.status_contract import read_subagent_result_metadata
from deerflow.tools.builtins.task_tool import task_tool
from deerflow.tools.types import Runtime
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langsmith import tracing_context


# Only one child per run can read at a time. Each grant disappears on use or cancellation.
_readers = {}
_readers_lock = Lock()


@tool
def read_assigned_evidence(runtime: Runtime, config: RunnableConfig) -> str:
    """核对当前岗位受托查阅的院内资料。"""
    # Both values are injected by DeerFlow's executor. The tool has no model-supplied arguments.
    roles = [tag.removeprefix("subagent:") for tag in config.get("tags", ()) if tag.startswith("subagent:")]
    if len(roles) != 1:
        raise PermissionError("无法核对受派岗位")
    key = ((runtime.context or {}).get("thread_id"), roles[0])
    with _readers_lock:
        collect = _readers.pop(key, None)
    if collect is None:
        raise PermissionError("此次委派没有可用的资料授权")
    collect()
    return "本次授权的业务资料已核对"


def result(message):
    return ChatResult(generations=[ChatGeneration(message=message)])


class EvidenceTransport(BaseChatModel):
    """Replay the vetted plan. The institution meters reasoning and checks evidence in the host."""

    @property
    def _llm_type(self):
        return "careops-authorized-read"

    def bind_tools(self, tools, **kwargs):
        if [item.name for item in tools] != [read_assigned_evidence.name]:
            raise PermissionError("受派岗位的工具范围与授权不符")
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if isinstance(messages[-1], ToolMessage):
            return result(AIMessage(content="资料核对完成"))
        return result(AIMessage(content="", tool_calls=[
            {"name": read_assigned_evidence.name, "args": {}, "id": uuid4().hex},
        ]))


def run_supervisor(start, exchange):
    roles = start["roles"]
    config = get_app_config()
    registered = config.subagents.custom_agents
    if not roles or any(role not in registered for role in roles) or len(set(roles)) != len(roles):
        raise ValueError("委派岗位未经授权")
    ident = start["id"]
    pending = iter(())
    completed = set()

    class SupervisorTransport(EvidenceTransport):
        def bind_tools(self, tools, **kwargs):
            if [item.name for item in tools] != [task_tool.name]:
                raise PermissionError("委派工具配置与授权不符")
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            nonlocal pending
            last = messages[-1]
            if isinstance(last, ToolMessage):
                receipt = read_subagent_result_metadata(last.additional_kwargs)
                if (not receipt or receipt.get("status") != "completed" or receipt.get("stop_reason")
                        or last.tool_call_id not in completed):
                    raise ValueError("专员未完成此次资料核对")
            else:
                calls = exchange("model", phase="initial")["calls"]
                if [call["name"] for call in calls] != roles or any(call["arguments"] != {} for call in calls):
                    raise ValueError("委派计划与岗位授权不符")
                pending = iter(calls)
            call = next(pending, None)
            if call is None:
                exchange("model", phase="synthesis")
                return result(AIMessage(content="完成"))

            def collect():
                exchange("tool", name=call["name"], args={}, callId=call["id"])
                completed.add(call["id"])

            with _readers_lock:
                _readers[ident, call["name"]] = collect
            return result(AIMessage(content="", tool_calls=[{
                "name": task_tool.name,
                "args": {"subagent_type": call["name"], "prompt": "核对本次分配的资料。", "context_mode": "isolated"},
                "id": call["id"],
            }]))

    try:
        with tracing_context(enabled=False):
            graph = create_deerflow_agent(SupervisorTransport(), tools=[task_tool], middleware=[],
                                          checkpointer=None, name="careops-supervisor")
            asyncio.run(graph.ainvoke(
                {"messages": [("user", "执行此次已核对的委派计划。")]},
                {"metadata": {"allowed_subagents": roles, "available_skills": [], "mcp_plugins": [],
                              "tool_groups": ["institution-evidence"]}, "recursion_limit": 4 * len(roles) + 8},
                context={"thread_id": ident, "run_id": ident, "user_id": DEFAULT_USER_ID, "app_config": config},
            ))
    finally:
        with _readers_lock:
            for role in roles:
                _readers.pop((ident, role), None)
        get_paths().delete_thread_dir(ident, user_id=DEFAULT_USER_ID)
