from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from claw.security.policy_tools import get_security_lane_status, run_critical_slot_policy_checks


@pytest.mark.asyncio
async def test_policy_tools_uses_repo_local_semgrep_config_and_docker_runner(tmp_path: Path):
    workspace = tmp_path
    (workspace / "security").mkdir()
    (workspace / "security" / "semgrep.yml").write_text("rules: []\n", encoding="utf-8")
    (workspace / "scripts").mkdir()
    runner = workspace / "scripts" / "camseq_semgrep.sh"
    runner.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    runner.chmod(0o755)
    target = workspace / "app.py"
    target.write_text("print('hi')\n", encoding="utf-8")

    async def fake_run(args: list[str]):
        if args[0].endswith("camseq_semgrep.sh"):
            return 0, '{"results":[]}', ""
        return 0, "", ""

    with patch("claw.security.policy_tools.shutil.which") as which, patch(
        "claw.security.policy_tools._run_command",
        side_effect=fake_run,
    ):
        which.side_effect = lambda name: "/usr/bin/docker" if name == "docker" else None
        result = await run_critical_slot_policy_checks(str(workspace), [str(target)])

    assert result["semgrep"]["status"] == "pass"


@pytest.mark.asyncio
async def test_policy_tools_defers_codeql_when_not_installed(tmp_path: Path):
    workspace = tmp_path
    (workspace / "security").mkdir()
    (workspace / "security" / "semgrep.yml").write_text("rules: []\n", encoding="utf-8")

    with patch.dict("os.environ", {}, clear=True), patch(
        "claw.security.policy_tools.shutil.which", return_value=None
    ):
        result = await run_critical_slot_policy_checks(str(workspace), [])

    assert result["codeql"]["status"] == "deferred"
    assert "deferred" in result["codeql"]["details"][0]


@pytest.mark.asyncio
async def test_policy_tools_skips_codeql_when_mode_off(tmp_path: Path):
    workspace = tmp_path
    (workspace / "security").mkdir()
    (workspace / "security" / "semgrep.yml").write_text("rules: []\n", encoding="utf-8")

    with patch.dict("os.environ", {"CLAW_CODEQL_MODE": "off"}, clear=True), patch(
        "claw.security.policy_tools.shutil.which", return_value=None
    ):
        result = await run_critical_slot_policy_checks(str(workspace), [])

    assert result["codeql"]["status"] == "skipped"
    assert "disabled" in result["codeql"]["details"][0]


@pytest.mark.asyncio
async def test_policy_tools_marks_required_codeql_unavailable_when_missing(tmp_path: Path):
    workspace = tmp_path
    (workspace / "security").mkdir()
    (workspace / "security" / "semgrep.yml").write_text("rules: []\n", encoding="utf-8")

    with patch.dict("os.environ", {"CLAW_CODEQL_MODE": "required"}, clear=True), patch(
        "claw.security.policy_tools.shutil.which", return_value=None
    ):
        result = await run_critical_slot_policy_checks(str(workspace), [])

    assert result["codeql"]["status"] == "unavailable"
    assert "required" in result["codeql"]["details"][0]


@pytest.mark.asyncio
async def test_policy_tools_marks_required_codeql_config_unavailable(tmp_path: Path):
    workspace = tmp_path
    (workspace / "security").mkdir()
    (workspace / "security" / "semgrep.yml").write_text("rules: []\n", encoding="utf-8")

    with patch.dict("os.environ", {"CLAW_CODEQL_MODE": "required"}, clear=True), patch(
        "claw.security.policy_tools.shutil.which",
        side_effect=lambda name: "/usr/bin/codeql" if name == "codeql" else None,
    ):
        result = await run_critical_slot_policy_checks(str(workspace), [])

    assert result["codeql"]["status"] == "unavailable"
    assert "CLAW_CODEQL_DATABASE" in result["codeql"]["details"][0]


@pytest.mark.asyncio
async def test_policy_tools_runs_required_codeql_and_parses_sarif(tmp_path: Path):
    workspace = tmp_path
    (workspace / "security").mkdir()
    (workspace / "security" / "semgrep.yml").write_text("rules: []\n", encoding="utf-8")
    target = workspace / "app.py"
    target.write_text("import subprocess\nsubprocess.run('x', shell=True)\n", encoding="utf-8")
    database = workspace / "codeql-db"
    queries = workspace / "security.qls"
    database.mkdir()
    queries.write_text("- query: test\n", encoding="utf-8")
    commands: list[list[str]] = []

    async def fake_run(args: list[str]):
        commands.append(args)
        if args[0] == "semgrep":
            return 0, '{"results":[]}', ""
        if args[0] == "codeql":
            output_arg = next(arg for arg in args if arg.startswith("--output="))
            Path(output_arg.removeprefix("--output=")).write_text(
                """
{
  "version": "2.1.0",
  "runs": [
    {
      "tool": {
        "driver": {
          "name": "CodeQL",
          "rules": [
            {
              "id": "py/shell-command-constructed-from-input",
              "shortDescription": {"text": "Shell command constructed from input"}
            }
          ]
        }
      },
      "results": [
        {
          "ruleId": "py/shell-command-constructed-from-input",
          "level": "error",
          "message": {"text": "Tainted command reaches shell execution"},
          "locations": [
            {
              "physicalLocation": {
                "artifactLocation": {"uri": "app.py"},
                "region": {"startLine": 2}
              }
            }
          ]
        }
      ]
    }
  ]
}
""".strip(),
                encoding="utf-8",
            )
            return 0, "", ""
        raise AssertionError(f"unexpected command: {args}")

    env = {
        "CLAW_CODEQL_MODE": "required",
        "CLAW_CODEQL_DATABASE": str(database),
        "CLAW_CODEQL_QUERIES": str(queries),
    }
    with patch.dict("os.environ", env, clear=True), patch(
        "claw.security.policy_tools.shutil.which",
        side_effect=lambda name: f"/usr/bin/{name}" if name in {"semgrep", "codeql"} else None,
    ), patch("claw.security.policy_tools._run_command", side_effect=fake_run):
        result = await run_critical_slot_policy_checks(str(workspace), ["app.py"])

    codeql_commands = [command for command in commands if command[0] == "codeql"]
    assert codeql_commands == [
        [
            "codeql",
            "database",
            "analyze",
            str(database),
            str(queries),
            "--format=sarif-latest",
            f"--output={workspace / '.claw_codeql_results.sarif'}",
        ]
    ]
    assert result["codeql"]["status"] == "fail"
    assert result["codeql"]["findings"] == [
        {
            "tool": "codeql",
            "severity": "high",
            "rule_id": "py/shell-command-constructed-from-input",
            "message": "Tainted command reaches shell execution",
            "path": "app.py",
            "line": 2,
        }
    ]


def test_security_lane_status_reports_configured_modes(tmp_path: Path):
    workspace = tmp_path
    (workspace / "security").mkdir()
    semgrep_config = workspace / "security" / "semgrep.yml"
    semgrep_config.write_text("rules: []\n", encoding="utf-8")
    (workspace / "scripts").mkdir()
    runner = workspace / "scripts" / "camseq_semgrep.sh"
    runner.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    runner.chmod(0o755)

    env = {
        "CLAW_CODEQL_MODE": "required",
        "CLAW_CODEQL_DATABASE": "/tmp/codeql-db",
        "CLAW_CODEQL_QUERIES": "/tmp/security.qls",
        "CLAW_SECURITY_USE_DOCKER": "1",
    }
    with patch.dict("os.environ", env, clear=True), patch(
        "claw.security.policy_tools.shutil.which",
        side_effect=lambda name: f"/usr/bin/{name}" if name in {"docker", "codeql"} else None,
    ):
        status = get_security_lane_status(str(workspace))

    assert status["semgrep"]["config_available"] is True
    assert status["semgrep"]["docker_runner_available"] is True
    assert status["semgrep"]["use_docker"] is True
    assert status["codeql"]["mode"] == "required"
    assert status["codeql"]["cli_available"] is True
    assert status["codeql"]["database_configured"] is True
    assert status["codeql"]["queries_configured"] is True
