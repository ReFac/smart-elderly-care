"""Exercise the on-disk formats and recovery against actual SQLCipher files."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import manage_storage
from platform_core import secure_storage as vault, storage_assets
from platform_core.store import SignedOut, Store


class EncryptedStorageTests(unittest.TestCase):
    password = "local-fixture-owner-pass"
    marker = b"x-only-in-memory-of-test-for-sealed-vault-x"

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        config = patch.dict(
            os.environ, {"NH_STORAGE_KEY_FILE": "", "NH_OWNER_PASSWORD": self.password}
        )
        config.start()
        self.addCleanup(config.stop)
        self.path = self.root / "workspace.db"
        self.store = Store(self.path)
        self.key = self.store.storage_key_file

    def test_archive_and_tour_are_preserved_in_snapshot_and_sessions_revoked(self):
        art = self.root / "sourcedata"
        art.write_bytes(b"\x00" + self.marker * 150_000)
        jpeg = self.root / "original.jpg"
        jpeg.write_bytes(b"\xff\xd8\xff\xdb" + self.marker)
        token, _ = self.store.login("owner", self.password)
        with closing(self.store.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            result = storage_assets.import_asset(db, "archive", "legacy/dev.db", art)
            self.assertEqual(
                result, storage_assets.import_asset(db, "archive", "legacy/dev.db", art)
            )
            storage_assets.import_asset(db, "tour", "lobby.jpg", jpeg)
        with closing(self.store.connect()) as db:
            self.assertEqual(
                db.execute("SELECT count(*) FROM storage_assets").fetchone()[0], 2
            )
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM audit WHERE action='storage.import'"
                ).fetchone()[0],
                2,
            )
            with self.assertRaises(ValueError), db:
                storage_assets.import_asset(db, "archive", "legacy/dev.db", jpeg)
            for p in [
                self.path,
                Path(str(self.path) + "-wal"),
                Path(str(self.path) + "-shm"),
            ]:
                if p.exists():
                    self.assertNotIn(self.marker, p.read_bytes())
        with (
            closing(sqlite3.connect(self.path)) as db,
            self.assertRaises(sqlite3.DatabaseError),
        ):
            db.execute("SELECT * FROM workspace").fetchall()
        with self.assertRaises(FileNotFoundError):
            self.store.tour_media(token, "/tour-media/lobby.jpg")
        building = self.store.facility_resource(token, "directory")["buildings"][0][
            "id"
        ]
        self.store.execute(
            "facility.setScene",
            {
                "buildingId": building,
                "kind": "photo",
                "title": "测试大厅",
                "sortOrder": 1,
                "mediaUrl": "/tour-media/lobby.jpg",
            },
            self.store.version(token)["revision"],
            token,
        )
        self.assertEqual(
            self.store.tour_media(token, "/tour-media/lobby.jpg"),
            (jpeg.read_bytes(), "image/jpeg"),
        )
        archive = self.root / "point.akbak"
        info = vault.create_snapshot(self.store, archive)
        self.assertEqual(info["sha256"], sha256(archive.read_bytes()).hexdigest())
        self.assertNotIn(self.marker, archive.read_bytes())
        restored = self.root / "restored" / "workspace.db"
        self.assertEqual(
            vault.restore_snapshot(archive, restored, self.key)["revision"],
            info["revision"],
        )
        recovered = Store(restored)
        with self.assertRaises(SignedOut):
            recovered.version(token)
        restored_token, _ = recovered.login("owner", self.password)
        self.assertEqual(
            recovered.tour_media(restored_token, "/tour-media/lobby.jpg"),
            (jpeg.read_bytes(), "image/jpeg"),
        )
        with closing(recovered.connect()) as db:
            export = self.root / "returned"
            storage_assets.export_asset(db, "archive", "legacy/dev.db", export)
            self.assertEqual(art.read_bytes(), export.read_bytes())
            self.assertEqual(
                storage_assets.read_tour(db, "/tour-media/lobby.jpg"),
                (jpeg.read_bytes(), "image/jpeg"),
            )
        with self.assertRaises(FileExistsError):
            vault.restore_snapshot(archive, restored, self.key)
        with self.assertRaises(FileExistsError):
            vault.create_snapshot(self.store, archive)

    def test_recovery_starts_empty_backup_queue_and_requires_new_cloud_authority(self):
        with closing(self.store.connect()) as db, db:
            db.execute(
                "INSERT INTO backup_points(id,request,created,state) VALUES('p','t',0,'capturing')"
            )
            db.execute("INSERT INTO backup_checks VALUES('p',0)")
            db.execute("INSERT INTO backup_locations VALUES('icloud','sig',1)")
            db.execute(
                "INSERT INTO backup_deliveries(point,provider,signature,state) VALUES('p','icloud','sig','queued')"
            )
            db.execute(
                "INSERT INTO audit(revision,at,action,summary) VALUES(19,'sample','backup.request','audit survives')"
            )
        point = self.root / "transfer.akbak"
        vault.create_snapshot(self.store, point)
        target = self.root / "fresh.db"
        vault.restore_snapshot(point, target, self.key)
        with (
            closing(Store(target).connect()) as db,
            closing(self.store.connect()) as old,
        ):
            for table in (
                "backup_checks",
                "backup_deliveries",
                "backup_points",
                "backup_locations",
            ):
                self.assertEqual(
                    db.execute("SELECT count(*) FROM " + table).fetchone()[0], 0
                )
                self.assertEqual(
                    old.execute("SELECT count(*) FROM " + table).fetchone()[0], 1
                )
            self.assertEqual(
                db.execute("SELECT summary FROM audit WHERE revision=19").fetchone()[0],
                "audit survives",
            )

    def test_restore_tampering_truncation_wrong_and_missing_key(self):
        point = self.root / "point.akbak"
        vault.create_snapshot(self.store, point)
        new = self.root / "recover.db"
        wrong = self.root / "wrong"
        vault.install_key(wrong, os.urandom(32))
        with self.assertRaises(ValueError):
            vault.restore_snapshot(point, new, wrong)
        self.assertFalse(new.exists())
        with patch.dict(os.environ, {"NH_STORAGE_KEY_FILE": str(wrong)}):
            with self.assertRaises(vault.cipherdb.DatabaseError):
                Store(self.path)
        data = point.read_bytes()
        for damaged in [
            data[:-210],
            data[:800] + bytes([data[800] ^ 2]) + data[801:],
            data + b"extra",
        ]:
            point.write_bytes(damaged)
            with self.assertRaises(ValueError):
                vault.restore_snapshot(point, new, self.key)
            self.assertFalse(new.exists())
            self.assertFalse(vault.key_location(new).exists())
        self.key.write_bytes(wrong.read_bytes())
        with self.assertRaisesRegex(ValueError, "磁盘不一致"):
            vault.create_snapshot(self.store, self.root / "invalid.akbak")
        self.assertFalse((self.root / "invalid.akbak").exists())
        self.key.unlink()
        with self.assertRaisesRegex(ValueError, "缺少原数据库"):
            Store(self.path)
        self.assertFalse(self.key.exists())

    def test_snapshot_during_write_never_captures_half_of_a_transaction(self):
        with closing(self.store.connect()) as db, db:
            db.execute("CREATE TABLE sample_pair(k PRIMARY KEY,v)")
            db.executemany("INSERT INTO sample_pair VALUES(?,?)", [(1, 4), (2, 4)])
        pending, finish = Event(), Event()

        def edit():
            with closing(self.store.connect()) as db, db:
                db.execute("UPDATE sample_pair SET v=8 WHERE k=1")
                pending.set()
                self.assertTrue(finish.wait(10))
                db.execute("UPDATE sample_pair SET v=8 WHERE k=2")

        point = self.root / "concurrent.akbak"
        with ThreadPoolExecutor(1) as pool:
            task = pool.submit(edit)
            try:
                self.assertTrue(pending.wait(5))
                vault.create_snapshot(self.store, point)
            finally:
                finish.set()
            task.result(5)
        target = self.root / "recover.db"
        vault.restore_snapshot(point, target, self.key)
        with closing(Store(target).connect()) as db:
            self.assertEqual(
                [r[0] for r in db.execute("SELECT v FROM sample_pair")], [4, 4]
            )
        with closing(self.store.connect()) as db:
            self.assertEqual(
                [r[0] for r in db.execute("SELECT v FROM sample_pair")], [8, 8]
            )

    def test_continuous_wal_commits_do_not_restart_copy_or_move_snapshot_revision(self):
        connect = self.store.connect
        with closing(connect()) as db, db:
            db.execute("CREATE TABLE sample_pages(data BLOB NOT NULL)")
            db.executemany(
                "INSERT INTO sample_pages VALUES(zeroblob(3500))", [()] * 1400
            )
            initial_revision = db.execute("SELECT revision FROM workspace").fetchone()[
                0
            ]

        def write_page():
            with closing(connect()) as db, db:
                db.execute("INSERT INTO sample_pages VALUES(zeroblob(3500))")
                db.execute("UPDATE workspace SET revision=revision+1 WHERE id=1")

        remaining = []
        with ThreadPoolExecutor(1) as writer:

            def progress(status, left, count):
                remaining.append(left)
                # Interleave actual committed writes between initial backup steps.
                if left and len(remaining) <= 4:
                    writer.submit(write_page).result(5)

            with closing(connect()) as source:
                traced = Mock(wraps=source)
                traced.backup.side_effect = lambda target, **opts: source.backup(
                    target, progress=progress, **opts
                )
                with patch.object(self.store, "connect", return_value=traced):
                    point = self.root / "busy.akbak"
                    info = vault.create_snapshot(self.store, point)

        self.assertGreater(len(remaining), 4)
        self.assertTrue(
            all(new < old for old, new in zip(remaining, remaining[1:])), remaining
        )
        self.assertEqual(info["revision"], initial_revision)
        target = self.root / "busy-restored.db"
        vault.restore_snapshot(point, target, self.key)
        with closing(Store(target).connect()) as recovered, closing(connect()) as live:
            self.assertEqual(
                recovered.execute("SELECT count(*) FROM sample_pages").fetchone()[0],
                1400,
            )
            self.assertEqual(
                live.execute("SELECT count(*) FROM sample_pages").fetchone()[0], 1404
            )
            self.assertEqual(
                live.execute("SELECT revision FROM workspace").fetchone()[0],
                initial_revision + 4,
            )

    def test_old_db_bootstrap_verified_and_memory_hard_wrapped_key_roundtrip(self):
        legacy = self.root / "old.db"
        with closing(sqlite3.connect(legacy)) as db, db:
            db.execute(
                "CREATE TABLE workspace(id INTEGER PRIMARY KEY,revision INTEGER,data TEXT)"
            )
            db.execute("INSERT INTO workspace VALUES(1,19,'{}')")
            db.execute("PRAGMA user_version=3")
        with self.assertRaisesRegex(ValueError, "停机"):
            Store(legacy)
        self.assertEqual(
            vault.migrate_database(legacy), {"revision": 19, "schemaVersion": 3}
        )
        self.assertNotEqual(legacy.read_bytes()[:16], vault.SQLITE_HEADER)
        legacy_key = vault.key_location(legacy)
        master = vault.read_key(legacy_key)
        old_store = SimpleNamespace(
            storage_key_file=legacy_key,
            _storage_master=master,
            connect=lambda: vault.open_database(legacy, master),
        )
        point = self.root / "legacy.akbak"
        vault.create_snapshot(old_store, point)
        self.assertEqual(
            vault.restore_snapshot(point, self.root / "old-restored.db", legacy_key),
            {"revision": 19, "schemaVersion": 3},
        )
        old = self.root / ".owner-password"
        with vault.private_file(old) as f:
            f.write(self.password.encode())
        with closing(self.store.connect()) as db:
            self.assertEqual(
                manage_storage.seal_legacy_bootstrap(db, self.path), "sealed"
            )
            self.assertFalse(old.exists())
            self.assertEqual(
                db.execute("SELECT password FROM storage_bootstrap").fetchone()[0],
                self.password,
            )
        wrapped, recovered = self.root / "key.akkey", self.root / "recovered-key"
        vault.wrap_recovery_key(self.key, wrapped, "test-only-offline-password")
        self.assertNotIn(self.key.read_bytes(), wrapped.read_bytes())
        with self.assertRaisesRegex(ValueError, "认证"):
            vault.unwrap_recovery_key(wrapped, recovered, "test-only-wrong-password")
        self.assertFalse(recovered.exists())
        vault.unwrap_recovery_key(wrapped, recovered, "test-only-offline-password")
        self.assertEqual(vault.read_key(recovered), vault.read_key(self.key))
        self.assertEqual(recovered.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            vault.unwrap_recovery_key(wrapped, recovered, "test-only-offline-password")
        recovered.chmod(0o644)
        with self.assertRaises(ValueError):
            vault.read_key(recovered)
