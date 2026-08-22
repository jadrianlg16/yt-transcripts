"""When to check followed channels for new uploads.

A fixed interval is both a giveaway and wasteful: checking every six hours means
four requests a day landing at the same minutes, forever. Real viewing happens in
bursts, so this picks one moment inside each of two daily windows and moves it
every day.

The windows are local time, because they describe when a person is awake, not
anything about UTC.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable

# Morning and evening. Deliberately not on the hour or half hour.
DEFAULT_WINDOWS: tuple[tuple[str, str], ...] = (
    ("07:00", "09:42"),
    ("20:12", "22:27"),
)


class ScheduleError(ValueError):
    pass


def parse_window(window: Iterable[str]) -> tuple[time, time]:
    start_text, end_text = list(window)[:2]
    try:
        start = time.fromisoformat(str(start_text))
        end = time.fromisoformat(str(end_text))
    except ValueError as exc:
        raise ScheduleError(f"Not a time range: {start_text}-{end_text}") from exc

    if start >= end:
        raise ScheduleError(f"Window start must be before its end: {start_text}-{end_text}")
    return start, end


def normalize_windows(windows: Any) -> list[tuple[time, time]]:
    if not windows:
        return [parse_window(w) for w in DEFAULT_WINDOWS]

    parsed = [parse_window(w) for w in windows]
    return sorted(parsed, key=lambda pair: pair[0])


def _seconds(value: time) -> int:
    return value.hour * 3600 + value.minute * 60 + value.second


def pick_time_in_window(
    window: tuple[time, time],
    day: date,
    rng: random.Random | None = None,
    tzinfo: Any = None,
) -> datetime:
    """A moment somewhere inside the window, to the second.

    Carries the caller's timezone, because the result is compared against, and
    stored alongside, timezone-aware timestamps.
    """
    rng = rng or random
    start, end = window
    offset = rng.randint(0, max(0, _seconds(end) - _seconds(start)))
    moment = datetime.combine(day, start) + timedelta(seconds=offset)
    return moment.replace(tzinfo=tzinfo) if tzinfo is not None else moment


def next_check_after(
    now: datetime,
    windows: Any = None,
    rng: random.Random | None = None,
) -> datetime:
    """The next moment to check, always in the future.

    Rolls into tomorrow's first window once today's have passed, so the schedule
    never stalls and never fires twice for the same window.
    """
    parsed = normalize_windows(windows)
    rng = rng or random
    tzinfo = now.tzinfo
    current = now.time()

    for start, end in parsed:
        # Skip any window already under way. Picking a later slot inside the window
        # we are currently in would run again the same morning, so two windows a day
        # would not mean two checks a day.
        if start <= current:
            continue
        return pick_time_in_window((start, end), now.date(), rng=rng, tzinfo=tzinfo)

    return pick_time_in_window(
        parsed[0], now.date() + timedelta(days=1), rng=rng, tzinfo=tzinfo
    )


def describe_windows(windows: Any = None) -> list[str]:
    return [f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}" for start, end in normalize_windows(windows)]


def is_within_a_window(moment: datetime, windows: Any = None) -> bool:
    """Whether a moment falls inside any window, for a late or catch-up run."""
    parsed = normalize_windows(windows)
    current = moment.time()
    return any(start <= current <= end for start, end in parsed)
