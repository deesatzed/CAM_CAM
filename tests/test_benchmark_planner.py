from __future__ import annotations

import json
from pathlib import Path

import pytest

from claw.models.benchmark import (
    BenchmarkPlanner,
    BenchmarkSuite,
    MiningPromptFixture,
)
from claw.models.catalog import ModelCatalog


def _catalog() -> ModelCatalog:
    payload_path = Path(__file__).parent / "fixtures" / "openrouter_models.json"
    return ModelCatalog.from_payload(json.loads(payload_path.read_text()))


def _fixture(name: str, stage: str, prompt_tokens: int = 12000) -> MiningPromptFixture:
    prompt = f"Mine {name}\n" + ("source context\n" * 200)
    return MiningPromptFixture(
        repo_path=f"/private/{name}",
        repo_name=name,
        git_head="a" * 40,
        dirty_paths=[],
        brain="python",
        prompt=prompt,
        prompt_sha256=f"prompt-{name}",
        repo_content="private source must not enter plan",
        repo_content_sha256=f"content-{name}",
        source_manifest=["README.md", "src/main.py"],
        repo_bytes=10000,
        file_count=2,
        estimated_tokens=prompt_tokens,
        token_budget=4096,
        domain_info={"complexity": "small"},
        overlap={},
    )


def test_plan_freezes_all_candidates_stages_and_hides_raw_prompts() -> None:
    suite = BenchmarkSuite.load(Path("benchmarks/mining-v1.toml"))
    fixtures = [
        _fixture("Codx_LoopKit", "first-round"),
        _fixture("atomic-agent", "first-round"),
        _fixture("RedaktSafe", "first-round"),
        _fixture("OpenCLI", "heldout"),
        _fixture("OpenViking", "heldout"),
    ]

    plan = BenchmarkPlanner().plan(suite, fixtures, _catalog(), budget_usd=5.0)

    assert plan.status == "planned"
    assert plan.budget_usd == 5.0
    assert plan.maximum_cost_usd <= 5.0
    assert len(plan.first_round_calls) == 8 * 3
    assert plan.stage_policy == {
        "first_round_candidates": 8,
        "first_round_fixtures": 3,
        "heldout_candidates": 4,
        "heldout_fixtures": 2,
        "repeat_candidates": 2,
        "repeat_fixtures": 1,
    }
    assert {call.model_id for call in plan.first_round_calls} == set(suite.candidates)
    assert all(call.catalog_digest for call in plan.first_round_calls)
    serialized = plan.model_dump_json()
    assert "private source must not enter plan" not in serialized
    assert "Mine Codx_LoopKit" not in serialized
    assert "prompt-Codx_LoopKit" in serialized


def test_plan_rejects_budget_that_cannot_cover_worst_case() -> None:
    suite = BenchmarkSuite.load(Path("benchmarks/mining-v1.toml"))
    fixtures = [
        _fixture("Codx_LoopKit", "first-round", prompt_tokens=500000),
        _fixture("atomic-agent", "first-round", prompt_tokens=500000),
        _fixture("RedaktSafe", "first-round", prompt_tokens=500000),
        _fixture("OpenCLI", "heldout", prompt_tokens=500000),
        _fixture("OpenViking", "heldout", prompt_tokens=500000),
    ]

    with pytest.raises(ValueError, match="exceeds budget"):
        BenchmarkPlanner().plan(suite, fixtures, _catalog(), budget_usd=0.01)


def test_plan_rejects_prompt_or_catalog_drift_and_batch_parameter_mismatch() -> None:
    suite = BenchmarkSuite.load(Path("benchmarks/mining-v1.toml"))
    fixtures = [
        _fixture("Codx_LoopKit", "first-round"),
        _fixture("atomic-agent", "first-round"),
        _fixture("RedaktSafe", "first-round"),
        _fixture("OpenCLI", "heldout"),
        _fixture("OpenViking", "heldout"),
    ]
    plan = BenchmarkPlanner().plan(suite, fixtures, _catalog(), budget_usd=5.0)

    gemini_calls = [
        call
        for call in plan.first_round_calls
        if call.model_id == "google/gemini-3.6-flash:batch"
    ]
    assert gemini_calls
    assert all("temperature" not in call.parameters for call in gemini_calls)
    assert all(call.transport == "batch-compatibility" for call in gemini_calls)
    assert plan.catalog_receipt.digest == _catalog().digest
