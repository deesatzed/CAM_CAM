"""Evidence-only comparison of a model candidate with a fixed CAM baseline."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from claw.models.scoring import BenchmarkQualityReport, ModelQualitySummary


_REQUIRED_STAGES = ("first-round", "heldout", "repeat")


class BaselineComparison(BaseModel):
    """A non-promoting conclusion from completed CAM benchmark evidence."""

    model_config = ConfigDict(frozen=True)

    baseline_model: str
    candidate_model: str
    status: Literal["better", "not_better", "rejected", "inconclusive"]
    reasons: tuple[str, ...]
    stage_evidence: tuple[str, ...]


def _summary(report: BenchmarkQualityReport, model_id: str) -> ModelQualitySummary | None:
    return next((model for model in report.models if model.model_id == model_id), None)


def _rank(summary: ModelQualitySummary) -> tuple[float, float, float, float]:
    return (
        summary.worst_quality,
        summary.average_quality,
        -(summary.cost_per_finding_usd if summary.cost_per_finding_usd is not None else float("inf")),
        -summary.total_cost_usd,
    )


def compare_to_baseline(
    *,
    baseline_model: str,
    candidate_model: str,
    reports: dict[str, BenchmarkQualityReport],
) -> BaselineComparison:
    """Compare only complete, eligible evidence; never produce a promotion action."""
    evidence: list[str] = []
    missing: list[str] = []
    candidate_failures: set[str] = set()
    for stage in _REQUIRED_STAGES:
        report = reports.get(stage)
        if report is None:
            missing.append(f"missing report for {stage}")
            continue
        baseline = _summary(report, baseline_model)
        candidate = _summary(report, candidate_model)
        if baseline is None or candidate is None:
            missing.append(f"missing model evidence for {stage}")
            continue
        if baseline.completed_calls <= 0 or candidate.completed_calls <= 0:
            missing.append(f"incomplete model evidence for {stage}")
            continue
        evidence.append(stage)
        candidate_failures.update(candidate.hard_failures)
        if not candidate.eligible and not candidate.hard_failures:
            missing.append(f"candidate is ineligible for {stage}")
        if not baseline.eligible:
            missing.append(f"baseline is ineligible for {stage}")

    if candidate_failures:
        return BaselineComparison(
            baseline_model=baseline_model, candidate_model=candidate_model,
            status="rejected", reasons=tuple(sorted(candidate_failures)),
            stage_evidence=tuple(evidence),
        )
    if missing:
        return BaselineComparison(
            baseline_model=baseline_model, candidate_model=candidate_model,
            status="inconclusive", reasons=tuple(missing), stage_evidence=tuple(evidence),
        )

    heldout = reports["heldout"]
    baseline = _summary(heldout, baseline_model)
    candidate = _summary(heldout, candidate_model)
    assert baseline is not None and candidate is not None
    better = _rank(candidate) > _rank(baseline)
    return BaselineComparison(
        baseline_model=baseline_model, candidate_model=candidate_model,
        status="better" if better else "not_better",
        reasons=(
            "candidate outranks baseline on held-out quality floor, average quality, and cost tie-breakers"
            if better
            else "candidate does not outrank baseline on held-out evidence"
        ,),
        stage_evidence=tuple(evidence),
    )
