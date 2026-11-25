from io import BytesIO
import json
import socket
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from platform_core.agents import deerflow_chat
from platform_core.provider import web_search


class SearchProviderTests(unittest.TestCase):
    def setUp(self):
        factory = patch.object(web_search, "build_opener")
        self.factory = factory.start()
        self.addCleanup(factory.stop)
        self.open = self.factory.return_value.open
        self.response = MagicMock()
        self.response.status = 200
        self.open.return_value.__enter__.return_value = self.response

    def native_search(self):
        capability = patch.object(deerflow_chat, "capability")
        call = capability.start()
        self.addCleanup(capability.stop)
        return call

    def returns(self, payload):
        self.response.read.return_value = json.dumps(
            payload, ensure_ascii=False
        ).encode()

    def failure(self, operation, code, billed):
        with self.assertRaises(web_search.WebSearchError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        self.assertIs(caught.exception.billed, billed)
        self.assertNotIn("private-test", str(caught.exception))

    def test_probe_only_checks_authenticated_configured_model(self):
        self.returns({"data": [{"id": "other"}, {"id": "deepseek-flash"}]})
        self.assertEqual(
            web_search.probe("secret"), {"connected": True, "model": "deepseek-flash"}
        )
        request = self.open.call_args.args[0]
        self.assertEqual(
            (request.full_url, request.get_method(), request.data),
            ("https://api.deepseek.com/models", "GET", None),
        )
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertIsNone(
            self.factory.call_args.args[0].redirect_request(
                request, None, 302, "redirect", {}, "http://localhost/"
            )
        )
        self.returns({"data": [{"id": "other"}]})
        self.failure(lambda: web_search.probe("secret"), "model_unavailable", False)

    def test_request_carries_only_public_keywords_and_response_is_minimal(self):
        row = {
            "title": "官方\n文件",
            "url": "https://www.gov.cn/news",
            "snippet": "公开资料",
            "summary": "private-test",
            "site_icon": "http://127.0.0.1",
            "content": "private-test",
        }
        call = self.native_search()
        call.return_value = {"results": [row, row, {"url": "javascript:alert(1)"}]}
        self.assertEqual(
            web_search.search(" 养老公开政策 "),
            [{"title": "官方 文件", "url": row["url"], "snippet": "公开资料"}],
        )
        call.assert_called_once_with("web_search", {"query": "养老公开政策"})
        self.open.assert_not_called()

    def test_explicit_charge_semantics_for_empty_filtered_and_bounded_sources(self):
        call = self.native_search()
        call.return_value = {"results": []}
        self.assertEqual(web_search.search("公开问题"), [])
        for address in (
            "file:///a",
            "javascript:alert(1)",
            "http://localhost/",
            "http://a.local/",
            "https://user:secret@example.com/",
            "http://127.0.0.1",
            "http://127.1",
            "http://0x7f000001",
            "http://[::1]",
            "http://224.0.0.1",
            "https://example.org\\@localhost/",
            "https://example.org/a\nLocation:x",
        ):
            with self.subTest(address=address):
                call.return_value = {"results": [{"url": address}]}
                self.failure(
                    lambda: web_search.search("公开问题"),
                    "invalid_sources",
                    True,
                )
        call.return_value = {
            "results": [
                {
                    "url": f"https://example.org/{i}" + ("片" * 1000),
                    "title": "资" * 300,
                    "snippet": "疗" * 400,
                }
                for i in range(8)
            ]
        }
        data = web_search.search("公开问题")
        size = len(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode())
        self.assertTrue(0 < len(data) <= 5)
        self.assertLessEqual(size, web_search.MAX_RESULTS_BYTES)

    def test_input_validation_and_safe_network_failures(self):
        for query in (None, {}, "   ", "资料\x00注入", "中" * 129, "\ud800"):
            self.failure(lambda: web_search.search(query), "query", False)
        self.failure(lambda: web_search.probe(""), "credentials", False)
        self.open.assert_not_called()
        call = self.native_search()
        call.side_effect = deerflow_chat.Unavailable("private-test")
        self.failure(lambda: web_search.search("private-test"), "network", False)
        call.side_effect = ValueError("private-test")
        self.failure(lambda: web_search.search("private-test"), "invalid_response", False)
        call.side_effect = None
        call.return_value = {"error": "private-test"}
        self.failure(lambda: web_search.search("private-test"), "network", False)
        for error, code in (
            (HTTPError("private-test", 401, "private-test", {}, BytesIO()), "credentials"),
            (HTTPError("private-test", 402, "private-test", {}, BytesIO()), "balance"),
            (HTTPError("private-test", 429, "private-test", {}, BytesIO()), "rate_limited"),
            (URLError(socket.gaierror("private-test")), "network"),
            (TimeoutError("private-test"), "timeout"),
        ):
            with self.subTest(code=code):
                self.open.side_effect = error
                self.failure(lambda: web_search.probe("secret"), code, False)
        self.open.side_effect = None
        for raw in (b"private-test", b"x" * (web_search.MAX_RESPONSE_BYTES + 1), b"[]"):
            self.response.read.return_value = raw
            self.failure(lambda: web_search.probe("secret"), "invalid_response", False)
