"""Serve the shared staff/family workspace and authenticated API on loopback."""

import sys
import os
import argparse
import logging
from functools import partial
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler
import json
import mimetypes
from pathlib import Path
import re
from threading import Event, Thread
from platform_core.secure_storage import OPERATIONAL_ERRORS
from urllib.parse import parse_qs, unquote, urlsplit

from platform_core.agents import chat
from platform_core.operations import expense_import
from platform_core.backups import exchange
from platform_core import access, facility, http_capacity, updates, visitor_access
from platform_core import daily_life, lead_intake, medical_visits, resident_health, scheduled_work
from platform_core.provider import round_priorities
from platform_core.store import Conflict, SignedOut, Store, encode

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
SMALL_BODY = 64 * 1024
DOCUMENT_BODY = 12 * 1024 * 1024
VISIT_GROUP_BODY = 34 * 1024 * 1024  # 24 MiB of originals, base64-encoded, plus metadata.


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, store, public_origin=None, demo_public_tour=False,
                 update_service=None, update_gate=None, update_boot=None, **kwargs):
        self.store = store
        self.public_origin = public_origin
        self.demo_public_tour = demo_public_tour
        self.update_service = update_service
        self.update_gate = update_gate
        self.update_boot = update_boot
        super().__init__(*args, **kwargs)

    def log_request(self, code="-", size="-"):
        # Do not include staff names or room filters from the query string in access logs.
        self.log_message("%s %s %s", self.command, self.path.partition("?")[0], code)

    def respond(self, status, content, mime, cookie=None, *, attachment=None, retry_after=None, etag=None, page_count=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        if status != 304:
            self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "private, no-cache" if etag else "no-store")
        if page_count is not None:
            self.send_header("X-Page-Count", str(page_count))
        if etag:
            self.send_header("ETag", etag)
        self.send_header("X-Content-Type-Options", "nosniff")
        if retry_after is not None:
            self.send_header("Retry-After", str(retry_after))
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
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

    def send_json(self, status, body, cookie=None, *, retry_after=None):
        self.respond(
            status, encode(body).encode(), "application/json; charset=utf-8", cookie,
            retry_after=retry_after,
        )

    def token(self, name="nh_session"):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        value = cookie.get(name)
        return value.value if value else None

    def visitor_demo(self):
        return self.demo_public_tour and not self.public_origin

    def visitor_status(self, current=None):
        return visitor_access.status(
            self.store, current or self.token("nh_visitor"), self.token(), demo=self.visitor_demo()
        )

    def passkey_origin(self):
        host = self.headers.get("Host", "")
        if self.public_origin and host == urlsplit(self.public_origin).netloc:
            return self.public_origin
        if urlsplit("//" + host).hostname == "localhost":
            return "http://" + host
        return None

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
            if self.update_gate and not self.update_gate.is_file() and path != "/api/health":
                return self.send_json(503, {"error": "机构正在切换新版，请稍后重新打开"})
            if method == "POST":
                origin = self.headers.get("Origin")
                if origin and origin not in {
                    self.public_origin,
                    "http://" + host if local else self.public_origin,
                }:
                    raise PermissionError("请从机构工作台提交")
            operation = self.read_resource if method == "GET" else self.write_resource
            slots = getattr(getattr(self, "server", None), "heavy_slots", None)
            if slots is None or not http_capacity.heavy_request(method, path, self.headers.get("Content-Length")):
                return operation(path)
            if not slots.acquire(blocking=False):
                return self.send_json(503, {"error": "机构正在处理较多请求，请稍后重试"}, retry_after=2)
            try:
                return operation(path)
            finally:
                slots.release()
        except SignedOut as e:
            self.send_json(401, {"error": str(e)})
        except (access.LoginThrottled, lead_intake.SubmissionLimit) as e:
            self.send_json(429, {"error": str(e)})
        except PermissionError as e:
            self.send_json(403, {"error": str(e)})
        except FileNotFoundError as e:
            self.send_json(404, {"error": str(e)})
        except chat.Unavailable as e:
            self.send_json(503, {"error": str(e)})
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

    def query_fields(self, allowed):
        params = parse_qs(urlsplit(self.path).query, max_num_fields=len(allowed))
        if set(params) - allowed or any(len(values) != 1 for values in params.values()):
            raise ValueError("筛选参数无效")
        return {key: values[0] for key, values in params.items()}

    def read_resource(self, path):
        if path == "/api/account/display-preferences":
            from platform_core import display_preferences
            return self.send_json(200, display_preferences.settings(self.store, self.token()))
        if path == "/api/care/risk-report-example":
            from platform_core.care import risk_reports
            return self.send_json(200, risk_reports.example(self.store, self.token()))
        if path == "/api/system/monitor":
            from platform_core import system_monitor
            params = self.query_fields({"view"})
            return self.send_json(200, system_monitor.inspect(self.store, self.token(), params.get("view"), self.server))

        if path == "/api/finance/subsidies":
            from platform_core.operations import subsidies
            params = self.query_fields({"month"})
            return self.send_json(200, subsidies.read(self.store, self.token(), params.get("month")))
        subsidy_file = re.fullmatch(r"/api/(finance/subsidies/materials|dossier/credentials)/([a-f0-9]{32})", path)
        if subsidy_file:
            from platform_core.operations import subsidies
            raw, mime = subsidies.original(self.store, self.token(), subsidy_file[2], credential=subsidy_file[1] == "dossier/credentials")
            return self.respond(200, raw, mime)
        if path == "/api/auth/passkeys":
            from platform_core import passkeys

            return self.send_json(200, passkeys.listing(self.store, self.token(), self.passkey_origin()))
        if path == "/api/updates":
            service = self.update_service or updates.UpdateService(self.store)
            return self.send_json(200, service.status(self.token()))
        if path == "/api/catalog/hospitals":
            from platform_core import hospital_catalog

            params = self.query_fields({"q"})
            return self.send_json(200, hospital_catalog.search(self.store, self.token(), params.get("q", "")))
        if path == "/api/care/areas":
            from platform_core import care_areas

            params = self.query_fields({"buildingId"})
            return self.send_json(200, care_areas.read(self.store, self.token(), params.get("buildingId", "")))
        if path == "/api/scheduled-work":
            return self.send_json(200, scheduled_work.read(self.store, self.token()))
        if path == "/api/provider/usage":
            from platform_core.provider import usage_report

            query = self.query_fields({"start", "end", "feature", "actorId", "page"})
            return self.send_json(200, usage_report.read(self.store, self.token(), query))
        reported = re.fullmatch(r"/api/residents/([A-Za-z0-9_-]{1,100})/(reported-medications|drug-names)", path)
        if reported:
            from platform_core import medication_reports
            if reported[2] == "drug-names":
                query = self.query_fields({"q", "online"})
                if "online" in query and query["online"] != "1":
                    raise ValueError("联网选项无效")
                return self.send_json(200, medication_reports.lookup(
                    self.store, self.token(), reported[1], query.get("q", ""), online="online" in query
                ))
            return self.send_json(200, medication_reports.read(self.store, self.token(), reported[1]))
        card = re.fullmatch(r"/api/medication-rounds/cards/([A-Za-z0-9]{8})\.png", path)
        if card:
            from platform_core import med_rounds
            return self.respond(200, med_rounds.qr(self.store, self.token(), card[1], self.public_origin or ("http://" + self.headers["Host"])), "image/png")
        if path == "/api/daily-life/roster":
            params = self.query_fields({"campusId", "roomId", "day"})
            return self.send_json(200, daily_life.roster(
                self.store, self.token(), params.get("campusId", ""), params.get("roomId", ""), params.get("day", "")
            ))
        timeline_match = re.fullmatch(r"/api/residents/([A-Za-z0-9_-]{1,100})/daily-life", path)
        if timeline_match:
            params = self.query_fields({"start", "end"})
            return self.send_json(200, daily_life.timeline(
                self.store, self.token(), timeline_match[1], params.get("start", ""), params.get("end", "")
            ))
        health = re.fullmatch(r"/api/residents/([A-Za-z0-9_-]{1,100})/health-profile", path)
        if health:
            return self.send_json(200, resident_health.read(self.store, self.token(), health[1]))
        personal_brief = re.fullmatch(r"/api/residents/([A-Za-z0-9_-]{1,100})/personal-brief", path)
        if personal_brief:
            return self.send_json(200, self.store.rounds.personal_brief(self.token(), personal_brief[1]))
        original = re.fullmatch(r"/api/medical-visits/originals/([a-f0-9]{32})", path)
        if original:
            raw, mime = medical_visits.original(self.store, self.token(), original[1])
            return self.respond(200, raw, mime)
        if path in ("/visit", "/visit/"):
            return self.respond(200, (WEB / "visit.html").read_bytes(), "text/html; charset=utf-8")
        if path in ("/faq", "/faq/"):
            return self.respond(200, (WEB / "faq.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/public/faq":
            from platform_core import faq

            return self.send_json(200, faq.read())
        if path in ("/roomtour", "/roomtour/", "/visit/roomtour"):
            return self.respond(200, (WEB / "roomtour.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/public/visitor/status":
            return self.send_json(200, self.visitor_status())
        if path == "/api/public/reception":
            return self.send_json(200, lead_intake.reception(self.store))
        if path == "/api/leads/schedule":
            query = parse_qs(urlsplit(self.path).query, max_num_fields=2)
            if set(query) != {"campusId", "date"} or any(len(v) != 1 for v in query.values()):
                raise ValueError("请选择接待院区和排班日期")
            return self.send_json(200, lead_intake.schedule(self.store, self.token(), query["campusId"][0], query["date"][0]))
        expense_file = re.fullmatch(r"/api/finance/expense-import/files/([a-f0-9]{64})", path)
        if expense_file:
            raw = expense_import.original(self.store, self.token(), expense_file[1])
            return self.respond(200, raw, "application/octet-stream")
        if path == "/api/assistant/chat":
            values = parse_qs(urlsplit(self.path).query, max_num_fields=4)
            if set(values) - {"roomId", "floorId", "buildingId", "campusId"} or any(
                len(v) != 1 for v in values.values()
            ):
                raise ValueError("聊天区域参数无效")
            return self.send_json(
                200,
                chat.read(
                    self.store, self.token(), {k: v[0] for k, v in values.items()}
                ),
            )
        if path == "/api/auth/channels":
            from platform_core import identity

            return self.send_json(
                200, {"channels": sorted(identity.senders(self.store))}
            )
        priority = re.fullmatch(
            r"/api/rounds/residents/([A-Za-z0-9_-]{1,100})/priorities", path
        )
        if priority:
            params = parse_qs(urlsplit(self.path).query, max_num_fields=1)
            return self.send_json(
                200,
                round_priorities.read(
                    self.store,
                    self.token(),
                    priority[1],
                    params.get("reportId", [""])[0],
                ),
            )
        if self.store.rounds.matches(path, False):
            return self.send_json(200, self.store.rounds.read(self.token(), path))
        token = self.token()
        permission_profile = re.fullmatch(r"/api/permission-requests/([a-f0-9]{32})/profile", path)
        if path == "/api/permission-requests" or permission_profile:
            from platform_core import permission_requests

            return self.send_json(200, permission_requests.read(
                self.store, token, permission_profile[1] if permission_profile else None
            ))
        voice = re.fullmatch(r"/api/voice-proposals/([a-f0-9]{32})", path)
        if voice:
            return self.send_json(200, self.store.voice_proposal(token, voice[1]))
        if path == "/api/backups/download":
            params = parse_qs(urlsplit(self.path).query, max_num_fields=1)
            ticket = params.get("ticket", [""])[0]
            src, size, name = exchange.open_download(self.store.backups, token, ticket)
            with src:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(size))
                self.send_header(
                    "Content-Disposition", 'attachment; filename="' + name + '"'
                )
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                import shutil

                shutil.copyfileobj(src, self.wfile, 1024 * 1024)
            return
        if path == "/api/backups":
            params = parse_qs(urlsplit(self.path).query, max_num_fields=1)
            return self.send_json(
                200,
                self.store.backups.status(token, int(params.get("before", ["0"])[0])),
            )
        if path == "/api/payments/checkout/channels":
            return self.send_json(200, self.store.payment_channels(token))
        match = re.fullmatch(r"/api/payments/checkout/orders/(NH-[a-f0-9]{16})", path)
        if match:
            return self.send_json(200, self.store.payment_order_status(token, match[1]))
        geo = ("campusId", "buildingId", "floorId", "roomId")
        if path.startswith("/api/care-timeline/"):
            from platform_core.care import timeline

            match = re.fullmatch(
                r"/api/care-timeline/(?:(work)|(resident|room)/([a-zA-Z0-9_-]{1,120}))",
                path,
            )
            if not match:
                raise FileNotFoundError("未找到照护时间线")
            query = parse_qs(
                urlsplit(self.path).query, max_num_fields=4, keep_blank_values=True
            )
            if any(
                k not in {"day", "offset", "revision", "q"} or len(v) != 1
                for k, v in query.items()
            ):
                raise ValueError("无效的时间线查询")
            return self.send_json(
                200,
                timeline.read(
                    self.store,
                    token,
                    match[1] or match[2],
                    match[3] or "",
                    **{k: v[0] for k, v in query.items()},
                ),
            )
        if path == "/api/facility":
            return self.send_json(200, self.store.facility_resource(token, "directory"))
        if path == "/api/care/trial-assignees":
            query = parse_qs(urlsplit(self.path).query, max_num_fields=1)
            if set(query) != {"residentId"}:
                raise ValueError("请选择试住长辈档案")
            return self.send_json(200, self.store.trial_assignees(token, query["residentId"][0]))
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
            "/api/facility/rooms",
            "/api/facility/tour",
            "/api/agent/room-context",
        ):
            kind = path.rsplit("/", 1)[1]
            extras = {
                "search": ("q", "limit"),
                "rooms": ("bedCount", "limit"),
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
            state = {"status": "ok"}
            if self.update_boot:
                state["boot"] = self.update_boot
            return self.send_json(200, state)
        if path == "/api/version":
            return self.send_json(200, self.store.version(token))
        if path == "/api/assistant/navigation-version":
            return self.send_json(200, self.store.navigation_version(token))
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
        if path == "/api/history":
            query = parse_qs(urlsplit(self.path).query, max_num_fields=7)
            allowed = {"residentId", "roomId", "actorId", "before", "limit", "q", "day"}
            if query.keys() - allowed or any(
                len(values) != 1 for values in query.values()
            ):
                raise ValueError("变更记录筛选条件无效")
            filters = {key: values[0] for key, values in query.items()}
            for key in ("before", "limit"):
                if key in filters:
                    filters[key] = int(filters[key])
            return self.send_json(200, self.store.history(token, **filters))
        history_point = re.fullmatch(r"/api/history/([1-9][0-9]{0,17})", path)
        if history_point:
            return self.send_json(
                200, self.store.history_change(token, int(history_point[1]))
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
        match = re.fullmatch(r"/api/staff/([a-zA-Z0-9_-]+)/employment(?:/([a-zA-Z0-9_-]+)/original)?", path)
        if match:
            from platform_core import staff_employment

            result = staff_employment.read(self.store, token, match[1], match[2])
            if match[2]:
                return self.respond(200, *result)
            return self.send_json(200, result)
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
        match = re.fullmatch(r"/api/documents/([a-zA-Z0-9_-]+)/pages/([1-9][0-9]{0,3})", path)
        if match:
            from platform_core import pdf_original

            original, mime = self.store.photo(token, match[1])
            if mime != "application/pdf":
                raise ValueError("请选择 PDF 原件")
            return self.respond(200, pdf_original.render_page(original, int(match[2])), "image/png")
        match = re.fullmatch(r"/api/documents/([a-zA-Z0-9_-]+)/image", path)
        if match:
            image, mime = self.store.photo(token, match[1])
            return self.respond(200, image, mime, attachment="document.pdf" if mime == "application/pdf" else None)
        target = (WEB / (path.lstrip("/") or "index.html")).resolve()
        if (
            not target.is_relative_to(WEB)
            or target.is_relative_to(WEB / "tour-media")
            or not target.is_file()
        ):
            raise FileNotFoundError("找不到此资源")
        mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        with target.open("rb") as source:
            etag = None
            if target.suffix in {".js", ".css"}:
                stat = os.fstat(source.fileno())
                # Match the open file even when an upgrade replaces the path.
                tag = f'"{stat.st_ino:x}-{stat.st_size:x}-{stat.st_mtime_ns:x}-{stat.st_ctime_ns:x}"'
                etag = "W/" + tag
                candidates = self.headers.get("If-None-Match", "").split(",")
                if any(value.strip().removeprefix("W/") in {"*", tag} for value in candidates):
                    return self.respond(304, b"", mime, etag=etag)
            self.respond(200, source.read(), mime, etag=etag)

    def tour_image(self, token, path):
        image, mime = self.store.tour_media(token, path)
        self.respond(200, image, mime)

    def assistant_stream(self, request):
        from platform_core.agents.chat_progress import Progress

        speak = request.pop("readAloud", False)
        voice_receipt = request.pop("voiceTranscriptId", None)
        if type(speak) is not bool:
            raise ValueError("朗读选项格式无效")
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        connected = True

        def emit(event):
            nonlocal connected
            if connected:
                try:
                    self.wfile.write((encode(event) + "\n").encode())
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    connected = False

        progress = Progress(self.store, emit, speak=speak)
        try:
            result = chat.reply(self.store, self.token(), request, progress=progress, voice_receipt=voice_receipt)
            emit({"type": "done", "result": result})
        except (SignedOut, Conflict, PermissionError, FileNotFoundError, chat.Unavailable,
                ValueError, TypeError, OverflowError, RecursionError, *OPERATIONAL_ERRORS) as err:
            if isinstance(err, SignedOut):
                status = 401
            elif isinstance(err, Conflict):
                status = 409
            elif isinstance(err, (PermissionError, FileNotFoundError)):
                status = 403
            elif isinstance(err, (chat.Unavailable, OPERATIONAL_ERRORS)):
                status = 503
            else:
                status = 400
            message = "数据库暂时不可用，请稍后重试" if isinstance(err, OPERATIONAL_ERRORS) else str(err)
            emit({"type": "error", "status": status, "error": message})
        finally:
            progress.close()

    def write_resource(self, path):
        if path == "/api/account/display-preferences":
            from platform_core import display_preferences
            return self.send_json(200, display_preferences.settings(self.store, self.token(), self.read_json(1024)))
        if path in ("/api/updates/check", "/api/updates/settings", "/api/updates/download", "/api/updates/install"):
            service = self.update_service or updates.UpdateService(self.store)
            data = self.read_json(1024)
            token = self.token()
            if path.endswith("/settings"):
                view = service.configure(token, data)
            elif path.endswith("/check") and not data:
                view = service.check(token)
            elif set(data) == {"version"} and path.endswith(("/download", "/install")):
                action = service.download if path.endswith("/download") else service.queue
                view = action(token, data["version"])
            else:
                raise ValueError("请选择更新操作或版本")
            return self.send_json(200, view)
        if path == "/api/care/admission/preview":
            return self.send_json(200, self.store.admission_preview(self.token(), self.read_json(SMALL_BODY)))
        if path == "/api/inventory/matches":
            from platform_core import inventory_dedupe

            return self.send_json(200, inventory_dedupe.preview(self.store, self.token(), self.read_json(4096)))
        doc_page = re.fullmatch(r"/api/assistant/documents/pages/([1-9][0-9]{0,3})", path)
        if doc_page:
            from platform_core import pdf_original
            from platform_core.agents import document_intake

            token = self.token()
            document_intake.check(self.store, token)
            if self.headers.get_content_type() != "application/pdf":
                raise InvalidMedia("请选择 PDF 原件")
            raw = self.read_body(8 * 1024 * 1024)
            number = int(doc_page[1])
            count = pdf_original.pages(raw)
            if number > count:
                raise ValueError("页码超出原件范围")
            page = pdf_original.render_page(raw, number)
            document_intake.check(self.store, token)
            return self.respond(200, page, "image/png", page_count=count)
        if path == "/api/assistant/documents/preview":
            from platform_core.agents import document_intake

            token = self.token()
            document_intake.check(self.store, token)
            mime = self.headers.get_content_type()
            if mime not in ("application/pdf", "image/png", "image/jpeg"):
                raise InvalidMedia("请选择 PDF、PNG 或 JPEG 原件")
            return self.send_json(200, document_intake.preview(
                self.store, token, self.read_body(8 * 1024 * 1024), mime))
        if path == "/api/staff/resume/preview":
            from platform_core import staff_resume

            token = self.token()
            staff_resume.check(self.store, token)
            if self.headers.get_content_type() not in ("application/pdf", "image/png", "image/jpeg"):
                raise InvalidMedia("请选择 PDF、PNG 或 JPEG 简历")
            return self.send_json(200, staff_resume.preview(self.store, token, self.read_body(staff_resume.MAX_BYTES)))
        if path == "/api/public/visitor/register":
            token, user = visitor_access.register(
                self.store, self.read_json(2048), self.client_address[0], self.token()
            )
            return self.send_json(201, {"user": user}, self.session_cookie(token))
        if path == "/api/public/visitor/wechat-contact":
            from platform_core import wechat_tour
            return self.send_json(202, wechat_tour.receive(self.store, self.read_json(1024), self.client_address[0]))
        if path == "/api/public/visitor/code":
            result = visitor_access.request_code(
                self.store, self.read_json(512), self.client_address[0], demo=self.visitor_demo()
            )
            return self.send_json(200, result)
        if path == "/api/public/visitor/verify":
            token = visitor_access.verify(
                self.store, self.read_json(512), self.client_address[0], demo=self.visitor_demo()
            )
            secure = "; Secure" if self.public_origin else ""
            cookie = f"nh_visitor={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={visitor_access.SESSION_TTL}{secure}"
            return self.send_json(200, self.visitor_status(token), cookie)
        health = re.fullmatch(r"/api/residents/([A-Za-z0-9_-]{1,100})/health-profile/draft", path)
        if health:
            return self.send_json(200, resident_health.draft(self.store, self.token(), health[1], self.read_json(SMALL_BODY)))
        visit = re.fullmatch(r"/api/residents/([A-Za-z0-9_-]{1,100})/medical-visits/preview", path)
        if visit:
            token = self.token()
            self.store.version(token)
            group = self.read_json(VISIT_GROUP_BODY)
            result = medical_visits.preview(self.store, token, visit[1], group)
            return self.send_json(200, result)
        if path == "/api/public/leads":
            payload = self.read_json(8192)
            return self.send_json(202, lead_intake.submit(self.store, payload, self.client_address[0]))
        inspection = re.fullmatch(r"/api/residents/([a-zA-Z0-9_-]+)/document-pages", path)
        if inspection:
            if self.headers.get_content_type() != "application/pdf":
                raise InvalidMedia("请选择 PDF 原件")
            return self.send_json(200, self.store.inspect_pdf(
                self.token(), inspection[1], self.read_body(8 * 1024 * 1024)
            ))
        if path == "/api/assistant/network/probe":
            from platform_core.agents import network

            if self.read_json(1024):
                raise ValueError("连接检测仅使用机构配置的 DeepSeek 服务")
            return self.send_json(200, network.probe(self.store, self.token()))
        chart = re.fullmatch(r"/api/residents/([a-zA-Z0-9_-]+)/summary-draft", path)
        if chart:
            if self.read_json(SMALL_BODY) != {}:
                raise ValueError("生成档案摘要无需额外参数")
            return self.send_json(
                200,
                self.store.dossier_summary_draft(self.token(), chart[1], generate=True),
            )
        if path == "/api/scheduled-work/meals/preview":
            from platform_core import scheduled_meals

            return self.send_json(200, scheduled_meals.preview(self.store, self.token(), self.read_json(SMALL_BODY)))
        if path == "/api/medication-rounds/preview":
            from platform_core import med_rounds
            return self.send_json(200, med_rounds.preview(self.store, self.token(), self.read_json(SMALL_BODY)))
        if path == "/api/assistant/chat/speech":
            from platform_core.provider import read_aloud

            return self.respond(200, read_aloud.listen(self.store, self.token(), self.read_json(SMALL_BODY)), "audio/wav")
        if path == "/api/assistant/chat/stream":
            return self.assistant_stream(self.read_json(SMALL_BODY))
        if path in ("/api/assistant/chat", "/api/assistant/chat/reset"):
            request = self.read_json(SMALL_BODY)
            operation = chat.reset if path.endswith("/reset") else chat.reply
            return self.send_json(200, operation(self.store, self.token(), request))
        if path == "/api/billing/preview":
            body = self.read_json(SMALL_BODY)
            return self.send_json(
                200,
                self.store.bill_preview(
                    self.token(), body.get("payload"), body.get("revision")
                ),
            )
        if path == "/api/finance/expense-import/preview":
            return self.send_json(200, expense_import.preview(
                self.store, self.token(), self.read_json(2 * expense_import.FILE_LIMIT)
            ))
        if path.startswith("/api/auth/passkeys/"):
            from platform_core import passkeys

            origin = self.passkey_origin()
            if not passkeys.available(origin):
                raise ValueError("通行密钥仅可用在机构 HTTPS 域名或 localhost")
            request = self.read_json(32 * 1024)
            operation = path.rsplit("/", 1)[-1]
            if operation in ("enroll-options", "signin-options"):
                return self.send_json(200, passkeys.options(self.store, self.token(), operation, request, origin, self.client_address[0]))
            if operation == "revoke":
                return self.send_json(200, passkeys.revoke(self.store, self.token(), request, origin))
            if operation == "enroll":
                return self.send_json(200, passkeys.finish(self.store, self.token(), operation, request, origin))
            if operation == "signin":
                token, user = passkeys.finish(self.store, None, operation, request, origin)
                return self.send_json(200, {"user": user}, self.session_cookie(token))
            raise FileNotFoundError("未找到通行密钥操作")
        if path in ("/api/auth/reset-link/send", "/api/auth/reset-link/redeem"):
            from platform_core import reset_links

            request = self.read_json(2048)
            if path.endswith("/send"):
                if not self.token():
                    raise SignedOut("请先登录")
                return self.send_json(200, reset_links.send(self.store, self.token(), request, self.public_origin))
            return self.send_json(200, reset_links.redeem(self.store, request), self.session_cookie(None))
        if path in ("/api/auth/code", "/api/auth/verify"):
            from platform_core import identity

            payload = self.read_json(2048)
            if path == "/api/auth/code":
                return self.send_json(
                    200,
                    identity.request_code(
                        self.store,
                        payload,
                        token=self.token(),
                        peer=self.client_address[0],
                        background=True,
                    ),
                )
            result = identity.finish(self.store, payload, token=self.token())
            return self.send_json(
                200,
                result,
                self.session_cookie(None) if payload["purpose"] == "password" else None,
            )
        priority = re.fullmatch(
            r"/api/rounds/residents/([A-Za-z0-9_-]{1,100})/priorities", path
        )
        if priority:
            return self.send_json(
                200,
                round_priorities.generate(
                    self.store, self.token(), priority[1], self.read_json(SMALL_BODY)
                ),
            )
        if self.store.rounds.matches(path, True):
            return self.send_json(
                200,
                self.store.rounds.write(self.token(), path, self.read_json(SMALL_BODY)),
            )
        undo = re.fullmatch(r"/api/history/([1-9][0-9]{0,17})/undo", path)
        if undo:
            body = self.read_json(SMALL_BODY)
            if body.keys() - {"revision", "comment"}:
                raise ValueError("撤销参数无效")
            result = self.store.undo_change(
                self.token(),
                int(undo[1]),
                body.get("revision"),
                comment=body.get("comment", ""),
            )
            return self.send_json(200, result)

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
        if path == "/api/backups/imports/preview":
            if self.headers.get_content_type() != "application/octet-stream":
                raise InvalidMedia("请选择 .akbak 加密文件")
            result = exchange.preview_file(
                self.store.backups,
                self.token(),
                self.rfile,
                int(self.headers.get("Content-Length", "0")),
            )
            return self.send_json(200, result)
        imported = re.fullmatch(r"/api/backups/imports/([a-f0-9]{32})/confirm", path)
        if imported:
            body = self.read_json(SMALL_BODY)
            return self.send_json(
                200,
                exchange.confirm_import(
                    self.store.backups,
                    self.token(),
                    imported[1],
                    body.get("comment", ""),
                ),
            )
        point_op = re.fullmatch(
            r"/api/backups/points/(ak-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{32})/(preview|apply|export|fetch)",
            path,
        )
        if point_op:
            body = self.read_json(SMALL_BODY)
            service = self.store.backups
            if point_op[2] == "preview":
                result = exchange.preview_point(service, self.token(), point_op[1])
            elif point_op[2] == "fetch":
                result = exchange.fetch_replica(
                    service,
                    self.token(),
                    point_op[1],
                    body.get("provider"),
                    body.get("comment", ""),
                )
            elif point_op[2] == "apply":
                result = exchange.apply_point(service, self.token(), point_op[1], body)
            else:
                result = exchange.prepare_export(
                    service, self.token(), point_op[1], body.get("comment", "")
                )
            return self.send_json(200, result)
        if path in ("/api/backups/settings", "/api/backups/locations/unlink"):
            body = self.read_json(SMALL_BODY)
            if path.endswith("/settings"):
                result = exchange.change_policy(self.store.backups, self.token(), body)
            else:
                result = exchange.unlink(
                    self.store.backups,
                    self.token(),
                    body.get("provider"),
                    body.get("comment", ""),
                )
            return self.send_json(200, result)
        verify = re.fullmatch(
            r"/api/backups/points/(ak-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{32})/verify", path
        )
        if verify:
            body = self.read_json(SMALL_BODY)
            return self.send_json(
                200,
                self.store.backups.verify(
                    self.token(), verify[1], body.get("comment", "")
                ),
            )
        if path in (
            "/api/backups/points",
            "/api/backups/locations",
            "/api/backups/retry",
        ):
            body = self.read_json(SMALL_BODY)
            if path.endswith("/points"):
                result = self.store.backups.request(
                    self.token(), body.get("requestId"), body.get("comment", "")
                )
            elif path.endswith("/locations"):
                result = self.store.backups.link(
                    self.token(), body.get("provider"), body.get("comment", "")
                )
            else:
                result = self.store.backups.retry(self.token(), body.get("comment", ""))
            return self.send_json(200, result)
        asr = re.fullmatch(r"/api/media/asr/([a-zA-Z0-9_-]{1,100})", path)
        agent_voice = path in (
            "/api/agent/voice/transcriptions",
            "/api/assistant/voice",
        )
        if asr or agent_voice:
            if not self.token():
                raise SignedOut("请先登录")
            if self.headers.get_content_type() not in (
                "audio/wav",
                "audio/ogg",
                "application/octet-stream",
            ):
                raise InvalidMedia("请上传 WAV 或 Ogg Opus 录音")
            raw = self.read_body(8 * 1024 * 1024)
            consent = self.headers.get("X-DeepSeek-Consent") == "yes"
            if agent_voice:
                from platform_core.provider import speech

                query = parse_qs(
                    urlsplit(self.path).query, max_num_fields=4, keep_blank_values=True
                )
                if any(len(items) != 1 for items in query.values()):
                    raise ValueError("区域参数不能重复")
                region = {key: items[0] for key, items in query.items()} or None
                result = speech.recognize_agent(
                    self.store,
                    self.token(),
                    region,
                    raw,
                    consent,
                    conversation=path == "/api/assistant/voice",
                )
            else:
                result = self.store.transcribe(self.token(), asr[1], raw, consent)
            return self.send_json(200, result)
        terminal = re.fullmatch(r"/api/payments/terminal/v1/(lookup|receipt)", path)
        if terminal:
            from platform_core.operations.terminal import handle
            return self.send_json(200, handle(self.store, terminal[1], self.headers, self.read_body(2048)))
        if path == "/api/payments/refunds/channel":
            from platform_core.operations import merchant_refunds
            return self.send_json(200, merchant_refunds.perform(self.store, self.token(), self.read_json(512)))
        if path == "/api/payments/refunds/notify/wechat":
            from platform_core.operations import merchant_refunds
            if self.headers.get_content_type() != "application/json":
                raise InvalidMedia("微信退款通知格式无效")
            merchant_refunds.receive_wechat(self.store, self.headers, self.read_body(SMALL_BODY))
            return self.send_json(200, {"code": "SUCCESS", "message": "成功"})
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
            if user["kind"] == "owner" and getattr(self.store, "sample_pending_login", False):
                from platform_core import sample

                if sample.pending(self.store):
                    try:
                        sample.populate(self.store, token)
                    except Exception:
                        self.store.logout(token)
                        raise
                self.store.sample_pending_login = False
            return self.send_json(200, {"user": user}, self.session_cookie(token))
        if path == "/api/auth/logout":
            self.read_json(2048)
            self.store.logout(self.token())
            return self.send_json(200, {"ok": True}, self.session_cookie(None))
        if path == "/api/agent/room-proposals":
            if not self.token():
                raise SignedOut("请先登录")
            body = self.read_json(SMALL_BODY)
            if not {"payload", "revision"} <= body.keys() or body.keys() - {
                "payload",
                "revision",
                "comment",
            }:
                raise ValueError("请提交修订号及区域草稿")
            return self.send_json(
                200,
                self.store.execute(
                    "gw.propose",
                    body["payload"],
                    body["revision"],
                    self.token(),
                    room_bound=True,
                    comment=body.get("comment", ""),
                ),
            )
        if path == "/api/commands":
            if not self.token():
                raise SignedOut("请先登录")
            body = self.read_json(DOCUMENT_BODY)
            if body.get("action") in ("access.create", "access.update"):
                account_payload = body.get("payload")
                if isinstance(account_payload, dict) and "invitation" in account_payload:
                    invitation = account_payload["invitation"]
                    if not isinstance(invitation, dict) or invitation.get("channel") != "sms":
                        raise ValueError("请登记账号本人的手机号")
                elif body["action"] == "access.create":
                    raise ValueError("请登记本人手机号。登录密码由本人设置。")
            if (
                body.get("action") not in ("dossier.document", "dossier.credential", "access.staffContract", "ops.subsidyMaterial")
                and int(self.headers["Content-Length"]) > SMALL_BODY
            ):
                raise ValueError("普通表单上限为 64 KiB")
            result = self.store.execute(
                body.get("action"),
                body.get("payload"),
                body.get("revision"),
                self.token(),
                comment=body.get("comment", ""),
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


def dispatch_scheduled_work(store, stopped):
    from platform_core.care import archive_retention, trial_expiry
    from platform_core.operations import billing_lifecycle

    while not stopped.is_set():
        for maintain in (trial_expiry.maintain, archive_retention.maintain, scheduled_work.tick, billing_lifecycle.tick):
            try:
                maintain(store)
            except Exception:
                logging.getLogger(__name__).exception("定时任务 %s 未完成，将在下一次检查时重试", maintain.__module__)
        stopped.wait(10)


def dispatch_updates(service, stopped):
    while not stopped.is_set():
        try:
            service.automatic()
        except (OSError, ValueError, *OPERATIONAL_ERRORS):
            logging.getLogger(__name__).exception("机构自动更新检查未完成")
        stopped.wait(60)


def main():
    parser = argparse.ArgumentParser(description="医养管理平台 · 机构工作台")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--db", type=Path, default=ROOT / ".local" / "workspace.sqlite3"
    )
    parser.add_argument(
        "--public-origin",
        help="通过机构 HTTPS 反向代理访问时的完整源，例如 https://care.example.org",
    )
    parser.add_argument("--demo-public-tour", action="store_true", help="仅本机人工演示 Roomtour 短信验证")
    parser.add_argument(
        "--initial-data",
        choices=("empty", "demo"),
        default="demo",
        help="仅新数据库使用。empty 创建空白机构，demo 创建演示样本",
    )
    args = parser.parse_args()
    origin = (args.public_origin or "").rstrip("/") or None
    if origin and args.demo_public_tour:
        parser.error("对外访问时不能使用 Roomtour 演示验证码")
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
    initial_password = None
    if (
        not args.db.exists()
        and sys.stdin.isatty()
        and not os.environ.get("NH_OWNER_PASSWORD")
    ):
        from getpass import getpass

        initial_password = getpass("为 Owner 设置初始密码（10–128 字符）：")
        if not 10 <= len(initial_password) <= 128 or initial_password != getpass(
            "请再次输入："
        ):
            parser.error("初始密码长度不符或两次输入不同")
    from platform_core.backups import process_lock

    args.db.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with process_lock(updates.update_directory(args.db), "running-server") as locked:
        if not locked:
            parser.error("此机构资料库已有一个程序在运行")
        serve_institution(args, origin, initial_password)


def serve_institution(args, origin, initial_password):
    from platform_core import sample, sms_delivery
    from platform_core.operations import checkout, merchant_refunds

    try:
        workers, heavy_workers = http_capacity.configured_limits()
        codes, links = sms_delivery.configured()
    except ValueError as error:
        raise SystemExit(str(error)) from None
    store = Store(args.db, initial_data=args.initial_data, prepare_sample=True, initial_owner_password=initial_password,
                  code_senders=codes, reset_link_senders=links)
    owner_password = initial_password or os.environ.get("NH_OWNER_PASSWORD")
    if store.created_workspace and args.initial_data == "demo" and owner_password:
        token, _ = store.login("owner", owner_password)
        try:
            sample.populate(store, token)
        finally:
            store.logout(token)
    store.sample_pending_login = sample.pending(store)
    update_service = updates.UpdateService(store)
    gate = Path(os.environ["NH_UPDATE_GATE"]) if os.environ.get("NH_UPDATE_GATE") else None
    handler = partial(
        Handler, store=store, public_origin=origin, demo_public_tour=args.demo_public_tour,
        update_service=update_service, update_gate=gate, update_boot=os.environ.get("NH_UPDATE_BOOT"),
    )
    with http_capacity.CapacityServer(("127.0.0.1", args.port), handler,
                                      workers=workers, heavy_workers=heavy_workers) as server:
        stopped = Event()
        worker = Thread(target=dispatch_scheduled_work, args=(store, stopped), name="scheduled-work", daemon=True)
        auto = Thread(target=dispatch_updates, args=(update_service, stopped), name="platform-updates", daemon=True)
        refunds = Thread(target=merchant_refunds.poll, args=(store, stopped), name="merchant-refunds", daemon=True)

        def start_services():
            while gate and not gate.is_file():
                if stopped.wait(0.1):
                    return
            if not stopped.is_set():
                store.backups.start()
                store.rounds.start()
                worker.start()
                if checkout.enabled_channels():
                    refunds.start()
                if update_service.managed:
                    auto.start()

        startup = Thread(target=start_services, name="institution-startup", daemon=True)
        startup.start()
        print(f"医养管理平台已启动  http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            stopped.set()
            startup.join(timeout=1)
            if worker.ident is not None:
                worker.join(timeout=12)
            if auto.ident is not None:
                auto.join(timeout=1)
            if refunds.ident is not None:
                refunds.join(timeout=10)
            store.rounds.stop()
            store.backups.stop()


if __name__ == "__main__":
    main()
