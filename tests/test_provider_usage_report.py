"""Check owner scope, date boundaries and report attribution without a cloud request."""

from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from platform_core import provider
from platform_core.provider import usage_report
from platform_core.store import Store


DAY = datetime(2026, 11, 24, 15, tzinfo=provider.ZONE)


class ReportTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(
            Path(folder.name) / "usage.db",
            now=lambda: DAY,
            initial_owner_password="usage-owner-private",
        )
        self.owner, actor = self.store.login("owner", "usage-owner-private")
        self.owner_id = actor["id"]
        self.staff = self._staff("nurse-one")
        self.other = self._staff("nurse-two")
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "用量测试套餐", 2_000_000, "2026-11-30", now=DAY)
            self.plan = provider.latest(db)["id"]
        self.staff_id = self.store.version(self.staff)["userId"]
        self.other_id = self.store.version(self.other)["userId"]

    def _staff(self, username):
        self.store.execute(
            "access.create",
            {
                "username": username,
                "displayName": "同名护士",
                "password": "usage-staff-private",
                "kind": "staff",
                "role": "护士",
            },
            self.store.version(self.owner)["revision"],
            self.owner,
        )
        return self.store.login(username, "usage-staff-private")[0]

    def _token(
        self,
        db,
        who,
        request,
        *,
        at=DAY,
        feature=None,
        billing=0,
        split=(None,) * 5,
        status="ok",
        reason="",
        attributed=None,
        reserved=1000,
    ):
        db.execute(
            """INSERT INTO api_usage(actor,request,planId,fingerprint,model,createdAt,status,allowance,
                charged,reason,feature,attributedActor,providerTokens,inputTokens,cachedInputTokens,
                uncachedInputTokens,outputTokens)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                who,
                request,
                self.plan,
                "internal-fingerprint",
                "deepseek-flash",
                int(at.timestamp()),
                status,
                reserved,
                billing,
                reason,
                feature,
                attributed,
                *split,
            ),
        )

    def _media(
        self,
        db,
        receipt,
        kind,
        charged,
        *,
        state="complete",
        reference="",
        feature=None,
    ):
        db.execute(
            """INSERT INTO media_usage(id,plan,kind,actor,fingerprint,at,state,reserved,charged,reference,original,feature)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                receipt,
                self.plan,
                kind,
                self.staff_id,
                "internal-media-fingerprint",
                int(DAY.timestamp()),
                state,
                100,
                charged,
                reference,
                b"private original bytes",
                feature,
            ),
        )

    def test_one_task_groups_runtime_handoffs_without_revealing_other_jobs(self):
        from platform_core.provider import task_usage
        key = task_usage.identifier("chat", self.staff_id, "合成请求")
        with closing(self.store.connect()) as db, db:
            with self.assertRaises(ValueError), task_usage.scope("pi", key):
                self.fail("旧运行时不能接受新作业")
            with task_usage.scope("platform", key):
                self._token(db, self.staff_id, "plan", billing=13)
                task_usage.attach(db, "tokens", self.staff_id, "plan")
                with task_usage.scope("deerflow", key):
                    self._token(db, "health-review", "draft", billing=23, attributed=self.staff_id)
                    task_usage.attach(db, "tokens", "health-review", "draft")
                self._media(db, "attachment", "ocr", 4)
                task_usage.attach(db, "media", self.staff_id, "attachment")
            # Retain a pre-migration receipt exactly as an upgraded ledger stores it.
            db.execute("UPDATE agent_task_usage SET runtime='pi' WHERE taskId=? AND receipt='plan'", (key,))
            self._token(db, self.staff_id, "unrelated", billing=100)
            task_usage.attach(db, "tokens", self.staff_id, "unrelated")
        report = usage_report.read(self.store, self.owner, {"taskId": key})
        self.assertEqual(report["summary"]["tokens"], 36)
        self.assertEqual(report["summary"]["ocrPages"], 4)
        self.assertCountEqual([r["runtime"] for r in report["records"]["items"]], ["pi","deerflow","platform"])
        with self.assertRaises(PermissionError):
            usage_report.read(self.store, self.staff, {"taskId": key})
        with self.assertRaises(ValueError):
            usage_report.read(self.store, self.owner, {"taskId": "姓名"})

    def test_reports_only_confirmed_units_and_keeps_missing_breakdowns_distinct(self):
        with closing(self.store.connect()) as db, db:
            self._token(
                db,
                self.staff_id,
                "chat/alpha",
                feature="assistant.chat",
                billing=100,
                split=(100, 80, 30, 50, 20),
            )
            self._token(db, self.other_id, "chat/beta", billing=15)
            self._token(
                db,
                "rounds-agent",
                "generation/xxx",
                feature="care.roundNarrative",
                billing=45,
                split=(45, 35, 0, 35, 10),
                attributed=self.staff_id,
            )
            self._token(db, "change-review", "generation/yyy", billing=7)
            self._token(db, self.staff_id, "generation/unknown", billing=6)
            self._token(
                db,
                self.staff_id,
                "chat/pending",
                status="uncertain",
                feature="assistant.chat",
                reserved=77,
            )
            self._media(db, "ocr-1", "ocr", 4)
            self._media(db, "ocr-visit", "ocr", 2, feature="dossier.visitOcr")
            self._media(db, "voice-1", "asr", 8, reference="chat-voice:opaque-context")
            self._media(db, "tts-1", "tts", 12)
            db.execute(
                "INSERT INTO api_search_usage(actor,request,planId,createdAt,status,verified) VALUES(?,?,?,?,?,?)",
                (self.staff_id, "web", self.plan, int(DAY.timestamp()), "empty", None),
            )
            db.execute(
                "INSERT INTO api_search_usage(actor,request,planId,createdAt,status,verified) VALUES(?,?,?,?,?,?)",
                (self.other_id, "web", self.plan, int(DAY.timestamp()), "ok", 1),
            )
        report = usage_report.read(self.store, self.owner, {})
        stats = report["summary"]
        self.assertEqual(
            stats
            | {
                "calls": 12,
                "pendingCalls": 1,
                "tokens": 173,
                "reservedTokens": 77,
                "inputTokens": 115,
                "cacheHitTokens": 30,
                "cacheMissTokens": 85,
                "outputTokens": 30,
                "unclassifiedTokenCalls": 3,
                "unclassifiedCacheCalls": 3,
                "ocrPages": 6,
                "asrSeconds": 8,
                "ttsCharacters": 12,
                "searchCalls": 1,
            },
            stats,
        )
        self.assertEqual(
            report["range"],
            {"start": "2026-11-01", "end": "2026-11-24", "timeZone": "Asia/Shanghai"},
        )
        self.assertEqual(report["byDay"][0]["id"], "2026-11-24")
        sources = {item["id"]: item for item in report["byFeature"]}
        self.assertEqual(sources["legacy.ocr"]["ocrPages"], 4)
        self.assertEqual(sources["dossier.visitOcr"]["ocrPages"], 2)
        self.assertEqual(sources["assistant.voiceAsr"]["asrSeconds"], 8)
        self.assertEqual(sources["workflow.changeReview"]["tokens"], 7)
        self.assertNotIn("rounds-agent", {row["id"] for row in report["actors"]})
        names = {row["id"]: row["label"] for row in report["actors"]}
        self.assertNotEqual(names[self.staff_id], names[self.other_id])
        self.assertNotIn("private original bytes", json.dumps(report))
        self.assertNotIn("internal-fingerprint", json.dumps(report))
        scoped = usage_report.read(
            self.store,
            self.owner,
            {"actorId": self.staff_id, "feature": "care.roundNarrative"},
        )
        self.assertEqual(scoped["summary"]["tokens"], 45)
        self.assertEqual(scoped["records"]["items"][0]["cacheHitTokens"], 0)
        self.assertEqual({a["id"] for a in scoped["actors"]}, set(names))

    def test_late_receipt_reconciliation_shows_split_only_when_totals_match(self):
        with closing(self.store.connect()) as db, db:
            self._token(
                db,
                self.staff_id,
                "chat/match",
                billing=10,
                status="closed",
                reason="reconciled",
                split=(20, 16, 4, 12, 4),
            )
            self._token(
                db,
                self.staff_id,
                "chat/mismatch",
                billing=10,
                status="closed",
                reason="reconciled",
                split=(20, 16, 4, 12, 4),
            )
            self._token(
                db,
                self.staff_id,
                "chat/wait",
                billing=10,
                status="closed",
                reason="reconciled",
                split=(20, 16, 4, 12, 4),
            )
            db.executemany(
                """INSERT INTO api_late_usage(actor,request,original,reported,receivedAt,verified)
                   VALUES(?,?,10,20,?,?)""",
                [
                    (self.staff_id, name, int(DAY.timestamp()), value)
                    for name, value in (
                        ("chat/match", 20),
                        ("chat/mismatch", 25),
                        ("chat/wait", None),
                    )
                ],
            )
        report = usage_report.read(self.store, self.owner, {})
        self.assertEqual(report["summary"]["tokens"], 55)
        self.assertEqual(report["summary"]["reservedTokens"], 10)
        self.assertEqual(report["summary"]["cacheHitTokens"], 4)
        self.assertEqual(report["summary"]["unclassifiedCacheCalls"], 2)
        payload = {row["amount"]: row for row in report["records"]["items"]}
        self.assertIsNone(payload[25]["cacheHitTokens"])
        self.assertEqual(payload[10]["status"], "review")

    def test_local_midnight_pagination_and_owner_permission(self):
        with closing(self.store.connect()) as db, db:
            for i in range(52):
                self._token(db, self.staff_id, f"chat/{i}", billing=1)
            for request, at in (
                (
                    "chat/previous-day",
                    datetime(2026, 11, 23, 23, 59, tzinfo=provider.ZONE),
                ),
                (
                    "chat/first-minute",
                    datetime(2026, 11, 24, 0, 0, tzinfo=provider.ZONE),
                ),
                ("chat/next-day", datetime(2026, 11, 25, 0, 0, tzinfo=provider.ZONE)),
            ):
                self._token(db, self.staff_id, request, at=at, billing=1)
        start_end = {"start": "2026-11-24", "end": "2026-11-24"}
        report = usage_report.read(self.store, self.owner, {**start_end, "page": "2"})
        self.assertEqual(report["summary"]["calls"], 53)
        self.assertEqual(len(report["records"]["items"]), 3)
        self.assertTrue(
            report["records"]["items"][-1]["at"].startswith("2026-11-24T00:00")
        )
        self.assertEqual(report["summary"]["cacheHitTokens"], None)
        self.assertEqual(report["summary"]["unclassifiedCacheCalls"], 53)
        with self.assertRaises(PermissionError):
            usage_report.read(self.store, self.staff, start_end)
        with self.assertRaises(ValueError):
            usage_report.read(self.store, self.owner, {"start": "2020-01-01"})
        with self.assertRaises(ValueError):
            usage_report.read(self.store, self.owner, {"end": "2026-11-25"})
