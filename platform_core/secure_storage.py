"""Encrypted database connections, offline migration and authenticated point-in-time copies."""

from contextlib import closing
from hashlib import sha256
import hmac
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import sys
import tempfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

try:
    from sqlcipher3 import dbapi2 as cipherdb
except ImportError:
    # Operator-managed local installation, shared with the service and recovery CLI.
    local = Path(__file__).resolve().parent.parent / ".local/storage-runtime"
    if local.is_dir():
        sys.path.append(str(local))
    try:
        from sqlcipher3 import dbapi2 as cipherdb
    except ImportError as error:
        raise RuntimeError("缺少 SQLCipher，请安装 requirements-storage.txt") from error

INTEGRITY_ERRORS = (sqlite3.IntegrityError, cipherdb.IntegrityError)
OPERATIONAL_ERRORS = (sqlite3.OperationalError, cipherdb.OperationalError)

MAGIC = b"ANKANG-SNAPSHOT\x01"
SQLITE_HEADER = b"SQLite format 3\x00"
BLOCK = 1024 * 1024


def key_location(db_path):
    configured = os.environ.get("NH_STORAGE_KEY_FILE")
    return (
        Path(configured)
        if configured
        else Path(db_path).with_name("." + Path(db_path).name + ".storage-key")
    )


def sync_dir(directory):
    if os.name == "posix":
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def private_file(path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(fd, "wb")


def read_key(path):
    fd = os.open(
        path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    )
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or (
            os.name == "posix" and (info.st_uid != os.geteuid() or info.st_mode & 0o077)
        ):
            raise ValueError("存储密钥须为服务账号独占的普通文件，Unix 权限为 0600")
        key = stream.read(33)
        if len(key) != 32:
            raise ValueError("存储密钥文件长度应为 32 字节")
        return key


def install_key(path, value):
    """Publish fully written key material without replacing an existing installation."""
    path = Path(path)
    with tempfile.TemporaryDirectory(prefix=".ak-key-", dir=path.parent) as tmp:
        draft = Path(tmp) / "secret"
        with private_file(draft) as out:
            out.write(value)
            out.flush()
            os.fsync(out.fileno())
        try:
            os.link(draft, path)
        except FileExistsError:
            return
        sync_dir(path.parent)


def derive(master, purpose):
    # Independent fixed-purpose subkeys from a uniformly random 256-bit root.
    return hmac.digest(master, b"ankang.storage.v1/" + purpose, "sha256")


def open_database(path, master, *, new=False):
    path = Path(path)
    if new:
        with private_file(path):
            pass
    if path.is_symlink() or not path.is_file():
        raise ValueError("请选择有效的机构数据库文件")
    db = cipherdb.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=8)
    try:
        db.execute("PRAGMA key = \"x'" + derive(master, b"database").hex() + "'\"")
        if not db.execute("PRAGMA cipher_version").fetchone():
            raise RuntimeError("数据库驱动未启用 SQLCipher")
        db.execute("PRAGMA temp_store=MEMORY")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("SELECT count(*) FROM sqlite_master").fetchone()
        db.row_factory = cipherdb.Row
        return db
    except BaseException:
        db.close()
        raise


def legacy_file(path):
    with Path(path).open("rb") as source:
        return source.read(16) == SQLITE_HEADER


def prepare_database(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("数据库路径不能是符号链接")
    if path.exists() and not path.is_file():
        raise ValueError("请指定普通数据库文件")
    keyfile = key_location(path)
    if path.exists() and legacy_file(path):
        raise ValueError("旧版明文数据库须先停机执行 manage_storage.py migrate")
    if not keyfile.exists():
        if path.exists() and path.stat().st_size:
            raise ValueError("缺少原数据库的存储密钥，请使用离线恢复材料")
        install_key(keyfile, secrets.token_bytes(32))
    key = read_key(keyfile)
    if not path.exists():
        try:
            with private_file(path):
                pass
        except FileExistsError:
            pass
    return keyfile, key


def verify(db):
    if db.execute("PRAGMA cipher_integrity_check").fetchone() is not None:
        raise ValueError("加密页面认证失败")
    row = db.execute("PRAGMA integrity_check").fetchone()
    if not row or row[0] != "ok":
        raise ValueError("数据库结构校验失败")
    value = db.execute("SELECT revision FROM workspace WHERE id=1").fetchone()
    if value is None:
        raise ValueError("文件缺少机构业务工作区")
    return {
        "revision": value[0],
        "schemaVersion": db.execute("PRAGMA user_version").fetchone()[0],
    }


def migrate_database(path):
    """Run with the old service stopped. The original database is the last file replaced."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("没有找到要迁移的机构数据库")
    keyfile = key_location(path)
    if not legacy_file(path):
        with closing(open_database(path, read_key(keyfile))) as db:
            return verify(db)
    if not keyfile.exists():
        install_key(keyfile, secrets.token_bytes(32))
    master = read_key(keyfile)
    with tempfile.TemporaryDirectory(prefix=".ak-migrate-", dir=path.parent) as tmp:
        encrypted = Path(tmp) / "encrypted"
        with private_file(encrypted):
            pass
        with closing(
            cipherdb.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=2)
        ) as source:
            source.execute("PRAGMA temp_store=MEMORY")
            if (
                source.execute("PRAGMA main.journal_mode=DELETE").fetchone()[0]
                != "delete"
            ):
                raise ValueError("请先停止仍在使用旧库的服务")
            source.execute("PRAGMA locking_mode=EXCLUSIVE")
            source.execute(
                "ATTACH DATABASE ? AS sealed KEY ?",
                (str(encrypted), "x'" + derive(master, b"database").hex() + "'"),
            )
            source.execute("BEGIN EXCLUSIVE")
            revision = source.execute(
                "SELECT revision FROM workspace WHERE id=1"
            ).fetchone()[0]
            version = source.execute("PRAGMA main.user_version").fetchone()[0]
            source.execute("SELECT sqlcipher_export('sealed')")
            source.execute(f"PRAGMA sealed.user_version={int(version)}")
            source.commit()
            source.execute("DETACH DATABASE sealed")
        with closing(open_database(encrypted, master)) as check:
            info = verify(check)
            if info != {"revision": revision, "schemaVersion": version}:
                raise ValueError("迁移数据版本不匹配")
        if any(
            Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")
        ):
            raise ValueError("旧库仍有活动日志，请停机重试迁移")
        os.replace(encrypted, path)
        sync_dir(path.parent)
        return info


def create_snapshot(store, destination):
    """Capture a consistent online backup including WAL commits, then seal and publish atomically."""
    destination = Path(destination)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError("此快照文件已存在")
    master = read_key(store.storage_key_file)
    if not hmac.compare_digest(master, store._storage_master):
        raise ValueError("运行中的主密钥与磁盘不一致，请核对部署密钥")
    with tempfile.TemporaryDirectory(prefix=".ak-snap-", dir=destination.parent) as tmp:
        cold, packet = Path(tmp) / "cold", Path(tmp) / "sealed"
        with (
            closing(store.connect()) as source,
            closing(open_database(cold, master, new=True)) as target,
        ):
            # A pinned WAL view prevents active writers from restarting each backup step.
            source.execute("BEGIN")
            revision = source.execute(
                "SELECT revision FROM workspace WHERE id=1"
            ).fetchone()[0]
            source.backup(target, pages=256, sleep=0.03)
            source.rollback()  # Release the WAL reader before verifying and sealing the copy.
            target.execute("PRAGMA journal_mode=DELETE")
            info = verify(target)
            if info["revision"] != revision:
                raise ValueError("快照与起始读取修订号不匹配")
        nonce, salt = secrets.token_bytes(12), secrets.token_bytes(32)
        header = MAGIC + salt + nonce
        seal = Cipher(
            algorithms.AES(derive(master, b"snapshot/" + salt)), modes.GCM(nonce)
        ).encryptor()
        seal.authenticate_additional_data(header)
        digest = sha256()
        with cold.open("rb") as raw, private_file(packet) as out:
            out.write(header)
            digest.update(header)
            while chunk := raw.read(BLOCK):
                sealed = seal.update(chunk)
                out.write(sealed)
                digest.update(sealed)
            tail = seal.finalize() + seal.tag
            out.write(tail)
            digest.update(tail)
            out.flush()
            os.fsync(out.fileno())
        os.link(packet, destination)
        sync_dir(destination.parent)
        return {**info, "size": packet.stat().st_size, "sha256": digest.hexdigest()}


def restore_snapshot(source, target_db, recovery_key_file):
    """Verify into an encrypted staging database and publish only a complete, fresh recovery."""
    source, target_db = Path(source), Path(target_db)
    if (
        target_db.exists()
        or target_db.is_symlink()
        or any(Path(str(target_db) + x).exists() for x in ("-wal", "-shm", "-journal"))
    ):
        raise FileExistsError("恢复目标须为全新路径")
    master = read_key(recovery_key_file)
    target_db.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".ak-restore-", dir=target_db.parent
    ) as tmp:
        cold = Path(tmp) / "encrypted"
        with source.open("rb") as raw, private_file(cold) as out:
            header = raw.read(len(MAGIC) + 44)
            if len(header) != len(MAGIC) + 44 or not header.startswith(MAGIC):
                raise ValueError("无法识别快照格式")
            size = os.fstat(raw.fileno()).st_size - len(header) - 16
            if size < 1:
                raise ValueError("快照内容不完整")
            raw.seek(-16, os.SEEK_END)
            tag = raw.read(16)
            raw.seek(len(header))
            salt, nonce = header[len(MAGIC) : -12], header[-12:]
            decryptor = Cipher(
                algorithms.AES(derive(master, b"snapshot/" + salt)),
                modes.GCM(nonce, tag),
            ).decryptor()
            decryptor.authenticate_additional_data(header)
            while size:
                chunk = raw.read(min(BLOCK, size))
                if not chunk:
                    raise ValueError("快照传输不完整")
                out.write(decryptor.update(chunk))
                size -= len(chunk)
            try:
                out.write(decryptor.finalize())
            except InvalidTag:
                raise ValueError("快照认证失败，请核对密钥及文件完整性") from None
            out.flush()
            os.fsync(out.fileno())
        with closing(open_database(cold, master)) as db:
            info = verify(db)
            # Restored instances start new sessions and a new, explicitly linked replica set.
            # Child delivery rows precede parent points. Old schemas may lack these tables.
            local_tables = (
                "sessions",
                "backup_retrievals",
                "backup_restores",
                "backup_imports",
                "backup_exports",
                "backup_deliveries",
                "backup_checks",
                "backup_points",
                "backup_locations",
            )
            existing = {
                r[0]
                for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            with db:
                if "family_round_preferences" in existing:
                    # A disaster-recovery host cannot know which party withdrew consent
                    # after this point. Keep the encrypted evidence and old receipts;
                    # require both parties to opt in again before exposing new reports.
                    db.execute("""UPDATE family_round_preferences
                        SET allowed=0, subscribed=0, generation=generation+1
                        WHERE allowed=1 OR subscribed=1""")
                for table in local_tables:
                    if table in existing:
                        db.execute("DELETE FROM " + table)
        keyfile = key_location(target_db)
        if not keyfile.exists():
            install_key(keyfile, master)
        if not hmac.compare_digest(read_key(keyfile), master):
            raise ValueError("恢复目标的存储密钥与备份不一致，请选择独立恢复目录")
        os.link(cold, target_db)
        sync_dir(target_db.parent)
        return info


RECOVERY_MAGIC = b"ANKANG-RECOVERY\x01"


def recovery_cipher(password, salt):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    # v1 is fixed to 128 MiB, independent of untrusted file content.
    key = Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(
        password.encode("utf-8")
    )
    return AESGCM(key)


def wrap_recovery_key(keyfile, destination, password):
    if len(password) < 14:
        raise ValueError("恢复口令至少 14 个字符")
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError("请使用全新恢复材料路径")
    master = read_key(keyfile)
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    header = RECOVERY_MAGIC + salt + nonce
    wrapped = header + recovery_cipher(password, salt).encrypt(nonce, master, header)
    install_key(destination, wrapped)
    if destination.read_bytes() != wrapped:
        raise FileExistsError("恢复材料目标路径已被占用")
    return {"wrapped": True}


def unwrap_recovery_key(source, destination, password):
    with Path(source).open("rb") as raw:
        packet = raw.read(len(RECOVERY_MAGIC) + 28 + 48 + 1)
    header = packet[: len(RECOVERY_MAGIC) + 28]
    if (
        not header.startswith(RECOVERY_MAGIC)
        or len(packet) != len(RECOVERY_MAGIC) + 28 + 48
    ):
        raise ValueError("离线恢复材料格式无效")
    try:
        master = recovery_cipher(password, header[len(RECOVERY_MAGIC) : -12]).decrypt(
            header[-12:], packet[len(header) :], header
        )
    except InvalidTag:
        raise ValueError("恢复口令或材料认证失败") from None
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("请输入全新的密钥恢复路径")
    install_key(destination, master)
    if not hmac.compare_digest(read_key(destination), master):
        raise FileExistsError("密钥恢复目标路径已被占用")
    return {"unwrapped": True}
