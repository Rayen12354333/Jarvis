"""Allow-listed local action execution without changing the real Mac."""

from __future__ import annotations

from types import SimpleNamespace

from jarvis import actions
from jarvis.actions import ListeningVolumeGuard, LocalAction, LocalActionExecutor
from jarvis.timers import TimerManager


def test_timer_actions_create_list_and_cancel() -> None:
    timers = TimerManager()
    executor = LocalActionExecutor(timers)

    created = executor.execute(LocalAction(name="set_timer", seconds=30, label="tea"))
    listed = executor.execute(LocalAction(name="list_timers"))
    cancelled = executor.execute(LocalAction(name="cancel_timer", label="tea"))

    assert "Set timer #1" in created
    assert "30 seconds" in created
    assert "#1 'tea'" in listed
    assert "Cancelled timer #1 'tea'" in cancelled
    assert timers.active() == []


def test_adjust_volume_reads_clamps_and_sets(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):  # noqa: ANN001
        commands.append(command)
        if "set volume output volume 0" in command:
            return SimpleNamespace(stdout="0\n")
        if any("get volume settings" in part for part in command):
            return SimpleNamespace(stdout="7,false\n")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(actions.sys, "platform", "darwin")
    monkeypatch.setattr(actions.subprocess, "run", fake_run)
    executor = LocalActionExecutor()

    result = executor.execute(LocalAction(name="adjust_volume", amount=-10))

    assert result == "Output volume changed from 7 to 0 percent."
    assert "set volume output volume 0" in commands[-1]
    assert commands[-1][-1] == "return output volume of (get volume settings)"
    assert all(command[0] == "osascript" for command in commands)


def test_invalid_volume_is_rejected_without_running_osascript(monkeypatch) -> None:
    def unexpected_run(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("osascript should not run")

    monkeypatch.setattr(actions.subprocess, "run", unexpected_run)
    executor = LocalActionExecutor()

    result = executor.execute(LocalAction(name="set_volume", level=101))

    assert result == "FAILED set_volume: Volume level must be between 0 and 100."


def test_volume_confirmation_must_match_actual_device_state(monkeypatch):
    executor = LocalActionExecutor()
    monkeypatch.setattr(executor, "_run_osascript", lambda *args: "70")
    assert executor.execute(LocalAction(name="set_volume", level=20)).startswith(
        "FAILED set_volume:"
    )
    monkeypatch.setattr(executor, "_run_osascript", lambda *args: "false")
    assert executor.execute(LocalAction(name="mute_volume")).startswith("FAILED mute_volume:")


def test_listening_guard_mutes_temporarily_then_restores() -> None:
    class FakeVolumeExecutor:
        def __init__(self) -> None:
            self.muted = False
            self.changes: list[bool] = []

        def get_volume_state(self) -> tuple[int, bool]:
            return 70, self.muted

        def set_output_muted(self, muted: bool) -> None:
            self.muted = muted
            self.changes.append(muted)

    executor = FakeVolumeExecutor()
    guard = ListeningVolumeGuard(executor)  # type: ignore[arg-type]

    with guard.suppress_output() as newly_muted:
        assert newly_muted
        assert executor.muted

    assert not executor.muted
    assert executor.changes == [True, False]


def test_listening_guard_preserves_an_existing_mute() -> None:
    class AlreadyMutedExecutor:
        def get_volume_state(self) -> tuple[int, bool]:
            return 50, True

        def set_output_muted(self, muted: bool) -> None:
            raise AssertionError("an existing mute must not be changed")

    guard = ListeningVolumeGuard(AlreadyMutedExecutor())  # type: ignore[arg-type]

    with guard.suppress_output() as newly_muted:
        assert not newly_muted


def test_app_actions_delegate_only_structured_parameters() -> None:
    class FakeApps:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        def open_app(self, name: str) -> str:
            self.calls.append(("open", name))
            return "Opened Spotify."

        def search(self, app_name: str, query: str) -> str:
            self.calls.append(("search", app_name, query))
            return "Opened results."

        def control_spotify(self, command: str) -> str:
            self.calls.append(("spotify", command))
            return "Paused Spotify playback."

        def adjust_spotify_volume(self, amount: int) -> str:
            self.calls.append(("spotify_volume_adjust", amount))
            return "Spotify volume changed from 70 to 60 percent."

        def set_spotify_volume(self, level: int) -> str:
            self.calls.append(("spotify_volume_set", level))
            return "Spotify volume changed from 60 to 25 percent."

        def play_spotify_track(self, query: str) -> str:
            self.calls.append(("spotify_track", query))
            return "Spotify started the requested track."

    apps = FakeApps()
    executor = LocalActionExecutor(apps=apps)  # type: ignore[arg-type]

    assert "Opened Spotify" in executor.execute(
        LocalAction(name="open_application", app_name="Spotify")
    )
    assert "Opened results" in executor.execute(
        LocalAction(name="search_in_app", app_name="Spotify", query="Daft Punk")
    )
    assert "Paused Spotify" in executor.execute(
        LocalAction(name="control_spotify", media_command="pause")
    )
    assert "70 to 60" in executor.execute(LocalAction(name="adjust_spotify_volume", amount=-10))
    assert "60 to 25" in executor.execute(LocalAction(name="set_spotify_volume", level=25))
    assert "requested track" in executor.execute(
        LocalAction(name="play_spotify_track", query="God's Plan Drake")
    )
    assert apps.calls == [
        ("open", "Spotify"),
        ("search", "Spotify", "Daft Punk"),
        ("spotify", "pause"),
        ("spotify_volume_adjust", -10),
        ("spotify_volume_set", 25),
        ("spotify_track", "God's Plan Drake"),
    ]


def test_create_note_requires_a_confirmed_notes_result() -> None:
    class FakeNotes:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def create_note(self, title: str, body: str) -> str:
            self.calls.append((title, body))
            return "Created note; Apple Notes returned note ID verified-id."

    notes = FakeNotes()
    executor = LocalActionExecutor(notes=notes)  # type: ignore[arg-type]

    result = executor.execute(
        LocalAction(
            name="create_note",
            note_title="Shopping",
            note_body="Buy milk and coffee.",
        )
    )

    assert "verified-id" in result
    assert notes.calls == [("Shopping", "Buy milk and coffee.")]


def test_screen_input_actions_delegate_only_validated_parameters() -> None:
    class FakeScreen:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        def scroll(self, direction: str, amount: int) -> str:
            self.calls.append(("scroll", direction, amount))
            return "Scrolled down."

        def click(self, x: int, y: int) -> str:
            self.calls.append(("click", x, y))
            return "Clicked target."

    screen = FakeScreen()
    activities: list[str] = []
    executor = LocalActionExecutor(  # type: ignore[arg-type]
        screen=screen,
        activity_reporter=activities.append,
    )

    assert "Scrolled" in executor.execute(
        LocalAction(name="scroll_screen", scroll_direction="down", scroll_amount=4)
    )
    assert "Clicked" in executor.execute(
        LocalAction(name="click_screen", screen_x=320, screen_y=610)
    )
    assert screen.calls == [("scroll", "down", 4), ("click", 320, 610)]
    assert activities == ["Scrolling down…", "Clicking target…"]


def test_screen_input_actions_reject_missing_parameters() -> None:
    executor = LocalActionExecutor()

    assert executor.execute(LocalAction(name="scroll_screen")) == (
        "FAILED scroll_screen: A scroll direction is required."
    )
    assert executor.execute(LocalAction(name="click_screen", screen_x=100)) == (
        "FAILED click_screen: Fresh-screen target coordinates are required."
    )


def test_work_session_actions_persist_and_export_an_actual_artifact(tmp_path):
    from jarvis.workspaces import WorkspaceStore

    store = WorkspaceStore(tmp_path / "work.sqlite3", tmp_path / "exports")
    receipts = []
    executor = LocalActionExecutor(
        workspaces=store,
        result_reporter=lambda *args: receipts.append(args),
    )
    assert "Started" in executor.execute(
        LocalAction(
            name="start_workspace",
            workspace_name="Biology revision",
        )
    )
    saved = executor.execute(
        LocalAction(
            name="save_workspace_entry",
            entry_kind="next_step",
            entry_text="Review cell division.",
        )
    )
    assert not saved.startswith("FAILED ")
    assert "Review cell division" in executor.execute(LocalAction(name="read_workspace"))
    exported = executor.execute(LocalAction(name="export_workspace"))
    artifact = next((tmp_path / "exports").glob("*.md"))
    assert str(artifact) in exported
    assert "Review cell division" in artifact.read_text()
    assert "content omitted" in receipts[2][1]
    assert "Review cell division" not in receipts[2][1]


def test_browser_dispatch_and_parameter_errors():
    class FakeBrowser:
        def play_visible_video(self, index, app_name):
            assert (index, app_name) == (2, "Safari")
            return '{"playback_verified": false, "action": "opened_video"}'

    executor = LocalActionExecutor(browser=FakeBrowser())
    result = executor.execute(
        LocalAction(name="play_visible_video", item_index=2, app_name="Safari")
    )
    assert '"playback_verified": false' in result
    assert executor.execute(LocalAction(name="open_url")).startswith("FAILED open_url:")
    assert executor.execute(LocalAction(name="browser_navigate")).startswith("FAILED")


def test_reporting_failure_does_not_prevent_action():
    def fail(*args):
        raise OSError("no disk space")

    executor = LocalActionExecutor(activity_reporter=fail, result_reporter=fail)
    result = executor.execute(LocalAction(name="get_current_time"))
    assert "Current local date and time" in result
