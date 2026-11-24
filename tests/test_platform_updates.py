from base64 import b64encode
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from platform_core import secure_storage, updates
from platform_core.store import Store
from platform_core.update_deploy import protection, restore_previous, unpack_archive


class PlatformUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = Ed25519PrivateKey.generate()
        self.keyfile = self.root / "release.pub"
        self.keyfile.write_bytes(self.key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
        self.store = Store(self.root / "site.db", initial_owner_password="update-test-owner")
        self.token, self.owner = self.store.login("owner", "update-test-owner")
        self.url = "https://releases.example.org/platform/latest.json"

    def signed(self, archive, **override):
        release = {
            "product": "ankang-platform", "format": 1, "version": "0.2.1", "artifact": "release.zip",
            "size": len(archive), "sha256": sha256(archive).hexdigest(), "notes": "测试版本",
            **override,
        }
        return {"release": release, "signature": b64encode(self.key.sign(updates.canonical(release))).decode()}

    def service(self, archive, envelope, **flags):
        def transport(request, *, timeout):
            payload = updates.canonical(envelope) if request.full_url == self.url else archive
            return BytesIO(payload)

        source = updates.ReleaseSource(self.url, self.keyfile, transport=transport)
        return updates.UpdateService(self.store, source, version="0.2.0", **flags)

    def test_owner_can_check_stage_and_schedule_signed_upgrade(self):
        content = b"test archive"
        svc = self.service(content, self.signed(content), managed=True)
        self.assertEqual(svc.check(self.token)["available"]["version"], "0.2.1")
        with self.assertRaisesRegex(ValueError, "先下载"):
            svc.queue(self.token, "0.2.1")
        self.assertEqual(svc.download(self.token, "0.2.1")["stagedVersion"], "0.2.1")
        self.assertEqual(svc.archive("0.2.1").read_bytes(), content)
        self.assertEqual(svc.queue(self.token, "0.2.1")["pendingVersion"], "0.2.1")
        self.assertEqual(updates.read_json(svc.pending)["actor"], self.owner["id"])
        self.assertEqual(svc.queue(self.token, "0.2.1")["pendingVersion"], "0.2.1")

    def test_director_cannot_check_download_install_or_change_policy(self):
        self.store.execute(
            "access.create",
            {
                "kind": "staff", "role": "院长", "username": "branch-director",
                "displayName": "更新权限测试", "password": "local-updates-tests",
            },
            self.store.version(self.token)["revision"], self.token,
        )
        token, _ = self.store.login("branch-director", "local-updates-tests")
        svc = self.service(b"package", self.signed(b"package"), managed=True)
        for operation, args in (
            (svc.status, ()), (svc.check, ()), (svc.download, ("0.2.1",)),
            (svc.queue, ("0.2.1",)), (svc.configure, ({"automatic": True, "hour": 1},)),
        ):
            with self.subTest(operation=operation), self.assertRaises(PermissionError):
                operation(token, *args)
        self.assertFalse(svc.offer.exists())
        self.assertFalse(svc.pending.exists())

    def test_invalid_signatures_integrity_and_downgrade_leave_no_install(self):
        content = b"signed contents"
        tampered = self.signed(content)
        tampered["release"]["notes"] = "不应接受的篡改清单"
        svc = self.service(content, tampered, managed=True)
        with self.assertRaisesRegex(ValueError, "签名验证失败"):
            svc.check(self.token)
        self.assertFalse(svc.offer.exists())
        svc = self.service(b"bad bytes", self.signed(content), managed=True)
        svc.check(self.token)
        with self.assertRaisesRegex(ValueError, "摘要校验失败"):
            svc.download(self.token, "0.2.1")
        self.assertFalse(svc.staged.exists())
        svc = self.service(content, self.signed(content, version="0.1.0"), managed=True)
        self.assertIsNone(svc.check(self.token)["available"])
        with self.assertRaisesRegex(ValueError, "较新的"):
            svc.download(self.token, "0.1.0")

    def test_auto_update_is_opt_in_and_needs_managed_installation(self):
        content = b"release"
        envelope = self.signed(content)
        plain = self.service(content, envelope, managed=False)
        with self.assertRaisesRegex(ValueError, "托管"):
            plain.configure(self.token, {"automatic": True, "hour": 3})
        svc = self.service(content, envelope, managed=True)
        moment = datetime(2026, 11, 25, 3, tzinfo=updates.LOCAL)
        svc.automatic(moment)
        self.assertFalse(svc.pending.exists())
        svc.configure(self.token, {"automatic": True, "hour": 3})
        svc.automatic(moment)
        pending = updates.read_json(svc.pending)
        self.assertEqual(pending["version"], "0.2.1")
        self.assertEqual(pending["actor"], "platform-operator")
        svc.pending.unlink()
        svc.automatic(moment)
        self.assertFalse(svc.pending.exists())

    def test_backup_restores_same_host_sessions_and_catalogs_encrypted_point(self):
        backup = protection(self.store.path, self.owner["id"])
        point = self.store.backups.status(self.token)["points"][0]
        self.assertEqual((point["id"], point["kind"]), (backup["id"], "upgrade"))
        packet = self.store.backups.folder / (backup["id"] + ".akbak")
        self.assertTrue(packet.read_bytes().startswith(secure_storage.MAGIC))
        self.store.logout(self.token)
        restore_previous(self.store.path, backup, self.owner["id"])
        self.assertEqual(self.store.snapshot(self.token)["data"]["user"]["id"], self.owner["id"])
        self.assertEqual(self.store.backups.status(self.token)["points"][0]["kind"], "upgrade")

    def test_archive_has_only_expected_application_members(self):
        archive = self.root / "release.zip"
        with ZipFile(archive, "w") as bundle:
            bundle.writestr("server.py", "pass")
            bundle.writestr("platform_core/store.py", "")
            bundle.writestr("web/index.html", "<html>")
            bundle.writestr("outside.txt", "wrong target")
        with self.assertRaisesRegex(ValueError, "不支持"):
            unpack_archive(archive, self.signed(archive.read_bytes())["release"], self.root / "code")
        self.assertFalse((self.root / "code").exists())
