"""Local echo-cancelled speech I/O and interrupt preservation for macOS."""

from __future__ import annotations

import base64
import json
import os
import queue
import subprocess
import tempfile
import threading
import time
import uuid
from collections import deque
from pathlib import Path

import numpy as np

from jarvis.audio import FRAME_LENGTH, MicStream, _rms
from jarvis.config import PROJECT_ROOT

SOURCE = PROJECT_ROOT / "native" / "VoiceIO.swift"
HELPER = PROJECT_ROOT / "build" / "jarvis-voice-io"


class DuplexMicStream:
    """Same pull interface as MicStream, plus AEC playback and voice interruption.

    Only echo-cancelled input can trigger interruption. The legacy mic never
    guesses at barge-in from raw speaker leakage. Buffers stay local/in memory.
    """

    def __init__(self, vad=None) -> None:
        if vad is None:
            import webrtcvad

            vad = webrtcvad.Vad(2).is_speech
        self._vad = vad
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=64)
        self._process = None
        self._reader = None
        self._write_lock = threading.Lock()
        self._ready = threading.Event()
        self.interrupted = threading.Event()
        self._armed = False
        self._preserve_next = False
        self._voiced = 0
        self._preroll: deque[np.ndarray] = deque(maxlen=5)
        self._pending = b""
        self._error = ""
        self._play_waiters: dict[str, threading.Event] = {}
        self._play_errors: dict[str, str] = {}

    def start(self) -> None:
        if self._process is not None:
            return
        if not HELPER.exists() or HELPER.stat().st_mtime < SOURCE.stat().st_mtime:
            HELPER.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    "/usr/bin/xcrun",
                    "swiftc",
                    "-O",
                    str(SOURCE),
                    "-o",
                    str(HELPER),
                    "-framework",
                    "AVFoundation",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
        self._process = subprocess.Popen(
            [str(HELPER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_messages, daemon=True)
        self._reader.start()
        if not self._ready.wait(timeout=8) or self._error:
            self.stop()
            raise RuntimeError(self._error or "Echo-cancelled microphone startup timed out")
        print("[audio] native echo cancellation and voice interruption enabled")

    def _send(self, item: dict) -> None:
        with self._write_lock:
            if self._process is None or self._process.poll() is not None:
                raise RuntimeError("Native audio helper stopped")
            self._process.stdin.write(json.dumps(item) + "\n")
            self._process.stdin.flush()

    def _read_messages(self) -> None:
        try:
            for line in self._process.stdout:
                item = json.loads(line)
                event = item.get("event")
                if event == "ready":
                    if item.get("echo_cancellation") is not True:
                        self._error = "Echo cancellation was not enabled"
                    self._ready.set()
                elif event == "error":
                    self._error = str(item.get("error", "Native audio failed"))
                    self._ready.set()
                elif event == "audio":
                    self._receive_pcm(base64.b64decode(item["pcm"], validate=True))
                elif event in {"played", "play_error"}:
                    identifier = item.get("id")
                    waiter = self._play_waiters.get(identifier)
                    if waiter:
                        if event == "play_error":
                            self._play_errors[identifier] = str(item.get("error"))
                        waiter.set()
        except Exception as exc:  # noqa: BLE001 -- surface helper failure on the main thread
            self._error = f"Native audio reader failed: {type(exc).__name__}"
        finally:
            if not self._ready.is_set():
                self._error = self._error or "Native audio helper exited during startup"
                self._ready.set()

    def _put_frame(self, frame: np.ndarray) -> None:
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
        self._queue.put_nowait(frame)

    def _receive_pcm(self, raw: bytes) -> None:
        self._pending += raw
        size = FRAME_LENGTH * 2
        while len(self._pending) >= size:
            data, self._pending = self._pending[:size], self._pending[size:]
            frame = np.frombuffer(data, dtype="<i2").copy()
            if self._armed and not self.interrupted.is_set():
                self._preroll.append(frame)
                # Four 20 ms VAD windows per frame; require 240 ms of sustained
                # speech plus energy, not a keyboard tap or one noisy callback.
                voice = (
                    _rms(frame) >= 250
                    and sum(
                        self._vad(data[index : index + 640], 16000) for index in range(0, size, 640)
                    )
                    >= 3
                )
                self._voiced = self._voiced + 1 if voice else 0
                if self._voiced >= 3:
                    self.clear_pending_frames()
                    for prior in list(self._preroll)[:-1]:
                        self._put_frame(prior)
                    self._preserve_next = True
                    self.interrupted.set()
                    self._send({"command": "stop"})
                    print("[audio] user speech interrupted Jarvis; preserving the utterance")
            self._put_frame(frame)

    def begin_speech(self) -> None:
        self.clear_pending_frames()
        self._preroll.clear()
        self._voiced = 0
        self.interrupted.clear()
        self._armed = True

    def end_speech(self) -> None:
        self._armed = False
        if not self.interrupted.is_set():
            self.clear_pending_frames()

    def consume_interruption(self) -> bool:
        preserve, self._preserve_next = self._preserve_next, False
        return preserve

    def clear_pending_frames(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def read_frame(self, timeout: float | None = None) -> np.ndarray:
        while True:
            try:
                return self._queue.get(timeout=1 if timeout is None else timeout)
            except queue.Empty:
                if self._error or self._process is None or self._process.poll() is not None:
                    raise RuntimeError(self._error or "Native audio helper exited")
                if timeout is not None:
                    raise

    def play_audio(self, audio: np.ndarray, sample_rate: int) -> None:
        from jarvis.speak import _write_wav

        if self.interrupted.is_set():
            return
        descriptor, raw_path = tempfile.mkstemp(prefix="jarvis-voice-", suffix=".wav")
        os.close(descriptor)
        path = Path(raw_path)
        identifier, done = uuid.uuid4().hex, threading.Event()
        self._play_waiters[identifier] = done
        try:
            _write_wav(path, audio, sample_rate)
            # Interruption may have happened while generating/writing audio.
            if self.interrupted.is_set():
                return
            self._send({"command": "play", "path": str(path), "id": identifier})
            deadline = time.monotonic() + len(audio) / sample_rate + 5
            while not done.wait(0.04):
                if self.interrupted.is_set():
                    self._send({"command": "stop"})
                    return
                if time.monotonic() > deadline or self._process.poll() is not None:
                    raise RuntimeError("Native speech playback did not complete")
            if identifier in self._play_errors:
                raise RuntimeError(self._play_errors.pop(identifier))
        finally:
            self._play_waiters.pop(identifier, None)
            path.unlink(missing_ok=True)

    def stop(self) -> None:
        process = self._process
        if process is None:
            return
        try:
            if process.poll() is None:
                self._send({"command": "quit"})
                process.stdin.close()
                process.wait(timeout=3)
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            process.kill()
            process.wait(timeout=2)
        finally:
            if self._reader is not None:
                self._reader.join(timeout=1)
            if process.stdout:
                process.stdout.close()
            self._process = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


def create_voice_stream():
    """Native AEC first; explicitly report any safe half-duplex fallback."""
    native = None
    try:
        native = DuplexMicStream()
        native.start()
        return native
    except Exception as exc:  # noqa: BLE001 -- keep basic voice working on unsupported routes
        if native is not None:
            native.stop()
        print(f"[audio] Voice interruption unavailable; using legacy audio: {exc}")
        return MicStream()
