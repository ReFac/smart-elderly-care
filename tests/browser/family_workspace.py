"""Exercise the signed-in family and resident service pages using separate synthetic accounts."""
import json
from contextlib import closing
from pathlib import Path

from public_visitors import run_browser
from perf_workspace import PASSWORD


def seed(store):
    from platform_core import facility, rounds_family, storage_assets
    from platform_core.operations import admission_finance

    owner = store.login("owner", PASSWORD)[0]

    def command(token, action, **payload):
        return store.execute(action, payload, store.version(token)["revision"], token)

    for name, rid, scopes, self_account in (
        ("family-browser", "r003", ["careSchedule", "medication", "billingNotices"], False),
        ("resident-browser", "r001", ["personalHealth", "medicationReport", "careSchedule"], True),
        ("limited-family", "r002", [], False),
    ):
        command(owner, "access.create", username=name, displayName=name, password=PASSWORD,
                kind="family", residentId=rid, portalScopes=scopes, portalSelf=self_account,
                familyServices=name == "family-browser")
    token, relative = store.login("family-browser", PASSWORD)
    command(owner, "family.consent", accountId=relative["id"], residentId="r003", enabled=True,
            method="长辈当面确认", evidence="测试账号已当面核对")
    command(token, "family.subscribe", residentId="r003", enabled=True)
    assets = Path(__file__).resolve().parents[2] / "web" / "assets" / "visit"
    for name, title in (("garden", "庭院参观"), ("reception", "来访接待区")):
        with closing(store.connect()) as db, db:
            storage_assets.import_asset(db, "tour", name + ".webp", assets / (name + ".webp"))
        command(owner, "facility.setScene", title=title, buildingId=facility.MAIN, kind="photo",
                mediaUrl="/tour-media/" + name + ".webp")
    now = store.now()
    with closing(store.connect()) as db, db:
        state = json.loads(db.execute("SELECT data FROM workspace").fetchone()[0])
        for resident_id in ("r002", "r003"):
            person = next(p for p in state["residents"] if p["id"] == resident_id)
            person["admissionTerms"] = admission_finance.terms({"depositMonths": 0})
            state.setdefault("billingNotices", []).append({
                "id": "test-notice-" + resident_id, "residentId": resident_id, "kind": "contractExpired",
                "title": "续住提醒", "date": now.date().isoformat(), "billingDate": now.date().isoformat(),
                "message": "请核对续住登记 · " + resident_id, "billId": "private-finance-field",
            })
        db.execute("UPDATE workspace SET data=?", (json.dumps(state),))
        assert rounds_family.deliver(db, state, {
            "id": "browser-report", "day": now.date().isoformat(), "residentId": "r003",
            "today": {"planned": 4, "completed": 3, "pending": 1, "overdue": 0},
        }, now) == 1


def verify(b, port):
    def login(account):
        b.call("Page.navigate", url=f"http://127.0.0.1:{port}/?workspace=1#family")
        b.wait_for("!!document.querySelector('.access-login-form')")
        b.evaluate("{const f=document.querySelector('.access-login-form'); f.elements.username.value="
                   + json.dumps(account) + ";f.elements.password.value=" + json.dumps(PASSWORD) + ";f.requestSubmit()}")
        b.wait_for("!!document.querySelector('.family-service-desk')")

    def logout():
        b.evaluate("fetch('/api/auth/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(r=>r.status)")
        b.call("Page.navigate", url=f"http://127.0.0.1:{port}/?workspace=1")
        b.wait_for("!!document.querySelector('.access-login-form')")

    def click(label, scope=".family-service-desk button"):
        expr = (f"Array.from(document.querySelectorAll({json.dumps(scope)})).find(b=>"
                f"b.offsetWidth && b.textContent.trim()==={json.dumps(label)})")
        b.wait_for("!!(" + expr + ")")
        b.evaluate(expr + ".click()")

    def submitted():
        b.wait_for("!!document.querySelector('.change-review[open],dialog[open] .change-review-fields') || "
                   "document.querySelectorAll('dialog[open]').length>=2")
        b.evaluate("[...document.querySelectorAll('dialog[open]')].at(-1).querySelector('.btn-primary').click()")
        b.wait_for("!document.querySelector('dialog[open]')")

    login("family-browser")
    click("查看简报")
    b.wait_for("document.querySelector('dialog[open]')?.textContent.includes('待完成')")
    click("标为已读", "dialog[open] button")
    submitted()
    b.wait_for("document.querySelector('.family-mail tbody')?.textContent.includes('已读')")
    click("照护服务")
    click("评价")
    b.evaluate("{const f=document.querySelector('dialog[open] form');f.elements.rating.value='4';f.requestSubmit()}")
    submitted()
    b.wait_for("document.querySelector('.family-view-body tbody')?.textContent.includes('4 分')")
    click("已完成服务")
    b.wait_for("document.querySelector('.family-view-body h2')?.textContent==='已完成服务'")
    b.click(".family-view-body tbody button")
    b.wait_for("document.querySelector('dialog[open]')?.textContent.includes('服务状态')")
    b.evaluate("document.querySelector('dialog[open]').close()")
    click("用药记录")
    b.click(".family-view-body tbody button")
    b.wait_for("document.querySelector('dialog[open]')?.textContent.includes('已复核医嘱')")
    b.evaluate("document.querySelector('dialog[open]').close()")
    click("账单与提醒")
    b.wait_for("document.querySelector('.family-view-body h2')?.textContent==='缴费与续住提醒'")
    click("续住提醒")
    b.wait_for("document.querySelector('dialog[open]')?.textContent.includes('请核对续住登记 · r003')")
    assert not b.evaluate("document.body.innerText.includes('请核对续住登记 · r002')")
    b.evaluate("document.querySelector('dialog[open]').close()")
    click("我的亲属资料")
    click("编辑本人资料")
    b.wait_for("!!document.querySelector('dialog[open] form [name=phone]')")
    b.evaluate("document.querySelector('dialog[open]').close()")
    b.evaluate("location.hash='tour'")
    b.wait_for("document.querySelectorAll('.family-tour-stop').length===4 && !!document.querySelector('.family-tour-published')")
    b.wait_for("document.querySelectorAll('.room-tour-stop').length===2 && document.querySelector('.room-scene-photo')?.naturalWidth>0")
    before = b.evaluate("document.querySelector('.room-scene-photo').src")
    click("下一站", ".room-tour-move button")
    b.wait_for("document.querySelector('.room-scene-photo')?.naturalWidth>0 && document.querySelector('.room-scene-photo').src!==" + json.dumps(before))
    assert not b.evaluate("document.querySelector('.room-tour-move').innerText.includes('撤下视点')")
    b.click('.family-tour-stop[href$="scene=bedroom"]')
    b.wait_for("location.pathname==='/roomtour' && document.querySelector('#scene-name')?.textContent==='长辈居室'")
    logout()
    login("resident-browser")
    click("生活与健康")
    b.wait_for("document.querySelector('.family-view-body')?.textContent.includes('健康简介')")
    click("用药记录")
    b.wait_for("document.querySelector('.family-view-body')?.textContent.includes('填写用药')")
    click("分享授权")
    b.wait_for("document.querySelector('.family-view-body')?.textContent.includes('我的简报分享授权')")
    assert not b.evaluate("document.querySelector('.family-views').textContent.includes('我的亲属资料')")
    logout()
    login("limited-family")
    assert b.evaluate("Array.from(document.querySelectorAll('.family-views button'), b=>b.textContent)") == ["收件箱", "我的亲属资料"]
    b.evaluate("location.hash='family?tab=medication'")
    b.wait_for("document.querySelector('.family-view-body')?.textContent.includes('站内收件箱')")
    assert b.evaluate("fetch('/api/state').then(r=>r.json()).then(s=>fetch('/api/portal/history/medication?offset=0&revision='+s.revision)).then(r=>r.status)") == 403
    assert not b.errors, b.errors
    print("Verified family inbox, consent-scoped service/medication views, rating, personal profile, tour and account isolation")


if __name__ == "__main__":
    run_browser(verify, seed=seed)
