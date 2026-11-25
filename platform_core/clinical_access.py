"""Append access receipts for clinical HTTP reads on licensed installations."""
from contextlib import closing
import re

# Persist only our resource identifiers. Never store query strings, uploads, answers or headers.
RESOURCE = re.compile(r"/api/(?:state|medical-visits/originals/[a-f0-9]{32}|"
                      r"residents/[A-Za-z0-9_-]{1,100}/(?:health-profile|personal-brief|summary-draft|reported-medications|daily-life)"
                      r"|care-timeline/(?:resident|room)/[A-Za-z0-9_-]{1,100}|care/handover-draft|agent/room-context|daily-life/roster|documents/[A-Za-z0-9_-]{1,100}/(?:ocr|image|pages/[0-9]{1,4})|portal/history/(?:careSchedule|medication)|dossier/credentials/[a-f0-9]{32})")


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS clinical_reads(
        seq INTEGER PRIMARY KEY, at TEXT NOT NULL, actor TEXT NOT NULL, role TEXT NOT NULL,
        resource TEXT NOT NULL, status INTEGER NOT NULL, peer TEXT NOT NULL)""")
    for operation in ("UPDATE", "DELETE"):
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS clinical_reads_no_{operation} BEFORE {operation} ON clinical_reads
                        BEGIN SELECT RAISE(ABORT, 'clinical access receipts are append-only'); END""")


def receipt(store, token, resource, status, peer):
    if not RESOURCE.fullmatch(resource):
        return
    from .store import SignedOut
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        try:
            user = store.actor(db, token)
        except SignedOut:
            if status == 200:
                raise
            user = {"id":"", "role":""}
        db.execute("INSERT INTO clinical_reads(at,actor,role,resource,status,peer) VALUES(?,?,?,?,?,?)",
                   (store.now().isoformat(), user["id"], user["role"], resource, status, peer))
