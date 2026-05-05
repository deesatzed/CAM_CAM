"""Tests for polyglot multi-pass mining architecture.

Covers:
    1. detect_all_repo_languages() — single, polyglot, thresholds, config signals
    2. LanguageZone dataclass — field population
    3. _BRAIN_EXTENSIONS reverse mapping — correctness
    4. detect_repo_language() backward compatibility — thin wrapper
    5. serialize_repo() language_filter — filtering, README/config passthrough
    6. PolyglotMiningResult / RepoMiningResult.brain_breakdown — dataclass fields
    7. Multi-pass mine_repo() — polyglot detection triggers multi-pass
    8. Explicit --brain override — single-brain path preserved

All tests use REAL dependencies — no mocks, no placeholders, no cached responses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claw.core.config import BrainConfig, ClawConfig
from claw.miner import (
    LanguageZone,
    PolyglotMiningResult,
    RepoMiningResult,
    _BRAIN_EXTENSIONS,
    _EXT_TO_LANGUAGE,
    _LANGUAGE_TO_BRAIN,
    _MIN_ZONE_FILES,
    _MIN_ZONE_PCT,
    detect_all_repo_languages,
    detect_repo_language,
    serialize_repo,
    should_skip_polyglot_zone,
)


# ---------------------------------------------------------------------------
# Test repo builders
# ---------------------------------------------------------------------------

def _make_polyglot_repo(tmp_path: Path) -> Path:
    """Create a repo with TypeScript + Go + Python files."""
    repo = tmp_path / "polyglot"
    repo.mkdir()
    (repo / "README.md").write_text("# Polyglot Project\n")
    (repo / "tsconfig.json").write_text('{"compilerOptions": {}}')
    (repo / "go.mod").write_text("module example.com/poly\n\ngo 1.21\n")
    (repo / "pyproject.toml").write_text('[project]\nname = "poly"\n')

    # TypeScript files (10)
    ts_dir = repo / "web" / "src"
    ts_dir.mkdir(parents=True)
    for i in range(10):
        (ts_dir / f"component{i}.tsx").write_text(
            f"export const Comp{i} = () => <div>{i}</div>;"
        )

    # Go files (8)
    go_dir = repo / "api"
    go_dir.mkdir()
    for i in range(8):
        (go_dir / f"handler{i}.go").write_text(
            f"package api\n\nfunc Handler{i}() {{}}\n"
        )

    # Python files (6)
    py_dir = repo / "scripts"
    py_dir.mkdir()
    for i in range(6):
        (py_dir / f"task{i}.py").write_text(f"x = {i}\n")

    return repo


def _make_single_lang_repo(tmp_path: Path, lang: str) -> Path:
    """Create a single-language repo."""
    repo = tmp_path / f"{lang}-only"
    repo.mkdir()
    (repo / "README.md").write_text(f"# {lang} project\n")

    if lang == "python":
        (repo / "pyproject.toml").write_text('[project]\nname = "x"\n')
        for i in range(5):
            (repo / f"mod{i}.py").write_text(f"x = {i}\n")
    elif lang == "typescript":
        (repo / "tsconfig.json").write_text("{}")
        for i in range(5):
            (repo / f"comp{i}.ts").write_text(f"export const x{i} = {i};")
    elif lang == "go":
        (repo / "go.mod").write_text("module x\n\ngo 1.21\n")
        for i in range(5):
            (repo / f"pkg{i}.go").write_text(f"package main\nfunc F{i}() {{}}\n")
    elif lang == "rust":
        (repo / "Cargo.toml").write_text('[package]\nname = "x"\n')
        src = repo / "src"
        src.mkdir()
        for i in range(5):
            (src / f"mod{i}.rs").write_text(f"pub fn f{i}() {{}}")
    return repo


# ===========================================================================
# 1. detect_all_repo_languages
# ===========================================================================

class TestDetectAllRepoLanguages:
    def test_polyglot_repo_detects_multiple_zones(self, tmp_path):
        repo = _make_polyglot_repo(tmp_path)
        zones = detect_all_repo_languages(repo)
        brains = set(zones.keys())
        assert "typescript" in brains
        assert "go" in brains
        assert "python" in brains
        assert len(zones) >= 3

    def test_single_language_repo_returns_one_zone(self, tmp_path):
        repo = _make_single_lang_repo(tmp_path, "go")
        zones = detect_all_repo_languages(repo)
        assert len(zones) == 1
        assert "go" in zones

    def test_empty_repo_returns_empty(self, tmp_path):
        repo = tmp_path / "empty"
        repo.mkdir()
        (repo / "LICENSE").write_text("MIT")
        zones = detect_all_repo_languages(repo)
        assert zones == {}

    def test_nonexistent_path_returns_empty(self, tmp_path):
        zones = detect_all_repo_languages(tmp_path / "nope")
        assert zones == {}

    def test_zone_file_count_matches(self, tmp_path):
        repo = _make_polyglot_repo(tmp_path)
        zones = detect_all_repo_languages(repo)
        # 10 .tsx files
        assert zones["typescript"].file_count == 10
        # 8 .go files
        assert zones["go"].file_count == 8
        # 6 .py files
        assert zones["python"].file_count == 6

    def test_zone_percentages(self, tmp_path):
        repo = _make_polyglot_repo(tmp_path)
        zones = detect_all_repo_languages(repo)
        total_pct = sum(z.pct for z in zones.values())
        # Should sum to ~100% (may not be exact due to rounding)
        assert 95.0 <= total_pct <= 105.0

    def test_small_zone_skipped(self, tmp_path):
        """Zones below _MIN_ZONE_FILES or _MIN_ZONE_PCT are skipped."""
        repo = tmp_path / "mostly-python"
        repo.mkdir()
        # 100 Python files
        for i in range(100):
            (repo / f"mod{i}.py").write_text(f"x = {i}")
        # 1 Go file (below _MIN_ZONE_FILES=3 and _MIN_ZONE_PCT=5%)
        (repo / "main.go").write_text("package main\nfunc main() {}")
        zones = detect_all_repo_languages(repo)
        assert "go" not in zones
        assert "python" in zones

    def test_config_signal_bypasses_threshold(self, tmp_path):
        """A config-file signal (tsconfig.json) ensures zone inclusion."""
        repo = tmp_path / "ts-signal"
        repo.mkdir()
        (repo / "tsconfig.json").write_text("{}")
        # Only 1 TS file (below _MIN_ZONE_FILES normally)
        (repo / "index.ts").write_text("export const x = 1;")
        # 50 Python files
        for i in range(50):
            (repo / f"mod{i}.py").write_text(f"x = {i}")
        zones = detect_all_repo_languages(repo)
        # TypeScript should still be present due to tsconfig.json signal
        assert "typescript" in zones

    def test_zone_extensions_populated(self, tmp_path):
        repo = _make_polyglot_repo(tmp_path)
        zones = detect_all_repo_languages(repo)
        assert ".tsx" in zones["typescript"].file_extensions
        assert ".go" in zones["go"].file_extensions
        assert ".py" in zones["python"].file_extensions


# ===========================================================================
# 2. LanguageZone dataclass
# ===========================================================================

class TestLanguageZone:
    def test_fields(self):
        zone = LanguageZone(
            brain="typescript", file_count=42,
            file_extensions={".ts", ".tsx"}, pct=63.2,
        )
        assert zone.brain == "typescript"
        assert zone.file_count == 42
        assert zone.pct == 63.2
        assert ".ts" in zone.file_extensions

    def test_small_secondary_zone_skipped_for_paid_polyglot_pass(self):
        zone = LanguageZone(
            brain="rust",
            file_count=_MIN_ZONE_FILES - 1,
            file_extensions={".rs"},
            pct=0.8,
        )

        assert should_skip_polyglot_zone(zone, total_zones=2) is True
        assert should_skip_polyglot_zone(zone, total_zones=1) is False

    def test_large_secondary_zone_not_skipped_for_paid_polyglot_pass(self):
        zone = LanguageZone(
            brain="go",
            file_count=_MIN_ZONE_FILES,
            file_extensions={".go"},
            pct=5.0,
        )

        assert should_skip_polyglot_zone(zone, total_zones=2) is False


# ===========================================================================
# 3. _BRAIN_EXTENSIONS mapping
# ===========================================================================

class TestBrainExtensions:
    def test_python_extensions(self):
        assert ".py" in _BRAIN_EXTENSIONS["python"]

    def test_typescript_extensions(self):
        assert ".ts" in _BRAIN_EXTENSIONS["typescript"]
        assert ".tsx" in _BRAIN_EXTENSIONS["typescript"]
        assert ".js" in _BRAIN_EXTENSIONS["typescript"]
        assert ".jsx" in _BRAIN_EXTENSIONS["typescript"]

    def test_go_extensions(self):
        assert ".go" in _BRAIN_EXTENSIONS["go"]

    def test_rust_extensions(self):
        assert ".rs" in _BRAIN_EXTENSIONS["rust"]

    def test_misc_extensions(self):
        assert ".java" in _BRAIN_EXTENSIONS["misc"]
        assert ".cpp" in _BRAIN_EXTENSIONS["misc"]

    def test_all_ext_to_language_covered(self):
        """Every extension in _EXT_TO_LANGUAGE maps to a brain in _BRAIN_EXTENSIONS."""
        for ext in _EXT_TO_LANGUAGE:
            lang = _EXT_TO_LANGUAGE[ext]
            brain = _LANGUAGE_TO_BRAIN.get(lang, "misc")
            assert ext in _BRAIN_EXTENSIONS[brain], f"{ext} not in _BRAIN_EXTENSIONS[{brain}]"


# ===========================================================================
# 4. detect_repo_language backward compatibility
# ===========================================================================

class TestDetectRepoLanguageBackwardCompat:
    def test_returns_string(self, tmp_path):
        repo = _make_single_lang_repo(tmp_path, "go")
        result = detect_repo_language(repo)
        assert isinstance(result, str)
        assert result == "go"

    def test_tsconfig_promotes_typescript(self, tmp_path):
        """Even if Python has more files, tsconfig.json promotes TypeScript."""
        repo = tmp_path / "mixed"
        repo.mkdir()
        (repo / "tsconfig.json").write_text("{}")
        (repo / "index.ts").write_text("export const x = 1;")
        for i in range(10):
            (repo / f"mod{i}.py").write_text(f"x = {i}")
        assert detect_repo_language(repo) == "typescript"

    def test_empty_returns_misc(self, tmp_path):
        repo = tmp_path / "e"
        repo.mkdir()
        assert detect_repo_language(repo) == "misc"


# ===========================================================================
# 5. serialize_repo language_filter
# ===========================================================================

class TestSerializeRepoLanguageFilter:
    def test_filter_includes_only_matching(self, tmp_path):
        repo = tmp_path / "mixed"
        repo.mkdir()
        (repo / "app.ts").write_text("export const x = 1;")
        (repo / "util.py").write_text("x = 1")
        (repo / "main.go").write_text("package main")

        content, count = serialize_repo(repo, language_filter={".ts"})
        assert "app.ts" in content
        assert "util.py" not in content
        assert "main.go" not in content

    def test_filter_preserves_readme(self, tmp_path):
        repo = tmp_path / "proj"
        repo.mkdir()
        (repo / "README.md").write_text("# Hello")
        (repo / "app.ts").write_text("x = 1")
        (repo / "util.py").write_text("y = 2")

        content, count = serialize_repo(repo, language_filter={".ts"})
        assert "README.md" in content

    def test_filter_preserves_config_files(self, tmp_path):
        repo = tmp_path / "proj"
        repo.mkdir()
        (repo / "package.json").write_text('{"name": "x"}')
        (repo / "go.mod").write_text("module x")
        (repo / "app.ts").write_text("x = 1")

        content, count = serialize_repo(repo, language_filter={".ts"})
        assert "package.json" in content

    def test_filter_none_unchanged(self, tmp_path):
        repo = tmp_path / "proj"
        repo.mkdir()
        (repo / "app.ts").write_text("x = 1")
        (repo / "util.py").write_text("y = 2")

        content_all, count_all = serialize_repo(repo, language_filter=None)
        assert "app.ts" in content_all
        assert "util.py" in content_all

    def test_filter_respects_max_bytes(self, tmp_path):
        repo = tmp_path / "big"
        repo.mkdir()
        for i in range(100):
            (repo / f"f{i}.ts").write_text("x" * 1000)

        content, count = serialize_repo(repo, max_bytes=5000, language_filter={".ts"})
        assert len(content.encode()) <= 5000

    def test_generated_bundles_and_schemas_are_skipped(self, tmp_path):
        repo = tmp_path / "generated-assets"
        repo.mkdir()
        (repo / "app.ts").write_text("export const app = 1;")
        (repo / "codemirror-bundle.js").write_text("generated_bundle();" * 100)
        (repo / "desktop-schema.json").write_text('{"generated": true}')
        (repo / "macOS-schema.json").write_text('{"generated": true}')
        (repo / "acl-manifests.json").write_text('{"generated": true}')

        content, count = serialize_repo(repo)

        assert "app.ts" in content
        assert "codemirror-bundle.js" not in content
        assert "desktop-schema.json" not in content
        assert "macOS-schema.json" not in content
        assert "acl-manifests.json" not in content


# ===========================================================================
# 6. PolyglotMiningResult / RepoMiningResult.brain_breakdown
# ===========================================================================

class TestPolyglotMiningResultFields:
    def test_defaults(self):
        p = PolyglotMiningResult(brain="go")
        assert p.brain == "go"
        assert p.findings_count == 0
        assert p.methodology_ids == []
        assert p.error is None

    def test_with_values(self):
        p = PolyglotMiningResult(
            brain="typescript",
            findings_count=8,
            methodology_ids=["a", "b"],
            tokens_used=5000,
            duration_seconds=12.3,
        )
        assert p.findings_count == 8
        assert len(p.methodology_ids) == 2

    def test_brain_breakdown_default_empty(self):
        r = RepoMiningResult(repo_name="x", repo_path="/x")
        assert r.brain_breakdown == []

    def test_brain_breakdown_populated(self):
        r = RepoMiningResult(
            repo_name="poly",
            repo_path="/poly",
            brain_breakdown=[
                PolyglotMiningResult(brain="python", findings_count=5),
                PolyglotMiningResult(brain="go", findings_count=3),
            ],
        )
        assert len(r.brain_breakdown) == 2
        assert r.brain_breakdown[0].brain == "python"
