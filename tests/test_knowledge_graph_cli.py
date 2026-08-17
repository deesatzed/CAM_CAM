"""Read-only CAM knowledge-graph troubleshooting command tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from typer.testing import CliRunner

from claw.core.config import DatabaseConfig
from claw.db.engine import DatabaseEngine
from claw.knowledge_graph.contract import EvidenceGraphFixture
from claw.knowledge_graph.persistence import persist_evidence_graph

FIXTURE = Path(__file__).parent / "fixtures" / "evidence_graph_v1" / "graph.json"


def _prepare_database(path: Path) -> None:
    async def prepare() -> None:
        engine = DatabaseEngine(DatabaseConfig(db_path=str(path)))
        await engine.connect()
        await engine.apply_migrations()
        await engine.initialize_schema()
        graph = EvidenceGraphFixture.model_validate_json(FIXTURE.read_text())
        await persist_evidence_graph(engine, snapshot_id="fixture-auth-v1", graph=graph)
        await engine.close()

    asyncio.run(prepare())


def test_knowledge_graph_query_is_hidden_read_only_command() -> None:
    from claw.cli import app
    from claw.cli.capability_manifest import build_capability_manifest

    items = {
        item["path"]: item
        for item in build_capability_manifest(app)["items"]
    }
    assert items["knowledge-graph-query"] == {
        "path": "knowledge-graph-query",
        "kind": "command",
        "hidden": True,
    }


def test_knowledge_graph_query_reads_named_snapshot_as_json(tmp_path: Path) -> None:
    from claw.cli import app

    database = tmp_path / "graph.db"
    _prepare_database(database)
    result = CliRunner().invoke(
        app,
        [
            "knowledge-graph-query",
            "--db",
            str(database),
            "--snapshot-id",
            "fixture-auth-v1",
            "--seed-node-id",
            "source_file:auth_service",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["snapshot_id"] == "fixture-auth-v1"
    assert payload["edges"][0]["edge_type"] == "declares"


def test_knowledge_graph_query_refuses_missing_database(tmp_path: Path) -> None:
    from claw.cli import app

    result = CliRunner().invoke(
        app,
        [
            "knowledge-graph-query",
            "--db",
            str(tmp_path / "typo.db"),
            "--snapshot-id",
            "fixture-auth-v1",
            "--seed-node-id",
            "source_file:auth_service",
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "already exist" in result.stdout
