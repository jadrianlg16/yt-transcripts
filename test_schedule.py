import random
import unittest
from datetime import datetime, time, timedelta, timezone

from core.schedule import (
    DEFAULT_WINDOWS,
    ScheduleError,
    describe_windows,
    is_within_a_window,
    next_check_after,
    normalize_windows,
    parse_window,
    pick_time_in_window,
)

LOCAL = timezone(timedelta(hours=-6))


def at(hour, minute=0, day=15, tz=LOCAL):
    return datetime(2026, 8, day, hour, minute, tzinfo=tz)


class WindowParsingTests(unittest.TestCase):
    def test_the_default_windows_are_the_two_asked_for(self):
        self.assertEqual(describe_windows(), ["07:00-09:42", "20:12-22:27"])

    def test_a_backwards_window_is_rejected(self):
        with self.assertRaises(ScheduleError):
            parse_window(("22:00", "07:00"))

    def test_nonsense_times_are_rejected(self):
        for bad in (("7am", "9am"), ("25:00", "26:00"), ("", "")):
            with self.subTest(bad=bad):
                with self.assertRaises(ScheduleError):
                    parse_window(bad)

    def test_windows_come_back_in_order(self):
        parsed = normalize_windows([("20:12", "22:27"), ("07:00", "09:42")])

        self.assertEqual(parsed[0][0], time(7, 0))
        self.assertEqual(parsed[1][0], time(20, 12))


class PickTimeTests(unittest.TestCase):
    def test_the_chosen_moment_is_inside_the_window(self):
        window = (time(7, 0), time(9, 42))

        for seed in range(50):
            moment = pick_time_in_window(window, at(1).date(), rng=random.Random(seed))
            with self.subTest(seed=seed):
                self.assertGreaterEqual(moment.time(), time(7, 0))
                self.assertLessEqual(moment.time(), time(9, 42))

    def test_the_moment_moves_from_day_to_day(self):
        window = (time(7, 0), time(9, 42))
        picks = {
            pick_time_in_window(window, at(1).date(), rng=random.Random(seed)).time()
            for seed in range(30)
        }

        self.assertGreater(len(picks), 20, "a fixed time would be a pattern")

    def test_the_moment_carries_the_timezone_it_was_asked_about(self):
        moment = pick_time_in_window((time(7, 0), time(9, 42)), at(1).date(), tzinfo=LOCAL)

        self.assertEqual(moment.tzinfo, LOCAL)


class NextCheckTests(unittest.TestCase):
    def test_before_the_morning_window_the_next_check_is_that_morning(self):
        nxt = next_check_after(at(5, 30), rng=random.Random(1))

        self.assertEqual(nxt.date(), at(5, 30).date())
        self.assertGreaterEqual(nxt.time(), time(7, 0))
        self.assertLessEqual(nxt.time(), time(9, 42))

    def test_between_the_windows_the_next_check_is_that_evening(self):
        nxt = next_check_after(at(13, 0), rng=random.Random(1))

        self.assertEqual(nxt.date(), at(13, 0).date())
        self.assertGreaterEqual(nxt.time(), time(20, 12))
        self.assertLessEqual(nxt.time(), time(22, 27))

    def test_after_the_last_window_it_rolls_to_the_next_morning(self):
        now = at(23, 30)

        nxt = next_check_after(now, rng=random.Random(1))

        self.assertEqual(nxt.date(), (now + timedelta(days=1)).date())
        self.assertGreaterEqual(nxt.time(), time(7, 0))
        self.assertLessEqual(nxt.time(), time(9, 42))

    def test_the_next_check_is_always_in_the_future(self):
        for hour in range(24):
            for seed in range(5):
                now = at(hour, 30)
                with self.subTest(hour=hour, seed=seed):
                    self.assertGreater(next_check_after(now, rng=random.Random(seed)), now)

    def test_it_keeps_the_timezone_of_the_moment_it_was_given(self):
        nxt = next_check_after(at(5, 0), rng=random.Random(1))

        self.assertEqual(nxt.tzinfo, LOCAL)

    def test_it_lands_twice_a_day_over_a_simulated_week(self):
        """Walk forward as the watcher does and count the runs per day."""
        moment = at(0, 1, day=1)
        per_day: dict[int, int] = {}

        for _ in range(20):
            moment = next_check_after(moment, rng=random.Random(moment.hour * 60 + moment.minute))
            per_day[moment.day] = per_day.get(moment.day, 0) + 1

        complete = [count for day, count in per_day.items() if day not in (min(per_day), max(per_day))]
        self.assertTrue(complete)
        for count in complete:
            self.assertEqual(count, 2, "two checks a day, matching the two windows")

    def test_custom_windows_are_honoured(self):
        nxt = next_check_after(at(1, 0), windows=[("03:15", "03:45")], rng=random.Random(1))

        self.assertGreaterEqual(nxt.time(), time(3, 15))
        self.assertLessEqual(nxt.time(), time(3, 45))


class WithinWindowTests(unittest.TestCase):
    def test_moments_inside_and_outside_are_told_apart(self):
        self.assertTrue(is_within_a_window(at(8, 0)))
        self.assertTrue(is_within_a_window(at(21, 0)))
        self.assertFalse(is_within_a_window(at(13, 0)))
        self.assertFalse(is_within_a_window(at(3, 0)))

    def test_the_edges_of_a_window_count_as_inside(self):
        self.assertTrue(is_within_a_window(at(7, 0)))
        self.assertTrue(is_within_a_window(at(9, 42)))
        self.assertTrue(is_within_a_window(at(22, 27)))


if __name__ == "__main__":
    unittest.main()
