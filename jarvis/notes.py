"""Validated Apple Notes creation through its native scripting interface."""
from __future__ import annotations

import html
import subprocess
import sys

_CREATE_NOTE_SCRIPT = (
    """
on run argv
    set noteTitle to item 1 of argv
    set noteHTML to item 2 of argv
    tell application "Notes"
        set targetAccount to default account
        set targetFolder to default folder of targetAccount
"""
    "        set createdNote to make new note at targetFolder with properties "
    "{name:noteTitle, body:noteHTML}\n"
    """
        show createdNote
        activate
        return id of createdNote
    end tell
end run
"""
).strip()


class NotesController:
    """Create real notes while keeping user text out of AppleScript source."""

    @staticmethod
    def _note_html(body: str) -> str:
        escaped_body = html.escape(body, quote=True).replace("\n", "<br>")
        return f"<div>{escaped_body}</div>"

    def create_note(self, title: str, body: str) -> str:
        if sys.platform != "darwin":
            raise RuntimeError("Apple Notes control is only available on macOS.")

        clean_title = " ".join(title.strip().split())[:200]
        clean_body = body.strip()[:20_000]
        if not clean_title:
            raise ValueError("A note title is required.")
        if not clean_body:
            raise ValueError("Note content is required.")

        command = [
            "osascript",
            "-e",
            _CREATE_NOTE_SCRIPT,
            "--",
            clean_title,
            self._note_html(clean_body),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").strip() or str(exc)
            raise RuntimeError(f"Apple Notes command failed: {detail}") from exc

        note_id = completed.stdout.strip()
        if not note_id:
            raise RuntimeError("Apple Notes did not return a created-note ID.")
        print(f"[notes] created {clean_title!r} (id={note_id})")
        return f"Created note {clean_title!r}; Apple Notes returned note ID {note_id}."
