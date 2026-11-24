from contextlib import closing
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from platform_core.care import timeline
from platform_core.store import Conflict, Store, TIMEZONE


class CareTimelineTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "office.sqlite3"
        self.date = datetime(2026, 11, 24, 9, 0, tzinfo=TIMEZONE)
        self.passwd = "synthetic-timeline-only"
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": self.passwd}):
            self.store = Store(self.path, lambda: self.date)
        self.owner, _ = self.store.login("owner", self.passwd)
        self.staff = self.account("care-staff")
        with closing(self.store.connect()) as db:
            self.room = db.execute(
                "SELECT roomId FROM facility_beds WHERE bedId='b001'"
            ).fetchone()[0]
            self.other = db.execute(
                "SELECT roomId FROM facility_beds WHERE bedId='b003'"
            ).fetchone()[0]

    def cmd(self, action, payload, token=None):
        token = token or self.owner
        return self.store.execute(
            action, payload, self.store.version(token)["revision"], token
        )

    def account(self, name, role="护工"):
        self.cmd(
            "access.create",
            {
                "kind": "staff",
                "displayName": name,
                "username": name,
                "role": role,
                "password": self.passwd,
            },
        )
        return self.store.login(name, self.passwd)[0]

    def finish(self, rid, minute, *, title="递水", kind="日常照护", token=None):
        self.date = self.date.replace(hour=9 + minute // 60, minute=minute % 60)
        self.cmd(
            "care.addTask",
            {
                "residentId": rid,
                "title": title,
                "assignee": "排班员",
                "kind": kind,
                "time": "08:00",
                "date": "2026-11-24",
            },
        )
        task = self.store.snapshot(self.owner)["data"]["tasks"][-1]["id"]
        self.cmd("care.completeTask", {"taskId": task, "note": "合成服务凭证"}, token)
        return task

    def read(self, scope="room", entity=None, token=None, **kwargs):
        return timeline.read(
            self.store,
            token or self.owner,
            scope,
            entity or self.room,
            day="2026-11-24",
            **kwargs,
        )

    def config(self, field, target, minutes=30, enabled=True, token=None):
        return self.cmd(
            "care.timelineSettings",
            {field: target, "mergeEnabled": enabled, "windowMinutes": minutes},
            token,
        )

    def test_actual_times_same_room_multiple_residents_and_staff_keep_all_receipts(
        self,
    ):
        a = self.finish("r001", 0)
        b = self.finish("r002", 20, token=self.staff)
        c = self.finish("r001", 30)
        d = self.finish("r002", 40, token=self.staff)
        self.finish("r003", 10)
        groups = self.read()["groups"]
        self.assertEqual([1, 3], [len(g["entries"]) for g in groups])
        event = groups[1]
        self.assertEqual("09:00", event["start"][11:16])
        self.assertEqual("09:30", event["end"][11:16])
        self.assertEqual([a, b, c], [e["taskId"] for e in event["entries"]])
        self.assertEqual(2, len({r["operatorId"] for r in event["entries"]}))
        self.assertTrue(all(e["roomId"] == self.room for e in event["entries"]))
        self.assertEqual(d, groups[0]["entries"][0]["taskId"])
        self.assertEqual(2, self.read(q="care-staff")["totalGroups"])

    def test_per_room_and_per_resident_settings_separate_from_originals(self):
        self.finish("r001", 0)
        self.finish("r001", 12)
        self.finish("r002", 18)
        self.config("roomId", self.room, enabled=False, token=self.staff)
        self.config("residentId", "r001", 15)
        self.assertEqual(3, self.read()["totalGroups"])
        self.assertEqual(2, self.read("resident", "r001", q="递水")["totalEntries"])
        self.assertEqual(1, self.read("resident", "r001", q="递水")["totalGroups"])
        other = Store(self.path, lambda: self.date)
        self.assertFalse(
            timeline.read(other, self.owner, "room", self.room)["settings"][
                "mergeEnabled"
            ]
        )
        self.assertEqual(
            3, timeline.read(other, self.owner, "work", q="递水")["totalGroups"]
        )
        with self.assertRaises(ValueError):
            self.config("roomId", self.room, 99)

    def test_clinical_unknown_and_legacy_receipts_stay_separate(self):
        for i in (0, 3):
            self.finish("r001", i, title="递水", kind="医嘱执行")
            self.finish("r002", i, title="餐后核对医嘱")
            self.finish("r002", i, title="午餐陪护", kind="膳食服务")
        groups = self.read()["groups"]
        self.assertCountEqual([1, 1, 1, 1, 2], [len(g["entries"]) for g in groups])
        historical = self.read("resident", "r001")["groups"]
        old = [g for g in historical if not g["start"]]
        self.assertTrue(old)
        self.assertTrue(all(len(g["entries"]) == 1 and not g["roomLabel"] for g in old))

    def test_voice_completion_freezes_time_bed_and_resolves_proposal_exactly_once(self):
        self.cmd(
            "care.addTask",
            {
                "residentId": "r001",
                "title": "协助饮水",
                "assignee": "执行员",
                "kind": "日常照护",
                "date": "2026-11-24",
                "time": "08:00",
            },
        )
        task = self.store.snapshot(self.owner)["data"]["tasks"][-1]["id"]
        self.cmd(
            "gw.propose",
            {
                "taskId": task,
                "requestId": "timeline-voice",
                "note": "语音核对并执行",
                "transcript": "合成音频",
            },
        )
        with closing(self.store.connect()) as db:
            pid = db.execute(
                "SELECT id FROM gateway_voice WHERE task_id=?", (task,)
            ).fetchone()[0]
        self.cmd("gw.confirm", {"proposalId": pid}, self.staff)
        row = self.read(q="协助饮水")["groups"][0]["entries"][0]
        self.assertEqual(self.room, row["roomId"])
        self.assertEqual("care-staff", row["operator"])
        self.assertEqual("09:00", row["at"][11:16])
        self.assertEqual("", row["scannedBed"])

    def test_location_is_frozen_and_scoped_staff_cannot_read_foreign_old_or_current_room(
        self,
    ):
        self.finish("r001", 0)
        self.finish("r003", 0)
        self.cmd(
            "care.transfer",
            {"residentId": "r001", "bedId": "b015", "reason": "楼内合成调床"},
        )
        self.assertEqual(1, self.read(q="递水")["totalEntries"])
        scoped = Store(
            self.path,
            lambda: self.date,
            facility_policy=lambda db, user: {"roomIds": [self.room]},
        )
        self.assertEqual(
            0,
            timeline.read(scoped, self.staff, "room", self.room, q="递水")[
                "totalEntries"
            ],
        )
        with self.assertRaises(FileNotFoundError):
            timeline.read(scoped, self.staff, "room", self.other)
        with self.assertRaises(PermissionError):
            timeline.read(scoped, self.staff, "resident", "r001")
        with self.assertRaises((FileNotFoundError, PermissionError)):
            scoped.execute(
                "care.timelineSettings",
                {"roomId": self.other, "mergeEnabled": True, "windowMinutes": 10},
                scoped.version(self.staff)["revision"],
                self.staff,
            )
        finance = self.account("test-finance", "财务")
        with self.assertRaises(PermissionError):
            self.read(token=finance)
        with self.assertRaises(PermissionError):
            self.config("roomId", self.room, token=finance)

    def test_custom_routine_requires_explicit_classification_and_sensitive_notes_stay_single(
        self,
    ):
        labels = []
        for title, mode, note in [
            ("茶歇递温水", "water", "护理组协助"),
            ("午间递杯", "water", "常规服务"),
            ("送水", "auto", "发现呛咳并已通知护士"),
            ("送水", "separate", "已照护"),
        ]:
            self.cmd(
                "care.addTask",
                {
                    "residentId": "r001",
                    "title": title,
                    "assignee": "合成",
                    "routineActivity": mode,
                },
            )
            tid = self.store.snapshot(self.owner)["data"]["tasks"][-1]["id"]
            self.cmd("care.completeTask", {"taskId": tid, "note": note})
            labels.append(tid)
        self.assertCountEqual(
            [2, 1, 1], [len(g["entries"]) for g in self.read()["groups"]]
        )
        with self.assertRaises(ValueError):
            self.cmd(
                "care.addTask",
                {
                    "residentId": "r001",
                    "title": "核对医嘱",
                    "assignee": "合成",
                    "routineActivity": "water",
                },
            )

    def test_settings_version_is_locatable_and_can_revert_without_touching_the_originals(
        self,
    ):
        task_id = self.finish("r001", 0)
        revision = self.config("roomId", self.room, enabled=False)["revision"]
        row = self.store.history_change(self.owner, revision)
        self.assertTrue(row["undoable"], row.get("undoReason"))
        self.assertIn(
            revision,
            [
                item["revision"]
                for item in self.store.history(self.owner, roomId=self.room)["rows"]
            ],
        )
        from platform_core import history

        history.undo(self.store, self.owner, revision, revision, "撤销显示调整")
        page = self.read()
        self.assertTrue(page["settings"]["mergeEnabled"])
        self.assertEqual(task_id, page["groups"][0]["entries"][0]["taskId"])

    def test_stale_pagination_and_malformed_queries(self):
        old = self.read()["revision"]
        self.finish("r001", 0)
        with self.assertRaises(Conflict):
            self.read(offset="15", revision=str(old))
        for key, value in (("offset", "-1"), ("revision", "hello"), ("q", "a" * 65)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.read(**{key: value})
