from threading import BoundedSemaphore
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from platform_core import http_capacity
from server import Handler


class HttpCapacityTests(unittest.TestCase):
    def setUp(self):
        self.handler = Handler.__new__(Handler)
        self.slots = BoundedSemaphore(1)
        self.handler.server = SimpleNamespace(heavy_slots=self.slots)
        self.handler.public_origin = self.handler.update_gate = None
        self.handler.headers = {"Host": "localhost", "Content-Length": "2097152"}
        self.handler.path = "/api/staff/resume/preview"
        self.handler.read_resource = Mock()
        self.handler.write_resource = Mock()
        self.handler.send_json = Mock()

    def test_heavy_overload_rejects_before_body_and_leaves_light_reads_available(self):
        with self.slots:
            self.handler.dispatch("POST")
            self.handler.write_resource.assert_not_called()
            self.handler.send_json.assert_called_once_with(503, {"error": "机构正在处理较多请求，请稍后重试"}, retry_after=2)
            self.handler.path = "/api/health"
            self.handler.dispatch("GET")
            self.handler.read_resource.assert_called_once_with("/api/health")

    def test_heavy_slot_is_returned_on_failure(self):
        self.handler.write_resource.side_effect = [ValueError("无效文档"), None]
        self.handler.dispatch("POST")
        self.handler.send_json.assert_called_once_with(400, {"error": "无效文档"})
        self.handler.dispatch("POST")
        self.assertEqual(self.handler.write_resource.call_count, 2)

    def test_connection_overload_does_not_start_worker_and_closes_socket(self):
        with patch.object(http_capacity.ThreadingHTTPServer, "__init__", return_value=None):
            server = http_capacity.CapacityServer(("localhost", 0), Mock(), workers=1, heavy_workers=1)
        server.shutdown_request = Mock()
        request = Mock()
        with server.connections:
            server.process_request(request, ("127.0.0.1", 1234))
        self.assertIn(b"503 Service Unavailable", request.sendall.call_args.args[0])
        server.shutdown_request.assert_called_once_with(request)
        self.assertEqual(server.usage()["rejected"], 1)

    def test_heavy_limit_must_leave_connection_capacity(self):
        with patch.dict("os.environ", {"NH_HTTP_WORKERS": "8", "NH_HTTP_HEAVY_WORKERS": "7"}):
            with self.assertRaisesRegex(ValueError, "普通请求名额"):
                http_capacity.configured_limits()
        with patch.dict("os.environ", {"NH_HTTP_WORKERS": "8", "NH_HTTP_HEAVY_WORKERS": "2"}):
            self.assertEqual(http_capacity.configured_limits(), (8, 2))
