"""DeerFlow lead and specialist graphs with one private callback channel per run."""

from concurrent.futures import ThreadPoolExecutor
import asyncio
import json
from pathlib import Path
from queue import Empty, Queue
import sys
from threading import BoundedSemaphore, Event, Lock
from time import monotonic

from deerflow.agents.factory import create_deerflow_agent
from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware
from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
from deerflow.config.loop_detection_config import LoopDetectionConfig
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from langsmith import tracing_context


MAX_RUNS = 16
MAX_EVENT = 1024 * 1024
output_lock = Lock()
registry_lock = Lock()
sessions = {}


class Session(Queue):
    def __init__(self):
        super().__init__()
        self.cancelled = Event()

    def cancel(self):
        self.cancelled.set()
        self.put_nowait({"op": "cancel"})


def send(ident, op, **fields):
    payload = json.dumps({"id": ident, "op": op, **fields}, ensure_ascii=False)
    if len(payload.encode("utf-8")) + 1 > MAX_EVENT:
        payload = json.dumps({"id": ident, "op": "invalid"})
    with output_lock:
        print(payload, flush=True)


def run_graph(start, inbox):
    ident = start["id"]
    timeout = min(start["deadlineMs"] / 1000, 140)
    deadline = monotonic() + timeout
    callbacks = Lock()
    calls = {}
    used = set()
    available = set()

    def exchange(op, **fields):
        # ToolNode can run independent tools concurrently. The host rechecks and
        # acknowledges each call separately before another callback may proceed.
        with callbacks:
            if inbox.cancelled.is_set() or deadline <= monotonic():
                raise TimeoutError
            send(ident, op, **fields)
            frame = inbox.get(timeout=max(0, deadline - monotonic()))
            if frame["op"] != "return":
                raise TimeoutError
            return frame["value"]

    def make_tool(spec):
        name = spec["name"]

        def invoke(**kwargs):
            return exchange("tool", name=name, args=kwargs, callId=calls[name])

        return StructuredTool(name=name, description=spec.get("description", name),
                              args_schema=spec["parameters"], func=invoke)

    class HostModel(BaseChatModel):
        @property
        def _llm_type(self):
            return "careops-metered"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            phase = "synthesis" if isinstance(messages[-1], ToolMessage) else "initial"
            result = exchange("model", phase=phase)
            selected = []
            calls.clear()
            for call in result.get("calls", ()):
                name = call["name"]
                if name not in available or name in calls or call["id"] in used or len(used) >= start["maxActions"]:
                    raise ValueError("未授权或重复的工具")
                calls[name] = call["id"]
                used.add(call["id"])
                selected.append({"name": name, "args": call["arguments"], "id": call["id"]})
            message = AIMessage(content=result.get("text", ""), tool_calls=selected)
            return ChatResult(generations=[ChatGeneration(message=message)])

    def run():
        if start["agent"] == "careops-supervisor":
            from delegation import run_supervisor
            run_supervisor(start, exchange)
            return "done"
        tools = [make_tool(t["function"]) for t in start.get("tools", [])]
        available.update(tool.name for tool in tools)
        loop_guard = LoopDetectionMiddleware.from_config(LoopDetectionConfig(warn_threshold=2, hard_limit=2))
        with tracing_context(enabled=False):
            graph = create_deerflow_agent(HostModel(), tools=tools,
                                          middleware=[DanglingToolCallMiddleware(), loop_guard],
                                          checkpointer=None, name=start["agent"])
            graph.invoke({"messages": [("user", "处理这次已授权的请求。")]},
                         {"recursion_limit": 4 * start["maxActions"] + 8},
                         context={"thread_id": ident, "run_id": ident})
        return "loop" if loop_guard.consume_stop_reason(ident) else "done"

    try:
        status = run()
    except (TimeoutError, Empty):
        status = "expired"
    except Exception:
        status = "invalid"
    with registry_lock:
        sessions.pop(ident, None)
    send(ident, status)


def capability(frame):
    ident = frame["id"]
    try:
        import capabilities
        value = frame["value"]
        if frame["name"] in ("read_skill", "describe_skill"):
            result = capabilities.read_skill(value["source"], value["name"], metadata_only=frame["name"] == "describe_skill")
        elif frame["name"] == "experience.review":
            from experience import review
            result = review(value)
        elif frame["name"] == "call_mcp":
            result = asyncio.run(capabilities.call_mcp(value))
        else:
            raise ValueError("未知能力")
        reply = {"op": "result", "value": result}
    except Exception:
        reply = {"op": "invalid"}
    finally:
        capability_slots.release()
    send(ident, **reply)


capability_slots = BoundedSemaphore(4)


def main():
    # In isolated (-I) mode import helpers only from this release's own directory.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    with ThreadPoolExecutor(max_workers=MAX_RUNS) as pool, ThreadPoolExecutor(max_workers=4) as helpers:
        while line := sys.stdin.buffer.readline(MAX_EVENT + 1):
            if len(line) > MAX_EVENT or not line.endswith(b"\n"):
                break
            frame = json.loads(line)
            ident = frame["id"]
            if frame["op"] == "capability":
                if capability_slots.acquire(blocking=False):
                    helpers.submit(capability, frame)
                else:
                    send(ident, "busy")
                continue
            with registry_lock:
                if frame["op"] == "start":
                    if len(sessions) >= MAX_RUNS or ident in sessions:
                        send(ident, "busy")
                    else:
                        inbox = sessions[ident] = Session()
                        pool.submit(run_graph, frame, inbox)
                elif ident in sessions:
                    if frame["op"] == "cancel":
                        sessions[ident].cancel()
                    else:
                        sessions[ident].put_nowait(frame)
        with registry_lock:
            for inbox in sessions.values():
                inbox.cancel()


if __name__ == "__main__":
    main()
