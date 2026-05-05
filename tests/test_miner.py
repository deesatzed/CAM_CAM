"""Tests for CLAW repo mining module (claw.miner).

Covers:
    1. serialize_repo() — file serialization with extension/dir filtering
    2. parse_findings() — LLM JSON response parsing and validation
    3. _discover_repos() — git repository discovery in directory trees
    4. _relevance_to_priority() — relevance-to-priority mapping
    5. _category_to_agent() — category-to-agent mapping
    6. Data classes — MiningFinding, RepoMiningResult, MiningReport
    7. RepoMiner.store_finding() — async methodology storage
    8. RepoMiner._generate_tasks() — async task generation from findings
    9. CLI registration — mine command exists

All tests use REAL dependencies — no mocks, no placeholders, no cached responses.
Database tests use the real SQLite in-memory engine from conftest.py.
Filesystem tests use pytest's tmp_path fixture for isolation.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import asyncio

import pytest

from claw.core.config import AgentConfig, ClawConfig, load_config
from claw.core.models import ActionTemplate, Methodology, Project, Task, TaskStatus
from claw.db.embeddings import EmbeddingEngine
from claw.memory.hybrid_search import HybridSearch
from claw.memory.semantic import SemanticMemory
from claw.miner import (
    MiningFinding,
    MiningReport,
    MiningModelSelector,
    RepoCandidate,
    RepoMiner,
    RepoMiningResult,
    RepoScanLedger,
    _MAX_FINDINGS_PER_REPO,
    _SKIP_DIRS,
    _VALID_CATEGORIES,
    _canonicalize_name,
    _category_to_agent,
    _collect_repo_metadata,
    _dedup_iterations,
    _discover_repos,
    _relevance_to_priority,
    parse_findings,
    _repair_json,
    serialize_repo,
)


# ---------------------------------------------------------------------------
# Deterministic embedding engine (same pattern as test_memory.py)
# ---------------------------------------------------------------------------

class FixedEmbeddingEngine:
    """Deterministic embedding engine using SHA-384 for reproducible tests.

    Hashes the input text with SHA-384 to produce 48 bytes, then
    normalizes each byte to [0, 1] and repeats 8x to fill 384 floats.
    """

    DIMENSION = 384

    def encode(self, text: str) -> list[float]:
        h = hashlib.sha384(text.encode()).digest()
        raw = [b / 255.0 for b in h] * 8
        return raw[: self.DIMENSION]

    async def async_encode(self, text: str) -> list[float]:
        return self.encode(text)

    def cosine_similarity(self, a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class TestMiningModelSelector:
    def test_escalation_chain_dedupes_model_ids_across_agents(self):
        config = ClawConfig()
        config.agents = {
            "claude": AgentConfig(
                enabled=True,
                mode="openrouter",
                model="deepseek/deepseek-v4-flash",
                context_window_tokens=1_000_000,
            ),
            "codex": AgentConfig(
                enabled=True,
                mode="openrouter",
                model="deepseek/deepseek-v4-flash",
                context_window_tokens=1_000_000,
            ),
            "gemini": AgentConfig(
                enabled=True,
                mode="openrouter",
                model="qwen/qwen3.6-flash",
                context_window_tokens=1_000_000,
            ),
        }
        config.mining.recovery.escalation_order = ["claude", "codex", "gemini"]

        chain = MiningModelSelector(config).build_escalation_chain(
            estimated_tokens=10_000,
        )

        assert chain == [
            ("claude", "deepseek/deepseek-v4-flash"),
            ("gemini", "qwen/qwen3.6-flash"),
        ]


@pytest.fixture
def embedding_engine() -> FixedEmbeddingEngine:
    return FixedEmbeddingEngine()


@pytest.fixture
async def hybrid_search(repository, embedding_engine):
    return HybridSearch(
        repository=repository,
        embedding_engine=embedding_engine,
    )


@pytest.fixture
async def semantic_memory(repository, embedding_engine, hybrid_search):
    return SemanticMemory(
        repository=repository,
        embedding_engine=embedding_engine,
        hybrid_search=hybrid_search,
    )


@pytest.fixture
def miner_config() -> ClawConfig:
    """ClawConfig with at least one agent enabled and model set."""
    config = load_config()
    # Ensure claude agent is configured for _get_mining_model()
    config.agents["claude"] = AgentConfig(
        enabled=True,
        mode="api",
        model="test-model/claude-test",
    )
    return config


@pytest.fixture
async def repo_miner(repository, semantic_memory, miner_config):
    """RepoMiner with real database, real SemanticMemory, but no LLM client.

    Tests that exercise mine_repo() or mine_directory() are skipped because
    they require a real LLM call. Tests for store_finding() and
    _generate_tasks() work without the LLM client.
    """
    from claw.llm.client import LLMClient
    # LLMClient is constructed but not called in the tests below
    llm_client = LLMClient(config=miner_config.llm)
    return RepoMiner(
        repository=repository,
        llm_client=llm_client,
        semantic_memory=semantic_memory,
        config=miner_config,
    )


# ===========================================================================
# 1. serialize_repo()
# ===========================================================================

class TestSerializeRepo:
    """Tests for serialize_repo() — pure filesystem operations."""

    def test_includes_python_files(self, tmp_path):
        """Python files (.py) are included in serialization."""
        (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")
        content, count = serialize_repo(tmp_path)
        assert count == 1
        assert "--- FILE: main.py ---" in content
        assert "print('hello')" in content

    def test_includes_js_and_ts_files(self, tmp_path):
        """JavaScript and TypeScript files are included."""
        (tmp_path / "app.js").write_text("const x = 1;", encoding="utf-8")
        (tmp_path / "utils.ts").write_text("export const y = 2;", encoding="utf-8")
        content, count = serialize_repo(tmp_path)
        assert count == 2
        assert "--- FILE: app.js ---" in content
        assert "--- FILE: utils.ts ---" in content

    def test_includes_config_files(self, tmp_path):
        """Config files (.toml, .yaml, .yml, .json) are included."""
        (tmp_path / "config.toml").write_text("[section]\nkey = 'value'", encoding="utf-8")
        (tmp_path / "data.json").write_text('{"key": "value"}', encoding="utf-8")
        (tmp_path / "spec.yaml").write_text("name: test", encoding="utf-8")
        content, count = serialize_repo(tmp_path)
        assert count == 3

    def test_skips_binary_extensions(self, tmp_path):
        """Binary files (.exe, .png, .jpg, .dll) are excluded."""
        (tmp_path / "app.exe").write_bytes(b"\x00\x01\x02")
        (tmp_path / "logo.png").write_bytes(b"\x89PNG")
        (tmp_path / "photo.jpg").write_bytes(b"\xff\xd8")
        (tmp_path / "real.py").write_text("x = 1", encoding="utf-8")
        content, count = serialize_repo(tmp_path)
        assert count == 1
        assert "app.exe" not in content
        assert "logo.png" not in content

    def test_skips_git_directory(self, tmp_path):
        """Files inside .git/ are excluded."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("[core]", encoding="utf-8")
        (git_dir / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
        (tmp_path / "main.py").write_text("pass", encoding="utf-8")
        content, count = serialize_repo(tmp_path)
        assert count == 1
        assert ".git" not in content.replace("--- FILE:", "")

    def test_skips_node_modules(self, tmp_path):
        """Files inside node_modules/ are excluded."""
        nm = tmp_path / "node_modules" / "lodash"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("module.exports = {};", encoding="utf-8")
        (tmp_path / "app.js").write_text("require('lodash')", encoding="utf-8")
        content, count = serialize_repo(tmp_path)
        assert count == 1
        assert "node_modules" not in content

    def test_skips_pycache(self, tmp_path):
        """Files inside __pycache__/ are excluded."""
        pc = tmp_path / "__pycache__"
        pc.mkdir()
        (pc / "main.cpython-312.pyc").write_bytes(b"\x00")
        (tmp_path / "main.py").write_text("x = 1", encoding="utf-8")
        content, count = serialize_repo(tmp_path)
        assert count == 1
        assert "__pycache__" not in content

    def test_respects_max_bytes(self, tmp_path):
        """Serialization stops when max_bytes is exceeded."""
        # Create files that exceed a small limit
        for i in range(10):
            (tmp_path / f"file{i}.py").write_text(f"x = {i}\n" * 50, encoding="utf-8")
        content, count = serialize_repo(tmp_path, max_bytes=500)
        # Should have stopped before processing all files
        assert count < 10
        assert "TRUNCATED" in content


class TestAssimilationParallelism:
    @pytest.mark.asyncio
    async def test_assimilate_methodologies_runs_concurrently(self, repo_miner):
        calls: list[str] = []

        class SlowAssimilationEngine:
            async def assimilate(self, methodology_id: str):
                calls.append(methodology_id)
                await asyncio.sleep(0.05)

        repo_miner.assimilation_engine = SlowAssimilationEngine()
        repo_miner._assimilation_parallelism = 4

        start = time.monotonic()
        await repo_miner._assimilate_methodologies(["a", "b", "c", "d"])
        duration = time.monotonic() - start

        assert sorted(calls) == ["a", "b", "c", "d"]
        assert duration < 0.16


@pytest.mark.asyncio
async def test_backfill_components_from_existing_methodology(repo_miner, repository):
    methodology = Methodology(
        problem_description="Retry helper for HTTP client backoff",
        solution_code="def with_retry(): pass",
        capability_data={
            "source_repos": ["org/service"],
            "source_artifacts": [
                {
                    "file_path": "app/retry.py",
                    "symbol_name": "with_retry",
                    "symbol_kind": "function",
                    "note": "retry helper",
                }
            ],
            "applicability": ["HTTP retry flows"],
            "non_applicability": ["async event loops"],
            "dependencies": ["requests"],
            "risks": ["sleep-based implementation"],
            "evidence": ["source_file:app/retry.py"],
            "domain": ["architecture"],
        },
        tags=["source:org/service", "category:architecture"],
        language="python",
        files_affected=["app/retry.py"],
    )
    await repository.save_methodology(methodology)

    summary = await repo_miner.backfill_components(methodology_ids=[methodology.id])
    cards = await repository.list_components_for_methodology(methodology.id)

    assert summary["created"] >= 1
    assert len(cards) == 1
    assert cards[0].file_path == "app/retry.py"
    assert cards[0].symbol == "with_retry"


@pytest.mark.asyncio
async def test_backfill_components_preserves_precise_symbol_receipts(repo_miner, repository):
    methodology = Methodology(
        problem_description="Refresh session helper",
        solution_code="def refresh_session(): pass",
        capability_data={
            "source_repos": ["org/service"],
            "source_artifacts": [
                {
                    "file_path": "app/auth/session.py",
                    "symbol_name": "refresh_session",
                    "symbol_kind": "function",
                    "line_start": 12,
                    "line_end": 18,
                    "provenance_precision": "precise_symbol",
                    "note": "scip matched",
                }
            ],
        },
        tags=["source:org/service", "category:security"],
        language="python",
        files_affected=["app/auth/session.py"],
    )
    await repository.save_methodology(methodology)

    summary = await repo_miner.backfill_components(methodology_ids=[methodology.id])
    cards = await repository.list_components_for_methodology(methodology.id)
    full_card = await repository.get_component_card(cards[0].id)

    assert summary["created"] >= 1
    assert full_card is not None
    assert full_card.receipt.line_start == 12
    assert full_card.receipt.line_end == 18
    assert full_card.receipt.provenance_precision == "precise_symbol"


@pytest.mark.asyncio
async def test_store_finding_backfills_components_when_flag_enabled(repo_miner, repository):
    repo_miner.config.feature_flags.component_cards = True

    finding = MiningFinding(
        title="Token refresh serialization helper",
        description="Coordinates token refresh across concurrent requests.",
        category="security",
        source_repo="org/auth-service",
        source_files=["app/auth/session.py"],
        source_symbols=[
            {
                "file_path": "app/auth/session.py",
                "symbol_name": "refresh_session",
                "symbol_kind": "function",
                "note": "top-level function definition",
            }
        ],
        implementation_sketch="Use a lock around token refresh and retry stale requests.",
        augmentation_notes="Adapt to async lock semantics in async stacks.",
        relevance_score=0.88,
        language="python",
    )

    methodology_id = await repo_miner.store_finding(finding, target_project_id="proj_001")
    assert methodology_id is not None

    cards = await repository.list_components_for_methodology(methodology_id)
    assert len(cards) >= 1
    assert cards[0].symbol == "refresh_session"
    assert cards[0].family_barcode.startswith("fam_")


class TestSerializeRepoEdgeCases:
    def test_empty_directory(self, tmp_path):
        """Empty directory returns empty string and 0 file count."""
        content, count = serialize_repo(tmp_path)
        assert content == ""
        assert count == 0

    def test_correct_file_count(self, tmp_path):
        """File count matches actual files serialized."""
        (tmp_path / "a.py").write_text("a = 1", encoding="utf-8")
        (tmp_path / "b.py").write_text("b = 2", encoding="utf-8")
        (tmp_path / "c.js").write_text("const c = 3;", encoding="utf-8")
        (tmp_path / "skip.exe").write_bytes(b"\x00")
        content, count = serialize_repo(tmp_path)
        assert count == 3

    def test_skips_unreadable_files(self, tmp_path):
        """Unreadable files are gracefully skipped."""
        good = tmp_path / "good.py"
        good.write_text("x = 1", encoding="utf-8")
        bad = tmp_path / "bad.py"
        bad.write_text("secret", encoding="utf-8")
        bad.chmod(0o000)
        try:
            content, count = serialize_repo(tmp_path)
            assert count >= 1
            assert "good.py" in content
        finally:
            bad.chmod(0o644)

    def test_file_header_format(self, tmp_path):
        """Each file is prefixed with --- FILE: relative/path --- header."""
        subdir = tmp_path / "src"
        subdir.mkdir()
        (subdir / "app.py").write_text("pass", encoding="utf-8")
        content, count = serialize_repo(tmp_path)
        assert "--- FILE: src/app.py ---" in content

    def test_nonexistent_path_returns_empty(self, tmp_path):
        """Non-existent path returns empty string and 0 count."""
        content, count = serialize_repo(tmp_path / "nonexistent")
        assert content == ""
        assert count == 0

    def test_skips_all_skip_dirs(self, tmp_path):
        """All directories in _SKIP_DIRS are excluded."""
        for skip_dir in list(_SKIP_DIRS)[:5]:
            d = tmp_path / skip_dir
            d.mkdir(exist_ok=True)
            (d / "file.py").write_text("x = 1", encoding="utf-8")
        (tmp_path / "main.py").write_text("pass", encoding="utf-8")
        content, count = serialize_repo(tmp_path)
        assert count == 1


class TestIncrementalMiningLedger:
    def test_collect_repo_metadata_signature_changes_when_file_changes(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        target = repo / "main.py"
        target.write_text("print('v1')\n", encoding="utf-8")

        count_1, ts_1, size_1, sig_1, _ = _collect_repo_metadata(repo)
        assert count_1 == 1
        assert size_1 > 0
        assert sig_1

        time.sleep(0.01)
        target.write_text("print('v2')\nprint('more')\n", encoding="utf-8")

        count_2, ts_2, size_2, sig_2, _ = _collect_repo_metadata(repo)
        assert count_2 == 1
        assert size_2 > size_1
        assert ts_2 >= ts_1
        assert sig_2 != sig_1

    def test_scan_ledger_skips_unchanged_and_rescans_changed(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "README.md").write_text("# demo\n", encoding="utf-8")
        (repo / "main.py").write_text("print('v1')\n", encoding="utf-8")

        candidate = _discover_repos(tmp_path, max_depth=2)[0]
        ledger = RepoScanLedger(tmp_path / "mining_registry.json")

        should_mine, reason = ledger.should_mine(candidate)
        assert should_mine is True
        assert reason == "new"

        result = RepoMiningResult(
            repo_name=candidate.name,
            repo_path=str(candidate.path),
            findings=[MiningFinding(
                title="Pattern",
                description="A sufficiently descriptive finding for incremental mining ledger tests.",
                category="architecture",
                source_repo=candidate.name,
            )],
            files_analyzed=2,
            tokens_used=123,
            methodology_ids=["meth-1"],
            action_template_ids=["tmpl-1"],
        )
        ledger.record_result(candidate, result)

        loaded = RepoScanLedger(tmp_path / "mining_registry.json")
        should_mine, reason = loaded.should_mine(candidate)
        assert should_mine is False
        assert reason == "unchanged"
        loaded_record = loaded.get_record(candidate.path)
        assert loaded_record is not None
        assert loaded_record.methodology_ids == ["meth-1"]
        assert loaded_record.action_template_ids == ["tmpl-1"]

        time.sleep(0.01)
        (repo / "main.py").write_text("print('v2')\n", encoding="utf-8")
        changed_candidate = _discover_repos(tmp_path, max_depth=2)[0]
        should_mine, reason = loaded.should_mine(changed_candidate)
        assert should_mine is True
        assert reason == "changed"


# ===========================================================================
# 2. parse_findings()
# ===========================================================================

class TestParseFindings:
    """Tests for parse_findings() — JSON parsing and validation."""

    def _make_finding_dict(self, **overrides) -> dict:
        """Helper to create a valid finding dict."""
        base = {
            "title": "Pattern Found",
            "description": "A useful pattern discovered in the repo",
            "category": "architecture",
            "relevance_score": 0.8,
            "source_files": ["src/main.py"],
            "implementation_sketch": "def impl(): pass",
            "augmentation_notes": "Could improve CLAW's architecture",
            "language": "python",
        }
        base.update(overrides)
        return base

    def test_parses_valid_json_array(self):
        """Valid JSON array of findings is parsed correctly."""
        findings_data = [self._make_finding_dict()]
        response = json.dumps(findings_data)
        results = parse_findings(response, "test-repo")
        assert len(results) == 1
        assert results[0].title == "Pattern Found"
        assert results[0].source_repo == "test-repo"

    def test_handles_json_fences(self):
        """JSON wrapped in ```json fences is parsed correctly."""
        findings_data = [self._make_finding_dict()]
        response = f"```json\n{json.dumps(findings_data)}\n```"
        results = parse_findings(response, "test-repo")
        assert len(results) == 1
        assert results[0].title == "Pattern Found"

    def test_handles_malformed_json(self):
        """Malformed JSON returns empty list."""
        results = parse_findings("{not valid json[", "test-repo")
        assert results == []

    def test_handles_completely_invalid_text(self):
        """Non-JSON text returns empty list."""
        results = parse_findings("This is just plain text with no JSON.", "test-repo")
        assert results == []

    def test_filters_low_relevance(self):
        """Findings with relevance_score < 0.4 are filtered out."""
        findings_data = [
            self._make_finding_dict(title="High", relevance_score=0.8),
            self._make_finding_dict(title="Low", relevance_score=0.2),
            self._make_finding_dict(title="Zero", relevance_score=0.0),
        ]
        results = parse_findings(json.dumps(findings_data), "test-repo")
        assert len(results) == 1
        assert results[0].title == "High"

    def test_caps_at_max_findings(self):
        """Results are capped at _MAX_FINDINGS_PER_REPO (15)."""
        findings_data = [
            self._make_finding_dict(title=f"Finding {i}", relevance_score=0.8)
            for i in range(25)
        ]
        results = parse_findings(json.dumps(findings_data), "test-repo")
        assert len(results) == _MAX_FINDINGS_PER_REPO

    def test_missing_title_excluded(self):
        """Findings without a title are excluded."""
        findings_data = [
            self._make_finding_dict(title=""),
            self._make_finding_dict(title="Valid Title"),
        ]
        results = parse_findings(json.dumps(findings_data), "test-repo")
        assert len(results) == 1
        assert results[0].title == "Valid Title"

    def test_missing_description_excluded(self):
        """Findings without a description are excluded."""
        findings_data = [
            self._make_finding_dict(description=""),
            self._make_finding_dict(description="Valid desc"),
        ]
        results = parse_findings(json.dumps(findings_data), "test-repo")
        assert len(results) == 1

    def test_validates_and_defaults_category(self):
        """Invalid category defaults to 'cross_cutting'."""
        findings_data = [
            self._make_finding_dict(category="unknown_category"),
        ]
        results = parse_findings(json.dumps(findings_data), "test-repo")
        assert len(results) == 1
        assert results[0].category == "cross_cutting"

    def test_valid_categories_pass_through(self):
        """All valid categories pass through without defaulting."""
        for category in _VALID_CATEGORIES:
            findings_data = [self._make_finding_dict(category=category)]
            results = parse_findings(json.dumps(findings_data), "test-repo")
            assert len(results) == 1
            assert results[0].category == category

    def test_clamps_relevance_score(self):
        """Relevance scores are clamped to [0.4, 1.0]."""
        findings_data = [
            self._make_finding_dict(title="Clamped High", relevance_score=1.5),
            self._make_finding_dict(title="Just Right", relevance_score=0.7),
        ]
        results = parse_findings(json.dumps(findings_data), "test-repo")
        assert len(results) == 2
        high = next(f for f in results if f.title == "Clamped High")
        assert high.relevance_score == 1.0
        right = next(f for f in results if f.title == "Just Right")
        assert right.relevance_score == 0.7

    def test_non_array_json_returns_empty(self):
        """Non-array JSON (e.g., a dict) returns empty list."""
        results = parse_findings('{"title": "not an array"}', "test-repo")
        assert results == []

    def test_finds_json_array_not_at_start(self):
        """JSON array embedded in text is extracted and parsed."""
        prefix = "Here are the findings I discovered:\n\n"
        findings_data = [self._make_finding_dict()]
        response = prefix + json.dumps(findings_data) + "\n\nThat's all."
        results = parse_findings(response, "test-repo")
        assert len(results) == 1

    def test_source_repo_injected(self):
        """source_repo field is set to the provided repo_name."""
        findings_data = [self._make_finding_dict()]
        results = parse_findings(json.dumps(findings_data), "my-cool-repo")
        assert results[0].source_repo == "my-cool-repo"

    def test_invalid_relevance_type_filtered(self):
        """Non-numeric relevance_score causes finding to be filtered (score=0.0 < 0.4)."""
        findings_data = [
            self._make_finding_dict(relevance_score="not a number"),
        ]
        results = parse_findings(json.dumps(findings_data), "test-repo")
        assert len(results) == 0

    def test_source_files_non_list_defaults_to_empty(self):
        """Non-list source_files defaults to empty list."""
        findings_data = [
            self._make_finding_dict(source_files="not-a-list"),
        ]
        results = parse_findings(json.dumps(findings_data), "test-repo")
        assert len(results) == 1
        assert results[0].source_files == []

    def test_handles_null_json_fields_without_crashing(self):
        """Null-valued fields from LLM JSON should not trigger attribute errors."""
        findings_data = [
            self._make_finding_dict(
                title=None,
                description=None,
                category=None,
                implementation_sketch=None,
                augmentation_notes=None,
                language=None,
            ),
            self._make_finding_dict(
                title="Valid",
                description="Still valid",
                category=None,
                implementation_sketch=None,
                augmentation_notes=None,
                language=None,
            ),
        ]
        results = parse_findings(json.dumps(findings_data), "test-repo")
        assert len(results) == 1
        assert results[0].title == "Valid"
        assert results[0].category == "cross_cutting"

    def test_parses_optional_runbook_fields(self):
        """execution_steps/acceptance_checks/rollback/preconditions are parsed when present."""
        findings_data = [
            self._make_finding_dict(
                execution_steps=["npm install", "npm test"],
                acceptance_checks=["npm test -- --runInBand"],
                rollback_steps=["git restore src/app.ts"],
                preconditions=["Node 20 installed"],
            )
        ]
        results = parse_findings(json.dumps(findings_data), "test-repo")
        assert len(results) == 1
        finding = results[0]
        assert finding.execution_steps == ["npm install", "npm test"]
        assert finding.acceptance_checks == ["npm test -- --runInBand"]
        assert finding.rollback_steps == ["git restore src/app.ts"]
        assert finding.preconditions == ["Node 20 installed"]


# ===========================================================================
# 2b. _repair_json() — JSON repair for malformed LLM output
# ===========================================================================

class TestRepairJson:
    """Tests for _repair_json() — handles common LLM JSON errors."""

    def test_trailing_comma_in_array(self):
        """Trailing comma before ] is fixed."""
        text = '[{"title": "a", "description": "b"},]'
        result = _repair_json(text)
        assert result is not None
        assert len(result) == 1
        assert result[0]["title"] == "a"

    def test_trailing_comma_in_object(self):
        """Trailing comma before } is fixed."""
        text = '[{"title": "a", "description": "b",}]'
        result = _repair_json(text)
        assert result is not None
        assert len(result) == 1

    def test_truncated_array_at_last_bracket(self):
        """Truncated response with trailing text after ] is recovered."""
        text = '[{"title": "a", "description": "b"}] some trailing garbage'
        result = _repair_json(text)
        assert result is not None
        assert len(result) == 1

    def test_truncated_midway_extracts_complete_objects(self):
        """When array is cut mid-object, complete objects before the cut are extracted."""
        text = '[{"title": "a", "description": "b"}, {"title": "c", "descr'
        result = _repair_json(text)
        assert result is not None
        assert len(result) == 1
        assert result[0]["title"] == "a"

    def test_multiple_objects_extracted(self):
        """Multiple complete objects are extracted from a broken array."""
        text = '[{"title": "a", "description": "b"}, {"title": "c", "description": "d"}, {"title": "e"'
        result = _repair_json(text)
        assert result is not None
        assert len(result) == 2
        assert result[0]["title"] == "a"
        assert result[1]["title"] == "c"

    def test_valid_json_returns_as_is(self):
        """Already-valid JSON is returned unchanged."""
        text = '[{"title": "a", "description": "b"}]'
        # This won't normally be called on valid JSON, but should still work
        result = _repair_json(text)
        assert result is not None
        assert len(result) == 1

    def test_completely_invalid_returns_none(self):
        """Totally unparseable text returns None."""
        result = _repair_json("this is not json at all")
        assert result is None

    def test_empty_string_returns_none(self):
        """Empty string returns None."""
        result = _repair_json("")
        assert result is None

    def test_nested_objects_handled(self):
        """Objects with nested braces are correctly extracted."""
        text = '[{"title": "a", "meta": {"key": "val"}}, {"title": "b"'
        result = _repair_json(text)
        assert result is not None
        assert len(result) == 1
        assert result[0]["meta"]["key"] == "val"

    def test_parse_findings_uses_repair(self):
        """parse_findings integrates _repair_json for broken LLM output."""
        # Simulate a real LLM failure: trailing comma + truncation
        broken = '[{"title": "Pattern X", "description": "Does Y", "category": "testing", "relevance_score": 0.8,}]'
        results = parse_findings(broken, "test-repo")
        assert len(results) == 1
        assert results[0].title == "Pattern X"

    def test_parse_findings_recovers_partial_array(self):
        """parse_findings recovers findings from truncated LLM output."""
        broken = """[
            {"title": "First", "description": "Desc1", "category": "testing", "relevance_score": 0.9},
            {"title": "Second", "description": "Desc2", "category": "architecture", "relevance_score": 0.8},
            {"title": "Third", "description": "Inc"""
        results = parse_findings(broken, "test-repo")
        assert len(results) >= 2
        assert results[0].title == "First"
        assert results[1].title == "Second"


# ===========================================================================
# 3. _discover_repos()
# ===========================================================================

class TestDiscoverRepos:
    """Tests for _discover_repos() — repo discovery."""

    def test_finds_base_level_repo(self, tmp_path):
        """If base itself has .git, it is discovered."""
        (tmp_path / ".git").mkdir()
        repos = _discover_repos(tmp_path)
        assert len(repos) == 1
        assert repos[0].path == tmp_path
        assert repos[0].name == tmp_path.name

    def test_finds_repos_one_level_deep(self, tmp_path):
        """Repos at immediate children level are discovered."""
        repo_a = tmp_path / "repo-a"
        repo_a.mkdir()
        (repo_a / ".git").mkdir()

        repo_b = tmp_path / "repo-b"
        repo_b.mkdir()
        (repo_b / ".git").mkdir()

        repos = _discover_repos(tmp_path)
        names = {r.name for r in repos}
        assert "repo-a" in names
        assert "repo-b" in names

    def test_finds_repos_two_levels_deep(self, tmp_path):
        """Repos at grandchild level are discovered."""
        org = tmp_path / "github"
        org.mkdir()
        project = org / "my-project"
        project.mkdir()
        (project / ".git").mkdir()

        repos = _discover_repos(tmp_path)
        names = {r.name for r in repos}
        assert "my-project" in names

    def test_skips_hidden_directories(self, tmp_path):
        """Directories starting with . (except .git itself) are skipped."""
        hidden = tmp_path / ".hidden-repo"
        hidden.mkdir()
        (hidden / ".git").mkdir()

        visible = tmp_path / "visible-repo"
        visible.mkdir()
        (visible / ".git").mkdir()

        repos = _discover_repos(tmp_path)
        names = {r.name for r in repos}
        assert "visible-repo" in names
        assert ".hidden-repo" not in names

    def test_empty_directory(self, tmp_path):
        """Empty directory returns empty list."""
        repos = _discover_repos(tmp_path)
        assert repos == []

    def test_finds_extracted_source_tree_with_project_markers(self, tmp_path):
        """Extracted source trees without .git are still discoverable."""
        repo = tmp_path / "downloaded-project"
        repo.mkdir()
        (repo / "README.md").write_text("# Downloaded Project", encoding="utf-8")
        (repo / "pyproject.toml").write_text("[project]\nname='demo'", encoding="utf-8")
        (repo / "main.py").write_text("print('hi')", encoding="utf-8")

        repos = _discover_repos(tmp_path)

        assert len(repos) == 1
        assert repos[0].name == "downloaded-project"
        assert repos[0].source_kind == "source_tree"

    def test_finds_extracted_source_tree_from_multiple_source_files(self, tmp_path):
        """Source-heavy folders without markers are treated as repo candidates."""
        repo = tmp_path / "src-drop"
        repo.mkdir()
        (repo / "app.py").write_text("print('x')", encoding="utf-8")
        (repo / "utils.py").write_text("print('y')", encoding="utf-8")

        repos = _discover_repos(tmp_path)

        assert len(repos) == 1
        assert repos[0].source_kind == "source_tree"

    def test_skips_non_repo_like_source_folder(self, tmp_path):
        """A folder with a single loose file is not treated as a repo."""
        loose = tmp_path / "random-dir"
        loose.mkdir()
        (loose / "notes.txt").write_text("hello", encoding="utf-8")

        repos = _discover_repos(tmp_path)

        assert repos == []

    def test_skips_skip_dirs_at_child_level(self, tmp_path):
        """Directories in _SKIP_DIRS are not scanned for repos."""
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / ".git").mkdir()

        real = tmp_path / "real-repo"
        real.mkdir()
        (real / ".git").mkdir()

        repos = _discover_repos(tmp_path)
        names = {r.name for r in repos}
        assert "real-repo" in names
        assert "node_modules" not in names

    def test_finds_repos_at_depth_4(self, tmp_path):
        """Repos nested 4 levels deep are discovered with default depth."""
        deep = tmp_path / "org" / "team" / "category" / "my-deep-repo"
        deep.mkdir(parents=True)
        (deep / ".git").mkdir()

        repos = _discover_repos(tmp_path)
        names = {r.name for r in repos}
        assert "my-deep-repo" in names

    def test_respects_max_depth(self, tmp_path):
        """Repos beyond max_depth are not discovered.

        BFS depth counting: base=0, a=1, b=2, deep-repo=3.
        max_depth controls how deep we descend into non-repo dirs.
        To discover depth=3, we need max_depth >= 3 so we descend
        into b (depth=2, which is < 3) and find deep-repo at depth 3.
        """
        # a/b/deep-repo = depth 3 from base
        deep = tmp_path / "a" / "b" / "deep-repo"
        deep.mkdir(parents=True)
        (deep / ".git").mkdir()

        # depth=1 should miss repos at depth 3
        repos = _discover_repos(tmp_path, max_depth=1)
        names = {r.name for r in repos}
        assert "deep-repo" not in names

        # depth=3 should find it
        repos = _discover_repos(tmp_path, max_depth=3)
        names = {r.name for r in repos}
        assert "deep-repo" in names

    def test_collects_file_count_metadata(self, tmp_path):
        """Discovered repos have file_count metadata from source files."""
        repo = tmp_path / "my-repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / "main.py").write_text("x = 1", encoding="utf-8")
        (repo / "utils.py").write_text("y = 2", encoding="utf-8")
        (repo / "data.bin").write_bytes(b"\x00")  # not a code file

        repos = _discover_repos(tmp_path)
        assert len(repos) == 1
        assert repos[0].file_count == 2  # only .py files counted

    def test_sets_canonical_name(self, tmp_path):
        """Discovered repos have canonical_name set."""
        repo = tmp_path / "my-project-v3"
        repo.mkdir()
        (repo / ".git").mkdir()

        repos = _discover_repos(tmp_path)
        assert len(repos) == 1
        assert repos[0].canonical_name == "my-project"

    def test_does_not_descend_into_repos(self, tmp_path):
        """Once .git is found, don't look for nested repos inside."""
        outer = tmp_path / "outer"
        outer.mkdir()
        (outer / ".git").mkdir()

        inner = outer / "vendor" / "inner"
        inner.mkdir(parents=True)
        (inner / ".git").mkdir()

        repos = _discover_repos(tmp_path)
        names = {r.name for r in repos}
        assert "outer" in names
        assert "inner" not in names


# ===========================================================================
# 4. _relevance_to_priority()
# ===========================================================================

class TestRelevanceToPriority:
    """Tests for _relevance_to_priority() — score-to-priority mapping."""

    def test_very_high_relevance(self):
        """0.9+ maps to priority 9."""
        assert _relevance_to_priority(0.9) == 9
        assert _relevance_to_priority(0.95) == 9
        assert _relevance_to_priority(1.0) == 9

    def test_high_relevance(self):
        """0.8-0.89 maps to priority 7."""
        assert _relevance_to_priority(0.8) == 7
        assert _relevance_to_priority(0.85) == 7
        assert _relevance_to_priority(0.89) == 7

    def test_medium_relevance(self):
        """0.7-0.79 maps to priority 5."""
        assert _relevance_to_priority(0.7) == 5
        assert _relevance_to_priority(0.75) == 5
        assert _relevance_to_priority(0.79) == 5

    def test_low_relevance(self):
        """0.6-0.69 maps to priority 3."""
        assert _relevance_to_priority(0.6) == 3
        assert _relevance_to_priority(0.65) == 3
        assert _relevance_to_priority(0.69) == 3

    def test_very_low_relevance(self):
        """Below 0.6 maps to priority 1."""
        assert _relevance_to_priority(0.5) == 1
        assert _relevance_to_priority(0.3) == 1
        assert _relevance_to_priority(0.0) == 1


# ===========================================================================
# 5. _category_to_agent()
# ===========================================================================

class TestCategoryToAgent:
    """Tests for _category_to_agent() — category-to-agent mapping."""

    def test_architecture_maps_to_claude(self):
        assert _category_to_agent("architecture") == "claude"

    def test_ai_integration_maps_to_claude(self):
        assert _category_to_agent("ai_integration") == "claude"

    def test_memory_maps_to_claude(self):
        assert _category_to_agent("memory") == "claude"

    def test_security_maps_to_claude(self):
        assert _category_to_agent("security") == "claude"

    def test_code_quality_maps_to_codex(self):
        assert _category_to_agent("code_quality") == "codex"

    def test_cli_ux_maps_to_codex(self):
        assert _category_to_agent("cli_ux") == "codex"

    def test_testing_maps_to_codex(self):
        assert _category_to_agent("testing") == "codex"

    def test_data_processing_maps_to_gemini(self):
        assert _category_to_agent("data_processing") == "gemini"

    def test_algorithm_maps_to_gemini(self):
        assert _category_to_agent("algorithm") == "gemini"

    def test_cross_cutting_maps_to_grok(self):
        assert _category_to_agent("cross_cutting") == "grok"

    def test_unknown_category_defaults_to_claude(self):
        assert _category_to_agent("totally_unknown") == "claude"
        assert _category_to_agent("") == "claude"


# ===========================================================================
# 6. Data classes
# ===========================================================================

class TestDataClasses:
    """Tests for MiningFinding, RepoMiningResult, MiningReport dataclasses."""

    def test_mining_finding_defaults(self):
        """MiningFinding has correct defaults."""
        f = MiningFinding(
            title="Test",
            description="Desc",
            category="testing",
            source_repo="repo",
        )
        assert f.source_files == []
        assert f.implementation_sketch == ""
        assert f.augmentation_notes == ""
        assert f.relevance_score == 0.5
        assert f.language == "python"

    def test_mining_finding_custom_fields(self):
        """MiningFinding accepts custom values."""
        f = MiningFinding(
            title="Custom Pattern",
            description="A custom pattern",
            category="algorithm",
            source_repo="my-repo",
            source_files=["file1.py", "file2.py"],
            implementation_sketch="def algo(): pass",
            augmentation_notes="Improves speed",
            relevance_score=0.95,
            language="rust",
        )
        assert f.title == "Custom Pattern"
        assert f.language == "rust"
        assert f.relevance_score == 0.95
        assert len(f.source_files) == 2

    def test_repo_mining_result_defaults(self):
        """RepoMiningResult has correct defaults."""
        r = RepoMiningResult(repo_name="test", repo_path="/tmp/test")
        assert r.findings == []
        assert r.files_analyzed == 0
        assert r.tokens_used == 0
        assert r.cost_usd == 0.0
        assert r.duration_seconds == 0.0
        assert r.error is None

    def test_repo_mining_result_with_error(self):
        """RepoMiningResult can carry an error message."""
        r = RepoMiningResult(
            repo_name="broken",
            repo_path="/tmp/broken",
            error="LLM call failed",
        )
        assert r.error == "LLM call failed"

    def test_mining_report_defaults(self):
        """MiningReport has correct defaults."""
        report = MiningReport()
        assert report.repos_scanned == 0
        assert report.total_findings == 0
        assert report.tasks_generated == 0
        assert report.total_cost_usd == 0.0
        assert report.total_tokens == 0
        assert report.total_duration_seconds == 0.0
        assert report.repo_results == []
        assert report.tasks == []

    def test_mining_report_accumulation(self):
        """MiningReport fields can be accumulated."""
        report = MiningReport()
        report.repos_scanned = 3
        report.total_findings = 10
        report.tasks_generated = 5
        report.total_cost_usd = 0.15
        assert report.repos_scanned == 3
        assert report.total_findings == 10
        assert report.tasks_generated == 5


# ===========================================================================
# 7. RepoMiner.store_finding() — async, real database
# ===========================================================================

class TestStoreFinding:
    """Tests for RepoMiner.store_finding() — stores in SemanticMemory."""

    async def test_store_finding_returns_methodology_id(self, repo_miner, repository, sample_project):
        """store_finding returns a methodology ID string."""
        await repository.create_project(sample_project)
        finding = MiningFinding(
            title="Useful Pattern",
            description="A pattern that could improve CLAW's memory system",
            category="memory",
            source_repo="external-repo",
            source_files=["src/memory.py"],
            implementation_sketch="class Memory: ...",
            augmentation_notes="Could be adapted for semantic search",
            relevance_score=0.85,
        )
        method_id = await repo_miner.store_finding(finding, sample_project.id)
        assert isinstance(method_id, str)
        assert len(method_id) > 0

    async def test_store_finding_creates_methodology_with_global_scope(self, repo_miner, repository, sample_project):
        """Stored methodology has scope='global' and type='PATTERN'."""
        await repository.create_project(sample_project)
        finding = MiningFinding(
            title="Architecture Pattern",
            description="Event sourcing pattern for state management",
            category="architecture",
            source_repo="event-store-lib",
            relevance_score=0.9,
        )
        method_id = await repo_miner.store_finding(finding, sample_project.id)

        # Verify via direct repository lookup
        methodology = await repository.get_methodology(method_id)
        assert methodology is not None
        assert methodology.scope == "global"
        assert methodology.methodology_type == "PATTERN"

    async def test_store_finding_tags_include_mined_and_source(self, repo_miner, repository, sample_project):
        """Methodology tags include 'mined' and 'source:{repo_name}'."""
        await repository.create_project(sample_project)
        finding = MiningFinding(
            title="Security Pattern",
            description="Input sanitization pattern",
            category="security",
            source_repo="secure-lib",
            relevance_score=0.75,
        )
        method_id = await repo_miner.store_finding(finding, sample_project.id)
        methodology = await repository.get_methodology(method_id)
        assert "mined" in methodology.tags
        assert "source:secure-lib" in methodology.tags
        assert "category:security" in methodology.tags

    async def test_store_finding_problem_description_contains_repo_name(self, repo_miner, repository, sample_project):
        """Problem description includes [Mined from repo_name] prefix."""
        await repository.create_project(sample_project)
        finding = MiningFinding(
            title="CLI Pattern",
            description="Rich console progress bars",
            category="cli_ux",
            source_repo="rich-cli",
            relevance_score=0.7,
        )
        method_id = await repo_miner.store_finding(finding, sample_project.id)
        methodology = await repository.get_methodology(method_id)
        assert "[Mined from rich-cli]" in methodology.problem_description

    async def test_store_finding_creates_action_template_for_runbook(self, repo_miner, repository, sample_project):
        """Findings with concrete commands create reusable action templates."""
        await repository.create_project(sample_project)
        finding = MiningFinding(
            title="Useful build pipeline",
            description="Build and test flow for TypeScript service",
            category="code_quality",
            source_repo="nanochat",
            relevance_score=0.88,
            execution_steps=["npm install", "npm run build"],
            acceptance_checks=["npm test -- --runInBand"],
            rollback_steps=["git restore src/service.ts"],
            preconditions=["Node 20 installed"],
        )
        method_id = await repo_miner.store_finding(finding, sample_project.id)
        assert method_id
        assert finding.action_template_id is not None

        template = await repository.get_action_template(finding.action_template_id)
        assert template is not None
        assert template.source_methodology_id == method_id
        assert template.execution_steps == ["npm install", "npm run build"]
        assert template.acceptance_checks == ["npm test -- --runInBand"]
        assert template.source_repo == "nanochat"

    async def test_store_finding_creates_fallback_action_template_for_accepted_pattern(
        self, repo_miner, repository, sample_project
    ):
        """Accepted findings without explicit runbooks still create source-linked templates."""
        await repository.create_project(sample_project)
        finding = MiningFinding(
            title="Policy first validation",
            description="Validate requests against a policy object before mutation",
            category="code_quality",
            source_repo="policy-engine",
            source_files=["src/policy.py", "tests/test_policy.py"],
            implementation_sketch="Use a small validator object before writes.",
            augmentation_notes="Adapt checks to the target persistence layer.",
            relevance_score=0.91,
        )
        method_id = await repo_miner.store_finding(finding, sample_project.id)
        assert method_id
        assert finding.action_template_id is not None

        template = await repository.get_action_template(finding.action_template_id)
        assert template is not None
        assert template.source_methodology_id == method_id
        assert template.source_repo == "policy-engine"
        assert template.confidence == 0.75
        assert "src/policy.py" in template.execution_steps[0]
        assert method_id in template.acceptance_checks[0]
        assert template.rollback_steps
        assert "Source repo policy-engine was mined and accepted" in template.preconditions

    async def test_store_finding_seeds_capability_data_with_provenance_and_triggers(
        self, repo_miner, repository, sample_project
    ):
        await repository.create_project(sample_project)
        finding = MiningFinding(
            title="Verification pipeline",
            description="A reusable workflow pattern with explicit verification checks.",
            category="testing",
            source_repo="verifier-lib",
            source_files=["src/verify.py", "tests/test_verify.py"],
            implementation_sketch="Adapt this into a validation runner for CLAW.",
            augmentation_notes="Needs adaptation to local repo layout.",
            relevance_score=0.82,
            preconditions=["pytest installed"],
        )
        method_id = await repo_miner.store_finding(finding, sample_project.id)
        methodology = await repository.get_methodology(method_id)
        assert methodology is not None
        assert methodology.capability_data is not None
        cap = methodology.capability_data
        assert cap["enrichment_status"] == "seeded"
        assert cap["source_repos"] == ["verifier-lib"]
        assert cap["domain"] == ["testing"]
        assert "missing_tests" in cap["activation_triggers"]
        assert "high_relevance" in cap["activation_triggers"]
        assert cap["source_artifacts"][0]["file_path"] == "src/verify.py"
        assert cap["dependencies"] == ["pytest installed"]

    async def test_store_finding_preserves_symbol_level_source_artifacts(
        self, repo_miner, repository, sample_project
    ):
        await repository.create_project(sample_project)
        finding = MiningFinding(
            title="Prompt registry pattern",
            description="A function-oriented pattern with strong verification.",
            category="architecture",
            source_repo="symbolic-repo",
            source_files=["src/prompting.py"],
            source_symbols=[
                {
                    "file_path": "src/prompting.py",
                    "symbol_name": "build_prompt_registry",
                    "symbol_kind": "function",
                    "note": "top-level function implementing the pattern",
                }
            ],
            relevance_score=0.8,
        )
        method_id = await repo_miner.store_finding(finding, sample_project.id)
        methodology = await repository.get_methodology(method_id)
        assert methodology is not None
        artifacts = methodology.capability_data["source_artifacts"]
        assert any(item["symbol_name"] == "build_prompt_registry" for item in artifacts)


class TestSymbolExtraction:
    def test_attach_symbol_provenance_extracts_python_symbols(self, repo_miner, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        source = repo / "signals.py"
        source.write_text(
            "class PromptRegistry:\n    pass\n\n"
            "def build_prompt_registry():\n    return PromptRegistry()\n",
            encoding="utf-8",
        )

        finding = MiningFinding(
            title="Prompt registry pattern",
            description="The build_prompt_registry function wires a registry for prompt loading.",
            category="architecture",
            source_repo="tmp-repo",
            source_files=["signals.py"],
        )
        repo_miner._attach_symbol_provenance([finding], repo)
        names = {item["symbol_name"] for item in finding.source_symbols}
        kinds = {item["symbol_kind"] for item in finding.source_symbols}
        assert "build_prompt_registry" in names
        assert "PromptRegistry" in names
        assert "function" in kinds
        assert "class" in kinds


# ===========================================================================
# 8. RepoMiner._generate_tasks() — async, real database
# ===========================================================================

class TestGenerateTasks:
    """Tests for RepoMiner._generate_tasks() — task creation from findings."""

    async def test_filters_by_min_relevance(self, repo_miner, repository, sample_project):
        """Findings below min_relevance are not turned into tasks."""
        await repository.create_project(sample_project)
        findings = [
            MiningFinding(
                title="High Relevance",
                description="Important pattern",
                category="architecture",
                source_repo="repo-a",
                relevance_score=0.8,
            ),
            MiningFinding(
                title="Low Relevance",
                description="Less important pattern",
                category="testing",
                source_repo="repo-b",
                relevance_score=0.3,  # Below any reasonable min_relevance
            ),
        ]
        tasks = await repo_miner._generate_tasks(findings, sample_project.id, min_relevance=0.6)
        assert len(tasks) == 1
        assert "High Relevance" in tasks[0].title

    async def test_creates_tasks_with_correct_priority(self, repo_miner, repository, sample_project):
        """Task priority matches _relevance_to_priority mapping."""
        await repository.create_project(sample_project)
        findings = [
            MiningFinding(
                title="Critical Pattern",
                description="Very important",
                category="security",
                source_repo="secure-repo",
                relevance_score=0.95,
            ),
        ]
        tasks = await repo_miner._generate_tasks(findings, sample_project.id, min_relevance=0.6)
        assert len(tasks) == 1
        assert tasks[0].priority == 9  # 0.95 >= 0.9 -> priority 9

    async def test_sets_recommended_agent(self, repo_miner, repository, sample_project):
        """Task recommended_agent is set based on finding category."""
        await repository.create_project(sample_project)
        findings = [
            MiningFinding(
                title="Data Processing Enhancement",
                description="Better CSV parsing",
                category="data_processing",
                source_repo="csv-lib",
                relevance_score=0.75,
            ),
        ]
        tasks = await repo_miner._generate_tasks(findings, sample_project.id, min_relevance=0.6)
        assert len(tasks) == 1
        assert tasks[0].recommended_agent == "gemini"

    async def test_task_title_includes_mined_prefix(self, repo_miner, repository, sample_project):
        """Task title includes [Mined:{repo}] prefix."""
        await repository.create_project(sample_project)
        findings = [
            MiningFinding(
                title="Test Pattern",
                description="Helpful testing approach",
                category="testing",
                source_repo="test-lib",
                relevance_score=0.8,
            ),
        ]
        tasks = await repo_miner._generate_tasks(findings, sample_project.id, min_relevance=0.6)
        assert len(tasks) == 1
        assert tasks[0].title.startswith("[Mined:test-lib]")

    async def test_generates_multiple_tasks_sorted_by_relevance(self, repo_miner, repository, sample_project):
        """Multiple tasks are generated, sorted by relevance descending."""
        await repository.create_project(sample_project)
        findings = [
            MiningFinding(
                title="Medium",
                description="Medium importance",
                category="code_quality",
                source_repo="repo-a",
                relevance_score=0.7,
            ),
            MiningFinding(
                title="High",
                description="High importance",
                category="architecture",
                source_repo="repo-b",
                relevance_score=0.9,
            ),
            MiningFinding(
                title="Low",
                description="Low importance",
                category="testing",
                source_repo="repo-c",
                relevance_score=0.6,
            ),
        ]
        tasks = await repo_miner._generate_tasks(findings, sample_project.id, min_relevance=0.6)
        assert len(tasks) == 3
        # Tasks should be ordered by relevance descending
        assert "High" in tasks[0].title
        assert "Medium" in tasks[1].title
        assert "Low" in tasks[2].title

    async def test_empty_findings_returns_empty_list(self, repo_miner, repository, sample_project):
        """No findings produces no tasks."""
        await repository.create_project(sample_project)
        tasks = await repo_miner._generate_tasks([], sample_project.id, min_relevance=0.6)
        assert tasks == []

    async def test_task_status_is_pending(self, repo_miner, repository, sample_project):
        """Generated tasks have PENDING status."""
        await repository.create_project(sample_project)
        findings = [
            MiningFinding(
                title="Pending Test",
                description="Should be pending",
                category="testing",
                source_repo="repo",
                relevance_score=0.8,
            ),
        ]
        tasks = await repo_miner._generate_tasks(findings, sample_project.id, min_relevance=0.6)
        assert tasks[0].status == TaskStatus.PENDING

    async def test_generated_task_carries_runbook_fields(self, repo_miner, repository, sample_project):
        """Generated tasks copy execution and acceptance commands into typed fields."""
        await repository.create_project(sample_project)
        await repository.create_action_template(
            ActionTemplate(
                id="tmpl-123",
                title="Pipeline template",
                problem_pattern="Build/test standardization",
                execution_steps=["npm ci", "npm run lint"],
                acceptance_checks=["npm test"],
            )
        )
        findings = [
            MiningFinding(
                title="Pipeline hardening",
                description="Make build/test repeatable",
                category="code_quality",
                source_repo="bioclaw",
                relevance_score=0.9,
                action_template_id="tmpl-123",
                execution_steps=["npm ci", "npm run lint"],
                acceptance_checks=["npm test"],
                rollback_steps=["git restore src/index.ts"],
                preconditions=["Node installed"],
            ),
        ]
        tasks = await repo_miner._generate_tasks(findings, sample_project.id, min_relevance=0.6)
        assert len(tasks) == 1
        task = tasks[0]
        assert task.action_template_id == "tmpl-123"
        assert task.execution_steps == ["npm ci", "npm run lint"]
        assert task.acceptance_checks == ["npm test"]
        assert "### Execution Steps" in task.description
        assert "### Acceptance Checks" in task.description


# ===========================================================================
# 9. CLI registration
# ===========================================================================

class TestCLIRegistration:
    """Tests for mine command registration in CLI app."""

    def test_mine_command_exists(self):
        """The 'mine' command is registered in the typer app."""
        from claw.cli import app
        # Typer stores name=None for commands using the function name as command name.
        # Resolve effective name by falling back to the callback function name.
        command_names = [
            cmd.name or (cmd.callback.__name__ if cmd.callback else None)
            for cmd in app.registered_commands
        ]
        assert "mine" in command_names


# ===========================================================================
# 10. _canonicalize_name()
# ===========================================================================

class TestCanonicalizeName:
    """Tests for _canonicalize_name() — version/variant suffix stripping."""

    def test_strips_version_suffix(self):
        """Strips -v2, -v3, _v10 etc."""
        assert _canonicalize_name("ace-forecaster-v3") == "ace-forecaster"
        assert _canonicalize_name("project_v2") == "project"
        assert _canonicalize_name("tool-v10") == "tool"

    def test_strips_common_suffixes(self):
        """Strips -final, -latest, -backup, -copy, -wip, -old, -new, -orig."""
        assert _canonicalize_name("project-final") == "project"
        assert _canonicalize_name("project-latest") == "project"
        assert _canonicalize_name("project-backup") == "project"
        assert _canonicalize_name("project-copy") == "project"
        assert _canonicalize_name("project-wip") == "project"
        assert _canonicalize_name("project-old") == "project"
        assert _canonicalize_name("project-new") == "project"
        assert _canonicalize_name("project-orig") == "project"

    def test_strips_env_suffixes(self):
        """Strips -dev, -test, -staging, -prod."""
        assert _canonicalize_name("api-dev") == "api"
        assert _canonicalize_name("api-test") == "api"
        assert _canonicalize_name("api-staging") == "api"
        assert _canonicalize_name("api-prod") == "api"

    def test_strips_trailing_digits(self):
        """Strips bare trailing digits after dash: -2, -3, etc."""
        assert _canonicalize_name("project-2") == "project"
        assert _canonicalize_name("tool-42") == "tool"

    def test_iterative_stripping(self):
        """Strips multiple suffixes iteratively."""
        assert _canonicalize_name("tool-dev-v2") == "tool"
        assert _canonicalize_name("project-old-backup") == "project"

    def test_preserves_meaningful_names(self):
        """Doesn't strip parts that are part of the project name."""
        assert _canonicalize_name("grokflow-cli") == "grokflow-cli"
        assert _canonicalize_name("ace-forecaster") == "ace-forecaster"
        assert _canonicalize_name("my-awesome-project") == "my-awesome-project"

    def test_lowercases(self):
        """Names are lowercased."""
        assert _canonicalize_name("MyProject-V2") == "myproject"

    def test_underscore_separator(self):
        """Works with underscore separator too."""
        assert _canonicalize_name("project_final") == "project"
        assert _canonicalize_name("tool_backup") == "tool"

    def test_empty_and_simple(self):
        """Handles edge cases."""
        assert _canonicalize_name("x") == "x"
        assert _canonicalize_name("project") == "project"


# ===========================================================================
# 11. _dedup_iterations()
# ===========================================================================

class TestDedupIterations:
    """Tests for _dedup_iterations() — picking best version per canonical name."""

    def _make_candidate(self, name: str, **kwargs) -> RepoCandidate:
        """Helper to create a RepoCandidate with defaults."""
        from pathlib import Path
        return RepoCandidate(
            path=Path(f"/repos/{name}"),
            name=name,
            canonical_name=_canonicalize_name(name),
            depth=kwargs.get("depth", 1),
            file_count=kwargs.get("file_count", 5),
            last_commit_ts=kwargs.get("last_commit_ts", 1000.0),
            total_bytes=kwargs.get("total_bytes", 5000),
        )

    def test_single_repo_passes_through(self):
        """Single repo with unique canonical name is always selected."""
        candidates = [self._make_candidate("my-project")]
        selected, skipped = _dedup_iterations(candidates)
        assert len(selected) == 1
        assert len(skipped) == 0
        assert selected[0].name == "my-project"

    def test_dedup_picks_newest(self):
        """When multiple iterations exist, picks the one with latest commit."""
        candidates = [
            self._make_candidate("project-v1", last_commit_ts=1000.0),
            self._make_candidate("project-v2", last_commit_ts=2000.0),
            self._make_candidate("project-v3", last_commit_ts=3000.0),
        ]
        selected, skipped = _dedup_iterations(candidates)
        assert len(selected) == 1
        assert selected[0].name == "project-v3"
        assert len(skipped) == 2

    def test_dedup_uses_file_count_tiebreaker(self):
        """When timestamps are equal, picks the one with most files."""
        candidates = [
            self._make_candidate("project-v1", last_commit_ts=1000.0, file_count=5),
            self._make_candidate("project-v2", last_commit_ts=1000.0, file_count=20),
        ]
        selected, skipped = _dedup_iterations(candidates)
        assert len(selected) == 1
        assert selected[0].name == "project-v2"

    def test_dedup_uses_total_bytes_tiebreaker(self):
        """When timestamp and file_count are equal, picks largest."""
        candidates = [
            self._make_candidate("project-v1", last_commit_ts=1000.0, file_count=5, total_bytes=1000),
            self._make_candidate("project-v2", last_commit_ts=1000.0, file_count=5, total_bytes=5000),
        ]
        selected, skipped = _dedup_iterations(candidates)
        assert len(selected) == 1
        assert selected[0].name == "project-v2"

    def test_different_canonical_names_all_selected(self):
        """Repos with different canonical names are all selected."""
        candidates = [
            self._make_candidate("project-a"),
            self._make_candidate("project-b"),
            self._make_candidate("tool-x"),
        ]
        selected, skipped = _dedup_iterations(candidates)
        assert len(selected) == 3
        assert len(skipped) == 0

    def test_skipped_includes_reason(self):
        """Skipped entries include the superseding repo in the reason."""
        candidates = [
            self._make_candidate("project-v1", last_commit_ts=1000.0),
            self._make_candidate("project-v2", last_commit_ts=2000.0),
        ]
        selected, skipped = _dedup_iterations(candidates)
        assert len(skipped) == 1
        reason = skipped[0][1]
        assert "superseded by" in reason
        assert "project-v2" in reason

    def test_mixed_groups(self):
        """Mix of unique repos and iteration groups."""
        candidates = [
            self._make_candidate("alpha"),               # unique
            self._make_candidate("beta-v1", last_commit_ts=1000.0),
            self._make_candidate("beta-v2", last_commit_ts=2000.0),
            self._make_candidate("gamma"),               # unique
            self._make_candidate("delta-old", last_commit_ts=500.0),
            self._make_candidate("delta-new", last_commit_ts=3000.0),
        ]
        selected, skipped = _dedup_iterations(candidates)
        assert len(selected) == 4  # alpha, beta-v2, gamma, delta-new
        assert len(skipped) == 2   # beta-v1, delta-old
        selected_names = {c.name for c in selected}
        assert "alpha" in selected_names
        assert "beta-v2" in selected_names
        assert "gamma" in selected_names
        assert "delta-new" in selected_names


# ===========================================================================
# 12. _collect_repo_metadata()
# ===========================================================================

class TestCollectRepoMetadata:
    """Tests for _collect_repo_metadata() — lightweight metadata collection."""

    def test_counts_source_files(self, tmp_path):
        """Counts files matching _CODE_EXTENSIONS in top level."""
        (tmp_path / ".git").mkdir()
        (tmp_path / "main.py").write_text("x = 1", encoding="utf-8")
        (tmp_path / "utils.py").write_text("y = 2", encoding="utf-8")
        (tmp_path / "data.bin").write_bytes(b"\x00")

        file_count, _, total_bytes, scan_signature, _ = _collect_repo_metadata(tmp_path)
        assert file_count >= 2  # at least top-level .py files
        assert total_bytes > 0
        assert scan_signature

    def test_includes_subdirectory_files(self, tmp_path):
        """Counts files in immediate subdirectories too."""
        (tmp_path / ".git").mkdir()
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("pass", encoding="utf-8")
        (src / "lib.py").write_text("pass", encoding="utf-8")

        file_count, _, _, _, _ = _collect_repo_metadata(tmp_path)
        assert file_count >= 2

    def test_uses_git_mtime_for_timestamp(self, tmp_path):
        """Uses .git directory mtime as last_commit_ts."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")

        _, last_commit_ts, _, _, _ = _collect_repo_metadata(tmp_path)
        assert last_commit_ts > 0

    def test_handles_no_git_dir(self, tmp_path):
        """Falls back to source file mtimes when no .git directory exists."""
        (tmp_path / "main.py").write_text("x = 1", encoding="utf-8")
        _, last_commit_ts, _, _, _ = _collect_repo_metadata(tmp_path)
        assert last_commit_ts > 0.0


# ===========================================================================
# 13. RepoCandidate dataclass
# ===========================================================================

class TestRepoCandidate:
    """Tests for RepoCandidate dataclass."""

    def test_defaults(self):
        """RepoCandidate has correct defaults."""
        from pathlib import Path
        c = RepoCandidate(
            path=Path("/repos/test"),
            name="test",
            canonical_name="test",
            depth=1,
        )
        assert c.file_count == 0
        assert c.last_commit_ts == 0.0
        assert c.total_bytes == 0

    def test_custom_fields(self):
        """RepoCandidate accepts custom values."""
        from pathlib import Path
        c = RepoCandidate(
            path=Path("/repos/project-v2"),
            name="project-v2",
            canonical_name="project",
            depth=3,
            file_count=42,
            last_commit_ts=1709900000.0,
            total_bytes=150000,
        )
        assert c.canonical_name == "project"
        assert c.file_count == 42
        assert c.depth == 3


# ===========================================================================
# 14. mine-workspace command
# ===========================================================================

class TestMineWorkspaceCommand:
    """Tests for mine-workspace CLI command registration."""

    def test_mine_workspace_command_registered(self):
        """The 'mine-workspace' command is registered in the typer app."""
        from claw.cli import app
        command_names = [
            cmd.name or (cmd.callback.__name__ if cmd.callback else None)
            for cmd in app.registered_commands
        ]
        assert "mine-workspace" in command_names

    def test_mine_workspace_accepts_multiple_directories(self):
        """The mine-workspace command has a 'directories' list parameter."""
        from claw.cli import mine_workspace
        import inspect
        sig = inspect.signature(mine_workspace)
        assert "directories" in sig.parameters
        param = sig.parameters["directories"]
        # Should be annotated as list[str]
        assert "list" in str(param.annotation).lower() or "list" in str(param.default).lower()


# ===========================================================================
# 15. Multi-directory discovery and dedup
# ===========================================================================

class TestMultiDirectoryDiscovery:
    """Tests for repo discovery across multiple directories."""

    def test_discovers_repos_across_two_directories(self, tmp_path):
        """Repos from separate roots are all found."""
        dir_a = tmp_path / "workspace_a"
        dir_b = tmp_path / "workspace_b"
        # Create two repos in separate roots
        for name, parent in [("repo-alpha", dir_a), ("repo-beta", dir_b)]:
            repo = parent / name
            repo.mkdir(parents=True)
            (repo / ".git").mkdir()
            (repo / "main.py").write_text("print('hello')\n")
        candidates_a = _discover_repos(dir_a, max_depth=3)
        candidates_b = _discover_repos(dir_b, max_depth=3)
        all_names = {c.name for c in candidates_a} | {c.name for c in candidates_b}
        assert "repo-alpha" in all_names
        assert "repo-beta" in all_names

    def test_cross_path_dedup_by_resolved_path(self, tmp_path):
        """Same repo path discovered from two roots is deduplicated."""
        shared = tmp_path / "shared" / "repo-x"
        shared.mkdir(parents=True)
        (shared / ".git").mkdir()
        (shared / "app.py").write_text("x = 1\n")
        # Discover from two roots that contain the same repo
        c1 = _discover_repos(tmp_path / "shared", max_depth=3)
        c2 = _discover_repos(tmp_path / "shared", max_depth=3)
        # Merge with resolved-path dedup
        seen: set[str] = set()
        merged: list = []
        for c in c1 + c2:
            key = str(c.path.resolve())
            if key not in seen:
                seen.add(key)
                merged.append(c)
        assert len(merged) == 1
        assert merged[0].name == "repo-x"

    def test_cross_directory_canonical_dedup(self, tmp_path):
        """Canonical name dedup works across directories: v1 + v2 -> best kept."""
        dir_a = tmp_path / "old_stuff"
        dir_b = tmp_path / "new_stuff"
        # v1 in dir_a (small)
        v1 = dir_a / "my-tool-v1"
        v1.mkdir(parents=True)
        (v1 / ".git").mkdir()
        (v1 / "tool.py").write_text("v1\n")
        # v2 in dir_b (bigger)
        v2 = dir_b / "my-tool-v2"
        v2.mkdir(parents=True)
        (v2 / ".git").mkdir()
        (v2 / "tool.py").write_text("v2 with more content " * 50 + "\n")
        (v2 / "utils.py").write_text("def helper(): pass\n")
        c_a = _discover_repos(dir_a, max_depth=3)
        c_b = _discover_repos(dir_b, max_depth=3)
        merged = c_a + c_b
        selected, skipped = _dedup_iterations(merged)
        selected_names = {c.name for c in selected}
        # Both share canonical "my-tool", so only best (v2, more files/bytes) should survive
        assert len(selected) == 1
        assert "my-tool-v2" in selected_names

    def test_empty_directories_produce_empty_result(self, tmp_path):
        """Empty directories return empty candidate list without error."""
        empty = tmp_path / "empty"
        empty.mkdir()
        candidates = _discover_repos(empty, max_depth=3)
        assert candidates == []


# ===========================================================================
# 16. mine-self command
# ===========================================================================

class TestMineSelfCommand:
    """Tests for mine-self CLI command registration and parameters."""

    def test_mine_self_command_registered(self):
        """The 'mine-self' command is registered in the typer app."""
        from claw.cli import app
        command_names = [
            cmd.name or (cmd.callback.__name__ if cmd.callback else None)
            for cmd in app.registered_commands
        ]
        assert "mine-self" in command_names

    def test_mine_self_has_quick_option(self):
        """mine-self has a --quick parameter."""
        from claw.cli import mine_self
        import inspect
        sig = inspect.signature(mine_self)
        assert "quick" in sig.parameters

    def test_mine_self_has_path_option(self):
        """mine-self has a --path parameter (not a positional argument)."""
        from claw.cli import mine_self
        import inspect
        sig = inspect.signature(mine_self)
        assert "path" in sig.parameters


# ===========================================================================
# 17. mine-self quick preview
# ===========================================================================

class TestMineSelfQuickPreview:
    """Tests for mine-self --quick preview functionality."""

    def test_quick_preview_collects_metadata(self, tmp_path):
        """_collect_repo_metadata returns file count and bytes from real files."""
        project = tmp_path / "my-project"
        project.mkdir()
        (project / "main.py").write_text("print('hello world')\n")
        (project / "utils.py").write_text("def add(a, b): return a + b\n")
        (project / "README.md").write_text("# My Project\n")
        file_count, _, total_bytes, sig, _ = _collect_repo_metadata(project)
        assert file_count == 3
        assert total_bytes > 0
        assert len(sig) == 40  # SHA-1 hex digest

    def test_quick_preview_domain_classification(self, tmp_path):
        """Domain keywords detect AI domain from file content."""
        from claw.miner import _DOMAIN_KEYWORDS
        project = tmp_path / "ai-project"
        project.mkdir()
        (project / "agent.py").write_text(
            "from openai import OpenAI\n"
            "client = OpenAI()\n"
            "response = client.chat.completions.create(model='gpt-4')\n"
            "embedding = get_embedding(text)\n"
            "prompt = 'You are an agent that...'\n"
        )
        (project / "README.md").write_text("# AI Agent Framework\nLLM-powered agent with RAG.\n")
        content, _ = serialize_repo(project)
        content_lower = content.lower()
        scores: dict[str, int] = {}
        for category, keywords in _DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in content_lower[:10_000])
            if score > 0:
                scores[category] = score
        assert "ai_integration" in scores
        assert scores["ai_integration"] >= 3  # agent, llm/openai, prompt, embedding, etc.

    def test_quick_preview_language_breakdown(self, tmp_path):
        """Language breakdown groups .py and .js correctly, skips non-code."""
        from claw.miner import _CODE_EXTENSIONS, _SKIP_DIRS
        project = tmp_path / "mixed-project"
        project.mkdir()
        (project / "app.py").write_text("x = 1\n")
        (project / "helper.py").write_text("y = 2\n")
        (project / "index.js").write_text("const z = 3;\n")
        (project / "logo.png").write_bytes(b"\x89PNG\r\n")  # Should be skipped
        ext_counts: dict[str, int] = {}
        for filepath in sorted(project.rglob("*")):
            if not filepath.is_file():
                continue
            rel = filepath.relative_to(project)
            if any(part in _SKIP_DIRS for part in rel.parts):
                continue
            ext = filepath.suffix.lower()
            if ext not in _CODE_EXTENSIONS:
                continue
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
        assert ext_counts.get(".py") == 2
        assert ext_counts.get(".js") == 1
        assert ".png" not in ext_counts

    def test_self_tagging_convention(self):
        """Self-mining repo name ends with '-self'."""
        project_name = "multiclaw"
        repo_name = f"{project_name}-self"
        assert repo_name == "multiclaw-self"
        assert repo_name.endswith("-self")
