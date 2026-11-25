"""Prepare approved evidence for DeerFlow supervisor and specialist runs."""

from contextlib import closing
import json

from . import brief_workflow, preflight, runtime
from .. import access, campus_access
from ..operations import assistants
from ..provider import completions, generation, model_name, plan as route_domains


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


def collect(check, state, actor, day, provider_plan=None):
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
        provider_plan=provider_plan,
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
            req = [revision, check["request"], check["fingerprintScope"]]
    if not suggestion:
        day = store.now().date().isoformat()
        provider_plan = None
        if check["args"]["scope"] == "auto":
            provider_plan = route_domains(
                store.connect,
                lambda db: store.actor(db, token),
                check["args"]["goal"],
                "brief-route/" + generation.fingerprint(check["request"]),
                now=store.now(), allowed_specs=check["specs"],
                scope_key=check["fingerprintScope"],
                required_care=bool(check["args"]["residentId"]),
            )
            if provider_plan["mode"] != "deepseek":
                reason = provider_plan["reason"]
                explanations = {
                    "no_signal": "请说明要核对照护、物资、收费还是全院概况，或直接选择专员",
                    "inactive": "机构的云端 AI 套餐尚未开通或已到期",
                    "exhausted": "机构的云端 AI 套餐额度不足",
                    "unconfigured": "机构尚未配置可用的云端模型",
                }
                raise ValueError(explanations.get(reason, "云端尚未返回有效的专员计划，请核对服务回执"))
            # Recheck current authorization and the captured revision before observing any records.
            with closing(store.connect()) as db, db:
                db.execute("BEGIN")
                actor = store.actor(db, token)
                current, data = db.execute("SELECT revision,data FROM workspace WHERE id=1").fetchone()
                if current != revision:
                    raise Conflict("数据已更新，请核对最新内容后重新提交")
                state = json.loads(data)
                latest = preflight(db, state, actor, payload)
                if latest["prior"]:
                    return None
                if latest["resolved"] != check["resolved"]:
                    raise PermissionError("授权区域已变化，请重新生成")
                check = latest
        artifacts, log = collect(check, state, actor, day, provider_plan)
    if not suggestion:
        # The evidence snapshot is frozen before adding cloud prose or evaluation metadata.
        source_artifacts = [dict(item) for item in artifacts]
    for artifact in artifacts:
        facts = measures(artifact)
        request = ["specialist", req, artifact["agent"]]
        if suggestion:
            explanation = generation.summarize(
                store, actor["id"], request, artifact["category"], facts, feature="agent.specialist." + artifact["agent"],
            )
        else:
            # Recheck the account and evidence before every metered step, including a retry.
            done = brief_workflow.checkpoint(store,token,check,revision,source_artifacts)
            name = artifact["agent"]
            if name in done:
                reviewed = done[name]
                log.append(name,"step.resumed","复用此来源版本上已核对的步骤","coordinator")
            else:
                reviewed = brief_workflow.reviewed_summary(store,actor["id"],request,artifact,facts,
                    lambda: brief_workflow.checkpoint(store,token,check,revision,source_artifacts))
                done = brief_workflow.checkpoint(store,token,check,revision,source_artifacts,(name,reviewed))
                reviewed = done[name]
            explanation = reviewed["text"]
            artifact["reflection"] = reviewed["reflection"]
            log.append(name,"reflection." + artifact["reflection"]["outcome"],
                       "已核对数值依据与办理表述 · " + str(artifact["reflection"]["attempts"]) + " 次生成","coordinator")
        artifact["detail"] = explanation + "\n\n核对依据\n" + artifact["detail"]
        artifact["model"] = model_name() if suggestion else reviewed["model"]
        artifact["source"] = completions.provider_name() if suggestion else reviewed["source"]
    if not suggestion:
        log.append("coordinator", "approval.requested", "产出已保存，等待人工核对并发布")
    return {
        "mode": "deepseek",
        "model": model_name(),
        "artifacts": artifacts,
        "events": log.rows,
        "actor": actor["id"],
        "region": check["resolved"] if not suggestion else None,
    }
