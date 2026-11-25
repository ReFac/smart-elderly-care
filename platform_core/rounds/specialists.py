"""Scheduling controls and authorized, read-only projections for the two resident specialists."""

import json

from .. import access
from .inputs import check_fields, update_settings
from .records import latest, policy, visible_report


DAILY = "daily-life"
HEALTH = "health-review"
NAMES = {DAILY: "日常起居助理", HEALTH: "健康复核助理"}
UNLOADED = object()


def outcome(db, agent, text, now):
    db.execute(
        """INSERT INTO rounds_agent_outcomes VALUES(?,?,?) ON CONFLICT(agent)
        DO UPDATE SET result=excluded.result,at=excluded.at""",
        (agent, text, now.isoformat()),
    )


def schedules(db):
    daily = policy(db)
    health = db.execute(
        "SELECT * FROM rounds_health_policy WHERE singleton=1"
    ).fetchone()
    outcomes = dict(db.execute("SELECT agent,result FROM rounds_agent_outcomes"))
    result = []
    for agent, enabled, interval, last, next_at, jobs in (
        (
            DAILY,
            daily["enabled"],
            daily["intervalMinutes"],
            daily["lastRunAt"],
            daily["nextRunAt"],
            "rounds_jobs",
        ),
        (
            HEALTH,
            bool(health["enabled"]),
            health["interval_min"],
            health["last_at"],
            health["next_at"],
            "rounds_health_jobs",
        ),
    ):
        queued, retrying = db.execute(
            f"SELECT COUNT(*),COUNT(CASE WHEN attempts>0 THEN 1 END) FROM {jobs}"
        ).fetchone()
        result.append(
            dict(
                id=agent,
                name=NAMES[agent],
                enabled=enabled,
                intervalMinutes=interval,
                lastRunAt=last,
                nextRunAt=next_at if enabled else None,
                pending=queued,
                retrying=retrying,
                lastResult=outcomes.get(agent),
            )
        )
    return result


def configure(db, body, now):
    check_fields(body, ("agentId", "enabled", "intervalMinutes"))
    agent, enabled, interval = (
        body.get(k) for k in ("agentId", "enabled", "intervalMinutes")
    )
    if (
        agent not in (DAILY, HEALTH)
        or type(enabled) is not bool
        or type(interval) is not int
        or not 5 <= interval <= 1440
    ):
        raise ValueError("请选择任务并设置 5 至 1440 分钟的检查周期")
    if agent == DAILY:
        original = policy(db)
        return update_settings(
            db,
            {
                "enabled": enabled,
                "intervalMinutes": interval,
                "defaultMode": original["defaultMode"],
                "notifyAt": original["notifyAt"],
            },
            now,
        )
    previous = db.execute(
        "SELECT enabled,interval_min FROM rounds_health_policy WHERE singleton=1"
    ).fetchone()
    if tuple(previous) == (enabled, interval):
        return False
    db.execute(
        "UPDATE rounds_health_policy SET enabled=?,interval_min=?,next_at=? WHERE singleton=1",
        (enabled, interval, now.isoformat()),
    )
    if not enabled:
        db.execute("DELETE FROM rounds_health_jobs")
    return True


def drafts(db, person, user, daily=UNLOADED):
    """Read drafts after records.locate checked this actor's access to the current stay."""
    if daily is UNLOADED:
        daily = visible_report(latest(db, person), user)
    daily_draft = None
    if daily and daily.get("format") == "daily-life-v2":
        daily_draft = {
            k: daily.get(k)
            for k in (
                "id",
                "day",
                "generatedAt",
                "source",
                "model",
                "residentId",
                "taskId",
                "draftRuntime",
            )
        }
        # A daily brief is only the resident's confirmed care observations. Legacy reports
        # can also contain clinical and yesterday's paragraphs; their dates remain explicit.
        items = [
            dict(text=row["text"], day=row["day"], evidence=row["evidence"])
            for row in daily.get("changes", ())
            if row["permission"] == "care"
        ]
        daily_draft.update(agentId=DAILY, status="draft", items=items)
    result = {DAILY: daily_draft}
    if access.has(user, "medical") and access.has(user, "clinical"):
        row = db.execute(
            """SELECT payload FROM rounds_health_reviews WHERE resident=? AND bed=? AND stay=?
            ORDER BY day DESC,created_at DESC,rowid DESC LIMIT 1""",
            (person["id"], person["bedId"], person["_stayId"]),
        ).fetchone()
        result[HEALTH] = json.loads(row[0]) if row else None
    return result
