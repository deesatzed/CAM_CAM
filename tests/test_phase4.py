"""Tests for CLAW Phase 4 — Batch 1: PromptEvolver, CapabilityDiscovery, ClawMCPServer.

Covers:
  1. PromptEvolver    — prompt mutation, A/B testing, sample recording, evaluation,
                        promotion, variant selection, listing, and enrichment
  2. CapabilityDiscovery — boundary recording, dedup, retesting, resolution,
                           escalation, and summary statistics
  3. ClawMCPServer    — tool schema, dispatch routing, query_memory, store_finding,
                        verify_claim, request_specialist, escalate

NO mocks, NO placeholders, NO cached responses, NO simulation. All tests use real
SQLite in-memory databases via the ``db_engine`` / ``repository`` fixtures from conftest.
"""

from __future__ import annotations

import uuid

import pytest

from claw.db.repository import Repository
from claw.evolution.capability_disc import CapabilityDiscovery
from claw.evolution.prompt_evolver import (
    _PRIOR_ALPHA,
    _PRIOR_BETA,
    MIN_SAMPLES,
    PromptEvolver,
    _bayesian_score,
)
from claw.mcp_server import ClawMCPServer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return str(uuid.uuid4())


# ===========================================================================
# Module 1: PromptEvolver
# ===========================================================================


class TestPromptEvolverMutations:
    """Tests for PromptEvolver.mutate_prompt — deterministic string transformations."""

    @pytest.fixture
    async def evolver(self, repository: Repository) -> PromptEvolver:
        return PromptEvolver(repository=repository)

    # -- test_mutate_add_emphasis ----------------------------------------

    async def test_mutate_add_emphasis(self, evolver: PromptEvolver):
        """Lines containing directive keywords get IMPORTANT: prefix."""
        base = "You must validate all inputs.\nReturn a JSON object."
        result = evolver.mutate_prompt(base, "add_emphasis")
        lines = result.split("\n")
        assert lines[0] == "IMPORTANT: You must validate all inputs."
        # "Return a JSON object" has no directive keyword -> unchanged
        assert lines[1] == "Return a JSON object."

    async def test_mutate_add_emphasis_multiple_keywords(self, evolver: PromptEvolver):
        """Multiple directive keywords in different lines all get prefixed."""
        base = (
            "Always check for null.\n"
            "Never skip validation.\n"
            "Optional greeting line."
        )
        result = evolver.mutate_prompt(base, "add_emphasis")
        lines = result.split("\n")
        assert lines[0].startswith("IMPORTANT:")
        assert lines[1].startswith("IMPORTANT:")
        assert not lines[2].startswith("IMPORTANT:")

    async def test_mutate_add_emphasis_already_prefixed(self, evolver: PromptEvolver):
        """Lines already starting with IMPORTANT are not double-prefixed."""
        base = "IMPORTANT: You must always verify."
        result = evolver.mutate_prompt(base, "add_emphasis")
        assert result.count("IMPORTANT:") == 1

    # -- test_mutate_reorder_sections ------------------------------------

    async def test_mutate_reorder_sections(self, evolver: PromptEvolver):
        """Sections after the header are reversed; header stays first."""
        base = "Header\n\nSection A\n\nSection B\n\nSection C"
        result = evolver.mutate_prompt(base, "reorder_sections")
        sections = result.split("\n\n")
        assert sections[0] == "Header"
        assert sections[1] == "Section C"
        assert sections[2] == "Section B"
        assert sections[3] == "Section A"

    async def test_mutate_reorder_sections_two_sections_unchanged(self, evolver: PromptEvolver):
        """With only 2 sections (header + 1 body), no reordering occurs."""
        base = "Header\n\nOnly body section"
        result = evolver.mutate_prompt(base, "reorder_sections")
        assert result == base

    # -- test_mutate_add_constraints -------------------------------------

    async def test_mutate_add_constraints(self, evolver: PromptEvolver):
        """Quality constraints block is appended."""
        base = "Analyze the codebase."
        result = evolver.mutate_prompt(base, "add_constraints")
        assert "Additional Quality Constraints" in result
        assert "Every claim must be verifiable" in result
        assert result.startswith("Analyze the codebase.")

    # -- test_mutate_simplify --------------------------------------------

    async def test_mutate_simplify(self, evolver: PromptEvolver):
        """Parenthetical remarks (>=5 chars inside) are stripped."""
        base = "Check code quality (this is an aside remark) carefully."
        result = evolver.mutate_prompt(base, "simplify")
        assert "(this is an aside remark)" not in result
        assert "carefully" in result

    async def test_mutate_simplify_short_parens_kept(self, evolver: PromptEvolver):
        """Parenthetical remarks shorter than 5 chars are preserved."""
        base = "Use Python (3.12) for the project."
        result = evolver.mutate_prompt(base, "simplify")
        # "(3.12)" has content length 4 < 5 so it stays
        assert "(3.12)" in result

    # -- test_mutate_add_examples ----------------------------------------

    async def test_mutate_add_examples(self, evolver: PromptEvolver):
        """Examples section is appended."""
        base = "Provide recommendations."
        result = evolver.mutate_prompt(base, "add_examples_placeholder")
        assert "--- Examples ---" in result
        assert "concrete example" in result

    # -- test_mutate_unknown_type_raises ---------------------------------

    async def test_mutate_unknown_type_raises(self, evolver: PromptEvolver):
        """Unknown mutation type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown mutation_type"):
            evolver.mutate_prompt("test", "nonexistent_type")


class TestPromptEvolverABTesting:
    """Tests for A/B test scheduling, sample recording, and evaluation."""

    @pytest.fixture
    async def evolver(self, repository: Repository) -> PromptEvolver:
        return PromptEvolver(repository=repository)

    # -- test_schedule_ab_test -------------------------------------------

    async def test_schedule_ab_test(self, evolver: PromptEvolver):
        """Creates control + variant rows and returns both IDs."""
        ids = await evolver.schedule_ab_test(
            prompt_name="deepdive",
            control_content="Original prompt.",
            variant_content="Mutated prompt.",
        )
        assert "control_id" in ids
        assert "variant_id" in ids
        assert ids["control_id"] != ids["variant_id"]

        # Verify DB state: control is active, variant is not
        active = await evolver.get_active_variant("deepdive")
        assert active is not None
        assert active["variant_label"] == "control"
        assert active["content"] == "Original prompt."

    # -- test_schedule_ab_test_upsert ------------------------------------

    async def test_schedule_ab_test_upsert(self, evolver: PromptEvolver):
        """Scheduling again resets counters but reuses row IDs."""
        ids1 = await evolver.schedule_ab_test(
            prompt_name="deepdive",
            control_content="Original v1.",
            variant_content="Variant v1.",
        )

        # Record some samples to dirty the counters
        await evolver.record_sample("deepdive", "control", None, True, 0.8)
        await evolver.record_sample("deepdive", "variant", None, False, 0.3)

        # Re-schedule — should reset counters
        ids2 = await evolver.schedule_ab_test(
            prompt_name="deepdive",
            control_content="Original v2.",
            variant_content="Variant v2.",
        )

        # Same row IDs should be reused
        assert ids2["control_id"] == ids1["control_id"]
        assert ids2["variant_id"] == ids1["variant_id"]

        # Counters should be reset
        result = await evolver.evaluate_test("deepdive")
        assert result["control"]["sample_count"] == 0
        assert result["variant"]["sample_count"] == 0

    # -- test_record_sample_success --------------------------------------

    async def test_record_sample_success(self, evolver: PromptEvolver):
        """Recording a success increments both sample_count and success_count."""
        await evolver.schedule_ab_test("test_prompt", "ctrl", "var")

        ok = await evolver.record_sample("test_prompt", "control", None, True, 0.9)
        assert ok is True

        result = await evolver.evaluate_test("test_prompt")
        ctrl = result["control"]
        assert ctrl["sample_count"] == 1
        assert ctrl["success_count"] == 1

    # -- test_record_sample_failure --------------------------------------

    async def test_record_sample_failure(self, evolver: PromptEvolver):
        """Recording a failure increments sample_count but not success_count."""
        await evolver.schedule_ab_test("test_prompt", "ctrl", "var")

        ok = await evolver.record_sample("test_prompt", "variant", None, False, 0.2)
        assert ok is True

        result = await evolver.evaluate_test("test_prompt")
        var = result["variant"]
        assert var["sample_count"] == 1
        assert var["success_count"] == 0

    # -- test_record_sample_not_found ------------------------------------

    async def test_record_sample_not_found(self, evolver: PromptEvolver):
        """Recording a sample for a nonexistent variant returns False."""
        ok = await evolver.record_sample("no_such_prompt", "control", None, True, 0.5)
        assert ok is False

    # -- test_evaluate_test_not_ready ------------------------------------

    async def test_evaluate_test_not_ready(self, evolver: PromptEvolver):
        """Evaluation returns ready=False when samples < MIN_SAMPLES."""
        await evolver.schedule_ab_test("ab_test", "ctrl", "var")

        # Record fewer than MIN_SAMPLES
        for _ in range(MIN_SAMPLES - 1):
            await evolver.record_sample("ab_test", "control", None, True, 0.7)
            await evolver.record_sample("ab_test", "variant", None, True, 0.8)

        result = await evolver.evaluate_test("ab_test")
        assert result["ready"] is False
        assert result["winner"] is None

    # -- test_evaluate_test_variant_wins ---------------------------------

    async def test_evaluate_test_variant_wins(self, evolver: PromptEvolver):
        """Variant with significantly better success rate wins."""
        await evolver.schedule_ab_test("ab_test", "ctrl", "var")

        # Control: 50% success rate
        for i in range(MIN_SAMPLES):
            await evolver.record_sample(
                "ab_test", "control", None, i % 2 == 0, 0.5
            )
        # Variant: 95% success rate
        for i in range(MIN_SAMPLES):
            await evolver.record_sample(
                "ab_test", "variant", None, True, 0.9
            )

        result = await evolver.evaluate_test("ab_test")
        assert result["ready"] is True
        assert result["winner"] == "variant"
        assert result["margin"] > result["effective_margin"]

    # -- test_evaluate_test_control_wins ---------------------------------

    async def test_evaluate_test_control_wins(self, evolver: PromptEvolver):
        """Control with significantly better success rate wins."""
        await evolver.schedule_ab_test("ab_test", "ctrl", "var")

        # Control: 95% success rate
        for _ in range(MIN_SAMPLES):
            await evolver.record_sample("ab_test", "control", None, True, 0.9)

        # Variant: 30% success rate
        for i in range(MIN_SAMPLES):
            await evolver.record_sample(
                "ab_test", "variant", None, i < (MIN_SAMPLES * 3 // 10), 0.3
            )

        result = await evolver.evaluate_test("ab_test")
        assert result["ready"] is True
        assert result["winner"] == "control"
        assert result["margin"] < -result["effective_margin"]

    # -- test_evaluate_test_inconclusive ---------------------------------

    async def test_evaluate_test_inconclusive(self, evolver: PromptEvolver):
        """Very similar rates produce winner=None."""
        await evolver.schedule_ab_test("ab_test", "ctrl", "var")

        # Both at ~80% success
        for i in range(MIN_SAMPLES):
            success = i < (MIN_SAMPLES * 4 // 5)
            await evolver.record_sample("ab_test", "control", None, success, 0.8)
            await evolver.record_sample("ab_test", "variant", None, success, 0.8)

        result = await evolver.evaluate_test("ab_test")
        assert result["ready"] is True
        assert result["winner"] is None
        assert abs(result["margin"]) <= result["effective_margin"]

    # -- test_evaluate_test_missing_variant ------------------------------

    async def test_evaluate_test_missing_variant(self, evolver: PromptEvolver):
        """Evaluation returns ready=False when variant row is missing entirely."""
        result = await evolver.evaluate_test("totally_missing")
        assert result["ready"] is False
        assert result["winner"] is None


class TestPromptEvolverPromotion:
    """Tests for promote_variant, get_active_variant, and related methods."""

    @pytest.fixture
    async def evolver(self, repository: Repository) -> PromptEvolver:
        return PromptEvolver(repository=repository)

    # -- test_promote_variant --------------------------------------------

    async def test_promote_variant(self, evolver: PromptEvolver):
        """Promoting variant activates it and deactivates control."""
        await evolver.schedule_ab_test("promo_test", "ctrl text", "var text")

        ok = await evolver.promote_variant("promo_test", "variant")
        assert ok is True

        active = await evolver.get_active_variant("promo_test")
        assert active is not None
        assert active["variant_label"] == "variant"
        assert active["content"] == "var text"

    # -- test_promote_variant_not_found ----------------------------------

    async def test_promote_variant_not_found(self, evolver: PromptEvolver):
        """Promoting a nonexistent variant returns False."""
        ok = await evolver.promote_variant("no_such_prompt", "variant")
        assert ok is False

    # -- test_get_active_variant -----------------------------------------

    async def test_get_active_variant(self, evolver: PromptEvolver):
        """Returns the active variant content."""
        await evolver.schedule_ab_test("active_test", "ctrl content", "var content")
        active = await evolver.get_active_variant("active_test")
        assert active is not None
        assert active["content"] == "ctrl content"

    # -- test_get_active_variant_fallback --------------------------------

    async def test_get_active_variant_fallback(self, evolver: PromptEvolver):
        """Agent-specific lookup falls back to agent-agnostic."""
        await evolver.schedule_ab_test("fallback_test", "generic ctrl", "generic var")

        # Query with a specific agent_id — should fall back to agent-agnostic row
        active = await evolver.get_active_variant("fallback_test", agent_id="claude")
        assert active is not None
        assert active["content"] == "generic ctrl"
        assert active["agent_id"] is None

    # -- test_get_active_variant_none ------------------------------------

    async def test_get_active_variant_none(self, evolver: PromptEvolver):
        """No variants at all returns None."""
        active = await evolver.get_active_variant("nonexistent_prompt")
        assert active is None

    # -- test_select_variant_for_invocation_random -----------------------

    async def test_select_variant_for_invocation_random(self, evolver: PromptEvolver):
        """During active test (samples < MIN_SAMPLES), assignment is random."""
        await evolver.schedule_ab_test("rand_test", "ctrl_text", "var_text")

        labels_seen = set()
        # Run enough times to statistically see both labels
        for _ in range(50):
            label, content = await evolver.select_variant_for_invocation("rand_test")
            labels_seen.add(label)
            assert label in ("control", "variant")
            if label == "control":
                assert content == "ctrl_text"
            else:
                assert content == "var_text"

        # With 50 iterations, both labels should appear
        assert "control" in labels_seen
        assert "variant" in labels_seen

    # -- test_select_variant_for_invocation_active -----------------------

    async def test_select_variant_for_invocation_active(self, evolver: PromptEvolver):
        """After both variants reach MIN_SAMPLES, returns the active variant."""
        await evolver.schedule_ab_test("done_test", "ctrl_done", "var_done")

        # Fill both to MIN_SAMPLES
        for _ in range(MIN_SAMPLES):
            await evolver.record_sample("done_test", "control", None, True, 0.7)
            await evolver.record_sample("done_test", "variant", None, True, 0.7)

        label, content = await evolver.select_variant_for_invocation("done_test")
        # Active is control (set by schedule_ab_test)
        assert label == "control"
        assert content == "ctrl_done"

    # -- test_select_variant_no_variants_raises --------------------------

    async def test_select_variant_no_variants_raises(self, evolver: PromptEvolver):
        """Raises ValueError when no variants exist for the prompt."""
        with pytest.raises(ValueError, match="No variants found"):
            await evolver.select_variant_for_invocation("totally_missing")

    # -- test_list_tests -------------------------------------------------

    async def test_list_tests(self, evolver: PromptEvolver):
        """Lists tests grouped by prompt_name."""
        await evolver.schedule_ab_test("prompt_a", "ca", "va")
        await evolver.schedule_ab_test("prompt_b", "cb", "vb")

        tests = await evolver.list_tests()
        names = {t["prompt_name"] for t in tests}
        assert "prompt_a" in names
        assert "prompt_b" in names

        for t in tests:
            assert "variants" in t
            labels = {v["variant_label"] for v in t["variants"]}
            assert "control" in labels
            assert "variant" in labels

    async def test_list_tests_filtered_by_agent(self, evolver: PromptEvolver):
        """list_tests with agent_id filters correctly."""
        await evolver.schedule_ab_test("agent_test", "ctrl", "var", agent_id="claude")
        await evolver.schedule_ab_test("agent_test", "ctrl", "var", agent_id=None)

        # Filter by agent_id="claude"
        tests = await evolver.list_tests(agent_id="claude")
        assert len(tests) >= 1
        for t in tests:
            assert t["agent_id"] == "claude"


class TestPromptEvolverEvolveAndBayesian:
    """Tests for evolve_prompt and _bayesian_score."""

    @pytest.fixture
    async def evolver(self, repository: Repository) -> PromptEvolver:
        return PromptEvolver(repository=repository)

    # -- test_evolve_prompt_no_enrichment --------------------------------

    async def test_evolve_prompt_no_enrichment(self, evolver: PromptEvolver):
        """Without semantic_memory or error_kb, prompt returns unchanged."""
        base = "Analyze the codebase for issues."
        result = await evolver.evolve_prompt(base)
        assert result == base

    # -- test_bayesian_score_computation ---------------------------------

    def test_bayesian_score_computation(self):
        """_bayesian_score returns correct Beta posterior mean."""
        # With 0 successes, 0 samples: prior only
        score = _bayesian_score(0, 0)
        expected = _PRIOR_ALPHA / (_PRIOR_ALPHA + _PRIOR_BETA)
        assert abs(score - expected) < 1e-9

        # With 10 successes, 10 samples
        score = _bayesian_score(10, 10)
        alpha = _PRIOR_ALPHA + 10
        beta = _PRIOR_BETA + 0
        expected = alpha / (alpha + beta)
        assert abs(score - expected) < 1e-9

        # With 5 successes, 20 samples
        score = _bayesian_score(5, 20)
        alpha = _PRIOR_ALPHA + 5
        beta = _PRIOR_BETA + 15
        expected = alpha / (alpha + beta)
        assert abs(score - expected) < 1e-9

    def test_bayesian_score_symmetry(self):
        """Score for (s, n) should be complementary to score for (n-s, n)."""
        score_high = _bayesian_score(18, 20)
        score_low = _bayesian_score(2, 20)
        # They should sum to approximately 1.0
        assert abs(score_high + score_low - 1.0) < 1e-9

    # -- test_record_sample_quality_running_average ----------------------

    async def test_record_sample_quality_running_average(self, evolver: PromptEvolver):
        """Quality score uses running average correctly."""
        await evolver.schedule_ab_test("quality_test", "ctrl", "var")

        await evolver.record_sample("quality_test", "control", None, True, 0.6)
        await evolver.record_sample("quality_test", "control", None, True, 0.8)

        result = await evolver.evaluate_test("quality_test")
        avg = result["control"]["avg_quality_score"]
        assert abs(avg - 0.7) < 1e-9


# ===========================================================================
# Module 2: CapabilityDiscovery
# ===========================================================================


class TestCapabilityDiscoveryRecord:
    """Tests for recording and deduplicating capability boundaries."""

    @pytest.fixture
    async def cap_disc(self, repository: Repository) -> CapabilityDiscovery:
        return CapabilityDiscovery(repository=repository, retest_days=30)

    # -- test_record_boundary_new ----------------------------------------

    async def test_record_boundary_new(self, cap_disc: CapabilityDiscovery):
        """Creates a new boundary, returns a UUID string."""
        bid = await cap_disc.record_boundary(
            task_type="refactor",
            task_description="Refactor the authentication module",
            agents_attempted=["claude", "codex"],
            failure_signatures=["TypeError: cannot unpack None"],
        )
        assert isinstance(bid, str)
        assert len(bid) == 36  # UUID length

        # Verify it exists in unresolved
        unresolved = await cap_disc.get_unresolved_boundaries()
        assert any(b["id"] == bid for b in unresolved)

    # -- test_record_boundary_dedup --------------------------------------

    async def test_record_boundary_dedup(self, cap_disc: CapabilityDiscovery):
        """Same task_type + exact description deduplicates to update."""
        bid1 = await cap_disc.record_boundary(
            task_type="security_fix",
            task_description="Fix SQL injection in user endpoint",
            agents_attempted=["claude"],
            failure_signatures=["sig1"],
        )
        bid2 = await cap_disc.record_boundary(
            task_type="security_fix",
            task_description="Fix SQL injection in user endpoint",
            agents_attempted=["codex"],
            failure_signatures=["sig2"],
        )
        assert bid1 == bid2

        # Agents and sigs should be merged
        unresolved = await cap_disc.get_unresolved_boundaries()
        boundary = next(b for b in unresolved if b["id"] == bid1)
        assert "claude" in boundary["agents_attempted"]
        assert "codex" in boundary["agents_attempted"]
        assert "sig1" in boundary["failure_signatures"]
        assert "sig2" in boundary["failure_signatures"]

    # -- test_record_boundary_dedup_substring ----------------------------

    async def test_record_boundary_dedup_substring(self, cap_disc: CapabilityDiscovery):
        """Substring match in description deduplicates to existing row."""
        bid1 = await cap_disc.record_boundary(
            task_type="refactor",
            task_description="Refactor auth module",
            agents_attempted=["claude"],
            failure_signatures=["err1"],
        )
        bid2 = await cap_disc.record_boundary(
            task_type="refactor",
            task_description="Refactor auth module with JWT integration",
            agents_attempted=["gemini"],
            failure_signatures=["err2"],
        )
        # "Refactor auth module" is a substring of the second description
        assert bid1 == bid2


class TestCapabilityDiscoveryChecks:
    """Tests for check_boundary_exists."""

    @pytest.fixture
    async def cap_disc(self, repository: Repository) -> CapabilityDiscovery:
        return CapabilityDiscovery(repository=repository, retest_days=30)

    # -- test_check_boundary_exists_true ---------------------------------

    async def test_check_boundary_exists_true(self, cap_disc: CapabilityDiscovery):
        """Returns True when a matching unresolved boundary exists."""
        await cap_disc.record_boundary(
            task_type="migration",
            task_description="Migrate from Django to FastAPI",
            agents_attempted=["claude", "codex"],
            failure_signatures=["complex_migration_error"],
        )
        exists = await cap_disc.check_boundary_exists("migration", "Migrate from Django to FastAPI")
        assert exists is True

    # -- test_check_boundary_exists_false --------------------------------

    async def test_check_boundary_exists_false(self, cap_disc: CapabilityDiscovery):
        """Returns False when no matching boundary exists."""
        exists = await cap_disc.check_boundary_exists("nonexistent_type", "some description")
        assert exists is False


class TestCapabilityDiscoveryUnresolved:
    """Tests for get_unresolved_boundaries and get_retestable_boundaries."""

    @pytest.fixture
    async def cap_disc(self, repository: Repository) -> CapabilityDiscovery:
        return CapabilityDiscovery(repository=repository, retest_days=0)

    # -- test_get_unresolved_boundaries ----------------------------------

    async def test_get_unresolved_boundaries(self, cap_disc: CapabilityDiscovery):
        """Returns only unresolved boundaries."""
        bid1 = await cap_disc.record_boundary(
            "bug_fix", "Bug A", ["claude"], ["err_a"]
        )
        bid2 = await cap_disc.record_boundary(
            "bug_fix", "Bug B", ["codex"], ["err_b"]
        )
        # Resolve one
        await cap_disc.mark_resolved(bid1)

        unresolved = await cap_disc.get_unresolved_boundaries()
        ids = [b["id"] for b in unresolved]
        assert bid2 in ids
        assert bid1 not in ids

    # -- test_get_retestable_boundaries ----------------------------------

    async def test_get_retestable_boundaries(self, repository: Repository):
        """Boundaries old enough to retest are returned."""
        # Use retest_days=0 so everything older than 'now' is retestable
        cap_disc = CapabilityDiscovery(repository=repository, retest_days=0)

        bid = await cap_disc.record_boundary(
            "analysis", "Complex analysis task", ["claude"], ["timeout"]
        )

        retestable = await cap_disc.get_retestable_boundaries()
        ids = [b["id"] for b in retestable]
        assert bid in ids


class TestCapabilityDiscoveryRetest:
    """Tests for mark_retested and auto-resolution."""

    @pytest.fixture
    async def cap_disc(self, repository: Repository) -> CapabilityDiscovery:
        return CapabilityDiscovery(repository=repository, retest_days=30)

    # -- test_mark_retested ----------------------------------------------

    async def test_mark_retested(self, cap_disc: CapabilityDiscovery):
        """Updates retest fields."""
        bid = await cap_disc.record_boundary(
            "testing", "Flaky test suite", ["codex"], ["flaky_err"]
        )
        ok = await cap_disc.mark_retested(bid, "still_failing")
        assert ok is True

        # Verify retest_result is stored
        boundaries = await cap_disc.get_unresolved_boundaries()
        boundary = next(b for b in boundaries if b["id"] == bid)
        assert boundary["last_retested_at"] is not None

    # -- test_mark_retested_auto_resolve ---------------------------------

    async def test_mark_retested_auto_resolve(self, cap_disc: CapabilityDiscovery):
        """result="resolved" auto-resolves the boundary."""
        bid = await cap_disc.record_boundary(
            "ci_cd", "Pipeline always fails", ["codex"], ["build_err"]
        )
        ok = await cap_disc.mark_retested(bid, "resolved")
        assert ok is True

        # Should no longer appear in unresolved
        unresolved = await cap_disc.get_unresolved_boundaries()
        ids = [b["id"] for b in unresolved]
        assert bid not in ids

    # -- test_mark_retested_not_found ------------------------------------

    async def test_mark_retested_not_found(self, cap_disc: CapabilityDiscovery):
        """Returns False for nonexistent boundary."""
        ok = await cap_disc.mark_retested("nonexistent-id", "still_failing")
        assert ok is False


class TestCapabilityDiscoveryResolution:
    """Tests for mark_resolved."""

    @pytest.fixture
    async def cap_disc(self, repository: Repository) -> CapabilityDiscovery:
        return CapabilityDiscovery(repository=repository, retest_days=30)

    # -- test_mark_resolved ----------------------------------------------

    async def test_mark_resolved(self, cap_disc: CapabilityDiscovery):
        """Sets resolved=1."""
        bid = await cap_disc.record_boundary(
            "refactor", "Complex refactor", ["claude"], ["err"]
        )
        ok = await cap_disc.mark_resolved(bid)
        assert ok is True

        unresolved = await cap_disc.get_unresolved_boundaries()
        ids = [b["id"] for b in unresolved]
        assert bid not in ids

    # -- test_mark_resolved_already --------------------------------------

    async def test_mark_resolved_already(self, cap_disc: CapabilityDiscovery):
        """Already resolved boundary returns True without error."""
        bid = await cap_disc.record_boundary(
            "refactor", "Already resolved", ["claude"], ["err"]
        )
        await cap_disc.mark_resolved(bid)
        ok = await cap_disc.mark_resolved(bid)
        assert ok is True

    # -- test_mark_resolved_not_found ------------------------------------

    async def test_mark_resolved_not_found(self, cap_disc: CapabilityDiscovery):
        """Returns False for nonexistent boundary."""
        ok = await cap_disc.mark_resolved("nonexistent-id")
        assert ok is False


class TestCapabilityDiscoveryEscalation:
    """Tests for escalate_to_human."""

    @pytest.fixture
    async def cap_disc(self, repository: Repository) -> CapabilityDiscovery:
        return CapabilityDiscovery(repository=repository, retest_days=30)

    # -- test_escalate_to_human ------------------------------------------

    async def test_escalate_to_human(self, cap_disc: CapabilityDiscovery):
        """Sets the escalated flag."""
        bid = await cap_disc.record_boundary(
            "security", "Critical vuln", ["claude", "codex"], ["cve_err"]
        )
        ok = await cap_disc.escalate_to_human(bid)
        assert ok is True

        summary = await cap_disc.get_boundary_summary()
        assert summary["escalated"] >= 1

    # -- test_escalate_already -------------------------------------------

    async def test_escalate_already(self, cap_disc: CapabilityDiscovery):
        """Already escalated boundary returns True."""
        bid = await cap_disc.record_boundary(
            "security", "Already escalated vuln", ["claude"], ["err"]
        )
        await cap_disc.escalate_to_human(bid)
        ok = await cap_disc.escalate_to_human(bid)
        assert ok is True

    # -- test_escalate_not_found -----------------------------------------

    async def test_escalate_not_found(self, cap_disc: CapabilityDiscovery):
        """Returns False for nonexistent boundary."""
        ok = await cap_disc.escalate_to_human("nonexistent-id")
        assert ok is False


class TestCapabilityDiscoverySummary:
    """Tests for get_boundary_summary."""

    @pytest.fixture
    async def cap_disc(self, repository: Repository) -> CapabilityDiscovery:
        return CapabilityDiscovery(repository=repository, retest_days=0)

    # -- test_boundary_summary -------------------------------------------

    async def test_boundary_summary(self, cap_disc: CapabilityDiscovery):
        """Summary returns correct counts and breakdowns."""
        bid1 = await cap_disc.record_boundary(
            "refactor", "Refactor task A", ["claude", "codex"], ["err1"]
        )
        bid2 = await cap_disc.record_boundary(
            "security", "Security task B", ["gemini"], ["err2"]
        )
        bid3 = await cap_disc.record_boundary(
            "refactor", "Refactor task C", ["grok"], ["err3"]
        )

        # Resolve one, escalate another
        await cap_disc.mark_resolved(bid1)
        await cap_disc.escalate_to_human(bid2)

        summary = await cap_disc.get_boundary_summary()
        assert summary["total"] == 3
        assert summary["resolved"] == 1
        assert summary["unresolved"] == 2
        assert summary["escalated"] == 1
        assert "by_task_type" in summary
        assert "agents_most_involved" in summary

        # by_task_type counts only unresolved
        assert summary["by_task_type"].get("refactor", 0) == 1  # bid3 only
        assert summary["by_task_type"].get("security", 0) == 1  # bid2

    # -- test_boundary_summary_empty -------------------------------------

    async def test_boundary_summary_empty(self, cap_disc: CapabilityDiscovery):
        """Summary with no boundaries returns all zeros."""
        summary = await cap_disc.get_boundary_summary()
        assert summary["total"] == 0
        assert summary["unresolved"] == 0
        assert summary["resolved"] == 0
        assert summary["escalated"] == 0
        assert summary["retestable"] == 0
        assert summary["by_task_type"] == {}
        assert summary["agents_most_involved"] == {}


# ===========================================================================
# Module 3: ClawMCPServer
# ===========================================================================


class TestClawMCPServerSchemas:
    """Tests for tool schema definitions."""

    @pytest.fixture
    async def mcp_server(self, repository: Repository) -> ClawMCPServer:
        return ClawMCPServer(repository=repository)

    # -- test_tool_schemas_count -----------------------------------------

    async def test_tool_schemas_count(self, mcp_server: ClawMCPServer):
        """Tool schema count matches the registered MCP metadata."""
        schemas = mcp_server.get_tool_schemas()
        from claw.tools.schemas import TOOL_METADATA

        assert len(schemas) == len(TOOL_METADATA)

    # -- test_tool_schemas_structure -------------------------------------

    async def test_tool_schemas_structure(self, mcp_server: ClawMCPServer):
        """Each schema has name, description, and inputSchema keys."""
        schemas = mcp_server.get_tool_schemas()
        for schema in schemas:
            assert "name" in schema, f"Schema missing 'name': {schema}"
            assert "description" in schema, f"Schema missing 'description': {schema}"
            assert "inputSchema" in schema, f"Schema missing 'inputSchema': {schema}"
            assert isinstance(schema["name"], str)
            assert isinstance(schema["description"], str)
            assert isinstance(schema["inputSchema"], dict)
            assert schema["inputSchema"]["type"] == "object"
            assert "properties" in schema["inputSchema"]

    # -- test_tool_schemas_names -----------------------------------------

    async def test_tool_schemas_names(self, mcp_server: ClawMCPServer):
        """All expected tool names are present."""
        schemas = mcp_server.get_tool_schemas()
        names = {s["name"] for s in schemas}
        expected = {
            "claw_query_memory",
            "claw_store_finding",
            "claw_verify_claim",
            "claw_request_specialist",
            "claw_escalate",
            "claw_decompose_task",
            "claw_build_application_packet",
            "claw_get_run_connectome",
            "claw_trace_failure",
            "claw_promote_recipe",
            "claw_queue_mining_mission",
            "claw_request_specialist_packet",
            "claw_export_specialist_exchange",
            "claw_import_specialist_exchange",
            "claw_list_specialist_exchanges",
        }
        assert names == expected


class TestClawMCPServerDispatch:
    """Tests for dispatch_tool routing."""

    @pytest.fixture
    async def mcp_server(self, repository: Repository) -> ClawMCPServer:
        return ClawMCPServer(repository=repository)

    # -- test_dispatch_tool_unknown --------------------------------------

    async def test_dispatch_tool_unknown(self, mcp_server: ClawMCPServer):
        """Unknown tool name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown tool"):
            await mcp_server.dispatch_tool("nonexistent_tool", {})

    # -- test_dispatch_routes_correctly -----------------------------------

    async def test_dispatch_routes_correctly(self, mcp_server: ClawMCPServer):
        """Each registered tool name dispatches to the correct handler."""
        # Test claw_query_memory
        result = await mcp_server.dispatch_tool(
            "claw_query_memory", {"query": "test query"}
        )
        assert result["status"] == "ok"
        assert "results" in result

        # Test claw_verify_claim
        result = await mcp_server.dispatch_tool(
            "claw_verify_claim", {"claim": "code is tested"}
        )
        assert result["status"] == "ok"
        assert "verdict" in result

        # Test claw_request_specialist
        result = await mcp_server.dispatch_tool(
            "claw_request_specialist", {"task_description": "fix a security bug"}
        )
        assert result["status"] == "ok"
        assert "selected_agent" in result

        # Test claw_escalate
        result = await mcp_server.dispatch_tool(
            "claw_escalate", {"reason": "Cannot solve this problem"}
        )
        assert result["status"] == "ok"
        assert "escalation_id" in result


class TestClawMCPServerQueryMemory:
    """Tests for handle_query_memory."""

    @pytest.fixture
    async def mcp_server(self, repository: Repository) -> ClawMCPServer:
        return ClawMCPServer(repository=repository)

    # -- test_handle_query_memory_no_semantic -----------------------------

    async def test_handle_query_memory_no_semantic(self, mcp_server: ClawMCPServer):
        """Fallback path (no SemanticMemory) returns ok status with empty results."""
        result = await mcp_server.handle_query_memory(
            query="authentication pattern",
            limit=3,
        )
        assert result["status"] == "ok"
        assert result["query"] == "authentication pattern"
        assert isinstance(result["results"], list)
        assert result["result_count"] == len(result["results"])

    async def test_handle_query_memory_empty_query(self, mcp_server: ClawMCPServer):
        """Empty query string returns error."""
        result = await mcp_server.handle_query_memory(query="", limit=3)
        assert result["status"] == "error"
        assert "empty" in result["error"].lower()

    async def test_handle_query_memory_limit_clamped(self, mcp_server: ClawMCPServer):
        """Limit is clamped to [1, 20]."""
        # Should not error even with extreme values
        result = await mcp_server.handle_query_memory(query="test", limit=0)
        assert result["status"] == "ok"

        result = await mcp_server.handle_query_memory(query="test", limit=100)
        assert result["status"] == "ok"


class TestClawMCPServerStoreFinding:
    """Tests for handle_store_finding."""

    @pytest.fixture
    async def mcp_server(self, repository: Repository) -> ClawMCPServer:
        return ClawMCPServer(repository=repository)

    # -- test_handle_store_finding_no_semantic ----------------------------

    async def test_handle_store_finding_no_semantic(self, mcp_server: ClawMCPServer):
        """Fallback save (no SemanticMemory) stores to repository and returns ID."""
        result = await mcp_server.handle_store_finding(
            problem_description="API returns 500 on missing auth header",
            solution_code="if not request.headers.get('Authorization'):\n    raise HTTPException(401)",
            tags=["auth", "fastapi"],
            methodology_type="BUG_FIX",
        )
        assert result["status"] == "ok"
        assert "methodology_id" in result
        assert result["has_embedding"] is False
        assert result["lifecycle_state"] == "embryonic"

    async def test_handle_store_finding_empty_description(self, mcp_server: ClawMCPServer):
        """Empty problem_description returns error."""
        result = await mcp_server.handle_store_finding(
            problem_description="",
            solution_code="some code",
        )
        assert result["status"] == "error"

    async def test_handle_store_finding_empty_solution(self, mcp_server: ClawMCPServer):
        """Empty solution_code returns error."""
        result = await mcp_server.handle_store_finding(
            problem_description="some problem",
            solution_code="   ",
        )
        assert result["status"] == "error"

    async def test_handle_store_finding_invalid_type(self, mcp_server: ClawMCPServer):
        """Invalid methodology_type returns error."""
        result = await mcp_server.handle_store_finding(
            problem_description="test problem",
            solution_code="test code",
            methodology_type="INVALID_TYPE",
        )
        assert result["status"] == "error"
        assert "Invalid methodology_type" in result["error"]


class TestClawMCPServerVerifyClaim:
    """Tests for handle_verify_claim."""

    @pytest.fixture
    async def mcp_server(self, repository: Repository) -> ClawMCPServer:
        return ClawMCPServer(repository=repository)

    # -- test_handle_verify_claim_no_placeholders ------------------------

    async def test_handle_verify_claim_no_placeholders(self, mcp_server: ClawMCPServer):
        """Clean claim (no suspicious patterns) passes."""
        result = await mcp_server.handle_verify_claim(
            claim="The function validates all input parameters correctly."
        )
        assert result["status"] == "ok"
        assert result["verdict"] == "PASS"
        assert result["violation_count"] == 0

    # -- test_handle_verify_claim_with_placeholder -----------------------

    async def test_handle_verify_claim_with_placeholder(self, mcp_server: ClawMCPServer):
        """Claim text containing 'production ready' is flagged as unsubstantiated."""
        result = await mcp_server.handle_verify_claim(
            claim="The code is production ready and all tests pass."
        )
        assert result["status"] == "ok"
        # "production ready" triggers unsubstantiated flag
        analysis = result["claim_analysis"]
        assert analysis["unsubstantiated"] is True

    async def test_handle_verify_claim_empty(self, mcp_server: ClawMCPServer):
        """Empty claim returns error."""
        result = await mcp_server.handle_verify_claim(claim="")
        assert result["status"] == "error"

    async def test_handle_verify_claim_matched_patterns(self, mcp_server: ClawMCPServer):
        """Claims matching known claim patterns are detected."""
        result = await mcp_server.handle_verify_claim(
            claim="The bug is fixed and all tests pass."
        )
        assert result["status"] == "ok"
        analysis = result["claim_analysis"]
        assert analysis["claim_count"] >= 1
        # Should have matched at least "fixed" and "tests pass"
        phrases = {mc["phrase"] for mc in analysis["matched_claim_patterns"]}
        assert len(phrases) >= 1


class TestClawMCPServerRequestSpecialist:
    """Tests for handle_request_specialist."""

    @pytest.fixture
    async def mcp_server(self, repository: Repository) -> ClawMCPServer:
        return ClawMCPServer(repository=repository)

    # -- test_handle_request_specialist ----------------------------------

    async def test_handle_request_specialist(self, mcp_server: ClawMCPServer):
        """Returns agent recommendation via static fallback."""
        result = await mcp_server.handle_request_specialist(
            task_description="Analyze the security vulnerabilities in this codebase."
        )
        assert result["status"] == "ok"
        assert "selected_agent" in result
        assert result["routing_method"] == "static_fallback"
        assert result["inferred_task_type"] == "security"
        assert result["selected_agent"] == "claude"

    async def test_handle_request_specialist_with_preferred(self, mcp_server: ClawMCPServer):
        """Preferred agent is honored in static fallback mode."""
        result = await mcp_server.handle_request_specialist(
            task_description="Run a full repo comprehension analysis.",
            preferred_agent="grok",
        )
        assert result["status"] == "ok"
        assert result["selected_agent"] == "grok"
        assert result["preferred_agent"] == "grok"

    async def test_handle_request_specialist_empty_description(self, mcp_server: ClawMCPServer):
        """Empty task_description returns error."""
        result = await mcp_server.handle_request_specialist(task_description="")
        assert result["status"] == "error"

    async def test_handle_request_specialist_invalid_agent(self, mcp_server: ClawMCPServer):
        """Invalid preferred_agent returns error."""
        result = await mcp_server.handle_request_specialist(
            task_description="Fix a bug.",
            preferred_agent="invalid_agent",
        )
        assert result["status"] == "error"
        assert "Invalid preferred_agent" in result["error"]

    async def test_handle_request_specialist_inferred_types(self, mcp_server: ClawMCPServer):
        """Various descriptions infer correct task types."""
        cases = [
            ("Refactor the legacy code to clean it up", "refactoring"),
            ("Write unit tests for the API", "testing"),
            ("Check the npm dependency tree", "dependency_analysis"),
            ("Apply a quick fix for the off-by-one error", "quick_fix"),
            ("Do a web lookup for the OpenRouter rate limits", "web_lookup"),
        ]
        for description, expected_type in cases:
            result = await mcp_server.handle_request_specialist(
                task_description=description
            )
            assert result["status"] == "ok"
            assert result["inferred_task_type"] == expected_type, (
                f"For '{description}': expected '{expected_type}', "
                f"got '{result['inferred_task_type']}'"
            )


class TestClawMCPServerEscalate:
    """Tests for handle_escalate."""

    @pytest.fixture
    async def mcp_server(self, repository: Repository) -> ClawMCPServer:
        return ClawMCPServer(repository=repository)

    # -- test_handle_escalate --------------------------------------------

    async def test_handle_escalate(self, mcp_server: ClawMCPServer):
        """Returns acknowledgment with escalation ID."""
        result = await mcp_server.handle_escalate(
            reason="Cannot resolve circular dependency after 5 attempts.",
            context={"attempts": 5, "last_error": "circular import"},
            task_id="task-123",
        )
        assert result["status"] == "ok"
        assert "escalation_id" in result
        assert result["task_id"] == "task-123"
        assert "timestamp" in result
        assert "Escalation logged" in result["message"]

    async def test_handle_escalate_minimal(self, mcp_server: ClawMCPServer):
        """Escalation with only reason (no context, no task_id) works."""
        result = await mcp_server.handle_escalate(reason="Stuck on a hard problem.")
        assert result["status"] == "ok"
        assert result["escalation_id"] is not None
        assert result["task_id"] is None

    async def test_handle_escalate_empty_reason(self, mcp_server: ClawMCPServer):
        """Empty reason returns error."""
        result = await mcp_server.handle_escalate(reason="")
        assert result["status"] == "error"
        assert "empty" in result["error"].lower()
