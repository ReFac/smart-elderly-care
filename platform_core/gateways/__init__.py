"""Local event review and authorized voice proposals. Each command runs inside Store's write transaction."""

import json
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from .. import access_policy as access
from .. import campus_access
from ..care import apply as care_action
from ..care.records import append_record, lookup, text_field
from ..care.residency import active_card
from .catalog import SOURCES, catalog

__all__ = ["apply", "audit_context", "catalog", "init", "project"]

SIGNALS = {"possible_fall": "疑似跌倒", "prolonged_bedrest": "持续卧床提示"}
SHANGHAI = ZoneInfo("Asia/Shanghai")


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS gateway_alert (
        id TEXT PRIMARY KEY, source TEXT NOT NULL, event_id TEXT NOT NULL, bed_id TEXT NOT NULL,
        room TEXT NOT NULL, signal TEXT NOT NULL, observed_at TEXT NOT NULL, fingerprint TEXT NOT NULL,
        resident_hint TEXT NOT NULL, candidates TEXT NOT NULL, evidence_ref TEXT NOT NULL, observation TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT '待复核', reviewed_by TEXT, reviewed_at TEXT, resident_id TEXT,
        review_note TEXT, episode TEXT NOT NULL DEFAULT '', allocation TEXT NOT NULL DEFAULT '', UNIQUE(source,event_id))""")
    columns = {r[1] for r in db.execute("PRAGMA table_info(gateway_alert)")}
    if "episode" not in columns:
        db.execute(
            "ALTER TABLE gateway_alert ADD COLUMN episode TEXT NOT NULL DEFAULT ''"
        )
        db.execute("UPDATE gateway_alert SET episode=id")
    if "allocation" not in columns:
        db.execute(
            "ALTER TABLE gateway_alert ADD COLUMN allocation TEXT NOT NULL DEFAULT ''"
        )
    db.execute("CREATE INDEX IF NOT EXISTS alert_episode ON gateway_alert(episode)")
    db.execute(
        "CREATE INDEX IF NOT EXISTS alert_location ON gateway_alert(bed_id,status,signal,observed_at)"
    )
    db.execute("""CREATE TABLE IF NOT EXISTS gateway_voice (
        id TEXT PRIMARY KEY, requester_id TEXT NOT NULL, request_id TEXT NOT NULL, requester_name TEXT NOT NULL,
        task_id TEXT NOT NULL, task_title TEXT NOT NULL, transcript TEXT NOT NULL, note TEXT NOT NULL,
        resident_id TEXT NOT NULL, bed_id TEXT NOT NULL, allocation TEXT NOT NULL, room TEXT NOT NULL,
        created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT '待确认', reviewer_id TEXT,
        reviewed_at TEXT, reason TEXT, UNIQUE(requester_id,request_id))""")
    if "media_call" not in {
        r[1] for r in db.execute("PRAGMA table_info(gateway_voice)")
    }:
        db.execute(
            "ALTER TABLE gateway_voice ADD COLUMN media_call TEXT NOT NULL DEFAULT ''"
        )
    db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS gateway_pending_task
                  ON gateway_voice(task_id) WHERE status = '待确认'""")


def required(payload, key, label, size=240):
    return text_field(payload.get(key), label, required=True, limit=size)


def room_label(bed):
    return bed["ward"] + " / " + bed["label"].rsplit("-", 1)[0]


def timestamp(value=None):
    if value is None:
        return datetime.now(SHANGHAI).isoformat(timespec="seconds")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.utcoffset() is None:
            raise ValueError
        return dt.astimezone(SHANGHAI).isoformat(timespec="seconds")
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise ValueError("事件时间须含日期、时刻和时区。") from None


def alert_by_key(db, payload):
    return db.execute(
        "SELECT * FROM gateway_alert WHERE source=? AND event_id=?",
        (payload["source"].strip(), payload["eventId"].strip()),
    ).fetchone()


def ingest(db, state, payload, user, today):
    source = required(payload, "source", "设备来源")
    signal = required(payload, "signal", "信号类型")
    event = required(payload, "eventId", "源事件编号", 160)
    if source not in SOURCES or signal not in SIGNALS:
        raise ValueError("请选择支持的来源和观测信号。")
    bed_id = required(payload, "bedId", "定位床位")
    hint = text_field(payload.get("residentId"), "设备提示的长者", limit=160)
    evidence = text_field(payload.get("evidenceRef"), "证据编号", limit=240)
    observation = text_field(payload.get("observation"), "设备观测摘要", limit=800)
    observed = timestamp(payload["observedAt"]) if payload.get("observedAt") else None
    fingerprint = json.dumps(
        [signal, bed_id, hint, evidence, observation, observed], ensure_ascii=False
    )
    prior = alert_by_key(db, payload)
    if prior:
        if prior["fingerprint"] != fingerprint:
            raise ValueError("此来源的事件编号已对应另一份观测，请核对原报文。")
        return f"收到重传事件 {event}，沿用原预警"
    bed = lookup(state, "beds", bed_id)
    room = room_label(bed)
    mapped = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='facility_beds'"
    ).fetchone()
    if mapped:
        # A room may have the same label in different buildings or branches.
        room_beds = {
            r[0]
            for r in db.execute(
                "SELECT bedId FROM facility_beds WHERE roomId=(SELECT roomId FROM facility_beds WHERE bedId=?)",
                (bed_id,),
            )
        }
        room_beds.add(bed_id)
    else:
        room_beds = {b["id"] for b in state["beds"] if room_label(b) == room}
    ids = [
        b["residentId"]
        for b in state["beds"]
        if b["id"] in room_beds and b["residentId"]
    ]
    if hint and hint not in ids:
        raise ValueError("提示的长者不在此房间的在住名单中。")
    observed = observed or timestamp()
    event_time = datetime.fromisoformat(observed)
    resident_map = {r["id"]: r for r in state["residents"]}
    allocation = json.dumps(
        sorted((rid, active_card(state, resident_map[rid])) for rid in ids)
    )
    alert_id = uuid4().hex
    # Anchor the window to the first observation; a rolling chain could mask a later incident.
    anchor = (
        db.execute(
            """SELECT a.id FROM gateway_alert a WHERE a.id=a.episode AND a.status='待复核'
           AND a.bed_id=? AND a.signal=? AND a.resident_hint=? AND a.allocation=?
           AND a.observed_at BETWEEN ? AND ?
           AND NOT EXISTS(SELECT 1 FROM gateway_alert b WHERE b.episode=a.id AND b.source=?)
           ORDER BY abs(julianday(a.observed_at)-julianday(?)),a.rowid DESC LIMIT 1""",
            (
                bed_id,
                signal,
                hint,
                allocation,
                (event_time - timedelta(seconds=90)).isoformat(),
                (event_time + timedelta(seconds=90)).isoformat(),
                source,
                observed,
            ),
        ).fetchone()
        if ids
        else None
    )
    episode = anchor[0] if anchor else alert_id
    db.execute(
        """INSERT INTO gateway_alert
        (id,source,event_id,bed_id,room,signal,observed_at,fingerprint,resident_hint,candidates,evidence_ref,observation,episode,allocation)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            alert_id,
            source,
            event,
            bed_id,
            room,
            signal,
            observed,
            fingerprint,
            hint,
            json.dumps(ids),
            evidence,
            observation,
            episode,
            allocation,
        ),
    )
    return f"{room} 收到{SIGNALS[signal]}，等待护士核实"


def record(db, table, key):
    # Table names come exclusively from the command registry below.
    row = db.execute(f"SELECT * FROM {table} WHERE id=?", (key,)).fetchone()
    if not row:
        raise ValueError("所选记录不存在，请刷新工作台。")
    return row


def review(db, state, payload, user, today):
    row = record(db, "gateway_alert", required(payload, "alertId", "预警编号"))
    if row["status"] != "待复核":
        raise ValueError("此预警已经复核。")
    decision = required(payload, "decision", "核实结果")
    if decision not in ("已核实", "误报", "无法核实"):
        raise ValueError("请选择有效核实结果。")
    note = required(payload, "note", "现场核实与处置记录", 1000)
    resident_id = ""
    if decision == "已核实":
        resident_id = required(payload, "residentId", "现场核实的长者")
        if resident_id not in json.loads(row["candidates"]):
            raise ValueError("请选择该房间事件记录内经现场核实的长者。")
        resident = lookup(state, "residents", resident_id)
        # A later transfer or discharge must not reassign an earlier incident to a new occupant.
        summary = f"{SIGNALS[row['signal']]} · {row['room']} · {note}"
        append_record(
            state,
            "archives",
            residentId=resident_id,
            date=today,
            reviewer=user["displayName"],
            reviewerId=user["id"],
            summary=summary,
            source="设备预警人工复核",
            alertId=row["episode"],
            room=row["room"],
            observedAt=row["observed_at"],
        )
        message = f"核实{resident['name']}的设备预警，已追加档案事件"
    else:
        message = f"将{row['room']}的设备预警标记为{decision}"
    db.execute(
        """UPDATE gateway_alert SET status=?,reviewed_by=?,reviewed_at=?,resident_id=?,review_note=?
                  WHERE episode=? AND status='待复核'""",
        (decision, user["id"], timestamp(), resident_id, note, row["episode"]),
    )
    return message


def propose(db, state, payload, user, today):
    access.require(user, "care")
    if payload.get("targetAction", "care.completeTask") != "care.completeTask":
        raise ValueError("当前语音确认模板仅支持登记一项工单完成。")
    request_id = required(payload, "requestId", "申请幂等编号", 160)
    transcript = required(
        payload,
        "transcript",
        "转写内容",
        16000 if payload.get("transcriptId") else 1000,
    )
    note = required(payload, "note", "拟写入的执行记录", 1000)
    task_id = required(payload, "taskId", "目标工单")
    task = lookup(state, "tasks", task_id)
    campus_access.require_resident(db, user, task["residentId"], state)
    media_call = text_field(payload.get("transcriptId"), "语音识别凭据", limit=100)
    if media_call:
        recognized = db.execute(
            """SELECT result FROM media_usage WHERE id=? AND actor=? AND reference=?
                               AND kind='asr' AND state='complete'""",
            (media_call, user["id"], task_id),
        ).fetchone()
        if not recognized or transcript != json.loads(recognized[0])["text"]:
            raise ValueError("请重新核对当前工单的语音识别凭据")
    previous = db.execute(
        "SELECT * FROM gateway_voice WHERE requester_id=? AND request_id=?",
        (user["id"], request_id),
    ).fetchone()
    if previous:
        if (
            previous["task_id"],
            previous["note"],
            previous["transcript"],
            previous["media_call"],
        ) != (
            task_id,
            note,
            transcript,
            media_call,
        ):
            raise ValueError("此申请编号已对应不同改动。")
        return "收到重复提交，沿用原语音申请"
    resident = lookup(state, "residents", task["residentId"])
    if (
        task["status"] != "待执行"
        or task["date"] > today
        or resident["status"] != "在住"
    ):
        raise ValueError("请选择当日或逾期的在住长者待执行工单。")
    bed = lookup(state, "beds", resident["bedId"])
    allocation = active_card(state, resident)
    if not allocation or bed["residentId"] != resident["id"]:
        raise ValueError("当前床位与长者档案不一致。")
    if db.execute(
        "SELECT 1 FROM gateway_voice WHERE task_id=? AND status='待确认'", (task_id,)
    ).fetchone():
        raise ValueError("此工单已有待确认申请。")
    db.execute(
        """INSERT INTO gateway_voice
        (id,requester_id,request_id,requester_name,task_id,task_title,transcript,note,
         resident_id,bed_id,allocation,room,created_at,media_call) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            uuid4().hex,
            user["id"],
            request_id,
            user["displayName"],
            task_id,
            task["title"],
            transcript,
            note,
            resident["id"],
            bed["id"],
            allocation,
            room_label(bed),
            timestamp(),
            media_call,
        ),
    )
    return f"已提交「{task['title']}」的完成申请，等待授权人员确认"


def pending_voice(db, user, proposal_id, state=None):
    access.require(user, "care")
    access.require(user, "voice.confirm")
    row = record(db, "gateway_voice", proposal_id)
    beds = campus_access.allowed_beds(db, user, include_rooms=True)
    if beds is not None:
        if state is None:
            state = json.loads(
                db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
            )
        if row["bed_id"] not in beds or row[
            "resident_id"
        ] not in campus_access.resident_ids(state, beds):
            raise PermissionError("该语音申请不在本人授权范围内")
    if row["status"] != "待确认":
        raise ValueError("该申请已由其他人员处理，请刷新待办。")
    return row


def resolve_voice(db, state, payload, user, today, confirm):
    row = pending_voice(db, user, required(payload, "proposalId", "申请编号"), state)
    note = "" if confirm else required(payload, "reason", "退回原因", 500)
    if confirm:
        task = lookup(state, "tasks", row["task_id"])
        resident = lookup(state, "residents", row["resident_id"])
        if (
            resident["status"] != "在住"
            or resident["bedId"] != row["bed_id"]
            or task["residentId"] != resident["id"]
            or active_card(state, resident) != row["allocation"]
        ):
            raise ValueError(
                "从申请发起后，入住、床位或服务对象已变更。请退回并重新核对。"
            )
        values = {
            "taskId": task["id"],
            "note": row["note"],
            "operator": user["displayName"],
        }
        access.authorize(user, "care.completeTask", values, state)
        result = care_action(state, "care.completeTask", values, today)
        status = "已确认"
        # No checked bed receipt is written: an approved voice note is not a bedside scan.
        task["voiceProposalId"] = row["id"]
        task["operatorId"] = user["id"]
    else:
        status = "已退回"
        result = f"退回「{row['task_title']}」的变更申请"
    db.execute(
        """UPDATE gateway_voice SET status=?, reviewer_id=?,reviewed_at=?,reason=?
                  WHERE id=? AND status='待确认'""",
        (status, user["id"], timestamp(), note, row["id"]),
    )
    return result


def apply(db, state, action, payload, user, today):
    access.authorize(user, action, payload, state)
    if action == "gw.ingest":
        return ingest(db, state, payload, user, today)
    if action == "gw.review":
        return review(db, state, payload, user, today)
    if action == "gw.propose":
        return propose(db, state, payload, user, today)
    if action in ("gw.confirm", "gw.dismiss"):
        return resolve_voice(db, state, payload, user, today, action == "gw.confirm")
    raise ValueError("未知接入动作。")


def project(db, data, user, bed_ids=None, resident_ids=None):
    data["gatewayAlerts"], data["voiceQueue"], data["integrationCatalog"] = [], [], []
    if any(
        access.has(user, grant)
        for grant in ("gateway.simulate", "alerts", "voice", "voice.confirm")
    ):
        data["integrationCatalog"] = [
            p for p in catalog() if not p["ownerOnly"] or user["kind"] == "owner"
        ]
    if access.has(user, "alerts"):
        episodes = {}
        for row in db.execute("SELECT * FROM gateway_alert ORDER BY rowid DESC"):
            if bed_ids is not None and row["bed_id"] not in bed_ids:
                continue
            if resident_ids is not None and any(
                rid and rid not in resident_ids
                for rid in (row["resident_hint"], row["resident_id"])
            ):
                continue
            episodes.setdefault(row["episode"], []).append(
                {
                    "source": row["source"],
                    "eventId": row["event_id"],
                    "observedAt": row["observed_at"],
                    "evidenceRef": row["evidence_ref"],
                    "observation": row["observation"],
                }
            )
            if row["id"] != row["episode"]:
                continue
            observations = episodes[row["episode"]]
            data["gatewayAlerts"].append(
                {
                    "id": row["id"],
                    "source": row["source"],
                    "priority": "优先现场核实"
                    if row["signal"] == "possible_fall"
                    else "现场观察",
                    "observations": observations,
                    "eventId": row["event_id"],
                    "room": row["room"],
                    "signal": row["signal"],
                    "observedAt": row["observed_at"],
                    "residentHint": row["resident_hint"],
                    "candidates": [
                        rid
                        for rid in json.loads(row["candidates"])
                        if resident_ids is None or rid in resident_ids
                    ],
                    "evidenceRef": row["evidence_ref"],
                    "observation": row["observation"],
                    "status": row["status"],
                    "residentId": row["resident_id"],
                    "reviewedBy": row["reviewed_by"],
                    "reviewedAt": row["reviewed_at"],
                    "reviewNote": row["review_note"],
                }
            )
        data["gatewayAlerts"].sort(
            key=lambda r: (
                r["status"] == "待复核",
                r["status"] == "待复核" and r["signal"] == "possible_fall",
                r["observedAt"],
            ),
            reverse=True,
        )
    if access.has(user, "voice.confirm") and access.has(user, "care"):
        for row in db.execute(
            """SELECT id,task_id,task_title,resident_id,room,created_at,requester_name,bed_id
               FROM gateway_voice WHERE status='待确认' ORDER BY rowid DESC"""
        ):
            if bed_ids is not None and row["bed_id"] not in bed_ids:
                continue
            if resident_ids is not None and row["resident_id"] not in resident_ids:
                continue
            data["voiceQueue"].append(
                {
                    "id": row["id"],
                    "taskId": row["task_id"],
                    "title": row["task_title"],
                    "residentId": row["resident_id"],
                    "room": row["room"],
                    "createdAt": row["created_at"],
                    "requester": row["requester_name"],
                }
            )
    return data


def audit_context(db, state, action, payload, user=None):
    if action == "gw.ingest":
        row = alert_by_key(db, payload)
    elif action == "gw.review":
        row = record(db, "gateway_alert", payload["alertId"].strip())
    elif action == "gw.propose":
        query = "SELECT * FROM gateway_voice WHERE request_id=? AND task_id=?"
        keys = [payload["requestId"].strip(), payload["taskId"].strip()]
        if user:
            query += " AND requester_id=?"
            keys.append(user["id"])
        row = db.execute(query + " ORDER BY rowid DESC LIMIT 1", keys).fetchone()
    elif action in ("gw.dismiss", "gw.confirm"):
        row = record(db, "gateway_voice", payload["proposalId"].strip())
    else:
        return {}
    if not row:
        return {}
    return {"residentId": row["resident_id"] or "", "room": row["room"]}
