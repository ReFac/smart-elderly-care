from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from platform_core import scheduled_work
from platform_core.store import Store


class PlanRevisions(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.now = datetime(2026, 11, 23, 10, 30, tzinfo=scheduled_work.LOCAL)
        self.store = Store(
            Path(folder.name) / "care.db",
            now=lambda: self.now,
            initial_owner_password="plan-test-only",
        )
        self.owner, _ = self.store.login("owner", "plan-test-only")

    def save(self, action, values, user=None):
        user = user or self.owner
        return self.store.execute(
            action, values, self.store.version(user)["revision"], user
        )

    def snapshot(self):
        return self.store.snapshot(self.owner)["data"]

    def test_plan_changes_wait_for_review_and_repeat_without_duplicate_dispatch(self):
        self.save(
            "care.assess",
            dict(
                residentId="r001",
                level="半失能",
                note="核对生活协助需求",
                assignee="陈悦",
            ),
        )
        plan = self.snapshot()["plans"][-1]

        def items(name, **fields):
            return dict(
                dict(
                    title=name,
                    category="生活照料",
                    period="daily",
                    weekday=1,
                    count=2,
                    times=["08:00", "14:00"],
                    roles=["护士"],
                    assignee="陈悦",
                    enabled=True,
                ),
                **fields,
            )

        entries = [
            items("早晚照护"),
            items("暂缓", enabled=False),
            items("不定时陪伴", times=[]),
            items("周二协助", period="weekly", weekday=2, count=1, times=["09:00"]),
        ]
        self.save(
            "care.revisePlan",
            dict(planId=plan["id"], serviceItems=entries, operator="冒名"),
        )
        draft = self.snapshot()["plans"][-1]
        self.assertEqual(draft["modifiedBy"], "Owner")
        self.assertFalse(scheduled_work.read(self.store, self.owner)["rules"])
        self.save("care.approvePlan", dict(planId=plan["id"]))
        state = self.snapshot()
        tasks = [t for t in state["tasks"] if t.get("planId") == plan["id"]]
        self.assertCountEqual(
            [t["time"] for t in tasks if t["title"] == "早晚照护"], ["08:00", "14:00"]
        )
        self.assertEqual(sum(t["title"] == "不定时陪伴" for t in tasks), 2)
        self.save("access.create", dict(username="plan-viewer", kind="staff", role="护工",
                                        displayName="照护员", password="staff-test-only"))
        staff, _ = self.store.login("plan-viewer", "staff-test-only")
        restricted_task = next(t for t in tasks if t["title"] == "早晚照护")
        with self.assertRaisesRegex(PermissionError, "岗位"):
            self.save("care.completeTask", dict(taskId=restricted_task["id"], note="测试",
                      owner=True, actorRole="护士"), staff)
        self.assertFalse(any(t["title"] in ("暂缓", "周二协助") for t in tasks))
        rules = scheduled_work.read(self.store, self.owner)["rules"]
        self.assertEqual(len(rules), 5)
        with self.assertRaises(ValueError):
            self.save(
                "care.setScheduleEnabled", {"id": rules[0]["id"], "enabled": False}
            )
        self.now += timedelta(days=1)
        self.assertEqual(scheduled_work.tick(self.store), 4)
        self.assertEqual(scheduled_work.tick(self.store), 0)
        self.now += timedelta(hours=4)
        self.assertEqual(scheduled_work.tick(self.store), 1)
        self.save(
            "care.revisePlan",
            dict(planId=plan["id"], serviceItems=[items("新安排", period="once")]),
        )
        new = self.snapshot()["plans"][-1]
        self.assertEqual(new["previousPlanId"], plan["id"])
        self.assertEqual(new["status"], "待复核")
        self.assertEqual(
            sum(
                r["enabled"]
                for r in scheduled_work.read(self.store, self.owner)["rules"]
            ),
            5,
        )
        self.save("care.approvePlan", dict(planId=new["id"]))
        self.assertFalse(
            any(
                r["enabled"]
                for r in scheduled_work.read(self.store, self.owner)["rules"]
            )
        )
        with self.assertRaises(ValueError):
            self.save("care.revisePlan", dict(planId=plan["id"], serviceItems=entries))

    def test_risk_report_requires_clinical_grant_keeps_factors_and_preserves_empty_score(
        self,
    ):
        self.save(
            "access.create",
            dict(
                username="plan-aide",
                kind="staff",
                role="护工",
                displayName="照护员",
                password="staff-test-only",
            ),
        )
        staff, _ = self.store.login("plan-aide", "staff-test-only")
        report = dict(
            topic="跌倒/坠床",
            instrument="测试用人工记录",
            level="待专业复核",
            score=None,
            maximum=None,
            factors=[dict(group="环境观察", finding="合成观察", points=None)],
            immediate="",
            follow="复核原始观察",
            routine="",
            avoid="",
            nextReview="2026-11-25",
        )
        p = dict(
            residentId="r001",
            subject=report["topic"],
            finding="等待复核",
            riskReport=report,
        )
        with self.assertRaises(PermissionError):
            self.save("care.screen", p, staff)
        self.save("care.screen", p)
        row = self.snapshot()["followups"][-1]
        self.assertEqual(row["riskReport"], report)
        self.assertEqual(row["openedBy"], "Owner")
        self.assertFalse(self.store.snapshot(staff)["data"]["followups"])
        with self.assertRaises(ValueError):
            self.save(
                "care.screen",
                {**p, "riskReport": {**report, "score": 12, "maximum": 10}},
            )
        self.assertEqual(len(self.snapshot()["followups"]), 1)
