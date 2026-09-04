"""Speech-to-text via faster-whisper, loaded once and reused."""
from __future__ import annotations

import numpy as np
from faster_whisper import WhisperModel

from jarvis.config import WHISPER_COMPUTE_TYPE, WHISPER_MODEL

_model: WhisperModel | None = None

# Whisper hallucinates short "thank you" / "bye" segments on near-silence.
# Drop anything below this confidence or above this no-speech probability.
# Tune these against real false-positive logs from Phase 1, not in the abstract.
MIN_AVG_LOGPROB = -1.0
MAX_NO_SPEECH_PROB = 0.6


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        print(f"[stt] loading {WHISPER_MODEL} ({WHISPER_COMPUTE_TYPE})...")
        _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type=WHISPER_COMPUTE_TYPE)
    return _model


def transcribe(pcm_int16: np.ndarray) -> str:
    """Transcribe int16 PCM samples at 16 kHz to text.

    Returns "" (not raising) when there's nothing usable -- silence, a
    hallucinated fragment, or a low-confidence guess. Callers should treat an
    empty string as "say nothing back", not as an error.
    """
    if pcm_int16.size == 0:
        return ""
    audio = pcm_int16.astype(np.float32) / 32768.0
    segments, _info = _get_model().transcribe(audio, language="en", vad_filter=True)

    parts = []
    for segment in segments:
        if segment.no_speech_prob > MAX_NO_SPEECH_PROB:
            continue
        if segment.avg_logprob < MIN_AVG_LOGPROB:
            continue
        parts.append(segment.text.strip())
    return " ".join(parts).strip()
