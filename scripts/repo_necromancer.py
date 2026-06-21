"""Create a Repo Necromancer showpiece packet from two source repos.

The script is intentionally read-only against the source repositories. It
profiles both repos, synthesizes a Codex-ready fusion brief, and writes a tiny
runnable prototype that demonstrates the merged product story.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".next",
    "dist",
    "build",
}

LANGUAGE_BY_EXTENSION = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".swift": "Swift",
    ".md": "Markdown",
    ".json": "JSON",
    ".toml": "TOML",
    ".yaml": "YAML",
    ".yml": "YAML",
}

SIGNAL_TERMS = {
    "graft": ("graft", "transplant", "merge", "extract", "copy", "reuse"),
    "workspace": ("workspace", "repo", "scan", "discover", "organize", "inventory"),
    "safety": ("safe", "guard", "preflight", "rollback", "audit", "validate"),
    "knowledge": ("knowledge", "rag", "retrieval", "search", "index", "qa"),
    "dashboard": ("dashboard", "ui", "html", "next", "react", "visual"),
    "clinical": ("medical", "clinical", "patient", "hipaa", "ehr", "sql"),
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a Repo Necromancer fusion packet from two source repos.",
    )
    parser.add_argument("--repo-a", required=True, type=Path, help="First source repo.")
    parser.add_argument("--repo-b", required=True, type=Path, help="Second source repo.")
    parser.add_argument("--out-dir", required=True, type=Path, help="Output directory.")
    parser.add_argument(
        "--product-name",
        default=None,
        help="Optional product name for the resurrected app.",
    )
    parser.add_argument(
        "--standalone-repo",
        default=None,
        type=Path,
        help="Optional path where a standalone repo scaffold should be created.",
    )
    return parser.parse_args(argv)


def profile_repo(path: Path) -> dict[str, Any]:
    path = path.resolve()
    readme = read_readme(path)
    files = list(iter_files(path))
    language_counts = Counter(
        LANGUAGE_BY_EXTENSION.get(file.suffix.lower())
        for file in files
        if LANGUAGE_BY_EXTENSION.get(file.suffix.lower())
    )
    text_sample = "\n".join([path.name, readme, *read_text_samples(files)])
    signals = detect_signals(text_sample)
    return {
        "name": path.name,
        "path": str(path),
        "title": extract_title(readme) or path.name,
        "summary": extract_summary(readme) or "No README summary found.",
        "languages": dict(language_counts),
        "file_count": len(files),
        "has_tests": has_tests(path),
        "entrypoints": find_entrypoints(path),
        "signals": signals,
        "git": inspect_git(path),
    }


def read_readme(path: Path) -> str:
    for name in ("README.md", "README.rst", "readme.md", "Readme.md"):
        candidate = path / name
        if candidate.exists():
            return candidate.read_text(encoding="utf-8", errors="replace")[:12000]
    return ""


def iter_files(path: Path) -> list[Path]:
    found: list[Path] = []
    for current, dirs, files in os.walk(path):
        dirs[:] = [item for item in dirs if item not in SKIP_DIRS]
        for filename in sorted(files):
            if filename.startswith(".DS_Store"):
                continue
            found.append(Path(current) / filename)
    return found


def read_text_samples(files: list[Path], limit: int = 80) -> list[str]:
    samples: list[str] = []
    for file in files[:limit]:
        if file.suffix.lower() not in LANGUAGE_BY_EXTENSION and file.name.lower() not in {"readme", "license"}:
            continue
        try:
            samples.append(file.read_text(encoding="utf-8", errors="replace")[:2000])
        except OSError:
            continue
    return samples


def detect_signals(text: str) -> list[str]:
    lowered = text.lower()
    signals = []
    for signal, terms in SIGNAL_TERMS.items():
        if any(term in lowered for term in terms):
            signals.append(signal)
    return sorted(signals)


def extract_title(readme: str) -> str:
    for line in readme.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def extract_summary(readme: str) -> str:
    for line in readme.splitlines():
        stripped = re.sub(r"\s+", " ", line.strip())
        if not stripped or stripped.startswith("#") or stripped.startswith("[!"):
            continue
        if stripped.startswith("```") or stripped.startswith("|"):
            continue
        return stripped[:300]
    return ""


def has_tests(path: Path) -> bool:
    if (path / "tests").is_dir() or (path / "test").is_dir():
        return True
    return any(path.glob("test_*.py")) or any(path.glob("*.test.*"))


def find_entrypoints(path: Path) -> list[str]:
    candidates = []
    for name in ("pyproject.toml", "package.json", "setup.py", "Makefile"):
        if (path / name).exists():
            candidates.append(name)
    for file in sorted(path.iterdir()):
        if file.is_file() and file.suffix.lower() in {".py", ".sh"}:
            candidates.append(file.name)
    return candidates[:10]


def inspect_git(path: Path) -> dict[str, str | bool]:
    status = git(path, "status", "--short")
    is_repo = bool(git(path, "rev-parse", "--show-toplevel"))
    return {
        "is_repo": is_repo,
        "branch": git(path, "branch", "--show-current"),
        "head": git(path, "rev-parse", "--short", "HEAD"),
        "remote": git(path, "remote", "get-url", "origin"),
        "dirty": bool(status.strip()),
        "status_receipt": status,
    }


def git(path: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def synthesize_product(
    profile_a: dict[str, Any],
    profile_b: dict[str, Any],
    name: str | None,
    standalone_repo: Path | None = None,
) -> dict[str, Any]:
    product_name = name or f"{camel(profile_a['name'])}{camel(profile_b['name'])} Necromancer"
    combined_signals = sorted(set(profile_a["signals"]) | set(profile_b["signals"]))
    promise = (
        f"{product_name} revives useful parts of {profile_a['name']} and {profile_b['name']} "
        "into a safe integration workbench with provenance, readiness checks, and a runnable demo."
    )
    if {"graft", "workspace"}.issubset(combined_signals):
        promise = (
            f"{product_name} turns workspace inventory plus code-grafting logic into a local "
            "subsystem transplant desk: find reusable modules, preflight the target, and produce "
            "a patch plan before copying code."
        )
    elif {"knowledge", "dashboard"}.issubset(combined_signals):
        promise = (
            f"{product_name} merges retrieval logic with a visual dashboard so abandoned docs and "
            "code become an askable local knowledge appliance."
        )
    evidence = {
        "product_name": product_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "promise": promise,
        "combined_signals": combined_signals,
        "source_repos": [profile_a, profile_b],
        "merge_ledger": build_merge_ledger(profile_a, profile_b, product_name),
        "safe_merge_plan": build_safe_merge_plan(profile_a, profile_b, package_slug(product_name)),
        "mvp_features": [
            "Read-only source repo profiler with git state receipts.",
            "Compatibility map showing which source repo contributes each subsystem.",
            "Safe merge plan with target files, tests to add, and rollback notes.",
            "Runnable demo app that explains the revived product in one command.",
            "Codex-ready goal brief for turning the packet into a real merged repo.",
        ],
    }
    if standalone_repo is not None:
        evidence["standalone_repo"] = str(standalone_repo.resolve())
    return evidence


def build_merge_ledger(profile_a: dict[str, Any], profile_b: dict[str, Any], product_name: str) -> list[dict[str, Any]]:
    return [
        {
            "subsystem": "Workspace inventory and repo signal profiler",
            "source": "Source A",
            "source_repo": profile_a["name"],
            "provenance": [
                f"path={profile_a['path']}",
                f"signals={', '.join(profile_a['signals']) or 'none'}",
                f"git_head={profile_a['git'].get('head') or 'not available'}",
            ],
            "revived_as": "A read-only scanner that turns source trees into evidence JSON before any graft.",
        },
        {
            "subsystem": "Care-oriented preflight and rollback framing",
            "source": "Source B",
            "source_repo": profile_b["name"],
            "provenance": [
                f"path={profile_b['path']}",
                f"signals={', '.join(profile_b['signals']) or 'none'}",
                f"git_head={profile_b['git'].get('head') or 'not available'}",
            ],
            "revived_as": "A target-safety review that names warnings, required checks, and rollback steps.",
        },
        {
            "subsystem": "Transplant desk glue",
            "source": "New glue",
            "source_repo": product_name,
            "provenance": [
                "generated_by=CAM_CAM scripts/repo_necromancer.py",
                "inputs=read-only source profiles",
            ],
            "revived_as": "A merged CLI/report packet that explains what to borrow before copying code.",
        },
    ]


def build_safe_merge_plan(profile_a: dict[str, Any], profile_b: dict[str, Any], package_name: str) -> list[dict[str, Any]]:
    return [
        {
            "phase": "1. Freeze source receipts",
            "target_files": ["docs/source_receipts.md", "evidence/source_profiles.json"],
            "tests_to_add": ["tests/test_source_receipts.py"],
            "rollback": "Delete generated receipts; no source repo rollback needed because inputs are read-only.",
            "risk": "Low. Fails only if source paths disappear or git commands time out.",
        },
        {
            "phase": "2. Build transplant planner",
            "target_files": [f"{package_name}/planner.py", f"{package_name}/cli.py"],
            "tests_to_add": ["tests/test_planner.py", "tests/test_cli_demo.py"],
            "rollback": "Revert planner and CLI files; keep receipts for audit continuity.",
            "risk": "Medium. Planner must label weak matches instead of implying safe copyability.",
        },
        {
            "phase": "3. Add reviewable patch output",
            "target_files": ["patch_plan.md", "patches/README.md"],
            "tests_to_add": ["tests/test_patch_plan_contract.py"],
            "rollback": "Discard generated patch plan and rerun from unchanged receipts.",
            "risk": "Medium. Human review is required before any file copy into a real target repo.",
        },
    ]


def camel(text: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", text)
    return "".join(part[:1].upper() + part[1:] for part in parts if part)


def write_packet(evidence: dict[str, Any], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    fused_app = out_dir / "fused_app"
    fused_app.mkdir(parents=True, exist_ok=True)
    paths = {
        "showpiece": out_dir / "NECROMANCER_SHOWPIECE.md",
        "codex_goal": out_dir / "CAM_CODEX_GOAL.md",
        "evidence": out_dir / "evidence.json",
        "app_readme": fused_app / "README.md",
        "demo_py": fused_app / "repo_necromancer_demo.py",
        "index_html": fused_app / "index.html",
    }
    paths["evidence"].write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    paths["showpiece"].write_text(render_showpiece(evidence), encoding="utf-8")
    paths["codex_goal"].write_text(render_codex_goal(evidence), encoding="utf-8")
    paths["app_readme"].write_text(render_app_readme(evidence), encoding="utf-8")
    paths["demo_py"].write_text(render_demo_py(), encoding="utf-8")
    paths["index_html"].write_text(render_index_html(evidence), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}


def write_standalone_repo(evidence: dict[str, Any], repo_dir: Path) -> dict[str, str]:
    repo_dir = repo_dir.resolve()
    if repo_dir.exists() and any(repo_dir.iterdir()):
        raise FileExistsError(f"standalone repo path is not empty: {repo_dir}")

    package_name = package_slug(evidence["product_name"])
    repo_dir.mkdir(parents=True, exist_ok=True)
    (repo_dir / package_name).mkdir(parents=True, exist_ok=True)
    (repo_dir / "tests").mkdir(exist_ok=True)
    (repo_dir / "docs").mkdir(exist_ok=True)
    (repo_dir / "evidence").mkdir(exist_ok=True)

    paths = {
        "standalone_readme": repo_dir / "README.md",
        "pyproject": repo_dir / "pyproject.toml",
        "package_init": repo_dir / package_name / "__init__.py",
        "planner": repo_dir / package_name / "planner.py",
        "cli": repo_dir / package_name / "cli.py",
        "test_cli": repo_dir / "tests" / "test_cli.py",
        "source_receipts": repo_dir / "docs" / "source_receipts.md",
        "source_profiles": repo_dir / "evidence" / "source_profiles.json",
        "patch_plan": repo_dir / "patch_plan.md",
        "gitignore": repo_dir / ".gitignore",
    }
    paths["standalone_readme"].write_text(render_standalone_readme(evidence, package_name), encoding="utf-8")
    paths["pyproject"].write_text(render_standalone_pyproject(evidence, package_name), encoding="utf-8")
    paths["package_init"].write_text(render_standalone_init(evidence), encoding="utf-8")
    paths["planner"].write_text(render_standalone_planner(), encoding="utf-8")
    paths["cli"].write_text(render_standalone_cli(), encoding="utf-8")
    paths["test_cli"].write_text(render_standalone_test(package_name), encoding="utf-8")
    paths["source_receipts"].write_text(render_source_receipts(evidence), encoding="utf-8")
    paths["source_profiles"].write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    paths["patch_plan"].write_text(render_patch_plan(evidence), encoding="utf-8")
    paths["gitignore"].write_text("__pycache__/\n.pytest_cache/\n*.pyc\n.venv/\ndist/\nbuild/\n", encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}


def render_showpiece(evidence: dict[str, Any]) -> str:
    repos = evidence["source_repos"]
    lines = [
        f"# Repo Necromancer: {evidence['product_name']}",
        "",
        evidence["promise"],
        "",
        "## Why this is a social-media-worthy CAM_Codx demo",
        "",
        "- It starts with two existing repos instead of a blank prompt.",
        "- It extracts purpose, signals, git state, entrypoints, and test posture from both.",
        "- It produces a runnable fused-app packet plus a Codex-ready build goal.",
        "- It keeps source repos read-only and records provenance.",
        "",
        "## Source repos",
        "",
    ]
    for repo in repos:
        git_state = repo.get("git", {})
        status_receipt = git_state.get("status_receipt") or "clean or unavailable"
        lines.extend([
            f"### {repo['name']}",
            "",
            f"- Path: `{repo['path']}`",
            f"- Summary: {repo['summary']}",
            f"- Signals: {', '.join(repo['signals']) or 'none'}",
            f"- Languages: {format_dict(repo['languages'])}",
            f"- Tests found: {repo['has_tests']}",
            f"- Git repo: `{git_state.get('is_repo', False)}`",
            f"- Branch: `{git_state.get('branch') or 'not available'}`",
            f"- Head: `{git_state.get('head') or 'not available'}`",
            f"- Remote: `{git_state.get('remote') or 'not available'}`",
            f"- Dirty: `{git_state.get('dirty', False)}`",
            "- Status receipt:",
            "",
            "```text",
            status_receipt,
            "```",
            "",
        ])
    lines.extend([
        "## Merge ledger",
        "",
        "| Subsystem | Source | Provenance | Revived as |",
        "|---|---|---|---|",
    ])
    for item in evidence["merge_ledger"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    item["subsystem"],
                    f"{item['source']} / {item['source_repo']}",
                    "<br>".join(item["provenance"]),
                    item["revived_as"],
                ]
            )
            + " |"
        )
    lines.extend([
        "",
        "## Safe merge plan",
        "",
        "| Phase | Target files | Tests to add | Rollback | Risk |",
        "|---|---|---|---|---|",
    ])
    for item in evidence["safe_merge_plan"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    item["phase"],
                    "<br>".join(f"`{path}`" for path in item["target_files"]),
                    "<br>".join(f"`{path}`" for path in item["tests_to_add"]),
                    item["rollback"],
                    item["risk"],
                ]
            )
            + " |"
        )
    lines.extend([
        "",
        "## MVP feature sketch",
        "",
        *[f"- {feature}" for feature in evidence["mvp_features"]],
        "",
        "## Run the fused demo",
        "",
        "```bash",
        "python fused_app/repo_necromancer_demo.py --evidence evidence.json",
        "open fused_app/index.html",
        "```",
        "",
        "## Verification",
        "",
        "See `TEST_RESULTS.md` for the latest smoke, test, and read-only source receipts.",
    ])
    return "\n".join(lines) + "\n"


def render_codex_goal(evidence: dict[str, Any]) -> str:
    repo_a, repo_b = evidence["source_repos"]
    standalone_repo = evidence.get("standalone_repo")
    standalone_section = ""
    if standalone_repo:
        standalone_section = f"""
## Standalone repo requirement

The task is incomplete unless this exact directory exists and contains its own
runtime code, tests, README, provenance docs, and smoke command:

`{standalone_repo}`

Do not count `docs/showpieces/repo_necromancer/.../fused_app` as the output
repo. That directory is only the packet demo.
"""
    return f"""# CAM_Codx Repo Necromancer Goal

Build a working merged product from two source repos:

- Source A: `{repo_a['path']}`
- Source B: `{repo_b['path']}`

Product name: **{evidence['product_name']}**

Promise:

> {evidence['promise']}
{standalone_section}

## Required behavior

1. Keep both source repos read-only.
2. Create a new standalone output repo or app directory outside the packet.
3. Reuse source ideas only with provenance notes.
4. Implement a runnable MVP with CLI help, README, and at least one smoke test.
5. Include a merge ledger that maps each new subsystem to Source A, Source B, or new glue code.
6. Run tests and record results before claiming completion.
7. Do not mark the goal complete by only updating the packet directory.

## Initial MVP features

{chr(10).join(f'- {item}' for item in evidence['mvp_features'])}

## Acceptance

- `python -m pytest -q` or the app's equivalent smoke test passes.
- README explains what was revived from each source repo.
- No source repo files are modified.
- The final report includes exact source paths and git heads.
- If a standalone repo path is named above, that path exists and contains runtime code.
"""


def package_slug(text: str) -> str:
    text = text.replace("CareFrame", "Careframe")
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return slug or "repo_necromancer_app"


def render_standalone_readme(evidence: dict[str, Any], package_name: str) -> str:
    return f"""# {evidence['product_name']}

{evidence['promise']}

This is a standalone Repo Necromancer scaffold. It was generated from read-only
source evidence and is meant to become the real fused product repo, not just a
packet under `docs/showpieces`.

## Run

```bash
python -m {package_name}.cli --evidence evidence/source_profiles.json
```

## Test

```bash
python -m pytest -q
```

## Source Boundary

{chr(10).join(f'- `{repo["name"]}`: `{repo["path"]}`; git head `{repo["git"].get("head") or "not available"}`; dirty `{repo["git"].get("dirty", False)}`' for repo in evidence['source_repos'])}

The source repos are evidence only. Do not modify them from this repo.
"""


def render_standalone_pyproject(evidence: dict[str, Any], package_name: str) -> str:
    distribution_name = package_name.replace("_", "-")
    return f"""[project]
name = "{distribution_name}"
version = "0.1.0"
description = "{evidence['promise'].replace('"', "'")[:180]}"
requires-python = ">=3.11"
dependencies = []

[project.scripts]
{distribution_name} = "{package_name}.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
"""


def render_standalone_init(evidence: dict[str, Any]) -> str:
    return f'''"""Standalone scaffold for {evidence["product_name"]}."""

__version__ = "0.1.0"
'''


def render_standalone_planner() -> str:
    return '''from __future__ import annotations

from typing import Any


def summarize_plan(evidence: dict[str, Any]) -> list[str]:
    """Return human-readable implementation phases from Repo Necromancer evidence."""
    return [
        f"{item['phase']}: {', '.join(item['target_files'])}"
        for item in evidence.get("safe_merge_plan", [])
    ]


def source_summary(evidence: dict[str, Any]) -> list[str]:
    """Return source repo receipts without mutating those repos."""
    lines = []
    for repo in evidence.get("source_repos", []):
        git_state = repo.get("git", {})
        lines.append(
            f"{repo['name']}: {repo['path']} "
            f"(head={git_state.get('head') or 'not available'}, dirty={git_state.get('dirty', False)})"
        )
    return lines
'''


def render_standalone_cli() -> str:
    return '''from __future__ import annotations

import argparse
import json
from pathlib import Path

from .planner import source_summary, summarize_plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the standalone Repo Necromancer scaffold.")
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))

    print(evidence["product_name"])
    print(evidence["promise"])
    print()
    print("Source repos:")
    for line in source_summary(evidence):
        print(f"- {line}")
    print()
    print("Safe merge plan:")
    for line in summarize_plan(evidence):
        print(f"- {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def render_standalone_test(package_name: str) -> str:
    return f'''from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_cli_smoke() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    evidence_path = repo_root / "evidence" / "source_profiles.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    result = subprocess.run(
        [sys.executable, "-m", "{package_name}.cli", "--evidence", str(evidence_path)],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert evidence["product_name"] in result.stdout
    assert "Safe merge plan" in result.stdout
'''


def render_source_receipts(evidence: dict[str, Any]) -> str:
    lines = ["# Source Receipts", ""]
    for repo in evidence["source_repos"]:
        git_state = repo.get("git", {})
        status = git_state.get("status_receipt") or "clean or unavailable"
        lines.extend([
            f"## {repo['name']}",
            "",
            f"- Path: `{repo['path']}`",
            f"- Git repo: `{git_state.get('is_repo', False)}`",
            f"- Head: `{git_state.get('head') or 'not available'}`",
            f"- Dirty: `{git_state.get('dirty', False)}`",
            "",
            "```text",
            status,
            "```",
            "",
        ])
    return "\n".join(lines)


def render_patch_plan(evidence: dict[str, Any]) -> str:
    lines = [f"# {evidence['product_name']} Patch Plan", "", evidence["promise"], ""]
    for item in evidence["safe_merge_plan"]:
        lines.extend([
            f"## {item['phase']}",
            "",
            f"- Target files: {', '.join(item['target_files'])}",
            f"- Tests to add: {', '.join(item['tests_to_add'])}",
            f"- Rollback: {item['rollback']}",
            f"- Risk: {item['risk']}",
            "",
        ])
    return "\n".join(lines)


def render_app_readme(evidence: dict[str, Any]) -> str:
    return f"""# {evidence['product_name']}

This is a Repo Necromancer fused-app packet generated by CAM_Codx/CAM_CAM.

{evidence['promise']}

## Run

```bash
python repo_necromancer_demo.py --evidence ../evidence.json
open index.html
```

## Source Repos

{chr(10).join(f'- `{repo["name"]}`: {repo["summary"]} Source path: `{repo["path"]}`. Git repo: `{repo["git"].get("is_repo", False)}`. Git head: `{repo["git"].get("head") or "not available"}`. Dirty: `{repo["git"].get("dirty", False)}`.' for repo in evidence['source_repos'])}

## What was revived

{chr(10).join(f'- **{item["subsystem"]}** from {item["source"]}: {item["revived_as"]}' for item in evidence['merge_ledger'])}

## Safe merge plan

{chr(10).join(f'- **{item["phase"]}**: write {", ".join(item["target_files"])}; verify with {", ".join(item["tests_to_add"])}; rollback: {item["rollback"]}' for item in evidence['safe_merge_plan'])}

## Verification

The packet-level verification record lives in `../TEST_RESULTS.md`.
"""


def render_demo_py() -> str:
    return '''from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Repo Necromancer fused demo.")
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    print(f"Repo Necromancer Demo: {evidence['product_name']}")
    print(evidence["promise"])
    print()
    print("Source repos:")
    for repo in evidence["source_repos"]:
        print(f"- {repo['name']}: {', '.join(repo['signals']) or 'no signals'}")
    print()
    print("MVP features:")
    for feature in evidence["mvp_features"]:
        print(f"- {feature}")
    print()
    print("Merge ledger:")
    for item in evidence.get("merge_ledger", []):
        print(f"- {item['subsystem']} <- {item['source']} ({item['source_repo']})")
    print()
    print("Safe merge plan:")
    for item in evidence.get("safe_merge_plan", []):
        print(f"- {item['phase']}: {', '.join(item['target_files'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def render_index_html(evidence: dict[str, Any]) -> str:
    repo_cards = "\n".join(
        f"<article><h3>{html.escape(repo['name'])}</h3>"
        f"<p>{html.escape(repo['summary'])}</p>"
        f"<p><b>Signals:</b> {html.escape(', '.join(repo['signals']) or 'none')}</p></article>"
        for repo in evidence["source_repos"]
    )
    features = "".join(f"<li>{html.escape(feature)}</li>" for feature in evidence["mvp_features"])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(evidence['product_name'])}</title>
  <style>
    body {{ margin: 0; font-family: Inter, system-ui, sans-serif; background: #101418; color: #f4f7fb; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 48px 24px; }}
    h1 {{ font-size: clamp(2.2rem, 6vw, 4.5rem); margin: 0 0 12px; }}
    p {{ color: #c9d4df; line-height: 1.6; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }}
    article {{ border: 1px solid #33424f; border-radius: 8px; padding: 18px; background: #17212a; }}
    li {{ margin: 8px 0; }}
    code {{ background: #253340; padding: 2px 5px; border-radius: 4px; }}
  </style>
</head>
<body>
  <main>
    <p><code>Repo Necromancer</code></p>
    <h1>{html.escape(evidence['product_name'])}</h1>
    <p>{html.escape(evidence['promise'])}</p>
    <section class="grid">{repo_cards}</section>
    <h2>MVP Feature Plan</h2>
    <ul>{features}</ul>
  </main>
</body>
</html>
"""


def format_dict(data: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(data.items())) or "none"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        profile_a = profile_repo(args.repo_a)
        profile_b = profile_repo(args.repo_b)
        evidence = synthesize_product(profile_a, profile_b, args.product_name, args.standalone_repo)
        outputs = write_packet(evidence, args.out_dir)
        if args.standalone_repo is not None:
            outputs.update(write_standalone_repo(evidence, args.standalone_repo))
        print(f"Repo Necromancer created: {evidence['product_name']}")
        for name, path in outputs.items():
            print(f"{name}: {path}")
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
