"""Dispatcher — multi-agent routing and task state machine for CLAW.

Combines two responsibilities:

1. **Dispatcher** — Routes tasks to the best-fit agent using a static routing
   table with Bayesian learned scores and a 10% exploration rate.

2. **TaskRouter** — Enforces legal task-status transitions through a state
   machine. Every status change goes through this router for validation,
   logging, and database persistence.

The static routing table encodes starting priors. As tasks complete, the
agent_scores table in the database accumulates real performance data that
overrides the static priors. The 10% exploration rate ensures non-optimal
agents still get sampled to gather data for the scoring system.
"""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime
from typing import Any, Optional

from claw.core.exceptions import AgentError, RoutingError
from claw.core.models import Task, TaskContext, TaskStatus

logger = logging.getLogger("claw.dispatcher")


# ---------------------------------------------------------------------------
# Static routing table — starting priors for task_type -> agent_id
# ---------------------------------------------------------------------------

STATIC_ROUTING: dict[str, str] = {
    # Claude — analysis, documentation, architecture, security
    "analysis": "claude",
    "documentation": "claude",
    "architecture": "claude",
    "security": "claude",
    # Codex — parallel refactoring, bulk tests, CI/CD
    "refactoring": "codex",
    "testing": "codex",
    "bulk_changes": "codex",
    "ci_cd": "codex",
    # Gemini — full-repo comprehension (1M context), dependency analysis
    "dependency_analysis": "gemini",
    "full_repo_review": "gemini",
    "comprehension": "gemini",
    "migration": "gemini",
    # Grok — fast fixes, web lookup, multi-agent reasoning
    "quick_fix": "grok",
    "web_lookup": "grok",
    "fast_iteration": "grok",
    "bug_fix": "grok",
    # Local — high-volume, low-judgment tasks suitable for local inference
    "mining_extraction": "local",
    "bulk_classification": "local",
    "pattern_extraction": "local",
    "code_summarization": "local",
}

# Default agent when nothing else matches
DEFAULT_AGENT = "claude"


# ---------------------------------------------------------------------------
# Dispatcher — Bayesian routing with exploration
# ---------------------------------------------------------------------------

class Dispatcher:
    """Routes tasks to the best-fit agent.

    Routing strategy (in order):
    1. If the task's ``recommended_agent`` is set and available, use it.
    2. Query the ``agent_scores`` table for learned per-task-type scores.
       Select the agent with the highest average quality score.
    3. Fall back to the static routing table.
    4. If nothing matches, use ``DEFAULT_AGENT``.

    A 10% exploration rate overrides the above to pick a random available
    agent, ensuring the system continues gathering data on all agents.
    """

    def __init__(
        self,
        agents: dict[str, Any],
        exploration_rate: float = 0.10,
        repository: Optional[Any] = None,
        kelly_sizer: Optional[Any] = None,
    ):
        """Initialize the Dispatcher.

        Args:
            agents: Mapping of agent_id -> AgentInterface instances.
                    Only agents present in this dict are considered available.
            exploration_rate: Probability [0.0, 1.0] of picking a random agent
                             instead of the best-fit. Default is 10%.
            repository: Optional Repository instance for reading learned
                        agent_scores from the database. If None, only static
                        routing and exploration are used.
            kelly_sizer: Optional BayesianKellySizer for adaptive Kelly-weighted
                        routing.  When provided, replaces the static exploration
                        rate with per-agent Bayesian Kelly fractions.
        """
        if not agents:
            raise RoutingError("(any)", reason="No agents provided to Dispatcher")
        if not 0.0 <= exploration_rate <= 1.0:
            raise ValueError(
                f"exploration_rate must be between 0.0 and 1.0, got {exploration_rate}"
            )

        self.agents = agents
        self.exploration_rate = exploration_rate
        self.repository = repository
        self.kelly_sizer = kelly_sizer
        self._available_agent_ids: list[str] = sorted(agents.keys())

        logger.info(
            "Dispatcher initialized: agents=%s, exploration_rate=%.2f, "
            "repository=%s, kelly=%s",
            self._available_agent_ids,
            exploration_rate,
            "connected" if repository else "none",
            "enabled" if kelly_sizer else "disabled",
        )

    async def route_task(self, task: Task, task_context: Optional[TaskContext] = None) -> str:
        """Select the best agent for a task.

        Args:
            task: The task to route. Uses ``task.task_type`` for lookup and
                  ``task.recommended_agent`` as a hint.
            task_context: Optional enriched context (currently used for logging
                          only but reserved for future context-aware routing).

        Returns:
            The agent_id of the selected agent.

        Raises:
            RoutingError: If no agent can be selected (all agents unavailable).
        """
        task_type = task.task_type or ""

        # Build exclusion set from task.excluded_agents, populated by agent rotation.
        excluded = set(getattr(task, "excluded_agents", None) or [])
        if excluded:
            logger.info(
                "Routing with excluded_agents=%s for task %s",
                sorted(excluded), task.id,
            )
            if excluded >= set(self._available_agent_ids):
                logger.warning(
                    "All agents excluded for task %s — clearing exclusions for fallback",
                    task.id,
                )
                excluded = set()

        # 1. User-explicit agent override (--agent flag) takes absolute priority.
        #    Distinguished from planner-assigned recommended_agent by checking
        #    whether Kelly has data — if Kelly can route, it overrides the
        #    planner's static assignment but NOT a user's explicit choice.
        user_explicit = task.recommended_agent and task.recommended_agent in self.agents

        # 2. Kelly-weighted routing (if enabled and has performance data)
        kelly_agent = await self._kelly_route(task_type)
        if kelly_agent and kelly_agent not in excluded:
            if user_explicit and task.recommended_agent != kelly_agent:
                logger.info(
                    "Kelly routing overrides recommended_agent='%s' with '%s' "
                    "for task_type='%s'",
                    task.recommended_agent, kelly_agent, task_type,
                )
            return kelly_agent

        # 3. Fall back to recommended_agent (from planner static table)
        if user_explicit and task.recommended_agent not in excluded:
            logger.info(
                "Using recommended_agent='%s' for task_type='%s'",
                task.recommended_agent, task_type,
            )
            return task.recommended_agent

        # 4. Classic routing: exploration + learned scores + static table
        if self._should_explore():
            chosen = self._pick_random_agent(excluded=excluded)
            logger.info(
                "Exploration triggered: task_type='%s' -> random agent '%s'",
                task_type, chosen,
            )
            return chosen

        # 5. Try learned scores from repository
        learned_agent = await self._lookup_learned_scores(task_type)
        if learned_agent and learned_agent not in excluded:
            logger.info(
                "Learned routing: task_type='%s' -> agent '%s'",
                task_type, learned_agent,
            )
            return learned_agent

        # 6. Static routing table
        static_agent = self._lookup_static(task_type)
        if static_agent and static_agent not in excluded:
            logger.info(
                "Static routing: task_type='%s' -> agent '%s'",
                task_type, static_agent,
            )
            return static_agent

        # 7. Absolute fallback
        fallback = self._resolve_fallback(task_type, excluded=excluded)
        logger.info(
            "Fallback routing: task_type='%s' -> agent '%s'",
            task_type, fallback,
        )
        return fallback

    def _should_explore(self) -> bool:
        """Roll the dice for exploration."""
        return random.random() < self.exploration_rate

    def _pick_random_agent(self, excluded: set[str] | None = None) -> str:
        """Pick a uniformly random available agent, respecting exclusions."""
        candidates = self._available_agent_ids
        if excluded:
            candidates = [a for a in candidates if a not in excluded]
        if not candidates:
            candidates = self._available_agent_ids
        return random.choice(candidates)

    async def _kelly_route(self, task_type: str) -> Optional[str]:
        """Route using Bayesian Kelly fractions when kelly_sizer is active.

        Returns the selected agent_id, or None to fall through to classic routing.
        Falls through when:
        - kelly_sizer is not configured
        - repository is not available
        - no agent_scores data exists for this task_type
        """
        if not self.kelly_sizer or not self.repository or not task_type:
            return None

        try:
            all_scores = await self.repository.get_agent_scores()
        except Exception as e:
            logger.warning("Kelly routing: failed to read agent_scores: %s", e)
            return None

        # Filter to scores for this task_type
        task_scores = [
            s for s in all_scores
            if s.get("task_type") == task_type
            and s.get("agent_id") in self.agents
        ]

        # Check if any agent has actual data — if not, fall through to classic
        has_data = any(
            (s.get("successes", 0) + s.get("failures", 0)) > 0
            for s in task_scores
        )
        if not has_data:
            return None

        weights = self.kelly_sizer.compute_routing_weights(
            task_scores, self._available_agent_ids,
        )
        chosen = self.kelly_sizer.sample_agent(weights)

        logger.info(
            "Kelly routing: task_type='%s' -> agent '%s' "
            "(weights: %s)",
            task_type,
            chosen,
            {a: f"{w:.3f}" for a, w in sorted(weights.items())},
        )
        return chosen

    async def _lookup_learned_scores(self, task_type: str) -> Optional[str]:
        """Query agent_scores for the highest-scoring agent for a task type.

        Returns the agent_id with the highest average quality score among
        agents that have attempted this task type, or None if no scores exist
        or no repository is configured.
        """
        if not self.repository or not task_type:
            return None

        try:
            all_scores = await self.repository.get_agent_scores()
        except Exception as e:
            logger.warning(
                "Failed to read agent_scores from repository: %s", e,
            )
            return None

        # Filter to scores matching this task_type and available agents
        candidates: list[dict[str, Any]] = []
        for score_row in all_scores:
            if (
                score_row.get("task_type") == task_type
                and score_row.get("agent_id") in self.agents
                and score_row.get("total_attempts", 0) > 0
            ):
                candidates.append(score_row)

        if not candidates:
            return None

        # Select agent with highest avg_quality_score, break ties by
        # success rate, then by lower avg_cost
        best = max(
            candidates,
            key=lambda c: (
                c.get("avg_quality_score", 0.0),
                (c.get("successes", 0) / max(c.get("total_attempts", 1), 1)),
                -(c.get("avg_cost_usd", 0.0)),
            ),
        )
        return best.get("agent_id")

    def _lookup_static(self, task_type: str) -> Optional[str]:
        """Look up the static routing table and verify the agent is available.

        Returns the agent_id if found and available, otherwise None.
        """
        agent_id = STATIC_ROUTING.get(task_type)
        if agent_id and agent_id in self.agents:
            return agent_id

        # Agent from static table is not in the available pool — skip
        if agent_id and agent_id not in self.agents:
            logger.debug(
                "Static route '%s' -> '%s' unavailable, skipping",
                task_type, agent_id,
            )
        return None

    def _resolve_fallback(self, task_type: str, excluded: set[str] | None = None) -> str:
        """Determine the fallback agent, respecting exclusions.

        Prefers DEFAULT_AGENT if available, otherwise picks the first
        available agent alphabetically.

        Raises:
            RoutingError: If the available agents dict is empty (should not
                          happen as __init__ validates this).
        """
        excluded = excluded or set()

        if DEFAULT_AGENT in self.agents and DEFAULT_AGENT not in excluded:
            return DEFAULT_AGENT

        candidates = [a for a in self._available_agent_ids if a not in excluded]
        if candidates:
            return candidates[0]

        if self._available_agent_ids:
            return self._available_agent_ids[0]

        # This branch should be unreachable due to __init__ validation
        raise RoutingError(
            task_type,
            reason="No agents available for fallback routing",
        )

    def get_routing_info(self, task_type: str) -> dict[str, Any]:
        """Return diagnostic information about how a task_type would be routed.

        This is a synchronous method for inspection/debugging. It does NOT
        perform the actual routing (no exploration roll, no DB lookup).
        """
        static_agent = STATIC_ROUTING.get(task_type)
        static_available = static_agent in self.agents if static_agent else False
        fallback = DEFAULT_AGENT if DEFAULT_AGENT in self.agents else (
            self._available_agent_ids[0] if self._available_agent_ids else None
        )

        return {
            "task_type": task_type,
            "static_route": static_agent,
            "static_available": static_available,
            "fallback": fallback,
            "exploration_rate": self.exploration_rate,
            "available_agents": list(self._available_agent_ids),
            "repository_connected": self.repository is not None,
            "kelly_enabled": self.kelly_sizer is not None,
        }


# ---------------------------------------------------------------------------
# Task state machine — legal status transitions
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {
        TaskStatus.EVALUATING,
        TaskStatus.DISPATCHED,
    },
    TaskStatus.EVALUATING: {
        TaskStatus.PLANNING,
        TaskStatus.STUCK,
    },
    TaskStatus.PLANNING: {
        TaskStatus.DISPATCHED,
        TaskStatus.STUCK,
    },
    TaskStatus.DISPATCHED: {
        TaskStatus.CODING,
        TaskStatus.STUCK,
    },
    TaskStatus.CODING: {
        TaskStatus.REVIEWING,
        TaskStatus.CODING,       # Retry within coding
        TaskStatus.DISPATCHED,   # Re-dispatch to a different agent
        TaskStatus.STUCK,
    },
    TaskStatus.REVIEWING: {
        TaskStatus.DONE,
        TaskStatus.CODING,       # Verification rejected — back to coding
        TaskStatus.DISPATCHED,   # Re-route to different agent
        TaskStatus.STUCK,
    },
    TaskStatus.STUCK: set(),     # Terminal — requires human intervention
    TaskStatus.DONE: set(),      # Terminal
}


class TaskRouter:
    """Manages task status transitions with validation and persistence.

    All status changes flow through this router to enforce the state graph,
    produce structured log entries, and persist to the database via the
    Repository layer.

    State graph (CLAW claw cycle):
        PENDING -> EVALUATING -> PLANNING -> DISPATCHED -> CODING -> REVIEWING -> DONE
                                                           |           |
                                                           v           v
                                                         STUCK       STUCK
        (CODING and REVIEWING can loop back to DISPATCHED for re-routing)

    Terminal states: STUCK, DONE.
    """

    def __init__(self, repository: Any):
        """Initialize the TaskRouter.

        Args:
            repository: Repository instance for persisting status changes.
                        Must have async methods: update_task_status(),
                        increment_task_attempt(), increment_task_escalation().
        """
        self.repository = repository

    async def transition(
        self,
        task: Task,
        new_status: TaskStatus,
        reason: Optional[str] = None,
    ) -> Task:
        """Move a task to a new status.

        Validates the transition against the state graph, persists to the
        database, and updates the in-memory task object.

        Args:
            task: The task to transition.
            new_status: Target status.
            reason: Optional human-readable reason for the transition.

        Returns:
            The task with its status updated.

        Raises:
            AgentError: If the transition is not allowed by the state graph.
        """
        if not self.can_transition(task.status, new_status):
            raise AgentError(
                f"Invalid transition: {task.status.value} -> {new_status.value} "
                f"for task '{task.title}' ({task.id}). "
                f"Allowed from {task.status.value}: "
                f"{{{', '.join(s.value for s in VALID_TRANSITIONS.get(task.status, set()))}}}"
            )

        old_status = task.status

        # Persist to database
        await self.repository.update_task_status(task.id, new_status)

        # Update in-memory model
        task.status = new_status
        task.updated_at = datetime.now(UTC)

        log_msg = f"Task '{task.title}' ({task.id}): {old_status.value} -> {new_status.value}"
        if reason:
            log_msg += f" ({reason})"
        logger.info(log_msg)

        return task

    def can_transition(self, from_status: TaskStatus, to_status: TaskStatus) -> bool:
        """Check if a transition from one status to another is legal.

        Args:
            from_status: Current task status.
            to_status: Desired target status.

        Returns:
            True if the transition is allowed, False otherwise.
        """
        allowed = VALID_TRANSITIONS.get(from_status, set())
        return to_status in allowed

    def get_valid_transitions(self, from_status: TaskStatus) -> set[TaskStatus]:
        """Return the set of statuses reachable from the given status.

        Args:
            from_status: Current task status.

        Returns:
            Set of valid target statuses. Empty set for terminal states.
        """
        return VALID_TRANSITIONS.get(from_status, set()).copy()

    async def mark_stuck(self, task: Task, reason: str) -> Task:
        """Convenience method to move a task to STUCK with a reason.

        Args:
            task: The task to mark as stuck.
            reason: Why the task is stuck (logged and used for diagnostics).

        Returns:
            The task with STUCK status.

        Raises:
            AgentError: If STUCK is not reachable from the current status.
        """
        return await self.transition(task, TaskStatus.STUCK, reason=reason)

    async def mark_done(self, task: Task) -> Task:
        """Convenience method to move a task to DONE.

        Args:
            task: The task to mark as done.

        Returns:
            The task with DONE status and completed_at set.

        Raises:
            AgentError: If DONE is not reachable from the current status.
        """
        result = await self.transition(task, TaskStatus.DONE, reason="completed successfully")
        result.completed_at = datetime.now(UTC)
        return result

    async def increment_attempt(self, task: Task) -> Task:
        """Increment the task's attempt counter and persist.

        Args:
            task: The task whose attempt count to increment.

        Returns:
            The task with incremented attempt_count.
        """
        await self.repository.increment_task_attempt(task.id)
        task.attempt_count += 1
        logger.info(
            "Task '%s' (%s): attempt_count -> %d",
            task.title, task.id, task.attempt_count,
        )
        return task

    async def increment_escalation(self, task: Task) -> Task:
        """Increment the task's escalation counter and persist.

        Args:
            task: The task whose escalation count to increment.

        Returns:
            The task with incremented escalation_count.
        """
        await self.repository.increment_task_escalation(task.id)
        task.escalation_count += 1
        logger.info(
            "Task '%s' (%s): escalation_count -> %d",
            task.title, task.id, task.escalation_count,
        )
        return task

    def should_escalate(self, task: Task, threshold: int = 2) -> bool:
        """Check if the task has enough failures to trigger escalation.

        Escalation is triggered when attempt_count reaches the threshold
        and no escalation has happened yet.

        Args:
            task: The task to check.
            threshold: Number of failed attempts before escalation.

        Returns:
            True if escalation should be triggered.
        """
        return task.attempt_count >= threshold and task.escalation_count == 0

    def should_mark_stuck(self, task: Task, max_escalations: int = 3) -> bool:
        """Check if the task should be marked STUCK (escalations exhausted).

        Args:
            task: The task to check.
            max_escalations: Maximum escalation attempts before giving up.

        Returns:
            True if the task has exhausted all escalation attempts.
        """
        return task.escalation_count >= max_escalations

    def get_state_summary(self, task: Task) -> str:
        """Build a human-readable summary of the task's current state.

        Args:
            task: The task to summarize.

        Returns:
            Formatted string with task status, attempts, and escalations.
        """
        valid_next = self.get_valid_transitions(task.status)
        next_str = ", ".join(s.value for s in sorted(valid_next, key=lambda s: s.value))
        return (
            f"Task '{task.title}' ({task.id}): "
            f"status={task.status.value}, "
            f"attempts={task.attempt_count}, "
            f"escalations={task.escalation_count}, "
            f"assigned_agent={task.assigned_agent or 'none'}, "
            f"valid_next=[{next_str}]"
        )

    def is_terminal(self, task: Task) -> bool:
        """Check if the task is in a terminal state (STUCK or DONE).

        Args:
            task: The task to check.

        Returns:
            True if no transitions are possible from the current status.
        """
        return len(VALID_TRANSITIONS.get(task.status, set())) == 0
