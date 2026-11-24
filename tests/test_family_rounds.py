"""Authorized household profiles and independent two-party consent for round delivery."""

from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from platform_core import rounds_family, secure_storage
from platform_core.backups import exchange
from platform_core.store import SignedOut, Store


class FamilyRoundTests(unittest.TestCase):
    password = "temporary-account-fixture"

    def setUp(self):
        from provider_fixture import simulate_narration

        simulate_narration(self)
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "trial.sqlite"
        self.now = datetime(2026, 11, 24, 19, tzinfo=ZoneInfo("Asia/Shanghai"))
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": self.password}):
            self.store = Store(self.path, now=lambda: self.now)
        self.owner, _ = self.store.login("owner", self.password)
        self.token, self.family = self.user(
            "daughter", kind="family", residentId="r001"
        )

    def user(self, username, **p):
        self.call(
            self.owner,
            "access.create",
            username=username,
            displayName=username,
            password=self.password,
            **p,
        )
        return self.store.login(username, self.password)

    def call(self, token, action, **p):
        return self.store.execute(
            action, p, self.store.version(token)["revision"], token
        )

    def data(self, token):
        return self.store.snapshot(token)["data"]

    def consent(self, state, actor=None):
        return self.call(
            actor or self.owner,
            "family.consent",
            residentId="r001",
            accountId=self.family["id"],
            enabled=state,
            method="长者当面确认",
            evidence="在接待室逐项核对简报范围",
        )

    def subscription(self, state):
        self.call(self.token, "family.subscribe", residentId="r001", enabled=state)

    def deliver(self, rid="r001", day=None):
        report = {
            "id": "report",
            "residentId": rid,
            "day": day or self.now.date().isoformat(),
            "today": {"planned": 3, "completed": 2, "pending": 1, "overdue": 0},
            "cough": {"status": "elevated", "notes": "内部医学细节"},
            "changes": ["内部医学细节"],
            "suggestions": ["内部工作人员姓名"],
        }
        with closing(self.store.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            state = json.loads(db.execute("SELECT data FROM workspace").fetchone()[0])
            return rounds_family.deliver(db, state, report, self.now)

    def test_independent_consent_dedup_visibility_read_revocation_and_regrant(self):
        sibling, sibling_user = self.user("brother", kind="family", residentId="r001")
        elsewhere, another = self.user(
            "another-family", kind="family", residentId="r002"
        )
        self.assertFalse(self.data(self.token)["familyRoundInbox"]["subscribed"])
        self.subscription(True)
        self.assertEqual(self.deliver(), 0)
        self.consent(True)
        self.assertEqual(self.deliver(day="2026-11-23"), 0)
        self.assertEqual(self.deliver("r002"), 0)
        self.assertEqual([self.deliver(), self.deliver()], [1, 0])
        inbox = self.data(self.token)["familyRoundInbox"]
        self.assertEqual(len(inbox["messages"]), 1)
        message = inbox["messages"][0]
        self.assertEqual(message["today"]["overdue"], 0)
        self.assertTrue(message["coughIncreased"])
        self.assertNotIn("内部", json.dumps(message, ensure_ascii=False))
        self.assertNotIn("familyRoundRecipients", self.data(self.token))
        self.assertFalse(self.data(sibling)["familyRoundInbox"]["messages"])
        self.assertFalse(self.data(elsewhere)["familyRoundInbox"]["messages"])
        for actor, action, p in [
            (sibling, "family.read", dict(residentId="r001", messageId=message["id"])),
            (
                elsewhere,
                "family.read",
                dict(residentId="r001", messageId=message["id"]),
            ),
            (
                self.token,
                "family.subscribe",
                dict(residentId="r001", accountId=sibling_user["id"], enabled=False),
            ),
            (
                self.token,
                "family.consent",
                dict(residentId="r001", accountId=self.family["id"], enabled=True),
            ),
            (
                self.owner,
                "family.consent",
                dict(residentId="r001", accountId=another["id"], enabled=True),
            ),
        ]:
            with self.assertRaises(PermissionError):
                self.call(actor, action, **p)
        self.call(self.token, "family.read", residentId="r001", messageId=message["id"])
        self.assertTrue(
            self.data(self.token)["familyRoundInbox"]["messages"][0]["readAt"]
        )
        for change in [self.consent, self.subscription]:
            change(False)
            self.assertFalse(self.data(self.token)["familyRoundInbox"]["messages"])
            self.assertEqual(self.deliver(), 0)
            with self.assertRaises(PermissionError):
                self.call(
                    self.token,
                    "family.read",
                    residentId="r001",
                    messageId=message["id"],
                )
            change(True)
            self.assertFalse(self.data(self.token)["familyRoundInbox"]["messages"])
        self.assertEqual(self.deliver(), 0)
        self.now = self.now.replace(day=25)
        self.assertEqual(self.deliver(), 1)
        self.assertEqual(
            [m["day"] for m in self.data(self.token)["familyRoundInbox"]["messages"]],
            ["2026-11-25"],
        )

    def test_resident_self_proxy_branch_and_disabled_account(self):
        self_user, _ = self.user(
            "elder", kind="family", residentId="r001", portalSelf=True
        )
        wrong, _ = self.user(
            "another-elder", kind="family", residentId="r002", portalSelf=True
        )
        reader, _ = self.user(
            "kin-reader", kind="staff", role="自定义", permissions=["relatives"]
        )
        proxy, _ = self.user(
            "kin-consent",
            kind="staff",
            role="自定义",
            permissions=["relatives", "family.share"],
        )
        for actor in (reader, wrong):
            with self.assertRaises(PermissionError):
                self.consent(True, actor)
        self.assertNotIn("familyRoundRecipients", self.data(reader))
        self.assertFalse(self.data(wrong)["familyRoundRecipients"])
        self.assertNotIn("familyRoundInbox", self.data(self_user))
        with self.assertRaises(PermissionError):
            self.call(self_user, "family.subscribe", residentId="r001", enabled=True)
        self.consent(True, self_user)
        self.assertEqual(
            self.data(proxy)["familyRoundRecipients"][0]["method"], "长者本人账号确认"
        )
        self.consent(False, proxy)
        self.assertFalse(self.data(self.token)["familyRoundInbox"]["allowed"])
        self.consent(True, proxy)
        self.subscription(True)
        self.assertEqual(self.deliver(), 1)
        self.call(self.owner, "access.update", id=self.family["id"], enabled=False)
        with self.assertRaises(SignedOut):
            self.data(self.token)
        self.call(self.owner, "access.update", id=self.family["id"], enabled=True)
        token, _ = self.store.login("daughter", self.password)
        self.assertEqual(
            self.data(token)["familyRoundInbox"],
            {"allowed": False, "subscribed": False, "messages": []},
        )
        self.call(self.owner, "facility.addCampus", name="测试分院")
        east = self.store.facility_resource(self.owner, "directory")["campuses"][-1][
            "id"
        ]
        local, _ = self.user(
            "branch-recorder",
            kind="staff",
            role="自定义",
            campusId=east,
            permissions=["relatives", "family.share"],
        )
        self.assertFalse(self.data(local)["familyRoundRecipients"])
        with self.assertRaises(PermissionError):
            self.consent(True, local)

    def test_contacts_many_children_roles_history_and_existing_profile(self):
        reader, _ = self.user(
            "no-kin", kind="staff", role="自定义", permissions=["intake", "audit"]
        )

        def save(**p):
            return self.call(
                self.owner, "dossier.profile", residentId="r001", name="测试长者", **p
            )

        save(children="原有自由文本", address="原现住址")

        def add(name, kind, **extra):
            return save(familyContact=dict(name=name, kind=kind, **extra))

        add("配偶甲", "配偶")
        with self.assertRaises(ValueError):
            add("配偶乙", "配偶")
        add(
            "子女甲",
            "子女",
            roles=["推荐联系人", "紧急联系人"],
            phone="13800000000",
            verifiedOn="2026-11-23",
        )
        rev = add("子女乙", "子女", roles=["常用联系人"], phone="021-12345678")[
            "revision"
        ]

        def profile(token):
            return next(
                p
                for p in self.data(token)["dossierProfiles"]
                if p["residentId"] == "r001"
            )

        records = profile(self.owner)
        self.assertEqual(records["children"], "原有自由文本")
        self.assertEqual(records["address"], "原现住址")
        self.assertEqual(len(records["familyMembers"]), 3)
        self.assertEqual(
            records["familyMembers"][1]["roles"], ["推荐联系人", "紧急联系人"]
        )
        self.assertEqual(records["familyMembers"][2]["verifiedOn"], "")
        with self.assertRaises(ValueError):
            add("错误", "其他", roles=["紧急联系人"])
        self.assertNotIn("familyMembers", profile(reader))
        self.assertNotIn(
            "familyMembers", json.dumps(self.data(self.token), ensure_ascii=False)
        )
        with self.assertRaises(PermissionError):
            self.call(
                reader,
                "dossier.profile",
                residentId="r001",
                name="测试长者",
                familyContact={
                    "id": records["familyMembers"][-1]["id"],
                    "remove": True,
                },
            )
        self.assertIn(
            "子女乙",
            json.dumps(self.store.history_change(self.owner, rev), ensure_ascii=False),
        )
        self.assertNotIn(
            "子女乙",
            json.dumps(self.store.history_change(reader, rev), ensure_ascii=False),
        )
        self.store.undo_change(
            self.owner, rev, self.store.version(self.owner)["revision"]
        )
        self.assertEqual(len(profile(self.owner)["familyMembers"]), 2)
        self.assertNotIn(b"13800000000", self.path.read_bytes())

    def apply_archive(self, packet):
        svc = self.store.backups
        with packet.open("rb") as handle:
            plan = exchange.preview_file(svc, self.owner, handle, packet.stat().st_size)
        point = exchange.confirm_import(svc, self.owner, plan["id"])["point"]
        view = exchange.preview_point(svc, self.owner, point)
        self.assertEqual(view["blockers"], [])
        exchange.apply_point(
            svc,
            self.owner,
            point,
            {
                "confirmed": True,
                "approval": view["approval"],
                "revision": view["currentRevision"],
            },
        )

    def test_online_and_disaster_restore_never_reenable_historical_consent(self):
        self.consent(True)
        self.subscription(True)
        self.assertEqual(self.deliver(), 1)
        packet = self.path.with_name("before-revocation.akbak")
        secure_storage.create_snapshot(self.store, packet)
        self.consent(False)
        self.call(
            self.owner,
            "dossier.profile",
            residentId="r001",
            name="测试对象",
            address="用于区分业务版本",
        )
        self.apply_archive(packet)
        self.assertEqual(
            self.data(self.token)["familyRoundInbox"],
            {"allowed": False, "subscribed": True, "messages": []},
        )

        cold = self.path.with_name("recovery.sqlite")
        secure_storage.restore_snapshot(packet, cold, self.store.storage_key_file)
        restored = Store(cold, now=lambda: self.now)
        family = restored.login("daughter", self.password)[0]
        self.assertEqual(
            restored.snapshot(family)["data"]["familyRoundInbox"],
            {"allowed": False, "subscribed": False, "messages": []},
        )
        with closing(restored.connect()) as db:
            self.assertEqual(
                db.execute("SELECT count(*) FROM family_round_messages").fetchone()[0],
                1,
            )
            self.assertIn(
                "接待室",
                db.execute("SELECT evidence FROM family_round_preferences").fetchone()[
                    0
                ],
            )
        owner = restored.login("owner", self.password)[0]
        for token, action, p in [
            (
                owner,
                "family.consent",
                {
                    "accountId": self.family["id"],
                    "method": "长者电话确认",
                    "evidence": "重新征求长者同意",
                },
            ),
            (family, "family.subscribe", {}),
        ]:
            restored.execute(
                action,
                {"residentId": "r001", "enabled": True, **p},
                restored.version(token)["revision"],
                token,
            )
        self.assertFalse(
            restored.snapshot(family)["data"]["familyRoundInbox"]["messages"]
        )

    def test_archive_from_before_family_module_preserves_live_preferences_and_inbox(
        self,
    ):
        self.call(
            self.owner,
            "dossier.profile",
            residentId="r001",
            name="原档案",
            children="历史长女描述",
        )
        # Build an authentic older-format packet from the isolated test institution.
        with closing(self.store.connect()) as db, db:
            db.execute("DROP TRIGGER family_round_unbind")
            db.execute("DROP TABLE family_round_messages")
            db.execute("DROP TABLE family_round_preferences")
        packet = self.path.with_name("pre-feature.akbak")
        secure_storage.create_snapshot(self.store, packet)
        self.store = Store(self.path, now=lambda: self.now)
        self.consent(True)
        self.subscription(True)
        self.assertEqual(self.deliver(), 1)
        expected = self.data(self.token)["familyRoundInbox"]
        self.call(
            self.owner,
            "dossier.profile",
            residentId="r001",
            name="较新档案",
            children="更新描述",
        )
        self.apply_archive(packet)
        self.assertEqual(self.data(self.token)["familyRoundInbox"], expected)
        profile = next(
            p
            for p in self.data(self.owner)["dossierProfiles"]
            if p["residentId"] == "r001"
        )
        self.assertEqual(profile["children"], "历史长女描述")
