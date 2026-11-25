"""Report provider cache counters without altering the charged total or replaying work."""

from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from platform_core import provider
from platform_core.agents import chat
from platform_core.provider import deepseek, generation, token_receipt
from platform_core.store import Store


def response(message="收到", **fields):
    return {
        "choices": [{"finish_reason": "stop", "message": {"content": message}}],
        "usage": {
            "total_tokens": 111,
            "prompt_tokens": 100,
            "prompt_cache_hit_tokens": 60,
            "prompt_cache_miss_tokens": 40,
            "completion_tokens": 11,
            **fields,
        },
    }


class TokenReceiptTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(
            Path(folder.name) / "meter.db",
            initial_owner_password="offline-fixture-only",
        )
        self.token, self.owner = self.store.login("owner", "offline-fixture-only")
        today = self.store.now().date().isoformat()
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "计量测试", 100000, today, now=self.store.now())

    def rows(self):
        with closing(self.store.connect()) as db:
            return [
                tuple(row)
                for row in db.execute("""SELECT feature,attributedActor,charged,providerTokens,inputTokens,
                    cachedInputTokens,uncachedInputTokens,outputTokens FROM api_usage ORDER BY rowid""")
            ]

    def test_receipt_uses_reported_values_and_keeps_unknowns_null(self):
        read = token_receipt.read
        self.assertEqual(
            read(response(), 500), token_receipt.TokenReceipt(111, 100, 60, 40, 11)
        )
        self.assertEqual(
            read({"usage": {"total_tokens": 2}}, 500),
            token_receipt.TokenReceipt(2),
        )
        self.assertIsNone(read(response(total_tokens=True), 500))
        self.assertIsNone(read(response(), 110))
        self.assertEqual(
            read(response(prompt_cache_miss_tokens=39), 500),
            token_receipt.TokenReceipt(111, 100, output=11),
        )
        self.assertEqual(
            read(response(completion_tokens=15), 500), token_receipt.TokenReceipt(111)
        )
        self.assertEqual(
            read(
                response(prompt_cache_hit_tokens=0, prompt_cache_miss_tokens=100), 500
            ),
            token_receipt.TokenReceipt(111, 100, 0, 100, 11),
        )

    def test_chat_records_one_provider_charge_and_replay_writes_nothing(self):
        payload = {"text": "你好", "requestId": "usage-demo"}
        with (
            patch.object(provider, "read_key", return_value="test"),
            patch.object(deepseek, "send", return_value=response()) as remote,
        ):
            result = chat.reply(self.store, self.token, payload)
            self.assertEqual(chat.reply(self.store, self.token, payload), result)
            remote.assert_called_once()
        self.assertEqual(
            self.rows(), [("assistant.chat", None, 111, 111, 100, 60, 40, 11)]
        )

    def test_rejected_business_shape_still_records_actual_receipt(self):
        replies = [response(message="不是完整 JSON"), {**response(), "choices": [None]}]
        for index, reply in enumerate(replies):
            with (
                patch.object(provider, "read_key", return_value="test"),
                patch.object(deepseek, "send", return_value=reply),
                self.assertRaisesRegex(ValueError, "未能完成"),
            ):
                generation.generate(
                    self.store,
                    "change-review",
                    "usage-invalid-" + str(index),
                    "根据已给事实答复",
                    {"test": 7},
                    generation.narrative,
                    feature="workflow.changeReview",
                    attributed_actor=self.owner["id"],
                )
        self.assertEqual(
            self.rows(),
            [("workflow.changeReview", self.owner["id"], 111, 111, 100, 60, 40, 11)] * 2,
        )

    def test_late_receipt_keeps_paid_total_and_breakdown_on_original_row(self):
        from datetime import timedelta

        def reconcile_during_transport(key, body, **opts):
            with closing(self.store.connect()) as db, db:
                actor, request = db.execute(
                    "SELECT actor,request FROM api_usage"
                ).fetchone()
                provider.reconcile(
                    db, actor, request, 19, now=self.store.now() + timedelta(minutes=5)
                )
            return response(message='{"text":"收到"}')

        with (
            patch.object(provider, "read_key", return_value="test"),
            patch.object(deepseek, "send", side_effect=reconcile_during_transport),
        ):
            with self.assertRaisesRegex(ValueError, "迟到回执"):
                generation.generate(
                    self.store,
                    "rounds-agent",
                    "late-receipt",
                    "根据已给事实答复",
                    {"test": 8},
                    generation.narrative,
                    feature="care.roundNarrative",
                    attributed_actor=self.owner["id"],
                )
        self.assertEqual(
            self.rows(),
            [
                ("care.roundNarrative", self.owner["id"], 19, 111, 100, 60, 40, 11),
            ],
        )
        with closing(self.store.connect()) as db:
            original, reported, verified = db.execute(
                "SELECT original,reported,verified FROM api_late_usage"
            ).fetchone()
            self.assertEqual((original, reported, verified), (19, 111, None))
