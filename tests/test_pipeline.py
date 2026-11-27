"""Release entry-point checks that must fail before producing a partial output."""
from __future__ import annotations

from pathlib import Path

from main import main


def test_release_requires_a_secret_before_writing_output(tmp_path, monkeypatch):
    inputs = tmp_path / "input"
    inputs.mkdir()
    output = tmp_path / "output"
    monkeypatch.delenv("RAKSHA_SECRET", raising=False)

    assert main(["--input", str(inputs), "--output", str(output)]) == 2
    assert not (output / "report.json").exists()


def test_cli_does_not_echo_a_pii_shaped_input_path(tmp_path, capsys):
    missing = tmp_path / "patient-Ram-Kumar-123456"
    assert main(["--input", str(missing), "--output", str(tmp_path / "out")]) == 2
    assert str(missing) not in capsys.readouterr().err


def test_cli_does_not_echo_exception_values(tmp_path, monkeypatch, caplog):
    inputs = tmp_path / "input"
    inputs.mkdir()
    output = tmp_path / "output"

    def fail_with_source_value(*args, **kwargs):
        raise ValueError("Patient Sample Name must not appear in logs")

    monkeypatch.setattr("main.run", fail_with_source_value)
    assert main(["--input", str(inputs), "--output", str(output)]) == 2
    assert "Patient Sample Name" not in caplog.text
    assert "pipeline failed" in caplog.text
