"""Recoverable half-day snapshots, authorization and independent delivery queues."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch
from platform_core import backups, secure_storage
from platform_core.backups import cloud
from platform_core.store import Store


class Backups(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.path = self.base / "pilot.sqlite3"
        self.profiles = self.base / "remotes.json"
        self.profiles.write_text(
            json.dumps({"icloud": "apple:copies", "115": "webdav:copies"})
        )
        env = patch.dict(
            "os.environ",
            {
                "NH_OWNER_PASSWORD": "local-backup-tests",
                "NH_BACKUP_LOCATIONS_FILE": str(self.profiles),
            },
        )
        env.start()
        self.addCleanup(env.stop)
        self.store = Store(self.path)
        self.owner, _ = self.store.login("owner", "local-backup-tests")
        self.svc = self.store.backups
        self.t = backups.slot_for(1780000000)

    def points(self):
        return self.svc.status(self.owner)["points"]

    def test_concurrent_capture_in_a_slot_and_next_boundary(self):
        second = Store(self.path).backups
        gate = Barrier(2)

        def tick(service):
            gate.wait()
            return service.capture(self.t)

        with ThreadPoolExecutor(2) as pool:
            self.assertCountEqual(pool.map(tick, [second, self.svc]), [True, False])
        self.assertFalse(self.svc.capture(self.t + backups.PERIOD - 1))
        self.assertTrue(self.svc.capture(self.t + backups.PERIOD))
        self.assertEqual(len(self.points()), 2)
        self.assertTrue(all(p["state"] == "ready" for p in self.points()))

    def test_manual_idempotency_and_verified_isolated_recovery(self):
        self.svc.capture(self.t)
        self.store.execute(
            "care.inquire",
            {"name": "合成恢复测试"},
            self.store.version(self.owner)["revision"],
            self.owner,
        )
        result = self.svc.request(self.owner, "manual-verification-1")
        self.svc.capture(self.t)
        self.assertEqual(result, self.svc.request(self.owner, "manual-verification-1"))
        self.assertTrue(self.svc.verify(self.owner, result["id"])["verified"])
        row = next(p for p in self.points() if p["id"] == result["id"])
        self.assertIsNotNone(row["checked"])
        file = self.svc.folder / (row["id"] + ".akbak")
        data = file.read_bytes()
        self.assertTrue(data.startswith(secure_storage.MAGIC))
        self.assertNotIn("合成恢复测试".encode(), data)
        restored = self.base / "cold" / "restored.db"
        secure_storage.restore_snapshot(file, restored, self.store.storage_key_file)
        with closing(Store(restored).connect()) as db:
            self.assertIn(
                "合成恢复测试", db.execute("select data from workspace").fetchone()[0]
            )
            self.assertEqual(
                0, db.execute("select count(*) from sessions").fetchone()[0]
            )
        file.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
        with self.assertRaises(ValueError):
            self.svc.verify(self.owner, row["id"])

    def test_restore_missing_current_point_keeps_old_identity_and_history(self):
        self.svc.capture(self.t)
        original = self.points()[0]["id"]
        (self.svc.folder / (original + ".akbak")).unlink()
        self.assertEqual("missing", self.points()[0]["state"])
        self.svc.capture(self.t + 500)
        rows = {p["id"]: p["state"] for p in self.points()}
        self.assertEqual("missing", rows.pop(original))
        self.assertEqual(["ready"], list(rows.values()))
        self.assertFalse(self.svc.capture(self.t + 501))

    def test_recover_published_packet_without_changing_its_bytes_or_revision(self):
        self.svc.capture(self.t)
        original = self.points()[0]
        packet = self.svc.folder / (original["id"] + ".akbak")
        digest = cloud.hash_file(packet)
        with closing(self.store.connect()) as db, db:
            db.execute(
                "UPDATE backup_points SET state='creating',revision=NULL,digest=NULL"
            )
        self.store.execute(
            "care.inquire",
            {"name": "晚于时间点的记录"},
            self.store.version(self.owner)["revision"],
            self.owner,
        )
        self.assertTrue(self.svc.capture(self.t + 100))
        self.assertEqual(original["revision"], self.points()[0]["revision"])
        self.assertEqual(digest, cloud.hash_file(packet))
        packet.write_bytes(b"damaged")
        with self.assertRaises(ValueError):
            self.svc.verify(self.owner, original["id"])
        self.assertTrue(self.svc.capture(self.t + 120))
        self.assertCountEqual(["damaged", "ready"], [r["state"] for r in self.points()])
        self.assertEqual(b"damaged", packet.read_bytes())

    def test_locations_fail_independently_and_restart_recovers_inflight_upload(self):
        for provider in ["icloud", "115"]:
            self.svc.link(self.owner, provider)
        self.svc.capture(self.t)

        def receive(path, remote, name):
            self.assertTrue(path.read_bytes().startswith(secure_storage.MAGIC))
            self.assertTrue(cloud.OBJECT.fullmatch(name))
            if remote == "apple:copies":
                raise cloud.TransferError("模拟云端不可用")

        with patch.object(cloud, "upload", side_effect=receive):
            self.assertTrue(self.svc.deliver("icloud", self.t))
            self.assertFalse(self.svc.deliver("icloud", self.t + 1))
            self.assertTrue(self.svc.deliver("115", self.t))
        self.assertEqual(
            {"icloud": "failed", "115": "verified"},
            {r["provider"]: r["state"] for r in self.points()[0]["copies"]},
        )
        with closing(self.store.connect()) as db, db:
            db.execute(
                "UPDATE backup_deliveries SET state='sending',retry=? WHERE provider='icloud'",
                (self.t + 7200,),
            )
        with patch.object(cloud, "upload") as transfer:
            self.assertTrue(Store(self.path).backups.deliver("icloud", self.t + 2))
            transfer.assert_called_once()
        self.assertTrue(
            all(r["state"] == "verified" for r in self.points()[0]["copies"])
        )
        self.profiles.write_text(json.dumps({"icloud": "replacement:folder"}))
        self.assertFalse(self.svc.deliver("icloud", self.t + 3))
        self.assertEqual(
            "changed", self.svc.status(self.owner)["locations"][0]["state"]
        )

    def test_only_owner_can_use_any_backup_action(self):
        self.store.execute(
            "access.create",
            {
                "kind": "staff",
                "role": "院长",
                "username": "branch-director",
                "displayName": "备份权限测试",
                "password": "local-backup-tests",
            },
            self.store.version(self.owner)["revision"],
            self.owner,
        )
        token, _ = self.store.login("branch-director", "local-backup-tests")
        self.svc.capture(self.t)
        id = self.points()[0]["id"]
        for fn, args in [
            (self.svc.status, ()),
            (self.svc.request, ("long-request-test",)),
            (self.svc.verify, (id,)),
            (self.svc.retry, ()),
            (self.svc.link, ("115",)),
        ]:
            with self.subTest(fn=fn.__name__), self.assertRaises(PermissionError):
                fn(token, *args)

    def test_invalid_remote_and_upload_of_cleartext_are_refused(self):
        for remotes in [
            {"115": "r:../private"},
            {"unknown": "r:valid"},
            {"115": "r:x", "icloud": "r:x"},
        ]:
            self.profiles.write_text(json.dumps(remotes))
            with self.assertRaises(cloud.TransferError):
                cloud.locations()
        path = self.base / "cleartext"
        path.write_bytes(b"example")
        with (
            patch.object(cloud, "run") as transfer,
            self.assertRaises(cloud.TransferError),
        ):
            cloud.upload(
                path,
                "r:folder",
                cloud.object_name(backups.identifier(self.t), cloud.hash_file(path)),
            )
        transfer.assert_not_called()
