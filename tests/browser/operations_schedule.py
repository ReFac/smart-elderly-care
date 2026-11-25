"""Check bed navigation and the real scheduling/confirmation flows with isolated test data."""
import json

from public_visitors import run_browser
from perf_workspace import PASSWORD


def seed(store):
    from platform_core import care_areas, facility

    token, _ = store.login("owner", PASSWORD)
    room = care_areas.read(store, token, facility.MAIN)["rooms"][0]
    store.execute(
        "care.areaSave",
        {"name": "验收区域", "parentId": "", "buildingId": facility.MAIN, "roomIds": [room["id"]]},
        store.version(token)["revision"], token,
    )


def verify(b, port):
    def go(route):
        b.evaluate("location.hash=" + json.dumps(route))

    def click(label, selector="button,a"):
        button = (
            f"Array.from(document.querySelectorAll({json.dumps(selector)}))"
            f".find(el=>el.offsetWidth && el.textContent.trim()==={json.dumps(label)})"
        )
        b.wait_for("!!(" + button + ")")
        b.evaluate(button + ".click()")

    def change(name, value):
        b.evaluate(
            "{const input=document.querySelector('dialog[open] form').elements.namedItem("
            + json.dumps(name) + "); input.value=" + json.dumps(value)
            + "; input.dispatchEvent(new Event('change',{bubbles:true}));}"
        )

    def submit():
        b.evaluate("document.querySelector('dialog[open] form').requestSubmit()")
        b.wait_for("document.querySelectorAll('dialog[open]').length >= 2")
        b.evaluate("[...document.querySelectorAll('dialog[open]')].at(-1).querySelector('.btn-primary').click()")
        b.wait_for("!document.querySelector('dialog[open]')")

    b.call("Page.navigate", url=f"http://127.0.0.1:{port}/?workspace=1")
    b.wait_for("!!document.querySelector('.access-login-form')")
    b.evaluate("{const f=document.querySelector('.access-login-form'); f.elements.username.value='owner';"
               "f.elements.password.value=" + json.dumps(PASSWORD) + ";f.requestSubmit()}")
    b.wait_for("!!document.querySelector('.desk-tabbar')")
    go("beds")
    click("办理入住", ".bed-list-grid button")
    b.wait_for("!!document.querySelector('dialog[open]')")
    b.evaluate("document.querySelector('dialog[open]').close()")
    click("房间看板", ".bed-list-status button")
    b.wait_for("!!document.querySelector('.bed-list-room .fx-bed')")
    click("床位台账", ".bed-list-status button")
    click("平面图定位", ".bed-list-grid button")
    b.wait_for("document.querySelector('.room-detail')?.innerText.includes('验收区域')")
    click("查看本层床位台账")
    b.wait_for("!![...document.querySelectorAll('.bed-list-control')].find(l=>"
               "l.firstChild.textContent==='楼层')?.querySelector('select').value")
    go("beds?tab=zones")
    click("查看区域床位台账")
    b.wait_for("document.querySelector('.bed-list-grid tbody')?.textContent.includes('验收区域')")
    assert b.evaluate("[...document.querySelectorAll('.bed-list-grid tbody tr')].every(r=>r.textContent.includes('验收区域'))")

    go("shifts")
    b.wait_for("!!document.querySelector('.shift-calendar')")
    b.click('[aria-label$="早班安排班次"]')
    # Today can be any weekday. A new staff name avoids conflicts with the demo shifts.
    field = "document.querySelector('dialog[open] form').elements.staff"
    b.wait_for(f"!!({field})")
    person = "排班验收员工"
    if b.evaluate(field + ".tagName === 'SELECT'"):
        change("staff", "__custom_option__")
    change("staff", person)
    submit()
    button = f"[...document.querySelectorAll('.shift-calendar td button')].find(b=>b.textContent.includes({json.dumps(person)}))"
    b.wait_for("!!(" + button + ")")
    b.evaluate(button + ".click()")
    b.wait_for("document.querySelector('dialog[open]')?.textContent.includes('当日照护工单')")
    b.evaluate("document.querySelector('dialog[open]').close()")
    click("全部排班台账")
    b.wait_for("document.querySelector('.agenda-results tbody')?.textContent.includes(" + json.dumps(person) + ")")

    go("leads")
    click("手工登记")
    change("phone", "13900000017")
    change("name", "接待验收访客")
    submit()
    go("leads?tab=schedule")
    click("后一天")
    b.wait_for("document.querySelector('.lead-day-info')?.textContent.includes('个并行席位')")
    click("电话确认排期")
    lead = b.evaluate("[...document.querySelector('dialog[open] form').elements.leadId.options]"
                      ".find(o=>o.textContent.includes('接待验收访客')).value")
    change("leadId", lead)
    b.wait_for("[...document.querySelector('dialog[open] form').elements.start.options].some(o=>o.value==='16:00')")
    change("start", "16:00")
    change("end", "17:00")
    b.click("dialog[open] input[type=checkbox]")
    submit()
    b.wait_for("document.querySelector('.lead-booking')?.innerText.includes('接待验收访客')")
    click("预约台账")
    b.wait_for("document.querySelector('.lead-day tbody')?.innerText.includes('16:00–17:00')")
    click("取消预约")
    change("feedback", "来电取消预约")
    submit()
    b.wait_for("document.querySelector('.lead-day tbody')?.innerText.includes('已取消')")
    assert b.evaluate("document.querySelector('.lead-day-info').textContent.includes('0 项已确认安排')")
    assert not b.errors, b.errors
    print("Verified bed and floor plan navigation, staff scheduling, reception booking and cancellation")


if __name__ == "__main__":
    run_browser(verify, seed=seed)
