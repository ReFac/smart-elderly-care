"""Illustrated example histories keep their originals behind the clinical access checks."""

from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from platform_core import medical_visits
from platform_core.store import Store, TIMEZONE
from platform_core.sample import medical as demo_medical


class DemoMedicalTests(unittest.TestCase):
    def make_store(self, mode="demo"):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        store = Store(
            Path(directory.name) / "institution.sqlite",
            now=lambda: datetime(2026, 11, 25, 12, tzinfo=TIMEZONE),
            initial_data=mode,
            initial_owner_password="synthetic-owner-example",
        )
        return store, store.login("owner", "synthetic-owner-example")[0]

    def test_seed_and_resume_open_scoped_originals(self):
        store, owner = self.make_store()
        # Interrupt after the follow-up is saved and before its supplemental sheet is signed.
        original = demo_medical._encoded

        def stop_at_supplement(key):
            if key == "bp-measurements":
                raise OSError("unavailable sample sheet")
            return original(key)

        with patch.object(demo_medical, "_encoded", side_effect=stop_at_supplement):
            with self.assertRaisesRegex(OSError, "unavailable sample"):
                demo_medical.seed_medical(store, owner)
        self.assertEqual(demo_medical.seed_medical(store, owner), 3)
        revision = store.version(owner)["revision"]
        self.assertEqual(demo_medical.seed_medical(store, owner), 0)
        self.assertEqual(store.version(owner)["revision"], revision)
        data = store.snapshot(owner)["data"]
        self.assertCountEqual(
            [v["residentId"] for v in data["medicalVisits"]],
            ["r001", "r001", "r002", "r003"],
        )
        for visit in data["medicalVisits"]:
            (attachment,) = visit["attachments"]
            raw, mime = medical_visits.original(store, owner, attachment["id"])
            self.assertEqual(mime, "application/pdf")
            self.assertEqual(attachment["pageCount"], 1)
            self.assertTrue(raw.startswith(b"%PDF-"))
            if shutil.which("pdftotext"):
                words = subprocess.check_output(
                    ["pdftotext", "-", "-"], input=raw
                ).decode()
                self.assertIn(visit["fields"]["eventDate"], words)
                self.assertIn(attachment["filename"].split("-")[0], words)
                self.assertIn("虚构演示病例", words)
        (supplement,) = data["medicalDocuments"]
        followup = next(
            v for v in data["medicalVisits"] if v["id"] == supplement["visitId"]
        )
        self.assertEqual(followup["attachments"][0]["filename"], "沈月兰-复诊记录.pdf")
        self.assertEqual(store.photo(owner, supplement["id"])[1], "application/pdf")
        store.execute(
            "access.create",
            {
                "username": "sample-family",
                "kind": "family",
                "displayName": "演示家属",
                "residentId": "r001",
                "password": "synthetic-family-test",
            },
            revision,
            owner,
        )
        family = store.login("sample-family", "synthetic-family-test")[0]
        with self.assertRaises(PermissionError):
            medical_visits.original(store, family, followup["attachments"][0]["id"])
        with self.assertRaises(PermissionError):
            store.photo(family, supplement["id"])

    def test_empty_institution_is_not_populated(self):
        store, owner = self.make_store("empty")
        revision = store.version(owner)["revision"]
        self.assertEqual(demo_medical.seed_medical(store, owner), 0)
        self.assertEqual(store.version(owner)["revision"], revision)
        self.assertEqual(store.snapshot(owner)["data"]["medicalVisits"], [])
