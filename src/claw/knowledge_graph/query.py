"""Bounded read-only traversal for receipt-backed evidence graph snapshots."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from claw.db.engine import DatabaseEngine
from claw.knowledge_graph.contract import EvidenceClass, GraphEvidenceReceipt


class EvidenceGraphQueryNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    node_type: str
    canonical_name: str
    aliases: tuple[str, ...] = ()
    provenance: tuple[GraphEvidenceReceipt, ...] = Field(min_length=1)


class EvidenceGraphQueryEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    edge_id: str
    source_id: str
    target_id: str
    edge_type: str
    evidence_class: EvidenceClass
    confidence: float
    factual_path_eligible: bool
    receipts: tuple[GraphEvidenceReceipt, ...] = Field(min_length=1)


class EvidenceGraphQueryResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    seed_node_id: str
    max_hops: int
    nodes: tuple[EvidenceGraphQueryNode, ...]
    edges: tuple[EvidenceGraphQueryEdge, ...]
    token_estimate: int


def _in_clause(values: Iterable[str]) -> tuple[str, list[str]]:
    values = list(values)
    return ", ".join("?" for _ in values), values


async def query_evidence_graph(
    engine: DatabaseEngine,
    *,
    snapshot_id: str,
    seed_node_id: str,
    max_hops: int = 2,
    edge_types: set[str] | None = None,
    include_associations: bool = False,
    max_nodes: int = 50,
    max_edges: int = 75,
    max_degree: int = 8,
    token_budget: int = 2048,
) -> EvidenceGraphQueryResult:
    """Return a deterministic, compact subgraph without changing database state."""
    if not 0 <= max_hops <= 2:
        raise ValueError("max_hops must be between 0 and 2")
    if min(max_nodes, max_edges, max_degree, token_budget) <= 0:
        raise ValueError("query limits must be positive")

    snapshot = await engine.fetch_one(
        "SELECT snapshot_id FROM evidence_graph_snapshots WHERE snapshot_id = ?",
        [snapshot_id],
    )
    if snapshot is None:
        raise ValueError(f"Unknown evidence graph snapshot: {snapshot_id}")
    seed = await engine.fetch_one(
        """SELECT node_id, node_type, canonical_name, aliases_json
           FROM evidence_graph_nodes WHERE snapshot_id = ? AND node_id = ?""",
        [snapshot_id, seed_node_id],
    )
    if seed is None:
        raise ValueError(f"Unknown evidence graph seed node: {seed_node_id}")

    selected_edges: dict[str, dict[str, object]] = {}
    node_distance = {seed_node_id: 0}
    frontier = [seed_node_id]
    for hop in range(max_hops):
        if not frontier or len(selected_edges) >= max_edges:
            break
        clause, params = _in_clause(frontier)
        rows = await engine.fetch_all(
            f"""SELECT edge_id, source_id, target_id, edge_type, evidence_class,
                       confidence, factual_path_eligible
                   FROM evidence_graph_edges
                   WHERE snapshot_id = ?
                     AND (source_id IN ({clause}) OR target_id IN ({clause}))""",
            [snapshot_id, *params, *params],
        )
        candidates_by_node: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in rows:
            if (
                not include_associations
                and row["evidence_class"] == EvidenceClass.ASSOCIATION.value
            ):
                continue
            if edge_types is not None and row["edge_type"] not in edge_types:
                continue
            for node_id in (row["source_id"], row["target_id"]):
                if node_id in frontier:
                    candidates_by_node[node_id].append(row)

        next_frontier: list[str] = []
        for node_id in frontier:
            candidates = sorted(
                candidates_by_node[node_id],
                key=lambda row: (str(row["edge_type"]), str(row["edge_id"])),
            )[:max_degree]
            for row in candidates:
                edge_id = str(row["edge_id"])
                if edge_id in selected_edges:
                    continue
                other = str(row["target_id"] if row["source_id"] == node_id else row["source_id"])
                if other not in node_distance:
                    if len(node_distance) >= max_nodes:
                        continue
                    node_distance[other] = hop + 1
                    next_frontier.append(other)
                selected_edges[edge_id] = row
                if len(selected_edges) >= max_edges:
                    break
            if len(selected_edges) >= max_edges:
                break
        frontier = sorted(set(next_frontier), key=lambda value: (node_distance[value], value))

    edge_ids = list(selected_edges)
    receipts_by_edge: dict[str, list[GraphEvidenceReceipt]] = defaultdict(list)
    if edge_ids:
        clause, params = _in_clause(edge_ids)
        receipt_rows = await engine.fetch_all(
            f"""SELECT edge_id, source_uri, source_revision, content_sha256, extraction_method
                   FROM evidence_graph_edge_receipts
                   WHERE snapshot_id = ? AND edge_id IN ({clause})
                   ORDER BY edge_id, receipt_index""",
            [snapshot_id, *params],
        )
        for row in receipt_rows:
            receipts_by_edge[str(row["edge_id"])].append(
                GraphEvidenceReceipt(
                    source_uri=str(row["source_uri"]),
                    source_revision=str(row["source_revision"]),
                    content_sha256=str(row["content_sha256"]),
                    extraction_method=str(row["extraction_method"]),
                )
            )

    edges: list[EvidenceGraphQueryEdge] = []
    node_provenance: dict[str, list[GraphEvidenceReceipt]] = defaultdict(list)
    for edge_id, row in selected_edges.items():
        receipts = tuple(receipts_by_edge[edge_id])
        if not receipts:
            raise ValueError(f"Graph edge has no evidence receipts: {edge_id}")
        edge = EvidenceGraphQueryEdge(
            edge_id=edge_id,
            source_id=str(row["source_id"]),
            target_id=str(row["target_id"]),
            edge_type=str(row["edge_type"]),
            evidence_class=EvidenceClass(str(row["evidence_class"])),
            confidence=float(row["confidence"]),
            factual_path_eligible=bool(row["factual_path_eligible"]),
            receipts=receipts,
        )
        edges.append(edge)
        node_provenance[edge.source_id].extend(receipts)
        node_provenance[edge.target_id].extend(receipts)

    node_ids = sorted(node_distance, key=lambda value: (node_distance[value], value))
    clause, params = _in_clause(node_ids)
    node_rows = await engine.fetch_all(
        f"""SELECT node_id, node_type, canonical_name, aliases_json
               FROM evidence_graph_nodes
               WHERE snapshot_id = ? AND node_id IN ({clause})""",
        [snapshot_id, *params],
    )
    rows_by_id = {str(row["node_id"]): row for row in node_rows}
    nodes: list[EvidenceGraphQueryNode] = []
    for node_id in node_ids:
        row = rows_by_id[node_id]
        provenance = tuple(
            {receipt.model_dump_json(): receipt for receipt in node_provenance[node_id]}.values()
        )
        nodes.append(
            EvidenceGraphQueryNode(
                node_id=node_id,
                node_type=str(row["node_type"]),
                canonical_name=str(row["canonical_name"]),
                aliases=tuple(json.loads(str(row["aliases_json"]))),
                provenance=provenance,
            )
        )

    payload = {
        "nodes": [node.model_dump(mode="json") for node in nodes],
        "edges": [edge.model_dump(mode="json") for edge in edges],
    }
    token_estimate = len(json.dumps(payload, sort_keys=True)) // 4
    if token_estimate > token_budget:
        raise ValueError(f"Graph query exceeds token budget: {token_estimate} > {token_budget}")
    return EvidenceGraphQueryResult(
        snapshot_id=snapshot_id,
        seed_node_id=seed_node_id,
        max_hops=max_hops,
        nodes=tuple(nodes),
        edges=tuple(edges),
        token_estimate=token_estimate,
    )
