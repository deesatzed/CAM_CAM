"""Repo universe inventory, clustering, risk scoring, and mindmap exports."""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
    "dist",
    "build",
    "target",
    ".next",
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
    ".java": "Java",
    ".kt": "Kotlin",
    ".dart": "Dart",
    ".vue": "Vue",
    ".html": "HTML",
    ".css": "CSS",
    ".md": "Markdown",
    ".sh": "Shell",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++",
}

DOMAIN_KEYWORDS = {
    "repo_intelligence": [
        "repo",
        "codebase",
        "architecture",
        "dependency",
        "git history",
        "mcp",
        "workspace",
        "snippet",
        "search",
        "index",
    ],
    "agent_safety": [
        "policy",
        "receipt",
        "audit",
        "sandbox",
        "guardrail",
        "preflight",
        "security",
        "semantic",
        "trust",
        "risk",
    ],
    "rag_knowledge": [
        "rag",
        "knowledge",
        "retrieval",
        "wiki",
        "document",
        "citation",
        "graph",
        "openkb",
        "lightrag",
        "memory",
    ],
    "medical_clinical": [
        "medical",
        "clinical",
        "patient",
        "hipaa",
        "phi",
        "pii",
        "diagnosis",
        "triage",
        "biomedical",
        "oncology",
    ],
    "learning_evolution": [
        "learn",
        "evolve",
        "evolution",
        "rl",
        "reinforcement",
        "skill",
        "trajectory",
        "experiment",
        "fitness",
        "benchmark",
    ],
    "browser_local_tools": [
        "browser",
        "webgpu",
        "local",
        "offline",
        "desktop",
        "video",
        "search",
        "cli",
        "dashboard",
        "tool",
    ],
    "mindmap_graphrag": [
        "mindmap",
        "markmap",
        "freeplane",
        "logseq",
        "graph",
        "wiki",
        "outline",
        "concept",
        "link",
        "node",
    ],
}

RISK_PATTERNS = {
    "dirty-worktree": "Repository has uncommitted or untracked changes.",
    "no-readme": "No README was found, so purpose is not self-evident.",
    "no-tests": "No obvious tests directory or test file was found.",
    "medical-sensitive": "Medical/clinical language appears; PHI/PII safeguards may matter.",
    "security-sensitive": "Security/sandbox/proxy language appears; write actions need caution.",
    "llm-key-sensitive": "LLM/API-key language appears; scan secrets before model ingestion.",
    "large-node-project": "Node project detected; dependency and build cost may be high.",
}


@dataclass
class RepoProfile:
    name: str
    path: str
    is_git: bool
    remote: str = ""
    branch: str = ""
    head: str = ""
    last_commit_date: str = ""
    dirty: bool = False
    untracked_count: int = 0
    file_count: int = 0
    language_counts: dict[str, int] = field(default_factory=dict)
    primary_languages: list[str] = field(default_factory=list)
    readme_title: str = ""
    readme_excerpt: str = ""
    domain_scores: dict[str, int] = field(default_factory=dict)
    primary_cluster: str = "uncategorized"
    risk_flags: list[str] = field(default_factory=list)
    evidence_terms: list[str] = field(default_factory=list)


@dataclass
class RescueReport:
    root: str
    generated_at: str
    repos: list[RepoProfile]
    clusters: dict[str, list[str]]
    duplicate_groups: list[list[str]]
    opportunities: list[dict[str, Any]]
    graph: dict[str, list[dict[str, Any]]]
    receipts: list[dict[str, Any]]

    def to_json(self) -> str:
        payload = {
            "root": self.root,
            "generated_at": self.generated_at,
            "repos": [asdict(repo) for repo in self.repos],
            "clusters": self.clusters,
            "duplicate_groups": self.duplicate_groups,
            "opportunities": self.opportunities,
            "graph": self.graph,
            "receipts": self.receipts,
        }
        return json.dumps(payload, indent=2, sort_keys=True)


def enrich_with_cam_rag(
    report: RescueReport,
    rag_folder: Path,
    *,
    query: str | None = None,
    module_name: str = "cam_rag",
) -> dict[str, Any]:
    """Attach optional CAM-RAG retrieval evidence to a report.

    This keeps CAM-RAG outside the default dependency set. If the caller opts in
    with ``--rag-folder``, CAM_CAM asks the specialist package for cited context
    and stores the result as a receipt plus graph evidence nodes.
    """
    from claw.memory.cam_rag_bridge import CamRagBridge

    bridge = CamRagBridge(module_name=module_name)
    indexed_docs = bridge.ingest_folder(rag_folder, domain="repo_rescue")
    retrieval_query = query or _default_rag_query(report)
    chunks = bridge.retrieve(retrieval_query, top_k=5, domain="repo_rescue")
    receipt = bridge.receipt_for(retrieval_query, chunks).as_dict()
    receipt_payload = {
        "kind": "cam-rag-retrieval",
        "folder": str(Path(rag_folder).resolve()),
        "indexed_docs": indexed_docs,
        "receipt": receipt,
        "chunks": [
            {
                "document_id": chunk.document_id,
                "score": chunk.score,
                "confidence": chunk.confidence,
                "citation": chunk.citation,
                "routing_reason": chunk.routing_reason,
                "excerpt": chunk.text[:500],
            }
            for chunk in chunks
        ],
    }
    report.receipts.append(receipt_payload)
    _attach_rag_graph(report, receipt_payload)
    return receipt_payload


def _default_rag_query(report: RescueReport) -> str:
    opportunity = report.opportunities[0]["title"] if report.opportunities else "repo rescue"
    clusters = ", ".join(list(report.clusters)[:4])
    return f"{opportunity} repo triage GraphRAG evidence {clusters}".strip()


def _attach_rag_graph(report: RescueReport, receipt_payload: dict[str, Any]) -> None:
    receipt = receipt_payload.get("receipt", {})
    query = str(receipt.get("query") or "CAM-RAG retrieval")
    root_id = "rag:cam-rag-receipt"
    report.graph.setdefault("nodes", []).append({
        "id": root_id,
        "type": "rag_receipt",
        "label": "CAM-RAG receipt",
        "query": query,
        "confidence": receipt.get("confidence", 0.0),
        "result_count": receipt.get("result_count", 0),
    })
    report.graph.setdefault("edges", []).append({
        "source": root_id,
        "target": "cluster:rag_knowledge",
        "kind": "grounds",
        "weight": max(int(receipt.get("result_count") or 1), 1),
    })
    for index, chunk in enumerate(receipt_payload.get("chunks", []), 1):
        chunk_id = f"rag:chunk:{index}"
        report.graph["nodes"].append({
            "id": chunk_id,
            "type": "rag_chunk",
            "label": chunk.get("document_id") or chunk.get("citation") or f"chunk {index}",
            "citation": chunk.get("citation", ""),
            "confidence": chunk.get("confidence", 0.0),
        })
        report.graph["edges"].append({
            "source": root_id,
            "target": chunk_id,
            "kind": "retrieved",
            "weight": float(chunk.get("score") or 0.0),
        })


def scan_universe(root: Path, max_repos: int | None = None) -> RescueReport:
    root = root.resolve()
    repo_paths = discover_repo_paths(root)
    if max_repos is not None:
        repo_paths = repo_paths[:max_repos]

    repos = [profile_repo(path) for path in repo_paths]
    clusters = build_clusters(repos)
    duplicate_groups = find_duplicate_groups(repos)
    graph = build_graph(repos, clusters, duplicate_groups)
    opportunities = rank_opportunities(repos, clusters)
    receipts = build_receipts(root, repos)

    return RescueReport(
        root=str(root),
        generated_at=datetime.now(timezone.utc).isoformat(),
        repos=repos,
        clusters=clusters,
        duplicate_groups=duplicate_groups,
        opportunities=opportunities,
        graph=graph,
        receipts=receipts,
    )


def discover_repo_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name in SKIP_DIRS:
            continue
        if (child / ".git").exists():
            paths.append(child)
    return paths


def profile_repo(path: Path) -> RepoProfile:
    readme_text = read_readme(path)
    language_counts, file_count = count_languages(path)
    git_status = inspect_git(path)
    domain_scores, evidence_terms = score_domains(path.name, readme_text, language_counts)
    primary_cluster = (
        max(domain_scores, key=domain_scores.get) if domain_scores else "uncategorized"
    )
    if domain_scores.get(primary_cluster, 0) <= 0:
        primary_cluster = "uncategorized"

    profile = RepoProfile(
        name=path.name,
        path=str(path),
        is_git=(path / ".git").exists(),
        remote=git_status["remote"],
        branch=git_status["branch"],
        head=git_status["head"],
        last_commit_date=git_status["last_commit_date"],
        dirty=git_status["dirty"],
        untracked_count=git_status["untracked_count"],
        file_count=file_count,
        language_counts=dict(language_counts),
        primary_languages=[lang for lang, _ in language_counts.most_common(4)],
        readme_title=extract_title(readme_text) or path.name,
        readme_excerpt=extract_excerpt(readme_text),
        domain_scores=domain_scores,
        primary_cluster=primary_cluster,
        risk_flags=[],
        evidence_terms=evidence_terms[:12],
    )
    profile.risk_flags = detect_risks(profile, readme_text)
    return profile


def inspect_git(path: Path) -> dict[str, Any]:
    status = git(path, "status", "--short")
    return {
        "remote": git(path, "remote", "get-url", "origin"),
        "branch": git(path, "branch", "--show-current"),
        "head": git(path, "rev-parse", "--short", "HEAD"),
        "last_commit_date": git(path, "log", "-1", "--format=%cI"),
        "dirty": bool(status.strip()),
        "untracked_count": sum(1 for line in status.splitlines() if line.startswith("??")),
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


def read_readme(path: Path) -> str:
    for name in ("README.md", "README.rst", "readme.md", "Readme.md"):
        candidate = path / name
        if candidate.exists():
            return candidate.read_text(encoding="utf-8", errors="replace")[:12000]
    return ""


def count_languages(path: Path) -> tuple[Counter[str], int]:
    counts: Counter[str] = Counter()
    file_count = 0
    for current, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for filename in files:
            if filename.startswith(".DS_Store"):
                continue
            file_count += 1
            ext = Path(filename).suffix.lower()
            language = LANGUAGE_BY_EXTENSION.get(ext)
            if language:
                counts[language] += 1
    return counts, file_count


def score_domains(
    name: str,
    readme_text: str,
    language_counts: Counter[str],
) -> tuple[dict[str, int], list[str]]:
    haystack = f"{name}\n{readme_text}".lower()
    scores: dict[str, int] = {}
    evidence: list[str] = []
    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            occurrences = haystack.count(keyword.lower())
            if occurrences:
                score += min(occurrences, 4)
                evidence.append(keyword)
        scores[domain] = score
    if language_counts.get("Markdown", 0) > 20:
        scores["rag_knowledge"] += 1
    if language_counts.get("Python", 0) and language_counts.get("TypeScript", 0):
        scores["browser_local_tools"] += 1
    return scores, sorted(set(evidence))


def detect_risks(profile: RepoProfile, readme_text: str) -> list[str]:
    text = f"{profile.name}\n{readme_text}".lower()
    flags: list[str] = []
    if profile.dirty:
        flags.append("dirty-worktree")
    if not readme_text:
        flags.append("no-readme")
    if not has_tests(Path(profile.path)):
        flags.append("no-tests")
    if any(term in text for term in ("medical", "clinical", "patient", "hipaa", "phi", "pii")):
        flags.append("medical-sensitive")
    if any(term in text for term in ("security", "sandbox", "proxy", "audit", "credential")):
        flags.append("security-sensitive")
    if any(term in text for term in ("api key", "openrouter", "token", "secret", ".env")):
        flags.append("llm-key-sensitive")
    has_package_json = (Path(profile.path) / "package.json").exists()
    has_node_modules = (Path(profile.path) / "node_modules").exists()
    if has_package_json and has_node_modules:
        flags.append("large-node-project")
    return sorted(set(flags))


def has_tests(path: Path) -> bool:
    if (path / "tests").is_dir() or (path / "test").is_dir():
        return True
    for candidate in path.glob("test_*.py"):
        if candidate.is_file():
            return True
    for candidate in path.glob("*.test.*"):
        if candidate.is_file():
            return True
    return False


def build_clusters(repos: list[RepoProfile]) -> dict[str, list[str]]:
    clusters: dict[str, list[str]] = defaultdict(list)
    for repo in repos:
        clusters[repo.primary_cluster].append(repo.name)
    return {name: sorted(values) for name, values in sorted(clusters.items())}


def find_duplicate_groups(repos: list[RepoProfile]) -> list[list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for repo in repos:
        grouped[normalize_repo_name(repo.name)].append(repo.name)
    return [sorted(names) for names in grouped.values() if len(names) > 1]


def normalize_repo_name(name: str) -> str:
    text = name.lower()
    text = re.sub(r"(\b|[-_])(main|copy|backup|bu|old|new|v\d+)\b", "", text)
    text = re.sub(r"[-_\s]+", "", text)
    text = re.sub(r"\d{3,}$", "", text)
    return text


def build_graph(
    repos: list[RepoProfile],
    clusters: dict[str, list[str]],
    duplicate_groups: list[list[str]],
) -> dict[str, list[dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for cluster, names in clusters.items():
        nodes.append({
            "id": f"cluster:{cluster}",
            "type": "cluster",
            "label": cluster,
            "size": len(names),
        })
    for repo in repos:
        repo_id = f"repo:{repo.name}"
        nodes.append({
            "id": repo_id,
            "type": "repo",
            "label": repo.name,
            "cluster": repo.primary_cluster,
            "risk_count": len(repo.risk_flags),
        })
        edges.append({
            "source": repo_id,
            "target": f"cluster:{repo.primary_cluster}",
            "kind": "belongs_to",
            "weight": max(repo.domain_scores.get(repo.primary_cluster, 1), 1),
        })
    for group in duplicate_groups:
        group_id = f"duplicate:{normalize_repo_name(group[0])}"
        nodes.append({"id": group_id, "type": "duplicate_group", "label": ", ".join(group)})
        for name in group:
            edges.append({"source": f"repo:{name}", "target": group_id, "kind": "duplicate_name"})
    return {"nodes": nodes, "edges": edges}


def rank_opportunities(
    repos: list[RepoProfile],
    clusters: dict[str, list[str]],
) -> list[dict[str, Any]]:
    cluster_counts = {name: len(values) for name, values in clusters.items()}
    templates = [
        {
            "title": "Repo Rescue Desk",
            "needs": ["repo_intelligence", "rag_knowledge", "agent_safety"],
            "useful_output": (
                "A dashboard that inventories repos, ranks opportunities, "
                "and exports mindmaps."
            ),
            "measure": "repos scanned, clusters found, risks flagged, artifacts generated",
        },
        {
            "title": "Guarded Autonomous Engineer",
            "needs": ["agent_safety", "learning_evolution", "repo_intelligence"],
            "useful_output": (
                "A branch-first patch runner with receipts and blocked direct-main writes."
            ),
            "measure": "unsafe actions blocked, allowed patch path succeeds, tests pass",
        },
        {
            "title": "Local Knowledge Appliance",
            "needs": ["rag_knowledge", "browser_local_tools", "repo_intelligence"],
            "useful_output": "A private searchable knowledge base over repos, docs, and decisions.",
            "measure": "retrieval hit rate, source citations, repeated-session recall",
        },
        {
            "title": "Medical Privacy Workbench",
            "needs": ["medical_clinical", "agent_safety", "rag_knowledge"],
            "useful_output": (
                "A local PHI/PII-aware document and repo review desk for medical projects."
            ),
            "measure": "PII cases caught, citation grounding, false-positive review rate",
        },
        {
            "title": "Learning Tournament Bench",
            "needs": ["learning_evolution", "repo_intelligence", "agent_safety"],
            "useful_output": "A repeatable task tournament that learns which methods work best.",
            "measure": "baseline vs learned-method success, cost, retry reduction",
        },
        {
            "title": "Mindmap GraphRAG Studio",
            "needs": ["mindmap_graphrag", "rag_knowledge", "repo_intelligence"],
            "useful_output": "Logseq, Freeplane, and Markmap exports from a repo knowledge graph.",
            "measure": "graph nodes, cross-links, orphan clusters, useful query context chunks",
        },
    ]
    opportunities = []
    for template in templates:
        support = sum(cluster_counts.get(name, 0) for name in template["needs"])
        evidence = []
        for need in template["needs"]:
            evidence.extend(clusters.get(need, [])[:5])
        opportunities.append({
            "title": template["title"],
            "score": support,
            "required_clusters": template["needs"],
            "supporting_repos": evidence[:12],
            "useful_output": template["useful_output"],
            "measurable_outcome": template["measure"],
        })
    return sorted(opportunities, key=lambda item: (-item["score"], item["title"]))


def build_receipts(root: Path, repos: list[RepoProfile]) -> list[dict[str, Any]]:
    receipts = [
        {
            "kind": "scan-root",
            "path": str(root),
            "repo_count": len(repos),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    ]
    receipts.extend(
        {
            "kind": "source-repo-state",
            "repo": repo.name,
            "path": repo.path,
            "head": repo.head,
            "dirty": repo.dirty,
            "remote": repo.remote,
        }
        for repo in repos
    )
    return receipts


def extract_title(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def extract_excerpt(text: str, max_len: int = 240) -> str:
    paragraphs = [
        re.sub(r"\s+", " ", line.strip())
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "[!", "<", "!", "|"))
    ]
    if not paragraphs:
        return ""
    return paragraphs[0][:max_len]


def write_artifacts(report: RescueReport, out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "inventory_json": out_dir / "repo_inventory.json",
        "dashboard_html": out_dir / "repo_rescue_dashboard.html",
        "opportunities_md": out_dir / "opportunity_rankings.md",
        "risk_report_md": out_dir / "risk_report.md",
        "markmap_md": out_dir / "repo_mindmap_markmap.md",
        "freeplane_mm": out_dir / "repo_mindmap_freeplane.mm",
        "graph_json": out_dir / "repo_graph.json",
        "graphrag_md": out_dir / "graphrag_context.md",
    }
    paths["inventory_json"].write_text(report.to_json(), encoding="utf-8")
    paths["dashboard_html"].write_text(render_dashboard(report), encoding="utf-8")
    paths["opportunities_md"].write_text(render_opportunities(report), encoding="utf-8")
    paths["risk_report_md"].write_text(render_risk_report(report), encoding="utf-8")
    paths["markmap_md"].write_text(render_markmap(report), encoding="utf-8")
    paths["freeplane_mm"].write_text(render_freeplane(report), encoding="utf-8")
    paths["graph_json"].write_text(
        json.dumps(report.graph, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    paths["graphrag_md"].write_text(render_graphrag_context(report), encoding="utf-8")
    rag_receipt = latest_cam_rag_receipt(report)
    if rag_receipt:
        receipt_json = out_dir / "cam_rag_receipt.json"
        receipt_md = out_dir / "cam_rag_receipt.md"
        receipt_json.write_text(json.dumps(rag_receipt, indent=2, sort_keys=True), encoding="utf-8")
        receipt_md.write_text(render_cam_rag_receipt(rag_receipt), encoding="utf-8")
        paths["cam_rag_receipt_json"] = receipt_json
        paths["cam_rag_receipt_md"] = receipt_md
    write_logseq_pages(report, out_dir / "logseq")
    return {name: str(path) for name, path in paths.items()}


def latest_cam_rag_receipt(report: RescueReport) -> dict[str, Any] | None:
    for receipt in reversed(report.receipts):
        if receipt.get("kind") == "cam-rag-retrieval":
            return receipt
    return None


def render_cam_rag_receipt(receipt: dict[str, Any]) -> str:
    inner = receipt.get("receipt", {})
    lines = [
        "# CAM-RAG Retrieval Receipt",
        "",
        f"- Folder: `{receipt.get('folder', '')}`",
        f"- Indexed docs: **{receipt.get('indexed_docs', 0)}**",
        f"- Query: `{inner.get('query', '')}`",
        f"- Results: **{inner.get('result_count', 0)}**",
        f"- Confidence: **{inner.get('confidence', 0.0)}**",
        "",
        "## Citations",
    ]
    for citation in inner.get("citations", []):
        lines.append(f"- `{citation}`")
    lines.extend(["", "## Retrieved Chunks"])
    for chunk in receipt.get("chunks", []):
        lines.extend([
            f"### {chunk.get('document_id', 'chunk')}",
            "",
            f"- Citation: `{chunk.get('citation', '')}`",
            f"- Score: {chunk.get('score', 0.0)}",
            f"- Confidence: {chunk.get('confidence', 0.0)}",
            "",
            chunk.get("excerpt", ""),
            "",
        ])
    return "\n".join(lines)


def render_opportunities(report: RescueReport) -> str:
    lines = [
        "# Repo Rescue Desk Opportunity Rankings",
        "",
        f"Root: `{report.root}`",
        f"Repos scanned: **{len(report.repos)}**",
        "",
    ]
    for idx, item in enumerate(report.opportunities, 1):
        lines.extend([
            f"## {idx}. {item['title']} — score {item['score']}",
            "",
            f"- Useful output: {item['useful_output']}",
            f"- Measurable outcome: {item['measurable_outcome']}",
            f"- Required clusters: {', '.join(item['required_clusters'])}",
            f"- Supporting repos: {', '.join(item['supporting_repos']) or 'none'}",
            "",
        ])
    return "\n".join(lines)


def render_risk_report(report: RescueReport) -> str:
    lines = ["# Repo Rescue Desk Risk Report", ""]
    risk_counter = Counter(flag for repo in report.repos for flag in repo.risk_flags)
    lines.append("## Summary")
    for flag, count in risk_counter.most_common():
        lines.append(f"- **{flag}**: {count} — {RISK_PATTERNS.get(flag, '')}")
    lines.append("")
    lines.append("## Repositories With Flags")
    for repo in sorted(report.repos, key=lambda r: (-len(r.risk_flags), r.name.lower())):
        if repo.risk_flags:
            lines.append(f"- **{repo.name}**: {', '.join(repo.risk_flags)}")
    lines.append("")
    return "\n".join(lines)


def render_markmap(report: RescueReport) -> str:
    lines = ["# CAM Repo Rescue Desk", ""]
    lines.append("## Opportunities")
    for item in report.opportunities[:8]:
        lines.append(f"- {item['title']} ({item['score']})")
        lines.append(f"  - Output: {item['useful_output']}")
        lines.append(f"  - Measure: {item['measurable_outcome']}")
    lines.append("")
    lines.append("## Clusters")
    for cluster, names in report.clusters.items():
        lines.append(f"- {cluster} ({len(names)})")
        for name in names[:20]:
            lines.append(f"  - {name}")
    lines.append("")
    lines.append("## Risks")
    risk_counts = Counter(flag for repo in report.repos for flag in repo.risk_flags)
    for flag, count in risk_counts.most_common():
        lines.append(f"- {flag}: {count}")
    rag_receipt = latest_cam_rag_receipt(report)
    if rag_receipt:
        inner = rag_receipt.get("receipt", {})
        lines.append("")
        lines.append("## CAM-RAG Evidence")
        lines.append(f"- Query: {inner.get('query', '')}")
        lines.append(f"- Results: {inner.get('result_count', 0)}")
        lines.append(f"- Confidence: {inner.get('confidence', 0.0)}")
        for citation in inner.get("citations", [])[:8]:
            lines.append(f"  - {citation}")
    return "\n".join(lines) + "\n"


def render_freeplane(report: RescueReport) -> str:
    root = ET.Element("map", version="freeplane 1.11.1")
    root_node = ET.SubElement(root, "node", TEXT="CAM Repo Rescue Desk")
    opportunities = ET.SubElement(root_node, "node", TEXT="Opportunities")
    for item in report.opportunities[:8]:
        item_node = ET.SubElement(opportunities, "node", TEXT=f"{item['title']} ({item['score']})")
        ET.SubElement(item_node, "node", TEXT=item["useful_output"])
        ET.SubElement(item_node, "node", TEXT=item["measurable_outcome"])
    clusters = ET.SubElement(root_node, "node", TEXT="Clusters")
    for cluster, names in report.clusters.items():
        cluster_node = ET.SubElement(clusters, "node", TEXT=f"{cluster} ({len(names)})")
        for name in names[:40]:
            ET.SubElement(cluster_node, "node", TEXT=name)
    risks = ET.SubElement(root_node, "node", TEXT="Risks")
    risk_counts = Counter(flag for repo in report.repos for flag in repo.risk_flags)
    for flag, count in risk_counts.most_common():
        ET.SubElement(risks, "node", TEXT=f"{flag}: {count}")
    rag_receipt = latest_cam_rag_receipt(report)
    if rag_receipt:
        inner = rag_receipt.get("receipt", {})
        rag_node = ET.SubElement(root_node, "node", TEXT="CAM-RAG Evidence")
        ET.SubElement(rag_node, "node", TEXT=f"Query: {inner.get('query', '')}")
        ET.SubElement(rag_node, "node", TEXT=f"Results: {inner.get('result_count', 0)}")
        for citation in inner.get("citations", [])[:8]:
            ET.SubElement(rag_node, "node", TEXT=str(citation))
    return ET.tostring(root, encoding="unicode")


def write_logseq_pages(report: RescueReport, out_dir: Path) -> None:
    pages = out_dir / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    index_lines = ["- CAM Repo Rescue Desk", f"  - Root:: {report.root}", "  - Opportunities"]
    for item in report.opportunities[:8]:
        index_lines.append(f"    - [[{item['title']}]] score:: {item['score']}")
    index_lines.append("  - Clusters")
    for cluster in report.clusters:
        index_lines.append(f"    - [[Cluster {cluster}]]")
    if latest_cam_rag_receipt(report):
        index_lines.append("  - [[CAM-RAG Evidence]]")
    (pages / "CAM Repo Rescue Desk.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")

    for cluster, names in report.clusters.items():
        lines = [f"- Cluster:: {cluster}", f"  - Repo count:: {len(names)}", "  - Repos"]
        for name in names[:80]:
            lines.append(f"    - [[Repo {name}]]")
        (pages / f"Cluster {cluster}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    for item in report.opportunities[:8]:
        lines = [
            f"- Opportunity:: {item['title']}",
            f"  - Score:: {item['score']}",
            f"  - Useful output:: {item['useful_output']}",
            f"  - Measurable outcome:: {item['measurable_outcome']}",
            "  - Supporting repos",
        ]
        for name in item["supporting_repos"]:
            lines.append(f"    - [[Repo {name}]]")
        (pages / f"{item['title']}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    rag_receipt = latest_cam_rag_receipt(report)
    if rag_receipt:
        inner = rag_receipt.get("receipt", {})
        lines = [
            "- CAM-RAG Evidence",
            f"  - Query:: {inner.get('query', '')}",
            f"  - Result count:: {inner.get('result_count', 0)}",
            f"  - Confidence:: {inner.get('confidence', 0.0)}",
            "  - Citations",
        ]
        for citation in inner.get("citations", [])[:12]:
            lines.append(f"    - {citation}")
        (pages / "CAM-RAG Evidence.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_graphrag_context(report: RescueReport) -> str:
    lines = ["# GraphRAG Context: CAM Repo Rescue Desk", ""]
    lines.append("## Retrieval Chunks")
    for cluster, names in report.clusters.items():
        lines.append(f"### Cluster: {cluster}")
        lines.append(f"Repos: {', '.join(names[:40])}")
        lines.append("")
    lines.append("## Opportunity Evidence")
    for item in report.opportunities:
        lines.append(f"### {item['title']}")
        lines.append(f"Useful output: {item['useful_output']}")
        lines.append(f"Measure: {item['measurable_outcome']}")
        lines.append(f"Supporting repos: {', '.join(item['supporting_repos'])}")
        lines.append("")
    rag_receipt = latest_cam_rag_receipt(report)
    if rag_receipt:
        inner = rag_receipt.get("receipt", {})
        lines.append("## CAM-RAG Cited Context")
        lines.append(f"Query: {inner.get('query', '')}")
        lines.append(f"Confidence: {inner.get('confidence', 0.0)}")
        lines.append("")
        for chunk in rag_receipt.get("chunks", []):
            lines.append(f"### Citation: {chunk.get('citation', '')}")
            lines.append(chunk.get("excerpt", ""))
            lines.append("")
    return "\n".join(lines)


def render_dashboard(report: RescueReport) -> str:
    risk_counter = Counter(flag for repo in report.repos for flag in repo.risk_flags)
    rag_receipt = latest_cam_rag_receipt(report)
    cluster_cards = "\n".join(
        f"<section class='panel'><h3>{html.escape(cluster)}</h3>"
        f"<p>{len(names)} repos</p><ul>{render_repo_list_items(names[:12])}</ul></section>"
        for cluster, names in report.clusters.items()
    )
    opportunity_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(item['title'])}</td>"
        f"<td>{item['score']}</td>"
        f"<td>{html.escape(item['useful_output'])}</td>"
        f"<td>{html.escape(item['measurable_outcome'])}</td>"
        "</tr>"
        for item in report.opportunities
    )
    risk_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(flag)}</td>"
        f"<td>{count}</td>"
        f"<td>{html.escape(RISK_PATTERNS.get(flag, ''))}</td>"
        "</tr>"
        for flag, count in risk_counter.most_common()
    )
    rag_section = ""
    if rag_receipt:
        inner = rag_receipt.get("receipt", {})
        citations = "".join(
            f"<li><code>{html.escape(str(citation))}</code></li>"
            for citation in inner.get("citations", [])[:8]
        )
        rag_section = f"""
    <h2>CAM-RAG Evidence</h2>
    <section class="panel">
      <p><b>Query:</b> <code>{html.escape(str(inner.get('query', '')))}</code></p>
      <p>
        <b>Results:</b> {inner.get('result_count', 0)}
        · <b>Confidence:</b> {inner.get('confidence', 0.0)}
      </p>
      <ul>{citations}</ul>
    </section>"""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CAM Repo Rescue Desk</title>
  <style>
    body {{
      margin: 0;
      font-family: Inter, system-ui, sans-serif;
      color: #182026;
      background: #f7f8f5;
    }}
    header {{ padding: 32px 40px; background: #18332f; color: white; }}
    header h1 {{ margin: 0 0 8px; font-size: 34px; }}
    header p {{ margin: 0; max-width: 900px; color: #dce9e4; }}
    main {{ padding: 28px 40px 48px; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }}
    .metric, .panel {{
      background: white;
      border: 1px solid #dfe5dc;
      border-radius: 8px;
      padding: 16px;
    }}
    .metric b {{ display: block; font-size: 28px; color: #176b5b; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 12px;
    }}
    h2 {{ margin-top: 32px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: white;
      border: 1px solid #dfe5dc;
    }}
    th, td {{
      text-align: left;
      border-bottom: 1px solid #e8ede5;
      padding: 10px;
      vertical-align: top;
    }}
    th {{ background: #edf3ef; }}
    ul {{ padding-left: 18px; margin-bottom: 0; }}
    code {{ background: #edf3ef; padding: 2px 5px; border-radius: 4px; }}
  </style>
</head>
<body>
  <header>
    <h1>CAM Repo Rescue Desk</h1>
    <p>
      Local repo-universe inventory, opportunity ranking, risk triage, and
      mindmap exports. Root: <code>{html.escape(report.root)}</code>
    </p>
  </header>
  <main>
    <section class="metrics">
      <div class="metric"><b>{len(report.repos)}</b>Repos scanned</div>
      <div class="metric"><b>{len(report.clusters)}</b>Capability clusters</div>
      <div class="metric"><b>{sum(risk_counter.values())}</b>Risk flags</div>
      <div class="metric"><b>{len(report.duplicate_groups)}</b>Duplicate-name groups</div>
    </section>
    <h2>Top Opportunities</h2>
    <table>
      <thead>
        <tr><th>Opportunity</th><th>Score</th><th>Useful Output</th><th>Measure</th></tr>
      </thead>
      <tbody>{opportunity_rows}</tbody>
    </table>
    <h2>Capability Clusters</h2>
    <section class="grid">{cluster_cards}</section>
    <h2>Risk Summary</h2>
    <table><thead><tr><th>Flag</th><th>Count</th><th>Meaning</th></tr></thead><tbody>{risk_rows}</tbody></table>
    {rag_section}
  </main>
</body>
</html>
"""


def render_repo_list_items(names: list[str]) -> str:
    return "".join(f"<li>{html.escape(name)}</li>" for name in names)
