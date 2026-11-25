"""Personal settings with independent browser storage and the same institutional account."""
import json
from public_visitors import run_browser
from perf_workspace import PASSWORD


def verify(browser, port):
    b = browser
    b.call("Emulation.setDeviceMetricsOverride", width=1500, height=855, deviceScaleFactor=1, mobile=False)
    b.call("Page.navigate", url=f"http://127.0.0.1:{port}/?workspace=1")
    b.wait_for("!!document.querySelector('.access-login-form')")
    b.evaluate("""{const form=document.querySelector('.access-login-form');
        form.elements.username.value='owner'; form.elements.password.value=""" + json.dumps(PASSWORD) + """;
        form.requestSubmit()}""")
    b.wait_for("!!document.querySelector('.desk-home')")
    # Personal appearance follows the account across a clean device unless explicitly opted out.
    b.click('.account-trigger')
    b.evaluate("Array.from(document.querySelectorAll('dialog button')).find(b=>b.textContent==='外观与显示').click()")
    b.wait_for("!!document.querySelector('.personal-display')")
    f = "document.querySelector('.personal-display').elements"
    assert b.evaluate(f"[{f}.level.min,{f}.level.max,{f}.level.value,{f}.source.value]") == ["1","10","3","account"]
    sizes = []
    for level in range(1, 11):
        b.evaluate(f"{{const e={f}.level;e.value={level};e.dispatchEvent(new Event('input',{{bubbles:true}}));}}")
        sizes.append(b.evaluate("parseFloat(getComputedStyle(document.querySelector('.personal-type-sample')).fontSize)"))
    assert sizes == list(range(12,22)), sizes
    b.evaluate(f"{{const f={f};f.mode.value='dark';f.family.value='serif';f.density.value='compact';document.querySelector('.personal-display').requestSubmit();}}")
    b.wait_for("document.querySelector('.personal-save-status')?.textContent.includes('保存到账号')")
    assert b.evaluate("document.documentElement.dataset.colorMode==='dark' && document.documentElement.dataset.density==='compact'")
    b.call("Emulation.setDeviceMetricsOverride", width=1500, height=855, deviceScaleFactor=1, mobile=False)
    b.call("Page.navigate", url=f"http://localhost:{port}/?workspace=1")
    b.wait_for("!!document.querySelector('.access-login-form')")
    b.evaluate("""{const form=document.querySelector('.access-login-form');
        form.elements.username.value='owner'; form.elements.password.value=""" + json.dumps(PASSWORD) + """;
        form.requestSubmit()}""")
    b.wait_for("!!document.querySelector('.desk-home')")
    b.click('.account-trigger')
    b.evaluate("Array.from(document.querySelectorAll('dialog button')).find(b=>b.textContent==='外观与显示').click()")
    b.wait_for("!!document.querySelector('.personal-display')")
    assert b.evaluate(f"[{f}.mode.value,{f}.family.value,{f}.level.value]") == ["dark","serif","10"]
    b.evaluate(f"{{const f={f};f.source.value='device';f.source.dispatchEvent(new Event('change'));f.mode.value='light';document.querySelector('.personal-display').requestSubmit();}}")
    b.wait_for("document.querySelector('.personal-save-status')?.textContent.includes('此设备')")
    assert b.evaluate("fetch('/api/account/display-preferences').then(r=>r.json()).then(s=>s.values.mode)") == "dark"
    b.call('Page.reload',ignoreCache=True)
    b.wait_for("!!document.querySelector('.personal-display')")
    assert b.evaluate(f"[{f}.mode.value,{f}.source.value]") == ["light","device"]
    b.call("Page.navigate", url=f"http://127.0.0.1:{port}/?workspace=1#account?tab=display")
    b.wait_for("!!document.querySelector('.personal-display')")
    assert b.evaluate(f"[{f}.mode.value,{f}.source.value]") == ["dark","account"]
    assert not b.errors, b.errors
    print("Account settings verified across two browser origins, including local opt-out and all ten font sizes.")

if __name__ == "__main__":
    run_browser(verify)
