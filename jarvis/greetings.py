"""Tiny local wake acknowledgements; never wait on a model to start listening."""

import random

GREETINGS = ("At your service, sir.", "Yes, sir?", "I'm here, sir.", "Ready, sir.")
_previous: str | None = None


def next_greeting() -> str:
    global _previous
    _previous = random.choice([text for text in GREETINGS if text != _previous])
    return _previous
