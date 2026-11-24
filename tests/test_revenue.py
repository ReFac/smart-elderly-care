import unittest

from platform_core.agents import runtime
from platform_core.agents.contracts import SPECIALISTS
from platform_core.agents.revenue import reporting_window


class RevenueTests(unittest.TestCase):
    def test_receipts_use_actual_money_with_room_permission_and_short_citations(self):
        class Trace:
            def append(self, *args):
                pass

        state = {
            "payments": [
                dict(
                    id=key,
                    date="2026-11-01",
                    residentId=rid,
                    method=method,
                    amount=amount,
                )
                for key, rid, method, amount in [
                    ("p", "me", "微信支付", 100.01),
                    ("c", "me", "预交金冲抵", 30),
                    ("x", "other", "支付宝", 999),
                ]
            ],
            "depositEntries": [
                dict(id="d", date="2026-11-02", residentId="me", amount=50.25),
                dict(id="old", date="2026-10-31", residentId="me", amount=500),
            ],
        }
        (artifact,) = runtime.execute(
            "本月实收多少",
            SPECIALISTS,
            "auto",
            state,
            "",
            "2026-11-24",
            Trace(),
            member_ids={"me"},
        )
        self.assertEqual(artifact["tool"], "finance.revenue")
        self.assertEqual(artifact["title"], "实收合计 ¥150.26")
        self.assertEqual([r["recordIds"] for r in artifact["evidence"]], [["d"], ["p"]])
        state["bills"] = [
            dict(id="invoice", residentId="me", date="2026-11-04", amount=200)
        ]
        (overview,) = runtime.execute(
            "本月营收",
            SPECIALISTS,
            "auto",
            state,
            "",
            "2026-11-24",
            Trace(),
            member_ids={"me"},
        )
        self.assertEqual(overview["title"], "开单应收 ¥200.00 · 实收 ¥150.26")
        with self.assertRaises(PermissionError):
            runtime.execute(
                "本月实收多少",
                SPECIALISTS[:1],
                "auto",
                state,
                "",
                "2026-11-24",
                Trace(),
            )

    def test_natural_calendar_boundaries_and_unsupported_ranges(self):
        self.assertEqual(
            reporting_window("上个月营收", "2024-03-01"), ("2024-02-01", "2024-02-29")
        )
        self.assertEqual(
            reporting_window("2025年11月收入", "2026-01-01"),
            ("2025-11-01", "2025-11-30"),
        )
        self.assertEqual(
            reporting_window("昨天收入", "2026-01-01"), ("2025-12-31", "2025-12-31")
        )
        for goal in (
            "上月和本月实收",
            "最近一周收入",
            "2026-13收入",
            "2026年2月30日收入",
        ):
            with self.subTest(goal=goal), self.assertRaises(ValueError):
                reporting_window(goal, "2026-11-24")
