from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import manage_deployment
from platform_core import clinical_access
from platform_core.care import archive_retention
from platform_core.store import Store, TIMEZONE


class LicensedDeployment(TestCase):
    def test_protected_archive_survives_restart_and_audits_are_append_only(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "unit.sqlite3"
            day = datetime(2026, 4, 1, tzinfo=TIMEZONE)
            with patch.dict("os.environ", NH_INSTITUTION_PROFILE="licensed-medical"):
                store = Store(path, lambda:day, initial_data="empty", initial_owner_password="fixture-licensed-care")
                token, _ = store.login("owner", "fixture-licensed-care")
                store.execute("care.register", {"name":"虚构甲","kind":"archive"}, store.version(token)["revision"], token)
                person = store.snapshot(token)["data"]["residents"][0]
                clinical_access.receipt(store, token, "/api/residents/" + person["id"] + "/health-profile", 200, "127.0.0.1")
            day += timedelta(days=400)
            reopened = Store(path, lambda:day)
            self.assertTrue(reopened.clinical_archive_protection)
            token, _ = reopened.login("owner", "fixture-licensed-care")
            protected, = reopened.snapshot(token)["data"]["residents"]
            self.assertEqual((protected["name"], protected["status"]), ("虚构甲", "已退住"))
            archive_retention.maintain(reopened)
            with closing(reopened.connect()) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM clinical_archive_reviews").fetchone()[0],1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM clinical_reads").fetchone()[0],1)
                for sql in ("DELETE FROM clinical_reads", "UPDATE audit SET summary='changed'"):
                    with self.assertRaisesRegex(Exception, "append-only"):
                        db.execute(sql)
            result = manage_deployment.check(path, "licensed-medical", "https://care.example.org", full=True)
            self.assertEqual(result["encryptedDatabase"],"integrity-verified")

    def test_residential_demo_is_never_treated_as_licensed_medical(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "unit.sqlite3"
            Store(path, initial_data="demo")
            with patch.dict("os.environ", NH_INSTITUTION_PROFILE="licensed-medical"), self.assertRaisesRegex(ValueError,"演示库"):
                Store(path)

    def test_unmarked_legacy_institution_retains_service_records(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.db"
            store = Store(path, initial_data="empty")
            with closing(store.connect()) as db, db:
                db.execute("DELETE FROM workspace_installation")
            self.assertTrue(Store(path).retain_service_records)

    def test_formal_residential_service_agreement_survives_the_one_year_review(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "residential.db"
            now = datetime(2025, 2, 1, tzinfo=TIMEZONE)
            store = Store(path, lambda: now, initial_data="empty", initial_owner_password="formal-unit-password")
            owner, _ = store.login("owner","formal-unit-password")
            store.execute("care.register",{"name":"测试服务协议","kind":"archive"},store.version(owner)["revision"],owner)
            now += timedelta(days=370)
            archive_retention.maintain(store)
            self.assertEqual(store.snapshot(owner)["data"]["residents"][0]["name"],"测试服务协议")
            page = manage_deployment.review(path,"retention",0,10)
            self.assertEqual(len(page["entries"]),1)
            self.assertEqual(manage_deployment.review(path,"retention",page["after"],10)["entries"],[])
