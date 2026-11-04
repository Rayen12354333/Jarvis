"""Setup information never requests permissions or reveals provider credentials."""

from jarvis import diagnostics


def test_setup_report_is_read_only_and_keeps_keys_private(monkeypatch):
    monkeypatch.setattr(diagnostics, "GEMINI_API_KEY", "never-show-this-key")
    monkeypatch.setattr(diagnostics, "GROQ_API_KEY", "also-private")
    monkeypatch.setattr(diagnostics, "permission_status", lambda: {"Microphone": "Denied"})
    monkeypatch.setattr(diagnostics, "_installed", lambda name: True)
    report = diagnostics.setup_report()
    assert "Configured" in report
    assert "never-show" not in report
    assert "also-private" not in report
    assert "Microphone: Denied" in report
    assert "Python executable:" in report
    assert "not a connection test" in report
