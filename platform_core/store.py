"""Authenticate and commit a single business action and its scoped audit entry."""

from contextlib import closing
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from threading import BoundedSemaphore, Lock
from zoneinfo import ZoneInfo

from .system_monitor import Presence
from .room_context import room_context, validate_proposal
from .operations import expense_import, subsidies
from .care import timeline as care_timeline
from . import protected_docs, secure_storage, staff_employment, storage_assets
from . import lead_contacts, lead_intake, medical_visits, people_labels, visit_schedule
from . import care_areas, daily_life, med_rounds, medication_reports, resident_health, scheduled_work
from . import permission_requests, visitor_access
from .bootstrap import empty_workspace
from .care import trial_expiry, trial_followups
from . import backups, history, rounds
from .access_policy import can_record_scale
from .care import archive_retention
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


def actor_stamp(user):
    return sha256(json.dumps(user, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Store:
    def __init__(
        self,
        path,
        now=clock,
        *,
        facility_policy=None,
        initial_data="demo",
        code_senders=None,
        reset_link_senders=None,
        initial_owner_password=None,
    ):
        if initial_data not in ("demo", "empty"):
            raise ValueError("请选择 demo 或 empty 初始化模式")
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.storage_key_file, self._storage_master = secure_storage.prepare_database(
            self.path
        )
        self.now = now
        self._daily_maintenance_lock = Lock()
        self._trials_checked = None
        self._archive_checked = None
        self.presence = Presence()
        self.network_probes = BoundedSemaphore(4)
        self.public_submissions = lead_intake.PublicSubmissions()
        self.code_senders = dict(code_senders or {})
        self.reset_link_senders = dict(reset_link_senders or {})
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
            expense_import.init(db)
            subsidies.init(db)
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
            access.init(db, initial_owner_password)
            permission_requests.init(db)
            visitor_access.init(db)
            if version < 4:
                access.migrate_branding(db)
            dossier.init(db)
            medical_visits.init(db)
            med_rounds.init(db)
            medication_reports.init(db)
            resident_health.init(db)
            daily_life.init(db)
            scheduled_work.init(db)
            archive_retention.init(db)
            rounds_family.init(db)
            gateways.init(db)
            agents.init(db)
            from .agents import chat

            chat.init(db)
            provider.init(db)
            data = json.loads(
                db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
            )
            missing = {k: v for k, v in empty_workspace().items() if k not in data}
            if missing:
                data.update(missing)
                db.execute("UPDATE workspace SET data=? WHERE id=1", (encode(data),))
            facility.init(db, data)
            care_areas.init(db)
            backups.init(db)
            from . import updates

            updates.init(db)
            rounds.init(db, self.now())
            history.prune(db, self.now())
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        trial_expiry.maintain(self)
        archive_retention.maintain(self)
        self.backups = backups.BackupService(self)
        self.rounds = rounds.RoundService(self)

    def actor(self, db, token):
        actor = viewer(db, token)
        if (
            actor["kind"] == "family"
            and db.execute(
                "SELECT 1 FROM archive_expirations WHERE resident=?",
                (actor.get("residentId"),),
            ).fetchone()
        ):
            actor = {**actor, "familyServices": False, "portalScopes": []}
        if self.facility_policy is not None and not actor.get("registeredCustomer"):
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
        trial_expiry.maintain(self)
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            user = self.actor(db, token)
            self.presence.touch(access._token_hash(token))
            return {
                "userId": user["id"],
                "actorStamp": actor_stamp(user),
                "groupActivityDue": daily_life.pending_count(db, None, user, self.now()),
                "today": self.now().date().isoformat(),
                "revision": db.execute(
                    "SELECT revision FROM workspace WHERE id=1"
                ).fetchone()[0],
            }

    def navigation_version(self, token):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            user = self.actor(db, token)
            return {
                "userId": user["id"],
                "actorStamp": actor_stamp(user),
                "revision": db.execute("SELECT revision FROM workspace WHERE id=1").fetchone()[0],
                "today": self.now().date().isoformat(),
            }

    def snapshot(self, token):
        trial_expiry.maintain(self)
        archive_retention.maintain(self)
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            user = self.actor(db, token)
            self.presence.touch(access._token_hash(token))
            stamp = actor_stamp(user)
            row = db.execute(
                "SELECT revision,data FROM workspace WHERE id=1"
            ).fetchone()
            today = self.now().date().isoformat()
            state = json.loads(row["data"])
            state["residents"] = [
                r
                for r in state["residents"]
                if r["status"] != archive_retention.EXPIRED
            ]
            lead_contacts.reconcile_callbacks(db, state, self.now())
            data = access.project(db, state, user, self.facility_policy)
            from .operations import billing_lifecycle, contract_renewal

            billing_lifecycle.project(state, data, user, today)
            contract_renewal.project(state, data, user, today)
            if access.has(user, "intake") or access.has(user, "finance"):
                from .operations.admission_finance import project_status

                project_status(state, data)
            data["shifts"] = [{k: v for k, v in row.items() if k != "area"} for row in data.get("shifts", ())]
            if "beds" in user["routes"]:
                data["bedDirectory"] = care_areas.bed_directory(db, [bed["id"] for bed in data["beds"]])
            from .operations import dispatch

            dispatch.project(db, state, user, data)
            trial_followups.project(db, state, user, data)
            lead_contacts.project(db, state, user, data)
            data["pendingPermissionRequests"] = permission_requests.pending_count(db, state, user, self.now())
            if not data["leadCampuses"] and "leads" in user["routes"]:
                user = {**user, "routes": [route for route in user["routes"] if route != "leads"]}
                data["user"] = user
                data["allowedActions"] = [action for action in data["allowedActions"] if not action.startswith("leads.")]
            if access.has(user, "finance"):
                from .operations.charges import CATEGORIES, UNITS
                from .operations.billing_cycles import pending_periods

                from .agents import revenue

                data["cashOverview"] = revenue.overview(data, today)
                data["chargeCatalog"] = {"categories": CATEGORIES, "units": UNITS}
                data["billingDue"] = pending_periods(data, today)
            if (
                access.has(user, "intake")
                or access.has(user, "residents")
                or access.has(user, "care")
                or access.has(user, "clinical")
            ):
                shown_beds = {b["id"] for b in data["beds"]}
                data["bedLocations"] = {
                    r[0]: [r[1], r[2], r[3]]
                    for r in db.execute(
                        "SELECT beds.bedId,b.campusName,b.name,f.label FROM "
                        + facility.ROOM_TABLE
                        + " JOIN facility_beds beds ON beds.roomId=r.id"
                    )
                    if r[0] in shown_beds
                }
            if can_record_scale(user):
                from .care.scales import CATALOG

                data["careScale"] = CATALOG
            from . import identity

            data["identityContacts"] = identity.contacts(db, user["id"])
            data["identityChannels"] = sorted(identity.senders(self))
            from .agents.change_review import category

            data["agentReviewDomains"] = {
                a: category(a) for a in data["allowedActions"] if category(a)
            }
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
            from .portal import SCOPES, is_customer

            if user["kind"] == "family" and not is_customer(user):
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
                            "label": "查看绑定长辈已完成的照护服务",
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
            if access.has(user, "longCare") and user["kind"] != "family":
                from . import long_care

                data["longCareCatalog"] = long_care.catalog()
                data["longCareEvents"] = [
                    {**e, "displayStatus": long_care.status_text(e, today)}
                    for e in data.get("longCareEvents", ())
                ]
            dossier.project(db, data, user, today)
            dossier.project_roster(db, data, user)
            medical_visits.project(db, data, user)
            rounds_family.project(db, data, user)
            beds = campus_access.allowed_beds(db, user, include_rooms=True)
            if user["kind"] in ("owner", "staff") and any(
                access.has(user, grant) for grant in ("care", "clinical")
            ):
                data["roundsNoticeCount"] = rounds.inbox_query(
                    db, state, beds, access.has(user, "clinical"), today
                ).fetchone()[0]
            people = (
                campus_access.resident_ids(state, beds, user)
                if beds is not None
                else None
            )
            if beds is not None:
                data["tasks"] = [
                    t
                    for t in data.get("tasks", [])
                    if t.get("residentId") in people
                    and (not t.get("executionBedId") or t["executionBedId"] in beds)
                ]
            gateways.project(db, data, user, beds, people)
            if user["kind"] in ("owner", "staff") and access.has(user, "voice"):
                from .provider import speech

                data["assistantVoice"] = {
                    **speech.agent_capability(db, self.now()),
                    "path": "/api/assistant/voice",
                }
            if access.has(user, "assistants"):
                data["agentRuns"] = agents.listing(db, user)
                data["agentCapabilities"] = self.agent_capabilities(db, user)
            logs = (
                activity.page(db, user, limit=100)["rows"]
                if access.has(user, "audit")
                else []
            )
            people_labels.project(db, state, data, user, logs)
            data["groupActivityDue"] = daily_life.pending_count(db, state, user, self.now())
            return {
                "revision": row["revision"],
                "actorStamp": stamp,
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
        from .operations.checkout import authorized_order, cached_payment_link

        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            _, data, order = authorized_order(self, db, token, order_id)
            return {"orderId": order["id"], "status": order["status"], **cached_payment_link(db, data, order, self.now())}

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

    def trial_assignees(self, token, resident_id):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            user = self.actor(db, token)
            state = json.loads(
                db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
            )
            return people_labels.recipient_positions(db, {
                "recipients": trial_followups.recipients(
                    db, state, user, resident_id, self.facility_policy
                )
            })

    def handover_recipients(self, token):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            result = handovers.recipients(db, self.actor(db, token), self.facility_policy)
            return people_labels.recipient_positions(db, result)

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
                    raise FileNotFoundError("长辈目前不在该简报的区域内")
            return handovers.visible(record, access.has(user, "clinical"))

    def photo(self, token, doc_id):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            user = self.actor(db, token)
            campus_access.require_document(db, user, doc_id)
            return dossier.photo(db, doc_id, user)

    def inspect_pdf(self, token, resident_id, raw):
        from . import pdf_original

        with closing(self.connect()) as db:
            user = self.actor(db, token)
            access.require(user, "medical.write")
            state = json.loads(db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0])
            campus_access.require_resident(db, user, resident_id, state)
            if not any(r["id"] == resident_id for r in state["residents"]):
                raise FileNotFoundError("找不到长辈档案")
        return {"pageCount": pdf_original.pages(raw)}

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

    def dossier_summary_draft(self, token, resident_id, *, generate=False):
        from .dossier_summary import review_facts
        from .provider.generation import summarize

        def current():
            with closing(self.connect()) as db, db:
                db.execute("BEGIN")
                user = self.actor(db, token)
                access.require(user, "medical")
                access.require(user, "clinical")
                state = json.loads(
                    db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
                )
                campus_access.require_resident(db, user, resident_id, state)
                return dossier.summary_draft(db, state, user, resident_id), user["id"]

        draft, actor_id = current()
        if not generate or draft["summary"]:
            return draft
        # A single verified evidence set shares one metered response across reviewers.
        text = summarize(
            self,
            "dossier-summary",
            draft["fingerprint"],
            "根据护理等级、已复核的文书类型和照护记录数量，撰写简短的档案核对提示。"
            "具体病情只在院内原文中，由签认人核对补写。",
            review_facts(draft),
            feature="dossier.summary",
            attributed_actor=actor_id,
        )
        after, _ = current()
        if after["fingerprint"] != draft["fingerprint"]:
            raise ValueError("摘要依据已经变化，请重新生成并核对")
        if not after["summary"]:
            after["summary"] = text
        return after

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
                room = facility.room(db, state, user, key)
                room.update(care_areas.room_areas(db, [room["id"]]).get(room["id"], {}))
                return room
            if resource == "rooms":
                return facility.rooms(db, state, user, **filters)
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
                    "id": "rooms.list",
                    "method": "GET",
                    "path": "/api/facility/rooms",
                    "arguments": ["bedCount", "limit", "campusId", "buildingId", "floorId", "roomId"],
                    "navigation": "#beds?tab=all&capacity={bedCount}&limit={limit}",
                    "cloudTokens": 0,
                },
                {
                    "id": "rooms.floor",
                    "method": "GET",
                    "path": "/api/facility/floors/{floorId}",
                    "arguments": ["floorId"],
                    "navigation": "#beds?tab=plan&floor={floorId}",
                    "cloudTokens": 0,
                },
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
            if access.has(user, "facility.manage"):
                result["facilityTools"].extend((
                    {
                        "id": "rooms.edit",
                        "navigation": "#beds?tab=plan&edit=room&room={roomId}",
                        "arguments": ["roomId"],
                        "action": "facility.updateRoom",
                        "effect": "awaiting_human_confirmation",
                    },
                    {
                        "id": "rooms.editLayout",
                        "navigation": "#beds?tab=plan&edit=layout&floor={floorId}",
                        "arguments": ["floorId"],
                        "action": "facility.setLayout",
                        "effect": "awaiting_human_confirmation",
                    },
                ))
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
        result["planningModes"] = ["platform"]
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

    def bill_preview(self, token, payload, revision):
        from .operations.billing import quote_bill

        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            user = self.actor(db, token)
            access.require(user, "finance")
            row = db.execute(
                "SELECT data,revision FROM workspace WHERE id=1"
            ).fetchone()
            if type(revision) is not int or revision != row["revision"]:
                raise Conflict("机构记录已更新，请重新打开收费核算")
            if not isinstance(payload, dict):
                raise ValueError("请填写收费项目")
            state = json.loads(row["data"])
            access.authorize(user, "ops.bill", payload, state)
            campus_access.authorize_command(db, user, "ops.bill", payload, state)
            return quote_bill(state, payload, self.now().date().isoformat())

    def admission_preview(self, token, body):
        from .care import residency
        from .operations import admission_finance

        if set(body) != {"action", "payload", "revision"} or not isinstance(body["payload"], dict):
            raise ValueError("请选择长辈档案、床位和入住日期")
        action, payload = body["action"], body["payload"]
        entries = {"care.admit": residency.admit, "care.confirmStay": residency.confirm_stay}
        if not isinstance(action, str) or action not in entries:
            raise ValueError("请选择入住办理方式")
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            user = self.actor(db, token)
            current, raw = db.execute("SELECT revision,data FROM workspace WHERE id=1").fetchone()
            if type(body["revision"]) is not int or current != body["revision"]:
                raise Conflict("机构记录已更新，请重新核对入住明细")
            state = json.loads(raw)
            access.authorize(user, action, payload, state)
            campus_access.authorize_command(db, user, action, payload, state)
            admission_finance.authorize(user, payload)
            quote = entries[action](state, payload, self.now().date().isoformat(), preview=True)
            return {**quote, "revision": current}

    def plan_agent(self, payload, revision, token):
        from .agents import narrative

        return narrative.prepare(self, token, payload, revision)

    def execute(
        self, action, payload, revision, token, *, room_bound=False, comment=""
    ):
        trial_expiry.maintain(self)
        comment = history.comment_text(comment)
        if action == "dossier.ocr":
            from . import document_ocr

            document_ocr.prepare(self, token, payload, revision)
        planning = None
        if isinstance(payload, dict) and action in ("agent.start", "ops.suggest"):
            if action == "agent.start":
                planning = self.plan_agent(payload, revision, token)
            else:
                from .agents import narrative

                planning = narrative.prepare(
                    self, token, payload, revision, suggestion=True
                )
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
            if action in ("care.admit", "care.confirmStay"):
                from .operations.admission_finance import authorize as authorize_fees

                authorize_fees(user, payload)
            if action in ("ops.publishNotice", "ops.supplyOrder", "care.addTask"):
                from .operations.dispatch import verify_proposal

                verify_proposal(self, db, token, user, action, payload)
            if action == "care.register":
                visible = campus_access.projection(db, data, user)
                name = payload.get("name")
                if not name and payload.get("inquiryId"):
                    name = next(
                        (
                            q["name"]
                            for q in visible["inquiries"]
                            if q["id"] == payload["inquiryId"]
                        ),
                        "",
                    )
                matches = any(
                    r["status"] == archive_retention.ARCHIVED
                    and r["name"] == str(name or "").strip()
                    for r in visible["residents"]
                )
                if matches and payload.get("acknowledgeArchive") is not True:
                    raise ValueError(
                        "已有同名归档老人，请先核对身份再确认建立独立档案。"
                    )
            if action == "portal.feedback":
                archive_retention.writable(data, user.get("residentId"))
            if action.startswith("dossier.") or action == "care.archive":
                rid = payload.get("residentId")
                if not rid and action == "dossier.relative":
                    subject = (
                        user
                        if user["kind"] == "family"
                        else access.account(db, payload.get("accountId"))
                    )
                    rid = (subject or {}).get("residentId")
                if rid:
                    archive_retention.writable(data, rid)
            history.watch(db, action)
            previous = activity.locate(db, data, action, payload, user)
            permission_target = None
            domain = action.partition(".")[0]
            try:
                if action == "leads.capacity":
                    if set(payload) != {"campusId", "capacity"}:
                        raise ValueError("请选择院区和并行接待席位数")
                    campus_id = lead_contacts.require_campus(db, user, payload["campusId"])
                    visit_schedule.configure(data, campus_id, payload["capacity"], now)
                    summary = "已更新院区并行接待席位"
                elif domain == "leads":
                    summary = lead_contacts.command(db, data, user, action, payload, now)
                elif action in care_areas.ACTIONS:
                    summary = care_areas.command(db, data, user, action, payload, now)
                elif action in subsidies.ACTIONS:
                    summary = subsidies.command(db, data, user, action, payload, now)
                elif action == "ops.dischargeSettlement":
                    from .operations.discharge_settlement import settle

                    summary = settle(data, payload, user, today)
                elif action == "ops.mergeStockItem":
                    from . import inventory_dedupe

                    summary = inventory_dedupe.merge(self, data, user, payload, today)
                elif action == "ops.residentBillingPolicy":
                    from .operations.admission_finance import configure

                    summary = configure(data, payload)
                elif action in scheduled_work.ACTIONS:
                    summary = scheduled_work.command(db, data, user, action, payload, now)
                elif action == "care.confirmScheduledMeal":
                    from . import scheduled_meals

                    summary = scheduled_meals.confirm(db, data, user, payload, now)
                elif action == "care.confirmMedRound":
                    summary = med_rounds.command(db, data, user, action, payload, now)
                elif action in ("portal.reportMedication", "care.reportMedication"):
                    summary = medication_reports.record(db, data, user, payload, now)
                elif action == "dossier.confirmVisit":
                    summary = medical_visits.confirm(db, data, payload, user, now)
                elif action == "dossier.document":
                    summary = medical_visits.archive_document(db, data, payload, user, now)
                elif action == "dossier.linkVisitDocument":
                    summary = medical_visits.link_document(db, data, payload, user, now)
                elif action == "care.proposeGroupActivity":
                    summary = daily_life.propose(db, data, user, payload, now)
                elif action == "care.confirmGroupActivity":
                    summary = daily_life.confirm(db, data, user, payload, now)
                elif action in ("care.healthNote", "dossier.signHealthIntro", "dossier.recordChronic"):
                    summary = resident_health.command(db, data, user, action, payload, now)
                elif action == "care.timelineSettings":
                    summary = care_timeline.configure(db, data, user, payload)
                elif action in ("access.staffContract", "access.staffPayday"):
                    summary = staff_employment.apply(db, user, action, payload, now, self.facility_policy)
                elif action == "care.endTrial":
                    trial_followups.assign(
                        db, data, user, payload, now, self.facility_policy
                    )
                    fields = {k: payload[k] for k in ("residentId", "reason")}
                    summary = care.apply(data, action, fields, today)
                elif action == "care.finishTrialFollowup":
                    summary = trial_followups.complete(db, data, user, payload, now)
                elif action == "care.reassignTrialFollowup":
                    summary = trial_followups.reassign(
                        db, data, user, payload, now, self.facility_policy
                    )
                elif action == "access.trialSettings":
                    summary = trial_followups.configure(data, payload)
                elif action == "care.handover":
                    summary = handovers.create(
                        db, data, payload, user, now, self.facility_policy
                    )
                elif action == "care.acceptHandover":
                    summary = handovers.accept(data, payload, user, now)
                elif action == "care.withdrawHandover":
                    summary = handovers.withdraw(data, payload, user, now)
                elif action in (
                    "ops.publishNotice",
                    "ops.supplyOrder",
                    "ops.finishSupplyOrder",
                ):
                    from .operations import dispatch

                    summary = dispatch.apply(db, data, action, payload, user, now)
                elif action == "ops.importExpenses":
                    summary, changed = expense_import.apply(db, data, payload, user, now)
                    if not changed:
                        return {"revision": revision, "summary": "所选凭证已经登记"}
                elif action == "ops.suggest":
                    suggestion = planning["artifacts"][0]
                    data["suggestions"].insert(0, suggestion)
                    summary = "已生成待人工核对的云端建议"
                elif domain in ("ops", "care"):
                    fields = dict(payload)
                    if action in ("care.inquire", "care.register", "ops.shift"):
                        fields["campusId"] = facility.selected_campus(db, user, fields)
                    if action == "care.assess":
                        rid = fields.get("residentId")
                        fields["matchCampusId"] = facility.resident_campus(db, data, rid)
                        resident = next((p for p in data["residents"] if p["id"] == rid), None)
                        fields["matchAreaStaff"] = care_areas.responsible_staff(db, resident["bedId"]) if resident and resident.get("bedId") else ()
                    actor_fields = {
                        "care.assess": "operator",
                        "care.revisePlan": "operator",
                        "care.addMedication": "operator",
                        "care.receiveMedication": "operator",
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
                    if action == "care.receiveMedication":
                        fields["nowLocal"] = now.isoformat(timespec="seconds")
                        fields["operatorId"] = user["id"]
                    module = care if domain == "care" else operations
                    if action == "care.addTask":
                        from .operations.dispatch import source_reference

                        source = source_reference(data, fields, user)
                    summary = module.apply(data, action, fields, today)
                    if action == "care.approvePlan":
                        care.plan_items.sync_rules(db, data, fields["planId"], user, now)
                    elif action in ("care.discharge", "care.endTrial"):
                        care.plan_items.disable_rules(db, fields["residentId"], user, now)
                    if action == "care.addTask":
                        data["tasks"][-1].update(source)
                elif action == "ltci.record":
                    from . import long_care

                    summary = long_care.record(data, payload, user, today)
                elif domain == "agent":
                    summary, run_id = agents.apply(
                        db, data, action, payload, user, now, revision, planning
                    )
                elif domain == "facility":
                    summary = facility.apply(db, data, action, payload, user, today)
                elif action == "access.mediaSettings":
                    from .provider import media

                    summary = media.configure(db, user, payload)
                elif action == permission_requests.CREATE:
                    summary, permission_target = permission_requests.create(self, db, data, user, payload, now)
                elif action == permission_requests.REVIEW:
                    try:
                        summary, permission_target = permission_requests.review(self, db, data, user, payload, now)
                    except (access.SignaturePasswordDenied, access.LoginThrottled):
                        db.commit()  # Persist failed re-authentication without approving the request.
                        raise
                elif action == permission_requests.EDIT:
                    summary, permission_target = permission_requests.edit(self, db, data, user, payload, now)
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
            if action == "care.dateArchive":
                archive_retention.clear_due(db, data, today, payload["residentId"])
            if action in ("care.admit", "care.confirmStay", "dossier.profile", "dossier.relative",
                          "access.create", "access.update", "access.status", permission_requests.EDIT):
                lead_contacts.reconcile_callbacks(db, data, now)
            current = activity.locate(db, data, action, payload, user)
            if permission_target:
                current = activity.for_person(data, permission_target)
            if action == "care.register":
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
