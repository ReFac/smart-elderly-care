from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from threading import Barrier

from platform_core import care, operations, secure_storage
from platform_core.store import Conflict, SCHEMA_VERSION, Store, TIMEZONE


class WorkspaceTransactions(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "workspace.sqlite3"
        self.date = datetime(2026, 11, 24, 10, tzinfo=TIMEZONE)
        bootstrap = "synthetic-store-password"
        environment = patch.dict("os.environ", {"NH_OWNER_PASSWORD": bootstrap})
        environment.start()
        self.addCleanup(environment.stop)
        self.store = Store(self.path, lambda: self.date)
        self.token, _ = self.store.login("owner", bootstrap)

    def execute(self, action, payload, revision):
        return self.store.execute(action, payload, revision, self.token)

    def test_owner_label_migrates_with_the_existing_login_session(self):
        with closing(self.store.connect()) as db, db:
            db.execute(
                "UPDATE accounts SET display_name='总管理员',role='总管理员' WHERE kind='owner'"
            )
        reopened = Store(self.path, lambda: self.date)
        user = reopened.snapshot(self.token)["data"]["user"]
        self.assertEqual((user["displayName"], user["role"]), ("Owner", "Owner"))
        self.assertEqual(user["username"], "owner")
        self.assertIn("settings", user["routes"])

    def test_restart_preserves_state_and_audit_and_refreshes_business_day(self):
        before = self.store.snapshot(self.token)
        self.execute("care.inquire", {"name": "走查长者"}, before["revision"])
        tomorrow = self.date + timedelta(days=1)
        reopened = Store(self.path, lambda: tomorrow).snapshot(self.token)
        self.assertEqual(reopened["today"], "2026-11-25")
        self.assertEqual(reopened["data"]["inquiries"][-1]["name"], "走查长者")
        self.assertEqual(len(reopened["data"]["tasks"]), len(before["data"]["tasks"]))
        self.assertEqual(reopened["audit"][0]["action"], "care.inquire")
        self.assertEqual(reopened["audit"][0]["revision"], reopened["revision"])

    def test_two_clients_claiming_the_same_revision_only_commit_once(self):
        gate = Barrier(2)

        def worker():
            gate.wait()
            try:
                self.execute("ops.deposit", {"residentId": "r001", "amount": 100}, 0)
                return "committed"
            except Conflict:
                return "conflict"

        before = self.store.snapshot(self.token)["data"]["depositEntries"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: worker(), range(2)))
        after = self.store.snapshot(self.token)
        self.assertCountEqual(outcomes, ["committed", "conflict"])
        self.assertEqual(len(after["data"]["depositEntries"]), len(before) + 1)
        self.assertEqual(len(after["audit"]), 1)

    def test_invalid_actions_do_not_change_records_or_revision(self):
        before = self.store.snapshot(self.token)
        for action, payload in [
            ("care.admit", {"name": "演示", "bedId": "b001"}),
            (
                "ops.stock",
                {
                    "itemId": before["data"]["inventory"][0]["id"],
                    "type": "出库",
                    "quantity": 999999,
                },
            ),
            ("ops.unknown", {}),
        ]:
            with self.assertRaises(ValueError):
                self.execute(action, payload, before["revision"])
        self.assertEqual(before, self.store.snapshot(self.token))

    def test_observed_needs_create_reviewable_tasks_and_match_actual_shift(self):
        before = self.store.snapshot(self.token)
        person = before["data"]["residents"][0]
        bed = next(b for b in before["data"]["beds"] if b["id"] == person["bedId"])
        shift = next(s for s in before["data"]["shifts"] if s["area"] == bed["ward"])
        result = self.execute(
            "care.assess",
            {
                "residentId": person["id"],
                "level": "半失能",
                "note": "本人提出活动与起居协助需求",
                "observations": {"院内活动": "需协助", "生活起居": "需协助"},
            },
            0,
        )
        draft = self.store.snapshot(self.token)["data"]
        self.assertEqual(len(before["data"]["tasks"]), len(draft["tasks"]))
        plan = draft["plans"][-1]
        self.assertEqual(plan["assignee"], shift["staff"])
        self.execute(
            "care.approvePlan",
            {"planId": plan["id"], "reviewer": "复核人"},
            result["revision"],
        )
        titles = [
            t["title"]
            for t in self.store.snapshot(self.token)["data"]["tasks"]
            if t.get("planId") == plan["id"]
        ]
        self.assertCountEqual(titles, ["起居照护协助", "院内活动陪伴", "护理需求复评"])


class WorkspaceMigration(unittest.TestCase):
    def test_v1_workspace_and_four_column_audit_survive_upgrade_and_next_write(self):
        date = datetime(2026, 11, 24, 10, tzinfo=TIMEZONE)
        day = "2026-07-16"
        legacy = operations.seed(day, care.seed(day))
        for move in legacy["bedMoves"]:
            move.pop("cardCode", None)
        care.apply(legacy, "care.inquire", {"name": "历史来访人"}, day)
        payload = json.dumps(legacy, ensure_ascii=False)
        audit = [
            (1, day + "T09:00:00", "ops.report", "旧版报送已登记"),
            (2, day + "T09:30:00", "care.inquire", "旧版来访已登记"),
        ]
        password = "migration-only-417"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "old.sqlite"
            # Construct the two-table v1 database before opening any contemporary Store.
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript("""
                    PRAGMA user_version=1;
                    CREATE TABLE workspace (id INTEGER PRIMARY KEY CHECK(id=1),
                        revision INTEGER NOT NULL, data TEXT NOT NULL);
                    CREATE TABLE audit (revision INTEGER PRIMARY KEY, at TEXT NOT NULL,
                        action TEXT NOT NULL, summary TEXT NOT NULL);
                """)
                db.execute("INSERT INTO workspace VALUES (1,2,?)", (payload,))
                db.executemany("INSERT INTO audit VALUES (?,?,?,?)", audit)
            with self.assertRaisesRegex(ValueError, "migrate"):
                Store(path, lambda: date)
            secure_storage.migrate_database(path)
            with patch.dict("os.environ", {"NH_OWNER_PASSWORD": password}):
                store = Store(path, lambda: date)
            token, _ = store.login("owner", password)
            migrated = store.snapshot(token)
            self.assertEqual(migrated["revision"], 2)
            self.assertEqual(migrated["data"]["inquiries"][-1]["name"], "历史来访人")
            self.assertEqual(migrated["data"]["bedMoves"], legacy["bedMoves"])
            self.assertEqual(migrated["data"]["agentRuns"], [])
            with closing(store.connect()) as db:
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION
                )
                self.assertEqual(
                    db.execute("SELECT data FROM workspace").fetchone()[0], payload
                )
                rows = db.execute(
                    "SELECT revision,at,action,summary FROM audit ORDER BY revision"
                )
                self.assertEqual([tuple(r) for r in rows], audit)
            store.execute("care.inquire", {"name": "迁移后来访人"}, 2, token)
            reopened = Store(path, lambda: date).snapshot(token)
            self.assertEqual(reopened["revision"], 3)
            self.assertEqual([a["revision"] for a in reopened["audit"]], [3, 2, 1])
            self.assertTrue(reopened["audit"][0]["actorId"])
            self.assertEqual(reopened["audit"][1]["actorId"], "")
            self.assertEqual(
                [r["name"] for r in reopened["data"]["inquiries"][-2:]],
                ["历史来访人", "迁移后来访人"],
            )
