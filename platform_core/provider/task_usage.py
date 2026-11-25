"""Join current and historical task receipts without copying patient data."""

from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
import json
import re


_current = ContextVar("agent_usage_scope", default=None)
TASK_ID = re.compile(r"[a-z][a-z0-9-]{0,24}-[0-9a-f]{24}")


def identifier(kind, *parts):
    """Use the same business identity on retry, without exposing IDs or filenames."""
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,24}", kind):
        raise ValueError("任务类别无效")
    key = json.dumps(parts, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return kind + "-" + sha256(key.encode()).hexdigest()[:24]


@contextmanager
def scope(runtime, task_id):
    """The caller supplies the business task across a handoff, never a browser grant."""
    if runtime not in ("deerflow", "platform") or not TASK_ID.fullmatch(task_id):
        raise ValueError("任务归属无效")
    marker = _current.set((runtime, task_id))
    try:
        yield task_id
    finally:
        _current.reset(marker)


def current_task_id():
    """Keep child model receipts on the employee’s original business task."""
    current = _current.get()
    return current[1] if current else None


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS agent_task_usage(
        meter TEXT NOT NULL, actor TEXT NOT NULL, receipt TEXT NOT NULL,
        runtime TEXT NOT NULL, taskId TEXT NOT NULL,
        PRIMARY KEY(meter,actor,receipt)) WITHOUT ROWID""")
    db.execute("CREATE INDEX IF NOT EXISTS agent_task_usage_by_task ON agent_task_usage(taskId)")


def attach(db, meter, actor, receipt):
    """Called in the same transaction as the original reservation, including failures."""
    current = _current.get()
    if current is not None:
        db.execute("""INSERT INTO agent_task_usage(meter,actor,receipt,runtime,taskId)
                      VALUES(?,?,?,?,?) ON CONFLICT(meter,actor,receipt) DO NOTHING""",
                   (meter, actor, receipt, *current))


def for_receipt(db, meter, actor, receipt):
    row = db.execute("SELECT taskId FROM agent_task_usage WHERE meter=? AND actor=? AND receipt=?",
                     (meter, actor, receipt)).fetchone()
    return row[0] if row else None


def link_chat_voice(db, actor, receipt):
    """The media reservation or the validated ASR receipt supplies the identity."""
    task = identifier("voice", actor, receipt)
    with scope("platform", task):
        attach(db, "media", actor, receipt)
    return task
