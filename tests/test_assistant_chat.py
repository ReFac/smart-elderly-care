"""Conversation scope, rolling time window, provider-only responses and explicit action gates."""

from contextlib import closing
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from platform_core import provider
from platform_core.agents import chat
from platform_core.agents.chat_progress import Progress, sentences
from platform_core.provider import read_aloud
from platform_core.store import Conflict, SignedOut, Store, TIMEZONE


def result(answer="云端答复", kind="", route=""):
    action = (
        {
            "kind": kind,
            "route": route,
            "title": "核对库存",
            "description": "检查护理垫库存",
        }
        if kind
        else None
    )
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps({"answer": answer, "action": action})
                },
            }
        ],
        "usage": {"total_tokens": 128},
    }


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = datetime(2026, 11, 24, 14, tzinfo=TIMEZONE)
        self.store = Store(
            Path(self.temp.name) / "demo.sqlite3",
            lambda: self.now,
            initial_owner_password="test-cloud-123456",
        )
        self.owner, _ = self.store.login("owner", "test-cloud-123456")
        self.transport = Mock()
        self.transport.return_value = result()
        self.transport.return_value["choices"][0]["message"]["content"] = "云端答复"
        self.key = patch.object(
            provider, "read_key", return_value="mock-provider-credential"
        )
        self.key.start()
        self.addCleanup(self.key.stop)
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "机构对话", 1_000_000, "2026-12-01", now=self.now)

    def ask(self, text, request="request-1", token=None, **kwargs):
        return chat.reply(
            self.store,
            token or self.owner,
            {"text": text, "requestId": request, **kwargs},
            transport=self.transport,
        )

    def command(self, action, payload):
        return self.store.execute(
            action, payload, self.store.version(self.owner)["revision"], self.owner
        )

    def staff(self, permissions, username="staff_1"):
        self.command(
            "access.create",
            {
                "username": username,
                "displayName": "测试员工",
                "password": "test-employee-123",
                "kind": "staff",
                "role": "自定义",
                "permissions": permissions,
            },
        )
        return self.store.login(username, "test-employee-123")[0]

    def facts(self):
        body = self.transport.call_args.args[1]
        return json.loads(body["messages"][1]["content"])["本次可见资料"]

    def test_short_sentence_is_authorized_before_complete_chat_turn(self):
        events, clips = [], []
        first = "今天的探访安排可以在接待时间表里核对。"
        key = patch.object(read_aloud, "read_key", return_value="mock-provider-credential")
        key.start()
        self.addCleanup(key.stop)

        def emit(event):
            events.append(event)
            if event["type"] == "speech" and event["sentence"] == 0:
                begin = events[0]
                with closing(self.store.connect()) as db:
                    self.assertEqual(db.execute("SELECT count(*) FROM assistant_turns").fetchone()[0], 0)
                read_aloud.listen(self.store, self.owner, {
                    **{key: begin[key] for key in ("generation", "scopeKey", "requestId")},
                    "region": {}, "sentence": 0,
                }, transport=lambda _key, content: clips.append(content) or b"voice")

        def stream(_key, _body, publish):
            publish(first)
            self.assertEqual(clips, [first])
            publish("请优先按已经确认的来访时间接待。")
            return {
                "choices": [{"finish_reason": "stop", "message": {
                    "content": first + "请优先按已经确认的来访时间接待。"
                }}],
                "usage": {"total_tokens": 100},
            }

        progress = Progress(self.store, emit, speak=True)
        try:
            with patch("platform_core.provider.deepseek.stream", side_effect=stream):
                saved = chat.reply(self.store, self.owner, {
                    "requestId": "in-progress-read", "text": "说下探访安排。"
                }, progress=progress)
            second = sentences(saved["messages"][-1]["content"], final=True)[1]
            read_aloud.listen(self.store, self.owner, {
                "scopeKey": saved["scopeKey"], "generation": saved["generation"],
                "requestId": "in-progress-read", "region": {}, "sentence": 1,
            }, transport=lambda _key, content: clips.append(content) or b"voice")
            self.assertEqual(clips, [first, second])
            self.assertEqual([e["type"] for e in events[:3]], ["begin", "text", "speech"])
        finally:
            progress.close()

    def test_conversation_returns_filtered_room_destination(self):
        answer = self.ask("请列出 3 间双人间")
        link = answer["messages"][-1]["pageLinks"][0]
        self.assertEqual(link, {
            "title": "查看双人间", "route": "beds", "tab": "all",
            "params": {"capacity": "2", "limit": "3"},
        })
        matched = self.facts()["实查房型"]
        self.assertEqual(matched["每间启用床位数"], 2)
        self.assertTrue(matched["房号"])
        self.assertLessEqual(len(matched["房号"]), 3)

    def test_cloud_evidence_action_rechecks_scope_and_bills_synthesis(self):
        def choose(_key, body):
            tools = {entry["function"]["name"] for entry in body["tools"]}
            self.assertIn("inventory_evidence", tools)
            self.assertNotIn("account_evidence", tools)
            self.command("ops.stock", {"itemId": "stock-1", "type": "入库", "quantity": 2})
            return {
                "usage": {"total_tokens": 80},
                "choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [
                    {"type": "function", "function": {"name": "inventory_evidence", "arguments": "{}"}}
                ]}}],
            }

        self.transport.side_effect = choose
        with patch("platform_core.provider.deepseek.send", return_value={
            "usage": {"total_tokens": 42},
            "choices": [{"finish_reason": "stop", "message": {"content": '{"text":"已核对库存。"}'}}],
        }) as final:
            result = self.ask("护理用具库存怎么样")
        self.assertEqual(result["messages"][-1]["content"], "已核对库存。")
        observed = json.loads(final.call_args.args[1]["messages"][1]["content"])["最新工具观察"]
        self.assertEqual(list(observed), ["inventory_evidence"])
        with closing(self.store.connect()) as db:
            rows = dict(db.execute("SELECT feature,charged FROM api_usage WHERE feature LIKE 'assistant.%'"))
        self.assertEqual(rows, {"assistant.chat": 80, "assistant.toolAnswer": 42})

    def test_tool_cannot_override_authorized_scope(self):
        self.transport.return_value = {
            "usage": {"total_tokens": 80},
            "choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [
                {"type": "function", "function": {
                    "name": "inventory_evidence", "arguments": '{"residentId":"r001"}'
                }}
            ]}}],
        }
        with patch("platform_core.provider.deepseek.send") as final:
            with self.assertRaises(chat.Unavailable):
                self.ask("护理用具库存怎么样")
        final.assert_not_called()

    def test_window_facts_followups_and_idempotent_read_only_turn(self):
        original = self.now
        self.now -= timedelta(hours=36)
        self.command("ops.stock", {"itemId": "stock-1", "type": "入库", "quantity": 1})
        self.now = original
        self.command("ops.stock", {"itemId": "stock-1", "type": "入库", "quantity": 2})
        rev = self.store.version(self.owner)["revision"]
        first = self.ask("今天院里情况怎么样呀")
        self.assertEqual(
            self.facts()["精确时间窗内已登记改动（操作代号及次数）"]["ops.stock"], 1
        )
        self.assertEqual(self.facts()["物资"]["低于下限品项数"], 1)
        self.assertNotIn("账号概况", self.facts())
        self.assertNotIn("经销员或供应商绩效资料", self.facts())
        self.assertEqual(len(first["messages"]), 2)
        self.assertEqual(self.ask("今天院里情况怎么样呀"), first)
        self.transport.assert_called_once()
        self.ask("那过去48小时呢", "again")
        self.assertEqual(
            self.facts()["精确时间窗内已登记改动（操作代号及次数）"]["ops.stock"], 2
        )
        second_prompt = self.transport.call_args.args[1]["messages"]
        message = json.loads(second_prompt[-1]["content"])
        self.assertEqual(
            [m["content"] for m in message["对话上文"]],
            ["今天院里情况怎么样呀", "云端答复"],
        )
        self.assertEqual(message["当前问题"], "那过去48小时呢")
        self.ask("护理用具怎么样", "third")
        self.assertEqual(
            self.facts()["精确时间窗内已登记改动（操作代号及次数）"]["ops.stock"], 2
        )
        self.assertEqual(self.store.version(self.owner)["revision"], rev)
        again = Store(self.store.path, lambda: self.now)
        self.assertEqual(len(chat.read(again, self.owner)["messages"]), 6)

    def test_account_and_supplier_evidence_is_only_added_for_relevant_questions(self):
        first = self.ask("账号情况怎么样", generation="")
        self.assertEqual(self.facts()["账号概况"]["可见账号"], 1)
        self.assertEqual(first, self.ask("账号情况怎么样", generation=""))
        self.ask("经销员怎么样", "supplier")
        self.assertIn("经销员或供应商绩效资料", self.facts())
        self.ask("他们有哪些变化呢", "follow")
        self.assertIn("经销员或供应商绩效资料", self.facts())
        self.ask("今天护理用具怎么样", "supplies")
        self.assertNotIn("经销员或供应商绩效资料", self.facts())
        self.assertNotIn("账号概况", self.facts())

    def test_actions_only_open_on_explicit_current_turn_and_stable_retry(self):
        self.transport.return_value = result(kind="workOrder", route="inventory")
        for i, q in enumerate(
            ("护理用具怎么样", "如果我说创建工单呢", "不要创建工单", "创建工单需要什么")
        ):
            self.assertIsNone(self.ask(q, f"q{i}")["messages"][-1]["action"])
        action = self.ask("创建工单护理用具")["messages"][-1]["action"]
        self.assertEqual(action["route"], "inventory")
        self.assertEqual(len(action["id"]), 64)
        self.assertEqual(action, self.ask("创建工单护理用具")["messages"][-1]["action"])
        self.transport.return_value = result(kind="navigate", route="intake")
        self.assertEqual(
            self.ask("创建老人入住", "go")["messages"][-1]["action"]["route"], "intake"
        )
        self.transport.return_value = result(kind="notice", route="inbox")
        self.assertEqual(
            self.ask("上全员通知", "all")["messages"][-1]["action"]["kind"], "notice"
        )
        self.assertEqual(self.store.version(self.owner)["revision"], 0)

    def test_requested_floorplan_excludes_current_page_and_other_tab(self):
        self.transport.return_value["choices"][0]["message"]["content"] = (
            "点击楼层平面图。床位管理还有全部床位页签。你当前停在长期护理保险页面。"
        )
        self.assertEqual(
            self.ask("我想按平面图选床，该从哪里进入？", page="longCare")["messages"][
                -1
            ]["pageLinks"],
            [{"route": "beds", "tab": "plan", "title": "楼层平面图"}],
        )
        guide = json.loads(self.transport.call_args.args[1]["messages"][-1]["content"])[
            "可见办理入口（页面及分页签）"
        ]
        self.assertIn("长护险经办台账", guide["长期护理保险"][0])
        self.assertIn("档案名册", " ".join(guide["长者档案"]))

    def test_internal_destination_unavailable_to_employee_stays_off_public_network(
        self,
    ):
        staff = self.staff(["clinical"])
        with patch("platform_core.agents.chat_web.collect") as search:
            self.transport.return_value["choices"][0]["message"]["content"] = (
                "当前账号仅提供健康体征。"
            )
            msg = self.ask("打开机构的数据备份", token=staff, webSearch=True)[
                "messages"
            ][-1]
        search.assert_not_called()
        self.assertFalse(msg["pageLinks"])
        self.assertIsNone(msg["action"])
        self.assertFalse(msg["webSearched"])

    def test_how_to_links_to_real_pages_and_tabs_without_opening_a_form(self):
        cases = [
            ("在哪里办理老人入住？", "residents", "all"),
            ("哪里办理试住？", "residents", "trials"),
            ("我的试住回访入口在哪里？", "residents", "trials"),
            ("试住默认价在哪里修改？", "settings", "trials"),
            ("在哪里核算月付账单？", "billing", "due"),
            ("我想按平面图选床，该从哪里进入？", "beds", "plan"),
            ("我想查看机构的备份和恢复记录，入口在哪里？", "settings", "backups"),
            ("怎么进入长期护理保险的经办台账？", "longCare", None),
            ("怎么查看欠费提醒？", "billing", "reminders"),
        ]
        for i, (text, route, tab) in enumerate(cases):
            with self.subTest(text=text):
                reply = self.ask(text, "how" + str(i))["messages"][-1]
                self.assertEqual(
                    [(p["route"], p.get("tab")) for p in reply["pageLinks"]],
                    [(route, tab)],
                )
                self.assertIsNone(reply["action"])
        self.assertEqual(self.store.version(self.owner)["revision"], 0)

    def test_recommended_pages_survive_history_and_anaphoric_followup(self):
        # Older turns stored just the assistant's prose, with no application destinations.
        self.transport.return_value["choices"][0]["message"]["content"] = (
            "可在「物资仓储」的「库存台账」核对库存；收款请进入「财务结算」的「收款流水」。"
        )
        first = self.ask("接下来有什么需要看的？")
        links = first["messages"][-1]["pageLinks"]
        self.assertEqual(
            [(p["route"], p.get("tab")) for p in links],
            [("inventory", "stock"), ("billing", "receipts")],
        )
        self.assertEqual(chat.read(self.store, self.owner), first)
        self.transport.return_value["choices"][0]["message"]["content"] = (
            "可以选择刚才提到的入口。"
        )
        self.assertEqual(
            self.ask("刚才说的那个页面入口在哪？", "follow")["messages"][-1][
                "pageLinks"
            ],
            links,
        )
        self.assertFalse(self.ask("谢谢", "bye")["messages"][-1]["pageLinks"])

    def test_canonical_links_follow_hidden_routes_and_tab_permissions(self):
        staff = self.staff(["clinical"])
        self.transport.return_value["choices"][0]["message"]["content"] = (
            "您可以前往「机构设置」「照护工单」和「健康体征」。"
        )
        reply = self.ask("这些入口在哪里？", token=staff)["messages"][-1]
        self.assertEqual(
            reply["pageLinks"],
            [{"route": "care", "tab": "vitals", "title": "健康体征"}],
        )
        with closing(self.store.connect()) as db, db:
            db.execute(
                """UPDATE institution_settings SET visual=json_set(visual,'$.hiddenRoutes',json('["care"]'))"""
            )
        self.assertFalse(chat.read(self.store, staff)["messages"])
        self.assertFalse(
            self.ask("这些入口在哪里？", "hidden", token=staff)["messages"][-1][
                "pageLinks"
            ]
        )

    def test_scope_revocation_private_transcripts_and_reset(self):
        employee = self.staff(["assistants", "inventory"])
        first = self.ask("看看仓库", token=employee)
        self.assertIn("物资", self.facts())
        self.assertNotIn("账号概况", self.facts())
        self.assertNotIn("照护工单", self.facts())
        self.assertFalse(chat.read(self.store, self.owner)["messages"])
        with self.assertRaises(Conflict):
            self.ask("看我上次聊天", request="changed", scopeKey=first["scopeKey"])
        current = self.store.snapshot(employee)["data"]["user"]
        self.command("access.update", {"id": current["id"], "permissions": []})
        employee = self.store.login("staff_1", "test-employee-123")[0]
        self.assertFalse(chat.read(self.store, employee)["messages"])
        limited = self.ask("怎么使用这个界面", token=employee, request="help")
        self.assertNotIn("物资", self.facts())
        self.assertNotEqual(limited["scopeKey"], first["scopeKey"])
        chat.reset(
            self.store,
            employee,
            {"scopeKey": limited["scopeKey"], "generation": limited["generation"]},
        )
        self.assertEqual(chat.read(self.store, employee)["messages"], [])
        with self.assertRaises(Conflict):
            self.ask("怎么使用这个界面", token=employee, request="help")

    def test_provider_failure_no_fallback_and_billing_is_retained(self):
        self.transport.side_effect = URLError("timeout")
        with self.assertRaises(chat.Unavailable):
            self.ask("库存怎么样")
        self.assertFalse(chat.read(self.store, self.owner)["messages"])
        with closing(self.store.connect()) as db, db:
            self.assertEqual(
                db.execute("SELECT status FROM api_usage").fetchone()[0], "uncertain"
            )
        self.transport.side_effect = None
        self.ask("再次询问", "retry")
        with closing(self.store.connect()) as db, db:
            provider.disable(db)
        with self.assertRaises(chat.Unavailable):
            self.ask("没有额度", "noplan")
        self.assertEqual(self.transport.call_count, 2)
        with self.assertRaises(SignedOut):
            chat.read(self.store, "invalid")

    def test_region_prompt_and_thread_do_not_contain_institution_or_neighbor_data(self):
        room = {
            "roomId": self.store.facility_resource(self.owner, "floor", "floor-1")[
                "rooms"
            ][0]["id"]
        }
        scoped = self.ask("这个房间如何", region=room)
        self.assertNotIn("账号概况", self.facts())
        self.assertNotIn("物资", self.facts())
        self.assertLess(
            self.facts()["当前床位"]["床位数"],
            len(self.store.snapshot(self.owner)["data"]["beds"]),
        )
        self.assertFalse(chat.read(self.store, self.owner)["messages"])
        self.assertEqual(scoped, chat.read(self.store, self.owner, room))
        with self.assertRaises(FileNotFoundError):
            chat.read(self.store, self.owner, {"roomId": "room-nowhere"})

    def test_reset_with_stale_or_missing_generation_preserves_other_tabs_conversation(
        self,
    ):
        snapshot = chat.read(self.store, self.owner)
        fresh = chat.reset(
            self.store, self.owner, {"scopeKey": snapshot["scopeKey"], "generation": ""}
        )
        saved = self.ask("我的新问题", generation=fresh["generation"])
        for old in (
            {"scopeKey": snapshot["scopeKey"], "generation": ""},
            {"scopeKey": fresh["scopeKey"]},
        ):
            with self.assertRaises(Conflict):
                chat.reset(self.store, self.owner, old)
        self.assertEqual(chat.read(self.store, self.owner), saved)

    def test_closed_413_releases_entitlement(self):
        self.transport.side_effect = HTTPError(
            "https://example.test", 413, "too large", {}, None
        )
        with self.assertRaises(chat.Unavailable):
            self.ask("查照护")
        with closing(self.store.connect()) as db:
            self.assertEqual(
                tuple(db.execute("SELECT status,charged FROM api_usage").fetchone()),
                ("closed", 0),
            )
            self.assertEqual(provider.usage(db, provider.latest(db)["id"]), (0, 0))

    def test_reconciliation_wins_late_receipt_without_publishing_the_answer(self):
        def delayed(*args):
            self.now += timedelta(seconds=100)
            with closing(self.store.connect()) as db, db:
                provider.reconcile(
                    db,
                    self.store.actor(db, self.owner)["id"],
                    "chat/request-1",
                    0,
                    self.now,
                )
            return result()

        self.transport.side_effect = delayed
        with self.assertRaises(chat.Unavailable):
            self.ask("问院务")
        with closing(self.store.connect()) as db:
            self.assertEqual(
                tuple(
                    db.execute(
                        "SELECT status,charged,reason FROM api_usage WHERE request='chat/request-1'"
                    ).fetchone()
                ),
                ("closed", 0, "reconciled"),
            )
            self.assertEqual(provider.usage(db, provider.latest(db)["id"]), (0, 128))
        self.assertFalse(chat.read(self.store, self.owner)["messages"])

    def test_token_budget_discards_whole_oldest_turns_and_keeps_latest(self):
        # Fill the synthetic thread without paying for additional provider calls.
        first = self.ask("第一轮")
        with closing(self.store.connect()) as db, db:
            actor = self.store.actor(db, self.owner)["id"]
            for index in range(14):
                db.execute(
                    """INSERT INTO assistant_turns(actor,scope,generation,request,fingerprint,asked,answered,question,answer,hours)
                    VALUES(?,?,?,?,?,'test','test',?,?,24)""",
                    (
                        actor,
                        first["scopeKey"],
                        first["generation"],
                        f"fill{index}",
                        "demo",
                        f"问题{index}",
                        "库存依据" * 800,
                    ),
                )
        self.ask("继续", "last")
        body = self.transport.call_args.args[1]
        prompt = json.loads(body["messages"][-1]["content"])
        self.assertGreater(len(prompt["对话上文"]), 2)
        self.assertEqual(prompt["对话上文"][-2]["content"], "问题13")
        self.assertNotIn("第一轮", [m["content"] for m in prompt["对话上文"]])
        self.assertEqual(len(prompt["对话上文"]) % 2, 0)
        self.assertLessEqual(
            len(chat.ctx.compact(body["messages"]).encode())
            + body["max_tokens"]
            + chat.CONTEXT_PAD,
            100000,
        )

    def test_reset_during_transport_discards_reply_and_settles_usage(self):
        def resetting(key, body):
            chat.reset(
                self.store,
                self.owner,
                {"generation": chat.read(self.store, self.owner)["generation"]},
            )
            return result()

        self.transport.side_effect = resetting
        with self.assertRaises(Conflict):
            self.ask("看护理工单")
        self.assertFalse(chat.read(self.store, self.owner)["messages"])
        with closing(self.store.connect()) as db:
            self.assertEqual(
                tuple(db.execute("SELECT status,charged FROM api_usage").fetchone()),
                ("ok", 128),
            )
