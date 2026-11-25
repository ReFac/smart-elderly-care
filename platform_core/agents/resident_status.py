"""Recognize spoken resident status questions and resolve locations inside the current assignment."""

from dataclasses import dataclass
import re
from unicodedata import normalize

from .. import access_policy, campus_access, care_areas, facility


def _key(value):
    return "".join(normalize("NFKC", value).casefold().split())


@dataclass(frozen=True)
class Location:
    place: str = ""
    room: str = ""
    bed: str = ""


WHEN = r"(?:今天|今日|目前|现在|最近)?"
PEOPLE = r"(?:老人|长辈|长者|住户|导人气)(?:们)?"
STATUS = r"(?:身体健康|健康状况|身体状况|身体情况|健康情况|精神状态|健康|身体|状况|情况|状态)?"
ASK = r"(?:如何|怎么样了?|咋样了?|正常|健康|有没有异常|有异常|还好吗?|好吗)"
ENDING = WHEN + r"的?(?:总体|整体|大体|都|各自)?" + STATUS + r"(?:都)?" + ASK + r"[吗么呀啊呢]?"
PREFIX = r"(?:请问|想问一下|帮我看看|看看|看一下|我想了解)?"
GLOBAL = re.compile(PREFIX + WHEN + r"的?(?:我们院|养老院|院里|院内|全院|在住)?的?" + PEOPLE + r"的?" + ENDING)
NUMBER = r"[a-z]?\d+[a-z]?"
BED = NUMBER + r"(?:[-－][0-9a-z]+)?"
# Buildings/campuses are matched by their complete displayed name after authorization.
PLACE = r"(?P<place>[\w·]{0,40}?(?:楼|栋|院区|分院|本部)(?:\d+层)?)?"
WHERE = re.compile(PLACE + r"(?:(?P<room>" + NUMBER + r")号?(?:病房|房间|房|室))?(?:第?(?P<bed>" + BED + r")号?(?:床位|床))?")
LOCAL = re.compile(PREFIX + WHEN + r"(?P<where>.+?)的?(?:" + PEOPLE + r")?的?" + ENDING)
FOLLOWUP = re.compile(r"(?:那|看看|是指|是)?(?P<where>.+?)(?:呢|吧)?")


def question(text, *, followup=False, previous=None):
    query = _key(text).strip("。，,！？?!")
    if previous and re.fullmatch(r"(?:那)?(?:他们|她们|这位长辈|这间房|这个床位)的?" + ENDING, query):
        return Location(**previous)
    if GLOBAL.fullmatch(query):
        return Location()
    match = LOCAL.fullmatch(query)
    if match is None and followup:
        match = FOLLOWUP.fullmatch(query)
    if match:
        where = WHERE.fullmatch(match["where"])
        if where and (where["room"] or where["bed"]):
            return Location(*(where[k] or "" for k in ("place", "room", "bed")))
    return None


def _slot_key(value):
    return str(int(value)) if value.isdecimal() else value


def _place_matches(place, meta):
    if not place:
        return True
    building, campus = meta.get("buildingName", ""), meta.get("campusName", "")
    floor = meta.get("floorLabel", "")
    return place in {_key(p + f) for p in (building, campus, campus + building)
                     for f in ("", floor) if p}


def _room_label(meta):
    return " ".join(meta[k] for k in ("campusName", "buildingName", "floorLabel", "roomNumber")) + " 房"


def select(db, state, actor, selected, location):
    """Return an exact bed set, its display name, or a clarification without health data."""
    allowed = campus_access.allowed_beds(db, actor, include_rooms=True)
    within = set(selected["bedIds"]) if selected else None
    beds = {b["id"]: b for b in state["beds"] if facility.operational_bed(b)
            and (allowed is None or b["id"] in allowed) and (within is None or b["id"] in within)}
    by_bed = care_areas.bed_directory(db, beds)
    matches, same_number_rooms = [], {}
    for bid, bed in beds.items():
        meta = by_bed.get(bid, {})
        if not _place_matches(location.place, meta):
            continue
        room = _key(meta.get("roomNumber", ""))
        label = _key(bed["label"]).split("·")[-1]
        if location.room and room != location.room:
            continue
        if location.bed and not location.room and room == location.bed:
            same_number_rooms[meta["roomId"]] = meta
        if location.bed:
            slot = label.rsplit("-", 1)[-1]
            if location.bed != label and not (location.room and _slot_key(slot) == _slot_key(location.bed)):
                continue
        matches.append((bid, meta))
    if not matches:
        if same_number_rooms:
            rooms = "、".join(_room_label(m) for m in list(same_number_rooms.values())[:4])
            return set(), "", f"当前范围内有{rooms}，没有床号恰好为 {location.bed} 的床位。你想看整间房，还是其中一张床？可以回复“{location.bed}房”或完整床号。"
        return set(), "", "在你当前可查看的范围内没有找到对应位置。请核对房间号或完整床号。"
    room_ids = {meta.get("roomId") for _, meta in matches}
    if len(room_ids) > 1 or (location.bed and len(matches) > 1):
        options = list(dict.fromkeys(_room_label(m) for _, m in matches if m))[:4]
        return set(), "", "有多个位置符合这个编号，请补充院区、楼栋或楼层，再写房号或完整床号。" + "、".join(options)
    bid, meta = matches[0]
    label = (_room_label(meta) if meta else "") + (" " + beds[bid]["label"] + " 床" if location.bed else "")
    return {i for i, _ in matches}, label.strip(), ""


def can_read(actor):
    return actor["kind"] in {"owner", "staff"} and any(
        access_policy.has(actor, p) for p in ("health.overview", "clinical", "alerts", "care")
    )
