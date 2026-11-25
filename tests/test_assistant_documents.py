"""An assistant attachment chooses a destination; only the destination form can commit it."""

from contextlib import closing
from datetime import datetime
from email.message import Message
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from platform_core import provider, resident_credentials, staff_resume
from platform_core.agents import document_intake
from platform_core.provider import media
from platform_core.store import Store, TIMEZONE
from test_medical_visits import png
from test_pdf_ocr import synthetic_pdf
from server import Handler


class AssistantDocuments(TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(Path(tmp.name) / "workspace.db", now=lambda: datetime(2026, 11, 25, tzinfo=TIMEZONE),
                           initial_owner_password="test-original-only")
        self.owner = self.store.login("owner", "test-original-only")[0]
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "synthetic", 140000, "2026-12-01", self.store.now())
            media.grant(db, provider.latest(db)["id"], "ocr", 5)
        self.raw = png((77, 50, 32))

    def preview(self, token=None):
        return document_intake.preview(self.store, token or self.owner, self.raw, "image/png")

    def test_resume_original_and_category_receipts_are_reused_without_creating_an_account(self):
        reply = {"id": "test-ocr", "purpose": "text_recognition", "object": "ocr.result",
                 "page_count": 1, "pages": [{"index": 0, "finish_reason": "stop",
                 "text": "应聘简历\n姓名：张小明\n手机号：13900001025\n应聘岗位：护士"}]}
        output = {"usage": {"total_tokens": 30}, "choices": [{"finish_reason": "stop",
                  "message": {"content": json.dumps({"category": "员工简历"}, ensure_ascii=False)}}]}
        before = self.store.snapshot(self.owner)["data"]["accounts"]
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "local-fixture"}), \
             patch.object(media, "invoke", return_value=reply) as ocr, \
             patch("platform_core.provider.deepseek.send", return_value=output) as classify:
            decision = self.preview()
            self.assertEqual(decision, self.preview())
            self.assertEqual(staff_resume.preview(self.store, self.owner, self.raw), decision["resume"])
        self.assertEqual((ocr.call_count, classify.call_count), (1, 1))
        self.assertNotIn("13900001025", repr(classify.call_args))
        self.assertNotIn("张小明", repr(classify.call_args))
        self.assertEqual(decision["category"], "员工简历")
        self.assertEqual(decision["resume"]["fields"]["displayName"]["value"], "张小明")
        self.assertNotIn("role", decision["resume"]["fields"])
        self.assertEqual(self.store.snapshot(self.owner)["data"]["accounts"], before)
        with closing(self.store.connect()) as db:
            receipt = db.execute("SELECT feature,original,charged FROM media_usage WHERE kind='ocr'").fetchone()
            self.assertEqual(tuple(receipt), ("assistant.documentOcr", self.raw, 1))
            self.assertEqual(db.execute("SELECT count(*) FROM api_usage WHERE feature='assistant.documentClassify'").fetchone()[0], 1)

    def test_photograph_without_text_uses_one_visual_call_and_never_invents_form_fields(self):
        reply = {"id": "photo-ocr", "purpose": "text_recognition", "object": "ocr.result", "page_count": 1,
                 "pages": [{"index": 0, "finish_reason": "stop", "text": ""}]}
        output = {"usage": {"total_tokens": 220}, "choices": [{"finish_reason": "stop",
                  "message": {"content": json.dumps({"category": "CT影像"}, ensure_ascii=False)}}]}
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "local-fixture", "NH_CHAT_PROVIDER": "deepseek"}), \
             patch.object(media, "invoke", return_value=reply) as ocr, \
             patch("platform_core.provider.deepseek.send", return_value=output) as classify:
            result = self.preview()
            self.assertEqual(result, self.preview())
        self.assertEqual((ocr.call_count, classify.call_count), (1, 1))
        part = classify.call_args.args[1]["messages"][-1]["content"][-1]["image_url"]
        self.assertTrue(part["url"].startswith("data:image/png;base64,"))
        self.assertEqual(part["detail"], "low")
        self.assertEqual(result["category"], "CT影像")
        self.assertEqual(result["excerpt"], "")
        self.assertFalse(result["resume"]["fields"])

    def test_unknowns_are_reviewable_and_roles_are_rechecked(self):
        blocked = {"kind": "family", "id": "bound", "permissions": ["assistants"]}
        worker = {"kind": "staff", "id": "worker", "permissions": ["assistants"]}
        with patch.object(self.store, "actor", return_value=blocked), self.assertRaises(PermissionError):
            document_intake.check(self.store, "session")
        with self.assertRaises(ValueError):
            document_intake.preview(self.store, self.owner, self.raw, "application/pdf")
        sample = {"pageCount": 1, "lines": [{"page": 1, "line": 1, "text": "营养品库存盘点"}],
                  "pages": [{"page": 1, "state": "complete"}]}
        with patch.object(self.store, "actor", return_value=worker), \
             patch.object(document_intake.document_ocr, "recognize", return_value=sample), \
             patch.object(document_intake.generation, "generate", side_effect=ValueError):
            result = self.preview("session")
        self.assertEqual(result["category"], "其他")
        self.assertIn("库存盘点", result["excerpt"])
        self.assertNotIn("resume", result)
        self.assertIn("请选择", result["note"])

    def test_contract_fields_require_one_unambiguous_value_from_labelled_text(self):
        samples = ["合同编号：ZH-25", "签订日期：2026年11月22日", "合同开始日期：2026年12月1日",
                   "合同结束日期：2027-12-01", "合同终止日期：2028-12-01", "打印日期：2029-01-01"]
        fields = document_intake._contract_fields([{"text": t} for t in samples])
        self.assertEqual(fields, {"number": "ZH-25", "signedOn": "2026-11-22", "startsOn": "2026-12-01"})

    def test_identity_fields_do_not_escape_to_chat_or_classifier(self):
        number = "11010519491231002X"
        strings = ["居民身份证", "姓名 张三 性别 男 民族 汉", "出生 1949年12月31日", "公民身份号码", number]
        sample = {"pageCount": 1, "pages": [{"page": 1, "state": "complete"}],
                  "lines": [{"text": text, "page": 1, "line": i} for i, text in enumerate(strings)]}
        with patch.object(document_intake.document_ocr, "recognize", return_value=sample), \
             patch.object(document_intake.generation, "generate", return_value={"category": "身份证正面"}) as classify:
            result = self.preview()
            self.assertEqual(result["material"]["fields"], {"name":"张三", "birthDate":"1949-12-31", "idNumber":number})
            self.assertEqual(result["excerpt"], "")
            self.assertNotIn(number, repr(classify.call_args))
            self.assertNotIn("张三", repr(classify.call_args))
            with patch.object(self.store, "actor", return_value={"kind":"staff","id":"w","permissions":["assistants"]}):
                self.assertNotIn("material", self.preview())
        sample["lines"].append({"text":"出生日期：1950年1月1日", "page":1})
        self.assertIn("birthDate", resident_credentials.suggestions(sample["lines"])["ambiguous"])
        back = resident_credentials.suggestions([{"text": v, "page":1} for v in ("签发机关 测试公安局","有效期限 2020.01.01-长期")])
        self.assertEqual(back["fields"], {"authority":"测试公安局","validity":"2020.01.01-长期"})

    def test_pdf_preview_renders_requested_local_page_and_checks_access(self):
        handler = Handler.__new__(Handler)
        handler.store = self.store
        handler.token = lambda: self.owner
        handler.headers = Message()
        handler.headers["Content-Type"] = "application/pdf"
        handler.read_body = Mock(return_value=synthetic_pdf(2))
        handler.respond = Mock()
        handler.write_resource("/api/assistant/documents/pages/2")
        status, png_bytes, mime = handler.respond.call_args.args
        self.assertEqual((status, mime, handler.respond.call_args.kwargs), (200, "image/png", {"page_count": 2}))
        self.assertTrue(png_bytes.startswith(b"\x89PNG"))
        with self.assertRaisesRegex(ValueError, "页码"):
            handler.write_resource("/api/assistant/documents/pages/3")
        with patch.object(self.store, "actor", return_value={"kind": "family", "permissions":[]}), self.assertRaises(PermissionError):
            handler.write_resource("/api/assistant/documents/pages/1")
        self.assertEqual(handler.read_body.call_count, 2)
