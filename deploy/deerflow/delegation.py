"""Run the institution's approved delegations through DeerFlow's subagent executor."""

from uuid import uuid4

from deerflow.agents.factory import create_deerflow_agent
from deerflow.config import get_app_config
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import DEFAULT_USER_ID
from deerflow.subagents.config import SubagentConfig
from deerflow.subagents.executor import SubagentExecutor, SubagentStatus
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from langsmith import tracing_context


def result(message):
    return ChatResult(generations=[ChatGeneration(message=message)])


class EvidenceTransport(BaseChatModel):
    """Replay one authorized read. Reasoning and paid generation stay on the metered transport."""

    @property
    def _llm_type(self):
        return "careops-authorized-read"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if isinstance(messages[-1], ToolMessage):
            return result(AIMessage(content="资料核对完成"))
        return result(AIMessage(content="", tool_calls=[
            {"name": "read_assigned_evidence", "args": {}, "id": uuid4().hex},
        ]))


def run_supervisor(start, exchange):
    registry = {spec["function"]["name"]: spec["function"] for spec in start["tools"]}
    if not registry or set(registry) - {"care", "inventory", "finance"}:
        raise ValueError("委派岗位未经授权")
    config = get_app_config()
    selected = {}
    completed = set()

    class SupervisorTransport(EvidenceTransport):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if isinstance(messages[-1], ToolMessage):
                if completed != set(registry):
                    raise ValueError("委派未完成")
                exchange("model", phase="synthesis")
                return result(AIMessage(content="完成"))
            plan = exchange("model", phase="initial")["calls"]
            for call in plan:
                name = call["name"]
                if name not in registry or name in selected or call["arguments"] != {}:
                    raise ValueError("委派与本次授权不符")
                selected[name] = call["id"]
            return result(AIMessage(content="", tool_calls=[
                {"name": name, "args": {}, "id": call_id} for name, call_id in selected.items()
            ]))

    def handoff(name, spec):
        def invoke():
            def read():
                exchange("tool", name=name, args={}, callId=selected[name])
                return "本次授权的业务记录已核对"

            evidence = StructuredTool.from_function(read, name="read_assigned_evidence", description=spec["description"])
            role = SubagentConfig(name=name, description=spec["description"], tools=[evidence.name],
                                  skills=[], model="scoped-read", max_turns=3, timeout_seconds=90)
            thread_id = uuid4().hex
            child = SubagentExecutor(role, [evidence], app_config=config, trace_id=start["id"],
                                     run_id=uuid4().hex, thread_id=thread_id, user_id=DEFAULT_USER_ID)
            try:
                receipt = child.execute("核对此次委派的资料。")
            finally:
                # Each child owns a fresh temporary thread. Its durable receipt lives in the institution.
                get_paths().delete_thread_dir(thread_id, user_id=DEFAULT_USER_ID)
            if receipt.status is not SubagentStatus.COMPLETED or receipt.stop_reason:
                raise RuntimeError("专员未完成此次资料核对")
            completed.add(name)
            return "已核对"

        return StructuredTool(name=name, description=spec["description"], args_schema=spec["parameters"], func=invoke)

    with tracing_context(enabled=False):
        graph = create_deerflow_agent(SupervisorTransport(), tools=[handoff(n, s) for n, s in registry.items()],
                                      middleware=[], checkpointer=None, name="careops-supervisor")
        graph.invoke({"messages": [("user", "执行本次已核对的委派计划。")]},
                     {"max_concurrency": 1, "recursion_limit": 8})
