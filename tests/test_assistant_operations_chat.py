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

    def test_resident_status_questions_resolve_the_requested_location_before_cloud(self):
        with closing(self.store.connect()) as db, db:
            state = json.loads(db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0])
            state["vitals"] = [
                {"residentId": person, "date": "2026-11-24", "abnormal": True}
                for person in ("r001", "r003", "r003")
            ]
            db.execute("UPDATE workspace SET data=? WHERE id=1", (json.dumps(state),))
        overview = self.ask("老人们状况如何？", "health-all", web=True)
        self.assertIn("3 条异常体征", overview["content"])
        self.assertFalse(overview["webSearched"])
        ambiguous = self.ask("101床的老人们状态如何？", "check-number", web=True)
        self.assertIn("整间房", ambiguous["content"])
        self.assertFalse(ambiguous["pageLinks"])
        self.assertNotIn("异常体征", ambiguous["content"])
        room = self.ask("101房", "health-room", web=True)
        self.assertIn("101 房", room["content"])
        self.assertIn("在住 2 人", room["content"])
        self.assertIn("1 条异常体征", room["content"])
        bed = self.ask("那101-02床呢？", "health-bed", web=True)
        self.assertIn("101-02", bed["content"])
        self.assertIn("在住 1 人，今天还没有体征登记", bed["content"])
        prompt = self.cloud.call_args.args[1]["messages"][-1]["content"]
        self.assertNotRegex(prompt, "3 条异常体征|在住 2 人|收款|r001")
        missing = self.ask("999床的长辈状态如何？", "missing-bed", web=True)
        self.assertIn("没有找到", missing["content"])
        self.assertFalse(missing["pageLinks"])
        self.assertEqual(self.receipt("health-room"), "assistant.health")

    def test_resident_status_respects_permissions_and_room_assignment(self):
        account = self.account("health-reader", kind="staff", role="自定义",
                               permissions=["assistants", "clinical"])
        with closing(self.store.connect()) as db:
            room = db.execute("SELECT roomId FROM facility_beds WHERE bedId='b001'").fetchone()[0]
        self.store.facility_policy = lambda db, actor: {"roomIds": [room]}
        scoped = self.ask("老人们状况如何？", "assigned", token=account, web=True)
        self.assertIn("在住 2 人", scoped["content"])
        hidden = self.ask("102-01床的老人状态如何？", "other-room", token=account, web=True)
        self.assertIn("没有找到", hidden["content"])
        self.assertFalse(hidden["pageLinks"])
        self.store.facility_policy = None
        family = self.account("health-relative", kind="family", residentId="r001")
        count = self.cloud.call_count
        self.assertIn("权限", self.ask("老人们状况如何？", "denied-health", token=family)["content"])
        self.assertEqual(self.cloud.call_count, count)

    def test_unfamiliar_phrasing_gets_a_private_clarifying_turn(self):
        self.cloud.return_value["choices"][0]["message"]["content"] = "你想问的是哪间房？"
        for index, question in enumerate(("帮我瞅瞅大伙儿呗", "怎么设置 Wi-Fi 路由器？")):
            msg = self.ask(question, f"ambiguous-{index}", web=True)
            self.assertEqual(msg["content"], "你想问的是哪间房？")
            self.assertFalse(msg["webSearched"])
            body = self.cloud.call_args.args[1]
            self.assertNotIn("tools", body)
            self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
            self.assertEqual(body["messages"][-1]["content"], question)

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
