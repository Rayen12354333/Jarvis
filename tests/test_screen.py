"""Time-limited screen-vision tests without capturing the real display."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis import screen
from jarvis.screen import ScreenVisionManager


class Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def tick(self, seconds: float) -> None:
        self.value += seconds


def test_screen_capture_requires_active_unexpired_authorization() -> None:
    clock = Clock()
    captures: list[bool] = []
    manager = ScreenVisionManager(
        foreground_pid=lambda: 123,
        monotonic=lambda: clock.value,
        capture=lambda: captures.append(True) or b"png bytes",
    )

    with pytest.raises(RuntimeError, match="not authorized"):
        manager.capture("What is here?")

    confirmation = manager.start(30, "explain a diagram")
    captured = manager.capture("Explain the highlighted box")
    assert "30 seconds" in confirmation
    assert captured.image_bytes == b"png bytes"
    assert captured.question == "Explain the highlighted box"
    assert captures == [True]

    clock.tick(30)
    assert not manager.is_active()
    with pytest.raises(RuntimeError, match="expired"):
        manager.capture("What changed?")


def test_screen_authorization_is_bounded_and_revocable() -> None:
    manager = ScreenVisionManager(capture=lambda: b"png", foreground_pid=lambda: 123)

    with pytest.raises(ValueError, match="between 5 seconds and 30 minutes"):
        manager.start(1801)

    manager.start(60, "temporary help")
    assert manager.is_active()
    assert "stopped" in manager.stop()
    assert not manager.is_active()


def test_scroll_requires_authorization_and_invalidates_capture() -> None:
    clock = Clock()
    scrolls: list[tuple[str, int]] = []
    clicks: list[tuple[int, int]] = []
    manager = ScreenVisionManager(
        foreground_pid=lambda: 123,
        monotonic=lambda: clock.value,
        capture=lambda: b"png",
        scroll=lambda direction, amount: scrolls.append((direction, amount)),
        click=lambda x, y: clicks.append((x, y)),
    )

    with pytest.raises(RuntimeError, match="not authorized"):
        manager.scroll("down", 5)

    manager.start(60, "browse visible results")
    manager.capture("Find the second video")
    assert "Scroll event sent down" in manager.scroll("down", 5)
    assert scrolls == [("down", 5)]
    with pytest.raises(RuntimeError, match="fresh screen inspection"):
        manager.click(500, 500)
    assert clicks == []


def test_click_requires_fresh_capture_and_allows_only_one_click() -> None:
    clock = Clock()
    clicks: list[tuple[int, int]] = []
    manager = ScreenVisionManager(
        foreground_pid=lambda: 123,
        monotonic=lambda: clock.value,
        capture=lambda: b"png",
        click=lambda x, y: clicks.append((x, y)),
    )
    manager.start(60, "select a visible video")

    with pytest.raises(RuntimeError, match="fresh screen inspection"):
        manager.click(250, 400)

    manager.capture("Find the second video")
    assert "Clicked" in manager.click(250, 400)
    assert clicks == [(250, 400)]
    with pytest.raises(RuntimeError, match="fresh screen inspection"):
        manager.click(250, 400)


def test_click_rejects_stale_capture_and_invalid_coordinates() -> None:
    clock = Clock()
    manager = ScreenVisionManager(
        foreground_pid=lambda: 123,
        monotonic=lambda: clock.value,
        capture=lambda: b"png",
        click=lambda x, y: None,
    )
    manager.start(60, "select a visible target")
    manager.capture("Locate it")

    with pytest.raises(ValueError, match="between 0 and 1000"):
        manager.click(1001, 500)

    clock.tick(16)
    with pytest.raises(RuntimeError, match="stale"):
        manager.click(500, 500)


@pytest.mark.parametrize("direction", ["up", "down", "left", "right"])
def test_scroll_accepts_each_direction(direction: str) -> None:
    scrolls: list[tuple[str, int]] = []
    manager = ScreenVisionManager(
        foreground_pid=lambda: 123,
        capture=lambda: b"png",
        scroll=lambda requested, amount: scrolls.append((requested, amount)),
    )
    manager.start(60)

    manager.scroll(direction, 1)  # type: ignore[arg-type]
    assert scrolls == [(direction, 1)]


def test_real_capture_path_is_removed_after_read(monkeypatch) -> None:
    captured_paths: list[Path] = []

    def fake_run(command, **kwargs):  # noqa: ANN001
        path = Path(command[-1])
        captured_paths.append(path)
        path.write_bytes(b"fake png")
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(screen.sys, "platform", "darwin")
    monkeypatch.setattr(screen.subprocess, "run", fake_run)

    assert screen.capture_main_display() == b"fake png"
    assert len(captured_paths) == 1
    assert not captured_paths[0].exists()


def test_app_switch_after_capture_blocks_click_and_consumes_observation() -> None:
    pid = [123]
    clicks = []
    manager = ScreenVisionManager(
        capture=lambda: b"png",
        click=lambda x, y: clicks.append((x, y)),
        foreground_pid=lambda: pid[0],
    )
    manager.start(60)
    manager.capture()
    pid[0] = 456
    with pytest.raises(RuntimeError, match="foreground app changed"):
        manager.click(500, 500)
    pid[0] = 123
    with pytest.raises(RuntimeError, match="fresh screen inspection"):
        manager.click(500, 500)
    assert clicks == []


def test_app_switch_during_capture_discards_image_and_click_authorization() -> None:
    pid = [123]

    def capture():
        pid[0] = 456
        return b"must not be returned"

    manager = ScreenVisionManager(capture=capture, foreground_pid=lambda: pid[0])
    manager.start(60)
    with pytest.raises(RuntimeError, match="foreground app changed during screen capture"):
        manager.capture()
    with pytest.raises(RuntimeError, match="fresh screen inspection"):
        manager.click(500, 500)


@pytest.mark.parametrize("change", ["expire", "revoke", "restart", "scroll"])
def test_changed_authorization_during_capture_never_returns_late_screenshot(change) -> None:
    clock = Clock()

    def capture():
        if change == "expire":
            clock.tick(30)
        elif change == "revoke":
            manager.stop()
        elif change == "restart":
            manager.start(60, "A different task")
        else:
            manager.scroll("down")
        return b"late screenshot must be discarded"

    manager = ScreenVisionManager(
        capture=capture,
        monotonic=lambda: clock.value,
        foreground_pid=lambda: 123,
        scroll=lambda direction, amount: None,
    )
    manager.start(30)
    with pytest.raises(RuntimeError, match="screenshot was discarded"):
        manager.capture()
    with pytest.raises(RuntimeError):
        manager.click(500, 500)


def test_failed_capture_invalidates_earlier_click_permission() -> None:
    failing = [False]

    def capture():
        if failing[0]:
            raise RuntimeError("Screenshot failed")
        return b"png"

    manager = ScreenVisionManager(capture=capture, foreground_pid=lambda: 123)
    manager.start(60)
    manager.capture()
    failing[0] = True
    with pytest.raises(RuntimeError, match="Screenshot failed"):
        manager.capture()
    with pytest.raises(RuntimeError, match="fresh screen inspection"):
        manager.click(500, 500)


def test_failed_focus_check_invalidates_earlier_click_permission() -> None:
    failing = [False]

    def focus():
        if failing[0]:
            raise RuntimeError("No foreground app")
        return 123

    manager = ScreenVisionManager(capture=lambda: b"png", foreground_pid=focus)
    manager.start(60)
    manager.capture()
    failing[0] = True
    with pytest.raises(RuntimeError, match="No foreground app"):
        manager.click(500, 500)
    failing[0] = False
    with pytest.raises(RuntimeError, match="fresh screen inspection"):
        manager.click(500, 500)


def test_focus_check_cannot_restore_revoked_click_authorization() -> None:
    revoke = [False]
    clicks = []

    def focus():
        if revoke[0]:
            manager.stop()
        return 123

    manager = ScreenVisionManager(
        capture=lambda: b"png", foreground_pid=focus,
        click=lambda x, y: clicks.append((x, y)),
    )
    manager.start(60)
    manager.capture()
    revoke[0] = True
    with pytest.raises(RuntimeError, match="authorization or view changed"):
        manager.click(500, 500)
    assert clicks == []


def test_foreground_pid_reader_is_read_only_and_rejects_missing_app(monkeypatch) -> None:
    import sys

    active = [SimpleNamespace(processIdentifier=lambda: 123)]
    workspace = SimpleNamespace(frontmostApplication=lambda: active[0])
    appkit = SimpleNamespace(NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: workspace))
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    monkeypatch.setattr(screen.sys, "platform", "darwin")
    assert screen.foreground_application_pid() == 123
    active[0] = None
    with pytest.raises(RuntimeError, match="No foreground app"):
        screen.foreground_application_pid()
