"""Custom exception hierarchy for CLAW.

All exceptions inherit from ClawError so callers can catch broadly
or narrowly as needed.
"""


class ClawError(Exception):
    """Base exception for all CLAW errors."""


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

class DatabaseError(ClawError):
    """Failed database operation."""


class SchemaInitError(DatabaseError):
    """Failed to initialize database schema."""


class ConnectionError(DatabaseError):
    """Failed to connect to database."""


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

class LLMError(ClawError):
    """Failed LLM operation."""


class RateLimitError(LLMError):
    """Hit API rate limit."""


class AuthenticationError(LLMError):
    """Invalid API key or unauthorized."""


class ModelNotFoundError(LLMError):
    """Requested model not available."""


class ModelRejectedError(ModelNotFoundError):
    """Provider rejected the model request as non-retryable."""


class ResponseParseError(LLMError):
    """Failed to parse LLM response."""


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

class AgentError(ClawError):
    """Agent processing failure."""


class AgentUnavailableError(AgentError):
    """Agent is not available (not installed, not configured, or health check failed)."""

    def __init__(self, agent_id: str, reason: str = ""):
        self.agent_id = agent_id
        self.reason = reason
        msg = f"Agent '{agent_id}' unavailable"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


class CheckpointError(AgentError):
    """Failed to create or restore git checkpoint."""


class VerificationRejectionError(AgentError):
    """Verifier rejected the agent output."""

    def __init__(self, violations: list[dict[str, str]], message: str = "Verifier rejected output"):
        self.violations = violations
        super().__init__(message)


class EscalationExhaustionError(AgentError):
    """Escalation invoked too many times — task is STUCK."""

    def __init__(self, task_id: str, escalation_count: int):
        self.task_id = task_id
        self.escalation_count = escalation_count
        super().__init__(
            f"Task {task_id} stuck after {escalation_count} escalation attempts"
        )


# ---------------------------------------------------------------------------
# Routing & Dispatch
# ---------------------------------------------------------------------------

class RoutingError(ClawError):
    """Failed to route task to an appropriate agent."""

    def __init__(self, task_type: str, reason: str = ""):
        self.task_type = task_type
        self.reason = reason
        msg = f"Cannot route task type '{task_type}'"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


class BudgetExceededError(ClawError):
    """Token or cost budget exceeded."""

    def __init__(self, budget_type: str, limit: float, current: float):
        self.budget_type = budget_type
        self.limit = limit
        self.current = current
        super().__init__(
            f"{budget_type} budget exceeded: {current:.2f} / {limit:.2f}"
        )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

class ToolError(ClawError):
    """Tool execution failure."""


class ShellTimeoutError(ToolError):
    """Shell command exceeded timeout."""


class GitOperationError(ToolError):
    """Git operation failed."""


class SearchError(ToolError):
    """Web search API failure."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class ConfigError(ClawError):
    """Invalid or missing configuration."""
