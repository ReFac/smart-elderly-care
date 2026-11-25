from contextlib import closing
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from platform_core.profile_fields import address_fields, catalog
from platform_core.store import Store, TIMEZONE


class ProfileRegisterTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.now = datetime(2026, 11, 24, 10, tzinfo=TIMEZONE)
        self.path = Path(tmp.name) / "sample.sqlite3"
        self.password = "register-fixture-password"
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": self.password}):
            self.store = Store(self.path, now=lambda: self.now)
        self.owner = self.store.login("owner", self.password)[0]

    def command(self, act, fields, token=None):
        token = token or self.owner
        return self.store.execute(
            act, fields, self.store.version(token)["revision"], token
        )

    def data(self, token=None):
        return self.store.snapshot(token or self.owner)["data"]

    def staff(self, name, permissions):
        self.command(
            "access.create",
            dict(
                kind="staff",
                username=name,
                displayName=name,
                password=self.password,
                role="自定义",
                permissions=permissions,
            ),
        )
        return self.store.login(name, self.password)[0]

    def test_offline_district_street_village_and_reorganization(self):
        tree = catalog("address-regions")
        self.assertEqual(len(tree["CN"]), 34)
        loc = {
            "codes": ["41", "4104", "410482", "410482004", "410482004203"],
            "detail": "10号楼",
        }
        self.assertEqual(
            address_fields(loc)[1],
            "河南省 · 平顶山市 · 汝州市 · 洗耳河街道 · 十里村民委员会 · 10号楼",
        )
        self.assertEqual(
            address_fields(
                {"codes": ["41", "4104"], "detail": "一号楼", "unlisted": "样本新区"}
            )[1],
            "河南省 · 平顶山市 · 样本新区 · 一号楼",
        )
        with self.assertRaises(ValueError):
            address_fields(
                {"codes": ["41", "4104"], "detail": "", "unlisted": "汝州市"}
            )
        self.assertIn("410482108220", tree["410482207"])
        self.assertNotIn("410482108220", tree["410482108"])
        with self.assertRaises(ValueError):
            address_fields({"codes": ["41", "4101", "410482"], "detail": ""})
        with self.assertRaises(ValueError):
            address_fields({"codes": ["41", "4104"], "detail": "十里"})

    def test_structured_values_preserve_and_protect_older_text(self):
        name = self.data()["residents"][0]["name"]
        p = {"residentId": "r001", "name": name}
        self.command(
            "dossier.profile",
            {**p, "address": "原始历史地址", "incomeSource": "旧版原文"},
        )
        self.command(
            "dossier.profile",
            {
                **p,
                "language": "河南方言（汝州）",
                "fundingSources": ["子女支付", "本人支付"],
                "pensionBand": "精确金额",
                "pensionAmount": "2305.8",
                "birthRegion": {"codes": ["41", "4104"]},
                "addressRegion": {
                    "codes": ["41", "4104", "410482", "410482004", "410482004203"],
                    "detail": "十号",
                },
            },
        )
        self.command(
            "dossier.profile",
            {
                **p,
                "familyContact": {
                    "kind": "子女",
                    "name": "甲",
                    "relationship": "儿子",
                    "supportStatus": "提供定期支持",
                    "supportBand": "精确金额",
                    "supportAmount": "500",
                },
            },
        )
        full = self.data()["dossierProfiles"][0]
        self.assertEqual(
            (full["pensionAmount"], full["incomeSource"], full["birthplace"]),
            ("2305.80", "旧版原文", "河南省 · 平顶山市"),
        )
        self.assertEqual(full["familyMembers"][0]["supportAmount"], "500.00")
        self.command(
            "dossier.profile",
            {
                **p,
                "pensionAmount": "2500",
                "addressRegion": {
                    "codes": ["41", "4101", "410102", "410102001", "410102001002"],
                    "detail": "2号",
                },
            },
        )
        corrected = self.data()["dossierProfiles"][0]
        self.assertEqual(corrected["pensionAmount"], "2500.00")
        self.assertIn("碧沙岗社区", corrected["address"])
        self.command("dossier.profile", {**p, "pensionBand": "待核实"})
        self.assertEqual(self.data()["dossierProfiles"][0]["pensionAmount"], "")
        for extra in (
            {"relationship": "配偶"},
            {"supportStatus": "提供定期支持", "supportBand": "无"},
            {
                "supportStatus": "提供不定期支持",
                "supportBand": "精确金额",
                "supportAmount": "0",
            },
        ):
            with self.assertRaises(ValueError):
                self.command(
                    "dossier.profile",
                    {
                        **p,
                        "familyContact": {
                            "kind": "子女",
                            "name": "待核对",
                            "relationship": "女儿",
                            **extra,
                        },
                    },
                )
        staff = self.staff("intake-staff", ["intake", "residents"])
        slim = self.data(staff)["dossierProfiles"][0]
        for private in (
            "familyMembers",
            "pensionBand",
            "pensionAmount",
            "fundingSources",
            "incomeSource",
        ):
            self.assertNotIn(private, slim)
        self.assertEqual(slim["addressRegion"]["codes"][-1], "410102001002")
        with self.assertRaises(PermissionError):
            self.command(
                "dossier.profile", {**p, "fundingSources": ["子女支付"]}, staff
            )
        with self.assertRaises(ValueError):
            self.command("dossier.profile", {**p, "language": "任意伪造选项"})
        self.command("dossier.profile", {**p, "address": "旧客户端更正后的地址"})
        self.assertNotIn("addressRegion", self.data()["dossierProfiles"][0])

    def test_resident_mobile_is_optional_normalized_and_separate_from_family(self):
        base = {"residentId": "r001", "name": "样例长辈"}
        self.command("dossier.profile", {**base, "address": "原登记地址"})
        self.assertNotIn("phone", self.data()["dossierProfiles"][0])
        self.command("dossier.profile", {
            **base, "phone": "＋８６ １３９-００００-０１２３",
            "familyContact": {"kind": "子女", "name": "家属甲", "relationship": "女儿", "phone": "13800000876"},
        })
        profile = self.data()["dossierProfiles"][0]
        self.assertEqual(profile["phone"], "13900000123")
        self.assertEqual(profile["familyMembers"][0]["phone"], "13800000876")
        for invalid in ("0371-60000000", "1234", "老张"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "长辈本人手机号"):
                self.command("dossier.profile", {**base, "phone": invalid})
        self.command("dossier.profile", {**base, "address": "新地址"})
        self.assertEqual(self.data()["dossierProfiles"][0]["phone"], "13900000123")
        self.command("dossier.profile", {**base, "phone": ""})
        profile = self.data()["dossierProfiles"][0]
        self.assertEqual(profile["phone"], "")
        self.assertEqual(profile["familyMembers"][0]["phone"], "13800000876")

    def test_receipt_lifecycle_scope_and_permissions(self):
        clerk = self.staff("ins-clerk", ["longCare"])
        readonly = self.staff("ordinary", ["residents"])
        self.assertIn("longCare", self.data(clerk)["user"]["routes"])
        p = {
            "residentId": "r001",
            "region": {"codes": ["41", "4104", "410482"]},
            "reference": "虚构参保凭证",
            "date": "2026-11-24",
        }

        def add(event, actor=clerk, **extra):
            self.command("ltci.record", {**p, "event": event, **extra}, actor)

        with self.assertRaises(PermissionError):
            add("登记参保", readonly)
        add("登记参保")
        with self.assertRaises(ValueError):
            add("登记待遇核定", service="机构护理", startsOn="2026-11-24")
        add("登记申请")
        add("登记评估结论", grade="3级")
        add(
            "登记待遇核定",
            service="机构护理",
            startsOn="2026-11-20",
            endsOn="2026-12-01",
        )
        rows = self.data(clerk)["longCareEvents"]
        self.assertEqual(rows[-1]["displayStatus"], "待遇有效期内")
        self.assertEqual(len(rows), 4)
        self.assertEqual(self.data(readonly)["longCareEvents"], [])
        with self.assertRaises(ValueError):
            add("登记待遇终止", date="2027-01-01")
        with closing(self.store.connect()) as db:
            self.assertEqual(
                db.execute(
                    "SELECT residentId FROM audit WHERE action='ltci.record' ORDER BY revision DESC"
                ).fetchone()[0],
                "r001",
            )
        target = Store(
            self.path,
            now=lambda: self.now,
            facility_policy=lambda db, user: {"campusIds": ["other-campus"]},
        )
        self.assertEqual(target.snapshot(clerk)["data"]["longCareEvents"], [])
        with self.assertRaises(PermissionError):
            target.execute(
                "ltci.record",
                {**p, "event": "登记待遇终止"},
                target.version(clerk)["revision"],
                clerk,
            )
