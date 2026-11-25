from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import sqlite3

from release_scope import international_only

from platform_core import deployment_language as locale
from platform_core.backups import restore_plan
from platform_core.store import Store


class DeploymentLanguage(TestCase):
    def test_chinese_installation_persists_edition_and_page_metadata(self):
        with TemporaryDirectory() as tmp, patch.dict("os.environ", NH_DEPLOYMENT_LANGUAGE="zh-CN"):
            path = Path(tmp) / "facility.sqlite3"
            store = Store(path, initial_data="empty")
            self.assertEqual((store.deployment_language, store.deployment_edition), ("zh-CN", "china"))
            self.assertEqual(Store(path).deployment_language, "zh-CN")
            with closing(store.connect()) as db, self.assertRaisesRegex(Exception, "immutable"):
                db.execute("DELETE FROM deployment_language")
        self.assertEqual(locale.public("zh-CN")["mapProvider"], "amap")
        html = locale.page(b'<html lang="zh-CN"><head></head></html>', "zh-CN")
        self.assertIn(b'lang="zh-CN"', html)
        self.assertIn(b'src="/deployment.js"', html)
        self.assertNotIn(b"/lib/deployment-i18n.js", html)

    @international_only
    def test_persisted_edition_and_read_only_metadata(self):
        with TemporaryDirectory() as tmp:
            db_file = Path(tmp) / "care.db"
            with patch.dict("os.environ", NH_DEPLOYMENT_LANGUAGE="en"):
                first = Store(db_file, initial_data="empty")
            self.assertEqual(Store(db_file).deployment_language, "en")
            with patch.dict("os.environ", NH_DEPLOYMENT_LANGUAGE="zh-CN"), self.assertRaisesRegex(ValueError, "cannot be changed"):
                Store(db_file)
            with closing(first.connect()) as db:
                with self.assertRaisesRegex(Exception, "immutable"):
                    db.execute("UPDATE deployment_language SET language='zh-CN'")
            html = locale.page(b'<html lang="zh-CN"><head></head></html>', "en")
            self.assertIn(b'lang="en"', html)
            self.assertLess(html.index(b"/deployment.js"), html.index(b"/lib/deployment-i18n.js"))
            self.assertEqual(locale.public("en")["mapProvider"], "google")

    def test_existing_chinese_installations_keep_their_language(self):
        with TemporaryDirectory() as tmp, patch.dict("os.environ", NH_DEPLOYMENT_LANGUAGE="zh-CN"):
            db_file = Path(tmp) / "legacy.db"
            first = Store(db_file)
            with closing(first.connect()) as db, db:
                db.execute("DROP TABLE deployment_language")
            self.assertEqual(Store(db_file).deployment_language, "zh-CN")

    @international_only
    def test_legacy_installation_refuses_requested_language_change(self):
        with TemporaryDirectory() as tmp:
            db_file = Path(tmp) / "legacy.db"
            first = Store(db_file)
            with closing(first.connect()) as db, db:
                db.execute("DROP TABLE deployment_language")
            with patch.dict("os.environ", NH_DEPLOYMENT_LANGUAGE="en"), self.assertRaisesRegex(ValueError, "cannot be changed"):
                Store(db_file)
            self.assertEqual(Store(db_file).deployment_language, "zh-CN")

    def test_chinese_restore_rejects_incompatible_snapshot_metadata(self):
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("ATTACH ':memory:' AS incoming")
            for schema, value in (("main", "zh-CN"), ("incoming", "unsupported")):
                db.execute(f"CREATE TABLE {schema}.facility_site (id TEXT)")
                db.execute(f"INSERT INTO {schema}.facility_site VALUES ('same-institution')")
                db.execute(f"CREATE TABLE {schema}.deployment_language (id INTEGER, language TEXT)")
                db.execute(f"INSERT INTO {schema}.deployment_language VALUES (1, ?)", (value,))
            with self.assertRaisesRegex(ValueError, "部署语言"):
                restore_plan.describe(db)

    @international_only
    def test_restore_cannot_import_another_language_or_reinterpret_an_old_snapshot(self):
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("ATTACH ':memory:' AS incoming")
            for schema in ("main", "incoming"):
                db.execute(f"CREATE TABLE {schema}.facility_site (id TEXT)")
                db.execute(f"INSERT INTO {schema}.facility_site VALUES ('same-institution')")
            db.execute("CREATE TABLE main.deployment_language (id INTEGER, language TEXT)")
            db.execute("INSERT INTO main.deployment_language VALUES (1, 'fr')")
            with self.assertRaisesRegex(ValueError, "部署语言"):
                restore_plan.describe(db)
            db.execute("CREATE TABLE incoming.deployment_language AS SELECT 1 AS id, 'es' AS language")
            with self.assertRaisesRegex(ValueError, "部署语言"):
                restore_plan.describe(db)

    @international_only
    def test_french_and_spanish_inherit_international_features_and_overlay(self):
        for language in ("fr", "es"):
            with self.subTest(language=language), TemporaryDirectory() as tmp:
                path = Path(tmp) / "institution.db"
                with patch.dict("os.environ", NH_DEPLOYMENT_LANGUAGE=language):
                    store = Store(path, initial_data="empty")
                self.assertEqual(store.deployment_edition, "international")
                self.assertEqual(Store(path).deployment_language, language)
                public = locale.public(language)
                self.assertEqual((public["fallbackLanguage"],public["mapProvider"]),("en","google"))
                self.assertEqual(public["messagesOverlay"], f"/assets/locales/{language}.json")
                self.assertIn(f'lang="{language}"'.encode(), locale.page(b'<html lang="zh-CN"><head></head>',language))

    @international_only
    def test_new_locale_only_needs_manifest_registration_to_inherit_english(self):
        catalog = dict(locale.locales(), it={"name": "Italiano"})
        with patch.object(locale, "locales", return_value=catalog):
            info = locale.public("it")
            self.assertEqual((info["edition"], info["fallbackLanguage"], info["mapProvider"]),
                             ("international", "en", "google"))
            self.assertIsNone(info["messagesOverlay"])
            self.assertEqual(locale.message("it", "Beds available"), "Beds available")

    @international_only
    def test_french_name_and_unambiguous_dob_from_labelled_original(self):
        from platform_core.agents import resident_profile_intake
        lines = [{"text":v} for v in ("Full name: Renée O’Neill", "DOB: 1950-09-03", "Mobile: +353 87 123 4567",
                                       "Place of birth: Côte d’Or", "Postal address: 10 River Road")]
        result = resident_profile_intake.suggestions(lines, {"fields":{},"ambiguous":[]}, international=True)
        self.assertEqual(result["fields"]["name"], "Renée O’Neill")
        self.assertEqual(result["fields"]["phone"], "+353871234567")
        lines.append({"text":"Date of birth: 09/03/1950"})
        result = resident_profile_intake.suggestions(lines, {"fields":{},"ambiguous":[]}, international=True)
        self.assertIn("birthDate",result["ambiguous"])
        self.assertNotIn("birthDate",result["fields"])
