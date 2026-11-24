"""DeepSeek Chat Completions usage, independent of the response's business validity."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenReceipt:
    total: int
    input: int | None = None
    cached: int | None = None
    uncached: int | None = None
    output: int | None = None


def init(db):
    existing = {r[1] for r in db.execute("PRAGMA table_info(api_usage)")}
    columns = {
        "feature": "TEXT",
        "attributedActor": "TEXT",
        "providerTokens": "INTEGER",
        "inputTokens": "INTEGER",
        "cachedInputTokens": "INTEGER",
        "uncachedInputTokens": "INTEGER",
        "outputTokens": "INTEGER",
    }
    for name, sql_type in columns.items():
        if name not in existing:
            db.execute(f"ALTER TABLE api_usage ADD COLUMN {name} {sql_type}")
    db.execute("CREATE INDEX IF NOT EXISTS api_usage_by_time ON api_usage(createdAt)")


def read(response, limit):
    fields = response.get("usage") if isinstance(response, dict) else None
    if not isinstance(fields, dict):
        return None
    total = fields.get("total_tokens")
    if type(total) is not int or not 0 < total <= limit:
        return None

    def count(value):
        return value if type(value) is int and 0 <= value <= total else None

    prompt = count(fields.get("prompt_tokens"))
    output = count(fields.get("completion_tokens"))
    if prompt is not None and output is not None and prompt + output != total:
        return TokenReceipt(total)

    cached = count(fields.get("prompt_cache_hit_tokens"))
    uncached = count(fields.get("prompt_cache_miss_tokens"))
    details = fields.get("prompt_tokens_details")
    alternative = (
        count(details.get("cached_tokens")) if isinstance(details, dict) else None
    )
    if "prompt_cache_hit_tokens" not in fields:
        cached = alternative
    input_limit = prompt if prompt is not None else total - (output or 0)
    split_total = (cached or 0) + (uncached or 0)
    if (
        (cached is not None and alternative is not None and cached != alternative)
        or split_total > input_limit
        or (
            cached is not None
            and uncached is not None
            and (prompt is not None or output is not None)
            and split_total != input_limit
        )
    ):
        cached = uncached = None
    return TokenReceipt(total, prompt, cached, uncached, output)


def keep(db, actor, request, receipt):
    """Attach the original breakdown to the same immutable provider request identity."""
    if receipt is None:
        return
    db.execute(
        """UPDATE api_usage SET providerTokens=?,inputTokens=?,cachedInputTokens=?,
           uncachedInputTokens=?,outputTokens=? WHERE actor=? AND request=? AND providerTokens IS NULL""",
        (
            receipt.total,
            receipt.input,
            receipt.cached,
            receipt.uncached,
            receipt.output,
            actor,
            request,
        ),
    )
