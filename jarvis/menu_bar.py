"""Persistent macOS menu-bar controller for the Jarvis voice listener."""

from __future__ import annotations

import argparse
import plistlib
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import rumps
from AppKit import NSWorkspace

from jarvis.commands import CommandSession
from jarvis.config import LOG_DIR, PROJECT_ROOT
from jarvis.diagnostics import setup_report
from jarvis.screen_access import ScreenAccessStore
from jarvis.screen_overlay import ScreenOverlay
from jarvis.status import (
    STATUS_PATH,
    clear_activity,
    publish_activity,
    read_activity,
    read_receipts,
)

APP_NAME = "Jarvis"
LAUNCH_AGENT_LABEL = "com.rayen.jarvis-menubar"
ICON_PATH = PROJECT_ROOT / "assets" / "jarvis-menu-icon@2x.png"
VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"
LAUNCH_AGENT_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
MENU_LOG_PATH = LOG_DIR / "menu-bar.log"
VOICE_LOG_PATH = LOG_DIR / "menu-bar-voice.log"


class VoiceProcessController:
    """Own exactly one Jarvis voice subprocess for the menu-bar app."""

    def __init__(
        self,
        *,
        python_executable: Path = VENV_PYTHON,
        project_root: Path = PROJECT_ROOT,
        log_path: Path = VOICE_LOG_PATH,
        activity_path: Path = STATUS_PATH,
        popen_factory: Callable[..., Any] = subprocess.Popen,
    ) -> None:
        self.python_executable = python_executable
        self.project_root = project_root
        self.log_path = log_path
        self.activity_path = activity_path
        self._popen = popen_factory
        self._process: Any | None = None
        self.last_exit_code: int | None = None

    def is_running(self) -> bool:
        if self._process is None:
            return False
        exit_code = self._process.poll()
        if exit_code is None:
            return True
        self.last_exit_code = exit_code
        self._process = None
        return False

    def start(self) -> bool:
        """Start listening; return False when this controller already owns it."""
        if self.is_running():
            return False
        clear_activity(self.activity_path)
        if not self.python_executable.is_file():
            raise RuntimeError(
                f"Jarvis virtualenv Python was not found at {self.python_executable}."
            )
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as log_file:
            self._process = self._popen(
                [str(self.python_executable), "-m", "jarvis.main"],
                cwd=str(self.project_root),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        self.last_exit_code = None
        publish_activity("Starting…", path=self.activity_path)
        return True

    def stop(self) -> bool:
        """Stop the voice subprocess; return False when it is already stopped."""
        if not self.is_running():
            return False
        process = self._process
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        self.last_exit_code = process.returncode
        self._process = None
        clear_activity(self.activity_path)
        return True


def launch_agent_payload(
    *,
    python_executable: Path = VENV_PYTHON,
    project_root: Path = PROJECT_ROOT,
    log_path: Path = MENU_LOG_PATH,
) -> dict[str, object]:
    """Return the user LaunchAgent that keeps the controller available at login."""
    return {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [
            str(python_executable),
            "-m",
            "jarvis.menu_bar",
        ],
        "WorkingDirectory": str(project_root),
        "RunAtLoad": True,
        "ProcessType": "Interactive",
        "LimitLoadToSessionType": "Aqua",
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
        "EnvironmentVariables": {
            "PYTHONUNBUFFERED": "1",
            "PATH": (
                f"{project_root / '.venv' / 'bin'}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
            ),
        },
    }


def install_login_item(path: Path = LAUNCH_AGENT_PATH) -> Path:
    """Write the LaunchAgent; loading it is kept as an explicit install step."""
    if not VENV_PYTHON.is_file():
        raise RuntimeError(f"Virtualenv Python was not found at {VENV_PYTHON}.")
    if not ICON_PATH.is_file():
        raise RuntimeError(f"Menu-bar icon was not found at {ICON_PATH}.")
    path.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as plist_file:
        plistlib.dump(launch_agent_payload(), plist_file, sort_keys=True)
    path.chmod(0o600)
    return path


class JarvisMenuBar(rumps.App):
    """Icon-only status item with explicit start, stop, logs, and quit actions."""

    def __init__(self, controller: VoiceProcessController | None = None) -> None:
        super().__init__(
            APP_NAME,
            icon=str(ICON_PATH),
            template=True,
            quit_button=None,
        )
        self.controller = controller or VoiceProcessController()
        self.commands = CommandSession()
        self.screen_access = ScreenAccessStore()
        self.screen_overlay = ScreenOverlay()
        self._screen_remaining = 0.0
        self.last_reply = "No typed reply yet."
        self._reply_unread = False
        self.status_item = rumps.MenuItem("Status: Stopped")
        self.start_item = rumps.MenuItem("Start Jarvis", callback=self.start_jarvis)
        self.stop_item = rumps.MenuItem("Stop Jarvis", callback=self.stop_jarvis)
        self.screen_status_item = rumps.MenuItem("Screen: Off")
        self.screen_on_item = rumps.MenuItem(
            "Enable Screen Assistance (30 min)…",
            callback=self.enable_screen,
        )
        self.screen_off_item = rumps.MenuItem(
            "Stop Screen Assistance", callback=self.disable_screen
        )
        self.logs_item = rumps.MenuItem("Open Jarvis Log", callback=self.open_log)
        self.ask_item = rumps.MenuItem("Type a Request…", callback=self.ask_jarvis)
        self.cancel_item = rumps.MenuItem("Cancel Typed Request", callback=None)
        self.reply_item = rumps.MenuItem("Last Typed Reply…", callback=self.show_reply)
        self.history_item = rumps.MenuItem("Recent Actions…", callback=self.show_history)
        self.setup_item = rumps.MenuItem("Setup & Permissions…", callback=self.show_setup)
        self.guide_item = rumps.MenuItem("What Can Jarvis Do?", callback=self.open_guide)
        self.sessions_item = rumps.MenuItem(
            "Open Exported Work Sessions", callback=self.open_sessions
        )
        self.quit_item = rumps.MenuItem("Quit Jarvis Menu Bar", callback=self.quit_controller)
        self.menu = [
            self.status_item,
            rumps.separator,
            self.start_item,
            self.stop_item,
            self.screen_status_item,
            self.screen_on_item,
            self.screen_off_item,
            rumps.separator,
            self.ask_item,
            self.cancel_item,
            self.reply_item,
            self.history_item,
            self.sessions_item,
            rumps.separator,
            self.setup_item,
            self.guide_item,
            self.logs_item,
            self.quit_item,
        ]
        self._timer = rumps.Timer(self.refresh_status, 0.25)
        self._timer.start()
        self.refresh_status()

    def refresh_status(self, _sender: object | None = None) -> None:
        self.refresh_screen_access()
        running = self.controller.is_running()
        busy = self.commands.busy
        if running or busy:
            activity = read_activity()
            visible = activity.visible_text() if activity is not None else "Ready"
            self.status_item.title = f"Status: {visible}"
            self.title = "" if visible == "Ready" else f" {visible}"
        elif self.controller.last_exit_code not in {None, 0, -15}:
            self.status_item.title = f"Status: Stopped (exit {self.controller.last_exit_code})"
            self.title = ""
        else:
            self.status_item.title = "Status: Stopped"
            self.title = " Reply ready" if self._reply_unread else ""
        self.start_item.set_callback(None if running or busy else self.start_jarvis)
        self.stop_item.set_callback(self.stop_jarvis if running else None)
        self.ask_item.set_callback(None if busy else self.ask_jarvis)
        self.cancel_item.set_callback(self.cancel_request if busy else None)
        for item, callback in (
            (self.reply_item, self.show_reply),
            (self.history_item, self.show_history),
            (self.setup_item, self.show_setup),
            (self.guide_item, self.open_guide),
            (self.sessions_item, self.open_sessions),
            (self.logs_item, self.open_log),
        ):
            item.set_callback(None if busy else callback)
        reply = self.commands.take_reply()
        if reply is not None:
            self.last_reply = f"{reply.text}\n\nResponse time: {reply.elapsed_s:.1f}s"
            self._reply_unread = True
            self.reply_item.title = "Read New Reply…"
        if self._screen_remaining > 0:
            minutes, seconds = divmod(int(self._screen_remaining), 60)
            self.title += f" ◉ {minutes:02}:{seconds:02}"

    def start_jarvis(self, _sender: object | None = None) -> None:
        if self.commands.busy:
            return
        try:
            self.controller.start()
        except Exception as exc:  # noqa: BLE001 -- surface startup errors in the UI
            rumps.alert("Jarvis could not start", str(exc))
        self.refresh_status()

    def stop_jarvis(self, _sender: object | None = None) -> None:
        self.disable_screen()
        try:
            self.controller.stop()
        except Exception as exc:  # noqa: BLE001 -- surface shutdown errors in the UI
            rumps.alert("Jarvis could not stop", str(exc))
        self.refresh_status()

    def refresh_screen_access(self) -> None:
        remaining = self.screen_access.remaining()
        if remaining > 0:
            self.screen_status_item.title = (
                f"Screen: ON · {int(remaining) // 60:02}:{int(remaining) % 60:02}"
            )
            try:
                self.screen_overlay.show()
            except Exception as exc:  # noqa: BLE001 -- never allow invisible screen access
                self.screen_access.revoke()
                self.screen_status_item.title = (
                    f"Screen: indicator unavailable ({type(exc).__name__})"
                )
                remaining = 0
        else:
            self.screen_overlay.hide()
            self.screen_status_item.title = "Screen: Off"
        self._screen_remaining = remaining
        self.screen_on_item.set_callback(self.enable_screen if remaining <= 0 else None)
        self.screen_off_item.set_callback(self.disable_screen if remaining > 0 else None)

    def enable_screen(self, _sender: object | None = None) -> None:
        if self.commands.busy:
            return
        previous_app = NSWorkspace.sharedWorkspace().frontmostApplication()
        confirmed = rumps.alert(
            "Enable screen assistance for 30 minutes?",
            "Your screen will have a cyan tint. While on, fresh screen images can accompany "
            "your requests to Gemini. This is not continuous recording. Say 'screen off', "
            "use Stop Screen Assistance, or close Jarvis to revoke access. "
            "It also switches off automatically after 30 minutes.",
            ok="Enable",
            cancel="Cancel",
        )
        if previous_app is not None:
            previous_app.activateWithOptions_(0)
        if confirmed:
            self.screen_access.grant()
            self.refresh_screen_access()

    def disable_screen(self, _sender: object | None = None) -> None:
        self.screen_access.revoke()
        self.screen_overlay.hide()
        self.screen_status_item.title = "Screen: Off"
        self._screen_remaining = 0.0

    def open_log(self, _sender: object | None = None) -> None:
        self.controller.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.controller.log_path.touch(exist_ok=True)
        subprocess.Popen(["/usr/bin/open", str(self.controller.log_path)])

    def ask_jarvis(self, _sender: object | None = None) -> None:
        if self.controller.is_running():
            rumps.alert(
                "Voice is currently running",
                "Stop Jarvis from this menu before typing a request. This keeps voice and typed "
                "requests from controlling the Mac at the same time. "
                "Stopping clears active timers.",
            )
            return
        if self.commands.busy:
            return
        # A modal input window activates Python. Restore only the application
        # observed before opening it so subsequent browser actions target what
        # the user was looking at, without weakening foreground-only guards.
        previous_app = NSWorkspace.sharedWorkspace().frontmostApplication()
        response = rumps.Window(
            title="Ask Jarvis",
            message="Type a request or follow-up. Then choose Read New Reply from the menu.\n"
            "Try: Start a work session called Biology revision.",
            ok="Ask",
            cancel="Cancel",
            dimensions=(460, 120),
        ).run()
        if previous_app is not None:
            previous_app.activateWithOptions_(0)
        if response.clicked:
            try:
                self.commands.submit(response.text)
            except ValueError as exc:
                rumps.alert("Check your request", str(exc))
            self.refresh_status()

    def cancel_request(self, _sender: object | None = None) -> None:
        self.commands.cancel()
        publish_activity("Cancelling…")

    def show_reply(self, _sender: object | None = None) -> None:
        self._reply_unread = False
        self.reply_item.title = "Last Typed Reply…"
        self._show_information("Jarvis", self.last_reply)

    def _show_information(self, title: str, message: str) -> None:
        if self.commands.busy:
            return
        previous_app = NSWorkspace.sharedWorkspace().frontmostApplication()
        try:
            rumps.alert(title, message)
        finally:
            if previous_app is not None:
                previous_app.activateWithOptions_(0)

    def show_history(self, _sender: object | None = None) -> None:
        receipts = read_receipts()
        lines = []
        for receipt in reversed(receipts[-8:]):
            stamp = datetime.fromtimestamp(receipt.finished_at).strftime("%H:%M:%S")
            label = "Failed" if receipt.failed else "Result"
            lines.append(
                f"{stamp} · {receipt.name.replace('_', ' ')} · {receipt.elapsed_s:.1f}s\n"
                f"{label}: {receipt.result[:400]}"
            )
        self._show_information(
            "Recent Jarvis Actions",
            "\n\n".join(lines) or "No actions recorded yet.",
        )

    def show_setup(self, _sender: object | None = None) -> None:
        self._show_information("Jarvis Setup & Permissions", setup_report())

    def open_guide(self, _sender: object | None = None) -> None:
        subprocess.Popen(["/usr/bin/open", str(PROJECT_ROOT / "PRODUCT.md")])

    def open_sessions(self, _sender: object | None = None) -> None:
        from jarvis.workspaces import WorkspaceStore

        store = WorkspaceStore()
        store.export_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        subprocess.Popen(["/usr/bin/open", str(store.export_dir)])

    def quit_controller(self, _sender: object | None = None) -> None:
        self.disable_screen()
        self._timer.stop()
        self.commands.close()
        self.controller.stop()
        rumps.quit_application()


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis macOS menu-bar controller")
    parser.add_argument(
        "--install-login-item",
        action="store_true",
        help="Write the per-user LaunchAgent plist and exit",
    )
    args = parser.parse_args()
    if args.install_login_item:
        path = install_login_item()
        print(f"Installed Jarvis menu-bar login item at {path}")
        return
    JarvisMenuBar().run()


if __name__ == "__main__":
    main()
