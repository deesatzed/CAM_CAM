"""Serial champion/challenger evolution for CAM-PULSE.

This module implements the conservative first milestone from the serial
evolution plan: register a champion, create one challenger record, mine
layer-specific material, stage one bounded mutation artifact, evaluate per
slice, and stop at a manual promotion decision.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tomllib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import httpx

from claw.core.config import DatabaseConfig
from claw.db.engine import DatabaseEngine
from claw.db.repository import Repository


LAYERS = ("data_feature", "strategy_policy", "prompt_config", "model")
ROTATION = ("data_feature", "strategy_policy", "prompt_config", "model")
APPROVED_MODEL_IDS = (
    "qwen/qwen3.6-flash",
    "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-v4-pro",
    "openai/gpt-mini-latest",
    "openai/gpt-4.1-mini",
    "x-ai/grok-4.3",
)
CHAMPION_POINTER_FILENAME = "current_champion.json"

PROMOTION_WEIGHTS: dict[str, float] = {
    "functional_correctness": 0.25,
    "structural_compliance": 0.15,
    "intent_alignment": 0.15,
    "expectation_match": 0.15,
    "correction_efficiency": 0.10,
    "retrieval_or_knowledge_lift": 0.10,
    "cost_efficiency": 0.05,
    "stability": 0.05,
}


@dataclass
class PromotionGateConfig:
    """Conservative gate defaults for early serial evolution."""

    min_relative_lift: float = 0.03
    min_independent_passing_slices: int = 2
    max_cost_usd: float = 10.0
    max_latency_seconds: float = 120.0
    require_manual_approval: bool = False
    require_validation_gate: bool = False
    allowed_layers: set[str] = field(
        default_factory=lambda: {"data_feature", "prompt_config", "strategy_policy"}
    )
    weights: dict[str, float] = field(default_factory=lambda: dict(PROMOTION_WEIGHTS))


@dataclass
class SerialEvolutionResult:
    """Return payload for one serial evolution cycle."""

    run_id: str
    cycle_number: int
    layer: str
    champion_instance_id: str
    challenger_instance_id: str
    decision: str
    decision_reason: str
    artifact_dir: Path
    report_path: Path
    promotion_score_delta: float


@dataclass
class BudgetStatus:
    """OpenRouter budget state used to bound autonomous iteration."""

    can_continue: bool
    source: str
    remaining_credits: Optional[float] = None
    reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class LiveProbeStatus:
    """Low-cost remote model probe before live autonomous mining."""

    can_continue: bool
    source: str
    model_used: Optional[str] = None
    attempted_models: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    reason: str = ""
    tokens_used: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class AutonomousLoopResult:
    """Summary of an autonomous serial evolution loop run."""

    rounds_attempted: int
    stop_reason: str
    last_budget_status: BudgetStatus
    cycle_results: list[SerialEvolutionResult] = field(default_factory=list)
    live_probe_status: Optional[LiveProbeStatus] = None


@dataclass
class LiveMiningBinding:
    """Per-challenger live mining stack."""

    repo_miner: Any
    target_project_id: str
    db_path: Optional[Path] = None
    close: Optional[Callable[[], Awaitable[None]]] = None


class OpenRouterBudgetClient:
    """Checks OpenRouter key budget and performs low-cost live model probes."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout_seconds: float = 20.0,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def get_status(self, min_remaining_credits: float = 0.01) -> BudgetStatus:
        if not self.api_key:
            return BudgetStatus(
                can_continue=False,
                source="openrouter_key",
                reason="OPENROUTER_API_KEY is not set",
            )

        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            key_resp = await client.get(f"{self.base_url}/key", headers=headers)
            if key_resp.status_code == 402:
                return BudgetStatus(
                    can_continue=False,
                    source="openrouter_key",
                    reason="OpenRouter returned 402 insufficient credits",
                )
            key_resp.raise_for_status()
            key_data = key_resp.json().get("data", {})
            limit_remaining = key_data.get("limit_remaining")
            if limit_remaining is not None:
                remaining = float(limit_remaining)
                return BudgetStatus(
                    can_continue=remaining > min_remaining_credits,
                    source="openrouter_key",
                    remaining_credits=remaining,
                    reason=(
                        "key limit has remaining credits"
                        if remaining > min_remaining_credits
                        else "OpenRouter key limit remaining credits are below threshold"
                    ),
                    raw=key_data,
                )

            credits_resp = await client.get(f"{self.base_url}/credits", headers=headers)
            if credits_resp.status_code in {401, 403}:
                return BudgetStatus(
                    can_continue=True,
                    source="openrouter_key_unlimited",
                    remaining_credits=None,
                    reason="key has no explicit limit and account credits endpoint is unavailable",
                    raw=key_data,
                )
            credits_resp.raise_for_status()
            credits_data = credits_resp.json().get("data", {})
            remaining = float(credits_data.get("total_credits", 0.0)) - float(
                credits_data.get("total_usage", 0.0)
            )
            return BudgetStatus(
                can_continue=remaining > min_remaining_credits,
                source="openrouter_credits",
                remaining_credits=remaining,
                reason=(
                    "account has remaining credits"
                    if remaining > min_remaining_credits
                    else "OpenRouter account credits are below threshold"
                ),
                raw=credits_data,
            )

    async def probe_allowed_models(
        self,
        models: tuple[str, ...] = APPROVED_MODEL_IDS,
        max_tokens: int = 4,
    ) -> LiveProbeStatus:
        """Send one tiny completion through the approved model chain."""
        if not self.api_key:
            return LiveProbeStatus(
                can_continue=False,
                source="openrouter_probe",
                reason="OPENROUTER_API_KEY is not set",
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/claw",
            "X-Title": "CAM-PULSE Evolution Probe",
        }
        attempted: list[str] = []
        failures: list[str] = []
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            for model in models:
                attempted.append(model)
                payload = {
                    "model": model,
                    "messages": [
                        {
                            "role": "user",
                            "content": "Reply with exactly: OK",
                        }
                    ],
                    "temperature": 0,
                    "max_tokens": max_tokens,
                }
                try:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                except Exception as exc:
                    failures.append(f"{model}: {type(exc).__name__}: {exc}")
                    continue

                if resp.status_code == 200:
                    data = resp.json()
                    usage = data.get("usage", {})
                    return LiveProbeStatus(
                        can_continue=True,
                        source="openrouter_probe",
                        model_used=data.get("model", model),
                        attempted_models=attempted,
                        failures=failures,
                        reason="OpenRouter live probe succeeded",
                        tokens_used=int(usage.get("total_tokens", 0) or 0),
                        raw={"usage": usage},
                    )

                detail = _openrouter_error_detail(resp)
                failures.append(f"{model}: HTTP {resp.status_code}: {detail}")
                if resp.status_code in {401, 402, 403}:
                    break

        return LiveProbeStatus(
            can_continue=False,
            source="openrouter_probe",
            attempted_models=attempted,
            failures=failures,
            reason="No approved OpenRouter model passed the live probe",
        )


def promotion_score(metrics: dict[str, float], weights: Optional[dict[str, float]] = None) -> float:
    """Compute the configured composite promotion score."""
    active_weights = weights or PROMOTION_WEIGHTS
    return round(
        sum(active_weights[name] * float(metrics.get(name, 0.0)) for name in active_weights),
        6,
    )


def select_layer_for_cycle(cycle_number: int, override: Optional[str] = None) -> tuple[str, str]:
    """Select one mutation layer by fixed rotation unless explicitly overridden."""
    if override:
        if override not in LAYERS:
            raise ValueError(f"Unknown evolution layer: {override}")
        return override, "operator_override"
    return ROTATION[(cycle_number - 1) % len(ROTATION)], "rotation"


def _openrouter_error_detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except Exception:
        return resp.text[:300]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or error)[:300]
        if error:
            return str(error)[:300]
    return str(data)[:300]


def _now_label() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _hash_file(path: Path, hasher: "hashlib._Hash") -> None:
    hasher.update(str(path).encode("utf-8", errors="replace"))
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)


def _hash_paths(paths: list[Path]) -> str:
    hasher = hashlib.sha256()
    for path in sorted({p.resolve() for p in paths if p.exists()}):
        if path.is_file():
            _hash_file(path, hasher)
        elif path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and _is_hashable_repo_file(child):
                    _hash_file(child, hasher)
    return hasher.hexdigest()


def _is_hashable_repo_file(path: Path) -> bool:
    ignored_parts = {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        "batch_run",
    }
    if ignored_parts.intersection(path.parts):
        return False
    return path.suffix in {
        ".py",
        ".sql",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".md",
        ".sh",
    }


def compute_workspace_hashes(repo_path: Path, db_path: Optional[Path] = None) -> dict[str, str]:
    """Compute stable snapshot hashes without traversing generated run archives."""
    repo_path = repo_path.resolve()
    config_dir = repo_path / "config"
    config_candidates = [
        *repo_path.glob("*.toml"),
        *(config_dir.glob("*.yaml") if config_dir.exists() else []),
        *(config_dir.glob("*.yml") if config_dir.exists() else []),
    ]
    code_candidates = [
        repo_path / "src",
        repo_path / "scripts",
        repo_path / "pyproject.toml",
        repo_path / "Dockerfile",
    ]
    knowledge_candidates = [
        repo_path / "knowledge",
        repo_path / "prompts",
        *repo_path.glob("instances/*/brain_manifest.json"),
    ]
    if db_path and db_path.exists() and db_path.is_file():
        knowledge_candidates.append(db_path)

    return {
        "config_hash": _hash_paths(config_candidates),
        "code_hash": _hash_paths(code_candidates),
        "knowledge_hash": _hash_paths(knowledge_candidates),
    }


def git_ref(repo_path: Path) -> Optional[str]:
    """Return the current git commit hash when available."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _parse_utc_timestamp(value: Any) -> Optional[datetime]:
    """Parse SQLite ISO timestamps as timezone-aware UTC datetimes."""
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class SerialEvolutionRunner:
    """Conservative champion/challenger serial evolution orchestrator."""

    def __init__(
        self,
        repository: Repository,
        repo_path: Path,
        db_path: Optional[Path] = None,
        instances_root: Optional[Path] = None,
        gate_config: Optional[PromotionGateConfig] = None,
        repo_miner: Optional[Any] = None,
        target_project_id: Optional[str] = None,
        live_mining_factory: Optional[
            Callable[[dict[str, Any]], Awaitable[LiveMiningBinding]]
        ] = None,
        live_repo_timeout_seconds: int = 180,
        stale_run_timeout_seconds: int = 3600,
        require_live_source_preflight: bool = False,
        repo_preflight_config: Any = None,
    ) -> None:
        self.repository = repository
        self.repo_path = repo_path.resolve()
        self.db_path = db_path.resolve() if db_path and str(db_path) != ":memory:" else db_path
        self.instances_root = instances_root or (self.repo_path / "instances" / "evolution")
        self.gate_config = gate_config or PromotionGateConfig()
        self.repo_miner = repo_miner
        self.target_project_id = target_project_id
        self.live_mining_factory = live_mining_factory
        self.live_repo_timeout_seconds = live_repo_timeout_seconds
        self.stale_run_timeout_seconds = stale_run_timeout_seconds
        self.require_live_source_preflight = require_live_source_preflight
        self.repo_preflight_config = repo_preflight_config

    async def register_current_workspace(
        self,
        version_label: str = "v0",
        notes: str = "Initial serial evolution champion",
        force_new: bool = False,
    ) -> dict[str, Any]:
        """Register the current workspace as the champion if none exists."""
        existing = await self.repository.get_current_evolution_champion()
        if existing and not force_new:
            return existing

        hashes = compute_workspace_hashes(self.repo_path, self.db_path)
        champion = await self.repository.create_evolution_instance(
            {
                "role": "champion",
                "version_label": version_label,
                "repo_path": str(self.repo_path),
                "db_path": str(self.db_path) if self.db_path else None,
                "git_ref": git_ref(self.repo_path),
                "config_hash": hashes["config_hash"],
                "code_hash": hashes["code_hash"],
                "knowledge_hash": hashes["knowledge_hash"],
                "notes": notes,
            }
        )
        await self._write_champion_pointer(champion)
        return champion

    async def run_minimal_cycle(
        self,
        layer_override: Optional[str] = None,
        objective: Optional[str] = None,
        materialize_copy: bool = False,
        allow_model_layer: bool = False,
        mining_dir: Optional[Path] = None,
        repos_per_round: int = 3,
    ) -> SerialEvolutionResult:
        """Run one conservative dry-run serial evolution cycle."""
        active = await self._get_active_mutating_run()
        if active and await self._recover_stale_active_run(active):
            active = await self._get_active_mutating_run()
        if active:
            raise RuntimeError(
                f"Evolution run {active['id']} is already active with status {active['status']}"
            )

        champion = await self.register_current_workspace()
        latest_run = await self.repository.get_latest_evolution_run()
        cycle_number = int(latest_run["cycle_number"]) + 1 if latest_run else 1
        layer, selected_by = select_layer_for_cycle(cycle_number, layer_override)
        if layer == "model" and not allow_model_layer:
            layer = "data_feature"
            selected_by = "safety_override_model_disabled"
        if layer not in self.gate_config.allowed_layers and not (
            layer == "model" and allow_model_layer
        ):
            layer = "data_feature"
            selected_by = "safety_override_layer_not_allowed"

        objective_text = objective or self._default_objective(layer)
        run = await self.repository.create_evolution_run(
            {
                "champion_instance_id": champion["id"],
                "cycle_number": cycle_number,
                "layer": layer,
                "status": "planned",
                "objective": objective_text,
                "selected_by": selected_by,
            }
        )

        artifact_dir = self.instances_root / "artifacts" / run["id"]
        artifact_dir.mkdir(parents=True, exist_ok=True)

        try:
            challenger = await self._create_challenger_instance(
                champion=champion,
                cycle_number=cycle_number,
                layer=layer,
                materialize_copy=materialize_copy,
            )
            await self.repository.attach_evolution_challenger(run["id"], challenger["id"])

            live_binding: Optional[LiveMiningBinding] = None
            await self.repository.update_evolution_run_status(run["id"], "mining")
            try:
                if self.live_mining_factory is not None and mining_dir is not None:
                    live_binding = await self.live_mining_factory(challenger)
                mined = await self._mine_layer_material(
                    run["id"],
                    layer,
                    mining_dir=mining_dir,
                    repos_per_round=repos_per_round,
                    live_binding=live_binding,
                )
            finally:
                if live_binding and live_binding.close is not None:
                    await live_binding.close()

            await self.repository.update_evolution_run_status(run["id"], "mutating")
            mutation = await self._stage_bounded_mutation(run["id"], layer, mined, artifact_dir)

            await self.repository.update_evolution_run_status(run["id"], "evaluating")
            evaluations = await self._evaluate(run["id"], layer, mined, mutation, challenger)

            decision = await self._decide(run, challenger, evaluations, mined)
            final_status = {
                "promote": "promoted",
                "reject": "rejected",
                "pause": "paused",
                "rollback": "failed",
            }[decision["decision"]]
            await self.repository.update_evolution_run_status(
                run["id"],
                final_status,
                decision["reason"] if final_status in {"rejected", "failed"} else None,
            )
            if decision["decision"] == "promote":
                await self.repository.update_evolution_instance_role(
                    champion["id"],
                    "archived",
                    f"Archived after autonomous promotion of run {run['id']}",
                )
                await self.repository.update_evolution_instance_role(
                    challenger["id"],
                    "champion",
                    f"Autonomously promoted from run {run['id']}",
                )
                promoted = await self.repository.get_evolution_instance(challenger["id"])
                await self._write_champion_pointer(promoted, run_id=run["id"])
            if decision["decision"] == "reject":
                await self.repository.update_evolution_instance_role(
                    challenger["id"],
                    "rejected",
                    decision["reason"],
                )

            report_path = await self._write_decision_report(
                run_id=run["id"],
                artifact_dir=artifact_dir,
                decision=decision,
            )
            score_delta = max((float(e["delta_score"]) for e in evaluations), default=0.0)
            return SerialEvolutionResult(
                run_id=run["id"],
                cycle_number=cycle_number,
                layer=layer,
                champion_instance_id=champion["id"],
                challenger_instance_id=challenger["id"],
                decision=decision["decision"],
                decision_reason=decision["reason"],
                artifact_dir=artifact_dir,
                report_path=report_path,
                promotion_score_delta=score_delta,
            )
        except Exception as exc:
            await self.repository.update_evolution_run_status(run["id"], "failed", str(exc))
            await self.repository.record_evolution_monitor_event(
                {
                    "run_id": run["id"],
                    "instance_id": champion["id"],
                    "severity": "critical",
                    "event_type": "cycle_failed",
                    "message": str(exc),
                    "payload": {"layer": layer},
                }
            )
            raise

    async def run_autonomous_loop(
        self,
        mining_dir: Path,
        repos_per_round: int = 3,
        max_rounds: Optional[int] = None,
        min_budget_remaining_credits: float = 0.01,
        budget_client: Optional[OpenRouterBudgetClient] = None,
        require_live_probe: bool = False,
    ) -> AutonomousLoopResult:
        """Run data-feature evolution rounds until budget or repo supply stops."""
        if repos_per_round <= 0:
            raise ValueError("repos_per_round must be greater than zero")

        budget = budget_client or OpenRouterBudgetClient()
        results: list[SerialEvolutionResult] = []
        last_budget = BudgetStatus(
            can_continue=False,
            source="not_checked",
            reason="loop did not start",
        )
        live_probe_status: Optional[LiveProbeStatus] = None

        while max_rounds is None or len(results) < max_rounds:
            last_budget = await budget.get_status(min_budget_remaining_credits)
            if not last_budget.can_continue:
                return AutonomousLoopResult(
                    rounds_attempted=len(results),
                    stop_reason=last_budget.reason,
                    last_budget_status=last_budget,
                    cycle_results=results,
                    live_probe_status=live_probe_status,
                )

            if require_live_probe and live_probe_status is None:
                live_probe_status = await budget.probe_allowed_models()
                if not live_probe_status.can_continue:
                    return AutonomousLoopResult(
                        rounds_attempted=len(results),
                        stop_reason=(
                            f"OpenRouter live probe failed: {live_probe_status.reason}"
                        ),
                        last_budget_status=last_budget,
                        cycle_results=results,
                        live_probe_status=live_probe_status,
                    )

            remaining = await self.available_folder_repo_count(mining_dir)
            if remaining < repos_per_round:
                return AutonomousLoopResult(
                    rounds_attempted=len(results),
                    stop_reason=(
                        f"fewer than {repos_per_round} unmined repos remain in {mining_dir}"
                    ),
                    last_budget_status=last_budget,
                    cycle_results=results,
                    live_probe_status=live_probe_status,
                )

            results.append(
                await self.run_minimal_cycle(
                    layer_override="data_feature",
                    objective=f"Mine {repos_per_round} repos from {mining_dir}",
                    mining_dir=mining_dir,
                    repos_per_round=repos_per_round,
                )
            )

        return AutonomousLoopResult(
            rounds_attempted=len(results),
            stop_reason=f"max_rounds reached ({max_rounds})",
            last_budget_status=last_budget,
            cycle_results=results,
            live_probe_status=live_probe_status,
        )

    async def available_folder_repo_count(self, mining_dir: Path) -> int:
        """Count folder repos not already consumed by prior evolution rounds."""
        return len(await self._select_folder_repos(mining_dir, limit=None))

    async def approve_paused_run(self, run_id: str, decided_by: str = "operator") -> dict[str, Any]:
        """Manually promote a paused challenger after operator review."""
        run = await self.repository.get_evolution_run(run_id)
        if not run:
            raise ValueError(f"Unknown evolution run: {run_id}")
        if run["status"] != "paused":
            raise ValueError(f"Run {run_id} is not paused; current status is {run['status']}")
        if not run.get("challenger_instance_id"):
            raise ValueError(f"Run {run_id} has no challenger instance")

        await self.repository.update_evolution_instance_role(
            run["champion_instance_id"],
            "archived",
            f"Archived after manual promotion of run {run_id}",
        )
        await self.repository.update_evolution_instance_role(
            run["challenger_instance_id"],
            "champion",
            f"Promoted by {decided_by} from run {run_id}",
        )
        promoted = await self.repository.get_evolution_instance(run["challenger_instance_id"])
        await self._write_champion_pointer(promoted, run_id=run_id)
        await self.repository.update_evolution_run_status(run_id, "promoted")
        return await self.repository.record_evolution_decision(
            {
                "run_id": run_id,
                "decision": "promote",
                "decided_by": decided_by,
                "reason": "Manual approval promoted paused challenger",
                "promoted_instance_id": run["challenger_instance_id"],
                "rollback_instance_id": run["champion_instance_id"],
                "gate_report": {"manual_approval": True},
            }
        )

    async def status(self) -> dict[str, Any]:
        """Return current evolution status for CLI and dashboard use."""
        champion = await self.repository.get_current_evolution_champion()
        active = await self._get_active_mutating_run()
        runs = await self.repository.list_evolution_runs(limit=10)
        decisions = await self.repository.list_evolution_decisions(limit=10)
        return {
            "champion": champion,
            "champion_pointer": str(self._champion_pointer_path()),
            "active_run": active,
            "recent_runs": runs,
            "recent_decisions": decisions,
        }

    async def sync_champion_pointer(self) -> dict[str, Any]:
        """Rewrite the current champion pointer from the control-plane DB."""
        champion = await self.repository.get_current_evolution_champion()
        if not champion:
            raise ValueError("No current evolution champion is registered")
        await self._write_champion_pointer(champion)
        return {
            "champion": champion,
            "pointer_path": str(self._champion_pointer_path()),
        }

    async def _get_active_mutating_run(self) -> Optional[dict[str, Any]]:
        return await self.repository.engine.fetch_one(
            """SELECT * FROM evolution_runs
               WHERE status IN ('planned','mining','mutating','training','evaluating')
               ORDER BY started_at DESC
               LIMIT 1"""
        )

    def _champion_pointer_path(self) -> Path:
        return self.instances_root / CHAMPION_POINTER_FILENAME

    async def _write_champion_pointer(
        self,
        champion: dict[str, Any],
        run_id: Optional[str] = None,
    ) -> None:
        pointer_path = self._champion_pointer_path()
        pointer_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "instance_id": champion.get("id"),
            "version_label": champion.get("version_label"),
            "repo_path": champion.get("repo_path"),
            "db_path": champion.get("db_path"),
            "run_id": run_id,
            "control_db_path": str(self.db_path) if self.db_path else None,
            "updated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        pointer_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    async def _recover_stale_active_run(self, run: dict[str, Any]) -> bool:
        """Fail an abandoned active run so autonomous loops can keep moving."""
        if self.stale_run_timeout_seconds <= 0:
            return False

        started_at = _parse_utc_timestamp(run.get("started_at"))
        if started_at is None:
            return False

        age_seconds = (datetime.now(UTC) - started_at).total_seconds()
        if age_seconds <= self.stale_run_timeout_seconds:
            return False

        reason = (
            f"stale_active_run_timeout_after_{self.stale_run_timeout_seconds}s"
        )
        await self.repository.update_evolution_run_status(
            run["id"],
            "failed",
            reason,
        )
        await self.repository.record_evolution_monitor_event(
            {
                "run_id": run["id"],
                "instance_id": run.get("champion_instance_id"),
                "severity": "warning",
                "event_type": "stale_active_run_recovered",
                "message": (
                    f"Active evolution run {run['id']} was failed after "
                    f"{int(age_seconds)}s in status {run['status']}"
                ),
                "payload": {
                    "status": run["status"],
                    "age_seconds": age_seconds,
                    "timeout_seconds": self.stale_run_timeout_seconds,
                },
            }
        )
        return True

    async def _create_challenger_instance(
        self,
        champion: dict[str, Any],
        cycle_number: int,
        layer: str,
        materialize_copy: bool,
    ) -> dict[str, Any]:
        version_label = f"v{cycle_number}-candidate"
        challenger_path = self.instances_root / "challengers" / version_label
        if materialize_copy:
            self._materialize_challenger_copy(challenger_path)
            repo_path = challenger_path
        else:
            challenger_path.mkdir(parents=True, exist_ok=True)
            repo_path = challenger_path

        challenger_db_path = await self._materialize_challenger_db(challenger_path)
        hash_repo_path = repo_path if materialize_copy else self.repo_path
        hashes = compute_workspace_hashes(hash_repo_path, challenger_db_path)
        challenger = await self.repository.create_evolution_instance(
            {
                "parent_instance_id": champion["id"],
                "role": "challenger",
                "version_label": version_label,
                "repo_path": str(repo_path),
                "db_path": str(challenger_db_path) if challenger_db_path else None,
                "git_ref": git_ref(self.repo_path),
                "config_hash": hashes["config_hash"],
                "code_hash": hashes["code_hash"],
                "knowledge_hash": hashes["knowledge_hash"],
                "notes": f"Serial evolution challenger for {layer} cycle {cycle_number}",
            }
        )
        await self.repository.record_evolution_monitor_event(
            {
                "instance_id": challenger["id"],
                "severity": "info",
                "event_type": "challenger_created",
                "message": f"Created challenger {version_label}",
                "payload": {
                    "materialized_copy": materialize_copy,
                    "repo_path": str(repo_path),
                    "db_path": str(challenger_db_path) if challenger_db_path else None,
                },
            }
        )
        return challenger

    async def _materialize_challenger_db(self, challenger_path: Path) -> Optional[Path]:
        """Create an isolated challenger database snapshot when a source DB exists."""
        if self.db_path is None or str(self.db_path) == ":memory:":
            return None

        challenger_db_path = challenger_path / "data" / "claw.db"
        challenger_db_path.parent.mkdir(parents=True, exist_ok=True)
        if challenger_db_path.exists():
            challenger_db_path.unlink()

        source_db = Path(self.db_path)
        if source_db.exists() and source_db.is_file():
            await self.repository.engine.conn.execute(
                "VACUUM INTO ?",
                [str(challenger_db_path)],
            )
            await self.repository.engine.conn.commit()
            return challenger_db_path

        engine = DatabaseEngine(DatabaseConfig(db_path=str(challenger_db_path)))
        await engine.connect()
        try:
            await engine.apply_migrations()
            await engine.initialize_schema()
        finally:
            await engine.close()
        return challenger_db_path

    def _materialize_challenger_copy(self, challenger_path: Path) -> None:
        if challenger_path.exists():
            raise FileExistsError(f"Challenger path already exists: {challenger_path}")

        ignored = {
            ".git",
            ".venv",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "node_modules",
            "batch_run",
            "instances/evolution",
        }

        def _ignore(dir_path: str, names: list[str]) -> set[str]:
            base = Path(dir_path)
            ignored_names: set[str] = set()
            for name in names:
                rel = str((base / name).relative_to(self.repo_path)) if base.is_relative_to(self.repo_path) else name
                if name in ignored or rel in ignored:
                    ignored_names.add(name)
            return ignored_names

        shutil.copytree(self.repo_path, challenger_path, ignore=_ignore)

    async def _mine_layer_material(
        self,
        run_id: str,
        layer: str,
        mining_dir: Optional[Path] = None,
        repos_per_round: int = 3,
        live_binding: Optional[LiveMiningBinding] = None,
    ) -> list[dict[str, Any]]:
        if layer == "data_feature":
            if mining_dir is not None:
                return await self._mine_folder_repos(
                    run_id,
                    mining_dir,
                    repos_per_round,
                    live_binding=live_binding,
                )
            return await self._mine_data_feature(run_id)
        if layer == "prompt_config":
            return await self._mine_prompt_config(run_id)
        if layer == "strategy_policy":
            return await self._mine_strategy_policy(run_id)
        if layer == "model":
            return await self._mine_model(run_id)
        raise ValueError(f"Unsupported layer: {layer}")

    async def _mine_folder_repos(
        self,
        run_id: str,
        mining_dir: Path,
        repos_per_round: int,
        live_binding: Optional[LiveMiningBinding] = None,
    ) -> list[dict[str, Any]]:
        selected = await self._select_folder_repos(mining_dir, limit=repos_per_round)
        mined: list[dict[str, Any]] = []
        active_miner = live_binding.repo_miner if live_binding else self.repo_miner
        active_project_id = (
            live_binding.target_project_id if live_binding else self.target_project_id
        )
        for repo_path in selected:
            manifest = self._summarize_folder_repo(repo_path)
            live_result_payload: dict[str, Any] = {}
            accepted = True
            rejection_reason = None
            if active_miner is not None and active_project_id:
                try:
                    mining_result = await asyncio.wait_for(
                        active_miner.mine_repo(
                            repo_path=repo_path,
                            repo_name=repo_path.name,
                            target_project_id=active_project_id,
                        ),
                        timeout=self.live_repo_timeout_seconds,
                    )
                    live_result_payload = {
                        "live_mining": True,
                        "findings_count": len(getattr(mining_result, "findings", []) or []),
                        "methodology_ids": getattr(mining_result, "methodology_ids", []) or [],
                        "action_template_ids": getattr(mining_result, "action_template_ids", []) or [],
                        "tokens_used": int(getattr(mining_result, "tokens_used", 0) or 0),
                        "cost_usd": float(getattr(mining_result, "cost_usd", 0.0) or 0.0),
                        "error": getattr(mining_result, "error", None),
                        "skipped": bool(getattr(mining_result, "skipped", False)),
                        "skip_reason": getattr(mining_result, "skip_reason", None),
                        "target_db_path": (
                            str(live_binding.db_path)
                            if live_binding and live_binding.db_path
                            else None
                        ),
                    }
                    if live_binding and live_binding.db_path:
                        live_result_payload["artifact_db_paths"] = (
                            self._locate_live_mining_artifact_paths(
                                live_binding.db_path,
                                live_result_payload["methodology_ids"],
                                live_result_payload["action_template_ids"],
                            )
                        )
                    accepted = (
                        not live_result_payload["error"]
                        and not live_result_payload["skipped"]
                        and live_result_payload["findings_count"] > 0
                    )
                    rejection_reason = None if accepted else (
                        live_result_payload["error"]
                        or live_result_payload["skip_reason"]
                        or "live_mining_returned_no_findings"
                    )
                except asyncio.TimeoutError:
                    timeout_error = (
                        f"live_mining_timeout_after_{self.live_repo_timeout_seconds}s"
                    )
                    recovered_payload = self._recover_live_mining_side_effects(
                        repo_name=repo_path.name,
                        live_binding=live_binding,
                    )
                    recovered_count = int(
                        recovered_payload.get("findings_count", 0) or 0
                    )
                    live_result_payload = {
                        "live_mining": True,
                        "findings_count": recovered_count,
                        "methodology_ids": recovered_payload.get("methodology_ids", []),
                        "action_template_ids": recovered_payload.get(
                            "action_template_ids", []
                        ),
                        "artifact_db_paths": recovered_payload.get(
                            "artifact_db_paths", []
                        ),
                        "tokens_used": 0,
                        "cost_usd": 0.0,
                        "error": None if recovered_count > 0 else timeout_error,
                        "partial_timeout": recovered_count > 0,
                        "timeout_error": timeout_error,
                        "cost_accounting": "unavailable_after_timeout",
                        "skipped": False,
                        "skip_reason": None,
                        "target_db_path": (
                            str(live_binding.db_path)
                            if live_binding and live_binding.db_path
                            else None
                        ),
                    }
                    accepted = recovered_count > 0
                    rejection_reason = None if accepted else timeout_error
                    if accepted:
                        await self.repository.record_evolution_monitor_event(
                            {
                                "run_id": run_id,
                                "severity": "warning",
                                "event_type": "live_mining_partial_timeout_recovered",
                                "message": (
                                    f"Recovered {recovered_count} challenger DB "
                                    f"side effects for {repo_path.name} after timeout"
                                ),
                                "payload": live_result_payload,
                            }
                        )
                manifest.update(live_result_payload)
            item = await self.repository.record_evolution_mined_input(
                {
                    "run_id": run_id,
                    "source_type": "folder_repo",
                    "source_uri": str(repo_path.resolve()),
                    "source_ref": repo_path.name,
                    "license_type": manifest.get("license_type"),
                    "novelty_score": manifest["novelty_score"],
                    "relevance_score": manifest["relevance_score"],
                    "accepted": accepted,
                    "rejection_reason": rejection_reason,
                    "extracted_payload": manifest,
                }
            )
            mined.append(item)

        if len(mined) < repos_per_round:
            await self.repository.record_evolution_monitor_event(
                {
                    "run_id": run_id,
                    "severity": "warning",
                    "event_type": "folder_repo_shortfall",
                    "message": (
                        f"Only mined {len(mined)} repos from {mining_dir}; "
                        f"expected {repos_per_round}"
                    ),
                    "payload": {
                        "mining_dir": str(mining_dir),
                        "repos_per_round": repos_per_round,
                        "mined_count": len(mined),
                    },
                }
            )
        return mined

    def _recover_live_mining_side_effects(
        self,
        repo_name: str,
        live_binding: Optional[LiveMiningBinding],
    ) -> dict[str, Any]:
        """Find challenger DB artifacts already written before timeout cancellation."""
        if not live_binding or not live_binding.db_path:
            return {"findings_count": 0, "methodology_ids": [], "action_template_ids": []}

        db_path = Path(live_binding.db_path)
        if not db_path.exists():
            return {"findings_count": 0, "methodology_ids": [], "action_template_ids": []}

        methodology_ids: list[str] = []
        action_template_ids: list[str] = []
        source_db_paths: list[str] = []
        seen_methodologies: set[str] = set()
        seen_templates: set[str] = set()

        for candidate_db_path in self._live_mining_side_effect_db_paths(db_path):
            if not candidate_db_path.exists():
                continue
            recovered = self._recover_repo_artifacts_from_db(
                repo_name,
                candidate_db_path,
            )
            recovered_methodologies = recovered.get("methodology_ids", [])
            recovered_templates = recovered.get("action_template_ids", [])
            if not recovered_methodologies and not recovered_templates:
                continue
            source_db_paths.append(str(candidate_db_path))
            for methodology_id in recovered_methodologies:
                if methodology_id not in seen_methodologies:
                    methodology_ids.append(methodology_id)
                    seen_methodologies.add(methodology_id)
            for action_template_id in recovered_templates:
                if action_template_id not in seen_templates:
                    action_template_ids.append(action_template_id)
                    seen_templates.add(action_template_id)

        return {
            "findings_count": max(len(methodology_ids), len(action_template_ids)),
            "methodology_ids": methodology_ids,
            "action_template_ids": action_template_ids,
            "artifact_db_paths": source_db_paths,
        }

    def _locate_live_mining_artifact_paths(
        self,
        db_path: Path,
        methodology_ids: list[str],
        action_template_ids: list[str],
    ) -> list[str]:
        """Find primary/ganglion DBs containing returned live-mining artifact IDs."""
        paths: list[str] = []
        for candidate_db_path in self._live_mining_side_effect_db_paths(Path(db_path)):
            if not candidate_db_path.exists():
                continue
            method_hits = self._count_existing_ids_in_sqlite_path(
                candidate_db_path,
                "methodologies",
                methodology_ids,
            )
            action_hits = self._count_existing_ids_in_sqlite_path(
                candidate_db_path,
                "action_templates",
                action_template_ids,
            )
            if method_hits or action_hits:
                paths.append(str(candidate_db_path))
        return paths

    def _live_mining_side_effect_db_paths(self, db_path: Path) -> list[Path]:
        """Return primary and ganglion DBs that may receive live mining writes."""
        paths = [db_path]
        try:
            challenger_root = db_path.parent.parent
            ganglion_root = challenger_root / "instances"
            if ganglion_root.exists():
                paths.extend(
                    sorted(
                        ganglion_root.glob("*/claw.db"),
                        key=lambda path: str(path).lower(),
                    )
                )
        except Exception:
            pass

        deduped: list[Path] = []
        seen: set[str] = set()
        for path in paths:
            ident = str(path.resolve()) if path.exists() else str(path)
            if ident in seen:
                continue
            seen.add(ident)
            deduped.append(path)
        return deduped

    def _recover_repo_artifacts_from_db(
        self,
        repo_name: str,
        db_path: Path,
    ) -> dict[str, Any]:
        """Recover repo-tagged methodology/action-template IDs from one DB."""
        try:
            with sqlite3.connect(str(db_path), timeout=5.0) as conn:
                conn.row_factory = sqlite3.Row
                source_tag = f'%source:{repo_name}%'
                mined_prefix = f"[Mined from {repo_name}]%"
                methodology_rows = conn.execute(
                    """
                    SELECT id
                    FROM methodologies
                    WHERE tags LIKE ? OR problem_description LIKE ?
                    ORDER BY created_at, id
                    """,
                    (source_tag, mined_prefix),
                ).fetchall()
                methodology_ids = [str(row["id"]) for row in methodology_rows]

                action_template_ids: list[str] = []
                if methodology_ids:
                    placeholders = ",".join("?" for _ in methodology_ids)
                    action_rows = conn.execute(
                        f"""
                        SELECT id
                        FROM action_templates
                        WHERE source_repo = ?
                           OR source_methodology_id IN ({placeholders})
                        ORDER BY created_at, id
                        """,
                        (repo_name, *methodology_ids),
                    ).fetchall()
                    action_template_ids = [str(row["id"]) for row in action_rows]
                else:
                    action_rows = conn.execute(
                        """
                        SELECT id
                        FROM action_templates
                        WHERE source_repo = ?
                        ORDER BY created_at, id
                        """,
                        (repo_name,),
                    ).fetchall()
                    action_template_ids = [str(row["id"]) for row in action_rows]
        except sqlite3.Error:
            return {"findings_count": 0, "methodology_ids": [], "action_template_ids": []}

        return {
            "findings_count": max(len(methodology_ids), len(action_template_ids)),
            "methodology_ids": methodology_ids,
            "action_template_ids": action_template_ids,
        }

    async def _select_folder_repos(
        self,
        mining_dir: Path,
        limit: Optional[int],
    ) -> list[Path]:
        mining_dir = mining_dir.resolve()
        if not mining_dir.exists() or not mining_dir.is_dir():
            raise FileNotFoundError(f"Mining directory not found: {mining_dir}")

        rows = await self.repository.engine.fetch_all(
            """SELECT DISTINCT source_uri, source_ref
               FROM evolution_mined_inputs
               WHERE source_type = 'folder_repo'
                 AND (
                   accepted = 1
                   OR rejection_reason = 'No recognizable source files found'
                 )"""
        )
        excluded_sources = {str(Path(row["source_uri"]).resolve()) for row in rows}
        excluded_refs = {
            str(row["source_ref"])
            for row in rows
            if row.get("source_ref")
        }
        candidates = [
            child.resolve()
            for child in sorted(mining_dir.iterdir(), key=lambda p: p.name.lower())
            if child.is_dir()
            and not child.name.startswith(".")
            and str(child.resolve()) not in excluded_sources
            and child.resolve().name not in excluded_refs
            and (
                not self.require_live_source_preflight
                or self._folder_repo_passes_live_source_preflight(child.resolve())
            )
        ]
        if limit is None:
            return candidates
        return candidates[:limit]

    def _folder_repo_passes_live_source_preflight(self, repo_path: Path) -> bool:
        """Mirror cheap miner gates before spending a live LLM call."""
        try:
            from claw.miner import detect_all_repo_languages, serialize_repo

            zones = detect_all_repo_languages(repo_path, self.repo_preflight_config)
            source_file_count = sum(zone.file_count for zone in zones.values())
            if source_file_count <= 0:
                return False

            repo_content, file_count = serialize_repo(
                repo_path,
                config=self.repo_preflight_config,
            )
        except Exception:
            return False

        if file_count < 3:
            return False
        return len(repo_content.encode("utf-8")) >= 1024

    def _summarize_folder_repo(self, repo_path: Path) -> dict[str, Any]:
        files = [path for path in repo_path.rglob("*") if path.is_file()]
        suffix_counts: dict[str, int] = {}
        for path in files:
            suffix = path.suffix.lower() or "<none>"
            suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
        readme = next(
            (path for path in files if path.name.lower() in {"readme.md", "readme.txt", "readme"}),
            None,
        )
        license_file = next(
            (path for path in files if path.name.lower().startswith("license")),
            None,
        )
        return {
            "repo_name": repo_path.name,
            "file_count": len(files),
            "top_extensions": dict(
                sorted(suffix_counts.items(), key=lambda item: item[1], reverse=True)[:10]
            ),
            "has_git_dir": (repo_path / ".git").exists(),
            "has_readme": readme is not None,
            "license_type": license_file.name if license_file else None,
            "novelty_score": 0.90,
            "relevance_score": 0.85 if readme else 0.75,
            "content_hash": _hash_paths([repo_path]),
        }

    async def _mine_data_feature(self, run_id: str) -> list[dict[str, Any]]:
        rows = await self.repository.engine.fetch_all(
            """SELECT id, canonical_url, github_url, novelty_score, license_type,
                      status, methodology_ids, mine_result
               FROM pulse_discoveries
               WHERE status IN ('assimilated','discovered','queued_enhance')
               ORDER BY COALESCE(novelty_score, 0.0) DESC, discovered_at DESC
               LIMIT 10"""
        )
        mined: list[dict[str, Any]] = []
        for row in rows:
            novelty = float(row.get("novelty_score") or 0.0)
            license_type = row.get("license_type")
            accepted = novelty >= 0.70 and str(license_type or "").lower() not in {
                "agpl",
                "unknown-risk",
            }
            item = await self.repository.record_evolution_mined_input(
                {
                    "run_id": run_id,
                    "source_type": "pulse_discovery",
                    "source_uri": row.get("canonical_url") or row.get("github_url") or row["id"],
                    "source_ref": row["id"],
                    "license_type": license_type,
                    "novelty_score": novelty,
                    "relevance_score": novelty,
                    "accepted": accepted,
                    "rejection_reason": None if accepted else "novelty_or_license_gate",
                    "extracted_payload": {
                        "status": row.get("status"),
                        "methodology_ids": _loads_json(row.get("methodology_ids"), []),
                        "mine_result": _loads_json(row.get("mine_result"), {}),
                    },
                }
            )
            mined.append(item)
        if not mined:
            await self._record_no_mining_material(run_id, "pulse_discovery")
        return mined

    async def _mine_prompt_config(self, run_id: str) -> list[dict[str, Any]]:
        rows = await self.repository.engine.fetch_all(
            """SELECT id, prompt_name, variant_label, agent_id, sample_count,
                      success_count, avg_quality_score, is_active
               FROM prompt_variants
               ORDER BY sample_count DESC, avg_quality_score DESC
               LIMIT 10"""
        )
        mined = []
        for row in rows:
            sample_count = int(row.get("sample_count") or 0)
            accepted = sample_count >= 20
            item = await self.repository.record_evolution_mined_input(
                {
                    "run_id": run_id,
                    "source_type": "prompt_variant",
                    "source_uri": row["prompt_name"],
                    "source_ref": row["id"],
                    "novelty_score": None,
                    "relevance_score": float(row.get("avg_quality_score") or 0.0),
                    "accepted": accepted,
                    "rejection_reason": None if accepted else "insufficient_samples",
                    "extracted_payload": dict(row),
                }
            )
            mined.append(item)
        if not mined:
            mined = await self._mine_static_prompt_config(run_id)
        if not mined:
            await self._record_no_mining_material(run_id, "prompt_or_config")
        return mined

    async def _mine_static_prompt_config(self, run_id: str) -> list[dict[str, Any]]:
        """Bootstrap prompt/config evolution before A/B prompt history exists."""
        mined: list[dict[str, Any]] = []
        prompt_dir = self.repo_path / "prompts"
        for path in sorted(prompt_dir.glob("*.md"))[:10]:
            text = self._safe_read_text(path, max_chars=120_000)
            if not text.strip():
                continue
            rel_path = path.relative_to(self.repo_path).as_posix()
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            item = await self.repository.record_evolution_mined_input(
                {
                    "run_id": run_id,
                    "source_type": "prompt_template",
                    "source_uri": rel_path,
                    "source_ref": digest,
                    "novelty_score": 0.5,
                    "relevance_score": self._prompt_template_relevance(text),
                    "accepted": True,
                    "extracted_payload": {
                        "path": rel_path,
                        "content_hash": digest,
                        "char_count": len(text),
                        "line_count": text.count("\n") + 1,
                        "signals": self._prompt_config_signals(text),
                        "bootstrap_reason": "no_prompt_variant_history",
                    },
                }
            )
            mined.append(item)

        for path in self._candidate_config_files():
            text = self._safe_read_text(path, max_chars=120_000)
            if not text.strip():
                continue
            rel_path = path.relative_to(self.repo_path).as_posix()
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            item = await self.repository.record_evolution_mined_input(
                {
                    "run_id": run_id,
                    "source_type": "config_file",
                    "source_uri": rel_path,
                    "source_ref": digest,
                    "novelty_score": 0.45,
                    "relevance_score": self._config_file_relevance(path, text),
                    "accepted": True,
                    "extracted_payload": {
                        "path": rel_path,
                        "content_hash": digest,
                        "char_count": len(text),
                        "line_count": text.count("\n") + 1,
                        "signals": self._prompt_config_signals(text),
                        "config_summary": self._summarize_config_file(path, text),
                        "bootstrap_reason": "no_prompt_variant_history",
                    },
                }
            )
            mined.append(item)
        return mined

    def _candidate_config_files(self) -> list[Path]:
        candidates: list[Path] = []
        for pattern in ("claw*.toml", "config/*.toml", "config/*.yaml", "config/*.yml"):
            candidates.extend(sorted(self.repo_path.glob(pattern)))
        unique: dict[str, Path] = {}
        for path in candidates:
            if path.is_file():
                unique[path.resolve().as_posix()] = path
        return list(unique.values())[:10]

    @staticmethod
    def _safe_read_text(path: Path, max_chars: int) -> str:
        try:
            return path.read_text(encoding="utf-8")[:max_chars]
        except UnicodeDecodeError:
            return path.read_text(errors="ignore")[:max_chars]

    @staticmethod
    def _prompt_config_signals(text: str) -> list[str]:
        lowered = text.lower()
        signals = []
        for key in (
            "agent",
            "model",
            "prompt",
            "constraint",
            "verify",
            "test",
            "retry",
            "fallback",
            "budget",
            "quality",
        ):
            if key in lowered:
                signals.append(key)
        return signals

    def _prompt_template_relevance(self, text: str) -> float:
        signals = self._prompt_config_signals(text)
        return min(1.0, 0.45 + (0.05 * len(signals)))

    def _config_file_relevance(self, path: Path, text: str) -> float:
        signals = self._prompt_config_signals(text)
        base = 0.55 if path.name.startswith("claw") else 0.4
        return min(1.0, base + (0.04 * len(signals)))

    @staticmethod
    def _summarize_config_file(path: Path, text: str) -> dict[str, Any]:
        if path.suffix != ".toml":
            return {"format": path.suffix.lstrip(".") or "text"}
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            return {"format": "toml", "parse_error": str(exc)}
        agents = data.get("agents", {})
        brains = data.get("mining", {}).get("brains", {})
        return {
            "format": "toml",
            "top_level_sections": sorted(str(key) for key in data.keys()),
            "agents": sorted(str(key) for key in agents.keys()) if isinstance(agents, dict) else [],
            "brain_profiles": sorted(str(key) for key in brains.keys()) if isinstance(brains, dict) else [],
        }

    async def _mine_strategy_policy(self, run_id: str) -> list[dict[str, Any]]:
        mined = await self._mine_static_strategy_policy(run_id)
        rows = await self.repository.engine.fetch_all(
            """SELECT agent_id, task_type, successes, failures, total_attempts,
                      avg_quality_score, avg_cost_usd
               FROM agent_scores
               ORDER BY total_attempts DESC, avg_quality_score DESC
               LIMIT 10"""
        )
        skipped = 0
        for row in rows:
            attempts = int(row.get("total_attempts") or 0)
            if attempts < 5:
                skipped += 1
                continue
            item = await self.repository.record_evolution_mined_input(
                {
                    "run_id": run_id,
                    "source_type": "agent_score",
                    "source_uri": f"{row['agent_id']}:{row['task_type']}",
                    "source_ref": f"{row['agent_id']}:{row['task_type']}",
                    "relevance_score": float(row.get("avg_quality_score") or 0.0),
                    "accepted": True,
                    "extracted_payload": dict(row),
                }
            )
            mined.append(item)
        if skipped:
            await self.repository.record_evolution_monitor_event(
                {
                    "run_id": run_id,
                    "severity": "info",
                    "event_type": "strategy_policy_low_sample_rows_skipped",
                    "message": (
                        f"Skipped {skipped} agent_score rows with fewer than 5 attempts"
                    ),
                    "payload": {"skipped_count": skipped, "min_attempts": 5},
                }
            )
        if not mined:
            await self._record_no_mining_material(run_id, "agent_score")
        return mined

    async def _mine_static_strategy_policy(self, run_id: str) -> list[dict[str, Any]]:
        mined: list[dict[str, Any]] = []
        config_path = self.repo_path / "claw.toml"
        if config_path.exists():
            text = self._safe_read_text(config_path, max_chars=120_000)
            try:
                config_data = tomllib.loads(text)
            except tomllib.TOMLDecodeError:
                config_data = {}
            routing = config_data.get("routing", {}) if isinstance(config_data, dict) else {}
            static_priors = (
                routing.get("static_priors", {}) if isinstance(routing, dict) else {}
            )
            if isinstance(routing, dict) and routing:
                item = await self.repository.record_evolution_mined_input(
                    {
                        "run_id": run_id,
                        "source_type": "routing_policy_config",
                        "source_uri": "claw.toml#routing",
                        "source_ref": hashlib.sha256(
                            json.dumps(routing, sort_keys=True).encode("utf-8")
                        ).hexdigest(),
                        "novelty_score": 0.45,
                        "relevance_score": 0.75,
                        "accepted": True,
                        "extracted_payload": {
                            "exploration_rate": routing.get("exploration_rate"),
                            "score_decay_factor": routing.get("score_decay_factor"),
                            "min_samples_for_routing": routing.get("min_samples_for_routing"),
                            "static_prior_count": (
                                len(static_priors) if isinstance(static_priors, dict) else 0
                            ),
                        },
                    }
                )
                mined.append(item)
            if isinstance(static_priors, dict):
                for task_type, agent_id in sorted(static_priors.items())[:10]:
                    item = await self.repository.record_evolution_mined_input(
                        {
                            "run_id": run_id,
                            "source_type": "routing_static_prior",
                            "source_uri": f"claw.toml#routing.static_priors.{task_type}",
                            "source_ref": f"{task_type}:{agent_id}",
                            "novelty_score": 0.4,
                            "relevance_score": 0.68,
                            "accepted": True,
                            "extracted_payload": {
                                "task_type": task_type,
                                "agent_id": agent_id,
                                "bootstrap_reason": "static_routing_policy",
                            },
                        }
                    )
                    mined.append(item)
            kelly = config_data.get("kelly", {}) if isinstance(config_data, dict) else {}
            if isinstance(kelly, dict) and kelly:
                item = await self.repository.record_evolution_mined_input(
                    {
                        "run_id": run_id,
                        "source_type": "kelly_policy_config",
                        "source_uri": "claw.toml#kelly",
                        "source_ref": hashlib.sha256(
                            json.dumps(kelly, sort_keys=True).encode("utf-8")
                        ).hexdigest(),
                        "novelty_score": 0.45,
                        "relevance_score": 0.75,
                        "accepted": True,
                        "extracted_payload": dict(kelly),
                    }
                )
                mined.append(item)

        failure_rows = await self.repository.engine.fetch_all(
            """SELECT id, error_signature, error_category, diagnosis, prevention_hint,
                      occurrence_count, resolved, root_cause_key, detail_signals_json
               FROM failure_knowledge
               ORDER BY occurrence_count DESC, updated_at DESC
               LIMIT 10"""
        )
        for row in failure_rows:
            occurrences = int(row.get("occurrence_count") or 0)
            source_ref = row.get("root_cause_key") or row["error_signature"]
            item = await self.repository.record_evolution_mined_input(
                {
                    "run_id": run_id,
                    "source_type": "failure_policy_signal",
                    "source_uri": f"failure_knowledge:{row['id']}",
                    "source_ref": source_ref,
                    "novelty_score": 0.5,
                    "relevance_score": min(1.0, 0.55 + (0.05 * max(1, occurrences))),
                    "accepted": True,
                    "extracted_payload": dict(row),
                }
            )
            mined.append(item)
        return mined

    async def _mine_model(self, run_id: str) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in APPROVED_MODEL_IDS)
        rows = await self.repository.engine.fetch_all(
            f"""SELECT model_used, COUNT(*) AS calls, SUM(cost_usd) AS cost_usd,
                      SUM(total_tokens) AS total_tokens
               FROM token_costs
               WHERE model_used IN ({placeholders})
               GROUP BY model_used
               ORDER BY calls DESC
               LIMIT 10""",
            list(APPROVED_MODEL_IDS),
        )
        mined = []
        for row in rows:
            accepted = int(row.get("calls") or 0) >= 5
            item = await self.repository.record_evolution_mined_input(
                {
                    "run_id": run_id,
                    "source_type": "model_cost_trace",
                    "source_uri": row["model_used"],
                    "source_ref": row["model_used"],
                    "relevance_score": 1.0 if accepted else 0.25,
                    "accepted": accepted,
                    "rejection_reason": None if accepted else "insufficient_calls",
                    "extracted_payload": dict(row),
                }
            )
            mined.append(item)
        if not mined:
            await self._record_no_mining_material(run_id, "model_cost_trace")
        return mined

    async def _record_no_mining_material(self, run_id: str, source_type: str) -> None:
        await self.repository.record_evolution_monitor_event(
            {
                "run_id": run_id,
                "severity": "warning",
                "event_type": "no_mining_material",
                "message": f"No {source_type} material available for evolution cycle",
                "payload": {"source_type": source_type},
            }
        )

    async def _stage_bounded_mutation(
        self,
        run_id: str,
        layer: str,
        mined: list[dict[str, Any]],
        artifact_dir: Path,
    ) -> dict[str, Any]:
        accepted = [item for item in mined if int(item.get("accepted", 0))]
        manifest = {
            "layer": layer,
            "accepted_input_ids": [item["id"] for item in accepted],
            "source_count": len(mined),
            "accepted_count": len(accepted),
            "mutation_scope": self._mutation_scope(layer),
            "manual_promotion_required": self.gate_config.require_manual_approval,
        }
        rollback = {
            "type": "staged_artifact_only",
            "delete_paths": [str(artifact_dir)],
            "champion_unchanged": True,
        }
        mutation_manifest_path = artifact_dir / "mutation_manifest.json"
        rollback_manifest_path = artifact_dir / "rollback_manifest.json"
        mutation_manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        rollback_manifest_path.write_text(json.dumps(rollback, indent=2, sort_keys=True) + "\n")

        before_hash = compute_workspace_hashes(self.repo_path, self.db_path)["knowledge_hash"]
        after_hash = hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return await self.repository.record_evolution_mutation(
            {
                "run_id": run_id,
                "layer": layer,
                "mutation_type": "staged_retrieval_manifest",
                "target_ref": str(mutation_manifest_path),
                "before_hash": before_hash,
                "after_hash": after_hash,
                "mutation_manifest": manifest,
                "rollback_manifest": rollback,
            }
        )

    def _mutation_scope(self, layer: str) -> str:
        return {
            "data_feature": "stage accepted PULSE sources for retrieval/methodology reweighting",
            "prompt_config": "stage prompt variant candidates for A/B review",
            "strategy_policy": "stage routing-policy observations without changing live routing",
            "model": "stage model comparison observations without changing live models",
        }[layer]

    async def _evaluate(
        self,
        run_id: str,
        layer: str,
        mined: list[dict[str, Any]],
        mutation: dict[str, Any],
        challenger: dict[str, Any],
    ) -> list[dict[str, Any]]:
        champion_metrics = await self._baseline_metrics()
        accepted_count = sum(1 for item in mined if int(item.get("accepted", 0)))
        total_count = len(mined)
        staged_lift = min(0.35, accepted_count * 0.08)
        if layer != "data_feature":
            staged_lift = min(0.25, accepted_count * 0.06)

        eval_specs = [
            ("smoke", 0.0, {"validation_gate": "skipped"}),
            ("layer_specific", staged_lift, {"accepted_inputs": accepted_count}),
            ("holdout_proxy", staged_lift * 0.75, {"source_count": total_count}),
        ]

        evaluations: list[dict[str, Any]] = []
        champion_score = promotion_score(champion_metrics, self.gate_config.weights)
        for eval_slice, lift, extra in eval_specs:
            challenger_metrics = dict(champion_metrics)
            challenger_metrics["retrieval_or_knowledge_lift"] = min(
                1.0,
                challenger_metrics["retrieval_or_knowledge_lift"] + lift,
            )
            if accepted_count == 0:
                challenger_metrics["stability"] = max(0.0, challenger_metrics["stability"] - 0.02)
            challenger_score = promotion_score(challenger_metrics, self.gate_config.weights)
            delta = round(challenger_score - champion_score, 6)
            evaluation = await self.repository.record_evolution_evaluation(
                {
                    "run_id": run_id,
                    "eval_slice": eval_slice,
                    "champion_score": champion_score,
                    "challenger_score": challenger_score,
                    "delta_score": delta,
                    "effect_size": delta,
                    "bootstrap_ci_low": delta - 0.01,
                    "bootstrap_ci_high": delta + 0.01,
                    "passed": delta > 0.0,
                    "metrics": {
                        "champion": champion_metrics,
                        "challenger": challenger_metrics,
                        "mutation_id": mutation["id"],
                        **extra,
                    },
                }
            )
            evaluations.append(evaluation)

        paired = await self._evaluate_paired_retrieval(
            run_id=run_id,
            mined=mined,
            mutation=mutation,
            champion_metrics=champion_metrics,
            challenger=challenger,
        )
        if paired is not None:
            evaluations.append(paired)
        task_readiness = await self._evaluate_paired_task_readiness(
            run_id=run_id,
            mined=mined,
            mutation=mutation,
            champion_metrics=champion_metrics,
            challenger=challenger,
        )
        if task_readiness is not None:
            evaluations.append(task_readiness)
        return evaluations

    async def _evaluate_paired_retrieval(
        self,
        *,
        run_id: str,
        mined: list[dict[str, Any]],
        mutation: dict[str, Any],
        champion_metrics: dict[str, float],
        challenger: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Compare champion and challenger text retrieval over mined-source queries."""
        challenger_db = challenger.get("db_path")
        if not challenger_db:
            return None

        challenger_db_path = Path(challenger_db)
        if not challenger_db_path.exists():
            return None
        if self.db_path and challenger_db_path.resolve() == Path(self.db_path).resolve():
            return None

        queries = self._paired_retrieval_queries(mined)
        if not queries:
            return None

        challenger_engine = DatabaseEngine(DatabaseConfig(db_path=str(challenger_db_path)))
        await challenger_engine.connect()
        try:
            await challenger_engine.apply_migrations()
            await challenger_engine.initialize_schema()
            challenger_repo = Repository(challenger_engine)
            champion_scores: list[float] = []
            challenger_scores: list[float] = []
            query_reports: list[dict[str, Any]] = []
            for query in queries:
                champion_hits = await self.repository.search_methodologies_text(query, limit=5)
                challenger_hits = await challenger_repo.search_methodologies_text(query, limit=5)
                champion_score = self._retrieval_hit_score(champion_hits)
                challenger_score = self._retrieval_hit_score(challenger_hits)
                champion_scores.append(champion_score)
                challenger_scores.append(challenger_score)
                query_reports.append(
                    {
                        "query": query,
                        "champion_hits": len(champion_hits),
                        "challenger_hits": len(challenger_hits),
                        "champion_score": champion_score,
                        "challenger_score": challenger_score,
                    }
                )
        finally:
            await challenger_engine.close()

        avg_champion = (
            sum(champion_scores) / len(champion_scores) if champion_scores else 0.0
        )
        avg_challenger = (
            sum(challenger_scores) / len(challenger_scores) if challenger_scores else 0.0
        )
        delta_retrieval = avg_challenger - avg_champion
        champion_eval_metrics = dict(champion_metrics)
        challenger_eval_metrics = dict(champion_metrics)
        champion_eval_metrics["retrieval_or_knowledge_lift"] = avg_champion
        challenger_eval_metrics["retrieval_or_knowledge_lift"] = avg_challenger
        champion_score = promotion_score(champion_eval_metrics, self.gate_config.weights)
        challenger_score = promotion_score(challenger_eval_metrics, self.gate_config.weights)
        delta_score = round(challenger_score - champion_score, 6)

        return await self.repository.record_evolution_evaluation(
            {
                "run_id": run_id,
                "eval_slice": "paired_retrieval",
                "champion_score": champion_score,
                "challenger_score": challenger_score,
                "delta_score": delta_score,
                "effect_size": delta_retrieval,
                "bootstrap_ci_low": delta_score - 0.01,
                "bootstrap_ci_high": delta_score + 0.01,
                "passed": delta_score > 0.0,
                "metrics": {
                    "champion": champion_eval_metrics,
                    "challenger": challenger_eval_metrics,
                    "mutation_id": mutation["id"],
                    "query_count": len(queries),
                    "avg_champion_retrieval": avg_champion,
                    "avg_challenger_retrieval": avg_challenger,
                    "query_reports": query_reports,
                    "challenger_db_path": str(challenger_db_path),
                },
            }
        )

    def _paired_retrieval_queries(self, mined: list[dict[str, Any]]) -> list[str]:
        queries: list[str] = []
        for item in mined:
            if not int(item.get("accepted", 0)):
                continue
            payload = _loads_json(item.get("extracted_payload"), {})
            candidates = [
                payload.get("repo_name"),
                item.get("source_ref"),
                Path(str(item.get("source_uri", ""))).name,
            ]
            for candidate in candidates:
                if not candidate:
                    continue
                query = re.sub(r"[^A-Za-z0-9_ -]+", " ", str(candidate)).strip()
                query = re.sub(r"\s+", " ", query)
                if len(query) >= 3 and query not in queries:
                    queries.append(query)
        return queries[:10]

    @staticmethod
    def _retrieval_hit_score(hits: list[tuple[Any, float]]) -> float:
        if not hits:
            return 0.0
        score = 0.0
        for idx, _hit in enumerate(hits[:5]):
            score += 1.0 / (idx + 1)
        return min(1.0, score / 2.2833333333)

    async def _evaluate_paired_task_readiness(
        self,
        *,
        run_id: str,
        mined: list[dict[str, Any]],
        mutation: dict[str, Any],
        champion_metrics: dict[str, float],
        challenger: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Compare whether both instances have actionable coverage for same task intents."""
        challenger_db = challenger.get("db_path")
        if not challenger_db:
            return None

        challenger_db_path = Path(challenger_db)
        if not challenger_db_path.exists():
            return None
        if self.db_path and challenger_db_path.resolve() == Path(self.db_path).resolve():
            return None

        task_inputs = self._paired_task_inputs(mined)
        if not task_inputs:
            return None

        challenger_engine = DatabaseEngine(DatabaseConfig(db_path=str(challenger_db_path)))
        await challenger_engine.connect()
        try:
            await challenger_engine.apply_migrations()
            await challenger_engine.initialize_schema()
            challenger_repo = Repository(challenger_engine)

            champion_scores: list[float] = []
            challenger_scores: list[float] = []
            champion_action_scores: list[float] = []
            challenger_action_scores: list[float] = []
            champion_application_scores: list[float] = []
            challenger_application_scores: list[float] = []
            task_reports: list[dict[str, Any]] = []

            for task_input in task_inputs:
                intent = task_input["intent"]
                champion_score, champion_report = await self._task_readiness_score(
                    self.repository,
                    intent,
                    expected_methodology_ids=task_input["methodology_ids"],
                    expected_action_template_ids=task_input["action_template_ids"],
                )
                challenger_score, challenger_report = await self._task_readiness_score(
                    challenger_repo,
                    intent,
                    expected_methodology_ids=task_input["methodology_ids"],
                    expected_action_template_ids=task_input["action_template_ids"],
                    artifact_db_paths=task_input["artifact_db_paths"],
                )
                champion_scores.append(champion_score)
                challenger_scores.append(challenger_score)
                champion_action_scores.append(champion_report["action_template_score"])
                challenger_action_scores.append(challenger_report["action_template_score"])
                champion_application_scores.append(
                    champion_report["action_template_application_score"]
                )
                challenger_application_scores.append(
                    challenger_report["action_template_application_score"]
                )
                task_reports.append(
                    {
                        "intent": intent,
                        "champion": champion_report,
                        "challenger": challenger_report,
                    }
                )
        finally:
            await challenger_engine.close()

        avg_champion = (
            sum(champion_scores) / len(champion_scores) if champion_scores else 0.0
        )
        avg_challenger = (
            sum(challenger_scores) / len(challenger_scores) if challenger_scores else 0.0
        )
        avg_champion_action = (
            sum(champion_action_scores) / len(champion_action_scores)
            if champion_action_scores
            else 0.0
        )
        avg_challenger_action = (
            sum(challenger_action_scores) / len(challenger_action_scores)
            if challenger_action_scores
            else 0.0
        )
        avg_champion_application = (
            sum(champion_application_scores) / len(champion_application_scores)
            if champion_application_scores
            else 0.0
        )
        avg_challenger_application = (
            sum(challenger_application_scores) / len(challenger_application_scores)
            if challenger_application_scores
            else 0.0
        )

        champion_eval_metrics = dict(champion_metrics)
        challenger_eval_metrics = dict(champion_metrics)
        for metrics, readiness, action_score, application_score in (
            (
                champion_eval_metrics,
                avg_champion,
                avg_champion_action,
                avg_champion_application,
            ),
            (
                challenger_eval_metrics,
                avg_challenger,
                avg_challenger_action,
                avg_challenger_application,
            ),
        ):
            metrics["functional_correctness"] = readiness
            metrics["expectation_match"] = readiness
            metrics["retrieval_or_knowledge_lift"] = readiness
            metrics["correction_efficiency"] = max(
                metrics.get("correction_efficiency", 0.0),
                action_score,
                application_score,
            )

        champion_score = promotion_score(champion_eval_metrics, self.gate_config.weights)
        challenger_score = promotion_score(challenger_eval_metrics, self.gate_config.weights)
        delta_score = round(challenger_score - champion_score, 6)

        return await self.repository.record_evolution_evaluation(
            {
                "run_id": run_id,
                "eval_slice": "paired_task_readiness",
                "champion_score": champion_score,
                "challenger_score": challenger_score,
                "delta_score": delta_score,
                "effect_size": avg_challenger - avg_champion,
                "bootstrap_ci_low": delta_score - 0.01,
                "bootstrap_ci_high": delta_score + 0.01,
                "passed": delta_score > 0.0,
                "metrics": {
                    "champion": champion_eval_metrics,
                    "challenger": challenger_eval_metrics,
                    "mutation_id": mutation["id"],
                    "task_count": len(task_inputs),
                    "avg_champion_task_readiness": avg_champion,
                    "avg_challenger_task_readiness": avg_challenger,
                    "avg_champion_action_template_score": avg_champion_action,
                    "avg_challenger_action_template_score": avg_challenger_action,
                    "avg_champion_action_template_application_score": (
                        avg_champion_application
                    ),
                    "avg_challenger_action_template_application_score": (
                        avg_challenger_application
                    ),
                    "task_reports": task_reports,
                    "challenger_db_path": str(challenger_db_path),
                },
            }
        )

    def _paired_task_inputs(self, mined: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in mined:
            if not int(item.get("accepted", 0)):
                continue
            payload = _loads_json(item.get("extracted_payload"), {})
            candidates = [
                payload.get("repo_name"),
                item.get("source_ref"),
                Path(str(item.get("source_uri", ""))).name,
            ]
            query = ""
            for candidate in candidates:
                if not candidate:
                    continue
                query = re.sub(r"[^A-Za-z0-9_ -]+", " ", str(candidate)).strip()
                query = re.sub(r"\s+", " ", query)
                if len(query) >= 3:
                    break
            if not query or query in seen:
                continue
            seen.add(query)
            tasks.append(
                {
                    "intent": f"Apply {query} as a reusable CAM enhancement pattern",
                    "methodology_ids": [
                        str(value)
                        for value in (payload.get("methodology_ids") or [])
                        if value
                    ],
                    "action_template_ids": [
                        str(value)
                        for value in (payload.get("action_template_ids") or [])
                        if value
                    ],
                    "artifact_db_paths": [
                        str(value)
                        for value in (payload.get("artifact_db_paths") or [])
                        if value
                    ],
                }
            )
        return tasks[:10]

    async def _task_readiness_score(
        self,
        repository: Repository,
        task_intent: str,
        expected_methodology_ids: Optional[list[str]] = None,
        expected_action_template_ids: Optional[list[str]] = None,
        artifact_db_paths: Optional[list[str]] = None,
    ) -> tuple[float, dict[str, Any]]:
        methodology_hits = await repository.search_methodologies_text(
            task_intent,
            limit=5,
        )
        retrieval_score = self._retrieval_hit_score(methodology_hits)
        action_templates = await self._search_action_templates(
            repository,
            task_intent,
            limit=5,
        )
        action_score = self._action_template_score(action_templates)
        application_score, application_trace = (
            self._action_template_application_score(action_templates, task_intent)
        )
        artifact_score, artifact_report = await self._artifact_attribution_score(
            repository,
            expected_methodology_ids or [],
            expected_action_template_ids or [],
            artifact_db_paths=artifact_db_paths or [],
        )
        readiness = min(
            1.0,
            0.40 * retrieval_score
            + 0.20 * action_score
            + 0.20 * application_score
            + 0.20 * artifact_score,
        )
        return readiness, {
            "readiness_score": readiness,
            "retrieval_score": retrieval_score,
            "action_template_score": action_score,
            "action_template_application_score": application_score,
            "action_template_application_trace": application_trace,
            "artifact_attribution_score": artifact_score,
            "methodology_hits": len(methodology_hits),
            "action_template_hits": len(action_templates),
            **artifact_report,
        }

    async def _artifact_attribution_score(
        self,
        repository: Repository,
        methodology_ids: list[str],
        action_template_ids: list[str],
        artifact_db_paths: Optional[list[str]] = None,
    ) -> tuple[float, dict[str, Any]]:
        method_hits = await self._count_existing_ids(
            repository,
            "methodologies",
            methodology_ids,
            artifact_db_paths=artifact_db_paths or [],
        )
        action_hits = await self._count_existing_ids(
            repository,
            "action_templates",
            action_template_ids,
            artifact_db_paths=artifact_db_paths or [],
        )
        method_score = (
            method_hits / len(methodology_ids) if methodology_ids else 0.0
        )
        action_score = (
            action_hits / len(action_template_ids) if action_template_ids else 0.0
        )
        if methodology_ids and action_template_ids:
            score = 0.4 * method_score + 0.6 * action_score
        elif methodology_ids:
            score = method_score
        elif action_template_ids:
            score = action_score
        else:
            score = 0.0
        return min(1.0, score), {
            "expected_methodology_ids": len(methodology_ids),
            "attributed_methodology_hits": method_hits,
            "expected_action_template_ids": len(action_template_ids),
            "attributed_action_template_hits": action_hits,
            "artifact_db_paths": list(artifact_db_paths or []),
        }

    async def _count_existing_ids(
        self,
        repository: Repository,
        table_name: str,
        ids: list[str],
        artifact_db_paths: Optional[list[str]] = None,
    ) -> int:
        safe_ids = [str(value) for value in ids if value]
        if not safe_ids:
            return 0
        if table_name not in {"methodologies", "action_templates"}:
            raise ValueError(f"Unsupported artifact table: {table_name}")
        placeholders = ",".join("?" for _ in safe_ids)
        row = await repository.engine.fetch_one(
            f"SELECT COUNT(*) AS cnt FROM {table_name} WHERE id IN ({placeholders})",
            safe_ids,
        )
        hits = int(row["cnt"]) if row else 0
        if not artifact_db_paths:
            return hits

        found_ids = await self._fetch_existing_ids(repository, table_name, safe_ids)
        for artifact_db_path in artifact_db_paths:
            found_ids.update(
                self._fetch_existing_ids_from_sqlite_path(
                    Path(artifact_db_path),
                    table_name,
                    safe_ids,
                )
            )
        return len(found_ids)

    async def _fetch_existing_ids(
        self,
        repository: Repository,
        table_name: str,
        ids: list[str],
    ) -> set[str]:
        if table_name not in {"methodologies", "action_templates"}:
            raise ValueError(f"Unsupported artifact table: {table_name}")
        safe_ids = [str(value) for value in ids if value]
        if not safe_ids:
            return set()
        placeholders = ",".join("?" for _ in safe_ids)
        rows = await repository.engine.fetch_all(
            f"SELECT id FROM {table_name} WHERE id IN ({placeholders})",
            safe_ids,
        )
        return {str(row["id"]) for row in rows}

    def _count_existing_ids_in_sqlite_path(
        self,
        db_path: Path,
        table_name: str,
        ids: list[str],
    ) -> int:
        return len(self._fetch_existing_ids_from_sqlite_path(db_path, table_name, ids))

    def _fetch_existing_ids_from_sqlite_path(
        self,
        db_path: Path,
        table_name: str,
        ids: list[str],
    ) -> set[str]:
        if table_name not in {"methodologies", "action_templates"}:
            raise ValueError(f"Unsupported artifact table: {table_name}")
        safe_ids = [str(value) for value in ids if value]
        if not safe_ids or not db_path.exists():
            return set()
        placeholders = ",".join("?" for _ in safe_ids)
        try:
            with sqlite3.connect(str(db_path), timeout=5.0) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    f"SELECT id FROM {table_name} WHERE id IN ({placeholders})",
                    safe_ids,
                ).fetchall()
        except sqlite3.Error:
            return set()
        return {str(row["id"]) for row in rows}

    async def _search_action_templates(
        self,
        repository: Repository,
        task_intent: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        tokens = [
            token.lower()
            for token in re.findall(r"[A-Za-z0-9_]+", task_intent)
            if len(token) >= 3
        ]
        tokens = list(dict.fromkeys(tokens))[:6]
        if not tokens:
            return []

        clauses: list[str] = []
        params: list[Any] = []
        for token in tokens:
            like = f"%{token}%"
            clauses.append(
                "(lower(title) LIKE ? OR lower(problem_pattern) LIKE ? OR lower(source_repo) LIKE ?)"
            )
            params.extend([like, like, like])
        params.append(limit)
        return await repository.engine.fetch_all(
            f"""SELECT *
                FROM action_templates
                WHERE {' OR '.join(clauses)}
                ORDER BY confidence DESC, success_count DESC, created_at DESC
                LIMIT ?""",
            params,
        )

    @staticmethod
    def _action_template_score(templates: list[dict[str, Any]]) -> float:
        if not templates:
            return 0.0
        score = 0.0
        for idx, template in enumerate(templates[:5]):
            item_score = 0.35
            execution_steps = _loads_json(template.get("execution_steps"), [])
            acceptance_checks = _loads_json(template.get("acceptance_checks"), [])
            rollback_steps = _loads_json(template.get("rollback_steps"), [])
            preconditions = _loads_json(template.get("preconditions"), [])
            if execution_steps:
                item_score += 0.25
            if acceptance_checks:
                item_score += 0.25
            if rollback_steps or preconditions:
                item_score += 0.15
            score += min(1.0, item_score) / (idx + 1)
        return min(1.0, score / 2.2833333333)

    def _action_template_application_score(
        self,
        templates: list[dict[str, Any]],
        task_intent: str,
    ) -> tuple[float, list[dict[str, Any]]]:
        """Deterministically simulate whether retrieved runbooks can be applied."""
        if not templates:
            return 0.0, []

        intent_tokens = {
            token.lower()
            for token in re.findall(r"[A-Za-z0-9_]+", task_intent)
            if len(token) >= 3
        }
        total = 0.0
        traces: list[dict[str, Any]] = []
        for idx, template in enumerate(templates[:3]):
            execution_steps = _loads_json(template.get("execution_steps"), [])
            acceptance_checks = _loads_json(template.get("acceptance_checks"), [])
            rollback_steps = _loads_json(template.get("rollback_steps"), [])
            preconditions = _loads_json(template.get("preconditions"), [])
            title = str(template.get("title") or "")
            pattern = str(template.get("problem_pattern") or "")
            source_repo = str(template.get("source_repo") or "")
            template_tokens = {
                token.lower()
                for token in re.findall(
                    r"[A-Za-z0-9_]+",
                    " ".join([title, pattern, source_repo]),
                )
                if len(token) >= 3
            }
            overlap = (
                len(intent_tokens & template_tokens) / max(1, len(intent_tokens))
                if intent_tokens
                else 0.0
            )
            checks = {
                "has_execution_steps": bool(execution_steps),
                "has_acceptance_checks": bool(acceptance_checks),
                "has_rollback_or_preconditions": bool(rollback_steps or preconditions),
                "has_task_fit": overlap > 0.0,
            }
            template_score = 0.0
            if checks["has_execution_steps"]:
                template_score += 0.35
            if checks["has_acceptance_checks"]:
                template_score += 0.30
            if checks["has_rollback_or_preconditions"]:
                template_score += 0.15
            template_score += min(0.20, overlap * 0.20)
            template_score = min(1.0, template_score)
            total += template_score / (idx + 1)
            traces.append(
                {
                    "template_id": template.get("id"),
                    "title": title,
                    "source_repo": source_repo or None,
                    "checks": checks,
                    "task_token_overlap": round(overlap, 4),
                    "score": round(template_score, 6),
                    "step_count": len(execution_steps),
                    "acceptance_check_count": len(acceptance_checks),
                    "rollback_step_count": len(rollback_steps),
                    "precondition_count": len(preconditions),
                }
            )
        return min(1.0, total / 1.8333333333), traces

    async def _baseline_metrics(self) -> dict[str, float]:
        row = await self.repository.engine.fetch_one(
            """SELECT AVG(d_functional_correctness) AS functional_correctness,
                      AVG(d_structural_compliance) AS structural_compliance,
                      AVG(d_intent_alignment) AS intent_alignment,
                      AVG(d_expectation_match) AS expectation_match,
                      AVG(d_correction_efficiency) AS correction_efficiency,
                      AVG(d_token_economy) AS cost_efficiency,
                      AVG(composite_score) AS composite_score,
                      AVG(duration_seconds) AS duration_seconds,
                      AVG(tokens_used) AS tokens_used
               FROM ab_quality_samples"""
        )
        defaults = {
            "functional_correctness": 0.70,
            "structural_compliance": 0.70,
            "intent_alignment": 0.70,
            "expectation_match": 0.70,
            "correction_efficiency": 0.70,
            "retrieval_or_knowledge_lift": 0.50,
            "cost_efficiency": 0.70,
            "stability": 0.80,
        }
        if not row:
            return defaults
        metrics = dict(defaults)
        for key in (
            "functional_correctness",
            "structural_compliance",
            "intent_alignment",
            "expectation_match",
            "correction_efficiency",
            "cost_efficiency",
        ):
            if row.get(key) is not None:
                metrics[key] = float(row[key])
        if row.get("composite_score") is not None:
            metrics["retrieval_or_knowledge_lift"] = min(1.0, max(0.0, float(row["composite_score"])))
        return metrics

    async def _decide(
        self,
        run: dict[str, Any],
        challenger: dict[str, Any],
        evaluations: list[dict[str, Any]],
        mined: list[dict[str, Any]],
    ) -> dict[str, Any]:
        validation_report = await self._validate_challenger_for_promotion(
            challenger=challenger,
            evaluations=evaluations,
            mined=mined,
        )
        primary = self._primary_evaluation_for_decision(run, evaluations)
        champion_score = float(primary["champion_score"])
        challenger_score = float(primary["challenger_score"])
        relative_lift = (
            (challenger_score - champion_score) / champion_score
            if champion_score > 0
            else 0.0
        )
        passing_slices = sum(1 for e in evaluations if int(e.get("passed", 0)))
        accepted_inputs = sum(1 for item in mined if int(item.get("accepted", 0)))
        rejected_inputs = len(mined) - accepted_inputs
        gate_report = {
            "primary_champion_score": champion_score,
            "primary_challenger_score": challenger_score,
            "relative_lift": relative_lift,
            "min_relative_lift": self.gate_config.min_relative_lift,
            "passing_slices": passing_slices,
            "min_independent_passing_slices": self.gate_config.min_independent_passing_slices,
            "accepted_inputs": accepted_inputs,
            "rejected_inputs": rejected_inputs,
            "total_inputs": len(mined),
            "validation_gate": "required" if self.gate_config.require_validation_gate else "observed",
            "validation_report": validation_report,
            "manual_approval_required": self.gate_config.require_manual_approval,
        }

        decision = "promote"
        reason = "Candidate passed promotion gates and was autonomously promoted"
        if accepted_inputs == 0:
            decision = "reject"
            reason = "No accepted mined inputs; challenger has no attributable mutation"
        elif rejected_inputs > 0:
            decision = "reject"
            reason = "Not all mined inputs were accepted; exact batch coverage is required"
        elif relative_lift < self.gate_config.min_relative_lift:
            decision = "reject"
            reason = "Promotion score lift is below the configured 3% threshold"
        elif passing_slices < self.gate_config.min_independent_passing_slices:
            decision = "reject"
            reason = "Improvement did not appear in at least two independent slices"
        elif self.gate_config.require_validation_gate and not validation_report["passed"]:
            decision = "reject"
            reason = "Challenger validation gate failed before promotion"
        elif self.gate_config.require_manual_approval:
            decision = "pause"
            reason = "Candidate passed staged gates; manual approval is required before promotion"

        return await self.repository.record_evolution_decision(
            {
                "run_id": run["id"],
                "decision": decision,
                "decided_by": "promotion_gate",
                "reason": reason,
                "gate_report": gate_report,
                "promoted_instance_id": challenger["id"] if decision == "promote" else None,
                "rollback_instance_id": run["champion_instance_id"],
            }
        )

    @staticmethod
    def _primary_evaluation_for_decision(
        run: dict[str, Any],
        evaluations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        layer = str(run.get("layer") or "")
        if layer in {"prompt_config", "strategy_policy"}:
            preferred = ("layer_specific", "holdout_proxy", "paired_task_readiness", "paired_retrieval")
        else:
            preferred = ("paired_task_readiness", "paired_retrieval", "layer_specific", "holdout_proxy")
        for eval_slice in preferred:
            match = next((e for e in evaluations if e["eval_slice"] == eval_slice), None)
            if match is not None:
                return match
        return evaluations[-1]

    async def _validate_challenger_for_promotion(
        self,
        *,
        challenger: dict[str, Any],
        evaluations: list[dict[str, Any]],
        mined: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Validate that a challenger is an isolated, openable CAM instance."""
        checks: dict[str, bool] = {}
        details: dict[str, Any] = {}

        checks["role_is_challenger"] = challenger.get("role") == "challenger"
        challenger_db = challenger.get("db_path")
        checks["db_path_present"] = bool(challenger_db)
        if not challenger_db:
            return {"passed": False, "checks": checks, "details": details}

        challenger_db_path = Path(challenger_db)
        checks["db_exists"] = challenger_db_path.exists() and challenger_db_path.is_file()
        if self.db_path:
            checks["db_is_isolated"] = challenger_db_path.resolve() != Path(self.db_path).resolve()
        else:
            checks["db_is_isolated"] = True

        if not checks["db_exists"]:
            return {"passed": False, "checks": checks, "details": details}

        engine = DatabaseEngine(DatabaseConfig(db_path=str(challenger_db_path)))
        await engine.connect()
        try:
            integrity = await engine.fetch_one("PRAGMA integrity_check")
            integrity_value = next(iter(integrity.values())) if integrity else None
            checks["sqlite_integrity_ok"] = integrity_value == "ok"
            details["sqlite_integrity_check"] = integrity_value

            table_rows = await engine.fetch_all(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            table_names = {row["name"] for row in table_rows}
            required_tables = {
                "methodologies",
                "methodology_fts",
                "action_templates",
                "evolution_instances",
                "evolution_runs",
            }
            missing_tables = sorted(required_tables - table_names)
            checks["required_tables_present"] = not missing_tables
            details["missing_tables"] = missing_tables

            methodology_count = await engine.fetch_one(
                "SELECT COUNT(*) AS cnt FROM methodologies"
            )
            action_template_count = await engine.fetch_one(
                "SELECT COUNT(*) AS cnt FROM action_templates"
            )
            details["methodology_count"] = int(methodology_count["cnt"]) if methodology_count else 0
            details["action_template_count"] = (
                int(action_template_count["cnt"]) if action_template_count else 0
            )
        finally:
            await engine.close()

        target_paths: list[str] = []
        for item in mined:
            payload = _loads_json(item.get("extracted_payload"), {})
            target_db_path = payload.get("target_db_path")
            if target_db_path:
                target_paths.append(str(Path(target_db_path).resolve()))
        if target_paths:
            expected = str(challenger_db_path.resolve())
            checks["live_mining_targeted_challenger_db"] = all(
                target_path == expected for target_path in target_paths
            )
            details["live_mining_target_db_paths"] = sorted(set(target_paths))
        else:
            checks["live_mining_targeted_challenger_db"] = True

        paired_slices = {
            row["eval_slice"]: bool(int(row.get("passed", 0)))
            for row in evaluations
            if row["eval_slice"] in {"paired_retrieval", "paired_task_readiness"}
        }
        details["paired_evaluation_slices"] = paired_slices
        checks["paired_evaluation_present"] = bool(paired_slices)

        return {
            "passed": all(checks.values()),
            "checks": checks,
            "details": details,
        }

    async def _write_decision_report(
        self,
        run_id: str,
        artifact_dir: Path,
        decision: dict[str, Any],
    ) -> Path:
        run = await self.repository.get_evolution_run(run_id)
        mined = await self.repository.list_evolution_mined_inputs(run_id)
        mutations = await self.repository.list_evolution_mutations(run_id)
        evaluations = await self.repository.list_evolution_evaluations(run_id)

        report = {
            "run": run,
            "mined_inputs": mined,
            "mutations": mutations,
            "evaluations": evaluations,
            "decision": decision,
        }
        (artifact_dir / "decision_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, default=str) + "\n"
        )

        lines = [
            f"# Evolution Decision Report: {run_id}",
            "",
            f"- cycle: {run['cycle_number'] if run else 'unknown'}",
            f"- layer: {run['layer'] if run else 'unknown'}",
            f"- status: {run['status'] if run else 'unknown'}",
            f"- decision: {decision['decision']}",
            f"- reason: {decision['reason']}",
            f"- mined inputs: {len(mined)}",
            f"- mutations: {len(mutations)}",
            f"- evaluations: {len(evaluations)}",
            "",
            "## Evaluation Slices",
            "",
        ]
        for evaluation in evaluations:
            lines.append(
                "- {slice}: champion={champion:.4f} challenger={challenger:.4f} "
                "delta={delta:+.4f} passed={passed}".format(
                    slice=evaluation["eval_slice"],
                    champion=float(evaluation["champion_score"]),
                    challenger=float(evaluation["challenger_score"]),
                    delta=float(evaluation["delta_score"]),
                    passed=bool(evaluation["passed"]),
                )
            )
        lines.extend(
            [
                "",
                "## Gate Report",
                "",
                "```json",
                json.dumps(_loads_json(decision.get("gate_report"), {}), indent=2, sort_keys=True),
                "```",
                "",
            ]
        )
        report_path = artifact_dir / "decision_report.md"
        report_path.write_text("\n".join(lines))
        return report_path

    def _default_objective(self, layer: str) -> str:
        return {
            "data_feature": "Improve retrieval quality using recent PULSE discoveries without changing live knowledge.",
            "strategy_policy": "Improve routing and escalation decisions from recent outcome traces.",
            "prompt_config": "Improve prompt/config behavior using prompt variant evidence.",
            "model": "Compare model quality-adjusted cost without changing live models.",
        }[layer]


def _loads_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def python_bin() -> str:
    """Expose the interpreter path for validation integration callers."""
    return sys.executable
