"""Persistence tests for the sparse evidence graph's isolated tables."""

from __future__ import annotations

from pathlib import Path

from claw.core.config import DatabaseConfig
from claw.db.engine import DatabaseEngine
from claw.knowledge_graph.contract import EvidenceGraphFixture
from claw.knowledge_graph.persistence import persist_evidence_graph

FIXTURE = Path(__file__).parent / "fixtures" / "evidence_graph_v1" / "graph.json"


async def test_persisted_fixture_keeps_receipts_and_associations_out_of_factual_paths(
    tmp_path: Path,
) -> None:
    engine = DatabaseEngine(DatabaseConfig(db_path=str(tmp_path / "graph.db")))
    await engine.connect()
    try:
        await engine.apply_migrations()
        await engine.initialize_schema()
        graph = EvidenceGraphFixture.model_validate_json(FIXTURE.read_text())

        await persist_evidence_graph(engine, snapshot_id="fixture-auth-v1", graph=graph)

        association = await engine.fetch_one(
            """SELECT evidence_class, factual_path_eligible
               FROM evidence_graph_edges
               WHERE snapshot_id = ? AND edge_id = ?""",
            ["fixture-auth-v1", "edge:legacy:co_retrieval"],
        )
        receipt = await engine.fetch_one(
            """SELECT content_sha256, source_revision
               FROM evidence_graph_edge_receipts
               WHERE snapshot_id = ? AND edge_id = ?""",
            ["fixture-auth-v1", "edge:declares:validate_token"],
        )

        assert association == {
            "evidence_class": "association",
            "factual_path_eligible": 0,
        }
        assert receipt == {
            "content_sha256": "1" * 64,
            "source_revision": "fixture-auth-v1",
        }
    finally:
        await engine.close()


async def test_reimporting_the_same_snapshot_is_idempotent(tmp_path: Path) -> None:
    engine = DatabaseEngine(DatabaseConfig(db_path=str(tmp_path / "graph.db")))
    await engine.connect()
    try:
        await engine.apply_migrations()
        await engine.initialize_schema()
        graph = EvidenceGraphFixture.model_validate_json(FIXTURE.read_text())

        await persist_evidence_graph(engine, snapshot_id="fixture-auth-v1", graph=graph)
        await persist_evidence_graph(engine, snapshot_id="fixture-auth-v1", graph=graph)

        edge_count = await engine.fetch_one(
            "SELECT COUNT(*) AS count FROM evidence_graph_edges WHERE snapshot_id = ?",
            ["fixture-auth-v1"],
        )
        receipt_count = await engine.fetch_one(
            """SELECT COUNT(*) AS count FROM evidence_graph_edge_receipts
               WHERE snapshot_id = ?""",
            ["fixture-auth-v1"],
        )

        assert edge_count == {"count": 5}
        assert receipt_count == {"count": 5}
    finally:
        await engine.close()


async def test_snapshot_id_cannot_be_reused_for_changed_graph(tmp_path: Path) -> None:
    engine = DatabaseEngine(DatabaseConfig(db_path=str(tmp_path / "graph.db")))
    await engine.connect()
    try:
        await engine.apply_migrations()
        await engine.initialize_schema()
        graph = EvidenceGraphFixture.model_validate_json(FIXTURE.read_text())
        await persist_evidence_graph(engine, snapshot_id="fixture-auth-v1", graph=graph)

        changed = graph.model_copy(
            update={
                "nodes": tuple(
                    node.model_copy(update={"canonical_name": "changed"})
                    if node.node_id == "symbol:validate_token"
                    else node
                    for node in graph.nodes
                )
            }
        )
        try:
            await persist_evidence_graph(
                engine, snapshot_id="fixture-auth-v1", graph=changed
            )
        except ValueError as exc:
            assert "different content" in str(exc)
        else:
            raise AssertionError("changed graph content must not replace an immutable snapshot")

        node = await engine.fetch_one(
            """SELECT canonical_name FROM evidence_graph_nodes
               WHERE snapshot_id = ? AND node_id = ?""",
            ["fixture-auth-v1", "symbol:validate_token"],
        )
        assert node == {"canonical_name": "validate_token"}
    finally:
        await engine.close()


async def test_entity_resolution_decisions_are_retained(tmp_path: Path) -> None:
    engine = DatabaseEngine(DatabaseConfig(db_path=str(tmp_path / "graph.db")))
    await engine.connect()
    try:
        await engine.apply_migrations()
        await engine.initialize_schema()
        graph = EvidenceGraphFixture.model_validate_json(FIXTURE.read_text())
        await persist_evidence_graph(engine, snapshot_id="fixture-auth-v1", graph=graph)

        resolution = await engine.fetch_one(
            """SELECT decision, confidence, candidate_node_ids_json
               FROM evidence_graph_entity_resolution
               WHERE snapshot_id = ? AND entity_key = ?""",
            ["fixture-auth-v1", "methodology:token-pattern"],
        )
        assert resolution is not None
        assert resolution["decision"] == "unresolved"
        assert resolution["confidence"] == 0.42
        assert "methodology:auth_pattern" in resolution["candidate_node_ids_json"]
    finally:
        await engine.close()
