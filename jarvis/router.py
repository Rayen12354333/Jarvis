"""Legacy handler registry: one regex pattern -> one function.

The live voice and text paths now send every utterance to one stateful Gemini
conversation. This registry remains for old tests and as scaffolding while
deterministic computer actions are migrated into explicit Gemini tools.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from re import Match, Pattern

HandlerFunc = Callable[[Match[str], str], str | None]


@dataclass
class Handler:
    name: str
    pattern: Pattern[str]
    func: HandlerFunc


_handlers: list[Handler] = []


def handler(pattern: str, *, name: str) -> Callable[[HandlerFunc], HandlerFunc]:
    """Register `func` to run when `pattern` matches spoken text.

    Patterns are matched case-insensitively, in registration order (which
    follows handlers/__init__.py's import order). Put more specific patterns
    in modules imported earlier if two patterns could both match one phrase.
    """
    compiled = re.compile(pattern, re.IGNORECASE)

    def decorator(func: HandlerFunc) -> HandlerFunc:
        _handlers.append(Handler(name=name, pattern=compiled, func=func))
        return func

    return decorator


def dispatch(text: str) -> str | None:
    """Run the first matching handler on `text`, falling back to the LLM
    (jarvis/llm.py) if nothing matches. Returns the spoken reply, or None.
    """
    for h in _handlers:
        match = h.pattern.search(text)
        if match:
            print(f"[router] '{text}' -> {h.name}")
            return h.func(match, text)
    print(f"[router] '{text}' matched no handler, falling back to LLM")
    from jarvis.llm import ask_llm  # imported here so google-genai is only a
                                     # hard dependency for people using this
    return ask_llm(text)


def registered_handlers() -> list[str]:
    """Names of every registered handler, in registration order -- debugging/tests."""
    return [h.name for h in _handlers]
