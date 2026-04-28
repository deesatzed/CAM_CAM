"""Latent Capability Discovery Engine (LCDE).

After each successful task outcome, LCDE extracts what latent capabilities
the used methodologies enabled. This drives:
- Capability expansion tracking
- Adjacent task suggestion
- Knowledge gap identification
- Use-immediately-as directive refinement
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Optional

from claw.core.models import CapabilityData, Methodology

logger = logging.getLogger("claw.lcde")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CapabilityDiscovery:
    """Result of LCDE extraction for one methodology applied to a task."""

    methodology_id: str
    task_id: str
    discovered_capabilities: list[str] = field(default_factory=list)
    adjacent_tasks: list[str] = field(default_factory=list)
    knowledge_gaps: list[str] = field(default_factory=list)
    use_refinements: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dictionary."""
        return {
            "methodology_id": self.methodology_id,
            "task_id": self.task_id,
            "discovered_capabilities": self.discovered_capabilities,
            "adjacent_tasks": self.adjacent_tasks,
            "knowledge_gaps": self.knowledge_gaps,
            "use_refinements": self.use_refinements,
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Keyword / NLP utilities (lightweight, no external deps beyond stdlib)
# ---------------------------------------------------------------------------

# Common stop words filtered out of keyword extraction
_STOP_WORDS: frozenset[str] = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "of", "in", "to",
    "for", "with", "on", "at", "from", "by", "about", "as", "into",
    "through", "during", "before", "after", "above", "below", "between",
    "but", "and", "or", "if", "then", "else", "when", "up", "out", "that",
    "this", "it", "not", "no", "so", "very", "just", "also", "than",
    "more", "some", "such", "only", "other", "new", "used", "using",
    "use", "one", "two", "each", "which", "their", "its", "all", "any",
})


def _tokenize(text: str) -> list[str]:
    """Extract lowercase alpha-numeric tokens from text, filtering stop words."""
    tokens = re.findall(r"[a-z][a-z0-9_]+", text.lower())
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 2]


def _keyword_overlap(tokens_a: list[str], tokens_b: list[str]) -> list[str]:
    """Return sorted intersection of two token lists."""
    return sorted(set(tokens_a) & set(tokens_b))


def _unique_tokens(tokens_a: list[str], tokens_b: list[str]) -> list[str]:
    """Tokens in A that are NOT in B."""
    b_set = set(tokens_b)
    seen: set[str] = set()
    result: list[str] = []
    for t in tokens_a:
        if t not in b_set and t not in seen:
            result.append(t)
            seen.add(t)
    return result


# ---------------------------------------------------------------------------
# Capability data parsing helpers
# ---------------------------------------------------------------------------

def _parse_cap_data(methodology: Methodology) -> Optional[CapabilityData]:
    """Parse capability_data dict into a CapabilityData model, or None."""
    raw = methodology.capability_data
    if not raw:
        return None
    try:
        if isinstance(raw, str):
            raw = json.loads(raw)
        return CapabilityData(**raw)
    except Exception:
        return None


def _get_source_repos(methodology: Methodology) -> list[str]:
    """Get the list of source repos from capability_data."""
    cd = _parse_cap_data(methodology)
    if cd:
        return cd.source_repos
    return []


# ---------------------------------------------------------------------------
# Domain tag vocabulary for composition reasoning
# ---------------------------------------------------------------------------

# Maps broad domain families to related domain tags for composition discovery
_DOMAIN_COMPOSITION_MAP: dict[str, list[str]] = {
    "testing": ["validation", "quality", "coverage", "assertions", "ci_cd"],
    "api": ["http", "rest", "graphql", "grpc", "networking", "endpoints"],
    "database": ["sql", "orm", "migration", "schema", "persistence", "storage"],
    "security": ["auth", "encryption", "tokens", "permissions", "rbac"],
    "observability": ["logging", "metrics", "tracing", "monitoring", "alerting"],
    "data_processing": ["etl", "pipeline", "stream", "batch", "transform"],
    "ml": ["model", "training", "inference", "embeddings", "features"],
    "frontend": ["ui", "components", "state", "rendering", "accessibility"],
    "cli": ["commands", "arguments", "terminal", "scripting", "automation"],
    "devops": ["deployment", "containers", "infrastructure", "ci_cd", "config"],
}

# Inverse map: tag -> domain family
_TAG_TO_FAMILY: dict[str, str] = {}
for _family, _tags in _DOMAIN_COMPOSITION_MAP.items():
    for _tag in _tags:
        _TAG_TO_FAMILY[_tag] = _family
    _TAG_TO_FAMILY[_family] = _family


# ---------------------------------------------------------------------------
# Core extraction functions
# ---------------------------------------------------------------------------

def extract_capabilities(
    methodology: Methodology,
    task_description: str,
    task_id: str = "",
    outcome_notes: str = "",
) -> CapabilityDiscovery:
    """Analyze a methodology's data against task context to discover latent capabilities.

    This is the primary LCDE extraction function. It performs four analyses:
      1. Discovered capabilities: what new capabilities this methodology enables
      2. Adjacent tasks: what tasks become possible now
      3. Knowledge gaps: what is missing to fully exploit this methodology
      4. Use refinements: refined use_immediately_as directives based on actual use

    All analysis is deterministic and based on structural inspection of the
    methodology's capability_data, tags, solution_code, and the task context.

    Args:
        methodology: The methodology that was applied in the successful task.
        task_description: Full text description of the task that was completed.
        task_id: Identifier of the task (for linking the discovery record).
        outcome_notes: Optional notes about how the outcome went (approach summary).

    Returns:
        A CapabilityDiscovery dataclass with all extracted information.
    """
    cap_data = _parse_cap_data(methodology)
    meth_tags = [t.lower() for t in methodology.tags]
    task_tokens = _tokenize(task_description)
    outcome_tokens = _tokenize(outcome_notes) if outcome_notes else []
    solution_tokens = _tokenize(methodology.solution_code[:2000])
    problem_tokens = _tokenize(methodology.problem_description)

    # Combined methodology vocabulary
    meth_vocab = list(set(meth_tags + solution_tokens + problem_tokens))

    # ----- 1. Discover capabilities -----
    discovered = _extract_discovered_capabilities(
        methodology, cap_data, meth_tags, task_tokens, meth_vocab, outcome_tokens,
    )

    # ----- 2. Generate adjacent tasks -----
    adjacent = _generate_adjacent_tasks(
        methodology, cap_data, meth_tags, task_tokens, task_description, meth_vocab,
    )

    # ----- 3. Identify knowledge gaps -----
    gaps = _identify_knowledge_gaps(methodology, cap_data)

    # ----- 4. Generate use refinements -----
    refinements = _generate_use_refinements(
        methodology, cap_data, task_description, outcome_notes, task_tokens,
    )

    return CapabilityDiscovery(
        methodology_id=methodology.id,
        task_id=task_id,
        discovered_capabilities=discovered,
        adjacent_tasks=adjacent,
        knowledge_gaps=gaps,
        use_refinements=refinements,
    )


def _extract_discovered_capabilities(
    methodology: Methodology,
    cap_data: Optional[CapabilityData],
    meth_tags: list[str],
    task_tokens: list[str],
    meth_vocab: list[str],
    outcome_tokens: list[str],
) -> list[str]:
    """Extract discovered capabilities from the methodology-task intersection.

    Three signals:
      a) Parse capability_data for activation_triggers and latent_capabilities
      b) Cross-reference methodology tags with task description keywords
      c) Pattern composition opportunities (multi-domain connections)
    """
    capabilities: list[str] = []

    # (a) From activation_triggers: each trigger that matches task context
    #     represents an activated latent capability
    if cap_data:
        for trigger in cap_data.activation_triggers:
            trigger_tokens = _tokenize(trigger)
            overlap = _keyword_overlap(trigger_tokens, task_tokens + outcome_tokens)
            if overlap:
                capabilities.append(
                    f"Activated trigger: {trigger} (matched: {', '.join(overlap[:5])})"
                )
            elif not task_tokens:
                # If task has no parseable tokens, include trigger as-is
                capabilities.append(f"Available trigger: {trigger}")

        # Check composability interface for chain-after/chain-before that
        # overlap with the task domain -- these are latent pipeline stages
        if cap_data.composability:
            comp = cap_data.composability
            for chain_tag in comp.can_chain_after:
                if chain_tag.lower() in [t.lower() for t in task_tokens + meth_tags]:
                    capabilities.append(
                        f"Latent pipeline capability: can chain after '{chain_tag}' domain"
                    )
            for chain_tag in comp.can_chain_before:
                if chain_tag.lower() in [t.lower() for t in task_tokens + meth_tags]:
                    capabilities.append(
                        f"Latent pipeline capability: can chain before '{chain_tag}' domain"
                    )

        # Domain coverage: each domain tag on the methodology represents a
        # capability surface area that was exercised
        for domain in cap_data.domain:
            if domain.lower() in [t.lower() for t in task_tokens]:
                capabilities.append(f"Domain capability exercised: {domain}")

    # (b) Cross-reference tags with task keywords
    tag_overlap = _keyword_overlap(meth_tags, task_tokens)
    if tag_overlap:
        capabilities.append(
            f"Tag-task alignment: methodology tags [{', '.join(tag_overlap)}] "
            f"directly matched task context"
        )

    # Unique methodology vocabulary that the task did NOT explicitly mention
    # but that are part of the methodology's solution -- these are latent
    # capabilities the methodology brought to the task beyond what was asked
    unique_meth = _unique_tokens(meth_vocab, task_tokens)[:10]
    if unique_meth:
        capabilities.append(
            f"Latent vocabulary brought by methodology: {', '.join(unique_meth)}"
        )

    # (c) Pattern composition: if methodology spans multiple domain families,
    #     that cross-domain bridge is itself a capability
    domain_families_hit: set[str] = set()
    for tag in meth_tags:
        family = _TAG_TO_FAMILY.get(tag)
        if family:
            domain_families_hit.add(family)
    if cap_data:
        for domain in cap_data.domain:
            family = _TAG_TO_FAMILY.get(domain.lower())
            if family:
                domain_families_hit.add(family)
    if len(domain_families_hit) >= 2:
        families_str = ", ".join(sorted(domain_families_hit))
        capabilities.append(
            f"Cross-domain bridge capability: spans [{families_str}]"
        )

    return capabilities


def _generate_adjacent_tasks(
    methodology: Methodology,
    cap_data: Optional[CapabilityData],
    meth_tags: list[str],
    task_tokens: list[str],
    task_description: str,
    meth_vocab: list[str],
) -> list[str]:
    """Generate adjacent tasks that become possible after this methodology application.

    Three strategies:
      a) Invert: what is the opposite/complementary pattern?
      b) Extend: what is the natural next step?
      c) Compose: what + what = new capability?
    """
    adjacent: list[str] = []

    # (a) Invert the methodology's purpose
    #     If it builds something, the inverse is tearing it down / migrating it.
    #     If it validates, the inverse is generating the thing to validate.
    #     We derive this from methodology_type and the problem description.
    mtype = (methodology.methodology_type or "").upper()
    problem_lower = methodology.problem_description.lower()

    if mtype == "BUG_FIX":
        adjacent.append(
            f"Add regression test for the fixed bug pattern: "
            f"'{methodology.problem_description[:80]}'"
        )
        adjacent.append(
            "Audit codebase for similar bug patterns that may recur"
        )
    elif mtype == "PATTERN":
        adjacent.append(
            f"Apply this pattern to other modules: '{methodology.problem_description[:80]}'"
        )
        adjacent.append(
            "Create a linter rule or code-mod that enforces this pattern project-wide"
        )
    elif mtype == "DECISION":
        adjacent.append(
            "Document the decision rationale as an ADR (Architecture Decision Record)"
        )
        adjacent.append(
            "Revisit this decision when constraints change (add a review trigger)"
        )
    elif mtype == "GOTCHA":
        adjacent.append(
            f"Add a guard-rail / assertion to prevent this gotcha: "
            f"'{methodology.problem_description[:80]}'"
        )
        adjacent.append(
            "Create onboarding documentation warning about this gotcha"
        )

    # General inversions from problem description keywords
    if any(kw in problem_lower for kw in ("add", "create", "implement", "build")):
        adjacent.append(
            "Write comprehensive tests for the newly created functionality"
        )
    if any(kw in problem_lower for kw in ("fix", "repair", "resolve", "patch")):
        adjacent.append(
            "Refactor the repaired area to prevent recurrence structurally"
        )
    if any(kw in problem_lower for kw in ("test", "validate", "assert", "check")):
        adjacent.append(
            "Extend validation coverage to edge cases and boundary conditions"
        )

    # (b) Extend: next step based on capability_data outputs and applicability
    if cap_data:
        for output in cap_data.outputs:
            adjacent.append(
                f"Consume the '{output.name}' output ({output.type}) in a downstream pipeline stage"
            )

        for app_note in cap_data.applicability[:3]:
            if app_note.lower() not in task_description.lower():
                adjacent.append(
                    f"Apply methodology in related context: {app_note}"
                )

        # Non-applicability notes reveal what NOT to do, and by negation
        # suggest where a different approach is needed
        for non_app in cap_data.non_applicability[:2]:
            adjacent.append(
                f"Find alternative methodology for excluded context: {non_app}"
            )

    # (c) Compose: tag-based composition with domain families
    meth_families: set[str] = set()
    for tag in meth_tags:
        family = _TAG_TO_FAMILY.get(tag)
        if family:
            meth_families.add(family)

    for family in meth_families:
        related_families = set()
        for tag in _DOMAIN_COMPOSITION_MAP.get(family, []):
            related_family = _TAG_TO_FAMILY.get(tag)
            if related_family and related_family != family:
                related_families.add(related_family)
        for related in sorted(related_families)[:2]:
            adjacent.append(
                f"Compose '{family}' methodology with '{related}' domain for integrated solution"
            )

    return adjacent


def _identify_knowledge_gaps(
    methodology: Methodology,
    cap_data: Optional[CapabilityData],
) -> list[str]:
    """Identify what is missing to fully exploit this methodology.

    Three gap categories:
      a) Missing test evidence
      b) Missing constraint documentation
      c) Single-source provenance (only seen in one repo)
    """
    gaps: list[str] = []

    # (a) Missing test evidence
    if cap_data:
        if not cap_data.evidence:
            gaps.append(
                "No evidence entries in capability_data -- "
                "methodology has no recorded proof of correctness"
            )
        elif len(cap_data.evidence) < 2:
            gaps.append(
                f"Weak evidence: only {len(cap_data.evidence)} evidence entry. "
                f"Need multiple independent verifications for confidence."
            )

        # Check if source_artifacts reference test files
        has_test_artifact = any(
            "test" in (art.file_path or "").lower()
            for art in cap_data.source_artifacts
        )
        if not has_test_artifact and cap_data.source_artifacts:
            gaps.append(
                "No test file references in source_artifacts -- "
                "cannot verify correctness independently"
            )
    else:
        gaps.append(
            "No capability_data at all -- methodology has not been enriched. "
            "Run assimilation to extract structured capability metadata."
        )

    # (b) Missing constraint documentation
    if cap_data:
        if not cap_data.risks:
            gaps.append(
                "No risk documentation -- unknown failure modes for this methodology"
            )
        if not cap_data.non_applicability:
            gaps.append(
                "No non-applicability constraints documented -- "
                "unclear when this methodology should NOT be used"
            )
        if not cap_data.dependencies:
            # Only a gap if the methodology references imports or external libs
            solution_lower = methodology.solution_code.lower()
            if "import " in solution_lower or "require(" in solution_lower:
                gaps.append(
                    "Methodology references imports but has no dependency list "
                    "in capability_data -- dependency tracking incomplete"
                )
    else:
        # Without capability_data, we check the raw methodology fields
        if not methodology.tags:
            gaps.append(
                "No tags on methodology -- cannot classify or compose with others"
            )

    # (c) Single-source provenance
    source_repos = _get_source_repos(methodology)
    if len(source_repos) <= 1:
        repo_name = source_repos[0] if source_repos else "unknown"
        gaps.append(
            f"Single-source provenance: methodology only observed in '{repo_name}'. "
            f"Cross-repo validation needed to confirm generalizability."
        )

    # Additional gap: if methodology has high retrieval count but low success rate
    total_uses = methodology.success_count + methodology.failure_count
    if total_uses > 0:
        success_rate = methodology.success_count / total_uses
        if success_rate < 0.5 and total_uses >= 3:
            gaps.append(
                f"Low success rate ({success_rate:.0%} over {total_uses} uses) -- "
                f"methodology may need refinement or narrower applicability scope"
            )

    return gaps


def _generate_use_refinements(
    methodology: Methodology,
    cap_data: Optional[CapabilityData],
    task_description: str,
    outcome_notes: str,
    task_tokens: list[str],
) -> list[str]:
    """Generate refined use_immediately_as directives from actual task application.

    These are operational directives that tell future consumers exactly how
    to apply this methodology. The refinements are based on the specific
    task context where the methodology proved useful.
    """
    refinements: list[str] = []
    problem_lower = methodology.problem_description.lower()
    task_lower = task_description.lower()

    # Derive context-specific directive from task type
    mtype = (methodology.methodology_type or "").upper()
    if mtype == "BUG_FIX":
        # Refine: specify what kind of bug and where
        refinements.append(
            f"Apply as bug-fix pattern when encountering: "
            f"'{methodology.problem_description[:100]}'"
        )
    elif mtype == "PATTERN":
        refinements.append(
            f"Apply as reusable pattern for: "
            f"'{methodology.problem_description[:100]}'"
        )
    elif mtype == "GOTCHA":
        refinements.append(
            f"Guard against: '{methodology.problem_description[:100]}'"
        )

    # Derive from activation triggers that matched the task
    if cap_data:
        for trigger in cap_data.activation_triggers:
            trigger_tokens = _tokenize(trigger)
            overlap = _keyword_overlap(trigger_tokens, task_tokens)
            if overlap:
                refinements.append(
                    f"Activate when task involves: {trigger}"
                )

        # From capability_type
        ctype = cap_data.capability_type
        if ctype == "transformation":
            refinements.append(
                "Use as a transformation step: feed input, expect structured output"
            )
        elif ctype == "analysis":
            refinements.append(
                "Use as an analysis lens: apply to codebase/data to extract insights"
            )
        elif ctype == "generation":
            refinements.append(
                "Use as a generator: produces new artifacts from specifications"
            )
        elif ctype == "validation":
            refinements.append(
                "Use as a validation gate: check artifacts against criteria"
            )

    # From the task description itself -- what concrete scenario triggered use
    if outcome_notes:
        outcome_first_sentence = outcome_notes.split(".")[0].strip()
        if len(outcome_first_sentence) > 10:
            refinements.append(
                f"Proven effective in context: '{outcome_first_sentence[:150]}'"
            )

    # Language-specific directive
    if methodology.language:
        refinements.append(
            f"Applicable in {methodology.language} codebases"
        )

    # Tag-derived directives
    tag_families: set[str] = set()
    for tag in methodology.tags:
        family = _TAG_TO_FAMILY.get(tag.lower())
        if family:
            tag_families.add(family)
    if tag_families:
        refinements.append(
            f"Relevant domains: {', '.join(sorted(tag_families))}"
        )

    return refinements


# ---------------------------------------------------------------------------
# Batch extraction
# ---------------------------------------------------------------------------

def batch_extract(
    methodologies: list[Methodology],
    task_description: str,
    task_id: str = "",
    outcome_notes: str = "",
) -> list[CapabilityDiscovery]:
    """Extract capability discoveries from multiple methodologies applied in a single task.

    This is the batch entry point for post-task LCDE analysis. Each methodology
    gets its own CapabilityDiscovery record.

    Args:
        methodologies: All methodologies that contributed to the task outcome.
        task_description: Full text of the completed task.
        task_id: Task identifier for linking.
        outcome_notes: Optional approach summary or outcome notes.

    Returns:
        List of CapabilityDiscovery records, one per methodology.
    """
    discoveries: list[CapabilityDiscovery] = []
    for meth in methodologies:
        try:
            discovery = extract_capabilities(
                methodology=meth,
                task_description=task_description,
                task_id=task_id,
                outcome_notes=outcome_notes,
            )
            discoveries.append(discovery)
            logger.debug(
                "LCDE extracted %d capabilities, %d adjacent tasks, %d gaps for methodology %s",
                len(discovery.discovered_capabilities),
                len(discovery.adjacent_tasks),
                len(discovery.knowledge_gaps),
                meth.id,
            )
        except Exception as exc:
            logger.warning(
                "LCDE extraction failed for methodology %s: %s",
                meth.id, exc,
            )
    return discoveries


# ---------------------------------------------------------------------------
# Methodology directive update
# ---------------------------------------------------------------------------

def update_methodology_directives(
    methodology: Methodology,
    discovery: CapabilityDiscovery,
) -> Methodology:
    """Update a methodology's use_immediately_as list with refined directives from LCDE.

    Merges (does NOT replace) existing directives with new refinements.
    Deduplicates by normalized text comparison.

    Args:
        methodology: The methodology to update (will be mutated).
        discovery: The LCDE extraction results containing use_refinements.

    Returns:
        The same methodology instance with updated use_immediately_as.
    """
    existing = list(methodology.use_immediately_as)
    new_refinements = discovery.use_refinements

    # Normalize for dedup: lowercase, strip, collapse whitespace
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text.strip().lower())

    existing_normalized: set[str] = {_normalize(d) for d in existing}

    merged: list[str] = list(existing)
    for refinement in new_refinements:
        norm = _normalize(refinement)
        if norm not in existing_normalized:
            merged.append(refinement)
            existing_normalized.add(norm)

    methodology.use_immediately_as = merged
    return methodology


# ---------------------------------------------------------------------------
# Summary / reporting helper
# ---------------------------------------------------------------------------

def summarize_discoveries(discoveries: list[CapabilityDiscovery]) -> dict[str, Any]:
    """Create a summary report from a batch of LCDE discoveries.

    Useful for logging, dashboards, and post-task reports.

    Returns:
        Dictionary with aggregate counts and merged lists.
    """
    total_capabilities = 0
    total_adjacent = 0
    total_gaps = 0
    total_refinements = 0
    all_gaps: list[str] = []
    all_adjacent: list[str] = []

    for d in discoveries:
        total_capabilities += len(d.discovered_capabilities)
        total_adjacent += len(d.adjacent_tasks)
        total_gaps += len(d.knowledge_gaps)
        total_refinements += len(d.use_refinements)
        all_gaps.extend(d.knowledge_gaps)
        all_adjacent.extend(d.adjacent_tasks)

    # Deduplicate adjacent tasks and gaps across methodologies
    unique_gaps = list(dict.fromkeys(all_gaps))
    unique_adjacent = list(dict.fromkeys(all_adjacent))

    return {
        "methodologies_analyzed": len(discoveries),
        "total_capabilities_discovered": total_capabilities,
        "total_adjacent_tasks": total_adjacent,
        "unique_adjacent_tasks": len(unique_adjacent),
        "total_knowledge_gaps": total_gaps,
        "unique_knowledge_gaps": len(unique_gaps),
        "total_use_refinements": total_refinements,
        "knowledge_gaps": unique_gaps,
        "adjacent_tasks": unique_adjacent,
    }
