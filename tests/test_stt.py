"""Speech-model initialization tests without loading Whisper."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from jarvis import stt


def test_warm_up_loads_whisper_without_transcribing(monkeypatch) -> None:
    loaded: list[bool] = []
    monkeypatch.setattr(stt, "_get_model", lambda: loaded.append(True))

    stt.warm_up()

    assert loaded == [True]


def test_short_audio_cannot_become_a_long_repeated_command(monkeypatch):
    options = {}

    def transcribe(audio, **kwargs):
        options.update(kwargs)
        return iter(
            [
                SimpleNamespace(
                    text="Have a good day. " * 9,
                    no_speech_prob=0,
                    avg_logprob=-0.2,
                    compression_ratio=1.5,
                )
            ]
        ), None

    monkeypatch.setattr(stt, "_get_model", lambda: SimpleNamespace(transcribe=transcribe))
    assert stt.transcribe(np.ones(17920, dtype=np.int16)) == ""
    assert options["temperature"] == 0.0
    assert options["beam_size"] == 1
    assert options["condition_on_previous_text"] is False
    assert options["max_new_tokens"] == 16


def test_normal_short_command_is_preserved(monkeypatch):
    segment = SimpleNamespace(
        text=" Open YouTube. ", no_speech_prob=0.1, avg_logprob=-0.4, compression_ratio=1.1
    )
    monkeypatch.setattr(
        stt,
        "_get_model",
        lambda: SimpleNamespace(transcribe=lambda *args, **kwargs: (iter([segment]), None)),
    )
    assert stt.transcribe(np.ones(16000, dtype=np.int16)) == "Open YouTube."
