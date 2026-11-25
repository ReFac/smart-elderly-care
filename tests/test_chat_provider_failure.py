"""Distinguish upstream payment failures from the institution's token allowance."""

from contextlib import closing
from datetime import datetime
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from platform_core import provider
from platform_core.agents import chat
from platform_core.store import Store, TIMEZONE


class ChatProviderFailureTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.now = datetime(2026, 11, 24, 14, tzinfo=TIMEZONE)
        self.store = Store(
            Path(directory.name) / "test.db",
            lambda: self.now,
            initial_owner_password="example-failure-test",
        )
        self.owner, _ = self.store.login("owner", "example-failure-test")
        self.enterContext(patch.object(provider, "read_model_key", return_value="fixture"))
        self.enterContext(patch.object(provider, "model_name", return_value="fixture"))
        self.set_allowance(1_000_000)

    def set_allowance(self, tokens):
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "测试", tokens, "2026-12-01", now=self.now)

    def ask(self, request, transport):
        chat.reply(
            self.store, self.owner, {"text": "查照护", "requestId": request},
            transport=transport,
        )

    def test_http_reason_identifies_provider_and_does_not_disclose_response(self):
        cases = (
            ("deepseek", 402, "DeepSeek API 余额不足", "closed"),
            ("openai", 402, "服务商要求付款", "closed"),
            ("deepseek", 401, "当前凭据", "closed"),
            ("deepseek", 403, "访问权限", "closed"),
            ("deepseek", 429, "服务商限制", "closed"),
            ("deepseek", 413, "未接受本次请求", "closed"),
            ("deepseek", 503, "暂时无法处理", "uncertain"),
        )
        for channel, code, phrase, status in cases:
            with self.subTest(channel=channel, code=code):
                request = f"{channel}-{code}"
                raw = BytesIO(b"private-provider-body")
                error = HTTPError(
                    "https://provider.invalid/", code, "private-provider-message", {}, raw
                )
                with (
                    patch.object(chat.completions, "provider_name", return_value=channel),
                    self.assertRaises(chat.Unavailable) as raised,
                ):
                    self.ask(request, Mock(side_effect=error))
                message = str(raised.exception)
                self.assertIn(phrase, message)
                self.assertIn(f"HTTP {code}", message)
                self.assertNotIn("private-provider", message)
                if (channel, code) != ("deepseek", 402):
                    self.assertNotIn("余额不足", message)
                self.assertTrue(raw.closed)
                with closing(self.store.connect()) as db:
                    row = db.execute(
                        "SELECT status,reason,charged FROM api_usage WHERE request=?",
                        ("chat/" + request,),
                    ).fetchone()
                    self.assertEqual(tuple(row), (status, f"provider_http_{code}", 0))

    def test_insufficient_institution_tokens_stops_before_contacting_provider(self):
        self.set_allowance(1)
        transport = Mock(side_effect=AssertionError("不应调用服务商"))
        with self.assertRaisesRegex(chat.Unavailable, "机构.*套餐") as raised:
            self.ask("institution-limit", transport)
        self.assertNotIn("余额不足", str(raised.exception))
        transport.assert_not_called()
        with closing(self.store.connect()) as db:
            self.assertIsNone(db.execute(
                "SELECT 1 FROM api_usage WHERE request='chat/institution-limit'"
            ).fetchone())
