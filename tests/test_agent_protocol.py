"""A2A official client interoperability, replay, scoped reads and persistence."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from functools import partial
from http.server import ThreadingHTTPServer
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch

from release_scope import international_only

from platform_core.agents import agent_protocol
from platform_core.store import Store
from server import Handler


def rpc(method, params, rid="r1"):
    return {"jsonrpc": "2.0", "method": method, "params": params, "id": rid}


def message(text="bed-availability", mid="m1"):
    return {"message": {"messageId": mid, "role": "ROLE_USER", "parts": [{"text": text}]}}


@unittest.skipUnless(find_spec("a2a"), "install requirements-a2a.txt to exercise the A2A endpoint")
class A2ATests(unittest.TestCase):
    def setUp(self):
        self.scratch = TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.path = Path(self.scratch.name) / "service.sqlite3"
        self.password = "fixture-protocol-owner-2026"
        self.store = Store(self.path, initial_owner_password=self.password)
        self.owner = self.store.login("owner", self.password)[0]

    def invoke(self, method, params, rid="r1", actor=None):
        return agent_protocol.dispatch(self.store, actor or self.owner, rpc(method, params, rid))

    def test_parallel_idempotency_replay_conflict_and_restart(self):
        def send(index):
            return self.invoke("SendMessage", message(), rid=index)["result"]["task"]
        with ThreadPoolExecutor(3) as pool:
            tasks = list(pool.map(send, (1, 2, 3, 1)))
        self.assertTrue(all(task == tasks[0] for task in tasks))
        with closing(self.store.connect()) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM a2a_tasks").fetchone()[0], 1)
        self.assertEqual(self.invoke("SendMessage", message("today-care-work"), 4)["error"]["code"], -32602)
        self.assertEqual(self.invoke("SendMessage", message(mid="other"), 1)["error"]["code"], -32602)
        self.store = Store(self.path)
        self.assertEqual(self.invoke("GetTask", {"id":tasks[0]["id"]})["result"], tasks[0])
        self.assertEqual(self.invoke("CancelTask", {"id":tasks[0]["id"]})["error"]["code"], -32002)

    def test_scope_actor_tenant_and_unsupported_content(self):
        self.store.execute("access.create", {"username":"protocol-staff", "displayName":"查询员工", "role":"自定义",
                           "kind":"staff", "permissions":["assistants","care"], "password":self.password},
                           self.store.version(self.owner)["revision"], self.owner)
        staff, person = self.store.login("protocol-staff", self.password)
        args = self.invoke("SendMessage", message("today-care-work"), actor=staff)["result"]["task"]
        self.assertIn("照护工单", args["artifacts"][0]["parts"][0]["text"])
        self.assertEqual(self.invoke("GetTask", {"id":args["id"]})["error"]["code"], -32001)
        with closing(self.store.connect()) as db, db:
            db.execute("UPDATE facility_site SET id='other-site' WHERE singleton=1")
        self.assertEqual(self.invoke("GetTask", {"id":args["id"]}, actor=staff)["error"]["code"], -32001)
        for payload in ({**message(), "tenant":"another"}, {**message(), "metadata":{"residentId":"x"}},
                        {"message":{**message()["message"], "taskId":args["id"]}}):
            self.assertEqual(self.invoke("SendMessage", payload)["error"]["code"], -32602)
        self.assertEqual(self.invoke("SendMessage", message("办理退住"))["error"]["code"], -32004)
        self.assertEqual(self.invoke("SendMessage", {"message":{**message()["message"], "parts":[{"url":"https://invalid"}]}})["error"]["code"], -32005)
        old = self.invoke("SendMessage", message("today-care-work","changed"), actor=staff)["result"]["task"]
        self.store.execute("access.update", {"id":person["id"], "permissions":["assistants","care","clinical"]},
                           self.store.version(self.owner)["revision"], self.owner)
        staff = self.store.login("protocol-staff", self.password)[0]
        self.assertEqual(self.invoke("GetTask", {"id":old["id"]}, actor=staff)["error"]["code"], -32001)

    @international_only
    def test_international_locales_share_protocol_capabilities(self):
        for lang in ("fr", "es"):
            with self.subTest(language=lang), patch.dict("os.environ", {"NH_DEPLOYMENT_LANGUAGE":lang}):
                store = Store(self.path.with_name(lang + ".sqlite3"), initial_owner_password=self.password)
                token = store.login("owner", self.password)[0]
                card = agent_protocol.agent_card("https://example.test", store.deployment_edition)
                self.assertEqual(card["skills"][0]["name"], "Bed availability")
                task = agent_protocol.dispatch(store, token, rpc("SendMessage", message()))["result"]["task"]
                self.assertIn("visible beds", task["artifacts"][0]["parts"][0]["text"])

    def test_official_client_over_http(self):
        import httpx
        from a2a.client import ClientConfig
        from a2a.client.client_factory import create_client
        from a2a.types import a2a_pb2 as wire
        from google.protobuf.json_format import ParseDict

        class QuietHandler(Handler):
            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, store=self.store)) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            async def scenario():
                url = f"http://127.0.0.1:{server.server_port}"
                async with httpx.AsyncClient(base_url=url, trust_env=False) as http:
                    client = await create_client(url, ClientConfig(httpx_client=http, streaming=False))
                    anon = await http.post("/api/a2a", json=rpc("SendMessage", message()))
                    self.assertEqual(anon.status_code, 401)
                    auth = await http.post("/api/auth/login", json={"username":"owner","password":self.password})
                    auth.raise_for_status()
                    saved = []
                    async for event in client.send_message(ParseDict(message(), wire.SendMessageRequest())):
                        saved.append(event.task)
                    self.assertEqual(len(saved), 1)
                    task = await client.get_task(wire.GetTaskRequest(id=saved[0].id))
                    self.assertEqual(task, saved[0])
                    self.assertEqual(task.status.state, wire.TASK_STATE_COMPLETED)
                    self.assertIn("床位", task.artifacts[0].parts[0].text)
                    invalid = await http.post("/api/a2a", json=rpc("GetTask", {"id":task.id}), headers={"A2A-Version":"0.3"})
                    self.assertEqual(invalid.json()["error"]["code"], -32009)
                    await http.post("/api/auth/logout", json={})
                    self.assertEqual((await http.post("/api/a2a", json=rpc("GetTask", {"id":task.id}))).status_code, 401)
            try:
                asyncio.run(scenario())
            finally:
                server.shutdown()
                thread.join()
