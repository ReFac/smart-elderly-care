"""Employee contract originals, version history and monthly pay dates."""

import calendar
from contextlib import closing
from datetime import date
from uuid import uuid4

from . import access, dossier, staff_scope
from .care.records import iso_date, text_field
from .operations.records import whole_number


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS staff_contract_originals(
        sha256 TEXT PRIMARY KEY, mime TEXT NOT NULL, original BLOB NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS staff_contract_versions(
        id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
        version INTEGER NOT NULL, contract_no TEXT NOT NULL, signed_on TEXT NOT NULL,
        starts_on TEXT NOT NULL, ends_on TEXT NOT NULL, filename TEXT NOT NULL,
        digest TEXT NOT NULL REFERENCES staff_contract_originals(sha256),
        recorded_at TEXT NOT NULL, recorded_by TEXT NOT NULL REFERENCES accounts(id),
        UNIQUE(account_id,version))""")
    db.execute("""CREATE TABLE IF NOT EXISTS staff_paydays(
        account_id TEXT PRIMARY KEY REFERENCES accounts(id), payday INTEGER NOT NULL
        CHECK(payday BETWEEN 1 AND 31))""")


def employee(db, actor, account_id, facility_policy, *, editing):
    if not editing and actor["kind"] == "staff" and actor["id"] == account_id:
        return actor
    if not access.manages_accounts(actor):
        raise PermissionError("无权查看或管理员工合同")
    target = access._target(
        db, {"id": account_id}, actor, staff_scope.boundary(db, actor, facility_policy)
    )
    if target["kind"] != "staff":
        raise ValueError("请选择员工账号")
    return target


def next_payday(today, day):
    year, month = today.year, today.month
    this_month = date(year, month, min(day, calendar.monthrange(year, month)[1]))
    if this_month >= today:
        return this_month.isoformat()
    year, month = year + month // 12, month % 12 + 1
    return date(year, month, min(day, calendar.monthrange(year, month)[1])).isoformat()


def read(store, token, account_id, contract_id=None):
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        actor = store.actor(db, token)
        person = employee(db, actor, account_id, store.facility_policy, editing=False)
        if contract_id:
            row = db.execute(
                """SELECT o.original,o.mime FROM staff_contract_versions v
                JOIN staff_contract_originals o ON o.sha256=v.digest WHERE v.account_id=? AND v.id=?""",
                (account_id, contract_id),
            ).fetchone()
            if not row:
                raise FileNotFoundError("未找到此员工的合同版本")
            return row[0], row[1]
        row = db.execute(
            "SELECT payday FROM staff_paydays WHERE account_id=?", (account_id,)
        ).fetchone()
        versions = db.execute(
            """SELECT v.id,v.version,v.contract_no AS number,v.signed_on AS signedOn,
                v.starts_on AS startsOn,v.ends_on AS endsOn,v.filename,v.digest AS sha256,
                v.recorded_at AS recordedAt,a.display_name AS recordedBy
                FROM staff_contract_versions v JOIN accounts a ON a.id=v.recorded_by
                WHERE v.account_id=? ORDER BY v.version DESC""",
            (account_id,),
        )
        return {
            "id": person["id"],
            "displayName": person["displayName"],
            "canEdit": actor["id"] != account_id and access.manages_accounts(actor),
            "payday": row[0] if row else None,
            "nextPayday": next_payday(store.now().date(), row[0]) if row else "",
            "contracts": [dict(r) for r in versions],
        }


def apply(db, actor, action, p, now, facility_policy):
    person = employee(db, actor, p.get("id"), facility_policy, editing=True)
    account_id = person["id"]
    if action == "access.staffPayday":
        day = whole_number(p.get("payday"), "工资日")
        if day > 31:
            raise ValueError("工资日须为每月 1 至 31 日")
        db.execute(
            """INSERT INTO staff_paydays VALUES(?,?) ON CONFLICT(account_id)
                    DO UPDATE SET payday=excluded.payday""",
            (account_id, day),
        )
        return f"将{person['displayName']}的工资日设为每月{day}日"
    number = text_field(p.get("number"), "合同编号", limit=100)
    signed = iso_date(p.get("signedOn"), "签订日期")
    if signed > now.date().isoformat():
        raise ValueError("签订日期不能晚于今日")
    start = iso_date(p.get("startsOn"), "合同起始日期")
    end = iso_date(p["endsOn"], "合同结束日期") if p.get("endsOn") else ""
    if end and end < start:
        raise ValueError("合同结束日期不能早于起始日期")
    filename = text_field(p.get("filename"), "原件文件名", required=True, limit=180)
    if any(c in "/\\" or ord(c) < 32 for c in filename):
        raise ValueError("原件文件名无效")
    raw, mime, digest = dossier.photo_payload(p, allow_pdf=True)
    if not raw or (mime == "application/pdf" and not raw.rstrip().endswith(b"%%EOF")):
        raise ValueError("请提供完整的劳动合同原件")
    db.execute(
        "INSERT OR IGNORE INTO staff_contract_originals VALUES(?,?,?)",
        (digest, mime, raw),
    )
    version = db.execute(
        "SELECT COALESCE(MAX(version),0)+1 FROM staff_contract_versions WHERE account_id=?",
        (account_id,),
    ).fetchone()[0]
    db.execute(
        """INSERT INTO staff_contract_versions
          (id,account_id,version,contract_no,signed_on,starts_on,ends_on,filename,digest,recorded_at,recorded_by)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            uuid4().hex,
            account_id,
            version,
            number,
            signed,
            start,
            end,
            filename,
            digest,
            now.isoformat(timespec="seconds"),
            actor["id"],
        ),
    )
    return f"已留存{person['displayName']}的劳动合同第{version}版"
