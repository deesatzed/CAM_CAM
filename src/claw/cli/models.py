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
    BenchmarkPlanner,
    BenchmarkRunner,
    BenchmarkSuite,
    MiningPromptFixture,
)
from claw.models.catalog import ModelCatalog, OpenRouterCatalogClient
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
    fixtures: Path = typer.Option(..., "--fixtures"),
    catalog_snapshot: Path | None = typer.Option(None, "--catalog-snapshot"),
    budget_usd: float = typer.Option(5.0, "--budget-usd", min=0.01),
    output: Path = typer.Option(Path("data/model_benchmarks/planned"), "--output"),
) -> None:
    """Freeze a worst-case-cost benchmark plan without making paid calls."""
    benchmark_suite = BenchmarkSuite.load(suite)
    fixture_adapter = TypeAdapter(list[MiningPromptFixture])
    prompt_fixtures = fixture_adapter.validate_json(fixtures.read_text())
    if catalog_snapshot is not None:
        catalog = ModelCatalog.from_payload(json.loads(catalog_snapshot.read_text()))
    else:
        catalog = asyncio.run(OpenRouterCatalogClient().fetch())
    plan = BenchmarkPlanner().plan(
        benchmark_suite,
        prompt_fixtures,
        catalog,
        budget_usd=budget_usd,
    )
    output.mkdir(parents=True, exist_ok=True)
    plan_path = output / "plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2) + "\n")
    os.chmod(plan_path, 0o600)
    typer.echo("NO PAID CALLS MADE")
    typer.echo(f"Run ID: {plan.run_id}")
    typer.echo(f"Worst-case reserved spend: ${plan.maximum_cost_usd:.4f} / ${budget_usd:.2f}")
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
    """Execute a frozen first round with exact models and per-call receipts."""
    plan = BenchmarkPlan.model_validate_json(plan_path.read_text())
    if not no_fallback or not plan.no_fallback:
        raise typer.BadParameter("Benchmark execution requires --no-fallback")
    if budget_usd is not None:
        if plan.maximum_cost_usd > budget_usd:
            raise typer.BadParameter(
                f"Frozen maximum ${plan.maximum_cost_usd:.4f} exceeds run cap ${budget_usd:.4f}"
            )
        plan = plan.model_copy(update={"budget_usd": min(plan.budget_usd, budget_usd)})
    fixture_adapter = TypeAdapter(list[MiningPromptFixture])
    prompt_fixtures = fixture_adapter.validate_json(fixtures.read_text())
    if catalog_snapshot is not None:
        catalog = ModelCatalog.from_payload(json.loads(catalog_snapshot.read_text()))
    else:
        catalog = asyncio.run(OpenRouterCatalogClient().fetch())
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
    report = score_benchmark_run(
        run_id=str(plan_payload["run_id"]),
        run_dir=run_dir,
        fixtures=prompt_fixtures,
        expected_fixtures=int(plan_payload["stage_policy"]["first_round_fixtures"]),
        existing_titles=existing_titles,
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
