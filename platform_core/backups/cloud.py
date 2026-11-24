"""Transfer immutable encrypted objects using operator-authorized cloud profiles."""

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .. import secure_storage

PROVIDERS = {
    "icloud": "iCloud Drive",
    "115": "115 网盘",
    "baidu": "百度网盘",
    "offsite": "其他异地存储",
}
OBJECT = re.compile(r"ak-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}-[0-9a-f]{64}\.akbak")


class TransferError(ValueError):
    pass


def locations():
    """Only deployment-owned paths are accepted, never remote arguments from HTTP clients."""
    path = os.environ.get("NH_BACKUP_LOCATIONS_FILE")
    if not path:
        path = (
            Path(__file__).resolve().parents[2]
            / ".local/platform/backup-locations.json"
        )
        if not path.exists():
            return {}
    try:
        entries = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(entries, dict) or set(entries) - PROVIDERS.keys():
            raise ValueError
        result = {}
        for provider, remote in entries.items():
            if not isinstance(remote, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}:[^:\\\x00-\x1f]{1,240}", remote
            ):
                raise ValueError
            alias, folder = remote.split(":", 1)
            if any(part in ("", ".", "..") for part in folder.split("/")):
                raise ValueError
            result[provider] = alias + ":" + folder
        if len(set(result.values())) != len(result):
            raise ValueError
        return result
    except (OSError, ValueError, TypeError):
        raise TransferError("异地位置配置不可用，请核对部署配置") from None


def binary():
    override = os.environ.get("NH_RCLONE_BIN")
    if override:
        return override
    installed = Path(__file__).resolve().parents[2] / ".local/backup-tools/rclone"
    return str(installed) if installed.is_file() else shutil.which("rclone") or "rclone"


def run(*args):
    # rclone may include signed URLs in diagnostics. Only return action-level errors.
    try:
        return subprocess.run(
            [
                binary(),
                *args,
                "--retries",
                "2",
                "--low-level-retries",
                "2",
                "--contimeout",
                "15s",
                "--timeout",
                "2m",
                "--log-level",
                "ERROR",
            ],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=3000,
        ).stdout.decode("utf-8")
    except (OSError, UnicodeError, subprocess.SubprocessError):
        raise TransferError("云端传输未完成，请核对账号授权、空间和网络") from None


def hash_file(path):
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def object_name(snapshot, digest):
    name = snapshot + "-" + digest + ".akbak"
    if not OBJECT.fullmatch(name):
        raise TransferError("快照对象编号无效")
    return name


def upload(path, remote, name):
    if not OBJECT.fullmatch(name):
        raise TransferError("云端对象编号无效")
    with path.open("rb") as stream:
        if stream.read(len(secure_storage.MAGIC)) not in secure_storage.SNAPSHOT_FORMATS:
            raise TransferError("只可发送本系统加密快照")
    expected = name[-70:-6]
    if hash_file(path) != expected:
        raise TransferError("本机快照校验失败，已停止传输")
    destination = remote + "/" + name
    run("copyto", "--ignore-times", str(path), destination)
    # Works for providers without a native SHA256 API, including iCloud Drive.
    proof = run("hashsum", "SHA256", "--download", destination).split()
    if not proof or proof[0].lower() != expected:
        raise TransferError("异地回读校验未通过")


def list_files(remote):
    return sorted(
        (
            n
            for n in run("lsf", remote, "--files-only", "--max-depth", "1").splitlines()
            if OBJECT.fullmatch(n)
        ),
        reverse=True,
    )


def download(remote, name, destination):
    destination = Path(destination)
    if not OBJECT.fullmatch(name) or destination.exists():
        raise ValueError("请选择已登记的云端对象和未使用的本地文件名")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as stage:
        temp = Path(stage) / "received.akbak"
        run("copyto", remote + "/" + name, str(temp))
        if hash_file(temp) != name[-70:-6]:
            raise TransferError("下载副本校验失败")
        temp.chmod(0o600)
        os.link(temp, destination)
        secure_storage.sync_dir(destination.parent)
