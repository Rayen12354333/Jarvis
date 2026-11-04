"""Explicit consent and its UI indicator; no real screen capture or permissions."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from jarvis.screen import ScreenVisionManager, prepare_screen_image
from jarvis.screen_access import ScreenAccessStore


def test_access_expires_and_cannot_exceed_thirty_minutes(tmp_path):
    now = [100.0]
    store = ScreenAccessStore(
        tmp_path / "access.json", clock=lambda: now[0], is_alive=lambda pid: True
    )
    assert store.read() is None
    access = store.grant()
    assert access.expires_at - access.started_at == 1800
    assert store.remaining() == 1800
    now[0] += 1800
    assert store.read() is None
    with pytest.raises(ValueError):
        store.grant(1801)


def test_access_stops_when_owner_exits_or_user_revokes(tmp_path):
    alive = [True]
    store = ScreenAccessStore(tmp_path / "access.json", is_alive=lambda pid: alive[0])
    store.grant()
    assert store.read()
    alive[0] = False
    assert store.read() is None
    alive[0] = True
    store.revoke()
    assert store.read() is None


def test_cross_process_revoke_invalidates_existing_click(tmp_path):
    store = ScreenAccessStore(tmp_path / "access.json", is_alive=lambda pid: True)
    manager = ScreenVisionManager(
        capture=lambda: b"fake",
        foreground_pid=lambda: 123,
        access_store=store,
        click=lambda *args: pytest.fail("Revoked access must never click"),
    )
    store.grant()
    assert manager.is_active()
    manager.capture()
    store.revoke()
    assert not manager.is_active()
    with pytest.raises(RuntimeError, match="not authorized"):
        manager.click(10, 10)


def test_voice_revocation_clears_shared_menu_grant(tmp_path):
    store = ScreenAccessStore(tmp_path / "access.json", is_alive=lambda pid: True)
    manager = ScreenVisionManager(access_store=store)
    store.grant()
    manager.stop()
    assert store.read() is None


def test_corrupt_or_future_access_is_not_granted(tmp_path):
    path = tmp_path / "access.json"
    store = ScreenAccessStore(path, clock=lambda: 100, is_alive=lambda pid: True)
    path.write_text("garbage")
    assert store.read() is None
    path.write_text(json.dumps(dict(token="x" * 32, started_at=200, expires_at=300, owner_pid=123)))
    assert store.read() is None


def test_screen_upload_is_small_and_preserves_coordinate_aspect():
    from io import BytesIO

    from PIL import Image

    raw = BytesIO()
    Image.new("RGB", (2560, 1664), color="white").save(raw, format="PNG")
    data, mime = prepare_screen_image(raw.getvalue())
    with Image.open(BytesIO(data)) as result:
        assert result.size == (1600, 1040)
        assert result.format == "JPEG"
    assert mime == "image/jpeg"
    assert len(data) < 100_000


def test_menu_indicator_tracks_consent_and_stops_on_expiry():
    from jarvis.menu_bar import JarvisMenuBar

    remaining, events = [60], []

    def item():
        return SimpleNamespace(title="", set_callback=lambda callback: None)

    app = SimpleNamespace(
        screen_access=SimpleNamespace(remaining=lambda: remaining[0]),
        screen_overlay=SimpleNamespace(
            show=lambda: events.append("show"), hide=lambda: events.append("hide")
        ),
        screen_status_item=item(),
        screen_on_item=item(),
        screen_off_item=item(),
        enable_screen=None,
        disable_screen=None,
    )
    JarvisMenuBar.refresh_screen_access(app)
    assert "01:00" in app.screen_status_item.title
    remaining[0] = 0
    JarvisMenuBar.refresh_screen_access(app)
    assert app.screen_status_item.title == "Screen: Off"
    assert events == ["show", "hide"]


def test_indicator_failure_revokes_screen_access():
    from jarvis.menu_bar import JarvisMenuBar

    events = []

    def fail():
        raise RuntimeError("No window server")

    def item():
        return SimpleNamespace(title="", set_callback=lambda callback: None)

    app = SimpleNamespace(
        screen_access=SimpleNamespace(remaining=lambda: 50, revoke=lambda: events.append("revoke")),
        screen_overlay=SimpleNamespace(show=fail),
        screen_status_item=item(),
        screen_on_item=item(),
        screen_off_item=item(),
        enable_screen=None,
        disable_screen=None,
    )
    JarvisMenuBar.refresh_screen_access(app)
    assert events == ["revoke"]
    assert app._screen_remaining == 0
    assert "unavailable" in app.screen_status_item.title


def test_quitting_jarvis_revokes_before_waiting_on_workers(monkeypatch):
    from jarvis import menu_bar

    events = []
    app = SimpleNamespace(
        disable_screen=lambda: events.append("revoke"),
        _timer=SimpleNamespace(stop=lambda: events.append("timer")),
        commands=SimpleNamespace(close=lambda: events.append("commands")),
        controller=SimpleNamespace(stop=lambda: events.append("voice")),
    )
    monkeypatch.setattr(menu_bar.rumps, "quit_application", lambda: events.append("quit"))
    menu_bar.JarvisMenuBar.quit_controller(app)
    assert events == ["revoke", "timer", "commands", "voice", "quit"]


def test_overlay_is_click_through_and_never_steals_keyboard_focus(monkeypatch):
    import AppKit

    from jarvis.screen_overlay import ScreenOverlay

    events = []

    class Window:
        def initWithContentRect_styleMask_backing_defer_(self, *args):
            events.append(("frame", args[0]))
            return self

        def __getattr__(self, name):
            assert "Key" not in name
            return lambda *args: events.append((name, args))

    monkeypatch.setattr(AppKit, "NSWindow", SimpleNamespace(alloc=Window))
    monkeypatch.setattr(
        AppKit, "NSScreen", SimpleNamespace(screens=lambda: [SimpleNamespace(frame=lambda: "main")])
    )
    monkeypatch.setattr(
        AppKit,
        "NSColor",
        SimpleNamespace(colorWithCalibratedRed_green_blue_alpha_=lambda *args: args),
    )
    overlay = ScreenOverlay()
    overlay.show()
    overlay.show()
    assert ("frame", "main") in events
    assert ("setIgnoresMouseEvents_", (True,)) in events
    assert events.count(("orderFrontRegardless", ())) == 1
    overlay.hide()
    assert events[-2:] == [("orderOut_", (None,)), ("close", ())]
    assert overlay._window is None
