"""Exercise public intake and staff scheduling against the same encrypted workspace."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest

from platform_core import facility, lead_intake
from platform_core.store import Conflict, Store, TIMEZONE


class ReceptionWorkspaceTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.password = "reception-test-only"
        at = datetime(2026, 11, 25, 8, 15, tzinfo=TIMEZONE)
        self.store = Store(
            Path(directory.name) / "reception.db",
            initial_data="empty",
            now=lambda: at,
            initial_owner_password=self.password,
        )
        self.owner, _ = self.store.login("owner", self.password)
        self.main = facility.HOME_CAMPUS
        self.phone_a, self.phone_b = "13800000070", "13800000071"

    def version(self):
        return self.store.version(self.owner)["revision"]

    def save(self, action, payload, token=None):
        return self.store.execute(action, payload, self.version(), token or self.owner)

    def register(self, phone, campus=None):
        return lead_intake.submit(
            self.store,
            {
                "phone": phone,
                "source": "consent",
                "consent": True,
                "campusId": campus or self.main,
            },
            "test-peer",
        )

    def test_public_directory_repeated_consent_and_scoped_staff_history(self):
        self.save("facility.addCampus", {"name": "北院区"})
        north = lead_intake.reception(self.store)["campuses"][-1]
        self.assertEqual(set(north), {"id", "name"})
        self.save(
            "access.create",
            {
                "kind": "staff",
                "role": "自定义",
                "permissions": ["intake", "audit"],
                "username": "frontdesk",
                "password": self.password,
                "displayName": "本部接待",
                "campusId": self.main,
            },
        )
        staff, _ = self.store.login("frontdesk", self.password)
        self.assertEqual(self.register(self.phone_a), {"received": True})
        revision = self.version()
        self.assertEqual(self.register(self.phone_a), {"received": True})
        self.assertEqual(self.version(), revision)
        self.register(self.phone_b, north["id"])
        data = self.store.snapshot(staff)["data"]
        self.assertIn("leads", data["user"]["routes"])
        self.assertEqual([r["phone"] for r in data["leadContacts"]], [self.phone_a])
        self.assertNotIn("leads.capacity", data["allowedActions"])
        with self.assertRaises(PermissionError):
            self.save("leads.capacity", {"campusId": self.main, "capacity": 3}, staff)
        with self.assertRaises(PermissionError):
            lead_intake.schedule(self.store, staff, north["id"], "2026-11-25")
        self.assertEqual(
            self.store.history_change(staff, revision)["action"], "leads.public"
        )
        audits = [a["revision"] for a in self.store.activity(staff)["rows"] if a["action"] == "leads.public"]
        self.assertEqual(audits, [revision])
        with self.assertRaises(FileNotFoundError):
            self.store.history_change(staff, revision + 1)

    def test_two_desk_sessions_cannot_overbook_one_seat(self):
        self.register(self.phone_a)
        self.register(self.phone_b)
        rows = self.store.snapshot(self.owner)["data"]["leadContacts"]
        revision, gate = self.version(), Barrier(2)
        args = dict(
            kind="visit",
            date="2026-11-26",
            start="16:00",
            end="17:00",
            phoneConfirmed=True,
        )

        def book(row):
            gate.wait(timeout=10)
            try:
                self.store.execute(
                    "leads.book", {**args, "leadId": row["id"]}, revision, self.owner
                )
                return True
            except Conflict:
                return False

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(book, rows))
        self.assertEqual(sum(results), 1)
        losing = rows[results.index(False)]
        with self.assertRaisesRegex(ValueError, "席位"):
            self.save("leads.book", {**args, "leadId": losing["id"]})
        day = lead_intake.schedule(self.store, self.owner, self.main, args["date"])
        self.assertEqual(len(day["bookings"]), 1)
        for slot in day["slots"][32:34]:
            self.assertFalse(slot["bookable"])
            self.assertEqual(slot["seats"], [day["bookings"][0]["id"]])
