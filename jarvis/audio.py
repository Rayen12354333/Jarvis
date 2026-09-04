"""Microphone streaming and utterance recording."""
from __future__ import annotations

import queue
from dataclasses import dataclass, field

import numpy as np
import sounddevice as sd

from jarvis.config import MAX_RECORDING_S, SAMPLE_RATE, SILENCE_TIMEOUT_S

# Porcupine wants 512-sample frames at 16 kHz (32 ms). We reuse the same frame
# length for recording so wake.py and audio.py share one audio pipeline shape.
FRAME_LENGTH = 512

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
    _queue: "queue.Queue[np.ndarray]" = field(default_factory=queue.Queue, init=False, repr=False)
    _stream: sd.InputStream | None = field(default=None, init=False, repr=False)

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001, ARG002
        if status:
            print(f"[audio] stream status: {status}")
        self._queue.put(indata.copy().reshape(-1))

    def start(self) -> None:
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME_LENGTH,
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def read_frame(self, timeout: float | None = None) -> np.ndarray:
        """Block for the next FRAME_LENGTH-sample frame."""
        return self._queue.get(timeout=timeout)

    def __enter__(self) -> "MicStream":
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


def record_utterance(mic: MicStream) -> np.ndarray:
    """Record until ~SILENCE_TIMEOUT_S of quiet, capped at MAX_RECORDING_S.

    Call this right after wake-word detection. Returns int16 PCM samples at
    SAMPLE_RATE, ready for stt.transcribe().
    """
    frames: list[np.ndarray] = []
    silence_frames_needed = int(SILENCE_TIMEOUT_S * SAMPLE_RATE / FRAME_LENGTH)
    max_frames = int(MAX_RECORDING_S * SAMPLE_RATE / FRAME_LENGTH)
    silent_run = 0

    for _ in range(max_frames):
        frame = mic.read_frame()
        frames.append(frame)
        if _rms(frame) < SILENCE_RMS_THRESHOLD:
            silent_run += 1
            if silent_run >= silence_frames_needed and len(frames) > silence_frames_needed:
                break
        else:
            silent_run = 0

    return np.concatenate(frames) if frames else np.array([], dtype=np.int16)
