"""中文 Owner 在机构设置提议、核对、发布和撤回院区呈现规则。"""

import argparse
import base64
from functools import partial
import json
from pathlib import Path

from public_visitors import run_browser
from perf_workspace import PASSWORD


def verify(b, port, screenshots=None):
    def viewport(width, height, mobile=False):
        b.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=mobile)

    def screenshot(name):
        if screenshots:
            screenshots.mkdir(parents=True, exist_ok=True)
            b.evaluate("Promise.all(document.getAnimations().filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{})))")
            data = b.call("Page.captureScreenshot", format="png")["data"]
            (screenshots / name).write_bytes(base64.b64decode(data))

    viewport(1440, 900)
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
    screenshot("learning-desktop.png")
    click("从审核记录提议")
    b.wait_for("document.querySelector('.learning-error').textContent.includes('还没有可用于学习')")
    viewport(390, 844, True)
    b.evaluate("document.documentElement.dataset.colorMode='dark'")
    assert b.evaluate("document.querySelector('.learning-dialog').scrollWidth <= document.querySelector('.learning-dialog').clientWidth + 1")
    screenshot("learning-mobile-dark.png")
    # Open native disclosure with the keyboard and move an existing item into first place.
    b.evaluate("document.querySelector('.learning-manual summary').focus()")
    b.call("Page.bringToFront")
    b.call("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", text="\r", windowsVirtualKeyCode=13)
    b.call("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter", windowsVirtualKeyCode=13)
    b.wait_for("document.querySelector('.learning-manual').open")
    b.evaluate("""{const a=document.querySelectorAll('.learning-order select');
        a[0].value=a[1].value; a[0].dispatchEvent(new Event('change', {bubbles:true}));}""")
    assert b.evaluate("new Set([...document.querySelectorAll('.learning-order select')].map(x=>x.value)).size === 3")
    click("预览规则与虚构案例")
    b.wait_for("document.activeElement.textContent === '待提交的规则'")
    assert "/api/assistant/learning/propose" not in [p for m, p in b.api if m == "POST"]
    viewport(1440, 900)
    b.evaluate("document.documentElement.dataset.colorMode='light';document.querySelector('.learning-manual').open=false")
    b.evaluate(
        "document.querySelector('dialog textarea').value='先说明出席记录，再放实际进食，缺项标明待核对'"
    )
    click("预览修改效果")
    b.wait_for("document.querySelector('dialog')?.textContent.includes('仅有一项记录')")
    b.wait_for("!!document.querySelector('.learning-preview .learning-receipt code')?.textContent")
    screenshot("learning-preview.png")
    click("确认提交建议")
    b.wait_for("!!document.querySelector('.learning-report')")
    b.evaluate("document.querySelector('.learning-report').open = true")
    b.wait_for("document.querySelector('.learning-report-content')?.textContent.includes('DeerFlow 静态检查报告')")
    assert b.evaluate("document.querySelector('.learning-report-content')?.textContent.includes('publish_candidate')")
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
    print("中文桌面与窄屏已核对规则预览、键盘排序、经验来源、DeerFlow 校验回执、人工发布和恢复。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshots", type=Path)
    options = parser.parse_args()
    run_browser(partial(verify, screenshots=options.screenshots))
