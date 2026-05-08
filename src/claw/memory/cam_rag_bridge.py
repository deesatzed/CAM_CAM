"""Optional bridge between CAM_CAM and the external CAM-RAG package.

This module keeps CAM-RAG as a specialist package while giving CAM_CAM a stable
contract for ingesting text, retrieving grounded chunks, and emitting receipts
that can be stored in CAM memory.
"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


class CamRagUnavailableError(RuntimeError):
    """Raised when CAM-RAG is not installed but an operation needs it."""


@dataclass(frozen=True)
class RagDocument:
    """Document payload normalized before handing it to CAM-RAG."""

    id: str
    text: str
    metadata: dict[str, str] = field(default_factory=dict)
    domain: str = "default"


@dataclass(frozen=True)
class RagChunk:
    """Grounded retrieval result normalized for CAM_CAM."""

    document_id: str
    text: str
    score: float
    citation: str
    confidence: float
    metadata: dict[str, str] = field(default_factory=dict)
    routing_reason: str | None = None


@dataclass(frozen=True)
class RagReceipt:
    """Machine-readable receipt for CAM memory/proof artifacts."""

    query: str
    adapter: str
    result_count: int
    citations: list[str]
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "adapter": self.adapter,
            "result_count": self.result_count,
            "citations": list(self.citations),
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }


class CamRagBridge:
    """Adapter contract for the external `cam_rag` package.

    The current implementation uses CAM-RAG's deterministic retriever when the
    package is importable. CAM_CAM remains independent at install time.
    """

    def __init__(self, module_name: str = "cam_rag", rules_path: str | None = None) -> None:
        self.module_name = module_name
        self.rules_path = rules_path
        self._module: Any | None = None
        self._retriever: Any | None = None

    @property
    def available(self) -> bool:
        try:
            self._load_module()
        except CamRagUnavailableError:
            return False
        return True

    def ingest_documents(self, documents: Iterable[RagDocument]) -> int:
        """Index documents through CAM-RAG and return the indexed count."""
        module = self._load_module()
        retriever = self._get_retriever(module)
        native_docs = [
            module.Document(
                id=doc.id,
                text=doc.text,
                metadata=dict(doc.metadata),
                domain=doc.domain,
            )
            for doc in documents
            if doc.text.strip()
        ]
        retriever.index_documents(native_docs)
        return len(native_docs)

    def ingest_folder(
        self,
        folder: str | Path,
        *,
        domain: str = "default",
        suffixes: tuple[str, ...] = (".md", ".txt", ".rst"),
    ) -> int:
        """Index simple text files from a folder."""
        root = Path(folder)
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"RAG folder does not exist: {root}")
        docs: list[RagDocument] = []
        allowed = {suffix.lower() for suffix in suffixes}
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in allowed:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            docs.append(
                RagDocument(
                    id=str(path.relative_to(root)),
                    text=text,
                    metadata={"path": str(path), "name": path.name},
                    domain=domain,
                )
            )
        return self.ingest_documents(docs)

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        domain: str | None = None,
    ) -> list[RagChunk]:
        """Retrieve grounded chunks with citations and confidence metadata."""
        if not query.strip():
            return []
        module = self._load_module()
        retriever = self._get_retriever(module)
        try:
            results = retriever.retrieve(query, top_k=top_k, domain=domain)
        except Exception:
            return self._fallback_retrieve(retriever, query, top_k=top_k, domain=domain)
        chunks: list[RagChunk] = []
        for result in results:
            doc = result.document
            score = float(result.score)
            chunks.append(
                RagChunk(
                    document_id=str(doc.id),
                    text=str(doc.text),
                    score=score,
                    citation=self._citation_for(doc),
                    confidence=max(0.0, min(score, 1.0)),
                    metadata=dict(getattr(doc, "metadata", {}) or {}),
                    routing_reason=getattr(result, "routing_reason", None),
                )
            )
        return chunks

    def receipt_for(self, query: str, chunks: list[RagChunk]) -> RagReceipt:
        """Build a compact receipt that CAM can store with task evidence."""
        confidence = 0.0
        if chunks:
            confidence = sum(chunk.confidence for chunk in chunks) / len(chunks)
        return RagReceipt(
            query=query,
            adapter=self.module_name,
            result_count=len(chunks),
            citations=[chunk.citation for chunk in chunks],
            confidence=round(confidence, 4),
            metadata={
                "document_ids": [chunk.document_id for chunk in chunks],
                "scores": [chunk.score for chunk in chunks],
            },
        )

    def _load_module(self) -> Any:
        if self._module is not None:
            return self._module
        try:
            self._module = importlib.import_module(self.module_name)
        except ImportError as exc:
            raise CamRagUnavailableError(
                "CAM-RAG is not installed. Install it with `pip install -e ../CAM-RAG` "
                "or set PYTHONPATH to include its `src` directory."
            ) from exc
        required = ("Document", "DeterministicRetriever")
        missing = [name for name in required if not hasattr(self._module, name)]
        if missing:
            raise CamRagUnavailableError(
                f"CAM-RAG module '{self.module_name}' is missing: {', '.join(missing)}"
            )
        return self._module

    def _get_retriever(self, module: Any) -> Any:
        if self._retriever is None:
            self._retriever = module.DeterministicRetriever(rules_path=self.rules_path)
        return self._retriever

    def _fallback_retrieve(
        self,
        retriever: Any,
        query: str,
        *,
        top_k: int,
        domain: str | None,
    ) -> list[RagChunk]:
        """Recover when an optional CAM-RAG backend raises during retrieval."""
        docs = self._indexed_documents(retriever)
        query_terms = set(_tokenize(query))
        if not query_terms:
            return []
        scored: list[tuple[float, Any]] = []
        for doc in docs:
            if domain and getattr(doc, "domain", None) != domain:
                continue
            text_terms = set(_tokenize(str(getattr(doc, "text", ""))))
            if not text_terms:
                continue
            overlap = len(query_terms & text_terms)
            if overlap <= 0:
                continue
            score = overlap / max(len(query_terms), 1)
            scored.append((score, doc))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            RagChunk(
                document_id=str(getattr(doc, "id", "")),
                text=str(getattr(doc, "text", "")),
                score=score,
                citation=self._citation_for(doc),
                confidence=max(0.0, min(score, 1.0)),
                metadata=dict(getattr(doc, "metadata", {}) or {}),
                routing_reason="cam_rag_bridge_fallback",
            )
            for score, doc in scored[:top_k]
        ]

    @staticmethod
    def _indexed_documents(retriever: Any) -> list[Any]:
        raw_docs = getattr(retriever, "_documents", None)
        if isinstance(raw_docs, dict):
            return list(raw_docs.values())
        if isinstance(raw_docs, list):
            return raw_docs
        docs = getattr(retriever, "documents", None)
        if isinstance(docs, list):
            return docs
        return []

    @staticmethod
    def _citation_for(doc: Any) -> str:
        metadata = dict(getattr(doc, "metadata", {}) or {})
        return metadata.get("path") or metadata.get("source") or str(doc.id)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9]+", text.lower())
