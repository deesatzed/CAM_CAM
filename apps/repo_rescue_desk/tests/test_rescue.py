from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

from repo_rescue_desk.cli import main
from repo_rescue_desk.rescue import enrich_with_cam_rag, scan_universe, write_artifacts


class FakeDocument:
    def __init__(self, id: str, text: str, metadata=None, domain: str = "default"):
        self.id = id
        self.text = text
        self.metadata = metadata or {}
        self.domain = domain


class FakeRetrievalResult:
    def __init__(self, document, score: float, routing_reason=None):
        self.document = document
        self.score = score
        self.routing_reason = routing_reason


class FakeDeterministicRetriever:
    def __init__(self, rules_path=None):
        self.documents = []

    def index_documents(self, documents):
        self.documents.extend(documents)

    def retrieve(self, query: str, top_k: int = 5, domain=None):
        candidates = self.documents
        if domain:
            candidates = [doc for doc in candidates if doc.domain == domain]
        return [
            FakeRetrievalResult(doc, 0.88, "test evidence")
            for doc in candidates
            if query.lower() in doc.text.lower()
        ][:top_k]


def install_fake_cam_rag(monkeypatch, module_name: str = "fake_cam_rag") -> str:
    module = types.ModuleType(module_name)
    module.Document = FakeDocument
    module.DeterministicRetriever = FakeDeterministicRetriever
    monkeypatch.setitem(sys.modules, module_name, module)
    return module_name


def init_repo(path: Path, readme: str, extra_files: dict[str, str] | None = None) -> None:
    path.mkdir(parents=True)
    (path / "README.md").write_text(readme, encoding="utf-8")
    for rel, content in (extra_files or {}).items():
        file_path = path / rel
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


def test_scan_universe_clusters_risks_and_opportunities(tmp_path: Path) -> None:
    init_repo(
        tmp_path / "repowise-lite",
        "# RepoWise Lite\n\nMulti-repo codebase intelligence, MCP tools, dependency graph.",
        {"tests/test_app.py": "def test_ok():\n    assert True\n"},
    )
    init_repo(
        tmp_path / "agent-pidgin-lite",
        "# Agent Pidgin Lite\n\nPolicy receipts, audit trace, sandbox preflight guardrails.",
    )
    init_repo(
        tmp_path / "openkb-lite",
        "# OpenKB Lite\n\nKnowledge wiki, retrieval, graph, documents, memory.",
    )

    report = scan_universe(tmp_path)

    assert len(report.repos) == 3
    assert "repo_intelligence" in report.clusters
    assert "agent_safety" in report.clusters
    assert report.opportunities[0]["title"] in {
        "Repo Rescue Desk",
        "Guarded Autonomous Engineer",
        "Local Knowledge Appliance",
    }
    pidgin = next(repo for repo in report.repos if repo.name == "agent-pidgin-lite")
    assert "no-tests" in pidgin.risk_flags


def test_write_artifacts_creates_mindmap_and_graphrag_outputs(tmp_path: Path) -> None:
    init_repo(
        tmp_path / "markmap-kb",
        "# Markmap KB\n\nMindmap graph wiki logseq freeplane markmap knowledge retrieval.",
    )
    report = scan_universe(tmp_path)
    out_dir = tmp_path / "out"
    artifacts = write_artifacts(report, out_dir)

    assert Path(artifacts["dashboard_html"]).exists()
    markmap = Path(artifacts["markmap_md"]).read_text(encoding="utf-8")
    assert markmap.startswith("# CAM Repo Rescue Desk")
    assert "<map" in Path(artifacts["freeplane_mm"]).read_text(encoding="utf-8")
    assert "GraphRAG Context" in Path(artifacts["graphrag_md"]).read_text(encoding="utf-8")
    assert (out_dir / "logseq" / "pages" / "CAM Repo Rescue Desk.md").exists()


def test_cam_rag_bridge_adds_receipt_graph_and_artifacts(tmp_path: Path, monkeypatch) -> None:
    module_name = install_fake_cam_rag(monkeypatch)
    init_repo(
        tmp_path / "repo-map",
        "# Repo Map\n\nKnowledge graph repo triage retrieval.",
    )
    rag_docs = tmp_path / "rag-docs"
    rag_docs.mkdir()
    (rag_docs / "plan.md").write_text(
        "Repo Rescue Desk needs cited context for repo triage.",
        encoding="utf-8",
    )

    report = scan_universe(tmp_path)
    receipt = enrich_with_cam_rag(
        report,
        rag_docs,
        query="cited context",
        module_name=module_name,
    )
    artifacts = write_artifacts(report, tmp_path / "out")

    assert receipt["kind"] == "cam-rag-retrieval"
    assert receipt["receipt"]["result_count"] == 1
    assert "cam_rag_receipt_json" in artifacts
    assert any(node["type"] == "rag_receipt" for node in report.graph["nodes"])
    assert (tmp_path / "out" / "logseq" / "pages" / "CAM-RAG Evidence.md").exists()


def test_cli_generates_outputs(tmp_path: Path) -> None:
    init_repo(
        tmp_path / "medical-rag",
        "# Medical RAG\n\nClinical patient HIPAA knowledge retrieval graph.",
    )
    out_dir = tmp_path / "artifacts"
    exit_code = main(["--root", str(tmp_path), "--out-dir", str(out_dir)])

    assert exit_code == 0
    assert (out_dir / "repo_inventory.json").exists()
    assert (out_dir / "opportunity_rankings.md").exists()


def test_cli_generates_cam_rag_receipt_when_requested(tmp_path: Path, monkeypatch) -> None:
    module_name = install_fake_cam_rag(monkeypatch)
    init_repo(
        tmp_path / "knowledge-rag",
        "# Knowledge RAG\n\nKnowledge retrieval graph.",
    )
    rag_docs = tmp_path / "rag-docs"
    rag_docs.mkdir()
    (rag_docs / "context.md").write_text("agent safety cited context", encoding="utf-8")
    out_dir = tmp_path / "artifacts"

    exit_code = main([
        "--root",
        str(tmp_path),
        "--out-dir",
        str(out_dir),
        "--rag-folder",
        str(rag_docs),
        "--rag-query",
        "cited context",
        "--rag-module",
        module_name,
    ])

    assert exit_code == 0
    assert (out_dir / "cam_rag_receipt.json").exists()
