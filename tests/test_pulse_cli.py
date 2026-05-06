"""Tests for CAM-PULSE CLI command surface."""

import inspect

from typer.testing import CliRunner

from claw.cli import app, pulse_app

runner = CliRunner()


def _invoke_pulse(*args: str):
    return runner.invoke(
        app,
        ["pulse", *args],
        env={"COLUMNS": "140", "TERM": "xterm-256color"},
    )


def _pulse_options(command_name: str) -> set[str]:
    for command in pulse_app.registered_commands:
        if command.name == command_name:
            options: set[str] = set()
            for parameter in inspect.signature(command.callback).parameters.values():
                param_decls = getattr(parameter.default, "param_decls", ())
                options.update(param_decls)
            return options
    raise AssertionError(f"pulse command not registered: {command_name}")


class TestPulseCLI:
    def test_pulse_help(self):
        result = _invoke_pulse("--help")
        assert result.exit_code == 0
        assert "CAM-PULSE" in result.stdout
        assert "scan" in result.stdout
        assert "daemon" in result.stdout
        assert "status" in result.stdout
        assert "discoveries" in result.stdout
        assert "report" in result.stdout
        assert "preflight" in result.stdout

    def test_pulse_scan_help(self):
        result = _invoke_pulse("scan", "--help")
        assert result.exit_code == 0
        assert {"--keywords", "--from-date", "--dry-run"} <= _pulse_options("scan")

    def test_pulse_daemon_help(self):
        result = _invoke_pulse("daemon", "--help")
        assert result.exit_code == 0
        assert "--interval" in _pulse_options("daemon")

    def test_pulse_status_help(self):
        result = _invoke_pulse("status", "--help")
        assert result.exit_code == 0

    def test_pulse_discoveries_help(self):
        result = _invoke_pulse("discoveries", "--help")
        assert result.exit_code == 0
        assert "--limit" in _pulse_options("discoveries")

    def test_pulse_scans_help(self):
        result = _invoke_pulse("scans", "--help")
        assert result.exit_code == 0

    def test_pulse_report_help(self):
        result = _invoke_pulse("report", "--help")
        assert result.exit_code == 0
        assert "--date" in _pulse_options("report")

    def test_pulse_preflight_help(self):
        result = _invoke_pulse("preflight", "--help")
        assert result.exit_code == 0
