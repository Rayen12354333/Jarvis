"""macOS app actions without launching real applications."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis import apps
from jarvis.apps import MacAppController


def _installed_apps(tmp_path: Path) -> MacAppController:
    (tmp_path / "Spotify.app").mkdir()
    (tmp_path / "Google Chrome.app").mkdir()
    return MacAppController(app_roots=(tmp_path,))


def test_open_app_resolves_only_an_installed_bundle(monkeypatch, tmp_path) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):  # noqa: ANN001
        commands.append(command)
        return SimpleNamespace(stdout="", returncode=0)

    monkeypatch.setattr(apps.sys, "platform", "darwin")
    monkeypatch.setattr(apps.subprocess, "run", fake_run)
    controller = _installed_apps(tmp_path)

    result = controller.open_app("chrome")

    assert result == "Opened Google Chrome."
    assert commands == [["open", str(tmp_path / "Google Chrome.app")]]


def test_unknown_app_is_rejected_before_open(monkeypatch, tmp_path) -> None:
    def unexpected_run(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("open must not run for an unknown app")

    monkeypatch.setattr(apps.sys, "platform", "darwin")
    monkeypatch.setattr(apps.subprocess, "run", unexpected_run)
    controller = _installed_apps(tmp_path)

    with pytest.raises(ValueError, match="could not find"):
        controller.open_app("Definitely Not Installed")


def test_spotify_search_uses_encoded_uri_and_installed_app(
    monkeypatch, tmp_path
) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):  # noqa: ANN001
        commands.append(command)
        return SimpleNamespace(stdout="", returncode=0)

    monkeypatch.setattr(apps.sys, "platform", "darwin")
    monkeypatch.setattr(apps.subprocess, "run", fake_run)
    controller = _installed_apps(tmp_path)

    result = controller.search("Spotify", "Daft Punk around the world")

    assert result == "Opened Spotify search results for 'Daft Punk around the world'."
    assert commands == [
        [
            "open",
            "-a",
            "Spotify",
            "spotify:search:Daft+Punk+around+the+world",
        ]
    ]


def test_spotify_playback_uses_only_fixed_applescript(monkeypatch, tmp_path) -> None:
    commands: list[list[str]] = []
    controller = _installed_apps(tmp_path)

    def fake_controller_run(command: list[str]) -> str:
        commands.append(command)
        return "playing|spotify:track:6DCZcSspjsKoFjzjrWoCdn"

    monkeypatch.setattr(apps.sys, "platform", "darwin")
    monkeypatch.setattr(controller, "_run", fake_controller_run)

    result = controller.control_spotify("play")

    assert result == "Started or resumed Spotify playback."
    assert len(commands) == 1
    assert commands[0][:2] == ["osascript", "-e"]
    assert commands[0][-1].startswith('tell application "Spotify"\nplay\n')
    assert "set observedState to player state as text" in commands[0][-1]


def test_spotify_volume_adjusts_app_without_touching_system_volume(
    monkeypatch, tmp_path
) -> None:
    commands: list[list[str]] = []
    controller = _installed_apps(tmp_path)

    def fake_controller_run(command: list[str]) -> str:
        commands.append(command)
        if "return (sound volume as text)" in command[-1]:
            return "65"
        return "55"

    monkeypatch.setattr(apps.sys, "platform", "darwin")
    monkeypatch.setattr(controller, "_spotify_is_running", lambda: True)
    monkeypatch.setattr(controller, "_run", fake_controller_run)

    result = controller.adjust_spotify_volume(-10)

    assert result == "Spotify volume changed from 65 to 55 percent."
    assert len(commands) == 2
    assert commands[0] == [
        "osascript", "-e", 'tell application "Spotify" to return (sound volume as text)'
    ]
    assert commands[1][-1].startswith('tell application "Spotify"\nset sound volume to 55\n')
    assert "return sound volume as text" in commands[1][-1]


def test_spotify_volume_set_validates_range_before_applescript(
    monkeypatch, tmp_path
) -> None:
    controller = _installed_apps(tmp_path)
    monkeypatch.setattr(apps.sys, "platform", "darwin")

    with pytest.raises(ValueError, match="between 0 and 100"):
        controller.set_spotify_volume(101)


def test_named_track_is_resolved_to_validated_uri_then_played(
    monkeypatch, tmp_path
) -> None:
    class FakeDDGS:
        def text(self, query: str, *, max_results: int):
            assert query == "site:open.spotify.com/track God's Plan Drake"
            assert max_results == 6
            return [
                {
                    "title": "Untrusted non-Spotify result",
                    "href": "https://evil.example/track/6DCZcSspjsKoFjzjrWoCdn",
                },
                {
                    "title": "God's Plan - Drake | Spotify",
                    "href": "https://open.spotify.com/track/6DCZcSspjsKoFjzjrWoCdn?si=test",
                },
            ]

    commands: list[list[str]] = []
    controller = _installed_apps(tmp_path)

    def fake_controller_run(command: list[str]) -> str:
        commands.append(command)
        return "playing|spotify:track:6DCZcSspjsKoFjzjrWoCdn"

    monkeypatch.setattr(apps.sys, "platform", "darwin")
    monkeypatch.setattr(apps, "DDGS", FakeDDGS)
    monkeypatch.setattr(controller, "_run", fake_controller_run)

    result = controller.play_spotify_track("God's Plan Drake")

    assert result == "Spotify started the track resolved for \"God's Plan Drake\"."
    assert len(commands) == 1
    script = commands[0][-1]
    assert script.startswith(
        'tell application "Spotify"\nplay track "spotify:track:6DCZcSspjsKoFjzjrWoCdn"\n'
    )
    assert "set observedTrack to id of current track as text" in script
    assert "God's Plan" not in script


@pytest.mark.parametrize(
    "url",
    [
        "http://open.spotify.com/track/6DCZcSspjsKoFjzjrWoCdn",
        "https://spotify.example/track/6DCZcSspjsKoFjzjrWoCdn",
        "https://open.spotify.com/album/6DCZcSspjsKoFjzjrWoCdn",
        "https://open.spotify.com/track/not-a-valid-id",
    ],
)
def test_spotify_uri_validation_rejects_non_track_urls(url: str) -> None:
    assert MacAppController._spotify_track_uri(url) is None


@pytest.mark.parametrize("observed", ["65", "unverified", "999", ""])
def test_volume_change_does_not_claim_success_without_matching_readback(
    monkeypatch, tmp_path, observed
) -> None:
    controller = _installed_apps(tmp_path)
    commands: list[list[str]] = []

    def fake_run(command):
        commands.append(command)
        return "65" if len(commands) == 1 else observed

    monkeypatch.setattr(apps.sys, "platform", "darwin")
    monkeypatch.setattr(controller, "_spotify_is_running", lambda: True)
    monkeypatch.setattr(controller, "_run", fake_run)

    result = controller.adjust_spotify_volume(-10)

    assert "change was not verified" in result
    assert "volume changed from" not in result
    assert len(commands) == 2  # No repeated write, even when readback is unavailable.


def test_absolute_volume_uses_matching_readback_before_confirming(monkeypatch, tmp_path) -> None:
    controller = _installed_apps(tmp_path)
    outputs = iter(["65", "20"])
    monkeypatch.setattr(apps.sys, "platform", "darwin")
    monkeypatch.setattr(controller, "_spotify_is_running", lambda: True)
    monkeypatch.setattr(controller, "_run", lambda command: next(outputs))

    assert controller.set_spotify_volume(20) == "Spotify volume changed from 65 to 20 percent."


@pytest.mark.parametrize(
    "observed",
    [
        "playing|spotify:track:AAAAAAAAAAAAAAAAAAAAAA",
        "paused|spotify:track:6DCZcSspjsKoFjzjrWoCdn",
        "unknown|",
        "",
    ],
)
def test_named_track_requires_matching_id_and_playing_state(
    monkeypatch, tmp_path, observed
) -> None:
    controller = _installed_apps(tmp_path)
    commands: list[list[str]] = []

    def fake_run(command):
        commands.append(command)
        return observed

    monkeypatch.setattr(apps.sys, "platform", "darwin")
    monkeypatch.setattr(
        controller, "resolve_spotify_track",
        lambda query: ("spotify:track:6DCZcSspjsKoFjzjrWoCdn", query),
    )
    monkeypatch.setattr(controller, "_run", fake_run)

    result = controller.play_spotify_track("God's Plan")

    assert "not yet verified" in result
    assert "Spotify started" not in result
    assert len(commands) == 1


@pytest.mark.parametrize(
    ("command", "observed", "confirmed"),
    [
        ("play", "playing|", True),
        ("play", "paused|", False),
        ("pause", "paused|", True),
        ("pause", "playing|", False),
        ("next", "playing|", False),
        ("previous", "playing|", False),
        ("play_pause", "paused|", False),
    ],
)
def test_playback_confirmation_matches_observed_state(
    monkeypatch, tmp_path, command, observed, confirmed
) -> None:
    controller = _installed_apps(tmp_path)
    monkeypatch.setattr(apps.sys, "platform", "darwin")
    monkeypatch.setattr(controller, "_spotify_is_running", lambda: True)
    monkeypatch.setattr(controller, "_run", lambda argv: observed)

    result = controller.control_spotify(command)

    assert ("not been verified" not in result) is confirmed
    if not confirmed:
        assert result.startswith("Sent Spotify")


def test_resolver_cannot_inject_applescript_into_track_playback(monkeypatch, tmp_path) -> None:
    controller = _installed_apps(tmp_path)
    monkeypatch.setattr(apps.sys, "platform", "darwin")
    monkeypatch.setattr(
        controller, "resolve_spotify_track", lambda query: ('bad"\nquit', query)
    )
    monkeypatch.setattr(
        controller, "_run", lambda argv: pytest.fail("invalid URI must not reach osascript")
    )

    with pytest.raises(ValueError, match="URI was not valid"):
        controller.play_spotify_track("A song")
