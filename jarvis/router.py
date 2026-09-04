"""Handler registry: one regex pattern -> one function, decorator-based.

This is the whole point of the architecture (PLAN.md section 3): adding a
command means adding a file in handlers/, never touching this file or main.py.
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
    """Run the first matching handler on `text`. Returns its spoken reply, or None."""
    for h in _handlers:
        match = h.pattern.search(text)
        if match:
            print(f"[router] '{text}' -> {h.name}")
            return h.func(match, text)
    print(f"[router] '{text}' matched no handler")
    return None


def registered_handlers() -> list[str]:
    """Names of every registered handler, in registration order -- debugging/tests."""
    return [h.name for h in _handlers]
