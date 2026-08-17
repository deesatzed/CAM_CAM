"""Health and stale-revision safety tests for persisted graph snapshots."""

from __future__ import annotations

from pathlib import Path

import pytest

from claw.core.config import DatabaseConfig
from claw.db.engine import DatabaseEngine
from claw.knowledge_graph.contract import EvidenceGraphFixture
from claw.knowledge_graph.health import measure_evidence_graph_health
from claw.knowledge_graph.persistence import persist_evidence_graph
from claw.knowledge_graph.query import query_evidence_graph

FIXTURE = Path(__file__).parent / "fixtures" / "evidence_graph_v1" / "graph.json"


async def _engine_with_fixture(tmp_path: Path) -> DatabaseEngine:
    engine = DatabaseEngine(DatabaseConfig(db_path=str(tmp_path / "graph.db")))
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    graph = EvidenceGraphFixture.model_validate_json(FIXTURE.read_text())
    await persist_evidence_graph(engine, snapshot_id="fixture-auth-v1", graph=graph)
    return engine


async def test_health_report_matches_persisted_fixture_baseline(tmp_path: Path) -> None:
    engine = await _engine_with_fixture(tmp_path)
    try:
        report = await measure_evidence_graph_health(
            engine, snapshot_id="fixture-auth-v1"
        )

        assert report.node_count == 6
        assert report.edge_count == 5
        assert report.average_degree == pytest.approx(10 / 6)
        assert report.hub_dominance == pytest.approx(0.3)
        assert report.edge_class_counts == {
            "association": 1,
            "explicit": 4,
            "inferred": 0,
        }
        assert report.unresolved_entity_count == 1
        assert report.query_node_count == 0
        assert report.query_edge_count == 0
    finally:
        await engine.close()


async def test_query_rejects_receipts_from_stale_source_revision(tmp_path: Path) -> None:
    engine = await _engine_with_fixture(tmp_path)
    try:
        with pytest.raises(ValueError, match="stale source revision"):
            await query_evidence_graph(
                engine,
                snapshot_id="fixture-auth-v1",
                seed_node_id="source_file:auth_service",
                expected_source_revision="fixture-auth-v2",
            )
    finally:
        await engine.close()
