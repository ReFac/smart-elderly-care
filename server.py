"""Serve the shared staff/family workspace and authenticated API on loopback."""

import argparse
from functools import partial
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
from platform_core.secure_storage import OPERATIONAL_ERRORS
from urllib.parse import parse_qs, unquote, urlsplit

from platform_core import access, facility
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
        media = " ".join(facility.media_origins())
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            f"img-src 'self' data: blob: {media}; media-src 'self' blob:; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
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
        body = json.loads(self.read_body(limit), parse_constant=self.invalid_constant)
        if not isinstance(body, dict):
            raise ValueError("请求必须为 JSON 对象")
        return body

    def read_body(self, limit):
        size = int(self.headers.get("Content-Length", "0"))
        if size <= 0 or size > limit:
            raise ValueError("请求为空或超过体积限制")
        return self.rfile.read(size)

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
        except OPERATIONAL_ERRORS:
            self.send_json(503, {"error": "数据库暂时不可用，请稍后重试"})
        except (ConnectionResetError, BrokenPipeError):
            pass

    def read_resource(self, path):
        token = self.token()
        voice = re.fullmatch(r"/api/voice-proposals/([a-f0-9]{32})", path)
        if voice:
            return self.send_json(200, self.store.voice_proposal(token, voice[1]))
        if path == "/api/backups":
            return self.send_json(200, self.store.backups.status(token))
        if path == "/api/payments/checkout/channels":
            return self.send_json(200, self.store.payment_channels(token))
        match = re.fullmatch(r"/api/payments/checkout/orders/(NH-[a-f0-9]{16})", path)
        if match:
            return self.send_json(200, self.store.payment_order_status(token, match[1]))
        geo = ("campusId", "buildingId", "floorId", "roomId")
        if path == "/api/facility":
            return self.send_json(200, self.store.facility_resource(token, "directory"))
        if path == "/api/care/handover-recipients":
            return self.send_json(200, self.store.handover_recipients(token))
        if path == "/api/care/handover-draft":
            params = parse_qs(
                urlsplit(self.path).query, max_num_fields=2, keep_blank_values=True
            )
            if (
                "assigneeId" not in params
                or set(params) - {"assigneeId", "residentId"}
                or any(len(v) != 1 for v in params.values())
            ):
                raise ValueError("请选择接班账号和交接范围")
            return self.send_json(
                200,
                self.store.handover_draft(
                    token, params["assigneeId"][0], params.get("residentId", [""])[0]
                ),
            )
        if path in (
            "/api/facility/search",
            "/api/facility/tour",
            "/api/agent/room-context",
        ):
            kind = path.rsplit("/", 1)[1]
            extras = {
                "search": ("q", "limit"),
                "tour": (),
                "room-context": ("limit", "offset"),
            }
            allowed = ("roomId",) if kind == "room-context" else geo
            params = parse_qs(
                urlsplit(self.path).query, max_num_fields=8, keep_blank_values=True
            )
            if any(
                k not in (*allowed, *extras[kind]) or len(v) != 1
                for k, v in params.items()
            ):
                raise ValueError("院区查询参数无效")
            filters = {k: v[0] for k, v in params.items()}
            if kind == "search" and "q" not in filters:
                raise ValueError("请提供房号或姓名查询词")
            return self.send_json(
                200,
                self.store.facility_resource(
                    token,
                    "agent-context" if kind == "room-context" else kind,
                    **filters,
                ),
            )
        match = re.fullmatch(r"/api/facility/(floors|rooms)/([a-zA-Z0-9_-]+)", path)
        if match:
            return self.send_json(
                200, self.store.facility_resource(token, match[1][:-1], match[2])
            )
        if path.startswith("/tour-media/"):
            return self.tour_image(token, path)
        if path == "/api/branding":
            return self.send_json(200, self.store.branding())
        if path == "/api/health":
            return self.send_json(200, {"status": "ok"})
        if path == "/api/version":
            return self.send_json(200, self.store.version(token))
        if path == "/api/state":
            return self.send_json(200, self.store.snapshot(token))
        match = re.fullmatch(r"/api/portal/history/(careSchedule|medication)", path)
        if match:
            query = parse_qs(urlsplit(self.path).query, max_num_fields=2)
            if set(query) != {"offset", "revision"} or any(
                len(v) != 1
                or not v[0].isascii()
                or not v[0].isdigit()
                or len(v[0]) > 16
                for v in query.values()
            ):
                raise ValueError("请指定有效的历史分页及版本")
            return self.send_json(
                200,
                self.store.portal_history(
                    token, match[1], int(query["offset"][0]), int(query["revision"][0])
                ),
            )
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
        match = re.fullmatch(
            r"/api/agent/runs/(run-[a-f0-9]{32})/handovers/([a-f0-9]{32})", path
        )
        if match:
            return self.send_json(
                200, self.store.agent_handover(token, *match.groups())
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
        match = re.fullmatch(r"/api/documents/([a-zA-Z0-9_-]+)/ocr", path)
        if match:
            return self.send_json(200, self.store.document_ocr_detail(token, match[1]))
        match = re.fullmatch(r"/api/residents/([a-zA-Z0-9_-]+)/summary-draft", path)
        if match:
            return self.send_json(
                200, self.store.dossier_summary_draft(token, match[1])
            )
        match = re.fullmatch(
            r"/api/reports/([a-zA-Z0-9_-]+)/versions/([1-9][0-9]{0,8})", path
        )
        if match:
            return self.send_json(
                200, self.store.report_version(token, match[1], int(match[2]))
            )
        match = re.fullmatch(r"/api/documents/([a-zA-Z0-9_-]+)/image", path)
        if match:
            image, mime = self.store.photo(token, match[1])
            return self.respond(200, image, mime)
        target = (WEB / (path.lstrip("/") or "index.html")).resolve()
        if (
            not target.is_relative_to(WEB)
            or target.is_relative_to(WEB / "tour-media")
            or not target.is_file()
        ):
            raise FileNotFoundError("找不到此资源")
        self.respond(
            200,
            target.read_bytes(),
            mimetypes.guess_type(str(target))[0] or "application/octet-stream",
        )

    def tour_image(self, token, path):
        image, mime = self.store.tour_media(token, path)
        self.respond(200, image, mime)

    def write_resource(self, path):
        if path in ("/api/secure-documents/export", "/api/secure-documents/open"):
            from platform_core import protected_docs

            token = self.token()
            if not token:
                raise SignedOut("请先登录")
            if path.endswith("/export"):
                spec = self.read_json(SMALL_BODY)
                revision = spec.pop("revision", None)
                packet = protected_docs.export(self.store, token, spec, revision)
                return self.respond(200, packet, "application/octet-stream")
            if self.headers.get_content_type() != "application/octet-stream":
                raise InvalidMedia("请上传 .akdoc 加密文件")
            packet = self.read_body(protected_docs.MAX_PACKET)
            return self.send_json(
                200, protected_docs.open_package(self.store, token, packet)
            )
        verify = re.fullmatch(
            r"/api/backups/points/(ak-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{32})/verify", path
        )
        if verify:
            self.read_json(SMALL_BODY)
            return self.send_json(
                200, self.store.backups.verify(self.token(), verify[1])
            )
        if path in (
            "/api/backups/points",
            "/api/backups/locations",
            "/api/backups/retry",
        ):
            body = self.read_json(SMALL_BODY)
            if path.endswith("/points"):
                result = self.store.backups.request(self.token(), body.get("requestId"))
            elif path.endswith("/locations"):
                result = self.store.backups.link(self.token(), body.get("provider"))
            else:
                result = self.store.backups.retry(self.token())
            return self.send_json(200, result)
        asr = re.fullmatch(r"/api/media/asr/([a-zA-Z0-9_-]{1,100})", path)
        if asr:
            if not self.token():
                raise SignedOut("请先登录")
            if self.headers.get_content_type() not in (
                "audio/wav",
                "audio/ogg",
                "application/octet-stream",
            ):
                raise InvalidMedia("请上传 WAV 或 Ogg Opus 录音")
            result = self.store.transcribe(
                self.token(),
                asr[1],
                self.read_body(8 * 1024 * 1024),
                self.headers.get("X-DeepSeek-Consent") == "yes",
            )
            return self.send_json(200, result)
        if path == "/api/payments/checkout":
            body = self.read_json(512)
            if set(body) != {"orderId"}:
                raise ValueError("请选择商户订单")
            return self.send_json(
                200, self.store.payment_checkout(self.token(), body["orderId"])
            )
        channel = re.fullmatch(r"/api/payments/notify/(wechat|alipay)", path)
        if channel:
            from platform_core.operations import channels

            provider = channel[1]
            mime = (
                "application/json"
                if provider == "wechat"
                else "application/x-www-form-urlencoded"
            )
            if self.headers.get_content_type() != mime:
                raise InvalidMedia("支付渠道回调格式无效")
            channels.receive(
                self.store, provider, self.headers, self.read_body(SMALL_BODY)
            )
            if provider == "alipay":
                return self.respond(200, b"success", "text/plain; charset=utf-8")
            return self.send_json(200, {"code": "SUCCESS", "message": "成功"})
        if path == "/api/access/preview":
            return self.send_json(
                200, self.store.access_preview(self.token(), self.read_json(8192))
            )
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
        if path == "/api/agent/room-proposals":
            if not self.token():
                raise SignedOut("请先登录")
            body = self.read_json(SMALL_BODY)
            if set(body) != {"payload", "revision"}:
                raise ValueError("请提交修订号及区域草稿")
            return self.send_json(
                200,
                self.store.execute(
                    "gw.propose",
                    body["payload"],
                    body["revision"],
                    self.token(),
                    room_bound=True,
                ),
            )
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
            if body.get("action") == "account.changePassword":
                return self.send_json(200, result, self.session_cookie(None))
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
    parser.add_argument(
        "--initial-data",
        choices=("empty", "demo"),
        default="demo",
        help="仅新数据库使用。empty 创建空白机构，demo 创建演示样本",
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
    store = Store(args.db, initial_data=args.initial_data)
    handler = partial(Handler, store=store, public_origin=origin)
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        store.backups.start()
        print(f"安康医养平台已启动  http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            store.backups.stop()


if __name__ == "__main__":
    main()
