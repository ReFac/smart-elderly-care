from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from platform_core import protected_docs, secure_storage
from platform_core.store import Conflict, Store, TIMEZONE


class ProtectedDocumentsTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.password = "local-doc-test-owner"
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": self.password}):
            self.store = Store(
                self.root / "workspace.db",
                now=lambda: datetime(2026, 11, 20, tzinfo=TIMEZONE),
            )
        self.owner, _ = self.store.login("owner", self.password)

    def run_command(self, action, **data):
        self.store.execute(
            action, data, self.store.version(self.owner)["revision"], self.owner
        )

    def state(self):
        return self.store.snapshot(self.owner)["data"]

    def create_scoped_staff(self):
        self.run_command("facility.addCampus", name="测试外院", address="路4号")
        campus = self.store.facility_resource(self.owner, "directory")["campuses"][-1][
            "id"
        ]
        self.run_command(
            "access.create",
            kind="staff",
            role="自定义",
            username="external-nurse",
            displayName="演练护理员",
            password=self.password,
            permissions=["clinical", "reports"],
            campusId=campus,
        )
        return self.store.login("external-nurse", self.password)[0]

    def test_referral_requires_current_consent_and_branch_on_each_read(self):
        self.run_command(
            "care.refer",
            residentId="r001",
            kind="院外转介",
            destination="接收机构甲",
            summary="测试交接逐字保留",
        )
        rid = self.state()["referrals"][-1]["id"]

        def consent(decision):
            self.run_command(
                "care.referralConsent",
                referralId=rid,
                decision=decision,
                scope="姓名与交接摘要",
                basis="受权凭证甲",
            )

        consent("同意")
        eid = str(uuid4())
        self.run_command("care.exportReferral", referralId=rid, exportId=eid)
        selector = dict(kind="referral", id=rid, exportId=eid)
        packet = protected_docs.export(self.store, self.owner, selector)
        self.assertEqual(
            packet, protected_docs.export(self.store, self.owner, selector)
        )
        self.assertNotIn("测试交接".encode(), packet)
        self.assertNotIn("content", self.state()["referrals"][-1]["exports"][-1])
        recovered = protected_docs.open_package(self.store, self.owner, packet)["data"]
        self.assertEqual(recovered["summary"], "测试交接逐字保留")
        self.assertNotIn("allergies", recovered)
        external = self.create_scoped_staff()
        for fn, args in [
            (protected_docs.open_package, (packet,)),
            (protected_docs.export, (selector,)),
        ]:
            with self.assertRaises(PermissionError):
                fn(self.store, external, *args)
        for invalid in [
            packet[:-1],
            packet + b"x",
            packet[:65] + bytes((packet[65] ^ 4,)) + packet[66:],
        ]:
            with self.assertRaises(ValueError):
                protected_docs.open_package(self.store, self.owner, invalid)
        consent("撤回")
        with self.assertRaises(PermissionError):
            protected_docs.open_package(self.store, self.owner, packet)
        consent("同意")
        with self.assertRaises(PermissionError):
            protected_docs.open_package(self.store, self.owner, packet)

    def test_report_keeps_draft_at_export_and_freezes_submitted_version_across_restore(
        self,
    ):
        self.run_command("ops.report", month="2026-11")
        report = self.state()["reports"][0]
        spec = dict(kind="report", id=report["id"], version=1)
        with self.assertRaises(Conflict):
            protected_docs.export(self.store, self.owner, spec, 0)
        draft = protected_docs.export(
            self.store, self.owner, spec, self.store.version(self.owner)["revision"]
        )
        self.run_command(
            "ops.submitReport",
            reportId=report["id"],
            recipient="接收单位",
            submissionRef="TR-051",
        )
        sealed = protected_docs.export(self.store, self.owner, spec)
        through_api = self.store.report_version(self.owner, report["id"], 1)["dataset"]
        self.assertEqual(
            protected_docs.open_package(self.store, self.owner, sealed)["data"],
            through_api,
        )
        with closing(self.store.connect()) as db, db:
            state = json.loads(db.execute("SELECT data FROM workspace").fetchone()[0])
            state["reports"][0]["rows"] = []
            db.execute("UPDATE workspace SET data=?", (json.dumps(state),))
        self.assertEqual(
            protected_docs.open_package(self.store, self.owner, draft)["data"]["rows"],
            report["rows"],
        )
        self.assertEqual(protected_docs.export(self.store, self.owner, spec), sealed)
        external = self.create_scoped_staff()
        with self.assertRaises(PermissionError):
            protected_docs.open_package(self.store, external, sealed)
        with self.assertRaises(PermissionError):
            self.store.report_version(external, report["id"], 1)
        point = self.root / "documents.akbak"
        secure_storage.create_snapshot(self.store, point)
        copied = self.root / "restored.db"
        secure_storage.restore_snapshot(point, copied, self.store.storage_key_file)
        reopened = Store(copied)
        token, _ = reopened.login("owner", self.password)
        self.assertEqual(
            protected_docs.open_package(reopened, token, sealed)["data"], through_api
        )
