"""Finance filing rules apply to the selected month, scope and exact document version."""

import base64
from contextlib import closing
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zoneinfo import ZoneInfo

from platform_core.operations import subsidies
from platform_core.store import Store
from test_dossier import PNG


class SubsidyFilingTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.pw = "subsidy-registry-test"
        self.store = Store(
            Path(folder.name) / "finance.sqlite3",
            initial_owner_password=self.pw,
            now=lambda: datetime(2026, 11, 25, 12, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        self.owner, _ = self.store.login("owner", self.pw)
        self.month = "2026-11"
        self.command("ops.subsidyRules", minimumDays=1, invoiceMonths=0)
        self.person, self.other = (r["residentId"] for r in self.read()["rows"][:2])

    def command(self, action, token=None, **payload):
        token = token or self.owner
        return self.store.execute(
            action, payload, self.store.version(token)["revision"], token
        )

    def read(self, token=None):
        return subsidies.read(self.store, token or self.owner, self.month)

    def upload(self, kind, filename):
        self.command(
            "ops.subsidyMaterial",
            month=self.month,
            residentId=self.person,
            kind=kind,
            fileName=filename,
            imageBase64=PNG,
        )
        row = next(r for r in self.read()["rows"] if r["residentId"] == self.person)
        return next(m["id"] for m in row["materials"] if m["kind"] == kind)

    def test_complete_batch_originals_immutable_and_rules_frozen(self):
        older = self.upload("idFront", "正面.png")
        self.assertEqual(self.upload("idFront", "正面.png"), older)
        latest = self.upload("idFront", "核对后正面.png")
        self.assertNotEqual(older, latest)
        self.upload("idBack", "反面.png")
        self.upload("household", "户口本.png")
        with self.assertRaises(ValueError):
            self.command(
                "ops.subsidyList",
                month=self.month,
                residentIds=[self.person, self.other],
            )
        self.assertFalse(any(r["claim"] for r in self.read()["rows"]))
        self.command("ops.subsidyList", month=self.month, residentIds=[self.person])
        self.command("ops.subsidyRules", minimumDays=365, invoiceMonths=12)
        signed = next(r for r in self.read()["rows"] if r["residentId"] == self.person)
        self.assertEqual(signed["rules"], {"minimumDays": 1, "invoiceMonths": 0})
        self.assertEqual(signed["claim"]["actor"], "Owner")
        self.assertIn(latest, [m["id"] for m in signed["materials"]])
        self.assertFalse(signed["missing"])
        self.assertEqual(
            subsidies.original(self.store, self.owner, older),
            (base64.b64decode(PNG), "image/png"),
        )
        with self.assertRaises(ValueError):
            self.command("ops.subsidyList", month=self.month, residentIds=[self.person])
        with (
            closing(self.store.connect()) as db,
            self.assertRaisesRegex(Exception, "不可改写"),
        ):
            db.execute("DELETE FROM subsidy_materials WHERE id=?", (older,))
        with self.assertRaisesRegex(ValueError, "未来"):
            subsidies.read(self.store, self.owner, "2026-12")

    def test_pending_resident_credentials_are_independent_of_monthly_subsidy_eligibility(self):
        self.command("care.register", name="登记样例")
        person = self.store.snapshot(self.owner)["data"]["residents"][-1]
        self.assertNotIn(person["id"], {r["residentId"] for r in self.read()["rows"]})
        self.command("access.create", kind="staff", role="自定义", displayName="接待样例", username="intake-example",
                     password=self.pw, permissions=["intake", "audit"])
        clerk, _ = self.store.login("intake-example", self.pw)
        number = "11010519491231002X"
        draft = dict(kind="idFront", residentId=person["id"], fileName=number+".png", imageBase64=PNG,
                     reviewedFields=dict(name=person["name"], birthDate="1949-12-31", idNumber=number))
        self.command("dossier.credential", clerk, **draft)
        visible = self.store.snapshot(clerk)["data"]
        self.assertNotIn(number, str(visible))
        record = next(row for row in visible["residents"] if row["id"] == person["id"])["credentialMaterials"]["idFront"]
        self.assertTrue(record["fields"]["idNumber"].endswith("002X"))
        self.assertEqual(subsidies.original(self.store, clerk, record["id"], credential=True)[0], base64.b64decode(PNG))
        with closing(self.store.connect()) as db:
            self.assertIn(number, db.execute("SELECT reviewed_fields FROM subsidy_materials WHERE id=?", (record["id"],)).fetchone()[0])
            self.assertNotIn(number, str([tuple(r) for r in db.execute("SELECT * FROM history_commits")]))
        with self.assertRaises(PermissionError):
            subsidies.original(self.store, clerk, record["id"])
        with self.assertRaisesRegex(ValueError, "姓名"):
            self.command("dossier.credential", clerk, **{**draft, "reviewedFields": {"name":"其他人"}})
        with self.assertRaisesRegex(ValueError, "证件号码"):
            self.command("dossier.credential", clerk, **{**draft, "reviewedFields": {"birthDate":"1999-12-31", "idNumber":number}})
        self.store.facility_policy = lambda db, user: {"campusIds": []} if user["username"] == "intake-example" else {}
        with self.assertRaises(PermissionError):
            self.command("dossier.credential", clerk, **draft)
        with self.assertRaises(PermissionError):
            subsidies.original(self.store, clerk, record["id"], credential=True)

    def test_scoped_and_non_finance_accounts_cannot_access_person_or_rules(self):
        doc = self.upload("household", "户口本.png")
        self.command("facility.addCampus", name="独立分院")
        new = self.store.facility_resource(self.owner, "directory")["campuses"][-1][
            "id"
        ]
        for username, rights, region in [
            ("filing-staff", ["finance"], new),
            ("care-staff", ["care"], None),
        ]:
            self.command(
                "access.create",
                kind="staff",
                role="自定义",
                displayName=username,
                username=username,
                password=self.pw,
                permissions=rights,
                **({"campusId": region} if region else {}),
            )
            token, _ = self.store.login(username, self.pw)
            if region:
                self.assertEqual(self.read(token)["rows"], [])
            else:
                with self.assertRaises(PermissionError):
                    self.read(token)
            with self.assertRaises(PermissionError):
                subsidies.original(self.store, token, doc)
            with self.assertRaises(PermissionError):
                self.command("ops.subsidyRules", token, minimumDays=5, invoiceMonths=1)

    def test_raw_audit_and_bulk_statement_respect_room_floor_building_and_campus(self):
        rows = self.read()["rows"]
        inside = rows[0]
        outside = next(r for r in rows if r["floorId"] != inside["floorId"])
        for r in (inside, outside):
            self.person = r["residentId"]
            for kind in ("idFront", "idBack", "household"):
                doc = self.upload(kind, kind + ".png")
            subsidies.original(self.store, self.owner, doc)
        self.command(
            "ops.subsidyList",
            month=self.month,
            residentIds=[inside["residentId"], outside["residentId"]],
        )
        self.command(
            "access.create",
            kind="staff",
            role="自定义",
            displayName="审计员",
            username="audit-cashier",
            password=self.pw,
            permissions=["audit", "finance"],
        )
        token, _ = self.store.login("audit-cashier", self.pw)
        for dimension in ("room", "floor", "building", "campus"):
            key = dimension + "Ids"
            allowed = (
                [inside[dimension + "Id"]] if dimension in ("room", "floor") else []
            )
            self.store.facility_policy = lambda db, user: (
                {key: allowed} if user["username"] == "audit-cashier" else {}
            )
            audit = [
                r
                for r in self.store.activity(token)["rows"]
                if r["action"].startswith("ops.")
            ]
            if allowed:
                self.assertTrue(
                    any(r["action"] == "ops.readSubsidyMaterial" for r in audit)
                )
                self.assertTrue(
                    any(r["action"] == "ops.subsidyMaterial" for r in audit)
                )
                self.assertTrue(
                    all(r["residentId"] == inside["residentId"] for r in audit)
                )
            else:
                self.assertEqual(audit, [])
            self.assertFalse(any(r["action"] == "ops.subsidyList" for r in audit))
        self.store.facility_policy = None
        self.assertTrue(
            any(
                r["action"] == "ops.subsidyList"
                for r in self.store.activity(token)["rows"]
            )
        )

    def test_required_invoices_are_exact_preceding_months_since_admission(self):
        from datetime import date

        self.assertEqual(
            subsidies.invoice_months(date(2026, 1, 1), 4, date(2025, 11, 30)),
            ["2025-11", "2025-12"],
        )
        self.assertEqual(
            subsidies.invoice_months(date(2026, 1, 1), 2, date(2026, 1, 1)), []
        )
