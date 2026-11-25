from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from platform_core.store import Conflict, Store, TIMEZONE


class RoundsTests(unittest.TestCase):
    def setUp(self):
        from provider_fixture import simulate_narration

        simulate_narration(self)
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "synthetic.sqlite3"
        self.now = datetime(2026, 11, 24, 11, 15, tzinfo=TIMEZONE)
        self.password = "isolated-rounds-password"
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": self.password}):
            self.store = Store(self.path, lambda: self.now)
        self.owner, _ = self.store.login("owner", self.password)
        self.base = "/api/rounds/residents/r001"
        self.settings = "/api/rounds/settings"

    def send(self, path, data, token=None):
        token = token or self.owner
        return self.store.rounds.write(
            token, path, {"revision": self.store.version(token)["revision"], **data}
        )

    def read(self, path, token=None):
        return self.store.rounds.read(token or self.owner, path)

    def account(self, name, role):
        self.store.execute(
            "access.create",
            {
                "kind": "staff",
                "displayName": name,
                "username": name,
                "role": role,
                "password": self.password,
            },
            self.store.version(self.owner)["revision"],
            self.owner,
        )
        return self.store.login(name, self.password)[0]

    def observation(self, offset, count, **extra):
        return {
            "day": (self.now.date() - timedelta(days=offset)).isoformat(),
            "hour": 9,
            "count": count,
            "observedMinutes": 60,
            "source": "yamnet:wearable-1:0.50",
            "reviewed": True,
            "attribution": "wearable",
            **extra,
        }

    def test_observation_dedup_and_matched_baseline(self):
        path = self.base + "/observations"
        body = self.observation(0, 6)
        first = self.send(path, body)
        replay = self.send(path, {**body, "revision": first["revision"] - 1})
        self.assertFalse(replay["changed"])
        self.assertEqual(first["revision"], replay["revision"])
        with self.assertRaises(ValueError):
            self.send(path, {**body, "count": 99})
        for extra in (
            {"hour": 11, "observedMinutes": 16},
            {"hour": 13},
            {"reviewed": False},
            {"attribution": "room"},
            {"count": True},
            {"source": ""},
        ):
            with self.assertRaises(ValueError):
                self.send(path, {**body, **extra})
        for offset, events, fields in (
            (1, 2, {}),
            (2, 5, {}),
            (3, 12, {"source": "other"}),
            (4, 3, {"hour": 2}),
            (5, 2, {"observedMinutes": 15}),
            (6, 3, {"attribution": "staff-verified"}),
        ):
            self.send(path, self.observation(offset, events, **fields))
        early = self.send(self.base + "/generate", {})["latest"]
        self.assertEqual(
            ("insufficient", 2),
            (early["cough"]["status"], early["cough"]["historyDays"]),
        )
        self.send(path, self.observation(7, 3))
        report = self.send(self.base + "/generate", {})["latest"]
        self.assertEqual(
            ("elevated", 3, 6, 60),
            tuple(
                report["cough"][k]
                for k in ("status", "baseline", "rate", "observedMinutes")
            ),
        )
        self.assertTrue(
            any(
                c["evidence"][0]["kind"] == "reviewedCough"
                for c in report["changes"]
                if c["evidence"]
            )
        )
        self.assertFalse(self.send(self.base + "/generate", {})["changed"])

    def test_permissions_conflict_and_scoped_reports(self):
        token = self.account("rounds-staff", "护工")
        with self.assertRaises(PermissionError):
            self.read(self.settings, token)
        with self.assertRaises(PermissionError):
            self.send(self.base + "/observations", self.observation(0, 0), token)
        with self.assertRaises(Conflict):
            self.send(self.base + "/mode", {"mode": "manual", "revision": 0})
        self.assertEqual("inherit", self.read(self.base)["mode"])
        report = self.send(self.base + "/generate", {}, token)["latest"]
        self.assertIsNone(report["cough"])
        self.assertEqual("deepseek", report["source"])
        self.assertTrue(
            all(
                row["permission"] == "care"
                for row in report["changes"] + report["suggestions"]
            )
        )
        with closing(self.store.connect()) as db:
            room = db.execute(
                "SELECT roomId FROM facility_beds WHERE bedId='b003'"
            ).fetchone()[0]
        restricted = Store(
            self.path,
            lambda: self.now,
            facility_policy=lambda db, actor: {"roomIds": [room]},
        )
        with self.assertRaises(PermissionError):
            restricted.rounds.read(token, self.base)
        self.assertEqual(
            [], restricted.rounds.read(token, "/api/rounds/inbox")["items"]
        )

    def test_restart_claims_only_current_day_no_duplicate_deliveries(self):
        self.send(
            self.settings,
            {
                "enabled": True,
                "intervalMinutes": 30,
                "defaultMode": "manual",
                "notifyAt": "12:00",
            },
        )
        self.send(self.base + "/mode", {"mode": "auto"})
        with ThreadPoolExecutor(max_workers=2) as pool:
            runs = list(pool.map(lambda _: self.store.rounds.tick(), range(2)))
        self.assertEqual(1, sum(r["generated"] for r in runs))
        self.assertEqual(0, sum(r["delivered"] for r in runs))
        self.assertEqual([], self.read("/api/rounds/inbox")["items"])
        self.now += timedelta(hours=2)
        reopened = Store(self.path, lambda: self.now)
        self.assertEqual(1, reopened.rounds.tick()["delivered"])
        self.assertEqual(0, self.store.rounds.tick()["delivered"])
        inbox = self.read("/api/rounds/inbox")
        self.assertEqual(1, inbox["total"])
        self.assertEqual(
            1, self.store.snapshot(self.owner)["data"]["roundsNoticeCount"]
        )
        self.assertEqual("r001", inbox["items"][0]["residentId"])
        report = self.read(self.base)["latest"]
        self.now += timedelta(days=3)
        reopened.rounds.tick()
        self.assertEqual(
            self.now.date().isoformat(), self.read(self.base)["latest"]["day"]
        )
        self.assertNotEqual(report["id"], self.read(self.base)["latest"]["id"])
        with closing(self.store.connect()) as db:
            self.assertEqual(
                2,
                db.execute("SELECT COUNT(DISTINCT day) FROM rounds_reports").fetchone()[
                    0
                ],
            )
            self.assertEqual(
                0, db.execute("SELECT COUNT(*) FROM rounds_jobs").fetchone()[0]
            )

    def test_crash_keeps_claim_and_prevents_partial_report(self):
        self.send(
            self.settings,
            {
                "enabled": True,
                "intervalMinutes": 30,
                "defaultMode": "manual",
                "notifyAt": "22:00",
            },
        )
        self.send(self.base + "/mode", {"mode": "auto"})
        with patch(
            "platform_core.rounds.records.build",
            side_effect=KeyboardInterrupt("test crash"),
        ):
            with self.assertRaises(KeyboardInterrupt):
                self.store.rounds.tick()
        with closing(self.store.connect()) as db:
            self.assertEqual(
                1, db.execute("SELECT COUNT(*) FROM rounds_jobs").fetchone()[0]
            )
            self.assertEqual(
                0, db.execute("SELECT COUNT(*) FROM rounds_reports").fetchone()[0]
            )
        # A process can die while waiting on DeepSeek; another worker must respect
        # that lease before retrying and billing for the same resident.
        self.assertEqual(
            0, Store(self.path, lambda: self.now).rounds.tick()["generated"]
        )
        self.now += timedelta(minutes=5)
        self.assertEqual(
            1, Store(self.path, lambda: self.now).rounds.tick()["generated"]
        )

    def test_daily_send_refreshes_auto_residents_even_when_next_regular_sweep_is_tomorrow(
        self,
    ):
        self.send(
            self.settings,
            {
                "enabled": True,
                "intervalMinutes": 1440,
                "defaultMode": "manual",
                "notifyAt": "12:00",
            },
        )
        self.send(self.base + "/mode", {"mode": "auto"})
        self.store.rounds.tick()
        first = self.read(self.base)["latest"]
        next_run = self.read(self.settings)["settings"]["nextRunAt"]
        self.store.execute(
            "care.addTask",
            {
                "residentId": "r001",
                "date": self.now.date().isoformat(),
                "time": "11:30",
                "title": "交班前查房",
                "assignee": "当班人员",
                "kind": "日常照护",
            },
            self.store.version(self.owner)["revision"],
            self.owner,
        )
        self.now = self.now.replace(hour=12, minute=0)
        self.assertEqual(1, self.store.rounds.tick()["generated"])
        self.assertEqual(next_run, self.read(self.settings)["settings"]["nextRunAt"])
        inbox = self.read("/api/rounds/inbox")["items"][0]
        self.assertEqual(first["today"]["pending"] + 1, inbox["today"]["pending"])
        self.assertEqual(0, self.store.rounds.tick()["delivered"])

    def test_failure_for_one_resident_retries_without_blocking_others(self):
        from platform_core.rounds import records

        self.send(
            self.settings,
            {
                "enabled": True,
                "intervalMinutes": 60,
                "defaultMode": "manual",
                "notifyAt": "18:00",
            },
        )
        self.send(self.base + "/mode", {"mode": "auto"})
        self.send("/api/rounds/residents/r002/mode", {"mode": "auto"})
        real = records.build

        def flaky(db, state, resident, now):
            if resident["id"] == "r001":
                raise ValueError("synthetic failure")
            return real(db, state, resident, now)

        with (
            self.assertLogs("platform_core.rounds.scheduler", level="ERROR"),
            patch.object(records, "build", side_effect=flaky),
        ):
            result = self.store.rounds.tick()
        self.assertEqual(1, result["generated"])
        self.assertIsNone(self.read(self.base)["latest"])
        self.assertIsNotNone(self.read("/api/rounds/residents/r002")["latest"])
        self.now += timedelta(minutes=1)
        self.assertEqual(1, self.store.rounds.tick()["generated"])

    def test_online_import_recovers_missing_hourly_evidence_and_report(self):
        from platform_core import secure_storage
        from platform_core.backups import exchange, restore_plan

        self.send(self.base + "/observations", self.observation(0, 7))
        report = self.send(self.base + "/generate", {})["latest"]
        packet = self.path.parent / "with-evidence.akbak"
        secure_storage.create_snapshot(self.store, packet)
        # Simulate an earlier, otherwise equivalent household database.
        with closing(self.store.connect()) as db, db:
            db.execute("DELETE FROM rounds_observations")
            db.execute("DELETE FROM rounds_reports")
        with (
            exchange.restored(self.store.backups, packet) as incoming,
            closing(self.store.connect()) as db,
            db,
        ):
            restore_plan.attach(db, incoming, self.store)
            diff = restore_plan.describe(db)
            self.assertEqual([], diff["blockers"])
            self.assertIn(
                "已核对咳嗽时段观测", [row["label"] for row in diff["changes"]]
            )
            restore_plan.apply(db)
        self.assertEqual(report, self.read(self.base)["latest"])
        self.assertEqual(7, self.read(self.base + "/observations")["rows"][0]["count"])

    def test_staff_signals_are_scoped_and_family_digest_is_independent(self):
        staff = self.account("signals-aide", "护工")
        self.send(
            self.settings,
            {
                "enabled": True,
                "intervalMinutes": 60,
                "defaultMode": "manual",
                "notifyAt": "10:00",
            },
        )

        def records(tasks, vitals):
            with closing(self.store.connect()) as db, db:
                state = json.loads(
                    db.execute("SELECT data FROM workspace").fetchone()[0]
                )
                state.update(tasks=tasks, vitals=vitals)
                db.execute(
                    "UPDATE workspace SET data=?,revision=revision+1",
                    (json.dumps(state),),
                )
            self.send(self.base + "/generate", {})

        def action(token, name, **args):
            self.store.execute(name, args, self.store.version(token)["revision"], token)

        records([], [])
        self.assertEqual(0, self.store.rounds.tick()["delivered"])
        with patch(
            "platform_core.rounds.scheduler.workspace",
            side_effect=AssertionError("unchanged queue reprocessed"),
        ):
            self.assertEqual(0, self.store.rounds.tick()["delivered"])
        self.assertEqual([], self.read("/api/rounds/inbox")["items"])

        # A new family subscription after the delivery time still receives exactly one neutral daily summary.
        action(
            self.owner,
            "access.create",
            username="rounds-family",
            kind="family",
            residentId="r001",
            displayName="rounds-family",
            password=self.password,
        )
        family, account = self.store.login("rounds-family", self.password)
        action(
            self.owner,
            "family.consent",
            residentId="r001",
            accountId=account["id"],
            enabled=True,
            method="长辈当面确认",
            evidence="测试环境确认分享",
        )
        action(family, "family.subscribe", residentId="r001", enabled=True)
        self.assertEqual(1, self.store.rounds.tick()["delivered"])
        self.assertEqual(0, self.store.rounds.tick()["delivered"])
        self.assertEqual(
            1, len(self.store.snapshot(family)["data"]["familyRoundInbox"]["messages"])
        )
        self.assertEqual(
            0, self.store.snapshot(self.owner)["data"]["roundsNoticeCount"]
        )

        vital = {
            "id": "synthetic-vital",
            "residentId": "r001",
            "date": "2026-11-15",
            "status": "待复核",
            "metric": "观察",
            "value": "记录",
            "abnormal": True,
        }
        records([], [vital])
        self.store.rounds.tick()
        self.assertEqual(
            ["vital"], self.read("/api/rounds/inbox")["items"][0]["signals"]
        )
        self.assertEqual([], self.read("/api/rounds/inbox", staff)["items"])
        self.assertEqual(0, self.store.snapshot(staff)["data"]["roundsNoticeCount"])
        task = {
            "id": "synthetic-task",
            "residentId": "r001",
            "date": "2026-11-15",
            "time": "09:00",
            "status": "待执行",
            "title": "床旁核查",
            "assignee": "当班人员",
        }
        records([task], [vital])
        self.store.rounds.tick()
        self.assertEqual(
            ["carry", "vital"], self.read("/api/rounds/inbox")["items"][0]["signals"]
        )
        self.assertEqual(
            ["carry"], self.read("/api/rounds/inbox", staff)["items"][0]["signals"]
        )
        self.assertEqual(1, self.store.snapshot(staff)["data"]["roundsNoticeCount"])
        records([], [])
        self.store.rounds.tick()
        self.assertFalse(self.read("/api/rounds/inbox")["items"])
        self.assertEqual(
            1, len(self.store.snapshot(family)["data"]["familyRoundInbox"]["messages"])
        )

    def test_online_import_legacy_packet_preserves_new_records_and_settings(self):
        from platform_core import secure_storage
        from platform_core.backups import exchange, restore_plan

        packet = self.path.parent / "legacy.akbak"
        with closing(self.store.connect()) as db, db:
            for table in restore_plan.OPTIONAL_TABLES:
                db.execute(f'DROP TABLE "{table}"')
        secure_storage.create_snapshot(self.store, packet)
        self.store = Store(self.path, lambda: self.now)
        self.send(self.base + "/observations", self.observation(0, 1))
        report = self.send(self.base + "/generate", {})["latest"]["id"]
        self.send(self.base + "/mode", {"mode": "manual"})
        with (
            exchange.restored(self.store.backups, packet) as incoming,
            closing(self.store.connect()) as db,
            db,
        ):
            restore_plan.attach(db, incoming, self.store)
            self.assertEqual([], restore_plan.describe(db)["blockers"])
            restore_plan.apply(db)
        self.assertEqual(report, self.read(self.base)["latest"]["id"])
        self.assertEqual("manual", self.read(self.base)["mode"])
        self.assertEqual(1, len(self.read(self.base + "/observations")["rows"]))

    def test_online_import_cannot_erase_or_overwrite_observations_and_reports(self):
        from platform_core import secure_storage
        from platform_core.backups import exchange, restore_plan

        packet = self.path.parent / "before.akbak"
        secure_storage.create_snapshot(self.store, packet)
        self.send(self.base + "/observations", self.observation(0, 1))
        self.send(self.base + "/generate", {})
        with (
            exchange.restored(self.store.backups, packet) as incoming,
            closing(self.store.connect()) as db,
        ):
            restore_plan.attach(db, incoming, self.store)
            blockers = restore_plan.describe(db)["blockers"]
        self.assertIn("已核对咳嗽时段观测", blockers)
        self.assertIn("已生成的长辈巡查简报", blockers)

    def test_daily_life_describes_confirmed_meals_and_observations_without_inventing_normality(
        self,
    ):
        now = self.now.date().isoformat()
        with closing(self.store.connect()) as db:
            room = db.execute(
                "SELECT roomId FROM facility_beds WHERE bedId='b001'"
            ).fetchone()[0]
            campus = db.execute("SELECT id FROM facility_campuses LIMIT 1").fetchone()[
                0
            ]

        def command(action, **data):
            self.store.execute(
                action, data, self.store.version(self.owner)["revision"], self.owner
            )

        def meal(kind, day, detail, people, **fields):
            command(
                "care.confirmGroupActivity",
                campusId=campus,
                roomId=room,
                day=day,
                kind=kind,
                startsAt="07:00",
                endsAt="07:30",
                details=detail,
                requestId=kind.encode().hex(),
                residentIds=people,
                confirmed=True,
                **fields,
            )

        yesterday = (self.now.date() - timedelta(days=1)).isoformat()
        meal("午餐", yesterday, "萝卜汤", ["r001"])
        meal(
            "早餐",
            now,
            "小米粥、鸡蛋",
            ["r001", "r002"],
            mealIntake={"r001": "喝了半碗小米粥", "r002": "只吃了两个鸡蛋"},
        )
        meal("晚餐", yesterday, "牛肉面", ["r002"])
        command(
            "care.addTask",
            residentId="r001",
            kind="日常照护",
            date=now,
            time="07:00",
            title="协助起床",
            assignee="当班人员",
            note="计划请评估睡眠情况",
        )
        task = self.store.snapshot(self.owner)["data"]["tasks"][-1]
        command(
            "care.completeTask",
            taskId=task["id"],
            operator="当班人员",
            note="和平时一样自己起床。",
        )
        report = self.send(self.base + "/generate", {})["latest"]
        days = {row["day"] for row in report["changes"]}
        story = "".join(row["text"] for row in report["changes"])
        self.assertEqual(days, {yesterday, now})
        for term in (
            "萝卜汤",
            "参加了午餐",
            "早餐喝了半碗小米粥",
            "和平时一样自己起床",
        ):
            self.assertIn(term, story)
        for term in (
            "计划请评估",
            "两个鸡蛋",
            "牛肉面",
            "身体正常",
            "咳嗽",
            "跌倒",
            "工单",
            "执行",
        ):
            self.assertNotIn(term, story)
        self.assertEqual([], report["suggestions"])

    def test_only_noticeable_trend_and_confirmed_fall_reach_person_brief(self):
        for offset, count in ((1, 10), (2, 10), (3, 10), (0, 11)):
            self.send(self.base + "/observations", self.observation(offset, count))
        payload = {
            "source": "radar",
            "eventId": "synthetic-fall",
            "signal": "possible_fall",
            "bedId": "b002",
            "observedAt": self.now.replace(hour=9).isoformat(),
        }

        def command(action, data):
            self.store.execute(
                action, data, self.store.version(self.owner)["revision"], self.owner
            )

        command("gw.ingest", payload)
        first = self.send(self.base + "/generate", {})["latest"]
        self.assertEqual(first["cough"]["status"], "elevated")
        self.assertFalse(first["cough"]["noticeable"])
        self.assertNotRegex(str(first["changes"] + first["suggestions"]), "咳嗽|跌倒")
        eid = self.store.snapshot(self.owner)["data"]["gatewayAlerts"][0]["id"]
        command(
            "gw.review",
            {
                "alertId": eid,
                "decision": "已核实",
                "residentId": "r001",
                "note": "已在现场核对",
            },
        )
        second = self.send(self.base + "/generate", {})["latest"]
        self.assertIn("发生过一次跌倒", str(second["changes"]))
        self.assertNotIn(
            "发生过一次跌倒",
            str(
                self.send("/api/rounds/residents/r002/generate", {})["latest"][
                    "changes"
                ]
            ),
        )

    def test_personal_brief_is_read_only_individually_granted_and_contains_no_internal_evidence(
        self,
    ):
        def action(name, **data):
            self.store.execute(
                name, data, self.store.version(self.owner)["revision"], self.owner
            )

        def view(token, rid="r001"):
            return self.store.rounds.personal_brief(token, rid)

        for name, personal in [("self-brief", True), ("relative-brief", False)]:
            action(
                "access.create",
                kind="family",
                portalSelf=personal,
                username=name,
                displayName=name,
                password=self.password,
                residentId="r001",
            )
        myself, user = self.store.login("self-brief", self.password)
        relative, _ = self.store.login("relative-brief", self.password)
        for token in [self.owner, relative, myself]:
            with self.assertRaises(PermissionError):
                view(token)
        action("access.update", id=user["id"], portalScopes=["personalHealth"])
        with self.assertRaises(PermissionError):
            view(myself, "r002")
        self.assertEqual(view(myself), {"day": None, "paragraphs": []})
        now = self.now.date().isoformat()

        def complete(title, note):
            action(
                "care.addTask",
                residentId="r001",
                kind="日常照护",
                date=now,
                time="07:00",
                title=title,
                assignee="不能公开的经办人",
            )
            task = self.store.snapshot(self.owner)["data"]["tasks"][-1]
            action(
                "care.completeTask", taskId=task["id"], operator="机构负责人", note=note
            )

        complete("协助起床", "早上像平时一样自己起床。")
        complete("个人观察", "不能公开的经办人说了内部细节 13900002222")
        report = self.send(self.base + "/generate", {})["latest"]
        self.assertIn("内部细节", str(report["changes"]))
        before = self.store.version(myself)["revision"]
        with patch(
            "platform_core.rounds.records.interpret",
            side_effect=AssertionError("should only read"),
        ):
            result = view(myself)
        self.assertEqual(before, self.store.version(myself)["revision"])
        self.assertEqual(set(result), {"day", "paragraphs"})
        for item in result["paragraphs"]:
            self.assertEqual(set(item), {"text", "day"})
        self.assertIn("像平时一样自己起床", str(result))
        for forbidden in (
            "1390000",
            "经办人",
            "机构负责人",
            "dossier",
            "r001",
            "evidence",
            "planned",
            "内部细节",
        ):
            self.assertNotIn(forbidden, str(result))
        action("access.update", id=user["id"], portalScopes=[])
        with self.assertRaises(PermissionError):
            view(myself)

    def test_previous_stay_hidden_even_after_return_to_same_bed(self):
        report = self.send(self.base + "/generate", {})["latest"]
        with closing(self.store.connect()) as db, db:
            state = json.loads(db.execute("SELECT data FROM workspace").fetchone()[0])
            state["bedMoves"].append(
                {
                    "id": "testReturn",
                    "residentId": "r001",
                    "bedId": report["bedId"],
                    "beforeBedId": "elsewhere",
                    "date": self.now.date().isoformat(),
                }
            )
            db.execute("UPDATE workspace SET data=?", (json.dumps(state),))
        self.assertIsNone(self.read(self.base)["latest"])
        with self.assertRaises(ValueError):
            self.send(self.base + "/observations", self.observation(2, 1))
        next_report = self.send(self.base + "/generate", {})["latest"]
        self.assertNotEqual(report["id"], next_report["id"])
        self.assertEqual(0, next_report["today"]["planned"])
