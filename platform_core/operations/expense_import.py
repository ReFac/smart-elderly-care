"""Finance-controlled preview, reconciliation and archival of paid expense evidence."""

import base64
import binascii
from contextlib import closing
from decimal import Decimal
from hashlib import sha256
import json
import re
from uuid import uuid4

from .. import access
from .dispatch import unrestricted
from .expense_files import MAX_ROWS, bank_or_power_csv, power_invoice
from .settlements import expense

FILE_LIMIT = 1024 * 1024


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS expense_file_previews(
        id TEXT PRIMARY KEY, actor TEXT NOT NULL, expires INTEGER NOT NULL,
        source TEXT NOT NULL, name TEXT NOT NULL, original BLOB NOT NULL, rows TEXT NOT NULL)""")


def require_finance(actor):
    access.require(actor, "finance")
    if not unrestricted(actor):
        raise PermissionError("机构支出文件需要全机构财务授权")


def read_file(payload):
    if set(payload) != {"source", "fileName", "contentBase64"}:
        raise ValueError("请选择账单来源和原始文件")
    source, name, body = (payload[k] for k in ("source", "fileName", "contentBase64"))
    if (
        source not in ("bank", "electricity")
        or not isinstance(name, str)
        or not re.fullmatch(r"[^/\\\x00-\x1f\x7f]{1,160}", name)
    ):
        raise ValueError("来源或文件名无效")
    if not isinstance(body, str) or len(body) > 4 * ((FILE_LIMIT + 2) // 3):
        raise ValueError("单个账单文件限 1 MiB")
    try:
        raw = base64.b64decode(body, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("账单文件编码无效") from None
    if not raw or len(raw) > FILE_LIMIT:
        raise ValueError("单个账单文件限 1 MiB，文件不能为空")
    return source, name, raw


def keys(row):
    return {(k, row[k]) for k in ("transactionId", "invoiceNo") if row.get(k)}


def review(row, candidates, reason):
    refs = []
    for e in candidates[:5]:
        origins = {f["source"] for f in e.get("evidenceFiles", [])}
        sources = [
            label
            for key, label in (("bank", "银行"), ("electricity", "电费"))
            if key in origins
        ]
        refs.append(f"{'、'.join(sources) or '手工'}凭证 {e['voucher']}（{e['date']}）")
    return {
        **row,
        "status": "review",
        "reason": f"{reason}。请对照{'；'.join(refs)}",
    }, None


def decision(row, entries, digest, source):
    if row["status"] != "ready" and not row.get("invoiceOnly"):
        return row, None
    refs = keys(row)
    raw_refs = {v for _, v in refs}
    matched = [
        e
        for e in entries
        if keys(e) & refs or (not keys(e) and e.get("voucher") in raw_refs)
    ]
    if not matched:
        candidates = [
            e
            for e in entries
            if (
                row["date"] == e["date"]
                and row["amount"] == e["amount"]
                and row["payee"] == e["payee"]
                and (
                    not e.get("evidenceFiles")
                    or any(f["source"] != source for f in e["evidenceFiles"])
                )
                and not any(
                    row.get(k) and e.get(k) and row[k] != e[k]
                    for k in ("invoiceNo", "transactionId")
                )
            )
        ]
        if candidates:
            return review(row, candidates, "同日、同额、同收款方，尚无共同凭证号")
        return row, None
    existing = matched[0]
    incompatible_refs = any(
        row.get(k) and existing.get(k) and row[k] != existing[k]
        for k in ("invoiceNo", "transactionId")
    )
    if (
        len(matched) != 1
        or existing["amount"] != row["amount"]
        or existing["payee"] != row["payee"]
        or incompatible_refs
    ):
        return review(row, matched, "相同凭证对应的金额、收款方或流水有冲突")
    bank_date = existing.get("bankDate")
    if not bank_date and any(
        f["source"] == "bank" for f in existing.get("evidenceFiles", ())
    ):
        bank_date = existing["date"]
    if source == "bank" and bank_date and row["date"] != bank_date:
        return review(
            row, matched, f"同一银行流水的实付日期不同，原银行记账日为 {bank_date}"
        )
    if any(
        item["id"] == digest and item["rowNumber"] == row["rowNumber"]
        for item in existing.get("evidenceFiles", ())
    ):
        return {
            **row,
            "status": "duplicate",
            "reason": "该凭证及文件行已登记",
        }, existing
    return {
        **row,
        "status": "ready",
        "mode": "link",
        "reason": "关联至已有支出，新增支出 ¥0",
    }, existing


def entry_fields(row):
    return {
        k: row[k] for k in ("date", "payee", "amount", "category", "note", "voucher")
    }


def attach(entry, row, ref):
    for k in ("transactionId", "invoiceNo"):
        if row.get(k):
            entry[k] = row[k]
    entry.setdefault("evidenceFiles", []).append(ref)
    if ref["source"] == "bank":
        entry["bankDate"] = row["date"]


def classify(rows, entries, digest, source):
    # Detect ambiguous identifiers in the entire uploaded file before presenting any of them.
    seen, conflict = {}, set()
    for r in rows:
        if r["status"] != "ready":
            continue
        for key in keys(r):
            other = "invoiceNo" if key[0] == "transactionId" else "transactionId"
            first = seen.setdefault(key, r)
            if (first["amount"], first["payee"], first["date"]) != (
                r["amount"],
                r["payee"],
                r["date"],
            ) or (first[other] and r[other] and first[other] != r[other]):
                conflict.add(key)
            if r[other]:
                seen[key] = r
    out = []
    known = list(entries)
    for row in rows:
        if keys(row) & conflict:
            out.append(
                {
                    **row,
                    "status": "review",
                    "reason": "同一文件内凭证号对应多笔不同实付记录",
                }
            )
            continue
        item, prior = decision(row, known, digest, source)
        if item["status"] == "ready" and prior and "previewRow" in prior:
            item = {
                **item,
                "status": "duplicate",
                "reason": f"与本文件第 {prior['previewRow']} 行为同一笔支出",
            }
        elif item["status"] == "ready" and not prior:
            known.append(
                {
                    "previewRow": item["rowNumber"],
                    **entry_fields(item),
                    **{k: item[k] for k in ("transactionId", "invoiceNo")},
                }
            )
        out.append(item)
    return out


def preview(store, token, payload):
    with closing(store.connect()) as db:
        require_finance(store.actor(db, token))
    source, name, raw = read_file(payload)
    now = store.now()
    if name.lower().endswith(".csv"):
        rows = bank_or_power_csv(raw, source, now.date().isoformat())
    elif source == "electricity" and name.lower().endswith(".xml"):
        rows = power_invoice(raw)
    else:
        raise ValueError("银行请上传 CSV；电费可上传缴费 CSV 或数电发票 XML")
    digest = sha256(raw).hexdigest()
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        actor = store.actor(db, token)
        require_finance(actor)
        revision, entries = db.execute(
            "SELECT revision,json_extract(data,'$.expenses') FROM workspace WHERE id=1"
        ).fetchone()
        rows = classify(rows, json.loads(entries or "[]"), digest, source)
        stamp = int(now.timestamp())
        db.execute("DELETE FROM expense_file_previews WHERE expires<=?", (stamp,))
        # Bound transient originals for an account, also when a user abandons the preview dialog.
        db.execute(
            "DELETE FROM expense_file_previews WHERE id IN (SELECT id FROM expense_file_previews WHERE actor=? ORDER BY rowid DESC LIMIT -1 OFFSET 9)",
            (actor["id"],),
        )
        ticket = uuid4().hex
        db.execute(
            "INSERT INTO expense_file_previews VALUES(?,?,?,?,?,?,?)",
            (
                ticket,
                actor["id"],
                stamp + 1800,
                source,
                name,
                raw,
                json.dumps(rows, ensure_ascii=False),
            ),
        )
    return {"previewId": ticket, "rows": rows, "revision": revision}


def apply(db, state, payload, actor, now):
    require_finance(actor)
    if set(payload) != {"previewId", "rowNumbers"}:
        raise ValueError("请确认预览中要入账的行")
    selected = payload["rowNumbers"]
    if (
        not isinstance(selected, list)
        or not 1 <= len(selected) <= MAX_ROWS
        or any(type(n) is not int for n in selected)
        or len(set(selected)) != len(selected)
    ):
        raise ValueError("请选择有效的凭证行")
    batch = db.execute(
        "SELECT source,name,original,rows FROM expense_file_previews WHERE id=? AND actor=? AND expires>?",
        (payload["previewId"], actor["id"], int(now.timestamp())),
    ).fetchone()
    if not batch:
        raise ValueError("预览已过期或不属于当前经办人，请重新上传")
    source, name, raw, stored = batch
    digest = sha256(raw).hexdigest()
    rows = {r["rowNumber"]: r for r in json.loads(stored)}
    if any(n not in rows or rows[n]["status"] != "ready" for n in selected):
        raise ValueError("只可选择预览中待确认的行")
    added = linked = 0
    added_amount = Decimal(0)
    for n in sorted(selected):
        row = rows[n]
        item, existing = decision(row, state["expenses"], digest, source)
        if item["status"] == "duplicate":
            continue
        if item["status"] != "ready" or (
            (row.get("mode") == "link") != (existing is not None)
        ):
            raise ValueError("所选凭证的核对结果已变化，请重新预览")
        if existing is None:
            expense(state, entry_fields(item), now.date().isoformat())
            existing = state["expenses"][0]
            added += 1
            added_amount += Decimal(str(row["amount"]))
        else:
            linked += 1
        attach(
            existing,
            item,
            {"id": digest, "rowNumber": n, "name": name, "source": source},
        )
    if added or linked:
        db.execute(
            "INSERT OR IGNORE INTO storage_assets(namespace,name,mime,sha256,data) VALUES('expense',?,'application/octet-stream',?,?)",
            (digest, digest, raw),
        )
    return (
        f"已登记 {added} 笔实付支出 ¥{added_amount:.2f}，关联 {linked} 条补充凭证",
        bool(added or linked),
    )


def original(store, token, digest):
    with closing(store.connect()) as db:
        require_finance(store.actor(db, token))
        row = db.execute(
            "SELECT data FROM storage_assets WHERE namespace='expense' AND name=?",
            (digest,),
        ).fetchone()
        if not row:
            raise FileNotFoundError("找不到已归档的支出原件")
        return bytes(row[0])
