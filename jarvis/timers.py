"""In-process countdown timers for Jarvis.

Deadlines use ``time.monotonic`` so a wall-clock correction cannot make a
running timer jump forwards or backwards.  ``due_at`` is retained only for
natural confirmations and status messages.
"""
from __future__ import annotations

import datetime as dt
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

MIN_TIMER_SECONDS = 1.0
MAX_TIMER_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class Timer:
    """One active or completed countdown timer."""

    timer_id: int
    label: str
    duration_seconds: float
    due_monotonic: float
    due_at: dt.datetime


def format_duration(seconds: float) -> str:
    """Return a compact duration that sounds natural when spoken."""
    total = max(0, int(round(seconds)))
    units = (
        ("day", 24 * 60 * 60),
        ("hour", 60 * 60),
        ("minute", 60),
        ("second", 1),
    )
    parts: list[str] = []
    for name, size in units:
        value, total = divmod(total, size)
        if value:
            parts.append(f"{value} {name}{'' if value == 1 else 's'}")
        if len(parts) == 2:
            break
    return " and ".join(parts) or "0 seconds"


class TimerManager:
    """Own the timers for the lifetime of one Jarvis process."""

    def __init__(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self._monotonic = monotonic
        self._now = now or (lambda: dt.datetime.now().astimezone())
        self._timers: dict[int, Timer] = {}
        self._next_id = 1
        self._lock = threading.Lock()

    def set_timer(self, seconds: float, label: str | None = None) -> Timer:
        """Create a countdown and return its stable id and deadlines."""
        if not math.isfinite(seconds):
            raise ValueError("Timer duration must be a finite number.")
        if not MIN_TIMER_SECONDS <= seconds <= MAX_TIMER_SECONDS:
            raise ValueError("Timers must be between 1 second and 7 days.")

        clean_label = " ".join((label or "timer").strip().split())[:80] or "timer"
        with self._lock:
            timer = Timer(
                timer_id=self._next_id,
                label=clean_label,
                duration_seconds=seconds,
                due_monotonic=self._monotonic() + seconds,
                due_at=self._now() + dt.timedelta(seconds=seconds),
            )
            self._timers[timer.timer_id] = timer
            self._next_id += 1
        return timer

    def active(self) -> list[Timer]:
        """Return all active timers in due-time order."""
        with self._lock:
            return sorted(self._timers.values(), key=lambda timer: timer.due_monotonic)

    def has_due(self) -> bool:
        now = self._monotonic()
        with self._lock:
            return any(timer.due_monotonic <= now for timer in self._timers.values())

    def remaining_seconds(self, timer: Timer) -> float:
        """Return remaining time using the same monotonic clock as the deadline."""
        return max(0.0, timer.due_monotonic - self._monotonic())

    def pop_due(self) -> list[Timer]:
        """Remove and return every timer whose monotonic deadline has passed."""
        now = self._monotonic()
        with self._lock:
            due = sorted(
                (
                    timer
                    for timer in self._timers.values()
                    if timer.due_monotonic <= now
                ),
                key=lambda timer: timer.due_monotonic,
            )
            for timer in due:
                self._timers.pop(timer.timer_id, None)
        return due

    def cancel(
        self, *, timer_id: int | None = None, label: str | None = None
    ) -> list[Timer]:
        """Cancel timers by id or exact label, or the sole timer if unambiguous."""
        with self._lock:
            if timer_id is not None:
                timer = self._timers.pop(timer_id, None)
                return [timer] if timer is not None else []

            if label:
                normalized = " ".join(label.strip().casefold().split())
                matches = [
                    timer
                    for timer in self._timers.values()
                    if timer.label.casefold() == normalized
                ]
                for timer in matches:
                    self._timers.pop(timer.timer_id, None)
                return matches

            if len(self._timers) == 1:
                _, timer = self._timers.popitem()
                return [timer]
            return []


def timer_alarm_message(timer: Timer) -> str:
    """Create a concise alarm message without duplicating generic wording."""
    if timer.label.casefold() == "timer":
        return "Sir, your timer is up."
    return f"Sir, your {timer.label} timer is up."
