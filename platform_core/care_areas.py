"""Building-specific care responsibilities and the effective area of each room."""

from collections import defaultdict
from contextlib import closing
import json
import re
from unicodedata import normalize
from uuid import uuid4

from . import access, access_policy as policy, facility

GRANT = "care.areas"
ACTIONS = ("care.areaSave", "care.areaArchive", "care.areaMap", "care.areaAssign")
MAPPINGS = {
    "floors": ("care_area_floors", "floorId"),
    "rooms": ("care_area_rooms", "roomId"),
}
IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,100}")


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS care_areas (
        id TEXT PRIMARY KEY, buildingId TEXT NOT NULL REFERENCES facility_buildings(id),
        parentId TEXT, name TEXT NOT NULL, nameKey TEXT NOT NULL, archivedAt TEXT NOT NULL DEFAULT '',
        createdAt TEXT NOT NULL, updatedAt TEXT NOT NULL, updatedBy TEXT NOT NULL,
        UNIQUE (id,buildingId),
        FOREIGN KEY (parentId,buildingId) REFERENCES care_areas(id,buildingId))""")
    db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS care_area_live_name
        ON care_areas(buildingId,COALESCE(parentId,''),nameKey) WHERE archivedAt=''""")
    for table, column, places in (
        ("care_area_floors", "floorId", "facility_floors"),
        ("care_area_rooms", "roomId", "facility_rooms"),
    ):
        db.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
            {column} TEXT PRIMARY KEY REFERENCES {places}(id),
            buildingId TEXT NOT NULL, areaId TEXT NOT NULL,
            FOREIGN KEY (areaId,buildingId) REFERENCES care_areas(id,buildingId))""")
        db.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_lookup ON {table}(buildingId,areaId)"
        )
    db.execute("""CREATE TABLE IF NOT EXISTS care_area_staff (
        staffId TEXT NOT NULL REFERENCES accounts(id), buildingId TEXT NOT NULL, areaId TEXT NOT NULL,
        PRIMARY KEY (staffId,areaId),
        FOREIGN KEY (areaId,buildingId) REFERENCES care_areas(id,buildingId))""")
    db.execute(
        "CREATE INDEX IF NOT EXISTS care_area_staff_lookup ON care_area_staff(buildingId,areaId)"
    )


def _allowed(user):
    return user["kind"] in ("owner", "staff") and any(
        policy.has(user, name) for name in (*facility.READ_GRANTS, GRANT)
    )


def _may_manage(user):
    scope = user.get("facilityScope", {})
    return (
        user["kind"] in ("owner", "staff")
        and policy.has(user, GRANT)
        and not any(key in scope for key in ("floorIds", "roomIds"))
    )


def _fields(payload, required, optional=()):
    if not isinstance(payload, dict) or not set(required) <= payload.keys() <= set(
        required
    ) | set(optional):
        raise ValueError("请核对区域设置的提交字段")


def _identifier(raw, *, optional=False):
    if optional and raw == "":
        return raw
    if not isinstance(raw, str) or not IDENTIFIER.fullmatch(raw):
        raise ValueError("请选择有效的楼栋、区域或人员")
    return raw


def _items(values):
    if not isinstance(values, list) or len(values) > 2000:
        raise ValueError("请选择有效的区域、楼层或房间")
    ids = [_identifier(item) for item in values]
    if len(set(ids)) != len(ids):
        raise ValueError("请移除重复选项")
    return ids


def _directory(db, state, user):
    acl = facility._access(db, user, environment=True)
    return facility._directory(db, state, user, acl)["buildings"], acl


def _building(buildings, key):
    return next((item for item in buildings if item["id"] == key), None)


def _rooms(db, acl, key):
    return {r["id"]: r for r in facility._meta(db, acl, buildingId=key)}


def _floors(db, acl, key):
    return {r["id"]: r for r in facility._floor_rows(db, acl, buildingId=key)}


def _areas(db, key):
    return {
        r["id"]: dict(r)
        for r in db.execute(
            """SELECT id,buildingId,parentId,name,createdAt,updatedAt FROM care_areas
               WHERE buildingId=? AND archivedAt='' ORDER BY nameKey,id""",
            (key,),
        )
    }


def _chain(areas, key):
    chain = []
    seen = set()
    while key and key in areas:
        if key in seen:
            raise ValueError("区域层级存在循环")
        seen.add(key)
        current = areas[key]
        chain.append(current)
        key = current.get("parentId")
    return list(reversed(chain))


def _path(chain):
    return " / ".join(item["name"] for item in chain)


def _map(db, key, category):
    table, column = MAPPINGS[category]
    return dict(
        db.execute(
            f"""SELECT m.{column},m.areaId FROM {table} m
                          JOIN care_areas a ON a.id=m.areaId
                          WHERE m.buildingId=? AND a.archivedAt=''""",
            (key,),
        )
    )


def _write_map(db, key, category, replacements):
    table, column = MAPPINGS[category]
    db.executemany(
        f"DELETE FROM {table} WHERE buildingId=? AND {column}=?",
        [(key, place) for place, area in replacements if not area],
    )
    db.executemany(
        f"""INSERT INTO {table}({column},buildingId,areaId) VALUES(?,?,?)
            ON CONFLICT({column}) DO UPDATE SET areaId=excluded.areaId
            WHERE {table}.buildingId=excluded.buildingId""",
        [(place, key, area) for place, area in replacements if area],
    )


def _check_area(areas, key):
    if key not in areas:
        raise ValueError("所选区域不在当前楼栋，或已归档")


def _save(db, key, areas, places, payload, user, stamp):
    _fields(payload, ("buildingId", "name", "parentId"), ("id", "floorIds", "roomIds"))
    area = _identifier(payload.get("id", ""), optional=True)
    parent = _identifier(payload["parentId"], optional=True)
    name = facility._text(payload["name"], "区域名称", 60)
    name_key = normalize("NFKC", name).casefold()
    if area:
        _check_area(areas, area)
    if parent:
        _check_area(areas, parent)
        if area and any(item["id"] == area for item in _chain(areas, parent)):
            raise ValueError("上级区域不能选择自身或下属区域")
    if db.execute(
        """SELECT 1 FROM care_areas
        WHERE buildingId=? AND parentId IS ? AND nameKey=? AND archivedAt='' AND id<>?""",
        (key, parent or None, name_key, area),
    ).fetchone():
        raise ValueError("同一楼栋的同一级已有这个区域名称")

    changes = {}
    for category, field in (("floors", "floorIds"), ("rooms", "roomIds")):
        if field in payload:
            selected = _items(payload[field])
            if not places[category].keys() >= set(selected):
                raise PermissionError("请选择当前楼栋内的楼层或房间")
            changes[category] = selected

    if area:
        db.execute(
            """UPDATE care_areas SET parentId=?,name=?,nameKey=?,updatedAt=?,updatedBy=?
                    WHERE buildingId=? AND id=?""",
            (parent or None, name, name_key, stamp, user["id"], key, area),
        )
        result = "已更新照护区域"
    else:
        area = "area-" + uuid4().hex
        db.execute(
            """INSERT INTO care_areas(id,buildingId,parentId,name,nameKey,createdAt,updatedAt,updatedBy)
            VALUES(?,?,?,?,?,?,?,?)""",
            (area, key, parent or None, name, name_key, stamp, stamp, user["id"]),
        )
        result = "已新建照护区域"
    for category, selected in changes.items():
        table, _ = MAPPINGS[category]
        db.execute(f"DELETE FROM {table} WHERE buildingId=? AND areaId=?", (key, area))
        _write_map(db, key, category, [(place, area) for place in selected])
    return result + "「" + name + "」"


def _map_changes(db, key, areas, places, payload):
    _fields(payload, ("buildingId",), ("floors", "rooms"))
    if not any(category in payload for category in MAPPINGS):
        raise ValueError("请选择要划分的楼层或房间")
    changes = {}
    for category in MAPPINGS:
        rows = payload.get(category, [])
        if not isinstance(rows, list) or len(rows) > 2000:
            raise ValueError("请选择要划分的楼层或房间")
        pairs = {}
        for row in rows:
            _fields(row, ("id", "areaId"))
            place = _identifier(row["id"])
            if place not in places[category]:
                raise PermissionError("请选择当前楼栋内的楼层或房间")
            if place in pairs:
                raise ValueError("同一楼层或房间只能设置一个直接区域")
            item = _identifier(row["areaId"], optional=True)
            if item:
                _check_area(areas, item)
            pairs[place] = item
        changes[category] = list(pairs.items())
    for category, replacements in changes.items():
        _write_map(db, key, category, replacements)
    return "已更新区域的楼层和房间划分"


def _archive(db, key, areas, payload, user, stamp):
    _fields(payload, ("buildingId", "id"))
    item = _identifier(payload["id"])
    _check_area(areas, item)
    if any(child["parentId"] == item for child in areas.values()):
        raise ValueError("请先迁出或归档该区域的所有子区域")
    for table, _ in MAPPINGS.values():
        db.execute(f"DELETE FROM {table} WHERE buildingId=? AND areaId=?", (key, item))
    db.execute(
        "DELETE FROM care_area_staff WHERE buildingId=? AND areaId=?", (key, item)
    )
    db.execute(
        "UPDATE care_areas SET archivedAt=?,updatedAt=?,updatedBy=? WHERE buildingId=? AND id=?",
        (stamp, stamp, user["id"], key, item),
    )
    return "已归档照护区域「" + areas[item]["name"] + "」"


def _selectable(account, building):
    campuses = account.get("facilityScope", {}).get("campusIds")
    return (
        account["kind"] == "staff"
        and account["enabled"]
        and not account["activationPending"]
        and any(policy.has(account, name) for name in ("care", "clinical"))
        and (campuses is None or building["campusId"] in campuses)
    )


def _assign(db, building, areas, payload):
    _fields(payload, ("buildingId", "staffId", "areaIds"))
    staff = _identifier(payload["staffId"])
    selected = _items(payload["areaIds"])
    for key in selected:
        _check_area(areas, key)
    account = access.account(db, staff)
    if not account or account["kind"] != "staff":
        raise ValueError("请选择照护人员")
    key = building["id"]
    if not _selectable(account, building) and (
        selected
        or not db.execute(
            "SELECT 1 FROM care_area_staff WHERE buildingId=? AND staffId=?",
            (key, staff),
        ).fetchone()
    ):
        raise PermissionError("请选择此分院的在岗照护人员")
    db.execute(
        "DELETE FROM care_area_staff WHERE buildingId=? AND staffId=?", (key, staff)
    )
    db.executemany(
        "INSERT INTO care_area_staff VALUES(?,?,?)",
        [(staff, key, area) for area in selected],
    )
    return f"已更新「{account['displayName']}」在本楼栋的照护区域"


def command(db, state, user, action, payload, now):
    if not _may_manage(user):
        raise PermissionError("此账号没有完整楼栋的区域管理授权")
    if action not in ACTIONS or not isinstance(payload, dict):
        raise ValueError("区域设置操作无效")
    key = _identifier(payload.get("buildingId"))
    buildings, acl = _directory(db, state, user)
    building = _building(buildings, key)
    if not building:
        raise PermissionError("请选择您获授权的楼栋")
    areas = _areas(db, key)
    stamp = now.isoformat(timespec="seconds")
    if action == "care.areaArchive":
        return _archive(db, key, areas, payload, user, stamp)
    if action == "care.areaAssign":
        return _assign(db, building, areas, payload)
    places = {"floors": _floors(db, acl, key), "rooms": _rooms(db, acl, key)}
    if action == "care.areaSave":
        return _save(db, key, areas, places, payload, user, stamp)
    return _map_changes(db, key, areas, places, payload)


def _staff(db, building, user, visible_ids, can_manage):
    assigned = defaultdict(list)
    for staff, key in db.execute(
        """SELECT m.staffId,m.areaId FROM care_area_staff m
           JOIN care_areas a ON a.id=m.areaId WHERE m.buildingId=? AND a.archivedAt=''
           ORDER BY a.nameKey,a.id""",
        (building["id"],),
    ):
        if key in visible_ids:
            assigned[staff].append(key)
    if not can_manage:
        ids = (user["id"],) if user["id"] in assigned else ()
    else:
        ids = [
            row[0]
            for row in db.execute(
                "SELECT id FROM accounts WHERE kind='staff' ORDER BY display_name,username"
            )
        ]
    rows = []
    for key in ids:
        account = access.account(db, key)
        selectable = can_manage and _selectable(account, building)
        if selectable or key in assigned:
            role = account["role"]
            if role == "自定义" and account.get("staffDuties"):
                role = "、".join(account["staffDuties"])
            rows.append(
                dict(
                    id=key,
                    name=account["displayName"],
                    role=role,
                    username=account["username"],
                    areaIds=assigned[key],
                    selectable=selectable,
                )
            )
    return rows


def _projection(db, state, user, key):
    buildings, acl = _directory(db, state, user)
    options = [
        {field: b[field] for field in ("id", "name", "campusId", "campusName")}
        for b in buildings
    ]
    result = dict(
        buildings=options,
        buildingId="",
        canManage=False,
        areas=[],
        floors=[],
        rooms=[],
        staff=[],
    )
    key = key or (options[0]["id"] if options else "")
    if not key:
        return result
    building = _building(buildings, key)
    if not building:
        raise PermissionError("请选择您获授权的楼栋")
    can_manage = _may_manage(user)
    areas = _areas(db, key)
    floors, rooms = _floors(db, acl, key), _rooms(db, acl, key)
    floor_map, room_map = _map(db, key, "floors"), _map(db, key, "rooms")
    paths = {aid: _chain(areas, aid) for aid in areas}
    visible_ids = areas.keys()
    if acl.floors is not None or acl.rooms is not None:
        targets = {
            room_map.get(rid) or floor_map.get(r["floorId"]) for rid, r in rooms.items()
        }
        targets.update(floor_map.get(fid) for fid in floors)
        visible_ids = {area["id"] for key in targets if key for area in paths[key]}
    floor_assignments, room_assignments = defaultdict(list), defaultdict(list)
    floor_rows, room_rows = [], []
    for fid, row in floors.items():
        area = floor_map.get(fid, "")
        if area:
            floor_assignments[area].append(fid)
        floor_rows.append(
            dict(id=fid, number=row["number"], label=row["label"], areaId=area)
        )
    for rid, row in rooms.items():
        direct = room_map.get(rid, "")
        if direct:
            room_assignments[direct].append(rid)
        effective = direct or floor_map.get(row["floorId"], "")
        room_rows.append(
            dict(
                id=rid,
                number=row["number"],
                floorId=row["floorId"],
                areaId=direct,
                effectiveAreaId=effective,
                areaPath=_path(paths.get(effective, ())),
            )
        )
    result.update(
        buildingId=key,
        canManage=can_manage,
        areas=sorted(
            (
                dict(
                    id=aid,
                    buildingId=key,
                    parentId=areas[aid]["parentId"] or "",
                    name=areas[aid]["name"],
                    floorIds=floor_assignments[aid],
                    roomIds=room_assignments[aid],
                    path=_path(paths[aid]),
                )
                for aid in visible_ids
            ),
            key=lambda item: (item["path"].casefold(), item["id"]),
        ),
        floors=floor_rows,
        rooms=room_rows,
        staff=_staff(db, building, user, visible_ids, can_manage),
    )
    return result


def read(store, token, building_id=""):
    key = _identifier(building_id, optional=True)
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        user = store.actor(db, token)
        if not _allowed(user):
            raise PermissionError("此账号没有区域设置的查阅权限")
        state = json.loads(
            db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
        )
        return _projection(db, state, user, key)


def room_areas(db, room_ids):
    """Annotate rooms after the caller has applied its existing facility ACL."""
    matches = db.execute(
        """SELECT r.id,f.buildingId,coalesce(direct.id,fallback.id) AS areaId
        FROM facility_rooms r JOIN facility_floors f ON f.id=r.floorId
        LEFT JOIN care_area_rooms m ON m.roomId=r.id AND m.buildingId=f.buildingId
        LEFT JOIN care_areas direct ON direct.id=m.areaId AND direct.archivedAt=''
        LEFT JOIN care_area_floors fm ON fm.floorId=f.id AND fm.buildingId=f.buildingId
        LEFT JOIN care_areas fallback ON fallback.id=fm.areaId AND fallback.archivedAt=''
        WHERE r.id IN (SELECT value FROM json_each(?))""",
        (json.dumps(list(room_ids)),),
    )
    buildings, result = {}, {}
    for row in matches:
        key, area = row["buildingId"], row["areaId"]
        if key not in buildings:
            buildings[key] = _areas(db, key)
        chain = _chain(buildings[key], area)
        result[row["id"]] = dict(
            areaId=area or "",
            areaName=chain[-1]["name"] if chain else "",
            areaPath=_path(chain),
            areaIds=[item["id"] for item in chain],
        )
    return result


def bed_directory(db, bed_ids):
    """Return display metadata for the already authorized bed identifiers."""
    records = {
        row["bedId"]: {key: row[key] for key in row.keys() if key != "bedId"}
        for row in db.execute(
            """SELECT fb.bedId,r.id AS roomId,r.number AS roomNumber,
               CASE WHEN f.layoutSource='registered' THEN r.x END AS x,
               CASE WHEN f.layoutSource='registered' THEN r.y END AS y,
               f.id AS floorId,f.number AS floorNumber,f.label AS floorLabel,
               b.id AS buildingId,b.name AS buildingName,b.campusId,b.campusName
            FROM """
            + facility.ROOM_TABLE
            + """ JOIN facility_beds fb ON r.id=fb.roomId
            WHERE fb.bedId IN (SELECT value FROM json_each(?))""",
            (json.dumps(list(bed_ids)),),
        )
    }
    areas = room_areas(db, {row["roomId"] for row in records.values()})
    for metadata in records.values():
        metadata.update(areas[metadata["roomId"]])
    return records


def responsible_staff(db, bed_id):
    """Prefer staff assigned to the effective area or any of its parent areas."""
    bed = bed_directory(db, (bed_id,)).get(bed_id)
    if not bed or not bed["areaIds"]:
        return set()
    staff = db.execute(
        """SELECT DISTINCT staffId FROM care_area_staff
        WHERE buildingId=? AND areaId IN (SELECT value FROM json_each(?))""",
        (bed["buildingId"], json.dumps(bed["areaIds"])),
    )
    result = set()
    for (key,) in staff:
        account = access.account(db, key)
        if account and _selectable(account, bed):
            result.add(account["displayName"])
    return result
