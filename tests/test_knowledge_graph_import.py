"""Bounded, authorization-gated evidence-graph import tests."""

from __future__ import annotations

import asyncio
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from claw.core.config import DatabaseConfig
from claw.db.engine import DatabaseEngine
from claw.knowledge_graph.importer import (
    BoundedImportAuthorization,
    BoundedImportRequest,
    execute_bounded_import,
    preview_bounded_import,
    request_digest,
)


def _git_source(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "source"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "outcomes").mkdir()
    (root / "src" / "auth.py").write_text(
        "def validate_token(value: str) -> bool:\n    return bool(value)\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_auth.py").write_text(
        "from src.auth import validate_token\n\n"
        "def test_validate_token():\n    assert validate_token('ok')\n",
        encoding="utf-8",
    )
    (root / "outcomes" / "auth.json").write_text(
        '{"symbol": "validate_token"}\n', encoding="utf-8"
    )
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(root), "config", "user.name", "CAM tests"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "--quiet", "-m", "fixture"], check=True)
    revision = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"], text=True
    ).strip()
    return root, revision


def _request(
    root: Path, revision: str, database: Path, **overrides: object
) -> BoundedImportRequest:
    values: dict[str, object] = {
        "source_root": str(root),
        "source_revision": revision,
        "database_path": str(database),
        "snapshot_id": "live-fixture-v1",
    }
    values.update(overrides)
    return BoundedImportRequest.model_validate(values)


def test_request_rejects_mutable_revision_and_unbounded_values(tmp_path: Path) -> None:
    root, _revision = _git_source(tmp_path)
    database = tmp_path / "graph.db"

    with pytest.raises(ValueError, match="40-character"):
        _request(root, "main", database)
    with pytest.raises(ValueError, match="max_files"):
        _request(root, "0" * 40, database, max_files=0)


def test_preview_is_read_only_and_enforces_file_bound(tmp_path: Path) -> None:
    root, revision = _git_source(tmp_path)
    database = tmp_path / "graph.db"
    database.write_bytes(b"sentinel")
    request = _request(root, revision, database, max_files=1)

    with pytest.raises(ValueError, match="max_files"):
        preview_bounded_import(request)
    assert database.read_bytes() == b"sentinel"


def test_preview_requires_clean_source_and_reports_content_digest(tmp_path: Path) -> None:
    root, revision = _git_source(tmp_path)
    database = tmp_path / "graph.db"
    database.write_bytes(b"sentinel")
    preview = preview_bounded_import(_request(root, revision, database))

    assert preview.source_revision == revision
    assert preview.file_count == 3
    assert len(preview.graph_sha256) == 64
    assert preview.write_requires_authorization is True
    assert database.read_bytes() == b"sentinel"

    (root / "src" / "uncommitted.py").write_text(
        "def changed():\n    return True\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="clean"):
        preview_bounded_import(_request(root, revision, database))


def test_execute_requires_content_bound_authorization_and_is_single_use(tmp_path: Path) -> None:
    root, revision = _git_source(tmp_path)
    database = tmp_path / "graph.db"
    engine = DatabaseEngine(DatabaseConfig(db_path=str(database)))

    async def prepare() -> None:
        await engine.connect()
        await engine.apply_migrations()
        await engine.initialize_schema()
        await engine.close()

    asyncio.run(prepare())
    request = _request(root, revision, database)
    preview = preview_bounded_import(request)
    expired = BoundedImportAuthorization(
        operation_id="expired",
        request_digest=preview.request_digest,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="expired"):
        asyncio.run(execute_bounded_import(request, authorization=expired))

    authorization = BoundedImportAuthorization(
        operation_id="fixture-import-1",
        request_digest=request_digest(request),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    receipt = asyncio.run(execute_bounded_import(request, authorization=authorization))
    assert receipt.imported is True
    assert receipt.operation_id == "fixture-import-1"

    with pytest.raises(ValueError, match="already used"):
        asyncio.run(execute_bounded_import(request, authorization=authorization))

    async def count() -> int:
        check = DatabaseEngine(DatabaseConfig(db_path=str(database)))
        await check.connect()
        try:
            row = await check.fetch_one(
                "SELECT COUNT(*) AS count FROM evidence_graph_snapshots WHERE snapshot_id = ?",
                [request.snapshot_id],
            )
            return int(row["count"])
        finally:
            await check.close()

    assert asyncio.run(count()) == 1
