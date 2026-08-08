from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from claw.models.benchmark import BenchmarkSuite, MiningPromptFixture
from claw.models.catalog import ModelCatalog
from claw.models.scoring import BenchmarkQualityReport, ModelQualitySummary
from claw.models.tournament import (
    TournamentPlanner,
    TournamentStagePlan,
    rank_eligible_models,
)


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
    assert set(plan.catalog_prices) == set(suite.candidates)
    assert plan.catalog_prices["openai/gpt-5.6-luna"].completion_per_million > 0
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


def _model_summary(
    model_id: str,
    *,
    floor: float,
    average: float,
    cost: float,
    findings: int,
    latency: float | None = 2.0,
    eligible: bool = True,
) -> ModelQualitySummary:
    return ModelQualitySummary(
        model_id=model_id,
        completed_calls=3,
        average_quality=average,
        worst_quality=floor,
        total_cost_usd=cost,
        cost_per_finding_usd=cost / findings if findings else None,
        average_sync_latency_seconds=latency,
        finding_count=findings,
        hard_failures=[] if eligible else ["truncated_response"],
        eligible=eligible,
    )


def test_ranking_prefers_quality_floor_then_average_then_cost_per_finding() -> None:
    summaries = [
        _model_summary(
            "qwen/qwen3.8-max", floor=90, average=95, cost=0.3, findings=6
        ),
        _model_summary(
            "openai/gpt-5.6-luna", floor=92, average=93, cost=0.2, findings=5
        ),
        _model_summary(
            "z-ai/glm-5.2", floor=90, average=95, cost=0.1, findings=10
        ),
        _model_summary(
            "moonshotai/kimi-k3",
            floor=99,
            average=99,
            cost=0.5,
            findings=8,
            eligible=False,
        ),
    ]

    ranked = rank_eligible_models(summaries)

    assert [item.model_id for item in ranked] == [
        "openai/gpt-5.6-luna",
        "z-ai/glm-5.2",
        "qwen/qwen3.8-max",
    ]


def test_heldout_advance_uses_eligible_rank_and_actual_parent_spend() -> None:
    suite = BenchmarkSuite.load(Path("benchmarks/mining-v1.toml"))
    parent = TournamentPlanner().plan_first_round(
        suite,
        _fixtures(),
        _catalog(),
        authorization_usd=5.0,
        prior_spend_usd=2.0,
    )
    models = [
        _model_summary(
            "openai/gpt-5.6-luna", floor=92, average=93, cost=0.02, findings=5
        ),
        _model_summary(
            "z-ai/glm-5.2", floor=90, average=95, cost=0.01, findings=10
        ),
        _model_summary(
            "qwen/qwen3.8-max", floor=88, average=94, cost=0.03, findings=8
        ),
        _model_summary(
            "moonshotai/kimi-k3",
            floor=99,
            average=99,
            cost=0.04,
            findings=8,
            eligible=False,
        ),
    ]
    report = BenchmarkQualityReport(
        run_id=parent.run_id,
        expected_fixtures=3,
        actual_cost_usd=0.1,
        calls=[],
        models=models,
    )

    heldout = TournamentPlanner().plan_advance(
        parent=parent,
        report=report,
        suite=suite,
        fixtures=_fixtures(),
        catalog=_catalog(),
        next_stage="heldout",
    )

    assert heldout.stage == "heldout"
    assert heldout.parent_run_id == parent.run_id
    assert heldout.prior_spend_usd == pytest.approx(2.1)
    assert heldout.selected_candidates == [
        "openai/gpt-5.6-luna",
        "z-ai/glm-5.2",
        "qwen/qwen3.8-max",
    ]
    assert len(heldout.calls) == 3 * 2
    assert {call.fixture_name for call in heldout.calls} == {"OpenCLI", "OpenViking"}
    assert heldout.excluded_candidates["moonshotai/kimi-k3"] == [
        "truncated_response"
    ]


def test_advance_never_ranks_an_eligible_flag_with_missing_calls() -> None:
    suite = BenchmarkSuite.load(Path("benchmarks/mining-v1.toml"))
    parent = TournamentPlanner().plan_first_round(
        suite,
        _fixtures(),
        _catalog(),
        authorization_usd=5.0,
        prior_spend_usd=2.0,
    )
    valid = _model_summary(
        "openai/gpt-5.6-luna", floor=90, average=92, cost=0.02, findings=5
    )
    contradictory = _model_summary(
        "moonshotai/kimi-k3", floor=100, average=100, cost=0.01, findings=5
    ).model_copy(update={"completed_calls": 2, "eligible": True})
    report = BenchmarkQualityReport(
        run_id=parent.run_id,
        expected_fixtures=3,
        actual_cost_usd=0.1,
        calls=[],
        models=[valid, contradictory],
    )

    heldout = TournamentPlanner().plan_advance(
        parent=parent,
        report=report,
        suite=suite,
        fixtures=_fixtures(),
        catalog=_catalog(),
        next_stage="heldout",
    )

    assert heldout.selected_candidates == ["openai/gpt-5.6-luna"]
    assert heldout.excluded_candidates["moonshotai/kimi-k3"] == [
        "missing_expected_calls"
    ]


def test_repeat_advance_reuses_original_first_round_request_controls() -> None:
    suite = BenchmarkSuite.load(Path("benchmarks/mining-v1.toml"))
    fixtures = _fixtures()
    catalog = _catalog()
    first = TournamentPlanner().plan_first_round(
        suite,
        fixtures,
        catalog,
        authorization_usd=5.0,
        prior_spend_usd=2.0,
    )
    finalists = [
        _model_summary(
            "openai/gpt-5.6-luna", floor=92, average=94, cost=0.02, findings=8
        ),
        _model_summary(
            "z-ai/glm-5.2", floor=90, average=93, cost=0.01, findings=8
        ),
    ]
    first_report = BenchmarkQualityReport(
        run_id=first.run_id,
        expected_fixtures=3,
        actual_cost_usd=0.1,
        calls=[],
        models=finalists,
    )
    heldout = TournamentPlanner().plan_advance(
        parent=first,
        report=first_report,
        suite=suite,
        fixtures=fixtures,
        catalog=catalog,
        next_stage="heldout",
    )
    heldout_report = BenchmarkQualityReport(
        run_id=heldout.run_id,
        expected_fixtures=2,
        actual_cost_usd=0.1,
        calls=[],
        models=[
            summary.model_copy(update={"completed_calls": 2}) for summary in finalists
        ],
    )

    repeat = TournamentPlanner().plan_advance(
        parent=heldout,
        root=first,
        report=heldout_report,
        suite=suite,
        fixtures=fixtures,
        catalog=catalog,
        next_stage="repeat",
    )

    assert repeat.stage == "repeat"
    assert {call.fixture_name for call in repeat.calls} == {"Codx_LoopKit"}
    originals = {
        (call.model_id, call.fixture_name): call for call in first.calls
    }
    for repeated in repeat.calls:
        original = originals[(repeated.model_id, repeated.fixture_name)]
        assert repeated.call_id != original.call_id
        assert repeated.stage == "repeat"
        assert repeated.prompt_sha256 == original.prompt_sha256
        assert repeated.repo_content_sha256 == original.repo_content_sha256
        assert repeated.catalog_digest == original.catalog_digest
        assert repeated.maximum_input_tokens == original.maximum_input_tokens
        assert repeated.maximum_output_tokens == original.maximum_output_tokens
        assert repeated.maximum_cost_usd == original.maximum_cost_usd
        assert repeated.parameters == original.parameters
        assert repeated.reasoning_effort == original.reasoning_effort
        assert repeated.transport == original.transport
