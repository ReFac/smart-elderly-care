"""Cash allocation, resident coverage, private audio and reception archive boundaries."""

from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from platform_core import lead_contacts, lead_directory, provider
from platform_core.agents import chat, chat_context, revenue, ward_brief
from platform_core.provider import read_aloud
from platform_core.store import Store, TIMEZONE


class WardOverview(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.now = datetime(2026, 11, 24, 14, tzinfo=TIMEZONE)
        self.store = Store(
            Path(folder.name) / "test.db",
            now=lambda: self.now,
            initial_owner_password="example-only-000",
        )
        self.token, self.owner = self.store.login("owner", "example-only-000")

    def test_finance_allocation_cutoffs_and_private_scope(self):
        direct = [
            dict(
                residentId="a",
                amount=58.01,
                feeAmount=0.10,
                method="线下刷卡登记",
                date="2026-11-24",
            ),
            dict(residentId="a", amount=40, method="预交金冲抵", date="2026-11-24"),
            dict(residentId="a", amount=5, method="线下登记", date="2026-10-31"),
            dict(residentId="b", amount=45, method="微信支付", date="2026-11-24"),
        ]
        ledgers = dict(
            payments=direct,
            depositEntries=[
                dict(residentId="a", amount=1.99, date="2026-11-24", feeAmount=0.01),
                dict(residentId="a", amount=42, date="2026-11-02"),
            ],
            bills=[
                dict(residentId="a", balance=10.25),
                dict(residentId="b", balance=11),
            ],
        )
        totals = revenue.overview(ledgers, "2026-11-24", {"a"})
        self.assertEqual(
            [
                totals[k]
                for k in ("monthGross", "todayGross", "todayNet", "outstanding")
            ],
            [102, 60, 59.89, 10.25],
        )

        del direct[0]["feeAmount"]
        self.assertIsNone(revenue.overview(ledgers, "2026-11-24", {"a"})["todayNet"])

    def test_health_counts_no_abnormal_and_permissions(self):
        with closing(self.store.connect()) as db, db:
            actor, _, _, state, _ = chat_context.scope(self.store, db, self.token, {})
            state["vitals"] = []
            facts = chat_context.evidence(
                self.store, db, actor, state, None, 24, "老人健康吗"
            )
            self.assertEqual(facts["今日已登记健康情况"]["新增异常体征记录"], 0)
            self.assertEqual(facts["今日已登记健康情况"]["已记录体征人数"], 0)
            wording = "".join(ward_brief.phrases("health", facts))
            self.assertIn("今日已登记的记录中未见新增健康异常", wording)
            self.assertIn("还没有体征登记", wording)
            self.assertNotIn("咳嗽", wording)
            actor = {
                **actor,
                "kind": "staff",
                "permissions": ["inventory", "assistants"],
            }
            scoped = chat_context.evidence(
                self.store, db, actor, state, None, 24, "今日的财"
            )
            self.assertNotIn("今日已登记健康情况", scoped)
            self.assertNotIn("到账与欠款（元）", scoped)

    def test_cloud_daily_brief_can_order_but_cannot_insert_other_facts(self):
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "单位测试", 200000, "2026-12-01", now=self.now)
        transport = Mock(
            return_value={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"first":2,"answer":"所有人健康"}'},
                    }
                ],
                "usage": {"total_tokens": 90},
            }
        )
        with patch.object(provider, "read_key", return_value="test"):
            for i, question in enumerate(
                ("今日的财、今日的流水、今日的营收情况", "今日导人气正常吗？")
            ):
                result = chat.reply(
                    self.store,
                    self.token,
                    {
                        "text": question,
                        "webSearch": True,
                        "requestId": "brief-" + str(i),
                    },
                    transport=transport,
                )
                reply = result["messages"][-1]
                self.assertFalse(reply["webSearched"])
                self.assertNotIn("所有人健康", reply["content"])
                if not i:
                    self.assertIn("今天新收到", reply["content"])
                    self.assertIn("待缴", reply["content"])
                else:
                    self.assertIn("登记体征", reply["content"])
                    self.assertIn("异常", reply["content"])

    def test_private_reply_speech_refetch_and_medication_intent(self):
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "单位测试", 200000, "2026-12-01", now=self.now)
        transport = Mock(
            return_value={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"answer":"请核对","action":null}'},
                    }
                ],
                "usage": {"total_tokens": 100},
            }
        )
        with patch.object(provider, "read_key", return_value="test"):
            thread = chat.reply(
                self.store,
                self.token,
                {"text": "已完成 101、102 所有老人的喂药工作", "requestId": "round"},
                transport=transport,
            )
        msg = thread["messages"][-1]
        self.assertEqual(msg["action"]["kind"], "medicationRound")
        self.assertIn("101、102", msg["action"]["text"])
        for query in (
            "101房老人已经服药了吗？",
            "举例说明今天哪些老人已经服药",
            "如果101已经服药了怎么办",
        ):
            self.assertNotIn(
                "medicationRound",
                chat.permitted_actions(
                    self.owner, {"care": "照护"}, query, None
                ).values(),
            )
        audio = Mock(return_value=b"audio")
        payload = dict(
            requestId=msg["requestId"],
            part=0,
            scopeKey=thread["scopeKey"],
            generation=thread["generation"],
            region={},
        )
        with patch.object(read_aloud, "read_key", return_value="test"):
            with self.assertRaisesRegex(PermissionError, "按住说话"):
                read_aloud.listen(self.store, self.token, payload, transport=audio)
            with self.assertRaises(PermissionError):
                read_aloud.listen(
                    self.store,
                    self.token,
                    {**payload, "requestId": "unrelated"},
                    transport=audio,
                )
        audio.assert_not_called()

    def test_directory_snapshot_retains_relationship_until_365_days(self):
        with closing(self.store.connect()) as db, db:
            _, _, _, state, _ = chat_context.scope(self.store, db, self.token, {})
            person = next(r for r in state["residents"] if r.get("bedId"))
            phone = "13900007777"
            db.execute(
                "INSERT OR REPLACE INTO dossier_profiles VALUES(?,?,?)",
                (
                    person["id"],
                    "{}",
                    json.dumps(
                        {
                            "familyMembers": [
                                {
                                    "phone": phone,
                                    "name": "测试联系人",
                                    "relationship": "女儿",
                                }
                            ]
                        }
                    ),
                ),
            )
            lead_contacts.command(
                db,
                state,
                self.owner,
                "leads.register",
                dict(
                    campusId="campus-main", phone=phone, occurredAt=self.now.isoformat()
                ),
                self.now,
            )
            lead = state["leadContacts"][-1]
            lead_contacts.command(
                db,
                state,
                self.owner,
                "leads.archive",
                dict(leadId=lead["id"], feedback="接待完成"),
                self.now,
            )
            self.assertTrue(
                any(
                    r["relation"] == "女儿" and r["bed"]
                    for r in lead["directoryAtArchive"]
                )
            )
            person["bedId"] = ""
            self.assertEqual(lead_directory.expire(state, "2027-11-23"), 0)
            self.assertEqual(lead_directory.expire(state, "2027-11-24"), 1)
            view = {}
            lead_contacts.project(db, state, self.owner, view)
            self.assertTrue(lead_directory.matches_phone(lead, phone))
            self.assertNotIn(phone, json.dumps(lead))
            self.assertFalse(view["leadEvents"])
            self.assertFalse(view["leadContacts"])
