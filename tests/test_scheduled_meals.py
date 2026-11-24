"""Scheduled meal voice proposals and human signoff share resident timeline evidence."""

from contextlib import closing
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from platform_core import daily_life, provider, scheduled_meals, scheduled_work
from platform_core.provider import deepseek
from platform_core.store import Store


class ScheduledMealTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.now = datetime(2026, 11, 24, 8, 59, tzinfo=daily_life.LOCAL)
        self.store = Store(
            Path(folder.name) / "meals.db",
            now=lambda: self.now,
            initial_owner_password="meal-owner-fixture",
        )
        self.owner, self.actor = self.store.login("owner", "meal-owner-fixture")
        roster = scheduled_work.read(self.store, self.owner)["roster"]
        self.people = [row for row in roster if row["roomId"] == roster[0]["roomId"]][
            :2
        ]
        self.assertEqual(len(self.people), 2)

    def command(self, action, payload, token=None):
        token = token or self.owner
        return self.store.execute(
            action, payload, self.store.version(token)["revision"], token
        )

    def staff(self, username):
        self.command(
            "access.create",
            dict(
                username=username,
                password="meal-staff-fixture",
                displayName="同名员工",
                kind="staff",
                role="护工",
                permissions=["care"],
            ),
        )
        return self.store.login(username, "meal-staff-fixture")

    def release(self, **extra):
        self.command(
            "care.saveSchedule",
            {
                "title": "早餐任务",
                "kind": "meal",
                "time": "09:00",
                "scope": {"kind": "rooms", "roomIds": [self.people[0]["roomId"]]},
                "mealKind": "早餐",
                "menu": ["小米粥", "鸡蛋", "清蒸南瓜"],
                **extra,
            },
        )
        rule = scheduled_work.read(self.store, self.owner)["rules"][0]["id"]
        self.now += timedelta(minutes=30)
        self.assertEqual(scheduled_work.tick(self.store), 2)
        tasks = [
            v
            for v in self.store.snapshot(self.owner)["data"]["tasks"]
            if v.get("scheduleId") == rule
        ]
        return rule, tasks

    def proof(self, draft, rows=None):
        return {
            "occurrenceId": draft["occurrenceId"],
            "region": draft["region"],
            "confirmed": True,
            "entries": [
                {"taskId": r["taskId"], "basis": r["basis"], "omitted": r["omitted"]}
                for r in (rows or draft["rows"])
                if r["selected"]
            ],
        }

    def test_voice_all_and_one_omission_reaches_each_resident_and_assignee(self):
        _, tasks = self.release()
        skipped = self.people[1]
        text = "早餐所有老人都吃了今天的伙食，" + skipped["name"] + "没有吃鸡蛋"
        with closing(self.store.connect()) as db, db:
            provider.grant(
                db, "语音样例", 10000, self.now.date().isoformat(), now=self.now
            )
        model = {
            "usage": {
                "total_tokens": 88,
                "prompt_tokens": 80,
                "prompt_cache_hit_tokens": 32,
                "prompt_cache_miss_tokens": 48,
                "completion_tokens": 8,
            },
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(
                            {
                                "meal": "早餐",
                                "mode": "all",
                                "rooms": [],
                                "people": [],
                                "exceptions": [
                                    {
                                        "name": skipped["name"],
                                        "room": "",
                                        "bed": "",
                                        "entire": False,
                                        "dishes": ["鸡蛋"],
                                    }
                                ],
                                "unclear": False,
                            },
                            ensure_ascii=False,
                        )
                    },
                }
            ],
        }
        with (
            patch.object(provider, "read_key", return_value="test-model"),
            patch.object(deepseek, "send", return_value=model) as call,
        ):
            draft = scheduled_meals.preview(self.store, self.owner, {"text": text})
            call.assert_called_once()
        self.assertEqual(len(draft["rows"]), 2)
        self.assertEqual(
            {r["name"]: r["omitted"] for r in draft["rows"]},
            {
                p["name"]: ["鸡蛋"] if p["id"] == skipped["id"] else []
                for p in self.people
            },
        )
        self.assertFalse(
            daily_life.timeline(self.store, self.owner, self.people[0]["id"])["events"]
        )
        result = self.command("care.confirmScheduledMeal", self.proof(draft))
        for person in self.people:
            (item,) = daily_life.timeline(self.store, self.owner, person["id"])[
                "events"
            ]
            self.assertEqual(item["confirmedBy"], self.actor["displayName"])
            self.assertIn("吃了小米粥", item["intake"])
            if person["id"] == skipped["id"]:
                self.assertEqual(item["intake"], "吃了小米粥、清蒸南瓜。没有吃鸡蛋")
            else:
                self.assertNotIn("没有吃", item["intake"])
        with closing(self.store.connect()) as db:
            self.assertEqual(
                db.execute("SELECT feature FROM api_usage").fetchone()[0],
                "care.scheduledMealVoiceParse",
            )
        self.assertEqual(
            self.store.history_change(self.owner, result["revision"])["actorId"],
            self.actor["id"],
        )
        for current in self.store.snapshot(self.owner)["data"]["tasks"]:
            if current["id"] in {t["id"] for t in tasks}:
                self.assertEqual(current["status"], "已完成")
                self.assertEqual(current["operatorId"], self.actor["id"])
        with self.assertRaisesRegex(ValueError, "已变化"):
            self.command("care.confirmScheduledMeal", self.proof(draft))

    def test_manual_pick_is_per_person_and_stale_menu_is_rejected(self):
        rule, tasks = self.release()
        draft = scheduled_meals.preview(
            self.store, self.owner, {"taskId": tasks[0]["id"]}
        )
        self.assertEqual(sum(row["selected"] for row in draft["rows"]), 1)
        with self.assertRaisesRegex(ValueError, "逐项核对"):
            self.command(
                "care.completeTask",
                {"taskId": tasks[0]["id"], "note": "旧写入应被拒绝"},
            )
        self.command(
            "care.scheduleMenu",
            {"id": rule, "day": self.now.date().isoformat(), "menu": ["鸡蛋"]},
        )
        with self.assertRaisesRegex(ValueError, "菜单、床位"):
            self.command("care.confirmScheduledMeal", self.proof(draft))
        new = scheduled_meals.preview(
            self.store, self.owner, {"taskId": tasks[0]["id"]}
        )
        selected = next(row for row in new["rows"] if row["selected"])
        proof = self.proof(new)
        proof["entries"][0]["omitted"] = ["鸡蛋"]
        self.command("care.confirmScheduledMeal", proof)
        (item,) = daily_life.timeline(self.store, self.owner, selected["residentId"])[
            "events"
        ]
        self.assertEqual(item["intake"], "没吃这顿饭。没有吃鸡蛋")

    def test_existing_group_signoff_cancels_only_covered_scheduled_work(self):
        _, tasks = self.release()
        attendee = self.people[0]
        day = self.now.date().isoformat()
        self.command(
            "care.confirmGroupActivity",
            {
                "requestId": "exercise-group-meal",
                "campusId": attendee["campusId"],
                "roomId": attendee["roomId"],
                "kind": "早餐",
                "day": day,
                "startsAt": "09:00",
                "endsAt": "09:20",
                "details": "小米粥、鸡蛋、清蒸南瓜",
                "residentIds": [attendee["id"]],
                "confirmed": True,
                "mealIntake": {attendee["id"]: "吃了小米粥"},
            },
        )
        ids = {r["id"] for r in tasks}
        released = [
            task
            for task in self.store.snapshot(self.owner)["data"]["tasks"]
            if task["id"] in ids
        ]
        canceled = next(row for row in released if row["residentId"] == attendee["id"])
        pending = next(row for row in released if row["residentId"] != attendee["id"])
        self.assertEqual(
            (canceled["status"], canceled["cancellationReason"]),
            ("已取消", "同餐已有签认"),
        )
        (event,) = daily_life.timeline(self.store, self.owner, attendee["id"])["events"]
        self.assertEqual(canceled["scheduledMealEventId"], event["id"])
        self.assertEqual(pending["status"], "待执行")
        draft = scheduled_meals.preview(
            self.store, self.owner, {"taskId": pending["id"]}
        )
        self.command("care.confirmScheduledMeal", self.proof(draft))
        self.assertEqual(
            len(daily_life.timeline(self.store, self.owner, attendee["id"])["events"]),
            1,
        )
        self.assertEqual(
            len(
                daily_life.timeline(self.store, self.owner, pending["residentId"])[
                    "events"
                ]
            ),
            1,
        )

    def test_assignee_id_not_shared_name_controls_read_and_confirmation(self):
        picker, assigned = self.staff("meal-staff-a")
        other, _ = self.staff("meal-staff-b")
        _, tasks = self.release(assigneeId=assigned["id"])
        with self.assertRaises(FileNotFoundError):
            scheduled_meals.preview(self.store, other, {"taskId": tasks[0]["id"]})
        draft = scheduled_meals.preview(self.store, picker, {"taskId": tasks[0]["id"]})
        with self.assertRaisesRegex(ValueError, "权限"):
            self.command("care.confirmScheduledMeal", self.proof(draft), other)
        self.command("care.confirmScheduledMeal", self.proof(draft), picker)

    def test_ambiguous_rooms_and_missing_negative_detail_do_not_enlarge_scope(self):
        text = "101、102房的所有老人都吃了今天的伙食，但王宁没有吃青菜"
        draft = {
            "meal": "",
            "mode": "all",
            "rooms": ["102"],
            "people": [],
            "unclear": False,
            "exceptions": [
                {
                    "name": "王宁",
                    "room": "",
                    "bed": "",
                    "dishes": ["青菜"],
                    "entire": False,
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "房号"):
            scheduled_meals._parse(draft, text)
        with self.assertRaisesRegex(ValueError, "哪位老人"):
            scheduled_meals._parse({**draft, "exceptions": []}, text)
        for query in (
            "老人吃了今天的伙食吗",
            "老人已经吃完今天的午餐么",
            "其他老人都吃了今天的伙食，不要登记",
            "其他老人都吃了今天的伙食，不用登记",
            "别记录王宁吃了今天的伙食",
            "谁吃了今天的伙食",
            "有没有人吃完了今天的午餐",
        ):
            self.assertFalse(scheduled_meals.voice_intent(query), query)
