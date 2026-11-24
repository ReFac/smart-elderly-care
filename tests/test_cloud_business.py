"""Cloud generation and local invariants are independent, authenticated operations."""

from contextlib import closing, redirect_stdout, redirect_stderr
from datetime import datetime, timedelta
from io import BytesIO, StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import manage_plan

from platform_core import provider
from platform_core.agents import change_review
from platform_core.provider import generation
from platform_core.store import Store, TIMEZONE


class CloudBusinessTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        env = patch.dict(
            "os.environ",
            {
                "DEEPSEEK_API_KEY": "fixture-only",
                "NH_OWNER_PASSWORD": "synthetic-cloud-only",
            },
        )
        env.start()
        self.addCleanup(env.stop)
        self.store = Store(
            Path(folder.name) / "site.db",
            lambda: datetime(2026, 11, 24, 17, 0, tzinfo=TIMEZONE),
        )
        self.token, self.owner = self.store.login("owner", "synthetic-cloud-only")

    def grant(self):
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "synthetic", 50000, "2026-12-01", self.store.now())

    def send(self, action, fields):
        return self.store.execute(
            action, fields, self.store.version(self.token)["revision"], self.token
        )

    def reply(self, key, body, **options):
        self.assertEqual(key, "fixture-only")
        self.assertEqual(body["model"], "deepseek-flash")
        # Obtain an exclusive writer lock while the real transport would be waiting.
        with closing(self.store.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
        return {
            "usage": {"total_tokens": 58},
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": '{"text":"本次测试由云端返回。"}'},
                }
            ],
        }

    def test_legacy_business_endpoints_never_answer_from_local_rules_on_outage(self):
        fields = {
            "goal": "库存与护理",
            "requestId": "disabled-local-option",
            "planning": "local",
        }
        with self.assertRaisesRegex(ValueError, "套餐"):
            self.send("agent.start", fields)
        self.assertEqual(self.store.agent_resource(self.token, "runs")["runs"], [])
        self.grant()
        with patch(
            "platform_core.provider.deepseek.send", side_effect=self.reply
        ) as transport:
            self.send("agent.start", fields)
            self.assertEqual(transport.call_count, 2)
            record = self.store.agent_resource(self.token, "runs")["runs"][0]
            result = self.store.agent_resource(self.token, "runs", record["id"])
            self.assertTrue(
                all(
                    x["detail"].startswith("本次测试由云端返回。")
                    and x["source"] == "deepseek"
                    for x in result["artifacts"]
                )
            )
            self.send("agent.start", fields)
            self.assertEqual(transport.call_count, 2)
            self.send("ops.suggest", {"category": "运营分析"})
            self.assertEqual(transport.call_count, 3)
            prompts = str(transport.call_args_list)
            self.assertNotIn("residentId", prompts)
            self.assertNotIn("password_hash", prompts)

    def test_check_receipt_is_queued_and_account_data_never_leaves_workspace(self):
        self.grant()
        receipt = self.send(
            "ops.addItem",
            {"name": "合成纱布", "category": "护理耗材", "unit": "包", "minimum": 5},
        )
        rev = receipt["revision"]
        self.assertEqual(
            self.store.history_change(self.token, rev)["agentReview"]["status"],
            "pending",
        )
        with patch(
            "platform_core.provider.deepseek.send", side_effect=self.reply
        ) as transport:
            self.assertEqual(change_review.process_pending(self.store, Event()), 1)
            self.assertEqual(change_review.process_pending(self.store, Event()), 0)
            facts = json.loads(transport.call_args.args[1]["messages"][1]["content"])[
                "facts"
            ]
            self.assertEqual(set(facts), {"domain", "action", "checks"})
            self.assertNotIn("合成纱布", str(facts))
        resolved = self.store.history_change(self.token, rev)["agentReview"]
        self.assertEqual(
            (resolved["status"], resolved["provider"]), ("reviewed", "deepseek")
        )

    def test_care_and_clinical_cloud_prompts_and_responses_stay_separate(self):
        self.grant()
        self.send(
            "access.create",
            {
                "username": "cloud-carer",
                "kind": "staff",
                "displayName": "护工测试",
                "role": "护工",
                "password": "test-cloud-carer-only",
                "permissions": ["care"],
            },
        )
        token, _ = self.store.login("cloud-carer", "test-cloud-carer-only")
        url = "/api/rounds/residents/r001"

        def generate(actor):
            return self.store.rounds.write(
                actor,
                url + "/generate",
                {"revision": self.store.version(actor)["revision"]},
            )["latest"]

        # Only a reviewed, attributable change is eligible for the clinical section.
        self.send(
            "care.resolveVital",
            {
                "vitalId": self.store.snapshot(self.token)["data"]["vitals"][0]["id"],
                "operator": "值班护士",
                "note": "已现场复核",
            },
        )

        def structure(key, body, **options):
            facts = json.loads(body["messages"][1]["content"])["事实"]
            reply = self.reply(key, body, **options)
            reply["choices"][0]["message"]["content"] = json.dumps(
                {"paragraphs": [[i] for i in range(1, len(facts) + 1)]}
            )
            return reply

        with patch(
            "platform_core.provider.deepseek.send", side_effect=structure
        ) as transport:
            carer = generate(token)
            self.assertIsNone(carer["cough"])
            self.assertEqual(transport.call_count, 1)
            facts = transport.call_args.args[1]["messages"][1]["content"]
            for forbidden in ("r001", "planned", "体温", "咳嗽", "值班护士"):
                self.assertNotIn(forbidden, facts)
            clinical = generate(self.token)
            self.assertEqual(transport.call_count, 2)
            facts = transport.call_args.args[1]["messages"][1]["content"]
            self.assertIn("体温", facts)
            self.assertNotIn("咳嗽", facts)
            self.assertNotIn("r001", facts)
            self.assertTrue(
                any(
                    row["source"] == "deepseek" and row["permission"] == "clinical"
                    for row in clinical["changes"]
                )
            )
            carer = generate(token)
            self.assertEqual(transport.call_count, 2)
            self.assertTrue(
                all(
                    x["permission"] == "care"
                    for x in carer["changes"] + carer["suggestions"]
                )
            )
            self.assertNotIn("体温", str(carer))

    def test_retry_cache_actual_usage_and_indeterminate_billing(self):
        self.grant()
        replies = [
            dict(usage={"total_tokens": 41}, choices=[]),
            self.reply("fixture-only", {"model": "deepseek-flash"}),
        ]
        with patch("platform_core.provider.deepseek.send", side_effect=replies) as send:

            def call():
                return generation.summarize(
                    self.store, "synthetic", "once", "库存", {"out": 4}
                )

            with self.assertRaisesRegex(ValueError, "未能完成"):
                call()
            self.assertEqual(call(), call())
            self.assertEqual(send.call_count, 2)
            with closing(self.store.connect()) as db:
                self.assertEqual(provider.usage(db, provider.latest(db)["id"]), (99, 0))
        with patch(
            "platform_core.provider.deepseek.send", side_effect=TimeoutError()
        ) as timed:
            for _ in range(2):
                with self.assertRaises(ValueError):
                    generation.summarize(
                        self.store, "synthetic", "ambiguous", "库存", {"out": 6}
                    )
            self.assertEqual(timed.call_count, 1)

    def test_late_usage_after_manual_settlement_is_visible_and_reconciled_once(self):
        self.grant()

        def transport(key, body, **options):
            with closing(self.store.connect()) as db, db:
                actor, request = db.execute(
                    "SELECT actor,request FROM api_usage WHERE status='pending'"
                ).fetchone()
                provider.reconcile(
                    db, actor, request, 17, self.store.now() + timedelta(minutes=3)
                )
            return self.reply(key, body, **options)

        def run():
            return generation.summarize(
                self.store, "one", "same-key", "日常", {"change": 1}
            )

        def cli(*args):
            output = StringIO()
            with (
                patch(
                    "sys.argv", ["manage_plan.py", "--db", str(self.store.path), *args]
                ),
                redirect_stdout(output),
                redirect_stderr(output),
            ):
                code = manage_plan.main()
            return code, output.getvalue()

        with patch(
            "platform_core.provider.deepseek.send", side_effect=transport
        ) as send:
            with self.assertRaisesRegex(ValueError, "对账"):
                run()
            with self.assertRaisesRegex(ValueError, "等待核对"):
                run()
            self.assertEqual(send.call_count, 1)
        code, raw = cli("unsettled")
        self.assertEqual(code, 0)
        (row,) = json.loads(raw)
        self.assertEqual(
            (
                row["status"],
                row["originalTokens"],
                row["reportedTokens"],
                row["differenceTokens"],
            ),
            ("late_receipt", 17, 58, 41),
        )
        with closing(self.store.connect()) as db, db:
            provider.late_usage(db, row["actor"], row["request"], 58, self.store.now())
            self.assertEqual(provider.usage(db, row["planId"]), (17, 41))
        args = (
            "reconcile",
            "--actor",
            row["actor"],
            "--request",
            row["request"],
            "--tokens",
            "58",
        )
        self.assertEqual(cli(*args)[0], 0)
        self.assertEqual(cli(*args)[0], 1)
        self.assertEqual(json.loads(cli("unsettled")[1]), [])
        with closing(self.store.connect()) as db, db:
            provider.late_usage(db, row["actor"], row["request"], 58, self.store.now())
            self.assertEqual(provider.usage(db, row["planId"]), (58, 0))
            self.assertEqual(
                db.execute("SELECT charged FROM api_usage").fetchone()[0], 17
            )
            self.assertEqual(
                tuple(
                    db.execute(
                        "SELECT original,reported,verified FROM api_late_usage"
                    ).fetchone()
                ),
                (17, 58, 58),
            )
            self.assertEqual(
                db.execute("SELECT count(*) FROM cloud_generation_results").fetchone()[
                    0
                ],
                0,
            )

    def test_definite_provider_rejection_releases_reservation_and_can_credit_an_overpayment(
        self,
    ):
        self.grant()

        def reject(key, body, **options):
            raise HTTPError(
                "https://api.deepseek.com", 413, "Payload Too Large", {}, BytesIO()
            )

        with patch("platform_core.provider.deepseek.send", side_effect=reject):
            with self.assertRaisesRegex(ValueError, "未能完成"):
                generation.summarize(self.store, "one", "oversize", "库存", {"test": 1})
        with closing(self.store.connect()) as db, db:
            row = db.execute("SELECT * FROM api_usage").fetchone()
            self.assertEqual(
                (row["status"], row["charged"], row["reason"]),
                ("closed", 0, "provider_rejected"),
            )
            self.assertEqual(provider.usage(db, row["planId"]), (0, 0))
            db.execute("UPDATE api_usage SET reason='reconciled',charged=29")
            provider.late_usage(db, row["actor"], row["request"], 0, self.store.now())
            self.assertFalse(provider.unsettled(db))
            provider.late_usage(
                db,
                row["actor"],
                row["request"],
                0,
                self.store.now(),
                confirmed_zero=True,
            )
            self.assertEqual(provider.unsettled(db)[0]["differenceTokens"], -29)
            self.assertEqual(provider.usage(db, row["planId"]), (29, 0))
            provider.reconcile(db, row["actor"], row["request"], 0, self.store.now())
            self.assertEqual(provider.usage(db, row["planId"]), (0, 0))
