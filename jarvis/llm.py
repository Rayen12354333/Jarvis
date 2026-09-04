"""LLM fallback for commands no regex handler matches.

Uses Google's Gemini API (free tier: 1500 requests/day, no credit card --
see aistudio.google.com/apikey) rather than a paid API, to keep the
no-signup-cost philosophy this project has followed elsewhere (openWakeWord
over Porcupine, Kokoro over paid TTS). See PROGRESS.md for the cost/model
comparison this decision was based on.

Only called from router.dispatch() when nothing else matches.
"""
from __future__ import annotations

from jarvis.config import GEMINI_API_KEY, GEMINI_MODEL

_client = None  # lazy-loaded: importing google.genai shouldn't cost anything
                # until we actually need to call it.

SYSTEM_PROMPT = (
    "You are Jarvis, a voice assistant running locally on Rayen's Mac. "
    "Keep replies to 1-2 short sentences -- they get spoken aloud through "
    "text-to-speech, not read on screen. Be direct, no filler, no markdown."
)


def _get_client():
    global _client
    if _client is None:
        from google import genai

        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def ask_llm(text: str) -> str | None:
    """Send `text` to Gemini and return a short spoken reply, or None on failure."""
    if not GEMINI_API_KEY:
        print("[llm] no GEMINI_API_KEY set in .env, skipping LLM fallback")
        return None
    try:
        response = _get_client().models.generate_content(
            model=GEMINI_MODEL,
            contents=text,
            config={"system_instruction": SYSTEM_PROMPT},
        )
        return (response.text or "").strip() or None
    except Exception as exc:  # noqa: BLE001 -- never let a flaky API call crash the voice loop
        print(f"[llm] Gemini call failed: {exc}")
        return None
