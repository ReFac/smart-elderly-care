"""Exercise English registration, contact and staff forms through actual browser controls."""
from unittest import skip

SKIP_REASON = "仅测试中文版，国际版专项浏览器测试已归档。"
if __name__ == "__main__":
    print("SKIP — " + SKIP_REASON)
    raise SystemExit(0)

from contextlib import closing, contextmanager
from datetime import timedelta
import json
from unittest.mock import patch


@skip(SKIP_REASON)
@contextmanager
def international_server(root, seed, *, language):
    from perf_workspace import credential_env, server

    env = {**credential_env(root), "NH_DEPLOYMENT_LANGUAGE":language}
    with patch("perf_workspace.credential_env", return_value=env), server(root, seed) as endpoint:
        yield endpoint


@skip(SKIP_REASON)
def seed_navigation(store):
    from perf_workspace import PASSWORD
    from platform_core import provider
    from platform_core.agents import chat

    token, _ = store.login("owner",PASSWORD)
    with closing(store.connect()) as db, db:
        expires = (store.now().date() + timedelta(days=5)).isoformat()
        provider.grant(db,"Synthetic UI test",100_000,expires,now=store.now())
    with patch.object(provider,"read_key",return_value="test-only"):
        response = {"usage":{"total_tokens":24},"choices":[{"finish_reason":"stop","message":{"content":"Open Inventory."}}]}
        chat.reply(store,token,{"text":"Show inventory","requestId":"test-inventory"},
                   transport=lambda *_: response)
    store.logout(token)


@skip(SKIP_REASON)
def verify(b, port):
    from perf_workspace import PASSWORD

    origin = f"http://127.0.0.1:{port}"

    def fill(selector, values):
        for key, value in values.items():
            item = json.dumps(selector + ' [name="' + key + '"]')
            b.evaluate("{let field=document.querySelector(" + item + ");field.value="+json.dumps(value)+
                       ";field.dispatchEvent(new Event('input',{bubbles:true}))}")

    def click_when(selector):
        b.wait_for("!!document.querySelector("+json.dumps(selector)+")")
        b.click(selector)

    b.call("Page.navigate",url=origin+"/visit#book-visit")
    b.wait_for("!!document.querySelector('#visit-form input[name=given]') && !document.querySelector('#visit-form button[type=submit]').disabled")
    fill("#visit-form",{"given":"María","family":"de la Cruz","phone":"+1 (202) 555-0105"})
    b.click("#visit-form input[name=consent]")
    b.evaluate("document.querySelector('#visit-form').requestSubmit()")
    b.wait_for("document.querySelector('#visit-form').hidden")
    b.call("Page.navigate",url=origin+"/?workspace=1#residents")
    b.wait_for("!!document.querySelector('.access-login-form')")
    fill(".access-login-form",{"username":"owner","password":PASSWORD})
    b.evaluate("document.querySelector('.access-login-form').requestSubmit()")
    click_when(".desk-assistant-float")
    b.wait_for("!!document.querySelector('.assistant-page-link')")
    before = b.evaluate("location.hash")
    assert before.startswith("#residents") and "Inventory" in b.evaluate("document.querySelector('.assistant-page-link').textContent")
    if b.evaluate("window.NH_DEPLOYMENT.language") == "en":
        assert b.evaluate("document.querySelector('.assistant-page-link').textContent.trim()") == "Open Inventory"
    b.click(".assistant-page-link")
    b.wait_for("location.hash === '#inventory' && !!document.querySelector('.assistant-compact')")
    b.call("Page.navigate",url=origin+"/?workspace=1#residents")
    click_when(".roster-heading .btn-primary")
    b.wait_for("!!document.querySelector('.dossier-form input[name=given]')")
    assert not b.evaluate("performance.getEntriesByType('resource').some(r=>r.name.endsWith('/assets/address-regions.json'))")
    fill(".dossier-form",{"given":"José","middle":"Luis","family":"de Ávila","street":"85 King Street",
                          "unit":"Flat 2B","locality":"London","postalCode":"SW1A 1AA","country":"United Kingdom"})
    b.evaluate("document.querySelector('.dossier-form').closest('form').requestSubmit()")
    click_when(".change-review-dialog[open] .btn-primary")
    b.wait_for("!document.querySelector('.dossier-form')")
    query = ".roster-filters input[type=search]"
    b.evaluate("document.querySelector("+json.dumps(query)+").value='jose luis de avila'; document.querySelector('.roster-filters').requestSubmit()")
    b.wait_for("document.querySelector('.roster-table-wrap')?.innerText.includes('José Luis de Ávila')")
    b.evaluate("location.hash='access'")
    click_when(".access-management .btn-primary")
    b.wait_for("!!document.querySelector('.access-form input[name=given]')")
    fill(".access-form",{"given":"Niamh","family":"O’Donnell","username":"synthetic-nurse","destination":"00 44 (7700) 900-555",
                         "street":"6 Smith Road","locality":"Dublin","country":"Ireland"})
    b.evaluate("document.querySelector('.access-form').requestSubmit()")
    click_when(".change-review-dialog[open] .btn-primary")
    b.wait_for("!document.querySelector('.access-form')")
    data=b.evaluate("fetch('/api/state').then(r=>r.json()).then(s=>s.data)")
    person=next(p for p in data["residents"] if p["name"]=="José Luis de Ávila")
    profile=next(p for p in data["dossierProfiles"] if p["residentId"]==person["id"])
    assert profile["internationalAddress"]["postalCode"]=="SW1A 1AA" and profile["nameParts"]["middle"]=="Luis"
    employee=next(a for a in data["accounts"] if a["username"]=="synthetic-nurse")
    assert employee["nameParts"]["family"]=="O’Donnell" and employee["internationalAddress"]["locality"]=="Dublin"
    hits=b.evaluate("""fetch('/api/accounts/by-phone',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({phone:'+44 (7700) 900-555'})}).then(r=>r.json())""")
    assert hits=={"accountIds":[employee["id"]]}
    assert any(l["nameParts"]["given"]=="María" and l["phone"]=="+12025550105" for l in data["leadContacts"] if l.get("nameParts"))
    preview = b.evaluate("""(async () => {
      const {editResident} = await import('/features/profile-editor.js');
      async function submit(original, creation) {
        let submitForm, result;
        const ctx={state:{allowedActions:[], residents:[], user:{kind:'staff',permissions:['intake']}, today:'2026-11-26'},
          dialog(options){submitForm=options.onSubmit; return options.content},
          command(action,payload){result=payload}, toast(msg){throw Error(msg)}};
        const person=creation?{}:{id:'synthetic-draft',name:'Resident Sample'};
        const draft={fields:{name:'Resident Sample',address:'99 Carrer Major, Barcelona, España',birthplace:'Girona'}};
        await editResident(ctx,person,original,null,draft,creation?{}:null);
        await submitForm();
        return creation?result.profile:result;
      }
      return [await submit({},true), await submit({address:'Previous Road',internationalAddress:{street:'Previous Road'}},false)];
    })()""")
    assert all(p["address"]=="99 Carrer Major, Barcelona, España" and p["birthplace"]=="Girona" for p in preview)
    b.call("Network.clearBrowserCookies")
    b.call("Page.navigate",url=origin+"/visitor-register.html")
    b.wait_for("!!document.querySelector('#visitor-register input[name=given]')")
    fill("#visitor-register",{"given":"Ana María","family":"Díaz López","username":"synthetic-visitor",
                              "password":"visitor-synthetic-password"})
    b.evaluate("document.querySelector('#visitor-register').requestSubmit()")
    b.wait_for("location.search === '?workspace=1' && !!document.querySelector('#content')")
    user=b.evaluate("fetch('/api/state').then(r=>r.json()).then(s=>s.data.user)")
    assert user["displayName"]=="Ana María Díaz López" and user["nameParts"]["family"]=="Díaz López"
    assert not b.errors,b.errors
    print("Verified international resident, employee, public registration, reception and accent-insensitive lookup.")
