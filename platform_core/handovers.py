"""Shift handovers preserve a dated workload snapshot and one named receipt."""

from hashlib import sha256
import json
import re

from . import access, campus_access, facility
from .care.records import append_record, get_resident, lookup, text_field


def recipients(db, actor, policy=None):
    access.require(actor, "care")
    accounts = db.execute(
        """SELECT * FROM accounts WHERE enabled=1 AND activation_pending=0 AND kind IN ('staff','owner')
        AND id<>? ORDER BY display_name,username""",
        (actor["id"],),
    )
    result = []
    for row in accounts:
        target = access._public(row)
        if not access.has(target, "care"):
            continue
        if policy is not None:
            target["facilityScope"] = campus_access.effective(
                target, policy(db, target)
            )
        if not _share_campus(actor, target):
            continue
        result.append({k: target[k] for k in ("id", "username", "displayName")})
    return {"recipients": result}


def _share_campus(actor, receiver):
    return not (campus_access.bound(actor) and campus_access.bound(receiver)) or bool(
        set(actor["facilityScope"]["campusIds"])
        & set(receiver["facilityScope"]["campusIds"])
    )


def workload(state, resident_id, today, include_vitals):
    result = {"pendingToday": 0, "completedToday": 0, "overdue": 0}
    for task in state["tasks"]:
        if resident_id and task["residentId"] != resident_id:
            continue
        if task["date"] == today and task["status"] == "已完成":
            result["completedToday"] += 1
        elif task["date"] == today and task["status"] == "待执行":
            result["pendingToday"] += 1
        elif task["date"] < today and task["status"] == "待执行":
            result["overdue"] += 1
    if include_vitals:
        result["openVitals"] = sum(
            v["status"] == "待复核"
            and (not resident_id or v["residentId"] == resident_id)
            for v in state["vitals"]
        )
    return result


def recipient(db, actor, account_id, policy):
    receiver = access.account(db, account_id)
    if (
        not receiver
        or not receiver["enabled"]
        or receiver["activationPending"]
        or receiver["kind"] not in ("staff", "owner")
        or receiver["id"] == actor["id"]
        or not access.has(receiver, "care")
    ):
        raise ValueError("请选择另一位在岗且具有照护权限的接班账号")
    if policy is not None:
        receiver = {
            **receiver,
            "facilityScope": campus_access.effective(receiver, policy(db, receiver)),
        }
    if not _share_campus(actor, receiver):
        raise PermissionError("接班账号不在双方共有分院")
    return receiver


def shared_residents(db, state, actor, receiver):
    ids = {r["id"] for r in state["residents"] if r["status"] == "在住"}
    for user in (actor, receiver):
        if not user or not user.get("facilityScope"):
            continue
        buildings = facility.directory(db, state, user)["buildings"]
        permitted = set()
        for building in buildings:
            permitted.update(
                facility.scope(db, state, user, buildingId=building["id"])[
                    "residentIds"
                ]
            )
        ids &= permitted
    return ids


SAFE_SERVICES = {
    "晨间生活照护",
    "床旁巡访",
    "午餐陪护",
    "午间巡视",
    "活动陪伴",
    "晚间巡房",
    "交班前巡访",
    "起居照护协助",
    "院内活动陪伴",
    "日常沟通陪伴",
    "执行个体照护计划",
}
SAFE_KINDS = {"日常照护", "生活照料", "膳食照护", "活动支持", "护理复评"}


def draft(db, state, actor, receiver, resident_id, today):
    access.require(actor, "care")
    allowed = shared_residents(db, state, actor, receiver)
    if resident_id and resident_id not in allowed:
        raise PermissionError("所选长辈超出双方可交接的在住范围")
    names = {r["id"]: r["name"] for r in state["residents"] if r["id"] in allowed}
    aliases = {
        name
        for name in (actor["displayName"], actor["username"])
        if db.execute(
            "SELECT count(*) FROM accounts WHERE display_name=? OR username=?",
            (name, name),
        ).fetchone()[0]
        == 1
    }
    groups = {"completedToday": [], "pendingToday": [], "overdue": []}
    for t in state["tasks"]:
        rid = t.get("residentId")
        if rid not in allowed or (resident_id and rid != resident_id):
            continue
        completed = t.get("status") == "已完成"
        related = t.get("operatorId") == actor["id"] or (
            not t.get("operatorId") and t.get("operator") in aliases
        )
        assigned = t.get("assigneeId") == actor["id"] or (
            not t.get("assigneeId") and t.get("assignee") in aliases
        )
        if not resident_id and not (assigned or (completed and related)):
            continue
        if completed and (t.get("completedAt") or t.get("date")) == today:
            key = "completedToday"
        elif t.get("status") == "待执行" and t["date"] <= today:
            key = "pendingToday" if t["date"] == today else "overdue"
        else:
            continue
        title = (
            t.get("title")
            if t.get("title") in SAFE_SERVICES
            else t.get("kind")
            if t.get("kind") in SAFE_KINDS
            else "照护工单"
        )
        groups[key].append((t["date"], t.get("time", ""), t["id"], rid, title))
    for items in groups.values():
        items.sort()
    stamp = sha256(
        json.dumps(
            [today, actor["id"], receiver["id"], resident_id, groups], sort_keys=True
        ).encode()
    ).hexdigest()
    scope = names[resident_id] if resident_id else "本人当班照护"
    lines = [f"{today} 交班小结 · {scope}"]
    counts = {k: len(v) for k, v in groups.items()}
    for key, label in (
        ("completedToday", "今日已完成"),
        ("pendingToday", "当日待执行"),
        ("overdue", "逾期未完成"),
    ):
        items = groups[key]
        samples = []
        for day, clock, _, rid, title in items[:3]:
            slot = (day[5:] + " " if key == "overdue" else "") + clock
            samples.append(
                " ".join(
                    filter(None, (slot, names[rid] if not resident_id else "", title))
                )
            )
        tail = "，另有 " + str(len(items) - 3) + " 项" if len(items) > 3 else ""
        lines.append(
            f"{label} {len(items)} 项"
            + (" · " + "、".join(samples) + tail if samples else "")
        )
    return dict(
        note="\n".join(lines),
        stamp=stamp,
        snapshot=counts,
        date=today,
        scope=scope,
        residentIds=sorted({item[3] for items in groups.values() for item in items}),
    )


def create(db, state, payload, actor, now, policy=None):
    assigned = "assigneeId" in payload
    if set(payload) - {
        "assigneeId" if assigned else "assignee",
        "residentId",
        "note",
        "draftStamp",
    }:
        raise ValueError("交班表单含有未知字段")
    resident_id = text_field(payload.get("residentId"), "长辈编号", limit=100)
    if resident_id:
        get_resident(state, resident_id)
    receiver = None
    if assigned:
        account_id = text_field(
            payload["assigneeId"], "接班账号", required=True, limit=100
        )
        receiver = recipient(db, actor, account_id, policy)
        assignee = receiver["displayName"]
    else:
        # Old clients submit a name with no stable account identity.
        assignee = text_field(payload.get("assignee"), "接班人", required=True)
    today = now.date().isoformat()
    generated = None
    if "draftStamp" in payload:
        if not receiver:
            raise ValueError("交班初稿必须指定实名接班人")
        generated = draft(db, state, actor, receiver, resident_id, today)
        if generated["stamp"] != payload["draftStamp"]:
            raise ValueError("交班范围或当班工单已变动，请重新生成初稿并核对")
    elif actor.get("facilityScope") or (receiver and receiver.get("facilityScope")):
        if not resident_id or resident_id not in shared_residents(
            db, state, actor, receiver
        ):
            raise PermissionError("请选择双方有权交接的在住长辈")
    counts = (
        generated["snapshot"]
        if generated
        else workload(
            state,
            resident_id,
            today,
            access.has(actor, "clinical") and access.has(receiver, "clinical"),
        )
    )
    summary = (
        f"当日待执行 {counts['pendingToday']} 项，逾期待执行 {counts['overdue']} 项，"
        f"当日已完成 {counts['completedToday']} 项。"
    )
    append_record(
        state,
        "handovers",
        date=today,
        residentId=resident_id,
        senderId=actor["id"],
        senderName=actor["displayName"],
        assigneeId=receiver["id"] if receiver else "",
        assignee=assignee,
        createdAt=now.isoformat(timespec="seconds"),
        snapshot=counts,
        summary=summary,
        **(
            {
                "draftScope": "resident" if resident_id else "personal",
                "draftDate": today,
                "draftResidentIds": generated["residentIds"],
            }
            if generated
            else {}
        ),
        note=text_field(payload.get("note"), "交接要点"),
        status="待签收" if assigned else "历史记录",
    )
    if assigned:
        return f"{actor['displayName']}向{assignee}提交班次交接"
    return f"{actor['displayName']}为{assignee}登记历史交班记录"


def pending_record(state, payload):
    record = lookup(
        state,
        "handovers",
        text_field(payload.get("handoverId"), "交班记录编号", required=True, limit=100),
    )
    if not record.get("assigneeId"):
        raise ValueError("历史交班记录没有指定接班账号")
    if record["status"] != "待签收":
        raise ValueError(f"交班记录{record['status']}，请核对最新状态")
    return record


def accept(state, payload, actor, now):
    if set(payload) - {"handoverId", "note"}:
        raise ValueError("签收表单含有未知字段")
    record = pending_record(state, payload)
    if record["assigneeId"] != actor["id"]:
        raise PermissionError("仅指定的接班账号可以签收")
    record.update(
        status="已签收",
        acceptedAt=now.isoformat(timespec="seconds"),
        acceptedById=actor["id"],
        acceptedByName=actor["displayName"],
        receiptNote=text_field(payload.get("note"), "签收备注"),
    )
    return f"{actor['displayName']}签收了{record['senderName']}的班次交接"


def withdraw(state, payload, actor, now):
    if set(payload) - {"handoverId", "reason"}:
        raise ValueError("撤回表单含有未知字段")
    record = pending_record(state, payload)
    if record["senderId"] != actor["id"]:
        raise PermissionError("仅原交班人可以撤回")
    record.update(
        status="已撤回",
        withdrawnAt=now.isoformat(timespec="seconds"),
        withdrawnById=actor["id"],
        withdrawnByName=actor["displayName"],
        withdrawReason=text_field(payload.get("reason"), "撤回原因", required=True),
    )
    return f"{actor['displayName']}撤回了交给{record['assignee']}的班次交接"


def visible(record, include_vitals):
    row = dict(record)
    if not row.get("assigneeId"):
        row["status"] = "历史记录"
    if include_vitals:
        return row
    if "snapshot" in row:
        row["snapshot"] = {
            k: v for k, v in row["snapshot"].items() if k != "openVitals"
        }
    else:
        # Previous versions embedded the clinical count in the generated summary.
        match = re.match(
            r"今日照护工单 \d+ 项，已完成 \d+ 项，待完成 \d+ 项。",
            row.get("summary", ""),
        )
        row["summary"] = match[0] if match else "历史交班记录"
    return row
