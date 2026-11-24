"""An isolated operator vault. It has a separate key and never enters institution backups."""

from contextlib import closing
import hmac
import os
from pathlib import Path
import re
import secrets
import stat

from . import secure_storage as vault

DEFAULT = Path(__file__).resolve().parents[1] / ".local/platform/secrets.sqlite3"
MAX_BYTES = 1024 * 1024


def vault_path():
    return Path(os.environ.get("NH_PLATFORM_VAULT") or DEFAULT)


def key_file(path):
    return Path(
        os.environ.get("NH_PLATFORM_KEY_FILE")
        or path.with_name("." + path.name + ".platform-key")
    )


def connect(path, create=False):
    path = Path(path)
    key = key_file(path)
    if create and not path.exists():
        path.parent.mkdir(mode=0o700, exist_ok=True, parents=True)
        if not key.exists():
            vault.install_key(key, secrets.token_bytes(32))
        try:
            with vault.private_file(path):
                pass
        except FileExistsError:
            pass
    db = vault.open_database(path, vault.read_key(key))
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='workspace'").fetchone():
        db.close()
        raise ValueError("机构业务库和平台运维密库须使用独立路径")
    if create:
        with db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS secrets(name TEXT PRIMARY KEY,data BLOB NOT NULL)"
            )
    return db


def read_value(path, name):
    with closing(connect(path)) as db:
        row = db.execute("SELECT data FROM secrets WHERE name=?", (name,)).fetchone()
        if not row:
            raise ValueError("平台凭据尚未配置")
        return row[0]


def save(path, name, data, *, replace=False):
    if not re.fullmatch(r"[a-z][a-z0-9.-]{0,95}", name):
        raise ValueError("请选择有效的运维档案编号")
    if not 0 < len(data) <= MAX_BYTES:
        raise ValueError("运维文件须在 1 MiB 以内")
    if name == "deepseek":
        try:
            value = data.strip().decode("ascii")
        except UnicodeDecodeError:
            raise ValueError("平台凭据格式不正确") from None
        if not valid_key(value):
            raise ValueError("平台凭据格式不正确")
    with closing(connect(path, create=True)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute("SELECT data FROM secrets WHERE name=?", (name,)).fetchone()
        if (
            prior is not None
            and not hmac.compare_digest(prior[0], data)
            and not replace
        ):
            raise ValueError("该编号已保存不同内容，请核实后使用新编号或明确替换")
        db.execute("INSERT OR REPLACE INTO secrets VALUES(?,?)", (name, data))
    if not hmac.compare_digest(read_value(path, name), data):
        raise ValueError("运维存储回读校验失败")


def valid_key(value):
    return (
        0 < len(value) <= 512
        and value.isascii()
        and all(33 <= ord(c) <= 126 for c in value)
    )


def import_file(path, name, source, remove_source=False, replace=False):
    source = Path(source)
    if source.resolve() in {Path(path).resolve(), key_file(Path(path)).resolve()}:
        raise ValueError("禁止把运维数据库及其密钥当作凭据导入")
    fd = os.open(
        source,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
    )
    with os.fdopen(fd, "rb") as stream:
        start = os.fstat(fd)
        if not stat.S_ISREG(start.st_mode) or (
            os.name == "posix" and start.st_uid != os.geteuid()
        ):
            raise ValueError("请指定由运维账号持有的普通文件")
        data = stream.read(MAX_BYTES + 1)
        save(path, name, data, replace=replace)
        if remove_source:
            current = source.lstat()
            if (
                not os.path.samestat(start, current)
                or start.st_mtime_ns != current.st_mtime_ns
                or start.st_size != current.st_size
            ):
                raise ValueError("原文件已变化，请再次核对")
            stream.seek(0)
            if not hmac.compare_digest(
                stream.read(MAX_BYTES + 1), read_value(path, name)
            ):
                raise ValueError("移除原件前内容核验失败")
            source.unlink()
            vault.sync_dir(source.parent)
