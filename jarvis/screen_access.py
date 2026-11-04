"""Explicit, time-limited screen consent shared by voice and menu processes."""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jarvis.config import LOG_DIR

SCREEN_ACCESS_PATH = LOG_DIR / "screen-access.json"
MAX_ACCESS_SECONDS = 30 * 60


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


@dataclass(frozen=True)
class ScreenAccess:
    token: str
    started_at: float
    expires_at: float
    owner_pid: int


class ScreenAccessStore:
    def __init__(
        self,
        path: Path = SCREEN_ACCESS_PATH,
        *,
        clock: Callable[[], float] = time.time,
        is_alive: Callable[[int], bool] = _process_alive,
    ) -> None:
        self.path, self._clock, self._is_alive = path, clock, is_alive

    def read(self) -> ScreenAccess | None:
        try:
            if self.path.stat().st_size > 2048:
                return None
            item = json.loads(self.path.read_text(encoding="utf-8"))
            access = ScreenAccess(**item)
            now = self._clock()
            if (
                not isinstance(access.token, str)
                or len(access.token) != 32
                or not isinstance(access.owner_pid, int)
                or access.owner_pid <= 1
                or not all(math.isfinite(t) for t in (access.started_at, access.expires_at))
                or not access.started_at <= now < access.expires_at
                or not 0 < access.expires_at - access.started_at <= MAX_ACCESS_SECONDS
                or not self._is_alive(access.owner_pid)
            ):
                return None
            return access
        except (OSError, TypeError, ValueError):
            return None

    def remaining(self) -> float:
        access = self.read()
        return max(0, access.expires_at - self._clock()) if access else 0

    def grant(self, seconds: float = MAX_ACCESS_SECONDS) -> ScreenAccess:
        if not math.isfinite(seconds) or not 5 <= seconds <= MAX_ACCESS_SECONDS:
            raise ValueError("Screen access must last between 5 seconds and 30 minutes.")
        now = self._clock()
        access = ScreenAccess(uuid.uuid4().hex, now, now + seconds, os.getpid())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".screen-access-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(vars(access), stream)
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return access

    def revoke(self) -> None:
        self.path.unlink(missing_ok=True)
