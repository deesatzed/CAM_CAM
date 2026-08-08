from __future__ import annotations

import json
from pathlib import Path

import pytest

from claw.llm.client import LLMResponse
from claw.models.benchmark import (
    BenchmarkPlan,
    BenchmarkPlanner,
    BenchmarkRunner,
    BenchmarkSuite,
    BudgetLedger,
    MiningPromptFixture,
)
from claw.models.catalog import ModelCatalog


def _catalog() -> ModelCatalog:
    path = Path(__file__).parent / "fixtures" / "openrouter_models.json"
    return ModelCatalog.from_payload(json.loads(path.read_text()))


def _fixtures() -> list[MiningPromptFixture]:
    names = ["Codx_LoopKit", "atomic-agent", "RedaktSafe", "OpenCLI", "OpenViking"]
    fixtures = []
    for name in names:
        prompt = f"mine {name}"
        fixtures.append(
            MiningPromptFixture(
                repo_path=f"/repo/{name}",
                repo_name=name,
                git_head="a" * 40,
                dirty_paths=[],
                brain="python",
                prompt=prompt,
                prompt_sha256=__import__("hashlib").sha256(prompt.encode()).hexdigest(),
                repo_content=f"content {name}",
                repo_content_sha256=__import__("hashlib").sha256(
                    f"content {name}".encode()
                ).hexdigest(),
                source_manifest=["README.md", "main.py"],
                repo_bytes=2000,
                file_count=2,
                estimated_tokens=100,
                token_budget=100,
                domain_info={"complexity": "small"},
                overlap={},
            )
        )
    return fixtures


def _plan(fixtures: list[MiningPromptFixture]) -> BenchmarkPlan:
    suite = BenchmarkSuite.load(Path("benchmarks/mining-v1.toml"))
    return BenchmarkPlanner().plan(suite, fixtures, _catalog(), budget_usd=5.0)


class RecordingClient:
    def __init__(self, returned_model: str | None = None) -> None:
        self.models: list[str] = []
        self.returned_model = returned_model

    async def complete(
        self,
        messages,
        model,
        temperature,
        max_tokens,
        response_format=None,
        seed=None,
        include_temperature=True,
    ):
        self.models.append(model)
        return LLMResponse(
            content="[]",
            model=self.returned_model or model,
            tokens_used=120,
            input_tokens=100,
            output_tokens=20,
            reasoning_tokens=5,
            cost_usd=0.0001,
            cost_source="provider",
            request_id=f"req-{len(self.models)}",
            finish_reason="stop",
        )


class RecordingBatchClient:
    def __init__(self, returned_model: str | None = None) -> None:
        self.models: list[str] = []
        self.returned_model = returned_model

    async def complete(
        self,
        *,
        messages,
        requested_model,
        custom_id,
        max_tokens,
        response_format=None,
        seed=None,
    ):
        from claw.models.batch import BatchCompatibilityReceipt, BatchCompletion

        self.models.append(requested_model)
        return BatchCompletion(
            response=LLMResponse(
                content="[]",
                model=self.returned_model or requested_model.removesuffix(":batch"),
                input_tokens=100,
                output_tokens=20,
                cost_usd=0.0001,
                cost_source="provider",
                request_id=f"batch-gen-{len(self.models)}",
                finish_reason="stop",
            ),
            job_id=f"batch-job-{len(self.models)}",
            compatibility=BatchCompatibilityReceipt(
                model_id=requested_model,
                status="completed",
                transport="queued-job",
                job_id=f"batch-job-{len(self.models)}",
                retention_days=30,
            ),
        )


async def test_runner_uses_exact_models_writes_atomic_receipts_and_resumes(
    tmp_path: Path,
) -> None:
    fixtures = _fixtures()
    plan = _plan(fixtures)
    client = RecordingClient()
    batch_client = RecordingBatchClient()
    runner = BenchmarkRunner(
        plan=plan,
        fixtures=fixtures,
        catalog=_catalog(),
        client=client,
        batch_client=batch_client,
        run_dir=tmp_path,
    )

    first = await runner.run_first_round()

    assert first.completed == len(plan.first_round_calls)
    assert first.failed == 0
    assert first.actual_cost_usd == pytest.approx(len(plan.first_round_calls) * 0.0001)
    assert batch_client.models == [
        call.model_id
        for call in plan.first_round_calls
        if call.transport == "batch-compatibility"
    ]
    assert client.models == [
        call.model_id
        for call in plan.first_round_calls
        if call.transport != "batch-compatibility"
    ]
    assert len(list((tmp_path / "receipts").glob("*.json"))) == len(plan.first_round_calls)
    assert all(not path.name.endswith(".tmp") for path in tmp_path.rglob("*"))

    resumed_client = RecordingClient()
    resumed = await BenchmarkRunner(
        plan=plan,
        fixtures=fixtures,
        catalog=_catalog(),
        client=resumed_client,
        batch_client=RecordingBatchClient(),
        run_dir=tmp_path,
    ).run_first_round()
    assert resumed.skipped == len(plan.first_round_calls)
    assert resumed_client.models == []


async def test_runner_aborts_on_returned_model_drift(tmp_path: Path) -> None:
    fixtures = _fixtures()
    plan = _plan(fixtures)
    runner = BenchmarkRunner(
        plan=plan,
        fixtures=fixtures,
        catalog=_catalog(),
        client=RecordingClient(returned_model="unexpected/provider-model"),
        batch_client=RecordingBatchClient(returned_model="unexpected/provider-model"),
        run_dir=tmp_path,
    )

    with pytest.raises(ValueError, match="Returned model drift"):
        await runner.run_first_round(limit=1)
    failed = json.loads(next((tmp_path / "receipts").glob("*.json")).read_text())
    assert failed["cost_usd"] == pytest.approx(0.0001)
    assert failed["returned_model"] == "unexpected/provider-model"
    assert (tmp_path / failed["response_path"]).is_file()


async def test_runner_can_resume_a_selected_model_lane(tmp_path: Path) -> None:
    fixtures = _fixtures()
    plan = _plan(fixtures)
    client = RecordingClient()
    selected = "openai/gpt-5.6-luna"

    summary = await BenchmarkRunner(
        plan=plan,
        fixtures=fixtures,
        catalog=_catalog(),
        client=client,
        batch_client=RecordingBatchClient(),
        run_dir=tmp_path,
    ).run_first_round(models={selected})

    assert summary.completed == 3
    assert client.models == [selected, selected, selected]


def test_budget_ledger_refuses_reservation_over_cap() -> None:
    ledger = BudgetLedger(budget_usd=0.01)
    ledger.authorize(0.006)
    ledger.reconcile(0.006, 0.004)
    with pytest.raises(ValueError, match="budget cap"):
        ledger.authorize(0.007)


def test_returned_model_validation_accepts_only_same_family_rolling_alias() -> None:
    catalog = _catalog()
    requested = "~deepseek/deepseek-v4-flash-latest"
    entry = catalog.require(requested)

    BenchmarkRunner._validate_returned_model(
        requested,
        "deepseek/deepseek-v4-flash-0731",
        entry,
    )
    with pytest.raises(ValueError, match="Returned model drift"):
        BenchmarkRunner._validate_returned_model(
            requested,
            "other/deepseek-v4-flash-0731",
            entry,
        )
    with pytest.raises(ValueError, match="Returned model drift"):
        BenchmarkRunner._validate_returned_model(
            requested,
            "deepseek/unrelated-0731",
            entry,
        )
