"""Check personal access and session revocation through the same service used by the PC client."""

from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from platform_core.store import SignedOut, Store


class PersonalAccountTests(unittest.TestCase):
    current = "personal-account-local-fixture"
    replacement = "replacement-local-fixture"

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": self.current}):
            self.store = Store(Path(folder.name) / "site.sqlite")
        self.owner, self.owner_user = self.store.login("owner", self.current)

    def call(self, token, action, **payload):
        revision = self.store.version(token)["revision"]
        return self.store.execute(action, payload, revision, token)

    def create(self, username, **extra):
        self.call(
            self.owner,
            "access.create",
            username=username,
            displayName=username,
            password=self.current,
            **extra,
        )
        return self.store.login(username, self.current)

    def test_only_self_can_change_own_password_and_all_its_sessions_end(self):
        for name, account in (
            ("staff-p", {"kind": "staff", "role": "护工"}),
            ("family-p", {"kind": "family", "residentId": "r001"}),
        ):
            with self.subTest(account=name):
                token, user = self.create(name, **account)
                second, _ = self.store.login(name, self.current)
                before = self.store.version(token)["revision"]
                for invalid in (
                    {"currentPassword": "incorrect", "newPassword": self.replacement},
                    {"currentPassword": self.current, "newPassword": self.current},
                    {
                        "id": self.owner_user["id"],
                        "currentPassword": self.current,
                        "newPassword": self.replacement,
                    },
                ):
                    with self.assertRaises(ValueError):
                        self.call(token, "account.changePassword", **invalid)
                self.assertEqual(self.store.version(second)["revision"], before)
                self.call(
                    token,
                    "account.changePassword",
                    currentPassword=self.current,
                    newPassword=self.replacement,
                )
                for previous in (token, second):
                    with self.assertRaises(SignedOut):
                        self.store.snapshot(previous)
                with self.assertRaises(PermissionError):
                    self.store.login(name, self.current)
                self.assertEqual(
                    self.store.login(name, self.replacement)[1]["id"], user["id"]
                )
                event = self.store.snapshot(self.owner)["audit"][0]
                self.assertEqual(
                    (event["action"], event["actorId"]),
                    ("account.changePassword", user["id"]),
                )
                self.assertNotIn(self.current, json.dumps(event))
                self.assertNotIn(self.replacement, json.dumps(event))

    def test_self_view_tracks_effective_routes_combined_grants_and_hidden_modules(self):
        token, user = self.create(
            "no-domain",
            kind="staff",
            role="自定义",
            permissions=["assistants", "voice.confirm"],
        )
        data = self.store.snapshot(token)["data"]
        self.assertCountEqual(
            [p["id"] for p in data["selfAccess"]["permissions"]],
            ["assistants", "voice.confirm"],
        )
        self.assertIn("account", data["selfAccess"]["routes"])
        for route in ("assistants", "inbox", "access", "settings"):
            self.assertNotIn(route, data["selfAccess"]["routes"])
        self.assertNotIn("agent.start", data["allowedActions"])
        self.assertNotIn("gw.confirm", data["allowedActions"])
        self.assertEqual(data["residents"], [])
        self.call(
            self.owner,
            "access.update",
            id=user["id"],
            permissions=["assistants", "voice.confirm", "care"],
        )
        self.call(self.owner, "access.settings", hiddenRoutes=["inbox"])
        updated = self.store.snapshot(token)["data"]
        self.assertIn("assistants", updated["selfAccess"]["routes"])
        self.assertIn("gw.confirm", updated["allowedActions"])
        self.assertNotIn("inbox", updated["selfAccess"]["routes"])
