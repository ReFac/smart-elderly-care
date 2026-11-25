"""Check workspace navigation and live reauthorization using synthetic accounts and resident records."""
from contextlib import contextmanager
from functools import partial
import json
from threading import Thread
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from public_visitors import run_browser
from perf_workspace import PASSWORD, checked, session_headers
from provider_fixture import credential_env
from platform_core import visitor_access
from platform_core.store import Store
from platform_core.http_capacity import CapacityServer
from server import Handler

NAMES = ("核验当天照护甲", "核验当天照护乙")
ACCOUNTS = {
    "owner": None,
    "qa-nurse": {"kind": "staff", "role": "护士"},
    "qa-reception": {"kind": "staff", "role": "自定义", "permissions": ["intake", "residents"]},
    "qa-finance": {"kind": "staff", "role": "财务"},
    "qa-family": {"kind": "family", "residentId": "r001", "familyServices": True,
                  "portalScopes": ["careSchedule"]},
    "qa-visitor": None,
}


def seed(store):
    owner, _ = store.login("owner", PASSWORD)

    def save(action, payload):
        store.execute(action, payload, store.version(owner)["revision"], owner)

    for username, config in ACCOUNTS.items():
        if config:
            save("access.create", {**config, "username": username,
                                   "displayName": username, "password": PASSWORD})
    visitor_access.register(store, {"username": "qa-visitor", "password": PASSWORD}, "test-peer")
    for rid, title in zip(("r001", "r002"), NAMES):
        save("care.addTask", {"residentId": rid, "title": title, "assignee": "测试护士"})
        task = store.snapshot(owner)["data"]["tasks"][-1]["id"]
        save("care.completeTask", {"taskId": task, "note": "隔离测试记录"})


def owner_command(port, action, payload):
    owner = session_headers(port, "owner")
    revision = json.loads(checked(port, "/api/version", headers=owner)[1])["revision"]
    checked(port, "/api/commands", headers=owner,
            payload={"revision": revision, "action": action, "payload": payload})


def exercise(b, port, username):
    origin = f"http://127.0.0.1:{port}"
    is_family = username in ("qa-family", "qa-visitor")
    narrow = is_family or username == "qa-nurse"
    b.call("Emulation.setDeviceMetricsOverride", width=390 if narrow else 1440,
           height=844 if narrow else 900, deviceScaleFactor=1, mobile=narrow)
    if narrow:
        b.call("Emulation.setTouchEmulationEnabled", enabled=True)
        b.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
    b.call("Page.navigate", url=origin + "/?workspace=1")
    b.wait_for("!!document.querySelector('.access-login-form')")
    assert b.evaluate("document.querySelector('[data-color-mode-control]').value === 'light'")
    assert b.evaluate("document.documentElement.dataset.colorMode === 'light'")
    b.evaluate("""{const f=document.querySelector('.access-login-form');
        f.elements.username.value=""" + json.dumps(username) + ";f.elements.password.value=" +
               json.dumps(PASSWORD) + "; f.requestSubmit()}")
    b.wait_for("!!document.querySelector('.sidebar a.nav-item') && !!document.querySelector('#content')")
    if narrow:
        assert b.evaluate("document.documentElement.dataset.colorMode === 'light'")
        b.click(".account-trigger")
        b.evaluate("Array.from(document.querySelectorAll('dialog button')).find(b=>b.textContent==='外观与显示').click()")
        b.wait_for("!!document.querySelector('.personal-display')")
        b.evaluate("""{const form=document.querySelector('.personal-display');
            form.elements.mode.value='system';form.requestSubmit()}""")
        b.wait_for("document.documentElement.dataset.colorMode === 'dark'")
        b.click(".menu-trigger")
        assert b.evaluate("document.querySelector('.sidebar').getBoundingClientRect().left >= -1")
    data = b.evaluate("fetch('/api/state').then(r=>r.json()).then(s=>s.data)")
    routes = data["user"]["routes"]
    items = b.evaluate("Array.from(document.querySelectorAll('.sidebar a.nav-item'), a=>[a.hash,a.title])")
    assert items and all(target[1:].split("?")[0] in routes for target, _ in items)
    if is_family:
        expected = {"family","tour","account","faq"} if username == "qa-family" else {"tour","faq","account"}
        assert {target[1:] for target, _ in items} == expected

    for target, title in items:
        b.click('.sidebar a[href="' + target + '"]')
        route = target[1:].split("?")[0]
        expected = "location.hash === " + json.dumps(target) + " && document.querySelector('#content')?.dataset.route === " + json.dumps(route)
        b.wait_for(expected + " && !!document.querySelector('#content > *')")
        selected = b.evaluate("document.querySelector('#content > * .fx-tabs > [aria-selected=true]')?.dataset.key")
        tab = parse_qs(urlsplit(target[1:]).query).get("tab", [None])[0]
        if selected and tab:
            assert selected == tab, (username, title, target, selected)
        assert not b.errors, (username, title, b.errors)

    if username in ("qa-family", "qa-visitor"):
        # Work links copied from a colleague are interpreted using the current portal account.
        b.call("Page.navigate", url=origin + "/?workspace=1#dossier?work=resident-r002")
        b.wait_for("!!document.querySelector('#content') && !location.hash.includes('work=')")
        content = b.evaluate("document.querySelector('#content').innerText")
        assert NAMES[1] not in content
        assert not b.evaluate("!!document.querySelector('.resident-record-workspace')")
        if username == "qa-visitor":
            assert not data["residents"]
        else:
            assert [r["id"] for r in data["residents"]] == ["r001"]
            b.click('.sidebar a[href="#family"]')
            b.click('.family-views button[data-group="tasks"]')
            b.click('.family-subviews button:last-child')
            b.wait_for("document.querySelector('#content').textContent.includes(" + json.dumps(NAMES[0]) + ")")
            assert NAMES[1] not in b.evaluate("document.querySelector('#content').textContent")
            b.click('.sidebar a[href="#faq"]')
            owner_command(port, "access.update", {"id": data["user"]["id"], "familyServices": False, "portalScopes": []})
            b.wait_for("!Array.from(document.querySelectorAll('.desk-tab-name')).some(b=>b.title==='常见问题') || " +
                       "document.querySelectorAll('.desk-tab-name').length <= 2")
            b.click('.sidebar a[href="#family"]')
            b.wait_for("document.querySelector('#content').dataset.route==='family' && !document.querySelector('#content').textContent.includes(" + json.dumps(NAMES[0]) + ")")
            assert not b.evaluate("document.querySelector('.family-views button[data-group=tasks], .family-views button[data-group=completed]') !== null")
    elif username == "qa-nurse":
        resident = next(r for r in data["residents"] if r["id"] == "r001")
        work_url = origin + "/?workspace=1#dossier?work=resident-r001"
        b.call("Page.navigate", url=work_url)
        b.wait_for("document.querySelector('.resident-record-workspace')?.textContent.includes(" + json.dumps(resident["name"]) + ")")
        b.click('.sidebar a[href="#faq"]')
        owner_command(port, "access.update", {"id": data["user"]["id"], "permissions": ["shifts"]})
        b.wait_for("!document.querySelector('.sidebar a[href=\"#dossier\"]')")
        assert not b.evaluate("document.querySelector('.desk-tabs').textContent.includes(" + json.dumps(resident["name"]) + ")")
        b.call("Page.navigate", url=work_url)
        b.wait_for("!!document.querySelector('#content') && !location.hash.includes('work=')")
        assert not b.evaluate("!!document.querySelector('.resident-record-workspace')")
    assert not b.errors, (username,b.errors)
    print(f"{username}: {len(items)} destinations passed", flush=True)


@contextmanager
def room_server(folder, seed_data):
    # Exercise the production room-policy port on one real HTTP server with two rooms in the same institution.
    def room_policy(db, actor):
        if actor["username"] == "qa-nurse":
            room = db.execute("SELECT roomId FROM facility_beds WHERE bedId='b001'").fetchone()[0]
            return {"roomIds": [room]}
        return {}

    class QuietHandler(Handler):
        def log_message(self, *_):
            pass

    with patch.dict("os.environ", credential_env(folder)):
        store = Store(folder / "fixture.sqlite3", initial_owner_password=PASSWORD, facility_policy=room_policy)
        seed_data(store)
        handler = partial(QuietHandler, store=store)
        with CapacityServer(("127.0.0.1", 0), handler, workers=12, heavy_workers=4) as http:
            worker = Thread(target=http.serve_forever, daemon=True)
            worker.start()
            try:
                yield None, http.server_port
            finally:
                http.shutdown()
                worker.join(4)


def check_moved_resident(b, port):
    owner = session_headers(port,"owner")
    data = json.loads(checked(port, "/api/state", headers=owner)[1])["data"]
    patient = next(r for r in data["residents"] if r["bedId"] == "b001")
    rooms = data["bedDirectory"]
    other_bed = next(r["id"] for r in data["beds"] if r["status"] == "空闲"
                     and rooms[r["id"]]["roomId"] != rooms["b001"]["roomId"])
    marker = "同分院转床前的合成观察记录"
    owner_command(port, "care.vital", {"residentId":patient["id"], "metric":marker,
                  "value":12, "unit":"测试单位", "abnormal":False})
    b.call("Page.navigate", url=f"http://127.0.0.1:{port}/?workspace=1#care?tab=vitals")
    b.wait_for("!!document.querySelector('.access-login-form')")
    b.evaluate("""{const f=document.querySelector('.access-login-form');f.elements.username.value='qa-nurse';
        f.elements.password.value=""" + json.dumps(PASSWORD) + "; f.requestSubmit()}")
    b.wait_for("Array.from(document.querySelectorAll('#content tbody tr')).some(t=>t.textContent.includes(" +
               json.dumps(marker) + "))")
    b.evaluate("Array.from(document.querySelectorAll('#content tbody tr')).find(t=>t.textContent.includes(" +
               json.dumps(marker) + ")).querySelector('button').click()")
    b.wait_for("document.querySelector('dialog[open]')?.textContent.includes(" + json.dumps(marker) + ")")
    assert not b.evaluate("!!document.querySelector('[data-rounds-resident-id],[data-linked-resident]')")
    owner_command(port, "care.transfer", {"residentId":patient["id"], "fromBedId":"b001","bedId":other_bed})
    b.wait_for("!document.querySelector('dialog[open]') && !document.querySelector('#content').textContent.includes(" + json.dumps(marker) + ")")
    visible = b.evaluate("fetch('/api/state').then(r=>r.json()).then(s=>s.data.residents.map(r=>r.id))")
    assert patient["id"] not in visible
    b.click('.sidebar a[href="#faq"]')
    b.click('.sidebar a[href="#care?tab=vitals"]')
    assert marker not in b.evaluate("document.querySelector('#content').textContent")
    assert not b.errors,b.errors
    print("Same-institution room transfer cleared an untagged clinical dialog, source ledger, and saved view")


if __name__ == "__main__":
    for user in ACCOUNTS:
        run_browser(lambda b, p: exercise(b, p, user), seed)
    run_browser(check_moved_resident, seed, server_factory=room_server)
