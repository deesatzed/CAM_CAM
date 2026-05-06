"""Tests for claw.planner — gap analysis and task generation from evaluation results.

Covers:
  1. analyze_gaps produces tasks from findings
  2. Severity to priority mapping (critical=10, high=8, medium=5, low=2)
  3. Category to task_type mapping
  4. Empty findings produce no tasks
  5. Priority ordering — security first, then testing, then architecture
  6. Agent recommendations match STATIC_ROUTING

NO mocks. All objects are real instances of production models.
"""

from __future__ import annotations

import pytest

from claw.core.models import Task, TaskStatus
from claw.dispatcher import DEFAULT_AGENT, STATIC_ROUTING
from claw.planner import (
    CATEGORY_TO_TASK_TYPE,
    DEFAULT_PRIORITY,
    DEFAULT_TASK_TYPE,
    SEVERITY_TO_PRIORITY,
    TASK_TYPE_TIER,
    EvaluationResult,
    Planner,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROJECT_ID = "proj-planner-test-001"


def _eval(
    prompt_name: str = "deepdive",
    findings: list[str] | None = None,
    severity: str = "medium",
    category: str = "",
) -> EvaluationResult:
    """Build a real EvaluationResult."""
    return EvaluationResult(
        prompt_name=prompt_name,
        findings=findings or [],
        severity=severity,
        category=category,
    )


# ============================================================================
# analyze_gaps — Core Task Generation
# ============================================================================


class TestAnalyzeGaps:
    """Planner.analyze_gaps converts evaluation findings into Tasks."""

    async def test_produces_tasks_from_findings(self):
        planner = Planner(PROJECT_ID)
        results = [
            _eval(
                prompt_name="deepdive",
                findings=["Missing error handling in auth module"],
                severity="high",
                category="security",
            ),
        ]
        tasks = await planner.analyze_gaps(results)
        assert len(tasks) == 1
        assert isinstance(tasks[0], Task)
        assert tasks[0].project_id == PROJECT_ID
        assert tasks[0].status == TaskStatus.PENDING
        assert "Missing error handling" in tasks[0].title or "Missing error handling" in tasks[0].description

    async def test_multiple_findings_produce_multiple_tasks(self):
        planner = Planner(PROJECT_ID)
        results = [
            _eval(
                findings=["Finding one", "Finding two", "Finding three"],
                severity="medium",
                category="testing",
            ),
        ]
        tasks = await planner.analyze_gaps(results)
        assert len(tasks) == 3

    async def test_multiple_eval_results(self):
        planner = Planner(PROJECT_ID)
        results = [
            _eval(findings=["A"], severity="high", category="security"),
            _eval(findings=["B", "C"], severity="low", category="docs"),
        ]
        tasks = await planner.analyze_gaps(results)
        assert len(tasks) == 3

    async def test_empty_findings_produce_no_tasks(self):
        planner = Planner(PROJECT_ID)
        results = [
            _eval(findings=[], severity="high", category="security"),
        ]
        tasks = await planner.analyze_gaps(results)
        assert len(tasks) == 0

    async def test_empty_results_list(self):
        planner = Planner(PROJECT_ID)
        tasks = await planner.analyze_gaps([])
        assert len(tasks) == 0

    async def test_mixed_empty_and_populated(self):
        planner = Planner(PROJECT_ID)
        results = [
            _eval(findings=[], severity="high", category="security"),
            _eval(findings=["Real finding"], severity="medium", category="testing"),
            _eval(findings=[], severity="low", category="docs"),
        ]
        tasks = await planner.analyze_gaps(results)
        assert len(tasks) == 1

    async def test_structured_json_finding_uses_summary_and_runbook_hints(self):
        planner = Planner(PROJECT_ID)
        results = [
            _eval(
                prompt_name="app__mitigen",
                findings=[
                    """{
                      "summary": "Add targeted CAM-Pulse assimilation task generation",
                      "recommendations": [
                        "Parse guide manifest rows into implementation tasks",
                        "Preserve source file and acceptance-test hints"
                      ],
                      "acceptance_checks": [
                        "pytest tests/test_camify.py tests/test_planner.py"
                      ]
                    }"""
                ],
                severity="medium",
                category="remediation_planning",
            )
        ]
        tasks = await planner.analyze_gaps(results)
        assert len(tasks) == 1
        assert tasks[0].title == "[Remediation_planning] Add targeted CAM-Pulse assimilation task generation"
        assert "{" not in tasks[0].title
        assert tasks[0].task_type == "architecture"
        assert tasks[0].execution_steps == [
            "Parse guide manifest rows into implementation tasks",
            "Preserve source file and acceptance-test hints",
        ]
        assert tasks[0].acceptance_checks == [
            "pytest tests/test_camify.py tests/test_planner.py"
        ]


# ============================================================================
# Severity to Priority Mapping
# ============================================================================


class TestSeverityToPriority:
    """SEVERITY_TO_PRIORITY: critical=10, high=8, medium=5, low=2."""

    async def test_critical_priority_is_10(self):
        planner = Planner(PROJECT_ID)
        results = [_eval(findings=["Critical bug"], severity="critical", category="security")]
        tasks = await planner.analyze_gaps(results)
        assert tasks[0].priority == 10

    async def test_high_priority_is_8(self):
        planner = Planner(PROJECT_ID)
        results = [_eval(findings=["High issue"], severity="high", category="testing")]
        tasks = await planner.analyze_gaps(results)
        assert tasks[0].priority == 8

    async def test_medium_priority_is_5(self):
        planner = Planner(PROJECT_ID)
        results = [_eval(findings=["Medium thing"], severity="medium", category="docs")]
        tasks = await planner.analyze_gaps(results)
        assert tasks[0].priority == 5

    async def test_low_priority_is_2(self):
        planner = Planner(PROJECT_ID)
        results = [_eval(findings=["Minor issue"], severity="low", category="docs")]
        tasks = await planner.analyze_gaps(results)
        assert tasks[0].priority == 2

    async def test_unknown_severity_defaults_to_5(self):
        planner = Planner(PROJECT_ID)
        results = [_eval(findings=["Unknown sev"], severity="banana", category="docs")]
        tasks = await planner.analyze_gaps(results)
        assert tasks[0].priority == DEFAULT_PRIORITY

    def test_severity_map_values_directly(self):
        assert SEVERITY_TO_PRIORITY["critical"] == 10
        assert SEVERITY_TO_PRIORITY["high"] == 8
        assert SEVERITY_TO_PRIORITY["medium"] == 5
        assert SEVERITY_TO_PRIORITY["low"] == 2


# ============================================================================
# Category to task_type Mapping
# ============================================================================


class TestCategoryToTaskType:
    """CATEGORY_TO_TASK_TYPE maps evaluation categories to routing types."""

    async def test_security_category(self):
        planner = Planner(PROJECT_ID)
        results = [_eval(findings=["SQL injection risk"], severity="high", category="security")]
        tasks = await planner.analyze_gaps(results)
        assert tasks[0].task_type == "security"

    async def test_testing_category(self):
        planner = Planner(PROJECT_ID)
        results = [_eval(findings=["Low coverage"], severity="medium", category="testing")]
        tasks = await planner.analyze_gaps(results)
        assert tasks[0].task_type == "testing"

    async def test_docs_category(self):
        planner = Planner(PROJECT_ID)
        results = [_eval(findings=["Missing docs"], severity="low", category="docs")]
        tasks = await planner.analyze_gaps(results)
        assert tasks[0].task_type == "documentation"

    async def test_architecture_category(self):
        planner = Planner(PROJECT_ID)
        results = [_eval(findings=["Bad arch"], severity="high", category="architecture")]
        tasks = await planner.analyze_gaps(results)
        assert tasks[0].task_type == "architecture"

    async def test_bug_category(self):
        planner = Planner(PROJECT_ID)
        results = [_eval(findings=["Crash on startup"], severity="high", category="bug")]
        tasks = await planner.analyze_gaps(results)
        assert tasks[0].task_type == "bug_fix"

    async def test_performance_maps_to_refactoring(self):
        planner = Planner(PROJECT_ID)
        results = [_eval(findings=["Slow query"], severity="medium", category="performance")]
        tasks = await planner.analyze_gaps(results)
        assert tasks[0].task_type == "refactoring"

    async def test_dependency_category(self):
        planner = Planner(PROJECT_ID)
        results = [_eval(findings=["Outdated dep"], severity="medium", category="dependency")]
        tasks = await planner.analyze_gaps(results)
        assert tasks[0].task_type == "dependency_analysis"

    async def test_empty_category_defaults_to_analysis(self):
        planner = Planner(PROJECT_ID)
        results = [_eval(findings=["Some finding"], severity="medium", category="")]
        tasks = await planner.analyze_gaps(results)
        assert tasks[0].task_type == DEFAULT_TASK_TYPE

    async def test_unknown_category_defaults_to_analysis(self):
        planner = Planner(PROJECT_ID)
        results = [_eval(findings=["Some finding"], severity="medium", category="banana_category")]
        tasks = await planner.analyze_gaps(results)
        assert tasks[0].task_type == DEFAULT_TASK_TYPE

    def test_category_map_values_directly(self):
        assert CATEGORY_TO_TASK_TYPE["docs"] == "documentation"
        assert CATEGORY_TO_TASK_TYPE["security"] == "security"
        assert CATEGORY_TO_TASK_TYPE["testing"] == "testing"
        assert CATEGORY_TO_TASK_TYPE["architecture"] == "architecture"
        assert CATEGORY_TO_TASK_TYPE["bug"] == "bug_fix"


# ============================================================================
# Priority Ordering — Security First, Then Testing, Then Architecture
# ============================================================================


class TestPriorityOrdering:
    """Tasks are sorted by type tier then priority, respecting dependency order."""

    async def test_security_before_testing_before_architecture(self):
        planner = Planner(PROJECT_ID)
        results = [
            _eval(findings=["Arch issue"], severity="high", category="architecture"),
            _eval(findings=["Security vuln"], severity="critical", category="security"),
            _eval(findings=["Test gap"], severity="high", category="testing"),
        ]
        tasks = await planner.analyze_gaps(results)

        # Task types in output order
        type_order = [t.task_type for t in tasks]

        # security tier=0, testing tier=1, architecture tier=2
        sec_idx = type_order.index("security")
        test_idx = type_order.index("testing")
        arch_idx = type_order.index("architecture")

        assert sec_idx < test_idx, f"security @{sec_idx} should come before testing @{test_idx}"
        assert test_idx < arch_idx, f"testing @{test_idx} should come before architecture @{arch_idx}"

    async def test_higher_priority_before_lower_within_same_tier(self):
        planner = Planner(PROJECT_ID)
        results = [
            _eval(findings=["Low priority bug fix"], severity="low", category="bug"),
            _eval(findings=["High priority bug fix"], severity="high", category="bug"),
        ]
        tasks = await planner.analyze_gaps(results)

        # Both are bug_fix (tier 3), high priority (8) should come before low (2)
        assert tasks[0].priority > tasks[1].priority

    async def test_documentation_comes_last(self):
        planner = Planner(PROJECT_ID)
        results = [
            _eval(findings=["Doc gap"], severity="low", category="docs"),
            _eval(findings=["Security fix"], severity="critical", category="security"),
            _eval(findings=["Testing gap"], severity="high", category="testing"),
        ]
        tasks = await planner.analyze_gaps(results)
        type_order = [t.task_type for t in tasks]

        # documentation tier=4, should be last
        doc_idx = type_order.index("documentation")
        assert doc_idx == len(tasks) - 1


# ============================================================================
# Agent Recommendations Match STATIC_ROUTING
# ============================================================================


class TestAgentRecommendations:
    """Planner sets recommended_agent from the same STATIC_ROUTING table."""

    async def test_security_task_recommends_claude(self):
        planner = Planner(PROJECT_ID)
        results = [_eval(findings=["Vuln found"], severity="high", category="security")]
        tasks = await planner.analyze_gaps(results)
        assert tasks[0].recommended_agent == STATIC_ROUTING.get("security", DEFAULT_AGENT)

    async def test_testing_task_recommends_codex(self):
        planner = Planner(PROJECT_ID)
        results = [_eval(findings=["Low coverage"], severity="medium", category="testing")]
        tasks = await planner.analyze_gaps(results)
        assert tasks[0].recommended_agent == STATIC_ROUTING.get("testing", DEFAULT_AGENT)

    async def test_dependency_task_recommends_gemini(self):
        planner = Planner(PROJECT_ID)
        results = [_eval(findings=["Outdated deps"], severity="medium", category="dependency")]
        tasks = await planner.analyze_gaps(results)
        assert tasks[0].recommended_agent == STATIC_ROUTING.get("dependency_analysis", DEFAULT_AGENT)

    async def test_bug_fix_recommends_grok(self):
        planner = Planner(PROJECT_ID)
        results = [_eval(findings=["Crash bug"], severity="high", category="bug")]
        tasks = await planner.analyze_gaps(results)
        assert tasks[0].recommended_agent == STATIC_ROUTING.get("bug_fix", DEFAULT_AGENT)

    async def test_unknown_category_recommends_default(self):
        planner = Planner(PROJECT_ID)
        results = [_eval(findings=["Something"], severity="medium", category="")]
        tasks = await planner.analyze_gaps(results)
        # Empty category -> "analysis" task_type -> claude (from STATIC_ROUTING)
        expected = STATIC_ROUTING.get("analysis", DEFAULT_AGENT)
        assert tasks[0].recommended_agent == expected


# ============================================================================
# Planning Summary
# ============================================================================


class TestPlanningSummary:
    """Planner.get_planning_summary produces human-readable output."""

    async def test_summary_for_empty_tasks(self):
        planner = Planner(PROJECT_ID)
        summary = planner.get_planning_summary([])
        assert "No tasks generated" in summary

    async def test_summary_contains_project_id(self):
        planner = Planner(PROJECT_ID)
        task = Task(
            project_id=PROJECT_ID,
            title="Test task",
            description="desc",
            task_type="testing",
            priority=8,
            recommended_agent="codex",
        )
        summary = planner.get_planning_summary([task])
        assert PROJECT_ID in summary
        assert "testing" in summary
        assert "Total tasks: 1" in summary
