"""Audio compatibility is tested with in-memory provider replies."""

from contextlib import closing
from datetime import datetime
from email.message import Message
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from provider_fixture import isolate_credentials
from test_deepseek_media import sample_wav
from platform_core import provider
from platform_core.agents import chat
from platform_core.provider import audio_adapters, media, read_aloud, speech
from platform_core.store import Store


def response(body, request_id=None):
    stream = BytesIO(body)
    stream.headers = Message()
    if request_id:
        stream.headers["X-Request-Id"] = request_id
    return stream


class AudioGatewayTests(unittest.TestCase):
    def test_openai_asr_uses_native_endpoint_and_requires_credential(self):
        with patch.dict(
            "os.environ",
            {
                "NH_ASR_PROVIDER": "openai",
                "NH_ASR_ENDPOINT": "https://audio.example.com/custom",
            },
            clear=True,
        ):
            service = audio_adapters.options("asr")
            self.assertEqual(
                service.url, "https://api.openai.com/v1/audio/transcriptions"
            )
            self.assertEqual(service.model, "gpt-transcribe")
            with self.assertRaisesRegex(ValueError, "凭据"):
                service.key()

    def test_openai_speech_uses_provider_voice_and_transport(self):
        raw = sample_wav()
        settings = {
            "NH_TTS_PROVIDER": "openai",
            "NH_TTS_MODEL": "speech-test-v1",
            "NH_TTS_VOICE": "marin",
            "OPENAI_API_KEY": "fake-openai-key",
        }
        with (
            patch.dict("os.environ", settings, clear=True),
            patch.object(
                audio_adapters.connection, "open_request", return_value=response(raw)
            ) as call,
        ):
            service = audio_adapters.options("tts")
            self.assertEqual(
                audio_adapters.synthesize(service, service.key(), "请核对这条记录。"),
                raw,
            )
        req = call.call_args.args[0]
        self.assertEqual(req.full_url, "https://api.openai.com/v1/audio/speech")
        self.assertEqual(req.get_header("Authorization"), "Bearer fake-openai-key")
        self.assertEqual(
            json.loads(req.data),
            {
                "model": "speech-test-v1",
                "input": "请核对这条记录。",
                "voice": "marin",
                "response_format": "wav",
            },
        )

    def test_compatible_tts_rejects_untrusted_http_and_malformed_wav(self):
        settings = {"NH_TTS_PROVIDER": "compatible", "NH_TTS_MODEL": "my-tts"}
        with patch.dict("os.environ", settings, clear=True):
            with patch.dict(
                "os.environ", {"NH_TTS_ENDPOINT": "http://audio.example.com/speech"}
            ):
                with self.assertRaisesRegex(ValueError, "HTTPS"):
                    audio_adapters.options("tts")
            with patch.dict(
                "os.environ",
                {"NH_TTS_ENDPOINT": "http://127.0.0.1:8000/v1/audio/speech"},
            ):
                service = audio_adapters.options("tts")
                self.assertEqual(service.key(), "")
                with (
                    patch.object(
                        audio_adapters.connection,
                        "open_request",
                        return_value=response(sample_wav()[:-1]),
                    ) as call,
                    self.assertRaisesRegex(ValueError, "中断"),
                ):
                    audio_adapters.synthesize(service, service.key(), "确认")
                self.assertIsNone(call.call_args.args[0].get_header("Authorization"))


class AudioGatewayUsageTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        isolate_credentials(self, folder.name)
        self.settings = {
            "NH_ASR_PROVIDER": "compatible",
            "NH_ASR_MODEL": "my-asr",
            "NH_ASR_ENDPOINT": "http://127.0.0.1:8085/v1/audio/transcriptions",
            "NH_ASR_API_KEY": "",
        }
        env = patch.dict("os.environ", self.settings)
        env.start()
        self.addCleanup(env.stop)
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": "temporary-test-password"}):
            self.store = Store(
                Path(folder.name) / "voice.sqlite3",
                now=lambda: datetime.fromisoformat("2026-11-24T12:00:00+08:00"),
            )
        self.token, _ = self.store.login("owner", "temporary-test-password")
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "测试套餐", 10000, "2029-01-01", self.store.now())
            self.plan = provider.latest(db)["id"]
            media.allow_unlimited_asr(db)

    def recognize(self):
        return speech.recognize_agent(
            self.store, self.token, None, sample_wav(16001), True, conversation=True
        )

    def test_compatible_asr_checks_duration_and_preserves_unlimited_usage(self):
        service = self.store.snapshot(self.token)["data"]["assistantVoice"]
        self.assertEqual(
            (service["state"], service["provider"]), ("available", "兼容语音服务")
        )
        with (
            patch.object(
                audio_adapters.connection,
                "open_request",
                return_value=response(
                    b'{"text":"test transcript","duration_ms":5}', "test-audio-receipt"
                ),
            ) as call,
            patch.object(media, "read_key") as legacy,
        ):
            result = self.recognize()
            self.assertEqual(self.recognize(), result)
            legacy.assert_not_called()
        call.assert_called_once()
        req = call.call_args.args[0]
        self.assertEqual(req.full_url, self.settings["NH_ASR_ENDPOINT"])
        self.assertIn(b'name="model"\r\n\r\nmy-asr\r\n', req.data)
        self.assertIn(b'filename="speech.wav"\r\nContent-Type: audio/wav\r\n', req.data)
        self.assertIsNone(req.get_header("Authorization"))
        self.assertEqual(
            (result["text"], result["durationMs"]), ("test transcript", 1001)
        )
        with closing(self.store.connect()) as db:
            self.assertEqual(
                media.amounts(db, self.plan, "asr"),
                {
                    "limit": None,
                    "used": 2,
                    "held": 0,
                    "unit": "秒",
                },
            )
            self.assertEqual(
                db.execute("SELECT vendor_id FROM media_usage").fetchone()[0],
                "test-audio-receipt",
            )

    def test_uncertain_compatible_asr_does_not_upload_twice(self):
        error = HTTPError(
            self.settings["NH_ASR_ENDPOINT"], 504, "unavailable", {}, BytesIO()
        )
        with patch.object(
            audio_adapters.connection, "open_request", side_effect=error
        ) as call:
            with self.assertRaisesRegex(ValueError, "504"):
                self.recognize()
            with self.assertRaisesRegex(ValueError, "待平台核对"):
                self.recognize()
            call.assert_called_once()
        with closing(self.store.connect()) as db:
            self.assertEqual(media.amounts(db, self.plan, "asr")["held"], 2)

    def test_configured_tts_reads_only_authorized_voice_replies_and_meters_chars(self):
        with patch.object(
            audio_adapters.connection,
            "open_request",
            return_value=response(b'{"text":"test"}'),
        ):
            receipt = self.recognize()["transcriptId"]
        with closing(self.store.connect()) as db, db:
            user, scope, *_ = chat.conversation(self.store, db, self.token, None)
            db.execute(
                "INSERT INTO assistant_threads(actor,scope,generation) VALUES(?,?,?)",
                (
                    user["id"],
                    scope,
                    "fixture-generation",
                ),
            )
            db.execute(
                """INSERT INTO assistant_turns(actor,scope,generation,request,fingerprint,asked,answered,question,answer,hours,voice_receipt)
                VALUES(?,?,?,?,?,'','','','请复核。',24,?)""",
                (user["id"], scope, "fixture-generation", "voice-turn", "", receipt),
            )
        settings = {
            "NH_TTS_PROVIDER": "compatible",
            "NH_TTS_MODEL": "tts-fixture",
            "NH_TTS_ENDPOINT": "https://audio.example.com/v1/audio/speech",
            "NH_TTS_VOICE": "zh_voice",
            "NH_TTS_API_KEY": "fake-tts-key",
        }
        audio = sample_wav()
        with (
            patch.dict("os.environ", settings),
            patch.object(
                audio_adapters.connection, "open_request", return_value=response(audio)
            ) as call,
            patch.object(read_aloud, "read_key") as legacy,
        ):
            payload = {
                "region": {},
                "scopeKey": scope,
                "generation": "fixture-generation",
                "requestId": "voice-turn",
                "sentence": 0,
            }
            with self.assertRaises(PermissionError):
                read_aloud.listen(
                    self.store,
                    self.token,
                    {**payload, "generation": "other-generation"},
                )
            call.assert_not_called()
            self.assertEqual(read_aloud.listen(self.store, self.token, payload), audio)
            legacy.assert_not_called()
        self.assertEqual(json.loads(call.call_args.args[0].data)["input"], "请复核。")
        with closing(self.store.connect()) as db:
            row = db.execute(
                "SELECT actor, charged, state FROM media_usage WHERE kind='tts'"
            ).fetchone()
            self.assertEqual(tuple(row), (user["id"], 7, "complete"))
