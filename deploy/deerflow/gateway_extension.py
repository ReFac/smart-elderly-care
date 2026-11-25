"""Optional, human-only publication through the v2.2 Gateway's bound host API."""

from collections.abc import Mapping
from hashlib import sha256
import json
import re

import httpx
from deerflow_extension_api import BackendAction, PluginContribution, extension


class ApprovedSkills:
    def __init__(self, config):
        port = config.get("workspace_port")
        owners = config.get("owner_campuses")
        if type(port) is not int or not 1 <= port <= 65535 or not isinstance(owners, Mapping) or not owners:
            raise ValueError("请配置本机工作台端口和 Gateway 账号与院区的一对一对应关系")
        if (len(set(owners.values())) != len(owners)
                or not all(isinstance(k, str) and isinstance(v, str) and k and v for k, v in owners.items())):
            raise ValueError("每个 Gateway 账号与院区应独立绑定")
        self.url = f"http://127.0.0.1:{port}/api/assistant/learning/gateway-exchange"
        self.owners = dict(owners)
        self.deps = None

    async def start(self, deps):
        if deps.completed_run_evidence is None or deps.skill_mutations is None:
            raise RuntimeError("请启用本扩展的 Gateway 宿主授权")
        self.deps = deps

    async def stop(self):
        self.deps = None

    async def approved(self, owner, ticket):
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=5) as client:
            reply = await client.post(self.url, json={"gatewayOwner": owner, "ticket": ticket})
            reply.raise_for_status()
            result = reply.json()
        if (result["campus"] != self.owners[owner] or result["name"] not in {
                "careops-meals", "careops-handover", "careops-visit", "careops-observations"}):
            raise PermissionError("院区或技能不匹配")
        return result

    def caller(self, value, ctx):
        owner = ctx.principal.user_id
        if (not self.deps or ctx.interaction != "session" or ctx.principal.is_internal or owner not in self.owners):
            raise PermissionError("请使用本院区绑定的 Gateway 账号人工操作")
        if not isinstance(value.get("ticket"), str) or not re.fullmatch(r"[a-zA-Z0-9_-]{43}", value["ticket"]):
            raise ValueError("请提供工作台签发的短时同步凭证")
        return owner

    async def stage(self, value, ctx):
        owner = self.caller(value, ctx)
        if set(value) != {"ticket", "threadId", "runId"}:
            raise ValueError("请选择已完成的 Gateway 对话和运行")
        if not all(isinstance(value[k], str) and 0 < len(value[k]) <= 128 for k in ("threadId", "runId")):
            raise ValueError("运行编号无效")
        approved = await self.approved(owner, value["ticket"])
        evidence, mutations = self.deps.completed_run_evidence, self.deps.skill_mutations
        snap = await evidence.get_snapshot(thread_id=value["threadId"], run_id=value["runId"])
        if (snap.seal_state != "sealed" or snap.status != "success" or snap.owner_id != owner or
                snap.agent_id != "lead_agent" or snap.origin != "interactive"):
            raise PermissionError("请使用该账号的已封存主对话运行")
        skill = await mutations.read_skill(source_ref=snap.snapshot_ref, name=approved["name"])
        if skill.owner_id != owner or skill.name != approved["name"] or not skill.enabled:
            raise PermissionError("技能不属于该账号或未启用")
        # The source run and the institution release define a logical request; a
        # refreshed snapshot reference must not open a second logical publication.
        key = sha256(json.dumps([owner, approved["campus"], approved["name"], approved["version"],
                                 approved["digest"], snap.thread_id, snap.run_id], separators=(",", ":")).encode()).hexdigest()
        proposal = await mutations.stage(source_refs=(snap.snapshot_ref,), target_ref=skill.target_ref,
                                         expected_revision=skill.revision, content=approved["document"],
                                         idempotency_key="careops-stage-" + key)
        check = await self._checked(mutations, owner, proposal, approved)
        return {"proposalId": proposal.proposal_id, "decision": check.decision,
                "candidateHash": check.candidate_hash, "workspaceDigest": approved["digest"]}

    async def _checked(self, mutations, owner, proposal, approved):
        if proposal.owner_id != owner or proposal.name != approved["name"]:
            raise PermissionError("候选技能与当前账号不匹配")
        bundle = await mutations.read_proposal_bundle(proposal_id=proposal.proposal_id)
        if len(bundle.candidate) != 1 or bundle.candidate[0].path != "SKILL.md" or bundle.candidate[0].executable:
            raise PermissionError("已审核的机构技能只能包含一份不可执行的 SKILL.md")
        if bundle.candidate[0].content != approved["document"].encode() or bundle.candidate_hash != proposal.candidate_hash:
            raise PermissionError("Gateway 候选与机构已审定原件不一致")
        result = await mutations.check(proposal_id=proposal.proposal_id)
        if result.decision != "allow" or result.candidate_hash != bundle.candidate_hash:
            raise ValueError("Gateway 安全扫描未允许发布")
        return result

    async def publish(self, value, ctx):
        owner = self.caller(value, ctx)
        if (set(value) != {"ticket", "proposalId", "confirm"} or value["confirm"] is not True
                or not isinstance(value["proposalId"], str) or not 0 < len(value["proposalId"]) <= 128):
            raise ValueError("发布需要重新人工确认指定的候选版本")
        approved = await self.approved(owner, value["ticket"])
        mutations = self.deps.skill_mutations
        proposal = await mutations.get_proposal(proposal_id=value["proposalId"])
        if proposal.owner_id != owner or proposal.name != approved["name"]:
            raise PermissionError("该候选属于其他账号或技能")
        key = "careops-commit-" + sha256(json.dumps([owner, proposal.proposal_id, approved["digest"]],
                                                   separators=(",", ":")).encode()).hexdigest()
        operation = await mutations.find_operation(idempotency_key=key, method="commit")
        if operation is None:
            await self._checked(mutations, owner, proposal, approved)
            # Scanning can take minutes. Recheck the current employee session and
            # exact institution head immediately before the host's revision CAS.
            if await self.approved(owner, value["ticket"]) != approved:
                raise PermissionError("机构版本或权限已改变")
            operation = await mutations.commit(proposal_id=proposal.proposal_id, idempotency_key=key)
        return {"operationId": operation.operation_id, "publication": operation.publication,
                "views": operation.views, "generation": operation.generation}


@extension(api="0.2.9", name="careops-reviewed-skills")
def install(registry, config):
    service = ApprovedSkills(config)
    registry.service(service)
    registry.plugin(PluginContribution(namespace="careops.reviewed-skills", title="已审核的机构经验技能",
                    description="同步已由本院区员工批准的写作规则", backend=(
                        BackendAction("stage", service.stage), BackendAction("publish", service.publish))))
