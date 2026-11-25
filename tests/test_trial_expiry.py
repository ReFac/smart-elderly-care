"""Exercise the trial deadline and both decisions through the real encrypted workspace."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from queue import SimpleQueue
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch

from platform_core.care import archive_retention, trial_expiry
from platform_core.store import Store, TIMEZONE


class TrialDeadlineTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "trial.db"
        self.now = datetime(2028, 2, 28, 10, tzinfo=TIMEZONE)
        self.passwd = "trial-clock-qa-only"
        self.store = Store(
            self.path, lambda: self.now, initial_owner_password=self.passwd
        )
        self.owner, _ = self.store.login("owner", self.passwd)
        self.bed, self.spare = [
            b["id"] for b in self.data()["beds"] if b["status"] == "空闲"
        ][:2]
        self.rid = self.register("待定试住")
        self.write(
            "care.admit",
            residentId=self.rid,
            bedId=self.bed,
            stayType="trial",
            trialPrice=150,
        )

    def data(self, token=None):
        return self.store.snapshot(token or self.owner)["data"]

    def write(self, action, token=None, **payload):
        token = token or self.owner
        return self.store.execute(
            action, payload, self.store.version(token)["revision"], token
        )

    def register(self, name):
        self.write("care.register", name=name)
        return self.data()["residents"][-1]["id"]

    def resident(self):
        return next(r for r in self.data()["residents"] if r["id"] == self.rid)

    def expiry_events(self):
        with closing(self.store.connect()) as db:
            return db.execute(
                "SELECT count(*) FROM audit WHERE action='trial.expire' AND residentId=?",
                (self.rid,),
            ).fetchone()[0]

    def test_midnight_releases_reliably_once_and_does_not_start_monthly_charges(self):
        self.now = datetime(2028, 3, 1, 23, 59, 59, tzinfo=TIMEZONE)
        self.assertEqual(self.resident()["bedId"], self.bed)
        self.now += timedelta(seconds=1)
        connections = SimpleQueue()
        original = self.store.connect
        start = Barrier(8, timeout=10)

        def traced_connect():
            db = original()
            db.set_trace_callback(lambda sql: connections.put(sql) if sql == "BEGIN IMMEDIATE" else None)
            return db

        def maintain(_):
            start.wait()
            trial_expiry.maintain(self.store)
            archive_retention.maintain(self.store)

        with (
            patch.object(self.store, "connect", traced_connect),
            ThreadPoolExecutor(max_workers=8) as pool,
        ):
            list(pool.map(maintain, range(8)))
            trial_expiry.maintain(self.store)
            archive_retention.maintain(self.store)
        self.assertEqual(connections.qsize(), 2)
        resident = self.resident()
        self.assertEqual(
            (resident["status"], resident["bedId"], resident["trialReleasedOn"]),
            (trial_expiry.PENDING, "", "2028-03-02"),
        )
        others = [r for r in self.data()["billingDue"] if r["residentId"] == self.rid]
        self.assertFalse(others)
        self.assertEqual(self.expiry_events(), 1)
        revision = self.store.version(self.owner)["revision"]
        self.store = Store(self.path, lambda: self.now)
        self.assertEqual(self.store.version(self.owner)["revision"], revision)
        self.assertEqual(self.expiry_events(), 1)

    def test_failed_daily_scan_can_retry_during_the_same_day(self):
        self.now += timedelta(days=4)
        for job in (trial_expiry.maintain, archive_retention.maintain):
            with (
                patch.object(self.store, "connect", side_effect=OSError("暂时无法打开")),
                self.assertRaisesRegex(OSError, "暂时无法打开"),
            ):
                job(self.store)
            with patch.object(self.store, "connect", wraps=self.store.connect) as connect:
                job(self.store)
                job(self.store)
                connect.assert_called_once()
        self.assertEqual(self.expiry_events(), 1)

    def test_missed_deadline_and_new_occupant_survive_late_confirmation(self):
        self.now += timedelta(days=9)
        self.store = Store(self.path, lambda: self.now)
        self.assertEqual(self.resident()["trialReleasedOn"], "2028-03-02")
        new_id = self.register("后来入住")
        self.write("care.admit", residentId=new_id, bedId=self.bed)
        for fields in ({}, {"bedId": self.bed}):
            with self.assertRaises(ValueError):
                self.write("care.confirmStay", residentId=self.rid, **fields)
        self.write("care.confirmStay", residentId=self.rid, bedId=self.spare)
        resident = self.resident()
        self.assertEqual(
            (
                resident["status"],
                resident["stayType"],
                resident["bedId"],
                resident["formalizedAt"],
            ),
            ("在住", "formal", self.spare, "2028-03-08"),
        )
        self.assertEqual(
            next(b["residentId"] for b in self.data()["beds"] if b["id"] == self.bed),
            new_id,
        )
        self.assertEqual(
            [
                p["startDate"]
                for p in self.data()["billingDue"]
                if p["residentId"] == self.rid
            ],
            [],
        )
        self.assertEqual(
            sorted((b["kind"], b["startDate"]) for b in self.data()["bills"] if b["residentId"] == self.rid),
            [("monthly", "2028-03-08"), ("security", "2028-03-08"), ("trial", "2028-02-28")],
        )

    def test_cancellation_after_release_archives_and_assigns_one_followup(self):
        self.now += timedelta(days=4)
        new_id = self.register("接替床位")
        self.write("care.admit", residentId=new_id, bedId=self.bed)
        payload = dict(
            residentId=self.rid,
            reason="家属决定居家照护",
            assigneeId=self.data()["user"]["id"],
            dueDate=self.now.date().isoformat(),
        )
        self.write("care.endTrial", **payload)
        with self.assertRaises(ValueError):
            self.write("care.endTrial", **payload)
        self.assertEqual(self.resident()["status"], "已退住")
        self.assertEqual(len(self.data()["trialFollowups"]), 1)
        self.assertEqual(
            next(b["residentId"] for b in self.data()["beds"] if b["id"] == self.bed),
            new_id,
        )

    def test_scoped_recipient_can_still_see_released_resident_but_cannot_pick_another_room(
        self,
    ):
        self.write(
            "access.create",
            kind="staff",
            role="自定义",
            permissions=["intake"],
            displayName="接待值班",
            username="intake-qa",
            password=self.passwd,
        )
        token, user = self.store.login("intake-qa", self.passwd)
        with closing(self.store.connect()) as db:
            room = db.execute(
                "SELECT roomId FROM facility_beds WHERE bedId=?", (self.bed,)
            ).fetchone()[0]
            other = db.execute(
                "SELECT bedId FROM facility_beds WHERE roomId<>? ", (room,)
            ).fetchall()
        self.now += timedelta(days=4)
        self.store.facility_policy = lambda db, person: (
            {"roomIds": [room]} if person["id"] == user["id"] else {}
        )
        self.assertIn(
            self.rid,
            [
                r["id"]
                for r in self.data(token)["residents"]
                if r["status"] == trial_expiry.PENDING
            ],
        )
        with self.assertRaises(PermissionError):
            self.write(
                "care.confirmStay", token, residentId=self.rid, bedId=other[0][0]
            )
        self.store.facility_policy = lambda db, person: (
            {"roomIds": []} if person["id"] == user["id"] else {}
        )
        self.assertNotIn(self.rid, [r["id"] for r in self.data(token)["residents"]])
        with self.assertRaises(PermissionError):
            self.write("care.confirmStay", token, residentId=self.rid, bedId=self.bed)

    def test_inconsistent_old_reference_never_clears_current_occupant(self):
        data = self.data()
        bed = next(b for b in data["beds"] if b["id"] == self.bed)
        resident = next(r for r in data["residents"] if r["id"] == self.rid)
        bed.update(residentId="already-reassigned", status="已入住")
        trial_expiry.release(data, resident)
        self.assertEqual(
            (bed["residentId"], bed["status"]), ("already-reassigned", "已入住")
        )
        self.assertEqual(resident["bedId"], "")
