"""Shared facility maps, private room lookups and explicitly published environment scenes."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from math import ceil, isfinite, sqrt
import os
import re
from .secure_storage import INTEGRITY_ERRORS
import unicodedata
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from .access_policy import has
from .care.records import text_field
from .portal import is_customer

MAIN = "building-main"
HOME_CAMPUS = "campus-main"
INITIAL_FLOORS = (1, 2, 3, 5, 6, 7)
READ_GRANTS = ("intake", "care", "clinical", "residents")
MANAGE_GRANT = "facility.manage"
INACTIVE_BED = "停用"
ROOM_TYPES = {0: "未配置床位", 1: "单人间", 2: "双人间", 3: "三人间"}
ROOM_FIELDS = "r.id,r.number,r.ward,r.floorId,r.x,r.y,r.w,r.h,f.buildingId,f.label AS floorLabel,b.name AS buildingName,b.campusId,b.campusName"
ROOM_TABLE = "facility_rooms r JOIN facility_floors f ON f.id=r.floorId JOIN facility_building_directory b ON b.id=f.buildingId"
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS facility_site (singleton INTEGER PRIMARY KEY CHECK(singleton=1), id TEXT NOT NULL UNIQUE)",
    "CREATE TABLE IF NOT EXISTS facility_buildings (id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE)",
    "CREATE TABLE IF NOT EXISTS facility_campuses (id TEXT PRIMARY KEY,name TEXT UNIQUE NOT NULL,address TEXT NOT NULL DEFAULT '')",
    """CREATE TABLE IF NOT EXISTS facility_building_campus (
        buildingId TEXT PRIMARY KEY REFERENCES facility_buildings(id),
        campusId TEXT NOT NULL REFERENCES facility_campuses(id),localName TEXT NOT NULL,
        UNIQUE(campusId,localName))""",
    """CREATE VIEW IF NOT EXISTS facility_building_directory AS
        SELECT m.buildingId AS id,m.localName AS name,c.id AS campusId,c.name AS campusName,b.rowid AS ordinal
        FROM facility_buildings b JOIN facility_building_campus m ON m.buildingId=b.id
        JOIN facility_campuses c ON c.id=m.campusId""",
    """CREATE TABLE IF NOT EXISTS facility_floors (
        id TEXT PRIMARY KEY,buildingId TEXT NOT NULL REFERENCES facility_buildings(id),
        number INTEGER NOT NULL,label TEXT NOT NULL,layoutSource TEXT NOT NULL DEFAULT 'schematic',
        UNIQUE(buildingId,number))""",
    """CREATE TABLE IF NOT EXISTS facility_rooms (
        id TEXT PRIMARY KEY,floorId TEXT NOT NULL REFERENCES facility_floors(id),
        number TEXT NOT NULL,ward TEXT NOT NULL,x REAL,y REAL,w REAL,h REAL,
        UNIQUE(floorId,number))""",
    "CREATE TABLE IF NOT EXISTS facility_media (kind TEXT NOT NULL,itemId TEXT NOT NULL,path TEXT NOT NULL,PRIMARY KEY(kind,itemId))",
    "CREATE INDEX IF NOT EXISTS facility_media_path ON facility_media(path)",
    "CREATE TABLE IF NOT EXISTS facility_plans (floorId TEXT PRIMARY KEY REFERENCES facility_floors(id),mediaUrl TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS facility_beds (bedId TEXT PRIMARY KEY,roomId TEXT NOT NULL REFERENCES facility_rooms(id))",
    "CREATE INDEX IF NOT EXISTS facility_beds_room ON facility_beds(roomId)",
    """CREATE TABLE IF NOT EXISTS facility_scenes (
        id TEXT PRIMARY KEY,buildingId TEXT NOT NULL REFERENCES facility_buildings(id),
        floorId TEXT REFERENCES facility_floors(id),roomId TEXT REFERENCES facility_rooms(id),
        title TEXT NOT NULL,mediaUrl TEXT NOT NULL,kind TEXT NOT NULL,sortOrder INTEGER NOT NULL,
        UNIQUE(buildingId,floorId,roomId,title))""",
)


def init(db, state):
    new_index = not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='facility_media'"
    ).fetchone()
    for statement in SCHEMA:
        db.execute(statement)
    if new_index:
        for kind, query in (
            ("scene", "SELECT id,mediaUrl FROM facility_scenes"),
            ("plan", "SELECT floorId,mediaUrl FROM facility_plans"),
        ):
            for key, url in db.execute(query):
                _index_media(db, kind, key, url)
    db.execute(
        "INSERT OR IGNORE INTO facility_campuses(id,name) VALUES (?,?)",
        (HOME_CAMPUS, "本部"),
    )
    db.execute(
        """INSERT INTO facility_building_campus(buildingId,campusId,localName)
        SELECT b.id,?,b.name FROM facility_buildings b
        WHERE NOT EXISTS(SELECT 1 FROM facility_building_campus m WHERE m.buildingId=b.id)""",
        (HOME_CAMPUS,),
    )
    if db.execute("SELECT id FROM facility_site").fetchone():
        return
    db.execute("INSERT INTO facility_site VALUES (1,?)", ("site-" + uuid4().hex,))
    db.execute("INSERT INTO facility_buildings VALUES (?,?)", (MAIN, "主楼"))
    db.execute(
        "INSERT INTO facility_building_campus VALUES(?,?,?)",
        (MAIN, HOME_CAMPUS, "主楼"),
    )
    for number in INITIAL_FLOORS:
        db.execute(
            "INSERT INTO facility_floors(id,buildingId,number,label) VALUES (?,?,?,?)",
            (f"floor-{number}", MAIN, number, f"{number} 层"),
        )
    # Numeric legacy labels use the final two digits as the room sequence.
    # Unrecognizable beds keep their old identities and can be surveyed and bound later.
    for bed in state.get("beds", ()):
        number = unicodedata.normalize("NFKC", bed["label"]).rsplit("-", 1)[0]
        match = re.fullmatch(r"([1-9][0-9]?)[0-9]{2}", number)
        if not match or int(match[1]) not in INITIAL_FLOORS:
            continue
        floor_id = "floor-" + match[1]
        entry = db.execute(
            "SELECT id,ward FROM facility_rooms WHERE floorId=? AND number=?",
            (floor_id, number),
        ).fetchone()
        if entry and entry["ward"] != bed["ward"]:
            continue
        room_id = entry["id"] if entry else "room-" + uuid4().hex
        if not entry:
            db.execute(
                "INSERT INTO facility_rooms(id,floorId,number,ward) VALUES (?,?,?,?)",
                (room_id, floor_id, number, bed["ward"]),
            )
        db.execute("INSERT INTO facility_beds VALUES (?,?)", (bed["id"], room_id))


def selected_campus(db, user, payload):
    grants = user.get("facilityScope", {}).get("campusIds")
    key = payload.get("campusId") or ((grants or [HOME_CAMPUS])[0])
    if not isinstance(key, str) or (grants is not None and key not in grants):
        raise PermissionError("所选分院未获授权")
    if not db.execute("SELECT 1 FROM facility_campuses WHERE id=?", (key,)).fetchone():
        raise ValueError("所选分院不存在")
    return key


def resident_campus(db, state, resident_id):
    bed = next(
        (p.get("bedId") for p in state["residents"] if p["id"] == resident_id), None
    )
    row = db.execute(
        "SELECT b.campusId FROM "
        + ROOM_TABLE
        + " JOIN facility_beds beds ON beds.roomId=r.id WHERE beds.bedId=?",
        (bed,),
    ).fetchone()
    return row[0] if row else HOME_CAMPUS


def _id(prefix):
    return prefix + "-" + uuid4().hex


def _text(value, label, limit):
    value = text_field(value, label, required=True, limit=limit)
    value = unicodedata.normalize("NFKC", value).strip()
    if (
        not value
        or len(value) > limit
        or any(unicodedata.category(c) in {"Cc", "Cf"} for c in value)
    ):
        raise ValueError("请检查" + label)
    return value


def _integer(value, label, low, high):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,5}", value):
        value = int(value)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label}须为 {low} 到 {high} 之间的整数")
    return value


def _price(value):
    try:
        d = Decimal(str(value))
        if not d.is_finite() or not 0 <= d <= 99999 or d != d.quantize(Decimal("0.01")):
            raise InvalidOperation
        return float(d)
    except (ValueError, InvalidOperation):
        raise ValueError("床位日价须为 0 至 99999 元，最多两位小数") from None


@dataclass(frozen=True)
class _Access:
    site: str
    buildings: frozenset | None
    floors: frozenset | None
    rooms: frozenset | None
    campuses: frozenset | None

    def allows(self, b="", f="", r=""):
        return all(
            not key or allowed is None or key in allowed
            for key, allowed in ((b, self.buildings), (f, self.floors), (r, self.rooms))
        )


def _access(db, user, *, environment=False):
    if not user or is_customer(user) or not (
        user["kind"] == "owner"
        or (environment and user["kind"] in ("staff", "family"))
        or (user["kind"] == "staff" and any(has(user, k) for k in (*READ_GRANTS, MANAGE_GRANT)))
    ):
        raise PermissionError("当前账号未获准访问此区域")
    site = db.execute("SELECT id FROM facility_site WHERE singleton=1").fetchone()[0]
    policy = user.get("facilityScope", {})
    if not isinstance(policy, dict) or policy.get("institutionId", site) != site:
        raise PermissionError("机构范围不匹配")
    limits = []
    for key in ("buildingIds", "floorIds", "roomIds", "campusIds"):
        if key not in policy:
            limits.append(None)
        else:
            items = policy[key]
            if not isinstance(items, (list, tuple)) or not all(
                isinstance(x, str) and x for x in items
            ):
                raise PermissionError("区域授权格式无效")
            limits.append(frozenset(items))
    if limits[3] is not None:
        buildings = {
            row[0]
            for row in db.execute("SELECT id,campusId FROM facility_building_directory")
            if row[1] in limits[3]
        }
        limits[0] = frozenset(buildings) if limits[0] is None else limits[0] & buildings
    return _Access(site, *limits)


def _restrictions(acl, buildingId="", floorId="", roomId="", campusId=""):
    tests = []
    values = []
    for column, key, allowed in (
        ("b.campusId", campusId, acl.campuses),
        ("f.buildingId", buildingId, acl.buildings),
        ("f.id", floorId, acl.floors),
        ("r.id", roomId, acl.rooms),
    ):
        if key:
            tests.append(column + "=?")
            values.append(key)
        if allowed is not None:
            if not allowed:
                tests.append("0")
                continue
            tests.append(column + " IN (" + ",".join("?" for _ in allowed) + ")")
            values.extend(sorted(allowed))
    return (" WHERE " + " AND ".join(tests) if tests else ""), values


def _meta(db, acl, buildingId="", floorId="", roomId="", campusId=""):
    where, values = _restrictions(acl, buildingId, floorId, roomId, campusId)
    return [
        dict(r)
        for r in db.execute(
            f"SELECT {ROOM_FIELDS} FROM {ROOM_TABLE}"
            + where
            + " ORDER BY b.ordinal,f.number,r.number COLLATE NOCASE,r.id",
            values,
        )
    ]


def _floor_rows(db, acl, buildingId="", floorId="", campusId=""):
    # Only include parents of accessible children when the downstream scope is constrained.
    rooms_needed = acl.rooms is not None
    left = " JOIN" if rooms_needed else " LEFT JOIN"
    where, values = _restrictions(acl, buildingId, floorId, campusId=campusId)
    return [
        dict(f)
        for f in db.execute(
            "SELECT f.*,b.name AS buildingName,b.campusId,b.campusName,COUNT(r.id) AS roomCount FROM facility_floors f JOIN facility_building_directory b ON f.buildingId=b.id"
            + left
            + " facility_rooms r ON r.floorId=f.id"
            + where
            + " GROUP BY f.id ORDER BY b.ordinal,f.number",
            values,
        )
    ]


def directory(db, state, user):
    return _directory(db, state, user, _access(db, user))


def _directory(db, state, user, acl):
    floors = _floor_rows(db, acl)
    by_id = {}
    for b in db.execute(
        "SELECT id,name,campusId,campusName FROM facility_building_directory ORDER BY ordinal"
    ):
        if acl.allows(b["id"]) and (
            acl.rooms is None
            and acl.floors is None
            or any(f["buildingId"] == b["id"] for f in floors)
        ):
            by_id[b["id"]] = {**dict(b), "floors": []}
    for f in floors:
        by_id[f["buildingId"]]["floors"].append(f)
    can_manage = user["kind"] == "owner" and all(
        v is None for v in (acl.buildings, acl.floors, acl.rooms)
    )
    visible_campuses = {b["campusId"] for b in by_id.values()}
    whole_campus = (
        acl.floors is None
        and acl.rooms is None
        and "buildingIds" not in user.get("facilityScope", {})
    )
    campuses = [
        dict(c)
        for c in db.execute(
            "SELECT id,name,address FROM facility_campuses ORDER BY rowid"
        )
        if c["id"] in visible_campuses
        or (whole_campus and (acl.campuses is None or c["id"] in acl.campuses))
    ]
    result = {
        "institutionId": acl.site,
        "campuses": campuses,
        "buildings": list(by_id.values()),
        "canManage": can_manage,
        "canReadResidents": _can_read_residents(user),
    }
    if can_manage:
        linked = {r[0] for r in db.execute("SELECT bedId FROM facility_beds")}
        result["unmappedBeds"] = [
            {k: b[k] for k in ("id", "label", "ward")}
            for b in state["beds"]
            if b["id"] not in linked and operational_bed(b)
        ]
    return result


def operational_bed(bed):
    return bed.get("status") != INACTIVE_BED


def _can_read_residents(user):
    return user["kind"] == "owner" or any(has(user, grant) for grant in READ_GRANTS)


def room_type(count):
    return ROOM_TYPES.get(count, f"{count} 人间")


def _capacity(entries):
    return {
        "bedCount": len(entries),
        "roomType": room_type(len(entries)),
        "occupiedCount": sum(bool(b["residentId"]) or b["status"] == "已入住" for b in entries),
    }


def _used_beds(db, rooms, state):
    mapping = {}
    for row in db.execute("SELECT roomId,bedId FROM facility_beds"):
        if row["roomId"] in rooms:
            mapping[row["bedId"]] = row["roomId"]
    occupants = {p["id"]: p for p in state["residents"] if p["status"] == "在住"}
    result = {r: [] for r in rooms}
    for b in state["beds"]:
        if b["id"] not in mapping or not operational_bed(b):
            continue
        p = occupants.get(b["residentId"])
        if p and p.get("bedId") != b["id"]:
            p = None
        result[mapping[b["id"]]].append(
            {
                "id": b["id"],
                "label": b["label"],
                "status": b["status"],
                "residentId": p["id"] if p else "",
                "residentName": p["name"] if p else "",
            }
        )
    return result


def _diagram(index, count):
    cols = max(2, ceil(sqrt(count)))
    rows = max(2, ceil(count / cols))
    x, y = index % cols, index // cols
    return {
        "x": round(4 + x * 92 / cols, 3),
        "y": round(5 + y * 90 / rows, 3),
        "w": round(85 / cols, 3),
        "h": round(72 / rows, 3),
    }


def floor(db, state, user, floorId):
    acl = _access(db, user)
    rows = _floor_rows(db, acl, floorId=floorId)
    if not rows:
        raise FileNotFoundError("没有可查看的楼层")
    rooms = _meta(db, acl, floorId=floorId)
    beds = _used_beds(db, {r["id"] for r in rooms}, state)
    for index, r in enumerate(rooms):
        if rows[0]["layoutSource"] == "schematic":
            r.update(_diagram(index, len(rooms)))
        r.update(_capacity(beds[r["id"]]))
    plan = ""
    if acl.rooms is None:
        saved = db.execute(
            "SELECT mediaUrl FROM facility_plans WHERE floorId=?", (floorId,)
        ).fetchone()
        if saved:
            try:
                plan = _media_url(saved[0])
            except ValueError:
                pass  # The site may have revoked this media origin.
    return {
        **rows[0],
        "rooms": rooms,
        "planMediaUrl": plan,
        "vector": {
            "viewBox": [0, 0, 100, 100],
            "editable": has(user, MANAGE_GRANT) and acl.rooms is None,
            "rooms": [
                {**{key: r[key] for key in ("x", "y", "w", "h")}, "roomId": r["id"]}
                for r in rooms
            ],
        },
    }


def room(db, state, user, roomId):
    rows = _meta(db, _access(db, user), roomId=roomId)
    if not roomId or not rows:
        raise FileNotFoundError("没有可查看的房间")
    r = rows[0]
    beds = _used_beds(db, {roomId}, state)[roomId]
    result = {
        **r,
        "beds": beds if _can_read_residents(user) else [
            {**b, "residentId": "", "residentName": ""} for b in beds
        ],
        **_capacity(beds),
        "canEdit": has(user, MANAGE_GRANT),
    }
    if result["canEdit"] and has(user, "finance"):
        existing = _room_beds(db, state, roomId)
        current = next((b for b in existing if operational_bed(b)), existing[0] if existing else {})
        result["defaultBedDailyRate"] = current.get("dailyRate", 60)
        result["canSetBedRate"] = True
    return result


def rooms(
    db, state, user, bedCount=None, limit=12, buildingId="", floorId="", roomId="", campusId=""
):
    acl = _access(db, user)
    if bedCount is not None:
        bedCount = _integer(bedCount, "房型床位数", 0, 12)
    limit = _integer(limit, "查询条数", 1, 30)
    places = _meta(db, acl, buildingId, floorId, roomId, campusId)
    beds = _used_beds(db, {r["id"] for r in places}, state)
    keys = ("id", "number", "campusId", "campusName", "buildingId", "buildingName", "floorId", "floorLabel")
    matching = [
        {**{key: r[key] for key in keys}, **_capacity(beds[r["id"]])}
        for r in places
        if bedCount is None or len(beds[r["id"]]) == bedCount
    ]
    return {"rooms": matching[:limit], "total": len(matching), "hasMore": len(matching) > limit}


def scope(
    db, state, user, buildingId="", floorId="", roomId="", campusId="", *, agent=False
):
    """Resolve the requested hierarchy before exposing any agent input."""
    if not any((campusId, buildingId, floorId, roomId)):
        raise ValueError("请先限定分院、楼栋、楼层或房间")
    # Finance agents can summarize their branch's accounts without room-directory access.
    finance_branch = (
        agent
        and bool(campusId)
        and not any((buildingId, floorId, roomId))
        and has(user, "assistants")
        and has(user, "finance")
    )
    acl = _access(db, user, environment=finance_branch)
    directory_data = _directory(db, state, user, acl)
    building = floor_row = room_row = None
    if roomId:
        matching = _meta(db, acl, buildingId, floorId, roomId, campusId)
        if not matching:
            raise FileNotFoundError("没有可访问的房间")
        room_row = matching[0]
        floorId = room_row["floorId"]
    if floorId:
        matching = _floor_rows(db, acl, buildingId, floorId, campusId)
        if not matching:
            raise FileNotFoundError("没有可访问的楼层")
        floor_row = matching[0]
        buildingId = floor_row["buildingId"]
    if buildingId:
        building = next(
            (
                b
                for b in directory_data["buildings"]
                if b["id"] == buildingId and (not campusId or b["campusId"] == campusId)
            ),
            None,
        )
        if not building:
            raise FileNotFoundError("没有可访问的楼栋")
        campusId = building["campusId"]
    campus = next((c for c in directory_data["campuses"] if c["id"] == campusId), None)
    if not campus:
        raise FileNotFoundError("没有可访问的分院")
    rooms = _meta(db, acl, buildingId, floorId, roomId, campusId)
    beds = _used_beds(db, {r["id"] for r in rooms}, state)
    allbeds = [b for entries in beds.values() for b in entries]
    location = [campus["name"]]
    if building:
        location.append(building["name"])
    if floor_row:
        location.append(floor_row["label"])
    if room_row:
        location.append(room_row["number"] + " 房")
    return {
        "institutionId": acl.site,
        "campusId": campusId,
        "buildingId": buildingId,
        "floorId": floorId,
        "roomId": roomId,
        "roomIds": sorted(beds),
        "label": " · ".join(location),
        "bedIds": sorted(b["id"] for b in allbeds),
        "residentIds": sorted(
            b["residentId"] for b in allbeds
            if b["residentId"] and (_can_read_residents(user) or finance_branch)
        ),
    }


def _normalized(value):
    return re.sub(r"[\s·\-]+", "", unicodedata.normalize("NFKC", value).casefold())


def search(
    db, state, user, q, buildingId="", floorId="", roomId="", limit=12, campusId=""
):
    acl = _access(db, user)
    limit = _integer(limit, "查询条数", 1, 30)
    term = _normalized(_text(q, "搜索词", 80))
    if not term:
        raise ValueError("请填写房号或姓名中的至少一个字")
    number_term = re.sub(r"(?:号房间|号房|房间|房号|号|室|房)$", "", term)
    rooms = _meta(db, acl, buildingId, floorId, roomId, campusId)
    beds = _used_beds(db, {r["id"] for r in rooms}, state)
    hits = []
    for r in rooms:
        names = list(
            dict.fromkeys(b["residentName"] for b in beds[r["id"]] if b["residentName"])
        )
        matched = [n for n in names if term in _normalized(n)] if _can_read_residents(user) else []
        number = _normalized(r["number"])
        if (number_term and number_term in number) or matched:
            rank = (
                0
                if number_term == number or any(term == _normalized(n) for n in matched)
                else 1
            )
            hits.append(
                (
                    rank,
                    {
                        "roomId": r["id"],
                        "number": r["number"],
                        "campusId": r["campusId"],
                        "campusName": r["campusName"],
                        "buildingId": r["buildingId"],
                        "buildingName": r["buildingName"],
                        "floorId": r["floorId"],
                        "floorLabel": r["floorLabel"],
                        **_capacity(beds[r["id"]]),
                        "matchedNames": matched,
                        "matchedResidents": [
                            {"id": bed["residentId"], "name": bed["residentName"], "bedLabel": bed["label"]}
                            for bed in beds[r["id"]] if bed["residentName"] in matched
                        ],
                    },
                )
            )
    hits.sort(key=lambda h: h[0])
    return {
        "results": [result for _, result in hits[:limit]],
        "hasMore": len(hits) > limit,
    }


def _https_origin(url):
    try:
        p = urlsplit(url)
        if (
            p.scheme != "https"
            or p.username
            or p.password
            or not p.hostname
            or not re.fullmatch(r"[a-zA-Z0-9.-]+", p.hostname)
        ):
            return ""
        port = p.port
        return (
            "https://"
            + p.hostname.lower()
            + (f":{port}" if port and port != 443 else "")
        )
    except ValueError:
        return ""


def media_origins():
    values = []
    for entry in os.environ.get("NH_TOUR_MEDIA_ORIGINS", "").split(","):
        entry = entry.strip()
        origin = _https_origin(entry)
        if origin and entry.rstrip("/").lower() in {origin, origin + ":443"}:
            values.append(origin)
    return sorted(set(values))


def _media_url(value):
    url = _text(value, "环境媒体地址", 1024)
    p = urlsplit(url)
    path = unquote(p.path)
    if (
        p.query
        or p.fragment
        or "\\" in unquote(url)
        or re.search(r"%[0-9a-fA-F]{2}", path)
        or any(t in (".", "..") for t in path.split("/"))
        or any(ord(c) < 32 for c in unquote(url))
    ):
        raise ValueError("请使用无凭据、无查询参数的环境媒体地址")
    if (
        not p.netloc
        and not p.scheme
        and url.startswith("/tour-media/")
        and path.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    ) or (
        _https_origin(url)
        and _https_origin(url) in media_origins()
        and p.path not in ("", "/")
    ):
        return url
    raise ValueError("请使用 /tour-media/ 路径或已配置的 HTTPS 媒体域名")


def _scene_visible(acl, s):
    return (
        acl.allows(s["buildingId"], s["floorId"], s["roomId"])
        and (acl.rooms is None or bool(s["roomId"]))
        and (acl.floors is None or bool(s["floorId"]))
    )


def _index_media(db, kind, key, url):
    db.execute("DELETE FROM facility_media WHERE kind=? AND itemId=?", (kind, key))
    if url.startswith("/tour-media/"):
        db.execute(
            "INSERT INTO facility_media VALUES(?,?,?)", (kind, key, unquote(url))
        )


def can_read_media(db, state, user, path):
    """Authorize the canonical decoded path against a currently published scene or plan."""
    if (
        not isinstance(path, str)
        or not path.startswith("/tour-media/")
        or path.endswith("/")
    ):
        return False
    try:
        acl = _access(db, user, environment=True)
    except PermissionError:
        return False
    rows = db.execute(
        """SELECT s.buildingId,s.floorId,s.roomId FROM facility_media m
        JOIN facility_scenes s ON s.id=m.itemId WHERE m.path=? AND m.kind='scene'""",
        (path,),
    )
    if any(_scene_visible(acl, s) for s in rows):
        return True
    try:
        acl = _access(db, user)
    except PermissionError:
        return False
    if acl.rooms is not None:
        return False
    rows = db.execute(
        """SELECT f.buildingId,f.id FROM facility_media m
        JOIN facility_plans p ON p.floorId=m.itemId JOIN facility_floors f ON f.id=p.floorId
        WHERE m.path=? AND m.kind='plan'""",
        (path,),
    )
    return any(acl.allows(row["buildingId"], row["id"]) for row in rows)


def tour(db, state, user, buildingId="", floorId="", roomId="", campusId=""):
    acl = _access(db, user, environment=True)
    scenes = []
    query = """SELECT s.*,b.name AS buildingName,b.campusId,b.campusName,COALESCE(f.label,'') AS floorLabel,
        COALESCE(r.number,'') AS roomNumber FROM facility_scenes s
        JOIN facility_building_directory b ON s.buildingId=b.id LEFT JOIN facility_floors f ON s.floorId=f.id
        LEFT JOIN facility_rooms r ON s.roomId=r.id ORDER BY s.sortOrder,b.ordinal,f.number,r.number,s.rowid"""
    for raw in db.execute(query):
        s = dict(raw)
        if not _scene_visible(acl, s):
            continue
        if any(
            asked and asked != s[key]
            for key, asked in (
                ("campusId", campusId),
                ("buildingId", buildingId),
                ("floorId", floorId),
                ("roomId", roomId),
            )
        ):
            continue
        try:
            _media_url(s["mediaUrl"])
        except ValueError:
            continue  # An operator can remove a media origin after publishing.
        scenes.append({k: (v if v is not None else "") for k, v in s.items()})
    return {"status": "available" if scenes else "awaiting_media", "scenes": scenes}


def _find(db, table, key, label):
    if not isinstance(key, str) or not key:
        raise ValueError("请选择" + label)
    row = db.execute(f"SELECT * FROM {table} WHERE id=?", (key,)).fetchone()
    if row is None:
        raise FileNotFoundError(label + "不存在")
    return row


def _layout_rect(p):
    rect = {}
    for key in ("x", "y", "w", "h"):
        v = p.get(key)
        if isinstance(v, bool):
            raise ValueError("平面图坐标无效")
        try:
            v = float(v)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("平面图坐标无效") from None
        if not isfinite(v) or not 0 <= v <= 100:
            raise ValueError("平面图坐标应为 0 至 100 之间的百分比")
        rect[key] = v
    if (
        rect["w"] <= 0
        or rect["h"] <= 0
        or rect["x"] + rect["w"] > 100
        or rect["y"] + rect["h"] > 100
    ):
        raise ValueError("房间须有面积且完整位于图内")
    return rect


def _set_layout(db, p):
    f = _find(db, "facility_floors", p.get("floorId"), "楼层")
    ids = {
        r[0]
        for r in db.execute("SELECT id FROM facility_rooms WHERE floorId=?", (f["id"],))
    }
    entries = p.get("rooms")
    if (
        not isinstance(entries, list)
        or not ids
        or len(entries) != len(ids)
        or not all(isinstance(e, dict) for e in entries)
    ):
        raise ValueError("平面图需要包含该层每一间房间")
    rectangles = {}
    for e in entries:
        key = e.get("roomId")
        if not isinstance(key, str) or key not in ids or key in rectangles:
            raise ValueError("平面图的房间编号无效")
        r = _layout_rect(e)
        for other in rectangles.values():
            if (
                r["x"] < other["x"] + other["w"]
                and r["x"] + r["w"] > other["x"]
                and r["y"] < other["y"] + other["h"]
                and r["y"] + r["h"] > other["y"]
            ):
                raise ValueError("房间图形不能重叠")
        rectangles[key] = r
    db.executemany(
        "UPDATE facility_rooms SET x=:x,y=:y,w=:w,h=:h WHERE id=:id",
        ({**r, "id": key} for key, r in rectangles.items()),
    )
    db.execute(
        "UPDATE facility_floors SET layoutSource='registered' WHERE id=?", (f["id"],)
    )
    if "planMediaUrl" in p:
        if p["planMediaUrl"] == "":
            db.execute("DELETE FROM facility_plans WHERE floorId=?", (f["id"],))
            _index_media(db, "plan", f["id"], "")
        else:
            media = _media_url(p["planMediaUrl"])
            db.execute(
                "INSERT INTO facility_plans(floorId,mediaUrl) VALUES (?,?) ON CONFLICT(floorId) DO UPDATE SET mediaUrl=excluded.mediaUrl",
                (f["id"], media),
            )
            _index_media(db, "plan", f["id"], media)
    return "已登记楼层房间坐标"


def _room_beds(db, state, room_id):
    ids = {
        row[0]
        for row in db.execute("SELECT bedId FROM facility_beds WHERE roomId=?", (room_id,))
    }
    return [b for b in state["beds"] if b["id"] in ids]


def _add_beds(db, state, room_id, count, rate):
    if not count:
        return
    r = _find(db, "facility_rooms", room_id, "房间")
    f = _find(db, "facility_floors", r["floorId"], "楼层")
    building = _find(db, "facility_building_directory", f["buildingId"], "楼栋")
    existing = _room_beds(db, state, room_id)
    previous = sum(operational_bed(b) for b in existing)
    if previous + count > 12:
        raise ValueError("每个房间最多登记 12 张床")
    retired = [b for b in existing if not operational_bed(b) and not b.get("residentId")]
    for bed in retired[:count]:
        bed["status"] = "空闲"
    count = max(0, count - len(retired))
    # Keep all beds of a legacy room in its original room key for audit and fall observations.
    # New rooms include the building and floor to disambiguate duplicate numbers across buildings.
    prefix = (
        existing[0]["label"].rsplit("-", 1)[0]
        if existing
        else (
            (building["campusName"] + "·")
            if building["campusId"] != HOME_CAMPUS
            else ""
        )
        + f"{building['name']}·{f['label']}·{r['number']}"
    )
    labels = {b["label"] for b in state["beds"] if b["ward"] == r["ward"]}
    slot = 0
    for _ in range(count):
        while True:
            slot += 1
            label = f"{prefix}-{slot:02}"
            if label not in labels:
                break
        bed_id = _id("bed")
        labels.add(label)
        state["beds"].append(
            dict(
                id=bed_id,
                label=label,
                ward=r["ward"],
                dailyRate=rate,
                residentId="",
                status="空闲",
            )
        )
        db.execute("INSERT INTO facility_beds VALUES (?,?)", (bed_id, room_id))


def _edit_room(db, state, p, user, acl):
    if set(p) - {"roomId", "bedCount", "dailyRate"} or not p.get("roomId"):
        raise ValueError("请指定房间和目标床位数")
    rows = _meta(db, acl, roomId=p["roomId"])
    if not rows:
        raise FileNotFoundError("没有可维护的房间")
    room_id = rows[0]["id"]
    count = _integer(p.get("bedCount"), "房型床位数", 0, 12)
    existing = _room_beds(db, state, room_id)
    active = [b for b in existing if operational_bed(b)]
    change = count - len(active)
    if change > 0:
        if "dailyRate" in p and not has(user, "finance"):
            raise PermissionError("当前账号没有设置新增床位价格的权限")
        typical = active[0] if active else (existing[0] if existing else {})
        rate = _price(p.get("dailyRate", typical.get("dailyRate", 60)))
        _add_beds(db, state, room_id, change, rate)
    elif change < 0:
        count_to_remove = -change
        assigned = {r.get("bedId") for r in state["residents"]}
        slots = [
            b for b in active
            if b["status"] == "空闲" and not b.get("residentId") and b["id"] not in assigned
        ]
        if len(slots) < count_to_remove:
            raise ValueError("房型不能少于仍在使用的床位数，请先安置长辈")
        for bed in sorted(slots, key=lambda b: (b["label"], b["id"]), reverse=True)[:count_to_remove]:
            bed["status"] = INACTIVE_BED
    return f"已将{rows[0]['number']}房调整为{room_type(count)}（{count} 张床）"


def apply(db, state, action, payload, user, today):
    if action in ("facility.updateRoom", "facility.setLayout"):
        if not user or not has(user, MANAGE_GRANT):
            raise PermissionError("当前账号没有房型或平面图维护权限")
        acl = _access(db, user)
        if action == "facility.updateRoom":
            return _edit_room(db, state, payload, user, acl)
        floor_id = payload.get("floorId")
        if acl.rooms is not None:
            raise PermissionError("编辑楼层矢量布局需要整层授权")
        if not floor_id or not _floor_rows(db, acl, floorId=floor_id):
            raise FileNotFoundError("没有可维护的楼层")
        return _set_layout(db, payload)
    if not user or user["kind"] != "owner":
        raise PermissionError("仅机构 Owner 可维护院区和导览")
    acl = _access(db, user)
    if any(value is not None for value in (acl.buildings, acl.floors, acl.rooms)):
        raise PermissionError("院区维护需要完整机构管理范围")
    p = payload
    try:
        if action == "facility.addCampus":
            name = _text(p.get("name"), "分院名称", 60)
            address = text_field(p.get("address"), "分院地址", limit=150)
            db.execute(
                "INSERT INTO facility_campuses VALUES(?,?,?)",
                (_id("campus"), name, address),
            )
            return "新增分院 " + name
        if action == "facility.updateCampus":
            campus = _find(db, "facility_campuses", p.get("campusId"), "分院")
            name = _text(p.get("name", campus["name"]), "分院名称", 60)
            address = text_field(
                p.get("address", campus["address"]), "分院地址", limit=150
            )
            db.execute(
                "UPDATE facility_campuses SET name=?,address=? WHERE id=?",
                (name, address, campus["id"]),
            )
            return f"更新分院 {campus['name']} 的名称和地址，现名 {name}"
        if action == "facility.renameBuilding":
            building = _find(
                db, "facility_building_directory", p.get("buildingId"), "楼栋"
            )
            name = _text(p.get("name"), "楼栋名称", 60)
            db.execute(
                "UPDATE facility_building_campus SET localName=? WHERE buildingId=?",
                (name, building["id"]),
            )
            return f"{building['campusName']}的{building['name']}更名为{name}"
        if action == "facility.addBuilding":
            campus = _find(
                db, "facility_campuses", p.get("campusId", HOME_CAMPUS), "分院"
            )
            name = _text(p.get("name"), "楼栋名称", 60)
            bid = _id("building")
            # Keep the legacy globally unique column for existing foreign keys.
            db.execute("INSERT INTO facility_buildings VALUES (?,?)", (bid, bid))
            db.execute(
                "INSERT INTO facility_building_campus VALUES(?,?,?)",
                (bid, campus["id"], name),
            )
            return f"为{campus['name']}新增楼栋 {name}"
        if action == "facility.addFloor":
            b = _find(db, "facility_building_directory", p.get("buildingId"), "楼栋")
            n = _integer(p.get("number"), "楼层", 1, 199)
            if b["id"] == MAIN and n == 4:
                raise ValueError("主楼不设四楼")
            db.execute(
                "INSERT INTO facility_floors(id,buildingId,number,label) VALUES (?,?,?,?)",
                (_id("floor"), b["id"], n, f"{n} 层"),
            )
            return f"为{b['name']}新增 {n} 层"
        if action == "facility.addRoom":
            f = _find(db, "facility_floors", p.get("floorId"), "楼层")
            number = _text(p.get("number"), "房号", 32)
            ward = _text(p.get("ward"), "护理区", 60)
            count = _integer(p.get("bedCount", 0), "床位数", 0, 12)
            rate = _price(p.get("dailyRate", 60))
            room_id = _id("room")
            has_rect = any(k in p for k in ("x", "y", "w", "h"))
            if f["layoutSource"] == "registered" and not has_rect:
                raise ValueError("此层已登记平面图，请给新增房间指定图内位置")
            neighbors = [
                dict(v)
                for v in db.execute(
                    "SELECT id AS roomId,x,y,w,h FROM facility_rooms WHERE floorId=?",
                    (f["id"],),
                )
            ]
            if has_rect and neighbors and f["layoutSource"] == "schematic":
                raise ValueError("请先逐间登记该层的完整布局，或省略坐标使用示意图")
            db.execute(
                "INSERT INTO facility_rooms(id,floorId,number,ward) VALUES (?,?,?,?)",
                (room_id, f["id"], number, ward),
            )
            if has_rect:
                _set_layout(
                    db,
                    {
                        "floorId": f["id"],
                        "rooms": [*neighbors, {**p, "roomId": room_id}],
                    },
                )
            _add_beds(db, state, room_id, count, rate)
            return "新增 " + number + " 房并登记 " + str(count) + " 张床"
        if action == "facility.linkBed":
            r = _find(db, "facility_rooms", p.get("roomId"), "房间")
            b = next((b for b in state["beds"] if b["id"] == p.get("bedId")), None)
            if not b or b["ward"] != r["ward"] or not operational_bed(b):
                raise ValueError("请选择同一护理区的待定位床位")
            if db.execute(
                "SELECT 1 FROM facility_beds WHERE bedId=?", (b["id"],)
            ).fetchone():
                raise ValueError("该床位已经定位")
            existing = _used_beds(db, {r["id"]}, state)[r["id"]]
            if len(existing) >= 12 or any(
                e["label"].rsplit("-", 1)[0] != b["label"].rsplit("-", 1)[0]
                for e in existing
            ):
                raise ValueError("既有床位的房号不一致或已满")
            db.execute("INSERT INTO facility_beds VALUES (?,?)", (b["id"], r["id"]))
            return f"已为{b['label']}登记房间位置"
        if action == "facility.addBeds":
            r = _find(db, "facility_rooms", p.get("roomId"), "房间")
            count = _integer(p.get("count"), "新增床位数", 1, 12)
            _add_beds(db, state, r["id"], count, _price(p.get("dailyRate", 60)))
            return f"为{r['number']}房增加 {count} 张床"
        if action == "facility.setScene":
            title = _text(p.get("title"), "场景名称", 80)
            media = _media_url(p.get("mediaUrl"))
            kind = p.get("kind", "photo")
            if kind not in ("photo", "panorama"):
                raise ValueError("请选择照片或全景图")
            r = (
                _find(db, "facility_rooms", p["roomId"], "房间")
                if p.get("roomId")
                else None
            )
            fid = r["floorId"] if r else (p.get("floorId") or None)
            f = _find(db, "facility_floors", fid, "楼层") if fid else None
            bid = f["buildingId"] if f else p.get("buildingId")
            b = _find(db, "facility_building_directory", bid, "楼栋")
            if (
                p.get("floorId")
                and p["floorId"] != fid
                or p.get("buildingId")
                and p["buildingId"] != b["id"]
            ):
                raise ValueError("场景与所选区域不符")
            rid = r["id"] if r else None
            current = db.execute(
                "SELECT id FROM facility_scenes WHERE buildingId=? AND floorId IS ? AND roomId IS ? AND title=?",
                (b["id"], fid, rid, title),
            ).fetchone()
            order = _integer(p.get("sortOrder", 100), "展示次序", 0, 9999)
            scene_id = current["id"] if current else _id("view")
            if current:
                db.execute(
                    "UPDATE facility_scenes SET mediaUrl=?,kind=?,sortOrder=? WHERE id=?",
                    (media, kind, order, current["id"]),
                )
            else:
                db.execute(
                    "INSERT INTO facility_scenes VALUES (?,?,?,?,?,?,?,?)",
                    (scene_id, b["id"], fid, rid, title, media, kind, order),
                )
            _index_media(db, "scene", scene_id, media)
            return "已发布环境导览场景 " + title
        if action == "facility.withdrawScene":
            s = _find(db, "facility_scenes", p.get("sceneId"), "导览场景")
            db.execute("DELETE FROM facility_scenes WHERE id=?", (s["id"],))
            _index_media(db, "scene", s["id"], "")
            return "已撤下环境导览场景 " + s["title"]
    except INTEGRITY_ERRORS:
        raise ValueError("同一区域内已存在此编号或名称") from None
    raise ValueError("未登记的院区动作")
