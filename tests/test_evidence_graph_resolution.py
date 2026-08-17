"""Deterministic, review-first entity resolution tests."""

from __future__ import annotations

from claw.knowledge_graph.contract import GraphEvidenceReceipt, GraphNode
from claw.knowledge_graph.resolve import resolve_methodology_entities

RECEIPT = GraphEvidenceReceipt(
    source_uri="fixture:README.md",
    source_revision="fixture-auth-v1",
    content_sha256="5" * 64,
    extraction_method="fixture_alias_blocking",
)


def test_high_similarity_methodologies_emit_receipt_backed_merge() -> None:
    records = resolve_methodology_entities(
        [
            GraphNode(
                node_id="methodology:retry-a",
                node_type="methodology",
                canonical_name="Retry with jitter",
                aliases=("retry jitter",),
            ),
            GraphNode(
                node_id="methodology:retry-b",
                node_type="methodology",
                canonical_name="Retry jitter strategy",
            ),
        ],
        evidence=(RECEIPT,),
    )

    assert len(records) == 1
    assert records[0].decision == "merge"
    assert records[0].candidate_node_ids == (
        "methodology:retry-a",
        "methodology:retry-b",
    )
    assert records[0].evidence == (RECEIPT,)


def test_close_candidates_remain_unresolved_for_review() -> None:
    records = resolve_methodology_entities(
        [
            GraphNode(
                node_id="methodology:retry-a",
                node_type="methodology",
                canonical_name="Retry strategy",
            ),
            GraphNode(
                node_id="methodology:retry-b",
                node_type="methodology",
                canonical_name="Retry pattern",
            ),
            GraphNode(
                node_id="methodology:retry-c",
                node_type="methodology",
                canonical_name="Retry approach",
            ),
        ],
        evidence=(RECEIPT,),
        min_similarity=0.4,
        ambiguity_margin=0.2,
    )

    assert records
    assert all(record.decision == "unresolved" for record in records)
    assert all(record.confidence < 1.0 for record in records)
