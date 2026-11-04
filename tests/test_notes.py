"""Apple Notes creation tests without writing to the real Notes database."""
from __future__ import annotations

from types import SimpleNamespace

from jarvis import notes
from jarvis.notes import NotesController


def test_create_note_passes_escaped_content_as_arguments(monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):  # noqa: ANN001
        commands.append(command)
        return SimpleNamespace(stdout="x-coredata://note/ABC123\n")

    monkeypatch.setattr(notes.sys, "platform", "darwin")
    monkeypatch.setattr(notes.subprocess, "run", fake_run)
    controller = NotesController()
    title = 'Ideas "for later"'
    body = "First line\n<script>do not run</script>"

    result = controller.create_note(title, body)

    command = commands[0]
    assert command[:2] == ["osascript", "-e"]
    assert title not in command[2]
    assert body not in command[2]
    assert command[3:5] == ["--", title]
    assert title not in command[5]
    assert "&lt;script&gt;do not run&lt;/script&gt;" in command[5]
    assert "<br>" in command[5]
    assert "Apple Notes returned note ID x-coredata://note/ABC123" in result


def test_create_note_requires_title_and_content(monkeypatch) -> None:
    def unexpected_run(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("osascript should not run")

    monkeypatch.setattr(notes.sys, "platform", "darwin")
    monkeypatch.setattr(notes.subprocess, "run", unexpected_run)
    controller = NotesController()

    try:
        controller.create_note("", "content")
    except ValueError as exc:
        assert "title" in str(exc)
    else:
        raise AssertionError("an empty title must fail")

    try:
        controller.create_note("Title", "")
    except ValueError as exc:
        assert "content" in str(exc)
    else:
        raise AssertionError("empty content must fail")


def test_missing_created_note_id_is_treated_as_failure(monkeypatch) -> None:
    monkeypatch.setattr(notes.sys, "platform", "darwin")
    monkeypatch.setattr(
        notes.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=""),
    )

    try:
        NotesController().create_note("Title", "Body")
    except RuntimeError as exc:
        assert "did not return" in str(exc)
    else:
        raise AssertionError("a missing note id must fail")
