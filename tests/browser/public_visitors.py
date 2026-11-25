"""Exercise public browsing, contact requests and phone-free registration in Chromium.

Run python3 tests/browser/public_visitors.py with a Chromium browser, websocket-client
and the project's storage dependencies installed. All accounts and leads are synthetic.
"""

from contextlib import closing, ExitStack
import json
import os
from pathlib import Path
from shutil import which
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from urllib.parse import urlsplit
from urllib.request import urlopen

from websocket import create_connection

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from perf_workspace import checked, server, session_headers


def until(test):
    deadline = monotonic() + 15
    while monotonic() < deadline:
        if value := test():
            return value
        sleep(0.05)
    raise AssertionError(f"timed out waiting for {test}")


class Browser:
    def __init__(self, ws):
        self.ws = ws
        self.sequence = 0
        self.api = []
        self.errors = []
        for domain in ("Page", "Runtime", "Network"):
            self.call(domain + ".enable")

    def call(self, method, **params):
        self.sequence += 1
        self.ws.send(json.dumps({"id": self.sequence, "method": method, "params": params}))
        while True:
            event = json.loads(self.ws.recv())
            if event.get("method") == "Network.requestWillBeSent":
                req = event["params"]["request"]
                path = urlsplit(req["url"]).path
                if path.startswith("/api/"):
                    self.api.append((req["method"], path))
            elif event.get("method") == "Runtime.exceptionThrown":
                detail = event["params"]["exceptionDetails"]
                self.errors.append(detail.get("exception", {}).get("description", detail["text"]))
            if event.get("id") == self.sequence:
                if "error" in event:
                    raise RuntimeError(event["error"])
                return event["result"]

    def evaluate(self, expression):
        res = self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in res:
            raise RuntimeError(res["exceptionDetails"]["text"])
        return res["result"].get("value")

    def click(self, selector):
        self.evaluate(f"document.querySelector({json.dumps(selector)}).click()")

    def wait_for(self, expression):
        try:
            return until(lambda: self.evaluate(expression))
        except AssertionError as error:
            state = self.evaluate("[location.pathname, location.hash, document.querySelector('[role=alert]')?.textContent]")
            raise AssertionError(f"{expression} timed out at {state}, browser errors: {self.errors}") from error


def check_width(browser):
    assert browser.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth + 1"
    ), "The page overflows the viewport"


def smoke(browser, port):
    b = browser
    origin = f"http://127.0.0.1:{port}"
    b.call("Page.navigate", url=origin + "/visit")
    b.wait_for("document.querySelector('#visit-form select')?.disabled === false")
    check_width(b)
    assert not b.evaluate("Boolean(document.querySelector('dialog[open]'))")
    assert b.evaluate("Array.from(document.querySelectorAll('input[type=tel]')).every(i => !i.getClientRects().length)")
    assert b.evaluate("document.querySelector('.account-actions a[href=\"/visitor-register.html\"]').innerText.includes('免手机号')")
    b.click(".hero a[href='/roomtour']")
    b.wait_for("document.querySelectorAll('.tour-stop').length === 4")
    check_width(b)
    b.call("Page.bringToFront")
    b.click(".tour-stop:nth-child(2)")
    b.wait_for("new URLSearchParams(location.search).has('scene')")
    sleep(11)  # Keep a focused, visible tour open beyond the previous ten-second prompt.
    assert b.evaluate("document.hasFocus() && !document.hidden")
    assert not b.evaluate("Boolean(document.querySelector('dialog[open], input[type=tel]'))")
    assert set(b.api) == {("GET", "/api/public/reception")}, b.api
    assert not b.call("Network.getCookies", urls=[origin])["cookies"]

    b.click(".tour-title a[href='/visit#book-visit']")
    b.wait_for("document.querySelector('#visit-request')?.open && !document.querySelector('#visit-form select').disabled")
    b.evaluate("""{const f = document.querySelector('#visit-form'); f.elements.phone.value='13900001111';
        f.elements.name.value='参观测试'; f.requestSubmit();}""")
    assert ("POST", "/api/public/leads") not in b.api
    b.evaluate("""{const f=document.querySelector('#visit-form'); f.elements.consent.click(); f.requestSubmit();}""")
    b.wait_for("!document.querySelector('#visit-receipt').hidden")
    b.click("#visit-request [data-again]")
    assert b.evaluate("""!document.getElementById('visit-form').hidden &&
        !document.getElementById('visit-form').elements.consent.checked &&
        document.getElementById('visit-form').elements.phone.value === ''""")
    b.click("#visit-request [data-close]")
    b.click("#open-callback")
    b.evaluate("""{const f=document.querySelector('#callback-form'); f.elements.phone.value='13900002222';
        f.elements.consent.click(); f.requestSubmit();}""")
    b.wait_for("!document.querySelector('#callback-receipt').hidden")
    b.click("#callback [data-close]")
    assert b.api.count(("POST", "/api/public/leads")) == 2

    b.click(".site-nav a[href='/faq']")
    b.wait_for("document.querySelectorAll('.faq-entry').length > 0")
    check_width(b)
    b.click(".faq-filter:nth-child(2)")
    b.click(".faq-question")
    assert b.evaluate("!!document.querySelector('.faq-entry[open] .faq-answer')?.textContent")
    b.evaluate("""{const t=document.querySelector('[data-color-mode-control]');t.value='dark';
        t.dispatchEvent(new Event('change'));}""")
    assert b.evaluate("document.documentElement.dataset.colorMode === 'dark'")
    b.click(".site-brand")
    b.wait_for("!!document.querySelector('.hero')")
    b.click(".account-actions a[href='/visitor-register.html']")
    b.wait_for("document.querySelector('#visitor-register button')?.disabled === false")
    check_width(b)
    assert b.evaluate("Array.from(document.querySelectorAll('input'), e => e.name)") == ["username", "password"]
    b.evaluate("""{const f=document.querySelector('#visitor-register'); f.elements.username.value='visit-e2e';
        f.elements.password.value='short'; f.requestSubmit();}""")
    b.wait_for("document.querySelector('#register-error').innerText.includes('10')")
    assert ("POST", "/api/public/visitor/register") not in b.api
    b.evaluate("""{const f=document.querySelector('#visitor-register');
        f.elements.password.value='visitor-test-phrase'; f.requestSubmit();}""")
    b.wait_for("location.search === '?workspace=1' && Boolean(document.querySelector('#content'))")
    profile = b.evaluate("fetch('/api/state').then(r=>r.json()).then(r=>r.data.user)")
    assert profile["registeredCustomer"] and profile["username"] == "visit-e2e"
    assert b.api.count(("POST", "/api/public/visitor/register")) == 1
    assert not b.errors, b.errors
    _, body = checked(port, "/api/state", headers=session_headers(port, "owner"))
    contacts = json.loads(body)["data"]["leadContacts"]
    for source, suffix in (("visit", "1111"), ("callback", "2222")):
        assert sum(row["source"] == source and row["phone"].endswith(suffix) for row in contacts) == 1


def run_browser(check, seed=lambda store: None, *, server_factory=server):
    browser = os.environ.get("BROWSER_BIN") or which("chromium") or which("microsoft-edge") or which("google-chrome")
    if not browser:
        raise SystemExit("Set BROWSER_BIN to a Chromium executable")
    with TemporaryDirectory(prefix="visitor-browser-") as temp, ExitStack() as stack:
        root = Path(temp)
        _, port = stack.enter_context(server_factory(root, seed))
        profile = root / "browser"
        process = subprocess.Popen([browser, "--headless", "--disable-gpu", "--disable-extensions",
            "--disable-background-networking", "--no-first-run", "--remote-debugging-port=0",
            "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1",
            f"--user-data-dir={profile}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        stack.callback(process.wait, timeout=8)
        stack.callback(process.terminate)
        marker = profile / "DevToolsActivePort"
        until(marker.exists)
        debug_port = marker.read_text().splitlines()[0]
        with urlopen(f"http://127.0.0.1:{debug_port}/json/list", timeout=5) as response:
            url = next(page["webSocketDebuggerUrl"] for page in json.load(response) if page["type"] == "page")
        with closing(create_connection(url, timeout=15, suppress_origin=True)) as ws:
            check(Browser(ws), port)


def run_at_viewport(width, height, mobile):
    def check(session, port):
        session.call("Emulation.setDeviceMetricsOverride", width=width, height=height,
                     deviceScaleFactor=1, mobile=mobile)
        if mobile:
            session.call("Emulation.setTouchEmulationEnabled", enabled=True)
        smoke(session, port)
    run_browser(check)


def main():
    for width, height, mobile in ((1440, 900, False), (390, 844, True)):
        run_at_viewport(width, height, mobile)
    print("Public visitor browser checks passed at desktop and touch-phone sizes")


if __name__ == "__main__":
    main()
