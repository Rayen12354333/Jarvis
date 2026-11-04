"""Speech-to-text via faster-whisper, loaded once and reused."""

from __future__ import annotations

import threading

import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.utils import download_model

from jarvis.config import SAMPLE_RATE, WHISPER_COMPUTE_TYPE, WHISPER_MODEL

_model: WhisperModel | None = None
_model_lock = threading.Lock()

# Whisper hallucinates short "thank you" / "bye" segments on near-silence.
# Drop anything below this confidence or above this no-speech probability.
# Tune these against real false-positive logs from Phase 1, not in the abstract.
MIN_AVG_LOGPROB = -1.0
MAX_NO_SPEECH_PROB = 0.6


def _get_model() -> WhisperModel:
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        print(f"[stt] loading {WHISPER_MODEL} ({WHISPER_COMPUTE_TYPE})...")
        model_source = WHISPER_MODEL
        try:
            # Resolve the already-downloaded snapshot without checking the
            # network every time the menu-bar listener is restarted.
            model_source = download_model(WHISPER_MODEL, local_files_only=True)
        except Exception:  # noqa: BLE001 -- Whisper downloads normally if absent
            pass
        _model = WhisperModel(
            model_source,
            device="cpu",
            compute_type=WHISPER_COMPUTE_TYPE,
        )
    return _model


def warm_up() -> None:
    """Load Whisper before the first utterance whenever startup time allows."""
    _get_model()


def transcribe(pcm_int16: np.ndarray) -> str:
    """Transcribe int16 PCM samples at 16 kHz to text.

    Returns "" (not raising) when there's nothing usable -- silence, a
    hallucinated fragment, or a low-confidence guess. Callers should treat an
    empty string as "say nothing back", not as an error.
    """
    if pcm_int16.size == 0:
        return ""
    audio = pcm_int16.astype(np.float32) / 32768.0
    duration = len(audio) / SAMPLE_RATE
    segments, _info = _get_model().transcribe(
        audio,
        language="en",
        vad_filter=True,
        beam_size=1,
        best_of=1,
        temperature=0.0,
        condition_on_previous_text=False,
        max_new_tokens=max(16, min(192, int(duration * 12))),
    )

    parts = []
    for segment in segments:
        if segment.no_speech_prob > MAX_NO_SPEECH_PROB:
            continue
        if segment.avg_logprob < MIN_AVG_LOGPROB:
            continue
        if getattr(segment, "compression_ratio", 0) > 2.4:
            continue
        parts.append(segment.text.strip())
    text = " ".join(parts).strip()
    # A one-second clip cannot contain a forty-word farewell. Never execute it.
    if len(text.split()) > max(8, duration * 5):
        print("[stt] discarded an implausibly long transcript for this short audio")
        return ""
    return text
