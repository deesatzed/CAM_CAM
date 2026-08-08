from __future__ import annotations

from claw.models.scoring import (
    BenchmarkQualityReport,
    CallQualityReceipt,
    ModelQualitySummary,
)
from claw.models.tournament import TournamentStagePlan, select_tournament_roles


def _plan(
    run_id: str,
    stage: str,
    candidates: list[str],
    *,
    parent: str | None = None,
    prior: float = 2.0,
) -> TournamentStagePlan:
    fixtures = (
        [
            {
                "repo_name": "Codx_LoopKit",
                "git_head": "a" * 40,
                "brain": "python",
                "prompt_sha256": "prompt-Codx_LoopKit",
                "repo_content_sha256": "content-Codx_LoopKit",
                "source_manifest": ["README.md"],
                "file_count": 1,
                "estimated_tokens": 100,
                "token_budget": 100,
                "stage": "repeat",
            }
        ]
        if stage == "repeat"
        else []
    )
    return TournamentStagePlan(
        run_id=run_id,
        created_at="2026-08-08T00:00:00+00:00",
        suite_name="mining-v1",
        stage=stage,
        authorization_usd=5.0,
        prior_spend_usd=prior,
        stage_maximum_cost_usd=0.0,
        parent_run_id=parent,
        catalog_receipt={"digest": run_id, "model_digests": {}},
        fixtures=fixtures,
        calls=[],
        selected_candidates=candidates,
    )


def _summary(
    model_id: str,
    *,
    average: float,
    floor: float,
    cost: float,
    findings: int,
    latency: float | None,
    eligible: bool = True,
) -> ModelQualitySummary:
    return ModelQualitySummary(
        model_id=model_id,
        completed_calls=2,
        average_quality=average,
        worst_quality=floor,
        total_cost_usd=cost,
        cost_per_finding_usd=cost / findings,
        average_sync_latency_seconds=latency,
        finding_count=findings,
        hard_failures=[] if eligible else ["truncated_response"],
        eligible=eligible,
    )


def _call(
    model_id: str,
    *,
    transport: str,
    fixture: str = "OpenCLI",
    quality: float = 95,
    findings: int = 5,
    cost: float = 0.01,
) -> CallQualityReceipt:
    return CallQualityReceipt(
        candidate_code=f"candidate-{model_id}",
        call_id=f"call-{model_id}",
        model_id=model_id,
        fixture_name=fixture,
        envelope="findings-wrapper",
        quality=quality,
        finding_count=findings,
        cost_usd=cost,
        duration_seconds=None if transport == "queued-job" else 2.0,
        transport=transport,
        finish_reason="stop",
    )


def test_selects_distinct_quality_budget_fast_and_batch_roles_without_promotion() -> None:
    luna = "openai/gpt-5.6-luna"
    glm = "z-ai/glm-5.2"
    gemini = "google/gemini-3.6-flash:batch"
    first = _plan("first", "first-round", [luna, glm, gemini])
    heldout = _plan(
        "heldout", "heldout", [luna, glm, gemini], parent="first", prior=2.1
    )
    repeat = _plan("repeat", "repeat", [luna, glm], parent="heldout", prior=2.2)
    reports = [
        BenchmarkQualityReport(
            run_id="first",
            expected_fixtures=3,
            actual_cost_usd=0.1,
            calls=[],
            models=[
                _summary(luna, average=94, floor=90, cost=0.02, findings=10, latency=3),
                _summary(glm, average=91, floor=89, cost=0.005, findings=10, latency=1),
                _summary(
                    gemini, average=93, floor=90, cost=0.02, findings=10, latency=None
                ),
            ],
        ),
        BenchmarkQualityReport(
            run_id="heldout",
            expected_fixtures=2,
            actual_cost_usd=0.1,
            calls=[
                _call(luna, transport="chat-completions"),
                _call(glm, transport="chat-completions"),
                _call(gemini, transport="queued-job"),
            ],
            models=[
                _summary(luna, average=97, floor=95, cost=0.04, findings=10, latency=3),
                _summary(glm, average=92, floor=90, cost=0.005, findings=10, latency=1),
                _summary(
                    gemini, average=95, floor=93, cost=0.02, findings=10, latency=None
                ),
            ],
        ),
        BenchmarkQualityReport(
            run_id="repeat",
            expected_fixtures=1,
            actual_cost_usd=0.02,
            calls=[
                _call(luna, transport="chat-completions"),
                _call(glm, transport="chat-completions"),
            ],
            models=[
                _summary(luna, average=96, floor=96, cost=0.01, findings=5, latency=3),
                _summary(glm, average=91, floor=91, cost=0.001, findings=5, latency=1),
            ],
        ),
    ]

    selection = select_tournament_roles(
        plans=[first, heldout, repeat],
        reports=reports,
        profile="legacy-import",
    )

    assert selection.roles["quality"].model_id == luna
    assert selection.roles["budget"].model_id == glm
    assert selection.roles["fast"].model_id == glm
    assert selection.roles["batch"].model_id == gemini
    assert selection.roles["quality"].promotion_command == (
        "cam models set mining-quality openai/gpt-5.6-luna --profile legacy-import"
    )
    assert selection.roles["fast"].promotion_command is None
    assert selection.tournament_spend_usd == 0.22
    assert selection.cumulative_spend_usd == 2.22
    assert selection.conservative_cumulative_maximum_usd == 2.22
    assert set(selection.catalog_receipts) == {"first-round", "heldout", "repeat"}
    assert set(selection.catalog_prices) == {"first-round", "heldout", "repeat"}


def test_repeat_failure_is_reported_and_not_selected_for_quality() -> None:
    luna = "openai/gpt-5.6-luna"
    glm = "z-ai/glm-5.2"
    first = _plan("first", "first-round", [luna, glm])
    heldout = _plan("heldout", "heldout", [luna, glm], parent="first", prior=2.1)
    repeat = _plan("repeat", "repeat", [luna, glm], parent="heldout", prior=2.2)
    reports = [
        BenchmarkQualityReport(
            run_id="first",
            expected_fixtures=3,
            actual_cost_usd=0.1,
            calls=[],
            models=[
                _summary(luna, average=98, floor=96, cost=0.02, findings=5, latency=2),
                _summary(glm, average=90, floor=88, cost=0.01, findings=5, latency=1),
            ],
        ),
        BenchmarkQualityReport(
            run_id="heldout",
            expected_fixtures=2,
            actual_cost_usd=0.1,
            calls=[],
            models=[
                _summary(luna, average=98, floor=96, cost=0.02, findings=5, latency=2),
                _summary(glm, average=90, floor=88, cost=0.01, findings=5, latency=1),
            ],
        ),
        BenchmarkQualityReport(
            run_id="repeat",
            expected_fixtures=1,
            actual_cost_usd=0.02,
            calls=[],
            models=[
                _summary(
                    luna,
                    average=0,
                    floor=0,
                    cost=0.01,
                    findings=1,
                    latency=2,
                    eligible=False,
                ),
                _summary(glm, average=90, floor=90, cost=0.01, findings=5, latency=1),
            ],
        ),
    ]

    selection = select_tournament_roles(
        plans=[first, heldout, repeat], reports=reports, profile="legacy-import"
    )

    assert selection.roles["quality"].model_id == glm
    assert selection.exclusions[luna] == ["repeat_hard_failure"]


def test_repeat_stability_compares_the_original_same_fixture_call() -> None:
    luna = "openai/gpt-5.6-luna"
    first = _plan("first", "first-round", [luna])
    heldout = _plan("heldout", "heldout", [luna], parent="first", prior=2.1)
    repeat = _plan("repeat", "repeat", [luna], parent="heldout", prior=2.2)
    reports = [
        BenchmarkQualityReport(
            run_id="first",
            expected_fixtures=3,
            actual_cost_usd=0.1,
            calls=[
                _call(
                    luna,
                    transport="chat-completions",
                    fixture="Codx_LoopKit",
                    quality=95,
                    findings=5,
                    cost=0.01,
                )
            ],
            models=[
                _summary(luna, average=90, floor=85, cost=0.02, findings=5, latency=2)
            ],
        ),
        BenchmarkQualityReport(
            run_id="heldout",
            expected_fixtures=2,
            actual_cost_usd=0.1,
            calls=[],
            models=[
                _summary(luna, average=75, floor=70, cost=0.02, findings=5, latency=2)
            ],
        ),
        BenchmarkQualityReport(
            run_id="repeat",
            expected_fixtures=1,
            actual_cost_usd=0.02,
            calls=[
                _call(
                    luna,
                    transport="chat-completions",
                    fixture="Codx_LoopKit",
                    quality=70,
                    findings=3,
                    cost=0.02,
                )
            ],
            models=[
                _summary(luna, average=70, floor=70, cost=0.02, findings=3, latency=2)
            ],
        ),
    ]

    selection = select_tournament_roles(
        plans=[first, heldout, repeat], reports=reports, profile="legacy-import"
    )

    assert selection.exclusions[luna] == ["repeat_instability"]
    assert selection.stability[luna] == {
        "fixture_name": "Codx_LoopKit",
        "quality_delta": -25.0,
        "finding_count_delta": -2,
        "cost_delta_usd": 0.01,
        "validity_match": True,
    }
