"""Exercise consent, signed-receipt eligibility and posting through the live finance workspace."""
from contextlib import contextmanager
from functools import partial
from http.server import ThreadingHTTPServer
import json
from threading import Thread
from unittest.mock import patch

from public_visitors import run_browser
from perf_workspace import PASSWORD
from platform_core.operations import channels, checkout
from platform_core.store import Store
from server import Handler


@contextmanager
def merchant_server(root, _):
    store = Store(root / "finance.db", initial_owner_password=PASSWORD)
    token, _ = store.login("owner", PASSWORD)
    state = store.snapshot(token)["data"]
    bill = next(b for b in state["bills"] if b["balance"] > 20)
    def command(name, payload):
        store.execute(name,payload,store.version(token)["revision"],token)
    command("ops.paymentOrder",dict(billId=bill["id"],amount=12.34,channel="支付宝"))
    order = store.snapshot(token)["data"]["paymentOrders"][0]["id"]
    tx = "SIGNED-BROWSER-001"
    channels.record_verified(store,"alipay",dict(billId=bill["id"],channel="支付宝",transactionId=tx,
        merchantOrder=order,amount=12.34,paidDate=store.now().date().isoformat(),source="测试签名到账"),
        store.now(),"渠道签名通知")
    def merchant(method,biz,now):
        doc = dict(code="10000",trade_no=tx,out_trade_no=order)
        if method == "alipay.trade.refund":
            assert biz["trade_no"] == tx and biz["refund_amount"] == "4.25"
            return dict(doc,fund_change="N")
        assert method == "alipay.trade.fastpay.refund.query"
        return dict(doc,out_request_no=biz["out_request_no"],refund_amount="4.25",refund_status="REFUND_SUCCESS")
    class QuietHandler(Handler):
        def log_request(self,*args):
            pass
    with patch.object(checkout,"enabled_channels",return_value=["支付宝"]), patch.object(checkout,"alipay_api",merchant), \
            patch.object(checkout,"send",side_effect=AssertionError("外部商户请求超出浏览器测试范围")):
        server=ThreadingHTTPServer(("127.0.0.1",0),partial(QuietHandler,store=store))
        thread=Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            yield None,server.server_port
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


def check(b,port):
    def button(where,text):
        return f"Array.from(({where}).querySelectorAll('button')).find(x=>x.textContent.trim()==={json.dumps(text)})"
    def click(where,text):
        s=button(where,text)
        b.wait_for(f"!!({s}) && !({s}).disabled")
        b.evaluate(f"({s}).click()")
    b.call("Page.navigate",url=f"http://127.0.0.1:{port}/?workspace=1")
    b.wait_for("!!document.querySelector('.access-login-form')")
    b.evaluate("""{const f=document.querySelector('.access-login-form');f.elements.username.value='owner';
       f.elements.password.value="""+json.dumps(PASSWORD)+""";f.requestSubmit()}""")
    b.wait_for("!!document.querySelector('.desk-home')")
    b.evaluate("document.querySelector('.sidebar a[title=\"收费记录\"]').click()")
    table="document.querySelector('#content')"
    paid=f"[...{table}.querySelectorAll('tr')].find(r=>r.textContent.includes('12.34'))"
    b.wait_for(f"!!({paid})")
    click(paid,"申请退款")
    b.wait_for("!!document.querySelector('dialog[open] [name=reason]')")
    b.evaluate("""{const f=document.querySelector('dialog[open] form');f.elements.amount.value='4.25';
       f.elements.mode.value='channel';f.elements.reason.value='申请渠道原路核对';f.requestSubmit()}""")
    review="document.querySelector('.change-review-dialog[open]')"
    b.wait_for(f"!!{review}")
    click(review,"确认执行")
    row=f"[...{table}.querySelectorAll('tr')].find(r=>r.textContent.includes('申请渠道原路核对'))"
    b.wait_for(f"({row})?.textContent.includes('待核实')")
    click(row,"提交或查询原路退款")
    dlg="document.querySelector('dialog[aria-label=\"原路退款\"][open]')"
    b.wait_for(f"!!{dlg}")
    click(dlg,"提交原路退款")
    b.wait_for(f"!!{review}")
    endpoint = ("POST","/api/payments/refunds/channel")
    assert endpoint not in b.api
    click(review,"返回")
    click(dlg,"提交原路退款")
    click(review,"确认原路退款")
    b.wait_for(f"({dlg})?.textContent.includes('查询退款结果')")
    b.wait_for(f"({row})?.textContent.includes('渠道处理中')")
    assert b.api.count(endpoint)==1
    click(dlg,"查询退款结果")
    b.wait_for(f"({row})?.textContent.includes('已退款')")
    assert b.api.count(endpoint)==2 and not b.errors,(b.api,b.errors)
    print("浏览器通过：经办人确认、原单支付渠道提交、逐笔查询及退款入账")


if __name__ == "__main__":
    run_browser(check,server_factory=merchant_server)
