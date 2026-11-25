"""Run concurrent, isolated DeerFlow lead-agent graphs in a warm Python process.

The SDK requests model and tool callbacks. The signed-in caller performs each
authorized read, streams provider output, and records the original receipt.
"""

import atexit
from contextvars import ContextVar
import json
from queue import Empty, Full, Queue
from subprocess import DEVNULL, PIPE, Popen
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4

from . import deerflow_worker


SETUP = "DeerFlow 对话服务未就绪，请管理员核对部署控制台中的运行环境"
_MAX_EVENT = 1024 * 1024
TURN_SECONDS = 140
_lock = Lock()
_worker = None
_active = ContextVar("inside_deerflow_graph", default=False)


class Unavailable(RuntimeError):
    pass


def active():
    return _active.get()


class Worker:
    def __init__(self):
        if not deerflow_worker.installation()["ready"]:
            raise Unavailable(SETUP)
        self.home = TemporaryDirectory(prefix="careops-deerflow-chat-")
        try:
            self.process = Popen(
                [deerflow_worker._interpreter(), "-I", "-u", str(deerflow_worker.ENTRY.with_name("conversation.py"))],
                cwd=self.home.name, env=deerflow_worker._env(self.home.name), stdin=PIPE, stdout=PIPE, stderr=DEVNULL,
            )
        except OSError:
            self.home.cleanup()
            raise Unavailable(SETUP) from None
        self.sessions = {}
        self.sessions_lock = Lock()
        self.outbox = Queue(maxsize=64)
        self.dead = False
        Thread(target=self._write, name="careops-deerflow-requests", daemon=True).start()
        Thread(target=self._read, name="careops-deerflow-events", daemon=True).start()

    def _write(self):
        # A wedged child must not block every HTTP request on one shared pipe.
        try:
            while frame := self.outbox.get():
                payload, written = frame
                try:
                    self.process.stdin.write(payload)
                    self.process.stdin.flush()
                finally:
                    written.set()
        except (OSError, ValueError):
            if self.process.poll() is None:
                self.process.kill()
        finally:
            try:
                self.process.stdin.close()
            except OSError:
                pass

    def _read(self):
        try:
            while line := self.process.stdout.readline(_MAX_EVENT + 1):
                if len(line) > _MAX_EVENT:
                    break
                event = json.loads(line)
                with self.sessions_lock:
                    inbox = self.sessions.get(event["id"])
                    if inbox is not None:
                        inbox.put_nowait(event)
        except (ValueError, OSError, KeyError, TypeError):
            pass
        finally:
            self.stop()
            with self.sessions_lock:
                self.dead = True
                for inbox in self.sessions.values():
                    inbox.put_nowait({"op": "offline"})

    def stop(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()
        try:
            self.outbox.put_nowait(None)
        except Full:
            # The writer wakes as soon as the killed process closes the pipe.
            pass
        self.process.stdout.close()
        self.home.cleanup()

    def send(self, ident, op, **fields):
        if self.dead or self.process.poll() is not None:
            raise Unavailable(SETUP)
        payload = json.dumps({"id": ident, "op": op, **fields}, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"
        if len(payload) > _MAX_EVENT:
            raise ValueError("本次 DeerFlow 请求过大，请减少同时读取的资料")
        written = Event()
        try:
            self.outbox.put((payload, written), timeout=2)
        except Full:
            raise Unavailable("DeerFlow 对话服务正在处理其他请求，请稍后重试") from None
        if not written.wait(timeout=6):
            if self.process.poll() is None:
                self.process.kill()
            raise Unavailable("DeerFlow 对话服务通信超时，请稍后重试")
        if self.process.poll() is not None:
            raise Unavailable(SETUP)


def _current():
    global _worker
    with _lock:
        if _worker is None or _worker.dead or _worker.process.poll() is not None:
            _worker = Worker()
        return _worker


@atexit.register
def close():
    with _lock:
        if _worker is not None and _worker.process.poll() is None:
            _worker.process.kill()
            _worker.process.wait()


def _run(body, first, execute, synthesize, name):
    """Drive SDK events on the caller thread so DB scopes and task metering survive.

    first returns a validated text or a list of authorised calls. Python still
    owns the receipts (including late ones) and the user-visible stream.
    """
    ident = uuid4().hex
    worker = _current()
    inbox = Queue()
    with worker.sessions_lock:
        if worker.dead:
            raise Unavailable(SETUP)
        worker.sessions[ident] = inbox
    done = False
    started = finished = False
    pending, issued = {}, set()
    tools = body.get("tools", [])
    roles = body.get("roles", []) if name == "careops-supervisor" else []
    limit = len(roles) if name == "careops-supervisor" else 3
    allowed = set(roles) if name == "careops-supervisor" else {entry["function"]["name"] for entry in tools}
    try:
        deadline = monotonic() + TURN_SECONDS
        worker.send(ident, "start", agent=name, tools=tools, roles=roles, maxActions=limit,
                    deadlineMs=int(TURN_SECONDS * 1000))
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise Unavailable("DeerFlow 对话服务超时，请稍后重试")
            try:
                event = inbox.get(timeout=remaining)
            except Empty:
                raise Unavailable("DeerFlow 对话服务超时，请稍后重试") from None
            op = event["op"]
            if op == "expired":
                raise Unavailable("DeerFlow 对话服务超时，请稍后重试")
            if op == "offline":
                raise Unavailable(SETUP)
            if op == "loop":
                raise ValueError("DeerFlow 已停止重复的工具调用")
            if op == "model" and not pending and not finished:
                if event.get("phase") != ("synthesis" if started else "initial"):
                    raise ValueError("DeerFlow 请求的模型步骤无效")
                result = synthesize() if started else first()
                started = True
                batch = result.get("calls", ()) if isinstance(result, dict) else ()
                if len(issued) + len(batch) > limit:
                    raise ValueError("本轮工具调用已达上限")
                for call in batch:
                    key = call["id"]
                    if not isinstance(key, str) or not key or key in issued or call["name"] not in allowed:
                        raise ValueError("DeerFlow 工具未授权或调用编号重复")
                    issued.add(key)
                    pending[key] = call
                finished = not batch
                value = {"calls": batch} if batch else {"text": "completed"}
            elif op == "tool" and pending:
                selected = pending.pop(event.get("callId"), None)
                if not selected or selected["name"] != event["name"] or selected["arguments"] != event["args"]:
                    raise ValueError("DeerFlow 请求的工具与已核对的模型指令不一致")
                execute(selected["name"], selected["arguments"])
                # The host supplies scoped observations to the next model call.
                value = {"read": True}
            elif op == "done" and finished:
                done = True
                return
            elif op == "busy":
                raise Unavailable("DeerFlow 正在处理其他请求，请稍后重试")
            else:
                raise ValueError("DeerFlow 未完成有效的对话工具流程")
            if monotonic() >= deadline:
                raise Unavailable("DeerFlow 对话服务超时，请稍后重试")
            worker.send(ident, "return", value=value)
    finally:
        with worker.sessions_lock:
            worker.sessions.pop(ident, None)
        if not done:
            try:
                worker.send(ident, "cancel")
            except Unavailable:
                pass


def run(body, first, execute, synthesize, *, name="careops-lead"):
    marker = _active.set(True)
    try:
        return _run(body, first, execute, synthesize, name)
    finally:
        _active.reset(marker)


def delegate(roles, collect):
    """Submit a verified role plan to the upstream supervisor and its scoped children."""
    calls = [{"id": role, "name": role, "arguments": {}} for role in roles]
    run({"roles": list(roles)}, lambda: {"calls": calls}, lambda role, _: collect(role),
        lambda: {"text": "completed"}, name="careops-supervisor")


def generate(callback, *, name):
    """Use a specialist graph for one metered model callback and preserve its result."""
    if active():
        return callback()
    result = []

    def first():
        result.append(callback())
        return {"text": "completed"}

    def unexpected(*args):
        raise ValueError("此任务没有获授权的工具")

    run({}, first, unexpected, unexpected, name=name)
    return result[0]


def capability(name, value):
    """Send a trusted, already-scoped adapter request to the isolated DeerFlow SDK."""
    worker = _current()
    ident, inbox = uuid4().hex, Queue()
    with worker.sessions_lock:
        if worker.dead:
            raise Unavailable(SETUP)
        worker.sessions[ident] = inbox
    try:
        worker.send(ident, "capability", name=name, value=value)
        reply = inbox.get(timeout=20)
        if reply["op"] == "result":
            return reply["value"]
        if reply["op"] in ("busy", "offline"):
            raise Unavailable("DeerFlow 暂时无法处理请求")
        raise ValueError("DeerFlow 未能读取已授权的技能或 MCP 工具")
    except Empty:
        raise Unavailable("DeerFlow 能力调用超时") from None
    finally:
        with worker.sessions_lock:
            worker.sessions.pop(ident, None)
