import unittest

from platform_core import care


class BedsideVerificationTests(unittest.TestCase):
    def setUp(self):
        self.today = "2026-11-24"
        self.state = care.seed(self.today)
        self.task = next(
            t
            for t in self.state["tasks"]
            if t["date"] == self.today and t["status"] == "待执行"
        )
        self.person = next(
            r for r in self.state["residents"] if r["id"] == self.task["residentId"]
        )
        self.card = next(
            m["cardCode"]
            for m in self.state["bedMoves"]
            if m["residentId"] == self.person["id"]
        )
        self.bed = self.person["bedId"]

    def call(self, action, **fields):
        return care.apply(self.state, "care." + action, fields, self.today)

    def complete(self, code):
        return self.call(
            "completeTask",
            cardCode=code,
            bedId=self.bed,
            taskId=self.task["id"],
            operator="床旁执行人",
        )

    def test_current_card_records_service_receipt(self):
        self.complete(self.card)
        self.assertEqual(self.task["checkedCardCode"], self.card)
        self.assertEqual(self.task["checkedBedId"], self.bed)
        self.assertEqual(self.task["status"], "已完成")

    def test_transfer_back_requires_fresh_card_and_discharge_invalidates_it(self):
        vacant = next(b for b in self.state["beds"] if b["status"] == "空闲")
        self.call("transfer", residentId=self.person["id"], bedId=vacant["id"])
        self.call("transfer", residentId=self.person["id"], bedId=self.bed)
        replacement = self.state["bedMoves"][-1]["cardCode"]
        self.assertNotEqual(self.card, replacement)
        with self.assertRaises(ValueError):
            self.complete(self.card)
        self.assertEqual(self.task["status"], "待执行")
        self.call("discharge", residentId=self.person["id"])
        with self.assertRaises(ValueError):
            self.complete(replacement)

    def test_mismatched_resident_and_legacy_workspaces(self):
        other = next(
            m for m in self.state["bedMoves"] if m["residentId"] != self.person["id"]
        )
        with self.assertRaises(ValueError):
            self.complete(other["cardCode"])
        for move in self.state["bedMoves"]:
            del move["cardCode"]
        self.complete(self.card)
        self.assertEqual(self.task["checkedCardCode"], self.card)


if __name__ == "__main__":
    unittest.main()
