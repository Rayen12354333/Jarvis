"""Microphone streaming and utterance recording."""
from __future__ import annotations

import math
import queue
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import sounddevice as sd

from jarvis.config import (
    MAX_RECORDING_S,
    SAMPLE_RATE,
    SILENCE_TIMEOUT_S,
    SPEECH_START_TIMEOUT_S,
)

# openWakeWord wants frames sized in multiples of 80ms. We reuse the same frame
# length (1280 samples @ 16kHz = 80ms) for recording so wake.py and audio.py
FRAME_LENGTH = 1280  # 80ms @ 16kHz -- must match wake.FRAME_LENGTH

# Frames below this RMS (int16 scale) count as "silence" for the recorder's
# stop condition. Tune this after Phase 1 sensitivity testing in a real room.
SILENCE_RMS_THRESHOLD = 150


@dataclass
class MicStream:
    """A pull-based wrapper around sounddevice's callback API.

    Usage:
        with MicStream() as mic:
            frame = mic.read_frame()  # blocks for one FRAME_LENGTH-sample chunk

    Only one MicStream should be open at a time -- share the instance between
    wake.py and audio.py rather than opening two streams.
    """

    device: int | None = None
    _queue: queue.Queue[np.ndarray] = field(
        default_factory=queue.Queue, init=False, repr=False
    )
    _stream: sd.InputStream | None = field(default=None, init=False, repr=False)

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001, ARG002
        if status:
            print(f"[audio] stream status: {status}")
        self._queue.put(indata.copy().reshape(-1))

    def start(self) -> None:
        if self._stream is not None:
            return
        # Frames captured before TTS was paused can otherwise be mistaken for
        # the user's next answer when the stream is restarted.
        self.clear_pending_frames()
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME_LENGTH,
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()

    def clear_pending_frames(self) -> None:
        """Discard audio already captured before a listening-state change."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def read_frame(self, timeout: float | None = None) -> np.ndarray:
        """Block for the next FRAME_LENGTH-sample frame."""
        return self._queue.get(timeout=timeout)

    def __enter__(self) -> MicStream:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()


def list_input_devices() -> list[dict]:
    """Available input devices, for tests/audio_check.py and debugging."""
    return [d for d in sd.query_devices() if d["max_input_channels"] > 0]


def _rms(frame: np.ndarray) -> float:
    if frame.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))


def record_utterance(
    mic: MicStream,
    *,
    speech_start_timeout_s: float | None = None,
    silence_timeout_s: float | None = None,
    max_recording_s: float | None = None,
    should_interrupt: Callable[[], bool] | None = None,
) -> np.ndarray:
    """Wait for speech, then record until quiet or the recording hard cap.

    The start timeout and end-of-speech timeout are intentionally independent:
    Jarvis can wait patiently for the user to begin without appending ten
    seconds of silence to every Whisper request. Returns an empty array if no
    speech begins before the start timeout.
    """
    speech_start_timeout_s = (
        SPEECH_START_TIMEOUT_S
        if speech_start_timeout_s is None
        else speech_start_timeout_s
    )
    silence_timeout_s = (
        SILENCE_TIMEOUT_S if silence_timeout_s is None else silence_timeout_s
    )
    max_recording_s = (
        MAX_RECORDING_S if max_recording_s is None else max_recording_s
    )

    start_frames = max(
        1, math.ceil(speech_start_timeout_s * SAMPLE_RATE / FRAME_LENGTH)
    )
    silence_frames_needed = max(
        1, math.ceil(silence_timeout_s * SAMPLE_RATE / FRAME_LENGTH)
    )
    max_frames = max(1, math.ceil(max_recording_s * SAMPLE_RATE / FRAME_LENGTH))

    # Preserve a tiny pre-roll so the beginning of the first spoken syllable
    # is not clipped when its first frame falls just below the RMS threshold.
    pre_roll: deque[np.ndarray] = deque(maxlen=2)
    frames: list[np.ndarray] = []
    for _ in range(start_frames):
        # Timers may interrupt the pre-speech wait so their alarm is timely.
        # Once speech begins we preserve the utterance rather than talking over
        # the user; the alarm is delivered immediately after it ends.
        if should_interrupt is not None and should_interrupt():
            return np.array([], dtype=np.int16)
        frame = mic.read_frame()
        if _rms(frame) < SILENCE_RMS_THRESHOLD:
            pre_roll.append(frame)
            continue
        frames.extend(pre_roll)
        frames.append(frame)
        break

    if not frames:
        return np.array([], dtype=np.int16)

    silent_run = 0
    for _ in range(max_frames - 1):
        frame = mic.read_frame()
        frames.append(frame)
        if _rms(frame) < SILENCE_RMS_THRESHOLD:
            silent_run += 1
            if silent_run >= silence_frames_needed:
                break
        else:
            silent_run = 0

    return np.concatenate(frames)
