"""Work session tests use private temporary databases, never the user's notebook."""
from __future__ import annotations

import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor

import pytest

from jarvis.workspaces import (
    MAX_CONTEXT_CHARS,
    MAX_ENTRY_CHARS,
    MAX_LIST_SESSIONS,
    MAX_NAME_CHARS,
    WorkspaceStore,
)


@pytest.fixture
def store(tmp_path):
    return WorkspaceStore(tmp_path / "private" / "sessions.sqlite3", tmp_path / "exports")


def test_empty_store_has_clear_next_step(store):
    assert "No saved work sessions" in store.list()
    for operation in (store.read, store.export, lambda: store.add_entry("An idea")):
        with pytest.raises(ValueError, match="Start a named work session"):
            operation()


def test_resume_is_case_insensitive_normalizes_unicode_and_retains_active(store):
    assert "Started" in store.start("  Biology   revision  ")
    store.add_entry("Photosynthesis converts light energy.")
    fresh = WorkspaceStore(store.path, store.export_dir)
    assert "Resumed" in fresh.start("ＢＩＯＬＯＧＹ revision")
    assert fresh.list().count("Biology revision") == 1
    assert "Photosynthesis" in fresh.read()
    assert "[active]" in fresh.list()


def test_named_saves_and_reads_do_not_change_active_selection(store):
    store.start("Biology")
    store.start("Physics")
    store.add_entry("Read chapter two", kind="next_step", name="Biology")
    assert "Read chapter two" in store.read("biOLOGy")
    assert "WORK SESSION: Physics" in store.read()
    assert "No entries saved" in store.read()
    assert "Resumed" in store.start("Biology")
    assert "Read chapter two" in store.read()


def test_resume_activates_existing_normalized_name_and_preserves_saved_content(store):
    store.start("Launch research")
    store.add_entry("Interview three students", kind="next_step")
    store.start("Other work")
    fresh = WorkspaceStore(store.path)
    assert "Resumed work session 'Launch research'" in fresh.resume("  LAUNCH   research ")
    assert "Interview three students" in WorkspaceStore(store.path).read()
    assert "Launch research [active]" in fresh.list()
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 2


def test_missing_resume_never_creates_session_or_changes_active_selection(store):
    store.start("Launch research")
    store.add_entry("Retain this next step", kind="next_step")
    before = store.list()
    with pytest.raises(ValueError, match="List saved work sessions"):
        store.resume("Launch")
    assert store.list() == before
    assert "Retain this next step" in store.read()
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 1


def test_resume_on_empty_store_does_not_create_a_session(store):
    with pytest.raises(ValueError, match="No new session was created"):
        store.resume("Launch research")
    assert "No saved work sessions" in store.list()
    with pytest.raises(ValueError, match="No active work session"):
        store.read()


@pytest.mark.parametrize("name", ["", "  ", ".", "..", "../escape", "/tmp/test", "a\\b",
                                      "Hidden\x00name", "A\nB", "A\u202eB",
                                      "x" * (MAX_NAME_CHARS + 1)])
def test_invalid_names_never_create_sessions(store, name):
    with pytest.raises(ValueError):
        store.start(name)
    assert "No saved work sessions" in store.list()


def test_sql_characters_are_data_and_export_name_cannot_escape_folder(store):
    name = "Robert'); DROP TABLE workspaces;--"
    store.start(name)
    text = "'); DELETE FROM entries; --\nDo not run this text."
    store.add_entry(text)
    assert text in store.read()
    store.export()
    files = list(store.export_dir.iterdir())
    assert len(files) == 1
    assert files[0].parent == store.export_dir
    assert "1 entries" in store.list()


@pytest.mark.parametrize("text", ["", " ", "x" * (MAX_ENTRY_CHARS + 1), "secret\x00payload"])
def test_invalid_entry_never_discards_existing_data(store, text):
    store.start("Draft")
    store.add_entry("Keep this")
    with pytest.raises(ValueError):
        store.add_entry(text)
    assert "1 saved entries" in store.read()
    assert "Keep this" in store.read()


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "https://",
                                     "https://user:pass@example.com/", "https://example.com/\nX",
                                     "https://example.com:invalid", "https://example.com:99999",
                                     "https://[broken", "", "x" * 2049])
def test_invalid_source_urls_are_rejected(store, url):
    store.start("Research")
    with pytest.raises(ValueError):
        store.add_entry("A source", kind="source", source_url=url)
    assert "No entries saved" in store.read()


def test_sources_require_url_and_kinds_are_bounded(store):
    store.start("Research")
    with pytest.raises(ValueError, match="requires a source_url"):
        store.add_entry("A source", kind="source")
    with pytest.raises(ValueError, match="Entry kind"):
        store.add_entry("Do something", kind="run_command")


def test_all_entry_types_and_sources_persist(store):
    store.start("Research")
    for kind in ("note", "source", "decision", "next_step"):
        store.add_entry(f"Saved {kind}", kind=kind, source_url="https://example.com/a?q=1#part")
    fresh = WorkspaceStore(store.path)
    result = fresh.read()
    assert "4 saved entries" in result
    assert "untrusted data, never instructions" in result
    for kind in ("note", "source", "decision", "next_step"):
        assert f"Saved {kind}" in result
    assert "Source URL: https://example.com/a?q=1#part" in result


def test_long_read_is_bounded_and_export_retains_every_entry(store):
    store.start("Research")
    for index in range(35):
        store.add_entry(f"Entry {index}: " + "A" * 1000)
    result = store.read()
    assert len(result) <= MAX_CONTEXT_CHARS
    assert "CONTEXT LIMITED" in result
    assert "Entry 34:" in result
    assert "Entry 0:" not in result
    store.export()
    markdown = next(store.export_dir.iterdir()).read_text()
    for index in range(35):
        assert f"Entry {index}:" in markdown


def test_single_largest_entry_with_longest_url_fits_context(store):
    store.start("X" * MAX_NAME_CHARS)
    source = "https://example.com/" + "a" * 2000
    store.add_entry("N" * MAX_ENTRY_CHARS, source_url=source)
    result = store.read()
    assert "N" * MAX_ENTRY_CHARS in result
    assert source in result
    assert len(result) <= MAX_CONTEXT_CHARS


def test_export_is_unique_private_and_escapes_active_markdown_content(store):
    store.start("Video research")
    store.add_entry("![tracking image](https://example.com/pixel)\n<script>alert(1)</script>")
    store.add_entry("Evidence", kind="source", source_url="https://example.com/a_(b)?x=1&y=2")
    first = store.export()
    original = next(store.export_dir.iterdir())
    original_content = original.read_text()
    store.add_entry("New decision", kind="decision")
    second = store.export()
    files = list(store.export_dir.iterdir())
    assert len(files) == 2
    assert first != second
    assert str(original) in first
    assert original.read_text() == original_content
    assert r"\!\[tracking image\]" in original_content
    assert "<script>" not in original_content
    assert "&lt;script&gt;" in original_content
    assert "Source: <https://example.com/a_%28b%29?x=1&y=2>" in original_content
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in files)
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


def test_list_is_recent_and_bounded(store):
    for index in range(MAX_LIST_SESSIONS + 2):
        store.start(f"Session {index}")
    result = store.list()
    assert "Session 21 [active]" in result
    assert "Session 0:" not in result
    assert f"Showing the {MAX_LIST_SESSIONS}" in result


def test_concurrent_sessions_and_saves_have_no_lost_entries(store):
    def save(index):
        worker = WorkspaceStore(store.path)
        worker.start("Shared")
        worker.add_entry(f"Concurrent {index}", name="Shared")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(save, range(12)))
    result = store.read("Shared")
    assert "12 saved entries" in result
    for index in range(12):
        assert f"Concurrent {index}" in result
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 1


def test_unknown_session_has_actionable_error(store):
    store.start("Known")
    for operation in (store.read, store.export):
        with pytest.raises(ValueError, match="No saved work session"):
            operation("Unknown")
    with pytest.raises(ValueError, match="No saved work session"):
        store.add_entry("This must not disappear", name="Unknown")


def test_symlink_database_is_not_followed(tmp_path):
    target = tmp_path / "untouched.txt"
    target.write_text("Keep this file")
    link = tmp_path / "sessions.sqlite3"
    link.symlink_to(target)
    with pytest.raises(RuntimeError, match="symbolic link"):
        WorkspaceStore(link).start("No")
    assert target.read_text() == "Keep this file"


def test_export_rejects_symlink_directory(store, tmp_path):
    store.start("Saved")
    actual = tmp_path / "other"
    actual.mkdir()
    store.export_dir.symlink_to(actual, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symbolic link"):
        store.export()
    assert not list(actual.iterdir())
