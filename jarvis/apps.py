"""Safe macOS application launching, search surfaces, and Spotify control."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote_plus, urlparse

from ddgs import DDGS

DEFAULT_APP_ROOTS = (
    Path("/Applications"),
    Path("/System/Applications"),
    Path.home() / "Applications",
)

SPOTIFY_COMMANDS = {
    "play": "play",
    "pause": "pause",
    "play_pause": "playpause",
    "next": "next track",
    "previous": "previous track",
}

_SPOTIFY_TRACK_PATH = re.compile(
    r"^/(?:intl-[a-z]{2}/)?track/([A-Za-z0-9]{22})/?$",
    flags=re.IGNORECASE,
)


def _normalized_app_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.casefold().removesuffix(".app"))


class MacAppController:
    """Resolve installed apps before launching any model-provided app name."""

    def __init__(self, app_roots: tuple[Path, ...] = DEFAULT_APP_ROOTS) -> None:
        self._app_roots = app_roots

    @staticmethod
    def _require_macos() -> None:
        if sys.platform != "darwin":
            raise RuntimeError("Application control is only available on macOS.")

    @staticmethod
    def _run(command: list[str]) -> str:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").strip() or str(exc)
            raise RuntimeError(f"macOS application command failed: {detail}") from exc
        return completed.stdout.strip()

    def installed_apps(self) -> dict[str, Path]:
        """Return normalized names mapped to installed application bundles."""
        apps: dict[str, Path] = {}
        for root in self._app_roots:
            if not root.is_dir():
                continue
            for pattern in ("*.app", "*/*.app"):
                for path in root.glob(pattern):
                    apps.setdefault(_normalized_app_name(path.stem), path)
        return apps

    def resolve_app(self, requested_name: str) -> Path:
        """Resolve an exact or unique partial installed-app name."""
        normalized = _normalized_app_name(requested_name)
        if len(normalized) < 2:
            raise ValueError("An installed application name is required.")

        apps = self.installed_apps()
        aliases = {
            "chrome": "googlechrome",
            "google": "googlechrome",
            "music": "music",
            "spotify": "spotify",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized in apps:
            return apps[normalized]

        matches = [path for name, path in apps.items() if normalized in name]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise ValueError(f"I could not find an installed app named {requested_name!r}.")
        options = ", ".join(sorted(path.stem for path in matches)[:5])
        raise ValueError(f"That app name is ambiguous. Matching apps: {options}.")

    def open_app(self, requested_name: str) -> str:
        self._require_macos()
        path = self.resolve_app(requested_name)
        self._run(["open", str(path)])
        return f"Opened {path.stem}."

    def search(self, app_name: str, query: str) -> str:
        """Open a validated query in Spotify, YouTube, or the default browser."""
        self._require_macos()
        clean_query = " ".join(query.strip().split())[:300]
        if not clean_query:
            raise ValueError("A search query is required.")

        destination = _normalized_app_name(app_name)
        if destination == "spotify":
            spotify = self.resolve_app("Spotify")
            uri = "spotify:search:" + quote_plus(clean_query)
            self._run(["open", "-a", spotify.stem, uri])
            return f"Opened Spotify search results for {clean_query!r}."
        if destination in {"youtube", "yt"}:
            url = "https://www.youtube.com/results?search_query=" + quote_plus(clean_query)
            self._run(["open", url])
            return f"Opened YouTube search results for {clean_query!r}."
        if destination in {"browser", "web", "google", "safari", "chrome"}:
            url = "https://www.google.com/search?q=" + quote_plus(clean_query)
            self._run(["open", url])
            return f"Opened a browser search for {clean_query!r}."
        raise ValueError("Search currently supports Spotify, YouTube, or the web browser.")

    def _spotify_is_running(self) -> bool:
        completed = subprocess.run(
            ["pgrep", "-x", "Spotify"],
            capture_output=True,
            timeout=3,
            check=False,
        )
        return completed.returncode == 0

    def control_spotify(self, command: str) -> str:
        """Control the installed Spotify client through its AppleScript API."""
        self._require_macos()
        self.resolve_app("Spotify")
        if command == "now_playing":
            if not self._spotify_is_running():
                return "Spotify is not currently running."
            output = self._run(
                [
                    "osascript",
                    "-e",
                    'tell application "Spotify" to return (player state as text) & "|" '
                    '& (name of current track) & "|" & (artist of current track)',
                ]
            )
            state, title, artist = output.split("|", maxsplit=2)
            return f"Spotify is {state}; current track is {title!r} by {artist}."

        spotify_command = SPOTIFY_COMMANDS.get(command)
        if spotify_command is None:
            raise ValueError(f"Unsupported Spotify command: {command!r}.")
        if command != "play" and not self._spotify_is_running():
            return f"Spotify is not running, so {command.replace('_', ' ')} was not sent."
        state, _ = self._spotify_command_and_state(spotify_command)
        if command == "play" and state == "playing":
            return "Started or resumed Spotify playback."
        if command == "pause" and state == "paused":
            return "Paused Spotify playback."
        # A command returning normally does not establish that the player changed
        # track/state. Do not retry a possibly accepted command or guess success.
        label = command.replace("_", " ")
        return (
            f"Sent Spotify {label} command; observed player state is {state}. "
            "The requested change has not been verified."
        )

    def _spotify_command_and_state(self, command: str) -> tuple[str, str]:
        """Run a fixed/validated command once, then read state in the same process."""
        output = self._run([
            "osascript",
            "-e",
            '\n'.join([
                'tell application "Spotify"',
                command,
                'set observedState to "unknown"',
                "try",
                "set observedState to player state as text",
                "end try",
                'set observedTrack to ""',
                "try",
                "set observedTrack to id of current track as text",
                "end try",
                'return observedState & "|" & observedTrack',
                "end tell",
            ]),
        ])
        state, _, track_id = output.partition("|")
        if state not in {"playing", "paused", "stopped"}:
            state = "unknown"
        if not re.fullmatch(r"spotify:track:[A-Za-z0-9]{22}", track_id):
            track_id = ""
        return state, track_id

    def _spotify_volume(self) -> int:
        output = self._run(
            [
                "osascript",
                "-e",
                'tell application "Spotify" to return (sound volume as text)',
            ]
        )
        try:
            level = int(output)
        except ValueError as exc:
            raise RuntimeError(
                f"Could not understand Spotify volume state: {output!r}."
            ) from exc
        if not 0 <= level <= 100:
            raise RuntimeError(f"Spotify returned an invalid volume level: {level}.")
        return level

    def set_spotify_volume(self, level: int) -> str:
        """Set only Spotify's application volume, leaving macOS volume alone."""
        self._require_macos()
        self.resolve_app("Spotify")
        if not 0 <= level <= 100:
            raise ValueError("Spotify volume level must be between 0 and 100.")
        if not self._spotify_is_running():
            return "Spotify is not currently running, so its volume was not changed."
        previous = self._spotify_volume()
        return self._set_and_verify_spotify_volume(previous, level)

    def adjust_spotify_volume(self, amount: int) -> str:
        """Raise or lower only Spotify's application volume."""
        self._require_macos()
        self.resolve_app("Spotify")
        if not -100 <= amount <= 100:
            raise ValueError("Spotify volume adjustment must be between -100 and 100.")
        if not self._spotify_is_running():
            return "Spotify is not currently running, so its volume was not changed."
        previous = self._spotify_volume()
        target = max(0, min(100, previous + amount))
        return self._set_and_verify_spotify_volume(previous, target)

    def _set_and_verify_spotify_volume(self, previous: int, target: int) -> str:
        output = self._run([
            "osascript",
            "-e",
            '\n'.join([
                'tell application "Spotify"',
                f"set sound volume to {target}",
                "try",
                "return sound volume as text",
                "on error",
                'return "unverified"',
                "end try",
                "end tell",
            ]),
        ])
        try:
            actual = int(output)
        except ValueError:
            actual = -1
        if actual != target:
            observed = f"{actual} percent" if 0 <= actual <= 100 else "an unreadable level"
            return (
                f"Spotify volume was requested at {target} percent, but Spotify "
                f"reported {observed}. The change was not verified and was not retried."
            )
        return f"Spotify volume changed from {previous} to {target} percent."

    @staticmethod
    def _spotify_track_uri(url: str) -> str | None:
        """Convert only a genuine public Spotify track URL into a safe URI."""
        parsed = urlparse(url)
        if parsed.scheme != "https" or (parsed.hostname or "").casefold() != "open.spotify.com":
            return None
        match = _SPOTIFY_TRACK_PATH.fullmatch(parsed.path)
        if match is None:
            return None
        return "spotify:track:" + match.group(1)

    def resolve_spotify_track(self, query: str) -> tuple[str, str]:
        """Resolve a spoken title/artist query to a validated Spotify track URI."""
        clean_query = " ".join(query.strip().split())[:200]
        if not clean_query:
            raise ValueError("A song title is required.")
        print(f"[apps] resolving Spotify track: {clean_query}")
        try:
            results = DDGS().text(
                f"site:open.spotify.com/track {clean_query}", max_results=6
            )
        except Exception as exc:  # noqa: BLE001 -- action failure goes back to Gemini
            raise RuntimeError(
                f"Spotify track lookup failed: {type(exc).__name__}: {exc}"
            ) from exc

        for result in results or []:
            url = str(result.get("href") or result.get("url") or "").strip()
            uri = self._spotify_track_uri(url)
            if uri is None:
                continue
            title = " ".join(str(result.get("title") or "Spotify track").split())[:200]
            print(f"[apps] Spotify match: {title} — {url}")
            return uri, clean_query
        raise RuntimeError(f"No validated Spotify track was found for {clean_query!r}.")

    def play_spotify_track(self, query: str) -> str:
        """Resolve and immediately play the strongest exact-track result."""
        self._require_macos()
        self.resolve_app("Spotify")
        uri, clean_query = self.resolve_spotify_track(query)
        # uri contains only a fixed prefix and a validated 22-character base62 id.
        if not re.fullmatch(r"spotify:track:[A-Za-z0-9]{22}", uri):
            raise ValueError("The resolved Spotify track URI was not valid.")
        state, observed_uri = self._spotify_command_and_state(f'play track "{uri}"')
        if state == "playing" and observed_uri == uri:
            return f"Spotify started the track resolved for {clean_query!r}."
        return (
            f"Sent Spotify a play request for {clean_query!r}; observed player state "
            f"is {state}, but playback of the requested track is not yet verified. "
            "The command was not retried."
        )
