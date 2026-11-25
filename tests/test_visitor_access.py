from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from platform_core import portal, reset_links, visitor_access
from platform_core.store import SignedOut, Store


class VisitorAccessTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.now = datetime.now(timezone.utc)
        self.store = Store(Path(directory.name) / "tour.sqlite3", now=lambda: self.now,
                           initial_owner_password="visitor-test-only")

    def verify_phone(self, phone):
        assigned = []
        self.store.code_senders["sms"] = lambda _, code: assigned.append(code)
        challenge = visitor_access.request_code(self.store, {"phone": phone}, "fixture")
        return visitor_access.verify(self.store, {
            "challengeId": challenge["challengeId"], "code": assigned[0],
        }, "fixture")

    def owner_change(self, token, action, **payload):
        return self.store.execute(action, payload, self.store.version(token)["revision"], token)

    def test_public_branding_defaults_are_generic_and_preserve_configured_names(self):
        self.assertEqual(self.store.branding(), {
            "brandName": "医养管理平台", "institutionName": "养老机构",
        })
        token, _ = self.store.login("owner", "visitor-test-only")
        settings = {"brandName": "示例照护平台", "institutionName": "示例照护中心"}
        self.store.execute("access.settings", settings, self.store.version(token)["revision"], token)
        self.assertEqual(Store(self.store.path).branding(), settings)

    def test_demo_verification_is_one_time_and_not_a_workspace_session(self):
        phone = {"phone": "13900000000"}
        with self.assertRaisesRegex(ValueError, "暂未开通"):
            visitor_access.request_code(self.store, phone, "local")
        request = visitor_access.request_code(self.store, phone, "local", demo=True)
        payload = {"challengeId": request["challengeId"], "code": request["demoCode"]}
        with self.assertRaises(ValueError):
            visitor_access.verify(self.store, payload, "local", demo=False)
        session = visitor_access.verify(self.store, payload, "local", demo=True)
        self.assertTrue(visitor_access.status(self.store, session, None, demo=True)["signedIn"])
        self.assertFalse(visitor_access.status(self.store, session, None)["signedIn"])
        with self.assertRaises(SignedOut):
            self.store.snapshot(session)
        with self.assertRaises(ValueError):
            visitor_access.verify(self.store, payload, "local", demo=True)
        with closing(self.store.connect()) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM accounts").fetchone()[0], 1)

    def test_configured_sender_delivers_code_and_does_not_return_it(self):
        deliveries = []
        self.store.code_senders["sms"] = lambda phone, code: deliveries.append((phone, code))
        request = visitor_access.request_code(self.store, {"phone": "13900000001"}, "fixture")
        self.assertNotIn("demoCode", request)
        self.assertEqual(deliveries[0][0], "+8613900000001")
        token = visitor_access.verify(self.store, {
            "challengeId": request["challengeId"], "code": deliveries[0][1],
        }, "fixture")
        self.assertEqual(visitor_access.status(self.store, token, None)["maskedPhone"], "****0001")

    def test_existing_sms_account_is_selected_without_elevation_or_duplicate(self):
        owner, _ = self.store.login("owner", "visitor-test-only")
        self.owner_change(owner, "access.create", username="fixture-staff", displayName="现有员工",
                          kind="staff", role="护工", invitation={"channel": "sms", "destination": "13000000101"})
        first = visitor_access.status(self.store, self.verify_phone("13000000101"), None)
        self.assertTrue(first["signedIn"])
        self.assertNotIn("customerUsername", first)
        rows = self.store.snapshot(owner)["data"]["accounts"]
        self.assertEqual(len(rows), 2)
        staff = next(r for r in rows if r["kind"] == "staff")
        self.assertTrue(staff["activationPending"])
        with closing(self.store.connect()) as db:
            self.assertEqual(db.execute("SELECT verified FROM identity_contacts").fetchone()[0], 0)
            db.execute("UPDATE identity_contacts SET verified=1")
            db.commit()
        self.now += timedelta(minutes=2)
        existing = self.verify_phone("13000000101")
        self.assertNotIn("customerUsername", visitor_access.status(self.store, existing, None))
        self.assertEqual(len(self.store.snapshot(owner)["data"]["accounts"]), 2)
        with self.assertRaises(SignedOut):
            self.store.snapshot(existing)

    def test_registration_reuse_password_reset_and_revocation_stay_isolated(self):
        owner, _ = self.store.login("owner", "visitor-test-only")
        tour = self.verify_phone("13000000202")
        first = visitor_access.status(self.store, tour, None)
        self.assertTrue(first["signedIn"])
        self.now += timedelta(minutes=2)
        second = self.verify_phone("+8613000000202")
        self.assertEqual(first, visitor_access.status(self.store, second, None))
        rows = self.store.snapshot(owner)["data"]["accounts"]
        guest, = [row for row in rows if row["directoryGroup"] == "registered"]
        self.assertEqual((guest["role"], guest["username"]), (portal.CUSTOMER_ROLE, first["customerUsername"]))
        self.assertNotIn("13000000202", repr(rows))
        with self.assertRaises(SignedOut):
            self.store.snapshot(tour)
        issued = []
        self.store.reset_link_senders["sms"] = lambda _, link: issued.append(link)
        reset_links.send(self.store, owner, {"id": guest["id"]}, "https://care.invalid")
        password = "customer-isolation-fixture"
        reset_links.redeem(self.store, {"token": issued[0].split("#reset=")[1], "newPassword": password})
        token, actor = self.store.login(guest["username"], password)
        self.assertEqual(actor["routes"], ["tour", "faq", "account"])
        data = self.store.snapshot(token)["data"]
        self.assertEqual(data["allowedActions"], ["account.changePassword"])
        self.assertEqual(data["selfAccess"]["permissions"], [])
        self.assertEqual(data["residents"], [])
        self.assertNotIn("accounts", data)
        for operation in ("family.subscribe", "dossier.relative", "portal.feedback", "access.create"):
            with self.subTest(operation=operation), self.assertRaises(PermissionError):
                self.owner_change(token, operation)
        with self.assertRaises(PermissionError):
            self.store.portal_history(token, "careSchedule", 0, self.store.version(token)["revision"])
        with self.assertRaises(PermissionError):
            self.store.facility_resource(token, "search", q="沈月兰")
        with self.assertRaises(PermissionError):
            self.store.facility_resource(token, "tour")
        for field in ({"residentId": "r001"}, {"familyServices": True}, {"portalScopes": ["medication"]}):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.owner_change(owner, "access.update", id=guest["id"], **field)
        self.owner_change(owner, "access.update", id=guest["id"], enabled=False)
        self.assertFalse(visitor_access.status(self.store, tour, None)["signedIn"])
        with self.assertRaises(SignedOut):
            self.store.snapshot(token)
        self.now += timedelta(minutes=2)
        with self.assertRaises(ValueError):
            self.verify_phone("13000000202")
        self.owner_change(owner, "access.update", id=guest["id"], enabled=True)
        self.assertFalse(visitor_access.status(self.store, second, None)["signedIn"])
        reopened = Store(self.store.path)
        reopened_token, _ = reopened.login("owner", "visitor-test-only")
        self.assertEqual(len(reopened.snapshot(reopened_token)["data"]["accounts"]), 2)
