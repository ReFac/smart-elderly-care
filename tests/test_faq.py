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
from platform_core.agents.chat_progress import Progress
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

    def ask(self, question, request, token=None):
        return chat.reply(self.store, token or self.token, {"text": question, "requestId": request, "webSearch": True},
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
        self.assertIn("院务范围", reply["content"])
        self.assertFalse(reply["pageLinks"])
        self.assertFalse(reply["webSearched"])
        self.transport.assert_not_called()
        search.assert_not_called()

    def test_scheduled_batch_questions_use_verified_workflow_and_direct_links(self):
        guide = faq.BY_ID["scheduled-batch-work"]
        self.transport.return_value["choices"][0]["message"]["content"] = '{"first":2}'
        revision = self.store.version(self.token)["revision"]
        questions = ["如何发送定时批量报单", "批量化报表在哪里", "怎么进批量报表", "联网查一下怎么定时派发照护工作"]
        with patch("platform_core.agents.chat_web.collect") as search:
            for i, question in enumerate(questions):
                with self.subTest(question=question):
                    reply = self.ask(question, f"scheduled-guide-{i}")
                    self.assertEqual(reply["content"], "\n\n".join(reversed(guide.answer.split("\n\n"))))
                    self.assertIsNone(reply["action"])
                    self.assertFalse(reply["webSearched"])
                    self.assertEqual(reply["pageLinks"], [
                        {"route": "care", "tab": "scheduledWork", "title": "定时工单"},
                        {"route": "reports", "tab": "drafts", "title": "民政报送"},
                        {"route": "settings", "tab": "rounds", "title": "定时巡查"},
                        {"route": "faq", "title": guide.question, "params": {"item": guide.id}},
                    ])
        search.assert_not_called()
        self.assertEqual(self.transport.call_count, len(questions))
        self.assertEqual(self.store.version(self.token)["revision"], revision)
        self.assertEqual(chat.read(self.store, self.token)["messages"][-1]["pageLinks"], reply["pageLinks"])

    def test_scheduled_batch_links_require_the_corresponding_page_permissions(self):
        revision = self.store.version(self.token)["revision"]
        password = "temporary-faq-employee-password"
        self.store.execute("access.create", {
            "username": "scheduled-faq-staff", "displayName": "测试员工", "password": password,
            "kind": "staff", "role": "自定义", "permissions": ["care", "audit"],
        }, revision, self.token)
        employee = self.store.login("scheduled-faq-staff", password)[0]
        reply = self.ask("怎么进批量报表", "care-staff-faq", employee)
        self.assertIn("平台目前没有把这些内容统一批量发送的入口", reply["content"])
        self.assertIsNone(reply["action"])
        self.assertEqual([(link["route"], link.get("tab")) for link in reply["pageLinks"]], [
            ("care", "scheduledWork"), ("faq", None),
        ])

    def test_resident_term_accepts_old_faq_questions_and_unifies_new_stream_output(self):
        old_question = "FAQ 家属在哪里查看长者的照护记录？"
        reply = self.ask(old_question, "old-wording")
        self.assertEqual(reply["pageLinks"][0]["params"], {"item": "family-portal"})
        self.assertIn("长辈", reply["pageLinks"][0]["title"])
        self.assertEqual(chat.read(self.store, self.token)["messages"][-2]["content"], old_question)

        def send(_key, _body, receive):
            receive("请为长")
            receive("者核对资料。")
            return {"choices": [{"finish_reason": "stop", "message": {"content": "请为长者核对资料。"}}],
                    "usage": {"total_tokens": 30}}

        events = []
        progress = Progress(self.store, events.append)
        with patch.object(chat.deepseek, "stream", side_effect=send):
            turn = chat.reply(self.store, self.token, {"text": "你好", "requestId": "new-wording"}, progress=progress)
        self.assertEqual(turn["messages"][-1]["content"], "请为长辈核对资料。")
        self.assertEqual("".join(event["text"] for event in events if event["type"] == "text"), "请为长辈核对资料。")
