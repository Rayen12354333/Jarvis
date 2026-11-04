"""Menu-bar process and login-item behavior without launching a GUI."""

from __future__ import annotations

import plistlib
from pathlib import Path

from jarvis.menu_bar import VoiceProcessController, launch_agent_payload


class FakeProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def wait(self, timeout: float) -> int:
        assert timeout in {2, 8}
        assert self.returncode is not None
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def test_controller_starts_exact_venv_module_and_stops_it(tmp_path: Path) -> None:
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    process = FakeProcess()
    calls: list[tuple[list[str], dict]] = []

    def fake_popen(command: list[str], **kwargs):  # noqa: ANN003, ANN201
        calls.append((command, kwargs))
        return process

    controller = VoiceProcessController(
        python_executable=python,
        project_root=tmp_path,
        log_path=tmp_path / "logs" / "voice.log",
        activity_path=tmp_path / "activity.json",
        popen_factory=fake_popen,
    )

    assert controller.start()
    assert not controller.start()
    assert controller.is_running()
    assert calls[0][0] == [str(python), "-m", "jarvis.main"]
    assert calls[0][1]["cwd"] == str(tmp_path)
    assert calls[0][1]["start_new_session"] is True

    assert controller.stop()
    assert process.terminated
    assert not process.killed
    assert not controller.is_running()


def test_controller_reports_an_unexpected_exit(tmp_path: Path) -> None:
    python = tmp_path / "python"
    python.touch()
    process = FakeProcess()
    controller = VoiceProcessController(
        python_executable=python,
        project_root=tmp_path,
        log_path=tmp_path / "voice.log",
        activity_path=tmp_path / "activity.json",
        popen_factory=lambda *args, **kwargs: process,
    )

    controller.start()
    process.returncode = 3

    assert not controller.is_running()
    assert controller.last_exit_code == 3


def test_launch_agent_uses_venv_without_shell_activation(tmp_path: Path) -> None:
    python = tmp_path / ".venv" / "bin" / "python"
    payload = launch_agent_payload(
        python_executable=python,
        project_root=tmp_path,
        log_path=tmp_path / "menu.log",
    )

    encoded = plistlib.dumps(payload)
    decoded = plistlib.loads(encoded)

    assert decoded["ProgramArguments"] == [
        str(python),
        "-m",
        "jarvis.menu_bar",
    ]
    assert decoded["WorkingDirectory"] == str(tmp_path)
    assert decoded["RunAtLoad"] is True
    assert "activate" not in encoded.decode()


def test_typed_request_restores_observed_app_before_model_runs(monkeypatch):
    from types import SimpleNamespace

    from jarvis import menu_bar

    order = []
    previous = SimpleNamespace(activateWithOptions_=lambda options: order.append("restore"))
    monkeypatch.setattr(
        menu_bar,
        "NSWorkspace",
        SimpleNamespace(
            sharedWorkspace=lambda: SimpleNamespace(frontmostApplication=lambda: previous),
        ),
    )
    monkeypatch.setattr(
        menu_bar.rumps,
        "Window",
        lambda **kwargs: SimpleNamespace(
            run=lambda: order.append("dialog") or SimpleNamespace(clicked=1, text="Read this page"),
        ),
    )
    app = SimpleNamespace(
        controller=SimpleNamespace(is_running=lambda: False),
        commands=SimpleNamespace(busy=False, submit=lambda text: order.append("submit")),
        refresh_status=lambda: None,
    )
    menu_bar.JarvisMenuBar.ask_jarvis(app)
    assert order == ["dialog", "restore", "submit"]


def test_completed_request_marks_reply_ready_without_stealing_focus(monkeypatch):
    from types import SimpleNamespace

    from jarvis import menu_bar
    from jarvis.commands import CommandReply

    def forbidden_alert(*args, **kwargs):
        raise AssertionError("A completed command must not steal focus with a popup")

    monkeypatch.setattr(menu_bar.rumps, "alert", forbidden_alert)

    def item():
        return SimpleNamespace(title="", set_callback=lambda callback: None)

    app = SimpleNamespace(
        controller=SimpleNamespace(is_running=lambda: False, last_exit_code=None),
        commands=SimpleNamespace(busy=False, take_reply=lambda: CommandReply("Done", 1.2)),
        _reply_unread=False,
        status_item=item(),
        start_item=item(),
        stop_item=item(),
        ask_item=item(),
        cancel_item=item(),
        reply_item=item(),
        start_jarvis=None,
        stop_jarvis=None,
        ask_jarvis=None,
        cancel_request=None,
        history_item=item(),
        setup_item=item(),
        guide_item=item(),
        sessions_item=item(),
        logs_item=item(),
        show_reply=None,
        show_history=None,
        show_setup=None,
        open_guide=None,
        open_sessions=None,
        open_log=None,
        refresh_screen_access=lambda: None,
        _screen_remaining=0,
    )
    menu_bar.JarvisMenuBar.refresh_status(app)
    assert app._reply_unread
    assert app.reply_item.title == "Read New Reply…"
    assert "Done" in app.last_reply
