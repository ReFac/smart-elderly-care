"""Resolve spoken workspace filters against business choices available to this account."""

import re
from unicodedata import normalize

from .. import facility
from . import chat_navigation as navigation

FILTER = re.compile(r"(?:筛选(?:出|为|到)?|过滤到?|只看|仅看|限定在)")
SWITCH = re.compile(r"切换到")
BED_PAGE = re.compile(r"床位|病房|房型|房间")
ACT = re.compile(r"打开|进入|跳转|带我|选出|切换|筛选|过滤|只看|仅看|限定")
EXAMPLE = re.compile(r"比如|例如|假如|假设|如果|怎么|如何|教程|演示|为何")
FLOOR = re.compile(r"(1[0-9]|[1-9一两二三四五六七八九十])\s*(?:楼|层)")
STATUS = {"vacant": ("空闲", "空床", "空置"), "occupied": ("已入住", "在住床位")}
QUOTES = '「」『』“”"‘’'


def text_key(text):
    return "".join(normalize("NFKC", text).casefold().split()).strip(QUOTES)


def request(question, current_page="", previous_question=""):
    if (navigation.NEGATIVE.search(question) or navigation.public_topic(question)
        or re.search(r"不想|别筛|别切|无需", question)):
        return None
    if navigation.ROOM_EDIT.search(question):
        return None
    text = normalize("NFKC", question).translate(str.maketrans("", "", QUOTES))
    match = FILTER.search(text) or SWITCH.search(text)
    if not match:
        return None
    named = navigation.named(text, navigation.PAGES)
    explicit = "beds" in {page.route for page in named}
    if not explicit and not (
        not named and (current_page in ("beds", "rooms") or BED_PAGE.search(previous_question))
    ):
        return None
    term = text[match.end():].strip(" ，,。？?！!：:")[:100]
    if match[0] == "切换到" and any(
        term == label for page in named for label in (page.title, *page.aliases)
    ):
        return None
    return term, bool(ACT.search(text) and not EXAMPLE.search(text))


def name_matches(term, rows, name_field):
    key = text_key(term)
    exact = [row for row in rows if text_key(row[name_field]) in key]
    names = [text_key(row[name_field]) for row in exact]
    return [row for row, name in zip(exact, names)
            if not any(name != other and name in other for other in names)]


def resolve(db, state, user, requested, selected):
    term, automatic = requested
    if not term:
        return [], False
    try:
        directory = facility.directory(db, state, user)
    except PermissionError:
        return [], False
    selected = selected or {}
    base = {key: selected[value] for key, value in (
        ("campus", "campusId"), ("building", "buildingId"),
        ("floor", "floorId"), ("room", "roomId"),
    ) if selected.get(value)}
    buildings = [
        row for row in directory["buildings"]
        if (not base.get("campus") or row["campusId"] == base["campus"])
        and (not base.get("building") or row["id"] == base["building"])
    ]
    floor = FLOOR.search(term)
    capacity = navigation.room_capacity(term)
    status = next((v for v, labels in STATUS.items() if any(label in term for label in labels)), None)
    location = FLOOR.sub("", term)
    location = navigation.ROOM_CAPACITY.sub("", location)
    location = re.sub(r"\d+\s*(?:间|张)|[一两二三四五六七八九十]+\s*(?:间|张)", "", location)
    location = re.sub(
        r"空闲|空床|空置|已入住|在住床位|床位管理|全部床位|床位列表|房间|床位|楼栋|显示|查看|选择",
        "", text_key(location),
    )
    campuses = name_matches(location, [
        row for row in directory["campuses"] if not base.get("campus") or base["campus"] == row["id"]
    ], "name")
    campus_ids = {row["id"] for row in campuses}
    if campus_ids:
        buildings = [row for row in buildings if row["campusId"] in campus_ids]
    matched = name_matches(location, buildings, "name")
    known = {text_key(row["name"]) for row in (*matched, *campuses)}
    remainder = location
    for name in sorted(known, key=len, reverse=True):
        remainder = remainder.replace(name, "")
    remainder = re.sub(r"以及|或者|里面|的|和|与|及|或|里|再|[,、]", "", remainder)
    if remainder:
        if matched or not re.fullmatch(r"[\w\u3400-\u9fff]{2,24}", remainder):
            return [], False
        matched = [row for row in buildings if remainder in text_key(row["name"])]
        if not matched:
            return [], False
    if not (matched or campuses or floor or capacity or status):
        return [], False

    extra = {}
    if capacity:
        extra = {"capacity": str(capacity[0]), "limit": str(capacity[1])}
    if status:
        extra["status"] = status
    choices = []
    floor_number = navigation.ROOM_NUMBER.get(floor[1], int(floor[1]) if floor[1].isdigit() else -1) if floor else None
    for building in matched or (buildings if floor else []):
        destination = {**base, "campus": building["campusId"], "building": building["id"], **extra}
        label = " · ".join((building["campusName"], building["name"]))
        if floor_number is not None:
            target = next((f for f in building["floors"] if f["number"] == floor_number
                           and (not base.get("floor") or f["id"] == base["floor"])), None)
            if not target:
                continue
            destination["floor"] = target["id"]
            label += " · " + target["label"]
        choices.append(navigation.Page("beds", label + "床位", tab="all", params=tuple(destination.items())).link())
    if not matched and not floor:
        for campus in campuses:
            choices.append(navigation.Page("beds", campus["name"] + "床位", tab="all",
                                           params=tuple({**base, "campus": campus["id"], **extra}.items())).link())
        if not choices and extra:
            label = "空闲床位" if status == "vacant" else "已入住床位" if status else "查看所选房型"
            choices.append(navigation.Page("beds", label, tab="all", params=tuple({**base, **extra}.items())).link())
    return choices[:4], automatic and len(choices) == 1
