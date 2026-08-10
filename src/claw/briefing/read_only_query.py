"""Read primary CAM methodology records without modifying SQLite state.

This intentionally does not use ``DatabaseEngine`` or the normal semantic
memory path: those interfaces can configure WAL, record retrieval usage, or
otherwise exceed a Development Brief's no-write default.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
from typing import Any


SCHEMA_VERSION = 1
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")


class ReadOnlyQueryError(ValueError):
    """Raised when a local primary-corpus query cannot run safely."""


def _safe_fts_query(query: str) -> str:
    if not isinstance(query, str) or not query.strip():
        raise ReadOnlyQueryError("query must be non-empty")
    tokens = _TOKEN_PATTERN.findall(query)
    if not tokens:
        raise ReadOnlyQueryError("query must contain searchable text")
    return " AND ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def _read_only_uri(database: Path) -> str:
    return f"{database.resolve().as_uri()}?mode=ro&immutable=1"


def _parse_tags(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, str)]


def query_primary_corpus(database: Path, query: str, *, limit: int = 10) -> dict[str, Any]:
    """Return FTS provenance from one existing CAM primary database.

    The connection is immutable and URI read-only.  It cannot initialize a
    schema, alter a journal, increment retrieval counts, or search siblings.
    """

    fts_query = _safe_fts_query(query)
    if not isinstance(limit, int) or not 1 <= limit <= 20:
        raise ReadOnlyQueryError("limit must be an integer between 1 and 20")
    path = Path(database).expanduser()
    if not path.is_file():
        raise ReadOnlyQueryError(f"database does not exist or is not a file: {path}")

    try:
        connection = sqlite3.connect(_read_only_uri(path), uri=True)
        connection.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        raise ReadOnlyQueryError(f"cannot open database read-only: {exc}") from exc

    try:
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute(
            """
            SELECT
                m.id AS methodology_id,
                m.problem_description,
                m.methodology_notes,
                m.tags,
                m.language,
                m.lifecycle_state,
                f.rank AS text_score
            FROM methodology_fts AS f
            JOIN methodologies AS m ON m.id = f.methodology_id
            WHERE methodology_fts MATCH ?
            ORDER BY f.rank
            LIMIT ?
            """,
            (fts_query, limit),
        ).fetchall()
    except sqlite3.Error as exc:
        raise ReadOnlyQueryError(f"primary-corpus query failed: {exc}") from exc
    finally:
        connection.close()

    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "primary_only",
        "query": query.strip(),
        "results": [
            {
                "methodology_id": str(row["methodology_id"]),
                "problem_description": str(row["problem_description"] or ""),
                "methodology_notes": str(row["methodology_notes"] or ""),
                "tags": _parse_tags(row["tags"]),
                "language": str(row["language"] or ""),
                "lifecycle_state": str(row["lifecycle_state"] or ""),
                "text_score": float(row["text_score"]),
            }
            for row in rows
        ],
    }
