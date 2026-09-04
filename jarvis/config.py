"""Environment variables and constants for Jarvis.

Everything here is read once at import time. Add new tunables as module-level
names, not scattered os.environ.get() calls in feature files.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root regardless of current working directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _get(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


# --- Wake word ---------------------------------------------------------
PICOVOICE_ACCESS_KEY = _get("PICOVOICE_ACCESS_KEY", required=True)
WAKE_WORD = _get("WAKE_WORD", "jarvis")  # must be a Porcupine built-in keyword
WAKE_SENSITIVITY = float(_get("WAKE_SENSITIVITY", "0.5"))

# --- Audio ---------------------------------------------------------
SAMPLE_RATE = 16_000  # Hz -- fixed by Porcupine and what we feed Whisper
SILENCE_TIMEOUT_S = 1.0  # stop recording after this much silence
MAX_RECORDING_S = 8.0  # hard cap on a single utterance

# --- Speech-to-text ---------------------------------------------------------
WHISPER_MODEL = _get("WHISPER_MODEL", "base.en")
WHISPER_COMPUTE_TYPE = _get("WHISPER_COMPUTE_TYPE", "int8")

# --- Logging ---------------------------------------------------------
LOG_DIR = Path(os.path.expanduser("~/Library/Logs/jarvis"))
