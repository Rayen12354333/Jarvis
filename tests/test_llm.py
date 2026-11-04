"""Gemini research orchestration with a fake chat transport."""

from __future__ import annotations

from types import SimpleNamespace

from jarvis import llm
from jarvis.actions import LocalAction, LocalActionExecutor
from jarvis.llm import AgentTurn, GeminiConversation
from jarvis.screen import ScreenVisionManager


def test_system_prompt_requests_direct_computer_game_advice() -> None:
    prompt = llm._system_prompt()

    assert "playing against a computer" in prompt
    assert "strongest move or action first" in prompt
    assert "ethics lecture" in prompt
    assert "Do not provide live move advice" not in prompt


def test_system_prompt_distinguishes_spotify_from_mac_volume() -> None:
    prompt = llm._system_prompt()

    assert "adjust_spotify_volume" in prompt
    assert "set_spotify_volume" in prompt
    assert "change only Spotify" in prompt


def test_system_prompt_routes_explicit_second_opinions_to_groqcloud() -> None:
    prompt = llm._system_prompt()

    assert "specialist_query" in prompt
    assert '"double-check that"' in prompt
    assert "not xAI's Grok" in prompt
    assert "one unified" in prompt


class FakeChat:
    def __init__(self, turns: list[AgentTurn]) -> None:
        self.turns = iter(turns)
        self.messages: list[object] = []

    def send_message(self, message: str):
        self.messages.append(message)
        return SimpleNamespace(parsed=next(self.turns), text=None)


class FakeGroq:
    def __init__(self) -> None:
        self.model = "test-specialist"
        self.consulted: list[str] = []
        self.fallback_messages: list[str] = []

    def consult(self, question: str) -> str:
        self.consulted.append(question)
        return "The specialist independently reached the same conclusion."

    def fallback(self, message: str):  # noqa: ANN201
        self.fallback_messages.append(message)
        return SimpleNamespace(
            speech="GroqCloud fallback answered directly.",
            action="continue",
        )

    def close(self) -> None:
        pass


def test_gemini_can_consult_second_model_then_synthesize() -> None:
    chat = FakeChat(
        [
            AgentTurn(
                speech="",
                action="continue",
                specialist_query="Solve the hard question independently.",
            ),
            AgentTurn(speech="Both models agree on the answer.", action="continue"),
        ]
    )
    groq = FakeGroq()
    conversation = GeminiConversation.__new__(GeminiConversation)
    conversation._client = None
    conversation._chat = chat
    conversation._groq = groq
    conversation._action_executor = None

    turn = conversation.respond("Double-check this hard question")

    assert turn.speech == "Both models agree on the answer."
    assert groq.consulted == ["Solve the hard question independently."]
    assert "Internal second-opinion result" in chat.messages[1]


def test_groqcloud_takes_over_when_gemini_fails() -> None:
    class BrokenGemini:
        def send_message(self, message: str):
            raise RuntimeError("provider unavailable")

    groq = FakeGroq()
    conversation = GeminiConversation.__new__(GeminiConversation)
    conversation._client = None
    conversation._chat = BrokenGemini()
    conversation._groq = groq
    conversation._action_executor = None

    turn = conversation.respond("Answer despite the outage")

    assert turn.speech == "GroqCloud fallback answered directly."
    assert groq.fallback_messages == ["Answer despite the outage"]


def test_dual_provider_failure_ends_only_the_active_session() -> None:
    class BrokenGroq:
        def fallback(self, message: str):  # noqa: ANN201
            raise RuntimeError("secondary provider unavailable")

    conversation = GeminiConversation.__new__(GeminiConversation)
    conversation._client = None
    conversation._chat = None
    conversation._groq = BrokenGroq()
    conversation._action_executor = None

    turn = conversation.respond("Answer if possible")

    assert turn.action == "sleep"
    assert "can't reach either" in turn.speech


def test_research_searches_then_requires_a_primary_page(monkeypatch) -> None:
    chat = FakeChat(
        [
            AgentTurn(speech="", action="continue", web_queries=["focused query"]),
            # Even if Gemini tries to answer from snippets, the orchestrator
            # requires a real source page before accepting the answer.
            AgentTurn(speech="Premature answer.", action="continue"),
            AgentTurn(
                speech="",
                action="continue",
                read_urls=["https://example.com/source"],
            ),
            AgentTurn(speech="Verified final answer. Anything else?", action="continue"),
        ]
    )
    conversation = GeminiConversation.__new__(GeminiConversation)
    conversation._client = None
    conversation._chat = chat
    conversation._action_executor = None
    searched: list[str] = []
    read: list[str] = []

    monkeypatch.setattr(
        llm,
        "search_web",
        lambda query: searched.append(query) or "search evidence",
    )
    monkeypatch.setattr(
        llm,
        "read_webpage",
        lambda url: read.append(url) or "primary page evidence",
    )

    turn = conversation.respond("Research something current")

    assert searched == ["focused query"]
    assert read == ["https://example.com/source"]
    assert turn.speech == "Verified final answer. Anything else?"
    assert any("verification requirement" in message for message in chat.messages)


class FakeActionExecutor:
    def __init__(self) -> None:
        self.actions: list[LocalAction] = []

    def execute(self, action: LocalAction) -> str:
        self.actions.append(action)
        if action.name == "get_volume":
            return "Current output volume is 50 percent; muted is false."
        return "Output volume changed from 60 to 50 percent."


def test_successful_local_action_skips_a_second_model_round_trip() -> None:
    chat = FakeChat(
        [
            AgentTurn(
                speech="Done, I've lowered it.",
                action="continue",
                local_actions=[LocalAction(name="adjust_volume", amount=-10)],
                task_complete=True,
            )
        ]
    )
    executor = FakeActionExecutor()
    conversation = GeminiConversation.__new__(GeminiConversation)
    conversation._client = None
    conversation._chat = chat
    conversation._action_executor = executor

    turn = conversation.respond("Lower the volume a little")

    assert [action.name for action in executor.actions] == ["adjust_volume"]
    assert executor.actions[0].amount == -10
    assert turn.speech == "Volume at 50 percent."
    assert turn.local_actions == []
    assert chat.messages == ["Lower the volume a little"]


def test_successful_action_can_speak_its_trusted_result_without_another_call() -> None:
    chat = FakeChat(
        [
            AgentTurn(
                speech="",
                action="continue",
                local_actions=[LocalAction(name="get_volume")],
                task_complete=True,
            )
        ]
    )
    executor = FakeActionExecutor()
    conversation = GeminiConversation.__new__(GeminiConversation)
    conversation._client = None
    conversation._chat = chat
    conversation._action_executor = executor

    turn = conversation.respond("What is the volume?")

    assert turn.speech == "Current output volume is 50 percent; muted is false."
    assert len(chat.messages) == 1


def test_screen_capture_is_attached_as_image_after_authorization() -> None:
    chat = FakeChat(
        [
            AgentTurn(
                speech="",
                action="continue",
                local_actions=[
                    LocalAction(
                        name="start_screen_vision",
                        seconds=60,
                        purpose="explain a diagram",
                    ),
                    LocalAction(
                        name="inspect_screen",
                        screen_question="Explain the visible diagram",
                    ),
                ],
            ),
            AgentTurn(
                speech="The diagram shows a request flowing into a service.",
                action="continue",
            ),
        ]
    )
    screen = ScreenVisionManager(
        capture=lambda: b"\x89PNG\r\n\x1a\nimage",
        foreground_pid=lambda: 123,
    )
    conversation = GeminiConversation.__new__(GeminiConversation)
    conversation._client = None
    conversation._chat = chat
    conversation._action_executor = LocalActionExecutor(screen=screen)

    turn = conversation.respond("Look at my screen and explain this diagram")

    assert turn.speech.startswith("The diagram")
    image_message = chat.messages[1]
    assert isinstance(image_message, list)
    assert any(part.inline_data is not None for part in image_message)


def make_conversation(chat, executor=None, **attributes) -> GeminiConversation:
    conversation = GeminiConversation.__new__(GeminiConversation)
    conversation._client = None
    conversation._chat = chat
    conversation._action_executor = executor
    conversation._groq = None
    for key, value in attributes.items():
        setattr(conversation, key, value)
    return conversation


def test_intermediate_action_continues_the_entire_request() -> None:
    chat = FakeChat(
        [
            AgentTurn(
                speech="",
                action="continue",
                local_actions=[LocalAction(name="get_volume")],
            ),
            AgentTurn(
                speech="Don't speak this unsupported promise.",
                action="continue",
                local_actions=[LocalAction(name="adjust_volume", amount=-10)],
                task_complete=True,
            ),
        ]
    )
    executor = FakeActionExecutor()
    conversation = make_conversation(chat, executor)

    turn = conversation.respond("Check the volume and lower it if it is too high")

    assert [a.name for a in executor.actions] == ["get_volume", "adjust_volume"]
    assert turn.speech == "Volume at 50 percent."
    assert "Current output volume is 50" in chat.messages[1]


def test_fast_path_preserves_action_evidence_for_followups() -> None:
    chat = FakeChat(
        [
            AgentTurn(
                speech="",
                action="continue",
                local_actions=[LocalAction(name="adjust_volume", amount=-10)],
                task_complete=True,
            ),
            AgentTurn(speech="It is 50 percent after that change.", action="continue"),
        ]
    )
    executor = FakeActionExecutor()
    conversation = make_conversation(chat, executor)

    conversation.respond("Lower the volume")
    conversation.respond("What did you change it to?")

    assert "Output volume changed from 60 to 50 percent" in chat.messages[1]
    assert "Do not repeat these actions" in chat.messages[1]
    assert "[Current user request follows:]\nWhat did you change it to?" in chat.messages[1]
    assert conversation._pending_action_results == ""
    assert len(executor.actions) == 1


def test_non_failure_string_is_not_necessarily_action_success() -> None:
    class UnavailableSpotify:
        def execute(self, action):
            return "Spotify is not currently running, so its volume was not changed."

    chat = FakeChat(
        [
            AgentTurn(
                speech="Done, Spotify is quieter.",
                action="continue",
                local_actions=[LocalAction(name="adjust_spotify_volume", amount=-10)],
                task_complete=True,
            ),
            AgentTurn(
                speech="Spotify is closed, so I couldn't change its volume.", action="continue"
            ),
        ]
    )
    conversation = make_conversation(chat, UnavailableSpotify())

    turn = conversation.respond("Lower Spotify volume")

    assert len(chat.messages) == 2
    assert turn.speech == "Spotify is closed, so I couldn't change its volume."


def test_model_failure_after_action_does_not_repeat_or_use_stateless_fallback() -> None:
    chat = FakeChat(
        [
            AgentTurn(
                speech="",
                action="continue",
                local_actions=[LocalAction(name="adjust_volume", amount=-10)],
            ),
        ]
    )  # Exhausted chat raises during the post-action model request.
    groq = FakeGroq()
    executor = FakeActionExecutor()
    conversation = make_conversation(chat, executor, _groq=groq)

    turn = conversation.respond("Lower the volume and then explain the change")

    assert len(executor.actions) == 1
    assert "Volume at 50" in turn.speech
    assert "connection failed" in turn.speech
    assert groq.fallback_messages == []
    assert "Output volume changed" in conversation._pending_action_results


def test_identical_relative_action_cannot_be_repeated_within_one_request() -> None:
    action = LocalAction(name="adjust_volume", amount=-10)
    chat = FakeChat(
        [
            AgentTurn(speech="", action="continue", local_actions=[action]),
            AgentTurn(speech="", action="continue", local_actions=[action]),
            AgentTurn(speech="The volume was lowered once.", action="continue"),
        ]
    )
    executor = FakeActionExecutor()
    conversation = make_conversation(chat, executor)

    conversation.respond("Lower the volume")

    assert len(executor.actions) == 1
    assert "already attempted" in chat.messages[2]


def test_identical_failed_open_stops_without_another_action_or_model_round():
    from types import SimpleNamespace

    action = LocalAction(name="open_url", url="https://www.youtube.com")
    chat = FakeChat([AgentTurn(speech="", action="continue", local_actions=[action])] * 3)
    actions = []
    executor = SimpleNamespace(execute=lambda a: actions.append(a) or "FAILED open_url: denied")
    result = make_conversation(chat, executor).respond("Open YouTube")
    assert len(actions) == 1
    assert len(chat.messages) == 2
    assert "stopped retrying" in result.speech


def test_fresh_screen_can_be_used_for_a_followup_action() -> None:
    clicks: list[tuple[int, int]] = []
    screen = ScreenVisionManager(
        capture=lambda: b"png bytes",
        click=lambda x, y: clicks.append((x, y)),
        foreground_pid=lambda: 123,
    )
    chat = FakeChat(
        [
            AgentTurn(
                speech="",
                action="continue",
                # Even a model's incorrect task_complete flag cannot skip image analysis.
                task_complete=True,
                local_actions=[
                    LocalAction(name="start_screen_vision", seconds=60, purpose="select video"),
                    LocalAction(name="inspect_screen", screen_question="Locate the second video"),
                ],
            ),
            AgentTurn(
                speech="The video is playing!",  # A click result does not prove playback.
                action="continue",
                task_complete=True,
                local_actions=[LocalAction(name="click_screen", screen_x=200, screen_y=400)],
            ),
        ]
    )
    conversation = make_conversation(chat, LocalActionExecutor(screen=screen))

    turn = conversation.respond("Play the second video on screen")

    assert clicks == [(200, 400)]
    assert turn.speech == "Done, I clicked the requested target."
    assert len(chat.messages) == 2


def test_budget_exhaustion_never_returns_unexecuted_actions(monkeypatch) -> None:
    monkeypatch.setattr(llm, "MAX_TOOL_ROUNDS", 1)
    action = LocalAction(name="get_volume")
    chat = FakeChat(
        [
            AgentTurn(speech="", action="continue", local_actions=[action]),
            AgentTurn(speech="", action="continue", local_actions=[action]),
            AgentTurn(
                speech="I created the note.",
                action="continue",
                local_actions=[
                    LocalAction(name="create_note", note_title="Test", note_body="Body")
                ],
            ),
        ]
    )
    executor = FakeActionExecutor()
    conversation = make_conversation(chat, executor)

    turn = conversation.respond("A complicated task")

    assert len(executor.actions) == 1
    assert turn.local_actions == []
    assert "step limit" in turn.speech
    assert "created" not in turn.speech


def test_cancellation_before_start_does_not_call_model_or_actions() -> None:
    chat = FakeChat([])
    executor = FakeActionExecutor()
    conversation = make_conversation(chat, executor, _should_cancel=lambda: True)

    turn = conversation.respond("Lower the volume")

    assert chat.messages == []
    assert executor.actions == []
    assert turn.speech.startswith("Cancelled")
    assert turn.local_actions == []


def test_cancellation_between_actions_keeps_results_and_stops_next_action() -> None:
    cancelled = False

    class CancellingExecutor(FakeActionExecutor):
        def execute(self, action):
            nonlocal cancelled
            result = super().execute(action)
            cancelled = True
            return result

    chat = FakeChat(
        [
            AgentTurn(
                speech="All done!",
                action="continue",
                local_actions=[
                    LocalAction(name="adjust_volume", amount=-10),
                    LocalAction(name="create_note", note_title="Test", note_body="Body"),
                ],
            ),
        ]
    )
    executor = CancellingExecutor()
    conversation = make_conversation(chat, executor, _should_cancel=lambda: cancelled)

    turn = conversation.respond("Lower the volume and save a note")

    assert len(executor.actions) == 1
    assert turn.speech.startswith("Cancelled")
    assert "changed from 60 to 50" in conversation._pending_action_results


def test_gemini_transport_has_bounded_timeout_and_no_invisible_retries(monkeypatch) -> None:
    from google import genai

    observed = {}

    def fake_client(**kwargs):
        observed.update(kwargs)
        return SimpleNamespace(chats=SimpleNamespace(create=lambda **kw: FakeChat([])))

    monkeypatch.setattr(llm, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm, "GROQ_API_KEY", "")
    monkeypatch.setattr(genai, "Client", fake_client)

    GeminiConversation()

    assert observed["http_options"].timeout == 25_000
    assert observed["http_options"].retry_options.attempts == 1


def test_parallel_research_preserves_order_and_isolates_failures() -> None:
    from threading import Barrier

    barrier = Barrier(3)

    def operation(value):
        barrier.wait(timeout=2)
        if value == "second":
            raise RuntimeError("offline")
        return value

    result = GeminiConversation._parallel_evidence(operation, ["first", "second", "third"])

    assert result.startswith("first\n\nFAILED")
    assert result.endswith("third")


def test_spotify_observation_is_repeatable_but_mutation_is_guarded() -> None:
    assert llm._requires_duplicate_guard(
        LocalAction(name="play_spotify_track", query="God's Plan Drake")
    )
    assert not llm._requires_duplicate_guard(
        LocalAction(name="control_spotify", media_command="now_playing")
    )
    assert llm._requires_duplicate_guard(LocalAction(name="control_spotify", media_command="next"))
    assert llm._confirmed_action_result(
        LocalAction(name="control_spotify", media_command="pause"),
        "Paused Spotify playback.",
    )


def test_processed_images_are_removed_without_losing_text_history():
    from google.genai import types

    original = types.Content(
        role="user",
        parts=[
            types.Part.from_text(text="Click this"),
            types.Part.from_bytes(data=b"private-image", mime_type="image/jpeg"),
        ],
    )
    response = types.Content(
        role="model", parts=[types.Part.from_text(text="Observed button at 20,30")]
    )
    recreated = []
    conversation = make_conversation(
        SimpleNamespace(get_history=lambda curated: [original, response])
    )
    conversation._chat_config = object()
    conversation._client = SimpleNamespace(
        chats=SimpleNamespace(
            create=lambda **kwargs: recreated.append(kwargs) or object(),
        )
    )
    conversation._discard_processed_images()
    assert recreated
    history = recreated[0]["history"]
    assert all(part.inline_data is None for content in history for part in content.parts)
    assert history[0].parts[0].text == "Click this"
    assert history[1].parts[0].text == "Observed button at 20,30"
    assert original.parts[1].inline_data.data == b"private-image"  # no SDK history mutation


def test_active_screen_is_in_first_request_and_click_needs_one_model_call():
    clicked = []
    screen = ScreenVisionManager(
        capture=lambda: b"image",
        foreground_pid=lambda: 123,
        click=lambda *args: clicked.append(args),
    )
    screen.start(1800)
    chat = FakeChat(
        [
            AgentTurn(
                speech="",
                action="continue",
                task_complete=True,
                local_actions=[LocalAction(name="click_screen", screen_x=200, screen_y=400)],
            )
        ]
    )
    turn = make_conversation(chat, LocalActionExecutor(screen=screen)).respond("Click that button")
    assert len(chat.messages) == 1
    assert any(part.inline_data is not None for part in chat.messages[0])
    assert clicked == [(200, 400)]
    assert "clicked" in turn.speech


def test_voice_screen_off_works_without_model_or_capture():
    screen = ScreenVisionManager(
        capture=lambda: (_ for _ in ()).throw(AssertionError("No capture")),
        foreground_pid=lambda: 123,
    )
    screen.start(1800)
    chat = FakeChat([])
    turn = make_conversation(chat, LocalActionExecutor(screen=screen)).respond("Screen off!")
    assert not screen.is_active()
    assert chat.messages == []
    assert turn.speech == "Screen access is off."
