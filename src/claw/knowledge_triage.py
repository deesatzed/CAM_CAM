"""Knowledge Triage Scoring -- 7-dimensional quality gate for methodology ingest.

Implements the storage policy: store a segment only when at least one condition is true:
- 100% accuracy is required
- It encodes a novel concept, method, invariant, failure model, or decision rule
- It is hard to reproduce from generic model priors
- It creates new capability when retrieved
- It should constrain or redirect an agent in a scenario
- It is a high-value bridge between domains

Do NOT store:
- obvious boilerplate, common CRUD, easily regenerated setup, low-risk prose,
  generic best practices unless tied to specific local invariant
"""

from __future__ import annotations

import enum
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from claw.core.models import Methodology

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Triage dimensions
# ---------------------------------------------------------------------------


class TriageDimension(str, enum.Enum):
    """The 7 scoring dimensions for methodology ingest triage."""

    ACCURACY_CRITICALITY = "accuracy_criticality"
    """How critical is getting this exactly right -- security, invariant, safety."""

    NOVELTY = "novelty"
    """How different from common patterns and generic model priors."""

    METHODOLOGY_DENSITY = "methodology_density"
    """Richness of actionable method content (code, steps, algorithms)."""

    EMERGENCE_LEVERAGE = "emergence_leverage"
    """Potential for emergent capabilities when combined with other knowledge."""

    CONTEXT_SOVEREIGNTY = "context_sovereignty"
    """Degree to which local context overrides what a model would assume."""

    COMPLEXITY = "complexity"
    """Structural/algorithmic complexity of the methodology."""

    REPRODUCIBILITY = "reproducibility"
    """How easily reproduced from scratch (NEGATIVE weight -- high = easy = bad)."""


# ---------------------------------------------------------------------------
# Keyword sets used across dimension scorers
# ---------------------------------------------------------------------------

_ACCURACY_KEYWORDS: set[str] = {
    "security", "invariant", "must-not", "must not", "correctness", "safety",
    "constraint", "boundary", "race-condition", "race condition", "deadlock",
    "authentication", "authorization", "cryptograph", "encrypt", "decrypt",
    "atomic", "idempotent", "transaction", "integrity", "mutex", "lock",
    "permission", "privilege", "injection", "sanitiz", "validat", "overflow",
    "underflow", "bounds check", "assert", "precondition", "postcondition",
    "critical section", "thread-safe", "thread safe", "concurren",
}

_NOVELTY_KEYWORDS: set[str] = {
    "novel", "emergent", "unconventional", "first", "pioneer", "breakthrough",
    "unique", "original", "inventive", "unprecedented", "non-obvious",
    "counter-intuitive", "surprising", "unexpected", "exotic", "bespoke",
    "domain-specific heuristic", "custom algorithm",
}

_BOILERPLATE_KEYWORDS: set[str] = {
    "hello world", "helloworld", "todo app", "crud", "boilerplate",
    "getting started", "quick start", "quickstart", "tutorial",
    "basic setup", "default config", "standard template",
    "create-react-app", "npm init", "pip install", "import os",
    "print(", "console.log", "lorem ipsum",
}

_CONTEXT_MARKERS: set[str] = {
    "/", ".py", ".ts", ".js", ".go", ".rs", ".java", ".toml", ".yaml",
    ".json", ".env", "config", "settings", "repo-specific", "project-specific",
    "our codebase", "this repo", "this project", "internal api",
    "local convention", "house rule", "team standard", "org policy",
    "monorepo", "workspace", "package.json", "pyproject.toml",
    "claw.toml", "Makefile", "Dockerfile", "docker-compose",
}

_COMPLEXITY_INDICATORS: set[str] = {
    "recursion", "recursive", "dynamic programming", "memoiz",
    "backtrack", "graph traversal", "bfs", "dfs", "topological sort",
    "binary search", "divide and conquer", "state machine",
    "finite automaton", "parser", "lexer", "ast", "visitor pattern",
    "coroutine", "generator", "async", "await", "callback",
    "middleware chain", "pipeline", "orchestrat", "saga",
    "consensus", "raft", "paxos", "crdt", "eventual consisten",
    "retry", "circuit breaker", "backoff", "rate limit",
    "tree", "trie", "heap", "priority queue", "bloom filter",
    "hash map", "linked list", "balanced tree", "b-tree",
}


# ---------------------------------------------------------------------------
# Triage result
# ---------------------------------------------------------------------------


@dataclass
class TriageResult:
    """Outcome of 7-dimensional triage scoring for a single methodology."""

    composite_score: float
    dimension_scores: dict[str, float]
    accept: bool
    reject_reason: Optional[str] = None
    concept_type: Optional[str] = None
    methodology_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Dimension weights
# ---------------------------------------------------------------------------

_DIMENSION_WEIGHTS: dict[TriageDimension, float] = {
    TriageDimension.ACCURACY_CRITICALITY: 0.20,
    TriageDimension.NOVELTY: 0.20,
    TriageDimension.METHODOLOGY_DENSITY: 0.15,
    TriageDimension.EMERGENCE_LEVERAGE: 0.15,
    TriageDimension.CONTEXT_SOVEREIGNTY: 0.15,
    TriageDimension.COMPLEXITY: 0.05,
    TriageDimension.REPRODUCIBILITY: -0.30,
}

_ACCEPT_THRESHOLD: float = 0.25


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _combine_text(methodology: Methodology) -> str:
    """Combine all textual fields into a single searchable blob."""
    parts: list[str] = []
    if methodology.problem_description:
        parts.append(methodology.problem_description)
    if methodology.solution_code:
        parts.append(methodology.solution_code)
    if methodology.methodology_notes:
        parts.append(methodology.methodology_notes)
    if methodology.tags:
        parts.append(" ".join(methodology.tags))
    return "\n".join(parts)


def _keyword_hit_ratio(text: str, keywords: set[str]) -> float:
    """Return fraction of keyword set found in text (case-insensitive).

    Uses substring matching so partial stems like 'cryptograph' match
    'cryptography' and 'cryptographic'.
    """
    if not text:
        return 0.0
    text_lower = text.lower()
    hits = sum(1 for kw in keywords if kw.lower() in text_lower)
    return hits / max(len(keywords), 1)


def _keyword_hit_count(text: str, keywords: set[str]) -> int:
    """Count how many distinct keywords appear in text."""
    if not text:
        return 0
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw.lower() in text_lower)


def _count_code_chars(text: str) -> int:
    """Count characters inside fenced code blocks or indented code lines."""
    count = 0
    # Fenced code blocks: ```...```
    fenced = re.findall(r"```[\s\S]*?```", text)
    for block in fenced:
        # Strip the fence markers themselves
        inner = block.strip("`").strip()
        count += len(inner)

    # Indented lines (4+ spaces or tab at start) not already in fenced blocks
    # Simple heuristic: count lines that look like code
    for line in text.splitlines():
        stripped = line.rstrip()
        if stripped and (line.startswith("    ") or line.startswith("\t")):
            count += len(stripped)

    return count


def _count_step_chars(text: str) -> int:
    """Count characters in numbered/bulleted step sequences."""
    count = 0
    step_pattern = re.compile(
        r"^\s*(?:\d+[\.\)]\s|[-*]\s|step\s+\d+)", re.IGNORECASE
    )
    for line in text.splitlines():
        if step_pattern.match(line):
            count += len(line.strip())
    return count


def _count_indentation_depth(text: str) -> int:
    """Measure maximum indentation depth as a complexity proxy."""
    max_depth = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        # Count leading spaces (4 spaces = 1 level) or tabs
        spaces = len(line) - len(line.lstrip(" "))
        tabs = len(line) - len(line.lstrip("\t"))
        depth = max(spaces // 4, tabs)
        if depth > max_depth:
            max_depth = depth
    return max_depth


def _count_branch_indicators(text: str) -> int:
    """Count branching constructs as complexity signals."""
    text_lower = text.lower()
    branch_tokens = [
        "if ", "elif ", "else:", "else {",
        "match ", "case ", "switch ", "? :",
        "try:", "except ", "catch ", "finally:",
        "for ", "while ", "loop ",
        "and ", "or ", "not ",
    ]
    return sum(text_lower.count(tok) for tok in branch_tokens)


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------


def _score_accuracy_criticality(methodology: Methodology) -> float:
    """Score based on presence of accuracy-critical keywords.

    Score = min(1.0, matched_count * 0.2)
    """
    text = _combine_text(methodology)
    matched = _keyword_hit_count(text, _ACCURACY_KEYWORDS)

    # Also boost if accuracy_contract is hard or frontier
    contract_boost = 0.0
    if methodology.accuracy_contract in ("hard", "frontier"):
        contract_boost = 0.4
    elif methodology.accuracy_contract == "scenario":
        contract_boost = 0.2

    return min(1.0, matched * 0.2 + contract_boost)


def _score_novelty(methodology: Methodology) -> float:
    """Score novelty from explicit novelty_score or keyword scan.

    Prefers the stored novelty_score when available since it was computed
    by the mining pipeline with richer context.
    """
    if methodology.novelty_score is not None and methodology.novelty_score > 0.0:
        return min(1.0, max(0.0, methodology.novelty_score))

    text = _combine_text(methodology)
    keyword_ratio = _keyword_hit_ratio(text, _NOVELTY_KEYWORDS)

    # Boost if methodology_type is not a common pattern
    type_boost = 0.0
    if methodology.methodology_type in ("GOTCHA", "DECISION"):
        type_boost = 0.15

    # Boost if tags contain uncommon domain markers
    tag_boost = 0.0
    if methodology.tags:
        # Tags that are multi-word or very specific signal novelty
        specific_tags = [t for t in methodology.tags if len(t.split()) > 1 or "-" in t]
        tag_boost = min(0.2, len(specific_tags) * 0.05)

    return min(1.0, keyword_ratio * 3.0 + type_boost + tag_boost)


def _score_methodology_density(methodology: Methodology) -> float:
    """Measure ratio of actionable content vs. prose.

    Actionable content: code blocks, step sequences, algorithm descriptions.
    Score = min(1.0, (code_chars + step_chars) / max(total_chars, 1))
    """
    text = _combine_text(methodology)
    total_chars = max(len(text), 1)

    # Direct code contribution from solution_code field
    solution_code_len = len(methodology.solution_code.strip()) if methodology.solution_code else 0

    # Code blocks and step sequences in all text
    code_chars = _count_code_chars(text)
    step_chars = _count_step_chars(text)

    # solution_code itself is inherently actionable
    actionable = solution_code_len + code_chars + step_chars

    # Avoid double-counting: solution_code is already in total_chars via _combine_text
    ratio = actionable / max(total_chars, 1)

    return min(1.0, ratio)


def _score_emergence_leverage(methodology: Methodology) -> float:
    """Score potential for emergent capabilities.

    Checks capability_data for activation_triggers, latent_capabilities,
    domain bridging, and composability indicators.
    """
    score = 0.0
    cap_data = methodology.capability_data or {}

    # Activation triggers
    triggers = cap_data.get("activation_triggers", [])
    if isinstance(triggers, list):
        score += min(0.3, len(triggers) * 0.1)

    # Latent capabilities (not a standard field but may be enriched)
    latent = cap_data.get("latent_capabilities", [])
    if isinstance(latent, list):
        score += min(0.2, len(latent) * 0.1)

    # Domain bridging: multiple domains in capability_data
    domains = cap_data.get("domain", [])
    if isinstance(domains, list) and len(domains) >= 2:
        score += min(0.3, (len(domains) - 1) * 0.15)

    # Composability: can_chain_after / can_chain_before
    composability = cap_data.get("composability", {})
    if isinstance(composability, dict):
        chain_after = composability.get("can_chain_after", [])
        chain_before = composability.get("can_chain_before", [])
        if isinstance(chain_after, list) and isinstance(chain_before, list):
            chain_count = len(chain_after) + len(chain_before)
            score += min(0.2, chain_count * 0.05)

    # Composition candidates
    candidates = cap_data.get("composition_candidates", [])
    if isinstance(candidates, list):
        score += min(0.15, len(candidates) * 0.05)

    # Text-based bridging indicators
    text = _combine_text(methodology)
    bridge_terms = [
        "cross-domain", "bridge", "connect", "integrate",
        "compose", "chain", "pipeline", "multi-agent",
        "orchestrat", "federat", "synergy",
    ]
    bridge_hits = sum(1 for term in bridge_terms if term in text.lower())
    score += min(0.15, bridge_hits * 0.05)

    return min(1.0, score)


def _score_context_sovereignty(methodology: Methodology) -> float:
    """Score how context-specific and locally sovereign the methodology is.

    Higher = more dependent on local context, harder for a generic model
    to infer. This makes it MORE worth storing.
    """
    text = _combine_text(methodology)
    marker_hits = _keyword_hit_count(text, _CONTEXT_MARKERS)

    # File paths in the text (specific paths are strong sovereignty signals)
    path_pattern = re.compile(r"(?:/[\w./-]+){2,}")
    path_matches = path_pattern.findall(text)
    path_score = min(0.3, len(path_matches) * 0.05)

    # files_affected field
    files_score = min(0.2, len(methodology.files_affected) * 0.05)

    # Scope: narrower scope = higher sovereignty
    scope_boost = 0.0
    if methodology.scope == "project":
        scope_boost = 0.15
    elif methodology.scope == "repo":
        scope_boost = 0.2
    elif methodology.scope == "file":
        scope_boost = 0.25

    # Keyword markers
    marker_score = min(0.3, marker_hits * 0.03)

    return min(1.0, marker_score + path_score + files_score + scope_boost)


def _score_complexity(methodology: Methodology) -> float:
    """Measure structural/algorithmic complexity.

    Score = min(1.0, complexity_indicators / 10)
    """
    text = _combine_text(methodology)

    # Keyword-based complexity indicators
    keyword_hits = _keyword_hit_count(text, _COMPLEXITY_INDICATORS)

    # Structural complexity from code
    indent_depth = _count_indentation_depth(text)
    branch_count = _count_branch_indicators(text)

    # Combine: keywords + depth + branches
    total_indicators = keyword_hits + (indent_depth // 2) + (branch_count // 3)

    return min(1.0, total_indicators / 10.0)


def _score_reproducibility(methodology: Methodology) -> float:
    """Score how easily an LLM could regenerate this from scratch.

    HIGH score = easy to reproduce = BAD (will receive NEGATIVE weight).
    LOW score = hard to reproduce = GOOD (penalty is small).
    """
    text = _combine_text(methodology)
    text_lower = text.lower()
    score = 0.0

    # Boilerplate detection
    boilerplate_hits = _keyword_hit_count(text, _BOILERPLATE_KEYWORDS)
    score += min(0.4, boilerplate_hits * 0.15)

    # Short solution code is usually trivial
    solution_len = len(methodology.solution_code.strip()) if methodology.solution_code else 0
    if solution_len < 50:
        score += 0.25
    elif solution_len < 150:
        score += 0.10

    # Very generic problem descriptions
    generic_problems = [
        "how to", "how do i", "what is", "explain",
        "example of", "simple", "basic",
    ]
    generic_hits = sum(1 for gp in generic_problems if gp in text_lower)
    score += min(0.2, generic_hits * 0.07)

    # Standard library / common pattern detection
    standard_patterns = [
        "import json", "import os", "import sys", "import re",
        "fetch(", "axios.", "requests.get", "requests.post",
        "app.get(", "app.post(", "@app.route",
        "select * from", "insert into", "update ", "delete from",
        "class Meta:", "class Config:",
    ]
    std_hits = sum(1 for sp in standard_patterns if sp in text_lower)
    score += min(0.25, std_hits * 0.05)

    # Counterbalance: domain-specific content REDUCES reproducibility score
    domain_specific = [
        "invariant", "race condition", "consensus", "crdt",
        "custom protocol", "proprietary", "internal api",
        "undocumented", "workaround for",
    ]
    domain_hits = sum(1 for ds in domain_specific if ds in text_lower)
    score -= min(0.3, domain_hits * 0.1)

    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Dimension scoring dispatch
# ---------------------------------------------------------------------------

_SCORERS: dict[TriageDimension, callable] = {
    TriageDimension.ACCURACY_CRITICALITY: _score_accuracy_criticality,
    TriageDimension.NOVELTY: _score_novelty,
    TriageDimension.METHODOLOGY_DENSITY: _score_methodology_density,
    TriageDimension.EMERGENCE_LEVERAGE: _score_emergence_leverage,
    TriageDimension.CONTEXT_SOVEREIGNTY: _score_context_sovereignty,
    TriageDimension.COMPLEXITY: _score_complexity,
    TriageDimension.REPRODUCIBILITY: _score_reproducibility,
}


def score_dimension(methodology: Methodology, dimension: TriageDimension) -> float:
    """Score a single triage dimension for a methodology.

    Parameters
    ----------
    methodology:
        The Methodology instance to evaluate.
    dimension:
        Which of the 7 triage dimensions to score.

    Returns
    -------
    float
        A score between 0.0 and 1.0 (inclusive).
    """
    scorer = _SCORERS.get(dimension)
    if scorer is None:
        logger.warning("No scorer registered for dimension %s", dimension)
        return 0.0
    try:
        raw = scorer(methodology)
        return max(0.0, min(1.0, raw))
    except Exception:
        logger.exception(
            "Error scoring dimension %s for methodology %s",
            dimension,
            methodology.id,
        )
        return 0.0


# ---------------------------------------------------------------------------
# Concept type classification
# ---------------------------------------------------------------------------


def classify_concept_type(dimension_scores: dict[str, float]) -> str:
    """Infer concept type from the dominant scoring dimensions.

    Uses a priority-ordered decision matrix. Each concept type has a
    characteristic dimension signature. When multiple types could match,
    the most specific (narrowest) pattern wins.

    Parameters
    ----------
    dimension_scores:
        Mapping of TriageDimension.value -> score (0.0 to 1.0).

    Returns
    -------
    str
        One of: "invariant", "failure_mode", "protocol", "novel_abstraction",
        "decision_rule", "bridge", "general".
    """
    acc = dimension_scores.get(TriageDimension.ACCURACY_CRITICALITY.value, 0.0)
    nov = dimension_scores.get(TriageDimension.NOVELTY.value, 0.0)
    density = dimension_scores.get(TriageDimension.METHODOLOGY_DENSITY.value, 0.0)
    emergence = dimension_scores.get(TriageDimension.EMERGENCE_LEVERAGE.value, 0.0)
    context = dimension_scores.get(TriageDimension.CONTEXT_SOVEREIGNTY.value, 0.0)
    complexity = dimension_scores.get(TriageDimension.COMPLEXITY.value, 0.0)
    repro = dimension_scores.get(TriageDimension.REPRODUCIBILITY.value, 0.0)

    # Decision matrix: pick the concept type whose signature best matches
    # the dimension profile. More specific patterns are checked first.

    # Invariant: high accuracy criticality + significant complexity, low repro.
    # The hallmark of an invariant is that accuracy is paramount AND the logic
    # is complex enough that getting it wrong is non-trivial.
    if acc >= 0.5 and complexity >= 0.3 and repro < 0.5:
        return "invariant"

    # Decision rule: moderate accuracy + moderate context + meaningful density.
    # Decision rules are actionable (high density) local logic that balances
    # accuracy with context-awareness. Checked before failure_mode because
    # decision rules have richer actionable content (density).
    if acc >= 0.3 and context >= 0.3 and density >= 0.3:
        return "decision_rule"

    # Failure mode: accuracy + context sovereignty but lower density.
    # Failure modes are warnings/gotchas -- they describe what goes wrong,
    # not step-by-step procedures (which would be protocols or decision rules).
    if acc >= 0.4 and context >= 0.4:
        return "failure_mode"

    # Protocol: high methodology density + moderate complexity (step-by-step).
    # Protocols are procedural recipes with rich actionable content.
    if density >= 0.5 and complexity >= 0.2:
        return "protocol"

    # Novel abstraction: high novelty, hard to reproduce.
    # These represent genuinely new ideas that a model would not infer.
    if nov >= 0.5 and repro < 0.4:
        return "novel_abstraction"

    # Bridge: high emergence leverage (cross-domain connective tissue).
    # Bridges create value by linking disparate knowledge domains.
    if emergence >= 0.4:
        return "bridge"

    return "general"


# ---------------------------------------------------------------------------
# Composite triage scoring
# ---------------------------------------------------------------------------


def compute_triage_score(methodology: Methodology) -> TriageResult:
    """Compute the full 7-dimensional triage score for a methodology.

    Parameters
    ----------
    methodology:
        The Methodology to evaluate for ingest.

    Returns
    -------
    TriageResult
        Contains composite score, per-dimension scores, accept/reject decision,
        and inferred concept type.
    """
    dimension_scores: dict[str, float] = {}

    for dim in TriageDimension:
        dimension_scores[dim.value] = score_dimension(methodology, dim)

    # Weighted composite
    composite = 0.0
    for dim, weight in _DIMENSION_WEIGHTS.items():
        composite += weight * dimension_scores[dim.value]

    # Accept/reject decision
    accept = composite >= _ACCEPT_THRESHOLD
    reject_reason: Optional[str] = None

    if not accept:
        # Build an informative rejection reason
        low_dims = [
            dim.value
            for dim in TriageDimension
            if dim != TriageDimension.REPRODUCIBILITY
            and dimension_scores[dim.value] < 0.3
        ]
        repro_score = dimension_scores[TriageDimension.REPRODUCIBILITY.value]
        parts: list[str] = []
        parts.append(f"composite={composite:.3f} < threshold={_ACCEPT_THRESHOLD}")
        if low_dims:
            parts.append(f"low dimensions: {', '.join(low_dims)}")
        if repro_score > 0.6:
            parts.append(
                f"high reproducibility ({repro_score:.2f}) indicates boilerplate"
            )
        reject_reason = "; ".join(parts)

    # Concept type classification
    concept_type = classify_concept_type(dimension_scores)

    return TriageResult(
        composite_score=round(composite, 4),
        dimension_scores={k: round(v, 4) for k, v in dimension_scores.items()},
        accept=accept,
        reject_reason=reject_reason,
        concept_type=concept_type,
        methodology_id=methodology.id,
    )


# ---------------------------------------------------------------------------
# Batch triage
# ---------------------------------------------------------------------------


def batch_triage(methodologies: list[Methodology]) -> list[TriageResult]:
    """Score all methodologies and return results sorted by composite_score descending.

    Parameters
    ----------
    methodologies:
        List of Methodology instances to evaluate.

    Returns
    -------
    list[TriageResult]
        Triage results sorted from highest to lowest composite score.
    """
    results: list[TriageResult] = []
    for m in methodologies:
        try:
            result = compute_triage_score(m)
            results.append(result)
        except Exception:
            logger.exception("Failed to triage methodology %s", m.id)
            # Include a zero-score reject entry so nothing is silently dropped
            results.append(
                TriageResult(
                    composite_score=0.0,
                    dimension_scores={dim.value: 0.0 for dim in TriageDimension},
                    accept=False,
                    reject_reason=f"scoring error for methodology {m.id}",
                    concept_type=None,
                    methodology_id=m.id,
                )
            )

    results.sort(key=lambda r: r.composite_score, reverse=True)
    return results
