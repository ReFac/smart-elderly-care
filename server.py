"""Serve the shared staff/family workspace and authenticated API on loopback."""

import argparse
from functools import partial
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs, unquote, urlsplit

from platform_core import access
from platform_core.store import Conflict, SignedOut, Store, encode

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
SMALL_BODY = 64 * 1024
DOCUMENT_BODY = 12 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, store, public_origin=None, **kwargs):
        self.store = store
        self.public_origin = public_origin
        super().__init__(*args, **kwargs)

    def log_request(self, code="-", size="-"):
        # Do not include staff names or room filters from the query string in access logs.
        self.log_message("%s %s %s", self.command, self.path.partition("?")[0], code)

    def respond(self, status, content, mime, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, status, body, cookie=None):
        self.respond(
            status, encode(body).encode(), "application/json; charset=utf-8", cookie
        )

    def token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        value = cookie.get("nh_session")
        return value.value if value else None

    def session_cookie(self, token):
        secure = "; Secure" if self.public_origin else ""
        age = access.SESSION_LIFETIME if token else 0
        return f"nh_session={token or ''}; Path=/; HttpOnly; SameSite=Strict; Max-Age={age}{secure}"

    def read_json(self, limit):
        if self.headers.get_content_type() != "application/json":
            raise InvalidMedia("仅接收 JSON 表单")
        size = int(self.headers.get("Content-Length", "0"))
        if size <= 0 or size > limit:
            raise ValueError("请求为空或超过体积限制")
        body = json.loads(self.rfile.read(size), parse_constant=self.invalid_constant)
        if not isinstance(body, dict):
            raise ValueError("请求必须为 JSON 对象")
        return body

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        try:
            host = self.headers.get("Host", "")
            parsed = urlsplit("//" + host)
            local = parsed.hostname in ("127.0.0.1", "localhost", "::1")
            configured = (
                self.public_origin and host == urlsplit(self.public_origin).netloc
            )
            if not (local or configured) or parsed.username or parsed.password:
                raise PermissionError("请使用配置的机构域名或本机地址")
            path = unquote(urlsplit(self.path).path)
            if method == "GET":
                self.read_resource(path)
            else:
                origin = self.headers.get("Origin")
                if origin and origin not in {
                    self.public_origin,
                    "http://" + host if local else self.public_origin,
                }:
                    raise PermissionError("请从机构工作台提交")
                self.write_resource(path)
        except SignedOut as e:
            self.send_json(401, {"error": str(e)})
        except access.LoginThrottled as e:
            self.send_json(429, {"error": str(e)})
        except PermissionError as e:
            self.send_json(403, {"error": str(e)})
        except FileNotFoundError as e:
            self.send_json(404, {"error": str(e)})
        except Conflict as e:
            self.send_json(409, {"error": str(e)})
        except InvalidMedia as e:
            self.send_json(415, {"error": str(e)})
        except (ValueError, TypeError, OverflowError, RecursionError) as e:
            self.send_json(400, {"error": str(e)})
        except sqlite3.OperationalError:
            self.send_json(503, {"error": "数据库暂时不可用，请稍后重试"})
        except (ConnectionResetError, BrokenPipeError):
            pass

    def read_resource(self, path):
        token = self.token()
        if path == "/api/branding":
            return self.send_json(200, self.store.branding())
        if path == "/api/health":
            return self.send_json(200, {"status": "ok"})
        if path == "/api/version":
            return self.send_json(200, self.store.version(token))
        if path == "/api/state":
            return self.send_json(200, self.store.snapshot(token))
        if path == "/api/activity":
            query = parse_qs(urlsplit(self.path).query, max_num_fields=5)
            filters = {k: query[k][0] for k in ("room", "actor") if k in query}
            filters.update(
                {k: int(query[k][0]) for k in ("before", "limit") if k in query}
            )
            return self.send_json(200, self.store.activity(token, **filters))
        if path in ("/api/agent/capabilities", "/api/agent/runs"):
            return self.send_json(
                200, self.store.agent_resource(token, path.rsplit("/", 1)[1])
            )
        match = re.fullmatch(r"/api/agent/runs/(run-[a-f0-9]{32})", path)
        if match:
            return self.send_json(
                200, self.store.agent_resource(token, "runs", match[1])
            )
        if path == "/api/integrations":
            return self.send_json(200, {"capabilities": self.store.capabilities(token)})
        match = re.fullmatch(r"/api/integrations/([a-zA-Z0-9._-]+)", path)
        if match:
            return self.send_json(200, self.store.capabilities(token, match[1]))
        match = re.fullmatch(r"/api/documents/([a-zA-Z0-9_-]+)/image", path)
        if match:
            image, mime = self.store.photo(token, match[1])
            return self.respond(200, image, mime)
        target = (WEB / (path.lstrip("/") or "index.html")).resolve()
        if not target.is_relative_to(WEB) or not target.is_file():
            raise FileNotFoundError("找不到此资源")
        self.respond(
            200,
            target.read_bytes(),
            mimetypes.guess_type(str(target))[0] or "application/octet-stream",
        )

    def write_resource(self, path):
        if path == "/api/auth/login":
            body = self.read_json(2048)
            try:
                token, user = self.store.login(
                    body.get("username"), body.get("password")
                )
            except access.LoginThrottled:
                raise
            except PermissionError as e:
                raise SignedOut(str(e)) from e
            return self.send_json(200, {"user": user}, self.session_cookie(token))
        if path == "/api/auth/logout":
            self.read_json(2048)
            self.store.logout(self.token())
            return self.send_json(200, {"ok": True}, self.session_cookie(None))
        if path == "/api/commands":
            if not self.token():
                raise SignedOut("请先登录")
            body = self.read_json(DOCUMENT_BODY)
            if (
                body.get("action") != "dossier.document"
                and int(self.headers["Content-Length"]) > SMALL_BODY
            ):
                raise ValueError("普通表单上限为 64 KiB")
            result = self.store.execute(
                body.get("action"),
                body.get("payload"),
                body.get("revision"),
                self.token(),
            )
            return self.send_json(200, result)
        match = re.fullmatch(r"/api/agent/adapters/([a-z0-9-]+)", path)
        if match:
            catalog = self.store.agent_resource(self.token(), "capabilities")
            spec = next((r for r in catalog["adapters"] if r["id"] == match[1]), None)
            if spec is None:
                raise FileNotFoundError("未登记或无权使用此适配器")
            return self.send_json(501, {"status": "not_connected", "contract": spec})
        match = re.fullmatch(r"/api/integrations/([a-zA-Z0-9._-]+)", path)
        if match:
            spec = self.store.capabilities(self.token(), match[1])
            return self.send_json(
                501,
                {
                    "status": "not_connected",
                    "id": spec["id"],
                    "message": "此适配器尚未接入",
                    "contract": spec,
                },
            )
        raise FileNotFoundError("找不到此接口")

    @staticmethod
    def invalid_constant(_value):
        raise ValueError("表单中含无效数值")


class InvalidMedia(ValueError):
    pass


def main():
    parser = argparse.ArgumentParser(description="安康医养平台 · 机构工作台")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--db", type=Path, default=ROOT / ".local" / "workspace.sqlite3"
    )
    parser.add_argument(
        "--public-origin",
        help="通过机构 HTTPS 反向代理访问时的完整源，例如 https://care.example.org",
    )
    args = parser.parse_args()
    origin = (args.public_origin or "").rstrip("/") or None
    if origin:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            parser.error("--public-origin 需要 HTTPS 根域名")
    store = Store(args.db)
    handler = partial(Handler, store=store, public_origin=origin)
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"安康医养平台已启动  http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
