"""Specialist model calls share one graph, the original receipt and its retry key."""

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from platform_core import provider
from platform_core.agents import deerflow_chat
from platform_core.provider import generation, task_usage
from platform_core.store import Store
from provider_fixture import isolate_credentials


class SpecialistDispatchTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        isolate_credentials(self, folder.name)
        self.store = Store(Path(folder.name) / "institution.sqlite3", initial_owner_password="test-only-synthetic")
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "机构测试", 5000, "2099-03-02", self.store.now())
        self.enterContext(patch.object(provider, "read_model_key", return_value="test-only"))
        self.provider = self.enterContext(patch.object(generation.completions, "send", return_value={
            "choices": [{"finish_reason": "stop", "message": {"content": '{"text":"已核对"}'}}],
            "usage": {"total_tokens": 12},
        }))

    def classify(self):
        return generation.generate(self.store, "owner", "demo-1", "整理虚构资料", {"原文": "样例"},
                                   generation.narrative, feature="assistant.documentClassify")

    def test_classification_uses_graph_once_and_preserves_business_receipt(self):
        task = task_usage.identifier("visit", "demo")
        with (patch.object(deerflow_chat, "_run", side_effect=lambda body, first, tool, summary, name: first()) as graph,
              task_usage.scope("platform", task)):
            self.assertEqual(self.classify(), {"text": "已核对"})
            self.assertEqual(self.classify(), {"text": "已核对"})
        graph.assert_called_once()
        self.assertEqual(graph.call_args.args[-1], "assistant-documentClassify")
        self.provider.assert_called_once()
        with closing(self.store.connect()) as db:
            rows = db.execute("SELECT runtime,taskId FROM agent_task_usage").fetchall()
            self.assertEqual([tuple(row) for row in rows], [("deerflow", task)])

    def test_unavailable_graph_leaves_no_charge_or_stale_reservation(self):
        with (patch.object(deerflow_chat, "_run", side_effect=deerflow_chat.Unavailable("任务服务不可用")),
              self.assertRaisesRegex(ValueError, "任务服务不可用")):
            self.classify()
        self.provider.assert_not_called()
        with closing(self.store.connect()) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM api_usage").fetchone()[0], 0)

    def test_active_lead_graph_uses_its_existing_task(self):
        task = task_usage.identifier("chat", "demo")
        with (patch.object(deerflow_chat, "_run") as new_graph,
              patch.object(deerflow_chat, "active", return_value=True),
              task_usage.scope("deerflow", task)):
            self.classify()
        new_graph.assert_not_called()
        self.provider.assert_called_once()
