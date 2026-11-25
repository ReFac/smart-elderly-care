"""Business revision history is scoped, transactional and independently reversible."""

from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch


from identity_fixture import verified_password
from platform_core.store import Store, Conflict, TIMEZONE


class ChangeHistory(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.now = datetime.now(TIMEZONE).replace(microsecond=0)
        self.file = Path(tmp.name) / "test.db"
        self.password = "only-history-fixture"
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": self.password}):
            self.store = Store(self.file, lambda: self.now)
        self.owner, _ = self.store.login("owner", self.password)
        self.rid = "r001"
        self.name = next(
            r["name"]
            for r in self.store.snapshot(self.owner)["data"]["residents"]
            if r["id"] == self.rid
        )

    def do(self, action, token=None, comment="", **payload):
        token = token or self.owner
        return self.store.execute(
            action,
            payload,
            self.store.version(token)["revision"],
            token,
            comment=comment,
        )["revision"]

    def undo(self, target, token=None):
        token = token or self.owner
        return self.store.undo_change(
            token, target, self.store.version(token)["revision"], comment="核对后更正"
        )["revision"]

    def task(self, title="协助饮水", token=None, kind="日常照护"):
        rev = self.do(
            "care.addTask",
            token,
            residentId=self.rid,
            title=title,
            kind=kind,
            assignee="值班人员",
        )
        return rev, self.store.history_change(token or self.owner, rev)["changes"][0][
            "entityId"
        ]

    def employee(self, name, **kwargs):
        self.do(
            "access.create",
            kind="staff",
            username=name,
            password=self.password,
            displayName=name,
            role="护工",
            **kwargs,
        )
        return self.store.login(name, self.password)[0]

    def test_field_level_profile_changes_and_original_source_are_stable(self):
        a = self.do(
            "dossier.profile",
            residentId=self.rid,
            name=self.name,
            comment="长辈核对常住地址",
            address="甲路",
        )
        b = self.do(
            "dossier.profile", residentId=self.rid, name=self.name, nativePlace="乙地"
        )
        first = self.store.history_change(self.owner, a)
        self.assertEqual(
            ("dossier_profiles", "basic/address", "甲路"),
            tuple(first["changes"][0][k] for k in ("collection", "field", "after")),
        )
        self.assertEqual(first["comment"], "长辈核对常住地址")
        self.assertTrue(first["undoable"])
        undone = self.undo(a)
        self.assertEqual(self.store.history_change(self.owner, a)["undoneBy"], undone)
        self.assertEqual(self.store.history_change(self.owner, undone)["undoOf"], a)
        self.assertEqual(
            self.store.history_change(self.owner, undone)["changes"][0]["before"],
            "甲路",
        )
        self.assertTrue(self.store.history_change(self.owner, b)["undoable"])
        with closing(self.store.connect()) as db:
            current = json.loads(
                db.execute(
                    "SELECT basic FROM dossier_profiles WHERE resident_id=?",
                    (self.rid,),
                ).fetchone()[0]
            )
        self.assertEqual(current, {"nativePlace": "乙地"})

    def test_inverse_of_first_profile_edit_removes_initial_empty_storage_row(self):
        a = self.do(
            "dossier.profile", residentId=self.rid, name=self.name, address="甲路"
        )
        self.undo(a)
        with closing(self.store.connect()) as db:
            self.assertFalse(
                db.execute(
                    "SELECT 1 FROM dossier_profiles WHERE resident_id=?", (self.rid,)
                ).fetchone()
            )

    def test_retouching_same_value_cannot_destroy_another_update(self):
        a = self.do(
            "dossier.profile", residentId=self.rid, name=self.name, address="原地址"
        )
        self.do(
            "dossier.profile", residentId=self.rid, name=self.name, address="新地址"
        )
        self.do(
            "dossier.profile", residentId=self.rid, name=self.name, address="原地址"
        )
        self.assertFalse(self.store.history_change(self.owner, a)["undoable"])
        with self.assertRaises(Conflict):
            self.undo(a)

    def test_routine_voice_confirmation_is_reversible_without_reopening_receipt(self):
        worker = self.employee("worker-voice")
        _, task = self.task(token=worker)
        self.do(
            "gw.propose",
            worker,
            requestId="normal-voice-01",
            taskId=task,
            transcript="每天协助饮水",
            note="已协助饮水",
        )
        with closing(self.store.connect()) as db:
            pid = db.execute(
                "SELECT id FROM gateway_voice WHERE task_id=?", (task,)
            ).fetchone()[0]
        confirmed = self.do("gw.confirm", worker, proposalId=pid)
        self.assertTrue(self.store.history_change(worker, confirmed)["undoable"])
        self.undo(confirmed, worker)
        view = self.store.snapshot(worker)["data"]
        self.assertEqual(
            "待执行", next(t for t in view["tasks"] if t["id"] == task)["status"]
        )
        self.assertFalse(any(v["id"] == pid for v in view["voiceQueue"]))
        with closing(self.store.connect()) as db:
            status, reviewer, stamp = db.execute(
                "SELECT status,reviewer_id,reviewed_at FROM gateway_voice WHERE id=?",
                (pid,),
            ).fetchone()
        self.assertEqual(status, "已撤销")
        self.assertTrue(reviewer and stamp)
        with self.assertRaises(ValueError):
            self.do("gw.confirm", worker, proposalId=pid)

    def test_downstream_quality_and_clinical_receipts_protect_task(self):
        _, task = self.task()
        completed = self.do("care.completeTask", taskId=task, note="完成")
        self.do("care.quality", taskId=task, rating=4, note="抽查", result="合格")
        with self.assertRaises(Conflict):
            self.undo(completed)
        _, medical = self.task("执行给药", kind="临床")
        completed = self.do("care.completeTask", taskId=medical)
        self.assertFalse(self.store.history_change(self.owner, completed)["undoable"])

    def test_room_scope_filter_and_privilege_loss(self):
        worker = self.employee("worker-one")
        other = self.employee("worker-two")
        rev, _ = self.task(token=worker)
        row = self.store.history_change(worker, rev)
        self.assertTrue(row["roomId"])
        self.assertEqual(
            [rev],
            [
                p["revision"]
                for p in self.store.history(worker, roomId=row["roomId"])["rows"]
            ],
        )
        self.assertEqual([], self.store.history(worker, roomId=row["room"])["rows"])
        self.assertEqual([], self.store.history(other)["rows"])
        with self.assertRaises(FileNotFoundError):
            self.store.history_change(other, rev)
        tight = Store(
            self.file,
            lambda: self.now,
            facility_policy=lambda db, user: {"roomIds": []},
        )
        self.assertEqual([], tight.history(worker)["rows"])
        with self.assertRaises(FileNotFoundError):
            tight.undo_change(worker, rev, self.store.version(worker)["revision"])

    def test_legacy_cutoff_sensitive_credentials_and_comments(self):
        holder = self.employee("history-policy")
        previous = self.store.version(self.owner)["revision"]
        with self.assertRaises(ValueError):
            self.do("care.inquire", comment="长" * 241, name="不会创建")
        self.assertEqual(previous, self.store.version(self.owner)["revision"])
        with closing(self.store.connect()) as db, db:
            db.execute("DELETE FROM history_commits WHERE revision=?", (previous,))
        self.assertEqual(
            self.store.history_change(self.owner, previous)["source"], "legacy"
        )
        self.assertNotIn(self.password, json.dumps(self.store.history(self.owner)))
        verified_password(
            self.store, holder, "history-policy", self.password, "new-private-test-pass"
        )
        current = self.store.version(self.owner)["revision"]
        record = self.store.history_change(self.owner, current)
        self.assertTrue(any(c["field"] == "credential" for c in record["changes"]))
        self.assertNotIn("new-private-test-pass", str(record))
        self.now += timedelta(days=60, seconds=1)
        self.assertEqual([], self.store.history(self.owner)["rows"])
        with self.assertRaises(FileNotFoundError):
            self.store.history_change(self.owner, current)
        reopened = Store(self.file, lambda: self.now)
        with closing(reopened.connect()) as db:
            self.assertEqual(
                0, db.execute("SELECT count(*) FROM history_commits").fetchone()[0]
            )
            self.assertGreater(
                db.execute("SELECT count(*) FROM audit").fetchone()[0], 0
            )

    def test_concurrent_inverse_only_commits_once_and_keeps_original_entry(self):
        rev, _ = self.task()
        gate = Barrier(2)

        def run(_):
            gate.wait()
            try:
                return self.store.undo_change(self.owner, rev, rev)["revision"]
            except Conflict:
                return "conflict"

        with ThreadPoolExecutor(2) as pool:
            self.assertCountEqual(pool.map(run, range(2)), [rev + 1, "conflict"])
        self.assertEqual(2, len(self.store.history(self.owner)["rows"]))

    def test_backup_policy_inverse_preserves_version_and_other_fields(self):
        from platform_core.backups.exchange import change_policy

        def configure(keep, size, v):
            return change_policy(
                self.store.backups,
                self.owner,
                dict(retentionDays=keep, uploadLimitMiB=size, version=v),
            )

        v = configure(90, 1024, 0)["version"]
        first = self.store.version(self.owner)["revision"]
        configure(90, 64, v)
        self.undo(first)
        restored = self.store.backups.status(self.owner)["policy"]
        self.assertEqual(
            (0, 64, 3),
            (
                restored["retentionDays"],
                restored["uploadLimitMiB"],
                restored["version"],
            ),
        )

    def test_room_timeline_preference_retains_its_own_history_scope(self):
        _, task = self.task()
        assigned = self.store.history(self.owner)["rows"][0]["roomId"]
        change = self.do(
            "care.timelineSettings",
            roomId=assigned,
            mergeEnabled=True,
            windowMinutes=15,
        )
        self.assertEqual(
            change,
            self.store.history(self.owner, roomId=assigned)["rows"][0]["revision"],
        )
        self.undo(change)
        self.assertEqual(
            [], self.store.snapshot(self.owner)["data"].get("careTimelineSettings", [])
        )

    def test_search_only_returns_authorized_comments_and_shanghai_day(self):
        other = self.employee("history-search")
        actor = self.employee("history-note")
        self.now = datetime(2026, 11, 23, 15, 59, 59, tzinfo=ZoneInfo("UTC"))
        first = self.do(
            "care.addTask",
            actor,
            residentId=self.rid,
            title="生活协助",
            assignee="值班",
            comment="已与监护人核实",
        )
        self.now += timedelta(seconds=2)
        second = self.do(
            "care.addTask",
            actor,
            residentId=self.rid,
            title="生活协助",
            assignee="值班",
            note="私密详细原文",
        )
        self.assertEqual(
            [first],
            [
                r["revision"]
                for r in self.store.history(actor, q="监护人", day="2026-11-23")["rows"]
            ],
        )
        self.assertEqual([], self.store.history(other, q="监护人")["rows"])
        self.assertEqual([], self.store.history(actor, q="私密详细原文")["rows"])
        self.assertEqual(
            [], self.store.history(actor, q=f"V{first}", day="2026-11-24")["rows"]
        )
        self.assertEqual(
            [second],
            [
                r["revision"]
                for r in self.store.history(actor, q=f"v{second}", day="2026-11-24")[
                    "rows"
                ]
            ],
        )
        for invalid in ({"q": "x" * 121}, {"day": "2026-02-30"}, {"day": "20261124"}):
            with self.assertRaises(ValueError):
                self.store.history(actor, **invalid)

    def test_composite_change_comments_are_hidden_on_field_grant_revocation_and_search(
        self,
    ):
        full = self.employee("profile-writer", permissions=["intake", "relatives"])
        peer = self.employee("profile-auditor", permissions=["intake", "audit"])
        private = "家庭会计核对金额"
        revision = self.do(
            "dossier.profile",
            full,
            residentId=self.rid,
            name=self.name,
            economicNotes=private,
            comment=private,
        )
        self.assertEqual(self.store.history_change(full, revision)["comment"], private)
        self.assertEqual(self.store.history_change(peer, revision)["comment"], "")
        self.assertEqual([], self.store.history(peer, q=private)["rows"])
        account = self.store.snapshot(full)["data"]["user"]["id"]
        self.do("access.update", id=account, permissions=["intake"])
        renewed = self.store.login("profile-writer", self.password)[0]
        self.assertNotIn(private, str(self.store.history_change(renewed, revision)))
        undo = self.undo(revision)
        self.assertEqual("", self.store.history_change(peer, undo)["comment"])

    def test_campus_only_reception_provenance_excludes_another_campus_and_room_scopes(
        self,
    ):
        from platform_core import facility

        self.do("facility.addCampus", name="历史示例分院")
        other_site = next(
            c["id"]
            for c in self.store.facility_resource(self.owner, "directory")["campuses"]
            if c["id"] != facility.HOME_CAMPUS
        )
        local = self.employee(
            "main-intake",
            campusId=facility.HOME_CAMPUS,
            permissions=["intake", "audit"],
        )
        other = self.employee(
            "other-intake", campusId=other_site, permissions=["intake", "audit"]
        )
        change = self.do("care.inquire", local, name="历史示例访客")
        self.assertEqual(change, self.store.history_change(local, change)["revision"])
        with self.assertRaises(FileNotFoundError):
            self.store.history_change(other, change)
        mainroom = self.store.facility_resource(self.owner, "search", q="101")[
            "results"
        ][0]["roomId"]
        limited = Store(
            self.file,
            lambda: self.now,
            facility_policy=lambda db, u: {"roomIds": [mainroom]},
        )
        with self.assertRaises(FileNotFoundError):
            limited.history_change(local, change)
        self.undo(change, local)

    def test_no_diff_leaks_after_failed_business_transaction(self):
        with (
            patch(
                "platform_core.history.record",
                side_effect=RuntimeError("journal unavailable"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.do("care.inquire", name="丢弃的数据")
        self.assertEqual([], self.store.history(self.owner)["rows"])
        self.assertFalse(
            any(
                r["name"] == "丢弃的数据"
                for r in self.store.snapshot(self.owner)["data"]["inquiries"]
            )
        )
