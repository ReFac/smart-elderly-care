from contextlib import closing
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from platform_core import backups, secure_storage
from platform_core.agents import change_review
from platform_core.store import Store, TIMEZONE


class ChargesAndCompressionTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": "only-in-test-fixture"}):
            self.store = Store(
                self.root / "source.sqlite3",
                lambda: datetime(2026, 11, 24, 10, 0, tzinfo=TIMEZONE),
            )
        self.token, _ = self.store.login("owner", "only-in-test-fixture")

    def test_itemized_quote_saved_and_locally_reviewed(self):
        state = self.store.snapshot(self.token)["data"]
        rid = next(
            r["id"]
            for r in state["residents"]
            if r["status"] == "在住"
            and not any(
                b["residentId"] == r["id"] and b["month"] == "2026-11"
                for b in state["bills"]
            )
        )
        payload = {
            "residentId": rid,
            "month": "2026-11",
            "items": [
                {
                    "code": "meal",
                    "basis": "presentDays",
                    "unit": "天",
                    "unitPrice": "18.50",
                },
                {"code": "supplies", "unit": "件", "quantity": 3, "unitPrice": "3.10"},
                {"code": "reduction", "unit": "次", "quantity": 1, "unitPrice": "2"},
            ],
        }
        rev = self.store.version(self.token)["revision"]
        quote = self.store.bill_preview(self.token, payload, rev)
        self.assertEqual(
            quote["amount"],
            float(sum(Decimal(str(i["amount"])) for i in quote["lineItems"])),
        )
        meal, supplies, discount = quote["lineItems"][-3:]
        self.assertEqual(meal["quantity"], quote["serviceDays"] - quote["leaveDays"])
        self.assertEqual((supplies["amount"], discount["amount"]), (9.3, -2.0))
        self.assertEqual(rev, self.store.version(self.token)["revision"])
        saved = self.store.execute("ops.bill", payload, rev, self.token)
        detail = self.store.history_change(self.token, saved["revision"])
        self.assertEqual(detail["agentReview"]["domain"], "费用核算")
        bill = self.store.snapshot(self.token)["data"]["bills"][0]
        self.assertEqual(bill["lineItems"], quote["lineItems"])
        with closing(self.store.connect()) as db:
            db.execute("BEGIN")
            db.execute(
                """UPDATE workspace SET data=json_set(data,'$.bills[0].amount',0)"""
            )
            with self.assertRaisesRegex(ValueError, "不一致"):
                change_review.inspect(db, 999, "ops.bill", {"kind": "owner"}, rid)
            db.rollback()

        with closing(self.store.connect()) as db:
            db.execute("BEGIN")
            db.execute(
                "UPDATE workspace SET data=json_set(data,'$.bills[0].lineItems[0].quantity',12345)"
            )
            with self.assertRaisesRegex(ValueError, "不一致"):
                change_review.inspect(db, 999, "ops.bill", {"kind": "owner"}, rid)
            db.rollback()
        paid = self.store.execute(
            "ops.pay",
            {"billId": bill["id"], "amount": 1},
            saved["revision"],
            self.token,
        )
        self.assertEqual(
            self.store.history_change(self.token, paid["revision"])["agentReview"][
                "domain"
            ],
            "收款核销",
        )

    def test_daily_slot_compresses_roundtrips_and_still_reads_v1(self):
        with closing(self.store.connect()) as db, db:
            data = json.loads(db.execute("SELECT data FROM workspace").fetchone()[0])
            data["exercise"] = "合成可压缩资料" * 200000
            db.execute(
                "UPDATE workspace SET data=?", (json.dumps(data, ensure_ascii=False),)
            )
        packet = self.root / "compressed.akbak"
        info = secure_storage.create_snapshot(self.store, packet)
        self.assertEqual(backups.PERIOD, 86400)
        self.assertLess(info["size"], info["sourceBytes"] // 2)
        self.assertNotIn("合成可压缩资料".encode(), packet.read_bytes())
        master = self.store._storage_master

        def verify(path, target):
            destination = self.root / target
            secure_storage.restore_snapshot(
                path, destination, self.store.storage_key_file
            )
            with closing(secure_storage.open_database(destination, master)) as db:
                self.assertEqual(
                    json.loads(db.execute("SELECT data FROM workspace").fetchone()[0])[
                        "exercise"
                    ],
                    data["exercise"],
                )

        verify(packet, "roundtrip.sqlite")
        old = self.root / "old.sqlite"
        with (
            closing(self.store.connect()) as src,
            closing(secure_storage.open_database(old, master, new=True)) as dest,
        ):
            src.backup(dest)
            dest.execute("PRAGMA journal_mode=DELETE")
        salt, nonce = b"0" * 32, b"1" * 12
        header = secure_storage.LEGACY_MAGIC + salt + nonce
        packet = self.root / "old.akbak"
        packet.write_bytes(
            header
            + AESGCM(secure_storage.derive(master, b"snapshot/" + salt)).encrypt(
                nonce, old.read_bytes(), header
            )
        )
        verify(packet, "legacy-roundtrip.sqlite")
