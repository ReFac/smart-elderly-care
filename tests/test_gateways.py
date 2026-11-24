import sqlite3
from copy import deepcopy
from unittest import TestCase

from platform_core import care, gateways

TODAY = "2026-11-24"


def user(name, *permissions):
    return {
        "id": name,
        "kind": "staff",
        "displayName": name,
        "permissions": list(permissions),
    }


class GatewayCases(TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        gateways.init(self.db)
        self.state = care.seed(TODAY)
        self.sensor = user("值班台", "gateway.simulate")
        self.nurse = user("护士甲", "alerts")
        self.proposer = user("护工甲", "voice", "care")
        self.first = user("护工乙", "voice.confirm", "care")
        self.second = user("护工丙", "voice.confirm", "care")
        self.event = {
            "source": "radar",
            "eventId": "radar-09:192",
            "signal": "possible_fall",
            "bedId": "b001",
            "observation": "地面区域出现目标，需现场核实",
            "evidenceRef": "frame-3",
            "observedAt": "2026-11-24T11:30:00+08:00",
        }
        self.task = next(
            t
            for t in self.state["tasks"]
            if t["date"] == TODAY and t["status"] == "待执行"
        )
        self.proposal = {
            "taskId": self.task["id"],
            "requestId": "demo-001",
            "note": "日常服务已完成",
            "transcript": "请登记本次照护服务已完成",
        }

    def call(self, action, payload, actor):
        with self.db:
            return gateways.apply(
                self.db, self.state, "gw." + action, payload, actor, TODAY
            )

    def view(self, actor):
        return gateways.project(self.db, {}, actor)

    def alert(self):
        self.call("ingest", self.event, self.sensor)
        return self.view(self.nurse)["gatewayAlerts"][0]

    def pending(self):
        self.call("propose", self.proposal, self.proposer)
        return self.view(self.first)["voiceQueue"][0]

    def test_catalog_schemas_and_private_model(self):
        catalog = gateways.catalog()
        ids = [p["id"] for p in catalog]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("iot.youle", ids)
        self.assertIn("badge.service-export", ids)
        for spec in catalog:
            self.assertTrue(spec["requestSchema"]["properties"])
            self.assertTrue(spec["responseSchema"]["properties"])
            self.assertEqual(spec["status"], "reserved")
        self.assertNotIn(
            "deepseek-summary",
            [p["id"] for p in self.view(self.sensor)["integrationCatalog"]],
        )
        self.assertIn(
            "deepseek-summary",
            [
                p["id"]
                for p in self.view({"id": "owner", "kind": "owner"})[
                    "integrationCatalog"
                ]
            ],
        )

    def test_independent_signals_share_one_review_and_keep_both_observations(self):
        first = self.alert()
        other = dict(
            self.event,
            source="sensor",
            eventId="sensor-2",
            observedAt="2026-11-24T11:31:30+08:00",
        )
        self.call("ingest", other, self.sensor)
        alerts = self.view(self.nurse)["gatewayAlerts"]
        self.assertEqual([r["id"] for r in alerts], [first["id"]])
        self.assertEqual(
            {r["eventId"] for r in alerts[0]["observations"]},
            {other["eventId"], self.event["eventId"]},
        )
        before = len(self.state["archives"])
        self.call(
            "review",
            {
                "alertId": first["id"],
                "decision": "已核实",
                "residentId": first["candidates"][0],
                "note": "现场记录",
            },
            self.nurse,
        )
        self.assertEqual(len(self.state["archives"]), before + 1)
        self.assertEqual(
            self.db.execute(
                "SELECT count(*) FROM gateway_alert WHERE status='已核实'"
            ).fetchone()[0],
            2,
        )
        self.call("ingest", dict(other, eventId="sensor-3"), self.sensor)
        self.assertEqual(len(self.view(self.nurse)["gatewayAlerts"]), 2)

    def test_observations_outside_episode_and_different_signals_stay_separate(self):
        self.alert()
        self.call(
            "ingest",
            dict(
                self.event,
                source="sensor",
                eventId="sensor-late",
                observedAt="2026-11-24T11:31:31+08:00",
            ),
            self.sensor,
        )
        self.call(
            "ingest",
            dict(self.event, eventId="bedrest", signal="prolonged_bedrest"),
            self.sensor,
        )
        rows = self.view(self.nurse)["gatewayAlerts"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            [r["priority"] for r in rows], ["优先现场核实", "优先现场核实", "现场观察"]
        )

    def test_duplicate_report_only_creates_one_alert_and_no_file_update(self):
        before = deepcopy(self.state["archives"])
        alert = self.alert()
        self.call(
            "ingest",
            {**self.event, "eventId": " " + self.event["eventId"] + " "},
            self.sensor,
        )
        self.assertEqual(self.state["archives"], before)
        self.assertEqual(len(self.view(self.nurse)["gatewayAlerts"]), 1)
        self.assertEqual(alert["room"], "颐养一区 / 101")
        with self.assertRaises(ValueError):
            self.call("ingest", {**self.event, "bedId": "b005"}, self.sensor)
        self.assertEqual(self.view(self.sensor)["gatewayAlerts"], [])
        with self.assertRaises(PermissionError):
            self.call(
                "review",
                {"alertId": alert["id"], "decision": "误报", "note": "复核"},
                self.sensor,
            )

    def test_nurse_resolves_one_actual_person_with_the_original_room(self):
        alert = self.alert()
        first, second = alert["candidates"]
        payload = {
            "alertId": alert["id"],
            "decision": "已核实",
            "note": "已到现场查看并完成登记",
        }
        with self.assertRaises(ValueError):
            self.call("review", {**payload, "residentId": "r003"}, self.nurse)
        care.apply(
            self.state, "care.transfer", {"residentId": second, "bedId": "b016"}, TODAY
        )
        self.call("review", {**payload, "residentId": second}, self.nurse)
        entry = self.state["archives"][-1]
        self.assertEqual(
            (entry["residentId"], entry["room"], entry["reviewerId"]),
            (second, alert["room"], self.nurse["id"]),
        )
        self.assertEqual(
            gateways.audit_context(self.db, self.state, "gw.review", payload),
            {"residentId": second, "room": alert["room"]},
        )
        with self.assertRaises(ValueError):
            self.call("review", {**payload, "residentId": first}, self.nurse)

    def test_false_alarm_does_not_update_medical_history(self):
        alert = self.alert()
        before = deepcopy(self.state)
        self.call(
            "review",
            {"alertId": alert["id"], "decision": "误报", "note": "目标为掉落物品"},
            self.nurse,
        )
        self.assertEqual(before, self.state)

    def test_voice_receipts_deduplicate_and_only_first_confirmation_changes_task(self):
        proposal = self.pending()
        self.call("propose", self.proposal, self.proposer)
        with self.assertRaises(ValueError):
            self.call(
                "propose", {**self.proposal, "requestId": "another"}, self.proposer
            )
        self.assertEqual(
            [r["id"] for r in self.view(self.second)["voiceQueue"]], [proposal["id"]]
        )
        self.assertEqual(self.view(self.proposer)["voiceQueue"], [])
        self.assertEqual(self.task["status"], "待执行")
        self.call(
            "confirm",
            {"proposalId": proposal["id"], "operator": "伪造姓名"},
            self.first,
        )
        self.assertEqual(self.view(self.second)["voiceQueue"], [])
        self.assertEqual(
            (self.task["status"], self.task["note"], self.task["operatorId"]),
            ("已完成", self.proposal["note"], self.first["id"]),
        )
        with self.assertRaises(ValueError):
            self.call("confirm", {"proposalId": proposal["id"]}, self.second)

    def test_voice_target_and_action_cannot_be_changed_by_requester(self):
        with self.assertRaises(ValueError):
            self.call(
                "propose", {**self.proposal, "targetAction": "ops.pay"}, self.proposer
            )
        with self.assertRaises(PermissionError):
            self.call("propose", self.proposal, user("其他", "voice"))
        item = self.pending()
        with self.assertRaises(PermissionError):
            self.call(
                "confirm", {"proposalId": item["id"]}, user("其他", "voice.confirm")
            )
        self.call(
            "confirm",
            {"proposalId": item["id"], "taskId": "bad", "note": "覆盖"},
            self.first,
        )
        self.assertEqual(self.task["note"], self.proposal["note"])

    def test_transfer_back_prevents_stale_voice_confirmation(self):
        item = self.pending()
        resident = next(
            r for r in self.state["residents"] if r["id"] == item["residentId"]
        )
        initial = resident["bedId"]
        vacant = next(b for b in self.state["beds"] if not b["residentId"])
        for bed in [vacant["id"], initial]:
            care.apply(
                self.state,
                "care.transfer",
                {"residentId": resident["id"], "bedId": bed},
                TODAY,
            )
        with self.assertRaises(ValueError):
            self.call("confirm", {"proposalId": item["id"]}, self.first)
        self.call(
            "dismiss",
            {"proposalId": item["id"], "reason": "床位分配已变更"},
            self.first,
        )
        self.assertEqual(self.task["status"], "待执行")
        self.assertEqual(self.view(self.first)["voiceQueue"], [])


class ConcurrentVoiceReceipt(TestCase):
    def test_two_staff_one_confirmation_and_room_receipt(self):
        from concurrent.futures import ThreadPoolExecutor
        from datetime import datetime
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from threading import Barrier
        from unittest.mock import patch
        from platform_core.store import Conflict, Store, TIMEZONE

        password = "test-credentials-42"
        with (
            TemporaryDirectory() as directory,
            patch.dict("os.environ", {"NH_OWNER_PASSWORD": password}),
        ):
            store = Store(
                Path(directory) / "race.sqlite3",
                lambda: datetime(2026, 11, 24, 12, tzinfo=TIMEZONE),
            )
            owner, _ = store.login("owner", password)
            workers = []
            for i in range(2):
                username = "worker" + str(i)
                store.execute(
                    "access.create",
                    {
                        "kind": "staff",
                        "role": "护工",
                        "username": username,
                        "displayName": "护工" + str(i),
                        "password": password,
                    },
                    i,
                    owner,
                )
                workers.append(store.login(username, password)[0])
            state = store.snapshot(workers[0])["data"]
            task = next(
                t
                for t in state["tasks"]
                if t["status"] == "待执行" and t["date"] == TODAY
            )
            store.execute(
                "gw.propose",
                {
                    "transcript": "已完成活动陪伴",
                    "note": "活动照护已结束",
                    "taskId": task["id"],
                    "requestId": "voice-A",
                },
                2,
                workers[0],
            )
            item = store.snapshot(workers[1])["data"]["voiceQueue"][0]
            gate = Barrier(2)

            def confirm(token):
                gate.wait()
                try:
                    store.execute("gw.confirm", {"proposalId": item["id"]}, 3, token)
                    return "confirmed"
                except Conflict:
                    return "conflict"

            with ThreadPoolExecutor(max_workers=2) as executor:
                self.assertCountEqual(
                    executor.map(confirm, workers), ["confirmed", "conflict"]
                )
            for token in workers:
                self.assertEqual(store.snapshot(token)["data"]["voiceQueue"], [])
            audit = store.activity(owner, room=item["room"])["rows"]
            events = [e for e in audit if e["action"] == "gw.confirm"]
            self.assertEqual(len(events), 1)
            event = events[0]
            self.assertEqual(
                store.activity(owner, actor=event["actorId"], room=item["room"])[
                    "rows"
                ][0]["revision"],
                4,
            )
