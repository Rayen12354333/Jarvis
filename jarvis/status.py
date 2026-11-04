"""Tiny cross-process activity channel for the menu-bar controller."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from jarvis.config import LOG_DIR

STATUS_PATH = LOG_DIR / "activity.json"
HISTORY_PATH = LOG_DIR / "recent-actions.json"
MAX_RECENT_ACTIONS = 20
ACTION_VISIBILITY_SECONDS = 2.0
STALE_STATUS_SECONDS = 120.0

_write_lock = threading.Lock()


@dataclass(frozen=True)
class ActivityStatus:
    state: str
    updated_at: float
    last_action: str = ""
    last_action_at: float = 0.0

    def visible_text(self, now: float | None = None) -> str:
        now = time.time() if now is None else now
        if self.last_action and now - self.last_action_at < ACTION_VISIBILITY_SECONDS:
            return self.last_action
        return self.state


@dataclass(frozen=True)
class ActionReceipt:
    name: str
    result: str
    elapsed_s: float
    finished_at: float

    @property
    def failed(self) -> bool:
        return self.result.startswith("FAILED ")


def _clean(text: str) -> str:
    return " ".join(text.strip().split())[:60]


def read_activity(
    path: Path = STATUS_PATH,
    *,
    now: float | None = None,
    stale_after: float = STALE_STATUS_SECONDS,
) -> ActivityStatus | None:
    """Read a recent status, tolerating partial, missing, or old files."""
    now = time.time() if now is None else now
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        status = ActivityStatus(
            state=_clean(str(payload["state"])),
            updated_at=float(payload["updated_at"]),
            last_action=_clean(str(payload.get("last_action", ""))),
            last_action_at=float(payload.get("last_action_at", 0.0)),
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
    if (
        not status.state
        or not math.isfinite(status.updated_at)
        or status.updated_at > now + 60
        or now - status.updated_at > stale_after
    ):
        return None
    return status


def publish_activity(
    state: str,
    *,
    action: bool = False,
    path: Path = STATUS_PATH,
    now: float | None = None,
) -> None:
    """Atomically publish a short state while preserving recent action feedback."""
    clean_state = _clean(state)
    if not clean_state:
        return
    now = time.time() if now is None else now
    with _write_lock:
        previous = read_activity(path, now=now, stale_after=float("inf"))
        payload = {
            "state": clean_state,
            "updated_at": now,
            "last_action": previous.last_action if previous else "",
            "last_action_at": previous.last_action_at if previous else 0.0,
        }
        if action:
            payload["last_action"] = clean_state
            payload["last_action_at"] = now

        _atomic_write(path, payload)


def _atomic_write(path: Path, payload: object) -> None:
    """Best-effort private status storage; disk errors must not stop voice/actions."""
    raw_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, raw_path = tempfile.mkstemp(
            prefix=".jarvis-activity-", suffix=".tmp", dir=path.parent
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as status_file:
            json.dump(payload, status_file, separators=(",", ":"), allow_nan=False)
        os.replace(raw_path, path)
    except (OSError, ValueError):
        pass
    finally:
        if raw_path is not None:
            try:
                Path(raw_path).unlink(missing_ok=True)
            except OSError:
                pass


def read_receipts(path: Path = HISTORY_PATH) -> list[ActionReceipt]:
    """Newest last; tolerate damaged or missing local history."""
    try:
        if path.stat().st_size > 100_000:
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            return []
        receipts = []
        for item in payload[-MAX_RECENT_ACTIONS:]:
            receipt = ActionReceipt(
                name=_clean(str(item["name"])),
                result=str(item["result"])[:800],
                elapsed_s=float(item["elapsed_s"]),
                finished_at=float(item["finished_at"]),
            )
            if (
                not math.isfinite(receipt.elapsed_s)
                or receipt.elapsed_s < 0
                or not math.isfinite(receipt.finished_at)
            ):
                continue
            receipts.append(receipt)
        return receipts
    except (OSError, ValueError, TypeError, KeyError):
        return []


def record_action(
    name: str,
    result: str,
    elapsed_s: float,
    *,
    path: Path = HISTORY_PATH,
    now: float | None = None,
) -> None:
    """Keep bounded local evidence, not guesses about whether the user's task is done."""
    if not math.isfinite(elapsed_s):
        return
    # Provider exceptions sometimes include credentials. Never display common key forms.
    result = re.sub(r"(?:gsk_|sk-|AIza)[A-Za-z0-9_-]{16,}", "[redacted]", result)
    with _write_lock:
        records = [vars(item) for item in read_receipts(path)]
        records.append(
            {
                "name": _clean(name),
                "result": result[:800],
                "elapsed_s": round(max(0, elapsed_s), 3),
                "finished_at": time.time() if now is None else now,
            }
        )
        _atomic_write(path, records[-MAX_RECENT_ACTIONS:])


def clear_activity(path: Path = STATUS_PATH) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
