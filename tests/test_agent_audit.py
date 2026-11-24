"""Room history and live grants for the general audit view of Agent work."""

from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from platform_core import activity
from platform_core.store import Store


class AgentAuditTests(unittest.TestCase):
    password = "local-audit-fixture!"

    def setUp(self):
        from provider_fixture import simulate_narration

        simulate_narration(self)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "audit.sqlite"
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": self.password}):
            self.store = Store(self.path)
        self.owner, _ = self.store.login("owner", self.password)

    def execute(self, token, action, **payload):
        return self.store.execute(
            action, payload, self.store.version(token)["revision"], token
        )

    def staff(self, name, *grants):
        self.execute(
            self.owner,
            "access.create",
            kind="staff",
            username=name,
            displayName=name,
            password=self.password,
            role="自定义",
            permissions=["audit", "assistants", *grants],
        )
        return self.store.login(name, self.password)

    def start(self, token, request, goal, **payload):
        self.execute(token, "agent.start", goal=goal, requestId=request, **payload)
        return self.store.agent_resource(token, "runs")["runs"][0]["id"]

    def agent_logs(self, token, **filters):
        return [
            r
            for r in self.store.activity(token, **filters)["rows"]
            if r["action"].startswith("agent.")
        ]

    def test_single_resident_remains_in_original_room_after_transfer_and_owner_confirmation(
        self,
    ):
        staff, _ = self.staff("audit-care", "care")
        rid = "r001"
        data = self.store.snapshot(self.owner)["data"]
        original_room = activity.for_person(data, rid)["room"]
        new_bed = next(
            b
            for b in data["beds"]
            if b["status"] == "空闲"
            and not original_room.endswith(b["label"].rsplit("-", 1)[0])
        )
        run = self.start(staff, "move", "核对照护工单", residentId=rid, room="伪造房间")
        self.execute(self.owner, "care.transfer", residentId=rid, bedId=new_bed["id"])
        self.store = Store(self.path)
        self.execute(
            self.owner, "agent.publish", runId=run, residentId="r002", room="伪造房间"
        )
        rows = self.agent_logs(staff, room=original_room)
        self.assertEqual([r["action"] for r in rows], ["agent.publish", "agent.start"])
        self.assertTrue(
            all(r["residentId"] == rid and r["agentRunId"] == run for r in rows)
        )
        self.assertEqual(rows[0]["actorLogin"], "owner")
        current_room = activity.for_person(
            self.store.snapshot(self.owner)["data"], rid
        )["room"]
        self.assertNotEqual(current_room, original_room)
        self.assertFalse(self.agent_logs(staff, room=current_room))
        self.assertFalse(self.agent_logs(staff, room="伪造房间"))
        self.assertEqual(self.agent_logs(staff, actor="audit-care"), rows[1:])

    def test_cross_domain_and_unscoped_runs_remain_institutional_and_restrict_auditors(
        self,
    ):
        actor, user = self.staff("audit-person", "care", "inventory")
        peer, _ = self.staff("audit-peer", "care", "inventory")
        mixed = self.start(actor, "mixed", "护理和库存", residentId="r001")
        self.execute(actor, "agent.cancel", runId=mixed, residentId="r001")
        whole = self.start(actor, "whole", "全院照护")
        self.assertFalse(self.agent_logs(peer))
        rows = self.agent_logs(actor)
        self.assertTrue(all(r["room"] == r["residentId"] == "" for r in rows))
        self.assertEqual({r["agentRunId"] for r in rows}, {mixed, whole})
        self.execute(
            self.owner,
            "access.update",
            id=user["id"],
            permissions=["assistants", "care", "audit"],
        )
        self.assertEqual([r["agentRunId"] for r in self.agent_logs(actor)], [whole])
        self.assertEqual(
            [r["agentRunId"] for r in self.store.snapshot(actor)["audit"]], [whole]
        )
        self.assertEqual(len(self.agent_logs(self.owner)), 3)

    def test_unlinked_legacy_agent_events_are_private_to_owner(self):
        staff, user = self.staff("audit-legacy", "care")
        with closing(self.store.connect()) as db, db:
            db.execute(
                "INSERT INTO audit(revision,at,action,summary,actorId,room) VALUES(?,?,?,?,?,?)",
                (-5, "2025-01-02", "agent.start", "旧版记录", user["id"], "旧房间"),
            )
        self.store = Store(self.path)
        self.assertFalse(self.agent_logs(staff, room="旧房间"))
        self.assertEqual(
            self.agent_logs(self.owner, room="旧房间")[0]["summary"], "旧版记录"
        )


if __name__ == "__main__":
    unittest.main()
