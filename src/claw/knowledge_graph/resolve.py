"""Model-free methodology entity blocking and review-first resolution."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Iterable

from claw.knowledge_graph.contract import (
    EntityResolutionRecord,
    GraphEvidenceReceipt,
    GraphNode,
)


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def _similarity(left: GraphNode, right: GraphNode) -> float:
    values: list[float] = []
    for left_name in (left.canonical_name, *left.aliases):
        for right_name in (right.canonical_name, *right.aliases):
            left_tokens = _tokens(left_name)
            right_tokens = _tokens(right_name)
            union = left_tokens | right_tokens
            jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
            sequence = SequenceMatcher(
                None, left_name.lower(), right_name.lower()
            ).ratio()
            values.append(max(jaccard, sequence))
    return max(values, default=0.0)


def _blocking_keys(node: GraphNode) -> set[str]:
    keys: set[str] = set()
    for name in (node.canonical_name, *node.aliases):
        tokens = re.findall(r"[a-z0-9]+", name.lower())
        if tokens:
            keys.add(tokens[0])
    return keys


def resolve_methodology_entities(
    nodes: Iterable[GraphNode],
    *,
    evidence: tuple[GraphEvidenceReceipt, ...],
    min_similarity: float = 0.55,
    ambiguity_margin: float = 0.1,
) -> tuple[EntityResolutionRecord, ...]:
    """Return deterministic merge/unresolved records for methodology nodes.

    Blocking limits comparisons to shared normalized tokens. Similarity is a
    transparent combination of token Jaccard and character sequence ratio.
    Records are never applied automatically; close alternatives remain
    ``unresolved`` for review and carry the caller's exact receipt.
    """
    if not evidence:
        raise ValueError("entity resolution requires at least one evidence receipt")
    if not 0.0 <= min_similarity <= 1.0:
        raise ValueError("min_similarity must be between 0 and 1")
    if not 0.0 <= ambiguity_margin <= 1.0:
        raise ValueError("ambiguity_margin must be between 0 and 1")

    methodology_nodes = sorted(
        (node for node in nodes if node.node_type == "methodology"),
        key=lambda node: node.node_id,
    )
    blocks: dict[str, list[GraphNode]] = defaultdict(list)
    for node in methodology_nodes:
        for key in _blocking_keys(node):
            blocks[key].append(node)

    pair_scores: dict[tuple[str, str], float] = {}
    pair_nodes: dict[tuple[str, str], tuple[GraphNode, GraphNode]] = {}
    for block_nodes in blocks.values():
        for index, left in enumerate(block_nodes):
            for right in block_nodes[index + 1 :]:
                pair = tuple(sorted((left.node_id, right.node_id)))
                if pair in pair_scores:
                    continue
                score = _similarity(left, right)
                if score >= min_similarity:
                    pair_scores[pair] = score
                    pair_nodes[pair] = (left, right)

    records: list[EntityResolutionRecord] = []
    for pair in sorted(pair_scores):
        score = pair_scores[pair]
        alternatives = [
            other_score
            for other_pair, other_score in pair_scores.items()
            if pair[0] in other_pair or pair[1] in other_pair
            if other_pair != pair
        ]
        ambiguous = any(other_score >= score - ambiguity_margin for other_score in alternatives)
        decision = "unresolved" if ambiguous else "merge"
        key_digest = hashlib.sha256("|".join(pair).encode("utf-8")).hexdigest()[:16]
        records.append(
            EntityResolutionRecord(
                entity_key=f"methodology:{key_digest}",
                candidate_node_ids=pair,
                decision=decision,
                confidence=round(score, 6),
                evidence=evidence,
            )
        )
    return tuple(records)
