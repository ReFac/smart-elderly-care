import base64
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest

from platform_core import secure_storage, staff_employment
from platform_core.backups import exchange
from platform_core.store import Conflict, SignedOut, Store, TIMEZONE


class EmploymentTests(unittest.TestCase):
    password = "employment-tests-local"
    pdf = b"%PDF-1.7\nExample employee signed agreement\n%%EOF\n"

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(
            Path(folder.name) / "staff.db",
            lambda: datetime(2028, 2, 10, tzinfo=TIMEZONE),
            initial_owner_password=self.password,
        )
        self.owner, self.owner_user = self.store.login("owner", self.password)
        self.manager, self.lead = self.employee("manager", ["staff.manage", "care"])
        self.staff, self.target = self.employee("nurse-a", ["care"])
        self.other, self.colleague = self.employee("nurse-b", ["care"])
        self.rid = self.target["id"]
        self.payload = {
            "id": self.rid,
            "number": "staff-1",
            "signedOn": "2028-01-29",
            "startsOn": "2028-02-01",
            "endsOn": "",
            "mime": "application/pdf",
            "filename": "签署版.pdf",
            "imageBase64": base64.b64encode(self.pdf).decode(),
        }

    def cmd(self, token, action, payload):
        return self.store.execute(
            action, payload, self.store.version(token)["revision"], token
        )

    def employee(self, username, permissions):
        self.cmd(
            self.owner,
            "access.create",
            {
                "kind": "staff",
                "role": "自定义",
                "username": username,
                "displayName": username,
                "password": self.password,
                "permissions": permissions,
            },
        )
        return self.store.login(username, self.password)

    def test_encrypted_originals_append_versions_scoped_to_an_employee(self):
        rev = self.store.version(self.owner)["revision"]
        self.cmd(self.manager, "access.staffContract", self.payload)
        with self.assertRaises(Conflict):
            self.store.execute("access.staffContract", self.payload, rev, self.manager)
        self.cmd(
            self.owner, "access.staffContract", {**self.payload, "endsOn": "2028-07-17"}
        )
        own = staff_employment.read(self.store, self.staff, self.rid)
        self.assertFalse(own["canEdit"])
        self.assertTrue(
            staff_employment.read(self.store, self.manager, self.rid)["canEdit"]
        )
        self.assertEqual(
            [(c["version"], c["endsOn"]) for c in own["contracts"]],
            [(2, "2028-07-17"), (1, "")],
        )
        original_id = own["contracts"][-1]["id"]
        self.assertEqual(
            staff_employment.read(self.store, self.staff, self.rid, original_id),
            (self.pdf, "application/pdf"),
        )
        with self.assertRaises(PermissionError):
            self.cmd(self.staff, "access.staffContract", self.payload)
        with self.assertRaises(PermissionError):
            staff_employment.read(self.store, self.other, self.rid, original_id)
        with self.assertRaises(FileNotFoundError):
            staff_employment.read(
                self.store, self.manager, self.colleague["id"], original_id
            )
        with closing(self.store.connect()) as db:
            self.assertEqual(
                db.execute("SELECT count(*) FROM staff_contract_originals").fetchone()[
                    0
                ],
                1,
            )
        self.assertNotIn(self.pdf, self.store.path.read_bytes())
        self.assertNotIn("contracts", self.store.snapshot(self.other)["data"])
        self.assertFalse(
            staff_employment.read(self.store, self.manager, self.colleague["id"])[
                "contracts"
            ]
        )

    def test_require_valid_contract_and_authority_to_change_salary_day(self):
        for change in (
            {"endsOn": "2028-01-01"},
            {"filename": "../private.pdf"},
            {"imageBase64": "!"},
            {"imageBase64": base64.b64encode(b"not a PDF").decode()},
        ):
            with self.assertRaises(ValueError):
                self.cmd(
                    self.manager, "access.staffContract", {**self.payload, **change}
                )
        for token, target in (
            (self.staff, self.rid),
            (self.manager, self.lead["id"]),
            (self.manager, self.owner_user["id"]),
        ):
            with self.assertRaises(PermissionError):
                self.cmd(token, "access.staffPayday", {"id": target, "payday": 18})
        for day in (0, 32, 3.5, True):
            with self.assertRaises(ValueError):
                self.cmd(
                    self.owner, "access.staffPayday", {"id": self.rid, "payday": day}
                )
        self.cmd(self.manager, "access.staffPayday", {"id": self.rid, "payday": 31})
        profile = staff_employment.read(self.store, self.staff, self.rid)
        self.assertEqual((profile["payday"], profile["nextPayday"]), (31, "2028-02-29"))
        self.assertEqual(
            staff_employment.next_payday(date(2027, 2, 27), 31), "2027-02-28"
        )
        self.assertEqual(
            staff_employment.next_payday(date(2027, 12, 28), 26), "2028-01-26"
        )

    def test_target_scope_rechecked_for_metadata_original_and_changes(self):
        self.cmd(self.owner, "access.staffContract", self.payload)
        doc = staff_employment.read(self.store, self.staff, self.rid)["contracts"][0][
            "id"
        ]
        with closing(self.store.connect()) as db:
            campus_id = db.execute(
                "SELECT id FROM facility_campuses LIMIT 1"
            ).fetchone()[0]
        self.store.facility_policy = lambda db, actor: (
            {"campusIds": [campus_id]} if actor["id"] == self.lead["id"] else {}
        )
        for contract in (None, doc):
            with self.assertRaises(PermissionError):
                staff_employment.read(self.store, self.manager, self.rid, contract)
        with self.assertRaises(PermissionError):
            self.cmd(self.manager, "access.staffPayday", {"id": self.rid, "payday": 10})

    def test_disabled_employee_original_revoked_but_retained(self):
        self.cmd(self.manager, "access.staffContract", self.payload)
        doc = staff_employment.read(self.store, self.staff, self.rid)["contracts"][0][
            "id"
        ]
        self.cmd(self.manager, "access.update", {"id": self.rid, "enabled": False})
        with self.assertRaises(SignedOut):
            staff_employment.read(self.store, self.staff, self.rid, doc)
        self.assertEqual(
            staff_employment.read(self.store, self.manager, self.rid, doc)[0], self.pdf
        )

    def test_encrypted_snapshot_restores_payday_and_preserves_contract_originals(self):
        self.cmd(self.manager, "access.staffContract", self.payload)
        self.cmd(self.manager, "access.staffPayday", {"id": self.rid, "payday": 23})
        doc = staff_employment.read(self.store, self.staff, self.rid)["contracts"][0][
            "id"
        ]
        service = self.store.backups
        service.capture()
        point = service.status(self.owner)["points"][0]["id"]
        archive = service.folder / (point + ".akbak")
        self.assertNotIn(self.pdf, archive.read_bytes())
        restored = self.store.path.parent / "dr" / "restored.sqlite3"
        secure_storage.restore_snapshot(archive, restored, self.store.storage_key_file)
        isolated = Store(restored)
        employee = isolated.login("nurse-a", self.password)[0]
        self.assertEqual(
            staff_employment.read(isolated, employee, self.rid)["payday"], 23
        )
        self.assertEqual(
            staff_employment.read(isolated, employee, self.rid, doc)[0], self.pdf
        )
        self.cmd(self.owner, "access.staffPayday", {"id": self.rid, "payday": 5})
        view = exchange.preview_point(service, self.owner, point)
        self.assertEqual(view["blockers"], [])
        exchange.apply_point(
            service,
            self.owner,
            point,
            {
                "confirmed": True,
                "revision": view["currentRevision"],
                "approval": view["approval"],
                "comment": "工资日快照回归",
            },
        )
        self.assertEqual(
            staff_employment.read(self.store, self.staff, self.rid)["payday"], 23
        )
        self.assertEqual(
            staff_employment.read(self.store, self.staff, self.rid, doc)[0], self.pdf
        )
        self.cmd(
            self.manager, "access.staffContract", {**self.payload, "number": "more"}
        )
        self.assertIn(
            "员工合同留存版本",
            str(exchange.preview_point(service, self.owner, point)["blockers"]),
        )
