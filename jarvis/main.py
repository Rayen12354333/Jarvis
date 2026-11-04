"""Entry point: the wake -> listen -> transcribe -> Gemini -> speak loop.

Run the real voice loop:
    python -m jarvis.main

Or skip the mic entirely to test one Gemini prompt:
    python -m jarvis.main --text "what time is it"
"""

from __future__ import annotations

import argparse
import logging
import signal
import subprocess
import sys
import threading
import time
from contextlib import nullcontext

from jarvis.actions import ListeningVolumeGuard, LocalActionExecutor
from jarvis.audio import MicStream, record_utterance
from jarvis.config import (
    LOG_DIR,
    MUTE_OUTPUT_WHILE_LISTENING,
    SPEECH_START_TIMEOUT_S,
)
from jarvis.duplex_audio import create_voice_stream
from jarvis.llm import GeminiConversation
from jarvis.screen_access import ScreenAccessStore
from jarvis.speak import speak
from jarvis.speak import warm_up as warm_up_tts
from jarvis.status import publish_activity, record_action
from jarvis.stt import transcribe
from jarvis.stt import warm_up as warm_up_stt
from jarvis.timers import TimerManager, timer_alarm_message
from jarvis.wake import create_wake_model, listen_for_wake_word

LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "jarvis.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("jarvis")


def _beep() -> None:
    """Audible confirmation on wake-word detection (PLAN.md Phase 1 checkpoint).

    Plays an actual system sound in the background rather than relying on
    the terminal bell (muted by default in Terminal.app), so it's audible
    during the "test from 3-4m across the room" sensitivity check.
    """
    subprocess.Popen(
        ["afplay", "/System/Library/Sounds/Tink.aiff"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _say_to_user(mic: MicStream, *messages: str) -> None:
    """Pause the mic, speak one or more messages, then resume cleanly."""
    if not any(messages):
        return
    publish_activity("Speaking…")
    started = time.perf_counter()
    if hasattr(mic, "begin_speech"):
        mic.begin_speech()
        try:
            for message in messages:
                speak(
                    message,
                    blocking=True,
                    player=mic.play_audio,
                    should_stop=mic.interrupted.is_set,
                )
                if mic.interrupted.is_set():
                    break
        finally:
            mic.end_speech()
            log.info("interruptible speech finished in %.2fs", time.perf_counter() - started)
            publish_activity("Listening…" if mic.interrupted.is_set() else "Ready")
        return
    mic.stop()
    try:
        for message in messages:
            speak(message, blocking=True)
    finally:
        log.info("speech generation and playback completed in %.2fs", time.perf_counter() - started)
        mic.start()
        publish_activity("Ready")


def _announce_due_timers(mic: MicStream, timers: TimerManager) -> bool:
    """Speak every newly due alarm and report whether anything fired."""
    due = timers.pop_due()
    if not due:
        return False
    for timer in due:
        log.info("timer fired (id=%d, label=%r)", timer.timer_id, timer.label)
    _say_to_user(mic, *(timer_alarm_message(timer) for timer in due))
    return True


def _listen_for_text(
    mic: MicStream,
    timers: TimerManager | None = None,
    volume_guard: ListeningVolumeGuard | None = None,
) -> str:
    """Give the user a full start window, then transcribe one utterance."""
    while True:
        publish_activity("Listening…")
        guard = volume_guard.suppress_output() if volume_guard else nullcontext(False)
        preserve = getattr(mic, "consume_interruption", lambda: False)()
        with guard as newly_muted:
            if newly_muted:
                # Let the last sound already travelling through the room decay
                # before accepting a frame as the start of Rayen's request.
                time.sleep(0.16)
            # Drop speaker audio captured in the milliseconds before macOS mute
            # took effect, otherwise it could still trigger speech detection.
            if not preserve:
                mic.clear_pending_frames()
            pcm = record_utterance(
                mic,
                speech_start_timeout_s=SPEECH_START_TIMEOUT_S,
                should_interrupt=timers.has_due if timers is not None else None,
            )
        alarm_fired = (
            _announce_due_timers(mic, timers) if timers is not None and timers.has_due() else False
        )
        if pcm.size:
            publish_activity("Transcribing…")
            started = time.perf_counter()
            text = transcribe(pcm)
            log.info("transcription completed in %.2fs", time.perf_counter() - started)
            if text:
                print(f"[jarvis] heard: {text!r}")
            return text
        if not alarm_fired:
            return ""


def run_conversation(
    mic: MicStream,
    conversation: GeminiConversation | None = None,
    timers: TimerManager | None = None,
) -> None:
    """Run one stateful Gemini session after a wake-word detection."""
    owns_conversation = conversation is None
    action_executor = LocalActionExecutor(
        timers,
        activity_reporter=lambda state: publish_activity(state, action=True),
        result_reporter=record_action,
    )
    conversation = conversation or GeminiConversation(
        action_executor,
        activity_reporter=publish_activity,
    )
    volume_guard = ListeningVolumeGuard(action_executor, enabled=MUTE_OUTPUT_WHILE_LISTENING)
    patient_mode = False

    try:
        publish_activity("Thinking…")
        turn = conversation.greet()
        _say_to_user(mic, turn.speech)
        if turn.action == "sleep":
            return

        while True:
            text = _listen_for_text(mic, timers, volume_guard)
            if not text:
                if patient_mode or action_executor.screen.is_active():
                    continue
                publish_activity("Thinking…")
                turn = conversation.idle_timeout()
            else:
                # Every real utterance goes to the same Gemini chat. Gemini
                # answers, varies its own conversational handoff, and uses the
                # chat context to distinguish "yes, another" from "yes, done".
                publish_activity("Thinking…")
                started = time.perf_counter()
                turn = conversation.respond(text)
                log.info("response completed in %.2fs", time.perf_counter() - started)

            _say_to_user(mic, turn.speech)
            if turn.action == "sleep":
                action_executor.screen.stop()
                return
            if turn.action == "wait":
                patient_mode = True
    finally:
        publish_activity("Ready")
        if owns_conversation:
            conversation.close()


def run_text_mode(text: str, *, silent: bool = False) -> None:
    executor = LocalActionExecutor(
        activity_reporter=lambda state: publish_activity(state, action=True),
        result_reporter=record_action,
    )
    with GeminiConversation(executor, activity_reporter=publish_activity) as conversation:
        turn = conversation.respond(text)
    print(f"[jarvis] {turn.speech!r}")
    if not silent:
        speak(turn.speech, blocking=True)


def _warm_local_models() -> None:
    """Load local speech models before the first request whenever possible."""
    started = time.perf_counter()
    try:
        warm_up_tts()
        warm_up_stt()
    except Exception as exc:  # noqa: BLE001 -- lazy loading remains as fallback
        log.warning("background model warm-up failed: %s", exc)
        return
    log.info("local speech models warmed in %.2fs", time.perf_counter() - started)


def run_voice_loop() -> None:
    wake_model = create_wake_model()
    timers = TimerManager()
    threading.Thread(target=_warm_local_models, daemon=True).start()
    with create_voice_stream() as mic:
        publish_activity("Ready")
        print("[jarvis] listening for the wake word...")
        log.info("listening (threshold from .env WAKE_THRESHOLD)")
        while True:
            score = listen_for_wake_word(
                mic,
                wake_model,
                on_poll=lambda: _announce_due_timers(mic, timers),
            )
            _beep()
            log.info("wake word detected (score=%.3f)", score)
            print("[jarvis] wake word detected; starting conversation...")
            # openWakeWord keeps a rolling prediction buffer per wakeword across
            # calls (see openwakeword/model.py's Model.reset()). Without clearing
            # it here, residual state from the tail of the utterance that just
            # triggered detection can immediately re-trigger a second (or third,
            # fourth...) detection with no new speech behind it -- seen as bursts
            # of several "wake word detected" log lines within ~100ms of each
            # other. Reset right after each detection so the next check starts
            # clean.
            wake_model.reset()
            run_conversation(mic, timers=timers)
            publish_activity("Ready")
            print("[jarvis] resting; listening for the wake word...")
            log.info("conversation ended; listening for wake word")


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis voice assistant")
    parser.add_argument(
        "--silent",
        action="store_true",
        help="With --text, print the reply without playing audio",
    )
    parser.add_argument(
        "--text",
        metavar="TEXT",
        help="Skip the mic and ask Gemini directly, e.g. --text 'what time is it'",
    )
    args = parser.parse_args()
    # Menu Stop sends SIGTERM. Unwind the normal finally blocks so a temporary
    # listening mute is restored and an active speech subprocess is cleaned up.
    signal.signal(signal.SIGTERM, _request_shutdown)

    try:
        if args.text:
            run_text_mode(args.text, silent=args.silent)
        else:
            run_voice_loop()
    except KeyboardInterrupt:
        print("\n[jarvis] stopped.")
        sys.exit(0)
    finally:
        ScreenAccessStore().revoke()


def _request_shutdown(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


if __name__ == "__main__":
    main()
