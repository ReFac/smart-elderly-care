"""Exercise DeerFlow’s conversation graph with local Chinese fixtures and no paid model."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, BrokenBarrierError, Event, Thread
from unittest.mock import patch
import unittest

from platform_core.agents import deerflow_chat


class DeerFlowConversationTests(unittest.TestCase):
    def test_oversized_request_leaves_shared_worker_usable(self):
        worker = deerflow_chat._current()
        with self.assertRaisesRegex(ValueError, "请求过大"):
            deerflow_chat.capability("read_skill", {"name": "测试", "source": "栏" * 400000})
        deerflow_chat.run({}, lambda: {"text": "同一进程继续处理"}, self.fail, self.fail)
        self.assertIs(deerflow_chat._current(), worker)

    def test_graph_calls_tools_across_rounds_and_stops_at_the_total_limit(self):
        spec = {"type": "function", "function": {"name": "read_section", "description": "读取指定章节",
                "parameters": {"type": "object", "properties": {"section": {"type": "integer"}},
                               "required": ["section"], "additionalProperties": False}}}
        observed = []

        def next_section():
            index = len(observed) + 1
            return {"calls": [{"id": str(index), "name": "read_section", "arguments": {"section": index}}]}

        with self.assertRaisesRegex(ValueError, "上限"):
            deerflow_chat.run({"tools": [spec]}, next_section,
                              lambda _, args: observed.append(args["section"]), next_section)
        self.assertEqual(observed, [1, 2, 3])

    def test_native_loop_guard_blocks_the_second_identical_read(self):
        spec = {"type": "function", "function": {"name": "read_once", "description": "读取一次资料",
                                                 "parameters": {"type": "object", "properties": {}}}}
        executed = []
        def decision():
            return {"calls": [{"id": str(len(executed) + 1), "name": "read_once", "arguments": {}}]}
        with self.assertRaisesRegex(ValueError, "停止重复"):
            deerflow_chat.run({"tools": [spec]}, decision, lambda name, args: executed.append(name), decision)
        self.assertEqual(executed, ["read_once"])

    def test_interleaved_turns_share_worker_but_not_observations(self):
        count = 16
        ready = Barrier(count + 1, timeout=30)
        resume = Event()

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
                if not resume.wait(30):
                    self.fail("等待核对并发上限超时")
                return {"calls": [{"id": "r1", "name": "room_read", "arguments": {}}]}

            def read(name, args):
                self.assertEqual((name, args), ("room_read", {}))
                observed.append(index)
                return {"房间": index}

            def answer():
                self.assertEqual(observed, [index])
                return f"已核对房间 {index}"

            try:
                deerflow_chat.run(body, model, read, answer)
            except Exception:
                ready.abort()
                raise
            return observed

        with ThreadPoolExecutor(max_workers=count) as executor:
            turns = [executor.submit(converse, n) for n in range(count)]
            try:
                ready.wait()
                with self.assertRaisesRegex(deerflow_chat.Unavailable, "正在处理其他请求"):
                    deerflow_chat.run({}, self.fail, self.fail, self.fail)
            except BrokenBarrierError:
                pass  # Report the worker that failed before the barrier.
            finally:
                resume.set()
            errors = [repr(e) for turn in turns if (e := turn.exception()) and not isinstance(e, BrokenBarrierError)]
            self.assertEqual(errors, [], "未抵达并发屏障的会话报告了错误")
            self.assertEqual([turn.result() for turn in turns], [[n] for n in range(count)])
        deerflow_chat.run({}, lambda: {"text": "再次接收新任务"}, self.fail, self.fail)

    def test_unknown_tool_does_not_run_or_retry_model(self):
        def unexpected(*_):
            self.fail("超范围的工具不得读取记录或继续调用模型")

        with self.assertRaises(ValueError):
            deerflow_chat.run(
                {"model": "中文模拟模型", "messages": [{"role": "user", "content": "看看床位"}]},
                lambda: {"calls": [{"id": "x", "name": "unknown", "arguments": {}}]},
                unexpected, unexpected,
            )
        deerflow_chat.run({"model": "中文模拟模型", "messages": [{"role": "user", "content": "请重新查询"}]},
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
                deerflow_chat.run(body, slow, self.fail, self.fail)
                results.append("unexpected")
            except deerflow_chat.Unavailable:
                results.append("expired")

        with patch.object(deerflow_chat, "TURN_SECONDS", .08):
            thread = Thread(target=go)
            thread.start()
            self.assertTrue(started.wait(2))
            deerflow_chat.run(body, lambda: {"text": "另一位员工的简报"}, self.fail, self.fail)
            self.assertFalse(resume.wait(.15))
            resume.set()
            thread.join(timeout=3)
        self.assertEqual(results, ["expired"])
