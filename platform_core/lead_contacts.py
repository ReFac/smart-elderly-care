"""Consented enquiries, reception records and telephone-confirmed appointments."""

import json
import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

from . import access, facility, lead_directory, portal, visit_schedule
from .care.records import append_record, text_field
from .profile_fields import phone_number as _phone

LOCAL = ZoneInfo("Asia/Shanghai")
OUTCOMES = ("有参观意向", "继续联系", "未接通", "暂无意向")
PUBLIC_EVENTS = {"visit": "申请参观", "callback": "请求回电", "consent": "授权留号"}
PHONE_TEXT = re.compile(r"(?<![A-Za-z0-9])\+?[0-9][() 0-9-]{5,23}[0-9](?![A-Za-z0-9])")
SELF_LABEL = re.compile(
    r"(?:^|[\s,;、/|(])(?:长辈本人|长者本人|老人本人|住户本人|本人)(?:的)?(?:联系)?(?:手机号码?|手机号?|电话(?:号码?)?)?[\s:]*$"
)


def _time(value, now, *, future=False):
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,6})?)?(?:Z|[+-][0-9]{2}:[0-9]{2})?",
        value,
    ):
        raise ValueError("请选择有效的日期和时间")
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("请选择有效的日期和时间") from None
    stamp = (stamp if stamp.tzinfo else stamp.replace(tzinfo=LOCAL)).astimezone(LOCAL)
    if not future and stamp > now:
        raise ValueError("实际来电或接待时间不能晚于当前时间")
    if future and stamp < now.replace(second=0, microsecond=0):
        raise ValueError("意向参观时间须为当前或将来的时段")
    return stamp.isoformat(timespec="seconds")


def _fields(payload, allowed):
    if not isinstance(payload, dict) or payload.keys() - allowed:
        raise ValueError("请核对意向登记的提交项目")


def _dt(now):
    return now.astimezone(LOCAL).isoformat(timespec="seconds")


def _phone_index(db, state):
    """Normalize institution-wide matches without disclosing which file matched."""
    known, admitted = set(), set()
    in_house = {p["id"] for p in state.get("residents", ()) if p["status"] == "在住"}
    for person in state.get("residents", ()):
        # Older admissions used a single, sometimes labelled telephone contact.
        legacy = unicodedata.normalize("NFKC", person.get("contact") or "")
        for match in PHONE_TEXT.finditer(legacy):
            phone = _phone(match[0])
            if SELF_LABEL.search(legacy[: match.start()]):
                if person["id"] in in_house:
                    admitted.add(phone)
            else:
                # A legacy reception number often belongs to the relative who called.
                known.add(phone)
    for rid, basic, household in db.execute(
        "SELECT resident_id,basic,household FROM dossier_profiles"
    ):
        if rid in in_house:
            admitted.add(_phone(json.loads(basic).get("phone")))
        known.update(
            _phone(p.get("phone"))
            for p in json.loads(household).get("familyMembers", ())
        )
    for (details,) in db.execute("SELECT details FROM dossier_relatives"):
        known.add(_phone(json.loads(details).get("phone")))
    for kind, role, rid, username, destination in db.execute(
        """SELECT a.kind,a.role,a.resident_id,a.username,c.destination FROM accounts a
           LEFT JOIN identity_contacts c ON c.account_id=a.id AND c.channel='sms'
                                       AND c.verified>=0"""
    ):
        phones = (_phone(username), _phone(destination))
        if kind == "family" and role == portal.CUSTOMER_ROLE:
            continue
        if kind == "family" and portal.is_self_role(role):
            if rid in in_house:
                admitted.update(phones)
        else:
            known.update(phones)
    known.discard("")
    admitted.discard("")
    return known, admitted


def _exempt_reason(lead, index):
    known, admitted = index
    phone = lead["phone"]
    if lead.get("admissionResolved") or phone in admitted:
        return "admitted"
    if not lead["explicitInterest"] and (
        lead.get("directoryResolved") or phone in known
    ):
        return "directory"
    return ""


def _campuses(db, user):
    if (
        not user
        or user["kind"] not in ("owner", "staff")
        or not access.has(user, "intake")
    ):
        return []
    scope = user.get("facilityScope") or {}
    if any(key in scope for key in ("buildingIds", "floorIds", "roomIds")):
        return []
    acl = facility._access(db, user, environment=True)
    return [
        {"id": cid, "name": name}
        for cid, name in db.execute(
            "SELECT id,name FROM facility_campuses ORDER BY name"
        )
        if acl.campuses is None or cid in acl.campuses
    ]


def require_campus(db, user, campus_id):
    if not any(c["id"] == campus_id for c in _campuses(db, user)):
        raise PermissionError("该账号没有此分院的意向接待权限")
    return campus_id


def require_lead(db, state, user, lead_id, *, open_only=False, callback=False):
    lead = next((r for r in state.get("leadContacts", ()) if r["id"] == lead_id), None)
    if not lead or lead["status"] == "归档到期":
        raise PermissionError("未找到有权办理的意向记录")
    require_campus(db, user, lead["campusId"])
    if open_only and lead["status"] == "已归档":
        raise ValueError("此来访已经归档，请另行登记新的来访")
    if callback and (
        lead["callbackStopped"] or _exempt_reason(lead, _phone_index(db, state))
    ):
        raise ValueError("该号码已停止回访，请记录客户主动来电或办理来访")
    return lead


def record_event(state, lead, user, now, kind, *, occurredAt=None, **fields):
    stamp = _dt(now)
    state.setdefault("leadEvents", [])
    append_record(
        state,
        "leadEvents",
        leadId=lead["id"],
        campusId=lead["campusId"],
        kind=kind,
        occurredAt=occurredAt or stamp,
        recordedAt=stamp,
        actorId=user["id"] if user else "",
        actorName=user["displayName"] if user else "宣传页",
        **fields,
    )
    lead["updatedAt"] = stamp


def _open(state, campus, phone):
    return next(
        (
            r
            for r in reversed(state.get("leadContacts", ()))
            if r["campusId"] == campus
            and r.get("phone") == phone
            and r["status"] not in ("已归档", "归档到期")
        ),
        None,
    )


def _new(state, campus, phone, name, note, source, now):
    state.setdefault("leadContacts", [])
    previous = next(
        (
            r
            for r in reversed(state["leadContacts"])
            if r["campusId"] == campus and lead_directory.matches_phone(r, phone)
        ),
        {},
    )
    return append_record(
        state,
        "leadContacts",
        campusId=campus,
        phone=phone,
        name=name,
        note=note,
        source=source,
        status="待回访",
        explicitInterest=source != "consent",
        callbackStopped=previous.get("callbackStopped", False),
        createdAt=_dt(now),
        updatedAt=_dt(now),
    )


def receive(db, state, payload, now):
    """Return whether a change occurred. The public handler always acknowledges alike."""
    _fields(
        payload,
        {"source", "campusId", "phone", "consent", "name", "nameParts", "note", "preferredAt"},
    )
    source = payload.get("source")
    if not isinstance(source, str) or source not in PUBLIC_EVENTS or payload.get("consent") is not True:
        raise ValueError("请先确认同意机构使用本次提交的号码联系您")
    campus = payload.get("campusId", facility.HOME_CAMPUS)
    if (
        not isinstance(campus, str)
        or not db.execute(
            "SELECT 1 FROM facility_campuses WHERE id=?", (campus,)
        ).fetchone()
    ):
        raise ValueError("请选择有效分院")
    phone = _phone(payload.get("phone"), mobile=source == "consent")
    if not phone:
        raise ValueError("请填写有效的联系电话，固定电话请含区号")
    if source != "visit" and any(
        payload.get(k) for k in ("name", "nameParts", "note", "preferredAt")
    ):
        raise ValueError("参观偏好请从申请参观入口登记")
    name = text_field(payload.get("name"), "称呼", required=source == "visit" and "nameParts" not in payload, limit=60)
    parts = None
    if "nameParts" in payload:
        from .international_profile import name_parts
        display, parts = name_parts(payload["nameParts"])
        if name and name != display:
            raise ValueError("Display name must match its name fields.")
        name = display
    note = text_field(payload.get("note"), "意向说明", limit=500)
    preferred = (
        _time(payload["preferredAt"], now, future=True)
        if payload.get("preferredAt")
        else ""
    )
    lead = _open(state, campus, phone)
    if source == "consent":
        known, admitted = _phone_index(db, state)
        # Opening the site or authorizing autofill again never restarts an archived enquiry.
        if (
            phone in known
            or phone in admitted
            or any(
                r["campusId"] == campus and lead_directory.matches_phone(r, phone)
                for r in state.get("leadContacts", ())
            )
        ):
            return False
    if lead is not None and source == "callback":
        last = next((e for e in reversed(state.get("leadEvents", ()))
                     if e["leadId"] == lead["id"] and e["kind"] in ("请求回电", "回访", "来电")), None)
        if last and last["kind"] == "请求回电":
            return False
    if lead is not None and source == "visit":
        previous = next(
            (
                e
                for e in reversed(state.get("leadEvents", ()))
                if e["leadId"] == lead["id"] and e["kind"] == "申请参观"
            ),
            None,
        )
        if previous and (parts is None or parts == lead.get("nameParts")) and (
            previous.get("name"),
            previous["feedback"],
            previous["preferredAt"],
        ) == (name, note, preferred):
            return False
    if lead is None:
        lead = _new(state, campus, phone, name, note, source, now)
    if source == "callback":
        lead["explicitInterest"] = True
        if phone in _phone_index(db, state)[1]:
            lead["admissionResolved"] = True
        elif not lead["callbackStopped"] and lead["status"] == "跟进中":
            lead["status"] = "待回访"
    if source == "visit":
        if parts:
            lead["nameParts"] = parts
        elif lead.get("name") != name:
            lead.pop("nameParts", None)
        lead.update(
            name=name,
            note=note,
            preferredAt=preferred,
            explicitInterest=True,
            callbackStopped=False,
            admissionResolved=phone in _phone_index(db, state)[1],
            status="待接待",
        )
    record_event(
        state,
        lead,
        None,
        now,
        PUBLIC_EVENTS[source],
        name=name,
        **({"nameParts": parts} if parts else {}),
        feedback=note,
        consent=True,
        preferredAt=preferred,
    )
    return True


def _register(db, state, user, payload, now):
    _fields(payload, {"campusId", "name", "phone", "channel", "note", "occurredAt"})
    campus = require_campus(db, user, payload.get("campusId"))
    phone = _phone(payload.get("phone"))
    if not phone:
        raise ValueError("请填写有效的联系电话，固定电话请含区号")
    channel = payload.get("channel", "incoming")
    if channel not in ("incoming", "walkin"):
        raise ValueError("请选择电话来询或现场到访")
    name = text_field(payload.get("name"), "称呼", limit=60)
    note = text_field(payload.get("note"), "接待说明", limit=1000)
    occurred = _time(payload.get("occurredAt"), now)
    lead = _open(state, campus, phone)
    if lead is None:
        lead = _new(state, campus, phone, name, note, "manual", now)
    elif name:
        lead["name"] = name
    lead["explicitInterest"] = True
    if phone in _phone_index(db, state)[1]:
        lead["admissionResolved"] = True
    if channel == "walkin":
        lead["status"] = "待接待"
    kind = "来电" if channel == "incoming" else "到访登记"
    record_event(state, lead, user, now, kind, feedback=note, occurredAt=occurred)
    return "登记客户" + kind


def _call(db, state, user, p, now):
    _fields(
        p,
        {"leadId", "direction", "outcome", "feedback", "occurredAt", "callbackStopped"},
    )
    direction = p.get("direction")
    outcome = p.get("outcome", "")
    stop = p.get("callbackStopped", False)
    if direction not in ("incoming", "outgoing") or type(stop) is not bool:
        raise ValueError("请核对来电、回访或停止联系选项")
    if outcome not in OUTCOMES and not (direction == "incoming" and outcome == ""):
        raise ValueError("请选择电话沟通结果")
    lead = require_lead(
        db,
        state,
        user,
        p.get("leadId"),
        open_only=True,
        callback=direction == "outgoing",
    )
    feedback = text_field(p.get("feedback"), "沟通反馈", required=True)
    occurred = _time(p.get("occurredAt"), now)
    if (
        stop
        or outcome == "暂无意向"
        or (
            direction == "outgoing"
            and _after_confirmation(state, lead, "callback", occurred)
        )
    ):
        _close(
            state,
            lead,
            "callback",
            "completed" if direction == "outgoing" else "cancelled",
            now,
            user,
        )
    if stop or outcome == "暂无意向":
        lead["callbackStopped"] = True
    if outcome == "有参观意向":
        lead["status"] = "待接待"
    elif lead["status"] != "待接待":
        lead["status"] = (
            "待回访"
            if outcome in ("未接通", "继续联系") and not lead["callbackStopped"]
            else "跟进中"
        )
    kind = "回访" if direction == "outgoing" else "来电"
    record_event(
        state,
        lead,
        user,
        now,
        kind,
        feedback=feedback,
        outcome=outcome,
        occurredAt=occurred,
        callbackStopped=lead["callbackStopped"],
    )
    return "记录客户" + kind + "反馈"


def _after_confirmation(state, lead, kind, occurred):
    # Logging a past contact must not complete a newer appointment.
    return any(
        row["leadId"] == lead["id"]
        and row["kind"] == kind
        and row["status"] == "confirmed"
        and row["confirmedAt"] <= occurred
        for row in state.get("visitBookings", ())
    )


def _close(state, lead, kind, status, now, user):
    return visit_schedule.close(
        state, lead["campusId"], lead["id"], kind, status, now, user["id"]
    )


def command(db, state, user, action, payload, now):
    if action == "leads.register":
        return _register(db, state, user, payload, now)
    if action == "leads.call":
        return _call(db, state, user, payload, now)
    lead = require_lead(db, state, user, payload.get("leadId"), open_only=True)
    if action == "leads.book":
        _fields(
            payload,
            {
                "leadId",
                "kind",
                "date",
                "start",
                "end",
                "seat",
                "phoneConfirmed",
                "feedback",
            },
        )
        if payload.get("phoneConfirmed") is not True:
            raise ValueError("请先与客户电话确认本次预约时间")
        kind = payload.get("kind")
        if kind == "callback":
            require_lead(db, state, user, lead["id"], callback=True)
        feedback = text_field(payload.get("feedback"), "电话确认备注")
        slot = visit_schedule.reserve(
            state,
            lead["campusId"],
            lead["id"],
            {
                k: payload[k]
                for k in ("kind", "date", "start", "end", "seat")
                if k in payload
            },
            now,
            user["id"],
        )
        if kind == "visit":
            lead["status"] = "待接待"
        record_event(
            state,
            lead,
            user,
            now,
            "电话确认预约",
            bookingId=slot["id"],
            bookingKind=kind,
            date=slot["date"],
            start=slot["start"],
            end=slot["end"],
            seat=slot["seat"],
            feedback=feedback,
        )
        return "电话确认客户预约时间"
    if action == "leads.cancel":
        _fields(payload, {"leadId", "kind", "feedback"})
        if payload.get("kind") not in ("visit", "callback"):
            raise ValueError("请选择要取消的预约")
        feedback = text_field(payload.get("feedback"), "取消原因", required=True)
        slots = _close(state, lead, payload["kind"], "cancelled", now, user)
        if not slots:
            raise ValueError("未找到相应的有效预约")
        record_event(
            state,
            lead,
            user,
            now,
            "取消预约",
            feedback=feedback,
            bookingId=slots[0]["id"],
        )
        return "记录客户取消预约"
    if action == "leads.feedback":
        _fields(payload, {"leadId", "feedback", "occurredAt"})
        feedback = text_field(payload.get("feedback"), "接待反馈", required=True)
        occurred = (
            _time(payload["occurredAt"], now) if payload.get("occurredAt") else _dt(now)
        )
        if _after_confirmation(state, lead, "visit", occurred):
            _close(state, lead, "visit", "completed", now, user)
        lead["status"] = "跟进中"
        record_event(
            state, lead, user, now, "接待反馈", occurredAt=occurred, feedback=feedback
        )
        return "记录客户来访接待反馈"
    if action == "leads.archive":
        _fields(payload, {"leadId", "feedback"})
        feedback = text_field(payload.get("feedback"), "归档反馈", required=True)
        _close(state, lead, None, "cancelled", now, user)
        directory = lead_directory.links(db, state, {lead["phone"]})
        lead.update(status="已归档", archivedAt=_dt(now), archiveFeedback=feedback,
                    directoryAtArchive=directory.get((lead["campusId"], lead["phone"]), []))
        record_event(state, lead, user, now, "归档", feedback=feedback)
        return "归档意向接待与反馈"
    raise ValueError("未登记的意向接待操作")


def reconcile_callbacks(db, state, now):
    """Release confirmed callbacks after a change to a resident or the contact directory."""
    active = [r for r in state.get("leadContacts", ()) if r["status"] not in ("已归档", "归档到期")]
    if not active:
        return
    scheduled = {
        r["leadId"]
        for r in state.get("visitBookings", ())
        if r["kind"] == "callback" and r["status"] == "confirmed"
    }
    index = _phone_index(db, state)
    system = {"id": "system", "displayName": "机构系统"}
    for lead in active:
        admitted = lead["phone"] in index[1] and not lead.get("admissionResolved")
        directory = (
            not lead["explicitInterest"]
            and lead["phone"] in index[0]
            and not lead.get("directoryResolved")
        )
        if admitted:
            lead["admissionResolved"] = True
        if directory:
            lead["directoryResolved"] = True
        suppress = lead["id"] in scheduled and (
            lead["callbackStopped"] or _exempt_reason(lead, index)
        )
        if suppress:
            _close(state, lead, "callback", "cancelled", now, system)
        if admitted or directory or suppress:
            record_event(
                state, lead, system, now, "停止回访", feedback="该号码免去后续回访"
            )


def project(db, state, user, data):
    campuses = _campuses(db, user)
    data["leadCampuses"] = campuses
    allowed = {r["id"] for r in campuses}
    visible = [r for r in state.get("leadContacts", ()) if r["campusId"] in allowed and r["status"] != "归档到期"]
    directory = lead_directory.links(db, state, {r["phone"] for r in visible}) if visible else {}
    index = _phone_index(db, state) if visible else (set(), set())
    data["leadContacts"] = []
    for row in visible:
        reason = _exempt_reason(row, index)
        data["leadContacts"].append(
            {**row, "directoryLinks": row.get("directoryAtArchive", directory.get((row["campusId"], row["phone"]), [])),
             "callbackExempt": bool(reason), "callbackExemptReason": reason}
        )
    for collection in ("leadEvents", "visitBookings", "visitSchedulePolicies"):
        data[collection] = [
            r for r in state.get(collection, ()) if r["campusId"] in allowed
        ]
