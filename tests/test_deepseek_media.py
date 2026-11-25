"""DeepSeek media is separately metered and its authenticated transcript is only a proposal."""

from contextlib import closing
from datetime import datetime
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

from provider_fixture import isolate_credentials
from platform_core import provider
from platform_core.provider import media, speech
from platform_core.store import Store


def sample_wav(frames=16000):
    out = BytesIO()
    with wave.open(out, "wb") as dst:
        dst.setparams((1, 2, 16000, frames, "NONE", ""))
        dst.writeframes(bytes(frames * 2))
    return out.getvalue()


class MediaTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        isolate_credentials(self, folder.name)
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": "temporary-test-password"}):
            self.store = Store(
                Path(folder.name) / "media.sqlite3",
                now=lambda: datetime.fromisoformat("2026-11-24T12:00:00+08:00"),
            )
        self.token, self.owner = self.store.login("owner", "temporary-test-password")
        data = self.store.snapshot(self.token)["data"]
        self.task = next(
            t["id"]
            for t in data["tasks"]
            if t["status"] == "待执行"
            and t["date"] <= self.store.now().date().isoformat()
        )
        self.raw = sample_wav(16001)
        self.reply = {
            "request_id": "test-speech-id",
            "duration_ms": 1001,
            "text": "合成测试内容",
        }
        self.command(
            "access.create",
            {
                "username": "test-worker",
                "displayName": "测试人员",
                "kind": "staff",
                "role": "自定义",
                "permissions": ["care", "voice", "voice.confirm"],
                "password": "temporary-test-password",
            },
        )
        self.worker, _ = self.store.login("test-worker", "temporary-test-password")
        key = patch.object(media, "read_key", return_value="test-key")
        key.start()
        self.addCleanup(key.stop)

    def command(self, action, values, actor=None):
        actor = actor or self.token
        return self.store.execute(
            action, values, self.store.version(actor)["revision"], actor
        )

    def grant(self):
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "测试识别额度", 100, "2029-01-01", self.store.now())
            self.plan = provider.latest(db)["id"]
            media.grant(db, self.plan, "asr", 2)

    def call(self, consent=True, token=None):
        return self.store.transcribe(token or self.worker, self.task, self.raw, consent)

    def test_transcript_bound_to_task_author_and_manual_confirmation(self):
        self.grant()
        with patch.object(media, "invoke", return_value=self.reply) as invoke:
            result = self.call()
            self.assertEqual(self.call(), result)
            invoke.assert_called_once_with(
                "asr", self.raw, "speech.wav", "audio/wav", "test-key"
            )
            self.assertEqual(self.store.snapshot(self.token)["data"]["voiceQueue"], [])
            proposal = {
                "requestId": "synthetic",
                "taskId": self.task,
                "transcriptId": result["transcriptId"],
                "transcript": result["text"],
                "note": "核实过的工单完成记录",
            }
            with self.assertRaises(ValueError):
                self.command("gw.propose", proposal, self.token)
            with self.assertRaises(ValueError):
                self.command(
                    "gw.propose", {**proposal, "transcript": "篡改原文"}, self.worker
                )
            self.command("gw.propose", proposal, self.worker)
            snapshot = self.store.snapshot(self.token)["data"]
            self.assertEqual(
                next(t["status"] for t in snapshot["tasks"] if t["id"] == self.task),
                "待执行",
            )
            pending = snapshot["voiceQueue"][0]
            self.assertTrue({"transcript", "note", "transcriptId"}.isdisjoint(pending))
            self.assertEqual(
                self.store.voice_proposal(self.token, pending["id"]),
                {"note": proposal["note"], "transcript": result["text"]},
            )
            with patch.object(
                self.store, "facility_policy", lambda db, actor: {"roomIds": []}
            ):
                self.assertEqual(
                    self.store.snapshot(self.worker)["data"]["voiceQueue"], []
                )
                with self.assertRaises(PermissionError):
                    self.call()
                with self.assertRaises(PermissionError):
                    self.store.voice_proposal(self.worker, pending["id"])
                with self.assertRaises(PermissionError):
                    self.command(
                        "gw.confirm", {"proposalId": pending["id"]}, self.worker
                    )
            self.command("gw.confirm", {"proposalId": snapshot["voiceQueue"][0]["id"]})
            self.assertEqual(self.store.snapshot(self.worker)["data"]["voiceQueue"], [])
            with self.assertRaisesRegex(ValueError, "已由其他人员处理"):
                self.store.voice_proposal(self.token, pending["id"])
            with self.assertRaisesRegex(ValueError, "可办理"):
                self.call()
        with closing(self.store.connect()) as db:
            self.assertEqual(
                media.amounts(db, self.plan, "asr"),
                {"limit": 2, "used": 2, "held": 0, "unit": "秒"},
            )
            self.assertEqual(provider.usage(db, self.plan), (0, 0))
            self.assertEqual(
                db.execute("SELECT original FROM media_usage").fetchone()[0], self.raw
            )

    def test_denied_requests_never_upload_and_inflight_revocation_keeps_metering(self):
        with patch.object(media, "invoke") as invoke:
            with self.assertRaisesRegex(ValueError, "确认"):
                self.call(consent=False)
            with self.assertRaisesRegex(ValueError, "尚未开通"):
                self.call()
            self.grant()
            with self.assertRaises(PermissionError):
                self.command(
                    "access.mediaSettings", {"ocr": True, "asr": False}, self.worker
                )
            self.command("access.mediaSettings", {"ocr": True, "asr": False})
            with self.assertRaisesRegex(PermissionError, "停用"):
                self.call()
            self.command("access.mediaSettings", {"ocr": True, "asr": True})
            with patch.object(
                self.store, "facility_policy", lambda _db, actor: {"campusIds": []}
            ):
                with self.assertRaises(PermissionError):
                    self.call()
            invoke.assert_not_called()

            def revoke(*_):
                self.store.facility_policy = lambda _db, _actor: {"campusIds": []}
                return self.reply

            invoke.side_effect = revoke
            with self.assertRaises(PermissionError):
                self.call()
            invoke.assert_called_once()
        with closing(self.store.connect()) as db:
            self.assertEqual(media.amounts(db, self.plan, "asr")["used"], 2)

    def test_unlimited_asr_transcribes_after_cap_while_preserving_usage(self):
        self.grant()
        with patch.object(media, "invoke", return_value=self.reply) as invoke, patch.object(
            provider, "configured", return_value=True
        ):
            self.call()
            self.raw = sample_wav(16002)
            self.assertEqual(self.store.snapshot(self.worker)["data"]["assistantVoice"]["state"], "exhausted")
            with self.assertRaisesRegex(ValueError, "剩余额度不足"):
                self.call()
            invoke.assert_called_once()
            with closing(self.store.connect()) as db, db:
                media.grant(db, self.plan, "ocr", 6)
                media.allow_unlimited_asr(db)
            self.assertEqual(self.store.snapshot(self.worker)["data"]["assistantVoice"]["state"], "available")
            self.assertEqual(self.call()["text"], self.reply["text"])
            self.assertEqual(invoke.call_count, 2)

        with closing(self.store.connect()) as db, db:
            self.assertEqual(media.amounts(db, self.plan, "asr"), {"limit": None, "used": 4, "held": 0, "unit": "秒"})
            self.assertEqual(media.amounts(db, self.plan, "ocr")["limit"], 6)
            with self.assertRaisesRegex(ValueError, "不能低于"):
                media.grant(db, self.plan, "asr", 3)
            self.assertIsNone(media.amounts(db, self.plan, "asr")["limit"])
            media.grant(db, self.plan, "asr", 4)
            self.assertEqual(media.amounts(db, self.plan, "asr")["limit"], 4)

    def test_unlimited_asr_persists_when_operator_renews_plan(self):
        self.grant()
        with closing(self.store.connect()) as db, db:
            media.allow_unlimited_asr(db)
            renewal = datetime.fromisoformat("2029-01-02T12:00:00+08:00")
            provider.grant(db, "测试机构续期", 100, "2029-12-31", renewal)
            plan = provider.latest(db)["id"]
            self.assertNotEqual(plan, self.plan)
            self.assertIsNone(media.amounts(db, plan, "asr")["limit"])

    def test_uncertain_delivery_holds_allowance_until_operator_reconciles(self):
        self.grant()
        with patch.object(
            media, "invoke", side_effect=media.MediaError("连接中断", uncertain=True)
        ) as invoke:
            with self.assertRaisesRegex(ValueError, "连接中断"):
                self.call()
            with self.assertRaisesRegex(ValueError, "待平台核对"):
                self.call()
            invoke.assert_called_once()
        with closing(self.store.connect()) as db, db:
            self.assertEqual(media.amounts(db, self.plan, "asr")["held"], 2)
            call = db.execute("SELECT id FROM media_usage").fetchone()[0]
            media.reconcile(db, call, 0, self.store.now())
            self.assertEqual(media.amounts(db, self.plan, "asr")["held"], 0)
        with patch.object(media, "invoke", return_value=self.reply):
            self.assertEqual(self.call()["text"], self.reply["text"])

    def test_uploaded_wav_retains_original_locally_and_only_sends_audio_samples(self):
        self.grant()
        pcm = self.raw
        private = b"Test clinic tag: fixture person"
        self.raw = (
            pcm[:4]
            + (len(pcm) - 8 + 8 + len(private)).to_bytes(4, "little")
            + pcm[8:]
            + b"JUNK"
            + len(private).to_bytes(4, "little")
            + private
        )
        with patch.object(media, "invoke", return_value=self.reply) as send:
            self.call()
            self.assertEqual(send.call_args.args[1], pcm)
        with closing(self.store.connect()) as db:
            self.assertEqual(
                db.execute("SELECT original FROM media_usage").fetchone()[0], self.raw
            )

    def test_silent_audio_receipt_settles_only_once_and_creates_no_proposal(self):
        self.grant()
        with patch.object(
            media, "invoke", return_value={**self.reply, "text": ""}
        ) as send:
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, "未识别到可用语音"):
                    self.call()
            send.assert_called_once()
        with closing(self.store.connect()) as db:
            self.assertEqual(media.amounts(db, self.plan, "asr")["used"], 2)
        self.assertEqual(self.store.snapshot(self.token)["data"]["voiceQueue"], [])

    def test_multipart_request_uses_documented_fields_and_generic_filename(self):
        client = BytesIO(b'\n{"request_id":"test","duration_ms":100,"text":"ok"}')
        with patch.object(media, "build_opener") as factory:
            factory.return_value.open.return_value = client
            result = media.invoke(
                "asr", self.raw, "speech.wav", "audio/wav", "fixture-key"
            )
            req = factory.return_value.open.call_args.args[0]
            self.assertEqual(req.full_url, "https://api.deepseek.com/v1/tools/asr")
            self.assertEqual(req.get_header("Authorization"), "Bearer fixture-key")
            self.assertIn(b'name="file"; filename="speech.wav"', req.data)
            self.assertNotIn(b'name="model"', req.data)
            self.assertNotIn(b'name="purpose"', req.data)
            self.assertEqual(result["text"], "ok")
        for raw in (b"not audio", self.raw[:-1], b"OggS", sample_wav(16000 * 120 + 1)):
            with self.assertRaises(ValueError):
                speech.audio_spec(raw)
