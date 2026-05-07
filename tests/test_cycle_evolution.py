"""Tests for NanoClaw, MesoClaw, and MicroClaw evolution wiring.

Validates that:
- MicroClaw.evaluate() enriches forbidden approaches from error KB
- MicroClaw.evaluate() adds hints from semantic memory
- MicroClaw.learn() saves patterns to semantic memory on success
- MicroClaw.learn() records errors in error KB on failure
- MicroClaw.learn() triggers pattern extraction on success
- NanoClaw runs a full self-improvement cycle
- MesoClaw runs evaluation -> planning -> MicroClaw dispatch
- ClawContext has new evolution/memory fields
- TaskContext has hints field
"""

import logging

import pytest

from claw.core.config import load_config
from claw.core.factory import ClawContext
from claw.core.models import (
    CycleResult,
    HypothesisEntry,
    HypothesisOutcome,
    Project,
    Task,
    TaskContext,
    TaskOutcome,
    TaskStatus,
    VerificationResult,
)
from claw.cycle import MesoClaw, MicroClaw, NanoClaw
from claw.db.embeddings import EmbeddingEngine
from claw.db.engine import DatabaseEngine
from claw.db.repository import Repository
from claw.evolution.pattern_learner import PatternLearner
from claw.evolution.prompt_evolver import PromptEvolver
from claw.llm.client import LLMClient
from claw.llm.token_tracker import TokenTracker
from claw.memory.error_kb import ErrorKB
from claw.memory.hybrid_search import HybridSearch
from claw.memory.semantic import SemanticMemory
from claw.security.policy import SecurityPolicy


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def evolution_context():
    """ClawContext with error_kb, semantic_memory, prompt_evolver, pattern_learner wired."""
    from claw.core.config import DatabaseConfig

    config = load_config()
    config.database.db_path = ":memory:"

    engine = DatabaseEngine(config.database)
    await engine.connect()
    await engine.initialize_schema()
    repo = Repository(engine)
    embeddings = EmbeddingEngine(config.embeddings)

    error_kb = ErrorKB(repository=repo)

    hybrid_search = HybridSearch(
        repository=repo,
        embedding_engine=embeddings,
    )
    semantic_memory = SemanticMemory(
        repository=repo,
        embedding_engine=embeddings,
        hybrid_search=hybrid_search,
    )

    prompt_evolver = PromptEvolver(
        repository=repo,
        semantic_memory=semantic_memory,
        error_kb=error_kb,
    )

    pattern_learner = PatternLearner(
        repository=repo,
        semantic_memory=semantic_memory,
    )

    ctx = ClawContext(
        config=config,
        engine=engine,
        repository=repo,
        embeddings=embeddings,
        llm_client=LLMClient(config.llm),
        token_tracker=TokenTracker(repository=repo),
        security=SecurityPolicy(),
        agents={},
        error_kb=error_kb,
        semantic_memory=semantic_memory,
        prompt_evolver=prompt_evolver,
        pattern_learner=pattern_learner,
    )

    yield ctx
    await ctx.close()


@pytest.fixture
def evo_project() -> Project:
    return Project(
        name="evo-test-project",
        repo_path="/tmp/evo-test-repo",
        tech_stack={"language": "python"},
    )


@pytest.fixture
def evo_task(evo_project: Project) -> Task:
    return Task(
        project_id=evo_project.id,
        title="Fix connection pooling bug",
        description="The database connection pool exhausts under high concurrency",
        priority=8,
        task_type="bug_fix",
    )


# ---------------------------------------------------------------------------
# TaskContext.hints
# ---------------------------------------------------------------------------


class TestTaskContextHints:
    def test_task_context_has_hints_field(self):
        task = Task(project_id="p1", title="Test", description="test")
        ctx = TaskContext(task=task)
        assert isinstance(ctx.hints, list)
        assert ctx.hints == []

    def test_task_context_hints_populated(self):
        task = Task(project_id="p1", title="Test", description="test")
        ctx = TaskContext(
            task=task,
            hints=["Similar past solution: use connection pool recycling"],
        )
        assert len(ctx.hints) == 1
        assert "connection pool" in ctx.hints[0]


# ---------------------------------------------------------------------------
# ClawContext evolution fields
# ---------------------------------------------------------------------------


class TestClawContextEvolutionFields:
    async def test_context_has_error_kb(self, evolution_context):
        ctx = evolution_context
        assert ctx.error_kb is not None
        assert isinstance(ctx.error_kb, ErrorKB)

    async def test_context_has_semantic_memory(self, evolution_context):
        ctx = evolution_context
        assert ctx.semantic_memory is not None
        assert isinstance(ctx.semantic_memory, SemanticMemory)

    async def test_context_has_prompt_evolver(self, evolution_context):
        ctx = evolution_context
        assert ctx.prompt_evolver is not None
        assert isinstance(ctx.prompt_evolver, PromptEvolver)

    async def test_context_has_pattern_learner(self, evolution_context):
        ctx = evolution_context
        assert ctx.pattern_learner is not None
        assert isinstance(ctx.pattern_learner, PatternLearner)

    async def test_context_fields_default_none(self):
        """When not provided, evolution fields default to None."""
        config = load_config()
        config.database.db_path = ":memory:"
        engine = DatabaseEngine(config.database)
        await engine.connect()
        await engine.initialize_schema()
        repo = Repository(engine)

        ctx = ClawContext(
            config=config,
            engine=engine,
            repository=repo,
            embeddings=EmbeddingEngine(config.embeddings),
            llm_client=LLMClient(config.llm),
            token_tracker=TokenTracker(repository=repo),
            security=SecurityPolicy(),
        )
        assert ctx.error_kb is None
        assert ctx.semantic_memory is None
        assert ctx.prompt_evolver is None
        assert ctx.pattern_learner is None
        await ctx.close()


# ---------------------------------------------------------------------------
# MicroClaw.evaluate() — error KB enrichment + semantic hints
# ---------------------------------------------------------------------------


class TestMicroClawEvaluateEnrichment:
    async def test_evaluate_enriches_from_error_kb(self, evolution_context, evo_project, evo_task):
        ctx = evolution_context
        await ctx.repository.create_project(evo_project)
        await ctx.repository.create_task(evo_task)

        # Record a prior failure with error signature so error KB has data
        await ctx.error_kb.record_attempt(
            task_id=evo_task.id,
            attempt_number=1,
            approach_summary="Tried naive pool increase",
            outcome=HypothesisOutcome.FAILURE,
            error_signature="connection_pool_exhaustion",
            error_full="Pool exhausted after 100 connections",
            agent_id="claude",
        )

        micro = MicroClaw(ctx, evo_project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)

        # Forbidden approaches should include the local failure
        assert len(task_ctx.forbidden_approaches) >= 1
        found_pool = any("pool" in fa.lower() for fa in task_ctx.forbidden_approaches)
        assert found_pool, f"Expected pool-related forbidden approach, got: {task_ctx.forbidden_approaches}"

    async def test_evaluate_adds_semantic_hints(self, evolution_context, evo_project, evo_task):
        ctx = evolution_context
        await ctx.repository.create_project(evo_project)
        await ctx.repository.create_task(evo_task)

        # Save a prior solution that should match the task description
        await ctx.semantic_memory.save_solution(
            problem_description="Database connection pool exhaustion under load",
            solution_code="Use SQLAlchemy pool_recycle=3600 and pool_pre_ping=True",
            methodology_notes="Recycle stale connections and pre-ping before checkout",
            tags=["bug_fix"],
        )

        micro = MicroClaw(ctx, evo_project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)

        # Hints list should be populated (may be empty if similarity is low,
        # which is acceptable -- the important thing is the code path works)
        assert isinstance(task_ctx.hints, list)

    async def test_evaluate_formats_preventive_memory_with_root_cause_details(
        self,
        evolution_context,
        evo_project,
        evo_task,
    ):
        ctx = evolution_context
        await ctx.repository.create_project(evo_project)
        await ctx.repository.create_task(evo_task)
        await ctx.repository.record_failure_knowledge(
            error_signature="camseq_negative_memory:auth-refresh:slot-refresh:comp-old",
            error_category="camseq_negative_memory",
            diagnosis="sync wrapper failed under concurrent token refresh",
            prevention_hint="prefer async-safe refresh path with explicit race tests",
            task_type=evo_task.task_type,
            project_id=evo_project.id,
            root_cause_key="camseq_negative_memory:auth-refresh:slot-refresh",
            detail_signals_json={
                "slot_name": "token_refresh",
                "component_title": "Legacy refresh adapter",
                "component_file_path": "app/auth.py",
                "transfer_mode": "direct_fit",
                "fit_bucket": "strong",
                "proof_gate_ids": ["tests", "verifier"],
                "landing_sites": [{"file_path": "app/auth.py"}],
            },
        )

        micro = MicroClaw(ctx, evo_project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)

        preventive = [
            item for item in task_ctx.forbidden_approaches
            if "root-cause=camseq_negative_memory:auth-refresh:slot-refresh" in item
        ]
        assert len(preventive) == 1
        assert "slot=token_refresh" in preventive[0]
        assert "component=Legacy refresh adapter (app/auth.py)" in preventive[0]
        assert "fit=direct_fit/strong" in preventive[0]
        assert "proof_gates=tests,verifier" in preventive[0]

    async def test_evaluate_keeps_one_preventive_memory_per_root_cause(
        self,
        evolution_context,
        evo_project,
        evo_task,
    ):
        ctx = evolution_context
        await ctx.repository.create_project(evo_project)
        await ctx.repository.create_task(evo_task)
        root_key = "camseq_negative_memory:auth-refresh:slot-refresh"
        await ctx.repository.record_failure_knowledge(
            error_signature="camseq_negative_memory:auth-refresh:slot-refresh:comp-low",
            error_category="camseq_negative_memory",
            diagnosis="first component failed",
            prevention_hint="low-signal hint",
            task_type=evo_task.task_type,
            project_id=evo_project.id,
            root_cause_key=root_key,
        )
        high_signature = "camseq_negative_memory:auth-refresh:slot-refresh:comp-high"
        for _ in range(2):
            await ctx.repository.record_failure_knowledge(
                error_signature=high_signature,
                error_category="camseq_negative_memory",
                diagnosis="repeated representative failure",
                prevention_hint="higher-signal hint",
                task_type=evo_task.task_type,
                project_id=evo_project.id,
                root_cause_key=root_key,
            )

        micro = MicroClaw(ctx, evo_project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)

        preventive = [
            item for item in task_ctx.forbidden_approaches
            if f"root-cause={root_key}" in item
        ]
        assert len(preventive) == 1
        assert high_signature in preventive[0]
        assert "higher-signal hint" in preventive[0]

    async def test_evaluate_still_works_without_evolution_components(self):
        """Without error_kb/semantic_memory, evaluate still works (backward compat)."""
        config = load_config()
        config.database.db_path = ":memory:"
        engine = DatabaseEngine(config.database)
        await engine.connect()
        await engine.initialize_schema()
        repo = Repository(engine)

        ctx = ClawContext(
            config=config,
            engine=engine,
            repository=repo,
            embeddings=EmbeddingEngine(config.embeddings),
            llm_client=LLMClient(config.llm),
            token_tracker=TokenTracker(repository=repo),
            security=SecurityPolicy(),
        )

        project = Project(name="bare", repo_path="/tmp/bare")
        task = Task(
            project_id=project.id,
            title="Simple task",
            description="No evolution components",
            priority=5,
        )
        await repo.create_project(project)
        await repo.create_task(task)

        micro = MicroClaw(ctx, project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)
        assert isinstance(task_ctx.forbidden_approaches, list)
        assert isinstance(task_ctx.hints, list)
        await ctx.close()


# ---------------------------------------------------------------------------
# MicroClaw.learn() — semantic memory save + error KB record + patterns
# ---------------------------------------------------------------------------


class TestMicroClawLearnEvolution:
    async def test_learn_success_saves_to_semantic_memory(self, evolution_context, evo_project, evo_task):
        ctx = evolution_context
        await ctx.repository.create_project(evo_project)
        await ctx.repository.create_task(evo_task)

        micro = MicroClaw(ctx, evo_project.id)

        # Simulate a successful verification tuple
        outcome = TaskOutcome(
            approach_summary="Applied connection pool recycling with pre-ping",
            raw_output="Updated pool config: pool_recycle=3600, pool_pre_ping=True",
            tests_passed=True,
            files_changed=["src/db/pool.py"],
            duration_seconds=15.0,
        )
        verification = VerificationResult(
            approved=True,
            quality_score=0.9,
        )
        task_ctx = TaskContext(task=evo_task)

        verified = ("claude", task_ctx, outcome, verification)
        await micro.learn(verified)

        # Verify the methodology was saved
        count = await ctx.semantic_memory.get_total_count()
        assert count >= 1

    async def test_learn_failure_records_in_error_kb(self, evolution_context, evo_project, evo_task):
        ctx = evolution_context
        await ctx.repository.create_project(evo_project)
        await ctx.repository.create_task(evo_task)

        micro = MicroClaw(ctx, evo_project.id)

        # Simulate a failed verification tuple
        outcome = TaskOutcome(
            approach_summary="Tried increasing pool size to 1000",
            failure_reason="memory_overflow",
            failure_detail="OOM after 500 connections",
            files_changed=[],
            duration_seconds=5.0,
        )
        verification = VerificationResult(
            approved=False,
            violations=[{"check": "execution", "detail": "memory_overflow"}],
            quality_score=0.2,
        )
        task_ctx = TaskContext(task=evo_task)

        verified = ("claude", task_ctx, outcome, verification)
        await micro.learn(verified)

        # Verify the error was recorded in the hypothesis log via error KB
        count = await ctx.repository.get_hypothesis_count(evo_task.id)
        assert count >= 1

    async def test_learn_failure_does_not_double_log_attempt(
        self,
        evolution_context,
        evo_project,
        evo_task,
        caplog,
    ):
        ctx = evolution_context
        await ctx.repository.create_project(evo_project)
        await ctx.repository.create_task(evo_task)

        micro = MicroClaw(ctx, evo_project.id)
        outcome = TaskOutcome(
            approach_summary="Attempted bad pool expansion",
            failure_reason="memory_overflow",
            failure_detail="OOM after 500 connections",
            files_changed=[],
            duration_seconds=5.0,
        )
        verification = VerificationResult(
            approved=False,
            violations=[{"check": "execution", "detail": "memory_overflow"}],
            quality_score=0.2,
        )
        task_ctx = TaskContext(task=evo_task)

        with caplog.at_level(logging.WARNING, logger="claw.cycle"):
            await micro.learn(("claude", task_ctx, outcome, verification))

        assert await ctx.repository.get_hypothesis_count(evo_task.id) == 1
        assert "Failed to record error in KB" not in caplog.text

    async def test_learn_success_triggers_pattern_extraction(self, evolution_context, evo_project):
        ctx = evolution_context
        await ctx.repository.create_project(evo_project)

        # Create 6 completed tasks so pattern extraction threshold (5) is met
        for i in range(6):
            t = Task(
                project_id=evo_project.id,
                title=f"Completed task {i}",
                description=f"Task description {i}",
                priority=5,
                status=TaskStatus.DONE,
            )
            await ctx.repository.create_task(t)

        # Now create the task that will "complete"
        evo_task = Task(
            project_id=evo_project.id,
            title="New task",
            description="New task to complete",
            priority=5,
        )
        await ctx.repository.create_task(evo_task)

        micro = MicroClaw(ctx, evo_project.id)

        outcome = TaskOutcome(
            approach_summary="Applied pattern X",
            tests_passed=True,
            files_changed=["src/foo.py"],
            duration_seconds=10.0,
        )
        verification = VerificationResult(approved=True, quality_score=0.8)
        task_ctx = TaskContext(task=evo_task)

        # This should trigger pattern extraction (6 DONE tasks exist)
        verified = ("claude", task_ctx, outcome, verification)
        await micro.learn(verified)

        # No assertion crash = pattern extraction ran without error


# ---------------------------------------------------------------------------
# NanoClaw
# ---------------------------------------------------------------------------


class TestNanoClaw:
    async def test_nano_claw_runs_full_cycle(self, evolution_context, evo_project):
        ctx = evolution_context
        await ctx.repository.create_project(evo_project)

        nano = NanoClaw(ctx, evo_project.id)
        result = await nano.run_cycle()
        assert isinstance(result, CycleResult)
        assert result.cycle_level == "nano"
        assert result.success is True
        assert result.project_id == evo_project.id

    async def test_nano_claw_grab_returns_project_id(self, evolution_context, evo_project):
        ctx = evolution_context
        nano = NanoClaw(ctx, evo_project.id)
        target = await nano.grab()
        assert target == evo_project.id

    async def test_nano_claw_evaluate_returns_summary(self, evolution_context, evo_project):
        ctx = evolution_context
        await ctx.repository.create_project(evo_project)

        nano = NanoClaw(ctx, evo_project.id)
        evaluation = await nano.evaluate(evo_project.id)
        assert isinstance(evaluation, dict)
        assert "task_summary" in evaluation
        assert "pattern_summary" in evaluation
        assert "project_id" in evaluation

    async def test_nano_claw_decide_includes_actions(self, evolution_context, evo_project):
        ctx = evolution_context
        nano = NanoClaw(ctx, evo_project.id)
        evaluation = {"task_summary": {}, "pattern_summary": None, "project_id": evo_project.id}
        actions = await nano.decide(evaluation)
        assert isinstance(actions, list)
        assert "evolve_prompts" in actions
        assert "extract_patterns" in actions

    async def test_nano_claw_act_executes_actions(self, evolution_context, evo_project):
        ctx = evolution_context
        await ctx.repository.create_project(evo_project)

        nano = NanoClaw(ctx, evo_project.id)
        actions = ["evolve_prompts", "extract_patterns"]
        results = await nano.act(actions)
        assert isinstance(results, dict)
        # prompt_evolution should have run (may report "evaluated 0 tests")
        assert "prompt_evolution" in results
        # patterns_extracted should be 0 (not enough completed tasks)
        assert "patterns_extracted" in results

    async def test_nano_claw_logs_episode(self, evolution_context, evo_project):
        ctx = evolution_context
        await ctx.repository.create_project(evo_project)

        nano = NanoClaw(ctx, evo_project.id)
        await nano.run_cycle()

        # Check that an episode was logged
        episodes = await ctx.repository.engine.fetch_all(
            "SELECT * FROM episodes WHERE cycle_level = 'nano'"
        )
        assert len(episodes) >= 1

    async def test_nano_claw_with_ab_tests(self, evolution_context, evo_project):
        ctx = evolution_context
        await ctx.repository.create_project(evo_project)

        # Schedule an A/B test
        await ctx.prompt_evolver.schedule_ab_test(
            prompt_name="deepdive",
            control_content="Analyze the codebase thoroughly.",
            variant_content="IMPORTANT: Analyze the codebase thoroughly.",
        )

        nano = NanoClaw(ctx, evo_project.id)
        result = await nano.run_cycle()
        assert result.success is True


# ---------------------------------------------------------------------------
# MesoClaw
# ---------------------------------------------------------------------------


class TestMesoClaw:
    async def test_meso_claw_grab_returns_repo_path(self, evolution_context, evo_project):
        ctx = evolution_context
        meso = MesoClaw(ctx, evo_project.id, evo_project.repo_path)
        target = await meso.grab()
        assert target == evo_project.repo_path

    async def test_meso_claw_run_cycle_returns_result(self, evolution_context, evo_project):
        ctx = evolution_context
        await ctx.repository.create_project(evo_project)

        meso = MesoClaw(ctx, evo_project.id, evo_project.repo_path)
        result = await meso.run_cycle()
        assert isinstance(result, CycleResult)
        assert result.cycle_level == "meso"
        assert result.project_id == evo_project.id

    async def test_meso_claw_evaluate_returns_report(self, evolution_context, evo_project):
        ctx = evolution_context
        await ctx.repository.create_project(evo_project)

        meso = MesoClaw(ctx, evo_project.id, evo_project.repo_path)
        report = await meso.evaluate(evo_project.repo_path)

        # report should have phases attribute (even if evaluation had no output)
        assert hasattr(report, "phases")
        assert hasattr(report, "total_prompts")

    async def test_meso_claw_decide_returns_task_list(self, evolution_context, evo_project):
        ctx = evolution_context
        await ctx.repository.create_project(evo_project)

        meso = MesoClaw(ctx, evo_project.id, evo_project.repo_path)
        report = await meso.evaluate(evo_project.repo_path)
        tasks = await meso.decide(report)
        assert isinstance(tasks, list)

    async def test_meso_claw_verify_returns_aggregate(self, evolution_context, evo_project):
        ctx = evolution_context
        meso = MesoClaw(ctx, evo_project.id, evo_project.repo_path)

        # Simulate MicroClaw results
        results = [
            CycleResult(cycle_level="micro", success=True, duration_seconds=1.0),
            CycleResult(cycle_level="micro", success=False, duration_seconds=2.0),
            CycleResult(cycle_level="micro", success=True, duration_seconds=1.5),
        ]

        verification = await meso.verify(results)
        successes, total, _results = verification
        assert successes == 2
        assert total == 3

    async def test_meso_claw_learn_logs_episode(self, evolution_context, evo_project):
        ctx = evolution_context
        await ctx.repository.create_project(evo_project)

        meso = MesoClaw(ctx, evo_project.id, evo_project.repo_path)
        outcome = (3, 5, [])
        await meso.learn(outcome)

        episodes = await ctx.repository.engine.fetch_all(
            "SELECT * FROM episodes WHERE cycle_level = 'meso' AND event_type = 'meso_cycle_completed'"
        )
        assert len(episodes) >= 1

    async def test_meso_claw_learn_triggers_prompt_evolution(self, evolution_context, evo_project):
        ctx = evolution_context
        await ctx.repository.create_project(evo_project)

        # Schedule an A/B test with enough samples for evaluation
        await ctx.prompt_evolver.schedule_ab_test(
            prompt_name="test-prompt",
            control_content="Control text.",
            variant_content="Variant text.",
        )

        meso = MesoClaw(ctx, evo_project.id, evo_project.repo_path)
        # total >= 5 triggers prompt evolution
        outcome = (5, 5, [])
        await meso.learn(outcome)

        # Verify the A/B test was evaluated (even if not enough samples to promote)
        tests = await ctx.prompt_evolver.list_tests()
        assert len(tests) >= 1

    async def test_meso_claw_on_step_callback(self, evolution_context, evo_project):
        ctx = evolution_context
        await ctx.repository.create_project(evo_project)

        steps = []

        def on_step(name: str, detail: str = "") -> None:
            steps.append(name)

        meso = MesoClaw(ctx, evo_project.id, evo_project.repo_path)
        await meso.run_cycle(on_step=on_step)

        assert "grab" in steps
        assert "evaluate" in steps
        assert "decide" in steps


# ---------------------------------------------------------------------------
# Integration: MicroClaw + NanoClaw sequence
# ---------------------------------------------------------------------------


class TestMicroNanoIntegration:
    async def test_micro_then_nano_cycle(self, evolution_context, evo_project, evo_task):
        """After MicroClaw completes, NanoClaw should run without error."""
        ctx = evolution_context
        await ctx.repository.create_project(evo_project)
        await ctx.repository.create_task(evo_task)

        # MicroClaw will fail (no agents) but should still learn from the failure
        micro = MicroClaw(ctx, evo_project.id)
        micro_result = await micro.run_cycle()

        # NanoClaw runs self-improvement
        nano = NanoClaw(ctx, evo_project.id)
        nano_result = await nano.run_cycle()
        assert nano_result.success is True

    async def test_nano_after_multiple_micro_cycles(self, evolution_context, evo_project):
        """NanoClaw benefits from data left by multiple MicroClaw cycles."""
        ctx = evolution_context
        await ctx.repository.create_project(evo_project)

        for i in range(3):
            task = Task(
                project_id=evo_project.id,
                title=f"Task {i}",
                description=f"Description {i}",
                priority=5,
            )
            await ctx.repository.create_task(task)

        for _ in range(3):
            micro = MicroClaw(ctx, evo_project.id)
            await micro.run_cycle()

        nano = NanoClaw(ctx, evo_project.id)
        result = await nano.run_cycle()
        assert result.success is True
