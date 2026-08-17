"""Deterministic local extraction of explicit Python evidence edges."""

from __future__ import annotations

import ast
import hashlib
import json
import time
from pathlib import Path

from claw.knowledge_graph.contract import (
    SCHEMA_VERSION,
    EvidenceClass,
    EvidenceGraphFixture,
    GraphEdge,
    GraphEvidenceReceipt,
    GraphNode,
)


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _receipt(root: Path, path: Path, revision: str, method: str) -> GraphEvidenceReceipt:
    data = path.read_bytes()
    return GraphEvidenceReceipt(
        source_uri=f"file:{_relative(root, path)}",
        source_revision=revision,
        content_sha256=hashlib.sha256(data).hexdigest(),
        extraction_method=method,
    )


def _module_name(path: Path) -> str:
    return path.stem


def extract_evidence_graph(
    root: Path,
    *,
    source_revision: str,
    deadline: float | None = None,
) -> EvidenceGraphFixture:
    """Extract only explicit local Python/test/outcome relationships.

    The extractor deliberately does not infer relationships from prose,
    embeddings, proximity, or co-retrieval. Unsupported imports and outcomes
    remain absent rather than being guessed.
    """
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Evidence graph root is not a directory: {root}")

    python_paths = sorted(path for path in root.rglob("*.py") if path.is_file())
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    parsed: dict[Path, ast.Module] = {}
    exports: dict[str, str] = {}

    for path in python_paths:
        if deadline is not None and time.monotonic() > deadline:
            raise ValueError("evidence graph extraction exceeded its deadline")
        relative = _relative(root, path)
        source_id = f"source_file:{relative}"
        nodes.append(
            GraphNode(
                node_id=source_id,
                node_type="source_file",
                canonical_name=relative,
            )
        )
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        parsed[path] = tree
        receipt = _receipt(root, path, source_revision, "python_ast")
        for definition in tree.body:
            if not isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if definition.name.startswith("test_"):
                continue
            symbol_id = f"symbol:{relative}::{definition.name}"
            nodes.append(
                GraphNode(
                    node_id=symbol_id,
                    node_type="symbol",
                    canonical_name=definition.name,
                )
            )
            exports.setdefault(definition.name, symbol_id)
            edges.append(
                GraphEdge(
                    edge_id=f"edge:declares:{relative}:{definition.name}",
                    source_id=source_id,
                    target_id=symbol_id,
                    edge_type="declares",
                    evidence_class=EvidenceClass.EXPLICIT,
                    confidence=1.0,
                    factual_path_eligible=True,
                    evidence=(receipt,),
                )
            )

    for path, tree in parsed.items():
        if deadline is not None and time.monotonic() > deadline:
            raise ValueError("evidence graph extraction exceeded its deadline")
        relative = _relative(root, path)
        if not relative.startswith("tests/"):
            continue
        imported_names: dict[str, str] = {}
        for statement in tree.body:
            if not isinstance(statement, ast.ImportFrom) or not statement.module:
                continue
            for imported in statement.names:
                if imported.name in exports:
                    imported_names[imported.asname or imported.name] = exports[imported.name]
        receipt = _receipt(root, path, source_revision, "python_ast_test_reference")
        for definition in tree.body:
            if not isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not definition.name.startswith("test_"):
                continue
            test_id = f"test:{relative}::{definition.name}"
            nodes.append(
                GraphNode(
                    node_id=test_id,
                    node_type="test",
                    canonical_name=definition.name,
                )
            )
            called_names = sorted(
                {
                    call.func.id
                    for call in ast.walk(definition)
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    and call.func.id in imported_names
                }
            )
            for called_name in called_names:
                source_id = imported_names[called_name]
                edges.append(
                    GraphEdge(
                        edge_id=f"edge:covered_by:{source_id}:{test_id}",
                        source_id=source_id,
                        target_id=test_id,
                        edge_type="covered_by",
                        evidence_class=EvidenceClass.EXPLICIT,
                        confidence=1.0,
                        factual_path_eligible=True,
                        evidence=(receipt,),
                    )
                )

    outcome_dir = root / "outcomes"
    for path in sorted(outcome_dir.glob("*.json")) if outcome_dir.is_dir() else []:
        if deadline is not None and time.monotonic() > deadline:
            raise ValueError("evidence graph extraction exceeded its deadline")
        relative = _relative(root, path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        outcome_id = f"outcome:{relative}"
        nodes.append(
            GraphNode(
                node_id=outcome_id,
                node_type="outcome",
                canonical_name=path.stem,
            )
        )
        symbol_name = payload.get("symbol")
        if not isinstance(symbol_name, str) or symbol_name not in exports:
            continue
        edges.append(
            GraphEdge(
                edge_id=f"edge:verified_by:{exports[symbol_name]}:{outcome_id}",
                source_id=exports[symbol_name],
                target_id=outcome_id,
                edge_type="verified_by",
                evidence_class=EvidenceClass.EXPLICIT,
                confidence=1.0,
                factual_path_eligible=True,
                evidence=(_receipt(root, path, source_revision, "outcome_receipt"),),
            )
        )

    return EvidenceGraphFixture(
        schema_version=SCHEMA_VERSION,
        nodes=tuple(sorted(nodes, key=lambda node: node.node_id)),
        edges=tuple(sorted(edges, key=lambda edge: edge.edge_id)),
    )
