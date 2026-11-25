"""Exercise signed terminal payment from an open admission form to its first settled bill."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hmac
import json
from unittest.mock import patch
from urllib.request import Request, urlopen

from public_visitors import run_browser
from perf_workspace import PASSWORD, credential_env, server

KEY = bytes(range(32))


@contextmanager
def terminal_server(root, seed):
    key = root / "terminal.key"
    key.write_bytes(KEY)
    env = {**credential_env(root), "NH_TERMINAL_ID": "sample-reader", "NH_TERMINAL_KEY_FILE": str(key)}
    with patch("perf_workspace.credential_env", return_value=env), server(root, seed) as result:
        yield result


def seed(store):
    token, _ = store.login("owner", PASSWORD)
    store.execute("care.register", {"name":"定额收款演练"}, store.version(token)["revision"], token)
    store.logout(token)


def verify(b, port):
    origin = f"http://127.0.0.1:{port}"
    b.call("Page.navigate",url=origin + "/?workspace=1#residents?tab=notAdmitted")
    b.wait_for("!!document.querySelector('.access-login-form')")
    b.evaluate("""{const f=document.querySelector('.access-login-form');f.elements.username.value='owner';
        f.elements.password.value=""" + json.dumps(PASSWORD) + "; f.requestSubmit()}")
    b.wait_for("Array.from(document.querySelectorAll('#content tr')).some(r=>r.innerText.includes('定额收款演练'))")
    b.evaluate("""{const r=Array.from(document.querySelectorAll('#content tr')).find(r=>r.innerText.includes('定额收款演练'));
        Array.from(r.querySelectorAll('button')).find(b=>b.textContent==='办理入住').click()}""")
    b.wait_for("!!document.querySelector('.admission-finance-form')")
    b.evaluate("""{const f=document.querySelector('.admission-finance-form').elements;
        f.paymentMode.value='terminal';f.paymentMode.dispatchEvent(new Event('change',{bubbles:true}));
        f.allocateSecurityFromPrepaid.checked=true;}""")
    b.wait_for("document.querySelector('.admission-collection select')?.options.length === 3")
    def click_text(where, label):
        b.evaluate("Array.from(document.querySelectorAll("+json.dumps(where+" button")+")).find(b=>b.textContent.trim()==="+json.dumps(label)+").click()")
    click_text(".admission-finance-form","核算首期费用")
    b.wait_for("Number(document.querySelector('.admission-collection input')?.value)>0")
    click_text(".admission-finance-form","发起定额收款")
    b.wait_for("!!document.querySelector('.change-review-dialog[open]')")
    b.click('.change-review-dialog .btn-primary')
    b.wait_for("document.querySelector('.admission-collection [role=status]')?.innerText.includes('请在收银终端')")
    order = b.evaluate("fetch('/api/state').then(r=>r.json()).then(s=>s.data.paymentOrders[0])")
    # Submit once before payment, then report a successful test adapter receipt.
    b.evaluate("document.querySelector('.admission-finance-form').requestSubmit()")
    b.wait_for("document.querySelector('.admission-finance-form .form-error')?.textContent.includes('收到渠道到账回执')")
    amount = round(100 * order["amount"])
    now = datetime.now(timezone.utc)
    message = json.dumps(dict(orderId=order["id"], status="SUCCESS", amountCents=amount, currency="CNY",
                              transactionId="demo-terminal-e2e",channel=order["channel"],paidAt=now.isoformat())).encode()
    stamp = str(int(now.timestamp()))
    signature = hmac.digest(KEY, f"v1\nsample-reader\nreceipt\n{stamp}\n".encode()+message,"sha256").hex()
    with urlopen(Request(origin+"/api/payments/terminal/v1/receipt",data=message,headers={
        "Content-Type":"application/json","X-Terminal-Id":"sample-reader","X-Terminal-Time":stamp,
        "X-Terminal-Signature":signature}), timeout=10) as response:
        assert json.load(response)["status"]=="已到账"
    click_text(".admission-finance-form","核对到账状态")
    b.wait_for("document.querySelector('.admission-collection [role=status]')?.innerText.includes('已到账')")
    b.evaluate("document.querySelector('.admission-finance-form').requestSubmit()")
    b.wait_for("!!document.querySelector('.change-review-dialog[open]')")
    b.click('.change-review-dialog .btn-primary')
    b.wait_for("!document.querySelector('.admission-finance-form')")
    data=b.evaluate("fetch('/api/state').then(r=>r.json()).then(s=>s.data)")
    person=next(p for p in data["residents"] if p["name"]=="定额收款演练")
    assert person["status"]=="在住" and person["admissionPayment"]["paymentOrderId"]==order["id"]
    bills=[r for r in data["bills"] if r["residentId"]==person["id"]]
    assert len(bills)==2 and all(r["balance"]==0 for r in bills)
    assert not b.errors,b.errors
    print("Merchant-set admission amount, authenticated receipt and staff confirmation verified.")


if __name__ == "__main__":
    run_browser(verify, seed, server_factory=terminal_server)
