import base64
from contextlib import closing
from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from platform_core.operations import expense_import
from platform_core.store import Store, TIMEZONE


BANK = (
    "交易日期,银行流水号,收支方向,交易金额,对方户名,摘要,交易状态,发票号码,支出分类\n"
)
POWER = "缴费日期,发票号码,银行流水号,实付金额,收款单位,缴费状态,摘要\n"
BANK_ROW = "2026-11-01,TX01,支出,125.30,电力公司,十月电费,成功,INV01,设施\n"


class ExpenseFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(
            Path(self.temp.name) / "test.sqlite3",
            lambda: datetime(2026, 11, 24, 9, tzinfo=TIMEZONE),
            initial_owner_password="test-expenses-012",
            initial_data="empty",
        )
        self.owner = self.store.login("owner", "test-expenses-012")[0]

    def preview(self, text, source="bank", ext="csv", enc="utf-8-sig", token=None):
        return expense_import.preview(
            self.store,
            self.owner if token is None else token,
            {
                "source": source,
                "fileName": "对账原件." + ext,
                "contentBase64": base64.b64encode(text.encode(enc)).decode(),
            },
        )

    def confirm(self, view, numbers, token=None):
        token = token or self.owner
        return self.store.execute(
            "ops.importExpenses",
            {"previewId": view["previewId"], "rowNumbers": numbers},
            self.store.version(token)["revision"],
            token,
        )

    def expense_rows(self):
        return self.store.snapshot(self.owner)["data"]["expenses"]

    def test_ready_explicit_confirm_archive_and_replay(self):
        text = (
            BANK
            + BANK_ROW
            + "2026-11-01,T2,收入,30,甲,订金,成功,,其他\n"
            + "2026-11-01,T3,支出,30,甲,设备,未支付,,设施\n"
            + "2026-11-01,,支出,30,甲,设备,成功,,设施\n"
        )
        view = self.preview(text, enc="gb18030")
        self.assertEqual(
            [r["status"] for r in view["rows"]],
            ["ready", "excluded", "excluded", "review"],
        )
        self.assertEqual(self.expense_rows(), [])
        with self.assertRaisesRegex(ValueError, "只可"):
            self.confirm(view, [2, 3])
        made = self.confirm(view, [2])
        result = self.expense_rows()
        self.assertEqual(len(result), 1)
        self.assertEqual(
            (result[0]["amount"], result[0]["date"], result[0]["transactionId"]),
            (125.30, "2026-11-01", "TX01"),
        )
        digest = result[0]["evidenceFiles"][0]["id"]
        self.assertEqual(
            expense_import.original(self.store, self.owner, digest),
            text.encode("gb18030"),
        )
        self.assertEqual(self.confirm(view, [2])["revision"], made["revision"])
        self.assertEqual(
            self.preview(text, enc="gb18030")["rows"][0]["status"], "duplicate"
        )

    def test_invoice_alone_exact_matches_attach_and_conflicts_stay_manual(self):
        xml = "<Invoice><InvoiceNumber>INV01</InvoiceNumber><SellerName>电力公司</SellerName><TotalTaxIncludedAmount>125.30</TotalTaxIncludedAmount></Invoice>"
        self.assertEqual(
            self.preview(xml, "electricity", "xml")["rows"][0]["status"], "review"
        )
        self.confirm(
            self.preview(
                POWER + "2026-11-01,INV01,,125.30,电力公司,已缴费,十月电费\n",
                "electricity",
            ),
            [2],
        )
        ambiguous = self.preview(BANK + BANK_ROW.replace("INV01", ""))
        self.assertEqual(ambiguous["rows"][0]["status"], "review")
        same = self.preview(BANK + BANK_ROW)
        self.assertEqual(same["rows"][0]["mode"], "link")
        self.confirm(same, [2])
        attach = self.preview(xml, "electricity", "xml")
        self.assertEqual(attach["rows"][0]["mode"], "link")
        self.confirm(attach, [1])
        bad = self.preview(BANK + BANK_ROW.replace("125.30", "125.31"))
        self.assertEqual(bad["rows"][0]["status"], "review")
        ledger = self.expense_rows()
        self.assertEqual(len(ledger), 1)
        self.assertEqual(len(ledger[0]["evidenceFiles"]), 3)
        self.assertEqual(ledger[0]["transactionId"], "TX01")

    def test_bank_debit_credit_and_mutually_conflicting_file_rows(self):
        text = (
            "记账日期,交易流水号,借方发生额（元）,贷方发生额（元）,对方户名\n"
            "20261101,B01,12.50,0,甲\n20261101,B02,0,12.5,丙\n20261101,B01,22.50,0,乙\n"
            "20261101,B03,22.50,5,丁\n20261101,B04,22.50,0,戊\n"
        )
        view = self.preview(text)
        self.assertEqual(
            [r["status"] for r in view["rows"]],
            ["review", "excluded", "review", "review", "ready"],
        )
        self.confirm(view, [6])
        self.assertEqual(self.expense_rows()[0]["amount"], 22.5)

    def test_account_and_expiry_authorization(self):
        for name, permissions in (("fin", ["finance"]), ("carer", ["care"])):
            self.store.execute(
                "access.create",
                dict(
                    username=name,
                    displayName=name,
                    password="test-finance-012",
                    kind="staff",
                    role="自定义",
                    permissions=permissions,
                ),
                self.store.version(self.owner)["revision"],
                self.owner,
            )
        fin = self.store.login("fin", "test-finance-012")[0]
        carer = self.store.login("carer", "test-finance-012")[0]
        with self.assertRaises(PermissionError):
            self.preview(BANK + BANK_ROW, token=carer)
        view = self.preview(BANK + BANK_ROW, token=fin)
        with self.assertRaisesRegex(ValueError, "不属于"):
            self.confirm(view, [2], self.owner)
        self.confirm(view, [2], fin)
        digest = self.expense_rows()[0]["evidenceFiles"][0]["id"]
        with self.assertRaises(PermissionError):
            expense_import.original(self.store, carer, digest)
        with closing(self.store.connect()) as db, db:
            db.execute("UPDATE expense_file_previews SET expires=0")
        with self.assertRaisesRegex(ValueError, "过期"):
            self.confirm(view, [2], fin)

    def test_manual_expense_candidate_and_bank_date_conflict_do_not_post(self):
        self.store.execute(
            "ops.expense",
            dict(
                category="设施",
                voucher="内部报销-001",
                amount="125.30",
                date="2026-11-01",
                payee="电力公司",
                note="十月电费",
            ),
            self.store.version(self.owner)["revision"],
            self.owner,
        )
        view = self.preview(BANK + BANK_ROW)
        self.assertEqual(view["rows"][0]["status"], "review")
        self.assertIn("手工凭证 内部报销-001", view["rows"][0]["reason"])
        with self.assertRaisesRegex(ValueError, "只可"):
            self.confirm(view, [2])
        another = BANK_ROW.replace("电力公司", "电力营业厅")
        self.confirm(self.preview(BANK + another), [2])
        bad = self.preview(BANK + another.replace("2026-11-01", "2026-11-02"))
        self.assertEqual(bad["rows"][0]["status"], "review")
        self.assertIn("银行凭证 TX01", bad["rows"][0]["reason"])
        self.assertEqual(len(self.expense_rows()), 2)

    def test_credit_arrears_and_repeated_rows_in_either_source(self):
        text = (
            BANK
            + BANK_ROW
            + BANK_ROW
            + "2026-11-01,T2,收入,50,乙,退还,已支付,,设施\n"
            + "2026-11-01,T3,支出,70,甲,应缴,欠费,,设施\n"
        )
        for source in ("bank", "electricity"):
            view = self.preview(text, source)
            self.assertEqual(
                [r["status"] for r in view["rows"]],
                ["ready", "duplicate", "excluded", "excluded"],
            )
        result = self.confirm(view, [2])
        self.assertIn("¥125.30", result["summary"])
        self.assertEqual(sum(r["amount"] for r in self.expense_rows()), 125.30)

    def test_stale_preview_does_not_turn_a_new_expense_into_an_attachment(self):
        view = self.preview(BANK + BANK_ROW)
        payment = self.preview(
            POWER + "2026-11-01,INV01,,125.30,电力公司,已缴费,十月电费\n", "electricity"
        )
        self.confirm(payment, [2])
        with self.assertRaisesRegex(ValueError, "重新预览"):
            self.confirm(view, [2])
        current = self.preview(BANK + BANK_ROW)
        self.assertEqual(current["rows"][0]["mode"], "link")
        receipt = self.confirm(current, [2])
        self.assertIn("¥0.00", receipt["summary"])
        self.assertEqual(sum(r["amount"] for r in self.expense_rows()), 125.30)
