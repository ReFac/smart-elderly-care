"""Task-independent voice input stays scoped, metered and reviewable inside the Agent workbench."""

from contextlib import closing
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from provider_fixture import isolate_credentials
from test_deepseek_media import sample_wav
from platform_core import provider
from platform_core.provider import media, speech
from platform_core.store import Store, TIMEZONE


class AgentVoiceTests(unittest.TestCase):
    def setUp(self):
        from provider_fixture import simulate_narration

        simulate_narration(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        isolate_credentials(self, tmp.name)
        self.password = "temporary-agent-voice-test"
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": self.password}):
            self.store = Store(
                Path(tmp.name) / "test.sqlite",
                lambda: datetime(2026, 11, 24, 9, tzinfo=TIMEZONE),
            )
        self.owner, _ = self.store.login("owner", self.password)
        self.raw = sample_wav()
        self.reply = {
            "text": "核对护理工单",
            "duration_ms": 980,
            "request_id": "fixture-only",
        }
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "模拟语音套餐", 100, "2029-01-01", self.store.now())
            self.plan = provider.latest(db)["id"]
            media.grant(db, self.plan, "asr", 10)
        self.key = patch.object(media, "read_key", return_value="fixture-key")
        self.key.start()
        self.addCleanup(self.key.stop)
        self.staff = self.user("voice-worker", ["assistants", "voice", "care"])

    def command(self, token, action, payload):
        return self.store.execute(
            action, payload, self.store.version(token)["revision"], token
        )

    def user(self, name, permissions):
        self.command(
            self.owner,
            "access.create",
            {
                "username": name,
                "kind": "staff",
                "displayName": name,
                "role": "自定义",
                "permissions": permissions,
                "password": self.password,
            },
        )
        return self.store.login(name, self.password)[0]

    def recognize(self, token=None, scope=None, consent=True):
        return speech.recognize_agent(
            self.store, token or self.staff, scope, self.raw, consent
        )

    def test_edit_transcript_send_reuse_then_human_publication(self):
        before = self.store.snapshot(self.owner)["data"]
        with patch.object(media, "invoke", return_value=self.reply) as call:
            review = self.recognize()
            self.assertEqual(review, self.recognize())
            call.assert_called_once()
        current = self.store.snapshot(self.owner)["data"]
        for key in ("voiceQueue", "agentRuns", "tasks", "suggestions"):
            self.assertEqual(current[key], before[key])
        fields = {
            "goal": "核对今日护理工单",
            "scope": "care",
            "requestId": "utterance-one",
            "voiceTranscriptId": review["transcriptId"],
        }
        run_id = self.command(self.staff, "agent.start", fields)["runId"]
        self.assertEqual(
            self.command(self.staff, "agent.start", fields)["runId"], run_id
        )
        report = self.store.agent_resource(self.staff, "runs", run_id)
        self.assertEqual(report["status"], "awaiting_approval")
        self.assertEqual(report["goal"], fields["goal"])
        self.assertEqual(
            before["suggestions"],
            self.store.snapshot(self.owner)["data"]["suggestions"],
        )
        self.command(self.staff, "agent.publish", {"runId": run_id})
        self.assertGreater(
            len(self.store.snapshot(self.owner)["data"]["suggestions"]),
            len(before["suggestions"]),
        )
        with closing(self.store.connect()) as db:
            self.assertEqual(media.amounts(db, self.plan, "asr")["used"], 1)
            self.assertEqual(
                db.execute("SELECT original FROM media_usage").fetchone()[0], self.raw
            )
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM audit WHERE action='media.agentVoice'"
                ).fetchone()[0],
                2,
            )
        self.assertNotIn(self.reply["text"].encode(), self.store.path.read_bytes())

    def test_receipts_are_specific_to_author_region_and_workflow(self):
        task = next(
            t["id"]
            for t in self.store.snapshot(self.owner)["data"]["tasks"]
            if t["status"] == "待执行"
            and t["date"] <= self.store.now().date().isoformat()
        )
        room = self.store.facility_resource(self.owner, "directory")["buildings"][0][
            "floors"
        ][0]["id"]
        region = {"floorId": room}
        with patch.object(media, "invoke", return_value=self.reply):
            free = self.recognize(scope=region)["transcriptId"]
            task_receipt = self.store.transcribe(self.staff, task, self.raw, True)[
                "transcriptId"
            ]
        self.assertNotEqual(free, task_receipt)
        run = {
            "goal": "核对护理",
            "requestId": "cross-context",
            "region": region,
            "voiceTranscriptId": free,
        }
        for token, payload in [
            (self.owner, run),
            (self.staff, {k: v for k, v in run.items() if k != "region"}),
            (self.staff, {**run, "voiceTranscriptId": task_receipt}),
        ]:
            with self.assertRaisesRegex(ValueError, "不匹配"):
                self.command(token, "agent.start", payload)
        with self.assertRaises(ValueError):
            self.command(
                self.staff,
                "gw.propose",
                {
                    "requestId": "bad-proposal",
                    "taskId": task,
                    "note": "待核对",
                    "transcript": self.reply["text"],
                    "transcriptId": free,
                },
            )

    def test_grants_consent_region_and_midflight_revocation(self):
        no_voice = self.user("text-worker", ["assistants", "care"])
        no_workbench = self.user("care-only", ["voice", "care"])
        no_domain = self.user("no-domain", ["assistants", "voice"])
        with patch.object(media, "invoke") as send:
            for token in (no_voice, no_workbench, no_domain):
                with self.assertRaises(PermissionError):
                    self.recognize(token=token)
            with self.assertRaisesRegex(ValueError, "确认"):
                self.recognize(consent=False)
            with self.assertRaises(ValueError):
                self.recognize(scope={"bogus": "unknown"})
            with patch.object(
                self.store, "facility_policy", lambda *_: {"roomIds": []}
            ):
                with self.assertRaisesRegex(PermissionError, "必须选择"):
                    self.recognize()
            send.assert_not_called()

            def revoke(*args):
                self.store.facility_policy = lambda *_: {"roomIds": []}
                return self.reply

            send.side_effect = revoke
            with self.assertRaises(PermissionError):
                self.recognize()
        with closing(self.store.connect()) as db:
            self.assertEqual(media.amounts(db, self.plan, "asr")["used"], 1)

    def test_history_rechecks_all_spoken_business_domains(self):
        worker = self.user("coordinator", ["voice", "assistants", "care", "finance"])
        actor = self.store.snapshot(worker)["data"]["user"]
        with patch.object(media, "invoke", return_value=self.reply):
            receipt = self.recognize(worker)["transcriptId"]
        events = [
            r
            for r in self.store.history(worker)["rows"]
            if r["action"] == "media.agentVoice"
        ]
        self.assertEqual(len(events), 2)
        self.command(
            self.owner,
            "access.update",
            {"id": actor["id"], "permissions": ["voice", "assistants", "care"]},
        )
        worker, _ = self.store.login("coordinator", self.password)
        self.assertFalse(
            any(
                r["action"] == "media.agentVoice"
                for r in self.store.history(worker)["rows"]
            )
        )
        with self.assertRaises(ValueError):
            self.command(
                worker,
                "agent.start",
                {
                    "requestId": "after-revoke",
                    "goal": "护理",
                    "voiceTranscriptId": receipt,
                },
            )
