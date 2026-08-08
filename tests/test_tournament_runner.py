from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from claw.llm.client import LLMResponse
from claw.models.benchmark import BenchmarkRunner, MiningPromptFixture
from claw.models.catalog import ModelCatalog
from claw.models.tournament import TournamentPlanner, TournamentStagePlan


def _catalog() -> ModelCatalog:
    path = Path(__file__).parent / "fixtures" / "openrouter_models.json"
    return ModelCatalog.from_payload(json.loads(path.read_text()))


def _fixture() -> MiningPromptFixture:
    prompt = "mine heldout"
    content = "def heldout():\n    return True\n"
    return MiningPromptFixture(
        repo_path="/repo/OpenCLI",
        repo_name="OpenCLI",
        git_head="a" * 40,
        dirty_paths=[],
        brain="python",
        prompt=prompt,
        prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
        repo_content=content,
        repo_content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        source_manifest=["main.py"],
        repo_bytes=len(content),
        file_count=1,
        estimated_tokens=100,
        token_budget=100,
        domain_info={},
        overlap={},
    )


def _plan() -> TournamentStagePlan:
    catalog = _catalog()
    fixture = _fixture()
    candidate = "openai/gpt-5.6-luna"
    calls = TournamentPlanner()._freeze_calls(
        stage="heldout",
        candidates=[candidate],
        fixtures=[fixture],
        catalog=catalog,
    )
    return TournamentStagePlan(
        run_id="heldout-run",
        created_at="2026-08-08T00:00:00+00:00",
        suite_name="mining-v1",
        stage="heldout",
        authorization_usd=5.0,
        prior_spend_usd=4.9,
        stage_maximum_cost_usd=sum(call.maximum_cost_usd for call in calls),
        parent_run_id="first-run",
        catalog_receipt={
            "digest": catalog.digest,
            "model_digests": {candidate: catalog.require(candidate).catalog_digest},
        },
        fixtures=[
            {
                "repo_name": fixture.repo_name,
                "git_head": fixture.git_head,
                "brain": fixture.brain,
                "prompt_sha256": fixture.prompt_sha256,
                "repo_content_sha256": fixture.repo_content_sha256,
                "source_manifest": fixture.source_manifest,
                "file_count": fixture.file_count,
                "estimated_tokens": fixture.estimated_tokens,
                "token_budget": fixture.token_budget,
                "stage": "heldout",
            }
        ],
        calls=calls,
        selected_candidates=[candidate],
    )


class RecordingClient:
    def __init__(self) -> None:
        self.models: list[str] = []

    async def complete(self, messages, model, **kwargs) -> LLMResponse:
        self.models.append(model)
        return LLMResponse(
            content="[]",
            model=model,
            input_tokens=100,
            output_tokens=20,
            cost_usd=0.0001,
            cost_source="provider",
            request_id=f"req-{len(self.models)}",
            finish_reason="stop",
        )


async def test_runner_executes_and_resumes_an_arbitrary_tournament_stage(
    tmp_path: Path,
) -> None:
    plan = _plan()
    client = RecordingClient()
    runner = BenchmarkRunner(
        plan=plan,
        fixtures=[_fixture()],
        catalog=_catalog(),
        client=client,
        run_dir=tmp_path,
    )

    first = await runner.run_calls(plan.calls)

    assert first.completed == 1
    assert first.actual_cost_usd == pytest.approx(0.0001)
    assert runner.ledger.budget_usd == pytest.approx(0.1)
    assert client.models == ["openai/gpt-5.6-luna"]

    resumed_client = RecordingClient()
    resumed_runner = BenchmarkRunner(
        plan=plan,
        fixtures=[_fixture()],
        catalog=_catalog(),
        client=resumed_client,
        run_dir=tmp_path,
    )
    resumed = await resumed_runner.run_calls(plan.calls)
    repeated = await resumed_runner.run_calls(plan.calls)

    assert resumed.skipped == 1
    assert resumed.actual_cost_usd == pytest.approx(0.0001)
    assert repeated.actual_cost_usd == pytest.approx(0.0001)
    assert resumed_client.models == []


def test_runner_rejects_full_catalog_digest_drift_before_calls(tmp_path: Path) -> None:
    plan = _plan()
    catalog = _catalog().model_copy(update={"digest": "tampered"})

    with pytest.raises(ValueError, match="catalog digest mismatch"):
        BenchmarkRunner(
            plan=plan,
            fixtures=[_fixture()],
            catalog=catalog,
            client=RecordingClient(),
            run_dir=tmp_path,
        )


def test_runner_applies_a_lower_runtime_authorization_cap(tmp_path: Path) -> None:
    plan = _plan()

    runner = BenchmarkRunner(
        plan=plan,
        fixtures=[_fixture()],
        catalog=_catalog(),
        client=RecordingClient(),
        run_dir=tmp_path,
        budget_usd=4.95,
    )

    assert runner.ledger.budget_usd == pytest.approx(0.05)
