"""Chinese evidence regression tests for the pinned, unprivileged DeerFlow process."""

from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import patch

from platform_core.agents import deerflow_worker as worker
from platform_core.provider import task_usage


class WorkerTests(TestCase):
    def setUp(self):
        self.store = SimpleNamespace(path="独立中文测试库")
        self.task = task_usage.identifier("round", "测试长辈", "今日")

    def request(self, kind, facts, **options):
        return worker.generate(
            kind,
            self.task,
            self.store,
            "测试护士",
            [kind, "虚构任务"],
            "仅引用提供的资料。",
            facts,
            lambda value: value,
            **options,
        )

    @skipUnless(
        worker.installation()["installed"], "需要在独立环境安装官方 DeerFlow 2.2.0 SDK"
    )
    def test_graph_checks_evidence_and_forgets_previous_resident(self):
        with patch.dict("os.environ", {"NH_DEERFLOW_BACKEND": "deerflow"}):
            first = {"事实": [{"日期": "2026-11-24", "事实": "甲参加早餐"}]}
            second = {"摘录": [[1, "登记体征", "乙已登记晚间体征"]]}
            with patch.object(
                worker.generation,
                "generate",
                side_effect=[
                    {"paragraphs": [[1]]},
                    {"selected": [1]},
                    {"selected": [2]},
                ],
            ) as paid:
                self.assertEqual(
                    self.request("daily-life", first), {"paragraphs": [[1]]}
                )
                self.assertEqual(
                    self.request("health-review", second), {"selected": [1]}
                )
                # Exercise the actual IPC/tool graph, including defense against
                # a syntactically valid cloud draft citing another source.
                with self.assertRaisesRegex(ValueError, "来源"):
                    self.request("health-review", second)
                self.assertEqual(
                    [call.args[4] for call in paid.call_args_list],
                    [first, second, second],
                )

    @skipUnless(
        worker.installation()["installed"], "需要在独立环境安装官方 DeerFlow 2.2.0 SDK"
    )
    def test_revocation_is_checked_immediately_before_cloud_dispatch(self):
        def revoked():
            raise PermissionError("已经撤销授权")

        with (
            patch.dict("os.environ", {"NH_DEERFLOW_BACKEND": "deerflow"}),
            patch.object(worker.generation, "generate") as paid,
        ):
            with self.assertRaises(PermissionError):
                self.request(
                    "health-review",
                    {"摘录": [[1, "复核", "本人体征"]]},
                    authorize=revoked,
                )
            paid.assert_not_called()

    def test_missing_runtime_never_transparently_calls_cloud(self):
        with patch.dict(
            "os.environ",
            {
                "NH_DEERFLOW_BACKEND": "deerflow",
                "NH_DEERFLOW_PYTHON": "/不存在/测试解释器",
            },
        ):
            with worker.LOCK:
                worker._stop()
            self.assertFalse(worker.installation()["ready"])
            with (
                patch.object(worker.generation, "generate") as paid,
                self.assertRaisesRegex(ValueError, "DeerFlow 2.2.0 未就绪"),
            ):
                self.request("daily-life", {"事实": []})
            paid.assert_not_called()

    @skipUnless(
        worker.installation()["installed"], "需要在独立环境安装官方 DeerFlow 2.2.0 SDK"
    )
    def test_scheduled_health_review_runs_one_scoped_graph_for_unchanged_sources(self):
        from contextlib import closing
        from datetime import datetime
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from threading import Event

        from platform_core.rounds import health_review
        from platform_core.store import Store, TIMEZONE

        fixed = datetime(2026, 11, 24, 19, tzinfo=TIMEZONE)
        with (
            TemporaryDirectory() as folder,
            patch.dict("os.environ", {"NH_DEERFLOW_BACKEND": "deerflow"}),
        ):
            store = Store(
                Path(folder) / "health.sqlite3",
                now=lambda: fixed,
                initial_owner_password="synthetic-care-123",
            )
            with closing(store.connect()) as db, db:
                state = json.loads(
                    db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
                )
                people = [
                    person
                    for person in state["residents"]
                    if person["status"] == "在住" and person.get("bedId")
                ]
                selected, other = people[:2]
                selected["summary"] = "本次巡查专用的个人观察。"
                other["summary"] = "另一位不属于本任务的资料。"
                db.execute(
                    "UPDATE workspace SET data=? WHERE id=1",
                    (json.dumps(state, ensure_ascii=False),),
                )
                db.execute("UPDATE rounds_policy SET default_mode='manual'")
                db.execute("UPDATE rounds_health_policy SET enabled=1,next_at=''")
                db.execute(
                    "INSERT OR REPLACE INTO rounds_modes VALUES(?,?)",
                    (selected["id"], "auto"),
                )
            with patch.object(
                worker.generation, "generate", return_value={"selected": [1]}
            ) as paid:
                self.assertEqual(health_review.tick(store, Event()), 1)
                facts = str(paid.call_args.args[4])
                self.assertIn("本次巡查专用", facts)
                self.assertNotIn("不属于本任务", facts)
                with closing(store.connect()) as db, db:
                    row = db.execute(
                        "SELECT resident,payload FROM rounds_health_reviews"
                    ).fetchone()
                    self.assertEqual(row[0], selected["id"])
                    draft = json.loads(row[1])
                    self.assertEqual(
                        (draft["status"], draft["draftRuntime"]), ("draft", "deerflow")
                    )
                    self.assertRegex(draft["taskId"], r"^round-[a-f0-9]{24}$")
                    db.execute("UPDATE rounds_health_policy SET next_at=''")
                self.assertEqual(health_review.tick(store, Event()), 0)
                self.assertEqual(paid.call_count, 1)
