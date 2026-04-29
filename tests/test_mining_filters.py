"""Tests for mining serialization filter gaps (skip patterns, data file gate, trivial repo gate).

Covers:
    1. _SKIP_FILENAMES catches lock files and LICENSE
    2. _SKIP_FILE_PATTERNS catches *.min.js, *_pb2.py, etc.
    3. Large data files (.json, .yaml, etc.) exceeding _MAX_DATA_FILE_BYTES are skipped
    4. Trivial repos (< 3 files or < 1024 bytes) trigger early-exit
    5. Normal code files still pass all filters

All tests use REAL filesystem fixtures via pytest tmp_path — no mocks.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

import pytest

from claw.miner import (
    _DATA_EXTENSIONS,
    _MAX_DATA_FILE_BYTES,
    _SKIP_FILE_PATTERNS,
    _SKIP_FILENAMES,
    serialize_repo,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a minimal repo tree under tmp_path and return root."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for relpath, content in files.items():
        fp = repo / relpath
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
    return repo


# ---------------------------------------------------------------------------
# 1. _SKIP_FILENAMES
# ---------------------------------------------------------------------------

class TestSkipFilenames:
    """Exact-match filename skip list catches lock files, LICENSE, etc."""

    @pytest.mark.parametrize("filename", [
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "Pipfile.lock",
        "poetry.lock",
        "composer.lock",
        "Gemfile.lock",
        "Cargo.lock",
        "LICENSE",
        "LICENSE.md",
        "LICENSE.txt",
        ".gitignore",
        ".editorconfig",
        "renovate.json",
        "dependabot.yml",
    ])
    def test_known_filenames_in_set(self, filename: str) -> None:
        assert filename in _SKIP_FILENAMES, f"{filename} should be in _SKIP_FILENAMES"

    def test_lock_file_excluded_from_serialize(self, tmp_path: Path) -> None:
        """package-lock.json should not appear in serialized output."""
        files = {
            "main.py": "def main(): pass\n",
            "utils.py": "def helper(): return 1\n",
            "app.py": "import main\nimport utils\n",
            "package-lock.json": '{"lockfileVersion": 3, "packages": {}}',
        }
        repo = _make_repo(tmp_path, files)
        content, count = serialize_repo(repo)
        assert "package-lock.json" not in content
        assert count == 3  # main.py, utils.py, app.py

    def test_license_excluded_from_serialize(self, tmp_path: Path) -> None:
        """LICENSE should not appear in serialized output."""
        files = {
            "main.py": "def main(): pass\n",
            "utils.py": "def helper(): return 1\n",
            "app.py": "import main\nimport utils\n",
            "LICENSE": "MIT License\nCopyright (c) 2024\n",
        }
        repo = _make_repo(tmp_path, files)
        content, count = serialize_repo(repo)
        assert "--- FILE: LICENSE ---" not in content
        assert count == 3


# ---------------------------------------------------------------------------
# 2. _SKIP_FILE_PATTERNS
# ---------------------------------------------------------------------------

class TestSkipFilePatterns:
    """fnmatch patterns catch minified bundles, protobuf generated, etc."""

    @pytest.mark.parametrize("filename,expected_match", [
        ("app.min.js", True),
        ("styles.min.css", True),
        ("vendor.bundle.js", True),
        ("main.chunk.js", True),
        ("app.js.map", True),
        ("styles.css.map", True),
        ("service_pb2.py", True),
        ("types.pb.go", True),
        ("api.pb.ts", True),
        ("schema.generated.ts", True),
        ("routes.auto.js", True),
        # Normal files should NOT match
        ("app.js", False),
        ("main.py", False),
        ("config.yaml", False),
    ])
    def test_pattern_matching(self, filename: str, expected_match: bool) -> None:
        matches = any(fnmatch.fnmatch(filename, pat) for pat in _SKIP_FILE_PATTERNS)
        assert matches == expected_match, (
            f"{filename}: expected match={expected_match}, got {matches}"
        )

    def test_minified_js_excluded_from_serialize(self, tmp_path: Path) -> None:
        """*.min.js files should not appear in serialized output."""
        files = {
            "main.py": "def main(): pass\n",
            "utils.py": "def helper(): return 1\n",
            "app.py": "import main\nimport utils\n",
            "vendor.min.js": "!function(e){e.x=1}(window);",
        }
        repo = _make_repo(tmp_path, files)
        content, count = serialize_repo(repo)
        assert "vendor.min.js" not in content
        assert count == 3

    def test_protobuf_excluded_from_serialize(self, tmp_path: Path) -> None:
        """*_pb2.py files should not appear in serialized output."""
        files = {
            "main.py": "def main(): pass\n",
            "utils.py": "def helper(): return 1\n",
            "app.py": "import main\nimport utils\n",
            "service_pb2.py": "# Generated by protobuf\nclass ServiceStub: pass\n",
        }
        repo = _make_repo(tmp_path, files)
        content, count = serialize_repo(repo)
        assert "service_pb2.py" not in content
        assert count == 3


# ---------------------------------------------------------------------------
# 3. Large data file gate
# ---------------------------------------------------------------------------

class TestLargeDataFileGate:
    """Data files (.json, .yaml, .sql, .csv) exceeding 200KB are skipped."""

    def test_data_extensions_defined(self) -> None:
        assert ".json" in _DATA_EXTENSIONS
        assert ".yaml" in _DATA_EXTENSIONS
        assert ".yml" in _DATA_EXTENSIONS
        assert ".sql" in _DATA_EXTENSIONS
        assert ".csv" in _DATA_EXTENSIONS

    def test_large_json_skipped(self, tmp_path: Path) -> None:
        """A .json file > 200KB should be excluded entirely."""
        big_json = '{"data": "' + "x" * (_MAX_DATA_FILE_BYTES + 1024) + '"}'
        files = {
            "main.py": "def main(): pass\n",
            "utils.py": "def helper(): return 1\n",
            "app.py": "import main\nimport utils\n",
            "fixtures.json": big_json,
        }
        repo = _make_repo(tmp_path, files)
        content, count = serialize_repo(repo)
        assert "fixtures.json" not in content
        assert count == 3

    def test_small_json_included(self, tmp_path: Path) -> None:
        """A small .json file should still be included."""
        files = {
            "main.py": "def main(): pass\n",
            "utils.py": "def helper(): return 1\n",
            "app.py": "import main\nimport utils\n",
            "config.json": '{"name": "test-project"}',
        }
        repo = _make_repo(tmp_path, files)
        content, count = serialize_repo(repo)
        assert "config.json" in content
        assert count == 4

    def test_large_yaml_skipped(self, tmp_path: Path) -> None:
        """A .yaml file > 200KB should be excluded."""
        big_yaml = "data: |\n" + "  line\n" * (_MAX_DATA_FILE_BYTES // 6 + 100)
        files = {
            "main.py": "def main(): pass\n",
            "utils.py": "def helper(): return 1\n",
            "app.py": "import main\nimport utils\n",
            "seed_data.yaml": big_yaml,
        }
        repo = _make_repo(tmp_path, files)
        content, count = serialize_repo(repo)
        assert "seed_data.yaml" not in content
        assert count == 3


# ---------------------------------------------------------------------------
# 4. Trivial repo early-exit
# ---------------------------------------------------------------------------

class TestTrivialRepoGate:
    """Repos with too few files or too little content are detected."""

    def test_serialize_two_files_returns_content(self, tmp_path: Path) -> None:
        """serialize_repo itself still works with <3 files — the gate is in
        _mine_single_brain, not serialize_repo. Here we just verify serialize
        correctly reports the count so the gate can act on it."""
        files = {
            "main.py": "print('hi')\n",
            "README.md": "# Tiny\n",
        }
        repo = _make_repo(tmp_path, files)
        content, count = serialize_repo(repo)
        assert count == 2  # gate in _mine_single_brain uses this

    def test_serialize_empty_repo(self, tmp_path: Path) -> None:
        """An empty repo returns 0 files."""
        repo = _make_repo(tmp_path, {})
        content, count = serialize_repo(repo)
        assert count == 0
        assert content == ""

    def test_serialize_one_tiny_file(self, tmp_path: Path) -> None:
        """A repo with 1 tiny file returns count=1 and minimal content."""
        files = {"x.py": "x=1\n"}
        repo = _make_repo(tmp_path, files)
        content, count = serialize_repo(repo)
        assert count == 1
        assert len(content.encode("utf-8")) < 1024


# ---------------------------------------------------------------------------
# 5. Normal code files pass all filters
# ---------------------------------------------------------------------------

class TestNormalFilesPass:
    """Regular source files are not affected by the new filters."""

    def test_python_files_included(self, tmp_path: Path) -> None:
        files = {
            "main.py": "def main(): pass\n",
            "utils.py": "def helper(): return 1\n",
            "tests/test_main.py": "def test_main(): assert True\n",
        }
        repo = _make_repo(tmp_path, files)
        content, count = serialize_repo(repo)
        assert count == 3
        assert "main.py" in content
        assert "utils.py" in content
        assert "test_main.py" in content

    def test_mixed_code_and_config(self, tmp_path: Path) -> None:
        """Code + small config files all pass through."""
        files = {
            "app.ts": "export const x = 1;\n",
            "lib.ts": "export function f() { return 2; }\n",
            "index.ts": "import { x } from './app';\n",
            "tsconfig.json": '{"compilerOptions": {"strict": true}}',
            "README.md": "# Project\nA description.\n",
        }
        repo = _make_repo(tmp_path, files)
        content, count = serialize_repo(repo)
        assert count == 5
        for name in ["app.ts", "lib.ts", "index.ts", "tsconfig.json", "README.md"]:
            assert name in content
