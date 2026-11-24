"""Clinical source fidelity, approval chronology, external consent and scoped medication review."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
from uuid import uuid4

from platform_core import care
from platform_core.care import scales
from platform_core.store import Store


TODAY = "2026-11-24"


def sheet(score=90, **fields):
    maxima = {
        name: cap for group in scales.GROUPS.values() for name, cap in group.items()
    }
    values = {}
    for name, cap in maxima.items():
        values[name] = min(cap, score)
        score -= values[name]
    return {
        "version": scales.VERSION,
        "scores": values,
        "assessor": "甲护士",
        "coAssessor": "乙评估员",
        "assessedOn": TODAY,
        "reference": "虚构原件 P-051",
        "adjustment": "无",
        **fields,
    }


class CareEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.state = care.seed(TODAY)
        self.a, self.b = self.state["residents"][:2]

    def call(self, action, **fields):
        return care.apply(
            self.state, "care." + action, {"operator": "经办丁", **fields}, TODAY
        )

    def test_scale_boundaries_and_confirmed_adjustments(self):
        for total, grade in [
            (90, 0),
            (89, 1),
            (66, 1),
            (65, 2),
            (46, 2),
            (45, 3),
            (30, 3),
            (29, 4),
            (0, 4),
        ]:
            with self.subTest(total=total):
                measured = scales.score_scale(sheet(total), "线上采集", TODAY)
                self.assertEqual((measured["total"], measured["grade"]), (total, grade))
                self.assertEqual(total, sum(measured["subtotals"].values()))
        adjusted = sheet(
            66, adjustment=scales.CATALOG["adjustments"][1], basis="虚构诊断凭据 017"
        )
        self.assertEqual(
            scales.score_scale(adjusted, "纸质量表录入", TODAY)["grade"], 2
        )
        coma = sheet(0, adjustment="昏迷", basis="虚构记录 003")
        self.assertEqual(scales.score_scale(coma, "线上采集", TODAY)["grade"], 4)
        self.assertEqual(
            scales.score_scale(sheet(), "纸质量表录入", TODAY)["sourceUrl"],
            scales.CATALOG["sourceUrl"],
        )

    def test_reject_incomplete_scores_bad_ranges_unsupported_versions_and_unverified_sources(
        self,
    ):
        missing = sheet()
        del missing["scores"]["听力"]
        invalid = sheet()
        invalid["scores"]["视力"] = 3
        boolean = sheet()
        boolean["scores"]["进食"] = True
        for raw in [
            missing,
            invalid,
            boolean,
            sheet(version="未核准版本"),
            sheet(reference=""),
            sheet(coAssessor="甲护士"),
            sheet(assessedOn="2031-01-01"),
            sheet(adjustment="昏迷", basis="凭据"),
            sheet(adjustment=scales.CATALOG["adjustments"][1]),
        ]:
            with self.subTest(raw=raw):
                before = deepcopy(self.state)
                with self.assertRaises(ValueError):
                    self.assess(raw)
                self.assertEqual(before, self.state)

    def assess(self, raw):
        self.call(
            "assess",
            residentId=self.a["id"],
            level="失能",
            source="纸质量表录入",
            note="已核实支持需求",
            assignee="责任护士乙",
            reviewDate="2026-12-24",
            scale=raw,
        )
        return self.state["assessments"][-1]

    def test_scale_drives_review_and_reassessment_historical_entry_cannot_cancel_current_plan(
        self,
    ):
        row = self.assess(sheet(60))
        plan = self.state["plans"][-1]
        self.assertEqual(row["recordedBy"], "经办丁")
        self.assertEqual(plan["assessmentId"], row["id"])
        self.assertTrue(any("支持需求" in item for item in plan["items"]))
        prior_level = self.a["level"]
        count = len(self.state["plans"])
        historical = self.assess(sheet(65, assessedOn="2026-05-12"))
        self.assertTrue(historical["historyOnly"])
        self.assertEqual(len(self.state["plans"]), count)
        self.assertEqual(plan["status"], "待复核")
        self.call("approvePlan", planId=plan["id"], reviewer="院内复核人甲")
        self.assertEqual(
            (plan["previousCareLevel"], plan["careLevel"], plan["reviewedAt"]),
            (prior_level, "失能", TODAY),
        )
        reminders = [
            t
            for t in self.state["tasks"]
            if t.get("planId") == plan["id"] and t["kind"] == "复评提醒"
        ]
        self.assertEqual(
            [(t["date"], t["assignee"]) for t in reminders],
            [("2026-12-24", "责任护士乙")],
        )

    def test_screen_grade_intervene_evaluate_distinct_steps_and_resident_checks(self):
        row = self.assess(sheet())
        self.state.pop("followups", None)
        self.call(
            "screen",
            residentId=self.a["id"],
            subject="生活支持需求",
            finding="现场观察记录001",
        )
        screening = self.state["followups"][-1]
        target = {"followupId": screening["id"]}
        with self.assertRaises(ValueError):
            self.call("finishFollowup", **target, actual="回访", outcome="结果")
        schedule = dict(
            priority="重点跟进",
            dueDate="2026-11-25",
            basis="工作人员核对评估表",
            assignee="责任护士乙",
            intervention="按已核准计划回访",
        )
        with self.assertRaises(ValueError):
            self.call(
                "scheduleFollowup", **target, **{**schedule, "dueDate": "2025-01-01"}
            )
        self.call(
            "assess",
            residentId=self.b["id"],
            level="自理",
            note="另一份",
            assignee="乙",
        )
        with self.assertRaises(ValueError):
            self.call(
                "scheduleFollowup",
                **target,
                **schedule,
                assessmentId=self.state["assessments"][-1]["id"],
            )
        self.call("scheduleFollowup", **target, **schedule, assessmentId=row["id"])
        self.call(
            "finishFollowup",
            **target,
            actual="登记实际回访",
            outcome="已向负责人反馈",
            operator="随访护士",
        )
        self.assertEqual(
            (screening["status"], screening["gradedBy"], screening["finishedBy"]),
            ("已评价", "经办丁", "随访护士"),
        )
        with self.assertRaises(ValueError):
            self.call("finishFollowup", **target, actual="重复", outcome="重复")

    def test_personal_consent_minimizes_package_and_withdrawal_blocks_export(self):
        self.state.pop("referrals", None)
        self.call(
            "refer",
            residentId=self.a["id"],
            kind="出院衔接",
            channel="基层公卫",
            destination="社区机构甲",
            summary="授权范围内的交接说明",
        )
        ref = self.state["referrals"][-1]
        target = {"referralId": ref["id"]}
        with self.assertRaises(ValueError):
            self.call("exportReferral", **target, exportId=str(uuid4()))
        for scope, extended in [
            ("姓名与交接摘要", False),
            ("姓名、交接摘要和过敏及风险记录", True),
        ]:
            self.call(
                "referralConsent",
                **target,
                decision="同意",
                scope=scope,
                basis="本人授权凭据甲",
            )
            export_id = str(uuid4())
            self.call("exportReferral", **target, exportId=export_id)
            pkg = ref["exports"][-1]["content"]
            self.assertEqual(pkg["exportId"], export_id)
            self.assertEqual(pkg["residentName"], self.a["name"])
            self.assertEqual("allergies" in pkg, extended)
            self.assertEqual("risk" in pkg, extended)
            self.assertNotIn("basis", pkg)
            with self.assertRaises(ValueError):
                self.call("exportReferral", **target, exportId=export_id)
            self.call(
                "referralConsent", **target, decision="撤回", basis="本人撤回凭据乙"
            )
            with self.assertRaises(ValueError):
                self.call("exportReferral", **target, exportId=str(uuid4()))
        self.call(
            "receiveReferral",
            **target,
            receiver="社区联系人",
            receipt="来电及纸质签收编号012",
        )
        self.assertEqual((ref["status"], ref["recordedBy"]), ("已登记回执", "经办丁"))
        with self.assertRaises(ValueError):
            self.call("receiveReferral", **target, receiver="重复", receipt="重复")

    def add_med(self, resident, name, scheduled=""):
        self.call(
            "addMedication",
            residentId=resident["id"],
            name=name,
            instruction="虚构医嘱记录",
            scheduledAt=scheduled,
        )
        return self.state["medications"][-1]

    def test_rules_are_versioned_scoped_and_reviewed_against_human_evidence(self):
        self.state.pop("drugRules", None)
        for when in ["2026-2-01T08:01", "2026-02-30T09:00", "2026-12-13T24:00"]:
            with self.assertRaises(ValueError):
                self.add_med(self.a, "样本甲", when)
        first = self.add_med(self.a, "样本Ａ", "2026-11-24T09:05")
        second = self.add_med(self.a, "样本B")
        other = self.add_med(self.b, "样本Ａ")
        for row in [first, second, other]:
            self.call("reviewMedication", medicationId=row["id"], reviewer="复核护士")
        fields = dict(
            drugA="样本a",
            drugB="样本Ｂ",
            version="v1",
            source="虚构院内核准资料0001",
            message="核对模拟事项",
        )
        with self.assertRaises(ValueError):
            self.call("publishDrugRule", **{**fields, "source": ""})
        self.call("publishDrugRule", **fields)
        rule = self.state["drugRules"][-1]
        self.assertEqual(
            (first["status"], second["status"], other["status"]),
            ("待复核", "待复核", "待执行"),
        )
        with self.assertRaises(ValueError):
            self.call("reviewMedication", medicationId=first["id"], reviewer="复核护士")
        self.call(
            "reviewMedication",
            medicationId=first["id"],
            reviewer="复核护士",
            note="已核对合成人工规则",
        )
        proof = deepcopy(first["reviews"][-1])
        self.assertEqual(proof["ruleIds"], [rule["id"]])
        self.assertIn("虚构院内核准资料0001", proof["warnings"][0])
        self.call("retireDrugRule", ruleId=rule["id"], reason="核准版更新")
        self.assertEqual(first["reviews"][-1], proof)
        with self.assertRaises(ValueError):
            self.call("publishDrugRule", **fields)
        self.call("publishDrugRule", **{**fields, "version": "v2"})
        self.assertEqual(first["status"], "待复核")
        self.call(
            "reviewMedication",
            medicationId=first["id"],
            reviewer="复核护士",
            note="已复核第二版",
        )
        self.call(
            "giveMedication", medicationId=first["id"], nowLocal="2026-11-24T09:10"
        )
        self.assertEqual(
            (first["scheduledAt"], first["executedTime"]),
            ("2026-11-24T09:05", "2026-11-24T09:10"),
        )
        self.assertEqual(len(first["reviews"]), 3)


class CareRoleIntegrationTests(unittest.TestCase):
    def test_care_staff_sees_score_only_and_cannot_enter_medical_basis(self):
        with (
            TemporaryDirectory() as tmp,
            patch.dict("os.environ", {"NH_OWNER_PASSWORD": "pdf-test-only-password"}),
        ):
            store = Store(Path(tmp) / "fixture.sqlite")
            owner, _ = store.login("owner", "pdf-test-only-password")

            def call(token, action, **fields):
                return store.execute(
                    action, fields, store.version(token)["revision"], token
                )

            call(
                owner,
                "access.create",
                kind="staff",
                username="assessor",
                displayName="经办甲",
                role="自定义",
                password="pdf-staff-test-only",
                permissions=["care", "medical"],
            )
            token, user = store.login("assessor", "pdf-staff-test-only")
            scale = sheet(
                89,
                assessedOn=store.now().date().isoformat(),
                adjustment=scales.CATALOG["adjustments"][1],
                basis="授权查验的诊断原始证据",
                reference="已签原件编号0001",
            )
            common = dict(
                residentId="r001",
                level="半失能",
                note="核对日常照护安排",
                assignee="护工甲",
            )
            for professional in ["medical", "clinical"]:
                call(
                    owner,
                    "access.update",
                    id=user["id"],
                    permissions=["care", professional],
                )
                call(token, "care.assess", **common, source="纸质量表录入", scale=scale)
                saved = store.snapshot(token)["data"]["assessments"][-1]["scale"]
                self.assertEqual(
                    (saved["basis"], saved["reference"], saved["assessors"]),
                    (
                        scale["basis"],
                        scale["reference"],
                        [scale["assessor"], scale["coAssessor"]],
                    ),
                )
            call(owner, "access.update", id=user["id"], permissions=["care"])
            with self.assertRaises(PermissionError):
                call(token, "care.assess", **common, source="纸质量表录入", scale=scale)
            care_state = store.snapshot(token)["data"]
            visible = care_state["assessments"][-1]["scale"]
            self.assertEqual(
                set(visible),
                {
                    "version",
                    "name",
                    "assessedOn",
                    "scores",
                    "subtotals",
                    "total",
                    "grade",
                    "gradeName",
                },
            )
            self.assertEqual(
                (visible["total"], visible["grade"], len(visible["scores"])),
                (89, 2, 26),
            )
            call(token, "care.assess", **common, observations={"生活起居": "需协助"})
            self.assertNotIn("scale", store.snapshot(token)["data"]["assessments"][-1])

    def test_role_and_current_session_control_rules_and_protected_evidence(self):
        with (
            TemporaryDirectory() as tmp,
            patch.dict("os.environ", {"NH_OWNER_PASSWORD": "pdf-test-only-password"}),
        ):
            store = Store(Path(tmp) / "fixture.sqlite")
            owner, _ = store.login("owner", "pdf-test-only-password")

            def command(token, action, **fields):
                return store.execute(
                    action, fields, store.version(token)["revision"], token
                )

            grants = ["clinical", "clinical.rules", "staff.manage"]
            command(
                owner,
                "access.create",
                kind="staff",
                username="rules-reviewer",
                displayName="专业复核员",
                role="自定义",
                password="pdf-staff-test-only",
                permissions=grants,
            )
            staff, user = store.login("rules-reviewer", "pdf-staff-test-only")
            command(
                owner,
                "access.create",
                kind="family",
                username="care-family",
                displayName="家属",
                password="pdf-family-test-only",
                residentId="r001",
            )
            family, _ = store.login("care-family", "pdf-family-test-only")
            rule = dict(
                drugA="模拟甲",
                drugB="模拟乙",
                source="机构演练规则",
                version="演练版",
                message="虚构核准提示",
                operator="冒用的操作人",
            )
            command(staff, "care.publishDrugRule", **rule)
            command(
                staff,
                "care.screen",
                residentId="r001",
                subject="随访项目甲",
                finding="观察记录",
            )
            command(
                staff,
                "care.refer",
                residentId="r001",
                kind="院外转介",
                channel="医联体",
                destination="接收方",
                summary="回访摘要",
            )
            data = store.snapshot(staff)["data"]
            self.assertEqual(data["drugRules"][-1]["reviewer"], "专业复核员")
            self.assertTrue(data["followups"] and data["referrals"])
            self.assertEqual(data["followups"][-1]["openedBy"], "专业复核员")
            with self.assertRaises((PermissionError, ValueError)):
                command(
                    staff,
                    "access.create",
                    kind="staff",
                    username="peer-reviewer",
                    displayName="同事",
                    role="自定义",
                    password="local-peer-test-only",
                    permissions=["clinical", "clinical.rules"],
                )
            command(owner, "access.update", id=user["id"], permissions=["clinical"])
            with self.assertRaises(PermissionError):
                command(
                    staff,
                    "care.retireDrugRule",
                    ruleId=data["drugRules"][-1]["id"],
                    reason="撤下",
                )
            self.assertEqual(
                store.snapshot(staff)["data"]["drugRules"], data["drugRules"]
            )
            command(owner, "access.update", id=user["id"], permissions=["care"])
            for token in [staff, family]:
                denied = store.snapshot(token)["data"]
                for key in ("drugRules", "followups", "referrals", "medications"):
                    self.assertFalse(denied.get(key))
                with self.assertRaises(PermissionError):
                    command(
                        token,
                        "care.exportReferral",
                        referralId=data["referrals"][-1]["id"],
                        exportId=str(uuid4()),
                    )


if __name__ == "__main__":
    unittest.main()
