"""Authenticate and commit a single business action and its scoped audit entry."""

from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from .room_context import room_context, validate_proposal
from .bootstrap import empty_workspace
from . import (
    access,
    activity,
    agents,
    care,
    dossier,
    facility,
    gateways,
    handovers,
    operations,
    provider,
)

TIMEZONE = ZoneInfo("Asia/Shanghai")
SCHEMA_VERSION = 6


class Conflict(Exception):
    """A different client already saved a newer revision."""


class SignedOut(Exception):
    """The session is absent, expired or revoked."""


def clock():
    return datetime.now(TIMEZONE)


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def viewer(db, token):
    user = access.authenticate(db, token) if token else None
    if user is None:
        raise SignedOut("请登录机构工作台")
    return user


class Store:
    def __init__(self, path, now=clock, *, facility_policy=None, initial_data="demo"):
        if initial_data not in ("demo", "empty"):
            raise ValueError("请选择 demo 或 empty 初始化模式")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.now = now
        self.facility_policy = facility_policy
        with closing(self.connect()) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if not 0 <= version <= SCHEMA_VERSION:
                raise RuntimeError(f"数据库版本 {version} 需要迁移")
            db.execute(
                "CREATE TABLE IF NOT EXISTS workspace (id INTEGER PRIMARY KEY CHECK(id = 1), revision INTEGER NOT NULL, data TEXT NOT NULL)"
            )
            activity.init(db)
            if not db.execute("SELECT 1 FROM workspace WHERE id=1").fetchone():
                day = now().date().isoformat()
                data = (
                    operations.seed(day, care.seed(day))
                    if initial_data == "demo"
                    else empty_workspace()
                )
                db.execute("INSERT INTO workspace VALUES (1, 0, ?)", (encode(data),))
            access.init(db)
            if version < 4:
                access.migrate_branding(db)
            dossier.init(db)
            gateways.init(db)
            agents.init(db)
            provider.init(db)
            facility.init(
                db,
                json.loads(
                    db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
                ),
            )
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def actor(self, db, token):
        actor = viewer(db, token)
        if self.facility_policy is not None:
            actor = {**actor, "facilityScope": self.facility_policy(db, actor)}
        return actor

    def connect(self):
        db = sqlite3.connect(self.path, timeout=8)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def login(self, username, password):
        with closing(self.connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                result = access.login(db, username, password)
            except PermissionError:
                db.commit()  # Failed-attempt counters survive the rejected login.
                raise
            db.commit()
            return result

    def logout(self, token):
        with closing(self.connect()) as db, db:
            access.logout(db, token)

    def version(self, token):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            user = self.actor(db, token)
            return {
                "userId": user["id"],
                "today": self.now().date().isoformat(),
                "revision": db.execute(
                    "SELECT revision FROM workspace WHERE id=1"
                ).fetchone()[0],
            }

    def snapshot(self, token):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            user = self.actor(db, token)
            row = db.execute(
                "SELECT revision,data FROM workspace WHERE id=1"
            ).fetchone()
            today = self.now().date().isoformat()
            data = access.project(
                db, json.loads(row["data"]), user, self.facility_policy
            )
            data["selfAccess"] = {
                "permissions": [
                    {"id": grant, "label": access.PERMISSIONS[grant]}
                    for grant in user["permissions"]
                    if grant in access.PERMISSIONS
                ],
                "routes": [
                    route
                    for route in user["routes"]
                    if route not in data["uiSettings"]["hiddenRoutes"]
                ],
            }
            if user["kind"] == "family":
                family_permissions = data["selfAccess"]["permissions"]
                family_permissions.append(
                    {"id": "dossier.relative", "label": "维护本人的亲属资料"}
                )
                if user.get("familyServices"):
                    family_permissions.append(
                        {
                            "id": "familyServices",
                            "label": "查看绑定长者已完成的照护服务",
                        }
                    )
            data["handovers"] = [
                handovers.visible(record, access.has(user, "clinical"))
                for record in data.get("handovers", ())
            ]
            if user.get("facilityScope"):
                data["suggestions"] = [
                    item
                    for item in data["suggestions"]
                    if item.get("runId")
                    and agents.region_visible(db, user, item["runId"])
                ]
            dossier.project(db, data, user, today)
            gateways.project(db, data, user)
            if access.has(user, "assistants"):
                data["agentRuns"] = agents.listing(db, user)
                data["agentCapabilities"] = self.agent_capabilities(db, user)
            logs = (
                activity.page(db, user, limit=100)["rows"]
                if access.has(user, "audit")
                else []
            )
            return {
                "revision": row["revision"],
                "today": today,
                "data": data,
                "audit": logs,
            }

    def branding(self):
        with closing(self.connect()) as db:
            visual = json.loads(
                db.execute(
                    "SELECT visual FROM institution_settings WHERE id=1"
                ).fetchone()[0]
            )
            return {key: visual[key] for key in ("brandName", "institutionName")}

    def access_preview(self, token, payload):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            return access.preview(
                db, self.actor(db, token), payload, self.facility_policy
            )

    def activity(self, token, **filters):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            return activity.page(db, self.actor(db, token), **filters)

    def handover_recipients(self, token):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            return handovers.recipients(db, self.actor(db, token))

    def agent_handover(self, token, run_id, handover_id):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            user = self.actor(db, token)
            access.require(user, "care")
            run = agents.detail(db, user, run_id)
            cited = any(
                handover_id in item["recordIds"]
                for artifact in run["artifacts"]
                if artifact["tool"] == "handover.pending"
                for item in artifact["evidence"]
                if item["source"] == "handovers"
            )
            if not cited:
                raise FileNotFoundError("未找到本次简报可核对的交班")
            state = json.loads(
                db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
            )
            record = next(
                (
                    r
                    for r in state["handovers"]
                    if r["id"] == handover_id and r.get("assigneeId") == user["id"]
                ),
                None,
            )
            if record is None:
                raise FileNotFoundError("未找到本次简报可核对的交班")
            if run["region"]:
                region = {
                    k: run["region"][k] for k in ("buildingId", "floorId", "roomId")
                }
                current = facility.scope(db, state, user, **region)
                if record["residentId"] not in current["residentIds"]:
                    raise FileNotFoundError("长者目前不在该简报的区域内")
            return handovers.visible(record, access.has(user, "clinical"))

    def photo(self, token, doc_id):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            return dossier.photo(db, doc_id, self.actor(db, token))

    def facility_resource(self, token, resource, key="", **filters):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            user = self.actor(db, token)
            state = (
                json.loads(
                    db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
                )
                if resource != "tour"
                else {}
            )
            if resource == "directory":
                return facility.directory(db, state, user)
            if resource == "floor":
                return facility.floor(db, state, user, key)
            if resource == "room":
                return facility.room(db, state, user, key)
            if resource == "search":
                return facility.search(db, state, user, **filters)
            if resource == "tour":
                return facility.tour(db, state, user, **filters)
            if resource == "agent-context":
                access.require(user, "assistants")
                return room_context(
                    db, state, user, filters, self.now().date().isoformat()
                )
            raise FileNotFoundError("未登记的院区资源")

    def tour_media(self, token, path):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            return facility.can_read_media(db, {}, self.actor(db, token), path)

    def agent_capabilities(self, db, user):
        result = agents.capabilities(user)
        result["plan"] = provider.status(db, user, self.now())
        if "rooms" in user["routes"]:
            result["facilityTools"] = [
                {
                    "id": "rooms.search",
                    "method": "GET",
                    "path": "/api/facility/search",
                    "arguments": ["q", "buildingId", "floorId", "roomId", "limit"],
                    "cloudTokens": 0,
                },
                {
                    "id": "rooms.context",
                    "method": "GET",
                    "path": "/api/agent/room-context",
                    "arguments": ["roomId", "limit", "offset"],
                    "cloudTokens": 0,
                },
                {
                    "id": "rooms.tour",
                    "method": "GET",
                    "path": "/api/facility/tour",
                    "arguments": ["buildingId", "floorId", "roomId"],
                    "cloudTokens": 0,
                },
            ]
            if "gw.propose" in access.allowed_actions(user):
                result["facilityTools"].append(
                    {
                        "id": "rooms.propose",
                        "method": "POST",
                        "path": "/api/agent/room-proposals",
                        "arguments": ["roomId", "requestId", "taskId", "note"],
                        "effect": "awaiting_human_confirmation",
                        "cloudTokens": 0,
                    }
                )
        result["businessCommandNames"] = access.allowed_actions(user)
        result["planningModes"] = ["local", "platform"]
        return result

    def agent_resource(self, token, name, run_id=None):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            user = self.actor(db, token)
            access.require(user, "assistants")
            if name == "capabilities":
                return self.agent_capabilities(db, user)
            if name == "runs" and run_id is None:
                return {"runs": agents.listing(db, user)}
            return agents.detail(db, user, run_id)

    def capabilities(self, token, capability=None):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            user = self.actor(db, token)
            catalog = gateways.catalog()
            if user["kind"] != "owner":
                catalog = [
                    r
                    for r in catalog
                    if r["id"] != "deepseek-summary" and not r.get("ownerOnly")
                ]
            if "integrations" not in user["routes"] and user["kind"] != "owner":
                raise PermissionError("没有接口目录权限")
            if capability is None:
                return catalog
            record = next((r for r in catalog if r["id"] == capability), None)
            if record is None:
                raise FileNotFoundError("未登记或无权查看此接口")
            return record

    def plan_agent(self, payload, revision, token):
        def inspect(db):
            actor = self.actor(db, token)
            row = db.execute(
                "SELECT revision,data FROM workspace WHERE id=1"
            ).fetchone()
            if type(revision) is not int or revision != row["revision"]:
                raise Conflict("数据已更新，请核对最新内容后重新提交")
            return actor, agents.preflight(db, json.loads(row["data"]), actor, payload)

        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            _, check = inspect(db)
        if check["prior"]:
            return None
        if check["args"]["scope"] != "auto":
            return {
                "mode": "local",
                "reason": "explicit_scope",
                "model": "",
                "specialistIds": [],
            }

        def authorize(db):
            actor, current = inspect(db)
            if not current["prior"] and current["specs"] != check["specs"]:
                raise PermissionError("协作范围或岗位授权已更新，请重新核对")
            return actor

        return provider.plan(
            self.connect,
            authorize,
            check["args"]["goal"],
            check["request"],
            allowed_specs=check["specs"],
            scope_key=check["fingerprintScope"],
            now=self.now(),
        )

    def execute(self, action, payload, revision, token, *, room_bound=False):
        planning = None
        if (
            action == "agent.start"
            and isinstance(payload, dict)
            and payload.get("planning") == "platform"
        ):
            planning = self.plan_agent(payload, revision, token)
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            user = self.actor(db, token)
            if not isinstance(action, str) or not isinstance(payload, dict):
                raise ValueError("操作及表单内容格式错误")
            row = db.execute(
                "SELECT revision,data FROM workspace WHERE id=1"
            ).fetchone()
            data = json.loads(row["data"])
            access.authorize(user, action, payload, data)
            if user.get("facilityScope") and action in ("ops.review", "ops.suggest"):
                linked = next(
                    (
                        r.get("runId")
                        for r in data["suggestions"]
                        if r["id"] == payload.get("id")
                    ),
                    None,
                )
                if (
                    action == "ops.suggest"
                    or not linked
                    or not agents.region_visible(db, user, linked)
                ):
                    raise PermissionError("请通过授权区域的 Agent 任务办理")
            if type(revision) is not int or revision < 0:
                raise ValueError("缺少有效的数据版本，请刷新页面")
            if row["revision"] != revision:
                raise Conflict("数据已更新，请核对最新内容后重新提交")
            now = self.now()
            today = now.date().isoformat()
            if room_bound:
                if action != "gw.propose":
                    raise ValueError("未登记的区域工具")
                payload = validate_proposal(db, data, user, payload, today)
            previous = activity.locate(db, data, action, payload, user)
            domain = action.partition(".")[0]
            try:
                if action == "care.handover":
                    summary = handovers.create(db, data, payload, user, now)
                elif action == "care.acceptHandover":
                    summary = handovers.accept(data, payload, user, now)
                elif action == "care.withdrawHandover":
                    summary = handovers.withdraw(data, payload, user, now)
                elif domain in ("ops", "care"):
                    fields = dict(payload)
                    actor_fields = {
                        "care.completeTask": "operator",
                        "care.giveMedication": "operator",
                        "care.vital": "operator",
                        "care.resolveVital": "operator",
                        "care.reviewMedication": "reviewer",
                        "care.archive": "reviewer",
                        "care.approvePlan": "reviewer",
                        "care.quality": "reviewer",
                    }
                    if action in actor_fields:
                        fields[actor_fields[action]] = user["displayName"]
                    module = care if domain == "care" else operations
                    summary = module.apply(data, action, fields, today)
                elif domain == "agent":
                    summary, run_id = agents.apply(
                        db, data, action, payload, user, now, revision, planning
                    )
                elif domain == "facility":
                    summary = facility.apply(db, data, action, payload, user, today)
                elif domain == "access":
                    summary = access.apply(
                        db, data, action, payload, user, self.facility_policy
                    )
                elif action == "account.changePassword":
                    summary = access.change_own_password(db, user, payload)
                elif domain in ("gw", "dossier"):
                    module = gateways if domain == "gw" else dossier
                    summary = module.apply(db, data, action, payload, user, today)
                else:
                    raise ValueError("未登记的操作")
            except KeyError as error:
                raise ValueError("操作名称或必填字段无效") from error
            current = activity.locate(db, data, action, payload, user)
            if action == "care.admit":
                current = activity.for_person(data, data["residents"][-1]["id"])
            if domain == "gw":
                current = gateways.audit_context(db, data, action, payload, user)
            if domain == "agent":
                current = agents.audit_context(db, run_id)
            new_revision = revision + 1
            db.execute(
                "UPDATE workspace SET revision=?,data=? WHERE id=1",
                (new_revision, encode(data)),
            )
            activity.write(
                db,
                new_revision,
                now.isoformat(timespec="seconds"),
                action,
                summary,
                user,
                current,
                previous,
            )
            return {"revision": new_revision, "summary": summary}
