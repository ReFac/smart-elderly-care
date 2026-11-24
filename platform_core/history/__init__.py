"""Revision-addressed business changes, current access checks and a 60-day detail window."""

from contextlib import closing
from datetime import date, datetime
import json
import re
from zoneinfo import ZoneInfo

from .capture import RETENTION_DAYS, WINDOW, collect, dump, watch
from .. import access_policy as policy, campus_access

__all__ = ["init", "prune", "record", "watch", "page", "detail", "undo", "comment_text"]


def init(db):
    from ..agents import change_review

    db.execute("""CREATE TABLE IF NOT EXISTS history_commits(
        revision INTEGER PRIMARY KEY REFERENCES audit(revision), recordedAt INTEGER NOT NULL,
        comment TEXT NOT NULL, source TEXT NOT NULL, undoOf INTEGER UNIQUE,
        rooms TEXT NOT NULL, people TEXT NOT NULL, changes TEXT NOT NULL)""")
    change_review.init(db)
    db.execute("""CREATE TABLE IF NOT EXISTS history_targets(
        kind TEXT NOT NULL,entity TEXT NOT NULL,revision INTEGER NOT NULL REFERENCES history_commits(revision) ON DELETE CASCADE,
        PRIMARY KEY(kind,entity,revision))""")
    db.execute(
        "CREATE INDEX IF NOT EXISTS history_targets_revision ON history_targets(revision)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS history_age ON history_commits(recordedAt)")
    db.execute("""CREATE TRIGGER IF NOT EXISTS history_no_update BEFORE UPDATE ON history_commits
        BEGIN SELECT RAISE(ABORT,'变更记录不可覆盖'); END""")


def prune(db, now):
    db.execute(
        "DELETE FROM history_commits WHERE recordedAt<?",
        (int(now.timestamp()) - WINDOW,),
    )


def comment_text(value):
    if (
        not isinstance(value, str)
        or len(value) > 240
        or any(ord(ch) < 32 and ch != "\n" for ch in value)
    ):
        raise ValueError("变更说明须为 240 字以内的文本")
    return value.strip()


def record(
    db, revision, timestamp, action, actor, current, previous, comment="", undo_of=None
):
    changes, people, rooms, campuses = collect(db, current, previous)
    if action == "dossier.ocr":
        published = [
            c["entityId"]
            for c in changes
            if c["collection"] == "dossier_ocr_jobs"
            and c["path"] == ["published"]
            and c.get("after") == 1
        ]
        for did in published:
            data = db.execute(
                "SELECT result FROM dossier_ocr_jobs WHERE document_id=?", (did,)
            ).fetchone()[0]
            if data:
                changes.append(
                    {
                        "collection": "dossier_ocr_jobs",
                        "entityId": did,
                        "path": ["publishedResult"],
                        "kind": "add",
                        "after": json.loads(data),
                    }
                )
    if action in ("account.changePassword", "access.password"):
        updated = db.execute(
            "SELECT ident FROM temp.history_capture WHERE tbl='accounts' LIMIT 1"
        ).fetchone()
        changes.append(
            {
                "collection": "accounts",
                "entityId": updated[0] if updated else actor["id"],
                "path": ["credential"],
                "kind": "edit",
                "before": "此前凭据",
                "after": "已重新设置",
            }
        )
    source = (
        "agent"
        if action.startswith("agent.") or actor["id"] == "rounds-agent"
        else "system"
        if actor["id"] in ("platform-operator", "archive-service")
        or actor["id"].startswith("channel-")
        else "human"
    )
    at = datetime.fromisoformat(timestamp)
    prune(db, at)
    db.execute(
        "INSERT INTO history_commits VALUES(?,?,?,?,?,?,?,?)",
        (
            revision,
            int(at.timestamp()),
            comment_text(comment),
            source,
            undo_of,
            dump(rooms),
            dump(people),
            dump(changes),
        ),
    )
    from ..agents import change_review

    change_review.inspect(
        db,
        revision,
        action,
        actor,
        current.get("residentId") or previous.get("residentId") or "",
    )
    seen = list(
        dict.fromkeys(
            (c["collection"], c["entityId"]) for c in changes if c["entityId"]
        )
    )
    db.executemany(
        "INSERT INTO history_targets VALUES(?,?,?)",
        [
            (kind, key, revision)
            for kind, keys in (
                ("room", rooms),
                ("resident", people),
                ("campus", campuses),
            )
            for key in keys
        ]
        + [("entity/" + kind, key, revision) for kind, key in seen],
    )
    safe = actor.get("kind") == "owner"
    return [
        {"collection": c, "entityId": i}
        for c, i in seen
        if safe
        or c
        in (
            "residents",
            "beds",
            "tasks",
            "careTimelineSettings",
            "inquiries",
            "inventory",
            "shifts",
            "bills",
            "payments",
            "assessments",
            "plans",
            "leaves",
            "followups",
            "vitals",
            "medications",
        )
    ][:16]


SELECT = """SELECT a.revision,a.at,a.action,a.summary,a.actorId,a.actorName,a.room,a.previousRoom,a.residentId,a.agentRunId,
 h.comment,h.source,h.undoOf,h.rooms,h.people,
 (SELECT json_group_array(t.entity) FROM history_targets t WHERE t.revision=a.revision AND t.kind='campus') AS campuses,
 (SELECT u.revision FROM history_commits u WHERE u.undoOf=a.revision) AS undoneBy,
 (SELECT a2.action FROM audit a2 WHERE a2.revision=h.undoOf) AS originalAction
 FROM audit a LEFT JOIN history_commits h ON h.revision=a.revision"""
AGE = "COALESCE(h.recordedAt,unixepoch(a.at))>=?"


class Reader:
    def __init__(self, store, db, user):
        if user["kind"] not in ("owner", "staff"):
            raise PermissionError("仅在岗工作人员可查看最近改动")
        self.db = db
        self.user = user
        self.cutoff = int(store.now().timestamp()) - WINDOW
        self.allowed_beds = campus_access.allowed_beds(db, user, include_rooms=True)
        self.archived_ids = {
            r[0]
            for r in db.execute("""SELECT json_extract(value,'$.id') FROM workspace,json_each(data,'$.residents')
            WHERE json_extract(value,'$.status') IN ('已退住','归档到期')""")
        }
        self.people = self.rooms = None
        if self.allowed_beds is not None:
            state = json.loads(
                db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
            )
            self.people = campus_access.resident_ids(state, self.allowed_beds, user)
            # Empty rooms should remain addressable even when they have no bed yet.
            from .. import facility

            acl = facility._access(db, user, environment=True)
            where, args = facility._restrictions(acl)
            self.rooms = {
                r[0]
                for r in db.execute(
                    "SELECT r.id FROM " + facility.ROOM_TABLE + where, args
                )
            }
        self.import_revision = (
            db.execute(
                "SELECT MAX(revision) FROM audit WHERE action='backup.apply'"
            ).fetchone()[0]
            or 0
        )

    def visible(self, row):
        if self.user["kind"] == "owner":
            return True
        own = row["actorId"] == self.user["id"]
        if not own and not policy.has(self.user, "audit"):
            return False
        action = row["originalAction"] or row["action"]
        if self.allowed_beds is not None:
            if not row["source"]:
                return False
            people = set(json.loads(row["people"] or "[]"))
            if not people and row["residentId"]:
                people.add(row["residentId"])
            rooms = set(json.loads(row["rooms"] or "[]"))
            if not people <= self.people or not rooms <= self.rooms:
                return False
            if not (people or rooms):
                local = self.user.get("facilityScope", {})
                broad = set(local) <= {"institutionId", "campusIds"}
                campuses = set(json.loads(row["campuses"]))
                if not (own and action == "account.changePassword") and not (
                    broad and campuses and campuses <= set(local.get("campusIds", ()))
                ):
                    return False
        if action == "media.agentVoice":
            from ..provider.speech import can_read_agent_history

            return own and can_read_agent_history(self.db, self.user, row["revision"])
        if action == "family.consent":
            return policy.has(self.user, "relatives") and policy.has(
                self.user, "family.share"
            )
        if action == "media.asr":
            return (
                own and policy.has(self.user, "voice") and policy.has(self.user, "care")
            )
        if action.startswith("agent."):
            from .. import agents

            if not row["agentRunId"]:
                return False
            try:
                agents.detail(self.db, self.user, row["agentRunId"])
                return True
            except (PermissionError, ValueError, FileNotFoundError):
                return False
        if action not in policy.ACTION_GRANTS or not policy.has(
            self.user, policy.ACTION_GRANTS[action]
        ):
            return own and action == "account.changePassword"
        # Recheck composite role requirements; an archived summary may also carry sensitive text.
        if action in ("gw.propose", "gw.confirm", "gw.dismiss"):
            return own and policy.has(self.user, "care")
        if action.startswith("dossier.") and action != "dossier.profile":
            if not policy.has(self.user, "medical"):
                return False
        if action in (
            "dossier.signSummary",
            "dossier.reviewDocument",
        ) and not policy.has(self.user, "clinical"):
            return False
        return True

    def by_revision(self, revision):
        if type(revision) is not int or revision <= 0:
            raise ValueError("请选择有效的改动编号")
        row = self.db.execute(
            SELECT + " WHERE a.revision=? AND " + AGE, (revision, self.cutoff)
        ).fetchone()
        if row is None or not self.visible(row):
            raise FileNotFoundError("未找到可查阅的 60 天内改动")
        return row

    def can_read_field(self, c):
        if self.user["kind"] == "owner":
            return True
        name = c["collection"]
        if name == "family_round_preferences":
            return policy.has(self.user, "relatives") and policy.has(
                self.user, "family.share"
            )
        if name == "assessments":
            return policy.can_record_scale(self.user)
        if name in (
            "dossier_documents",
            "dossier_ocr_jobs",
            "dossier_document_reviews",
        ):
            return policy.has(self.user, "medical")
        if name in policy.COLLECTION_GRANTS and name != "handovers":
            return policy.has(self.user, policy.COLLECTION_GRANTS[name])
        if name == "residents":
            return c["path"] in (["name"], ["age"], ["bedId"], ["status"])
        if name == "dossier_profiles":
            return bool(c["path"]) and (
                c["path"][0] == "basic" or policy.has(self.user, "relatives")
            )
        reveal = name in ("careTimelineSettings", "bedMoves", "leaves")
        return reveal

    def visible_comment(self, row):
        text = row["comment"] or ""
        if self.user["kind"] == "owner" or not text:
            return text
        # Free text can quote any of the changed fields. Recheck the scope of the original
        # action as well when a compensation comment refers to the earlier write.
        versions = [row["revision"]]
        if row["undoOf"]:
            versions.append(row["undoOf"])
        for revision in versions:
            changes = self.raw_changes(revision)
            if not changes or not all(self.can_read_field(c) for c in changes):
                return ""
        return text

    def metadata(self, row):
        from .reverse import SUPPORTED

        people = json.loads(row["people"] or "[]")
        undo_reason = ""
        if row["undoneBy"]:
            undo_reason = "这项改动已撤销"
        elif not row["source"]:
            undo_reason = "早期记录只有审计摘要"
        elif row["revision"] <= self.import_revision:
            undo_reason = "此后已导入机构数据，请核对当前版本"
        elif (
            row["action"].startswith("dossier.")
            and (set(people) | {row["residentId"]}) & self.archived_ids
        ):
            undo_reason = "归档老人的资料只读"
        elif row["action"] not in SUPPORTED:
            undo_reason = "已留存业务凭证，可在对应模块办理更正"
        elif self.user["kind"] != "owner" and row["actorId"] != self.user["id"]:
            undo_reason = "仅经办人或总管理员可撤销"
        rooms = json.loads(row["rooms"] or "[]")
        people = json.loads(row["people"] or "[]")
        return {
            **{
                k: row[k]
                for k in (
                    "revision",
                    "at",
                    "action",
                    "summary",
                    "actorId",
                    "actorName",
                    "room",
                    "previousRoom",
                    "undoneBy",
                    "undoOf",
                )
            },
            "source": row["source"] or "legacy",
            "comment": self.visible_comment(row),
            "residentId": row["residentId"] or next(iter(people), ""),
            "residentIds": people,
            "roomId": next(iter(rooms), ""),
            "roomIds": rooms,
            "undoable": not undo_reason,
            "undoReason": undo_reason,
        }

    def raw_changes(self, revision):
        row = self.db.execute(
            "SELECT changes FROM history_commits WHERE revision=?", (revision,)
        ).fetchone()
        return json.loads(row[0]) if row else []

    def details(self, row):
        from ..agents import change_review
        from .reverse import check, UndoConflict

        result = self.metadata(row)
        changes = self.raw_changes(row["revision"])
        if (
            row["action"] == "backup.apply"
            and self.user["kind"] == "owner"
            and self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='backup_restores'"
            ).fetchone()
        ):
            restore = self.db.execute(
                "SELECT rollbackPoint FROM backup_restores WHERE revision=?",
                (row["revision"],),
            ).fetchone()
            if restore:
                result["rollbackPointId"] = restore[0]
        if result["undoable"]:
            try:
                check(self.db, self.user, row["action"], changes, row["revision"])
            except (UndoConflict, PermissionError) as e:
                result.update(undoable=False, undoReason=str(e))
        # For a limited role, labels remain available; protected fields require their current read grant.
        for c in changes:
            c["field"] = "/".join(c["path"])
            if self.user["kind"] == "owner":
                continue
            if not self.can_read_field(c):
                for k in ("before", "after"):
                    if k in c:
                        c[k] = "依当前岗位隐藏"
        return {
            **result,
            "changes": changes,
            "agentReview": change_review.result(self.db, row["revision"]),
        }


def page(
    store,
    token,
    *,
    residentId="",
    roomId="",
    actorId="",
    before=None,
    limit=40,
    q="",
    day="",
):
    for v in (residentId, roomId, actorId):
        if not isinstance(v, str) or len(v) > 150:
            raise ValueError("筛选编号无效")
    if (
        type(limit) is not int
        or not 1 <= limit <= 100
        or before is not None
        and (type(before) is not int or before <= 0)
    ):
        raise ValueError("分页参数无效")
    if not isinstance(q, str) or len(q) > 120 or any(ord(ch) < 32 for ch in q):
        raise ValueError("搜索文字须在 120 字以内")
    if (
        not isinstance(day, str)
        or day
        and not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day)
    ):
        raise ValueError("筛选日期使用 YYYY-MM-DD")
    if day:
        selected = date.fromisoformat(day)
        midnight = datetime(
            selected.year,
            selected.month,
            selected.day,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        )
        start = int(midnight.timestamp())
    query = q.strip().casefold()
    exact = re.fullmatch(r"v([1-9][0-9]{0,17})", query)
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        reader = Reader(store, db, store.actor(db, token))
        filters, params = [AGE], [reader.cutoff]
        if day:
            filters.append(
                "COALESCE(h.recordedAt,unixepoch(a.at)) >= ? AND COALESCE(h.recordedAt,unixepoch(a.at)) < ?"
            )
            params.extend((start, start + 86400))
        if exact:
            filters.append("a.revision=?")
            params.append(int(exact[1]))
        for value, clause in (
            (actorId, "a.actorId=?"),
            (
                roomId,
                "a.revision IN (SELECT revision FROM history_targets WHERE kind='room' AND entity=?)",
            ),
            (before, "a.revision<?"),
        ):
            if value:
                filters.append(clause)
                params.append(value)
        if residentId:
            filters.append(
                "(a.residentId=? OR a.revision IN (SELECT revision FROM history_targets WHERE kind='resident' AND entity=?))"
            )
            params.extend((residentId, residentId))
        rows = []
        for row in db.execute(
            SELECT + " WHERE " + " AND ".join(filters) + " ORDER BY a.revision DESC",
            params,
        ):
            if reader.visible(row):
                item = reader.metadata(row)
                # Search only text exposed in this authorized projection.
                if (
                    query
                    and not exact
                    and not any(
                        query in item[key].casefold() for key in ("summary", "comment")
                    )
                ):
                    continue
                rows.append(item)
                if len(rows) > limit:
                    break
        return {
            "rows": rows[:limit],
            "nextBefore": rows[limit - 1]["revision"] if len(rows) > limit else None,
            "retentionDays": RETENTION_DAYS,
        }


def detail(store, token, revision):
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        reader = Reader(store, db, store.actor(db, token))
        return reader.details(reader.by_revision(revision))


def undo(store, token, target, expected, comment=""):
    from .. import activity
    from ..store import Conflict
    from ..secure_storage import INTEGRITY_ERRORS
    from .reverse import revert, UndoConflict

    note = comment_text(comment)
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        actor = store.actor(db, token)
        reader = Reader(store, db, actor)
        row = reader.by_revision(target)
        at = store.now()
        revision = db.execute("SELECT revision FROM workspace WHERE id=1").fetchone()[0]
        if type(expected) is not int or revision != expected:
            raise Conflict("数据已更新，请重新核对后撤销")
        meta = reader.metadata(row)
        if not meta["undoable"]:
            raise PermissionError(meta["undoReason"])
        watch(db, "history.undo")
        try:
            revert(db, actor, row["action"], reader.raw_changes(target), target)
        except UndoConflict as e:
            raise Conflict(str(e)) from None
        except INTEGRITY_ERRORS:
            raise Conflict("新记录已占用原名称或有关联，请核对当前数据") from None
        db.execute("UPDATE workspace SET revision=revision+1 WHERE id=1")
        summary = "撤销第 " + str(target) + " 次改动 · " + row["summary"]
        current = {
            "residentId": row["residentId"],
            "room": row["room"],
            "roomId": meta["roomId"],
        }
        affected = activity.write(
            db,
            revision + 1,
            at.isoformat(timespec="seconds"),
            "history.undo",
            summary,
            actor,
            current,
            {},
            comment=note,
            undo_of=target,
        )
        return {"revision": revision + 1, "summary": summary, "affected": affected}
