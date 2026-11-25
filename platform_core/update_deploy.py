"""Switch managed institution releases only after a verified full backup."""

from contextlib import closing
from datetime import datetime
from hashlib import sha256
from http.client import HTTPConnection, HTTPException
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from . import history, secure_storage, updates
from .backups import audit, enqueue_deliveries, identifier, private_directory, process_lock


MAX_UNPACKED = 600 * 1024 * 1024


def app_file(name):
    parts = name.split("/")
    return name == "server.py" or (
        len(parts) >= 2 and parts[0] in ("platform_core", "web")
        and all(re.fullmatch(r"[a-zA-Z0-9_-][a-zA-Z0-9_.-]{0,150}", part) for part in parts)
        and "__pycache__" not in parts and not name.endswith((".pyc", ".pyo"))
    )


def unpack_archive(archive, release, destination):
    size, digest = 0, sha256()
    with archive.open("rb") as stream:
        while chunk := stream.read(updates.CHUNK):
            size += len(chunk)
            if size > release["size"]:
                raise updates.UpdateError("安装前更新包长度复核不一致")
            digest.update(chunk)
        if size != release["size"] or digest.hexdigest() != release["sha256"]:
            raise updates.UpdateError("安装前更新包签名摘要复核失败")
        stream.seek(0)
        try:
            with ZipFile(stream) as bundle:
                entries = bundle.infolist()
                names = {entry.filename for entry in entries}
                required = {"server.py", "platform_core/store.py", "web/index.html"}
                if (
                    not required <= names or not 3 <= len(entries) <= 5000
                    or len(entries) != len(names)
                    or sum(entry.file_size for entry in entries) > MAX_UNPACKED
                ):
                    raise updates.UpdateError("更新包的目录或大小不符合部署要求")
                for entry in entries:
                    kind = stat.S_IFMT(entry.external_attr >> 16)
                    if not app_file(entry.filename) or kind not in (0, stat.S_IFREG) or entry.flag_bits & 1:
                        raise updates.UpdateError("更新包包含不支持的路径、文件类型或加密成员")
                for entry in entries:
                    target = destination / entry.filename
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(entry) as source, secure_storage.private_file(target) as out:
                        shutil.copyfileobj(source, out)
                        out.flush()
                        os.fsync(out.fileno())
        except (BadZipFile, RuntimeError) as error:
            raise updates.UpdateError("无法完整读取已签名的安装包") from error


def current_database(path):
    keyfile = secure_storage.key_location(path)
    key = secure_storage.read_key(keyfile)

    return SimpleNamespace(
        path=path,
        storage_key_file=keyfile,
        _storage_master=key,
        connect=lambda: secure_storage.open_database(path, key),
        now=lambda: datetime.now(updates.LOCAL),
    )


def catalog(store, backup, owner):
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        history.watch(db, "backup.update")
        point, stamp, result = backup["id"], backup["stamp"], backup["info"]
        db.execute(
            """INSERT OR IGNORE INTO backup_points
            (id,request,created,captured,state,owner,revision,bytes,digest,source_bytes)
            VALUES(?,?,?,?,'ready',?,?,?,?,?)""",
            (point, "upgrade:" + point, stamp, stamp, owner,
             result["revision"], result["size"], result["sha256"], result.get("sourceBytes")),
        )
        db.execute("INSERT OR IGNORE INTO backup_checks VALUES(?,?)", (point, stamp))
        enqueue_deliveries(db)
        audit(db, store, updates.SERVICE, "backup.update", "已核验更新前的完整机构快照 " + point)


def protection(database, owner):
    store = current_database(database)
    folder = private_directory(store)
    stamp = int(time.time())
    point = identifier(stamp)
    packet = folder / (point + ".akbak")
    with process_lock(folder, "capture", wait=True) as locked:
        if not locked:
            raise updates.UpdateError("无法锁定当前快照任务")
        with closing(store.connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            result = secure_storage.create_snapshot(store, packet)
            db.rollback()
        with tempfile.TemporaryDirectory(prefix=".update-verify-", dir=folder) as tmp:
            verified = secure_storage.restore_snapshot(
                packet, Path(tmp) / "verify.sqlite3", store.storage_key_file,
                same_host=True,
            )
            if verified["revision"] != result["revision"]:
                raise updates.UpdateError("更新前快照的完整恢复核验失败")
        backup = {"id": point, "stamp": stamp, "info": result}
        catalog(store, backup, owner)
        return backup


def restore_previous(database, backup, owner):
    store = current_database(database)
    packet = private_directory(store) / (backup["id"] + ".akbak")
    with tempfile.TemporaryDirectory(prefix=".update-revert-", dir=database.parent) as tmp:
        path = Path(tmp) / "workspace.sqlite3"
        info = secure_storage.restore_snapshot(packet, path, store.storage_key_file, same_host=True)
        if info["revision"] != backup["info"]["revision"]:
            raise updates.UpdateError("回到原版本所需的快照版本不一致")
        with closing(store.connect()) as db:
            checkpoint = db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint[0]:
                raise updates.UpdateError("仍有机构程序占用资料库，无法安全恢复")
        for suffix in ("-wal", "-shm", "-journal"):
            Path(str(database) + suffix).unlink(missing_ok=True)
        os.replace(path, database)
        secure_storage.sync_dir(database.parent)
    catalog(store, backup, owner)


def stop_process(process):
    if process.poll() is not None:
        return
    if os.name == "posix":
        process.send_signal(signal.SIGINT)
    else:
        process.terminate()
    try:
        process.wait(timeout=25)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=10)


class Launcher:
    def __init__(self, root, database, port, *, public_origin=None, demo=False, initial_data="demo"):
        self.root, self.database, self.port = root, database, port
        self.options = ["--initial-data", initial_data]
        if public_origin:
            self.options.extend(("--public-origin", public_origin))
        if demo:
            self.options.append("--demo-public-tour")
        self.database.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.folder = updates.update_directory(database)
        self.source = updates.ReleaseSource()
        self.active = self.folder / "active.json"
        self.journal = self.folder / "install.json"
        self.staged = self.folder / "staged.json"
        self.pending = self.folder / "pending.json"
        self.outcome = self.folder / "outcome.json"
        self.releases = self.folder / "releases"
        self.releases.mkdir(mode=0o700, exist_ok=True)
        self.process = None

    def environment(self, version, boot, gate):
        env = {**os.environ, "NH_UPDATE_MANAGED": "1", "NH_RELEASE_VERSION": version, "NH_UPDATE_BOOT": boot}
        if gate:
            env["NH_UPDATE_GATE"] = str(gate)
        else:
            env.pop("NH_UPDATE_GATE", None)
        local = self.root / ".local"
        if "NH_DEEPSEEK_KEY_FILE" not in env:
            env.setdefault("NH_PLATFORM_VAULT", str(local / "platform" / "secrets.sqlite3"))
        if (locations := local / "platform" / "backup-locations.json").is_file():
            env.setdefault("NH_BACKUP_LOCATIONS_FILE", str(locations))
        if (rclone := local / "backup-tools" / "rclone").is_file():
            env.setdefault("NH_RCLONE_BIN", str(rclone))
        runtime = [str(local / name) for name in ("harness-runtime", "a2a-runtime", "storage-runtime", "payment-runtime", "passkey-runtime") if (local / name).is_dir()]
        if env.get("PYTHONPATH"):
            runtime.append(env["PYTHONPATH"])
        if runtime:
            env["PYTHONPATH"] = os.pathsep.join(runtime)
        return env

    def start(self, code, version, *, gate=None):
        boot = uuid4().hex
        self.process = subprocess.Popen(
            [sys.executable, str(code / "server.py"), "--db", str(self.database),
             "--port", str(self.port), *self.options],
            cwd=self.root, env=self.environment(version, boot, gate),
        )
        deadline = time.monotonic() + 45
        while self.process.poll() is None and time.monotonic() < deadline:
            with closing(HTTPConnection("127.0.0.1", self.port, timeout=1)) as connection:
                try:
                    connection.request("GET", "/api/health")
                    response = connection.getresponse()
                    if response.status == 200 and json.loads(response.read(4096)).get("boot") == boot:
                        return
                except (OSError, ValueError, HTTPException):
                    pass
            time.sleep(0.1)
        raise updates.UpdateError("候选版本未通过本机服务启动检查")

    def installed(self):
        active = updates.read_json(self.active)
        if active:
            version = active["version"]
            updates.parse_version(version)
            return self.releases / version, version
        return self.root, updates.BASE_VERSION

    def recovery(self):
        record = updates.read_json(self.journal)
        if not record:
            return
        current = self.installed()[1]
        if current != record["version"]:
            self.restore(record)
            self.record("failed", record, "更新未完成，已恢复更新前的机构资料")
        else:
            self.record("installed", record, "已安装并保留完整更新前快照")
        self.pending.unlink(missing_ok=True)
        self.journal.unlink()
        secure_storage.sync_dir(self.folder)

    def record(self, state, record, message):
        backup = record.get("backup") or {}
        updates.atomic_json(self.outcome, {
            "state": state, "version": record["version"], "message": message,
            "snapshotId": backup.get("id"), "at": int(time.time()),
        })

    def restore(self, record):
        with process_lock(self.folder, "running-server") as locked:
            if not locked:
                raise updates.UpdateError("机构服务仍在运行，恢复前需停止服务")
            restore_previous(self.database, record["backup"], record["actor"])

    def backup(self, actor):
        with process_lock(self.folder, "running-server") as locked:
            if not locked:
                raise updates.UpdateError("旧服务仍在运行，无法核对更新前的时间点")
            return protection(self.database, actor)

    def install(self, request):
        prior, version = self.installed()
        target = request["version"]
        if updates.parse_version(target) <= updates.parse_version(version):
            self.pending.unlink(missing_ok=True)
            return
        try:
            envelope = updates.read_json(self.staged)
            release = self.source.verify(envelope)
            if release["version"] != target:
                raise updates.UpdateError("待安装版本与已签名下载记录不一致")
            folder = self.releases / target
            if folder.exists():
                # An interrupted attempt can leave a staging directory. A new download
                # must be unpacked and verified before it is allowed to start again.
                shutil.rmtree(folder)
            with tempfile.TemporaryDirectory(prefix=".unpack-", dir=self.releases) as tmp:
                content = Path(tmp) / "application"
                content.mkdir(mode=0o700)
                unpack_archive(self.folder / ("application-" + target + ".zip"), release, content)
                os.replace(content, folder)
                secure_storage.sync_dir(self.releases)
            self.record("backing-up", request, "正在停止旧服务并创建完整加密快照")
            stop_process(self.process)
            backup = self.backup(request["actor"])
            record = {**request, "backup": backup}
            updates.atomic_json(self.journal, record)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            message = str(error) if isinstance(error, updates.UpdateError) else "安装前核验或加密备份失败"
            self.record("failed", request, message)
            self.pending.unlink(missing_ok=True)
            if self.process.poll() is not None:
                self.start(prior, version)
            return
        gate = self.folder / ("activate-" + uuid4().hex)
        try:
            self.record("starting", record, "快照已核验，正在检查新版服务")
            self.start(folder, target, gate=gate)
            updates.atomic_json(self.active, {"version": target})
            updates.atomic_json(gate, {"version": target})
        except (OSError, ValueError, subprocess.SubprocessError):
            stop_process(self.process)
            if self.installed()[1] == target:
                if prior == self.root:
                    self.active.unlink()
                    secure_storage.sync_dir(self.folder)
                else:
                    updates.atomic_json(self.active, {"version": version})
            self.restore(record)
            self.record("failed", record, "新版启动检查失败，已回到原版本并恢复更新前的资料")
            self.start(prior, version)
        else:
            self.record("installed", record, "新版已启用，更新前完整快照已保留")
        self.pending.unlink(missing_ok=True)
        self.journal.unlink()
        secure_storage.sync_dir(self.folder)

    def run(self):
        with process_lock(self.folder, "launcher") as locked:
            if not locked:
                raise updates.UpdateError("此机构已经有一个更新托管启动器")
            try:
                self.recovery()
                self.start(*self.installed())
                while self.process.poll() is None:
                    request = updates.read_json(self.pending)
                    if request:
                        self.install(request)
                    time.sleep(1)
            except KeyboardInterrupt:
                return
            finally:
                if self.process is not None:
                    stop_process(self.process)
