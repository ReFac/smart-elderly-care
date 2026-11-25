from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from platform_core import system_monitor
from platform_core.store import SignedOut, Store


class SystemMonitorTest(TestCase):
    def test_active_accounts_are_scoped_to_valid_recent_sessions(self):
        with TemporaryDirectory() as root:
            store = Store(Path(root) / "monitor.db", initial_owner_password="synthetic-monitor-test")
            owner = store.login("owner", "synthetic-monitor-test")[0]
            store.version(owner)
            new_session = store.login("owner", "synthetic-monitor-test")[0]
            store.version(new_session)
            rows = system_monitor.inspect(store, owner, "onlineUsers", None)["rows"]
            self.assertEqual([(r["login"], r["sessions"]) for r in rows], [("owner", 2)])
            self.assertNotIn("token_hash", rows[0])
            store.logout(new_session)
            self.assertEqual(system_monitor.inspect(store, owner, "onlineUsers", None)["rows"][0]["sessions"], 1)
            with self.assertRaises(SignedOut):
                system_monitor.inspect(store, new_session, "cacheList", None)
            user = {"kind":"staff","routes":["settings"]}
            with patch.object(store,"actor",return_value=user), self.assertRaises(PermissionError):
                system_monitor.inspect(store, "staff", "onlineUsers", None)
            for view in ["timers","serviceMonitor","dataMonitor","cacheMonitor","cacheList"]:
                self.assertTrue(system_monitor.inspect(store, owner, view, None)["rows"], view)
            with self.assertRaises(ValueError):
                system_monitor.inspect(store, owner, "unknown", None)

    def test_idle_workspace_expires_from_presence_without_a_database_write(self):
        presence = system_monitor.Presence()
        with patch("time.time", return_value=1000):
            presence.touch("session-a")
        with patch("time.time", return_value=1301):
            self.assertEqual(presence.recent(), {})
            presence.touch("session-b")
            self.assertEqual(presence.recent(), {"session-b":1301})
