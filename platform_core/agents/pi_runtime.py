"""Pi runs one isolated conversation per turn in a shared, tool-less Node worker.

The host retains credentials, authorisation and metering. A Pi tool callback always
returns to the live Python session. No file, shell, network or arbitrary MCP tool
is registered here; the application's own MCP adapter supplies reviewed tools.
"""

import atexit
from functools import lru_cache
import json
from pathlib import Path
from queue import Empty, Full, Queue
import re
import shutil
import subprocess
from subprocess import DEVNULL, PIPE, Popen
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4

from . import runtime_assets


MINIMUM_NODE = (22, 19, 0)
RUNTIME = runtime_assets.sources("runtimes/pi")
SETUP = "Pi 对话服务未就绪，请管理员核对 Node.js 和 runtimes/pi 的锁定依赖"
_MAX_EVENT = 65536
TURN_SECONDS = 140  # Shorter than the chat reservation's 150-second lease.
_lock = Lock()
_worker = None


class Unavailable(RuntimeError):
    pass


@lru_cache(maxsize=4)
def _node_release(node, _file_stamp):
    # Cache by binary identity. Replacing Node, including its symlink target,
    # automatically refreshes the check without restarting the workspace.
    output = subprocess.run([node, "--version"], stdin=DEVNULL, stdout=PIPE, stderr=DEVNULL,
                            env={}, timeout=2, check=True).stdout.strip()
    match = re.fullmatch(rb"v(\d{1,4})\.(\d{1,4})\.(\d{1,4})", output)
    if not match:
        raise ValueError("未知的 Node.js 版本")
    return tuple(int(part) for part in match.groups())


def _installation(node):
    version, locked = "", False
    try:
        modules = runtime_assets.dependencies("pi") / "node_modules"
        pins = json.loads((RUNTIME / "package-lock.json").read_bytes())["packages"]
        tree = json.loads((modules / ".package-lock.json").read_bytes())["packages"]
        locked = all(
            (path in tree and tree[path].get("integrity") == pin["integrity"]
             and tree[path].get("version") == pin["version"])
            or (path not in tree and pin.get("optional"))
            for path, pin in pins.items() if path
        ) and all(path in pins for path in tree)
        package = modules / "@earendil-works/pi-agent-core/package.json"
        version = json.loads(package.read_bytes())["version"]
        for name in ("pi-ai", "pi-agent-core"):
            sdk = modules / "@earendil-works" / name
            locked = (locked and (sdk / "dist/index.js").is_file()
                      and json.loads((sdk / "package.json").read_bytes())["version"] == "1.6.1")
    except (OSError, ValueError, TypeError, KeyError):
        locked = False
    release = ()
    if node:
        try:
            info = Path(node).stat()
            release = _node_release(node, (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size))
        except (OSError, ValueError, subprocess.SubprocessError):
            pass  # Failed probes may be retried; only a verified release is cached.
    supported = release >= MINIMUM_NODE
    installed = bool(supported and locked)
    return {"installed": installed, "version": version, "requiredVersion": "1.6.1",
            "nodeVersion": ".".join(map(str, release)), "nodeSupported": supported,
            "minimumNode": ".".join(map(str, MINIMUM_NODE))}


def installation():
    """Owner and worker share a local version probe without cloud credentials."""
    return _installation(shutil.which("node"))


class Worker:
    def __init__(self):
        node = shutil.which("node")
        if not _installation(node)["installed"]:
            raise Unavailable(SETUP)
        modules = (runtime_assets.dependencies("pi") / "node_modules").resolve()
        try:
            self.process = Popen(
                [node, "--permission", f"--allow-fs-read={RUNTIME}", f"--allow-fs-read={modules}",
                 str(RUNTIME / "conversation.mjs"), str(modules)],
                cwd=RUNTIME, env={"LANG": "C.UTF-8"}, stdin=PIPE, stdout=PIPE, stderr=DEVNULL,
            )
        except OSError:
            raise Unavailable(SETUP) from None
        self.sessions = {}
        self.sessions_lock = Lock()
        self.outbox = Queue(maxsize=64)
        self.dead = False
        Thread(target=self._write, name="careops-pi-requests", daemon=True).start()
        Thread(target=self._read, name="careops-pi-events", daemon=True).start()

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

    def send(self, ident, op, **fields):
        if self.dead or self.process.poll() is not None:
            raise Unavailable(SETUP)
        payload = json.dumps({"id": ident, "op": op, **fields}, ensure_ascii=False, allow_nan=False)
        written = Event()
        try:
            self.outbox.put((payload.encode("utf-8") + b"\n", written), timeout=2)
        except Full:
            raise Unavailable("Pi 对话服务正在处理其他请求，请稍后重试") from None
        if not written.wait(timeout=6):
            if self.process.poll() is None:
                self.process.kill()
            raise Unavailable("Pi 对话服务通信超时，请稍后重试")
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


def run(body, first, execute, synthesize):
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
    initial = None
    called, finished = set(), False
    try:
        deadline = monotonic() + TURN_SECONDS
        worker.send(ident, "start", model=body["model"], messages=body["messages"], tools=body.get("tools", []),
                    deadlineMs=int(TURN_SECONDS * 1000))
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise Unavailable("Pi 对话服务超时，请稍后重试")
            try:
                event = inbox.get(timeout=min(10, remaining))
            except Empty:
                raise Unavailable("Pi 对话服务超时，请稍后重试") from None
            op = event["op"]
            if op == "expired":
                raise Unavailable("Pi 对话服务超时，请稍后重试")
            if op == "offline":
                raise Unavailable(SETUP)
            if op == "model" and event["phase"] == "initial" and initial is None:
                initial = first()
                value = initial
            elif op == "tool" and initial and not finished:
                selected = next((c for c in initial.get("calls", ()) if c["id"] == event["callId"]), None)
                if (not selected or selected["name"] != event["name"] or selected["id"] in called
                        or selected["arguments"] != event["args"]):
                    raise ValueError("Pi 请求的工具与已核对的模型指令不一致")
                called.add(selected["id"])
                execute(selected["name"], selected["arguments"])
                # Synthesis reads the host's private observation by reference. Pi
                # only needs the tool acknowledgement to advance its state.
                value = {"read": True}
            elif (op == "model" and event.get("phase") == "synthesis" and not finished and called
                  and len(called) == len(initial["calls"])):
                value = {"text": synthesize()}
                finished = True
            elif op == "done" and initial is not None and (not initial.get("calls") or finished):
                done = True
                return
            else:
                raise ValueError("Pi 未完成有效的对话工具流程")
            worker.send(ident, "return", value=value)
    finally:
        with worker.sessions_lock:
            worker.sessions.pop(ident, None)
        if not done:
            try:
                worker.send(ident, "cancel")
            except Unavailable:
                pass
