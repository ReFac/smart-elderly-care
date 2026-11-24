import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest
from unittest.mock import patch

from platform_core import access, care, operations
from platform_core.store import Store

DAY = "2026-11-24"
PASSWORD = "internal-test-only-417"


class AccountPermissions(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        with patch.dict(os.environ, {"NH_OWNER_PASSWORD": PASSWORD}):
            access.init(self.db)
        self.token, self.owner = access.login(self.db, "owner", PASSWORD)
        self.state = operations.seed(DAY, care.seed(DAY))

    def create(self, name="staff-one", role="护工", **extra):
        values = {
            "kind": "staff",
            "username": name,
            "displayName": "测试人员",
            "password": PASSWORD,
            "role": role,
            **extra,
        }
        access.apply(self.db, self.state, "access.create", values, self.owner)
        return access.login(self.db, name, PASSWORD)

    def test_removes_reversible_legacy_credentials_and_preserves_current_login(self):
        with (
            tempfile.TemporaryDirectory() as d,
            patch.dict(os.environ, {"NH_OWNER_PASSWORD": PASSWORD}),
        ):
            store = Store(Path(d) / "workspace.sqlite3")
            db = store.connect()
            self.addCleanup(db.close)
            self.assertFalse((Path(d) / ".owner-password").exists())
            if os.name == "posix":
                self.assertEqual(
                    stat.S_IMODE(store.storage_key_file.stat().st_mode), 0o600
                )
            db.execute(
                "CREATE TABLE storage_bootstrap(id INTEGER PRIMARY KEY,password TEXT)"
            )
            db.execute("INSERT INTO storage_bootstrap VALUES(1,?)", (PASSWORD,))
            access.init(db)
            self.assertIsNone(
                db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='storage_bootstrap'"
                ).fetchone()
            )
            _, user = access.login(db, "owner", PASSWORD)
            with self.assertRaises(PermissionError):
                access.apply(
                    db,
                    self.state,
                    "access.password",
                    {"id": user["id"], "password": PASSWORD},
                    user,
                )

    def test_live_revocation_independent_sessions_and_disabled_cannot_login(self):
        token, user = self.create()
        other, unused = access.login(self.db, user["username"], PASSWORD)
        self.assertNotEqual(token, other)
        access.logout(self.db, other)
        self.assertIsNone(access.authenticate(self.db, other))
        self.assertIn("care", access.authenticate(self.db, token)["permissions"])
        access.apply(
            self.db,
            self.state,
            "access.update",
            {"id": user["id"], "permissions": ["shifts"]},
            self.owner,
        )
        self.assertEqual(access.authenticate(self.db, token)["permissions"], ["shifts"])
        access.apply(
            self.db,
            self.state,
            "access.update",
            {"id": user["id"], "enabled": False},
            self.owner,
        )
        self.assertIsNone(access.authenticate(self.db, token))
        with self.assertRaises(PermissionError):
            access.login(self.db, user["username"], PASSWORD)
        access.apply(
            self.db,
            self.state,
            "access.update",
            {"id": user["id"], "enabled": True},
            self.owner,
        )
        self.assertIsNone(access.authenticate(self.db, token))
        self.assertIsNotNone(access.login(self.db, user["username"], PASSWORD)[0])

    def test_family_sees_only_own_name_and_account(self):
        first = self.state["residents"][0]["id"]
        _, user = self.create("family-a", kind="family", residentId=first)
        data = access.project(self.db, self.state, user)
        self.assertEqual(
            data["residents"],
            [{"id": first, "name": self.state["residents"][0]["name"]}],
        )
        self.assertEqual(data["user"]["routes"], ["family", "tour", "faq", "account"])
        for key in ("tasks", "medications", "bills", "reports", "suggestions", "beds"):
            self.assertEqual(data[key], [])
        for key in ("settings", "accounts", "rolePresets", "permissionOptions"):
            self.assertNotIn(key, data)
        with self.assertRaises(PermissionError):
            access.authorize(user, "care.completeTask", {}, self.state)
        with self.assertRaises(ValueError):
            access.apply(
                self.db,
                self.state,
                "access.update",
                {"id": user["id"], "residentId": "r002"},
                self.owner,
            )

    def test_employee_cannot_promote_self_or_read_unrelated_fields(self):
        _, staff = self.create()
        with self.assertRaises(PermissionError):
            access.apply(
                self.db,
                self.state,
                "access.update",
                {"id": staff["id"], "permissions": ["medical"]},
                staff,
            )
        with self.assertRaises(PermissionError):
            access.authorize(staff, "gw.review", {}, self.state)
        with self.assertRaises(PermissionError):
            access.authorize(staff, "ops.bill", {}, self.state)
        with self.assertRaises(PermissionError):
            access.authorize(staff, "dossier.relative", {}, self.state)
        with self.assertRaises(ValueError):
            self.create("extra-owner", kind="owner")
        data = access.project(
            self.db, {**self.state, "futurePrivate": [{"secret": True}]}, staff
        )
        self.assertNotIn("contact", data["residents"][0])
        self.assertNotIn("risk", data["residents"][0])
        self.assertNotIn("allergies", data["residents"][0])
        self.assertNotIn("futurePrivate", data)
        for key in (
            "inventory",
            "bills",
            "vitals",
            "medications",
            "reports",
            "archives",
            "suggestions",
        ):
            self.assertEqual(data[key], [])
        self.assertTrue(data["tasks"])
        self.assertNotIn("access", staff["routes"])

    def test_owner_registers_signature_identity_independently_of_display_name(self):
        _, nurse = self.create(role="护士")
        fields = {"accountId": nurse["id"], "realName": "林雅慧"}
        with self.assertRaises(PermissionError):
            access.apply(self.db, self.state, "access.setRealName", fields, nurse)
        access.apply(self.db, self.state, "access.setRealName", fields, self.owner)
        access.apply(
            self.db, self.state, "access.setRealName",
            {"accountId": self.owner["id"], "realName": "陈安"}, self.owner,
        )
        self.assertEqual(access.account(self.db, self.owner["id"])["displayName"], "Owner")
        self.assertEqual(access.account(self.db, nurse["id"])["displayName"], "测试人员")
        self.assertEqual(access.real_name(self.db, nurse["id"]), "林雅慧")
        self.assertEqual(access.project(self.db, self.state, nurse)["signatureRealName"], "林雅慧")
        _, colleague = self.create(name="another-staff")
        self.assertEqual(access.project(self.db, self.state, colleague)["signatureRealName"], "")

    def test_notes_and_audit_follow_source_grants(self):
        _, staff = self.create(permissions=["inventory", "assistants", "audit"])
        allowed = access.project(self.db, self.state, staff)["suggestions"]
        self.assertTrue(allowed)
        self.assertEqual({s["category"] for s in allowed}, {"物资管控"})
        category = next(
            s for s in self.state["suggestions"] if s["category"] == "运营分析"
        )
        with self.assertRaises(PermissionError):
            access.authorize(staff, "ops.review", {"id": category["id"]}, self.state)
        with self.assertRaises(PermissionError):
            access.authorize(staff, "ops.suggest", {"category": "日常照护"}, self.state)
        self.assertTrue(access.can_view_audit(staff, "ops.stock"))
        self.assertFalse(access.can_view_audit(staff, "ops.pay"))
        self.assertFalse(access.can_view_audit(staff, "access.update"))
        self.assertFalse(access.can_view_audit(staff, "ops.review"))

    def test_appearance_edit_cannot_replace_platform_credentials_or_entitlement(self):
        _, staff = self.create()
        with patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": "test-value-must-stay-in-environment"}
        ):
            payload = {
                "brandName": "机构演示",
                "theme": "ocean",
                "hiddenRoutes": ["inventory"],
            }
            with self.assertRaises(PermissionError):
                access.apply(self.db, self.state, "access.settings", payload, staff)
            access.apply(self.db, self.state, "access.settings", payload, self.owner)
            admin = access.project(self.db, self.state, self.owner)
            public = access.project(self.db, self.state, staff)
            for override in (
                {"deepseekEnabled": True},
                {"deepseekModel": "client-choice"},
            ):
                with self.assertRaises(ValueError):
                    access.apply(
                        self.db, self.state, "access.settings", override, self.owner
                    )
            self.assertEqual(public["uiSettings"]["hiddenRoutes"], ["inventory"])
            self.assertNotIn("settings", public)
            self.assertNotIn("test-value-must-stay-in-environment", str(admin))
            self.assertNotIn("test-value-must-stay-in-environment", str(public))
            with self.assertRaises(ValueError):
                access.apply(
                    self.db,
                    self.state,
                    "access.settings",
                    {"apiKey": "secret"},
                    self.owner,
                )

    def test_known_accounts_rate_limited_and_sessions_expire(self):
        with patch("platform_core.access.time.time", return_value=10000):
            _, user = self.create()
            for i in range(access.MAX_FAILURES):
                with self.assertRaises(PermissionError):
                    access.login(self.db, user["username"], "wrong")
            with self.assertRaises(access.LoginThrottled):
                access.login(self.db, user["username"], PASSWORD)
        with patch(
            "platform_core.access.time.time", return_value=10000 + access.WINDOW + 1
        ):
            token, unused = access.login(self.db, user["username"], PASSWORD)
        with patch(
            "platform_core.access.time.time",
            return_value=10000 + access.WINDOW + 1 + access.SESSION_LIFETIME,
        ):
            self.assertIsNone(access.authenticate(self.db, token))

    def test_nurse_and_caregiver_authority_separate(self):
        _, nurse = self.create("nurse", role="护士")
        _, aide = self.create("aide", role="护工")
        access.authorize(nurse, "gw.review", {}, self.state)
        access.authorize(nurse, "dossier.document", {}, self.state)
        with self.assertRaises(PermissionError):
            access.authorize(aide, "dossier.document", {}, self.state)
        access.authorize(aide, "gw.confirm", {}, self.state)
        _, custom = self.create("custom", permissions=["voice.confirm"])
        with self.assertRaises(PermissionError):
            access.authorize(custom, "gw.confirm", {}, self.state)
        with self.assertRaises(ValueError):
            access.authorize(nurse, "unknown.action", {}, self.state)
