"""Measure real HTTP reads with an isolated encrypted account-directory fixture (Linux).

Run python3 tests/perf_workspace.py --clients 6 --samples 100 > result.json.
Each sample includes a new loopback connection and the entire response body.
"""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from html.parser import HTMLParser
from http.client import HTTPConnection
from itertools import product
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from provider_fixture import credential_env
from test_account_directory import PASSWORD, REGISTERED, STAFF, STAYS, STAY_PER_STATUS, populate_directory
from platform_core.store import Store

USERS = {"owner": "owner", "nurse": "clinical-employee", "relative": "relative-0000"}
ROUTES = ("/api/state", "/api/version", "/api/assistant/navigation-version")


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        path = None
        if tag == "link" and attrs.get("rel") == "stylesheet":
            path = attrs.get("href")
        if tag == "script":
            path = attrs.get("src")
        if path and path.startswith("/") and not path.startswith("//"):
            self.paths.append(path)


def request(port, path, *, headers=None, payload=None):
    with closing(HTTPConnection("127.0.0.1", port, timeout=60)) as client:
        if payload is None:
            client.request("GET", path, headers=headers or {})
        else:
            headers = {**(headers or {}), "Content-Type": "application/json"}
            client.request("POST", path, json.dumps(payload), headers)
        response = client.getresponse()
        return response.status, response.headers, response.read()


@contextmanager
def server(scratch, seed=populate_directory):
    env = {k: os.environ[k] for k in ("PATH", "PYTHONPATH", "LD_LIBRARY_PATH", "LANG", "TZ") if k in os.environ}
    env.update(credential_env(scratch))
    env["NH_BACKUP_LOCATIONS_FILE"] = str(scratch / "unused-locations.json")
    db = scratch / "fixture.sqlite3"
    with patch.dict(os.environ, env, clear=True):
        seed(Store(db, initial_owner_password=PASSWORD))
    with (scratch / "server.log").open("w+b") as log:
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "server.py"), "--db", str(db), "--port", "0"],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env,
        )
        try:
            deadline = monotonic() + 60
            while monotonic() < deadline:
                content = (scratch / "server.log").read_bytes()
                if process.poll() is not None:
                    raise RuntimeError(content[-1500:].decode(errors="replace"))
                match = re.search(rb"http://127\.0\.0\.1:(\d+)", content)
                if match:
                    yield process.pid, int(match[1])
                    return
                sleep(.05)
            raise RuntimeError("test server did not become ready")
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def checked(port, path, **kwargs):
    status, headers, body = request(port, path, **kwargs)
    if status != 200:
        raise RuntimeError(f"{path} returned HTTP {status}")
    return headers, body


def session_headers(port, username):
    headers, _ = checked(port, "/api/auth/login", payload={"username": username, "password": PASSWORD})
    return {"Cookie": headers["Set-Cookie"].split(";", 1)[0]}


def percentiles(values):
    times = sorted(values)
    return {
        "p50_ms": round(times[math.ceil(len(times) * .50) - 1], 2),
        "p95_ms": round(times[math.ceil(len(times) * .95) - 1], 2),
    }


def assets(port):
    _, page = checked(port, "/?workspace=1")
    parser = Assets()
    parser.feed(page.decode())
    cold_bytes = repeat_bytes = 0
    codes = Counter()
    checks = {}
    for path in dict.fromkeys(parser.paths):
        headers, body = checked(port, path)
        cold_bytes += len(body)
        checks[path] = headers.get("ETag")
    for path, tag in checks.items():
        status, _, body = request(port, path, headers={"If-None-Match": tag} if tag else {})
        if status not in (200, 304):
            raise RuntimeError(f"{path} returned HTTP {status}")
        repeat_bytes += len(body)
        codes[status] += 1
    if not checks:
        raise AssertionError("no first-level JS or CSS found")
    return {"resource_count": len(checks), "initial_body_bytes": cold_bytes,
            "repeat_body_bytes": repeat_bytes, "repeat_statuses": codes}


def cpu_seconds(pid):
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")


def peak_rss(pid):
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1]) / 1024
    raise RuntimeError("missing service process high-water RSS")


def mixed_reads(pid, port, clients, samples):
    cookies = {}
    for role, username in USERS.items():
        cookies[role] = session_headers(port, username)
        for path in ROUTES:
            _, body = checked(port, path, headers=cookies[role])
            if path == "/api/state":
                state = json.loads(body)["data"]
                if state["user"]["username"] != username or ("accounts" in state) != (role == "owner"):
                    raise AssertionError(f"unexpected account projection for {role}")

    def read(pair):
        role, route = pair
        begin = monotonic()
        status, _, body = request(port, route, headers=cookies[role])
        return role, route, status, len(body), (monotonic() - begin) * 1000

    jobs = list(product(USERS, ROUTES)) * samples
    cpu_start = cpu_seconds(pid)
    start = monotonic()
    with ThreadPoolExecutor(clients) as pool:
        results = list(pool.map(read, jobs))
    elapsed = monotonic() - start
    cpu = cpu_seconds(pid) - cpu_start
    groups = defaultdict(list)
    for role, route, status, size, ms in results:
        groups[role, route].append((status, size, ms))
    routes = {}
    for (role, route), values in groups.items():
        routes[role + " " + route] = {
            "http_statuses": Counter(status for status, _, _ in values),
            "response_body_bytes": sum(size for _, size, _ in values),
            **percentiles(ms for _, _, ms in values),
        }
    return {
        "clients": clients, "samples_per_role_and_route": samples, "total_requests": len(results),
        "wall_s": round(elapsed, 3), "requests_per_s": round(len(results) / elapsed, 2),
        "service_cpu_s": round(cpu, 2), "service_lifetime_peak_rss_mib": round(peak_rss(pid), 2),
        "routes": routes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clients", type=int, default=6)
    parser.add_argument("--samples", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.clients <= 256 or not 1 <= args.samples <= 1000:
        parser.error("clients must be 1–256 and samples 1–1000")
    with TemporaryDirectory(prefix="eldercare-http-benchmark-") as root, server(Path(root)) as (pid, port):
        static = assets(port)
        reads = mixed_reads(pid, port, args.clients, args.samples)
    print(json.dumps({
        "accounts": {"owner": 1, "staff": STAFF, "related": len(STAYS) * STAY_PER_STATUS, "registered": REGISTERED},
        "entry_assets": static, "mixed_reads": reads,
    }, indent=2))
    return int(any(set(row["http_statuses"]) != {200} for row in reads["routes"].values()))


if __name__ == "__main__":
    sys.exit(main())
