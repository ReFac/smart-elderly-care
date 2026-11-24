"""Room-bounded Agent dispatch, historical grants, and cloud input minimization."""

from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from platform_core import agents, facility, provider
from platform_core.store import Store
from platform_core.agents import runtime


class RegionRuns(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.now = datetime(2026, 11, 24, 12, tzinfo=provider.ZONE)
        with patch.dict(os.environ, {"NH_OWNER_PASSWORD": "region-fixture-pass"}):
            self.store = Store(Path(workspace.name) / "site.sqlite", lambda: self.now)
        self.token, self.owner = self.store.login("owner", "region-fixture-pass")
        self.staff = {
            "id": "restricted-employee",
            "kind": "staff",
            "displayName": "分区员工",
            "permissions": ["assistants", "care", "finance", "inventory"],
        }
        self.data = self.store.snapshot(self.token)["data"]
        with closing(self.store.connect()) as db, db:
            facility.init(db, self.data)
            self.room = facility.floor(db, self.data, self.owner, "floor-1")["rooms"][
                0
            ]["id"]
            self.other = facility.floor(db, self.data, self.owner, "floor-2")["rooms"][
                0
            ]["id"]
            self.ids = facility.scope(db, self.data, self.owner, roomId=self.room)[
                "residentIds"
            ]
            self.outsider = facility.scope(
                db, self.data, self.owner, roomId=self.other
            )["residentIds"][0]

    def start(self, db, user=None, **fields):
        body = {
            "requestId": "request-room",
            "goal": "核对护理工单和欠费账单",
            "region": {"roomId": self.room},
            **fields,
        }
        return agents.apply(
            db, self.data, "agent.start", body, user or self.staff, self.now, 0
        )[1]

    def test_filter_runs_and_domain_records_with_frozen_room_and_source_evidence(self):
        # Force a finance record for an outsider and one for an insider to test cross-domain filtering.
        sample = self.data["bills"][0]
        self.data["bills"] = [
            {**sample, "id": "private-other-room", "residentId": self.outsider},
            {**sample, "id": "this-room-bill", "residentId": self.ids[0]},
        ]
        known = {r["id"] for r in self.data["tasks"] if r["residentId"] in self.ids}
        with closing(self.store.connect()) as db, db:
            run = self.start(db)
            record = agents.detail(db, self.staff, run)
            self.assertIn("101", record["region"]["label"])
            self.assertEqual(record["region"]["floorId"], "floor-1")
            self.assertNotIn("residentIds", record["region"])
            self.assertEqual(record["agents"], ["care", "finance"])
            self.assertTrue(
                any(e["event"] == "region.selected" for e in record["events"])
            )
            refs = [x for a in record["artifacts"] for x in a["evidence"]]
            task_ids = {
                i for e in refs if e["source"] == "tasks" for i in e["recordIds"]
            }
            bill_ids = {
                i for e in refs if e["source"] == "bills" for i in e["recordIds"]
            }
            self.assertTrue(task_ids)
            self.assertTrue(task_ids <= known)
            self.assertEqual(bill_ids, {"this-room-bill"})
            self.assertIn("101", agents.audit_context(db, run)["room"])
            self.assertEqual(self.start(db), run)
            with self.assertRaises(ValueError):
                self.start(db, region={"roomId": self.other})
            with self.assertRaisesRegex(ValueError, "锁定"):
                agents.apply(
                    db,
                    self.data,
                    "agent.publish",
                    {"runId": run, "region": {"roomId": self.other}},
                    self.staff,
                    self.now,
                    1,
                )
            agents.apply(
                db, self.data, "agent.publish", {"runId": run}, self.staff, self.now, 1
            )
            saved = [r for r in self.data["suggestions"] if r.get("runId") == run]
            self.assertEqual(len(saved), 2)
            self.assertTrue(all(r["region"] == record["region"] for r in saved))

    def test_partial_scope_intersection_and_live_revocation_hide_legacy_or_broader_run(
        self,
    ):
        with closing(self.store.connect()) as db, db:
            legacy = agents.apply(
                db,
                self.data,
                "agent.start",
                {"goal": "核对护理工单", "requestId": "institution"},
                self.staff,
                self.now,
                0,
            )[1]
            wider = self.start(db, region={"floorId": "floor-1"})
            restricted = {**self.staff, "facilityScope": {"roomIds": [self.room]}}
            self.assertFalse(agents.region_visible(db, restricted, legacy))
            self.assertFalse(agents.region_visible(db, restricted, wider))
            self.assertFalse(agents.listing(db, restricted))
            with self.assertRaises(PermissionError):
                agents.preflight(
                    db, self.data, restricted, {"goal": "照护", "requestId": "missing"}
                )
            with self.assertRaises(FileNotFoundError):
                self.start(
                    db, restricted, requestId="forbidden", region={"roomId": self.other}
                )
            with self.assertRaises(PermissionError):
                self.start(
                    db,
                    restricted,
                    requestId="wrong-person",
                    residentId=self.outsider,
                    goal="安排照护",
                )
            own = self.start(
                db,
                restricted,
                requestId="scoped",
                region={"buildingId": "building-main"},
            )
            self.assertEqual([r["id"] for r in agents.listing(db, restricted)], [own])
            different = {**self.staff, "facilityScope": {"roomIds": [self.other]}}
            with self.assertRaises(FileNotFoundError):
                agents.detail(db, different, own)
            with self.assertRaises(FileNotFoundError):
                agents.apply(
                    db,
                    self.data,
                    "agent.publish",
                    {"runId": own},
                    different,
                    self.now,
                    1,
                )
            malformed = {
                **self.staff,
                "facilityScope": {"institutionId": "some-other-institution"},
            }
            self.assertFalse(agents.region_visible(db, malformed, own))
            with self.assertRaises(PermissionError):
                self.start(db, malformed, requestId="tenant-crossing")

    def test_empty_floor_cannot_fall_back_to_all_records_and_inventory_requires_institution(
        self,
    ):
        with closing(self.store.connect()) as db, db:
            rid = self.start(db, region={"floorId": "floor-7"})
            artifacts = agents.detail(db, self.staff, rid)["artifacts"]
            self.assertFalse(
                any(ref["recordIds"] for a in artifacts for ref in a["evidence"])
            )
            with self.assertRaises(PermissionError):
                self.start(
                    db, requestId="unsupported-tool", scope="inventory", goal="核对库存"
                )
            with self.assertRaises(ValueError):
                self.start(db, requestId="empty-region", region={})
            with self.assertRaises(ValueError):
                self.start(
                    db,
                    requestId="injected",
                    region={"roomId": self.room, "residentIds": self.ids},
                )

    def test_region_controls_cloud_domains_and_token_identity_stays_local(self):
        with closing(self.store.connect()) as db, db:
            check = agents.preflight(
                db,
                self.data,
                self.staff,
                {
                    "goal": "核对护理、库存和欠费",
                    "requestId": "r",
                    "region": {"roomId": self.room},
                },
            )
            other = agents.preflight(
                db,
                self.data,
                self.staff,
                {
                    "goal": "核对护理、库存和欠费",
                    "requestId": "r",
                    "region": {"roomId": self.other},
                },
            )
            provider.grant(db, "测试额度", 2000, "2026-12-01", self.now)
        mock = Mock(
            return_value={
                "usage": {"total_tokens": 41},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"ids":["care","finance"]}'},
                    }
                ],
            }
        )

        def call(check):
            return provider.plan(
                self.store.connect,
                lambda db: self.staff,
                check["args"]["goal"],
                "r",
                now=self.now,
                transport=mock,
                scope_key=check["fingerprintScope"],
                allowed_specs=check["specs"],
            )

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "unit-fixture"}):
            self.assertEqual(call(check)["specialistIds"], ["care", "finance"])
            with self.assertRaisesRegex(ValueError, "另一项"):
                call(other)
        sent = json.dumps(mock.call_args.args[1], ensure_ascii=False)
        for excluded in (
            self.room,
            self.other,
            "floor-1",
            "building-main",
            "库存",
            "inventory",
        ):
            self.assertNotIn(excluded, sent)
        mock.assert_called_once()

    def test_scope_is_enforced_on_tool_input_before_output_validation(self):
        spec = next(s for s in agents.specialists(self.staff) if s.key == "care")
        scoped = runtime.scoped_records(self.data, spec, "", frozenset(self.ids))
        self.assertEqual({r["id"] for r in scoped["residents"]}, set(self.ids))
        for key in ("assessments", "tasks"):
            self.assertTrue(all(r["residentId"] in self.ids for r in scoped[key]))


if __name__ == "__main__":
    unittest.main()
