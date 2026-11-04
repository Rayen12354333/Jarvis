"""Validated local actions Gemini may ask Jarvis to execute."""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Literal

from pydantic import BaseModel, Field

from jarvis.apps import MacAppController
from jarvis.browser import BrowserController
from jarvis.notes import NotesController
from jarvis.screen import ScreenCapture, ScreenVisionManager
from jarvis.screen_access import ScreenAccessStore
from jarvis.timers import TimerManager, format_duration
from jarvis.workspaces import WorkspaceStore


def _action_activity(action: LocalAction) -> str:
    """Return compact, visible feedback for a local operation in progress."""
    if action.name in {"scroll_screen", "browser_scroll"}:
        return f"Scrolling {action.scroll_direction or ''}…".replace("  ", " ")
    if action.name == "click_screen":
        return "Clicking target…"
    if action.name == "inspect_screen":
        return "Looking at screen…"
    if action.name == "start_screen_vision":
        return "Enabling screen view…"
    if action.name == "stop_screen_vision":
        return "Stopping screen view…"
    if action.name == "open_application":
        return f"Opening {action.app_name or 'application'}…"
    if action.name == "search_in_app":
        return f"Searching {action.app_name or 'application'}…"
    if action.name == "play_spotify_track":
        return "Starting Spotify track…"
    if action.name in {
        "control_spotify",
        "adjust_spotify_volume",
        "set_spotify_volume",
    }:
        return "Controlling Spotify…"
    if action.name == "create_note":
        return "Creating note…"
    if action.name == "browser_context":
        return "Reading browser page…"
    if action.name == "open_url":
        return "Opening web page…"
    if action.name == "browser_navigate":
        return "Navigating browser…"
    if action.name == "play_visible_video":
        return "Opening selected video…"
    if action.name == "control_browser_video":
        return "Skipping ad…" if action.video_command == "skip_ad" else "Controlling video…"
    if "workspace" in action.name:
        return {
            "start_workspace": "Opening work session…",
            "resume_workspace": "Resuming work session…",
            "list_workspaces": "Listing work sessions…",
            "read_workspace": "Reading work session…",
            "save_workspace_entry": "Saving to work session…",
            "export_workspace": "Exporting work session…",
        }[action.name]
    if action.name in {"set_timer", "cancel_timer"}:
        return "Updating timer…"
    if "volume" in action.name:
        return "Adjusting volume…"
    if action.name == "get_current_time":
        return "Checking time…"
    return "Working…"


class LocalAction(BaseModel):
    """A deliberately small, allow-listed computer action."""

    name: Literal[
        "get_current_time",
        "set_timer",
        "list_timers",
        "cancel_timer",
        "get_volume",
        "adjust_volume",
        "set_volume",
        "mute_volume",
        "unmute_volume",
        "open_application",
        "search_in_app",
        "control_spotify",
        "adjust_spotify_volume",
        "set_spotify_volume",
        "play_spotify_track",
        "create_note",
        "start_screen_vision",
        "inspect_screen",
        "scroll_screen",
        "click_screen",
        "screen_vision_status",
        "stop_screen_vision",
        "browser_context",
        "open_url",
        "browser_navigate",
        "browser_scroll",
        "control_browser_video",
        "play_visible_video",
        "start_workspace",
        "resume_workspace",
        "list_workspaces",
        "read_workspace",
        "save_workspace_entry",
        "export_workspace",
    ]
    seconds: float | None = Field(
        default=None,
        description="Duration in seconds for set_timer or start_screen_vision",
    )
    label: str | None = Field(
        default=None, description="Short optional timer label, such as tea or laundry"
    )
    timer_id: int | None = Field(default=None, description="Timer number to cancel when known")
    amount: int | None = Field(
        default=None,
        description="Signed volume change: negative lowers and positive raises volume",
    )
    level: int | None = Field(default=None, description="Absolute output volume from 0 through 100")
    app_name: str | None = Field(
        default=None, description="Installed application name or search destination"
    )
    query: str | None = Field(default=None, description="Search terms for search_in_app")
    media_command: (
        Literal["play", "pause", "play_pause", "next", "previous", "now_playing"] | None
    ) = Field(default=None, description="Spotify playback operation")
    note_title: str | None = Field(default=None, description="Concise title for a new Apple Note")
    note_body: str | None = Field(
        default=None, description="Exact content to put in a new Apple Note"
    )
    purpose: str | None = Field(
        default=None, description="Why the user authorized temporary screen vision"
    )
    screen_question: str | None = Field(
        default=None, description="Question Gemini should answer from the fresh screenshot"
    )
    scroll_direction: Literal["up", "down", "left", "right"] | None = Field(
        default=None, description="Direction for scroll_screen"
    )
    scroll_amount: int | None = Field(default=None, description="Scroll strength from 1 through 10")
    screen_x: int | None = Field(
        default=None, description="Horizontal target position from 0 through 1000"
    )
    screen_y: int | None = Field(
        default=None, description="Vertical target position from 0 through 1000"
    )
    url: str | None = Field(
        default=None,
        max_length=4096,
        description="HTTP(S) page to open visibly in Safari or Google Chrome",
    )
    navigation: Literal["back", "forward", "reload"] | None = None
    scroll_edge: Literal["top", "bottom"] | None = None
    video_command: Literal["play", "pause", "skip_ad"] | None = None
    item_index: int | None = Field(
        default=None,
        ge=1,
        le=50,
        description="One-based index of the visible YouTube video requested by the user",
    )
    workspace_name: str | None = Field(
        default=None,
        max_length=120,
        description="Named local work session; omit to use the active work session",
    )
    entry_kind: Literal["note", "source", "decision", "next_step"] | None = None
    entry_text: str | None = Field(
        default=None,
        max_length=8000,
        description="Content the user asked to save to a work session",
    )
    source_url: str | None = Field(
        default=None,
        max_length=2048,
        description="Actual HTTP(S) source URL for a saved finding; never invent a citation",
    )


class LocalActionExecutor:
    """Execute only the local operations represented by ``LocalAction``."""

    def __init__(
        self,
        timers: TimerManager | None = None,
        apps: MacAppController | None = None,
        notes: NotesController | None = None,
        screen: ScreenVisionManager | None = None,
        activity_reporter: Callable[[str], None] | None = None,
        browser: BrowserController | None = None,
        workspaces: WorkspaceStore | None = None,
        result_reporter: Callable[[str, str, float], None] | None = None,
    ) -> None:
        self.timers = timers
        self.apps = apps or MacAppController()
        self.notes = notes or NotesController()
        self.screen = screen or ScreenVisionManager(access_store=ScreenAccessStore())
        self.browser = browser or BrowserController()
        self._preferred_browser: str | None = None
        self._workspaces = workspaces
        self._activity_reporter = activity_reporter
        self._result_reporter = result_reporter

    @property
    def workspaces(self) -> WorkspaceStore:
        if self._workspaces is None:
            self._workspaces = WorkspaceStore()
        return self._workspaces

    @staticmethod
    def _report(callback: Callable | None, *args: object) -> None:
        # A full disk or unavailable UI must never prevent a requested action.
        if callback is not None:
            try:
                callback(*args)
            except Exception as exc:  # noqa: BLE001 -- observability is best effort
                print(f"[activity] reporter unavailable: {type(exc).__name__}")

    @staticmethod
    def _run_osascript(*lines: str) -> str:
        if sys.platform != "darwin":
            raise RuntimeError("Volume control is only available on macOS.")
        command = ["osascript"]
        for line in lines:
            command.extend(["-e", line])
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").strip() or str(exc)
            raise RuntimeError(f"macOS volume command failed: {detail}") from exc
        return completed.stdout.strip()

    def get_volume_state(self) -> tuple[int, bool]:
        """Return the real macOS output level and mute state."""
        output = self._run_osascript(
            "set s to get volume settings",
            'return (output volume of s as text) & "," & (output muted of s as text)',
        )
        try:
            level_text, muted_text = output.split(",", maxsplit=1)
            level, muted = int(level_text), muted_text.strip().casefold()
            if not 0 <= level <= 100 or muted not in {"true", "false"}:
                raise ValueError("Invalid volume state")
            return level, muted == "true"
        except (ValueError, TypeError) as exc:
            raise RuntimeError(f"Could not understand macOS volume state: {output!r}") from exc

    def set_output_muted(self, muted: bool) -> None:
        """Set macOS output mute without changing its stored volume level."""
        phrase = "set volume with output muted" if muted else "set volume without output muted"
        actual = self._run_osascript(phrase, "return output muted of (get volume settings)")
        if actual.casefold() != str(muted).casefold():
            raise RuntimeError("macOS did not confirm the requested mute state.")

    def _set_output_volume(self, level: int) -> None:
        actual = self._run_osascript(
            f"set volume output volume {level}",
            "return output volume of (get volume settings)",
        )
        if actual != str(level):
            raise RuntimeError(f"macOS did not confirm volume {level}; reported {actual!r}.")

    def execute(self, action: LocalAction) -> str | ScreenCapture:
        """Execute one action and return trustworthy evidence for Gemini."""
        self._report(self._activity_reporter, _action_activity(action))
        started = time.perf_counter()
        try:
            result = self._execute(action)
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
            result = f"FAILED {action.name}: {exc}"
        if isinstance(result, ScreenCapture):
            print(
                f"[action] {action.name}: captured {len(result.image_bytes)} bytes "
                "for ephemeral Gemini analysis"
            )
            receipt = "Captured a screenshot for analysis; image not stored in action history."
        else:
            # Page/work-session text can be sensitive. Keep it out of the
            # general action log; Gemini still receives the complete evidence.
            private_read = action.name in {"browser_context", "read_workspace", "list_workspaces"}
            receipt = (
                "Returned requested content; content omitted from action history."
                if private_read and not result.startswith("FAILED ")
                else result
            )
            print(f"[action] {action.name}: {receipt}")
        self._report(self._result_reporter, action.name, receipt, time.perf_counter() - started)
        return result

    def _execute(self, action: LocalAction) -> str | ScreenCapture:
        if action.name == "get_current_time":
            now = dt.datetime.now().astimezone()
            return "Current local date and time: " + now.strftime("%A, %B %d, %Y at %I:%M:%S %p %Z")

        if action.name == "set_timer":
            if self.timers is None:
                raise RuntimeError("Timers require the continuously running voice mode.")
            if action.seconds is None:
                raise ValueError("A duration in seconds is required.")
            timer = self.timers.set_timer(action.seconds, action.label)
            return (
                f"Set timer #{timer.timer_id} named {timer.label!r} for "
                f"{format_duration(timer.duration_seconds)}; it is due at "
                f"{timer.due_at.strftime('%I:%M:%S %p %Z')}."
            )

        if action.name == "list_timers":
            if self.timers is None:
                raise RuntimeError("Timers require the continuously running voice mode.")
            timers = self.timers.active()
            if not timers:
                return "There are no active timers."
            descriptions = [
                f"#{timer.timer_id} {timer.label!r}, about "
                f"{format_duration(self.timers.remaining_seconds(timer))} remaining"
                for timer in timers
            ]
            return "Active timers: " + "; ".join(descriptions) + "."

        if action.name == "cancel_timer":
            if self.timers is None:
                raise RuntimeError("Timers require the continuously running voice mode.")
            before = self.timers.active()
            cancelled = self.timers.cancel(timer_id=action.timer_id, label=action.label)
            if cancelled:
                names = ", ".join(f"#{timer.timer_id} {timer.label!r}" for timer in cancelled)
                return f"Cancelled timer {names}."
            if not before:
                return "No timer was cancelled because there are no active timers."
            return (
                "No timer was cancelled because the request was ambiguous or did not "
                "match. Active timers: "
                + ", ".join(f"#{timer.timer_id} {timer.label!r}" for timer in before)
                + "."
            )

        if action.name == "get_volume":
            level, muted = self.get_volume_state()
            return f"Current output volume is {level} percent; muted is {muted}."

        if action.name == "adjust_volume":
            if action.amount is None:
                raise ValueError("A signed volume amount is required.")
            if not -100 <= action.amount <= 100:
                raise ValueError("Volume adjustment must be between -100 and 100.")
            current, _ = self.get_volume_state()
            target = max(0, min(100, current + action.amount))
            self._set_output_volume(target)
            return f"Output volume changed from {current} to {target} percent."

        if action.name == "set_volume":
            if action.level is None or not 0 <= action.level <= 100:
                raise ValueError("Volume level must be between 0 and 100.")
            self._set_output_volume(action.level)
            return f"Output volume is now {action.level} percent."

        if action.name == "mute_volume":
            self.set_output_muted(True)
            return "Output is now muted."

        if action.name == "unmute_volume":
            self.set_output_muted(False)
            level, _ = self.get_volume_state()
            return f"Output is unmuted at {level} percent."

        if action.name == "open_application":
            if not action.app_name:
                raise ValueError("An application name is required.")
            result = self.apps.open_app(action.app_name)
            if action.app_name.casefold() in {"safari", "chrome", "google chrome"}:
                self._preferred_browser = action.app_name
            return result

        if action.name == "search_in_app":
            if not action.app_name or not action.query:
                raise ValueError("A search destination and query are required.")
            name = action.app_name.casefold()
            if name in {"youtube", "yt", "browser", "web", "google", "safari", "chrome"}:
                chosen = (
                    action.app_name if name in {"safari", "chrome"} else self._preferred_browser
                )
                return self.browser.search(
                    "youtube" if name in {"youtube", "yt"} else "web", action.query, chosen
                )
            return self.apps.search(action.app_name, action.query)

        if action.name == "control_spotify":
            if not action.media_command:
                raise ValueError("A Spotify media command is required.")
            return self.apps.control_spotify(action.media_command)

        if action.name == "adjust_spotify_volume":
            if action.amount is None:
                raise ValueError("A signed Spotify volume amount is required.")
            if not -100 <= action.amount <= 100:
                raise ValueError("Spotify volume adjustment must be between -100 and 100.")
            return self.apps.adjust_spotify_volume(action.amount)

        if action.name == "set_spotify_volume":
            if action.level is None or not 0 <= action.level <= 100:
                raise ValueError("Spotify volume level must be between 0 and 100.")
            return self.apps.set_spotify_volume(action.level)

        if action.name == "play_spotify_track":
            if not action.query:
                raise ValueError("A song title or title-and-artist query is required.")
            return self.apps.play_spotify_track(action.query)

        if action.name == "create_note":
            if not action.note_title or not action.note_body:
                raise ValueError("A note title and content are required.")
            return self.notes.create_note(action.note_title, action.note_body)

        if action.name == "browser_context":
            return self.browser.context(action.app_name)

        if action.name == "open_url":
            if not action.url:
                raise ValueError("A web page URL is required.")
            result = self.browser.open_url(action.url, action.app_name or self._preferred_browser)
            if action.app_name:
                self._preferred_browser = action.app_name
            return result

        if action.name == "browser_navigate":
            if action.navigation is None:
                raise ValueError("A browser navigation direction is required.")
            return self.browser.navigate(action.navigation, action.app_name)

        if action.name == "browser_scroll":
            if action.scroll_direction is None:
                raise ValueError("A scroll direction is required.")
            return self.browser.scroll(
                action.scroll_direction,
                action.scroll_amount or 5,
                action.scroll_edge,
                action.app_name,
            )

        if action.name == "control_browser_video":
            if action.video_command is None:
                raise ValueError("A video command is required.")
            return self.browser.control_video(action.video_command, action.app_name)

        if action.name == "play_visible_video":
            if action.item_index is None:
                raise ValueError("The visible video's one-based index is required.")
            return self.browser.play_visible_video(action.item_index, action.app_name)

        if action.name == "start_workspace":
            if not action.workspace_name:
                raise ValueError("A work session name is required.")
            return self.workspaces.start(action.workspace_name)

        if action.name == "resume_workspace":
            if not action.workspace_name:
                raise ValueError("An existing work session name is required.")
            return self.workspaces.resume(action.workspace_name)

        if action.name == "list_workspaces":
            return self.workspaces.list()

        if action.name == "read_workspace":
            return self.workspaces.read(action.workspace_name)

        if action.name == "save_workspace_entry":
            if not action.entry_text:
                raise ValueError("Content to save is required.")
            return self.workspaces.add_entry(
                action.entry_text,
                kind=action.entry_kind or "note",
                source_url=action.source_url,
                name=action.workspace_name,
            )

        if action.name == "export_workspace":
            return self.workspaces.export(action.workspace_name)

        if action.name == "start_screen_vision":
            duration = action.seconds if action.seconds is not None else 1800.0
            return self.screen.start(duration, action.purpose)

        if action.name == "inspect_screen":
            return self.screen.capture(action.screen_question)

        if action.name == "scroll_screen":
            if action.scroll_direction is None:
                raise ValueError("A scroll direction is required.")
            amount = action.scroll_amount if action.scroll_amount is not None else 5
            return self.screen.scroll(action.scroll_direction, amount)

        if action.name == "click_screen":
            if action.screen_x is None or action.screen_y is None:
                raise ValueError("Fresh-screen target coordinates are required.")
            return self.screen.click(action.screen_x, action.screen_y)

        if action.name == "screen_vision_status":
            return self.screen.status()

        if action.name == "stop_screen_vision":
            return self.screen.stop()

        raise ValueError(f"Unsupported local action: {action.name}")


class ListeningVolumeGuard:
    """Temporarily silence speaker audio while the microphone is accepting speech."""

    def __init__(self, executor: LocalActionExecutor, *, enabled: bool = True) -> None:
        self._executor = executor
        self._enabled = enabled

    @contextmanager
    def suppress_output(self) -> Iterator[bool]:
        restore_unmuted = False
        if self._enabled:
            try:
                _, already_muted = self._executor.get_volume_state()
                if not already_muted:
                    self._executor.set_output_muted(True)
                    restore_unmuted = True
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                # Audio capture remains usable if macOS denies volume access.
                print(f"[audio] could not suppress speaker output while listening: {exc}")

        try:
            yield restore_unmuted
        finally:
            if restore_unmuted:
                try:
                    self._executor.set_output_muted(False)
                except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                    print(f"[audio] could not restore speaker output: {exc}")
