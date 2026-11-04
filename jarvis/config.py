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
# Give the user time to start talking after Jarvis finishes its prompt.  This
# is deliberately separate from SILENCE_TIMEOUT_S: the latter detects when an
# utterance has ended, while this one controls how patient Jarvis is before it
# decides that nobody answered.
SPEECH_START_TIMEOUT_S = float(_get("SPEECH_START_TIMEOUT_S", "10.0"))
SILENCE_TIMEOUT_S = float(_get("SILENCE_TIMEOUT_S", "0.9"))
MAX_RECORDING_S = float(_get("MAX_RECORDING_S", "15.0"))
# Prevent a playing video or podcast from becoming the recorded request. Jarvis
# restores the previous mute state before transcribing or answering.
MUTE_OUTPUT_WHILE_LISTENING = str(
    _get("MUTE_OUTPUT_WHILE_LISTENING", "true")
).casefold() in {"1", "true", "yes", "on"}

# --- Speech-to-text ---------------------------------------------------------
WHISPER_MODEL = _get("WHISPER_MODEL", "base.en")
WHISPER_COMPUTE_TYPE = _get("WHISPER_COMPUTE_TYPE", "int8")

# --- Text-to-speech (Kokoro-82M, via kokoro-mlx) ---------------------------
# Kokoro voice id, e.g. "am_adam" (American male), "bm_lewis" (British male).
# Full list: https://github.com/gabrimatic/kokoro-mlx
VOICE_NAME = _get("VOICE_NAME", "am_adam")
VOICE_SPEED = float(_get("VOICE_SPEED", "1.0"))  # >1 faster, <1 slower

# --- Conversational brain (Gemini) ----------------------------------------
# Every utterance in a wake session goes through Gemini. Computer operations
# are still constrained to explicit, locally validated actions.
GEMINI_API_KEY = _get("GEMINI_API_KEY")
GEMINI_MODEL = _get("GEMINI_MODEL", "gemini-3.5-flash-lite")

# --- Optional second brain (GroqCloud) -------------------------------------
# Gemini remains the normal controller. A Groq-hosted model is available for
# deliberate second opinions and as a fallback when Gemini is unavailable.
GROQ_API_KEY = _get("GROQ_API_KEY")
GROQ_MODEL = _get("GROQ_MODEL", "openai/gpt-oss-120b")

# --- Logging ---------------------------------------------------------
LOG_DIR = Path(os.path.expanduser("~/Library/Logs/jarvis"))
