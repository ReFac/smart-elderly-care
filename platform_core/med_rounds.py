"""One staff signature per resident and Shanghai medication round."""

from contextlib import closing
import json
from pathlib import Path
import re
import struct
import sys
import zlib
from urllib.parse import urlencode

from . import access, campus_access, facility
from .care import legacy_bed_cards
from .care.clinical import give_medication, vital
from .care.records import text_field
from .care.residency import current_cards
from .provider import generation


SLOTS = ("凌晨", "早晨", "中午", "晚上", "夜间")
SLOT_START = dict(zip(SLOTS, (0, 5, 11, 16, 21)))
PARSE = """把这次服药现场报告解析成查询条件，只返回 JSON。不办理业务、不提供用药建议。
{"targets":[{"room":"房号","bed":"床号","name":"姓名"}],"exceptions":[{"room":"","bed":"","name":"","reason":"原话中的未服原因"}],"outcome":"taken 或 notGiven","reason":"","slots":["凌晨/早晨/中午/晚上/夜间，未明确用空数组，多个时段逐一列出"],"unclear":false}
只解析今天、本次实际发生的报告。其他日期、语意不清或问句标记 unclear。多个明确餐次逐一列在 slots。若例外只涉及部分时段，在例外对象内加 slots 数组限定。每个号码、姓名和理由须为原文片段，不增补、猜测或转换号码。未说的字段填空串。
多房全员逐房列条件；指定个人时把房号、床号和姓名放在同一条件。除外的人分别列入 exceptions，包括因无需喂药而未服的人。有例外但无法辨别是谁则 unclear。绝不解释为停药指示。"""


def init(db):
    legacy_bed_cards.init(db)
    db.execute("""CREATE TABLE IF NOT EXISTS medication_round_receipts(
        id TEXT PRIMARY KEY, resident TEXT NOT NULL, day TEXT NOT NULL, slot TEXT NOT NULL,
        details TEXT NOT NULL, UNIQUE(resident,day,slot))""")


def slot_of(hour):
    return next(slot for slot in reversed(SLOTS) if hour >= SLOT_START[slot])


def actor_allowed(user):
    if user["kind"] not in ("staff", "owner"):
        raise PermissionError("仅当班照护人员可核对服药")
    access.require(user, "care")


def people(db, state, user):
    allowed = campus_access.allowed_beds(db, user, include_rooms=True)
    places = {
        r["bedId"]: r
        for r in db.execute(
            f"SELECT fb.bedId,{facility.ROOM_FIELDS} FROM {facility.ROOM_TABLE} JOIN facility_beds fb ON fb.roomId=r.id"
        )
    }
    beds = {b["id"]: b for b in state["beds"]}
    result = []
    cards = current_cards(state, state["residents"])
    for p in state["residents"]:
        bid = p.get("bedId")
        if (
            p["status"] != "在住"
            or bid not in places
            or (allowed is not None and bid not in allowed)
        ):
            continue
        bed, room = beds.get(bid), places[bid]
        if not bed or bed["residentId"] != p["id"]:
            continue
        card = cards.get(p["id"], {}).get("code", "")
        result.append(
            dict(
                residentId=p["id"],
                name=p["name"],
                bedId=bid,
                bed=bed["label"],
                room=room["number"],
                roomId=room["id"],
                card=card,
                location=" / ".join(
                    (
                        room["campusName"],
                        room["buildingName"],
                        room["floorLabel"],
                        room["number"] + " 房",
                    )
                ),
            )
        )
    return result


def valid_parse(raw, text):
    invalid = ValueError("口述范围不够明确，请说出今天的房间、床号或姓名，或手动选择")
    if (
        not isinstance(raw, dict)
        or raw.get("unclear") is not False
        or raw.get("outcome") not in ("taken", "notGiven")
    ):
        raise invalid
    slots = raw.get("slots")
    if (
        not isinstance(slots, list)
        or any(s not in SLOTS for s in slots)
        or len(slots) != len(set(slots))
    ):
        raise invalid
    for group in ("targets", "exceptions"):
        entries = raw.get(group)
        if (
            not isinstance(entries, list)
            or len(entries) > 30
            or (group == "targets" and not entries)
        ):
            raise invalid
        for item in entries:
            keys = {"room", "bed", "name"} | (
                {"reason"} if group == "exceptions" else set()
            )
            if (
                not isinstance(item, dict)
                or set(item) - ({"slots"} if group == "exceptions" else set()) != keys
                or not any(item[k] for k in ("room", "bed", "name"))
            ):
                raise invalid
            if "slots" in item and (
                not isinstance(item["slots"], list)
                or not item["slots"]
                or any(s not in slots for s in item["slots"])
            ):
                raise invalid
            if any(
                not isinstance(item[k], str)
                or len(item[k]) > 120
                or item[k] not in text
                for k in keys
            ):
                raise invalid
    if not isinstance(raw.get("reason"), str) or raw["reason"] not in text:
        raise invalid
    if re.search(r"除[了外]|但是|但.+没|其中.+没", text) and not raw["exceptions"]:
        raise invalid
    return raw


def match(entries, selector, *, individual=False):
    room, bed, name = (selector[k] for k in ("room", "bed", "name"))
    result = []
    for row in entries:
        suffix = row["bed"].rsplit("-", 1)[-1]
        if room and room != row["room"]:
            continue
        if bed and bed not in (
            row["bed"],
            suffix,
            suffix.lstrip("0"),
            row["bed"].replace("-", ""),
        ):
            continue
        if not name or name == row["name"]:
            result.append(row)
    all_in_room = room and not (bed or name) and len({r["roomId"] for r in result}) == 1
    if not result or (len(result) != 1 and (individual or not all_in_room)):
        raise ValueError("无法唯一匹配本班可见的房间或床位，请手动选择并核对姓名")
    return result


def current_orders(state, person, now, slot):
    day, stamp = now.date().isoformat(), now.strftime("%Y-%m-%dT%H:%M")
    return sorted(
        (
            {
                "id": m["id"],
                "name": m["name"],
                "instruction": m["instruction"],
                "scheduledAt": m["scheduledAt"],
                "warnings": m.get("warnings", []),
            }
            for m in state["medications"]
            if m["residentId"] == person["residentId"]
            and m["status"] == "待执行"
            and re.fullmatch(day + r"T\d\d:\d\d", m.get("scheduledAt", ""))
            and m["scheduledAt"] <= stamp
            and slot_of(int(m["scheduledAt"][11:13])) == slot
        ),
        key=lambda m: (m["scheduledAt"], m["id"]),
    )


def visible_receipt(raw, allowed):
    record = json.loads(raw)
    if allowed is not None and record["bedId"] not in allowed:
        return {"restricted": True}
    return record


def region_selector(region):
    region = {} if region is None else region
    region_keys = {"campusId", "buildingId", "floorId", "roomId"}
    if (
        not isinstance(region, dict)
        or set(region) - region_keys
        or any(not isinstance(v, str) for v in region.values())
    ):
        raise ValueError("对话区域无效")
    return region


def entry(db, state, person, user, now, slot, allowed, region):
    day = now.date().isoformat()
    existing = db.execute(
        "SELECT details FROM medication_round_receipts WHERE resident=? AND day=? AND slot=?",
        (person["residentId"], day, slot),
    ).fetchone()
    orders = (
        current_orders(state, person, now, slot) if access.has(user, "clinical") else []
    )
    basis = generation.fingerprint(
        [user["id"], day, slot, person, orders, access.has(user, "clinical"), region]
    )
    return {
        **{k: v for k, v in person.items() if k != "card"},
        "basis": basis,
        "orders": orders,
        "receipt": visible_receipt(existing[0], allowed) if existing else None,
    }


def preview(store, token, payload):
    if not isinstance(payload, dict) or set(payload) - {
        "text",
        "roomId",
        "residentId",
        "cardCode",
        "slot",
        "region",
    }:
        raise ValueError("请指定一种核对范围")
    region = region_selector(payload.get("region"))
    keys = set(payload) - {"slot", "region"}
    if len(keys) > 1 or ("slot" in payload and payload["slot"] not in SLOTS):
        raise ValueError("请选择一个核对范围和一个服药时段")
    parsed = None
    if "text" in keys:
        with closing(store.connect()) as db:
            initial = store.actor(db, token)
            actor_allowed(initial)
        text = text_field(payload["text"], "本次口述", required=True, limit=1500)
        parsed = generation.generate(
            store,
            initial["id"],
            "med-round/" + generation.fingerprint([text, PARSE]),
            PARSE,
            {"口述": text},
            lambda obj: valid_parse(obj, text),
            feature="medication.voiceParse",
            output_tokens=1500,
        )
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        user = store.actor(db, token)
        actor_allowed(user)
        now = store.now()
        state = json.loads(
            db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
        )
        visible = people(db, state, user)
        if region:
            area = facility.scope(db, state, user, agent=True, **region)
            beds = set(area["bedIds"])
            visible = [p for p in visible if p["bedId"] in beds]
        rooms = {p["roomId"]: p["location"] for p in visible}
        requested = (
            [payload["slot"]]
            if "slot" in payload
            else (parsed and parsed["slots"]) or [slot_of(now.hour)]
        )
        slots = [s for s in SLOTS if s in requested and SLOT_START[s] <= now.hour]
        if not slots:
            raise ValueError("尚未到达口述或选定的服药时段，请核对时段")
        allowed = campus_access.allowed_beds(db, user, include_rooms=True)
        base = {
            "availableSlots": [s for s in SLOTS if SLOT_START[s] <= now.hour],
            "rooms": [
                {"id": i, "label": label}
                for i, label in sorted(rooms.items(), key=lambda a: a[1])
            ],
            "day": now.date().isoformat(),
            "slot": slots[0],
            "futureSlots": [s for s in requested if s not in slots],
            "clinical": access.has(user, "clinical"),
        }
        if not keys:
            return {**base, "people": []}
        exceptions = {}
        if parsed:
            selected = {
                r["residentId"]: r for s in parsed["targets"] for r in match(visible, s)
            }
            for selector in parsed["exceptions"]:
                person = match(list(selected.values()), selector, individual=True)[0]
                for slot in selector.get("slots", slots):
                    exceptions[(person["residentId"], slot)] = selector["reason"]
            rows = list(selected.values())
        else:
            key = next(iter(keys))
            field = "card" if key == "cardCode" else key
            if not isinstance(payload[key], str) or not payload[key].strip():
                raise ValueError("请指定有效的床位或核对对象")
            rows = [r for r in visible if r[field] == payload[key]]
            if not rows:
                raise ValueError(
                    "未找到可核对的当前床位，请检查名单或重新扫描有效床头卡"
                )
        entries = []
        for row in sorted(rows, key=lambda r: (r["location"], r["bed"])):
            rid = row["residentId"]
            for slot in slots:
                item = entry(db, state, row, user, now, slot, allowed, region)
                if keys == {"residentId"}:
                    history = db.execute(
                        "SELECT details FROM medication_round_receipts WHERE resident=? ORDER BY day DESC,rowid DESC LIMIT 60",
                        (rid,),
                    )
                    item["history"] = [
                        r
                        for (raw,) in history
                        if not (r := visible_receipt(raw, allowed)).get("restricted")
                    ]
                entries.append(
                    {
                        **item,
                        "roundSlot": slot,
                        "outcome": "notGiven"
                        if (rid, slot) in exceptions
                        else parsed["outcome"]
                        if parsed
                        else "taken",
                        "note": exceptions.get(
                            (rid, slot), parsed["reason"] if parsed else ""
                        ),
                    }
                )
        return {**base, "people": entries}


def command(db, state, user, action, p, now):
    actor_allowed(user)
    if (
        action != "care.confirmMedRound"
        or set(p)
        - {
            "residentId",
            "basis",
            "slot",
            "day",
            "outcome",
            "note",
            "medicationIds",
            "cardCode",
            "confirmed",
            "region",
            "observedTime",
        }
        or p.get("confirmed") is not True
    ):
        raise ValueError("请逐人核对后签名")
    day, slot, outcome = now.date().isoformat(), p.get("slot"), p.get("outcome")
    if p.get("day") != day or slot not in SLOTS or outcome not in ("taken", "notGiven"):
        raise ValueError("请核对今天的日期、时段和实际服药情况")
    if now.hour < SLOT_START[slot]:
        raise ValueError("不能提前签认尚未开始的服药时段")
    row = next(
        (r for r in people(db, state, user) if r["residentId"] == p.get("residentId")),
        None,
    )
    if not row:
        raise PermissionError("当前床位不在本人获授权的在住名单中")
    region = region_selector(p.get("region"))
    if (
        region
        and row["bedId"]
        not in facility.scope(db, state, user, agent=True, **region)["bedIds"]
    ):
        raise PermissionError("床位超出当前对话选择的区域")
    item = entry(
        db,
        state,
        row,
        user,
        now,
        slot,
        campus_access.allowed_beds(db, user, include_rooms=True),
        region,
    )
    observed = p.get("observedTime", "")
    if not isinstance(observed, str) or (
        observed
        and (
            not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", observed)
            or observed > now.strftime("%H:%M")
            or slot_of(int(observed[:2])) != slot
        )
    ):
        raise ValueError("实际观察时间须在本时段内，且不能晚于当前时间")
    if item["receipt"] or item["basis"] != p.get("basis"):
        raise ValueError("本次已签认或床位、医嘱已变化，请重新查看")
    card = p.get("cardCode", "")
    if card and card != row["card"]:
        raise ValueError("床头卡已失效，请重新核验")
    ids = p.get("medicationIds", [])
    if (
        not isinstance(ids, list)
        or any(not isinstance(i, str) for i in ids)
        or len(ids) != len(set(ids))
    ):
        raise ValueError("请选择本人的已核对医嘱")
    allowed = {order["id"] for order in item["orders"]}
    if not set(ids) <= allowed or (outcome == "notGiven" and ids):
        raise ValueError("只能签认本次实际服用、已到执行时间的本人医嘱")
    note = text_field(
        p.get("note"), "未服原因或现场说明", required=outcome == "notGiven", limit=500
    )
    for order_id in ids:
        give_medication(
            state,
            dict(
                medicationId=order_id,
                operator=user["displayName"],
                nowLocal=now.strftime("%Y-%m-%dT%H:%M"),
                executionNote=note,
            ),
            day,
        )
        next(m for m in state["medications"] if m["id"] == order_id)["operatorId"] = (
            user["id"]
        )
    if outcome == "notGiven":
        vital(
            state,
            dict(
                residentId=row["residentId"],
                metric=slot + "服药核对",
                value="现场报告未服",
                abnormal=True,
                operator=user["displayName"],
                note=note,
            ),
            day,
        )
    receipt = dict(
        residentId=row["residentId"],
        roomId=row["roomId"],
        bedId=row["bedId"],
        room=row["location"],
        bed=row["bed"],
        checkedCardCode=card,
        observedTime=observed,
        slot=slot,
        day=day,
        outcome=outcome,
        note=note,
        medicationIds=ids,
        actorId=user["id"],
        actor=user["displayName"],
        position=user.get("role", ""),
        at=now.isoformat(),
    )
    db.execute(
        "INSERT INTO medication_round_receipts VALUES(?,?,?,?,?)",
        (
            generation.fingerprint([row["residentId"], day, slot]),
            row["residentId"],
            day,
            slot,
            json.dumps(receipt, ensure_ascii=False),
        ),
    )
    detail = "已观察服药" if outcome == "taken" else "未服，已交护士复核"
    return f"{user['displayName']}签认{row['name']}（{row['room']}）{slot}服药情况：{detail}"


def qr(store, token, code, origin):
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        user = store.actor(db, token)
        if user["kind"] not in ("owner", "staff") or not any(
            access.has(user, g) for g in facility.READ_GRANTS
        ):
            raise PermissionError("没有床头卡查阅权限")
        state = json.loads(
            db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
        )
        person = next((p for p in people(db, state, user) if p["card"] == code), None)
        if not person:
            raise FileNotFoundError("床头卡已失效或不在本人可查范围内")
    try:
        import qrcode
    except ModuleNotFoundError:
        # Existing on-prem installations may have installed this shared dependency with payments.
        runtime = Path(__file__).resolve().parents[1] / ".local" / "payment-runtime"
        if runtime.is_dir() and str(runtime) not in sys.path:
            sys.path.append(str(runtime))
        try:
            import qrcode
        except ModuleNotFoundError:
            raise ValueError(
                "缺少生成二维码的组件，请安装 requirements-storage.txt"
            ) from None

    qr_code = qrcode.QRCode(border=4, box_size=4)
    qr_code.add_data(
        origin.rstrip("/")
        + "/#care?"
        + urlencode({"bedcard": code, "bed": person["bed"]})
    )
    qr_code.make(fit=True)
    matrix = qr_code.get_matrix()
    size = 4 * len(matrix)
    # Grayscale PNG generated from the library matrix without a Pillow runtime dependency.
    pixels = b"".join(
        (b"\x00" + b"".join((b"\x00" if bit else b"\xff") * 4 for bit in line)) * 4
        for line in matrix
    )

    def chunk(tag, data):
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">2I5B", size, size, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )
