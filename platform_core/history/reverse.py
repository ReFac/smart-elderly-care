"""Apply inverses to the exact current fields under the same database writer lock."""

import json
from .capture import MISSING, dump, JSON_COLUMNS
from .. import access_policy as policy


class UndoConflict(ValueError):
    pass


SUPPORTED = {
    "care.addTask": {"tasks"},
    "care.completeTask": {"tasks"},
    "gw.confirm": {"tasks", "gateway_voice"},
    "care.inquire": {"inquiries"},
    "care.timelineSettings": {"careTimelineSettings"},
    "ops.addItem": {"inventory"},
    "ops.shift": {"shifts"},
    "dossier.profile": {"residents", "dossier_profiles"},
    "access.settings": {"institution_settings"},
    "access.mediaSettings": {"media_policy"},
    "backup.policy": {"backup_policy"},
    "facility.updateCampus": {"facility_campuses"},
    "facility.renameBuilding": {"facility_building_campus"},
}
SQL = {
    "dossier_profiles": ("resident_id", {"basic", "household"}),
    "institution_settings": ("id", {"visual"}),
    "media_policy": ("id", {"ocr", "asr"}),
    "backup_policy": ("singleton", {"retention", "upload_mib", "version"}),
    "gateway_voice": ("id", {"status", "reviewer_id", "reviewed_at", "reason"}),
    "facility_campuses": ("id", {"name", "address"}),
    "facility_building_campus": ("buildingId", {"localName"}),
}


def related(db, state, collection, identity, confirmed=""):
    if collection == "careTimelineSettings":
        return False
    if (
        collection == "tasks"
        and db.execute(
            "SELECT 1 FROM gateway_voice WHERE task_id=? AND id<>? LIMIT 1",
            (identity, confirmed),
        ).fetchone()
    ):
        return True

    # Foreign references in business JSON and issued Agent evidence prevent removing a source record.
    def refers(obj):
        if isinstance(obj, dict):
            return any(refers(v) for v in obj.values())
        if isinstance(obj, list):
            return any(refers(v) for v in obj)
        return obj == identity

    for name, rows in state.items():
        for r in rows:
            if name == collection and r.get("id") == identity:
                continue
            if refers(r):
                return True
    return bool(
        db.execute(
            "SELECT 1 FROM agent_runs r,json_tree(r.artifacts) e WHERE e.atom=? LIMIT 1",
            (identity,),
        ).fetchone()
    )


def overlap(first, second):
    if (
        first["collection"] != second["collection"]
        or first["entityId"] != second["entityId"]
    ):
        return False
    left, right = first["path"], second["path"]
    common = min(len(left), len(right))
    return left[:common] == right[:common]


def apply_inverse(db, actor, action, changes, revision, write):
    if not changes or action not in SUPPORTED:
        raise UndoConflict("此提交没有可撤销的字段改动")
    if any(
        c["collection"] not in SUPPORTED[action] or c["kind"] == "order"
        for c in changes
    ):
        raise UndoConflict("该改动含关联凭证，需要在业务模块更正")
    if action == "dossier.profile" and any(
        c["path"][:1] == ["household"] for c in changes
    ):
        policy.require(actor, "relatives")
    if action == "backup.policy":
        # The policy's optimistic concurrency version always advances on a successful write.
        changes = [c for c in changes if c["path"] != ["version"]]
    affected = {(c["collection"], c["entityId"]) for c in changes}
    markers = ",".join("(?,?)" for _ in affected)
    bindings = [v for c, i in sorted(affected) for v in ("entity/" + c, i)]
    later = db.execute(
        f"""SELECT revision,changes FROM history_commits WHERE revision>? AND revision IN (
        SELECT revision FROM history_targets WHERE (kind,entity) IN (VALUES {markers}) AND revision>?)""",
        (revision, *bindings, revision),
    )
    for _, encoded in later:
        if any(overlap(a, b) for b in json.loads(encoded) for a in changes):
            raise UndoConflict("相同字段在此后被修改，请打开最新记录核对")

    state = json.loads(
        db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
    )
    objects = {}
    confirmed = next((i for col, i in affected if col == "gateway_voice"), "")
    if action == "gw.confirm" and not confirmed:
        raise UndoConflict("找不到原语音确认凭证")
    for collection, identity in sorted(affected):
        if collection in SQL:
            key, editable = SQL[collection]
            row = db.execute(
                f"SELECT * FROM {collection} WHERE {key}=?", (identity,)
            ).fetchone()
            if row is None:
                raise UndoConflict("目标记录已不存在")
            obj = dict(row)
            for k in obj.keys() & editable & JSON_COLUMNS:
                obj[k] = json.loads(obj[k])
        else:
            obj = next(
                (r for r in state.get(collection, ()) if r["id"] == identity), None
            )
            if obj is None:
                raise UndoConflict("目标记录已不存在")
        objects[collection, identity] = obj
        if action in ("care.completeTask", "gw.confirm") and collection == "tasks":
            person = next(
                (r for r in state["residents"] if r["id"] == obj.get("residentId")), {}
            )
            risk_words = (
                "服药",
                "给药",
                "用药",
                "注射",
                "换药",
                "医嘱",
                "生命体征",
                "血糖",
                "血压",
                "输液",
                "处置",
            )
            if obj.get("kind") not in (
                "日常照护",
                "生活照护",
                "生活护理",
                "日常护理",
            ) or any(word in obj.get("title", "") for word in risk_words):
                raise UndoConflict("医疗处置或非日常工单须从业务记录更正")
            if person.get("status") != "在住" or (
                obj.get("executionBedId")
                and person.get("bedId") != obj["executionBedId"]
            ):
                raise UndoConflict("长者入住或床位已改变，请核对当前照护记录")
            if related(db, state, collection, identity, confirmed):
                raise UndoConflict("此工单已有后续引用，请从业务记录更正")
            if action == "gw.confirm" and obj.get("voiceProposalId") != confirmed:
                raise UndoConflict("工单与原语音确认凭证不一致")
    for change in changes:
        collection = change["collection"]
        identity = change["entityId"]
        obj = objects[collection, identity]
        path = change["path"]
        if not path:
            if (
                collection == "dossier_profiles"
                and change["kind"] == "add"
                and obj == change["after"]
                and not obj["basic"]
                and not obj["household"]
            ):
                continue
            if collection == "shifts" and any(
                t.get("assignee") == obj.get("staff")
                and t.get("date") == obj.get("date")
                for t in state["tasks"]
            ):
                raise UndoConflict("该日已有向此员工派发的工单，请核对排班")
            if (
                collection in SQL
                or change["kind"] != "add"
                or obj != change["after"]
                or related(db, state, collection, identity)
            ):
                raise UndoConflict("这条记录已被更改或引用")
            state[collection].remove(obj)
            continue
        if collection in SQL and path[0] not in SQL[collection][1]:
            raise UndoConflict("该字段须在业务模块更正")
        parent = obj
        for key in path[:-1]:
            parent = parent.get(key) if isinstance(parent, dict) else None
        if not isinstance(parent, dict) or parent.get(path[-1], MISSING) != change.get(
            "after", MISSING
        ):
            raise UndoConflict("目标字段已有新值，请核对最新记录")
        if collection == "gateway_voice":
            # Keep the signed receipt and its reviewer/time. It can never enter another pending queue.
            if path == ["status"]:
                if change.get("after") != "已确认":
                    raise UndoConflict("语音确认凭证的状态不一致")
                parent["status"] = "已撤销"
            continue
        if "before" in change:
            parent[path[-1]] = change["before"]
        else:
            parent.pop(path[-1])

    if not write:
        return
    for (collection, identity), obj in objects.items():
        if collection in SQL:
            key, editable = SQL[collection]
            touched = sorted(
                {
                    c["path"][0]
                    for c in changes
                    if c["path"]
                    and c["collection"] == collection
                    and c["entityId"] == identity
                }
                & editable
            )
            if (
                collection == "dossier_profiles"
                and not obj["basic"]
                and not obj["household"]
                and any(
                    (c.get("createdRow") or (not c["path"] and c["kind"] == "add"))
                    and c["entityId"] == identity
                    for c in changes
                    if c["collection"] == collection
                )
            ):
                db.execute(
                    "DELETE FROM dossier_profiles WHERE resident_id=?", (identity,)
                )
                continue
            if collection == "backup_policy":
                touched.append("version")
                obj["version"] += 1
            values = [dump(obj[f]) if f in JSON_COLUMNS else obj[f] for f in touched]
            db.execute(
                f"UPDATE {collection} SET "
                + ",".join(f + "=?" for f in touched)
                + f" WHERE {key}=?",
                (*values, identity),
            )
    if any(c not in SQL for c, _ in objects):
        db.execute("UPDATE workspace SET data=? WHERE id=1", (dump(state),))


def check(db, actor, action, changes, revision):
    apply_inverse(db, actor, action, changes, revision, False)


def revert(db, actor, action, changes, revision):
    apply_inverse(db, actor, action, changes, revision, True)
