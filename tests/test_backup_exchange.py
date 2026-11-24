"""End-to-end tests for encrypted exchanges, protected restoration and retention."""

from contextlib import closing
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

from platform_core import secure_storage
from platform_core.backups import exchange
from platform_core.store import Store, Conflict


class ExchangeTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.key = "synthetic-operator-password"
        env = patch.dict(
            "os.environ",
            {
                "NH_OWNER_PASSWORD": self.key,
                "NH_BACKUP_LOCATIONS_FILE": str(self.root / "profiles.json"),
            },
        )
        env.start()
        self.addCleanup(env.stop)
        (self.root / "profiles.json").write_text('{"icloud":"icloud:backup"}')
        self.store = Store(self.root / "office.sqlite3")
        self.t = self.store.login("owner", self.key)[0]
        self.s = self.store.backups
        self.s.capture()
        self.id = self.s.status(self.t)["points"][0]["id"]
        self.packet = (self.s.folder / (self.id + ".akbak")).read_bytes()

    def issue(self, point):
        view = exchange.preview_point(self.s, self.t, point)
        return {
            **{
                "confirmed": True,
                "approval": view["approval"],
                "revision": view["currentRevision"],
            },
            "comment": "已核对业务差异",
        }

    def inquire(self, txt):
        self.store.execute(
            "care.inquire",
            {"name": txt},
            self.store.version(self.t)["revision"],
            self.t,
        )

    def test_stream_import_is_authenticated_scoped_and_idempotent(self):
        self.inquire("快照演练对象甲")
        temp = self.root / "operator.akbak"
        result = secure_storage.create_snapshot(self.store, temp)
        packet = temp.read_bytes()
        with self.assertRaises(ValueError):
            exchange.preview_file(
                self.s,
                self.t,
                BytesIO(packet[:-1] + bytes([packet[-1] ^ 2])),
                len(packet),
            )
        self.assertEqual([], list(self.s.folder.glob("*.pending")))
        with self.assertRaises(ValueError):
            exchange.preview_file(self.s, self.t, BytesIO(packet[:128]), len(packet))
        plan = exchange.preview_file(self.s, self.t, BytesIO(packet), len(packet))
        receipt = exchange.confirm_import(self.s, self.t, plan["id"], "加密演练")
        self.assertEqual(receipt, exchange.confirm_import(self.s, self.t, plan["id"]))
        row = self.s.status(self.t)["points"][0]
        self.assertEqual(row["kind"], "import")
        self.assertEqual(result["revision"], row["revision"])
        exported = exchange.prepare_export(
            self.s, self.t, receipt["point"], "另存加密包"
        )
        ticket = parse_qs(urlsplit(exported["url"]).query)["ticket"][0]
        different = self.store.login("owner", self.key)[0]
        with self.assertRaises(PermissionError):
            exchange.open_download(self.s, different, ticket)
        handle, size, name = exchange.open_download(self.s, self.t, ticket)
        with handle:
            self.assertEqual(handle.read(), packet)
        self.assertEqual(size, len(packet))
        self.assertTrue(name.endswith(".akbak"))
        with self.assertRaises(PermissionError):
            exchange.open_download(self.s, self.t, ticket)
        self.assertEqual([], list(self.s.folder.glob(".exchange-*")))

    def test_apply_and_rollback_preserve_audit_identity_and_monotonic_versions(self):
        self.inquire("快照回退对象乙")
        with closing(self.store.connect()) as db:
            prior = db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
            history = list(
                map(tuple, db.execute("SELECT * FROM audit ORDER BY revision"))
            )
            grants = list(
                map(
                    tuple,
                    db.execute("SELECT id,role,enabled,password_hash FROM accounts"),
                )
            )
        args = self.issue(self.id)
        with self.assertRaises(ValueError):
            exchange.apply_point(self.s, self.t, self.id, {**args, "approval": {}})
        restored = exchange.apply_point(self.s, self.t, self.id, args)
        self.assertEqual(args["revision"] + 1, restored["revision"])
        with closing(self.store.connect()) as db:
            self.assertNotIn(
                "快照回退对象乙", db.execute("SELECT data FROM workspace").fetchone()[0]
            )
            all_audit = list(
                map(tuple, db.execute("SELECT * FROM audit ORDER BY revision"))
            )
            self.assertEqual(all_audit[:-1], history)
            self.assertEqual("backup.apply", all_audit[-1][2])
            self.assertEqual(
                grants,
                list(
                    map(
                        tuple,
                        db.execute(
                            "SELECT id,role,enabled,password_hash FROM accounts"
                        ),
                    )
                ),
            )
            self.assertEqual(
                restored["rollbackPoint"],
                db.execute(
                    "SELECT rollbackPoint FROM backup_restores WHERE revision=?",
                    (restored["revision"],),
                ).fetchone()[0],
            )
        with self.assertRaises(Conflict):
            exchange.apply_point(self.s, self.t, self.id, args)
        rollback = restored["rollbackPoint"]
        undone = exchange.apply_point(self.s, self.t, rollback, self.issue(rollback))
        self.assertEqual(undone["revision"], restored["revision"] + 1)
        with closing(self.store.connect()) as db:
            self.assertEqual(
                prior, db.execute("SELECT data FROM workspace").fetchone()[0]
            )

    def test_new_payments_cannot_be_erased_and_check_occurs_after_preview(self):
        self.inquire("被并发更新的咨询")
        args = self.issue(self.id)
        self.inquire("另一个经办人提交")
        with self.assertRaises(Conflict):
            exchange.apply_point(self.s, self.t, self.id, args)
        args = self.issue(self.id)
        with closing(self.store.connect()) as db, db:
            # Simulate a channel's delayed callback between preview and execution.
            obj = json.loads(db.execute("SELECT data FROM workspace").fetchone()[0])
            obj["channelReceipts"].append({"id": "fixture-paid", "amount": 123})
            db.execute("UPDATE workspace SET data=?", (json.dumps(obj),))
        with self.assertRaisesRegex(ValueError, "渠道回执"):
            exchange.apply_point(self.s, self.t, self.id, args)
        self.assertIn(
            "渠道回执", exchange.preview_point(self.s, self.t, self.id)["blockers"]
        )

    def test_foreign_institution_rejected_even_if_deployment_keys_were_reused(self):
        key = self.store.storage_key_file
        with patch.dict("os.environ", {"NH_STORAGE_KEY_FILE": str(key)}):
            other = Store(self.root / "other.sqlite3")
            packet = self.root / "other.akbak"
            secure_storage.create_snapshot(other, packet)
            with packet.open("rb") as f, self.assertRaisesRegex(ValueError, "所属机构"):
                exchange.preview_file(self.s, self.t, f, packet.stat().st_size)

    def test_owner_only_policy_and_retention_safety(self):
        self.store.execute(
            "access.create",
            {
                "kind": "staff",
                "role": "院长",
                "username": "care-staff",
                "displayName": "测试职员",
                "password": self.key,
            },
            self.store.version(self.t)["revision"],
            self.t,
        )
        staff = self.store.login("care-staff", self.key)[0]
        payload = {"retentionDays": 60, "uploadLimitMiB": 64, "version": 0}
        for fn, args in [
            (exchange.change_policy, (payload,)),
            (exchange.preview_file, (BytesIO(self.packet), len(self.packet))),
            (exchange.prepare_export, (self.id,)),
            (exchange.preview_point, (self.id,)),
            (exchange.confirm_import, ("abc",)),
            (exchange.unlink, ("icloud",)),
        ]:
            with self.subTest(fn=fn.__name__), self.assertRaises(PermissionError):
                fn(self.s, staff, *args)
        self.assertEqual(
            60, exchange.change_policy(self.s, self.t, payload)["retentionDays"]
        )
        with self.assertRaises(Conflict):
            exchange.change_policy(self.s, self.t, payload)
        old = int(time.time()) - 61 * exchange.DAY
        with closing(self.store.connect()) as db, db:
            db.execute("UPDATE backup_points SET captured=? WHERE id=?", (old, self.id))
        exchange.cleanup(self.s, int(time.time()))
        first = self.s.folder / (self.id + ".akbak")
        self.assertTrue(first.exists())
        self.s.link(self.t, "icloud")
        self.s.request(self.t, "manual-copy-after-archiving")
        self.s.capture()
        with closing(self.store.connect()) as db, db:
            db.execute(
                "UPDATE backup_deliveries SET state='verified',verified=?",
                (int(time.time()),),
            )
        exchange.cleanup(self.s, int(time.time()))
        self.assertFalse(first.exists())
        self.assertTrue(list(self.s.folder.glob("*.akbak")))
        self.assertEqual(
            "retired",
            next(
                p["state"]
                for p in self.s.status(self.t)["points"]
                if p["id"] == self.id
            ),
        )
        exchange.unlink(self.s, self.t, "icloud")
        self.assertNotEqual("linked", self.s.status(self.t)["locations"][0]["state"])

    def test_immutable_archive_blocks_replacement_and_archives_after_import_survive(
        self,
    ):
        asset = self.root / "historical.bin"
        asset.write_bytes(b"original retention fixture")
        from platform_core import storage_assets

        with closing(self.store.connect()) as db, db:
            storage_assets.import_asset(db, "archive", "original", asset)
        before = self.s.status(self.t)["points"]
        view = exchange.preview_point(self.s, self.t, self.id)
        self.assertIn("环境与历史原件", view["blockers"])
        with self.assertRaisesRegex(ValueError, "受保护"):
            exchange.apply_point(
                self.s, self.t, self.id, {**self.issue(self.id), "comment": "保留原件"}
            )
        self.assertEqual(before, self.s.status(self.t)["points"])
        with closing(self.store.connect()) as db:
            self.assertEqual(
                b"original retention fixture",
                db.execute(
                    "SELECT data FROM storage_assets WHERE name='original'"
                ).fetchone()[0],
            )

    def test_fetch_verified_remote_keeps_packet_and_restores_local_retention(self):
        from platform_core.backups import cloud

        self.s.link(self.t, "icloud")
        file = self.s.folder / (self.id + ".akbak")
        orig = file.read_bytes()
        with closing(self.store.connect()) as db, db:
            db.execute(
                "UPDATE backup_deliveries SET state='verified',verified=?",
                (int(time.time()),),
            )
            db.execute(
                "UPDATE backup_points SET state='retired' WHERE id=?", (self.id,)
            )
        file.unlink()

        def receive(remote, name, destination):
            self.assertEqual("icloud:backup", remote)
            destination.write_bytes(orig)

        with patch.object(cloud, "download", side_effect=receive):
            result = exchange.fetch_replica(
                self.s, self.t, self.id, "icloud", "模拟远端"
            )
        self.assertEqual(0, result["revision"])
        self.assertEqual(orig, file.read_bytes())
        self.assertEqual("ready", self.s.status(self.t)["points"][0]["state"])
