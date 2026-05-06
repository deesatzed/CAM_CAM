"""CLI UX surface tests for recently added user-facing commands/options."""

from __future__ import annotations

import asyncio
import inspect
import json
from copy import deepcopy

from typer.testing import CliRunner


def _command_map():
    from claw.cli import app

    mapping = {}
    for cmd in app.registered_commands:
        name = cmd.name or (cmd.callback.__name__ if cmd.callback else "")
        if cmd.callback is not None:
            mapping[name] = cmd.callback
    return mapping


def _group_map():
    from claw.cli import app

    mapping = {}
    for group in getattr(app, "registered_groups", []):
        info = group.typer_instance.info
        name = group.name
        if hasattr(name, "value"):
            name = name.value
        if not name:
            name = info.name
        mapping[name] = group.typer_instance
    return mapping


async def _seed_doctor_audit_db(
    db_path: str,
    *,
    flagged: bool,
    attributed_success: bool = False,
    attributed_failures: int = 0,
) -> None:
    from claw.core.config import DatabaseConfig
    from claw.core.models import Methodology, MethodologyUsageEntry, Project, Task
    from claw.db.engine import DatabaseEngine
    from claw.db.repository import Repository

    engine = DatabaseEngine(DatabaseConfig(db_path=db_path))
    await engine.connect()
    await engine.initialize_schema()
    repository = Repository(engine)

    project = Project(name="doctor-audit-project", repo_path="/tmp/doctor-audit")
    await repository.create_project(project)
    task = Task(project_id=project.id, title="doctor audit task", description="seed audit usage")
    await repository.create_task(task)

    method = Methodology(
        problem_description="Promotion-sensitive methodology",
        solution_code="apply_fix()",
        lifecycle_state="thriving" if flagged else "viable",
        scope="global" if flagged else "project",
        success_count=4 if flagged else 0,
        source_task_id=task.id,
    )
    await repository.save_methodology(method)
    if attributed_success:
        await repository.log_methodology_usage(
            MethodologyUsageEntry(
                task_id=task.id,
                methodology_id=method.id,
                project_id=project.id,
                stage="outcome_attributed",
                success=True,
                expectation_match_score=0.92,
                quality_score=0.88,
            )
        )
    for _ in range(attributed_failures):
        await repository.log_methodology_usage(
            MethodologyUsageEntry(
                task_id=task.id,
                methodology_id=method.id,
                project_id=project.id,
                stage="outcome_attributed",
                success=False,
                expectation_match_score=0.25,
                quality_score=0.20,
            )
        )
    await engine.close()


class TestCLIUXSurface:
    def test_cli_root_dir_points_to_repo(self):
        from claw.cli import ROOT_DIR

        assert (ROOT_DIR / "scripts" / "export_cam_knowledge_pack.py").exists()
        assert (ROOT_DIR / "apps" / "embedding_forge" / "benchmark_regression.py").exists()

    def test_ci_workflow_uploads_doctor_audit_report(self):
        from claw.cli import ROOT_DIR

        workflow = (ROOT_DIR / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        assert "python -m claw.cli doctor audit --limit 5 --json-out doctor_audit.json" in workflow
        assert "--fail-on-flags" not in workflow
        assert "name: doctor-audit-${{ matrix.python-version }}" in workflow

    def test_quickstart_command_registered(self):
        commands = _command_map()
        assert "quickstart" in commands

    def test_forge_export_command_registered(self):
        commands = _command_map()
        assert "forge-export" in commands

    def test_create_command_registered(self):
        commands = _command_map()
        assert "create" in commands

    def test_preflight_command_registered(self):
        commands = _command_map()
        assert "preflight" in commands

    def test_chat_command_registered(self):
        commands = _command_map()
        assert "chat" in commands

    def test_ideate_command_registered(self):
        commands = _command_map()
        assert "ideate" in commands

    def test_mine_report_command_registered(self):
        commands = _command_map()
        assert "mine-report" in commands

    def test_assimilation_report_command_registered(self):
        commands = _command_map()
        assert "assimilation-report" in commands

    def test_assimilation_delta_command_registered(self):
        commands = _command_map()
        assert "assimilation-delta" in commands

    def test_reassess_command_registered(self):
        commands = _command_map()
        assert "reassess" in commands

    def test_keycheck_command_registered(self):
        commands = _command_map()
        assert "keycheck" in commands

    def test_doctor_expectations_command_registered(self):
        groups = _group_map()
        doctor_names = {
            cmd.name or (cmd.callback.__name__ if cmd.callback else "")
            for cmd in groups["doctor"].registered_commands
        }
        assert "expectations" in doctor_names

    def test_grouped_workflow_namespaces_registered(self):
        groups = _group_map()
        assert "learn" in groups
        assert "task" in groups
        assert "forge" in groups
        assert "doctor" in groups
        assert "kb" in groups

    def test_grouped_namespace_commands_exist(self):
        groups = _group_map()

        learn_names = {
            cmd.name or (cmd.callback.__name__ if cmd.callback else "")
            for cmd in groups["learn"].registered_commands
        }
        assert {"report", "delta", "reassess", "synergies", "usage"} <= learn_names

        task_names = {
            cmd.name or (cmd.callback.__name__ if cmd.callback else "")
            for cmd in groups["task"].registered_commands
        }
        assert {"add", "quickstart", "runbook", "results"} <= task_names

        forge_names = {
            cmd.name or (cmd.callback.__name__ if cmd.callback else "")
            for cmd in groups["forge"].registered_commands
        }
        assert {"export", "benchmark"} <= forge_names

        doctor_names = {
            cmd.name or (cmd.callback.__name__ if cmd.callback else "")
            for cmd in groups["doctor"].registered_commands
        }
        assert {"keycheck", "status", "expectations", "audit"} <= doctor_names

        kb_names = {
            cmd.name or (cmd.callback.__name__ if cmd.callback else "")
            for cmd in groups["kb"].registered_commands
        }
        assert {"search", "capability", "patterns", "domains", "synergies"} <= kb_names

    def test_benchmark_command_registered(self):
        commands = _command_map()
        assert "benchmark" in commands

    def test_validate_command_registered(self):
        commands = _command_map()
        assert "validate" in commands

    def test_forge_benchmark_command_registered(self):
        commands = _command_map()
        assert "forge-benchmark" in commands

    def test_runbook_command_registered(self):
        commands = _command_map()
        assert "runbook" in commands

    def test_enhance_has_dry_run_option(self):
        commands = _command_map()
        enhance_cb = commands["enhance"]
        sig = inspect.signature(enhance_cb)
        assert "dry_run" in sig.parameters

    def test_mine_has_time_guardrail_option(self):
        commands = _command_map()
        mine_cb = commands["mine"]
        sig = inspect.signature(mine_cb)
        assert "max_minutes" in sig.parameters
        assert "skip_known" in sig.parameters
        assert "force_rescan" in sig.parameters
        assert "changed_only" in sig.parameters
        assert "live_keycheck" in sig.parameters

    def test_create_has_repo_mode_and_time_guardrail(self):
        commands = _command_map()
        cb = commands["create"]
        sig = inspect.signature(cb)
        assert "repo_mode" in sig.parameters
        assert "answer" in sig.parameters
        assert "preflight_file" in sig.parameters
        assert "preflight" in sig.parameters
        assert "auto_preflight" in sig.parameters
        assert "preflight_live" in sig.parameters
        assert "accept_preflight_defaults" in sig.parameters
        assert "namespace_safe_retry" in sig.parameters
        assert "max_minutes" in sig.parameters

    def test_chat_guides_mine_request(self):
        from claw.cli import app

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["chat"],
            input=(
                "I want to mine the folder ./tests/fixtures/embedding_forge\n"
                "\n"
                "cam\n"
                "y\n"
                "y\n"
                "4\n"
                "3\n"
                "n\n"
                "n\n"
                "exit\n"
            ),
        )

        assert result.exit_code == 0
        assert "Purpose: type `cam` to improve CAM itself" in result.output
        assert "Suggested command" in result.output
        assert ".venv/bin/cam mine ./tests/fixtures/embedding_forge" in result.output
        assert "--scan-only" in result.output
        assert "--changed-only" in result.output

    def test_resolve_operator_path_recovers_trailing_space_match(self, tmp_path, monkeypatch):
        from claw import cli

        real_dir = tmp_path / "repoTST "
        real_dir.mkdir()
        monkeypatch.chdir(tmp_path)

        resolved = cli._resolve_operator_path("repoTST")

        assert resolved == real_dir.resolve()

    def test_ideate_has_focus_promote_and_time_guardrail(self):
        commands = _command_map()
        cb = commands["ideate"]
        sig = inspect.signature(cb)
        assert "focus" in sig.parameters
        assert "promote" in sig.parameters
        assert "target_repo" in sig.parameters
        assert "max_minutes" in sig.parameters

    def test_benchmark_has_spec_file_and_time_guardrail(self):
        commands = _command_map()
        cb = commands["validate"]
        sig = inspect.signature(cb)
        assert "spec_file" in sig.parameters
        assert "max_minutes" in sig.parameters

    def test_benchmark_has_time_guardrail(self):
        commands = _command_map()
        cb = commands["benchmark"]
        sig = inspect.signature(cb)
        assert "max_minutes" in sig.parameters

    def test_add_goal_has_step_and_check_options(self):
        commands = _command_map()
        add_goal_cb = commands["add-goal"]
        sig = inspect.signature(add_goal_cb)
        assert "step" in sig.parameters
        assert "check" in sig.parameters

    def test_quickstart_has_preview_and_execute_options(self):
        commands = _command_map()
        quickstart_cb = commands["quickstart"]
        sig = inspect.signature(quickstart_cb)
        assert "preview" in sig.parameters
        assert "execute" in sig.parameters

    def test_forge_export_has_time_guardrail_option(self):
        commands = _command_map()
        cb = commands["forge-export"]
        sig = inspect.signature(cb)
        assert "max_minutes" in sig.parameters

    def test_forge_benchmark_has_time_guardrail_option(self):
        commands = _command_map()
        cb = commands["forge-benchmark"]
        sig = inspect.signature(cb)
        assert "max_minutes" in sig.parameters

    def test_keycheck_has_for_command_option(self):
        commands = _command_map()
        cb = commands["keycheck"]
        sig = inspect.signature(cb)
        assert "for_command" in sig.parameters
        assert "live" in sig.parameters

    def test_doctor_audit_has_json_and_fail_options(self):
        groups = _group_map()
        doctor_commands = {
            (cmd.name or (cmd.callback.__name__ if cmd.callback else "")): cmd.callback
            for cmd in groups["doctor"].registered_commands
            if cmd.callback is not None
        }
        cb = doctor_commands["audit"]
        sig = inspect.signature(cb)
        assert "json_out" in sig.parameters
        assert "fail_on_flags" in sig.parameters

    def test_display_task_status_marks_failed_pending_as_retry_ready(self):
        from claw.cli import _display_task_status

        assert _display_task_status("PENDING", "FAILURE") == "[yellow]RETRY_READY[/yellow]"
        assert _display_task_status("PENDING", "-") == "[yellow]PENDING[/yellow]"

    def test_doctor_audit_writes_json_payload(self, monkeypatch, tmp_path, claw_config):
        from claw.cli import app
        import claw.core.config as config_module

        db_path = tmp_path / "audit.db"
        out_path = tmp_path / "doctor_audit.json"
        asyncio.run(_seed_doctor_audit_db(str(db_path), flagged=False))

        cfg = deepcopy(claw_config)
        cfg.database.db_path = str(db_path)
        monkeypatch.setattr(config_module, "load_config", lambda config_path=None: cfg)

        runner = CliRunner()
        result = runner.invoke(app, ["doctor", "audit", "--json-out", str(out_path)])

        assert result.exit_code == 0
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        assert payload["summary"]["total_reviewed"] == 0
        assert payload["summary"]["flagged_total"] == 0
        assert payload["flagged"] == []
        assert payload["limit"] == 10
        assert payload["expectation_threshold"] == 0.65

    def test_doctor_audit_fail_on_flags_exits_nonzero(self, monkeypatch, tmp_path, claw_config):
        from claw.cli import app
        import claw.core.config as config_module

        db_path = tmp_path / "audit_flagged.db"
        out_path = tmp_path / "doctor_audit_flagged.json"
        asyncio.run(_seed_doctor_audit_db(str(db_path), flagged=True))

        cfg = deepcopy(claw_config)
        cfg.database.db_path = str(db_path)
        monkeypatch.setattr(config_module, "load_config", lambda config_path=None: cfg)

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "doctor",
                "audit",
                "--json-out",
                str(out_path),
                "--fail-on-flags",
            ],
        )

        assert result.exit_code == 1
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        assert payload["summary"]["total_reviewed"] == 1
        assert payload["summary"]["flagged_total"] == 1
        assert payload["summary"]["demotion_candidate_total"] == 0
        assert payload["flagged"][0]["evidence_source"] == "legacy"
        assert "legacy_evidence" in payload["flagged"][0]["flags"]

    def test_doctor_audit_fail_on_flags_allows_attributed_high_trust(self, monkeypatch, tmp_path, claw_config):
        from claw.cli import app
        import claw.core.config as config_module

        db_path = tmp_path / "audit_healthy.db"
        out_path = tmp_path / "doctor_audit_healthy.json"
        asyncio.run(_seed_doctor_audit_db(str(db_path), flagged=True, attributed_success=True))

        cfg = deepcopy(claw_config)
        cfg.database.db_path = str(db_path)
        monkeypatch.setattr(config_module, "load_config", lambda config_path=None: cfg)

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "doctor",
                "audit",
                "--json-out",
                str(out_path),
                "--fail-on-flags",
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        assert payload["summary"]["total_reviewed"] == 1
        assert payload["summary"]["attribution_backed_total"] == 1
        assert payload["summary"]["flagged_total"] == 0
        assert payload["flagged"] == []

    def test_doctor_audit_marks_demotion_candidate_for_repeated_attributed_failures(
        self, monkeypatch, tmp_path, claw_config
    ):
        from claw.cli import app
        import claw.core.config as config_module

        db_path = tmp_path / "audit_demotion.db"
        out_path = tmp_path / "doctor_audit_demotion.json"
        asyncio.run(
            _seed_doctor_audit_db(
                str(db_path),
                flagged=True,
                attributed_failures=2,
            )
        )

        cfg = deepcopy(claw_config)
        cfg.database.db_path = str(db_path)
        monkeypatch.setattr(config_module, "load_config", lambda config_path=None: cfg)

        runner = CliRunner()
        result = runner.invoke(app, ["doctor", "audit", "--json-out", str(out_path)])

        assert result.exit_code == 0
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        assert payload["summary"]["demotion_candidate_total"] == 1
        assert "demotion_candidate" in payload["flagged"][0]["flags"]
