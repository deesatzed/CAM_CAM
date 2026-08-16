"""Versioned, provenance-first contract for CAM's sparse evidence graph.

This module is intentionally pure: Phase 1 defines and validates graph facts
without opening a CAM database, extracting source code, or traversing a graph.
"""

from __future__ import annotations

from collections import Counter
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "cam.evidence-graph.v1"


class EvidenceClass(str, Enum):
    """How strongly an edge may be used during future graph retrieval."""

    EXPLICIT = "explicit"
    INFERRED = "inferred"
    ASSOCIATION = "association"


class GraphEvidenceReceipt(BaseModel):
    """Immutable provenance for one edge observation or inference."""

    model_config = ConfigDict(frozen=True)

    source_uri: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction_method: str = Field(min_length=1)


class GraphNode(BaseModel):
    """Canonical entity reference; aliases remain explicit for later resolution."""

    model_config = ConfigDict(frozen=True)

    node_id: str = Field(min_length=1)
    node_type: Literal["source_file", "symbol", "test", "outcome", "methodology"]
    canonical_name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()


class EntityResolutionRecord(BaseModel):
    """A reproducible merge, split, or unresolved entity decision."""

    model_config = ConfigDict(frozen=True)

    entity_key: str = Field(min_length=1)
    candidate_node_ids: tuple[str, ...] = Field(min_length=1)
    decision: Literal["merge", "split", "unresolved"]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: tuple[GraphEvidenceReceipt, ...] = Field(min_length=1)


class GraphEdge(BaseModel):
    """A typed, directed relationship with its evidence semantics preserved."""

    model_config = ConfigDict(frozen=True)

    edge_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    edge_type: str = Field(min_length=1)
    evidence_class: EvidenceClass
    confidence: float = Field(ge=0.0, le=1.0)
    factual_path_eligible: bool
    evidence: tuple[GraphEvidenceReceipt, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def association_edges_are_never_factual(self) -> "GraphEdge":
        if self.evidence_class is EvidenceClass.ASSOCIATION and self.factual_path_eligible:
            raise ValueError("Association edges cannot be eligible for factual paths")
        return self


class EvidenceGraphFixture(BaseModel):
    """Small deterministic corpus used to establish the Phase 1 baseline."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[SCHEMA_VERSION]
    nodes: tuple[GraphNode, ...] = Field(min_length=1)
    edges: tuple[GraphEdge, ...] = Field(min_length=1)
    entity_resolution: tuple[EntityResolutionRecord, ...] = ()

    @model_validator(mode="after")
    def references_existing_nodes(self) -> "EvidenceGraphFixture":
        node_ids = {node.node_id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("Graph node IDs must be unique")
        unknown = sorted(
            {
                endpoint
                for edge in self.edges
                for endpoint in (edge.source_id, edge.target_id)
                if endpoint not in node_ids
            }
        )
        if unknown:
            raise ValueError("Edges reference unknown nodes: " + ", ".join(unknown))
        return self


class GraphHealth(BaseModel):
    """Deterministic baseline metrics; no accuracy claim is implied."""

    model_config = ConfigDict(frozen=True)

    node_count: int
    edge_count: int
    average_degree: float
    hub_dominance: float
    edge_class_counts: dict[str, int]
    unresolved_entity_count: int


def graph_health(graph: EvidenceGraphFixture) -> GraphHealth:
    """Calculate stable sparsity metrics for an evidence graph fixture."""
    degree = Counter[str]()
    edge_classes = Counter(edge.evidence_class.value for edge in graph.edges)
    for edge in graph.edges:
        degree[edge.source_id] += 1
        degree[edge.target_id] += 1
    total_degree = sum(degree.values())
    return GraphHealth(
        node_count=len(graph.nodes),
        edge_count=len(graph.edges),
        average_degree=total_degree / len(graph.nodes),
        hub_dominance=(max(degree.values(), default=0) / total_degree) if total_degree else 0.0,
        edge_class_counts={
            evidence_class.value: edge_classes[evidence_class.value]
            for evidence_class in EvidenceClass
        },
        unresolved_entity_count=sum(
            record.decision == "unresolved" for record in graph.entity_resolution
        ),
    )
