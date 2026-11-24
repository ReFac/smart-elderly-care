from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from platform_core import provider
from platform_core.provider import round_priorities as priorities
from platform_core.store import Store, TIMEZONE
from provider_fixture import isolate_credentials


class PriorityTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        isolate_credentials(self, tmp.name)
        env = patch.dict(
            "os.environ",
            {
                "DEEPSEEK_API_KEY": "test-only",
                "NH_OWNER_PASSWORD": "test-only-long-password",
            },
        )
        env.start()
        self.addCleanup(env.stop)
        now = datetime(2026, 11, 24, 10, 0, tzinfo=TIMEZONE)
        self.store = Store(Path(tmp.name) / "care.sqlite3", lambda: now)
        self.token, _ = self.store.login("owner", "test-only-long-password")
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "test", 4000, "2026-12-01", now)
            revision, state = db.execute(
                "SELECT revision,data FROM workspace"
            ).fetchone()
            workspace = json.loads(state)
            workspace["tasks"] = [
                {
                    "id": "private-task-" + str(i),
                    "residentId": "r001",
                    "date": "2026-11-24",
                    "title": "PRIVATE TEXT",
                    "status": status,
                    "time": time,
                    "assignee": "PRIVATE NAME",
                }
                for i, (time, status) in enumerate(
                    [("09:00", "待执行"), ("15:00", "待执行"), ("08:00", "已完成")]
                )
            ]
            db.execute("UPDATE workspace SET data=?", (json.dumps(workspace),))
        result = self.store.rounds.write(
            self.token, "/api/rounds/residents/r001/generate", {"revision": revision}
        )
        self.payload = {
            "revision": result["revision"],
            "reportId": result["latest"]["id"],
            "confirmed": True,
        }

    def test_minimized_prompt_deduplicates_and_preserves_checks(self):
        transport = Mock(
            return_value={
                "usage": {"total_tokens": 44},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"ids":["upcoming","past_due"]}'},
                    }
                ],
            }
        )
        result = priorities.generate(
            self.store, self.token, "r001", self.payload, transport=transport
        )
        self.assertEqual(
            result["items"],
            [priorities.CHECKS[k] for k in ("upcoming", "past_due", "completed")],
        )
        self.assertEqual(
            priorities.generate(
                self.store, self.token, "r001", self.payload, transport=transport
            ),
            result,
        )
        self.assertEqual(transport.call_count, 1)
        body = transport.call_args.args[1]
        self.assertEqual(
            json.loads(body["messages"][1]["content"]),
            ["past_due", "upcoming", "completed"],
        )
        self.assertNotIn("PRIVATE", json.dumps(body))
        with closing(self.store.connect()) as db:
            self.assertEqual(provider.usage(db, provider.latest(db)["id"]), (44, 0))

    def test_requires_consent_and_rejects_unapproved_output(self):
        transport = Mock(
            return_value={
                "usage": {"total_tokens": 35},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"ids":["DOSE"]}'},
                    }
                ],
            }
        )
        with self.assertRaises(ValueError):
            priorities.generate(
                self.store,
                self.token,
                "r001",
                {**self.payload, "confirmed": False},
                transport=transport,
            )
        transport.assert_not_called()
        result = priorities.generate(
            self.store, self.token, "r001", self.payload, transport=transport
        )
        self.assertEqual((result["items"], result["reason"]), ([], "invalid_output"))
