import unittest
from datetime import datetime, timedelta, timezone

from platform_core import visit_schedule as schedule


class VisitScheduleTests(unittest.TestCase):
    def setUp(self):
        self.state = {}
        self.now = datetime(2026, 11, 25, 8, tzinfo=schedule.LOCAL_ZONE)
        self.day = "2026-11-25"

    def reserve(
        self, lead, start="16:00", end="16:30", campus="home", now=None, **options
    ):
        payload = {
            "date": self.day,
            "start": start,
            "end": end,
            "kind": "visit",
            **options,
        }
        return schedule.reserve(
            self.state, campus, lead, payload, now or self.now, "reception"
        )

    def view(self, now=None):
        return schedule.day_view(self.state, "home", self.day, now or self.now)

    def test_contiguous_seat_required_across_multiple_half_hours(self):
        schedule.configure(self.state, "home", 2, self.now)
        first = self.reserve("a", seat=1)
        second = self.reserve("b", "16:30", "17:30", seat=2)
        with self.assertRaisesRegex(ValueError, "全程"):
            self.reserve("c", "16:00", "17:00")
        slots = self.view()["slots"]
        self.assertEqual(slots[32]["seats"], [first["id"], None])
        self.assertEqual(slots[33]["seats"], [None, second["id"]])
        other = self.reserve("c")
        self.assertEqual(other["seat"], 2)
        self.assertFalse(self.view()["slots"][32]["bookable"])
        self.assertEqual(self.reserve("d", "16:30", "17:30")["seat"], 1)
        self.assertTrue(self.view()["slots"][35]["bookable"])

    def test_default_capacity_and_parallel_campuses_are_independent(self):
        a = self.reserve("home lead")
        b = self.reserve("other lead", campus="other")
        self.assertEqual((a["seat"], b["seat"]), (1, 1))
        with self.assertRaises(ValueError):
            self.reserve("third")
        schedule.close(
            self.state, "other", "home lead", None, "cancelled", self.now, "staff"
        )
        self.assertEqual(self.view()["bookings"], [a])
        self.assertEqual(self.view()["slots"][32]["seats"], [a["id"]])

    def test_atomic_reschedule_seat_holds_and_history(self):
        first = self.reserve("a")
        self.assertIs(self.reserve("a"), first)
        self.reserve("b", "17:00", "17:30")
        with self.assertRaises(ValueError):
            self.reserve("a", "16:30", "17:30")
        self.assertEqual(first["status"], "confirmed")
        replacement = self.reserve("a", "16:30", "17:00")
        self.assertEqual(first["status"], "rescheduled")
        self.assertEqual(replacement["replacesId"], first["id"])
        self.assertTrue(self.view()["slots"][32]["bookable"])
        self.assertEqual(self.view()["slots"][33]["seats"], [replacement["id"]])
        self.assertCountEqual(self.view()["bookings"], self.state["visitBookings"])
        self.reserve("a", "18:00", "18:30", kind="callback")
        self.assertEqual(
            len(
                schedule.close(
                    self.state, "home", "a", None, "cancelled", self.now, "operator"
                )
            ),
            2,
        )
        self.assertTrue(self.view()["slots"][33]["bookable"])

    def test_same_lead_cannot_be_called_while_on_visit_even_with_free_seat(self):
        schedule.configure(self.state, "home", 2, self.now)
        self.reserve("a", end="17:00")
        with self.assertRaisesRegex(ValueError, "已有其他预约"):
            self.reserve("a", "16:30", "17:00", kind="callback")
        self.reserve("a", "17:00", "17:30", kind="callback")

    def test_capacity_reduction_preserves_promises_and_history(self):
        schedule.configure(self.state, "home", 3, self.now)
        first = self.reserve("a", "16:00", "17:00", seat=3)
        with self.assertRaises(ValueError):
            schedule.configure(self.state, "home", 2, self.now)
        half_past = self.now.replace(hour=16, minute=30)
        with self.assertRaises(ValueError):
            schedule.configure(self.state, "home", 1, half_past)
        schedule.close(
            self.state, "home", "a", "visit", "completed", half_past, "employee"
        )
        schedule.configure(self.state, "home", 1, half_past)
        grid = self.view(half_past)
        self.assertEqual((grid["capacity"], grid["displayCapacity"]), (1, 3))
        self.assertEqual(grid["slots"][32]["seats"][2], first["id"])
        self.assertFalse(grid["slots"][32]["bookable"])
        self.assertEqual(grid["slots"][33]["seats"], [None, None, None])
        self.assertTrue(grid["slots"][33]["bookable"])
        self.assertEqual(first["closedBy"], "employee")

    def test_local_day_and_exact_boundary(self):
        # 15:30 UTC is already 23:30 in Henan.
        utc = datetime(2026, 11, 25, 15, 30, tzinfo=timezone.utc)
        self.assertTrue(self.view(utc)["slots"][47]["bookable"])
        booking = self.reserve("n", "23:30", "24:00", now=utc)
        self.assertEqual(booking["confirmedAt"], "2026-11-25T23:30:00+08:00")
        with self.assertRaisesRegex(ValueError, "尚未开始"):
            self.reserve("n", "23:30", "24:00", now=utc + timedelta(microseconds=1))
        with self.assertRaisesRegex(ValueError, "尚未开始"):
            self.reserve("n", "23:30", "24:00", now=utc + timedelta(minutes=30))
        self.assertEqual(
            self.reserve("other", "00:00", "00:30", date="2026-11-26", now=utc)["seat"],
            1,
        )
        self.assertEqual(len(self.view()["slots"]), 48)

    def test_invalid_intervals_and_capacity_never_modify_state(self):
        for value in [None, False, -1, 0, 33, 2.0, "2"]:
            with self.subTest(capacity=value), self.assertRaises(ValueError):
                schedule.configure(self.state, "home", value, self.now)
        invalid = [
            {"start": "16:00", "end": "16:00"},
            {"start": "16:01"},
            {"end": "25:00"},
            {"start": "24:00", "end": "24:00"},
            {"date": "2026-99-99"},
            {"date": "20261125"},
            {"date": None},
            {"seat": True},
            {"seat": 0},
            {"seat": 2},
            {"kind": "other"},
            {"start": "23:30", "end": "00:30"},
        ]
        for options in invalid:
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.reserve("a", **options)
        self.assertEqual(self.state, {})
