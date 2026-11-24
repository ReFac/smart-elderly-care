from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from platform_core import visitor_access
from platform_core.store import SignedOut, Store


class VisitorAccessTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name) / "tour.sqlite3", initial_owner_password="visitor-test-only")

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
