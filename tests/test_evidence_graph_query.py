"""Bounded, provenance-first graph query tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from claw.core.config import DatabaseConfig
from claw.db.engine import DatabaseEngine
from claw.knowledge_graph.contract import EvidenceGraphFixture
from claw.knowledge_graph.persistence import persist_evidence_graph
from claw.knowledge_graph.query import query_evidence_graph

FIXTURE = Path(__file__).parent / "fixtures" / "evidence_graph_v1" / "graph.json"


async def _engine_with_fixture(tmp_path: Path) -> tuple[DatabaseEngine, EvidenceGraphFixture]:
    engine = DatabaseEngine(DatabaseConfig(db_path=str(tmp_path / "graph.db")))
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    graph = EvidenceGraphFixture.model_validate_json(FIXTURE.read_text())
    await persist_evidence_graph(engine, snapshot_id="fixture-auth-v1", graph=graph)
    return engine, graph


async def test_query_defaults_to_factual_two_hop_receipt_backed_subgraph(
    tmp_path: Path,
) -> None:
    engine, _ = await _engine_with_fixture(tmp_path)
    try:
        result = await query_evidence_graph(
            engine,
            snapshot_id="fixture-auth-v1",
            seed_node_id="source_file:auth_service",
        )

        assert result.seed_node_id == "source_file:auth_service"
        assert result.max_hops == 2
        assert [edge.edge_type for edge in result.edges] == [
            "declares",
            "covered_by",
            "verified_by",
        ]
        assert all(edge.evidence_class == "explicit" for edge in result.edges)
        assert all(edge.factual_path_eligible for edge in result.edges)
        assert all(edge.receipts for edge in result.edges)
        assert all(node.provenance for node in result.nodes)
        assert all(edge.edge_type != "co_retrieval" for edge in result.edges)
    finally:
        await engine.close()


async def test_association_edges_require_explicit_opt_in_and_remain_nonfactual(
    tmp_path: Path,
) -> None:
    engine, _ = await _engine_with_fixture(tmp_path)
    try:
        result = await query_evidence_graph(
            engine,
            snapshot_id="fixture-auth-v1",
            seed_node_id="methodology:auth_pattern",
            include_associations=True,
        )

        association = next(edge for edge in result.edges if edge.edge_type == "co_retrieval")
        assert association.evidence_class == "association"
        assert association.factual_path_eligible is False
    finally:
        await engine.close()


async def test_query_supports_typed_filter_and_rejects_excessive_budget(
    tmp_path: Path,
) -> None:
    engine, _ = await _engine_with_fixture(tmp_path)
    try:
        filtered = await query_evidence_graph(
            engine,
            snapshot_id="fixture-auth-v1",
            seed_node_id="source_file:auth_service",
            edge_types={"declares"},
        )
        assert [edge.edge_type for edge in filtered.edges] == ["declares"]

        with pytest.raises(ValueError, match="token budget"):
            await query_evidence_graph(
                engine,
                snapshot_id="fixture-auth-v1",
                seed_node_id="source_file:auth_service",
                token_budget=1,
            )
    finally:
        await engine.close()
