"""Recognize an onboarding document and return editable staff-account suggestions."""

from contextlib import closing
import re
from unicodedata import normalize

from . import access, document_ocr, identity


MAX_BYTES = 8 * 1024 * 1024
NAME = re.compile(r"(?:^|\s)(?:姓名|应聘人|candidate name|name)\s*[:：]\s*([\w·• -]{2,60}?)(?=\s+[\w ]{1,20}[:：]|$)", re.I)
PHONE = re.compile(r"(?<![0-9+])(?:\+86[ -]?)?1[3-9][0-9]{9}(?![0-9])")


def authorize(store, db, token):
    actor = store.actor(db, token)
    access.require(actor, "staff.manage")
    return actor


def suggestions(result):
    complete = {p["page"] for p in result.get("pages", ()) if p["state"] == "complete"}
    evidence = {"displayName": {}, "phone": {}}
    for line in result.get("lines", ()):
        if line["page"] not in complete:
            continue
        text = line["text"]
        name = NAME.search(text)
        if name:
            value = " ".join(name[1].split())
            if not any(c.isdigit() or c == "_" for c in value):
                evidence["displayName"].setdefault(value, line)
        phone_text = normalize("NFKC", text)
        if re.match(r"(?:手机号码?|联系电话|手机|电话|mobile|phone)\s*:", phone_text, re.I):
            for match in PHONE.finditer(phone_text):
                value = identity.destination("sms", re.sub(r"[ -]", "", match[0]))
                evidence["phone"].setdefault(value, line)
    fields = {}
    for field, values in evidence.items():
        if len(values) == 1:
            value, line = next(iter(values.items()))
            fields[field] = {"value": value, "page": line["page"], "line": line["line"]}
    return {"fields": fields, "ambiguous": [f for f, v in evidence.items() if len(v) > 1]}


def preview(store, token, raw):
    if not raw.startswith((b"%PDF-", b"\x89PNG", b"\xff\xd8")):
        raise ValueError("请选择 PDF、PNG 或 JPEG 简历")
    result, _, _ = document_ocr.recognize(
        store, token, raw, lambda db, current: authorize(store, db, current),
        feature="access.resumeOcr",
    )
    return suggestions(result)


def check(store, token):
    with closing(store.connect()) as db:
        authorize(store, db, token)
