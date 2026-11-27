"""中文机构助理上传就诊图片，后台整理时继续对话，经办人逐项核对后入档。"""

from contextlib import closing, contextmanager
from functools import partial
import json
import os
from threading import Event, Thread
from unittest.mock import patch

from public_visitors import run_browser
from perf_workspace import PASSWORD, credential_env, request, session_headers
from test_medical_visits import png, RID
from platform_core import provider, visit_jobs
from platform_core.http_capacity import CapacityServer
from platform_core.provider import media
from platform_core.store import Store
from server import Handler


class FixtureHandler(Handler):
    def log_message(self, *args):
        pass


class VisitWorkflow:
    def __init__(self):
        self.extracting = Event()
        self.release = Event()

    def model(self, key, body, **kwargs):
        # The provider is simulated. Conversation and evidence workers run the real DeerFlow SDK.
        assert key == "synthetic-visit-browser"
        guide = body["messages"][0]["content"]
        if "文件分拣员" in guide:
            content = '{"category":"就诊记录"}'
        elif "原文行号" in guide:
            self.extracting.set()
            assert self.release.wait(60), "浏览器未完成后台整理期间的对话"
            content = '{"eventDate":[1],"orders":[2]}'
        elif "first" in guide:
            content = '{"first":1}'
        elif "办理说明" in guide:
            content = "请上传本次就诊资料，核对原件后保存。"
        else:
            raise AssertionError("收到意料外的模型请求")
        return {
            "usage": {"prompt_tokens": 24, "completion_tokens": 8, "total_tokens": 32},
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
        }

    def stream(self, key, body, received, **kwargs):
        reply = self.model(key, body, **kwargs)
        received(reply["choices"][0]["message"]["content"])
        return reply

    @contextmanager
    def serve(self, directory, seed):
        env = {
            k: os.environ[k]
            for k in (
                "PATH",
                "HOME",
                "LANG",
                "LD_LIBRARY_PATH",
                "TZ",
                "NH_DEERFLOW_PYTHON",
            )
            if k in os.environ
        }
        env.update(
            credential_env(directory),
            DEEPSEEK_API_KEY="synthetic-visit-browser",
            NH_DEERFLOW_BACKEND="deerflow",
        )
        with patch.dict(os.environ, env, clear=True):
            self.store = Store(
                directory / "workspace.sqlite3", initial_owner_password=PASSWORD
            )
            with closing(self.store.connect()) as db, db:
                provider.grant(
                    db, "虚构测试套餐", 180000, "2099-12-01", self.store.now()
                )
                media.grant(db, provider.latest(db)["id"], "ocr", 100)
                state = json.loads(
                    db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
                )
                self.resident = next(
                    person["name"]
                    for person in state["residents"]
                    if person["id"] == RID
                )
            owner = self.store.login("owner", PASSWORD)[0]
            self.store.execute(
                "access.create",
                {
                    "kind": "staff",
                    "role": "自定义",
                    "displayName": "虚构核对同事",
                    "username": "other-reviewer",
                    "password": PASSWORD,
                    "permissions": ["medical", "medical.write", "clinical"],
                },
                self.store.version(owner)["revision"],
                owner,
            )
            self.store.logout(owner)
            self.original = directory / "虚构就诊原件.png"
            self.original.write_bytes(png((123, 145, 224)))
            ocr_result = {
                "id": "synthetic-ocr",
                "purpose": "text_recognition",
                "object": "ocr.result",
                "page_count": 1,
                "pages": [
                    {
                        "index": 0,
                        "text": "就诊日期：2026年11月20日\n医嘱：按记录复诊",
                        "finish_reason": "stop",
                    }
                ],
            }
            stopped = Event()
            with (
                patch.object(media, "invoke", return_value=ocr_result) as self.ocr,
                patch("platform_core.provider.deepseek.send", self.model),
                patch("platform_core.provider.deepseek.stream", self.stream),
                CapacityServer(
                    ("127.0.0.1", 0),
                    partial(FixtureHandler, store=self.store),
                    workers=8,
                    heavy_workers=4,
                ) as http,
            ):
                http.deployment_origin = None
                http.deployment_port_pinned = False
                listener = Thread(target=http.serve_forever, daemon=True)
                worker = Thread(
                    target=visit_jobs.dispatch, args=(self.store, stopped), daemon=True
                )
                listener.start()
                worker.start()
                try:
                    yield os.getpid(), http.server_port
                finally:
                    self.release.set()
                    stopped.set()
                    self.store.visit_job_wakeup.set()
                    http.shutdown()
                    listener.join()
                    worker.join(timeout=30)

    def verify(self, b, port):
        def click(label):
            target = (
                "[...document.querySelectorAll('button')].find(e => e.getClientRects().length && "
                "!e.disabled && (e.textContent.trim()==="
                + json.dumps(label)
                + " || e.getAttribute('aria-label')==="
                + json.dumps(label)
                + "))"
            )
            try:
                b.wait_for("!!" + target)
            except AssertionError as exc:
                visible = b.evaluate(
                    "(document.querySelector('dialog[open]') || document.getElementById('assistant-chat'))?.innerText"
                )
                raise AssertionError(
                    f"缺少按钮 {label}，当前内容 {visible}，最近请求 {b.api[-8:]}"
                ) from exc
            b.evaluate(target + ".click()")

        def type_in(selector, value):
            b.wait_for("!!document.querySelector(" + json.dumps(selector) + ")")
            b.evaluate(
                "{const field=document.querySelector("
                + json.dumps(selector)
                + ");field.value="
                + json.dumps(value)
                + ";field.dispatchEvent(new Event('input',{bubbles:true}));}"
            )

        def ask(text):
            selector = "#assistant-chat .assistant-input:not(:disabled)"
            type_in(selector, text)
            b.evaluate(
                "document.querySelector('#assistant-chat .assistant-input').form.requestSubmit()"
            )

        def get(path):
            return b.evaluate("fetch(" + json.dumps(path) + ").then(r=>r.json())")

        def records(draft_id):
            with closing(self.store.connect()) as db:
                return db.execute(
                    "SELECT metadata FROM dossier_visit_records WHERE id=? AND resident_id=?",
                    (draft_id, RID),
                ).fetchall()

        b.call("Page.navigate", url=f"http://127.0.0.1:{port}/?workspace=1")
        b.wait_for("!!document.querySelector('.access-login-form')")
        b.evaluate(
            "{const f=document.querySelector('.access-login-form'); f.elements.username.value='owner';"
            "f.elements.password.value=" + json.dumps(PASSWORD) + ";f.requestSubmit();}"
        )
        b.wait_for("!!document.querySelector('.desk-assistant-float')")
        b.click(".desk-assistant-float")
        for width, scale in [(1366, 1), (1366, 1.5), (320, 1.5)]:
            b.call("Emulation.setDeviceMetricsOverride", width=width, height=800, deviceScaleFactor=1, mobile=width==320)
            b.evaluate(f"document.documentElement.style.setProperty('--desk-type-scale','{scale}')")
            assert b.evaluate("""(() => {
                const button = document.querySelector('.assistant-task-control');
                const range = document.createRange();
                range.selectNodeContents(button.lastChild);
                const box = button.getBoundingClientRect(), text = range.getBoundingClientRect();
                const header = button.closest('header').getBoundingClientRect();
                const titleRange = document.createRange();
                titleRange.selectNodeContents(button.closest('header').querySelector('h2'));
                const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
                return titleRange.getClientRects().length === 1 && range.getClientRects().length === 1 && text.right <= box.right &&
                    text.bottom <= box.bottom && box.left >= 0 && box.right <= innerWidth &&
                    box.bottom <= header.bottom && button.contains(hit);
            })()"""), f"整理任务按钮在宽 {width}、字号倍率 {scale} 时换行、被裁切或无法点击"
        b.call("Emulation.setDeviceMetricsOverride", width=1366, height=800, deviceScaleFactor=1, mobile=False)
        b.evaluate("document.documentElement.style.setProperty('--desk-type-scale','1')")
        click("整理任务")
        b.wait_for("document.querySelector('dialog[open]')?.textContent.includes('由 DeerFlow 整理就诊草稿')")
        b.wait_for("document.querySelector('dialog[open]')?.textContent.includes('当前没有等待核对的就诊资料')")
        b.click("dialog[open] button[aria-label='关闭对话框']")
        ask("帮我整理本次就诊资料")
        b.call("Page.setInterceptFileChooserDialog", enabled=True)
        click("上传就诊资料")
        origin = get("/api/assistant/chat")["messages"][-1]
        assert (
            origin["runtime"] == "deerflow"
            and origin["action"]["kind"] == "uploadVisitRecords"
        )
        doc = b.call("DOM.getDocument")["root"]["nodeId"]
        picker = b.call(
            "DOM.querySelector", nodeId=doc, selector="#assistant-chat input[type=file]"
        )["nodeId"]
        b.call("DOM.setFileInputFiles", files=[str(self.original)], nodeId=picker)
        click("识别并分类")
        b.wait_for("document.querySelector('.assistant-document-card')?.innerText.includes('细小文字可能漏读')")
        click("确认分类")
        b.wait_for("document.querySelector('.assistant-document-card')?.innerText.includes('手动核对并归档')")
        click("整理所选就诊资料")
        type_in("dialog[open] input[role=combobox]", self.resident)
        b.click("dialog[open] [role=option]")
        click("继续")
        click("继续")
        type_in("dialog[open] input[name=eventDate]", "2026-11-20")
        click("继续")
        b.click("dialog[open] input[type=checkbox]")
        click("开始识别并核对")
        b.wait_for(
            "document.querySelector('dialog[open]')?.textContent.includes('我的就诊资料整理任务')"
        )
        endpoint = "/api/assistant/visit-jobs"
        job = get(endpoint)["items"][0]
        task, draft = job["taskId"], job["draftId"]
        assert job["residentId"] == RID and task == origin["taskId"]
        assert self.extracting.wait(30), get(endpoint)
        assert get(f"{endpoint}/{draft}")["state"] == "running" and not records(draft)
        b.click("dialog[open] button[aria-label='关闭对话框']")
        if b.evaluate("document.querySelector('#assistant-chat')?.hidden"):
            b.click(".desk-assistant-float")
        if b.evaluate(
            "document.querySelector('#assistant-chat')?.classList.contains('assistant-compact')"
        ):
            click("展开对话")
        ask("今天院里怎么样？")
        b.wait_for(
            "fetch('/api/assistant/chat').then(r=>r.json()).then(x=>x.messages.length===4)"
        )
        reply = get("/api/assistant/chat")["messages"][-1]
        assert reply["runtime"] == "deerflow" and reply["taskId"] != task and reply["content"]
        b.wait_for("document.querySelector('.from-assistant .assistant-task-receipt')?.textContent.includes('DeerFlow')")
        assert get(f"{endpoint}/{draft}")["state"] == "running" and not records(draft)
        self.release.set()
        click("整理任务")
        b.wait_for("document.querySelector('dialog[open] [data-visit-jobs] .assistant-task-receipt')?.textContent.includes('DeerFlow')")
        b.click('dialog[open] [data-visit-jobs] .assistant-task-receipt summary')
        b.wait_for("document.querySelector('dialog[open] [data-visit-jobs] .assistant-task-receipt[open]')?.innerText.includes(" + json.dumps(task) + ")")
        b.evaluate("""{const body = document.querySelector('[data-visit-jobs]');
            window.previousVisitReceipt = body.querySelector('details');
            [...body.querySelectorAll('button')].find(button => button.textContent === '刷新').click();}""")
        b.wait_for("!window.previousVisitReceipt.isConnected && !!document.querySelector('[data-visit-jobs] details[open]')")
        click("核对草稿")
        b.wait_for(
            "document.querySelector('.medical-visit-review-content img')?.naturalWidth === 1"
        )
        assert "按记录复诊" in b.evaluate(
            "document.querySelector('textarea[name=orders]').value"
        )
        asset = b.evaluate(
            "document.querySelector('.medical-visit-review-content img').getAttribute('src')"
        )
        assert asset.startswith(f"{endpoint}/{draft}/originals/")
        assert request(port, asset)[0] == 401
        colleague = session_headers(port, "other-reviewer")
        status, _, listing = request(port, endpoint, headers=colleague)
        assert status == 200 and json.loads(listing)["items"] == []
        assert request(port, f"{endpoint}/{draft}", headers=colleague)[0] == 404
        assert request(port, asset, headers=colleague)[0] == 404
        click("确认添加此病例")
        assert not records(draft) and not b.evaluate(
            "document.querySelector('.medical-visit-form').checkValidity()"
        )
        b.click(".medical-visit-form input[type=checkbox]")
        click("确认添加此病例")
        b.wait_for("!document.querySelector('.medical-visit-form')")
        assert len(records(draft)) == 1 and not get(endpoint)["items"]
        assert self.ocr.call_count == 1, "上传分拣和后台整理应复用相同 OCR 原文"
        with closing(self.store.connect()) as db:
            runtimes = {
                row[0]
                for row in db.execute(
                    "SELECT runtime FROM agent_task_usage WHERE taskId=?", (task,)
                )
            }
        assert runtimes == {"deerflow", "platform"}, runtimes
        click("整理任务")
        click("查看组件部署状态")
        b.wait_for("document.querySelector('main')?.textContent.includes('DeerFlow · 对话与资料整理')")
        click("查看我的整理任务")
        b.wait_for("document.querySelector('dialog[open]')?.textContent.includes('由 DeerFlow 整理就诊草稿')")
        b.click("dialog[open] button[aria-label='关闭对话框']")
        assert not b.errors, b.errors
        print(
            "中文 Chromium 已验证普通及大字号、窄屏整理入口、DeerFlow 对话与后台整理回执、OCR 复用、授权预览和员工确认入档。"
        )


if __name__ == "__main__":
    workflow = VisitWorkflow()
    run_browser(workflow.verify, server_factory=workflow.serve)
