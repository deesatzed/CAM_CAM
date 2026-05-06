"""Deterministic auto-fix engine for shallow model bugs.

Applies regex/string transforms to workspace files to fix common
LLM-generated code errors (missing imports, leaked FIM tokens, wrong
function calls, relative import issues) WITHOUT consuming an LLM
correction attempt.

Defense layer 1 in the graduated failure learning system:
  1. Auto-fix (deterministic, no LLM) — this module
  2. ErrorKB-enriched correction — model gets known fix hints
  3. RL escalation — agent rotation or human review
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("claw.memory.auto_fix")

# Directories to skip when scanning workspace files.
_EXCLUDED_DIRS = frozenset({
    "node_modules", ".git", "__pycache__", "venv", ".venv",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".eggs", "*.egg-info",
})

# LLM special tokens — mirrored from cycle.py for standalone use.
_LLM_SPECIAL_TOKENS = re.compile(
    r"</?(?:fim-(?:prefix|middle|suffix)|fim_(?:prefix|middle|suffix)|"
    r"\|fim_(?:prefix|middle|suffix)\|"
    r"|endoftext|pad|unk|mask|sep|cls|bos|eos)>",
    re.IGNORECASE,
)


@dataclass
class AutoFixRule:
    """A single deterministic fix rule."""
    name: str
    description: str
    category: str
    # Regex pattern matched against error output / violation text
    error_pattern: re.Pattern[str]
    # Glob pattern for files to scan (e.g. "*.py", "test_*.py")
    file_glob: str
    # Fix function: (file_path, file_content, error_text) -> (new_content, description) or None
    fix_fn: Callable[[Path, str, str], Optional[tuple[str, str]]]


@dataclass
class AutoFixWorkspaceRule:
    """A workspace-level fix rule (operates on the workspace root, not individual files)."""
    name: str
    description: str
    category: str
    # Regex pattern matched against error output / violation text
    error_pattern: re.Pattern[str]
    # Fix function: (workspace_path, error_text) -> (list[created_files], description) or None
    fix_fn: Callable[[Path, str], Optional[tuple[list[str], str]]]


@dataclass
class AutoFixResult:
    """Result of running the auto-fix engine on a workspace."""
    fixes_applied: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)


class AutoFixEngine:
    """Registry and executor for deterministic auto-fix rules."""

    def __init__(self) -> None:
        self._rules: list[AutoFixRule] = []
        self._workspace_rules: list[AutoFixWorkspaceRule] = []

    def register(self, rule: AutoFixRule) -> None:
        """Register a new file-level auto-fix rule."""
        self._rules.append(rule)

    def register_workspace_rule(self, rule: AutoFixWorkspaceRule) -> None:
        """Register a workspace-level auto-fix rule."""
        self._workspace_rules.append(rule)

    def try_auto_fix(
        self,
        workspace_dir: str,
        error_output: str,
        violations: Optional[list[dict[str, str]]] = None,
        *,
        proactive: bool = False,
    ) -> AutoFixResult:
        """Try to auto-fix workspace files based on error output.

        Scans matching files and applies each triggered rule.
        All fixes are deterministic string/regex transforms.

        Args:
            workspace_dir: Path to the workspace root.
            error_output: Combined stderr/stdout from failed verification.
            violations: Optional list of violation dicts from verifier.
            proactive: If True, skip error_pattern matching and try all rules
                       against all matching files. Used for pre-verification
                       cleanup (FIM tokens, missing imports).

        Returns:
            AutoFixResult with descriptions of fixes applied.
        """
        result = AutoFixResult()
        root = Path(workspace_dir)

        if not root.exists() or not root.is_dir():
            return result

        # Combine error text for pattern matching
        error_text = error_output or ""
        if violations:
            for v in violations:
                error_text += "\n" + v.get("detail", "")

        for rule in self._rules:
            if not proactive and not rule.error_pattern.search(error_text):
                continue

            # Find matching files
            for fpath in self._iter_files(root, rule.file_glob):
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue

                fix_result = rule.fix_fn(fpath, content, error_text)
                if fix_result is None:
                    continue

                new_content, description = fix_result
                if new_content == content:
                    continue

                try:
                    fpath.write_text(new_content, encoding="utf-8")
                    fix_desc = f"{rule.name}: {description} [{fpath.name}]"
                    result.fixes_applied.append(fix_desc)
                    result.files_modified.append(str(fpath))
                    logger.info("Auto-fix applied: %s", fix_desc)
                except OSError as e:
                    logger.warning("Auto-fix write failed for %s: %s", fpath, e)

        # Workspace-level rules (operate on workspace root, not individual files)
        for ws_rule in self._workspace_rules:
            if not ws_rule.error_pattern.search(error_text):
                continue
            try:
                ws_result = ws_rule.fix_fn(root, error_text)
                if ws_result is None:
                    continue
                created_files, description = ws_result
                if created_files:
                    fix_desc = f"{ws_rule.name}: {description}"
                    result.fixes_applied.append(fix_desc)
                    result.files_modified.extend(created_files)
                    logger.info("Workspace auto-fix applied: %s", fix_desc)
            except Exception as e:
                logger.warning("Workspace auto-fix %s failed: %s", ws_rule.name, e)

        return result

    @staticmethod
    def _iter_files(root: Path, glob_pattern: str):
        """Iterate workspace files matching glob, skipping excluded dirs."""
        for fpath in root.rglob(glob_pattern):
            if any(part in _EXCLUDED_DIRS for part in fpath.parts):
                continue
            if fpath.is_file():
                yield fpath


# ---------------------------------------------------------------------------
# Seed fix rules
# ---------------------------------------------------------------------------

def _fix_missing_import_pytest(
    fpath: Path, content: str, error_text: str,
) -> Optional[tuple[str, str]]:
    """Add 'import pytest' to test files that use pytest but don't import it."""
    # Only apply to test files
    if not fpath.name.startswith("test_") and not fpath.name.endswith("_test.py"):
        return None

    # Check if file uses pytest but doesn't import it
    if "import pytest" in content:
        return None

    # Check if file actually references pytest
    if not re.search(r'\bpytest\b', content):
        return None

    # Add import after any existing imports, or at the top.
    # Must handle multi-line imports: from X import (\n    a,\n    b,\n)
    lines = content.split("\n")
    insert_idx = 0
    in_multiline_import = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Track multi-line import blocks
        if in_multiline_import:
            if ")" in stripped:
                in_multiline_import = False
                insert_idx = i + 1
            continue

        # Skip past docstrings, comments, and existing imports
        if stripped.startswith(("import ", "from ", "#", '"""', "'''", '"""')):
            if "(" in stripped and ")" not in stripped:
                in_multiline_import = True
            insert_idx = i + 1
        elif stripped.startswith(("def ", "class ")) and insert_idx > 0:
            break

    lines.insert(insert_idx, "import pytest")
    return "\n".join(lines), "added missing 'import pytest'"


def _fix_fim_token_leakage(
    fpath: Path, content: str, error_text: str,
) -> Optional[tuple[str, str]]:
    """Strip FIM/special LLM tokens from Python files."""
    if not _LLM_SPECIAL_TOKENS.search(content):
        return None

    cleaned = _LLM_SPECIAL_TOKENS.sub("", content)

    # Also clean up any resulting empty lines from token removal
    # (don't collapse all blank lines, just obvious artifacts)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

    return cleaned, "stripped leaked FIM/special tokens"


def _fix_callable_vs_isfunction(
    fpath: Path, content: str, error_text: str,
) -> Optional[tuple[str, str]]:
    """Replace inspect.isfunction() with callable() for broader compatibility."""
    if "inspect.isfunction(" not in content:
        return None

    new_content = content.replace("inspect.isfunction(", "callable(")

    # Remove unused inspect import if no other inspect.* usage remains
    if "inspect." not in new_content:
        new_content = re.sub(
            r'^import inspect\s*\n', '', new_content, count=1, flags=re.MULTILINE,
        )

    return new_content, "replaced inspect.isfunction() with callable()"


def _fix_relative_import(
    fpath: Path, content: str, error_text: str,
) -> Optional[tuple[str, str]]:
    """Convert relative imports to absolute when they cause ImportError."""
    # Extract the failing module name from error text
    match = re.search(
        r"ImportError: attempted relative import (?:with no known parent package|"
        r"beyond top-level package)",
        error_text,
    )
    if not match:
        return None

    # Find relative imports in the file
    modified = False
    lines = content.split("\n")
    new_lines = []

    for line in lines:
        # Match "from . import X" or "from .module import X"
        rel_match = re.match(r'^(\s*)from\s+\.(\w*)\s+import\s+(.+)$', line)
        if rel_match:
            indent = rel_match.group(1)
            module = rel_match.group(2)
            imports = rel_match.group(3)
            if module:
                new_lines.append(f"{indent}from {module} import {imports}")
            else:
                # "from . import X" — can't easily resolve without package context
                # Leave as-is and let correction loop handle it
                new_lines.append(line)
            modified = True
        else:
            new_lines.append(line)

    if not modified:
        return None

    return "\n".join(new_lines), "converted relative imports to absolute"


def _fix_missing_init_for_local_package(
    workspace: Path, error_text: str,
) -> Optional[tuple[list[str], str]]:
    """Create __init__.py files for local packages missing them.

    Extracts module name from ModuleNotFoundError, checks if a matching
    directory exists in the workspace without __init__.py, and creates it.
    """
    match = re.search(
        r"ModuleNotFoundError: No module named ['\"](\w+)['\"]",
        error_text,
    )
    if not match:
        return None

    module_name = match.group(1)
    pkg_dir = workspace / module_name

    if not pkg_dir.is_dir():
        return None

    # Check if __init__.py already exists
    init_file = pkg_dir / "__init__.py"
    if init_file.exists():
        return None

    created: list[str] = []

    # Create __init__.py in the package root
    try:
        init_file.write_text("", encoding="utf-8")
        created.append(str(init_file))
    except OSError:
        return None

    # Also create __init__.py in subdirectories that contain .py files
    for subdir in pkg_dir.rglob("*"):
        if not subdir.is_dir():
            continue
        if any(part in _EXCLUDED_DIRS for part in subdir.parts):
            continue
        has_py = any(f.suffix == ".py" for f in subdir.iterdir() if f.is_file())
        sub_init = subdir / "__init__.py"
        if has_py and not sub_init.exists():
            try:
                sub_init.write_text("", encoding="utf-8")
                created.append(str(sub_init))
            except OSError:
                pass

    if not created:
        return None

    return created, f"created __init__.py for local package '{module_name}' ({len(created)} files)"


def build_default_engine() -> AutoFixEngine:
    """Create an AutoFixEngine with the 4 seed rules + workspace rules.

    Returns a ready-to-use engine with rules for:
    - missing_import_pytest: NameError for pytest in test files
    - fim_token_leakage: SyntaxError from leaked FIM tokens
    - callable_vs_isfunction: TypeError from inspect.isfunction
    - relative_import_fix: ImportError from relative imports
    - missing_init_py: ModuleNotFoundError for local packages (workspace rule)
    """
    engine = AutoFixEngine()

    engine.register(AutoFixRule(
        name="missing_import_pytest",
        description="Add 'import pytest' to test files missing it",
        category="import_error",
        error_pattern=re.compile(
            r"NameError.*pytest|name 'pytest' is not defined",
            re.IGNORECASE,
        ),
        file_glob="*.py",
        fix_fn=_fix_missing_import_pytest,
    ))

    engine.register(AutoFixRule(
        name="fim_token_leakage",
        description="Strip leaked FIM/special tokens from Python files",
        category="syntax_error",
        error_pattern=re.compile(
            r"SyntaxError|<fim[-_]|<endoftext>|<\|fim",
            re.IGNORECASE,
        ),
        file_glob="*.py",
        fix_fn=_fix_fim_token_leakage,
    ))

    engine.register(AutoFixRule(
        name="callable_vs_isfunction",
        description="Replace inspect.isfunction() with callable()",
        category="type_error",
        error_pattern=re.compile(
            r"TypeError.*isfunction|AssertionError.*isfunction|assert.*isfunction|inspect\.isfunction",
            re.IGNORECASE,
        ),
        file_glob="*.py",
        fix_fn=_fix_callable_vs_isfunction,
    ))

    engine.register(AutoFixRule(
        name="relative_import_fix",
        description="Convert relative imports to absolute",
        category="import_error",
        error_pattern=re.compile(
            r"ImportError.*relative import",
            re.IGNORECASE,
        ),
        file_glob="*.py",
        fix_fn=_fix_relative_import,
    ))

    # Workspace-level rules
    engine.register_workspace_rule(AutoFixWorkspaceRule(
        name="missing_init_py",
        description="Create __init__.py for local packages missing it",
        category="import_error",
        error_pattern=re.compile(
            r"ModuleNotFoundError: No module named",
            re.IGNORECASE,
        ),
        fix_fn=_fix_missing_init_for_local_package,
    ))

    return engine
