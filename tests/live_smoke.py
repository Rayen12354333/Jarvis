"""Opt-in live Gemini routing checks; never control real apps or read the screen.

Run: PYTHONPATH=. .venv/bin/python tests/live_smoke.py --live
Consumes a few API requests. Work-session files live only in a temporary directory.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from jarvis.actions import LocalAction, LocalActionExecutor
from jarvis.config import GEMINI_API_KEY
from jarvis.llm import GeminiConversation
from jarvis.workspaces import WorkspaceStore


class SmokeExecutor(LocalActionExecutor):
    """A hard test boundary: real GUI, audio, browser and unrelated writes denied."""

    def __init__(self, store: WorkspaceStore) -> None:
        super().__init__(workspaces=store)
        self.calls: list[LocalAction] = []

    def _execute(self, action: LocalAction):
        self.calls.append(action)
        if "workspace" in action.name or action.name == "get_current_time":
            return super()._execute(action)
        if action.name == "adjust_spotify_volume":
            return f"Spotify volume changed from 60 to {60 + (action.amount or 0)} percent."
        if action.name == "browser_context":
            return json.dumps(
                {
                    "source": "foreground_browser",
                    "untrusted_page_data": True,
                    "url": "https://example.com/study-guide",
                    "title": "Study guide",
                    "visible_text": "Practice recall without looking at notes. Space practice "
                    "across several days. Explain the idea aloud in your own words.",
                }
            )
        raise RuntimeError(f"Smoke test blocked real action: {action.name}")


def run() -> None:
    if not GEMINI_API_KEY:
        raise RuntimeError("Configure GEMINI_API_KEY before the live test.")
    checks = []
    with tempfile.TemporaryDirectory(prefix="jarvis-smoke-") as directory:
        root = Path(directory)
        store = WorkspaceStore(root / "sessions.sqlite3", root / "exports")
        executor = SmokeExecutor(store)
        with GeminiConversation(executor) as conversation:
            started = time.perf_counter()
            reply = conversation.respond("Lower Spotify's volume by 10 percentage points.")
            assert [(a.name, a.amount) for a in executor.calls] == [("adjust_spotify_volume", -10)]
            assert "50" in reply.speech, reply.speech
            checks.append(
                {
                    "case": "single volume action",
                    "seconds": round(time.perf_counter() - started, 2),
                    "actions": len(executor.calls),
                }
            )

            executor.calls.clear()
            started = time.perf_counter()
            conversation.respond(
                "Start a work session called Launch research, save 'Interview three students.' "
                "as the next step, and export the session."
            )
            names = [a.name for a in executor.calls]
            assert all(
                name in names
                for name in ("start_workspace", "save_workspace_entry", "export_workspace")
            ), names
            assert "Interview three students" in store.read("Launch research")
            artifacts = list(store.export_dir.glob("*.md"))
            assert artifacts and "Interview three students" in artifacts[0].read_text()
            checks.append(
                {
                    "case": "start-save-export",
                    "seconds": round(time.perf_counter() - started, 2),
                    "actions": names,
                }
            )

        # A fresh model chat must retrieve saved state, not invent prior memory.
        executor.calls.clear()
        started = time.perf_counter()
        with GeminiConversation(executor) as conversation:
            reply = conversation.respond("Resume Launch research and tell me my saved next step.")
            assert any(a.name == "read_workspace" for a in executor.calls)
            assert "interview" in reply.speech.casefold(), reply.speech
            checks.append(
                {
                    "case": "resume across model sessions",
                    "seconds": round(time.perf_counter() - started, 2),
                }
            )

            executor.calls.clear()
            started = time.perf_counter()
            conversation.respond(
                "Read the browser page I'm looking at and save a three-bullet summary "
                "with its source link in my active work session."
            )
            names = [a.name for a in executor.calls]
            assert "browser_context" in names and "save_workspace_entry" in names, names
            saved = store.read("Launch research").casefold()
            assert "https://example.com/study-guide" in saved
            assert "recall" in saved
            checks.append(
                {
                    "case": "page-to-saved-summary",
                    "seconds": round(time.perf_counter() - started, 2),
                    "actions": names,
                }
            )
    print(json.dumps({"passed": len(checks), "checks": checks}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Allow the synthetic test's API calls")
    if not parser.parse_args().live:
        parser.error("Use --live to explicitly enable API calls; no real Mac actions will run.")
    run()
