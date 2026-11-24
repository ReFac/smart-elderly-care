"""Single-use, resident-scoped registration edits approved by a named account."""

from contextlib import closing
from datetime import timedelta
import hashlib
import hmac
import json
import re
from uuid import uuid4

from . import access, activity, campus_access, dossier, secure_storage
from .access_policy import select_fields
from .care import archive_retention

CREATE = "permissionRequest.create"
REVIEW = "permissionRequest.review"
EDIT = "permissionRequest.editProfile"
APPROVE = "permissions.approve"
PROFILE_FIELDS = {
    *dossier.BASIC,
    "name",
    "age",
    "birthRegion",
    "nativeRegion",
    "addressRegion",
}
PENDING = timedelta(days=7)
APPROVED = timedelta(hours=24)


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS permission_requests(
        id TEXT PRIMARY KEY, resident_id TEXT NOT NULL,
        requester_id TEXT NOT NULL REFERENCES accounts(id), requester_name TEXT NOT NULL,
        requester_role TEXT NOT NULL,
        approver_id TEXT NOT NULL REFERENCES accounts(id), approver_name TEXT NOT NULL,
        approver_role TEXT NOT NULL, reason TEXT NOT NULL,
        requested_at TEXT NOT NULL, request_expires_at TEXT NOT NULL,
        decision TEXT CHECK(decision IN ('approve','reject')),
        decided_at TEXT, expires_at TEXT, signature TEXT, decision_note TEXT,
        signature_proof TEXT, used_at TEXT,
        CHECK(requester_id<>approver_id))""")
    db.execute(
        "CREATE INDEX IF NOT EXISTS permission_request_sent ON permission_requests(requester_id,requested_at DESC)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS permission_request_received ON permission_requests(approver_id,requested_at DESC)"
    )


def stamp(now):
    return now.isoformat(timespec="seconds")


def requester(user):
    return user["kind"] == "staff" and "residents" in access.resolve_routes(user)


def approver(user):
    return (
        user["kind"] in ("staff", "owner")
        and access.has(user, APPROVE)
        and access.has(user, "intake")
    )


def authorize(user, action):
    if (action in (CREATE, EDIT) and requester(user)) or (
        action == REVIEW and approver(user)
    ):
        return
    raise PermissionError("此账号没有办理该权限申请的资格")


def active_account(db, aid):
    user = access.account(db, aid)
    return user if user and user["enabled"] and not user["activationPending"] else None


def current_approver(store, db, aid):
    if not isinstance(aid, str) or not 1 <= len(aid) <= 100:
        raise ValueError("请选择审批人")
    user = active_account(db, aid)
    if not user or not approver(user):
        return None
    try:
        if store.facility_policy is not None:
            user["facilityScope"] = campus_access.effective(
                user, store.facility_policy(db, user)
            )
    except (PermissionError, ValueError):
        return None
    return user


def target(state, rid):
    return next((r for r in state["residents"] if r["id"] == rid), None)


def visible(db, state, user, rid):
    try:
        campus_access.require_resident(db, user, rid, state)
    except PermissionError:
        return False
    return True


def reviewable(db, state, user, rid):
    return approver(user) and visible(db, state, user, rid)


def state_of(row, now):
    if row["decision"] == "reject":
        return "rejected"
    if row["used_at"]:
        return "used"
    if row["decision"] == "approve":
        return "approved" if row["expires_at"] > stamp(now) else "expired"
    return "pending" if row["request_expires_at"] > stamp(now) else "expired"


def proof(store, row, signature, decided_at, expires_at, decision, note):
    key = secure_storage.derive(store._storage_master, b"resident-permission-signature")
    evidence = json.dumps(
        [
            row["id"],
            row["resident_id"],
            row["requester_id"],
            row["approver_id"],
            row["reason"],
            row["requested_at"],
            signature,
            decided_at,
            expires_at,
            decision,
            note,
            EDIT,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hmac.new(key, evidence.encode(), hashlib.sha256).hexdigest()


def can_edit(store, db, state, row, person, now):
    if state_of(row, now) != "approved" or not writable(person):
        return False
    signer = current_approver(store, db, row["approver_id"])
    if signer is None or not reviewable(db, state, signer, person["id"]):
        return False
    return row["signature"] == access.real_name(
        db, signer["id"]
    ) and hmac.compare_digest(
        row["signature_proof"],
        proof(
            store,
            row,
            row["signature"],
            row["decided_at"],
            row["expires_at"],
            row["decision"],
            row["decision_note"],
        ),
    )


def request_row(db, rid):
    row = (
        db.execute("SELECT * FROM permission_requests WHERE id=?", (rid,)).fetchone()
        if isinstance(rid, str) and len(rid) == 32
        else None
    )
    if not row:
        raise FileNotFoundError("未找到可办理的权限申请")
    return row


def writable(person):
    return person and person["status"] not in (
        archive_retention.ARCHIVED,
        archive_retention.EXPIRED,
    )


def pending_review(db, row, person):
    applicant = active_account(db, row["requester_id"])
    return bool(writable(person) and applicant and requester(applicant))


def pending_count(db, state, user, now):
    if not approver(user) or not access.real_name(db, user["id"]):
        return 0
    return sum(
        visible(db, state, user, row["resident_id"])
        and pending_review(db, row, target(state, row["resident_id"]))
        for row in db.execute(
            "SELECT resident_id,requester_id FROM permission_requests WHERE approver_id=? AND decision IS NULL AND request_expires_at>?",
            (user["id"], stamp(now)),
        )
    )


def read_one(store, db, state, user, row, now, *, received):
    rid = row["resident_id"]
    person = target(state, rid)
    status = state_of(row, now)
    allowed = person and visible(db, state, user, rid)
    if received and (not allowed or not approver(user)):
        return None
    edit = not received and can_edit(store, db, state, row, person, now)
    if status == "approved" and not received and not edit:
        status = "expired"
    shown = (
        person
        if (allowed or edit) and person["status"] != archive_retention.EXPIRED
        else {}
    )
    return {
        "id": row["id"],
        "residentId": rid,
        "residentName": shown.get("name", ""),
        "room": activity.for_person(state, rid).get("room", "") if shown else "",
        "requesterId": row["requester_id"],
        "requesterName": row["requester_name"],
        "requesterRole": row["requester_role"],
        "approverId": row["approver_id"],
        "approverName": row["approver_name"],
        "approverRole": row["approver_role"],
        "reason": row["reason"],
        "status": status,
        "requestedAt": row["requested_at"],
        "decidedAt": row["decided_at"],
        "signature": row["signature"],
        "decisionNote": row["decision_note"],
        "expiresAt": row["expires_at"],
        "usedAt": row["used_at"],
        "canReview": bool(
            received
            and status == "pending"
            and pending_review(db, row, person)
            and access.real_name(db, user["id"])
        ),
        "canEdit": edit,
    }


def directory(store, db, user):
    if not requester(user):
        return []
    return [
        {"id": other["id"], "name": other["displayName"], "role": other["role"]}
        for (aid,) in db.execute(
            """SELECT id FROM accounts
            WHERE id<>? AND kind IN ('staff','owner') AND enabled=1 AND activation_pending=0
            ORDER BY kind,display_name,id""",
            (user["id"],),
        )
        if (other := current_approver(store, db, aid)) and access.real_name(db, aid)
    ]


def basic_profile(db, person):
    row = db.execute(
        "SELECT basic FROM dossier_profiles WHERE resident_id=?", (person["id"],)
    ).fetchone()
    return select_fields(json.loads(row[0]), PROFILE_FIELDS) if row else {}


def read(store, token, profile_id=None):
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        user = store.actor(db, token)
        if user["kind"] not in ("staff", "owner"):
            raise PermissionError("仅在岗人员可以使用权限申请")
        workspace = db.execute(
            "SELECT revision,data FROM workspace WHERE id=1"
        ).fetchone()
        state = json.loads(workspace["data"])
        now = store.now()
        if profile_id:
            row = request_row(db, profile_id)
            person = authorized_edit(store, db, state, user, row, now)
            return {
                "revision": workspace["revision"],
                "resident": select_fields(person, ("id", "name", "age")),
                "basic": basic_profile(db, person),
            }
        result = {
            "revision": workspace["revision"],
            "sent": [],
            "received": [],
            "approvers": directory(store, db, user),
            "canReview": bool(approver(user) and access.real_name(db, user["id"])),
        }
        for side, key, allowed in (
            ("sent", "requester_id", requester(user)),
            ("received", "approver_id", approver(user)),
        ):
            if not allowed:
                continue
            for row in db.execute(
                f"""SELECT * FROM permission_requests WHERE {key}=?
                                   ORDER BY requested_at DESC,id DESC LIMIT 100""",
                (user["id"],),
            ):
                item = read_one(
                    store, db, state, user, row, now, received=side == "received"
                )
                if item:
                    result[side].append(item)
        return result


def create(store, db, state, user, payload, now):
    if set(payload) != {"residentId", "approverId", "reason"}:
        raise ValueError("请填写长者档案编号、审批人及申请原因")
    rid = payload["residentId"]
    if not isinstance(rid, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", rid):
        raise ValueError("请填写正确的长者档案编号")
    reason = dossier.text(payload, "reason", 500, True)
    aid = payload["approverId"]
    if aid == user["id"]:
        raise PermissionError("权限申请须由其他合资格人员审批")
    reviewer = current_approver(store, db, aid)
    person = target(state, rid)
    if (
        not reviewer
        or not access.real_name(db, aid)
        or not writable(person)
        or not reviewable(db, state, reviewer, rid)
    ):
        raise ValueError("未能递交申请，请核对档案编号并选择对该档案有权限的审批人")
    if access.has(user, "intake") and visible(db, state, user, rid):
        raise ValueError("当前账号可以编辑该档案，无须申请")
    active = db.execute(
        """SELECT * FROM permission_requests WHERE requester_id=? AND used_at IS NULL
        AND ((decision IS NULL AND request_expires_at>?) OR (decision='approve' AND expires_at>?))""",
        (user["id"], stamp(now), stamp(now)),
    ).fetchall()
    if any(
        r["resident_id"] == rid
        and (r["decision"] is None or can_edit(store, db, state, r, person, now))
        for r in active
    ):
        raise ValueError("该档案已有待审批或可使用的申请")
    if len(active) >= 20:
        raise ValueError("达到了有效权限申请上限，请先处理现有申请")
    db.execute(
        """INSERT INTO permission_requests(id,resident_id,requester_id,requester_name,requester_role,
               approver_id,approver_name,approver_role,reason,requested_at,request_expires_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            uuid4().hex,
            rid,
            user["id"],
            user["displayName"],
            user["role"],
            aid,
            reviewer["displayName"],
            reviewer["role"],
            reason,
            stamp(now),
            stamp(now + PENDING),
        ),
    )
    return "已提交长者档案编辑权限申请", rid


def review(store, db, state, user, payload, now):
    if set(payload) - {"requestId", "decision", "signature", "currentPassword", "note"}:
        raise ValueError("权限审批表单格式有误")
    row = request_row(db, payload.get("requestId"))
    rid = row["resident_id"]
    if row["approver_id"] != user["id"] or not reviewable(db, state, user, rid):
        raise FileNotFoundError("未找到可办理的权限申请")
    if state_of(row, now) != "pending" or not pending_review(
        db, row, target(state, rid)
    ):
        raise ValueError("申请已处理、已过期或申请人及档案状态已改变")
    decision = payload.get("decision")
    if decision not in ("approve", "reject"):
        raise ValueError("请选择批准或驳回")
    registered = access.real_name(db, user["id"])
    signed = access.signature_text(payload.get("signature"))
    if not registered or signed != registered:
        raise ValueError("请使用当前账号已登记的实名签署")
    note = dossier.text(payload, "note", 500)
    access.verify_current_password(db, user, payload.get("currentPassword"))
    decided_at = stamp(now)
    expires_at = stamp(now + APPROVED) if decision == "approve" else None
    evidence = proof(store, row, signed, decided_at, expires_at, decision, note)
    db.execute(
        """UPDATE permission_requests SET decision=?,decided_at=?,expires_at=?,signature=?,
               decision_note=?,signature_proof=? WHERE id=?""",
        (decision, decided_at, expires_at, signed, note, evidence, row["id"]),
    )
    return (
        "已实名签署批准长者档案编辑权限"
        if decision == "approve"
        else "已实名签署驳回长者档案编辑权限"
    ), rid


def authorized_edit(store, db, state, user, row, now):
    if not requester(user) or row["requester_id"] != user["id"]:
        raise FileNotFoundError("未找到可办理的权限申请")
    person = target(state, row["resident_id"])
    if not can_edit(store, db, state, row, person, now):
        raise PermissionError("这次档案编辑授权尚未生效、已使用或已失效")
    return person


def edit(store, db, state, user, payload, now):
    if set(payload) - {"requestId", *PROFILE_FIELDS}:
        raise ValueError("此项授权仅可编辑长者登记资料")
    row = request_row(db, payload.get("requestId"))
    person = authorized_edit(store, db, state, user, row, now)
    details = {key: value for key, value in payload.items() if key in PROFILE_FIELDS}

    def values():
        basic = {
            k: v
            for k, v in basic_profile(db, person).items()
            if v and v != {"codes": [], "detail": ""}
        }
        return person["name"], person.get("age"), basic

    before = values()
    dossier.edit_profile(
        db,
        state,
        {**details, "residentId": person["id"]},
        user,
        now.date().isoformat(),
        temporary=True,
    )
    if values() == before:
        raise ValueError("登记内容没有变化，临时授权仍可使用")
    db.execute(
        "UPDATE permission_requests SET used_at=? WHERE id=?", (stamp(now), row["id"])
    )
    return "已使用一次性授权更新长者登记资料", person["id"]
