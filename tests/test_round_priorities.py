from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from platform_core import provider
from platform_core.provider import generation, round_priorities as priorities
from platform_core.store import Store, TIMEZONE
from provider_fixture import isolate_credentials


class PriorityTests(unittest.TestCase):
    def setUp(self):
        from provider_fixture import simulate_narration

        simulate_narration(self)
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        isolate_credentials(self, tmp.name)
        env = patch.dict(
            "os.environ",
            {
                "DEEPSEEK_API_KEY": "test-only",
                "NH_OWNER_PASSWORD": "test-only-long-password",
            },
        )
        env.start()
        self.addCleanup(env.stop)
        now = datetime(2026, 11, 24, 10, 0, tzinfo=TIMEZONE)
        self.store = Store(Path(tmp.name) / "care.sqlite3", lambda: now)
        self.token, _ = self.store.login("owner", "test-only-long-password")
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "test", 4000, "2026-12-01", now)
            revision, state = db.execute(
                "SELECT revision,data FROM workspace"
            ).fetchone()
            workspace = json.loads(state)
            workspace["tasks"] = [
                {
                    "id": "private-task-" + str(i),
                    "residentId": "r001",
                    "date": "2026-11-24",
                    "title": "PRIVATE TEXT",
                    "status": status,
                    "time": time,
                    "assignee": "PRIVATE NAME",
                }
                for i, (time, status) in enumerate(
                    [("09:00", "待执行"), ("15:00", "待执行"), ("08:00", "已完成")]
                )
            ]
            db.execute("UPDATE workspace SET data=?", (json.dumps(workspace),))
        result = self.store.rounds.write(
            self.token, "/api/rounds/residents/r001/generate", {"revision": revision}
        )
        self.payload = {
            "revision": result["revision"],
            "reportId": result["latest"]["id"],
            "confirmed": True,
        }

    def test_minimized_prompt_deduplicates_and_preserves_checks(self):
        transport = Mock(
            return_value={
                "usage": {"total_tokens": 44},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"ids":["upcoming","past_due","completed"]}'},
                    }
                ],
            }
        )
        result = priorities.generate(
            self.store, self.token, "r001", self.payload, transport=transport
        )
        self.assertEqual(
            result["items"],
            [priorities.CHECKS[k] for k in ("upcoming", "past_due", "completed")],
        )
        self.assertEqual(
            priorities.generate(
                self.store, self.token, "r001", self.payload, transport=transport
            ),
            result,
        )
        self.assertEqual(transport.call_count, 1)
        body = transport.call_args.args[1]
        self.assertEqual(
            json.loads(body["messages"][1]["content"]),
            ["past_due", "upcoming", "completed"],
        )
        self.assertNotIn("PRIVATE", json.dumps(body))
        with closing(self.store.connect()) as db:
            self.assertEqual(provider.usage(db, provider.latest(db)["id"]), (44, 0))

    def test_unlimited_site_keeps_receipts_for_routing_narratives_and_care_checks(self):
        def completion(payload, tokens):
            return {
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(payload)}}],
                "usage": {"total_tokens": tokens},
            }

        with closing(self.store.connect()) as db, db:
            # Model an existing site's exhausted subscription from the preceding day.
            plan_id = provider.latest(db)["id"]
            db.execute("""UPDATE api_plans SET startsOn='2026-11-01', expiresOn='2026-11-23',
                          tokenLimit=45 WHERE id=?""", (plan_id,))
            db.execute("""INSERT INTO api_usage(actor,request,planId,fingerprint,model,createdAt,
                          status,allowance,charged,feature) VALUES('worker','past',?,'past','test',0,
                          'ok',45,45,'care.roundNarrative')""", (plan_id,))
            provider.allow_unlimited(db, self.store.now())

        routed = provider.plan(
            self.store.connect, lambda db: self.store.actor(db, self.token),
            "护理交班", "staff-routing", now=self.store.now(),
            transport=Mock(return_value=completion({"ids": ["care"]}, 30)),
        )
        self.assertEqual(routed["specialistIds"], ["care"])
        with patch.object(generation.completions, "send", return_value=completion({"text": "待交班"}, 32)):
            summary = generation.generate(
                self.store, "rounds-agent", "daily", "汇总护理交班情况", {"待核对": 2},
                generation.narrative, feature="care.roundNarrative",
            )
        self.assertEqual(summary, {"text": "待交班"})
        ranked = priorities.generate(
            self.store, self.token, "r001", self.payload,
            transport=Mock(return_value=completion({"ids": ["past_due", "upcoming", "completed"]}, 34)),
        )
        self.assertEqual(ranked["status"], "ok")
        with closing(self.store.connect()) as db:
            self.assertEqual(provider.usage(db, plan_id), (141, 0))
            receipts = db.execute("""SELECT feature,charged,status FROM api_usage
                                     WHERE planId=? AND request!='past' ORDER BY feature""", (plan_id,))
            self.assertEqual([tuple(row) for row in receipts], [
                ("agent.routing", 30, "ok"), ("care.roundNarrative", 32, "ok"),
                ("care.roundPriorities", 34, "ok"),
            ])

    def test_missing_check_does_not_become_a_locally_completed_ai_ranking(self):
        response = {
            "choices": [{"finish_reason": "stop", "message": {"content": '{"ids":["upcoming"]}'}}],
            "usage": {"total_tokens": 26},
        }
        result = priorities.generate(self.store, self.token, "r001", self.payload, transport=Mock(return_value=response))
        self.assertEqual((result["items"], result["reason"]), ([], "invalid_output"))


    def test_old_report_separates_unranked_business_checks_from_the_model_response(self):
        report_id = self.payload["reportId"]
        with closing(self.store.connect()) as db, db:
            db.execute("INSERT INTO rounds_priorities VALUES (?,?,?,?,?)", (report_id, "legacy", "rank", "2026-11-24", ""))
            db.execute("""INSERT INTO api_usage(actor,request,planId,fingerprint,model,createdAt,status,
                allowance,specialistIds) VALUES('legacy','rank',?,'fixture','fixture',0,'ok',100,'["upcoming"]')""",
                (provider.latest(db)["id"],))
        saved = priorities.read(self.store, self.token, "r001", report_id)
        self.assertEqual(saved["items"], [priorities.CHECKS["upcoming"]])
        self.assertEqual(saved["unrankedItems"], [priorities.CHECKS["past_due"], priorities.CHECKS["completed"]])


    def test_requires_consent_and_rejects_unapproved_output(self):
        transport = Mock(
            return_value={
                "usage": {"total_tokens": 35},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"ids":["DOSE"]}'},
                    }
                ],
            }
        )
        with self.assertRaises(ValueError):
            priorities.generate(
                self.store,
                self.token,
                "r001",
                {**self.payload, "confirmed": False},
                transport=transport,
            )
        transport.assert_not_called()
        result = priorities.generate(
            self.store, self.token, "r001", self.payload, transport=transport
        )
        self.assertEqual((result["items"], result["reason"]), ([], "invalid_output"))
