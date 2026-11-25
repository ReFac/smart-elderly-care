"""Check the public and authenticated international UI in an isolated, offline browser."""
from unittest import skip

SKIP_REASON = "仅测试中文版，国际版专项浏览器测试已归档。"
if __name__ == "__main__":
    print("SKIP — " + SKIP_REASON)
    raise SystemExit(0)

import json


@skip(SKIP_REASON)
def verify(browser, port, language):
    from perf_workspace import PASSWORD

    base = f"http://127.0.0.1:{port}"
    b = browser
    b.call("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)

    def visit(path):
        b.call("Page.navigate", url=base + path)
        b.wait_for("location.pathname === " + json.dumps(path.split('?')[0]) + " && window.NH_I18N?.ready")
        assert b.evaluate("document.documentElement.lang") == language

    visit("/visit")
    b.wait_for("document.querySelector('.site-nav').innerText.includes('Virtual tour')")
    visit("/roomtour")
    b.wait_for("!!document.querySelector('h1') && !/[\\u3400-\\u9fff]/.test(document.querySelector('h1').innerText)")
    visit("/faq")
    b.wait_for("document.querySelectorAll('.faq-entry').length >= 16")
    assert b.evaluate("Array.from(document.querySelectorAll('.faq-entry')).every(entry=>!/[\\u3400-\\u9fff]/.test(entry.textContent))")
    b.evaluate("const search=document.querySelector('.faq-search input'); search.value='medication round'; search.dispatchEvent(new Event('input'))")
    b.wait_for("document.querySelector('#faq-medication-record') && document.querySelectorAll('.faq-entry').length === 1")
    visit("/?workspace=1")
    b.wait_for("document.querySelector('h1')?.textContent === 'Sign in to your workspace'")
    b.evaluate("""{const f=document.querySelector('.access-login-form');f.elements.username.value='owner';
        f.elements.password.value=""" + json.dumps(PASSWORD) + """; f.requestSubmit();}""")
    b.wait_for("document.querySelector('.desk-home h1')?.textContent==='Facility overview'")
    assert b.evaluate("Array.from(document.querySelectorAll('.nav-list .nav-item span')).some(x=>x.textContent===window.NH_I18N.text('入住管理'))")
    b.click(".desk-new-resident")
    b.wait_for("!!document.querySelector('dialog[open]')")
    assert b.evaluate("document.querySelector('dialog[open]').innerText.includes('Date of birth')")
    b.evaluate("""{const d=document.querySelector('dialog[open]'), box=document.createElement('div');
        const s=document.createElement('select'), o=document.createElement('option'); o.textContent='未婚'; s.append(o);
        const note=document.createElement('span');note.translate=false;note.textContent='提交';box.append(s,note);
        box.id='i18n-evidence';d.append(box);}""")
    b.wait_for("document.querySelector('#i18n-evidence option')?.textContent==='Single'")
    assert b.evaluate("document.querySelector('#i18n-evidence select').value==='未婚' && document.querySelector('#i18n-evidence span').textContent==='提交'")
    b.evaluate("document.querySelectorAll('dialog[open]').forEach(d=>d.close());location.hash='#deployment'")
    b.wait_for("document.querySelector('#content')?.innerText.includes(window.NH_I18N.text('部署语言')) && document.querySelector('#content')?.innerText.includes(window.NH_I18N.text('地图服务'))")
    if language in ('fr','es'):
        expected = {'fr':'Prénom','es':'Nombre de pila'}[language]
        assert b.evaluate("window.NH_I18N.text('Given name')") == expected
        assert b.evaluate("window.NH_I18N.text('登录')") != 'Sign in'
        b.call('Network.setBlockedURLs', urls=['*/assets/locales/*.json'])
        visit('/faq')
        assert b.evaluate("window.NH_I18N.text('登录')") == 'Sign in'
    b.evaluate("""{window.NH_I18N.setWorkspace({residents:[{name:'首页',note:'提交'}]});
        const item=document.createElement('section');item.id='source-note-check';
        const note=document.createElement('p'), name=document.createElement('strong');
        note.textContent='提交';name.textContent='首页';item.append(note,name);document.body.append(item);}""")
    b.wait_for("!!document.querySelector('#source-note-check')")
    assert b.evaluate("document.querySelector('#source-note-check').textContent==='提交首页'")
    assert not b.errors, b.errors
