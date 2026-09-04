"""Entry point: the wake -> listen -> transcribe -> route -> speak loop.

Run the real voice loop:
    python -m jarvis.main

Or skip the mic entirely to develop/test a handler (Track B, PLAN.md section 6):
    python -m jarvis.main --text "what time is it"
"""
from __future__ import annotations

import argparse
import sys

from jarvis import handlers  # noqa: F401  (importing this registers every handler)
from jarvis.audio import MicStream, record_utterance
from jarvis.router import dispatch
from jarvis.speak import speak
from jarvis.stt import transcribe
from jarvis.wake import create_wake_model, listen_for_wake_word


def run_text_mode(text: str) -> None:
    reply = dispatch(text)
    print(f"[jarvis] {reply!r}")
    if reply:
        speak(reply, blocking=True)


def run_voice_loop() -> None:
    wake_model = create_wake_model()
    with MicStream() as mic:
        print("[jarvis] listening for the wake word...")
        while True:
            listen_for_wake_word(mic, wake_model)
            print("[jarvis] wake word detected, recording...")
            pcm = record_utterance(mic)
            text = transcribe(pcm)
            if not text:
                continue
            print(f"[jarvis] heard: {text!r}")
            reply = dispatch(text)
            if reply:
                speak(reply)


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis voice assistant")
    parser.add_argument(
        "--text",
        metavar="TEXT",
        help="Skip the mic and route TEXT directly, e.g. --text 'what time is it'",
    )
    args = parser.parse_args()

    if args.text:
        run_text_mode(args.text)
        return

    try:
        run_voice_loop()
    except KeyboardInterrupt:
        print("\n[jarvis] stopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
