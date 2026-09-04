"""Wake-word detection via Picovoice Porcupine."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pvporcupine

from jarvis.config import PICOVOICE_ACCESS_KEY, WAKE_SENSITIVITY, WAKE_WORD

if TYPE_CHECKING:
    from jarvis.audio import MicStream


def create_porcupine() -> pvporcupine.Porcupine:
    """Build a Porcupine instance for the configured wake word.

    WAKE_WORD must be one of Porcupine's free built-in keywords -- "jarvis"
    ships by default. See pvporcupine.KEYWORDS for the full list if you want
    to try a different one.
    """
    return pvporcupine.create(
        access_key=PICOVOICE_ACCESS_KEY,
        keywords=[WAKE_WORD],
        sensitivities=[WAKE_SENSITIVITY],
    )


def listen_for_wake_word(mic: "MicStream", porcupine: pvporcupine.Porcupine) -> None:
    """Block until the wake word fires once, consuming frames from `mic`.

    Porcupine fixes frame_length at 512 samples for its published models --
    this should always match audio.FRAME_LENGTH. The assert catches a mismatch
    early instead of silently never triggering.
    """
    assert porcupine.frame_length == 512, (
        f"Porcupine frame_length is {porcupine.frame_length}, expected 512 -- "
        "check audio.FRAME_LENGTH matches."
    )
    while True:
        frame = mic.read_frame()
        if porcupine.process(frame) >= 0:
            return
