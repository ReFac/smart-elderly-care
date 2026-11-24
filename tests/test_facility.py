"""Room directory migration, access boundaries, maps, expansion and tour publishing."""

from copy import deepcopy
import json
import os
import sqlite3
import unittest
from unittest.mock import patch

from platform_core import access_policy, care, facility


DAY = "2026-11-24"
OWNER = {"id": "owner", "kind": "owner", "permissions": []}
NURSE = {"id": "n", "kind": "staff", "permissions": ["care"]}
FAMILY = {"id": "f", "kind": "family", "permissions": []}


class FacilityTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.s = care.seed(DAY)
        with self.db:
            facility.init(self.db, self.s)

    def command(self, action, **p):
        with self.db:
            return facility.apply(self.db, self.s, "facility." + action, p, OWNER, DAY)

    def search(self, term, user=NURSE, **limits):
        return facility.search(self.db, self.s, user, term, **limits)["results"]

    def first(self, number="101"):
        return self.search(number)[0]["roomId"]

    def view(self, fid="floor-1", user=NURSE):
        return facility.floor(self.db, self.s, user, fid)

    def test_existing_occupancy_maps_only_to_known_floors_without_mutating_records(
        self,
    ):
        initial = deepcopy(self.s)
        floors = facility.directory(self.db, self.s, NURSE)["buildings"][0]["floors"]
        self.assertEqual([f["number"] for f in floors], [1, 2, 3, 5, 6, 7])
        self.assertEqual([f["roomCount"] for f in floors], [4, 4, 4, 0, 0, 0])
        first = self.view()
        self.assertEqual(first["layoutSource"], "schematic")
        self.assertEqual(first["rooms"][0]["bedCount"], 2)
        who = facility.room(self.db, self.s, NURSE, first["rooms"][0]["id"])
        self.assertEqual(who["beds"][0]["residentName"], self.s["residents"][0]["name"])
        self.assertNotIn("contact", who["beds"][0])
        with self.db:
            facility.init(self.db, self.s)
        self.assertEqual(initial, self.s)
        self.assertEqual(self.view(), first)

    def test_search_single_character_nfkc_room_suffix_duplicates_and_live_transfer(
        self,
    ):
        self.s["residents"][0]["name"] = "房子兰"
        self.assertEqual(self.search("房")[0]["number"], "101")
        self.assertIn("房子兰", self.search(" 兰 ")[0]["matchedNames"])
        self.assertEqual(self.search("１０１号房")[0]["number"], "101")
        limited = facility.search(self.db, self.s, NURSE, "0", limit=1)
        self.assertTrue(limited["hasMore"])
        self.assertEqual(len(limited["results"]), 1)
        with self.assertRaises(ValueError):
            self.search("0", limit=200)
        destination = next(b for b in self.s["beds"] if b["status"] == "空闲")
        care.apply(
            self.s,
            "care.transfer",
            {"residentId": "r001", "bedId": destination["id"]},
            DAY,
        )
        self.assertEqual(
            self.search("房")[0]["number"], destination["label"].split("-")[0]
        )
        self.assertEqual(self.search("房", floorId="floor-1"), [])

    def test_role_and_trusted_scope_apply_to_every_read_and_agent_resolution(self):
        rid = self.first()
        private = {**NURSE, "facilityScope": {"roomIds": [rid]}}
        result = facility.directory(self.db, self.s, private)
        self.assertEqual(len(result["buildings"][0]["floors"]), 1)
        self.assertEqual(len(self.view(user=private)["rooms"]), 1)
        self.assertEqual(self.search("101", private)[0]["roomId"], rid)
        self.assertEqual(self.search("201", private), [])
        with self.assertRaises(FileNotFoundError):
            self.view("floor-2", private)
        with self.assertRaises(FileNotFoundError):
            facility.room(self.db, self.s, private, self.first("201"))
        exact = facility.scope(self.db, self.s, private, buildingId=facility.MAIN)
        self.assertEqual(exact["residentIds"], ["r001", "r002"])
        with self.assertRaises(FileNotFoundError):
            facility.scope(self.db, self.s, private, floorId="floor-2", roomId=rid)
        with self.assertRaises(PermissionError):
            self.search(
                "沈", {**NURSE, "facilityScope": {"institutionId": "different"}}
            )
        self.assertEqual(
            facility.directory(
                self.db, self.s, {**NURSE, "facilityScope": {"buildingIds": []}}
            )["buildings"],
            [],
        )
        with self.assertRaises(PermissionError):
            self.search("101", FAMILY)
        with self.assertRaises(PermissionError):
            facility.apply(
                self.db, self.s, "facility.addBuilding", {"name": "越权"}, NURSE, DAY
            )

    def test_expansion_creates_bookable_beds_and_scopes_duplicate_room_numbers(self):
        self.command("addBuilding", name="扩建楼")
        building = facility.directory(self.db, self.s, OWNER)["buildings"][-1]
        self.command("addFloor", buildingId=building["id"], number=1)
        fid = facility.directory(self.db, self.s, OWNER)["buildings"][-1]["floors"][0][
            "id"
        ]
        self.command(
            "addRoom",
            floorId=fid,
            number="101",
            ward="颐养一区",
            bedCount=1,
            dailyRate="75.50",
        )
        self.assertEqual(len(self.search("101")), 2)
        r = self.search("101", buildingId=building["id"])[0]
        new = facility.room(self.db, self.s, NURSE, r["roomId"])
        bid = new["beds"][0]["id"]
        self.assertNotEqual(new["beds"][0]["label"], "101-01")
        care.apply(self.s, "care.register", {"name": "扩建验收"}, DAY)
        care.apply(
            self.s,
            "care.admit",
            {"residentId": self.s["residents"][-1]["id"], "bedId": bid},
            DAY,
        )
        self.assertEqual(self.search("验收")[0]["roomId"], new["id"])
        self.command("addBeds", roomId=new["id"], count=2, dailyRate=75.50)
        self.assertEqual(
            len(facility.room(self.db, self.s, NURSE, new["id"])["beds"]), 3
        )
        with self.assertRaises(ValueError):
            self.command("addFloor", buildingId=facility.MAIN, number=4)
        with self.assertRaises(ValueError):
            self.command("addRoom", floorId=fid, number="101", ward="其他")
        with self.assertRaises(ValueError):
            self.command("addBeds", roomId=new["id"], count=12)
        # Buildings added later may use floor labels according to their own plans.
        self.command("addFloor", buildingId=building["id"], number=4)

    def test_manual_geometry_is_all_or_nothing_and_room_numbers_share_the_same_ids(
        self,
    ):
        entries = [
            {"roomId": r["id"], "x": i * 24, "y": 10, "w": 20, "h": 30}
            for i, r in enumerate(self.view()["rooms"])
        ]
        with self.assertRaises(ValueError):
            self.command("setLayout", floorId="floor-1", rooms=entries[:-1])
        bad = deepcopy(entries)
        bad[-1]["x"] = 1
        with self.assertRaises(ValueError):
            self.command("setLayout", floorId="floor-1", rooms=bad)
        self.assertEqual(self.view()["layoutSource"], "schematic")
        self.command(
            "setLayout",
            floorId="floor-1",
            rooms=entries,
            planMediaUrl="/tour-media/first-floor.png",
        )
        self.assertEqual(self.view()["planMediaUrl"], "/tour-media/first-floor.png")
        limited = {**NURSE, "facilityScope": {"roomIds": [entries[0]["roomId"]]}}
        self.assertEqual(self.view(user=limited)["planMediaUrl"], "")
        self.assertEqual(self.view()["layoutSource"], "registered")
        self.assertEqual(self.view()["rooms"][1]["x"], 24)
        self.assertEqual(self.view()["rooms"][0]["id"], self.first("101"))
        with self.assertRaises(ValueError):
            self.command("addRoom", floorId="floor-1", number="105", ward="颐养一区")
        self.command(
            "addRoom",
            floorId="floor-1",
            number="105",
            ward="颐养一区",
            x=10,
            y=65,
            w=18,
            h=15,
        )
        self.assertEqual(self.view()["roomCount"], 5)

    def test_room_resize_retains_bed_identity_and_only_removes_vacant_capacity(self):
        full = self.first("101")
        untouched = deepcopy(self.s)
        with self.assertRaisesRegex(ValueError, "仍在使用"):
            self.command("updateRoom", roomId=full, bedCount=1)
        self.assertEqual(self.s, untouched)
        self.command("updateRoom", roomId=full, bedCount=3)
        room = facility.room(self.db, self.s, NURSE, full)
        self.assertEqual((room["roomType"], room["occupiedCount"]), ("三人间", 2))
        extra = room["beds"][-1]["id"]
        self.command("updateRoom", roomId=full, bedCount=2)
        former = next(b for b in self.s["beds"] if b["id"] == extra)
        self.assertEqual(former["status"], facility.INACTIVE_BED)
        self.assertTrue(self.db.execute("SELECT 1 FROM facility_beds WHERE bedId=?", (extra,)).fetchone())
        self.assertNotIn(extra, {b["id"] for b in access_policy.visible_data(self.s, OWNER)["beds"]})
        self.assertEqual(facility.room(self.db, self.s, NURSE, full)["roomType"], "双人间")
        old_rate = former["dailyRate"]
        self.command("updateRoom", roomId=full, bedCount=3, dailyRate="76.50")
        self.assertEqual((former["status"], former["dailyRate"]), ("空闲", old_rate))
        self.assertEqual(facility.room(self.db, self.s, NURSE, full)["beds"][-1]["id"], extra)
        self.assertEqual(facility.rooms(self.db, self.s, NURSE, "3", "3")["total"], 1)

    def test_capacity_and_vector_administration_keep_their_own_access_boundaries(self):
        first = self.first()
        manager = {"id": "manager", "kind": "staff", "permissions": ["facility.manage"],
                   "facilityScope": {"roomIds": [first]}}
        self.assertIn("facility.updateRoom", access_policy.allowed_actions(manager))
        self.assertNotIn("facility.updateRoom", access_policy.allowed_actions(NURSE))
        place = facility.room(self.db, self.s, manager, first)
        self.assertTrue(place["canEdit"])
        self.assertTrue(all(not b["residentName"] and not b["residentId"] for b in place["beds"]))
        listing = facility.rooms(self.db, self.s, manager)
        self.assertEqual([r["id"] for r in listing["rooms"]], [first])
        self.assertEqual(self.search("沈", manager), [])
        self.assertFalse(self.view(user=manager)["vector"]["editable"])
        with self.assertRaises(FileNotFoundError):
            facility.apply(self.db, self.s, "facility.updateRoom",
                           {"roomId": self.first("201"), "bedCount": 3}, manager, DAY)
        with self.assertRaises(PermissionError):
            facility.apply(self.db, self.s, "facility.setLayout",
                           {"floorId": "floor-1", "rooms": []}, manager, DAY)
        floor_manager = {**manager, "facilityScope": {"floorIds": ["floor-1"]}}
        vector = self.view(user=floor_manager)["vector"]
        self.assertEqual(vector["viewBox"], [0, 0, 100, 100])
        self.assertTrue(vector["editable"])
        rectangles = [{**r, "x": i * 24, "y": 10, "w": 20, "h": 30}
                      for i, r in enumerate(vector["rooms"])]
        with self.db:
            facility.apply(self.db, self.s, "facility.setLayout",
                           {"floorId": "floor-1", "rooms": rectangles}, floor_manager, DAY)
        self.assertEqual(self.view()["vector"]["rooms"], rectangles)
        self.assertFalse(self.view()["vector"]["editable"])

    def test_tour_filter_sort_replace_withdraw_and_allowed_media_origins(self):
        rid = self.first()
        self.assertEqual(
            facility.tour(self.db, self.s, FAMILY)["status"], "awaiting_media"
        )
        self.command(
            "setScene",
            buildingId=facility.MAIN,
            title="入口",
            mediaUrl="/tour-media/front.jpg",
            kind="photo",
            sortOrder=1,
        )
        self.command(
            "setScene",
            roomId=rid,
            title="窗边",
            mediaUrl="/tour-media/window.jpg",
            sortOrder=8,
        )
        for url in (
            "http://static.example/a.jpg",
            "https://user@static.example/a.jpg",
            "javascript:alert(1)",
            "/tour-media/../private",
            "/tour-media/%2E%2E/private",
            "/other/one.jpg",
            "https://static.example/a.jpg",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.command("setScene", floorId="floor-1", title="退件", mediaUrl=url)
        with patch.dict(
            os.environ,
            {
                "NH_TOUR_MEDIA_ORIGINS": "https://static.example, https://bad.example/path, invalid"
            },
        ):
            self.assertEqual(facility.media_origins(), ["https://static.example"])
            self.command(
                "setScene",
                roomId=rid,
                title="窗边",
                mediaUrl="https://static.example/2.jpg",
                kind="panorama",
                sortOrder=8,
            )
            scenes = facility.tour(self.db, self.s, FAMILY)["scenes"]
            self.assertEqual([s["title"] for s in scenes], ["入口", "窗边"])
            self.assertNotIn("resident", json.dumps(scenes))
            only = facility.tour(
                self.db, self.s, {**FAMILY, "facilityScope": {"roomIds": [rid]}}
            )
            self.assertEqual(only["scenes"], scenes[1:])
            self.assertEqual(
                facility.tour(self.db, self.s, FAMILY, floorId="floor-2")["scenes"], []
            )
        self.assertEqual(len(facility.tour(self.db, self.s, FAMILY)["scenes"]), 1)
        self.command("withdrawScene", sceneId=scenes[0]["id"])
        self.assertEqual(
            facility.tour(self.db, self.s, FAMILY)["status"], "awaiting_media"
        )

    def test_media_path_respects_publish_state_decoding_user_type_and_region(self):
        floor = self.view()
        rooms = [
            {"roomId": r["id"], "x": i * 24, "w": 20, "y": 10, "h": 20}
            for i, r in enumerate(floor["rooms"])
        ]
        self.command(
            "setLayout",
            floorId="floor-1",
            rooms=rooms,
            planMediaUrl="/tour-media/map.png",
        )
        self.command(
            "setScene",
            roomId=rooms[0]["roomId"],
            title="窗边",
            mediaUrl="/tour-media/window%20side.jpg",
        )

        def can(user, path):
            return facility.can_read_media(self.db, self.s, user, "/tour-media/" + path)

        self.assertTrue(can(NURSE, "map.png"))
        self.assertFalse(can(FAMILY, "map.png"))
        self.assertFalse(can(NURSE, "unpublished.png"))
        self.assertFalse(can(None, "window side.jpg"))
        self.assertTrue(can(FAMILY, "window side.jpg"))
        allowed = {**NURSE, "facilityScope": {"roomIds": [rooms[0]["roomId"]]}}
        other = {**NURSE, "facilityScope": {"roomIds": [rooms[1]["roomId"]]}}
        self.assertFalse(can(allowed, "map.png"))
        self.assertTrue(can(allowed, "window side.jpg"))
        self.assertFalse(can(other, "window side.jpg"))
        self.command(
            "setScene",
            roomId=rooms[0]["roomId"],
            title="窗边",
            mediaUrl="/tour-media/updated.jpg",
        )
        self.assertFalse(can(allowed, "window side.jpg"))
        self.assertTrue(can(allowed, "updated.jpg"))
        scene = facility.tour(self.db, self.s, allowed)["scenes"][0]
        self.command("withdrawScene", sceneId=scene["id"])
        self.assertFalse(can(allowed, "updated.jpg"))
        self.command("setLayout", floorId="floor-1", rooms=rooms, planMediaUrl="")
        self.assertFalse(can(NURSE, "map.png"))

    def test_unmapped_legacy_bed_can_be_bound_without_affecting_resident_or_old_audit_keys(
        self,
    ):
        self.s["beds"].append(
            dict(
                id="old-b1",
                label="东翼A-01",
                ward="旧区",
                status="空闲",
                residentId="",
                dailyRate=56,
            )
        )
        self.assertEqual(
            facility.directory(self.db, self.s, OWNER)["unmappedBeds"][0]["id"],
            "old-b1",
        )
        self.command("addRoom", floorId="floor-6", number="601", ward="旧区")
        rid = self.first("601")
        self.command("linkBed", bedId="old-b1", roomId=rid)
        with self.assertRaises(ValueError):
            self.command("linkBed", bedId="old-b1", roomId=rid)
        self.assertEqual(facility.directory(self.db, self.s, OWNER)["unmappedBeds"], [])
        self.command("addBeds", roomId=rid, count=1)
        self.assertEqual(
            [b["label"] for b in facility.room(self.db, self.s, OWNER, rid)["beds"]],
            ["东翼A-01", "东翼A-02"],
        )


if __name__ == "__main__":
    unittest.main()
