"""Exercise the pinned Pi runtime with local Chinese fixtures and no paid model."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from threading import Barrier, Event, Thread
from unittest.mock import patch
import unittest

from platform_core.agents import pi_runtime


class PiLoopTests(unittest.TestCase):
    def test_owner_and_worker_reject_old_node_and_detect_binary_replacement(self):
        with TemporaryDirectory() as temp:
            node = Path(temp, "node")
            node.touch()
            with patch.object(pi_runtime.shutil, "which", return_value=str(node)), patch.object(
                pi_runtime.subprocess, "run", side_effect=[
                    subprocess.CompletedProcess([], 0, stdout=b"v22.18.0\n"),
                    subprocess.CompletedProcess([], 0, stdout=b"v22.19.0\n"),
                ],
            ) as command, patch.object(pi_runtime, "Popen") as worker:
                old = pi_runtime.installation()
                self.assertFalse(old["installed"])
                self.assertFalse(old["nodeSupported"])
                self.assertEqual(old["nodeVersion"], "22.18.0")
                with self.assertRaises(pi_runtime.Unavailable):
                    pi_runtime.Worker()
                worker.assert_not_called()
                self.assertEqual(command.call_count, 1)
                self.assertEqual(command.call_args.kwargs["env"], {})
                node.write_bytes(b"replacement")
                self.assertTrue(pi_runtime.installation()["nodeSupported"])
                self.assertEqual(command.call_count, 2)

    def test_interleaved_turns_share_worker_but_not_observations(self):
        count = 8
        ready = Barrier(count, timeout=8)

        def converse(index):
            observed = []
            body = {
                "model": "中文模拟模型",
                "messages": [{"role": "user", "content": f"查看虚构房间 {index} 的情况"}],
                "tools": [{"type": "function", "function": {
                    "name": "room_read", "description": "读取本人可见房间",
                    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
                }}],
            }

            def model():
                ready.wait()
                return {"calls": [{"id": "r1", "name": "room_read", "arguments": {}}]}

            def read(name, args):
                self.assertEqual((name, args), ("room_read", {}))
                observed.append(index)
                return {"房间": index}

            def answer():
                self.assertEqual(observed, [index])
                return f"已核对房间 {index}"

            pi_runtime.run(body, model, read, answer)
            return observed

        with ThreadPoolExecutor(max_workers=count) as executor:
            self.assertEqual(list(executor.map(converse, range(count))), [[n] for n in range(count)])

    def test_unknown_tool_does_not_run_or_retry_model(self):
        def unexpected(*_):
            self.fail("超范围的工具不得读取记录或继续调用模型")

        with self.assertRaises(ValueError):
            pi_runtime.run(
                {"model": "中文模拟模型", "messages": [{"role": "user", "content": "看看床位"}]},
                lambda: {"calls": [{"id": "x", "name": "unknown", "arguments": {}}]},
                unexpected, unexpected,
            )
        pi_runtime.run({"model": "中文模拟模型", "messages": [{"role": "user", "content": "请重新查询"}]},
                       lambda: {"text": "已查询"}, unexpected, unexpected)

    def test_stalled_callback_expires_without_synthesizing_or_blocking_other_staff(self):
        started, resume = Event(), Event()
        results = []
        body = {"model": "中文模拟模型", "messages": [{"role": "user", "content": "查询授权范围内的库存"}]}

        def slow():
            started.set()
            resume.wait(timeout=3)
            return {"text": "迟到的云端回执"}

        def go():
            try:
                pi_runtime.run(body, slow, self.fail, self.fail)
                results.append("unexpected")
            except pi_runtime.Unavailable:
                results.append("expired")

        with patch.object(pi_runtime, "TURN_SECONDS", .08):
            thread = Thread(target=go)
            thread.start()
            self.assertTrue(started.wait(2))
            pi_runtime.run(body, lambda: {"text": "另一位员工的简报"}, self.fail, self.fail)
            self.assertFalse(resume.wait(.15))
            resume.set()
            thread.join(timeout=3)
        self.assertEqual(results, ["expired"])
