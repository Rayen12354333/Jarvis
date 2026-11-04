"""Typed requests do not block the menu or overlap one another."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from jarvis import commands
from jarvis.commands import CommandSession


@pytest.fixture(autouse=True)
def no_live_status(monkeypatch):
    monkeypatch.setattr(commands, "publish_activity", lambda *args, **kwargs: None)


def finish(session: CommandSession):
    deadline = time.monotonic() + 2
    while session.busy and time.monotonic() < deadline:
        time.sleep(0.005)
    assert not session.busy
    reply = session.take_reply()
    assert reply is not None
    return reply


def test_typed_followups_share_one_conversation():
    heard = []
    conversation = SimpleNamespace(
        respond=lambda text: (
            heard.append(text) or SimpleNamespace(speech="Done", action="continue")
        ),
        close=lambda: None,
    )
    session = CommandSession(lambda: conversation)
    assert session.submit("  Start a study session  ")
    assert finish(session).text == "Done"
    assert session.submit("Save this for later")
    finish(session)
    assert heard == ["Start a study session", "Save this for later"]
    session.close()
    assert not session.submit("Must not start after close")


def test_busy_requests_do_not_overlap_and_cancel_clears_context():
    entered, release = threading.Event(), threading.Event()
    closed = []

    def respond(text):
        entered.set()
        assert release.wait(timeout=2)
        return SimpleNamespace(speech="Original answer", action="continue")

    session = CommandSession(
        lambda: SimpleNamespace(respond=respond, close=lambda: closed.append(1))
    )
    assert session.submit("First")
    assert entered.wait(timeout=2)
    assert not session.submit("Second")
    session.cancel()
    release.set()
    assert "Cancelled" in finish(session).text
    assert closed == [1]


def test_error_does_not_leak_exception_contents_and_allows_retry():
    def fail(text):
        raise RuntimeError("secret content must not be exposed")

    session = CommandSession(lambda: SimpleNamespace(respond=fail, close=lambda: None))
    assert session.submit("First")
    reply = finish(session)
    assert reply.failed
    assert "secret" not in reply.text
    assert session.submit("Retry")
    finish(session)


@pytest.mark.parametrize("text", ["", "  ", "x" * 6001])
def test_invalid_typed_requests_are_rejected(text):
    with pytest.raises(ValueError):
        CommandSession().submit(text)
