"""Each handler gets a test here that calls it with sample text (PLAN.md section 7).

Run with: pytest
"""
from __future__ import annotations

from jarvis import handlers  # noqa: F401  (importing this registers every handler)
from jarvis.router import dispatch


def test_what_time_is_it() -> None:
    reply = dispatch("what time is it")
    assert reply is not None
    assert "It's" in reply


def test_unmatched_text_returns_none() -> None:
    assert dispatch("asdkfjalksdjf nonsense") is None
