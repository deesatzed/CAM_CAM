"""CAM CLI — Typer-based command line interface for CAM-PULSE.

Primary workflows:
  evaluate <repo>        — inspect one repo and score improvement potential
  enhance <repo>         — improve one existing repo in a bounded loop
  mine <dir>             — learn from outside repos into CAM memory
  ideate <dir>           — invent standalone app concepts from mined knowledge
  preflight <repo>       — clarify a requested task before execution starts
  create <repo>          — create or augment a repo from a requested outcome
  validate               — verify a created repo against its saved spec/checks

Advanced groups:
  learn <subcommand>     — learning continuum, delta, reassessment, synergies
  task <subcommand>      — goal/task setup, runbooks, and task results
  forge <subcommand>     — standalone Forge export and benchmark workflow
  doctor <subcommand>    — preflight and environment diagnostics
  kb <subcommand>        — low-level knowledge browser
  self-enhance <sub>     — self-enhancement pipeline (clone, validate, swap)
  evolution <subcommand> — serial champion/challenger evolution
  cag <subcommand>       — CAG cache-augmented generation (vectorless retrieval)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

import time as _time

import click
import typer
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.text import Text

from claw.premine import (
    PreMineResult,
    append_candidate_jsonl,
    premine_url,
    read_targets,
    render_markdown_report,
    results_to_json,
)

app = typer.Typer(
    name="cam",
    help="CAM — inspect repos, learn from repos, create from that learning, and validate outcomes",
    no_args_is_help=True,
)
console = Console()
logger = logging.getLogger("claw.cli")

ROOT_DIR = Path(__file__).resolve().parents[3]
_IDEA_DIR = ROOT_DIR / "data" / "ideation"
_PREFLIGHT_DIR = ROOT_DIR / "data" / "preflights"
_CAMIFY_DIR = ROOT_DIR / "data" / "camify"


def _find_default_claw_toml() -> Optional[Path]:
    """Locate a default claw.toml by walking up from this file, then cwd.

    Returns the first existing claw.toml found in any ancestor of this
    source file, falling back to ``Path.cwd() / "claw.toml"`` if it
    exists. Returns None if no claw.toml can be located.

    This is robust to editable installs where ``__file__`` lives under
    ``src/claw/cli/`` — the repo root (containing claw.toml) is not a
    fixed number of ``.parent`` hops away.
    """
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        candidate = ancestor / "claw.toml"
        if candidate.exists():
            return candidate
    cwd_candidate = Path.cwd() / "claw.toml"
    if cwd_candidate.exists():
        return cwd_candidate
    return None

learn_app = typer.Typer(
    name="learn",
    help="Learning lifecycle tools — delta, continuum report, reassessment, synergies",
    no_args_is_help=True,
)
task_app = typer.Typer(
    name="task",
    help="Task/operator tools — add goals, quickstart, runbooks, results",
    no_args_is_help=True,
)
forge_app = typer.Typer(
    name="forge",
    help="Standalone Forge subsystem — export knowledge packs and benchmark them",
    no_args_is_help=True,
)
doctor_app = typer.Typer(
    name="doctor",
    help="Preflight and diagnostics — key checks and system health",
    no_args_is_help=True,
)
pulse_app = typer.Typer(
    name="pulse",
    help="CAM-PULSE — perpetual X-powered discovery and assimilation of novel GitHub repos",
    no_args_is_help=True,
)
self_enhance_app = typer.Typer(
    name="self-enhance",
    help="Self-enhancement pipeline — clone, enhance, validate, swap",
    no_args_is_help=True,
)
ab_test_app = typer.Typer(
    name="ab-test",
    help="A/B knowledge ablation testing — prove whether knowledge injection improves outcomes",
    no_args_is_help=True,
)

evolution_app = typer.Typer(
    name="evolution",
    help="Serial champion/challenger evolution — autonomous budget-bound improvement loop",
    no_args_is_help=True,
)

security_app = typer.Typer(
    name="security",
    help="Security tools — secret scanning, policy checks",
    no_args_is_help=True,
)

cag_app = typer.Typer(
    name="cag",
    help="CAG — Cache-Augmented Generation (vectorless retrieval via KV cache)",
    no_args_is_help=True,
)

_FOUNDATION_CHARTER = [
    {
        "name": "learn",
        "expectation": "CAM must assimilate reusable knowledge from repos into structured memory.",
    },
    {
        "name": "reassess",
        "expectation": "CAM must reactivate old knowledge for new tasks instead of leaving it as dead notes.",
    },
    {
        "name": "validate",
        "expectation": "CAM must reject claimed success when the repo did not materially change.",
    },
    {
        "name": "standalone_output",
        "expectation": "Generated apps may be built by CAM, but must not depend on CAM runtime code.",
    },
    {
        "name": "builder_truth",
        "expectation": "Create/enhance execution may only be treated as real if an executable build path exists.",
    },
]


def _setup_logging(verbose: bool = False, json_mode: bool = False, log_file: str = "") -> None:
    from claw.logging_config import setup_logging
    setup_logging(
        verbose=verbose,
        json_mode=json_mode,
        log_file=log_file or None,
    )


def _run_python_script_with_timeout(script_path: Path, args: list[str], max_minutes: int) -> subprocess.CompletedProcess[str]:
    if max_minutes <= 0:
        raise typer.BadParameter("max-minutes must be greater than 0")

    cmd = [sys.executable, str(script_path), *args]
    timeout_seconds = max_minutes * 60
    try:
        return subprocess.run(
            cmd,
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        console.print(
            f"[red]Timed out after {max_minutes} minute(s) while running {script_path.name}[/red]"
        )
        if exc.stdout:
            console.print("[dim]Partial stdout:[/dim]")
            console.print(exc.stdout.strip())
        raise typer.Exit(124)


def _uses_remote_embeddings(config: Any) -> bool:
    """Return True if embeddings use a remote API (OpenRouter or direct Gemini)."""
    model_name = str(getattr(config.embeddings, "model", "") or "")
    required_model = str(getattr(config.embeddings, "required_model", "") or "")
    # OpenRouter: provider/model format (e.g. "perplexity/pplx-embed-v1-4b")
    if "/" in model_name:
        return True
    # Direct Gemini API
    return model_name.startswith("gemini-embedding") or required_model.startswith("gemini-embedding")


# Keep old name as alias for backward compat in any other callers
_uses_remote_gemini_embeddings = _uses_remote_embeddings


def _required_api_keys_for_command(config: Any, command_name: str) -> list[tuple[str, str]]:
    command = command_name.strip().lower()
    requirements: list[tuple[str, str]] = []

    if command in {"mine", "mine-workspace", "mine-self", "mine-all", "ideate"}:
        requirements.append(("OPENROUTER_API_KEY", "OpenRouter LLM access"))

    if command in {"mine", "mine-workspace", "mine-self", "mine-all"} and _uses_remote_gemini_embeddings(config):
        key_name = getattr(config.embeddings, "api_key_env", "") or "GOOGLE_API_KEY"
        requirements.append((str(key_name), "Gemini embeddings for methodology persistence"))

    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key_name, reason in requirements:
        if key_name in seen:
            continue
        seen.add(key_name)
        deduped.append((key_name, reason))
    return deduped


def _select_live_llm_model(config: Any, command_name: str) -> str:
    command = command_name.strip().lower()
    if command in {"mine", "mine-workspace", "mine-self", "mine-all"}:
        for agent_name in ("claude", "gemini", "codex", "grok"):
            agent_cfg = config.agents.get(agent_name)
            if agent_cfg and agent_cfg.enabled and agent_cfg.model:
                return agent_cfg.model
        raise typer.BadParameter("No enabled agent model is configured for mining")
    return _select_ideation_model(config)


def _print_api_key_check(config: Any, command_name: str) -> list[str]:
    requirements = _required_api_keys_for_command(config, command_name)
    console.print(f"\n[bold]CAM API Key Check[/bold]")
    console.print(f"  Command: {command_name}")

    if not requirements:
        console.print("  No API keys required for this command path.")
        return []

    table = Table(title="Required Keys")
    table.add_column("Key", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Why", style="dim", max_width=44)

    missing: list[str] = []
    for key_name, reason in requirements:
        present = bool(os.getenv(key_name, ""))
        if present:
            status = "[green]set[/green]"
        else:
            status = "[red]missing[/red]"
            missing.append(key_name)
        table.add_row(key_name, status, reason)

    console.print(table)
    return missing


def _fail_if_missing_api_keys(config: Any, command_name: str) -> None:
    missing = _print_api_key_check(config, command_name)
    if not missing:
        return

    console.print("\n[red]Required API keys are missing. Refusing to start live work.[/red]")
    for key_name in missing:
        console.print(f"  export {key_name}=your-key-here")
    raise typer.Exit(1)


async def _run_live_key_checks(config: Any, command_name: str) -> list[dict[str, str]]:
    import sys

    from claw.db.embeddings import EmbeddingEngine
    from claw.llm.client import LLMClient, LLMMessage

    command = command_name.strip().lower()
    results: list[dict[str, str]] = []
    public_cli = sys.modules.get("claw.cli")
    required_fn = getattr(public_cli, "_required_api_keys_for_command", _required_api_keys_for_command)
    requirements = required_fn(config, command)

    if any(key == "OPENROUTER_API_KEY" for key, _ in requirements):
        model = _select_live_llm_model(config, command)
        llm_client = LLMClient(config.llm)
        try:
            response = await llm_client.complete(
                messages=[LLMMessage(role="user", content="Reply with OK only.")],
                model=model,
                temperature=0.0,
                max_tokens=16,
            )
            content = (response.content or "").strip().replace("\n", " ")
            results.append({
                "service": "OpenRouter",
                "status": "ok",
                "detail": f"model={model} reply={content[:60] or 'non-empty'}",
            })
        except Exception as exc:
            results.append({
                "service": "OpenRouter",
                "status": "failed",
                "detail": str(exc),
            })
        finally:
            await llm_client.close()

    requires_embedding_probe = any("embedding" in reason.lower() for _, reason in requirements)
    if (
        command in {"mine", "mine-workspace", "mine-self", "mine-all"}
        and (_uses_remote_embeddings(config) or requires_embedding_probe)
    ):
        try:
            engine = EmbeddingEngine(config.embeddings)
            vector = engine.encode("cam keycheck live probe")
            service_label = "OpenRouter embeddings" if engine._uses_openrouter else "Gemini embeddings"
            results.append({
                "service": service_label,
                "status": "ok",
                "detail": f"model={engine.model_name} dim={len(vector)}",
            })
        except Exception as exc:
            service_label = "Embeddings"
            results.append({
                "service": service_label,
                "status": "failed",
                "detail": str(exc),
            })

    return results


def _render_live_key_check_results(results: list[dict[str, str]]) -> bool:
    console.print("\n[bold]CAM Live API Validation[/bold]")
    table = Table(title="Provider Checks")
    table.add_column("Service", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Detail", max_width=56)

    failed = False
    for item in results:
        status = item["status"]
        rendered_status = "[green]ok[/green]" if status == "ok" else "[red]failed[/red]"
        if status != "ok":
            failed = True
        table.add_row(item["service"], rendered_status, item["detail"])

    console.print(table)
    return not failed


def _fail_if_live_key_checks_fail(config: Any, command_name: str) -> None:
    try:
        live_results = asyncio.run(_run_live_key_checks(config, command_name))
    except Exception as exc:
        console.print(f"\n[red]Live preflight failed before provider validation: {exc}[/red]")
        raise typer.Exit(1)

    if not _render_live_key_check_results(live_results):
        raise typer.Exit(1)


def _agent_supports_workspace_execution(agent: Any) -> bool:
    """Return whether an agent can directly modify workspace files."""
    if agent is None:
        return False
    direct_capability = getattr(agent, "can_modify_workspace", None)
    if callable(direct_capability):
        try:
            if direct_capability():
                return True
        except Exception:
            return False
    internal_capability = getattr(agent, "can_use_internal_workspace_executor", None)
    if callable(internal_capability):
        try:
            return bool(internal_capability())
        except Exception:
            return False
    return False


def _resolve_operator_path(raw_path: str) -> Path:
    """Resolve operator-supplied paths, including whitespace-mismatch recovery.

    If the exact path does not exist but a sibling entry differs only by leading
    or trailing whitespace, prefer the unique match and warn.
    """
    candidate = Path(raw_path).expanduser()
    if candidate.exists():
        return candidate.resolve()

    parent = candidate.parent if str(candidate.parent) not in {"", "."} else Path.cwd()
    try:
        if parent.exists():
            stripped_name = candidate.name.strip()
            matches = [entry for entry in parent.iterdir() if entry.name.strip() == stripped_name]
            if len(matches) == 1:
                resolved = matches[0].resolve()
                console.print(
                    f"[yellow]Path '{raw_path}' not found exactly. Using whitespace-normalized match: {resolved}[/yellow]"
                )
                return resolved
    except OSError:
        pass

    return candidate.resolve()


def _workspace_execution_agents(ctx: Any) -> tuple[list[str], list[str]]:
    executable: list[str] = []
    read_only: list[str] = []
    for agent_name, agent in getattr(ctx, "agents", {}).items():
        if _agent_supports_workspace_execution(agent):
            executable.append(agent_name)
        else:
            read_only.append(agent_name)
    return executable, read_only


def _print_workspace_execution_preflight(ctx: Any, workflow_name: str) -> bool:
    executable, read_only = _workspace_execution_agents(ctx)
    if executable:
        return True

    console.print(
        f"\n[red]{workflow_name} cannot execute real repo changes in the current runtime.[/red]"
    )
    if read_only:
        console.print(
            "[red]Configured agents are reasoning-only in their current modes: "
            f"{', '.join(sorted(read_only))}.[/red]"
        )
    else:
        console.print("[red]No executable build agents are configured.[/red]")
    console.print(
        "[yellow]To run real code changes, enable a CLI-capable agent or an agent mode that emits structured file operations for CAM's internal executor.[/yellow]"
    )
    return False


def _build_foundation_expectation_report(ctx: Any) -> dict[str, Any]:
    executable, read_only = _workspace_execution_agents(ctx)
    checks = [
        {
            "name": "learn",
            "ok": bool(getattr(ctx, "miner", None) and getattr(ctx, "assimilation_engine", None) and getattr(ctx, "semantic_memory", None)),
            "detail": "Repo mining, semantic memory, and assimilation engine are wired.",
        },
        {
            "name": "reassess",
            "ok": bool(getattr(ctx, "semantic_memory", None) and getattr(ctx, "repository", None)),
            "detail": "Memory/repository layers required for reassessment are wired.",
        },
        {
            "name": "validate",
            "ok": bool(getattr(ctx, "repository", None) and getattr(ctx, "verifier", None)),
            "detail": "Validation and repo-state checks are available.",
        },
        {
            "name": "standalone_output",
            "ok": True,
            "detail": "Policy: generated apps must not import CAM runtime code at runtime.",
        },
        {
            "name": "builder_truth",
            "ok": bool(executable),
            "detail": (
                f"Executable build agents: {', '.join(sorted(executable))}"
                if executable else
                "No executable build agent is configured; create/enhance execution must be treated as planning/spec-only."
            ),
        },
    ]
    return {
        "checks": checks,
        "writable_agents": sorted(executable),
        "readonly_agents": sorted(read_only),
        "builder_execution_available": bool(executable),
    }


def _build_create_spec(
    repo_path: Path,
    request: str,
    repo_mode: str,
    title: str,
    task_type: str,
    execution_steps: list[str],
    acceptance_checks: list[str],
    spec_items: list[str],
    preflight_report: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    seeded_steps, seeded_checks = _seed_create_runbook(
        repo_mode=repo_mode,
        task_type=task_type,
        request=request,
        spec_items=spec_items,
        execution_steps=execution_steps,
        acceptance_checks=acceptance_checks,
    )
    baseline_snapshot = _snapshot_repo_state(repo_path)
    expectation_contract = _build_expectation_contract(
        request=request,
        repo_mode=repo_mode,
        task_type=task_type,
        spec_items=spec_items,
        acceptance_checks=seeded_checks,
    )
    spec_payload = {
        "version": 1,
        "title": title,
        "request": request,
        "repo_mode": repo_mode,
        "target_repo": str(repo_path),
        "task_type": task_type,
        "spec_items": spec_items,
        "baseline_snapshot": baseline_snapshot,
        "execution_steps": seeded_steps,
        "acceptance_checks": seeded_checks,
        "expectation_contract": expectation_contract,
        "validation": {
            "require_repo_exists": True,
            "require_nonempty_repo": True,
        },
        "benchmark": {
            "catastrophic_floor_pct": -35.0,
            "require_non_negative_lift": False,
        },
        "created_at_epoch": int(_time.time()),
    }
    if preflight_report:
        spec_payload["preflight"] = {
            "artifact_path": preflight_report.get("artifact_path"),
            "recommended_mode": preflight_report.get("recommended_mode"),
            "complexity": preflight_report.get("complexity"),
            "task_kind": preflight_report.get("task_kind"),
            "hard_blockers": list(preflight_report.get("hard_blockers", []) or []),
            "clarifying_questions": list(preflight_report.get("clarifying_questions", []) or []),
            "operator_answers": list(preflight_report.get("operator_answers", []) or []),
            "answered_questions": list(preflight_report.get("answered_questions", []) or []),
        }
    return spec_payload


def _build_expectation_contract(
    *,
    request: str,
    repo_mode: str,
    task_type: str,
    spec_items: list[str],
    acceptance_checks: list[str],
) -> dict[str, Any]:
    text = " ".join([request, *spec_items]).lower()
    expected_outcome = ["Requested workflow exists and is demonstrable"]
    expected_ux = ["Result is understandable and usable by an operator"]
    constraints = ["Result must materially change the target repository"]
    non_goals = ["Do not stop at analysis-only output"]
    validation_signals = [check.strip() for check in acceptance_checks if check.strip()]

    if repo_mode == "new":
        expected_outcome.append("A runnable standalone repository is created")
    elif repo_mode == "augment":
        expected_outcome.append("The existing repository gains the requested capability")
        expected_ux.append("Existing working behavior is preserved")
    else:
        expected_outcome.append("The broken or weak repo path is repaired")
        expected_ux.append("The repaired path is verifiable with focused checks")
        constraints.append("Do not introduce a new top-level source namespace unless explicitly requested")

    if "standalone" in text:
        constraints.append("Result must not require CAM runtime imports")
    if "cli" in text or "command" in text or "entrypoint" in text:
        expected_ux.append("A user-facing CLI entrypoint exists and exposes help or usage")
        expected_outcome.append("Invalid CLI arguments return a nonzero code without uncaught SystemExit")
        expected_outcome.append("CLI help and version return a zero exit code")
        constraints.append(
            "CLI help and version must work under python -m app.cli without relying on __main__.__version__"
        )
    if task_type in {"architecture", "bug_fix", "testing", "refactoring"}:
        expected_outcome.append("Automated verification exists for the primary changed behavior")
    if any("readme" in item.lower() or "doc" in item.lower() or "usage" in item.lower() for item in spec_items):
        expected_ux.append("Usage documentation explains how to run the result")

    for item in spec_items:
        lowered = item.strip().lower()
        if not lowered:
            continue
        if lowered.startswith("must not"):
            constraints.append(item.strip())
        elif lowered.startswith("must"):
            expected_outcome.append(item.strip())
        elif lowered.startswith("should"):
            expected_ux.append(item.strip())
        elif lowered.startswith("do not") or lowered.startswith("avoid"):
            non_goals.append(item.strip())

    return {
        "goal": request.strip(),
        "expected_outcome": sorted(set(expected_outcome)),
        "expected_ux": sorted(set(expected_ux)),
        "constraints": sorted(set(constraints)),
        "non_goals": sorted(set(non_goals)),
        "validation_signals": sorted(set(validation_signals)),
    }


def _scan_for_cam_runtime_imports(repo_path: Path) -> list[str]:
    hits: list[str] = []
    for path in repo_path.rglob("*.py"):
        try:
            rel = path.relative_to(repo_path)
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "import claw" in text or "from claw" in text:
            hits.append(str(rel))
            if len(hits) >= 10:
                break
    return hits


def _extract_source_namespaces_from_snapshot(snapshot: dict[str, Any]) -> set[str]:
    namespaces: set[str] = set()
    if not isinstance(snapshot, dict):
        return namespaces
    for rel_path in snapshot.keys():
        rel = Path(str(rel_path))
        parts = rel.parts
        if len(parts) >= 2 and parts[0] == "src":
            namespaces.add(parts[1])
        elif parts and parts[0] not in {".git", "tests", "docs", "data", "tmp"}:
            if rel.suffix == ".py" and len(parts) >= 1:
                namespaces.add(parts[0].replace(".py", ""))
    return namespaces


def _scan_for_new_source_namespaces(repo_path: Path, baseline_snapshot: dict[str, Any]) -> list[str]:
    current_snapshot = _snapshot_repo_state(repo_path)
    baseline_namespaces = _extract_source_namespaces_from_snapshot(baseline_snapshot)
    current_namespaces = _extract_source_namespaces_from_snapshot(current_snapshot)
    return sorted(ns for ns in current_namespaces - baseline_namespaces if ns)


def _list_added_repo_files(repo_path: Path, baseline_snapshot: dict[str, Any]) -> list[Path]:
    current_snapshot = _snapshot_repo_state(repo_path)
    baseline_files = {str(path) for path in baseline_snapshot.keys()}
    added: list[Path] = []
    for rel_path in current_snapshot.keys():
        rel = str(rel_path)
        if rel not in baseline_files:
            candidate = repo_path / rel
            if candidate.is_file():
                added.append(candidate)
    return sorted(added)


def _rollback_added_repo_files(repo_path: Path, baseline_snapshot: dict[str, Any]) -> list[str]:
    removed: list[str] = []
    for file_path in reversed(_list_added_repo_files(repo_path, baseline_snapshot)):
        try:
            rel = str(file_path.relative_to(repo_path))
            file_path.unlink(missing_ok=True)
            removed.append(rel)
        except OSError:
            continue

    protected_roots = {
        repo_path,
        repo_path / ".git",
        repo_path / "src",
        repo_path / "tests",
        repo_path / "docs",
        repo_path / "data",
        repo_path / "tmp",
    }
    for root, dirs, _files in os.walk(repo_path, topdown=False):
        root_path = Path(root)
        if root_path in protected_roots:
            continue
        try:
            if not any(root_path.iterdir()):
                root_path.rmdir()
        except OSError:
            continue
    return sorted(removed)


def _enforce_quickstart_execution_guard(
    *,
    repo_path: Path,
    baseline_snapshot: dict[str, Any],
    outcome: Any,
    verification: Any,
) -> tuple[Any, Any, list[str]]:
    baseline_namespaces = _extract_source_namespaces_from_snapshot(baseline_snapshot)
    # Only enforce the fixed-repo namespace guard when the target already has
    # an established source namespace baseline. New repo creation is allowed to
    # introduce its first namespace.
    if not baseline_namespaces:
        return outcome, verification, []

    new_source_namespaces = _scan_for_new_source_namespaces(repo_path, baseline_snapshot)
    if not new_source_namespaces:
        return outcome, verification, []

    rolled_back = _rollback_added_repo_files(repo_path, baseline_snapshot)
    violation_detail = (
        "new_source_namespace: " + ", ".join(new_source_namespaces)
        + ("; rolled back added files: " + ", ".join(rolled_back[:8]) if rolled_back else "")
    )
    verification.approved = False
    verification.violations.append({"check": "namespace_guard", "detail": violation_detail})
    outcome.tests_passed = False
    outcome.failure_reason = "new_source_namespace"
    if outcome.test_output:
        outcome.test_output += "\n"
    outcome.test_output += (
        "Quickstart execution introduced forbidden new source namespaces: "
        + ", ".join(new_source_namespaces)
    )
    return outcome, verification, rolled_back


def _assess_expectation_contract(
    spec: dict[str, Any],
    *,
    repo_path: Path,
    findings: list[str],
    checks: list[dict[str, Any]],
    manual_checks: list[str],
) -> dict[str, Any]:
    contract = spec.get("expectation_contract", {}) if isinstance(spec.get("expectation_contract"), dict) else {}
    if not contract:
        return {"score": None, "matched": [], "unmet": [], "summary": ""}

    matched: list[str] = []
    unmet: list[str] = []
    hard_failures: list[str] = []
    scored = 0
    total = 0

    def score_clause(clause: str, ok: bool, hard: bool = False) -> None:
        nonlocal scored, total
        total += 1
        if ok:
            scored += 1
            matched.append(clause)
        else:
            unmet.append(clause)
            if hard:
                hard_failures.append(clause)

    repo_exists = repo_path.exists()
    repo_nonempty = repo_exists and any(p.is_file() for p in repo_path.rglob("*"))
    repo_changed = not any("unchanged" in item.lower() for item in findings)
    checks_ok = all(item.get("ok") for item in checks) if checks else True
    has_readme = repo_exists and any((repo_path / name).exists() for name in ("README.md", "README.rst", "README.txt", "README"))
    has_cli = repo_exists and (
        (repo_path / "app" / "cli.py").exists()
        or (repo_path / "src" / "app" / "cli.py").exists()
        or (repo_path / "main.py").exists()
    )
    cam_runtime_hits = _scan_for_cam_runtime_imports(repo_path) if repo_exists else []
    baseline_snapshot = spec.get("baseline_snapshot", {}) if isinstance(spec.get("baseline_snapshot"), dict) else {}
    new_source_namespaces = _scan_for_new_source_namespaces(repo_path, baseline_snapshot) if repo_exists and baseline_snapshot else []

    for clause in contract.get("expected_outcome", []) or []:
        text = str(clause).lower()
        if "standalone repository" in text or "runnable standalone" in text:
            score_clause(str(clause), repo_exists and repo_nonempty)
        elif "materially change" in text:
            score_clause(str(clause), repo_changed)
        elif "automated verification" in text:
            score_clause(str(clause), checks_ok)
        elif "requested workflow exists" in text or "requested capability" in text or "repaired" in text:
            score_clause(str(clause), repo_exists and repo_nonempty and checks_ok)
        else:
            score_clause(str(clause), repo_exists and repo_nonempty)

    for clause in contract.get("expected_ux", []) or []:
        text = str(clause).lower()
        if "cli entrypoint" in text or "help or usage" in text:
            score_clause(str(clause), has_cli)
        elif "documentation" in text or "operator" in text:
            score_clause(str(clause), has_readme)
        elif "preserved" in text:
            score_clause(str(clause), checks_ok)
        else:
            score_clause(str(clause), repo_exists and repo_nonempty)

    for clause in contract.get("constraints", []) or []:
        text = str(clause).lower()
        if "cam runtime" in text:
            score_clause(str(clause), len(cam_runtime_hits) == 0, hard=True)
        elif "new top-level source namespace" in text:
            score_clause(str(clause), len(new_source_namespaces) == 0, hard=True)
        elif "materially change" in text:
            score_clause(str(clause), repo_changed, hard=True)
        else:
            score_clause(str(clause), True)

    score = round(scored / total, 3) if total else None
    if manual_checks:
        unmet.extend([f"manual validation still required: {item}" for item in manual_checks[:5]])
    summary = ""
    if score is not None:
        summary = f"matched {scored}/{total} expectation clauses"
    if cam_runtime_hits:
        unmet.append("CAM runtime imports found in: " + ", ".join(cam_runtime_hits[:5]))
    if new_source_namespaces:
        unmet.append("New source namespaces introduced: " + ", ".join(new_source_namespaces[:5]))
    return {
        "score": score,
        "matched": matched,
        "unmet": unmet,
        "hard_failures": hard_failures,
        "summary": summary,
    }


def _seed_create_runbook(
    *,
    repo_mode: str,
    task_type: str,
    request: str,
    spec_items: list[str],
    execution_steps: list[str],
    acceptance_checks: list[str],
) -> tuple[list[str], list[str]]:
    """Seed a usable runbook when create is underspecified."""
    clean_steps = [step.strip() for step in execution_steps if step.strip()]
    clean_checks = [check.strip() for check in acceptance_checks if check.strip()]
    if clean_steps and clean_checks:
        return clean_steps, clean_checks

    combined_text = " ".join([request, *spec_items]).lower()

    seeded_steps = list(clean_steps)
    if not seeded_steps:
        if repo_mode == "new":
            seeded_steps.extend([
                "Read the create spec and identify the minimum standalone architecture needed for the requested app.",
                "Scaffold the new repository structure, entrypoints, and configuration files needed to run the app.",
                "Implement the core user workflow first, then add supporting modules and documentation.",
                "Add or update automated tests for the primary workflow before claiming success.",
                "Run the acceptance checks, fix failures, and leave the repo in a runnable state.",
            ])
        elif repo_mode == "augment":
            seeded_steps.extend([
                "Read the create spec and map the requested capability onto the existing repository structure.",
                "Inspect the current code paths and identify the smallest safe integration points for the new behavior.",
                "Implement the augmentation with tests and documentation updates.",
                "Run the acceptance checks, fix failures, and preserve existing working behavior.",
            ])
        else:
            seeded_steps.extend([
                "Read the create spec and isolate the files or flows that must change to satisfy the request.",
                "Implement the requested repair or refinement with focused edits rather than broad rewrites.",
                "Avoid introducing new top-level source namespaces or parallel subsystems unless the spec explicitly requires them.",
                "Add or update regression tests for the changed behavior.",
                "Run the acceptance checks and confirm the target repo materially changed.",
            ])

    if ("cli" in combined_text or "command" in combined_text or "entrypoint" in combined_text):
        cli_steps = [
            "For Python CLIs, keep version metadata in the package module and reference it from the CLI without relying on __main__.__version__.",
            "If using argparse, preserve exit code semantics: --help and --version should return 0, invalid arguments should return nonzero.",
            "If wrapping parser.parse_args(argv), return int(exc.code) from caught SystemExit so argparse help/version behavior stays correct in tests.",
            "Add CLI tests for help/version behavior and invalid-argument handling before claiming success.",
        ]
        for step in cli_steps:
            if step not in seeded_steps:
                seeded_steps.append(step)

    seeded_checks = list(clean_checks)
    if not seeded_checks:
        seeded_checks.extend([
            "Repository materially changed from the baseline snapshot",
            "Primary requested workflow can be demonstrated end-to-end",
            "README or equivalent usage documentation explains how to run the result",
        ])
        if "standalone" in combined_text:
            seeded_checks.append("Result does not require CAM runtime imports")
        if "cli" in combined_text or "command" in combined_text or "entrypoint" in combined_text:
            seeded_checks.append("A user-facing CLI entrypoint exists and shows a help or usage screen")
            seeded_checks.append("CLI tests cover invalid-argument handling and version/help behavior")
            seeded_checks.append("CLI help and version return exit code 0 while invalid arguments return nonzero")
        if task_type in {"architecture", "bug_fix", "testing", "refactoring"}:
            seeded_checks.append("Automated tests exist for the primary changed behavior")

    return seeded_steps, seeded_checks


def _display_task_status(status_val: str, hypothesis_outcome: str) -> str:
    if status_val == "DONE":
        return "[green]DONE[/green]"
    if status_val == "PENDING" and hypothesis_outcome == "FAILURE":
        return "[yellow]RETRY_READY[/yellow]"
    if status_val == "PENDING":
        return "[yellow]PENDING[/yellow]"
    if status_val in ("CODING", "REVIEWING", "DISPATCHED"):
        return f"[cyan]{status_val}[/cyan]"
    if status_val == "STUCK":
        return "[red]STUCK[/red]"
    return status_val


def _write_create_spec(spec: dict[str, Any]) -> Path:
    spec_dir = ROOT_DIR / "data" / "create_specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _time.strftime("%Y%m%d-%H%M%S", _time.localtime(spec["created_at_epoch"]))
    repo_slug = Path(spec["target_repo"]).name or "repo"
    filename = f"{timestamp}-{repo_slug}-create-spec.json"
    out_path = spec_dir / filename
    out_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return out_path


def _write_preflight_artifact(report: dict[str, Any]) -> Path:
    _PREFLIGHT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = _time.strftime("%Y%m%d-%H%M%S", _time.localtime(report["created_at_epoch"]))
    repo_slug = Path(report["target_repo"]).name or "repo"
    filename = f"{timestamp}-{repo_slug}-preflight.json"
    out_path = _PREFLIGHT_DIR / filename
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out_path


def _load_preflight_artifact(preflight_file: Optional[str]) -> Optional[dict[str, Any]]:
    if not preflight_file:
        return None
    path = Path(preflight_file)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        raise typer.BadParameter(f"Preflight artifact not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"Invalid preflight artifact JSON: {path} ({exc})") from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter(f"Preflight artifact must contain a JSON object: {path}")
    payload["artifact_path"] = str(path)
    return payload


def _build_create_description(request: str, repo_mode: str, spec_path: Path, spec_items: list[str]) -> str:
    lines = [
        f"Creation mode: {repo_mode}",
        "",
        "Requested outcome:",
        request.strip(),
        "",
        f"Spec file: {spec_path}",
    ]
    if spec_items:
        lines.extend(["", "Initial specs:"])
        lines.extend([f"- {item}" for item in spec_items])
    lines.extend(
        [
            "",
            "Requirement: use prior mined/assimilated CAM knowledge where relevant.",
            "Outcome target: produce the requested repo state, not just analysis.",
        ]
    )
    return "\n".join(lines)


def _infer_preflight_task_kind(request: str, repo_mode: str, spec_items: list[str]) -> str:
    text = " ".join([request, *spec_items]).lower()
    if "apply everything" in text or "like repo-a" in text or "repo-a" in text or "transfer" in text:
        return "pattern_transfer"
    if repo_mode == "new":
        return "greenfield_app_creation"
    if any(word in text for word in ("bug", "fix", "repair", "broken", "failing")):
        return "bugfix"
    if any(word in text for word in ("redesign", "modernize", "ux", "ui", "website")):
        return "repo_transformation"
    if any(word in text for word in ("refactor", "restructure", "future proof", "future-proof")):
        return "repo_transformation"
    if any(word in text for word in ("research", "explore", "spike", "investigate")):
        return "research_spike"
    if any(word in text for word in ("design", "architecture", "system")):
        return "architecture_design"
    return "feature_build"


def _estimate_preflight_complexity(
    request: str,
    repo_mode: str,
    spec_items: list[str],
    acceptance_checks: list[str],
) -> str:
    text = " ".join([request, *spec_items]).lower()
    score = 0
    if repo_mode == "new":
        score += 2
    if len(spec_items) >= 4:
        score += 1
    if len(acceptance_checks) >= 3:
        score += 1
    if any(word in text for word in ("integrate", "migration", "security", "auth", "database", "deploy", "api")):
        score += 2
    if any(word in text for word in ("repo-a", "transfer", "replicate", "apply everything", "assimilated")):
        score += 2
    if any(word in text for word in ("production", "showpiece", "end-to-end", "autonomous")):
        score += 1
    if any(word in text for word in ("web app", "website", "frontend", "backend", "full stack", "full-stack")):
        score += 1

    if score <= 1:
        return "low"
    if score <= 3:
        return "medium"
    if score <= 5:
        return "high"
    return "very_high"


def _time_estimate_for_complexity(complexity: str) -> dict[str, str]:
    mapping = {
        "low": {
            "elapsed": "15-45 minutes",
            "active": "10-30 minutes",
            "phases": "1-2 phases",
        },
        "medium": {
            "elapsed": "45-120 minutes",
            "active": "30-90 minutes",
            "phases": "2-4 phases",
        },
        "high": {
            "elapsed": "2-6 hours",
            "active": "90-240 minutes",
            "phases": "4-6 phases",
        },
        "very_high": {
            "elapsed": "1-3 days",
            "active": "4-12 hours",
            "phases": "6+ phases",
        },
    }
    return mapping[complexity]


def _budget_estimate_for_complexity(config: Any, complexity: str) -> dict[str, Any]:
    ranges = {
        "low": (0.25, 0.75),
        "medium": (0.75, 2.5),
        "high": (2.5, 8.0),
        "very_high": (8.0, 20.0),
    }
    low, high = ranges[complexity]
    caps = {
        "per_repo_default_usd": round(float(getattr(config.fleet, "max_cost_per_repo_usd", 5.0)), 2),
        "per_day_default_usd": round(float(getattr(config.fleet, "max_cost_per_day_usd", 50.0)), 2),
        "per_agent_max_usd": round(
            max((float(getattr(agent_cfg, "max_budget_usd", 0.0)) for agent_cfg in getattr(config, "agents", {}).values()), default=0.0),
            2,
        ),
    }
    return {
        "usd_range": f"${low:.2f}-${high:.2f}",
        "assumption": "Assumes a normal create/validate loop with 1-3 execution attempts.",
        "config_caps": caps,
    }


def _build_preflight_questions(
    request: str,
    repo_mode: str,
    spec_items: list[str],
    acceptance_checks: list[str],
) -> list[dict[str, str]]:
    text = " ".join([request, *spec_items]).lower()
    questions: list[dict[str, str]] = []

    def add(priority: str, question: str, why: str, default: str) -> None:
        if len(questions) >= 7:
            return
        questions.append({
            "priority": priority,
            "question": question,
            "why_it_matters": why,
            "default_if_unanswered": default,
        })

    if not acceptance_checks:
        add(
            "must",
            "What exact acceptance checks or demo outcomes will count as success?",
            "Without explicit checks, CAM can only prove basic repo change, not task completion.",
            "CAM will infer generic checks from the request, which may miss the real quality bar.",
        )
    if repo_mode == "new":
        add(
            "must",
            "What is the required delivery surface: CLI, web app, API, library, or mixed?",
            "The architecture, files, and verification plan depend on the interface contract.",
            "CAM will choose the smallest plausible delivery surface implied by the request.",
        )
    if any(word in text for word in ("repo-a", "transfer", "apply everything", "replicate")):
        add(
            "must",
            "Which parts of the source repo must transfer: UX, architecture, workflows, data model, integrations, or all of them?",
            "Pattern transfer fails when source scope is implied but not enumerated.",
            "CAM will transfer only the most visible behavior and architecture patterns.",
        )
    if any(word in text for word in ("api", "integration", "oauth", "auth", "database", "scrape")):
        add(
            "must",
            "What external systems, credentials, or runtime dependencies are available right now?",
            "Execution can stall immediately if CAM plans around dependencies that do not exist.",
            "CAM will assume no privileged credentials and no external system write access.",
        )
    if any(word in text for word in ("health", "medical", "finance", "legal", "security", "compliance", "privacy", "phi", "pii")):
        add(
            "must",
            "Are there domain constraints such as privacy, compliance, security, or auditability requirements?",
            "These constraints change architecture, logging, storage, and validation.",
            "CAM will assume normal engineering standards but no special regulated-domain guarantees.",
        )
    add(
        "should",
        "What is the time ceiling and how much autonomy should CAM use before stopping for human review?",
        "This determines whether CAM should aim for a single pass, milestone slicing, or bounded retries.",
        "CAM will use a bounded supervised loop with milestone-oriented checkpoints.",
    )
    add(
        "should",
        "What budget ceiling should CAM respect for model/tool usage on this task?",
        "Budget limits affect model choice, retry strategy, and whether broader exploration is justified.",
        "CAM will assume the default configured budget caps in claw.toml.",
    )
    return questions


def _normalize_preflight_answers(answers: list[str]) -> list[str]:
    return [item.strip() for item in answers if item and item.strip()]


def _merge_preflight_answers(
    prior_report: Optional[dict[str, Any]],
    answers: list[str],
) -> list[str]:
    prior_answers = []
    if isinstance(prior_report, dict):
        prior_answers = [str(item).strip() for item in prior_report.get("operator_answers", []) or [] if str(item).strip()]
    merged: list[str] = []
    for item in [*prior_answers, *_normalize_preflight_answers(answers)]:
        if item and item not in merged:
            merged.append(item)
    return merged


def _answer_covers_question(question: str, answers: list[str]) -> bool:
    q = question.lower()
    answer_blob = " ".join(answers).lower()
    topic_groups = [
        (("acceptance", "demo", "success"), ("acceptance", "demo", "test", "success", "done")),
        (("delivery surface", "cli", "web app", "api", "library"), ("cli", "web", "website", "api", "library", "surface")),
        (("source repo", "must transfer", "architecture", "workflows"), ("transfer", "ux", "architecture", "workflow", "data model", "integration", "source")),
        (("external systems", "credentials", "dependencies"), ("credential", "dependency", "database", "oauth", "api key", "integration")),
        (("privacy", "compliance", "security", "auditability"), ("privacy", "compliance", "security", "audit", "phi", "pii", "hipaa")),
        (("time ceiling", "autonomy"), ("time", "hours", "minutes", "autonomy", "review", "checkpoint")),
        (("budget ceiling",), ("budget", "$", "usd", "cost")),
    ]
    for q_terms, a_terms in topic_groups:
        if any(term in q for term in q_terms):
            return any(term in answer_blob for term in a_terms)
    return False


def _apply_answers_to_preflight(
    report: dict[str, Any],
    answers: list[str],
) -> dict[str, Any]:
    normalized_answers = _normalize_preflight_answers(answers)
    if not normalized_answers:
        report["operator_answers"] = []
        report["answered_questions"] = []
        return report

    remaining_questions: list[dict[str, str]] = []
    answered_questions: list[dict[str, str]] = []
    for item in list(report.get("clarifying_questions", []) or []):
        question = str(item.get("question", "")).strip()
        if question and _answer_covers_question(question, normalized_answers):
            answered_questions.append(item)
        else:
            remaining_questions.append(item)
    report["clarifying_questions"] = remaining_questions
    report["operator_answers"] = normalized_answers
    report["answered_questions"] = answered_questions

    answer_blob = " ".join(normalized_answers).lower()
    blockers = list(report.get("hard_blockers", []) or [])
    filtered_blockers: list[str] = []
    for blocker in blockers:
        lowered = blocker.lower()
        if "credentials" in lowered or "external systems" in lowered:
            if any(term in answer_blob for term in ("credential", "available", "database", "oauth", "api key", "no external")):
                continue
        if "compliance" in lowered or "privacy" in lowered or "audit" in lowered:
            if any(term in answer_blob for term in ("hipaa", "privacy", "compliance", "no special", "standard security", "no phi", "no pii")):
                continue
        filtered_blockers.append(blocker)
    report["hard_blockers"] = filtered_blockers

    if normalized_answers:
        report["assumptions"] = list(report.get("assumptions", []) or []) + [
            "Operator-provided preflight answers were incorporated into the task contract."
        ]
    return report


def _should_auto_preflight(
    *,
    request: str,
    repo_mode: str,
    spec_items: list[str],
    acceptance_checks: list[str],
    execute: bool,
) -> bool:
    complexity = _estimate_preflight_complexity(request, repo_mode, spec_items, acceptance_checks)
    text = " ".join([request, *spec_items]).lower()

    if execute:
        return True
    if not acceptance_checks:
        return True
    if complexity in {"high", "very_high"}:
        return True
    if any(word in text for word in (
        "repo-a", "transfer", "replicate", "apply everything", "inspired by",
        "medical", "health", "finance", "legal", "security", "privacy",
        "oauth", "database", "integration", "production", "showpiece",
    )):
        return True
    return False


def _build_preflight_prompt(
    *,
    repo_path: Path,
    request: str,
    repo_mode: str,
    spec_items: list[str],
    acceptance_checks: list[str],
    answers: list[str],
    heuristic: dict[str, Any],
) -> str:
    payload = {
        "target_repo": str(repo_path),
        "repo_mode": repo_mode,
        "request": request,
        "spec_items": spec_items,
        "acceptance_checks": acceptance_checks,
        "operator_answers": answers,
        "heuristic_baseline": heuristic,
    }
    return (
        "You are CAM Preflight, a task-scoping and execution-readiness agent.\n"
        "Examine the requested task before implementation begins.\n"
        "Do not code. Do not claim progress on the build.\n"
        "Return strict JSON with these keys only:\n"
        "{\n"
        '  "task_restatement": string,\n'
        '  "likely_deliverable": string,\n'
        '  "definition_of_done": [string],\n'
        '  "assumptions": [string],\n'
        '  "hard_blockers": [string],\n'
        '  "clarifying_questions": [{"priority":"must|should","question":string,"why_it_matters":string,"default_if_unanswered":string}],\n'
        '  "estimated_phases": [string],\n'
        '  "time_estimate": {"elapsed": string, "active": string, "phases": string},\n'
        '  "budget_estimate": {"usd_range": string, "assumption": string},\n'
        '  "recommended_mode": "proceed_now|proceed_after_answers|split_into_milestone_1|not_ready",\n'
        '  "proposed_first_milestone": string,\n'
        '  "confidence": "low|medium|high"\n'
        "}\n"
        "Rules:\n"
        "- Ask at most 7 clarifying questions.\n"
        "- Distinguish must-know blockers from nice-to-have preferences.\n"
        "- Prefer defaults only when they are defensible.\n"
        "- If the task is underspecified, say so directly.\n"
        "- Stay concise and operator-facing.\n\n"
        f"Task payload:\n{json.dumps(payload, indent=2)}"
    )


def _normalize_preflight_report(report: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(fallback)
    for key in (
        "task_restatement",
        "likely_deliverable",
        "recommended_mode",
        "proposed_first_milestone",
        "confidence",
    ):
        value = report.get(key)
        if isinstance(value, str) and value.strip():
            normalized[key] = value.strip()

    for key in ("definition_of_done", "assumptions", "hard_blockers", "estimated_phases"):
        value = report.get(key)
        if isinstance(value, list):
            normalized[key] = [str(item).strip() for item in value if str(item).strip()]

    raw_questions = report.get("clarifying_questions")
    if isinstance(raw_questions, list):
        questions: list[dict[str, str]] = []
        for item in raw_questions[:7]:
            if not isinstance(item, dict):
                continue
            priority = str(item.get("priority", "should")).strip().lower()
            if priority not in {"must", "should"}:
                priority = "should"
            question = str(item.get("question", "")).strip()
            if not question:
                continue
            questions.append({
                "priority": priority,
                "question": question,
                "why_it_matters": str(item.get("why_it_matters", "")).strip(),
                "default_if_unanswered": str(item.get("default_if_unanswered", "")).strip(),
            })
        if questions:
            normalized["clarifying_questions"] = questions

    for key in ("time_estimate", "budget_estimate"):
        value = report.get(key)
        if isinstance(value, dict):
            normalized[key] = {**normalized.get(key, {}), **value}
    return normalized


async def _generate_llm_preflight_report(
    *,
    config: Any,
    repo_path: Path,
    request: str,
    repo_mode: str,
    spec_items: list[str],
    acceptance_checks: list[str],
    answers: list[str],
    heuristic_report: dict[str, Any],
    preferred_agent: Optional[str],
) -> dict[str, Any]:
    from claw.llm.client import LLMClient, LLMMessage

    model = _select_ideation_model(config, preferred_agent=preferred_agent)
    prompt = _build_preflight_prompt(
        repo_path=repo_path,
        request=request,
        repo_mode=repo_mode,
        spec_items=spec_items,
        acceptance_checks=acceptance_checks,
        answers=answers,
        heuristic=heuristic_report,
    )
    client = LLMClient(config.llm)
    try:
        response = await client.complete_json(
            [LLMMessage("user", prompt)],
            model=model,
            temperature=0.2,
        )
    finally:
        await client.close()
    return _normalize_preflight_report(response, heuristic_report)


async def _run_preflight_async(
    *,
    repo_path: Path,
    request: str,
    repo_mode: str,
    spec_items: list[str],
    acceptance_checks: list[str],
    answers: list[str],
    prior_report: Optional[dict[str, Any]],
    preferred_agent: Optional[str],
    config_path: Optional[str],
    live: bool,
) -> tuple[dict[str, Any], Optional[Path]]:
    from claw.core.config import load_config

    cfg = load_config(Path(config_path) if config_path else None)
    complexity = _estimate_preflight_complexity(request, repo_mode, spec_items, acceptance_checks)
    task_kind = _infer_preflight_task_kind(request, repo_mode, spec_items)
    merged_answers = _merge_preflight_answers(prior_report, answers)
    heuristic_report: dict[str, Any] = {
        "version": 1,
        "target_repo": str(repo_path),
        "repo_mode": repo_mode,
        "task_kind": task_kind,
        "complexity": complexity,
        "confidence": "medium" if complexity in {"low", "medium"} else "low",
        "task_restatement": request.strip(),
        "likely_deliverable": (
            "A standalone repository outcome" if repo_mode == "new"
            else "A modified target repository with the requested capability"
        ),
        "definition_of_done": [
            "Requested outcome is implemented in the target repository",
            "Acceptance checks pass or are concretely specified",
            "Result is understandable enough for an operator to run or review",
        ],
        "assumptions": [
            "CAM may use mined/assimilated knowledge where relevant",
            "The target repo path is the correct workspace for this task",
        ],
        "hard_blockers": [],
        "clarifying_questions": _build_preflight_questions(request, repo_mode, spec_items, acceptance_checks),
        "estimated_phases": [
            "Clarify scope and acceptance criteria",
            "Plan architecture and implementation steps",
            "Execute changes in the target repo",
            "Run validation and repair any failures",
        ],
        "time_estimate": _time_estimate_for_complexity(complexity),
        "budget_estimate": _budget_estimate_for_complexity(cfg, complexity),
        "recommended_mode": "proceed_after_answers",
        "proposed_first_milestone": "Lock the task contract, acceptance checks, and execution surface before implementation.",
        "created_at_epoch": int(_time.time()),
        "live_model_used": None,
        "llm_enhanced": False,
        "operator_answers": merged_answers,
        "answered_questions": [],
        "reused_preflight_artifact": prior_report.get("artifact_path") if isinstance(prior_report, dict) else None,
    }

    must_questions = [q for q in heuristic_report["clarifying_questions"] if q.get("priority") == "must"]
    if not must_questions:
        heuristic_report["recommended_mode"] = "proceed_now" if complexity in {"low", "medium"} else "split_into_milestone_1"
    elif complexity in {"high", "very_high"}:
        heuristic_report["recommended_mode"] = "split_into_milestone_1"

    if any(word in request.lower() for word in ("api", "database", "oauth", "integration")):
        heuristic_report["hard_blockers"].append("Execution may require external systems or credentials that are not yet confirmed.")
    if any(word in request.lower() for word in ("health", "medical", "finance", "legal", "phi", "pii")):
        heuristic_report["hard_blockers"].append("Domain constraints may require explicit compliance, privacy, or audit decisions before execution.")

    report = heuristic_report
    if live:
        try:
            report = await _generate_llm_preflight_report(
                config=cfg,
                repo_path=repo_path,
                request=request,
                repo_mode=repo_mode,
                spec_items=spec_items,
                acceptance_checks=acceptance_checks,
                answers=merged_answers,
                heuristic_report=heuristic_report,
                preferred_agent=preferred_agent,
            )
            report["llm_enhanced"] = True
            report["live_model_used"] = _select_ideation_model(cfg, preferred_agent=preferred_agent)
        except Exception as exc:
            report = dict(heuristic_report)
            report["assumptions"] = list(report["assumptions"]) + [f"Live preflight enrichment failed: {type(exc).__name__}"]

    report = _apply_answers_to_preflight(report, merged_answers)
    report["created_at_epoch"] = heuristic_report["created_at_epoch"]
    artifact_path = _write_preflight_artifact(report)
    report["artifact_path"] = str(artifact_path)
    artifact_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report, artifact_path


def _display_preflight_report(report: dict[str, Any]) -> None:
    console.print("\n[bold]CAM Preflight[/bold]")
    console.print(f"  Repo: {report.get('target_repo', '')}")
    console.print(f"  Mode: {report.get('repo_mode', '')}")
    console.print(f"  Kind: {report.get('task_kind', '')}")
    console.print(f"  Complexity: {report.get('complexity', '')}")
    console.print(f"  Confidence: {report.get('confidence', '')}")
    if report.get("artifact_path"):
        console.print(f"  Artifact: {report['artifact_path']}")
    if report.get("reused_preflight_artifact"):
        console.print(f"  Reused artifact: {report['reused_preflight_artifact']}")
    if report.get("live_model_used"):
        console.print(f"  Model: {report['live_model_used']}")

    console.print("\n[cyan]Task Restatement[/cyan]")
    console.print(f"  {report.get('task_restatement', '')}")
    console.print("\n[cyan]Likely Deliverable[/cyan]")
    console.print(f"  {report.get('likely_deliverable', '')}")

    done_items = report.get("definition_of_done", []) or []
    if done_items:
        console.print("\n[cyan]Definition Of Done[/cyan]")
        for item in done_items:
            console.print(f"  - {item}")

    blockers = report.get("hard_blockers", []) or []
    if blockers:
        console.print("\n[red]Hard Blockers[/red]")
        for item in blockers:
            console.print(f"  - {item}")

    assumptions = report.get("assumptions", []) or []
    if assumptions:
        console.print("\n[cyan]Assumptions[/cyan]")
        for item in assumptions[:6]:
            console.print(f"  - {item}")

    answers = report.get("operator_answers", []) or []
    if answers:
        console.print("\n[cyan]Recorded Answers[/cyan]")
        for item in answers:
            console.print(f"  - {item}")

    questions = report.get("clarifying_questions", []) or []
    if questions:
        console.print("\n[yellow]Clarifying Questions[/yellow]")
        for item in questions:
            priority = str(item.get("priority", "should")).upper()
            console.print(f"  - [{priority}] {item.get('question', '')}")
            why = str(item.get("why_it_matters", "")).strip()
            default = str(item.get("default_if_unanswered", "")).strip()
            if why:
                console.print(f"      why: {why}")
            if default:
                console.print(f"      default: {default}")

    console.print("\n[cyan]Time Estimate[/cyan]")
    for key, value in (report.get("time_estimate", {}) or {}).items():
        console.print(f"  {key}: {value}")

    console.print("\n[cyan]Budget Estimate[/cyan]")
    budget = report.get("budget_estimate", {}) or {}
    if budget.get("usd_range"):
        console.print(f"  usd_range: {budget['usd_range']}")
    if budget.get("assumption"):
        console.print(f"  assumption: {budget['assumption']}")
    caps = budget.get("config_caps", {}) or {}
    for key, value in caps.items():
        console.print(f"  {key}: {value}")

    console.print("\n[bold]Recommended Execution Mode[/bold]")
    console.print(f"  {report.get('recommended_mode', '')}")
    console.print("\n[bold]Proposed First Milestone[/bold]")
    console.print(f"  {report.get('proposed_first_milestone', '')}")


def _detect_chat_intent(text: str) -> str:
    lowered = text.strip().lower()
    if not lowered:
        return "empty"
    if lowered in {"exit", "quit", ":q"}:
        return "exit"
    if "mine" in lowered:
        return "mine"
    if any(word in lowered for word in ("create", "build", "make", "generate")):
        return "create"
    if any(word in lowered for word in ("fix", "repair", "improve", "enhance")):
        return "enhance"
    return "unknown"


def _extract_chat_path(text: str) -> Optional[str]:
    match = re.search(r"(\./[^\s]+|\.\.[^\s]*|/[^\s]+)", text)
    if match:
        return match.group(1)
    match = re.search(r"(?:folder|directory|repo|path)\s+([^\s]+)", text, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def _chat_prompt(message: str, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{message}{suffix}: ").strip()
    if not value and default is not None:
        return default
    return value


def _chat_confirm(message: str, default: bool = True) -> bool:
    prompt = "Y/n" if default else "y/N"
    while True:
        value = input(f"{message} [{prompt}]: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        console.print("[yellow]Please answer yes or no.[/yellow]")


def _build_mine_command_preview(
    *,
    directory: str,
    target: str,
    max_repos: int,
    depth: int,
    scan_only: bool,
    tasks: bool,
    changed_only: bool,
) -> str:
    parts = [
        ".venv/bin/cam",
        "mine",
        directory,
        "--target",
        target,
        "--max-repos",
        str(max_repos),
        "--depth",
        str(depth),
    ]
    if scan_only:
        parts.append("--scan-only")
    if not tasks:
        parts.append("--no-tasks")
    if changed_only:
        parts.append("--changed-only")
    return " ".join(parts)


def _chat_handle_mine(initial_text: str, config: Optional[str]) -> None:
    suggested_dir = _extract_chat_path(initial_text) or "."
    directory = _chat_prompt("Folder to mine", suggested_dir)

    purpose = _chat_prompt(
        "Purpose: type `cam` to improve CAM itself, or enter another target repo/task path",
        "cam",
    ).strip()
    if purpose.lower() == "cam":
        target = str(ROOT_DIR)
        console.print(f"[cyan]Target repo set to CAM itself:[/cyan] {target}")
    else:
        target = purpose

    preview_first = _chat_confirm("Start with preview-only scan before live mining", default=True)
    changed_only = _chat_confirm("Only include repos that are new or changed", default=True)
    max_repos_raw = _chat_prompt("Maximum repos to inspect", "4")
    depth_raw = _chat_prompt("Directory depth", "3")
    task_generation = _chat_confirm("Generate enhancement tasks from mined findings", default=(not preview_first))

    try:
        max_repos = max(1, int(max_repos_raw))
    except ValueError:
        max_repos = 4
    try:
        depth = max(1, int(depth_raw))
    except ValueError:
        depth = 3

    preview_command = _build_mine_command_preview(
        directory=directory,
        target=target,
        max_repos=max_repos,
        depth=depth,
        scan_only=preview_first,
        tasks=task_generation,
        changed_only=changed_only,
    )

    console.print("\n[bold]CAM Chat Plan[/bold]")
    console.print("  Intent: mine")
    console.print(f"  Directory: {directory}")
    console.print(f"  Target: {target}")
    console.print(f"  Preview first: {preview_first}")
    console.print(f"  Changed only: {changed_only}")
    console.print(f"  Max repos: {max_repos}")
    console.print(f"  Depth: {depth}")
    console.print(f"  Generate tasks: {task_generation}")
    console.print("\n[cyan]Suggested command[/cyan]")
    console.print(f"  {preview_command}")

    if _chat_confirm("Run this now", default=False):
        mine(
            directory=directory,
            target=target,
            max_repos=max_repos,
            min_relevance=0.6,
            tasks=task_generation,
            depth=depth,
            dedup=True,
            skip_known=True,
            force_rescan=False,
            changed_only=changed_only,
            scan_only=preview_first,
            live_keycheck=True,
            max_minutes=15,
            verbose=False,
            config=config,
        )



# ---------------------------------------------------------------------------
# cam init — guided first-run setup wizard (top-level command)
# ---------------------------------------------------------------------------
#
# This is the recommended entry point for brand-new users. It walks through
# config creation, API-key checks, domain selection, curated seed-pack
# bootstrap (via ``run_seed`` — not a subprocess), and a smoke test. The
# wizard is interactive by default but fully scriptable via ``--non-interactive``.

_INIT_DEFAULT_CLAW_TOML = """\
# CAM-PULSE configuration
# See docs/ for full options

[database]
db_path = "data/claw.db"

[embeddings]
provider = "google"
model = "gemini-embedding-2-preview"

[local_llm]
provider = "ollama"
kv_cache_quantization = "q8_0"

[governance]
sweep_interval_cycles = 10

[cag]
token_budget_max = 16000
"""


def _init_parse_domain_input(raw: str, valid_domains: list[str]) -> list[str]:
    """Parse a user-supplied domain selection string.

    Accepts numbers (1..N, in the order of ``valid_domains``), domain names,
    or a comma-separated mix. Returns a de-duplicated list preserving input
    order. Raises ``ValueError`` on any unresolvable token.
    """
    tokens = [t.strip().lower() for t in raw.replace(";", ",").split(",") if t.strip()]
    if not tokens:
        raise ValueError("no domains specified")

    selected: list[str] = []
    for t in tokens:
        if t.isdigit():
            idx = int(t) - 1
            if idx < 0 or idx >= len(valid_domains):
                raise ValueError(f"index out of range: {t}")
            name = valid_domains[idx]
        elif t in valid_domains:
            name = t
        else:
            raise ValueError(f"unknown domain: {t!r}")
        if name not in selected:
            selected.append(name)

    # Collapse: if "all" is selected, that trumps everything else.
    if "all" in selected:
        return ["all"]
    return selected


@app.command(name="init")
def init_cmd(
    domain: Optional[list[str]] = typer.Option(
        None,
        "--domain",
        "-d",
        help=(
            "Domain(s) to bootstrap (repeatable). Values: python, devsecops, "
            "webdev, all. If omitted in interactive mode, you'll be prompted."
        ),
    ),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        "--yes",
        "-y",
        help="Skip all prompts. Uses --domain flags or defaults. For CI/scripts.",
    ),
    force: bool = typer.Option(
        False, "--force", help="Re-run even if already initialized."
    ),
    skip_smoke_test: bool = typer.Option(
        False, "--skip-smoke-test", help="Skip the final federation smoke test."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Guided first-run setup for CAM-PULSE.

    Walks a new user through:
      1. Checking for claw.toml config (creates from template if missing)
      2. Verifying API keys (GOOGLE_API_KEY for embeddings, OPENROUTER_API_KEY for LLM)
      3. Selecting domains to bootstrap
      4. Loading curated starter packs via cam kb bootstrap
      5. A smoke test via cam federate
      6. Printing next-step recommendations

    Use --non-interactive for scripts and CI.
    """
    _setup_logging(verbose)

    from rich.panel import Panel
    from claw.community.seeder import DOMAIN_PACKS, DEFAULT_DOMAIN, list_available_packs

    valid_domains = sorted(DOMAIN_PACKS.keys())  # deterministic order

    # ── Step 1: Welcome banner ───────────────────────────────────────────
    if not non_interactive:
        console.print(
            Panel.fit(
                "[bold cyan]CAM-PULSE First-Run Setup[/bold cyan]\n\n"
                "This wizard will prepare a working knowledge base and verify your\n"
                "environment. It is safe to re-run; use [bold]--force[/bold] to re-seed.",
                border_style="cyan",
                title="cam init",
            )
        )

    # ── Step 2: Config check ─────────────────────────────────────────────
    if config:
        config_path = Path(config).resolve()
    else:
        config_path = (Path.cwd() / "claw.toml").resolve()

    if config_path.exists():
        console.print(f"[green]OK[/green] Found claw.toml at [dim]{config_path}[/dim]")
    else:
        if non_interactive:
            console.print(
                f"[red]No claw.toml found at {config_path}.[/red] In --non-interactive mode "
                f"the wizard will not auto-create a config."
            )
            console.print(
                "[dim]Create one manually (or run without --non-interactive) and retry.[/dim]"
            )
            raise typer.Exit(1)

        create_it = typer.confirm(
            f"No claw.toml found at {config_path}. Create a default one?",
            default=True,
        )
        if not create_it:
            console.print(
                "[yellow]Aborting.[/yellow] Create a claw.toml manually, then re-run "
                "[cyan]cam init[/cyan]."
            )
            raise typer.Exit(0)

        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(_INIT_DEFAULT_CLAW_TOML)
        console.print(
            f"[green]OK[/green] Wrote default claw.toml to [dim]{config_path}[/dim]"
        )

    # Load the config we now know exists. Any config error is a hard fail.
    from claw.core.config import load_config
    try:
        cfg = load_config(config_path)
    except Exception as exc:
        console.print(f"[red]Failed to load {config_path}: {exc}[/red]")
        raise typer.Exit(1)

    # ── Step 3: API key check ────────────────────────────────────────────
    missing_keys: list[tuple[str, str, str]] = []
    if not os.environ.get("GOOGLE_API_KEY"):
        missing_keys.append((
            "GOOGLE_API_KEY",
            "Google Gemini embeddings (dense retrieval)",
            "export GOOGLE_API_KEY=your-key-here",
        ))
    if not os.environ.get("OPENROUTER_API_KEY"):
        missing_keys.append((
            "OPENROUTER_API_KEY",
            "OpenRouter LLM routing (mining, synthesis, preflight)",
            "export OPENROUTER_API_KEY=your-key-here",
        ))

    if missing_keys:
        for name, purpose, export in missing_keys:
            console.print(f"[yellow]!  {name} is not set[/yellow]  — {purpose}")
            console.print(f"   [dim]{export}[/dim]")

    if len(missing_keys) == 2:
        console.print(
            "\n[red]Both API keys are missing.[/red] Some features "
            "(dense retrieval, LLM mining) will be degraded."
        )
        if non_interactive:
            console.print("[yellow]Continuing anyway (--non-interactive).[/yellow]")
        else:
            proceed = typer.confirm("Continue anyway?", default=False)
            if not proceed:
                console.print("[yellow]Aborting.[/yellow] Set the API keys and re-run.")
                raise typer.Exit(0)
    elif len(missing_keys) == 1:
        console.print(
            "[yellow]One key missing — the wizard will continue, but set it "
            "before using the affected features.[/yellow]"
        )
    else:
        console.print("[green]OK[/green] Required API keys are present")

    # ── Step 4: Domain selection ─────────────────────────────────────────
    selected_domains: list[str]
    if domain:
        # Normalize & validate the flag-supplied values.
        try:
            selected_domains = _init_parse_domain_input(",".join(domain), valid_domains)
        except ValueError as exc:
            console.print(f"[red]Invalid --domain: {exc}[/red]")
            console.print(f"[dim]Valid: {', '.join(valid_domains)}[/dim]")
            raise typer.Exit(2)
    elif non_interactive:
        selected_domains = [DEFAULT_DOMAIN]
        console.print(
            f"[dim]Non-interactive: defaulting to domain [bold]{DEFAULT_DOMAIN}[/bold][/dim]"
        )
    else:
        console.print("\n[bold]Which domains should CAM bootstrap knowledge for?[/bold]")
        # Hand-written descriptions per domain. The display order is curated
        # (most common first) but every name is still validated against the
        # canonical sorted ``valid_domains`` list above.
        display_order = ["python", "devsecops", "webdev", "all"]
        descriptions = {
            "python": "Python-primary starter (default)",
            "devsecops": "Security + CI/CD patterns",
            "webdev": "Web development (small, supplemented with python)",
            "all": "Load every available starter pack",
        }
        # Defensive: include any new domain that wasn't in the curated order.
        for name in valid_domains:
            if name not in display_order:
                display_order.append(name)
        for i, name in enumerate(display_order, start=1):
            desc = descriptions.get(name, "")
            console.print(f"  {i}. [cyan]{name:<10}[/cyan] — {desc}")

        while True:
            raw = typer.prompt(
                "Select one or more (numbers, names, or comma-separated)",
                default=DEFAULT_DOMAIN,
            )
            try:
                # Use the display_order for numeric resolution so the user's
                # "1" matches what they saw on screen.
                selected_domains = _init_parse_domain_input(raw, display_order)
                break
            except ValueError as exc:
                console.print(f"[red]Invalid selection: {exc}[/red]")

    console.print(
        f"[green]OK[/green] Domains selected: [cyan]{', '.join(selected_domains)}[/cyan]"
    )

    # ── Idempotency check (before we touch any pack) ─────────────────────
    # We open the engine once, check DB state, and reuse it for the bootstrap
    # + smoke test so we don't thrash connections.
    from claw.db.engine import DatabaseEngine
    from claw.db.repository import Repository

    engine = DatabaseEngine(cfg.database)

    async def _run() -> int:
        await engine.connect()
        await engine.apply_migrations()
        await engine.initialize_schema()

        repository = Repository(engine)

        # Count current methodologies. ``count_methodologies`` is the public
        # API on Repository; use it rather than raw SQL.
        try:
            current_count = await repository.count_methodologies()
        except Exception:
            current_count = 0

        if current_count > 0 and not force:
            console.print(
                f"\n[yellow]CAM appears to be already initialized "
                f"({current_count} methodologies in DB).[/yellow] "
                f"Use [bold]--force[/bold] to re-run."
            )
            return 0

        # ── Step 5: Bootstrap each domain via run_seed ───────────────────
        # Resolve packs across the selected domains, preserving order and
        # de-duplicating (don't re-seed the same pack twice in one run).
        requested_packs: list[str] = []
        for d in selected_domains:
            for p in DOMAIN_PACKS[d]:
                if p not in requested_packs:
                    requested_packs.append(p)

        on_disk = {e["name"]: e for e in list_available_packs()}
        missing_packs = [p for p in requested_packs if p not in on_disk]
        if missing_packs:
            console.print(
                f"\n[red]Missing seed pack(s): {', '.join(missing_packs)}[/red]"
            )
            if on_disk:
                console.print(
                    f"[dim]Available on disk: {', '.join(sorted(on_disk.keys()))}[/dim]"
                )
            return 1

        # Optional embedding engine — same pattern as kb_bootstrap.
        from claw.community.seeder import run_seed
        from claw.db.embeddings import EmbeddingEngine

        embedding_engine = None
        try:
            embedding_engine = EmbeddingEngine(cfg.embeddings)
            console.print(
                f"\n[bold]Bootstrapping knowledge[/bold] "
                f"(embeddings via [dim]{cfg.embeddings.model}[/dim])"
            )
        except Exception as exc:
            console.print(
                f"\n[yellow]!  Embeddings unavailable ({exc}) — "
                f"seeding without vectors.[/yellow]"
            )

        console.print(f"  Packs: [dim]{', '.join(requested_packs)}[/dim]")

        summary = await run_seed(
            engine=engine,
            embedding_engine=embedding_engine,
            force=force,
            config=cfg,
            names=requested_packs,
        )

        reason = summary.get("reason", "")
        imported = int(summary.get("imported", 0))
        skipped = int(summary.get("skipped", 0))
        rejected = int(summary.get("rejected", 0))

        if reason == "already_seeded" and not force:
            # Safety net — ``run_seed`` guards this too but the top-level
            # idempotency check above should have caught it first.
            console.print(
                "\n[yellow]Knowledge base already seeded.[/yellow] "
                "Use [bold]--force[/bold] to re-seed."
            )
        elif imported > 0:
            console.print(f"\n[green]OK[/green] Imported [bold]{imported}[/bold] methodologies")
            if skipped:
                console.print(f"  Skipped (dedup): {skipped}")
            if rejected:
                console.print(f"  [yellow]Rejected: {rejected}[/yellow]")
        elif skipped > 0:
            console.print("\n[green]All seed records already present (idempotent).[/green]")
        else:
            console.print(
                f"\n[yellow]No records imported (reason: {reason or '?'}).[/yellow]"
            )

        # ── Step 6: Smoke test ───────────────────────────────────────────
        if not skip_smoke_test:
            smoke_query_map = {
                "python": "refactor long function",
                "devsecops": "detect SQL injection",
                "webdev": "handle form validation",
                "all": "error handling patterns",
            }
            first = selected_domains[0]
            query = smoke_query_map.get(first, "error handling patterns")
            console.print(f"\n[bold]Smoke test:[/bold] query = [cyan]{query!r}[/cyan]")

            try:
                if cfg.instances.enabled and cfg.instances.siblings:
                    # Federated path — mirrors cam federate.
                    from claw.community.cross_language import CrossLanguageAnalyzer
                    primary_db = str(Path(cfg.database.db_path).resolve())
                    analyzer = CrossLanguageAnalyzer(
                        cfg.instances, primary_db_path=primary_db
                    )
                    report = await analyzer.analyze(query)
                    console.print(
                        f"  [green]OK[/green] Federation returned "
                        f"{report.metrics.total_results} results across "
                        f"{report.metrics.brains_queried} brain(s)"
                    )
                else:
                    # Fallback smoke test: direct count from the primary DB.
                    total = await repository.count_methodologies()
                    console.print(
                        f"  [green]OK[/green] Fallback smoke test: "
                        f"{total} methodologies in primary DB"
                    )
            except Exception as exc:
                console.print(
                    f"  [yellow]!  Smoke test failed: {exc}[/yellow] "
                    "(init will continue)"
                )

        # ── Step 7: Next steps ───────────────────────────────────────────
        console.print(
            Panel.fit(
                "[bold green]CAM-PULSE is ready.[/bold green]\n\n"
                "Next steps:\n"
                "  1. Verify more: [cyan]cam federate \"your query here\"[/cyan]\n"
                "  2. Expand KB:   [cyan]cam pulse ingest https://github.com/<repo>[/cyan]\n"
                "  3. Playbooks:   [cyan]docs/KB_BOOTSTRAP_PLAYBOOKS.md[/cyan]\n"
                "  4. Build:       [cyan]cam create /path/to/new-repo --execute --request \"...\"[/cyan]",
                border_style="green",
                title="Done",
            )
        )
        return 0

    try:
        rc = asyncio.run(_run())
    finally:
        try:
            asyncio.run(engine.close())
        except Exception:
            pass

    if rc != 0:
        raise typer.Exit(rc)


@app.command()
def chat(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Interactive conversational guide for CAM workflows."""
    _setup_logging(False)

    console.print("\n[bold]CAM Chat[/bold]")
    console.print("Describe what you want in plain English. Type `exit` to leave.")

    while True:
        try:
            user_text = input("cam> ").strip()
        except EOFError:
            console.print("\n[dim]Exiting CAM Chat.[/dim]")
            return

        intent = _detect_chat_intent(user_text)
        if intent == "exit":
            console.print("[dim]Exiting CAM Chat.[/dim]")
            return
        if intent == "empty":
            continue
        if intent == "mine":
            _chat_handle_mine(user_text, config)
            continue

        if intent in {"create", "enhance"}:
            console.print(
                "[yellow]Chat support for that workflow is not wired yet. Use `cam preflight` or `cam create` directly for now.[/yellow]"
            )
            continue

        console.print(
            "[yellow]I could not map that request yet. Try something like: `I want to mine the folder ./folderx`.[/yellow]"
        )


def _select_ideation_model(config: Any, preferred_agent: Optional[str] = None) -> str:
    agent_order = [preferred_agent] if preferred_agent else ["claude", "gemini", "codex", "grok"]
    if not preferred_agent:
        agent_order = ["claude", "gemini", "codex", "grok"]

    for agent_name in agent_order:
        if not agent_name:
            continue
        agent_cfg = config.agents.get(agent_name)
        if agent_cfg and agent_cfg.enabled and agent_cfg.model:
            return agent_cfg.model
    raise typer.BadParameter("No enabled agent with a configured model is available for ideation")


def _summarize_repo_tree(repo_path: Path, max_files: int = 10) -> dict[str, Any]:
    from claw.miner import _CODE_EXTENSIONS, _SKIP_DIRS

    marker_names = {
        "README.md", "README.rst", "README.txt",
        "pyproject.toml", "package.json", "Cargo.toml", "go.mod",
        "requirements.txt", "setup.py", "Makefile", "Dockerfile",
    }

    sample_files: list[str] = []
    marker_files: list[str] = []
    top_dirs: list[str] = []

    try:
        for entry in sorted(repo_path.iterdir(), key=lambda p: p.name):
            if entry.name.startswith("."):
                continue
            if entry.is_dir() and entry.name not in _SKIP_DIRS and len(top_dirs) < 8:
                top_dirs.append(entry.name)
            elif entry.is_file() and entry.name in marker_names and len(marker_files) < 8:
                marker_files.append(entry.name)
    except OSError:
        pass

    try:
        for path in sorted(repo_path.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(repo_path)
            if any(part in _SKIP_DIRS for part in rel.parts):
                continue
            if path.name in marker_names or path.suffix.lower() in _CODE_EXTENSIONS:
                sample_files.append(str(rel))
            if len(sample_files) >= max_files:
                break
    except OSError:
        pass

    return {
        "name": repo_path.name,
        "path": str(repo_path),
        "marker_files": marker_files,
        "top_dirs": top_dirs,
        "sample_files": sample_files,
    }


def _summarize_methodology(meth: Any) -> dict[str, Any]:
    return {
        "id": getattr(meth, "id", ""),
        "problem": getattr(meth, "problem_description", "")[:240],
        "notes": (getattr(meth, "methodology_notes", "") or "")[:240],
        "tags": list(getattr(meth, "tags", []) or [])[:8],
        "novelty_score": getattr(meth, "novelty_score", None),
        "potential_score": getattr(meth, "potential_score", None),
    }


def _classify_assimilation_stage(
    meth: Any,
    *,
    template_count: int = 0,
    template_successes: int = 0,
    usage_stats: Optional[dict[str, Any]] = None,
) -> str:
    """Classify a methodology along the learning/usefulness continuum."""
    usage_stats = usage_stats or {}
    if (
        getattr(meth, "success_count", 0) > 0
        or template_successes > 0
        or int(usage_stats.get("attributed_success_count", 0) or 0) > 0
    ):
        return "proven"
    if template_count > 0 or int(usage_stats.get("used_count", 0) or 0) > 0:
        return "operationalized"
    if getattr(meth, "retrieval_count", 0) > 0 or int(usage_stats.get("retrieved_count", 0) or 0) > 0:
        return "retrieved"
    if (
        getattr(meth, "capability_data", None) is not None
        or getattr(meth, "novelty_score", None) is not None
        or getattr(meth, "potential_score", None) is not None
    ):
        return "enriched"
    return "stored"


def _is_future_candidate(
    meth: Any,
    *,
    potential_threshold: float,
    template_count: int = 0,
    usage_stats: Optional[dict[str, Any]] = None,
) -> bool:
    """Estimate whether a methodology looks promising for future use."""
    usage_stats = usage_stats or {}
    if getattr(meth, "success_count", 0) > 0 or int(usage_stats.get("attributed_success_count", 0) or 0) > 0:
        return False
    potential = getattr(meth, "potential_score", None)
    if potential is not None and potential >= potential_threshold:
        return True
    capability_data = getattr(meth, "capability_data", None) or {}
    domains = capability_data.get("domain", []) if isinstance(capability_data, dict) else []
    if capability_data and domains and template_count > 0:
        return True
    return False


_TRIGGER_KEYWORDS: dict[str, set[str]] = {
    "frontend": {"frontend", "ui", "ux", "react", "component", "design"},
    "backend": {"backend", "api", "server", "service", "endpoint"},
    "finetuning": {"finetune", "fine-tuning", "training", "adapter", "lora", "sft"},
    "evaluation": {"eval", "evaluation", "benchmark", "grade", "metrics", "score"},
    "validation": {"validate", "validation", "check", "verify", "assert"},
    "repo_repair": {"repair", "fix", "debug", "failing", "broken", "regression"},
    "testing": {"test", "pytest", "unit", "integration", "coverage"},
    "data_pipeline": {"dataset", "jsonl", "ingest", "embedding", "pipeline", "packing"},
    "security": {"security", "privacy", "secret", "auth", "permission"},
    "deployment": {"deploy", "deployment", "release", "packaging", "ops", "ci", "cd"},
}

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "using", "use",
    "build", "create", "make", "repo", "project", "task", "app", "tool", "system",
    "your", "their", "there", "will", "have", "has", "was", "are", "its", "not",
}


def _tokenize_reassessment_text(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9_+-]{3,}", text.lower()))
    return {t for t in tokens if t not in _STOPWORDS}


def _build_reassessment_expectation_contract(task: str, repo_summary: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    expected_outcome = ["recommend methodologies that materially help the requested task"]
    expected_ux = ["recommendations should fit the intended operator workflow"]
    constraints = ["avoid methodologies that only loosely match the task"]

    task_lower = task.lower()
    if any(word in task_lower for word in ("future-proof", "modernize", "upgrade")):
        expected_outcome.append("prioritize maintainability and modernization patterns")
    if any(word in task_lower for word in ("security", "harden", "secure")):
        expected_outcome.append("prioritize security and verification patterns")
    if any(word in task_lower for word in ("cli", "operator", "ux", "workflow")):
        expected_ux.append("favor operator-facing usability and clear execution flow")
    if repo_summary:
        expected_outcome.append(f"fit the repo context of {repo_summary.get('name', 'target repo')}")
    return {
        "goal": task.strip(),
        "expected_outcome": expected_outcome,
        "expected_ux": expected_ux,
        "constraints": constraints,
    }


def _derive_activation_triggers(meth: Any, *, template_count: int = 0) -> list[str]:
    """Derive lightweight trigger metadata from existing methodology fields."""
    text_parts = [
        getattr(meth, "problem_description", "") or "",
        getattr(meth, "methodology_notes", "") or "",
        " ".join(getattr(meth, "tags", []) or []),
    ]
    capability_data = getattr(meth, "capability_data", None) or {}
    if isinstance(capability_data, dict):
        for trigger in capability_data.get("activation_triggers", []) or []:
            text_parts.append(str(trigger))
        for hint in capability_data.get("applicability", []) or []:
            text_parts.append(str(hint))
        for hint in capability_data.get("non_applicability", []) or []:
            text_parts.append(str(hint))
        text_parts.extend(capability_data.get("domain", []) or [])
        ctype = capability_data.get("capability_type")
        if ctype:
            text_parts.append(str(ctype))
        for io_key in ("inputs", "outputs"):
            for item in capability_data.get(io_key, []) or []:
                if isinstance(item, dict):
                    if item.get("type"):
                        text_parts.append(str(item["type"]))
                    if item.get("name"):
                        text_parts.append(str(item["name"]))

    text = " ".join(text_parts).lower()
    triggers: list[str] = []
    for name, keywords in _TRIGGER_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            triggers.append(name)
    if template_count > 0:
        triggers.append("has_action_template")
    if getattr(meth, "potential_score", None) is not None and (meth.potential_score or 0) >= 0.75:
        triggers.append("high_future_value")
    return sorted(set(triggers))


def _summarize_methodology_usage(entries: list[Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "total_events": len(entries),
        "methodology_count": 0,
        "retrieved_count": 0,
        "used_count": 0,
        "attributed_count": 0,
        "attributed_success_count": 0,
        "avg_expectation_match_score": None,
        "top_methodologies": [],
    }
    if not entries:
        return summary

    per_methodology: dict[str, dict[str, Any]] = {}
    expectation_scores: list[float] = []

    for entry in entries:
        bucket = per_methodology.setdefault(
            entry.methodology_id,
            {
                "methodology_id": entry.methodology_id,
                "retrieved_count": 0,
                "used_count": 0,
                "attributed_count": 0,
                "success_count": 0,
                "avg_expectation_match_score": None,
                "_expectation_scores": [],
            },
        )
        if entry.stage == "retrieved_presented":
            summary["retrieved_count"] += 1
            bucket["retrieved_count"] += 1
        elif entry.stage == "used_in_outcome":
            summary["used_count"] += 1
            bucket["used_count"] += 1
        elif entry.stage == "outcome_attributed":
            summary["attributed_count"] += 1
            bucket["attributed_count"] += 1
            if entry.success:
                summary["attributed_success_count"] += 1
                bucket["success_count"] += 1
            if entry.expectation_match_score is not None:
                score = float(entry.expectation_match_score)
                expectation_scores.append(score)
                bucket["_expectation_scores"].append(score)

    summary["methodology_count"] = len(per_methodology)
    if expectation_scores:
        summary["avg_expectation_match_score"] = sum(expectation_scores) / len(expectation_scores)

    top_methodologies: list[dict[str, Any]] = []
    for bucket in per_methodology.values():
        scores = bucket.pop("_expectation_scores")
        if scores:
            bucket["avg_expectation_match_score"] = sum(scores) / len(scores)
        top_methodologies.append(bucket)
    top_methodologies.sort(
        key=lambda item: (
            item["success_count"],
            item["used_count"],
            item["retrieved_count"],
            item["methodology_id"],
        ),
        reverse=True,
    )
    summary["top_methodologies"] = top_methodologies
    return summary


def _score_methodology_for_task(
    meth: Any,
    *,
    task_tokens: set[str],
    repo_tokens: set[str],
    expectation_tokens: Optional[set[str]] = None,
    template_count: int = 0,
    template_successes: int = 0,
    usage_stats: Optional[dict[str, Any]] = None,
) -> tuple[float, list[str], list[str]]:
    """Heuristic task-conditioned reassessment score and explanation."""
    tags = set(getattr(meth, "tags", []) or [])
    capability_data = getattr(meth, "capability_data", None) or {}
    domains = set(capability_data.get("domain", []) if isinstance(capability_data, dict) else [])
    triggers = _derive_activation_triggers(meth, template_count=template_count)
    trigger_set = set(triggers)

    text_tokens = _tokenize_reassessment_text(
        " ".join([
            getattr(meth, "problem_description", "") or "",
            getattr(meth, "methodology_notes", "") or "",
            " ".join(tags),
            " ".join(domains),
            " ".join(triggers),
        ])
    )

    overlap_tokens = sorted((task_tokens | repo_tokens) & text_tokens)
    expectation_overlap = sorted((expectation_tokens or set()) & text_tokens)
    score = 0.0
    reasons: list[str] = []

    if overlap_tokens:
        overlap_score = min(0.45, 0.06 * len(overlap_tokens))
        score += overlap_score
        reasons.append("task/repo overlap: " + ", ".join(overlap_tokens[:5]))

    if expectation_overlap:
        score += min(0.2, 0.05 * len(expectation_overlap))
        reasons.append("expectation fit: " + ", ".join(expectation_overlap[:4]))

    potential = getattr(meth, "potential_score", None)
    if potential is not None:
        score += min(0.2, potential * 0.2)
        if potential >= 0.65:
            reasons.append(f"high potential {potential:.2f}")

    novelty = getattr(meth, "novelty_score", None)
    if novelty is not None and novelty >= 0.45:
        score += min(0.08, novelty * 0.08)
        reasons.append(f"novelty {novelty:.2f}")

    retrieval_count = getattr(meth, "retrieval_count", 0) or 0
    if retrieval_count > 0:
        score += min(0.1, 0.02 * retrieval_count)
        reasons.append(f"retrieved {retrieval_count}x")

    direct_success = getattr(meth, "success_count", 0) or 0
    if direct_success > 0 or template_successes > 0:
        combined_success = direct_success + template_successes
        score += min(0.18, 0.05 * combined_success)
        reasons.append(f"success evidence {combined_success}")

    if template_count > 0:
        score += min(0.12, 0.04 * template_count)
        reasons.append(f"{template_count} action template(s)")

    if trigger_set & task_tokens:
        score += 0.08
        reasons.append("activation trigger matched task")

    usage_stats = usage_stats or {}
    used_count = int(usage_stats.get("used_count", 0) or 0)
    attributed_success_count = int(usage_stats.get("attributed_success_count", 0) or 0)
    attributed_failure_count = int(usage_stats.get("attributed_failure_count", 0) or 0)
    avg_expectation_match_score = usage_stats.get("avg_expectation_match_score")
    avg_quality_score = usage_stats.get("avg_quality_score")

    if used_count > 0:
        score += min(0.12, 0.03 * used_count)
        reasons.append(f"used in outcomes {used_count}x")

    if attributed_success_count > 0:
        score += min(0.18, 0.06 * attributed_success_count)
        reasons.append(f"attributed success {attributed_success_count}")

    if attributed_failure_count > 0:
        score -= min(0.12, 0.04 * attributed_failure_count)
        reasons.append(f"attributed failure {attributed_failure_count}")

    if avg_expectation_match_score is not None and float(avg_expectation_match_score) >= 0.6:
        score += min(0.15, float(avg_expectation_match_score) * 0.15)
        reasons.append(f"expectation-matched outcomes {float(avg_expectation_match_score):.2f}")

    if avg_quality_score is not None and float(avg_quality_score) >= 0.6:
        score += min(0.12, float(avg_quality_score) * 0.12)
        reasons.append(f"outcome quality {float(avg_quality_score):.2f}")

    return score, reasons, triggers


_TRIGGER_OPPORTUNITY_MAP: dict[str, str] = {
    "finetuning": "Task-specific small-model training or adapter pipelines",
    "evaluation": "Benchmark and evaluation harnesses with measurable pass/fail criteria",
    "validation": "Spec-backed validation and acceptance-check workflows",
    "repo_repair": "Automated repo repair, regression triage, and fix suggestions",
    "testing": "Test generation, stabilization, and coverage-improvement workflows",
    "data_pipeline": "Dataset, embedding, ingestion, or packing pipelines",
    "frontend": "Frontend scaffolding, UI modernization, and usability improvements",
    "backend": "Service/API modernization and backend capability upgrades",
    "security": "Security hardening, secret handling, and permission boundary improvements",
    "deployment": "CI/CD, packaging, and deployment automation",
}


def _summarize_new_capabilities(methodologies: list[Any]) -> dict[str, Any]:
    """Summarize domains, capability types, and source repos for newly mined methodologies."""
    domains: dict[str, int] = {}
    capability_types: dict[str, int] = {}
    source_repos: dict[str, int] = {}

    for meth in methodologies:
        capability_data = getattr(meth, "capability_data", None) or {}
        if isinstance(capability_data, dict):
            for domain in capability_data.get("domain", []) or []:
                domains[str(domain)] = domains.get(str(domain), 0) + 1
            cap_type = capability_data.get("capability_type")
            if cap_type:
                capability_types[str(cap_type)] = capability_types.get(str(cap_type), 0) + 1

        for tag in getattr(meth, "tags", []) or []:
            if isinstance(tag, str) and tag.startswith("source:"):
                source_repo = tag.split(":", 1)[1]
                source_repos[source_repo] = source_repos.get(source_repo, 0) + 1

    return {
        "domains": sorted(domains.items(), key=lambda item: (-item[1], item[0])),
        "capability_types": sorted(capability_types.items(), key=lambda item: (-item[1], item[0])),
        "source_repos": sorted(source_repos.items(), key=lambda item: (-item[1], item[0])),
    }


def _infer_feature_opportunities(
    methodologies: list[Any],
    *,
    methodology_ids_with_templates: Optional[set[str]] = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """Infer likely next-step features or updates from newly mined methodologies."""
    trigger_counts: dict[str, int] = {}
    template_ids = methodology_ids_with_templates or set()
    for meth in methodologies:
        template_count = 1 if getattr(meth, "id", "") in template_ids else 0
        for trigger in _derive_activation_triggers(meth, template_count=template_count):
            if trigger in _TRIGGER_OPPORTUNITY_MAP:
                trigger_counts[trigger] = trigger_counts.get(trigger, 0) + 1

    ranked = sorted(trigger_counts.items(), key=lambda item: (-item[1], item[0]))
    opportunities: list[dict[str, Any]] = []
    for trigger, count in ranked[:limit]:
        opportunities.append({
            "trigger": trigger,
            "count": count,
            "description": _TRIGGER_OPPORTUNITY_MAP[trigger],
        })
    return opportunities


def _recently_created_near_mine(
    created_at: Any,
    mine_ts: float,
    *,
    lookback_hours: float = 6.0,
) -> bool:
    """Best-effort fallback for older ledger entries that do not record created IDs."""
    if created_at is None:
        return False
    try:
        created_ts = created_at.timestamp()
    except AttributeError:
        return False
    return (mine_ts - (lookback_hours * 3600)) <= created_ts <= (mine_ts + 300)


def _build_ideation_prompt(
    focus: str,
    repo_contexts: list[dict[str, Any]],
    repo_findings: dict[str, list[dict[str, Any]]],
    cam_memory: dict[str, list[dict[str, Any]]],
    idea_count: int,
) -> str:
    goal = focus.strip() or (
        "Propose novel standalone applications that combine CAM's strongest existing knowledge "
        "with the most useful mechanisms visible in the candidate repos."
    )

    return (
        "You are CAM's product ideation engine.\n"
        "Use the candidate repo context plus CAM's existing knowledge to propose novel, useful, "
        "non-demo application ideas.\n\n"
        "Rules:\n"
        "- Prefer ideas that build, troubleshoot, create, validate, or automate real work.\n"
        "- Do not propose generic chat apps or vague agents.\n"
        "- Each idea must clearly combine CAM knowledge with one or more candidate repos.\n"
        "- Favor standalone apps, not modifications to CAM itself.\n"
        "- Return strict JSON only.\n\n"
        f"User focus:\n{goal}\n\n"
        "Candidate repo summaries:\n"
        f"{json.dumps(repo_contexts, indent=2)}\n\n"
        "Existing mined findings by repo:\n"
        f"{json.dumps(repo_findings, indent=2)}\n\n"
        "CAM memory highlights:\n"
        f"{json.dumps(cam_memory, indent=2)}\n\n"
        f"Return a JSON object with key 'ideas' containing exactly {idea_count} items.\n"
        "Each idea must contain:\n"
        "- title\n"
        "- tagline\n"
        "- problem\n"
        "- why_valuable\n"
        "- novelty\n"
        "- repos_used (array)\n"
        "- cam_knowledge_used (array)\n"
        "- app_request\n"
        "- spec_items (array)\n"
        "- execution_steps (array)\n"
        "- acceptance_checks (array)\n"
        "- repo_mode\n"
        "- build_confidence (0.0 to 1.0)\n"
    )


def _normalize_ideation_payload(payload: dict[str, Any], idea_count: int) -> list[dict[str, Any]]:
    raw_ideas = payload.get("ideas", [])
    if not isinstance(raw_ideas, list):
        return []

    ideas: list[dict[str, Any]] = []
    for idx, idea in enumerate(raw_ideas[:idea_count], start=1):
        if not isinstance(idea, dict):
            continue
        title = str(idea.get("title", "")).strip() or f"Idea {idx}"
        try:
            build_confidence = float(idea.get("build_confidence", 0.5) or 0.5)
        except (TypeError, ValueError):
            build_confidence = 0.5
        normalized = {
            "title": title,
            "tagline": str(idea.get("tagline", "")).strip(),
            "problem": str(idea.get("problem", "")).strip(),
            "why_valuable": str(idea.get("why_valuable", "")).strip(),
            "novelty": str(idea.get("novelty", "")).strip(),
            "repos_used": [str(x).strip() for x in idea.get("repos_used", []) if str(x).strip()],
            "cam_knowledge_used": [str(x).strip() for x in idea.get("cam_knowledge_used", []) if str(x).strip()],
            "app_request": str(idea.get("app_request", "")).strip() or title,
            "spec_items": [str(x).strip() for x in idea.get("spec_items", []) if str(x).strip()],
            "execution_steps": [str(x).strip() for x in idea.get("execution_steps", []) if str(x).strip()],
            "acceptance_checks": [str(x).strip() for x in idea.get("acceptance_checks", []) if str(x).strip()],
            "repo_mode": str(idea.get("repo_mode", "new")).strip() or "new",
            "build_confidence": build_confidence,
        }
        ideas.append(normalized)
    return ideas


def _render_ideation_markdown(
    focus: str,
    source_dir: Path,
    ideas: list[dict[str, Any]],
) -> str:
    lines = [
        "# CAM Ideation Report",
        "",
        f"- Source directory: `{source_dir}`",
        f"- Focus: {focus or 'general'}",
        f"- Ideas generated: {len(ideas)}",
        "",
    ]
    for idx, idea in enumerate(ideas, start=1):
        lines.extend(
            [
                f"## {idx}. {idea['title']}",
                "",
                idea["tagline"] or "_No tagline provided._",
                "",
                f"Problem: {idea['problem']}",
                "",
                f"Why valuable: {idea['why_valuable']}",
                "",
                f"Novelty: {idea['novelty']}",
                "",
                f"Repos used: {', '.join(idea['repos_used']) or 'n/a'}",
                "",
                f"CAM knowledge used: {', '.join(idea['cam_knowledge_used']) or 'n/a'}",
                "",
                f"Build confidence: {idea['build_confidence']:.2f}",
                "",
                "Spec items:",
            ]
        )
        if idea["spec_items"]:
            lines.extend([f"- {item}" for item in idea["spec_items"]])
        else:
            lines.append("- n/a")
        lines.extend(["", "Acceptance checks:"])
        if idea["acceptance_checks"]:
            lines.extend([f"- {item}" for item in idea["acceptance_checks"]])
        else:
            lines.append("- n/a")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _write_ideation_artifacts(
    source_dir: Path,
    focus: str,
    ideas: list[dict[str, Any]],
    raw_payload: dict[str, Any],
) -> tuple[Path, Path]:
    _IDEA_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = _time.strftime("%Y%m%d-%H%M%S", _time.localtime())
    slug = source_dir.name or "ideas"
    json_path = _IDEA_DIR / f"{timestamp}-{slug}-ideas.json"
    md_path = _IDEA_DIR / f"{timestamp}-{slug}-ideas.md"

    json_path.write_text(
        json.dumps(
            {
                "focus": focus,
                "source_dir": str(source_dir),
                "ideas": ideas,
                "raw_payload": raw_payload,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    md_path.write_text(_render_ideation_markdown(focus, source_dir, ideas), encoding="utf-8")
    return json_path, md_path


def _run_validation_check(command: str, cwd: Path, timeout_seconds: float) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            shell=True,
            capture_output=True,
            text=True,
            timeout=max(1.0, timeout_seconds),
            check=False,
        )
        return {
            "command": command,
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "ok": False,
            "returncode": 124,
            "stdout": (exc.stdout or "").strip() if exc.stdout else "",
            "stderr": (exc.stderr or "").strip() if exc.stderr else "",
            "timeout": True,
        }


def _snapshot_repo_state(repo_path: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    if not repo_path.exists():
        return snapshot

    for path in sorted(repo_path.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_path)
        if ".git" in rel.parts:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        snapshot[str(rel)] = json.dumps(
            {
                "size": len(data),
                "sha1": hashlib.sha1(data).hexdigest(),
            },
            sort_keys=True,
        )
    return snapshot


def _looks_like_shell_command(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    shell_markers = ("&&", "||", "|", ">", "<", ";", "./", "../")
    if any(marker in text for marker in shell_markers):
        return True
    first = text.split()[0].lower()
    known_commands = {
        "python", "python3", "pytest", "uv", "npm", "npx", "node",
        "cargo", "go", "make", "ruff", "mypy", "bash", "sh", "git",
        "ls", "cat", "echo", "test", "rg", "grep", "find",
    }
    return first in known_commands


def _validate_create_spec(spec: dict[str, Any], max_minutes: int) -> tuple[bool, dict[str, Any]]:
    start = _time.monotonic()
    findings: list[str] = []
    checks: list[dict[str, Any]] = []
    manual_checks: list[str] = []

    repo_path = Path(str(spec.get("target_repo", ""))).resolve()
    validation_cfg = spec.get("validation", {}) if isinstance(spec.get("validation"), dict) else {}
    acceptance_checks = spec.get("acceptance_checks", []) if isinstance(spec.get("acceptance_checks"), list) else []

    require_repo_exists = bool(validation_cfg.get("require_repo_exists", True))
    require_nonempty_repo = bool(validation_cfg.get("require_nonempty_repo", True))

    if require_repo_exists and not repo_path.exists():
        findings.append(f"target repo does not exist: {repo_path}")
    elif repo_path.exists() and require_nonempty_repo:
        has_files = any(p.is_file() for p in repo_path.rglob("*"))
        if not has_files:
            findings.append(f"target repo has no files: {repo_path}")

    baseline_snapshot = spec.get("baseline_snapshot", {}) if isinstance(spec.get("baseline_snapshot"), dict) else {}
    if repo_path.exists() and baseline_snapshot:
        current_snapshot = _snapshot_repo_state(repo_path)
        if current_snapshot == baseline_snapshot:
            findings.append("target repo is unchanged since create spec was written")

    deadline = start + (max_minutes * 60)
    for command in acceptance_checks:
        if not _looks_like_shell_command(str(command)):
            manual_checks.append(str(command))
            continue
        remaining = deadline - _time.monotonic()
        if remaining <= 0:
            findings.append("validation timed out before all acceptance checks completed")
            break
        check_result = _run_validation_check(str(command), cwd=repo_path, timeout_seconds=remaining)
        checks.append(check_result)
        if not check_result["ok"]:
            findings.append(f"acceptance check failed: {command}")

    expectation_assessment = _assess_expectation_contract(
        spec,
        repo_path=repo_path,
        findings=findings,
        checks=checks,
        manual_checks=manual_checks,
    )
    for item in expectation_assessment.get("hard_failures", []) or []:
        findings.append(f"expectation mismatch: {item}")

    summary = {
        "repo": str(repo_path),
        "title": spec.get("title", ""),
        "request": spec.get("request", ""),
        "repo_mode": spec.get("repo_mode", ""),
        "checks_run": len(checks),
        "checks": checks,
        "manual_checks": manual_checks,
        "findings": findings,
        "expectation_assessment": expectation_assessment,
    }
    return len(findings) == 0, summary


def _validate_benchmark_against_spec(summary: dict[str, Any], spec: dict[str, Any]) -> tuple[bool, list[str]]:
    benchmark = spec.get("benchmark", {}) if isinstance(spec, dict) else {}
    best = summary.get("best", {}) if isinstance(summary, dict) else {}
    findings: list[str] = []

    catastrophic_floor = float(benchmark.get("catastrophic_floor_pct", -35.0))
    lift_pct = float(best.get("hit_rate_lift_pct", 0.0))
    if lift_pct < catastrophic_floor:
        findings.append(
            f"lift {lift_pct:.2f}% is below catastrophic floor {catastrophic_floor:.2f}%"
        )

    require_non_negative = bool(benchmark.get("require_non_negative_lift", False))
    if require_non_negative and lift_pct < 0:
        findings.append(f"lift {lift_pct:.2f}% is negative but spec requires non-negative lift")

    return len(findings) == 0, findings


@app.command()
def evaluate(
    repo: str = typer.Argument(..., help="Path to the repository to evaluate"),
    mode: str = typer.Option(
        "auto", "--mode", "-m",
        help="Evaluation mode: full (all 18 prompts), quick (orientation + deep_analysis only), structural (no agent calls), auto (full if agents configured, else structural)",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Evaluate a repository for enhancement potential.

    Runs structural analysis and the 18-prompt evaluation battery on the
    target repo, storing results in SQLite.

    Modes:
      full       — structural analysis + all 18 evaluation prompts via agents
      quick      — structural analysis + orientation and deep_analysis prompts only
      structural — structural analysis only (no agent calls)
      auto       — uses 'full' if agents are configured, otherwise 'structural'
    """
    _setup_logging(verbose)

    valid_modes = ("full", "quick", "structural", "auto")
    if mode not in valid_modes:
        console.print(f"[red]Invalid mode: {mode}. Use: {', '.join(valid_modes)}[/red]")
        raise typer.Exit(1)

    repo_path = Path(repo).resolve()
    if not repo_path.exists():
        console.print(f"[red]Repository path does not exist: {repo_path}[/red]")
        raise typer.Exit(1)

    asyncio.run(_evaluate_async(repo_path, config, mode))


async def _evaluate_async(repo_path: Path, config_path: Optional[str], mode: str) -> None:
    from claw.core.factory import ClawFactory
    from claw.core.models import Project, Task

    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p, workspace_dir=repo_path)

    try:
        # Reuse an existing project row for this repo_path, or create one.
        project = await ctx.repository.get_project_by_repo_path(str(repo_path))
        if project is None:
            project = Project(
                name=repo_path.name,
                repo_path=str(repo_path),
            )
            await ctx.repository.create_project(project)

        # Resolve "auto" mode based on whether agents are available
        effective_mode = mode
        if mode == "auto":
            effective_mode = "full" if ctx.agents else "structural"

        console.print(f"\n[bold]CLAW Evaluation: {repo_path.name}[/bold]")
        console.print(f"  Repository: {repo_path}")
        console.print(f"  Project ID: {project.id}")
        console.print(f"  Database: {ctx.config.database.db_path}")
        console.print(f"  Mode: {effective_mode}")
        if effective_mode != "structural":
            console.print(f"  Agents: {', '.join(ctx.agents.keys()) or 'none'}")

        # ---------------------------------------------------------------
        # Phase 1: Basic structural analysis (always runs)
        # ---------------------------------------------------------------
        console.print(f"\n[cyan]Phase 1: Structural Analysis[/cyan]")
        analysis = await _analyze_repo(repo_path)

        # Create evaluation task
        eval_task = Task(
            project_id=project.id,
            title=f"Evaluate {repo_path.name}",
            description=f"Structural analysis of {repo_path.name}",
            task_type="analysis",
            priority=10,
        )
        await ctx.repository.create_task(eval_task)

        # Log episode
        await ctx.repository.log_episode(
            session_id="cli-evaluate",
            event_type="evaluation_started",
            event_data={"repo_path": str(repo_path), "analysis": analysis, "mode": effective_mode},
            project_id=project.id,
        )

        # Display structural results
        _display_analysis(analysis, repo_path.name)
        expectation_baseline = _assess_repo_expectation_baseline(analysis)
        console.print(f"\n[bold]Expectation Baseline[/bold]")
        console.print(f"  Match score: {expectation_baseline['score']:.3f}")
        for item in expectation_baseline["unmet"][:5]:
            console.print(f"  [yellow]GAP[/yellow] {item}")

        # Store structural results
        await ctx.repository.log_episode(
            session_id="cli-evaluate",
            event_type="structural_analysis_completed",
            event_data=analysis,
            project_id=project.id,
        )

        # ---------------------------------------------------------------
        # Phase 2: Evaluation Battery (if mode is "full" or "quick")
        # ---------------------------------------------------------------
        if effective_mode in ("full", "quick"):
            from claw.evaluator import Evaluator

            # Determine battery mode for the Evaluator
            battery_mode = effective_mode  # "full" or "quick"

            # Use the dispatcher if agents are available, otherwise None
            # (Evaluator records prompts as pending when dispatcher is None)
            dispatcher = ctx.dispatcher if ctx.agents else None

            evaluator = Evaluator(
                repository=ctx.repository,
                dispatcher=dispatcher,
            )

            agent_status = f"dispatching to {', '.join(ctx.agents.keys())}" if ctx.agents else "no agents (prompts will be recorded as pending)"
            console.print(f"\n[cyan]Phase 2: Evaluation Battery ({battery_mode})[/cyan]")
            console.print(f"  {agent_status}")

            # Run the battery with a live progress indicator
            battery_start = _time.monotonic()
            report = await evaluator.run_battery(
                project_id=project.id,
                repo_path=str(repo_path),
                mode=battery_mode,
            )
            battery_elapsed = _time.monotonic() - battery_start

            # Display the evaluation report
            _display_evaluation_report(report)

            # Log the battery summary as an episode
            await ctx.repository.log_episode(
                session_id="cli-evaluate",
                event_type="evaluation_battery_summary",
                event_data={
                    "mode": battery_mode,
                    "total_prompts": report.total_prompts,
                    "successful_prompts": report.successful_prompts,
                    "failed_prompts": report.failed_prompts,
                    "total_duration_seconds": report.total_duration_seconds,
                    "phases_completed": len(report.phases),
                    "agents_used": list({
                        pr.agent_id
                        for phase in report.phases
                        for pr in phase.prompt_results
                        if pr.agent_id is not None
                    }),
                },
                project_id=project.id,
            )

        # Final status
        await ctx.repository.log_episode(
            session_id="cli-evaluate",
            event_type="evaluation_completed",
            event_data={"mode": effective_mode, "analysis": analysis},
            project_id=project.id,
        )

        console.print(f"\n[green]Evaluation stored in {ctx.config.database.db_path}[/green]")

    finally:
        await ctx.close()


def _display_evaluation_report(report) -> None:
    """Display the evaluation battery report as a Rich table.

    Shows each prompt with its phase, agent, status, and duration,
    followed by a summary line.
    """
    from claw.evaluator import EvaluationReport

    if not isinstance(report, EvaluationReport):
        return

    console.print()

    table = Table(title="Evaluation Battery Results")
    table.add_column("Phase", style="cyan", max_width=22)
    table.add_column("Prompt", style="bold", max_width=22)
    table.add_column("Agent", style="yellow", width=10)
    table.add_column("Status", width=10)
    table.add_column("Duration", justify="right", width=10)
    table.add_column("Error", style="red", max_width=60)

    for phase in report.phases:
        for pr in phase.prompt_results:
            # Phase name (cleaned up for display)
            phase_display = phase.phase_name.replace("_", " ").title()

            # Agent
            agent_display = pr.agent_id or ("pending" if pr.error is None else "-")

            # Status: green check for success, red x for failure, yellow dash for pending
            if pr.error is not None:
                status_display = "[red]FAILED[/red]"
            elif pr.agent_id is not None:
                status_display = "[green]OK[/green]"
            else:
                # No error, but no agent -- prompt was recorded as pending
                status_display = "[yellow]PENDING[/yellow]"

            # Duration
            dur = pr.duration_seconds
            if dur >= 60:
                mins = int(dur // 60)
                secs = int(dur % 60)
                dur_str = f"{mins}m {secs:02d}s"
            elif dur >= 0.01:
                dur_str = f"{dur:.2f}s"
            else:
                dur_str = "<0.01s"

            # Error summary: only populated when the prompt failed
            if pr.error:
                error_text = " ".join(str(pr.error).split())
                if len(error_text) > 60:
                    error_text = error_text[:57] + "..."
                error_display = error_text
            else:
                error_display = ""

            table.add_row(
                phase_display,
                pr.prompt_name,
                agent_display,
                status_display,
                dur_str,
                error_display,
            )

    console.print(table)

    # Summary line
    total = report.total_prompts
    succeeded = report.successful_prompts
    failed = report.failed_prompts
    pending = total - succeeded - failed

    parts = [f"{succeeded}/{total} prompts completed"]
    if failed > 0:
        parts.append(f"[red]{failed} failed[/red]")
    if pending > 0:
        parts.append(f"[yellow]{pending} pending[/yellow]")

    # Show unique agents used
    agents_used = sorted({
        pr.agent_id
        for phase in report.phases
        for pr in phase.prompt_results
        if pr.agent_id is not None
    })
    if agents_used:
        parts.append(f"agents: {', '.join(agents_used)}")

    # Total duration
    dur = report.total_duration_seconds
    if dur >= 60:
        mins = int(dur // 60)
        secs = int(dur % 60)
        dur_str = f"{mins}m {secs:02d}s"
    else:
        dur_str = f"{dur:.2f}s"
    parts.append(f"total: {dur_str}")

    console.print(f"\n  {' | '.join(parts)}")


async def _analyze_repo(repo_path: Path) -> dict:
    """Perform basic structural analysis of a repository."""
    analysis = {
        "has_git": (repo_path / ".git").exists(),
        "has_readme": any(
            (repo_path / f).exists() for f in ["README.md", "readme.md", "README"]
        ),
        "has_tests": any(
            (repo_path / d).exists() for d in ["tests", "test", "spec", "__tests__"]
        ),
        "file_counts": {},
        "total_files": 0,
        "languages_detected": [],
    }

    # Count files by extension
    ext_counts: dict[str, int] = {}
    total = 0
    for f in repo_path.rglob("*"):
        if f.is_file() and ".git" not in f.parts:
            total += 1
            ext = f.suffix.lower() or "(no ext)"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1

    analysis["file_counts"] = dict(sorted(ext_counts.items(), key=lambda x: -x[1])[:20])
    analysis["total_files"] = total

    # Detect languages from extensions
    lang_map = {
        ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
        ".rs": "Rust", ".go": "Go", ".java": "Java", ".rb": "Ruby",
        ".cpp": "C++", ".c": "C", ".cs": "C#", ".swift": "Swift",
        ".kt": "Kotlin", ".scala": "Scala", ".php": "PHP",
    }
    langs = []
    for ext, lang in lang_map.items():
        if ext in ext_counts:
            langs.append(lang)
    analysis["languages_detected"] = langs

    # Check for config files
    config_files = [
        "pyproject.toml", "package.json", "Cargo.toml", "go.mod",
        "pom.xml", "build.gradle", "Gemfile", "Makefile",
        "docker-compose.yml", "Dockerfile",
    ]
    analysis["config_files"] = [f for f in config_files if (repo_path / f).exists()]

    return analysis


def _display_analysis(analysis: dict, name: str) -> None:
    """Display analysis results using Rich."""
    console.print()

    # Summary table
    table = Table(title=f"Repository Analysis: {name}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Total Files", str(analysis["total_files"]))
    table.add_row("Git Repository", "Yes" if analysis["has_git"] else "No")
    table.add_row("Has README", "Yes" if analysis["has_readme"] else "No")
    table.add_row("Has Tests", "Yes" if analysis["has_tests"] else "No")
    table.add_row("Languages", ", ".join(analysis["languages_detected"]) or "None detected")
    table.add_row("Config Files", ", ".join(analysis["config_files"]) or "None")

    console.print(table)

    # File breakdown
    if analysis["file_counts"]:
        ft = Table(title="File Type Breakdown (Top 10)")
        ft.add_column("Extension", style="cyan")
        ft.add_column("Count", style="yellow", justify="right")

        for ext, count in list(analysis["file_counts"].items())[:10]:
            ft.add_row(ext, str(count))

        console.print(ft)


def _assess_repo_expectation_baseline(analysis: dict[str, Any]) -> dict[str, Any]:
    clauses = [
        ("Repository has version-control context", bool(analysis.get("has_git"))),
        ("Repository includes usage or orientation docs", bool(analysis.get("has_readme"))),
        ("Repository includes automated tests", bool(analysis.get("has_tests"))),
        ("Repository includes recognizable build/config files", bool(analysis.get("config_files"))),
        ("Repository structure is concrete enough to improve safely", bool(analysis.get("total_files", 0) > 0)),
    ]
    matched = [text for text, ok in clauses if ok]
    unmet = [text for text, ok in clauses if not ok]
    score = round(len(matched) / len(clauses), 3) if clauses else 0.0
    return {
        "score": score,
        "matched": matched,
        "unmet": unmet,
        "summary": f"repo baseline matched {len(matched)}/{len(clauses)} expectation clauses",
    }


# ---------------------------------------------------------------------------
# cam camify — guided CAM-ification planner
# ---------------------------------------------------------------------------


@app.command()
def camify(
    repo: str = typer.Argument(..., help="Path to the target repository to CAM-ify"),
    goal: list[str] = typer.Option([], "--goal", "-g", help="Enhancement goal (repeatable). Examples: 'enhance error handling', 'learn patterns for CAM KB'"),
    guide: list[str] = typer.Option([], "--guide", help="Path to domain guide .md file (repeatable, auto-detected if omitted)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Path to save the plan markdown"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Analyze a repo, match with CAM's KB, and generate an executable enhancement plan.

    Automates the manual CAM-ify workflow: discover what the repo does, cross-reference
    with CAM's knowledge base of 2,895+ learned methodologies, and produce a step-by-step
    plan with concrete 'cam' commands.

    Examples:
        cam camify /path/to/repo
        cam camify /path/to/repo --goal "enhance error handling" --goal "learn for CAM KB"
        cam camify /path/to/repo --guide /path/to/repo/AI_Augment.md
    """
    _setup_logging(verbose)

    repo_path = Path(repo).resolve()
    if not repo_path.exists():
        console.print(f"[red]Repository path does not exist: {repo_path}[/red]")
        raise typer.Exit(1)
    if not repo_path.is_dir():
        console.print(f"[red]Path is not a directory: {repo_path}[/red]")
        raise typer.Exit(1)

    asyncio.run(_camify_async(
        repo_path=repo_path,
        goals=goal,
        guide_paths=[Path(g) for g in guide],
        output_path=Path(output) if output else None,
        config_path=config,
    ))


async def _camify_async(
    repo_path: Path,
    goals: list[str],
    guide_paths: list[Path],
    output_path: Path | None,
    config_path: str | None,
) -> None:
    from claw.camify import (
        CamifyDiscovery,
        CamifyMatcher,
        CamifyPlanner,
        write_camify_artifact,
    )
    from claw.core.factory import ClawFactory

    console.print(f"\n[bold]CAM-ify Planner: {repo_path.name}[/bold]")
    console.print(f"  Target: {repo_path}")

    # Interactive goal collection if none provided and TTY
    if not goals and sys.stdin.isatty():
        console.print("\n[cyan]No goals specified. Let's define them.[/cyan]")
        while True:
            g = _chat_prompt("Enhancement goal (e.g. 'enhance error handling')")
            if g:
                goals.append(g)
            if not _chat_confirm("Add another goal?", default=False):
                break
    if not goals:
        goals = ["enhance the repo"]

    console.print(f"  Goals: {', '.join(goals)}")

    # Phase 1: Discover
    console.print("\n[cyan]Phase 1: Discovering repository...[/cyan]")
    discovery = CamifyDiscovery()
    profile = await discovery.discover(repo_path, guide_paths or None)

    table = Table(title="Repository Profile")
    table.add_column("Attribute", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Files", str(profile.file_count))
    table.add_row("Languages", ", ".join(profile.languages) or "None")
    table.add_row("README", "Yes" if profile.has_readme else "No")
    table.add_row("CLAUDE.md", "Yes" if profile.has_claude_md else "No")
    table.add_row("Tests", "Yes" if profile.has_tests else "No")
    table.add_row("Guide files", ", ".join(profile.guide_files) or "None auto-detected")
    table.add_row("Domain keywords", ", ".join(profile.domain_keywords[:10]) or "None extracted")
    console.print(table)

    # Phase 2: Match with KB
    console.print("\n[cyan]Phase 2: Matching with CAM knowledge base...[/cyan]")
    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p, workspace_dir=repo_path)
    try:
        matcher = CamifyMatcher()
        matches = await matcher.match(
            profile=profile,
            semantic_memory=ctx.semantic_memory,
            repository=ctx.repository,
        )

        match_table = Table(title="KB Match Results")
        match_table.add_column("KB Size", style="cyan")
        match_table.add_column("Matches", style="green")
        match_table.add_column("Gaps", style="yellow")
        match_table.add_row(
            str(matches.kb_methodology_count),
            str(len(matches.matched_methodologies)),
            ", ".join(matches.gap_areas) or "None",
        )
        console.print(match_table)

        if matches.matched_methodologies:
            mt = Table(title="Top Matched Methodologies")
            mt.add_column("#", style="dim")
            mt.add_column("Problem", style="white")
            mt.add_column("Score", style="green", justify="right")
            for i, m in enumerate(matches.matched_methodologies[:5], 1):
                mt.add_row(str(i), m.problem[:80], str(m.score))
            console.print(mt)

        # Phase 3: Generate plan
        console.print("\n[cyan]Phase 3: Generating enhancement plan...[/cyan]")
        planner = CamifyPlanner()
        plan = planner.plan(profile, matches, goals)
        plan_md = planner.render_markdown(plan)

        # Save
        out_path = write_camify_artifact(plan_md, plan, output_path)
        console.print(f"\n[bold green]Plan saved to: {out_path}[/bold green]")
        console.print(f"  JSON sidecar: {out_path.with_suffix('.json')}")
        console.print(f"  Steps: {len(plan.steps)}")
        console.print(f"  Goals: {len(plan.goals)}")

        # Display plan summary
        console.print(f"\n[bold]Plan Summary[/bold]")
        for i, step in enumerate(plan.steps, 1):
            opt = " [dim](optional)[/dim]" if not step.required else ""
            console.print(f"  {i}. [{step.phase}] {step.purpose}{opt}")

        console.print(f"\n[dim]To execute: review the plan, then run the commands in order.[/dim]")

    finally:
        await ctx.close()


@app.command()
def enhance(
    repo: str = typer.Argument(..., help="Path to the repository to enhance"),
    mode: str = typer.Option("attended", "--mode", "-m", help="Mode: attended, supervised, autonomous"),
    max_tasks: int = typer.Option(10, "--max-tasks", help="Maximum number of tasks to process"),
    battery: bool = typer.Option(False, "--battery", "-b", help="Use full evaluation battery (MesoClaw) instead of structural analysis"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview planned tasks without writing tasks or executing agents"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
    task_id: Optional[str] = typer.Option(
        None,
        "--task-id",
        help="Target a specific pending task id instead of the highest-priority task. "
             "Skips evaluate/plan phases and runs exactly one cycle against that task.",
    ),
) -> None:
    """Enhance a repository: evaluate, plan, dispatch, verify, learn.

    Runs the full MesoClaw pipeline on the target repo.
    Use --battery to run the full 18-prompt evaluation battery.
    Use --task-id <uuid> to execute one specific pending task.
    """
    _setup_logging(verbose)

    repo_path = Path(repo).resolve()
    if not repo_path.exists():
        console.print(f"[red]Repository path does not exist: {repo_path}[/red]")
        raise typer.Exit(1)

    if mode not in ("attended", "supervised", "autonomous"):
        console.print(f"[red]Invalid mode: {mode}. Use attended, supervised, or autonomous.[/red]")
        raise typer.Exit(1)

    if battery:
        asyncio.run(_enhance_battery_async(repo_path, config, mode, max_tasks, dry_run))
    else:
        asyncio.run(_enhance_async(repo_path, config, mode, max_tasks, dry_run, task_id=task_id))


async def _enhance_async(
    repo_path: Path,
    config_path: Optional[str],
    mode: str,
    max_tasks: int,
    dry_run: bool = False,
    task_id: Optional[str] = None,
) -> None:
    from claw.core.factory import ClawFactory
    from claw.core.models import Project
    from claw.cycle import MicroClaw
    from claw.planner import EvaluationResult, Planner

    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p, workspace_dir=repo_path)

    try:
        # Reuse an existing project row for this repo_path, or create one.
        project = await ctx.repository.get_project_by_repo_path(str(repo_path))
        if project is None:
            project = Project(
                name=repo_path.name,
                repo_path=str(repo_path),
            )
            await ctx.repository.create_project(project)

        console.print(f"\n[bold]CLAW Enhancement: {repo_path.name}[/bold]")
        console.print(f"  Repository: {repo_path}")
        console.print(f"  Mode: {mode}")
        console.print(f"  Dry run: {'yes' if dry_run else 'no'}")
        console.print(f"  Agents: {', '.join(ctx.agents.keys()) or 'none'}")

        if not ctx.agents:
            console.print("[red]No agents available. Enable at least one agent in claw.toml.[/red]")
            return
        if not dry_run and not _print_workspace_execution_preflight(ctx, "Enhancement"):
            return

        # Targeted-task fast path: skip evaluate/plan, run one cycle against task_id.
        if task_id:
            targeted = await ctx.repository.get_task(task_id)
            if targeted is None:
                console.print(f"[red]Task id not found: {task_id}[/red]")
                return
            from claw.core.models import TaskStatus as _TS
            if targeted.status != _TS.PENDING:
                console.print(
                    f"[red]Task {task_id} has status {targeted.status.value} (expected PENDING).[/red]"
                )
                return
            console.print(f"\n[cyan]Targeted task mode[/cyan] — running one cycle against: {targeted.title[:80]}")
            if dry_run:
                console.print("[yellow]Dry run enabled: no agents executed.[/yellow]")
                return
            micro = MicroClaw(ctx=ctx, project_id=project.id, target_task_id=task_id)
            cycle_result = await micro.run_cycle()
            if cycle_result.success:
                duration = cycle_result.duration_seconds or 0
                console.print(f"[green]completed[/green] ({duration:.1f}s)")
            else:
                console.print("[yellow]failed[/yellow]")
            _display_task_result(cycle_result)
            return

        # Phase 1: Evaluate
        console.print("\n[cyan]Phase 1: Evaluating repository...[/cyan]")
        analysis = await _analyze_repo(repo_path)
        _display_analysis(analysis, repo_path.name)
        expectation_baseline = _assess_repo_expectation_baseline(analysis)
        console.print(f"\n[bold]Expectation Baseline[/bold]")
        console.print(f"  Match score: {expectation_baseline['score']:.3f}")
        for item in expectation_baseline["unmet"][:5]:
            console.print(f"  [yellow]GAP[/yellow] {item}")

        # Phase 2: Plan — convert analysis into tasks
        console.print("\n[cyan]Phase 2: Planning enhancements...[/cyan]")
        planner = Planner(project_id=project.id, repository=ctx.repository)

        eval_results = _analysis_to_eval_results(analysis, repo_path.name)
        tasks = await planner.analyze_gaps(eval_results)

        if not tasks:
            console.print("[green]No enhancement tasks identified. Repository looks good![/green]")
            return

        tasks = tasks[:max_tasks]
        console.print(f"  Generated {len(tasks)} enhancement tasks")

        if dry_run:
            _display_planned_tasks(tasks, title=f"Planned Tasks (dry-run): {repo_path.name}")
            console.print("\n[yellow]Dry run enabled: no tasks written, no agents executed.[/yellow]")
            return

        # Store tasks in DB
        for task in tasks:
            await ctx.repository.create_task(task)

        # Phase 3: Execute — run MicroClaw cycles
        console.print(f"\n[cyan]Phase 3: Executing {len(tasks)} tasks...[/cyan]")
        micro = MicroClaw(ctx=ctx, project_id=project.id)

        completed = 0
        failed = 0
        for i in range(len(tasks)):
            task_label = tasks[i].title[:60] if i < len(tasks) else "task"
            console.print(f"\n  [bold]Task {i + 1}/{len(tasks)}:[/bold] {task_label}")

            # Progress state shared with the callback
            progress_state = {"step": "starting", "detail": "", "start": _time.monotonic()}

            def on_step(step: str, detail: str) -> None:
                progress_state["step"] = step
                progress_state["detail"] = detail

            async def run_with_progress():
                """Run the cycle while updating a live spinner."""
                cycle_task = asyncio.create_task(micro.run_cycle(on_step=on_step))
                step_icons = {
                    "grab": "[cyan]grab[/cyan]",
                    "evaluate": "[cyan]evaluate[/cyan]",
                    "decide": "[yellow]decide[/yellow]",
                    "act": "[bold green]act[/bold green]",
                    "verify": "[magenta]verify[/magenta]",
                    "learn": "[blue]learn[/blue]",
                    "done": "[green]done[/green]",
                }
                with Live(console=console, refresh_per_second=2, transient=True) as live:
                    while not cycle_task.done():
                        elapsed = _time.monotonic() - progress_state["start"]
                        step = progress_state["step"]
                        icon = step_icons.get(step, step)
                        detail = progress_state["detail"]
                        mins = int(elapsed // 60)
                        secs = int(elapsed % 60)
                        time_str = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
                        live.update(
                            Text.from_markup(
                                f"    [{time_str}] {icon}  {detail}"
                            )
                        )
                        await asyncio.sleep(0.5)
                return cycle_task.result()

            cycle_result = await run_with_progress()

            if cycle_result.success:
                completed += 1
                duration = cycle_result.duration_seconds or 0
                console.print(f"    [green]completed[/green] ({duration:.1f}s)")
            else:
                failed += 1
                console.print(f"    [yellow]failed[/yellow]")

            # Show what the agent did
            _display_task_result(cycle_result)

            if mode == "attended":
                response = console.input("  Continue? [y/n] ")
                if response.lower() != "y":
                    console.print("  [yellow]Paused by user.[/yellow]")
                    break

        # Summary
        console.print(f"\n[bold]Enhancement Summary[/bold]")
        console.print(f"  Completed: {completed}")
        console.print(f"  Failed: {failed}")
        console.print(f"  Results stored in {ctx.config.database.db_path}")

    finally:
        await ctx.close()


async def _enhance_battery_async(
    repo_path: Path,
    config_path: Optional[str],
    mode: str,
    max_tasks: int,
    dry_run: bool = False,
) -> None:
    """Run enhance using the full MesoClaw pipeline with evaluation battery."""
    from claw.core.factory import ClawFactory
    from claw.core.models import Project
    from claw.cycle import MesoClaw

    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p, workspace_dir=repo_path)

    try:
        project = await ctx.repository.get_project_by_repo_path(str(repo_path))
        if project is None:
            project = Project(
                name=repo_path.name,
                repo_path=str(repo_path),
            )
            await ctx.repository.create_project(project)

        console.print(f"\n[bold]CLAW Enhancement (Battery Mode): {repo_path.name}[/bold]")
        console.print(f"  Repository: {repo_path}")
        console.print(f"  Mode: {mode}")
        console.print(f"  Dry run: {'yes' if dry_run else 'no'}")
        console.print(f"  Agents: {', '.join(ctx.agents.keys()) or 'none'}")

        if not ctx.agents:
            console.print("[red]No agents available. Enable at least one agent in claw.toml.[/red]")
            return
        if not dry_run and not _print_workspace_execution_preflight(ctx, "Enhancement"):
            return

        if dry_run:
            meso_preview = MesoClaw(
                ctx=ctx,
                project_id=project.id,
                repo_path=str(repo_path),
            )
            console.print("\n[cyan]Dry-run: evaluating and planning only (no task execution)...[/cyan]")
            evaluation = await meso_preview.evaluate(str(repo_path))
            tasks = await meso_preview.decide(evaluation)
            tasks = tasks[:max_tasks]
            _display_planned_tasks(tasks, title=f"Planned Tasks (battery dry-run): {repo_path.name}")
            console.print("\n[yellow]Dry run enabled: no tasks written, no agents executed.[/yellow]")
            return

        # Run MesoClaw which handles: evaluate -> plan -> dispatch -> verify -> learn
        meso = MesoClaw(
            ctx=ctx,
            project_id=project.id,
            repo_path=str(repo_path),
        )

        console.print("\n[cyan]Running MesoClaw pipeline (evaluate -> plan -> execute -> learn)...[/cyan]")

        progress_state = {"step": "starting", "detail": "", "start": _time.monotonic()}

        def on_step(step: str, detail: str) -> None:
            progress_state["step"] = step
            progress_state["detail"] = detail

        async def run_with_progress():
            cycle_task = asyncio.create_task(meso.run_cycle(on_step=on_step))
            step_icons = {
                "grab": "[cyan]grab[/cyan]",
                "evaluate": "[cyan]evaluate[/cyan]",
                "decide": "[yellow]decide[/yellow]",
                "act": "[bold green]act[/bold green]",
                "verify": "[magenta]verify[/magenta]",
                "learn": "[blue]learn[/blue]",
                "done": "[green]done[/green]",
            }
            with Live(console=console, refresh_per_second=2, transient=True) as live:
                while not cycle_task.done():
                    elapsed = _time.monotonic() - progress_state["start"]
                    step = progress_state["step"]
                    icon = step_icons.get(step, step)
                    detail = progress_state["detail"]
                    mins = int(elapsed // 60)
                    secs = int(elapsed % 60)
                    time_str = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
                    live.update(
                        Text.from_markup(
                            f"    [{time_str}] {icon}  {detail}"
                        )
                    )
                    await asyncio.sleep(0.5)
            return cycle_task.result()

        result = await run_with_progress()

        # Display results
        console.print(f"\n[bold]Enhancement Summary (Battery Mode)[/bold]")
        console.print(f"  Success: {result.success}")
        console.print(f"  Tasks processed: {result.outcome.approach_summary[:200] if result.outcome.approach_summary else 'N/A'}")
        console.print(f"  Duration: {result.duration_seconds:.1f}s")
        console.print(f"  Tokens: {result.tokens_used}")
        console.print(f"  Cost: ${result.cost_usd:.4f}")
        console.print(f"  Results stored in {ctx.config.database.db_path}")

    finally:
        await ctx.close()


def _analysis_to_eval_results(analysis: dict, name: str) -> list:
    """Convert structural analysis into EvaluationResult objects for the Planner."""
    from claw.planner import EvaluationResult

    results = []

    if not analysis.get("has_tests"):
        results.append(EvaluationResult(
            prompt_name="structural_analysis",
            findings=[f"{name} has no test directory — add test infrastructure"],
            severity="high",
            category="testing",
        ))

    if not analysis.get("has_readme"):
        results.append(EvaluationResult(
            prompt_name="structural_analysis",
            findings=[f"{name} is missing a README — add documentation"],
            severity="medium",
            category="docs",
        ))

    if not analysis.get("has_git"):
        results.append(EvaluationResult(
            prompt_name="structural_analysis",
            findings=[f"{name} is not a git repository — initialize git"],
            severity="low",
            category="architecture",
        ))

    if not analysis.get("config_files"):
        results.append(EvaluationResult(
            prompt_name="structural_analysis",
            findings=[f"{name} has no build/config files — add project manifest"],
            severity="medium",
            category="architecture",
        ))

    # If the analysis looks healthy, add a general enhancement task
    if not results:
        results.append(EvaluationResult(
            prompt_name="structural_analysis",
            findings=[f"General code quality review for {name}"],
            severity="low",
            category="analysis",
        ))

    return results


def _display_task_result(cycle_result) -> None:
    """Display the outcome of a single task cycle."""
    from claw.core.models import CycleResult

    if not isinstance(cycle_result, CycleResult):
        return

    outcome = cycle_result.outcome
    verification = cycle_result.verification

    # Agent and cost
    agent = cycle_result.agent_id or "unknown"
    cost = cycle_result.cost_usd
    tokens = cycle_result.tokens_used

    info_parts = [f"Agent: {agent}"]
    if cost > 0:
        info_parts.append(f"Cost: ${cost:.4f}")
    if tokens > 0:
        info_parts.append(f"Tokens: {tokens:,}")
    console.print(f"    {' | '.join(info_parts)}")

    # Approach summary (truncated for display)
    if outcome and outcome.approach_summary:
        summary = outcome.approach_summary
        if len(summary) > 200:
            summary = summary[:200] + "..."
        console.print(f"    [dim]Summary:[/dim] {summary}")

    # Files changed
    if outcome and outcome.files_changed:
        files_str = ", ".join(outcome.files_changed[:5])
        extra = f" (+{len(outcome.files_changed) - 5} more)" if len(outcome.files_changed) > 5 else ""
        console.print(f"    [dim]Files:[/dim] {files_str}{extra}")

    # Verification
    if verification:
        if verification.approved:
            console.print(f"    [green]Verified[/green] (quality: {verification.quality_score or 0:.2f})")
        else:
            v_count = len(verification.violations)
            console.print(f"    [red]Rejected[/red] ({v_count} violation{'s' if v_count != 1 else ''})")
            for v in verification.violations[:3]:
                check = v.get("check", "")
                detail = v.get("detail", "")
                console.print(f"      - {check}: {detail}")

    # Failure reason
    if outcome and outcome.failure_reason and not cycle_result.success:
        console.print(f"    [yellow]Failure:[/yellow] {outcome.failure_reason}")
        if outcome.failure_detail:
            detail = outcome.failure_detail[:150]
            console.print(f"    [dim]{detail}[/dim]")


def _display_planned_tasks(tasks: list, title: str = "Planned Tasks") -> None:
    """Show a concise preview of planned tasks for dry-run workflows."""
    if not tasks:
        console.print("\n[yellow]No tasks were planned.[/yellow]")
        return

    table = Table(title=title, show_lines=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("Priority", justify="right", style="green", width=8)
    table.add_column("Agent", style="yellow", width=10)
    table.add_column("Type", style="cyan", width=18)
    table.add_column("Title", style="white", max_width=46)
    table.add_column("Runbook", style="magenta", width=12)

    for i, task in enumerate(tasks, 1):
        steps = len(getattr(task, "execution_steps", []) or [])
        checks = len(getattr(task, "acceptance_checks", []) or [])
        runbook_label = f"{steps} step/{checks} check"
        if steps != 1:
            runbook_label = f"{steps} steps/{checks} checks"

        table.add_row(
            str(i),
            str(getattr(task, "priority", 0)),
            getattr(task, "recommended_agent", None) or "-",
            (getattr(task, "task_type", None) or "general")[:18],
            (getattr(task, "title", "") or "")[:46],
            runbook_label,
        )

    console.print()
    console.print(table)


# ---------------------------------------------------------------------------
# fleet-enhance command
# ---------------------------------------------------------------------------


@app.command(name="fleet-enhance")
def fleet_enhance(
    repos_dir: str = typer.Argument(..., help="Directory containing repositories to enhance"),
    mode: str = typer.Option("supervised", "--mode", "-m", help="Mode: attended, supervised, autonomous"),
    max_repos: int = typer.Option(10, "--max-repos", help="Maximum number of repos to process"),
    max_tasks_per_repo: int = typer.Option(5, "--max-tasks", help="Maximum tasks per repo"),
    budget: float = typer.Option(50.0, "--budget", "-b", help="Total budget in USD"),
    strategy: str = typer.Option("proportional", "--strategy", help="Budget strategy: proportional or equal"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Enhance multiple repositories across a fleet.

    Scans a directory for git repositories, ranks them by enhancement potential,
    allocates a budget, and runs the MesoClaw pipeline on each repo in ranked order.
    All agent work goes to enhancement branches -- never directly to main.
    """
    _setup_logging(verbose)

    repos_path = Path(repos_dir).resolve()
    if not repos_path.exists():
        console.print(f"[red]Repos directory does not exist: {repos_path}[/red]")
        raise typer.Exit(1)
    if not repos_path.is_dir():
        console.print(f"[red]Path is not a directory: {repos_path}[/red]")
        raise typer.Exit(1)

    if mode not in ("attended", "supervised", "autonomous"):
        console.print(f"[red]Invalid mode: {mode}. Use attended, supervised, or autonomous.[/red]")
        raise typer.Exit(1)

    if strategy not in ("proportional", "equal"):
        console.print(f"[red]Invalid strategy: {strategy}. Use proportional or equal.[/red]")
        raise typer.Exit(1)

    if budget < 0:
        console.print(f"[red]Budget must be non-negative, got {budget}[/red]")
        raise typer.Exit(1)

    if max_repos < 1:
        console.print(f"[red]--max-repos must be at least 1[/red]")
        raise typer.Exit(1)

    asyncio.run(_fleet_enhance_async(
        repos_path, config, mode, max_repos, max_tasks_per_repo, budget, strategy,
    ))


async def _fleet_enhance_async(
    repos_path: Path,
    config_path: Optional[str],
    mode: str,
    max_repos: int,
    max_tasks_per_repo: int,
    budget: float,
    strategy: str,
) -> None:
    from claw.core.factory import ClawFactory
    from claw.core.models import Project
    from claw.cycle import MicroClaw
    from claw.fleet import FleetOrchestrator
    from claw.planner import Planner

    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p, workspace_dir=repos_path)

    try:
        fleet = FleetOrchestrator(repository=ctx.repository, config=ctx.config)

        console.print(f"\n[bold]CLAW Fleet Enhancement[/bold]")
        console.print(f"  Repos directory: {repos_path}")
        console.print(f"  Mode: {mode}")
        console.print(f"  Budget: ${budget:.2f} ({strategy})")
        console.print(f"  Max repos: {max_repos}")
        console.print(f"  Max tasks per repo: {max_tasks_per_repo}")
        console.print(f"  Agents: {', '.join(ctx.agents.keys()) or 'none'}")
        console.print(f"  Database: {ctx.config.database.db_path}")
        if not ctx.agents:
            console.print("[red]No agents available. Enable at least one agent in claw.toml.[/red]")
            return
        if not _print_workspace_execution_preflight(ctx, "Fleet enhancement"):
            return

        # ---------------------------------------------------------------
        # Phase 1: Scan for repositories
        # ---------------------------------------------------------------
        console.print(f"\n[cyan]Phase 1: Scanning for repositories...[/cyan]")
        discovered = await fleet.scan_repos(str(repos_path))

        if not discovered:
            console.print("[yellow]No git repositories found in the directory.[/yellow]")
            return

        # Display discovered repos
        disc_table = Table(title=f"Discovered Repositories ({len(discovered)} found)")
        disc_table.add_column("#", style="dim", width=4)
        disc_table.add_column("Name", style="cyan", max_width=30)
        disc_table.add_column("Path", style="dim", max_width=50)
        disc_table.add_column("Branch", style="yellow", width=16)
        disc_table.add_column("Last Commit", style="green", width=22)

        for i, repo_info in enumerate(discovered, 1):
            branch = repo_info.get("default_branch") or "-"
            last_commit = repo_info.get("last_commit_date") or "-"
            # Truncate the ISO timestamp for display
            if last_commit != "-" and len(last_commit) > 19:
                last_commit = last_commit[:19]
            disc_table.add_row(
                str(i),
                repo_info["name"],
                repo_info["path"],
                branch,
                last_commit,
            )

        console.print(disc_table)

        # ---------------------------------------------------------------
        # Phase 2: Register repos
        # ---------------------------------------------------------------
        console.print(f"\n[cyan]Phase 2: Registering repositories...[/cyan]")
        repo_ids: dict[str, str] = {}  # repo_path -> repo_id
        for repo_info in discovered:
            repo_id = await fleet.register_repo(
                repo_path=repo_info["path"],
                repo_name=repo_info["name"],
            )
            repo_ids[repo_info["path"]] = repo_id
        console.print(f"  Registered {len(repo_ids)} repositories")

        # ---------------------------------------------------------------
        # Phase 3: Rank repos
        # ---------------------------------------------------------------
        console.print(f"\n[cyan]Phase 3: Ranking repositories...[/cyan]")
        ranked = await fleet.rank_repos()

        if not ranked:
            console.print("[yellow]No repos eligible for ranking (all completed or skipped).[/yellow]")
            return

        rank_table = Table(title="Repository Ranking")
        rank_table.add_column("Rank", style="bold", width=5)
        rank_table.add_column("Name", style="cyan", max_width=30)
        rank_table.add_column("Priority", justify="right", width=9)
        rank_table.add_column("Score", style="green", justify="right", width=8)
        rank_table.add_column("Status", width=12)

        for i, repo in enumerate(ranked[:max_repos], 1):
            status_val = repo.get("status", "pending")
            if status_val == "pending":
                status_display = "[yellow]pending[/yellow]"
            elif status_val == "completed":
                status_display = "[green]completed[/green]"
            elif status_val == "failed":
                status_display = "[red]failed[/red]"
            else:
                status_display = status_val
            rank_table.add_row(
                str(i),
                repo["repo_name"],
                f"{repo['priority']:.2f}",
                f"{repo['rank_score']:.4f}",
                status_display,
            )

        console.print(rank_table)

        # ---------------------------------------------------------------
        # Phase 4: Allocate budget
        # ---------------------------------------------------------------
        console.print(f"\n[cyan]Phase 4: Allocating budget...[/cyan]")
        allocation_result = await fleet.allocate_budget(
            total_budget_usd=budget,
            strategy=strategy,
        )

        if allocation_result["allocations"]:
            budget_table = Table(title=f"Budget Allocation (strategy: {strategy})")
            budget_table.add_column("Repo", style="cyan", max_width=30)
            budget_table.add_column("Allocated", style="green", justify="right", width=12)

            for alloc in allocation_result["allocations"]:
                budget_table.add_row(
                    alloc["repo_name"],
                    f"${alloc['allocated_usd']:.4f}",
                )

            budget_table.add_section()
            budget_table.add_row(
                "[bold]Total Allocated[/bold]",
                f"[bold]${allocation_result['allocated_usd']:.4f}[/bold]",
            )
            budget_table.add_row(
                "[dim]Unallocated[/dim]",
                f"[dim]${budget - allocation_result['allocated_usd']:.4f}[/dim]",
            )

            console.print(budget_table)
        else:
            console.print("  [yellow]No repos eligible for budget allocation.[/yellow]")

        # ---------------------------------------------------------------
        # Phase 5: Process repos
        # ---------------------------------------------------------------
        repos_to_process = ranked[:max_repos]
        console.print(
            f"\n[cyan]Phase 5: Processing {len(repos_to_process)} "
            f"repositor{'y' if len(repos_to_process) == 1 else 'ies'}...[/cyan]"
        )

        fleet_completed = 0
        fleet_failed = 0
        fleet_skipped = 0
        total_tasks_created = 0
        total_tasks_completed = 0

        for repo_idx, repo_row in enumerate(repos_to_process, 1):
            repo_name = repo_row["repo_name"]
            repo_path_str = repo_row["repo_path"]
            repo_id = repo_row["id"]
            repo_path_obj = Path(repo_path_str)

            console.print(
                f"\n{'=' * 60}\n"
                f"[bold]Repo {repo_idx}/{len(repos_to_process)}: {repo_name}[/bold]\n"
                f"  Path: {repo_path_str}"
            )

            if not repo_path_obj.exists():
                console.print(f"  [red]Path no longer exists, skipping.[/red]")
                await fleet.update_repo_status(repo_id, "skipped")
                fleet_skipped += 1
                continue

            try:
                # 5a: Create enhancement branch
                console.print(f"  [dim]Creating enhancement branch...[/dim]")
                try:
                    branch_name = await fleet.create_enhancement_branch(repo_path_str)
                    console.print(f"  Branch: [green]{branch_name}[/green]")
                    await fleet.update_repo_status(
                        repo_id, "enhancing",
                        enhancement_branch=branch_name,
                    )
                except RuntimeError as branch_err:
                    console.print(f"  [yellow]Branch creation failed: {branch_err}[/yellow]")
                    console.print(f"  [dim]Continuing on current branch.[/dim]")
                    await fleet.update_repo_status(repo_id, "enhancing")

                # 5b: Create project in DB (idempotent — re-runs of fleet
                # enhance must not duplicate rows for the same repo path).
                existing = await ctx.repository.get_project_by_repo_path(repo_path_str)
                if existing is not None:
                    project = existing
                else:
                    project = Project(
                        name=repo_name,
                        repo_path=repo_path_str,
                    )
                    await ctx.repository.create_project(project)

                # 5c: Run structural analysis
                console.print(f"  [dim]Analyzing repository...[/dim]")
                analysis = await _analyze_repo(repo_path_obj)
                _display_analysis(analysis, repo_name)

                # Update evaluation timestamp
                from datetime import UTC, datetime
                await fleet.update_repo_status(
                    repo_id, "enhancing",
                    last_evaluated_at=datetime.now(UTC).isoformat(),
                )

                # Log episode
                await ctx.repository.log_episode(
                    session_id=f"fleet-{repo_id}",
                    event_type="fleet_repo_evaluated",
                    event_data={"repo_name": repo_name, "analysis": analysis},
                    project_id=project.id,
                )

                # 5d: Plan and execute tasks (requires agents)
                if ctx.agents:
                    console.print(f"  [dim]Planning enhancements...[/dim]")
                    planner = Planner(project_id=project.id, repository=ctx.repository)
                    eval_results = _analysis_to_eval_results(analysis, repo_name)
                    tasks = await planner.analyze_gaps(eval_results)

                    if not tasks:
                        console.print(f"  [green]No enhancement tasks for {repo_name}.[/green]")
                        await fleet.update_repo_status(
                            repo_id, "completed",
                            tasks_created=0,
                            tasks_completed=0,
                        )
                        fleet_completed += 1
                        continue

                    tasks = tasks[:max_tasks_per_repo]
                    for task in tasks:
                        await ctx.repository.create_task(task)

                    repo_tasks_created = len(tasks)
                    total_tasks_created += repo_tasks_created

                    await fleet.update_repo_status(
                        repo_id, "enhancing",
                        tasks_created=repo_tasks_created,
                    )

                    console.print(f"  Generated {repo_tasks_created} tasks")

                    # 5e: Run MicroClaw cycles
                    micro = MicroClaw(ctx=ctx, project_id=project.id)
                    repo_completed = 0
                    repo_failed = 0

                    for task_idx in range(len(tasks)):
                        task_label = tasks[task_idx].title[:60]
                        console.print(
                            f"\n  [bold]Task {task_idx + 1}/{len(tasks)}:[/bold] {task_label}"
                        )

                        progress_state = {
                            "step": "starting",
                            "detail": "",
                            "start": _time.monotonic(),
                        }

                        def on_step(step: str, detail: str) -> None:
                            progress_state["step"] = step
                            progress_state["detail"] = detail

                        async def run_with_progress():
                            """Run the cycle while updating a live spinner."""
                            cycle_task = asyncio.create_task(
                                micro.run_cycle(on_step=on_step)
                            )
                            step_icons = {
                                "grab": "[cyan]grab[/cyan]",
                                "evaluate": "[cyan]evaluate[/cyan]",
                                "decide": "[yellow]decide[/yellow]",
                                "act": "[bold green]act[/bold green]",
                                "verify": "[magenta]verify[/magenta]",
                                "learn": "[blue]learn[/blue]",
                                "done": "[green]done[/green]",
                            }
                            with Live(
                                console=console,
                                refresh_per_second=2,
                                transient=True,
                            ) as live:
                                while not cycle_task.done():
                                    elapsed = _time.monotonic() - progress_state["start"]
                                    step = progress_state["step"]
                                    icon = step_icons.get(step, step)
                                    detail = progress_state["detail"]
                                    mins = int(elapsed // 60)
                                    secs = int(elapsed % 60)
                                    time_str = (
                                        f"{mins}m {secs:02d}s" if mins else f"{secs}s"
                                    )
                                    live.update(
                                        Text.from_markup(
                                            f"    [{time_str}] {icon}  {detail}"
                                        )
                                    )
                                    await asyncio.sleep(0.5)
                            return cycle_task.result()

                        cycle_result = await run_with_progress()

                        if cycle_result.success:
                            repo_completed += 1
                            duration = cycle_result.duration_seconds or 0
                            console.print(
                                f"    [green]completed[/green] ({duration:.1f}s)"
                            )
                        else:
                            repo_failed += 1
                            console.print(f"    [yellow]failed[/yellow]")

                        _display_task_result(cycle_result)

                        if mode == "attended":
                            response = console.input("  Continue to next task? [y/n] ")
                            if response.lower() != "y":
                                console.print(
                                    "  [yellow]Skipping remaining tasks for this repo.[/yellow]"
                                )
                                break

                    total_tasks_completed += repo_completed

                    # 5f: Display per-repo results
                    console.print(f"\n  [bold]{repo_name} Results:[/bold]")
                    console.print(f"    Tasks completed: {repo_completed}/{repo_tasks_created}")
                    console.print(f"    Tasks failed: {repo_failed}")

                    # 5g: Update repo status
                    final_status = "completed" if repo_failed == 0 else "failed"
                    await fleet.update_repo_status(
                        repo_id, final_status,
                        tasks_completed=repo_completed,
                    )

                    if final_status == "completed":
                        fleet_completed += 1
                    else:
                        fleet_failed += 1

                else:
                    # No agents available -- scan and rank only
                    console.print(
                        f"  [yellow]No agents available. "
                        f"Analysis stored but no tasks executed.[/yellow]"
                    )
                    await fleet.update_repo_status(
                        repo_id, "completed",
                        tasks_created=0,
                        tasks_completed=0,
                    )
                    fleet_completed += 1

            except Exception as repo_err:
                console.print(f"  [red]Error processing {repo_name}: {repo_err}[/red]")
                logging.getLogger("claw.cli").error(
                    "Fleet repo %s failed: %s", repo_name, repo_err, exc_info=True,
                )
                try:
                    await fleet.update_repo_status(repo_id, "failed")
                except Exception:
                    pass  # Best-effort status update on error path
                fleet_failed += 1

            # In attended mode, ask before moving to the next repo
            if mode == "attended" and repo_idx < len(repos_to_process):
                response = console.input("\n  Continue to next repo? [y/n] ")
                if response.lower() != "y":
                    console.print("  [yellow]Fleet processing paused by user.[/yellow]")
                    break

        # ---------------------------------------------------------------
        # Phase 6: Fleet summary
        # ---------------------------------------------------------------
        console.print(f"\n{'=' * 60}")
        summary = await fleet.get_fleet_summary()
        _display_fleet_summary(summary, fleet_completed, fleet_failed, fleet_skipped)

        console.print(f"\n[dim]Results stored in {ctx.config.database.db_path}[/dim]")

    finally:
        await ctx.close()


def _display_fleet_summary(
    summary: dict,
    repos_completed: int,
    repos_failed: int,
    repos_skipped: int,
) -> None:
    """Display the fleet processing summary using Rich tables."""

    summary_table = Table(title="Fleet Enhancement Summary", show_lines=True)
    summary_table.add_column("Metric", style="cyan", width=28)
    summary_table.add_column("Value", style="green", justify="right", width=20)

    summary_table.add_row(
        "Total Repos in Fleet",
        str(summary.get("total_repos", 0)),
    )
    summary_table.add_row("Repos Completed", f"[green]{repos_completed}[/green]")
    summary_table.add_row(
        "Repos Failed",
        f"[red]{repos_failed}[/red]" if repos_failed else "0",
    )
    summary_table.add_row(
        "Repos Skipped",
        f"[yellow]{repos_skipped}[/yellow]" if repos_skipped else "0",
    )

    # Status breakdown from DB
    by_status = summary.get("by_status", {})
    if by_status:
        status_parts = []
        for status_name, count in sorted(by_status.items()):
            status_parts.append(f"{status_name}: {count}")
        summary_table.add_row("Status Breakdown", ", ".join(status_parts))

    # Budget
    allocated = summary.get("total_budget_allocated_usd", 0.0)
    used = summary.get("total_budget_used_usd", 0.0)
    summary_table.add_row("Budget Allocated", f"${allocated:.4f}")
    summary_table.add_row("Budget Used", f"${used:.4f}")
    if allocated > 0:
        usage_pct = (used / allocated) * 100.0
        summary_table.add_row("Budget Usage", f"{usage_pct:.1f}%")

    # Tasks
    tasks_created = summary.get("total_tasks_created", 0)
    tasks_completed = summary.get("total_tasks_completed", 0)
    summary_table.add_row("Tasks Created", str(tasks_created))
    summary_table.add_row("Tasks Completed", str(tasks_completed))

    completion_rate = summary.get("completion_rate", 0.0)
    if tasks_created > 0:
        rate_str = f"{completion_rate * 100:.1f}%"
        if completion_rate >= 0.8:
            rate_display = f"[green]{rate_str}[/green]"
        elif completion_rate >= 0.5:
            rate_display = f"[yellow]{rate_str}[/yellow]"
        else:
            rate_display = f"[red]{rate_str}[/red]"
    else:
        rate_display = "-"
    summary_table.add_row("Completion Rate", rate_display)

    console.print(summary_table)


# ---------------------------------------------------------------------------
# results command
# ---------------------------------------------------------------------------


@app.command(hidden=True)
def results(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of results to show"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Filter by project ID"),
) -> None:
    """Show past task results from the database."""
    _setup_logging(False)
    asyncio.run(_results_async(config, limit, project))


async def _results_async(config_path: Optional[str], limit: int, project_id: Optional[str]) -> None:
    from claw.core.factory import ClawFactory

    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p)

    try:
        rows = await ctx.repository.get_project_results(project_id=project_id, limit=limit)

        if not rows:
            console.print("\n[yellow]No task results found.[/yellow]")
            return

        console.print(f"\n[bold]CLAW Task Results[/bold] ({len(rows)} shown)\n")
        usage_summary = await ctx.repository.get_methodology_usage_summary_for_tasks(
            [str(row["task_id"]) for row in rows if row.get("task_id")]
        )

        table = Table(show_lines=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Task", style="cyan", max_width=40)
        table.add_column("Status", width=10)
        table.add_column("Agent", style="yellow", width=8)
        table.add_column("Outcome", width=9)
        table.add_column("Knowledge", width=18)
        table.add_column("Duration", justify="right", width=8)
        table.add_column("Summary", max_width=50)

        for i, row in enumerate(rows, 1):
            title = (row.get("title") or "")[:40]
            status_val = row.get("status", "")
            agent = row.get("agent_id") or row.get("assigned_agent") or "-"
            hypothesis_outcome = row.get("hypothesis_outcome") or "-"
            duration = row.get("duration_seconds")
            summary = (row.get("approach_summary") or "")[:50]
            usage = usage_summary.get(str(row.get("task_id")), {})

            status_display = _display_task_status(str(status_val), str(hypothesis_outcome))

            # Color outcome
            if hypothesis_outcome == "SUCCESS":
                outcome_display = "[green]SUCCESS[/green]"
            elif hypothesis_outcome == "FAILURE":
                outcome_display = "[red]FAILURE[/red]"
            else:
                outcome_display = hypothesis_outcome

            # Format duration
            if duration:
                mins = int(duration // 60)
                secs = int(duration % 60)
                dur_str = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
            else:
                dur_str = "-"

            if usage:
                knowledge_parts = [
                    f"r{usage.get('retrieved_count', 0)}",
                    f"u{usage.get('used_count', 0)}",
                ]
                attributed_count = int(usage.get("attributed_count", 0) or 0)
                if attributed_count:
                    knowledge_parts.append(f"a{attributed_count}")
                expectation_score = usage.get("avg_expectation_match_score")
                if expectation_score is not None:
                    knowledge_parts.append(f"e{float(expectation_score):.2f}")
                knowledge_str = " ".join(knowledge_parts)
            else:
                knowledge_str = "-"

            table.add_row(
                str(i), title, status_display, agent,
                outcome_display, knowledge_str, dur_str, summary,
            )

        console.print(table)

        # Quick summary stats
        total = len(rows)
        successes = sum(1 for r in rows if r.get("hypothesis_outcome") == "SUCCESS")
        failures = sum(1 for r in rows if r.get("hypothesis_outcome") == "FAILURE")
        pending = sum(1 for r in rows if r.get("status") == "PENDING")
        console.print(f"\n  Total: {total} | Success: {successes} | Failed: {failures} | Pending: {pending}")

    finally:
        await ctx.close()


@app.command()
def status(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Show CLAW system status."""
    _setup_logging(False)
    asyncio.run(_status_async(config))


async def _status_async(config_path: Optional[str]) -> None:
    from claw.core.factory import ClawFactory

    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p)

    try:
        console.print("\n[bold]CLAW System Status[/bold]")
        console.print(f"  Database: {ctx.config.database.db_path}")
        console.print(f"  Agents: {', '.join(ctx.agents.keys()) or 'none'}")

        # Check agent health
        for name, agent in ctx.agents.items():
            health = await agent.health_check()
            status_str = "[green]available[/green]" if health.available else f"[red]unavailable: {health.error}[/red]"
            console.print(f"  {name}: {status_str}")

        writable_agents, readonly_agents = _workspace_execution_agents(ctx)
        console.print("\n  Execution capability:")
        if writable_agents:
            console.print(f"    executable agents: {', '.join(writable_agents)}")
        else:
            console.print("    [red]executable agents: none[/red]")
        if readonly_agents:
            console.print(f"    reasoning-only agents: {', '.join(readonly_agents)}")

        # Knowledge base health — warn if empty (T11, punch list #6)
        try:
            kb_row = await ctx.engine.fetch_one(
                "SELECT COUNT(*) as cnt FROM methodologies"
            )
            kb_count = kb_row["cnt"] if kb_row else 0
            seed_row = await ctx.engine.fetch_one(
                "SELECT COUNT(*) as cnt FROM methodologies WHERE tags LIKE ?",
                ['%"origin:seed"%'],
            )
            seed_count = seed_row["cnt"] if seed_row else 0
            console.print("\n  Knowledge base:")
            if kb_count == 0:
                console.print(
                    "    [red]methodologies: 0[/red]  "
                    "[dim](run [bold]cam kb bootstrap[/bold] to seed)[/dim]"
                )
            else:
                console.print(
                    f"    methodologies: {kb_count} "
                    f"([dim]{seed_count} seed[/dim])"
                )
        except Exception as kb_exc:
            console.print(f"  [yellow]Knowledge base check failed: {kb_exc}[/yellow]")

        # Local LLM (Ollama) health — optional check (T11, punch list #10)
        try:
            local_cfg = getattr(ctx.config, "local_llm", None)
            if local_cfg and getattr(local_cfg, "provider", "") == "ollama":
                import httpx
                try:
                    async with httpx.AsyncClient(timeout=2.0) as client:
                        resp = await client.get("http://localhost:11434/api/tags")
                    if resp.status_code == 200:
                        tags_data = resp.json()
                        model_count = len(tags_data.get("models", []))
                        console.print(
                            f"  Local LLM (Ollama): "
                            f"[green]running[/green] "
                            f"([dim]{model_count} models[/dim])"
                        )
                    else:
                        console.print(
                            f"  Local LLM (Ollama): "
                            f"[yellow]HTTP {resp.status_code}[/yellow]"
                        )
                except Exception:
                    console.print(
                        "  Local LLM (Ollama): [red]not responding[/red]  "
                        "[dim](start with [bold]ollama serve[/bold])[/dim]"
                    )
        except Exception:
            pass  # Ollama check is optional; don't break status

        # Task summary
        summary = await ctx.repository.get_task_status_summary()
        if summary:
            console.print("\n  Task Summary:")
            for status, count in summary.items():
                console.print(f"    {status}: {count}")
        else:
            console.print("  No tasks yet.")

    finally:
        await ctx.close()


async def _expectations_async(config_path: Optional[str]) -> None:
    from claw.core.factory import ClawFactory

    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p)

    try:
        report = _build_foundation_expectation_report(ctx)
        console.print("\n[bold]CAM Expectations[/bold]")
        console.print("  Purpose: keep CAM aligned with its stated role as a learning + building system")

        charter = Table(title="Project Charter")
        charter.add_column("Expectation", style="cyan")
        charter.add_column("Meaning", max_width=80)
        for item in _FOUNDATION_CHARTER:
            charter.add_row(item["name"], item["expectation"])
        console.print(charter)

        checks = Table(title="Current Runtime Checks")
        checks.add_column("Check", style="cyan")
        checks.add_column("Status", style="bold")
        checks.add_column("Detail", max_width=84)
        for item in report["checks"]:
            status = "[green]ok[/green]" if item["ok"] else "[red]gap[/red]"
            checks.add_row(item["name"], status, item["detail"])
        console.print(checks)

        if report["builder_execution_available"]:
            console.print(
                f"\n[green]Builder execution available via: {', '.join(report['writable_agents'])}[/green]"
            )
        else:
            console.print(
                "\n[yellow]Current consequence: `create --execute`, `quickstart --execute`, and non-dry-run `enhance` "
                "must be treated as planning/spec workflows until a writable agent is configured.[/yellow]"
            )
    finally:
        await ctx.close()


async def _doctor_audit_async(
    limit: int,
    expectation_threshold: float,
    config_path: Optional[str],
    json_out: Optional[str],
    fail_on_flags: bool,
) -> None:
    from claw.core.config import load_config
    from claw.db.engine import DatabaseEngine
    from claw.db.repository import Repository

    cfg = load_config(Path(config_path) if config_path else None)
    engine = DatabaseEngine(cfg.database)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    repository = Repository(engine)

    try:
        audit = await repository.get_methodology_evidence_audit(
            limit=limit,
            expectation_threshold=expectation_threshold,
        )
        summary = audit["summary"]
        flagged = audit["flagged"]
        payload = {
            "summary": summary,
            "flagged": flagged,
            "expectation_threshold": expectation_threshold,
            "limit": limit,
        }

        console.print("\n[bold]CAM Evidence Audit[/bold]")
        console.print(
            "  Purpose: flag thriving/global methodologies that still rely on weak or legacy evidence and identify demotion candidates"
        )

        summary_table = Table(title="Evidence Summary")
        summary_table.add_column("Metric", style="cyan")
        summary_table.add_column("Count", justify="right", style="bold")
        summary_table.add_row("High-trust reviewed", str(summary["total_reviewed"]))
        summary_table.add_row("Thriving", str(summary["thriving_total"]))
        summary_table.add_row("Global", str(summary["global_total"]))
        summary_table.add_row("Attribution-backed", str(summary["attribution_backed_total"]))
        summary_table.add_row("Legacy-backed", str(summary["legacy_backed_total"]))
        summary_table.add_row("Low expectation", str(summary["low_expectation_total"]))
        summary_table.add_row("Demotion candidates", str(summary["demotion_candidate_total"]))
        summary_table.add_row("Flagged", str(summary["flagged_total"]))
        console.print(summary_table)

        if json_out:
            out_path = Path(json_out)
            if not out_path.is_absolute():
                out_path = Path.cwd() / out_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            console.print(f"\n[dim]JSON report written: {out_path}[/dim]")

        if not flagged:
            console.print(
                f"\n[green]No flagged high-trust methodologies found at threshold {expectation_threshold:.2f}.[/green]"
            )
            return

        table = Table(title="Flagged High-Trust Methodologies")
        table.add_column("ID", style="cyan", width=8)
        table.add_column("State", width=10)
        table.add_column("Scope", width=8)
        table.add_column("Evidence", width=11)
        table.add_column("Attr Succ", justify="right", width=9)
        table.add_column("Exp", justify="right", width=6)
        table.add_column("Flags", max_width=38)
        table.add_column("Problem", max_width=44)
        for item in flagged:
            expectation_score = item.get("avg_expectation_match_score")
            table.add_row(
                item["id"][:8],
                item["lifecycle_state"],
                item["scope"],
                item["evidence_source"],
                str(item["attributed_success_count"]),
                "-" if expectation_score is None else f"{float(expectation_score):.2f}",
                ", ".join(item["flags"]),
                item["problem_description"][:44],
            )
        console.print(table)
        if fail_on_flags:
            raise typer.Exit(1)
    finally:
        await engine.close()


def _display_runbook_details(task, project_name: str, action_template=None, usage_entries: Optional[list[Any]] = None) -> None:
    """Render runbook sections for a task with optional template fallback."""
    execution_steps = list(task.execution_steps)
    acceptance_checks = list(task.acceptance_checks)
    preconditions: list[str] = []
    rollback_steps: list[str] = []

    if action_template is not None:
        if not execution_steps:
            execution_steps = list(action_template.execution_steps)
        if not acceptance_checks:
            acceptance_checks = list(action_template.acceptance_checks)
        preconditions = list(action_template.preconditions)
        rollback_steps = list(action_template.rollback_steps)

    console.print(f"\n[bold]Task Runbook[/bold]")
    console.print(f"  Task: {task.title}")
    console.print(f"  Task ID: {task.id}")
    console.print(f"  Project: {project_name}")
    console.print(f"  Status: {task.status.value}")
    console.print(f"  Agent: {task.recommended_agent or task.assigned_agent or '-'}")
    if action_template is not None:
        console.print(
            f"  Template: {action_template.title} "
            f"(confidence={action_template.confidence:.2f}, "
            f"S/F={action_template.success_count}/{action_template.failure_count})"
        )

    usage_summary = _summarize_methodology_usage(usage_entries or [])
    if usage_summary["total_events"] > 0:
        console.print(
            "  Knowledge Attribution: "
            f"{usage_summary['methodology_count']} methodology(s), "
            f"retrieved={usage_summary['retrieved_count']}, "
            f"used={usage_summary['used_count']}, "
            f"attributed={usage_summary['attributed_count']}"
        )
        if usage_summary["avg_expectation_match_score"] is not None:
            console.print(
                f"  Expectation Match: {float(usage_summary['avg_expectation_match_score']):.2f}"
            )

    if preconditions:
        console.print("\n[cyan]Preconditions[/cyan]")
        for item in preconditions:
            console.print(f"  - {item}")

    if execution_steps:
        console.print("\n[cyan]Execution Steps[/cyan]")
        for i, step in enumerate(execution_steps, 1):
            console.print(f"  {i}. {step}")
    else:
        console.print("\n[yellow]No execution steps defined yet.[/yellow]")

    if acceptance_checks:
        console.print("\n[cyan]Acceptance Checks[/cyan]")
        for i, check in enumerate(acceptance_checks, 1):
            console.print(f"  {i}. {check}")
    else:
        console.print("\n[yellow]No acceptance checks defined yet.[/yellow]")

    if rollback_steps:
        console.print("\n[cyan]Rollback Steps[/cyan]")
        for i, step in enumerate(rollback_steps, 1):
            console.print(f"  {i}. {step}")

    if usage_summary["top_methodologies"]:
        usage_table = Table(title="Methodology Attribution")
        usage_table.add_column("Methodology", style="cyan")
        usage_table.add_column("Retrieved", justify="right")
        usage_table.add_column("Used", justify="right")
        usage_table.add_column("Success", justify="right")
        usage_table.add_column("Expect", justify="right")
        for item in usage_summary["top_methodologies"][:8]:
            expectation_score = item.get("avg_expectation_match_score")
            usage_table.add_row(
                str(item["methodology_id"])[:8],
                str(item["retrieved_count"]),
                str(item["used_count"]),
                str(item["success_count"]),
                "-" if expectation_score is None else f"{float(expectation_score):.2f}",
            )
        console.print()
        console.print(usage_table)


@app.command(hidden=True)
def runbook(
    task_id: str = typer.Argument(..., help="Task ID to inspect"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Display execution steps and acceptance checks for a task."""
    _setup_logging(False)
    asyncio.run(_runbook_async(task_id, config))


async def _runbook_async(task_id: str, config_path: Optional[str]) -> None:
    from claw.core.factory import ClawFactory

    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p)

    try:
        task = await ctx.repository.get_task(task_id)
        if task is None:
            console.print(f"[red]Task not found: {task_id}[/red]")
            raise typer.Exit(1)

        project = await ctx.repository.get_project(task.project_id)
        action_template = None
        usage_entries = await ctx.repository.get_methodology_usage_for_task(task.id)
        if task.action_template_id:
            action_template = await ctx.repository.get_action_template(task.action_template_id)
        _display_runbook_details(
            task=task,
            project_name=project.name if project else task.project_id,
            action_template=action_template,
            usage_entries=usage_entries,
        )

        console.print("\n[dim]Use `cam enhance <repo> --dry-run` to preview execution without running agents.[/dim]")

    finally:
        await ctx.close()


async def _learn_usage_async(task_id: str, config_path: Optional[str]) -> None:
    from claw.core.factory import ClawFactory

    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p)

    try:
        task = await ctx.repository.get_task(task_id)
        if task is None:
            console.print(f"[red]Task not found: {task_id}[/red]")
            raise typer.Exit(1)

        entries = await ctx.repository.get_methodology_usage_for_task(task.id)
        summary = _summarize_methodology_usage(entries)

        console.print("\n[bold]CAM Methodology Usage[/bold]")
        console.print(f"  Task: {task.title}")
        console.print(f"  Task ID: {task.id}")
        console.print(
            f"  Retrieved={summary['retrieved_count']} | "
            f"Used={summary['used_count']} | "
            f"Attributed={summary['attributed_count']}"
        )
        if summary["avg_expectation_match_score"] is not None:
            console.print(f"  Avg Expectation Match: {float(summary['avg_expectation_match_score']):.2f}")

        if not entries:
            console.print("\n[yellow]No methodology attribution recorded yet.[/yellow]")
            return

        by_methodology = {item["methodology_id"]: item for item in summary["top_methodologies"]}
        methods = await ctx.repository.list_methodologies(limit=5000, include_dead=True)
        method_map = {m.id: m for m in methods}

        table = Table(show_lines=True)
        table.add_column("Methodology", style="cyan", max_width=48)
        table.add_column("ID", width=8)
        table.add_column("Retrieved", justify="right")
        table.add_column("Used", justify="right")
        table.add_column("Success", justify="right")
        table.add_column("Expect", justify="right")
        table.add_column("Source", max_width=24)

        for methodology_id, item in list(by_methodology.items())[:12]:
            meth = method_map.get(methodology_id)
            source = "-"
            if meth is not None:
                source = next((tag.split(":", 1)[1] for tag in (meth.tags or []) if tag.startswith("source:")), "-")
            title = meth.problem_description if meth is not None else methodology_id
            table.add_row(
                title[:48],
                methodology_id[:8],
                str(item["retrieved_count"]),
                str(item["used_count"]),
                str(item["success_count"]),
                "-" if item.get("avg_expectation_match_score") is None else f"{float(item['avg_expectation_match_score']):.2f}",
                source,
            )

        console.print()
        console.print(table)
    finally:
        await ctx.close()


@app.command(hidden=True)
def quickstart(
    repo: str = typer.Argument(..., help="Path to the repository this goal is for"),
    title: str = typer.Option(..., "--title", "-t", prompt="Goal title", help="Short title for the goal"),
    description: str = typer.Option(
        ..., "--description", "-d", prompt="Goal description (what should be done?)",
        help="Detailed goal description",
    ),
    priority: str = typer.Option("high", "--priority", "-p", help="Priority: critical, high, medium, low"),
    task_type: str = typer.Option(
        "bug_fix",
        "--type",
        help="Task type: analysis, testing, documentation, security, refactoring, bug_fix, architecture, dependency_analysis",
    ),
    agent: Optional[str] = typer.Option(
        None,
        "--agent",
        "-a",
        help="Preferred agent: claude, codex, gemini, grok (or leave blank for auto-routing)",
    ),
    step: list[str] = typer.Option(
        [],
        "--step",
        help="Execution command to run for this goal (repeat --step for multiple commands)",
    ),
    check: list[str] = typer.Option(
        [],
        "--check",
        help="Acceptance check command for this goal (repeat --check for multiple commands)",
    ),
    preview: bool = typer.Option(
        True,
        "--preview/--no-preview",
        help="Show runbook and dry-run preview after creating the goal",
    ),
    execute: bool = typer.Option(
        False,
        "--execute",
        help="Immediately execute this exact task after setup",
    ),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Guided one-command setup: add goal + preview runbook (+ optional execution)."""
    _setup_logging(False)

    repo_path = Path(repo).resolve()
    if not repo_path.exists():
        console.print(f"[red]Repository path does not exist: {repo_path}[/red]")
        raise typer.Exit(1)

    asyncio.run(_quickstart_async(
        repo_path=repo_path,
        title=title,
        description=description,
        priority=priority.lower(),
        task_type=task_type,
        agent=agent,
        execution_steps=step,
        acceptance_checks=check,
        preview=preview,
        execute=execute,
        config_path=config,
    ))


async def _quickstart_async(
    repo_path: Path,
    title: str,
    description: str,
    priority: str,
    task_type: str,
    agent: Optional[str],
    execution_steps: list[str],
    acceptance_checks: list[str],
    repo_mode: str = "augment",
    namespace_safe_retry: bool = False,
    preview: bool = True,
    execute: bool = False,
    config_path: Optional[str] = None,
) -> None:
    from claw.core.factory import ClawFactory
    from claw.core.models import CycleResult, Project, Task, TaskStatus
    from claw.cycle import MicroClaw
    from claw.dispatcher import DEFAULT_AGENT, STATIC_ROUTING

    valid_priorities = {"critical": 10, "high": 8, "medium": 5, "low": 2}
    if priority not in valid_priorities:
        console.print(f"[red]Invalid priority '{priority}'. Use: critical, high, medium, low[/red]")
        raise typer.Exit(1)

    valid_types = [
        "analysis", "testing", "documentation", "security", "refactoring",
        "bug_fix", "architecture", "dependency_analysis",
    ]
    if task_type not in valid_types:
        console.print(f"[red]Invalid task type '{task_type}'. Use: {', '.join(valid_types)}[/red]")
        raise typer.Exit(1)

    if agent and agent not in ("claude", "codex", "gemini", "grok"):
        console.print(f"[red]Invalid agent '{agent}'. Use: claude, codex, gemini, grok[/red]")
        raise typer.Exit(1)

    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p, workspace_dir=repo_path)
    baseline_snapshot = _snapshot_repo_state(repo_path)

    try:
        project = await ctx.repository.get_project_by_name(repo_path.name)
        if project is None:
            project = Project(name=repo_path.name, repo_path=str(repo_path))
            await ctx.repository.create_project(project)

        recommended = agent or STATIC_ROUTING.get(task_type, DEFAULT_AGENT)
        task = Task(
            project_id=project.id,
            title=title,
            description=description,
            status=TaskStatus.PENDING,
            priority=valid_priorities[priority],
            task_type=task_type,
            recommended_agent=recommended,
            execution_steps=[s.strip() for s in execution_steps if s.strip()],
            acceptance_checks=[s.strip() for s in acceptance_checks if s.strip()],
        )
        await ctx.repository.create_task(task)

        console.print("\n[green]Quickstart goal created.[/green]")
        console.print(f"  Task ID: {task.id}")
        console.print(f"  Project: {project.name}")
        console.print(f"  Agent: {recommended}")
        console.print(f"  Priority: {priority} ({valid_priorities[priority]})")

        if preview:
            _display_runbook_details(task=task, project_name=project.name, action_template=None)
            _display_planned_tasks([task], title="Quickstart Preview")
            console.print("\n[yellow]Preview mode: no execution yet.[/yellow]")

        if execute:
            if not ctx.agents:
                console.print("\n[red]No agents available to execute. Enable at least one agent in claw.toml.[/red]")
                console.print("[dim]Run [bold]cam init[/bold] or [bold]cam doctor status[/bold] to diagnose.[/dim]")
                raise typer.Exit(code=1)

            selected_agent = ctx.agents.get(recommended)
            if selected_agent is not None and not _agent_supports_workspace_execution(selected_agent):
                console.print(
                    "\n[red]Selected agent cannot modify workspace files in its current mode.[/red]"
                )
                console.print(
                    f"[red]Agent '{recommended}' must run in CLI mode for quickstart/create execution.[/red]"
                )
                raise typer.Exit(code=1)

            console.print("\n[cyan]Executing quickstart task...[/cyan]")

            async def _execute_once(active_task: Task) -> tuple[Any, Any]:
                micro = MicroClaw(ctx=ctx, project_id=project.id)
                start = _time.monotonic()
                task_ctx = await micro.evaluate(active_task)
                decision = await micro.decide(task_ctx)
                verified = await micro._act_with_correction(decision)
                await micro.learn(verified)
                duration = _time.monotonic() - start

                agent_id, _, outcome, verification = verified
                outcome, verification, rolled_back = _enforce_quickstart_execution_guard(
                    repo_path=repo_path,
                    baseline_snapshot=baseline_snapshot,
                    outcome=outcome,
                    verification=verification,
                )
                if rolled_back:
                    console.print(
                        "\n[yellow]Quickstart safety rollback removed added files from the failed execution.[/yellow]"
                    )
                    for rel_path in rolled_back[:8]:
                        console.print(f"  - {rel_path}")
                cycle_result = CycleResult(
                    cycle_level="micro",
                    task_id=active_task.id,
                    project_id=project.id,
                    agent_id=agent_id,
                    outcome=outcome,
                    verification=verification,
                    success=verification.approved,
                    tokens_used=outcome.tokens_used,
                    cost_usd=outcome.cost_usd,
                    duration_seconds=duration,
                )
                _display_task_result(cycle_result)
                return outcome, verification

            outcome, verification = await _execute_once(task)
            should_retry_namespace_safe = (
                namespace_safe_retry
                and repo_mode == "fixed"
                and getattr(outcome, "failure_reason", "") == "new_source_namespace"
            )
            if should_retry_namespace_safe:
                console.print(
                    "\n[yellow]Namespace guard rejected the execution. Retrying once with namespace-safe fixed-mode constraints...[/yellow]"
                )
                baseline_namespaces = sorted(
                    _extract_source_namespaces_from_snapshot(baseline_snapshot)
                )
                namespace_clause = (
                    f"CRITICAL NAMESPACE CONSTRAINT (retry): "
                    f"Allowed top-level source namespaces: {baseline_namespaces}. "
                    f"You MUST NOT create any new top-level directories or package roots. "
                    f"All changes must be within the existing namespace(s): {baseline_namespaces}."
                )
                retry_description = namespace_clause + "\n\n" + description
                namespace_acceptance = (
                    f"No new top-level namespaces beyond: {baseline_namespaces}"
                )
                retry_checks = [namespace_acceptance] + [
                    s.strip() for s in acceptance_checks if s.strip()
                ]
                retry_task = Task(
                    project_id=project.id,
                    title=f"{title} (namespace-safe retry)",
                    description=retry_description,
                    status=TaskStatus.PENDING,
                    priority=valid_priorities[priority],
                    task_type=task_type,
                    recommended_agent=recommended,
                    execution_steps=[s.strip() for s in execution_steps if s.strip()],
                    acceptance_checks=retry_checks,
                )
                await ctx.repository.create_task(retry_task)
                console.print(f"[dim]Retry task created: {retry_task.id}[/dim]")
                await _execute_once(retry_task)
        else:
            console.print("\n[dim]Run `cam quickstart ... --execute` when you're ready to run it.[/dim]")

    finally:
        await ctx.close()


@app.command()
def preflight(
    repo: str = typer.Argument(..., help="Target repository path to scope, fix, augment, or create"),
    request: str = typer.Option(..., "--request", "-r", prompt="What should CAM preflight?", help="Plain-language task request"),
    repo_mode: str = typer.Option("augment", "--repo-mode", help="Repo mode: fixed, augment, new"),
    spec: list[str] = typer.Option([], "--spec", help="Requirement/spec line (repeatable)"),
    check: list[str] = typer.Option([], "--check", help="Acceptance check / validation rule (repeatable)"),
    answer: list[str] = typer.Option([], "--answer", help="Operator answer to a preflight clarification item (repeatable)"),
    preflight_file: Optional[str] = typer.Option(None, "--preflight-file", help="Reuse a prior preflight artifact and its recorded answers"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Preferred agent/model family for live preflight"),
    live: bool = typer.Option(False, "--live/--no-live", help="Use an LLM to enrich the preflight artifact"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Pre-examine a requested task, ask clarifying questions, and estimate time/budget."""
    _setup_logging(False)

    repo_path = Path(repo).resolve()
    if repo_mode not in ("fixed", "augment", "new"):
        console.print("[red]--repo-mode must be one of: fixed, augment, new[/red]")
        raise typer.Exit(1)

    if repo_mode != "new" and not repo_path.exists():
        console.print(f"[red]Repository path does not exist: {repo_path}[/red]")
        raise typer.Exit(1)

    if repo_mode == "new":
        repo_path.mkdir(parents=True, exist_ok=True)

    prior_report = _load_preflight_artifact(preflight_file)
    report, _ = asyncio.run(_run_preflight_async(
        repo_path=repo_path,
        request=request,
        repo_mode=repo_mode,
        spec_items=[s.strip() for s in spec if s.strip()],
        acceptance_checks=[c.strip() for c in check if c.strip()],
        answers=[a.strip() for a in answer if a.strip()],
        prior_report=prior_report,
        preferred_agent=agent,
        config_path=config,
        live=live,
    ))
    _display_preflight_report(report)


@app.command()
def create(
    repo: str = typer.Argument(..., help="Target repository path to fix, augment, or create"),
    request: str = typer.Option(..., "--request", "-r", prompt="What should CAM create?", help="Plain-language outcome request"),
    repo_mode: str = typer.Option("augment", "--repo-mode", help="Repo mode: fixed, augment, new"),
    title: Optional[str] = typer.Option(None, "--title", "-t", help="Optional short task title"),
    priority: str = typer.Option("high", "--priority", "-p", help="Priority: critical, high, medium, low"),
    task_type: str = typer.Option("architecture", "--type", help="Task type for routing and execution"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Preferred agent override"),
    spec: list[str] = typer.Option([], "--spec", help="Initial requirement/spec line (repeatable)"),
    step: list[str] = typer.Option([], "--step", help="Suggested execution step (repeatable)"),
    check: list[str] = typer.Option([], "--check", help="Acceptance check / validation rule (repeatable)"),
    answer: list[str] = typer.Option([], "--answer", help="Operator answer to a preflight clarification item (repeatable)"),
    preflight_file: Optional[str] = typer.Option(None, "--preflight-file", help="Reuse a prior preflight artifact and its recorded answers"),
    preflight: bool = typer.Option(False, "--preflight/--no-preflight", help="Force structured task preflight before creating the task"),
    auto_preflight: bool = typer.Option(True, "--auto-preflight/--no-auto-preflight", help="Automatically run preflight for risky or ambiguous create tasks"),
    preflight_live: bool = typer.Option(False, "--preflight-live/--no-preflight-live", help="Use an LLM to enrich the create preflight"),
    accept_preflight_defaults: bool = typer.Option(False, "--accept-preflight-defaults", help="Allow execution to continue using CAM's stated defaults even if must-clarify questions remain"),
    namespace_safe_retry: bool = typer.Option(
        True,
        "--namespace-safe-retry/--no-namespace-safe-retry",
        help="When fixed-mode execution is rejected for a new source namespace, auto-run one namespace-safe retry.",
    ),
    preview: bool = typer.Option(True, "--preview/--no-preview", help="Preview runbook after creating the task"),
    execute: bool = typer.Option(False, "--execute", help="Immediately execute the created task"),
    max_minutes: int = typer.Option(20, "--max-minutes", help="Wall-clock time guardrail for creation/execution"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Create a fixed repo, augmented repo, or new repo from a requested outcome."""
    _setup_logging(False)

    repo_path = Path(repo).resolve()
    if repo_mode not in ("fixed", "augment", "new"):
        console.print("[red]--repo-mode must be one of: fixed, augment, new[/red]")
        raise typer.Exit(1)

    if repo_mode == "new":
        repo_path.mkdir(parents=True, exist_ok=True)
    elif not repo_path.exists():
        console.print(f"[red]Repository path does not exist: {repo_path}[/red]")
        raise typer.Exit(1)

    if max_minutes < 1:
        console.print("[red]--max-minutes must be at least 1[/red]")
        raise typer.Exit(1)

    task_title = title or request.strip().split("\n")[0][:80]

    try:
        asyncio.run(asyncio.wait_for(
            _create_async(
                repo_path=repo_path,
                request=request,
                repo_mode=repo_mode,
                title=task_title,
                priority=priority.lower(),
                task_type=task_type,
                agent=agent,
                spec_items=spec,
                execution_steps=step,
                acceptance_checks=check,
                answers=answer,
                preflight_file=preflight_file,
                preflight=preflight,
                auto_preflight=auto_preflight,
                preflight_live=preflight_live,
                accept_preflight_defaults=accept_preflight_defaults,
                namespace_safe_retry=namespace_safe_retry,
                preview=preview,
                execute=execute,
                config_path=config,
            ),
            timeout=max_minutes * 60,
        ))
    except TimeoutError:
        console.print(f"[red]Create timed out after {max_minutes} minute(s)[/red]")
        raise typer.Exit(124)


async def _create_async(
    repo_path: Path,
    request: str,
    repo_mode: str,
    title: str,
    priority: str,
    task_type: str,
    agent: Optional[str],
    spec_items: list[str],
    execution_steps: list[str],
    acceptance_checks: list[str],
    answers: list[str],
    preflight_file: Optional[str],
    preflight: bool,
    auto_preflight: bool,
    preflight_live: bool,
    accept_preflight_defaults: bool,
    preview: bool,
    execute: bool,
    config_path: Optional[str],
    namespace_safe_retry: bool = True,
) -> None:
    preflight_report: Optional[dict[str, Any]] = None
    prior_report = _load_preflight_artifact(preflight_file)
    run_preflight = preflight or (
        auto_preflight and _should_auto_preflight(
            request=request,
            repo_mode=repo_mode,
            spec_items=[s.strip() for s in spec_items if s.strip()],
            acceptance_checks=[c.strip() for c in acceptance_checks if c.strip()],
            execute=execute,
        )
    )
    if run_preflight:
        preflight_report, _ = await _run_preflight_async(
            repo_path=repo_path,
            request=request,
            repo_mode=repo_mode,
            spec_items=[s.strip() for s in spec_items if s.strip()],
            acceptance_checks=[c.strip() for c in acceptance_checks if c.strip()],
            answers=[a.strip() for a in answers if a.strip()],
            prior_report=prior_report,
            preferred_agent=agent,
            config_path=config_path,
            live=preflight_live,
        )
        if not preflight:
            console.print(
                "\n[dim]Auto-preflight triggered because the create request looks risky, ambiguous, or expensive.[/dim]"
            )
        _display_preflight_report(preflight_report)
        must_questions = [
            q for q in (preflight_report.get("clarifying_questions", []) or [])
            if q.get("priority") == "must"
        ]
        if execute and preflight_report.get("hard_blockers"):
            console.print(
                "\n[red]Preflight found hard blockers.[/red]"
            )
            console.print(
                "[red]Resolve the blockers first, or rerun create without --execute if you only want the spec/task created.[/red]"
            )
            raise typer.Exit(2)
        if execute and must_questions and not accept_preflight_defaults:
            console.print(
                "\n[red]Preflight found unresolved must-clarify questions.[/red]"
            )
            console.print(
                "[red]Execution is blocked until you answer them or rerun with --accept-preflight-defaults to explicitly accept CAM's stated defaults.[/red]"
            )
            raise typer.Exit(2)
        if execute and must_questions and accept_preflight_defaults:
            console.print(
                "\n[yellow]Proceeding with execution using CAM's preflight defaults for unresolved must-clarify questions.[/yellow]"
            )

    spec_payload = _build_create_spec(
        repo_path=repo_path,
        request=request,
        repo_mode=repo_mode,
        title=title,
        task_type=task_type,
        execution_steps=[s.strip() for s in execution_steps if s.strip()],
        acceptance_checks=[c.strip() for c in acceptance_checks if c.strip()],
        spec_items=[s.strip() for s in spec_items if s.strip()],
        preflight_report=preflight_report,
    )
    spec_path = _write_create_spec(spec_payload)
    description = _build_create_description(
        request=request,
        repo_mode=repo_mode,
        spec_path=spec_path,
        spec_items=spec_payload["spec_items"],
    )
    if preflight_report and preflight_report.get("artifact_path"):
        description = description + (
            f"\n\nPreflight artifact: {preflight_report['artifact_path']}\n"
            f"Preflight recommended mode: {preflight_report.get('recommended_mode', '')}"
        )

    console.print("\n[bold]CAM Create[/bold]")
    console.print(f"  Repo: {repo_path}")
    console.print(f"  Mode: {repo_mode}")
    console.print(f"  Spec file: {spec_path}")
    console.print("  Purpose: convert CAM memory + your request into an executable creation task")

    await _quickstart_async(
        repo_path=repo_path,
        title=title,
        description=description,
        priority=priority,
        task_type=task_type,
        agent=agent,
        execution_steps=spec_payload["execution_steps"],
        acceptance_checks=spec_payload["acceptance_checks"],
        repo_mode=repo_mode,
        namespace_safe_retry=namespace_safe_retry,
        preview=preview,
        execute=execute,
        config_path=config_path,
    )
    console.print("\n[dim]Next: run `cam validate --spec-file "
                  f"{spec_path}` then `cam benchmark`.[/dim]")


@app.command(name="add-goal", hidden=True)
def add_goal(
    repo: str = typer.Argument(..., help="Path to the repository this goal is for"),
    title: str = typer.Option(..., "--title", "-t", prompt="Goal title", help="Short title for the goal"),
    description: str = typer.Option(
        ..., "--description", "-d", prompt="Goal description (what should the agent do?)",
        help="Detailed description of what should be accomplished",
    ),
    priority: str = typer.Option(
        "medium", "--priority", "-p",
        help="Priority: critical, high, medium, low",
    ),
    task_type: str = typer.Option(
        "analysis", "--type",
        help="Task type: analysis, testing, documentation, security, refactoring, bug_fix, architecture, dependency_analysis",
    ),
    agent: Optional[str] = typer.Option(
        None, "--agent", "-a",
        help="Preferred agent: claude, codex, gemini, grok (or leave blank for auto-routing)",
    ),
    step: list[str] = typer.Option(
        [],
        "--step",
        help="Execution command to run for this goal (repeat --step for multiple commands)",
    ),
    check: list[str] = typer.Option(
        [],
        "--check",
        help="Acceptance check command for this goal (repeat --check for multiple commands)",
    ),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Add a custom goal/task for a repository.

    Creates a task that will be picked up by `claw enhance` on the next run.
    """
    _setup_logging(False)

    repo_path = Path(repo).resolve()
    if not repo_path.exists():
        console.print(f"[red]Repository path does not exist: {repo_path}[/red]")
        raise typer.Exit(1)

    valid_priorities = {"critical": 10, "high": 8, "medium": 5, "low": 2}
    if priority.lower() not in valid_priorities:
        console.print(f"[red]Invalid priority '{priority}'. Use: critical, high, medium, low[/red]")
        raise typer.Exit(1)

    valid_types = [
        "analysis", "testing", "documentation", "security", "refactoring",
        "bug_fix", "architecture", "dependency_analysis",
    ]
    if task_type not in valid_types:
        console.print(f"[red]Invalid task type '{task_type}'. Use: {', '.join(valid_types)}[/red]")
        raise typer.Exit(1)

    if agent and agent not in ("claude", "codex", "gemini", "grok"):
        console.print(f"[red]Invalid agent '{agent}'. Use: claude, codex, gemini, grok[/red]")
        raise typer.Exit(1)

    asyncio.run(_add_goal_async(
        repo_path,
        title,
        description,
        priority.lower(),
        task_type,
        agent,
        step,
        check,
        config,
    ))


async def _add_goal_async(
    repo_path: Path,
    title: str,
    description: str,
    priority: str,
    task_type: str,
    agent: Optional[str],
    execution_steps: list[str],
    acceptance_checks: list[str],
    config_path: Optional[str],
) -> None:
    from claw.core.factory import ClawFactory
    from claw.core.models import Project, Task, TaskStatus
    from claw.dispatcher import DEFAULT_AGENT, STATIC_ROUTING

    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p, workspace_dir=repo_path)

    priority_map = {"critical": 10, "high": 8, "medium": 5, "low": 2}

    try:
        # Find or create project for this repo
        project = await ctx.repository.get_project_by_name(repo_path.name)
        if project is None:
            project = Project(name=repo_path.name, repo_path=str(repo_path))
            await ctx.repository.create_project(project)
            console.print(f"  Created new project: {project.name} ({project.id})")

        # Determine recommended agent
        recommended = agent or STATIC_ROUTING.get(task_type, DEFAULT_AGENT)

        task = Task(
            project_id=project.id,
            title=title,
            description=description,
            status=TaskStatus.PENDING,
            priority=priority_map[priority],
            task_type=task_type,
            recommended_agent=recommended,
            execution_steps=[s.strip() for s in execution_steps if s.strip()],
            acceptance_checks=[s.strip() for s in acceptance_checks if s.strip()],
        )
        await ctx.repository.create_task(task)

        console.print(f"\n[green]Goal added successfully![/green]")
        console.print(f"  Title: {title}")
        console.print(f"  Project: {project.name}")
        console.print(f"  Priority: {priority} ({priority_map[priority]})")
        console.print(f"  Type: {task_type}")
        console.print(f"  Agent: {recommended}")
        if task.execution_steps:
            console.print(f"  Steps: {len(task.execution_steps)}")
        if task.acceptance_checks:
            console.print(f"  Checks: {len(task.acceptance_checks)}")
        console.print(f"  Task ID: {task.id}")
        console.print(f"\nRun [bold]cam enhance {repo_path}[/bold] to execute this goal.")

    finally:
        await ctx.close()


@app.command()
def ideate(
    directory: str = typer.Argument(..., help="Path to directory containing candidate repos"),
    focus: str = typer.Option("", "--focus", "-f", help="What kind of app should CAM invent?"),
    ideas: int = typer.Option(3, "--ideas", min=1, max=8, help="How many app concepts to generate"),
    max_repos: int = typer.Option(4, "--max-repos", help="Maximum repos to use as ideation inputs"),
    depth: int = typer.Option(3, "--depth", "-d", help="Max directory depth for repo discovery"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Preferred ideation agent: claude, codex, gemini, grok"),
    promote: int = typer.Option(0, "--promote", help="Promote idea N into a real cam create task/spec"),
    target_repo: Optional[str] = typer.Option(None, "--target-repo", help="Target repo path for promoted idea"),
    repo_mode: str = typer.Option("new", "--repo-mode", help="Repo mode for promoted idea: fixed, augment, new"),
    max_minutes: int = typer.Option(10, "--max-minutes", help="Wall-clock time guardrail for ideation"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Generate novel app concepts from CAM memory plus candidate repos."""
    _setup_logging(False)
    from claw.core.config import load_config

    dir_path = Path(directory).resolve()
    if not dir_path.exists():
        console.print(f"[red]Directory does not exist: {dir_path}[/red]")
        raise typer.Exit(1)

    if agent and agent not in ("claude", "codex", "gemini", "grok"):
        console.print(f"[red]Invalid agent '{agent}'. Use: claude, codex, gemini, grok[/red]")
        raise typer.Exit(1)

    if repo_mode not in ("fixed", "augment", "new"):
        console.print("[red]--repo-mode must be one of: fixed, augment, new[/red]")
        raise typer.Exit(1)

    if promote < 0:
        console.print("[red]--promote must be 0 or a 1-based idea index[/red]")
        raise typer.Exit(1)

    if max_minutes < 1:
        console.print("[red]--max-minutes must be at least 1[/red]")
        raise typer.Exit(1)

    cfg = load_config(Path(config) if config else None)
    _fail_if_missing_api_keys(cfg, "ideate")

    try:
        asyncio.run(asyncio.wait_for(
            _ideate_async(
                dir_path=dir_path,
                focus=focus.strip(),
                idea_count=ideas,
                max_repos=max_repos,
                depth=depth,
                preferred_agent=agent,
                promote_index=promote,
                target_repo=Path(target_repo).resolve() if target_repo else None,
                repo_mode=repo_mode,
                config_path=config,
            ),
            timeout=max_minutes * 60,
        ))
    except TimeoutError:
        console.print(f"[red]Ideation timed out after {max_minutes} minute(s)[/red]")
        raise typer.Exit(124)


@app.command(name="keycheck", hidden=True)
def keycheck(
    for_command: str = typer.Option("mine", "--for", help="Command to preflight: mine, ideate"),
    live: bool = typer.Option(False, "--live", help="Also validate the keys with a tiny real provider call"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Quick API-key preflight before running a live command."""
    _setup_logging(False)
    normalized = for_command.strip().lower()
    if normalized not in {"mine", "ideate"}:
        console.print("[red]--for must be one of: mine, ideate[/red]")
        raise typer.Exit(1)

    from claw.core.config import load_config

    cfg = load_config(Path(config) if config else None)
    missing = _print_api_key_check(cfg, normalized)
    if missing:
        console.print("\n[yellow]Set the missing keys before starting live work.[/yellow]")
        for key_name in missing:
            console.print(f"  export {key_name}=your-key-here")
        raise typer.Exit(1)

    if not live:
        console.print("\n[green]Preflight passed.[/green]")
        return

    _fail_if_live_key_checks_fail(cfg, normalized)
    console.print("\n[green]Live preflight passed.[/green]")


async def _ideate_async(
    dir_path: Path,
    focus: str,
    idea_count: int,
    max_repos: int,
    depth: int,
    preferred_agent: Optional[str],
    promote_index: int,
    target_repo: Optional[Path],
    repo_mode: str,
    config_path: Optional[str],
) -> None:
    from claw.core.factory import ClawFactory
    from claw.core.models import Project, Task, TaskStatus
    from claw.dispatcher import DEFAULT_AGENT, STATIC_ROUTING
    from claw.llm.client import LLMMessage
    from claw.miner import _dedup_iterations, _discover_repos

    candidates = _discover_repos(dir_path, max_depth=depth)
    if not candidates:
        console.print("[yellow]No repositories or source trees found for ideation.[/yellow]")
        return

    candidates, _ = _dedup_iterations(candidates)
    selected = candidates[:max_repos]

    workspace_dir = target_repo if target_repo else ROOT_DIR
    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p, workspace_dir=workspace_dir)

    try:
        model = _select_ideation_model(ctx.config, preferred_agent)

        repo_contexts = [_summarize_repo_tree(candidate.path) for candidate in selected]
        repo_findings: dict[str, list[dict[str, Any]]] = {}
        for candidate in selected:
            existing = await ctx.repository.get_methodologies_by_tag(f"source:{candidate.name}", limit=6)
            repo_findings[candidate.name] = [_summarize_methodology(m) for m in existing[:6]]

        high_potential = await ctx.repository.get_high_potential_methodologies(limit=8, min_potential=0.35)
        most_novel = await ctx.repository.get_most_novel_methodologies(limit=8, min_novelty=0.35)
        action_templates = await ctx.repository.list_action_templates(limit=8)
        cam_memory = {
            "high_potential": [_summarize_methodology(m) for m in high_potential],
            "most_novel": [_summarize_methodology(m) for m in most_novel],
            "action_templates": [
                {
                    "title": t.title,
                    "pattern": t.problem_pattern[:220],
                    "source_repo": t.source_repo,
                    "confidence": t.confidence,
                }
                for t in action_templates
            ],
        }

        prompt = _build_ideation_prompt(
            focus=focus,
            repo_contexts=repo_contexts,
            repo_findings=repo_findings,
            cam_memory=cam_memory,
            idea_count=idea_count,
        )

        payload = await ctx.llm_client.complete_json(
            messages=[LLMMessage(role="user", content=prompt)],
            model=model,
            temperature=0.4,
        )
        normalized_ideas = _normalize_ideation_payload(payload, idea_count)
        if not normalized_ideas:
            console.print("[red]Ideation returned no usable ideas.[/red]")
            raise typer.Exit(1)

        json_path, md_path = _write_ideation_artifacts(
            source_dir=dir_path,
            focus=focus,
            ideas=normalized_ideas,
            raw_payload=payload,
        )

        console.print("\n[bold]CAM Ideation[/bold]")
        console.print(f"  Source directory: {dir_path}")
        console.print(f"  Repos used: {len(selected)}")
        console.print(f"  Model: {model}")
        console.print(f"  JSON: {json_path}")
        console.print(f"  Markdown: {md_path}")

        table = Table(title="Novel App Concepts")
        table.add_column("#", justify="right", width=3)
        table.add_column("Title", style="cyan", max_width=28)
        table.add_column("Tagline", style="green", max_width=34)
        table.add_column("Repos", style="magenta", max_width=24)
        table.add_column("Confidence", justify="right", style="yellow", width=10)
        for idx, idea in enumerate(normalized_ideas, start=1):
            table.add_row(
                str(idx),
                idea["title"],
                idea["tagline"] or idea["problem"][:60],
                ", ".join(idea["repos_used"][:3]),
                f"{idea['build_confidence']:.2f}",
            )
        console.print(table)

        if promote_index:
            if promote_index < 1 or promote_index > len(normalized_ideas):
                console.print(f"[red]--promote must be between 1 and {len(normalized_ideas)}[/red]")
                raise typer.Exit(1)
            if target_repo is None:
                console.print("[red]--target-repo is required when using --promote[/red]")
                raise typer.Exit(1)

            chosen = normalized_ideas[promote_index - 1]
            if repo_mode == "new":
                target_repo.mkdir(parents=True, exist_ok=True)
            elif not target_repo.exists():
                console.print(f"[red]Target repo does not exist: {target_repo}[/red]")
                raise typer.Exit(1)

            spec_payload = _build_create_spec(
                repo_path=target_repo,
                request=chosen["app_request"],
                repo_mode=repo_mode,
                title=chosen["title"],
                task_type="architecture",
                execution_steps=chosen["execution_steps"],
                acceptance_checks=chosen["acceptance_checks"],
                spec_items=chosen["spec_items"],
            )
            spec_path = _write_create_spec(spec_payload)
            description = _build_create_description(
                request=chosen["app_request"],
                repo_mode=repo_mode,
                spec_path=spec_path,
                spec_items=chosen["spec_items"],
            )

            project = await ctx.repository.get_project_by_name(target_repo.name)
            if project is None:
                project = Project(name=target_repo.name, repo_path=str(target_repo))
                await ctx.repository.create_project(project)

            recommended = STATIC_ROUTING.get("architecture", DEFAULT_AGENT)
            task = Task(
                project_id=project.id,
                title=chosen["title"][:200],
                description=description,
                status=TaskStatus.PENDING,
                priority=8,
                task_type="architecture",
                recommended_agent=recommended,
                execution_steps=chosen["execution_steps"],
                acceptance_checks=chosen["acceptance_checks"],
            )
            await ctx.repository.create_task(task)

            console.print("\n[green]Promoted idea into a create task.[/green]")
            console.print(f"  Idea: {chosen['title']}")
            console.print(f"  Target repo: {target_repo}")
            console.print(f"  Spec file: {spec_path}")
            console.print(f"  Task ID: {task.id}")
            console.print(f"\n[dim]Next: run `cam runbook {task.id}` or `cam enhance {target_repo}`.[/dim]")

    finally:
        await ctx.close()


@app.command(name="premine")
def premine(
    target: str = typer.Argument(..., help="GitHub URL, owner/repo, or a file containing repo URLs"),
    output_format: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format: table, json, or markdown",
    ),
    out: Optional[Path] = typer.Option(None, "--out", help="Write JSON results to this path"),
    report: Optional[Path] = typer.Option(None, "--report", help="Write a Markdown report to this path"),
    save_candidates: Optional[Path] = typer.Option(
        None,
        "--save-candidates",
        help="Append JSONL candidate records for later CAM mining",
    ),
) -> None:
    """Assess GitHub repos remotely before deciding whether to clone and CAM-mine them."""
    fmt = output_format.lower().strip()
    if fmt not in {"table", "json", "markdown"}:
        console.print("[red]--format must be one of: table, json, markdown[/red]")
        raise typer.Exit(1)

    try:
        targets = read_targets(target)
        if not targets:
            console.print("[red]No GitHub targets found.[/red]")
            raise typer.Exit(1)
        results = [premine_url(repo_url) for repo_url in targets]
    except Exception as exc:
        console.print(f"[red]CAM-preMine failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    json_payload = results_to_json(results)
    markdown_report = render_markdown_report(results)

    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json_payload + "\n", encoding="utf-8")
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(markdown_report, encoding="utf-8")
    if save_candidates:
        append_candidate_jsonl(save_candidates, results)

    if fmt == "json":
        typer.echo(json_payload)
    elif fmt == "markdown":
        typer.echo(markdown_report)
    else:
        _render_premine_table(results)


def _render_premine_table(results: list[PreMineResult]) -> None:
    table = Table(title="CAM-preMine Remote GitHub Triage", show_lines=False)
    table.add_column("Repo", style="cyan")
    table.add_column("Verdict", style="bold", no_wrap=True)
    table.add_column("Score", justify="right")
    table.add_column("Type")
    table.add_column("Risk")
    table.add_column("Next Step")

    for result in results:
        table.add_row(
            result.repo,
            result.verdict.value,
            str(result.cam_value_score),
            result.repo_type.value,
            result.risk_gate.value,
            result.recommended_next_step,
        )

    console.print(table)


@app.command()
def mine(
    directory: str = typer.Argument(..., help="Path to directory containing repos to mine"),
    target: str = typer.Option(".", "--target", "-t", help="Target project path (defaults to current directory)"),
    max_repos: int = typer.Option(10, "--max-repos", help="Maximum number of repos to mine"),
    min_relevance: float = typer.Option(0.6, "--min-relevance", help="Minimum relevance score for task generation (0.4-1.0)"),
    tasks: bool = typer.Option(True, "--tasks/--no-tasks", help="Generate enhancement tasks from findings"),
    depth: int = typer.Option(6, "--depth", "-d", help="Max directory depth for repo discovery"),
    dedup: bool = typer.Option(True, "--dedup/--no-dedup", help="Dedup repo iterations by canonical name"),
    skip_known: bool = typer.Option(True, "--skip-known/--no-skip-known", help="Skip repos already mined when unchanged"),
    force_rescan: bool = typer.Option(False, "--force-rescan", help="Ignore the mining ledger and rescan selected repos"),
    changed_only: bool = typer.Option(False, "--changed-only", help="Only show/mine repos that are new or changed according to the mining ledger"),
    scan_only: bool = typer.Option(False, "--scan-only", help="Preview discovered repos without mining (no LLM calls)"),
    live_keycheck: bool = typer.Option(True, "--live-keycheck/--no-live-keycheck", help="Validate required provider keys with tiny real calls before live mining"),
    max_minutes: int = typer.Option(15, "--max-minutes", help="Wall-clock time guardrail for mining"),
    yield_sort: bool = typer.Option(True, "--yield-sort/--no-yield-sort", help="Sort candidates by expected yield before mining (default: on)"),
    self_assess: bool = typer.Option(False, "--self-assess", help="After mining, classify findings as DUPLICATE/PARTIAL_GAP/NOVEL vs existing CAM knowledge"),
    brain: Optional[str] = typer.Option(None, "--brain", "-b", help="Mining brain: auto (default), python, typescript, go, rust, misc"),
    suggest: bool = typer.Option(False, "--suggest", help="Show repos ranked by gap-filling potential instead of mining"),
    fast: bool = typer.Option(False, "--fast", help="Fast-mine: defer LLM assimilation, store findings as embryonic. Run `cam enrich` after."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Mine local repositories for patterns, features, and ideas.

    Scans a directory for git repos, analyzes each via LLM to extract
    transferable patterns, stores findings in semantic memory, and
    optionally generates enhancement tasks for the target project.

    Use --scan-only to preview what repos would be mined without making
    any LLM calls. Use --no-dedup to include all iterations of each project.
    Use --no-yield-sort to mine in alphabetical order instead of by expected yield.
    Use --self-assess to classify findings against existing knowledge after mining.
    Use --brain to force a specific language brain (auto-detects by default).
    Use --suggest to rank repos by gap-filling potential (no mining, no LLM calls).
    """
    _setup_logging(verbose)

    dir_path = _resolve_operator_path(directory)
    if not dir_path.exists():
        console.print(f"[red]Directory does not exist: {dir_path}[/red]")
        raise typer.Exit(1)
    if not dir_path.is_dir():
        console.print(f"[red]Path is not a directory: {dir_path}[/red]")
        raise typer.Exit(1)

    if max_repos < 1:
        console.print("[red]--max-repos must be at least 1[/red]")
        raise typer.Exit(1)

    if not (0.4 <= min_relevance <= 1.0):
        console.print("[red]--min-relevance must be between 0.4 and 1.0[/red]")
        raise typer.Exit(1)

    if depth < 1:
        console.print("[red]--depth must be at least 1[/red]")
        raise typer.Exit(1)

    if max_minutes < 1:
        console.print("[red]--max-minutes must be at least 1[/red]")
        raise typer.Exit(1)

    # Validate --brain flag
    from claw.miner import VALID_BRAIN_NAMES
    brain_value = brain.lower().strip() if brain else None
    if brain_value == "auto":
        brain_value = None
    if brain_value is not None and brain_value not in VALID_BRAIN_NAMES:
        console.print(
            f"[red]Invalid brain '{brain_value}'. "
            f"Valid options: auto, {', '.join(sorted(VALID_BRAIN_NAMES))}[/red]"
        )
        raise typer.Exit(1)

    if scan_only:
        _mine_scan_only(dir_path, depth, dedup, max_repos, config, skip_known, force_rescan, changed_only)
        return

    if suggest:
        _mine_suggest(dir_path, depth, dedup, max_repos, config, skip_known, force_rescan, changed_only)
        return

    from claw.core.config import load_config

    cfg = load_config(Path(config) if config else None)
    _fail_if_missing_api_keys(cfg, "mine")
    if live_keycheck:
        _fail_if_live_key_checks_fail(cfg, "mine")

    try:
        asyncio.run(asyncio.wait_for(
            _mine_async(
                dir_path, target, max_repos, min_relevance, tasks, config,
                depth, dedup, skip_known, force_rescan, changed_only,
                yield_sort=yield_sort,
                self_assess=self_assess,
                brain=brain_value,
                fast=fast,
            ),
            timeout=max_minutes * 60,
        ))
    except TimeoutError:
        console.print(f"[red]Mining timed out after {max_minutes} minute(s)[/red]")
        raise typer.Exit(124)


@app.command(name="mine-report", hidden=True)
def mine_report(
    directory: str = typer.Argument(..., help="Path to directory containing repos to inspect"),
    depth: int = typer.Option(6, "--depth", "-d", help="Max directory depth for repo discovery"),
    dedup: bool = typer.Option(True, "--dedup/--no-dedup", help="Dedup repo iterations by canonical name"),
    changed_only: bool = typer.Option(False, "--changed-only", help="Only show repos that are new or changed"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Show repo mining status from the persistent mining ledger."""
    _setup_logging(False)

    dir_path = _resolve_operator_path(directory)
    if not dir_path.exists():
        console.print(f"[red]Directory does not exist: {dir_path}[/red]")
        raise typer.Exit(1)
    if not dir_path.is_dir():
        console.print(f"[red]Path is not a directory: {dir_path}[/red]")
        raise typer.Exit(1)

    from claw.core.config import load_config
    from claw.miner import RepoScanLedger, _default_scan_ledger_path, _discover_repos, _dedup_iterations

    cfg = load_config(Path(config) if config else None)
    ledger = RepoScanLedger(_default_scan_ledger_path(cfg))
    candidates = _discover_repos(dir_path, max_depth=depth, config=cfg)
    skipped: list = []
    selected = candidates
    if dedup:
        selected, skipped = _dedup_iterations(candidates)

    console.print(f"\n[bold]CAM Mine Report[/bold]")
    console.print(f"  Directory: {dir_path}")
    console.print(f"  Depth: {depth}")
    console.print(f"  Dedup: {dedup}")
    console.print(f"  Changed only: {changed_only}")
    console.print(f"  Ledger: {ledger.path}")

    table = Table(title=f"Mining Status ({len(selected)} selected)")
    table.add_column("#", justify="right", style="dim", width=4)
    table.add_column("Name", style="cyan", max_width=30)
    table.add_column("Kind", style="magenta", width=11)
    table.add_column("Status", style="green", max_width=18)
    table.add_column("Last Mined", style="dim", width=18)
    table.add_column("Findings", justify="right", style="yellow", width=8)
    table.add_column("Tokens", justify="right", style="yellow", width=8)

    unchanged = 0
    changed = 0
    new = 0
    rows_added = 0
    for idx, candidate in enumerate(selected, start=1):
        should_mine, reason = ledger.should_mine(candidate, skip_known=True, force_rescan=False)
        record = ledger.get_record(candidate.path)
        if not should_mine:
            status = "unchanged"
            unchanged += 1
        elif reason == "changed":
            status = "changed"
            changed += 1
        else:
            status = "new"
            new += 1

        if changed_only and status == "unchanged":
            continue

        last_mined = "-"
        findings = "-"
        tokens = "-"
        if record is not None:
            from datetime import datetime
            last_mined = datetime.fromtimestamp(record.last_mined_at).strftime("%Y-%m-%d %H:%M")
            findings = str(record.findings_count)
            tokens = str(record.tokens_used)

        table.add_row(
            str(idx),
            candidate.name,
            candidate.source_kind,
            status,
            last_mined,
            findings,
            tokens,
        )
        rows_added += 1

    if rows_added:
        console.print(table)
    else:
        console.print("[yellow]No repos matched the requested report filters.[/yellow]")

    console.print(f"\n[bold]Summary[/bold]")
    console.print(f"  Total discovered: {len(candidates)}")
    console.print(f"  Selected after dedup: {len(selected)}")
    console.print(f"  New: {new}")
    console.print(f"  Changed: {changed}")
    console.print(f"  Unchanged: {unchanged}")
    console.print(f"  Dedup skipped: {len(skipped)}")


def _mine_scan_only(
    dir_path: Path,
    depth: int,
    dedup: bool,
    max_repos: int,
    config_path: Optional[str],
    skip_known: bool,
    force_rescan: bool,
    changed_only: bool,
) -> None:
    """Preview discovered repos without mining (no LLM calls, no DB)."""
    from datetime import datetime
    from claw.core.config import load_config
    from claw.miner import RepoScanLedger, _default_scan_ledger_path, _discover_repos, _dedup_iterations

    console.print(f"\n[bold]CLAW Repo Scanner (scan-only)[/bold]")
    console.print(f"  Directory: {dir_path}")
    console.print(f"  Depth: {depth}")
    console.print(f"  Dedup: {dedup}")
    console.print(f"  Skip unchanged repos: {skip_known}")
    console.print(f"  Force rescan: {force_rescan}")
    console.print(f"  Changed only: {changed_only}")
    console.print()

    console.print("[cyan]Scanning for repos...[/cyan]")
    cfg = load_config(Path(config_path) if config_path else None)
    candidates = _discover_repos(dir_path, max_depth=depth, config=cfg)
    ledger = RepoScanLedger(_default_scan_ledger_path(cfg))

    if not candidates:
        console.print("[yellow]No repositories or source trees found.[/yellow]")
        return

    skipped: list = []
    selected = candidates
    if dedup:
        selected, skipped = _dedup_iterations(candidates)

    effective_candidates = selected
    if changed_only:
        effective_candidates = [
            c for c in selected
            if ledger.should_mine(c, skip_known=skip_known, force_rescan=force_rescan)[0]
        ]

    # Build discovery table
    table = Table(title=f"Discovered Repos ({len(candidates)} total, {len(effective_candidates)} eligible)")
    table.add_column("#", justify="right", style="dim", width=4)
    table.add_column("Name", style="cyan", max_width=30)
    table.add_column("Canonical", style="blue", max_width=25)
    table.add_column("Files", justify="right", style="green", width=6)
    table.add_column("Size", justify="right", style="dim", width=8)
    table.add_column("Last Modified", style="dim", width=18)
    table.add_column("Depth", justify="right", style="dim", width=5)
    table.add_column("Kind", style="magenta", width=11)
    table.add_column("Status", max_width=20)

    skipped_names = {id(s[0]) for s in skipped}
    ledger_selected = 0

    for i, c in enumerate(candidates, 1):
        if c.total_bytes >= 1024 * 1024:
            size_str = f"{c.total_bytes / (1024 * 1024):.1f}MB"
        elif c.total_bytes >= 1024:
            size_str = f"{c.total_bytes / 1024:.0f}KB"
        else:
            size_str = f"{c.total_bytes}B"

        if c.last_commit_ts > 0:
            ts_str = datetime.fromtimestamp(c.last_commit_ts).strftime("%Y-%m-%d %H:%M")
        else:
            ts_str = "-"

        ledger_should_mine, ledger_reason = ledger.should_mine(
            c,
            skip_known=skip_known,
            force_rescan=force_rescan,
        )

        if id(c) in skipped_names:
            reason = next(r for s, r in skipped if id(s) == id(c))
            status = f"[dim]skipped: {reason[:18]}[/dim]"
        elif not ledger_should_mine:
            status = "[yellow]already mined[/yellow]"
        elif ledger_reason == "changed":
            ledger_selected += 1
            status = "[green]changed -> rescan[/green]"
        elif ledger_reason == "forced":
            ledger_selected += 1
            status = "[green]force rescan[/green]"
        else:
            ledger_selected += 1
            status = "[green]selected[/green]"

        if changed_only and (id(c) in skipped_names or not ledger_should_mine):
            continue

        table.add_row(
            str(i), c.name, c.canonical_name, str(c.file_count),
            size_str, ts_str, str(c.depth), c.source_kind, status,
        )

    console.print(table)

    # Summary
    console.print(f"\n[bold]Summary[/bold]")
    console.print(f"  Total discovered: {len(candidates)}")
    console.print(f"  Eligible after filters: {len(effective_candidates)}")
    console.print(f"  Skipped (dedup): {len(skipped)}")
    if max_repos < ledger_selected:
        console.print(f"  Will mine (--max-repos): {max_repos}")
    else:
        console.print(f"  Will mine: {ledger_selected}")

    # Show dedup groups with multiple iterations
    if dedup and skipped:
        from collections import Counter
        canon_counts = Counter(c.canonical_name for c in candidates)
        multi = {name: count for name, count in canon_counts.items() if count > 1}
        if multi:
            console.print(f"\n[bold]Iteration Groups ({len(multi)} with duplicates)[/bold]")
            group_table = Table()
            group_table.add_column("Canonical Name", style="blue", max_width=30)
            group_table.add_column("Iterations", justify="right", style="yellow", width=10)
            group_table.add_column("Selected", style="green", max_width=35)
            for name, count in sorted(multi.items(), key=lambda x: -x[1])[:20]:
                winner = next((c.name for c in selected if c.canonical_name == name), "?")
                group_table.add_row(name, str(count), winner)
            console.print(group_table)

    console.print(f"\n[dim]Remove --scan-only to mine these repos.[/dim]")


def _mine_suggest(
    dir_path: Path,
    depth: int,
    dedup: bool,
    max_repos: int,
    config_path: Optional[str],
    skip_known: bool,
    force_rescan: bool,
    changed_only: bool,
) -> None:
    """Rank repos by gap-filling potential using the coverage matrix."""
    from claw.core.config import load_config
    from claw.miner import (
        RepoScanLedger, _default_scan_ledger_path, _discover_repos,
        _dedup_iterations, detect_repo_language,
    )

    cfg = load_config(Path(config_path) if config_path else None)

    if not cfg.gap_analyzer.enabled or not cfg.instances.enabled:
        console.print("[yellow]Gap analyzer requires [gap_analyzer] enabled=true and [instances] enabled=true[/yellow]")
        raise typer.Exit(1)

    console.print(f"\n[bold]CAM Mine Suggest (gap-aware repo ranking)[/bold]")
    console.print(f"  Directory: {dir_path}")
    console.print()

    # Discover repos
    candidates = _discover_repos(dir_path, max_depth=depth, config=cfg)
    if dedup:
        candidates, _ = _dedup_iterations(candidates)

    ledger = RepoScanLedger(_default_scan_ledger_path(cfg))
    if skip_known:
        candidates = [
            c for c in candidates
            if ledger.should_mine(c, skip_known=skip_known, force_rescan=force_rescan)[0]
        ]

    if not candidates:
        console.print("[yellow]No unmined repos found.[/yellow]")
        return

    # Compute coverage matrix
    async def _run():
        from claw.db.engine import DatabaseEngine
        from claw.db.repository import Repository
        from claw.community.gap_analyzer import GapAnalyzer

        engine = DatabaseEngine(cfg.database)
        await engine.connect()
        await engine.apply_migrations()
        repo = Repository(engine)
        primary_db = str(Path(cfg.database.db_path).resolve())
        analyzer = GapAnalyzer(repo, cfg.instances, primary_db, cfg.gap_analyzer)

        try:
            coverage = await analyzer.compute_coverage_matrix()
        finally:
            await engine.close()

        # Score each candidate
        scored: list[tuple[Any, float, str]] = []
        for c in candidates:
            lang = detect_repo_language(c.path)
            domain_info = {"language": lang, "categories": []}
            score = analyzer.score_repo_for_gaps(c.name, domain_info, coverage)
            scored.append((c, score, lang))

        scored.sort(key=lambda x: x[1], reverse=True)

        # Display
        table = Table(title=f"Repos Ranked by Gap-Filling Potential ({len(scored)} candidates)")
        table.add_column("#", justify="right", style="dim", width=4)
        table.add_column("Name", style="cyan", max_width=30)
        table.add_column("Language", style="magenta", width=12)
        table.add_column("Gap Score", justify="right", style="yellow", width=10)
        table.add_column("Path", style="dim", max_width=40)

        for i, (c, score, lang) in enumerate(scored[:max_repos], 1):
            score_style = "green" if score > 0.3 else "yellow" if score > 0 else "dim"
            table.add_row(
                str(i), c.name, lang or "?",
                f"[{score_style}]{score:.3f}[/{score_style}]",
                str(c.path)[:40],
            )

        console.print(table)

        # Coverage summary
        sparse = coverage.sparse_cells + coverage.empty_cells
        if sparse:
            console.print(f"\n[bold]Sparse/empty cells ({len(sparse)}):[/bold]")
            for cat, brain in sorted(sparse)[:15]:
                count = coverage.matrix.get(cat, {}).get(brain, 0)
                style = "red" if count == 0 else "yellow"
                console.print(f"  [{style}]{cat} / {brain}: {count}[/{style}]")
            if len(sparse) > 15:
                console.print(f"  [dim]... and {len(sparse) - 15} more[/dim]")

    asyncio.run(_run())


async def _mine_async(
    dir_path: Path,
    target: str,
    max_repos: int,
    min_relevance: float,
    generate_tasks: bool,
    config_path: Optional[str],
    max_depth: int = 6,
    dedup_iterations: bool = True,
    skip_known: bool = True,
    force_rescan: bool = False,
    changed_only: bool = False,
    yield_sort: bool = True,
    self_assess: bool = False,
    brain: Optional[str] = None,
    fast: bool = False,
) -> None:
    from claw.core.factory import ClawFactory
    from claw.core.models import Project

    config_p = Path(config_path) if config_path else None
    target_path = Path(target).resolve()
    ctx = await ClawFactory.create(config_path=config_p, workspace_dir=target_path)

    try:
        # Get or create target project
        project_name = target_path.name
        project = await ctx.repository.get_project_by_name(project_name)
        if project is None:
            project = Project(name=project_name, repo_path=str(target_path))
            project = await ctx.repository.create_project(project)

        console.print(f"\n[bold]CLAW Repo Mining[/bold]")
        console.print(f"  Directory: {dir_path}")
        console.print(f"  Target: {project.name} ({target_path})")
        console.print(f"  Max repos: {max_repos}")
        console.print(f"  Min relevance for tasks: {min_relevance}")
        console.print(f"  Generate tasks: {generate_tasks}")
        console.print(f"  Depth: {max_depth}")
        console.print(f"  Dedup: {dedup_iterations}")
        console.print(f"  Skip unchanged repos: {skip_known}")
        console.print(f"  Force rescan: {force_rescan}")
        console.print(f"  Changed only: {changed_only}")
        console.print(f"  Yield sort: {yield_sort}")
        console.print(f"  Fast mine: {fast}")
        console.print(f"  Database: {ctx.config.database.db_path}")
        console.print()

        # Progress callback
        def on_repo_complete(repo_name: str, result: Any) -> None:
            n_findings = len(result.findings) if result.findings else 0
            if result.error:
                console.print(f"  [red]x {repo_name}: {result.error}[/red]")
            elif result.skipped:
                console.print(f"  [yellow]- {repo_name}: skipped ({result.skip_reason})[/yellow]")
            else:
                console.print(
                    f"  [green]+ {repo_name}[/green]: "
                    f"{n_findings} findings, {result.files_analyzed} files, "
                    f"{result.tokens_used} tokens, {result.duration_seconds:.1f}s"
                )

        console.print("[cyan]Mining repositories...[/cyan]")
        if brain:
            console.print(f"  Brain override: [bold]{brain}[/bold]")

        report = await ctx.miner.mine_directory(
            base_path=dir_path,
            target_project_id=project.id,
            max_repos=max_repos,
            min_relevance=min_relevance,
            generate_tasks=generate_tasks,
            on_repo_complete=on_repo_complete,
            max_depth=max_depth,
            dedup_iterations=dedup_iterations,
            skip_known=skip_known or changed_only,
            force_rescan=force_rescan,
            yield_sort=yield_sort,
            brain=brain,
            fast=fast,
        )

        # Display results table
        console.print()
        results_table = Table(title="Mining Results")
        results_table.add_column("Repo", style="cyan", max_width=25)
        results_table.add_column("Files", justify="right", style="dim", width=6)
        results_table.add_column("Findings", justify="right", style="green", width=9)
        results_table.add_column("Tokens", justify="right", style="yellow", width=8)
        results_table.add_column("Time", justify="right", style="dim", width=8)
        results_table.add_column("Status", max_width=20)

        for result in report.repo_results:
            if result.skipped:
                status = f"[yellow]skipped: {result.skip_reason}[/yellow]"
            else:
                status = "[green]OK[/green]" if not result.error else f"[red]{result.error[:18]}[/red]"
            results_table.add_row(
                result.repo_name,
                str(result.files_analyzed),
                str(len(result.findings)),
                str(result.tokens_used),
                f"{result.duration_seconds:.1f}s",
                status,
            )

        console.print(results_table)

        # Summary
        console.print(f"\n[bold]Summary[/bold]")
        console.print(f"  Repos scanned: {report.repos_scanned}")
        console.print(f"  Repos skipped: {report.repos_skipped}")
        console.print(f"  Total findings: {report.total_findings}")
        console.print(f"  Tasks generated: {report.tasks_generated}")
        console.print(f"  Total tokens: {report.total_tokens}")
        console.print(f"  Total time: {report.total_duration_seconds:.1f}s")

        if report.tasks:
            console.print(f"\n[bold]Generated Tasks[/bold]")
            task_table = Table()
            task_table.add_column("Title", style="cyan", max_width=60)
            task_table.add_column("Priority", justify="right", style="yellow", width=8)
            task_table.add_column("Type", style="dim", width=16)
            task_table.add_column("Agent", style="green", width=8)

            for task in report.tasks:
                task_table.add_row(
                    task.title[:58],
                    str(task.priority),
                    task.task_type or "-",
                    task.recommended_agent or "-",
                )

            console.print(task_table)

        if fast and report.total_findings > 0:
            console.print(
                f"\n[yellow bold]{report.total_findings} findings stored as embryonic (fast-mine).[/yellow bold]"
            )
            console.print("[yellow]Run `cam enrich` to complete LLM assimilation.[/yellow]")
        else:
            console.print(f"\n[dim]Use 'claw results' to view tasks, 'claw enhance .' to work on them.[/dim]")

        # Self-assessment: classify findings vs existing knowledge
        if self_assess and report.total_findings > 0:
            console.print(f"\n[bold]Self-Assessment: classifying {report.total_findings} findings against existing knowledge[/bold]")
            from claw.miner import assess_findings_against_existing
            assessments = await assess_findings_against_existing(
                report=report,
                embedding_engine=ctx.embeddings,
                repository=ctx.repository,
                semantic_memory=ctx.semantic_memory,
            )
            if assessments:
                assess_table = Table(title="Finding Classification")
                assess_table.add_column("Finding", style="cyan", max_width=50)
                assess_table.add_column("Class", width=14)
                assess_table.add_column("Sim", justify="right", width=5)
                assess_table.add_column("Closest Match", style="dim", max_width=45)

                novel_count = 0
                partial_count = 0
                dup_count = 0
                for a in assessments:
                    if a["classification"] == "NOVEL":
                        cls_style = "[green]NOVEL[/green]"
                        novel_count += 1
                    elif a["classification"] == "PARTIAL_GAP":
                        cls_style = "[yellow]PARTIAL_GAP[/yellow]"
                        partial_count += 1
                    else:
                        cls_style = "[dim]DUPLICATE[/dim]"
                        dup_count += 1
                    assess_table.add_row(
                        a["title"][:48],
                        cls_style,
                        f"{a['similarity']:.2f}",
                        a.get("closest_match", "-")[:43],
                    )

                console.print(assess_table)
                console.print(
                    f"\n  [green]{novel_count} novel[/green], "
                    f"[yellow]{partial_count} partial gaps[/yellow], "
                    f"[dim]{dup_count} duplicates[/dim]"
                )
            else:
                console.print("[dim]  No findings to assess.[/dim]")

    finally:
        await ctx.close()


@app.command(name="mine-workspace")
def mine_workspace(
    directories: list[str] = typer.Argument(..., help="One or more directory paths to scan for repos"),
    target: str = typer.Option(".", "--target", "-t", help="Target project path (defaults to current directory)"),
    max_repos: int = typer.Option(20, "--max-repos", help="Maximum number of repos to mine across all directories"),
    min_relevance: float = typer.Option(0.6, "--min-relevance", help="Minimum relevance score for task generation (0.4-1.0)"),
    tasks: bool = typer.Option(True, "--tasks/--no-tasks", help="Generate enhancement tasks from findings"),
    depth: int = typer.Option(8, "--depth", "-d", help="Max directory depth for repo discovery"),
    dedup: bool = typer.Option(True, "--dedup/--no-dedup", help="Dedup repo iterations by canonical name"),
    skip_known: bool = typer.Option(True, "--skip-known/--no-skip-known", help="Skip repos already mined when unchanged"),
    force_rescan: bool = typer.Option(False, "--force-rescan", help="Ignore the mining ledger and rescan selected repos"),
    changed_only: bool = typer.Option(False, "--changed-only", help="Only show/mine repos that are new or changed"),
    scan_only: bool = typer.Option(False, "--scan-only", help="Preview discovered repos without mining (no LLM calls)"),
    live_keycheck: bool = typer.Option(True, "--live-keycheck/--no-live-keycheck", help="Validate required provider keys"),
    max_minutes: int = typer.Option(30, "--max-minutes", help="Wall-clock time guardrail for mining"),
    yield_sort: bool = typer.Option(True, "--yield-sort/--no-yield-sort", help="Sort candidates by expected yield before mining (default: on)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Mine repos across multiple directories at once.

    Scans several directories for git repos and source trees, deduplicates
    across all paths (handles symlinks and overlapping roots), and mines
    each unique repo. Higher default depth (8) and max-repos (20) than
    single-directory mining.

    Examples:
        cam mine-workspace /Volumes/Projects /Volumes/Archive --scan-only
        cam mine-workspace ~/code ~/experiments --depth 4 --max-repos 10
    """
    _setup_logging(verbose)

    # Validate all directories
    dir_paths: list[Path] = []
    for d in directories:
        p = _resolve_operator_path(d)
        if not p.exists():
            console.print(f"[red]Directory does not exist: {p}[/red]")
            raise typer.Exit(1)
        if not p.is_dir():
            console.print(f"[red]Path is not a directory: {p}[/red]")
            raise typer.Exit(1)
        dir_paths.append(p)

    if max_repos < 1:
        console.print("[red]--max-repos must be at least 1[/red]")
        raise typer.Exit(1)
    if not (0.4 <= min_relevance <= 1.0):
        console.print("[red]--min-relevance must be between 0.4 and 1.0[/red]")
        raise typer.Exit(1)
    if depth < 1:
        console.print("[red]--depth must be at least 1[/red]")
        raise typer.Exit(1)
    if max_minutes < 1:
        console.print("[red]--max-minutes must be at least 1[/red]")
        raise typer.Exit(1)

    if scan_only:
        _mine_workspace_scan_only(dir_paths, depth, dedup, max_repos, config, skip_known, force_rescan, changed_only)
        return

    from claw.core.config import load_config

    cfg = load_config(Path(config) if config else None)
    _fail_if_missing_api_keys(cfg, "mine-workspace")
    if live_keycheck:
        _fail_if_live_key_checks_fail(cfg, "mine-workspace")

    try:
        asyncio.run(asyncio.wait_for(
            _mine_workspace_async(
                dir_paths, target, max_repos, min_relevance, tasks, config,
                depth, dedup, skip_known, force_rescan, changed_only,
                yield_sort=yield_sort,
            ),
            timeout=max_minutes * 60,
        ))
    except TimeoutError:
        console.print(f"[red]Mining timed out after {max_minutes} minute(s)[/red]")
        raise typer.Exit(124)


@app.command(name="mine-all")
def mine_all(
    directory: str = typer.Argument(..., help="Root directory containing repos to mine"),
    batch_size: int = typer.Option(10, "--batch-size", "-b", help="Repos per mining batch"),
    depth: int = typer.Option(8, "--depth", "-d", help="Max directory depth for repo discovery"),
    skip_known: bool = typer.Option(True, "--skip-known/--no-skip-known", help="Skip repos already mined when unchanged"),
    force_rescan: bool = typer.Option(False, "--force-rescan", help="Ignore mining ledger and rescan all repos"),
    max_repos: int = typer.Option(200, "--max-repos", help="Maximum total repos to mine"),
    max_minutes: int = typer.Option(60, "--max-minutes", help="Wall-clock time guardrail"),
    live_keycheck: bool = typer.Option(True, "--live-keycheck/--no-live-keycheck", help="Validate required provider keys"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Smart bulk mining with 5-phase pipeline: scan -> preview -> schema -> mine -> report.

    Phase 1 SCAN: discover repos, classify by domain, check ledger (free, no tokens)
    Phase 2 PREVIEW: Rich table with stats, user gate (free)
    Phase 3 SCHEMA: suggest domain ganglia for clusters >= 5 repos (free)
    Phase 4 MINE: batched mining with live progress, checkpointing (tokens spent)
    Phase 5 REPORT: before/after coverage delta, top discoveries, cost summary

    Examples:
        cam mine-all /Volumes/WS4TB/repo412sn --batch-size 10 -v
        cam mine-all ~/projects --max-repos 50 --depth 4
    """
    _setup_logging(verbose)

    dir_path = _resolve_operator_path(directory)
    if not dir_path.exists() or not dir_path.is_dir():
        console.print(f"[red]Directory does not exist: {dir_path}[/red]")
        raise typer.Exit(1)

    from claw.core.config import load_config

    cfg = load_config(Path(config) if config else None)
    _fail_if_missing_api_keys(cfg, "mine-all")
    if live_keycheck:
        _fail_if_live_key_checks_fail(cfg, "mine-all")

    try:
        asyncio.run(asyncio.wait_for(
            _mine_all_async(
                dir_path, batch_size, depth, skip_known, force_rescan,
                max_repos, config,
            ),
            timeout=max_minutes * 60,
        ))
    except TimeoutError:
        console.print(f"[red]Mining timed out after {max_minutes} minute(s)[/red]")
        raise typer.Exit(124)


async def _mine_all_async(
    base_dir: Path,
    batch_size: int,
    max_depth: int,
    skip_known: bool,
    force_rescan: bool,
    max_repos: int,
    config_path: Optional[str],
) -> None:
    """5-phase bulk mining pipeline."""
    from claw.core.factory import ClawFactory
    from claw.miner import (
        RepoScanLedger,
        _discover_repos,
        classify_repo_domain,
        RepoProfile,
    )

    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p)

    try:
        ledger_path = Path(ctx.config.database.db_path).parent / "mining_ledger.json"
        ledger = RepoScanLedger(ledger_path)

        # ── PHASE 1: SCAN ─────────────────────────────────────────
        console.print("\n[bold]Phase 1: SCAN[/bold] — Discovering repos...")
        candidates = _discover_repos(base_dir, max_depth=max_depth, config=ctx.config)
        console.print(f"  Found [cyan]{len(candidates)}[/cyan] repos under {base_dir}")

        # Classify + profile each candidate
        profiles: list[RepoProfile] = []
        for cand in candidates:
            should_mine, reason = ledger.should_mine(
                cand, skip_known=skip_known, force_rescan=force_rescan,
            )

            # Read README for domain classification
            readme_text = ""
            for readme_name in ("README.md", "readme.md", "README.rst", "README"):
                readme_path = cand.path / readme_name
                if readme_path.exists():
                    try:
                        readme_text = readme_path.read_text(encoding="utf-8", errors="ignore")[:4000]
                    except (OSError, UnicodeDecodeError):
                        pass
                    break

            domain = classify_repo_domain(cand.path, readme_text)

            # Simple yield score: file count * recency * gap bonus
            recency_bonus = 1.0 if cand.last_commit_ts > (_time.time() - 365 * 86400) else 0.5
            yield_score = min(1.0, (cand.file_count / 100) * recency_bonus)

            profile = RepoProfile(
                candidate=cand,
                application_domain=domain,
                yield_score=yield_score,
                ledger_status="unchanged" if not should_mine else reason,
            )
            profiles.append(profile)

        # Filter to mineable repos
        mineable = [p for p in profiles if p.ledger_status not in ("unchanged", "content-duplicate")]
        mineable.sort(key=lambda p: p.yield_score, reverse=True)
        mineable = mineable[:max_repos]

        console.print(
            f"  Mineable: [green]{len(mineable)}[/green]  |  "
            f"Skipped (unchanged): [yellow]{len(profiles) - len(mineable)}[/yellow]"
        )

        if not mineable:
            console.print("\n[yellow]No new or changed repos to mine.[/yellow]")
            return

        # ── PHASE 2: PREVIEW ───────────────────────────────────────
        console.print("\n[bold]Phase 2: PREVIEW[/bold]")
        table = Table(show_lines=True, title="Repos to Mine")
        table.add_column("#", width=3, justify="right")
        table.add_column("Repo", style="cyan", max_width=40)
        table.add_column("Domain", width=14)
        table.add_column("Files", justify="right", width=6)
        table.add_column("Size", justify="right", width=8)
        table.add_column("Yield", justify="right", width=6)
        table.add_column("Status", width=10)

        for i, p in enumerate(mineable[:50], 1):
            size = f"{p.candidate.total_bytes / 1024:.0f}KB" if p.candidate.total_bytes < 1024 * 1024 else f"{p.candidate.total_bytes / (1024 * 1024):.1f}MB"
            table.add_row(
                str(i),
                p.candidate.name,
                p.application_domain,
                str(p.candidate.file_count),
                size,
                f"{p.yield_score:.2f}",
                p.ledger_status,
            )

        console.print(table)

        # ── PHASE 3: SCHEMA ────────────────────────────────────────
        console.print("\n[bold]Phase 3: SCHEMA[/bold] — Domain ganglion suggestions")
        domain_counts: dict[str, int] = {}
        for p in mineable:
            domain_counts[p.application_domain] = domain_counts.get(p.application_domain, 0) + 1

        suggested_ganglia: list[str] = []
        for domain, count in sorted(domain_counts.items(), key=lambda x: -x[1]):
            marker = ""
            if count >= 5 and domain != "general":
                suggested_ganglia.append(domain)
                marker = " [green](ganglion suggested)[/green]"
            console.print(f"  {domain}: {count} repos{marker}")

        # ── PHASE 4: MINE ──────────────────────────────────────────
        console.print(f"\n[bold]Phase 4: MINE[/bold] — Mining {len(mineable)} repos in batches of {batch_size}")

        total_findings = 0
        total_tokens = 0
        total_cost = 0.0
        mined_count = 0
        errors: list[str] = []

        for batch_start in range(0, len(mineable), batch_size):
            batch = mineable[batch_start:batch_start + batch_size]
            batch_end = batch_start + len(batch)
            console.print(
                f"\n  [bold]Batch {batch_start // batch_size + 1}[/bold] "
                f"(repos {batch_start + 1}-{batch_end} of {len(mineable)})"
            )

            for p in batch:
                cand = p.candidate
                try:
                    console.print(f"    Mining {cand.name}...", end=" ")

                    # Use brain hint for domain if a domain ganglion exists
                    brain_hint = None
                    if p.application_domain in suggested_ganglia:
                        brain_hint = f"domain-{p.application_domain}"

                    result = await ctx.miner.mine_repo(
                        repo_path=str(cand.path),
                        repo_name=cand.name,
                        target_project_id=None,
                        brain=brain_hint,
                    )

                    findings = result.findings_count if hasattr(result, "findings_count") else len(getattr(result, "findings", []))
                    tokens = result.total_tokens if hasattr(result, "total_tokens") else 0
                    cost = result.cost_usd if hasattr(result, "cost_usd") else 0.0

                    total_findings += findings
                    total_tokens += tokens
                    total_cost += cost
                    mined_count += 1

                    # Record in ledger
                    ledger.record_result(cand, result)

                    console.print(f"[green]{findings} findings[/green] ({tokens:,} tokens)")

                except Exception as e:
                    error_msg = f"{cand.name}: {e}"
                    errors.append(error_msg)
                    console.print(f"[red]FAILED: {e}[/red]")
                    logger.warning("Mining failed for %s: %s", cand.name, e)

        # ── PHASE 5: REPORT ────────────────────────────────────────
        console.print(f"\n[bold]Phase 5: REPORT[/bold]")
        console.print(f"  Repos mined: [green]{mined_count}[/green] / {len(mineable)}")
        console.print(f"  Total findings: [cyan]{total_findings}[/cyan]")
        console.print(f"  Total tokens: [yellow]{total_tokens:,}[/yellow]")
        if total_cost > 0:
            console.print(f"  Estimated cost: ${total_cost:.4f}")

        if errors:
            console.print(f"\n  [red]Errors ({len(errors)}):[/red]")
            for err in errors[:10]:
                console.print(f"    - {err}")

        if suggested_ganglia:
            console.print(f"\n  Domain ganglia suggested: {', '.join(suggested_ganglia)}")

        # Post-mining methodology count
        total_methodologies = await ctx.repository.count_methodologies()
        console.print(f"\n  Total knowledge base: [bold]{total_methodologies}[/bold] methodologies")

    finally:
        await ctx.close()


def _mine_workspace_scan_only(
    dir_paths: list[Path],
    depth: int,
    dedup: bool,
    max_repos: int,
    config_path: Optional[str],
    skip_known: bool,
    force_rescan: bool,
    changed_only: bool,
) -> None:
    """Preview repos discovered across multiple directories (no LLM calls)."""
    from datetime import datetime
    from claw.core.config import load_config
    from claw.miner import RepoScanLedger, _default_scan_ledger_path, _discover_repos, _dedup_iterations

    console.print(f"\n[bold]CAM Workspace Scanner (scan-only)[/bold]")
    console.print(f"  Directories: {len(dir_paths)}")
    for p in dir_paths:
        console.print(f"    - {p}")
    console.print(f"  Depth: {depth}")
    console.print(f"  Dedup: {dedup}")
    console.print(f"  Skip unchanged: {skip_known}")
    console.print(f"  Force rescan: {force_rescan}")
    console.print(f"  Changed only: {changed_only}")
    console.print()

    # Discover repos from each directory and merge
    console.print("[cyan]Scanning directories for repos...[/cyan]")
    cfg = load_config()
    all_candidates: list = []
    source_map: dict[str, str] = {}  # resolved path -> scan root name
    seen_resolved: set[str] = set()

    for dir_path in dir_paths:
        candidates = _discover_repos(dir_path, max_depth=depth, config=cfg)
        for c in candidates:
            try:
                resolved = str(c.path.resolve())
            except OSError:
                resolved = str(c.path)
            if resolved not in seen_resolved:
                seen_resolved.add(resolved)
                all_candidates.append(c)
                source_map[resolved] = dir_path.name

    if not all_candidates:
        console.print("[yellow]No repositories or source trees found in any directory.[/yellow]")
        return

    cfg = load_config(Path(config_path) if config_path else None)
    ledger = RepoScanLedger(_default_scan_ledger_path(cfg))

    skipped: list = []
    selected = all_candidates
    if dedup:
        selected, skipped = _dedup_iterations(all_candidates)

    effective = selected
    if changed_only:
        effective = [
            c for c in selected
            if ledger.should_mine(c, skip_known=skip_known, force_rescan=force_rescan)[0]
        ]

    table = Table(title=f"Workspace Repos ({len(all_candidates)} total, {len(effective)} eligible)")
    table.add_column("#", justify="right", style="dim", width=4)
    table.add_column("Name", style="cyan", max_width=30)
    table.add_column("Source", style="blue", max_width=20)
    table.add_column("Files", justify="right", style="green", width=6)
    table.add_column("Size", justify="right", style="dim", width=8)
    table.add_column("Kind", style="magenta", width=11)
    table.add_column("Status", max_width=20)

    skipped_ids = {id(s[0]) for s in skipped}
    ledger_selected = 0

    for i, c in enumerate(all_candidates, 1):
        if c.total_bytes >= 1024 * 1024:
            size_str = f"{c.total_bytes / (1024 * 1024):.1f}MB"
        elif c.total_bytes >= 1024:
            size_str = f"{c.total_bytes / 1024:.0f}KB"
        else:
            size_str = f"{c.total_bytes}B"

        try:
            resolved = str(c.path.resolve())
        except OSError:
            resolved = str(c.path)
        src = source_map.get(resolved, "?")

        ledger_should_mine, ledger_reason = ledger.should_mine(
            c, skip_known=skip_known, force_rescan=force_rescan,
        )

        if id(c) in skipped_ids:
            reason = next(r for s, r in skipped if id(s) == id(c))
            status = f"[dim]skipped: {reason[:18]}[/dim]"
        elif not ledger_should_mine:
            status = "[yellow]already mined[/yellow]"
        elif ledger_reason == "changed":
            ledger_selected += 1
            status = "[green]changed -> rescan[/green]"
        elif ledger_reason == "forced":
            ledger_selected += 1
            status = "[green]force rescan[/green]"
        else:
            ledger_selected += 1
            status = "[green]selected[/green]"

        if changed_only and (id(c) in skipped_ids or not ledger_should_mine):
            continue

        table.add_row(str(i), c.name, src, str(c.file_count), size_str, c.source_kind, status)

    console.print(table)

    console.print(f"\n[bold]Summary[/bold]")
    console.print(f"  Directories scanned: {len(dir_paths)}")
    console.print(f"  Total discovered: {len(all_candidates)}")
    console.print(f"  Eligible after filters: {len(effective)}")
    console.print(f"  Skipped (dedup): {len(skipped)}")
    console.print(f"  Cross-path duplicates removed: {sum(len(_discover_repos(p, max_depth=depth, config=cfg)) for p in dir_paths) - len(all_candidates)}")
    if max_repos < ledger_selected:
        console.print(f"  Will mine (--max-repos): {max_repos}")
    else:
        console.print(f"  Will mine: {ledger_selected}")

    console.print(f"\n[dim]Remove --scan-only to mine these repos.[/dim]")


async def _mine_workspace_async(
    dir_paths: list[Path],
    target: str,
    max_repos: int,
    min_relevance: float,
    generate_tasks: bool,
    config_path: Optional[str],
    max_depth: int = 8,
    dedup_iterations: bool = True,
    skip_known: bool = True,
    force_rescan: bool = False,
    changed_only: bool = False,
    yield_sort: bool = True,
) -> None:
    """Mine repos across multiple directories."""
    from claw.core.factory import ClawFactory
    from claw.core.models import Project
    from claw.miner import _discover_repos, _dedup_iterations, _score_yield_priority, MiningReport, RepoMiningResult

    config_p = Path(config_path) if config_path else None
    target_path = Path(target).resolve()
    ctx = await ClawFactory.create(config_path=config_p, workspace_dir=target_path)

    try:
        project_name = target_path.name
        project = await ctx.repository.get_project_by_name(project_name)
        if project is None:
            project = Project(name=project_name, repo_path=str(target_path))
            project = await ctx.repository.create_project(project)

        # Discover + merge + dedup across all directories
        all_candidates: list = []
        seen_resolved: set[str] = set()
        for dir_path in dir_paths:
            candidates = _discover_repos(dir_path, max_depth=max_depth, config=ctx.config)
            for c in candidates:
                try:
                    resolved = str(c.path.resolve())
                except OSError:
                    resolved = str(c.path)
                if resolved not in seen_resolved:
                    seen_resolved.add(resolved)
                    all_candidates.append(c)

        if not all_candidates:
            console.print("[yellow]No repos found in any directory.[/yellow]")
            return

        skipped_dedup: list = []
        selected = all_candidates
        if dedup_iterations:
            selected, skipped_dedup = _dedup_iterations(all_candidates)

        # Apply ledger filtering
        mining_plan: list = []
        for candidate in selected:
            should_mine, reason = ctx.miner.scan_ledger.should_mine(
                candidate, skip_known=skip_known or changed_only, force_rescan=force_rescan,
            )
            if should_mine:
                mining_plan.append(candidate)

        # Sort by expected yield before selecting top-N
        if yield_sort and mining_plan:
            mining_plan.sort(
                key=lambda c: _score_yield_priority(c, ctx.miner.scan_ledger),
                reverse=True,
            )
            import time as _time
            _log = logging.getLogger("claw.cli")
            for cand in mining_plan[:min(5, len(mining_plan))]:
                s = _score_yield_priority(cand, ctx.miner.scan_ledger)
                age = (_time.time() - cand.last_commit_ts) / 86400 if cand.last_commit_ts > 0 else -1
                _log.info(
                    "Yield-priority: %s score=%.1f (files=%d, kind=%s, age=%.0fd)",
                    cand.name, s, cand.file_count, cand.source_kind, age,
                )

        to_mine = mining_plan[:max_repos]

        console.print(f"\n[bold]CAM Workspace Mining[/bold]")
        console.print(f"  Directories: {len(dir_paths)}")
        for p in dir_paths:
            console.print(f"    - {p}")
        console.print(f"  Target: {project.name} ({target_path})")
        console.print(f"  Total discovered: {len(all_candidates)}")
        console.print(f"  Selected after dedup: {len(selected)}")
        console.print(f"  Eligible after ledger: {len(mining_plan)}")
        console.print(f"  Will mine: {len(to_mine)}")
        console.print()

        if not to_mine:
            console.print("[yellow]No new or changed repos to mine.[/yellow]")
            return

        report = MiningReport()

        def on_repo_complete(repo_name: str, result: Any) -> None:
            n_findings = len(result.findings) if result.findings else 0
            if result.error:
                console.print(f"  [red]x {repo_name}: {result.error}[/red]")
            elif result.skipped:
                console.print(f"  [yellow]- {repo_name}: skipped ({result.skip_reason})[/yellow]")
            else:
                console.print(
                    f"  [green]+ {repo_name}[/green]: "
                    f"{n_findings} findings, {result.files_analyzed} files, "
                    f"{result.tokens_used} tokens, {result.duration_seconds:.1f}s"
                )

        console.print("[cyan]Mining repositories...[/cyan]")
        import time
        start = time.monotonic()

        for candidate in to_mine:
            try:
                result = await ctx.miner.mine_repo(candidate.path, candidate.name, project.id)
                report.repo_results.append(result)
                report.repos_scanned += 1
                report.total_findings += len(result.findings)
                report.total_cost_usd += result.cost_usd
                report.total_tokens += result.tokens_used
                if not result.error and not result.skipped:
                    ctx.miner.scan_ledger.record_result(candidate, result)
                on_repo_complete(candidate.name, result)
            except Exception as e:
                err_result = RepoMiningResult(
                    repo_name=candidate.name, repo_path=str(candidate.path), error=str(e),
                )
                report.repo_results.append(err_result)
                report.repos_scanned += 1
                on_repo_complete(candidate.name, err_result)

        # Generate tasks from all findings
        if generate_tasks:
            all_findings = []
            for result in report.repo_results:
                all_findings.extend(result.findings)
            if all_findings:
                tasks = await ctx.miner._generate_tasks(
                    all_findings, project.id, min_relevance,
                )
                report.tasks = tasks
                report.tasks_generated = len(tasks)

        report.total_duration_seconds = time.monotonic() - start

        # Display results
        results_table = Table(title="Workspace Mining Results")
        results_table.add_column("Repo", style="cyan", max_width=25)
        results_table.add_column("Files", justify="right", style="dim", width=6)
        results_table.add_column("Findings", justify="right", style="green", width=9)
        results_table.add_column("Tokens", justify="right", style="yellow", width=8)
        results_table.add_column("Time", justify="right", style="dim", width=8)
        results_table.add_column("Status", max_width=20)

        for result in report.repo_results:
            if result.skipped:
                status = f"[yellow]skipped: {result.skip_reason}[/yellow]"
            else:
                status = "[green]OK[/green]" if not result.error else f"[red]{result.error[:18]}[/red]"
            results_table.add_row(
                result.repo_name, str(result.files_analyzed),
                str(len(result.findings)), str(result.tokens_used),
                f"{result.duration_seconds:.1f}s", status,
            )

        console.print()
        console.print(results_table)

        console.print(f"\n[bold]Summary[/bold]")
        console.print(f"  Repos mined: {report.repos_scanned}")
        console.print(f"  Total findings: {report.total_findings}")
        console.print(f"  Tasks generated: {report.tasks_generated}")
        console.print(f"  Total tokens: {report.total_tokens}")
        console.print(f"  Total time: {report.total_duration_seconds:.1f}s")

        if report.tasks:
            console.print(f"\n[bold]Generated Tasks[/bold]")
            task_table = Table()
            task_table.add_column("Title", style="cyan", max_width=60)
            task_table.add_column("Priority", justify="right", style="yellow", width=8)
            task_table.add_column("Type", style="dim", width=16)
            task_table.add_column("Agent", style="green", width=8)

            for task in report.tasks:
                task_table.add_row(
                    task.title[:58], str(task.priority),
                    task.task_type or "-", task.recommended_agent or "-",
                )
            console.print(task_table)

        console.print(f"\n[dim]Use 'claw results' to view tasks, 'claw enhance .' to work on them.[/dim]")

    finally:
        await ctx.close()


@app.command(name="mine-self")
def mine_self(
    path: str = typer.Option(".", "--path", "-p", help="Project root to mine (defaults to cwd)"),
    target: str = typer.Option(None, "--target", "-t", help="Target project for findings (defaults to same project)"),
    min_relevance: float = typer.Option(0.5, "--min-relevance", help="Minimum relevance score for task generation"),
    tasks: bool = typer.Option(True, "--tasks/--no-tasks", help="Generate enhancement tasks from findings"),
    quick: bool = typer.Option(False, "--quick", "-q", help="Quick preview: file stats + domain signals, no LLM"),
    live_keycheck: bool = typer.Option(True, "--live-keycheck/--no-live-keycheck", help="Validate required provider keys"),
    max_minutes: int = typer.Option(10, "--max-minutes", help="Wall-clock time guardrail for mining"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Mine the current project's own code for reusable patterns.

    Point CAM at itself (or any single project) to discover patterns,
    architecture decisions, and reusable techniques within its own code.
    Findings are tagged with a [self] suffix for easy filtering.

    Use --quick for a fast preview (no LLM calls) showing file stats,
    language breakdown, and domain signal classification.

    Examples:
        cam mine-self --quick               # Fast preview of current project
        cam mine-self --path /my/project     # Mine a specific project
        cam mine-self --no-tasks             # Extract patterns without tasks
    """
    _setup_logging(verbose)

    project_path = _resolve_operator_path(path)
    if not project_path.exists():
        console.print(f"[red]Project path does not exist: {project_path}[/red]")
        raise typer.Exit(1)
    if not project_path.is_dir():
        console.print(f"[red]Path is not a directory: {project_path}[/red]")
        raise typer.Exit(1)

    if not (0.4 <= min_relevance <= 1.0):
        console.print("[red]--min-relevance must be between 0.4 and 1.0[/red]")
        raise typer.Exit(1)

    if quick:
        _mine_self_quick(project_path)
        return

    from claw.core.config import load_config

    cfg = load_config(Path(config) if config else None)
    _fail_if_missing_api_keys(cfg, "mine-self")
    if live_keycheck:
        _fail_if_live_key_checks_fail(cfg, "mine-self")

    effective_target = target if target else path

    try:
        asyncio.run(asyncio.wait_for(
            _mine_self_async(
                project_path, effective_target, min_relevance, tasks, config,
            ),
            timeout=max_minutes * 60,
        ))
    except TimeoutError:
        console.print(f"[red]Self-mining timed out after {max_minutes} minute(s)[/red]")
        raise typer.Exit(124)


def _mine_self_quick(project_path: Path) -> None:
    """Quick preview of a project: file stats + domain signals, no LLM calls."""
    from claw.miner import (
        _collect_repo_metadata, serialize_repo, _CODE_EXTENSIONS,
        _SKIP_DIRS, _DOMAIN_KEYWORDS, _LANGUAGE_SIGNALS,
    )

    console.print(f"\n[bold]CAM Self-Mining Quick Preview[/bold]")
    console.print(f"  Project: {project_path.name}")
    console.print(f"  Path: {project_path}")
    console.print()

    # Collect metadata (miner returns 5-tuple: file_count, last_commit_ts,
    # total_bytes, scan_signature, content_hash)
    file_count, last_commit_ts, total_bytes, scan_signature, _content_hash = _collect_repo_metadata(project_path)

    if total_bytes >= 1024 * 1024:
        size_str = f"{total_bytes / (1024 * 1024):.1f} MB"
    elif total_bytes >= 1024:
        size_str = f"{total_bytes / 1024:.0f} KB"
    else:
        size_str = f"{total_bytes} B"

    console.print(f"[bold]Project Stats[/bold]")
    console.print(f"  Source files: {file_count}")
    console.print(f"  Total size: {size_str}")
    console.print(f"  Scan signature: {scan_signature[:12]}...")
    console.print()

    # Language breakdown
    ext_counts: dict[str, int] = {}
    ext_bytes: dict[str, int] = {}
    try:
        for filepath in sorted(project_path.rglob("*")):
            if not filepath.is_file():
                continue
            rel = filepath.relative_to(project_path)
            if any(part in _SKIP_DIRS for part in rel.parts):
                continue
            ext = filepath.suffix.lower()
            if ext not in _CODE_EXTENSIONS:
                continue
            try:
                stat = filepath.stat()
            except OSError:
                continue
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
            ext_bytes[ext] = ext_bytes.get(ext, 0) + stat.st_size
    except (PermissionError, OSError):
        pass

    if ext_counts:
        lang_table = Table(title="Language Breakdown")
        lang_table.add_column("Extension", style="cyan", width=12)
        lang_table.add_column("Files", justify="right", style="green", width=8)
        lang_table.add_column("Size", justify="right", style="dim", width=10)
        lang_table.add_column("% of Code", justify="right", style="yellow", width=10)

        for ext in sorted(ext_counts, key=lambda e: -ext_bytes.get(e, 0)):
            pct = (ext_bytes[ext] / total_bytes * 100) if total_bytes > 0 else 0
            if ext_bytes[ext] >= 1024:
                sz = f"{ext_bytes[ext] / 1024:.0f} KB"
            else:
                sz = f"{ext_bytes[ext]} B"
            lang_table.add_row(ext, str(ext_counts[ext]), sz, f"{pct:.1f}%")

        console.print(lang_table)
        console.print()

    # Domain signal classification
    repo_content, _ = serialize_repo(project_path)
    if repo_content:
        content_lower = repo_content.lower()
        scores: dict[str, int] = {}
        for category, keywords in _DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in content_lower[:10_000])
            if score > 0:
                scores[category] = score

        if scores:
            ranked = sorted(scores.items(), key=lambda x: -x[1])
            domain_table = Table(title="Domain Signals")
            domain_table.add_column("Domain", style="cyan", max_width=20)
            domain_table.add_column("Signal Strength", justify="right", style="yellow", width=16)
            domain_table.add_column("Keywords Matched", justify="right", style="green", width=16)

            max_score = ranked[0][1] if ranked else 1
            for domain, score in ranked:
                bar_len = int(score / max_score * 15)
                bar = "█" * bar_len + "░" * (15 - bar_len)
                domain_table.add_row(domain, bar, str(score))

            console.print(domain_table)
            console.print()

        # Language detection
        language = "unknown"
        for config_name, lang in _LANGUAGE_SIGNALS.items():
            if f"--- file: {config_name}" in content_lower or f"/{config_name}" in content_lower:
                language = lang
                break

        if file_count < 50:
            complexity = "small"
        elif file_count <= 200:
            complexity = "medium"
        else:
            complexity = "large"

        console.print(f"[bold]Classification[/bold]")
        console.print(f"  Primary language: {language}")
        console.print(f"  Complexity: {complexity} ({file_count} files)")
        if scores:
            console.print(f"  Primary domain: {ranked[0][0]}")
            if len(ranked) > 1:
                console.print(f"  Secondary domains: {', '.join(d for d, _ in ranked[1:4])}")

    console.print(f"\n[dim]Run 'cam mine-self' (without --quick) for full LLM-powered mining.[/dim]")


async def _mine_self_async(
    project_path: Path,
    target: str,
    min_relevance: float,
    generate_tasks: bool,
    config_path: Optional[str],
) -> None:
    """Mine a project's own code for reusable patterns."""
    from claw.core.factory import ClawFactory
    from claw.core.models import Project

    config_p = Path(config_path) if config_path else None
    target_path = Path(target).resolve()
    ctx = await ClawFactory.create(config_path=config_p, workspace_dir=target_path)

    try:
        project_name = target_path.name
        project = await ctx.repository.get_project_by_name(project_name)
        if project is None:
            project = Project(name=project_name, repo_path=str(target_path))
            project = await ctx.repository.create_project(project)

        repo_name = f"{project_path.name}-self"

        console.print(f"\n[bold]CAM Self-Mining[/bold]")
        console.print(f"  Project: {project_path.name}")
        console.print(f"  Path: {project_path}")
        console.print(f"  Repo name: {repo_name}")
        console.print(f"  Target: {project.name} ({target_path})")
        console.print(f"  Min relevance: {min_relevance}")
        console.print(f"  Generate tasks: {generate_tasks}")
        console.print()

        console.print("[cyan]Mining own code for patterns...[/cyan]")
        result = await ctx.miner.mine_repo(project_path, repo_name, project.id)

        n_findings = len(result.findings) if result.findings else 0
        if result.error:
            console.print(f"[red]Mining failed: {result.error}[/red]")
            raise typer.Exit(1)

        # Display findings
        if result.findings:
            findings_table = Table(title=f"Self-Mining Findings ({n_findings})")
            findings_table.add_column("Category", style="magenta", width=16)
            findings_table.add_column("Title", style="cyan", max_width=50)
            findings_table.add_column("Relevance", justify="right", style="yellow", width=10)

            for finding in result.findings:
                findings_table.add_row(
                    finding.category, finding.title[:48],
                    f"{finding.relevance_score:.2f}" if hasattr(finding, 'relevance_score') else "-",
                )
            console.print(findings_table)

        console.print(f"\n[bold]Summary[/bold]")
        console.print(f"  Files analyzed: {result.files_analyzed}")
        console.print(f"  Findings: {n_findings}")
        console.print(f"  Tokens used: {result.tokens_used}")
        console.print(f"  Time: {result.duration_seconds:.1f}s")

        # Generate tasks from findings
        if generate_tasks and result.findings:
            tasks = await ctx.miner._generate_tasks(
                result.findings, project.id, min_relevance,
            )
            if tasks:
                console.print(f"\n[bold]Self-Improvement Tasks ({len(tasks)})[/bold]")
                task_table = Table()
                task_table.add_column("Title", style="cyan", max_width=60)
                task_table.add_column("Priority", justify="right", style="yellow", width=8)
                task_table.add_column("Type", style="dim", width=16)

                for task in tasks:
                    task_table.add_row(
                        task.title[:58], str(task.priority), task.task_type or "-",
                    )
                console.print(task_table)

        console.print(f"\n[dim]Findings tagged as '{repo_name}'. Use 'cam learn search \"{repo_name}\"' to query.[/dim]")

    finally:
        await ctx.close()


@app.command()
def enrich(
    limit: int = typer.Option(100, "--limit", "-n", help="Maximum methodologies to enrich"),
    include_ganglia: bool = typer.Option(False, "--include-ganglia", help="Also enrich ganglion DBs (instances/*/claw.db)"),
    parallelism: int = typer.Option(8, "--parallelism", "-p", help="Concurrent assimilation tasks (max 16)"),
    skip_llm: bool = typer.Option(True, "--skip-llm/--no-skip-llm", help="Skip LLM potential assessment in novelty scoring"),
    live_keycheck: bool = typer.Option(True, "--live-keycheck/--no-live-keycheck", help="Validate required provider keys"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Batch-enrich unenriched (embryonic) methodologies with LLM assimilation.

    Processes methodologies that were stored without assimilation (e.g. from
    `cam mine --fast`). For each methodology, runs capability extraction,
    novelty scoring, and synergy discovery.

    Examples:
        cam enrich                     # Enrich up to 100 methodologies
        cam enrich --limit 500         # Enrich up to 500
        cam enrich --include-ganglia   # Also process ganglion DBs
        cam enrich --parallelism 4     # Fewer concurrent tasks
    """
    _setup_logging(verbose)

    parallelism = max(1, min(parallelism, 16))

    from claw.core.config import load_config

    cfg = load_config(Path(config) if config else None)
    _fail_if_missing_api_keys(cfg, "mine")
    if live_keycheck:
        _fail_if_live_key_checks_fail(cfg, "mine")

    try:
        asyncio.run(_enrich_async(
            limit=limit,
            include_ganglia=include_ganglia,
            parallelism=parallelism,
            skip_llm=skip_llm,
            config_path=config,
        ))
    except Exception as e:
        console.print(f"[red]Enrichment failed: {e}[/red]")
        raise typer.Exit(1)


async def _enrich_async(
    *,
    limit: int,
    include_ganglia: bool,
    parallelism: int,
    skip_llm: bool,
    config_path: Optional[str],
) -> None:
    from claw.core.factory import ClawFactory
    from claw.evolution.assimilation import CapabilityAssimilationEngine

    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p)

    try:
        console.print(f"\n[bold]CAM Batch Enrichment[/bold]")
        console.print(f"  Limit: {limit}")
        console.print(f"  Parallelism: {parallelism}")
        console.print(f"  Skip LLM potential: {skip_llm}")
        console.print(f"  Include ganglia: {include_ganglia}")
        console.print(f"  Database: {ctx.config.database.db_path}")
        console.print()

        # --- Primary DB ---
        unenriched = await ctx.repository.get_unenriched_methodologies(limit)
        console.print(f"[cyan]Found {len(unenriched)} unenriched methodologies in primary DB[/cyan]")

        enriched_count = 0
        error_count = 0

        if unenriched and ctx.assimilation_engine is not None:
            semaphore = asyncio.Semaphore(parallelism)

            async def _enrich_one(meth_id: str) -> bool:
                nonlocal enriched_count, error_count
                async with semaphore:
                    try:
                        result = await ctx.assimilation_engine.assimilate(
                            meth_id, skip_llm_potential=skip_llm,
                        )
                        if result.get("enriched"):
                            enriched_count += 1
                            return True
                        return False
                    except Exception as e:
                        error_count += 1
                        logging.getLogger("claw.cli").warning(
                            "Enrich failed for %s: %s", meth_id, e,
                        )
                        return False

            tasks = [_enrich_one(m.id) for m in unenriched]
            await asyncio.gather(*tasks)

            console.print(
                f"  [green]{enriched_count} enriched[/green], "
                f"[red]{error_count} errors[/red] "
                f"(of {len(unenriched)} attempted)"
            )
        elif ctx.assimilation_engine is None:
            console.print("[yellow]Assimilation engine not available (disabled in config?)[/yellow]")

        # --- Ganglia ---
        if include_ganglia:
            project_root = Path(ctx.config.database.db_path).parent.parent
            instances_dir = project_root / "instances"
            if instances_dir.exists():
                ganglion_dbs = sorted(instances_dir.glob("*/claw.db"))
                console.print(f"\n[cyan]Scanning {len(ganglion_dbs)} ganglion DB(s)...[/cyan]")

                for gdb_path in ganglion_dbs:
                    ganglion_name = gdb_path.parent.name
                    try:
                        from claw.db.engine import DatabaseEngine
                        from claw.db.repository import Repository
                        g_engine = DatabaseEngine(str(gdb_path))
                        await g_engine.initialize()
                        g_repo = Repository(g_engine)

                        g_unenriched = await g_repo.get_unenriched_methodologies(limit)
                        if not g_unenriched:
                            console.print(f"  {ganglion_name}: 0 unenriched — skipping")
                            await g_engine.close()
                            continue

                        console.print(
                            f"  {ganglion_name}: {len(g_unenriched)} unenriched — enriching..."
                        )

                        g_assimilation = CapabilityAssimilationEngine(
                            g_repo, ctx.llm_client, ctx.config,
                        )

                        g_enriched = 0
                        g_errors = 0
                        g_sem = asyncio.Semaphore(parallelism)

                        async def _enrich_ganglion(mid: str) -> None:
                            nonlocal g_enriched, g_errors
                            async with g_sem:
                                try:
                                    r = await g_assimilation.assimilate(
                                        mid, skip_llm_potential=skip_llm,
                                    )
                                    if r.get("enriched"):
                                        g_enriched += 1
                                except Exception as e:
                                    g_errors += 1
                                    logging.getLogger("claw.cli").warning(
                                        "Ganglion enrich failed for %s/%s: %s",
                                        ganglion_name, mid, e,
                                    )

                        g_tasks = [_enrich_ganglion(m.id) for m in g_unenriched]
                        await asyncio.gather(*g_tasks)

                        console.print(
                            f"    [green]{g_enriched} enriched[/green], "
                            f"[red]{g_errors} errors[/red]"
                        )
                        enriched_count += g_enriched
                        error_count += g_errors

                        await g_engine.close()
                    except Exception as e:
                        console.print(f"  [red]{ganglion_name}: error — {e}[/red]")
            else:
                console.print("[dim]No instances/ directory found — no ganglia to scan.[/dim]")

        # Final summary
        console.print(f"\n[bold]Enrichment Complete[/bold]")
        console.print(
            f"  Total enriched: [green]{enriched_count}[/green], "
            f"errors: [red]{error_count}[/red]"
        )

    finally:
        await ctx.close()


@app.command(name="forge-export", hidden=True)
def forge_export(
    out: str = typer.Option("data/cam_knowledge_pack.jsonl", "--out", help="Output JSONL knowledge pack path"),
    db: Optional[str] = typer.Option(None, "--db", help="Override CAM database path"),
    max_methodologies: int = typer.Option(300, "--max-methodologies", help="Maximum methodologies to export"),
    max_tasks: int = typer.Option(300, "--max-tasks", help="Maximum tasks to export"),
    max_minutes: int = typer.Option(5, "--max-minutes", help="Wall-clock time guardrail for the export"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Export CAM memory into a standalone Forge knowledge pack."""
    from claw.core.config import load_config

    _setup_logging(verbose)
    cfg = load_config(Path(config) if config else None)
    db_path = db or cfg.database.db_path
    script_path = ROOT_DIR / "scripts" / "export_cam_knowledge_pack.py"

    console.print("\n[bold]CAM Forge Export[/bold]")
    console.print(f"  Database: {db_path}")
    console.print(f"  Out: {out}")
    console.print(f"  Max methodologies: {max_methodologies}")
    console.print(f"  Max tasks: {max_tasks}")
    console.print(f"  Time guardrail: {max_minutes} minute(s)")

    result = _run_python_script_with_timeout(
        script_path=script_path,
        args=[
            "--db", db_path,
            "--out", out,
            "--max-methodologies", str(max_methodologies),
            "--max-tasks", str(max_tasks),
        ],
        max_minutes=max_minutes,
    )

    if result.returncode != 0:
        console.print(f"[red]Export failed with exit code {result.returncode}[/red]")
        if result.stderr.strip():
            console.print(result.stderr.strip())
        raise typer.Exit(result.returncode)

    payload = json.loads(result.stdout)
    console.print("\n[green]Knowledge pack exported.[/green]")
    console.print(f"  Total: {payload['total']}")
    console.print(f"  Methodologies: {payload['methodologies']}")
    console.print(f"  Tasks: {payload['tasks']}")
    console.print(f"  File: {payload['out']}")


@app.command(name="forge-benchmark", hidden=True)
def forge_benchmark(
    repo: str = typer.Option("tests/fixtures/embedding_forge/repo", "--repo", help="Fixture or target repo path"),
    note: str = typer.Option("tests/fixtures/embedding_forge/note.md", "--note", help="Note path"),
    knowledge_pack: str = typer.Option(
        "tests/fixtures/embedding_forge/knowledge_pack.jsonl",
        "--knowledge-pack",
        help="Knowledge pack JSONL path",
    ),
    out: str = typer.Option("data/forge_benchmark_fixture", "--out", help="Output benchmark directory"),
    max_minutes: int = typer.Option(5, "--max-minutes", help="Wall-clock time guardrail for the benchmark"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Run the standalone Forge regression benchmark with a wall-clock limit."""
    _setup_logging(verbose)
    script_path = ROOT_DIR / "apps" / "embedding_forge" / "benchmark_regression.py"

    console.print("\n[bold]CAM Forge Benchmark[/bold]")
    console.print(f"  Repo: {repo}")
    console.print(f"  Note: {note}")
    console.print(f"  Knowledge pack: {knowledge_pack}")
    console.print(f"  Out: {out}")
    console.print(f"  Time guardrail: {max_minutes} minute(s)")

    result = _run_python_script_with_timeout(
        script_path=script_path,
        args=[
            "--repo", repo,
            "--note", note,
            "--knowledge-pack", knowledge_pack,
            "--out", out,
        ],
        max_minutes=max_minutes,
    )

    if result.returncode != 0:
        console.print(f"[red]Benchmark failed with exit code {result.returncode}[/red]")
        if result.stderr.strip():
            console.print(result.stderr.strip())
        raise typer.Exit(result.returncode)

    payload = json.loads(result.stdout)
    best = payload["best"]
    console.print("\n[green]Benchmark complete.[/green]")
    console.print(f"  Status: {payload['status']}")
    console.print(f"  Docs: {payload['docs_total']}")
    console.print(f"  Best lift: {best['hit_rate_lift_pct']:.2f}%")
    console.print(
        "  Best config: "
        f"anchor_dim={best['anchor_dim']} residual_dim={best['residual_dim']} "
        f"anchor_weight={best['anchor_weight']} residual_weight={best['residual_weight']}"
    )
    console.print(f"  Summary: {Path(out) / 'benchmark_summary.json'}")


@app.command()
def validate(
    spec_file: str = typer.Option(..., "--spec-file", help="Creation spec JSON to validate against"),
    max_minutes: int = typer.Option(5, "--max-minutes", help="Wall-clock time guardrail for validation"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Validate a created repo against its saved spec and acceptance checks."""
    _setup_logging(verbose)

    if max_minutes < 1:
        console.print("[red]--max-minutes must be at least 1[/red]")
        raise typer.Exit(1)

    spec_path = Path(spec_file).resolve()
    if not spec_path.exists():
        console.print(f"[red]Spec file does not exist: {spec_path}[/red]")
        raise typer.Exit(1)

    spec_payload = json.loads(spec_path.read_text(encoding="utf-8"))
    passed, summary = _validate_create_spec(spec_payload, max_minutes=max_minutes)

    console.print("\n[bold]CAM Validate[/bold]")
    console.print(f"  Spec file: {spec_path}")
    console.print(f"  Repo: {summary['repo']}")
    console.print(f"  Checks run: {summary['checks_run']}")
    if summary["manual_checks"]:
        console.print(f"  Manual checks: {len(summary['manual_checks'])}")
    expectation = summary.get("expectation_assessment", {}) or {}
    if expectation.get("score") is not None:
        console.print(f"  Expectation match: {expectation['score']:.3f}")

    if passed:
        console.print("\n[green]Validation passed.[/green]")
    else:
        console.print("\n[red]Validation failed.[/red]")
        for finding in summary["findings"]:
            console.print(f"  - {finding}")

    for check in summary["checks"]:
        status = "[green]OK[/green]" if check["ok"] else "[red]FAIL[/red]"
        console.print(f"  {status} {check['command']}")

    for check in summary["manual_checks"]:
        console.print(f"  [yellow]MANUAL[/yellow] {check}")

    if expectation.get("summary"):
        console.print(f"\n[bold]Expectation Assessment[/bold]")
        console.print(f"  {expectation['summary']}")
        for item in expectation.get("matched", [])[:5]:
            console.print(f"  [green]MATCH[/green] {item}")
        for item in expectation.get("unmet", [])[:8]:
            console.print(f"  [yellow]GAP[/yellow] {item}")

    if not passed:
        raise typer.Exit(2)


@app.command()
def benchmark(
    repo: str = typer.Option("tests/fixtures/embedding_forge/repo", "--repo", help="Fixture or target repo path"),
    note: str = typer.Option("tests/fixtures/embedding_forge/note.md", "--note", help="Note path"),
    knowledge_pack: str = typer.Option(
        "tests/fixtures/embedding_forge/knowledge_pack.jsonl",
        "--knowledge-pack",
        help="Knowledge pack JSONL path",
    ),
    out: str = typer.Option("data/forge_benchmark_fixture", "--out", help="Output benchmark directory"),
    max_minutes: int = typer.Option(5, "--max-minutes", help="Wall-clock time guardrail for the benchmark"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Benchmark Forge output."""
    _setup_logging(verbose)
    script_path = ROOT_DIR / "apps" / "embedding_forge" / "benchmark_regression.py"

    console.print("\n[bold]CAM Benchmark[/bold]")
    console.print(f"  Repo: {repo}")
    console.print(f"  Note: {note}")
    console.print(f"  Knowledge pack: {knowledge_pack}")
    console.print(f"  Out: {out}")
    console.print(f"  Time guardrail: {max_minutes} minute(s)")

    result = _run_python_script_with_timeout(
        script_path=script_path,
        args=[
            "--repo", repo,
            "--note", note,
            "--knowledge-pack", knowledge_pack,
            "--out", out,
        ],
        max_minutes=max_minutes,
    )

    if result.returncode != 0:
        console.print(f"[red]Benchmark failed with exit code {result.returncode}[/red]")
        if result.stderr.strip():
            console.print(result.stderr.strip())
        raise typer.Exit(result.returncode)

    payload = json.loads(result.stdout)
    best = payload["best"]
    console.print("\n[green]Benchmark complete.[/green]")
    console.print(f"  Status: {payload['status']}")
    console.print(f"  Best lift: {best['hit_rate_lift_pct']:.2f}%")
    console.print(f"  Summary: {Path(out) / 'benchmark_summary.json'}")


@app.command(hidden=True)
def govern(
    action: str = typer.Argument(
        "stats",
        help="Action: stats, sweep, gc, quota, prune, bandit-stats",
    ),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Verbose output"),
    config: Optional[str] = typer.Option(None, "--config", help="Path to claw.toml"),
) -> None:
    """Memory governance — sweep, stats, GC, quota enforcement, episode pruning.

    Actions:
      stats        — Show methodology counts by state, DB size, quota usage
      sweep        — Run a full governance sweep (lifecycle + GC + quota + prune)
      gc           — Garbage-collect dead methodologies only
      quota        — Enforce methodology quota only
      prune        — Prune old episodes only
      bandit-stats — Show RL bandit win/loss statistics per methodology x task_type
    """
    _setup_logging(verbose)
    asyncio.run(_govern_async(action, config))


async def _govern_async(action: str, config_path: Optional[str]) -> None:
    """Run governance action."""
    from claw.core.config import load_config
    from claw.db.engine import DatabaseEngine
    from claw.db.repository import Repository
    from claw.memory.governance import MemoryGovernor

    cfg = load_config(Path(config_path) if config_path else None)

    engine = DatabaseEngine(cfg.database)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    repository = Repository(engine)

    governor = MemoryGovernor(repository=repository, config=cfg.governance, claw_config=cfg)

    try:
        if action == "stats":
            stats = await governor.get_storage_stats()
            active_methodologies = sum(v for k, v in stats.by_state.items() if k != "dead")
            console.print("\n[bold]Memory Governance Stats[/bold]")
            console.print(f"  Total methodologies:  {stats.total_methodologies}")
            console.print(f"  Active (non-dead):    {active_methodologies}")

            table = Table(title="Methodologies by State")
            table.add_column("State", style="bold")
            table.add_column("Count", justify="right")
            for state, count in sorted(stats.by_state.items()):
                style = {
                    "thriving": "green",
                    "viable": "cyan",
                    "embryonic": "yellow",
                    "declining": "magenta",
                    "dormant": "dim",
                    "dead": "red",
                }.get(state, "")
                table.add_row(f"[{style}]{state}[/{style}]" if style else state, str(count))
            console.print(table)

            quota = cfg.governance.max_methodologies
            if quota > 0:
                usage_pct = active_methodologies / quota * 100
                bar_style = "green" if usage_pct < 80 else ("yellow" if usage_pct < 100 else "red")
                console.print(f"  Quota: {active_methodologies}/{quota} ({usage_pct:.1f}%) [{bar_style}]")
            else:
                console.print(f"  Quota: {active_methodologies} (unlimited)")
            console.print(f"  DB size: {stats.db_size_bytes / 1024 / 1024:.2f} MB")
            console.print(f"  Episodes: {stats.total_episodes}")

        elif action == "sweep":
            console.print("[bold]Running full governance sweep...[/bold]")
            report = await governor.run_full_sweep()
            console.print(f"  Dead collected:    {report.dead_collected}")
            console.print(f"  Quota culled:      {report.quota_culled}")
            console.print(f"  Episodes pruned:   {report.episodes_pruned}")
            transitions = report.lifecycle_transitions or {}
            if transitions:
                for key, count in transitions.items():
                    console.print(f"  Lifecycle {key}: {count}")
            else:
                console.print("  Lifecycle transitions: none")
            console.print("[green]Sweep complete.[/green]")

        elif action == "gc":
            console.print("[bold]Garbage-collecting dead methodologies...[/bold]")
            count = await governor.garbage_collect_dead()
            console.print(f"  Removed: {count} dead methodologies")

        elif action == "quota":
            console.print("[bold]Enforcing methodology quota...[/bold]")
            count = await governor.enforce_methodology_quota()
            console.print(f"  Culled: {count} methodologies to stay within quota")

        elif action == "prune":
            console.print("[bold]Pruning old episodes...[/bold]")
            count = await governor._prune_episodes()
            console.print(f"  Pruned: {count} episodes older than {cfg.governance.episodic_retention_days} days")

        elif action == "bandit-stats":
            rows = await repository.get_bandit_summary()
            if not rows:
                console.print("No bandit outcomes recorded yet.")
            else:
                table = Table(title="RL Bandit Statistics")
                table.add_column("Methodology", style="bold", max_width=20)
                table.add_column("Task Type", style="cyan")
                table.add_column("W", justify="right", style="green")
                table.add_column("L", justify="right", style="red")
                table.add_column("Total", justify="right")
                table.add_column("Win Rate", justify="right")
                table.add_column("Thompson", justify="center")
                for r in rows:
                    mid = r["methodology_id"]
                    if len(mid) > 20:
                        mid = mid[:17] + "..."
                    graduated = "yes" if r["thompson_graduated"] else "no"
                    table.add_row(
                        mid,
                        r["task_type"],
                        str(r["successes"]),
                        str(r["failures"]),
                        str(r["total"]),
                        f"{r['win_rate']:.3f}",
                        graduated,
                    )
                console.print(table)

                total_pairs = len(rows)
                graduated_count = sum(1 for r in rows if r["thompson_graduated"])
                total_trials = sum(r["total"] for r in rows)
                total_wins = sum(r["successes"] for r in rows)
                overall_wr = total_wins / total_trials if total_trials > 0 else 0.0
                console.print(f"  Pairs tracked:       {total_pairs}")
                console.print(f"  Thompson-graduated:  {graduated_count}")
                console.print(f"  Overall win rate:    {overall_wr:.3f} ({total_wins}/{total_trials})")

        else:
            console.print(f"[red]Unknown action: {action}[/red]")
            console.print("[dim]Valid actions: stats, sweep, gc, quota, prune, bandit-stats[/dim]")

    finally:
        await engine.close()


@app.command()
def setup(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Interactive setup for API keys, models, and agent configuration.

    Walks you through configuring each agent with API keys and model preferences,
    then writes the updated configuration to claw.toml.
    """
    import toml as _toml

    if config:
        config_path = Path(config).resolve()
    else:
        resolved = _find_default_claw_toml()
        if resolved is None:
            console.print("[red]Config file not found: claw.toml[/red]")
            console.print("[dim]Run from the multiclaw directory or pass --config path/to/claw.toml[/dim]")
            raise typer.Exit(1)
        config_path = resolved.resolve()

    if not config_path.exists():
        console.print(f"[red]Config file not found: {config_path}[/red]")
        console.print("[dim]Run from the multiclaw directory or pass --config path/to/claw.toml[/dim]")
        raise typer.Exit(1)

    console.print(f"\n[bold]CAM Setup[/bold]")
    console.print(f"  Config: {config_path}\n")

    # Load .env file so API keys and models are available
    import os
    from dotenv import load_dotenv
    env_path = config_path.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)
        console.print(f"  [dim]Loaded .env from {env_path}[/dim]")
    else:
        console.print(f"  [yellow]No .env found. Run: cp .env.example .env[/yellow]")
        console.print(f"  [yellow]Fill in your API keys and models, then re-run cam setup.[/yellow]")
        raise typer.Exit(1)

    # Load current config
    with open(config_path) as f:
        raw = _toml.load(f)

    agents_section = raw.setdefault("agents", {})
    changed = False

    # ── Key summary (read-only, no prompts) ──
    console.print(f"\n[bold cyan]── API Keys (from .env) ──[/bold cyan]")
    key_checks = {
        "OPENROUTER_API_KEY": "Multi-agent LLM routing",
        "XAI_API_KEY": "PULSE X-Scout scanning",
        "GOOGLE_API_KEY": "Embeddings / novelty scoring",
    }
    keys_ok = {}
    for key_name, purpose in key_checks.items():
        val = os.getenv(key_name, "")
        keys_ok[key_name] = bool(val)
        status = "[green]set[/green]" if val else "[red]missing[/red]"
        console.print(f"  {key_name}: {status}  ({purpose})")

    if not any(keys_ok.values()):
        console.print(f"\n  [red]No API keys found. Edit .env and add your keys first.[/red]")
        raise typer.Exit(1)
    console.print()

    has_openrouter = keys_ok["OPENROUTER_API_KEY"]

    # ── Agent models (read from .env CAM_MODEL_* vars) ──
    console.print(f"[bold cyan]── Agent Models (from .env) ──[/bold cyan]")
    agent_slots = {
        "claude": {"env_var": "CAM_MODEL_CLAUDE", "label": "Claude"},
        "codex": {"env_var": "CAM_MODEL_CODEX", "label": "Codex"},
        "gemini": {"env_var": "CAM_MODEL_GEMINI", "label": "Gemini"},
        "grok": {"env_var": "CAM_MODEL_GROK", "label": "Grok"},
    }

    enabled_agents = []
    for agent_name, slot in agent_slots.items():
        model = os.getenv(slot["env_var"], "").strip()
        if model:
            console.print(f"  {slot['label']:8s} → {model}")
            enabled_agents.append((agent_name, model))
        else:
            console.print(f"  [dim]{slot['label']:8s} → (not set — agent disabled)[/dim]")

    if not enabled_agents:
        console.print(f"\n  [yellow]No agent models set. Add CAM_MODEL_* vars to .env.[/yellow]")
        console.print(f"  [dim]Example: CAM_MODEL_CLAUDE=anthropic/claude-sonnet-4-6[/dim]")

    # PULSE model
    pulse_model = os.getenv("CAM_PULSE_MODEL", "").strip()
    console.print(f"\n  {'PULSE':8s} → {pulse_model or '[dim](not set)[/dim]'}")
    console.print()

    # ── Budget configuration (the only interactive part) ──
    console.print(f"[bold cyan]── Budget Configuration ──[/bold cyan]")
    console.print(f"  Budgets are hard caps — CAM stops spending when hit.")
    console.print(f"  Typical costs:")
    console.print(f"    Per-agent task (evaluate/enhance a repo): $0.50 - $2.00")
    console.print(f"    PULSE scan (4 keywords via x_search):    ~$0.02 per scan")
    console.print(f"    PULSE daily (scan every 30 min):          ~$1-2 per day")
    console.print()

    for agent_name, model in enabled_agents:
        current = agents_section.get(agent_name, {})
        current_budget = current.get("max_budget_usd", 1.0)
        budget_input = console.input(
            f"  {agent_name} max budget per task USD [{current_budget}]: "
        ).strip()
        try:
            budget = float(budget_input) if budget_input else current_budget
        except ValueError:
            console.print(f"  [yellow]Invalid, keeping ${current_budget:.2f}[/yellow]")
            budget = current_budget

        # Write agent config
        agent_section = agents_section.setdefault(agent_name, {})
        new_values = {
            "enabled": True,
            "mode": "openrouter" if has_openrouter else "api",
            "api_key_env": "OPENROUTER_API_KEY" if has_openrouter else "",
            "model": model,
            "max_concurrent": current.get("max_concurrent", 2),
            "timeout": current.get("timeout", 600 if agent_name in ("claude", "gemini") else 300),
            "max_budget_usd": budget,
        }
        if new_values != {k: current.get(k) for k in new_values}:
            changed = True
        agent_section.update(new_values)
        console.print(f"  [green]{agent_name}: {model}, ${budget:.2f}/task[/green]")

    # Disable agents that have no model set
    all_agent_names = set(agent_slots.keys())
    enabled_names = {name for name, _ in enabled_agents}
    for disabled_name in all_agent_names - enabled_names:
        section = agents_section.setdefault(disabled_name, {})
        if section.get("enabled", False):
            section["enabled"] = False
            changed = True

    console.print()

    # ── PULSE configuration ──
    console.print(f"[bold cyan]── CAM-PULSE (X-Scout Discovery) ──[/bold cyan]")
    pulse_section = raw.setdefault("pulse", {})
    has_xai = keys_ok["XAI_API_KEY"]

    if not has_xai:
        console.print(f"  [dim]PULSE disabled — XAI_API_KEY not set in .env[/dim]\n")
        pulse_section["enabled"] = False
    elif not pulse_model:
        console.print(f"  [dim]PULSE disabled — CAM_PULSE_MODEL not set in .env[/dim]")
        console.print(f"  [dim]Add: CAM_PULSE_MODEL=grok-4-1-fast-non-reasoning[/dim]\n")
        pulse_section["enabled"] = False
    else:
        pulse_section["enabled"] = True
        pulse_section["xai_model"] = pulse_model

        current_pulse_budget = pulse_section.get("max_cost_per_day_usd", 10.0)
        budget_input = console.input(
            f"  PULSE max cost per day USD [{current_pulse_budget}]: "
        ).strip()
        try:
            pulse_budget = float(budget_input) if budget_input else current_pulse_budget
        except ValueError:
            console.print(f"  [yellow]Invalid, keeping ${current_pulse_budget:.2f}[/yellow]")
            pulse_budget = current_pulse_budget
        pulse_section["max_cost_per_day_usd"] = pulse_budget

        # Profile configuration
        profile_section = pulse_section.setdefault("profile", {})
        current_profile_name = profile_section.get("name", "general")
        current_profile_mission = profile_section.get("mission", "")
        current_profile_domains = profile_section.get("domains", [])

        console.print(f"\n  [bold]Mission Profile[/bold]")
        console.print(f"  [dim]Focus your PULSE instance on a domain (or keep 'general' for broad discovery)[/dim]")
        profile_name_input = console.input(
            f"  Profile name [{current_profile_name}]: "
        ).strip()
        if profile_name_input:
            profile_section["name"] = profile_name_input
            changed = True

        mission_input = console.input(
            f"  Mission [{current_profile_mission or 'none'}]: "
        ).strip()
        if mission_input:
            profile_section["mission"] = mission_input
            changed = True

        domains_str = ", ".join(current_profile_domains) if current_profile_domains else "none"
        domains_input = console.input(
            f"  Domains (comma-separated) [{domains_str}]: "
        ).strip()
        if domains_input:
            profile_section["domains"] = [d.strip() for d in domains_input.split(",") if d.strip()]
            changed = True

        console.print(f"\n  [green]PULSE: {pulse_model}, ${pulse_budget:.2f}/day, profile={profile_section.get('name', 'general')}[/green]\n")

    changed = True  # Always write to capture model updates from .env

    # --- Write config ---
    if changed:
        with open(config_path, "w") as f:
            _toml.dump(raw, f)
        console.print(f"[green]Configuration saved to {config_path}[/green]")
    else:
        console.print(f"[dim]No changes made to {config_path}[/dim]")

    # --- Summary ---
    enabled_agents = [
        name for name, cfg in agents_section.items()
        if isinstance(cfg, dict) and cfg.get("enabled")
    ]
    console.print(f"\n[bold]Setup Complete[/bold]")
    console.print(f"  Enabled agents: {', '.join(enabled_agents) or 'none'}")

    # Check for missing keys
    missing_keys = []
    for name in enabled_agents:
        cfg = agents_section[name]
        key_env_name = cfg.get("api_key_env", "")
        if key_env_name and not os.getenv(key_env_name, ""):
            missing_keys.append(f"  export {key_env_name}=your-key-here")

    if missing_keys:
        console.print(f"\n[yellow]Missing API keys — add these to your shell profile:[/yellow]")
        for line in missing_keys:
            console.print(line)

    console.print(f"\n[dim]Next steps:[/dim]")
    console.print(f"  cam status              — verify agent connectivity")
    console.print(f"  cam evaluate <repo>     — analyze a repository")
    console.print(f"  cam add-goal <repo>     — add a custom task")
    console.print(f"  cam enhance <repo>      — run the full pipeline")
    console.print(f"  cam fleet-enhance <dir> — process a fleet of repos")
    console.print(f"  cam pulse preflight     — verify PULSE configuration")
    console.print(f"  cam pulse scan          — run a single X-Scout scan")
    console.print(f"  cam forge-export        — export CAM memory for standalone Forge")
    console.print(f"  cam forge-benchmark     — benchmark Forge with time guardrails")


@app.command(hidden=True)
def synergies(
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Show detailed edge list"),
    config: Optional[str] = typer.Option(None, "--config", help="Path to claw.toml"),
):
    """Show capability synergy graph summary, exploration stats, and recent discoveries."""
    _setup_logging(verbose)
    asyncio.run(_synergies_async(verbose))


@app.command(name="assimilation-report", hidden=True)
def assimilation_report(
    limit: int = typer.Option(10, "--limit", "-n", help="Rows to show per section"),
    future_threshold: float = typer.Option(0.65, "--future-threshold", help="Potential score threshold for future-candidate flag"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Show the learning continuum from stored methodologies to proven usefulness."""
    _setup_logging(False)
    asyncio.run(_assimilation_report_async(limit, future_threshold))


@app.command(name="assimilation-delta", hidden=True)
def assimilation_delta(
    directory: Optional[str] = typer.Argument(None, help="Optional repo directory to scope the report"),
    depth: int = typer.Option(6, "--depth", "-d", help="Max directory depth when scoping by directory"),
    dedup: bool = typer.Option(True, "--dedup/--no-dedup", help="Dedup repo iterations by canonical name"),
    since_hours: float = typer.Option(24.0, "--since-hours", help="Only include repos mined within this many hours"),
    latest: int = typer.Option(10, "--latest", "-n", help="Maximum recently mined repos/methodologies to summarize"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Show what recent mine runs actually added: methodologies, templates, capabilities, and next uses."""
    _setup_logging(False)
    asyncio.run(_assimilation_delta_async(directory, depth, dedup, since_hours, latest, config))


@app.command(hidden=True)
def reassess(
    repo: Optional[str] = typer.Argument(None, help="Optional repository path for additional context"),
    task: str = typer.Option(..., "--task", "-t", help="Task or goal CAM should reassess prior knowledge against"),
    limit: int = typer.Option(10, "--limit", "-n", help="Maximum recommendations to show"),
    min_score: float = typer.Option(0.2, "--min-score", help="Minimum reassessment score to show"),
    future_threshold: float = typer.Option(0.65, "--future-threshold", help="Potential score threshold for future-candidate flag"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Re-score prior methodologies against a new task and explain why they matter now."""
    _setup_logging(False)
    asyncio.run(_reassess_async(repo, task, limit, min_score, future_threshold))


async def _assimilation_delta_async(
    directory: Optional[str],
    depth: int,
    dedup: bool,
    since_hours: float,
    latest: int,
    config: Optional[str],
) -> None:
    from datetime import UTC, datetime
    from rich.panel import Panel
    from claw.core.config import load_config
    from claw.miner import RepoScanLedger, _default_scan_ledger_path, _discover_repos, _dedup_iterations

    cfg = load_config(Path(config) if config else None)
    ledger = RepoScanLedger(_default_scan_ledger_path(cfg))

    scoped_repo_keys: Optional[set[str]] = None
    if directory:
        dir_path = Path(directory).resolve()
        if not dir_path.exists():
            console.print(f"[red]Directory does not exist: {dir_path}[/red]")
            raise typer.Exit(1)
        if not dir_path.is_dir():
            console.print(f"[red]Path is not a directory: {dir_path}[/red]")
            raise typer.Exit(1)
        candidates = _discover_repos(dir_path, max_depth=depth)
        if dedup:
            candidates, _ = _dedup_iterations(candidates)
        scoped_repo_keys = {ledger.repo_key(candidate.path) for candidate in candidates}

    cutoff_ts = _time.time() - (max(since_hours, 0.0) * 3600.0)
    records = ledger.list_records()
    if scoped_repo_keys is not None:
        records = [record for record in records if record.repo_path in scoped_repo_keys]
    records = [record for record in records if record.last_mined_at >= cutoff_ts]
    records.sort(key=lambda record: record.last_mined_at, reverse=True)
    if latest > 0:
        records = records[:latest]

    if not records:
        console.print("[yellow]No mined repos matched this delta window. Try a larger --since-hours or run cam mine first.[/yellow]")
        return

    engine, repository = await _kb_engine()

    try:
        repo_summaries: list[dict[str, Any]] = []
        all_methodologies: list[Any] = []
        methodology_ids_with_templates: set[str] = set()

        for record in records:
            methodologies: list[Any] = []
            seen_methodology_ids: set[str] = set()
            for methodology_id in record.methodology_ids:
                meth = await repository.get_methodology(methodology_id)
                if meth is not None and meth.id not in seen_methodology_ids:
                    methodologies.append(meth)
                    seen_methodology_ids.add(meth.id)

            if not methodologies:
                fallback_methodologies = await repository.get_methodologies_by_tag(
                    f"source:{record.repo_name}",
                    limit=max(20, record.findings_count * 3 or 20),
                )
                methodologies = [
                    meth for meth in fallback_methodologies
                    if _recently_created_near_mine(meth.created_at, record.last_mined_at)
                ]
                seen_methodology_ids = {meth.id for meth in methodologies}

            action_templates: list[Any] = []
            for template_id in record.action_template_ids:
                template = await repository.get_action_template(template_id)
                if template is not None:
                    action_templates.append(template)
                    if template.source_methodology_id:
                        methodology_ids_with_templates.add(template.source_methodology_id)

            if not action_templates:
                fallback_templates = await repository.list_action_templates(
                    source_repo=record.repo_name,
                    limit=max(10, len(methodologies) * 2 or 10),
                )
                action_templates = [
                    template for template in fallback_templates
                    if _recently_created_near_mine(template.created_at, record.last_mined_at)
                ]
                for template in action_templates:
                    if template.source_methodology_id:
                        methodology_ids_with_templates.add(template.source_methodology_id)

            future_candidates = [
                meth for meth in methodologies
                if _is_future_candidate(
                    meth,
                    potential_threshold=0.65,
                    template_count=1 if meth.id in methodology_ids_with_templates else 0,
                )
            ]

            all_methodologies.extend(methodologies)
            repo_summaries.append({
                "record": record,
                "methodologies": methodologies,
                "templates": action_templates,
                "future_candidates": future_candidates,
            })

        if not all_methodologies:
            console.print("[yellow]Mine records exist, but no stored methodologies could be resolved from them yet.[/yellow]")
            return

        capability_summary = _summarize_new_capabilities(all_methodologies)
        opportunities = _infer_feature_opportunities(
            all_methodologies,
            methodology_ids_with_templates=methodology_ids_with_templates,
            limit=max(3, min(6, latest if latest > 0 else 6)),
        )

        console.print(Panel.fit(
            f"[bold cyan]CAM Assimilation Delta[/bold cyan]\n"
            f"[bold]{len(repo_summaries)}[/bold] mined repo(s) in the last [bold]{since_hours:g}[/bold] hour(s)\n"
            f"[bold]{len(all_methodologies)}[/bold] methodology record(s) resolved from those mine runs\n"
            f"[bold]{sum(len(item['templates']) for item in repo_summaries)}[/bold] action template(s) created",
            border_style="cyan",
        ))

        summary = Table(title="Recently Mined Repos")
        summary.add_column("Repo", style="cyan", max_width=28)
        summary.add_column("Mined At", style="dim", width=18)
        summary.add_column("Meth", justify="right", width=6)
        summary.add_column("Tpl", justify="right", width=5)
        summary.add_column("Future", justify="right", width=7)
        summary.add_column("Top Domains", max_width=28)
        for item in repo_summaries:
            record = item["record"]
            methodologies = item["methodologies"]
            domains: dict[str, int] = {}
            for meth in methodologies:
                capability_data = getattr(meth, "capability_data", None) or {}
                if isinstance(capability_data, dict):
                    for domain in capability_data.get("domain", []) or []:
                        domains[str(domain)] = domains.get(str(domain), 0) + 1
            domain_str = ", ".join(name for name, _count in sorted(domains.items(), key=lambda x: (-x[1], x[0]))[:3]) or "-"
            summary.add_row(
                record.repo_name,
                datetime.fromtimestamp(record.last_mined_at, UTC).strftime("%Y-%m-%d %H:%M"),
                str(len(methodologies)),
                str(len(item["templates"])),
                str(len(item["future_candidates"])),
                domain_str,
            )
        console.print(summary)

        if capability_summary["domains"] or capability_summary["capability_types"]:
            cap_table = Table(title="New Capabilities Surfaced")
            cap_table.add_column("Kind", style="bold", width=16)
            cap_table.add_column("Top Items", max_width=76)
            if capability_summary["domains"]:
                cap_table.add_row(
                    "Domains",
                    ", ".join(f"{name} ({count})" for name, count in capability_summary["domains"][:8]),
                )
            if capability_summary["capability_types"]:
                cap_table.add_row(
                    "Capability types",
                    ", ".join(f"{name} ({count})" for name, count in capability_summary["capability_types"][:8]),
                )
            console.print(cap_table)

        if opportunities:
            opp_table = Table(title="Possible New Features / Updates")
            opp_table.add_column("Signal", style="cyan", width=16)
            opp_table.add_column("Weight", justify="right", width=6)
            opp_table.add_column("What CAM could operationalize next", max_width=72)
            for opp in opportunities:
                opp_table.add_row(opp["trigger"], str(opp["count"]), opp["description"])
            console.print(opp_table)

        top_methodologies = sorted(
            all_methodologies,
            key=lambda meth: (
                1 if meth.id in methodology_ids_with_templates else 0,
                getattr(meth, "potential_score", None) or 0,
                getattr(meth, "novelty_score", None) or 0,
                getattr(meth, "created_at", datetime.min.replace(tzinfo=UTC)),
            ),
            reverse=True,
        )

        top_limit = latest if latest > 0 else 10
        top_table = Table(title=f"New Methodologies / Operationalization Candidates ({min(len(top_methodologies), top_limit)})")
        top_table.add_column("ID", width=8)
        top_table.add_column("Repo", style="cyan", max_width=20)
        top_table.add_column("Description", max_width=40)
        top_table.add_column("Stage", width=17)
        top_table.add_column("Potential", justify="right", width=9)
        top_table.add_column("Novelty", justify="right", width=8)
        top_table.add_column("Triggers", max_width=26)
        for meth in top_methodologies[:top_limit]:
            template_count = 1 if meth.id in methodology_ids_with_templates else 0
            stage = _classify_assimilation_stage(meth, template_count=template_count)
            source_repo = next(
                (tag.split(":", 1)[1] for tag in getattr(meth, "tags", []) or [] if isinstance(tag, str) and tag.startswith("source:")),
                "-",
            )
            triggers = ", ".join(_derive_activation_triggers(meth, template_count=template_count)[:3]) or "-"
            top_table.add_row(
                meth.id[:8],
                source_repo,
                meth.problem_description[:40],
                stage,
                f"{(meth.potential_score or 0):.3f}",
                f"{(meth.novelty_score or 0):.3f}" if meth.novelty_score is not None else "-",
                triggers,
            )
        console.print(top_table)

        console.print(
            "\n[dim]Interpretation: this report answers 'what did the recent mine runs actually add?' "
            "Use 'cam assimilation-report' for lifecycle maturity and 'cam kb synergies' for cross-capability relationships.[/dim]"
        )

    finally:
        await engine.close()


async def _assimilation_report_async(limit: int, future_threshold: float) -> None:
    from rich.panel import Panel

    engine, repository = await _kb_engine()

    try:
        methods = await repository.list_methodologies(limit=5000, include_dead=False)
        if not methods:
            console.print("[yellow]No methodologies in knowledge base. Run 'cam mine <dir>' first.[/yellow]")
            return

        template_rows = await repository.engine.fetch_all(
            """SELECT source_methodology_id,
                      COUNT(*) as template_count,
                      COALESCE(SUM(success_count), 0) as template_successes,
                      COALESCE(SUM(failure_count), 0) as template_failures,
                      MAX(confidence) as max_confidence
               FROM action_templates
               WHERE source_methodology_id IS NOT NULL
               GROUP BY source_methodology_id"""
        )
        template_stats = {
            row["source_methodology_id"]: {
                "count": int(row["template_count"] or 0),
                "successes": int(row["template_successes"] or 0),
                "failures": int(row["template_failures"] or 0),
                "max_confidence": float(row["max_confidence"] or 0.0),
            }
            for row in template_rows
            if row.get("source_methodology_id")
        }
        usage_stats = await repository.get_methodology_usage_stats()

        stage_counts = {
            "stored": 0,
            "enriched": 0,
            "retrieved": 0,
            "operationalized": 0,
            "proven": 0,
        }
        future_candidates: list[Any] = []
        proven_items: list[Any] = []
        stored_items: list[Any] = []
        enriched_items: list[Any] = []
        operationalized_items: list[Any] = []

        for meth in methods:
            stats = template_stats.get(meth.id, {})
            usage = usage_stats.get(meth.id, {})
            template_count = int(stats.get("count", 0))
            template_successes = int(stats.get("successes", 0))
            stage = _classify_assimilation_stage(
                meth,
                template_count=template_count,
                template_successes=template_successes,
                usage_stats=usage,
            )
            stage_counts[stage] += 1

            if _is_future_candidate(
                meth,
                potential_threshold=future_threshold,
                template_count=template_count,
                usage_stats=usage,
            ):
                future_candidates.append((meth, template_count, template_successes, usage))

            if stage == "proven":
                proven_items.append((meth, template_count, template_successes, usage))
            elif stage == "stored":
                stored_items.append((meth, template_count, template_successes, usage))
            elif stage == "enriched":
                enriched_items.append((meth, template_count, template_successes, usage))
            elif stage == "operationalized":
                operationalized_items.append((meth, template_count, template_successes, usage))

        future_candidates.sort(key=lambda x: ((x[0].potential_score or 0), (x[0].novelty_score or 0)), reverse=True)
        proven_items.sort(
            key=lambda x: (
                x[0].success_count + x[2] + int((x[3] or {}).get("attributed_success_count", 0) or 0),
                int((x[3] or {}).get("used_count", 0) or 0),
                x[0].retrieval_count,
            ),
            reverse=True,
        )
        stored_items.sort(key=lambda x: x[0].created_at, reverse=True)
        enriched_items.sort(key=lambda x: ((x[0].potential_score or 0), (x[0].novelty_score or 0)), reverse=True)
        operationalized_items.sort(
            key=lambda x: (x[1], int((x[3] or {}).get("used_count", 0) or 0), x[0].retrieval_count),
            reverse=True,
        )

        console.print(Panel.fit(
            f"[bold cyan]CAM Assimilation Continuum[/bold cyan]\n"
            f"[bold]{len(methods):,}[/bold] active methodologies tracked across the learning continuum",
            border_style="cyan",
        ))

        summary = Table(title="Continuum Stages")
        summary.add_column("Stage", style="bold", width=18)
        summary.add_column("Count", justify="right", width=8)
        summary.add_column("Meaning", max_width=52)
        summary.add_row("stored", str(stage_counts["stored"]), "Filed in memory, not yet enriched or retrieved")
        summary.add_row("enriched", str(stage_counts["enriched"]), "Structured metadata exists, but not yet in active use")
        summary.add_row("retrieved", str(stage_counts["retrieved"]), "CAM is pulling it back during later work")
        summary.add_row("operationalized", str(stage_counts["operationalized"]), "Turned into executable action template(s)")
        summary.add_row("proven", str(stage_counts["proven"]), "Has actual success signal from use")
        console.print(summary)

        console.print(
            f"\n[bold]Future candidates:[/bold] {len(future_candidates)} "
            f"[dim](potential >= {future_threshold:.2f}, no direct success yet)[/dim]"
        )

        if future_candidates:
            future_table = Table(title=f"Top Future Candidates ({min(limit, len(future_candidates))})")
            future_table.add_column("ID", width=8)
            future_table.add_column("Description", max_width=44)
            future_table.add_column("Potential", justify="right", width=9, style="bold cyan")
            future_table.add_column("Novelty", justify="right", width=8, style="yellow")
            future_table.add_column("Domains", max_width=24)
            for meth, template_count, _, usage in future_candidates[:limit]:
                domains = ", ".join(((meth.capability_data or {}).get("domain", [])[:3]))
                expect = usage.get("avg_expectation_match_score")
                future_table.add_row(
                    meth.id[:8],
                    meth.problem_description[:44],
                    f"{(meth.potential_score or 0):.3f}",
                    f"{(meth.novelty_score or 0):.3f}" if meth.novelty_score is not None else "-",
                    domains or (
                        "expect:" + f"{float(expect):.2f}" if expect is not None else ("templates:" + str(template_count) if template_count else "-")
                    ),
                )
            console.print(future_table)

        def _print_stage_table(title: str, items: list[Any], *, score_label: str = "") -> None:
            if not items:
                return
            table = Table(title=title)
            table.add_column("ID", width=8)
            table.add_column("Description", max_width=44)
            table.add_column("Retr", justify="right", width=6)
            table.add_column("Succ", justify="right", width=6)
            table.add_column("Used", justify="right", width=6)
            table.add_column("Exp", justify="right", width=6)
            table.add_column("Tpl", justify="right", width=5)
            if score_label:
                table.add_column(score_label, justify="right", width=9)
            for meth, template_count, template_successes, usage in items[:limit]:
                used_count = int((usage or {}).get("used_count", 0) or 0)
                expectation_score = (usage or {}).get("avg_expectation_match_score")
                row = [
                    meth.id[:8],
                    meth.problem_description[:44],
                    str(meth.retrieval_count),
                    str(meth.success_count + template_successes + int((usage or {}).get("attributed_success_count", 0) or 0)),
                    str(used_count),
                    "-" if expectation_score is None else f"{float(expectation_score):.2f}",
                    str(template_count),
                ]
                if score_label == "Potential":
                    row.append(f"{(meth.potential_score or 0):.3f}")
                elif score_label == "Novelty":
                    row.append(f"{(meth.novelty_score or 0):.3f}")
                table.add_row(*row)
            console.print(table)

        _print_stage_table("Proven Use", proven_items, score_label="Potential")
        _print_stage_table("Operationalized But Not Proven", operationalized_items, score_label="Potential")
        _print_stage_table("Enriched But Not Yet Used", enriched_items, score_label="Potential")
        _print_stage_table("Stored Only", stored_items)

        console.print(
            "\n[dim]Interpretation: stored -> enriched -> retrieved -> operationalized -> proven. "
            "Future-candidate is an orthogonal flag for capabilities CAM should keep reconsidering.[/dim]"
        )

    finally:
        await engine.close()


async def _reassess_async(
    repo: Optional[str],
    task: str,
    limit: int,
    min_score: float,
    future_threshold: float,
) -> None:
    from rich.panel import Panel

    repo_tokens: set[str] = set()
    repo_summary: Optional[dict[str, Any]] = None
    if repo:
        repo_path = Path(repo).resolve()
        if not repo_path.exists():
            console.print(f"[red]Repository path does not exist: {repo_path}[/red]")
            raise typer.Exit(1)
        repo_summary = _summarize_repo_tree(repo_path)
        repo_tokens = _tokenize_reassessment_text(
            " ".join(
                repo_summary.get("marker_files", [])
                + repo_summary.get("top_dirs", [])
                + repo_summary.get("sample_files", [])
            )
        )

    task_tokens = _tokenize_reassessment_text(task)
    if not task_tokens and not repo_tokens:
        console.print("[red]Task is too vague for reassessment. Provide a more specific --task.[/red]")
        raise typer.Exit(1)
    expectation_contract = _build_reassessment_expectation_contract(task, repo_summary)
    expectation_tokens = _tokenize_reassessment_text(
        " ".join(
            [expectation_contract.get("goal", "")]
            + list(expectation_contract.get("expected_outcome", []) or [])
            + list(expectation_contract.get("expected_ux", []) or [])
            + list(expectation_contract.get("constraints", []) or [])
        )
    )

    engine, repository = await _kb_engine()

    try:
        methods = await repository.list_methodologies(limit=5000, include_dead=False)
        if not methods:
            console.print("[yellow]No methodologies in knowledge base. Run 'cam mine <dir>' first.[/yellow]")
            return

        template_rows = await repository.engine.fetch_all(
            """SELECT source_methodology_id,
                      COUNT(*) as template_count,
                      COALESCE(SUM(success_count), 0) as template_successes
               FROM action_templates
               WHERE source_methodology_id IS NOT NULL
               GROUP BY source_methodology_id"""
        )
        template_stats = {
            row["source_methodology_id"]: {
                "count": int(row["template_count"] or 0),
                "successes": int(row["template_successes"] or 0),
            }
            for row in template_rows
            if row.get("source_methodology_id")
        }
        usage_stats = await repository.get_methodology_usage_stats()

        recommendations: list[dict[str, Any]] = []
        future_watchlist: list[dict[str, Any]] = []
        for meth in methods:
            stats = template_stats.get(meth.id, {})
            template_count = int(stats.get("count", 0))
            template_successes = int(stats.get("successes", 0))
            score, reasons, triggers = _score_methodology_for_task(
                meth,
                task_tokens=task_tokens,
                repo_tokens=repo_tokens,
                expectation_tokens=expectation_tokens,
                template_count=template_count,
                template_successes=template_successes,
                usage_stats=usage_stats.get(meth.id),
            )
            stage = _classify_assimilation_stage(
                meth,
                template_count=template_count,
                template_successes=template_successes,
            )
            payload = {
                "methodology": meth,
                "score": score,
                "reasons": reasons,
                "triggers": triggers,
                "stage": stage,
                "template_count": template_count,
                "template_successes": template_successes,
            }
            if score >= min_score:
                recommendations.append(payload)
            elif _is_future_candidate(meth, potential_threshold=future_threshold, template_count=template_count):
                future_watchlist.append(payload)

        recommendations.sort(
            key=lambda x: (
                x["score"],
                (usage_stats.get(x["methodology"].id, {}) or {}).get("attributed_success_count", 0),
                x["methodology"].success_count + x["template_successes"],
                x["methodology"].retrieval_count,
                x["methodology"].potential_score or 0,
            ),
            reverse=True,
        )
        future_watchlist.sort(
            key=lambda x: (
                x["methodology"].potential_score or 0,
                x["methodology"].novelty_score or 0,
            ),
            reverse=True,
        )

        console.print(Panel.fit(
            f"[bold cyan]CAM Reassess[/bold cyan]\n"
            f"Task: {task}\n"
            f"Repo context: {repo_summary['name'] if repo_summary else 'none'}",
            border_style="cyan",
        ))
        console.print(
            f"[dim]Expectation focus:[/dim] "
            f"{'; '.join(expectation_contract.get('expected_outcome', [])[:2] + expectation_contract.get('expected_ux', [])[:1])}"
        )

        if repo_summary:
            console.print(
                f"[dim]Repo markers:[/dim] {', '.join(repo_summary.get('marker_files', [])[:6]) or '-'}"
            )

        if recommendations:
            table = Table(title=f"Recommended Now ({min(limit, len(recommendations))})")
            table.add_column("ID", width=8)
            table.add_column("Stage", width=16)
            table.add_column("Score", justify="right", width=7, style="bold green")
            table.add_column("Description", max_width=36)
            table.add_column("Why Now", max_width=36)
            table.add_column("Triggers", max_width=22)
            for item in recommendations[:limit]:
                meth = item["methodology"]
                table.add_row(
                    meth.id[:8],
                    item["stage"],
                    f"{item['score']:.2f}",
                    meth.problem_description[:36],
                    "; ".join(item["reasons"][:2])[:36],
                    ", ".join(item["triggers"][:3])[:22] or "-",
                )
            console.print(table)
        else:
            console.print("[yellow]No methodologies cleared the reassessment score threshold.[/yellow]")

        if future_watchlist:
            watch = Table(title=f"Future Watchlist ({min(limit, len(future_watchlist))})")
            watch.add_column("ID", width=8)
            watch.add_column("Potential", justify="right", width=9, style="bold cyan")
            watch.add_column("Description", max_width=40)
            watch.add_column("Triggers", max_width=24)
            for item in future_watchlist[:limit]:
                meth = item["methodology"]
                watch.add_row(
                    meth.id[:8],
                    f"{(meth.potential_score or 0):.3f}",
                    meth.problem_description[:40],
                    ", ".join(item["triggers"][:4])[:24] or "-",
                )
            console.print(watch)

        console.print(
            "\n[dim]Use this command when a new task arrives and you want CAM to reactivate prior knowledge "
            "based on current fit, not just historical storage.[/dim]"
        )

    finally:
        await engine.close()


async def _synergies_async(verbose: bool) -> None:
    """Display synergy stats and graph summary."""
    from rich.panel import Panel
    from claw.core.config import DatabaseConfig, load_config
    from claw.db.engine import DatabaseEngine
    from claw.db.repository import Repository

    config = load_config()
    engine = DatabaseEngine(config.database)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    repository = Repository(engine)

    try:
        # Synergy exploration stats
        stats = await repository.get_synergy_stats()
        console.print(Panel.fit(
            "[bold cyan]Capability Synergy Graph[/bold cyan]",
            border_style="cyan",
        ))

        table = Table(title="Exploration Stats")
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")
        table.add_row("Total explored pairs", str(stats["total_explored"]))
        for result_type, count in stats.get("by_result", {}).items():
            table.add_row(f"  {result_type}", str(count))
        table.add_row("Avg synergy score", f"{stats['avg_synergy_score']:.4f}")
        table.add_row("Synergy edges", str(stats["synergy_edges"]))
        console.print(table)

        # Capabilities with data
        with_caps = await repository.get_methodologies_with_capabilities()
        without_caps = await repository.get_methodologies_without_capability_data()
        console.print(f"\nCapabilities enriched: [bold]{len(with_caps)}[/bold]")
        console.print(f"Capabilities unenriched: [bold]{len(without_caps)}[/bold]")

        if verbose and with_caps:
            cap_table = Table(title="Enriched Capabilities")
            cap_table.add_column("ID", width=8)
            cap_table.add_column("Problem", width=40)
            cap_table.add_column("Type", width=15)
            cap_table.add_column("Domain")
            for m in with_caps[:20]:
                cd = m.capability_data or {}
                cap_table.add_row(
                    m.id[:8],
                    m.problem_description[:40],
                    cd.get("capability_type", "?"),
                    ", ".join(cd.get("domain", [])[:3]),
                )
            console.print(cap_table)

    finally:
        await engine.close()


# ---------------------------------------------------------------------------
# Grouped workflow aliases
# ---------------------------------------------------------------------------


@learn_app.command(name="report")
def learn_report(
    limit: int = typer.Option(10, "--limit", "-n", help="Rows to show per section"),
    future_threshold: float = typer.Option(0.65, "--future-threshold", help="Potential score threshold for future-candidate flag"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Preferred grouped alias for `cam assimilation-report`."""
    assimilation_report(limit=limit, future_threshold=future_threshold, config=config)


@learn_app.command(name="delta")
def learn_delta(
    directory: Optional[str] = typer.Argument(None, help="Optional repo directory to scope the report"),
    depth: int = typer.Option(6, "--depth", "-d", help="Max directory depth when scoping by directory"),
    dedup: bool = typer.Option(True, "--dedup/--no-dedup", help="Dedup repo iterations by canonical name"),
    since_hours: float = typer.Option(24.0, "--since-hours", help="Only include repos mined within this many hours"),
    latest: int = typer.Option(10, "--latest", "-n", help="Maximum recently mined repos/methodologies to summarize"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Preferred grouped alias for `cam assimilation-delta`."""
    assimilation_delta(
        directory=directory,
        depth=depth,
        dedup=dedup,
        since_hours=since_hours,
        latest=latest,
        config=config,
    )


@learn_app.command(name="reassess")
def learn_reassess(
    repo: Optional[str] = typer.Argument(None, help="Optional repository path for additional context"),
    task: str = typer.Option(..., "--task", "-t", help="Task or goal CAM should reassess prior knowledge against"),
    limit: int = typer.Option(10, "--limit", "-n", help="Maximum recommendations to show"),
    min_score: float = typer.Option(0.2, "--min-score", help="Minimum reassessment score to show"),
    future_threshold: float = typer.Option(0.65, "--future-threshold", help="Potential score threshold for future-candidate flag"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Preferred grouped alias for `cam reassess`."""
    reassess(
        repo=repo,
        task=task,
        limit=limit,
        min_score=min_score,
        future_threshold=future_threshold,
        config=config,
    )


@learn_app.command(name="synergies")
def learn_synergies(
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Show detailed edge list"),
    config: Optional[str] = typer.Option(None, "--config", help="Path to claw.toml"),
) -> None:
    """Preferred grouped alias for `cam synergies`."""
    synergies(verbose=verbose, config=config)


@learn_app.command(name="usage")
def learn_usage(
    task_id: str = typer.Argument(..., help="Task ID to inspect methodology attribution for"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Show retrieved and attributed methodologies for a task."""
    _setup_logging(False)
    asyncio.run(_learn_usage_async(task_id, config))


@learn_app.command(name="search")
def learn_search(
    query: str = typer.Argument(..., help="Natural language search query"),
    limit: int = typer.Option(10, "--limit", "-n", help="Maximum results"),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Show detailed scores"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Semantic search across all learned methodologies."""
    _setup_logging(verbose)
    asyncio.run(_learn_search_async(query, limit, verbose, config))


@learn_app.command(name="backfill-components")
def learn_backfill_components(
    methodology_id: list[str] = typer.Option(
        None,
        "--methodology-id",
        help="Specific methodology ID(s) to backfill; omit to scan methodologies with capability_data",
    ),
    limit: int = typer.Option(100, "--limit", "-n", help="Maximum methodologies to inspect when no IDs are provided"),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Backfill component cards from existing methodologies and capability metadata."""
    _setup_logging(verbose)
    asyncio.run(_learn_backfill_components_async(methodology_id or None, limit, config))


async def _learn_backfill_components_async(
    methodology_ids: Optional[list[str]],
    limit: int,
    config_path: Optional[str],
) -> None:
    from claw.core.factory import ClawFactory

    ctx = await ClawFactory.create(config_path=Path(config_path) if config_path else None)
    try:
        summary = await ctx.miner.backfill_components(
            methodology_ids=methodology_ids,
            limit=limit,
            repository=ctx.repository,
        )
        console.print("\n[bold]CAM-SEQ Component Backfill[/bold]")
        console.print(f"  Methodologies scanned: [bold]{summary.get('methodologies', 0)}[/bold]")
        console.print(f"  Components created:    [green]{summary.get('created', 0)}[/green]")
        console.print(f"  Components updated:    [cyan]{summary.get('updated', 0)}[/cyan]")
        console.print(f"  Components skipped:    [yellow]{summary.get('skipped', 0)}[/yellow]")
        skip_reasons = summary.get("skip_reasons", []) or []
        if skip_reasons:
            console.print("\n[bold]Skip Reasons[/bold]")
            for item in skip_reasons[:20]:
                console.print(
                    f"  - {item.get('methodology_id', '?')[:8]}: {item.get('reason', 'unknown')}"
                )
    finally:
        await ctx.close()


@learn_app.command(name="proof")
def learn_proof(
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum methodologies to show"),
    json_output: bool = typer.Option(False, "--json", help="Output as machine-readable JSON"),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Show system-wide attribution proof: retrieved -> applied -> succeeded funnel."""
    _setup_logging(verbose)
    asyncio.run(_learn_proof_async(limit, json_output, config))


async def _learn_proof_async(
    limit: int, json_output: bool, config_path: Optional[str]
) -> None:
    import json as json_mod

    from claw.core.factory import ClawFactory

    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p)

    try:
        usage_stats = await ctx.repository.get_methodology_usage_stats()
        methods = await ctx.repository.list_methodologies(limit=5000, include_dead=True)
        method_map = {m.id: m for m in methods}

        # Aggregate the system-wide funnel
        total_retrieved = 0
        total_applied = 0
        total_success = 0
        total_failure = 0
        never_applied: list[dict] = []
        per_methodology: list[dict] = []

        for meth_id, stats in usage_stats.items():
            retrieved = int(stats.get("retrieved_count", 0))
            applied = int(stats.get("used_count", 0))
            success = int(stats.get("attributed_success_count", 0))
            failure = int(stats.get("attributed_failure_count", 0))

            total_retrieved += retrieved
            total_applied += applied
            total_success += success
            total_failure += failure

            meth = method_map.get(meth_id)
            title = meth.problem_description[:80].replace("\n", " ").replace("\r", "") if meth else meth_id[:8]
            lifecycle = meth.lifecycle_state if meth else "unknown"
            source_tag = "-"
            if meth:
                source_tag = next(
                    (t.split(":", 1)[1] for t in (meth.tags or []) if t.startswith("source:")),
                    "-",
                )

            entry = {
                "methodology_id": meth_id,
                "title": title,
                "lifecycle": lifecycle,
                "source": source_tag,
                "retrieved": retrieved,
                "applied": applied,
                "success": success,
                "failure": failure,
                "applied_rate": applied / retrieved if retrieved > 0 else 0.0,
                "success_rate": success / applied if applied > 0 else 0.0,
                "avg_quality": stats.get("avg_quality_score"),
                "avg_relevance": stats.get("avg_relevance_score"),
            }
            per_methodology.append(entry)

            if retrieved > 0 and applied == 0:
                never_applied.append(entry)

        # Sort by total usage (retrieved desc)
        per_methodology.sort(key=lambda e: e["retrieved"], reverse=True)

        applied_rate = total_applied / total_retrieved if total_retrieved > 0 else 0.0
        success_rate = total_success / total_applied if total_applied > 0 else 0.0
        overall_conversion = total_success / total_retrieved if total_retrieved > 0 else 0.0

        proof_data = {
            "funnel": {
                "total_retrieved": total_retrieved,
                "total_applied": total_applied,
                "total_success": total_success,
                "total_failure": total_failure,
                "applied_rate": round(applied_rate, 4),
                "success_rate": round(success_rate, 4),
                "overall_conversion": round(overall_conversion, 4),
            },
            "methodology_count": len(usage_stats),
            "never_applied_count": len(never_applied),
            "per_methodology": per_methodology[:limit],
            "never_applied": never_applied[:limit],
        }

        if json_output:
            print(json_mod.dumps(proof_data, indent=2, default=str))
            return

        # Rich table output
        console.print("\n[bold]CAM Attribution Proof — System-Wide Funnel[/bold]")
        console.print(
            f"\n  Methodologies tracked: [bold]{len(usage_stats)}[/bold]"
        )
        console.print(
            f"  Retrieved: [cyan]{total_retrieved}[/cyan]  →  "
            f"Applied: [yellow]{total_applied}[/yellow] ({applied_rate:.1%})  →  "
            f"Success: [green]{total_success}[/green] ({success_rate:.1%})"
        )
        if total_failure > 0:
            console.print(f"  Failures: [red]{total_failure}[/red]")
        console.print(
            f"  Overall conversion (retrieved → success): [bold]{overall_conversion:.1%}[/bold]"
        )

        if per_methodology:
            console.print(f"\n[bold]Top {min(limit, len(per_methodology))} Methodologies by Usage[/bold]")
            table = Table(show_lines=True)
            table.add_column("Methodology", style="cyan", max_width=48)
            table.add_column("ID", width=8)
            table.add_column("State", width=10)
            table.add_column("Retrieved", justify="right")
            table.add_column("Applied", justify="right")
            table.add_column("Success", justify="right")
            table.add_column("Apply%", justify="right")
            table.add_column("Succ%", justify="right")

            for entry in per_methodology[:limit]:
                a_rate = f"{entry['applied_rate']:.0%}" if entry["retrieved"] > 0 else "-"
                s_rate = f"{entry['success_rate']:.0%}" if entry["applied"] > 0 else "-"
                table.add_row(
                    entry["title"][:48],
                    entry["methodology_id"][:8],
                    entry["lifecycle"],
                    str(entry["retrieved"]),
                    str(entry["applied"]),
                    str(entry["success"]),
                    a_rate,
                    s_rate,
                )

            console.print()
            console.print(table)

        if never_applied:
            console.print(f"\n[yellow]Never Applied ({len(never_applied)} methodologies retrieved but never used):[/yellow]")
            for entry in never_applied[:10]:
                console.print(f"  - {entry['title'][:60]}  (retrieved {entry['retrieved']}x)")

    finally:
        await ctx.close()


@learn_app.command(name="ingest-codex-outcomes")
def learn_ingest_codex_outcomes(
    outcome_db: Optional[str] = typer.Option(
        None,
        "--outcome-db",
        help="Path to codex_outcome_log.db; defaults to ~/.cam_codex_mcp/codex_outcome_log.db",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would be ingested without writing"),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Consume rows from codex_outcome_log and push them into the CAM_CAM corpus.

    Reads unprocessed rows from the MCP outcome staging table and calls
    semantic_memory.record_outcome() for each methodology_id referenced.
    Idempotent: already-ingested row IDs are tracked in claw.db.
    """
    _setup_logging(verbose)
    asyncio.run(_learn_ingest_codex_outcomes_async(outcome_db, dry_run, verbose, config))


INGEST_TRACKING_DDL = """
CREATE TABLE IF NOT EXISTS codex_outcome_ingested (
    row_id      TEXT PRIMARY KEY,
    ingested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    methodology_ids TEXT NOT NULL,
    outcome     TEXT NOT NULL
);
"""


async def _learn_ingest_codex_outcomes_async(
    outcome_db_path: Optional[str],
    dry_run: bool,
    verbose: bool,
    config_path: Optional[str],
) -> None:
    import json as json_mod
    import sqlite3 as _sqlite3
    from pathlib import Path as _Path

    from claw.core.factory import ClawFactory

    # Resolve outcome DB path
    if outcome_db_path:
        src_path = _Path(outcome_db_path).expanduser().resolve()
    else:
        src_path = _Path("~/.cam_codex_mcp/codex_outcome_log.db").expanduser()

    if not src_path.exists():
        console.print(f"[red]Outcome DB not found: {src_path}[/red]")
        raise typer.Exit(1)

    config_p = _Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p)

    try:
        primary_db_path = _Path(ctx.config.database.db_path).resolve()

        # Ensure the tracking table exists in claw.db
        with _sqlite3.connect(str(primary_db_path)) as tracking_conn:
            tracking_conn.executescript(INGEST_TRACKING_DDL)

        # Read all rows from codex_outcome_log
        with _sqlite3.connect(str(src_path)) as src_conn:
            src_conn.row_factory = _sqlite3.Row
            rows = src_conn.execute(
                "SELECT id, methodology_ids, outcome, task_id, repo, ts FROM codex_outcome_log ORDER BY ts ASC"
            ).fetchall()

        if not rows:
            console.print("[yellow]codex_outcome_log is empty — nothing to ingest.[/yellow]")
            return

        # Identify already-ingested IDs
        with _sqlite3.connect(str(primary_db_path)) as tracking_conn:
            already_done = {
                r[0]
                for r in tracking_conn.execute("SELECT row_id FROM codex_outcome_ingested").fetchall()
            }

        pending = [r for r in rows if r["id"] not in already_done]

        console.print(
            f"\n[bold]CAM Learn — Ingest Codex Outcomes[/bold]\n"
            f"  Source: {src_path}\n"
            f"  Total rows: {len(rows)} | already ingested: {len(already_done)} | pending: {len(pending)}"
        )

        if not pending:
            console.print("[green]All rows already ingested. Nothing to do.[/green]")
            return

        if dry_run:
            console.print("[yellow]Dry run — no writes will occur.[/yellow]")

        semantic_memory = ctx.semantic_memory
        ingested = 0
        skipped = 0
        errors = 0

        for row in pending:
            row_id = row["id"]
            raw_ids = row["methodology_ids"]
            outcome_val = row["outcome"]

            try:
                meth_ids: list[str] = json_mod.loads(raw_ids) if raw_ids else []
            except Exception:
                meth_ids = [raw_ids] if raw_ids else []

            if not meth_ids:
                skipped += 1
                continue

            # green=success, all others (red, partial, rejected)=failure
            success = outcome_val == "green"

            if not dry_run:
                row_errors = 0
                for mid in meth_ids:
                    try:
                        await semantic_memory.record_outcome(
                            methodology_id=mid,
                            success=success,
                            retrieval_relevance=0.5,
                        )
                    except Exception as exc:
                        logger.warning("record_outcome failed for %s: %s", mid, exc)
                        row_errors += 1
                errors += row_errors

                if row_errors == 0:
                    # Mark row as ingested only when all method calls succeeded
                    with _sqlite3.connect(str(primary_db_path)) as tracking_conn:
                        tracking_conn.execute(
                            "INSERT OR IGNORE INTO codex_outcome_ingested (row_id, methodology_ids, outcome) VALUES (?, ?, ?)",
                            (row_id, raw_ids, outcome_val),
                        )

            ingested += 1
            if verbose:
                ids_preview = ", ".join(meth_ids[:3])
                if len(meth_ids) > 3:
                    ids_preview += f" +{len(meth_ids) - 3} more"
                console.print(
                    f"  [{'green' if success else 'red'}]{'PASS' if success else 'FAIL'}[/{'green' if success else 'red'}] "
                    f"{row_id[:8]}  {ids_preview}"
                )

        action = "Would ingest" if dry_run else "Ingested"
        console.print(
            f"\n[bold green]{action}: {ingested}[/bold green]  "
            f"skipped (no IDs): {skipped}  "
            f"errors: {errors}"
        )

    finally:
        await ctx.close()


async def _learn_search_async(
    query: str, limit: int, verbose: bool, config_path: Optional[str]
) -> None:
    from claw.core.factory import ClawFactory

    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p)

    try:
        hs = ctx.semantic_memory.hybrid_search
        results = await hs.search(query, limit=limit)

        if not results:
            console.print(f"[yellow]No methodologies matched: {query!r}[/yellow]")
            return

        console.print(f"\n[bold]CAM Knowledge Search[/bold]: {query!r}")
        console.print(f"  {len(results)} result(s)\n")

        table = Table(show_lines=True)
        table.add_column("#", width=3, justify="right")
        table.add_column("Description", max_width=52)
        table.add_column("Score", width=6, justify="right")
        table.add_column("Source", max_width=28)
        table.add_column("Domains", max_width=30)
        if verbose:
            table.add_column("Vec", width=5, justify="right")
            table.add_column("Txt", width=5, justify="right")
            table.add_column("Stage", width=12)

        for i, r in enumerate(results, 1):
            m = r.methodology
            source = next(
                (tag.split(":", 1)[1] for tag in (m.tags or []) if tag.startswith("source:")),
                "-",
            )
            cd = m.capability_data or {}
            domains = ", ".join(cd.get("domain", [])[:3]) if cd else "-"
            desc = m.problem_description[:52] if m.problem_description else "-"

            row = [
                str(i),
                desc,
                f"{r.combined_score:.3f}",
                source,
                domains,
            ]
            if verbose:
                row.extend([
                    f"{r.vector_score:.2f}",
                    f"{r.text_score:.2f}",
                    m.lifecycle_state or "-",
                ])
            table.add_row(*row)

        console.print(table)
    finally:
        await ctx.close()


@task_app.command(name="add")
def task_add(
    repo: str = typer.Argument(..., help="Path to the repository this goal is for"),
    title: str = typer.Option(..., "--title", "-t", prompt="Goal title", help="Short title for the goal"),
    description: str = typer.Option(
        ..., "--description", "-d", prompt="Goal description (what should the agent do?)",
        help="Detailed description of what should be accomplished",
    ),
    priority: str = typer.Option("medium", "--priority", "-p", help="Priority: critical, high, medium, low"),
    task_type: str = typer.Option(
        "analysis", "--type",
        help="Task type: analysis, testing, documentation, security, refactoring, bug_fix, architecture, dependency_analysis",
    ),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Preferred agent: claude, codex, gemini, grok"),
    step: list[str] = typer.Option([], "--step", help="Execution command to run for this goal (repeatable)"),
    check: list[str] = typer.Option([], "--check", help="Acceptance check command for this goal (repeatable)"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Preferred grouped alias for `cam add-goal`."""
    add_goal(
        repo=repo,
        title=title,
        description=description,
        priority=priority,
        task_type=task_type,
        agent=agent,
        step=step,
        check=check,
        config=config,
    )


@task_app.command(name="quickstart")
def task_quickstart(
    repo: str = typer.Argument(..., help="Path to the repository this goal is for"),
    title: str = typer.Option(..., "--title", "-t", prompt="Goal title", help="Short title for the goal"),
    description: str = typer.Option(
        ..., "--description", "-d", prompt="Goal description (what should be done?)",
        help="Detailed goal description",
    ),
    priority: str = typer.Option("high", "--priority", "-p", help="Priority: critical, high, medium, low"),
    task_type: str = typer.Option(
        "bug_fix",
        "--type",
        help="Task type: analysis, testing, documentation, security, refactoring, bug_fix, architecture, dependency_analysis",
    ),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Preferred agent: claude, codex, gemini, grok"),
    step: list[str] = typer.Option([], "--step", help="Execution command to run for this goal (repeatable)"),
    check: list[str] = typer.Option([], "--check", help="Acceptance check command for this goal (repeatable)"),
    preview: bool = typer.Option(True, "--preview/--no-preview", help="Show runbook and dry-run preview after creating the goal"),
    execute: bool = typer.Option(False, "--execute", help="Immediately execute this exact task after setup"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Preferred grouped alias for `cam quickstart`."""
    quickstart(
        repo=repo,
        title=title,
        description=description,
        priority=priority,
        task_type=task_type,
        agent=agent,
        step=step,
        check=check,
        preview=preview,
        execute=execute,
        config=config,
    )


@task_app.command(name="runbook")
def task_runbook(
    task_id: str = typer.Argument(..., help="Task ID to inspect"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Preferred grouped alias for `cam runbook`."""
    runbook(task_id=task_id, config=config)


@task_app.command(name="results")
def task_results(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of results to show"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Filter by project ID"),
) -> None:
    """Preferred grouped alias for `cam results`."""
    results(config=config, limit=limit, project=project)


@forge_app.command(name="export")
def forge_export_grouped(
    out: str = typer.Option("data/cam_knowledge_pack.jsonl", "--out", help="Output JSONL knowledge pack path"),
    db: Optional[str] = typer.Option(None, "--db", help="Override CAM database path"),
    max_methodologies: int = typer.Option(300, "--max-methodologies", help="Maximum methodologies to export"),
    max_tasks: int = typer.Option(300, "--max-tasks", help="Maximum tasks to export"),
    max_minutes: int = typer.Option(5, "--max-minutes", help="Wall-clock time guardrail for the export"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Preferred grouped alias for `cam forge-export`."""
    forge_export(
        out=out,
        db=db,
        max_methodologies=max_methodologies,
        max_tasks=max_tasks,
        max_minutes=max_minutes,
        verbose=verbose,
        config=config,
    )


@forge_app.command(name="benchmark")
def forge_benchmark_grouped(
    repo: str = typer.Option("tests/fixtures/embedding_forge/repo", "--repo", help="Fixture or target repo path"),
    note: str = typer.Option("tests/fixtures/embedding_forge/note.md", "--note", help="Note path"),
    knowledge_pack: str = typer.Option(
        "tests/fixtures/embedding_forge/knowledge_pack.jsonl",
        "--knowledge-pack",
        help="Knowledge pack JSONL path",
    ),
    out: str = typer.Option("data/forge_benchmark_fixture", "--out", help="Output benchmark directory"),
    max_minutes: int = typer.Option(5, "--max-minutes", help="Wall-clock time guardrail for the benchmark"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Preferred grouped alias for `cam forge-benchmark`."""
    forge_benchmark(
        repo=repo,
        note=note,
        knowledge_pack=knowledge_pack,
        out=out,
        max_minutes=max_minutes,
        verbose=verbose,
    )


@doctor_app.command(name="keycheck")
def doctor_keycheck(
    for_command: str = typer.Option("mine", "--for", help="Command to preflight: mine, ideate"),
    live: bool = typer.Option(False, "--live", help="Also validate the keys with a tiny real provider call"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Preferred grouped alias for `cam keycheck`."""
    keycheck(for_command=for_command, live=live, config=config)


@doctor_app.command(name="status")
def doctor_status(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Preferred grouped alias for `cam status`.

    Calls _status_async directly rather than the top-level `status`
    function, because `status` is re-bound later in the module by
    `@cag_app.command() def status(...)` (Python namespace shadowing).
    """
    _setup_logging(False)
    asyncio.run(_status_async(config))


@doctor_app.command(name="expectations")
def doctor_expectations(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Show whether the current runtime satisfies CAM's core product expectations."""
    _setup_logging(False)
    asyncio.run(_expectations_async(config))


@doctor_app.command(name="audit")
def doctor_audit(
    limit: int = typer.Option(10, "--limit", min=1, help="Max flagged methodologies to show"),
    expectation_threshold: float = typer.Option(
        0.65,
        "--expectation-threshold",
        min=0.0,
        max=1.0,
        help="Minimum expectation-match score for high-trust methodologies",
    ),
    json_out: Optional[str] = typer.Option(
        None,
        "--json-out",
        help="Write a machine-readable JSON summary to this path",
    ),
    fail_on_flags: bool = typer.Option(
        False,
        "--fail-on-flags",
        help="Exit nonzero when flagged methodologies are found",
    ),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Audit high-trust methodologies for attribution-backed evidence quality."""
    _setup_logging(False)
    asyncio.run(
        _doctor_audit_async(
            limit=limit,
            expectation_threshold=expectation_threshold,
            config_path=config,
            json_out=json_out,
            fail_on_flags=fail_on_flags,
        )
    )


@doctor_app.command(name="routing")
def doctor_routing(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Show Kelly routing weights for all agents per task type."""
    _setup_logging(False)
    asyncio.run(_doctor_routing_async(config_path=config))


async def _doctor_routing_async(config_path: Optional[str]) -> None:
    from claw.core.config import load_config
    from claw.db.engine import DatabaseEngine
    from claw.db.repository import Repository
    from claw.evolution.kelly import BayesianKellySizer

    cfg = load_config(Path(config_path) if config_path else None)

    if not cfg.kelly.enabled:
        console.print("[yellow]Kelly routing is disabled in claw.toml.[/yellow]")
        console.print("Enable with: [bold]kelly.enabled = true[/bold]")
        return

    engine = DatabaseEngine(cfg.database)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    repository = Repository(engine)

    try:
        rows = await repository.get_agent_scores()
        if not rows:
            console.print(
                "[yellow]Cold-start mode:[/yellow] no agent_scores data yet."
            )
            console.print(
                "  [dim]The dispatcher is falling back to static routing priors "
                "until agents have historical performance data.[/dim]"
            )
            console.print(
                "  [dim]Run a few tasks ([bold]cam create[/bold], "
                "[bold]cam quickstart[/bold], or [bold]cam evaluate[/bold]) "
                "to warm up Kelly routing.[/dim]"
            )
            return

        # Cold-start warning for under-sampled agents (punch list #4)
        cold_agents = [
            r for r in rows
            if r.get("total_attempts", r.get("successes", 0) + r.get("failures", 0)) < 5
        ]
        if cold_agents:
            count = len(cold_agents)
            console.print(
                f"[yellow]Warning:[/yellow] {count} agent-task combo(s) "
                f"have <5 attempts. Kelly sizing is unreliable at low sample "
                f"count — expect static fallback for those rows.\n"
            )

        sizer = BayesianKellySizer(
            kappa=cfg.kelly.kappa,
            f_max=cfg.kelly.f_max,
            prior_alpha=cfg.kelly.prior_alpha,
            prior_beta=cfg.kelly.prior_beta,
        )

        table = Table(title="Kelly Routing Weights")
        table.add_column("task_type", style="cyan")
        table.add_column("agent", style="bold")
        table.add_column("samples", justify="right")
        table.add_column("win_rate", justify="right")
        table.add_column("kelly_fraction", justify="right", style="green")
        table.add_column("posterior_std", justify="right", style="dim")

        for row in sorted(rows, key=lambda r: (r.get("task_type", ""), r.get("agent_id", ""))):
            successes = row.get("successes", 0)
            failures = row.get("failures", 0)
            total = row.get("total_attempts", successes + failures)
            avg_quality = row.get("avg_quality_score", 0.5)
            avg_cost = row.get("avg_cost_usd", 0.0)

            result = sizer.compute_fraction(
                successes=successes,
                failures=failures,
                avg_quality_score=avg_quality,
                avg_cost_usd=avg_cost,
            )

            table.add_row(
                row.get("task_type", "?"),
                row.get("agent_id", "?"),
                str(total),
                f"{result.p_bar:.3f}",
                f"{result.fraction:.4f}",
                f"{result.posterior_std:.4f}",
            )

        console.print(table)
        console.print(f"\n[dim]kappa={cfg.kelly.kappa}  f_max={cfg.kelly.f_max}  prior=Beta({cfg.kelly.prior_alpha}, {cfg.kelly.prior_beta})[/dim]")
    finally:
        await engine.close()


@app.command(name="prism-demo", hidden=True)
def prism_demo(
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Show detailed diagnostics"),
    config: Optional[str] = typer.Option(None, "--config", help="Path to claw.toml"),
):
    """Demonstrate PRISM multi-scale embeddings with non-base-10 math."""
    _setup_logging(verbose)
    asyncio.run(_prism_demo_async(verbose))


async def _prism_demo_async(verbose: bool) -> None:
    """Run the PRISM demonstration."""
    import numpy as np
    from rich.panel import Panel
    from claw.embeddings.prism import PrismEngine, PrismEmbedding
    import hashlib

    console.print(Panel.fit(
        "[bold cyan]PRISM[/bold cyan] — P-adic Residue Informed Stochastic Multi-scale Embeddings\n"
        "[dim]Non-base-10 embedding methodology for hierarchical, fault-tolerant, uncertainty-aware similarity[/dim]",
        border_style="cyan",
    ))

    # Use deterministic embedding engine (SHA-384 hash → 384-dim)
    class DemoEmbeddingEngine:
        DIMENSION = 384
        def encode(self, text: str) -> list[float]:
            h = hashlib.sha384(text.encode()).digest()
            raw = [b / 255.0 for b in h] * 8
            return raw[:self.DIMENSION]

    embedding_engine = DemoEmbeddingEngine()
    engine = PrismEngine(embedding_engine=embedding_engine)

    # Sample methodology descriptions with lifecycle states
    samples = [
        ("Refactoring database queries for performance", "thriving"),
        ("Optimizing SQL query execution plans", "thriving"),
        ("Adding JWT authentication to REST API", "viable"),
        ("Implementing OAuth2 flow for user login", "viable"),
        ("Experimental neural code search prototype", "embryonic"),
        ("Legacy XML parser migration to JSON", "declining"),
        ("Deprecated SOAP endpoint removal", "dormant"),
    ]

    # 1. Encode all samples with PRISM
    console.print("\n[bold]1. Encoding samples with PRISM[/bold]")
    embeddings = []
    for text, lifecycle in samples:
        emb = engine.encode_and_enhance(text, {"lifecycle_state": lifecycle})
        embeddings.append((text, lifecycle, emb))
        if verbose:
            console.print(f"  [dim]{lifecycle:10s}[/dim] κ={emb.vmf_kappa:5.1f}  tree={emb.padic_tree}  {text[:50]}")

    # 2. Pairwise comparison table
    console.print("\n[bold]2. PRISM vs Cosine Similarity Matrix[/bold]")
    table = Table(title="Pairwise Similarity (PRISM combined / cosine)")
    table.add_column("", style="dim", width=6)
    for i in range(len(samples)):
        table.add_column(f"S{i}", justify="center", width=12)

    for i, (text_i, _, emb_i) in enumerate(embeddings):
        row = [f"S{i}"]
        for j, (text_j, _, emb_j) in enumerate(embeddings):
            if i == j:
                row.append("[bold]1.00/1.00[/bold]")
            else:
                score = engine.similarity(emb_i, emb_j)
                cos = score.cosine
                prism = score.combined
                # Highlight divergence
                diff = abs(prism - max(0, cos))
                style = "green" if diff > 0.1 else ""
                row.append(f"[{style}]{prism:.2f}/{cos:.2f}[/{style}]" if style else f"{prism:.2f}/{cos:.2f}")
        table.add_row(*row)

    console.print(table)
    console.print("[dim]Format: PRISM/cosine. [green]Green[/green] = divergence > 0.1[/dim]")

    # Legend
    legend = Table(title="Sample Legend", show_header=False)
    legend.add_column("ID", width=4)
    legend.add_column("Lifecycle", width=12)
    legend.add_column("Description")
    for i, (text, lifecycle, _) in enumerate(embeddings):
        legend.add_row(f"S{i}", lifecycle, text)
    console.print(legend)

    # 3. Hierarchy demonstration
    console.print("\n[bold]3. Hierarchical Similarity (P-adic)[/bold]")
    # Same-domain pair vs cross-domain pair
    score_same = engine.similarity(embeddings[0][2], embeddings[1][2])
    score_cross = engine.similarity(embeddings[0][2], embeddings[2][2])
    console.print(f"  Same domain (DB query + SQL optimization):  p-adic={score_same.padic:.3f}  cosine={score_same.cosine:.3f}")
    console.print(f"  Cross domain (DB query + JWT auth):         p-adic={score_cross.padic:.3f}  cosine={score_cross.cosine:.3f}")

    # 4. Fault detection demonstration
    console.print("\n[bold]4. Fault Detection (RNS Channel Voting)[/bold]")
    clean_emb = embeddings[0][2]
    # Create corrupted version
    corrupted_channels = [ch[:] for ch in clean_emb.rns_channels]
    # Corrupt channel 2: shift all values
    corrupted_channels[2] = [(v + 5) % engine.PRIMES[2] for v in corrupted_channels[2]]
    corrupted = PrismEmbedding(
        base_vector=clean_emb.base_vector,
        padic_tree=clean_emb.padic_tree,
        rns_channels=corrupted_channels,
        vmf_kappa=clean_emb.vmf_kappa,
    )
    score_clean = engine.similarity(clean_emb, clean_emb)
    score_corrupt = engine.similarity(clean_emb, corrupted)
    console.print(f"  Clean vs clean:     agreement={score_clean.channel_agreement:.3f}  drift={score_clean.drift_detected}")
    console.print(f"  Clean vs corrupted: agreement={score_corrupt.channel_agreement:.3f}  drift={score_corrupt.drift_detected}")

    # 5. Uncertainty demonstration (vMF)
    console.print("\n[bold]5. Uncertainty Weighting (von Mises-Fisher)[/bold]")
    # Same text, different lifecycle states
    text = "Implementing caching layer for API responses"
    emb_thriving = engine.encode_and_enhance(text, {"lifecycle_state": "thriving"})
    emb_embryonic = engine.encode_and_enhance(text, {"lifecycle_state": "embryonic"})
    emb_viable = engine.encode_and_enhance(text, {"lifecycle_state": "viable"})

    score_tt = engine.similarity(emb_thriving, emb_thriving)
    score_te = engine.similarity(emb_thriving, emb_embryonic)
    score_tv = engine.similarity(emb_thriving, emb_viable)

    console.print(f"  thriving↔thriving (κ=20↔20):   vMF overlap={score_tt.vmf_overlap:.3f}  combined={score_tt.combined:.3f}")
    console.print(f"  thriving↔viable   (κ=20↔5):    vMF overlap={score_tv.vmf_overlap:.3f}  combined={score_tv.combined:.3f}")
    console.print(f"  thriving↔embryonic (κ=20↔2):   vMF overlap={score_te.vmf_overlap:.3f}  combined={score_te.combined:.3f}")

    # 6. Diagnostic breakdown
    if verbose:
        console.print("\n[bold]6. Detailed Diagnostic (S0 vs S1)[/bold]")
        diag = engine.diagnose(embeddings[0][2], embeddings[1][2])
        diag_table = Table(title="Diagnostic Breakdown")
        diag_table.add_column("Component", width=16)
        diag_table.add_column("Raw", justify="right", width=8)
        diag_table.add_column("Weighted", justify="right", width=8)
        diag_table.add_column("Detail")

        diag_table.add_row(
            "Cosine", str(diag["cosine_detail"]["raw"]), str(diag["cosine_detail"]["weighted"]),
            ""
        )
        diag_table.add_row(
            "P-adic", str(diag["padic_detail"]["raw"]), str(diag["padic_detail"]["weighted"]),
            f"shared_depth={diag['padic_detail']['shared_depth']}"
        )
        diag_table.add_row(
            "RNS", str(diag["rns_detail"]["consensus"]), "",
            f"channels={diag['rns_detail']['channel_sims']} agreement={diag['rns_detail']['agreement']}"
        )
        diag_table.add_row(
            "vMF", str(diag["vmf_detail"]["overlap"]), str(diag["vmf_detail"]["weighted"]),
            f"κ_a={diag['vmf_detail']['kappa_a']} κ_b={diag['vmf_detail']['kappa_b']}"
        )
        console.print(diag_table)
        console.print(f"  Dominant: [bold]{diag['dominant_component']}[/bold]")
        console.print(f"  Interpretation: {diag['interpretation']}")

    console.print(f"\n[bold green]PRISM demonstration complete.[/bold green]")
    console.print("[dim]PRISM adds hierarchical (p-adic), fault-tolerant (RNS), and uncertainty-aware (vMF) signals to standard cosine similarity.[/dim]")



# ---------------------------------------------------------------------------
# stats — Quick summary of this CAM ganglion
# ---------------------------------------------------------------------------

@app.command()
def stats(
    as_json: bool = typer.Option(False, "--json", help="Output machine-readable JSON to stdout"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Show methodology count, repo count, ganglion name, and CAG cache status."""
    _setup_logging(False)
    asyncio.run(_stats_async(as_json=as_json, config_path=config))


async def _stats_async(*, as_json: bool, config_path: Optional[str]) -> None:
    """Gather counts from the database and CAG cache, then print."""
    from claw.core.config import load_config
    from claw.db.engine import DatabaseEngine
    from claw.db.repository import Repository

    cfg = load_config(Path(config_path) if config_path else None)

    # -- database counts --
    engine = DatabaseEngine(cfg.database)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    repo = Repository(engine)

    try:
        methodology_count = await repo.count_methodologies()
        active_count = await repo.count_active_methodologies()
        state_counts = await repo.count_methodologies_by_state()

        # Count distinct source repos from tags (source:reponame)
        import json as _json

        tag_rows = await engine.fetch_all(
            "SELECT tags FROM methodologies WHERE tags IS NOT NULL"
        )
        sources: set[str] = set()
        for row in tag_rows:
            tags = _json.loads(row["tags"]) if isinstance(row["tags"], str) else (row["tags"] or [])
            for t in tags:
                if isinstance(t, str) and t.startswith("source:"):
                    sources.add(t[7:])
        source_repo_count = len(sources)

        # -- ganglion identity --
        ganglion_name = cfg.instances.instance_name or "general"
        ganglion_description = cfg.instances.instance_description or ""
        federation_enabled = cfg.instances.enabled
        sibling_count = len(cfg.instances.siblings)

        # -- CAG cache status --
        cag_status: dict = {"enabled": cfg.cag.enabled, "loaded": False, "methodology_count": 0}
        if cfg.cag.enabled:
            try:
                from claw.memory.cag_retriever import CAGRetriever

                retriever = CAGRetriever(cfg.cag)
                await retriever.load_cache(ganglion=ganglion_name)
                cag_status = retriever.get_status(ganglion=ganglion_name)
            except Exception:
                cag_status["error"] = "failed to load CAG cache"
    finally:
        await engine.close()

    result = {
        "ganglion": ganglion_name,
        "ganglion_description": ganglion_description,
        "methodology_count": methodology_count,
        "active_methodology_count": active_count,
        "source_repo_count": source_repo_count,
        "lifecycle_states": state_counts,
        "federation_enabled": federation_enabled,
        "sibling_count": sibling_count,
        "db_path": cfg.database.db_path,
        "cag": cag_status,
    }

    if as_json:
        import json as _json2
        sys.stdout.write(_json2.dumps(result, indent=2) + "\n")
    else:
        from rich.panel import Panel

        console.print(Panel.fit(
            f"[bold cyan]CAM Stats[/bold cyan]  —  ganglion: [bold]{ganglion_name}[/bold]",
            border_style="cyan",
        ))

        console.print(f"  Methodologies:       [bold]{methodology_count:,}[/bold]  ({active_count:,} active)")
        console.print(f"  Source repos:        [bold]{source_repo_count:,}[/bold]")
        console.print(f"  DB path:             {cfg.database.db_path}")

        if ganglion_description:
            console.print(f"  Description:         {ganglion_description}")

        # Lifecycle breakdown
        if state_counts:
            parts = []
            for state in ["thriving", "viable", "embryonic", "declining", "dormant", "dead"]:
                cnt = state_counts.get(state, 0)
                if cnt:
                    parts.append(f"{state}={cnt}")
            console.print(f"  Lifecycle:           {', '.join(parts)}")

        # Federation
        fed_str = "enabled" if federation_enabled else "disabled"
        console.print(f"  Federation:          {fed_str}  ({sibling_count} sibling(s))")

        # CAG
        if cfg.cag.enabled:
            loaded_str = "yes" if cag_status.get("loaded") else "no"
            cag_meths = cag_status.get("methodology_count", 0)
            cag_built = cag_status.get("built_at", "never")
            stale_str = "yes" if cag_status.get("stale") else "no"
            console.print(f"  CAG cache:           loaded={loaded_str}  meths={cag_meths}  built={cag_built}  stale={stale_str}")
        else:
            console.print("  CAG cache:           [dim]disabled[/dim]")


# ---------------------------------------------------------------------------
# kb — Knowledge Browser command group
# ---------------------------------------------------------------------------

kb_app = typer.Typer(
    name="kb",
    help="Knowledge browser — explore assimilated capabilities, synergies, and domains",
    no_args_is_help=True,
)
app.add_typer(learn_app, name="learn")
app.add_typer(task_app, name="task")
app.add_typer(forge_app, name="forge")
app.add_typer(doctor_app, name="doctor")
app.add_typer(kb_app, name="kb")
app.add_typer(pulse_app, name="pulse")
app.add_typer(self_enhance_app, name="self-enhance")
app.add_typer(ab_test_app, name="ab-test")
app.add_typer(evolution_app, name="evolution")
app.add_typer(security_app, name="security")
app.add_typer(cag_app, name="cag")


# ---------------------------------------------------------------------------
# Gap Analysis commands
# ---------------------------------------------------------------------------

@app.command()
def gaps(
    snapshot: bool = typer.Option(False, "--snapshot", help="Take a new coverage snapshot before display"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    discover: bool = typer.Option(False, "--discover", help="Analyze cross_cutting for candidate new categories"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Show category x brain coverage matrix and identify knowledge gaps.

    Displays a Rich table with color coding:
      red = empty (0 methodologies), yellow = sparse (< threshold), green = adequate.
    Use --snapshot to persist the current state for trend tracking.
    Use --json for machine-readable output.
    Use --discover to analyze cross_cutting for emergent category candidates.
    """
    _setup_logging(verbose)
    from claw.core.config import load_config

    cfg = load_config(Path(config) if config else None)

    if not cfg.gap_analyzer.enabled:
        console.print("[yellow]Gap analyzer is disabled. Set [gap_analyzer] enabled=true in claw.toml[/yellow]")
        raise typer.Exit(1)

    async def _run():
        from claw.db.engine import DatabaseEngine
        from claw.db.repository import Repository
        from claw.community.gap_analyzer import GapAnalyzer

        engine = DatabaseEngine(cfg.database)
        await engine.connect()
        await engine.apply_migrations()
        repo = Repository(engine)
        primary_db = str(Path(cfg.database.db_path).resolve())
        analyzer = GapAnalyzer(repo, cfg.instances, primary_db, cfg.gap_analyzer)

        try:
            if snapshot:
                coverage = await analyzer.take_snapshot()
                console.print("[green]Snapshot saved.[/green]\n")
            else:
                coverage = await analyzer.compute_coverage_matrix()

            if json_output:
                import json as _json
                console.print(_json.dumps({
                    "matrix": coverage.matrix,
                    "sparse_cells": coverage.sparse_cells,
                    "empty_cells": coverage.empty_cells,
                    "total_by_category": coverage.total_by_category,
                    "total_by_brain": coverage.total_by_brain,
                }, indent=2))
                return

            # Rich table display
            all_brains = sorted(set(coverage.total_by_brain.keys()))
            if not all_brains:
                console.print("[yellow]No methodology data found. Run `cam mine` first.[/yellow]")
                return

            threshold = cfg.gap_analyzer.sparse_cell_threshold
            total_methods = sum(coverage.total_by_brain.values())

            console.print(f"\n[bold]Coverage Matrix[/bold] ({total_methods} total methodologies, threshold={threshold})")

            table = Table()
            table.add_column("Category", style="bold", max_width=25)
            for brain in all_brains:
                table.add_column(brain, justify="right", width=12)
            table.add_column("Total", justify="right", style="bold", width=8)

            for cat in sorted(coverage.total_by_category.keys()):
                row = [cat]
                for brain in all_brains:
                    count = coverage.matrix.get(cat, {}).get(brain, 0)
                    if count == 0:
                        row.append("[red]0[/red]")
                    elif count < threshold:
                        row.append(f"[yellow]{count}[/yellow]")
                    else:
                        row.append(f"[green]{count}[/green]")
                row.append(str(coverage.total_by_category.get(cat, 0)))
                table.add_row(*row)

            # Total row
            total_row = ["[bold]TOTAL[/bold]"]
            for brain in all_brains:
                total_row.append(f"[bold]{coverage.total_by_brain.get(brain, 0)}[/bold]")
            total_row.append(f"[bold]{total_methods}[/bold]")
            table.add_row(*total_row)

            console.print(table)

            # Sparse summary
            sparse_count = len(coverage.sparse_cells)
            empty_count = len(coverage.empty_cells)
            if sparse_count or empty_count:
                console.print(f"\n  [red]{empty_count} empty[/red] + [yellow]{sparse_count} sparse[/yellow] cells")
            else:
                console.print(f"\n  [green]All cells at or above threshold ({threshold})[/green]")

            # Trend
            trend = await analyzer.get_trend_summary()
            if trend:
                console.print(f"\n{trend}")

            # Category discovery
            if discover:
                console.print("\n[bold]Category Discovery[/bold] — analyzing cross_cutting for emergent themes\n")
                candidates = await analyzer.discover_candidate_categories(min_cluster_size=5)
                if not candidates:
                    console.print("[dim]No candidate categories found (cross_cutting may be too small or well-distributed).[/dim]")
                else:
                    disc_table = Table(title=f"{len(candidates)} Candidate Categories from cross_cutting")
                    disc_table.add_column("Theme", style="bold cyan")
                    disc_table.add_column("Count", justify="right")
                    disc_table.add_column("Suggested Name", style="green")
                    disc_table.add_column("Sample Titles")
                    for c in candidates:
                        samples = "\n".join(f"  - {t[:70]}" for t in c["sample_titles"][:3])
                        disc_table.add_row(
                            c["theme"],
                            str(c["count"]),
                            c["suggested_name"],
                            samples,
                        )
                    console.print(disc_table)
                    console.print(
                        "\n[dim]To reclassify, add the new category to _VALID_CATEGORIES in miner.py, "
                        "then use repository.reclassify_methodologies() to migrate tagged entries.[/dim]"
                    )

        finally:
            await engine.close()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Security commands
# ---------------------------------------------------------------------------

@security_app.command(name="scan")
def security_scan(
    path: str = typer.Argument(..., help="Path to directory to scan for secrets"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show all findings"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Scan a directory for hardcoded secrets using TruffleHog (or regex fallback)."""
    import asyncio

    async def _run():
        from claw.security.scanner import SecretScanner, ScanSeverity

        target = Path(path).resolve()
        if not target.is_dir():
            console.print(f"[red]Error:[/red] {path} is not a directory")
            raise typer.Exit(1)

        scanner = SecretScanner()
        scanner_name = "trufflehog" if scanner._trufflehog_available else "regex (fallback)"
        console.print(f"\n[bold]Secret Scan[/bold] — {target}")
        console.print(f"  Scanner: {scanner_name}\n")

        result = await scanner.scan(target)

        if result.error:
            console.print(f"[red]Scan error:[/red] {result.error}")
            raise typer.Exit(1)

        if json_output:
            import json
            output = {
                "path": result.path,
                "scanner": result.scanner_used,
                "duration_seconds": round(result.scan_duration_seconds, 2),
                "findings_count": len(result.findings),
                "critical_count": result.critical_count,
                "findings": [
                    {
                        "file": f.file_path,
                        "line": f.line,
                        "detector": f.detector_name,
                        "severity": f.severity,
                        "verified": f.verified,
                        "redacted": f.redacted_match,
                    }
                    for f in result.findings
                ],
            }
            console.print(json.dumps(output, indent=2))
        else:
            if not result.has_any:
                console.print(
                    f"  [green]CLEAN[/green] — 0 findings ({result.scan_duration_seconds:.1f}s)"
                )
            else:
                for f in result.findings:
                    if f.severity in (ScanSeverity.CRITICAL, ScanSeverity.HIGH) or verbose:
                        if f.severity == ScanSeverity.CRITICAL:
                            icon = "[red]CRITICAL[/red]"
                        elif f.severity == ScanSeverity.HIGH:
                            icon = "[yellow]HIGH[/yellow]"
                        else:
                            icon = f"[dim]{f.severity}[/dim]"
                        console.print(
                            f"  {icon} {f.file_path}:{f.line} — "
                            f"{f.detector_name} ({f.redacted_match})"
                        )
                console.print(
                    f"\n  Total: {len(result.findings)} findings "
                    f"({result.critical_count} critical) in "
                    f"{result.scan_duration_seconds:.1f}s"
                )

        raise typer.Exit(1 if result.has_critical else 0)

    asyncio.run(_run())


@security_app.command(name="status")
def security_status() -> None:
    """Check secret scanner availability and configuration."""
    from claw.security.scanner import _trufflehog_available
    from claw.core.config import load_config

    config = load_config()

    console.print("\n[bold]Security Scanner Status[/bold]")
    console.print(f"  Enabled: {config.security.secret_scan_enabled}")
    console.print(f"  Fail on critical: {config.security.secret_scan_fail_on_critical}")
    console.print(f"  Filter in serializer: {config.security.secret_scan_filter_in_serializer}")
    console.print(f"  Timeout: {config.security.secret_scan_timeout_seconds}s")

    if _trufflehog_available():
        import subprocess
        try:
            version = subprocess.run(
                ["trufflehog", "--version"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
        except Exception:
            version = "unknown"
        console.print(f"  TruffleHog: [green]AVAILABLE[/green] ({version})")
    else:
        console.print("  TruffleHog: [yellow]NOT FOUND[/yellow] (using regex fallback)")
        console.print("  Install: [dim]brew install trufflehog[/dim]")


async def _kb_engine():
    """Shared async setup for kb commands — returns (engine, repository)."""
    from claw.core.config import load_config
    from claw.db.engine import DatabaseEngine
    from claw.db.repository import Repository

    config = load_config()
    engine = DatabaseEngine(config.database)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    repository = Repository(engine)
    return engine, repository


@kb_app.command(name="seed")
def kb_seed(
    force: bool = typer.Option(False, "--force", help="Re-seed even if seed records already exist"),
    repair_embeddings: bool = typer.Option(False, "--repair-embeddings", help="Generate missing embeddings for existing methodologies"),
    pack: list[str] = typer.Option(
        [],
        "--pack",
        "-p",
        help="Seed pack name to load (without .jsonl suffix). Repeatable. Default: core_v1 only.",
    ),
    all_packs: bool = typer.Option(
        False,
        "--all-packs",
        help="Escape hatch: load every pack discovered under src/claw/data/seed/.",
    ),
    list_packs: bool = typer.Option(
        False,
        "--list-packs",
        help="List available seed packs with record counts and exit (does not touch the DB).",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Load built-in seed knowledge into the methodology store.

    Default behaviour loads only the canonical ``core_v1`` pack — this is
    a change from earlier releases which loaded every pack discovered on
    disk. Use ``--pack NAME`` (repeatable) to load specific packs,
    ``--all-packs`` to restore the old "load everything" behaviour, or
    ``--list-packs`` to inspect what is available without touching the DB.

    Runs automatically on first startup. Use ``--force`` to re-seed after
    accidental deletion. Use ``--repair-embeddings`` to generate missing
    vectors for methodologies that were saved without embeddings.
    """
    _setup_logging(verbose)

    # --list-packs is DB-free: short-circuit before touching the engine.
    if list_packs:
        from claw.community.seeder import list_available_packs

        entries = list_available_packs()
        console.print("\n[bold]Available seed packs[/bold]\n")
        if not entries:
            console.print("  [yellow]No seed packs found in package.[/yellow]")
            return
        for e in entries:
            count_str = str(e["records"]) if e["records"] >= 0 else "?"
            console.print(f"  {e['name']}  ({count_str} records)  [dim]{e['path']}[/dim]")
        return

    # Resolve which pack names the user wants.
    if all_packs and pack:
        console.print(
            "[red]--all-packs and --pack are mutually exclusive. Pick one.[/red]"
        )
        raise typer.Exit(2)

    if all_packs:
        selected_names: Optional[list[str]] = None  # None == every discovered pack
    elif pack:
        selected_names = list(pack)
    else:
        from claw.community.seeder import DEFAULT_SEED_PACK

        selected_names = [DEFAULT_SEED_PACK]

    async def _run() -> None:
        from claw.community.seeder import discover_seed_packs, list_available_packs, repair_missing_embeddings, run_seed
        from claw.core.config import load_config
        from claw.db.embeddings import EmbeddingEngine

        cfg = load_config(Path(config) if config else None)
        engine, _repo = await _kb_engine()

        # Surface what the user asked for vs what is on disk so missing
        # --pack names are visible instead of silently producing no-ops.
        on_disk = {e["name"]: e for e in list_available_packs()}
        if not on_disk:
            console.print("[red]No seed packs found in package.[/red]")
            try:
                await engine.close()
            except Exception:
                pass
            return

        if selected_names is None:
            resolved = list(on_disk.keys())
        else:
            resolved = [n for n in selected_names if n in on_disk]
            missing = [n for n in selected_names if n not in on_disk]
            if missing:
                console.print(
                    f"[yellow]Unknown pack name(s) ignored: {', '.join(missing)}[/yellow]"
                )
                console.print(
                    f"[dim]Known packs: {', '.join(sorted(on_disk.keys()))}[/dim]"
                )

        if not resolved:
            console.print("[red]No matching seed packs to load.[/red]")
            try:
                await engine.close()
            except Exception:
                pass
            return

        packs = discover_seed_packs(names=resolved)
        console.print(f"\n[bold]CAM Seed Knowledge Loader[/bold]\n")
        for p in packs:
            line_count = sum(1 for line in p.read_text().strip().splitlines() if line.strip())
            console.print(f"  Pack: {p.name} ({line_count} records)")

        # Try to create embedding engine
        embedding_engine = None
        try:
            embedding_engine = EmbeddingEngine(cfg.embeddings)
            console.print(f"  Embedding model: {cfg.embeddings.model}")
        except Exception as e:
            console.print(f"  [yellow]Embeddings unavailable ({e}) — seeding without vectors[/yellow]")

        summary = await run_seed(
            engine=engine,
            embedding_engine=embedding_engine,
            force=force,
            config=cfg,
            names=resolved,
        )

        if summary.get("reason") == "already_seeded" and not force:
            console.print("\n[green]Seed knowledge already present.[/green] Use --force to re-seed.")
        elif summary["imported"] > 0:
            console.print(f"\n  Imported: {summary['imported']}")
            console.print(f"  Skipped (dedup): {summary['skipped']}")
            if summary["rejected"]:
                console.print(f"  Rejected: {summary['rejected']}")
            console.print(f"\n[green]Seed knowledge loaded successfully.[/green]")
        elif summary["skipped"] > 0:
            console.print(f"\n[green]All seed records already present (idempotent).[/green]")
        else:
            console.print(f"\n[yellow]No records to seed (reason: {summary.get('reason', '?')}).[/yellow]")

        # Repair missing embeddings if requested
        if repair_embeddings:
            if embedding_engine is None:
                console.print("[red]Cannot repair embeddings without GOOGLE_API_KEY.[/red]")
            else:
                console.print("\n[cyan]Repairing missing embeddings...[/cyan]")
                repaired = await repair_missing_embeddings(engine, embedding_engine)
                console.print(f"  Repaired: {repaired} methodologies")

        try:
            await engine.close()
        except Exception:
            pass

    asyncio.run(_run())


@kb_app.command(name="bootstrap")
def kb_bootstrap(
    domain: str = typer.Option(
        "python",
        "--domain",
        "-d",
        help="Domain to bootstrap: python, devsecops, webdev, all",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-seed even if the knowledge base already has seed records",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Bootstrap the CAM knowledge base with a curated starter pack.

    This is the recommended first-run command for new users. It loads
    a domain-specific curated seed pack, verifies the DB is populated,
    and prints next-step recommendations for expanding the KB.

    Domains:
      python     - Python-primary starter (51 methodologies across
                   code_quality, architecture, security, design_patterns)
      devsecops  - Security + CI/CD focus (12 methodologies)
      webdev     - Web development focus (small pack, supplemented with Python starter)
      all        - Load every available starter pack
    """
    _setup_logging(verbose)

    from claw.community.seeder import DOMAIN_PACKS, list_available_packs

    # 1. Validate domain
    if domain not in DOMAIN_PACKS:
        console.print(f"[red]Unknown domain: {domain!r}[/red]")
        console.print(
            f"[dim]Available domains: {', '.join(sorted(DOMAIN_PACKS.keys()))}[/dim]"
        )
        raise typer.Exit(2)

    required_packs = list(DOMAIN_PACKS[domain])

    # 2. Verify every required pack is present on disk (DB-free check)
    on_disk = {e["name"]: e for e in list_available_packs()}
    missing = [p for p in required_packs if p not in on_disk]
    if missing:
        console.print(
            f"[red]Missing seed pack(s) for domain {domain!r}: "
            f"{', '.join(missing)}[/red]"
        )
        if on_disk:
            console.print(
                f"[dim]Available packs on disk: {', '.join(sorted(on_disk.keys()))}[/dim]"
            )
        else:
            console.print("[dim]No seed packs found in package.[/dim]")
        raise typer.Exit(1)

    console.print(f"\n[bold]CAM Knowledge Bootstrap[/bold] - Domain: [cyan]{domain}[/cyan]")
    console.print(f"Loading packs: [dim]{', '.join(required_packs)}[/dim]\n")

    async def _run() -> None:
        from claw.community.seeder import run_seed
        from claw.core.config import load_config
        from claw.db.embeddings import EmbeddingEngine

        cfg = load_config(Path(config) if config else None)
        engine, _repo = await _kb_engine()

        try:
            # Try to create embedding engine (same pattern as kb_seed)
            embedding_engine = None
            try:
                embedding_engine = EmbeddingEngine(cfg.embeddings)
                console.print(f"  Embedding model: [dim]{cfg.embeddings.model}[/dim]")
            except Exception as e:
                console.print(
                    f"  [yellow]Embeddings unavailable ({e}) - seeding without vectors[/yellow]"
                )

            # 3. Delegate to run_seed - do NOT duplicate its logic
            summary = await run_seed(
                engine=engine,
                embedding_engine=embedding_engine,
                force=force,
                config=cfg,
                names=required_packs,
            )

            reason = summary.get("reason", "")

            # 4. Idempotent path - already seeded
            if reason == "already_seeded" and not force:
                console.print(
                    "\n[green]Already bootstrapped.[/green] Use [bold]--force[/bold] to re-seed."
                )
                # Still show category breakdown so the user sees current state
                await _print_category_breakdown(engine)
                _print_next_steps(domain)
                return

            # 5. Report import results
            if summary.get("imported", 0) > 0:
                parts = []
                # We know which packs we asked for - report actual counts
                for pack_name in required_packs:
                    pack_meta = on_disk.get(pack_name)
                    if pack_meta and pack_meta["records"] >= 0:
                        parts.append(f"{pack_meta['records']} from {pack_name}")
                detail = f" ({', '.join(parts)})" if parts else ""
                console.print(
                    f"\n[green]OK[/green] Imported {summary['imported']} methodologies{detail}"
                )
                if summary.get("skipped", 0):
                    console.print(f"  Skipped (dedup): {summary['skipped']}")
                if summary.get("rejected", 0):
                    console.print(f"  [yellow]Rejected: {summary['rejected']}[/yellow]")
            elif summary.get("skipped", 0) > 0:
                console.print(
                    f"\n[green]All seed records already present (idempotent).[/green]"
                )
            else:
                console.print(
                    f"\n[yellow]No records imported (reason: {reason or '?'}).[/yellow]"
                )

            # 6. Category breakdown
            await _print_category_breakdown(engine)

            # 7. Next-step recommendations
            _print_next_steps(domain)

        finally:
            try:
                await engine.close()
            except Exception:
                pass

    asyncio.run(_run())


async def _print_category_breakdown(engine: Any) -> None:
    """Query methodologies grouped by category tag and print a Rich table.

    Uses the ``tags LIKE '%"category:X"%'`` pattern consistent with the
    rest of the codebase. Only prints when there are rows to show.
    """
    # Discover distinct category:* tags then count each one.
    rows = await engine.fetch_all(
        "SELECT tags FROM methodologies WHERE tags IS NOT NULL"
    )
    if not rows:
        return

    counts: dict[str, int] = {}
    for r in rows:
        raw = r["tags"] if isinstance(r, dict) else r[0]
        if not raw:
            continue
        try:
            tags = json.loads(raw) if isinstance(raw, str) else list(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for t in tags:
            if isinstance(t, str) and t.startswith("category:"):
                cat = t.split(":", 1)[1]
                counts[cat] = counts.get(cat, 0) + 1

    if not counts:
        return

    console.print("\n[bold]Category breakdown:[/bold]")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Category", style="cyan")
    table.add_column("Count", justify="right", style="bold")
    for cat, cnt in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        table.add_row(cat, str(cnt))
    console.print(table)


def _print_next_steps(domain: str) -> None:
    """Print domain-specific next-step recommendations."""
    console.print("\n[bold]Next steps:[/bold]")
    sample_query = "refactor long function"

    if domain == "python":
        console.print(f'  1. Verify: [cyan]cam federate "{sample_query}" --limit 5[/cyan]')
        console.print(
            "  2. Expand: [cyan]cam pulse ingest https://github.com/tiangolo/fastapi[/cyan]"
        )
        console.print(
            "  3. Mine more Python repos to grow the knowledge base further."
        )
    elif domain == "devsecops":
        console.print(f'  1. Verify: [cyan]cam federate "secret scanning ci" --limit 5[/cyan]')
        console.print(
            "  2. Expand with DevSecOps repos:"
        )
        console.print("     - [cyan]cam pulse ingest https://github.com/trufflesecurity/trufflehog[/cyan]")
        console.print("     - [cyan]cam pulse ingest https://github.com/aquasecurity/trivy[/cyan]")
        console.print("     - [cyan]cam pulse ingest https://github.com/returntocorp/semgrep[/cyan]")
        console.print("     - [cyan]cam pulse ingest https://github.com/gitleaks/gitleaks[/cyan]")
    elif domain == "webdev":
        console.print(f'  1. Verify: [cyan]cam federate "http middleware" --limit 5[/cyan]')
        console.print(
            "  2. Expand with Python web frameworks:"
        )
        console.print("     - [cyan]cam pulse ingest https://github.com/tiangolo/fastapi[/cyan]")
        console.print("     - [cyan]cam pulse ingest https://github.com/encode/starlette[/cyan]")
        console.print(
            "  [dim]Note: the TypeScript ganglion is currently empty - polyglot support is planned.[/dim]"
        )
    elif domain == "all":
        console.print(f'  1. Verify: [cyan]cam federate "{sample_query}" --limit 5[/cyan]')
        console.print(
            "  2. Full playbook: see [cyan]docs/KB_BOOTSTRAP_PLAYBOOKS.md[/cyan]"
        )
        console.print(
            "  3. Continue expanding with [cyan]cam pulse ingest <url>[/cyan]"
        )
    else:  # pragma: no cover - validated upstream
        console.print(f'  1. Verify: [cyan]cam federate "{sample_query}" --limit 5[/cyan]')


@kb_app.command()
def insights(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """THE showpiece — top capabilities, domain map, synergy highlights, score distributions."""
    asyncio.run(_kb_insights_async())


async def _kb_insights_async() -> None:
    from rich.panel import Panel

    engine, repository = await _kb_engine()

    try:
        # Header: total count + source repos
        total = await repository.count_methodologies()
        if total == 0:
            console.print("[yellow]No capabilities in knowledge base. Run 'cam mine <dir>' first.[/yellow]")
            return

        state_counts = await repository.count_methodologies_by_state()
        active = sum(v for k, v in state_counts.items() if k != "dead")

        # Count distinct source repos from tags (source:reponame)
        import json as _json
        _all_meths = await repository.engine.fetch_all(
            "SELECT tags FROM methodologies WHERE tags IS NOT NULL"
        )
        _sources = set()
        for _r in _all_meths:
            _tags = _json.loads(_r["tags"]) if isinstance(_r["tags"], str) else (_r["tags"] or [])
            for _t in _tags:
                if isinstance(_t, str) and _t.startswith("source:"):
                    _sources.add(_t[7:])
        repo_count = len(_sources) if _sources else "?"

        console.print(Panel.fit(
            f"[bold cyan]CAM Knowledge Base[/bold cyan]\n"
            f"[bold]{total:,}[/bold] capabilities from [bold]{repo_count}[/bold] repos  |  "
            f"[bold]{active:,}[/bold] active",
            border_style="cyan",
        ))

        # Score distributions
        dist = await repository.get_novelty_potential_distribution()
        if dist["total"] > 0:
            score_table = Table(title="Score Distributions")
            score_table.add_column("Metric", style="bold", width=18)
            score_table.add_column("Avg", justify="right", width=8)
            score_table.add_column("Min", justify="right", width=8)
            score_table.add_column("Max", justify="right", width=8)
            score_table.add_column("Scored", justify="right", width=8)
            score_table.add_row(
                "Novelty",
                f"{dist['avg_novelty']:.3f}",
                f"{dist['min_novelty']:.3f}",
                f"{dist['max_novelty']:.3f}",
                str(dist["total"]),
            )
            score_table.add_row(
                "Potential",
                f"{dist['avg_potential']:.3f}",
                f"{dist['min_potential']:.3f}",
                f"{dist['max_potential']:.3f}",
                str(dist["total"]),
            )
            console.print(score_table)

        # Lifecycle state table
        if state_counts:
            state_table = Table(title="Lifecycle States")
            state_table.add_column("State", style="bold", width=14)
            state_table.add_column("Count", justify="right", width=8)
            state_table.add_column("", width=30)
            state_colors = {
                "thriving": "green", "viable": "cyan", "embryonic": "yellow",
                "declining": "magenta", "dormant": "dim", "dead": "red",
            }
            for state in ["thriving", "viable", "embryonic", "declining", "dormant", "dead"]:
                count = state_counts.get(state, 0)
                if count == 0:
                    continue
                color = state_colors.get(state, "")
                bar_len = min(int(count / max(state_counts.values()) * 25), 25)
                bar = "█" * bar_len
                state_table.add_row(
                    f"[{color}]{state}[/{color}]" if color else state,
                    str(count),
                    f"[{color}]{bar}[/{color}]" if color else bar,
                )
            console.print(state_table)

        # Top 5 Novel
        top_novel = await repository.get_most_novel_methodologies(limit=5)
        if top_novel:
            novel_table = Table(title="Top 5 Novel Capabilities")
            novel_table.add_column("ID", width=8)
            novel_table.add_column("Description", max_width=50)
            novel_table.add_column("Novelty", justify="right", width=8, style="bold yellow")
            novel_table.add_column("Domains", max_width=25)
            for m in top_novel:
                domains = ", ".join((m.capability_data or {}).get("domain", [])[:3])
                score = m.novelty_score or 0
                score_style = "bold green" if score >= 0.7 else ("yellow" if score >= 0.4 else "dim")
                novel_table.add_row(
                    m.id[:8],
                    m.problem_description[:50],
                    f"[{score_style}]{score:.3f}[/{score_style}]",
                    domains,
                )
            console.print(novel_table)

        # Top 5 High-Potential
        top_potential = await repository.get_high_potential_methodologies(limit=5)
        if top_potential:
            pot_table = Table(title="Top 5 High-Potential Capabilities")
            pot_table.add_column("ID", width=8)
            pot_table.add_column("Description", max_width=50)
            pot_table.add_column("Potential", justify="right", width=8, style="bold cyan")
            pot_table.add_column("Domains", max_width=25)
            for m in top_potential:
                domains = ", ".join((m.capability_data or {}).get("domain", [])[:3])
                score = m.potential_score or 0
                score_style = "bold green" if score >= 0.7 else ("cyan" if score >= 0.4 else "dim")
                pot_table.add_row(
                    m.id[:8],
                    m.problem_description[:50],
                    f"[{score_style}]{score:.3f}[/{score_style}]",
                    domains,
                )
            console.print(pot_table)

        # Domain Landscape — Top 15
        domain_dist = await repository.get_domain_distribution()
        if domain_dist:
            sorted_domains = sorted(domain_dist.items(), key=lambda x: -x[1])[:15]
            max_count = sorted_domains[0][1] if sorted_domains else 1
            domain_table = Table(title="Domain Landscape (Top 15)")
            domain_table.add_column("Domain", style="cyan", max_width=25)
            domain_table.add_column("Count", justify="right", width=6)
            domain_table.add_column("", width=30)
            for domain, count in sorted_domains:
                bar_len = min(int(count / max_count * 25), 25)
                bar = "█" * bar_len
                domain_table.add_row(domain, str(count), f"[cyan]{bar}[/cyan]")
            console.print(domain_table)

        # Synergy Highlights — Top 5
        top_edges = await repository.get_top_synergy_edges(limit=5)
        if top_edges:
            syn_table = Table(title="Synergy Highlights (Top 5)")
            syn_table.add_column("Score", justify="right", width=7, style="bold green")
            syn_table.add_column("Type", width=14)
            syn_table.add_column("Capability A", max_width=35)
            syn_table.add_column("Capability B", max_width=35)
            syn_table.add_column("Cross?", width=6)
            for edge in top_edges:
                is_cross = bool(
                    set(edge["cap_a_domains"]) and set(edge["cap_b_domains"])
                    and not set(edge["cap_a_domains"]) & set(edge["cap_b_domains"])
                )
                cross_str = "[bold yellow]YES[/bold yellow]" if is_cross else ""
                syn_table.add_row(
                    f"{edge['synergy_score']:.3f}",
                    edge["synergy_type"][:14],
                    edge["cap_a_summary"][:35],
                    edge["cap_b_summary"][:35],
                    cross_str,
                )
            console.print(syn_table)

        # Capability Type Distribution
        type_dist = await repository.get_type_distribution()
        if type_dist:
            sorted_types = sorted(type_dist.items(), key=lambda x: -x[1])[:10]
            type_table = Table(title="Capability Types (Top 10)")
            type_table.add_column("Type", style="yellow", max_width=25)
            type_table.add_column("Count", justify="right", width=6)
            for ctype, count in sorted_types:
                type_table.add_row(ctype, str(count))
            console.print(type_table)

    finally:
        await engine.close()


@kb_app.command()
def search(
    query: str = typer.Argument(..., help="Natural language search query"),
    limit: int = typer.Option(10, "--limit", "-n", help="Maximum results"),
    brain: Optional[str] = typer.Option(None, "--brain", "-b", help="Restrict to a specific brain ganglion"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Search capabilities across all brain ganglions (smart cross-brain search)."""
    asyncio.run(_kb_search_async(query, limit, brain_filter=brain))


# Language hints for smart cross-brain query routing.
_QUERY_LANGUAGE_HINTS: dict[str, str] = {
    "goroutine": "go", "golang": "go", "go.mod": "go", "chan ": "go",
    "defer ": "go", "go concurrency": "go", "go interface": "go",
    "borrow checker": "rust", "ownership": "rust", "cargo": "rust",
    "tokio": "rust", "lifetime": "rust", "async trait": "rust",
    "crate": "rust", "unsafe ": "rust",
    "react": "typescript", "hooks": "typescript", "nextjs": "typescript",
    "express": "typescript", "typescript": "typescript", "npm": "typescript",
    "jsx": "typescript", "tsx": "typescript", "webpack": "typescript",
    "angular": "typescript", "svelte": "typescript",
    "pytest": "python", "django": "python", "fastapi": "python",
    "asyncio": "python", "pydantic": "python", "pip ": "python",
    "flask": "python", "pandas": "python", "numpy": "python",
}


def _detect_query_language(query: str) -> Optional[str]:
    """Detect language hint from query text for smart routing.

    Returns brain name (e.g. 'go', 'rust') or None if ambiguous.
    """
    query_lower = query.lower()
    detected: set[str] = set()
    for hint, brain in _QUERY_LANGUAGE_HINTS.items():
        if hint in query_lower:
            detected.add(brain)
    # Only return if unambiguous (single language detected)
    if len(detected) == 1:
        return detected.pop()
    return None


async def _kb_search_async(
    query: str, limit: int, brain_filter: Optional[str] = None,
) -> None:
    from claw.core.config import load_config
    from claw.community.federation import Federation

    cfg = load_config()
    engine, repository = await _kb_engine()

    try:
        total = await repository.count_methodologies()

        # --- Primary DB search ---
        text_results = await repository.search_methodologies_text(query, limit=limit)

        # Build combined results: (methodology, score, source_name)
        combined: list[tuple[Any, float, str]] = []
        seen_ids: set[str] = set()

        if text_results:
            for m, bm25 in text_results:
                combined.append((m, bm25, "primary"))
                seen_ids.add(m.id)

        # --- Federation cross-brain search ---
        detected_lang = brain_filter or _detect_query_language(query)
        try:
            federation = Federation(cfg.instances)
            fed_results = await federation.query(
                query, language=detected_lang, max_total=limit,
            )
            for fr in fed_results:
                if fr.methodology.id not in seen_ids:
                    combined.append((
                        fr.methodology,
                        fr.relevance_score * 10.0,  # Normalize to BM25-ish scale
                        fr.source_instance,
                    ))
                    seen_ids.add(fr.methodology.id)
        except Exception as e:
            logger.debug("Federation search failed (non-fatal): %s", e)

        if not combined:
            if total == 0:
                console.print("[yellow]No capabilities in knowledge base. Run 'cam mine <dir>' first.[/yellow]")
            else:
                console.print(f"[yellow]No results for '{query}'.[/yellow]")
            return

        # Sort by score descending
        combined.sort(key=lambda x: x[1], reverse=True)
        combined = combined[:limit]

        source_hint = ""
        if detected_lang:
            source_hint = f"  [dim](routed to {detected_lang} brain)[/dim]"
        console.print(
            f"\n[bold]Search results for:[/bold] [cyan]{query}[/cyan]"
            f"  ({len(combined)} matches){source_hint}\n",
        )

        table = Table(show_lines=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("ID", width=8)
        table.add_column("Description", max_width=45)
        table.add_column("Source", width=12)
        table.add_column("Domains", max_width=18)
        table.add_column("Score", justify="right", width=8)
        table.add_column("Novelty", justify="right", width=8)
        table.add_column("State", width=10)

        state_colors = {
            "thriving": "green", "viable": "cyan", "embryonic": "yellow",
            "declining": "magenta", "dormant": "dim", "dead": "red",
        }

        for i, (m, score, source) in enumerate(combined, 1):
            domains = ", ".join((m.capability_data or {}).get("domain", [])[:3])
            score_str = f"{score:.2f}"
            novelty_str = f"{m.novelty_score:.3f}" if m.novelty_score is not None else "-"
            color = state_colors.get(m.lifecycle_state, "")
            state_str = f"[{color}]{m.lifecycle_state}[/{color}]" if color else m.lifecycle_state
            source_color = "green" if source == "primary" else "cyan"
            source_str = f"[{source_color}]{source}[/{source_color}]"

            table.add_row(
                str(i),
                m.id[:8],
                m.problem_description[:45],
                source_str,
                domains,
                score_str,
                novelty_str,
                state_str,
            )

        console.print(table)
        console.print(f"\n[dim]Use 'cam kb capability <id>' for full details.[/dim]")

    finally:
        await engine.close()


@kb_app.command()
def capability(
    cap_id: str = typer.Argument(..., help="Capability ID or ID prefix (6+ chars)"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Deep dive on a single capability — full data, synergies, and related."""
    asyncio.run(_kb_capability_async(cap_id))


async def _kb_capability_async(cap_id: str) -> None:
    from rich.panel import Panel

    engine, repository = await _kb_engine()

    try:
        # Try prefix match
        m = await repository.get_methodology_by_prefix(cap_id)
        if m is None:
            console.print(f"[red]No capability found matching '{cap_id}'.[/red]")
            console.print("[dim]Provide at least 6 characters of the ID.[/dim]")
            return

        # Header
        state_colors = {
            "thriving": "green", "viable": "cyan", "embryonic": "yellow",
            "declining": "magenta", "dormant": "dim", "dead": "red",
        }
        color = state_colors.get(m.lifecycle_state, "")
        state_str = f"[{color}]{m.lifecycle_state}[/{color}]" if color else m.lifecycle_state

        console.print(Panel.fit(
            f"[bold cyan]Capability Detail[/bold cyan]\n"
            f"ID: [bold]{m.id}[/bold]\n"
            f"State: {state_str}",
            border_style="cyan",
        ))

        # Problem description
        console.print(f"\n[bold]Problem Description[/bold]")
        console.print(f"  {m.problem_description}")

        # Methodology notes
        if m.methodology_notes:
            notes = m.methodology_notes[:500]
            if len(m.methodology_notes) > 500:
                notes += "..."
            console.print(f"\n[bold]Notes[/bold]")
            console.print(f"  {notes}")

        # Scores
        score_table = Table(title="Scores")
        score_table.add_column("Metric", style="bold", width=16)
        score_table.add_column("Value", justify="right", width=10)

        fv = m.fitness_vector
        if fv and "total" in fv:
            score_table.add_row("Fitness (total)", f"{fv['total']:.3f}")
        if m.novelty_score is not None:
            score_table.add_row("Novelty", f"{m.novelty_score:.3f}")
        if m.potential_score is not None:
            score_table.add_row("Potential", f"{m.potential_score:.3f}")
        score_table.add_row("Retrievals", str(m.retrieval_count))
        score_table.add_row("Successes", str(m.success_count))
        score_table.add_row("Failures", str(m.failure_count))
        console.print(score_table)

        usage_stats = await repository.get_methodology_usage_stats_for_methodology(m.id)
        usage_entries = await repository.get_methodology_usage_for_methodology(m.id, limit=12)
        if usage_entries:
            usage_table = Table(title="Usage Attribution")
            usage_table.add_column("Metric", style="bold", width=22)
            usage_table.add_column("Value", justify="right", width=12)
            usage_table.add_row("Retrieved", str(usage_stats.get("retrieved_count", 0)))
            usage_table.add_row("Used In Outcomes", str(usage_stats.get("used_count", 0)))
            usage_table.add_row("Attributed", str(usage_stats.get("attributed_count", 0)))
            usage_table.add_row("Attributed Success", str(usage_stats.get("attributed_success_count", 0)))
            usage_table.add_row("Attributed Failure", str(usage_stats.get("attributed_failure_count", 0)))
            usage_table.add_row(
                "Avg Expectation Match",
                "-" if usage_stats.get("avg_expectation_match_score") is None else f"{float(usage_stats['avg_expectation_match_score']):.2f}",
            )
            usage_table.add_row(
                "Avg Quality",
                "-" if usage_stats.get("avg_quality_score") is None else f"{float(usage_stats['avg_quality_score']):.2f}",
            )
            usage_table.add_row(
                "Last Used",
                str(usage_stats.get("last_used_at") or "-"),
            )
            console.print(usage_table)

            recent_table = Table(title="Recent Usage Events")
            recent_table.add_column("Task", style="cyan", width=8)
            recent_table.add_column("Stage", width=18)
            recent_table.add_column("Success", width=8)
            recent_table.add_column("Expect", justify="right", width=7)
            recent_table.add_column("Quality", justify="right", width=7)
            recent_table.add_column("Agent", width=10)
            for entry in usage_entries[:8]:
                recent_table.add_row(
                    entry.task_id[:8],
                    entry.stage,
                    "-" if entry.success is None else ("yes" if entry.success else "no"),
                    "-" if entry.expectation_match_score is None else f"{float(entry.expectation_match_score):.2f}",
                    "-" if entry.quality_score is None else f"{float(entry.quality_score):.2f}",
                    entry.agent_id or "-",
                )
            console.print(recent_table)

        # Capability data
        cd = m.capability_data
        if cd:
            cap_table = Table(title="Capability Data")
            cap_table.add_column("Field", style="bold", width=18)
            cap_table.add_column("Value", max_width=50)
            cap_table.add_row("Type", cd.get("capability_type", "-"))
            cap_table.add_row("Domains", ", ".join(cd.get("domain", [])))
            cap_table.add_row(
                "Inputs",
                ", ".join(
                    f"{item.get('name', '?')}:{item.get('type', '?')}"
                    for item in cd.get("inputs", [])[:4]
                    if isinstance(item, dict)
                ) or "-",
            )
            cap_table.add_row(
                "Outputs",
                ", ".join(
                    f"{item.get('name', '?')}:{item.get('type', '?')}"
                    for item in cd.get("outputs", [])[:4]
                    if isinstance(item, dict)
                ) or "-",
            )
            composability = cd.get("composability", {}) if isinstance(cd.get("composability"), dict) else {}
            cap_table.add_row("Standalone", str(composability.get("standalone", "-")))
            cap_table.add_row("Triggers", ", ".join(cd.get("activation_triggers", [])[:5]) or "-")
            cap_table.add_row("Source Repos", ", ".join(cd.get("source_repos", [])[:4]) or "-")
            console.print(cap_table)

        # Metadata
        meta_parts = []
        if m.tags:
            meta_parts.append(f"Tags: {', '.join(m.tags)}")
        if m.language:
            meta_parts.append(f"Language: {m.language}")
        if m.files_affected:
            meta_parts.append(f"Files: {', '.join(m.files_affected[:5])}")
        if m.methodology_type:
            meta_parts.append(f"Type: {m.methodology_type}")
        if m.scope:
            meta_parts.append(f"Scope: {m.scope}")
        if meta_parts:
            console.print(f"\n[bold]Metadata[/bold]")
            for part in meta_parts:
                console.print(f"  {part}")

        # Related synergies
        links = await repository.get_methodology_links(m.id)
        if links:
            link_table = Table(title=f"Related Links ({len(links)})")
            link_table.add_column("Type", width=14)
            link_table.add_column("Linked To", width=10)
            link_table.add_column("Strength", justify="right", width=8)
            for link in links[:10]:
                other_id = link["target_id"] if link["source_id"] == m.id else link["source_id"]
                link_table.add_row(
                    link["link_type"],
                    other_id[:8] + "…",
                    f"{link['strength']:.2f}",
                )
            console.print(link_table)
            if len(links) > 10:
                console.print(f"  [dim]... and {len(links) - 10} more links[/dim]")

    finally:
        await engine.close()


@kb_app.command()
def patterns(
    limit: int = typer.Option(10, "--limit", "-n", help="Number of promoted global patterns to show"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Show globally promoted methodologies with attribution-backed evidence."""
    asyncio.run(_kb_patterns_async(limit))


async def _kb_patterns_async(limit: int) -> None:
    from rich.panel import Panel
    from claw.evolution.pattern_learner import PatternLearner

    engine, repository = await _kb_engine()
    try:
        patterns = await PatternLearner(repository).get_global_patterns(limit=limit)
        if not patterns:
            console.print("[yellow]No global patterns found yet.[/yellow]")
            return

        console.print(Panel.fit(
            f"[bold cyan]Global Patterns[/bold cyan]\n"
            f"[bold]{len(patterns)}[/bold] promoted methodologies with evidence summaries",
            border_style="cyan",
        ))

        table = Table(show_lines=True)
        table.add_column("ID", width=8, style="cyan")
        table.add_column("Description", max_width=42)
        table.add_column("State", width=10)
        table.add_column("Succ", justify="right", width=6)
        table.add_column("Attr", justify="right", width=6)
        table.add_column("Expect", justify="right", width=7)
        table.add_column("Evidence", width=10)

        for item in patterns:
            expectation_score = item.get("avg_expectation_match_score")
            table.add_row(
                item["methodology_id"][:8],
                item["problem_description"][:42],
                item.get("lifecycle_state", "-"),
                str(item.get("success_count", 0)),
                str(item.get("attributed_success_count", 0)),
                "-" if expectation_score is None else f"{float(expectation_score):.2f}",
                str(item.get("evidence_source", "legacy")),
            )
        console.print(table)
        console.print("\n[dim]Use 'cam kb capability <id>' to inspect attribution history for a specific promoted methodology.[/dim]")
    finally:
        await engine.close()


@kb_app.command()
def domains(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Domain landscape — which knowledge domains exist and bridge capabilities."""
    asyncio.run(_kb_domains_async())


async def _kb_domains_async() -> None:
    from rich.panel import Panel

    engine, repository = await _kb_engine()

    try:
        total = await repository.count_methodologies()
        if total == 0:
            console.print("[yellow]No capabilities in knowledge base. Run 'cam mine <dir>' first.[/yellow]")
            return

        domain_dist = await repository.get_domain_distribution()
        if not domain_dist:
            console.print("[yellow]No domain data. Capabilities may not have been enriched yet.[/yellow]")
            return

        sorted_domains = sorted(domain_dist.items(), key=lambda x: -x[1])
        max_count = sorted_domains[0][1] if sorted_domains else 1
        total_domains = len(sorted_domains)
        total_tagged = sum(v for v in domain_dist.values())

        console.print(Panel.fit(
            f"[bold cyan]Domain Landscape[/bold cyan]\n"
            f"[bold]{total_domains}[/bold] domains across [bold]{total:,}[/bold] capabilities\n"
            f"[bold]{total_tagged:,}[/bold] total domain tags (capabilities can span multiple domains)",
            border_style="cyan",
        ))

        # Full domain table
        domain_table = Table(title=f"All Domains ({total_domains})")
        domain_table.add_column("#", style="dim", width=3)
        domain_table.add_column("Domain", style="cyan", max_width=30)
        domain_table.add_column("Caps", justify="right", width=6)
        domain_table.add_column("", width=30)

        for i, (domain, count) in enumerate(sorted_domains, 1):
            bar_len = min(int(count / max_count * 25), 25)
            bar = "█" * bar_len
            domain_table.add_row(str(i), domain, str(count), f"[cyan]{bar}[/cyan]")

        console.print(domain_table)

        # Bridge Capabilities — spanning 3+ domains
        bridges = await repository.get_cross_domain_capabilities(min_domains=3, limit=15)
        if bridges:
            bridge_table = Table(title=f"Bridge Capabilities (3+ domains, showing {len(bridges)})")
            bridge_table.add_column("ID", width=8)
            bridge_table.add_column("Description", max_width=40)
            bridge_table.add_column("Domains", max_width=40)
            bridge_table.add_column("Novelty", justify="right", width=8)

            for m in bridges:
                domains = (m.capability_data or {}).get("domain", [])
                novelty_str = f"{m.novelty_score:.3f}" if m.novelty_score is not None else "-"
                bridge_table.add_row(
                    m.id[:8],
                    m.problem_description[:40],
                    ", ".join(domains),
                    novelty_str,
                )
            console.print(bridge_table)
        else:
            console.print("[dim]No bridge capabilities (spanning 3+ domains) found.[/dim]")

    finally:
        await engine.close()


@kb_app.command(name="synergies")
def kb_synergies(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of top synergy edges"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Cross-repo synthesis explorer — top synergy edges and connections."""
    asyncio.run(_kb_synergies_async(limit))


async def _kb_synergies_async(limit: int) -> None:
    from rich.panel import Panel

    engine, repository = await _kb_engine()

    try:
        stats = await repository.get_synergy_stats()
        total_explored = stats["total_explored"]

        if total_explored == 0:
            console.print("[yellow]No synergy data. Run 'cam mine <dir>' to build the synergy graph.[/yellow]")
            return

        by_result = stats.get("by_result", {})
        synergy_count = by_result.get("synergy", 0)

        console.print(Panel.fit(
            f"[bold cyan]Synergy Explorer[/bold cyan]\n"
            f"[bold]{total_explored:,}[/bold] pairs explored  |  "
            f"[bold]{synergy_count:,}[/bold] synergies found  |  "
            f"[bold]{stats['synergy_edges']}[/bold] graph edges\n"
            f"Avg synergy score: [bold]{stats['avg_synergy_score']:.4f}[/bold]",
            border_style="cyan",
        ))

        # Exploration stats
        stats_table = Table(title="Exploration Summary")
        stats_table.add_column("Result", style="bold", width=18)
        stats_table.add_column("Count", justify="right", width=10)
        for result_type, count in sorted(by_result.items(), key=lambda x: -x[1]):
            style = {"synergy": "green", "no_synergy": "dim", "stale": "yellow"}.get(result_type, "")
            stats_table.add_row(
                f"[{style}]{result_type}[/{style}]" if style else result_type,
                str(count),
            )
        console.print(stats_table)

        # Top synergy edges
        top_edges = await repository.get_top_synergy_edges(limit=limit)
        if top_edges:
            edge_table = Table(title=f"Top {len(top_edges)} Synergy Edges")
            edge_table.add_column("#", style="dim", width=3)
            edge_table.add_column("Score", justify="right", width=7, style="bold green")
            edge_table.add_column("Type", width=14)
            edge_table.add_column("Capability A", max_width=35)
            edge_table.add_column("Capability B", max_width=35)
            edge_table.add_column("Cross?", width=6)

            cross_count = 0
            for i, edge in enumerate(top_edges, 1):
                is_cross = bool(
                    set(edge["cap_a_domains"]) and set(edge["cap_b_domains"])
                    and not set(edge["cap_a_domains"]) & set(edge["cap_b_domains"])
                )
                if is_cross:
                    cross_count += 1
                cross_str = "[bold yellow]YES[/bold yellow]" if is_cross else ""
                edge_table.add_row(
                    str(i),
                    f"{edge['synergy_score']:.3f}",
                    edge["synergy_type"][:14],
                    edge["cap_a_summary"][:35],
                    edge["cap_b_summary"][:35],
                    cross_str,
                )
            console.print(edge_table)

            if cross_count > 0:
                console.print(
                    f"\n  [bold yellow]{cross_count}[/bold yellow] cross-domain synergies "
                    f"(capabilities from different domains connected)"
                )
        else:
            console.print("[dim]No synergy edges found.[/dim]")

    finally:
        await engine.close()


@kb_app.command(name="brains")
def kb_brains(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Show brain (language) distribution across all ganglia."""
    asyncio.run(_kb_brains_async())


async def _kb_brains_async() -> None:
    """Display per-brain methodology counts across primary + sibling ganglia."""
    from claw.core.config import DatabaseConfig, load_config
    from claw.db.engine import DatabaseEngine

    cfg = load_config()

    # Collect counts from primary DB
    brains_data: dict[str, dict[str, Any]] = {}

    async def _count_brains(db_path: str, ganglion_name: str) -> None:
        try:
            engine = DatabaseEngine(DatabaseConfig(db_path=db_path))
            await engine.connect()
            try:
                rows = await engine.fetch_all(
                    "SELECT language, COUNT(*) as cnt FROM methodologies "
                    "WHERE lifecycle_state != 'dead' GROUP BY language"
                )
                for row in rows:
                    lang = row["language"] or "unknown"
                    from claw.miner import _LANGUAGE_TO_BRAIN
                    brain_name = _LANGUAGE_TO_BRAIN.get(lang, "misc")
                    key = f"{brain_name}:{ganglion_name}"
                    if key not in brains_data:
                        brains_data[key] = {
                            "brain": brain_name,
                            "ganglion": ganglion_name,
                            "count": 0,
                        }
                    brains_data[key]["count"] += row["cnt"]
            finally:
                await engine.close()
        except Exception as e:
            console.print(f"  [dim]Skipping {ganglion_name}: {e}[/dim]")

    # Primary DB
    await _count_brains(cfg.database.db_path, "primary")

    # Sibling ganglia
    for sib in cfg.instances.siblings:
        await _count_brains(sib.db_path, sib.name)

    if not brains_data:
        console.print("[yellow]No methodologies found in any ganglion.[/yellow]")
        return

    # Aggregate by brain
    brain_totals: dict[str, int] = {}
    brain_ganglia: dict[str, list[str]] = {}
    for _key, data in brains_data.items():
        b = data["brain"]
        brain_totals[b] = brain_totals.get(b, 0) + data["count"]
        if data["count"] > 0:
            brain_ganglia.setdefault(b, []).append(
                f"{data['ganglion']} ({data['count']})"
            )

    table = Table(title="CAM Brain Distribution")
    table.add_column("Brain", style="bold cyan", width=14)
    table.add_column("Methodologies", justify="right", style="green", width=15)
    table.add_column("Ganglia", max_width=50)

    for brain_name in ["python", "typescript", "go", "rust", "misc"]:
        count = brain_totals.get(brain_name, 0)
        ganglia_str = ", ".join(brain_ganglia.get(brain_name, ["(none)"]))
        table.add_row(brain_name, str(count), ganglia_str)

    console.print(table)
    total = sum(brain_totals.values())
    console.print(f"\n  Total: [bold]{total:,}[/bold] methodologies across "
                  f"[bold]{1 + len(cfg.instances.siblings)}[/bold] ganglia")


@kb_app.command(name="export-kit")
def kb_export_kit(
    brain: str = typer.Option("python", "--brain", "-b", help="Brain name to export from"),
    category: Optional[str] = typer.Option(None, "--category", help="Category filter"),
    top: int = typer.Option(10, "--top", "-n", help="Number of top methodologies"),
    output: str = typer.Option(..., "--output", "-o", help="Output directory path"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing directory"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Export top methodologies as a JourneyKits-compatible directory."""
    asyncio.run(_kb_export_kit_async(brain, category, top, Path(output), force))


async def _kb_export_kit_async(
    brain: str, category: Optional[str], top_n: int, output_dir: Path, force: bool,
) -> None:
    from claw.community.kit_exporter import export_kit
    from claw.core.config import load_config
    from claw.db.engine import DatabaseEngine

    cfg = load_config()
    engine = DatabaseEngine(cfg.database)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()

    try:
        result = await export_kit(
            engine=engine,
            output_dir=output_dir,
            brain=brain,
            category=category,
            top_n=top_n,
            instance_name=getattr(cfg.instances, "instance_name", ""),
            force=force,
        )
        console.print(f"[green]Kit exported:[/green] {result['kit_name']}")
        console.print(f"  Methodologies: {result['methodology_count']}")
        console.print(f"  Output: {result['output_path']}")
        console.print(f"  Manifest hash: {result['manifest_hash'][:16]}...")
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
    finally:
        await engine.close()


# ---------------------------------------------------------------------------
# pulse — CAM-PULSE command group
# ---------------------------------------------------------------------------

async def _pulse_engine():
    """Shared async setup for pulse commands — returns (engine, config)."""
    from claw.core.config import load_config
    from claw.db.engine import DatabaseEngine

    config = load_config()
    engine = DatabaseEngine(config.database)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    return engine, config


async def _pulse_orchestrator(engine, config):
    """Build a full PulseOrchestrator from engine + config."""
    from claw.db.embeddings import EmbeddingEngine
    from claw.db.repository import Repository
    from claw.llm.client import LLMClient
    from claw.memory.hybrid_search import HybridSearch
    from claw.memory.semantic import SemanticMemory
    from claw.miner import RepoMiner
    from claw.pulse.assimilator import PulseAssimilator
    from claw.pulse.novelty import NoveltyFilter
    from claw.pulse.orchestrator import PulseOrchestrator
    from claw.pulse.scout import XScout

    repository = Repository(engine)
    llm_client = LLMClient(config.llm)
    embedding_engine = EmbeddingEngine()
    hybrid_search = HybridSearch(repository, embedding_engine)
    semantic_memory = SemanticMemory(repository, embedding_engine, hybrid_search)

    scout = XScout(config.pulse)
    novelty = NoveltyFilter(engine, embedding_engine, config.pulse)
    miner = RepoMiner(repository, llm_client, semantic_memory, config)
    assimilator = PulseAssimilator(engine, miner, config)

    return PulseOrchestrator(
        engine=engine,
        scout=scout,
        novelty=novelty,
        assimilator=assimilator,
        config=config,
    )


@pulse_app.command(name="scan")
def pulse_scan(
    keywords: Optional[str] = typer.Option(None, "--keywords", "-k", help="Comma-separated search keywords"),
    from_date: Optional[str] = typer.Option(None, "--from-date", help="Start date (YYYY-MM-DD)"),
    to_date: Optional[str] = typer.Option(None, "--to-date", help="End date (YYYY-MM-DD)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Scan and filter only, skip assimilation"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show debug logging (API calls, responses)"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """One-shot X scan: discover GitHub repos, filter, and assimilate."""
    import asyncio

    _setup_logging(verbose)

    async def _run():
        engine, cfg = await _pulse_engine()
        try:
            orch = await _pulse_orchestrator(engine, cfg)
            kw_list = [k.strip() for k in keywords.split(",")] if keywords else None

            # Show what we're about to do
            display_kw = kw_list or cfg.pulse.keywords
            console.print(f"[dim]Scanning X via {cfg.pulse.xai_model} with {len(display_kw)} keyword(s)...[/dim]")
            for kw in display_kw:
                console.print(f"[dim]  → {kw}[/dim]")

            result = await orch.run_single_scan(
                keywords=kw_list,
                from_date=from_date,
                to_date=to_date,
                dry_run=dry_run,
            )
            console.print(orch.build_scan_report(result))

            # If 0 results, give the user useful context
            disc_count = len(result.discoveries) if hasattr(result, "discoveries") else 0
            if disc_count == 0:
                console.print(f"[dim]Tip: 0 discoveries can mean:[/dim]")
                console.print(f"[dim]  • No X posts matched your keywords for this date range[/dim]")
                console.print(f"[dim]  • Try broader keywords or a wider date range[/dim]")
                console.print(f"[dim]  • Run with --verbose to see the raw API response[/dim]")
        finally:
            await engine.close()

    asyncio.run(_run())


@pulse_app.command(name="daemon")
def pulse_daemon(
    interval: Optional[int] = typer.Option(None, "--interval", "-i", help="Poll interval in minutes (overrides config)"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Start perpetual polling daemon."""
    import asyncio

    async def _run():
        engine, cfg = await _pulse_engine()
        if interval is not None:
            cfg.pulse.poll_interval_minutes = interval
        try:
            orch = await _pulse_orchestrator(engine, cfg)
            console.print(f"[bold green]PULSE daemon starting[/bold green] (interval={cfg.pulse.poll_interval_minutes}m)")
            await orch.run_daemon()
        finally:
            await engine.close()

    asyncio.run(_run())


@pulse_app.command(name="status")
def pulse_status(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Show discovery statistics."""
    import asyncio
    from claw.pulse.dashboard import PulseDashboard

    async def _run():
        engine, cfg = await _pulse_engine()
        try:
            dash = PulseDashboard(engine)
            await dash.show_stats()
        finally:
            await engine.close()

    asyncio.run(_run())


@pulse_app.command(name="discoveries")
def pulse_discoveries(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status (discovered, assimilated, failed, etc.)"),
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum rows to display"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """List recent discoveries."""
    import asyncio
    from claw.pulse.dashboard import PulseDashboard

    async def _run():
        engine, cfg = await _pulse_engine()
        try:
            dash = PulseDashboard(engine)
            await dash.show_novel(limit=limit)
        finally:
            await engine.close()

    asyncio.run(_run())


@pulse_app.command(name="scans")
def pulse_scans(
    limit: int = typer.Option(10, "--limit", "-n", help="Maximum scan sessions to display"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Show scan history."""
    import asyncio
    from claw.pulse.dashboard import PulseDashboard

    async def _run():
        engine, cfg = await _pulse_engine()
        try:
            dash = PulseDashboard(engine)
            await dash.show_scans(limit=limit)
        finally:
            await engine.close()

    asyncio.run(_run())


@pulse_app.command(name="report")
def pulse_report(
    date: Optional[str] = typer.Option(None, "--date", "-d", help="Date for report (YYYY-MM-DD), defaults to today"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Generate daily summary report."""
    import asyncio
    from claw.pulse.dashboard import PulseDashboard

    async def _run():
        engine, cfg = await _pulse_engine()
        try:
            dash = PulseDashboard(engine)
            await dash.show_daily_report(date=date)
        finally:
            await engine.close()

    asyncio.run(_run())


@pulse_app.command(name="preflight")
def pulse_preflight(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Validate PULSE configuration and API key."""
    from claw.core.config import load_config
    from claw.pulse.scout import XScout

    cfg = load_config()
    scout = XScout(cfg.pulse)
    ok, msg = scout.check_api_key()

    if ok:
        console.print(f"[green]OK[/green]: {msg}")
        console.print(f"Model: {cfg.pulse.xai_model}")
        console.print(f"Keywords: {len(cfg.pulse.keywords)}")
        console.print(f"Novelty threshold: {cfg.pulse.novelty_threshold}")
        console.print(f"Poll interval: {cfg.pulse.poll_interval_minutes}m")
        console.print(f"Max cost/day: ${cfg.pulse.max_cost_per_day_usd:.2f}")
    else:
        console.print(f"[red]FAIL[/red]: {msg}")
        raise typer.Exit(1)


def _normalize_github_url(raw_url: str) -> Optional[str]:
    """Normalize a GitHub URL to canonical form: https://github.com/{owner}/{repo}.

    Strips trailing /, .git, query params, fragments. Lowercases owner/repo.
    Returns None if the URL is not a valid GitHub repo URL.
    """
    import re
    from urllib.parse import urlparse

    url = raw_url.strip()

    # Parse and rebuild
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host not in ("github.com", "www.github.com"):
        return None

    path = parsed.path.strip("/")
    # Remove .git suffix
    if path.endswith(".git"):
        path = path[:-4]
    # Remove trailing slashes and extra path segments (tree/main, blob/...)
    parts = path.split("/")
    if len(parts) < 2:
        return None

    owner, repo = parts[0], parts[1]
    if not owner or not repo:
        return None

    # Validate characters
    if not re.match(r'^[A-Za-z0-9_.-]+$', owner) or not re.match(r'^[A-Za-z0-9_.-]+$', repo):
        return None

    return f"https://github.com/{owner.lower()}/{repo.lower()}"


def _normalize_repo_url(raw_url: str) -> Optional[str]:
    """Normalize a GitHub or HuggingFace repo URL to canonical form.

    Returns:
        'https://github.com/{owner}/{repo}' for GitHub URLs
        'https://huggingface.co/{owner}/{repo}' for HF URLs
        None if the URL doesn't match either pattern.
    """
    from urllib.parse import urlparse

    url = raw_url.strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    # Try GitHub first
    if host in ("github.com", "www.github.com"):
        return _normalize_github_url(raw_url)

    # HuggingFace
    if host in ("huggingface.co", "www.huggingface.co"):
        path = parsed.path.strip("/")
        parts = path.split("/")
        if len(parts) < 2:
            return None
        owner, repo = parts[0], parts[1]
        if not owner or not repo:
            return None
        return f"https://huggingface.co/{owner}/{repo}"

    return None


@pulse_app.command(name="ingest")
def pulse_ingest(
    urls: list[str] = typer.Argument(..., help="GitHub repo URLs to ingest"),
    novelty: float = typer.Option(0.95, "--novelty", "-n", help="Preset novelty score (0.0-1.0)"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-ingest even if already assimilated"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Ingest prescreened GitHub repos directly, bypassing X-Scout discovery."""
    import asyncio

    _setup_logging(verbose)

    async def _run():
        from datetime import UTC, datetime

        engine, cfg = await _pulse_engine()
        try:
            orch = await _pulse_orchestrator(engine, cfg)
            assimilator = orch.assimilator
            novelty_filter = orch.novelty

            scan_id = f"ingest-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
            total_methodologies = 0
            ingested = 0
            skipped = 0
            errors = []

            # Log scan start
            await engine.execute(
                "INSERT INTO pulse_scan_log (id, keywords) VALUES (?, ?)",
                [scan_id, '["prescreened"]'],
            )

            console.print(f"\n[bold]PULSE Ingest[/bold] — {len(urls)} prescreened repo(s)")
            console.print(f"  Novelty score: {novelty}")
            console.print(f"  Scan ID: {scan_id}\n")

            for raw_url in urls:
                canonical = _normalize_github_url(raw_url)
                if not canonical:
                    console.print(f"  [red]SKIP[/red] {raw_url} — not a valid GitHub repo URL")
                    errors.append(f"{raw_url}: invalid URL")
                    continue

                repo_label = canonical.replace("https://github.com/", "")

                # Dedup check
                already_known = await novelty_filter.is_already_known(canonical)
                if already_known and not force:
                    console.print(f"  [yellow]KNOWN[/yellow] {repo_label} — already assimilated (use --force to re-ingest)")
                    skipped += 1
                    continue
                elif already_known:
                    console.print(f"  [yellow]FORCE[/yellow] {repo_label} — re-ingesting despite existing record")

                # Create discovery
                from claw.pulse.models import PulseDiscovery

                disc = PulseDiscovery(
                    github_url=raw_url,
                    canonical_url=canonical,
                    x_post_text="Prescreened by user",
                    keywords_matched=["prescreened"],
                    novelty_score=novelty,
                    scan_id=scan_id,
                )

                try:
                    await assimilator.save_discovery(disc)
                    result = await assimilator.assimilate(disc, "pulse-default")

                    if result.success:
                        ingested += 1
                        total_methodologies += len(result.methodology_ids)
                        console.print(
                            f"  [green]OK[/green] {repo_label} — "
                            f"{result.findings_count} findings, "
                            f"{len(result.methodology_ids)} methodologies"
                        )
                    else:
                        errors.append(f"{repo_label}: {result.error}")
                        console.print(f"  [red]FAIL[/red] {repo_label} — {result.error}")
                except Exception as e:
                    errors.append(f"{repo_label}: {e}")
                    console.print(f"  [red]ERROR[/red] {repo_label} — {e}")

            # Log scan complete
            await engine.execute(
                """UPDATE pulse_scan_log
                   SET completed_at = ?, repos_discovered = ?, repos_novel = ?,
                       repos_assimilated = ?, error_detail = ?
                   WHERE id = ?""",
                [
                    datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    len(urls),
                    len(urls) - skipped,
                    ingested,
                    json.dumps(errors) if errors else None,
                    scan_id,
                ],
            )

            # Summary
            console.print(f"\n[bold]Summary[/bold]")
            console.print(f"  Ingested: {ingested}/{len(urls)}")
            console.print(f"  Methodologies: {total_methodologies}")
            if skipped:
                console.print(f"  Skipped (already known): {skipped}")
            if errors:
                console.print(f"  Errors: {len(errors)}")

        finally:
            await engine.close()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# HuggingFace Repo Ingestion
# ---------------------------------------------------------------------------


@pulse_app.command(name="ingest-hf")
def pulse_ingest_hf(
    repo_ids: list[str] = typer.Argument(..., help="HuggingFace repo IDs (e.g., d4data/biomedical-ner-all)"),
    revision: str = typer.Option("main", "--revision", "-r", help="Git revision to mount (branch, tag, SHA)"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-ingest even if already assimilated"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Ingest HuggingFace repos via hf-mount (or fallback download)."""
    import asyncio

    _setup_logging(verbose)

    async def _run():
        engine, cfg = await _pulse_engine()
        try:
            orch = await _pulse_orchestrator(engine, cfg)
            assimilator = orch.assimilator
            novelty_filter = orch.novelty

            scan_id = f"hf-ingest-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
            total_methodologies = 0
            ingested = 0
            skipped = 0
            errors = []

            await engine.execute(
                "INSERT INTO pulse_scan_log (id, keywords) VALUES (?, ?)",
                [scan_id, '["hf-ingest"]'],
            )

            console.print(f"\n[bold]PULSE HF Ingest[/bold] — {len(repo_ids)} repo(s)")
            console.print(f"  Revision: {revision}")
            console.print(f"  Scan ID: {scan_id}\n")

            from claw.pulse.hf_adapter import hf_mount_available

            if hf_mount_available():
                console.print("  [green]hf-mount detected[/green] — will use mount for ingestion\n")
            else:
                console.print("  [yellow]hf-mount not found[/yellow] — will fallback to huggingface_hub download\n")

            for repo_id in repo_ids:
                repo_id = repo_id.strip()
                if "/" not in repo_id:
                    console.print(f"  [red]SKIP[/red] {repo_id} — not a valid HF repo ID (expected owner/name)")
                    errors.append(f"{repo_id}: invalid format")
                    continue

                canonical_url = f"https://huggingface.co/{repo_id}"

                # Dedup check
                already_known = await novelty_filter.is_already_known(canonical_url)
                if already_known and not force:
                    console.print(f"  [yellow]KNOWN[/yellow] {repo_id} — already assimilated (use --force)")
                    skipped += 1
                    continue
                elif already_known:
                    console.print(f"  [yellow]FORCE[/yellow] {repo_id} — re-ingesting despite existing record")

                try:
                    result = await assimilator.assimilate_hf_repo(
                        repo_id, "pulse-default", revision=revision
                    )

                    if result.success:
                        ingested += 1
                        total_methodologies += len(result.methodology_ids)
                        console.print(
                            f"  [green]OK[/green] {repo_id} — "
                            f"{result.findings_count} findings, "
                            f"{len(result.methodology_ids)} methodologies"
                        )
                    else:
                        errors.append(f"{repo_id}: {result.error}")
                        console.print(f"  [red]FAIL[/red] {repo_id} — {result.error}")
                except Exception as e:
                    errors.append(f"{repo_id}: {e}")
                    console.print(f"  [red]ERROR[/red] {repo_id} — {e}")

            await engine.execute(
                """UPDATE pulse_scan_log
                   SET completed_at = ?, repos_discovered = ?, repos_novel = ?,
                       repos_assimilated = ?, error_detail = ?
                   WHERE id = ?""",
                [
                    datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    len(repo_ids),
                    len(repo_ids) - skipped,
                    ingested,
                    json.dumps(errors) if errors else None,
                    scan_id,
                ],
            )

            console.print(f"\n[bold]Summary[/bold]")
            console.print(f"  Ingested: {ingested}/{len(repo_ids)}")
            console.print(f"  Methodologies: {total_methodologies}")
            if skipped:
                console.print(f"  Skipped (already known): {skipped}")
            if errors:
                console.print(f"  Errors: {len(errors)}")

        finally:
            await engine.close()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Freshness Monitor Commands
# ---------------------------------------------------------------------------


def _backup_database(db_path: str) -> str | None:
    """Create a timestamped backup of the database before destructive operations.

    Returns the backup path on success, None on failure.
    """
    import shutil
    from datetime import UTC, datetime

    src = Path(db_path)
    if not src.exists() or str(src) == ":memory:":
        return None

    backup_dir = src.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{src.stem}_pre_refresh_{timestamp}{src.suffix}"

    try:
        shutil.copy2(src, backup_path)
        # Also copy WAL file if present
        wal_path = Path(f"{src}-wal")
        if wal_path.exists():
            shutil.copy2(wal_path, Path(f"{backup_path}-wal"))
        shm_path = Path(f"{src}-shm")
        if shm_path.exists():
            shutil.copy2(shm_path, Path(f"{backup_path}-shm"))
        return str(backup_path)
    except Exception as e:
        logging.getLogger("claw.cli").warning("Database backup failed: %s", e)
        return None


def _confirm_retirement(retired_ids: list[str], repo_label: str) -> bool:
    """Prompt user to confirm bulk methodology retirement.

    Returns True if user confirms, False to skip.
    """
    count = len(retired_ids)
    console.print(
        f"\n  [yellow bold]WARNING:[/yellow bold] About to retire {count} methodology(ies) from {repo_label}:"
    )
    for mid in retired_ids[:10]:
        console.print(f"    - {mid}")
    if count > 10:
        console.print(f"    ... and {count - 10} more")

    try:
        answer = typer.confirm("  Proceed with retirement?", default=False)
        return answer
    except (click.Abort, KeyboardInterrupt):
        return False


@pulse_app.command(name="freshness")
def pulse_freshness(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show debug logging"),
    auto_refresh: bool = typer.Option(False, "--auto-refresh", help="Automatically re-mine stale repos"),
    seed: bool = typer.Option(False, "--seed", help="Populate freshness metadata for repos with NULL values"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Check freshness without modifying database"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Check all tracked repos for staleness and report significance scores."""
    import asyncio

    _setup_logging(verbose)

    async def _run():
        engine, cfg = await _pulse_engine()
        try:
            from claw.pulse.freshness import FreshnessMonitor

            monitor = FreshnessMonitor(engine, cfg)

            mode_label = " [dim](DRY RUN)[/dim]" if dry_run else ""
            console.print(f"\n[bold]PULSE Freshness Check[/bold]{mode_label}\n")

            if seed and not dry_run:
                console.print("[bold]Seeding freshness metadata for existing repos...[/bold]\n")
                seeded = await monitor.seed_existing_repos()
                console.print(f"  Seeded {seeded} repos with freshness metadata.\n")
            elif seed and dry_run:
                console.print("  [dim]--seed skipped in dry-run mode[/dim]\n")

            results = await monitor.check_all()

            if not results:
                console.print("  No assimilated repos to check.")
                return

            # Display results table
            table = Table(title="Repo Freshness Status")
            table.add_column("Repository", style="cyan", min_width=30)
            table.add_column("Last Checked", style="dim")
            table.add_column("Significance", justify="right")
            table.add_column("Commits", justify="right")
            table.add_column("New Release", justify="center")
            table.add_column("README", justify="center")
            table.add_column("Status", min_width=10)

            stale_urls = []

            for r in results:
                repo_label = r.canonical_url.replace("https://github.com/", "")

                if r.error:
                    table.add_row(repo_label, "-", "-", "-", "-", "-", f"[red]ERROR: {r.error[:30]}[/red]")
                    continue

                sig = f"{r.significance_score:.2f}"
                commits = str(r.commits_since_mine) if r.commits_since_mine else "-"
                release = "[green]Yes[/green]" if r.has_new_release else "-"
                readme = "[green]Yes[/green]" if r.readme_changed else "-"

                if r.needs_refresh:
                    status = "[red bold]STALE[/red bold]"
                    stale_urls.append(r.canonical_url)
                elif r.significance_score > 0:
                    status = "[yellow]Changed[/yellow]"
                else:
                    status = "[green]Fresh[/green]"

                table.add_row(repo_label, "-", sig, commits, release, readme, status)

            console.print(table)

            # Summary
            fresh = sum(1 for r in results if not r.needs_refresh and not r.error)
            stale = len(stale_urls)
            errors = sum(1 for r in results if r.error)

            console.print(f"\n  [green]Fresh:[/green] {fresh}  [red]Stale:[/red] {stale}  [dim]Errors:[/dim] {errors}")

            if stale_urls and auto_refresh and dry_run:
                # Dry-run: preview what WOULD happen
                console.print(f"\n[bold]DRY RUN:[/bold] Would refresh {len(stale_urls)} stale repo(s):\n")
                for url in stale_urls:
                    repo_label = url.replace("https://github.com/", "")
                    would_retire, would_keep = await monitor.preview_retirement(url, [])
                    console.print(
                        f"  {repo_label} — "
                        f"would retire {len(would_retire)} methodology(ies), "
                        f"keep {len(would_keep)}"
                    )
                console.print("\n  [dim]No changes made. Remove --dry-run to execute.[/dim]")

            elif stale_urls and auto_refresh:
                # Create backup before destructive operations
                backup_path = _backup_database(cfg.database.db_path)
                if backup_path:
                    console.print(f"\n  [dim]Database backed up to: {backup_path}[/dim]")

                console.print(f"\n[bold]Auto-refreshing {len(stale_urls)} stale repo(s)...[/bold]\n")
                orch = await _pulse_orchestrator(engine, cfg)
                assimilator = orch.assimilator
                for url in stale_urls:
                    repo_label = url.replace("https://github.com/", "")
                    try:
                        from claw.pulse.models import PulseDiscovery

                        disc = PulseDiscovery(
                            github_url=url,
                            canonical_url=url,
                            x_post_text="Freshness auto-refresh",
                            keywords_matched=["freshness-refresh"],
                            novelty_score=1.0,
                            scan_id=f"refresh-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}",
                        )
                        result = await assimilator.assimilate(disc, "pulse-default")
                        if result.success:
                            # Preview retirement; confirm if > 5
                            would_retire, would_keep = await monitor.preview_retirement(
                                url, result.methodology_ids
                            )
                            if len(would_retire) > 5:
                                if not _confirm_retirement(would_retire, repo_label):
                                    console.print(f"  [yellow]SKIPPED[/yellow] {repo_label} — retirement cancelled")
                                    continue

                            retired, kept = await monitor.retire_stale_methodologies(
                                url, result.methodology_ids
                            )
                            await monitor.update_mine_metadata(url, result.head_sha)
                            console.print(
                                f"  [green]REFRESHED[/green] {repo_label} — "
                                f"{result.findings_count} findings, "
                                f"{len(result.methodology_ids)} methodologies"
                            )
                            if retired:
                                console.print(
                                    f"       [dim]Retired {len(retired)} stale, kept {len(kept)} unchanged[/dim]"
                                )
                        else:
                            console.print(f"  [red]FAIL[/red] {repo_label} — {result.error}")
                    except Exception as e:
                        console.print(f"  [red]ERROR[/red] {repo_label} — {e}")
            elif stale_urls:
                console.print(f"\n  Use [bold]--auto-refresh[/bold] to re-mine stale repos, or:")
                console.print(f"  [dim]cam pulse refresh --all[/dim]")

        finally:
            await engine.close()

    asyncio.run(_run())


@pulse_app.command(name="refresh")
def pulse_refresh(
    url: Optional[str] = typer.Argument(None, help="GitHub repo URL to refresh (or use --all)"),
    all_stale: bool = typer.Option(False, "--all", help="Refresh all stale repos"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip significance check and confirmation prompts"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview what would be refreshed/retired without modifying database"),
    no_backup: bool = typer.Option(False, "--no-backup", help="Skip pre-refresh database backup"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Re-mine a specific repo or all stale repos."""
    import asyncio

    _setup_logging(verbose)

    if not url and not all_stale:
        console.print("[red]Error:[/red] Provide a repo URL or use --all for all stale repos.")
        raise typer.Exit(1)

    async def _run():
        engine, cfg = await _pulse_engine()
        try:
            from claw.pulse.freshness import FreshnessMonitor

            urls_to_refresh: list[str] = []

            if url:
                canonical = _normalize_repo_url(url)
                if not canonical:
                    console.print(f"[red]Error:[/red] Not a valid GitHub or HuggingFace URL: {url}")
                    return
                urls_to_refresh.append(canonical)
            elif all_stale:
                rows = await engine.fetch_all(
                    "SELECT canonical_url FROM pulse_discoveries WHERE freshness_status = 'stale'"
                )
                urls_to_refresh = [r["canonical_url"] for r in rows]
                if not urls_to_refresh:
                    console.print("No stale repos found. Run [bold]cam pulse freshness[/bold] first.")
                    return

            mode_label = " [dim](DRY RUN)[/dim]" if dry_run else ""
            console.print(f"\n[bold]PULSE Refresh[/bold] — {len(urls_to_refresh)} repo(s){mode_label}\n")

            # Dry-run: preview only
            if dry_run:
                monitor = FreshnessMonitor(engine, cfg)
                for repo_url in urls_to_refresh:
                    repo_label = repo_url.replace("https://github.com/", "")
                    would_retire, would_keep = await monitor.preview_retirement(repo_url, [])
                    console.print(
                        f"  {repo_label} — "
                        f"would retire {len(would_retire)}, keep {len(would_keep)}"
                    )
                    if would_retire:
                        for mid in would_retire[:5]:
                            console.print(f"    [dim]retire: {mid}[/dim]")
                        if len(would_retire) > 5:
                            console.print(f"    [dim]... and {len(would_retire) - 5} more[/dim]")
                console.print("\n  [dim]No changes made. Remove --dry-run to execute.[/dim]")
                return

            # Create backup before destructive operations
            if not no_backup:
                backup_path = _backup_database(cfg.database.db_path)
                if backup_path:
                    console.print(f"  [dim]Database backed up to: {backup_path}[/dim]\n")

            orch = await _pulse_orchestrator(engine, cfg)
            assimilator = orch.assimilator
            monitor = FreshnessMonitor(engine, cfg)

            refreshed = 0
            for repo_url in urls_to_refresh:
                repo_label = repo_url.replace("https://github.com/", "")
                try:
                    from claw.pulse.models import PulseDiscovery

                    disc = PulseDiscovery(
                        github_url=repo_url,
                        canonical_url=repo_url,
                        x_post_text="Manual refresh",
                        keywords_matched=["refresh"],
                        novelty_score=1.0,
                        scan_id=f"refresh-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}",
                    )

                    # Mark as refreshing
                    await engine.execute(
                        "UPDATE pulse_discoveries SET freshness_status = 'refreshing' WHERE canonical_url = ?",
                        [repo_url],
                    )

                    result = await assimilator.assimilate(disc, "pulse-default")
                    if result.success:
                        refreshed += 1

                        # Preview retirement; confirm if > 5 (unless --force)
                        would_retire, would_keep = await monitor.preview_retirement(
                            repo_url, result.methodology_ids
                        )
                        if len(would_retire) > 5 and not force:
                            if not _confirm_retirement(would_retire, repo_label):
                                console.print(f"  [yellow]SKIPPED[/yellow] {repo_label} — retirement cancelled")
                                await monitor.update_mine_metadata(repo_url, result.head_sha)
                                continue

                        retired, kept = await monitor.retire_stale_methodologies(
                            repo_url, result.methodology_ids
                        )

                        await monitor.update_mine_metadata(repo_url, result.head_sha)
                        console.print(
                            f"  [green]OK[/green] {repo_label} — "
                            f"{result.findings_count} findings, "
                            f"{len(result.methodology_ids)} new methodologies"
                        )
                        if retired:
                            console.print(
                                f"       [dim]Retired {len(retired)} stale, kept {len(kept)} unchanged[/dim]"
                            )
                    else:
                        console.print(f"  [red]FAIL[/red] {repo_label} — {result.error}")
                except Exception as e:
                    console.print(f"  [red]ERROR[/red] {repo_label} — {e}")

            console.print(f"\n[bold]Summary:[/bold] Refreshed {refreshed}/{len(urls_to_refresh)} repos")

        finally:
            await engine.close()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Self-Enhancement Pipeline Commands
# ---------------------------------------------------------------------------


@self_enhance_app.command(name="status")
def self_enhance_status(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Show trigger readiness and self-enhancement state."""
    _setup_logging(verbose)

    async def _run() -> None:
        from claw.core.config import load_config
        from claw.db.engine import DatabaseEngine

        cfg = load_config(Path(config) if config else None)
        live_dir = Path(config).parent.resolve() if config else Path.cwd().resolve()

        engine = DatabaseEngine(cfg.database)
        await engine.connect()

        try:
            from claw.reconstruct import ReconstructionPipeline
            pipeline = ReconstructionPipeline(cfg, db_engine=engine, live_dir=live_dir)
            assessment = await pipeline.assess_trigger()
            console.print(assessment.summary())

            # Show state
            from claw.reconstruct import _load_state
            state = _load_state(live_dir)
            if state:
                console.print("\n[bold]State:[/bold]")
                for k, v in state.items():
                    console.print(f"  {k}: {v}")
        finally:
            await engine.close()

    asyncio.run(_run())


@self_enhance_app.command(name="start")
def self_enhance_start(
    mode: str = typer.Option("autonomous", "--mode", "-m", help="Mode: attended, supervised, autonomous"),
    max_tasks: int = typer.Option(0, "--max-tasks", help="Max enhancement tasks (0 = config default)"),
    skip_swap: bool = typer.Option(False, "--skip-swap", help="Stop after validation (don't swap)"),
    force: bool = typer.Option(False, "--force", help="Skip trigger assessment"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Run the full self-enhancement pipeline: clone, enhance, validate, swap."""
    _setup_logging(verbose)

    async def _run() -> None:
        from claw.core.config import load_config
        from claw.db.engine import DatabaseEngine

        cfg = load_config(Path(config) if config else None)
        live_dir = Path(config).parent.resolve() if config else Path.cwd().resolve()

        engine = DatabaseEngine(cfg.database)
        await engine.connect()

        try:
            from claw.reconstruct import ReconstructionPipeline
            pipeline = ReconstructionPipeline(cfg, db_engine=engine, live_dir=live_dir)

            def _on_step(step_name: str, detail: str = "") -> None:
                console.print(f"  [dim]{step_name}[/dim] {detail}")

            pipeline.on_step = _on_step

            result = await pipeline.run(
                mode=mode,
                max_tasks=max_tasks,
                skip_swap=skip_swap,
                force=force,
            )

            console.print(f"\n{result.summary()}")

            if result.copy_dir and not result.swap_completed:
                console.print(f"\n[dim]Enhanced copy at: {result.copy_dir}[/dim]")
                console.print("[dim]Use 'cam self-enhance validate <copy_dir>' to re-validate[/dim]")
                console.print("[dim]Use 'cam self-enhance swap <copy_dir>' to swap manually[/dim]")

        finally:
            await engine.close()

    asyncio.run(_run())


@self_enhance_app.command(name="validate")
def self_enhance_validate(
    copy_dir: str = typer.Argument(..., help="Path to the enhanced copy to validate"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Validate an enhanced copy through 7 gates."""
    _setup_logging(verbose)

    async def _run() -> None:
        from claw.core.config import load_config

        cfg = load_config(Path(config) if config else None)
        live_dir = Path(config).parent.resolve() if config else Path.cwd().resolve()

        from claw.reconstruct import ReconstructionPipeline
        pipeline = ReconstructionPipeline(cfg, live_dir=live_dir)
        report = await pipeline.validate(Path(copy_dir).resolve())

        console.print(report.summary())

        # Check protected files
        protected = pipeline.detect_protected_changes(Path(copy_dir).resolve())
        if protected:
            console.print(f"\n[yellow]Protected file changes ({len(protected)}):[/yellow]")
            for pc in protected:
                console.print(f"  {pc.file_path}: +{pc.additions} -{pc.deletions}")

        if report.passed:
            console.print("\n[green]All gates passed. Safe to swap.[/green]")
        else:
            console.print(f"\n[red]FAILED at: {report.failed_gate}[/red]")
            if report.error_detail:
                console.print(f"[red]{report.error_detail[:2000]}[/red]")
            raise typer.Exit(1)

    asyncio.run(_run())


@self_enhance_app.command(name="swap")
def self_enhance_swap(
    copy_dir: str = typer.Argument(..., help="Path to the validated enhanced copy"),
    force: bool = typer.Option(False, "--force", help="Skip re-validation before swap"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Swap a validated enhanced copy into production."""
    _setup_logging(verbose)

    async def _run() -> None:
        from claw.core.config import load_config

        cfg = load_config(Path(config) if config else None)
        live_dir = Path(config).parent.resolve() if config else Path.cwd().resolve()

        from claw.reconstruct import ReconstructionPipeline
        pipeline = ReconstructionPipeline(cfg, live_dir=live_dir)

        copy_path = Path(copy_dir).resolve()

        if not force:
            console.print("Re-validating before swap...")
            report = await pipeline.validate(copy_path)
            if not report.passed:
                console.print(f"[red]Validation FAILED at: {report.failed_gate}[/red]")
                console.print("[red]Cannot swap. Fix issues or use --force.[/red]")
                raise typer.Exit(1)

            # Check protected files
            protected = pipeline.detect_protected_changes(copy_path)
            if protected:
                console.print(f"[yellow]Protected file changes detected ({len(protected)}):[/yellow]")
                for pc in protected:
                    console.print(f"  {pc.file_path}: +{pc.additions} -{pc.deletions}")

        # Create backup
        backup_dir = pipeline.create_backup()
        console.print(f"Backup created at: {backup_dir}")

        # Swap
        pipeline.swap(copy_path)
        console.print("[green]Swap complete.[/green]")

        # Post-swap validation
        post_ok = await pipeline.post_swap_validate()
        if not post_ok:
            console.print("[red]Post-swap validation FAILED. Rolling back...[/red]")
            pipeline.rollback(backup_dir)
            console.print("[yellow]Rolled back to backup.[/yellow]")
            raise typer.Exit(1)

        console.print("[green]Post-swap validation passed. Enhancement is now live.[/green]")
        console.print(f"Backup preserved at: {backup_dir}")

    asyncio.run(_run())


@self_enhance_app.command(name="rollback")
def self_enhance_rollback(
    backup_dir: Optional[str] = typer.Argument(None, help="Path to backup (default: most recent)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Rollback to a backup after a failed swap."""
    _setup_logging(verbose)

    from claw.core.config import load_config

    cfg = load_config(Path(config) if config else None)
    live_dir = Path(config).parent.resolve() if config else Path.cwd().resolve()

    from claw.reconstruct import ReconstructionPipeline, _load_state
    pipeline = ReconstructionPipeline(cfg, live_dir=live_dir)

    if backup_dir:
        backup_path = Path(backup_dir).resolve()
    else:
        # Find most recent backup
        state = _load_state(live_dir)
        last_backup = state.get("last_backup_dir")
        if last_backup and Path(last_backup).exists():
            backup_path = Path(last_backup)
        else:
            workspace_parent = pipeline._resolve_workspace_parent()
            backups = sorted(workspace_parent.glob("cam-backup-*"), reverse=True)
            if not backups:
                console.print("[red]No backups found.[/red]")
                raise typer.Exit(1)
            backup_path = backups[0]

    if not backup_path.exists():
        console.print(f"[red]Backup not found: {backup_path}[/red]")
        raise typer.Exit(1)

    console.print(f"Rolling back from: {backup_path}")
    pipeline.rollback(backup_path)
    console.print("[green]Rollback complete.[/green]")


# ---------------------------------------------------------------------------
# A/B Knowledge Ablation Test Commands
# ---------------------------------------------------------------------------


@ab_test_app.command(name="start")
def ab_test_start() -> None:
    """Schedule the knowledge ablation A/B test.

    Control = no knowledge injection, Variant = with knowledge (current behavior).
    50/50 blind routing via Bayesian framework, needs 20+ samples per variant.
    """
    import asyncio
    from claw.core.config import load_config
    from claw.db.engine import DatabaseEngine
    from claw.evolution.prompt_evolver import PromptEvolver

    async def _run():
        cfg = load_config()
        engine = DatabaseEngine(cfg.database)
        await engine.connect()
        await engine.apply_migrations()
        await engine.initialize_schema()

        from claw.db.repository import Repository as _Repo
        evolver = PromptEvolver(_Repo(engine))
        result = await evolver.schedule_ab_test(
            prompt_name="knowledge_ablation",
            control_content="ablated",
            variant_content="with_knowledge",
            agent_id=None,
        )
        await engine.close()
        return result

    result = asyncio.run(_run())
    console.print("[green]A/B knowledge ablation test scheduled.[/green]")
    console.print(f"  Control (no knowledge): {result['control_id']}")
    console.print(f"  Variant (with knowledge): {result['variant_id']}")
    console.print("[dim]50/50 blind routing active. Run tasks to collect samples.[/dim]")


@ab_test_app.command(name="status")
def ab_test_status() -> None:
    """Show current A/B test results with Bayesian scores."""
    import asyncio
    from claw.core.config import load_config
    from claw.db.engine import DatabaseEngine
    from claw.evolution.prompt_evolver import PromptEvolver

    async def _run():
        cfg = load_config()
        engine = DatabaseEngine(cfg.database)
        await engine.connect()
        await engine.apply_migrations()
        await engine.initialize_schema()

        from claw.db.repository import Repository as _Repo
        evolver = PromptEvolver(_Repo(engine))
        result = await evolver.evaluate_test(
            prompt_name="knowledge_ablation", agent_id=None
        )
        await engine.close()
        return result

    result = asyncio.run(_run())

    from rich.table import Table

    table = Table(title="Knowledge Ablation A/B Test")
    table.add_column("Variant", style="bold")
    table.add_column("Samples", justify="right")
    table.add_column("Successes", justify="right")
    table.add_column("Avg Quality", justify="right")
    table.add_column("Bayesian Score", justify="right")
    table.add_column("Active", justify="center")

    for label in ("control", "variant"):
        data = result.get(label, {})
        if data:
            display_name = "No Knowledge" if label == "control" else "With Knowledge"
            table.add_row(
                display_name,
                str(data.get("sample_count", 0)),
                str(data.get("success_count", 0)),
                f"{data.get('avg_quality_score', 0):.3f}",
                f"{data.get('bayesian_score', 0):.4f}",
                "Y" if data.get("is_active") else "N",
            )

    console.print(table)

    ready = result.get("ready", False)
    winner = result.get("winner")
    margin = result.get("margin", 0)

    if ready and winner:
        winner_name = "With Knowledge" if winner == "variant" else "No Knowledge"
        console.print(f"\n[green]Winner: {winner_name} (margin={margin:.4f})[/green]")
    elif ready:
        console.print(f"\n[yellow]Inconclusive (margin={margin:.4f})[/yellow]")
    else:
        console.print("\n[dim]Not enough samples yet (need 20 per variant)[/dim]")


@ab_test_app.command(name="stop")
def ab_test_stop() -> None:
    """Remove the knowledge ablation test (delete variant rows)."""
    import asyncio
    from claw.core.config import load_config
    from claw.db.engine import DatabaseEngine

    async def _run():
        cfg = load_config()
        engine = DatabaseEngine(cfg.database)
        await engine.connect()
        await engine.apply_migrations()
        await engine.initialize_schema()
        await engine.execute(
            "DELETE FROM prompt_variants WHERE prompt_name = ?",
            ["knowledge_ablation"],
        )
        await engine.close()

    asyncio.run(_run())
    console.print("[green]Knowledge ablation test stopped and data cleared.[/green]")


# ---------------------------------------------------------------------------
# Serial Evolution Commands
# ---------------------------------------------------------------------------


async def _serial_evolution_runner(
    config: Optional[str] = None,
    live_mining: bool = False,
    live_repo_timeout_seconds: int = 180,
):
    from claw.core.config import load_config
    from claw.db.engine import DatabaseEngine
    from claw.db.repository import Repository
    from claw.evolution.serial import (
        LiveMiningBinding,
        PromotionGateConfig,
        SerialEvolutionRunner,
    )

    cfg_path = Path(config).resolve() if config else None
    cfg = load_config(cfg_path)
    repo_path = cfg_path.parent if cfg_path else Path.cwd().resolve()
    db_path_raw = str(cfg.database.db_path)
    if db_path_raw == ":memory:":
        db_path = None
    else:
        db_path = Path(db_path_raw)
        if not db_path.is_absolute():
            db_path = (repo_path / db_path).resolve()
        cfg.database.db_path = str(db_path)

    if live_mining:
        from claw.core.models import Project
        from claw.db.embeddings import EmbeddingEngine
        from claw.llm.client import LLMClient

        engine = DatabaseEngine(cfg.database)
        await engine.connect()
        await engine.apply_migrations()
        await engine.initialize_schema()
        repository = Repository(engine)
        embeddings = EmbeddingEngine(cfg.embeddings)
        llm_client = LLMClient(cfg.llm)

        class _LiveEvolutionContext:
            async def close(self) -> None:
                try:
                    embeddings.close()
                finally:
                    await llm_client.close()
                    await engine.close()

        async def _build_challenger_mining_binding(
            challenger: dict[str, Any],
        ) -> LiveMiningBinding:
            from claw.core.factory import _build_search_stack
            from claw.db.engine import DatabaseEngine
            from claw.evolution.assimilation import CapabilityAssimilationEngine
            from claw.miner import RepoMiner

            challenger_db = challenger.get("db_path")
            if not challenger_db:
                raise RuntimeError("Live mining requires an isolated challenger DB")

            challenger_config = cfg.model_copy(deep=True)
            challenger_config.database.db_path = str(Path(challenger_db).resolve())
            challenger_engine = DatabaseEngine(challenger_config.database)
            await challenger_engine.connect()
            await challenger_engine.apply_migrations()
            await challenger_engine.initialize_schema()

            search = _build_search_stack(
                challenger_config,
                challenger_engine,
                embeddings,
            )
            assimilation_engine = CapabilityAssimilationEngine(
                repository=search.repository,
                llm_client=llm_client,
                config=challenger_config,
            )
            miner = RepoMiner(
                repository=search.repository,
                llm_client=llm_client,
                semantic_memory=search.semantic_memory,
                config=challenger_config,
                governance=search.governance,
                assimilation_engine=assimilation_engine,
            )
            project = await search.repository.get_project_by_repo_path(str(repo_path))
            if project is None:
                project = await search.repository.create_project(
                    Project(
                        name=repo_path.name,
                        repo_path=str(repo_path),
                        tech_stack={
                            "purpose": "serial_evolution_challenger",
                            "source_champion_db": str(db_path) if db_path else None,
                        },
                    )
                )

            async def _close() -> None:
                await challenger_engine.close()

            return LiveMiningBinding(
                repo_miner=miner,
                target_project_id=project.id,
                db_path=Path(challenger_config.database.db_path),
                close=_close,
            )

        return SerialEvolutionRunner(
            repository,
            repo_path=repo_path,
            db_path=db_path,
            gate_config=PromotionGateConfig(require_validation_gate=True),
            live_mining_factory=_build_challenger_mining_binding,
            live_repo_timeout_seconds=live_repo_timeout_seconds,
            require_live_source_preflight=True,
            repo_preflight_config=cfg,
        ), _LiveEvolutionContext()

    engine = DatabaseEngine(cfg.database)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    return SerialEvolutionRunner(
        Repository(engine),
        repo_path=repo_path,
        db_path=db_path,
    ), engine


@evolution_app.command(name="register")
def evolution_register(
    version_label: str = typer.Option("v0", "--version-label", help="Champion version label"),
    force_new: bool = typer.Option(False, "--force-new", help="Create a new champion record even if one exists"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Register the current workspace as the serial evolution champion."""
    _setup_logging(verbose)

    async def _run() -> dict[str, Any]:
        runner, engine = await _serial_evolution_runner(config)
        try:
            return await runner.register_current_workspace(
                version_label=version_label,
                force_new=force_new,
            )
        finally:
            await engine.close()

    champion = asyncio.run(_run())
    console.print("[green]Champion registered.[/green]")
    console.print(f"  id: {champion['id']}")
    console.print(f"  version: {champion['version_label']}")
    console.print(f"  repo: {champion['repo_path']}")
    console.print(f"  git_ref: {champion.get('git_ref') or 'unknown'}")


@evolution_app.command(name="run")
def evolution_run(
    layer: Optional[str] = typer.Option(None, "--layer", help="Override layer: data_feature, prompt_config, strategy_policy, model"),
    objective: Optional[str] = typer.Option(None, "--objective", help="Cycle objective statement"),
    mining_dir: Optional[str] = typer.Option(None, "--mining-dir", help="Folder of repos to mine for data-feature cycles"),
    repos_per_round: int = typer.Option(3, "--repos-per-round", help="Repos to mine from --mining-dir in this cycle"),
    materialize_copy: bool = typer.Option(False, "--materialize-copy", help="Create an isolated filesystem copy for the challenger"),
    allow_model_layer: bool = typer.Option(False, "--allow-model-layer", help="Allow model-level cycles in this conservative runner"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Run one conservative champion/challenger evolution cycle."""
    _setup_logging(verbose)

    async def _run():
        runner, engine = await _serial_evolution_runner(config)
        try:
            return await runner.run_minimal_cycle(
                layer_override=layer,
                objective=objective,
                materialize_copy=materialize_copy,
                allow_model_layer=allow_model_layer,
                mining_dir=Path(mining_dir).resolve() if mining_dir else None,
                repos_per_round=repos_per_round,
            )
        finally:
            await engine.close()

    try:
        result = asyncio.run(_run())
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    console.print("[green]Evolution cycle recorded.[/green]")
    console.print(f"  run: {result.run_id}")
    console.print(f"  cycle: {result.cycle_number}")
    console.print(f"  layer: {result.layer}")
    console.print(f"  decision: {result.decision}")
    console.print(f"  reason: {result.decision_reason}")
    console.print(f"  score delta: {result.promotion_score_delta:+.4f}")
    console.print(f"  report: {result.report_path}")
    if result.decision == "pause":
        console.print("[dim]Manual promotion is available with: cam evolution approve RUN_ID[/dim]")


@evolution_app.command(name="loop")
def evolution_loop(
    mining_dir: str = typer.Argument(..., help="Folder containing repos to mine"),
    repos_per_round: int = typer.Option(3, "--repos-per-round", help="Number of repos to mine each round"),
    max_rounds: Optional[int] = typer.Option(None, "--max-rounds", help="Optional hard cap on rounds"),
    min_budget_remaining: float = typer.Option(0.01, "--min-budget-remaining", help="Minimum OpenRouter key credits required before starting another round"),
    live_repo_timeout_seconds: int = typer.Option(180, "--live-repo-timeout-seconds", help="Hard timeout for each live-mined repo"),
    summary_only: bool = typer.Option(False, "--summary-only", help="Do not invoke live LLM mining; record deterministic repo summaries only"),
    skip_live_probe: bool = typer.Option(False, "--skip-live-probe", help="Skip the tiny OpenRouter model probe before live mining"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Run autonomous data-feature evolution until OpenRouter budget or repo supply stops."""
    _setup_logging(verbose)

    async def _run():
        runner, engine = await _serial_evolution_runner(
            config,
            live_mining=not summary_only,
            live_repo_timeout_seconds=live_repo_timeout_seconds,
        )
        try:
            return await runner.run_autonomous_loop(
                mining_dir=Path(mining_dir).resolve(),
                repos_per_round=repos_per_round,
                max_rounds=max_rounds,
                min_budget_remaining_credits=min_budget_remaining,
                require_live_probe=(not summary_only and not skip_live_probe),
            )
        finally:
            await engine.close()

    try:
        result = asyncio.run(_run())
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    console.print("[green]Autonomous evolution loop stopped.[/green]")
    console.print(f"  rounds_attempted: {result.rounds_attempted}")
    console.print(f"  stop_reason: {result.stop_reason}")
    if result.last_budget_status.remaining_credits is not None:
        console.print(f"  budget_remaining: {result.last_budget_status.remaining_credits:.4f}")
    if result.live_probe_status is not None:
        probe = result.live_probe_status
        console.print(
            f"  live_probe: {'ok' if probe.can_continue else 'failed'} "
            f"model={probe.model_used or 'none'} tokens={probe.tokens_used}"
        )
        if probe.failures:
            console.print(f"  live_probe_failures: {len(probe.failures)}")
    for cycle in result.cycle_results:
        console.print(
            f"  cycle {cycle.cycle_number}: {cycle.decision} "
            f"layer={cycle.layer} delta={cycle.promotion_score_delta:+.4f}"
        )


@evolution_app.command(name="status")
def evolution_status(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Show current champion, active run, and recent serial evolution decisions."""
    _setup_logging(verbose)

    async def _run() -> dict[str, Any]:
        runner, engine = await _serial_evolution_runner(config)
        try:
            return await runner.status()
        finally:
            await engine.close()

    status = asyncio.run(_run())
    champion = status.get("champion")
    if champion:
        console.print("[bold]Current Champion[/bold]")
        console.print(f"  id: {champion['id']}")
        console.print(f"  version: {champion['version_label']}")
        console.print(f"  repo: {champion['repo_path']}")
        console.print(f"  db: {champion.get('db_path') or 'unset'}")
        console.print(f"  pointer: {status.get('champion_pointer')}")
    else:
        console.print("[yellow]No champion registered.[/yellow]")

    active = status.get("active_run")
    console.print("\n[bold]Active Run[/bold]")
    if active:
        console.print(f"  {active['id']} status={active['status']} layer={active['layer']}")
    else:
        console.print("  none")

    table = Table(title="Recent Evolution Runs")
    table.add_column("Cycle", justify="right")
    table.add_column("Run")
    table.add_column("Layer")
    table.add_column("Status")
    table.add_column("Objective", max_width=48)
    for run in status.get("recent_runs", []):
        table.add_row(
            str(run["cycle_number"]),
            run["id"][:8],
            run["layer"],
            run["status"],
            run["objective"],
        )
    console.print(table)

    decision_table = Table(title="Recent Decisions")
    decision_table.add_column("Decision")
    decision_table.add_column("Run")
    decision_table.add_column("Reason", max_width=60)
    for decision in status.get("recent_decisions", []):
        decision_table.add_row(
            decision["decision"],
            decision["run_id"][:8],
            decision["reason"],
        )
    console.print(decision_table)


@evolution_app.command(name="champion-db")
def evolution_champion_db(
    export_env: bool = typer.Option(False, "--export-env", help="Print shell export commands for downstream use"),
    sync_pointer: bool = typer.Option(True, "--sync-pointer/--no-sync-pointer", help="Rewrite current_champion.json before printing"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Print the active champion DB pointer for downstream CAM commands."""
    _setup_logging(verbose)

    async def _run() -> dict[str, Any]:
        runner, engine = await _serial_evolution_runner(config)
        try:
            if sync_pointer:
                return await runner.sync_champion_pointer()
            status = await runner.status()
            champion = status.get("champion")
            if not champion:
                raise ValueError("No current evolution champion is registered")
            return {
                "champion": champion,
                "pointer_path": status.get("champion_pointer"),
            }
        finally:
            await engine.close()

    try:
        payload = asyncio.run(_run())
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    champion = payload["champion"]
    db_path = champion.get("db_path")
    if export_env:
        console.print(f"export CLAW_USE_EVOLUTION_CHAMPION=1")
        if db_path:
            console.print(f"export CLAW_DB_PATH={shlex.quote(str(db_path))}")
        return

    console.print("[bold]Champion DB[/bold]")
    console.print(f"  instance: {champion['id']}")
    console.print(f"  version: {champion['version_label']}")
    console.print(f"  db: {db_path or 'unset'}")
    console.print(f"  pointer: {payload.get('pointer_path')}")


@evolution_app.command(name="approve", hidden=True)
def evolution_approve(
    run_id: str = typer.Argument(..., help="Paused evolution run to promote"),
    decided_by: str = typer.Option("operator", "--decided-by", help="Decision actor label"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Manually promote a paused challenger after reviewing its decision report."""
    _setup_logging(verbose)

    async def _run() -> dict[str, Any]:
        runner, engine = await _serial_evolution_runner(config)
        try:
            return await runner.approve_paused_run(run_id, decided_by=decided_by)
        finally:
            await engine.close()

    try:
        decision = asyncio.run(_run())
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    console.print("[green]Paused challenger promoted.[/green]")
    console.print(f"  run: {decision['run_id']}")
    console.print(f"  promoted_instance: {decision.get('promoted_instance_id')}")
    console.print(f"  rollback_instance: {decision.get('rollback_instance_id')}")


# ---------------------------------------------------------------------------
# kb community — Community knowledge sharing sub-app
# ---------------------------------------------------------------------------

community_app = typer.Typer(
    name="community",
    help="Share and import knowledge between CAM instances via HuggingFace",
    no_args_is_help=True,
)
kb_app.add_typer(community_app, name="community")


@community_app.command()
def publish(
    alias: str = typer.Option("", "--alias", "-a", help="Contributor alias (human-readable)"),
    hf_repo: str = typer.Option("cam-community/knowledge-hub", "--hf-repo", help="HuggingFace dataset repo"),
    min_lifecycle: str = typer.Option("viable", "--min-lifecycle", help="Minimum lifecycle state to include"),
    max_count: int = typer.Option(500, "--max", help="Max methodologies to publish"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without uploading"),
) -> None:
    """Export proven knowledge to a HuggingFace community hub."""

    async def _run():
        from pathlib import Path

        from claw.community.packer import pack_methodologies

        engine, _ = await _kb_engine()
        try:
            state_path = Path("data/community_state.json")
            records, manifest = await pack_methodologies(
                engine, state_path, min_lifecycle=min_lifecycle,
                max_count=max_count, contributor_alias=alias,
            )
            if not records:
                console.print("[yellow]No methodologies match the lifecycle filter.[/yellow]")
                return

            console.print(f"[bold]Packed {len(records)} methodologies[/bold]")
            console.print(f"  Instance ID: {manifest['instance_id'][:12]}...")
            console.print(f"  Languages: {manifest['language_breakdown']}")
            console.print(f"  Lifecycle filter: {manifest['lifecycle_filter']}")

            if dry_run:
                console.print("[yellow]Dry run — not uploading.[/yellow]")
                # Write locally for inspection
                out_path = Path(f"data/community_pack_{manifest['instance_id'][:12]}.jsonl")
                out_path.parent.mkdir(parents=True, exist_ok=True)
                import json
                with open(out_path, "w") as f:
                    for r in records:
                        f.write(json.dumps(r) + "\n")
                console.print(f"  Written to: {out_path}")
                return

            from claw.community.hub import push_pack
            url = await push_pack(records, manifest, hf_repo=hf_repo, instance_id=manifest["instance_id"])
            console.print(f"[green]Published to {url}[/green]")
        finally:
            await engine.close()

    asyncio.run(_run())


@community_app.command()
def browse(
    hf_repo: str = typer.Option("cam-community/knowledge-hub", "--hf-repo", help="HuggingFace dataset repo"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max methodologies to preview"),
) -> None:
    """Preview knowledge available in the community hub."""

    async def _run():
        from claw.community.hub import list_contributors
        contributors = await list_contributors(hf_repo=hf_repo)
        if not contributors:
            console.print("[yellow]No contributors found in the hub.[/yellow]")
            return

        from rich.table import Table
        table = Table(title=f"Community Hub: {hf_repo}")
        table.add_column("Alias")
        table.add_column("Methodologies", justify="right")
        table.add_column("Languages")
        table.add_column("Exported")
        table.add_column("Instance ID")

        for c in contributors:
            table.add_row(
                c.get("contributor_alias", "—"),
                str(c.get("methodology_count", 0)),
                ", ".join(c.get("domains", [])),
                c.get("exported_at", "—")[:10],
                c.get("instance_id", "—")[:12] + "...",
            )
        console.print(table)

    asyncio.run(_run())


@community_app.command(name="import")
def import_(
    hf_repo: str = typer.Option("cam-community/knowledge-hub", "--hf-repo", help="HuggingFace dataset repo"),
    contributor: str = typer.Option("", "--contributor", "-c", help="Instance ID or alias to import from"),
    from_file: str = typer.Option("", "--from-file", "-f", help="Import from local JSONL file instead of HF"),
    auto_approve: bool = typer.Option(False, "--auto-approve", help="Skip quarantine — write directly to KB"),
    max_records: int = typer.Option(200, "--max", help="Max records to import"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate only, no DB writes"),
) -> None:
    """Import knowledge from a community hub or local JSONL file."""

    async def _run():
        import json
        from pathlib import Path

        from claw.community.importer import import_records

        engine, _ = await _kb_engine()
        try:
            records = []
            if from_file:
                path = Path(from_file)
                if not path.exists():
                    console.print(f"[red]File not found: {from_file}[/red]")
                    return
                for line in path.read_text().strip().splitlines():
                    if line.strip():
                        records.append(json.loads(line))
                console.print(f"Loaded {len(records)} records from {from_file}")
            elif contributor:
                from claw.community.hub import pull_contributor_pack
                records = await pull_contributor_pack(contributor, hf_repo=hf_repo)
                console.print(f"Pulled {len(records)} records from contributor {contributor[:12]}...")
            else:
                console.print("[red]Specify --contributor or --from-file[/red]")
                return

            if dry_run:
                from claw.community.validator import validate_record
                from claw.community.importer import _ensure_tables
                await _ensure_tables(engine)
                passed = 0
                failed = 0
                for r in records[:max_records]:
                    result = await validate_record(r, engine)
                    if result.passed:
                        passed += 1
                    else:
                        failed += 1
                        gates = [g.gate_name for g in result.gates if not g.passed]
                        console.print(f"  [red]REJECT[/red] {r.get('id', '?')[:20]}: {gates}")
                console.print(f"\n[bold]Dry run: {passed} would pass, {failed} would fail[/bold]")
                return

            summary = await import_records(
                records, engine, max_records=max_records, auto_approve=auto_approve,
            )
            action = "auto-approved" if auto_approve else "quarantined"
            console.print(f"[green]{summary['imported']} records {action}[/green]")
            if summary["rejected"]:
                console.print(f"[yellow]{summary['rejected']} records rejected[/yellow]")
            if summary["skipped"]:
                console.print(f"[dim]{summary['skipped']} duplicates skipped[/dim]")
        finally:
            await engine.close()

    asyncio.run(_run())


@community_app.command()
def approve(
    record_id: str = typer.Option("", "--id", help="Approve specific quarantined record"),
    show: bool = typer.Option(False, "--show", help="List quarantined records"),
) -> None:
    """Review and approve quarantined community imports."""

    async def _run():
        from claw.community.importer import approve_all, approve_one, list_quarantined

        engine, _ = await _kb_engine()
        try:
            if show:
                quarantined = await list_quarantined(engine)
                if not quarantined:
                    console.print("[green]No records in quarantine.[/green]")
                    return
                from rich.table import Table
                table = Table(title="Quarantined Imports")
                table.add_column("ID")
                table.add_column("Contributor")
                table.add_column("Imported")
                table.add_column("Warnings")
                for q in quarantined:
                    table.add_row(
                        q["id"][:12] + "...",
                        q.get("contributor", "—"),
                        q.get("imported_at", "—")[:10],
                        str(len(q.get("gate_warnings", []))),
                    )
                console.print(table)
                return

            if record_id:
                ok = await approve_one(engine, record_id)
                if ok:
                    console.print(f"[green]Approved {record_id}[/green]")
                else:
                    console.print(f"[red]Record not found in quarantine: {record_id}[/red]")
            else:
                count = await approve_all(engine)
                console.print(f"[green]Approved {count} records into the knowledge base.[/green]")
        finally:
            await engine.close()

    asyncio.run(_run())


@community_app.command()
def status() -> None:
    """Show community sharing status — local instance, quarantine count, hub info."""

    async def _run():
        import json
        from pathlib import Path

        from claw.community.packer import _get_instance_id

        engine, _ = await _kb_engine()
        try:
            state_path = Path("data/community_state.json")
            instance_id = _get_instance_id(state_path)

            # Quarantine count
            quarantine_count = 0
            try:
                rows = await engine.fetch_all(
                    "SELECT COUNT(*) as cnt FROM community_imports WHERE status = 'quarantined'"
                )
                quarantine_count = rows[0]["cnt"] if rows else 0
            except Exception:
                pass

            # Imported count
            imported_count = 0
            try:
                rows = await engine.fetch_all(
                    "SELECT COUNT(*) as cnt FROM community_imports WHERE status = 'approved'"
                )
                imported_count = rows[0]["cnt"] if rows else 0
            except Exception:
                pass

            # Community-tagged methodologies
            community_meths = 0
            try:
                rows = await engine.fetch_all(
                    "SELECT COUNT(*) as cnt FROM methodologies WHERE tags LIKE '%imported%'"
                )
                community_meths = rows[0]["cnt"] if rows else 0
            except Exception:
                pass

            console.print("[bold]Community Status[/bold]")
            console.print(f"  Instance ID: {instance_id[:16]}...")
            console.print(f"  Quarantined: {quarantine_count}")
            console.print(f"  Approved imports: {imported_count}")
            console.print(f"  Community methodologies in KB: {community_meths}")
        finally:
            await engine.close()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# cam kb instances — CAM Swarm: Ganglion federation management
# ---------------------------------------------------------------------------

instances_app = typer.Typer(
    name="instances",
    help="CAM Swarm — manage ganglia (specialized instances), manifests, and cross-ganglion queries.",
)
kb_app.add_typer(instances_app, name="instances")


@instances_app.command(name="list")
def instances_list() -> None:
    """List registered ganglia (sibling CAM instances) and their manifest summaries."""

    async def _run():
        from claw.community.federation import Federation
        from claw.core.config import load_config

        config = load_config()
        if not config.instances.siblings:
            console.print("[yellow]No ganglia registered in the CAM Swarm.[/yellow]")
            console.print("Add [[instances.siblings]] entries to claw.toml or run: cam kb instances add <name> <db_path>")
            return

        federation = Federation(config.instances)
        summaries = await federation.get_sibling_summaries()

        table = Table(title="CAM Swarm — Registered Ganglia")
        table.add_column("Ganglion", style="cyan")
        table.add_column("Specialization")
        table.add_column("DB Exists", justify="center")
        table.add_column("Methodologies", justify="right")
        table.add_column("Top Categories")
        table.add_column("Languages")

        for s in summaries:
            db_status = "[green]Yes[/green]" if s["db_exists"] else "[red]No[/red]"
            cats = ", ".join(s["top_categories"][:3]) if s["top_categories"] else "-"
            langs = ", ".join(s["languages"][:3]) if s["languages"] else "-"
            table.add_row(
                s["name"],
                s["description"][:50] or "-",
                db_status,
                str(s["total_methodologies"]),
                cats,
                langs,
            )

        console.print(table)

        # Show this ganglion's info
        console.print(f"\n[bold]This ganglion:[/bold] {config.instances.instance_name or '(unnamed)'}")
        console.print(f"  Specialization: {config.instances.instance_description or '(none)'}")
        console.print(f"  Manifest: {config.instances.manifest_path}")
        console.print(f"  Swarm federation: {'[green]enabled[/green]' if config.instances.enabled else '[red]disabled[/red]'}")

    asyncio.run(_run())


@instances_app.command()
def manifest() -> None:
    """Generate/refresh this ganglion's brain manifest for the CAM Swarm."""

    async def _run():
        from pathlib import Path

        from claw.community.manifest import save_manifest
        from claw.core.config import load_config

        config = load_config()
        engine, _ = await _kb_engine()
        try:
            manifest_path = Path(config.instances.manifest_path)
            result = await save_manifest(
                engine,
                manifest_path,
                instance_name=config.instances.instance_name,
                instance_description=config.instances.instance_description,
            )
            console.print(f"[green]Brain manifest saved to {manifest_path}[/green]")
            console.print(f"  Total methodologies: {result['total_methodologies']}")
            console.print(f"  Source repos: {result['source_repo_count']}")
            console.print(f"  Top categories: {', '.join(list(result['top_categories'].keys())[:5])}")
            console.print(f"  Languages: {', '.join(list(result['language_breakdown'].keys())[:5])}")
            console.print(f"  PULSE discoveries: {result['pulse_discoveries_assimilated']}")
            console.print(f"  Fingerprint: {result['fingerprint']}")
        finally:
            await engine.close()

    asyncio.run(_run())


@instances_app.command()
def query(
    text: str = typer.Argument(..., help="Task description or query to search for"),
    language: Optional[str] = typer.Option(None, "--language", "-l", help="Filter by language"),
    max_results: int = typer.Option(5, "--max", "-m", help="Max results"),
) -> None:
    """Query the CAM Swarm — search across all registered ganglia."""

    async def _run():
        from claw.community.federation import Federation
        from claw.core.config import load_config

        config = load_config()
        if not config.instances.enabled:
            console.print("[yellow]CAM Swarm is disabled. Set instances.enabled = true in claw.toml[/yellow]")
            return
        if not config.instances.siblings:
            console.print("[yellow]No ganglia registered in the swarm.[/yellow]")
            return

        federation = Federation(config.instances)
        results = await federation.query(text, language=language, max_total=max_results)

        if not results:
            console.print("[dim]No results from sibling ganglia.[/dim]")
            return

        console.print(f"[bold]Swarm query results for:[/bold] {text[:80]}")
        console.print()
        for i, r in enumerate(results, 1):
            m = r.methodology
            console.print(f"[cyan]{i}.[/cyan] [bold]{(m.problem_description or 'Untitled')[:80]}[/bold]")
            console.print(f"   Ganglion: [magenta]{r.source_instance}[/magenta]  |  Relevance: {r.relevance_score:.3f}  |  FTS rank: {r.fts_rank:.3f}")
            console.print(f"   Language: {m.language or '-'}  |  Lifecycle: {m.lifecycle_state}  |  Success: {m.success_count}")
            if m.methodology_notes:
                console.print(f"   Notes: {m.methodology_notes[:150]}")
            console.print()

    asyncio.run(_run())


@instances_app.command()
def add(
    name: str = typer.Argument(..., help="Ganglion name (e.g. 'drive-ops', 'quantum')"),
    db_path: str = typer.Argument(..., help="Absolute path to the ganglion's claw.db"),
    description: str = typer.Option("", "--description", "-d", help="Specialization description"),
) -> None:
    """Register a new ganglion (sibling CAM instance) in the swarm."""
    from pathlib import Path

    db = Path(db_path)
    if not db.exists():
        console.print(f"[yellow]Warning: DB file not found at {db_path}[/yellow]")
        console.print("The ganglion will be registered but won't be queryable until the DB exists.")

    # Find claw.toml
    toml_path = Path("claw.toml")
    if not toml_path.exists():
        console.print("[red]claw.toml not found in current directory[/red]")
        raise typer.Exit(1)

    content = toml_path.read_text()

    # Append the ganglion entry
    entry = f"""
[[instances.siblings]]
name = "{name}"
db_path = "{db_path}"
description = "{description}"
"""
    content += entry
    toml_path.write_text(content)
    console.print(f"[green]Ganglion '{name}' added to the CAM Swarm → {db_path}[/green]")
    console.print("Run [bold]cam kb instances manifest[/bold] on the ganglion to generate its brain manifest.")


@instances_app.command()
def remove(
    name: str = typer.Argument(..., help="Ganglion name to remove from the swarm"),
) -> None:
    """Remove a ganglion from the CAM Swarm."""
    import toml as toml_lib
    from pathlib import Path

    toml_path = Path("claw.toml")
    if not toml_path.exists():
        console.print("[red]claw.toml not found[/red]")
        raise typer.Exit(1)

    with open(toml_path) as f:
        data = toml_lib.load(f)

    siblings = data.get("instances", {}).get("siblings", [])
    original_count = len(siblings)
    siblings = [s for s in siblings if s.get("name") != name]

    if len(siblings) == original_count:
        console.print(f"[yellow]No ganglion named '{name}' found in the swarm[/yellow]")
        return

    data.setdefault("instances", {})["siblings"] = siblings

    with open(toml_path, "w") as f:
        toml_lib.dump(data, f)

    console.print(f"[green]Ganglion '{name}' removed from the CAM Swarm[/green]")



# ---------------------------------------------------------------------------
# CAG — Cache-Augmented Generation commands
# ---------------------------------------------------------------------------


@cag_app.command()
def rebuild(
    ganglion: str = typer.Option("general", "--ganglion", "-g", help="Ganglion name to rebuild cache for"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Rebuild the CAG methodology cache for a ganglion."""

    async def _run() -> None:
        from claw.core.config import load_config
        from claw.db.engine import DatabaseEngine
        from claw.db.repository import Repository
        from claw.memory.cag_retriever import CAGRetriever

        cfg = load_config(Path(config) if config else None)

        if not cfg.cag.enabled:
            console.print("[yellow]CAG is disabled in claw.toml. Set [cag] enabled = true to use.[/yellow]")
            return

        engine = DatabaseEngine(cfg.database)
        await engine.connect()
        repo = Repository(engine)

        try:
            retriever = CAGRetriever(cfg.cag, repo)
            console.print(f"Building CAG cache for ganglion [bold]{ganglion}[/bold]...")
            meta = await retriever.build_cache(ganglion=ganglion)
            console.print(f"  Methodologies: {meta['methodology_count']}")
            console.print(f"  Corpus tokens (approx): {meta['corpus_tokens_approx']:,}")
            console.print(f"  Built at: {meta['built_at']}")
            console.print(f"  Cache dir: {cfg.cag.cache_dir}/{ganglion}/")
            console.print("[green]CAG cache rebuilt successfully.[/green]")
        finally:
            await engine.close()

    asyncio.run(_run())


@cag_app.command()
def status(
    ganglion: str = typer.Option("general", "--ganglion", "-g", help="Ganglion name"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Show CAG cache status for a ganglion."""

    async def _run() -> None:
        from claw.core.config import load_config
        from claw.memory.cag_retriever import CAGRetriever

        cfg = load_config(Path(config) if config else None)

        if not cfg.cag.enabled:
            console.print("[yellow]CAG is disabled in claw.toml.[/yellow]")
            return

        retriever = CAGRetriever(cfg.cag)
        loaded = await retriever.load_cache(ganglion=ganglion)
        info = retriever.get_status(ganglion=ganglion)

        console.print(f"\nCAG Cache Status: [bold]{ganglion}[/bold]")
        console.print(f"  Loaded:           {'yes' if info.get('loaded') else 'no'}")
        console.print(f"  Stale:            {'yes' if info.get('stale') else 'no'}")
        console.print(f"  Methodology count: {info.get('methodology_count', 0)}")
        console.print(f"  Corpus tokens:    {info.get('corpus_tokens_approx', 0):,}")
        console.print(f"  Built at:         {info.get('built_at', 'never')}")
        console.print(f"  Cache dir:        {cfg.cag.cache_dir}/{ganglion}/")

    asyncio.run(_run())


@cag_app.command()
def convert(
    source: str = typer.Argument(..., help="Path to RAG source (directory, Chroma DB, LanceDB, or FAISS index)"),
    fmt: Optional[str] = typer.Option(None, "--format", "-f", help="Source format: auto, directory, chroma, lancedb, faiss (default: auto-detect)"),
    ganglion: str = typer.Option("imported", "--ganglion", "-g", help="Ganglion name for the converted cache"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
    max_docs: int = typer.Option(0, "--max-docs", "-n", help="Max documents to import (0 = all)"),
    min_chars: int = typer.Option(50, "--min-chars", help="Skip documents shorter than this"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be imported without building cache"),
    export_recipe: bool = typer.Option(False, "--export-recipe", help="Export standalone cag_runtime.py + corpus.txt (no CAM dependency)"),
    export_dir: str = typer.Option("./cag_export", "--export-dir", help="Directory for exported recipe files"),
) -> None:
    """Convert an external RAG source into a CAG cache.

    Reads documents from Chroma, LanceDB, FAISS, or plain file directories
    and builds a CAG corpus that can be loaded into agent prompts.

    With --export-recipe, also generates a self-contained cag_runtime.py
    that lets the target repo load and use the cache without CAM installed.
    """

    async def _run() -> None:
        from claw.core.config import load_config
        from claw.memory.cag_retriever import CAGRetriever
        from claw.memory.rag_adapter import adapt_to_methodologies, read_source

        # Validate source path
        source_path = Path(source).resolve()
        if not source_path.exists():
            console.print(f"[red]Source path does not exist: {source_path}[/red]")
            return
        if not source_path.is_dir():
            console.print(f"[red]Source path is not a directory: {source_path}[/red]")
            return

        # Read documents
        try:
            docs, detected_fmt = read_source(source_path, fmt=fmt)
        except ImportError as exc:
            console.print(f"[red]{exc}[/red]")
            return
        except (FileNotFoundError, ValueError) as exc:
            console.print(f"[red]{exc}[/red]")
            return

        console.print(f"Detected format: [bold]{detected_fmt}[/bold]")
        console.print(f"  Found {len(docs)} documents")

        # Filter short documents
        original_count = len(docs)
        docs = [d for d in docs if len(d.content) >= min_chars]
        filtered_count = original_count - len(docs)
        if filtered_count > 0:
            console.print(f"  Filtered: {filtered_count} below {min_chars} char minimum")

        # Limit document count
        if max_docs > 0 and len(docs) > max_docs:
            docs = docs[:max_docs]
            console.print(f"  Limited to {max_docs} documents (--max-docs)")

        if not docs:
            console.print("[yellow]No documents to convert after filtering.[/yellow]")
            return

        total_chars = sum(len(d.content) for d in docs)

        # Dry run — show stats and exit
        if dry_run:
            console.print(f"\n[bold]Dry run summary:[/bold]")
            console.print(f"  Documents: {len(docs)}")
            console.print(f"  Total chars: {total_chars:,}")
            console.print(f"  Approx tokens: {total_chars // 4:,}")
            console.print(f"  Target ganglion: {ganglion}")
            console.print(f"\n  Sample documents:")
            for i, doc in enumerate(docs[:3], 1):
                title = doc.title or doc.source or "(untitled)"
                console.print(f"    {i}. {title[:80]} ({len(doc.content):,} chars)")
            return

        # Convert to Methodology objects
        console.print(f"  Converting {len(docs)} documents to CAG format...")
        adapted = adapt_to_methodologies(docs)

        # Load config and build cache
        cfg = load_config(Path(config) if config else None)
        retriever = CAGRetriever(cfg.cag)

        console.print(f"\nBuilding CAG cache for ganglion [bold]{ganglion}[/bold]...")
        meta = await retriever.build_cache(ganglion=ganglion, methodologies=adapted)

        console.print(f"  Documents converted: {meta['methodology_count']}")
        console.print(f"  Corpus tokens (approx): {meta['corpus_tokens_approx']:,}")
        console.print(f"  Cache dir: {cfg.cag.cache_dir}/{ganglion}/")
        console.print(f"  Built at: {meta['built_at']}")
        console.print("[green]CAG cache built successfully.[/green]")

        # Export recipe if requested
        if export_recipe:
            import shutil

            from claw.memory.cag_recipe import generate_recipe

            export_path = Path(export_dir).resolve()
            export_path.mkdir(parents=True, exist_ok=True)

            # Copy cache files
            src_corpus = Path(cfg.cag.cache_dir) / ganglion / "corpus.txt"
            src_meta = Path(cfg.cag.cache_dir) / ganglion / "meta.json"
            shutil.copy2(str(src_corpus), str(export_path / "corpus.txt"))
            shutil.copy2(str(src_meta), str(export_path / "meta.json"))

            # Generate standalone runtime
            recipe_code = generate_recipe(
                ganglion=ganglion,
                knowledge_budget=cfg.cag.knowledge_budget_chars,
            )
            (export_path / "cag_runtime.py").write_text(recipe_code, encoding="utf-8")

            console.print(f"\nExported to [bold]{export_path}[/bold]:")
            console.print(f"  cag_runtime.py  — standalone CAG loader (zero dependencies)")
            console.print(f"  corpus.txt      — pre-built knowledge corpus")
            console.print(f"  meta.json       — cache metadata")

        console.print(f"Use [bold]cam cag status -g {ganglion}[/bold] to verify.")

    asyncio.run(_run())


@app.command()
def dashboard(
    port: int = typer.Option(8420, help="Port to serve on"),
    host: str = typer.Option("127.0.0.1", help="Host to bind to"),
) -> None:
    """Launch the CAM Brain Dashboard — federated knowledge explorer in your browser."""
    try:
        import uvicorn
    except ImportError:
        console.print("[red]uvicorn not installed. Run: pip install uvicorn[/red]")
        raise typer.Exit(1)

    from claw.web.dashboard_server import app as dash_app

    console.print(f"\n[bold]CAM-PULSE Brain Dashboard[/bold]")
    console.print(f"  URL: [link]http://{host}:{port}[/link]")
    console.print(f"  API: [link]http://{host}:{port}/api/docs[/link]")
    console.print(f"  Press Ctrl+C to stop.\n")

    uvicorn.run(dash_app, host=host, port=port, log_level="warning")


@app.command(name="mcp")
def mcp_start(
    transport: str = typer.Option("stdio", "--transport", "-t", help="Transport mode: stdio or http"),
    host: str = typer.Option("127.0.0.1", "--host", help="HTTP host (ignored for stdio)"),
    port: int = typer.Option(3100, "--port", "-p", help="HTTP port (ignored for stdio)"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Start the CLAW MCP server for external agents (e.g. DeepScientist).

    In stdio mode (default), communicates over stdin/stdout using the MCP protocol.
    External agents launch this as a subprocess.

    In http mode, listens on a network port for MCP connections.
    """
    _setup_logging(False)
    import asyncio

    from claw.core.config import load_config
    cfg = load_config(Path(config) if config else None)

    async def _run_mcp() -> None:
        import os
        from claw.db.engine import DatabaseEngine
        from claw.db.embeddings import EmbeddingEngine
        from claw.db.repository import Repository
        from claw.mcp_server import ClawMCPServer, start_server

        engine = DatabaseEngine(cfg.database)
        await engine.initialize()
        repository = Repository(engine)
        embeddings = EmbeddingEngine(cfg.embeddings)

        # Build semantic memory for KB search
        semantic_memory = None
        try:
            from claw.memory.hybrid_search import HybridSearch
            from claw.memory.semantic import SemanticMemory
            hybrid_search = HybridSearch(
                repository=repository,
                embedding_engine=embeddings,
                deep_conf=cfg.deep_conf,
            )
            semantic_memory = SemanticMemory(
                repository=repository,
                embedding_engine=embeddings,
                hybrid_search=hybrid_search,
            )
        except Exception as e:
            console.print(f"[yellow]SemanticMemory unavailable: {e}. Text-only search.[/yellow]")

        auth_token = os.environ.get(cfg.mcp.auth_token_env)
        mcp_srv = ClawMCPServer(
            repository=repository,
            semantic_memory=semantic_memory,
            verifier=None,
            dispatcher=None,
            auth_token=auth_token,
        )

        server = start_server(mcp_srv, host=host, port=port)
        if server is None:
            console.print("[red]MCP SDK not installed. Run: pip install mcp[/red]")
            raise typer.Exit(1)

        if transport == "stdio":
            console.print("[bold green]CLAW MCP server starting (stdio)...[/bold green]", err=True)
            console.print(f"  Tools: {[s['name'] for s in mcp_srv.get_tool_schemas()]}", err=True)
            console.print(f"  KB: {await repository.count_methodologies()} methodologies", err=True)
            from mcp.server.stdio import stdio_server
            async with stdio_server() as (read_stream, write_stream):
                await server.run(
                    read_stream,
                    write_stream,
                    server.create_initialization_options(),
                )
        else:
            console.print(f"[bold green]CLAW MCP server listening on {host}:{port}[/bold green]")
            console.print(f"  Tools: {[s['name'] for s in mcp_srv.get_tool_schemas()]}")
            console.print(f"  KB: {await repository.count_methodologies()} methodologies")
            console.print("  Press Ctrl+C to stop.")
            # For HTTP mode, the server would need an HTTP transport adapter
            # For now, stdio is the primary transport for DeepScientist integration
            console.print("[yellow]HTTP transport not yet implemented. Use --transport stdio[/yellow]")
            raise typer.Exit(1)

    asyncio.run(_run_mcp())



@app.command()
def federate(
    query: str = typer.Argument(help="Query to search across all brains"),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
    trace: bool = typer.Option(False, "--trace", help="Generate RLMHT training traces"),
    domains: str = typer.Option("", help="Comma-separated domain filter"),
    config: str = typer.Option("claw.toml", "--config", help="Path to claw.toml"),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
):
    """Cross-brain pattern synthesis — query all CAM Brain ganglia."""
    import asyncio
    from pathlib import Path as _Path

    _setup_logging(verbose)

    if output_json and not verbose:
        import logging as _logging
        _logging.getLogger("claw").setLevel(_logging.WARNING)

    from claw.core.config import load_config

    cfg = load_config(_Path(config))

    if not cfg.instances.enabled:
        typer.echo("Federation is disabled in config (instances.enabled = false)")
        raise typer.Exit(1)

    if not cfg.instances.siblings:
        typer.echo("No sibling ganglia configured. Add [[instances.siblings]] to claw.toml")
        raise typer.Exit(1)

    async def _run():
        from claw.community.cross_language import CrossLanguageAnalyzer

        primary_db = str(_Path(cfg.database.db_path).resolve())
        analyzer = CrossLanguageAnalyzer(cfg.instances, primary_db_path=primary_db)

        domain_list = [d.strip() for d in domains.split(",") if d.strip()] if domains else None
        report = await analyzer.analyze(query, domains=domain_list)

        if trace:
            from claw.training.trace_extractor import FederationTraceExtractor
            from claw.community.manifest import BrainTopology
            topo = BrainTopology(cfg.instances, primary_db_path=primary_db)
            topo.load()
            extractor = FederationTraceExtractor(brain_names=topo.brain_names)
            trace_path, trace_count = extractor.write_traces(report)
            if not output_json:
                typer.echo(f"Traces written: {trace_count} to {trace_path}")

        if output_json:
            typer.echo(report.model_dump_json(indent=2))
        else:
            typer.echo(f"\n{chr(61)*60}")
            typer.echo(f"  Cross-Brain Pattern Atlas")
            typer.echo(f"{chr(61)*60}")
            typer.echo(f"  Query: {report.query}")
            typer.echo(f"  Domains: {', '.join(report.domains_queried) if report.domains_queried else 'all'}")
            typer.echo()

            if report.universal_patterns:
                typer.echo("  UNIVERSAL PATTERNS (found in 2+ brains):")
                for p in report.universal_patterns:
                    langs = ", ".join(p.implementations.keys())
                    typer.echo(f"    - {p.pattern_name} [{langs}] (overlap: {p.domain_overlap:.2f})")
                typer.echo()

            if report.unique_innovations:
                typer.echo("  UNIQUE INNOVATIONS:")
                for u in report.unique_innovations:
                    typer.echo(f"    - [{u.brain}] {u.problem_summary}")
                typer.echo()

            if report.transferable_insights:
                typer.echo("  TRANSFERABLE INSIGHTS:")
                for t in report.transferable_insights:
                    typer.echo(f"    - {t.source_brain} -> {t.target_brain}: {t.pattern_name}")
                typer.echo()

            if report.composition_layers:
                typer.echo("  COMPOSITION LAYERS:")
                for layer in report.composition_layers:
                    typer.echo(f"    L{layer.layer_number}: {layer.layer_name} ({layer.contributing_brain})")
                typer.echo()

            typer.echo("  METRICS:")
            m = report.metrics
            typer.echo(f"    Brains queried: {m.brains_queried}")
            typer.echo(f"    Brains with results: {m.brains_with_results}")
            typer.echo(f"    Total results: {m.total_results}")
            typer.echo(f"    Coverage: {m.cross_brain_coverage:.0%}")
            typer.echo(f"    Universal patterns: {m.universal_pattern_count}")
            typer.echo(f"    Novelty count: {m.novelty_count}")
            typer.echo(f"{chr(61)*60}")

    asyncio.run(_run())


def app_main() -> None:
    """Entry point for the installed CLI."""
    app()


if __name__ == "__main__":
    app_main()
