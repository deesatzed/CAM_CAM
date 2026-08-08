"""Deterministic provenance checks and blinded review packets for mining outputs."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field

from claw.miner import MiningFinding, parse_findings
from claw.models.benchmark import CallReceipt, MiningPromptFixture

QUALITY_WEIGHTS = {
    "grounded_correctness": 35,
    "novelty": 25,
    "actionable_specificity": 20,
    "coverage_diversity": 10,
    "structured_reliability": 10,
}

_SECRET_PATTERN = re.compile(
    r"(?:sk-(?:or-)?[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,})",
    re.IGNORECASE,
)


class CandidateScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    grounded_correctness: float
    novelty: float
    actionable_specificity: float
    coverage_diversity: float
    structured_reliability: float
    hard_failures: list[str]
    finding_count: int

    @property
    def total(self) -> float:
        return round(
            self.grounded_correctness
            + self.novelty
            + self.actionable_specificity
            + self.coverage_diversity
            + self.structured_reliability,
            2,
        )


class BlindedReviewPacket(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_code: str
    fixture_name: str
    response_text: str


class CallQualityReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_code: str
    call_id: str
    model_id: str
    fixture_name: str
    envelope: str
    quality: float
    finding_count: int
    hard_failures: list[str] = Field(default_factory=list)
    cost_usd: float
    duration_seconds: float | None
    transport: str
    finish_reason: str | None


class ModelQualitySummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str
    completed_calls: int
    average_quality: float
    total_cost_usd: float
    average_sync_latency_seconds: float | None
    finding_count: int
    hard_failures: list[str]
    eligible: bool


class BenchmarkQualityReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    expected_fixtures: int
    actual_cost_usd: float
    calls: list[CallQualityReceipt]
    models: list[ModelQualitySummary]


def _safe_source_path(repo_root: Path, relative_path: str) -> Path | None:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        return None
    candidate = (repo_root / Path(*pure.parts)).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _provenance_fraction(findings: list[MiningFinding], repo_root: Path) -> tuple[float, bool]:
    checks = 0
    valid = 0
    invalid_file_provenance = False
    for finding in findings:
        if not finding.source_files:
            checks += 1
            invalid_file_provenance = True
            continue
        for relative_path in finding.source_files:
            checks += 1
            source_path = _safe_source_path(repo_root, relative_path)
            if source_path is None:
                invalid_file_provenance = True
                continue
            valid += 1
        for symbol in finding.source_symbols:
            checks += 1
            source_path = _safe_source_path(repo_root, symbol.get("file_path", ""))
            symbol_name = symbol.get("symbol_name", "").strip()
            if source_path is None or not symbol_name:
                continue
            source_text = source_path.read_text(encoding="utf-8", errors="replace")
            qualified_parts = symbol_name.split(".")
            qualified_match = (
                len(qualified_parts) > 1
                and all(part.isidentifier() for part in qualified_parts)
                and all(
                    re.search(rf"\b{re.escape(part)}\b", source_text)
                    for part in qualified_parts
                )
            )
            if symbol_name not in source_text and not qualified_match:
                continue
            valid += 1
    return (valid / checks if checks else 0.0), invalid_file_provenance


def _actionability(findings: list[MiningFinding]) -> float:
    if not findings:
        return 0.0
    points = 0.0
    for finding in findings:
        checks = [
            bool(finding.implementation_sketch.strip()),
            bool(finding.execution_steps),
            bool(finding.acceptance_checks),
            bool(finding.rollback_steps),
            bool(finding.preconditions),
        ]
        points += sum(checks) / len(checks)
    return QUALITY_WEIGHTS["actionable_specificity"] * points / len(findings)


def score_candidate(
    response_text: str,
    fixture: MiningPromptFixture,
    existing_titles: list[str],
) -> CandidateScore:
    """Score objective mining-output properties without access to model identity."""
    hard_failures: list[str] = []
    if _SECRET_PATTERN.search(response_text):
        hard_failures.append("secret_like_output")
    findings = parse_findings(response_text, fixture.repo_name)
    if not findings:
        hard_failures.append("malformed_findings")
        return CandidateScore(
            grounded_correctness=0,
            novelty=0,
            actionable_specificity=0,
            coverage_diversity=0,
            structured_reliability=0,
            hard_failures=sorted(set(hard_failures)),
            finding_count=0,
        )

    grounded_fraction, invalid_file_provenance = _provenance_fraction(
        findings,
        Path(fixture.repo_path),
    )
    if invalid_file_provenance:
        hard_failures.append("invalid_provenance")
    grounded = QUALITY_WEIGHTS["grounded_correctness"] * grounded_fraction

    existing = {title.strip().casefold() for title in existing_titles}
    seen: set[str] = set()
    novel = 0
    for finding in findings:
        normalized = finding.title.strip().casefold()
        if normalized and normalized not in existing and normalized not in seen:
            novel += 1
        seen.add(normalized)
    novelty = QUALITY_WEIGHTS["novelty"] * novel / len(findings)
    actionability = _actionability(findings)
    categories = {finding.category for finding in findings}
    coverage = min(
        QUALITY_WEIGHTS["coverage_diversity"],
        4 + len(categories) * 2 + min(len(findings), 4),
    )
    return CandidateScore(
        grounded_correctness=round(grounded, 2),
        novelty=round(novelty, 2),
        actionable_specificity=round(actionability, 2),
        coverage_diversity=float(coverage),
        structured_reliability=float(QUALITY_WEIGHTS["structured_reliability"]),
        hard_failures=sorted(set(hard_failures)),
        finding_count=len(findings),
    )


def build_blinded_packet(
    *,
    run_id: str,
    model_id: str,
    fixture_name: str,
    response_text: str,
) -> BlindedReviewPacket:
    """Create a stable anonymous review packet; keep the identity map private."""
    digest = hashlib.sha256(f"{run_id}|{model_id}".encode()).hexdigest()[:10]
    return BlindedReviewPacket(
        candidate_code=f"candidate-{digest}",
        fixture_name=fixture_name,
        response_text=response_text,
    )


def _response_envelope(response_text: str) -> str:
    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError:
        return "repaired-or-invalid"
    if isinstance(parsed, list):
        return "strict-array"
    if isinstance(parsed, dict) and isinstance(parsed.get("findings"), list):
        return "findings-wrapper"
    if isinstance(parsed, dict) and parsed.get("title") and parsed.get("description"):
        return "single-finding"
    return "unsupported-json"


def score_benchmark_run(
    *,
    run_id: str,
    run_dir: Path,
    fixtures: list[MiningPromptFixture],
    expected_fixtures: int,
) -> BenchmarkQualityReport:
    """Score completed receipts and aggregate promotion eligibility by model."""
    fixture_by_name = {fixture.repo_name: fixture for fixture in fixtures}
    calls: list[CallQualityReceipt] = []
    for receipt_path in sorted((run_dir / "receipts").glob("*.json")):
        receipt = CallReceipt.model_validate_json(receipt_path.read_text())
        if receipt.status != "completed" or not receipt.response_path:
            continue
        fixture = fixture_by_name[receipt.fixture_name]
        response_text = (run_dir / receipt.response_path).read_text()
        score = score_candidate(response_text, fixture, existing_titles=[])
        failures = list(score.hard_failures)
        if receipt.finish_reason == "length":
            failures.append("truncated_response")
        envelope = _response_envelope(response_text)
        if envelope == "unsupported-json":
            failures.append("unsupported_json_envelope")
        calls.append(
            CallQualityReceipt(
                candidate_code=build_blinded_packet(
                    run_id=run_id,
                    model_id=receipt.requested_model,
                    fixture_name=receipt.fixture_name,
                    response_text="",
                ).candidate_code,
                call_id=receipt.call_id,
                model_id=receipt.requested_model,
                fixture_name=receipt.fixture_name,
                envelope=envelope,
                quality=score.total,
                finding_count=score.finding_count,
                hard_failures=sorted(set(failures)),
                cost_usd=receipt.cost_usd,
                duration_seconds=(
                    None if receipt.transport == "queued-job" else receipt.duration_seconds
                ),
                transport=receipt.transport,
                finish_reason=receipt.finish_reason,
            )
        )

    grouped: dict[str, list[CallQualityReceipt]] = defaultdict(list)
    for call in calls:
        grouped[call.model_id].append(call)
    models: list[ModelQualitySummary] = []
    for model_id, model_calls in sorted(grouped.items()):
        failures = sorted(
            {failure for call in model_calls for failure in call.hard_failures}
        )
        latencies = [
            call.duration_seconds
            for call in model_calls
            if call.duration_seconds is not None
        ]
        average_quality = round(
            sum(call.quality for call in model_calls) / len(model_calls),
            2,
        )
        models.append(
            ModelQualitySummary(
                model_id=model_id,
                completed_calls=len(model_calls),
                average_quality=average_quality,
                total_cost_usd=sum(call.cost_usd for call in model_calls),
                average_sync_latency_seconds=(
                    round(sum(latencies) / len(latencies), 3) if latencies else None
                ),
                finding_count=sum(call.finding_count for call in model_calls),
                hard_failures=failures,
                eligible=(
                    len(model_calls) == expected_fixtures
                    and average_quality >= 80
                    and not failures
                ),
            )
        )
    return BenchmarkQualityReport(
        run_id=run_id,
        expected_fixtures=expected_fixtures,
        actual_cost_usd=sum(call.cost_usd for call in calls),
        calls=sorted(calls, key=lambda call: (call.candidate_code, call.fixture_name)),
        models=models,
    )
