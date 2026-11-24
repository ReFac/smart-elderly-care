"""Exercise employee account delegation through the same revisioned commands as the PC UI."""

from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from platform_core import access
from platform_core.store import SignedOut, Store


class StaffAdminTests(unittest.TestCase):
    password = "delegation-local-fixture"
    grants = ["residents", "care", "audit", "staff.manage"]

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": self.password}):
            self.store = Store(Path(directory.name) / "work.sqlite3")
        self.owner, self.owner_user = self.store.login("owner", self.password)
        self.manager, self.manager_user = self.employee("duty-lead", self.grants)

    def run_command(self, token, action, **payload):
        revision = self.store.version(token)["revision"]
        return self.store.execute(action, payload, revision, token)

    def employee(self, username, grants, creator=None):
        self.run_command(
            creator or self.owner,
            "access.create",
            kind="staff",
            username=username,
            displayName=username,
            password=self.password,
            role="自定义",
            permissions=grants,
        )
        return self.store.login(username, self.password)

    def test_delegated_directory_and_preview_match_real_effective_permissions(self):
        staff, target = self.employee("floor-aide", ["care"], self.manager)
        self.employee("medical-lead", ["clinical"])
        self.employee("other-manager", ["staff.manage"])
        self.run_command(
            self.owner,
            "access.create",
            kind="family",
            username="relative",
            displayName="亲属",
            password=self.password,
            residentId="r001",
        )
        snapshot = self.store.snapshot(self.manager)["data"]
        self.assertIn("access", snapshot["user"]["routes"])
        self.assertNotIn("settings", snapshot["user"]["routes"])
        self.assertEqual(
            snapshot["accessManagement"], {"scope": "staff", "canBindFamily": False}
        )
        self.assertEqual([a["id"] for a in snapshot["accounts"]], [target["id"]])
        grants = set(self.grants) - {"staff.manage"}
        self.assertEqual(set(snapshot["permissionOptions"]), grants)
        self.assertTrue(all(set(v) <= grants for v in snapshot["rolePresets"].values()))
        self.assertNotIn("accessManagement", self.store.snapshot(staff)["data"])
        self.assertNotIn("access.settings", snapshot["allowedActions"])
        with closing(self.store.connect()) as db:
            preview = access.preview(
                db,
                self.manager_user,
                {
                    "id": target["id"],
                    "kind": "staff",
                    "role": "护工",
                    "permissions": ["residents", "care"],
                },
            )
        self.run_command(
            self.manager,
            "access.update",
            id=target["id"],
            role="护工",
            permissions=["residents", "care"],
        )
        effective = self.store.snapshot(staff)["data"]
        for field in ("permissions", "routes"):
            self.assertEqual(preview[field], effective["user"][field])
        self.assertEqual(preview["allowedActions"], effective["allowedActions"])
        self.assertIn("care.handover", preview["allowedActions"])
        audit = self.store.snapshot(self.owner)["audit"][0]
        self.assertEqual(audit["actorId"], self.manager_user["id"])
        self.assertIn("floor-aide", audit["summary"])
        self.assertIn("授予", audit["summary"])
        self.assertFalse(
            any(
                r["action"].startswith("access.")
                for r in self.store.activity(self.manager)["rows"]
            )
        )

    def test_manager_cannot_touch_privileged_targets_or_inflate_grants_using_role_defaults(
        self,
    ):
        _, target = self.employee("floor-aide", ["care"])
        _, treasurer = self.employee("treasurer", ["finance"])
        _, manager = self.employee("other-manager", ["staff.manage"])
        self.run_command(
            self.owner,
            "access.create",
            kind="family",
            username="relative",
            displayName="亲属",
            password=self.password,
            residentId="r001",
        )
        _, family = self.store.login("relative", self.password)
        version = self.store.version(self.manager)["revision"]
        for employee in (
            treasurer,
            manager,
            self.manager_user,
            self.owner_user,
            family,
        ):
            for action, fields in [
                ("access.update", {"permissions": []}),
                ("access.update", {"enabled": False}),
                ("access.password", {"password": "reset-not-allowed"}),
            ]:
                with (
                    self.subTest(target=employee["username"], action=action),
                    self.assertRaises(PermissionError),
                ):
                    self.run_command(self.manager, action, id=employee["id"], **fields)
        for payload in (
            {"role": "护士"},
            {"permissions": ["staff.manage"]},
            {"permissions": ["medical.write"]},
            {"permissions": ["finance"]},
        ):
            with self.subTest(payload=payload), self.assertRaises(PermissionError):
                self.run_command(
                    self.manager, "access.update", id=target["id"], **payload
                )
            with (
                closing(self.store.connect()) as db,
                self.assertRaises(PermissionError),
            ):
                access.preview(
                    db,
                    self.manager_user,
                    {"kind": "staff", "id": target["id"], **payload},
                )
        for kind, role in (("family", "自定义"), ("staff", "院长")):
            with self.assertRaises(PermissionError):
                self.run_command(
                    self.manager,
                    "access.create",
                    kind=kind,
                    role=role,
                    username="extra",
                    displayName="不可创建",
                    password=self.password,
                )
        with self.assertRaises(PermissionError):
            self.run_command(self.manager, "access.settings", brandName="其他名称")
        self.assertEqual(self.store.version(self.manager)["revision"], version)

    def test_reset_disable_and_live_revocation(self):
        old, target = self.employee("floor-aide", ["care"])
        new_password = "new-local-password"
        self.run_command(
            self.manager, "access.password", id=target["id"], password=new_password
        )
        with self.assertRaises(SignedOut):
            self.store.version(old)
        replacement, _ = self.store.login("floor-aide", new_password)
        self.run_command(self.manager, "access.update", id=target["id"], enabled=False)
        with self.assertRaises(SignedOut):
            self.store.version(replacement)
        self.run_command(self.manager, "access.update", id=target["id"], enabled=True)
        self.assertTrue(self.store.login("floor-aide", new_password)[0])
        self.run_command(
            self.owner, "access.update", id=target["id"], permissions=["finance"]
        )
        self.assertEqual(self.store.snapshot(self.manager)["data"]["accounts"], [])
        with self.assertRaises(PermissionError):
            self.run_command(
                self.manager, "access.password", id=target["id"], password=self.password
            )
        self.run_command(
            self.owner,
            "access.update",
            id=self.manager_user["id"],
            permissions=["care"],
        )
        current = self.store.snapshot(self.manager)["data"]
        self.assertNotIn("access", current["user"]["routes"])
        self.assertNotIn("accounts", current)
        with self.assertRaises(PermissionError):
            self.run_command(
                self.manager,
                "access.create",
                kind="staff",
                role="自定义",
                username="new-staff",
                displayName="员工",
                password=self.password,
            )

    def test_region_manager_sees_only_contained_subtrees_and_checks_scope_on_every_write(
        self,
    ):
        with closing(self.store.connect()) as db:
            floor, room = db.execute(
                "SELECT floorId,id FROM facility_rooms WHERE number='101'"
            ).fetchone()
            other_room = db.execute(
                "SELECT id FROM facility_rooms WHERE number='201'"
            ).fetchone()[0]
        regions = {
            "duty-lead": {"floorIds": [floor]},
            "assigned": {"roomIds": [room]},
            "outside": {"roomIds": [other_room]},
            "other-site": {"institutionId": "different-site"},
            "empty-shift": {"roomIds": []},
        }

        def resolver(db, actor):
            # A host can base its policy on the persisted row. A post-edit scope check
            # must therefore run after writing, within the same rollbackable transaction.
            display = db.execute(
                "SELECT display_name FROM accounts WHERE id=?", (actor["id"],)
            ).fetchone()
            if display and display[0] == "转至全院":
                return {}
            return regions.get(actor["username"], {})

        self.store = Store(self.store.path, facility_policy=resolver)
        _, assigned = self.employee("assigned", ["care"], self.manager)
        _, outside = self.employee("outside", ["care"])
        self.employee("other-site", ["care"])
        self.employee("empty-shift", ["care"], self.manager)
        directory = self.store.snapshot(self.manager)["data"]["accounts"]
        self.assertCountEqual(
            [a["username"] for a in directory], ["assigned", "empty-shift"]
        )
        self.assertIn(
            "care",
            self.store.access_preview(self.manager, {"id": assigned["id"]})[
                "permissions"
            ],
        )
        with self.assertRaises(PermissionError):
            self.store.access_preview(self.manager, {"id": outside["id"]})
        with self.assertRaises(PermissionError):
            self.run_command(
                self.manager,
                "access.password",
                id=outside["id"],
                password=self.password,
            )
        before = self.store.version(self.manager)["revision"]
        with self.assertRaises(PermissionError):
            self.employee("defaults-full-site", ["care"], self.manager)
        with self.assertRaises(PermissionError):
            self.run_command(
                self.manager, "access.update", id=assigned["id"], displayName="转至全院"
            )
        self.assertEqual(self.store.version(self.manager)["revision"], before)
        accounts = self.store.snapshot(self.owner)["data"]["accounts"]
        self.assertNotIn("defaults-full-site", [a["username"] for a in accounts])
        self.assertEqual(
            next(a for a in accounts if a["id"] == assigned["id"])["displayName"],
            "assigned",
        )
        regions["duty-lead"] = {"roomIds": [room]}
        regions["assigned"] = {"floorIds": [floor]}
        with self.assertRaises(PermissionError):
            self.run_command(
                self.manager,
                "access.password",
                id=assigned["id"],
                password=self.password,
            )
