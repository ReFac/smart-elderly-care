"""A multi-page original has one upload, one page reservation and page-specific evidence."""

import base64
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from platform_core import document_ocr, pdf_original, provider
from platform_core.provider import media
from platform_core.store import Store
from provider_fixture import isolate_credentials


def synthetic_pdf(count):
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Count {count} /Kids [".encode()
        + b" ".join(f"{4 + 2 * i} 0 R".encode() for i in range(count))
        + b"] >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i in range(count):
        stream = f"BT /F1 18 Tf 48 700 Td (Synthetic page {i + 1}) Tj ET".encode()
        objects.extend(
            [
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                + f"/Contents {5 + 2 * i} 0 R /Resources << /Font << /F1 3 0 R >> >> >>".encode(),
                f"<< /Length {len(stream)} >>\nstream\n".encode()
                + stream
                + b"\nendstream",
            ]
        )
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for num, body in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{num} 0 obj\n".encode() + body + b"\nendobj\n")
    start = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    )
    return bytes(data)


class PdfTests(unittest.TestCase):
    def test_invalid_pdf_tools_and_receipts_are_reported(self):
        with patch("platform_core.pdf_original.shutil.which", return_value=None):
            with self.assertRaisesRegex(ValueError, "poppler-utils"):
                pdf_original.pages(synthetic_pdf(1))
        receipt = {
            "id": "sample",
            "object": "ocr.result",
            "purpose": "text_recognition",
            "page_count": 2,
            "pages": [{"index": 0, "text": "one", "finish_reason": "stop"}] * 2,
        }
        with self.assertRaisesRegex(ValueError, "页码"):
            document_ocr.parse_result(receipt, 1000, 1000, 2)
        with self.assertRaisesRegex(ValueError, "页数"):
            document_ocr.parse_result(receipt, 1000, 1000, 6)

    def test_archival_pages_quota_and_last_page_evidence(self):
        raw = synthetic_pdf(6)
        with tempfile.TemporaryDirectory() as location:
            isolate_credentials(self, location)
            store = Store(
                Path(location) / "sample.db", initial_owner_password="SyntheticPass-123"
            )
            owner, _ = store.login("owner", "SyntheticPass-123")

            def command(action, payload):
                return store.execute(
                    action, payload, store.version(owner)["revision"], owner
                )

            self.assertEqual(store.inspect_pdf(owner, "r001", raw), {"pageCount": 6})
            self.assertTrue(pdf_original.render_page(raw, 6).startswith(b"\x89PNG"))
            with self.assertRaises(ValueError):
                pdf_original.pages(b"%PDF-1.5\ninvalid")
            command(
                "dossier.document",
                {
                    "residentId": "r001",
                    "requestId": "six-pages",
                    "source": "模拟文件",
                    "category": "出院小结",
                    "eventDate": store.now().date().isoformat(),
                    "method": document_ocr.METHOD,
                    "filename": "sample.pdf",
                    "mime": "application/pdf",
                    "imageBase64": base64.b64encode(raw).decode(),
                },
            )
            data = store.snapshot(owner)["data"]
            doc = data["medicalDocuments"][0]
            self.assertEqual((doc["mime"], doc["pageCount"]), ("application/pdf", 6))
            self.assertEqual(store.photo(owner, doc["id"]), (raw, "application/pdf"))
            reference = {"documentId": doc["id"], "residentId": "r001"}
            with closing(store.connect()) as db, db:
                provider.grant(db, "合成测试", 100, "2029-12-31", store.now())
                plan = provider.latest(db)["id"]
                media.grant(db, plan, "ocr", 5)
            result = {
                "object": "ocr.result",
                "purpose": "text_recognition",
                "id": "sample-six",
                "page_count": 6,
                "pages": [
                    {
                        "index": i,
                        "text": "过敏史：测试来源" + str(i + 1),
                        "finish_reason": "stop" if i != 2 else "length",
                    }
                    for i in reversed(range(6))
                ],
            }
            with (
                patch.object(media, "invoke", return_value=result) as remote,
                patch.object(media, "read_key", return_value="mock"),
            ):
                command("dossier.ocr", {**reference, "consent": True})
                self.assertFalse(remote.called)
                self.assertEqual(
                    store.document_ocr_detail(owner, doc["id"])["state"], "failed"
                )
                with closing(store.connect()) as db, db:
                    media.grant(db, plan, "ocr", 6)
                command("dossier.ocr", {**reference, "consent": True})
                command("dossier.ocr", {**reference, "consent": True})
                remote.assert_called_once()
                self.assertEqual(
                    remote.call_args.args[:4],
                    ("ocr", raw, "document.pdf", "application/pdf"),
                )
            receipt = store.document_ocr_detail(owner, doc["id"])
            self.assertEqual(
                [line["page"] for line in receipt["lines"]], list(range(1, 7))
            )
            self.assertEqual(receipt["pages"][2]["state"], "partial")
            with closing(store.connect()) as db:
                self.assertEqual(media.amounts(db, plan, "ocr")["used"], 6)
            person = next(r for r in data["residents"] if r["id"] == "r001")
            review = {
                **reference,
                "method": "DeepSeek OCR 人工核对",
                "verifiedName": person["name"],
                "sourceFacts": "核对第六页",
                "pending": "",
                "changes": [
                    {
                        "field": "allergies",
                        "previous": person.get("allergies") or "",
                        "value": "测试来源6",
                        "line": 1,
                        "page": 6,
                    }
                ],
            }
            with self.assertRaisesRegex(ValueError, "逐页"):
                command("dossier.reviewDocument", review)
            command(
                "dossier.reviewDocument", {**review, "reviewedPages": list(range(1, 7))}
            )
            published = store.snapshot(owner)["data"]["medicalDocuments"][0]
            self.assertEqual(published["reviewChanges"]["allergies"]["page"], 6)
            self.assertEqual(published["reviewedPages"], list(range(1, 7)))
