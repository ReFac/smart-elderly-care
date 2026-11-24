from contextlib import closing
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from platform_core import provider
from platform_core.agents import chat
from platform_core.provider import speech
from platform_core.store import Store, TIMEZONE
from test_assistant_chat import result


class AssistantPublicationTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.now = datetime(2026, 11, 24, 14, tzinfo=TIMEZONE)
        self.store = Store(
            Path(directory.name) / "sample.sqlite3",
            lambda: self.now,
            initial_owner_password="synthetic-test-owner",
        )
        self.owner, self.actor = self.store.login("owner", "synthetic-test-owner")
        key = patch.object(provider, "read_key", return_value="simulated-test-provider")
        key.start()
        self.addCleanup(key.stop)
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "合成测试", 1_000_000, "2026-12-31", now=self.now)
        self.crew, self.member = self.staff("day-crew", ["voice"])

    def write(self, action, payload, token=None):
        token = token or self.owner
        return self.store.execute(
            action, payload, self.store.version(token)["revision"], token
        )

    def staff(self, name, grants):
        self.write(
            "access.create",
            dict(
                kind="staff",
                username=name,
                password="synthetic-test-login",
                displayName="测试人员" + name,
                role="自定义",
                permissions=grants,
            ),
        )
        return self.store.login(name, "synthetic-test-login")

    def propose(self, text, kind, route, request):
        turns = chat.reply(
            self.store,
            self.owner,
            {"text": text, "requestId": request},
            transport=lambda *_, **__: result("请核对", kind, route),
        )
        return turns["messages"][-1]["action"]["id"]

    def test_supply_draft_confirmation_recipient_and_replay(self):
        key = self.propose("创建工单护理用具", "workOrder", "inventory", "new-supply")

        def snapshot(token):
            return self.store.snapshot(token)["data"]

        self.assertEqual(snapshot(self.owner)["supplyOrders"], [])
        draft = dict(
            assistantActionId=key,
            title="护理垫补货",
            description="盘点护理垫并登记采购需求",
            assigneeId=self.member["id"],
            dueDate="2026-11-25",
        )
        with self.assertRaises(ValueError):
            self.write("ops.supplyOrder", {**draft, "assigneeId": "missing"})
        self.write("ops.supplyOrder", draft)
        with self.assertRaisesRegex(ValueError, "已经发布"):
            self.write("ops.supplyOrder", draft)
        with self.assertRaises(PermissionError):
            self.write("ops.publishNotice", {**draft})
        order = snapshot(self.crew)["supplyOrders"][0]
        other, _ = self.staff("other-crew", [])
        self.assertEqual(snapshot(other)["supplyOrders"], [])
        with self.assertRaises(PermissionError):
            self.write("ops.finishSupplyOrder", {"orderId": order["id"]}, other)
        self.write("ops.finishSupplyOrder", {"orderId": order["id"]}, self.crew)
        self.assertEqual(snapshot(self.owner)["supplyOrders"][0]["status"], "已完成")

    def test_notice_requires_live_review_and_only_staff_can_read(self):
        def proposal(request):
            return self.propose("发布全员通知", "notice", "inbox", request)

        values = dict(
            title="新值班安排",
            description="请全体员工核对值班安排",
            assistantActionId=proposal("notice-first"),
        )
        session = chat.read(self.store, self.owner)
        chat.reset(
            self.store,
            self.owner,
            {key: session[key] for key in ("scopeKey", "generation")},
        )
        with self.assertRaises(PermissionError):
            self.write("ops.publishNotice", values)
        values["assistantActionId"] = proposal("notice-second")
        with self.assertRaises(PermissionError):
            self.write("ops.publishNotice", values, self.crew)
        self.write("ops.publishNotice", values)
        self.assertEqual(
            self.store.snapshot(self.crew)["data"]["staffNotices"][0]["title"],
            values["title"],
        )
        self.write(
            "access.create",
            dict(
                kind="family",
                username="family-notices",
                displayName="测试家属",
                residentId="r001",
                password="synthetic-family-test",
            ),
        )
        token, _ = self.store.login("family-notices", "synthetic-family-test")
        self.assertFalse(self.store.snapshot(token)["data"].get("staffNotices"))
        self.assertFalse(self.store.snapshot(token)["data"].get("assistantVoice"))

    def test_chat_voice_accepts_authorized_staff_independent_of_old_domain(self):
        self.assertEqual(
            self.store.snapshot(self.crew)["data"]["assistantVoice"]["path"],
            "/api/assistant/voice",
        )
        with closing(self.store.connect()) as db:
            ref, _ = speech.chat_voice_context(
                db, self.store.actor(db, self.crew), None
            )
            self.assertTrue(ref.startswith("chat-voice:"))
            with self.assertRaises(PermissionError):
                speech.agent_context(db, self.store.actor(db, self.crew), None)
