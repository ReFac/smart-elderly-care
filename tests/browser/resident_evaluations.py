"""Verify personal evaluation reports from the resident roster with an isolated institution."""
import argparse
import base64
from functools import partial
import json
from pathlib import Path

from public_visitors import run_browser
from perf_workspace import PASSWORD


def seed(store, *, screenshot_staff=False):
    token = store.login("owner", PASSWORD)[0]

    def save(action, payload):
        store.execute(action, payload, store.version(token)["revision"], token)

    save("care.screen", {"residentId": "r002", "subject": "另一位长辈的原表", "finding": "合成观察记录"})
    save("access.create", {"kind":"staff", "role":"自定义", "displayName":"档案查阅员", "username":"care-reader",
                           "password": PASSWORD, "permissions":["residents", "care"]})
    if screenshot_staff:
        save("access.create", {"kind":"staff", "role":"护士", "displayName":"周宁", "username":"evaluation-nurse",
                               "password":PASSWORD})


def verify(browser, port, screenshots=None):
    b = browser
    origin = f"http://127.0.0.1:{port}"

    def click_text(selector, text):
        expression = f"Array.from(document.querySelectorAll({json.dumps(selector)})).find(b=>b.textContent.trim()==={json.dumps(text)})"
        b.wait_for(f"Boolean({expression})")
        b.evaluate(f"({expression}).click()")

    def open_person(username):
        b.call("Page.navigate", url=origin + "/?workspace=1")
        b.wait_for("!!document.querySelector('.access-login-form')")
        b.evaluate("""{const f=document.querySelector('.access-login-form');f.elements.username.value=""" +
                   json.dumps(username) + ";f.elements.password.value=" + json.dumps(PASSWORD) + ";f.requestSubmit()}")
        b.wait_for("!!document.querySelector('.sidebar a[href=\"#dossier\"]')")
        b.click('.sidebar a[href="#dossier"]')
        b.wait_for("!!document.querySelector('.resident-roster input[type=search]')")
        b.evaluate("""{const q=document.querySelector('.resident-roster input[type=search]');q.value='r001';
                       q.dispatchEvent(new Event('input'));}""")
        click_text(".resident-roster tbody button", "详情")
        b.wait_for("!!document.querySelector('.resident-record-workspace[data-rounds-resident-id=r001]')")
        b.click('[data-dossier-tab="medical"]')
        b.wait_for("!!document.querySelector('.resident-evaluations tbody tr')")

    def screenshot(name):
        if screenshots:
            screenshots.mkdir(parents=True, exist_ok=True)
            raw = b.call("Page.captureScreenshot", format="png", captureBeyondViewport=False)["data"]
            (screenshots / name).write_bytes(base64.b64decode(raw))

    b.call("Emulation.setDeviceMetricsOverride", width=1600, height=1280, deviceScaleFactor=1, mobile=False)
    open_person("owner")
    text = b.evaluate("document.querySelector('.resident-evaluations').innerText")
    assert all(label in text for label in ("个人医疗评价", "床旁环境观察表", "能力评估", "登记日期", "评估人员")), text
    assert "另一位长辈的原表" not in text
    original = b.evaluate("location.hash")
    screenshot("resident-medical-evaluations.png")
    b.evaluate("""{const r=[...document.querySelectorAll('.resident-evaluations tr')]
                        .find(r=>r.textContent.includes('床旁环境观察表'));r.querySelector('button').click()}""")
    b.wait_for("!!document.querySelector('dialog.risk-drawer[open] .risk-factor-list')")
    assert b.evaluate("document.querySelector('.risk-score strong').textContent==='10' && document.querySelectorAll('.risk-steps li').length===3")
    if screenshots:
        assert b.evaluate("document.querySelector('.evaluation-identity').textContent.includes('周宁（护士）')")
        b.evaluate("Promise.all(document.getAnimations().map(a=>a.finished.catch(()=>{})))")
        extra = b.evaluate("""(()=>{const el=document.querySelector('dialog.risk-drawer .dialog-body');
                                     return el.scrollHeight-el.clientHeight;})()""")
        if extra > 1:
            b.call("Emulation.setDeviceMetricsOverride", width=1600, height=1280+extra+8, deviceScaleFactor=1, mobile=False)
    screenshot("resident-medical-risk-report.png")
    click_text("dialog[open] button", "其他评估")
    assert "另一位长辈的原表" not in b.evaluate("document.querySelector('dialog[open]').textContent")
    b.evaluate("""{const s=[...document.querySelectorAll('dialog[open] section')].find(
                    s=>s.querySelector('h3')?.textContent==='能力与照护评估');s.querySelector('button').click()}""")
    b.wait_for("document.querySelectorAll('dialog[open]').length===2")
    assert "评估记录" == b.evaluate("Array.from(document.querySelectorAll('dialog[open]')).at(-1).getAttribute('aria-label')")
    b.evaluate("Array.from(document.querySelectorAll('dialog[open]')).at(-1).querySelector('.dialog-head button').click()")
    b.wait_for("document.querySelectorAll('dialog[open]').length===1")
    b.click("dialog[open] .dialog-head button")
    b.wait_for("!document.querySelector('dialog[open]')")
    assert b.evaluate("location.hash") == original
    assert b.evaluate("document.querySelector('[data-dossier-tab=medical]').getAttribute('aria-selected')==='true'")

    for title in ("登记专项评估", "登记能力评估"):
        click_text(".resident-evaluations button", title)
        b.wait_for("!!document.querySelector('dialog[open] form')")
        assert b.evaluate("Array.from(document.querySelector('dialog[open] [name=residentId]').options,o=>o.value)") == ["r001"]
        b.click("dialog[open] .dialog-head button")

    b.evaluate("fetch('/api/auth/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(r=>r.status)")
    open_person("care-reader")
    text = b.evaluate("document.querySelector('.resident-evaluations').innerText")
    assert "能力评估" in text and "床旁环境观察表" not in text and "登记专项评估" not in text
    assert "登记能力评估" not in text
    click_text(".resident-evaluations tbody button", "查看报告")
    b.wait_for("!!document.querySelector('dialog[open] .risk-report')")
    assert not b.errors, b.errors
    print("Personal medical evaluations passed for Owner and care-only staff, including scoped records and nested drawers.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshots", type=Path)
    options = parser.parse_args()
    run_browser(partial(verify, screenshots=options.screenshots),
                seed=partial(seed, screenshot_staff=bool(options.screenshots)))
