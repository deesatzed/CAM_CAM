from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

import pytest
from typer.testing import CliRunner


MODULE_PATH = Path(__file__).parents[1] / "src" / "claw" / "briefing" / "read_only_query.py"


def _query_module():
    assert MODULE_PATH.is_file(), "read-only Development Brief query module is missing"
    spec = importlib.util.spec_from_file_location("read_only_brief_query", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _create_corpus(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE methodologies (
                id TEXT PRIMARY KEY,
                problem_description TEXT NOT NULL,
                methodology_notes TEXT,
                tags TEXT NOT NULL,
                language TEXT,
                lifecycle_state TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE methodology_fts USING fts5(
                methodology_id UNINDEXED,
                problem_description,
                methodology_notes,
                tags
            );
            """
        )
        connection.execute(
            """
            INSERT INTO methodologies
              (id, problem_description, methodology_notes, tags, language, lifecycle_state)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "method-retry-1",
                "Retry imports after transient network failures",
                "Use bounded retries with a durable state transition.",
                json.dumps(["retry", "import", "source:fixture-repo"]),
                "python",
                "viable",
            ),
        )
        connection.execute(
            """
            INSERT INTO methodology_fts
              (methodology_id, problem_description, methodology_notes, tags)
            VALUES (?, ?, ?, ?)
            """,
            (
                "method-retry-1",
                "Retry imports after transient network failures",
                "Use bounded retries with a durable state transition.",
                "retry import source:fixture-repo",
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _database_state(path: Path) -> tuple[str, tuple[str, ...]]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    files = tuple(sorted(item.name for item in path.parent.iterdir()))
    return digest, files


def test_query_primary_corpus_returns_provenance_without_database_mutation(tmp_path: Path) -> None:
    brief_query = _query_module()
    database = tmp_path / "claw.db"
    _create_corpus(database)
    before = _database_state(database)

    payload = brief_query.query_primary_corpus(database, "retry imports", limit=3)

    assert payload["schema_version"] == 1
    assert payload["scope"] == "primary_only"
    assert payload["query"] == "retry imports"
    assert len(payload["results"]) == 1
    result = payload["results"][0]
    assert result["methodology_id"] == "method-retry-1"
    assert result["problem_description"] == "Retry imports after transient network failures"
    assert result["methodology_notes"] == "Use bounded retries with a durable state transition."
    assert result["tags"] == ["retry", "import", "source:fixture-repo"]
    assert result["language"] == "python"
    assert result["lifecycle_state"] == "viable"
    assert isinstance(result["text_score"], float)
    assert _database_state(database) == before
    assert not list(tmp_path.glob("claw.db-*"))


def test_multi_clause_primary_query_returns_partial_evidence_instead_of_empty(tmp_path: Path) -> None:
    """A long task brief must not disappear because one token is absent."""
    brief_query = _query_module()
    database = tmp_path / "claw.db"
    _create_corpus(database)

    payload = brief_query.query_primary_corpus(
        database,
        "retry imports checkpoint recovery",
        limit=3,
    )

    assert [item["methodology_id"] for item in payload["results"]] == ["method-retry-1"]


def test_query_rejects_invalid_input_without_creating_a_database(tmp_path: Path) -> None:
    brief_query = _query_module()
    missing_database = tmp_path / "missing.db"

    with pytest.raises(brief_query.ReadOnlyQueryError, match="does not exist"):
        brief_query.query_primary_corpus(missing_database, "retry")
    with pytest.raises(brief_query.ReadOnlyQueryError, match="query"):
        brief_query.query_primary_corpus(missing_database, "  ")

    assert not missing_database.exists()


def test_brief_query_cli_returns_json_and_reports_errors_structurally(tmp_path: Path) -> None:
    from claw.cli._monolith import app

    database = tmp_path / "claw.db"
    _create_corpus(database)
    runner = CliRunner()

    result = runner.invoke(app, ["brief-query", "retry imports", "--db", str(database), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["scope"] == "primary_only"
    assert payload["results"][0]["methodology_id"] == "method-retry-1"

    missing = runner.invoke(
        app,
        ["brief-query", "retry", "--db", str(tmp_path / "missing.db"), "--json"],
    )

    assert missing.exit_code == 2
    error_payload = json.loads(missing.output)
    assert error_payload["status"] == "error"
    assert "does not exist" in error_payload["error"]


def test_read_only_query_never_imports_mutating_runtime_paths() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8") if MODULE_PATH.exists() else ""

    assert "ClawFactory" not in source
    assert "SemanticMemory" not in source
    assert "EmbeddingEngine" not in source
    assert "Federation" not in source
    assert "update_methodology_retrieval" not in source
