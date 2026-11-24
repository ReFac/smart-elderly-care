"""Daily full backups with a separate delivery queue for each location."""

from contextlib import closing, contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import logging
import os
from pathlib import Path
import re
import threading
import tempfile
import time
from uuid import uuid4

from . import cloud
from .. import activity, history, secure_storage

PERIOD = 24 * 60 * 60
SHANGHAI_OFFSET = 8 * 3600
LEASE = 2 * 60 * 60


def slot_for(stamp):
    return (stamp + SHANGHAI_OFFSET) // PERIOD * PERIOD - SHANGHAI_OFFSET


def init(db):
    from . import exchange

    exchange.init(db)
    db.execute(
        "CREATE TABLE IF NOT EXISTS backup_checks(point TEXT PRIMARY KEY, checked INTEGER NOT NULL)"
    )
    db.execute("""CREATE TABLE IF NOT EXISTS backup_points(
        id TEXT PRIMARY KEY, request TEXT NOT NULL UNIQUE, created INTEGER NOT NULL,
        state TEXT NOT NULL, owner TEXT NOT NULL DEFAULT '', lease TEXT, retry INTEGER NOT NULL DEFAULT 0,
        attempts INTEGER NOT NULL DEFAULT 0, revision INTEGER, bytes INTEGER, digest TEXT,
        captured INTEGER, error TEXT NOT NULL DEFAULT '')""")
    if "source_bytes" not in {
        r[1] for r in db.execute("PRAGMA table_info(backup_points)")
    }:
        db.execute("ALTER TABLE backup_points ADD COLUMN source_bytes INTEGER")
    db.execute("""CREATE TABLE IF NOT EXISTS backup_locations(
        provider TEXT PRIMARY KEY, signature TEXT NOT NULL, linked INTEGER NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS backup_deliveries(
        point TEXT NOT NULL REFERENCES backup_points(id), provider TEXT NOT NULL,
        signature TEXT NOT NULL, state TEXT NOT NULL, retry INTEGER NOT NULL DEFAULT 0,
        attempts INTEGER NOT NULL DEFAULT 0, lease TEXT, verified INTEGER, error TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(point,provider,signature))""")
    db.execute(
        "CREATE INDEX IF NOT EXISTS deliveries_due ON backup_deliveries(provider,signature,state,retry)"
    )


def identifier(stamp):
    return (
        datetime.fromtimestamp(stamp, timezone.utc).strftime("ak-%Y%m%dT%H%M%SZ-")
        + uuid4().hex
    )


def signature(remote):
    return sha256(remote.encode()).hexdigest()


def queued(db, request, stamp, owner=""):
    db.execute(
        "INSERT OR IGNORE INTO backup_points(id,request,created,state,owner) VALUES(?,?,?,'queued',?)",
        (identifier(stamp), request, stamp, owner),
    )
    return db.execute(
        "SELECT id FROM backup_points WHERE request=?", (request,)
    ).fetchone()[0]


def enqueue_deliveries(db):
    db.execute("""INSERT OR IGNORE INTO backup_deliveries(point,provider,signature,state)
        SELECT p.id,t.provider,t.signature,'queued' FROM backup_points p CROSS JOIN backup_locations t
        WHERE p.state='ready'""")


def require_owner(store, db, token):
    actor = store.actor(db, token)
    if actor["kind"] != "owner":
        raise PermissionError("仅总管理员可管理机构快照和异地备份")
    return actor


def audit(db, store, actor, action, summary, comment=""):
    revision = db.execute(
        "UPDATE workspace SET revision=revision+1 WHERE id=1 RETURNING revision"
    ).fetchone()[0]
    activity.write(
        db,
        revision,
        store.now().isoformat(timespec="seconds"),
        action,
        summary,
        actor,
        {},
        {},
        comment=comment,
    )


def private_directory(store):
    directory = store.path.parent / (store.path.name + ".snapshots")
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("本机快照目录无效")
    return directory


@contextmanager
def process_lock(folder, name, wait=False):
    with (folder / ("." + name + ".lock")).open("a+b") as handle:
        try:
            if os.name == "nt":
                import msvcrt

                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(
                    handle.fileno(), msvcrt.LK_LOCK if wait else msvcrt.LK_NBLCK, 1
                )
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except (BlockingIOError, PermissionError):
            yield False
            return
        yield True


class BackupService:
    def __init__(self, store):
        self.store = store
        self.folder = private_directory(store)
        self.stopping = threading.Event()
        self.wake = threading.Event()
        self.threads = []
        self.next_cleanup = 0

    def request(self, token, key, note=""):
        if not isinstance(key, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{12,80}", key):
            raise ValueError("需要有效的操作编号")
        with closing(self.store.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            actor = require_owner(self.store, db, token)
            request = "manual:" + actor["id"] + ":" + key
            prior = db.execute(
                "SELECT id FROM backup_points WHERE request=?", (request,)
            ).fetchone()
            if prior:
                return {"id": prior[0]}
            history.watch(db, "backup.create")
            point = queued(db, request, int(time.time()), actor["id"])
            audit(
                db, self.store, actor, "backup.create", "请求创建完整加密时间点", note
            )
        self.wake.set()
        return {"id": point}

    def link(self, token, provider, note=""):
        with closing(self.store.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            actor = require_owner(self.store, db, token)
            remotes = cloud.locations()
            if not isinstance(provider, str) or provider not in remotes:
                raise ValueError("请先在服务器授权并登记这个网盘目录")
            fingerprint = signature(remotes[provider])
            previous = db.execute(
                "SELECT signature FROM backup_locations WHERE provider=?", (provider,)
            ).fetchone()
            if not previous or previous[0] != fingerprint:
                history.watch(db, "backup.link")
                db.execute(
                    """INSERT INTO backup_locations VALUES(?,?,?)
                    ON CONFLICT(provider) DO UPDATE SET signature=excluded.signature,linked=excluded.linked""",
                    (provider, fingerprint, int(time.time())),
                )
                audit(
                    db,
                    self.store,
                    actor,
                    "backup.link",
                    "连接加密副本位置 " + cloud.PROVIDERS[provider],
                    note,
                )
            enqueue_deliveries(db)
        self.wake.set()
        return {"linked": True}

    def status(self, token, before=0):
        from .exchange import policy

        if type(before) is not int or not 0 <= before < 2**63:
            raise ValueError("快照分页游标无效")
        now = int(time.time())
        with closing(self.store.connect()) as db, db:
            db.execute("BEGIN")
            require_owner(self.store, db, token)
            try:
                remotes = cloud.locations()
                config_error = ""
            except cloud.TransferError as error:
                remotes = {}
                config_error = str(error)
            linked = {
                r["provider"]: r["signature"]
                for r in db.execute("SELECT * FROM backup_locations")
            }
            points = [
                dict(r)
                for r in db.execute(
                    """SELECT rowid AS cursor,id,created,state,revision,bytes,source_bytes AS sourceBytes,captured,error,
                 CASE WHEN request LIKE 'import:%' THEN 'import' WHEN request LIKE 'protection:%' THEN 'protection' WHEN owner='' THEN 'automatic' ELSE 'manual' END AS kind FROM backup_points
                 WHERE (?=0 OR rowid<?) ORDER BY rowid DESC LIMIT 51""",
                    (before, before),
                )
            ]
            more = len(points) > 50
            points = points[:50]
            for p in points:
                checked = db.execute(
                    "SELECT checked FROM backup_checks WHERE point=?", (p["id"],)
                ).fetchone()
                p["checked"] = checked[0] if checked else None
                if (
                    p["state"] == "ready"
                    and not (self.folder / (p["id"] + ".akbak")).is_file()
                ):
                    p["state"] = "missing"
                p["copies"] = [
                    dict(r)
                    for r in db.execute(
                        """SELECT d.provider,d.state,d.verified,d.error FROM backup_deliveries d
                    JOIN backup_locations t ON t.provider=d.provider AND t.signature=d.signature WHERE d.point=?""",
                        (p["id"],),
                    )
                ]
            locations = []
            for k, label in cloud.PROVIDERS.items():
                enabled = k in remotes and linked.get(k) == signature(remotes[k])
                state = (
                    "linked"
                    if enabled
                    else "available"
                    if k in remotes
                    else "unconfigured"
                )
                if k in linked and not enabled:
                    state = "changed"
                locations.append(
                    {"id": k, "label": label, "state": state, "available": k in remotes}
                )
            return {
                "intervalHours": PERIOD // 3600,
                "policy": policy(db),
                "nextAutomatic": slot_for(now) + PERIOD,
                "locations": locations,
                "points": points,
                "nextCursor": points[-1]["cursor"] if more else None,
                "configError": config_error,
            }

    def inspect_packet(self, source):
        with tempfile.TemporaryDirectory(prefix=".verify-", dir=self.folder) as tmp:
            return secure_storage.restore_snapshot(
                source, Path(tmp) / "verify.sqlite3", self.store.storage_key_file
            )

    def mark_damaged(self, point):
        with closing(self.store.connect()) as db, db:
            db.execute(
                "UPDATE backup_points SET state='damaged',error='本机密文校验失败，请使用已校验的异地副本' WHERE id=?",
                (point,),
            )
            db.execute("DELETE FROM backup_checks WHERE point=?", (point,))
        self.wake.set()

    def verify(self, token, point, note=""):
        with closing(self.store.connect()) as db, db:
            require_owner(self.store, db, token)
            row = db.execute(
                "SELECT revision,digest FROM backup_points WHERE id=? AND state='ready'",
                (point,),
            ).fetchone()
            if not row:
                raise ValueError("请选择可用的完整快照")
        source = self.folder / (point + ".akbak")
        if cloud.hash_file(source) != row["digest"]:
            self.mark_damaged(point)
            raise ValueError("快照密文校验失败")
        if self.inspect_packet(source)["revision"] != row["revision"]:
            raise ValueError("恢复出的业务版本不一致")
        with closing(self.store.connect()) as db, db:
            actor = require_owner(self.store, db, token)
            history.watch(db, "backup.verify")
            db.execute(
                "INSERT OR REPLACE INTO backup_checks VALUES(?,?)",
                (point, int(time.time())),
            )
            audit(
                db,
                self.store,
                actor,
                "backup.verify",
                "已完成隔离恢复核验 " + point,
                note,
            )
        return {"verified": True}

    def retry(self, token, note=""):
        with closing(self.store.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            actor = require_owner(self.store, db, token)
            history.watch(db, "backup.retry")
            db.execute("UPDATE backup_deliveries SET retry=0 WHERE state='failed'")
            db.execute("UPDATE backup_points SET retry=0 WHERE state='failed'")
            audit(
                db, self.store, actor, "backup.retry", "请求重新核验未完成的备份", note
            )
        self.wake.set()
        return {"queued": True}

    def capture(self, now=None, *, wait=False):
        with process_lock(self.folder, "capture", wait) as locked:
            if not locked:
                return False
            captured = self._capture(now)
            stamp = int(time.time()) if now is None else now
            if stamp >= self.next_cleanup:
                from . import exchange

                try:
                    exchange.cleanup(self, stamp)
                except (OSError, cloud.TransferError) as error:
                    logging.error("快照保留策略待重试 (%s)", type(error).__name__)
                self.next_cleanup = stamp + 300
            return captured

    def _capture(self, now):
        stamp = int(time.time()) if now is None else now
        lease = uuid4().hex
        with closing(self.store.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            current = queued(db, "slot:" + str(slot_for(stamp)), stamp)
            while True:
                state = db.execute(
                    "SELECT state FROM backup_points WHERE id=?", (current,)
                ).fetchone()[0]
                if (
                    state == "ready"
                    and not (self.folder / (current + ".akbak")).is_file()
                ):
                    db.execute(
                        "UPDATE backup_points SET state='missing',error='原时间点的本机副本缺失' WHERE id=?",
                        (current,),
                    )
                elif state not in ("damaged", "missing"):
                    break
                current = queued(db, "repair:" + current, stamp)
            row = db.execute(
                """SELECT id FROM backup_points WHERE state IN ('queued','failed','creating')
                AND (retry<=? OR state='creating') ORDER BY (id=?) DESC,created LIMIT 1""",
                (stamp, current),
            ).fetchone()
            if not row:
                return False
            point = row[0]
            db.execute(
                "UPDATE backup_points SET state='creating',lease=?,retry=?,attempts=attempts+1,error='' WHERE id=?",
                (lease, stamp + LEASE, point),
            )
        packet = self.folder / (point + ".akbak")
        try:
            if packet.exists():
                # Publication is atomic. A crash may precede the separate ledger commit.
                try:
                    result = self.inspect_packet(packet)
                except ValueError:
                    self.mark_damaged(point)
                    return True
                result.update(
                    sha256=cloud.hash_file(packet), size=packet.stat().st_size
                )
                captured = int(packet.stat().st_mtime)
            else:
                result = secure_storage.create_snapshot(self.store, packet)
                captured = stamp
            with closing(self.store.connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                if not db.execute(
                    "SELECT 1 FROM backup_points WHERE id=? AND lease=?", (point, lease)
                ).fetchone():
                    return False
                db.execute(
                    "UPDATE backup_points SET state='ready',digest=?,bytes=?,revision=?,captured=?,source_bytes=?,lease=NULL,retry=0 WHERE id=?",
                    (
                        result["sha256"],
                        result["size"],
                        result["revision"],
                        captured,
                        result.get("sourceBytes"),
                        point,
                    ),
                )
                enqueue_deliveries(db)
            return True
        except Exception:
            with closing(self.store.connect()) as db, db:
                db.execute(
                    "UPDATE backup_points SET state='failed',retry=?,error=?,lease=NULL WHERE id=? AND lease=?",
                    (
                        stamp + 60,
                        "本机快照失败，请检查磁盘空间、存储密钥和写入权限",
                        point,
                        lease,
                    ),
                )
            return False

    def deliver(self, provider, now=None):
        if provider not in cloud.PROVIDERS:
            raise ValueError("未知副本位置")
        with process_lock(self.folder, "delivery-" + provider) as locked:
            return self._deliver(provider, now) if locked else False

    def _deliver(self, provider, now):
        stamp = int(time.time()) if now is None else now
        remote = cloud.locations().get(provider)
        if not remote:
            return False
        fingerprint = signature(remote)
        lease = uuid4().hex
        with closing(self.store.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT d.point,d.attempts,p.digest FROM backup_deliveries d JOIN backup_points p ON p.id=d.point
                JOIN backup_locations t ON t.provider=d.provider AND t.signature=d.signature
                WHERE d.provider=? AND d.signature=? AND d.state<>'verified' AND (d.retry<=? OR d.state='sending') AND p.state='ready'
                ORDER BY p.created DESC,p.rowid DESC LIMIT 1""",
                (provider, fingerprint, stamp),
            ).fetchone()
            if not row:
                return False
            point, attempts, digest = row
            args = (point, provider, fingerprint)
            db.execute(
                """UPDATE backup_deliveries SET state='sending',retry=?,lease=?,attempts=attempts+1
                WHERE point=? AND provider=? AND signature=?""",
                (stamp + LEASE, lease, *args),
            )
        try:
            cloud.upload(
                self.folder / (point + ".akbak"),
                remote,
                cloud.object_name(point, digest),
            )
            state, verified, retry, error = (
                "verified",
                int(time.time()) if now is None else stamp,
                0,
                "",
            )
        except (cloud.TransferError, OSError) as problem:
            state, verified, retry = (
                "failed",
                None,
                stamp + min(3600, 30 * 2 ** min(7, attempts)),
            )
            error = (
                str(problem)
                if isinstance(problem, cloud.TransferError)
                else "本机快照不可读取"
            )
        with closing(self.store.connect()) as db, db:
            db.execute(
                """UPDATE backup_deliveries SET state=?,verified=?,retry=?,error=?,lease=NULL
                WHERE point=? AND provider=? AND signature=? AND lease=?""",
                (state, verified, retry, error, *args, lease),
            )
        return True

    def start(self):
        if self.threads:
            return

        def local_loop():
            while not self.stopping.is_set():
                self.wake.clear()
                try:
                    again = self.capture()
                except Exception as error:
                    logging.error("本地快照调度失败 (%s)", type(error).__name__)
                    again = False
                if not again:
                    self.wake.wait(
                        min(
                            30,
                            max(
                                1,
                                slot_for(int(time.time())) + PERIOD - int(time.time()),
                            ),
                        )
                    )

        def remote_loop(provider):
            while not self.stopping.is_set():
                try:
                    again = self.deliver(provider)
                except Exception:
                    again = False
                if not again:
                    self.stopping.wait(10)

        self.threads = [
            threading.Thread(target=local_loop, name="snapshots", daemon=True)
        ]
        self.threads.extend(
            threading.Thread(
                target=remote_loop, args=(p,), name="backup-" + p, daemon=True
            )
            for p in cloud.PROVIDERS
        )
        for t in self.threads:
            t.start()

    def stop(self):
        self.stopping.set()
        self.wake.set()
        for t in self.threads:
            t.join(timeout=1)
