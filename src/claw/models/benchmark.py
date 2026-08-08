"""Frozen inputs and evidence types for CAM mining-model benchmarks."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import toml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from claw.models.catalog import ModelCatalog, ModelCatalogEntry


class MiningPromptFixture(BaseModel):
    """Exact, content-addressed prompt emitted by the production miner."""

    model_config = ConfigDict(frozen=True)

    repo_path: str
    repo_name: str
    git_head: str | None = None
    dirty_paths: list[str] = Field(default_factory=list)
    brain: str
    prompt: str
    prompt_sha256: str
    repo_content: str
    repo_content_sha256: str
    source_manifest: list[str]
    repo_bytes: int
    file_count: int
    estimated_tokens: int
    token_budget: int
    domain_info: dict
    overlap: dict


class SuiteFixture(BaseModel):
    name: str
    language: str
    stage: Literal["first-round", "heldout"]


class BenchmarkSuite(BaseModel):
    schema_version: int = 1
    name: str
    description: str = ""
    candidates: list[str]
    fixtures: list[SuiteFixture]

    @model_validator(mode="after")
    def validate_suite(self) -> "BenchmarkSuite":
        if self.schema_version != 1:
            raise ValueError(f"Unsupported benchmark suite schema: {self.schema_version}")
        if len(self.candidates) != len(set(self.candidates)):
            raise ValueError("Benchmark candidates must be unique")
        if len([item for item in self.fixtures if item.stage == "first-round"]) != 3:
            raise ValueError("Benchmark suite requires exactly three first-round fixtures")
        if len([item for item in self.fixtures if item.stage == "heldout"]) != 2:
            raise ValueError("Benchmark suite requires exactly two heldout fixtures")
        return self

    @classmethod
    def load(cls, path: Path) -> "BenchmarkSuite":
        return cls.model_validate(toml.load(path))


class FixtureReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    repo_name: str
    git_head: str | None
    brain: str
    prompt_sha256: str
    repo_content_sha256: str
    source_manifest: list[str]
    file_count: int
    estimated_tokens: int
    token_budget: int
    stage: str


class CatalogReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    digest: str
    model_digests: dict[str, str]


class PlannedCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    call_id: str
    stage: str
    model_id: str
    fixture_name: str
    prompt_sha256: str
    repo_content_sha256: str
    catalog_digest: str
    maximum_input_tokens: int
    maximum_output_tokens: int
    maximum_cost_usd: float
    parameters: list[str]
    transport: str = "chat-completions"


class BenchmarkPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str
    created_at: str
    suite_name: str
    status: Literal["planned"] = "planned"
    budget_usd: float
    maximum_cost_usd: float
    smoke_reserve_usd: float
    heldout_reserve_usd: float
    repeat_reserve_usd: float
    catalog_receipt: CatalogReceipt
    fixtures: list[FixtureReceipt]
    first_round_calls: list[PlannedCall]
    stage_policy: dict[str, int]
    no_fallback: bool = True


def _price_for_tokens(entry: ModelCatalogEntry, prompt_tokens: int) -> tuple[float, float]:
    prompt_price = entry.pricing.prompt_per_million
    completion_price = entry.pricing.completion_per_million
    for override in sorted(
        entry.pricing.overrides,
        key=lambda item: int(item.get("min_prompt_tokens", 0)),
    ):
        if prompt_tokens >= int(override.get("min_prompt_tokens", 0)):
            prompt_price = float(override.get("prompt_per_million", prompt_price))
            completion_price = float(
                override.get("completion_per_million", completion_price)
            )
    return prompt_price, completion_price


def _maximum_call_cost(
    entry: ModelCatalogEntry,
    input_tokens: int,
    output_tokens: int,
) -> float:
    prompt_price, completion_price = _price_for_tokens(entry, input_tokens)
    return (input_tokens * prompt_price + output_tokens * completion_price) / 1_000_000


class BenchmarkPlanner:
    """Create a no-spend comparison plan with a conservative hard cost bound."""

    _REQUESTED_PARAMETERS = frozenset(
        {"max_tokens", "temperature", "seed", "structured_outputs"}
    )

    def plan(
        self,
        suite: BenchmarkSuite,
        fixtures: list[MiningPromptFixture],
        catalog: ModelCatalog,
        *,
        budget_usd: float,
    ) -> BenchmarkPlan:
        if budget_usd <= 0:
            raise ValueError("Benchmark budget must be positive")
        by_name = {fixture.repo_name: fixture for fixture in fixtures}
        expected_names = {fixture.name for fixture in suite.fixtures}
        if set(by_name) != expected_names:
            raise ValueError("Prompt fixtures do not match the benchmark suite")
        dirty = [fixture.repo_name for fixture in fixtures if fixture.dirty_paths]
        if dirty:
            raise ValueError(f"Benchmark fixtures must be clean: {', '.join(sorted(dirty))}")

        entries = {model_id: catalog.require(model_id) for model_id in suite.candidates}
        stage_by_name = {fixture.name: fixture.stage for fixture in suite.fixtures}
        fixture_receipts = [
            FixtureReceipt(
                repo_name=fixture.repo_name,
                git_head=fixture.git_head,
                brain=fixture.brain,
                prompt_sha256=fixture.prompt_sha256,
                repo_content_sha256=fixture.repo_content_sha256,
                source_manifest=fixture.source_manifest,
                file_count=fixture.file_count,
                estimated_tokens=fixture.estimated_tokens,
                token_budget=fixture.token_budget,
                stage=stage_by_name[fixture.repo_name],
            )
            for fixture in sorted(fixtures, key=lambda item: item.repo_name)
        ]

        first_round = [item for item in fixtures if stage_by_name[item.repo_name] == "first-round"]
        heldout = [item for item in fixtures if stage_by_name[item.repo_name] == "heldout"]
        calls: list[PlannedCall] = []
        for model_id in suite.candidates:
            entry = entries[model_id]
            for fixture in first_round:
                output_tokens = fixture.token_budget
                if entry.max_completion_tokens is not None:
                    output_tokens = min(output_tokens, entry.max_completion_tokens)
                cost = _maximum_call_cost(entry, fixture.estimated_tokens, output_tokens)
                call_seed = (
                    f"first-round|{model_id}|{fixture.prompt_sha256}|{entry.catalog_digest}"
                )
                calls.append(
                    PlannedCall(
                        call_id=hashlib.sha256(call_seed.encode()).hexdigest()[:20],
                        stage="first-round",
                        model_id=model_id,
                        fixture_name=fixture.repo_name,
                        prompt_sha256=fixture.prompt_sha256,
                        repo_content_sha256=fixture.repo_content_sha256,
                        catalog_digest=entry.catalog_digest,
                        maximum_input_tokens=fixture.estimated_tokens,
                        maximum_output_tokens=output_tokens,
                        maximum_cost_usd=cost,
                        parameters=sorted(
                            self._REQUESTED_PARAMETERS & entry.supported_parameters
                        ),
                        transport=(
                            "batch-compatibility" if entry.is_batch else "chat-completions"
                        ),
                    )
                )

        smoke_reserve = sum(
            _maximum_call_cost(entry, 256, min(256, entry.max_completion_tokens or 256))
            for entry in entries.values()
        )
        heldout_reserve = 0.0
        for fixture in heldout:
            candidate_costs = sorted(
                (
                    _maximum_call_cost(
                        entry,
                        fixture.estimated_tokens,
                        min(
                            fixture.token_budget,
                            entry.max_completion_tokens or fixture.token_budget,
                        ),
                    )
                    for entry in entries.values()
                ),
                reverse=True,
            )
            heldout_reserve += sum(candidate_costs[:4])
        repeat_candidate_costs = sorted(
            (
                max(
                    _maximum_call_cost(
                        entry,
                        fixture.estimated_tokens,
                        min(
                            fixture.token_budget,
                            entry.max_completion_tokens or fixture.token_budget,
                        ),
                    )
                    for fixture in first_round
                )
                for entry in entries.values()
            ),
            reverse=True,
        )
        repeat_reserve = sum(repeat_candidate_costs[:2])
        maximum_cost = (
            smoke_reserve
            + sum(call.maximum_cost_usd for call in calls)
            + heldout_reserve
            + repeat_reserve
        )
        if maximum_cost > budget_usd:
            raise ValueError(
                f"Projected maximum cost ${maximum_cost:.4f} exceeds budget ${budget_usd:.4f}"
            )

        run_seed = f"{suite.name}|{catalog.digest}|" + "|".join(
            item.prompt_sha256 for item in fixture_receipts
        )
        return BenchmarkPlan(
            run_id=f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{hashlib.sha256(run_seed.encode()).hexdigest()[:8]}",
            created_at=datetime.now(UTC).isoformat(),
            suite_name=suite.name,
            budget_usd=budget_usd,
            maximum_cost_usd=maximum_cost,
            smoke_reserve_usd=smoke_reserve,
            heldout_reserve_usd=heldout_reserve,
            repeat_reserve_usd=repeat_reserve,
            catalog_receipt=CatalogReceipt(
                digest=catalog.digest,
                model_digests={
                    model_id: entries[model_id].catalog_digest for model_id in suite.candidates
                },
            ),
            fixtures=fixture_receipts,
            first_round_calls=calls,
            stage_policy={
                "first_round_candidates": len(suite.candidates),
                "first_round_fixtures": len(first_round),
                "heldout_candidates": 4,
                "heldout_fixtures": len(heldout),
                "repeat_candidates": 2,
                "repeat_fixtures": 1,
            },
        )
