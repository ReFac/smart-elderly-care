"""A relative's optional service list is confined to their verified resident."""

from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from platform_core.store import Store


class FamilyServiceAccessTests(unittest.TestCase):
    password = "family-service-fixture"

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "workspace.sqlite3"
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": self.password}):
            self.store = Store(self.path)
        self.owner, _ = self.store.login("owner", self.password)

    def command(self, token, action, **payload):
        self.store.execute(
            action, payload, self.store.version(token)["revision"], token
        )

    def family(self, name, bound, **extra):
        self.command(
            self.owner,
            "access.create",
            kind="family",
            username=name,
            displayName=name,
            residentId=bound,
            password=self.password,
            **extra,
        )
        return self.store.login(name, self.password)

    def test_completed_services_project_only_bound_person_on_existing_session_and_after_restart(
        self,
    ):
        family, person = self.family("first-relative", "r001")
        peer, _ = self.family("second-relative", "r001")
        other, _ = self.family("other-relative", "r002", familyServices=True)
        self.assertFalse(person["familyServices"])
        self.assertNotIn("familyServiceHistory", self.store.snapshot(family)["data"])
        with closing(self.store.connect()) as db, db:
            state = json.loads(db.execute("SELECT data FROM workspace").fetchone()[0])

            def task(day):
                return dict(
                    id=str(day),
                    title=f"服务{day}",
                    residentId="r001",
                    status="已完成",
                    date=f"2026-10-{day:02}",
                    time="08:30",
                    operator="不公开",
                    note="护理备注",
                    completedAt=f"2026-10-{day:02}",
                )

            state["tasks"] = [task(i) for i in range(1, 32)]
            state["tasks"].append(
                {
                    **task(1),
                    "id": "new",
                    "title": "补录服务",
                    "completedAt": "2026-11-15",
                }
            )
            state["tasks"].append(
                {**task(2), "id": "uncompleted", "status": "待执行", "title": "未完成"}
            )
            state["tasks"].append(
                {
                    **task(3),
                    "id": "elsewhere",
                    "residentId": "r002",
                    "title": "其他住户",
                }
            )
            db.execute("UPDATE workspace SET data=?", (json.dumps(state),))
        self.command(self.owner, "access.update", id=person["id"], familyServices=True)
        result = Store(self.path).snapshot(family)["data"]
        history = result["familyServiceHistory"]
        self.assertEqual(len(history), 30)
        self.assertEqual(
            [r["title"] for r in history],
            ["补录服务", *(f"服务{i}" for i in range(31, 2, -1))],
        )
        self.assertTrue(
            all(set(r) == {"date", "time", "title", "completedAt"} for r in history)
        )
        self.assertEqual(result["tasks"], [])
        self.assertEqual(result["medications"], [])
        self.assertEqual(result["bills"], [])
        self.assertNotIn("familyServiceHistory", self.store.snapshot(peer)["data"])
        self.assertEqual(
            [
                r["title"]
                for r in self.store.snapshot(other)["data"]["familyServiceHistory"]
            ],
            ["其他住户"],
        )
        self.command(self.owner, "access.update", id=person["id"], familyServices=False)
        self.assertNotIn("familyServiceHistory", self.store.snapshot(family)["data"])
        self.assertIn(
            "收回已完成服务记录查阅权限",
            self.store.snapshot(self.owner)["audit"][0]["summary"],
        )

    def test_only_owner_can_grant_option_to_a_family_target(self):
        family, relative = self.family("relative", "r001")
        self.command(
            self.owner,
            "access.create",
            kind="staff",
            username="staff-manager",
            displayName="经理",
            role="自定义",
            permissions=["staff.manage"],
            password=self.password,
        )
        manager, user = self.store.login("staff-manager", self.password)
        for actor in (manager, family):
            with self.assertRaises(PermissionError):
                self.command(
                    actor, "access.update", id=relative["id"], familyServices=True
                )
        for bad in (1, "true", None):
            with self.assertRaises(ValueError):
                self.command(
                    self.owner, "access.update", id=relative["id"], familyServices=bad
                )
        with self.assertRaises(ValueError):
            self.command(
                self.owner, "access.update", id=user["id"], familyServices=True
            )
        self.assertNotIn("familyServices", self.store.snapshot(manager)["data"]["user"])
        self.assertFalse(self.store.snapshot(family)["data"]["user"]["familyServices"])

    def test_existing_unflagged_accounts_receive_no_grant_on_migration(self):
        family, _ = self.family("old-relative", "r001")
        with closing(self.store.connect()) as db, db:
            db.execute("ALTER TABLE accounts DROP COLUMN family_services")
            db.execute("PRAGMA user_version=5")
        fresh = Store(self.path)
        self.assertFalse(fresh.snapshot(family)["data"]["user"]["familyServices"])
        self.assertNotIn("familyServiceHistory", fresh.snapshot(family)["data"])
