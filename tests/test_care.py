import unittest
from copy import deepcopy

from platform_core import care


TODAY = "2026-11-24"


class CareWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.state = care.seed(TODAY)
        self.person = self.state["residents"][0]
        self.person_id = self.person["id"]

    def call(self, action, **fields):
        return care.apply(self.state, "care." + action, fields, TODAY)

    def test_seed_relations_match_and_daily_tasks_can_be_charted(self):
        beds = self.state["beds"]
        self.assertGreaterEqual(len(beds), 24)
        ward_counts = {}
        for bed in beds:
            ward_counts.setdefault(bed["ward"], 0)
            ward_counts[bed["ward"]] += bool(bed["residentId"])
        self.assertEqual(len(set(ward_counts.values())), 3)
        for person in self.state["residents"]:
            self.assertEqual(
                next(b for b in beds if b["id"] == person["bedId"])["residentId"],
                person["id"],
            )
        self.assertEqual(len({t["date"] for t in self.state["tasks"]}), 8)

    def test_intake_beds_and_discharge_keep_history(self):
        inquiry = self.state["inquiries"][0]
        first, second, *_ = [b for b in self.state["beds"] if b["status"] == "空闲"]
        self.call("register", inquiryId=inquiry["id"])
        self.call(
            "admit", residentId=self.state["residents"][-1]["id"], bedId=first["id"]
        )
        person = self.state["residents"][-1]
        self.assertEqual(inquiry["residentId"], person["id"])
        with self.assertRaises(ValueError):
            self.call("admit", inquiryId=inquiry["id"], bedId=second["id"])
        with self.assertRaises(ValueError):
            self.call("admit", name="另一位", bedId=first["id"])
        with self.assertRaises(ValueError):
            self.call("transfer", residentId=person["id"], bedId=self.person["bedId"])
        self.assertEqual(first["residentId"], person["id"])
        self.call("transfer", residentId=person["id"], bedId=second["id"])
        self.assertEqual(first["status"], "空闲")
        self.assertEqual(second["residentId"], person["id"])
        self.call("addTask", residentId=person["id"], title="巡访", assignee="护理员")
        self.call("discharge", residentId=person["id"], note="期满退住")
        self.assertEqual(second["status"], "空闲")
        self.assertEqual(person["dischargedAt"], TODAY)
        self.assertEqual(self.state["tasks"][-1]["status"], "已取消")
        moves = [
            x["kind"] for x in self.state["bedMoves"] if x["residentId"] == person["id"]
        ]
        self.assertEqual(moves, ["入住", "转床", "退住"])

    def test_assessment_requires_review_and_matches_execution_to_bed(self):
        old_level = self.person["level"]
        self.call(
            "assess",
            residentId=self.person_id,
            level="半失能",
            note="生活协助需求已记录",
            assignee="责任人",
        )
        self.assertEqual(self.person["level"], old_level)
        plan = self.state["plans"][-1]
        self.call("approvePlan", planId=plan["id"], reviewer="审核人")
        tasks = [t for t in self.state["tasks"] if t.get("planId") == plan["id"]]
        self.assertEqual(len(tasks), 2)
        self.assertEqual(self.person["level"], "半失能")
        with self.assertRaises(ValueError):
            self.call("approvePlan", planId=plan["id"], reviewer="复核人")
        with self.assertRaises(ValueError):
            self.call(
                "completeTask",
                taskId=tasks[0]["id"],
                operator="执行人",
                bedId="其他床位",
            )
        with self.assertRaises(ValueError):
            self.call("completeTask", taskId=tasks[1]["id"], operator="执行人")
        self.call(
            "completeTask",
            taskId=tasks[0]["id"],
            operator="执行人",
            bedId=self.person["bedId"],
        )
        self.call(
            "quality",
            taskId=tasks[0]["id"],
            reviewer="质控员",
            note="完成情况已核对",
            rating=5,
        )
        self.assertEqual(self.state["qualityChecks"][-1]["rating"], 5)
        with self.assertRaises(ValueError):
            self.call("completeTask", taskId=tasks[0]["id"], operator="执行人")

    def test_profile_change_invalidates_prior_medication_review(self):
        self.call(
            "addMedication",
            residentId=self.person_id,
            name="样例药 X",
            instruction="虚构演示医嘱",
        )
        record = self.state["medications"][-1]
        self.call("reviewMedication", medicationId=record["id"], reviewer="复核人")
        self.call(
            "archive",
            residentId=self.person_id,
            summary="回填模拟文档",
            allergies="样例药 X",
            reviewer="复核人",
        )
        self.assertEqual(record["status"], "待复核")
        with self.assertRaises(ValueError):
            self.call("giveMedication", medicationId=record["id"], operator="执行人")
        with self.assertRaises(ValueError):
            self.call("reviewMedication", medicationId=record["id"], reviewer="复核人")
        self.call(
            "reviewMedication",
            medicationId=record["id"],
            reviewer="复核人",
            note="已核对演示信息",
        )
        self.call("giveMedication", medicationId=record["id"], operator="执行人")
        with self.assertRaises(ValueError):
            self.call("giveMedication", medicationId=record["id"], operator="执行人")
        self.assertEqual(record["reviewer"], "复核人")
        self.assertEqual(record["operator"], "执行人")

    def test_duplicate_medication_incurs_review_on_both_records(self):
        for _ in range(2):
            self.call(
                "addMedication",
                residentId=self.person_id,
                name="模拟药品",
                instruction="模拟嘱托",
            )
        first, second = self.state["medications"][-2:]
        self.assertTrue(first["warnings"])
        self.assertEqual(second["warnings"], first["warnings"])

    def test_alert_handover_and_resolution(self):
        self.call(
            "vital",
            residentId=self.person_id,
            metric="复测项",
            value="演示读数",
            abnormal=True,
        )
        item = self.state["vitals"][-1]
        self.call("handover", residentId=self.person_id, assignee="晚班")
        self.assertIn("待复核体征异常 2 项", self.state["handovers"][-1]["summary"])
        self.call(
            "resolveVital",
            vitalId=item["id"],
            operator="值班员",
            note="已联系责任人员复核。",
        )
        self.assertEqual(item["status"], "已处理")

    def test_leave_intervals_preserve_bed_and_unknown_action_is_distinct(self):
        bed_id = self.person["bedId"]
        self.call(
            "leave", residentId=self.person_id, startDate=TODAY, endDate="2026-11-25"
        )
        before = deepcopy(self.state)
        with self.assertRaises(ValueError):
            self.call(
                "leave",
                residentId=self.person_id,
                startDate="2026-11-25",
                endDate="2026-11-26",
            )
        self.assertEqual(self.state, before)
        self.assertEqual(self.person["bedId"], bed_id)
        with self.assertRaises(KeyError):
            self.call("unknown")


if __name__ == "__main__":
    unittest.main()
