"""Local token reservations must leave the scoped facts and approval boundary intact."""
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from platform_core import provider
from platform_core.agents import chat
from platform_core.store import Store, TIMEZONE
from provider_fixture import isolate_credentials
from test_assistant_chat import result


class ChatCapacityTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        isolate_credentials(self, folder.name)
        self.now = datetime(2026, 11, 24, 14, tzinfo=TIMEZONE)
        self.store = Store(Path(folder.name) / "quota.sqlite3", lambda: self.now,
                           initial_owner_password="local-test-credential")
        self.token, _ = self.store.login("owner", "local-test-credential")
        key = patch.object(provider, "read_key", return_value="offline-test-key")
        key.start()
        self.addCleanup(key.stop)
        self.cloud = Mock()

    def grant(self, limit):
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "测试套餐", limit, "2026-12-01", now=self.now)

    def balance(self):
        with closing(self.store.connect()) as db:
            plan = provider.latest(db)
            return plan["tokenLimit"], *provider.usage(db, plan["id"])

    def ask(self, question, request):
        response = chat.reply(self.store, self.token, {"text": question, "requestId": request},
                              transport=self.cloud)
        return response["messages"][-1]

    def test_unlimited_chat_continues_past_old_cap_and_expiry_and_counts_actual_usage(self):
        self.grant(1)
        with closing(self.store.connect()) as db, db:
            provider.allow_unlimited(db, now=self.now)
        self.now = self.now.replace(year=2027)
        self.token, _ = self.store.login("owner", "local-test-credential")
        self.cloud.return_value = result()
        self.cloud.return_value["choices"][0]["message"]["content"] = "已核对。"
        for number in range(2):
            answer = self.ask("查询护理用具库存", f"unlimited-{number}")
            self.assertEqual(answer["content"], "已核对。")
        self.assertEqual(self.cloud.call_count, 2)
        with closing(self.store.connect()) as db:
            plan = provider.latest(db)
            self.assertIsNone(provider.remaining_tokens(db, plan))
            self.assertEqual(provider.usage(db, plan["id"]), (256, 0))

    def test_lighter_prompt_keeps_evidence_and_requires_explicit_work_order(self):
        self.grant(100_000)
        self.cloud.return_value = result()
        self.cloud.return_value["choices"][0]["message"]["content"] = "月初的库存已核对。" * 160
        question = "护理用具库存怎么样"
        self.ask(question, "full-prompt")
        full = self.cloud.call_args.args[1]
        full_envelope = json.loads(full["messages"][1]["content"])
        remaining = 9_200
        self.assertGreater(chat.token_allowance(full), remaining)

        spent = self.balance()[1]
        self.grant(spent + remaining)
        self.cloud.reset_mock()
        self.cloud.return_value = result("请人工核对。", "workOrder", "inventory")
        revision = self.store.version(self.token)["revision"]
        answer = self.ask(question, "small-prompt")
        self.cloud.assert_called_once()
        compact = self.cloud.call_args.args[1]
        contents = json.loads(compact["messages"][1]["content"])
        self.assertLessEqual(chat.token_allowance(compact), remaining)
        self.assertEqual(contents["当前问题"], question)
        self.assertIn("物资", contents["本次可见资料"])
        self.assertEqual(contents["本次可见资料"], full_envelope["本次可见资料"])
        self.assertFalse(contents["本句可选动作（页面号对应动作）"])
        self.assertIsNone(answer["action"])
        self.assertEqual(self.balance(), (spent + remaining, spent + 128, 0))

        review = self.ask("创建工单护理用具", "manual-approval")
        self.assertEqual((review["action"]["kind"], review["action"]["route"]),
                         ("workOrder", "inventory"))
        self.assertEqual(self.store.version(self.token)["revision"], revision)
        self.assertEqual(self.balance(), (spent + remaining, spent + 256, 0))

    def test_insufficient_tokens_report_remaining_and_required_without_a_charge(self):
        self.grant(37)
        with self.assertRaises(chat.Unavailable) as failure:
            self.ask("护理用具库存怎么样", "no-room")
        message = str(failure.exception)
        self.assertIn("机构", message)
        self.assertIn("37 token", message)
        self.assertIn("额度", message)
        required = re.search(r"预留\s*([0-9,]+)\s*token", message)
        self.assertIsNotNone(required, message)
        self.assertGreater(int(required.group(1).replace(",", "")), 37)
        self.cloud.assert_not_called()
        self.assertEqual(self.balance(), (37, 0, 0))
        with closing(self.store.connect()) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM api_usage").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM assistant_threads WHERE pending IS NOT NULL").fetchone()[0], 0)
