"""Tests for the deterministic auto-fix engine.

Covers all 4 seed rules and the engine's file-scanning logic.
Uses real temp directories — no mocks.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from claw.memory.auto_fix import (
    AutoFixEngine,
    AutoFixResult,
    AutoFixRule,
    AutoFixWorkspaceRule,
    build_default_engine,
    _fix_missing_import_pytest,
    _fix_fim_token_leakage,
    _fix_callable_vs_isfunction,
    _fix_relative_import,
    _fix_missing_init_for_local_package,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_file(tmpdir: Path, name: str, content: str) -> Path:
    """Write a file in tmpdir and return its path."""
    fpath = tmpdir / name
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text(content, encoding="utf-8")
    return fpath


# ---------------------------------------------------------------------------
# Test: build_default_engine returns an engine with 4 rules
# ---------------------------------------------------------------------------

def test_build_default_engine_has_four_rules():
    engine = build_default_engine()
    assert len(engine._rules) == 4
    names = {r.name for r in engine._rules}
    assert names == {
        "missing_import_pytest",
        "fim_token_leakage",
        "callable_vs_isfunction",
        "relative_import_fix",
    }
    # Plus 1 workspace rule
    assert len(engine._workspace_rules) == 1
    assert engine._workspace_rules[0].name == "missing_init_py"


# ---------------------------------------------------------------------------
# Test: missing_import_pytest rule
# ---------------------------------------------------------------------------

class TestMissingImportPytest:
    def test_adds_import_to_test_file(self, tmp_path):
        code = (
            "def test_something():\n"
            "    pytest.raises(ValueError)\n"
        )
        fpath = _write_file(tmp_path, "test_example.py", code)
        error = "NameError: name 'pytest' is not defined"

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)

        assert len(result.fixes_applied) == 1
        assert "import pytest" in result.fixes_applied[0]
        assert "import pytest" in fpath.read_text()

    def test_skips_if_already_imported(self, tmp_path):
        code = "import pytest\n\ndef test_foo():\n    pytest.raises(ValueError)\n"
        _write_file(tmp_path, "test_example.py", code)
        error = "NameError: name 'pytest' is not defined"

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)
        assert len(result.fixes_applied) == 0

    def test_skips_non_test_files(self, tmp_path):
        code = "def something():\n    pytest.raises(ValueError)\n"
        _write_file(tmp_path, "utils.py", code)
        error = "NameError: name 'pytest' is not defined"

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)
        assert len(result.fixes_applied) == 0

    def test_skips_if_no_pytest_reference(self, tmp_path):
        code = "def test_something():\n    assert True\n"
        _write_file(tmp_path, "test_example.py", code)
        error = "NameError: name 'pytest' is not defined"

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)
        assert len(result.fixes_applied) == 0

    def test_handles_multiline_imports(self, tmp_path):
        """Import should be placed AFTER multi-line from...import(...) blocks."""
        code = (
            "from __future__ import annotations\n"
            "\n"
            "import asyncio\n"
            "from io import StringIO\n"
            "\n"
            "from app.resilient import (\n"
            "    retry,\n"
            "    circuit_breaker,\n"
            ")\n"
            "\n"
            "\n"
            "def test_foo():\n"
            "    pytest.raises(ValueError)\n"
        )
        fpath = _write_file(tmp_path, "test_example.py", code)
        error = "NameError: name 'pytest' is not defined"

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)

        assert len(result.fixes_applied) == 1
        fixed = fpath.read_text()
        assert "import pytest" in fixed
        # Verify it's a valid Python file (no SyntaxError)
        import ast
        ast.parse(fixed)
        # Verify import pytest is NOT inside the parenthesized import
        lines = fixed.split("\n")
        pytest_line = next(i for i, l in enumerate(lines) if l.strip() == "import pytest")
        paren_close = next(i for i, l in enumerate(lines) if l.strip() == ")")
        assert pytest_line > paren_close


# ---------------------------------------------------------------------------
# Test: fim_token_leakage rule
# ---------------------------------------------------------------------------

class TestFimTokenLeakage:
    def test_strips_fim_tokens(self, tmp_path):
        code = 'def hello():\n    <fim-middle>return "world"\n'
        fpath = _write_file(tmp_path, "module.py", code)
        error = "SyntaxError: invalid syntax"

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)

        assert len(result.fixes_applied) == 1
        assert "FIM" in result.fixes_applied[0] or "token" in result.fixes_applied[0].lower()
        cleaned = fpath.read_text()
        assert "<fim-middle>" not in cleaned
        assert 'return "world"' in cleaned

    def test_strips_multiple_token_types(self, tmp_path):
        code = '<fim-prefix>def hello():<fim-suffix>\n    <|fim_middle|>return 42\n<endoftext>'
        fpath = _write_file(tmp_path, "module.py", code)
        error = "SyntaxError: unexpected EOF"

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)

        assert len(result.fixes_applied) >= 1
        cleaned = fpath.read_text()
        assert "<fim-prefix>" not in cleaned
        assert "<fim-suffix>" not in cleaned
        assert "<|fim_middle|>" not in cleaned
        assert "<endoftext>" not in cleaned

    def test_no_op_if_no_tokens(self, tmp_path):
        code = "def hello():\n    return 42\n"
        _write_file(tmp_path, "module.py", code)
        error = "SyntaxError: invalid syntax"

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)
        assert len(result.fixes_applied) == 0


# ---------------------------------------------------------------------------
# Test: callable_vs_isfunction rule
# ---------------------------------------------------------------------------

class TestCallableVsIsfunction:
    def test_replaces_isfunction(self, tmp_path):
        code = "import inspect\n\nif inspect.isfunction(obj):\n    obj()\n"
        fpath = _write_file(tmp_path, "checker.py", code)
        error = "TypeError: isfunction() argument is not a Python function"

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)

        assert len(result.fixes_applied) == 1
        cleaned = fpath.read_text()
        assert "callable(obj)" in cleaned
        assert "inspect.isfunction" not in cleaned

    def test_removes_unused_inspect_import(self, tmp_path):
        code = "import inspect\n\nif inspect.isfunction(obj):\n    pass\n"
        fpath = _write_file(tmp_path, "checker.py", code)
        error = "TypeError: isfunction()"

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)

        cleaned = fpath.read_text()
        assert "import inspect" not in cleaned

    def test_keeps_inspect_if_still_used(self, tmp_path):
        code = "import inspect\n\nif inspect.isfunction(obj):\n    inspect.getmodule(obj)\n"
        fpath = _write_file(tmp_path, "checker.py", code)
        error = "TypeError: isfunction()"

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)

        cleaned = fpath.read_text()
        assert "import inspect" in cleaned
        assert "inspect.getmodule" in cleaned


# ---------------------------------------------------------------------------
# Test: relative_import_fix rule
# ---------------------------------------------------------------------------

class TestRelativeImportFix:
    def test_converts_relative_to_absolute(self, tmp_path):
        code = "from .utils import helper\n\ndef main():\n    helper()\n"
        fpath = _write_file(tmp_path, "app.py", code)
        error = "ImportError: attempted relative import with no known parent package"

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)

        assert len(result.fixes_applied) == 1
        cleaned = fpath.read_text()
        assert "from utils import helper" in cleaned
        assert "from .utils" not in cleaned

    def test_no_match_if_different_error(self, tmp_path):
        code = "from .utils import helper\n"
        _write_file(tmp_path, "app.py", code)
        error = "ImportError: No module named 'nonexistent'"

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)
        assert len(result.fixes_applied) == 0


# ---------------------------------------------------------------------------
# Test: engine skips excluded directories
# ---------------------------------------------------------------------------

class TestExcludedDirs:
    def test_skips_node_modules(self, tmp_path):
        code = 'def hello():\n    <fim-middle>return "world"\n'
        _write_file(tmp_path / "node_modules" / "pkg", "module.py", code)
        error = "SyntaxError: invalid syntax"

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)
        assert len(result.fixes_applied) == 0

    def test_skips_pycache(self, tmp_path):
        code = 'def hello():\n    <fim-middle>return "world"\n'
        _write_file(tmp_path / "__pycache__", "module.py", code)
        error = "SyntaxError: invalid syntax"

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)
        assert len(result.fixes_applied) == 0


# ---------------------------------------------------------------------------
# Test: engine handles empty/missing workspace
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_nonexistent_workspace(self):
        engine = build_default_engine()
        result = engine.try_auto_fix("/nonexistent/path", "SyntaxError")
        assert len(result.fixes_applied) == 0
        assert len(result.files_modified) == 0

    def test_empty_workspace(self, tmp_path):
        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), "SyntaxError")
        assert len(result.fixes_applied) == 0

    def test_empty_error_text(self, tmp_path):
        code = 'def hello():\n    <fim-middle>return "world"\n'
        _write_file(tmp_path, "module.py", code)

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), "")
        assert len(result.fixes_applied) == 0

    def test_multiple_rules_can_fire(self, tmp_path):
        """Both FIM and missing pytest can fire on the same workspace."""
        test_code = "def test_foo():\n    pytest.raises(ValueError)\n"
        mod_code = 'def bar():\n    <fim-middle>return 1\n'
        _write_file(tmp_path, "test_example.py", test_code)
        _write_file(tmp_path, "module.py", mod_code)
        error = "NameError: name 'pytest' is not defined\nSyntaxError: invalid syntax"

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)

        assert len(result.fixes_applied) == 2


# ---------------------------------------------------------------------------
# Test: AutoFixResult dataclass
# ---------------------------------------------------------------------------

def test_auto_fix_result_defaults():
    result = AutoFixResult()
    assert result.fixes_applied == []
    assert result.files_modified == []


# ---------------------------------------------------------------------------
# Test: individual fix functions directly
# ---------------------------------------------------------------------------

class TestFixFunctionsDirect:
    def test_fix_missing_import_pytest_inserts_after_imports(self, tmp_path):
        code = "import os\nimport sys\n\ndef test_foo():\n    pytest.raises(ValueError)\n"
        fpath = tmp_path / "test_direct.py"
        fpath.write_text(code)

        result = _fix_missing_import_pytest(fpath, code, "")
        assert result is not None
        new_content, desc = result
        lines = new_content.split("\n")
        # import pytest should be after import sys
        assert lines[2] == "import pytest"

    def test_fix_fim_returns_none_if_clean(self, tmp_path):
        code = "def hello():\n    return 42\n"
        fpath = tmp_path / "clean.py"
        result = _fix_fim_token_leakage(fpath, code, "")
        assert result is None

    def test_fix_callable_returns_none_if_no_isfunction(self, tmp_path):
        code = "import inspect\nresult = inspect.getmembers(obj)\n"
        fpath = tmp_path / "other.py"
        result = _fix_callable_vs_isfunction(fpath, code, "")
        assert result is None

    def test_fix_relative_import_returns_none_if_no_relative(self, tmp_path):
        code = "from utils import helper\n"
        fpath = tmp_path / "abs.py"
        result = _fix_relative_import(fpath, code, "ImportError: attempted relative import with no known parent package")
        assert result is None


# ---------------------------------------------------------------------------
# Test: broadened callable_vs_isfunction pattern
# ---------------------------------------------------------------------------

class TestBroadenedIsfunctionPattern:
    def test_assertion_error_triggers_fix(self, tmp_path):
        code = "import inspect\n\nif inspect.isfunction(obj):\n    obj()\n"
        fpath = _write_file(tmp_path, "checker.py", code)
        error = "AssertionError: isfunction() check failed"

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)

        assert len(result.fixes_applied) == 1
        cleaned = fpath.read_text()
        assert "callable(obj)" in cleaned

    def test_assert_isfunction_triggers_fix(self, tmp_path):
        code = "import inspect\n\nassert inspect.isfunction(handler)\n"
        fpath = _write_file(tmp_path, "validator.py", code)
        error = "assert inspect.isfunction(handler)"

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)

        assert len(result.fixes_applied) == 1
        cleaned = fpath.read_text()
        assert "callable(handler)" in cleaned


# ---------------------------------------------------------------------------
# Test: missing_init_py workspace rule
# ---------------------------------------------------------------------------

class TestMissingInitPy:
    def test_creates_init_for_local_package(self, tmp_path):
        """When workspace has 'myapp/' dir with .py files but no __init__.py."""
        pkg_dir = tmp_path / "myapp"
        pkg_dir.mkdir()
        (pkg_dir / "main.py").write_text("print('hello')", encoding="utf-8")
        error = "ModuleNotFoundError: No module named 'myapp'"

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)

        assert len(result.fixes_applied) == 1
        assert "missing_init_py" in result.fixes_applied[0]
        assert (pkg_dir / "__init__.py").exists()

    def test_creates_init_in_subdirs(self, tmp_path):
        """Also creates __init__.py in subdirectories with .py files."""
        pkg_dir = tmp_path / "mylib"
        sub_dir = pkg_dir / "utils"
        sub_dir.mkdir(parents=True)
        (pkg_dir / "core.py").write_text("x = 1", encoding="utf-8")
        (sub_dir / "helpers.py").write_text("y = 2", encoding="utf-8")
        error = "ModuleNotFoundError: No module named 'mylib'"

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)

        assert len(result.fixes_applied) == 1
        assert (pkg_dir / "__init__.py").exists()
        assert (sub_dir / "__init__.py").exists()

    def test_no_op_if_init_exists(self, tmp_path):
        """No fix if __init__.py already exists."""
        pkg_dir = tmp_path / "myapp"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
        (pkg_dir / "main.py").write_text("print('hello')", encoding="utf-8")
        error = "ModuleNotFoundError: No module named 'myapp'"

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)
        assert len(result.fixes_applied) == 0

    def test_no_op_if_dir_not_found(self, tmp_path):
        """No fix if the module directory doesn't exist."""
        error = "ModuleNotFoundError: No module named 'nonexistent'"
        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), error)
        assert len(result.fixes_applied) == 0

    def test_direct_function_call(self, tmp_path):
        """Test _fix_missing_init_for_local_package directly."""
        pkg_dir = tmp_path / "myapp"
        pkg_dir.mkdir()
        (pkg_dir / "main.py").write_text("print('hello')", encoding="utf-8")

        result = _fix_missing_init_for_local_package(
            tmp_path, "ModuleNotFoundError: No module named 'myapp'"
        )
        assert result is not None
        created_files, desc = result
        assert len(created_files) >= 1
        assert "myapp" in desc


# ---------------------------------------------------------------------------
# Test: proactive mode (bypasses error_pattern matching)
# ---------------------------------------------------------------------------

class TestProactiveMode:
    """Proactive auto-fix runs all rules without error text."""

    def test_proactive_catches_fim_tokens(self, tmp_path):
        """FIM tokens are stripped even without error output."""
        code = "def foo():\n    <fim-middle>return 42\n"
        fpath = _write_file(tmp_path, "main.py", code)

        engine = build_default_engine()
        # With empty error_text and proactive=False, FIM rule won't fire
        result_reactive = engine.try_auto_fix(str(tmp_path), "")
        assert len(result_reactive.fixes_applied) == 0

        # Restore file
        fpath.write_text(code, encoding="utf-8")

        # With proactive=True, FIM rule fires without error text
        result_proactive = engine.try_auto_fix(str(tmp_path), "", proactive=True)
        assert len(result_proactive.fixes_applied) == 1
        assert "fim" in result_proactive.fixes_applied[0].lower()
        assert "<fim-middle>" not in fpath.read_text()

    def test_proactive_catches_missing_pytest_import(self, tmp_path):
        """Missing pytest import is caught proactively."""
        code = "def test_foo():\n    pytest.raises(ValueError)\n"
        fpath = _write_file(tmp_path, "test_example.py", code)

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), "", proactive=True)
        assert len(result.fixes_applied) >= 1
        assert "import pytest" in fpath.read_text()

    def test_proactive_skips_clean_files(self, tmp_path):
        """Clean files are not modified in proactive mode."""
        code = "import pytest\n\ndef test_foo():\n    assert True\n"
        _write_file(tmp_path, "test_clean.py", code)

        engine = build_default_engine()
        result = engine.try_auto_fix(str(tmp_path), "", proactive=True)
        assert len(result.fixes_applied) == 0
