"""Authenticate and commit a single business action and its scoped audit entry."""

from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .room_context import room_context, validate_proposal
from .care import timeline as care_timeline
from . import protected_docs, secure_storage, storage_assets
from .bootstrap import empty_workspace
from . import backups, history, rounds
from .access_policy import can_record_scale
from . import (
    access,
    activity,
    agents,
    campus_access,
    care,
    dossier,
    rounds_family,
    facility,
    gateways,
    handovers,
    operations,
    provider,
)

TIMEZONE = ZoneInfo("Asia/Shanghai")
SCHEMA_VERSION = 9


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
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.storage_key_file, self._storage_master = secure_storage.prepare_database(
            self.path
        )
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
            storage_assets.init(db)
            protected_docs.init(db)
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
            rounds_family.init(db)
            gateways.init(db)
            agents.init(db)
            provider.init(db)
            data = json.loads(
                db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
            )
            missing = {k: v for k, v in empty_workspace().items() if k not in data}
            if missing:
                data.update(missing)
                db.execute("UPDATE workspace SET data=? WHERE id=1", (encode(data),))
            facility.init(db, data)
            backups.init(db)
            rounds.init(db, self.now())
            history.prune(db, self.now())
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self.backups = backups.BackupService(self)
        self.rounds = rounds.RoundService(self)

    def actor(self, db, token):
        actor = viewer(db, token)
        if self.facility_policy is not None:
            actor = {
                **actor,
                "facilityScope": campus_access.effective(
                    actor, self.facility_policy(db, actor)
                ),
            }
        if campus_access.bound(actor):
            actor["permissions"] = [
                g for g in actor["permissions"] if access.has(actor, g)
            ]
            actor["routes"] = access.resolve_routes(actor)
        return actor

    def connect(self):
        return secure_storage.open_database(self.path, self._storage_master)

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
            state = json.loads(row["data"])
            data = access.project(db, state, user, self.facility_policy)
            if can_record_scale(user):
                from .care.scales import CATALOG

                data["careScale"] = CATALOG
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
                from .portal import SCOPES

                family_permissions = data["selfAccess"]["permissions"]
                family_permissions.extend(
                    {"id": k, "label": SCOPES[k]} for k in user["portalScopes"]
                )
                if user.get("portalSelf"):
                    family_permissions.append(
                        {"id": "family.consent", "label": "管理本人巡查简报的分享授权"}
                    )
                else:
                    family_permissions.append(
                        {
                            "id": "family.subscribe",
                            "label": "管理本账号简报订阅与收件箱",
                        }
                    )
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
                if not record.get("draftScope")
                or user["kind"] == "owner"
                or user["id"] in (record.get("senderId"), record.get("assigneeId"))
            ]
            if user.get("facilityScope"):
                data["suggestions"] = [
                    item
                    for item in data["suggestions"]
                    if item.get("runId")
                    and agents.region_visible(db, user, item["runId"])
                ]
            dossier.project(db, data, user, today)
            rounds_family.project(db, data, user)
            beds = campus_access.allowed_beds(db, user, include_rooms=True)
            if user["kind"] in ("owner", "staff") and any(
                access.has(user, grant) for grant in ("care", "clinical")
            ):
                data["roundsNoticeCount"] = rounds.inbox_query(
                    db, state, beds, access.has(user, "clinical"), today
                ).fetchone()[0]
            people = (
                campus_access.resident_ids(state, beds) if beds is not None else None
            )
            if beds is not None:
                data["tasks"] = [
                    t
                    for t in data.get("tasks", [])
                    if t.get("residentId") in people
                    and (not t.get("executionBedId") or t["executionBedId"] in beds)
                ]
            gateways.project(db, data, user, beds, people)
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

    def payment_channels(self, token):
        from .operations.checkout import enabled_channels

        with closing(self.connect()) as db:
            access.require(self.actor(db, token), "finance")
            return {"channels": enabled_channels()}

    def payment_order_status(self, token, order_id):
        from .operations.checkout import authorized_order

        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            _, _, order = authorized_order(self, db, token, order_id)
            return {"orderId": order["id"], "status": order["status"]}

    def payment_checkout(self, token, order_id):
        from .operations.checkout import open_code

        return open_code(self, token, order_id)

    def access_preview(self, token, payload):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            return access.preview(
                db, self.actor(db, token), payload, self.facility_policy
            )

    def history(self, token, **filters):
        return history.page(self, token, **filters)

    def history_change(self, token, revision):
        return history.detail(self, token, revision)

    def undo_change(self, token, target_revision, revision, *, comment=""):
        return history.undo(self, token, target_revision, revision, comment)

    def activity(self, token, **filters):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            return activity.page(db, self.actor(db, token), **filters)

    def handover_recipients(self, token):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            return handovers.recipients(db, self.actor(db, token), self.facility_policy)

    def handover_draft(self, token, receiver_id, resident_id=""):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            actor = self.actor(db, token)
            access.require(actor, "care")
            receiver = handovers.recipient(db, actor, receiver_id, self.facility_policy)
            state = json.loads(
                db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
            )
            return handovers.draft(
                db, state, actor, receiver, resident_id, self.now().date().isoformat()
            )

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
                    k: run["region"].get(k, "")
                    for k in ("campusId", "buildingId", "floorId", "roomId")
                }
                current = facility.scope(db, state, user, **region)
                if record["residentId"] not in current["residentIds"]:
                    raise FileNotFoundError("长者目前不在该简报的区域内")
            return handovers.visible(record, access.has(user, "clinical"))

    def photo(self, token, doc_id):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            user = self.actor(db, token)
            campus_access.require_document(db, user, doc_id)
            return dossier.photo(db, doc_id, user)

    def voice_proposal(self, token, proposal_id):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            actor = self.actor(db, token)
            row = gateways.pending_voice(db, actor, proposal_id)
            return {"transcript": row["transcript"], "note": row["note"]}

    def transcribe(self, token, task_id, raw, consent):
        from .provider import speech

        return speech.recognize(self, token, task_id, raw, consent)

    def document_ocr_detail(self, token, doc_id):
        from . import document_ocr

        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            user = self.actor(db, token)
            campus_access.require_document(db, user, doc_id)
            return document_ocr.detail(db, user, doc_id)

    def dossier_summary_draft(self, token, resident_id):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            user = self.actor(db, token)
            access.require(user, "medical")
            access.require(user, "clinical")
            state = json.loads(
                db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
            )
            campus_access.require_resident(db, user, resident_id, state)
            return dossier.summary_draft(db, state, user, resident_id)

    def portal_history(self, token, scope, offset, revision):
        from . import portal

        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            user = self.actor(db, token)
            if user["kind"] != "family" or scope not in user["portalScopes"]:
                raise PermissionError("该账号未获此项查阅授权")
            row = db.execute(
                "SELECT data, revision FROM workspace WHERE id=1"
            ).fetchone()
            if row["revision"] != revision:
                raise Conflict("记录已更新，请刷新服务页重新查看")
            return portal.history(json.loads(row["data"]), user, scope, offset)

    def report_version(self, token, report_id, version):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            access.require(self.actor(db, token), "reports")
            state = json.loads(
                db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
            )
            report = next((r for r in state["reports"] if r["id"] == report_id), {})
            item = next(
                (s for s in report.get("submissions", []) if s["version"] == version),
                None,
            )
            if not item:
                raise FileNotFoundError("未找到已冻结的报送版本")
            site = db.execute(
                "SELECT id FROM facility_site WHERE singleton=1"
            ).fetchone()
            return {
                "schemaVersion": "ankang.civil.monthly.v1",
                "institutionId": site[0],
                "recipient": item["recipient"],
                "submissionRef": item["submissionRef"],
                "sentOn": item["sentOn"],
                "dataset": item["snapshot"],
            }

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
            if not facility.can_read_media(db, {}, self.actor(db, token), path):
                raise FileNotFoundError("该环境场景尚未发布")
            return storage_assets.read_tour(db, path)

    def agent_capabilities(self, db, user):
        result = agents.capabilities(user)
        result["plan"] = provider.status(db, user, self.now())
        if access.has(user, "voice") and agents.specialists(user):
            from .provider import speech

            result["voiceInput"] = speech.agent_capability(db, self.now())
        if "rooms" in user["routes"]:
            result["facilityTools"] = [
                {
                    "id": "rooms.search",
                    "method": "GET",
                    "path": "/api/facility/search",
                    "arguments": [
                        "q",
                        "campusId",
                        "buildingId",
                        "floorId",
                        "roomId",
                        "limit",
                    ],
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
                    "arguments": ["campusId", "buildingId", "floorId", "roomId"],
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

    def execute(
        self, action, payload, revision, token, *, room_bound=False, comment=""
    ):
        comment = history.comment_text(comment)
        if action == "dossier.ocr":
            from . import document_ocr

            document_ocr.prepare(self, token, payload, revision)
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
            campus_access.authorize_command(db, user, action, payload, data)
            history.watch(db, action)
            previous = activity.locate(db, data, action, payload, user)
            domain = action.partition(".")[0]
            try:
                if action == "care.timelineSettings":
                    summary = care_timeline.configure(db, data, user, payload)
                elif action == "care.handover":
                    summary = handovers.create(
                        db, data, payload, user, now, self.facility_policy
                    )
                elif action == "care.acceptHandover":
                    summary = handovers.accept(data, payload, user, now)
                elif action == "care.withdrawHandover":
                    summary = handovers.withdraw(data, payload, user, now)
                elif domain in ("ops", "care"):
                    fields = dict(payload)
                    if action in ("care.inquire", "ops.shift"):
                        fields["campusId"] = facility.selected_campus(db, user, fields)
                    if action == "care.assess":
                        fields["matchCampusId"] = facility.resident_campus(
                            db, data, fields.get("residentId")
                        )
                    actor_fields = {
                        "care.assess": "operator",
                        "care.addMedication": "operator",
                        "care.screen": "operator",
                        "care.scheduleFollowup": "operator",
                        "care.finishFollowup": "operator",
                        "care.refer": "operator",
                        "care.receiveReferral": "operator",
                        "care.referralConsent": "operator",
                        "care.exportReferral": "operator",
                        "care.publishDrugRule": "operator",
                        "care.retireDrugRule": "operator",
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
                    if action == "care.completeTask":
                        fields["operatorId"] = user["id"]
                    if action in ("care.giveMedication", "care.addMedication"):
                        fields["nowLocal"] = now.strftime("%Y-%m-%dT%H:%M")
                    module = care if domain == "care" else operations
                    summary = module.apply(data, action, fields, today)
                elif domain == "agent":
                    summary, run_id = agents.apply(
                        db, data, action, payload, user, now, revision, planning
                    )
                elif domain == "facility":
                    summary = facility.apply(db, data, action, payload, user, today)
                elif action == "access.mediaSettings":
                    from .provider import media

                    summary = media.configure(db, user, payload)
                elif domain == "access":
                    summary = access.apply(
                        db, data, action, payload, user, self.facility_policy
                    )
                elif action == "account.changePassword":
                    summary = access.change_own_password(db, user, payload)
                elif domain == "family":
                    summary = rounds_family.apply(db, data, action, payload, user, now)
                elif action == "portal.feedback":
                    from . import portal

                    summary = portal.feedback(data, user, payload, today)
                elif domain in ("gw", "dossier"):
                    module = gateways if domain == "gw" else dossier
                    summary = module.apply(db, data, action, payload, user, today)
                else:
                    raise ValueError("未登记的操作")
            except KeyError as error:
                raise ValueError("操作名称或必填字段无效") from error
            if action == "care.completeTask":
                care_timeline.stamp_execution(db, data, payload["taskId"], now)
            elif action == "gw.confirm":
                task_id = db.execute(
                    "SELECT task_id FROM gateway_voice WHERE id=?",
                    (payload["proposalId"],),
                ).fetchone()[0]
                care_timeline.stamp_execution(db, data, task_id, now)
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
            affected = activity.write(
                db,
                new_revision,
                now.isoformat(timespec="seconds"),
                action,
                summary,
                user,
                current,
                previous,
                comment=comment,
            )
            result = {
                "revision": new_revision,
                "summary": summary,
                "affected": affected,
            }
            if action == "agent.start":
                result["runId"] = run_id
            return result
