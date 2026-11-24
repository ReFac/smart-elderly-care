"""Reviewed health introductions, staff additions, and individual health conversations."""

from contextlib import closing
import json
import re
from uuid import uuid4

from . import access, campus_access, dossier, portal
from .care import archive_retention
from .care.records import lookup
from .provider import generation
from . import resident_health_evidence as evidence


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS resident_health_notes(
        id TEXT PRIMARY KEY,resident_id TEXT NOT NULL,kind TEXT NOT NULL,
        event_day TEXT NOT NULL,content TEXT NOT NULL,refs TEXT NOT NULL,actor TEXT NOT NULL,
        actor_name TEXT NOT NULL,actor_role TEXT NOT NULL,recorded_at TEXT NOT NULL,
        request TEXT NOT NULL,UNIQUE(actor,request))""")
    db.execute(
        "CREATE INDEX IF NOT EXISTS health_notes_resident ON resident_health_notes(resident_id,kind)"
    )
    db.execute("""CREATE TABLE IF NOT EXISTS resident_health_drafts(
        id TEXT PRIMARY KEY,resident_id TEXT NOT NULL,actor TEXT NOT NULL,basis TEXT NOT NULL,
        points TEXT NOT NULL,UNIQUE(resident_id,actor,basis))""")
    for op in ("UPDATE", "DELETE"):
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS resident_health_notes_no_{op}
            BEFORE {op} ON resident_health_notes BEGIN SELECT RAISE(ABORT,'请追加健康记录以保留原文'); END""")


def _context(db, state, user, rid, writing=False):
    if user["kind"] not in ("staff", "owner") or not any(
        access.has(user, k) for k in ("medical", "care", "clinical")
    ):
        raise PermissionError("仅有照护或医疗权限的工作人员可查看健康简介")
    campus_access.require_resident(db, user, rid, state)
    person = lookup(state, "residents", rid)
    if person["status"] == archive_retention.EXPIRED:
        raise FileNotFoundError("档案已到保管期")
    if writing:
        archive_retention.writable(state, rid)
    return person


def _load(db, user, rid, *, ai=False):
    # The read path never loads other residents' charts into the assistant process.
    chart = db.execute(
        """SELECT r.value FROM workspace,json_each(data,'$.residents') r
        WHERE workspace.id=1 AND json_extract(r.value,'$.id')=?""",
        (rid,),
    ).fetchone()
    last_bed = db.execute(
        """SELECT b.value FROM workspace,json_each(data,'$.bedMoves') b
        WHERE workspace.id=1 AND json_extract(b.value,'$.residentId')=?
        ORDER BY b.key DESC LIMIT 1""",
        (rid,),
    ).fetchone()
    state = {
        "residents": [json.loads(chart[0])] if chart else [],
        "bedMoves": [json.loads(last_bed[0])] if last_bed else [],
    }
    person = _context(db, state, user, rid, writing=ai)
    if ai:
        access.require(user, "medical")
        access.require(user, "clinical")
    return person


def read(store, token, rid):
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        user = store.actor(db, token)
        if user["kind"] == "family":
            portal.require_personal_health(user, rid)
            status = db.execute(
                """SELECT json_extract(r.value,'$.status')
                FROM workspace,json_each(data,'$.residents') r WHERE workspace.id=1
                AND json_extract(r.value,'$.id')=?""",
                (rid,),
            ).fetchone()
            if not status or status[0] == archive_retention.EXPIRED:
                raise FileNotFoundError("找不到可查看的个人健康简介")
            result = {
                "intro": None,
                "additions": [],
                "conversations": [],
                "canWrite": False,
                "canGenerate": False,
            }
            for kind, text, day in db.execute(
                """SELECT kind,content,event_day FROM resident_health_notes
                WHERE resident_id=? AND kind IN ('ai','intro','addition') ORDER BY rowid DESC""",
                (rid,),
            ):
                entry = {"kind": kind, "text": text, "day": day}
                if kind == "addition":
                    result["additions"].append(entry)
                elif result["intro"] is None:
                    result["intro"] = entry
            return result
        person = _load(db, user, rid)
        can_review = all(access.has(user, p) for p in ("medical", "clinical"))
        editable = person["status"] != archive_retention.ARCHIVED
        result = {
            "revision": db.execute(
                "SELECT revision FROM workspace WHERE id=1"
            ).fetchone()[0],
            "intro": None,
            "additions": [],
            "conversations": [],
            "canWrite": editable and access.has(user, "care"),
            "canGenerate": editable and can_review,
        }
        for row in db.execute(
            "SELECT * FROM resident_health_notes WHERE resident_id=? ORDER BY rowid DESC",
            (rid,),
        ):
            kind = row["kind"]
            if kind in ("ai", "intro") and result["intro"]:
                continue
            entry = {
                "id": row["id"],
                "kind": kind,
                "text": row["content"],
                "day": row["event_day"],
                "at": row["recorded_at"],
                "staff": row["actor_name"],
                "staffId": row["actor"],
                "role": row["actor_role"],
            }
            if kind in ("ai", "intro"):
                entry["sources"] = json.loads(row["refs"]) if can_review else []
                result["intro"] = entry
            else:
                result[
                    "conversations" if kind == "conversation" else "additions"
                ].append(entry)
        return result


def _basis(rid, sources):
    return generation.fingerprint([rid, evidence.CALLOUT, sources])


def draft(store, token, rid, payload):
    if payload != {"consent": True} or payload.get("consent") is not True:
        raise ValueError("请确认发送这位长者的健康资料摘录至 DeepSeek")

    def scope(db):
        user = store.actor(db, token)
        person = _load(db, user, rid, ai=True)
        sources = evidence.collect(db, person)
        basis = _basis(rid, sources)
        return user, sources, basis

    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        user, sources, basis = scope(db)
        cached = db.execute(
            """SELECT id,points FROM resident_health_drafts
            WHERE resident_id=? AND actor=? AND basis=?""",
            (rid, user["id"], basis),
        ).fetchone()
        if cached:
            return {"draftId": cached[0], "points": json.loads(cached[1])}
    if not sources:
        return {"draftId": None, "points": []}
    raw = generation.generate(
        store,
        user["id"],
        "health-introduction/" + basis,
        evidence.CALLOUT,
        {"摘录": [[i, s["label"], s["value"]] for i, s in enumerate(sources, 1)]},
        lambda obj: evidence.validate(obj, sources),
        output_tokens=850,
        shared_once=True,
    )
    points = []
    for row in raw["points"]:
        source = sources[row["source"] - 1]
        points.append(
            {
                "text": row["text"].strip(),
                "quote": row["quote"],
                "label": source["label"],
                "recordId": source["id"],
            }
        )
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        after, _, latest = scope(db)
        if after["id"] != user["id"] or latest != basis:
            raise ValueError("个人健康资料或经办人已变更，请重新整理")
        db.execute(
            """INSERT OR IGNORE INTO resident_health_drafts VALUES(?,?,?,?,?)""",
            (uuid4().hex, rid, user["id"], basis, dossier.pack(points)),
        )
        row = db.execute(
            """SELECT id,points FROM resident_health_drafts
            WHERE resident_id=? AND actor=? AND basis=?""",
            (rid, user["id"], basis),
        ).fetchone()
        return {"draftId": row[0], "points": json.loads(row[1])}


def command(db, state, user, action, p, now):
    if p.get("confirmed") is not True:
        raise ValueError("请核对这位长者的健康记录并确认保存")
    rid = p.get("residentId")
    person = _context(db, state, user, rid, writing=True)
    today = now.date().isoformat()
    if action == "care.healthNote":
        access.require(user, "care")
        if set(p) != {"residentId", "kind", "text", "day", "requestId", "confirmed"}:
            raise ValueError("健康记录字段有误")
        kind = p["kind"]
        if kind not in ("intro", "addition", "conversation"):
            raise ValueError("请选择健康简介、人工补充或本人健康谈话")
        text = dossier.text(p, "text", 1600, True)
        day = dossier.calendar_day(p["day"], "记录日期", today).isoformat()
        req = dossier.text(p, "requestId", 80, True)
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", req):
            raise ValueError("健康记录提交编号有误")
        request = "manual/" + req
        refs = []
    elif action == "dossier.signHealthIntro":
        access.require(user, "medical")
        access.require(user, "clinical")
        if set(p) != {"residentId", "draftId", "selected", "confirmed"}:
            raise ValueError("请核对本人的健康简介草稿")
        item = db.execute(
            """SELECT id,basis,points FROM resident_health_drafts
            WHERE id=? AND actor=? AND resident_id=?""",
            (p["draftId"], user["id"], rid),
        ).fetchone()
        if not item:
            raise ValueError("这份草稿不属于当前经办人或这位长者")
        points = json.loads(item[2])
        indexes = p["selected"]
        if (
            not isinstance(indexes, list)
            or not indexes
            or any(type(i) is not int or not 0 <= i < len(points) for i in indexes)
            or indexes != sorted(set(indexes))
        ):
            raise ValueError("请勾选已核对的健康要点")
        if _basis(rid, evidence.collect(db, person)) != item[1]:
            raise ValueError("这位长者的健康资料已更新，请重新核对")
        refs = [points[i] for i in indexes]
        text = "\n".join(r["text"] for r in refs)
        kind, day, request = "ai", today, "draft/" + item[0]
    else:
        raise ValueError("未知健康档案操作")
    prior = db.execute(
        """SELECT resident_id,kind,event_day,content,refs FROM resident_health_notes
        WHERE actor=? AND request=?""",
        (user["id"], request),
    ).fetchone()
    packed = dossier.pack(refs)
    if prior:
        if tuple(prior) == (rid, kind, day, text, packed):
            return "本次健康记录已签认"
        raise ValueError("本次健康记录已经保存，请重新核对")
    role = user["role"]
    if role == "自定义":
        role = "、".join(user.get("staffDuties") or []) or "岗位未登记"
    db.execute(
        "INSERT INTO resident_health_notes VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            uuid4().hex,
            rid,
            kind,
            day,
            text,
            packed,
            user["id"],
            user["displayName"],
            role,
            now.isoformat(timespec="seconds"),
            request,
        ),
    )
    return {
        "ai": "已签认 AI 健康简介",
        "intro": "已填写健康简介",
        "addition": "已补充健康简介",
        "conversation": "已记录长者本人的健康谈话",
    }[kind]
