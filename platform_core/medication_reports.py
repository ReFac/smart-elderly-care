"""Patient-reported medicine history, with immutable signed-off revisions."""

from contextlib import closing
import hashlib
import json
import re
from uuid import uuid4

from . import access, campus_access, dossier, drug_catalog, drug_search
from .care import archive_retention
from .care.records import lookup as find, text_field


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS drug_name_references(
        id TEXT PRIMARY KEY, name TEXT NOT NULL, source TEXT NOT NULL, url TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS resident_medication_reports(
        id TEXT PRIMARY KEY, report_id TEXT NOT NULL, version INTEGER NOT NULL,
        resident_id TEXT NOT NULL, event_day TEXT NOT NULL, raw_name TEXT NOT NULL,
        reference TEXT NOT NULL, name TEXT NOT NULL, source TEXT NOT NULL, url TEXT NOT NULL,
        regimen TEXT NOT NULL, actor TEXT NOT NULL, actor_name TEXT NOT NULL,
        actor_role TEXT NOT NULL, self_report INTEGER NOT NULL, recorded_at TEXT NOT NULL,
        request TEXT NOT NULL, UNIQUE(report_id,version), UNIQUE(actor,request))""")
    db.execute(
        "CREATE INDEX IF NOT EXISTS reported_meds_resident ON resident_medication_reports(resident_id,event_day)"
    )
    for op in ("UPDATE", "DELETE"):
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS reported_meds_no_{op} BEFORE {op} ON
            resident_medication_reports BEGIN SELECT RAISE(ABORT,'请追加更正以保留自报原文'); END""")


def _access(db, user, rid, state, writing=False):
    if user["kind"] == "family":
        if not (
            user.get("portalSelf")
            and rid == user.get("residentId")
            and "medicationReport" in user.get("portalScopes", ())
        ):
            raise PermissionError("此账号未获本人用药自报授权")
        can_write = True
    else:
        if user["kind"] not in ("owner", "staff") or not any(
            access.has(user, k) for k in ("care", "medical", "clinical")
        ):
            raise PermissionError("仅有照护或医疗权限的员工可查看用药自报")
        campus_access.require_resident(db, user, rid, state)
        can_write = access.has(user, "care")
    person = find(state, "residents", rid)
    if person["status"] == archive_retention.EXPIRED:
        raise FileNotFoundError("已到保管期")
    if writing:
        archive_retention.writable(state, rid)
        if not can_write:
            raise PermissionError("未获用药自报登记权限")
    return can_write and person["status"] != archive_retention.ARCHIVED


def _session(db, store, token, rid, writing=False):
    user = store.actor(db, token)
    revision, raw = db.execute(
        "SELECT revision,data FROM workspace WHERE id=1"
    ).fetchone()
    return revision, _access(db, user, rid, json.loads(raw), writing)


def read(store, token, rid):
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        revision, can_write = _session(db, store, token, rid)
        reports = {}
        for row in db.execute(
            """SELECT * FROM resident_medication_reports WHERE resident_id=?
                ORDER BY report_id, version DESC""",
            (rid,),
        ):
            entry = {
                "reportId": row["report_id"],
                "version": row["version"],
                "day": row["event_day"],
                "rawName": row["raw_name"],
                "reference": row["reference"],
                "name": row["name"],
                "source": row["source"],
                "url": row["url"],
                "regimen": row["regimen"],
                "at": row["recorded_at"],
                "bySelf": bool(row["self_report"]),
                "actorName": row["actor_name"],
                "actorRole": row["actor_role"],
            }
            reports.setdefault(row["report_id"], []).append(entry)
        return {
            "revision": revision,
            "canWrite": can_write,
            "reports": [
                {**entries[0], "history": entries[1:]}
                for entries in sorted(
                    reports.values(), key=lambda rows: rows[0]["at"], reverse=True
                )
            ],
        }


def lookup(store, token, rid, query, online=False):
    with closing(store.connect()) as db, db:
        _session(db, store, token, rid, writing=True)
        if online:
            state = json.loads(
                db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
            )
            if not drug_search.public_term(db, state, query):
                raise ValueError(
                    "联网查询只能提交药名，请移除人员、房号、剂量和联系方式"
                )
    result = drug_search.search(query) if online else drug_catalog.suggestions(query)
    # Recheck scope after network I/O, without holding the encrypted DB's write lock.
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        _session(db, store, token, rid, writing=True)
        for match in result["matches"]:
            url = (
                match["url"]
                if online
                else drug_catalog.PDF + "#page=" + str(match["page"])
            )
            ref = hashlib.sha256(
                (result["source"] + "\0" + match["name"] + "\0" + url).encode()
            ).hexdigest()
            db.execute(
                "INSERT OR IGNORE INTO drug_name_references VALUES(?,?,?,?)",
                (ref, match["name"], result["source"], url),
            )
            match.update(reference=ref, url=url)
    return result


def record(db, state, user, payload, now):
    rid = payload.get("residentId")
    _access(db, user, rid, state, writing=True)
    expected = {
        "residentId",
        "day",
        "rawName",
        "reference",
        "regimen",
        "reportId",
        "expectedVersion",
        "requestId",
        "confirmed",
    }
    if set(payload) != expected or payload.get("confirmed") is not True:
        raise ValueError("请核对本次自报的药名与用法后确认保存")
    request = text_field(payload["requestId"], "请求编号", required=True, limit=80)
    if not re.fullmatch("[A-Za-z0-9_-]+", request):
        raise ValueError("请求编号无效")
    day = dossier.calendar_day(
        payload["day"], "自报日期", now.date().isoformat()
    ).isoformat()
    raw = text_field(payload["rawName"], "自报药名原文", required=True, limit=60)
    regimen = text_field(payload["regimen"], "本人陈述的用法", limit=400)
    ref = text_field(payload["reference"], "目录药名编号", limit=64)
    name, source, url = "", "", ""
    if ref:
        option = db.execute(
            "SELECT name,source,url FROM drug_name_references WHERE id=?", (ref,)
        ).fetchone()
        if not option:
            # Business restores preserve evidence even if this process has no catalogue cache.
            option = db.execute(
                """SELECT name,source,url FROM resident_medication_reports
                WHERE resident_id=? AND report_id=? AND reference=? LIMIT 1""",
                (rid, payload["reportId"], ref),
            ).fetchone()
        if not option:
            raise ValueError("请重新搜索并核对目录候选药名")
        name, source, url = option
    previous = payload["expectedVersion"]
    report = text_field(payload["reportId"], "自报记录编号", limit=40)
    if type(previous) is not int or previous < 0 or bool(report) != bool(previous):
        raise ValueError("自报版本无效，请刷新记录")
    prior = db.execute(
        "SELECT * FROM resident_medication_reports WHERE actor=? AND request=?",
        (user["id"], request),
    ).fetchone()
    if prior:
        if (
            prior["resident_id"],
            prior["version"],
            prior["event_day"],
            prior["raw_name"],
            prior["reference"],
            prior["regimen"],
        ) != (rid, previous + 1, day, raw, ref, regimen) or (
            report and report != prior["report_id"]
        ):
            raise ValueError("同一提交编号已用于另一条自报")
        return "用药自报已保存"
    if report:
        current = db.execute(
            "SELECT MAX(version) FROM resident_medication_reports WHERE report_id=? AND resident_id=?",
            (report, rid),
        ).fetchone()[0]
        if current != previous:
            raise ValueError("这条自报已变更或不属于这位长者，请重新查看后更正")
    else:
        report = uuid4().hex
    db.execute(
        "INSERT INTO resident_medication_reports VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            uuid4().hex,
            report,
            previous + 1,
            rid,
            day,
            raw,
            ref,
            name,
            source,
            url,
            regimen,
            user["id"],
            user["displayName"],
            user.get("role", ""),
            int(user["kind"] == "family"),
            now.isoformat(timespec="seconds"),
            request,
        ),
    )
    return "已更正长者用药自报" if previous else "已登记长者用药自报"
