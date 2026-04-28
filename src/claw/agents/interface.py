"""Abstract agent interface for CLAW.

All four agents (Claude, Codex, Gemini, Grok) implement this ABC.
Provides lifecycle timing, metrics, and structured TaskOutcome returns.

All agents can use OpenRouter mode (mode="openrouter") to route through
the OpenRouter API with any model. This is the recommended mode for
cost-controlled testing and multi-model comparison.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

import httpx

from claw.core.models import AgentHealth, AgentMode, AgentResult, TaskContext, TaskOutcome

logger = logging.getLogger("claw.agent.interface")

# ---------------------------------------------------------------------------
# Module-level concurrency guard — enforces AgentConfig.max_concurrent
# ---------------------------------------------------------------------------
_AGENT_SEMAPHORE: Optional[asyncio.Semaphore] = None
_AGENT_SEMAPHORE_LIMIT: int = 0


def get_agent_semaphore(max_concurrent: int = 2) -> asyncio.Semaphore:
    """Return (or create) a module-level semaphore for agent HTTP calls."""
    global _AGENT_SEMAPHORE, _AGENT_SEMAPHORE_LIMIT
    if _AGENT_SEMAPHORE is None or _AGENT_SEMAPHORE_LIMIT != max_concurrent:
        _AGENT_SEMAPHORE = asyncio.Semaphore(max_concurrent)
        _AGENT_SEMAPHORE_LIMIT = max_concurrent
    return _AGENT_SEMAPHORE


def _agent_backoff_delay(attempt: int, base_seconds: float = 2.0) -> float:
    """Exponential backoff with jitter for agent HTTP calls."""
    delay = min(base_seconds * (2 ** attempt), 60)
    jitter = random.uniform(0, base_seconds * 0.5)
    return delay + jitter


# ---------------------------------------------------------------------------
# Circuit breaker for LLM HTTP endpoints
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Simple circuit breaker for LLM API endpoints.

    States:
      CLOSED  -- normal operation, calls go through
      OPEN    -- fail fast, too many consecutive failures
      HALF_OPEN -- cooldown expired, allow one probe call

    After ``failure_threshold`` consecutive failures the circuit opens and
    rejects calls for ``cooldown_seconds``. Once the cooldown expires the
    circuit enters half-open state: the next call is a probe. If the probe
    succeeds the circuit closes; if it fails the circuit reopens for another
    cooldown period.

    Thread-safe via a threading.Lock (the breaker state is read/written from
    both sync helpers and async methods that may share a thread).
    """

    STATE_CLOSED = "closed"
    STATE_OPEN = "open"
    STATE_HALF_OPEN = "half_open"

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds

        self._lock = threading.Lock()
        self._state: str = self.STATE_CLOSED
        self._consecutive_failures: int = 0
        self._opened_at: float = 0.0  # monotonic timestamp
        self._total_rejected: int = 0
        self._total_failures: int = 0

    # -- public query ---------------------------------------------------------

    @property
    def state(self) -> str:
        """Current breaker state (closed / open / half_open)."""
        with self._lock:
            return self._resolve_state()

    @property
    def consecutive_failures(self) -> int:
        with self._lock:
            return self._consecutive_failures

    @property
    def total_rejected(self) -> int:
        with self._lock:
            return self._total_rejected

    @property
    def total_failures(self) -> int:
        with self._lock:
            return self._total_failures

    # -- call guard -----------------------------------------------------------

    def allow_request(self) -> bool:
        """Return True if a request should be attempted.

        Returns False (and increments rejected counter) when the circuit is
        OPEN. Returns True for CLOSED and HALF_OPEN (probe).
        """
        with self._lock:
            resolved = self._resolve_state()
            if resolved == self.STATE_OPEN:
                self._total_rejected += 1
                logger.warning(
                    "CircuitBreaker[%s] OPEN -- rejecting request "
                    "(%d consecutive failures, %.0fs remaining in cooldown)",
                    self.name,
                    self._consecutive_failures,
                    max(0, self.cooldown_seconds - (time.monotonic() - self._opened_at)),
                )
                return False
            if resolved == self.STATE_HALF_OPEN:
                logger.info(
                    "CircuitBreaker[%s] HALF_OPEN -- allowing probe request",
                    self.name,
                )
            return True

    # -- outcome recording ----------------------------------------------------

    def record_success(self) -> None:
        """Record a successful call. Resets failures and closes circuit."""
        with self._lock:
            was_open = self._state in (self.STATE_OPEN, self.STATE_HALF_OPEN)
            self._consecutive_failures = 0
            self._state = self.STATE_CLOSED
            if was_open:
                logger.info(
                    "CircuitBreaker[%s] CLOSED after successful call",
                    self.name,
                )

    def record_failure(self) -> None:
        """Record a failed call. Opens circuit after threshold is reached."""
        with self._lock:
            self._consecutive_failures += 1
            self._total_failures += 1
            logger.warning(
                "CircuitBreaker[%s] failure #%d (threshold=%d)",
                self.name,
                self._consecutive_failures,
                self.failure_threshold,
            )
            if self._consecutive_failures >= self.failure_threshold:
                if self._state != self.STATE_OPEN:
                    logger.warning(
                        "CircuitBreaker[%s] OPENED after %d consecutive failures -- "
                        "fast-failing for %.0fs",
                        self.name,
                        self._consecutive_failures,
                        self.cooldown_seconds,
                    )
                else:
                    logger.warning(
                        "CircuitBreaker[%s] remains OPEN after probe failure -- "
                        "resetting cooldown for %.0fs",
                        self.name,
                        self.cooldown_seconds,
                    )
                self._state = self.STATE_OPEN
                self._opened_at = time.monotonic()

    def reset(self) -> None:
        """Force-reset the circuit breaker to closed state."""
        with self._lock:
            self._consecutive_failures = 0
            self._state = self.STATE_CLOSED
            self._opened_at = 0.0
            logger.info("CircuitBreaker[%s] force-reset to CLOSED", self.name)

    # -- internals ------------------------------------------------------------

    def _resolve_state(self) -> str:
        """Resolve effective state, transitioning OPEN -> HALF_OPEN on cooldown expiry.

        Must be called while holding self._lock.
        """
        if self._state == self.STATE_OPEN:
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self.cooldown_seconds:
                self._state = self.STATE_HALF_OPEN
                logger.info(
                    "CircuitBreaker[%s] cooldown expired (%.1fs) -- entering HALF_OPEN",
                    self.name,
                    elapsed,
                )
                return self.STATE_HALF_OPEN
        return self._state


# Module-level circuit breakers -- one per endpoint type.
# These persist across agent instances for the lifetime of the process.
_openrouter_circuit = CircuitBreaker(
    name="openrouter",
    failure_threshold=5,
    cooldown_seconds=30.0,
)
_local_llm_circuit = CircuitBreaker(
    name="local_llm",
    failure_threshold=5,
    cooldown_seconds=30.0,
)


def get_openrouter_circuit() -> CircuitBreaker:
    """Return the module-level OpenRouter circuit breaker."""
    return _openrouter_circuit


def get_local_llm_circuit() -> CircuitBreaker:
    """Return the module-level local LLM circuit breaker."""
    return _local_llm_circuit



def _coerce_openrouter_content(choice: dict[str, Any]) -> str:
    """Normalize OpenRouter choice payloads into a plain text string."""
    if not isinstance(choice, dict):
        return ""

    message = choice.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if not isinstance(item, dict):
                    continue
                text_val = item.get("text")
                if isinstance(text_val, str):
                    parts.append(text_val)
                    continue
                for key in ("content", "value", "output_text"):
                    candidate = item.get(key)
                    if isinstance(candidate, str):
                        parts.append(candidate)
                        break
            return "\n".join(part for part in parts if part)

        # Tool-calling style payloads can put generated JSON into function arguments.
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            chunks: list[str] = []
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                function_obj = tc.get("function")
                if not isinstance(function_obj, dict):
                    continue
                args = function_obj.get("arguments")
                if isinstance(args, str):
                    chunks.append(args)
            if chunks:
                return "\n".join(chunks)

    # Some providers expose text directly at choice level.
    for key in ("text", "content", "output_text"):
        candidate = choice.get(key)
        if isinstance(candidate, str):
            return candidate

    return ""


class AgentInterface(ABC):
    """Base class for all CLAW agents.

    Every agent follows the same lifecycle:
    1. Receive task context
    2. Execute (LLM calls, tool execution, etc.)
    3. Return a TaskOutcome with structured results
    4. Log metrics and errors throughout

    Subclasses must implement:
    - execute() — core task processing
    - health_check() — agent availability check
    - supported_modes — property listing modes (cli, api, cloud)
    - instruction_file — property with path to agent instruction file
    """

    # Task types that benefit from full CAG corpus context instead of
    # top-K HybridSearch results. These are high-volume or broad-scan
    # operations where having the complete knowledge base in context
    # yields better coverage than selective retrieval.
    CAG_ELIGIBLE_TASK_TYPES: frozenset[str] = frozenset({
        # Mining/batch types
        "mining_extraction",
        "bulk_classification",
        "pattern_extraction",
        "code_summarization",
        "mining",
        "novelty_detection",
        "synergy_discovery",
        # Planner-generated types that benefit from full knowledge context
        "architecture",
        "analysis",
        "refactoring",
        "security",
    })

    def __init__(self, agent_id: str, name: str):
        """Initialize agent with id and name.

        Args:
            agent_id: Machine identifier (e.g., "claude", "codex", "gemini", "grok").
            name: Human-readable agent name (e.g., "Claude Code Agent").
        """
        self.agent_id = agent_id
        self.name = name
        self.logger = logging.getLogger(f"claw.agent.{agent_id}")
        self._metrics: dict[str, Any] = {
            "total_executed": 0,
            "total_errors": 0,
            "total_successes": 0,
            "last_duration_seconds": 0.0,
        }
        self._max_concurrent: int = 2  # Wired from AgentConfig.max_concurrent
        self._cag_corpus: str = ""
        self._cag_knowledge_budget: int = 16000
        self._token_budget: int = 100_000
        self._kv_cache_manager: Optional[Any] = None  # KVCacheManager when enabled
        self._fallback_models: list[str] = []  # SDK fallback model chain from config.llm
        self._brain_topology_text: str = ""  # Brain awareness for agent prompts

    def set_cag_corpus(self, corpus: str, knowledge_budget_chars: int = 16000) -> None:
        """Set the CAG corpus for knowledge injection.

        When set, eligible task types will use this full corpus text
        instead of the top-K HybridSearch results. Call with an empty
        string to disable CAG injection.

        Args:
            corpus: The serialized methodology corpus text.
            knowledge_budget_chars: Max chars of corpus to inject into prompt.
        """
        self._cag_corpus = corpus
        self._cag_knowledge_budget = knowledge_budget_chars

    def set_token_budget(self, budget: int) -> None:
        """Set the token budget for context assembly.

        This budget limits how many tokens (approximate, chars/4) the full
        prompt can consume. It also controls how much knowledge from
        HybridSearch results is injected into the prompt.

        Args:
            budget: Maximum token budget for context assembly.
        """
        self._token_budget = budget

    def set_kv_cache_manager(self, manager: Any) -> None:
        """Set the KV cache manager for prefix-based caching.

        When set, execute_local() will use a stable system message
        containing the CAG corpus, enabling Ollama 0.19's automatic
        prefix caching for KV state reuse across requests.

        Args:
            manager: A KVCacheManager instance.
        """
        self._kv_cache_manager = manager

    def set_brain_topology(self, topology_text: str) -> None:
        """Set brain topology text for awareness injection into prompts.

        When set, task prompts will include an "Available Knowledge Sources"
        section describing all brains (primary + ganglia), their specializations,
        and methodology counts.

        Args:
            topology_text: Deterministic summary from BrainTopology.build_summary_text().
        """
        self._brain_topology_text = topology_text

    def set_fallback_models(self, models: list[str]) -> None:
        """Set the SDK fallback model chain for OpenRouter execution.

        When the primary model fails with a retryable error (model not found,
        server error after retries, timeout after retries), the agent will try
        each fallback model in order before returning a failure.

        The fallback chain is independent of the DegradationManager's
        agent-level fallback (which routes to a different agent entirely).
        This provides model-level fallback within a single agent's execution.

        Args:
            models: List of OpenRouter model identifiers to try in order
                    when the primary model fails. E.g.
                    ["openai/gpt-4o-mini", "google/gemini-flash-1.5"].
        """
        self._fallback_models = list(models)
        if models:
            self.logger.info(
                "Fallback model chain set: %s", ", ".join(models),
            )

    @staticmethod
    def _resolve_cag_context(
        task: "TaskContext",
        cag_corpus: str = "",
    ) -> Optional[str]:
        """Check if CAG corpus should be used for this task.

        CAG is preferred for high-volume tasks that benefit from full knowledge:
        mining, novelty detection, synergy discovery, bulk classification.

        Args:
            task: The enriched task context.
            cag_corpus: The pre-built CAG corpus text. Empty string means
                CAG is not loaded / not available.

        Returns:
            The corpus text if CAG should be used, None otherwise.
        """
        if not cag_corpus:
            return None

        # Read task_type from the inner Task model
        task_type = getattr(task.task, "task_type", None) or ""
        if task_type in AgentInterface.CAG_ELIGIBLE_TASK_TYPES:
            return cag_corpus

        return None

    @abstractmethod
    async def execute(self, task: TaskContext, context: Optional[Any] = None) -> TaskOutcome:
        """Execute a task and return the outcome.

        Args:
            task: Enriched task context.
            context: Optional additional context (ContextBrief, etc.).

        Returns:
            TaskOutcome with files changed, test results, approach summary, etc.
        """

    @abstractmethod
    async def health_check(self) -> AgentHealth:
        """Check if this agent is available and operational.

        Returns:
            AgentHealth with availability status, mode, version, etc.
        """

    @property
    @abstractmethod
    def supported_modes(self) -> list[AgentMode]:
        """Return the modes this agent supports (cli, api, cloud)."""

    @property
    @abstractmethod
    def instruction_file(self) -> str:
        """Return the filename of this agent's instruction file (e.g., 'CLAUDE.md')."""

    async def run(self, task: TaskContext, context: Optional[Any] = None) -> TaskOutcome:
        """Execute the agent with lifecycle logging and metrics.

        This wraps execute() with start/complete/error tracking.
        Agents should override execute(), not run().
        """
        self._log_start(task)
        start = time.monotonic()

        try:
            result = await self.execute(task, context)
            duration = time.monotonic() - start
            result.duration_seconds = duration
            result.agent_id = self.agent_id
            self._metrics["total_executed"] += 1
            self._metrics["total_successes"] += 1
            self._metrics["last_duration_seconds"] = duration
            self._log_complete(duration, result)
            return result
        except Exception as e:
            duration = time.monotonic() - start
            self._metrics["total_executed"] += 1
            self._metrics["total_errors"] += 1
            self._metrics["last_duration_seconds"] = duration
            self._log_error(e)
            return TaskOutcome(
                agent_id=self.agent_id,
                failure_reason=type(e).__name__,
                failure_detail=str(e),
                duration_seconds=duration,
            )

    def _log_start(self, task: TaskContext) -> None:
        self.logger.info("[%s] Starting: task='%s'", self.name, task.task.title)

    def _log_complete(self, duration: float, result: TaskOutcome) -> None:
        if result.failure_reason:
            status = f"failed ({result.failure_reason})"
        elif result.tests_passed:
            status = "success"
        else:
            status = "completed"
        self.logger.info(
            "[%s] Complete: status=%s (%.2fs)",
            self.name, status, duration,
        )

    def _log_error(self, error: Exception) -> None:
        self.logger.error(
            "[%s] Error: %s", self.name, error, exc_info=True,
        )

    def _resolve_workspace(self, task: TaskContext) -> Optional[str]:
        """Return a safe cwd for subprocess execution.

        Uses workspace_dir if set and valid. Never falls back to
        task.description to prevent path-traversal via untrusted input.
        """
        ws = getattr(self, "workspace_dir", None)
        if ws and Path(ws).is_dir():
            return ws
        return None

    def can_modify_workspace(self) -> bool:
        """Whether this agent mode can directly edit files in the workspace.

        Unknown/custom test agents default to True so existing test doubles keep
        working. Real built-in agents only get write capability in CLI mode.
        """
        mode = getattr(self, "mode", None)
        if mode is None:
            return True
        return mode == AgentMode.CLI

    def can_use_internal_workspace_executor(self) -> bool:
        """Whether CAM can turn this agent's output into real file changes."""
        mode = getattr(self, "mode", None)
        return mode in {AgentMode.OPENROUTER, AgentMode.API, AgentMode.LOCAL}

    async def execute_openrouter(
        self, task: TaskContext, context: Optional[Any] = None
    ) -> TaskOutcome:
        """Execute task via OpenRouter API with retry + concurrency guard.

        All agents share this method. It uses OPENROUTER_API_KEY and
        the model specified in the agent's config. No native SDK needed.

        Retries transient errors (429, 5xx, timeout, connect) with
        exponential backoff + jitter. Bounded by module-level semaphore
        wired from AgentConfig.max_concurrent.
        """
        sem = get_agent_semaphore(self._max_concurrent)
        async with sem:
            return await self._execute_openrouter_inner(task, context)

    async def _execute_openrouter_inner(
        self, task: TaskContext, context: Optional[Any] = None
    ) -> TaskOutcome:
        """Inner OpenRouter execution with retry logic and SDK fallback chain.

        Tries the primary model first. If it fails with a retryable error
        (model not found, server error after retries, network timeout after
        retries), each fallback model in ``self._fallback_models`` is tried
        in order.

        Non-retryable errors (401 auth) abort immediately without fallback.
        """
        primary_model = getattr(self, "model", None)
        if not primary_model:
            return TaskOutcome(
                agent_id=self.agent_id,
                failure_reason="no_model",
                failure_detail="No model configured. Set model in claw.toml.",
            )

        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            return TaskOutcome(
                agent_id=self.agent_id,
                failure_reason="no_api_key",
                failure_detail="OPENROUTER_API_KEY not set in environment.",
            )

        # Circuit breaker: fail fast if OpenRouter endpoint is down
        circuit = _openrouter_circuit
        if not circuit.allow_request():
            return TaskOutcome(
                agent_id=self.agent_id,
                failure_reason="circuit_open",
                failure_detail=(
                    f"OpenRouter circuit breaker is OPEN after "
                    f"{circuit.consecutive_failures} consecutive failures. "
                    f"Waiting for cooldown ({circuit.cooldown_seconds:.0f}s) before retrying."
                ),
            )

        prompt = self._build_openrouter_prompt(task, context)
        knowledge_sections = prompt.count("### Pattern:")
        self.logger.debug(
            "Prompt for task %s: %d chars, %d knowledge sections, model=%s",
            getattr(getattr(task, "task", None), "id", "?")[:8],
            len(prompt),
            knowledge_sections,
            primary_model,
        )
        if knowledge_sections > 0:
            self.logger.info(
                "Injected %d PULSE methodology pattern(s) into agent prompt",
                knowledge_sections,
            )

        # Build the model chain: primary first, then fallbacks (deduped, order-preserved)
        model_chain: list[str] = [primary_model]
        for fb_model in self._fallback_models:
            if fb_model and fb_model not in model_chain:
                model_chain.append(fb_model)

        # Try each model in the chain
        chain_failures: list[str] = []
        for chain_idx, current_model in enumerate(model_chain):
            is_fallback = chain_idx > 0
            if is_fallback:
                self.logger.info(
                    "Primary model failed, trying fallback model %d/%d: %s",
                    chain_idx, len(model_chain) - 1, current_model,
                )

            outcome = await self._try_single_model_openrouter(
                model=current_model,
                api_key=api_key,
                prompt=prompt,
                task=task,
            )

            # Non-retryable failures: abort the chain immediately
            if outcome.failure_reason in ("http_401", "no_api_key"):
                return outcome

            # Success: return the outcome
            if outcome.failure_reason is None:
                if is_fallback:
                    self.logger.info(
                        "Fallback model '%s' succeeded (primary '%s' failed)",
                        current_model, primary_model,
                    )
                return outcome

            # Retryable failure: log and continue to next model in chain
            chain_failures.append(
                f"{current_model}: {outcome.failure_reason} - {outcome.failure_detail}"
            )

        # All models in chain failed
        failure_summary = "; ".join(chain_failures)
        return TaskOutcome(
            agent_id=self.agent_id,
            failure_reason="all_models_failed",
            failure_detail=(
                f"All {len(model_chain)} model(s) in fallback chain failed. "
                f"Details: {failure_summary}"
            ),
            duration_seconds=sum(
                0.0 for _ in chain_failures  # duration tracked per-attempt
            ),
        )

    async def _try_single_model_openrouter(
        self,
        model: str,
        api_key: str,
        prompt: str,
        task: TaskContext,
    ) -> TaskOutcome:
        """Attempt a single model via OpenRouter with retry logic.

        Returns a TaskOutcome. On success, failure_reason is None.
        On failure, failure_reason is set (e.g. http_404, http_401,
        TimeoutException, max_retries).
        """
        start = time.monotonic()

        try:
            # Build messages -- add system message when structured output is needed
            messages: list[dict[str, str]] = []
            needs_structured = self.can_use_internal_workspace_executor()
            if needs_structured:
                messages.append({
                    "role": "system",
                    "content": (
                        "You are a code generation agent. You MUST return ONLY valid JSON "
                        "with no markdown fences, no prose, no explanation outside the JSON object. "
                        "The JSON must have this exact shape:\n"
                        '{"summary": "short explanation of changes", '
                        '"file_operations": [{"path": "relative/path.ext", "action": "write", '
                        '"content": "full file contents"}]}\n'
                        "Rules: use only relative paths, action is write or delete, "
                        "content must be the complete file contents (not a diff or snippet)."
                    ),
                })
            messages.append({"role": "user", "content": prompt})

            payload: dict[str, object] = {
                "model": model,
                "messages": messages,
                "max_tokens": max(4096, int(getattr(self, "max_tokens", 16384) or 16384)),
            }
            if needs_structured:
                payload["response_format"] = {"type": "json_object"}

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/deesatzed/CAM-Pulse",
                "X-Title": "CLAW",
            }
            url = "https://openrouter.ai/api/v1/chat/completions"

            # Retry with exponential backoff + jitter
            max_retries = 3
            last_error: Optional[Exception] = None
            data: Optional[dict] = None

            for attempt in range(max_retries):
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                        response = await client.post(url, headers=headers, json=payload)

                    if response.status_code == 401:
                        detail = "Invalid OPENROUTER_API_KEY."
                        try:
                            err_body = response.json()
                            detail = err_body.get("error", {}).get("message", detail)
                        except Exception:
                            pass
                        return TaskOutcome(
                            agent_id=self.agent_id,
                            failure_reason="http_401",
                            failure_detail=detail,
                            duration_seconds=time.monotonic() - start,
                        )
                    if response.status_code == 404:
                        detail = f"Model not found: {model}"
                        try:
                            err_body = response.json()
                            detail = err_body.get("error", {}).get("message", detail)
                        except Exception:
                            pass
                        return TaskOutcome(
                            agent_id=self.agent_id,
                            failure_reason="http_404",
                            failure_detail=detail,
                            duration_seconds=time.monotonic() - start,
                        )
                    if response.status_code == 429:
                        delay = _agent_backoff_delay(attempt)
                        self.logger.warning(
                            "Rate limited (429). Waiting %.1fs before retry %d/%d",
                            delay, attempt + 1, max_retries,
                        )
                        await asyncio.sleep(delay)
                        continue
                    if response.status_code >= 500:
                        delay = _agent_backoff_delay(attempt)
                        self.logger.warning(
                            "Server error %d. Waiting %.1fs before retry %d/%d",
                            response.status_code, delay, attempt + 1, max_retries,
                        )
                        await asyncio.sleep(delay)
                        continue

                    response.raise_for_status()
                    data = response.json()
                    break  # Success

                except (httpx.TimeoutException, httpx.ConnectError) as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        delay = _agent_backoff_delay(attempt)
                        self.logger.warning(
                            "Network error: %s. Waiting %.1fs before retry %d/%d",
                            e, delay, attempt + 1, max_retries,
                        )
                        await asyncio.sleep(delay)
                    continue

            if data is None:
                duration = time.monotonic() - start
                reason = type(last_error).__name__ if last_error else "max_retries"
                detail = str(last_error) if last_error else f"Failed after {max_retries} attempts"
                _openrouter_circuit.record_failure()
                return TaskOutcome(
                    agent_id=self.agent_id,
                    failure_reason=reason,
                    failure_detail=detail,
                    duration_seconds=duration,
                )

            duration = time.monotonic() - start

            # Circuit breaker: record success -- OpenRouter API responded with parseable data
            _openrouter_circuit.record_success()

            # Parse response
            choices = data.get("choices", [])
            content = ""
            if choices:
                content = _coerce_openrouter_content(choices[0])
                if not isinstance(content, str):
                    content = str(content or "")

            usage = data.get("usage", {})
            tokens_used = (usage.get("prompt_tokens", 0) or 0) + (usage.get("completion_tokens", 0) or 0)
            model_used = data.get("model", model)

            return TaskOutcome(
                approach_summary=content[:500],
                model_used=model_used,
                agent_id=self.agent_id,
                raw_output=content,
                tokens_used=tokens_used,
                tests_passed=True,
                duration_seconds=duration,
            )

        except httpx.HTTPStatusError as e:
            duration = time.monotonic() - start
            detail = str(e)
            try:
                err_body = e.response.json()
                detail = err_body.get("error", {}).get("message", detail)
            except Exception:
                pass
            # Record failure for server errors (5xx); client errors (4xx)
            # are config issues and should not trip the circuit breaker.
            if e.response.status_code >= 500:
                _openrouter_circuit.record_failure()
            return TaskOutcome(
                agent_id=self.agent_id,
                failure_reason=f"http_{e.response.status_code}",
                failure_detail=detail,
                duration_seconds=duration,
            )
        except Exception as e:
            duration = time.monotonic() - start
            _openrouter_circuit.record_failure()
            return TaskOutcome(
                agent_id=self.agent_id,
                failure_reason=type(e).__name__,
                failure_detail=str(e),
                duration_seconds=duration,
            )

    async def execute_local(
        self, task: TaskContext, context: Optional[Any] = None
    ) -> TaskOutcome:
        """Execute task via a local LLM provider with retry + concurrency guard.

        Uses the OpenAI-compatible /v1/chat/completions endpoint. When a
        KVCacheManager is active, the CAG corpus is sent as a stable system
        message to enable Ollama 0.19's automatic prefix caching — the MLX
        runner reuses KV state for byte-identical prefixes, eliminating
        re-processing of the corpus on every request.

        Retries transient errors (429, 5xx, timeout) with exponential
        backoff + jitter. Bounded by module-level semaphore.
        """
        sem = get_agent_semaphore(self._max_concurrent)
        async with sem:
            return await self._execute_local_inner(task, context)

    async def _execute_local_inner(
        self, task: TaskContext, context: Optional[Any] = None
    ) -> TaskOutcome:
        """Inner local execution with retry logic."""
        model = getattr(self, "model", None)
        if not model:
            return TaskOutcome(
                agent_id=self.agent_id,
                failure_reason="no_model",
                failure_detail="No model configured for local mode. Set model in claw.toml.",
            )

        # Circuit breaker: fail fast if local LLM endpoint is down
        local_circuit = _local_llm_circuit
        if not local_circuit.allow_request():
            return TaskOutcome(
                agent_id=self.agent_id,
                failure_reason="circuit_open",
                failure_detail=(
                    f"Local LLM circuit breaker is OPEN after "
                    f"{local_circuit.consecutive_failures} consecutive failures. "
                    f"Waiting for cooldown ({local_circuit.cooldown_seconds:.0f}s) before retrying."
                ),
            )

        local_base_url = getattr(self, "local_base_url", None) or "http://localhost:11434/v1"
        endpoint = f"{local_base_url.rstrip('/')}/chat/completions"

        # When KV cache manager is active with a system message, build the
        # prompt WITHOUT CAG corpus injection (it's in the system message).
        # Otherwise, the standard path includes CAG in the user message.
        kv_mgr = self._kv_cache_manager
        use_kv_prefix = (
            kv_mgr is not None
            and kv_mgr.system_message
            and self._cag_corpus
            and self._resolve_cag_context(task, self._cag_corpus) is not None
        )

        if use_kv_prefix:
            prompt = self._build_openrouter_prompt(task, context, skip_cag=True)
        else:
            prompt = self._build_openrouter_prompt(task, context)

        start = time.monotonic()

        try:
            local_messages: list[dict[str, str]] = []
            local_needs_structured = self.can_use_internal_workspace_executor()

            if use_kv_prefix:
                local_messages.append({
                    "role": "system",
                    "content": kv_mgr.system_message,
                })
                if local_needs_structured:
                    prompt += (
                        "\n\n## Required Output Format\n"
                        "Return only valid JSON: "
                        '{"summary": "...", "file_operations": [{"path": "...", "action": "write", "content": "..."}]}'
                    )
            elif local_needs_structured:
                local_messages.append({
                    "role": "system",
                    "content": (
                        "You are a code generation agent. You MUST return ONLY valid JSON "
                        "with no markdown fences, no prose, no explanation outside the JSON object. "
                        "The JSON must have this exact shape:\n"
                        '{"summary": "short explanation of changes", '
                        '"file_operations": [{"path": "relative/path.ext", "action": "write", '
                        '"content": "full file contents"}]}\n'
                        "Rules: use only relative paths, action is write or delete, "
                        "content must be the complete file contents (not a diff or snippet)."
                    ),
                })
            local_messages.append({"role": "user", "content": prompt})

            local_timeout = float(getattr(self, "timeout", 300) or 300)
            local_payload: dict[str, object] = {
                "model": model,
                "messages": local_messages,
                "max_tokens": max(4096, int(getattr(self, "max_tokens", 16384) or 16384)),
            }
            if local_needs_structured:
                local_payload["response_format"] = {"type": "json_object"}

            if kv_mgr is not None:
                local_payload["keep_alive"] = kv_mgr.keep_alive

            local_headers = {"Content-Type": "application/json"}

            # Retry with exponential backoff + jitter
            max_retries = 3
            last_error: Optional[Exception] = None
            data: Optional[dict] = None

            for attempt in range(max_retries):
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(local_timeout)) as client:
                        response = await client.post(
                            endpoint, headers=local_headers, json=local_payload,
                        )

                    if response.status_code == 429:
                        delay = _agent_backoff_delay(attempt)
                        self.logger.warning(
                            "Local LLM rate limited (429). Waiting %.1fs before retry %d/%d",
                            delay, attempt + 1, max_retries,
                        )
                        await asyncio.sleep(delay)
                        continue
                    if response.status_code >= 500:
                        delay = _agent_backoff_delay(attempt)
                        self.logger.warning(
                            "Local LLM server error %d. Waiting %.1fs before retry %d/%d",
                            response.status_code, delay, attempt + 1, max_retries,
                        )
                        await asyncio.sleep(delay)
                        continue

                    response.raise_for_status()
                    data = response.json()
                    break

                except httpx.ConnectError as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        delay = _agent_backoff_delay(attempt)
                        self.logger.warning(
                            "Local LLM connect error. Waiting %.1fs before retry %d/%d",
                            delay, attempt + 1, max_retries,
                        )
                        await asyncio.sleep(delay)
                    continue
                except httpx.TimeoutException as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        delay = _agent_backoff_delay(attempt)
                        self.logger.warning(
                            "Local LLM timeout. Waiting %.1fs before retry %d/%d",
                            delay, attempt + 1, max_retries,
                        )
                        await asyncio.sleep(delay)
                    continue

            if data is None:
                duration = time.monotonic() - start
                local_circuit.record_failure()
                if isinstance(last_error, httpx.ConnectError):
                    return TaskOutcome(
                        agent_id=self.agent_id,
                        failure_reason="local_unreachable",
                        failure_detail=f"Local LLM endpoint not reachable at {endpoint} after {max_retries} attempts. "
                                       f"Start Ollama (`ollama serve`) or MLX-LM (`mlx_lm.server --model ...`).",
                        duration_seconds=duration,
                    )
                reason = type(last_error).__name__ if last_error else "max_retries"
                detail = str(last_error) if last_error else f"Failed after {max_retries} attempts"
                return TaskOutcome(
                    agent_id=self.agent_id,
                    failure_reason=reason,
                    failure_detail=detail,
                    duration_seconds=duration,
                )

            duration = time.monotonic() - start

            # Circuit breaker: record success — local LLM responded with parseable data
            local_circuit.record_success()

            choices = data.get("choices", [])
            content = ""
            if choices:
                content = _coerce_openrouter_content(choices[0])
                if not isinstance(content, str):
                    content = str(content or "")

            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0) or 0
            eval_tokens = usage.get("completion_tokens", 0) or 0
            tokens_used = prompt_tokens + eval_tokens
            model_used = data.get("model", model)

            if kv_mgr is not None and use_kv_prefix:
                kv_mgr.record_request(prompt_tokens, eval_tokens)

            return TaskOutcome(
                approach_summary=content[:500],
                model_used=model_used,
                agent_id=self.agent_id,
                raw_output=content,
                tokens_used=tokens_used,
                tests_passed=True,
                duration_seconds=duration,
            )

        except httpx.HTTPStatusError as e:
            duration = time.monotonic() - start
            detail = str(e)
            try:
                err_body = e.response.json()
                detail = err_body.get("error", {}).get("message", detail)
            except Exception:
                pass
            if e.response.status_code >= 500:
                local_circuit.record_failure()
            return TaskOutcome(
                agent_id=self.agent_id,
                failure_reason=f"http_{e.response.status_code}",
                failure_detail=detail,
                duration_seconds=duration,
            )
        except Exception as e:
            duration = time.monotonic() - start
            local_circuit.record_failure()
            return TaskOutcome(
                agent_id=self.agent_id,
                failure_reason=type(e).__name__,
                failure_detail=str(e),
                duration_seconds=duration,
            )

    @staticmethod
    def _resolve_knowledge_source(
        task: "TaskContext",
        context: Optional[Any],
        token_budget: int = 100_000,
    ) -> tuple[list[Any], int]:
        """Resolve knowledge to inject using 3-tier precedence.

        Precedence (highest to lowest):
          1. Task-level override: task.knowledge_override (if present)
          2. Context past_solutions: retrieved methodologies from PULSE
          3. Default: empty (no knowledge injection)

        The token_budget parameter controls how much of the context window
        can be allocated to knowledge injection. A smaller budget means
        less knowledge is injected.

        Returns (methodologies, budget_chars).
        """
        # Tier 1: explicit task-level override
        override = getattr(task, "knowledge_override", None)
        if override:
            budget = getattr(task, "knowledge_budget_chars", 8000)
            return (override, budget)

        # Tier 2: context past_solutions from retrieval
        if context is not None:
            past_solutions = getattr(context, "past_solutions", None) or []
            if past_solutions:
                # Use the explicit token_budget parameter instead of
                # the dead getattr fallback on context.
                max_chars = min(int(token_budget * 0.40 * 4), 32000)
                max_chars = max(max_chars, 4000)
                return (past_solutions, max_chars)

        # Tier 3: no knowledge
        return ([], 0)

    def _build_openrouter_prompt(
        self, task: TaskContext, context: Optional[Any] = None,
        skip_cag: bool = False,
    ) -> str:
        """Build prompt for OpenRouter execution. Agents can override.

        Args:
            task: The enriched task context.
            context: Optional execution context with past solutions.
            skip_cag: When True, skip CAG corpus injection (used when
                the corpus is in the system message for KV cache reuse).
        """
        parts = [f"# Task: {task.task.title}\n"]
        parts.append(task.task.description)

        execution_steps = list(task.task.execution_steps)
        acceptance_checks = list(task.task.acceptance_checks)

        if task.action_template is not None:
            if task.action_template.preconditions:
                parts.append("\n## Runbook Preconditions")
                for item in task.action_template.preconditions:
                    parts.append(f"- {item}")
            if not execution_steps:
                execution_steps = list(task.action_template.execution_steps)
            if not acceptance_checks:
                acceptance_checks = list(task.action_template.acceptance_checks)
            if task.action_template.rollback_steps:
                parts.append("\n## Rollback Steps")
                for step in task.action_template.rollback_steps:
                    parts.append(f"- {step}")

        if execution_steps:
            parts.append("\n## Execution Steps")
            for step in execution_steps:
                parts.append(f"- `{step}`")

        if acceptance_checks:
            parts.append("\n## Acceptance Checks")
            for check in acceptance_checks:
                parts.append(f"- `{check}`")

        if task.expectation_contract is not None:
            contract = task.expectation_contract
            expected_outcome = list(getattr(contract, "expected_outcome", []) or [])
            expected_ux = list(getattr(contract, "expected_ux", []) or [])
            constraints = list(getattr(contract, "constraints", []) or [])
            non_goals = list(getattr(contract, "non_goals", []) or [])

            if expected_outcome:
                parts.append("\n## Expected Outcome")
                for item in expected_outcome:
                    parts.append(f"- {item}")
            if expected_ux:
                parts.append("\n## Expected UX")
                for item in expected_ux:
                    parts.append(f"- {item}")
            if constraints:
                parts.append("\n## Constraints")
                for item in constraints:
                    parts.append(f"- {item}")
            if non_goals:
                parts.append("\n## Non-Goals")
                for item in non_goals:
                    parts.append(f"- {item}")

        task_text = " ".join(
            [
                task.task.title or "",
                task.task.description or "",
                " ".join(task.task.acceptance_checks or []),
            ]
        ).lower()
        if "python -m app.cli" in task_text or "cli" in task_text or "entrypoint" in task_text:
            parts.append("\n## CLI Guardrails")
            parts.append("- If you add --version, resolve version metadata from the package module, not from __main__.")
            parts.append("- If using argparse, preserve argparse exit code semantics: --help and --version should return 0, invalid arguments should return nonzero.")
            parts.append("- If you catch SystemExit around parser.parse_args(argv), return int(exc.code) so help/version keep exit code 0 while invalid arguments stay nonzero.")
            parts.append("- Include tests for help/version behavior and invalid-argument handling.")

        if task.forbidden_approaches:
            parts.append("\n## Forbidden Approaches (already tried, failed)")
            for fa in task.forbidden_approaches:
                parts.append(f"- {fa}")

        if hasattr(task, "hints") and task.hints:
            parts.append("\n## Hints from Past Solutions")
            for hint in task.hints:
                parts.append(f"- {hint}")

        # Inject correction feedback from a previous failed attempt within this cycle
        correction = getattr(task, "correction_feedback", None)
        if correction is None and context is not None:
            correction = getattr(context, "correction_feedback", None)
        if correction is not None:
            parts.append(f"\n## Correction Required (attempt {correction.attempt_number + 1})")
            parts.append(
                "Your previous attempt was rejected. Study the diff of what you "
                "wrote, the test output, and the test file content below. "
                "Identify the ROOT CAUSE of the failure and take a DIFFERENT approach."
            )
            if correction.violations:
                parts.append("\n### Violations Found")
                for v in correction.violations:
                    check = v.get("check", "unknown")
                    detail = v.get("detail", "no detail")
                    parts.append(f"- **{check}**: {detail}")
            if correction.code_diff:
                parts.append("\n### Your Previous Code Changes (what you wrote that failed)")
                parts.append(f"```diff\n{correction.code_diff[:6000]}\n```")
            if correction.failing_test_content:
                parts.append("\n### Test File(s) You Must Pass")
                parts.append(
                    "Read these carefully — your code must satisfy these exact assertions:"
                )
                parts.append(f"```python\n{correction.failing_test_content[:4000]}\n```")
            if correction.test_output:
                parts.append("\n### Test Output (from failed run)")
                test_text = correction.test_output[:4000]
                if len(correction.test_output) > 4000:
                    test_text += "\n... (truncated)"
                parts.append(f"```\n{test_text}\n```")
            if correction.failure_reason:
                parts.append(f"\n### Failure Reason: {correction.failure_reason}")
                if correction.failure_detail:
                    parts.append(correction.failure_detail[:1000])
            parts.append(
                "\nThe workspace has been restored to its pre-attempt state. "
                "Re-implement with a DIFFERENT approach that addresses the "
                "specific failure above."
            )

        # --- Brain topology awareness ---
        if self._brain_topology_text:
            parts.append("\n## Available Knowledge Sources")
            parts.append(self._brain_topology_text)

        # --- Knowledge injection ---
        # CAG path: if a CAG corpus is loaded and the task type is eligible,
        # inject the full corpus instead of individual HybridSearch results.
        # This gives broad-scan tasks (mining, novelty detection, etc.) access
        # to the complete methodology knowledge base in a single context window.
        # When skip_cag=True, the corpus is in the system message (KV cache
        # prefix strategy) — skip injection here to avoid duplication.
        cag_text = None if skip_cag else self._resolve_cag_context(task, self._cag_corpus)
        if cag_text:
            # Use configured CAG budget (default 16K chars ≈ 4K tokens)
            knowledge_budget = self._cag_knowledge_budget
            parts.append(
                "\n## Knowledge Base (CAG: full methodology corpus)\n"
                "The following is the complete methodology corpus from the knowledge base. "
                "Use these patterns as guidance for your implementation where applicable."
            )
            parts.append(cag_text[:knowledge_budget])
            parts.append("--- END KNOWLEDGE BASE ---")
            self.logger.info(
                "Injected CAG corpus (%d chars, budget %d) for task_type=%s",
                len(cag_text[:knowledge_budget]),
                knowledge_budget,
                getattr(task.task, "task_type", "unknown"),
            )
            # R6-06: Also inject top past_solutions alongside CAG corpus
            # CAG gives broad context; past_solutions give task-specific ranked matches
            _cag_solutions, _cag_budget = self._resolve_knowledge_source(
                task, context, token_budget=self._token_budget
            )
            if _cag_solutions:
                parts.append("\n## Task-Specific Retrieved Patterns (alongside CAG)")
                parts.append(
                    "These patterns were specifically retrieved and ranked for this task. "
                    "Prioritize these over the broad CAG corpus above."
                )
                _cag_chars = 0
                _cag_max = min(_cag_budget, 16000)  # Cap to avoid double-bloat
                for _sol in _cag_solutions[:5]:
                    _desc = getattr(_sol, "problem_description", "") or ""
                    _notes = getattr(_sol, "methodology_notes", "") or ""
                    _block = f"### Pattern: {_desc[:200]}\n{_notes[:2000]}"
                    if _cag_chars + len(_block) > _cag_max:
                        break
                    parts.append(_block)
                    _cag_chars += len(_block)
                self.logger.info(
                    "Injected %d task-specific patterns alongside CAG (%d chars)",
                    min(5, len(_cag_solutions)), _cag_chars,
                )
        else:
            # Standard HybridSearch path: inject individual methodology patterns
            # Uses 3-tier precedence: task override > context past_solutions > empty
            past_solutions, max_knowledge_chars = self._resolve_knowledge_source(
                task, context, token_budget=self._token_budget
            )
            if past_solutions:
                knowledge_parts: list[str] = []
                knowledge_chars = 0
                pointer_threshold = 1500  # Methodologies larger than this get pointers

                # Determine primary methodology ID from context brief
                _primary_mid = getattr(context, "primary_methodology_id", None) if context else None
                _context_mids = set(getattr(context, "context_methodology_ids", []) if context else [])

                for methodology in past_solutions:
                    if knowledge_chars >= max_knowledge_chars:
                        break
                    section_lines: list[str] = []
                    # Problem description — what this pattern solves
                    desc = getattr(methodology, "problem_description", "") or ""
                    mid_check = getattr(methodology, "id", None)
                    if desc:
                        if mid_check and mid_check == _primary_mid:
                            section_lines.append(f"### [PRIMARY] Recommended Pattern: {desc[:200]}")
                        elif mid_check and mid_check in _context_mids:
                            section_lines.append(f"### [CONTEXT] Alternative Pattern: {desc[:200]}")
                        else:
                            section_lines.append(f"### Pattern: {desc[:200]}")
                    # Source provenance
                    tags = getattr(methodology, "tags", []) or []
                    source_tags = [t for t in tags if t.startswith("source:")]
                    if source_tags:
                        section_lines.append(f"Source: {source_tags[0].removeprefix('source:')}")
                    # Capability data — rich structured context
                    cap_raw = getattr(methodology, "capability_data", None)
                    cap = {}
                    if isinstance(cap_raw, dict):
                        cap = cap_raw
                    elif isinstance(cap_raw, str) and cap_raw not in ("", "null"):
                        try:
                            parsed = json.loads(cap_raw)
                            if isinstance(parsed, dict):
                                cap = parsed
                        except (json.JSONDecodeError, TypeError):
                            pass
                    applicability = cap.get("applicability")
                    applicability_sketch = ""
                    if isinstance(applicability, dict):
                        applicability_sketch = applicability.get("sketch", "")
                    impl_sketch = cap.get("implementation_sketch") or applicability_sketch
                    triggers = cap.get("activation_triggers") or []
                    if impl_sketch:
                        section_lines.append(f"Implementation approach: {str(impl_sketch)[:600]}")
                    if triggers:
                        trigger_str = ", ".join(str(t) for t in triggers[:5]) if isinstance(triggers, list) else str(triggers)[:200]
                        section_lines.append(f"When to apply: {trigger_str}")
                    # Solution code / methodology notes — the actual pattern
                    sol = getattr(methodology, "solution_code", "") or ""
                    notes = getattr(methodology, "methodology_notes", "") or ""
                    pattern_text = sol or notes

                    # Context pointer for large methodologies
                    # PRIMARY and CONTEXT methodologies get full content (no truncation)
                    mid = getattr(methodology, "id", "unknown")
                    is_primary_or_context = (
                        (mid_check and mid_check == _primary_mid) or
                        (mid_check and mid_check in _context_mids)
                    )
                    if pattern_text and len(pattern_text) > pointer_threshold and not is_primary_or_context:
                        # Truncate with pointer for budget preservation (non-primary only)
                        summary = pattern_text[:600]
                        source_repos = cap.get("source_repos", [])
                        hf_source = next((r for r in source_repos if "huggingface.co" in r), None) if isinstance(source_repos, list) else None
                        if hf_source:
                            pointer = f"[TRUNCATED. Full content: hf://{hf_source}]"
                        else:
                            pointer = f"[TRUNCATED. Full content: methodology_id#{mid}]"
                        section_lines.append(f"Pattern details:\n{summary}\n{pointer}")
                    elif pattern_text and not impl_sketch:
                        section_lines.append(f"Pattern details:\n{pattern_text}")
                    elif pattern_text and impl_sketch:
                        section_lines.append(f"Reference:\n{pattern_text}")

                    if section_lines:
                        section = "\n".join(section_lines)
                        if knowledge_chars + len(section) > max_knowledge_chars:
                            break
                        knowledge_parts.append(section)
                        knowledge_chars += len(section)
                if knowledge_parts:
                    parts.append("\n## OPERATIONAL KNOWLEDGE (PULSE-mined methodologies — MANDATORY)")
                    parts.append(
                        "**DIRECTIVE**: The following knowledge was retrieved from the PULSE knowledge base. "
                        "These are not suggestions — they are operational patterns mined from real codebases. "
                        "You MUST:\n"
                        "1. Read each pattern carefully before writing any code.\n"
                        "2. Apply [PRIMARY] patterns as your default implementation approach.\n"
                        "3. Use [CONTEXT] patterns to cross-check and enrich your solution.\n"
                        "4. Cite which methodology you applied in your response "
                        "(e.g., 'Applied methodology#<id>: <pattern name>').\n"
                        "5. If you deviate from a retrieved pattern, explicitly state WHY "
                        "with a concrete technical reason.\n"
                        "6. DO NOT ignore retrieved knowledge in favor of generic model priors."
                    )
                    # Inject use_immediately_as directives if available
                    for methodology in past_solutions[:len(knowledge_parts)]:
                        use_immediately = None
                        _cap_raw = getattr(methodology, "capability_data", None)
                        if isinstance(_cap_raw, dict):
                            use_immediately = _cap_raw.get("use_immediately_as")
                        elif isinstance(_cap_raw, str) and _cap_raw not in ("", "null"):
                            try:
                                _parsed = json.loads(_cap_raw)
                                if isinstance(_parsed, dict):
                                    use_immediately = _parsed.get("use_immediately_as")
                            except (json.JSONDecodeError, TypeError):
                                pass
                        if use_immediately and isinstance(use_immediately, list):
                            _mid = getattr(methodology, "id", "?")
                            parts.append(f"\n**USE IMMEDIATELY (methodology#{_mid})**:")
                            for directive in use_immediately[:5]:
                                parts.append(f"  - {directive}")
                    parts.extend(knowledge_parts)
                    # Funnel metrics logging
                    self.logger.info(
                        "Knowledge funnel: retrieved=%d, injected=%d, chars=%d, budget=%d",
                        len(past_solutions), len(knowledge_parts),
                        knowledge_chars, max_knowledge_chars,
                    )

        # CAM-SEQ: inject ApplicationPacket guidance when available
        _packets = getattr(context, "application_packets", []) if context else []
        if _packets:
            parts.append("\n## Structured Component Guidance (CAM-SEQ Packets)")
            parts.append(
                "The following pre-analyzed components have been matched to task slots. "
                "Use these as structured implementation guidance."
            )
            for pkt in _packets[:4]:
                pkt_lines = [
                    f"### Slot: {pkt.slot.name} (job: {pkt.slot.abstract_job})",
                    f"Selected component: {pkt.selected.component_id} "
                    f"(confidence: {pkt.selected.confidence:.2f}, fit: {pkt.selected.fit_bucket.value})",
                ]
                if pkt.selected.why_fit:
                    pkt_lines.append(f"Why selected: {'; '.join(pkt.selected.why_fit[:3])}")
                for step in pkt.adaptation_plan[:3]:
                    pkt_lines.append(f"  Adaptation: {step.title} {'[BLOCKING]' if step.blocking else ''}")
                for gate in pkt.proof_plan[:3]:
                    pkt_lines.append(f"  Proof gate: {gate.gate_type} {'(required)' if gate.required else ''}")
                if pkt.negative_memory:
                    pkt_lines.append(f"  Avoid: {'; '.join(pkt.negative_memory[:2])}")
                if pkt.risk_notes:
                    pkt_lines.append(f"  Risk: {'; '.join(pkt.risk_notes[:2])}")
                parts.append("\n".join(pkt_lines))

        if self.can_use_internal_workspace_executor():
            # Include workspace file contents so the model knows what exists
            ws = self._resolve_workspace(task)
            if ws:
                workspace_root = Path(ws)
                if workspace_root.is_dir():
                    file_parts: list[str] = []
                    total_chars = 0
                    max_chars = 12000  # Cap to leave room for output tokens
                    for fpath in sorted(workspace_root.rglob("*")):
                        if not fpath.is_file():
                            continue
                        rel = fpath.relative_to(workspace_root)
                        if ".git" in rel.parts or "__pycache__" in rel.parts or "node_modules" in rel.parts:
                            continue
                        try:
                            content = fpath.read_text(errors="replace")
                        except OSError:
                            continue
                        if total_chars + len(content) > max_chars:
                            file_parts.append(f"\n--- {rel} (truncated, {len(content)} chars) ---")
                            break
                        file_parts.append(f"\n--- {rel} ---\n{content}")
                        total_chars += len(content)
                    if file_parts:
                        parts.append("\n## Existing Repository Files")
                        parts.extend(file_parts)

            parts.append(
                "\n## Required Output Format\n"
                "Return only valid JSON with this shape:\n"
                "{\n"
                '  "summary": "short explanation",\n'
                '  "file_operations": [\n'
                '    {"path": "relative/path.ext", "action": "write", "content": "full file contents"}\n'
                "  ]\n"
                "}\n"
                "Rules:\n"
                "- Use only relative paths inside the target repo.\n"
                "- Do not include markdown fences or prose outside the JSON object.\n"
                "- Use action `write` to create or replace a file.\n"
                "- Use action `delete` only when removal is necessary.\n"
                "- For standalone app requests, do not import CAM runtime code unless explicitly asked."
            )

        # --- Token budget enforcement logging ---
        total_chars = sum(len(p) for p in parts)
        total_tokens_approx = total_chars // 4
        if total_tokens_approx > self._token_budget:
            self.logger.warning(
                "Prompt exceeds token budget: ~%d tokens > %d budget (task=%s)",
                total_tokens_approx, self._token_budget,
                getattr(task.task, 'title', 'unknown'),
            )

        return "\n".join(parts)

    async def _local_health_check(self, agent_name: str) -> AgentHealth:
        """Check if local LLM endpoint (Ollama / MLX-LM) is reachable.

        Both Ollama and mlx_lm.server expose an OpenAI-compatible endpoint.
        We hit GET /v1/models to verify connectivity.
        """
        model = getattr(self, "model", None)
        if not model:
            return AgentHealth(
                agent_id=agent_name,
                available=False,
                mode=AgentMode.LOCAL,
                error="No model configured for local mode in claw.toml",
            )

        local_base_url = getattr(self, "local_base_url", None) or "http://localhost:11434/v1"
        models_url = f"{local_base_url.rstrip('/')}/models"

        try:
            start = time.monotonic()
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                response = await client.get(models_url)
                response.raise_for_status()
            latency = (time.monotonic() - start) * 1000
            return AgentHealth(
                agent_id=agent_name,
                available=True,
                mode=AgentMode.LOCAL,
                version=f"local:{model}",
                latency_ms=latency,
            )
        except httpx.ConnectError:
            return AgentHealth(
                agent_id=agent_name,
                available=False,
                mode=AgentMode.LOCAL,
                error=f"Local LLM not reachable at {models_url}. "
                      f"Start Ollama (`ollama serve`) or MLX-LM (`mlx_lm.server --model ...`).",
            )
        except Exception as e:
            return AgentHealth(
                agent_id=agent_name,
                available=False,
                mode=AgentMode.LOCAL,
                error=str(e),
            )

    def get_metrics(self) -> dict[str, Any]:
        """Return a copy of the agent's runtime metrics."""
        return self._metrics.copy()
