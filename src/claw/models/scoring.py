"""Deterministic provenance checks and blinded review packets for mining outputs."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict

from claw.miner import MiningFinding, parse_findings
from claw.models.benchmark import MiningPromptFixture

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
    invalid = False
    for finding in findings:
        if not finding.source_files:
            checks += 1
            invalid = True
            continue
        for relative_path in finding.source_files:
            checks += 1
            source_path = _safe_source_path(repo_root, relative_path)
            if source_path is None:
                invalid = True
                continue
            valid += 1
        for symbol in finding.source_symbols:
            checks += 1
            source_path = _safe_source_path(repo_root, symbol.get("file_path", ""))
            symbol_name = symbol.get("symbol_name", "").strip()
            if source_path is None or not symbol_name:
                invalid = True
                continue
            if symbol_name not in source_path.read_text(encoding="utf-8", errors="replace"):
                invalid = True
                continue
            valid += 1
    return (valid / checks if checks else 0.0), invalid


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

    grounded_fraction, invalid_provenance = _provenance_fraction(
        findings,
        Path(fixture.repo_path),
    )
    if invalid_provenance:
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
