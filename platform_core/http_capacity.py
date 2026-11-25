"""Bound request threads and concurrent memory-heavy or long-lived work."""

from http.server import ThreadingHTTPServer
import os
from pathlib import Path
from threading import BoundedSemaphore, Lock


LARGE_BODY = 512 * 1024
SLOW_WRITES = frozenset({
    "/api/assistant/chat", "/api/assistant/chat/stream", "/api/assistant/voice",
    "/api/agent/voice/transcriptions", "/api/staff/resume/preview",
    "/api/public/visitor/register", "/api/auth/login", "/api/auth/verify", "/api/auth/reset-link/redeem", "/api/auth/reset-link/send",
    "/api/auth/passkeys/enroll-options", "/api/auth/passkeys/revoke",
    "/api/updates/download", "/api/updates/install", "/api/backups/imports/preview",
})
OVERLOAD_BODY = '{"error":"机构服务正忙，请稍后重试"}'.encode()
OVERLOAD_REPLY = (
    "HTTP/1.0 503 Service Unavailable\r\nContent-Type: application/json; charset=utf-8\r\n"
    f"Content-Length: {len(OVERLOAD_BODY)}\r\nRetry-After: 2\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n"
).encode() + OVERLOAD_BODY


def _setting(name, default):
    value = os.environ.get(name, str(default)).strip()
    if len(value) > 3 or not value.isascii() or not value.isdigit():
        raise ValueError(name + " 须填写整数")
    return int(value)


def _cpu_capacity():
    available = getattr(os, "process_cpu_count", os.cpu_count)() or 1
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max" and int(quota) > 0 and int(period) > 0:
            available = min(available, (int(quota) + int(period) - 1) // int(period))
    except (OSError, ValueError):
        pass
    return available


def configured_limits():
    cpus = _cpu_capacity()
    workers = _setting("NH_HTTP_WORKERS", min(32, max(8, 4 * cpus)))
    heavy = _setting("NH_HTTP_HEAVY_WORKERS", min(8, max(2, workers // 4)))
    if not 4 <= workers <= 256 or not 1 <= heavy <= workers - 2:
        raise ValueError("NH_HTTP_WORKERS 须为 4–256，NH_HTTP_HEAVY_WORKERS 至少为 1，并留出至少 2 个普通请求名额")
    return workers, heavy


def heavy_request(method, path, content_length):
    if method == "GET":
        return path == "/api/backups/download" or path.startswith((
            "/api/medical-visits/originals/", "/api/finance/subsidies/materials/", "/api/finance/expense-import/files/", "/tour-media/",
        )) or (
            path.startswith("/api/documents/") and ("/pages/" in path or path.endswith("/image"))
        ) or (path.startswith("/api/staff/") and path.endswith("/original"))
    try:
        large = int(content_length or 0) >= LARGE_BODY
    except ValueError:
        large = False
    return large or path in SLOW_WRITES or path.startswith("/api/media/asr/") or path.endswith("/medical-visits/preview")


class CapacityServer(ThreadingHTTPServer):
    def __init__(self, address, handler, *, workers, heavy_workers):
        self._usage_lock = Lock()
        self._usage = dict(active=0, peak=0, limit=workers, rejected=0)
        self.connections = BoundedSemaphore(workers)
        self.heavy_slots = BoundedSemaphore(heavy_workers)
        self.request_queue_size = workers * 2
        super().__init__(address, handler)

    def usage(self):
        with self._usage_lock:
            return self._usage.copy()

    def release_connection(self):
        with self._usage_lock:
            self._usage["active"] -= 1
        self.connections.release()

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            with self._usage_lock:
                self._usage["rejected"] += 1
            try:
                request.settimeout(0.2)
                request.sendall(OVERLOAD_REPLY)
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            with self._usage_lock:
                self._usage["active"] += 1
                self._usage["peak"] = max(self._usage["peak"], self._usage["active"])
            request.settimeout(15)
            super().process_request(request, client_address)
        except BaseException:
            self.release_connection()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.release_connection()
