"""Deployment configuration stays separate from tenant backups and live connections."""

from contextlib import closing
import json
import os
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from platform_core import deployment_console as deployment, provider
from platform_core.provider import completions
from platform_core.store import Conflict, Store


class DeploymentTests(TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "NH_DEPLOYMENT_MODE": "operator",
                    "NH_DEPLOY_CHAT_ENDPOINTS": "https://llm.example.invalid/v1/chat/completions",
                    "NH_PLATFORM_KEY_FILE": str(self.folder / "vault-key"),
                    "NH_DEEPSEEK_KEY_FILE": str(self.folder / "unused"),
                    "NH_PLATFORM_VAULT": str(self.folder / "operator-vault"),
                },
            )
        )
        self.enterContext(patch.object(completions, "deployed", {}))
        self.store = Store(
            self.folder / "facility.sqlite3",
            initial_owner_password="synthetic-Owner-demo",
        )
        self.token, _ = self.store.login("owner", "synthetic-Owner-demo")
        self.http = SimpleNamespace(
            server_address=("127.0.0.1", 8765), server_port=8765
        )
        self.custom = "https://llm.example.invalid/v1/chat/completions"
        self.config = {
            "provider": "openai",
            "model": "institution-model",
            "endpoint": self.custom,
            "host": "127.0.0.1",
            "port": 8765,
        }
        self.secret = secrets.token_urlsafe(32)

    def save(self, **changes):
        data = {
            "action": "save",
            "revision": 0,
            "config": self.config,
            "policy": "manual",
            "key": self.secret,
            **changes,
        }
        return deployment.configure(self.store, self.token, data, self.http)

    def change(self, action, revision):
        return deployment.configure(
            self.store, self.token, {"action": action, "revision": revision}, self.http
        )

    def test_manual_staging_activation_and_key_redaction(self):
        view = self.save()
        self.assertEqual(view["running"]["provider"], "deepseek")
        self.assertIsNone(deployment.selected_config(self.store.path))
        self.assertEqual(view["draft"]["model"], "institution-model")
        self.assertNotIn(self.secret, json.dumps(view))
        self.assertNotIn(
            self.secret.encode(), deployment.path_for(self.store.path).read_bytes()
        )
        with self.assertRaises(Conflict):
            self.change("arm", 0)
        self.change("arm", 1)
        host, port, config = deployment.start_options(self.store.path, None, None)
        self.assertEqual((host, port), ("127.0.0.1", 8765))
        deployment.activate(self.store.path, config, port)
        self.assertEqual(provider.read_model_key(), self.secret)
        self.assertEqual(
            completions._request(
                "openai", self.secret, {"model": "institution-model", "max_tokens": 8}
            )[0],
            self.custom,
        )
        view = deployment.inspect(self.store, self.token, self.http)
        self.assertIsNone(view["draft"])
        self.assertEqual(view["running"]["endpoint"], self.custom)
        self.assertNotIn(self.secret, json.dumps(view))
        with closing(self.store.connect()) as conn:
            self.assertFalse(
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='secrets'"
                ).fetchone()
            )

    def test_untrusted_endpoint_and_managed_customer_cannot_set_credentials(self):
        with self.assertRaises(ValueError):
            self.save(
                config={**self.config, "endpoint": "https://unapproved.invalid/v1"}
            )
        with self.assertRaises(ValueError):
            self.save(key="")
        self.save()
        with patch.dict(os.environ, NH_DEPLOYMENT_MODE="managed"):
            view = deployment.inspect(self.store, self.token, self.http)
            self.assertIsNone(view["draft"])
            self.assertNotIn("endpoint", view["running"])
            self.assertNotIn(self.custom, json.dumps(view))
            with self.assertRaises(PermissionError):
                self.change("arm", 1)
            self.assertIsNone(deployment.selected_config(self.store.path))
        with patch.object(
            self.store,
            "actor",
            return_value={"kind": "staff", "permissions": ["assistants"]},
        ):
            with self.assertRaises(PermissionError):
                deployment.inspect(self.store, self.token, self.http)
            with self.assertRaises(PermissionError):
                self.save()

    def test_pinned_ports_invalid_listener_and_withdrawal(self):
        self.http.deployment_port_pinned = True
        with self.assertRaises(ValueError):
            self.save(config={**self.config, "port": 9876})
        with self.assertRaises(ValueError):
            self.save(config={**self.config, "host": "0.0.0.0"})
        self.save(policy="next-start")
        self.assertEqual(
            deployment.start_options(self.store.path, 9912, None),
            ("127.0.0.1", 9912, {}),
        )
        self.assertIsNone(self.change("discard", 1)["draft"])
        self.assertIsNone(deployment.selected_config(self.store.path))

    def test_gateway_liveness_requires_device_token_and_rotation_revokes_it(self):
        gateway = {
            "id": "radar-1",
            "transport": "MQTT 网桥",
            "label": "院内网桥",
            "enabled": True,
            "secret": self.secret,
        }
        save = lambda data: deployment.device_settings(
            self.store, self.token, data, self.http
        )
        self.assertEqual(save(gateway)["devices"][0]["status"], "等待首报")

        def beat(key):
            return deployment.heartbeat(self.store.path, gateway["id"], "Bearer " + key)

        with self.assertRaises(PermissionError):
            beat("f" * 40)
        self.assertTrue(beat(self.secret)["accepted"])
        view = deployment.inspect(self.store, self.token, self.http)
        self.assertEqual(view["devices"][0]["status"], "近期收到心跳")
        self.assertNotIn(self.secret, json.dumps(view))
        with patch.object(
            deployment, "time", return_value=view["devices"][0]["lastSeen"] + 300
        ):
            self.assertEqual(
                deployment.inspect(self.store, self.token, self.http)["devices"][0][
                    "status"
                ],
                "心跳超时",
            )
        replacement = secrets.token_urlsafe(32)
        self.assertEqual(
            save({**gateway, "secret": replacement})["devices"][0]["status"], "等待首报"
        )
        with self.assertRaises(PermissionError):
            beat(self.secret)
        save({**gateway, "enabled": False, "secret": ""})
        with self.assertRaises(PermissionError):
            beat(replacement)
