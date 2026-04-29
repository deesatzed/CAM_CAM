"""Scenario-Anchored Enrichment -- grounded directive generation from existing KB.

Generates target scenarios from task history, action templates, component gaps,
capability chains, stigmergic links, and coverage gaps. New methodologies are
scored against these scenarios to produce specific, grounded directives instead
of generic "Apply when cross_domain_reuse" style text.

Architecture:
    1. ScenarioBuilder  -- mines KB data to auto-generate scenarios
    2. ScenarioScorer   -- cosine + structural scoring of methodology vs scenarios
    3. DirectiveWriter  -- produces grounded directives from top scenario matches
    4. ScenarioEnricher -- orchestrates build -> score -> write for a methodology
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Optional

from claw.core.models import ActionTemplate, ComponentCard, Methodology

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    """A target use-case scenario derived from existing KB data."""

    id: str
    description: str
    derived_from: str  # e.g. "task_history", "action_template", "component_gap", "capability_chain", "coverage_gap"
    source_ids: list[str] = field(default_factory=list)  # IDs of KB items that generated this scenario
    anchor_methodology_ids: list[str] = field(default_factory=list)  # related existing methodologies
    domains: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    embedding: list[float] = field(default_factory=list)


@dataclass
class ScenarioMatch:
    """Result of scoring a methodology against a scenario."""

    scenario: Scenario
    cosine_score: float = 0.0
    composability_score: float = 0.0
    domain_overlap_score: float = 0.0
    keyword_overlap_score: float = 0.0
    composite_score: float = 0.0


@dataclass
class EnrichmentResult:
    """Output of scenario-anchored enrichment for a single methodology."""

    methodology_id: str
    directives: list[str] = field(default_factory=list)
    tension_questions: list[str] = field(default_factory=list)
    top_scenarios: list[ScenarioMatch] = field(default_factory=list)
    bandit_prior_boost: float = 0.0


# ---------------------------------------------------------------------------
# ScenarioBuilder: mines KB to generate scenarios
# ---------------------------------------------------------------------------


class ScenarioBuilder:
    """Builds target scenarios from existing KB data sources."""

    def build_from_task_history(
        self,
        task_categories: dict[str, int],
        methodologies: list[Methodology],
    ) -> list[Scenario]:
        """Generate scenarios from task history category distribution.

        For each task category with >= 2 occurrences, generate a scenario
        describing the typical work pattern for that category.
        """
        scenarios: list[Scenario] = []
        category_meths: dict[str, list[str]] = {}

        for m in methodologies:
            for tag in m.tags:
                if tag.startswith("category:"):
                    cat = tag.split(":", 1)[1]
                    category_meths.setdefault(cat, []).append(m.id)

        for category, count in sorted(task_categories.items(), key=lambda x: -x[1]):
            if count < 2:
                continue

            anchor_ids = category_meths.get(category, [])[:5]
            scenario = Scenario(
                id=f"task_hist_{category}",
                description=(
                    f"When working on {category} tasks: apply proven patterns "
                    f"from {count} prior task(s) in this domain. "
                    f"Focus on reusing existing methodologies for {category} challenges."
                ),
                derived_from="task_history",
                source_ids=[],
                anchor_methodology_ids=anchor_ids,
                domains=[category],
                keywords=_category_keywords(category),
            )
            scenarios.append(scenario)

        return scenarios

    def build_from_action_templates(
        self,
        templates: list[ActionTemplate],
    ) -> list[Scenario]:
        """Generate scenarios from action template problem patterns.

        Each action template encodes a reusable runbook for a known problem
        pattern -- this is a scenario the system already knows how to handle.
        """
        scenarios: list[Scenario] = []

        for tmpl in templates:
            keywords = _extract_keywords(tmpl.problem_pattern)
            scenario = Scenario(
                id=f"tmpl_{tmpl.id[:12]}",
                description=(
                    f"When encountering: {tmpl.problem_pattern[:200]}. "
                    f"Runbook '{tmpl.title}' exists with {len(tmpl.execution_steps)} "
                    f"execution steps (confidence: {tmpl.confidence:.2f})."
                ),
                derived_from="action_template",
                source_ids=[tmpl.id],
                anchor_methodology_ids=[tmpl.source_methodology_id] if tmpl.source_methodology_id else [],
                domains=[],
                keywords=keywords,
            )
            scenarios.append(scenario)

        return scenarios

    def build_from_component_gaps(
        self,
        component_type_counts: dict[str, int],
        all_component_types: list[str],
    ) -> list[Scenario]:
        """Generate scenarios from component type coverage gaps.

        If certain component types are under-represented, generate scenarios
        requesting methodologies that could fill those gaps.
        """
        scenarios: list[Scenario] = []

        # Standard component types that a healthy KB should cover
        expected_types = {
            "validator", "parser", "serializer", "auth_client",
            "queue_worker", "cache_layer", "rate_limiter", "retry_handler",
            "config_helper", "test_fixture", "error_handler", "middleware",
            "transformer", "aggregator", "monitor", "scheduler",
        }

        covered = set(component_type_counts.keys())
        uncovered = expected_types - covered

        for comp_type in sorted(uncovered):
            scenario = Scenario(
                id=f"comp_gap_{comp_type}",
                description=(
                    f"No {comp_type} components exist in the knowledge base. "
                    f"Methodologies that teach how to build or use {comp_type} "
                    f"patterns are high value for filling this capability gap."
                ),
                derived_from="component_gap",
                source_ids=[],
                anchor_methodology_ids=[],
                domains=[],
                keywords=[comp_type, comp_type.replace("_", " ")],
            )
            scenarios.append(scenario)

        # Also flag under-represented types (count < median/2)
        if component_type_counts:
            counts = list(component_type_counts.values())
            median_count = sorted(counts)[len(counts) // 2]
            threshold = max(2, median_count // 2)

            for comp_type, count in component_type_counts.items():
                if count < threshold and comp_type not in uncovered:
                    scenario = Scenario(
                        id=f"comp_weak_{comp_type}",
                        description=(
                            f"Only {count} {comp_type} component(s) exist. "
                            f"Additional {comp_type} methodologies would strengthen this area."
                        ),
                        derived_from="component_gap",
                        source_ids=[],
                        anchor_methodology_ids=[],
                        domains=[],
                        keywords=[comp_type, comp_type.replace("_", " ")],
                    )
                    scenarios.append(scenario)

        return scenarios

    def build_from_capability_chains(
        self,
        methodologies: list[Methodology],
    ) -> list[Scenario]:
        """Generate scenarios from capability composability data.

        Looks for methodologies that declare can_chain_after or can_chain_before
        and generates scenarios for those composition patterns.
        """
        scenarios: list[Scenario] = []
        seen_chain_patterns: set[str] = set()

        for m in methodologies:
            cap = m.capability_data or {}
            composability = cap.get("composability", {})
            if not isinstance(composability, dict):
                continue

            chain_after = composability.get("can_chain_after", [])
            chain_before = composability.get("can_chain_before", [])
            domains = cap.get("domain", [])

            if not chain_after and not chain_before:
                continue

            # Build scenario for this chain pattern
            chain_key = f"{sorted(chain_after)}_{sorted(chain_before)}"
            if chain_key in seen_chain_patterns:
                continue
            seen_chain_patterns.add(chain_key)

            parts: list[str] = []
            if chain_after:
                after_str = ", ".join(str(c) for c in chain_after[:3])
                parts.append(f"chains after [{after_str}]")
            if chain_before:
                before_str = ", ".join(str(c) for c in chain_before[:3])
                parts.append(f"feeds into [{before_str}]")

            chain_desc = " and ".join(parts)
            problem_snippet = m.problem_description[:100]

            scenario = Scenario(
                id=f"chain_{m.id[:12]}",
                description=(
                    f"Composability pattern: methodology that {chain_desc}. "
                    f"Based on '{problem_snippet}'. "
                    f"New methodologies matching this chain pattern can be composed together."
                ),
                derived_from="capability_chain",
                source_ids=[m.id],
                anchor_methodology_ids=[m.id],
                domains=domains if isinstance(domains, list) else [],
                keywords=_extract_keywords(m.problem_description),
            )
            scenarios.append(scenario)

        return scenarios

    def build_from_stigmergic_links(
        self,
        co_retrieval_pairs: list[dict[str, Any]],
        methodologies_by_id: dict[str, Methodology],
    ) -> list[Scenario]:
        """Generate scenarios from stigmergic co-retrieval patterns.

        If methodology A and B are frequently co-retrieved, new methodologies
        that bridge or extend that pair are high value.
        """
        scenarios: list[Scenario] = []

        for pair in co_retrieval_pairs[:20]:  # Top 20 strongest links
            source_id = pair.get("source_id", "")
            target_id = pair.get("target_id", "")
            strength = pair.get("strength", 0.0)

            source_m = methodologies_by_id.get(source_id)
            target_m = methodologies_by_id.get(target_id)

            if not source_m or not target_m:
                continue

            source_desc = source_m.problem_description[:80]
            target_desc = target_m.problem_description[:80]

            # Combine domains from both
            source_domains = (source_m.capability_data or {}).get("domain", [])
            target_domains = (target_m.capability_data or {}).get("domain", [])
            combined_domains = list(set(
                (source_domains if isinstance(source_domains, list) else []) +
                (target_domains if isinstance(target_domains, list) else [])
            ))

            scenario = Scenario(
                id=f"coret_{source_id[:8]}_{target_id[:8]}",
                description=(
                    f"Co-retrieval pattern (strength={strength:.1f}): "
                    f"'{source_desc}' is often used alongside '{target_desc}'. "
                    f"Methodologies that bridge, extend, or complement this pair "
                    f"are predicted to be high-value."
                ),
                derived_from="stigmergic_link",
                source_ids=[source_id, target_id],
                anchor_methodology_ids=[source_id, target_id],
                domains=combined_domains,
                keywords=(
                    _extract_keywords(source_m.problem_description) +
                    _extract_keywords(target_m.problem_description)
                ),
            )
            scenarios.append(scenario)

        return scenarios

    def build_from_coverage_gaps(
        self,
        domain_distribution: dict[str, int],
    ) -> list[Scenario]:
        """Generate scenarios from domain coverage gaps.

        Domains with very few methodologies are under-served and should be
        prioritized in mining.
        """
        scenarios: list[Scenario] = []

        if not domain_distribution:
            return scenarios

        counts = list(domain_distribution.values())
        median_count = sorted(counts)[len(counts) // 2] if counts else 0
        threshold = max(2, median_count // 3)

        for domain, count in domain_distribution.items():
            if count <= threshold:
                scenario = Scenario(
                    id=f"cov_gap_{domain}",
                    description=(
                        f"Domain '{domain}' has only {count} methodology(ies). "
                        f"This is under-represented relative to other domains. "
                        f"New methodologies in '{domain}' are high priority."
                    ),
                    derived_from="coverage_gap",
                    source_ids=[],
                    anchor_methodology_ids=[],
                    domains=[domain],
                    keywords=[domain, domain.replace("_", " ")],
                )
                scenarios.append(scenario)

        return scenarios

    def build_from_contradiction_signals(
        self,
        contradictions: list[dict[str, Any]],
        methodologies_by_id: dict[str, Methodology],
    ) -> list[Scenario]:
        """Generate scenarios from detected contradiction pairs.

        When two methodologies contradict, a new methodology that resolves
        or contextualizes the contradiction is valuable.
        """
        scenarios: list[Scenario] = []

        for contra in contradictions[:10]:
            a_id = contra.get("cap_a_id", "")
            b_id = contra.get("cap_b_id", "")
            details = contra.get("details", {})

            a_m = methodologies_by_id.get(a_id)
            b_m = methodologies_by_id.get(b_id)

            if not a_m or not b_m:
                continue

            a_desc = a_m.problem_description[:80]
            b_desc = b_m.problem_description[:80]
            conflict_type = details.get("conflict_type", "unknown") if isinstance(details, dict) else "unknown"

            scenario = Scenario(
                id=f"contra_{a_id[:8]}_{b_id[:8]}",
                description=(
                    f"Contradiction ({conflict_type}): '{a_desc}' conflicts with "
                    f"'{b_desc}'. Methodologies that resolve, contextualize, or "
                    f"clarify when each applies are high value."
                ),
                derived_from="contradiction",
                source_ids=[a_id, b_id],
                anchor_methodology_ids=[a_id, b_id],
                domains=[],
                keywords=_extract_keywords(a_m.problem_description) + _extract_keywords(b_m.problem_description),
            )
            scenarios.append(scenario)

        return scenarios


# ---------------------------------------------------------------------------
# ScenarioScorer: structural + embedding similarity
# ---------------------------------------------------------------------------


class ScenarioScorer:
    """Scores a methodology against a set of scenarios."""

    def score(
        self,
        methodology: Methodology,
        scenarios: list[Scenario],
        methodology_embedding: list[float] | None = None,
    ) -> list[ScenarioMatch]:
        """Score methodology against all scenarios and return sorted matches.

        Scoring dimensions:
            - cosine_score: embedding similarity (if embeddings available)
            - composability_score: input/output chain compatibility
            - domain_overlap_score: shared domain tags
            - keyword_overlap_score: shared keywords from text
        """
        matches: list[ScenarioMatch] = []
        meth_domains = set(self._get_domains(methodology))
        meth_keywords = set(_extract_keywords(methodology.problem_description))
        meth_chains = self._get_chain_labels(methodology)

        for scenario in scenarios:
            match = ScenarioMatch(scenario=scenario)

            # Cosine similarity (embedding-based)
            if methodology_embedding and scenario.embedding:
                match.cosine_score = _cosine_similarity(
                    methodology_embedding, scenario.embedding
                )

            # Domain overlap
            scenario_domains = set(scenario.domains)
            if meth_domains and scenario_domains:
                intersection = meth_domains & scenario_domains
                union = meth_domains | scenario_domains
                match.domain_overlap_score = len(intersection) / max(len(union), 1)

            # Keyword overlap
            scenario_keywords = set(scenario.keywords)
            if meth_keywords and scenario_keywords:
                intersection = meth_keywords & scenario_keywords
                union = meth_keywords | scenario_keywords
                match.keyword_overlap_score = len(intersection) / max(len(union), 1)

            # Composability match
            match.composability_score = self._composability_match(
                meth_chains, scenario
            )

            # Composite: weighted average
            match.composite_score = (
                0.35 * match.cosine_score
                + 0.20 * match.composability_score
                + 0.25 * match.domain_overlap_score
                + 0.20 * match.keyword_overlap_score
            )

            matches.append(match)

        matches.sort(key=lambda m: m.composite_score, reverse=True)
        return matches

    def _get_domains(self, methodology: Methodology) -> list[str]:
        cap = methodology.capability_data or {}
        domains = cap.get("domain", [])
        # Also extract category from tags
        for tag in methodology.tags:
            if tag.startswith("category:"):
                domains.append(tag.split(":", 1)[1])
        return domains if isinstance(domains, list) else []

    def _get_chain_labels(self, methodology: Methodology) -> dict[str, list[str]]:
        cap = methodology.capability_data or {}
        composability = cap.get("composability", {})
        if not isinstance(composability, dict):
            return {"after": [], "before": []}
        return {
            "after": composability.get("can_chain_after", []),
            "before": composability.get("can_chain_before", []),
        }

    def _composability_match(
        self,
        meth_chains: dict[str, list[str]],
        scenario: Scenario,
    ) -> float:
        """Score composability fit between methodology and scenario anchors.

        If the methodology's chain labels overlap with the scenario's anchor
        methodologies' known outputs/inputs, they can compose.
        """
        if not scenario.anchor_methodology_ids:
            return 0.0

        # Check if methodology mentions any anchor IDs in its chain labels
        anchor_set = set(scenario.anchor_methodology_ids)
        chain_after = set(str(c) for c in meth_chains.get("after", []))
        chain_before = set(str(c) for c in meth_chains.get("before", []))

        # Direct ID match
        direct_overlap = (chain_after | chain_before) & anchor_set
        if direct_overlap:
            return min(1.0, len(direct_overlap) * 0.5)

        # Keyword-based composability: check if scenario keywords appear
        # in the methodology's chain labels (softer signal)
        if scenario.keywords and (chain_after or chain_before):
            all_chains = chain_after | chain_before
            chain_text = " ".join(all_chains).lower()
            keyword_hits = sum(
                1 for kw in scenario.keywords
                if kw.lower() in chain_text
            )
            return min(0.5, keyword_hits * 0.15)

        return 0.0


# ---------------------------------------------------------------------------
# DirectiveWriter: generates grounded directives from scenario matches
# ---------------------------------------------------------------------------


class DirectiveWriter:
    """Produces grounded, specific directives from top scenario matches."""

    def write_directives(
        self,
        methodology: Methodology,
        top_matches: list[ScenarioMatch],
        existing_methodologies_by_id: dict[str, Methodology] | None = None,
    ) -> list[str]:
        """Generate grounded use-immediately directives from scenario matches.

        Each directive references specific scenarios, anchor methodologies,
        and composability patterns rather than generic keywords.
        """
        directives: list[str] = []
        existing = existing_methodologies_by_id or {}

        for match in top_matches[:5]:  # Top 5 scenario matches
            if match.composite_score < 0.10:
                continue

            scenario = match.scenario
            directive = self._directive_for_scenario(
                methodology, scenario, match, existing
            )
            if directive:
                directives.append(directive)

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for d in directives:
            normalized = d.strip().lower()
            if normalized not in seen:
                seen.add(normalized)
                unique.append(d.strip())

        return unique[:5]

    def write_tension_questions(
        self,
        methodology: Methodology,
        top_matches: list[ScenarioMatch],
        existing_methodologies_by_id: dict[str, Methodology] | None = None,
    ) -> list[str]:
        """Generate grounded tension questions from scenario matches.

        Questions reference specific existing knowledge and composability
        rather than generic epistemic probes.
        """
        questions: list[str] = []
        existing = existing_methodologies_by_id or {}

        # Q1: Contradiction-aware question
        contra_matches = [
            m for m in top_matches
            if m.scenario.derived_from == "contradiction" and m.composite_score >= 0.10
        ]
        if contra_matches:
            contra = contra_matches[0].scenario
            anchor_descs = []
            for aid in contra.anchor_methodology_ids[:2]:
                am = existing.get(aid)
                if am:
                    anchor_descs.append(am.problem_description[:60])
            if anchor_descs:
                questions.append(
                    f"This methodology may conflict with existing knowledge: "
                    f"'{anchor_descs[0]}'. Which approach is correct for "
                    f"the current context, and why?"
                )

        # Q2: Composability question
        chain_matches = [
            m for m in top_matches
            if m.scenario.derived_from == "capability_chain" and m.composite_score >= 0.10
        ]
        if chain_matches:
            chain = chain_matches[0].scenario
            anchor_ids = chain.anchor_methodology_ids[:1]
            if anchor_ids:
                anchor_m = existing.get(anchor_ids[0])
                if anchor_m:
                    questions.append(
                        f"Can this methodology be chained with "
                        f"'{anchor_m.problem_description[:60]}'? "
                        f"If so, what is the expected input/output contract?"
                    )

        # Q3: Gap-filling question
        gap_matches = [
            m for m in top_matches
            if m.scenario.derived_from in ("component_gap", "coverage_gap")
            and m.composite_score >= 0.10
        ]
        if gap_matches:
            gap = gap_matches[0].scenario
            questions.append(
                f"This methodology addresses a KB gap: {gap.description[:80]}. "
                f"Is the coverage sufficient, or are additional patterns needed?"
            )

        # Q4: Co-retrieval prediction question
        coret_matches = [
            m for m in top_matches
            if m.scenario.derived_from == "stigmergic_link" and m.composite_score >= 0.10
        ]
        if coret_matches:
            coret = coret_matches[0].scenario
            questions.append(
                f"Based on co-retrieval patterns, this methodology will likely "
                f"be retrieved alongside existing knowledge. "
                f"Does it complement or duplicate that knowledge?"
            )

        # Fallback if no scenario-specific questions
        if not questions:
            questions.append(
                "What existing knowledge in the KB does this methodology "
                "extend, replace, or contradict?"
            )
            if methodology.accuracy_contract in ("hard", "frontier"):
                questions.append(
                    "Has this pattern been validated beyond its source repository, "
                    "or is it a single-observation extrapolation?"
                )

        return questions[:3]

    def _directive_for_scenario(
        self,
        methodology: Methodology,
        scenario: Scenario,
        match: ScenarioMatch,
        existing: dict[str, Methodology],
    ) -> str | None:
        """Generate a single grounded directive for a scenario match."""

        if scenario.derived_from == "task_history":
            domain = scenario.domains[0] if scenario.domains else "this domain"
            return (
                f"Apply when working on {domain} tasks. "
                f"This pattern matches {len(scenario.anchor_methodology_ids)} "
                f"existing methodologies in this category."
            )

        if scenario.derived_from == "action_template":
            return (
                f"Use as part of runbook '{scenario.description[:60]}'. "
                f"Combine with existing execution steps for validated workflow."
            )

        if scenario.derived_from == "capability_chain":
            # Reference the actual anchor methodology by name
            for aid in scenario.anchor_methodology_ids[:1]:
                anchor = existing.get(aid)
                if anchor:
                    anchor_name = anchor.problem_description[:60]
                    return (
                        f"Chain after '{anchor_name}' when building "
                        f"the composability pipeline described in this scenario."
                    )
            return None

        if scenario.derived_from == "component_gap":
            return (
                f"This fills a KB gap: {scenario.description[:80]}. "
                f"Prioritize for immediate use in relevant tasks."
            )

        if scenario.derived_from == "coverage_gap":
            domain = scenario.domains[0] if scenario.domains else "this area"
            return (
                f"High-priority: {domain} is under-represented in the KB. "
                f"This methodology adds needed coverage."
            )

        if scenario.derived_from == "stigmergic_link":
            # Reference co-retrieved pair
            anchor_descs = []
            for aid in scenario.anchor_methodology_ids[:2]:
                am = existing.get(aid)
                if am:
                    anchor_descs.append(am.problem_description[:50])
            if anchor_descs:
                return (
                    f"Predicted co-retrieval with: '{anchor_descs[0]}'. "
                    f"Retrieve together for combined effect."
                )
            return None

        if scenario.derived_from == "contradiction":
            return (
                f"Context-dependent: may conflict with existing knowledge. "
                f"Apply only when scenario conditions match."
            )

        return None

    def compute_bandit_prior_boost(
        self,
        top_matches: list[ScenarioMatch],
    ) -> float:
        """Compute a bandit prior boost based on scenario fit.

        Higher scenario fit means the methodology is more likely to be
        useful in known task patterns, so it gets a positive prior for
        Thompson sampling / epsilon-greedy selection.

        Returns a boost in [0.0, 0.5] to add to the methodology's base prior.
        """
        if not top_matches:
            return 0.0

        # Average composite score of top 3 matches
        top_scores = [m.composite_score for m in top_matches[:3]]
        avg_score = sum(top_scores) / max(len(top_scores), 1)

        # Scale to [0, 0.5] range with diminishing returns
        return min(0.5, avg_score * 0.6)


# ---------------------------------------------------------------------------
# ScenarioEnricher: top-level orchestrator
# ---------------------------------------------------------------------------


class ScenarioEnricher:
    """Orchestrates scenario generation, scoring, and directive writing.

    Usage:
        enricher = ScenarioEnricher()
        scenarios = await enricher.build_scenarios(repository)
        result = enricher.enrich(methodology, scenarios, embedding_engine)
    """

    def __init__(self) -> None:
        self.builder = ScenarioBuilder()
        self.scorer = ScenarioScorer()
        self.writer = DirectiveWriter()
        self._cached_scenarios: list[Scenario] | None = None
        self._cached_meths_by_id: dict[str, Methodology] | None = None

    async def build_scenarios(
        self,
        repository: Any,  # Repository type from claw.db.repository
        embedding_engine: Any | None = None,  # EmbeddingEngine
    ) -> list[Scenario]:
        """Build scenarios from all KB data sources.

        This is the expensive step -- call once per mining session, not per
        methodology. Results are cached on the enricher instance.
        """
        scenarios: list[Scenario] = []

        # 1. Gather KB data
        methodologies = await repository.list_methodologies(limit=500)
        meths_by_id = {m.id: m for m in methodologies}
        self._cached_meths_by_id = meths_by_id

        # Task category distribution from methodology tags
        task_categories: dict[str, int] = {}
        for m in methodologies:
            for tag in m.tags:
                if tag.startswith("category:"):
                    cat = tag.split(":", 1)[1]
                    task_categories[cat] = task_categories.get(cat, 0) + 1

        # Action templates
        try:
            action_templates = await repository.list_action_templates(limit=50)
        except Exception:
            action_templates = []

        # Domain distribution
        try:
            domain_dist = await repository.get_domain_distribution()
        except Exception:
            domain_dist = {}

        # Component type counts
        component_type_counts: dict[str, int] = {}
        try:
            cap_meths = await repository.get_methodologies_with_capabilities(limit=500)
            for m in cap_meths:
                cap = m.capability_data or {}
                ctype = cap.get("capability_type", "")
                if ctype:
                    component_type_counts[ctype] = component_type_counts.get(ctype, 0) + 1
        except Exception:
            pass

        # Co-retrieval links (top by strength)
        co_retrieval_pairs: list[dict[str, Any]] = []
        try:
            rows = await repository.engine.fetch_all(
                """SELECT source_id, target_id, strength
                   FROM methodology_links
                   WHERE link_type = 'co_retrieval'
                   ORDER BY strength DESC
                   LIMIT 30"""
            )
            co_retrieval_pairs = [dict(r) for r in rows]
        except Exception:
            pass

        # Contradictions (from synergy exploration with conflict result)
        contradictions: list[dict[str, Any]] = []
        try:
            rows = await repository.engine.fetch_all(
                """SELECT cap_a_id, cap_b_id, details
                   FROM synergy_exploration_log
                   WHERE result = 'contradiction'
                   ORDER BY synergy_score DESC
                   LIMIT 20"""
            )
            contradictions = [dict(r) for r in rows]
        except Exception:
            pass

        # 2. Build scenarios from each source
        scenarios.extend(
            self.builder.build_from_task_history(task_categories, methodologies)
        )
        scenarios.extend(
            self.builder.build_from_action_templates(action_templates)
        )
        scenarios.extend(
            self.builder.build_from_component_gaps(
                component_type_counts,
                list(component_type_counts.keys()),
            )
        )
        scenarios.extend(
            self.builder.build_from_capability_chains(methodologies)
        )
        scenarios.extend(
            self.builder.build_from_stigmergic_links(co_retrieval_pairs, meths_by_id)
        )
        scenarios.extend(
            self.builder.build_from_coverage_gaps(domain_dist)
        )
        scenarios.extend(
            self.builder.build_from_contradiction_signals(contradictions, meths_by_id)
        )

        # 3. Embed scenarios (if embedding engine available)
        if embedding_engine is not None:
            texts = [s.description for s in scenarios]
            if texts:
                try:
                    embeddings = embedding_engine.encode_batch(texts)
                    for scenario, emb in zip(scenarios, embeddings):
                        scenario.embedding = emb
                except Exception as e:
                    logger.warning("Failed to embed scenarios: %s", e)

        logger.info(
            "Built %d scenarios: %s",
            len(scenarios),
            {
                s.derived_from
                for s in scenarios
            },
        )

        self._cached_scenarios = scenarios
        return scenarios

    def enrich(
        self,
        methodology: Methodology,
        scenarios: list[Scenario] | None = None,
        methodology_embedding: list[float] | None = None,
        existing_methodologies_by_id: dict[str, Methodology] | None = None,
    ) -> EnrichmentResult:
        """Enrich a single methodology with scenario-grounded directives.

        This is the fast path -- called per methodology during store_finding.
        Uses cached scenarios from build_scenarios().
        """
        active_scenarios = scenarios or self._cached_scenarios or []
        meths_by_id = existing_methodologies_by_id or self._cached_meths_by_id or {}

        if not active_scenarios:
            logger.debug("No scenarios available for enrichment")
            return EnrichmentResult(methodology_id=methodology.id)

        # Score methodology against all scenarios
        matches = self.scorer.score(
            methodology,
            active_scenarios,
            methodology_embedding=methodology_embedding,
        )

        # Filter to meaningful matches
        meaningful = [m for m in matches if m.composite_score >= 0.05]

        # Generate grounded directives
        directives = self.writer.write_directives(
            methodology, meaningful, meths_by_id
        )

        # Generate grounded tension questions
        tension_questions = self.writer.write_tension_questions(
            methodology, meaningful, meths_by_id
        )

        # Compute bandit prior boost
        bandit_boost = self.writer.compute_bandit_prior_boost(meaningful)

        return EnrichmentResult(
            methodology_id=methodology.id,
            directives=directives,
            tension_questions=tension_questions,
            top_scenarios=meaningful[:5],
            bandit_prior_boost=bandit_boost,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from text for overlap matching."""
    if not text:
        return []

    # Lowercase, split on non-alphanumeric
    import re
    tokens = re.findall(r"[a-z][a-z0-9_]+", text.lower())

    # Filter stopwords and very short tokens
    stopwords = {
        "the", "and", "for", "with", "this", "that", "from", "have", "has",
        "are", "was", "were", "been", "being", "not", "but", "can", "will",
        "should", "would", "could", "may", "might", "shall", "into", "over",
        "under", "about", "than", "then", "also", "each", "every", "both",
        "few", "more", "most", "other", "some", "such", "only", "same",
        "when", "where", "which", "while", "after", "before", "during",
        "between", "through", "using", "used", "use", "very", "just",
    }

    keywords = [t for t in tokens if len(t) >= 3 and t not in stopwords]

    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)

    return unique[:20]


def _category_keywords(category: str) -> list[str]:
    """Map a task/methodology category to expected keywords."""
    keyword_map: dict[str, list[str]] = {
        "architecture": ["pattern", "design", "structure", "module", "component", "layer", "interface"],
        "ai_integration": ["llm", "model", "prompt", "embedding", "agent", "inference", "token"],
        "code_quality": ["lint", "format", "convention", "style", "refactor", "clean", "naming"],
        "security": ["auth", "token", "permission", "encrypt", "secret", "sanitize", "inject"],
        "testing": ["test", "assert", "fixture", "mock", "coverage", "integration", "unit"],
        "performance": ["cache", "optimize", "latency", "throughput", "memory", "batch", "async"],
        "error_handling": ["error", "exception", "retry", "fallback", "circuit", "recovery", "resilience"],
        "data_management": ["database", "query", "migration", "schema", "index", "storage", "persistence"],
        "devops": ["deploy", "pipeline", "container", "docker", "kubernetes", "monitor", "log"],
        "api_design": ["endpoint", "rest", "graphql", "schema", "validation", "versioning", "rate"],
    }
    return keyword_map.get(category, [category.replace("_", " ")])


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors without numpy dependency."""
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot / (norm_a * norm_b)
