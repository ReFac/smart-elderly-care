from io import BytesIO
import json
import socket
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

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
        self.returns({"results": [row, row, {"url": "javascript:alert(1)"}]})
        self.assertEqual(
            web_search.search("secret", " 养老公开政策 "),
            [{"title": "官方 文件", "url": row["url"], "snippet": "公开资料"}],
        )
        request = self.open.call_args.args[0]
        self.assertEqual(
            (request.full_url, request.get_method()),
            ("https://api.deepseek.com/v1/tools/search", "POST"),
        )
        self.assertEqual(
            json.loads(request.data),
            {"query": "养老公开政策", "count": 5, "need_content": False},
        )

    def test_explicit_charge_semantics_for_empty_filtered_and_bounded_sources(self):
        self.returns({"results": []})
        self.assertEqual(web_search.search("secret", "公开问题"), [])
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
                self.returns({"results": [{"url": address}]})
                self.failure(
                    lambda: web_search.search("secret", "公开问题"),
                    "invalid_sources",
                    True,
                )
        self.returns(
            {
                "results": [
                    {
                        "url": f"https://example.org/{i}" + ("片" * 1000),
                        "title": "资" * 300,
                        "snippet": "疗" * 400,
                    }
                    for i in range(8)
                ]
            }
        )
        data = web_search.search("secret", "公开问题")
        size = len(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode())
        self.assertTrue(0 < len(data) <= 5)
        self.assertLessEqual(size, web_search.MAX_RESULTS_BYTES)

    def test_input_validation_and_safe_network_failures(self):
        for query in (None, {}, "   ", "资料\x00注入", "中" * 129, "\ud800"):
            self.failure(lambda: web_search.search("secret", query), "query", False)
        self.failure(lambda: web_search.probe(""), "credentials", False)
        self.open.assert_not_called()
        for error, code, billed in (
            (
                HTTPError("private-test", 401, "private-test", {}, BytesIO()),
                "credentials",
                False,
            ),
            (
                HTTPError("private-test", 402, "private-test", {}, BytesIO()),
                "balance",
                False,
            ),
            (
                HTTPError("private-test", 429, "private-test", {}, BytesIO()),
                "rate_limited",
                False,
            ),
            (
                HTTPError("private-test", 504, "private-test", {}, BytesIO()),
                "timeout",
                False,
            ),
            (URLError(socket.gaierror("private-test")), "network", False),
            (URLError(TimeoutError("private-test")), "timeout", None),
            (TimeoutError("private-test"), "timeout", None),
            (ConnectionResetError("private-test"), "network", None),
        ):
            with self.subTest(code=code, billed=billed):
                self.open.side_effect = error
                self.failure(
                    lambda: web_search.search("secret", "private-test"), code, billed
                )
        self.open.side_effect = None
        for raw in (b"private-test", b"x" * (web_search.MAX_RESPONSE_BYTES + 1), b"{}"):
            self.response.read.return_value = raw
            self.failure(
                lambda: web_search.search("secret", "private-test"),
                "invalid_response",
                None,
            )
            self.failure(lambda: web_search.probe("secret"), "invalid_response", False)
