"""User-facing model catalog, profile, and benchmark commands."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import typer
from pydantic import TypeAdapter
from rich.console import Console
from rich.table import Table

from claw.core.config import load_config
from claw.llm.client import LLMClient
from claw.miner import RepoMiner
from claw.models.batch import OpenRouterBatchClient
from claw.models.benchmark import (
    BenchmarkPlan,
    BenchmarkRunner,
    BenchmarkSuite,
    MiningPromptFixture,
)
from claw.models.catalog import ModelCatalog, OpenRouterCatalogClient
from claw.models.candidate_set import load_candidate_set
from claw.models.profiles import (
    PromotionReceipt,
    activate_profile,
    load_model_profiles,
    promote_role,
    rollback_promotion,
)
from claw.models.scoring import (
    BenchmarkQualityReport,
    load_existing_mining_titles,
    score_benchmark_run,
)
from claw.models.tournament import (
    TournamentPlanner,
    TournamentSelectionReport,
    TournamentStagePlan,
    select_tournament_roles,
)

console = Console()
models_app = typer.Typer(
    name="models",
    help="Discover, compare, select, and roll back CAM models.",
    no_args_is_help=True,
)
profile_app = typer.Typer(
    name="profile",
    help="Inspect and select role-based model profiles.",
    no_args_is_help=True,
)
benchmark_app = typer.Typer(
    name="benchmark",
    help="Plan, run, review, and report mining-model comparisons.",
    no_args_is_help=True,
)
models_app.add_typer(profile_app, name="profile")
models_app.add_typer(benchmark_app, name="benchmark")


def _emit_json(value: object) -> None:
    typer.echo(json.dumps(value, indent=2, sort_keys=True))


def _load_catalog_snapshot(path: Path) -> ModelCatalog:
    payload = json.loads(path.read_text())
    if "entries" in payload and "digest" in payload:
        catalog = ModelCatalog.model_validate(payload)
    else:
        catalog = ModelCatalog.from_payload(payload)
    catalog.verify_digests()
    return catalog


def _write_catalog_snapshot(path: Path, catalog: ModelCatalog) -> None:
    path.write_text(catalog.model_dump_json(indent=2) + "\n")
    os.chmod(path, 0o600)


class _ReadOnlyPromptRepository:
    """Minimal read-only repository surface for neutral benchmark prompt capture."""

    async def get_methodologies_by_tag(self, _tag: str, limit: int = 50) -> list:
        return []


@benchmark_app.command("fixtures")
def capture_benchmark_fixtures(
    suite: Path,
    repo_root: list[Path] = typer.Option(..., "--repo-root"),
    config: Path = typer.Option(Path("claw.toml"), "--config", "-c"),
    output: Path = typer.Option(..., "--output"),
) -> None:
    """Capture exact production prompts with neutral KB overlap and no model calls."""
    benchmark_suite = BenchmarkSuite.load(suite)
    claw_config = load_config(config)

    async def capture() -> list[MiningPromptFixture]:
        miner = RepoMiner(
            repository=_ReadOnlyPromptRepository(),
            llm_client=None,
            semantic_memory=None,
            config=claw_config,
            scan_ledger_path=output.parent / ".benchmark-fixture-ledger.json",
        )
        captured: list[MiningPromptFixture] = []
        for specification in benchmark_suite.fixtures:
            matches = [
                root / specification.name
                for root in repo_root
                if (root / specification.name).is_dir()
            ]
            if len(matches) != 1:
                raise ValueError(
                    f"Expected exactly one repo named {specification.name}, found {len(matches)}"
                )
            captured.append(
                await miner.prepare_mining_prompt(
                    matches[0],
                    specification.name,
                    specification.language,
                    set(),
                )
            )
        return captured

    fixtures = asyncio.run(capture())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            [fixture.model_dump(mode="json") for fixture in fixtures],
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    os.chmod(output, 0o600)
    typer.echo("NO MODEL CALLS MADE")
    typer.echo(f"Captured {len(fixtures)} frozen mining prompts: {output}")


@benchmark_app.command("plan")
def plan_benchmark(
    suite: Path,
    stage: str = typer.Option("first-round", "--stage"),
    fixtures: Path = typer.Option(..., "--fixtures"),
    catalog_snapshot: Path | None = typer.Option(None, "--catalog-snapshot"),
    candidate_set: Path | None = typer.Option(None, "--candidate-set"),
    baseline_model: str | None = typer.Option(None, "--baseline-model"),
    budget_usd: float = typer.Option(5.0, "--budget-usd", min=0.01),
    prior_spend_usd: float = typer.Option(0.0, "--prior-spend-usd", min=0.0),
    output: Path = typer.Option(Path("data/model_benchmarks/planned"), "--output"),
) -> None:
    """Freeze one worst-case-cost tournament stage without making paid calls."""
    if stage != "first-round":
        raise typer.BadParameter("Initial planning requires --stage first-round")
    benchmark_suite = BenchmarkSuite.load(suite)
    fixture_adapter = TypeAdapter(list[MiningPromptFixture])
    prompt_fixtures = fixture_adapter.validate_json(fixtures.read_text())
    if catalog_snapshot is not None:
        catalog = _load_catalog_snapshot(catalog_snapshot)
    else:
        catalog = asyncio.run(OpenRouterCatalogClient().fetch())
    candidates: list[str] | None = None
    if candidate_set is not None:
        if baseline_model is None:
            raise typer.BadParameter("--baseline-model is required with --candidate-set")
        imported = load_candidate_set(candidate_set, catalog=catalog)
        if imported.baseline_model != baseline_model:
            raise typer.BadParameter("--baseline-model must match the candidate-set baseline")
        candidates = list(imported.selected_model_ids)
    elif baseline_model is not None:
        raise typer.BadParameter("--baseline-model requires --candidate-set")
    plan = TournamentPlanner().plan_first_round(
        benchmark_suite,
        prompt_fixtures,
        catalog,
        authorization_usd=budget_usd,
        prior_spend_usd=prior_spend_usd,
        candidates=candidates,
    )
    if output.exists() and any(output.iterdir()):
        raise typer.BadParameter("Output directory already contains frozen evidence")
    output.mkdir(parents=True, exist_ok=True)
    plan_path = output / "plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2) + "\n")
    os.chmod(plan_path, 0o600)
    _write_catalog_snapshot(output / "catalog.json", catalog)
    typer.echo("NO PAID CALLS MADE")
    typer.echo(f"Run ID: {plan.run_id}")
    typer.echo(f"Stage: {plan.stage}")
    typer.echo(f"Stage maximum: ${plan.stage_maximum_cost_usd:.4f}")
    typer.echo(
        f"Cumulative maximum: ${plan.cumulative_maximum_cost_usd:.4f} / "
        f"${plan.authorization_usd:.2f}"
    )
    typer.echo(f"Remaining after maximum: ${plan.remaining_after_maximum_usd:.4f}")
    typer.echo(f"Plan: {plan_path}")


@benchmark_app.command("advance")
def advance_benchmark(
    parent_plan: Path,
    root_plan: Path | None = typer.Option(None, "--root-plan"),
    report: Path = typer.Option(..., "--report"),
    stage: str = typer.Option(..., "--stage"),
    suite: Path = typer.Option(..., "--suite"),
    fixtures: Path = typer.Option(..., "--fixtures"),
    catalog_snapshot: Path | None = typer.Option(None, "--catalog-snapshot"),
    output: Path = typer.Option(..., "--output"),
) -> None:
    """Freeze the next eligible tournament stage without making paid calls."""
    if stage not in {"heldout", "repeat"}:
        raise typer.BadParameter("--stage must be heldout or repeat")
    parent = TournamentStagePlan.model_validate_json(parent_plan.read_text())
    root = (
        TournamentStagePlan.model_validate_json(root_plan.read_text())
        if root_plan is not None
        else None
    )
    quality_report = BenchmarkQualityReport.model_validate_json(report.read_text())
    benchmark_suite = BenchmarkSuite.load(suite)
    fixture_adapter = TypeAdapter(list[MiningPromptFixture])
    prompt_fixtures = fixture_adapter.validate_json(fixtures.read_text())
    if catalog_snapshot is not None:
        catalog = _load_catalog_snapshot(catalog_snapshot)
    else:
        catalog = asyncio.run(OpenRouterCatalogClient().fetch())
    plan = TournamentPlanner().plan_advance(
        parent=parent,
        root=root,
        report=quality_report,
        suite=benchmark_suite,
        fixtures=prompt_fixtures,
        catalog=catalog,
        next_stage=stage,
    )
    if output.exists() and any(output.iterdir()):
        raise typer.BadParameter("Output directory already contains frozen evidence")
    output.mkdir(parents=True, exist_ok=True)
    plan_path = output / "plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2) + "\n")
    os.chmod(plan_path, 0o600)
    _write_catalog_snapshot(output / "catalog.json", catalog)
    typer.echo("NO PAID CALLS MADE")
    typer.echo(f"Run ID: {plan.run_id}")
    typer.echo(f"Stage: {plan.stage}")
    typer.echo(f"Candidates: {', '.join(plan.selected_candidates)}")
    typer.echo(f"Stage maximum: ${plan.stage_maximum_cost_usd:.4f}")
    typer.echo(
        f"Cumulative maximum: ${plan.cumulative_maximum_cost_usd:.4f} / "
        f"${plan.authorization_usd:.2f}"
    )
    typer.echo(f"Remaining after maximum: ${plan.remaining_after_maximum_usd:.4f}")
    typer.echo(f"Plan: {plan_path}")


@benchmark_app.command("run")
def run_benchmark(
    plan_path: Path,
    fixtures: Path = typer.Option(..., "--fixtures"),
    catalog_snapshot: Path | None = typer.Option(None, "--catalog-snapshot"),
    output: Path = typer.Option(..., "--output"),
    config: Path = typer.Option(Path("claw.toml"), "--config", "-c"),
    budget_usd: float | None = typer.Option(None, "--budget-usd", min=0.01),
    no_fallback: bool = typer.Option(True, "--no-fallback/--allow-fallback"),
    limit: int | None = typer.Option(None, "--limit", min=1),
    model: list[str] | None = typer.Option(None, "--model"),
) -> None:
    """Execute a frozen benchmark stage with exact models and call receipts."""
    plan_payload = json.loads(plan_path.read_text())
    tournament_plan = "authorization_usd" in plan_payload
    plan = (
        TournamentStagePlan.model_validate(plan_payload)
        if tournament_plan
        else BenchmarkPlan.model_validate(plan_payload)
    )
    if not no_fallback or not plan.no_fallback:
        raise typer.BadParameter("Benchmark execution requires --no-fallback")
    if budget_usd is not None:
        frozen_maximum = (
            plan.cumulative_maximum_cost_usd
            if tournament_plan
            else plan.maximum_cost_usd
        )
        if frozen_maximum > budget_usd:
            raise typer.BadParameter(
                f"Frozen maximum ${frozen_maximum:.4f} exceeds run cap ${budget_usd:.4f}"
            )
        if not tournament_plan:
            plan = plan.model_copy(update={"budget_usd": min(plan.budget_usd, budget_usd)})
    fixture_adapter = TypeAdapter(list[MiningPromptFixture])
    prompt_fixtures = fixture_adapter.validate_json(fixtures.read_text())
    if catalog_snapshot is not None:
        catalog = _load_catalog_snapshot(catalog_snapshot)
    elif tournament_plan:
        sibling_catalog = plan_path.parent / "catalog.json"
        if not sibling_catalog.is_file():
            raise typer.BadParameter(
                "Tournament execution requires its frozen sibling catalog.json"
            )
        catalog = _load_catalog_snapshot(sibling_catalog)
    else:
        catalog = asyncio.run(OpenRouterCatalogClient().fetch())
    output.mkdir(parents=True, exist_ok=True)
    frozen_plan_path = output / "plan.json"
    if frozen_plan_path.exists():
        if json.loads(frozen_plan_path.read_text()) != plan_payload:
            raise typer.BadParameter("Output directory contains a different frozen plan")
    else:
        if any(output.iterdir()):
            raise typer.BadParameter(
                "Nonempty output directory has no matching frozen plan"
            )
        frozen_plan_path.write_text(plan_path.read_text())
        os.chmod(frozen_plan_path, 0o600)
    claw_config = load_config(config)
    client = LLMClient(config=claw_config.llm)
    batch_client = OpenRouterBatchClient(api_key=client.api_key)

    async def execute():
        try:
            runner = BenchmarkRunner(
                plan=plan,
                fixtures=prompt_fixtures,
                catalog=catalog,
                client=client,
                batch_client=batch_client,
                run_dir=output,
                budget_usd=budget_usd,
            )
            if tournament_plan:
                return await runner.run_calls(
                    plan.calls,
                    limit=limit,
                    models=set(model) if model else None,
                )
            return await runner.run_first_round(
                limit=limit,
                models=set(model) if model else None,
            )
        finally:
            await client.close()
            await batch_client.close()

    summary = asyncio.run(execute())
    typer.echo(f"Completed: {summary.completed}")
    typer.echo(f"Resumed/skipped: {summary.skipped}")
    typer.echo(f"Failed: {summary.failed}")
    typer.echo(f"Actual recorded spend: ${summary.actual_cost_usd:.6f}")
    typer.echo(f"Receipts: {output / 'receipts'}")


def _quality_report_markdown(report: BenchmarkQualityReport) -> str:
    lines = [
        f"# CAM mining model comparison: {report.run_id}",
        "",
        f"Recorded provider spend: ${report.actual_cost_usd:.6f}",
        "",
        "| Model | Quality | Calls | Findings | Cost | Sync latency | Eligible |",
        "|---|---:|---:|---:|---:|---:|:---:|",
    ]
    for model in report.models:
        latency = (
            "batch"
            if model.average_sync_latency_seconds is None
            else f"{model.average_sync_latency_seconds:.2f}s"
        )
        lines.append(
            f"| {model.model_id} | {model.average_quality:.2f} | "
            f"{model.completed_calls} | {model.finding_count} | "
            f"${model.total_cost_usd:.6f} | {latency} | "
            f"{'yes' if model.eligible else 'no'} |"
        )
    return "\n".join(lines) + "\n"


@benchmark_app.command("report")
def report_benchmark(
    run_dir: Path,
    fixtures: Path = typer.Option(..., "--fixtures"),
    db: Path = typer.Option(
        ...,
        "--db",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Explicit read-only claw.db used for novelty scoring.",
    ),
    output_format: str = typer.Option("markdown", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Score completed receipts and report comparable model evidence."""
    if output_format not in {"json", "markdown"}:
        raise typer.BadParameter("--format must be json or markdown")
    plan_payload = json.loads((run_dir / "plan.json").read_text())
    fixture_adapter = TypeAdapter(list[MiningPromptFixture])
    prompt_fixtures = fixture_adapter.validate_json(fixtures.read_text())
    existing_titles = load_existing_mining_titles(db)
    expected_fixtures = (
        len(TournamentStagePlan.model_validate(plan_payload).fixtures)
        if "authorization_usd" in plan_payload
        else int(plan_payload["stage_policy"]["first_round_fixtures"])
    )
    report = score_benchmark_run(
        run_id=str(plan_payload["run_id"]),
        run_dir=run_dir,
        fixtures=prompt_fixtures,
        expected_fixtures=expected_fixtures,
        existing_titles=existing_titles,
        planned_calls=(
            TournamentStagePlan.model_validate(plan_payload).calls
            if "authorization_usd" in plan_payload
            else (
                BenchmarkPlan.model_validate(plan_payload).first_round_calls
                if "first_round_calls" in plan_payload
                else None
            )
        ),
    )
    content = (
        report.model_dump_json(indent=2) + "\n"
        if output_format == "json"
        else _quality_report_markdown(report)
    )
    if output is None:
        typer.echo(content, nl=False)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content)
    os.chmod(output, 0o600)
    typer.echo(f"Report: {output}")


def _selection_report_markdown(report: TournamentSelectionReport) -> str:
    lines = [
        f"# CAM mining-model tournament: {report.final_run_id}",
        "",
        f"Tournament spend: ${report.tournament_spend_usd:.6f}",
        f"Cumulative actual spend: ${report.cumulative_spend_usd:.6f}",
        f"Conservative cumulative maximum: "
        f"${report.conservative_cumulative_maximum_usd:.6f} / "
        f"${report.authorization_usd:.2f}",
        "",
        "| Role | Candidate | Reason | Promotion command |",
        "|---|---|---|---|",
    ]
    for role in ("quality", "budget", "fast", "batch"):
        candidate = report.roles[role]
        lines.append(
            f"| {role} | {candidate.model_id or 'none'} | {candidate.reason} | "
            f"{candidate.promotion_command or 'n/a'} |"
        )
    if report.exclusions:
        lines.extend(["", "## Exclusions", ""])
        for model_id, reasons in report.exclusions.items():
            lines.append(f"- `{model_id}`: {', '.join(reasons)}")
    lines.extend(
        [
            "",
            "No model profile was changed. Promotion commands require explicit execution.",
        ]
    )
    return "\n".join(lines) + "\n"


@benchmark_app.command("select")
def select_benchmark_roles(
    plan: list[Path] = typer.Option(..., "--plan"),
    report: list[Path] = typer.Option(..., "--report"),
    profile: str = typer.Option(..., "--profile"),
    output_format: str = typer.Option("markdown", "--format"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Select evidence-backed role candidates without changing model profiles."""
    if output_format not in {"json", "markdown"}:
        raise typer.BadParameter("--format must be json or markdown")
    plans = [TournamentStagePlan.model_validate_json(path.read_text()) for path in plan]
    reports = [
        BenchmarkQualityReport.model_validate_json(path.read_text()) for path in report
    ]
    selection = select_tournament_roles(
        plans=plans,
        reports=reports,
        profile=profile,
    )
    content = (
        selection.model_dump_json(indent=2) + "\n"
        if output_format == "json"
        else _selection_report_markdown(selection)
    )
    if output is None:
        typer.echo(content, nl=False)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content)
    os.chmod(output, 0o600)
    typer.echo(f"Selection report: {output}")
    typer.echo("No model profile was changed.")


@models_app.command("current")
def current_models(
    config: Path = typer.Option(Path("claw.toml"), "--config", "-c"),
    profiles: Path = typer.Option(Path("model_profiles.toml"), "--profiles"),
    output_format: str = typer.Option("table", "--format"),
) -> None:
    """Show the explicit config, corpus, active profile, and role assignments."""
    base = load_config(config)
    registry = load_model_profiles(profiles)
    payload = {
        "config_path": str(config.resolve()),
        "profile_path": str(profiles.resolve()),
        "database_path": base.database.db_path,
        "active_profile": registry.active_profile,
        "roles": registry.profiles[registry.active_profile].roles,
    }
    if output_format == "json":
        _emit_json(payload)
        return
    table = Table(title="CAM model roles")
    table.add_column("Role")
    table.add_column("Model")
    for role, model_id in sorted(payload["roles"].items()):
        table.add_row(role, model_id or "unassigned")
    console.print(table)
    console.print(f"Profile: {registry.active_profile}")
    console.print(f"Corpus: {base.database.db_path}")


@models_app.command("catalog")
def catalog_models(
    live: bool = typer.Option(True, "--live/--no-live"),
    model: list[str] | None = typer.Option(None, "--model"),
    output_format: str = typer.Option("table", "--format"),
) -> None:
    """Fetch current OpenRouter availability, prices, limits, and capabilities."""
    if not live:
        raise typer.BadParameter("Catalog lookup is live-only; no stale cache is authoritative")
    catalog = asyncio.run(OpenRouterCatalogClient().fetch())
    selected = model or sorted(catalog.entries)
    entries = [catalog.require(model_id) for model_id in selected]
    if output_format == "json":
        _emit_json(
            {
                "catalog_digest": catalog.digest,
                "models": [entry.model_dump(mode="json") for entry in entries],
            }
        )
        return
    table = Table(title="OpenRouter live model catalog")
    table.add_column("Model")
    table.add_column("Input / 1M", justify="right")
    table.add_column("Output / 1M", justify="right")
    table.add_column("Context", justify="right")
    table.add_column("Batch")
    for entry in entries:
        table.add_row(
            entry.requested_id,
            f"${entry.pricing.prompt_per_million:g}",
            f"${entry.pricing.completion_per_million:g}",
            f"{entry.context_length:,}",
            "yes" if entry.is_batch else "no",
        )
    console.print(table)


@profile_app.command("list")
def list_profiles(
    profiles: Path = typer.Option(Path("model_profiles.toml"), "--profiles"),
    output_format: str = typer.Option("table", "--format"),
) -> None:
    """List available profiles without changing runtime state."""
    registry = load_model_profiles(profiles)
    rows = [
        {"name": name, "active": name == registry.active_profile}
        for name in sorted(
            registry.profiles,
            key=lambda item: (item != registry.active_profile, item),
        )
    ]
    if output_format == "json":
        _emit_json(rows)
        return
    for row in rows:
        marker = "*" if row["active"] else " "
        typer.echo(f"{marker} {row['name']}")


@profile_app.command("show")
def show_profile(
    profile: str | None = typer.Argument(None),
    profiles: Path = typer.Option(Path("model_profiles.toml"), "--profiles"),
    output_format: str = typer.Option("table", "--format"),
) -> None:
    """Show one profile and its role assignments."""
    registry = load_model_profiles(profiles)
    profile_name = profile or registry.active_profile
    if profile_name not in registry.profiles:
        raise typer.BadParameter(f"Unknown model profile: {profile_name}")
    roles = registry.profiles[profile_name].roles
    if output_format == "json":
        _emit_json({"name": profile_name, "roles": roles})
        return
    typer.echo(f"Profile: {profile_name}")
    for role, model_id in sorted(roles.items()):
        typer.echo(f"{role}: {model_id or 'unassigned'}")


@profile_app.command("use")
def use_profile(
    profile: str,
    profiles: Path = typer.Option(Path("model_profiles.toml"), "--profiles"),
) -> None:
    """Atomically select an existing profile."""
    activate_profile(profiles, profile)
    typer.echo(f"Active model profile: {profile}")


@models_app.command("set")
def set_model(
    role: str,
    model_id: str,
    profile: str | None = typer.Option(None, "--profile"),
    profiles: Path = typer.Option(Path("model_profiles.toml"), "--profiles"),
    receipt: Path = typer.Option(Path("data/model_profiles/last_promotion.json"), "--receipt"),
) -> None:
    """Validate live availability, then atomically assign one role."""
    registry = load_model_profiles(profiles)
    profile_name = profile or registry.active_profile
    catalog = asyncio.run(OpenRouterCatalogClient().fetch())
    catalog.require(model_id)
    promotion = promote_role(
        profiles,
        profile_name,
        role,
        model_id,
        allowed_model_ids=set(catalog.entries),
    )
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(promotion.model_dump_json(indent=2) + "\n")
    typer.echo(f"Set {profile_name}.{role} = {model_id}")
    typer.echo(f"Rollback receipt: {receipt}")


@models_app.command("rollback")
def rollback_model(
    receipt: Path,
    profiles: Path = typer.Option(Path("model_profiles.toml"), "--profiles"),
) -> None:
    """Roll back one promotion when the registry still matches its receipt."""
    promotion = PromotionReceipt.model_validate_json(receipt.read_text())
    rollback_promotion(profiles, promotion)
    typer.echo(f"Restored {promotion.profile}.{promotion.role} = {promotion.previous_model}")
