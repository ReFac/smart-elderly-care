"""Authenticate and commit a single business action and its scoped audit entry."""

from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from . import access, activity, agents, care, dossier, gateways, operations

TIMEZONE = ZoneInfo("Asia/Shanghai")
SCHEMA_VERSION = 4


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
    def __init__(self, path, now=clock):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.now = now
        with closing(self.connect()) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3, SCHEMA_VERSION):
                raise RuntimeError(f"数据库版本 {version} 需要迁移")
            db.execute(
                "CREATE TABLE IF NOT EXISTS workspace (id INTEGER PRIMARY KEY CHECK(id = 1), revision INTEGER NOT NULL, data TEXT NOT NULL)"
            )
            activity.init(db)
            if not db.execute("SELECT 1 FROM workspace WHERE id=1").fetchone():
                day = now().date().isoformat()
                data = operations.seed(day, care.seed(day))
                db.execute("INSERT INTO workspace VALUES (1, 0, ?)", (encode(data),))
            access.init(db)
            if version < 4:
                access.migrate_branding(db)
            dossier.init(db)
            gateways.init(db)
            agents.init(db)
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

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
            user = viewer(db, token)
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
            user = viewer(db, token)
            row = db.execute(
                "SELECT revision,data FROM workspace WHERE id=1"
            ).fetchone()
            today = self.now().date().isoformat()
            data = access.project(db, json.loads(row["data"]), user)
            dossier.project(db, data, user, today)
            gateways.project(db, data, user)
            if access.has(user, "assistants"):
                data["agentRuns"] = agents.listing(db, user)
                data["agentCapabilities"] = agents.capabilities(user)
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

    def activity(self, token, **filters):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            return activity.page(db, viewer(db, token), **filters)

    def photo(self, token, doc_id):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            return dossier.photo(db, doc_id, viewer(db, token))

    def agent_resource(self, token, name, run_id=None):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            user = viewer(db, token)
            access.require(user, "assistants")
            if name == "capabilities":
                return agents.capabilities(user)
            if name == "runs" and run_id is None:
                return {"runs": agents.listing(db, user)}
            return agents.detail(db, user, run_id)

    def capabilities(self, token, capability=None):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            user = viewer(db, token)
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

    def execute(self, action, payload, revision, token):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            user = viewer(db, token)
            if not isinstance(action, str) or not isinstance(payload, dict):
                raise ValueError("操作及表单内容格式错误")
            row = db.execute(
                "SELECT revision,data FROM workspace WHERE id=1"
            ).fetchone()
            data = json.loads(row["data"])
            access.authorize(user, action, payload, data)
            if type(revision) is not int or revision < 0:
                raise ValueError("缺少有效的数据版本，请刷新页面")
            if row["revision"] != revision:
                raise Conflict("数据已更新，请核对最新内容后重新提交")
            now = self.now()
            today = now.date().isoformat()
            previous = activity.locate(db, data, action, payload, user)
            domain = action.partition(".")[0]
            try:
                if domain in ("ops", "care"):
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
                        db, data, action, payload, user, now, revision
                    )
                elif domain == "access":
                    summary = access.apply(db, data, action, payload, user)
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
