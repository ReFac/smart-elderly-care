"""Executed inside the pinned DeerFlow venv, using a synthetic sealed run and skill."""

import asyncio
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.paths import Paths
from deerflow.extensions.host_capabilities import HostCapabilities
from deerflow.extensions.loader import ExtensionSpec
from deerflow.persistence.base import Base
from deerflow.persistence.run import RunRepository
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.user.model import UserRow
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.skills.mutations.scanner import CandidateScanner, ScanVerdict
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage
from deerflow_extension_api import ActionContext, ExtensionPrincipal, ExtensionRuntimeDeps

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/deerflow"))
from gateway_extension import install


async def exercise(root, workspace_port, ticket):
    owner = "gateway-care-lead"
    name = "careops-meals"
    old = f"---\nname: {name}\ndescription: 用餐观察\n---\n\n检查本餐出席。\n"
    skill = UserScopedSkillStorage(owner, host_path=str(root / "skills"))
    path = skill.get_custom_skill_dir(name) / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(old, encoding="utf-8")
    database = DatabaseConfig(backend="sqlite", sqlite_dir=str(root))
    sync_db = create_engine(database.app_sync_sqlalchemy_url)
    Base.metadata.create_all(sync_db)
    sync_db.dispose()
    engine = create_async_engine(database.app_sqlalchemy_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as db:
        db.add(UserRow(id=owner, email="synthetic@example.test"))
        db.add(RunRow(run_id="review-run", thread_id="review-thread", user_id=owner, status="success",
                      evidence_seal_state="sealed", evidence_agent_id="lead_agent", evidence_origin="interactive",
                      evidence_event_count=0, evidence_upper_seq=0))
    spec = ExtensionSpec(use="gateway_extension:install", name="careops-reviewed-skills",
                         host_access={"evidence": {"owners": [owner]}, "skill_mutations": {"owners": [owner],
                                      "operations": ["stage", "check", "commit"], "trigger_agents": ["lead_agent"],
                                      "target_skills": [name], "topology": "single_host_local"}})
    host = HostCapabilities(SimpleNamespace(database=database, plugins=[spec]), RunRepository(sessions),
                            DbRunEventStore(sessions), root=root, storage_factory=lambda _: skill)
    loaded = {}
    registry = SimpleNamespace(service=lambda item: loaded.update(service=item),
                               plugin=lambda item: loaded.update(plugin=item))
    install(registry, {"workspace_port": workspace_port, "owner_campuses": {owner: "campus-main"}})
    assert not loaded["plugin"].tools
    actions = {a.name: a.handler for a in loaded["plugin"].backend}
    ctx = ActionContext(principal=ExtensionPrincipal(owner), settings={}, interaction="session")
    try:
        await host.start()
        evidence, mutations = host.bindings[spec.use]
        await loaded["service"].start(ExtensionRuntimeDeps(completed_run_evidence=evidence, skill_mutations=mutations))
        stage = {"ticket": ticket, "threadId": "review-thread", "runId": "review-run"}
        try:
            await actions["stage"](stage, ActionContext(principal=ExtensionPrincipal(owner), settings={}))
        except PermissionError:
            pass
        else:
            raise AssertionError("非人工会话不应获准")
        staged = await actions["stage"](stage, ctx)
        assert staged["decision"] == "allow" and path.read_text() == old
        # An otherwise valid host candidate containing an unreviewed sidecar cannot publish.
        from dataclasses import replace
        from deerflow_extension_api.skill_mutations import BundleFile
        bundle = await mutations.read_proposal_bundle(proposal_id=staged["proposalId"])
        original = await mutations.get_proposal(proposal_id=staged["proposalId"])
        extra = BundleFile("extra.txt", b"fixture", "0" * 64, False)
        for invalid in (bundle.candidate + (extra,), (replace(bundle.candidate[0], executable=True),)):
            with patch.object(mutations, "read_proposal_bundle", new_callable=AsyncMock,
                              return_value=replace(bundle, candidate=invalid)):
                try:
                    await loaded["service"]._checked(mutations, owner, original, {"name": name})
                except PermissionError:
                    pass
                else:
                    raise AssertionError("仅可发布经核对的单一不可执行技能文件")
        publish = {"ticket": ticket, "proposalId": staged["proposalId"], "confirm": True}
        done = await actions["publish"](publish, ctx)
        assert done["publication"] == "APPLIED" and done["views"] == "READY"
        assert await actions["publish"](publish, ctx) == done
        assert "实际摄入" in path.read_text()
        print(done["publication"], done["views"])
    finally:
        await loaded["service"].stop()
        await host.close()
        await engine.dispose()


if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        base = Path(directory)
        # Keep the SDK's storage, source grants, evidence, CAS, host checks and publication real.
        # Only the paid security-scanning model's verdict is a synthetic fixture.
        with (patch("deerflow.config.paths._paths", Paths(base_dir=base / "home")),
              patch.object(CandidateScanner, "policy_version_sync", return_value="test-scanner"),
              patch.object(CandidateScanner, "policy_version", new_callable=AsyncMock, return_value="test-scanner"),
              patch.object(CandidateScanner, "scan", new_callable=AsyncMock,
                           return_value=ScanVerdict("allow", "CHECK_PASSED", "test-scanner"))):
            asyncio.run(exercise(base, int(sys.argv[1]), sys.stdin.readline().strip()))
