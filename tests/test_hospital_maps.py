"""Opt-in hospital lookup sends public location terms only and leaves chart data untouched."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from release_scope import international_only

from platform_core import hospital_catalog as catalog, hospital_maps as maps, medical_visits
from platform_core.store import Store
from test_medical_visits import fixture_visit


class HospitalMapTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "test.sqlite3"
        self.password = "fixture-map-secret-2026"

    def work(self, language):
        with patch.dict("os.environ", {"NH_DEPLOYMENT_LANGUAGE":language}):
            store = Store(self.path.with_name(language + ".sqlite3"), initial_owner_password=self.password)
        return store, store.login("owner", self.password)[0]

    @international_only
    def test_global_query_filters_no_record_or_credentials_in_payload(self):
        store, user = self.work("en")
        fixture = {"places":[{"id":"place123", "displayName":{"text":"Test Hospital"},
                    "formattedAddress":"Fictional City", "attributions":[{"provider":"example","providerUri":"https://example.org"}]}]}
        self.assertEqual(catalog.search(store, user, "河南"), {"options":[]})
        with patch.dict("os.environ", {"NH_GOOGLE_PLACES_KEY":"test-places"}), patch.object(maps, "_fetch", return_value=fixture) as fetch:
            res = catalog.online(store, user, {"q":"Hospital London"})
            self.assertEqual(res["options"][0]["placeId"], "place123")
            self.assertEqual(fetch.call_args.args, ("places.googleapis.com", "/v1/places:searchText"))
            self.assertEqual(json.loads(fetch.call_args.kwargs["body"]), {"textQuery":"Hospital London",
                          "languageCode":"en", "includedType":"hospital", "strictTypeFiltering":True, "pageSize":8})
            self.assertEqual(fetch.call_args.kwargs["headers"]["X-Goog-Api-Key"], "test-places")
            for request in ({"q":"patient ID 12345678"}, {"q":"Hospital", "residentId":"r001"}, {"q":"https://other.test/"}, {"q":"a\nb"}):
                with self.assertRaises(ValueError):
                    catalog.online(store, user, request)
            fetch.assert_called_once()
            self.assertNotIn("test-places", json.dumps(res))

    @international_only
    def test_french_spanish_share_worldwide_lookup_without_or_with_keys(self):
        for lang, name in (("fr", "Hôpital à Lyon"), ("es", "Hospital de Madrid")):
            with self.subTest(lang=lang):
                store, user = self.work(lang)
                self.assertEqual(store.deployment_edition, "international")
                with patch.object(catalog, "lookup", side_effect=AssertionError):
                    self.assertEqual(catalog.search(store, user, name)["options"], [])
                with patch.dict("os.environ", {"NH_AMAP_WEB_KEY":"unused","NH_GOOGLE_PLACES_KEY":""}), patch.object(maps, "_fetch") as fetch:
                    self.assertEqual(catalog.online(store, user, {"q":name}), {"status":"not-configured","provider":"google","options":[]})
                    fetch.assert_not_called()
                fixture = {"places":[{"id":"p", "displayName":{"text":name}, "formattedAddress":"Example"}]}
                with patch.dict("os.environ", {"NH_GOOGLE_PLACES_KEY":"fixture"}), patch.object(maps, "_fetch", return_value=fixture) as fetch:
                    result = catalog.online(store, user, {"q":name})
                    self.assertEqual((result["provider"],result["status"],result["options"][0]["name"]), ("google","ok",name))
                    self.assertEqual(fetch.call_args.args[0], "places.googleapis.com")
                    self.assertEqual(json.loads(fetch.call_args.kwargs["body"])["languageCode"], lang)

    @international_only
    def test_authorization_precedes_paid_search_and_no_key_or_offline_fallback(self):
        store, user = self.work("en")
        store.execute("access.create", {"username":"map-staff", "displayName":"后勤员工", "role":"自定义",
                      "kind":"staff", "permissions":["care"], "password":self.password}, store.version(user)["revision"], user)
        restricted = store.login("map-staff", self.password)[0]
        with patch.dict("os.environ", {"NH_GOOGLE_PLACES_KEY":"test-places"}), patch.object(maps, "_fetch", side_effect=TimeoutError) as fetch:
            with self.assertRaises(PermissionError):
                catalog.online(store, restricted, {"q":"Test Hospital"})
            fetch.assert_not_called()
            self.assertEqual(catalog.online(store, user, {"q":"Test Hospital"})["status"], "unavailable")
        with patch.dict("os.environ", {"NH_GOOGLE_PLACES_KEY":""}), patch.object(maps, "_fetch") as fetch:
            self.assertEqual(catalog.online(store, user, {"q":"Test Hospital"})["status"], "not-configured")
            fetch.assert_not_called()

    def test_chinese_directory_amap_and_supplement(self):
        store, user = self.work("zh-CN")
        rid = "r001"
        day = store.now().date().isoformat()
        parent = fixture_visit(store, user, rid, day)
        with patch.object(maps, "_fetch") as fetch:
            self.assertIn("汝州市第一人民医院", [row["name"] for row in catalog.search(store, user, "汝州一院")["options"]])
            fetch.assert_not_called()
            with patch.object(catalog, "entries", side_effect=FileNotFoundError):
                self.assertEqual(catalog.search(store, user, "医院")["options"], [])
        data = {"status":"1", "pois":[{"name":"测试医院", "pname":"河南省", "cityname":"平顶山市", "adname":"汝州市"}]}
        with patch.dict("os.environ", {"NH_AMAP_WEB_KEY":"test-amap"}), patch.object(maps, "_fetch", return_value=data) as fetch:
            actual = catalog.online(store, user, {"q":"汝州医院"})
            self.assertEqual(actual["options"][0]["locality"], "河南省平顶山市汝州市")
            self.assertEqual(fetch.call_args.args[0], "restapi.amap.com")
            self.assertEqual(parse_qs(urlsplit(fetch.call_args.args[1]).query)["keywords"], ["汝州医院"])
        record = medical_visits.preview(store, user, rid, {
            "revision":store.version(user)["revision"], "requestId":"map-supplement", "mode":"manual",
            "visitId":parent, "fields":{"eventDate":day,"facility":"原件机构","tests":"复核结果"},
        })
        self.assertEqual(record["parentVisitId"], parent)
        self.assertEqual(record["fields"]["facility"], "原件机构")

    def test_chinese_online_search_checks_permissions_and_public_terms_before_call(self):
        store, owner = self.work("zh-CN")
        store.execute("access.create", {"username":"map-staff", "displayName":"后勤员工", "role":"自定义",
                      "kind":"staff", "permissions":["care"], "password":self.password},
                      store.version(owner)["revision"], owner)
        restricted = store.login("map-staff", self.password)[0]
        with patch.dict("os.environ", NH_AMAP_WEB_KEY="fixture"), patch.object(maps, "_fetch", side_effect=TimeoutError) as fetch:
            with self.assertRaises(PermissionError):
                catalog.online(store, restricted, {"q":"汝州医院"})
            for request in ({"q":"病历号12345678"}, {"q":"医院", "residentId":"r001"}):
                with self.assertRaises(ValueError):
                    catalog.online(store, owner, request)
            fetch.assert_not_called()
            self.assertEqual(catalog.online(store, owner, {"q":"汝州医院"})["status"], "unavailable")
        with patch.dict("os.environ", NH_AMAP_WEB_KEY=""), patch.object(maps, "_fetch") as fetch:
            self.assertEqual(catalog.online(store, owner, {"q":"汝州医院"})["status"], "not-configured")
            fetch.assert_not_called()
