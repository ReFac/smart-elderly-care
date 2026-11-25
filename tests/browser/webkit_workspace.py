"""Smoke-test a real WebKitGTK engine with an ephemeral store at desktop and phone widths."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from urllib.request import urlopen


def webkit(origin, width):
    target = urlsplit(origin)
    if target.scheme != "http" or target.hostname not in ("127.0.0.1", "::1", "localhost"):
        raise ValueError("WebKit 测试只接受本机的中文测试服务")
    with urlopen(origin + "/api/public/deployment", timeout=5) as response:
        deployment = json.load(response)
    if (deployment["language"], deployment["edition"]) != ("zh-CN", "china"):
        raise RuntimeError("WebKit 测试只允许中文机构部署")
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("WebKit2", "4.1")
    from gi.repository import GLib, Gtk, WebKit2

    window = Gtk.OffscreenWindow()
    window.set_default_size(width, 844)
    view = WebKit2.WebView.new_with_context(WebKit2.WebContext.new_ephemeral())
    window.add(view)
    window.show_all()
    loop = GLib.MainLoop()
    result = []
    script = """
        const wait = async selector => {
          const start = performance.now();
          while (!document.querySelector(selector)) {
            if(performance.now()-start>7500) throw Error('Missing ' + selector + ' at ' + location.hash);
            await new Promise(resolve=>setTimeout(resolve,40));
          }
          return document.querySelector(selector);
        };
        const login=await wait('.access-login-form');
        login.elements.username.value='owner'; login.elements.password.value=PASSWORD; login.requestSubmit();
        await wait('.desk-home');
        if (innerWidth > WIDTH+2 || document.documentElement.scrollWidth > innerWidth+1)
          throw Error('Viewport overflow ' + innerWidth + '/' + document.documentElement.scrollWidth);
        const compact=matchMedia('(max-width:760px)').matches;
        if(compact) document.querySelector('.menu-trigger').click();
        document.querySelector('.desk-new-resident').click();
        await wait('dialog[open] input[name=name]');
        document.querySelector('dialog[open] [aria-label="关闭对话框"]').click();
        if(compact) document.querySelector('.menu-trigger').click();
        document.querySelector('.sidebar a[href="#beds"]').click();
        await wait('#content[data-route=beds]');
        const api=await fetch('/api/version');
        if(!api.ok || !Number.isInteger((await api.json()).revision)) throw Error('Session did not survive navigation');
        return innerWidth + 'px ' + location.hash;
    """.replace("PASSWORD", json.dumps(os.environ["NH_TEST_WEBKIT_PASSWORD"])).replace("WIDTH", str(width))

    def completed(widget, pending):
        try:
            result.append(widget.call_async_javascript_function_finish(pending).to_string())
        except GLib.Error as error:
            result.append(error)
        loop.quit()

    def loaded(widget, event):
        if event == WebKit2.LoadEvent.FINISHED:
            view.disconnect(handler)
            view.call_async_javascript_function(script, -1, None, None, None, None, completed)

    handler = view.connect("load-changed", loaded)
    GLib.timeout_add_seconds(25, lambda: loop.quit() or False)
    view.load_uri(origin + "/?workspace=1")
    loop.run()
    window.destroy()
    if not result or isinstance(result[0], Exception):
        raise AssertionError(result or "WebKit timed out")
    print(f"WebKitGTK {WebKit2.get_major_version()}.{WebKit2.get_minor_version()}.{WebKit2.get_micro_version()} {result[0]} passed")


if __name__ == "__main__":
    os.environ["NH_DEPLOYMENT_LANGUAGE"] = "zh-CN"
    if len(sys.argv) == 3:
        webkit(sys.argv[1], int(sys.argv[2]))
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from perf_workspace import PASSWORD, server
        with TemporaryDirectory() as temp, server(Path(temp), lambda store: None) as (_, port):
            for width in (1440, 390):
                env = {**os.environ, "NH_TEST_WEBKIT_PASSWORD": PASSWORD}
                # The system Python has the distro's matching GTK bindings. Business code uses the project interpreter.
                subprocess.run([os.getenv("WEBKIT_PYTHON", "/usr/bin/python3"), __file__,
                                f"http://127.0.0.1:{port}", str(width)], env=env, check=True, timeout=40)
