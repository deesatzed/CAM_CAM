"""Tests for CAM-preMine remote GitHub triage.

These tests intentionally use compact local signal fixtures rather than live
GitHub calls. The feature's value is the decision contract: classify a remote
repo before cloning, score CAM value, surface license/safety risk, and give a
clear next step.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from claw.cli import app
from claw.premine import (
    CloneCost,
    PreMineResult,
    RepoSignals,
    RepoType,
    RiskGate,
    Verdict,
    evaluate_signals,
    render_markdown_report,
)


def _signals(
    name: str,
    *,
    description: str = "",
    license: str | None = "MIT",
    size_kb: int = 1000,
    stars: int = 100,
    pushed_at: str = "2026-06-20T00:00:00Z",
    languages: dict[str, int] | None = None,
    tree_paths: list[str] | None = None,
    workflows: list[str] | None = None,
    check_runs: list[str] | None = None,
    releases: list[str] | None = None,
    recent_commit_messages: list[str] | None = None,
    readme_excerpt: str = "",
) -> RepoSignals:
    owner_repo = f"example/{name}"
    return RepoSignals(
        url=f"https://github.com/{owner_repo}",
        name_with_owner=owner_repo,
        description=description,
        is_archived=False,
        is_fork=False,
        default_branch="main",
        stars=stars,
        forks=10,
        open_issues=2,
        license=license,
        pushed_at=pushed_at,
        size_kb=size_kb,
        topics=[],
        languages=languages or {"Python": 1000},
        tree_paths=tree_paths or [],
        workflows=workflows or [],
        check_runs=check_runs or [],
        releases=releases or [],
        recent_commit_messages=recent_commit_messages or [],
        readme_excerpt=readme_excerpt,
    )


def test_understand_anything_scores_clone_now_for_full_tool_repo():
    signals = _signals(
        "Understand-Anything",
        description="interactive knowledge graph for codebases",
        size_kb=33089,
        stars=65000,
        languages={"TypeScript": 1278262, "Python": 164888},
        workflows=["CI", "Supply-Chain Security Scan"],
        check_runs=["ci:success"],
        releases=["v2.7.3"],
        tree_paths=[
            "package.json",
            "CLAUDE.md",
            ".github/workflows/ci.yml",
            "tests/skill/understand/test_scan_project.test.mjs",
            "docs/superpowers/plans/2026-06-03-language-auto-detection.md",
            "understand-anything-plugin/skills/understand/SKILL.md",
            "understand-anything-plugin/packages/dashboard/package.json",
        ],
        readme_excerpt=(
            "multi-agent pipeline scans your project and builds a knowledge graph dashboard"
        ),
    )

    result = evaluate_signals(signals)

    assert result.repo_type == RepoType.RUNNABLE_TOOL
    assert result.verdict == Verdict.CLONE_NOW
    assert result.cam_value_score >= 90
    assert result.clone_cost == CloneCost.MEDIUM
    assert result.risk_gate == RiskGate.NONE
    assert "knowledge graph" in " ".join(result.cam_targets).lower()


def test_taste_skill_routes_to_remote_harvest_as_skill_corpus():
    signals = _signals(
        "taste-skill",
        description="portable agent skills for frontend design",
        size_kb=4799,
        stars=48000,
        languages={"JavaScript": 10746, "Shell": 897},
        tree_paths=[
            "README.md",
            "CHANGELOG.md",
            "skills/taste-skill/SKILL.md",
            "skills/image-to-code-skill/SKILL.md",
            "skills/gpt-tasteskill/SKILL.md",
            "research/laziness/findings/empirical-results.md",
        ],
        readme_excerpt="Portable Agent Skills that upgrade AI-built interfaces",
    )

    result = evaluate_signals(signals)

    assert result.repo_type == RepoType.AGENT_SKILL_CORPUS
    assert result.verdict == Verdict.REMOTE_HARVEST
    assert result.clone_cost == CloneCost.LOW
    assert "skill" in result.allowed_mining_scope[0].lower()


def test_custom_license_forces_conditional_clone_for_blockify():
    signals = _signals(
        "blockify-agentic-data-optimization",
        description="agentic data optimization for enterprise RAG",
        license="NOASSERTION",
        size_kb=1168,
        stars=247,
        languages={"Python": 320052, "HTML": 103931},
        tree_paths=[
            "LICENSE",
            "blockify-distillation-service/Dockerfile",
            "blockify-distillation-service/tests/test_api.py",
            "blockify-distillation-service/helm/blockify-distillation/Chart.yaml",
            "blockify-skill-for-claude-code/skills/blockify-integration/SKILL.md",
            "documentation/RAG-AGENTIC-SEARCH-RESEARCH.md",
        ],
        readme_excerpt="Community License IdeaBlocks benchmark RAG distillation service",
    )

    result = evaluate_signals(signals)

    assert result.verdict == Verdict.CONDITIONAL_CLONE
    assert result.risk_gate == RiskGate.LICENSE
    assert any("license" in risk.lower() for risk in result.risks)


def test_dual_use_repos_are_restricted_remote_harvest():
    gloss = _signals(
        "GLOSSOPETRAE",
        description="LINGUISTIC ENGINE FOR AI",
        license="AGPL-3.0",
        languages={"JavaScript": 2245901, "HTML": 459653},
        tree_paths=[
            "VALIDATION.md",
            "PAPER.md",
            "experiments/e3s_stego_channel.mjs",
            "experiments/results/e3s_stego_tag_char.json",
            "skills/glossopetrae/SKILL.md",
            "test-bench-integrity.mjs",
        ],
        readme_excerpt=(
            "dual-use modules steganography token exploitation covert channels offense defense"
        ),
    )
    st3gg = _signals(
        "ST3GG",
        description="All-in-one steganography suite",
        license="AGPL-3.0",
        languages={"Python": 527878, "HTML": 1136402},
        check_runs=["build:success", "deploy:success"],
        tree_paths=[
            "pyproject.toml",
            "examples/README.md",
            "examples/example_dns_tunnel.pcap",
            "test_comprehensive.py",
            "skills/stegg-cli/SKILL.md",
        ],
        readme_excerpt="steganography red team offense defense detection decode hidden data",
    )

    for signals in (gloss, st3gg):
        result = evaluate_signals(signals)
        assert result.repo_type == RepoType.SECURITY_DUAL_USE
        assert result.verdict == Verdict.RESTRICTED_REMOTE_HARVEST
        assert result.risk_gate == RiskGate.SAFETY
        assert result.blocked_by_default
        assert "defensive" in " ".join(result.allowed_mining_scope).lower()


def test_markdown_report_contains_clear_user_next_steps():
    results = [
        PreMineResult(
            repo="example/repo",
            url="https://github.com/example/repo",
            repo_type=RepoType.RUNNABLE_TOOL,
            verdict=Verdict.CLONE_NOW,
            cam_value_score=88,
            clone_cost=CloneCost.MEDIUM,
            risk_gate=RiskGate.NONE,
            confidence="high",
            why=["Has tests and CI"],
            cam_targets=["verification harness"],
            allowed_mining_scope=["Full CAM mine"],
            blocked_by_default=[],
            risks=[],
            recommended_next_step="git clone https://github.com/example/repo",
            evidence={"tests": 1},
        )
    ]

    report = render_markdown_report(results)

    assert "# CAM-preMine Report" in report
    assert "example/repo" in report
    assert "CLONE_NOW" in report
    assert "git clone https://github.com/example/repo" in report


def test_premine_cli_json_uses_remote_only_result(monkeypatch):
    result = PreMineResult(
        repo="example/repo",
        url="https://github.com/example/repo",
        repo_type=RepoType.RUNNABLE_TOOL,
        verdict=Verdict.CLONE_NOW,
        cam_value_score=91,
        clone_cost=CloneCost.LOW,
        risk_gate=RiskGate.NONE,
        confidence="high",
        why=["Fixture result"],
        cam_targets=["fixture target"],
        allowed_mining_scope=["Full CAM mine"],
        blocked_by_default=[],
        risks=[],
        recommended_next_step="git clone https://github.com/example/repo",
        evidence={},
    )

    monkeypatch.setattr("claw.cli._monolith.premine_url", lambda url: result)

    runner = CliRunner()
    cli_result = runner.invoke(
        app,
        ["premine", "https://github.com/example/repo", "--format", "json"],
    )

    assert cli_result.exit_code == 0, cli_result.output
    payload = json.loads(cli_result.output)
    assert payload["results"][0]["verdict"] == "CLONE_NOW"
    assert payload["results"][0]["repo"] == "example/repo"


def test_premine_cli_writes_report_and_candidate_queue(monkeypatch, tmp_path):
    result = PreMineResult(
        repo="example/repo",
        url="https://github.com/example/repo",
        repo_type=RepoType.AGENT_SKILL_CORPUS,
        verdict=Verdict.REMOTE_HARVEST,
        cam_value_score=74,
        clone_cost=CloneCost.LOW,
        risk_gate=RiskGate.NONE,
        confidence="medium",
        why=["Skill corpus"],
        cam_targets=["skill extraction"],
        allowed_mining_scope=["Harvest SKILL.md files"],
        blocked_by_default=[],
        risks=[],
        recommended_next_step="Harvest selected files remotely.",
        evidence={},
    )
    monkeypatch.setattr("claw.cli._monolith.premine_url", lambda url: result)

    report_path = tmp_path / "premine.md"
    candidates_path = tmp_path / "candidates.jsonl"
    runner = CliRunner()
    cli_result = runner.invoke(
        app,
        [
            "premine",
            "https://github.com/example/repo",
            "--report",
            str(report_path),
            "--save-candidates",
            str(candidates_path),
        ],
    )

    assert cli_result.exit_code == 0, cli_result.output
    assert "REMOTE_HARVEST" in cli_result.output
    assert "CAM-preMine Report" in report_path.read_text()
    lines = candidates_path.read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["verdict"] == "REMOTE_HARVEST"
