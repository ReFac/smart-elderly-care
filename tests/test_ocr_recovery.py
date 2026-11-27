"""Chinese CT report recovery keeps the submitted image and meters actual requests."""

from contextlib import closing
from datetime import datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from PIL import Image, ImageDraw

from platform_core import document_ocr, provider
from platform_core.provider import media
from platform_core.store import Store, TIMEZONE


REPORT = "胸部CT检查报告\n检查编号：CT-2718\n检查日期：2026-11-25\n"
MISSING_SIZE = REPORT + "检查所见：右肺上叶见结节。\n影像结论：肺结节。"
COMPLETE = REPORT + "检查所见：右肺上叶见结节，约 7.42 mm。\n影像结论：肺结节。"


def receipt(identifier, text, finish="stop"):
    return {
        "id": identifier,
        "object": "ocr.result",
        "purpose": "text_recognition",
        "page_count": 1,
        "pages": [{"index": 0, "finish_reason": finish, "text": text}],
    }


def report_image(revision):
    image = Image.new("RGB", (480, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.text((30, 40), "CT report " + revision, fill="black")
    draw.text((30, 120), "Finding: 7.42 mm", fill="black")
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


class OcrRecoveryTests(TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        password = "synthetic-ocr-recovery-account"
        self.store = Store(
            Path(folder.name) / "workspace.db",
            now=lambda: datetime(2026, 11, 27, 12, tzinfo=TIMEZONE),
            initial_owner_password=password,
        )
        self.owner, _ = self.store.login("owner", password)
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "CT复测模拟套餐", 5000, "2026-12-01", self.store.now())
            self.plan = provider.latest(db)["id"]
        self.allow(15)

    def allow(self, pages):
        with closing(self.store.connect()) as db, db:
            media.grant(db, self.plan, "ocr", pages)

    def recognize(self, raw):
        return document_ocr.recognize(
            self.store, self.owner, raw, self.store.actor, feature="assistant.documentOcr"
        )

    def ledger(self):
        with closing(self.store.connect()) as db:
            return db.execute(
                "SELECT state,reserved,charged,vendor_id,original FROM media_usage"
                " WHERE kind='ocr' ORDER BY rowid"
            ).fetchall()

    def test_blank_truncated_and_missing_size_are_recovered_once(self):
        for reason, first_text, finish in (
            ("blank", "", "stop"),
            ("truncated", REPORT + "检查所见：右肺", "length"),
            ("missing-size", MISSING_SIZE, "stop"),
        ):
            with self.subTest(reason=reason):
                raw = report_image(reason)
                first = receipt(reason + "-first", first_text, finish)
                second = receipt(reason + "-second", COMPLETE)
                with (
                    patch.object(media, "read_key", return_value="simulated-provider-key"),
                    patch.object(media, "invoke", side_effect=[first, second]) as send,
                ):
                    result = self.recognize(raw)
                    self.assertEqual(self.recognize(raw), result)
                self.assertEqual(send.call_count, 2)
                self.assertEqual(send.call_args_list[0].args[1], raw)
                self.assertNotEqual(send.call_args_list[1].args[1], raw)
                with Image.open(BytesIO(send.call_args_list[1].args[1])) as derived:
                    derived.verify()
                self.assertIs(result.get("recoveryUsed"), True)
                self.assertEqual(result["pages"], [{"page": 1, "state": "complete"}])
                self.assertIn("约 7.42 mm", "\n".join(line["text"] for line in result["lines"]))
                first_call, recovery_call = self.ledger()[-2:]
                self.assertEqual(tuple(first_call), ("complete", 1, 1, first["id"], raw))
                self.assertEqual(tuple(recovery_call)[:4], ("complete", 1, 1, second["id"]))
                self.assertIsNone(recovery_call["original"])

    def test_recovery_does_not_replace_an_existing_check_number(self):
        raw = report_image("conflicting-number")
        recovery = COMPLETE.replace("CT-2718", "CT-2719")
        for reason, state in (("stop", "complete"), ("length", "partial")):
            with self.subTest(reason=reason):
                original = raw if reason == "stop" else report_image("cutoff-number-conflict")
                with (
                    patch.object(media, "read_key", return_value="simulated-provider-key"),
                    patch.object(media, "invoke", side_effect=[
                        receipt("original-number-" + reason, MISSING_SIZE, reason),
                        receipt("different-number-" + reason, recovery),
                    ]) as send,
                ):
                    result = self.recognize(original)
                    self.assertEqual(self.recognize(original), result)
                self.assertEqual(send.call_count, 2)
                self.assertFalse(result.get("recoveryUsed"))
                self.assertEqual(result["pages"][0]["state"], state)
                text = "\n".join(line["text"] for line in result["lines"])
                self.assertNotIn("CT-2719", text)
                self.assertNotIn("7.42", text)
                if reason == "stop":
                    self.assertIn("CT-2718", text)

    def test_complete_and_negative_reports_use_one_request(self):
        negative = REPORT + "检查所见：未见肺结节。\n影像结论：未见肺结节。"
        for name, value in (("complete", COMPLETE), ("negative", negative)):
            with (
                self.subTest(name=name),
                patch.object(media, "read_key", return_value="simulated-provider-key"),
                patch.object(media, "invoke", return_value=receipt(name, value)) as send,
            ):
                result = self.recognize(report_image(name))
                send.assert_called_once()
                self.assertFalse(result.get("recoveryUsed"))
                self.assertFalse(result["manualReportReview"])

    def test_first_receipt_remains_available_when_only_one_page_is_available(self):
        self.allow(1)
        raw = report_image("only-one-page")
        with (
            patch.object(media, "read_key", return_value="simulated-provider-key"),
            patch.object(media, "invoke", return_value=receipt("only-page", "")) as send,
        ):
            first = self.recognize(raw)
            self.assertEqual(self.recognize(raw), first)
        send.assert_called_once()
        self.assertEqual(first["pages"], [{"page": 1, "state": "blank"}])
        self.assertFalse(first.get("recoveryUsed"))
        row, = self.ledger()
        self.assertEqual(tuple(row), ("complete", 1, 1, "only-page", raw))

    def test_rejected_recovery_is_not_resubmitted_when_viewed_again(self):
        raw = report_image("rejected-recovery")
        with (
            patch.object(media, "read_key", return_value="simulated-provider-key"),
            patch.object(media, "invoke", side_effect=[
                receipt("original-blank", ""), media.MediaError("恢复稿未被供应商接受"),
            ]) as send,
        ):
            result = self.recognize(raw)
            self.assertEqual(self.recognize(raw), result)
        self.assertEqual(send.call_count, 2)
        self.assertEqual(result["pages"][0]["state"], "blank")
        first, second = self.ledger()
        self.assertEqual(tuple(first), ("complete", 1, 1, "original-blank", raw))
        self.assertEqual(tuple(second)[:4], ("failed", 1, 0, None))

    def test_uncertain_first_delivery_reserves_but_never_retries(self):
        raw = report_image("uncertain-delivery")
        with (
            patch.object(media, "read_key", return_value="simulated-provider-key"),
            patch.object(media, "invoke", side_effect=media.MediaError("无法确认送达", uncertain=True)) as send,
        ):
            with self.assertRaisesRegex(media.MediaError, "无法确认送达"):
                self.recognize(raw)
            with self.assertRaisesRegex(ValueError, "待平台核对"):
                self.recognize(raw)
        send.assert_called_once()
        row, = self.ledger()
        self.assertEqual(tuple(row), ("uncertain", 1, 0, None, raw))
