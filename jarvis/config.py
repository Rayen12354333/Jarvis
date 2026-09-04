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


# --- Wake word (openWakeWord) ---------------------------------------------
# No signup, no API key -- see PLAN.md section 2 for why this replaced
# Porcupine (Picovoice killed its free/non-commercial tier in mid-2026).
WAKE_WORD_MODEL = _get("WAKE_WORD_MODEL", "hey_jarvis")
WAKE_THRESHOLD = float(_get("WAKE_THRESHOLD", "0.5"))

# --- Audio ---------------------------------------------------------
SAMPLE_RATE = 16_000  # Hz -- fixed by openWakeWord and what we feed Whisper
SILENCE_TIMEOUT_S = 1.0  # stop recording after this much silence
MAX_RECORDING_S = 8.0  # hard cap on a single utterance

# --- Speech-to-text ---------------------------------------------------------
WHISPER_MODEL = _get("WHISPER_MODEL", "base.en")
WHISPER_COMPUTE_TYPE = _get("WHISPER_COMPUTE_TYPE", "int8")

# --- Text-to-speech (Kokoro-82M, via kokoro-mlx) ---------------------------
# Kokoro voice id, e.g. "am_adam" (American male), "bm_lewis" (British male).
# Full list: https://github.com/gabrimatic/kokoro-mlx
VOICE_NAME = _get("VOICE_NAME", "am_adam")
VOICE_SPEED = float(_get("VOICE_SPEED", "1.0"))  # >1 faster, <1 slower

# --- LLM fallback (Gemini) ---------------------------------------------
# Used only when no regex handler in router.py matches -- known commands
# (time, volume, etc.) never touch this, so they stay fast and free. Picked
# Gemini over Claude/GPT for the free tier: 1500 requests/day, no credit
# card (aistudio.google.com/apikey). See PROGRESS.md for the cost/model
# comparison this was based on.
GEMINI_API_KEY = _get("GEMINI_API_KEY")
GEMINI_MODEL = _get("GEMINI_MODEL", "gemini-2.5-flash-lite")

# --- Logging ---------------------------------------------------------
LOG_DIR = Path(os.path.expanduser("~/Library/Logs/jarvis"))
