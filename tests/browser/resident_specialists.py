"""Chinese workspace: independently schedule the resident agents and read only permitted drafts."""

from contextlib import closing
import json

from public_visitors import run_browser
from perf_workspace import PASSWORD
from platform_core.rounds import report
from platform_core.rounds.records import current_stay, workspace


def seed(store):
    token, _ = store.login("owner", PASSWORD)
    store.execute("access.create", {
        "kind": "staff", "role": "自定义", "username": "rounds-care",
        "displayName": "照护测试员", "password": PASSWORD, "permissions": ["residents", "care"],
    }, store.version(token)["revision"], token)
    with closing(store.connect()) as db, db:
        _, state = workspace(db)
        resident = current_stay(state, next(p for p in state["residents"] if p["id"] == "r001"))
        now = store.now()
        day, stamp = now.date().isoformat(), now.isoformat()
        # Use an attributable fixture so the browser verifies a concrete result without a paid model.
        life = report.build(db, state, resident, now)
        life.update(id="fixture-life", generatedAt=stamp, source="deepseek", model="测试模型",
                    taskId="daily-0123456789abcdef01234567", draftRuntime="deerflow",
                    changes=[dict(day=day, permission="care", text="已签认午餐，吃了米饭。",
                                  evidence=[dict(kind="task", id="lunch-test", date=day)])],
                    suggestions=[], residentEdition=[])
        db.execute("INSERT INTO rounds_reports VALUES(?,?,?,?,?,?,?)",
                   (life["id"], "r001", resident["bedId"], day, stamp, "fixture", json.dumps(life)))
        health = dict(id="fixture-health", residentId="r001", agentId="health-review", status="draft",
                      day=day, generatedAt=stamp, source="deepseek", model="测试模型",
                      taskId="health-0123456789abcdef01234567", draftRuntime="deerflow",
                      items=[dict(text="护士已复核这位长辈的晨间观察。",
                                  evidence=[dict(kind="healthRecord", id="observation-test", date=day)])])
        db.execute("INSERT INTO rounds_health_reviews VALUES(?,?,?,?,?,?,?,?)",
                   (health["id"], "r001", resident["bedId"], resident["_stayId"], day, "fixture", stamp,
                    json.dumps(health)))


def sign_in(browser, origin, username):
    browser.call("Page.navigate", url=origin + "/?workspace=1")
    browser.wait_for("!!document.querySelector('.access-login-form')")
    browser.evaluate("""{const f=document.querySelector('.access-login-form');
        f.elements.username.value=""" + json.dumps(username) + "; f.elements.password.value=" +
        json.dumps(PASSWORD) + "; f.requestSubmit()}")
    browser.wait_for("!!document.querySelector('.sidebar a.nav-item')")


def profile(browser, origin, resident):
    browser.call("Page.navigate", url=origin + "/?workspace=1#dossier?work=resident-" + resident)
    browser.wait_for("!!document.querySelector('[data-dossier-tab=timeline]')")
    browser.click("[data-dossier-tab=timeline]")
    browser.wait_for("!!document.querySelector('[data-resident-agent=daily-life]')")


def check_owner(browser, port):
    b, origin = browser, f"http://127.0.0.1:{port}"
    sign_in(b, origin, "owner")
    b.click('.sidebar a[href="#settings?tab=timers"]')
    b.wait_for("Array.from(document.querySelectorAll('#content button')).some(b=>b.textContent==='长辈档案自动整理')")
    b.evaluate("Array.from(document.querySelectorAll('#content button')).find(b=>b.textContent==='长辈档案自动整理').click()")
    b.wait_for("document.querySelectorAll('[data-agent-schedule]').length === 2")
    life = b.evaluate("document.querySelector('[data-agent-schedule=daily-life] dl').textContent")
    b.click('[data-agent-schedule=health-review] button')
    b.wait_for("!!document.querySelector('dialog[open] [name=intervalMinutes]')")
    b.evaluate("""{const f=document.querySelector('dialog[open] form');
        f.elements.mode.value='off';f.elements.intervalMinutes.value='95';f.requestSubmit()}""")
    b.wait_for("document.querySelector('.change-review-dialog')?.textContent.includes('95 分钟')")
    b.click(".change-review-dialog .change-actions .btn-primary")
    b.wait_for("document.querySelector('[data-agent-schedule=health-review]').textContent.includes('每 95 分钟')")
    assert b.evaluate("document.querySelector('[data-agent-schedule=daily-life] dl').textContent") == life
    b.call("Page.reload")
    b.wait_for("document.querySelector('[data-agent-schedule=health-review]')?.textContent.includes('每 95 分钟')")
    profile(b, origin, "r001")
    assert b.evaluate("document.querySelector('[data-resident-agent=daily-life]').textContent.includes('吃了米饭')")
    b.click("[data-resident-agent=health-review] details summary")
    b.wait_for("document.querySelector('[data-resident-agent=health-review] details[open]').innerText.includes('observation-test')")
    for agent, prefix in [('daily-life', 'daily'), ('health-review', 'health')]:
        selector = f'[data-resident-agent={agent}] .assistant-task-receipt'
        b.click(selector + ' summary')
        receipt = b.evaluate(f"document.querySelector('{selector}').innerText")
        assert 'DeerFlow' in receipt and prefix + '-0123456789abcdef01234567' in receipt
    profile(b, origin, "r002")
    assert 'observation-test' not in b.evaluate("document.querySelector('#content').textContent")
    assert not b.errors, b.errors


def check_care(browser, port):
    b, origin = browser, f"http://127.0.0.1:{port}"
    sign_in(b, origin, "rounds-care")
    profile(b, origin, "r001")
    assert b.evaluate("document.querySelector('[data-resident-agent=daily-life]').textContent.includes('吃了米饭')")
    assert not b.evaluate("!!document.querySelector('[data-resident-agent=health-review]')")
    assert 'health-0123456789abcdef01234567' not in b.evaluate("document.querySelector('#content').textContent")
    assert not b.evaluate("!!document.querySelector('.sidebar a[href=\"#settings\"]')")
    assert not b.errors, b.errors


if __name__ == "__main__":
    for check in (check_owner, check_care):
        run_browser(check, seed)
    print("中文浏览器通过：两项计划独立、修改经确认后持久保存、档案依据可展开、跨人及岗位隔离。")
