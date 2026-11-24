"""Public reception and scoped schedule reads. Staff commands use Store.execute."""

from collections import OrderedDict
from contextlib import closing
import json
from threading import Lock
from time import monotonic

from . import access, activity, facility, history, lead_contacts, visit_schedule


class SubmissionLimit(Exception):
    pass


class PublicSubmissions:
    """Short-lived counters for the direct peer; no visitor identifier goes into the ledger."""

    def __init__(self):
        self.lock = Lock()
        self.windows = OrderedDict()

    def check(self, peer):
        now = monotonic()
        with self.lock:
            while self.windows and next(iter(self.windows.values()))[0] <= now:
                self.windows.popitem(last=False)
            if peer not in self.windows:
                if len(self.windows) >= 4096:
                    raise SubmissionLimit("当前咨询较多，请稍后再试")
                self.windows[peer] = [now + 300, 0]
            window = self.windows[peer]
            if window[1] >= 30:
                raise SubmissionLimit("本次提交过于频繁，请稍后再试")
            window[1] += 1


def reception(store):
    with closing(store.connect()) as db:
        campuses = [
            dict(r)
            for r in db.execute("SELECT id,name FROM facility_campuses ORDER BY rowid")
        ]
    return {**store.branding(), "campuses": campuses}


def submit(store, payload, peer):
    store.public_submissions.check(peer)
    from .store import encode

    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        revision, raw = db.execute(
            "SELECT revision,data FROM workspace WHERE id=1"
        ).fetchone()
        state, now = json.loads(raw), store.now()
        history.watch(db, "leads.public")
        if lead_contacts.receive(db, state, payload, now):
            db.execute(
                "UPDATE workspace SET data=?,revision=? WHERE id=1",
                (encode(state), revision + 1),
            )
            activity.write(
                db,
                revision + 1,
                now.isoformat(timespec="seconds"),
                "leads.public",
                "收到访客咨询",
                {"id": "public-visitor", "username": "", "displayName": "宣传页访客"},
                {"campusId": payload.get("campusId") or facility.HOME_CAMPUS},
                {},
            )
    return {"received": True}


def schedule(store, token, campus_id, day):
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        user = store.actor(db, token)
        access.require(user, "intake")
        campus_id = lead_contacts.require_campus(db, user, campus_id)
        state = json.loads(
            db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
        )
        now = store.now()
        lead_contacts.reconcile_callbacks(db, state, now)
        return visit_schedule.day_view(state, campus_id, day, now)
