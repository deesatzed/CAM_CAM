"""Remote GitHub triage before cloning a repo for CAM mining."""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx


class Verdict(str, Enum):
    CLONE_NOW = "CLONE_NOW"
    CONDITIONAL_CLONE = "CONDITIONAL_CLONE"
    REMOTE_HARVEST = "REMOTE_HARVEST"
    RESTRICTED_REMOTE_HARVEST = "RESTRICTED_REMOTE_HARVEST"
    WATCHLIST = "WATCHLIST"
    SKIP = "SKIP"
    NEEDS_HUMAN = "NEEDS_HUMAN"


class RepoType(str, Enum):
    RUNNABLE_TOOL = "runnable_tool"
    APP_PRODUCT = "app_product"
    LIBRARY = "library"
    AGENT_SKILL_CORPUS = "agent_skill_corpus"
    DOCS_METHODOLOGY = "docs_methodology"
    RESEARCH_EVAL = "research_eval"
    SECURITY_DUAL_USE = "security_dual_use"
    DATASET_OR_EXAMPLES = "dataset_or_examples"
    DEMO_ONLY = "demo_only"
    UNKNOWN = "unknown"


class CloneCost(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RiskGate(str, Enum):
    NONE = "NONE"
    LICENSE = "LICENSE"
    SAFETY = "SAFETY"
    MAINTENANCE = "MAINTENANCE"
    CREDENTIALS = "CREDENTIALS"


@dataclass(frozen=True)
class RepoSignals:
    url: str
    name_with_owner: str
    description: str = ""
    is_archived: bool = False
    is_fork: bool = False
    default_branch: str = "main"
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    license: str | None = None
    pushed_at: str | None = None
    size_kb: int = 0
    topics: list[str] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)
    tree_paths: list[str] = field(default_factory=list)
    workflows: list[str] = field(default_factory=list)
    check_runs: list[str] = field(default_factory=list)
    releases: list[str] = field(default_factory=list)
    recent_commit_messages: list[str] = field(default_factory=list)
    readme_excerpt: str = ""


@dataclass(frozen=True)
class PreMineResult:
    repo: str
    url: str
    repo_type: RepoType
    verdict: Verdict
    cam_value_score: int
    clone_cost: CloneCost
    risk_gate: RiskGate
    confidence: str
    why: list[str]
    cam_targets: list[str]
    allowed_mining_scope: list[str]
    blocked_by_default: list[str]
    risks: list[str]
    recommended_next_step: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "url": self.url,
            "repo_type": self.repo_type.value,
            "verdict": self.verdict.value,
            "cam_value_score": self.cam_value_score,
            "clone_cost": self.clone_cost.value,
            "risk_gate": self.risk_gate.value,
            "confidence": self.confidence,
            "why": self.why,
            "cam_targets": self.cam_targets,
            "allowed_mining_scope": self.allowed_mining_scope,
            "blocked_by_default": self.blocked_by_default,
            "risks": self.risks,
            "recommended_next_step": self.recommended_next_step,
            "evidence": self.evidence,
        }


PERMISSIVE_LICENSES = {
    "0BSD",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "CC0-1.0",
    "ISC",
    "MIT",
    "MPL-2.0",
    "Unlicense",
}

COPYLEFT_LICENSES = {
    "AGPL-3.0",
    "GPL-2.0",
    "GPL-3.0",
    "LGPL-2.1",
    "LGPL-3.0",
}

DUAL_USE_TERMS = {
    "covert channel",
    "dns tunnel",
    "exfil",
    "exploit",
    "hidden data",
    "jailbreak",
    "offense",
    "offensive",
    "payload",
    "red team",
    "steganography",
    "stego",
    "token exploitation",
}

MANIFEST_NAMES = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
}


def parse_github_url(value: str) -> tuple[str, str]:
    """Parse a GitHub URL, SSH URL, or owner/repo string."""
    text = value.strip()
    if not text:
        raise ValueError("empty GitHub repo value")

    ssh_match = re.match(r"^git@github\.com:([^/]+)/(.+?)(?:\.git)?$", text)
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2).removesuffix(".git")

    if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?$", text):
        owner, repo = text.removesuffix(".git").split("/", 1)
        return owner, repo

    parsed = urlparse(text)
    if parsed.netloc.lower() != "github.com":
        raise ValueError(f"not a GitHub URL: {value}")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise ValueError(f"GitHub URL must include owner and repo: {value}")
    return parts[0], parts[1].removesuffix(".git")


def evaluate_signals(signals: RepoSignals) -> PreMineResult:
    """Classify remote repo signals into a clone/no-clone CAM decision."""
    evidence = _collect_evidence(signals)
    repo_type = _classify_repo_type(signals, evidence)
    cam_value_score = _score_cam_value(signals, evidence, repo_type)
    clone_cost = _estimate_clone_cost(signals, evidence)
    risk_gate, risks = _risk_gate(signals, evidence, repo_type)
    verdict = _choose_verdict(signals, repo_type, cam_value_score, risk_gate)
    confidence = _confidence(evidence, signals)
    why = _why(signals, evidence, repo_type, verdict)
    cam_targets = _cam_targets(signals, evidence, repo_type)
    allowed_mining_scope = _allowed_scope(repo_type, verdict, risk_gate)
    blocked_by_default = _blocked_scope(repo_type, risk_gate)
    next_step = _recommended_next_step(signals.url, verdict, risk_gate)

    return PreMineResult(
        repo=signals.name_with_owner,
        url=signals.url,
        repo_type=repo_type,
        verdict=verdict,
        cam_value_score=cam_value_score,
        clone_cost=clone_cost,
        risk_gate=risk_gate,
        confidence=confidence,
        why=why,
        cam_targets=cam_targets,
        allowed_mining_scope=allowed_mining_scope,
        blocked_by_default=blocked_by_default,
        risks=risks,
        recommended_next_step=next_step,
        evidence=evidence,
    )


def premine_url(url: str) -> PreMineResult:
    signals = fetch_github_signals(url)
    return evaluate_signals(signals)


def premine_many(targets: list[str]) -> list[PreMineResult]:
    return [premine_url(target) for target in targets]


def read_targets(target: str) -> list[str]:
    path = Path(target).expanduser()
    if path.exists() and path.is_file():
        return [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    return [target]


def render_markdown_report(results: list[PreMineResult]) -> str:
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    lines = [
        "# CAM-preMine Report",
        "",
        f"Generated: {generated_at}",
        "",
        "| Repo | Verdict | Score | Type | Risk | Cost |",
        "| --- | --- | ---: | --- | --- | --- |",
    ]
    for result in results:
        lines.append(
            "| "
            f"{result.repo} | {result.verdict.value} | {result.cam_value_score} | "
            f"{result.repo_type.value} | {result.risk_gate.value} | {result.clone_cost.value} |"
        )

    for result in results:
        lines.extend(
            [
                "",
                f"## {result.repo}",
                "",
                f"- URL: {result.url}",
                f"- Verdict: {result.verdict.value}",
                f"- CAM value score: {result.cam_value_score}/100",
                f"- Clone cost: {result.clone_cost.value}",
                f"- Risk gate: {result.risk_gate.value}",
                f"- Confidence: {result.confidence}",
                f"- Recommended next step: {result.recommended_next_step}",
                "",
                "### Why",
            ]
        )
        lines.extend(f"- {item}" for item in result.why)
        lines.append("")
        lines.append("### CAM Targets")
        lines.extend(f"- {item}" for item in result.cam_targets)
        lines.append("")
        lines.append("### Allowed Mining Scope")
        lines.extend(f"- {item}" for item in result.allowed_mining_scope)
        if result.blocked_by_default:
            lines.append("")
            lines.append("### Blocked By Default")
            lines.extend(f"- {item}" for item in result.blocked_by_default)
        if result.risks:
            lines.append("")
            lines.append("### Risks")
            lines.extend(f"- {item}" for item in result.risks)

    return "\n".join(lines).rstrip() + "\n"


def results_to_json(results: list[PreMineResult]) -> str:
    return json.dumps({"results": [result.to_dict() for result in results]}, indent=2)


def append_candidate_jsonl(path: Path, results: list[PreMineResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result.to_dict(), sort_keys=True) + "\n")


def fetch_github_signals(url: str) -> RepoSignals:
    owner, repo_name = parse_github_url(url)
    api_root = "https://api.github.com"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "CAM-preMine/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    with httpx.Client(
        base_url=api_root,
        headers=headers,
        timeout=20.0,
        follow_redirects=True,
    ) as client:
        repo = _get_json(client, f"/repos/{owner}/{repo_name}")
        default_branch = repo.get("default_branch") or "main"
        tree = _get_json_or_empty(
            client,
            f"/repos/{owner}/{repo_name}/git/trees/{default_branch}",
            params={"recursive": "1"},
        )
        readme = _fetch_readme_excerpt(client, owner, repo_name)
        languages = _get_json_or_empty(client, f"/repos/{owner}/{repo_name}/languages")
        workflows = _get_json_or_empty(client, f"/repos/{owner}/{repo_name}/actions/workflows")
        check_runs = _get_json_or_empty(
            client,
            f"/repos/{owner}/{repo_name}/commits/{default_branch}/check-runs",
            headers={"Accept": "application/vnd.github+json"},
        )
        releases = _get_json_or_empty(
            client,
            f"/repos/{owner}/{repo_name}/releases",
            params={"per_page": "5"},
        )
        commits = _get_json_or_empty(
            client,
            f"/repos/{owner}/{repo_name}/commits",
            params={"per_page": "5"},
        )

    license_info = repo.get("license") or {}
    return RepoSignals(
        url=f"https://github.com/{owner}/{repo_name}",
        name_with_owner=repo.get("full_name") or f"{owner}/{repo_name}",
        description=repo.get("description") or "",
        is_archived=bool(repo.get("archived")),
        is_fork=bool(repo.get("fork")),
        default_branch=default_branch,
        stars=int(repo.get("stargazers_count") or 0),
        forks=int(repo.get("forks_count") or 0),
        open_issues=int(repo.get("open_issues_count") or 0),
        license=(license_info.get("spdx_id") or license_info.get("name") or None),
        pushed_at=repo.get("pushed_at"),
        size_kb=int(repo.get("size") or 0),
        topics=list(repo.get("topics") or []),
        languages=dict(languages if isinstance(languages, dict) else {}),
        tree_paths=_tree_paths(tree),
        workflows=_workflow_names(workflows),
        check_runs=_check_run_names(check_runs),
        releases=_release_names(releases),
        recent_commit_messages=_commit_messages(commits),
        readme_excerpt=readme,
    )


def _get_json(client: httpx.Client, path: str, **kwargs: Any) -> Any:
    response = client.get(path, **kwargs)
    if response.status_code == 404:
        raise RuntimeError(f"GitHub repository or endpoint not found: {path}")
    if response.status_code == 403:
        detail = _github_error_message(response)
        raise RuntimeError(f"GitHub API refused the request: {detail}")
    response.raise_for_status()
    return response.json()


def _get_json_or_empty(client: httpx.Client, path: str, **kwargs: Any) -> Any:
    try:
        return _get_json(client, path, **kwargs)
    except (RuntimeError, httpx.HTTPError, ValueError):
        return {}


def _github_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    return str(payload.get("message") or payload)[:300]


def _fetch_readme_excerpt(client: httpx.Client, owner: str, repo: str) -> str:
    try:
        payload = _get_json(client, f"/repos/{owner}/{repo}/readme")
    except (RuntimeError, httpx.HTTPError, ValueError):
        return ""
    content = payload.get("content")
    if not content:
        return ""
    try:
        decoded = base64.b64decode(content).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""
    return decoded[:8000]


def _tree_paths(tree_payload: Any) -> list[str]:
    if not isinstance(tree_payload, dict):
        return []
    entries = tree_payload.get("tree") or []
    paths = []
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            paths.append(entry["path"])
    return paths


def _workflow_names(payload: Any) -> list[str]:
    workflows = payload.get("workflows") if isinstance(payload, dict) else []
    return [
        str(item.get("name") or item.get("path"))
        for item in workflows
        if isinstance(item, dict)
    ]


def _check_run_names(payload: Any) -> list[str]:
    runs = payload.get("check_runs") if isinstance(payload, dict) else []
    names = []
    for run in runs:
        if isinstance(run, dict):
            name = run.get("name") or run.get("app", {}).get("name")
            conclusion = run.get("conclusion") or run.get("status")
            if name:
                names.append(f"{name}:{conclusion}" if conclusion else str(name))
    return names


def _release_names(payload: Any) -> list[str]:
    if not isinstance(payload, list):
        return []
    return [
        str(item.get("tag_name") or item.get("name"))
        for item in payload
        if isinstance(item, dict)
    ]


def _commit_messages(payload: Any) -> list[str]:
    if not isinstance(payload, list):
        return []
    messages = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        commit = item.get("commit") or {}
        message = commit.get("message")
        if message:
            messages.append(str(message).splitlines()[0])
    return messages


def _collect_evidence(signals: RepoSignals) -> dict[str, Any]:
    lower_paths = [path.lower() for path in signals.tree_paths]
    has_tests = any(_is_test_path(path) for path in lower_paths)
    skill_paths = [path for path in signals.tree_paths if path.lower().endswith("skill.md")]
    docs_paths = [path for path in signals.tree_paths if _is_doc_path(path.lower())]
    manifest_paths = [path for path in signals.tree_paths if Path(path).name in MANIFEST_NAMES]
    docker_paths = [
        path
        for path in signals.tree_paths
        if (
            Path(path).name == "Dockerfile"
            or "helm/" in path.lower()
            or path.lower().endswith("chart.yaml")
        )
    ]
    research_paths = [
        path
        for path in signals.tree_paths
        if any(
            term in path.lower()
            for term in ("paper", "validation", "benchmark", "experiment", "results")
        )
    ]
    examples_paths = [
        path
        for path in signals.tree_paths
        if path.lower().startswith("examples/") or "/examples/" in path.lower()
    ]
    text = _combined_text(signals)
    dual_use_terms = sorted(term for term in DUAL_USE_TERMS if term in text)

    return {
        "tests": int(has_tests),
        "test_paths": [path for path in signals.tree_paths if _is_test_path(path.lower())][:20],
        "skills": len(skill_paths),
        "skill_paths": skill_paths[:20],
        "docs": len(docs_paths),
        "doc_paths": docs_paths[:20],
        "manifests": len(manifest_paths),
        "manifest_paths": manifest_paths[:20],
        "ci": len(signals.workflows) + len(signals.check_runs),
        "workflows": signals.workflows[:20],
        "check_runs": signals.check_runs[:20],
        "releases": len(signals.releases),
        "release_names": signals.releases[:20],
        "languages": sorted(signals.languages.keys()),
        "language_bytes": signals.languages,
        "docker_or_helm": len(docker_paths),
        "docker_or_helm_paths": docker_paths[:20],
        "research": len(research_paths),
        "research_paths": research_paths[:20],
        "examples": len(examples_paths),
        "example_paths": examples_paths[:20],
        "dual_use_terms": dual_use_terms,
        "stars": signals.stars,
        "forks": signals.forks,
        "open_issues": signals.open_issues,
        "license": signals.license,
        "pushed_at": signals.pushed_at,
        "size_kb": signals.size_kb,
        "archived": signals.is_archived,
        "fork": signals.is_fork,
    }


def _classify_repo_type(signals: RepoSignals, evidence: dict[str, Any]) -> RepoType:
    if evidence["dual_use_terms"]:
        return RepoType.SECURITY_DUAL_USE
    if evidence["skills"] >= 2 and evidence["tests"] == 0 and evidence["manifests"] == 0:
        return RepoType.AGENT_SKILL_CORPUS
    text = _combined_text(signals)
    if evidence["manifests"] or evidence["tests"] or evidence["docker_or_helm"]:
        if "knowledge graph" in text or "pipeline" in text or "tool" in text:
            return RepoType.RUNNABLE_TOOL
        if "library" in text or "sdk" in text or "package" in text:
            return RepoType.LIBRARY
        if "app" in text or "dashboard" in text or "web" in text:
            return RepoType.APP_PRODUCT
        return RepoType.RUNNABLE_TOOL
    if evidence["research"] >= 2 and (
        "benchmark" in text or "validation" in text or "paper" in text
    ):
        return RepoType.RESEARCH_EVAL
    if evidence["docs"] >= 3 or "methodology" in text:
        return RepoType.DOCS_METHODOLOGY
    if evidence["examples"] >= 2:
        return RepoType.DATASET_OR_EXAMPLES
    if "demo" in text and evidence["tests"] == 0:
        return RepoType.DEMO_ONLY
    return RepoType.UNKNOWN


def _score_cam_value(signals: RepoSignals, evidence: dict[str, Any], repo_type: RepoType) -> int:
    score = 0
    if signals.description:
        score += 5
    if signals.readme_excerpt:
        score += 10
    if signals.languages:
        score += 10
    if evidence["tests"]:
        score += 15
    if evidence["ci"]:
        score += 15
    if evidence["manifests"]:
        score += 10
    if evidence["docs"]:
        score += min(8, evidence["docs"] * 2)
    if evidence["skills"]:
        score += min(8, evidence["skills"] * 4)
    if evidence["releases"]:
        score += 8
    if evidence["research"]:
        score += min(8, evidence["research"] * 2)
    if evidence["docker_or_helm"]:
        score += min(6, evidence["docker_or_helm"] * 3)
    if signals.stars >= 1000:
        score += 7
    elif signals.stars >= 100:
        score += 4
    elif signals.stars >= 10:
        score += 2
    if _pushed_recently(signals.pushed_at):
        score += 5
    if 0 < signals.size_kb < 75_000:
        score += 3
    if repo_type == RepoType.SECURITY_DUAL_USE:
        score += 4
    elif repo_type == RepoType.AGENT_SKILL_CORPUS:
        score += 6
    elif repo_type == RepoType.RUNNABLE_TOOL:
        score += 5
    if signals.is_archived:
        score -= 20
    if repo_type == RepoType.UNKNOWN:
        score -= 10
    return max(0, min(100, score))


def _estimate_clone_cost(signals: RepoSignals, evidence: dict[str, Any]) -> CloneCost:
    if signals.size_kb >= 250_000:
        return CloneCost.HIGH
    if signals.size_kb >= 10_000:
        return CloneCost.MEDIUM
    if evidence["docker_or_helm"] or evidence["manifests"] >= 4:
        return CloneCost.MEDIUM
    return CloneCost.LOW


def _risk_gate(
    signals: RepoSignals,
    evidence: dict[str, Any],
    repo_type: RepoType,
) -> tuple[RiskGate, list[str]]:
    if repo_type == RepoType.SECURITY_DUAL_USE:
        return (
            RiskGate.SAFETY,
            [
                "Dual-use security or steganography signals require defensive-only handling.",
                "Avoid cloning executable modules until a human approves the mining scope.",
            ],
        )
    if _license_requires_review(signals, evidence):
        return (
            RiskGate.LICENSE,
            [
                "License is missing, ambiguous, custom, or requires review before code reuse.",
            ],
        )
    if signals.is_archived:
        return (RiskGate.MAINTENANCE, ["Repository is archived; clone value may be stale."])
    return (RiskGate.NONE, [])


def _license_requires_review(signals: RepoSignals, evidence: dict[str, Any]) -> bool:
    license_id = (signals.license or "").strip()
    if not license_id:
        return True
    if license_id in PERMISSIVE_LICENSES or license_id in COPYLEFT_LICENSES:
        return False
    upper = license_id.upper()
    if upper in {"NOASSERTION", "UNKNOWN", "OTHER", "NONE"}:
        return True
    text = _combined_text(signals)
    return any(
        term in text
        for term in ("community license", "custom license", "commercial license")
    )


def _choose_verdict(
    signals: RepoSignals,
    repo_type: RepoType,
    score: int,
    risk_gate: RiskGate,
) -> Verdict:
    if signals.is_archived and score < 65:
        return Verdict.WATCHLIST
    if risk_gate == RiskGate.SAFETY:
        return Verdict.RESTRICTED_REMOTE_HARVEST
    if risk_gate == RiskGate.LICENSE:
        return Verdict.CONDITIONAL_CLONE if score >= 55 else Verdict.NEEDS_HUMAN
    if repo_type == RepoType.AGENT_SKILL_CORPUS:
        return Verdict.REMOTE_HARVEST
    if repo_type in {
        RepoType.DOCS_METHODOLOGY,
        RepoType.RESEARCH_EVAL,
        RepoType.DATASET_OR_EXAMPLES,
    }:
        return Verdict.REMOTE_HARVEST if score >= 50 else Verdict.WATCHLIST
    if (
        repo_type in {RepoType.RUNNABLE_TOOL, RepoType.APP_PRODUCT, RepoType.LIBRARY}
        and score >= 85
    ):
        return Verdict.CLONE_NOW
    if score >= 65:
        return Verdict.CONDITIONAL_CLONE
    if score >= 40:
        return Verdict.WATCHLIST
    return Verdict.SKIP


def _confidence(evidence: dict[str, Any], signals: RepoSignals) -> str:
    strong_count = sum(
        1
        for key in ("tests", "ci", "manifests", "docs", "skills", "releases", "research")
        if evidence.get(key)
    )
    if signals.readme_excerpt:
        strong_count += 1
    if strong_count >= 5:
        return "high"
    if strong_count >= 3:
        return "medium"
    return "low"


def _why(
    signals: RepoSignals,
    evidence: dict[str, Any],
    repo_type: RepoType,
    verdict: Verdict,
) -> list[str]:
    reasons = []
    if evidence["tests"]:
        reasons.append("Contains tests or test-bench files.")
    if evidence["ci"]:
        reasons.append("Exposes GitHub workflow/check-run evidence.")
    if evidence["manifests"]:
        reasons.append("Includes runnable package or build manifests.")
    if evidence["skills"]:
        reasons.append(f"Contains {evidence['skills']} agent skill file(s).")
    if evidence["research"]:
        reasons.append("Includes research, benchmark, validation, or experiment artifacts.")
    if evidence["releases"]:
        reasons.append("Has release metadata.")
    if evidence["dual_use_terms"]:
        terms = ", ".join(evidence["dual_use_terms"][:6])
        reasons.append(f"Matched dual-use safety terms: {terms}.")
    if signals.stars:
        reasons.append(f"Community signal: {signals.stars:,} stars.")
    if not reasons:
        reasons.append(f"Classified as {repo_type.value} with limited remote evidence.")
    reasons.append(f"Decision: {verdict.value}.")
    return reasons


def _cam_targets(signals: RepoSignals, evidence: dict[str, Any], repo_type: RepoType) -> list[str]:
    targets = []
    text = _combined_text(signals)
    if "knowledge graph" in text:
        targets.append("Knowledge graph and repo-understanding workflow.")
    if evidence["skills"]:
        targets.append("Agent skill extraction and skill packaging patterns.")
    if evidence["tests"]:
        targets.append("Verification harnesses, regression tests, and test taxonomy.")
    if evidence["research"]:
        targets.append("Research, benchmark, validation, and result-provenance methods.")
    if evidence["docker_or_helm"]:
        targets.append("Deployment, Docker, Helm, and service operation patterns.")
    if repo_type == RepoType.SECURITY_DUAL_USE:
        targets.append("Defensive taxonomy and validation evidence only.")
    if not targets:
        targets.append("General architecture and documentation patterns.")
    return targets


def _allowed_scope(repo_type: RepoType, verdict: Verdict, risk_gate: RiskGate) -> list[str]:
    if risk_gate == RiskGate.SAFETY:
        return [
            "Defensive taxonomy, validation notes, result provenance, and safe test metadata.",
            "Do not mine payload-generation, evasion, exploitation, or covert-channel procedures.",
        ]
    if risk_gate == RiskGate.LICENSE:
        return [
            "Remote metadata, README, docs, tests, and manifests for assessment only.",
            "Confirm license terms before cloning or reusing source code.",
        ]
    if repo_type == RepoType.AGENT_SKILL_CORPUS or verdict == Verdict.REMOTE_HARVEST:
        return [
            "Harvest SKILL.md files, docs, examples, and research notes remotely before clone.",
            "Promote to local clone only if remote harvest shows implementation value.",
        ]
    if verdict == Verdict.CLONE_NOW:
        return ["Full CAM mine after clone, including code, tests, docs, and package structure."]
    if verdict == Verdict.CONDITIONAL_CLONE:
        return ["Clone after reviewing identified risks; mine docs/tests first, then source."]
    return ["Watch remote metadata and defer local clone until stronger evidence appears."]


def _blocked_scope(repo_type: RepoType, risk_gate: RiskGate) -> list[str]:
    if risk_gate == RiskGate.SAFETY or repo_type == RepoType.SECURITY_DUAL_USE:
        return [
            "Executable offensive modules.",
            "Payload-generation, covert-channel operation, or evasion procedures.",
            "Automated local execution during preMine.",
        ]
    if risk_gate == RiskGate.LICENSE:
        return ["Source-code reuse until license review is complete."]
    return []


def _recommended_next_step(url: str, verdict: Verdict, risk_gate: RiskGate) -> str:
    if verdict == Verdict.CLONE_NOW:
        return f"git clone {url}"
    if risk_gate == RiskGate.SAFETY:
        return "Do not clone by default; remote-harvest defensive evidence only."
    if risk_gate == RiskGate.LICENSE:
        return f"Review license terms first; clone only if approved: git clone {url}"
    if verdict == Verdict.REMOTE_HARVEST:
        return "Remote-harvest selected files through the GitHub API before cloning."
    if verdict == Verdict.CONDITIONAL_CLONE:
        return f"Review risks and expected yield, then clone if still useful: git clone {url}"
    if verdict == Verdict.WATCHLIST:
        return "Put on watchlist; refresh remote signals later."
    if verdict == Verdict.NEEDS_HUMAN:
        return "Needs human review before clone or reuse."
    return "Skip for now; expected CAM value is too low."


def _is_test_path(path: str) -> bool:
    name = Path(path).name
    return (
        path.startswith("test/")
        or path.startswith("tests/")
        or "/test/" in path
        or "/tests/" in path
        or name.startswith("test_")
        or name.endswith(".test.js")
        or name.endswith(".test.ts")
        or name.endswith(".test.mjs")
        or name.endswith(".spec.js")
        or name.endswith(".spec.ts")
        or "test-bench" in name
    )


def _is_doc_path(path: str) -> bool:
    name = Path(path).name.lower()
    return (
        path.startswith("docs/")
        or "/docs/" in path
        or path.startswith("documentation/")
        or name in {"readme.md", "changelog.md", "paper.md", "validation.md"}
        or name.endswith(".md")
    )


def _combined_text(signals: RepoSignals) -> str:
    parts = [
        signals.name_with_owner,
        signals.description,
        " ".join(signals.topics),
        signals.readme_excerpt,
        " ".join(signals.tree_paths[:1000]),
        " ".join(signals.recent_commit_messages),
    ]
    return " ".join(part for part in parts if part).lower()


def _pushed_recently(pushed_at: str | None) -> bool:
    if not pushed_at:
        return False
    try:
        parsed = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(UTC) - parsed).days <= 365
