"""Verify demo discovery, the real medical record and its signed original in Chromium."""

import json

from public_visitors import run_browser
from perf_workspace import PASSWORD
from platform_core import sample


def seed(store):
    token, _ = store.login("owner", PASSWORD)
    try:
        sample.populate(store, token)
    finally:
        store.logout(token)


def verify(b, port):
    b.call("Page.navigate", url=f"http://127.0.0.1:{port}/?workspace=1")
    b.wait_for("!!document.querySelector('.access-login-form')")
    b.evaluate("""{const f=document.querySelector('.access-login-form'); f.elements.username.value='owner';
        f.elements.password.value=""" + json.dumps(PASSWORD) + ";f.requestSubmit()}")
    b.wait_for("!!document.querySelector('.desk-home-actions button')")
    b.click(".desk-home-actions button")
    b.wait_for("document.querySelectorAll('.demo-guide-case').length===4")
    b.evaluate("Array.from(document.querySelectorAll('.demo-guide-case')).find(b=>b.innerText.includes('沈月兰') && b.innerText.includes('复诊记录')).click()")
    b.wait_for("!!document.querySelector('dialog[open] .medical-visit-linked-documents')")
    assert b.evaluate("document.querySelector('.medical-visit-target').innerText.includes('沈月兰')")
    assert b.evaluate("document.querySelector('.medical-visit-originals select').value") == "0"
    original = b.evaluate("""fetch(document.querySelector('.medical-visit-originals a[download]').href)
        .then(async r=>[r.status,r.headers.get('content-type'),(await r.text()).slice(0,5)])""")
    assert original == [200, "application/pdf", "%PDF-"], original
    assert b.evaluate("!!document.querySelector('.resident-record-workspace')")
    assert not b.errors, b.errors
    print("Demo guide opened the selected resident's follow-up, its PDF original and its linked supplement.")


if __name__ == "__main__":
    run_browser(verify, seed)
