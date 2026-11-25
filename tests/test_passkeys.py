from contextlib import closing
from datetime import datetime, timedelta
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from platform_core import access, passkeys
from platform_core.store import Store


@unittest.skipUnless(find_spec("webauthn"), "optional WebAuthn dependency")
class Passkeys(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.now = datetime.fromisoformat("2026-11-25T10:00:00+08:00")
        self.store = Store(Path(folder.name) / "passkey.sqlite3", now=lambda: self.now,
                           initial_owner_password="test-owner-passkey-password")
        self.token, self.owner = self.store.login("owner", "test-owner-passkey-password")
        self.origin = "http://localhost:8765"

    def test_registration_requires_verified_phone_and_binds_to_origin(self):
        request = {"currentPassword": "test-owner-passkey-password"}
        with self.assertRaisesRegex(ValueError, "验证本人手机号"):
            passkeys.options(self.store, self.token, "enroll-options", request, self.origin, "local")
        with closing(self.store.connect()) as db, db:
            db.execute("INSERT INTO identity_contacts VALUES(?,?,?,1)", (self.owner["id"], "sms", "+8613900001010"))
        issued = passkeys.options(self.store, self.token, "enroll-options", request, self.origin, "local")
        self.assertEqual(issued["options"]["authenticatorSelection"]["userVerification"], "required")
        self.assertEqual(issued["options"]["authenticatorSelection"]["residentKey"], "required")
        invalid = {"ticket": issued["ticket"], "label": "设备", "credential": {"id": "YWJj"}}
        with self.assertRaisesRegex(PermissionError, "失效"):
            passkeys.finish(self.store, self.token, "enroll", invalid, "https://elsewhere.example.invalid")
        with self.assertRaisesRegex(PermissionError, "未能验证"):
            passkeys.finish(self.store, self.token, "enroll", invalid, self.origin)
        with self.assertRaisesRegex(PermissionError, "失效"):
            passkeys.finish(self.store, self.token, "enroll", invalid, self.origin)

    def test_signin_challenge_expires_and_password_recovery_revokes_credentials(self):
        request = passkeys.options(self.store, None, "signin-options", {}, self.origin, "local")
        self.now += timedelta(seconds=passkeys.LIFETIME)
        with self.assertRaisesRegex(PermissionError, "失效"):
            passkeys.finish(self.store, None, "signin", {"ticket": request["ticket"], "credential": {"id": "YWJj"}}, self.origin)
        with closing(self.store.connect()) as db, db:
            db.execute("INSERT INTO identity_passkeys VALUES(?,?,?,?,?,?,?,?)",
                       ("YWJj", self.owner["id"], self.origin, b"fixture", 0, "设备", self.now.isoformat(), ""))
            access._replace_password(db, self.owner, "test-recovered-private-password")
            self.assertEqual(db.execute("SELECT count(*) FROM identity_passkeys").fetchone()[0], 0)
            self.assertIsNone(access.authenticate(db, self.token))
