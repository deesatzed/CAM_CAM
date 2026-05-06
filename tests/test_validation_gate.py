"""Tests for the CAM Self-Enhancement Validation Gate.

Tests each gate independently using real temporary directories with
real Python source files. No mocks.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import textwrap
from pathlib import Path

import pytest

from claw.validation_gate import (
    DiffSummary,
    GateResult,
    PytestSuiteResults,
    ValidationConfig,
    ValidationReport,
    _gate_cli_smoke,
    _gate_config_compatibility,
    _gate_db_compatibility,
    _gate_diff_summary,
    _gate_import_smoke,
    _gate_syntax_check,
    run_all_gates,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LIVE_DIR = Path(__file__).resolve().parents[1]


def _make_copy_dir(tmp_path: Path) -> Path:
    """Create a minimal copy directory structure that mirrors real CAM."""
    copy_dir = tmp_path / "cam-copy"
    copy_dir.mkdir()
    (copy_dir / "src" / "claw").mkdir(parents=True)
    (copy_dir / "tests").mkdir()

    # Minimal pyproject.toml
    (copy_dir / "pyproject.toml").write_text(textwrap.dedent("""\
        [project]
        name = "claw"
        version = "0.1.0"
        requires-python = ">=3.12"
        dependencies = []

        [tool.setuptools]
        package-dir = {"claw" = "src/claw"}

        [tool.setuptools.packages.find]
        where = ["src"]
        include = ["claw*"]
    """))

    # Copy the real source so imports work
    real_src = LIVE_DIR / "src" / "claw"
    if real_src.exists():
        shutil.copytree(real_src, copy_dir / "src" / "claw", dirs_exist_ok=True)

    # Copy claw.toml and .env
    for filename in ["claw.toml", ".env"]:
        src = LIVE_DIR / filename
        if src.exists():
            shutil.copy2(src, copy_dir / filename)

    return copy_dir


def _make_minimal_copy_dir(tmp_path: Path) -> Path:
    """Create a copy dir with just enough structure, no real source."""
    copy_dir = tmp_path / "cam-minimal"
    copy_dir.mkdir()
    (copy_dir / "src" / "claw").mkdir(parents=True)
    (copy_dir / "tests").mkdir()
    (copy_dir / "pyproject.toml").write_text("[project]\nname='claw'\nversion='0.1.0'\n")
    (copy_dir / "src" / "claw" / "__init__.py").write_text('__version__ = "0.1.0"\n')
    return copy_dir


# ---------------------------------------------------------------------------
# Gate 1: Syntax Check
# ---------------------------------------------------------------------------

class TestGateSyntaxCheck:
    """Test the Python syntax checking gate."""

    def test_valid_python_passes(self, tmp_path: Path) -> None:
        copy_dir = _make_minimal_copy_dir(tmp_path)
        (copy_dir / "src" / "claw" / "valid.py").write_text("x = 1\ny = x + 2\n")
        (copy_dir / "src" / "claw" / "also_valid.py").write_text(
            "def foo(a: int) -> str:\n    return str(a)\n"
        )
        config = ValidationConfig(copy_dir=copy_dir, live_dir=LIVE_DIR)
        result = _gate_syntax_check(config)
        assert result.passed is True
        assert result.gate_number == 1

    def test_syntax_error_fails(self, tmp_path: Path) -> None:
        copy_dir = _make_minimal_copy_dir(tmp_path)
        (copy_dir / "src" / "claw" / "broken.py").write_text("def foo(\n")
        config = ValidationConfig(copy_dir=copy_dir, live_dir=LIVE_DIR)
        result = _gate_syntax_check(config)
        assert result.passed is False
        assert "syntax error" in result.message.lower()
        assert "broken.py" in (result.detail or "")

    def test_mixed_valid_and_invalid(self, tmp_path: Path) -> None:
        copy_dir = _make_minimal_copy_dir(tmp_path)
        (copy_dir / "src" / "claw" / "good.py").write_text("x = 1\n")
        (copy_dir / "src" / "claw" / "bad.py").write_text("class Foo(\n")
        config = ValidationConfig(copy_dir=copy_dir, live_dir=LIVE_DIR)
        result = _gate_syntax_check(config)
        assert result.passed is False
        assert "1 file(s)" in result.message

    def test_empty_src_passes(self, tmp_path: Path) -> None:
        copy_dir = _make_minimal_copy_dir(tmp_path)
        # __init__.py is already there, and it's valid
        config = ValidationConfig(copy_dir=copy_dir, live_dir=LIVE_DIR)
        result = _gate_syntax_check(config)
        assert result.passed is True

    def test_real_cam_source_passes(self, tmp_path: Path) -> None:
        """Verify the real CAM source has no syntax errors."""
        copy_dir = _make_copy_dir(tmp_path)
        config = ValidationConfig(copy_dir=copy_dir, live_dir=LIVE_DIR)
        result = _gate_syntax_check(config)
        assert result.passed is True, f"Real source has syntax errors: {result.detail}"


# ---------------------------------------------------------------------------
# Gate 2: Config Compatibility
# ---------------------------------------------------------------------------

class TestGateConfigCompatibility:
    """Test config loading gate."""

    def test_with_real_source_and_config(self, tmp_path: Path) -> None:
        copy_dir = _make_copy_dir(tmp_path)
        config = ValidationConfig(copy_dir=copy_dir, live_dir=LIVE_DIR)
        result = _gate_config_compatibility(config)
        assert result.passed is True
        assert "agents" in result.message.lower()

    def test_copies_missing_toml_from_live(self, tmp_path: Path) -> None:
        copy_dir = _make_copy_dir(tmp_path)
        # Remove claw.toml from copy
        toml_path = copy_dir / "claw.toml"
        if toml_path.exists():
            toml_path.unlink()
        config = ValidationConfig(copy_dir=copy_dir, live_dir=LIVE_DIR)
        result = _gate_config_compatibility(config)
        # Should still pass because it copies from live
        assert result.passed is True
        assert any("Copied claw.toml" in w for w in result.warnings)

    def test_missing_toml_everywhere_fails(self, tmp_path: Path) -> None:
        copy_dir = _make_minimal_copy_dir(tmp_path)
        fake_live = tmp_path / "fake_live"
        fake_live.mkdir()
        config = ValidationConfig(copy_dir=copy_dir, live_dir=fake_live)
        result = _gate_config_compatibility(config)
        assert result.passed is False
        assert "no claw.toml found" in result.message.lower()


# ---------------------------------------------------------------------------
# Gate 3: Import Smoke Test
# ---------------------------------------------------------------------------

class TestGateImportSmoke:
    """Test module import gate."""

    def test_real_source_imports(self, tmp_path: Path) -> None:
        copy_dir = _make_copy_dir(tmp_path)
        config = ValidationConfig(copy_dir=copy_dir, live_dir=LIVE_DIR)
        result = _gate_import_smoke(config)
        assert result.passed is True
        assert "modules imported" in result.message.lower()

    def test_broken_import_fails(self, tmp_path: Path) -> None:
        copy_dir = _make_minimal_copy_dir(tmp_path)
        # Add a module that imports something nonexistent
        (copy_dir / "src" / "claw" / "broken_import.py").write_text(
            "from claw.nonexistent_xyz import Foo\n"
        )
        config = ValidationConfig(copy_dir=copy_dir, live_dir=LIVE_DIR)
        result = _gate_import_smoke(config)
        # This should fail because broken_import.py can't import
        assert result.passed is False
        assert "failed to import" in result.message.lower()


# ---------------------------------------------------------------------------
# Gate 4: DB Schema Compatibility
# ---------------------------------------------------------------------------

class TestGateDBCompatibility:
    """Test DB schema compatibility gate."""

    @pytest.mark.asyncio
    async def test_real_db_compatible(self, tmp_path: Path) -> None:
        copy_dir = _make_copy_dir(tmp_path)
        config = ValidationConfig(copy_dir=copy_dir, live_dir=LIVE_DIR)
        result = await _gate_db_compatibility(config)
        live_db = LIVE_DIR / "data" / "claw.db"
        if live_db.exists():
            assert result.passed is True
            assert "tables" in result.message.lower()
        else:
            # Skipped because no live DB
            assert result.passed is True
            assert "skipping" in result.message.lower()

    @pytest.mark.asyncio
    async def test_no_live_db_skips(self, tmp_path: Path) -> None:
        copy_dir = _make_minimal_copy_dir(tmp_path)
        fake_live = tmp_path / "fake_live"
        fake_live.mkdir()
        (fake_live / "data").mkdir()
        # No claw.db file
        config = ValidationConfig(copy_dir=copy_dir, live_dir=fake_live)
        result = await _gate_db_compatibility(config)
        assert result.passed is True
        assert "skipping" in result.message.lower() or "no live db" in result.message.lower()

    @pytest.mark.asyncio
    async def test_cleanup_removes_temp_db(self, tmp_path: Path) -> None:
        copy_dir = _make_copy_dir(tmp_path)
        config = ValidationConfig(copy_dir=copy_dir, live_dir=LIVE_DIR)
        await _gate_db_compatibility(config)
        # Temp DB directory should be cleaned up
        assert not (copy_dir / "_validation_db_test").exists()


# ---------------------------------------------------------------------------
# Gate 5: CLI Smoke Test
# ---------------------------------------------------------------------------

class TestGateCLISmoke:
    """Test CLI smoke test gate."""

    def test_real_source_cli_works(self, tmp_path: Path) -> None:
        copy_dir = _make_copy_dir(tmp_path)
        config = ValidationConfig(copy_dir=copy_dir, live_dir=LIVE_DIR)
        result = _gate_cli_smoke(config)
        assert result.passed is True
        assert "help" in result.message.lower() or "cli" in result.message.lower()


# ---------------------------------------------------------------------------
# Gate 7: Diff Summary
# ---------------------------------------------------------------------------

class TestGateDiffSummary:
    """Test diff summary gate."""

    def test_identical_copy(self, tmp_path: Path) -> None:
        copy_dir = _make_copy_dir(tmp_path)
        config = ValidationConfig(copy_dir=copy_dir, live_dir=LIVE_DIR)
        result, diff = _gate_diff_summary(config)
        assert result.passed is True  # always passes (informational)
        assert diff.files_unchanged > 0
        assert len(diff.files_modified) == 0
        assert len(diff.files_added) == 0
        assert len(diff.files_removed) == 0

    def test_modified_file_detected(self, tmp_path: Path) -> None:
        copy_dir = _make_copy_dir(tmp_path)
        # Modify a file
        init_file = copy_dir / "src" / "claw" / "__init__.py"
        init_file.write_text('"""CLAW — Modified."""\n\n__version__ = "0.2.0"\n')
        config = ValidationConfig(copy_dir=copy_dir, live_dir=LIVE_DIR)
        result, diff = _gate_diff_summary(config)
        assert len(diff.files_modified) >= 1
        modified_names = [f for f, _, _ in diff.files_modified]
        assert any("__init__" in n for n in modified_names)

    def test_added_file_detected(self, tmp_path: Path) -> None:
        copy_dir = _make_copy_dir(tmp_path)
        # Add a new file
        (copy_dir / "src" / "claw" / "new_feature.py").write_text("# New feature\n")
        config = ValidationConfig(copy_dir=copy_dir, live_dir=LIVE_DIR)
        result, diff = _gate_diff_summary(config)
        assert len(diff.files_added) >= 1
        assert any("new_feature" in f for f in diff.files_added)

    def test_removed_file_detected(self, tmp_path: Path) -> None:
        copy_dir = _make_copy_dir(tmp_path)
        # Remove a file that exists in live
        budget_file = copy_dir / "src" / "claw" / "budget.py"
        if budget_file.exists():
            budget_file.unlink()
            config = ValidationConfig(copy_dir=copy_dir, live_dir=LIVE_DIR)
            result, diff = _gate_diff_summary(config)
            assert len(diff.files_removed) >= 1
            assert any("budget" in f for f in diff.files_removed)
            assert len(result.warnings) >= 1

    def test_new_test_files_detected(self, tmp_path: Path) -> None:
        copy_dir = _make_copy_dir(tmp_path)
        # Copy tests too
        if (LIVE_DIR / "tests").exists():
            shutil.copytree(LIVE_DIR / "tests", copy_dir / "tests", dirs_exist_ok=True)
        # Add a new test file
        (copy_dir / "tests" / "test_new_enhancement.py").write_text(
            "def test_placeholder():\n    assert True\n"
        )
        config = ValidationConfig(copy_dir=copy_dir, live_dir=LIVE_DIR)
        result, diff = _gate_diff_summary(config)
        assert len(diff.new_test_files) >= 1


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class TestDataModels:
    """Test data model properties."""

    def test_test_suite_results_pass_rate(self) -> None:
        tr = PytestSuiteResults(total=100, passed=95, failed=3, errors=1, skipped=1)
        assert tr.pass_rate == 95.0

    def test_test_suite_results_pass_rate_zero_total(self) -> None:
        tr = PytestSuiteResults()
        assert tr.pass_rate == 0.0

    def test_validation_report_summary(self) -> None:
        report = ValidationReport(
            passed=True,
            gate_results=[
                GateResult(gate_number=1, gate_name="Syntax", passed=True, message="OK"),
                GateResult(gate_number=2, gate_name="Config", passed=True, message="OK"),
            ],
        )
        summary = report.summary()
        assert "PASS" in summary
        assert "ALL GATES PASSED" in summary

    def test_validation_report_failure_summary(self) -> None:
        report = ValidationReport(
            passed=False,
            failed_gate="Config Compatibility",
            gate_results=[
                GateResult(gate_number=1, gate_name="Syntax", passed=True, message="OK"),
                GateResult(
                    gate_number=2, gate_name="Config Compatibility",
                    passed=False, message="Failed",
                ),
            ],
        )
        summary = report.summary()
        assert "FAIL" in summary
        assert "Config Compatibility" in summary

    def test_gate_result_with_warnings(self) -> None:
        gr = GateResult(
            gate_number=1, gate_name="Test",
            passed=True, message="OK",
            warnings=["Something to note"],
        )
        assert len(gr.warnings) == 1

    def test_diff_summary_defaults(self) -> None:
        ds = DiffSummary()
        assert ds.files_added == []
        assert ds.files_removed == []
        assert ds.files_modified == []
        assert ds.files_unchanged == 0
        assert ds.new_test_files == []


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class TestRunAllGates:
    """Test the full orchestrator."""

    @pytest.mark.asyncio
    async def test_missing_structure_fails(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        config = ValidationConfig(copy_dir=empty_dir, live_dir=LIVE_DIR)
        report = await run_all_gates(config)
        assert report.passed is False
        assert "pre-flight" in (report.failed_gate or "").lower()

    @pytest.mark.asyncio
    async def test_missing_pyproject_fails(self, tmp_path: Path) -> None:
        bad_dir = tmp_path / "bad"
        bad_dir.mkdir()
        (bad_dir / "src" / "claw").mkdir(parents=True)
        (bad_dir / "tests").mkdir()
        # No pyproject.toml
        config = ValidationConfig(copy_dir=bad_dir, live_dir=LIVE_DIR)
        report = await run_all_gates(config)
        assert report.passed is False

    @pytest.mark.asyncio
    async def test_syntax_error_stops_pipeline(self, tmp_path: Path) -> None:
        copy_dir = _make_copy_dir(tmp_path)
        # Inject a syntax error
        (copy_dir / "src" / "claw" / "syntax_bomb.py").write_text("def broken(:\n")
        config = ValidationConfig(copy_dir=copy_dir, live_dir=LIVE_DIR)
        report = await run_all_gates(config)
        assert report.passed is False
        assert report.failed_gate == "Python Syntax Check"
        # Only gate 1 should have run
        assert len(report.gate_results) == 1

    @pytest.mark.asyncio
    async def test_clean_copy_passes_early_gates(self, tmp_path: Path) -> None:
        """A clean copy of the real source should pass gates 1-5 at minimum."""
        copy_dir = _make_copy_dir(tmp_path)
        config = ValidationConfig(
            copy_dir=copy_dir,
            live_dir=LIVE_DIR,
            baseline_test_count=0,  # don't run full test suite threshold
        )

        # Run just the fast gates by checking individual results
        g1 = _gate_syntax_check(config)
        assert g1.passed, f"Gate 1 failed: {g1.detail}"

        g2 = _gate_config_compatibility(config)
        assert g2.passed, f"Gate 2 failed: {g2.detail}"

        g3 = _gate_import_smoke(config)
        assert g3.passed, f"Gate 3 failed: {g3.detail}"

        g4 = await _gate_db_compatibility(config)
        assert g4.passed, f"Gate 4 failed: {g4.detail}"

        g5 = _gate_cli_smoke(config)
        assert g5.passed, f"Gate 5 failed: {g5.detail}"


# ---------------------------------------------------------------------------
# ValidationConfig
# ---------------------------------------------------------------------------

class TestValidationConfig:
    """Test configuration defaults and overrides."""

    def test_defaults(self) -> None:
        config = ValidationConfig(copy_dir=Path("/tmp/test"))
        assert config.live_dir == Path("/Volumes/WS4TB/a_aSatzClaw/multiclaw")
        assert config.baseline_test_count == 1966
        assert config.allowed_new_failures == 0
        assert config.skip_venv is True

    def test_overrides(self) -> None:
        config = ValidationConfig(
            copy_dir=Path("/tmp/test"),
            live_dir=Path("/other/live"),
            baseline_test_count=2000,
            allowed_new_failures=5,
        )
        assert config.live_dir == Path("/other/live")
        assert config.baseline_test_count == 2000
        assert config.allowed_new_failures == 5
