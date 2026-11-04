"""Kokoro generation and macOS playback tests without audible output."""

from __future__ import annotations

import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from jarvis import speak


def test_warm_up_loads_tts_without_speaking(monkeypatch) -> None:
    loaded: list[bool] = []
    monkeypatch.setattr(speak, "_greeting_audio", {})
    monkeypatch.setattr(
        speak,
        "_get_tts",
        lambda: SimpleNamespace(
            generate=lambda *args, **kwargs: (
                loaded.append(True) or SimpleNamespace(audio=np.zeros(24), sample_rate=24000)
            ),
        ),
    )

    speak.warm_up()

    assert loaded == [True] * len(speak.GREETINGS)
    speak.warm_up()
    assert len(loaded) == len(speak.GREETINGS)


def test_speak_generates_then_uses_stable_player(monkeypatch) -> None:
    audio = np.array([0.0, 0.25, -0.25], dtype=np.float32)

    class FakeTTS:
        def generate(self, text: str, *, voice: str, speed: float):
            assert text == "Good evening."
            assert voice == "test_voice"
            assert speed == 1.15
            return SimpleNamespace(audio=audio, sample_rate=24_000)

    played: list[tuple[np.ndarray, int]] = []
    monkeypatch.setattr(speak, "_get_tts", lambda: FakeTTS())
    monkeypatch.setattr(speak, "_play_audio", lambda samples, rate: played.append((samples, rate)))

    speak.speak("Good evening.", voice="test_voice", speed=1.15, blocking=True)

    assert len(played) == 1
    np.testing.assert_array_equal(played[0][0], audio)
    assert played[0][1] == 24_000
    assert not speak.is_speaking()


def test_write_wav_clamps_samples_and_fades_edges(tmp_path: Path) -> None:
    path = tmp_path / "speech.wav"
    audio = np.ones(1_000, dtype=np.float32) * 2.0

    speak._write_wav(path, audio, 24_000)

    with wave.open(str(path), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 24_000
        pcm = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype="<i2")

    assert len(pcm) == len(audio)
    assert pcm[0] == 0
    assert pcm[-1] == 0
    assert pcm.max() == 32767


def test_player_uses_afplay_and_removes_temporary_wav(monkeypatch) -> None:
    played_path: Path | None = None

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
        nonlocal played_path
        assert command[0] == "/usr/bin/afplay"
        played_path = Path(command[1])
        assert played_path.exists()
        with wave.open(str(played_path), "rb") as wav_file:
            assert wav_file.getframerate() == 24_000
        assert kwargs["check"] is True
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(speak.subprocess, "run", fake_run)

    speak._play_audio(np.zeros(240, dtype=np.float32), 24_000)

    assert played_path is not None
    assert not played_path.exists()


def test_first_sentence_plays_before_later_sentence_is_generated(monkeypatch):
    events = []

    def generate(text, **kwargs):
        events.append(("generate", text))
        return SimpleNamespace(audio=np.zeros(24), sample_rate=24000)

    monkeypatch.setattr(speak, "_get_tts", lambda: SimpleNamespace(generate=generate))
    monkeypatch.setattr(speak, "_play_audio", lambda *args: events.append(("play", "")))
    speak.speak("First sentence. Second sentence.", blocking=True)
    assert events == [
        ("generate", "First sentence."),
        ("play", ""),
        ("generate", "Second sentence."),
        ("play", ""),
    ]


def test_speech_chunking_preserves_every_word():
    text = " ".join(f"word{index}" for index in range(90))
    chunks = speak.speech_chunks(text)
    assert all(len(chunk.split()) <= 30 for chunk in chunks)
    assert " ".join(chunks) == text


def test_interrupt_during_synthesis_does_not_play_or_generate_more(monkeypatch):
    cancelled, generated = [False], []

    def generate(text, **kwargs):
        generated.append(text)
        cancelled[0] = True
        return SimpleNamespace(audio=np.zeros(24), sample_rate=24000)

    monkeypatch.setattr(speak, "_get_tts", lambda: SimpleNamespace(generate=generate))
    played = []
    speak.speak(
        "One. Two.",
        blocking=True,
        should_stop=lambda: cancelled[0],
        player=lambda *args: played.append(True),
    )
    assert generated == ["One."]
    assert not played
