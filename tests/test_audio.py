"""Recorder behavior that can be verified without opening the real mic."""
from __future__ import annotations

import numpy as np

from jarvis.audio import FRAME_LENGTH, MicStream, record_utterance


class FakeMic:
    def __init__(self, frames: list[np.ndarray]) -> None:
        self.frames = iter(frames)
        self.read_count = 0

    def read_frame(self) -> np.ndarray:
        self.read_count += 1
        return next(self.frames)


def _frame(level: int) -> np.ndarray:
    return np.full(FRAME_LENGTH, level, dtype=np.int16)


def test_recorder_waits_for_speech_and_keeps_a_short_preroll() -> None:
    mic = FakeMic(
        [_frame(0), _frame(0), _frame(500), _frame(600), _frame(0), _frame(0)]
    )

    pcm = record_utterance(
        mic,
        speech_start_timeout_s=1.0,
        silence_timeout_s=0.16,
        max_recording_s=1.0,
    )

    assert mic.read_count == 6
    assert pcm.size == 6 * FRAME_LENGTH
    assert np.max(pcm) == 600


def test_recorder_returns_empty_only_after_start_timeout() -> None:
    mic = FakeMic([_frame(0), _frame(0), _frame(0)])

    pcm = record_utterance(mic, speech_start_timeout_s=0.24)

    assert mic.read_count == 3
    assert pcm.size == 0


def test_brief_pause_does_not_end_an_utterance() -> None:
    mic = FakeMic(
        [_frame(500), _frame(0), _frame(500), _frame(0), _frame(0)]
    )

    pcm = record_utterance(
        mic,
        speech_start_timeout_s=1.0,
        silence_timeout_s=0.16,
        max_recording_s=1.0,
    )

    assert mic.read_count == 5
    assert pcm.size == 5 * FRAME_LENGTH


def test_due_timer_interrupts_only_before_speech_starts() -> None:
    mic = FakeMic([_frame(0), _frame(0), _frame(500)])
    checks = iter([False, True])

    pcm = record_utterance(
        mic,
        speech_start_timeout_s=1.0,
        should_interrupt=lambda: next(checks),
    )

    assert mic.read_count == 1
    assert pcm.size == 0


def test_pending_speaker_audio_can_be_discarded_before_listening() -> None:
    mic = MicStream()
    mic._queue.put(_frame(500))
    mic._queue.put(_frame(600))

    mic.clear_pending_frames()

    assert mic._queue.empty()
