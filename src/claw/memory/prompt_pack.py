"""Prompt Pack Generator -- converts methodologies into operational knowledge cards.

Inspired by the Selective Pseudo-RAG pattern: store only high-consequence,
hard-to-reproduce, novel, or methodologically important knowledge as
immediately usable operational cards, not passive text chunks.
"""

from __future__ import annotations

import re
from typing import Any

from claw.core.models import Methodology


# ---------------------------------------------------------------------------
# Accuracy contract priority (lower number = higher priority)
# ---------------------------------------------------------------------------

_CONTRACT_PRIORITY: dict[str, int] = {
    "hard": 0,
    "frontier": 1,
    "scenario": 2,
    "soft": 3,
}

# ---------------------------------------------------------------------------
# Keyword sets for heuristic classification
#
# Multi-word phrases are checked with simple `in` substring matching.
# Single words are checked with word-boundary regex to avoid false positives
# (e.g. "new" inside "renewal" should not trigger frontier).
# ---------------------------------------------------------------------------

_HARD_KEYWORDS: tuple[str, ...] = (
    "security", "invariant", "correctness", "must", "required", "critical",
    "vulnerability", "exploit", "injection", "authentication", "authorization",
    "race condition", "deadlock", "data loss", "corruption",
)

_FRONTIER_KEYWORDS: tuple[str, ...] = (
    "novel", "experimental", "emergent", "prototype", "cutting-edge",
    "breakthrough", "unprecedented", "first-of-kind", "research",
    "novel approach", "new technique", "new approach", "new method",
)

_SCENARIO_KEYWORDS: tuple[str, ...] = (
    "context-specific", "conditional", "depends on",
    "platform-specific", "only when", "given that",
    "under conditions", "scenario",
    "when", "if",
)

# Compiled word-boundary patterns (cached at module level)
_HARD_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
    for kw in _HARD_KEYWORDS
]

_FRONTIER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
    for kw in _FRONTIER_KEYWORDS
]

_SCENARIO_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
    for kw in _SCENARIO_KEYWORDS
]

# ---------------------------------------------------------------------------
# Verb prefixes for directive extraction
# ---------------------------------------------------------------------------

_DIRECTIVE_VERBS: tuple[str, ...] = (
    "use", "apply", "replace", "avoid", "prefer", "ensure", "validate",
    "check", "implement", "enforce", "guard", "wrap", "inject", "extract",
    "convert", "transform", "call", "invoke", "pass", "return", "raise",
    "catch", "retry", "fallback", "default", "configure", "set", "add",
    "remove", "disable", "enable", "switch", "migrate", "refactor",
)


# ===================================================================
# 1. build_prompt_pack
# ===================================================================

def build_prompt_pack(
    methodologies: list[Methodology],
    scenario: str = "",
    top_k: int = 8,
) -> str:
    """Convert retrieved methodologies into a structured prompt pack string.

    Each methodology becomes an operational knowledge card sorted by
    accuracy-contract priority (hard > frontier > scenario > soft) then
    by triage_score descending. The result is a formatted block ready
    for direct injection into an agent's system or user prompt.

    Args:
        methodologies: Retrieved Methodology objects from memory.
        scenario: Optional scenario description for contextual framing.
        top_k: Maximum number of cards to include in the pack.

    Returns:
        A formatted multi-line string containing all operational cards.
    """
    if not methodologies:
        return ""

    # Sort: contract priority ascending (hard first), then triage_score desc
    sorted_meths = sorted(
        methodologies,
        key=lambda m: (
            _CONTRACT_PRIORITY.get(m.accuracy_contract, 3),
            -(m.triage_score or 0.0),
        ),
    )

    cards: list[str] = []
    for meth in sorted_meths[:top_k]:
        card = _render_card(meth)
        cards.append(card)

    header_parts = [
        "=== OPERATIONAL KNOWLEDGE PACK ===",
        f"Cards: {len(cards)}",
    ]
    if scenario:
        header_parts.append(f"Scenario: {scenario}")
    header_parts.append(
        "DIRECTIVE: You MUST consult these cards before generating code. "
        "They are not suggestions -- they are operational constraints derived "
        "from validated prior experience."
    )

    header = "\n".join(header_parts)
    body = "\n\n---\n\n".join(cards)
    footer = "=== END KNOWLEDGE PACK ==="

    return f"{header}\n\n{body}\n\n{footer}"


def _render_card(meth: Methodology) -> str:
    """Render a single Methodology as an operational knowledge card."""
    lines: list[str] = []

    # Card header
    contract_label = meth.accuracy_contract.upper()
    lines.append(f"[{contract_label}] Knowledge Card  (id: {meth.id[:12]})")

    # Claim
    lines.append(f"Claim: {meth.problem_description}")

    # Accuracy contract explanation
    contract_explanation = _contract_explanation(meth.accuracy_contract)
    lines.append(f"Accuracy Contract: {meth.accuracy_contract} -- {contract_explanation}")

    # Use-immediately directives
    directives = meth.use_immediately_as or extract_use_immediately_directives(meth)
    if directives:
        lines.append("Use Immediately As:")
        for d in directives:
            lines.append(f"  -> {d}")

    # Tension questions
    tensions = meth.tension_questions or generate_tension_questions(meth)
    if tensions:
        lines.append("Tension Questions:")
        for t in tensions:
            lines.append(f"  ? {t}")

    # Latent capability hooks
    hooks = _extract_capability_hooks(meth.capability_data)
    if hooks:
        lines.append("Latent Capability Hooks:")
        for h in hooks:
            lines.append(f"  * {h}")

    # Source provenance
    if meth.tags:
        lines.append(f"Provenance: {', '.join(meth.tags)}")

    # Priority score
    priority = score_card_priority(meth)
    lines.append(f"Priority: {priority:.2f}")

    return "\n".join(lines)


def _contract_explanation(contract: str) -> str:
    """Return a human-readable explanation for an accuracy contract level."""
    explanations: dict[str, str] = {
        "hard": "Violation breaks correctness or security. Must be obeyed unconditionally.",
        "frontier": "Novel or emerging pattern. High value but verify edge cases.",
        "scenario": "Context-dependent rule. Apply when scenario conditions match.",
        "soft": "General heuristic. Prefer unless overridden by higher-priority card.",
    }
    return explanations.get(contract, "Unknown contract level.")


def _extract_capability_hooks(capability_data: dict[str, Any] | None) -> list[str]:
    """Extract latent capability hooks from capability_data dictionary.

    Looks for activation triggers, composability interfaces, domain tags,
    and applicability conditions that signal when/how this capability
    can be chained or activated.
    """
    if not capability_data:
        return []

    hooks: list[str] = []

    # Activation triggers
    triggers = capability_data.get("activation_triggers", [])
    for trigger in triggers[:3]:
        if isinstance(trigger, str) and trigger.strip():
            hooks.append(f"Activates on: {trigger.strip()}")

    # Domain tags
    domains = capability_data.get("domain", [])
    if domains:
        domain_str = ", ".join(str(d) for d in domains[:5])
        hooks.append(f"Domain: {domain_str}")

    # Composability chains
    composability = capability_data.get("composability", {})
    if isinstance(composability, dict):
        chain_after = composability.get("can_chain_after", [])
        chain_before = composability.get("can_chain_before", [])
        if chain_after:
            hooks.append(f"Can chain after: {', '.join(str(c) for c in chain_after[:3])}")
        if chain_before:
            hooks.append(f"Can chain before: {', '.join(str(c) for c in chain_before[:3])}")

    # Applicability signals
    applicability = capability_data.get("applicability", [])
    for app_item in applicability[:2]:
        if isinstance(app_item, str) and app_item.strip():
            hooks.append(f"Applicable when: {app_item.strip()}")

    # Capability type
    cap_type = capability_data.get("capability_type")
    if cap_type and isinstance(cap_type, str):
        hooks.append(f"Type: {cap_type}")

    # Risks as negative hooks
    risks = capability_data.get("risks", [])
    for risk in risks[:2]:
        if isinstance(risk, str) and risk.strip():
            hooks.append(f"Risk: {risk.strip()}")

    return hooks


# ===================================================================
# Helper: word-boundary keyword search
# ===================================================================

def _any_pattern_matches(patterns: list[re.Pattern[str]], text: str) -> bool:
    """Return True if any of the pre-compiled patterns match in text."""
    for pat in patterns:
        if pat.search(text):
            return True
    return False


# ===================================================================
# 2. classify_accuracy_contract
# ===================================================================

def classify_accuracy_contract(methodology: Methodology) -> str:
    """Heuristic classifier that assigns an accuracy_contract based on content.

    Priority order: hard > frontier > scenario > soft.
    Uses word-boundary regex matching to avoid substring false positives.

    Classification rules:
        - "hard": security/invariant/correctness keywords found anywhere
        - "frontier": novelty_score > 0.7, or frontier keywords in
          problem_description or methodology_notes (not solution_code)
        - "scenario": conditional/context-specific keywords in
          problem_description or methodology_notes
        - "soft": default fallback

    Args:
        methodology: A Methodology object to classify.

    Returns:
        One of: "hard", "frontier", "scenario", "soft".
    """
    # Build text blobs for different scopes
    combined_parts: list[str] = [methodology.problem_description]
    if methodology.solution_code:
        combined_parts.append(methodology.solution_code)
    if methodology.methodology_notes:
        combined_parts.append(methodology.methodology_notes)
    combined = " ".join(combined_parts)

    # Descriptive text only (problem + notes, not code) -- used for
    # frontier and scenario where incidental code keywords are noisy.
    descriptive_parts: list[str] = [methodology.problem_description]
    if methodology.methodology_notes:
        descriptive_parts.append(methodology.methodology_notes)
    descriptive = " ".join(descriptive_parts)

    # --- HARD: check across all text (security invariants matter everywhere) ---
    if _any_pattern_matches(_HARD_PATTERNS, combined):
        return "hard"

    # --- FRONTIER: novelty_score threshold OR keyword in descriptive text ---
    if methodology.novelty_score is not None and methodology.novelty_score > 0.7:
        return "frontier"
    if _any_pattern_matches(_FRONTIER_PATTERNS, descriptive):
        return "frontier"

    # --- SCENARIO: conditional / context-specific keywords in descriptive text ---
    if _any_pattern_matches(_SCENARIO_PATTERNS, descriptive):
        return "scenario"

    return "soft"


# ===================================================================
# 3. extract_use_immediately_directives
# ===================================================================

def extract_use_immediately_directives(methodology: Methodology) -> list[str]:
    """Generate actionable operational directives from methodology content.

    Extracts directives from solution_code, methodology_notes, and
    capability_data. Each directive starts with an imperative verb.

    Args:
        methodology: A Methodology object.

    Returns:
        A list of 1-5 actionable directive strings.
    """
    directives: list[str] = []

    # 1. Extract from solution_code: look for actionable sentences
    if methodology.solution_code:
        code_directives = _extract_directives_from_text(methodology.solution_code)
        directives.extend(code_directives)

    # 2. Extract from methodology_notes
    if methodology.methodology_notes:
        note_directives = _extract_directives_from_text(methodology.methodology_notes)
        directives.extend(note_directives)

    # 3. Extract from capability_data
    if methodology.capability_data:
        cap_directives = _extract_directives_from_capability(methodology.capability_data)
        directives.extend(cap_directives)

    # 4. Synthesize a directive from problem_description if nothing else
    if not directives and methodology.problem_description:
        fallback = _synthesize_directive_from_problem(methodology.problem_description)
        if fallback:
            directives.append(fallback)

    # Deduplicate while preserving order, then cap at 5
    seen: set[str] = set()
    unique: list[str] = []
    for d in directives:
        normalized = d.strip().lower()
        if normalized not in seen:
            seen.add(normalized)
            unique.append(d.strip())

    return unique[:5]


def _extract_directives_from_text(text: str) -> list[str]:
    """Extract sentences that begin with imperative verbs from free text."""
    directives: list[str] = []
    # Split on sentence boundaries and line breaks
    segments = re.split(r'[.\n;]+', text)
    for segment in segments:
        segment = segment.strip()
        if not segment or len(segment) < 10:
            continue
        first_word = segment.split()[0].lower() if segment.split() else ""
        if first_word in _DIRECTIVE_VERBS:
            # Capitalize first letter and ensure it's not too long
            directive = segment[0].upper() + segment[1:]
            if len(directive) > 200:
                directive = directive[:197] + "..."
            directives.append(directive)
    return directives


def _extract_directives_from_capability(capability_data: dict[str, Any]) -> list[str]:
    """Derive directives from structured capability_data fields."""
    directives: list[str] = []

    # From activation_triggers -> "Apply when <trigger>"
    triggers = capability_data.get("activation_triggers", [])
    for trigger in triggers[:2]:
        if isinstance(trigger, str) and trigger.strip():
            directives.append(f"Apply when {trigger.strip()}")

    # From risks -> "Guard against <risk>"
    risks = capability_data.get("risks", [])
    for risk in risks[:1]:
        if isinstance(risk, str) and risk.strip():
            directives.append(f"Guard against {risk.strip()}")

    # From dependencies -> "Ensure <dependency> is available"
    deps = capability_data.get("dependencies", [])
    if deps:
        dep_list = ", ".join(str(d) for d in deps[:3])
        directives.append(f"Ensure dependencies are available: {dep_list}")

    return directives


def _synthesize_directive_from_problem(problem_description: str) -> str | None:
    """Create a fallback directive from the problem description."""
    # Strip to first sentence or first 150 chars
    first_sentence = problem_description.split(".")[0].strip()
    if len(first_sentence) < 10:
        return None
    return f"Apply this solution when encountering: {first_sentence}"


# ===================================================================
# 4. generate_tension_questions
# ===================================================================

def generate_tension_questions(methodology: Methodology) -> list[str]:
    """Generate 2-3 epistemic tension questions for a methodology.

    Based on the Epistemic Tension Field (ETF) pattern, these questions
    force agents to interrogate their own assumptions before applying
    the methodology blindly.

    Args:
        methodology: A Methodology object.

    Returns:
        A list of 2-3 tension question strings.
    """
    questions: list[str] = []
    contract = methodology.accuracy_contract
    problem = methodology.problem_description
    has_code = bool(methodology.solution_code and methodology.solution_code.strip())

    # --- Universal question: model-prior override ---
    questions.append(
        "What model-prior assumption might override this context, "
        "causing you to ignore this card's guidance?"
    )

    # --- Contract-specific questions ---
    if contract == "hard":
        questions.append(
            f"What would fail catastrophically if the claim "
            f"'{_truncate(problem, 80)}' were wrong or outdated?"
        )
        if has_code:
            questions.append(
                "Does the solution code enforce the invariant at all call sites, "
                "or only at the demonstrated one?"
            )
    elif contract == "frontier":
        questions.append(
            "Is there a simpler, well-established approach that achieves "
            "the same result without the novelty risk?"
        )
        questions.append(
            "Has this pattern been validated beyond the original context, "
            "or is it a single-observation extrapolation?"
        )
    elif contract == "scenario":
        questions.append(
            "Do the scenario conditions that activate this rule actually "
            "hold in the current task context?"
        )
        questions.append(
            "What would happen if you applied this outside its intended scenario?"
        )
    else:  # soft
        questions.append(
            "Is there a higher-priority card in this pack that contradicts "
            "or supersedes this guidance?"
        )
        if methodology.failure_count > 0:
            ratio = methodology.failure_count / max(
                methodology.success_count + methodology.failure_count, 1
            )
            if ratio > 0.3:
                questions.append(
                    f"This methodology has a {ratio:.0%} failure rate. "
                    "What conditions differentiate its successes from failures?"
                )
            else:
                questions.append(
                    "What would fail if this claim were wrong?"
                )
        else:
            questions.append(
                "What would fail if this claim were wrong?"
            )

    return questions[:3]


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, appending '...' if shortened."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


# ===================================================================
# 5. score_card_priority
# ===================================================================

def score_card_priority(methodology: Methodology) -> float:
    """Compute a 0.0-1.0 priority score for ordering in the prompt pack.

    Weight breakdown:
        - accuracy_contract: 0.3 (hard=1.0, frontier=0.75, scenario=0.5, soft=0.25)
        - triage_score: 0.3 (direct value, clamped to [0, 1])
        - novelty_score: 0.2 (direct value, clamped to [0, 1])
        - has_use_immediately: 0.2 (1.0 if non-empty, 0.0 otherwise)

    Args:
        methodology: A Methodology object.

    Returns:
        A float between 0.0 and 1.0.
    """
    # Accuracy contract component
    contract_scores: dict[str, float] = {
        "hard": 1.0,
        "frontier": 0.75,
        "scenario": 0.5,
        "soft": 0.25,
    }
    contract_val = contract_scores.get(methodology.accuracy_contract, 0.25)

    # Triage score component
    triage_val = _clamp(methodology.triage_score or 0.0, 0.0, 1.0)

    # Novelty score component
    novelty_val = _clamp(methodology.novelty_score or 0.0, 0.0, 1.0)

    # Has use-immediately directives component
    has_directives = 1.0 if methodology.use_immediately_as else 0.0

    # Weighted sum
    score = (
        0.3 * contract_val
        + 0.3 * triage_val
        + 0.2 * novelty_val
        + 0.2 * has_directives
    )

    return _clamp(score, 0.0, 1.0)


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp a value to [lo, hi]."""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value
