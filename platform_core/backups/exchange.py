"""Owner-only encrypted snapshot exchanges and rollback-protected online imports."""

from contextlib import closing, contextmanager
from hashlib import sha256
import hmac
import os
from pathlib import Path
import secrets
import tempfile
import time
from uuid import uuid4

from .. import secure_storage, history
from . import (
    audit,
    cloud,
    enqueue_deliveries,
    identifier,
    process_lock,
    require_owner,
    restore_plan,
)

DAY = 86400
DEFAULT_LIMIT = 1024
SIZE_CHOICES = (64, 256, 1024, 4096)
KEEP_CHOICES = (0, 60, 90, 180, 365)


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS backup_policy(
      singleton INTEGER PRIMARY KEY CHECK(singleton=1),retention INTEGER NOT NULL,upload_mib INTEGER NOT NULL,version INTEGER NOT NULL)""")
    db.execute("INSERT OR IGNORE INTO backup_policy VALUES(1,0,?,0)", (DEFAULT_LIMIT,))
    db.execute(
        """CREATE TABLE IF NOT EXISTS backup_retrievals(point TEXT PRIMARY KEY,retrieved INTEGER NOT NULL)"""
    )
    db.execute("""CREATE TABLE IF NOT EXISTS backup_restores(
      revision INTEGER PRIMARY KEY,point TEXT NOT NULL,rollbackPoint TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS backup_imports(
      id TEXT PRIMARY KEY,actor TEXT NOT NULL,created INTEGER NOT NULL,digest TEXT NOT NULL,
      bytes INTEGER NOT NULL,revision INTEGER NOT NULL,point TEXT NOT NULL DEFAULT '')""")
    db.execute("""CREATE TABLE IF NOT EXISTS backup_exports(
      ticket TEXT PRIMARY KEY, actor TEXT NOT NULL,session TEXT NOT NULL,point TEXT NOT NULL,expires INTEGER NOT NULL)""")


def policy(db):
    row = db.execute(
        "SELECT retention,upload_mib,version FROM backup_policy"
    ).fetchone()
    return {
        "retentionDays": row[0],
        "uploadLimitMiB": row[1],
        "version": row[2],
        "historyDays": 60,
    }


comment = history.comment_text


def change_policy(svc, token, payload):
    keep = payload.get("retentionDays")
    size = payload.get("uploadLimitMiB")
    if (
        type(keep) is not int
        or keep not in KEEP_CHOICES
        or type(size) is not int
        or size not in SIZE_CHOICES
    ):
        raise ValueError("请选择有效的保留期和上传限制")
    from ..store import Conflict

    with closing(svc.store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        actor = require_owner(svc.store, db, token)
        before = policy(db)
        if (
            type(payload.get("version")) is not int
            or before["version"] != payload["version"]
        ):
            raise Conflict("备份策略已变化，请重新查看")
        if before["retentionDays"] != keep or before["uploadLimitMiB"] != size:
            history.watch(db, "backup.policy")
            db.execute(
                "UPDATE backup_policy SET retention=?,upload_mib=?,version=version+1 WHERE singleton=1",
                (keep, size),
            )
            audit(
                db,
                svc.store,
                actor,
                "backup.policy",
                f"本机保留期 {before['retentionDays'] or '长期'} → {keep or '长期'}，单次导入上限 {before['uploadLimitMiB']} → {size} MiB",
                comment(payload.get("comment", "")),
            )
        return policy(db)


def unlink(svc, token, provider, note=""):
    with closing(svc.store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        actor = require_owner(svc.store, db, token)
        if provider not in cloud.PROVIDERS:
            raise ValueError("未知位置")
        history.watch(db, "backup.unlink")
        db.execute("DELETE FROM backup_locations WHERE provider=?", (provider,))
        audit(
            db,
            svc.store,
            actor,
            "backup.unlink",
            "停止向目标配送新副本 " + cloud.PROVIDERS[provider],
            comment(note),
        )
    return {"linked": False}


@contextmanager
def exclusive(folder, name):
    with process_lock(folder, name, True) as acquired:
        if not acquired:
            raise ValueError("另一项备份操作仍在进行，请稍后重试")
        yield


def point_source(svc, db, point):
    row = db.execute(
        "SELECT id,bytes,digest,revision FROM backup_points WHERE id=? AND state='ready'",
        (point,),
    ).fetchone()
    if not row:
        raise FileNotFoundError("未找到可用的本机快照")
    path = svc.folder / (row["id"] + ".akbak")
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError("本机密文不存在")
    return path, row


def prepare_export(svc, token, point, note=""):
    now = int(time.time())
    with closing(svc.store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        actor = require_owner(svc.store, db, token)
        _, row = point_source(svc, db, point)
        ticket = secrets.token_urlsafe(32)
        db.execute("DELETE FROM backup_exports WHERE expires<=?", (now,))
        db.execute(
            "INSERT INTO backup_exports VALUES(?,?,?,?,?)",
            (
                sha256(ticket.encode()).hexdigest(),
                actor["id"],
                sha256(token.encode()).hexdigest(),
                point,
                now + 180,
            ),
        )
        audit(
            db,
            svc.store,
            actor,
            "backup.export",
            "授权导出加密快照 " + point,
            comment(note),
        )
        return {
            "url": "/api/backups/download?ticket=" + ticket,
            "filename": point + ".akbak",
            "bytes": row["bytes"],
        }


def open_download(svc, token, ticket):
    with closing(svc.store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        actor = require_owner(svc.store, db, token)
        key = sha256(ticket.encode()).hexdigest()
        row = db.execute(
            "SELECT point FROM backup_exports WHERE ticket=? AND actor=? AND session=? AND expires>?",
            (key, actor["id"], sha256(token.encode()).hexdigest(), int(time.time())),
        ).fetchone()
        if not row:
            raise PermissionError("下载授权已失效，请重新导出")
        path, record = point_source(svc, db, row[0])
        db.execute("DELETE FROM backup_exports WHERE ticket=?", (key,))
    src = path.open("rb")
    try:
        digest = sha256()
        for chunk in iter(lambda: src.read(secure_storage.BLOCK), b""):
            digest.update(chunk)
        if digest.hexdigest() != record["digest"]:
            svc.mark_damaged(row[0])
            raise ValueError("快照密文校验失败")
        with closing(svc.store.connect()) as db:
            require_owner(svc.store, db, token)
        src.seek(0)
        return src, os.fstat(src.fileno()).st_size, path.name
    except BaseException:
        src.close()
        raise


@contextmanager
def restored(svc, packet):
    from ..store import Store, SCHEMA_VERSION

    with tempfile.TemporaryDirectory(prefix=".exchange-", dir=svc.folder) as tmp:
        path = Path(tmp) / "inspected.sqlite3"
        info = secure_storage.restore_snapshot(packet, path, svc.store.storage_key_file)
        if info["schemaVersion"] > SCHEMA_VERSION:
            raise ValueError("此备份由更高版本系统创建，请先升级")
        # Apply the same schema migrations as normal startup to the isolated database.
        Store(path, initial_data="empty")
        yield path


def preview_file(svc, token, stream, length):
    stage = uuid4().hex
    now = int(time.time())
    with closing(svc.store.connect()) as db:
        require_owner(svc.store, db, token)
        limit = policy(db)["uploadLimitMiB"] * 1024 * 1024
    if length is None or not 0 < length <= limit:
        raise ValueError("文件为空或超过当前导入上限")
    staging = svc.folder / ("import-" + stage + ".pending")
    with process_lock(svc.folder, "exchange", False) as locked:
        if not locked:
            raise ValueError("另一个备份导入正在处理，请稍后重试")
        try:
            with secure_storage.private_file(staging) as dest:
                digest = sha256()
                remaining = length
                while remaining:
                    chunk = stream.read(min(remaining, secure_storage.BLOCK))
                    if not chunk:
                        raise ValueError("没有收到完整备份")
                    if remaining == length and not chunk.startswith(
                        secure_storage.MAGIC
                    ):
                        raise ValueError("请选择安康 .akbak 加密备份")
                    dest.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
                dest.flush()
                os.fsync(dest.fileno())
            with restored(svc, staging) as path, closing(svc.store.connect()) as db, db:
                restore_plan.attach(db, path, svc.store)
                db.execute("BEGIN IMMEDIATE")
                actor = require_owner(svc.store, db, token)
                preview = restore_plan.describe(db)
                db.execute(
                    "INSERT INTO backup_imports(id,actor,created,digest,bytes,revision) VALUES(?,?,?,?,?,?)",
                    (
                        stage,
                        actor["id"],
                        now,
                        digest.hexdigest(),
                        length,
                        preview["sourceRevision"],
                    ),
                )
            return {
                **preview,
                "id": stage,
                "bytes": length,
                "expires": now + 1800,
                "digest": digest.hexdigest(),
            }
        except BaseException:
            staging.unlink(missing_ok=True)
            raise


def confirm_import(svc, token, stage, note=""):
    now = int(time.time())
    with (
        exclusive(svc.folder, "exchange"),
        closing(svc.store.connect()) as db,
        db,
    ):
        db.execute("BEGIN IMMEDIATE")
        actor = require_owner(svc.store, db, token)
        row = db.execute(
            "SELECT * FROM backup_imports WHERE id=? AND actor=?", (stage, actor["id"])
        ).fetchone()
        if not row or row["created"] + 1800 < now:
            raise ValueError("此导入预览已过期")
        if row["point"]:
            return {"point": row["point"]}
        history.watch(db, "backup.import")
        previous = db.execute(
            "SELECT id FROM backup_points WHERE digest=? AND state='ready' ORDER BY created DESC",
            (row["digest"],),
        ).fetchall()
        existing = next(
            (
                r[0]
                for r in previous
                if (svc.folder / (r[0] + ".akbak")).is_file()
                and cloud.hash_file(svc.folder / (r[0] + ".akbak")) == row["digest"]
            ),
            None,
        )
        pending = svc.folder / ("import-" + stage + ".pending")
        if not existing:
            if cloud.hash_file(pending) != row["digest"]:
                raise ValueError("暂存密文已变化，请重新选择备份")
            # A retry after a crash must adopt the same file identity.
            existing = (
                "ak-"
                + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(row["created"]))
                + "-"
                + stage
            )
            target = svc.folder / (existing + ".akbak")
            if target.exists():
                if cloud.hash_file(target) != row["digest"]:
                    raise ValueError("目标已被占用")
            else:
                os.link(pending, target)
                secure_storage.sync_dir(svc.folder)
            db.execute(
                """INSERT INTO backup_points(id,request,created,captured,state,owner,revision,bytes,digest)
             VALUES(?,?,?,?,'ready',?,?,?,?)""",
                (
                    existing,
                    "import:" + stage,
                    now,
                    now,
                    actor["id"],
                    row["revision"],
                    row["bytes"],
                    row["digest"],
                ),
            )
            enqueue_deliveries(db)
        db.execute("UPDATE backup_imports SET point=? WHERE id=?", (existing, stage))
        audit(
            db,
            svc.store,
            actor,
            "backup.import",
            "导入完整加密快照 " + existing,
            comment(note),
        )
    pending.unlink(missing_ok=True)
    return {"point": existing}


def approval(svc, token, point, revision, expires):
    subject = "|".join((token, point, str(revision), str(expires))).encode()
    return hmac.digest(
        secure_storage.derive(svc.store._storage_master, b"restore-confirmation"),
        subject,
        "sha256",
    ).hex()


def preview_point(svc, token, point):
    with closing(svc.store.connect()) as db:
        require_owner(svc.store, db, token)
        packet, record = point_source(svc, db, point)
    if cloud.hash_file(packet) != record["digest"]:
        raise ValueError("快照密文校验失败")
    with restored(svc, packet) as path, closing(svc.store.connect()) as db:
        restore_plan.attach(db, path, svc.store)
        db.execute("BEGIN")
        require_owner(svc.store, db, token)
        view = restore_plan.describe(db)
        expires = int(time.time()) + 600
        view["approval"] = {
            "expires": expires,
            "proof": approval(svc, token, point, view["currentRevision"], expires),
        }
        return view


def apply_point(svc, token, point, payload):
    from ..store import Conflict

    version = payload.get("revision")
    if type(version) is not int:
        raise ValueError("缺少预览时的业务修订")
    note = comment(payload.get("comment", ""))
    if payload.get("confirmed") is not True:
        raise ValueError("请确认应用此时间点")
    with closing(svc.store.connect()) as db:
        require_owner(svc.store, db, token)
        packet, record = point_source(svc, db, point)
        grant = payload.get("approval")
        if not isinstance(grant, dict):
            raise ValueError("请先打开本时间点核对恢复内容")
        expires = grant.get("expires")
        proof = grant.get("proof")
        if (
            type(expires) is not int
            or not 0 <= expires - int(time.time()) <= 600
            or not isinstance(proof, str)
            or not proof.isascii()
            or not hmac.compare_digest(
                proof, approval(svc, token, point, version, expires)
            )
        ):
            raise ValueError("恢复预览已失效，请重新核对")

    if cloud.hash_file(packet) != record["digest"]:
        raise ValueError("快照密文校验失败")
    with (
        exclusive(svc.folder, "capture"),
        restored(svc, packet) as path,
        closing(svc.store.connect()) as db,
        db,
    ):
        restore_plan.attach(db, path, svc.store)
        db.execute("BEGIN IMMEDIATE")
        actor = require_owner(svc.store, db, token)
        if (
            db.execute("SELECT revision FROM workspace WHERE id=1").fetchone()[0]
            != version
        ):
            raise Conflict("预览后机构资料已改变，请重新核对差异")
        view = restore_plan.describe(db)
        if view["blockers"]:
            raise ValueError(
                "当前工作库含受保护记录，无法覆盖：" + "、".join(view["blockers"])
            )
        if not view["changes"]:
            raise ValueError("当前可恢复业务内容与快照相同")
        now = int(time.time())
        recovery = identifier(now)
        protection = svc.folder / (recovery + ".akbak")
        # Publish and catalog the before-image in its own durable transaction before touching business rows.
        result = secure_storage.create_snapshot(svc.store, protection)
        if result["revision"] != version:
            raise Conflict("保护点修订与预览不一致")
        db.execute(
            """INSERT INTO backup_points(id,request,created,captured,state,owner,revision,bytes,digest)
            VALUES(?,?,?,?,'ready',?,?,?,?)""",
            (
                recovery,
                "protection:" + recovery,
                now,
                now,
                actor["id"],
                version,
                result["size"],
                result["sha256"],
            ),
        )
        enqueue_deliveries(db)
        db.commit()
        db.execute("BEGIN IMMEDIATE")
        actor = require_owner(svc.store, db, token)
        if (
            db.execute("SELECT revision FROM workspace WHERE id=1").fetchone()[0]
            != version
        ):
            raise Conflict("保护点已保存，机构资料随后有更新，请重新预览")
        # Other workers may update external delivery/recognition records without a business revision.
        view = restore_plan.describe(db)
        if view["blockers"]:
            raise Conflict("受保护数据已变化，请重新预览")
        history.watch(db, "backup.apply")
        restore_plan.apply(db)
        audit(
            db,
            svc.store,
            actor,
            "backup.apply",
            f"应用快照 {point}，恢复至来源修订 {view['sourceRevision']}；回退点 {recovery}",
            note,
        )
        new_revision = db.execute(
            "SELECT revision FROM workspace WHERE id=1"
        ).fetchone()[0]
        db.execute(
            "INSERT INTO backup_restores VALUES(?,?,?)", (new_revision, point, recovery)
        )
        return {"revision": new_revision, "rollbackPoint": recovery, "point": point}


def cleanup(svc, now):
    """Release expired previews and eligible local copies only after durable remote verification."""
    with process_lock(svc.folder, "exchange", False) as locked:
        if not locked:
            return
        with closing(svc.store.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            history.prune(db, svc.store.now())
            old = db.execute(
                "SELECT id FROM backup_imports WHERE created<?", (now - 1800,)
            ).fetchall()
            for item in old:
                (svc.folder / ("import-" + item[0] + ".pending")).unlink(
                    missing_ok=True
                )
            db.execute("DELETE FROM backup_imports WHERE created<?", (now - 1800,))
            db.execute("DELETE FROM backup_exports WHERE expires<=?", (now,))
            keep = policy(db)["retentionDays"]
            if keep:
                verified = usable_remotes(db)
                for sig in verified:
                    # Re-read the remote shortly before releasing its local source.
                    # Existing remote workers can re-upload a missing replica from this original.
                    db.execute(
                        """UPDATE backup_deliveries SET state='recheck',retry=0
                        WHERE signature=? AND state='verified' AND coalesce(verified,0)<?
                        AND point IN (SELECT id FROM backup_points WHERE state='ready' AND captured<?)""",
                        (sig, now - 86400, now - keep * DAY),
                    )
                    db.execute(
                        """UPDATE backup_points AS p SET state='retired' WHERE p.state='ready' AND max(p.captured,coalesce((SELECT retrieved FROM backup_retrievals r WHERE r.point=p.id),0))<?
                    AND EXISTS(SELECT 1 FROM backup_deliveries d WHERE d.point=p.id AND d.state='verified'
                        AND d.verified>=? AND d.signature=?)
                    AND EXISTS(SELECT 1 FROM backup_points n JOIN backup_deliveries q ON q.point=n.id
                       WHERE n.state='ready' AND n.captured>p.captured AND n.revision>=p.revision AND q.state='verified' AND q.signature=?)""",
                        (now - keep * DAY, now - DAY, sig, sig),
                    )
            retired = db.execute(
                "SELECT id FROM backup_points WHERE state='retired'"
            ).fetchall()
        for item in retired:
            (svc.folder / (item[0] + ".akbak")).unlink(missing_ok=True)
        # A killed upload may leave an unpublished ciphertext outside the catalog.
        for file in svc.folder.glob("import-*.pending"):
            if file.stat().st_mtime < now - 1800:
                file.unlink(missing_ok=True)


def usable_remotes(db):
    from . import signature

    remotes = cloud.locations()
    return [
        r["signature"]
        for r in db.execute("SELECT * FROM backup_locations")
        if r["provider"] in remotes
        and r["signature"] == signature(remotes[r["provider"]])
    ]


def fetch_replica(svc, token, point, provider, note=""):
    """Restore a missing local packet from an explicitly linked and verified remote."""
    from . import signature

    if provider not in cloud.PROVIDERS:
        raise ValueError("请选择异地副本位置")
    with exclusive(svc.folder, "exchange"):
        with closing(svc.store.connect()) as db:
            require_owner(svc.store, db, token)
            remote = cloud.locations().get(provider)
            if not remote:
                raise ValueError("请先配置并授权异地位置")
            fingerprint = signature(remote)

            def authorized(conn):
                return conn.execute(
                    """SELECT p.digest FROM backup_points p
                 JOIN backup_deliveries d ON d.point=p.id JOIN backup_locations l ON l.provider=d.provider AND l.signature=d.signature
                 WHERE p.id=? AND d.provider=? AND d.signature=? AND d.state='verified'""",
                    (point, provider, fingerprint),
                ).fetchone()

            source = authorized(db)
            if not source:
                raise ValueError("该位置没有已核验的备份")
            digest = source[0]
        with tempfile.TemporaryDirectory(dir=svc.folder) as temp:
            tmp = Path(temp) / "received.akbak"
            cloud.download(remote, cloud.object_name(point, digest), tmp)
            verified = svc.inspect_packet(tmp)
            with closing(svc.store.connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                actor = require_owner(svc.store, db, token)
                if not authorized(db) or cloud.locations().get(provider) != remote:
                    raise PermissionError("院方异地授权已变化")
                target = svc.folder / (point + ".akbak")
                if target.exists() and cloud.hash_file(target) != digest:
                    os.link(target, svc.folder / (point + ".damaged-" + uuid4().hex))
                history.watch(db, "backup.fetch")
                os.replace(tmp, target)
                secure_storage.sync_dir(svc.folder)
                db.execute(
                    "UPDATE backup_points SET state='ready',error='' WHERE id=?",
                    (point,),
                )
                db.execute(
                    "INSERT OR REPLACE INTO backup_checks VALUES(?,?)",
                    (point, int(time.time())),
                )
                # Restart the minimum local retention window when the administrator retrieves an old point.
                db.execute(
                    "INSERT OR REPLACE INTO backup_retrievals VALUES(?,?)",
                    (point, int(time.time())),
                )
                audit(
                    db,
                    svc.store,
                    actor,
                    "backup.fetch",
                    "从 " + cloud.PROVIDERS[provider] + " 取回并核验时间点 " + point,
                    comment(note),
                )
                return {"point": point, "revision": verified["revision"]}
