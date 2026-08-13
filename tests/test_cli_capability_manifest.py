"""Tests for the read-only CAM command capability manifest."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest
import typer
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


def test_unnamed_hidden_group_does_not_hide_flattened_child() -> None:
    from claw.cli.capability_manifest import build_capability_manifest

    root = typer.Typer()
    unnamed = typer.Typer(hidden=True)

    @unnamed.command()
    def visible_child() -> None:
        pass

    root.add_typer(unnamed)

    assert _items_by_path(build_capability_manifest(root))["visible-child"] == {
        "path": "visible-child",
        "kind": "command",
        "hidden": False,
    }


def test_duplicate_paths_are_sorted_in_error_diagnostics() -> None:
    from claw.cli.capability_manifest import build_capability_manifest

    root = typer.Typer()

    @root.command("zeta")
    def zeta_one() -> None:
        pass

    @root.command("alpha")
    def alpha_one() -> None:
        pass

    @root.command("zeta")
    def zeta_two() -> None:
        pass

    @root.command("alpha")
    def alpha_two() -> None:
        pass

    with pytest.raises(
        ValueError,
        match=r"duplicate invocation paths: alpha, zeta$",
    ):
        build_capability_manifest(root)


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


def test_doctor_capabilities_is_side_effect_free_from_fresh_process(tmp_path) -> None:
    sentinel_dir = tmp_path / "isolated-home"
    sentinel_dir.mkdir()
    sentinel = sentinel_dir / "sentinel.txt"
    sentinel.write_text("do not mutate\n", encoding="utf-8")

    probe = textwrap.dedent(
        r"""
        import builtins
        import hashlib
        import io
        import json
        import os
        from pathlib import Path
        import socket
        import sqlite3
        import subprocess
        import sys

        root = Path(sys.argv[1])
        before_paths = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
        before_hash = hashlib.sha256((root / "sentinel.txt").read_bytes()).hexdigest()

        def blocked(boundary):
            def fail(*args, **kwargs):
                raise AssertionError(f"capability inventory crossed {boundary}")
            return fail

        original_open = builtins.open
        original_io_open = io.open
        original_os_open = os.open

        def guarded_open(original):
            def guard(file, mode="r", *args, **kwargs):
                if any(flag in mode for flag in "wax+"):
                    raise AssertionError("capability inventory crossed filesystem write")
                return original(file, mode, *args, **kwargs)
            return guard

        def guarded_os_open(path, flags, *args, **kwargs):
            write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
            if flags & write_flags:
                raise AssertionError("capability inventory crossed filesystem write")
            return original_os_open(path, flags, *args, **kwargs)

        builtins.open = guarded_open(original_open)
        io.open = guarded_open(original_io_open)
        os.open = guarded_os_open
        Path.write_text = blocked("filesystem write")
        Path.write_bytes = blocked("filesystem write")
        Path.touch = blocked("filesystem write")
        Path.mkdir = blocked("filesystem write")
        Path.rename = blocked("filesystem write")
        Path.replace = blocked("filesystem write")
        Path.unlink = blocked("filesystem write")
        sqlite3.connect = blocked("database access")
        socket.socket.connect = blocked("network access")
        socket.socket.connect_ex = blocked("network access")
        socket.create_connection = blocked("network access")
        socket.getaddrinfo = blocked("network access")
        subprocess.Popen = blocked("subprocess execution")
        subprocess.run = blocked("subprocess execution")
        subprocess.call = blocked("subprocess execution")
        subprocess.check_call = blocked("subprocess execution")
        subprocess.check_output = blocked("subprocess execution")

        from typer.testing import CliRunner
        from claw.cli import app

        result = CliRunner().invoke(app, ["doctor", "capabilities", "--json"])
        if result.exit_code != 0:
            raise result.exception or AssertionError(result.output)
        payload = json.loads(result.output)
        assert payload["schema_version"] == 1

        after_paths = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
        after_hash = hashlib.sha256((root / "sentinel.txt").read_bytes()).hexdigest()
        assert after_paths == before_paths
        assert after_hash == before_hash
        print("SIDE_EFFECT_PROBE_OK")
        """
    )
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(sentinel_dir),
            "XDG_CONFIG_HOME": str(sentinel_dir / "config"),
            "XDG_CACHE_HOME": str(sentinel_dir / "cache"),
            "TMPDIR": str(sentinel_dir / "tmp"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        }
    )

    completed = subprocess.run(
        [sys.executable, "-c", probe, str(sentinel_dir)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert "SIDE_EFFECT_PROBE_OK" in completed.stdout
