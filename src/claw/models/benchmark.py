"""Frozen inputs and evidence types for CAM mining-model benchmarks."""

from __future__ import annotations

import hashlib
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import toml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from claw.llm.client import LLMMessage
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


class BudgetLedger(BaseModel):
    """In-process authorization ledger that reserves worst-case cost before calls."""

    budget_usd: float
    reserved_usd: float = 0.0
    actual_cost_usd: float = 0.0

    def authorize(self, maximum_call_cost: float) -> None:
        projected = self.actual_cost_usd + self.reserved_usd + maximum_call_cost
        if projected > self.budget_usd + 1e-12:
            raise ValueError(
                f"Request would cross benchmark budget cap: ${projected:.6f} > "
                f"${self.budget_usd:.6f}"
            )
        self.reserved_usd += maximum_call_cost

    def reconcile(self, reserved_cost: float, actual_cost: float) -> None:
        self.reserved_usd = max(0.0, self.reserved_usd - reserved_cost)
        self.actual_cost_usd += actual_cost
        if self.actual_cost_usd > self.budget_usd + 1e-12:
            raise ValueError("Provider-reported cost exceeded benchmark budget cap")


class CallReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    call_id: str
    status: Literal["completed", "failed"]
    requested_model: str
    returned_model: str | None = None
    fixture_name: str
    prompt_sha256: str
    request_id: str | None = None
    finish_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_input_tokens: int = 0
    cost_usd: float = 0.0
    cost_source: str = "estimated"
    transport: str = "chat-completions"
    duration_seconds: float = 0.0
    response_path: str | None = None
    batch_job_id: str | None = None
    retention_days: int | None = None
    error: str | None = None


class BenchmarkRunSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    completed: int
    failed: int
    skipped: int
    actual_cost_usd: float
    receipt_paths: list[str]


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


def _atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(content)
    os.chmod(temp_path, mode)
    temp_path.replace(path)


def _redact_error(message: str) -> str:
    redacted = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED_API_KEY]", message)
    return re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", redacted, flags=re.IGNORECASE)


class BenchmarkRunner:
    """Run exact planned calls one at a time with resumable local receipts."""

    def __init__(
        self,
        *,
        plan: BenchmarkPlan,
        fixtures: list[MiningPromptFixture],
        catalog: ModelCatalog,
        client,
        run_dir: Path,
        batch_client=None,
    ) -> None:
        self.plan = plan
        self.fixtures = {fixture.repo_name: fixture for fixture in fixtures}
        self.catalog = catalog
        self.client = client
        self.batch_client = batch_client
        self.run_dir = run_dir
        self.ledger = BudgetLedger(budget_usd=plan.budget_usd)

    def _validate_call(self, call: PlannedCall) -> MiningPromptFixture:
        fixture = self.fixtures[call.fixture_name]
        if hashlib.sha256(fixture.prompt.encode()).hexdigest() != call.prompt_sha256:
            raise ValueError(f"Prompt drift for fixture {fixture.repo_name}")
        if hashlib.sha256(fixture.repo_content.encode()).hexdigest() != call.repo_content_sha256:
            raise ValueError(f"Source drift for fixture {fixture.repo_name}")
        entry = self.catalog.require(call.model_id)
        if entry.catalog_digest != call.catalog_digest:
            raise ValueError(f"Catalog drift for model {call.model_id}")
        return fixture

    @staticmethod
    def _validate_returned_model(
        requested_model: str,
        returned_model: str,
        entry: ModelCatalogEntry,
    ) -> None:
        allowed = {
            requested_model,
            requested_model.removesuffix(":batch"),
            entry.canonical_slug,
        }
        rolling_alias_match = False
        if requested_model.startswith("~") and requested_model.endswith("-latest"):
            family = requested_model[1:].removesuffix("-latest")
            rolling_alias_match = returned_model.startswith(f"{family}-")
        if returned_model not in allowed and not rolling_alias_match:
            raise ValueError(
                f"Returned model drift: requested {requested_model}, got {returned_model}"
            )

    def _load_existing_receipt(self, path: Path) -> CallReceipt | None:
        if not path.exists():
            return None
        receipt = CallReceipt.model_validate_json(path.read_text())
        if receipt.status != "completed":
            return None
        return receipt

    async def run_first_round(
        self,
        *,
        limit: int | None = None,
        models: set[str] | None = None,
    ) -> BenchmarkRunSummary:
        calls = self.plan.first_round_calls
        if models is not None:
            planned_models = {call.model_id for call in calls}
            unknown = models - planned_models
            if unknown:
                raise ValueError(
                    f"Models are not in frozen plan: {', '.join(sorted(unknown))}"
                )
            calls = [call for call in calls if call.model_id in models]
        if limit is not None:
            calls = calls[:limit]
        completed = 0
        failed = 0
        skipped = 0
        receipt_paths: list[str] = []
        for call in calls:
            receipt_path = self.run_dir / "receipts" / f"{call.call_id}.json"
            existing = self._load_existing_receipt(receipt_path)
            if existing is not None:
                skipped += 1
                self.ledger.actual_cost_usd += existing.cost_usd
                receipt_paths.append(str(receipt_path))
                continue

            fixture = self._validate_call(call)
            self.ledger.authorize(call.maximum_cost_usd)
            started = time.monotonic()
            response = None
            response_path = None
            batch_job_id = None
            retention_days = None
            actual_cost = 0.0
            cost_source = "estimated"
            reconciled = False
            try:
                entry = self.catalog.require(call.model_id)
                response_format = (
                    {"type": "json_object"}
                    if "structured_outputs" in call.parameters
                    else None
                )
                if entry.is_batch:
                    if self.batch_client is None:
                        raise RuntimeError("Batch model requires an OpenRouter batch client")
                    batch = await self.batch_client.complete(
                        messages=[LLMMessage(role="user", content=fixture.prompt)],
                        requested_model=call.model_id,
                        custom_id=call.call_id,
                        max_tokens=call.maximum_output_tokens,
                        response_format=response_format,
                        seed=0 if "seed" in call.parameters else None,
                    )
                    response = batch.response
                    batch_job_id = batch.job_id
                    retention_days = batch.compatibility.retention_days
                else:
                    response = await self.client.complete(
                        messages=[LLMMessage(role="user", content=fixture.prompt)],
                        model=call.model_id,
                        temperature=0.3 if "temperature" in call.parameters else None,
                        max_tokens=call.maximum_output_tokens,
                        response_format=response_format,
                        include_temperature="temperature" in call.parameters,
                    )
                if response.cost_usd is None:
                    actual_cost = _maximum_call_cost(
                        entry,
                        response.input_tokens,
                        response.output_tokens,
                    )
                    cost_source = "estimated"
                else:
                    actual_cost = response.cost_usd
                    cost_source = response.cost_source
                response_path = self.run_dir / "responses" / f"{call.call_id}.txt"
                _atomic_write(response_path, response.content)
                self._validate_returned_model(call.model_id, response.model, entry)
                self.ledger.reconcile(call.maximum_cost_usd, actual_cost)
                reconciled = True
                receipt = CallReceipt(
                    call_id=call.call_id,
                    status="completed",
                    requested_model=call.model_id,
                    returned_model=response.model,
                    fixture_name=fixture.repo_name,
                    prompt_sha256=fixture.prompt_sha256,
                    request_id=response.request_id,
                    finish_reason=response.finish_reason,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    reasoning_tokens=response.reasoning_tokens,
                    cached_input_tokens=response.cached_input_tokens,
                    cost_usd=actual_cost,
                    cost_source=cost_source,
                    transport="queued-job" if entry.is_batch else "chat-completions",
                    duration_seconds=time.monotonic() - started,
                    response_path=str(response_path.relative_to(self.run_dir)),
                    batch_job_id=batch_job_id,
                    retention_days=retention_days,
                )
                completed += 1
            except Exception as exc:
                if response is not None and response_path is None:
                    response_path = self.run_dir / "responses" / f"{call.call_id}.txt"
                    _atomic_write(response_path, response.content)
                if response is not None and response.cost_usd is not None:
                    actual_cost = response.cost_usd
                    cost_source = response.cost_source
                elif response is not None:
                    entry = self.catalog.require(call.model_id)
                    actual_cost = _maximum_call_cost(
                        entry,
                        response.input_tokens,
                        response.output_tokens,
                    )
                if not reconciled:
                    self.ledger.reconcile(call.maximum_cost_usd, actual_cost)
                receipt = CallReceipt(
                    call_id=call.call_id,
                    status="failed",
                    requested_model=call.model_id,
                    returned_model=response.model if response is not None else None,
                    fixture_name=fixture.repo_name,
                    prompt_sha256=fixture.prompt_sha256,
                    request_id=response.request_id if response is not None else None,
                    finish_reason=response.finish_reason if response is not None else None,
                    input_tokens=response.input_tokens if response is not None else 0,
                    output_tokens=response.output_tokens if response is not None else 0,
                    reasoning_tokens=(
                        response.reasoning_tokens if response is not None else 0
                    ),
                    cached_input_tokens=(
                        response.cached_input_tokens if response is not None else 0
                    ),
                    cost_usd=actual_cost,
                    cost_source=cost_source,
                    transport=call.transport,
                    duration_seconds=time.monotonic() - started,
                    response_path=(
                        str(response_path.relative_to(self.run_dir))
                        if response_path is not None
                        else None
                    ),
                    batch_job_id=batch_job_id,
                    retention_days=retention_days,
                    error=_redact_error(str(exc)),
                )
                failed += 1
                _atomic_write(receipt_path, receipt.model_dump_json(indent=2) + "\n")
                raise
            _atomic_write(receipt_path, receipt.model_dump_json(indent=2) + "\n")
            receipt_paths.append(str(receipt_path))

        summary = BenchmarkRunSummary(
            completed=completed,
            failed=failed,
            skipped=skipped,
            actual_cost_usd=self.ledger.actual_cost_usd,
            receipt_paths=receipt_paths,
        )
        _atomic_write(
            self.run_dir / "run-summary.json",
            summary.model_dump_json(indent=2) + "\n",
        )
        return summary
