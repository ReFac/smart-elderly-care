"""Interruption, scoped resume and bounded fact checks for institutional briefs."""

from contextlib import closing
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from platform_core import provider
from platform_core.agents import brief_workflow
from platform_core.store import Store

PASSWORD = "synthetic-brief-test"


class BriefWorkflow(TestCase):
    def setUp(self):
        from provider_fixture import simulated_route

        self.enterContext(patch("platform_core.agents.narrative.route_domains", side_effect=simulated_route))
        folder = self.enterContext(TemporaryDirectory())
        self.path = Path(folder) / "facility.sqlite3"
        self.store = Store(self.path, initial_owner_password=PASSWORD)
        self.token, _ = self.store.login("owner", PASSWORD)
        self.payload = {"requestId": "brief-fixture", "goal": "复核护理和库存"}
        self.revision = self.store.version(self.token)["revision"]

    def start(self):
        self.store.execute("agent.start", self.payload, self.revision, self.token)

    def progress(self):
        return brief_workflow.progress(
            self.store, self.token, self.payload["requestId"]
        )

    def test_resume_after_process_failure_and_pending_approval(self):
        messages = []

        def fail_once(store, actor, request, topic, facts, **options):
            messages.append(topic)
            if len(messages) == 2:
                raise RuntimeError("synthetic service interruption")
            return "请核对本期记录。"

        with patch(
            "platform_core.provider.generation.summarize", side_effect=fail_once
        ):
            with self.assertRaises(RuntimeError):
                self.start()
            partial = self.progress()
            self.assertEqual(
                (partial["plan"], partial["completed"]),
                (["care", "inventory"], ["care"]),
            )
            self.assertEqual(self.store.version(self.token)["revision"], self.revision)
            self.store = Store(self.path)
            self.start()
        self.assertEqual(len(messages), 3)
        complete = self.progress()
        self.assertEqual(complete["status"], "awaiting_approval")
        run = self.store.agent_resource(self.token, "runs", complete["runId"])
        self.assertEqual(
            [e["agent"] for e in run["events"] if e["event"] == "step.resumed"],
            ["care"],
        )
        self.assertEqual(
            [a["reflection"]["outcome"] for a in run["artifacts"]],
            ["accepted", "accepted"],
        )

    def test_one_correction_per_domain_falls_back_to_verified_evidence(self):
        self.payload["scope"] = "inventory"
        with patch(
            "platform_core.provider.generation.summarize",
            side_effect=["已下发 999998 项。", "已扣款 999998 元。"],
        ) as remote:
            self.start()
        self.assertEqual(remote.call_count, 2)
        first, corrected = remote.call_args_list
        self.assertNotEqual(first.args[2], corrected.args[2])
        artifact = self.store.agent_resource(
            self.token, "runs", self.progress()["runId"]
        )["artifacts"][0]
        self.assertEqual(artifact["reflection"]["outcome"], "evidence_only")
        self.assertEqual(artifact["reflection"]["attempts"], 2)
        self.assertIn("unsupported_number", artifact["reflection"]["remaining"])
        self.assertNotIn("999998", artifact["detail"])
        self.assertTrue(artifact["evidence"])

    def test_accepted_correction_is_labeled_and_stays_pending(self):
        self.payload["scope"] = "care"
        with patch(
            "platform_core.provider.generation.summarize",
            side_effect=["已派发工单。", "请核对工单原件。"],
        ):
            self.start()
        complete = self.progress()
        self.assertEqual(complete["status"], "awaiting_approval")
        artifact = self.store.agent_resource(self.token, "runs", complete["runId"])[
            "artifacts"
        ][0]
        self.assertEqual(artifact["reflection"]["outcome"], "corrected")
        self.assertNotIn("已派发", artifact["detail"])

    def test_stale_source_requires_a_new_request_before_any_more_generation(self):
        with (
            patch(
                "platform_core.provider.generation.summarize",
                side_effect=RuntimeError("interrupted"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.start()
        with closing(self.store.connect()) as db, db:
            db.execute("UPDATE workspace SET revision=revision+1")
        self.revision = self.store.version(self.token)["revision"]
        self.assertEqual(self.progress()["status"], "stale")
        with (
            patch("platform_core.provider.generation.summarize") as generate,
            self.assertRaisesRegex(ValueError, "新请求"),
        ):
            self.start()
        generate.assert_not_called()

    def test_wrong_units_and_unverified_actions_are_flagged(self):
        self.assertEqual(
            brief_workflow.issues("应收 12 元。", [{"records": 1, "value": "12 元"}]),
            [],
        )
        self.assertIn(
            "unsupported_number",
            brief_workflow.issues(
                "应收 12 万元。", [{"records": 12, "value": "12 元"}]
            ),
        )
        self.assertIn(
            "action_claim", brief_workflow.issues("已开药。", [{"records": 2}])
        )

    def test_correction_uses_distinct_metered_receipts_without_charging_a_replay(self):
        self.payload["scope"] = "inventory"
        self.enterContext(
            patch.dict(
                "os.environ",
                DEEPSEEK_API_KEY="synthetic-key",
                NH_CHAT_PROVIDER="deepseek",
            )
        )
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "fixture", 100_000, "2099-12-31")

        def completion(text):
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps({"text": text}, ensure_ascii=False)
                        },
                    }
                ],
                "usage": {"total_tokens": 20},
            }

        with patch(
            "platform_core.provider.completions.send",
            side_effect=[
                completion("已扣款 999999 元。"),
                completion("请核对物资记录。"),
            ],
        ) as call:
            self.start()
            self.revision = self.store.version(self.token)["revision"]
            self.start()
        self.assertEqual(call.call_count, 2)
        with closing(self.store.connect()) as db:
            rows = db.execute(
                "SELECT request,charged,status FROM api_usage WHERE feature='agent.specialist.inventory'"
            ).fetchall()
        self.assertEqual(len({row[0] for row in rows}), 2)
        self.assertEqual(sum(row[1] for row in rows), 40)
        self.assertTrue(all(row[2] == "ok" for row in rows))
