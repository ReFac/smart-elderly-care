"""OCR never changes clinical fields until an authorized person checks the original."""

import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import copy
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from platform_core import document_ocr
from platform_core.store import Store

FIXTURE = Path(__file__).parent / "fixtures" / "discharge-training.png"
LOCAL = Path(__file__).resolve().parents[1] / ".local/ocr/usr/bin/tesseract"
PASSWORD = "local-ocr-test-account"
RESULT = {
    "state": "recognized",
    "engine": "test fixture",
    "lines": [
        {
            "page": 1,
            "line": 1,
            "text": "过敏史：原文乙",
            "confidence": 63,
            "box": [2, 5, 44, 18],
        }
    ],
    "candidates": [{"field": "allergies", "value": "原文乙", "line": 1}],
}


class DocumentOcrTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "test.db"
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": PASSWORD}):
            self.store = Store(self.path)
        self.owner, self.actor = self.store.login("owner", PASSWORD)
        self.rid = "r001"
        self.payload = {
            "residentId": self.rid,
            "requestId": "fixture",
            "category": "出院小结",
            "source": "虚构测试文书",
            "method": document_ocr.METHOD,
            "eventDate": "2025-11-01",
            "imageBase64": base64.b64encode(FIXTURE.read_bytes()).decode(),
        }
        self.command("dossier.document", self.payload)
        self.doc = self.view()
        self.arg = {"residentId": self.rid, "documentId": self.doc["id"]}

    def data(self, actor=None):
        return self.store.snapshot(actor or self.owner)["data"]

    def view(self):
        return self.data()["medicalDocuments"][0]

    def resident(self):
        return next(r for r in self.data()["residents"] if r["id"] == self.rid)

    def command(self, action, payload, actor=None):
        token = actor or self.owner
        return self.store.execute(
            action, payload, self.store.version(token)["revision"], token
        )

    def process(self):
        self.command("dossier.ocr", self.arg)

    def review(self, **extras):
        return {
            **self.arg,
            "verifiedName": self.resident()["name"],
            "sourceFacts": "已核对的原文",
            "pending": "",
            "method": "院内 OCR 人工核对",
            "changes": [],
            **extras,
        }

    def create_user(self, login, perms):
        self.command(
            "access.create",
            {
                "kind": "staff",
                "username": login,
                "displayName": login,
                "password": PASSWORD,
                "role": "自定义",
                "permissions": perms,
            },
        )
        return self.store.login(login, PASSWORD)[0]

    def test_immutable_original_cache_and_authorized_review(self):
        self.assertIsNone(self.doc["summary"])
        old = copy.deepcopy(self.resident())
        with patch.object(document_ocr, "recognize", return_value=RESULT) as engine:
            self.command(
                "dossier.ocr",
                {"residentId": self.rid, "imageHash": self.doc["imageHash"]},
            )
            self.process()
            self.assertEqual(engine.call_count, 1)
        self.assertEqual(self.resident(), old)
        self.assertEqual(self.view()["ocr"]["state"], "recognized")
        self.assertNotIn("lines", self.view()["ocr"])
        changes = [
            {
                "field": "allergies",
                "value": "人工修订乙",
                "previous": old["allergies"],
                "line": 1,
            }
        ]
        body = self.review(changes=changes)
        other = self.create_user("no-clinical", ["medical.write"])
        with self.assertRaises(PermissionError):
            self.command("dossier.reviewDocument", body, other)
        with self.assertRaises(ValueError):
            self.command("dossier.reviewDocument", {**body, "verifiedName": "另一人"})
        with self.assertRaises(ValueError):
            self.command(
                "dossier.reviewDocument",
                {**body, "changes": [{**changes[0], "line": 7}]},
            )
        with self.assertRaises(ValueError):
            self.command(
                "dossier.reviewDocument",
                {**body, "changes": [{**changes[0], "previous": "过时的原值"}]},
            )
        self.command("dossier.reviewDocument", body)
        self.command("dossier.reviewDocument", body)
        with self.assertRaises(ValueError):
            self.command("dossier.reviewDocument", {**body, "sourceFacts": "试图覆盖"})
        current = self.resident()
        self.assertEqual(current["allergies"], "人工修订乙")
        self.assertEqual(current["risk"], old["risk"])
        self.assertEqual(current["summary"], old["summary"])
        self.assertEqual(self.view()["summary"]["reviewerId"], self.actor["id"])
        self.assertEqual(
            self.view()["reviewChanges"]["allergies"]["before"], old["allergies"]
        )
        self.assertEqual(
            len(
                [
                    a
                    for a in self.data()["archives"]
                    if a.get("documentId") == self.doc["id"]
                ]
            ),
            1,
        )
        self.assertEqual(
            Store(self.path).photo(self.owner, self.doc["id"])[0], FIXTURE.read_bytes()
        )
        with (
            closing(self.store.connect()) as db,
            self.assertRaises(sqlite3.IntegrityError),
        ):
            db.execute("DELETE FROM dossier_document_reviews")

    def test_mismatch_and_failed_engine_retain_original_and_allow_manual_summary(self):
        with patch.object(
            document_ocr, "recognize", side_effect=ValueError("无法识别")
        ):
            self.process()
        self.assertEqual(self.view()["ocr"]["state"], "failed")
        self.assertEqual(
            self.store.photo(self.owner, self.doc["id"])[0], FIXTURE.read_bytes()
        )
        with self.assertRaises(ValueError):
            self.command("dossier.reviewDocument", self.review())
        self.command("dossier.reviewDocument", self.review(method="手工描述"))
        self.assertEqual(self.view()["summary"]["method"], "手工描述")

    def test_mismatched_name_and_unrelated_target_are_denied(self):
        old = self.resident()
        mismatched = {
            **RESULT,
            "candidates": [
                *RESULT["candidates"],
                {"field": "name", "value": "另一人", "line": 2},
            ],
        }
        with patch.object(document_ocr, "recognize", return_value=mismatched) as engine:
            outsider = self.create_user("no-medical", ["care"])
            with self.assertRaises(PermissionError):
                self.command("dossier.ocr", self.arg, outsider)
            with self.assertRaises(ValueError):
                self.command("dossier.ocr", {**self.arg, "residentId": "r002"})
            with (
                closing(self.store.connect()) as db,
                self.assertRaises(PermissionError),
            ):
                document_ocr.detail(db, self.data(outsider)["user"], self.doc["id"])
            engine.assert_not_called()
            self.process()
        with self.assertRaises(ValueError):
            self.command(
                "dossier.reviewDocument",
                self.review(
                    changes=[
                        {
                            "field": "allergies",
                            "value": "原文乙",
                            "previous": old["allergies"],
                            "line": 1,
                        }
                    ]
                ),
            )
        self.assertEqual(self.resident(), old)
        self.command("dossier.reviewDocument", self.review())
        self.assertNotIn(
            self.doc["id"],
            [
                e["id"]
                for e in self.store.dossier_summary_draft(self.owner, self.rid)[
                    "evidence"
                ]
            ],
        )

    def test_same_photo_in_two_charts_reuses_engine_but_not_approval(self):
        with patch.object(document_ocr, "recognize", return_value=RESULT) as engine:
            self.process()
            self.command("dossier.reviewDocument", self.review())
            self.command("dossier.document", {**self.payload, "residentId": "r002"})
            second = next(
                d for d in self.data()["medicalDocuments"] if d["residentId"] == "r002"
            )
            ref = {"residentId": "r002", "documentId": second["id"]}
            self.assertNotEqual(second["id"], self.doc["id"])
            self.assertEqual(second["imageHash"], self.doc["imageHash"])
            with closing(self.store.connect()) as db:
                self.assertEqual(
                    document_ocr.detail(db, self.actor, second["id"])["state"], "queued"
                )
            self.command("dossier.ocr", ref)
            engine.assert_called_once()
            refreshed = next(
                d for d in self.data()["medicalDocuments"] if d["residentId"] == "r002"
            )
            self.assertIsNone(refreshed["summary"])
            self.assertEqual(refreshed["ocr"]["state"], "recognized")

    def test_parallel_jobs_reserve_once_without_holding_workspace_write_lock(self):
        entered = threading.Event()
        release = threading.Event()

        def run(_):
            entered.set()
            self.assertTrue(release.wait(5))
            return RESULT

        with (
            patch.object(document_ocr, "recognize", side_effect=run) as engine,
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            future = executor.submit(self.process)
            try:
                self.assertTrue(entered.wait(2))
                with self.assertRaisesRegex(ValueError, "正在识别"):
                    self.process()
                self.assertIsNone(self.view()["summary"])
                with closing(self.store.connect()) as db, db:
                    db.execute("BEGIN IMMEDIATE")
            finally:
                release.set()
            future.result(timeout=3)
            self.process()
            engine.assert_called_once()

    def test_dynamic_summary_uses_only_signed_sources_and_is_read_only_until_confirmed(
        self,
    ):
        def build():
            return self.store.dossier_summary_draft(self.owner, self.rid)

        baseline = self.resident()["summary"]
        draft = build()
        self.assertFalse(any(e["id"] == self.doc["id"] for e in draft["evidence"]))
        self.command("dossier.reviewDocument", self.review(method="手工描述"))
        after = build()
        self.assertIn("已核对的原文", after["summary"])
        self.assertEqual(self.resident()["summary"], baseline)
        payload = {
            "residentId": self.rid,
            "fingerprint": draft["fingerprint"],
            "summary": "人工核对后的动态摘要",
            "confirmed": True,
        }
        with self.assertRaisesRegex(ValueError, "已经变化"):
            self.command("dossier.signSummary", payload)
        payload.update(fingerprint=after["fingerprint"])
        with self.assertRaises(ValueError):
            self.command("dossier.signSummary", {**payload, "confirmed": False})
        for login, grants in [
            ("reader-only", ["medical"]),
            ("clinic-only", ["clinical"]),
        ]:
            actor = self.create_user(login, grants)
            with self.assertRaises(PermissionError):
                self.store.dossier_summary_draft(actor, self.rid)
            with self.assertRaises(PermissionError):
                self.command("dossier.signSummary", payload, actor)
        self.command("dossier.signSummary", payload)
        self.command("dossier.signSummary", payload)
        self.assertEqual(self.resident()["summary"], payload["summary"])
        rows = [
            r
            for r in self.data()["archives"]
            if r.get("draftFingerprint") == after["fingerprint"]
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["evidence"], after["evidence"])
        self.assertEqual(rows[0]["reviewerId"], self.actor["id"])
        self.assertFalse(
            any(
                e["id"] == self.doc["id"]
                for e in self.store.dossier_summary_draft(self.owner, "r002")[
                    "evidence"
                ]
            )
        )

    def test_real_ocr_reads_synthetic_discharge_photo(self):
        installed = shutil.which("tesseract")
        if installed:
            languages = subprocess.run(
                [installed, "--list-langs"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            ).stdout.splitlines()
            if not {"eng", "chi_sim"}.issubset(languages):
                self.skipTest("本地 OCR 的简中、英文模型尚未同时安装")
        else:
            models = LOCAL.parents[1] / "share/tesseract-ocr/5/tessdata"
            if not LOCAL.is_file() or not all(
                (models / f"{lang}.traineddata").is_file()
                for lang in ("chi_sim", "eng")
            ):
                self.skipTest("本地 OCR 引擎与简中、英文模型尚未安装")
        self.process()
        with closing(self.store.connect()) as db:
            result = document_ocr.detail(db, self.actor, self.doc["id"])
        self.assertEqual(result["state"], "recognized", result.get("error"))
        self.assertGreaterEqual(len(result["lines"]), 4)
        self.assertTrue(
            any(
                c["field"] == "name" and c["value"] == self.resident()["name"]
                for c in result["candidates"]
            )
        )
        self.assertTrue(
            all(
                len(line["box"]) == 4 and 0 <= line["confidence"] <= 100
                for line in result["lines"]
            )
        )
        self.assertIsNone(self.view()["summary"])


if __name__ == "__main__":
    unittest.main()
