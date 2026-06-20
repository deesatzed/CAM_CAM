from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

from repo_rescue_desk.cli import main
from repo_rescue_desk.rescue import (
    answer_repo_question,
    enrich_with_cam_rag,
    find_reuse_matches,
    preflight_repo,
    scan_universe,
    write_artifacts,
)


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


def test_top_six_outputs_include_recommendations_report_reuse_and_ask_index(tmp_path: Path) -> None:
    init_repo(
        tmp_path / "fastapi-auth",
        "# FastAPI Auth\n\nFastAPI auth middleware token verification login session guard.",
        {
            "app/auth.py": "def verify_token(token):\n    return token == 'ok'\n",
            "tests/test_auth.py": "def test_auth():\n    assert True\n",
        },
    )
    init_repo(
        tmp_path / "retry-client",
        "# Retry Client\n\nHTTP client retry backoff timeout resilience API wrapper.",
        {"client.py": "def retry_request():\n    return 'retry with backoff'\n"},
    )
    init_repo(
        tmp_path / "retry-client-backup",
        "# Retry Client Backup\n\nHTTP client retry backoff timeout old copy.",
    )
    init_repo(
        tmp_path / "clinical-agent",
        "# Clinical Agent\n\nPatient triage HIPAA audit token.",
    )

    report = scan_universe(tmp_path)
    artifacts = write_artifacts(report, tmp_path / "out")

    categories = {item["category"] for item in report.next_actions}
    assert {"add-tests", "mine-reuse", "consolidate-duplicates"}.issubset(categories)
    assert report.reuse_matches
    assert any(match["query"] == "retry" for match in report.reuse_matches)
    assert any(match["query"] == "auth" for match in report.reuse_matches)
    assert "next_actions_json" in artifacts
    assert "reuse_matches_json" in artifacts
    assert "executive_report_md" in artifacts
    assert "ask_index_json" in artifacts
    executive = Path(artifacts["executive_report_md"]).read_text(encoding="utf-8")
    assert "# CAM_CAM Repo Universe Report" in executive
    assert "What to do next" in executive
    assert "Reusable code and patterns" in executive
    dashboard = Path(artifacts["dashboard_html"]).read_text(encoding="utf-8")
    assert "What to do next" in dashboard
    assert "Reusable code and patterns" in dashboard


def test_preflight_repo_blocks_dirty_and_warns_for_missing_tests(tmp_path: Path) -> None:
    init_repo(
        tmp_path / "safe-feature",
        "# Safe Feature\n\nSmall documented CLI.",
        {"tests/test_safe.py": "def test_safe():\n    assert True\n"},
    )
    subprocess.run(["git", "checkout", "-q", "-b", "feature/safe-agent"], cwd=tmp_path / "safe-feature", check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.com/safe-feature.git"],
        cwd=tmp_path / "safe-feature",
        check=True,
    )
    init_repo(
        tmp_path / "clean-no-tests",
        "# Clean No Tests\n\nSmall CLI with documentation.",
    )
    init_repo(
        tmp_path / "dirty-risky",
        "# Dirty Risky\n\nSecurity sandbox API key patient workflow.",
        {"tests/test_ok.py": "def test_ok():\n    assert True\n"},
    )
    (tmp_path / "dirty-risky" / "scratch.py").write_text("print('dirty')\n", encoding="utf-8")

    safe = preflight_repo(tmp_path / "safe-feature")
    clean = preflight_repo(tmp_path / "clean-no-tests")
    dirty = preflight_repo(tmp_path / "dirty-risky")

    assert safe["decision"] == "allow"
    assert clean["decision"] == "warn"
    assert any(check["id"] == "tests-present" and check["status"] == "warn" for check in clean["checks"])
    assert dirty["decision"] == "block"
    assert any(check["id"] == "git-clean" and check["status"] == "block" for check in dirty["checks"])
    assert dirty["remediation"]


def test_reuse_matches_include_provenance_and_confidence(tmp_path: Path) -> None:
    init_repo(
        tmp_path / "api-auth",
        "# API Auth\n\nFastAPI auth middleware bearer token validation.",
        {"src/auth.py": "class AuthMiddleware:\n    pass\n"},
    )
    init_repo(
        tmp_path / "resilient-client",
        "# Resilient Client\n\nRetry backoff timeout circuit breaker request wrapper.",
        {"client.py": "def retry_with_backoff():\n    pass\n"},
    )

    report = scan_universe(tmp_path)
    matches = find_reuse_matches(report.repos)

    assert any(match["query"] == "auth" and match["repo"] == "api-auth" for match in matches)
    assert any(match["query"] == "retry" and match["repo"] == "resilient-client" for match in matches)
    assert all(match["repo"] and match["path"] and match["confidence"] in {"high", "medium", "weak"} for match in matches)


def test_answer_repo_question_handles_common_intents(tmp_path: Path) -> None:
    init_repo(
        tmp_path / "fastapi-service",
        "# FastAPI Service\n\nFastAPI API service with auth token middleware.",
    )
    init_repo(
        tmp_path / "dirty-service",
        "# Dirty Service\n\nRetry backoff API client.",
    )
    (tmp_path / "dirty-service" / "scratch.py").write_text("print('dirty')\n", encoding="utf-8")
    report = scan_universe(tmp_path)

    assert "dirty-service" in answer_repo_question(report, "Which repos are dirty?")["answer"]
    assert "fastapi-service" in answer_repo_question(report, "Which repos have no tests?")["answer"]
    assert "fastapi-service" in answer_repo_question(report, "Which repos look like FastAPI apps?")["answer"]
    assert "What to do next" in answer_repo_question(report, "What should I do next?")["answer"]
    assert "retry" in answer_repo_question(report, "Where are reusable auth/retry/API patterns?")["answer"].lower()
    assert answer_repo_question(report, "What is the deployment password?")["confidence"] == "unknown"


def test_cli_preflight_writes_json(tmp_path: Path) -> None:
    init_repo(
        tmp_path / "dirty-target",
        "# Dirty Target\n\nSecurity workflow.",
    )
    (tmp_path / "dirty-target" / "scratch.py").write_text("print('dirty')\n", encoding="utf-8")
    json_out = tmp_path / "preflight.json"

    exit_code = main(["preflight", "--repo", str(tmp_path / "dirty-target"), "--json-out", str(json_out)])

    assert exit_code == 0
    payload = json_out.read_text(encoding="utf-8")
    assert '"decision": "block"' in payload
    assert '"git-clean"' in payload


def test_cli_ask_answers_from_saved_report(tmp_path: Path, capsys) -> None:
    init_repo(
        tmp_path / "fastapi-api",
        "# FastAPI API\n\nFastAPI auth endpoint.",
    )
    out_dir = tmp_path / "out"
    assert main(["--root", str(tmp_path), "--out-dir", str(out_dir)]) == 0

    exit_code = main([
        "ask",
        "--report",
        str(out_dir / "repo_inventory.json"),
        "--question",
        "Which repos look like FastAPI apps?",
    ])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "fastapi-api" in captured.out
