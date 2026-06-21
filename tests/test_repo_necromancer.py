from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.repo_necromancer import main, profile_repo


def init_repo(path: Path, readme: str, files: dict[str, str]) -> None:
    path.mkdir(parents=True)
    (path / "README.md").write_text(readme, encoding="utf-8")
    for rel_path, content in files.items():
        file_path = path / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test User",
            "commit",
            "-q",
            "-m",
            "initial",
        ],
        cwd=path,
        check=True,
    )


def test_profile_repo_extracts_necromancer_signals(tmp_path: Path) -> None:
    repo = tmp_path / "graft-tool"
    init_repo(
        repo,
        "# Graft Tool\n\nAnalyze source repos and graft valuable code into targets.",
        {"graft.py": "def transplant():\n    return 'graft'\n", "tests/test_graft.py": "def test_ok():\n    assert True\n"},
    )

    profile = profile_repo(repo)

    assert profile["name"] == "graft-tool"
    assert "Python" in profile["languages"]
    assert profile["has_tests"] is True
    assert "graft" in profile["signals"]


def test_repo_necromancer_writes_codex_showpiece_packet(tmp_path: Path) -> None:
    repo_a = tmp_path / "codegraft-lite"
    repo_b = tmp_path / "workspace-map"
    init_repo(
        repo_a,
        "# CodeGraft Lite\n\nFind graft candidates and transplant useful code.",
        {"codegraft.py": "def find_grafts():\n    return []\n"},
    )
    init_repo(
        repo_b,
        "# Workspace Map\n\nScan workspaces, classify repos, and produce safety plans.",
        {"scanner.py": "def scan_workspace():\n    return []\n"},
    )
    out_dir = tmp_path / "necromancer"

    exit_code = main([
        "--repo-a",
        str(repo_a),
        "--repo-b",
        str(repo_b),
        "--out-dir",
        str(out_dir),
        "--product-name",
        "GraftMap",
    ])

    assert exit_code == 0
    assert (out_dir / "NECROMANCER_SHOWPIECE.md").exists()
    assert (out_dir / "CAM_CODEX_GOAL.md").exists()
    assert (out_dir / "evidence.json").exists()
    assert (out_dir / "fused_app" / "README.md").exists()
    assert (out_dir / "fused_app" / "repo_necromancer_demo.py").exists()
    assert (out_dir / "fused_app" / "index.html").exists()

    evidence = json.loads((out_dir / "evidence.json").read_text(encoding="utf-8"))
    assert evidence["product_name"] == "GraftMap"
    assert evidence["source_repos"][0]["name"] == "codegraft-lite"
    assert evidence["source_repos"][1]["name"] == "workspace-map"

    demo = subprocess.run(
        [sys.executable, str(out_dir / "fused_app" / "repo_necromancer_demo.py"), "--evidence", str(out_dir / "evidence.json")],
        check=False,
        capture_output=True,
        text=True,
    )
    assert demo.returncode == 0
    assert "GraftMap" in demo.stdout


def test_repo_necromancer_records_merge_ledger_and_safe_plan(tmp_path: Path) -> None:
    repo_a = tmp_path / "moriah-omega"
    repo_b = tmp_path / "careframe-proto"
    init_repo(
        repo_a,
        "# Moriah Omega\n\nWorkspace repo inventory with retrieval and dashboard checks.",
        {"inventory.py": "def scan_workspace():\n    return []\n"},
    )
    init_repo(
        repo_b,
        "# CareFrame Proto\n\nClinical preflight workflow with graft and rollback planning.",
        {"careframe.js": "export function planRollback() { return [] }\n"},
    )
    out_dir = tmp_path / "moriah-careframe"

    exit_code = main([
        "--repo-a",
        str(repo_a),
        "--repo-b",
        str(repo_b),
        "--out-dir",
        str(out_dir),
        "--product-name",
        "MoriahCareFrame",
    ])

    assert exit_code == 0
    evidence = json.loads((out_dir / "evidence.json").read_text(encoding="utf-8"))
    ledger = evidence["merge_ledger"]
    merge_plan = evidence["safe_merge_plan"]
    assert {item["source"] for item in ledger} == {"Source A", "Source B", "New glue"}
    assert all(item["provenance"] for item in ledger)
    assert all(item["target_files"] for item in merge_plan)
    assert all(item["tests_to_add"] for item in merge_plan)
    assert all(item["rollback"] for item in merge_plan)

    showpiece = (out_dir / "NECROMANCER_SHOWPIECE.md").read_text(encoding="utf-8")
    app_readme = (out_dir / "fused_app" / "README.md").read_text(encoding="utf-8")
    assert "## Merge ledger" in showpiece
    assert "## Safe merge plan" in showpiece
    assert "## What was revived" in app_readme


def test_repo_necromancer_report_includes_git_state_receipts(tmp_path: Path) -> None:
    repo_a = tmp_path / "filesystem-source"
    repo_a.mkdir()
    (repo_a / "README.md").write_text("# Filesystem Source\n\nInventory source.", encoding="utf-8")
    repo_b = tmp_path / "git-source"
    init_repo(
        repo_b,
        "# Git Source\n\nGraft source with rollback planning.",
        {"planner.py": "def plan():\n    return []\n"},
    )
    (repo_b / "scratch.md").write_text("dirty working tree\n", encoding="utf-8")
    out_dir = tmp_path / "packet"

    exit_code = main([
        "--repo-a",
        str(repo_a),
        "--repo-b",
        str(repo_b),
        "--out-dir",
        str(out_dir),
        "--product-name",
        "ReceiptDesk",
    ])

    assert exit_code == 0
    evidence = json.loads((out_dir / "evidence.json").read_text(encoding="utf-8"))
    git_head = evidence["source_repos"][1]["git"]["head"]
    showpiece = (out_dir / "NECROMANCER_SHOWPIECE.md").read_text(encoding="utf-8")
    app_readme = (out_dir / "fused_app" / "README.md").read_text(encoding="utf-8")

    assert "Git repo: `False`" in showpiece
    assert "Git repo: `True`" in showpiece
    assert f"Head: `{git_head}`" in showpiece
    assert "Status receipt:" in showpiece
    assert "?? scratch.md" in showpiece
    assert f"Git head: `{git_head}`" in app_readme
    assert "Dirty: `True`" in app_readme


def test_repo_necromancer_standalone_scaffold_is_portable_for_unrelated_pair(tmp_path: Path) -> None:
    repo_a = tmp_path / "codegraft-lite"
    repo_b = tmp_path / "workspace-map"
    init_repo(
        repo_a,
        "# CodeGraft Lite\n\nFind graft candidates and transplant useful code.",
        {"codegraft.py": "def find_grafts():\n    return []\n"},
    )
    init_repo(
        repo_b,
        "# Workspace Map\n\nScan workspaces, classify repos, and produce safety plans.",
        {"scanner.py": "def scan_workspace():\n    return []\n"},
    )
    out_dir = tmp_path / "packet"
    standalone_repo = tmp_path / "CodeGraftScope"

    exit_code = main([
        "--repo-a",
        str(repo_a),
        "--repo-b",
        str(repo_b),
        "--out-dir",
        str(out_dir),
        "--product-name",
        "CodeGraftScope",
        "--standalone-repo",
        str(standalone_repo),
    ])

    assert exit_code == 0
    evidence = json.loads((standalone_repo / "evidence" / "source_profiles.json").read_text(encoding="utf-8"))
    target_files = {
        target_file
        for item in evidence["safe_merge_plan"]
        for target_file in item["target_files"]
    }
    glue_entries = [item for item in evidence["merge_ledger"] if item["source"] == "New glue"]
    assert "code_graft_scope/planner.py" in target_files
    assert "moriah_careframe/planner.py" not in target_files
    assert glue_entries[0]["source_repo"] == "CodeGraftScope"

    test_run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(standalone_repo / "tests")],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert test_run.returncode == 0, test_run.stdout + test_run.stderr


def test_repo_necromancer_can_create_standalone_repo_scaffold(tmp_path: Path) -> None:
    repo_a = tmp_path / "moriah-omega"
    repo_b = tmp_path / "careframe-proto"
    init_repo(
        repo_a,
        "# Moriah Omega\n\nEthical operating loop with KPI governance.",
        {"moriah.py": "def govern():\n    return 'safe'\n"},
    )
    init_repo(
        repo_b,
        "# CareFrame Proto\n\nPatient story builder with clinical safety guardrails.",
        {"careframe.jsx": "export function buildStory() { return [] }\n"},
    )
    out_dir = tmp_path / "packet"
    standalone_repo = tmp_path / "MoriahCareFrame"

    exit_code = main([
        "--repo-a",
        str(repo_a),
        "--repo-b",
        str(repo_b),
        "--out-dir",
        str(out_dir),
        "--product-name",
        "MoriahCareFrame",
        "--standalone-repo",
        str(standalone_repo),
    ])

    assert exit_code == 0
    assert standalone_repo.is_dir()
    assert (standalone_repo / "README.md").exists()
    assert (standalone_repo / "pyproject.toml").exists()
    assert (standalone_repo / "moriah_careframe" / "__init__.py").exists()
    assert (standalone_repo / "moriah_careframe" / "cli.py").exists()
    assert (standalone_repo / "moriah_careframe" / "planner.py").exists()
    assert (standalone_repo / "tests" / "test_cli.py").exists()
    assert (standalone_repo / "docs" / "source_receipts.md").exists()
    assert (standalone_repo / "evidence" / "source_profiles.json").exists()
    assert (standalone_repo / "patch_plan.md").exists()

    packet_evidence = json.loads((out_dir / "evidence.json").read_text(encoding="utf-8"))
    repo_evidence = json.loads((standalone_repo / "evidence" / "source_profiles.json").read_text(encoding="utf-8"))
    assert packet_evidence["standalone_repo"] == str(standalone_repo)
    assert repo_evidence["product_name"] == "MoriahCareFrame"

    smoke = subprocess.run(
        [sys.executable, "-m", "moriah_careframe.cli", "--evidence", "evidence/source_profiles.json"],
        cwd=standalone_repo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert smoke.returncode == 0
    assert "MoriahCareFrame" in smoke.stdout
    assert "Safe merge plan" in smoke.stdout
