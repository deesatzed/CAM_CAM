from __future__ import annotations

import json

import pytest
import typer

import claw.cli._monolith as _monolith


class TestPreflightAnswerHandling:
    def test_apply_answers_to_preflight_resolves_matching_questions_and_blockers(self):
        from claw import cli

        report = {
            "clarifying_questions": [
                {"priority": "must", "question": "What exact acceptance checks or demo outcomes will count as success?"},
                {"priority": "must", "question": "Are there domain constraints such as privacy, compliance, security, or auditability requirements?"},
            ],
            "hard_blockers": [
                "Domain constraints may require explicit compliance, privacy, or audit decisions before execution."
            ],
            "assumptions": [],
        }

        updated = cli._apply_answers_to_preflight(
            report,
            [
                "Acceptance checks: pytest -q and python -m app.cli --help",
                "Compliance: no PHI or PII, standard security only",
            ],
        )

        assert updated["clarifying_questions"] == []
        assert updated["hard_blockers"] == []
        assert len(updated["answered_questions"]) == 2
        assert updated["operator_answers"][0].startswith("Acceptance checks:")

    def test_answer_covers_question_matches_delivery_surface(self):
        from claw import cli

        assert cli._answer_covers_question(
            "What is the required delivery surface: CLI, web app, API, library, or mixed?",
            ["Delivery surface: web app with a small API"],
        ) is True

    def test_merge_preflight_answers_reuses_prior_artifact_answers(self):
        from claw import cli

        merged = cli._merge_preflight_answers(
            {"operator_answers": ["Acceptance checks: pytest -q", "Delivery surface: web app"]},
            ["Delivery surface: web app", "Transfer scope: UX and workflows"],
        )

        assert merged == [
            "Acceptance checks: pytest -q",
            "Delivery surface: web app",
            "Transfer scope: UX and workflows",
        ]

    def test_load_preflight_artifact_reads_json(self, tmp_path):
        from claw import cli

        artifact = tmp_path / "demo-preflight.json"
        artifact.write_text(json.dumps({"operator_answers": ["Acceptance checks: pytest -q"]}), encoding="utf-8")

        loaded = cli._load_preflight_artifact(str(artifact))

        assert loaded is not None
        assert loaded["operator_answers"] == ["Acceptance checks: pytest -q"]
        assert loaded["artifact_path"] == str(artifact)

    @pytest.mark.asyncio
    async def test_create_async_execute_unblocks_when_answers_cover_must_questions(self, tmp_path, monkeypatch):
        from claw import cli

        async def fake_preflight_async(**kwargs):
            report = {
                "artifact_path": str(tmp_path / "data" / "preflights" / "demo.json"),
                "hard_blockers": [],
                "clarifying_questions": [],
                "operator_answers": list(kwargs.get("answers", [])),
                "answered_questions": [
                    {"priority": "must", "question": "What exact acceptance checks or demo outcomes will count as success?"},
                    {"priority": "must", "question": "What is the required delivery surface: CLI, web app, API, library, or mixed?"},
                ],
                "recommended_mode": "proceed_now",
                "complexity": "medium",
                "task_kind": "greenfield_app_creation",
            }
            return report, tmp_path / "data" / "preflights" / "demo.json"

        async def fake_quickstart_async(**kwargs):
            return None

        monkeypatch.setattr(_monolith, "_run_preflight_async", fake_preflight_async)
        monkeypatch.setattr(_monolith, "_quickstart_async", fake_quickstart_async)

        await cli._create_async(
            repo_path=tmp_path / "demo",
            request="Build a risky app",
            repo_mode="new",
            title="Risky app",
            priority="high",
            task_type="architecture",
            agent=None,
            spec_items=[],
            execution_steps=[],
            acceptance_checks=[],
            answers=[
                "Acceptance checks: pytest -q and python -m app.cli --help",
                "Delivery surface: web app",
            ],
            preflight_file=None,
            preflight=True,
            auto_preflight=True,
            preflight_live=False,
            accept_preflight_defaults=False,
            preview=False,
            execute=True,
            config_path=None,
        )

    @pytest.mark.asyncio
    async def test_create_async_execute_still_blocks_when_must_questions_remain(self, tmp_path, monkeypatch):
        from claw import cli

        async def fake_preflight_async(**kwargs):
            report = {
                "artifact_path": str(tmp_path / "data" / "preflights" / "demo.json"),
                "hard_blockers": [],
                "clarifying_questions": [
                    {"priority": "must", "question": "Which parts of the source repo must transfer?"}
                ],
                "operator_answers": list(kwargs.get("answers", [])),
                "answered_questions": [],
                "recommended_mode": "proceed_after_answers",
                "complexity": "high",
                "task_kind": "pattern_transfer",
            }
            return report, tmp_path / "data" / "preflights" / "demo.json"

        monkeypatch.setattr(_monolith, "_run_preflight_async", fake_preflight_async)

        with pytest.raises(typer.Exit) as exc:
            await cli._create_async(
                repo_path=tmp_path / "demo",
                request="Build a risky app",
                repo_mode="new",
                title="Risky app",
                priority="high",
                task_type="architecture",
                agent=None,
                spec_items=[],
            execution_steps=[],
            acceptance_checks=[],
            answers=["Delivery surface: web app"],
            preflight_file=None,
            preflight=True,
            auto_preflight=True,
            preflight_live=False,
            accept_preflight_defaults=False,
                preview=False,
                execute=True,
                config_path=None,
            )

        assert exc.value.exit_code == 2

    @pytest.mark.asyncio
    async def test_quickstart_async_rolls_back_new_source_namespace(self, tmp_path, monkeypatch):
        from claw import cli
        from claw.core.models import TaskOutcome, VerificationResult

        repo_path = tmp_path / "demo"
        (repo_path / "src" / "claw").mkdir(parents=True)
        (repo_path / "src" / "claw" / "__init__.py").write_text("", encoding="utf-8")
        (repo_path / "tests").mkdir()

        created_tasks: list[object] = []

        class FakeRepository:
            async def get_project_by_name(self, _name):
                return None

            async def create_project(self, project):
                return None

            async def create_task(self, task):
                created_tasks.append(task)

        class FakeAgent:
            def can_modify_workspace(self):
                return True

        class FakeCtx:
            def __init__(self):
                self.repository = FakeRepository()
                self.agents = {"claude": FakeAgent()}

            async def close(self):
                return None

        class FakeMicroClaw:
            def __init__(self, ctx, project_id):
                self.ctx = ctx
                self.project_id = project_id

            async def evaluate(self, task):
                return task

            async def decide(self, task_ctx):
                return ("claude", task_ctx)

            async def act(self, decision):
                (repo_path / "cam").mkdir()
                (repo_path / "cam" / "cli.py").write_text("print('bad drift')\n", encoding="utf-8")
                (repo_path / "tests" / "test_atomic_operations.py").write_text("def test_bad():\n    assert True\n", encoding="utf-8")
                outcome = TaskOutcome(
                    approach_summary="bad quickstart drift",
                    tests_passed=True,
                    files_changed=["cam/cli.py", "tests/test_atomic_operations.py"],
                    raw_output="created bad files",
                )
                return ("claude", decision[1], outcome)

            async def verify(self, acted):
                return (
                    acted[0],
                    acted[1],
                    acted[2],
                    VerificationResult(approved=True, violations=[], recommendations=[], quality_score=0.95),
                )

            async def _act_with_correction(self, decision):
                acted = await self.act(decision)
                return await self.verify(acted)

            async def learn(self, verified):
                return None

        async def fake_create(*args, **kwargs):
            return FakeCtx()

        monkeypatch.setattr("claw.core.factory.ClawFactory.create", fake_create)
        monkeypatch.setattr("claw.cycle.MicroClaw", FakeMicroClaw)
        monkeypatch.setattr(cli, "_display_task_result", lambda cycle_result: None)

        await cli._quickstart_async(
            repo_path=repo_path,
            title="Guard quickstart",
            description="Avoid namespace drift",
            priority="high",
            task_type="architecture",
            agent="claude",
            execution_steps=[],
            acceptance_checks=["pytest -q"],
            preview=False,
            execute=True,
            config_path=None,
        )

        assert not (repo_path / "cam").exists()
        assert not (repo_path / "tests" / "test_atomic_operations.py").exists()

        baseline = cli._snapshot_repo_state(repo_path)
        assert "src/claw/__init__.py" in baseline

    @pytest.mark.asyncio
    async def test_quickstart_fixed_mode_namespace_safe_retry(self, tmp_path, monkeypatch):
        from claw import cli
        from claw.core.models import TaskOutcome, VerificationResult

        repo_path = tmp_path / "demo"
        (repo_path / "src" / "claw").mkdir(parents=True)
        (repo_path / "src" / "claw" / "__init__.py").write_text("", encoding="utf-8")
        (repo_path / "tests").mkdir()

        created_tasks: list[object] = []
        attempts = {"count": 0}

        class FakeRepository:
            async def get_project_by_name(self, _name):
                return None

            async def create_project(self, project):
                return None

            async def create_task(self, task):
                created_tasks.append(task)

        class FakeAgent:
            def can_modify_workspace(self):
                return True

        class FakeCtx:
            def __init__(self):
                self.repository = FakeRepository()
                self.agents = {"claude": FakeAgent()}

            async def close(self):
                return None

        class FakeMicroClaw:
            def __init__(self, ctx, project_id):
                self.ctx = ctx
                self.project_id = project_id

            async def evaluate(self, task):
                return task

            async def decide(self, task_ctx):
                return ("claude", task_ctx)

            async def act(self, decision):
                attempts["count"] += 1
                if attempts["count"] == 1:
                    (repo_path / "cam").mkdir()
                    (repo_path / "cam" / "cli.py").write_text("print('bad drift')\n", encoding="utf-8")
                    outcome = TaskOutcome(
                        approach_summary="bad namespace drift",
                        tests_passed=True,
                        files_changed=["cam/cli.py"],
                        raw_output="created cam namespace",
                    )
                else:
                    (repo_path / "src" / "claw" / "retry_safe.py").write_text("VALUE = 1\n", encoding="utf-8")
                    outcome = TaskOutcome(
                        approach_summary="namespace-safe retry",
                        tests_passed=True,
                        files_changed=["src/claw/retry_safe.py"],
                        raw_output="updated existing namespace only",
                    )
                return ("claude", decision[1], outcome)

            async def verify(self, acted):
                return (
                    acted[0],
                    acted[1],
                    acted[2],
                    VerificationResult(approved=True, violations=[], recommendations=[], quality_score=0.95),
                )

            async def _act_with_correction(self, decision):
                acted = await self.act(decision)
                return await self.verify(acted)

            async def learn(self, verified):
                return None

        async def fake_create(*args, **kwargs):
            return FakeCtx()

        monkeypatch.setattr("claw.core.factory.ClawFactory.create", fake_create)
        monkeypatch.setattr("claw.cycle.MicroClaw", FakeMicroClaw)
        monkeypatch.setattr(cli, "_display_task_result", lambda cycle_result: None)

        await cli._quickstart_async(
            repo_path=repo_path,
            title="Guard quickstart",
            description="Avoid namespace drift",
            priority="high",
            task_type="architecture",
            agent="claude",
            execution_steps=[],
            acceptance_checks=["pytest -q"],
            repo_mode="fixed",
            namespace_safe_retry=True,
            preview=False,
            execute=True,
            config_path=None,
        )

        assert attempts["count"] == 2
        assert len(created_tasks) == 2
        assert "(namespace-safe retry)" in created_tasks[1].title
        assert not (repo_path / "cam").exists()
        assert (repo_path / "src" / "claw" / "retry_safe.py").exists()
        # P0 fix: retry task description must START with explicit namespace constraint
        retry_desc = created_tasks[1].description
        assert retry_desc.startswith("CRITICAL NAMESPACE CONSTRAINT (retry):")
        assert "['claw']" in retry_desc or "claw" in retry_desc
        assert "Allowed top-level source namespaces:" in retry_desc
        # P0 fix: retry acceptance checks must include namespace guard
        retry_checks = created_tasks[1].acceptance_checks
        assert any("No new top-level namespaces beyond:" in c for c in retry_checks)
        assert "pytest -q" in retry_checks  # original check preserved

    def test_quickstart_namespace_guard_skips_new_repo_baseline(self, tmp_path):
        from claw import cli
        from claw.core.models import TaskOutcome, VerificationResult

        repo_path = tmp_path / "newrepo"
        repo_path.mkdir()
        (repo_path / "app").mkdir()
        (repo_path / "app" / "cli.py").write_text("print('ok')\n", encoding="utf-8")

        outcome = TaskOutcome(
            approach_summary="new repo scaffold",
            tests_passed=True,
            files_changed=["app/cli.py"],
            raw_output="created app namespace",
        )
        verification = VerificationResult(approved=True, violations=[], recommendations=[], quality_score=0.9)
        updated_outcome, updated_verification, rolled_back = cli._enforce_quickstart_execution_guard(
            repo_path=repo_path,
            baseline_snapshot={},
            outcome=outcome,
            verification=verification,
        )

        assert rolled_back == []
        assert updated_outcome.failure_reason in (None, "")
        assert updated_verification.approved is True
        assert (repo_path / "app" / "cli.py").exists()

    @pytest.mark.asyncio
    async def test_run_preflight_async_reuses_prior_answers(self, tmp_path):
        from claw import cli

        report, _ = await cli._run_preflight_async(
            repo_path=tmp_path / "demo",
            request="Apply everything repo-A does to a related healthcare intake app",
            repo_mode="new",
            spec_items=[],
            acceptance_checks=[],
            answers=["Transfer scope: UX and workflows"],
            prior_report={
                "artifact_path": str(tmp_path / "prior.json"),
                "operator_answers": [
                    "Acceptance checks: pytest -q",
                    "Delivery surface: web app",
                    "Compliance: no PHI or PII, standard security only",
                ],
            },
            preferred_agent=None,
            config_path=None,
            live=False,
        )

        assert report["reused_preflight_artifact"] == str(tmp_path / "prior.json")
        assert "Acceptance checks: pytest -q" in report["operator_answers"]
        assert "Transfer scope: UX and workflows" in report["operator_answers"]
        assert all(item.get("priority") != "must" or "time ceiling" not in item.get("question", "").lower() for item in report["answered_questions"])
