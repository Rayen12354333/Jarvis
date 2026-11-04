"""Time-limited, ephemeral macOS screen capture for Gemini vision."""

from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal

from jarvis.screen_access import ScreenAccessStore
from jarvis.timers import format_duration

MIN_SCREEN_SESSION_SECONDS = 5.0
MAX_SCREEN_SESSION_SECONDS = 30 * 60.0
MAX_SCREENSHOT_BYTES = 20_000_000
MAX_SCREENSHOT_AGE_FOR_CLICK_SECONDS = 15.0

ScrollDirection = Literal["up", "down", "left", "right"]


@dataclass(frozen=True)
class ScreenCapture:
    """An ephemeral image that should be sent to Gemini, then discarded."""

    image_bytes: bytes
    question: str
    purpose: str
    mime_type: str = "image/png"


def prepare_screen_image(raw: bytes) -> tuple[bytes, str]:
    """Bound cloud upload size while preserving the image aspect/coordinate space."""
    from PIL import Image

    with Image.open(BytesIO(raw)) as picture:
        picture.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        output = BytesIO()
        picture.convert("RGB").save(output, format="JPEG", quality=85)
    return output.getvalue(), "image/jpeg"


def capture_main_display() -> bytes:
    """Capture the main macOS display to a temporary PNG and remove the file."""
    if sys.platform != "darwin":
        raise RuntimeError("Screen capture is only available on macOS.")

    file_descriptor, raw_path = tempfile.mkstemp(prefix="jarvis-screen-", suffix=".png")
    os.close(file_descriptor)
    path = Path(raw_path)
    try:
        try:
            subprocess.run(
                ["/usr/sbin/screencapture", "-x", "-m", "-t", "png", str(path)],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").strip() or str(exc)
            raise RuntimeError(f"macOS screen capture failed: {detail}") from exc

        size = path.stat().st_size
        if size <= 0:
            raise RuntimeError(
                "The screenshot was empty. Grant Screen Recording permission to "
                "the app or terminal running Jarvis."
            )
        if size > MAX_SCREENSHOT_BYTES:
            raise RuntimeError("The screenshot exceeded the 20 MB safety limit.")
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def _require_accessibility_permission() -> None:
    """Fail clearly when macOS has not authorized synthetic input events."""
    if sys.platform != "darwin":
        raise RuntimeError("Screen control is only available on macOS.")

    from ApplicationServices import (
        AXIsProcessTrusted,
        AXIsProcessTrustedWithOptions,
        kAXTrustedCheckOptionPrompt,
    )

    if not AXIsProcessTrusted():
        # The user explicitly requested an input action, so ask macOS to show
        # its one-time consent UI. Jarvis never interacts with that dialog.
        AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
        raise RuntimeError(
            "Accessibility permission is required. Open System Settings > Privacy "
            "& Security > Accessibility, enable the app running Jarvis, then "
            "restart Jarvis."
        )


def post_scroll_event(direction: ScrollDirection, amount: int) -> None:
    """Post one bounded macOS scroll-wheel event to the active application."""
    _require_accessibility_permission()

    import Quartz

    vertical = 0
    horizontal = 0
    if direction == "up":
        vertical = amount
    elif direction == "down":
        vertical = -amount
    elif direction == "left":
        horizontal = amount
    elif direction == "right":
        horizontal = -amount
    else:
        raise ValueError(f"Unsupported scroll direction: {direction!r}")

    event = Quartz.CGEventCreateScrollWheelEvent(
        None,
        Quartz.kCGScrollEventUnitLine,
        2,
        vertical,
        horizontal,
    )
    if event is None:
        raise RuntimeError("macOS could not create the requested scroll event.")
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def post_click_event(x: int, y: int) -> None:
    """Click a normalized point on the main display (0..1000 on each axis)."""
    _require_accessibility_permission()

    import Quartz

    display_id = Quartz.CGMainDisplayID()
    bounds = Quartz.CGDisplayBounds(display_id)
    if bounds.size.width <= 0 or bounds.size.height <= 0:
        raise RuntimeError("macOS could not determine the main display bounds.")

    point = Quartz.CGPointMake(
        bounds.origin.x + (bounds.size.width * x / 1000),
        bounds.origin.y + (bounds.size.height * y / 1000),
    )
    events = (
        Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventMouseMoved, point, Quartz.kCGMouseButtonLeft
        ),
        Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventLeftMouseDown, point, Quartz.kCGMouseButtonLeft
        ),
        Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventLeftMouseUp, point, Quartz.kCGMouseButtonLeft
        ),
    )
    if any(event is None for event in events):
        raise RuntimeError("macOS could not create the requested mouse event.")

    Quartz.CGEventPost(Quartz.kCGHIDEventTap, events[0])
    # Leave the cursor at the located target briefly so the user can see what
    # Jarvis selected before the click lands.
    time.sleep(0.08)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, events[1])
    time.sleep(0.04)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, events[2])


def foreground_application_pid() -> int:
    """Read only the foreground process identity, without app text or screenshots."""
    if sys.platform != "darwin":
        raise RuntimeError("Screen focus checks are only available on macOS.")
    try:
        from AppKit import NSWorkspace

        application = NSWorkspace.sharedWorkspace().frontmostApplication()
        pid = int(application.processIdentifier()) if application is not None else 0
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "Could not identify the foreground app; screen control stopped."
        ) from exc
    if pid <= 0:
        raise RuntimeError("No foreground app could be identified; screen control stopped.")
    return pid


class ScreenVisionManager:
    """Authorize current-screen snapshots for one short, explicit time window."""

    def __init__(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        capture: Callable[[], bytes] = capture_main_display,
        scroll: Callable[[ScrollDirection, int], None] = post_scroll_event,
        click: Callable[[int, int], None] = post_click_event,
        foreground_pid: Callable[[], int] | None = None,
        prepare_image: Callable[[bytes], tuple[bytes, str]] | None = None,
        access_store: ScreenAccessStore | None = None,
    ) -> None:
        self._monotonic = monotonic
        self._access_store = access_store
        self._access_token: str | None = None
        self._capture = capture
        self._scroll = scroll
        self._click = click
        self._foreground_pid = foreground_pid or foreground_application_pid
        # Injected capture adapters keep their own encoding unless requested;
        # the production screenshot path always uses a bounded JPEG upload.
        self._prepare_image = prepare_image or (
            prepare_screen_image
            if capture is capture_main_display
            else lambda raw: (raw, "image/png")
        )
        self._allowed_until = 0.0
        self._purpose = ""
        self._last_capture_at: float | None = None
        self._last_capture_pid: int | None = None
        self._revision = 0
        self._lock = threading.Lock()

    def _sync_access(self) -> None:
        if self._access_store is None:
            return
        access = self._access_store.read()
        token = access.token if access else None
        remaining = self._access_store.remaining() if access else 0
        with self._lock:
            if token != self._access_token:
                self._invalidate_capture()
                self._access_token = token
                self._allowed_until = self._monotonic() + remaining
            elif access is not None:
                self._allowed_until = min(self._allowed_until, self._monotonic() + remaining)
            if access is None:
                self._allowed_until = 0

    def _invalidate_capture(self) -> None:
        """Call under the lock to revoke both pending and completed observations."""
        self._last_capture_at = None
        self._last_capture_pid = None
        self._revision += 1

    def start(self, seconds: float, purpose: str | None = None) -> str:
        if not math.isfinite(seconds):
            raise ValueError("Screen-vision duration must be finite.")
        if not MIN_SCREEN_SESSION_SECONDS <= seconds <= MAX_SCREEN_SESSION_SECONDS:
            raise ValueError("Screen vision must be limited to between 5 seconds and 30 minutes.")

        clean_purpose = " ".join((purpose or "screen assistance").strip().split())[:300]
        if self._access_store is not None:
            self._access_store.grant(seconds)
            self._sync_access()
        with self._lock:
            self._allowed_until = self._monotonic() + seconds
            self._purpose = clean_purpose
            self._invalidate_capture()
        return (
            f"Screen vision authorized for {format_duration(seconds)} for "
            f"{clean_purpose!r}. Screenshots are captured only on request."
        )

    def remaining_seconds(self) -> float:
        self._sync_access()
        with self._lock:
            return max(0.0, self._allowed_until - self._monotonic())

    def is_active(self) -> bool:
        return self.remaining_seconds() > 0

    def status(self) -> str:
        remaining = self.remaining_seconds()
        if remaining <= 0:
            return "Screen vision is not active."
        with self._lock:
            purpose = self._purpose
        return (
            f"Screen vision is active for about {format_duration(remaining)} more for {purpose!r}."
        )

    def stop(self) -> str:
        self._sync_access()
        if self._access_store is not None:
            self._access_store.revoke()
        with self._lock:
            was_active = self._allowed_until > self._monotonic()
            self._allowed_until = 0.0
            self._purpose = ""
            self._invalidate_capture()
        if was_active:
            return "Screen vision stopped and its authorization was cleared."
        return "Screen vision was already inactive."

    def capture(self, question: str | None = None) -> ScreenCapture:
        self._sync_access()
        with self._lock:
            # Failed or overlapping capture attempts must not leave a previous
            # screenshot's click permission behind.
            self._invalidate_capture()
            revision = self._revision
            remaining = self._allowed_until - self._monotonic()
            purpose = self._purpose
        if remaining <= 0:
            raise RuntimeError(
                "Screen vision is not authorized or its time limit expired. "
                "Ask the user to authorize another limited session."
            )

        clean_question = " ".join(
            (question or "Describe the current screen and help with the active task.")
            .strip()
            .split()
        )[:500]
        observed_pid = self._foreground_pid()
        image_bytes = self._capture()
        original_bytes = len(image_bytes)
        image_bytes, mime_type = self._prepare_image(image_bytes)
        print(f"[screen] upload image: {original_bytes} -> {len(image_bytes)} bytes")
        current_pid = self._foreground_pid()
        self._sync_access()
        with self._lock:
            now = self._monotonic()
            if self._revision != revision or self._allowed_until - now <= 0:
                raise RuntimeError(
                    "Screen authorization expired, was revoked, or the view changed during "
                    "capture. The screenshot was discarded; authorize and inspect again."
                )
            if observed_pid != current_pid:
                raise RuntimeError(
                    "The foreground app changed during screen capture. The screenshot was "
                    "discarded; inspect the intended app again."
                )
            self._last_capture_at = now
            self._last_capture_pid = observed_pid
        return ScreenCapture(
            image_bytes=image_bytes,
            question=clean_question,
            purpose=purpose,
            mime_type=mime_type,
        )

    def scroll(self, direction: ScrollDirection, amount: int = 5) -> str:
        """Scroll the active app during an authorized screen-control session."""
        if direction not in {"up", "down", "left", "right"}:
            raise ValueError("Scroll direction must be up, down, left, or right.")
        if not 1 <= amount <= 10:
            raise ValueError("Scroll amount must be between 1 and 10.")

        self._sync_access()
        with self._lock:
            if self._allowed_until - self._monotonic() <= 0:
                raise RuntimeError(
                    "Screen control is not authorized or its time limit expired. "
                    "Ask the user to authorize another limited session."
                )
            self._invalidate_capture()

        self._scroll(direction, amount)
        return f"Scroll event sent {direction}; movement has not been verified."

    def click(self, x: int, y: int) -> str:
        """Click once after a very recent authorized screen inspection."""
        if not 0 <= x <= 1000 or not 0 <= y <= 1000:
            raise ValueError("Screen coordinates must each be between 0 and 1000.")

        self._sync_access()
        with self._lock:
            now = self._monotonic()
            if self._allowed_until - now <= 0:
                raise RuntimeError(
                    "Screen control is not authorized or its time limit expired. "
                    "Ask the user to authorize another limited session."
                )
            if self._last_capture_at is None:
                raise RuntimeError(
                    "A fresh screen inspection is required immediately before clicking."
                )
            age = now - self._last_capture_at
            if age > MAX_SCREENSHOT_AGE_FOR_CLICK_SECONDS:
                self._invalidate_capture()
                raise RuntimeError(
                    "The last screen inspection is stale. Inspect the screen again before clicking."
                )
            # One screenshot authorizes at most one click. Invalidate it before
            # focus checks/posting input so failures cannot reuse stale evidence.
            observed_pid = self._last_capture_pid
            self._invalidate_capture()
            revision = self._revision

        if observed_pid is None or self._foreground_pid() != observed_pid:
            raise RuntimeError(
                "The foreground app changed since the screenshot. Nothing was clicked; "
                "inspect the intended app again."
            )
        self._sync_access()
        with self._lock:
            if self._revision != revision or self._allowed_until - self._monotonic() <= 0:
                raise RuntimeError(
                    "Screen control authorization or view changed before clicking. "
                    "Nothing was clicked; inspect the intended app again."
                )

        self._click(x, y)
        return f"Clicked the visible target at screen position ({x}, {y})."
