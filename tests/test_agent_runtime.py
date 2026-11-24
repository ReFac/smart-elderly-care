"""Exercise agent approval checkpoints through authenticated, file-backed workspaces."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from io import BytesIO
import json
from pathlib import Path
import tempfile
from threading import Barrier
import unittest
from unittest.mock import Mock, patch

from server import Handler
from platform_core.agents import runtime
from platform_core.store import Conflict, Store, TIMEZONE


PASSWORD = "agent-test-local-417"


class AgentRuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "agent.sqlite"
        self.now = datetime(2026, 11, 24, 10, tzinfo=TIMEZONE)
        with patch.dict("os.environ", {"NH_OWNER_PASSWORD": PASSWORD}):
            self.store = Store(self.path, lambda: self.now)
        self.owner, _ = self.store.login("owner", PASSWORD)

    def command(self, actor, action, payload):
        revision = self.store.version(actor)["revision"]
        return self.store.execute(action, payload, revision, actor)

    def create_staff(self, username, permissions):
        self.command(
            self.owner,
            "access.create",
            {
                "kind": "staff",
                "role": "自定义",
                "username": username,
                "displayName": username,
                "password": PASSWORD,
                "permissions": permissions,
            },
        )
        return self.store.login(username, PASSWORD)

    def start(self, actor, **payload):
        self.command(
            actor,
            "agent.start",
            {
                "goal": "复核护理和库存",
                "requestId": "handover-01",
                **payload,
            },
        )
        return self.store.snapshot(actor)["data"]["agentRuns"][0]["id"]

    def detail(self, actor, run_id):
        return self.store.agent_resource(actor, "runs", run_id)

    def test_two_domains_leave_source_references_and_resume_after_restart(self):
        token, _ = self.create_staff("coordinator", ["assistants", "care", "inventory"])
        before = self.store.snapshot(token)
        run_id = self.start(token, residentId="r001")
        paused = self.detail(token, run_id)
        self.assertEqual(paused["status"], "awaiting_approval")
        self.assertEqual(paused["sourceRevision"], before["revision"])
        self.assertCountEqual(paused["agents"], ["care", "inventory"])
        self.assertEqual(
            self.store.snapshot(token)["data"]["suggestions"],
            before["data"]["suggestions"],
        )
        events = paused["events"]
        self.assertEqual([e["seq"] for e in events], list(range(1, len(events) + 1)))
        self.assertEqual(events[0]["event"], "run.started")
        self.assertEqual(events[-1]["event"], "approval.requested")
        self.assertCountEqual(
            [
                (e["agent"], e["message"], e["parent"])
                for e in events
                if e["event"] == "tool.called"
            ],
            [
                ("care", "care.review", "coordinator"),
                ("inventory", "stock.review", "coordinator"),
            ],
        )
        allowed_sources = {
            "care": {"residents", "assessments", "tasks"},
            "inventory": {"inventory", "transactions"},
        }
        for artifact in paused["artifacts"]:
            self.assertTrue(artifact["evidence"])
            self.assertTrue(any(ref["recordIds"] for ref in artifact["evidence"]))
            for ref in artifact["evidence"]:
                self.assertIn(ref["source"], allowed_sources[artifact["agent"]])
                records = before["data"][ref["source"]]
                self.assertTrue(set(ref["recordIds"]) <= {r["id"] for r in records})
        self.store = Store(self.path, lambda: self.now)
        self.assertEqual(self.detail(token, run_id), paused)
        self.command(token, "agent.publish", {"runId": run_id})
        published = self.detail(token, run_id)
        self.assertEqual(published["status"], "published")
        self.assertEqual(published["events"][-1]["event"], "run.published")
        after = self.store.snapshot(self.owner)
        suggestions = [
            s for s in after["data"]["suggestions"] if s.get("runId") == run_id
        ]
        self.assertCountEqual([s["agent"] for s in suggestions], ["care", "inventory"])
        self.assertTrue(all(s["status"] == "待审核" for s in suggestions))
        self.assertEqual(after["audit"][0]["action"], "agent.publish")

    def test_retries_cancellation_and_conflicting_request_ids(self):
        a = self.start(self.owner)
        original = self.detail(self.owner, a)
        self.assertEqual(a, self.start(self.owner))
        self.assertEqual(self.detail(self.owner, a), original)
        with self.assertRaises(ValueError):
            self.start(self.owner, goal="另一项审核")
        self.command(self.owner, "agent.cancel", {"runId": a})
        for action in ("agent.cancel", "agent.publish"):
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.command(self.owner, action, {"runId": a})
        self.assertEqual(
            self.detail(self.owner, a)["events"][-1]["event"], "run.cancelled"
        )
        data = self.store.snapshot(self.owner)["data"]
        self.assertFalse(any(s.get("runId") == a for s in data["suggestions"]))

    def test_concurrent_publish_commits_once_and_replay_cannot_duplicate(self):
        run_id = self.start(self.owner)
        revision = self.store.version(self.owner)["revision"]
        barrier = Barrier(2)

        def publish():
            barrier.wait(timeout=10)
            try:
                self.store.execute(
                    "agent.publish", {"runId": run_id}, revision, self.owner
                )
            except Conflict:
                return "conflict"
            return "published"

        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(publish) for _ in range(2)]
            self.assertCountEqual(
                [f.result(timeout=15) for f in futures], ["published", "conflict"]
            )
        with self.assertRaises(ValueError):
            self.command(self.owner, "agent.publish", {"runId": run_id})
        events = self.detail(self.owner, run_id)["events"]
        self.assertEqual(sum(e["event"] == "run.published" for e in events), 1)
        after = self.store.snapshot(self.owner)
        self.assertEqual(after["revision"], revision + 1)
        rows = [s for s in after["data"]["suggestions"] if s.get("runId") == run_id]
        self.assertCountEqual([s["agent"] for s in rows], ["care", "inventory"])

    def test_actor_scope_and_revocation_on_an_existing_session(self):
        token, actor = self.create_staff("lead", ["assistants", "care", "inventory"])
        other, _ = self.create_staff("peer", ["assistants", "care", "inventory"])
        run_id = self.start(token)
        with self.assertRaises(FileNotFoundError):
            self.detail(other, run_id)
        self.assertFalse(self.store.snapshot(other)["data"]["agentRuns"])
        self.command(
            self.owner,
            "access.update",
            {"id": actor["id"], "permissions": ["assistants", "inventory"]},
        )
        caps = self.store.agent_resource(token, "capabilities")
        self.assertEqual([t["id"] for t in caps["tools"]], ["stock.review"])
        self.assertNotIn("deepseek-planner", {a["id"] for a in caps["adapters"]})
        self.assertFalse(self.store.snapshot(token)["data"]["agentRuns"])
        for call in (
            lambda: self.detail(token, run_id),
            lambda: self.command(token, "agent.publish", {"runId": run_id}),
            lambda: self.command(token, "agent.cancel", {"runId": run_id}),
        ):
            with self.assertRaises((FileNotFoundError, PermissionError)):
                call()
        self.assertEqual(self.detail(self.owner, run_id)["status"], "awaiting_approval")
        self.command(
            self.owner,
            "access.update",
            {"id": actor["id"], "permissions": ["inventory"]},
        )
        with self.assertRaises(PermissionError):
            self.store.agent_resource(token, "capabilities")

    def test_planner_cannot_invent_tools_expand_its_grants_or_exceed_budget(self):
        token, _ = self.create_staff("limited", ["assistants", "inventory"])
        before = self.store.snapshot(token)
        for plan, exception in (
            (["unregistered"], PermissionError),
            (["inventory", "finance"], PermissionError),
            (["inventory", "inventory"], ValueError),
            (["inventory"] * 4, ValueError),
            ([], ValueError),
        ):
            with (
                self.subTest(plan=plan),
                patch.object(runtime.LocalPlanner, "plan", return_value=plan),
                patch.object(runtime.LocalTools, "collect") as tool,
                self.assertRaises(exception),
            ):
                self.start(token)
            tool.assert_not_called()
        self.assertEqual(before, self.store.snapshot(token))

    def test_providers_receive_scoped_copies_and_cannot_mutate_sources(self):
        token, _ = self.create_staff("care-only", ["assistants", "care"])
        original = runtime.LocalTools.collect
        before = self.store.snapshot(self.owner)["data"]
        self.assertTrue(any("contact" in r for r in before["residents"]))

        def observe(provider, specialist, records, resident_id, day):
            self.assertEqual(set(records), {"residents", "assessments", "tasks"})
            self.assertTrue(
                all(
                    "contact" not in r and "allergies" not in r
                    for r in records["residents"]
                )
            )
            artifact = original(provider, specialist, records, resident_id, day)
            records["tasks"].clear()
            return artifact

        with patch.object(runtime.LocalTools, "collect", observe):
            run_id = self.start(token, goal="护理交班")
        self.assertEqual(self.detail(token, run_id)["status"], "awaiting_approval")
        self.assertEqual(
            before["tasks"], self.store.snapshot(self.owner)["data"]["tasks"]
        )

    def test_tool_cannot_forge_identity_citation_or_business_fields(self):
        actor, _ = self.create_staff("care-tool", ["assistants", "care"])
        before = self.store.snapshot(self.owner)
        original = runtime.LocalTools.collect
        fixture = before["data"]
        other_task = next(
            t["id"] for t in fixture["tasks"] if t["residentId"] != "r001"
        )
        cases = [
            ("agent", {"agent": "finance"}, PermissionError),
            ("tool", {"tool": "stock.review"}, PermissionError),
            ("category", {"category": "运营分析"}, PermissionError),
            ("resident", {"residentId": "r002"}, PermissionError),
            ("write", {"status": "已采纳"}, ValueError),
            ("nested text", {"detail": {"action": "care.completeTask"}}, ValueError),
            (
                "wrong domain",
                {
                    "evidence": [
                        {
                            "source": "bills",
                            "label": "",
                            "value": "",
                            "recordIds": [fixture["bills"][0]["id"]],
                        }
                    ]
                },
                PermissionError,
            ),
            (
                "wrong resident",
                {
                    "evidence": [
                        {
                            "source": "tasks",
                            "label": "",
                            "value": "",
                            "recordIds": [other_task],
                        }
                    ]
                },
                PermissionError,
            ),
            (
                "fabricated row",
                {
                    "evidence": [
                        {
                            "source": "tasks",
                            "label": "",
                            "value": "",
                            "recordIds": ["invented-task"],
                        }
                    ]
                },
                PermissionError,
            ),
            (
                "extra evidence fields",
                {
                    "evidence": [
                        {
                            "source": "tasks",
                            "label": "",
                            "value": "",
                            "recordIds": [],
                            "private": "extra",
                        }
                    ]
                },
                ValueError,
            ),
        ]
        for label, forged, expected in cases:

            def altered(provider, specialist, rows, target, day):
                artifact = original(provider, specialist, rows, target, day)
                # The provider can alter its input copy. Its original grant must still govern references.
                rows["tasks"].append({"id": "invented-task"})
                return {**artifact, **forged}

            with (
                self.subTest(label=label),
                patch.object(runtime.LocalTools, "collect", altered),
                self.assertRaises(expected),
            ):
                self.start(actor, goal="照护任务", residentId="r001")
        self.assertEqual(self.store.snapshot(self.owner), before)

    def test_one_specialist_cannot_rewrite_an_accepted_artifact(self):
        original = runtime.LocalTools.collect
        received = {}

        def observe(provider, specialist, rows, target, day):
            received[specialist.key] = target
            if specialist.key == "inventory":
                cached["agent"] = "finance"
                cached["evidence"][0]["recordIds"].append("later-injected")
            artifact = original(provider, specialist, rows, target, day)
            if specialist.key == "care":
                cached.update(artifact)
                return cached
            return artifact

        cached = {}
        with patch.object(runtime.LocalTools, "collect", observe):
            run_id = self.start(self.owner, residentId="r001")
        self.assertEqual(received, {"care": "r001", "inventory": ""})
        care, _ = self.detail(self.owner, run_id)["artifacts"]
        self.assertEqual(care["agent"], "care")
        self.assertEqual(care["evidence"][0]["recordIds"], ["r001"])

    def test_second_tool_failure_rolls_back_first_tool_and_allows_retry(self):
        before = self.store.snapshot(self.owner)
        original = runtime.LocalTools.collect
        called = []

        def fail_second(provider, specialist, records, resident_id, day):
            called.append(specialist.key)
            if specialist.key == "inventory":
                raise ValueError("工具暂不可用")
            return original(provider, specialist, records, resident_id, day)

        with (
            patch.object(runtime.LocalTools, "collect", fail_second),
            self.assertRaises(ValueError),
        ):
            self.start(self.owner)
        self.assertEqual(called, ["care", "inventory"])
        self.assertEqual(self.store.snapshot(self.owner), before)
        run_id = self.start(self.owner)
        self.assertEqual(self.detail(self.owner, run_id)["status"], "awaiting_approval")

    def test_http_contract_and_reserved_adapters_are_role_scoped(self):
        def request(method, path, token, payload=None):
            # Transport stays in memory, while the production HTTP parser, dispatcher
            # and authenticated SQLite backend handle the entire request.
            body = json.dumps(payload or {}).encode() if method == "POST" else b""
            headers = [
                f"{method} {path} HTTP/1.0",
                "Host: localhost",
                "Content-Type: application/json",
                f"Content-Length: {len(body)}",
            ]
            if token:
                headers.append("Cookie: nh_session=" + token)
            raw = ("\r\n".join(headers) + "\r\n\r\n").encode() + body
            conn = Mock()
            conn.makefile.return_value = BytesIO(raw)
            output = BytesIO()
            conn.sendall.side_effect = output.write
            with patch.object(Handler, "log_request"):
                Handler(conn, ("127.0.0.1", 10000), object(), store=self.store)
            head, answer = output.getvalue().split(b"\r\n\r\n", 1)
            return int(head.split(b" ", 2)[1]), json.loads(answer)

        caps_path = "/api/agent/capabilities"
        self.assertEqual(request("GET", caps_path, None)[0], 401)
        code, caps = request("GET", caps_path, self.owner)
        self.assertEqual(code, 200)
        self.assertEqual(caps["runtime"], "local-rules")
        self.assertEqual(
            {a["id"] for a in caps["adapters"]},
            {"mcp-tools", "a2a-delegate", "trace-export"},
        )
        for adapter in caps["adapters"]:
            code, answer = request("POST", adapter["path"], self.owner)
            self.assertEqual(code, 501)
            self.assertEqual(answer["status"], "not_connected")
        staff, _ = self.create_staff("stock-reader", ["inventory", "assistants"])
        self.assertEqual(
            request("POST", "/api/agent/adapters/deepseek-planner", staff)[0], 404
        )
        code, _ = request(
            "POST",
            "/api/commands",
            staff,
            {
                "revision": self.store.version(staff)["revision"],
                "action": "agent.start",
                "payload": {
                    "requestId": "http-stock",
                    "scope": "inventory",
                    "goal": "检查库存",
                },
            },
        )
        self.assertEqual(code, 200)
        code, runs = request("GET", "/api/agent/runs", staff)
        self.assertEqual(code, 200)
        code, run = request("GET", "/api/agent/runs/" + runs["runs"][0]["id"], staff)
        self.assertEqual(code, 200)
        self.assertEqual(run["artifacts"][0]["tool"], "stock.review")
