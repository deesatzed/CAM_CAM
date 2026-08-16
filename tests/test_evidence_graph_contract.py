from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from claw.knowledge_graph.contract import (
    EvidenceClass,
    EvidenceGraphFixture,
    GraphEdge,
    GraphEvidenceReceipt,
    graph_health,
)


FIXTURE = Path(__file__).parent / "fixtures" / "evidence_graph_v1" / "graph.json"


def test_fixture_graph_preserves_explicit_and_association_evidence() -> None:
    graph = EvidenceGraphFixture.model_validate_json(FIXTURE.read_text())

    assert graph.schema_version == "cam.evidence-graph.v1"
    assert {node.node_type for node in graph.nodes} >= {
        "source_file", "symbol", "test", "outcome"
    }
    associations = [edge for edge in graph.edges if edge.evidence_class == EvidenceClass.ASSOCIATION]
    assert [edge.edge_type for edge in associations] == ["co_retrieval"]
    assert associations[0].factual_path_eligible is False
    assert all(edge.evidence for edge in graph.edges)


def test_association_edge_cannot_be_marked_as_factual_path() -> None:
    receipt = GraphEvidenceReceipt(
        source_uri="legacy:methodology_links",
        source_revision="legacy-import-20260816",
        content_sha256="a" * 64,
        extraction_method="legacy_association_import",
    )

    with pytest.raises(ValidationError, match="Association edges"):
        GraphEdge(
            edge_id="edge:legacy:co-retrieval",
            source_id="methodology:auth-pattern",
            target_id="methodology:token-pattern",
            edge_type="co_retrieval",
            evidence_class=EvidenceClass.ASSOCIATION,
            confidence=0.7,
            factual_path_eligible=True,
            evidence=[receipt],
        )


def test_fixture_health_metrics_are_deterministic_and_sparse() -> None:
    graph = EvidenceGraphFixture.model_validate(json.loads(FIXTURE.read_text()))

    health = graph_health(graph)

    assert health.node_count == 6
    assert health.edge_count == 5
    assert health.average_degree == pytest.approx(10 / 6)
    assert health.hub_dominance == pytest.approx(0.3)
    assert health.edge_class_counts == {
        "association": 1,
        "explicit": 4,
        "inferred": 0,
    }
    assert health.unresolved_entity_count == 1
