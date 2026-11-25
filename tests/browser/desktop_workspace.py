"""Real browser regression for the sidebar, work tabs, form state and runtime readouts."""
import json
from public_visitors import run_browser
from perf_workspace import PASSWORD, checked, session_headers


def advance_revision(b, port):
    b.evaluate("window.testPreviousContent = document.getElementById('content'); void 0")
    owner = session_headers(port, "owner")
    revision = json.loads(checked(port, "/api/version", headers=owner)[1])["revision"]
    checked(port, "/api/commands", headers=owner, payload={
        "revision": revision, "action": "care.addTask",
        "payload": {"residentId": "r001", "title": "导航刷新测试", "assignee": "测试护士"},
    })
    b.evaluate("window.dispatchEvent(new Event('focus'))")
    b.wait_for("document.getElementById('content') !== window.testPreviousContent")


def click_through_refresh(b, port):
    # A real server revision can arrive between pressing a sidebar link and releasing the mouse.
    coords = b.evaluate("""(() => {
      const a=document.querySelector('.sidebar a[href="#leads"]');
      if (a.parentElement.hidden) a.closest('section').querySelector('button').click();
      const r=a.getBoundingClientRect(); return [r.x+r.width/2, r.y+r.height/2]
    })()""")
    x, y = coords
    b.call("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", buttons=1, clickCount=1)
    advance_revision(b, port)
    b.call("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=1)
    b.wait_for("location.hash === '#leads' && document.getElementById('content')?.dataset.route === 'leads'")


def tab_capacity(b, port):
    def visit(route):
        b.click('.sidebar a[href="#' + route + '"]')
        b.wait_for("location.hash === " + json.dumps("#" + route))

    def open_keys():
        return set(b.evaluate("JSON.parse(sessionStorage.getItem('nh-open-views')).keys"))

    visit("overview")
    b.evaluate("while(document.querySelector('.desk-tab-close')) document.querySelector('.desk-tab-close').click()")
    routes = ("settings", "leads", "residents", "beds", "inventory", "medications", "care", "dossier", "longCare")
    for route in routes:
        visit(route)
        if route == "leads":
            b.click(".desk-tab.selected .desk-tab-pin")
    visit("settings")
    visit("overview")
    b.call("Page.reload", ignoreCache=True)
    b.wait_for("document.querySelectorAll('.desk-tab').length===10")
    assert b.evaluate("""(()=>{const held=document.querySelector('.desk-tab.pinned:not(.selected)');
        const ordinary=document.querySelector('.desk-tab:not(.pinned):not(.selected)');
        return held && ordinary && getComputedStyle(held).borderColor!==getComputedStyle(ordinary).borderColor
            && held.querySelector('[role=tab]').getAttribute('aria-label').includes('已固定');})()""")
    before = open_keys()
    visit("activity")
    assert open_keys() == (before - {"#residents"}) | {"#activity"}, open_keys()
    assert b.evaluate("!!document.querySelector('.desk-tab-pin[aria-label=\"取消固定接待管理\"]')")

    visit("settings")
    field = "document.querySelector('form.access-settings [name=institutionName]')"
    b.evaluate("{const i=" + field + "; i.value='保留未保存的草稿'; i.dispatchEvent(new Event('input',{bubbles:true}))}")
    visit("activity")
    advance_revision(b, port)
    for key in sorted(open_keys() - {"#overview", "#leads", "#settings"}):
        visit(key[1:])
        b.click(".desk-tab.selected .desk-tab-pin")
    visit("settings")
    assert b.evaluate(field + ".value") == "保留未保存的草稿"
    before = open_keys()
    b.click('.sidebar a[href="#faq"]')
    assert b.evaluate("location.hash") == "#settings" and open_keys() == before
    assert b.evaluate("document.getElementById('announcer').textContent.includes('页签已满')")
    b.click('.desk-tab-pin[aria-label="取消固定接待管理"]')
    visit("faq")
    assert open_keys() == (before - {"#leads"}) | {"#faq"}
    visit("settings")
    assert b.evaluate(field + ".value") == "保留未保存的草稿"


def verify_register_shortcut(b, selector):
    previous = b.evaluate("location.hash")
    b.evaluate("document.querySelector(" + json.dumps(selector) + ").focus()")
    for event in ("keyDown", "keyUp"):
        b.call("Input.dispatchKeyEvent", type=event, key="Enter", code="Enter", windowsVirtualKeyCode=13,
               text="\r" if event == "keyDown" else "")
    try:
        b.wait_for("!!document.querySelector('dialog[open] input[name=name]')")
    except AssertionError as error:
        raise AssertionError((selector, b.evaluate("document.querySelector('#announcer')?.textContent"))) from error
    assert b.evaluate("location.hash") == previous
    b.click("dialog[open] [aria-label='关闭对话框']")


def verify(browser, port):
    b = browser
    b.call("Emulation.setDeviceMetricsOverride", width=1500, height=855, deviceScaleFactor=1, mobile=False)
    b.call("Emulation.setFocusEmulationEnabled", enabled=True)
    b.call("Page.navigate", url=f"http://127.0.0.1:{port}/?workspace=1")
    b.wait_for("!!document.querySelector('.access-login-form')")
    b.evaluate("""{const form=document.querySelector('.access-login-form');
        form.elements.username.value='owner'; form.elements.password.value=""" + json.dumps(PASSWORD) + """;
        form.requestSubmit()}""")
    b.wait_for("!!document.querySelector('.desk-home')")
    verify_register_shortcut(b, ".desk-new-resident")
    verify_register_shortcut(b, ".desk-home-head button.btn-primary")
    b.click('.desk-assistant-float')
    b.wait_for("!!document.querySelector('#assistant-chat:not([hidden])')")
    assert b.evaluate("getComputedStyle(document.querySelector('.desk-assistant-float')).display === 'none'")
    rect = """(() => {const r=document.querySelector('.assistant-header').getBoundingClientRect();
        return {x:r.left, y:r.top}})()"""
    initial = b.evaluate(rect)
    x, y = initial["x"] + 110, initial["y"] + 22
    target_x = x - 120 if initial["x"] >= 140 else x + 120
    b.call("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", buttons=1, clickCount=1)
    b.call("Input.dispatchMouseEvent", type="mouseMoved", x=target_x, y=y, buttons=1)
    b.call("Input.dispatchMouseEvent", type="mouseReleased", x=target_x, y=y, button="left")
    moved = b.evaluate(rect)
    assert abs(moved["x"] - initial["x"]) > 80, (initial, moved)
    b.call("Page.reload")
    b.wait_for("!!document.querySelector('.desk-home')")
    b.click('.desk-assistant-float')
    b.wait_for("!!document.querySelector('#assistant-chat:not([hidden])')")
    restored = b.evaluate(rect)
    assert abs(moved["x"] - restored["x"]) < 2 and abs(moved["y"] - restored["y"]) < 2, (moved, restored)
    b.click('#assistant-chat [aria-label="收起助理"]')
    b.click('#assistant-launch')
    assert b.evaluate("document.querySelectorAll('#assistant-chat:not([hidden])').length") == 1
    b.click('#assistant-chat [aria-label="收起助理"]')
    tree = b.evaluate("""Object.fromEntries(Array.from(document.querySelectorAll('.desk-nav-section'),g=>
        [g.querySelector('button').title,Array.from(g.querySelectorAll('a'), a=>a.title)]))""")
    assert b.evaluate("""Array.from(document.querySelector('.nav-list').children,
        item=>(item.matches('a')?item:item.querySelector('button')).title)""") == [
        "AI","首页","入住管理","床位管理","照护工单","接待入住","长辈档案","照护服务","仓库管理","费用管理","运营看板","部署控制台","系统管理","系统监控"]
    assert tree["接待入住"] == ["接待管理","退住记录","药品接收登记","请假管理"], tree
    assert b.evaluate("document.querySelector('.nav-list > a[title=照护工单]').hash") == "#care?tab=tasks"
    assert tree["费用管理"] == ["财务总览","待收费","月度账单确认","医疗费用","退住结算","收费记录","民政补贴申报材料","日结报表"], tree
    assert tree["系统监控"] == ["在线用户","定时任务","数据监控","服务监控","缓存监控","缓存列表"], tree
    click_through_refresh(b, port)
    links = b.evaluate("Array.from(document.querySelectorAll('.sidebar .nav-item'),a=>[a.title,a.hash])")
    for label, target in links:
        selector = '.sidebar a[href="' + target + '"]'
        position = b.evaluate("""(() => {
          const a=document.querySelector(""" + json.dumps(selector) + """);
          if (a.parentElement.hidden) a.closest('section').querySelector('button').click();
          a.scrollIntoView({block:'nearest'});
          const rect=a.getBoundingClientRect(), x=rect.x+rect.width/2, y=rect.y+rect.height/2;
          return [x,y,a.contains(document.elementFromPoint(x,y))];
        })()""")
        x, y, can_click = position
        assert can_click, (label, position)
        for event in ("mousePressed", "mouseReleased"):
            b.call("Input.dispatchMouseEvent", type=event, x=x, y=y, button="left", clickCount=1)
        b.wait_for("location.hash === " + json.dumps(target) + " && !!document.querySelector('#content > *')")
        if label in tree["系统监控"]:
            b.wait_for("!!document.querySelector('#content table tbody tr')")
        assert not b.errors, (label, target, b.errors)
        assert b.evaluate("document.documentElement.scrollWidth <= innerWidth"), label
    b.click('.sidebar a[href="#inventory"]')
    b.evaluate("""{const f=document.querySelector('#content .fx-table-tools');
      f.querySelector('input').value='不存在的回归物品';f.requestSubmit()}""")
    b.wait_for("document.querySelector('#content .fx-empty')?.innerText.includes('没有匹配')")
    b.click('.sidebar a[href="#beds"]')
    b.click('.desk-tab-name[title="库存台账"]')
    assert b.evaluate("document.querySelector('#content input[type=search]').value") == '不存在的回归物品'
    b.click('.desk-tab-close[aria-label="关闭库存台账"]')
    b.wait_for("location.hash!=='#inventory'")
    b.click('.sidebar a[href="#settings?tab=onlineUsers"]')
    b.wait_for("document.querySelector('#content tbody')?.innerText.includes('owner')")
    b.call('Page.reload', ignoreCache=True)
    b.wait_for("document.querySelector('#content tbody')?.innerText.includes('owner')")
    assert b.evaluate("document.querySelectorAll('.desk-tab').length") > 5
    b.click('.menu-trigger')
    assert b.evaluate("document.querySelector('#app').classList.contains('desk-compact')")
    verify_register_shortcut(b, ".desk-new-resident")
    b.click('.menu-trigger')
    # A history view can drop its async response after its DOM is detached.
    # Restoring the tab must load the ledger instead of retaining a permanent loading screen.
    b.evaluate("""document.querySelector('.desk-tab-close[aria-label="关闭最近改动"]')?.click()""")
    b.evaluate("""{
      const original=window.fetch;
      window.fetch=async (...args)=>{
        const result=await original(...args);
        if(String(args[0]).startsWith('/api/history?')) {
          window.fetch=original;
          await new Promise(resolve=>window.completeHistoryRead=resolve);
        }
        return result;
      };
    }""")
    b.click('.sidebar a[href="#history"]')
    b.wait_for("typeof window.completeHistoryRead==='function'")
    b.click('.sidebar a[href="#beds"]')
    b.evaluate("window.completeHistoryRead()")
    b.click('.desk-tab-name[title="最近改动"]')
    b.wait_for("!!document.querySelector('#content .history-item, #content .history-list .history-note')")
    tab_capacity(b, port)
    # A fresh browser context that lost its login cannot display cached account or resident tabs.
    b.evaluate("fetch('/api/auth/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(r=>r.status)")
    b.call("Page.reload", ignoreCache=True)
    b.wait_for("!!document.querySelector('.access-login-form')")
    assert not b.evaluate("!!document.querySelector('.desk-tabs, #content table')")
    assert not b.errors, b.errors
    print(f"Verified {len(links)} desktop sidebar destinations, tabs, filters and monitoring")


if __name__ == "__main__":
    run_browser(verify)
