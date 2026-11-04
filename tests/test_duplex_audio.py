"""Barge-in mechanics without accessing audio devices or running native code."""

import numpy as np

from jarvis.duplex_audio import DuplexMicStream
from jarvis.greetings import GREETINGS, next_greeting
from jarvis.llm import GeminiConversation


def test_varied_short_local_greeting_never_calls_a_model():
    conversation = GeminiConversation.__new__(GeminiConversation)
    previous = None
    for _ in range(30):
        reply = conversation.greet()
        assert reply.speech in GREETINGS
        assert reply.speech != previous
        assert len(reply.speech.split()) <= 5
        previous = reply.speech
    assert next_greeting() in GREETINGS
    assert conversation.idle_timeout().speech == ""


def test_sustained_voice_stops_playback_and_preserves_first_syllables(monkeypatch):
    mic = DuplexMicStream(vad=lambda *args: True)
    sent = []
    monkeypatch.setattr(mic, "_send", sent.append)
    mic.begin_speech()
    for index in range(3):
        mic._receive_pcm(np.full(1280, 300 + index, dtype="<i2").tobytes())
    assert mic.interrupted.is_set()
    assert sent == [{"command": "stop"}]
    mic.end_speech()
    assert mic.consume_interruption()
    assert not mic.consume_interruption()
    for index in range(3):
        assert mic.read_frame(timeout=0.01)[0] == 300 + index


def test_noise_or_one_brief_sound_does_not_interrupt(monkeypatch):
    mic = DuplexMicStream(vad=lambda *args: True)
    sent = []
    monkeypatch.setattr(mic, "_send", sent.append)
    mic.begin_speech()
    mic._receive_pcm(np.full(1280, 1000, dtype="<i2").tobytes())
    mic._receive_pcm(np.zeros(1280, dtype="<i2").tobytes())
    assert not sent
    assert not mic.interrupted.is_set()
    mic.end_speech()
    assert mic._queue.empty()


def test_non_speech_is_rejected_even_when_loud(monkeypatch):
    mic = DuplexMicStream(vad=lambda *args: False)
    sent = []
    monkeypatch.setattr(mic, "_send", sent.append)
    mic.begin_speech()
    for _ in range(20):
        mic._receive_pcm(np.full(1280, 9000, dtype="<i2").tobytes())
    assert not sent
    assert not mic.interrupted.is_set()
