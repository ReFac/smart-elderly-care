"""Count the provider's standalone web searches separately from model tokens."""

from datetime import timedelta


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS api_search_usage (
        actor TEXT NOT NULL, request TEXT NOT NULL, planId INTEGER NOT NULL REFERENCES api_plans(id),
        createdAt INTEGER NOT NULL, receivedAt INTEGER,
        status TEXT NOT NULL CHECK(status IN ('pending','ok','empty','closed','uncertain')),
        verified INTEGER CHECK(verified IN (0,1)), verifiedAt INTEGER,
        needsReview INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(actor,request))""")
    db.execute(
        "CREATE INDEX IF NOT EXISTS search_usage_by_time ON api_search_usage(createdAt)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS search_plan ON api_search_usage(planId,status)"
    )


def reserve(db, actor, request, plan_id, now):
    created = db.execute(
        "INSERT INTO api_search_usage(actor,request,planId,createdAt,status) VALUES(?,?,?,?,'pending') "
        "ON CONFLICT(actor,request) DO NOTHING",
        (actor, request, plan_id, int(now.timestamp())),
    )
    if not created.rowcount:
        raise ValueError("这次联网搜索已经登记，请查看原回复")


def settle(db, actor, request, status, now):
    if status not in ("ok", "empty", "closed", "uncertain"):
        raise ValueError("搜索回执状态无效")
    db.execute(
        """UPDATE api_search_usage SET status=?,receivedAt=?,needsReview=
        CASE WHEN ?!='uncertain' AND verified IS NOT NULL AND verified!=(?='ok')
             THEN 1 ELSE needsReview END
        WHERE actor=? AND request=? AND status IN ('pending','uncertain')""",
        (status, int(now.timestamp()), status, status, actor, request),
    )


def overview(db, plan_id):
    calls, waiting = db.execute(
        """SELECT COALESCE(sum(COALESCE(verified,status='ok')),0),
        COALESCE(sum((verified IS NULL AND status IN ('pending','uncertain')) OR needsReview),0)
        FROM api_search_usage WHERE planId=?""",
        (plan_id,),
    ).fetchone()
    return {"calls": calls, "pending": waiting}


def unsettled(db):
    return [
        dict(row)
        for row in db.execute("""SELECT planId, actor, request, status, createdAt,
            receivedAt, verified, needsReview FROM api_search_usage
            WHERE (verified IS NULL AND status IN ('pending','uncertain')) OR needsReview
            ORDER BY createdAt""")
    ]


def reconcile(db, actor, request, calls, now):
    row = db.execute(
        "SELECT * FROM api_search_usage WHERE actor=? AND request=?", (actor, request)
    ).fetchone()
    if not row or type(calls) is not int or calls not in (0, 1):
        raise ValueError("请核对搜索请求编号和实际计费次数（0 或 1）")
    if not row["needsReview"]:
        if row["verified"] == calls:
            return
        if row["verified"] is not None or row["status"] not in ("pending", "uncertain"):
            raise ValueError("此笔搜索已有明确回执")
        if (
            row["status"] == "pending"
            and row["createdAt"] > (now - timedelta(minutes=3)).timestamp()
        ):
            raise ValueError("搜索仍在进行中，请稍后核对")
    db.execute(
        "UPDATE api_search_usage SET verified=?,verifiedAt=?,needsReview=0 WHERE actor=? AND request=?",
        (calls, int(now.timestamp()), actor, request),
    )
