"""Exercise staff refund and settlement through real forms in an isolated demo database."""

import json
from public_visitors import run_browser
from perf_workspace import PASSWORD


def seed(store):
    token, _ = store.login("owner", PASSWORD)
    bill = next(b for b in store.snapshot(token)["data"]["bills"] if b["balance"] > 12)
    store.execute(
        "ops.pay",
        {
            "billId": bill["id"],
            "amount": 12.34,
            "method": "线下登记",
            "channel": "现金",
        },
        store.version(token)["revision"],
        token,
    )


def check(browser, port):
    b = browser
    b.call(
        "Emulation.setDeviceMetricsOverride",
        width=1500,
        height=855,
        deviceScaleFactor=1,
        mobile=False,
    )
    b.call("Page.navigate", url=f"http://127.0.0.1:{port}/?workspace=1")
    b.wait_for("!!document.querySelector('.access-login-form')")
    b.evaluate(
        """{const f=document.querySelector('.access-login-form');f.elements.username.value='owner';
       f.elements.password.value="""
        + json.dumps(PASSWORD)
        + """;f.requestSubmit()}"""
    )
    b.wait_for("!!document.querySelector('.desk-home')")
    b.evaluate("document.querySelector('.sidebar a[title=\"收费记录\"]').click()")
    row = """Array.from(document.querySelectorAll('#content tr')).find(r=>r.textContent.includes('12.34'))"""
    b.wait_for("Boolean(" + row + ")")
    b.evaluate(
        "Array.from(("
        + row
        + ").querySelectorAll('button')).find(x=>x.textContent.trim()==='申请退款').click()"
    )
    b.wait_for("!!document.querySelector('dialog[open] [name=reason]')")
    b.evaluate("""{const f=document.querySelector('dialog[open] form');f.elements.amount.value='4.25';
       f.elements.reason.value='现场复核重复收款';f.requestSubmit()}""")

    def sign():
        b.wait_for("!!document.querySelector('.change-review-dialog[open]')")
        b.evaluate(
            "Array.from(document.querySelectorAll('.change-review-dialog[open] button')).find(x=>x.textContent.trim()==='确认执行').click()"
        )

    sign()
    pending = """Array.from(document.querySelectorAll('#content tr')).find(r=>r.textContent.includes('现场复核重复收款'))"""
    b.wait_for(pending + "?.textContent.includes('待核实')")
    b.evaluate(
        "Array.from(("
        + pending
        + ").querySelectorAll('button')).find(x=>x.textContent.trim()==='核实凭证').click()"
    )
    b.wait_for("!!document.querySelector('dialog[open] [name=reference]')")
    b.evaluate(
        """{const f=document.querySelector('dialog[open] form');f.elements.reference.value='UI-REFUND-001';f.requestSubmit()}"""
    )
    sign()
    b.wait_for(pending + "?.textContent.includes('已退款')")
    b.wait_for(
        "document.querySelector('#content').textContent.includes('UI-REFUND-001')"
    )
    assert b.evaluate(
        "Array.from(document.querySelectorAll('#content tr')).some(r=>r.textContent.includes('-¥4.25') || r.textContent.includes('-￥4.25'))"
    )
    assert not b.errors, b.errors
    print(
        "Verified original receipt, signed partial refund and posted reconciliation in the browser"
    )


if __name__ == "__main__":
    run_browser(check, seed)
