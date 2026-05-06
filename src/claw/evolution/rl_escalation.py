"""RL Escalation Strategy — 3-tier reinforcement loop for persistent errors.

When the correction loop exhausts all attempts, this strategy diagnoses
the root cause and decides the next action:

    Tier 1: ROTATE_AGENT — try a different agent (agent-specific error)
    Tier 2: DECOMPOSE — split into simpler subtasks (task too complex)
    Tier 3: HUMAN_GATE — escalate to human with diagnosis (unresolvable)

The strategy uses ErrorKB categories to classify failures and tracks
escalation history to avoid infinite loops.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("claw.evolution.rl_escalation")


class EscalationAction(str, Enum):
    """What to do when correction loop is exhausted."""
    ROTATE_AGENT = "rotate_agent"
    DECOMPOSE = "decompose"
    HUMAN_GATE = "human_gate"
    ACCEPT_FAILURE = "accept_failure"


class EscalationDecision(BaseModel):
    """Result of the RL escalation diagnosis."""
    action: EscalationAction
    tier: int  # 1, 2, or 3
    error_category: str
    diagnosis: str
    excluded_agents: list[str] = Field(default_factory=list)
    subtask_hints: list[str] = Field(default_factory=list)


# Error categories that suggest agent-specific issues (Tier 1: rotate)
_AGENT_SPECIFIC_CATEGORIES = frozenset({
    "import_error",
    "api_error",
    "async_error",
    "connection_error",
    "test_failure",
    "syntax_error",
})

# Error categories that suggest task complexity issues (Tier 2: decompose)
_COMPLEXITY_CATEGORIES = frozenset({
    "type_error",
    "attribute_error",
    "value_error",
    "key_error",
    "index_error",
    "validation_error",
})

# Error categories that suggest environment/infra issues (Tier 3: human)
_INFRA_CATEGORIES = frozenset({
    "permission_error",
    "file_error",
    "database_error",
})

# Mirrored from error_kb.py for standalone classification
_ERROR_KEYWORDS: dict[str, list[str]] = {
    "type_error": ["typeerror", "type error", "has no attribute"],
    "import_error": ["importerror", "modulenotfounderror", "no module named"],
    "attribute_error": ["attributeerror"],
    "value_error": ["valueerror", "invalid literal"],
    "key_error": ["keyerror"],
    "index_error": ["indexerror", "list index"],
    "connection_error": ["connectionerror", "timeout", "refused"],
    "database_error": ["operationalerror", "integrityerror", "sqlite"],
    "permission_error": ["permissionerror", "access denied"],
    "file_error": ["filenotfounderror", "no such file"],
    "async_error": ["asyncio", "coroutine", "event loop"],
    "api_error": ["api error", "http error", "rate limit", "401", "403", "429"],
    "validation_error": ["validationerror", "pydantic"],
    "syntax_error": ["syntaxerror"],
    "test_failure": ["assertionerror", "assert", "expected", "test failed"],
}


def classify_error(error_signature: str, error_full: Optional[str] = None) -> str:
    """Classify an error into one of 15 categories.

    Returns the category name, or 'unknown' if no match.
    """
    text = (error_signature or "").lower()
    if error_full:
        text += " " + error_full[:500].lower()

    for category, keywords in _ERROR_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return category
    return "unknown"


class RLEscalationStrategy:
    """3-tier reinforcement loop for persistent task failures.

    Tracks escalation history per task to avoid infinite loops:
    - Max 2 agent rotations (Tier 1) before escalating to Tier 2
    - Max 1 decomposition attempt (Tier 2) before escalating to Tier 3
    - Tier 3 always goes to human gate

    Args:
        max_rotations: Maximum agent rotations before decomposing.
        max_decompositions: Maximum decomposition attempts before human gate.
    """

    def __init__(
        self,
        max_rotations: int = 2,
        max_decompositions: int = 1,
    ) -> None:
        self.max_rotations = max_rotations
        self.max_decompositions = max_decompositions
        # Track per-task escalation history: task_id -> {rotations, decompositions}
        self._history: dict[str, dict[str, int]] = {}

    def _get_history(self, task_id: str) -> dict[str, int]:
        if task_id not in self._history:
            self._history[task_id] = {"rotations": 0, "decompositions": 0}
        return self._history[task_id]

    def diagnose_and_decide(
        self,
        task_id: str,
        error_signature: Optional[str],
        error_full: Optional[str],
        current_agent_id: Optional[str],
        available_agents: list[str],
        excluded_agents: Optional[list[str]] = None,
    ) -> EscalationDecision:
        """Diagnose failure root cause and decide escalation action.

        Args:
            task_id: The failed task ID.
            error_signature: Normalized error signature from TaskOutcome.
            error_full: Full error traceback.
            current_agent_id: Agent that just failed.
            available_agents: All configured agent IDs.
            excluded_agents: Agents already excluded for this task.

        Returns:
            EscalationDecision with action, tier, and context.
        """
        history = self._get_history(task_id)
        excluded = list(excluded_agents or [])
        if current_agent_id and current_agent_id not in excluded:
            excluded.append(current_agent_id)

        # Classify the error
        category = classify_error(error_signature, error_full)

        # Determine viable alternative agents
        viable_agents = [a for a in available_agents if a not in excluded]

        # TIER 1: Rotate agent (if error is agent-specific and alternatives exist)
        if (
            category in _AGENT_SPECIFIC_CATEGORIES
            and viable_agents
            and history["rotations"] < self.max_rotations
        ):
            history["rotations"] += 1
            logger.info(
                "RL Tier 1: Rotating agent for task %s (category=%s, rotation=%d/%d)",
                task_id, category, history["rotations"], self.max_rotations,
            )
            return EscalationDecision(
                action=EscalationAction.ROTATE_AGENT,
                tier=1,
                error_category=category,
                diagnosis=(
                    f"Error category '{category}' suggests agent-specific issue. "
                    f"Rotating from '{current_agent_id}' to alternatives: {viable_agents}"
                ),
                excluded_agents=excluded,
            )

        # TIER 2: Decompose (if error suggests complexity and decomposition budget remains)
        if (
            category in _COMPLEXITY_CATEGORIES
            and history["decompositions"] < self.max_decompositions
        ):
            history["decompositions"] += 1
            logger.info(
                "RL Tier 2: Decomposing task %s (category=%s, decomposition=%d/%d)",
                task_id, category, history["decompositions"], self.max_decompositions,
            )
            return EscalationDecision(
                action=EscalationAction.DECOMPOSE,
                tier=2,
                error_category=category,
                diagnosis=(
                    f"Error category '{category}' suggests task complexity. "
                    f"Decomposing into simpler subtasks."
                ),
                excluded_agents=excluded,
                subtask_hints=[
                    f"Simplify: isolate the {category} by breaking into smaller units",
                    "Create a test-first subtask that validates the fix",
                ],
            )

        # TIER 3: Human gate (infra issues, exhausted rotations/decompositions, or unknown)
        if category in _INFRA_CATEGORIES or category == "unknown":
            logger.info(
                "RL Tier 3: Human gate for task %s (category=%s, infra/unknown)",
                task_id, category,
            )
            return EscalationDecision(
                action=EscalationAction.HUMAN_GATE,
                tier=3,
                error_category=category,
                diagnosis=(
                    f"Error category '{category}' requires human intervention. "
                    f"Agents tried: {excluded}. Error: {error_signature or 'unknown'}"
                ),
                excluded_agents=excluded,
            )

        # Exhausted all tiers — human gate as last resort
        logger.info(
            "RL Tier 3: All escalation tiers exhausted for task %s (rotations=%d, decomps=%d)",
            task_id, history["rotations"], history["decompositions"],
        )
        return EscalationDecision(
            action=EscalationAction.HUMAN_GATE,
            tier=3,
            error_category=category,
            diagnosis=(
                f"All escalation tiers exhausted for '{category}'. "
                f"Rotations: {history['rotations']}/{self.max_rotations}, "
                f"Decompositions: {history['decompositions']}/{self.max_decompositions}. "
                f"Escalating to human."
            ),
            excluded_agents=excluded,
        )

    def reset_task(self, task_id: str) -> None:
        """Reset escalation history for a task (e.g., after human resolution)."""
        self._history.pop(task_id, None)
