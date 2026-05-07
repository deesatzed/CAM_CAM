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
