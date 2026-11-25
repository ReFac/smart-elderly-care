"""A resident's local Agent output is a draft and cites only registered inputs."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from platform_core.agents import runtime
from platform_core.agents.contracts import CARE_PLAN_TOOL
from platform_core.store import Store


class CarePlanDraftTests(unittest.TestCase):
    def setUp(self):
        from provider_fixture import simulate_narration

        simulate_narration(self)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        passwd = "plan-test-owner-95"
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": passwd}):
            self.store = Store(Path(temp.name) / "care.db")
        self.owner, _ = self.store.login("owner", passwd)
        self.rid = "r001"
        self.day = self.store.version(self.owner)["today"]

    def call(self, action, p):
        return self.store.execute(
            action, p, self.store.version(self.owner)["revision"], self.owner
        )

    def data(self):
        return self.store.snapshot(self.owner)["data"]

    def test_generated_and_published_draft_never_dispatches(self):
        self.call(
            "care.assess",
            {
                "residentId": self.rid,
                "level": "半失能",
                "note": "隐私备忘",
                "assignee": "跟进人员甲",
                "observations": {"生活起居": "需协助", "日常沟通": "待观察"},
            },
        )
        state = self.data()
        care = [r for r in state["assessments"] if r["residentId"] == self.rid][-1]
        plan = [r for r in state["plans"] if r.get("assessmentId") == care["id"]][-1]

        def start(rid):
            self.call(
                "agent.start",
                {
                    "goal": "根据档案生成健康照护计划",
                    "residentId": rid,
                    "requestId": "personal-plan",
                    "scope": "care",
                },
            )

        with self.assertRaisesRegex(ValueError, "请先选择一位长辈"):
            start("")
        start(self.rid)
        action = self.data()["agentRuns"][0]
        view = self.store.agent_resource(self.owner, "runs", action["id"])
        artifact = view["artifacts"][0]
        self.assertEqual(artifact["tool"], "care.planDraft")
        self.assertEqual(view["status"], "awaiting_approval")
        for content in (
            "生活起居",
            "日常沟通",
            "起居照护协助",
            "跟进人员甲",
            care["reviewDate"],
        ):
            self.assertIn(content, artifact["detail"])
        self.assertNotIn("隐私备忘", json.dumps(artifact, ensure_ascii=False))
        self.assertIn(
            plan["id"],
            next(
                e["recordIds"] for e in artifact["evidence"] if e["source"] == "plans"
            ),
        )
        self.call("agent.publish", {"runId": action["id"]})
        sug = next(
            s for s in self.data()["suggestions"] if s.get("runId") == action["id"]
        )
        self.call(
            "ops.review",
            {"id": sug["id"], "decision": "采纳", "note": "已核对本人评估"},
        )
        after = self.data()
        for key in ("plans", "tasks", "residents", "assessments"):
            self.assertEqual(state[key], after[key])
        self.call("ops.suggest", {"residentId": self.rid, "category": "日常照护"})
        self.assertEqual(self.data()["suggestions"][0]["detail"], artifact["detail"])

    def test_input_minimization_and_region_boundary(self):
        state = self.data()
        originals = deepcopy(state)
        view = runtime.scoped_records(state, CARE_PLAN_TOOL, self.rid, {self.rid})
        self.assertTrue(all(r["id"] == self.rid for r in view["residents"]))
        for key in ("assessments", "plans", "tasks"):
            self.assertTrue(all(r["residentId"] == self.rid for r in view[key]))
        self.assertEqual(view["residents"][0].keys(), {"id", "name", "status", "level"})
        for r in view["assessments"]:
            self.assertFalse(
                {"note", "observations", "scale", "assessors", "contact"} & r.keys()
            )
        empty = runtime.scoped_records(state, CARE_PLAN_TOOL, "r002", {self.rid})
        self.assertTrue(all(not rows for rows in empty.values()))
        self.assertEqual(state, originals)


if __name__ == "__main__":
    unittest.main()
