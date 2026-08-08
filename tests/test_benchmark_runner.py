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


async def test_runner_uses_exact_models_writes_atomic_receipts_and_resumes(
    tmp_path: Path,
) -> None:
    fixtures = _fixtures()
    plan = _plan(fixtures)
    client = RecordingClient()
    runner = BenchmarkRunner(
        plan=plan,
        fixtures=fixtures,
        catalog=_catalog(),
        client=client,
        run_dir=tmp_path,
    )

    first = await runner.run_first_round()

    assert first.completed == len(plan.first_round_calls)
    assert first.failed == 0
    assert first.actual_cost_usd == pytest.approx(len(plan.first_round_calls) * 0.0001)
    assert client.models == [call.model_id for call in plan.first_round_calls]
    assert len(list((tmp_path / "receipts").glob("*.json"))) == len(plan.first_round_calls)
    assert all(not path.name.endswith(".tmp") for path in tmp_path.rglob("*"))

    resumed_client = RecordingClient()
    resumed = await BenchmarkRunner(
        plan=plan,
        fixtures=fixtures,
        catalog=_catalog(),
        client=resumed_client,
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
        run_dir=tmp_path,
    )

    with pytest.raises(ValueError, match="Returned model drift"):
        await runner.run_first_round(limit=1)


def test_budget_ledger_refuses_reservation_over_cap() -> None:
    ledger = BudgetLedger(budget_usd=0.01)
    ledger.authorize(0.006)
    ledger.reconcile(0.006, 0.004)
    with pytest.raises(ValueError, match="budget cap"):
        ledger.authorize(0.007)
