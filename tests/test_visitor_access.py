from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.message import Message
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from release_scope import international_only

from platform_core import portal, reset_links, secure_storage, visitor_access, wechat_tour
from platform_core.store import SignedOut, Store
from server import Handler


class VisitorAccessTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.now = datetime.now(timezone.utc)
        self.store = Store(Path(directory.name) / "tour.sqlite3", now=lambda: self.now,
                           initial_owner_password="visitor-test-only")

    def request_phone(self, phone):
        assigned = []
        self.store.code_senders["sms"] = lambda _, code: assigned.append(code)
        challenge = visitor_access.request_code(self.store, {"phone": phone}, "fixture")
        return {"challengeId": challenge["challengeId"], "code": assigned[0]}

    def verify_phone(self, phone):
        return visitor_access.verify(self.store, self.request_phone(phone), "fixture")

    def owner_change(self, token, action, **payload):
        return self.store.execute(action, payload, self.store.version(token)["revision"], token)

    def test_public_password_registration_creates_isolated_login_without_contact_or_lead(self):
        signup = {"username": "  Tour.Guest  ", "password": "my-own-secret-passphrase"}
        owner, _ = self.store.login("owner", "visitor-test-only")
        before = self.store.snapshot(owner)["data"].get("leadContacts", [])
        handler = Handler.__new__(Handler)
        handler.store, handler.client_address = self.store, ("127.0.0.1", 0)
        handler.path = "/api/public/visitor/register"
        handler.public_origin, handler.update_gate = "https://care.invalid", None
        body = json.dumps(signup).encode()
        handler.headers = Message()
        for name, value in {"Host": "care.invalid", "Origin": "https://care.invalid",
                            "Content-Type": "application/json", "Content-Length": str(len(body))}.items():
            handler.headers[name] = value
        handler.rfile = BytesIO(body)
        replies = []
        handler.send_json = lambda *args: replies.append(args)
        handler.dispatch("POST")
        status, reply, cookie = replies[0]
        self.assertEqual(status, 201)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("SameSite=Strict", cookie)
        token = cookie.split(";")[0].removeprefix("nh_session=")
        self.assertEqual(reply["user"]["username"], "tour.guest")
        self.assertEqual(reply["user"]["routes"], ["tour", "faq", "account"])
        self.assertTrue(visitor_access.status(self.store, None, token)["signedIn"])
        data = self.store.snapshot(token)["data"]
        self.assertEqual(data["residents"], [])
        self.assertNotIn("accounts", data)
        self.assertEqual(data["allowedActions"], ["account.changePassword"])
        with self.assertRaises(PermissionError):
            self.owner_change(token, "access.create")
        self.store.logout(token)
        with self.assertRaises(SignedOut):
            self.store.snapshot(token)
        _, guest = self.store.login("tour.guest", signup["password"])
        self.assertEqual(guest["id"], reply["user"]["id"])
        with closing(self.store.connect()) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM identity_contacts WHERE account_id=?",
                                        (guest["id"],)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM visitor_sessions").fetchone()[0], 0)
        self.assertEqual(self.store.snapshot(owner)["data"].get("leadContacts", []), before)

    def test_public_signup_rejects_privileged_fields_and_preserves_existing_identities(self):
        payload = {"username": "reserved.name", "password": "a-private-password"}
        for extra in ({"role": "Owner"}, {"residentId": "r001"}, {"phone": "13900000001"}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                visitor_access.register(self.store, {**payload, **extra}, "test")
        with self.assertRaises(ValueError):
            visitor_access.register(self.store, {**payload, "password": "short"}, "test")
        owner, _ = self.store.login("owner", "visitor-test-only")
        with self.assertRaises(PermissionError):
            visitor_access.register(self.store, payload, "test", owner)
        with self.assertRaisesRegex(ValueError, "已被使用"):
            visitor_access.register(self.store, {**payload, "username": "OWNER"}, "test")

        def try_register(password):
            try:
                _, user = visitor_access.register(self.store, {**payload, "password": password}, "test")
            except ValueError as error:
                self.assertIn("已被使用", str(error))
                return None
            return user["id"], password

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(try_register, ("private-phrase-one", "private-phrase-two")))
        winner, = [result for result in results if result]
        _, actual = self.store.login(payload["username"], winner[1])
        self.assertEqual(actual["id"], winner[0])
        with closing(self.store.connect()) as db:
            self.assertEqual(self.store.actor(db, owner)["kind"], "owner")
            self.assertEqual(db.execute("SELECT count(*) FROM accounts").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT count(*) FROM audit WHERE action='access.registerCustomer'").fetchone()[0], 1)

    def test_wechat_enquiry_requires_consent_and_validates_issuer_before_recording(self):
        config = {"NH_WECHAT_MINI_APP_ID": "wx-demo", "NH_WECHAT_MINI_APP_SECRET": "fixture-secret",
                  "NH_WECHAT_TOUR_LINK": "https://wxaurl.cn/Tour-test"}
        payload = {"code": "fixture-code", "consent": True}
        owner, _ = self.store.login("owner", "visitor-test-only")
        before = self.store.snapshot(owner)["data"].get("leadContacts", [])
        phone = {"purePhoneNumber": "13900003333", "countryCode": "86", "watermark": {"appid": "wx-demo"}}
        with patch.dict("os.environ", config), patch.object(wechat_tour, "_post") as call:
            self.assertEqual(visitor_access.status(self.store, None, None)["wechatContactLink"], config["NH_WECHAT_TOUR_LINK"])
            with self.assertRaises(ValueError):
                wechat_tour.receive(self.store, {**payload, "consent": False}, "peer")
            with self.assertRaises(ValueError):
                wechat_tour.receive(self.store, {**payload, "phone": "13900001111"}, "peer")
            call.assert_not_called()
            for invalid in ({"watermark": []}, {"watermark": {"appid": "other"}}, {"countryCode": "1"}):
                call.side_effect = [{"access_token": "test-token"}, {"phone_info": {**phone, **invalid}}]
                with self.assertRaises(ValueError):
                    wechat_tour.receive(self.store, payload, "peer")
            self.assertEqual(self.store.snapshot(owner)["data"].get("leadContacts", []), before)
            call.side_effect = [{"access_token": "test-token"}, {"phone_info": phone}]
            self.assertEqual(wechat_tour.receive(self.store, payload, "peer"), {"received": True})
            self.assertEqual(call.call_args.args,
                             ("wxa/business/getuserphonenumber?access_token=test-token", {"code": "fixture-code"}))
        leads = self.store.snapshot(owner)["data"]["leadContacts"]
        self.assertEqual(sum(row["phone"] == phone["purePhoneNumber"] and row["source"] == "consent" for row in leads), 1)
        with patch.dict("os.environ", {**config, "NH_WECHAT_TOUR_LINK": "https://other.invalid/"}):
            self.assertEqual(wechat_tour.contact_link(), "")

    @international_only
    def test_international_visitors_use_the_h5_callback_page(self):
        config = {"NH_WECHAT_TOUR_LINK":"https://wxaurl.cn/fixture", "NH_WECHAT_MINI_APP_ID":"fixture", "NH_WECHAT_MINI_APP_SECRET":"fixture"}
        for locale in ("fr","es"):
            with self.subTest(locale=locale), patch.dict("os.environ", {**config, "NH_DEPLOYMENT_LANGUAGE":locale}):
                store = Store(self.store.path.with_name(locale + ".sqlite3"), initial_owner_password="visitor-test-only")
                self.assertEqual(visitor_access.status(store, None, None)["wechatContactLink"], "")
                with patch.object(wechat_tour, "_post") as send, self.assertRaises(PermissionError):
                    wechat_tour.receive(store, {"code":"test", "consent":True}, "local")
                send.assert_not_called()

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
        self.now += timedelta(minutes=2)
        pending = self.request_phone("13000000202")
        issued = []
        self.store.reset_link_senders["sms"] = lambda _, link: issued.append(link)
        reset_links.send(self.store, owner, {"id": guest["id"]}, "https://care.invalid")
        password = "customer-isolation-fixture"
        reset_links.redeem(self.store, {"token": issued[0].split("#reset=")[1], "newPassword": password})
        self.assertFalse(visitor_access.status(self.store, tour, None)["signedIn"])
        self.assertFalse(visitor_access.status(self.store, second, None)["signedIn"])
        with self.assertRaises(ValueError):
            visitor_access.verify(self.store, pending, "fixture")
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
        self.now += timedelta(minutes=2)
        fresh_tour = self.verify_phone("13000000202")
        self.assertTrue(visitor_access.status(self.store, fresh_tour, None)["signedIn"])
        self.owner_change(owner, "access.update", id=guest["id"], enabled=False)
        self.assertFalse(visitor_access.status(self.store, fresh_tour, None)["signedIn"])
        with self.assertRaises(SignedOut):
            self.store.snapshot(token)
        self.now += timedelta(minutes=2)
        with self.assertRaises(ValueError):
            self.verify_phone("13000000202")
        self.owner_change(owner, "access.update", id=guest["id"], enabled=True)
        self.assertFalse(visitor_access.status(self.store, fresh_tour, None)["signedIn"])
        reopened = Store(self.store.path)
        reopened_token, _ = reopened.login("owner", "visitor-test-only")
        self.assertEqual(len(reopened.snapshot(reopened_token)["data"]["accounts"]), 2)

    def test_visitor_proofs_survive_same_host_update_only(self):
        tour = self.verify_phone("13000000303")
        username = visitor_access.status(self.store, tour, None)["customerUsername"]
        pending = self.request_phone("13000000404")
        root = self.store.path.parent
        point = root / "tour.akbak"
        secure_storage.create_snapshot(self.store, point)

        for same_host in (True, False):
            with self.subTest(same_host=same_host):
                restored_path = root / f"restored-{same_host}.sqlite3"
                secure_storage.restore_snapshot(
                    point, restored_path, self.store.storage_key_file, same_host=same_host,
                )
                restored = Store(restored_path, now=lambda: self.now)
                owner, _ = restored.login("owner", "visitor-test-only")
                self.assertIn(username, [account["username"] for account in restored.snapshot(owner)["data"]["accounts"]])
                self.assertEqual(visitor_access.status(restored, tour, None)["signedIn"], same_host)
                if same_host:
                    session = visitor_access.verify(restored, pending, "fixture")
                    self.assertTrue(visitor_access.status(restored, session, None)["signedIn"])
                else:
                    with self.assertRaises(ValueError):
                        visitor_access.verify(restored, pending, "fixture")
