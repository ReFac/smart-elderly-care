"""Exercise the Chinese hospital directory in Chrome with real authenticated visit supplements."""
import json

from public_visitors import run_browser
from perf_workspace import PASSWORD
from test_medical_visits import fixture_visit


def run():
    record = {}
    def seed(store):
        user = store.login("owner", PASSWORD)[0]
        record["id"] = fixture_visit(store, user, "r001", store.now().date().isoformat())

    def verify(b, port):
        b.call("Page.navigate", url=f"http://127.0.0.1:{port}/?workspace=1")
        b.wait_for("Boolean(document.querySelector('.access-login-form'))")
        b.evaluate("""{const f=document.querySelector('.access-login-form'); f.elements.username.value='owner';
            f.elements.password.value=""" + json.dumps(PASSWORD) + """; f.requestSubmit();}""")
        b.wait_for("Boolean(document.querySelector('.account-trigger'))")
        assert b.evaluate("window.NH_DEPLOYMENT.language") == "zh-CN"
        b.evaluate("""(async()=>{
          const get = async path=>(await fetch(path)).json();
          const ui=await import('/lib/ui.js'), {detail}=await import('/lib/dialogs.js');
          const {reviewVisit}=await import('/features/medical-visit-review.js');
          const {data:state,revision}=await get('/api/state');
          const person=state.residents.find(row=>row.id==='r001');
          const res=await fetch('/api/residents/r001/medical-visits/preview',{method:'POST',
            headers:{'Content-Type':'application/json'},body:JSON.stringify({revision, mode:'manual',
            visitId:""" + json.dumps(record["id"]) + """,requestId:'directory-ui',
            fields:{facility:'原就诊医院', tests:'已记录的复查资料'}})});
          if (!res.ok) throw new Error(await res.text());
          reviewVisit({state, ui, detail, get, toast:()=>{}, refreshWorkspace:async()=>true},person,await res.json(),[],{});
        })()""")
        b.click(".medical-map-directory summary")
        assert b.evaluate("document.querySelector('.medical-map-directory input').value === ''")
        b.evaluate("""{const i=document.querySelector('.medical-map-directory input'); i.value='测试市医院';
                     i.dispatchEvent(new Event('input',{bubbles:true}));}""")
        assert ("POST", "/api/catalog/hospitals/online") not in b.api
        href = b.evaluate("document.querySelector('.medical-map-actions a').href")
        assert href.startswith("https://uri.amap.com/search?")
        b.click(".medical-map-actions button")
        b.wait_for("Boolean(document.querySelector('.medical-map-status')?.textContent.includes('可点击'))")
        assert b.api.count(("POST", "/api/catalog/hospitals/online")) == 1
        assert b.evaluate("document.querySelector('.medical-visit-form [name=facility]').value") == "原就诊医院"
        assert ("POST", "/api/commands") not in b.api
        b.click(".medical-visit-form input[type=checkbox]")
        b.click(".medical-visit-form button[type=submit]")
        b.wait_for("!document.querySelector('dialog.medical-visit-dialog[open]')")
        assert b.evaluate("fetch('/api/state').then(r=>r.json()).then(({data})=>data.medicalVisits.some(v=>v.parentVisitId===" +
                          json.dumps(record["id"]) + " && v.fields.facility==='原就诊医院'))")
        assert not b.errors, b.errors

    run_browser(verify, seed)


if __name__ == "__main__":
    run()
    print("中文版医院目录、地图查询、无密钥回退和员工确认就诊补充均已验证。")
