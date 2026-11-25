"""Source-grounded health briefs remain bound to one resident and preserve staff additions."""

from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from platform_core import medical_visits, provider, resident_health as health
from platform_core.store import Store, TIMEZONE

DAY = "2026-11-24"
PW = "synthetic-health-only"


class ResidentHealthTests(TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(
            Path(folder.name) / "health.db",
            now=lambda: datetime(2026, 11, 24, 12, tzinfo=TIMEZONE),
            initial_owner_password=PW,
        )
        self.owner = self.store.login("owner", PW)[0]
        self.req = 0

    def cmd(self, action, p, token=None):
        token = token or self.owner
        return self.store.execute(
            action, p, self.store.version(token)["revision"], token
        )

    def account(self, name, grants, campus=None):
        self.cmd(
            "access.create",
            {
                "kind": "staff",
                "role": "自定义",
                "permissions": grants,
                "displayName": name,
                "username": name,
                "password": PW,
                **({"campusId": campus} if campus else {}),
            },
        )
        return self.store.login(name, PW)[0]

    def note(self, kind, text, rid="r001", token=None, **options):
        self.req += 1
        return self.cmd(
            "care.healthNote",
            {
                "residentId": rid,
                "kind": kind,
                "text": text,
                "day": DAY,
                "requestId": str(self.req),
                "confirmed": True,
                **options,
            },
            token,
        )

    def view(self, token=None, rid="r001"):
        return health.read(self.store, token or self.owner, rid)

    def draft(self, token=None, rid="r001"):
        return health.draft(self.store, token or self.owner, rid, {"consent": True})

    def sign(self, draft, token=None, rid="r001", **options):
        return self.cmd(
            "dossier.signHealthIntro",
            {
                "residentId": rid,
                "draftId": draft["draftId"],
                "selected": [0],
                "confirmed": True,
                **options,
            },
            token,
        )

    def visit(self, rid, diagnosis):
        fields = {"diagnosis": diagnosis, "eventDate": DAY}
        draft = medical_visits.preview(
            self.store,
            self.owner,
            rid,
            {
                "mode": "manual",
                "requestId": "test-" + rid,
                "fields": fields,
                "revision": self.store.version(self.owner)["revision"],
            },
        )
        self.cmd(
            "dossier.confirmVisit",
            {
                "residentId": rid,
                "draftId": draft["draftId"],
                "fields": fields,
                "confirmed": True,
            },
        )
        return draft["draftId"]

    def test_chronic_register_human_confirmation_history_and_scoped_evidence(self):
        action = "dossier.recordChronic"
        visit_id = self.visit("r001", "医生记录：确诊高血压。")
        foreign = self.visit("r002", "医生记录：确诊高血压。")
        self.note("intro", "家属说可能有糖尿病。")
        self.assertIsNone(self.view()["chronic"])
        aide = self.account("chronic-aide", ["care", "residents"])
        fields = {"residentId": "r001", "status": "confirmed", "requestId": "one", "confirmed": True,
                  "reviewNote": "", "items": [{"name": "高血压", "source": "", "visitId": visit_id},
                  {"name": "慢性肾脏病", "source": "人工核对外院出院小结", "visitId": ""}]}
        self.assertNotIn(action, self.store.snapshot(aide)["data"]["allowedActions"])
        with self.assertRaises(PermissionError):
            self.cmd(action, fields, aide)
        reviewer = self.account("chronic-read", ["medical", "clinical"])
        self.assertFalse(self.view(reviewer)["canRecordChronic"])
        with self.assertRaises(PermissionError):
            self.cmd(action, fields, reviewer)
        for updated in ({"confirmed": False}, {"items": []}, {"status": "none"},
                        {"items": [fields["items"][0], fields["items"][0]]},
                        {"items": [{"name": "高血压", "source": "", "visitId": foreign}]},
                        {"items": [{"name": "病历以外的诊断", "source": "", "visitId": visit_id}]},
                        {"items": [{"name": "高血压", "source": "", "visitId": ""}]}):
            with self.subTest(updated=updated), self.assertRaises(ValueError):
                self.cmd(action, {**fields, **updated})
        self.cmd(action, fields)
        self.cmd(action, fields)
        signed = self.view()["chronicHistory"]
        self.assertEqual(len(signed), 1)
        self.assertEqual(signed[0]["items"], fields["items"])
        self.assertEqual(self.view(aide)["chronic"]["items"], [{"name": "高血压"}, {"name": "慢性肾脏病"}])
        self.assertEqual(self.view(aide)["chronicHistory"], [])
        self.assertFalse(self.view(aide)["canRecordChronic"])
        self.assertIsNone(self.view(rid="r002")["chronic"])
        self.cmd(action, {**fields, "requestId": "two", "items": [], "status": "none", "reviewNote": "已核对更正资料"})
        self.assertEqual(self.view()["chronic"]["status"], "none")
        self.assertEqual(len(self.view()["chronicHistory"]), 2)
        self.assertEqual(self.view()["additions"], [])
        self.cmd("care.discharge", {"residentId": "r001", "reason": "家属接回"})
        self.assertFalse(self.view()["canRecordChronic"])
        with self.assertRaises(ValueError):
            self.cmd(action, {**fields, "requestId": "three"})
        with closing(self.store.connect()) as db:
            self.assertEqual(db.execute(
                "SELECT residentId FROM audit WHERE action=? LIMIT 1", (action,)
            ).fetchone()[0], "r001")

    def cloud(self, phrase):
        def send(_, body, **unused):
            inputs = json.loads(body["messages"][1]["content"])["摘录"]
            idx = next(i for i, _, text in inputs if phrase in text)
            raw = {
                "points": [
                    {
                        "source": idx,
                        "quote": phrase,
                        "text": "医生记录有" + phrase + "。",
                    }
                ]
            }
            return {
                "usage": {"total_tokens": 35},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(raw, ensure_ascii=False)},
                    }
                ],
            }

        with closing(self.store.connect()) as db, db:
            provider.grant(
                db, "synthetic-health", 160000, "2026-12-01", self.store.now()
            )
        self.addCleanup(patch.stopall)
        patch.dict("os.environ", {"DEEPSEEK_API_KEY": "fixture-only"}).start()
        return patch("platform_core.provider.deepseek.send", side_effect=send).start()

    def test_scoped_cloud_quotes_two_residents_manual_additions_and_deduplicated_draft(
        self,
    ):
        care = self.account("aide", ["care", "residents"])
        self.note("intro", "人工记录原健康简介。", token=care)
        self.note("addition", "行走时使用助行架。", token=care)
        self.note("conversation", "本人自述近来左膝不适。", token=care)
        self.note("conversation", "外人谈话密文", rid="r002", token=care)
        self.visit("r002", "外人就诊密文")
        self.visit("r001", "原文疾病甲")
        with closing(self.store.connect()) as db, db:
            db.execute(
                """INSERT INTO assistant_turns(actor,scope,generation,request,fingerprint,
                asked,answered,question,answer,hours) VALUES('owner','home','one','case','proof',?,?,
                '机构聊天隐私标记','全院聊天回复',24)""",
                (DAY, DAY),
            )
        chat = self.cloud("原文疾病甲")
        draft = self.draft()
        self.assertEqual(draft, self.draft())
        self.assertEqual(chat.call_count, 1)
        body = chat.call_args.args[1]["messages"][1]["content"]
        self.assertIn("本人自述近来左膝不适", body)
        self.assertIn("行走时使用助行架", body)
        self.assertNotIn("外人", body)
        self.assertNotIn("r001", body)
        self.assertNotIn("机构聊天隐私标记", body)
        self.assertEqual(self.view()["intro"]["text"], "人工记录原健康简介。")
        self.sign(draft)
        self.assertEqual(self.view()["intro"]["sources"][0]["quote"], "原文疾病甲")
        self.assertEqual(self.view(care)["intro"]["sources"], [])
        self.assertEqual(self.view(care)["intro"]["text"], "医生记录有原文疾病甲。")
        self.note("addition", "护士当面核实仍在使用助行架。", token=care)
        additions = self.view(care)["additions"]
        self.assertEqual(len(additions), 2)
        self.assertTrue(any("护士当面核实" in row["text"] for row in additions))
        self.assertFalse(any("外人" in row["text"] for row in additions))
        with self.assertRaises(PermissionError):
            self.draft(care)
        with self.assertRaises(PermissionError):
            self.sign(draft, care)

    def test_stale_evidence_wrong_chart_wrong_staff_and_missing_scope_cannot_publish(
        self,
    ):
        self.visit("r001", "病史乙")
        self.cloud("病史乙")
        staff = self.account("other-nurse", ["clinical", "medical", "care"])
        self.cmd("facility.addCampus", {"name": "测试分院"})
        campus = self.store.facility_resource(self.owner, "directory")["campuses"][-1][
            "id"
        ]
        outsider = self.account("campus-nurse", ["clinical", "medical", "medical.write", "care"], campus)
        draft = self.draft()
        for attempt in (
            lambda: self.view(outsider),
            lambda: self.draft(outsider),
            lambda: self.note("intro", "不应成功", token=outsider),
            lambda: self.sign(draft, outsider),
            lambda: self.cmd("dossier.recordChronic", {
                "residentId": "r001", "status": "none", "items": [], "reviewNote": "越区登记",
                "requestId": "no", "confirmed": True,
            }, outsider),
        ):
            with self.assertRaises(PermissionError):
                attempt()
        for attempt in (
            lambda: self.sign(draft, staff),
            lambda: self.sign(draft, rid="r002"),
            lambda: self.sign(draft, selected=[3]),
            lambda: self.sign(draft, confirmed=False),
        ):
            with self.assertRaises(ValueError):
                attempt()
        self.note("conversation", "长辈补充昨日膝部疼痛")
        with self.assertRaisesRegex(ValueError, "资料已更新"):
            self.sign(draft)
        self.assertIsNone(self.view()["intro"])

    def test_resident_opt_in_reads_only_confirmed_text_and_revocation_takes_effect(
        self,
    ):
        self.note("addition", "护理人员温馨补充。")
        self.note("conversation", "仅供后台的本人健康谈话")
        self.visit("r001", "原件记录丙病史")
        self.cloud("丙病史")
        draft = self.draft()
        self.sign(draft)
        self.cmd("dossier.recordChronic", {
            "residentId": "r001", "status": "confirmed", "requestId": "manual", "confirmed": True,
            "items": [{"name": "合成病名", "visitId": "", "source": "核对时的私有说明"}], "reviewNote": "",
        })
        for username, personal in (("elder-self", True), ("plain-relative", False)):
            self.cmd(
                "access.create",
                {
                    "kind": "family",
                    "username": username,
                    "displayName": username,
                    "password": PW,
                    "residentId": "r001",
                    "portalSelf": personal,
                },
            )
        token, self_user = self.store.login("elder-self", PW)
        relative, _ = self.store.login("plain-relative", PW)
        with self.assertRaises(PermissionError):
            self.view(token)
        self.cmd(
            "access.update", {"id": self_user["id"], "portalScopes": ["personalHealth"]}
        )
        page = self.view(token)
        self.assertEqual(page["chronic"], {"day": DAY, "status": "confirmed", "items": [{"name": "合成病名"}]})
        self.assertNotIn("chronicHistory", page)
        self.assertEqual(
            page["intro"], {"kind": "ai", "text": "医生记录有丙病史。", "day": DAY}
        )
        self.assertEqual(
            page["additions"],
            [{"kind": "addition", "text": "护理人员温馨补充。", "day": DAY}],
        )
        self.assertEqual(page["conversations"], [])
        self.assertFalse(page["canGenerate"] or page["canWrite"])
        for attempt in (
            lambda: self.view(relative),
            lambda: self.view(token, "r002"),
            lambda: self.draft(token),
            lambda: self.note("addition", "尝试写入", token=token),
        ):
            with self.assertRaises(PermissionError):
                attempt()
        self.cmd("access.update", {"id": self_user["id"], "portalScopes": []})
        with self.assertRaises(PermissionError):
            self.view(token)

    def test_archived_records_are_read_only_and_unverified_quotes_are_rejected(self):
        self.note("intro", "已核对的个人病史。")
        self.note("addition", "护理补充。", requestId="once")
        self.note("addition", "护理补充。", requestId="once")
        self.assertEqual(len(self.view()["additions"]), 1)
        with self.assertRaises(ValueError):
            self.note("addition", "不同内容", requestId="once")
        self.cmd("care.discharge", {"residentId": "r001", "reason": "家属接回"})
        self.assertFalse(self.view()["canWrite"])
        self.assertEqual(self.view()["intro"]["text"], "已核对的个人病史。")
        with self.assertRaises(ValueError):
            self.draft()
        with self.assertRaises(ValueError):
            self.note("intro", "修改归档")
        from platform_core.resident_health_evidence import validate

        for raw in (
            {"points": [{"source": 1, "text": "更改剂量", "quote": "错误引用"}]},
            {"points": [{"source": True, "text": "某病", "quote": "原文"}]},
        ):
            with self.assertRaises(ValueError):
                validate(raw, [{"value": "原文"}])
