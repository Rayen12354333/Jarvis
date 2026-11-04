"""Read-only setup checks. Never request or change a macOS permission here."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from jarvis.config import GEMINI_API_KEY, GEMINI_MODEL, GROQ_API_KEY, LOG_DIR


def permission_status() -> dict[str, str]:
    results = {
        "Accessibility (click/scroll)": "Unavailable",
        "Screen Recording": "Unavailable",
        "Microphone": "Unavailable",
    }
    if sys.platform != "darwin":
        return results
    try:
        from ApplicationServices import AXIsProcessTrusted

        results["Accessibility (click/scroll)"] = (
            "Allowed" if AXIsProcessTrusted() else "Not allowed for this process"
        )
    except (ImportError, OSError, RuntimeError):
        pass
    try:
        from Quartz import CGPreflightScreenCaptureAccess

        results["Screen Recording"] = (
            "Allowed" if CGPreflightScreenCaptureAccess() else "Not allowed for this process"
        )
    except (ImportError, OSError, RuntimeError):
        pass
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio

        status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
        results["Microphone"] = {
            0: "Not requested",
            1: "Restricted",
            2: "Denied",
            3: "Allowed",
        }.get(status, "Unknown")
    except (ImportError, OSError, RuntimeError):
        pass
    return results


def setup_report() -> str:
    """No credentials, screen content, browser history, or network requests."""
    lines = [
        f"Gemini key: {'Configured' if GEMINI_API_KEY else 'Missing'} (not a connection test)",
        f"Gemini model: {GEMINI_MODEL}",
        f"Groq fallback key: {'Configured' if GROQ_API_KEY else 'Optional, not configured'}",
        "",
        *(f"{label}: {value}" for label, value in permission_status().items()),
        "",
        "Automation: macOS asks separately for each app on first use.",
        "Browser page text/video selection: the browser must allow JavaScript from Apple Events.",
        "These checks describe this launcher; other launchers may have different permissions.",
        "",
        f"Python executable: {Path(sys.executable).resolve()}",
        f"Logs: {LOG_DIR}",
        "",
        "In System Settings → Privacy & Security, allow only the Jarvis launcher you trust.",
        "Restart Jarvis after changing permissions. Jarvis never grants itself access.",
    ]
    missing = [
        name
        for name in ("google.genai", "rumps", "faster_whisper", "kokoro_mlx")
        if not _installed(name)
    ]
    if missing:
        lines.extend(["", "Missing dependencies: " + ", ".join(missing)])
    return "\n".join(lines)


def _installed(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


if __name__ == "__main__":
    print(setup_report())
