"""Planner — gap analysis and task generation from evaluation results.

Takes raw evaluation findings (from the 17-prompt battery) and produces a
sorted, dependency-aware list of Tasks ready for the Dispatcher. The Planner
sits between the Evaluator and the Dispatcher in the claw cycle:

    Evaluator -> Planner -> Dispatcher -> Agent -> Verifier

Each evaluation prompt produces an ``EvaluationResult`` with findings.
The Planner:

1. Converts each finding into a ``Task`` (with title, description, priority,
   task_type, and recommended_agent).
2. Detects dependency relationships between tasks (e.g., security before
   features, infrastructure before implementation).
3. Applies topological priority ordering so the Dispatcher receives tasks
   in a safe execution order.

The agent recommendation uses the same ``STATIC_ROUTING`` table that the
Dispatcher uses as starting priors. This ensures consistency between the
Planner's recommendation and the Dispatcher's fallback routing.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from claw.core.models import ComplexityTier, Task, TaskStatus
from claw.dispatcher import DEFAULT_AGENT, STATIC_ROUTING

logger = logging.getLogger("claw.planner")


# ---------------------------------------------------------------------------
# Evaluation result model
# ---------------------------------------------------------------------------

class EvaluationResult(BaseModel):
    """Result from a single evaluation prompt.

    Each prompt in the 17-prompt battery (deepdive, driftx, claim-gate, etc.)
    produces one or more findings. The evaluator packages these into
    EvaluationResult instances that the Planner consumes.
    """

    prompt_name: str
    findings: list[str] = Field(default_factory=list)
    severity: str = "medium"  # low, medium, high, critical
    category: str = ""  # docs, testing, security, performance, architecture, etc.
    raw_output: str = ""


# ---------------------------------------------------------------------------
# Category -> task_type mapping
# ---------------------------------------------------------------------------

CATEGORY_TO_TASK_TYPE: dict[str, str] = {
    # Evaluation battery phases
    "orientation": "analysis",
    "deep_analysis": "analysis",
    "truth_verification": "testing",
    "quality_assessment": "testing",
    "remediation_planning": "architecture",
    "additional": "analysis",
    # Documentation
    "docs": "documentation",
    "documentation": "documentation",
    # Testing
    "testing": "testing",
    "tests": "testing",
    "coverage": "testing",
    # Security
    "security": "security",
    "auth": "security",
    # Performance / Refactoring
    "performance": "refactoring",
    "optimization": "refactoring",
    # Architecture
    "architecture": "architecture",
    "design": "architecture",
    # Dependency analysis
    "dependency": "dependency_analysis",
    "deps": "dependency_analysis",
    # Bug fixes
    "bug": "bug_fix",
    "error": "bug_fix",
    "fix": "bug_fix",
    # Features / General analysis
    "feature": "analysis",
    "enhancement": "analysis",
    # Code quality / style — suitable for local inference (low-judgment)
    "code_quality": "code_summarization",
    "code_style": "code_summarization",
    "naming": "code_summarization",
    "formatting": "code_summarization",
    # Mining / extraction — routes to local agent
    "mining": "mining_extraction",
    "extraction": "pattern_extraction",
    "classification": "bulk_classification",
    "pattern": "pattern_extraction",
}

DEFAULT_TASK_TYPE = "analysis"


# ---------------------------------------------------------------------------
# Severity -> priority mapping
# ---------------------------------------------------------------------------

SEVERITY_TO_PRIORITY: dict[str, int] = {
    "critical": 10,
    "high": 8,
    "medium": 5,
    "low": 2,
}

DEFAULT_PRIORITY = 5


# ---------------------------------------------------------------------------
# Task-type ordering tiers for prioritization
# ---------------------------------------------------------------------------

# Lower tier number = higher scheduling priority (runs first).
TASK_TYPE_TIER: dict[str, int] = {
    "security": 0,
    "testing": 1,
    "ci_cd": 1,
    "architecture": 2,
    "dependency_analysis": 2,
    "refactoring": 3,
    "bug_fix": 3,
    "documentation": 4,
    "analysis": 5,
}

DEFAULT_TIER = 5


class NormalizedFinding(BaseModel):
    """Planner-facing shape extracted from a raw evaluation finding."""

    title_text: str
    description_text: str
    execution_steps: list[str] = Field(default_factory=list)
    acceptance_checks: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Dependency rules — which task types must complete before others
# ---------------------------------------------------------------------------

# Keys are task types that should be done BEFORE the task types in their value
# list. For example, "security" tasks should be done before "analysis"
# (feature) tasks.
DEPENDENCY_ORDERING: dict[str, list[str]] = {
    "security": ["analysis", "refactoring", "bug_fix", "documentation"],
    "testing": ["refactoring", "analysis"],
    "architecture": ["analysis", "refactoring", "bug_fix"],
    "ci_cd": ["testing"],
    "dependency_analysis": ["refactoring", "analysis"],
}


# ---------------------------------------------------------------------------
# Complexity estimation heuristics
# ---------------------------------------------------------------------------

def _estimate_complexity(finding: str) -> ComplexityTier:
    """Estimate task complexity from the finding text.

    Uses keyword heuristics to classify findings into complexity tiers.
    This is a rough heuristic — the Dispatcher and agents will refine
    complexity estimates during execution.

    Args:
        finding: The raw finding text from an evaluation prompt.

    Returns:
        A ComplexityTier enum value.
    """
    finding_lower = finding.lower()
    word_count = len(finding_lower.split())

    # Very short findings tend to be trivial (typos, small config changes)
    if word_count < 10:
        return ComplexityTier.TRIVIAL

    # Keywords that suggest high complexity
    high_complexity_signals = [
        "refactor entire", "redesign", "rewrite", "migrate",
        "breaking change", "cross-cutting", "system-wide",
        "database schema", "api contract",
    ]
    for signal in high_complexity_signals:
        if signal in finding_lower:
            return ComplexityTier.HIGH

    # Keywords that suggest very high complexity
    very_high_signals = [
        "fundamental redesign", "complete rewrite", "architecture overhaul",
        "data migration", "backwards incompatible",
    ]
    for signal in very_high_signals:
        if signal in finding_lower:
            return ComplexityTier.VERY_HIGH

    # Keywords that suggest low complexity
    low_complexity_signals = [
        "typo", "rename", "add comment", "update readme",
        "fix import", "unused import", "missing docstring",
    ]
    for signal in low_complexity_signals:
        if signal in finding_lower:
            return ComplexityTier.LOW

    # Default to medium
    return ComplexityTier.MEDIUM


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

class Planner:
    """Gap analysis and task generation from evaluation results.

    The Planner is the bridge between the Evaluator (which identifies problems)
    and the Dispatcher (which assigns agents to fix them). It performs three
    core functions:

    1. **Gap Analysis** — converts raw evaluation findings into structured
       Task objects with appropriate metadata for routing.
    2. **Dependency Detection** — identifies ordering constraints between
       tasks (e.g., security fixes before feature work).
    3. **Prioritization** — sorts tasks respecting both priority scores
       and dependency ordering for safe execution.

    Args:
        project_id: The UUID of the project being planned for. All generated
                    tasks will reference this project.
        repository: Optional Repository instance for persisting tasks to the
                    database. If None, tasks are generated in-memory only.
    """

    def __init__(self, project_id: str, repository: Optional[Any] = None):
        self.project_id = project_id
        self.repository = repository

        logger.info(
            "Planner initialized: project_id=%s, repository=%s",
            project_id,
            "connected" if repository else "none",
        )

    async def analyze_gaps(
        self, evaluation_results: list[EvaluationResult]
    ) -> list[Task]:
        """Convert evaluation findings into prioritized tasks.

        For each finding in each evaluation result:
        1. Create a Task with title, description, priority, and task_type.
        2. Recommend an agent based on task_type (using STATIC_ROUTING).
        3. Set priority based on severity (critical=10, high=8, medium=5, low=2).
        4. Detect dependencies between tasks.

        After all tasks are created, dependencies are detected and the full
        list is prioritized via ``prioritize()``.

        Args:
            evaluation_results: List of EvaluationResult objects from the
                               evaluation battery. Each may contain multiple
                               findings.

        Returns:
            A list of Task objects sorted by priority and dependency order,
            ready for the Dispatcher.
        """
        if not evaluation_results:
            logger.warning("No evaluation results provided — nothing to plan")
            return []

        tasks: list[Task] = []

        for eval_result in evaluation_results:
            if not eval_result.findings:
                logger.debug(
                    "Evaluation '%s' has no findings, skipping",
                    eval_result.prompt_name,
                )
                continue

            task_type = self._category_to_task_type(eval_result.category)
            priority = self._severity_to_priority(eval_result.severity)
            recommended_agent = STATIC_ROUTING.get(task_type, DEFAULT_AGENT)

            for finding in eval_result.findings:
                normalized_finding = self._normalize_finding(finding)
                # Build a descriptive title from the finding
                title = self._build_title(
                    normalized_finding.title_text,
                    eval_result.prompt_name,
                    eval_result.category,
                )

                # Build description with full context
                description = self._build_description(
                    finding=normalized_finding.description_text,
                    prompt_name=eval_result.prompt_name,
                    category=eval_result.category,
                    severity=eval_result.severity,
                )

                task = Task(
                    project_id=self.project_id,
                    title=title,
                    description=description,
                    status=TaskStatus.PENDING,
                    priority=priority,
                    task_type=task_type,
                    recommended_agent=recommended_agent,
                    execution_steps=normalized_finding.execution_steps,
                    acceptance_checks=normalized_finding.acceptance_checks,
                )

                tasks.append(task)

                logger.debug(
                    "Created task: title='%s', type='%s', priority=%d, "
                    "agent='%s', from prompt='%s'",
                    title, task_type, priority, recommended_agent,
                    eval_result.prompt_name,
                )

        logger.info(
            "Gap analysis produced %d tasks from %d evaluation results",
            len(tasks), len(evaluation_results),
        )

        if not tasks:
            return []

        # Detect dependencies and prioritize
        prioritized = await self.prioritize(tasks)
        return prioritized

    async def prioritize(self, tasks: list[Task]) -> list[Task]:
        """Sort tasks by priority, respecting dependency ordering.

        Priority rules (applied in order):
        1. Security tasks first (task_type tier 0).
        2. Testing/infrastructure tasks second (task_type tier 1).
        3. Then by priority score (highest first).
        4. Within the same priority and tier, smaller (less complex) tasks
           first — estimated from title/description length as a proxy.

        The sorting is stable, so tasks that are equal on all criteria
        maintain their original order.

        Args:
            tasks: List of Task objects to sort.

        Returns:
            A new list of Task objects in prioritized order.
        """
        if not tasks:
            return []

        # Detect dependencies for logging/metadata purposes
        dependency_map = self._detect_dependencies(tasks)
        if dependency_map:
            logger.info(
                "Detected %d dependency relationships between tasks",
                sum(len(deps) for deps in dependency_map.values()),
            )

        # Build a set of task IDs that are depended upon (prerequisites)
        prerequisite_ids: set[str] = set()
        for deps in dependency_map.values():
            prerequisite_ids.update(deps)

        # Sort by: (tier ASC, priority DESC, description length ASC for
        # complexity proxy, title ASC for stability)
        def sort_key(task: Task) -> tuple:
            tier = TASK_TYPE_TIER.get(task.task_type or "", DEFAULT_TIER)
            # Negate priority so higher priority sorts first
            neg_priority = -task.priority
            # Use description length as a rough complexity proxy (shorter = simpler)
            complexity_proxy = len(task.description)
            return (tier, neg_priority, complexity_proxy, task.title)

        sorted_tasks = sorted(tasks, key=sort_key)

        logger.info(
            "Prioritized %d tasks. Order: %s",
            len(sorted_tasks),
            " -> ".join(
                f"[{t.task_type}:{t.priority}]" for t in sorted_tasks[:10]
            ) + ("..." if len(sorted_tasks) > 10 else ""),
        )

        return sorted_tasks

    def _severity_to_priority(self, severity: str) -> int:
        """Map severity string to numeric priority.

        Args:
            severity: One of "critical", "high", "medium", "low".
                     Case-insensitive.

        Returns:
            Numeric priority (10 for critical, 8 for high, 5 for medium,
            2 for low). Defaults to 5 if severity is unrecognized.
        """
        return SEVERITY_TO_PRIORITY.get(severity.lower().strip(), DEFAULT_PRIORITY)

    def _category_to_task_type(self, category: str) -> str:
        """Map evaluation category to CLAW task_type for routing.

        The category comes from the evaluation prompt and may use various
        labels. This method normalizes them to the task_type vocabulary
        used by the Dispatcher's STATIC_ROUTING table.

        Args:
            category: Raw category string from the evaluation result.
                     Case-insensitive. May contain spaces or mixed case.

        Returns:
            A task_type string that maps to an entry in STATIC_ROUTING.
            Defaults to "analysis" if category is empty or unrecognized.
        """
        if not category:
            return DEFAULT_TASK_TYPE

        normalized = category.lower().strip()

        # Direct lookup
        if normalized in CATEGORY_TO_TASK_TYPE:
            return CATEGORY_TO_TASK_TYPE[normalized]

        # Partial match — check if any known category keyword is a substring
        for key, task_type in CATEGORY_TO_TASK_TYPE.items():
            if key in normalized or normalized in key:
                return task_type

        logger.debug(
            "Unrecognized category '%s', defaulting to '%s'",
            category, DEFAULT_TASK_TYPE,
        )
        return DEFAULT_TASK_TYPE

    def _detect_dependencies(self, tasks: list[Task]) -> dict[str, list[str]]:
        """Detect dependency relationships between tasks.

        Uses the DEPENDENCY_ORDERING rules to identify which tasks should
        be completed before others. A dependency means task A should run
        before task B.

        Rules:
        - Security tasks should be done before feature tasks.
        - Testing infrastructure before test writing.
        - Architecture tasks before implementation.
        - Dependency analysis before refactoring.

        Args:
            tasks: List of Task objects to analyze for dependencies.

        Returns:
            A dict mapping task_id -> list of task_ids that must complete
            before it. The keys are the dependent tasks; the values are
            their prerequisites.

            Example: {"task-uuid-feature": ["task-uuid-security"]} means
            the feature task depends on the security task completing first.
        """
        if not tasks:
            return {}

        # Group tasks by task_type for efficient lookup
        tasks_by_type: dict[str, list[Task]] = {}
        for task in tasks:
            task_type = task.task_type or DEFAULT_TASK_TYPE
            if task_type not in tasks_by_type:
                tasks_by_type[task_type] = []
            tasks_by_type[task_type].append(task)

        # Build dependency map: task_id -> list of prerequisite task_ids
        dependencies: dict[str, list[str]] = {}

        for prerequisite_type, dependent_types in DEPENDENCY_ORDERING.items():
            prerequisite_tasks = tasks_by_type.get(prerequisite_type, [])
            if not prerequisite_tasks:
                continue

            prerequisite_ids = [t.id for t in prerequisite_tasks]

            for dependent_type in dependent_types:
                dependent_tasks = tasks_by_type.get(dependent_type, [])
                for dep_task in dependent_tasks:
                    if dep_task.id not in dependencies:
                        dependencies[dep_task.id] = []
                    # Add all prerequisite tasks as dependencies
                    for prereq_id in prerequisite_ids:
                        if prereq_id != dep_task.id and prereq_id not in dependencies[dep_task.id]:
                            dependencies[dep_task.id].append(prereq_id)

        # Log discovered dependencies
        for task_id, prereqs in dependencies.items():
            matching_tasks = [t for t in tasks if t.id == task_id]
            if matching_tasks:
                task = matching_tasks[0]
                logger.debug(
                    "Task '%s' (%s) depends on %d prerequisite(s)",
                    task.title, task.id, len(prereqs),
                )

        return dependencies

    def _normalize_finding(self, finding: str) -> NormalizedFinding:
        """Extract task-ready text and runbook hints from an evaluation finding.

        Evaluation prompts often return a JSON object with fields like
        ``summary`` and ``recommendations``. Without this normalization the
        dry-run planner shows raw JSON as the task title and loses executable
        hints.
        """
        raw = finding.strip()
        payload = self._parse_structured_finding(raw)
        if not payload:
            return NormalizedFinding(title_text=raw, description_text=raw)

        title_text = self._first_text(
            payload,
            ("title", "task_title", "summary", "finding", "problem", "issue"),
        )
        if not title_text:
            title_text = raw

        sections: list[str] = []
        for key in ("summary", "finding", "problem", "issue", "description", "rationale"):
            value = payload.get(key)
            text = self._stringify_structured_value(value)
            if text and text not in sections:
                sections.append(text)

        execution_steps = self._extract_string_list(
            payload,
            (
                "execution_steps",
                "steps",
                "next_steps",
                "recommendations",
                "recommended_actions",
                "actions",
                "remediation_steps",
            ),
        )
        acceptance_checks = self._extract_string_list(
            payload,
            (
                "acceptance_checks",
                "checks",
                "validation",
                "verification",
                "tests",
                "success_criteria",
            ),
        )

        if execution_steps:
            sections.append("Execution steps:\n" + "\n".join(f"- {step}" for step in execution_steps))
        if acceptance_checks:
            sections.append("Acceptance checks:\n" + "\n".join(f"- {check}" for check in acceptance_checks))

        if raw not in sections:
            sections.append("Raw evaluation output:\n" + raw)

        return NormalizedFinding(
            title_text=title_text,
            description_text="\n\n".join(sections),
            execution_steps=execution_steps,
            acceptance_checks=acceptance_checks,
        )

    def _parse_structured_finding(self, finding: str) -> Optional[dict[str, Any]]:
        """Parse a JSON object finding, including fenced markdown JSON."""
        text = finding.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        if not text.startswith("{"):
            return None

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            decoder = json.JSONDecoder()
            try:
                parsed, _ = decoder.raw_decode(text)
            except json.JSONDecodeError:
                return None

        return parsed if isinstance(parsed, dict) else None

    def _first_text(self, payload: dict[str, Any], keys: tuple[str, ...]) -> str:
        for key in keys:
            text = self._stringify_structured_value(payload.get(key))
            if text:
                return text
        return ""

    def _extract_string_list(self, payload: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for key in keys:
            raw_value = payload.get(key)
            items = raw_value if isinstance(raw_value, list) else [raw_value]
            for item in items:
                text = self._stringify_structured_value(item)
                if text and text not in seen:
                    values.append(text)
                    seen.add(text)
        return values

    def _stringify_structured_value(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, dict):
            for key in ("title", "summary", "description", "action", "step", "check", "name"):
                text = self._stringify_structured_value(value.get(key))
                if text:
                    return text
            return json.dumps(value, sort_keys=True)
        if isinstance(value, list):
            parts = [self._stringify_structured_value(item) for item in value]
            return "; ".join(part for part in parts if part)
        return str(value).strip()

    def _build_title(
        self, finding: str, prompt_name: str, category: str
    ) -> str:
        """Build a concise task title from a finding.

        Constructs a title that includes the category context and a
        truncated version of the finding for readability.

        Args:
            finding: The raw finding text.
            prompt_name: Name of the evaluation prompt that produced this finding.
            category: The evaluation category.

        Returns:
            A title string, truncated to 120 characters max.
        """
        # Clean up the finding for use as a title
        clean_finding = finding.strip()

        # Remove leading bullets, dashes, numbers
        for prefix in ["- ", "* ", "-- "]:
            if clean_finding.startswith(prefix):
                clean_finding = clean_finding[len(prefix):]

        # If the finding starts with a digit+period (like "1. "), strip it
        if len(clean_finding) > 2 and clean_finding[0].isdigit() and clean_finding[1] in ".):":
            clean_finding = clean_finding[2:].strip()

        # Build title with category prefix
        category_label = category.capitalize() if category else prompt_name
        max_finding_len = 120 - len(category_label) - 4  # 4 for "[]: "

        if len(clean_finding) > max_finding_len:
            truncated = clean_finding[:max_finding_len - 3].rsplit(" ", 1)[0] + "..."
        else:
            truncated = clean_finding

        return f"[{category_label}] {truncated}"

    def _build_description(
        self,
        finding: str,
        prompt_name: str,
        category: str,
        severity: str,
    ) -> str:
        """Build a detailed task description.

        Includes the full finding text, source prompt, category, and severity
        for the agent to have full context when working on the task.

        Args:
            finding: The raw finding text.
            prompt_name: Name of the evaluation prompt that produced this finding.
            category: The evaluation category.
            severity: The severity level.

        Returns:
            A multi-line description string.
        """
        lines = [
            f"Finding from evaluation prompt '{prompt_name}':",
            "",
            finding.strip(),
            "",
            f"Category: {category or 'unspecified'}",
            f"Severity: {severity}",
            f"Source prompt: {prompt_name}",
        ]
        return "\n".join(lines)

    def get_planning_summary(
        self, tasks: list[Task], dependency_map: Optional[dict[str, list[str]]] = None
    ) -> str:
        """Build a human-readable summary of the planning results.

        Useful for logging, reporting, and the attended-mode UI where a human
        reviews the plan before execution.

        Args:
            tasks: The prioritized list of tasks.
            dependency_map: Optional dependency map from _detect_dependencies.

        Returns:
            A formatted multi-line string summarizing the plan.
        """
        if not tasks:
            return "No tasks generated from evaluation results."

        # Count tasks by type and severity tier
        type_counts: dict[str, int] = {}
        priority_counts: dict[int, int] = {}
        for task in tasks:
            task_type = task.task_type or "unknown"
            type_counts[task_type] = type_counts.get(task_type, 0) + 1
            priority_counts[task.priority] = priority_counts.get(task.priority, 0) + 1

        lines = [
            f"Planning Summary for project {self.project_id}",
            f"{'=' * 50}",
            f"Total tasks: {len(tasks)}",
            "",
            "Tasks by type:",
        ]

        for task_type, count in sorted(type_counts.items()):
            agent = STATIC_ROUTING.get(task_type, DEFAULT_AGENT)
            lines.append(f"  {task_type}: {count} (recommended agent: {agent})")

        lines.append("")
        lines.append("Tasks by priority:")

        # Map priority back to severity for display
        priority_to_severity = {v: k for k, v in SEVERITY_TO_PRIORITY.items()}
        for priority, count in sorted(priority_counts.items(), reverse=True):
            severity_label = priority_to_severity.get(priority, f"priority-{priority}")
            lines.append(f"  {severity_label} (priority {priority}): {count}")

        if dependency_map:
            dep_count = sum(len(deps) for deps in dependency_map.values())
            lines.append("")
            lines.append(f"Dependencies: {dep_count} relationship(s) detected")

        lines.append("")
        lines.append("Execution order (first 20 tasks):")
        for i, task in enumerate(tasks[:20], 1):
            lines.append(
                f"  {i}. [{task.task_type}] {task.title} "
                f"(priority={task.priority}, agent={task.recommended_agent})"
            )

        if len(tasks) > 20:
            lines.append(f"  ... and {len(tasks) - 20} more tasks")

        return "\n".join(lines)
