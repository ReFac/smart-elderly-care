"""Offline managed binary originals, stored inside the same encrypted database as the records."""

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import hmac
import os
from pathlib import Path, PurePosixPath
import stat

from . import activity
from .secure_storage import BLOCK

MIMES = {
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS storage_assets(
        id INTEGER PRIMARY KEY, namespace TEXT NOT NULL, name TEXT NOT NULL,
        mime TEXT NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL,
        UNIQUE(namespace,name))""")


def canonical(name):
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 1024
        or "\\" in name
        or any(part in ("", ".", "..") for part in name.split("/"))
        or any(ord(c) < 32 for c in name)
    ):
        raise ValueError("请使用目录内的相对档案名称")
    return name


def import_asset(db, namespace, name, file):
    name = canonical(name)
    if namespace not in {"tour", "archive"}:
        raise ValueError("未知附件类型")
    fd = os.open(
        file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    )
    with os.fdopen(fd, "rb") as reader:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("请选择普通文件")
        mime = "application/octet-stream"
        if namespace == "tour":
            mime = MIMES.get(PurePosixPath(name).suffix.lower())
            if not mime or info.st_size > 32 * 1024 * 1024:
                raise ValueError("环境图片须为 32 MiB 以内的 JPEG、PNG 或 WebP")
            head = reader.read(12)
            valid = {
                "image/png": head.startswith(b"\x89PNG\r\n\x1a\n"),
                "image/jpeg": head.startswith(b"\xff\xd8\xff"),
                "image/webp": head[:4] == b"RIFF" and head[8:] == b"WEBP",
            }
            if not valid[mime]:
                raise ValueError("环境图片内容与扩展名不匹配")
            reader.seek(0)
        prior = db.execute(
            "SELECT id,sha256 FROM storage_assets WHERE namespace=? AND name=?",
            (namespace, name),
        ).fetchone()
        digest = hashlib.sha256()
        if not prior:
            cursor = db.execute(
                "INSERT INTO storage_assets(namespace,name,mime,sha256,data) VALUES(?,?,?,'',zeroblob(?))",
                (namespace, name, mime, info.st_size),
            )
            rowid = cursor.lastrowid
            blob = db.open_blob("storage_assets", "data", rowid, False)
        else:
            rowid, signature = prior
            blob = None
        try:
            size = 0
            while chunk := reader.read(BLOCK):
                digest.update(chunk)
                if blob is not None:
                    blob.write(chunk)
                size += len(chunk)
        finally:
            if blob is not None:
                blob.close()
        end = os.fstat(fd)
        if (info.st_size, info.st_mtime_ns) != (size, end.st_mtime_ns):
            raise ValueError("导入期间源文件已改变")
        hexdigest = digest.hexdigest()
        if prior and not hmac.compare_digest(signature, hexdigest):
            raise ValueError("同名文件已有其他内容，请使用新名称保留新版本")
        if not prior:
            db.execute(
                "UPDATE storage_assets SET sha256=? WHERE id=?", (hexdigest, rowid)
            )
            revision = db.execute(
                "UPDATE workspace SET revision=revision+1 WHERE id=1 RETURNING revision"
            ).fetchone()[0]
            activity.write(
                db,
                revision,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "storage.import",
                "导入环境素材" if namespace == "tour" else "导入历史档案",
                {
                    "id": "platform-operator",
                    "username": "platform-operator",
                    "displayName": "平台运维",
                },
                {},
                {},
            )
        # Check persisted content, including pre-existing originals, before reporting success.
        if not hmac.compare_digest(digest_blob(db, rowid), hexdigest):
            raise ValueError("保存内容校验失败")
    return {"namespace": namespace, "name": name, "size": size, "sha256": hexdigest}


def digest_blob(db, rowid, output=None):
    digest = hashlib.sha256()
    with closing(db.open_blob("storage_assets", "data", rowid, True)) as blob:
        while chunk := blob.read(BLOCK):
            digest.update(chunk)
            if output is not None:
                output.write(chunk)
    return digest.hexdigest()


def read_tour(db, url):
    name = canonical(url.removeprefix("/tour-media/"))
    row = db.execute(
        "SELECT data,mime FROM storage_assets WHERE namespace='tour' AND name=?",
        (name,),
    ).fetchone()
    if not row:
        raise FileNotFoundError("环境素材尚未导入加密媒体库")
    return row[0], row[1]


def export_asset(db, namespace, name, destination):
    import tempfile
    from .secure_storage import private_file, sync_dir

    destination = Path(destination)
    record = db.execute(
        "SELECT id,sha256 FROM storage_assets WHERE namespace=? AND name=?",
        (namespace, canonical(name)),
    ).fetchone()
    if not record:
        raise FileNotFoundError("未找到该原件")
    # Only the operator's explicit export creates an external cleartext document.
    with tempfile.TemporaryDirectory(
        prefix=".ak-export-", dir=destination.parent
    ) as tmp:
        artifact = Path(tmp) / "original"
        with private_file(artifact) as out:
            if not hmac.compare_digest(digest_blob(db, record[0], out), record[1]):
                raise ValueError("原件摘要核验失败")
            out.flush()
            os.fsync(out.fileno())
        os.link(artifact, destination)
        sync_dir(destination.parent)
    return {"size": destination.stat().st_size, "sha256": record[1]}
