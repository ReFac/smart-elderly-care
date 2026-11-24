"""Check cloud-assisted duplicate preview and explicit, idempotent stock merging."""

from contextlib import closing
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from platform_core import inventory_dedupe, provider
from platform_core.operations import resources
from platform_core.store import Store


class InventoryDedupeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.now = datetime(2026, 11, 25, 10, tzinfo=provider.ZONE)
        self.store = Store(
            Path(folder.name) / "stock.sqlite",
            now=lambda: self.now,
            initial_data="empty",
            initial_owner_password="inventory-fixture-only",
        )
        self.token, self.owner = self.store.login("owner", "inventory-fixture-only")

    @property
    def day(self):
        return self.now.date().isoformat()

    def draft(self, **fields):
        return dict(
            name="医用检查手套",
            unit="盒",
            brand="演示品牌",
            specification="50 副/盒",
            minimum=2,
            **fields,
        )

    def add(self, values):
        self.store.execute(
            "ops.addItem",
            values,
            self.store.version(self.token)["revision"],
            self.token,
        )
        return self.store.snapshot(self.token)["data"]["inventory"][-1]["id"]

    def catalog(self):
        return self.store.snapshot(self.token)["data"]

    def merge(self, values, match, user=None):
        payload = {**values, "itemId": match["id"], "matchToken": match["matchToken"]}
        if user is None:
            return self.store.execute(
                "ops.mergeStockItem",
                payload,
                self.store.version(self.token)["revision"],
                self.token,
            )["summary"]
        with closing(self.store.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            state = json.loads(db.execute("SELECT data FROM workspace").fetchone()[0])
            note = inventory_dedupe.merge(
                self.store,
                state,
                user,
                payload,
                self.day,
            )
            db.execute(
                "UPDATE workspace SET data=?", (json.dumps(state, ensure_ascii=False),)
            )
            return note

    def cloud_reply(self, *_args, **_kwargs):
        return {
            "usage": {
                "total_tokens": 40,
                "prompt_tokens": 30,
                "completion_tokens": 10,
                "prompt_cache_hit_tokens": 8,
                "prompt_cache_miss_tokens": 22,
            },
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(
                            {
                                "matches": [
                                    {"candidate": 1, "relation": "equivalent"},
                                    {"candidate": 2, "relation": "equivalent"},
                                ]
                            }
                        )
                    },
                }
            ],
        }

    def test_preview_cloud_suggestions_never_merge_incompatible_stock(self):
        own_id = self.add(self.draft())
        different = self.add({**self.draft(), "unit": "箱", "specification": "5 盒/箱"})
        draft = {**self.draft(), "name": "医用一次性检查手套", "openingQuantity": 3}
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "物资查重测试", 100_000, "2026-12-01", now=self.now)
        with (
            patch.object(provider, "read_key", return_value="fixture"),
            patch.object(
                provider.deepseek, "send", side_effect=self.cloud_reply
            ) as cloud,
        ):
            report = inventory_dedupe.preview(self.store, self.token, draft)
        self.assertEqual(report["source"], "deepseek")
        cloud.assert_called_once()
        matches = {row["id"]: row for row in report["matches"]}
        self.assertIn("matchToken", matches[own_id])
        self.assertNotIn("matchToken", matches[different])
        self.assertEqual(matches[different]["blockedReason"], "库存计量单位不同")
        self.assertEqual(self.catalog()["transactions"], [])
        with closing(self.store.connect()) as db:
            usage = db.execute(
                "SELECT feature,cachedInputTokens FROM api_usage"
            ).fetchone()
            self.assertEqual(tuple(usage), ("inventory.similarity", 8))

    def test_merge_adds_one_stock_receipt_and_preserves_original_balance_rules(self):
        target = self.add({**self.draft(), "openingQuantity": 4})
        draft = {
            **self.draft(),
            "name": "医用一次性检查手套",
            "openingQuantity": 3,
            "minimum": 1,
        }
        match = inventory_dedupe.preview(self.store, self.token, draft)["matches"][0]
        self.merge(draft, match)
        self.merge(draft, match)
        data = self.catalog()
        self.assertEqual(len(data["inventory"]), 1)
        item = data["inventory"][0]
        self.assertEqual(
            (item["id"], item["quantity"], item["minimum"], item["aliases"]),
            (target, 7, 2, ["医用一次性检查手套"]),
        )
        self.assertEqual(
            [(row["itemId"], row["quantity"]) for row in data["transactions"]],
            [(target, 3), (target, 4)],
        )

    def test_merge_receipt_cannot_be_reused_for_other_values_or_after_expiry(self):
        self.add(self.draft())
        draft = {**self.draft(), "name": "医用一次性检查手套", "openingQuantity": 3}
        match = inventory_dedupe.preview(self.store, self.token, draft)["matches"][0]
        with self.assertRaises(ValueError):
            self.merge({**draft, "openingQuantity": 100}, match)
        with self.assertRaises(ValueError):
            self.merge(draft, match, {**self.owner, "id": "another-account"})
        self.now += timedelta(hours=2)
        with self.assertRaises(ValueError):
            self.merge(draft, match)
        self.assertEqual(self.catalog()["transactions"], [])

    def test_edit_merges_no_existing_ledgers_and_inventory_authorization_applies(self):
        target = self.add(self.draft())
        another = self.add({**self.draft(), "specification": "20 副/盒"})
        data = self.catalog()
        with self.assertRaises(ValueError):
            resources.edit_item(
                data,
                {"itemId": target, "brand": "演示品牌", "specification": "20 副/盒"},
                self.day,
            )
        resources.edit_item(
            data, {"itemId": target, "brand": "", "specification": "50 副/盒"}, self.day
        )
        self.assertEqual([row["id"] for row in data["inventory"]], [target, another])
        self.assertEqual(data["inventory"][0]["brand"], "")
        self.store.execute(
            "access.create",
            {
                "username": "care-no-stock",
                "displayName": "照护员工",
                "password": "care-no-stock-pass",
                "kind": "staff",
                "role": "护工",
            },
            self.store.version(self.token)["revision"],
            self.token,
        )
        staff, _ = self.store.login("care-no-stock", "care-no-stock-pass")
        with self.assertRaises(PermissionError):
            inventory_dedupe.preview(self.store, staff, self.draft())
