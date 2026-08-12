"""Tests for the read-only CAM command capability manifest."""

from __future__ import annotations

import json

from typer.testing import CliRunner


def _items_by_path(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    return {item["path"]: item for item in payload["items"]}  # type: ignore[index]


def test_manifest_recursively_inventories_commands_groups_and_hidden_status() -> None:
    from claw.cli import app
    from claw.cli.capability_manifest import build_capability_manifest

    payload = build_capability_manifest(app)
    items = _items_by_path(payload)

    assert payload["schema_version"] == 1
    assert len(items) == len(payload["items"])
    assert items["mine"] == {"path": "mine", "kind": "command", "hidden": False}
    assert items["models"] == {"path": "models", "kind": "group", "hidden": False}
    assert items["models benchmark run"] == {
        "path": "models benchmark run",
        "kind": "command",
        "hidden": False,
    }
    assert items["forge-export"] == {
        "path": "forge-export",
        "kind": "command",
        "hidden": True,
    }
    assert items["evolution approve"] == {
        "path": "evolution approve",
        "kind": "command",
        "hidden": True,
    }


def test_manifest_output_is_deterministically_sorted() -> None:
    from claw.cli import app
    from claw.cli.capability_manifest import build_capability_manifest

    first = build_capability_manifest(app)
    second = build_capability_manifest(app)

    assert first == second
    assert first["items"] == sorted(
        first["items"],
        key=lambda item: (item["path"], item["kind"]),
    )
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_doctor_capabilities_json_is_read_only(monkeypatch, tmp_path) -> None:
    import httpx

    from claw.cli import app
    from claw.core.factory import ClawFactory
    from claw.db.engine import DatabaseEngine

    def unexpected_call(*args, **kwargs):
        raise AssertionError("capability inventory crossed a runtime side-effect boundary")

    monkeypatch.setattr("claw.core.config.load_config", unexpected_call)
    monkeypatch.setattr(ClawFactory, "create", unexpected_call)
    monkeypatch.setattr(DatabaseEngine, "connect", unexpected_call)
    monkeypatch.setattr(httpx.Client, "request", unexpected_call)
    monkeypatch.setattr(httpx.AsyncClient, "request", unexpected_call)

    monkeypatch.chdir(tmp_path)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    result = CliRunner().invoke(app, ["doctor", "capabilities", "--json"])

    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert _items_by_path(payload)["doctor capabilities"]["hidden"] is False
    assert after == before
