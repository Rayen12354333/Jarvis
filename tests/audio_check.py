"""Phase 0 checkpoint (PLAN.md section 5).

Run with:
    python tests/audio_check.py

Confirms, before writing any real feature code, that:
  1. sounddevice can see at least one microphone.
  2. openWakeWord's models download/load correctly (no signup needed -- see
     PLAN.md section 2 for why this replaced Porcupine).
  3. the mic actually captures sound (a non-silent peak amplitude).

This does NOT test wake-word detection itself -- that's Phase 1.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import sounddevice as sd

from jarvis.audio import list_input_devices
from jarvis.config import SAMPLE_RATE


def check_input_devices() -> None:
    print("\n[1/3] Input devices:")
    devices = list_input_devices()
    if not devices:
        print("  X No input devices found. Check System Settings > Privacy & Security > Microphone.")
        sys.exit(1)
    for d in devices:
        print(f"  - {d['name']}  ({d['max_input_channels']} ch, {d['default_samplerate']:.0f} Hz)")
    print("  OK")


def check_wake_model() -> None:
    print("\n[2/3] openWakeWord model (no signup needed):")
    try:
        from jarvis.config import WAKE_WORD_MODEL
        from jarvis.wake import create_wake_model

        model = create_wake_model()
        print(f"  model: '{WAKE_WORD_MODEL}'")
        print(f"  loaded models: {list(model.models.keys())}")

        # Which inference backend actually loaded matters: on Apple Silicon,
        # onnxruntime has a known, unfixed bug that returns near-zero wake-word
        # scores no matter what you say (openWakeWord issue #336). If tflite/
        # ai-edge-litert failed to import, openWakeWord silently falls back to
        # onnxruntime and this script would otherwise still print "OK".
        backend = type(model.models[WAKE_WORD_MODEL]).__module__
        if "onnxruntime" in backend:
            print(f"  X backend in use: {backend}")
            print("    openWakeWord silently fell back to onnxruntime, which has a known bug")
            print("    on Apple Silicon that returns near-zero scores for every prediction")
            print("    (https://github.com/dscripka/openWakeWord/issues/336). Wake-word")
            print("    detection will look like it 'works' here but will never actually fire.")
            print("    Fix: reinstall openwakeword from the pinned GitHub commit in")
            print("    requirements.txt (not the stale PyPI release) and make sure")
            print("    ai-edge-litert is installed:")
            print("      pip uninstall -y openwakeword")
            print("      pip install -r requirements.txt")
            sys.exit(1)
        print(f"  backend: {backend}")
        print("  OK")
    except Exception as exc:  # noqa: BLE001
        print(f"  X openWakeWord failed to initialize: {exc}")
        print("    On Apple Silicon this almost always means ai-edge-litert isn't installed:")
        print("    pip install ai-edge-litert")
        sys.exit(1)


def check_mic_levels(seconds: float = 3.0) -> None:
    print(f"\n[3/3] Recording {seconds:.0f}s -- say something out loud:")
    recording = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16")
    for remaining in range(int(seconds), 0, -1):
        print(f"  {remaining}...", end="\r")
        time.sleep(1)
    sd.wait()
    peak = int(np.abs(recording).max())
    print(f"  peak amplitude: {peak} / 32767")
    if peak < 500:
        print("  X Peak looks silent. Check mic permissions (Terminal/VS Code both need Microphone")
        print("    access) and that the right input device is selected.")
        sys.exit(1)
    print("  OK -- mic is capturing sound")


if __name__ == "__main__":
    check_input_devices()
    check_wake_model()
    check_mic_levels()
    print("\nPhase 0 checkpoint passed.")
