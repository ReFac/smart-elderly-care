"""Build a bounded, local chart summary on request and retain the signed source references."""

import hashlib
import json

from . import access
from .care.records import append_record, lookup


SOURCE = "动态档案摘要复核"


def excerpt(value, size=220):
    return value if len(value) <= size else value[:size].rstrip() + "…"


def summary_draft(db, state, user, resident_id):
    from .care.archive_retention import require_ai_eligible

    require_ai_eligible(state, resident_id)
    access.require(user, "medical")
    access.require(user, "clinical")
    resident = lookup(state, "residents", resident_id)
    evidence = [
        {
            "source": "residents",
            "id": resident_id,
            "label": "当前登记",
            "value": f"在院状态 {resident['status']}，护理等级 {resident['level']}。过敏史：{resident.get('allergies') or '未登记'}。高危要点：{resident.get('risk') or '未登记'}。",
        }
    ]
    prior = [
        r
        for r in state.get("archives", ())
        if r["residentId"] == resident_id
        and r.get("reviewer")
        and r.get("source") != SOURCE
    ]
    for row in sorted(
        reversed(prior), key=lambda r: r.get("observedAt") or r["date"], reverse=True
    )[:2]:
        evidence.append(
            {
                "source": "archives",
                "id": row["id"],
                "label": (row.get("source") or "照护复核") + " · " + row["date"],
                "value": excerpt(row["summary"]),
            }
        )
    docs = db.execute(
        """
        SELECT d.id,d.event_date,d.metadata,r.review FROM dossier_documents d
        LEFT JOIN dossier_document_reviews r ON r.document_id=d.id WHERE d.resident_id=?
        AND (json_type(d.metadata,'$.summary')='object' OR r.review IS NOT NULL)
        AND COALESCE(json_extract(r.review,'$.identityMatch'),1)=1
        ORDER BY d.event_date DESC, d.rowid DESC LIMIT 2""",
        (resident_id,),
    )
    for did, day, meta, review in docs:
        doc = json.loads(meta)
        summary = json.loads(review)["summary"] if review else doc["summary"]
        evidence.append(
            {
                "source": "dossier_documents",
                "id": did,
                "label": f"{doc['category']} · {day}",
                "value": excerpt(summary["sourceFacts"]),
            }
        )
    fingerprint = hashlib.sha256(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return {
        "residentId": resident_id,
        "fingerprint": fingerprint,
        "evidence": evidence,
        "summary": "\n".join(e["label"] + "：" + e["value"] for e in evidence),
    }


def sign_summary(db, state, p, user, today):
    if (
        set(p) != {"residentId", "fingerprint", "summary", "confirmed"}
        or p.get("confirmed") is not True
    ):
        raise ValueError("请核对摘要及其来源后签认")
    draft = summary_draft(db, state, user, p["residentId"])
    if p["fingerprint"] != draft["fingerprint"]:
        raise ValueError("摘要依据已经变化，请重新生成并核对")
    value = p["summary"]
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 3000
        or any(ord(c) < 32 and c not in "\n\t\r" for c in value)
    ):
        raise ValueError("请填写 1 至 3000 字已核对的摘要")
    value = value.strip()
    rid = p["residentId"]
    for row in state["archives"]:
        if (
            row["residentId"] == rid
            and row.get("draftFingerprint") == draft["fingerprint"]
        ):
            if row["summary"] == value:
                return f"长者 {rid} 的本次动态档案摘要已签认"
            raise ValueError("该组资料已有签认版本，请核对历史摘要")
    resident = lookup(state, "residents", rid)
    append_record(
        state,
        "archives",
        residentId=rid,
        date=today,
        source=SOURCE,
        reviewer=user["displayName"],
        reviewerId=user["id"],
        summary=value,
        previousSummary=resident.get("summary") or "",
        risk=resident.get("risk") or "",
        allergies=resident.get("allergies") or "",
        evidence=draft["evidence"],
        draftFingerprint=draft["fingerprint"],
    )
    resident["summary"] = value
    return f"已签认长者 {rid} 的动态档案摘要"
