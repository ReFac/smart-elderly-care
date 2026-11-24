"""Automatic payment reminders and deposit allocations are scoped and replay safe."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from platform_core import portal
from platform_core.agents.revenue import overview
from platform_core.operations import admission_finance, billing_lifecycle
from platform_core.store import Store, encode


class BillingLifecycleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.day("2026-11-22")
        self.store = Store(
            Path(temp.name) / "billing.db",
            initial_data="empty",
            now=lambda: self.now,
            initial_owner_password="billing-fixture",
        )
        self.resident = {
            "id": "person-a",
            "name": "测试长者",
            "status": "在住",
            "stayType": "formal",
            "admittedAt": "2026-10-25",
            "billingDay": 25,
            "admissionTerms": admission_finance.terms({"securityMode": "overdue"}),
            "admissionPayment": {"securityBillId": "security"},
        }

    def day(self, value):
        self.now = datetime.fromisoformat(value).replace(
            hour=8, tzinfo=billing_lifecycle.LOCAL
        )

    def bill(
        self, id_, *, day="2026-11-25", amount=100, paid=0, kind="monthly", person=None
    ):
        return {
            "id": id_,
            "residentId": person or self.resident["id"],
            "billingDate": day,
            "amount": amount,
            "paid": paid,
            "balance": amount - paid,
            "month": day[:7],
            "kind": kind,
            "status": "已结清" if paid == amount else "待缴费",
        }

    def seed(self, bills, residents=None):
        with closing(self.store.connect()) as db, db:
            state = json.loads(
                db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
            )
            state.update(residents=residents or [self.resident], bills=bills)
            db.execute("UPDATE workspace SET data=? WHERE id=1", (encode(state),))

    def state(self):
        with closing(self.store.connect()) as db:
            row = db.execute(
                "SELECT revision,data FROM workspace WHERE id=1"
            ).fetchone()
        return row["revision"], json.loads(row["data"])

    def tick(self):
        return billing_lifecycle.tick(self.store)

    def test_deposit_waits_for_expiry_or_next_day_withdrawal(self):
        self.resident["endDate"] = "2026-11-25"
        self.seed(
            [
                self.bill("monthly"),
                self.bill("security", kind="security", amount=150, paid=150),
                self.bill("trial", kind="trial"),
            ]
        )
        self.assertEqual(self.tick(), 0)
        self.assertEqual(self.tick(), 0)
        self.day("2026-11-24")
        self.assertEqual(self.tick(), 0)
        self.day("2026-11-25")
        self.assertEqual(self.tick(), 1)
        self.assertEqual(self.state()[1]["payments"], [])
        self.day("2026-11-26")
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(lambda _: self.tick(), (0, 1))), [0, 2])
        revision, data = self.state()
        self.assertEqual(revision, 2)
        self.assertEqual(
            [(n["kind"], n["billingDate"], n["date"]) for n in data["billingNotices"]],
            [
                ("contractExpired", "2026-11-25", "2026-11-25"),
                ("security", "2026-11-25", "2026-11-26"),
            ],
        )
        self.assertEqual(
            [
                (p["billId"], p["amount"], p["securityBillId"], p["method"])
                for p in data["payments"]
            ],
            [("monthly", 100, "security", "押金冲抵")],
        )
        self.assertEqual([bill["balance"] for bill in data["bills"]], [0, 0, 100])
        self.assertEqual(overview(data, "2026-11-26")["todayGross"], 0)
        with closing(self.store.connect()) as db:
            audited = db.execute(
                """SELECT a.residentId,h.changes FROM audit a JOIN history_commits h USING(revision)
                   WHERE a.action=? ORDER BY a.revision""",
                (billing_lifecycle.ACTION,),
            ).fetchall()
        self.assertEqual([row["residentId"] for row in audited], ["person-a"] * 2)
        self.assertEqual(
            {row["collection"] for row in json.loads(audited[-1]["changes"])},
            {"billingNotices", "bills", "payments"},
        )

    def test_outage_catchup_pays_earliest_month_and_never_newer_or_ineligible_bill(
        self,
    ):
        other = {
            **self.resident,
            "id": "person-b",
            "admissionTerms": admission_finance.terms({"reminderDays": 0, "depositMonths": 0}),
        }
        trial = {**self.resident, "id": "person-trial", "stayType": "trial"}
        discharged = {**self.resident, "id": "person-discharged", "status": "已退住"}
        self.seed(
            [
                self.bill("future", day="2026-12-25"),
                self.bill("new"),
                self.bill("old", day="2026-10-25"),
                self.bill("security", kind="security", amount=120, paid=120),
                self.bill("other", person=other["id"]),
                self.bill("trial", person=trial["id"]),
                self.bill("discharged", person=discharged["id"]),
            ],
            [self.resident, other, trial, discharged],
        )
        self.day("2026-11-27")
        self.assertEqual(self.tick(), 5)
        self.assertEqual(self.tick(), 0)
        _, data = self.state()
        due = [n for n in data["billingNotices"] if n["kind"] == "due"]
        self.assertEqual({n["billId"] for n in due}, {"other"})
        self.assertEqual({n["date"] for n in due}, {"2026-11-27"})
        self.assertEqual(
            {p["billId"]: p["amount"] for p in data["payments"]},
            {"old": 100, "new": 20},
        )
        self.assertEqual({b["id"]: b["balance"] for b in data["bills"]}["new"], 80)

    def test_cross_resident_deposit_is_not_used_or_disclosed_and_failed_transaction_retries(
        self,
    ):
        self.resident["endDate"] = "2026-11-26"
        other = {"id": "person-b", "name": "外部档案", "status": "未入住"}
        valid = {
            **self.resident,
            "id": "person-c",
            "admissionPayment": {"securityBillId": "valid-deposit"},
            "endDate": "",
        }
        self.seed(
            [
                self.bill("monthly"),
                self.bill("security", person=other["id"], kind="security", paid=100),
                self.bill("valid-monthly", person=valid["id"]),
                self.bill(
                    "valid-deposit", person=valid["id"], kind="security", paid=100
                ),
            ],
            [self.resident, valid, other],
        )
        self.day("2026-11-26")
        actual = admission_finance.use_security

        def interrupted(state, resident, bill, today):
            credit = actual(state, resident, bill, today)
            if credit:
                raise RuntimeError("temporary storage failure")
            return credit

        with mock.patch.object(
            admission_finance, "use_security", side_effect=interrupted
        ):
            with self.assertRaises(RuntimeError):
                self.tick()
        revision, rolled_back = self.state()
        self.assertEqual(revision, 0)
        self.assertEqual(rolled_back.get("billingNotices", []), [])
        self.assertEqual(rolled_back["payments"], [])
        self.assertEqual(self.tick(), 4)
        _, data = self.state()
        issues = [n for n in data["billingNotices"] if n["kind"] == "securityIssue"]
        self.assertEqual(
            [(n["residentId"], n["billId"]) for n in issues], [("person-a", "monthly")]
        )
        self.assertEqual([p["residentId"] for p in data["payments"]], [valid["id"]])

        def visible(user, resident_ids):
            projected = {"residents": [{"id": id_} for id_ in resident_ids]}
            billing_lifecycle.project(data, projected, user, "2026-11-26")
            return projected["billingNotices"]

        family = {
            "kind": "family",
            "residentId": self.resident["id"],
            "portalScopes": ["billingNotices"],
        }
        projected = visible(family, [self.resident["id"], "person-c"])
        self.assertEqual([notice["kind"] for notice in projected], ["contractExpired"])
        self.assertEqual(set(projected[0]), set(billing_lifecycle.FAMILY_FIELDS))
        self.assertEqual(
            visible({**family, "portalScopes": []}, [self.resident["id"]]), []
        )
        self.assertEqual(
            visible({**family, "residentId": other["id"]}, [other["id"]]), []
        )
        self.assertEqual(
            visible({"kind": "staff", "permissions": ["care"]}, [self.resident["id"]]),
            [],
        )
        finance = visible(
            {"kind": "staff", "permissions": ["finance"]}, [self.resident["id"]]
        )
        self.assertEqual({n["kind"] for n in finance}, {"contractExpired", "securityIssue"})
        owner = visible({"kind": "owner"}, [self.resident["id"], valid["id"]])
        self.assertEqual(
            {n["residentId"] for n in owner}, {self.resident["id"], valid["id"]}
        )
        self.assertEqual(
            next(n["amount"] for n in owner if n["kind"] == "security"), 100
        )
        self.assertEqual(
            portal.scopes({"portalScopes": ["billingNotices"]}, "family"),
            ["billingNotices"],
        )

    def test_reminder_created_before_invoice_links_after_issue_without_replacing_history(
        self,
    ):
        self.resident.update(admissionTerms=admission_finance.terms({"depositMonths": 0}), admissionPayment={})
        self.seed([])
        self.day("2026-11-25")
        self.assertEqual(self.tick(), 1)
        _, state = self.state()
        advance = state["billingNotices"][0]
        self.assertNotIn("billId", advance)
        posted = self.bill("new-monthly")
        data = {"residents": [self.resident], "bills": [posted]}
        billing_lifecycle.project(state, data, {"kind": "owner"}, "2026-11-25")
        self.assertEqual(data["billingNotices"][0]["billId"], posted["id"])
        self.assertNotIn("billId", state["billingNotices"][0])
