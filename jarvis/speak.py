"""Text-to-speech via Kokoro-82M (kokoro-mlx), non-blocking by default.

Kokoro replaced the original Phase 2 pick, macOS `say` -- same free/local/
no-signup requirement as openWakeWord's replacement of Porcupine (PLAN.md
section 2), just for voice quality instead of wake-word licensing. Kokoro
runs locally via MLX (Apple Silicon only) and downloads its model weights
once, automatically, on first use.

Phase 1 risk (PLAN.md section 8): Jarvis can hear its own voice through the
mic and re-trigger. `is_speaking()` lets the main loop mute/ignore the wake
listener while Kokoro is talking -- wire that up once echo is actually
observed, don't guess at it now.
"""
from __future__ import annotations

import threading

from jarvis.config import VOICE_NAME, VOICE_SPEED

_lock = threading.Lock()
_speaking = threading.Event()
_tts = None  # lazy-loaded: importing kokoro_mlx pulls in MLX + downloads
             # model weights on first use, which we don't want to pay for
             # just to import jarvis.speak.


def _get_tts():
    global _tts
    if _tts is None:
        from kokoro_mlx import KokoroTTS

        _tts = KokoroTTS.from_pretrained()
    return _tts


def is_speaking() -> bool:
    """True while Kokoro is producing audio."""
    return _speaking.is_set()


def speak(
    text: str,
    *,
    voice: str | None = None,
    speed: float | None = None,
    blocking: bool = False,
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
            try:
                _get_tts().speak(text, voice=voice, speed=speed)
            finally:
                _speaking.clear()

    if blocking:
        _run()
    else:
        threading.Thread(target=_run, daemon=True).start()
