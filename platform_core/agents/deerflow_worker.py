"""DeerFlow 2.0 delegates scoped evidence tasks. The platform owns the metered cloud call."""

import atexit
from contextlib import contextmanager
from functools import lru_cache
import json
import os
import re
import select
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Lock
from time import monotonic

from ..provider import generation, task_usage
from . import runtime_assets

ENTRY = runtime_assets.sources("deploy/deerflow") / "worker.py"
MAX_FRAME = 1024 * 1024
LOCK = Lock()
_claim_lock = Lock()
_claims = set()
_process = None
_home = None


def backend():
    value = os.environ.get("NH_DEERFLOW_BACKEND", "deerflow")
    if value not in ("deerflow", "direct"):
        raise ValueError("NH_DEERFLOW_BACKEND 必须为 deerflow 或 direct")
    return value


def _interpreter():
    dependencies = runtime_assets.dependencies("deerflow")
    if dependencies != runtime_assets.install_root() / "deploy/deerflow":
        return str(dependencies / "venv" / "bin" / "python")
    configured = os.environ.get("NH_DEERFLOW_PYTHON")
    if configured:
        if not os.path.isabs(configured):
            raise ValueError("NH_DEERFLOW_PYTHON 需要绝对路径")
        return configured
    isolated = runtime_assets.install_root() / ".local" / "deerflow-venv" / "bin" / "python"
    return str(isolated) if isolated.is_file() else sys.executable


def _env(home):
    return {
        "LANG": "C.UTF-8",
        "PATH": os.defpath,
        "LANGSMITH_TRACING": "false",
        "HOME": home,
        "DEER_FLOW_HOME": home,
        "DEER_FLOW_CONFIG_PATH": str(ENTRY.with_name("worker-config.yaml")),
        "DEER_FLOW_SKILLS_PATH": os.path.join(home, "empty-skills"),
    }


@lru_cache(maxsize=4)
def _installed(interpreter, requirements, revision):
    # Loading the factory catches partial installations. The probe never starts a
    # worker, talks to the model, or accepts any business data.
    probe_code = (
        "from importlib.metadata import distribution, version; import sys, json; "
        "print(version('deerflow-harness'), flush=True); "
        "origin=json.loads(distribution('deerflow-harness').read_text('direct_url.json') or '{}'); "
        "commit=origin.get('vcs_info', {}).get('commit_id'); "
        "deps_ok=all(version(name)==pin for name,pin in (p.split('==') for p in sys.argv[2:])); "
        "sys.exit(1) if (commit and commit!=sys.argv[1]) or not deps_ok else None; "
        "from deerflow.agents.factory import create_deerflow_agent"
    )
    try:
        with TemporaryDirectory(prefix="careops-deerflow-probe-") as home:
            probe = subprocess.run(
                [interpreter, "-I", "-c", probe_code, revision, *requirements],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=_env(home),
                cwd=home,
                text=True,
                timeout=10,
            )
        version = probe.stdout.strip() or None
        return version, probe.returncode == 0 and version == "2.0.0"
    except (OSError, subprocess.TimeoutExpired):
        return None, False


def installation():
    """Passive deployment metadata; no model call and no patient access."""
    try:
        engine = backend()
        requirements = tuple(line.strip() for line in ENTRY.with_name("requirements.txt").read_text().splitlines()
                             if line.strip() and not line.lstrip().startswith("#"))
        pin = re.search(r"@([0-9a-f]{40})#", ENTRY.with_name("sdk.txt").read_text())
        if not pin or not all(re.fullmatch(r"[\w.-]+==[\w.-]+", item) for item in requirements):
            raise ValueError("DeerFlow 依赖清单无效")
        version, installed = _installed(_interpreter(), requirements, pin[1])
        return {
            "backend": engine,
            "installed": installed,
            "version": version,
            "expectedVersion": "2.0.0",
            "ready": engine == "direct" or installed,
        }
    except (ValueError, OSError):
        return {
            "backend": "invalid",
            "installed": False,
            "version": None,
            "expectedVersion": "2.0.0",
            "ready": False,
        }


@contextmanager
def _claim(key):
    # Reject the same extraction immediately, including when it is queued for
    # the worker. The billing ledger remains authoritative across processes.
    with _claim_lock:
        if key in _claims:
            raise ValueError("这次云端请求正在处理，请稍后重试")
        _claims.add(key)
    try:
        yield
    finally:
        with _claim_lock:
            _claims.remove(key)


def _stop():
    global _process, _home
    if _process:
        child, _process = _process, None
        try:
            child.kill()
            child.wait(timeout=3)
        finally:
            child.stdin.close()
            child.stdout.close()
    if _home is not None:
        _home.cleanup()
        _home = None


atexit.register(_stop)


def _write(value):
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
    if len(data) > MAX_FRAME:
        raise ValueError("本次任务资料超过整理窗口")
    fd = _process.stdin.fileno()
    deadline = monotonic() + 20
    frame = memoryview(data)
    while frame:
        seconds = deadline - monotonic()
        if seconds <= 0 or not select.select([], [fd], [], seconds)[1]:
            raise ValueError("DeerFlow 2.0 未能及时接收本次任务")
        try:
            count = os.write(fd, frame)
        except BlockingIOError:
            continue
        frame = frame[count:]


def _read(timeout):
    """Read one bounded worker frame; a partial line cannot extend the deadline."""
    deadline = monotonic() + timeout
    data = bytearray()
    while len(data) < MAX_FRAME:
        seconds = deadline - monotonic()
        if seconds <= 0 or not select.select([_process.stdout], [], [], seconds)[0]:
            break
        chunk = os.read(_process.stdout.fileno(), min(65536, MAX_FRAME - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if data.endswith(b"\n"):
            return json.loads(data)
    raise ValueError("DeerFlow 2.0 工作进程无响应，请检查独立运行环境")


def _start():
    global _process, _home
    if _process and _process.poll() is None:
        return
    _stop()
    if not installation()["installed"]:
        raise ValueError("DeerFlow 2.0 未就绪，请预置对应发布版本的独立运行环境")
    _home = TemporaryDirectory(prefix="careops-deerflow-")
    try:
        _process = subprocess.Popen(
            [_interpreter(), "-I", "-u", str(ENTRY)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=_home.name,
            env=_env(_home.name),
        )
        os.set_blocking(_process.stdin.fileno(), False)
        if _read(25) != {"ready": "deerflow-2.0.0"}:
            raise ValueError("工作进程无法启动")
    except (OSError, ValueError) as exc:
        _stop()
        raise ValueError(
            "DeerFlow 2.0 未就绪，请按部署指南安装并核对 NH_DEERFLOW_PYTHON"
        ) from exc


def generate(
    kind,
    task_id,
    store,
    actor,
    request_id,
    instruction,
    facts,
    validate,
    *,
    authorize=None,
    **options,
):
    """Only the host can spend quota, read a provider key or publish a reviewed record."""
    engine = backend()

    def paid_call():
        if authorize:
            authorize()
        with task_usage.scope(
            "deerflow" if engine == "deerflow" else "platform", task_id
        ):
            return generation.generate(
                store, actor, request_id, instruction, facts, validate, **options
            )

    if engine == "direct":
        return paid_call()
    # Keep the heavy graph interpreter out of the HTTP process. A single warm
    # worker avoids 200 Python startups and shares no conversation/checkpoints.
    key = (
        str(store.path),
        None if options.get("shared_once") else actor,
        generation.fingerprint(request_id),
    )
    with _claim(key), LOCK:
        try:
            _start()
            _write({"kind": kind, "facts": facts})
            frame = _read(20)
            if frame != {"step": "generate", "evidence": facts}:
                raise ValueError("DeerFlow 未返回本任务获准的原始资料")
            result = paid_call()
            _write({"draft": result})
            if _read(20) != {"step": "reviewed"}:
                raise ValueError("DeerFlow 未能核对本次草稿的来源")
            return result
        except BaseException:
            # A half-consumed exchange may never be reused for another resident.
            _stop()
            raise
