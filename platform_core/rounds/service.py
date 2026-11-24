"""Authenticated read and write endpoints, plus worker lifecycle."""

from contextlib import closing
from datetime import timedelta
import json
import logging
import re
from threading import Event, Thread

from .. import access, campus_access, history
from .inputs import check_fields, observe, update_settings
from .records import (
    active,
    audit,
    card,
    inbox_query,
    locate,
    make_report,
    report_source,
    interpret,
    mode,
    policy,
    staff,
    workspace,
)
from . import scheduler

LOG = logging.getLogger(__name__)
ID = r"[A-Za-z0-9_-]{1,100}"


class RoundService:
    def __init__(self, store):
        self.store = store
        self.halt = Event()
        self.thread = None

    @staticmethod
    def matches(path, write):
        if path == "/api/rounds/settings":
            return True
        if not write and path == "/api/rounds/inbox":
            return True
        suffix = r"/(mode|generate|observations)" if write else r"(/observations)?"
        return bool(re.fullmatch(r"/api/rounds/residents/" + ID + suffix, path))

    def read(self, token, path):
        with closing(self.store.connect()) as db, db:
            db.execute("BEGIN")
            user = self.store.actor(db, token)
            staff(user)
            revision, state = workspace(db)
            if path == "/api/rounds/settings":
                if user["kind"] != "owner":
                    raise PermissionError("仅总管理员可查看机构巡查设置")
                return {"revision": revision, "settings": policy(db)}
            if path == "/api/rounds/inbox":
                beds = campus_access.allowed_beds(db, user, include_rooms=True)
                clinical = access.has(user, "clinical")
                rows = inbox_query(db, state, beds, clinical).fetchall()
                items = [
                    {
                        "id": row["report"],
                        "reportId": row["report"],
                        "residentId": row["resident"],
                        "residentName": row["resident_name"],
                        "day": row["day"],
                        "deliveredAt": row["delivered_at"],
                        "today": json.loads(row["today"]),
                        "signals": [
                            signal
                            for signal in json.loads(row["signals"])
                            if clinical or signal in ("pending", "carry")
                        ],
                    }
                    for row in rows
                ]
                return {
                    "revision": revision,
                    "items": items,
                    "total": rows[0]["total"] if rows else 0,
                }
            if path.endswith("/observations"):
                person = locate(db, state, user, path.split("/")[-2])
                access.require(user, "clinical")
                today = self.store.now().date()
                since = max(person["_fromDay"], (today - timedelta(days=7)).isoformat())
                rows = db.execute(
                    """SELECT day,hour,events AS count,minutes AS observedMinutes,source,attribution,
                              reviewer AS reviewedBy,reviewed_at AS reviewedAt FROM rounds_observations
                       WHERE resident=? AND bed=? AND day BETWEEN ? AND ? ORDER BY day DESC,hour DESC""",
                    (person["id"], person.get("bedId", ""), since, today.isoformat()),
                )
                return {
                    "revision": revision,
                    "since": since,
                    "through": today.isoformat(),
                    "rows": [dict(r) for r in rows],
                }
            person = locate(db, state, user, path.rsplit("/", 1)[-1])
            return {"revision": revision, **card(db, person, user)}

    def write(self, token, path, body):
        from ..store import Conflict

        now = self.store.now()
        prepared = None
        if path.endswith("/generate"):
            if not isinstance(body, dict) or type(body.get("revision")) is not int:
                raise ValueError("请提供当前版本")
            check_fields(body, ())
            with closing(self.store.connect()) as db, db:
                db.execute("BEGIN")
                user = self.store.actor(db, token)
                revision, state = workspace(db)
                person = locate(db, state, user, path.split("/")[-2])
                if not active(person):
                    raise ValueError("仅可为有床位的在住长者执行巡查")
                clinical = access.has(user, "clinical")
                data, digest, unchanged = report_source(
                    db, state, person, now, clinical=clinical
                )
                if not unchanged and revision != body["revision"]:
                    raise Conflict("数据已更新，请刷新后重试")
            if not unchanged:
                prepared = (
                    digest,
                    interpret(self.store, data, digest, clinical=clinical),
                )
        with closing(self.store.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            user = self.store.actor(db, token)
            staff(user)
            if not isinstance(body, dict) or type(body.get("revision")) is not int:
                raise ValueError("请提供当前版本")
            comment = history.comment_text(body.get("comment", ""))
            revision, state = workspace(db)
            action = path.rsplit("/", 1)[-1]
            if action == "settings":
                if user["kind"] != "owner":
                    raise PermissionError("仅总管理员可修改机构巡查设置")
                person = None
                history.watch(db, "rounds.settings")
                changed = update_settings(db, body, now)
                summary = "调整机构任务巡查和推送设置"
            else:
                person = locate(db, state, user, path.split("/")[-2])
                if not active(person):
                    raise ValueError("仅可为有床位的在住长者执行巡查")
                if action == "generate":
                    check_fields(body, ())
                    changed = make_report(
                        db,
                        state,
                        person,
                        now,
                        user,
                        prepared,
                        comment,
                        clinical=access.has(user, "clinical"),
                    )
                elif action == "mode":
                    access.require(user, "care")
                    check_fields(body, ("mode",))
                    selected = body.get("mode")
                    if selected not in ("manual", "auto", "inherit"):
                        raise ValueError("请选择生成方式")
                    changed = mode(db, person["id"]) != selected
                    if changed:
                        history.watch(db, "rounds.mode")
                        db.execute(
                            """INSERT INTO rounds_modes VALUES(?,?) ON CONFLICT(resident)
                                      DO UPDATE SET mode=excluded.mode""",
                            (person["id"], selected),
                        )
                    summary = "调整长者巡查生成方式"
                elif action == "observations":
                    access.require(user, "clinical")
                    history.watch(db, "rounds.observations")
                    changed = observe(db, person, user, body, now)
                    summary = "核对并登记个人咳嗽时段观测"
                else:
                    raise FileNotFoundError("巡查接口不存在")
            if changed and revision != body["revision"]:
                raise Conflict("数据已更新，请刷新后重试")
            if changed:
                revision += 1
                if action != "generate":
                    audit(
                        db,
                        now,
                        "rounds." + action,
                        summary,
                        user,
                        state,
                        person["id"] if person else "",
                        comment,
                    )
            response = card(db, person, user) if person else {"settings": policy(db)}
            return {"revision": revision, "changed": changed, **response}

    def tick(self):
        from ..care import archive_retention

        archive_retention.maintain(self.store)
        return scheduler.tick(self.store, self.halt)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.halt.clear()

        def worker():
            while not self.halt.is_set():
                try:
                    self.tick()
                    from ..agents import change_review

                    change_review.process_pending(self.store, self.halt)
                except Exception:
                    LOG.exception("定时巡查未完成，将在下一次检查时重试")
                self.halt.wait(60)

        self.thread = Thread(name="resident-rounds", target=worker, daemon=True)
        self.thread.start()

    def stop(self):
        self.halt.set()
        if self.thread:
            self.thread.join()
