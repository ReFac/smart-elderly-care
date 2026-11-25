"""Immutable institution locale and independent regional business rules."""
from functools import cache
import json
import os
from pathlib import Path
import re

ASSETS = Path(__file__).resolve().parents[1] / "web" / "assets"
TAG = re.compile(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*")


@cache
def locales():
    entries = json.loads((ASSETS / "deployment-locales.json").read_text(encoding="utf-8"))
    if not isinstance(entries, dict) or not {"zh-CN", "en"} <= entries.keys():
        raise ValueError("A deployment requires Chinese and English base locales")
    for tag, item in entries.items():
        if not TAG.fullmatch(tag) or not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("Invalid deployment locale")
        if item.get("edition", "international") not in {"china", "international"}:
            raise ValueError("Unknown business edition")
    return entries


def public(language):
    record = locales()[language]
    edition = record.get("edition", "international")
    fallback = "en" if edition == "international" else "zh-CN"
    overlay = ASSETS / "locales" / (language + ".json")
    return {"language": language, "languageName": record["name"], "edition": edition,
            "mapProvider": "google" if edition == "international" else "amap",
            "fallbackLanguage": fallback,
            "messagesOverlay": f"/assets/locales/{language}.json" if language != fallback and overlay.is_file() else None}


@cache
def _messages(language):
    if not public(language)["messagesOverlay"]:
        return {}
    return json.loads((ASSETS / "locales" / (language + ".json")).read_text(encoding="utf-8"))


def message(language, fallback):
    """Use a local deployment translation when available; keep the shipped English fallback."""
    return _messages(language).get(fallback, fallback)


def initialize(db, *, fresh):
    requested = os.environ.get("NH_DEPLOYMENT_LANGUAGE")
    if requested is not None and requested not in locales():
        raise ValueError("Supported deployment languages: " + ", ".join(locales()))
    db.execute("""CREATE TABLE IF NOT EXISTS deployment_language (
        id INTEGER PRIMARY KEY CHECK(id=1), language TEXT NOT NULL)""")
    row = db.execute("SELECT language FROM deployment_language WHERE id=1").fetchone()
    language = row[0] if row else "zh-CN"
    if fresh and row is None and requested:
        language = requested
    if language not in locales():
        raise ValueError(f"This release does not include the installed locale {language}.")
    if requested and requested != language:
        raise ValueError(f"This institution was initialized with {language}. Its language cannot be changed.")
    if row is None:
        db.execute("INSERT INTO deployment_language VALUES(1,?)", (language,))
    for event in ("UPDATE", "DELETE"):
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS deployment_language_no_{event} BEFORE {event}
            ON deployment_language BEGIN SELECT RAISE(ABORT,'deployment language is immutable'); END""")
    return language


def script(language):
    return ("window.NH_DEPLOYMENT=Object.freeze(" + json.dumps(public(language)) + ");").encode()


def page(content, language):
    info = public(language)
    tags = b'<script src="/deployment.js"></script>'
    if info["edition"] == "international":
        display_lang = language if info["messagesOverlay"] else info["fallbackLanguage"]
        content = content.replace(b'lang="zh-CN"', f'lang="{display_lang}"'.encode(), 1)
        tags += b'<script defer src="/lib/deployment-i18n.js"></script>'
    return content.replace(b"<head>", b"<head>" + tags, 1)
