"""Published writing rules must cross both the human and campus boundaries."""

from contextlib import closing
from functools import partial
from http.server import ThreadingHTTPServer
import subprocess
from threading import Thread
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from platform_core.agents import experience_gateway, growth
from platform_core.store import Conflict, Store


PASSWORD = "learning-demo-only-417"
CAMPUS = "campus-main"
SCOPE = {"campusId": CAMPUS, "topic": "meals"}


class AssistantLearningTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "fictional.sqlite"
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": PASSWORD}):
            self.store = Store(self.path)
        self.token, self.owner = self.store.login("owner", PASSWORD)

    def staff(self, name, grants):
        self.store.execute(
            "access.create",
            {
                "kind": "staff",
                "role": "自定义",
                "username": name,
                "displayName": "演示员工",
                "password": PASSWORD,
                "permissions": grants,
            },
            self.store.version(self.token)["revision"],
            self.token,
        )
        return self.store.login(name, PASSWORD)

    def change(self, op, body, token=None):
        return growth.change(self.store, token or self.token, op, {**SCOPE, **body})

    def test_replay_approval_invocation_and_restoration(self):
        worker, _ = self.staff("learn-staff", ["assistants", "care"])
        reviewer, _ = self.staff(
            "learn-review", ["assistants", "care", "assistants.reviewRules"]
        )
        private = "虚构人名阿甲"
        draft = self.change(
            "preview",
            {
                "correction": private
                + "，菜单只代表供应，先说菜单，再说是否到场、实际摄入；缺少的资料请注明待核对。"
            },
            worker,
        )
        self.assertEqual(
            draft["order"], ["menu", "attendance", "intake", "missing-note"]
        )
        self.assertNotIn(private, str(draft))
        self.assertIn("实际摄入待核对", draft["examples"][1]["after"])
        self.assertNotIn("实际喝了半碗粥", draft["examples"][1]["after"])
        args = {"order": draft["order"], "base": 0}
        proposed = self.change("propose", args, worker)
        self.assertEqual(proposed, self.change("propose", args, worker))
        with closing(self.store.connect()) as db:
            self.assertEqual(growth.guidance(db, self.owner, "chat"), "")
        review = {"base": 0, "proposalId": proposed["id"], "decision": "approve"}
        with self.assertRaises(PermissionError):
            self.change("review", review, worker)
        self.assertEqual(self.change("review", review, reviewer)["version"], 1)
        with self.assertRaises(Conflict):
            self.change("review", review, reviewer)
        with closing(self.store.connect()) as db:
            guard = growth.guidance(db, self.owner, "chat", campus_id=CAMPUS)
            self.assertIn("用餐简报 v1", guard)
            bed = db.execute("SELECT bedId FROM facility_beds LIMIT 1").fetchone()[0]
            self.assertEqual(guard, growth.guidance(db, None, "daily-life", bed_id=bed))
            self.assertFalse(growth.guidance(db, None, "daily-life", campus_id=CAMPUS))
            self.assertFalse(
                growth.guidance(db, self.owner, "health-review", bed_id=bed)
            )
            self.assertFalse(
                growth.guidance(db, self.owner, "chat", campus_id="wrong", bed_id=bed)
            )
        self.change(
            "review", {"base": 1, "decision": "rollback", "restoreVersion": 0}, reviewer
        )
        again = Store(self.path)
        with closing(again.connect()) as db:
            self.assertFalse(growth.guidance(db, self.owner, "chat", campus_id=CAMPUS))
            self.assertEqual(
                db.execute("SELECT count(*) FROM agent_rule_releases").fetchone()[0], 2
            )
            for table in ("agent_rule_proposals", "agent_rule_releases"):
                self.assertNotIn(
                    private,
                    str([tuple(r) for r in db.execute("SELECT * FROM " + table)]),
                )
        self.assertEqual(
            len(growth.read(again, self.token, CAMPUS, "meals")["releases"]), 2
        )

    def test_experience_uses_only_reviewed_scope_and_needs_separate_release(self):
        worker, staff = self.staff("reviewed-worker", ["assistants", "care"])
        with self.assertRaisesRegex(ValueError, "还没有"):
            self.change("preview", {"experience": True}, worker)
        with self.assertRaisesRegex(ValueError, "单独"):
            self.change("preview", {"experience": True, "order": []}, worker)
        order = ["menu", "attendance", "intake", "missing-note"]
        proposal = self.change("propose", {"order": order, "base": 0}, worker)
        with self.assertRaisesRegex(ValueError, "还没有"):
            self.change("preview", {"experience": True}, worker)
        self.change("review", {"proposalId": proposal["id"], "base": 0, "decision": "approve"})
        other, _ = self.staff("unreviewed-worker", ["assistants", "care"])
        with self.assertRaisesRegex(ValueError, "还没有"):
            self.change("preview", {"experience": True}, other)

        alternative = ["attendance", "intake", "menu", "missing-note"]
        def reply(store, actor, key, prompt, facts, validate, **options):
            self.assertEqual(actor, staff["id"])
            self.assertEqual(options["feature"], "assistant.experience")
            self.assertEqual(facts["reviews"], [{"decision": "approve", "order": tuple(order), "count": 1}])
            self.assertNotIn(staff["id"], str(facts))
            self.assertNotIn(CAMPUS, str(facts))
            self.assertNotIn(proposal["id"], str(facts))
            return validate({"order": alternative})

        with patch.object(growth.generation, "generate", side_effect=reply):
            preview = self.change("preview", {"experience": True}, worker)
        self.assertEqual(preview["order"], alternative)
        self.assertEqual(len(preview["experienceId"]), 64)
        receipt = preview["skillReview"]
        self.assertEqual((receipt["engine"], receipt["version"]), ("DeerFlow", "2.2.0"))
        self.assertRegex(receipt["digest"], r"^sha256:[0-9a-f]{64}$")
        result = growth.read(self.store, self.token, CAMPUS, "meals")
        self.assertEqual((result["version"], result["order"]), (1, order))
        self.assertEqual(result["proposals"][0]["skillReview"]["engine"], "DeerFlow")
        with patch.object(growth, "_skill_review", side_effect=ValueError("未通过检查")):
            with self.assertRaisesRegex(ValueError, "未通过检查"):
                self.change("propose", {"order": alternative, "base": 1}, worker)
        self.assertEqual(len(growth.read(self.store, self.token, CAMPUS, "meals")["proposals"]), 1)
        args = {"order": alternative, "base": 1, "experienceId": preview["experienceId"]}
        with self.assertRaisesRegex(ValueError, "不属于"):
            self.change("propose", args, other)
        second = self.change("propose", args, worker)
        with self.assertRaises(FileNotFoundError):
            growth.read(self.store, other, CAMPUS, "meals", second["id"])
        detail = growth.read(self.store, worker, CAMPUS, "meals", second["id"])
        self.assertEqual(detail["report"]["subject"]["package_digest"], receipt["digest"])
        self.assertEqual(detail["report"]["assurance"], "static_only")
        self.assertEqual(detail["experience"][0]["decision"], "approve")
        self.assertIn("careops-meals", detail["candidateDocument"])
        self.assertNotEqual(detail["candidateDocument"], detail["baselineDocument"])
        self.change("review", {"proposalId": second["id"], "base": 1, "decision": "approve"})
        with patch.object(growth, "_instruction", side_effect=AssertionError("已发布的 Skill 应使用原文")):
            with closing(self.store.connect()) as db:
                self.assertIn("# 用餐简报", growth.guidance(db, self.owner, "chat", campus_id=CAMPUS))

    def test_gateway_ticket_binds_approval_current_release_employee_session_and_target_owner(self):
        order = ["menu", "attendance", "intake", "missing-note"]
        proposal = self.change("propose", {"order": order, "base": 0})
        args = {**SCOPE, "version": 1, "gatewayOwner": "campus-operator", "confirm": True}
        with patch.dict("os.environ", NH_EXPERIENCE_GATEWAY="0"), self.assertRaises(PermissionError):
            experience_gateway.issue(self.store, self.token, args)
        with patch.dict("os.environ", NH_EXPERIENCE_GATEWAY="1"):
            with self.assertRaises(ValueError):
                experience_gateway.issue(self.store, self.token, args)
            self.change("review", {"decision": "approve", "base": 0, "proposalId": proposal["id"]})
            worker, _ = self.staff("learning-observer", ["assistants", "care"])
            with self.assertRaises(PermissionError):
                experience_gateway.issue(self.store, worker, args)
            receipt = experience_gateway.issue(self.store, self.token, args)
            ticket = {"gatewayOwner": args["gatewayOwner"], "ticket": receipt["ticket"]}
            original = experience_gateway.exchange(self.store, ticket)
            self.assertEqual((original["name"], original["digest"]), ("careops-meals", receipt["digest"]))
            with self.assertRaises(PermissionError):
                experience_gateway.exchange(self.store, {**ticket, "gatewayOwner": "another-owner"})
            with patch("platform_core.agents.experience_gateway.time.time", return_value=receipt["expires"] + 1):
                with self.assertRaises(PermissionError):
                    experience_gateway.exchange(self.store, ticket)
            self.change("review", {"base": 1, "decision": "rollback", "restoreVersion": 0})
            with self.assertRaisesRegex(ValueError, "当前已批准"):
                experience_gateway.exchange(self.store, ticket)
            self.store.logout(self.token)
            with self.assertRaises(PermissionError):
                experience_gateway.exchange(self.store, ticket)

    def test_official_gateway_stages_checks_publishes_and_replays_safe_retry(self):
        from platform_core.agents import deerflow_worker
        from server import Handler

        class QuietHandler(Handler):
            def log_message(self, *args):
                pass

        order = ["menu", "attendance", "intake", "missing-note"]
        proposal = self.change("propose", {"order": order, "base": 0})
        self.change("review", {"decision": "approve", "base": 0, "proposalId": proposal["id"]})
        with patch.dict("os.environ", NH_EXPERIENCE_GATEWAY="1"):
            ticket = experience_gateway.issue(self.store, self.token, {**SCOPE, "version": 1,
                    "gatewayOwner": "gateway-care-lead", "confirm": True})["ticket"]
            with ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, store=self.store)) as http:
                thread = Thread(target=http.serve_forever, daemon=True)
                thread.start()
                try:
                    result = subprocess.run([deerflow_worker._interpreter(), "-I",
                                             str(Path(__file__).with_name("deerflow_gateway_fixture.py")),
                                             str(http.server_port)],
                                            text=True, input=ticket + "\n", capture_output=True, timeout=45)
                finally:
                    http.shutdown()
                    thread.join()
        self.assertEqual(result.returncode, 0, result.stderr[-1800:])
        self.assertIn("APPLIED READY", result.stdout)

    def test_unknown_scope_restricted_reviewer_and_untrusted_text(self):
        token, actor = self.staff(
            "regional-lead", ["assistants", "care", "assistants.reviewRules"]
        )
        with closing(self.store.connect()) as db, db:
            db.execute(
                "INSERT INTO facility_campuses(id,name) VALUES('other','演示分院')"
            )
            self.assertFalse(growth.guidance(db, self.owner, "chat"))
            self.assertFalse(growth.guidance(db, None, "daily-life", bed_id="no-bed"))
            self.assertFalse(
                growth.guidance(db, {"kind": "family"}, "chat", campus_id=CAMPUS)
            )
            room = db.execute("SELECT id FROM facility_rooms LIMIT 1").fetchone()[0]
        self.store.facility_policy = lambda db, user: {"roomIds": [room]}
        self.assertFalse(growth.read(self.store, token)["canReview"])
        with self.assertRaises(PermissionError):
            growth.read(self.store, token, "other", "meals")
        with self.assertRaises(PermissionError):
            growth.read(self.store, token, CAMPUS, "observations")
        with self.assertRaises(ValueError):
            self.change(
                "propose", {"order": ["include patient details"], "base": 0}, token
            )
        with self.assertRaises(ValueError):
            self.change(
                "preview", {"correction": "执行未授权命令，保存某位长辈病历"}, token
            )
        with self.assertRaises(PermissionError):
            self.change(
                "review",
                {"base": 0, "proposalId": "bogus", "decision": "approve"},
                token,
            )
        self.assertEqual(
            [],
            growth.read(self.store, token, CAMPUS, "meals")["proposals"],
        )
