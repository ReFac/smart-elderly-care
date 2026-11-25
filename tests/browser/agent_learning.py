"""中文 Owner 在机构设置提议、核对、发布和撤回院区呈现规则。"""

import json

from public_visitors import run_browser
from perf_workspace import PASSWORD


def verify(b, port):
    b.call("Page.navigate", url=f"http://127.0.0.1:{port}/?workspace=1")
    b.wait_for("!!document.querySelector('.access-login-form')")
    b.evaluate(
        "{const f=document.querySelector('.access-login-form'); f.elements.username.value='owner';"
        "f.elements.password.value=" + json.dumps(PASSWORD) + "; f.requestSubmit();}"
    )
    b.wait_for("!!document.querySelector('.desk-assistant-float')")
    b.evaluate("location.hash='#settings'")

    def click(label):
        target = (
            "[...document.querySelectorAll('button,a')].find(e => e.getClientRects().length && "
            "!e.disabled && e.textContent.trim()===" + json.dumps(label) + ")"
        )
        b.wait_for("!!" + target)
        b.evaluate(target + ".click()")

    click("AI 套餐与识别服务")
    click("管理助理写作规则")
    b.wait_for("!!document.querySelector('dialog textarea')")
    b.evaluate(
        "document.querySelector('dialog textarea').value='先说明出席记录，再放实际进食，缺项标明待核对'"
    )
    click("从纠错提取规则")
    b.wait_for("document.querySelector('dialog')?.textContent.includes('仅有一项记录')")
    click("确认提交建议")
    click("批准发布")
    click("确认执行")
    b.wait_for(
        "document.querySelector('dialog')?.textContent.includes('当前规则 · v1')"
    )
    click("恢复此版")
    click("确认执行")
    b.wait_for(
        "document.querySelector('dialog')?.textContent.includes('当前规则 · v2')"
    )
    assert "/api/assistant/learning/propose" in [
        p for method, p in b.api if method == "POST"
    ]
    assert not b.errors, b.errors
    print("中文桌面已核对纠错提取、虚构案例、人工批准、版本历史和恢复。")


if __name__ == "__main__":
    run_browser(verify)
