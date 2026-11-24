"""Exercise signed group activities through the real encrypted store and its grants."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from platform_core import daily_life, facility
from platform_core.backups import exchange
from platform_core.store import Store, TIMEZONE, Conflict


class DailyLifeTests(TestCase):
    def setUp(self):
        institution = TemporaryDirectory()
        self.addCleanup(institution.cleanup)
        self.path = Path(institution.name) / "activities.db"
        self.now = datetime(2026, 11, 24, 8, 29, tzinfo=TIMEZONE)
        self.password = "synthetic-menu-office"
        self.store = Store(
            self.path, lambda: self.now, initial_owner_password=self.password
        )
        self.owner = self.store.login("owner", self.password)[0]
        self.campus = facility.HOME_CAMPUS
        self.request = dict(
            requestId="breakfast-on-24",
            roomId="",
            campusId=self.campus,
            kind="早餐",
            day="2026-11-24",
            startsAt="08:00",
            endsAt="08:30",
            details="小米粥、蒸蛋",
        )
        self.signer = self.account("head", "护士长")
        self.carer = self.account("helper", "护工")
        self.first, self.second = self.roster()["residents"][:2]

    def cmd(self, token, action, payload):
        return self.store.execute(
            action, payload, self.store.version(token)["revision"], token
        )

    def account(self, login, role, campus=""):
        self.cmd(
            self.owner,
            "access.create",
            dict(
                username=login,
                password=self.password,
                displayName=login,
                kind="staff",
                role=role,
                campusId=campus,
            ),
        )
        return self.store.login(login, self.password)[0]

    def roster(self, token=None, **scope):
        return daily_life.roster(self.store, token or self.owner, **scope)

    def events(self, rid, token=None):
        return daily_life.timeline(self.store, token or self.owner, rid)["events"]

    def submit(self, **overrides):
        return self.cmd(
            self.carer, "care.proposeGroupActivity", {**self.request, **overrides}
        )

    def sign(self, event, ids, token=None, **extra):
        return self.cmd(
            token or self.signer,
            "care.confirmGroupActivity",
            dict(eventId=event, residentIds=ids, confirmed=True, **extra),
        )

    def test_handover_defaults_due_clock_signature_and_individual_food(self):
        before = self.store.version(self.signer)
        self.submit(roomId=self.first["roomId"])
        event = self.roster(self.signer)["pending"][0]
        self.assertEqual([self.first, self.second], event["residents"])
        self.assertFalse(event["ready"])
        self.assertFalse(self.events(self.first["id"]))
        with self.assertRaises(ValueError):
            self.sign(event["id"], [])
        self.assertEqual(0, self.store.version(self.signer)["groupActivityDue"])
        self.now += timedelta(minutes=1)
        self.assertEqual(
            before["revision"] + 1, self.store.version(self.signer)["revision"]
        )
        self.assertEqual(1, self.store.version(self.signer)["groupActivityDue"])
        self.assertEqual(0, self.store.version(self.carer)["groupActivityDue"])
        with self.assertRaises(PermissionError):
            self.sign(event["id"], [], self.carer)
        ids = [self.first["id"]]
        for extra in (
            {"mealIntake": {self.second["id"]: "错误的长者"}},
            {"mealIntake": {ids[0]: "字" * 301}},
        ):
            with self.assertRaises(ValueError):
                self.sign(event["id"], ids, **extra)
        self.sign(event["id"], ids, mealIntake={ids[0]: "半碗粥，未食蒸蛋"})
        self.assertFalse(self.events(self.second["id"]))
        self.assertEqual(
            self.events(ids[0], self.carer)[0]["confirmedByPosition"], "护士长"
        )
        (record,) = self.events(ids[0])
        self.assertEqual(
            (record["intake"], record["details"], record["roomNumber"]),
            ("半碗粥，未食蒸蛋", "小米粥、蒸蛋", self.first["roomNumber"]),
        )
        desk = self.roster()
        self.assertEqual([], desk["pending"])
        self.assertEqual(
            (
                desk["receipts"][0]["attendedCount"],
                desk["receipts"][0]["excludedCount"],
            ),
            (1, 1),
        )
        self.assertEqual(0, self.store.version(self.signer)["groupActivityDue"])
        self.sign(event["id"], ids, mealIntake={ids[0]: "半碗粥，未食蒸蛋"})
        with self.assertRaises(ValueError):
            self.sign(event["id"], ids, mealIntake={ids[0]: "不同记录"})
        with closing(self.store.connect()) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM daily_life_signatures").fetchone()[0],
                1,
            )
            self.assertTrue(
                db.execute(
                    "SELECT 1 FROM history_targets WHERE kind='resident' AND entity=?",
                    tuple(ids),
                ).fetchone()
            )

    def test_trial_attends_leave_is_omitted_and_transfer_preserves_snapshot(self):
        self.cmd(self.owner, "care.register", {"name": "合成试住"})
        state = self.store.snapshot(self.owner)["data"]
        rid = state["residents"][-1]["id"]
        spare, other = [b["id"] for b in state["beds"] if b["status"] == "空闲"][::2][
            :2
        ]
        self.cmd(
            self.owner,
            "care.admit",
            dict(residentId=rid, bedId=spare, stayType="trial", trialPrice=0),
        )
        self.cmd(
            self.owner,
            "care.leave",
            dict(
                residentId=self.first["id"],
                startDate=self.request["day"],
                endDate=self.request["day"],
            ),
        )
        residents = {p["id"]: p for p in self.roster()["residents"]}
        self.assertIn(rid, residents)
        self.assertNotIn(self.first["id"], residents)
        self.assertNotIn(
            rid, {p["id"] for p in self.roster(day="2026-11-23")["residents"]}
        )
        self.now += timedelta(hours=1)
        self.cmd(
            self.owner,
            "care.confirmGroupActivity",
            {**self.request, "residentIds": [rid], "confirmed": True},
        )
        room = residents[rid]["roomNumber"]
        self.cmd(self.owner, "care.transfer", dict(residentId=rid, bedId=other))
        self.store = Store(self.path, lambda: self.now)
        (record,) = self.events(rid)
        self.assertEqual((record["roomNumber"], record["intake"]), (room, ""))
        with self.assertRaises(ValueError):
            self.cmd(
                self.signer,
                "care.confirmGroupActivity",
                {
                    **self.request,
                    "requestId": "second",
                    "startsAt": "08:05",
                    "residentIds": [rid],
                    "confirmed": True,
                },
            )
        self.assertEqual(1, len(self.events(rid)))

    def test_older_backup_cannot_erase_a_signed_meal_or_individual_intake(self):
        svc = self.store.backups
        svc.capture()
        point = svc.status(self.owner)["points"][0]["id"]
        self.now += timedelta(minutes=2)
        rid = self.first["id"]
        self.cmd(
            self.signer,
            "care.confirmGroupActivity",
            {
                **self.request,
                "residentIds": [rid],
                "confirmed": True,
                "mealIntake": {rid: "实测半碗粥"},
            },
        )
        blockers = exchange.preview_point(svc, self.owner, point)["blockers"]
        self.assertIn("个人活动与进食记录", blockers)
        self.assertIn("活动签认凭证", blockers)
        self.assertEqual("实测半碗粥", self.events(rid)[0]["intake"])

    def test_scopes_and_competing_signatures(self):
        self.cmd(self.owner, "facility.addCampus", dict(name="合成分院"))
        east = self.roster()["campuses"][-1]["id"]
        east_staff = self.account("branch-head", "护士长", east)
        self.now += timedelta(minutes=2)
        self.submit()
        event = self.roster()["pending"][0]
        self.assertFalse(self.roster(east_staff)["pending"])
        self.assertFalse(self.roster(east_staff)["residents"])
        self.assertEqual(0, self.store.version(east_staff)["groupActivityDue"])
        with self.assertRaises(PermissionError):
            self.roster(east_staff, campus_id=self.campus)
        with self.assertRaises(PermissionError):
            self.sign(event["id"], [], east_staff)
        with self.assertRaises(PermissionError):
            self.events(self.first["id"], east_staff)
        rev = self.store.version(self.owner)["revision"]

        def compete(token):
            try:
                self.store.execute(
                    "care.confirmGroupActivity",
                    dict(eventId=event["id"], residentIds=[], confirmed=True),
                    rev,
                    token,
                )
                return True
            except Conflict:
                return False

        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(
                sorted(pool.map(compete, [self.signer, self.owner])), [False, True]
            )
        self.assertEqual(self.roster()["receipts"][0]["attendedCount"], 0)
        history = self.store.history(self.owner, roomId=self.first["roomId"])["rows"]
        self.assertIn("care.confirmGroupActivity", [r["action"] for r in history])
        self.assertFalse(self.events(self.first["id"]))

    def test_dates_duplicate_requests_and_group_count_permissions(self):
        self.submit()
        self.submit()
        self.assertEqual(len(self.roster()["pending"]), 1)
        for change in (
            dict(details="改过的内容"),
            dict(requestId="again"),
            dict(requestId="bad-clock", startsAt="08:45"),
            dict(day="2026-11-25"),
        ):
            with self.assertRaises(ValueError):
                self.submit(**change)
        self.now += timedelta(minutes=2)
        base = {
            **self.request,
            "requestId": "group",
            "kind": "集体活动",
            "details": "院内合唱",
            "confirmed": True,
            "residentIds": [self.first["id"]],
        }
        with self.assertRaises(ValueError):
            self.cmd(
                self.owner,
                "care.confirmGroupActivity",
                {**base, "mealIntake": {self.first["id"]: "餐食"}},
            )
        self.cmd(self.owner, "care.confirmGroupActivity", base)
        self.assertEqual("集体活动", self.events(self.first["id"])[0]["kind"])

    def test_bell_lands_in_branch_with_ready_group_and_covers_only_authorized_rooms(
        self,
    ):
        self.cmd(self.owner, "facility.addCampus", {"name": "活动分院"})
        campus = self.roster()["campuses"][-1]["id"]
        self.cmd(
            self.owner, "facility.addBuilding", {"campusId": campus, "name": "分院楼栋"}
        )
        directory = self.store.facility_resource(self.owner, "directory")
        building = next(b for b in directory["buildings"] if b["campusId"] == campus)
        self.cmd(
            self.owner, "facility.addFloor", {"buildingId": building["id"], "number": 1}
        )
        directory = self.store.facility_resource(self.owner, "directory")
        floor = next(b for b in directory["buildings"] if b["id"] == building["id"])[
            "floors"
        ][0]
        self.cmd(
            self.owner,
            "facility.addRoom",
            {"floorId": floor["id"], "number": "101", "ward": "分院区", "bedCount": 1},
        )
        person = self.first["id"]
        self.cmd(self.owner, "care.confirmGroupActivity", {
            **self.request, "requestId": "before-branch-move", "kind": "集体活动",
            "details": "本部晨间活动", "endsAt": "08:20", "residentIds": [person], "confirmed": True,
        })
        bed = self.store.snapshot(self.owner)["data"]["beds"][-1]["id"]
        self.cmd(self.owner, "care.transfer", {"residentId": person, "bedId": bed})
        new_branch = self.account("new-branch-head", "护士长", campus)
        self.assertEqual([], self.events(person, new_branch))
        self.assertEqual("本部晨间活动", self.events(person)[0]["details"])
        self.submit(campusId=campus)
        self.assertEqual(self.campus, self.roster()["campusId"])
        self.now += timedelta(minutes=2)
        desk = self.roster(self.signer)
        self.assertEqual(campus, desk["campusId"])
        (event,) = desk["pending"]
        self.assertEqual([person], [r["id"] for r in event["residents"]])
        home_nurse = self.account("home-head", "护士长", self.campus)
        self.assertEqual(0, self.store.version(home_nurse)["groupActivityDue"])
        self.assertFalse(self.roster(home_nurse)["pending"])

    def test_personal_portal_requires_self_binding_and_opt_in_and_hides_internal_ids(
        self,
    ):
        rid = self.first["id"]
        self.now += timedelta(minutes=2)
        self.cmd(
            self.signer,
            "care.confirmGroupActivity",
            {
                **self.request,
                "residentIds": [rid],
                "confirmed": True,
                "mealIntake": {rid: "小米粥半碗"},
            },
        )

        def login_person(name, own, scopes, resident_id):
            self.cmd(
                self.owner,
                "access.create",
                dict(
                    username=name,
                    displayName=name,
                    kind="family",
                    password=self.password,
                    residentId=resident_id,
                    portalSelf=own,
                    portalScopes=scopes,
                ),
            )
            return self.store.login(name, self.password)

        guest, _ = login_person("linked-relative", False, [], rid)
        resident, account = login_person("verified-elder", True, [], rid)
        other, _ = login_person(
            "different-elder", True, ["personalHealth"], self.second["id"]
        )
        for denied in (guest, resident, other):
            with self.assertRaises(PermissionError):
                self.events(rid, denied)
        self.cmd(
            self.owner,
            "access.update",
            dict(id=account["id"], portalScopes=["personalHealth"]),
        )
        (record,) = self.events(rid, resident)
        self.assertEqual(
            {
                "kind",
                "day",
                "startsAt",
                "endsAt",
                "details",
                "intake",
                "roomNumber",
                "confirmedAt",
                "confirmedBy",
                "confirmedByPosition",
            },
            set(record),
        )
        self.assertEqual(
            ("小米粥半碗", "护士长"), (record["intake"], record["confirmedByPosition"])
        )
        with self.assertRaises(PermissionError):
            self.events(self.second["id"], resident)
        self.cmd(self.owner, "access.update", dict(id=account["id"], portalScopes=[]))
        with self.assertRaises(PermissionError):
            self.events(rid, resident)
