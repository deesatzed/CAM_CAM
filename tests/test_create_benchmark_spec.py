"""Tests for create-spec generation and benchmark validation helpers."""

from __future__ import annotations

import json
from pathlib import Path


class TestCreateBenchmarkSpecHelpers:
    def test_build_and_write_create_spec(self, tmp_path, monkeypatch):
        from claw import cli

        monkeypatch.setattr(cli, "ROOT_DIR", tmp_path)
        spec = cli._build_create_spec(
            repo_path=Path("/tmp/new-app"),
            request="Build a new repo for multimodal retrieval.",
            repo_mode="new",
            title="Build new retrieval repo",
            task_type="architecture",
            execution_steps=["uv init", "pytest -q"],
            acceptance_checks=["project boots", "tests pass"],
            spec_items=["Use Gemini embeddings", "Create a CLI"],
        )
        path = cli._write_create_spec(spec)

        assert path.exists()
        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["repo_mode"] == "new"
        assert "baseline_snapshot" in written
        assert written["validation"]["require_repo_exists"] is True
        assert written["benchmark"]["catastrophic_floor_pct"] == -35.0
        assert written["spec_items"][0] == "Use Gemini embeddings"
        assert written["expectation_contract"]["goal"] == "Build a new repo for multimodal retrieval."
        assert written["expectation_contract"]["expected_outcome"]

    def test_build_create_spec_seeds_runbook_when_missing(self, tmp_path):
        from claw import cli

        spec = cli._build_create_spec(
            repo_path=tmp_path / "new-app",
            request="Create a standalone CLI app for opportunity discovery.",
            repo_mode="new",
            title="Opportunity app",
            task_type="architecture",
            execution_steps=[],
            acceptance_checks=[],
            spec_items=["Must be standalone", "Must expose a CLI entrypoint"],
        )

        assert len(spec["execution_steps"]) >= 4
        assert len(spec["acceptance_checks"]) >= 4
        assert any("cam runtime" in item.lower() for item in spec["acceptance_checks"])
        assert any("cli" in item.lower() or "entrypoint" in item.lower() for item in spec["acceptance_checks"])
        assert any("return 0" in item.lower() for item in spec["execution_steps"])
        assert any("exit code 0" in item.lower() for item in spec["acceptance_checks"])

    def test_build_expectation_contract_adds_cli_exit_code_requirements(self):
        from claw import cli

        contract = cli._build_expectation_contract(
            request="Create a standalone CLI app.",
            repo_mode="new",
            task_type="architecture",
            spec_items=["Must expose python -m app.cli."],
            acceptance_checks=["python -m app.cli --help", "pytest -q"],
        )

        assert "CLI help and version return a zero exit code" in contract["expected_outcome"]

    def test_agent_supports_workspace_execution_only_for_writable_agent(self):
        from claw import cli

        class WritableAgent:
            def can_modify_workspace(self):
                return True

        class ReadOnlyAgent:
            def can_modify_workspace(self):
                return False

            def can_use_internal_workspace_executor(self):
                return False

        assert cli._agent_supports_workspace_execution(WritableAgent()) is True
        assert cli._agent_supports_workspace_execution(ReadOnlyAgent()) is False
        assert cli._agent_supports_workspace_execution(None) is False

    def test_build_foundation_expectation_report_flags_missing_builder(self):
        from claw import cli

        class ReadOnlyAgent:
            def can_modify_workspace(self):
                return False

            def can_use_internal_workspace_executor(self):
                return False

        class DummyCtx:
            agents = {"claude": ReadOnlyAgent()}
            miner = object()
            assimilation_engine = object()
            semantic_memory = object()
            repository = object()
            verifier = object()

        report = cli._build_foundation_expectation_report(DummyCtx())
        assert report["builder_execution_available"] is False
        assert report["readonly_agents"] == ["claude"]
        builder_truth = next(item for item in report["checks"] if item["name"] == "builder_truth")
        assert builder_truth["ok"] is False

    def test_build_foundation_expectation_report_flags_writable_builder(self):
        from claw import cli

        class ExecutableAgent:
            def can_modify_workspace(self):
                return False

            def can_use_internal_workspace_executor(self):
                return True

        class DummyCtx:
            agents = {"codex": ExecutableAgent()}
            miner = object()
            assimilation_engine = object()
            semantic_memory = object()
            repository = object()
            verifier = object()

        report = cli._build_foundation_expectation_report(DummyCtx())
        assert report["builder_execution_available"] is True
        assert report["writable_agents"] == ["codex"]
        builder_truth = next(item for item in report["checks"] if item["name"] == "builder_truth")
        assert builder_truth["ok"] is True

    def test_validate_create_spec_runs_acceptance_checks(self, tmp_path):
        from claw import cli

        repo_path = tmp_path / "app"
        repo_path.mkdir()
        (repo_path / "README.md").write_text("hello\n", encoding="utf-8")
        (repo_path / "app").mkdir()
        (repo_path / "app" / "cli.py").write_text("print('cli')\n", encoding="utf-8")

        spec = cli._build_create_spec(
            repo_path=repo_path,
            request="Create a standalone CLI tiny app.",
            repo_mode="new",
            title="Tiny app",
            task_type="architecture",
            execution_steps=[],
            acceptance_checks=["python -c \"print('ok')\""],
            spec_items=[],
        )
        (repo_path / "README.md").write_text("hello changed\n", encoding="utf-8")

        passed, summary = cli._validate_create_spec(spec, max_minutes=1)
        assert passed is True
        assert summary["checks_run"] == 1
        assert summary["checks"][0]["ok"] is True
        assert summary["expectation_assessment"]["score"] is not None
        assert summary["expectation_assessment"]["score"] >= 0.7

    def test_validate_create_spec_reports_failed_check(self, tmp_path):
        from claw import cli

        repo_path = tmp_path / "app"
        repo_path.mkdir()
        (repo_path / "README.md").write_text("hello\n", encoding="utf-8")

        spec = cli._build_create_spec(
            repo_path=repo_path,
            request="Create a tiny app.",
            repo_mode="new",
            title="Tiny app",
            task_type="architecture",
            execution_steps=[],
            acceptance_checks=["python -c \"import sys; sys.exit(3)\""],
            spec_items=[],
        )

        passed, summary = cli._validate_create_spec(spec, max_minutes=1)
        assert passed is False
        assert any("acceptance check failed" in item for item in summary["findings"])

    def test_validate_create_spec_treats_plain_english_checks_as_manual(self, tmp_path):
        from claw import cli

        repo_path = tmp_path / "app"
        repo_path.mkdir()
        (repo_path / "README.md").write_text("hello\n", encoding="utf-8")

        spec = cli._build_create_spec(
            repo_path=repo_path,
            request="Create a tiny app.",
            repo_mode="new",
            title="Tiny app",
            task_type="architecture",
            execution_steps=[],
            acceptance_checks=["CLI runs without crashing", "Reads JSONL knowledge pack"],
            spec_items=[],
        )
        (repo_path / "README.md").write_text("hello changed\n", encoding="utf-8")

        passed, summary = cli._validate_create_spec(spec, max_minutes=1)
        assert passed is True
        assert summary["checks_run"] == 0
        assert len(summary["manual_checks"]) == 2

    def test_validate_create_spec_executes_test_and_rg_commands(self, tmp_path):
        from claw import cli

        repo_path = tmp_path / "app"
        repo_path.mkdir()
        (repo_path / "README.md").write_text("hello modernizer\n", encoding="utf-8")

        spec = cli._build_create_spec(
            repo_path=repo_path,
            request="Create a tiny app.",
            repo_mode="new",
            title="Tiny app",
            task_type="architecture",
            execution_steps=[],
            acceptance_checks=["test -f README.md", "grep -q 'modernizer' README.md"],
            spec_items=[],
        )
        (repo_path / "README.md").write_text("hello modernizer changed\n", encoding="utf-8")

        passed, summary = cli._validate_create_spec(spec, max_minutes=1)
        assert passed is True
        assert summary["checks_run"] == 2
        assert summary["manual_checks"] == []

    def test_validate_create_spec_detects_unchanged_repo(self, tmp_path):
        from claw import cli

        repo_path = tmp_path / "app"
        repo_path.mkdir()
        (repo_path / "README.md").write_text("hello\n", encoding="utf-8")

        spec = cli._build_create_spec(
            repo_path=repo_path,
            request="Change the repo.",
            repo_mode="augment",
            title="Change repo",
            task_type="architecture",
            execution_steps=[],
            acceptance_checks=[],
            spec_items=[],
        )

        passed, summary = cli._validate_create_spec(spec, max_minutes=1)
        assert passed is False
        assert any("unchanged" in item for item in summary["findings"])

    def test_validate_create_spec_flags_cam_runtime_import_gap(self, tmp_path):
        from claw import cli

        repo_path = tmp_path / "app"
        repo_path.mkdir()
        (repo_path / "README.md").write_text("hello\n", encoding="utf-8")
        (repo_path / "main.py").write_text("from claw.cli import app\n", encoding="utf-8")

        spec = cli._build_create_spec(
            repo_path=repo_path,
            request="Create a standalone app.",
            repo_mode="new",
            title="Tiny app",
            task_type="architecture",
            execution_steps=[],
            acceptance_checks=[],
            spec_items=["Must be standalone"],
        )
        (repo_path / "README.md").write_text("hello changed\n", encoding="utf-8")

        passed, summary = cli._validate_create_spec(spec, max_minutes=1)
        assert passed is False
        assert any("expectation mismatch" in item for item in summary["findings"])
        assert any("CAM runtime" in item for item in summary["expectation_assessment"]["unmet"])

    def test_validate_create_spec_flags_new_source_namespace_in_fixed_mode(self, tmp_path):
        from claw import cli

        repo_path = tmp_path / "app"
        (repo_path / "src" / "claw").mkdir(parents=True)
        (repo_path / "src" / "claw" / "__init__.py").write_text("", encoding="utf-8")

        spec = cli._build_create_spec(
            repo_path=repo_path,
            request="Repair the existing repo behavior.",
            repo_mode="fixed",
            title="Repair repo",
            task_type="architecture",
            execution_steps=[],
            acceptance_checks=[],
            spec_items=[],
        )

        (repo_path / "src" / "cam").mkdir(parents=True)
        (repo_path / "src" / "cam" / "__init__.py").write_text("", encoding="utf-8")

        passed, summary = cli._validate_create_spec(spec, max_minutes=1)
        assert passed is False
        assert any("expectation mismatch" in item for item in summary["findings"])
        assert any("New source namespaces introduced" in item for item in summary["expectation_assessment"]["unmet"])

    def test_validate_benchmark_against_spec(self):
        from claw import cli

        summary = {
            "best": {
                "hit_rate_lift_pct": -2.5,
            }
        }
        spec = {
            "benchmark": {
                "catastrophic_floor_pct": -10.0,
                "require_non_negative_lift": True,
            }
        }

        passed, findings = cli._validate_benchmark_against_spec(summary, spec)
        assert passed is False
        assert any("non-negative" in item for item in findings)
