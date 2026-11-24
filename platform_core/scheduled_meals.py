"""Review today's scheduled meal intake against the signed-in employee's roster."""

from contextlib import closing
import json
import re
import unicodedata
from uuid import uuid4

from . import access_policy, campus_access, daily_life, facility
from .agents import region
from .care import plans, timeline
from .care.records import text_field
from .provider import generation
from .scheduled_work import ASSIGNMENT

VOICE_GUIDE = """你是伙食工单的语音文字解析器。只整理用户今天已经观察到的实际进食，不进行操作。
返回 JSON {"meal":"","mode":"individual","rooms":[],"people":[{"name":"","bed":"","room":""}],"exceptions":[{"name":"","bed":"","room":"","dishes":["原话中的菜名"],"entire":false}],"unclear":false}。
meal 只能为 早餐、午餐、晚餐或空字符串。mode 是 individual（明确指定参与者）或 all（明确表示全员、大家、其他老人都吃了）。
输出所有固定字段。没有为整组限定房间时 rooms 为 []。mode 为 all 时 people 为 []；有例外也只填入 exceptions。床号、姓名、房号和菜名必须原文摘取，禁止猜测。未知的身份字段填空字符串，姓名里去掉“老人”等称呼。无法定位人员或一句话说了多个餐次则 unclear。
若说“其他老人都吃了今天的午餐伙食，张三没有吃青菜”，设置 meal 为午餐，mode 为 all，exceptions 中只列张三和青菜，entire 为 false，unclear 为 false。没有此类例外则 exceptions 为 []。
只有明确说没吃整餐才将 entire 标为 true 并留空 dishes。依上下文无法确定遗漏何物标记 unclear。
复述、询问、其他日期、计划、嘱托、未经确认的信息均标记 unclear。不要使用电话、地址、身份证等信息。"""

VOICE_NEGATIVE = re.compile(
    r"[?？]|(?:怎么|如何|是否|哪些|何时|举例|例如|如果|假设|帮我问|请提醒|尚不确定|听说|据说|可能|昨天|明天|前天|后天|还没到|不(?:要|用|必)(?:登记|记录)|别(?:登记|记录)|谁(?:已经|还没|没|没有)?(?:吃|喝)|有没有(?:人|老人|长者)?)|(?:吗|么)[。！!]?$"
)
VOICE_OTHER = re.compile(r"除了|除外|未[吃喝]|没(?:有)?(?:吃|喝)|不吃")
VOICE_ALL = re.compile(
    r"所有(?:的)?(?:人|老人|长者|住户)|全(?:员|院|体)|全部(?:人|老人|长者|住户)|(?:其他|其余|剩下的).{0,12}都|大家|(?:老人|长者|住户)都"
)


def voice_intent(text):
    return (
        bool(
            re.search(
                r"伙食|餐食|饭菜|菜单|菜品|早餐|午餐|晚餐|早饭|午饭|晚饭|吃饭", text
            )
        )
        and bool(
            re.search(
                r"已.{0,6}(?:吃|喝|用餐)|吃了|吃过|没(?:有)?吃|未吃|没有喝|都吃|吃完|没有.{0,8}进食",
                text,
            )
        )
        and not VOICE_NEGATIVE.search(text)
    )


def _parse(raw, text):
    if (
        not isinstance(raw, dict)
        or set(raw) != {"meal", "mode", "rooms", "people", "exceptions", "unclear"}
        or raw["unclear"] is not False
        or raw["meal"] not in (*daily_life.MEALS, "")
        or raw["mode"] not in ("all", "individual")
    ):
        raise ValueError("请说明是哪顿饭、哪些老人和哪一道菜")
    if (raw["mode"] == "all") != bool(VOICE_ALL.search(text)):
        raise ValueError("请明确要核对的老人范围")
    if VOICE_OTHER.search(text) and not raw["exceptions"]:
        raise ValueError("请说明哪位老人没吃，以及缺少哪道菜")

    def literal(value):
        return isinstance(value, str) and len(value) <= 100 and value in text

    if not _list(raw["rooms"], literal) or any(not room for room in raw["rooms"]):
        raise ValueError("请明确房间编号")
    if raw["mode"] == "all" and raw["people"]:
        raise ValueError("全员范围和指定人员不能同时生效")
    if raw["mode"] == "individual" and not (raw["people"] or raw["exceptions"]):
        raise ValueError("请明确要核对的老人姓名或床位")
    if not isinstance(raw["people"], list) or not isinstance(raw["exceptions"], list):
        raise ValueError("请核对用餐名单")
    for group, keys in (
        ("people", {"name", "bed", "room"}),
        ("exceptions", {"name", "bed", "room", "dishes", "entire"}),
    ):
        for item in raw[group]:
            if (
                not isinstance(item, dict)
                or set(item) != keys
                or not all(literal(item[key]) for key in ("name", "bed", "room"))
                or not any(item[key] for key in ("name", "bed"))
            ):
                raise ValueError("请用床位或姓名区分需要核对的老人")
            if group == "exceptions" and (
                type(item["entire"]) is not bool
                or not _list(
                    item["dishes"], lambda value: bool(value) and literal(value)
                )
                or item["entire"] == bool(item["dishes"])
            ):
                raise ValueError("请说明是整餐没吃，还是某几道菜没有吃")
    # Every literal location in the utterance must participate in the draft, so an
    # omitted room qualifier cannot widen a voiced update to unrelated residents.
    groups = re.findall(
        r"(?<!\d)(\d{1,8}(?:[、，,和及]\s*\d{1,8})*)\s*(?:号)?(?:房|病房|床)", text
    )
    groups += re.findall(r"(?:房间|病房|床位)\s*(\d{1,8})(?!\d)", text)
    mentions = {number for group in groups for number in re.findall(r"\d+", group)}
    used = {*raw["rooms"]}
    for item in (*raw["people"], *raw["exceptions"]):
        for key in ("room", "bed"):
            if item[key]:
                used.add(item[key])
    if mentions - used:
        raise ValueError("口述中仍有房号或床号待核实")
    return raw


def _list(value, predicate):
    return isinstance(value, list) and all(predicate(part) for part in value)


def _employee(user):
    if user["kind"] not in ("owner", "staff"):
        raise PermissionError("仅工作人员可核对伙食工单")
    access_policy.require(user, "care")


def _assignee(user, task):
    if user["kind"] == "owner" or access_policy.has(user, "care.groupConfirm"):
        return True
    if task.get("assigneeId"):
        return task["assigneeId"] == user["id"]
    if task.get("assigneeRole"):
        return task["assigneeRole"] in (user["role"], *user.get("staffDuties", ()))
    return not task.get("assignee") or task["assignee"] in (
        ASSIGNMENT,
        "值班护工",
        "本区护工",
        "当班护工",
    )


def _rows(db, state, user, now, area):
    _employee(user)
    day = now.date().isoformat()
    permitted_beds = campus_access.allowed_beds(db, user, include_rooms=True)
    selected_rooms = (
        set(facility.scope(db, state, user, agent=True, **area)["roomIds"])
        if area
        else None
    )
    people = {
        p["id"]: p
        for p in state["residents"]
        if p["status"] == "在住" and p.get("bedId")
    }
    beds = {b["id"]: b for b in state["beds"]}
    guests = {
        row["bedId"]: dict(row)
        for row in db.execute(
            f"SELECT fb.bedId,{facility.ROOM_FIELDS} FROM {facility.ROOM_TABLE}"
            " JOIN facility_beds fb ON fb.roomId=r.id"
        )
    }
    existing = set(
        tuple(row)
        for row in db.execute(
            "SELECT residentId,kind FROM daily_life_attendance WHERE day=?", (day,)
        )
    )
    away = {
        leave["residentId"]
        for leave in state.get("leaves", ())
        if leave["startDate"] <= day <= leave["endDate"]
    }
    answer = []
    for task in state["tasks"]:
        menu = task.get("menu")
        if (
            task["date"] != day
            or task["status"] != "待执行"
            or task.get("mealKind") not in daily_life.MEALS
            or not task.get("occurrenceId")
            or not menu
            or not _assignee(user, task)
            or task["residentId"] in away
        ):
            continue
        who = people.get(task["residentId"])
        bed = task.get("scheduledBedId")
        place = guests.get(bed)
        if (
            not who
            or not place
            or who["bedId"] != bed
            or beds.get(bed, {}).get("residentId") != who["id"]
            or permitted_beds is not None
            and bed not in permitted_beds
            or selected_rooms is not None
            and place["id"] not in selected_rooms
            or task.get("scheduledRoomId") != place["id"]
            or task.get("scheduledCampusId") != place["campusId"]
        ):
            continue
        can_sign = task["time"] <= now.strftime("%H:%M")
        duplicate = (who["id"], task["mealKind"]) in existing
        reason = (
            "此人已有本餐签认"
            if duplicate
            else "尚未到用餐时间"
            if not can_sign
            else ""
        )
        basis = generation.fingerprint(
            [
                user["id"],
                area,
                task["id"],
                task["occurrenceId"],
                day,
                task["time"],
                task["mealKind"],
                menu,
                task.get("assigneeId"),
                task.get("assigneeRole"),
                bed,
                place["id"],
                who["id"],
            ]
        )
        answer.append(
            {
                "taskId": task["id"],
                "occurrenceId": task["occurrenceId"],
                "day": day,
                "kind": task["mealKind"],
                "time": task["time"],
                "menu": menu,
                "residentId": who["id"],
                "name": who["name"],
                "bedId": bed,
                "bedLabel": beds[bed]["label"],
                "roomId": place["id"],
                "room": place["number"],
                "campusId": place["campusId"],
                "place": " / ".join(
                    (
                        place["campusName"],
                        place["buildingName"],
                        place["number"] + " 房",
                    )
                ),
                "basis": basis,
                "reason": reason,
            }
        )
    return sorted(
        answer, key=lambda r: (r["time"], r["place"], r["bedLabel"], r["taskId"])
    )


def _match(rows, target):
    room, bed, name = (target[key] for key in ("room", "bed", "name"))
    matches = []
    for row in rows:
        room_matches = not room or room == row["room"]
        slot = row["bedLabel"].rsplit("-", 1)[-1]
        bed_matches = not bed or bed in (
            row["bedLabel"],
            slot,
            slot.lstrip("0"),
            row["bedLabel"].replace("-", ""),
        )
        if room_matches and bed_matches and (not name or row["name"] == name):
            matches.append(row)
    if len(matches) != 1:
        raise ValueError("无法唯一核对口述中的老人，请改用姓名和床号，或从工单手动勾选")
    return matches[0]


def _dish(value):
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _selection(rows, spoken, task_id):
    if not spoken:
        return {task_id: []}
    all_people = spoken["mode"] == "all"
    selections = {r["taskId"]: [] for r in rows if all_people and not r["reason"]}
    for target in spoken["people"]:
        row = _match(rows, target)
        if row["reason"]:
            raise ValueError(row["reason"])
        selections[row["taskId"]] = []
    exceptions = set()
    for exception in spoken["exceptions"]:
        row = _match(rows, exception)
        ident = row["taskId"]
        if (
            ident in exceptions
            or row["reason"]
            or all_people
            and ident not in selections
        ):
            raise ValueError("例外名单须在同一份尚待签认的伙食工单中")
        exceptions.add(ident)
        if exception["entire"]:
            selections[ident] = row["menu"]
        else:
            menu = {_dish(item): item for item in row["menu"]}
            names = [_dish(value) for value in exception["dishes"]]
            if len(names) != len(set(names)) or any(name not in menu for name in names):
                raise ValueError("有口述菜品与工单菜单无法对应，请手动核对")
            selections[ident] = [menu[name] for name in names]
    return selections


def _area(value):
    return region.selection(value) if value else {}


def _given_rows(rows, spoken):
    if spoken and spoken["meal"]:
        rows = [r for r in rows if r["kind"] == spoken["meal"]]
    if spoken and spoken["rooms"]:
        requested = set(spoken["rooms"])
        rows = [r for r in rows if r["room"] in requested]
        if requested - {r["room"] for r in rows}:
            raise ValueError("口述房间不存在于本餐或当前授权范围")
        if len({r["roomId"] for r in rows}) != len(requested):
            raise ValueError("有重名房号，请先在房间页面限定区域")
    return rows


def preview(store, token, payload):
    if not isinstance(payload, dict) or set(payload) - {"taskId", "text", "region"}:
        raise ValueError("请选择待核对的伙食工单")
    area = _area(payload.get("region"))
    task_id = text_field(payload.get("taskId"), "工单编号", limit=100)
    text = text_field(payload.get("text"), "口述内容", limit=1500)
    if not (text or task_id):
        raise ValueError("请先选择工单或口述实际进食")
    now = store.now().astimezone(daily_life.LOCAL)
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        user = store.actor(db, token)
        rev, raw = db.execute(
            "SELECT revision,data FROM workspace WHERE id=1"
        ).fetchone()
        rows = _rows(db, json.loads(raw), user, now, area)
    if task_id and not any(row["taskId"] == task_id for row in rows):
        raise FileNotFoundError("伙食工单已完成、已取消或超出当前授权范围")
    if not any(not r["reason"] for r in rows):
        raise ValueError("当前范围内没有到点且可签认的今日伙食工单")
    spoken = None
    if text:
        if not voice_intent(text):
            raise ValueError("请直接说实际进食情况，并指出餐次、老人姓名或同批人员范围")
        spoken = generation.generate(
            store,
            user["id"],
            ["scheduled-meal-v1", text],
            VOICE_GUIDE,
            {"口述": text},
            lambda raw: _parse(raw, text),
            feature="care.scheduledMealVoiceParse",
            output_tokens=1000,
        )
        # Permissions, menu and room allocations may have changed during the provider call.
        with closing(store.connect()) as db, db:
            db.execute("BEGIN")
            actor = store.actor(db, token)
            if actor["id"] != user["id"]:
                raise PermissionError("会话身份已变化，请重新核对")
            current = store.now().astimezone(daily_life.LOCAL)
            if current.date() != now.date():
                raise ValueError("营业日期已经变化，请重新核对当日伙食工单")
            rev, raw = db.execute(
                "SELECT revision,data FROM workspace WHERE id=1"
            ).fetchone()
            rows = _rows(db, json.loads(raw), actor, current, area)
    rows = _given_rows(rows, spoken)
    groups = {}
    targets = [
        *(spoken["people"] if spoken else []),
        *(spoken["exceptions"] if spoken else []),
    ]
    for row in rows:
        groups.setdefault(row["occurrenceId"], []).append(row)
    if task_id:
        eligible_groups = [
            members
            for members in groups.values()
            if any(r["taskId"] == task_id for r in members)
        ]
    elif targets:
        eligible_groups = []
        for members in groups.values():
            try:
                for target in targets:
                    _match(members, target)
            except ValueError:
                continue
            if any(not r["reason"] for r in members):
                eligible_groups.append(members)
    else:
        eligible_groups = [
            members
            for members in groups.values()
            if any(not r["reason"] for r in members)
        ]
    if not eligible_groups:
        raise ValueError("没有一份授权范围内的今日伙食工单能对应整段口述")
    if len(eligible_groups) != 1:
        return {
            "choices": [
                {
                    "taskId": person["taskId"],
                    "label": " · ".join(
                        (
                            person["kind"],
                            person["time"],
                            person["place"],
                            "、".join(person["menu"]),
                        )
                    ),
                }
                for group in eligible_groups
                if (person := next(r for r in group if not r["reason"]))
            ]
        }
    members = eligible_groups[0]
    selected = _selection(members, spoken, task_id)
    if not any(row["taskId"] in selected and not row["reason"] for row in members):
        raise ValueError("请选择尚未签认且已到点的伙食工单")
    return {
        "revision": rev,
        "occurrenceId": members[0]["occurrenceId"],
        "day": members[0]["day"],
        "kind": members[0]["kind"],
        "region": area,
        "rows": [
            {
                **r,
                "selected": r["taskId"] in selected and not r["reason"],
                "omitted": selected.get(r["taskId"], []),
            }
            for r in members
        ],
    }


def _intake(menu, omitted):
    if not omitted:
        return "吃了" + "、".join(menu)
    kept = [item for item in menu if item not in omitted]
    if not kept:
        return "没吃这顿饭。没有吃" + "、".join(omitted)
    return "吃了" + "、".join(kept) + "。没有吃" + "、".join(omitted)


def confirm(db, state, user, payload, now):
    if (
        not isinstance(payload, dict)
        or set(payload) != {"occurrenceId", "entries", "region", "confirmed"}
        or payload["confirmed"] is not True
    ):
        raise ValueError("请先逐人核对实际进食及未吃菜品")
    now = now.astimezone(daily_life.LOCAL)
    occurrence = text_field(
        payload["occurrenceId"], "伙食工单批次", required=True, limit=100
    )
    entries = payload["entries"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("请至少核对一位老人")
    rows = {
        r["taskId"]: r
        for r in _rows(db, state, user, now, _area(payload["region"]))
        if r["occurrenceId"] == occurrence
    }
    chosen, seen_tasks, seen_people = [], set(), set()
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"taskId", "basis", "omitted"}
            or not isinstance(entry["taskId"], str)
            or entry["taskId"] in seen_tasks
            or not _list(entry["omitted"], lambda value: isinstance(value, str))
        ):
            raise ValueError("请检查逐人签认项目")
        row = rows.get(entry["taskId"])
        if not row or row["reason"] or row["basis"] != entry["basis"]:
            raise ValueError("菜单、床位、权限或签认状态已变化，请重新读取工单")
        if row["residentId"] in seen_people:
            raise ValueError("同一位老人每餐只可签认一次")
        omitted = set(entry["omitted"])
        if len(omitted) != len(entry["omitted"]) or omitted - set(row["menu"]):
            raise ValueError("未吃菜品必须来自本次工单所列菜单")
        chosen.append((row, [item for item in row["menu"] if item in omitted]))
        seen_tasks.add(row["taskId"])
        seen_people.add(row["residentId"])
    tasks = {t["id"]: t for t in state["tasks"]}
    # One signed event can cover a shared menu and time across multiple rooms;
    # differing campuses, time slots or menus have separate receipts.
    batches = {}
    for row, omissions in chosen:
        batches.setdefault(
            (row["campusId"], row["day"], row["kind"], row["time"], tuple(row["menu"])),
            [],
        ).append((row, _intake(row["menu"], omissions)))
    for (campus, day, kind, time, menu), people in batches.items():
        event_id = daily_life.record_scheduled_meal(
            db,
            user,
            now,
            uuid4().hex,
            campus,
            day,
            kind,
            time,
            list(menu),
            people,
        )
        for row, intake in people:
            plans.complete_task(
                state,
                {
                    "taskId": row["taskId"],
                    "operator": user["displayName"],
                    "operatorId": user["id"],
                    "bedId": row["bedId"],
                    "note": intake
                    if len(intake) <= 1000
                    else "详见个人生活时间线的实际进食记录",
                },
                day,
                scheduled_meal=True,
            )
            timeline.stamp_execution(db, state, row["taskId"], now)
            task = tasks[row["taskId"]]
            task["scheduledMealEventId"] = event_id
            task["mealIntake"] = intake
        daily_life.cancel_duplicate_meals(
            state, event_id, kind, day, (row["residentId"] for row, _ in people), now
        )
    return f"已签认 {len(chosen)} 位长者的{chosen[0][0]['kind']}，个人生活时间线已更新"
