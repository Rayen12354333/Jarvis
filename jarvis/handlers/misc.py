"""Small standalone commands that don't need any external service.

Phase 2 checkpoint (PLAN.md): "what time is it" proves the wake -> listen ->
transcribe -> route -> speak wiring end to end, without needing Gmail,
Calendar, or SUIS credentials set up first.

Phase 7 adds timers, weather, unit conversion, and quick web lookup here (or
splits them into their own files once this one gets crowded).
"""
from __future__ import annotations

import datetime as _dt
from re import Match

from jarvis.router import handler


@handler(r"what(?:'s| is) the time|what time is it", name="time")
def what_time_is_it(match: Match[str], text: str) -> str:  # noqa: ARG001
    now = _dt.datetime.now().strftime("%I:%M %p").lstrip("0")
    return f"It's {now}."
