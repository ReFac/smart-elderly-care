"""The public guide and the assistant use the same prewritten answer catalog."""

from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from platform_core import faq, provider
from platform_core.agents import chat
from platform_core.store import Store, TIMEZONE


class FrequentlyAskedQuestions(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        day = datetime(2026, 11, 25, 10, tzinfo=TIMEZONE)
        password = "temporary-faq-test-password"
        self.store = Store(Path(directory.name) / "test.sqlite", lambda: day, initial_owner_password=password)
        self.token = self.store.login("owner", password)[0]
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "测试对话", 100000, "2026-12-01", now=day)
        key = patch.object(provider, "read_key", return_value="mock-provider-credential")
        key.start()
        self.addCleanup(key.stop)
        self.transport = Mock(return_value={
            "choices": [{"finish_reason": "stop", "message": {"content": "请选择审批人并填写申请理由。"}}],
            "usage": {"total_tokens": 30},
        })

    def ask(self, question, request):
        return chat.reply(self.store, self.token, {"text": question, "requestId": request, "webSearch": True},
                          transport=self.transport)["messages"][-1]

    def test_assistant_can_open_catalog_and_answer_from_same_entry(self):
        index = self.ask("打开FAQ", "open-faq")
        self.assertEqual(index["action"]["route"], "faq")
        self.assertEqual(index["action"]["kind"], "navigate")
        self.assertEqual(index["pageLinks"], [{"route": "faq", "title": "常见问题"}])
        reply = self.ask("FAQ 里如何申请临时权限？", "faq-answer")
        selected = next(item for item in faq.read()["items"] if item["id"] == "access-request")
        links = [{"route": "faq", "title": selected["question"], "params": {"item": selected["id"]}}]
        self.assertEqual(reply["pageLinks"], links)
        self.assertEqual(reply["content"], "请选择审批人并填写申请理由。")
        payload = json.loads(self.transport.call_args.args[1]["messages"][-1]["content"])
        self.assertEqual(payload["对话上文"], [])
        self.assertEqual(payload["本次可见资料"], {"公开常见问题": [
            {"问题": selected["question"], "已核对说明": selected["answer"]},
        ]})
        self.assertIsNone(reply["action"])
        self.assertEqual(chat.read(self.store, self.token)["messages"][-1]["pageLinks"], links)

    def test_computer_question_does_not_use_faq_or_provider(self):
        with patch("platform_core.agents.chat_web.collect") as search:
            reply = self.ask("FAQ里有电脑什么配置比较好吗？", "not-care")
        self.assertIn("只处理养老", reply["content"])
        self.assertFalse(reply["pageLinks"])
        self.assertFalse(reply["webSearched"])
        self.transport.assert_not_called()
        search.assert_not_called()
