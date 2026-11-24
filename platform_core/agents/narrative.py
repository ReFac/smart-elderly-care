"""Collect authorized evidence locally and interpret the scoped metrics in DeepSeek."""

from contextlib import closing
import json

from . import preflight, runtime
from .. import access, campus_access
from ..operations import assistants
from ..provider import generation, model_name


class Events:
    def __init__(self):
        self.rows = []

    def append(self, agent, event, text, parent=""):
        self.rows.append((agent, event, text, parent))


def measures(artifact):
    result = []
    for ref in artifact["evidence"][:48]:
        obj = {"dataset": ref["source"], "records": len(ref["recordIds"])}
        if artifact["agent"] in ("finance", "inventory"):
            obj.update(measure=ref["label"][:120], value=ref["value"][:240])
        result.append(obj)
    return result


def collect(check, state, actor, day):
    args = check["args"]
    log = Events()
    artifacts = runtime.execute(
        args["goal"],
        check["specs"],
        args["scope"],
        state,
        args["residentId"],
        day,
        log,
        member_ids=frozenset(check["resolved"]["residentIds"])
        if check["resolved"]
        else None,
        actor_id=actor["id"],
    )
    return artifacts, log


def prepare(store, token, payload, revision, *, suggestion=False):
    from ..store import Conflict

    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        actor = store.actor(db, token)
        current, data = db.execute(
            "SELECT revision,data FROM workspace WHERE id=1"
        ).fetchone()
        if type(revision) is not int or revision != current:
            raise Conflict("数据已更新，请核对最新内容后重新提交")
        state = json.loads(data)
        if suggestion:
            access.authorize(actor, "ops.suggest", payload, state)
            campus_access.authorize_command(db, actor, "ops.suggest", payload, state)
            if actor.get("facilityScope"):
                raise PermissionError("请通过授权区域的助理问询办理")
            category = payload.get("category")
            # Test and import callers can still use the calculator independently.
            assistants.generate_suggestion(
                state, payload, store.now().date().isoformat()
            )
            item = state["suggestions"][0]
            item["agent"] = {
                "日常照护": "care",
                "物资管控": "inventory",
                "运营分析": "finance",
            }[category]
            item["tool"] = category
            req = [revision, category, item["residentId"]]
            artifacts, log = [item], Events()
        else:
            check = preflight(db, state, actor, payload)
            if check["prior"]:
                return None
            artifacts, log = collect(
                check, state, actor, store.now().date().isoformat()
            )
            req = [revision, check["request"], check["fingerprintScope"]]
    for artifact in artifacts:
        facts = measures(artifact)
        explanation = generation.summarize(
            store,
            actor["id"],
            ["specialist", req, artifact["agent"]],
            artifact["category"],
            facts,
        )
        # Evidence calculations and referenced field-level facts stay reproducible on the host.
        artifact["detail"] = explanation + "\n\n核对依据\n" + artifact["detail"]
        artifact["model"] = model_name()
        artifact["source"] = "deepseek"
    return {
        "mode": "deepseek",
        "model": model_name(),
        "artifacts": artifacts,
        "events": log.rows,
        "actor": actor["id"],
        "region": check["resolved"] if not suggestion else None,
    }
