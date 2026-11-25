from datetime import datetime
from importlib.util import find_spec
from io import BytesIO
from pathlib import Path
from unittest import TestCase, skipUnless

from release_scope import international_only

from platform_core.agents import resident_workbook as workbook


@skipUnless(find_spec("openpyxl") and find_spec("excel_mcp") and find_spec("xlrd"), "requires requirements-harness.txt")
class RegistrationWorkbookTests(TestCase):
    def test_export_over_stdio_and_read_draft(self):
        fields = {"name": "演示甲", "birthDate": "1950-01-02", "phone": "13800001000",
                  "language": "普通话", "birthRegion": {"codes": ["41", "4104"], "detail": ""}}
        raw = workbook.export(fields)
        row, = workbook.preview(raw)["records"]
        self.assertEqual(row["fields"], fields)
        self.assertEqual(row["ambiguous"], [])
        self.assertEqual(row["labels"]["birthRegion"], "河南省 · 平顶山市")

    @international_only
    def test_international_template_round_trip(self):
        from openpyxl import load_workbook
        fields = {"name":"Amélie Martin", "birthDate":"1950-01-02", "address":"10 Park Road, London",
                  "phone":"+447700900123", "language":"法语", "birthplace":"Lyon"}
        raw = workbook.export(fields, international=True)
        book = load_workbook(BytesIO(raw), read_only=True)
        self.assertEqual(book.active.title,"Resident registration")
        self.assertEqual(book.active["A1"].value, "Full name")
        self.assertEqual(book.active["D2"].value, "French")
        book.close()
        self.assertEqual(workbook.preview(raw, international=True)["records"][0]["fields"], fields)

    def test_excel_97_2003_import(self):
        raw = (Path(__file__).parent / "fixtures/resident-registration.xls").read_bytes()
        row, = workbook.preview(raw)["records"]
        self.assertEqual(row["fields"], {"name": "演示甲", "birthDate": "1950-01-02", "phone": "13800001000"})

    def test_ambiguous_and_duplicate_columns(self):
        from openpyxl import Workbook

        book = Workbook()
        sheet = book.active

        def preview():
            stream = BytesIO()
            book.save(stream)
            return workbook.preview(stream.getvalue())

        sheet.append(["姓名", "出生日期", "电话", "语言"])
        sheet.append(["=1+1", datetime(1950, 1, 2), 13800001000, "选项以外的语言"])
        row, = preview()["records"]
        self.assertEqual(row["fields"], {"birthDate": "1950-01-02", "phone": "13800001000"})
        self.assertEqual(row["ambiguous"], ["name", "language"])
        sheet["D1"] = "联系电话"
        with self.assertRaisesRegex(ValueError, "唯一"):
            preview()
