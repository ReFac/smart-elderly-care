from contextlib import closing
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from threading import BoundedSemaphore
import unittest
from unittest.mock import patch

from platform_core import identity, secure_storage, access
from platform_core.store import Store


class IdentityRecovery(unittest.TestCase):
    def setUp(self):
        td = TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        self.epoch = int(time.time())
        self.out = []
        self.deliver = lambda target, code: self.out.append((target, code))
        self.store = Store(
            self.root / "auth.sqlite",
            initial_owner_password="test-owner-password",
            code_senders={"email": self.deliver},
        )
        self.token, self.owner = self.store.login("owner", "test-owner-password")

    def do(self, action, payload):
        return self.store.execute(
            action, payload, self.store.version(self.token)["revision"], self.token
        )

    def invite(self):
        self.do(
            "access.create",
            {
                "kind": "staff",
                "role": "护士",
                "username": "round-nurse",
                "displayName": "合成员工",
                "staffDuties": ["临床护理"],
                "invitation": {
                    "channel": "email",
                    "destination": "nurse@example.invalid",
                },
            },
        )
        return next(
            r
            for r in self.store.snapshot(self.token)["data"]["accounts"]
            if r["username"] == "round-nurse"
        )

    def code(self, who="round-nurse"):
        return identity.request_code(
            self.store, {"username": who, "channel": "email", "purpose": "password"}
        )["challenge"]

    def password(self, id, code):
        return identity.finish(
            self.store,
            {
                "purpose": "password",
                "challenge": id,
                "code": code,
                "newPassword": "new-password-private",
            },
        )

    def test_invitation_and_password_reset_one_use_no_secrets_revealed(self):
        person = self.invite()
        self.assertTrue(person["activationPending"])
        self.assertEqual(person["staffDuties"], ["临床护理"])
        req = self.code()
        addr, code = self.out[-1]
        self.assertEqual(addr, "nurse@example.invalid")
        with closing(self.store.connect()) as db:
            stored = db.execute(
                "SELECT proof FROM identity_challenges WHERE id=?", (req,)
            ).fetchone()[0]
            self.assertNotEqual(code.encode(), stored)
        self.password(req, code)
        with self.assertRaises(ValueError):
            self.password(req, code)
        tok, user = self.store.login("round-nurse", "new-password-private")
        self.assertFalse(user["activationPending"])
        state = self.store.snapshot(tok)["data"]
        self.assertNotIn(addr, json.dumps(state))
        self.assertEqual(state["identityContacts"][0]["masked"], "n***@example.invalid")
        self.assertNotIn(code, str(self.store.history(self.token)))
        with self.assertRaises(PermissionError):
            self.do(
                "access.update",
                {
                    "id": user["id"],
                    "invitation": {
                        "channel": "email",
                        "destination": "other@example.invalid",
                    },
                },
            )
        with self.assertRaises(PermissionError):
            self.do(
                "access.password",
                {"id": user["id"], "password": "new-password-private"},
            )

    def test_expiry_attempt_limits_unavailable_channel_and_missing_users(self):
        self.invite()
        unknown = self.code("missing-account")
        self.assertEqual(self.out, [])
        with self.assertRaises(ValueError):
            self.password(unknown, "12345678")
        with self.assertRaisesRegex(ValueError, "未接通"):
            identity.request_code(
                self.store,
                {"username": "round-nurse", "channel": "sms", "purpose": "password"},
            )
        req = self.code()
        with self.assertRaises(access.LoginThrottled):
            self.code()
        with patch("platform_core.identity.time.time", return_value=10**10):
            with self.assertRaises(ValueError):
                self.password(req, self.out[-1][1])
        for _ in range(identity.MAX_TRIES):
            with self.assertRaises(ValueError):
                self.password(req, "abcdefgh")
        with self.assertRaises(ValueError):
            self.password(req, self.out[-1][1])

    def test_pending_delivery_capacity_is_checked_for_known_and_unknown_accounts(self):
        self.invite()
        capacity = BoundedSemaphore(1)
        with patch.object(identity, "_delivery_slots", capacity), capacity:
            for username in ("round-nurse", "unknown-account"):
                with self.assertRaisesRegex(access.LoginThrottled, "正忙"):
                    identity.request_code(self.store, {"purpose": "password", "channel": "email", "username": username}, background=True)
        with closing(self.store.connect()) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM identity_challenges").fetchone()[0], 0)
        self.assertEqual(self.out, [])

    def test_reset_challenge_invalidated_by_contact_correction_or_account_disable(self):
        staff = self.invite()
        req = self.code()
        code = self.out[-1][1]
        self.do(
            "access.update",
            {
                "id": staff["id"],
                "invitation": {
                    "channel": "email",
                    "destination": "fixed@example.invalid",
                },
            },
        )
        with self.assertRaises(ValueError):
            self.password(req, code)
        with patch("platform_core.identity.time.time", return_value=self.epoch + 61):
            req = self.code()
            code = self.out[-1][1]
            self.assertEqual(self.out[-1][0], "fixed@example.invalid")
            self.do("access.update", {"id": staff["id"], "enabled": False})
            self.do("access.update", {"id": staff["id"], "enabled": True})
            with self.assertRaises(ValueError):
                self.password(req, code)

    def test_contact_change_requires_prior_and_new_proofs_disaster_quarantines_old_address(
        self,
    ):
        def request(purpose, **fields):
            return identity.request_code(
                self.store,
                {"purpose": purpose, "channel": "email", **fields},
                token=self.token,
            )

        def bind(req, code):
            return identity.finish(
                self.store,
                {"purpose": "bind", "challenge": req["challenge"], "code": code},
                token=self.token,
            )

        with patch("platform_core.identity.time.time", return_value=self.epoch):
            first = request(
                "bind",
                currentPassword="test-owner-password",
                destination="old@example.invalid",
            )
            bind(first, self.out[-1][1])
        with patch("platform_core.identity.time.time", return_value=self.epoch + 61):
            with self.assertRaises(ValueError):
                request(
                    "bind",
                    currentPassword="test-owner-password",
                    destination="new@example.invalid",
                )
            old = request("verifyContact")
            self.assertEqual(self.out[-1][0], "old@example.invalid")
            nxt = request(
                "bind",
                currentPassword="test-owner-password",
                destination="new@example.invalid",
                existingChallenge=old["challenge"],
                existingCode=self.out[-1][1],
            )
            self.assertEqual(self.out[-1][0], "new@example.invalid")
            bind(nxt, self.out[-1][1])
        with self.assertRaises(PermissionError):
            identity.request_code(
                self.store,
                {
                    "purpose": "bind",
                    "channel": "email",
                    "destination": "fake@example.invalid",
                },
                host_owner=True,
            )
        packet = self.root / "point.akbak"
        newdb = self.root / "new.sqlite"
        secure_storage.create_snapshot(self.store, packet)
        secure_storage.restore_snapshot(packet, newdb, self.store.storage_key_file)
        restored = Store(newdb, code_senders={"email": self.deliver})
        old_len = len(self.out)
        identity.request_code(
            restored, {"purpose": "password", "username": "owner", "channel": "email"}
        )
        self.assertEqual(len(self.out), old_len)
        self.assertTrue(restored.login("owner", "test-owner-password")[0])
