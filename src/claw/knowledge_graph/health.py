"""Deterministic health metrics for persisted evidence graph snapshots."""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict

from claw.db.engine import DatabaseEngine
from claw.knowledge_graph.contract import EvidenceClass


class EvidenceGraphHealthReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    node_count: int
    edge_count: int
    average_degree: float
    hub_dominance: float
    edge_class_counts: dict[str, int]
    unresolved_entity_count: int
    query_node_count: int = 0
    query_edge_count: int = 0
    retrieval_token_estimate: int = 0


async def measure_evidence_graph_health(
    engine: DatabaseEngine,
    *,
    snapshot_id: str,
    query_node_count: int = 0,
    query_edge_count: int = 0,
    retrieval_token_estimate: int = 0,
) -> EvidenceGraphHealthReport:
    """Measure a named snapshot without changing it or reading legacy links."""
    snapshot = await engine.fetch_one(
        "SELECT snapshot_id FROM evidence_graph_snapshots WHERE snapshot_id = ?",
        [snapshot_id],
    )
    if snapshot is None:
        raise ValueError(f"Unknown evidence graph snapshot: {snapshot_id}")

    node_row = await engine.fetch_one(
        "SELECT COUNT(*) AS count FROM evidence_graph_nodes WHERE snapshot_id = ?",
        [snapshot_id],
    )
    edge_row = await engine.fetch_one(
        "SELECT COUNT(*) AS count FROM evidence_graph_edges WHERE snapshot_id = ?",
        [snapshot_id],
    )
    node_count = int(node_row["count"] if node_row else 0)
    edge_count = int(edge_row["count"] if edge_row else 0)

    edge_class_counts = {evidence_class.value: 0 for evidence_class in EvidenceClass}
    class_rows = await engine.fetch_all(
        """SELECT evidence_class, COUNT(*) AS count
           FROM evidence_graph_edges WHERE snapshot_id = ?
           GROUP BY evidence_class""",
        [snapshot_id],
    )
    for row in class_rows:
        edge_class_counts[str(row["evidence_class"])] = int(row["count"])

    degree = Counter[str]()
    edge_rows = await engine.fetch_all(
        """SELECT source_id, target_id FROM evidence_graph_edges
           WHERE snapshot_id = ?""",
        [snapshot_id],
    )
    for row in edge_rows:
        degree[str(row["source_id"])] += 1
        degree[str(row["target_id"])] += 1
    total_degree = sum(degree.values())

    unresolved = await engine.fetch_one(
        """SELECT COUNT(*) AS count FROM evidence_graph_entity_resolution
           WHERE snapshot_id = ? AND decision = 'unresolved'""",
        [snapshot_id],
    )
    return EvidenceGraphHealthReport(
        snapshot_id=snapshot_id,
        node_count=node_count,
        edge_count=edge_count,
        average_degree=total_degree / node_count if node_count else 0.0,
        hub_dominance=max(degree.values(), default=0) / total_degree
        if total_degree
        else 0.0,
        edge_class_counts=edge_class_counts,
        unresolved_entity_count=int(unresolved["count"] if unresolved else 0),
        query_node_count=query_node_count,
        query_edge_count=query_edge_count,
        retrieval_token_estimate=retrieval_token_estimate,
    )
