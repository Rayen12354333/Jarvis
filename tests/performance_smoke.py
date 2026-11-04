"""Opt-in latency checks using synthetic screen pixels; never real screen/control.

PYTHONPATH=. .venv/bin/python tests/performance_smoke.py --live --tts
No audio is played. --tts measures local synthesis; --live uses a few Gemini calls.
"""

from __future__ import annotations

import argparse
import json
import time
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from jarvis.actions import LocalActionExecutor
from jarvis.llm import GeminiConversation
from jarvis.screen import ScreenVisionManager, prepare_screen_image


def visual_check():
    picture = Image.new("RGB", (2560, 1664), "white")
    draw = ImageDraw.Draw(picture)
    draw.text((900, 650), "42", fill="black", font=ImageFont.load_default(size=180))
    raw = BytesIO()
    picture.save(raw, format="PNG")
    captures = []
    screen = ScreenVisionManager(
        capture=lambda: captures.append(1) or raw.getvalue(),
        prepare_image=prepare_screen_image,
        foreground_pid=lambda: 123,
    )
    screen.start(1800)

    class NoMacActions(LocalActionExecutor):
        def _execute(self, action):
            if action.name == "inspect_screen":
                return super()._execute(action)
            raise RuntimeError("Real actions are disabled in this synthetic visual benchmark.")

    results = []
    with GeminiConversation(NoMacActions(screen=screen)) as conversation:
        for index in range(4):
            started = time.perf_counter()
            turn = conversation.respond(
                "What number is visible in the center? Answer only with the number."
            )
            elapsed = time.perf_counter() - started
            assert "42" in turn.speech, turn.speech
            old_pixels = sum(
                len(part.inline_data.data or b"")
                for content in conversation._chat.get_history(curated=True)
                for part in content.parts or []
                if part.inline_data is not None
            )
            assert old_pixels == 0, "Old pixels must not be uploaded with future requests"
            results.append(
                {
                    "request": index + 1,
                    "seconds": round(elapsed, 2),
                    "retained_image_bytes": old_pixels,
                }
            )
    assert len(captures) == 4, (
        "Each request should use one fresh observation, not repeated captures"
    )
    return results


def speech_check():
    from jarvis import speak

    started = time.perf_counter()
    speak.warm_up()
    warmup = time.perf_counter() - started
    measurements = []
    for sentence in ("Volume at fifty percent.", "Scrolled down."):
        started = time.perf_counter()
        result = speak._get_tts().generate(
            sentence, voice=speak.VOICE_NAME, speed=speak.VOICE_SPEED
        )
        measurements.append(
            {
                "text": sentence,
                "synthesis_seconds": round(time.perf_counter() - started, 2),
                "audio_seconds": round(result.duration, 2),
            }
        )
    return {"warmup_seconds": round(warmup, 2), "checks": measurements}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--tts", action="store_true")
    args = parser.parse_args()
    results = {}
    if args.live:
        results["visual_model_requests"] = visual_check()
    if args.tts:
        results["local_speech_no_playback"] = speech_check()
    if not results:
        parser.error("Choose --live and/or --tts explicitly.")
    print(json.dumps(results, indent=2))
