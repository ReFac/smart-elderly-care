"""Schedule resident work orders and issue each occurrence once in local business time."""

from contextlib import closing
import json
import re
from uuid import uuid4
from zoneinfo import ZoneInfo

from . import access, access_policy as policy, campus_access, daily_life, facility
from .care.plans import append_task
from .care.records import iso_date, text_field

LOCAL = ZoneInfo("Asia/Shanghai")
KINDS = {"meal": "膳食照护", "patrol": "巡查", "care": "日常照护"}
SCOPE_FIELDS = {"campus": "campusIds", "rooms": "roomIds", "residents": "residentIds"}
LOCATION_FIELDS = {
    "campusIds": "campusId",
    "buildingIds": "buildingId",
    "floorIds": "floorId",
    "roomIds": "roomId",
}
ASSIGNMENT = "当班照护组"
ROLE_ORDER = ("护士长", "护士", "护工", "院长")
SERVICE = {
    "id": "scheduled-work",
    "username": "scheduled-work",
    "displayName": "定时工单",
}
ACTIONS = ("care.saveSchedule", "care.setScheduleEnabled", "care.scheduleMenu")
RULE_KEYS = {
    "id",
    "title",
    "kind",
    "assignee",
    "assigneeId",
    "assigneeRole",
    "time",
    "weekdays",
    "startDate",
    "endDate",
    "scope",
    "mealKind",
    "menu",
    "weeklyMenus",
    "note",
    "enabled",
}


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS scheduled_work_rules(
        id TEXT PRIMARY KEY, config TEXT NOT NULL CHECK(json_valid(config)),
        createdBy TEXT NOT NULL, createdAt TEXT NOT NULL, updatedBy TEXT NOT NULL, updatedAt TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS scheduled_work_runs(
        id TEXT PRIMARY KEY, scheduleId TEXT NOT NULL REFERENCES scheduled_work_rules(id),
        day TEXT NOT NULL, time TEXT NOT NULL, title TEXT NOT NULL, releasedAt TEXT NOT NULL,
        count INTEGER NOT NULL, status TEXT NOT NULL, issuedRooms TEXT NOT NULL, UNIQUE(scheduleId,day))""")
    db.execute("""CREATE TABLE IF NOT EXISTS scheduled_work_menus(
        scheduleId TEXT NOT NULL REFERENCES scheduled_work_rules(id),
        day TEXT NOT NULL, items TEXT NOT NULL CHECK(json_valid(items)),
        updatedBy TEXT NOT NULL, updatedAt TEXT NOT NULL, PRIMARY KEY(scheduleId,day))""")
    db.execute(
        "CREATE INDEX IF NOT EXISTS scheduled_runs_by_day ON scheduled_work_runs(day DESC, time DESC)"
    )


def _readable(user):
    return user["kind"] in ("owner", "staff") and any(
        policy.has(user, p) for p in ("care", "care.schedule", "clinical")
    )


def _writable(user):
    return user["kind"] in ("owner", "staff") and policy.has(user, "care.schedule")


def _ids(value):
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= 1000
        or any(
            not isinstance(v, str) or not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,100}", v)
            for v in value
        )
        or len(set(value)) != len(value)
    ):
        raise ValueError("请选择至少一项，请勿重复选择人员或区域")
    return set(value)


def _scope(value):
    if not isinstance(value, dict):
        raise ValueError("请选择工单派发范围")
    kind = value.get("kind")
    if kind == "all" and set(value) == {"kind"}:
        return {"kind": kind}
    if (
        not isinstance(kind, str)
        or kind not in SCOPE_FIELDS
        or set(value) != {"kind", SCOPE_FIELDS[kind]}
    ):
        raise ValueError("请按住户、房间或分院选择工单派发范围")
    key = SCOPE_FIELDS[kind]
    return {"kind": kind, key: sorted(_ids(value[key]))}


def _date(value, label):
    day = iso_date(value, label)
    if value != day:
        raise ValueError(f"{label}须为 YYYY-MM-DD")
    return day


def _menu(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise ValueError("请填写 1 至 20 项菜单")
    items = [text_field(x, "菜品", required=True, limit=80) for x in value]
    if any(re.search(r"[\r\n\t\x00]", item) for item in items) or len(
        set(items)
    ) != len(items):
        raise ValueError("请每项填写一道菜品，避免重复")
    return items


def _weekly_menus(value):
    if not isinstance(value, dict) or set(value) - {"1", "2", "3", "4", "5", "6", "7"}:
        raise ValueError("请选择周一至周日的菜单")
    return {day: _menu(items) for day, items in value.items()}


def _clock(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value
    ):
        raise ValueError("执行时间须为 HH:MM")
    return value


def _config(payload, today, previous):
    if not isinstance(payload, dict) or set(payload) - RULE_KEYS:
        raise ValueError("工单模板字段无效")
    kind = payload.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("请选择伙食、巡查或照护模板")
    start = _date(payload.get("startDate") or today, "开始日期")
    end = _date(payload["endDate"], "结束日期") if payload.get("endDate") else ""
    weekdays = payload.get("weekdays", list(range(1, 8)))
    if (
        not isinstance(weekdays, list)
        or not weekdays
        or len(weekdays) > 7
        or any(type(n) is not int or not 1 <= n <= 7 for n in weekdays)
        or len(set(weekdays)) != len(weekdays)
        or end
        and end < start
    ):
        raise ValueError("请核对日期范围及每周执行日")
    enabled = payload.get("enabled", previous.get("enabled", True))
    if type(enabled) is not bool:
        raise ValueError("请选择启用或暂停")
    meal = payload.get("mealKind", "")
    menu = payload.get("menu", [])
    weekly_menus = {}
    if kind == "meal":
        if meal not in daily_life.MEALS:
            raise ValueError("请为伙食工单选择早餐、午餐或晚餐")
        menu = _menu(menu)
        weekly_menus = _weekly_menus(
            payload.get("weeklyMenus", previous.get("weeklyMenus", {}))
        )
    elif meal or menu or payload.get("weeklyMenus", {}) != {}:
        raise ValueError("仅伙食工单使用餐次和菜单")
    return dict(
        title=text_field(payload.get("title"), "模板名称", required=True, limit=100),
        kind=kind,
        time=_clock(payload.get("time")),
        weekdays=sorted(weekdays),
        startDate=start,
        endDate=end,
        scope=_scope(payload.get("scope")),
        note=text_field(payload.get("note"), "执行说明", limit=600),
        assignee=text_field(payload.get("assignee"), "派发给", limit=80) or ASSIGNMENT,
        assigneeId=text_field(payload.get("assigneeId"), "员工编号", limit=100),
        assigneeRole=text_field(payload.get("assigneeRole"), "岗位", limit=40),
        mealKind=meal,
        menu=menu,
        weeklyMenus=weekly_menus,
        enabled=enabled,
    )


def _areas(db, state, user):
    acl = facility._access(db, user, environment=True)
    rooms = facility._meta(db, acl)
    campuses = facility._directory(db, state, user, acl)["campuses"]
    return {r["id"]: r for r in rooms}, {c["id"]: c["name"] for c in campuses}, acl


def _full_campuses(user):
    return not any(
        k in user.get("facilityScope", {})
        for k in ("buildingIds", "floorIds", "roomIds")
    )


def _within(scope, user, rooms, campuses, ids, *, existing=False):
    if existing and user["kind"] == "owner" and not user.get("facilityScope"):
        return True
    kind = scope["kind"]
    if kind == "all":
        return user["kind"] == "owner" and not user.get("facilityScope")
    if kind == "campus":
        return _full_campuses(user) and campuses.keys() >= set(scope["campusIds"])
    if kind == "rooms":
        return rooms.keys() >= set(scope["roomIds"])
    return ids >= set(scope["residentIds"])


def _resident_ids(db, state, user):
    beds = campus_access.allowed_beds(db, user, include_rooms=True)
    if beds is not None:
        return campus_access.resident_ids(state, beds, user)
    return {p["id"] for p in state["residents"]}


def _roster(db, state, rooms, *, day=None):
    by_bed = {
        r["bedId"]: rooms[r["roomId"]]
        for r in db.execute("SELECT bedId,roomId FROM facility_beds")
        if r["roomId"] in rooms
    }
    beds = {b["id"]: b for b in state["beds"]}
    away = {
        r["residentId"]
        for r in state.get("leaves", ())
        if day and r["startDate"] <= day <= r["endDate"]
    }
    selected = []
    for person in state["residents"]:
        rid, bid = person["id"], person.get("bedId")
        if (
            person["status"] != "在住"
            or bid not in by_bed
            or beds.get(bid, {}).get("residentId") != rid
            or rid in away
        ):
            continue
        if day and (
            (person.get("admittedAt") or "") > day
            or person.get("stayType") == "trial"
            and person.get("trialEndsAt")
            and person["trialEndsAt"] < day
        ):
            continue
        room = by_bed[bid]
        selected.append(
            dict(
                id=rid,
                name=person["name"],
                bedId=bid,
                bedLabel=beds[bid]["label"],
                roomId=room["id"],
                roomNumber=room["number"],
                campusId=room["campusId"],
                buildingId=room["buildingId"],
                floorId=room["floorId"],
            )
        )
    return sorted(
        selected,
        key=lambda p: (
            p["campusId"],
            p["buildingId"],
            p["roomNumber"],
            p["bedLabel"],
            p["id"],
        ),
    )


def _staff_allowed(user, target):
    scope = user.get("facilityScope") or {}
    campuses = scope.get("campusIds")
    if (
        target["kind"] != "staff"
        or not target["enabled"]
        or target["activationPending"]
        or not policy.has(target, "care")
    ):
        return False
    if campuses is None:
        return True
    assigned = target.get("facilityScope", {}).get("campusIds", ())
    return bool(set(campuses).intersection(assigned))


def _assignment(db, config, user):
    aid, role = config["assigneeId"], config["assigneeRole"]
    if aid and role:
        raise ValueError("请选择一位员工或一个岗位")
    if aid:
        target = access.account(db, aid)
        if not target or not _staff_allowed(user, target):
            raise PermissionError("请选择权限范围内的在岗照护员工")
        config["assignee"] = target["displayName"]
    elif role:
        if role not in ROLE_ORDER:
            raise ValueError("请选择有效的照护岗位")
        config["assignee"] = role


def _attributes(rule):
    config = json.loads(rule["config"])
    config.pop("boundary", None)
    config.setdefault("weeklyMenus", {})
    return config


def _rule(db, sid):
    if not isinstance(sid, str) or not re.fullmatch("[a-f0-9]{32}", sid):
        raise ValueError("模板编号无效")
    row = db.execute("SELECT * FROM scheduled_work_rules WHERE id=?", (sid,)).fetchone()
    if not row:
        raise FileNotFoundError("没有这个定时工单模板")
    return row


def _future_menu(
    db, state, rule, config, user, rooms, ids, day, menu, timestamp, today
):
    if config["kind"] != "meal" or day < today:
        raise ValueError("可为今天或后续日期的伙食工单安排菜单")
    pending = [
        task
        for task in state["tasks"]
        if task.get("scheduleId") == rule["id"]
        and task["date"] == day
        and task["status"] == "待执行"
    ]
    if any(
        task["scheduledRoomId"] not in rooms or task["residentId"] not in ids
        for task in pending
    ):
        raise PermissionError("当天已派发的工单超出您的管理范围")
    db.execute(
        """INSERT INTO scheduled_work_menus VALUES(?,?,?,?,?)
           ON CONFLICT(scheduleId,day) DO UPDATE SET items=excluded.items,updatedBy=excluded.updatedBy,updatedAt=excluded.updatedAt""",
        (rule["id"], day, json.dumps(menu, ensure_ascii=False), user["id"], timestamp),
    )
    for task in pending:
        task["menu"] = menu


def command(db, state, user, action, payload, now):
    if not _writable(user):
        raise PermissionError("此账号没有定时工单的管理权限")
    if not isinstance(payload, dict):
        raise ValueError("模板内容无效")
    now = now.astimezone(LOCAL)
    today, timestamp = now.date().isoformat(), now.isoformat(timespec="seconds")
    rooms, campuses, acl = _areas(db, state, user)
    ids = _resident_ids(db, state, user)
    sid = payload.get("id")
    row = _rule(db, sid) if sid or action != "care.saveSchedule" else None
    current = json.loads(row["config"]) if row else {}
    if row and not _within(current["scope"], user, rooms, campuses, ids, existing=True):
        raise PermissionError("当前模板超出您的管理范围")
    if action == "care.setScheduleEnabled":
        if set(payload) != {"id", "enabled"} or type(payload["enabled"]) is not bool:
            raise ValueError("请选择启用或暂停定时工单")
        current["enabled"] = payload["enabled"]
        db.execute(
            "UPDATE scheduled_work_rules SET config=?,updatedBy=?,updatedAt=? WHERE id=?",
            (json.dumps(current, ensure_ascii=False), user["id"], timestamp, sid),
        )
        return (
            ("已启用" if payload["enabled"] else "已暂停")
            + "定时工单「"
            + current["title"]
            + "」"
        )
    if action == "care.scheduleMenu":
        if set(payload) != {"id", "day", "menu"}:
            raise ValueError("请选择需要更新菜单的日期")
        day, menu = _date(payload["day"], "菜单日期"), _menu(payload["menu"])
        _future_menu(
            db, state, row, current, user, rooms, ids, day, menu, timestamp, today
        )
        return f"已设置 {day} 的「{current['title']}」菜单"
    if action != "care.saveSchedule":
        raise ValueError("无效的定时工单操作")

    config = _config(payload, today, current)
    if not _within(config["scope"], user, rooms, campuses, ids):
        raise PermissionError("请选择您可管理的住户、分院或房间")
    _assignment(db, config, user)
    chosen = config["scope"]
    old_members = set(current.get("scope", {}).get("residentIds", ()))
    if chosen["kind"] == "residents":
        active = {p["id"] for p in _roster(db, state, rooms)}
        if not set(chosen["residentIds"]) <= active | old_members:
            raise ValueError("新加入定时名单的长者须已分床入住")
    config["boundary"] = {
        key: sorted(allowed)
        for key, allowed in (
            ("campusIds", acl.campuses),
            ("buildingIds", acl.buildings if not _full_campuses(user) else None),
            ("floorIds", acl.floors),
            ("roomIds", acl.rooms),
        )
        if allowed is not None
    }
    if row:
        db.execute(
            "UPDATE scheduled_work_rules SET config=?,updatedBy=?,updatedAt=? WHERE id=?",
            (json.dumps(config, ensure_ascii=False), user["id"], timestamp, sid),
        )
    else:
        db.execute(
            "INSERT INTO scheduled_work_rules VALUES(?,?,?,?,?,?)",
            (
                uuid4().hex,
                json.dumps(config, ensure_ascii=False),
                user["id"],
                timestamp,
                user["id"],
                timestamp,
            ),
        )
    return f"已{'更新' if row else '创建'}定时工单「{config['title']}」"


def _matches(person, config):
    boundary, scope = config.get("boundary", {}), config["scope"]
    if any(
        person[LOCATION_FIELDS[key]] not in permitted
        for key, permitted in boundary.items()
    ):
        return False
    kind = scope["kind"]
    if kind == "all":
        return True
    field = {"campus": "campusId", "rooms": "roomId", "residents": "id"}[kind]
    return person[field] in scope[SCOPE_FIELDS[kind]]


def _due(db, day, weekday, time):
    return db.execute(
        """SELECT r.id,r.config FROM scheduled_work_rules r
        WHERE json_extract(r.config,'$.enabled')=1 AND json_extract(r.config,'$.startDate')<=?
          AND (json_extract(r.config,'$.endDate')='' OR json_extract(r.config,'$.endDate')>=?)
          AND json_extract(r.config,'$.time')<=?
          AND EXISTS (SELECT 1 FROM json_each(r.config,'$.weekdays') WHERE value=?)
          AND NOT EXISTS (SELECT 1 FROM scheduled_work_runs o WHERE o.scheduleId=r.id AND o.day=?)
        ORDER BY json_extract(r.config,'$.time'), r.rowid""",
        (day, day, time, weekday, day),
    ).fetchall()


def _assigned(db, config, person, allowed):
    aid, role = config["assigneeId"], config["assigneeRole"]
    if aid and aid not in allowed:
        actor = access.account(db, aid)
        if actor and _staff_allowed({"facilityScope": {}}, actor):
            allowed[aid] = (
                actor["displayName"],
                campus_access.allowed_beds(db, actor, include_rooms=True),
            )
        else:
            allowed[aid] = ("", set())
    if aid:
        name, beds = allowed[aid]
        if not name or beds is not None and person["bedId"] not in beds:
            return ASSIGNMENT, "", ""
        return name, aid, ""
    return config["assignee"], "", role


def _releases(db, state, rules, now):
    day, timestamp = now.date().isoformat(), now.isoformat(timespec="seconds")
    weekday = str(now.isoweekday())
    acl = facility._access(db, {"kind": "owner"}, environment=True)
    rooms = {row["id"]: row for row in facility._meta(db, acl)}
    roster = _roster(db, state, rooms, day=day)
    meals = {
        (task["residentId"], task["mealKind"])
        for task in state["tasks"]
        if task.get("mealKind") and task["date"] == day and task["status"] != "已取消"
    }
    meals.update(
        tuple(row)
        for row in db.execute(
            "SELECT residentId,kind FROM daily_life_attendance WHERE day=? AND kind IN ('早餐','午餐','晚餐')",
            (day,),
        )
    )
    allowed, released = {}, []
    for rule in rules:
        sid, config = rule["id"], json.loads(rule["config"])
        meal = config["mealKind"]
        override = (
            db.execute(
                "SELECT items FROM scheduled_work_menus WHERE scheduleId=? AND day=?",
                (sid, day),
            ).fetchone()
            if meal
            else None
        )
        menu = (
            json.loads(override[0])
            if override
            else config.get("weeklyMenus", {}).get(weekday, config["menu"])
        )
        occurrence = uuid4().hex
        matched = []
        for person in roster:
            rid = person["id"]
            if not _matches(person, config) or meal and (rid, meal) in meals:
                continue
            assignee, aid, role = _assigned(db, config, person, allowed)
            append_task(
                state,
                rid,
                config["title"],
                assignee,
                day,
                config["time"],
                KINDS[config["kind"]],
                scheduleId=sid,
                occurrenceId=occurrence,
                scheduledBedId=person["bedId"],
                scheduledRoomId=person["roomId"],
                scheduledCampusId=person["campusId"],
                assigneeId=aid,
                assigneeRole=role,
                note=config["note"],
                **({"mealKind": meal, "menu": menu} if meal else {}),
            )
            matched.append(person)
            if meal:
                meals.add((rid, meal))
        db.execute(
            "INSERT INTO scheduled_work_runs VALUES(?,?,?,?,?,?,?,?,?)",
            (
                occurrence,
                sid,
                day,
                config["time"],
                config["title"],
                timestamp,
                len(matched),
                "released" if matched else "empty",
                json.dumps(sorted({person["roomId"] for person in matched})),
            ),
        )
        released.append((config["title"], matched))
    return released


def tick(store):
    from . import activity, history
    from .store import encode

    now = store.now().astimezone(LOCAL)
    day, weekday, clock = (
        now.date().isoformat(),
        now.isoweekday(),
        now.strftime("%H:%M"),
    )
    with closing(store.connect()) as db, db:
        if not _due(db, day, weekday, clock):
            return 0
        db.execute("BEGIN IMMEDIATE")
        now = store.now().astimezone(LOCAL)
        rules = _due(
            db, now.date().isoformat(), now.isoweekday(), now.strftime("%H:%M")
        )
        if not rules:
            return 0
        row = db.execute("SELECT revision,data FROM workspace WHERE id=1").fetchone()
        state, revision = json.loads(row["data"]), row["revision"] + 1
        history.watch(db, "care.releaseSchedules")
        released = _releases(db, state, rules, now)
        count = sum(len(people) for _, people in released)
        people = [p for _, recipients in released for p in recipients]
        place = {
            "residentIds": sorted({p["id"] for p in people}),
            "roomIds": sorted({p["roomId"] for p in people}),
            "campusIds": sorted({p["campusId"] for p in people}),
        }
        db.execute(
            "UPDATE workspace SET revision=?,data=? WHERE id=1",
            (revision, encode(state)),
        )
        activity.write(
            db,
            revision,
            now.isoformat(timespec="seconds"),
            "care.releaseSchedules",
            f"检查 {len(released)} 个定时模板，派发 {count} 张工单",
            SERVICE,
            place,
            {},
        )
        return count


def read(store, token):
    now = store.now().astimezone(LOCAL)
    today = now.date().isoformat()
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        user = store.actor(db, token)
        if not _readable(user):
            raise PermissionError("当前账号无法查看定时工单")
        state = json.loads(
            db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
        )
        rooms, campuses, _ = _areas(db, state, user)
        ids = _resident_ids(db, state, user)
        rules = []
        for row in db.execute(
            "SELECT * FROM scheduled_work_rules ORDER BY updatedAt DESC,id"
        ):
            config = _attributes(row)
            if _within(config["scope"], user, rooms, campuses, ids, existing=True):
                rules.append(
                    dict(
                        id=row["id"],
                        createdAt=row["createdAt"],
                        updatedAt=row["updatedAt"],
                        **config,
                    )
                )
        visible = json.dumps([r["id"] for r in rules])
        runs = [
            {key: row[key] for key in row.keys() if key != "issuedRooms"}
            for row in db.execute(
                """SELECT * FROM scheduled_work_runs WHERE scheduleId IN (SELECT value FROM json_each(?))
                   AND NOT EXISTS (SELECT value FROM json_each(issuedRooms) EXCEPT SELECT value FROM json_each(?))
                   ORDER BY day DESC,time DESC,id LIMIT 100""",
                (visible, json.dumps(list(rooms))),
            )
        ]
        menus = [
            dict(
                scheduleId=row["scheduleId"],
                day=row["day"],
                menu=json.loads(row["items"]),
            )
            for row in db.execute(
                """SELECT * FROM scheduled_work_menus WHERE day>=?
                   AND scheduleId IN (SELECT value FROM json_each(?)) ORDER BY day,scheduleId""",
                (today, visible),
            )
        ]
        staff = []
        if _writable(user):
            for (key,) in db.execute(
                "SELECT id FROM accounts WHERE kind='staff' ORDER BY display_name,username"
            ):
                target = access.account(db, key)
                if _staff_allowed(user, target):
                    staff.append(
                        dict(
                            id=key,
                            label=target["displayName"]
                            + "（"
                            + target["username"]
                            + "）",
                            role=target["role"],
                        )
                    )
        from .scheduled_sources import overview

        return {
            "builtins": overview(db, state, user, now),
            "rules": rules,
            "runs": runs,
            "menus": menus,
            "roster": _roster(db, state, rooms),
            "campuses": [{"id": cid, "name": name} for cid, name in campuses.items()]
            if _full_campuses(user)
            else [],
            "rooms": [
                {
                    **{
                        key: r[key]
                        for key in (
                            "id",
                            "number",
                            "campusId",
                            "campusName",
                            "buildingName",
                        )
                    },
                    "label": f"{r['buildingName']} · {r['number']} 房",
                }
                for r in rooms.values()
            ],
            "staff": staff,
            "roles": list(ROLE_ORDER),
            "today": today,
            "canManage": _writable(user),
            "allowAll": user["kind"] == "owner" and not user.get("facilityScope"),
        }
