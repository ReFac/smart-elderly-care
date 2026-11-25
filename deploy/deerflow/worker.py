"""CareOps' bounded, stateless evidence worker on the official DeerFlow 2.0 SDK.

The trusted parent owns permissions, credentials, charging and all business writes.
The worker receives only one authorized evidence projection over private pipes.
"""

from importlib.metadata import version
import json
import sys

MAX_FRAME = 1024 * 1024
KINDS = {"medical-documents": "原文", "daily-life": "事实", "health-review": "摘录"}


def send(value):
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), flush=True)


def read():
    line = sys.stdin.buffer.readline(MAX_FRAME + 1)
    if not line:
        raise EOFError
    if len(line) > MAX_FRAME or not line.endswith(b"\n"):
        raise ValueError("请求超出范围")
    return json.loads(line)


def review(kind, facts, draft):
    """Check that the selected evidence really belongs to this worker's projection."""
    rows = facts[KINDS[kind]]
    if not isinstance(rows, list) or not isinstance(draft, dict):
        raise ValueError("资料或草稿结构无效")
    if kind == "medical-documents":
        if set(draft) != set(facts["字段"]):
            raise ValueError("医疗表单字段不符")
        groups = list(draft.values())
    elif kind == "daily-life":
        groups = draft["paragraphs"]
    else:
        groups = [draft["selected"]]
    if not isinstance(groups, list):
        raise ValueError("资料引用无效")
    for group in groups:
        if (
            not isinstance(group, list)
            or any(type(n) is not int or not 1 <= n <= len(rows) for n in group)
            or len(set(group)) != len(group)
        ):
            raise ValueError("草稿引用了无效证据")
    if kind == "daily-life":
        if sorted(n for group in groups for n in group) != list(
            range(1, len(rows) + 1)
        ):
            raise ValueError("生活简报未完整覆盖本次事实")
        if any(
            not group or len({rows[n - 1]["日期"] for n in group}) != 1
            for group in groups
        ):
            raise ValueError("生活简报混合了不同日期")
    if kind == "health-review" and len(groups[0]) > 3:
        raise ValueError("健康复核超出范围")


def main():
    if version("deerflow-harness") != "2.2.0":
        raise RuntimeError("本部署需要 DeerFlow 2.2.0")
    from deerflow.agents.factory import create_deerflow_agent
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.tools import tool
    from langsmith import tracing_context

    # The SDK graph calls a read-only evidence tool first. Its model transport
    # calls back into the host billing boundary exactly once. No ambient tools,
    # global memories, shell, file reader, checkpointer or external tracing.
    class EvidenceModel(BaseChatModel):
        @property
        def _llm_type(self):
            return "careops-metered-evidence"

        def bind_tools(self, tools, **kwargs):
            if [item.name for item in tools] != ["read_authorized_evidence"]:
                raise ValueError("工作任务工具配置无效")
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if not isinstance(messages[-1], ToolMessage):
                message = AIMessage(
                    content="",
                    tool_calls=[
                        dict(
                            name="read_authorized_evidence", args={}, id="read-evidence"
                        )
                    ],
                )
            else:
                # The host verifies the returned projection before authorizing
                # the paid call, and rechecks the employee's current scope.
                send({"step": "generate", "evidence": json.loads(messages[-1].content)})
                result = read()
                message = AIMessage(
                    content=json.dumps(result["draft"], ensure_ascii=False)
                )
            return ChatResult(generations=[ChatGeneration(message=message)])

    send({"ready": "deerflow", "protocol": 1})
    while True:
        try:
            work = read()
        except EOFError:
            return
        kind, facts = work["kind"], work["facts"]
        if kind not in KINDS:
            raise ValueError("不支持的任务类型")

        @tool
        def read_authorized_evidence() -> str:
            """读取这项任务中已经核实归属的资料。"""
            return json.dumps(facts, ensure_ascii=False, separators=(",", ":"))

        with tracing_context(enabled=False):
            graph = create_deerflow_agent(
                EvidenceModel(),
                tools=[read_authorized_evidence],
                middleware=[],
                checkpointer=None,
                name=kind,
            )
            answer = graph.invoke(
                {"messages": [("user", "核对这次任务的资料并整理待审草稿。")]},
                {"recursion_limit": 6},
            )
        draft = json.loads(answer["messages"][-1].content)
        review(kind, facts, draft)
        send({"step": "reviewed"})
        # Explicitly release this resident's graph and tool closure before idle.
        del graph, answer, draft, read_authorized_evidence, facts, work


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # No clinical text, cloud reply, environment value or traceback on pipes.
        send({"error": "worker_unavailable"})
        sys.exit(1)
