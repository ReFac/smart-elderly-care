"""Release elapsed trial beds and retain the unresolved admission decision across restarts."""

from contextlib import closing
import json

from .records import offset_date
from .residency import TRIAL_PENDING as PENDING, move

SERVICE = {
    "id": "trial-service",
    "displayName": "试住到期服务",
    "username": "trial-service",
}


def due(state, day):
    return [
        person
        for person in state["residents"]
        if person.get("stayType") == "trial"
        and person["status"] == "在住"
        and person.get("trialEndsAt")
        and person["trialEndsAt"] < day
    ]


def release(state, person):
    # The recorded release date also determines when a pending-decision alert becomes due.
    released = offset_date(person["trialEndsAt"], 1)
    bed = next((b for b in state["beds"] if b["id"] == person.get("bedId")), None)
    move(state, person, released, "试住期满", old_bed=bed)
    person.update(status=PENDING, trialReleasedOn=released)


def maintain(store):
    if store._trials_checked == store.now().date().isoformat():
        return
    with store._daily_maintenance_lock:
        now = store.now()
        day = now.date().isoformat()
        if store._trials_checked != day:
            _maintain(store, now, day)
            store._trials_checked = day


def _maintain(store, now, day):
    from .. import activity, history
    from ..store import encode

    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        revision, raw = db.execute(
            "SELECT revision,data FROM workspace WHERE id=1"
        ).fetchone()
        state = json.loads(raw)
        for person in due(state, day):
            history.watch(db, "trial.expire")
            old = activity.for_person(state, person["id"])
            release(state, person)
            revision += 1
            db.execute(
                "UPDATE workspace SET revision=?,data=? WHERE id=1",
                (revision, encode(state)),
            )
            activity.write(
                db,
                revision,
                now.isoformat(timespec="seconds"),
                "trial.expire",
                "试住期已满，释放床位并提醒确认入住结果",
                SERVICE,
                {"residentId": person["id"]},
                old,
            )
