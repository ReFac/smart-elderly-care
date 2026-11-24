from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from platform_core.store import Store, TIMEZONE


class TrialFollowupTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.now = datetime(2026, 11, 24, 10, tzinfo=TIMEZONE)
        self.store = Store(
            Path(temp.name) / "trial.db",
            lambda: self.now,
            initial_owner_password="trial-test-only",
        )
        self.owner, _ = self.store.login("owner", "trial-test-only")
        self.staff = []
        for username in ("worker1", "worker2"):
            self.save(
                "access.create",
                {
                    "kind": "staff",
                    "role": "自定义",
                    "permissions": ["residents"],
                    "displayName": username,
                    "username": username,
                    "password": "testing-12345",
                },
            )
            token, user = self.store.login(username, "testing-12345")
            self.staff.append((token, user["id"]))

    def save(self, action, fields, token=None):
        token = token or self.owner
        return self.store.execute(
            action, fields, self.store.version(token)["revision"], token
        )

    def state(self, token=None):
        return self.store.snapshot(token or self.owner)["data"]

    def trial(self):
        self.save("access.trialSettings", {"days": 3, "fee": 256.50})
        self.save("care.register", {"name": "入住演练"})
        state = self.state()
        rid = state["residents"][-1]["id"]
        bed = next(b["id"] for b in state["beds"] if b["status"] == "空闲")
        self.save("care.admit", {"residentId": rid, "bedId": bed, "stayType": "trial"})
        return rid, bed

    def test_failed_stay_dispatch_and_signed_report_use_one_employee_identity(self):
        rid, bed = self.trial()
        token, aid = self.staff[0]
        other, bid = self.staff[1]
        payload = {
            "residentId": rid,
            "reason": "回家与亲属居住",
            "assigneeId": aid,
            "dueDate": "2026-11-27",
        }
        for bad in (
            {**payload, "assigneeId": "unknown"},
            {**payload, "dueDate": "2026-11-23"},
        ):
            with self.assertRaises(ValueError):
                self.save("care.endTrial", bad)
        self.assertEqual(
            next(b for b in self.state()["beds"] if b["id"] == bed)["residentId"], rid
        )
        self.assertFalse(self.state()["trialFollowups"])
        self.save("care.endTrial", payload)
        with self.assertRaises(ValueError):
            self.save("care.endTrial", payload)
        self.assertFalse(
            next(b for b in self.state()["beds"] if b["id"] == bed)["residentId"]
        )
        (row,) = self.state(token)["trialFollowups"]
        self.assertEqual(row["assigneeId"], aid)
        self.assertFalse(self.state(other)["trialFollowups"])
        report = {
            "taskId": row["id"],
            "method": "电话",
            "outcome": "暂缓入住",
            "feedback": "已与家属商议，考虑距离",
            "nextSteps": "按家属约定下周再联系",
        }
        with self.assertRaises(PermissionError):
            self.save("care.finishTrialFollowup", report, other)
        with self.assertRaises(ValueError):
            self.save("care.finishTrialFollowup", {**report, "feedback": ""}, token)
        self.save(
            "care.reassignTrialFollowup", {"taskId": row["id"], "assigneeId": bid}
        )
        self.assertFalse(self.state(token)["trialFollowups"])
        self.save("care.finishTrialFollowup", report, other)
        (finished,) = self.state()["trialFollowups"]
        self.assertEqual(
            (
                finished["status"],
                finished["reportedBy"],
                finished["report"]["feedback"],
            ),
            ("已回访", bid, report["feedback"]),
        )
        with self.assertRaises(ValueError):
            self.save("care.finishTrialFollowup", report, other)

    def test_defaults_are_owner_managed_and_dont_reprice_existing_stays(self):
        with self.assertRaises(PermissionError):
            self.save("access.trialSettings", {"days": 2, "fee": 99}, self.staff[0][0])
        self.assertEqual(self.state()["trialSettings"], {"days": 3, "fee": None})
        rid, _ = self.trial()
        self.save("access.trialSettings", {"days": 4, "fee": 0})
        state = self.state()
        trial = next(r for r in state["residents"] if r["id"] == rid)
        self.assertEqual(
            (trial["trialEndsAt"], trial["trialPrice"]), ("2026-11-26", 256.50)
        )
        self.assertEqual(state["trialSettings"], {"days": 4, "fee": 0})
        (bill,) = [b for b in state["bills"] if b["residentId"] == rid]
        self.assertEqual((bill["kind"], bill["amount"]), ("trial", 256.50))

    def test_receiving_employee_must_still_cover_the_archived_room(self):
        rid, _ = self.trial()
        token, aid = self.staff[0]
        assigned = {
            "residentId": rid,
            "reason": "回家居住",
            "assigneeId": aid,
            "dueDate": "2026-11-25",
        }
        self.store.facility_policy = lambda db, user: (
            {"roomIds": []} if user["id"] == aid else {}
        )
        self.assertNotIn(
            aid,
            [
                row["id"]
                for row in self.store.trial_assignees(self.owner, rid)["recipients"]
            ],
        )
        with self.assertRaises(ValueError):
            self.save("care.endTrial", assigned)
        self.store.facility_policy = None
        self.save("care.endTrial", assigned)
        (task,) = self.state(token)["trialFollowups"]
        self.store.facility_policy = lambda db, user: (
            {"roomIds": []} if user["id"] == aid else {}
        )
        self.assertFalse(self.state(token)["trialFollowups"])
        with self.assertRaises(PermissionError):
            self.save(
                "care.finishTrialFollowup",
                {
                    "taskId": task["id"],
                    "method": "电话",
                    "outcome": "未能联系",
                    "feedback": "已拨打登记电话",
                    "nextSteps": "明日跟进",
                },
                token,
            )
