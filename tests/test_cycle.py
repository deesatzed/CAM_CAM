"""Tests for CLAW cycle orchestration."""

from pathlib import Path

import pytest

from claw.core.models import (
    ActionTemplate,
    AgentMode,
    ContextBrief,
    Methodology,
    Project,
    Task,
    TaskContext,
    TaskOutcome,
    TaskStatus,
    VerificationResult,
)
from claw.cycle import MicroClaw


class TestMicroClaw:
    async def test_act_fails_when_agent_makes_no_workspace_changes(self, claw_context, sample_project, sample_task, tmp_path):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        workspace = tmp_path / "repo"
        workspace.mkdir()
        (workspace / "app.py").write_text("print('before')\n", encoding="utf-8")

        class NoChangeAgent:
            workspace_dir = str(workspace)

            async def run(self, task_ctx):
                return TaskOutcome(
                    approach_summary="Claimed update without touching files",
                    tests_passed=True,
                    files_changed=["fake.py"],
                    raw_output="updated fake.py",
                )

        ctx.agents["codex"] = NoChangeAgent()

        micro = MicroClaw(ctx, sample_project.id)
        task_ctx = TaskContext(task=sample_task)
        agent_id, _, outcome = await micro.act(("codex", task_ctx))

        assert agent_id == "codex"
        assert outcome.failure_reason == "no_workspace_changes"
        assert outcome.tests_passed is False
        assert outcome.files_changed == []
        assert outcome.diff == ""

    async def test_act_uses_real_workspace_changes(self, claw_context, sample_project, sample_task, tmp_path):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        workspace = tmp_path / "repo"
        workspace.mkdir()
        target = workspace / "app.py"
        target.write_text("print('before')\n", encoding="utf-8")

        class WriteAgent:
            workspace_dir = str(workspace)

            async def run(self, task_ctx):
                target.write_text("print('after')\n", encoding="utf-8")
                return TaskOutcome(
                    approach_summary="Updated app.py",
                    tests_passed=True,
                    files_changed=[],
                    raw_output="done",
                )

        ctx.agents["codex"] = WriteAgent()

        micro = MicroClaw(ctx, sample_project.id)
        task_ctx = TaskContext(task=sample_task)
        agent_id, _, outcome = await micro.act(("codex", task_ctx))

        assert agent_id == "codex"
        assert outcome.failure_reason is None
        assert outcome.files_changed == ["app.py"]
        assert "app.py" in outcome.diff

    async def test_act_refuses_agent_mode_without_workspace_write(
        self,
        claw_context,
        sample_project,
        sample_task,
        tmp_path,
    ):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        workspace = tmp_path / "repo"
        workspace.mkdir()

        class ReadOnlyAgent:
            mode = AgentMode.OPENROUTER
            workspace_dir = str(workspace)

            def can_modify_workspace(self):
                return False

            def can_use_internal_workspace_executor(self):
                return False

            async def run(self, task_ctx):
                raise AssertionError("run() should not be called for non-writable agents")

        ctx.agents["codex"] = ReadOnlyAgent()

        micro = MicroClaw(ctx, sample_project.id)
        task_ctx = TaskContext(task=sample_task)
        agent_id, _, outcome = await micro.act(("codex", task_ctx))

        assert agent_id == "codex"
        assert outcome.failure_reason == "agent_cannot_modify_workspace"
        assert "structured-output-capable mode" in (outcome.failure_detail or "")

    async def test_act_applies_structured_file_ops_from_readonly_agent(
        self,
        claw_context,
        sample_project,
        sample_task,
        tmp_path,
    ):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        workspace = tmp_path / "repo"
        workspace.mkdir()

        class StructuredAgent:
            mode = AgentMode.OPENROUTER
            workspace_dir = str(workspace)

            def can_modify_workspace(self):
                return False

            def can_use_internal_workspace_executor(self):
                return True

            async def run(self, task_ctx):
                return TaskOutcome(
                    approach_summary="Emit structured file operations",
                    tests_passed=False,
                    raw_output=(
                        "I created the requested app.\n\n```json\n"
                        '{"summary":"create app","file_operations":[{"path":"app.py","action":"write","content":"print(\\"hello\\")\\n"}]}'
                        "\n```"
                    ),
                )

        ctx.agents["codex"] = StructuredAgent()

        micro = MicroClaw(ctx, sample_project.id)
        task_ctx = TaskContext(task=sample_task)
        agent_id, _, outcome = await micro.act(("codex", task_ctx))

        assert agent_id == "codex"
        assert outcome.failure_reason is None
        assert outcome.files_changed == ["app.py"]
        assert (workspace / "app.py").read_text(encoding="utf-8") == 'print("hello")\n'

    async def test_act_applies_balanced_json_object_with_trailing_prose(
        self,
        claw_context,
        sample_project,
        sample_task,
        tmp_path,
    ):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        workspace = tmp_path / "repo"
        workspace.mkdir()

        class StructuredAgent:
            mode = AgentMode.OPENROUTER
            workspace_dir = str(workspace)

            def can_modify_workspace(self):
                return False

            def can_use_internal_workspace_executor(self):
                return True

            async def run(self, task_ctx):
                return TaskOutcome(
                    approach_summary="Emit structured file operations with commentary",
                    tests_passed=False,
                    raw_output=(
                        '{'
                        '"summary":"create app",'
                        '"file_operations":[{"path":"app.py","action":"write","content":"print(\\"hello\\")\\n"}]'
                        '}'
                        "\n\nThis satisfies the requested app."
                    ),
                )

        ctx.agents["codex"] = StructuredAgent()

        micro = MicroClaw(ctx, sample_project.id)
        task_ctx = TaskContext(task=sample_task)
        agent_id, _, outcome = await micro.act(("codex", task_ctx))

        assert agent_id == "codex"
        assert outcome.failure_reason is None
        assert outcome.files_changed == ["app.py"]
        assert (workspace / "app.py").read_text(encoding="utf-8") == 'print("hello")\n'

    async def test_act_applies_structured_ops_with_alternate_keys_and_actions(
        self,
        claw_context,
        sample_project,
        sample_task,
        tmp_path,
    ):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        workspace = tmp_path / "repo"
        workspace.mkdir()

        class StructuredAgent:
            mode = AgentMode.OPENROUTER
            workspace_dir = str(workspace)

            def can_modify_workspace(self):
                return False

            def can_use_internal_workspace_executor(self):
                return True

            async def run(self, task_ctx):
                return TaskOutcome(
                    approach_summary="Emit alternate operation schema",
                    tests_passed=False,
                    raw_output=(
                        '{'
                        '"summary":"create files",'
                        '"operations":['
                        '{"file_path":"index.html","operation":"create","text":"<h1>Hello</h1>\\n"},'
                        '{"path":"index.html","operation":"append","content":"<p>World</p>\\n"}'
                        "]"
                        "}"
                    ),
                )

        ctx.agents["codex"] = StructuredAgent()

        micro = MicroClaw(ctx, sample_project.id)
        task_ctx = TaskContext(task=sample_task)
        agent_id, _, outcome = await micro.act(("codex", task_ctx))

        assert agent_id == "codex"
        assert outcome.failure_reason is None
        assert outcome.files_changed == ["index.html"]
        assert (workspace / "index.html").read_text(encoding="utf-8") == "<h1>Hello</h1>\n<p>World</p>\n"

    async def test_act_applies_python_literal_structured_payload(
        self,
        claw_context,
        sample_project,
        sample_task,
        tmp_path,
    ):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        workspace = tmp_path / "repo"
        workspace.mkdir()

        class StructuredAgent:
            mode = AgentMode.OPENROUTER
            workspace_dir = str(workspace)

            def can_modify_workspace(self):
                return False

            def can_use_internal_workspace_executor(self):
                return True

            async def run(self, task_ctx):
                return TaskOutcome(
                    approach_summary="Emit python-literal payload",
                    tests_passed=False,
                    raw_output=(
                        "{'summary': 'ok', 'file_operations': "
                        "[{'path': 'README.md', 'action': 'write', 'content': '# Demo\\n'}]}"
                    ),
                )

        ctx.agents["codex"] = StructuredAgent()

        micro = MicroClaw(ctx, sample_project.id)
        task_ctx = TaskContext(task=sample_task)
        agent_id, _, outcome = await micro.act(("codex", task_ctx))

        assert agent_id == "codex"
        assert outcome.failure_reason is None
        assert outcome.files_changed == ["README.md"]
        assert (workspace / "README.md").read_text(encoding="utf-8") == "# Demo\n"

    async def test_grab_returns_task(self, claw_context, sample_project, sample_task):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        micro = MicroClaw(ctx, sample_project.id)
        grabbed = await micro.grab()
        assert grabbed is not None
        assert grabbed.title == sample_task.title

    async def test_grab_returns_none_when_empty(self, claw_context, sample_project):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)

        micro = MicroClaw(ctx, sample_project.id)
        grabbed = await micro.grab()
        assert grabbed is None

    async def test_evaluate_logs_retrieved_methodology_usage(self, claw_context, sample_project, sample_task):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        meth = Methodology(
            problem_description="JWT auth validation pattern",
            solution_code="validate_jwt()",
            problem_embedding=[0.1] * 384,
        )
        await ctx.repository.save_methodology(meth)

        class Result:
            def __init__(self, methodology, combined_score):
                self.methodology = methodology
                self.combined_score = combined_score

        class SemanticStub:
            def __init__(self, repository):
                self.repository = repository

            async def find_similar_with_signals(self, query, limit=3, language=None, tags=None):
                return [Result(meth, 0.81)], {"retrieval_confidence": 0.81, "conflicts": []}

            async def record_retrieval(self, methodology_id):
                await self.repository.update_methodology_retrieval(methodology_id)

        ctx.semantic_memory = SemanticStub(ctx.repository)

        micro = MicroClaw(ctx, sample_project.id)
        task_ctx = await micro.evaluate(sample_task)

        assert task_ctx.task.id == sample_task.id
        assert micro._current_context_brief is not None
        assert micro._current_context_brief.retrieved_methodology_ids == [meth.id]
        usage_rows = await ctx.repository.get_methodology_usage_for_task(sample_task.id)
        assert len(usage_rows) == 1
        assert usage_rows[0].stage == "retrieved_presented"
        assert usage_rows[0].methodology_id == meth.id

    async def test_learn_attributes_outcome_only_to_inferred_used_methodologies(
        self,
        claw_context,
        sample_project,
        sample_task,
    ):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        used = Methodology(
            problem_description="JWT auth validation pattern with token parsing",
            solution_code="validate_jwt()",
            problem_embedding=[0.2] * 384,
        )
        unused = Methodology(
            problem_description="frontend color theme palette generator",
            solution_code="theme()",
            problem_embedding=[0.3] * 384,
        )
        await ctx.repository.save_methodology(used)
        await ctx.repository.save_methodology(unused)

        class SemanticStub:
            def __init__(self, repository):
                self.repository = repository

            async def record_outcome(self, methodology_id, success, retrieval_relevance=0.5, source_db_path=None):
                await self.repository.update_methodology_outcome(methodology_id, success)

        ctx.semantic_memory = SemanticStub(ctx.repository)

        micro = MicroClaw(ctx, sample_project.id)
        micro._current_context_brief = ContextBrief(
            task=sample_task,
            past_solutions=[used, unused],
            retrieved_methodology_ids=[used.id, unused.id],
        )

        outcome = TaskOutcome(
            approach_summary="Implemented JWT auth validation with token parsing and auth checks.",
            raw_output="Added validate_jwt token parsing auth path",
            tests_passed=True,
            files_changed=["src/auth.py"],
            diff="+def validate_jwt(token): pass",
        )
        verification = VerificationResult(approved=True, quality_score=0.9, expectation_match_score=0.8)

        await micro.learn(("claude", TaskContext(task=sample_task), outcome, verification))

        used_reloaded = await ctx.repository.get_methodology(used.id)
        unused_reloaded = await ctx.repository.get_methodology(unused.id)
        assert used_reloaded is not None and used_reloaded.success_count == 1
        assert unused_reloaded is not None and unused_reloaded.success_count == 0

        usage_rows = await ctx.repository.get_methodology_usage_for_task(sample_task.id)
        stages_for_used = [row.stage for row in usage_rows if row.methodology_id == used.id]
        assert "used_in_outcome" in stages_for_used
        assert "outcome_attributed" in stages_for_used
        assert all(row.methodology_id != unused.id for row in usage_rows if row.stage == "outcome_attributed")

    async def test_learn_demotes_attributed_methodology_when_expectation_fit_is_low(
        self,
        claw_context,
        sample_project,
        sample_task,
    ):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        used = Methodology(
            problem_description="JWT auth validation pattern with token parsing",
            solution_code="validate_jwt()",
            problem_embedding=[0.2] * 384,
        )
        await ctx.repository.save_methodology(used)

        class SemanticStub:
            def __init__(self, repository):
                self.repository = repository

            async def record_outcome(self, methodology_id, success, retrieval_relevance=0.5, source_db_path=None):
                await self.repository.update_methodology_outcome(methodology_id, success)

        ctx.semantic_memory = SemanticStub(ctx.repository)

        micro = MicroClaw(ctx, sample_project.id)
        micro._current_context_brief = ContextBrief(
            task=sample_task,
            past_solutions=[used],
            retrieved_methodology_ids=[used.id],
        )

        outcome = TaskOutcome(
            approach_summary="Implemented JWT auth validation with token parsing and auth checks.",
            raw_output="Added validate_jwt token parsing auth path",
            tests_passed=True,
            files_changed=["src/auth.py"],
            diff="+def validate_jwt(token): pass",
        )
        verification = VerificationResult(approved=True, quality_score=0.7, expectation_match_score=0.2)

        await micro.learn(("claude", TaskContext(task=sample_task), outcome, verification))

        used_reloaded = await ctx.repository.get_methodology(used.id)
        assert used_reloaded is not None
        assert used_reloaded.success_count == 0
        assert used_reloaded.failure_count == 1

        usage_rows = await ctx.repository.get_methodology_usage_for_task(sample_task.id)
        attributed = [row for row in usage_rows if row.methodology_id == used.id and row.stage == "outcome_attributed"]
        assert len(attributed) == 1
        assert attributed[0].success is False

    async def test_grab_respects_priority(self, claw_context, sample_project):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)

        low = Task(project_id=sample_project.id, title="Low", description="low pri", priority=1)
        high = Task(project_id=sample_project.id, title="High", description="high pri", priority=10)
        await ctx.repository.create_task(low)
        await ctx.repository.create_task(high)

        micro = MicroClaw(ctx, sample_project.id)
        grabbed = await micro.grab()
        assert grabbed.title == "High"

    async def test_evaluate_builds_context(self, claw_context, sample_project, sample_task):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        micro = MicroClaw(ctx, sample_project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)
        assert task_ctx.task.id == sample_task.id
        assert isinstance(task_ctx.forbidden_approaches, list)

    async def test_decide_routes_to_available_agent(self, claw_context, sample_project, sample_task):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        micro = MicroClaw(ctx, sample_project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)
        agent_id, decided_ctx = await micro.decide(task_ctx)

        # No agents in test context, but decide handles gracefully
        # The important thing is it doesn't crash
        assert isinstance(agent_id, str)

    async def test_full_cycle_status_tracking(self, claw_context, sample_project, sample_task):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        micro = MicroClaw(ctx, sample_project.id)

        # Grab sets nothing yet
        grabbed = await micro.grab()
        assert grabbed is not None

        # Evaluate moves to EVALUATING
        task_ctx = await micro.evaluate(grabbed)
        got = await ctx.repository.get_task(sample_task.id)
        assert got.status == TaskStatus.EVALUATING

        # Decide moves to DISPATCHED
        agent_id, decided_ctx = await micro.decide(task_ctx)
        got = await ctx.repository.get_task(sample_task.id)
        assert got.status == TaskStatus.DISPATCHED

    async def test_evaluate_loads_action_template_into_context(
        self, claw_context, sample_project
    ):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        template = ActionTemplate(
            title="Auth patch template",
            problem_pattern="jwt auth regression",
            execution_steps=["pytest -q tests/test_auth.py"],
            acceptance_checks=["pytest -q tests/test_auth.py"],
            rollback_steps=["git restore src/auth.py"],
            preconditions=["pytest available in venv"],
        )
        await ctx.repository.create_action_template(template)
        task = Task(
            project_id=sample_project.id,
            title="Fix JWT bug",
            description="Repair login flow and verify",
            action_template_id=template.id,
        )
        await ctx.repository.create_task(task)

        micro = MicroClaw(ctx, sample_project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)

        assert task_ctx.action_template is not None
        assert task_ctx.action_template.id == template.id
        assert any("Runbook execute:" in hint for hint in task_ctx.hints)
        assert any("Runbook verify:" in hint for hint in task_ctx.hints)

    async def test_learn_updates_action_template_feedback(
        self, claw_context, sample_project
    ):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        template = ActionTemplate(
            title="Retry-safe template",
            problem_pattern="intermittent test failure",
            execution_steps=["pytest -q"],
            acceptance_checks=["pytest -q"],
            confidence=0.5,
        )
        await ctx.repository.create_action_template(template)
        task = Task(
            project_id=sample_project.id,
            title="Stabilize flaky tests",
            description="Stabilize and verify",
            action_template_id=template.id,
        )
        await ctx.repository.create_task(task)

        micro = MicroClaw(ctx, sample_project.id)
        verified = (
            "claude",
            TaskContext(task=task),
            TaskOutcome(
                approach_summary="Stabilized flaky test with deterministic fixture",
                tests_passed=True,
                files_changed=["tests/test_flaky.py"],
            ),
            VerificationResult(approved=True, quality_score=0.95),
        )
        await micro.learn(verified)

        updated_template = await ctx.repository.get_action_template(template.id)
        assert updated_template is not None
        assert updated_template.success_count == 1
        assert updated_template.confidence > 0.5
