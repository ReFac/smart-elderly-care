from copy import deepcopy
import unittest

from platform_core import operations


TODAY = "2026-11-24"


def base():
    return {
        "residents": [
            dict(
                id="R1",
                name="示例长者",
                status="在住",
                bedId="B1",
                level="半失能",
                admittedAt="2026-10-26",
                dischargedAt="",
            )
        ],
        "beds": [dict(id="B1", dailyRate=50)],
        "leaves": [
            dict(residentId="R1", startDate="2026-10-23", endDate="2026-10-27"),
            dict(residentId="R1", startDate="2026-10-27", endDate="2026-10-28"),
        ],
    }


class OperationsTest(unittest.TestCase):
    def setUp(self):
        self.state = operations.seed(TODAY, base())

    def call(self, action, **payload):
        return operations.apply(self.state, "ops." + action, payload, TODAY)

    def test_month_bill_uses_admission_and_unique_leave_days(self):
        self.call("bill", residentId="R1", month="2026-10", packageFee="50.20")
        bill = self.state["bills"][0]
        # 26–31号六天；请假重合部分只计一次；三天计护理费。
        self.assertEqual(
            (bill["serviceDays"], bill["leaveDays"], bill["amount"]), (6, 3, 485.20)
        )
        self.assertEqual(bill["bedId"], "B1")
        with self.assertRaises(ValueError):
            self.call("bill", residentId="R1", month="2026-10")
        self.assertEqual(len(self.state["bills"]), 2)

    def test_discharge_clips_last_day(self):
        resident = self.state["residents"][0]
        resident.update(status="已退住", dischargedAt="2026-10-28", bedId="")
        self.call("bill", residentId="R1", month="2026-10", bedFee="60.50", careFee=45)
        bill = self.state["bills"][0]
        self.assertEqual(
            (bill["serviceDays"], bill["leaveDays"], bill["amount"]), (3, 3, 181.50)
        )

    def test_deposit_applies_to_oldest_debt_and_carries_credit(self):
        self.call("bill", residentId="R1", month="2026-10", bedFee=5, careFee=0)
        old, new = self.state["bills"]
        new_balance = new["balance"]
        self.call("deposit", residentId="R1", amount="50.01")
        self.assertEqual(old["status"], "已结清")
        self.assertAlmostEqual(new["balance"], new_balance - 20.01)
        self.call("deposit", residentId="R1", amount=new["balance"] + 100)
        self.assertEqual(self.state["deposits"][0]["amount"], 100)
        self.assertEqual(new["status"], "已结清")

    def test_manual_payment_validation_is_atomic(self):
        bill = self.state["bills"][0]
        for value in (bill["balance"] + 1, "0.001", True, -1, "NaN", 0):
            snapshot = deepcopy(self.state)
            with self.assertRaises(ValueError):
                self.call("pay", billId=bill["id"], amount=value)
            self.assertEqual(snapshot, self.state)
        self.call("pay", billId=bill["id"], amount=bill["balance"], method="线下登记")
        self.assertEqual((bill["balance"], bill["status"]), (0, "已结清"))

    def test_stock_shortage_and_shift_conflict(self):
        item = self.state["inventory"][0]
        with self.assertRaises(ValueError):
            self.call(
                "stock", itemId=item["id"], type="出库", quantity=item["quantity"] + 1
            )
        self.call("stock", itemId=item["id"], type="出库", quantity=2)
        self.assertEqual(self.state["transactions"][0]["quantity"], 2)
        self.call("shift", staff="王一", date=TODAY, period="早班", area="一区")
        with self.assertRaises(ValueError):
            self.call("shift", staff="王一", date=TODAY, period="早班", area="二区")

    def test_report_is_a_monthly_local_snapshot_with_validation(self):
        self.state["residents"].append(
            dict(
                id="R2",
                name="二号",
                status="已退住",
                bedId="",
                level="失能",
                admittedAt="2026-09-01",
                dischargedAt="2026-10-05",
            )
        )
        self.call("report", month="2026-10")
        report = self.state["reports"][0]
        self.assertEqual(report["recordCount"], 2)
        self.assertEqual(
            report["summary"], {"本月入住": 1, "本月退住": 1, "期末在住": 1}
        )
        self.state["residents"][0]["level"] = ""
        self.call("report", month="2026-10")
        self.assertEqual(self.state["reports"][0]["id"], report["id"])
        self.assertEqual(report["status"], "待补正")
        self.assertTrue(any("R1" in issue for issue in report["issues"]))
        self.assertEqual(len(self.state["reports"]), 2)

    def test_suggestions_require_explicit_review_and_keep_references(self):
        bill_before = deepcopy(self.state["bills"])
        for category in ("日常照护", "物资管控", "运营分析"):
            self.call("suggest", category=category, residentId="R1")
            row = self.state["suggestions"][0]
            self.assertEqual(row["status"], "待审核")
            self.call("review", id=row["id"], decision="采纳", note="已检查本班记录")
            self.assertEqual(row["reviewedAt"], TODAY)
            with self.assertRaises(ValueError):
                self.call("review", id=row["id"], decision="驳回", note="重复")
        self.assertEqual(bill_before, self.state["bills"])

    def test_rates_match_care_level_contract(self):
        from platform_core.care import LEVELS

        self.assertEqual(set(operations.CARE_RATES), set(LEVELS))

    def test_care_suggestion_selects_latest_assessment_and_only_due_pending_tasks(self):
        self.state["assessments"] = [
            dict(
                id="A0",
                residentId="R1",
                date="2026-11-03",
                reviewDate="2026-12-03",
                level="自理",
            ),
            dict(
                id="A1",
                residentId="R1",
                date=TODAY,
                reviewDate="2026-12-20",
                level="失能",
            ),
        ]
        self.state["tasks"] = [
            dict(
                id="T1",
                residentId="R1",
                date=TODAY,
                status="待执行",
                title="本班巡视",
                assignee="林晓",
            ),
            dict(
                id="T2",
                residentId="R1",
                date=TODAY,
                status="已完成",
                title="已交班",
                assignee="陈悦",
            ),
            dict(
                id="T3",
                residentId="R1",
                date="2026-12-20",
                status="待执行",
                title="复评",
                assignee="林晓",
            ),
        ]
        self.call("suggest", category="日常照护", residentId="R1")
        row = self.state["suggestions"][0]
        self.assertIn("2026-12-20", row["detail"])
        self.assertIn("本班巡视", row["detail"])
        self.assertEqual(
            [e["recordIds"] for e in row["evidence"]], [["R1"], ["A1"], ["T1"]]
        )

    def test_material_signal_uses_only_adjacent_windows_and_cites_flagged_issue(self):
        self.state["inventory"] = [
            dict(id="I", name="用品", unit="盒", quantity=1, minimum=5)
        ]
        self.state["transactions"] = [
            dict(id=str(i), itemId="I", date=day, quantity=q, type=direction)
            for i, (day, q, direction) in enumerate(
                [
                    ("2026-11-10", 100, "出库"),
                    ("2026-11-11", 2, "出库"),
                    ("2026-11-13", 1, "出库"),
                    ("2026-11-17", 2, "出库"),
                    ("2026-11-18", 6, "出库"),
                    (TODAY, 9, "入库"),
                    ("2026-11-25", 10, "出库"),
                ]
            )
        ]
        self.call("suggest", category="物资管控")
        row = self.state["suggestions"][0]
        self.assertIn("上期 5、本期 6", row["detail"])
        self.assertIn("用品 5 盒", row["detail"])
        self.assertEqual(row["evidence"][-1]["recordIds"], ["4"])
        self.call("stock", itemId="I", type="入库", quantity=6)
        self.assertIn("用品 5 盒", row["detail"])  # 建议保存当次证据快照。

    def test_financial_signal_separates_monthly_balance_and_overdue_and_rate_override(
        self,
    ):
        self.call("bill", residentId="R1", month="2026-10", careFee=46)
        late, current = self.state["bills"]
        self.call("suggest", category="运营分析")
        row = self.state["suggestions"][0]
        pending, overdue, mismatch = row["evidence"]
        self.assertEqual(set(pending["recordIds"]), {current["id"], late["id"]})
        self.assertEqual(overdue["recordIds"], [late["id"]])
        self.assertEqual(mismatch["recordIds"], [late["id"]])
        self.assertIn("示例等级标准", mismatch["value"])
        self.assertIn("¥46.00", mismatch["value"])

    def test_unknown_action_can_be_dispatched_by_caller(self):
        with self.assertRaises(KeyError):
            self.call("unknown")
