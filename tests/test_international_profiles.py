"""International forms round-trip through the same authenticated business commands."""
from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from release_scope import international_only

from platform_core import account_directory, identity, international_profile, lead_contacts, visitor_access
from platform_core.store import Store


@international_only
class InternationalProfilesTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "institution.db"
        self.password = "institution-test-secret"
        with patch.dict(os.environ, {"NH_DEPLOYMENT_LANGUAGE": "en"}):
            self.store = Store(self.path, initial_data="empty", initial_owner_password=self.password)
        self.owner, _ = self.store.login("owner", self.password)
        self.parts = {"given": "José", "middle": "María", "family": "O’Neill-Santos"}
        self.full = "José María O’Neill-Santos"
        self.address = {"street":"85 King Street", "unit":"Flat 2B", "locality":"London",
                        "region":"Greater London", "postalCode":"SW1A 1AA", "country":"United Kingdom"}

    def command(self, action, **fields):
        return self.store.execute(action, fields, self.store.version(self.owner)["revision"], self.owner)

    def snapshot(self, token=None):
        return self.store.snapshot(token or self.owner)["data"]

    def test_resident_structured_and_legacy_edits(self):
        self.command("care.register", name=self.full, profile={"nameParts": self.parts,
                     "internationalAddress":self.address, "phone":"+44 (7700) 900-123"})
        state = self.snapshot()
        rid = state["residents"][0]["id"]
        profile = state["dossierProfiles"][0]
        self.assertEqual((profile["nameParts"], profile["phone"]), (self.parts, "+447700900123"))
        self.assertEqual(profile["internationalAddress"]["postalCode"], "SW1A 1AA")
        self.assertIn("Flat 2B, London", profile["address"])
        self.command("dossier.profile", residentId=rid, name=self.full, birthplace="Tāmaki Makaurau")
        self.assertEqual(self.snapshot()["dossierProfiles"][0]["nameParts"], self.parts)
        self.command("dossier.profile", residentId=rid, name="Sukarno", address="New address")
        profile = self.snapshot()["dossierProfiles"][0]
        self.assertNotIn("nameParts",profile)
        self.assertNotIn("internationalAddress",profile)
        revision = self.store.version(self.owner)["revision"]
        with self.assertRaisesRegex(ValueError,"match"):
            self.command("care.register",name="Somebody Else",profile={"nameParts":self.parts})
        self.assertEqual(self.store.version(self.owner)["revision"], revision)

    def test_staff_projected_only_into_authorized_directory(self):
        self.command("access.create",kind="staff", role="护工",username="nurse-one",
                     password=self.password,nameParts=self.parts,internationalAddress=self.address)
        staff, actor = self.store.login("nurse-one",self.password)
        self.assertEqual((actor["displayName"], actor["nameParts"]), (self.full,self.parts))
        self.assertNotIn("internationalAddress", actor)
        self.assertNotIn("accounts",self.snapshot(staff))
        record = next(a for a in self.snapshot()["accounts"] if a["id"] == actor["id"])
        self.assertEqual(record["internationalAddress"],self.address)
        self.command("access.update",id=actor["id"],nameParts={"single":"Suharto"})
        self.assertEqual(next(a for a in self.snapshot()["accounts"] if a["id"] == actor["id"])["displayName"],"Suharto")
        with closing(self.store.connect()) as db, db:
            db.execute("INSERT INTO identity_contacts VALUES(?,'sms',?,1)", (actor["id"],"+447700900123"))
        self.assertEqual(account_directory.by_phone(self.store,self.owner,{"phone":"00 44 (7700) 900-123"}), {"accountIds":[actor["id"]]})
        with self.assertRaises(PermissionError):
            account_directory.by_phone(self.store,staff,{"phone":"+447700900123"})
        self.assertNotIn("+447700900123",repr(self.snapshot()["accounts"]))
        self.assertEqual(identity.destination("sms","00 44 (7700) 900-123"), "+447700900123")
        self.assertEqual(identity.destination("sms","+86 138-0000-1000"), "+8613800001000")

    def test_optional_customer_name_and_explicit_visit_with_international_phone(self):
        _, anonymous = visitor_access.register(self.store, {"username":"guest-one","password":self.password},"loopback")
        self.assertEqual(anonymous["displayName"],"Visitor")
        _, named = visitor_access.register(self.store, {"username":"guest-two","password":self.password,
                                           "nameParts":{"single":"Sukarno"}},"loopback")
        self.assertEqual(named["nameParts"], {"single":"Sukarno"})
        with closing(self.store.connect()) as db:
            state = self.snapshot()
            fields = {"source":"visit","phone":"+1 (202) 555-0105","consent":True,"nameParts":self.parts}
            now = datetime.now(timezone.utc)
            self.assertTrue(lead_contacts.receive(db,state,fields,now))
            self.assertFalse(lead_contacts.receive(db,state,{**fields,"phone":"0012025550105"},now))
            lead = state["leadContacts"][0]
            self.assertEqual((lead["name"],lead["nameParts"],lead["phone"]), (self.full,self.parts,"+12025550105"))
            with self.assertRaises(ValueError):
                lead_contacts.receive(db,state,{**fields,"source":"consent"},now)

    def test_family_contacts_use_international_address_and_keep_name_parts_on_edit(self):
        member = {"name":self.full, "nameParts":self.parts, "kind":"其他", "roles":["紧急联系人"],
                  "internationalAddress":self.address, "phone":"+44.7700.900123"}
        self.command("care.register", name="Resident One", profile={"familyContacts":[member]})
        state = self.snapshot()
        contact = state["dossierProfiles"][0]["familyMembers"][0]
        self.assertEqual((contact["nameParts"], contact["internationalAddress"],contact["phone"]),
                         (self.parts,self.address,"+447700900123"))
        rid = state["residents"][0]["id"]
        self.command("dossier.profile",residentId=rid,name="Resident One",
                     familyContact={**{k:v for k,v in member.items() if k not in ("nameParts","internationalAddress")},
                                    "id":contact["id"],"note":"Prefers email"})
        saved=self.snapshot()["dossierProfiles"][0]["familyMembers"][0]
        self.assertEqual(saved["nameParts"],self.parts)
        self.assertEqual(saved["internationalAddress"],self.address)
        self.command("access.create",kind="family",residentId=rid,username="family-member",displayName=self.full,password=self.password)
        token, actor=self.store.login("family-member",self.password)
        self.store.execute("dossier.relative",{"accountId":actor["id"],"residentId":rid,"name":self.full,
                           "nameParts":self.parts,"phone":"+44.7700.900123","relationship":"其他",
                           "internationalAddress":self.address},self.store.version(token)["revision"],token)
        with closing(self.store.connect()) as db:
            import json
            details=json.loads(db.execute("SELECT details FROM dossier_relatives WHERE account_id=?",(actor["id"],)).fetchone()[0])
        self.assertEqual((details["nameParts"],details["internationalAddress"]), (self.parts,self.address))

    def test_validation_rejects_wrong_fields_and_preserves_compound_names(self):
        for bad in ({"given":"Mary"}, {"single":"Lee","family":"Li"}, {"single":"A\nB"}, {"code":"x"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                international_profile.name_parts(bad)
        display, parts = international_profile.name_parts({"given":"Mari\u0301a José","family":"de la Cruz"})
        self.assertEqual(display,"María José de la Cruz")
        self.assertEqual(parts["given"], "María José")
        with self.assertRaises(ValueError):
            international_profile.address({"postalCode":["SW1A"]})

    def test_french_and_spanish_institutions_use_international_name_format(self):
        for tag, given, middle, family in (("fr", "Éléonore", "Anne", "Le Gall-Duval"),
                                           ("es", "María del Carmen", "", "García López")):
            with self.subTest(language=tag), patch.dict(os.environ, {"NH_DEPLOYMENT_LANGUAGE":tag}):
                facility = Store(self.path.with_name(tag+".db"), initial_data="empty", initial_owner_password=self.password)
                self.assertEqual(facility.deployment_edition,"international")
                parts = {"given":given, "family":family, **({"middle":middle} if middle else {})}
                _, user = visitor_access.register(facility,{"username":"foreign-visitor","password":self.password,
                                                           "nameParts":parts},"local")
                self.assertEqual((user["displayName"],user["nameParts"]),
                                 (" ".join(part for part in (given,middle,family) if part),parts))
