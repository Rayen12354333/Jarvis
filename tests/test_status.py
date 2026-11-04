"""Cross-process menu activity state tests."""

from __future__ import annotations

from pathlib import Path

from jarvis.status import clear_activity, publish_activity, read_activity


def test_activity_preserves_a_recent_action_while_state_advances(tmp_path: Path) -> None:
    path = tmp_path / "activity.json"
    publish_activity("Thinking…", path=path, now=100.0)
    publish_activity("Scrolling down…", action=True, path=path, now=101.0)
    publish_activity("Speaking…", path=path, now=101.1)

    status = read_activity(path, now=101.2)
    assert status is not None
    assert status.state == "Speaking…"
    assert status.visible_text(now=101.2) == "Scrolling down…"
    assert status.visible_text(now=104.0) == "Speaking…"


def test_activity_ignores_stale_or_broken_files(tmp_path: Path) -> None:
    path = tmp_path / "activity.json"
    publish_activity("Listening…", path=path, now=10.0)
    assert read_activity(path, now=131.0) is None

    path.write_text("not json", encoding="utf-8")
    assert read_activity(path, now=11.0) is None


def test_clear_activity_removes_status(tmp_path: Path) -> None:
    path = tmp_path / "activity.json"
    publish_activity("Ready", path=path, now=10.0)
    clear_activity(path)
    assert not path.exists()


def test_action_history_is_bounded_private_and_redacts_keys(tmp_path):
    import stat

    from jarvis.status import read_receipts, record_action

    path = tmp_path / "history.json"
    for index in range(24):
        record_action("set_volume", f"Returned {index}", 0.123, path=path, now=100 + index)
    record_action("open_url", "FAILED open_url: gsk_" + "a" * 30, 1.5, path=path, now=125)
    receipts = read_receipts(path)
    assert len(receipts) == 20
    assert receipts[-1].failed
    assert "gsk_" not in receipts[-1].result
    assert "[redacted]" in receipts[-1].result
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_broken_history_and_status_io_failures_do_not_crash(tmp_path, monkeypatch):
    from jarvis import status

    path = tmp_path / "history.json"
    path.write_text('{"broken": true}')
    assert status.read_receipts(path) == []

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(status.tempfile, "mkstemp", fail)
    status.publish_activity("Listening", path=tmp_path / "status.json")
    status.record_action("open_url", "Returned", 1.0, path=path)


def test_invalid_status_times_are_rejected(tmp_path):
    path = tmp_path / "status.json"
    path.write_text('{"state":"Listening","updated_at":NaN}')
    assert read_activity(path, now=100) is None
    publish_activity("Listening", path=path, now=2000)
    assert read_activity(path, now=100) is None
