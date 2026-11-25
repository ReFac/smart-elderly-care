"""Exercise hosted provider protocols and the actual metered planner with synthetic receipts."""

from contextlib import closing
from datetime import datetime
from io import BytesIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from platform_core import provider
from platform_core.provider import completions, connection, token_receipt


CALL = {
    "type": "function",
    "function": {
        "name": "read_care",
        "description": "Read permitted care facts",
        "parameters": {"type": "object"},
    },
}
MESSAGES = [
    {"role": "system", "content": "Summarize evidence"},
    {"role": "user", "content": "请简述"},
]
BASE = {
    "model": "fixture-text",
    "messages": MESSAGES,
    "max_tokens": 48,
    "thinking": {"type": "disabled"},
}
USAGE = {
    "input_tokens": 16,
    "cache_creation_input_tokens": 6,
    "cache_read_input_tokens": 8,
    "output_tokens": 10,
}
RECEIPT = token_receipt.TokenReceipt(40, 30, 8, 22, 10)


def stream_data(events):
    return BytesIO(
        b"\n\n".join(
            b"data: "
            + (event if isinstance(event, bytes) else json.dumps(event).encode())
            for event in events
        )
        + b"\n\n"
    )


class ChatProviderAdapterTests(unittest.TestCase):
    def test_gemini_reasoning_budget_is_reserved_in_the_shared_token_calculation(self):
        from platform_core.agents.chat import token_allowance

        body = {**BASE, "model": "gemini-3.8-flash"}
        with patch.dict("os.environ", {"NH_CHAT_PROVIDER": "deepseek"}):
            baseline = token_allowance(body)
        with (
            patch.dict("os.environ", {"NH_CHAT_PROVIDER": "google"}),
            patch.object(
                connection, "json_request", return_value={"choices": []}
            ) as remote,
        ):
            completions.send("fixture-key", body)
            sent = remote.call_args.args[1]
            self.assertEqual(sent["reasoning_effort"], "minimal")
            self.assertEqual(sent["max_tokens"], 48 + 2048)
            self.assertEqual(token_allowance(body), baseline + 2048)

    def test_openai_and_google_request_supported_chat_fields(self):
        body = {
            **BASE,
            "response_format": {"type": "json_object"},
            "tools": [CALL],
            "tool_choice": "auto",
        }
        for kind, host, limit in (
            ("openai", "https://api.openai.com/v1", "max_completion_tokens"),
            (
                "google",
                "https://generativelanguage.googleapis.com/v1beta/openai",
                "max_tokens",
            ),
        ):
            with (
                self.subTest(kind=kind),
                patch.dict("os.environ", {"NH_CHAT_PROVIDER": kind}),
                patch.object(
                    connection, "json_request", return_value={"choices": []}
                ) as remote,
            ):
                self.assertEqual(completions.send("fixture-key", body), {"choices": []})
                remote.assert_called_once()
                url, sent, headers = remote.call_args.args
                self.assertEqual(url, host + "/chat/completions")
                self.assertEqual(headers, {"Authorization": "Bearer fixture-key"})
                self.assertEqual(sent[limit], 48)
                self.assertEqual(sent["tools"], [CALL])
                self.assertEqual(sent["response_format"], {"type": "json_object"})
                self.assertNotIn("thinking", sent)
                if kind == "openai":
                    self.assertIs(sent["store"], False)

    def test_anthropic_native_tool_and_cache_conversion(self):
        response = {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "local-tool",
                    "name": "read_care",
                    "input": {"day": "today"},
                }
            ],
            "usage": USAGE,
        }
        with (
            patch.dict("os.environ", {"NH_CHAT_PROVIDER": "anthropic"}),
            patch.object(connection, "json_request", return_value=response) as remote,
        ):
            result = completions.send(
                "fixture-key", {**BASE, "tools": [CALL], "tool_choice": "auto"}
            )
        url, sent, headers = remote.call_args.args
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(
            headers, {"x-api-key": "fixture-key", "anthropic-version": "2023-06-01"}
        )
        self.assertEqual(sent["system"], MESSAGES[0]["content"])
        self.assertEqual(
            sent["messages"],
            [{"role": "user", "content": [{"type": "text", "text": "请简述"}]}],
        )
        self.assertEqual(sent["tools"][0]["input_schema"], {"type": "object"})
        self.assertEqual(sent["tool_choice"], {"type": "auto"})
        self.assertEqual(result["choices"][0]["finish_reason"], "tool_calls")
        returned = result["choices"][0]["message"]["tool_calls"][0]
        self.assertEqual(returned["function"]["name"], "read_care")
        self.assertEqual(
            json.loads(returned["function"]["arguments"]), {"day": "today"}
        )
        self.assertEqual(token_receipt.read(result, 200), RECEIPT)

    def test_text_streams_publish_text_before_metered_terminal_reply(self):
        compatible_usage = {
            "total_tokens": 40,
            "prompt_tokens": 30,
            "completion_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 8},
        }
        compatible = [
            {"choices": [{"delta": {"content": "请核对。"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            {"choices": [], "usage": compatible_usage},
            b"[DONE]",
        ]
        native = [
            {
                "type": "message_start",
                "message": {"usage": {**USAGE, "output_tokens": 1}},
            },
            {
                "type": "content_block_start",
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "delta": {"type": "thinking_delta", "thinking": "private"},
            },
            {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "请核对。"},
            },
            {
                "type": "message_delta",
                "usage": {"output_tokens": 10},
                "delta": {"stop_reason": "end_turn"},
            },
            {"type": "message_stop"},
        ]
        for kind, events in (
            ("anthropic", native),
            ("google", compatible[:-1]),
            ("openai", compatible),
        ):
            with (
                self.subTest(kind=kind),
                patch.dict("os.environ", {"NH_CHAT_PROVIDER": kind}),
                patch.object(
                    connection, "open_request", return_value=stream_data(events)
                ) as remote,
            ):
                parts = []
                result = completions.stream("key", BASE, parts.append)
                self.assertEqual(parts, ["请核对。"])
                self.assertEqual(result["choices"][0]["message"]["content"], "请核对。")
                self.assertEqual(token_receipt.read(result, 200), RECEIPT)
                payload = json.loads(remote.call_args.args[0].data)
                self.assertIs(payload["stream"], True)
                if kind != "anthropic":
                    self.assertEqual(payload["stream_options"], {"include_usage": True})

    def test_malformed_stream_shapes_raise_a_provider_error(self):
        for kind, frame in (
            ("openai", []),
            ("openai", {"choices": [{"delta": ["invalid"]}]}),
            ("google", {"choices": [None]}),
            ("anthropic", []),
            ("anthropic", {"type": "content_block_delta", "delta": ["invalid"]}),
        ):
            with (
                self.subTest(kind=kind, frame=frame),
                patch.dict("os.environ", {"NH_CHAT_PROVIDER": kind}),
                patch.object(connection, "open_request", return_value=stream_data([frame])),
                self.assertRaisesRegex(ValueError, "回复流格式"),
            ):
                completions.stream("key", BASE, self.fail)

    def test_selected_provider_does_not_read_deepseek_key_and_invalid_config_is_closed(
        self,
    ):
        with (
            patch.dict(
                "os.environ",
                {
                    "NH_CHAT_PROVIDER": "google",
                    "NH_CHAT_MODEL": "gemini-fixture",
                    "GEMINI_API_KEY": "",
                    "GOOGLE_API_KEY": "google-fixture",
                    "OPENAI_API_KEY": "openai-fixture",
                },
            ),
            patch.object(
                provider,
                "read_key",
                side_effect=AssertionError("DeepSeek key must stay separate"),
            ),
        ):
            self.assertEqual(provider.model_name(), "gemini-fixture")
            self.assertEqual(provider.read_model_key(), "google-fixture")
            self.assertTrue(provider.model_configured())
            with patch.dict("os.environ", {"NH_CHAT_MODEL": "invalid model"}):
                self.assertFalse(provider.model_configured())
                with self.assertRaises(ValueError):
                    provider.read_model_key()

    def test_planning_uses_operator_provider_and_records_the_selected_model(self):
        def connect():
            db = sqlite3.connect(db_file)
            db.row_factory = sqlite3.Row
            return db

        now = datetime(2026, 11, 25, 12, tzinfo=provider.ZONE)
        actor = {
            "id": "planner",
            "kind": "staff",
            "permissions": ["assistants", "inventory"],
        }
        response = {
            "stop_reason": "end_turn",
            "usage": USAGE,
            "content": [{"type": "text", "text": '{"ids":["inventory"]}'}],
        }
        config = {
            "NH_CHAT_PROVIDER": "anthropic",
            "NH_CHAT_MODEL": "claude-fixture",
            "ANTHROPIC_API_KEY": "fixture-key",
        }
        with TemporaryDirectory() as folder:
            db_file = Path(folder) / "plan.sqlite"
            with closing(connect()) as db, db:
                provider.init(db)
                provider.grant(db, "测试套餐", 10000, "2026-12-31", now)
            with (
                patch.dict("os.environ", config),
                patch.object(
                    connection, "json_request", return_value=response
                ) as remote,
            ):
                result = provider.plan(
                    connect,
                    lambda _: actor,
                    "核对护理用具库存",
                    "adapter-plan",
                    now=now,
                )
                self.assertEqual(result["specialistIds"], ["inventory"])
                self.assertEqual(result["model"], "claude-fixture")
                self.assertIn("JSON", remote.call_args.args[1]["system"])
                self.assertEqual(remote.call_args.args[2]["x-api-key"], "fixture-key")
                with closing(connect()) as db:
                    state = provider.status(db, actor, now)
                    self.assertEqual(state["modelProvider"], "anthropic")
                    self.assertEqual(
                        provider.usage(db, provider.latest(db)["id"]), (40, 0)
                    )
                    self.assertEqual(
                        tuple(
                            db.execute(
                                "SELECT model,charged,cachedInputTokens,uncachedInputTokens FROM api_usage"
                            ).fetchone()
                        ),
                        ("claude-fixture", 40, 8, 22),
                    )
