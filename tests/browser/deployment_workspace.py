"""Owner deployment workflow against an isolated real server and an offline test gateway."""

from contextlib import contextmanager
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
from unittest.mock import patch

from public_visitors import run_browser, until
from perf_workspace import (
    ROOT,
    PASSWORD,
    credential_env,
    checked,
    request,
    session_headers,
)
from platform_core import deployment_console as console
from platform_core.store import Store

GATEWAY_TOKEN = secrets.token_urlsafe(40)


@contextmanager
def running(root, env, initial=False):
    db = root / "facility.sqlite3"
    log = root / ("first.log" if initial else "restart.log")
    with log.open("wb") as output:
        process = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "server.py"),
                "--db",
                str(db),
                "--initial-data",
                "empty",
            ],
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:

            def ready():
                if process.poll() is not None:
                    raise AssertionError("isolated deployment failed to start")
                match = re.search(rb"http://127\.0\.0\.1:(\d+)", log.read_bytes())
                return int(match[1]) if match else None

            yield process.pid, until(ready)
        finally:
            process.send_signal(signal.SIGINT)
            process.wait(timeout=15)


@contextmanager
def fixture(root, seed):
    env = {
        name: os.environ[name]
        for name in ("PATH", "PYTHONPATH", "LD_LIBRARY_PATH", "LANG", "TZ")
        if name in os.environ
    }
    env.update(credential_env(root))
    env.update(NH_DEPLOYMENT_MODE="operator", NH_INSTITUTION_PROFILE="residential")
    db = root / "facility.sqlite3"
    # Bootstrap this isolated test on an available unpinned port.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with patch.dict(os.environ, env, clear=True):
        from types import SimpleNamespace

        store = Store(db, initial_owner_password=PASSWORD, initial_data="empty")
        token, _ = store.login("owner", PASSWORD)
        console.configure(
            store,
            token,
            {
                "action": "save",
                "revision": 0,
                "policy": "next-start",
                "key": "",
                "config": {**console.connection_defaults(), "port": port},
            },
            SimpleNamespace(server_address=("127.0.0.1", port), server_port=port),
        )
        store.logout(token)
    with running(root, env, True) as result:
        yield result
    with running(root, env) as (_, next_port):
        _, body = checked(
            next_port, "/api/deployment", headers=session_headers(next_port, "owner")
        )
        status = json.loads(body)
        assert next_port != port and status["running"]["port"] == next_port
        assert (
            status["draft"] is None
            and status["running"]["provider"] == "openai"
            and status["credentialConfigured"]
        )
        assert status["running"]["model"] == "synthetic-chat"
        print("Restart applied the approved listener and provider configuration.")


def verify(b, port):
    b.call("Page.navigate", url=f"http://127.0.0.1:{port}/?workspace=1")
    b.wait_for("!!document.querySelector('.access-login-form')")
    b.evaluate(
        """{const f=document.querySelector('.access-login-form');f.elements.username.value='owner';
        f.elements.password.value="""
        + json.dumps(PASSWORD)
        + """;f.requestSubmit();}"""
    )
    b.wait_for("!!document.querySelector('.desk-assistant-float')")

    def click(txt):
        button = (
            "[...document.querySelectorAll('button,a')].find(e=>e.getClientRects().length && !e.disabled && e.textContent.trim()==="
            + json.dumps(txt)
            + ")"
        )
        b.wait_for("!!" + button)
        b.evaluate(button + ".click()")

    click("部署控制台")
    click("编辑部署配置")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        new_port = probe.getsockname()[1]
    b.evaluate(
        """{const e=document.querySelector('dialog[open] form').elements;e.provider.value='openai';
      e.provider.dispatchEvent(new Event('change'));e.model.value='synthetic-chat';
      e.key.value="""
        + json.dumps(secrets.token_urlsafe(48))
        + """;e.port.value="""
        + str(new_port)
        + """;e.policy.value='manual';}"""
    )
    click("保存待应用配置")
    b.wait_for("document.querySelector('main').textContent.includes('等待 Owner 批准')")
    click("批准下次启动应用")
    click("批准")
    b.wait_for("document.querySelector('main').textContent.includes('已批准')")
    click("登记设备网关")
    b.evaluate(
        """{const e=document.querySelector('dialog[open] form').elements;e.id.value='gateway-test';
      e.label.value='合成设备';e.secret.value="""
        + json.dumps(GATEWAY_TOKEN)
        + """;}"""
    )
    click("保存网关")
    b.wait_for("document.querySelector('main').textContent.includes('等待首报')")
    path = "/api/deployment/gateways/gateway-test/heartbeat"
    assert request(port, path, payload={})[0] == 403
    _, heartbeat = checked(
        port, path, headers={"Authorization": "Bearer " + GATEWAY_TOKEN}, payload={}
    )
    assert json.loads(heartbeat)["accepted"]
    click("刷新状态")
    b.wait_for("document.querySelector('main').textContent.includes('近期收到心跳')")
    assert not b.errors, b.errors
    print(
        "Owner staged and approved settings in Edge. A correctly authenticated synthetic gateway reported its first heartbeat."
    )


if __name__ == "__main__":
    run_browser(verify, server_factory=fixture)
