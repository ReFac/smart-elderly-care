"""An allowlisted MCP service has a narrower interface than its underlying server."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest import TestCase, skipUnless
from unittest.mock import patch

from platform_core.agents import mcp_plugins as plugins


OWNER = {"kind": "owner"}
HAS_SDK = (plugins.ROOT / ".local/harness-runtime/mcp").exists()
if not HAS_SDK:
    from importlib.util import find_spec
    HAS_SDK = find_spec("mcp") is not None and find_spec("mcp_server_time") is not None


@contextmanager
def configured(change):
    data = json.loads(plugins.DEFAULT_CONFIG.read_text())
    change(data["mcpServers"]["time"])
    with TemporaryDirectory() as temp:
        file = Path(temp) / "mcp.json"
        file.write_text(json.dumps(data))
        file.chmod(0o600)
        with patch.dict(os.environ, NH_MCP_CONFIG=str(file)):
            yield file


class PermissionTests(TestCase):
    def test_catalog_and_selection_disclose_only_authorized_labels(self):
        with configured(lambda cfg: cfg["tools"]["convert_time"].update(grant="clinical")):
            worker = {"kind": "staff", "permissions": ["assistants"]}
            self.assertFalse(plugins.tools_for(worker, "换算"))
            self.assertNotIn("mcp_time_convert_time", [tool.name for tool in plugins.tools_for(worker)])
            self.assertIn("mcp_time_convert_time", [tool.name for tool in plugins.tools_for(OWNER)])
            self.assertEqual(len(plugins.tools_for(OWNER, "换算")), 1)
            self.assertFalse(plugins.catalog({"kind": "family", "permissions": ["assistants"]}))
            self.assertFalse(plugins.tools_for(OWNER, "帮我填写居民个人资料"))
            self.assertNotIn("command", json.dumps(plugins.catalog(OWNER)))
            self.assertTrue(all(set(entry) == {"name", "server", "title", "description"}
                                for entry in plugins.catalog(OWNER)))

    def test_untrusted_http_and_unsafe_manifest_are_inert(self):
        with configured(lambda cfg: cfg.update(transport="streamable-http", url="https://other.example/mcp")):
            self.assertFalse(plugins.catalog(OWNER))
        with configured(lambda cfg: cfg.update(transport="streamable-http", url="https://other.example/mcp", trust="institution")) as file:
            self.assertTrue(plugins.catalog(OWNER))
            if os.name == "posix":
                file.chmod(0o666)
                self.assertFalse(plugins.catalog(OWNER))

    def test_unknown_fields_or_raw_text_never_leave_the_process(self):
        first, = plugins.tools_for(OWNER, "机构时间")
        convert, = plugins.tools_for(OWNER, "换算")
        offset, = plugins.tools_for(OWNER, "起始时刻")
        with patch.object(plugins, "_invoke") as invoke:
            for tool, arguments in ((first, {"timezone":"姓名和电话号码"}), (first, {"url":"http://elsewhere"}),
                                    (convert, {"time":"00:99","source_timezone":"UTC","target_timezone":"UTC"}),
                                    (convert, {}), (offset, {"minutes_ago":True}), (offset, {"days_ago":366})):
                with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                    tool.execute(arguments)
            invoke.assert_not_called()
        with configured(lambda cfg: cfg["tools"]["convert_time"]["parameters"].update(notes={"type":"string"})):
            self.assertFalse(plugins.catalog(OWNER))

    def test_busy_tool_returns_without_starting_a_subprocess(self):
        tool, = plugins.tools_for(OWNER, "机构时间")
        with patch.object(plugins, "_invoke") as invoke, plugins.SLOTS, plugins.SLOTS:
            with self.assertRaisesRegex(ValueError, "稍后"):
                tool.read()
            invoke.assert_not_called()


@skipUnless(HAS_SDK, "requires requirements-harness.txt")
class SDKTests(TestCase):
    def test_real_official_stdio_get_and_convert_time(self):
        now, = plugins.tools_for(OWNER, "机构时间")
        instant = now.read()
        self.assertEqual(instant["timezone"], "Asia/Shanghai")
        self.assertIn("+08:00", instant["datetime"])
        convert, = plugins.tools_for(OWNER, "换算")
        converted = convert.execute({"source_timezone":"Asia/Shanghai","target_timezone":"UTC","time":"12:00"})
        self.assertIn("04:00:", converted["target"]["datetime"])

    def test_approved_http_uses_fixed_endpoint_without_following_redirects(self):
        seen = []
        class Rejected(BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append(self.path)
                self.send_response(307)
                self.send_header("Location", "/other")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(("127.0.0.1",0), Rejected) as server:
            t = Thread(target=server.serve_forever, daemon=True)
            t.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/mcp"
                with configured(lambda cfg: cfg.update(transport="streamable-http", url=url)):
                    tool, = plugins.tools_for(OWNER, "机构时间")
                    with self.assertRaises(ValueError):
                        tool.read()
            finally:
                server.shutdown()
                t.join()
        self.assertTrue(seen)
        self.assertEqual(set(seen), {"/mcp"})
