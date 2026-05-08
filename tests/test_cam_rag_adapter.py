"""Tests for the optional CAM-RAG adapter contract."""

from __future__ import annotations

import sys
import types

import pytest

from claw.memory.cam_rag_bridge import (
    CamRagBridge,
    CamRagUnavailableError,
    RagDocument,
)
from claw.memory.rag_adapter import read_directory


class FakeDocument:
    def __init__(self, id: str, text: str, metadata=None, domain: str = "default"):
        self.id = id
        self.text = text
        self.metadata = metadata or {}
        self.domain = domain


class FakeRetrievalResult:
    def __init__(self, document, score: float, routing_reason=None):
        self.document = document
        self.score = score
        self.routing_reason = routing_reason


class FakeDeterministicRetriever:
    def __init__(self, rules_path=None):
        self.rules_path = rules_path
        self.documents = []

    def index_documents(self, documents):
        self.documents.extend(documents)

    def retrieve(self, query: str, top_k: int = 5, domain=None):
        candidates = self.documents
        if domain:
            candidates = [doc for doc in candidates if doc.domain == domain]
        matches = [
            FakeRetrievalResult(doc, 0.9, "fake match")
            for doc in candidates
            if query.lower() in doc.text.lower()
        ]
        return matches[:top_k]


@pytest.fixture
def fake_cam_rag_module(monkeypatch):
    module = types.ModuleType("fake_cam_rag")
    module.Document = FakeDocument
    module.DeterministicRetriever = FakeDeterministicRetriever
    monkeypatch.setitem(sys.modules, "fake_cam_rag", module)
    return module


def test_adapter_reports_unavailable_for_missing_module():
    adapter = CamRagBridge(module_name="definitely_missing_cam_rag_module")

    assert adapter.available is False
    with pytest.raises(CamRagUnavailableError):
        adapter.ingest_documents([])


def test_adapter_ingests_retrieves_and_emits_receipt(fake_cam_rag_module):
    adapter = CamRagBridge(module_name="fake_cam_rag")
    indexed = adapter.ingest_documents([
        RagDocument(
            id="design-note",
            text="Repo Rescue Desk should call RAG for cited context.",
            metadata={"path": "docs/design-note.md"},
            domain="cam",
        ),
        RagDocument(
            id="other",
            text="Unrelated material.",
            metadata={"path": "docs/other.md"},
            domain="cam",
        ),
    ])

    chunks = adapter.retrieve("cited context", top_k=3, domain="cam")
    receipt = adapter.receipt_for("cited context", chunks)

    assert indexed == 2
    assert len(chunks) == 1
    assert chunks[0].document_id == "design-note"
    assert chunks[0].citation == "docs/design-note.md"
    assert chunks[0].confidence == 0.9
    assert receipt.as_dict()["result_count"] == 1
    assert receipt.as_dict()["citations"] == ["docs/design-note.md"]


def test_existing_rag_to_cag_directory_reader_still_works(tmp_path):
    note = tmp_path / "note.md"
    note.write_text("# Existing Adapter\n\nThis should still parse.", encoding="utf-8")

    docs = read_directory(tmp_path)

    assert len(docs) == 1
    assert docs[0].title == "Existing Adapter"
