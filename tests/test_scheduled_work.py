"""Scheduled releases preserve resident scope, per-meal uniqueness and confirmed history."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from platform_core import facility, scheduled_work
from platform_core.store import Store


START = datetime(2026, 11, 24, 8, 59, tzinfo=scheduled_work.LOCAL)


class ScheduledWorkTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.now = START
        self.store = Store(
            Path(tmp.name) / "schedules.db",
            now=lambda: self.now,
            initial_owner_password="owner-only-fixture",
        )
        self.owner, _ = self.store.login("owner", "owner-only-fixture")
        self.people = scheduled_work.read(self.store, self.owner)["roster"]
        self.a, self.b = next(
            (pa, pb)
            for pa in self.people
            for pb in self.people
            if pa["id"] != pb["id"] and pa["roomId"] == pb["roomId"]
        )

    def save(self, action, values, token=None):
        token = token or self.owner
        return self.store.execute(
            action, values, self.store.version(token)["revision"], token
        )

    def rule(self, title, *, kind="meal", scope=None, token=None, **extra):
        fields = dict(
            title=title,
            kind=kind,
            scope=scope or {"kind": "residents", "residentIds": [self.a["id"]]},
            time="09:00",
        )
        if kind == "meal":
            fields.update(mealKind="早餐", menu=["小米粥", "鸡蛋"])
        self.save("care.saveSchedule", {**fields, **extra}, token)
        return next(
            row
            for row in scheduled_work.read(self.store, token or self.owner)["rules"]
            if row["title"] == title
        )

    def tasks(self):
        return [
            task
            for task in self.store.snapshot(self.owner)["data"]["tasks"]
            if task.get("scheduleId")
        ]

    def staff(self, permissions, *, campus=facility.HOME_CAMPUS):
        self.save(
            "access.create",
            dict(
                username="scheduling-staff",
                displayName="照护员工",
                password="staff-test-fixture",
                kind="staff",
                role="护工",
                permissions=permissions,
                campusId=campus,
            ),
        )
        return self.store.login("scheduling-staff", "staff-test-fixture")[0]

    def test_time_room_cohort_and_concurrent_release_prevent_duplicate_meals(self):
        room = {"kind": "rooms", "roomIds": [self.a["roomId"]]}
        self.rule("早餐专项", scope=room)
        self.rule("重复早餐", scope=room, time="09:05")
        self.assertEqual(scheduled_work.tick(self.store), 0)
        self.now += timedelta(minutes=6)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(lambda _: scheduled_work.tick(self.store), range(2))
            )
        self.assertEqual(sum(results), 2)
        tasks = self.tasks()
        self.assertEqual({r["residentId"] for r in tasks}, {self.a["id"], self.b["id"]})
        self.assertEqual({r["scheduledRoomId"] for r in tasks}, {self.a["roomId"]})
        self.assertEqual({r["mealKind"] for r in tasks}, {"早餐"})
        runs = scheduled_work.read(self.store, self.owner)["runs"]
        self.assertEqual(
            [(r["title"], r["status"]) for r in runs],
            [("重复早餐", "empty"), ("早餐专项", "released")],
        )

    def test_menu_only_updates_pending_and_uses_one_day_override(self):
        room = {"kind": "rooms", "roomIds": [self.a["roomId"]]}
        rule = self.rule("可改菜单", scope=room)
        self.now += timedelta(minutes=1)
        self.assertEqual(scheduled_work.tick(self.store), 2)
        # The meal signoff path owns the implementation of completion itself.
        with closing(self.store.connect()) as db, db:
            from platform_core.store import encode
            import json

            state = json.loads(db.execute("SELECT data FROM workspace").fetchone()[0])
            first = next(task for task in state["tasks"] if task.get("scheduleId"))
            first["status"] = "已完成"
            db.execute("UPDATE workspace SET data=?", (encode(state),))
        day = self.now.date().isoformat()
        self.save(
            "care.scheduleMenu",
            {"id": rule["id"], "day": day, "menu": ["米饭", "清蒸鱼"]},
        )
        self.assertEqual(
            {r["status"]: r["menu"] for r in self.tasks()},
            {"已完成": ["小米粥", "鸡蛋"], "待执行": ["米饭", "清蒸鱼"]},
        )
        self.now += timedelta(days=1)
        self.assertEqual(scheduled_work.tick(self.store), 2)
        self.assertEqual(
            [r["menu"] for r in self.tasks() if r["date"] != day],
            [["小米粥", "鸡蛋"]] * 2,
        )

    def test_weekday_pause_and_campus_scope(self):
        staff = self.staff(["care", "care.schedule"])
        with self.assertRaises(PermissionError):
            self.rule("跨院批量", kind="care", scope={"kind": "all"}, token=staff)
        self.assertFalse(scheduled_work.read(self.store, staff)["allowAll"])
        rid = self.rule(
            "按周巡查",
            kind="patrol",
            scope={"kind": "rooms", "roomIds": [self.a["roomId"]]},
            weekdays=[START.isoweekday() + 1],
            token=staff,
        )["id"]
        self.now += timedelta(minutes=1)
        self.assertEqual(scheduled_work.tick(self.store), 0)
        self.save("care.setScheduleEnabled", {"id": rid, "enabled": False}, staff)
        self.now += timedelta(days=1)
        self.assertEqual(scheduled_work.tick(self.store), 0)
        self.save("care.setScheduleEnabled", {"id": rid, "enabled": True}, staff)
        self.assertEqual(scheduled_work.tick(self.store), 2)
        self.assertTrue(all(r["kind"] == "巡查" for r in self.tasks()))

    def test_date_specific_menu_and_assignee_cannot_cross_scope(self):
        staff = self.staff(["care"])
        report = scheduled_work.read(self.store, self.owner)
        employee = next(
            p for p in report["staff"] if p["id"] == self.store.version(staff)["userId"]
        )
        rule = self.rule("精确早餐签认", assigneeId=employee["id"])
        self.assertFalse(scheduled_work.read(self.store, staff)["canManage"])
        with self.assertRaises(PermissionError):
            self.save(
                "care.scheduleMenu",
                {"id": rule["id"], "day": START.date().isoformat(), "menu": ["八宝粥"]},
                staff,
            )
        self.now += timedelta(minutes=1)
        self.assertEqual(scheduled_work.tick(self.store), 1)
        self.assertEqual(self.tasks()[0]["assigneeId"], employee["id"])

    def test_delegated_named_schedule_stays_in_original_branch_after_transfer(self):
        staff = self.staff(["care", "care.schedule"])
        self.rule("分院原住户", kind="patrol", token=staff)
        self.save("facility.addCampus", {"name": "专项验收分院"})
        report = scheduled_work.read(self.store, self.owner)
        branch = next(
            c["id"] for c in report["campuses"] if c["name"] == "专项验收分院"
        )
        self.save("facility.addBuilding", {"campusId": branch, "name": "乙楼"})
        directory = self.store.facility_resource(self.owner, "directory")
        building = next(
            b["id"] for b in directory["buildings"] if b["campusId"] == branch
        )
        self.save("facility.addFloor", {"buildingId": building, "number": 1})
        directory = self.store.facility_resource(self.owner, "directory")
        floor = next(
            b["floors"][0]["id"] for b in directory["buildings"] if b["id"] == building
        )
        self.save(
            "facility.addRoom",
            {"floorId": floor, "number": "101", "ward": "照护", "bedCount": 1},
        )
        report = scheduled_work.read(self.store, self.owner)
        room = next(r["id"] for r in report["rooms"] if r["campusId"] == branch)
        resource = self.store.facility_resource(self.owner, "room", room)
        self.save(
            "care.transfer",
            {"residentId": self.a["id"], "bedId": resource["beds"][0]["id"]},
        )
        self.now += timedelta(minutes=1)
        self.assertEqual(scheduled_work.tick(self.store), 0)
        runs = scheduled_work.read(self.store, self.owner)["runs"]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "empty")
        self.assertFalse(scheduled_work.read(self.store, staff)["rules"])
