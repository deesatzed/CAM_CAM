"""RAG-to-CAG Document Adapter.

Reads documents from external RAG sources (directories, Chroma, LanceDB, FAISS)
and converts them into Methodology objects compatible with CAM's CAG serializer
pipeline. Used by ``cam cag convert``.

Supported formats:
- **directory**: Plain .md, .txt, .json, .yaml files in a directory tree
- **chroma**: ChromaDB persistent storage (requires ``chromadb``)
- **lancedb**: LanceDB tables (requires ``lancedb``)
- **faiss**: FAISS index + LangChain docstore (requires ``pickle``)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from claw.core.models import Methodology

logger = logging.getLogger("claw.memory.rag_adapter")


# ---------------------------------------------------------------------------
# Intermediate representation
# ---------------------------------------------------------------------------

@dataclass
class RAGDocument:
    """A document extracted from an external RAG source."""

    content: str
    source: str = ""
    title: str = ""
    metadata: dict = field(default_factory=dict)
    score: float = 0.5


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _extract_first_paragraph(text: str, max_chars: int = 200) -> str:
    """Return the first non-empty paragraph, truncated to *max_chars*."""
    for para in text.split("\n\n"):
        stripped = para.strip()
        if stripped:
            # Strip leading markdown heading markers
            if stripped.startswith("#"):
                stripped = stripped.lstrip("#").strip()
            return stripped[:max_chars]
    return text[:max_chars]


def _extract_tags(metadata: dict) -> list[str]:
    """Pull tags/labels/categories from metadata and flatten to list[str]."""
    tags: list[str] = []
    for key in ("tags", "labels", "categories", "keywords"):
        val = metadata.get(key)
        if val is None:
            continue
        if isinstance(val, list):
            tags.extend(str(t) for t in val)
        elif isinstance(val, str):
            # Comma-separated string
            tags.extend(t.strip() for t in val.split(",") if t.strip())
    return tags


def _infer_domain(metadata: dict) -> list[str]:
    """Infer domain from metadata keys like domain/category/topic."""
    for key in ("domain", "category", "topic", "subject"):
        val = metadata.get(key)
        if val is None:
            continue
        if isinstance(val, list):
            return [str(d) for d in val]
        if isinstance(val, str) and val.strip():
            return [val.strip()]
    return ["imported"]


# ---------------------------------------------------------------------------
# Format readers
# ---------------------------------------------------------------------------

def read_directory(
    path: Path,
    extensions: Optional[list[str]] = None,
) -> list[RAGDocument]:
    """Read documents from a directory of plain files.

    Supports ``.md``, ``.txt``, ``.json``, and ``.yaml``/``.yml`` files.
    JSON files are handled specially: LangChain export format
    ``[{"page_content": "...", "metadata": {...}}]`` and simple list-of-objects
    format ``[{"content": "...", "title": "..."}]`` are both supported.

    Parameters
    ----------
    path : Path
        Root directory to scan.
    extensions : list[str] | None
        File extensions to include (with leading dot). Defaults to
        ``[".md", ".txt", ".json", ".yaml", ".yml"]``.
    """
    if extensions is None:
        extensions = [".md", ".txt", ".json", ".yaml", ".yml"]

    docs: list[RAGDocument] = []
    root = Path(path)

    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in sorted(filenames):
            fpath = Path(dirpath) / fname
            ext = fpath.suffix.lower()
            if ext not in extensions:
                continue

            try:
                raw = fpath.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                logger.warning("Skipping %s: %s", fpath, exc)
                continue

            if ext in (".json",):
                docs.extend(_parse_json_docs(raw, source=str(fpath)))
            elif ext in (".yaml", ".yml"):
                docs.extend(_parse_yaml_docs(raw, source=str(fpath)))
            else:
                # Plain text / markdown
                title = _extract_md_title(raw, fallback=fpath.stem)
                docs.append(RAGDocument(
                    content=raw,
                    source=str(fpath),
                    title=title,
                ))

    logger.info("read_directory: %d documents from %s", len(docs), root)
    return docs


def _extract_md_title(text: str, fallback: str = "") -> str:
    """Extract the first ``# Heading`` from markdown, or use fallback."""
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return stripped[2:].strip()
    return fallback


def _parse_json_docs(raw: str, source: str = "") -> list[RAGDocument]:
    """Parse JSON text into RAGDocuments.

    Handles:
    - LangChain format: ``[{"page_content": "...", "metadata": {...}}]``
    - Simple list: ``[{"content": "...", "title": "..."}]``
    - Single object with a content field
    - JSONL (one JSON object per line)
    """
    # Try JSONL first (one object per line)
    lines = raw.strip().split("\n")
    if len(lines) > 1 and lines[0].strip().startswith("{"):
        docs: list[RAGDocument] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    doc = _dict_to_rag_doc(obj, source=source)
                    if doc:
                        docs.append(doc)
            except json.JSONDecodeError:
                break  # Not JSONL, fall through to standard JSON parsing
        if docs:
            return docs

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse JSON from %s: %s", source, exc)
        return []

    if isinstance(data, list):
        docs = []
        for item in data:
            if isinstance(item, dict):
                doc = _dict_to_rag_doc(item, source=source)
                if doc:
                    docs.append(doc)
            elif isinstance(item, str):
                docs.append(RAGDocument(content=item, source=source))
        return docs

    if isinstance(data, dict):
        doc = _dict_to_rag_doc(data, source=source)
        return [doc] if doc else []

    return []


def _dict_to_rag_doc(obj: dict, source: str = "") -> Optional[RAGDocument]:
    """Convert a dict to a RAGDocument, trying common field names."""
    # Try common content field names
    content = None
    for key in ("page_content", "content", "text", "body", "document"):
        if key in obj and isinstance(obj[key], str):
            content = obj[key]
            break

    if not content:
        return None

    metadata = obj.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    title = (
        obj.get("title", "")
        or metadata.get("title", "")
        or metadata.get("source", "")
    )

    score = 0.5
    for score_key in ("score", "relevance", "rank"):
        if score_key in obj:
            try:
                score = float(obj[score_key])
            except (TypeError, ValueError):
                pass
            break
        if score_key in metadata:
            try:
                score = float(metadata[score_key])
            except (TypeError, ValueError):
                pass
            break

    return RAGDocument(
        content=content,
        source=source,
        title=str(title) if title else "",
        metadata=metadata,
        score=score,
    )


def _parse_yaml_docs(raw: str, source: str = "") -> list[RAGDocument]:
    """Parse YAML text into RAGDocuments."""
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not installed — skipping YAML file %s", source)
        return []

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse YAML from %s: %s", source, exc)
        return []

    if isinstance(data, list):
        docs = []
        for item in data:
            if isinstance(item, dict):
                doc = _dict_to_rag_doc(item, source=source)
                if doc:
                    docs.append(doc)
        return docs

    if isinstance(data, dict):
        doc = _dict_to_rag_doc(data, source=source)
        return [doc] if doc else []

    return []


def read_chroma(path: Path) -> list[RAGDocument]:
    """Read all documents from a ChromaDB persistent directory.

    Requires ``chromadb`` to be installed.
    """
    try:
        import chromadb
    except ImportError:
        raise ImportError(
            "chromadb is required to read Chroma databases. "
            "Install it with: pip install chromadb"
        )

    client = chromadb.PersistentClient(path=str(path))
    collections = client.list_collections()

    docs: list[RAGDocument] = []
    for collection in collections:
        col_name = collection if isinstance(collection, str) else collection.name
        col = client.get_collection(col_name)
        result = col.get(include=["documents", "metadatas"])

        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or [{}] * len(documents)

        for doc_text, meta in zip(documents, metadatas):
            if not doc_text:
                continue
            meta = meta or {}
            docs.append(RAGDocument(
                content=doc_text,
                source=f"chroma:{col_name}",
                title=meta.get("title", "") or meta.get("source", ""),
                metadata=meta,
            ))

    logger.info("read_chroma: %d documents from %s", len(docs), path)
    return docs


def read_lancedb(path: Path) -> list[RAGDocument]:
    """Read all documents from a LanceDB directory.

    Requires ``lancedb`` to be installed.
    """
    try:
        import lancedb as ldb
    except ImportError:
        raise ImportError(
            "lancedb is required to read LanceDB databases. "
            "Install it with: pip install lancedb"
        )

    db = ldb.connect(str(path))
    table_names = db.list_tables().tables

    docs: list[RAGDocument] = []
    for table_name in table_names:
        table = db.open_table(table_name)
        # LanceDB 0.33 delegates ``to_pandas`` through a LanceDataset method
        # that no longer exists.  Its public Arrow result remains stable.
        rows = table.to_arrow().to_pandas()

        # Find the content column
        content_col = None
        for col_name in ("text", "content", "page_content", "body", "document"):
            if col_name in rows.columns:
                content_col = col_name
                break

        if content_col is None:
            logger.warning(
                "LanceDB table '%s' has no text column (tried: text, content, page_content, body, document). Skipping.",
                table_name,
            )
            continue

        for _, row in rows.iterrows():
            content = str(row[content_col])
            if not content.strip():
                continue

            metadata = {}
            title = ""
            for col in rows.columns:
                if col == content_col or col == "vector":
                    continue
                val = row[col]
                if hasattr(val, "item"):
                    val = val.item()
                metadata[col] = val
                if col == "title" and val:
                    title = str(val)

            docs.append(RAGDocument(
                content=content,
                source=f"lancedb:{table_name}",
                title=title,
                metadata=metadata,
            ))

    logger.info("read_lancedb: %d documents from %s", len(docs), path)
    return docs


def read_faiss(path: Path) -> list[RAGDocument]:
    """Read documents from a FAISS index directory.

    Looks for LangChain's ``index.faiss`` + ``index.pkl`` pattern,
    or a ``docstore.json``/``documents.jsonl`` sidecar file.
    FAISS stores only vectors, so a sidecar with document texts is required.
    """
    import pickle

    faiss_dir = Path(path)

    # Strategy 1: LangChain pattern — index.pkl contains InMemoryDocstore
    pkl_path = faiss_dir / "index.pkl"
    if pkl_path.exists():
        try:
            with open(pkl_path, "rb") as f:
                store = pickle.load(f)  # noqa: S301
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load FAISS docstore from {pkl_path}: {exc}"
            ) from exc

        docs: list[RAGDocument] = []

        # LangChain InMemoryDocstore has a _dict attribute
        docstore_dict = None
        if hasattr(store, "_dict"):
            docstore_dict = store._dict
        elif isinstance(store, dict):
            # Sometimes the pickle IS the dict directly
            if "docstore" in store and hasattr(store["docstore"], "_dict"):
                docstore_dict = store["docstore"]._dict
            elif "index_to_docstore_id" in store and "docstore" in store:
                docstore_dict = getattr(store["docstore"], "_dict", None)

        if docstore_dict is not None:
            for doc_id, doc in docstore_dict.items():
                content = getattr(doc, "page_content", None) or str(doc)
                meta = getattr(doc, "metadata", {}) or {}
                docs.append(RAGDocument(
                    content=content,
                    source=f"faiss:{doc_id}",
                    title=meta.get("title", "") or meta.get("source", ""),
                    metadata=meta if isinstance(meta, dict) else {},
                ))
            logger.info("read_faiss (pkl): %d documents from %s", len(docs), faiss_dir)
            return docs

    # Strategy 2: JSON/JSONL sidecar
    for sidecar_name in ("docstore.json", "documents.json", "documents.jsonl"):
        sidecar = faiss_dir / sidecar_name
        if sidecar.exists():
            raw = sidecar.read_text(encoding="utf-8")
            docs = _parse_json_docs(raw, source=str(sidecar))
            logger.info("read_faiss (sidecar): %d documents from %s", len(docs), sidecar)
            return docs

    raise FileNotFoundError(
        f"FAISS index found at {faiss_dir} but no docstore. "
        f"Expected: index.pkl (LangChain), docstore.json, or documents.jsonl "
        f"with document texts alongside the FAISS index."
    )


# ---------------------------------------------------------------------------
# Format auto-detection
# ---------------------------------------------------------------------------

def auto_detect(path: Path) -> str:
    """Sniff the format of a RAG source directory.

    Returns one of: ``"chroma"``, ``"lancedb"``, ``"faiss"``, ``"directory"``.
    """
    p = Path(path)

    # Chroma: look for chroma.sqlite3
    if (p / "chroma.sqlite3").exists():
        return "chroma"

    # LanceDB: look for .lance directories
    for item in p.iterdir():
        if item.is_dir() and item.suffix == ".lance":
            return "lancedb"

    # FAISS: look for index.faiss
    if (p / "index.faiss").exists():
        return "faiss"

    return "directory"


# ---------------------------------------------------------------------------
# Read dispatcher
# ---------------------------------------------------------------------------

def read_source(path: Path, fmt: Optional[str] = None) -> tuple[list[RAGDocument], str]:
    """Read documents from a RAG source, auto-detecting format if needed.

    Parameters
    ----------
    path : Path
        Path to the RAG source directory.
    fmt : str | None
        Explicit format (``"directory"``, ``"chroma"``, ``"lancedb"``,
        ``"faiss"``). If None, auto-detects.

    Returns
    -------
    tuple[list[RAGDocument], str]
        The documents and the detected/used format name.
    """
    if fmt is None or fmt == "auto":
        fmt = auto_detect(path)

    readers = {
        "directory": read_directory,
        "chroma": read_chroma,
        "lancedb": read_lancedb,
        "faiss": read_faiss,
    }

    reader = readers.get(fmt)
    if reader is None:
        raise ValueError(
            f"Unknown format: {fmt!r}. Supported: {', '.join(readers.keys())}"
        )

    return reader(path), fmt


# ---------------------------------------------------------------------------
# Adapter: RAGDocument → Methodology
# ---------------------------------------------------------------------------

def adapt_to_methodologies(docs: list[RAGDocument]) -> list[Methodology]:
    """Convert RAGDocuments to Methodology objects for CAG serialization.

    Each document becomes one Methodology with:
    - ``problem_description``: document title or first paragraph
    - ``solution_code``: full document content
    - ``tags``: extracted from metadata
    - ``fitness_vector``: ``{"total": score, "imported": score}``
    - ``capability_data``: domain info + ``source_format: "rag_import"``
    """
    results: list[Methodology] = []

    for doc in docs:
        problem = doc.title if doc.title else _extract_first_paragraph(doc.content)

        m = Methodology(
            problem_description=problem or "Imported RAG document",
            solution_code=doc.content,
            methodology_notes=f"Imported from: {doc.source}" if doc.source else None,
            tags=_extract_tags(doc.metadata),
            lifecycle_state="viable",
            fitness_vector={"total": doc.score, "imported": doc.score},
            capability_data={
                "domain": _infer_domain(doc.metadata),
                "source_format": "rag_import",
            },
        )
        results.append(m)

    return results
