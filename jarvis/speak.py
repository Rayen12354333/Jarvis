"""Text-to-speech via Kokoro-82M (kokoro-mlx), non-blocking by default.

Kokoro replaced the original Phase 2 pick, macOS `say` -- same free/local/
no-signup requirement as openWakeWord's replacement of Porcupine (PLAN.md
section 2), just for voice quality instead of wake-word licensing. Kokoro
runs locally via MLX (Apple Silicon only) and downloads its model weights
once, automatically, on first use.

Kokoro generates the waveform, then macOS ``afplay`` sends one finished WAV
through CoreAudio. This avoids Kokoro's default ``sounddevice`` output stream,
which can crackle when the built-in input and output devices use different
sample rates. A short edge fade also prevents start/end clicks.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
import time
import wave
from collections.abc import Callable
from pathlib import Path

import numpy as np

from jarvis.config import VOICE_NAME, VOICE_SPEED
from jarvis.greetings import GREETINGS

_lock = threading.Lock()
_speaking = threading.Event()
_tts = None  # lazy-loaded: importing kokoro_mlx pulls in MLX + downloads
_greeting_audio: dict[tuple[str, str, float], tuple[np.ndarray, int]] = {}
# model weights on first use, which we don't want to pay for
# just to import jarvis.speak.
KOKORO_MODEL_ID = "mlx-community/Kokoro-82M-bf16"


def _get_tts():
    global _tts
    if _tts is None:
        from huggingface_hub import snapshot_download
        from kokoro_mlx import KokoroTTS

        model_source = KOKORO_MODEL_ID
        try:
            # Avoid a network revision check on every Jarvis restart when the
            # complete model is already in Hugging Face's local cache.
            model_source = snapshot_download(
                repo_id=KOKORO_MODEL_ID,
                local_files_only=True,
            )
        except Exception:  # noqa: BLE001 -- normal loader can download if absent
            pass
        _tts = KokoroTTS.from_pretrained(model_source)
    return _tts


def warm_up() -> None:
    """Load the TTS model without speaking, safe to call in the background."""
    with _lock:
        for text in GREETINGS:
            _synthesize(text, VOICE_NAME, VOICE_SPEED)


def _synthesize(text: str, voice: str, speed: float) -> tuple[np.ndarray, int]:
    key = (text, voice, speed)
    if key not in _greeting_audio:
        result = _get_tts().generate(text, voice=voice, speed=speed)
        audio = np.asarray(result.audio, dtype=np.float32).copy()
        if text not in GREETINGS:
            return audio, result.sample_rate
        _greeting_audio[key] = (audio, result.sample_rate)
    return _greeting_audio[key]


def speech_chunks(text: str) -> list[str]:
    """Start speaking at the first sentence instead of synthesizing the whole reply."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks = []
    for sentence in sentences:
        words = sentence.split()
        # Bound even a long sentence; preserve every word rather than truncating.
        while len(words) > 30:
            chunks.append(" ".join(words[:30]))
            words = words[30:]
        if words:
            chunks.append(" ".join(words))
    return chunks


def is_speaking() -> bool:
    """True while Kokoro is producing audio."""
    return _speaking.is_set()


def _write_wav(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    """Write mono float audio as a click-free 16-bit PCM WAV."""
    samples = np.asarray(audio, dtype=np.float32).reshape(-1).copy()
    samples = np.nan_to_num(samples, nan=0.0, posinf=1.0, neginf=-1.0)
    np.clip(samples, -1.0, 1.0, out=samples)

    # Even a tiny non-zero sample at a playback boundary can sound like a pop.
    fade_samples = min(int(sample_rate * 0.008), len(samples) // 2)
    if fade_samples:
        fade_in = np.linspace(0.0, 1.0, fade_samples, endpoint=False)
        fade_out = np.linspace(1.0, 0.0, fade_samples)
        samples[:fade_samples] *= fade_in
        samples[-fade_samples:] *= fade_out

    pcm = (samples * 32767.0).astype("<i2", copy=False)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())


def _play_audio(audio: np.ndarray, sample_rate: int) -> None:
    """Play generated speech through one stable macOS CoreAudio process."""
    descriptor, raw_path = tempfile.mkstemp(prefix="jarvis-tts-", suffix=".wav")
    os.close(descriptor)
    path = Path(raw_path)
    try:
        _write_wav(path, audio, sample_rate)
        duration = len(np.asarray(audio).reshape(-1)) / sample_rate
        subprocess.run(
            ["/usr/bin/afplay", str(path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=max(15.0, duration + 10.0),
        )
    finally:
        path.unlink(missing_ok=True)


def speak(
    text: str,
    *,
    voice: str | None = None,
    speed: float | None = None,
    blocking: bool = False,
    player: Callable[[np.ndarray, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Speak `text` aloud. Runs in a background thread unless blocking=True.

    `voice`/`speed` override VOICE_NAME/VOICE_SPEED (jarvis/config.py, set
    via .env) for this one call.
    """
    if not text:
        return
    voice = voice or VOICE_NAME
    speed = speed if speed is not None else VOICE_SPEED

    def _run() -> None:
        with _lock:
            _speaking.set()
            started = time.perf_counter()
            try:
                for index, chunk in enumerate(speech_chunks(text)):
                    if should_stop is not None and should_stop():
                        break
                    audio, sample_rate = _synthesize(chunk, voice, speed)
                    if should_stop is not None and should_stop():
                        break
                    if index == 0:
                        elapsed = time.perf_counter() - started
                        print(f"[latency] first speech audio ready: {elapsed:.2f}s")
                    (player or _play_audio)(audio, sample_rate)
            finally:
                _speaking.clear()

    if blocking:
        _run()
    else:
        threading.Thread(target=_run, daemon=True).start()
