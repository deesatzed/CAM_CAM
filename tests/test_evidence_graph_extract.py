from __future__ import annotations

import hashlib
from pathlib import Path

from claw.knowledge_graph.extract import extract_evidence_graph

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "evidence_graph_v1"


def test_python_fixture_extraction_emits_receipt_backed_explicit_edges() -> None:
    graph = extract_evidence_graph(FIXTURE_ROOT, source_revision="fixture-auth-v1")

    nodes = {node.node_id for node in graph.nodes}
    assert {
        "source_file:src/auth_service.py",
        "symbol:src/auth_service.py::validate_token",
        "test:tests/auth_test_fixture.py::test_validate_token_rejects_empty_value",
        "outcome:outcomes/token-validation.json",
    } <= nodes

    by_type = {edge.edge_type: edge for edge in graph.edges}
    assert by_type["declares"].source_id == "source_file:src/auth_service.py"
    assert by_type["covered_by"].target_id == (
        "test:tests/auth_test_fixture.py::test_validate_token_rejects_empty_value"
    )
    assert by_type["verified_by"].target_id == "outcome:outcomes/token-validation.json"
    assert all(edge.evidence_class.value == "explicit" for edge in graph.edges)
    assert all(edge.factual_path_eligible for edge in graph.edges)

    source_hash = hashlib.sha256(
        (FIXTURE_ROOT / "src" / "auth_service.py").read_bytes()
    ).hexdigest()
    declaration_receipt = by_type["declares"].evidence[0]
    assert declaration_receipt.source_uri == "file:src/auth_service.py"
    assert declaration_receipt.source_revision == "fixture-auth-v1"
    assert declaration_receipt.content_sha256 == source_hash
