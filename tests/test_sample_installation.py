from contextlib import closing
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from platform_core import sample, scheduled_work
from platform_core.store import Store, TIMEZONE


class SampleInstallationTests(TestCase):
    def make(self, mode="demo", **options):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        store = Store(Path(folder.name) / "test.sqlite3", initial_data=mode,
                      initial_owner_password="sample-test-password",
                      now=lambda: datetime(2026, 11, 25, 10, 20, tzinfo=TIMEZONE), **options)
        return store, store.login("owner", "sample-test-password")[0]

    def test_resume_initial_dispatch_and_scoped_case_links(self):
        store, owner = self.make(prepare_sample=True)
        self.assertTrue(sample.pending(store))
        self.assertNotIn("demoGuide", store.snapshot(owner)["data"])
        with patch("platform_core.scheduled_work.tick", side_effect=RuntimeError("outage")):
            with self.assertRaisesRegex(RuntimeError, "outage"):
                sample.populate(store, owner)
        self.assertTrue(sample.pending(store))
        self.assertTrue(sample.populate(store, owner))
        data = store.snapshot(owner)["data"]
        self.assertTrue(data["demoGuide"])
        self.assertCountEqual(data["demoVisitIds"], [r["id"] for r in data["medicalVisits"]])
        self.assertEqual(len(data["demoVisitIds"]), 4)
        rules = scheduled_work.read(store, owner)
        self.assertCountEqual([r["time"] for r in rules["rules"] if r["title"].startswith("Demo · ")],
                              ["07:00", "07:30", "12:00", "18:00", "20:00"])
        self.assertEqual(len([r for r in rules["runs"] if r["title"].startswith("Demo · ")]), 5)
        rev = store.version(owner)["revision"]
        self.assertFalse(sample.populate(store, owner))
        self.assertEqual(store.version(owner)["revision"], rev)
        self.assertFalse(sample.pending(store))
        for username, caps in [("sample-finance", {"kind": "staff", "role": "财务"}),
                               ("sample-family", {"kind": "family", "residentId": "r001"})]:
            store.execute("access.create", {**caps, "username": username, "displayName": username,
                          "password": "sample-test-password"}, store.version(owner)["revision"], owner)
            token = store.login(username, "sample-test-password")[0]
            view = store.snapshot(token)["data"]
            self.assertNotIn("demoVisitIds", view)
            self.assertEqual(bool(view.get("demoGuide")), username == "sample-finance")
            with self.assertRaises(PermissionError):
                sample.populate(store, token)

    def test_legacy_requires_explicit_owner_upgrade(self):
        store, owner = self.make()
        with closing(store.connect()) as db, db:
            db.execute("DELETE FROM workspace_installation")
        self.assertFalse(sample.pending(store))
        with self.assertRaisesRegex(ValueError, "演示样本"):
            sample.populate(store, owner)
        self.assertTrue(sample.populate(store, owner, adopt_legacy=True))
        self.assertTrue(store.snapshot(owner)["data"]["demoGuide"])

    def test_real_workspace_stays_empty_even_if_reopened_in_demo_mode(self):
        real, owner = self.make("empty", prepare_sample=True)
        reopened = Store(real.path, initial_data="demo", prepare_sample=True)
        self.assertFalse(reopened.created_workspace)
        self.assertFalse(sample.pending(reopened))
        with self.assertRaisesRegex(ValueError, "空白机构"):
            sample.populate(reopened, owner, adopt_legacy=True)
        with closing(reopened.connect()) as db, db:
            db.execute("DELETE FROM workspace_installation")
        with self.assertRaisesRegex(ValueError, "演示样本"):
            sample.populate(reopened, owner, adopt_legacy=True)
        self.assertEqual(reopened.snapshot(owner)["data"]["residents"], [])
