"""Resolve signed worker sources separately from operator-provisioned dependencies."""

from hashlib import sha256
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUNDLED = ROOT / "platform_core" / "agents" / "bundled"


def sources(relative):
    folder = ROOT / relative
    return folder if folder.is_dir() else BUNDLED / relative


def install_root():
    # Previous launchers already set the managed flag and start every release
    # in the original installation directory, including when restoring an older release.
    return Path.cwd() if os.environ.get("NH_UPDATE_MANAGED") == "1" else ROOT


def dependencies(kind):
    relative, names = {
        "deerflow": ("deploy/deerflow", ("requirements.txt", "sdk.txt")),
    }[kind]
    signed = sources(relative)
    locks = [(signed / name).read_bytes() for name in names]
    if configured := os.environ.get("NH_AGENT_RUNTIME_STORE"):
        store = Path(configured)
        if not store.is_absolute():
            raise ValueError("NH_AGENT_RUNTIME_STORE 需要绝对路径")
        identifier = sha256(b"".join(locks)).hexdigest()
        versioned = store / kind / identifier
        if versioned.exists():
            if all((versioned / name).read_bytes() == data for name, data in zip(names, locks)):
                return versioned
            raise ValueError("预置运行时与已签名的依赖清单不一致")
    deployed = install_root() / relative
    if all((deployed / name).read_bytes() == data for name, data in zip(names, locks)):
        return deployed
    raise ValueError("本机尚未预置与发布版本匹配的运行时依赖")


def verify_candidate():
    """Start the signed DeerFlow worker before opening the candidate HTTP service."""
    from . import deerflow_chat, deerflow_worker

    ran = False

    def synthetic_reply():
        nonlocal ran
        ran = True
        return {"text": "就绪"}

    def unexpected(*_):
        raise ValueError("运行时自检不应调用机构工具")

    try:
        deerflow_chat.run({}, synthetic_reply, unexpected, unexpected)
        if not ran:
            raise ValueError("DeerFlow 未执行自检对话")
        visited = []
        deerflow_chat.delegate({"care": "核对虚构资料"}, visited.append)
        if visited != ["care"]:
            raise ValueError("DeerFlow 专员委派自检失败")
        deerflow_worker._start()
    finally:
        deerflow_chat.close()
        deerflow_worker._stop()
