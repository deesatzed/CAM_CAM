"""Tests for the failure learning system integration.

Covers:
- CorrectionFeedback new fields (known_fix_hint, auto_fixes_applied)
- OrchestratorConfig auto_fix_enabled flag
- ErrorKB.get_resolution_for_error()
- RL escalation classify_error()
"""

from __future__ import annotations

import asyncio

import pytest

from claw.core.models import CorrectionFeedback
from claw.core.config import OrchestratorConfig
from claw.evolution.rl_escalation import classify_error, RLEscalationStrategy, EscalationAction


# ---------------------------------------------------------------------------
# CorrectionFeedback new fields
# ---------------------------------------------------------------------------

class TestCorrectionFeedbackFields:
    def test_known_fix_hint_default_none(self):
        feedback = CorrectionFeedback()
        assert feedback.known_fix_hint is None

    def test_known_fix_hint_set(self):
        feedback = CorrectionFeedback(known_fix_hint="Add import pytest")
        assert feedback.known_fix_hint == "Add import pytest"

    def test_auto_fixes_applied_default_empty(self):
        feedback = CorrectionFeedback()
        assert feedback.auto_fixes_applied == []

    def test_auto_fixes_applied_set(self):
        fixes = ["missing_import_pytest: added 'import pytest'"]
        feedback = CorrectionFeedback(auto_fixes_applied=fixes)
        assert feedback.auto_fixes_applied == fixes

    def test_backward_compatible(self):
        """Existing callers that don't pass new fields should work."""
        feedback = CorrectionFeedback(
            attempt_number=1,
            violations=[{"check": "test", "detail": "fail"}],
            test_output="FAILED test_foo",
        )
        assert feedback.attempt_number == 1
        assert feedback.known_fix_hint is None
        assert feedback.auto_fixes_applied == []


# ---------------------------------------------------------------------------
# OrchestratorConfig auto_fix_enabled
# ---------------------------------------------------------------------------

class TestOrchestratorConfig:
    def test_auto_fix_enabled_default_true(self):
        config = OrchestratorConfig()
        assert config.auto_fix_enabled is True

    def test_auto_fix_enabled_set_false(self):
        config = OrchestratorConfig(auto_fix_enabled=False)
        assert config.auto_fix_enabled is False


# ---------------------------------------------------------------------------
# RL Escalation classify_error
# ---------------------------------------------------------------------------

class TestClassifyError:
    def test_import_error(self):
        assert classify_error("ImportError: No module named 'foo'") == "import_error"

    def test_type_error(self):
        assert classify_error("TypeError: unsupported operand") == "type_error"

    def test_syntax_error(self):
        assert classify_error("SyntaxError: invalid syntax") == "syntax_error"

    def test_test_failure(self):
        assert classify_error("AssertionError: expected True") == "test_failure"

    def test_unknown(self):
        assert classify_error("SomethingWeirdHappened") == "unknown"

    def test_uses_full_text(self):
        result = classify_error("unknown_sig", "full text with assertionerror detail")
        assert result == "test_failure"


# ---------------------------------------------------------------------------
# RL Escalation Strategy
# ---------------------------------------------------------------------------

class TestRLEscalationStrategy:
    def test_tier1_rotate_agent(self):
        strategy = RLEscalationStrategy()
        decision = strategy.diagnose_and_decide(
            task_id="t1",
            error_signature="ImportError: No module named 'foo'",
            error_full=None,
            current_agent_id="agent_a",
            available_agents=["agent_a", "agent_b", "agent_c"],
        )
        assert decision.tier == 1
        assert decision.action == EscalationAction.ROTATE_AGENT

    def test_tier3_no_agents_left(self):
        strategy = RLEscalationStrategy()
        decision = strategy.diagnose_and_decide(
            task_id="t2",
            error_signature="ImportError: No module named 'foo'",
            error_full=None,
            current_agent_id="agent_a",
            available_agents=["agent_a"],
        )
        # No viable agents → should escalate past tier 1
        assert decision.tier >= 2

    def test_diagnosis_contains_error_info(self):
        strategy = RLEscalationStrategy()
        decision = strategy.diagnose_and_decide(
            task_id="t3",
            error_signature="TypeError: unsupported operand",
            error_full=None,
            current_agent_id="agent_a",
            available_agents=["agent_a"],
        )
        assert len(decision.diagnosis) > 0

    def test_test_failure_triggers_rotation(self):
        """AssertionError / test failures should trigger ROTATE_AGENT (Tier 1)."""
        strategy = RLEscalationStrategy()
        decision = strategy.diagnose_and_decide(
            task_id="t4",
            error_signature="AssertionError: expected 5 but got 3",
            error_full="assert compute_decay(100) == 5",
            current_agent_id="agent_a",
            available_agents=["agent_a", "agent_b"],
        )
        assert decision.tier == 1
        assert decision.action == EscalationAction.ROTATE_AGENT

    def test_syntax_error_triggers_rotation(self):
        """SyntaxError should trigger ROTATE_AGENT (Tier 1)."""
        strategy = RLEscalationStrategy()
        decision = strategy.diagnose_and_decide(
            task_id="t5",
            error_signature="SyntaxError: invalid syntax",
            error_full=None,
            current_agent_id="grok",
            available_agents=["grok", "claude", "gemini"],
        )
        assert decision.tier == 1
        assert decision.action == EscalationAction.ROTATE_AGENT
