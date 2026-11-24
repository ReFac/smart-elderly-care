import json
import sqlite3
import unittest
from datetime import datetime

from platform_core import access, dossier, facility, lead_contacts as leads
from platform_core.bootstrap import empty_workspace


class LeadContactTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.state = empty_workspace()
        access.init(self.db, "lead-test-only")
        facility.init(self.db, self.state)
        dossier.init(self.db)
        self.home = facility.HOME_CAMPUS
        self.db.execute("INSERT INTO facility_campuses(id,name) VALUES('west','西区')")
        self.now = datetime(2026, 11, 24, 10, 20, 28, tzinfo=leads.LOCAL)
        self.owner = {"id": "tester", "kind": "owner", "displayName": "测试院长"}
        self.a = "13800000001"
        self.b = "13800000002"

    def account(self, kind, role, phone, rid=""):
        self.db.execute(
            """INSERT INTO accounts(id,username,kind,role,display_name,resident_id,salt,password_hash)
               VALUES(?,?,?,?,?,?,X'00',X'00')""",
            (phone, "u" + phone, kind, role, role, rid),
        )
        self.db.execute(
            "INSERT INTO identity_contacts VALUES(?, 'sms', ?, 1)",
            (phone, "+86" + phone),
        )

    def receive(self, phone=None, source="consent", **fields):
        payload = {"source": source, "consent": True, "phone": phone or self.a}
        if source == "visit":
            payload["name"] = "赵女士"
        return leads.receive(self.db, self.state, {**payload, **fields}, self.now)

    def save(self, name, fields, actor=None):
        return leads.command(
            self.db, self.state, actor or self.owner, "leads." + name, fields, self.now
        )

    def call(self, lid, direction="outgoing", **fields):
        payload = {
            "leadId": lid,
            "direction": direction,
            "feedback": "已记录客户意见",
            "occurredAt": self.now.isoformat(),
        }
        if direction == "outgoing":
            payload["outcome"] = "继续联系"
        return self.save("call", {**payload, **fields})

    def book(self, lid, kind="visit", **fields):
        return self.save(
            "book",
            {
                "leadId": lid,
                "kind": kind,
                "date": "2026-11-25",
                "start": "10:00",
                "end": "11:00",
                "phoneConfirmed": True,
                **fields,
            },
        )

    def view(self, actor=None):
        data = dict(self.state)  # model the owner's initially unrestricted projection
        leads.project(self.db, self.state, actor or self.owner, data)
        return data

    def test_consent_is_required_active_sources_excluded_and_no_existence_is_disclosed(
        self,
    ):
        with self.assertRaises(ValueError):
            self.receive(consent=False)
        self.assertFalse(self.state["leadContacts"])
        self.account("staff", "护理员", self.a)
        self.account("family", "亲属", self.b)
        self.db.execute(
            "INSERT INTO dossier_profiles VALUES('person','{}',?)",
            (json.dumps({"familyMembers": [{"phone": "138-0000-0003"}]}),),
        )
        self.db.execute(
            "INSERT INTO dossier_relatives VALUES('parent','person',?)",
            (json.dumps({"phone": "＋８６ １３８０００００００４"}),),
        )
        for i in range(1, 5):
            self.assertFalse(self.receive(f"1380000000{i}"))
        self.assertFalse(self.view()["leadEvents"])
        self.assertTrue(self.receive("+86 138-0000-0001", source="visit"))
        (lead,) = self.view()["leadContacts"]
        self.assertFalse(lead["callbackExempt"])
        self.assertEqual(lead["phone"], self.a)
        self.call(lead["id"])
        self.assertFalse(self.receive(self.a))
        self.assertTrue(self.receive("13800000005"))
        cold = self.view()["leadContacts"][-1]
        self.call(cold["id"], outcome="未接通")
        self.assertEqual(self.view()["leadContacts"][-1]["status"], "待回访")
        self.assertFalse(self.receive("+8613800000005"))
        self.assertEqual(2, len(self.view()["leadContacts"]))

    def test_staff_log_all_calls_and_walkins_even_for_existing_phone(self):
        self.account("staff", "员工", self.a)
        manual = {"campusId": self.home, "phone": self.a, "name": "访客甲"}
        self.save("register", {**manual, "occurredAt": "2026-11-24T09:08:07"})
        self.save("register", {**manual, "occurredAt": "2026-11-24T09:08:27"})
        self.save(
            "register",
            {**manual, "channel": "walkin", "occurredAt": "2026-11-24T10:15"},
        )
        (lead,) = self.view()["leadContacts"]
        self.assertEqual(lead["status"], "待接待")
        self.assertEqual(
            [r["kind"] for r in self.view()["leadEvents"]], ["来电", "来电", "到访登记"]
        )
        self.assertEqual(
            self.view()["leadEvents"][0]["occurredAt"], "2026-11-24T09:08:07+08:00"
        )
        self.save("feedback", {"leadId": lead["id"], "feedback": "已看房，考虑试住"})
        self.save("archive", {"leadId": lead["id"], "feedback": "已接待完成"})
        self.assertEqual(self.view()["leadContacts"][0]["status"], "已归档")
        with self.assertRaises(ValueError):
            self.call(lead["id"])
        self.save("register", {**manual, "occurredAt": self.now.isoformat()})
        self.assertEqual(len(self.view()["leadContacts"]), 2)
        with self.assertRaises(ValueError):
            self.save("register", {**manual, "occurredAt": "2026-11-25T10:15"})

    def test_phone_confirmation_cancellation_and_feedback_complete_the_right_booking(
        self,
    ):
        self.receive(source="visit", preferredAt="2026-11-25T10:00")
        self.assertFalse(self.view()["visitBookings"])
        lid = self.view()["leadContacts"][0]["id"]
        with self.assertRaisesRegex(ValueError, "电话"):
            self.book(lid, phoneConfirmed=False)
        self.book(lid)
        self.book(lid, "callback", start="08:00", end="08:30")
        self.call(lid, occurredAt="2026-11-23T09:00:00")
        self.assertEqual(self.view()["visitBookings"][-1]["status"], "confirmed")
        self.call(lid)
        self.assertEqual(self.view()["visitBookings"][-1]["status"], "completed")
        self.save(
            "cancel", {"leadId": lid, "kind": "visit", "feedback": "改约其他日期"}
        )
        self.assertEqual(self.view()["visitBookings"][0]["status"], "cancelled")
        self.book(lid)
        self.save("feedback", {"leadId": lid, "feedback": "完成接待"})
        self.assertEqual(self.view()["visitBookings"][-1]["status"], "completed")
        self.book(lid, "callback")
        self.save("archive", {"leadId": lid, "feedback": "已完成"})
        self.assertEqual(self.view()["visitBookings"][-1]["status"], "cancelled")

    def test_new_admission_cancels_existing_callback_and_prevents_restarting_sales(
        self,
    ):
        self.receive()
        lid = self.view()["leadContacts"][0]["id"]
        self.book(lid, "callback")
        self.state["residents"] = [{"id": "resident", "status": "在住", "contact": ""}]
        self.account("family", "入住长者", self.a, "resident")
        self.assertTrue(self.view()["leadContacts"][0]["callbackExempt"])
        with self.assertRaises(ValueError):
            self.call(lid)
        with self.assertRaises(ValueError):
            self.book(lid, "callback")
        leads.reconcile_callbacks(self.db, self.state, self.now)
        leads.reconcile_callbacks(self.db, self.state, self.now)
        self.assertEqual(self.view()["visitBookings"][0]["status"], "cancelled")
        self.assertEqual(
            [e["kind"] for e in self.view()["leadEvents"]].count("停止回访"), 1
        )
        self.state["residents"][0]["status"] = "已退住"
        with self.assertRaisesRegex(ValueError, "停止回访"):
            self.call(lid)
        self.assertTrue(self.receive(source="visit"))
        self.call(lid)
        self.assertFalse(self.view()["leadContacts"][0]["callbackExempt"])

    def test_admitted_profile_and_legacy_contact_match_manual_public_and_callback_filters(
        self,
    ):
        self.state["residents"] = [
            {
                "id": "r1",
                "status": "在住",
                "contact": "长者本人联系电话：+86 138-0000-0001",
            },
            {"id": "r2", "status": "在住", "contact": ""},
        ]
        self.db.execute(
            "INSERT INTO dossier_profiles VALUES('r2',?,'{}')",
            (json.dumps({"phone": self.b}),),
        )
        self.assertFalse(self.receive(self.a))
        self.assertFalse(self.receive(self.b))
        self.assertTrue(self.receive(self.a, source="visit"))
        self.save(
            "register",
            {
                "campusId": self.home,
                "phone": self.b,
                "occurredAt": self.now.isoformat(),
            },
        )
        for lead in self.view()["leadContacts"]:
            self.assertTrue(lead["callbackExempt"])
            with self.assertRaises(ValueError):
                self.call(lead["id"])
            self.call(lead["id"], "incoming")
            self.save("archive", {"leadId": lead["id"], "feedback": "完成"})

    def test_declined_recontact_stays_closed_until_customer_requests_a_visit(self):
        self.receive()
        rid = self.view()["leadContacts"][0]["id"]
        self.book(rid, "callback")
        self.call(rid, outcome="暂无意向", feedback="客户要求暂时停止电话")
        self.assertTrue(self.view()["leadContacts"][0]["callbackStopped"])
        with self.assertRaises(ValueError):
            self.book(rid, "callback")
        self.call(rid, "incoming")
        with self.assertRaises(ValueError):
            self.call(rid)
        self.save("archive", {"leadId": rid, "feedback": "按客户意愿结案"})
        self.assertFalse(self.receive())
        self.receive(source="visit")
        self.assertFalse(self.view()["leadContacts"][-1]["callbackStopped"])

    def test_unlabelled_and_relative_legacy_contacts_do_not_imply_residency(self):
        self.state["residents"] = [
            {"id": "r1", "status": "在住", "contact": "家属本人：138-0000-0001"},
            {"id": "r2", "status": "在住", "contact": "13800000002"},
            {
                "id": "r3",
                "status": "在住",
                "contact": "长者本人：13800000003；家属: 13800000004",
            },
        ]
        for index in range(1, 5):
            phone = f"1380000000{index}"
            self.assertFalse(self.receive(phone))
            self.assertTrue(self.receive(phone, source="visit"))
            row = self.view()["leadContacts"][-1]
            self.assertEqual(
                row["callbackExemptReason"], "admitted" if index == 3 else ""
            )

    def test_new_directory_entry_stops_cold_callbacks_and_allows_explicit_enquiry(self):
        self.receive()
        lid = self.view()["leadContacts"][0]["id"]
        self.book(lid, "callback")
        self.account("staff", "员工", self.a)
        leads.reconcile_callbacks(self.db, self.state, self.now)
        self.assertEqual(
            self.view()["leadContacts"][0]["callbackExemptReason"], "directory"
        )
        self.assertEqual(self.view()["visitBookings"][0]["status"], "cancelled")
        self.db.execute("DELETE FROM identity_contacts WHERE account_id=?", (self.a,))
        self.assertEqual(
            self.view()["leadContacts"][0]["callbackExemptReason"], "directory"
        )
        with self.assertRaises(ValueError):
            self.call(lid)
        self.receive(source="visit")
        self.assertEqual(self.view()["leadContacts"][0]["callbackExemptReason"], "")
        self.call(lid)

    def test_identical_visit_retry_keeps_progress_and_changed_request_has_its_own_event(
        self,
    ):
        self.receive(source="visit", note="看餐厅", preferredAt="2026-11-25T10:00")
        lid = self.view()["leadContacts"][0]["id"]
        self.call(lid, outcome="暂无意向")
        self.assertFalse(
            self.receive(
                "+86 " + self.a,
                source="visit",
                note="看餐厅",
                preferredAt="2026-11-25T02:00:00Z",
            )
        )
        self.assertTrue(self.view()["leadContacts"][0]["callbackStopped"])
        self.assertTrue(
            self.receive(source="visit", note="看餐厅", preferredAt="2026-11-26T10:00")
        )
        self.assertEqual(
            [e["kind"] for e in self.view()["leadEvents"]],
            ["申请参观", "回访", "申请参观"],
        )
        self.assertFalse(self.view()["leadContacts"][0]["callbackStopped"])
        self.assertFalse(self.view()["visitBookings"])

    def test_leads_and_booking_policies_scoped_to_full_campus_staff(self):
        self.receive()
        self.receive(campusId="west")
        home, west = self.view()["leadContacts"]
        self.book(home["id"])
        self.book(west["id"])
        self.state["visitSchedulePolicies"] = [
            {"id": "west", "campusId": "west", "capacity": 2}
        ]
        home_staff = {
            "id": "home",
            "kind": "staff",
            "permissions": ["intake"],
            "displayName": "接待",
            "facilityScope": {"campusIds": [self.home]},
        }
        home_view = self.view(home_staff)
        self.assertEqual([r["id"] for r in home_view["leadContacts"]], [home["id"]])
        self.assertTrue(home_view["leadEvents"])
        self.assertTrue(
            all(r["campusId"] == self.home for r in home_view["leadEvents"])
        )
        self.assertEqual(len(home_view["visitBookings"]), 1)
        self.assertFalse(home_view["visitSchedulePolicies"])
        with self.assertRaises(PermissionError):
            self.save("archive", {"leadId": west["id"], "feedback": "越权"}, home_staff)
        for scope in (
            {"campusIds": []},
            {"campusIds": [self.home], "roomIds": ["room-a"]},
        ):
            worker = {**home_staff, "facilityScope": scope}
            self.assertFalse(self.view(worker)["leadContacts"])
            with self.assertRaises(PermissionError):
                self.save("archive", {"leadId": home["id"], "feedback": "越权"}, worker)
        family = {"kind": "family", "permissions": []}
        self.assertFalse(self.view(family)["leadEvents"])
        self.assertFalse(self.view(family)["visitBookings"])
