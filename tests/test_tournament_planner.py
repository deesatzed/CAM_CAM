from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from claw.models.benchmark import BenchmarkSuite, MiningPromptFixture
from claw.models.catalog import ModelCatalog
from claw.models.tournament import TournamentPlanner, TournamentStagePlan


def _catalog() -> ModelCatalog:
    payload_path = Path(__file__).parent / "fixtures" / "openrouter_models.json"
    return ModelCatalog.from_payload(json.loads(payload_path.read_text()))


def _fixtures(*, prompt_tokens: int = 12_000) -> list[MiningPromptFixture]:
    names = ["Codx_LoopKit", "atomic-agent", "RedaktSafe", "OpenCLI", "OpenViking"]
    fixtures: list[MiningPromptFixture] = []
    for name in names:
        fixtures.append(
            MiningPromptFixture(
                repo_path=f"/private/{name}",
                repo_name=name,
                git_head="a" * 40,
                dirty_paths=[],
                brain="python",
                prompt=f"private prompt for {name}",
                prompt_sha256=f"prompt-{name}",
                repo_content=f"private source for {name}",
                repo_content_sha256=f"content-{name}",
                source_manifest=["README.md", "src/main.py"],
                repo_bytes=10_000,
                file_count=2,
                estimated_tokens=prompt_tokens,
                token_budget=4096,
                domain_info={"complexity": "small"},
                overlap={},
            )
        )
    return fixtures


def test_first_round_plan_prices_only_executable_calls_and_prior_spend() -> None:
    suite = BenchmarkSuite.load(Path("benchmarks/mining-v1.toml"))

    plan = TournamentPlanner().plan_first_round(
        suite,
        _fixtures(),
        _catalog(),
        authorization_usd=5.0,
        prior_spend_usd=2.0348919774,
    )

    assert plan.stage == "first-round"
    assert plan.parent_run_id is None
    assert len(plan.calls) == 8 * 3
    assert plan.selected_candidates == suite.candidates
    assert plan.stage_maximum_cost_usd == pytest.approx(
        sum(call.maximum_cost_usd for call in plan.calls)
    )
    assert plan.cumulative_maximum_cost_usd == pytest.approx(
        plan.prior_spend_usd + plan.stage_maximum_cost_usd
    )
    assert plan.remaining_after_maximum_usd == pytest.approx(
        plan.authorization_usd - plan.cumulative_maximum_cost_usd
    )
    assert plan.cumulative_maximum_cost_usd <= 5.0
    assert {call.stage for call in plan.calls} == {"first-round"}
    serialized = plan.model_dump_json()
    assert "private source" not in serialized
    assert "private prompt" not in serialized


def test_stage_plan_rejects_a_call_from_another_stage() -> None:
    suite = BenchmarkSuite.load(Path("benchmarks/mining-v1.toml"))
    plan = TournamentPlanner().plan_first_round(
        suite,
        _fixtures(),
        _catalog(),
        authorization_usd=5.0,
        prior_spend_usd=2.0,
    )
    mismatched = plan.calls[0].model_copy(update={"stage": "heldout"})

    with pytest.raises(ValidationError, match="Call stages must match"):
        TournamentStagePlan.model_validate(
            plan.model_dump(mode="python") | {"calls": [mismatched, *plan.calls[1:]]}
        )


def test_stage_plan_rejects_duplicate_candidates() -> None:
    suite = BenchmarkSuite.load(Path("benchmarks/mining-v1.toml"))
    plan = TournamentPlanner().plan_first_round(
        suite,
        _fixtures(),
        _catalog(),
        authorization_usd=5.0,
        prior_spend_usd=2.0,
    )

    with pytest.raises(ValidationError, match="candidates must be unique"):
        TournamentStagePlan.model_validate(
            plan.model_dump(mode="python")
            | {"selected_candidates": [*plan.selected_candidates, plan.selected_candidates[0]]}
        )


def test_first_round_plan_rejects_insufficient_remaining_authorization() -> None:
    suite = BenchmarkSuite.load(Path("benchmarks/mining-v1.toml"))

    with pytest.raises(ValueError, match="exceeds authorization"):
        TournamentPlanner().plan_first_round(
            suite,
            _fixtures(prompt_tokens=500_000),
            _catalog(),
            authorization_usd=5.0,
            prior_spend_usd=4.99,
        )
