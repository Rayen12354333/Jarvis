"""Multi-turn conversation behavior without microphone, TTS, or network."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jarvis import main
from jarvis.llm import AgentTurn


class FakeMic:
    pass


class FakeConversation:
    def __init__(
        self,
        responses: list[AgentTurn],
        *,
        greeting: AgentTurn | None = None,
        idle: AgentTurn | None = None,
    ) -> None:
        self.greeting = greeting or AgentTurn(
            speech="Ready when you are, sir. What can I do?", action="continue"
        )
        self.responses = iter(responses)
        self.idle = idle or AgentTurn(speech="I'll be here when you need me.", action="sleep")
        self.heard: list[str] = []
        self.idle_calls = 0

    def greet(self) -> AgentTurn:
        return self.greeting

    def respond(self, text: str) -> AgentTurn:
        self.heard.append(text)
        return next(self.responses)

    def idle_timeout(self) -> AgentTurn:
        self.idle_calls += 1
        return self.idle


def _wire_audio(monkeypatch, heard: list[str]) -> list[str]:
    from jarvis.actions import LocalActionExecutor
    from jarvis.screen import ScreenVisionManager

    monkeypatch.setattr(
        main,
        "LocalActionExecutor",
        lambda *args, **kwargs: LocalActionExecutor(
            screen=ScreenVisionManager(capture=lambda: b"fake", foreground_pid=lambda: 123),
        ),
    )
    spoken: list[str] = []
    answers = iter(heard)
    monkeypatch.setattr(main, "publish_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        main,
        "_listen_for_text",
        lambda _mic, _timers=None, _volume_guard=None: next(answers),
    )
    monkeypatch.setattr(main, "_say_to_user", lambda _mic, *messages: spoken.extend(messages))
    return spoken


def test_one_wake_uses_one_gemini_session_for_direct_follow_ups(monkeypatch) -> None:
    spoken = _wire_audio(monkeypatch, ["first question", "follow-up question", "yes, that's it"])
    conversation = FakeConversation(
        [
            AgentTurn(
                speech="First answer. What else are you wondering?",
                action="continue",
            ),
            AgentTurn(
                speech="Context-aware second answer. Anything more?",
                action="continue",
            ),
            AgentTurn(speech="All right. I'll be here.", action="sleep"),
        ]
    )

    main.run_conversation(FakeMic(), conversation)

    assert conversation.heard == [
        "first question",
        "follow-up question",
        "yes, that's it",
    ]
    assert spoken == [
        conversation.greeting.speech,
        "First answer. What else are you wondering?",
        "Context-aware second answer. Anything more?",
        "All right. I'll be here.",
    ]


def test_wait_action_keeps_session_open_through_silent_windows(monkeypatch) -> None:
    spoken = _wire_audio(
        monkeypatch,
        ["first question", "wait", "", "", "second question", "rest for now"],
    )
    conversation = FakeConversation(
        [
            AgentTurn(speech="First answer. Anything else?", action="continue"),
            AgentTurn(speech="Of course. Take your time.", action="wait"),
            AgentTurn(speech="Second answer. Go on.", action="continue"),
            AgentTurn(speech="Resting now, sir.", action="sleep"),
        ]
    )

    main.run_conversation(FakeMic(), conversation)

    assert conversation.heard == [
        "first question",
        "wait",
        "second question",
        "rest for now",
    ]
    assert conversation.idle_calls == 0
    assert spoken[-1] == "Resting now, sir."


def test_normal_silence_uses_gemini_signoff_and_returns_to_wake_mode(
    monkeypatch,
) -> None:
    spoken = _wire_audio(monkeypatch, [""])
    conversation = FakeConversation([])

    main.run_conversation(FakeMic(), conversation)

    assert conversation.heard == []
    assert conversation.idle_calls == 1
    assert spoken == [conversation.greeting.speech, conversation.idle.speech]


def test_agent_turn_rejects_an_unknown_transition() -> None:
    with pytest.raises(ValidationError):
        AgentTurn(speech="Maybe.", action="confused")


def test_menu_stop_unwinds_listening_volume_guard():
    from jarvis.actions import ListeningVolumeGuard

    class Volume:
        muted = False

        def get_volume_state(self):
            return 60, self.muted

        def set_output_muted(self, value):
            self.muted = value

    volume = Volume()
    with pytest.raises(KeyboardInterrupt), ListeningVolumeGuard(volume).suppress_output():
        assert volume.muted
        main._request_shutdown(15, None)
    assert not volume.muted
