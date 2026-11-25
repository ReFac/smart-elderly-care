from base64 import b64encode
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import os
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from zipfile import ZIP_DEFLATED, ZipFile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

import manage_updates
from platform_core import secure_storage, updates
from platform_core.store import Store
from platform_core.update_deploy import (
    BUNDLED, BUNDLE_ASSETS, Launcher, app_file, protection, restore_previous, unpack_archive,
)


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

    def test_separate_launcher_starts_the_original_installation_and_uses_its_database(self):
        legacy = self.root / "previous"
        (legacy / "platform_core").mkdir(parents=True)
        (legacy / "platform_core/store.py").write_text("")
        old_app = legacy / "server.py"
        old_app.write_text("# 上一版程序")
        seen = []

        def inspect(launcher):
            seen.append((launcher.root, launcher.database, launcher.installed()))
            self.assertEqual(launcher.options, ["--initial-data", "empty"])

        with patch.object(sys, "argv", ["manage_updates.py", "run", "--install-root", str(legacy),
                                        "--initial-data", "empty"]), patch.object(Launcher, "run", inspect):
            manage_updates.main()
        self.assertEqual(seen, [(legacy, legacy / ".local/workspace.sqlite3", (legacy, updates.BASE_VERSION))])
        self.assertEqual(old_app.read_text(), "# 上一版程序")
        with self.assertRaisesRegex(ValueError, "原机构安装"):
            manage_updates.install_root(self.root / "未知安装")

    def test_signed_worker_bundle_runs_from_release_and_previous_release_without_network_install(self):
        key = self.root / "private.pem"
        key.write_bytes(self.key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
        output = self.root / "发布"
        manage_updates.build("0.2.1", output, key, "中文候选版本")
        manifest = updates.ReleaseSource(self.url, self.keyfile).verify(updates.read_json(output / "latest.json"))
        package = output / manifest["artifact"]
        # A legacy launcher cannot admit new signed Python entry points.
        # The operator preflights the same package using the independently deployed launcher.
        with patch.dict(os.environ, NH_UPDATE_MANIFEST_URL=self.url, NH_UPDATE_PUBLIC_KEY_FILE=str(self.keyfile)):
            checked = subprocess.run([sys.executable, str(manage_updates.ROOT / "manage_updates.py"),
                                      "verify-package", "--manifest", str(output / "latest.json")],
                                     capture_output=True, text=True, timeout=20)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("0.2.1", checked.stdout)
        self.assertEqual(manage_updates.install_root(manage_updates.ROOT), manage_updates.ROOT)
        with ZipFile(package) as files:
            names = set(files.namelist())
            self.assertTrue({BUNDLED + asset for asset in BUNDLE_ASSETS} <= names)
            self.assertFalse(any("node_modules" in name or ".local/" in name for name in names))
        # Match the long-running launcher's cwd and isolation while importing
        # the actual newly unpacked application's code at both cutover and rollback.
        script = ("import sys;sys.path.insert(0,sys.argv[1]);"
                  "from platform_core.agents import runtime_assets as r;"
                  "from platform_core.agents import mcp_plugins as m,community_skills as s;"
                  "assert str(r.ROOT)==sys.argv[1];r.verify_candidate();"
                  "assert m.DEFAULT_CONFIG==r.BUNDLED/'workspace-mcp.json';"
                  "assert s.BUNDLED==r.BUNDLED/'skills';"
                  "assert 'mcp_time_get_current_time' in {t['name'] for t in m.catalog({'kind':'owner'})};"
                  "assert s.document_guidance({'kind':'owner'})")
        env = {"PATH": os.environ["PATH"], "LANG": "C.UTF-8", "NH_UPDATE_MANAGED": "1"}
        launcher = Launcher(manage_updates.ROOT, self.store.path, 8765)
        launcher.source = updates.ReleaseSource(self.url, self.keyfile)
        launch = launcher.environment("0.2.1", "自检", None)
        for setting in ("NH_DEERFLOW_PYTHON", "NH_AGENT_RUNTIME_STORE", "PYTHONPATH"):
            if setting in launch:
                env[setting] = launch[setting]

        attempts = []

        def start(folder, version, *, gate=None):
            checked = subprocess.run([sys.executable, "-c", script, str(folder)], cwd=manage_updates.ROOT,
                                     capture_output=True, env=env, timeout=40)
            attempts.append((version, checked.returncode == 0))
            if checked.returncode:
                if version == "0.2.1":
                    self.fail(checked.stderr.decode(errors="replace")[-1500:])
                raise updates.UpdateError("候选运行时未通过启动检查")

        # Exercise the production staging, signature, snapshot, activation and recovery
        # paths. The socket liveness boundary is represented by the real worker probe.
        launcher.process = Mock()
        launcher.process.poll.return_value = 0
        shutil.copyfile(package, launcher.folder / "application-0.2.1.zip")
        updates.atomic_json(launcher.staged, updates.read_json(output / "latest.json"))
        with patch.object(launcher, "start", side_effect=start):
            launcher.install({"version": "0.2.1", "actor": self.owner["id"]})
            self.assertEqual(updates.read_json(launcher.outcome)["state"], "installed")
            newer = launcher.folder / "application-0.2.2.zip"
            with ZipFile(package) as source, ZipFile(newer, "w", ZIP_DEFLATED) as target:
                for name in source.namelist():
                    data = source.read(name)
                    if name == BUNDLED + "deploy/deerflow/requirements.txt":
                        data += b"\n"
                    target.writestr(name, data)
            updates.atomic_json(launcher.staged, self.signed(newer.read_bytes(), version="0.2.2"))
            launcher.install({"version": "0.2.2", "actor": self.owner["id"]})
        outcome = updates.read_json(launcher.outcome)
        self.assertEqual(outcome["state"], "failed")
        self.assertTrue(outcome["snapshotId"])
        self.assertEqual(launcher.installed()[1], "0.2.1")
        self.assertEqual(attempts, [("0.2.1", True), ("0.2.2", False), ("0.2.1", True)])

    def test_missing_worker_source_and_private_or_unlisted_files_are_rejected(self):
        for name in ("web/node_modules/runtime.js", "web/tenant.sqlite3", "web/key.pem",
                     BUNDLED + "skills/xlsx/private.md", BUNDLED + "runtimes/unlisted.js", BUNDLED + "deploy/deerflow/worker.env"):
            self.assertFalse(app_file(name))
        archive = self.root / "release.zip"
        with ZipFile(archive, "w") as files:
            for name in ("server.py", "platform_core/store.py", "web/index.html",
                         "platform_core/agents/deerflow_worker.py"):
                files.writestr(name, "")
        with self.assertRaisesRegex(ValueError, "目录"):
            unpack_archive(archive, self.signed(archive.read_bytes())["release"], self.root / "code")
        self.assertFalse((self.root / "code").exists())
