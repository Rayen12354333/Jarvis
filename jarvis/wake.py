"""Wake-word detection via openWakeWord.

Replaces the Porcupine-based version from PLAN.md's original Phase 1 --
Picovoice discontinued its free/non-commercial tier in mid-2026 and now
requires a company email + paid plan, which isn't viable for a student
project. See PLAN.md section 2 for the full writeup.

openWakeWord ships a pretrained "hey jarvis" model (close enough to our
"Jarvis" wake word) and needs no signup or key. On Apple Silicon it defaults
to the tflite backend via the `ai-edge-litert` package -- the onnx backend has
a known bug on macOS ARM64 (near-zero scores, see
https://github.com/dscripka/openWakeWord/issues/336), but tflite via
ai-edge-litert sidesteps it entirely and is the library's default anyway.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import openwakeword
from openwakeword.model import Model

from jarvis.config import WAKE_THRESHOLD, WAKE_WORD_MODEL

if TYPE_CHECKING:
    from jarvis.audio import MicStream

# openWakeWord wants frames sized in multiples of 80ms. This must match
# audio.FRAME_LENGTH (1280 samples @ 16kHz = 80ms).
FRAME_LENGTH = 1280


def create_wake_model() -> Model:
    """Build an openWakeWord Model for the configured wake word.

    One-time model download happens automatically on first run (cached under
    ~/.local/share or similar -- see openwakeword.utils.download_models()).
    """
    openwakeword.utils.download_models()
    return Model(wakeword_models=[WAKE_WORD_MODEL])


def listen_for_wake_word(mic: "MicStream", model: Model) -> float:
    """Block until the wake word fires once, then return its score.

    The caller (jarvis/main.py) logs this score on every detection -- real
    hits and false positives alike -- which is what Phase 1's sensitivity
    tuning and false-positive tracking (PLAN.md section 5) actually run on.
    """
    while True:
        frame = mic.read_frame()
        prediction = model.predict(frame)
        score = prediction.get(WAKE_WORD_MODEL, 0.0)
        if score >= WAKE_THRESHOLD:
            return score
