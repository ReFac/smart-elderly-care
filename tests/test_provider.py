"""Paid planning must remain scoped, bounded, replayable and reconcilable."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stdout
from datetime import datetime, timedelta
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from threading import Event
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import manage_plan
from provider_fixture import isolate_credentials
from platform_core import provider, secure_storage
from platform_core.provider import deepseek


DAY = datetime(2026, 11, 24, 12, tzinfo=provider.ZONE)


def reply(*ids, tokens=48):
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": json.dumps({"ids": list(ids)})},
            }
        ],
        "usage": {"total_tokens": tokens},
    }


class ProviderTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        isolate_credentials(self, tmp.name)
        self.path = Path(tmp.name) / "instance.sqlite"
        env = patch.dict(
            os.environ,
            {
                "DEEPSEEK_API_KEY": "fixture-only",
                "NH_DEEPSEEK_MODEL": "deepseek-flash",
                "NH_DEEPSEEK_KEY_FILE": "",
            },
        )
        env.start()
        self.addCleanup(env.stop)
        _, self.storage_key = secure_storage.prepare_database(self.path)
        self.actor = {
            "id": "employee-one",
            "kind": "staff",
            "permissions": ["assistants", "care", "inventory"],
        }
        self.owner = {"id": "owner", "kind": "owner"}
        with closing(self.connect()) as db, db:
            provider.init(db)
        self.mock = Mock(return_value=reply("inventory"))

    def connect(self):
        return secure_storage.open_database(self.path, self.storage_key)

    def grant(self, tokens=2000, now=DAY, expires="2026-11-30"):
        with closing(self.connect()) as db, db:
            provider.grant(db, "按期购买的云端协作", tokens, expires, now)

    def status(self, actor=None, now=DAY):
        with closing(self.connect()) as db:
            return provider.status(db, actor or self.owner, now)

    def plan(self, goal="检查库存", request="r01", **kwargs):
        return provider.plan(
            self.connect,
            lambda db: self.actor,
            goal,
            request,
            now=kwargs.pop("now", DAY),
            transport=kwargs.pop("transport", self.mock),
            **kwargs,
        )

    def test_operator_changes_refresh_workspace_and_create_one_audit_entry(self):
        with closing(self.connect()) as db, db:
            db.execute(
                "CREATE TABLE workspace(id INTEGER PRIMARY KEY, revision INTEGER)"
            )
            db.execute("INSERT INTO workspace VALUES(1, 7)")
        for args in (
            ["grant", "--name", "试点", "--tokens", "2500", "--expires", "2099-11-30"],
            ["unlimited"],
            ["unlimited"],
            ["status"],
            ["disable"],
        ):
            with (
                patch("sys.argv", ["manage_plan.py", "--db", str(self.path), *args]),
                redirect_stdout(StringIO()),
            ):
                self.assertEqual(manage_plan.main(), 0)
        with closing(self.connect()) as db:
            self.assertEqual(
                db.execute("SELECT revision FROM workspace").fetchone()[0], 10
            )
            entries = db.execute(
                "SELECT action,actorId FROM audit ORDER BY revision"
            ).fetchall()
            self.assertEqual(
                [tuple(r) for r in entries],
                [
                    ("platform.plan.grant", "platform-operator"),
                    ("platform.plan.unlimited", "platform-operator"),
                    ("platform.plan.disable", "platform-operator"),
                ],
            )

    def test_existing_plan_migration_keeps_limits_until_operator_opts_in(self):
        with closing(sqlite3.connect(":memory:")) as db:
            db.row_factory = sqlite3.Row
            db.execute("""CREATE TABLE api_plans(id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                tokenLimit INTEGER NOT NULL, startsOn TEXT NOT NULL,expiresOn TEXT NOT NULL,enabled INTEGER NOT NULL)""")
            db.execute("INSERT INTO api_plans VALUES(4,'既有机构',123,'2026-01-01','2026-10-31',1)")
            provider.init(db)
            provider.init(db)
            plan = provider.latest(db)
            self.assertFalse(plan["unlimited"])
            self.assertFalse(provider.active(plan, "2026-11-01"))
            self.assertEqual(provider.remaining_tokens(db, plan), 123)
            with patch.object(provider, "usage", side_effect=AssertionError("unlimited quota check should not scan usage")):
                self.assertTrue(provider.allow_unlimited(db, DAY))
                self.assertFalse(provider.allow_unlimited(db, DAY))
                plan = provider.latest(db)
                self.assertEqual(plan["id"], 4)
                self.assertTrue(provider.active(plan, "2030-01-01"))
                self.assertIsNone(provider.remaining_tokens(db, plan))

    def test_unlimited_routes_past_expiry_and_old_limit_with_real_usage(self):
        self.grant(tokens=1, expires="2026-11-24")
        future = DAY + timedelta(days=365)
        with closing(self.connect()) as db, db:
            plan_id = provider.latest(db)["id"]
            provider.allow_unlimited(db, future)
        self.assertEqual(self.plan(now=future)["reason"], "ready")
        self.assertEqual(self.plan(now=future)["reason"], "ready")
        self.mock.assert_called_once()
        status = self.status(now=future)
        self.assertTrue(status["unlimited"])
        self.assertTrue(status["available"])
        self.assertIsNone(status["tokenLimit"])
        self.assertIsNone(status["expiresOn"])
        self.assertEqual((status["tokensUsed"], status["tokensReserved"]), (48, 0))
        with closing(self.connect()) as db, db:
            provider.disable(db)
            self.assertFalse(provider.active(provider.latest(db), future.date().isoformat()))
        self.assertEqual(self.plan(request="off", now=future)["reason"], "inactive")
        with self.assertRaisesRegex(ValueError, "低于本期"):
            self.grant(tokens=1, now=future, expires="2027-12-31")
        self.grant(tokens=48, now=future, expires="2027-12-31")
        with closing(self.connect()) as db:
            self.assertEqual(provider.latest(db)["id"], plan_id)
        status = self.status(now=future)
        self.assertFalse(status["unlimited"])
        self.assertEqual(status["state"], "exhausted")
        self.assertEqual(status["tokensUsed"], 48)

    def test_operator_can_enable_unlimited_for_an_empty_workspace(self):
        with closing(self.connect()) as db, db:
            provider.allow_unlimited(db, DAY)
            self.assertTrue(provider.active(provider.latest(db), "2030-01-01"))
            self.assertFalse(provider.active(provider.latest(db), "2026-01-01"))
        self.assertTrue(self.status()["available"])

    def test_trial_needs_operator_grant_and_key_users_cannot_override(self):
        self.assertEqual(self.status()["state"], "inactive")
        self.assertEqual(self.plan()["reason"], "inactive")
        self.grant()
        self.assertTrue(self.status()["available"])
        self.assertNotIn("tokenLimit", self.status(self.actor))
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            self.assertEqual(self.plan()["reason"], "unconfigured")
        with self.assertRaises(PermissionError):
            self.status({"id": "relative", "kind": "family"})
        self.actor["permissions"] = ["assistants"]
        with self.assertRaises(PermissionError):
            self.plan()
        self.mock.assert_not_called()

    def test_private_request_replays_once_across_restart_checking_live_grants(self):
        self.grant()
        goal = "给张小林 301 床检查库存，身份证 1234567890，电话 13000000000"
        output = self.plan(goal, "r01")
        self.assertEqual(
            output,
            {
                "mode": "deepseek",
                "reason": "ready",
                "model": "deepseek-flash",
                "specialistIds": ["inventory"],
            },
        )
        self.assertEqual(self.plan(goal, " r01 "), output)
        self.mock.assert_called_once()
        body = self.mock.call_args.args[1]
        self.assertEqual(body["max_tokens"], 32)
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertEqual(body["model"], "deepseek-flash")
        sent = json.dumps(body, ensure_ascii=False)
        for prohibited in (
            "张小林",
            "301",
            "1234567890",
            "13000000000",
            "fixture-only",
            "finance",
        ):
            self.assertNotIn(prohibited, sent)
        self.assertEqual(self.status()["tokensUsed"], 48)
        self.assertEqual(self.status()["tokensReserved"], 0)
        with self.assertRaises(ValueError):
            self.plan("核对护理", "r01")
        self.actor["permissions"] = ["assistants", "care"]
        with self.assertRaises(PermissionError):
            self.plan(goal)
        with closing(self.connect()) as db:
            stored = [dict(r) for r in db.execute("SELECT * FROM api_usage")]
            self.assertNotIn(goal, str(stored))

    def test_unknown_tags_do_not_trigger_remote_or_send_personal_information(self):
        self.grant()
        self.assertEqual(self.plan("张先生的电话号码")["reason"], "no_signal")
        self.mock.assert_not_called()

    def test_concurrent_reservations_no_db_lock_overspend_or_duplicate_calls(self):
        self.grant()
        entered, finish = Event(), Event()

        def respond(key, body):
            entered.set()
            self.assertTrue(finish.wait(4))
            return reply("inventory")

        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.plan, transport=respond)
            self.assertTrue(entered.wait(2))
            try:
                # Updating a plan while transport is waiting proves there is no active DB write lock.
                hold = self.status()["tokensReserved"]
                self.assertGreater(hold, 48)
                self.grant(hold)
                with self.assertRaisesRegex(ValueError, "正在处理"):
                    self.plan()
                self.assertEqual(self.plan(request="r02")["reason"], "exhausted")
            finally:
                finish.set()
            self.assertEqual(pending.result(timeout=3)["mode"], "deepseek")
        self.mock.assert_not_called()
        self.assertEqual(self.status()["tokensUsed"], 48)

    def test_invalid_outcome_bills_reported_usage_and_stops_without_retry(self):
        self.grant()
        self.mock.return_value = reply("finance", tokens=51)
        self.assertEqual(self.plan()["reason"], "invalid_output")
        self.assertEqual(self.plan()["mode"], "unavailable")
        self.assertEqual(self.status()["tokensUsed"], 51)
        self.mock.assert_called_once()
        self.mock.side_effect = HTTPError(
            deepseek.ENDPOINT, 402, "Balance", {}, BytesIO(b"private error")
        )
        self.assertEqual(self.plan(request="rejected")["reason"], "provider_rejected")
        self.assertEqual(self.status()["tokensUsed"], 51)
        self.assertEqual(self.status()["tokensReserved"], 0)

    def test_ambiguous_failure_reserves_until_operator_reconciles(self):
        self.grant()
        self.mock.side_effect = TimeoutError("fixture uncertainty")
        self.assertEqual(self.plan()["reason"], "provider_unavailable")
        self.assertEqual(self.plan()["mode"], "unavailable")
        self.mock.assert_called_once()
        hold = self.status()["tokensReserved"]
        self.assertGreater(hold, 0)
        with closing(self.connect()) as db, db:
            with self.assertRaises(ValueError):
                provider.reconcile(db, self.actor["id"], "r01", hold + 1, DAY)
            provider.reconcile(db, self.actor["id"], "r01", 27, DAY)
        self.assertEqual(self.status()["tokensReserved"], 0)
        self.assertEqual(self.status()["tokensUsed"], 27)
        self.assertEqual(self.plan()["reason"], "reconciled")

    def test_expiry_renewal_and_revocation_during_network_request(self):
        self.grant(expires="2026-11-24")
        self.assertEqual(self.status(now=DAY + timedelta(days=1))["state"], "inactive")

        def revoke(key, body):
            self.actor["permissions"] = ["assistants", "care"]
            return reply("inventory")

        with self.assertRaises(PermissionError):
            self.plan(transport=revoke)
        self.assertEqual(self.status()["tokensUsed"], 48)
        self.grant(now=DAY + timedelta(days=2))
        self.assertEqual(self.status(now=DAY + timedelta(days=2))["tokensUsed"], 0)
        with closing(self.connect()) as db, db:
            provider.disable(db)
        self.assertEqual(self.status(now=DAY + timedelta(days=2))["state"], "inactive")

    @unittest.skipUnless(os.name == "posix", "POSIX file mode assertions")
    def test_platform_key_file_requires_private_regular_file(self):
        self.grant()
        key = self.path.parent / "test-provider"
        key.write_text("fixture-key-2\n")
        key.chmod(0o644)
        with patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": "", "NH_DEEPSEEK_KEY_FILE": str(key)}
        ):
            self.assertEqual(self.status()["state"], "unconfigured")
            key.chmod(0o600)
            self.assertEqual(self.plan()["mode"], "deepseek")
            self.assertEqual(self.mock.call_args.args[0], "fixture-key-2")
            link = key.parent / "link"
            link.symlink_to(key)
            os.environ["NH_DEEPSEEK_KEY_FILE"] = str(link)
            self.assertEqual(self.status()["state"], "unconfigured")


if __name__ == "__main__":
    unittest.main()
