"""Bound self-report, source choice and append-only medication histories."""

from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from platform_core import drug_catalog, medication_reports
from platform_core.store import Store, TIMEZONE


class MedicationReportTests(TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.pw = "example-medication-reports-only"
        self.store = Store(
            Path(folder.name) / "store.db",
            initial_owner_password=self.pw,
            now=lambda: datetime(2026, 11, 24, 11, 45, tzinfo=TIMEZONE),
        )
        self.owner = self.store.login("owner", self.pw)[0]
        self.payload = dict(
            residentId="r001",
            rawName="阿莫西淋",
            regimen="本人陈述：早饭后服用",
            day="2026-11-24",
            reference="",
            reportId="",
            expectedVersion=0,
            requestId="test-1",
            confirmed=True,
        )

    def cmd(self, token, action, payload):
        return self.store.execute(
            action, payload, self.store.version(token)["revision"], token
        )

    def family(self, name, rid="r001", **options):
        self.cmd(
            self.owner,
            "access.create",
            dict(
                username=name,
                displayName=name,
                kind="family",
                residentId=rid,
                password=self.pw,
                **options,
            ),
        )
        return self.store.login(name, self.pw)[0]

    def read(self, token, rid="r001"):
        return medication_reports.read(self.store, token, rid)

    def test_raw_then_correction_keeps_original_and_never_creates_order(self):
        me = self.family(
            "self-report", portalSelf=True, portalScopes=["medicationReport"]
        )
        with closing(self.store.connect()) as db:
            orders = json.loads(db.execute("SELECT data FROM workspace").fetchone()[0])[
                "medications"
            ]
        self.cmd(me, "portal.reportMedication", self.payload)
        raw = self.read(me)["reports"][0]
        self.assertEqual(
            (raw["rawName"], raw["name"], raw["version"], raw["bySelf"]),
            ("阿莫西淋", "", 1, True),
        )
        with patch.object(
            drug_catalog.catalogue,
            "current",
            return_value=({"阿莫西林": 39}, "online", "test"),
        ):
            match = medication_reports.lookup(
                self.store, self.owner, "r001", "阿莫西淋"
            )["matches"][0]
        self.assertEqual(match["match"], "相似写法")
        update = dict(
            self.payload,
            reportId=raw["reportId"],
            expectedVersion=1,
            reference=match["reference"],
            requestId="test-2",
        )
        self.cmd(self.owner, "care.reportMedication", update)
        self.cmd(self.owner, "care.reportMedication", update)
        item = self.read(me)["reports"][0]
        self.assertEqual(
            (item["name"], item["rawName"], item["version"], item["bySelf"]),
            ("阿莫西林", "阿莫西淋", 2, False),
        )
        self.assertEqual([e["version"] for e in item["history"]], [1])
        self.assertTrue(item["url"].endswith("#page=39"))
        with self.assertRaises(ValueError):
            self.cmd(me, "portal.reportMedication", dict(update, requestId="stale"))
        with closing(self.store.connect()) as db:
            self.assertEqual(
                orders,
                json.loads(db.execute("SELECT data FROM workspace").fetchone()[0])[
                    "medications"
                ],
            )
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM resident_medication_reports"
                ).fetchone()[0],
                2,
            )

    def test_scope_and_forged_references(self):
        me = self.family(
            "self-report", portalSelf=True, portalScopes=["medicationReport"]
        )
        relative = self.family("relative-face", portalScopes=["medication"])
        with self.assertRaises(ValueError):
            self.family("relative-write", portalScopes=["medicationReport"])
        for token, rid in ((relative, "r001"), (me, "r002")):
            with self.assertRaises(PermissionError):
                self.read(token, rid)
            with patch.object(
                drug_catalog.catalogue,
                "current",
                side_effect=AssertionError("no lookup"),
            ):
                with self.assertRaises(PermissionError):
                    medication_reports.lookup(self.store, token, rid, "阿莫西林")
            with self.assertRaises(PermissionError):
                self.cmd(
                    token, "portal.reportMedication", dict(self.payload, residentId=rid)
                )
        for patch_payload in (
            {"reference": "made-up"},
            {"confirmed": False},
            {"day": "2028-01-01"},
            {"name": "伪造候选"},
        ):
            with self.assertRaises(ValueError):
                self.cmd(
                    me, "portal.reportMedication", dict(self.payload, **patch_payload)
                )

    def test_publication_cache_and_fuzzy_lookup(self):
        cache = drug_catalog.Catalogue()
        with patch.object(drug_catalog, "_download", side_effect=OSError("offline")):
            self.assertEqual(cache.current()[1], "unavailable")
        cache.next_check = 0
        with patch.object(
            drug_catalog, "_download", return_value={"二甲双胍": 15, "阿莫西林": 39}
        ) as fetch:
            with patch.object(drug_catalog, "catalogue", cache):
                self.assertEqual(
                    drug_catalog.suggestions("阿莫")["matches"][0]["name"], "阿莫西林"
                )
                self.assertEqual(
                    drug_catalog.suggestions("二甲胍双")["matches"][0]["name"],
                    "二甲双胍",
                )
            fetch.assert_called_once_with()
        cache.next_check = 0
        with patch.object(drug_catalog, "_download", side_effect=OSError("offline")):
            names, status, when = cache.current()
            self.assertEqual(status, "cached")
            self.assertTrue(when)
            self.assertIn("阿莫西林", names)
        self.assertEqual(
            drug_catalog._index(
                "甲   1   阿莫西林       口服常释剂型\n甲   2                 注射剂"
            ),
            {"阿莫西林": 1},
        )

    def test_live_lookup_excludes_unrelated_entities_and_blocks_private_terms(self):
        from platform_core import drug_search

        with closing(self.store.connect()) as db:
            resident_name = json.loads(
                db.execute("SELECT data FROM workspace").fetchone()[0]
            )["residents"][0]["name"]
        for term in ("101房间阿莫西林", resident_name + "阿莫西林", "13800000000"):
            with patch.object(
                drug_search, "_api", side_effect=AssertionError("不得外发")
            ):
                with self.assertRaises(ValueError):
                    medication_reports.lookup(
                        self.store, self.owner, "r001", term, online=True
                    )
        pages = [
            {
                "search": [
                    {"id": "Q201928", "label": "阿莫西林"},
                    {"id": "Q123", "label": "一篇论文"},
                ]
            },
            {
                "entities": {
                    "Q201928": {
                        "claims": {
                            "P267": [{"mainsnak": {"datavalue": {"value": "J01CA04"}}}]
                        }
                    },
                    "Q123": {"claims": {}},
                }
            },
        ]
        with patch.object(drug_search, "_api", side_effect=pages) as api:
            result = medication_reports.lookup(
                self.store, self.owner, "r001", "阿莫西林", online=True
            )
        self.assertEqual(api.call_args_list[0].kwargs["search"], "阿莫西林")
        self.assertEqual(len(result["matches"]), 1)
        item = result["matches"][0]
        self.assertEqual((item["name"], item["match"]), ("阿莫西林", "ATC J01CA04"))
        self.cmd(
            self.owner,
            "care.reportMedication",
            dict(self.payload, reference=item["reference"]),
        )
        self.assertEqual(
            self.read(self.owner)["reports"][0]["url"],
            "https://www.wikidata.org/wiki/Q201928",
        )
        with patch.object(drug_search, "_api", side_effect=TimeoutError()):
            offline = medication_reports.lookup(
                self.store, self.owner, "r001", "阿莫西林", online=True
            )
        self.assertEqual((offline["status"], offline["matches"]), ("unavailable", []))
