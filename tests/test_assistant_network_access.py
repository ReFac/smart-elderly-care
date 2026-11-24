"""Probe authorization and web tool reconciliation are independent of model token receipts."""

from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from platform_core import provider
from platform_core.agents import chat, network
from platform_core.provider import search_usage, web_search
from platform_core.store import SignedOut, Store, TIMEZONE


class NetworkAccessTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.now = datetime(2026, 11, 24, 10, tzinfo=TIMEZONE)
        self.store = Store(
            Path(directory.name) / "institution.db",
            lambda: self.now,
            initial_owner_password="probe-test-password",
        )
        self.token, self.owner = self.store.login("owner", "probe-test-password")

    def grant(self):
        with closing(self.store.connect()) as db, db:
            provider.grant(db, "测试套餐", 100000, "2026-12-31", now=self.now)
            return provider.latest(db)["id"]

    def test_probe_requires_login_active_plan_and_checks_authorization_after_return(
        self,
    ):
        with (
            patch.object(provider, "read_key", return_value="test-credential"),
            patch.object(web_search, "probe") as call,
        ):
            with self.assertRaises(SignedOut):
                network.probe(self.store, None)
            with self.assertRaises(chat.Unavailable):
                network.probe(self.store, self.token)
            call.assert_not_called()
            self.grant()
            call.return_value = {"connected": True, "model": "deepseek-flash"}
            self.assertEqual(
                network.probe(self.store, self.token),
                {
                    **call.return_value,
                    "checkedAt": self.now.isoformat(timespec="seconds"),
                },
            )
            with closing(self.store.connect()) as db:
                self.assertEqual(provider.usage(db, provider.latest(db)["id"]), (0, 0))
                self.assertEqual(
                    db.execute("SELECT count(*) FROM api_search_usage").fetchone()[0], 0
                )

            def disable(_):
                with closing(self.store.connect()) as db, db:
                    provider.disable(db)
                return call.return_value

            call.side_effect = disable
            with self.assertRaises(chat.Unavailable):
                network.probe(self.store, self.token)

    def test_connection_error_does_not_reveal_backend_details_or_hold_probe_slots(self):
        self.grant()
        with patch.object(
            provider, "read_key", side_effect=OSError("/secret/platform/path")
        ):
            with self.assertRaisesRegex(chat.Unavailable, "尚未配置"):
                network.probe(self.store, self.token)
        with (
            patch.object(provider, "read_key", return_value="test-credential"),
            patch.object(
                web_search, "probe", side_effect=web_search.WebSearchError("timeout")
            ),
        ):
            for _ in range(6):
                with self.assertRaisesRegex(chat.Unavailable, "超时"):
                    network.probe(self.store, self.token)

    def test_empty_hits_duplicates_and_late_supplier_reconciliation(self):
        plan = self.grant()
        actor = self.owner["id"]
        with closing(self.store.connect()) as db, db:
            for request, status in [
                ("results", "ok"),
                ("no-results", "empty"),
                ("uncertain", "uncertain"),
            ]:
                search_usage.reserve(db, actor, request, plan, self.now)
                search_usage.settle(db, actor, request, status, self.now)
            with self.assertRaises(ValueError):
                search_usage.reserve(db, actor, "results", plan, self.now)
            self.assertEqual(search_usage.overview(db, plan), dict(calls=1, pending=1))
            search_usage.reconcile(db, actor, "uncertain", 0, self.now)
            search_usage.settle(
                db, actor, "uncertain", "ok", self.now + timedelta(seconds=1)
            )
            self.assertEqual(search_usage.unsettled(db)[0]["needsReview"], 1)
            search_usage.reconcile(
                db, actor, "uncertain", 1, self.now + timedelta(seconds=2)
            )
            search_usage.reconcile(
                db, actor, "uncertain", 1, self.now + timedelta(seconds=3)
            )
            self.assertEqual(search_usage.overview(db, plan), dict(calls=2, pending=0))
            self.assertEqual(search_usage.unsettled(db), [])
            self.assertEqual(provider.usage(db, plan), (0, 0))
            self.assertEqual(
                provider.status(db, self.owner, self.now)["webSearch"],
                dict(calls=2, pending=0),
            )
