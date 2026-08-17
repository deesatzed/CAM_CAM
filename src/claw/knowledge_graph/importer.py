"""Bounded, provenance-first import of a local evidence graph.

The adapter deliberately separates read-only assessment from persistence. A
preview verifies an exact clean Git revision, scans the bounded source scope,
and extracts the graph without opening the target database. Persistence then
requires a content-bound, expiring authorization and consumes its operation ID
once. It never initializes or migrates a database and never calls a provider.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from claw.core.config import DatabaseConfig
from claw.db.engine import DatabaseEngine
from claw.knowledge_graph.contract import EvidenceGraphFixture
from claw.knowledge_graph.extract import extract_evidence_graph
from claw.knowledge_graph.persistence import graph_digest, persist_evidence_graph

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_USED_AUTHORIZATIONS: set[str] = set()
_AUTHORIZATION_LOCK = threading.Lock()
_REQUIRED_TABLES = (
    "evidence_graph_snapshots",
    "evidence_graph_nodes",
    "evidence_graph_edges",
    "evidence_graph_edge_receipts",
    "evidence_graph_entity_resolution",
    "evidence_graph_entity_receipts",
)


class BoundedImportRequest(BaseModel):
    """Exact source, target, and resource limits for one import attempt."""

    model_config = ConfigDict(frozen=True)

    source_root: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    database_path: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1, max_length=160)
    max_files: int = Field(default=2_000, ge=1, le=20_000)
    max_bytes: int = Field(default=25_000_000, ge=1, le=250_000_000)
    timeout_seconds: float = Field(default=60.0, gt=0.0, le=300.0)

    @model_validator(mode="after")
    def validate_bounds_and_revision(self) -> "BoundedImportRequest":
        if not _SHA_RE.fullmatch(self.source_revision):
            raise ValueError("source_revision must be a 40-character lowercase Git SHA")
        if self.max_files < 1:
            raise ValueError("max_files must be positive")
        if self.max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        return self


class BoundedImportAuthorization(BaseModel):
    """One expiring authorization bound to one exact request digest."""

    model_config = ConfigDict(frozen=True)

    operation_id: str = Field(min_length=1, max_length=160)
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    expires_at: datetime


class BoundedImportPreview(BaseModel):
    """Read-only proof produced before any target database write."""

    model_config = ConfigDict(frozen=True)

    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_root: str
    source_revision: str
    database_path: str
    snapshot_id: str
    file_count: int
    byte_count: int
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    node_count: int
    edge_count: int
    elapsed_ms: int
    write_requires_authorization: bool = True


class BoundedImportReceipt(BaseModel):
    """Receipt for a successfully persisted bounded fixture/live import."""

    model_config = ConfigDict(frozen=True)

    operation_id: str
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision: str
    snapshot_id: str
    graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    imported: bool


def _canonical_request(request: BoundedImportRequest) -> dict[str, Any]:
    payload = request.model_dump(mode="json")
    payload["source_root"] = str(Path(request.source_root).expanduser().resolve())
    payload["database_path"] = str(Path(request.database_path).expanduser().resolve())
    return payload


def request_digest(request: BoundedImportRequest) -> str:
    """Return the digest an approval must bind to before a write."""

    encoded = json.dumps(
        _canonical_request(request), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
        raise ValueError(f"source Git identity could not be verified: {detail}")
    return result.stdout.strip()


def _source_identity(root: Path, expected_revision: str) -> None:
    actual = _git(root, "rev-parse", "--verify", "HEAD")
    if actual != expected_revision:
        raise ValueError(
            "source revision changed or does not match request: "
            f"expected {expected_revision}, got {actual}"
        )
    status = _git(root, "status", "--porcelain", "--untracked-files=all")
    if status:
        raise ValueError("source must be a clean Git checkout before import")


def _manifest(
    root: Path, *, deadline: float, max_files: int, max_bytes: int
) -> tuple[int, int, str]:
    paths = sorted(
        {
            *(
                path
                for path in root.rglob("*.py")
                if path.is_file() and not path.is_symlink()
            ),
            *(
                path
                for path in (root / "outcomes").glob("*.json")
                if path.is_file() and not path.is_symlink()
            )
        },
        key=lambda path: path.relative_to(root).as_posix(),
    )
    if len(paths) > max_files:
        raise ValueError(f"source exceeds max_files bound ({len(paths)} > {max_files})")

    entries: list[dict[str, Any]] = []
    total_bytes = 0
    for path in paths:
        if time.monotonic() > deadline:
            raise ValueError("source scan exceeded timeout_seconds bound")
        data = path.read_bytes()
        total_bytes += len(data)
        if total_bytes > max_bytes:
            raise ValueError(f"source exceeds max_bytes bound ({total_bytes} > {max_bytes})")
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    encoded = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return len(paths), total_bytes, hashlib.sha256(encoded).hexdigest()


def _paths(request: BoundedImportRequest) -> tuple[Path, Path]:
    root = Path(request.source_root).expanduser().resolve()
    database = Path(request.database_path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"source_root is not a directory: {root}")
    if not database.is_file():
        raise ValueError(f"database_path must already exist: {database}")
    return root, database


def preview_bounded_import(request: BoundedImportRequest) -> BoundedImportPreview:
    """Assess and extract one bounded source without opening the target DB."""

    started = time.monotonic()
    root, database = _paths(request)
    deadline = started + request.timeout_seconds
    _source_identity(root, request.source_revision)
    file_count, byte_count, manifest = _manifest(
        root,
        deadline=deadline,
        max_files=request.max_files,
        max_bytes=request.max_bytes,
    )
    graph: EvidenceGraphFixture = extract_evidence_graph(
        root, source_revision=request.source_revision, deadline=deadline
    )
    if time.monotonic() > deadline:
        raise ValueError("source extraction exceeded timeout_seconds bound")
    _source_identity(root, request.source_revision)
    post_count, post_bytes, post_manifest = _manifest(
        root,
        deadline=deadline,
        max_files=request.max_files,
        max_bytes=request.max_bytes,
    )
    if (file_count, byte_count, manifest) != (post_count, post_bytes, post_manifest):
        raise ValueError("source changed during bounded extraction")
    return BoundedImportPreview(
        request_digest=request_digest(request),
        source_root=str(root),
        source_revision=request.source_revision,
        database_path=str(database),
        snapshot_id=request.snapshot_id,
        file_count=file_count,
        byte_count=byte_count,
        source_manifest_sha256=manifest,
        graph_sha256=graph_digest(graph),
        node_count=len(graph.nodes),
        edge_count=len(graph.edges),
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )


async def execute_bounded_import(
    request: BoundedImportRequest,
    *,
    authorization: BoundedImportAuthorization,
) -> BoundedImportReceipt:
    """Persist a previewed graph only under one valid, single-use approval."""

    digest = request_digest(request)
    if authorization.request_digest != digest:
        raise ValueError("authorization does not match the exact import request")
    expires_at = authorization.expires_at
    if expires_at.tzinfo is None or expires_at.astimezone(timezone.utc) <= datetime.now(
        timezone.utc
    ):
        raise ValueError("import authorization is expired")

    with _AUTHORIZATION_LOCK:
        if authorization.operation_id in _USED_AUTHORIZATIONS:
            raise ValueError("import authorization was already used")

    preview = preview_bounded_import(request)
    engine = DatabaseEngine(DatabaseConfig(db_path=preview.database_path))
    await engine.connect()
    try:
        rows = await engine.fetch_all(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN (?, ?, ?, ?, ?, ?)",
            list(_REQUIRED_TABLES),
        )
        if {row["name"] for row in rows} != set(_REQUIRED_TABLES):
            raise ValueError("target database is missing the evidence graph schema")
        with _AUTHORIZATION_LOCK:
            if authorization.operation_id in _USED_AUTHORIZATIONS:
                raise ValueError("import authorization was already used")
            _USED_AUTHORIZATIONS.add(authorization.operation_id)

        graph = extract_evidence_graph(
            Path(preview.source_root),
            source_revision=preview.source_revision,
            deadline=time.monotonic() + request.timeout_seconds,
        )
        if graph_digest(graph) != preview.graph_sha256:
            raise ValueError("source graph changed after the read-only preview")
        await persist_evidence_graph(
            engine, snapshot_id=preview.snapshot_id, graph=graph
        )
        return BoundedImportReceipt(
            operation_id=authorization.operation_id,
            request_digest=preview.request_digest,
            source_revision=preview.source_revision,
            snapshot_id=preview.snapshot_id,
            graph_sha256=preview.graph_sha256,
            imported=True,
        )
    finally:
        await engine.close()
