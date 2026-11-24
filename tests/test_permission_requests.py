"""A countersigned grant can update just one long-term care resident's registration."""

from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zoneinfo import ZoneInfo

from platform_core import access, facility, history, permission_requests as requests
from platform_core.store import Store


class PermissionRequestsTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.now = datetime(2026, 11, 25, 9, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.password = "permission-test-account-password"
        self.store = Store(
            Path(folder.name) / "workspace.sqlite3",
            now=lambda: self.now,
            initial_owner_password=self.password,
        )
        self.owner, self.owner_account = self.store.login("owner", self.password)
        self.worker, self.worker_account = self.employee(
            "worker", ["residents", "care", "audit"]
        )
        self.reviewer, self.reviewer_account = self.employee(
            "reviewer", ["intake", "permissions.approve", "audit"]
        )
        self.outsider, self.outsider_account = self.employee(
            "observer", ["intake", "audit"]
        )
        self.name = "签署人张宁"
        self.run_as(
            self.owner,
            "access.setRealName",
            accountId=self.reviewer_account["id"],
            realName=self.name,
        )
        state = self.store.snapshot(self.owner)["data"]
        self.resident = state["residents"][0]
        self.other_resident = state["residents"][1]

    def run_as(self, token, action, **payload):
        return self.store.execute(
            action, payload, self.store.version(token)["revision"], token
        )

    def employee(self, login, permissions, **options):
        self.run_as(
            self.owner,
            "access.create",
            kind="staff",
            username=login,
            displayName="显示名" + login,
            role="自定义",
            permissions=permissions,
            password=self.password,
            **options,
        )
        return self.store.login(login, self.password)

    def queue(self, token):
        return requests.read(self.store, token)

    def submit(self, token=None, resident=None, reviewer=None):
        token = token or self.worker
        self.run_as(
            token,
            requests.CREATE,
            residentId=(resident or self.resident)["id"],
            approverId=(reviewer or self.reviewer_account)["id"],
            reason="补录登记资料",
        )
        return self.queue(token)["sent"][0]["id"]

    def decide(self, rid, *, token=None, **overrides):
        return self.run_as(
            token or self.reviewer,
            requests.REVIEW,
            **{
                "requestId": rid,
                "decision": "approve",
                "signature": self.name,
                "currentPassword": self.password,
                "note": "已核对原登记资料",
                **overrides,
            },
        )

    def test_named_signature_applies_one_registration_edit_to_one_resident(self):
        with self.assertRaises(PermissionError):
            self.run_as(
                self.worker,
                "dossier.profile",
                residentId=self.resident["id"],
                name="应由有权人员办理",
            )
        grant = self.submit()
        self.assertEqual(
            self.store.snapshot(self.reviewer)["data"]["pendingPermissionRequests"], 1
        )
        self.assertEqual(self.queue(self.outsider)["received"], [])
        self.assertFalse(self.queue(self.worker)["sent"][0]["canEdit"])
        with self.assertRaises(PermissionError):
            requests.read(self.store, self.worker, grant)
        with self.assertRaises(PermissionError):
            self.decide(grant, token=self.worker)
        with self.assertRaises(PermissionError):
            self.decide(grant, token=self.outsider)
        with self.assertRaises(ValueError):
            self.decide(grant, signature=self.reviewer_account["displayName"])
        with self.assertRaises(access.SignaturePasswordDenied):
            self.decide(grant, currentPassword="wrong-account-password")
        with closing(self.store.connect()) as db:
            failed = db.execute(
                "SELECT attempts FROM login_failures WHERE subject=?",
                (self.reviewer_account["id"],),
            ).fetchone()
            self.assertEqual(failed[0], 1)
        receipt = self.decide(grant)
        for viewer in (self.worker, self.outsider):
            self.assertFalse(
                any(
                    row["action"].startswith("permissionRequest.")
                    for row in self.store.activity(viewer)["rows"]
                )
            )
            with self.assertRaises(FileNotFoundError):
                history.detail(self.store, viewer, receipt["revision"])
        approved = self.queue(self.worker)["sent"][0]
        self.assertEqual(
            (approved["status"], approved["signature"], approved["canEdit"]),
            ("approved", self.name, True),
        )
        self.assertEqual(
            self.store.snapshot(self.reviewer)["data"]["pendingPermissionRequests"], 0
        )
        profile = requests.read(self.store, self.worker, grant)
        self.assertEqual(profile["resident"]["id"], self.resident["id"])
        self.assertNotIn("household", profile)
        with self.assertRaises(FileNotFoundError):
            requests.read(self.store, self.outsider, grant)
        with self.assertRaises(ValueError):
            self.run_as(
                self.worker,
                requests.EDIT,
                requestId=grant,
                residentId=self.other_resident["id"],
                name="测试",
            )
        with self.assertRaises(ValueError):
            self.run_as(
                self.worker,
                requests.EDIT,
                requestId=grant,
                name="测试",
                familyContact={},
            )
        with self.assertRaisesRegex(ValueError, "登记内容没有变化"):
            self.run_as(
                self.worker,
                requests.EDIT,
                requestId=grant,
                name=self.resident["name"],
                phone="",
                addressRegion={"codes": [], "detail": ""},
            )
        self.assertTrue(self.queue(self.worker)["sent"][0]["canEdit"])
        self.run_as(
            self.worker,
            requests.EDIT,
            requestId=grant,
            name="登记姓名已核对",
            address="示例城区测试地址",
        )
        self.assertEqual(self.queue(self.worker)["sent"][0]["status"], "used")
        with self.assertRaises(PermissionError):
            self.run_as(
                self.worker, requests.EDIT, requestId=grant, name="这次权限已经使用"
            )
        data = self.store.snapshot(self.owner)["data"]
        self.assertEqual(data["residents"][0]["name"], "登记姓名已核对")
        self.assertEqual(data["residents"][1]["name"], self.other_resident["name"])
        self.assertNotIn(
            "intake", self.store.snapshot(self.worker)["data"]["user"]["permissions"]
        )
        with closing(self.store.connect()) as db:
            evidence = db.execute(
                "SELECT decision_note,signature,signature_proof FROM permission_requests WHERE id=?",
                (grant,),
            ).fetchone()
            self.assertEqual(evidence[1], self.name)
            self.assertEqual(len(evidence[2]), 64)
            audit = db.execute(
                "SELECT changes FROM history_commits WHERE revision=?",
                (receipt["revision"],),
            ).fetchone()
            self.assertIn(self.name, audit[0])
            self.assertNotIn(self.password, audit[0])
            self.assertNotIn(evidence[2], audit[0])

    def test_scope_and_qualification_are_rechecked_for_access(self):
        self.run_as(
            self.owner, "facility.addCampus", name="跨院区权限测试", address="测试地址"
        )
        directory = self.store.facility_resource(self.owner, "directory")
        outside = next(
            r["id"] for r in directory["campuses"] if r["id"] != facility.HOME_CAMPUS
        )
        regional, _ = self.employee(
            "outside-care", ["intake", "residents"], campusId=outside
        )
        out_reviewer, out_account = self.employee(
            "outside-review",
            ["intake", "permissions.approve", "audit"],
            campusId=outside,
        )
        self.run_as(
            self.owner,
            "access.setRealName",
            accountId=out_account["id"],
            realName="分院审批人",
        )
        with self.assertRaises(ValueError):
            self.submit(regional, reviewer=out_account)
        with self.assertRaises(PermissionError):
            self.run_as(
                regional,
                "dossier.profile",
                residentId=self.resident["id"],
                name="无法修改",
            )
        grant = self.submit(regional)
        self.assertEqual(self.queue(regional)["sent"][0]["residentName"], "")
        with self.assertRaises(FileNotFoundError):
            self.decide(grant, token=out_reviewer, signature="分院审批人")
        receipt = self.decide(grant)
        self.assertFalse(
            any(
                row["action"].startswith("permissionRequest.")
                for row in self.store.activity(out_reviewer)["rows"]
            )
        )
        with self.assertRaises(FileNotFoundError):
            history.detail(self.store, out_reviewer, receipt["revision"])
        self.assertEqual(
            requests.read(self.store, regional, grant)["resident"]["id"],
            self.resident["id"],
        )
        self.assertFalse(self.store.snapshot(regional)["data"]["residents"])
        self.run_as(
            self.owner,
            "access.update",
            id=self.reviewer_account["id"],
            campusId=outside,
        )
        with self.assertRaises(PermissionError):
            requests.read(self.store, regional, grant)
        self.assertEqual(self.queue(regional)["sent"][0]["status"], "expired")
        self.assertFalse(self.queue(self.reviewer)["received"])

    def test_rejection_and_expiry_release_request_slot_without_granting_edit(self):
        original = self.submit()
        with self.assertRaises(ValueError):
            self.submit()
        self.decide(original, decision="reject", note="本次无须调整")
        self.assertEqual(self.queue(self.worker)["sent"][0]["status"], "rejected")
        with self.assertRaises(PermissionError):
            requests.read(self.store, self.worker, original)
        self.now += timedelta(seconds=1)
        replacement = self.submit()
        self.decide(replacement)
        self.now += timedelta(hours=24)
        self.assertEqual(self.queue(self.worker)["sent"][0]["status"], "expired")
        with self.assertRaises(PermissionError):
            requests.read(self.store, self.worker, replacement)
        pending = self.submit()
        self.now += timedelta(days=7)
        with self.assertRaises(ValueError):
            self.decide(pending)
        self.assertEqual(
            self.store.snapshot(self.reviewer)["data"]["pendingPermissionRequests"], 0
        )
