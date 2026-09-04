"""Text-to-speech via macOS `say`, non-blocking by default.

Phase 1 risk (PLAN.md section 8): Jarvis can hear its own voice through the
mic and re-trigger. `is_speaking()` lets the main loop mute/ignore the wake
listener while `say` is talking -- wire that up in Phase 1 once echo is
actually observed, don't guess at it now.
"""
from __future__ import annotations

import subprocess
import threading

from jarvis.config import VOICE_NAME

_lock = threading.Lock()
_speaking = threading.Event()


def is_speaking() -> bool:
    """True while `say` is producing audio."""
    return _speaking.is_set()


def speak(text: str, *, voice: str | None = None, blocking: bool = False) -> None:
    """Speak `text` aloud. Runs in a background thread unless blocking=True.

    `voice` overrides VOICE_NAME (jarvis/config.py, set via .env) for this one
    call; leave both unset to use the system default voice.
    """
    if not text:
        return
    voice = voice or VOICE_NAME

    def _run() -> None:
        with _lock:
            _speaking.set()
            try:
                cmd = ["say"]
                if voice:
                    cmd += ["-v", voice]
                cmd.append(text)
                subprocess.run(cmd, check=False)
            finally:
                _speaking.clear()

    if blocking:
        _run()
    else:
        threading.Thread(target=_run, daemon=True).start()
