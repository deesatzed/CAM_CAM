"""Tests for the Scenario-Anchored Enrichment system.

Uses real Methodology/ActionTemplate data structures -- no mocks.
"""

from __future__ import annotations

import math

import pytest

from claw.core.models import ActionTemplate, Methodology
from claw.scenario_enrichment import (
    DirectiveWriter,
    EnrichmentResult,
    Scenario,
    ScenarioBuilder,
    ScenarioMatch,
    ScenarioScorer,
    _cosine_similarity,
    _extract_keywords,
)


# ---------------------------------------------------------------------------
# Fixtures: real data structures
# ---------------------------------------------------------------------------


def _make_methodology(
    mid: str = "m-001",
    problem: str = "Implement retry logic with exponential backoff",
    solution: str = "Use async retry with jitter",
    tags: list[str] | None = None,
    category: str = "error_handling",
    capability_data: dict | None = None,
    accuracy_contract: str = "soft",
    novelty_score: float | None = None,
) -> Methodology:
    tags = tags or ["mined", f"source:test-repo", f"category:{category}"]
    cap = capability_data or {
        "domain": [category],
        "composability": {
            "can_chain_after": [],
            "can_chain_before": [],
            "standalone": True,
        },
        "capability_type": "transformation",
    }
    return Methodology(
        id=mid,
        problem_description=problem,
        solution_code=solution,
        tags=tags,
        capability_data=cap,
        accuracy_contract=accuracy_contract,
        novelty_score=novelty_score,
    )


def _make_template(
    tid: str = "t-001",
    title: str = "Retry Handler Runbook",
    problem_pattern: str = "Service calls fail intermittently due to transient errors",
    source_methodology_id: str = "m-001",
    confidence: float = 0.8,
) -> ActionTemplate:
    return ActionTemplate(
        id=tid,
        title=title,
        problem_pattern=problem_pattern,
        execution_steps=["1. Wrap call in retry decorator", "2. Set max_retries=3"],
        acceptance_checks=["Verify retry count in logs"],
        source_methodology_id=source_methodology_id,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# ScenarioBuilder tests
# ---------------------------------------------------------------------------


class TestScenarioBuilder:
    def test_build_from_task_history(self):
        builder = ScenarioBuilder()
        categories = {"architecture": 5, "error_handling": 3, "rare_category": 1}
        meths = [
            _make_methodology("m1", category="architecture"),
            _make_methodology("m2", category="architecture"),
            _make_methodology("m3", category="error_handling"),
        ]

        scenarios = builder.build_from_task_history(categories, meths)

        # Should only include categories with count >= 2
        ids = [s.id for s in scenarios]
        assert "task_hist_architecture" in ids
        assert "task_hist_error_handling" in ids
        assert "task_hist_rare_category" not in ids

        arch_scenario = next(s for s in scenarios if s.id == "task_hist_architecture")
        assert arch_scenario.derived_from == "task_history"
        assert "architecture" in arch_scenario.domains
        assert len(arch_scenario.keywords) > 0

    def test_build_from_action_templates(self):
        builder = ScenarioBuilder()
        templates = [_make_template()]

        scenarios = builder.build_from_action_templates(templates)

        assert len(scenarios) == 1
        assert scenarios[0].derived_from == "action_template"
        assert "t-001" in scenarios[0].source_ids[0]
        assert "m-001" in scenarios[0].anchor_methodology_ids

    def test_build_from_component_gaps(self):
        builder = ScenarioBuilder()
        # Simulate a KB with only validator and parser
        type_counts = {"validator": 10, "parser": 8}

        scenarios = builder.build_from_component_gaps(type_counts, list(type_counts.keys()))

        # Should generate gap scenarios for missing standard types
        gap_ids = [s.id for s in scenarios if s.id.startswith("comp_gap_")]
        assert len(gap_ids) > 0
        # auth_client is a standard type not covered
        assert "comp_gap_auth_client" in gap_ids

    def test_build_from_capability_chains(self):
        builder = ScenarioBuilder()
        meths = [
            _make_methodology(
                "m-chain",
                problem="Chain-able methodology",
                capability_data={
                    "domain": ["error_handling"],
                    "composability": {
                        "can_chain_after": ["retry_handler"],
                        "can_chain_before": ["circuit_breaker"],
                    },
                },
            ),
        ]

        scenarios = builder.build_from_capability_chains(meths)

        assert len(scenarios) == 1
        assert scenarios[0].derived_from == "capability_chain"
        assert "m-chain" in scenarios[0].anchor_methodology_ids
        assert "retry_handler" in scenarios[0].description
        assert "circuit_breaker" in scenarios[0].description

    def test_build_from_stigmergic_links(self):
        builder = ScenarioBuilder()
        m1 = _make_methodology("m-s1", problem="Rate limiting implementation")
        m2 = _make_methodology("m-s2", problem="Circuit breaker pattern")
        meths_by_id = {m1.id: m1, m2.id: m2}

        pairs = [{"source_id": "m-s1", "target_id": "m-s2", "strength": 5.0}]

        scenarios = builder.build_from_stigmergic_links(pairs, meths_by_id)

        assert len(scenarios) == 1
        assert scenarios[0].derived_from == "stigmergic_link"
        assert "m-s1" in scenarios[0].anchor_methodology_ids
        assert "m-s2" in scenarios[0].anchor_methodology_ids
        assert "5.0" in scenarios[0].description

    def test_build_from_coverage_gaps(self):
        builder = ScenarioBuilder()
        domain_dist = {"architecture": 20, "security": 15, "devops": 1, "testing": 2}

        scenarios = builder.build_from_coverage_gaps(domain_dist)

        # devops (1) and testing (2) should be flagged as under-represented
        gap_domains = [s.domains[0] for s in scenarios if s.domains]
        assert "devops" in gap_domains

    def test_build_from_contradiction_signals(self):
        builder = ScenarioBuilder()
        m1 = _make_methodology("m-c1", problem="Always use sync I/O for simplicity")
        m2 = _make_methodology("m-c2", problem="Always use async I/O for performance")
        meths_by_id = {m1.id: m1, m2.id: m2}

        contras = [{
            "cap_a_id": "m-c1",
            "cap_b_id": "m-c2",
            "details": {"conflict_type": "approach"},
        }]

        scenarios = builder.build_from_contradiction_signals(contras, meths_by_id)

        assert len(scenarios) == 1
        assert scenarios[0].derived_from == "contradiction"
        assert "approach" in scenarios[0].description


# ---------------------------------------------------------------------------
# ScenarioScorer tests
# ---------------------------------------------------------------------------


class TestScenarioScorer:
    def test_score_with_domain_overlap(self):
        scorer = ScenarioScorer()
        meth = _make_methodology(category="error_handling")
        scenario = Scenario(
            id="s1",
            description="Error handling scenario",
            derived_from="task_history",
            domains=["error_handling"],
            keywords=["retry", "fallback"],
        )

        matches = scorer.score(meth, [scenario])

        assert len(matches) == 1
        assert matches[0].domain_overlap_score > 0.0
        assert matches[0].composite_score > 0.0

    def test_score_with_keyword_overlap(self):
        scorer = ScenarioScorer()
        meth = _make_methodology(
            problem="Implement retry logic with exponential backoff and jitter"
        )
        scenario = Scenario(
            id="s2",
            description="Retry handling",
            derived_from="task_history",
            domains=[],
            keywords=["retry", "backoff", "jitter"],
        )

        matches = scorer.score(meth, [scenario])

        assert len(matches) == 1
        assert matches[0].keyword_overlap_score > 0.0

    def test_score_with_embeddings(self):
        scorer = ScenarioScorer()
        meth = _make_methodology()

        # Create two scenarios: one similar (parallel vectors), one different
        similar_embedding = [0.5, 0.3, 0.8, 0.1]
        different_embedding = [-0.5, -0.3, -0.8, -0.1]

        similar_scenario = Scenario(
            id="s-sim",
            description="Similar",
            derived_from="task_history",
            embedding=similar_embedding,
        )
        different_scenario = Scenario(
            id="s-diff",
            description="Different",
            derived_from="task_history",
            embedding=different_embedding,
        )

        matches = scorer.score(
            meth,
            [similar_scenario, different_scenario],
            methodology_embedding=similar_embedding,
        )

        # similar_scenario should rank higher
        assert matches[0].scenario.id == "s-sim"
        assert matches[0].cosine_score > matches[1].cosine_score

    def test_score_sorts_by_composite(self):
        scorer = ScenarioScorer()
        meth = _make_methodology(category="security")

        high_match = Scenario(
            id="s-high",
            description="Security patterns",
            derived_from="task_history",
            domains=["security"],
            keywords=["auth", "token", "security"],
        )
        low_match = Scenario(
            id="s-low",
            description="Unrelated devops",
            derived_from="task_history",
            domains=["devops"],
            keywords=["deploy", "container"],
        )

        matches = scorer.score(meth, [low_match, high_match])

        assert matches[0].scenario.id == "s-high"
        assert matches[0].composite_score >= matches[1].composite_score


# ---------------------------------------------------------------------------
# DirectiveWriter tests
# ---------------------------------------------------------------------------


class TestDirectiveWriter:
    def test_write_directives_from_task_history(self):
        writer = DirectiveWriter()
        meth = _make_methodology()

        matches = [
            ScenarioMatch(
                scenario=Scenario(
                    id="task_hist_error_handling",
                    description="Error handling tasks",
                    derived_from="task_history",
                    domains=["error_handling"],
                    anchor_methodology_ids=["m-001", "m-002"],
                ),
                composite_score=0.6,
            ),
        ]

        directives = writer.write_directives(meth, matches)

        assert len(directives) >= 1
        assert "error_handling" in directives[0].lower() or "error handling" in directives[0].lower()

    def test_write_directives_from_capability_chain(self):
        writer = DirectiveWriter()
        anchor_meth = _make_methodology("m-anchor", problem="Retry handler with backoff")
        meth = _make_methodology("m-new")

        matches = [
            ScenarioMatch(
                scenario=Scenario(
                    id="chain_m-anchor",
                    description="Chain pattern",
                    derived_from="capability_chain",
                    anchor_methodology_ids=["m-anchor"],
                ),
                composite_score=0.5,
            ),
        ]

        directives = writer.write_directives(
            meth, matches,
            existing_methodologies_by_id={"m-anchor": anchor_meth},
        )

        assert len(directives) >= 1
        assert "Retry handler" in directives[0] or "chain" in directives[0].lower()

    def test_write_directives_from_component_gap(self):
        writer = DirectiveWriter()
        meth = _make_methodology()

        matches = [
            ScenarioMatch(
                scenario=Scenario(
                    id="comp_gap_auth_client",
                    description="No auth_client components exist",
                    derived_from="component_gap",
                ),
                composite_score=0.4,
            ),
        ]

        directives = writer.write_directives(meth, matches)

        assert len(directives) >= 1
        assert "gap" in directives[0].lower() or "fills" in directives[0].lower()

    def test_write_directives_skips_low_scoring(self):
        writer = DirectiveWriter()
        meth = _make_methodology()

        matches = [
            ScenarioMatch(
                scenario=Scenario(
                    id="s-weak",
                    description="Barely related",
                    derived_from="task_history",
                    domains=["unrelated"],
                ),
                composite_score=0.05,  # Below threshold of 0.10
            ),
        ]

        directives = writer.write_directives(meth, matches)

        assert len(directives) == 0

    def test_write_tension_questions_contradiction(self):
        writer = DirectiveWriter()
        anchor_meth = _make_methodology("m-contra", problem="Use sync I/O for simplicity")
        meth = _make_methodology("m-new", problem="Use async I/O for performance")

        matches = [
            ScenarioMatch(
                scenario=Scenario(
                    id="contra_test",
                    description="Contradiction",
                    derived_from="contradiction",
                    anchor_methodology_ids=["m-contra"],
                ),
                composite_score=0.5,
            ),
        ]

        questions = writer.write_tension_questions(
            meth, matches,
            existing_methodologies_by_id={"m-contra": anchor_meth},
        )

        assert len(questions) >= 1
        assert "sync" in questions[0].lower() or "conflict" in questions[0].lower()

    def test_write_tension_questions_fallback(self):
        writer = DirectiveWriter()
        meth = _make_methodology()

        questions = writer.write_tension_questions(meth, [])

        assert len(questions) >= 1
        assert "existing knowledge" in questions[0].lower()

    def test_bandit_prior_boost(self):
        writer = DirectiveWriter()

        high_matches = [
            ScenarioMatch(
                scenario=Scenario(id="s1", description="", derived_from="task_history"),
                composite_score=0.8,
            ),
            ScenarioMatch(
                scenario=Scenario(id="s2", description="", derived_from="task_history"),
                composite_score=0.7,
            ),
        ]

        boost = writer.compute_bandit_prior_boost(high_matches)

        assert 0.0 < boost <= 0.5
        assert boost > 0.3  # High scoring matches should give strong boost

    def test_bandit_prior_boost_empty(self):
        writer = DirectiveWriter()
        assert writer.compute_bandit_prior_boost([]) == 0.0


# ---------------------------------------------------------------------------
# ScenarioEnricher integration test
# ---------------------------------------------------------------------------


class TestScenarioEnricher:
    def test_enrich_with_prebuilt_scenarios(self):
        from claw.scenario_enrichment import ScenarioEnricher

        enricher = ScenarioEnricher()
        meth = _make_methodology(category="error_handling")

        scenarios = [
            Scenario(
                id="task_hist_error_handling",
                description="Error handling tasks with retry and fallback patterns",
                derived_from="task_history",
                domains=["error_handling"],
                anchor_methodology_ids=["m-existing"],
                keywords=["retry", "backoff", "error", "fallback"],
            ),
            Scenario(
                id="comp_gap_retry_handler",
                description="No retry_handler components exist",
                derived_from="component_gap",
                keywords=["retry", "handler"],
            ),
        ]

        anchor_meth = _make_methodology("m-existing", problem="Existing retry handler")
        meths_by_id = {"m-existing": anchor_meth}

        result = enricher.enrich(
            meth,
            scenarios=scenarios,
            existing_methodologies_by_id=meths_by_id,
        )

        assert isinstance(result, EnrichmentResult)
        assert result.methodology_id == meth.id
        assert len(result.directives) > 0
        assert len(result.tension_questions) > 0
        assert result.bandit_prior_boost >= 0.0

    def test_enrich_no_scenarios_returns_empty(self):
        from claw.scenario_enrichment import ScenarioEnricher

        enricher = ScenarioEnricher()
        meth = _make_methodology()

        result = enricher.enrich(meth, scenarios=[])

        assert result.directives == []
        assert result.tension_questions == []
        assert result.bandit_prior_boost == 0.0


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_extract_keywords(self):
        text = "Implement retry logic with exponential backoff and jitter"
        keywords = _extract_keywords(text)

        assert "retry" in keywords
        assert "backoff" in keywords
        assert "jitter" in keywords
        # Stopwords should be filtered
        assert "with" not in keywords
        assert "and" not in keywords

    def test_extract_keywords_deduplicates(self):
        text = "retry retry retry backoff backoff"
        keywords = _extract_keywords(text)

        assert keywords.count("retry") == 1
        assert keywords.count("backoff") == 1

    def test_extract_keywords_empty(self):
        assert _extract_keywords("") == []
        assert _extract_keywords("a b") == []  # Too short

    def test_cosine_similarity_identical(self):
        vec = [1.0, 2.0, 3.0]
        sim = _cosine_similarity(vec, vec)
        assert abs(sim - 1.0) < 0.001

    def test_cosine_similarity_orthogonal(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        sim = _cosine_similarity(a, b)
        assert abs(sim) < 0.001

    def test_cosine_similarity_opposite(self):
        a = [1.0, 2.0, 3.0]
        b = [-1.0, -2.0, -3.0]
        sim = _cosine_similarity(a, b)
        assert abs(sim + 1.0) < 0.001

    def test_cosine_similarity_empty(self):
        assert _cosine_similarity([], []) == 0.0
        assert _cosine_similarity([1.0], []) == 0.0

    def test_cosine_similarity_zero_vectors(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0
