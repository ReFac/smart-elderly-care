"""Branches can share room numbers without sharing scoped patient records."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from platform_core import facility
from platform_core.store import Store


class CampusTests(unittest.TestCase):
    def setUp(self):
        from provider_fixture import simulate_narration

        simulate_narration(self)
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.password = "unit-campus-accounts"
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": self.password}):
            self.store = Store(Path(temp.name) / "campuses.sqlite3")
        self.owner, _ = self.store.login("owner", self.password)
        self.cmd(self.owner, "facility.addCampus", name="东湖分院", address="东湖路")
        atlas = self.directory(self.owner)
        self.east = atlas["campuses"][-1]["id"]
        self.cmd(self.owner, "facility.addBuilding", campusId=self.east, name="主楼")
        self.building = self.directory(self.owner)["buildings"][-1]["id"]
        self.cmd(self.owner, "facility.addFloor", buildingId=self.building, number=1)
        fid = self.directory(self.owner)["buildings"][-1]["floors"][0]["id"]
        self.cmd(
            self.owner,
            "facility.addRoom",
            floorId=fid,
            number="101",
            ward="照护区",
            bedCount=1,
        )
        self.east_bed = self.store.snapshot(self.owner)["data"]["beds"][-1]["id"]
        self.cmd(self.owner, "care.register", campusId=self.east, name="分院长者")
        self.rid = self.store.snapshot(self.owner)["data"]["residents"][-1]["id"]
        self.cmd(self.owner, "care.admit", bedId=self.east_bed, residentId=self.rid)
        self.staff, self.employee = self.create("east-nurse", self.east)
        self.main = facility.HOME_CAMPUS

    def cmd(self, token, action, **fields):
        return self.store.execute(
            action, fields, self.store.version(token)["revision"], token
        )

    def directory(self, token):
        return self.store.facility_resource(token, "directory")

    def create(self, name, campus):
        self.cmd(
            self.owner,
            "access.create",
            kind="staff",
            role="自定义",
            displayName=name,
            username=name,
            password=self.password,
            campusId=campus,
            permissions=[
                "care",
                "medical",
                "clinical",
                "medical.write",
                "intake",
                "residents",
                "assistants",
                "voice",
                "alerts",
                "finance",
                "audit",
                "reports",
                "staff.manage",
            ],
        )
        return self.store.login(name, self.password)

    def test_room_search_events_and_agent_history_respect_campus(self):
        results = self.store.facility_resource(self.owner, "search", q="101")["results"]
        self.assertEqual({self.main, self.east}, {r["campusId"] for r in results})
        self.assertEqual(
            [self.east], [c["id"] for c in self.directory(self.staff)["campuses"]]
        )
        self.assertEqual(
            [],
            self.store.facility_resource(
                self.staff, "search", q="101", campusId=self.main
            )["results"],
        )
        mainroom = next(r for r in results if r["campusId"] == self.main)
        with self.assertRaises(FileNotFoundError):
            self.store.facility_resource(self.staff, "room", mainroom["roomId"])
        self.cmd(
            self.staff,
            "agent.start",
            requestId="east-agent",
            goal="核对照护工单",
            region={"campusId": self.east},
        )
        run = self.store.agent_resource(self.staff, "runs")["runs"][0]
        self.assertEqual(self.east, run["region"]["campusId"])
        with self.assertRaises(FileNotFoundError):
            self.cmd(
                self.staff,
                "agent.start",
                requestId="other-agent",
                goal="核对照护工单",
                region={"campusId": self.main},
            )
        self.cmd(
            self.owner, "access.update", id=self.employee["id"], campusId=self.main
        )
        self.assertFalse(self.store.agent_resource(self.staff, "runs")["runs"])

    def test_staff_scope_filters_records_and_direct_writes(self):
        entire = self.store.snapshot(self.owner)["data"]
        main = entire["residents"][0]
        self.cmd(
            self.owner,
            "gw.ingest",
            source="badge",
            eventId="branch-alarm",
            bedId=main["bedId"],
            signal="possible_fall",
        )
        alert = self.store.snapshot(self.owner)["data"]["gatewayAlerts"][0]["id"]
        snapshot = self.store.snapshot(self.staff)["data"]
        self.assertEqual([self.rid], [r["id"] for r in snapshot["residents"]])
        self.assertEqual([], snapshot["gatewayAlerts"])
        self.assertNotIn("reports", snapshot["user"]["permissions"])
        for action, payload in [
            ("care.renew", {"residentId": main["id"]}),
            ("care.completeTask", {"taskId": entire["tasks"][0]["id"]}),
            ("care.transfer", {"residentId": self.rid, "bedId": main["bedId"]}),
            ("gw.review", {"alertId": alert, "decision": "误报", "note": "虚构"}),
            ("ops.expense", {}),
        ]:
            with self.subTest(action=action), self.assertRaises(PermissionError):
                self.cmd(self.staff, action, **payload)
        self.cmd(self.staff, "care.inquire", name="测试接待")
        self.assertEqual(
            [self.east],
            [
                r["campusId"]
                for r in self.store.snapshot(self.staff)["data"]["inquiries"]
            ],
        )
        self.cmd(self.staff, "care.discharge", residentId=self.rid)
        self.assertEqual(
            "已退住", self.store.snapshot(self.staff)["data"]["residents"][0]["status"]
        )
        self.assertTrue(
            all(
                row["residentId"] == self.rid
                for row in self.store.activity(self.staff)["rows"]
            )
        )

    def test_room_search_preserves_both_charts_for_identically_named_residents(self):
        for rid in ("r001", "r002"):
            self.cmd(self.owner, "dossier.profile", residentId=rid, name="同名陈长者")
        reopened = Store(self.store.path)
        results = reopened.facility_resource(self.owner, "search", q="同名陈")[
            "results"
        ]
        self.assertEqual([row["number"] for row in results], ["101"])
        self.assertCountEqual(
            results[0]["matchedResidents"],
            [
                {"id": "r001", "name": "同名陈长者", "bedLabel": "101-01"},
                {"id": "r002", "name": "同名陈长者", "bedLabel": "101-02"},
            ],
        )

    def test_room_and_position_labels_follow_branch_and_family_authorization(self):
        name = "同名员工"
        self.cmd(
            self.owner,
            "access.update",
            id=self.employee["id"],
            displayName=name,
            staffDuties=["临床护理"],
        )
        self.cmd(
            self.owner,
            "access.create",
            kind="staff",
            username="main-finance",
            role="财务",
            campusId=self.main,
            displayName=name,
            password=self.password,
        )
        _, other = self.store.login("main-finance", self.password)
        self.cmd(
            self.owner,
            "care.addTask",
            residentId=self.rid,
            assignee=name,
            title="院区记录",
        )
        data = self.store.snapshot(self.staff)["data"]
        self.assertEqual(data["residentRooms"], {self.rid: "101"})
        self.assertEqual(data["staffPositions"]["ids"][self.employee["id"]], "临床护理")
        self.assertNotIn(other["id"], data["staffPositions"]["ids"])
        self.assertNotIn(name, data["staffPositions"]["names"])
        self.cmd(
            self.owner,
            "access.create",
            kind="family",
            username="bound-relative",
            displayName="家属",
            residentId="r001",
            password=self.password,
        )
        family, person = self.store.login("bound-relative", self.password)
        self.assertEqual(self.store.snapshot(family)["data"]["residentRooms"], {})
        self.cmd(self.owner, "access.update", id=person["id"], familyServices=True)
        shared = self.store.snapshot(family)["data"]
        self.assertEqual(shared["residentRooms"], {"r001": "101"})
        self.assertNotIn("staffPositions", shared)

    def test_document_and_delegated_staff_cannot_cross_branch(self):
        main = "r001"
        self.cmd(
            self.owner,
            "dossier.document",
            residentId=main,
            requestId="legacy",
            eventDate="2025-02-03",
            source="测试门诊",
            category="CT",
            description="测试原件",
            imageBase64="iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR42mNk2GfDwMDAxMDAwMDAAAALpgD+jGO7GwAAAABJRU5ErkJggg==",
        )
        doc = self.store.snapshot(self.owner)["data"]["medicalDocuments"][0]["id"]
        self.assertTrue(self.store.photo(self.owner, doc))
        for method, arg in [
            (self.store.photo, doc),
            (self.store.document_ocr_detail, doc),
            (self.store.dossier_summary_draft, main),
        ]:
            with self.assertRaises(PermissionError):
                method(self.staff, arg)
        self.cmd(
            self.staff,
            "access.create",
            kind="staff",
            role="护工",
            permissions=["care"],
            displayName="东湖护工",
            username="east-care",
            password=self.password,
        )
        scoped = self.store.snapshot(self.staff)["data"]["accounts"][0]
        self.assertEqual(scoped["facilityScope"]["campusIds"], [self.east])
        with self.assertRaises(PermissionError):
            self.cmd(self.staff, "access.update", id=scoped["id"], campusId="")
        _, other = self.create("main-nurse", self.main)
        with self.assertRaises(PermissionError):
            self.cmd(
                self.staff,
                "access.password",
                id=other["id"],
                password=self.password + "-changed",
            )

    def test_assessment_assigns_same_named_ward_from_its_own_branch(self):
        day = self.store.snapshot(self.staff)["today"]
        for branch, staff in [(self.main, "一号本部人员"), (self.east, "分院责任人")]:
            self.cmd(
                self.owner,
                "ops.shift",
                campusId=branch,
                staff=staff,
                area="照护区",
                period="早班",
                date=day,
            )
        self.cmd(
            self.staff,
            "care.assess",
            residentId=self.rid,
            level="自理",
            note="入院后评估",
            matchCampusId=self.main,
        )
        plan = self.store.snapshot(self.staff)["data"]["plans"][-1]
        self.assertEqual(plan["assignee"], "分院责任人")

    def test_transfer_withdraws_old_agent_evidence(self):
        self.cmd(
            self.staff,
            "agent.start",
            requestId="resident-agent",
            goal="核对照护工单",
            region={"campusId": self.east},
        )
        run = self.store.agent_resource(self.staff, "runs")["runs"][0]
        self.assertNotIn("residentIds", run["region"])
        available = next(
            b
            for b in self.store.snapshot(self.owner)["data"]["beds"]
            if b["status"] == "空闲"
        )
        self.cmd(
            self.owner, "care.transfer", residentId=self.rid, bedId=available["id"]
        )
        self.assertFalse(self.store.agent_resource(self.staff, "runs")["runs"])
        self.assertFalse(self.store.snapshot(self.staff)["data"]["residents"])

    def test_clinical_documents_checkout_reports_and_finance_agent(self):
        with closing(self.store.connect()) as db:
            entire = json.loads(db.execute("SELECT data FROM workspace").fetchone()[0])
            main = entire["residents"][0]["id"]
            entire["paymentOrders"] = [
                {"id": "NH-0123456789abcdef", "residentId": main, "status": "待支付"}
            ]
            db.execute("UPDATE workspace SET data=?", (json.dumps(entire),))
            db.commit()
        with self.assertRaises(PermissionError):
            self.store.payment_order_status(self.staff, "NH-0123456789abcdef")
        with self.assertRaises(PermissionError):
            self.store.report_version(self.staff, "institution", 1)
        with self.assertRaises(PermissionError):
            self.store.backups.status(self.staff)
        self.cmd(
            self.owner,
            "access.update",
            id=self.employee["id"],
            permissions=["finance", "assistants"],
        )
        with self.assertRaises(PermissionError):
            self.directory(self.staff)
        self.cmd(
            self.staff,
            "agent.start",
            requestId="branch-finance",
            scope="finance",
            goal="核对分院费用",
            region={"campusId": self.east},
        )
        self.assertEqual(
            self.store.agent_resource(self.staff, "runs")["runs"][0]["region"][
                "campusId"
            ],
            self.east,
        )

    def test_edit_branch_and_building_preserves_people_and_rooms(self):
        initial = self.store.facility_resource(self.staff, "search", q="101")[
            "results"
        ][0]
        self.cmd(
            self.owner,
            "facility.updateCampus",
            campusId=self.east,
            name="东湖养护中心",
            address="沿湖路",
        )
        self.cmd(
            self.owner,
            "facility.renameBuilding",
            buildingId=self.building,
            name="护理楼",
        )
        updated = self.store.facility_resource(self.staff, "search", q="分院长者")[
            "results"
        ][0]
        self.assertEqual(initial["roomId"], updated["roomId"])
        self.assertEqual(
            (updated["campusName"], updated["buildingName"]), ("东湖养护中心", "护理楼")
        )
        self.assertEqual(self.directory(self.staff)["campuses"][0]["address"], "沿湖路")
        self.assertEqual(
            [self.rid],
            [r["id"] for r in self.store.snapshot(self.staff)["data"]["residents"]],
        )
        with self.assertRaises(PermissionError):
            self.cmd(
                self.staff, "facility.updateCampus", campusId=self.east, address="变更"
            )

    def test_legacy_building_id_migration_is_idempotent(self):
        with closing(sqlite3.connect(":memory:")) as db:
            db.row_factory = sqlite3.Row
            db.executescript("""
                CREATE TABLE facility_site(singleton INTEGER PRIMARY KEY,id TEXT);
                INSERT INTO facility_site VALUES(1,'original-site');
                CREATE TABLE facility_buildings(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE);
                INSERT INTO facility_buildings VALUES('old-building','主楼');
            """)
            for _ in range(2):
                facility.init(db, {"beds": []})
            row = db.execute(
                "SELECT id,name,campusId FROM facility_building_directory"
            ).fetchone()
            self.assertEqual(("old-building", "主楼", self.main), tuple(row))
            self.assertEqual(
                1,
                db.execute("SELECT count(*) FROM facility_building_campus").fetchone()[
                    0
                ],
            )
