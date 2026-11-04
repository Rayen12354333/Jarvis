"""Countdown scheduling tests with deterministic clocks."""
from __future__ import annotations

import datetime as dt

import pytest

from jarvis.timers import TimerManager, format_duration, timer_alarm_message


class Clock:
    def __init__(self) -> None:
        self.monotonic = 100.0
        self.now = dt.datetime(2026, 9, 5, 12, 0, tzinfo=dt.UTC)

    def tick(self, seconds: float) -> None:
        self.monotonic += seconds
        self.now += dt.timedelta(seconds=seconds)


def test_timer_fires_once_after_monotonic_deadline() -> None:
    clock = Clock()
    timers = TimerManager(monotonic=lambda: clock.monotonic, now=lambda: clock.now)
    timer = timers.set_timer(10, "tea")

    clock.tick(9.9)
    assert not timers.has_due()
    assert timers.pop_due() == []

    clock.tick(0.1)
    assert timers.has_due()
    assert timers.pop_due() == [timer]
    assert timers.pop_due() == []
    assert timer_alarm_message(timer) == "Sir, your tea timer is up."


def test_multiple_timers_list_and_cancel_independently() -> None:
    clock = Clock()
    timers = TimerManager(monotonic=lambda: clock.monotonic, now=lambda: clock.now)
    later = timers.set_timer(60, "laundry")
    sooner = timers.set_timer(10, "tea")

    assert timers.active() == [sooner, later]
    assert timers.cancel(label="  TEA ") == [sooner]
    assert timers.active() == [later]
    assert timers.cancel(timer_id=later.timer_id) == [later]
    assert timers.active() == []


def test_timer_duration_is_bounded() -> None:
    timers = TimerManager()

    with pytest.raises(ValueError):
        timers.set_timer(0)
    with pytest.raises(ValueError):
        timers.set_timer(8 * 24 * 60 * 60)


def test_duration_formatting() -> None:
    assert format_duration(90) == "1 minute and 30 seconds"
    assert format_duration(7200) == "2 hours"
