"""Non-blocking, text-only menu requests with one serialized conversation."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jarvis.actions import LocalActionExecutor
from jarvis.status import publish_activity, record_action


@dataclass(frozen=True)
class CommandReply:
    text: str
    elapsed_s: float
    failed: bool = False


class CommandSession:
    """Keep typed follow-up context; never run two requests concurrently."""

    def __init__(self, factory: Callable[..., Any] | None = None) -> None:
        self._factory = factory
        self._conversation: Any | None = None
        self._lock = threading.Lock()
        self._busy = False
        self._closed = False
        self._cancel = threading.Event()
        self._replies: queue.Queue[CommandReply] = queue.Queue()

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def submit(self, text: str) -> bool:
        text = text.strip()
        if not text or len(text) > 6000:
            raise ValueError("Enter a request between 1 and 6,000 characters.")
        with self._lock:
            if self._busy or self._closed:
                return False
            self._busy = True
            self._cancel.clear()
        threading.Thread(target=self._run, args=(text,), daemon=True).start()
        return True

    def cancel(self) -> None:
        """An operation already sent to macOS cannot be undone by cancellation."""
        self._cancel.set()

    def take_reply(self) -> CommandReply | None:
        try:
            return self._replies.get_nowait()
        except queue.Empty:
            return None

    def _create_conversation(self) -> Any:
        if self._factory is not None:
            return self._factory()
        from jarvis.llm import GeminiConversation

        executor = LocalActionExecutor(
            activity_reporter=lambda state: publish_activity(state, action=True),
            result_reporter=record_action,
        )
        return GeminiConversation(
            executor,
            activity_reporter=publish_activity,
            should_cancel=self._cancel.is_set,
        )

    def _run(self, text: str) -> None:
        started = time.perf_counter()
        try:
            publish_activity("Thinking…")
            if self._conversation is None:
                self._conversation = self._create_conversation()
            turn = self._conversation.respond(text)
            if self._cancel.is_set():
                reply = "Cancelled. Actions already sent may have completed; check Recent Actions."
            else:
                reply = turn.speech
            self._replies.put(CommandReply(reply, time.perf_counter() - started))
            if turn.action == "sleep" or self._cancel.is_set():
                self._close_conversation()
        except Exception as exc:  # noqa: BLE001 -- report failures without crashing the menu
            self._replies.put(
                CommandReply(
                    f"The request failed ({type(exc).__name__}). "
                    "Check Setup & Permissions and retry.",
                    time.perf_counter() - started,
                    failed=True,
                )
            )
            self._close_conversation()
        finally:
            publish_activity("Ready")
            with self._lock:
                self._busy = False
                if self._closed:
                    self._close_conversation()

    def _close_conversation(self) -> None:
        conversation, self._conversation = self._conversation, None
        if conversation is not None:
            try:
                conversation.close()
            except Exception:  # noqa: BLE001 -- cleanup must not strand the busy state
                pass

    def close(self) -> None:
        self.cancel()
        with self._lock:
            self._closed = True
            if not self._busy:
                self._close_conversation()
