from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from platform_core import reset_links, staff_resume
from platform_core.store import SignedOut, Store


class StaffOnboarding(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.now = datetime.fromisoformat("2026-11-25T10:00:00+08:00")
        self.out = []
        self.store = Store(
            Path(folder.name) / "workspace.sqlite3",
            now=lambda: self.now,
            initial_owner_password="demo-owner-password",
            reset_link_senders={"sms": lambda address, link: self.out.append((address, link))},
        )
        self.owner, _ = self.store.login("owner", "demo-owner-password")
        self.origin = "https://office.example.invalid"

    def command(self, action, payload):
        return self.store.execute(action, payload, self.store.version(self.owner)["revision"], self.owner)

    def make_staff(self, **identity):
        self.command("access.create", {
            "kind": "staff", "role": "护工", "displayName": "合成护工", "username": "sample-worker", **identity,
        })
        return next(a for a in self.store.snapshot(self.owner)["data"]["accounts"] if a["username"] == "sample-worker")

    def send(self, staff, actor=None):
        return reset_links.send(self.store, actor or self.owner, {"id": staff["id"]}, self.origin)

    def redeem(self, secret, password="private-password-chosen-by-employee"):
        return reset_links.redeem(self.store, {"token": secret, "newPassword": password})

    def test_onboarding_link_is_opaque_and_recipient_alone_sets_password(self):
        staff = self.make_staff(invitation={"channel": "sms", "destination": "13900001025"})
        self.assertTrue(staff["activationPending"])
        receipt = self.send(staff)
        mobile, link = self.out[-1]
        self.assertEqual(mobile, "+8613900001025")
        self.assertEqual(receipt, {"sent": True, "channel": "sms", "masked": "****1025"})
        self.assertTrue(link.startswith(self.origin + "/#reset="))
        secret = link.split("#reset=")[1]
        with closing(self.store.connect()) as db:
            self.assertNotIn(secret.encode(), db.execute("SELECT proof FROM identity_reset_links").fetchone()[0])
        self.redeem(secret)
        with self.assertRaisesRegex(ValueError, "失效"):
            self.redeem(secret)
        signed_in, profile = self.store.login("sample-worker", "private-password-chosen-by-employee")
        self.assertFalse(profile["activationPending"])
        self.assertTrue(self.store.snapshot(signed_in)["data"]["identityContacts"][0]["verified"])
        audit = str(self.store.activity(self.owner))
        self.assertIn("access.sendPasswordReset", audit)
        self.assertNotIn(secret, audit)
        self.assertNotIn(mobile, audit)

        with self.assertRaises(PermissionError):
            self.send(staff, signed_in)
        self.now += timedelta(seconds=61)
        self.send(staff)
        self.redeem(self.out[-1][1].split("#reset=")[1], "new-private-staff-password")
        with self.assertRaises(SignedOut):
            self.store.version(signed_in)

    def test_reset_link_expires_and_cannot_return_after_disabling_account(self):
        staff = self.make_staff(invitation={"channel": "sms", "destination": "13900001025"})
        self.send(staff)
        secret = self.out[-1][1].split("#reset=")[1]
        self.now += timedelta(minutes=10)
        with self.assertRaisesRegex(ValueError, "失效"):
            self.redeem(secret)
        self.send(staff)
        secret = self.out[-1][1].split("#reset=")[1]
        self.command("access.update", {"id": staff["id"], "enabled": False})
        self.command("access.update", {"id": staff["id"], "enabled": True})
        with self.assertRaisesRegex(ValueError, "失效"):
            self.redeem(secret)

    def test_resume_only_returns_unambiguous_completed_page_fields(self):
        raw = {"pages": [{"page": 1, "state": "complete"}, {"page": 2, "state": "partial"}], "lines": [
            {"page": 1, "line": 1, "text": "姓名：张小明"},
            {"page": 1, "line": 2, "text": "手机号：13900001025"},
            {"page": 2, "line": 1, "text": "姓名：王小明"},
            {"page": 1, "line": 3, "text": "岗位：总管理员"},
            {"page": 1, "line": 4, "text": "紧急联络人电话：13900001026"},
        ]}
        actor = self.make_staff(password="temporary-test-only-profile")
        employee, _ = self.store.login(actor["username"], "temporary-test-only-profile")
        with self.assertRaises(PermissionError):
            staff_resume.check(self.store, employee)
        with patch.object(staff_resume.document_ocr, "recognize", return_value=(raw, 2, "test-id")) as recognize:
            result = staff_resume.preview(self.store, self.owner, b"%PDF-1.4")
            self.assertEqual(recognize.call_args.kwargs, {"feature": "access.resumeOcr"})
        self.assertEqual(result["fields"], {
            "displayName": {"page": 1, "line": 1, "value": "张小明"},
            "phone": {"page": 1, "line": 2, "value": "+8613900001025"},
        })
        self.assertNotIn("role", result["fields"])
        raw["lines"].append({"page": 1, "line": 5, "text": "手机号：13900001029"})
        self.assertEqual(staff_resume.suggestions(raw)["ambiguous"], ["phone"])
