"""Read completed nursing receipts in their original room and present routine care together."""

from contextlib import closing
from datetime import date, datetime, timedelta
import json
from zoneinfo import ZoneInfo

from .. import access_policy, campus_access, facility
from .records import lookup

LOCAL = ZoneInfo("Asia/Shanghai")
WINDOWS = (10, 15, 30, 60)
DEFAULT = {"mergeEnabled": True, "windowMinutes": 30}
ROUTINES = {
    **dict.fromkeys(
        (
            "递水",
            "送水",
            "饮水",
            "喝水",
            "协助饮水",
            "饮水协助",
            "日常饮水",
            "饮水照护",
            "陪同饮水",
        ),
        "饮水照护",
    ),
    **dict.fromkeys(
        (
            "吃饭",
            "用餐",
            "就餐",
            "协助进餐",
            "进餐协助",
            "用餐协助",
            "用餐陪护",
            "膳食陪护",
            "陪同就餐",
            "早餐陪护",
            "午餐陪护",
            "晚餐陪护",
        ),
        "用餐陪护",
    ),
}
ROUTINE_KINDS = {"日常照护", "生活照料", "膳食照护", "膳食服务"}


ROUTINE_LABELS = {"water": "饮水照护", "meal": "用餐陪护"}
ATTENTION_TERMS = (
    "医嘱",
    "用药",
    "服药",
    "管饲",
    "鼻饲",
    "吞咽",
    "呛咳",
    "噎",
    "异常",
    "跌倒",
    "摔倒",
    "拒绝",
    "送医",
    "急救",
    "呕吐",
    "不适",
)


def routine_selection(value, kind, title):
    if value not in ("auto", "separate", *ROUTINE_LABELS):
        raise ValueError("请选择有效的时间线归类")
    if value in ROUTINE_LABELS and (
        kind not in ROUTINE_KINDS or any(term in title for term in ATTENTION_TERMS)
    ):
        raise ValueError("请将特殊护理或医嘱项目设为单独展示")
    return value


def routine_label(task):
    mode = task.get("routineActivity", "auto")
    if mode == "separate" or task.get("kind") not in ROUTINE_KINDS:
        return None
    if any(
        word in task["title"] or word in task.get("note", "")
        for word in ATTENTION_TERMS
    ):
        return None
    return (
        ROUTINES.get(task["title"].strip())
        if mode == "auto"
        else ROUTINE_LABELS.get(mode)
    )


def stamp_execution(db, state, task_id, now):
    """Only the server supplies the execution time and the room currently assigned to the bed."""
    task = lookup(state, "tasks", task_id)
    person = lookup(state, "residents", task["residentId"])
    bed = person.get("bedId") or ""
    task["executedAt"] = now.astimezone(LOCAL).isoformat(timespec="seconds")
    task["executionBedId"] = bed
    place = db.execute(
        """SELECT r.id,r.number,f.label,b.name,b.campusName FROM facility_beds beds
           JOIN facility_rooms r ON r.id=beds.roomId JOIN facility_floors f ON f.id=r.floorId
           JOIN facility_building_directory b ON b.id=f.buildingId WHERE beds.bedId=?""",
        (bed,),
    ).fetchone()
    if place:
        task["executionRoomId"] = place[0]
        task["executionRoomLabel"] = " / ".join(
            (place[4], place[3], place[2], place[1] + " 房")
        )


def scope_label(db, state, user, scope, entity_id):
    access_policy.require(user, "care")
    if scope == "resident":
        campus_access.require_resident(db, user, entity_id, state)
        return lookup(state, "residents", entity_id)["name"]
    if scope == "room":
        room = facility.room(db, state, user, entity_id)
        return " / ".join(
            (
                room["campusName"],
                room["buildingName"],
                room["floorLabel"],
                room["number"] + " 房",
            )
        )
    if scope == "work" and not entity_id:
        return "全部获授权的工单"
    raise ValueError("请选择有效的护理时间线")


def configure(db, state, user, values):
    if set(values) not in ({"residentId", *DEFAULT}, {"roomId", *DEFAULT}):
        raise ValueError("请选择一个长辈或房间，并填写合并方式和时间窗口")
    scope = "resident" if "residentId" in values else "room"
    field = scope + "Id"
    entity_id = values[field]
    if not isinstance(entity_id, str) or not entity_id or len(entity_id) > 120:
        raise ValueError("时间线对象无效")
    name = scope_label(db, state, user, scope, entity_id)
    enabled, window = values["mergeEnabled"], values["windowMinutes"]
    if type(enabled) is not bool or type(window) is not int or window not in WINDOWS:
        raise ValueError("请选择有效的合并开关及 10、15、30 或 60 分钟窗口")
    rows = state.setdefault("careTimelineSettings", [])
    key = scope + "/" + entity_id
    record = next((r for r in rows if r["id"] == key), None)
    if record is None:
        record = {"id": key, field: entity_id}
        rows.append(record)
    record.update(mergeEnabled=enabled, windowMinutes=window)
    return f"更新{name}的照护时间线，" + (
        f"按 {window} 分钟合并同类服务" if enabled else "逐笔展示服务"
    )


def settings(index, scope, key):
    item = index.get(scope + "/" + key, DEFAULT)
    return {k: item[k] for k in DEFAULT}


def window_for(index, scope, entity_id, row):
    if scope == "work":
        policies = [
            settings(index, "room", row["roomId"]),
            settings(index, "resident", row["residentId"]),
        ]
    else:
        policies = [settings(index, scope, entity_id)]
    return min(p["windowMinutes"] if p["mergeEnabled"] else 0 for p in policies)


def execution_moment(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(LOCAL) if parsed.tzinfo else None


def grouped(records, index, scope, entity_id):
    groups = []
    active = {}
    for row in sorted(records, key=lambda r: (r["day"], r["at"], r["taskId"])):
        category = row["routine"]
        window = window_for(index, scope, entity_id, row)
        key = (row["day"], row["roomId"], category, window)
        previous = active.get(key)
        mergeable = (
            category and window and row["roomId"] and row["at"] and row["operatorId"]
        )
        if (
            mergeable
            and previous
            and row["epoch"] - previous["firstEpoch"] <= window * 60
        ):
            previous["end"] = row["at"]
            previous["entries"].append(row)
        else:
            group = {
                "day": row["day"],
                "start": row["at"],
                "end": row["at"],
                "firstEpoch": row["epoch"],
                "roomLabel": row["roomLabel"],
                "title": category or row["title"],
                "entries": [row],
            }
            groups.append(group)
            if mergeable:
                active[key] = group
    for group in groups:
        del group["firstEpoch"]
        for entry in group["entries"]:
            del entry["epoch"]
    return sorted(
        groups,
        key=lambda g: (g["day"], g["end"], g["entries"][-1]["taskId"]),
        reverse=True,
    )


def read(store, token, scope, entity_id="", *, day="", offset="0", revision="", q=""):
    from ..store import Conflict

    if not (
        str(offset).isascii() and str(offset).isdecimal() and len(str(offset)) <= 7
    ):
        raise ValueError("页码无效")
    if revision and not (
        isinstance(revision, str)
        and revision.isascii()
        and revision.isdecimal()
        and len(revision) <= 18
    ):
        raise ValueError("时间线版本无效")
    if not isinstance(q, str) or len(q) > 64:
        raise ValueError("请缩短工单搜索词")
    term = q.strip().casefold()
    today = store.now().astimezone(LOCAL).date()
    if day:
        try:
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("请选择有效日期") from None
    lower, upper = (
        (day, day)
        if day
        else ((today - timedelta(days=59)).isoformat(), today.isoformat())
    )
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        user = store.actor(db, token)
        ver, raw = db.execute(
            "SELECT revision,data FROM workspace WHERE id=1"
        ).fetchone()
        state = json.loads(raw)
        label = scope_label(db, state, user, scope, entity_id)
        if revision and int(revision) != ver:
            raise Conflict("记录已更新，请重新载入时间线")
        beds = campus_access.allowed_beds(db, user, include_rooms=True)
        people = campus_access.resident_ids(state, beds) if beds is not None else None
        directory = {
            r[0]: (r[1], " / ".join((r[5], r[4], r[3], r[2] + " 房")))
            for r in db.execute(
                """SELECT beds.bedId,r.id,r.number,f.label,b.name,b.campusName FROM facility_beds beds
               JOIN facility_rooms r ON r.id=beds.roomId JOIN facility_floors f ON f.id=r.floorId
               JOIN facility_building_directory b ON b.id=f.buildingId"""
            )
        }
        names = {p["id"]: p["name"] for p in state["residents"]}
        index = {p["id"]: p for p in state.get("careTimelineSettings", [])}
        entries = []
        for task in state["tasks"]:
            if task["status"] != "已完成":
                continue
            rid = task["residentId"]
            if (
                scope == "resident"
                and rid != entity_id
                or people is not None
                and rid not in people
            ):
                continue
            bed = task.get("executionBedId") or task.get("checkedBedId") or ""
            # Scoped staff require proof of the execution's historical location.
            if beds is not None and bed not in beds:
                continue
            legacy_room, legacy_label = directory.get(bed, ("", ""))
            room = task.get("executionRoomId") or legacy_room
            if scope == "room" and room != entity_id:
                continue
            moment = execution_moment(task.get("executedAt"))
            done_day = (
                moment.date().isoformat() if moment else task.get("completedAt", "")
            )
            if not lower <= (done_day or task["date"]) <= upper:
                continue
            entries.append(
                {
                    "taskId": task["id"],
                    "title": task["title"],
                    "kind": task.get("kind", ""),
                    "routine": routine_label(task),
                    "residentId": rid,
                    "resident": names.get(rid, ""),
                    "bedId": bed,
                    "roomId": room,
                    "roomLabel": task.get("executionRoomLabel") or legacy_label,
                    "operator": task.get("operator") or "",
                    "operatorId": task.get("operatorId", ""),
                    "note": task.get("note", ""),
                    "at": moment.isoformat(timespec="seconds") if moment else "",
                    "epoch": int(moment.timestamp()) if moment else 0,
                    "day": done_day,
                    "planned": " ".join((task["date"], task.get("time", ""))).strip(),
                    "scannedBed": task.get("checkedBedId", ""),
                }
            )
        groups = grouped(entries, index, scope, entity_id)
        if term:
            groups = [
                g
                for g in groups
                if any(
                    term
                    in " ".join(
                        [
                            g["title"],
                            e["title"],
                            e["resident"],
                            e["operator"],
                            e["roomLabel"],
                        ]
                    ).casefold()
                    for e in g["entries"]
                )
            ]
        start = int(offset)
        size = 15
        return {
            "scope": scope,
            "label": label,
            "revision": ver,
            "settings": settings(index, scope, entity_id),
            "groups": groups[start : start + size],
            "totalGroups": len(groups),
            "totalEntries": sum(len(g["entries"]) for g in groups),
            "nextOffset": start + size if len(groups) > start + size else None,
        }
