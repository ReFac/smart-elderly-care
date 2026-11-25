"""Resolve due work, persist each resident independently and deliver current-day summaries."""

from contextlib import closing
from datetime import datetime, timedelta
import logging
import json

from .report import attention

from .. import history, rounds_family
from .records import (
    active,
    audit,
    current_stay,
    latest,
    make_report,
    report_source,
    interpret,
    mode,
    policy,
    workspace,
)

AGENT = {
    "id": "rounds-agent",
    "displayName": "健康助理定时巡查",
    "username": "rounds-agent",
}
LOG = logging.getLogger(__name__)


def tick(store, halt):
    """Queue the current sweep durably and checkpoint one resident per transaction."""
    now = store.now()
    day = now.date().isoformat()
    completed = delivered = 0
    with closing(store.connect()) as db:
        version, state_cache = None, None

        def business_state():
            # On this connection only the revision counter changes. A separate writer
            # can update the business JSON between residents, including a discharge.
            nonlocal version, state_cache
            fresh = db.execute("PRAGMA data_version").fetchone()[0]
            if fresh != version:
                _, state_cache = workspace(db)
                version = fresh
            return state_cache

        with db:
            db.execute("BEGIN IMMEDIATE")
            settings = policy(db)
            normal_due = settings["enabled"] and now >= datetime.fromisoformat(
                settings["nextRunAt"]
            )
            delivery_due = (
                settings["enabled"]
                and now.strftime("%H:%M") >= settings["notifyAt"]
                and not db.execute(
                    "SELECT 1 FROM rounds_delivery_sweep WHERE singleton=1 AND day=? AND notify_at=?",
                    (day, settings["notifyAt"]),
                ).fetchone()
            )
            if normal_due or delivery_due:
                state = business_state()
                overrides = dict(db.execute("SELECT resident,mode FROM rounds_modes"))
                residents = []
                for person in state["residents"]:
                    selected = overrides.get(person["id"], "inherit")
                    selected = (
                        settings["defaultMode"] if selected == "inherit" else selected
                    )
                    if active(person) and selected == "auto":
                        residents.append((person["id"], day))
                db.executemany(
                    """INSERT INTO rounds_jobs(resident,day) VALUES(?,?) ON CONFLICT(resident)
                                  DO UPDATE SET day=excluded.day,attempts=0,retry_at='' WHERE day<>excluded.day""",
                    residents,
                )
                if delivery_due:
                    db.execute(
                        "INSERT OR REPLACE INTO rounds_delivery_sweep VALUES(1,?,?)",
                        (day, settings["notifyAt"]),
                    )
                next_run = (
                    (now + timedelta(minutes=settings["intervalMinutes"])).isoformat()
                    if normal_due
                    else settings["nextRunAt"]
                )
                db.execute(
                    "UPDATE rounds_policy SET last_at=?,next_at=? WHERE singleton=1",
                    (now.isoformat(), next_run),
                )
        while not halt.is_set():
            with db:
                now = store.now()
                db.execute("BEGIN IMMEDIATE")
                job = db.execute(
                    "SELECT resident,day,attempts FROM rounds_jobs WHERE retry_at<=? ORDER BY resident LIMIT 1",
                    (now.isoformat(),),
                ).fetchone()
                if not job:
                    break
                lease = (now + timedelta(minutes=5)).isoformat()
                db.execute(
                    "UPDATE rounds_jobs SET retry_at=? WHERE resident=? AND day=?",
                    (lease, job[0], job[1]),
                )

            def inputs():
                state = business_state()
                person = next(
                    (r for r in state["residents"] if r["id"] == job[0]), None
                )
                settings = policy(db)
                selected = mode(db, job[0])
                enabled = selected == "auto" or (
                    selected == "inherit" and settings["defaultMode"] == "auto"
                )
                if (
                    settings["enabled"]
                    and enabled
                    and job[1] == store.now().date().isoformat()
                    and person
                    and active(person)
                ):
                    return state, current_stay(state, person)
                return state, None

            try:
                prepared = None
                with db:
                    db.execute("BEGIN")
                    state, person = inputs()
                    if person:
                        data, digest, unchanged = report_source(
                            db, state, person, now, clinical=True
                        )
                if person and not unchanged:
                    prepared = (digest, interpret(store, data, clinical=True))
                with db:
                    db.execute("BEGIN IMMEDIATE")
                    owned = db.execute(
                        "SELECT 1 FROM rounds_jobs WHERE resident=? AND day=? AND retry_at=?",
                        (job[0], job[1], lease),
                    ).fetchone()
                    if not owned:
                        continue
                    state, person = inputs()
                    if person:
                        completed += make_report(
                            db, state, person, now, AGENT, prepared, clinical=True
                        )
                    db.execute(
                        "DELETE FROM rounds_jobs WHERE resident=? AND day=? AND retry_at=?",
                        (job[0], job[1], lease),
                    )
            except Exception:
                wait = timedelta(minutes=min(60, 2 ** min(job[2], 6)))
                with db:
                    db.execute(
                        "UPDATE rounds_jobs SET attempts=attempts+1,retry_at=? WHERE resident=? AND day=? AND retry_at=?",
                        ((now + wait).isoformat(), job[0], job[1], lease),
                    )
                LOG.error("一项长辈巡查生成失败，将按退避间隔重试")
        if not halt.is_set():
            delivered = deliver_due(db, store.now, halt, business_state)
    return {"generated": completed, "delivered": delivered}


def deliver_due(db, clock, halt, business_state):
    now = clock()
    day = now.date().isoformat()
    settings = policy(db)
    if not settings["enabled"] or now.strftime("%H:%M") < settings["notifyAt"]:
        return 0
    # Most heartbeats find no new reports. New family consent can make an already-checked day eligible.
    ids = [
        row[0]
        for row in db.execute(
            """SELECT d.resident FROM rounds_dispatch d WHERE d.day=? AND d.checked=0
           AND NOT EXISTS(SELECT 1 FROM rounds_jobs j WHERE j.resident=d.resident AND j.day=d.day)
           UNION SELECT p.resident_id FROM family_round_preferences p
           JOIN accounts a ON a.id=p.account_id AND a.resident_id=p.resident_id
           JOIN rounds_dispatch d ON d.day=? AND d.resident=p.resident_id AND d.checked=1
           WHERE p.allowed=1 AND p.subscribed=1 AND a.enabled=1 AND a.kind='family' AND a.role='亲属'
           AND NOT EXISTS (SELECT 1 FROM rounds_jobs j WHERE j.resident=d.resident AND j.day=d.day)
           AND NOT EXISTS (SELECT 1 FROM family_round_messages m WHERE m.resident_id=p.resident_id
                           AND m.account_id=p.account_id AND m.day=d.day)""",
            (day, day),
        )
    ]
    delivered = 0
    for rid in ids:
        if halt.is_set():
            break
        with db:
            db.execute("BEGIN IMMEDIATE")
            now = clock()
            settings = policy(db)
            if (
                now.date().isoformat() != day
                or not settings["enabled"]
                or now.strftime("%H:%M") < settings["notifyAt"]
            ):
                break
            state = business_state()
            person = next((r for r in state["residents"] if r["id"] == rid), None)
            report = (
                latest(db, current_stay(state, person), day)
                if person and active(person)
                else None
            )
            db.execute(
                "UPDATE rounds_dispatch SET checked=? WHERE resident=? AND day=?",
                (1 if report else 2, rid, day),
            )
            if not report:
                continue
            old = db.execute(
                "SELECT report,signals FROM rounds_staff_inbox WHERE resident=? AND day=?",
                (rid, day),
            ).fetchone()
            signals = attention(report)
            history.watch(db, "rounds.deliver")
            family = rounds_family.deliver(db, state, report, now)
            changed = False
            if signals and (
                not old or old[0] != report["id"] or json.loads(old[1]) != signals
            ):
                db.execute(
                    """INSERT INTO rounds_staff_inbox(resident,day,report,delivered_at,signals)
                              VALUES(?,?,?,?,?) ON CONFLICT(resident,day)
                              DO UPDATE SET report=excluded.report,signals=excluded.signals""",
                    (rid, day, report["id"], now.isoformat(), json.dumps(signals)),
                )
                changed = True
            elif not signals and old:
                db.execute(
                    "DELETE FROM rounds_staff_inbox WHERE resident=? AND day=?",
                    (rid, day),
                )
                changed = True
            if changed or family:
                audit(
                    db,
                    now,
                    "rounds.deliver",
                    "更新当日巡查站内提醒",
                    AGENT,
                    state,
                    rid,
                )
            delivered += int(bool(signals) and not old) + family
    return delivered
