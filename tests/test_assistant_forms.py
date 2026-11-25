"""Assistant form entrypoints use signals, never draft submitted business values."""

from contextlib import closing
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from platform_core import provider
from platform_core.agents import chat
from platform_core.store import Store, TIMEZONE


class AssistantFormTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        now = datetime(2026, 11, 25, 10, tzinfo=TIMEZONE)
        self.password = "temporary-assistant-form-password"
        self.store = Store(Path(directory.name) / "test.sqlite", lambda: now, initial_owner_password=self.password)
        self.token = self.store.login("owner", self.password)[0]
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "表单测试", 100000, "2026-12-01", now=now)
        key = patch.object(provider, "read_key", return_value="mock-provider-credential")
        key.start()
        self.addCleanup(key.stop)
        self.transport = Mock(return_value={
            "choices": [{"finish_reason": "stop", "message": {
                "content": '{"answer":"已自动填写并发布", "action":{"kind":"notice","route":"inbox","title":"不应写入"}}',
            }}],
            "usage": {"total_tokens": 20},
        })

    def ask(self, text, request, token=None):
        return chat.reply(self.store, token or self.token, {"text": text, "requestId": request, "webSearch": True},
                          transport=self.transport)["messages"][-1]

    def test_known_direct_commands_open_precise_manual_forms_without_business_writes(self):
        cases = (
            ("新增员工，李明护士", "staffAdd", "access", ""),
            ("请帮我创建长者档案", "residentAdd", "residents", "notAdmitted"),
            ("办理入住", "admission", "residents", "notAdmitted"),
            ("打开办理试住", "trial", "residents", "notAdmitted"),
            ("登记来电", "leadAdd", "leads", "contacts"),
            ("打开录入体征", "vitalAdd", "care", "vitals"),
            ("核算账单，实收 99 元", "billAdd", "billing", "due"),
            ("新建定时工单", "scheduleAdd", "care", "scheduledWork"),
            ("生成报送草稿", "reportAdd", "reports", "drafts"),
            ("手动录入病例", "visitManual", "dossier", ""),
        )
        revision = self.store.version(self.token)["revision"]
        with patch("platform_core.agents.chat_web.collect") as search:
            for i, (text, form, route, tab) in enumerate(cases):
                with self.subTest(text=text):
                    reply = self.ask(text, f"form-{i}")
                    self.assertEqual(reply["action"], {
                        "kind": "openForm", "form": form, "route": route, "tab": tab, "title": reply["action"]["title"],
                    })
                    self.assertIn("填写资料并核对确认", reply["content"])
                    self.assertNotIn("已自动填写", reply["content"])
                    self.assertFalse(reply["webSearched"])
        search.assert_not_called()
        self.assertEqual(self.store.version(self.token)["revision"], revision)

    def test_direct_form_permissions_and_questions_do_not_trigger_actions(self):
        revision = self.store.version(self.token)["revision"]
        self.store.execute("access.create", {
            "username": "form-staff", "displayName": "测试员工", "password": self.password,
            "kind": "staff", "role": "自定义", "permissions": ["care"],
        }, revision, self.token)
        staff = self.store.login("form-staff", self.password)[0]
        denied = self.ask("新增员工", "form-denied", staff)
        self.assertIsNone(denied["action"])
        self.assertIn("没有", denied["content"])
        self.assertIsNone(self.ask("如何打开办理试住？", "form-question")["action"])
        self.assertIsNone(self.ask("请勿打开定时工单", "form-negative")["action"])
