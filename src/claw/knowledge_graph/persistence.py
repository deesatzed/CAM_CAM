"""Transactional storage for immutable sparse evidence graph snapshots."""

from __future__ import annotations

import hashlib
import json

from claw.db.engine import DatabaseEngine
from claw.knowledge_graph.contract import EvidenceGraphFixture


def _graph_digest(graph: EvidenceGraphFixture) -> str:
    payload = json.dumps(graph.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def persist_evidence_graph(
    engine: DatabaseEngine, *, snapshot_id: str, graph: EvidenceGraphFixture
) -> None:
    """Persist a graph once under a stable snapshot ID.

    The caller must initialize or migrate the database first. Reusing an ID
    with changed graph bytes fails closed; a graph snapshot is immutable once
    recorded. This service intentionally does not read or modify legacy
    ``methodology_links``.
    """
    digest = _graph_digest(graph)
    async with engine.transaction():
        existing = await engine.fetch_one(
            "SELECT graph_sha256 FROM evidence_graph_snapshots WHERE snapshot_id = ?",
            [snapshot_id],
        )
        if existing is not None and existing["graph_sha256"] != digest:
            raise ValueError(
                "Evidence graph snapshot already exists with different content: "
                f"{snapshot_id}"
            )
        if existing is not None:
            return

        await engine.execute(
            """INSERT INTO evidence_graph_snapshots
               (snapshot_id, schema_version, graph_sha256) VALUES (?, ?, ?)""",
            [snapshot_id, graph.schema_version, digest],
        )
        for node in graph.nodes:
            await engine.execute(
                """INSERT INTO evidence_graph_nodes
                   (snapshot_id, node_id, node_type, canonical_name, aliases_json)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    snapshot_id,
                    node.node_id,
                    node.node_type,
                    node.canonical_name,
                    json.dumps(node.aliases),
                ],
            )
        for edge in graph.edges:
            await engine.execute(
                """INSERT INTO evidence_graph_edges
                   (snapshot_id, edge_id, source_id, target_id, edge_type, evidence_class,
                    confidence, factual_path_eligible)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    snapshot_id,
                    edge.edge_id,
                    edge.source_id,
                    edge.target_id,
                    edge.edge_type,
                    edge.evidence_class.value,
                    edge.confidence,
                    int(edge.factual_path_eligible),
                ],
            )
            for receipt_index, receipt in enumerate(edge.evidence):
                await engine.execute(
                    """INSERT INTO evidence_graph_edge_receipts
                       (snapshot_id, edge_id, receipt_index, source_uri, source_revision,
                        content_sha256, extraction_method)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    [
                        snapshot_id,
                        edge.edge_id,
                        receipt_index,
                        receipt.source_uri,
                        receipt.source_revision,
                        receipt.content_sha256,
                        receipt.extraction_method,
                    ],
                )
        for record in graph.entity_resolution:
            await engine.execute(
                """INSERT INTO evidence_graph_entity_resolution
                   (snapshot_id, entity_key, candidate_node_ids_json, decision, confidence)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    snapshot_id,
                    record.entity_key,
                    json.dumps(record.candidate_node_ids),
                    record.decision,
                    record.confidence,
                ],
            )
            for receipt_index, receipt in enumerate(record.evidence):
                await engine.execute(
                    """INSERT INTO evidence_graph_entity_receipts
                       (snapshot_id, entity_key, receipt_index, source_uri, source_revision,
                        content_sha256, extraction_method)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    [
                        snapshot_id,
                        record.entity_key,
                        receipt_index,
                        receipt.source_uri,
                        receipt.source_revision,
                        receipt.content_sha256,
                        receipt.extraction_method,
                    ],
                )
