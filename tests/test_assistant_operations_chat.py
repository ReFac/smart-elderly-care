"""Everyday questions from staff should open a private, evidence-backed ward briefing."""

from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from platform_core import provider
from platform_core.agents import chat, chat_scope
from platform_core.agents.chat_progress import Progress
from platform_core.provider import web_search
from platform_core.store import Store, TIMEZONE


class OperationsChatTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        now = datetime(2026, 11, 24, 14, tzinfo=TIMEZONE)
        self.store = Store(
            Path(folder.name) / "test.db",
            lambda: now,
            initial_owner_password="test-institution-chat",
        )
        self.owner, _ = self.store.login("owner", "test-institution-chat")
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "测试", 1_000_000, "2026-12-01", now=now)
        key = patch.object(provider, "read_key", return_value="test-provider")
        key.start()
        self.addCleanup(key.stop)
        search = patch.object(
            web_search, "search", side_effect=AssertionError("院务资料不能联网检索")
        )
        search.start()
        self.addCleanup(search.stop)
        self.cloud = Mock(
            return_value={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"first":1,"answer":"模型编造的经营数据"}',
                        },
                    }
                ],
                "usage": {"total_tokens": 80},
            }
        )

    def ask(self, text, key, *, web=False, token=None, progress=None):
        return chat.reply(
            self.store,
            token or self.owner,
            {
                "requestId": key,
                "text": text,
                "webSearch": web,
            },
            transport=self.cloud,
            progress=progress,
        )["messages"][-1]

    def receipt(self, key):
        with closing(self.store.connect()) as db:
            row = db.execute(
                "SELECT feature FROM api_usage WHERE request=?", ("chat/" + key,)
            ).fetchone()
            return row[0] if row else None

    def account(self, username, **profile):
        password = "fixture-only-password"
        self.store.execute(
            "access.create",
            {
                "username": username,
                "displayName": "测试用户",
                "password": password,
                **profile,
            },
            self.store.version(self.owner)["revision"],
            self.owner,
        )
        return self.store.login(username, password)[0]

    def test_owner_overview_after_unrelated_question_with_and_without_web(self):
        blocked = self.ask("今天电脑配置怎么样？", "outside", web=True)
        self.assertEqual(blocked["content"], chat_scope.REFUSAL)
        self.cloud.assert_not_called()
        events = []
        stream = Progress(self.store, events.append)
        self.addCleanup(stream.close)
        for key, phrase, web in (
            ("today", "今天怎么样了？", False),
            ("institution", "养老院怎么样", True),
        ):
            with self.subTest(phrase=phrase):
                msg = self.ask(phrase, key, web=web, progress=stream if web else None)
                self.assertEqual(self.receipt(key), "assistant.operations")
                self.assertFalse(msg["webSearched"])
                self.assertIsNone(msg["action"])
                self.assertNotIn("模型编造的经营数据", msg["content"])
                prompt = json.loads(
                    self.cloud.call_args.args[1]["messages"][-1]["content"]
                )
                self.assertEqual(prompt["当前问题"], phrase)
                lines = list(prompt["事实"].values())
                self.assertGreaterEqual(len(lines), 2)
                for line in lines:
                    self.assertIn(line, msg["content"])
                records = self.store.snapshot(self.owner)["data"]
                occupied = sum(
                    person["status"] == "在住" for person in records["residents"]
                )
                self.assertRegex(msg["content"], rf"在住\s*{occupied}\s*人")
                self.assertRegex(msg["content"], "工单|照护|护理")
                self.assertRegex(msg["content"], "收入|收[到入款]|实收|入账")
        self.assertEqual(self.cloud.call_count, 2)
        self.assertIn({"type": "text", "text": msg["content"]}, events)
        self.assertEqual(self.ask("养老院怎么样", "institution", web=True), msg)
        self.assertEqual(self.cloud.call_count, 2)

    def test_short_followup_after_implicit_institution_question(self):
        self.ask("今天怎么样了？", "overview")
        self.cloud.return_value["choices"][0]["message"]["content"] = (
            "以下是最近 48 小时的院务变动。"
        )
        msg = self.ask("那过去48小时呢", "followup", web=True)
        self.assertNotEqual(msg["content"], chat_scope.REFUSAL)
        self.assertFalse(msg["webSearched"])
        self.assertEqual(self.cloud.call_count, 2)
        with closing(self.store.connect()) as db:
            row = db.execute(
                "SELECT hours FROM assistant_turns WHERE request='followup'"
            ).fetchone()
            self.assertEqual(row[0], 48)

    def test_family_and_staff_only_receive_permitted_data(self):
        family = self.account("operations-family", kind="family", residentId="r001")
        msg = self.ask("养老院怎么样？", "family", web=True, token=family)
        self.assertIsNone(self.receipt("family"))
        self.assertFalse(msg["webSearched"])
        self.assertIsNone(msg["action"])
        self.assertRegex(msg["content"], "权限|仅能|只能|无权")
        self.cloud.assert_not_called()

        staff = self.account(
            "operations-care",
            kind="staff",
            role="自定义",
            permissions=["assistants", "care"],
        )
        msg = self.ask("今天怎么样？", "staff", token=staff)
        self.assertEqual(self.receipt("staff"), "assistant.operations")
        self.assertRegex(msg["content"], "工单|照护|护理")
        prompt = self.cloud.call_args.args[1]["messages"][-1]["content"]
        self.assertNotRegex(prompt, "实收|新收到|净入账|待缴余额")

    def test_specific_subjects_and_off_topic_requests_keep_their_routes(self):
        for phrase, key in (("今天财务怎么样", "finance"), ("老人健康吗？", "health")):
            self.ask(phrase, key, web=True)
            self.assertEqual(self.receipt(key), "assistant." + key)
        for key, phrase in (
            ("weather", "今天郑州天气怎么样？"),
            ("mixed", "今天养老院怎么样，顺便推荐电脑配置"),
        ):
            msg = self.ask(phrase, key, web=True)
            self.assertEqual(msg["content"], chat_scope.REFUSAL)
            self.assertIsNone(self.receipt(key))
        self.assertEqual(self.cloud.call_count, 2)
