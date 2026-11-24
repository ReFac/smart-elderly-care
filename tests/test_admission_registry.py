from contextlib import closing
from datetime import datetime, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from platform_core import campus_access, facility
from platform_core.agents import runtime
from platform_core.agents.contracts import SPECIALISTS
from platform_core.care import archive_retention
from platform_core.store import Store, TIMEZONE, Conflict


class AdmissionRegistryTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.now = datetime(2026, 11, 24, 10, tzinfo=TIMEZONE)
        self.path = Path(temp.name) / "dossiers.sqlite3"
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": "fixture-register-only"}):
            self.store = Store(self.path, lambda: self.now)
        self.token, _ = self.store.login("owner", "fixture-register-only")

    def current(self):
        return self.store.snapshot(self.token)["data"]

    def write(self, action, **p):
        return self.store.execute(
            action, p, self.store.version(self.token)["revision"], self.token
        )

    def register(self, name="测试同名长者", **p):
        self.write("care.register", name=name, **p)
        return self.current()["residents"][-1]["id"]

    def test_two_stays_and_duplicate_names_are_distinct(self):
        bed, second = [b for b in self.current()["beds"] if b["status"] == "空闲"][:2]
        with self.assertRaises(ValueError):
            self.write("care.admit", name="凭空入住", bedId=bed["id"])
        old = self.register(kind="archive")
        with self.assertRaisesRegex(ValueError, "同名"):
            self.register()
        pid = self.register(acknowledgeArchive=True)
        self.assertNotEqual(old, pid)
        for target in (old, pid):
            with self.assertRaises(ValueError):
                self.store.dossier_summary_draft(self.token, target)
            with self.assertRaises(ValueError):
                self.store.rounds.read(self.token, "/api/rounds/residents/" + target)
        with self.assertRaises(ValueError):
            self.write("care.admit", residentId=old, bedId=bed["id"])
        self.write("care.admit", residentId=pid, bedId=bed["id"])
        stale = self.store.version(self.token)["revision"]
        transfer = self.write("care.transfer", residentId=pid, bedId=second["id"])
        with self.assertRaises(Conflict):
            self.store.execute(
                "care.transfer",
                {"residentId": pid, "bedId": bed["id"]},
                stale,
                self.token,
            )
        data = self.current()
        beds = {b["id"]: b["residentId"] for b in data["beds"]}
        self.assertEqual((beds[bed["id"]], beds[second["id"]]), ("", pid))
        self.assertEqual(
            self.store.history_change(self.token, transfer["revision"])["residentId"],
            pid,
        )
        self.write("care.discharge", residentId=pid)
        with self.assertRaises(ValueError):
            self.write("dossier.profile", residentId=pid, name="改名")
        with self.assertRaises(ValueError):
            self.write("care.admit", residentId=pid, bedId=bed["id"])
        ids = [
            r["id"]
            for r in runtime.scoped_records(self.current(), SPECIALISTS[0], "")[
                "residents"
            ]
        ]
        self.assertNotIn(old, ids)
        self.assertNotIn(pid, ids)

    def test_365_day_boundary_and_evidence_preserved(self):
        pid = self.register()
        rev = self.write(
            "dossier.profile", residentId=pid, name="只读资料", birthDate="1950-01-12"
        )["revision"]
        self.write(
            "care.fileArchive", residentId=pid, archiveDate=self.now.date().isoformat()
        )
        self.assertFalse(self.store.history_change(self.token, rev)["undoable"])
        self.now += timedelta(days=364)
        self.token, _ = self.store.login("owner", "fixture-register-only")
        self.assertTrue(any(r["id"] == pid for r in self.current()["residents"]))
        self.now += timedelta(days=1)
        self.token, _ = self.store.login("owner", "fixture-register-only")
        before = self.store.version(self.token)["revision"]
        self.assertFalse(any(r["id"] == pid for r in self.current()["residents"]))
        archive_retention.maintain(self.store)
        with closing(self.store.connect()) as db:
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM archive_expirations WHERE resident=?", (pid,)
                ).fetchone()[0],
                1,
            )
            self.assertIsNone(
                db.execute(
                    "SELECT 1 FROM dossier_profiles WHERE resident_id=?", (pid,)
                ).fetchone()
            )
            row = next(
                r
                for r in json.loads(
                    db.execute("SELECT data FROM workspace").fetchone()[0]
                )["residents"]
                if r["id"] == pid
            )
            self.assertEqual((row["name"], row["status"]), ("已到期档案", "归档到期"))
            self.assertEqual(
                db.execute("SELECT revision FROM workspace").fetchone()[0], before + 1
            )

    def test_early_trial_conversion_keeps_financial_start_after_archive_expiry(self):
        from platform_core.operations.billing_cycles import monthly_start

        rid = self.register()
        bed = next(b["id"] for b in self.current()["beds"] if not b["residentId"])
        self.write("care.admit", residentId=rid, bedId=bed, stayType="trial", trialPrice=100)
        self.write("care.confirmStay", residentId=rid)
        self.now += timedelta(days=6)
        self.token, _ = self.store.login("owner", "fixture-register-only")
        self.write("care.discharge", residentId=rid)
        self.now += timedelta(days=365)
        archive_retention.maintain(self.store)
        with closing(self.store.connect()) as db:
            state = json.loads(db.execute("SELECT data FROM workspace").fetchone()[0])
        person = next(row for row in state["residents"] if row["id"] == rid)
        self.assertEqual(person["status"], "归档到期")
        self.assertEqual(monthly_start(person), "2026-11-26")

    def test_scoped_new_files_are_only_visible_to_the_registering_campus(self):
        self.write("facility.addCampus", name="第二分院")
        east = self.current()["campusOptions"][-1]["id"]
        self.write(
            "access.create",
            kind="staff",
            username="registry-employee",
            displayName="接待员工",
            role="自定义",
            permissions=["intake", "residents"],
            campusId=east,
            password="fixture-scope-only",
        )
        self.token, _ = self.store.login("registry-employee", "fixture-scope-only")
        local = self.register("本院档案")
        self.assertEqual([r["id"] for r in self.current()["residents"]], [local])
        with self.assertRaises(PermissionError):
            self.write("care.register", campusId=facility.HOME_CAMPUS, name="越权")
        with self.assertRaises(PermissionError):
            self.write("care.admit", residentId=local, bedId="b001")
        with closing(self.store.connect()) as db:
            state = json.loads(db.execute("SELECT data FROM workspace").fetchone()[0])
            user = self.store.actor(db, self.token)
            campus_access.require_resident(db, user, local, state)
            with self.assertRaises(PermissionError):
                campus_access.require_resident(
                    db,
                    {**user, "facilityScope": {"campusIds": [east], "roomIds": []}},
                    local,
                    state,
                )

    def test_unseen_expired_archive_on_encrypted_restore_leaves_only_evidence(self):
        from platform_core.backups import exchange
        from test_dossier import DOCUMENT, PNG
        from test_medical_visits import fixture_visit
        import base64

        from platform_core import secure_storage
        from io import BytesIO

        backup = self.store.backups
        backup.capture(wait=True)
        original = backup.status(self.token)["points"][0]["id"]
        donor_path = self.path.parent / "historical.sqlite3"
        secure_storage.restore_snapshot(
            backup.folder / (original + ".akbak"),
            donor_path,
            self.store.storage_key_file,
        )
        donor = Store(donor_path, lambda: self.now)
        token, _ = donor.login("owner", "fixture-register-only")

        def command(action, **payload):
            donor.execute(action, payload, donor.version(token)["revision"], token)

        command("care.register", name="还原旧档样本")
        pid = donor.snapshot(token)["data"]["residents"][-1]["id"]
        event_date = self.now.date().isoformat()
        visit_id = fixture_visit(donor, token, pid, event_date)
        command(
            "dossier.document",
            **{**DOCUMENT, "residentId": pid, "eventDate": event_date, "visitId": visit_id},
        )
        command(
            "care.fileArchive", residentId=pid, archiveDate=self.now.date().isoformat()
        )
        historical = donor.backups.request(token, "retention-point-fixture")["id"]
        saved = donor.backups.folder / (historical + ".akbak")
        for _ in range(4):
            donor.backups.capture(wait=True)
            if saved.is_file():
                break
        packet = saved.read_bytes()
        self.now += timedelta(days=365)
        self.token, _ = self.store.login("owner", "fixture-register-only")
        self.current()  # Primed today's day-check, with no such resident in the live roster.
        candidate = exchange.preview_file(
            backup, self.token, BytesIO(packet), len(packet)
        )
        point = exchange.confirm_import(backup, self.token, candidate["id"])["point"]
        view = exchange.preview_point(backup, self.token, point)
        self.assertFalse(view["blockers"])
        exchange.apply_point(
            backup,
            self.token,
            point,
            {
                "revision": view["currentRevision"],
                "confirmed": True,
                "approval": view["approval"],
            },
        )
        with closing(self.store.connect()) as db:
            self.assertTrue(
                db.execute(
                    "SELECT 1 FROM archive_expirations WHERE resident=?", (pid,)
                ).fetchone()
            )
            restored = next(
                r
                for r in json.loads(
                    db.execute("SELECT data FROM workspace").fetchone()[0]
                )["residents"]
                if r["id"] == pid
            )
            self.assertEqual(restored["status"], "归档到期")
            self.assertEqual(
                db.execute(
                    "SELECT original FROM dossier_documents WHERE resident_id=?", (pid,)
                ).fetchone()[0],
                base64.b64decode(PNG),
            )
        self.assertFalse(any(r["id"] == pid for r in self.current()["residents"]))

    def test_unverified_legacy_date_waits_for_source(self):
        pid = self.register(kind="archive")
        with closing(self.store.connect()) as db, db:
            state = json.loads(db.execute("SELECT data FROM workspace").fetchone()[0])
            old = next(r for r in state["residents"] if r["id"] == pid)
            old.pop("archiveUntil")
            old["dischargedAt"] = ""
            db.execute("UPDATE workspace SET data=?", (json.dumps(state),))
        self.now += timedelta(days=500)
        self.token, _ = self.store.login("owner", "fixture-register-only")
        self.assertTrue(any(r["id"] == pid for r in self.current()["residents"]))
        self.write("care.dateArchive", residentId=pid, archiveDate="2026-11-24")
        self.assertFalse(any(r["id"] == pid for r in self.current()["residents"]))
