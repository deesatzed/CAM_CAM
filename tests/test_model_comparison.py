from __future__ import annotations

from claw.models.comparison import compare_to_baseline
from claw.models.scoring import BenchmarkQualityReport, ModelQualitySummary


BASELINE = "z-ai/glm-5.2"
CANDIDATE = "openai/gpt-5.6-luna"


def _summary(model_id: str, *, quality: float, eligible: bool = True) -> ModelQualitySummary:
    return ModelQualitySummary(
        model_id=model_id, completed_calls=1, average_quality=quality,
        worst_quality=quality, total_cost_usd=0.02, cost_per_finding_usd=0.004,
        average_sync_latency_seconds=1.0, finding_count=5,
        hard_failures=[] if eligible else ["truncated_response"], eligible=eligible,
    )


def _reports(*, candidate_eligible: bool = True) -> dict[str, BenchmarkQualityReport]:
    return {
        stage: BenchmarkQualityReport(
            run_id=stage, expected_fixtures=1, actual_cost_usd=0.04, calls=[],
            models=[_summary(BASELINE, quality=80), _summary(CANDIDATE, quality=90, eligible=candidate_eligible)],
        )
        for stage in ("first-round", "heldout", "repeat")
    }


def test_candidate_is_better_only_after_all_eligibility_gates() -> None:
    verdict = compare_to_baseline(
        baseline_model=BASELINE, candidate_model=CANDIDATE, reports=_reports(),
    )

    assert verdict.status == "better"
    assert verdict.stage_evidence == ("first-round", "heldout", "repeat")


def test_candidate_with_hard_failure_is_rejected() -> None:
    verdict = compare_to_baseline(
        baseline_model=BASELINE, candidate_model=CANDIDATE,
        reports=_reports(candidate_eligible=False),
    )

    assert verdict.status == "rejected"
    assert "truncated_response" in verdict.reasons


def test_missing_repeat_evidence_is_inconclusive() -> None:
    reports = _reports()
    del reports["repeat"]

    verdict = compare_to_baseline(
        baseline_model=BASELINE, candidate_model=CANDIDATE, reports=reports,
    )

    assert verdict.status == "inconclusive"
    assert verdict.reasons == ("missing report for repeat",)
