"""Encrypted database tables for the rounding scheduler, evidence and daily inbox."""

from datetime import timedelta


def init(db, now):
    db.execute("""CREATE TABLE IF NOT EXISTS rounds_policy (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), enabled INTEGER NOT NULL,
        interval_min INTEGER NOT NULL, default_mode TEXT NOT NULL, notify_at TEXT NOT NULL,
        next_at TEXT NOT NULL, last_at TEXT)""")
    db.execute(
        "INSERT OR IGNORE INTO rounds_policy VALUES (1,1,60,'auto','17:30',?,NULL)",
        ((now + timedelta(hours=1)).isoformat(),),
    )
    # Existing daily schedules retain their cadence. Sending additional clinical chart
    # excerpts to the model requires the Owner to enable the new specialist explicitly.
    db.execute("""CREATE TABLE IF NOT EXISTS rounds_health_policy(
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), enabled INTEGER NOT NULL,
        interval_min INTEGER NOT NULL, next_at TEXT NOT NULL, last_at TEXT)""")
    db.execute("INSERT OR IGNORE INTO rounds_health_policy VALUES(1,0,1440,?,NULL)", (now.isoformat(),))
    db.execute("""CREATE TABLE IF NOT EXISTS rounds_agent_outcomes(
        agent TEXT PRIMARY KEY, result TEXT NOT NULL, at TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS rounds_health_jobs(
        resident TEXT PRIMARY KEY, day TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        due_at TEXT NOT NULL DEFAULT '', lease TEXT NOT NULL DEFAULT '')""")
    db.execute("CREATE INDEX IF NOT EXISTS rounds_health_due ON rounds_health_jobs(due_at,resident)")
    db.execute("""CREATE TABLE IF NOT EXISTS rounds_health_reviews(
        id TEXT PRIMARY KEY, resident TEXT NOT NULL, bed TEXT NOT NULL, stay TEXT NOT NULL, day TEXT NOT NULL,
        basis TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)""")
    db.execute("""CREATE INDEX IF NOT EXISTS rounds_health_by_person ON
        rounds_health_reviews(resident,bed,stay,day,created_at)""")
    db.execute("""CREATE TABLE IF NOT EXISTS rounds_modes (
        resident TEXT PRIMARY KEY, mode TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS rounds_observations (
        resident TEXT NOT NULL, bed TEXT NOT NULL, day TEXT NOT NULL, hour INTEGER NOT NULL,
        events INTEGER NOT NULL, minutes INTEGER NOT NULL, source TEXT NOT NULL,
        attribution TEXT NOT NULL, reviewer TEXT NOT NULL, reviewed_at TEXT NOT NULL,
        PRIMARY KEY(resident,day,hour))""")
    db.execute("""CREATE TABLE IF NOT EXISTS rounds_reports (
        id TEXT PRIMARY KEY, resident TEXT NOT NULL, bed TEXT NOT NULL, day TEXT NOT NULL,
        created_at TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL)""")
    db.execute(
        "CREATE INDEX IF NOT EXISTS rounds_by_resident ON rounds_reports(resident,bed,day,created_at)"
    )
    db.execute("""CREATE TABLE IF NOT EXISTS rounds_jobs (
        resident TEXT PRIMARY KEY, day TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        retry_at TEXT NOT NULL DEFAULT '')""")
    job_columns = {r[1] for r in db.execute("PRAGMA table_info(rounds_jobs)")}
    if "attempts" not in job_columns:
        db.execute(
            "ALTER TABLE rounds_jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0"
        )
    if "retry_at" not in job_columns:
        db.execute(
            "ALTER TABLE rounds_jobs ADD COLUMN retry_at TEXT NOT NULL DEFAULT ''"
        )
    db.execute("""CREATE TABLE IF NOT EXISTS rounds_staff_inbox (
        resident TEXT NOT NULL, day TEXT NOT NULL, report TEXT NOT NULL,
        delivered_at TEXT NOT NULL, signals TEXT NOT NULL DEFAULT '[]', PRIMARY KEY(resident,day))""")
    if "signals" not in {
        r[1] for r in db.execute("PRAGMA table_info(rounds_staff_inbox)")
    }:
        # Rebuild unspecialized draft alerts when their next eligible report is dispatched.
        db.execute(
            "ALTER TABLE rounds_staff_inbox ADD COLUMN signals TEXT NOT NULL DEFAULT '[]'"
        )
        db.execute("DELETE FROM rounds_staff_inbox WHERE signals='[]'")
    db.execute("""CREATE TABLE IF NOT EXISTS rounds_delivery_sweep(
           singleton INTEGER PRIMARY KEY CHECK(singleton=1),day TEXT NOT NULL,notify_at TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS rounds_dispatch(
           resident TEXT NOT NULL,day TEXT NOT NULL,report TEXT NOT NULL,checked INTEGER NOT NULL DEFAULT 0,
           PRIMARY KEY(resident,day))""")
    db.execute(
        "CREATE INDEX IF NOT EXISTS rounds_dispatch_due ON rounds_dispatch(day,checked)"
    )
    db.execute("""CREATE TRIGGER IF NOT EXISTS rounds_publish AFTER INSERT ON rounds_reports
            BEGIN INSERT INTO rounds_dispatch(resident,day,report) VALUES(NEW.resident,NEW.day,NEW.id)
                ON CONFLICT(resident,day) DO UPDATE SET report=excluded.report,checked=0; END""")
    db.execute(
        """INSERT OR IGNORE INTO rounds_dispatch(resident,day,report)
        SELECT resident,day,id FROM (SELECT resident,day,id,
            ROW_NUMBER() OVER (PARTITION BY resident ORDER BY created_at DESC,rowid DESC) AS position
            FROM rounds_reports WHERE day=?) WHERE position=1""",
        (now.date().isoformat(),),
    )
