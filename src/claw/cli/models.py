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
from claw.models.benchmark import BenchmarkPlanner, BenchmarkSuite, MiningPromptFixture
from claw.models.catalog import ModelCatalog, OpenRouterCatalogClient
from claw.models.profiles import (
    PromotionReceipt,
    activate_profile,
    load_model_profiles,
    promote_role,
    rollback_promotion,
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
