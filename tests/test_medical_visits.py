"""A signed visit binds all originals, the encounter, its resident and its reviewer."""

import base64
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import zlib

from platform_core import medical_visits as visits, provider
from platform_core.provider import media
from platform_core.store import Store, TIMEZONE, Conflict

PASSWORD = "synthetic-visit-test"
RID = "r001"


def fixture_visit(store, token, resident_id, event_date):
    draft = visits.preview(store, token, resident_id, {
        "revision": store.version(token)["revision"],
        "requestId": "signed-fixture-" + uuid4().hex,
        "mode": "manual",
        "fields": {"eventDate": event_date, "reason": "测试用就诊记录"},
    })
    store.execute(
        "dossier.confirmVisit", {
            "confirmed": True, "fields": draft["fields"], "draftId": draft["draftId"],
            "residentId": resident_id,
        },
        draft["revision"], token,
    )
    return draft["draftId"]


def png(rgb):
    def chunk(key, data):
        return (
            len(data).to_bytes(4, "big")
            + key
            + data
            + zlib.crc32(key + data).to_bytes(4, "big")
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", bytes.fromhex("00000001000000010802000000"))
        + chunk(b"IDAT", zlib.compress(b"\0" + bytes(rgb)))
        + chunk(b"IEND", b"")
    )


class MedicalVisitTests(TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(
            Path(tmp.name) / "visit.db",
            now=lambda: datetime(2026, 11, 24, 9, tzinfo=TIMEZONE),
            initial_owner_password=PASSWORD,
        )
        self.token = self.store.login("owner", PASSWORD)[0]
        self.raw = png((24, 10, 25))
        self.note = self.file(self.raw)
        self.ct = self.file(png((43, 53, 33)), "CT影像")
        self.today = "2026-11-21"
        self.fields = {
            "eventDate": self.today,
            "diagnosis": "登记医生报告结论",
            "historyMeds": "既往用药甲",
            "prescriptions": "本次处方乙",
            "orders": "遵该次医嘱",
        }
        self.store.snapshot(self.token)

    def file(self, raw, category="就诊记录"):
        return {
            "category": category,
            "filename": "随诊.png",
            "mime": "image/png",
            "imageBase64": base64.b64encode(raw).decode(),
        }

    def rev(self):
        return self.store.version(self.token)["revision"]

    def body(self, **extras):
        return {
            "revision": self.rev(),
            "requestId": "one-visit",
            "attachments": [self.note, self.ct],
            "mode": "manual",
            "fields": self.fields,
            **extras,
        }

    def sign(self, draft, token=None, **overrides):
        fields = {
            "confirmed": True,
            "fields": draft["fields"],
            "draftId": draft["draftId"],
            "residentId": RID,
            **overrides,
        }
        return self.store.execute(
            "dossier.confirmVisit", fields, self.rev(), token or self.token
        )

    def data(self, token=None):
        return self.store.snapshot(token or self.token)["data"]

    def test_documents_are_supplements_of_a_single_signed_encounter(self):
        first = fixture_visit(self.store, self.token, RID, self.today)
        second = fixture_visit(self.store, self.token, RID, "2026-11-20")
        other = fixture_visit(self.store, self.token, "r002", self.today)
        document = {
            "residentId": RID, "requestId": "linked-doc", "eventDate": self.today,
            "category": "CT", "source": "测试医院", "description": "核对已存档影像",
            "imageBase64": base64.b64encode(self.raw).decode(),
        }
        with self.assertRaisesRegex(ValueError, "请先选择或新建"):
            self.store.execute("dossier.document", document, self.rev(), self.token)
        with self.assertRaises(FileNotFoundError):
            self.store.execute("dossier.document", {**document, "visitId": other}, self.rev(), self.token)
        self.assertEqual(self.data()["medicalDocuments"], [])
        signed = next(row for row in self.data()["medicalVisits"] if row["id"] == first)
        for attempt in range(2):
            self.store.execute("dossier.document", {
                **document, "visitId": first, "requestId": f"retry-{attempt}",
            }, self.rev(), self.token)
        saved, = self.data()["medicalDocuments"]
        self.assertEqual(saved["visitId"], first)
        self.assertEqual(self.store.photo(self.token, saved["id"]), (self.raw, "image/png"))
        with self.assertRaisesRegex(ValueError, "已归入另一条"):
            self.store.execute("dossier.linkVisitDocument", {
                "residentId": RID, "visitId": second, "documentId": saved["id"],
            }, self.rev(), self.token)
        self.assertEqual(next(row for row in self.data()["medicalVisits"] if row["id"] == first), signed)

    def test_explicit_legacy_link_keeps_original_and_resident_boundary(self):
        from platform_core import dossier
        from platform_core.backups import exchange

        first = fixture_visit(self.store, self.token, RID, self.today)
        other = fixture_visit(self.store, self.token, "r002", self.today)
        import_doc = {
            "residentId": RID, "requestId": "legacy-doc", "eventDate": self.today,
            "category": "CT", "source": "历史测试医院", "description": "旧系统文书",
            "imageBase64": base64.b64encode(self.raw).decode(),
        }
        with closing(self.store.connect()) as db, db:
            state = json.loads(db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0])
            actor = self.store.actor(db, self.token)
            dossier.archive_document(db, state, import_doc, actor, self.today)
        before, = self.data()["medicalDocuments"]
        self.assertNotIn("visitId", before)
        self.store.backups.capture()
        point = self.store.backups.status(self.token)["points"][0]["id"]
        fields = {"residentId": RID, "documentId": before["id"]}
        with self.assertRaises(FileNotFoundError):
            self.store.execute("dossier.linkVisitDocument", {**fields, "visitId": other}, self.rev(), self.token)
        self.store.execute("dossier.linkVisitDocument", {**fields, "visitId": first}, self.rev(), self.token)
        self.assertEqual(self.data()["medicalDocuments"], [{**before, "visitId": first}])
        self.assertEqual(self.store.photo(self.token, before["id"]), (self.raw, "image/png"))
        preview = exchange.preview_point(self.store.backups, self.token, point)
        self.assertIn("医疗文书与就诊病例关联", preview["blockers"])

    def test_manual_stages_originals_then_confirms_once_with_distinct_medication_history(
        self,
    ):
        with (
            patch.object(media, "invoke", side_effect=AssertionError),
            patch("platform_core.provider.deepseek.send", side_effect=AssertionError),
        ):
            draft = visits.preview(self.store, self.token, RID, self.body())
            ids = [a["id"] for a in draft["attachments"]]
            self.assertNotEqual(*ids)
            self.assertEqual(self.data()["medicalVisits"], [])
            with self.assertRaises(FileNotFoundError):
                visits.original(self.store, self.token, ids[0])
            with self.assertRaises(ValueError):
                self.sign(draft, residentId="r002")
            with self.assertRaises(ValueError):
                self.sign(draft, confirmed=False)
            self.sign(draft)
            self.sign(draft)
            self.assertEqual(len(self.data()["medicalVisits"]), 1)
            record = self.data()["medicalVisits"][0]
            self.assertEqual(record["fields"]["historyMeds"], "既往用药甲")
            self.assertEqual(record["fields"]["prescriptions"], "本次处方乙")
            self.assertEqual(
                visits.original(self.store, self.token, ids[0]), (self.raw, "image/png")
            )
            self.assertEqual(
                [a["category"] for a in record["attachments"]], ["就诊记录", "CT影像"]
            )
            with self.assertRaisesRegex(ValueError, "已.*签认"):
                visits.preview(
                    self.store, self.token, RID, self.body(requestId="different")
                )
            with self.assertRaises(ValueError):
                self.sign(
                    draft, fields={**draft["fields"], "orders": "试图覆盖签认内容"}
                )
            no_image = visits.preview(
                self.store,
                self.token,
                RID,
                self.body(requestId="manual-text", attachments=[]),
            )
            self.sign(no_image)

    def account(self, username, permissions, campus=None):
        p = {
            "kind": "staff",
            "role": "自定义",
            "displayName": "记录员工",
            "username": username,
            "password": PASSWORD,
            "permissions": permissions,
        }
        if campus:
            p["campusId"] = campus
        self.store.execute("access.create", p, self.rev(), self.token)
        return self.store.login(username, PASSWORD)[0]

    def test_supplements_append_to_original_visit_and_respect_id_and_date(self):
        root = visits.preview(self.store, self.token, RID, self.body())
        self.sign(root)
        before = self.data()["medicalVisits"][0]
        extra = self.file(png((14, 3, 128)), "检查报告")
        explicit = self.body(
            mode="manual",
            requestId="visit-supplement",
            visitId=before["id"],
            fields={},
            attachments=[extra],
        )
        with self.assertRaises(FileNotFoundError):
            visits.preview(self.store, self.token, "r002", explicit)
        with self.assertRaisesRegex(ValueError, "原件"):
            visits.preview(
                self.store, self.token, RID, {**explicit, "attachments": [self.note]}
            )
        draft = visits.preview(self.store, self.token, RID, explicit)
        self.assertEqual(draft["fixedDate"], before["fields"]["eventDate"])
        self.assertEqual(draft["parentVisitId"], before["id"])
        with self.assertRaisesRegex(ValueError, "日期"):
            self.sign(draft, fields={"eventDate": "2026-11-20", "tests": "不应签入"})
        self.sign(draft, fields={**draft["fields"], "tests": "补充检查结果"})
        self.sign(draft, fields={**draft["fields"], "tests": "补充检查结果"})
        rows = self.data()["medicalVisits"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(next(row for row in rows if row["id"] == before["id"]), before)
        latest = next(row for row in rows if row.get("parentVisitId") == before["id"])
        self.assertEqual(latest["fields"]["tests"], "补充检查结果")
        self.assertEqual(latest["parentVisitId"], before["id"])
        self.assertEqual(
            visits.original(self.store, self.token, latest["attachments"][0]["id"])[0],
            png((14, 3, 128)),
        )
        with self.assertRaises(FileNotFoundError):
            visits.preview(
                self.store,
                self.token,
                RID,
                {**explicit, "requestId": "nested", "visitId": latest["id"]},
            )

    def test_new_wizard_requires_date_and_detects_mismatched_ocr_date(self):
        missing = self.body(mode="ai", fields={}, consent=True, visitId="")
        with self.assertRaises(ValueError):
            visits.preview(self.store, self.token, RID, missing)
        self.metering()
        ocr, classify = self.cloud(
            "门诊日期：2026年11月20日\n医院：平顶山市第一人民医院",
            "影像片",
            classify={"facility": [2]},
        )
        draft = visits.preview(
            self.store,
            self.token,
            RID,
            {**missing, "fields": {"eventDate": "2026-11-21"}},
        )
        self.assertTrue(draft["identityConflict"])
        self.assertTrue(any("就诊日期" in item for item in draft["warnings"]))
        self.assertEqual(ocr.call_count, 2)
        classify.assert_not_called()
        with self.assertRaises(ValueError):
            self.sign(draft)
        self.assertEqual(self.data()["medicalVisits"], [])

    def test_draft_ownership_medical_and_campus_scope_rechecked_at_read_and_sign(self):
        rights = ["medical", "medical.write", "clinical"]
        staff = self.account("other-clinician", rights)
        readonly = self.account("view-only", ["medical"])
        self.store.execute(
            "facility.addCampus", {"name": "西院"}, self.rev(), self.token
        )
        foreign = self.store.facility_resource(self.token, "directory")["campuses"][-1][
            "id"
        ]
        outsider = self.account("branch-clinician", rights, foreign)
        draft = visits.preview(self.store, self.token, RID, self.body())
        with self.assertRaises(ValueError):
            self.sign(draft, staff)
        for token in (readonly, outsider):
            with self.assertRaises(PermissionError):
                visits.preview(self.store, token, RID, self.body())
        self.sign(draft)
        aid = draft["attachments"][0]["id"]
        self.assertEqual(self.data(outsider)["medicalVisits"], [])
        with self.assertRaises(PermissionError):
            visits.original(self.store, outsider, aid)
        self.assertEqual(visits.original(self.store, readonly, aid)[0], self.raw)

    def test_malformed_duplicate_group_stale_input_leave_no_chart_or_file(self):
        params = self.body()
        cases = (
            {"revision": params["revision"] + 1},
            {"attachments": [self.note, self.note]},
            {"attachments": [self.note] * 13},
            {"attachments": [{**self.note, "residentId": "r002"}]},
            {"mode": "ai", "consent": False},
            {"attachments": [{**self.note, "imageBase64": "!!"}]},
        )
        for change in cases:
            with (
                self.subTest(change=list(change)),
                self.assertRaises((ValueError, Conflict)),
            ):
                visits.preview(self.store, self.token, RID, {**params, **change})
        with closing(self.store.connect()) as db:
            self.assertEqual(
                db.execute("SELECT count(*) FROM dossier_visit_originals").fetchone()[
                    0
                ],
                0,
            )
        draft = visits.preview(self.store, self.token, RID, params)
        with self.assertRaises(ValueError):
            visits.preview(
                self.store, self.token, RID, {**params, "attachments": [self.ct]}
            )
        with self.assertRaises(ValueError):
            self.sign(draft, fields={"eventDate": "2060-01-01", "reason": "未来"})
        self.assertEqual(self.data()["medicalVisits"], [])

    def metering(self):
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "synthetic", 180000, "2026-12-01", self.store.now())
            plan = provider.latest(db)
            media.grant(db, plan["id"], "ocr", 100)

    def cloud(self, *texts, classify):
        responses = [
            {
                "id": "receipt" + str(i),
                "purpose": "text_recognition",
                "object": "ocr.result",
                "page_count": 1,
                "pages": [{"index": 0, "text": text, "finish_reason": "stop"}],
            }
            for i, text in enumerate(texts)
        ]
        self.addCleanup(patch.stopall)
        patch.dict("os.environ", {"DEEPSEEK_API_KEY": "fixture-only"}).start()
        ocr = patch.object(
            media,
            "invoke",
            side_effect=lambda kind, raw, *_: responses[0 if raw == self.raw else 1],
        ).start()
        chat = patch(
            "platform_core.provider.deepseek.send",
            side_effect=lambda *args, **kw: {
                "usage": {"total_tokens": 30},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(classify, ensure_ascii=False)
                        },
                    }
                ],
            },
        ).start()
        return ocr, chat

    def test_metered_agent_uses_original_lines_and_pages_never_derives_scan_findings(
        self,
    ):
        self.metering()
        name = next(r["name"] for r in self.data()["residents"] if r["id"] == RID)
        ocr, chat = self.cloud(
            "姓名："
            + name
            + " 性别：女 年龄：76\n就诊日期：2026年11月20日\n既往药物：原文甲\n处方：原文乙\n医嘱：原文丙",
            "图像中的文字不构成影像诊断",
            classify={
                "eventDate": [1],
                "historyMeds": [2],
                "prescriptions": [3],
                "orders": [4],
            },
        )
        req = self.body(mode="ai", fields={}, consent=True)
        draft = visits.preview(self.store, self.token, RID, req)
        self.assertEqual(draft, visits.preview(self.store, self.token, RID, req))
        self.assertEqual((ocr.call_count, chat.call_count), (2, 1))
        self.assertNotIn("图像中的文字", repr(chat.call_args))
        self.assertNotIn(name, repr(chat.call_args))
        self.assertFalse(draft["identityConflict"])
        self.assertEqual(draft["fields"]["eventDate"], "2026-11-20")
        self.assertEqual(draft["fields"]["tests"], "")
        quote = draft["sourceRefs"]["prescriptions"][0]
        self.assertEqual(
            (quote["attachmentId"], quote["page"], quote["line"]),
            (draft["attachments"][0]["id"], 1, 4),
        )
        self.assertTrue(any("影像" in s for s in draft["warnings"]))
        self.sign(
            draft, fields={**draft["fields"], "reason": "按原件核实录入的就诊原因"}
        )
        self.assertEqual(
            self.data()["medicalVisits"][0]["fields"]["prescriptions"], "处方：原文乙"
        )
        with closing(self.store.connect()) as db:
            self.assertEqual(media.overview(db)["ocr"]["used"], 2)

    def test_cached_ocr_names_with_other_fields_keep_the_patient_safety_check(self):
        name = next(r["name"] for r in self.data()["residents"] if r["id"] == RID)
        seen = (name, "确实是另一人", name + "；患者姓名：确实是另一人")
        for index, observed in enumerate(seen):
            inline = observed + " 性别：女 年龄：76"
            cached = {
                "state": "recognized",
                "pages": [{"page": 1, "state": "complete"}, {"page": 2, "state": "partial"}],
                "lines": [{"page": 2, "line": 1, "text": "患者姓名：" + inline}],
                "candidates": [{"field": "name", "page": 2, "line": 1, "value": inline}],
            }
            with patch.object(visits.visit_extraction.document_ocr, "recognize", return_value=cached):
                result = visits.preview(self.store, self.token, RID, self.body(
                    requestId=f"cached-inline-{index}", mode="ai", consent=True,
                ))
            self.assertEqual(result["identityConflict"], index != 0)

    def test_mixed_patient_or_encounter_blocked_even_if_client_edits_fields(self):
        self.metering()
        _, chat = self.cloud(
            "患者姓名：其他患者\n就诊日期：2026-11-21",
            "就诊日期：2026-11-13",
            classify={},
        )
        draft = visits.preview(
            self.store, self.token, RID, self.body(mode="ai", consent=True)
        )
        self.assertTrue(draft["identityConflict"])
        self.assertEqual(chat.call_count, 0)
        with self.assertRaises(ValueError):
            self.sign(draft, fields=self.fields)
        self.assertEqual(self.data()["medicalVisits"], [])

    def test_concurrent_operators_share_one_metered_generation_and_separate_drafts(
        self,
    ):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event

        self.metering()
        clinician = self.account(
            "other-reviewer", ["medical", "medical.write", "clinical"]
        )
        arrived, release = Event(), Event()
        args = self.body(mode="ai", consent=True, fields={})
        other = {
            **args,
            "requestId": "retry-new-tab",
            "attachments": list(reversed(args["attachments"])),
        }
        ocr, chat = self.cloud("既往记录甲", "影像片", classify={"reason": [1]})
        reply = chat.side_effect

        def delayed(*a, **k):
            arrived.set()
            if not release.wait(5):
                raise TimeoutError
            return reply(*a, **k)

        chat.side_effect = delayed
        with ThreadPoolExecutor(max_workers=1) as worker:
            first = worker.submit(visits.preview, self.store, self.token, RID, args)
            self.assertTrue(arrived.wait(5))
            try:
                with self.assertRaisesRegex(ValueError, "正在处理"):
                    visits.preview(self.store, clinician, RID, other)
            finally:
                release.set()
            draft = first.result()
        second = visits.preview(self.store, clinician, RID, other)
        self.assertEqual(second["fields"], draft["fields"])
        self.assertNotEqual(second["draftId"], draft["draftId"])
        self.assertEqual(second["attachments"], list(reversed(draft["attachments"])))
        self.assertEqual((ocr.call_count, chat.call_count), (2, 1))

    def test_invalid_model_reply_retains_originals_and_does_not_issue_a_second_call(
        self,
    ):
        self.metering()
        ocr, chat = self.cloud("既往记录甲", "影像片", classify={"orders": [999]})
        args = self.body(mode="ai", consent=True, fields={})
        with self.assertRaisesRegex(ValueError, "未能完成"):
            visits.preview(self.store, self.token, RID, args)
        with self.assertRaisesRegex(ValueError, "手工"):
            visits.preview(
                self.store, self.token, RID, {**args, "requestId": "another"}
            )
        self.assertEqual((ocr.call_count, chat.call_count), (2, 1))
        self.assertEqual(self.data()["medicalVisits"], [])
        with closing(self.store.connect()) as db:
            self.assertEqual(
                db.execute("SELECT count(*) FROM dossier_visit_originals").fetchone()[
                    0
                ],
                2,
            )
