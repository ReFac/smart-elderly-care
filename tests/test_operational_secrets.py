from contextlib import closing
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from platform_core import operational_secrets as ops, provider, secure_storage as vault
from platform_core.store import Store


class DeploymentCredentialTests(unittest.TestCase):
    def test_migrated_private_key_external_injection_and_independent_recovery(self):
        with (
            TemporaryDirectory() as temp,
            patch.dict(
                os.environ,
                {
                    "NH_STORAGE_KEY_FILE": "",
                    "NH_PLATFORM_KEY_FILE": "",
                    "NH_DEEPSEEK_KEY_FILE": "",
                    "DEEPSEEK_API_KEY": "",
                    "NH_OWNER_PASSWORD": "fixture-owner-test",
                },
            ),
        ):
            root = Path(temp)
            path = root / "platform" / "operational.sqlite3"
            os.environ["NH_PLATFORM_VAULT"] = str(path)
            legacy = root / "old.key"
            payload = b"fake-unit-test-platform-credential"
            with vault.private_file(legacy) as out:
                out.write(payload + b"\n")
            os.environ["NH_DEEPSEEK_KEY_FILE"] = str(legacy)
            self.assertTrue(provider.configured())
            self.assertEqual(provider.read_key(), payload.decode())
            ops.import_file(path, "deepseek", legacy, remove_source=True)
            self.assertFalse(legacy.exists())
            del os.environ["NH_DEEPSEEK_KEY_FILE"]
            self.assertEqual(provider.read_key(), payload.decode())
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "fixture-injected"}):
                self.assertEqual(provider.read_key(), "fixture-injected")
            self.assertNotIn(payload, path.read_bytes())
            institution = Store(root / "office.sqlite3")
            self.assertNotEqual(
                institution.storage_key_file.read_bytes(),
                ops.key_file(path).read_bytes(),
            )
            point = root / "office.akbak"
            vault.create_snapshot(institution, point)
            restored = root / "recovered.sqlite3"
            vault.restore_snapshot(point, restored, institution.storage_key_file)
            with closing(Store(restored).connect()) as db:
                self.assertFalse(
                    db.execute(
                        "SELECT name FROM sqlite_master WHERE name='secrets'"
                    ).fetchall()
                )
            original_config = b"test-only-opaque-binary=\x00\xff"
            old = root / ".env"
            old.write_bytes(original_config)
            ops.import_file(path, "legacy-app-env", old)
            self.assertEqual(ops.read_value(path, "legacy-app-env"), original_config)
            old.write_bytes(b"unrelated")
            with self.assertRaisesRegex(ValueError, "不同"):
                ops.import_file(path, "legacy-app-env", old, remove_source=True)
            self.assertTrue(old.exists())
            with self.assertRaisesRegex(ValueError, "禁止"):
                ops.import_file(path, "legacy-other", ops.key_file(path), True)
            ops.key_file(path).unlink()
            self.assertFalse(provider.configured())
            with self.assertRaises(ValueError):
                provider.read_key()
