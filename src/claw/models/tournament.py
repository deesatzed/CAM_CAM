"""Adaptive, budget-bounded tournament planning for CAM mining models."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from claw.models.benchmark import (
    BenchmarkSuite,
    CatalogReceipt,
    FixtureReceipt,
    MiningPromptFixture,
    PlannedCall,
    _maximum_call_cost,
)
from claw.models.catalog import ModelCatalog, ModelCatalogEntry
from claw.models.scoring import BenchmarkQualityReport, ModelQualitySummary

TournamentStage = Literal["first-round", "heldout", "repeat"]


class TournamentStagePlan(BaseModel):
    """One immutable, executable tournament stage under a cumulative cap."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str
    created_at: str
    suite_name: str
    stage: TournamentStage
    authorization_usd: float
    prior_spend_usd: float
    stage_maximum_cost_usd: float
    parent_run_id: str | None = None
    catalog_receipt: CatalogReceipt
    fixtures: list[FixtureReceipt]
    calls: list[PlannedCall]
    selected_candidates: list[str]
    excluded_candidates: dict[str, list[str]] = Field(default_factory=dict)
    no_fallback: bool = True

    @computed_field
    @property
    def cumulative_maximum_cost_usd(self) -> float:
        return self.prior_spend_usd + self.stage_maximum_cost_usd

    @computed_field
    @property
    def remaining_after_maximum_usd(self) -> float:
        return self.authorization_usd - self.cumulative_maximum_cost_usd

    @model_validator(mode="after")
    def validate_plan(self) -> "TournamentStagePlan":
        if self.schema_version != 1:
            raise ValueError(f"Unsupported tournament plan schema: {self.schema_version}")
        if self.authorization_usd <= 0:
            raise ValueError("Tournament authorization must be positive")
        if self.prior_spend_usd < 0 or self.stage_maximum_cost_usd < 0:
            raise ValueError("Tournament spend values cannot be negative")
        if self.cumulative_maximum_cost_usd > self.authorization_usd + 1e-12:
            raise ValueError(
                f"Cumulative maximum ${self.cumulative_maximum_cost_usd:.6f} "
                f"exceeds authorization ${self.authorization_usd:.6f}"
            )
        if len(self.selected_candidates) != len(set(self.selected_candidates)):
            raise ValueError("Selected candidates must be unique")
        if any(call.stage != self.stage for call in self.calls):
            raise ValueError("Call stages must match the tournament plan stage")
        selected = set(self.selected_candidates)
        if any(call.model_id not in selected for call in self.calls):
            raise ValueError("Every call model must be a selected candidate")
        planned_cost = sum(call.maximum_cost_usd for call in self.calls)
        if abs(planned_cost - self.stage_maximum_cost_usd) > 1e-9:
            raise ValueError("Stage maximum must equal the sum of frozen calls")
        return self


def _fixture_receipt(fixture: MiningPromptFixture, stage: TournamentStage) -> FixtureReceipt:
    return FixtureReceipt(
        repo_name=fixture.repo_name,
        git_head=fixture.git_head,
        brain=fixture.brain,
        prompt_sha256=fixture.prompt_sha256,
        repo_content_sha256=fixture.repo_content_sha256,
        source_manifest=fixture.source_manifest,
        file_count=fixture.file_count,
        estimated_tokens=fixture.estimated_tokens,
        token_budget=fixture.token_budget,
        stage=stage,
    )


class TournamentPlanner:
    """Freeze only the tournament calls authorized for the current stage."""

    _REQUESTED_PARAMETERS = frozenset(
        {"max_tokens", "temperature", "seed", "reasoning"}
    )

    def _freeze_calls(
        self,
        *,
        stage: TournamentStage,
        candidates: list[str],
        fixtures: list[MiningPromptFixture],
        catalog: ModelCatalog,
    ) -> list[PlannedCall]:
        calls: list[PlannedCall] = []
        for model_id in candidates:
            entry: ModelCatalogEntry = catalog.require(model_id)
            for fixture in fixtures:
                output_tokens = min(
                    fixture.token_budget,
                    entry.max_completion_tokens or fixture.token_budget,
                )
                call_seed = (
                    f"{stage}|{model_id}|{fixture.prompt_sha256}|{entry.catalog_digest}"
                )
                calls.append(
                    PlannedCall(
                        call_id=hashlib.sha256(call_seed.encode()).hexdigest()[:20],
                        stage=stage,
                        model_id=model_id,
                        fixture_name=fixture.repo_name,
                        prompt_sha256=fixture.prompt_sha256,
                        repo_content_sha256=fixture.repo_content_sha256,
                        catalog_digest=entry.catalog_digest,
                        maximum_input_tokens=fixture.estimated_tokens,
                        maximum_output_tokens=output_tokens,
                        maximum_cost_usd=_maximum_call_cost(
                            entry,
                            fixture.estimated_tokens,
                            output_tokens,
                        ),
                        parameters=sorted(
                            self._REQUESTED_PARAMETERS & entry.supported_parameters
                        ),
                        reasoning_effort=(
                            entry.reasoning.lowest_supported_effort()
                            if entry.reasoning is not None
                            and "reasoning" in entry.supported_parameters
                            else None
                        ),
                        transport=(
                            "batch-compatibility" if entry.is_batch else "chat-completions"
                        ),
                    )
                )
        return calls

    def plan_first_round(
        self,
        suite: BenchmarkSuite,
        fixtures: list[MiningPromptFixture],
        catalog: ModelCatalog,
        *,
        authorization_usd: float,
        prior_spend_usd: float = 0.0,
    ) -> TournamentStagePlan:
        if authorization_usd <= 0:
            raise ValueError("Tournament authorization must be positive")
        if prior_spend_usd < 0:
            raise ValueError("Prior spend cannot be negative")
        by_name = {fixture.repo_name: fixture for fixture in fixtures}
        expected = {item.name for item in suite.fixtures}
        if set(by_name) != expected:
            raise ValueError("Prompt fixtures do not match the benchmark suite")
        dirty = [fixture.repo_name for fixture in fixtures if fixture.dirty_paths]
        if dirty:
            raise ValueError(f"Benchmark fixtures must be clean: {', '.join(sorted(dirty))}")

        first_names = [
            item.name for item in suite.fixtures if item.stage == "first-round"
        ]
        first_round = [by_name[name] for name in first_names]
        calls = self._freeze_calls(
            stage="first-round",
            candidates=suite.candidates,
            fixtures=first_round,
            catalog=catalog,
        )
        stage_maximum = sum(call.maximum_cost_usd for call in calls)
        cumulative_maximum = prior_spend_usd + stage_maximum
        if cumulative_maximum > authorization_usd + 1e-12:
            raise ValueError(
                f"Cumulative maximum ${cumulative_maximum:.4f} exceeds authorization "
                f"${authorization_usd:.4f}"
            )

        entries = {model_id: catalog.require(model_id) for model_id in suite.candidates}
        now = datetime.now(UTC)
        seed = f"{suite.name}|first-round|{catalog.digest}|" + "|".join(
            fixture.prompt_sha256 for fixture in first_round
        )
        return TournamentStagePlan(
            run_id=(
                f"{now.strftime('%Y%m%dT%H%M%SZ')}-"
                f"{hashlib.sha256(seed.encode()).hexdigest()[:8]}-first-round"
            ),
            created_at=now.isoformat(),
            suite_name=suite.name,
            stage="first-round",
            authorization_usd=authorization_usd,
            prior_spend_usd=prior_spend_usd,
            stage_maximum_cost_usd=stage_maximum,
            catalog_receipt=CatalogReceipt(
                digest=catalog.digest,
                model_digests={
                    model_id: entries[model_id].catalog_digest
                    for model_id in suite.candidates
                },
            ),
            fixtures=[_fixture_receipt(fixture, "first-round") for fixture in first_round],
            calls=calls,
            selected_candidates=list(suite.candidates),
        )

    def plan_advance(
        self,
        *,
        parent: TournamentStagePlan,
        report: BenchmarkQualityReport,
        suite: BenchmarkSuite,
        fixtures: list[MiningPromptFixture],
        catalog: ModelCatalog,
        next_stage: Literal["heldout", "repeat"],
    ) -> TournamentStagePlan:
        expected_next = {
            "first-round": "heldout",
            "heldout": "repeat",
        }.get(parent.stage)
        if expected_next != next_stage:
            raise ValueError(
                f"Invalid tournament transition: {parent.stage} -> {next_stage}"
            )
        if report.run_id != parent.run_id:
            raise ValueError("Quality report run does not match the parent plan")

        by_name = {fixture.repo_name: fixture for fixture in fixtures}
        expected_names = {item.name for item in suite.fixtures}
        if set(by_name) != expected_names:
            raise ValueError("Prompt fixtures do not match the benchmark suite")
        dirty = [fixture.repo_name for fixture in fixtures if fixture.dirty_paths]
        if dirty:
            raise ValueError(f"Benchmark fixtures must be clean: {', '.join(sorted(dirty))}")

        report_by_model = {model.model_id: model for model in report.models}
        excluded: dict[str, list[str]] = {}
        for model_id in parent.selected_candidates:
            summary = report_by_model.get(model_id)
            if summary is None or summary.completed_calls != report.expected_fixtures:
                excluded[model_id] = ["missing_expected_calls"]
            elif not summary.eligible:
                excluded[model_id] = list(
                    summary.hard_failures or ["quality_below_gate"]
                )

        ranked = rank_eligible_models(
            [
                summary
                for model_id, summary in report_by_model.items()
                if model_id in parent.selected_candidates
            ]
        )
        candidate_limit = 4 if next_stage == "heldout" else 2
        ranked_prefix = ranked[:candidate_limit]
        for summary in ranked[candidate_limit:]:
            excluded[summary.model_id] = ["not_selected_for_stage"]
        if not ranked_prefix:
            raise ValueError("No eligible candidates are available for advancement")

        if next_stage == "heldout":
            stage_names = [
                item.name for item in suite.fixtures if item.stage == "heldout"
            ]
        else:
            stage_names = [
                next(item.name for item in suite.fixtures if item.stage == "first-round")
            ]
        stage_fixtures = [by_name[name] for name in stage_names]
        prior_spend = parent.prior_spend_usd + report.actual_cost_usd

        selected: list[str] = []
        calls: list[PlannedCall] = []
        for count in range(len(ranked_prefix), 0, -1):
            candidate_ids = [summary.model_id for summary in ranked_prefix[:count]]
            candidate_calls = self._freeze_calls(
                stage=next_stage,
                candidates=candidate_ids,
                fixtures=stage_fixtures,
                catalog=catalog,
            )
            if (
                prior_spend + sum(call.maximum_cost_usd for call in candidate_calls)
                <= parent.authorization_usd + 1e-12
            ):
                selected = candidate_ids
                calls = candidate_calls
                break
        if not selected:
            raise ValueError(
                f"No {next_stage} candidate fits the remaining tournament authorization"
            )
        for summary in ranked_prefix[len(selected) :]:
            excluded[summary.model_id] = ["not_selected_within_remaining_budget"]

        entries = {model_id: catalog.require(model_id) for model_id in selected}
        now = datetime.now(UTC)
        seed = (
            f"{suite.name}|{next_stage}|{parent.run_id}|{catalog.digest}|"
            + "|".join(fixture.prompt_sha256 for fixture in stage_fixtures)
            + "|"
            + "|".join(selected)
        )
        stage_maximum = sum(call.maximum_cost_usd for call in calls)
        return TournamentStagePlan(
            run_id=(
                f"{now.strftime('%Y%m%dT%H%M%SZ')}-"
                f"{hashlib.sha256(seed.encode()).hexdigest()[:8]}-{next_stage}"
            ),
            created_at=now.isoformat(),
            suite_name=suite.name,
            stage=next_stage,
            authorization_usd=parent.authorization_usd,
            prior_spend_usd=prior_spend,
            stage_maximum_cost_usd=stage_maximum,
            parent_run_id=parent.run_id,
            catalog_receipt=CatalogReceipt(
                digest=catalog.digest,
                model_digests={
                    model_id: entries[model_id].catalog_digest for model_id in selected
                },
            ),
            fixtures=[
                _fixture_receipt(fixture, next_stage) for fixture in stage_fixtures
            ],
            calls=calls,
            selected_candidates=selected,
            excluded_candidates=excluded,
        )


def rank_eligible_models(
    summaries: list[ModelQualitySummary],
) -> list[ModelQualitySummary]:
    """Order eligible models by quality floor, value, and stable tie-breakers."""

    eligible = [summary for summary in summaries if summary.eligible]

    def rank_key(summary: ModelQualitySummary) -> tuple:
        return (
            -summary.worst_quality,
            -summary.average_quality,
            (
                summary.cost_per_finding_usd
                if summary.cost_per_finding_usd is not None
                else float("inf")
            ),
            summary.total_cost_usd,
            summary.average_sync_latency_seconds is None,
            (
                summary.average_sync_latency_seconds
                if summary.average_sync_latency_seconds is not None
                else float("inf")
            ),
            summary.model_id,
        )

    return sorted(eligible, key=rank_key)
