"""Phase 0 checkpoint (PLAN.md section 5).

Run with:
    python tests/audio_check.py

Confirms, before writing any real feature code, that:
  1. sounddevice can see at least one microphone.
  2. the Picovoice access key in .env is valid and the wake keyword loads.
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


def check_porcupine() -> None:
    print("\n[2/3] Porcupine access key + wake keyword:")
    try:
        from jarvis.config import WAKE_WORD
        from jarvis.wake import create_porcupine

        porcupine = create_porcupine()
        print(f"  keyword: '{WAKE_WORD}'")
        print(f"  frame length: {porcupine.frame_length} samples, sample rate: {porcupine.sample_rate} Hz")
        porcupine.delete()
        print("  OK")
    except Exception as exc:  # noqa: BLE001
        print(f"  X Porcupine failed to initialize: {exc}")
        print("    Check PICOVOICE_ACCESS_KEY in .env (free signup: https://console.picovoice.ai)")
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
    check_porcupine()
    check_mic_levels()
    print("\nPhase 0 checkpoint passed.")
