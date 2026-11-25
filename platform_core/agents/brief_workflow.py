"""Durable specialist checkpoints and bounded review of generated brief text."""

from contextlib import closing
from hashlib import sha256
import json
import re

from . import region, specialists
from .. import access_policy
from ..provider import completions, generation, model_name

NUMBERS = re.compile(r"(?<![A-Za-z0-9])[-+]?\d+(?:,\d{3})*(?:\.\d+)?")
CLAIMED_ACTION = re.compile(
    r"已(?:经)?(?:为.{0,8})?(?:发布|扣款|开药|下发|派发|完成转账|修改档案|执行医嘱)|"
    r"\b(?:I|we) (?:have |already )?(?:published|charged|prescribed|dispatched|transferred|updated the record)\b", re.I
)
NUMBER_WITH_UNIT = re.compile(
    r"([+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*(万元|元|人次|人|笔|件|条|项|次|%)"
)


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS agent_work_progress (
        actor TEXT NOT NULL, request TEXT NOT NULL, revision INTEGER NOT NULL, fingerprint TEXT NOT NULL,
        plan TEXT NOT NULL, region TEXT NOT NULL, done TEXT NOT NULL, created INTEGER NOT NULL,
        PRIMARY KEY(actor,request))""")


def check_source(store, db, token, revision, plan, scope):
    from ..store import Conflict

    user = store.actor(db, token)
    if (
        db.execute("SELECT revision FROM workspace WHERE id=1").fetchone()[0]
        != revision
    ):
        raise Conflict("简报来源数据已更新，请核对最新内容后重新生成")
    if not set(plan) <= {s.key for s in specialists(user)} or not region.visible(
        db, user, scope
    ):
        raise PermissionError("简报授权已变化，请重新核对")
    return user["id"]


def checkpoint(store, token, check, revision, artifacts, accepted=None):
    plan = [artifact["agent"] for artifact in artifacts]
    args = check["args"]
    scope = check["resolved"]
    fingerprint = sha256(
        json.dumps(
            [args, scope, artifacts],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        actor = check_source(store, db, token, revision, plan, scope)
        key = actor, check["request"]
        row = db.execute(
            "SELECT revision,fingerprint,done FROM agent_work_progress WHERE actor=? AND request=?",
            key,
        ).fetchone()
        if row is None:
            # Only partial runs use this table. Completed runs are part of the audited ledger.
            now = int(store.now().timestamp())
            db.execute(
                "DELETE FROM agent_work_progress WHERE created < ?", (now - 60 * 86400,)
            )
            db.execute(
                "INSERT INTO agent_work_progress VALUES(?,?,?,?,?,?,?,?)",
                (
                    *key,
                    revision,
                    fingerprint,
                    json.dumps(plan),
                    json.dumps(scope),
                    "{}",
                    now,
                ),
            )
            done = {}
        else:
            if row[0] != revision or row[1] != fingerprint:
                raise ValueError("原简报的资料或任务内容已变化，请以新请求开始")
            done = json.loads(row[2])
        if accepted:
            name, result = accepted
            if name not in plan:
                raise ValueError("简报返回了计划外的步骤")
            done.setdefault(name, result)
            db.execute(
                "UPDATE agent_work_progress SET done=? WHERE actor=? AND request=?",
                (json.dumps(done, ensure_ascii=False), *key),
            )
        return done


def progress(store, token, request):
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        user = store.actor(db, token)
        access_policy.require(user, "assistants")
        if not isinstance(request, str) or not 1 <= len(request) <= 100:
            raise ValueError("请提供简报请求标识")
        row = db.execute(
            "SELECT * FROM agent_work_progress WHERE actor=? AND request=?",
            (user["id"], request),
        ).fetchone()
        if not row:
            from . import get_row

            finished = db.execute(
                "SELECT id FROM agent_runs WHERE actor=? AND request=?",
                (user["id"], request),
            ).fetchone()
            if not finished:
                raise FileNotFoundError("未找到此简报进度")
            run = get_row(db, user, finished[0])
            return {
                "status": run["status"],
                "runId": run["id"],
                "revision": run["revision"],
            }
        plan = json.loads(row["plan"])
        if not set(plan) <= {s.key for s in specialists(user)} or not region.visible(
            db, user, json.loads(row["region"])
        ):
            raise FileNotFoundError("未找到此简报进度")
        done = json.loads(row["done"])
        current = db.execute("SELECT revision FROM workspace WHERE id=1").fetchone()[0]
        return {
            "status": "in_progress" if current == row["revision"] else "stale",
            "revision": row["revision"],
            "plan": plan,
            "completed": [name for name in plan if name in done],
        }


def issues(text, facts):
    if not isinstance(text, str) or not text.strip():
        return ["empty"]
    problems = []
    if CLAIMED_ACTION.search(text):
        problems.append("action_claim")
    # Counts can be described as records. Unit-bearing amounts must be present
    # with their unit in a supplied measure; numbers alone cannot prove an amount.
    corpus = " ".join(str(value) for item in facts for value in item.values())
    count_values = {str(item["records"]) for item in facts}
    allowed = {value.replace(",", "") for value in NUMBERS.findall(corpus)}
    units = {
        (number.replace(",", ""), unit)
        for number, unit in NUMBER_WITH_UNIT.findall(corpus)
    }
    claims = {
        (number.replace(",", ""), unit)
        for number, unit in NUMBER_WITH_UNIT.findall(text)
    }
    if any(n.replace(",", "") not in allowed for n in NUMBERS.findall(text)) or any(
        (number, unit) not in units
        and not (number in count_values and unit in {"条", "项"})
        for number, unit in claims
    ):
        problems.append("unsupported_number")
    return problems


def reviewed_summary(store, actor, request, artifact, facts, authorize):
    feature = "agent.specialist." + artifact["agent"]
    result = generation.summarize(
        store, actor, request, artifact["category"], facts, feature=feature
    )
    findings = issues(result, facts)
    metadata = {"model": model_name(), "source": completions.provider_name()}
    if not findings:
        return {
            **metadata,
            "text": result,
            "reflection": {"outcome": "accepted", "attempts": 1, "checks": []},
        }
    authorize()
    amended = generation.summarize(
        store,
        actor,
        ["brief-correction", request],
        artifact["category"],
        {
            "evidence": facts,
            "correction": "上一版未通过事实核对。请依据这些资料重新给出核对建议，省略未经证实的数字和已经办理的表述。",
        },
        feature=feature,
    )
    outstanding = issues(amended, facts)
    if outstanding:
        return {
            **metadata,
            "source": "evidence",
            "text": ("Review the source records below. The generated narrative did not pass verification."
                     if getattr(store, "deployment_edition", "china") == "international" else "云端说明未通过核对，请依据下列原始记录复核。"),
            "reflection": {
                "outcome": "evidence_only",
                "attempts": 2,
                "checks": findings,
                "remaining": outstanding,
            },
        }
    return {
        **metadata,
        "text": amended,
        "reflection": {"outcome": "corrected", "attempts": 2, "checks": findings},
    }
