"""A room Agent proposes, and only the existing human confirmation executes the task."""

from copy import deepcopy
import sqlite3
import unittest

from platform_core import care, facility, gateways
from platform_core.room_context import PROPOSAL_PATH, room_context, validate_proposal

TODAY = "2026-11-24"


class RoomContext(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.state = care.seed(TODAY)
        self.owner = {"id": "operator", "kind": "owner", "displayName": "平台"}
        self.staff = {
            "id": "nurse-A",
            "kind": "staff",
            "displayName": "护士甲",
            "permissions": ["assistants", "care", "voice"],
        }
        self.reviewer = {
            "id": "nurse-B",
            "kind": "staff",
            "displayName": "护士乙",
            "permissions": ["care", "voice.confirm"],
        }
        with self.db:
            facility.init(self.db, self.state)
            gateways.init(self.db)
        rooms = facility.floor(self.db, self.state, self.owner, "floor-1")["rooms"]
        self.room, self.other = rooms[0]["id"], rooms[1]["id"]
        self.rid = facility.scope(self.db, self.state, self.staff, roomId=self.room)[
            "residentIds"
        ][0]
        outside = facility.scope(self.db, self.state, self.staff, roomId=self.other)[
            "residentIds"
        ][0]
        template = self.state["tasks"][0]
        self.state["tasks"] = [
            {
                **template,
                "id": "overdue",
                "residentId": self.rid,
                "date": "2026-11-20",
                "status": "待执行",
            },
            {
                **template,
                "id": "today",
                "residentId": self.rid,
                "date": TODAY,
                "status": "待执行",
            },
            {
                **template,
                "id": "future",
                "residentId": self.rid,
                "date": "2026-11-25",
                "status": "待执行",
            },
            {
                **template,
                "id": "done",
                "residentId": self.rid,
                "date": TODAY,
                "status": "已完成",
            },
            {
                **template,
                "id": "elsewhere",
                "residentId": outside,
                "date": TODAY,
                "status": "待执行",
            },
        ]
        self.payload = {
            "roomId": self.room,
            "taskId": "today",
            "note": "已核对本次执行结果",
            "requestId": "draft-17",
        }

    def read(self, user=None, **params):
        return room_context(
            self.db,
            self.state,
            user or self.staff,
            {"roomId": self.room, **params},
            TODAY,
        )

    def validated(self, user=None, **fields):
        return validate_proposal(
            self.db, self.state, user or self.staff, {**self.payload, **fields}, TODAY
        )

    def apply(self, action, payload, actor):
        with self.db:
            return gateways.apply(self.db, self.state, action, payload, actor, TODAY)

    def test_discovery_returns_only_eligible_current_room_targets_in_due_order(self):
        first = self.read(limit="1")
        self.assertEqual([t["id"] for t in first["targets"]], ["overdue"])
        self.assertEqual(first["nextOffset"], 1)
        last = self.read(limit=1, offset=first["nextOffset"])
        self.assertEqual([t["id"] for t in last["targets"]], ["today"])
        self.assertIsNone(last["nextOffset"])
        target = last["targets"][0]
        self.assertEqual(target["proposalPath"], PROPOSAL_PATH)
        self.assertTrue(target["requiresHumanConfirmation"])
        for restricted in ("note", "transcript", "residentName", "medical", "assignee"):
            self.assertNotIn(restricted, target)
        self.assertEqual(self.read(offset=42)["targets"], [])
        for bad in (True, -1, 1.3, "22.0", {}, 100):
            with self.assertRaises(ValueError):
                self.read(limit=bad)
        without_card = deepcopy(self.state)
        without_card["bedMoves"] = []
        self.assertEqual(
            room_context(
                self.db, without_card, self.staff, {"roomId": self.room}, TODAY
            )["targets"],
            [],
        )

    def test_role_and_geographical_boundaries_are_checked_at_read_and_write(self):
        for grants in (
            ["care", "voice"],
            ["assistants", "care"],
            ["assistants", "residents", "voice"],
        ):
            user = {**self.staff, "permissions": grants}
            self.assertFalse(self.read(user)["targets"])
            with self.assertRaises(PermissionError):
                self.validated(user)
        restricted = {**self.staff, "facilityScope": {"roomIds": [self.other]}}
        with self.assertRaises(FileNotFoundError):
            self.read(restricted)
        with self.assertRaises(FileNotFoundError):
            self.validated(restricted)
        for target in ("future", "done", "elsewhere", "missing"):
            with self.assertRaises(FileNotFoundError):
                self.validated(taskId=target)
        for extras in (
            {"role": "owner"},
            {"targetAction": "ops.pay"},
            {"region": {"roomId": self.room}},
            {"apiKey": "client-supplied"},
            {"transcript": "替换原文"},
            {"residentId": self.rid},
        ):
            with self.assertRaises(ValueError):
                self.validated(**extras)

    def test_same_proposal_retries_before_and_after_only_one_human_confirmation(self):
        payload = self.validated()
        self.assertIn("区域 Agent 草稿", payload["transcript"])
        self.assertEqual(payload["targetAction"], "care.completeTask")
        self.assertNotIn("roomId", payload)
        before = deepcopy(self.state["tasks"])
        self.apply("gw.propose", payload, self.staff)
        self.assertEqual(before, self.state["tasks"])
        self.assertEqual([t["id"] for t in self.read()["targets"]], ["overdue"])
        self.assertEqual(self.validated(), payload)
        self.apply("gw.propose", self.validated(), self.staff)
        pending = gateways.project(self.db, {}, self.reviewer)["voiceQueue"]
        self.assertEqual(len(pending), 1)
        other_staff = {**self.staff, "id": "nurse-C"}
        with self.assertRaises(ValueError):
            self.validated(other_staff, requestId="r2")
        with self.assertRaises(ValueError):
            self.validated(note="更换记录")
        with self.assertRaises(ValueError):
            self.validated(roomId=self.other)
        self.apply("gw.confirm", {"proposalId": pending[0]["id"]}, self.reviewer)
        self.assertEqual(self.state["tasks"][1]["status"], "已完成")
        self.assertEqual(self.state["tasks"][1]["operatorId"], self.reviewer["id"])
        self.apply("gw.propose", self.validated(), self.staff)
        self.assertFalse(gateways.project(self.db, {}, self.reviewer)["voiceQueue"])
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM gateway_voice").fetchone()[0], 1
        )


if __name__ == "__main__":
    unittest.main()
