"""Reconcile a late supplier receipt without rewriting the original operator settlement."""


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS api_late_usage (
        actor TEXT NOT NULL, request TEXT NOT NULL, original INTEGER NOT NULL, reported INTEGER NOT NULL,
        receivedAt INTEGER NOT NULL, verified INTEGER, verifiedAt INTEGER, PRIMARY KEY(actor,request),
        FOREIGN KEY(actor,request) REFERENCES api_usage(actor,request))""")
    db.execute(
        "CREATE INDEX IF NOT EXISTS late_usage_pending ON api_late_usage(receivedAt) WHERE verified IS NULL"
    )


def late_usage(db, actor, request, tokens, now, *, confirmed_zero=False):
    """Persist the supplier total only after a manual settlement won the write race."""
    if type(tokens) is not int or tokens < 0 or tokens == 0 and not confirmed_zero:
        return
    db.execute(
        """INSERT INTO api_late_usage(actor,request,original,reported,receivedAt)
        SELECT actor,request,charged,?,? FROM api_usage
        WHERE actor=? AND request=? AND status='closed' AND reason='reconciled'
        AND charged<>? AND allowance>=?
        ON CONFLICT(actor,request) DO NOTHING""",
        (tokens, int(now.timestamp()), actor, request, tokens, tokens),
    )


def unsettled(db):
    return [
        dict(row)
        for row in db.execute("""SELECT u.planId,u.actor,u.request,u.model,
        CASE WHEN l.actor IS NOT NULL THEN 'late_receipt' ELSE u.status END AS status,
        u.allowance, u.createdAt,u.charged AS originalTokens,l.reported AS reportedTokens,
        l.receivedAt, l.reported-l.original AS differenceTokens
        FROM api_usage u LEFT JOIN api_late_usage l ON l.actor=u.actor AND l.request=u.request
        WHERE u.status IN ('pending','uncertain') OR (l.actor IS NOT NULL AND l.verified IS NULL)
        ORDER BY COALESCE(l.receivedAt,u.createdAt),u.actor,u.request""")
    ]
