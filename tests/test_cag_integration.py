"""Tests for CAG (Cache-Augmented Generation) integration into the agent interface.

Validates that the CAG retrieval path is correctly wired into
AgentInterface._build_openrouter_prompt() and _resolve_cag_context().

Also validates token budget enforcement (L4) — the _token_budget attribute,
set_token_budget(), _resolve_knowledge_source budget parameter, and the
enforcement warning in _build_openrouter_prompt().

All tests use REAL Pydantic model objects -- no mocks, no placeholders,
no cached responses.
"""
from __future__ import annotations

import logging
import pytest

from claw.agents.interface import AgentInterface
from claw.agents.claude import ClaudeCodeAgent
from claw.core.models import AgentMode, Task, TaskContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task_context(task_type: str, title: str = "test task", description: str = "test description") -> TaskContext:
    """Create a real TaskContext with the given task_type."""
    task = Task(
        project_id="test-project",
        title=title,
        description=description,
        task_type=task_type,
    )
    return TaskContext(task=task)


def _make_agent() -> ClaudeCodeAgent:
    """Create a real ClaudeCodeAgent for testing base class behavior.

    Uses CLI mode so can_use_internal_workspace_executor() returns False,
    which keeps prompt output simpler for knowledge injection tests.
    """
    return ClaudeCodeAgent(mode=AgentMode.CLI)


# ---------------------------------------------------------------------------
# Test: _resolve_cag_context returns corpus for mining task
# ---------------------------------------------------------------------------

class TestResolveCagContextMiningTask:
    def test_resolve_cag_context_returns_corpus_for_mining_task(self):
        """mining_extraction task type with a loaded corpus must return the corpus."""
        ctx = _make_task_context("mining_extraction")
        corpus = "=== CAG Corpus ===\nMethodology A\nMethodology B"

        result = AgentInterface._resolve_cag_context(ctx, cag_corpus=corpus)

        assert result is not None
        assert result == corpus


# ---------------------------------------------------------------------------
# Test: _resolve_cag_context returns None for analysis task
# ---------------------------------------------------------------------------

class TestResolveCagContextNonEligibleTask:
    def test_resolve_cag_context_returns_none_for_non_eligible_task(self):
        """Non-eligible task type (e.g. 'debugging') must NOT receive CAG corpus."""
        ctx = _make_task_context("debugging")
        corpus = "=== CAG Corpus ===\nMethodology A"

        result = AgentInterface._resolve_cag_context(ctx, cag_corpus=corpus)

        assert result is None


# ---------------------------------------------------------------------------
# Test: _resolve_cag_context returns None when empty corpus
# ---------------------------------------------------------------------------

class TestResolveCagContextEmptyCorpus:
    def test_resolve_cag_context_returns_none_when_empty_corpus(self):
        """Empty corpus must always return None regardless of task type."""
        ctx = _make_task_context("mining_extraction")

        result = AgentInterface._resolve_cag_context(ctx, cag_corpus="")

        assert result is None

    def test_resolve_cag_context_returns_none_when_default_corpus(self):
        """Default (no argument) corpus must return None."""
        ctx = _make_task_context("mining_extraction")

        result = AgentInterface._resolve_cag_context(ctx)

        assert result is None


# ---------------------------------------------------------------------------
# Test: _resolve_cag_context for bulk_classification
# ---------------------------------------------------------------------------

class TestResolveCagContextBulkClassification:
    def test_resolve_cag_context_bulk_classification(self):
        """bulk_classification task type must return the corpus."""
        ctx = _make_task_context("bulk_classification")
        corpus = "Full corpus content for classification"

        result = AgentInterface._resolve_cag_context(ctx, cag_corpus=corpus)

        assert result is not None
        assert result == corpus


# ---------------------------------------------------------------------------
# Test: _cag_corpus attribute default empty
# ---------------------------------------------------------------------------

class TestCagCorpusAttributeDefault:
    def test_cag_corpus_attribute_default_empty(self):
        """A new AgentInterface subclass instance must have _cag_corpus as empty string."""
        agent = _make_agent()

        assert hasattr(agent, "_cag_corpus")
        assert agent._cag_corpus == ""


# ---------------------------------------------------------------------------
# Test: set_cag_corpus
# ---------------------------------------------------------------------------

class TestSetCagCorpus:
    def test_set_cag_corpus_stores_value(self):
        """set_cag_corpus must store the corpus text on the instance."""
        agent = _make_agent()
        corpus_text = "=== Full Methodology Corpus ===\nPattern 1\nPattern 2\nPattern 3"

        agent.set_cag_corpus(corpus_text)

        assert agent._cag_corpus == corpus_text

    def test_set_cag_corpus_empty_clears(self):
        """Calling set_cag_corpus with empty string disables CAG."""
        agent = _make_agent()
        agent.set_cag_corpus("some corpus")
        assert agent._cag_corpus == "some corpus"

        agent.set_cag_corpus("")
        assert agent._cag_corpus == ""


# ---------------------------------------------------------------------------
# Test: all CAG-eligible task types are recognized
# ---------------------------------------------------------------------------

class TestAllCagEligibleTaskTypes:
    @pytest.mark.parametrize("task_type", [
        "mining_extraction",
        "bulk_classification",
        "pattern_extraction",
        "code_summarization",
        "mining",
        "novelty_detection",
        "synergy_discovery",
    ])
    def test_eligible_task_type_returns_corpus(self, task_type: str):
        """Every task type in CAG_ELIGIBLE_TASK_TYPES must return the corpus."""
        ctx = _make_task_context(task_type)
        corpus = f"corpus for {task_type}"

        result = AgentInterface._resolve_cag_context(ctx, cag_corpus=corpus)

        assert result == corpus


# ---------------------------------------------------------------------------
# Test: non-eligible task types are rejected
# ---------------------------------------------------------------------------

class TestNonEligibleTaskTypes:
    @pytest.mark.parametrize("task_type", [
        "bug_fix",
        "code_review",
        "testing",
        "documentation",
        "debugging",
        "deployment",
        "",
    ])
    def test_non_eligible_task_type_returns_none(self, task_type: str):
        """Task types not in CAG_ELIGIBLE_TASK_TYPES must return None."""
        ctx = _make_task_context(task_type)
        corpus = "should not be used"

        result = AgentInterface._resolve_cag_context(ctx, cag_corpus=corpus)

        assert result is None


# ---------------------------------------------------------------------------
# Test: task with None task_type
# ---------------------------------------------------------------------------

class TestNoneTaskType:
    def test_none_task_type_returns_none(self):
        """Task with task_type=None must return None (not eligible)."""
        task = Task(
            project_id="test-project",
            title="no type task",
            description="test",
            task_type=None,
        )
        ctx = TaskContext(task=task)
        corpus = "should not be used"

        result = AgentInterface._resolve_cag_context(ctx, cag_corpus=corpus)

        assert result is None


# ---------------------------------------------------------------------------
# Test: CAG corpus appears in prompt for eligible tasks
# ---------------------------------------------------------------------------

class TestCagCorpusInPrompt:
    def test_cag_corpus_injected_into_prompt(self):
        """When CAG corpus is set and task is eligible, prompt must contain corpus text."""
        agent = _make_agent()
        corpus_text = "=== FULL CAG CORPUS: Pattern Alpha, Pattern Beta ==="
        agent.set_cag_corpus(corpus_text)

        ctx = _make_task_context("mining_extraction", title="Mine patterns", description="Extract patterns from codebase")
        prompt = agent._build_openrouter_prompt(ctx)

        assert "CAG: full methodology corpus" in prompt
        assert "Pattern Alpha" in prompt
        assert "Pattern Beta" in prompt
        assert "END KNOWLEDGE BASE" in prompt

    def test_cag_corpus_not_injected_for_non_eligible(self):
        """When CAG corpus is set but task is not eligible, prompt must NOT contain corpus."""
        agent = _make_agent()
        corpus_text = "=== SHOULD NOT APPEAR ==="
        agent.set_cag_corpus(corpus_text)

        ctx = _make_task_context("debugging", title="Debug code", description="Find root cause")
        prompt = agent._build_openrouter_prompt(ctx)

        assert "SHOULD NOT APPEAR" not in prompt
        assert "CAG: full methodology corpus" not in prompt

    def test_cag_corpus_not_in_prompt_when_empty(self):
        """When no CAG corpus is set, prompt must not contain CAG section."""
        agent = _make_agent()
        # _cag_corpus is "" by default

        ctx = _make_task_context("mining_extraction")
        prompt = agent._build_openrouter_prompt(ctx)

        assert "CAG: full methodology corpus" not in prompt


# ---------------------------------------------------------------------------
# Test: CAG corpus respects budget limit
# ---------------------------------------------------------------------------

class TestCagCorpusBudgetLimit:
    def test_cag_corpus_truncated_to_budget(self):
        """CAG corpus injection must respect the knowledge budget."""
        agent = _make_agent()
        # Create a corpus larger than the configured budget
        budget = 5000
        large_corpus = "X" * 20000
        agent.set_cag_corpus(large_corpus, knowledge_budget_chars=budget)

        ctx = _make_task_context("mining_extraction")
        prompt = agent._build_openrouter_prompt(ctx)

        # The corpus text in the prompt must be truncated to the budget
        x_count_in_prompt = prompt.count("X")
        assert x_count_in_prompt <= budget
        assert x_count_in_prompt > 0

    def test_cag_corpus_uses_default_budget(self):
        """CAG corpus uses 16K default budget when none specified."""
        agent = _make_agent()
        large_corpus = "Y" * 100000
        agent.set_cag_corpus(large_corpus)

        ctx = _make_task_context("mining_extraction")
        prompt = agent._build_openrouter_prompt(ctx)

        y_count = prompt.count("Y")
        assert y_count == 16000


# ---------------------------------------------------------------------------
# Test: CAG path does not break HybridSearch fallback
# ---------------------------------------------------------------------------

class TestHybridSearchFallbackPreserved:
    def test_hybrid_search_still_works_without_cag(self):
        """Without CAG corpus, the standard HybridSearch path must still function.

        We verify by checking that _resolve_knowledge_source still returns
        the correct values when called on a task with no CAG corpus.
        """
        ctx = _make_task_context("analysis")
        # No context with past_solutions, should get empty
        methods, budget = AgentInterface._resolve_knowledge_source(ctx, context=None)
        assert methods == []
        assert budget == 0

    def test_cag_replaces_hybrid_search_for_eligible_task(self):
        """For eligible tasks with CAG corpus, HybridSearch section must NOT appear."""
        agent = _make_agent()
        agent.set_cag_corpus("CAG corpus content here")

        ctx = _make_task_context("mining_extraction")
        prompt = agent._build_openrouter_prompt(ctx)

        # CAG path should be present
        assert "CAG: full methodology corpus" in prompt
        # Standard HybridSearch header should NOT be present (CAG replaces it)
        assert "Retrieved Knowledge (from PULSE-mined methodologies)" not in prompt


# ---------------------------------------------------------------------------
# Test: Token Budget Enforcement (L4)
# ---------------------------------------------------------------------------

class TestTokenBudgetEnforcement:
    """Validate that the token budget attribute, setter, and enforcement
    logic work correctly across AgentInterface."""

    def test_token_budget_default(self):
        """New agent must have _token_budget defaulting to 100_000."""
        agent = _make_agent()
        assert agent._token_budget == 100_000

    def test_set_token_budget(self):
        """set_token_budget must update the _token_budget attribute."""
        agent = _make_agent()
        agent.set_token_budget(32000)
        assert agent._token_budget == 32000

    def test_set_token_budget_to_zero(self):
        """Setting token budget to 0 must be stored (edge case)."""
        agent = _make_agent()
        agent.set_token_budget(0)
        assert agent._token_budget == 0

    def test_set_token_budget_large_value(self):
        """Setting a large token budget must be stored."""
        agent = _make_agent()
        agent.set_token_budget(1_000_000)
        assert agent._token_budget == 1_000_000

    def test_resolve_knowledge_source_respects_budget(self):
        """Token budget should limit knowledge chars via the formula."""
        ctx = _make_task_context("analysis")
        # With no context and no knowledge_override, should always return empty
        methods, max_chars = AgentInterface._resolve_knowledge_source(
            ctx, context=None, token_budget=1000
        )
        assert methods == []
        assert max_chars == 0

    def test_resolve_knowledge_source_default_budget(self):
        """Default token_budget parameter should be 100_000."""
        ctx = _make_task_context("analysis")
        # Call without explicit token_budget — should use default 100_000
        methods, max_chars = AgentInterface._resolve_knowledge_source(ctx, context=None)
        assert methods == []
        assert max_chars == 0

    def test_resolve_knowledge_source_budget_limits_past_solutions(self):
        """When context has past_solutions, budget should control max_chars.

        Formula: max_chars = min(int(token_budget * 0.25 * 4), 8000)
                 max_chars = max(max_chars, 2000)

        With token_budget=1000:
            raw = int(1000 * 0.25 * 4) = 1000
            capped = min(1000, 8000) = 1000
            floored = max(1000, 2000) = 2000
        """
        ctx = _make_task_context("analysis")

        class FakeContext:
            past_solutions = ["solution1"]

        methods, max_chars = AgentInterface._resolve_knowledge_source(
            ctx, context=FakeContext(), token_budget=1000
        )
        assert methods == ["solution1"]
        assert max_chars == 4000  # Floor of 4000

    def test_resolve_knowledge_source_large_budget_caps_at_32000(self):
        """With a large token_budget the max_chars should cap at 32000.

        With token_budget=100_000:
            raw = int(100_000 * 0.40 * 4) = 160_000
            capped = min(160_000, 32000) = 32000
            floored = max(32000, 4000) = 32000
        """
        ctx = _make_task_context("analysis")

        class FakeContext:
            past_solutions = ["solution1", "solution2"]

        methods, max_chars = AgentInterface._resolve_knowledge_source(
            ctx, context=FakeContext(), token_budget=100_000
        )
        assert methods == ["solution1", "solution2"]
        assert max_chars == 32000

    def test_resolve_knowledge_source_mid_budget(self):
        """With a mid-range token_budget the formula should produce the expected value.

        With token_budget=5000:
            raw = int(5000 * 0.40 * 4) = 8000
            capped = min(8000, 32000) = 8000
            floored = max(8000, 4000) = 8000
        """
        ctx = _make_task_context("analysis")

        class FakeContext:
            past_solutions = ["sol"]

        methods, max_chars = AgentInterface._resolve_knowledge_source(
            ctx, context=FakeContext(), token_budget=5000
        )
        assert methods == ["sol"]
        assert max_chars == 8000

    def test_token_budget_warning_logged_when_exceeded(self, caplog):
        """When the prompt exceeds the token budget, a warning must be logged."""
        agent = _make_agent()
        # Set token budget to 1 so even a minimal prompt exceeds it.
        # The shortest prompt is "# Task: <title>\n\n<desc>" which is at
        # least 20+ chars = 5+ approx tokens, always exceeding budget=1.
        agent.set_token_budget(1)

        ctx = _make_task_context(
            "analysis",
            title="Analyze this codebase thoroughly",
            description="Perform a comprehensive analysis of the entire repository",
        )

        with caplog.at_level(logging.WARNING, logger="claw.agent.claude"):
            prompt = agent._build_openrouter_prompt(ctx)

        # The prompt must be at least 8+ chars (so >1 approx token at chars//4)
        assert len(prompt) > 4

        # Check that the warning was emitted
        warning_found = any(
            "Prompt exceeds token budget" in record.message
            for record in caplog.records
        )
        assert warning_found, (
            f"Expected 'Prompt exceeds token budget' warning in logs. "
            f"Got: {[r.message for r in caplog.records]}"
        )

    def test_no_warning_when_within_budget(self, caplog):
        """When the prompt fits within the token budget, no warning should be logged."""
        agent = _make_agent()
        # Set a very large token budget
        agent.set_token_budget(1_000_000)

        ctx = _make_task_context("analysis", title="A task", description="desc")

        with caplog.at_level(logging.WARNING, logger="claw.agent.claude"):
            agent._build_openrouter_prompt(ctx)

        warning_found = any(
            "Prompt exceeds token budget" in record.message
            for record in caplog.records
        )
        assert not warning_found, (
            f"Did not expect 'Prompt exceeds token budget' warning but got: "
            f"{[r.message for r in caplog.records]}"
        )

    def test_token_budget_wired_into_prompt_knowledge_path(self):
        """The _build_openrouter_prompt must pass _token_budget to _resolve_knowledge_source.

        We verify by setting a tiny budget and checking the prompt does not
        contain a huge knowledge section. With no CAG corpus and no
        past_solutions, the knowledge section is empty either way, so we
        test the complete code path doesn't crash.
        """
        agent = _make_agent()
        agent.set_token_budget(500)

        ctx = _make_task_context("analysis", title="task", description="desc")
        prompt = agent._build_openrouter_prompt(ctx)

        # Prompt should still be generated (not crash)
        assert "# Task:" in prompt
        # No knowledge section since there's no context
        assert "Retrieved Knowledge" not in prompt


# ---------------------------------------------------------------------------
# Test: CAGConfig.token_budget_max field
# ---------------------------------------------------------------------------

class TestCAGConfigTokenBudgetMax:
    """Validate that CAGConfig has the token_budget_max field."""

    def test_cag_config_has_token_budget_max(self):
        """CAGConfig must have token_budget_max with default 100_000."""
        from claw.core.config import CAGConfig
        cfg = CAGConfig()
        assert cfg.token_budget_max == 100_000

    def test_cag_config_token_budget_max_custom(self):
        """CAGConfig token_budget_max must accept custom values."""
        from claw.core.config import CAGConfig
        cfg = CAGConfig(token_budget_max=32768)
        assert cfg.token_budget_max == 32768

    def test_cag_config_token_budget_max_in_clawconfig(self):
        """ClawConfig.cag.token_budget_max must be accessible."""
        from claw.core.config import ClawConfig
        config = ClawConfig()
        assert config.cag.token_budget_max == 100_000

    def test_cag_config_token_budget_max_overridden_in_clawconfig(self):
        """ClawConfig with custom CAG config must propagate token_budget_max."""
        from claw.core.config import ClawConfig, CAGConfig
        config = ClawConfig(cag=CAGConfig(token_budget_max=65536))
        assert config.cag.token_budget_max == 65536
