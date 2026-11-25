"""Validate area hierarchies without changing the existing facility permissions."""

from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from platform_core import care_areas, facility
from platform_core.store import Store


NOW = datetime(2026, 11, 25, 12, tzinfo=ZoneInfo("Asia/Shanghai"))


class CareAreaTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(
            Path(tmp.name) / "test.sqlite",
            now=lambda: NOW,
            initial_owner_password="care-areas-fixture",
        )
        self.token, self.owner = self.store.login("owner", "care-areas-fixture")
        with closing(self.store.connect()) as db, db:
            care_areas.init(db)
        data = self.read()
        self.floor = data["floors"][0]["id"]
        self.room = next(
            room["id"] for room in data["rooms"] if room["floorId"] == self.floor
        )
        detail = self.store.facility_resource(self.token, "room", self.room)
        self.bed = detail["beds"][0]["id"]

    def read(self, building=facility.MAIN, token=None):
        return care_areas.read(self.store, token or self.token, building)

    def command(self, action, payload, user=None, *, building=facility.MAIN):
        with closing(self.store.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            state = json.loads(db.execute("SELECT data FROM workspace").fetchone()[0])
            return care_areas.command(
                db,
                state,
                user or self.owner,
                action,
                {"buildingId": building, **payload},
                NOW,
            )

    def zone(self, name, *, parent="", building=facility.MAIN, **payload):
        self.command(
            "care.areaSave",
            {"name": name, "parentId": parent, **payload},
            building=building,
        )
        return next(
            row["id"] for row in self.read(building)["areas"] if row["name"] == name
        )

    def apply(self, action, payload):
        return self.store.execute(
            action, payload, self.store.version(self.token)["revision"], self.token
        )

    def test_room_inspector_uses_the_same_area_as_the_bed_directory(self):
        parent = self.zone("东区", floorIds=[self.floor])
        self.zone("东区夜班", parent=parent, roomIds=[self.room])
        room = self.store.facility_resource(self.token, "room", self.room)
        bed = self.store.snapshot(self.token)["data"]["bedDirectory"][self.bed]
        self.assertEqual(room["areaPath"], "东区 / 东区夜班")
        self.assertEqual(room["areaId"], bed["areaId"])
        self.assertEqual(room["areaPath"], bed["areaPath"])

    def add_building(self, *, campus=facility.HOME_CAMPUS):
        self.apply("facility.addBuilding", {"name": "二号楼", "campusId": campus})
        building = next(
            row["id"] for row in self.read()["buildings"] if row["name"] == "二号楼"
        )
        self.apply("facility.addFloor", {"buildingId": building, "number": 1})
        return building

    def staff(self, name, *, campus=facility.HOME_CAMPUS):
        self.apply(
            "access.create",
            {
                "kind": "staff",
                "role": "护工",
                "username": name,
                "displayName": name,
                "password": "care-staff-fixture",
                "campusId": campus,
            },
        )
        return self.store.login(name, "care-staff-fixture")

    def test_room_overrides_floor_and_ancestor_assignment_covers_child(self):
        _, staff = self.staff("caregiver-one")
        parent = self.zone("照护区", floorIds=[self.floor])
        child = self.zone("夜班一区", parent=parent, roomIds=[self.room])
        self.command(
            "care.areaAssign", {"staffId": staff["id"], "areaIds": [parent, child]}
        )
        report = self.read()
        self.assertEqual(report["floors"][0]["areaId"], parent)
        room = next(row for row in report["rooms"] if row["id"] == self.room)
        self.assertEqual(
            (room["areaId"], room["effectiveAreaId"], room["areaPath"]),
            (child, child, "照护区 / 夜班一区"),
        )
        self.assertEqual(set(report["staff"][0]["areaIds"]), {parent, child})
        self.command("care.areaAssign", {"staffId": staff["id"], "areaIds": [parent]})
        with closing(self.store.connect()) as db:
            self.assertEqual(
                care_areas.responsible_staff(db, self.bed), {"caregiver-one"}
            )
            metadata = care_areas.bed_directory(db, [self.bed])[self.bed]
            self.assertEqual(metadata["areaIds"], [parent, child])
            self.assertEqual(metadata["floorNumber"], 1)
            self.assertIsNone(metadata["x"])
        self.command("care.areaMap", {"rooms": [{"id": self.room, "areaId": ""}]})
        room = next(row for row in self.read()["rooms"] if row["id"] == self.room)
        self.assertEqual((room["areaId"], room["effectiveAreaId"]), ("", parent))

    def test_other_building_keeps_its_assignment_when_this_building_is_updated(self):
        _, staff = self.staff("caregiver-two")
        building = self.add_building()
        local = self.zone("一楼照护")
        other = self.zone("一楼照护", building=building)
        self.command("care.areaAssign", {"staffId": staff["id"], "areaIds": [local]})
        self.command(
            "care.areaAssign",
            {"staffId": staff["id"], "areaIds": [other]},
            building=building,
        )
        self.command("care.areaAssign", {"staffId": staff["id"], "areaIds": []})
        self.assertFalse(self.read()["staff"][0]["areaIds"])
        self.assertEqual(self.read(building)["staff"][0]["areaIds"], [other])
        with self.assertRaises(ValueError):
            self.zone("跨楼栋的孩子", parent=local, building=building)
        with self.assertRaises(PermissionError):
            self.zone("跨楼栋的房间", building=building, roomIds=[self.room])
        with self.assertRaises(ValueError):
            self.command(
                "care.areaMap", {"floors": [{"id": self.floor, "areaId": other}]}
            )

    def test_hierarchy_cycle_and_archive_unlink_preserve_floor_fallback(self):
        _, staff = self.staff("caregiver-three")
        parent = self.zone("照护区", floorIds=[self.floor])
        child = self.zone("子区", parent=parent, roomIds=[self.room])
        self.command("care.areaAssign", {"staffId": staff["id"], "areaIds": [child]})
        with self.assertRaises(ValueError):
            self.command(
                "care.areaSave", {"name": "照护区", "id": parent, "parentId": child}
            )
        with self.assertRaises(ValueError):
            self.command("care.areaArchive", {"id": parent})
        self.command("care.areaArchive", {"id": child})
        report = self.read()
        self.assertEqual([row["id"] for row in report["areas"]], [parent])
        self.assertFalse(report["staff"][0]["areaIds"])
        room = next(row for row in report["rooms"] if row["id"] == self.room)
        self.assertEqual(room["effectiveAreaId"], parent)
        with closing(self.store.connect()) as db:
            self.assertTrue(
                db.execute(
                    "SELECT archivedAt FROM care_areas WHERE id=?", (child,)
                ).fetchone()[0]
            )
            self.assertFalse(care_areas.responsible_staff(db, self.bed))

    def test_real_campus_scope_and_room_scope_still_limit_area_operations(self):
        self.apply("facility.addCampus", {"name": "二号分院"})
        cp = next(
            row["id"]
            for row in self.store.facility_resource(self.token, "directory")["campuses"]
            if row["name"] == "二号分院"
        )
        other = self.add_building(campus=cp)
        nurse_token, local = self.staff("caregiver-four")
        self.assertFalse(self.read(token=nurse_token)["canManage"])
        with self.assertRaises(PermissionError):
            self.read(other, token=nurse_token)
        with self.assertRaises(PermissionError):
            self.command(
                "care.areaSave", {"name": "不能创建的区域", "parentId": ""}, local
            )
        grant = {**local, "permissions": [*local["permissions"], care_areas.GRANT]}
        with self.assertRaises(PermissionError):
            self.command(
                "care.areaSave",
                {"name": "越权归属", "parentId": ""},
                grant,
                building=other,
            )
        self.command("care.areaSave", {"name": "授权楼栋区域", "parentId": ""}, grant)
        limited = {
            **grant,
            "facilityScope": {
                "campusIds": [facility.HOME_CAMPUS],
                "roomIds": [self.room],
            },
        }
        with self.assertRaises(PermissionError):
            self.command(
                "care.areaSave", {"name": "仅房间授权", "parentId": ""}, limited
            )
