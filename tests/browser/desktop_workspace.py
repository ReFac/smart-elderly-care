"""Real browser regression for the sidebar, work tabs, form state and runtime readouts."""
import json
from public_visitors import run_browser
from perf_workspace import PASSWORD


def verify(browser, port):
    b = browser
    b.call("Emulation.setDeviceMetricsOverride", width=1500, height=855, deviceScaleFactor=1, mobile=False)
    b.call("Page.navigate", url=f"http://127.0.0.1:{port}/?workspace=1")
    b.wait_for("!!document.querySelector('.access-login-form')")
    b.evaluate("""{const form=document.querySelector('.access-login-form');
        form.elements.username.value='owner'; form.elements.password.value=""" + json.dumps(PASSWORD) + """;
        form.requestSubmit()}""")
    b.wait_for("!!document.querySelector('.desk-home')")
    b.click('.desk-assistant-float')
    b.wait_for("!!document.querySelector('#assistant-chat:not([hidden])')")
    assert b.evaluate("getComputedStyle(document.querySelector('.desk-assistant-float')).display === 'none'")
    b.click('#assistant-chat [aria-label="收起助理"]')
    b.click('#assistant-launch')
    assert b.evaluate("document.querySelectorAll('#assistant-chat:not([hidden])').length") == 1
    b.click('#assistant-chat [aria-label="收起助理"]')
    tree = b.evaluate("""Object.fromEntries(Array.from(document.querySelectorAll('.desk-nav-section'),g=>
        [g.querySelector('button').title,Array.from(g.querySelectorAll('a'), a=>a.title)]))""")
    assert b.evaluate("""Array.from(document.querySelector('.nav-list').children,
        item=>(item.matches('a')?item:item.querySelector('button')).title)""") == [
        "首页","接待入住","老人档案","照护服务","仓库管理","费用管理","运营看板","系统管理","系统监控"]
    assert tree["接待入住"] == ["接待管理","入住管理","退住记录","药品接收登记","请假管理","床位全景"], tree
    assert tree["费用管理"] == ["财务总览","待收费","月度账单确认","医疗费用","退住结算","收费记录","民政补贴申报材料","日结报表"], tree
    assert tree["系统监控"] == ["在线用户","定时任务","数据监控","服务监控","缓存监控","缓存列表"], tree
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
    b.click('.menu-trigger')
    b.click('.global-tools button[aria-label="放大字号"]')
    assert b.evaluate("document.documentElement.classList.contains('desk-large-text')")
    # A history view can drop its async response after its DOM is detached.
    # Restoring the tab must load the ledger instead of retaining a permanent loading screen.
    b.click('.desk-tab-close[aria-label="关闭最近改动"]')
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
    # A fresh browser context that lost its login cannot display cached account or resident tabs.
    b.evaluate("fetch('/api/auth/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(r=>r.status)")
    b.call("Page.reload", ignoreCache=True)
    b.wait_for("!!document.querySelector('.access-login-form')")
    assert not b.evaluate("!!document.querySelector('.desk-tabs, #content table')")
    assert not b.errors, b.errors
    print(f"Verified {len(links)} desktop sidebar destinations, tabs, filters and monitoring")


if __name__ == "__main__":
    run_browser(verify)
