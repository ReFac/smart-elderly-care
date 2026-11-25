"""Shift changes bind the receipt to a live account and freeze the original evidence."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

from platform_core import activity
from platform_core.store import Conflict, SignedOut, Store, TIMEZONE


class ShiftHandoverTests(unittest.TestCase):
    password = "local-shift-fixture!"
    resident = "r001"

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "test.sqlite"
        self.instant = datetime(2026, 11, 24, 16, 30, tzinfo=TIMEZONE)
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": self.password}):
            self.store = Store(self.path, now=lambda: self.instant)
        self.owner, self.owner_account = self.store.login("owner", self.password)

    def execute(self, token, action, **payload):
        revision = self.store.version(token)["revision"]
        return self.store.execute(action, payload, revision, token)

    def account(self, login, *grants, name="值班同事", family=False):
        self.execute(
            self.owner,
            "access.create",
            username=login,
            displayName=name,
            password=self.password,
            **(
                {"kind": "family", "residentId": self.resident}
                if family
                else {"kind": "staff", "role": "自定义", "permissions": list(grants)}
            ),
        )
        return self.store.login(login, self.password)

    def submit(self, token, recipient, **more):
        self.execute(
            token,
            "care.handover",
            assigneeId=recipient["id"],
            residentId=self.resident,
            note="请接续未完成工单",
            **more,
        )
        return self.store.snapshot(token)["data"]["handovers"][-1]

    def test_recipient_directory_checks_live_grants_and_discloses_only_directory_fields(
        self,
    ):
        sender, sender_account = self.account("outgoing", "care")
        _, receiver = self.account("incoming", "care")
        other, other_account = self.account("accounting", "finance")
        family, family_account = self.account("family-login", family=True)
        _, disabled = self.account("disabled", "care")
        self.execute(self.owner, "access.update", id=disabled["id"], enabled=False)
        self.execute(
            self.owner, "access.create", kind="staff", role="自定义", permissions=["care"],
            displayName="尚未激活的接班员工", username="handover-pending-worker",
            invitation={"channel": "sms", "destination": "13900001025"},
        )
        pending = next(a for a in self.store.snapshot(self.owner)["data"]["accounts"]
                       if a["username"] == "handover-pending-worker")
        self.assertTrue(pending["activationPending"])
        listed = self.store.handover_recipients(sender)["recipients"]
        self.assertEqual(
            {r["id"] for r in listed}, {self.owner_account["id"], receiver["id"]}
        )
        for row in listed:
            self.assertEqual(set(row), {"id", "displayName", "username"})
        for token in (other, family):
            with self.assertRaises(PermissionError):
                self.store.handover_recipients(token)
        for not_eligible in (sender_account, other_account, family_account, disabled, pending):
            with self.assertRaises((ValueError, PermissionError)):
                self.submit(sender, not_eligible)
        self.execute(
            self.owner, "access.update", id=receiver["id"], permissions=["shifts"]
        )
        self.assertNotIn(
            receiver["id"],
            {r["id"] for r in self.store.handover_recipients(sender)["recipients"]},
        )
        with self.assertRaises((ValueError, PermissionError)):
            self.submit(sender, receiver)

    def test_only_assigned_account_can_acknowledge_even_when_names_match(self):
        sender, outgoing = self.account("sender", "care", name="交班人员")
        receiver, incoming = self.account("receiver", "care")
        other, _ = self.account("namesake", "care")
        with self.assertRaises(ValueError):
            self.submit(sender, incoming, senderId=self.owner_account["id"])
        row = self.submit(sender, incoming)
        self.assertEqual(
            (row["senderId"], row["senderName"]),
            (outgoing["id"], outgoing["displayName"]),
        )
        self.assertEqual(
            (row["assigneeId"], row["assignee"]),
            (incoming["id"], incoming["displayName"]),
        )
        self.assertEqual(row["status"], "待签收")
        self.assertEqual(datetime.fromisoformat(row["createdAt"]), self.instant)
        for token in (self.owner, sender, other):
            with self.assertRaises(PermissionError):
                self.execute(token, "care.acceptHandover", handoverId=row["id"])
        with self.assertRaises(ValueError):
            self.execute(
                receiver,
                "care.acceptHandover",
                handoverId=row["id"],
                acceptedById=self.owner_account["id"],
            )
        self.execute(
            self.owner, "access.update", id=incoming["id"], permissions=["shifts"]
        )
        with self.assertRaises(PermissionError):
            self.execute(receiver, "care.acceptHandover", handoverId=row["id"])
        self.execute(
            self.owner,
            "access.update",
            id=incoming["id"],
            permissions=["care"],
            enabled=False,
        )
        with self.assertRaises(SignedOut):
            self.store.execute(
                "care.acceptHandover",
                {"handoverId": row["id"]},
                self.store.version(self.owner)["revision"],
                receiver,
            )
        self.execute(
            self.owner,
            "access.update",
            id=incoming["id"],
            enabled=True,
            displayName="接班人新姓名",
        )
        receiver, _ = self.store.login("receiver", self.password)
        self.instant += timedelta(hours=2)
        self.execute(
            receiver, "care.acceptHandover", handoverId=row["id"], note="已查看未完成项"
        )
        self.store = Store(self.path, now=lambda: self.instant)
        signed = self.store.snapshot(receiver)["data"]["handovers"][-1]
        self.assertEqual(signed["status"], "已签收")
        self.assertEqual(signed["assignee"], incoming["displayName"])
        self.assertEqual(
            (signed["acceptedById"], signed["acceptedByName"]),
            (incoming["id"], "接班人新姓名"),
        )
        self.assertEqual(datetime.fromisoformat(signed["acceptedAt"]), self.instant)
        self.assertEqual(signed["receiptNote"], "已查看未完成项")
        with self.assertRaises(ValueError):
            self.execute(receiver, "care.acceptHandover", handoverId=row["id"])
        with self.assertRaises(ValueError):
            self.execute(
                sender, "care.withdrawHandover", handoverId=row["id"], reason="误选"
            )
        expected_room = activity.for_person(
            self.store.snapshot(self.owner)["data"], self.resident
        )["room"]
        self.assertTrue(expected_room)
        logs = self.store.activity(self.owner, room=expected_room)["rows"]
        self.assertEqual(
            [(r["action"], r["actorId"], r["residentId"]) for r in logs],
            [
                ("care.acceptHandover", incoming["id"], self.resident),
                ("care.handover", outgoing["id"], self.resident),
            ],
        )

    def test_concurrent_receipt_changes_revision_and_audit_only_once(self):
        receiver, account = self.account("double-receipt", "care")
        second, _ = self.store.login(account["username"], self.password)
        row = self.submit(self.owner, account)
        revision = self.store.version(receiver)["revision"]
        gate = Barrier(2)

        def sign(token):
            gate.wait()
            try:
                self.store.execute(
                    "care.acceptHandover", {"handoverId": row["id"]}, revision, token
                )
            except Conflict:
                return "conflict"
            return "accepted"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(sign, (receiver, second)))
        self.assertCountEqual(outcomes, ["accepted", "conflict"])
        self.assertEqual(self.store.version(receiver)["revision"], revision + 1)
        audit = self.store.activity(self.owner, actor=account["id"])["rows"]
        self.assertEqual([r["action"] for r in audit], ["care.acceptHandover"])

    def test_old_unbound_records_stay_historical_even_with_matching_employee(self):
        receiver, account = self.account("legacy-namesake", "care", name="文字接班人")
        self.execute(
            self.owner,
            "care.handover",
            assignee=account["displayName"],
            residentId=self.resident,
            note="旧格式交接",
        )
        records = self.store.snapshot(receiver)["data"]["handovers"]
        self.assertGreaterEqual(len(records), 2)
        for row in (records[0], records[-1]):
            self.assertEqual(row["status"], "历史记录")
            self.assertFalse(row.get("assigneeId"))
            self.assertNotIn("体征", row["summary"])
            with self.assertRaises((ValueError, PermissionError)):
                self.execute(receiver, "care.acceptHandover", handoverId=row["id"])
            with self.assertRaises(ValueError):
                self.execute(
                    self.owner,
                    "care.withdrawHandover",
                    handoverId=row["id"],
                    reason="误选",
                )

    def test_withdrawn_handover_stays_on_file_and_sender_can_choose_another_account(
        self,
    ):
        sender, outgoing = self.account("outgoing-withdraw", "care")
        receiver, incoming = self.account("incoming-withdraw", "care")
        _, replacement = self.account("substitute", "care")
        row = self.submit(sender, incoming)
        action = "care.withdrawHandover"
        why = {"handoverId": row["id"], "reason": "实际接班人调整"}
        for wrong_actor in (self.owner, receiver):
            with self.assertRaises(PermissionError):
                self.execute(wrong_actor, action, **why)
        with self.assertRaises(ValueError):
            self.execute(sender, action, handoverId=row["id"], reason=" ")
        with self.assertRaises(ValueError):
            self.execute(sender, action, **why, withdrawnById=incoming["id"])
        self.execute(
            self.owner, "access.update", id=outgoing["id"], permissions=["shifts"]
        )
        with self.assertRaises(PermissionError):
            self.execute(sender, action, **why)
        self.execute(
            self.owner, "access.update", id=outgoing["id"], permissions=["care"]
        )
        self.execute(self.owner, "access.update", id=incoming["id"], enabled=False)
        self.instant += timedelta(minutes=10)
        self.execute(sender, action, **why)
        closed = self.store.snapshot(sender)["data"]["handovers"][-1]
        self.assertEqual(closed["status"], "已撤回")
        self.assertEqual(
            (closed["withdrawnById"], closed["withdrawnByName"]),
            (outgoing["id"], outgoing["displayName"]),
        )
        self.assertEqual(closed["withdrawReason"], why["reason"])
        self.assertEqual(datetime.fromisoformat(closed["withdrawnAt"]), self.instant)
        for field in ("assigneeId", "snapshot", "createdAt"):
            self.assertEqual(closed[field], row[field])
        with self.assertRaises(ValueError):
            self.execute(sender, action, **why)
        self.execute(self.owner, "access.update", id=incoming["id"], enabled=True)
        receiver, _ = self.store.login("incoming-withdraw", self.password)
        with self.assertRaises(ValueError):
            self.execute(receiver, "care.acceptHandover", handoverId=row["id"])
        new = self.submit(sender, replacement)
        self.assertNotEqual(new["id"], row["id"])
        self.assertEqual(new["status"], "待签收")
        room = activity.for_person(self.store.snapshot(sender)["data"], self.resident)[
            "room"
        ]
        logs = self.store.activity(self.owner, actor=outgoing["id"], room=room)["rows"]
        self.assertEqual(
            [r["action"] for r in logs], ["care.handover", action, "care.handover"]
        )

    def test_withdrawal_racing_with_receipt_creates_only_one_terminal_action(self):
        receiver, account = self.account("concurrent-closing", "care")
        row = self.submit(self.owner, account)
        revision = self.store.version(receiver)["revision"]
        gate = Barrier(2)
        accept = "care.acceptHandover"
        withdraw = "care.withdrawHandover"

        def submit(args):
            token, action, extra = args
            gate.wait(timeout=10)
            try:
                self.store.execute(
                    action, {"handoverId": row["id"], **extra}, revision, token
                )
                return action
            except Conflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    submit,
                    [
                        (self.owner, withdraw, {"reason": "换班"}),
                        (receiver, accept, {}),
                    ],
                )
            )
        self.assertEqual(results.count("conflict"), 1)
        won = next(result for result in results if result != "conflict")
        closed = self.store.snapshot(receiver)["data"]["handovers"][-1]
        self.assertEqual(closed["status"], "已撤回" if won == withdraw else "已签收")
        self.assertEqual(self.store.version(receiver)["revision"], revision + 1)
        audit = self.store.activity(self.owner)["rows"]
        self.assertEqual(
            [r["action"] for r in audit if r["action"] in {accept, withdraw}], [won]
        )

    def test_new_snapshot_freezes_pending_and_overdue_with_clinical_counts_by_grant(
        self,
    ):
        clinical_token, nurse = self.account("nursing", "care", "clinical")
        care_token, aide = self.account("careonly", "care")
        self.execute(
            self.owner,
            "care.addTask",
            residentId=self.resident,
            title="前一班待办",
            assignee="护理组",
        )
        self.instant += timedelta(days=1)
        self.execute(
            self.owner,
            "care.addTask",
            residentId=self.resident,
            title="今日待办",
            assignee="护理组",
        )
        self.execute(
            self.owner,
            "care.vital",
            residentId=self.resident,
            metric="观测项目",
            value="已观测",
            abnormal=True,
        )
        data = self.store.snapshot(self.owner)["data"]
        tasks = [
            t
            for t in data["tasks"]
            if t["residentId"] == self.resident and t["status"] == "待执行"
        ]
        today = self.instant.date().isoformat()
        alerts = sum(
            v["residentId"] == self.resident and v["status"] == "待复核"
            for v in data["vitals"]
        )
        row = self.submit(self.owner, nurse)
        counts = row["snapshot"]
        self.assertEqual(counts["pendingToday"], 1)
        self.assertEqual(counts["overdue"], sum(t["date"] < today for t in tasks))
        self.assertGreaterEqual(counts["overdue"], 1)
        self.assertEqual(counts["openVitals"], alerts)
        self.assertGreaterEqual(alerts, 1)
        today_task = next(t for t in tasks if t["date"] == today)
        self.execute(self.owner, "care.completeTask", taskId=today_task["id"])
        self.assertEqual(
            self.store.snapshot(clinical_token)["data"]["handovers"][-1]["snapshot"],
            counts,
        )
        care_visible = self.store.snapshot(care_token)["data"]["handovers"][-1]
        self.assertNotIn("openVitals", care_visible["snapshot"])
        self.assertNotIn("体征", care_visible["summary"])
        self.assertNotIn("openVitals", self.submit(self.owner, aide)["snapshot"])
        self.assertNotIn("openVitals", self.submit(care_token, nurse)["snapshot"])

    def test_editable_preview_matches_today_completed_overdue_and_resists_scope_changes(
        self,
    ):
        outgoing, actor = self.account("out-qa", "care", name="交班甲")
        incoming, receiver = self.account("in-qa", "care", name="接班乙")
        other, third = self.account("third-qa", "care", name="旁班丙")
        finance, _ = self.account("fin-qa", "finance")

        def add(title):
            self.execute(
                self.owner,
                "care.addTask",
                residentId=self.resident,
                title=title,
                assignee=actor["username"],
                kind="自定义临床内容",
                note="内部医学内容，只限原记录",
            )

        add("病史密文")
        add("午餐陪护")
        self.instant += timedelta(days=1)
        add("晚间巡房")
        task = next(
            t
            for t in self.store.snapshot(outgoing)["data"]["tasks"]
            if t["title"] == "病史密文"
        )
        self.execute(
            outgoing, "care.completeTask", taskId=task["id"], operatorId=third["id"]
        )
        before = self.store.version(outgoing)["revision"]
        preview = self.store.handover_draft(outgoing, receiver["id"])
        self.assertEqual(self.store.version(outgoing)["revision"], before)
        self.assertEqual(
            preview["snapshot"], dict(completedToday=1, pendingToday=1, overdue=1)
        )
        self.assertIn("晚间巡房", preview["note"])
        self.assertIn("午餐陪护", preview["note"])
        for secret in ("病史密文", "内部医学", "自定义临床内容"):
            self.assertNotIn(secret, preview["note"])
        for token in (finance,):
            with self.assertRaises(PermissionError):
                self.store.handover_draft(token, receiver["id"])
        fields = dict(
            assigneeId=receiver["id"],
            residentId="",
            note="交班甲已核对。" + preview["note"],
            draftStamp=preview["stamp"],
        )
        for key, val in (("assigneeId", third["id"]), ("residentId", self.resident)):
            with self.assertRaises(ValueError):
                self.execute(outgoing, "care.handover", **{**fields, key: val})
        self.execute(outgoing, "care.handover", **fields)
        received = self.store.snapshot(incoming)["data"]["handovers"][-1]
        self.assertEqual(
            (received["draftScope"], received["snapshot"], received["note"]),
            ("personal", preview["snapshot"], fields["note"]),
        )
        self.assertNotIn(
            received["id"],
            [r["id"] for r in self.store.snapshot(other)["data"]["handovers"]],
        )
        self.execute(incoming, "care.acceptHandover", handoverId=received["id"])
        self.assertEqual(
            self.store.snapshot(outgoing)["data"]["handovers"][-1]["status"], "已签收"
        )
        add("交班前巡访")
        with self.assertRaises(ValueError):
            self.execute(outgoing, "care.handover", **fields)

    def test_preview_and_send_check_both_live_resident_regions(self):
        sender, _ = self.account("shift-limited", "care")
        _, receiver = self.account("limit-receiver", "care")
        _, target = self.account("empty-area", "care")
        self.store.facility_policy = lambda db, u: (
            {"roomIds": []} if u["id"] == target["id"] else {}
        )
        r = self.store.handover_draft(sender, receiver["id"], self.resident)
        with self.assertRaises(PermissionError):
            self.store.handover_draft(sender, target["id"], self.resident)
        self.store.facility_policy = lambda db, u: (
            {"roomIds": []} if u["id"] == receiver["id"] else {}
        )
        with self.assertRaises(PermissionError):
            self.execute(
                sender,
                "care.handover",
                assigneeId=receiver["id"],
                residentId=self.resident,
                draftStamp=r["stamp"],
                note=r["note"],
            )
