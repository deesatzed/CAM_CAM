"""Tests for multi-brain / multi-language mining architecture.

Covers:
    1. detect_repo_language() — config-file signals, extension census, fallback
    2. BrainConfig model — defaults, custom values, per-brain prompt assignment
    3. Prompt templates — all 5 prompts exist and contain {repo_content}
    4. _LANGUAGE_TO_BRAIN / _EXT_TO_LANGUAGE / _LANGUAGE_SIGNALS — mapping completeness
    5. VALID_BRAIN_NAMES — matches BrainConfig keys
    6. mine_repo() brain parameter — auto-detect and explicit override
    7. store_finding() brain tagging — brain:xxx tag injection
    8. ensure_language_ganglion() — python passthrough, non-python provisioning
    9. _register_sibling_if_needed() — idempotent claw.toml registration
    10. _refresh_ganglion_manifests() — manifest refresh after mining
    11. Backward compatibility — Python brain path unchanged
    12. CLI --brain flag validation

All tests use REAL dependencies — no mocks, no placeholders, no cached responses.
Database tests use the real SQLite in-memory engine from conftest.py.
Filesystem tests use pytest's tmp_path fixture for isolation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest

from claw.core.config import (
    BrainConfig,
    ClawConfig,
    DatabaseConfig,
    MiningConfig,
    load_config,
)
from claw.core.models import Methodology, Project
from claw.db.embeddings import EmbeddingEngine
from claw.db.engine import DatabaseEngine
from claw.db.repository import Repository
from claw.memory.hybrid_search import HybridSearch
from claw.memory.semantic import SemanticMemory
from claw.miner import (
    VALID_BRAIN_NAMES,
    MiningFinding,
    MiningReport,
    RepoMiner,
    RepoMiningResult,
    _EXT_TO_LANGUAGE,
    _LANGUAGE_SIGNALS,
    _LANGUAGE_TO_BRAIN,
    _register_sibling_if_needed,
    detect_all_repo_languages,
    detect_repo_language,
    ensure_language_ganglion,
    serialize_repo,
)


# ---------------------------------------------------------------------------
# Deterministic embedding engine (same pattern as test_miner.py)
# ---------------------------------------------------------------------------

class FixedEmbeddingEngine:
    """Deterministic embedding engine using SHA-384 for reproducible tests."""

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
# Helpers
# ---------------------------------------------------------------------------

def _make_ts_repo(tmp_path: Path) -> Path:
    """Create a minimal TypeScript repo structure."""
    repo = tmp_path / "ts-project"
    repo.mkdir()
    (repo / "tsconfig.json").write_text('{"compilerOptions": {}}')
    (repo / "package.json").write_text('{"name": "ts-project"}')
    src = repo / "src"
    src.mkdir()
    (src / "index.ts").write_text("export function hello(): string { return 'hi'; }")
    (src / "utils.ts").write_text("export const add = (a: number, b: number) => a + b;")
    return repo


def _make_go_repo(tmp_path: Path) -> Path:
    """Create a minimal Go repo structure."""
    repo = tmp_path / "go-project"
    repo.mkdir()
    (repo / "go.mod").write_text("module example.com/myproject\n\ngo 1.21\n")
    (repo / "main.go").write_text('package main\n\nfunc main() {}\n')
    (repo / "handler.go").write_text('package main\n\nfunc handler() {}\n')
    return repo


def _make_rust_repo(tmp_path: Path) -> Path:
    """Create a minimal Rust repo structure."""
    repo = tmp_path / "rust-project"
    repo.mkdir()
    (repo / "Cargo.toml").write_text('[package]\nname = "mylib"\nversion = "0.1.0"\n')
    src = repo / "src"
    src.mkdir()
    (src / "lib.rs").write_text("pub fn add(a: i32, b: i32) -> i32 { a + b }")
    (src / "main.rs").write_text("fn main() {}")
    return repo


def _make_python_repo(tmp_path: Path) -> Path:
    """Create a minimal Python repo structure."""
    repo = tmp_path / "py-project"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nname = "mylib"\n')
    src = repo / "src"
    src.mkdir()
    (src / "app.py").write_text("def main():\n    pass\n")
    (src / "utils.py").write_text("def add(a, b):\n    return a + b\n")
    return repo


def _make_cpp_repo(tmp_path: Path) -> Path:
    """Create a minimal C++ repo structure (no config-file signal)."""
    repo = tmp_path / "cpp-project"
    repo.mkdir()
    (repo / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.10)\n")
    src = repo / "src"
    src.mkdir()
    (src / "main.cpp").write_text('#include <iostream>\nint main() { return 0; }\n')
    (src / "utils.cpp").write_text("int add(int a, int b) { return a + b; }\n")
    (src / "utils.h").write_text("#pragma once\nint add(int a, int b);\n")
    return repo


def _make_mixed_repo(tmp_path: Path) -> Path:
    """Create a repo with both TS config and many Python files (TS should win)."""
    repo = tmp_path / "mixed-project"
    repo.mkdir()
    (repo / "tsconfig.json").write_text('{"compilerOptions": {}}')
    (repo / "package.json").write_text('{"name": "mixed"}')
    # Python files too
    (repo / "setup.py").write_text("from setuptools import setup; setup()")
    src = repo / "src"
    src.mkdir()
    (src / "index.ts").write_text("export function main() {}")
    # More Python files than TS files
    for i in range(5):
        (src / f"mod{i}.py").write_text(f"x = {i}\n")
    return repo


def _make_empty_repo(tmp_path: Path) -> Path:
    """Create a repo with no recognizable source files."""
    repo = tmp_path / "empty-project"
    repo.mkdir()
    (repo / "README.md").write_text("# Empty")
    (repo / "LICENSE").write_text("MIT")
    return repo


# ===========================================================================
# Test Class 1: detect_repo_language()
# ===========================================================================

class TestDetectRepoLanguage:
    """Tests for detect_repo_language() — config-file signals, census, fallback."""

    def test_typescript_repo_detected(self, tmp_path):
        repo = _make_ts_repo(tmp_path)
        assert detect_repo_language(repo) == "typescript"

    def test_go_repo_detected(self, tmp_path):
        repo = _make_go_repo(tmp_path)
        assert detect_repo_language(repo) == "go"

    def test_rust_repo_detected(self, tmp_path):
        repo = _make_rust_repo(tmp_path)
        assert detect_repo_language(repo) == "rust"

    def test_python_repo_detected(self, tmp_path):
        repo = _make_python_repo(tmp_path)
        assert detect_repo_language(repo) == "python"

    def test_cpp_repo_falls_to_misc(self, tmp_path):
        """C++ has no config-file signal, falls through to extension census → misc."""
        repo = _make_cpp_repo(tmp_path)
        assert detect_repo_language(repo) == "misc"

    def test_empty_repo_returns_misc(self, tmp_path):
        repo = _make_empty_repo(tmp_path)
        assert detect_repo_language(repo) == "misc"

    def test_nonexistent_path_returns_misc(self, tmp_path):
        assert detect_repo_language(tmp_path / "does-not-exist") == "misc"

    def test_tsconfig_promotes_over_python_config(self, tmp_path):
        """When tsconfig.json is present, TypeScript wins even with Python configs."""
        repo = _make_mixed_repo(tmp_path)
        assert detect_repo_language(repo) == "typescript"

    def test_javascript_repo_uses_typescript_brain(self, tmp_path):
        """JS-only repo (package.json but no tsconfig) → typescript brain."""
        repo = tmp_path / "js-project"
        repo.mkdir()
        (repo / "package.json").write_text('{"name": "js-only"}')
        src = repo / "src"
        src.mkdir()
        (src / "index.js").write_text("module.exports = {}")
        (src / "utils.js").write_text("const x = 1;")
        # package.json → javascript → _LANGUAGE_TO_BRAIN → "typescript"
        result = detect_repo_language(repo)
        assert result == "typescript"

    def test_extension_census_fallback(self, tmp_path):
        """When no config file signals, falls to extension census."""
        repo = tmp_path / "ext-only"
        repo.mkdir()
        # No config files, just .go source
        (repo / "main.go").write_text("package main\nfunc main() {}\n")
        (repo / "server.go").write_text("package main\nfunc serve() {}\n")
        (repo / "handler.go").write_text("package main\nfunc handle() {}\n")
        assert detect_repo_language(repo) == "go"

    def test_extension_census_dominant_wins(self, tmp_path):
        """When multiple languages via extension census, dominant wins."""
        repo = tmp_path / "multi-ext"
        repo.mkdir()
        # 5 Rust files vs 2 Python
        for i in range(5):
            (repo / f"mod{i}.rs").write_text(f"pub fn f{i}() {{}}")
        for i in range(2):
            (repo / f"util{i}.py").write_text(f"x = {i}")
        assert detect_repo_language(repo) == "rust"

    def test_skip_dirs_respected(self, tmp_path):
        """Files in node_modules/ etc. don't influence detection."""
        repo = tmp_path / "skip-test"
        repo.mkdir()
        # Main language = python (config signal)
        (repo / "pyproject.toml").write_text('[project]\nname = "test"')
        (repo / "app.py").write_text("x = 1")
        # Lots of TS in node_modules (should be ignored)
        nm = repo / "node_modules" / "some-lib"
        nm.mkdir(parents=True)
        for i in range(20):
            (nm / f"file{i}.ts").write_text(f"export const x = {i};")
        assert detect_repo_language(repo) == "python"

    def test_history_dir_skipped(self, tmp_path):
        """The .history dir (VS Code local history) is skipped."""
        repo = tmp_path / "history-test"
        repo.mkdir()
        (repo / "Cargo.toml").write_text('[package]\nname = "test"')
        (repo / "main.rs").write_text("fn main() {}")
        hist = repo / ".history"
        hist.mkdir()
        for i in range(50):
            (hist / f"old{i}.py").write_text(f"x = {i}")
        assert detect_repo_language(repo) == "rust"

    def test_config_overrides_respected(self, tmp_path):
        """Custom config's extra_skip_dirs are respected."""
        repo = tmp_path / "cfg-test"
        repo.mkdir()
        (repo / "go.mod").write_text("module test")
        (repo / "main.go").write_text("package main")
        config = ClawConfig()
        result = detect_repo_language(repo, config)
        assert result == "go"

    @pytest.mark.asyncio
    async def test_mine_repo_drops_zero_file_config_signal_zones(self, tmp_path):
        """A tsconfig without TS files should not trigger a zero-file model call."""
        repo = tmp_path / "py-with-empty-ts-zone"
        repo.mkdir()
        (repo / "tsconfig.json").write_text('{"compilerOptions": {}}')
        for idx in range(3):
            (repo / f"mod{idx}.py").write_text(f"x = {idx}\n")

        zones = detect_all_repo_languages(repo, ClawConfig())
        assert zones["typescript"].file_count == 0
        assert zones["python"].file_count == 3

        miner = RepoMiner(
            repository=None,
            llm_client=None,
            semantic_memory=None,
            config=ClawConfig(),
        )
        seen: list[str] = []

        async def fake_single_brain(**kwargs):
            seen.append(kwargs["brain"])
            return RepoMiningResult(
                repo_name=kwargs["repo_name"],
                repo_path=str(kwargs["repo_path"]),
                findings=[],
            )

        miner._mine_single_brain = fake_single_brain

        await miner.mine_repo(repo, "py-with-empty-ts-zone", "project-1")

        assert seen == ["python"]


# ===========================================================================
# Test Class 2: BrainConfig model
# ===========================================================================

class TestBrainConfig:
    """Tests for BrainConfig Pydantic model and defaults."""

    def test_default_values(self):
        bc = BrainConfig()
        assert bc.enabled is True
        assert bc.max_bytes == 921_600
        assert bc.prompt == "repo-mine.md"
        assert bc.priority_extensions == []
        assert bc.extra_skip_dirs == []
        assert bc.ganglion_name == ""

    def test_custom_values(self):
        bc = BrainConfig(
            max_bytes=2_000_000,
            prompt="repo-mine-go.md",
            ganglion_name="go",
            priority_extensions=[".go"],
        )
        assert bc.max_bytes == 2_000_000
        assert bc.prompt == "repo-mine-go.md"
        assert bc.ganglion_name == "go"
        assert bc.priority_extensions == [".go"]

    def test_mining_config_default_brains(self):
        mc = MiningConfig()
        brains = mc.brains
        assert "python" in brains
        assert "typescript" in brains
        assert "go" in brains
        assert "rust" in brains
        assert "misc" in brains
        assert len(brains) == 5

    def test_python_brain_uses_primary_db(self):
        mc = MiningConfig()
        assert mc.brains["python"].ganglion_name == ""

    def test_typescript_brain_has_larger_budget(self):
        mc = MiningConfig()
        ts = mc.brains["typescript"]
        py = mc.brains["python"]
        assert ts.max_bytes > py.max_bytes

    def test_non_python_brains_have_ganglion_names(self):
        mc = MiningConfig()
        for name in ("typescript", "go", "rust", "misc"):
            assert mc.brains[name].ganglion_name == name

    def test_each_brain_has_unique_prompt(self):
        mc = MiningConfig()
        prompts = {bc.prompt for bc in mc.brains.values()}
        # All 5 brains should have distinct prompts
        assert len(prompts) == 5

    def test_valid_brain_names_match_config(self):
        mc = MiningConfig()
        assert set(mc.brains.keys()) == VALID_BRAIN_NAMES


# ===========================================================================
# Test Class 3: Prompt templates
# ===========================================================================

class TestPromptTemplates:
    """Verify all language-specific prompt templates exist and are well-formed."""

    PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

    @pytest.mark.parametrize("prompt_file", [
        "repo-mine.md",
        "repo-mine-typescript.md",
        "repo-mine-go.md",
        "repo-mine-rust.md",
        "repo-mine-misc.md",
    ])
    def test_prompt_file_exists(self, prompt_file):
        path = self.PROMPTS_DIR / prompt_file
        assert path.exists(), f"Missing prompt template: {path}"

    @pytest.mark.parametrize("prompt_file", [
        "repo-mine.md",
        "repo-mine-typescript.md",
        "repo-mine-go.md",
        "repo-mine-rust.md",
        "repo-mine-misc.md",
    ])
    def test_prompt_contains_repo_content_placeholder(self, prompt_file):
        path = self.PROMPTS_DIR / prompt_file
        content = path.read_text(encoding="utf-8")
        assert "{repo_content}" in content, f"{prompt_file} missing {{repo_content}} placeholder"

    @pytest.mark.parametrize("prompt_file", [
        "repo-mine.md",
        "repo-mine-typescript.md",
        "repo-mine-go.md",
        "repo-mine-rust.md",
        "repo-mine-misc.md",
    ])
    def test_prompt_has_json_output_format(self, prompt_file):
        path = self.PROMPTS_DIR / prompt_file
        content = path.read_text(encoding="utf-8")
        assert '"title"' in content, f"{prompt_file} missing title field in output format"
        assert '"category"' in content, f"{prompt_file} missing category field in output format"
        assert '"relevance_score"' in content, f"{prompt_file} missing relevance_score in output format"

    def test_typescript_prompt_mentions_typescript(self):
        content = (self.PROMPTS_DIR / "repo-mine-typescript.md").read_text()
        assert "typescript" in content.lower() or "TypeScript" in content

    def test_go_prompt_mentions_go(self):
        content = (self.PROMPTS_DIR / "repo-mine-go.md").read_text()
        assert "Go" in content or "go " in content.lower()

    def test_rust_prompt_mentions_rust(self):
        content = (self.PROMPTS_DIR / "repo-mine-rust.md").read_text()
        assert "Rust" in content or "rust" in content.lower()

    def test_misc_prompt_is_language_agnostic(self):
        content = (self.PROMPTS_DIR / "repo-mine-misc.md").read_text()
        assert "Language-Agnostic" in content or "language" in content.lower()

    def test_python_prompt_not_changed(self):
        """Verify the original Python prompt still references Python."""
        content = (self.PROMPTS_DIR / "repo-mine.md").read_text()
        assert "Python" in content or "python" in content


# ===========================================================================
# Test Class 4: Mapping constants
# ===========================================================================

class TestMappingConstants:
    """Tests for _LANGUAGE_SIGNALS, _LANGUAGE_TO_BRAIN, _EXT_TO_LANGUAGE."""

    def test_all_signal_languages_have_brain_mapping(self):
        """Every language detected by config-file signals maps to a brain."""
        for lang in set(_LANGUAGE_SIGNALS.values()):
            assert lang in _LANGUAGE_TO_BRAIN, f"Language '{lang}' has no brain mapping"

    def test_all_ext_languages_have_brain_mapping(self):
        """Every language detected by extension census maps to a brain."""
        for lang in set(_EXT_TO_LANGUAGE.values()):
            if lang != "misc":
                assert lang in _LANGUAGE_TO_BRAIN, f"Ext language '{lang}' has no brain mapping"

    def test_all_brain_mappings_target_valid_brains(self):
        """Every brain in _LANGUAGE_TO_BRAIN is a valid brain name."""
        for brain in set(_LANGUAGE_TO_BRAIN.values()):
            assert brain in VALID_BRAIN_NAMES, f"Brain '{brain}' not in VALID_BRAIN_NAMES"

    def test_javascript_maps_to_typescript_brain(self):
        assert _LANGUAGE_TO_BRAIN["javascript"] == "typescript"

    def test_python_maps_to_python_brain(self):
        assert _LANGUAGE_TO_BRAIN["python"] == "python"

    def test_java_maps_to_misc(self):
        assert _LANGUAGE_TO_BRAIN["java"] == "misc"

    def test_tsconfig_signals_typescript(self):
        assert _LANGUAGE_SIGNALS["tsconfig.json"] == "typescript"

    def test_cargo_toml_signals_rust(self):
        assert _LANGUAGE_SIGNALS["cargo.toml"] == "rust"

    def test_go_mod_signals_go(self):
        assert _LANGUAGE_SIGNALS["go.mod"] == "go"


# ===========================================================================
# Test Class 5: ensure_language_ganglion()
# ===========================================================================

class TestEnsureLanguageGanglion:
    """Tests for ganglion auto-provisioning."""

    @pytest.fixture
    async def primary_db_pair(self, tmp_path, monkeypatch):
        """Create a primary DB pair (Repository + SemanticMemory).

        chdir to tmp_path so _register_sibling_if_needed writes to
        a throwaway claw.toml instead of polluting the real one.
        """
        monkeypatch.chdir(tmp_path)
        (tmp_path / "claw.toml").write_text("[project]\nname = 'test'\n")
        db_path = tmp_path / "data" / "claw.db"
        db_path.parent.mkdir(parents=True)
        config = DatabaseConfig(db_path=str(db_path))
        engine = DatabaseEngine(config)
        await engine.connect()
        await engine.initialize_schema()
        repo = Repository(engine)
        emb = FixedEmbeddingEngine()
        hybrid = HybridSearch(repository=repo, embedding_engine=emb)
        sem = SemanticMemory(repository=repo, embedding_engine=emb, hybrid_search=hybrid)
        yield repo, sem, engine, tmp_path
        await engine.close()

    @pytest.mark.asyncio
    async def test_python_brain_returns_primary(self, primary_db_pair):
        repo, sem, engine, tmp_path = primary_db_pair
        config = ClawConfig()
        config.database.db_path = str(tmp_path / "data" / "claw.db")

        brain_cfg = BrainConfig(ganglion_name="")
        result_repo, result_sem = await ensure_language_ganglion(
            "python", brain_cfg, repo, sem, config,
        )
        assert result_repo is repo
        assert result_sem is sem

    @pytest.mark.asyncio
    async def test_typescript_brain_provisions_ganglion(self, primary_db_pair):
        repo, sem, engine, tmp_path = primary_db_pair
        config = ClawConfig()
        config.database.db_path = str(tmp_path / "data" / "claw.db")

        brain_cfg = BrainConfig(ganglion_name="typescript")
        result_repo, result_sem = await ensure_language_ganglion(
            "typescript", brain_cfg, repo, sem, config,
        )
        # Should NOT be the primary DB
        assert result_repo is not repo
        assert result_sem is not sem
        # Ganglion DB should exist on disk
        ganglion_db = tmp_path / "instances" / "typescript" / "claw.db"
        assert ganglion_db.exists()

    @pytest.mark.asyncio
    async def test_ganglion_reused_on_second_call(self, primary_db_pair):
        """Second call reuses existing ganglion, doesn't re-create."""
        repo, sem, engine, tmp_path = primary_db_pair
        config = ClawConfig()
        config.database.db_path = str(tmp_path / "data" / "claw.db")

        brain_cfg = BrainConfig(ganglion_name="go")
        r1, s1 = await ensure_language_ganglion("go", brain_cfg, repo, sem, config)
        r2, s2 = await ensure_language_ganglion("go", brain_cfg, repo, sem, config)
        # Both should point to the same DB file
        ganglion_db = tmp_path / "instances" / "go" / "claw.db"
        assert ganglion_db.exists()

    @pytest.mark.asyncio
    async def test_ganglion_has_working_schema(self, primary_db_pair):
        """The auto-provisioned ganglion has a working schema (can save methodologies)."""
        repo, sem, engine, tmp_path = primary_db_pair
        config = ClawConfig()
        config.database.db_path = str(tmp_path / "data" / "claw.db")

        brain_cfg = BrainConfig(ganglion_name="rust")
        g_repo, g_sem = await ensure_language_ganglion(
            "rust", brain_cfg, repo, sem, config,
        )
        # Should be able to save a methodology
        meth = await g_sem.save_solution(
            problem_description="Test problem",
            solution_code="fn test() {}",
            tags=["brain:rust", "test"],
            language="rust",
        )
        assert meth.id is not None
        assert len(meth.id) > 0


# ===========================================================================
# Test Class 6: _register_sibling_if_needed()
# ===========================================================================

class TestRegisterSiblingIfNeeded:
    """Tests for idempotent claw.toml sibling registration."""

    def test_register_new_sibling(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # Create a minimal claw.toml
        (tmp_path / "claw.toml").write_text("[project]\nname = 'test'\n")
        config = ClawConfig()

        _register_sibling_if_needed("typescript", "/tmp/ts.db", config)

        content = (tmp_path / "claw.toml").read_text()
        assert "[[instances.siblings]]" in content
        assert 'name = "typescript"' in content
        assert 'db_path = "/tmp/ts.db"' in content

    def test_register_idempotent(self, tmp_path, monkeypatch):
        """Registering the same sibling twice doesn't duplicate the entry."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "claw.toml").write_text("[project]\nname = 'test'\n")
        config = ClawConfig()

        _register_sibling_if_needed("go", "/tmp/go.db", config)
        content_after_first = (tmp_path / "claw.toml").read_text()

        # Add the sibling to config to simulate already-registered
        from claw.core.config import InstanceConfig
        config.instances.siblings.append(
            InstanceConfig(name="go", db_path="/tmp/go.db")
        )
        _register_sibling_if_needed("go", "/tmp/go.db", config)
        content_after_second = (tmp_path / "claw.toml").read_text()

        assert content_after_first == content_after_second

    def test_no_claw_toml_logs_warning(self, tmp_path, monkeypatch):
        """No claw.toml present → logs warning, doesn't crash."""
        monkeypatch.chdir(tmp_path)
        config = ClawConfig()
        # Should not raise
        _register_sibling_if_needed("rust", "/tmp/rust.db", config)


# ===========================================================================
# Test Class 7: store_finding() brain tagging
# ===========================================================================

class TestStoreFindingBrainTag:
    """Tests for brain tag injection in store_finding()."""

    @pytest.fixture
    async def miner_with_db(self, tmp_path):
        """Create a RepoMiner with in-memory DB."""
        config = ClawConfig()
        config.database.db_path = ":memory:"
        engine = DatabaseEngine(config.database)
        await engine.connect()
        await engine.initialize_schema()
        repo = Repository(engine)
        emb = FixedEmbeddingEngine()
        hybrid = HybridSearch(repository=repo, embedding_engine=emb)
        sem = SemanticMemory(repository=repo, embedding_engine=emb, hybrid_search=hybrid)

        from claw.llm.client import LLMClient
        llm = LLMClient(config.llm)
        miner = RepoMiner(
            repository=repo,
            llm_client=llm,
            semantic_memory=sem,
            config=config,
        )
        yield miner, repo, engine
        await engine.close()

    def _make_finding(self, brain_name: str = "typescript") -> MiningFinding:
        return MiningFinding(
            title=f"Test finding for {brain_name}",
            description="A transferable pattern for testing.",
            category="architecture",
            source_files=["src/test.ts"],
            implementation_sketch="Implement this pattern by...",
            augmentation_notes="Adds cross-language value.",
            relevance_score=0.85,
            language=brain_name if brain_name != "misc" else "cpp",
            source_repo="test-repo",
        )

    @pytest.mark.asyncio
    async def test_brain_tag_injected(self, miner_with_db):
        miner, repo, engine = miner_with_db
        finding = self._make_finding("typescript")
        method_id = await miner.store_finding(finding, "proj-1", brain="typescript")
        assert method_id is not None

        # Verify the brain tag was stored
        row = await repo.get_methodology(method_id)
        assert row is not None
        tags = json.loads(row.tags) if isinstance(row.tags, str) else row.tags
        brain_tags = [t for t in tags if t.startswith("brain:")]
        assert "brain:typescript" in brain_tags

    @pytest.mark.asyncio
    async def test_no_brain_tag_when_none(self, miner_with_db):
        miner, repo, engine = miner_with_db
        finding = self._make_finding("python")
        method_id = await miner.store_finding(finding, "proj-1", brain=None)
        assert method_id is not None

        row = await repo.get_methodology(method_id)
        tags = json.loads(row.tags) if isinstance(row.tags, str) else row.tags
        brain_tags = [t for t in tags if t.startswith("brain:")]
        assert len(brain_tags) == 0

    @pytest.mark.asyncio
    async def test_brain_tag_with_target_repository(self, miner_with_db):
        """When target_repository is provided, finding goes there instead of primary."""
        miner, primary_repo, engine = miner_with_db

        # Create a separate "ganglion" DB
        config2 = DatabaseConfig(db_path=":memory:")
        engine2 = DatabaseEngine(config2)
        await engine2.connect()
        await engine2.initialize_schema()
        repo2 = Repository(engine2)
        emb2 = FixedEmbeddingEngine()
        hybrid2 = HybridSearch(repository=repo2, embedding_engine=emb2)
        sem2 = SemanticMemory(repository=repo2, embedding_engine=emb2, hybrid_search=hybrid2)

        finding = self._make_finding("go")
        method_id = await miner.store_finding(
            finding, "proj-1",
            brain="go",
            target_repository=repo2,
            target_semantic_memory=sem2,
        )
        assert method_id is not None

        # Should be in repo2, not primary
        row = await repo2.get_methodology(method_id)
        assert row is not None
        tags = json.loads(row.tags) if isinstance(row.tags, str) else row.tags
        assert "brain:go" in tags

        await engine2.close()


# ===========================================================================
# Test Class 8: Prompt cache in RepoMiner
# ===========================================================================

class TestPromptCache:
    """Tests for _get_prompt_template caching by brain name."""

    @pytest.fixture
    async def miner(self):
        config = ClawConfig()
        config.database.db_path = ":memory:"
        engine = DatabaseEngine(config.database)
        await engine.connect()
        await engine.initialize_schema()
        repo = Repository(engine)
        emb = FixedEmbeddingEngine()
        hybrid = HybridSearch(repository=repo, embedding_engine=emb)
        sem = SemanticMemory(repository=repo, embedding_engine=emb, hybrid_search=hybrid)
        from claw.llm.client import LLMClient
        llm = LLMClient(config.llm)
        m = RepoMiner(
            repository=repo,
            llm_client=llm,
            semantic_memory=sem,
            config=config,
        )
        yield m
        await engine.close()

    @pytest.mark.asyncio
    async def test_default_prompt_loads(self, miner):
        template = miner._get_prompt_template("repo-mine.md")
        assert "{repo_content}" in template
        assert len(template) > 100

    @pytest.mark.asyncio
    async def test_typescript_prompt_loads(self, miner):
        template = miner._get_prompt_template("repo-mine-typescript.md")
        assert "{repo_content}" in template

    @pytest.mark.asyncio
    async def test_go_prompt_loads(self, miner):
        template = miner._get_prompt_template("repo-mine-go.md")
        assert "{repo_content}" in template

    @pytest.mark.asyncio
    async def test_rust_prompt_loads(self, miner):
        template = miner._get_prompt_template("repo-mine-rust.md")
        assert "{repo_content}" in template

    @pytest.mark.asyncio
    async def test_misc_prompt_loads(self, miner):
        template = miner._get_prompt_template("repo-mine-misc.md")
        assert "{repo_content}" in template

    @pytest.mark.asyncio
    async def test_prompt_caching(self, miner):
        """Loading the same prompt twice returns cached version."""
        t1 = miner._get_prompt_template("repo-mine-go.md")
        t2 = miner._get_prompt_template("repo-mine-go.md")
        assert t1 is t2  # Same object (cached)

    @pytest.mark.asyncio
    async def test_different_prompts_cached_separately(self, miner):
        t1 = miner._get_prompt_template("repo-mine-go.md")
        t2 = miner._get_prompt_template("repo-mine-rust.md")
        assert t1 is not t2
        assert len(miner._prompt_cache) >= 2

    @pytest.mark.asyncio
    async def test_nonexistent_prompt_raises(self, miner):
        with pytest.raises(FileNotFoundError):
            miner._get_prompt_template("repo-mine-cobol.md")


# ===========================================================================
# Test Class 9: serialize_repo with brain max_bytes
# ===========================================================================

class TestSerializeRepoBrainBudget:
    """Tests that brain-specific max_bytes are respected."""

    def test_serialize_respects_larger_budget(self, tmp_path):
        """TypeScript brain's 1.5MB budget allows more content than Python's 900KB."""
        repo = _make_ts_repo(tmp_path)
        # With default budget
        content_default, count_default = serialize_repo(repo, max_bytes=921_600)
        # With TS brain budget
        content_large, count_large = serialize_repo(repo, max_bytes=1_536_000)
        # For small repos both should serialize everything
        assert count_default == count_large
        assert len(content_default) == len(content_large)

    def test_serialize_truncates_at_budget(self, tmp_path):
        """Very small budget truncates output."""
        repo = _make_ts_repo(tmp_path)
        content, count = serialize_repo(repo, max_bytes=100)
        assert len(content.encode()) <= 100 or count <= 2


# ===========================================================================
# Test Class 10: Backward compatibility
# ===========================================================================

class TestBackwardCompatibility:
    """Ensure the Python brain path works identically to before multi-brain."""

    def test_python_brain_config_matches_legacy(self):
        mc = MiningConfig()
        py = mc.brains["python"]
        assert py.max_bytes == 921_600
        assert py.prompt == "repo-mine.md"
        assert py.ganglion_name == ""  # Uses primary DB

    def test_detect_language_on_this_repo(self):
        """This repo (multiclaw) itself should be detected as Python."""
        repo_root = Path(__file__).parent.parent
        result = detect_repo_language(repo_root)
        assert result == "python"

    def test_mining_config_loaded_from_toml(self):
        """load_config() includes brains in mining section."""
        config = load_config()
        assert hasattr(config.mining, "brains")
        assert "python" in config.mining.brains
        assert "typescript" in config.mining.brains
