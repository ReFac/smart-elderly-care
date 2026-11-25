"""Verify floating detail and finance windows, including keyboard focus and scrolling."""
from public_visitors import run_browser
from perf_workspace import PASSWORD
import json


def verify(browser, port):
    b = browser
    b.call("Page.navigate", url=f"http://127.0.0.1:{port}/?workspace=1")
    b.wait_for("!!document.querySelector('.access-login-form')")
    b.evaluate("""{const f=document.querySelector('.access-login-form');
        f.elements.username.value='owner';f.elements.password.value="""+json.dumps(PASSWORD)+""";f.requestSubmit();}""")
    b.wait_for("!!document.querySelector('.account-trigger')")
    for width, height in ((1440, 900), (390, 740)):
        b.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)
        b.evaluate("""(async()=>{
          const ui=await import('/lib/ui.js'),{detail}=await import('/lib/dialogs.js');
          const {financeContext}=await import('/features/finance-dialogs.js');
          const opener=document.querySelector('.account-trigger'); opener.focus();
          const box=document.createElement('div');
          const child=ui.button('查看账单',()=>{const rows=document.createElement('div');
              for(let i=0;i<70;i++)rows.append(ui.el('p','','收费项目 '+(i+1)));
              financeContext({ui,detail}).detail('收费明细',rows);
          });
          child.id='floating-bill'; box.append(child);
          detail('档案详情',box,{drawer:true});
        })()""")
        b.evaluate("Promise.all(document.getAnimations().map(a=>a.finished.catch(()=>{})))")
        x, y = b.evaluate("(()=>{const r=document.querySelector('#floating-bill').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()")
        for event in ("mousePressed", "mouseReleased"):
            b.call("Input.dispatchMouseEvent", type=event, x=x, y=y, button="left", clickCount=1)
        b.wait_for("!!document.querySelector('dialog.finance-drawer[open]')")
        b.evaluate("Promise.all(document.getAnimations().map(a=>a.finished.catch(()=>{})))")
        box = b.evaluate("""(()=>{const d=document.querySelector('dialog.finance-drawer[open]'),r=d.getBoundingClientRect();
          const scroller=d.querySelector('.dialog-body');scroller.scrollTop=scroller.scrollHeight;
          const footer=d.querySelector('footer').getBoundingClientRect();
          return [r.left,document.documentElement.clientWidth-r.right,r.top,document.documentElement.clientHeight-r.bottom,
            d.matches(':modal'),d.contains(document.activeElement),scroller.scrollTop,footer.bottom <= r.bottom];
        })()""")
        left, right, top, bottom, native, focused, scrolled, footer_visible = box
        assert min(left,right,top,bottom) >= 10 and abs(left-right) <= 2 and abs(top-bottom) <= 2, box
        assert native and focused and scrolled > 0 and footer_visible, box
        for event in ("keyDown","keyUp"):
            b.call("Input.dispatchKeyEvent", type=event, key="Escape", code="Escape", windowsVirtualKeyCode=27)
        b.wait_for("document.querySelectorAll('dialog[open]').length===1 && document.activeElement.id==='floating-bill'")
        b.click("dialog[open] .dialog-head button")
        b.wait_for("!document.querySelector('dialog[open]') && document.activeElement.matches('.account-trigger')")
    assert not b.errors, b.errors
    print("Desktop and mobile floating dialogs verified with scrollable bills, visible footer and nested keyboard focus.")


if __name__ == "__main__":
    run_browser(verify)
