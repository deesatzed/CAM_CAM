"""CLAW Cycle — the core orchestration abstraction.

The Claw Cycle is a six-step loop: grab -> evaluate -> decide -> act -> verify -> learn
operating at four nested scales:

- MacroClaw (Fleet) — scans repo fleet, ranks by enhancement potential
- MesoClaw (Project) — runs evaluation battery on one repo, produces plan
- MicroClaw (Module) — takes one task, routes to agent, monitors/verifies.
  Includes an inner correction loop: if verification finds correctable failures
  (test failures, placeholder violations, drift), the workspace is restored and
  the agent is re-prompted with violation details. Up to max_correction_attempts
  retries before falling through to learn().
- NanoClaw (Self-improvement) — updates scores and routing after each task
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import json
import logging
import re
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from claw.core.factory import ClawContext
from claw.core.models import (
    ContextBrief,
    CorrectionFeedback,
    CycleResult,
    HypothesisEntry,
    HypothesisOutcome,
    MethodologyUsageEntry,
    Task,
    TaskContext,
    TaskOutcome,
    TaskStatus,
    VerificationResult,
)
from claw.llm.client import _parse_json_response
from claw.logging_config import set_context, clear_context

logger = logging.getLogger("claw.cycle")


# LLM special tokens that should never appear in generated source files.
_LLM_SPECIAL_TOKENS = re.compile(
    r"</?(?:fim-(?:prefix|middle|suffix)|fim_(?:prefix|middle|suffix)|"
    r"\|fim_(?:prefix|middle|suffix)\|"
    r"|endoftext|pad|unk|mask|sep|cls|bos|eos)>",
    re.IGNORECASE,
)


def _strip_llm_tokens(content: str) -> str:
    """Remove leaked LLM special tokens from generated file content."""
    return _LLM_SPECIAL_TOKENS.sub("", content)


def _resolve_workspace_dir(
    agents: dict[str, Any],
    agent_id: str,
    task_ctx: Any = None,
) -> Optional[str]:
    """Resolve workspace_dir from agent, task, then project context."""
    agent = agents.get(agent_id)
    ws = getattr(agent, "workspace_dir", None) if agent else None
    if ws:
        return ws

    if task_ctx is not None:
        task = getattr(task_ctx, "task", None)
        if task is not None:
            task_repo = getattr(task, "repo_path", None)
            if task_repo:
                return str(task_repo)
        project = getattr(task_ctx, "project", None)
        if project is not None:
            project_repo = getattr(project, "repo_path", None)
            if project_repo:
                return str(project_repo)

    logger.warning(
        "workspace_dir could not be resolved for agent '%s'; tests may be skipped",
        agent_id,
    )
    return None


def _snapshot_workspace(workspace_dir: Optional[str]) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    if not workspace_dir:
        return snapshot

    root = Path(workspace_dir)
    if not root.exists() or not root.is_dir():
        return snapshot

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if ".git" in rel.parts or "__pycache__" in rel.parts:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        snapshot[str(rel)] = hashlib.sha1(data).hexdigest()
    return snapshot


def _compute_workspace_change(before: dict[str, str], after: dict[str, str]) -> tuple[list[str], str]:
    changed_paths = sorted(set(before.keys()) | set(after.keys()))
    files_changed = [path for path in changed_paths if before.get(path) != after.get(path)]
    if not files_changed:
        return [], ""

    lines: list[str] = []
    for path in files_changed:
        if path not in before:
            lines.append(f"+++ {path}")
        elif path not in after:
            lines.append(f"--- {path}")
        else:
            lines.append(f"*** {path}")
    return files_changed, "\n".join(lines)


def _compute_content_diff(
    before: dict[str, bytes],
    workspace_dir: str,
    max_chars: int = 6000,
) -> str:
    """Compute a unified diff between snapshot content and current workspace.

    Returns a human-readable diff string showing exactly what the agent wrote,
    suitable for injection into correction feedback.  Capped at *max_chars* to
    avoid blowing up the prompt.
    """
    root = Path(workspace_dir)
    if not root.is_dir():
        return ""

    # Gather current workspace content
    after: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _is_excluded_path(rel):
            continue
        try:
            after[str(rel)] = path.read_bytes()
        except OSError:
            continue

    all_paths = sorted(set(before) | set(after))
    parts: list[str] = []
    total = 0

    for rel in all_paths:
        old_bytes = before.get(rel, b"")
        new_bytes = after.get(rel, b"")
        if old_bytes == new_bytes:
            continue

        # Decode as text (skip binary)
        try:
            old_text = old_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)
            new_text = new_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)
        except Exception:
            parts.append(f"--- {rel} (binary, skipped)\n")
            continue

        diff_lines = list(difflib.unified_diff(
            old_text, new_text,
            fromfile=f"a/{rel}", tofile=f"b/{rel}",
            lineterm="",
        ))
        if not diff_lines:
            continue

        chunk = "\n".join(diff_lines)
        if total + len(chunk) > max_chars:
            parts.append(f"... (diff truncated at {max_chars} chars)")
            break
        parts.append(chunk)
        total += len(chunk)

    return "\n".join(parts)


def _read_failing_test_files(
    test_output: str,
    workspace_dir: str,
    max_chars: int = 4000,
) -> str:
    """Extract test file paths from pytest output and read their content.

    Agents need to see the test they're supposed to make pass, not just the
    error message.  Parses paths like ``tests/test_foo.py::test_bar`` from
    pytest output.
    """
    root = Path(workspace_dir)
    # Match pytest node ids: path.py::test_name or FAILED path.py::test_name
    pattern = re.compile(r"([\w/._-]+\.py)::")
    seen: set[str] = set()
    parts: list[str] = []
    total = 0

    for m in pattern.finditer(test_output):
        rel = m.group(1)
        if rel in seen:
            continue
        seen.add(rel)
        fpath = root / rel
        if not fpath.is_file():
            continue
        try:
            content = fpath.read_text(errors="replace")
        except OSError:
            continue
        header = f"\n--- {rel} ---\n"
        if total + len(header) + len(content) > max_chars:
            parts.append(f"--- {rel} (skipped, would exceed {max_chars} char cap) ---")
            break
        parts.append(header + content)
        total += len(header) + len(content)

    return "".join(parts)


# Directories excluded from workspace snapshot/restore. These are either
# VCS internals, build caches, or installed dependency trees that should
# persist across correction attempts (otherwise auto-installed deps get
# wiped and the next attempt fails with the same env error).
_SNAPSHOT_EXCLUDE_DIRS = frozenset({
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "target",        # Rust/Cargo build dir
    "dist",
    "build",
    ".next",
    ".angular",
})


def _is_excluded_path(rel: Path) -> bool:
    """Check if a relative path falls under any excluded directory."""
    return any(part in _SNAPSHOT_EXCLUDE_DIRS for part in rel.parts)


# JSON files that agents commonly corrupt (double-escaping backslashes, etc.)
_CRITICAL_JSON_FILES = frozenset({
    "package.json",
    "package-lock.json",
    "tsconfig.json",
    "tsconfig.app.json",
    "tsconfig.spec.json",
    "angular.json",
    ".eslintrc.json",
    "composer.json",
})


def _validate_and_repair_json(
    workspace_dir: Optional[str],
    snapshot: dict[str, bytes],
) -> list[str]:
    """Validate critical JSON files after an agent edit; restore corrupted ones.

    Agents often double-escape backslash sequences (e.g. \\' → \\\\') which
    produces invalid JSON that causes EJSONPARSE cascading failures.  This
    function checks every JSON file in _CRITICAL_JSON_FILES that exists on
    disk.  If any fail ``json.loads()``, the original from *snapshot* is
    written back and the repair is logged.

    Returns a list of file names that were repaired (empty if none).
    """
    if not workspace_dir:
        return []

    root = Path(workspace_dir)
    repaired: list[str] = []

    for path in root.rglob("*.json"):
        rel = path.relative_to(root)
        if rel.name not in _CRITICAL_JSON_FILES:
            continue
        if _is_excluded_path(rel):
            continue

        try:
            raw = path.read_bytes()
        except OSError:
            continue

        try:
            json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            # File is corrupted — try to restore from snapshot
            rel_str = str(rel)
            if rel_str in snapshot:
                try:
                    path.write_bytes(snapshot[rel_str])
                    repaired.append(rel_str)
                    logger.warning(
                        "Repaired corrupted JSON: %s (restored from snapshot)",
                        rel_str,
                    )
                except OSError as e:
                    logger.error("Could not repair %s: %s", rel_str, e)
            else:
                logger.warning(
                    "Corrupted JSON detected but no snapshot to restore: %s",
                    rel_str,
                )

    return repaired


def _snapshot_workspace_content(workspace_dir: Optional[str]) -> dict[str, bytes]:
    """Snapshot workspace file CONTENTS (not just hashes) for restoration.

    Used by the correction loop to revert the workspace to its pre-attempt
    state before re-prompting the agent with feedback.

    Excludes dependency directories (node_modules, venv, etc.) so that
    auto-installed dependencies persist across correction attempts.
    """
    snapshot: dict[str, bytes] = {}
    if not workspace_dir:
        return snapshot

    root = Path(workspace_dir)
    if not root.exists() or not root.is_dir():
        return snapshot

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _is_excluded_path(rel):
            continue
        try:
            snapshot[str(rel)] = path.read_bytes()
        except OSError:
            continue
    return snapshot


def _restore_workspace(workspace_dir: str, snapshot: dict[str, bytes]) -> None:
    """Restore workspace to a previously captured content snapshot.

    - Files present in the snapshot are written back (created/overwritten).
    - Files NOT in the snapshot but currently on disk are removed.
    - Directories are cleaned up if empty after file removal.

    Excludes dependency directories (node_modules, venv, etc.) so that
    auto-installed dependencies are not wiped between correction attempts.
    """
    root = Path(workspace_dir)
    if not root.exists():
        return

    # Gather current files
    current_files: set[str] = set()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _is_excluded_path(rel):
            continue
        current_files.add(str(rel))

    # Remove files not in the snapshot
    for rel_str in current_files - set(snapshot.keys()):
        try:
            (root / rel_str).unlink(missing_ok=True)
        except OSError:
            pass

    # Restore files from snapshot
    for rel_str, content in snapshot.items():
        target = root / rel_str
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_bytes(content)
        except OSError:
            pass

    # Clean up empty directories (bottom-up)
    for dirpath in sorted(root.rglob("*"), reverse=True):
        if not dirpath.is_dir():
            continue
        rel = dirpath.relative_to(root)
        if _is_excluded_path(rel):
            continue
        try:
            dirpath.rmdir()  # Only succeeds if empty
        except OSError:
            pass


# Errors that are infrastructure / agent-capability issues, NOT content failures.
# These should NOT trigger the correction loop — the agent can't fix them by retrying.
_NON_CORRECTABLE_FAILURES = frozenset({
    "no_agent",
    "budget_exceeded",
    "no_workspace_changes",
    "agent_cannot_modify_workspace",
    "structured_execution_failed",
    "structured_output_missing",
    "file_operations_missing",
    "no_model",
    "no_api_key",
    "timeout",
    "TimeoutError",
    "ConnectError",
})


def _is_correctable_failure(
    outcome: "TaskOutcome", verification: "VerificationResult"
) -> bool:
    """Determine if a failed verification is something the agent can fix on retry.

    Returns True for content-related failures (test failures, placeholder violations,
    drift misalignment, etc.) — the agent should see these and correct.

    Returns False for infrastructure failures (no agent, budget exceeded, HTTP errors,
    missing API keys, environment setup issues) — retrying won't help because the
    agent can only edit files, not install dependencies or fix PATH.
    """
    # If the agent itself couldn't execute, don't retry
    if outcome.failure_reason:
        error_sig = outcome.failure_reason
        if error_sig in _NON_CORRECTABLE_FAILURES or error_sig.startswith("http_"):
            return False

    # If verification found violations, check if any are environment_setup —
    # those cannot be fixed by the agent (missing binaries, missing deps, etc.)
    if verification.violations:
        has_env_violation = any(
            v.get("check") == "environment_setup" for v in verification.violations
        )
        if has_env_violation:
            return False
        return True

    # Not approved but no violations: the verifier couldn't classify the failure
    # (e.g. tests didn't run, no test output captured, or silent failure).
    # This IS correctable — the agent should see the test output / lack thereof
    # and try a different approach.  Previously this returned False, causing ~31%
    # of samples to get only one attempt.
    if not verification.approved:
        return True

    # Approved with no issues — nothing to correct
    return False


def _tokenize_usage_attribution_text(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9_+-]{3,}", text.lower()))
    stopwords = {
        "the", "and", "for", "with", "that", "this", "from", "into", "using", "use",
        "build", "create", "make", "repo", "project", "task", "app", "tool", "system",
        "their", "there", "will", "have", "has", "was", "are", "its", "not",
    }
    return {t for t in tokens if t not in stopwords}


async def _infer_used_methodology_ids(
    context_brief: Optional[ContextBrief],
    outcome: TaskOutcome,
    embedding_engine: Optional[Any] = None,
    memory_config: Optional[Any] = None,
) -> list[tuple[str, float]]:
    """Infer which methodologies contributed to the outcome.

    Pass 1 (always): lexical token overlap (free, no API call).
    Pass 2 (opt-in): embedding cosine similarity for methodologies
        that didn't reach the lexical threshold.
    """
    if context_brief is None or not context_brief.past_solutions:
        return []

    outcome_text = " ".join(
        part for part in [
            outcome.approach_summary or "",
            outcome.raw_output or "",
            outcome.diff or "",
            " ".join(outcome.files_changed),
        ] if part
    )
    outcome_tokens = _tokenize_usage_attribution_text(outcome_text)
    if not outcome_tokens:
        return []

    # --- Pass 1: lexical token overlap ---
    lexical_matched: dict[str, float] = {}
    lexical_unmatched: list[Any] = []

    for meth in context_brief.past_solutions:
        meth_text = " ".join(
            [
                meth.problem_description or "",
                meth.methodology_notes or "",
                " ".join(meth.tags or []),
                " ".join(meth.files_affected or []),
            ]
        )
        meth_tokens = _tokenize_usage_attribution_text(meth_text)
        if not meth_tokens:
            lexical_unmatched.append(meth)
            continue
        overlap = outcome_tokens & meth_tokens
        if not overlap:
            lexical_unmatched.append(meth)
            continue
        score = len(overlap) / max(1, len(meth_tokens))
        if len(overlap) >= 2 or score >= 0.08:
            lexical_matched[meth.id] = round(score, 3)
        else:
            lexical_unmatched.append(meth)

    # --- Pass 2: embedding cosine (opt-in) ---
    embedding_scores: dict[str, float] = {}
    if (
        embedding_engine is not None
        and memory_config is not None
        and getattr(memory_config, "attribution_embedding_enabled", False)
    ):
        weight = getattr(memory_config, "attribution_embedding_weight", 0.6)
        threshold = getattr(memory_config, "attribution_embedding_threshold", 0.35)

        try:
            outcome_embedding = await embedding_engine.async_encode(outcome_text[:12000])

            for meth in lexical_unmatched:
                meth_text = " ".join(
                    [
                        meth.problem_description or "",
                        meth.methodology_notes or "",
                        " ".join(meth.tags or []),
                    ]
                )
                if not meth_text.strip():
                    continue
                meth_embedding = await embedding_engine.async_encode(meth_text[:12000])
                cosine = embedding_engine.cosine_similarity(
                    outcome_embedding, meth_embedding
                )
                if cosine >= threshold:
                    embedding_scores[meth.id] = round(cosine * weight, 3)

            # Also compute embedding scores for lexically matched to potentially upgrade
            for meth in context_brief.past_solutions:
                if meth.id in lexical_matched and meth.id not in embedding_scores:
                    meth_text = " ".join(
                        [
                            meth.problem_description or "",
                            meth.methodology_notes or "",
                            " ".join(meth.tags or []),
                        ]
                    )
                    if not meth_text.strip():
                        continue
                    meth_embedding = await embedding_engine.async_encode(meth_text[:12000])
                    cosine = embedding_engine.cosine_similarity(
                        outcome_embedding, meth_embedding
                    )
                    embedding_scores[meth.id] = round(cosine * weight, 3)
        except Exception as e:
            logger.warning("Embedding attribution pass failed: %s", e)

    # --- Combine scores ---
    all_ids = set(lexical_matched) | set(embedding_scores)
    ranked: list[tuple[str, float]] = []
    for mid in all_ids:
        lex = lexical_matched.get(mid, 0.0)
        emb = embedding_scores.get(mid, 0.0)
        ranked.append((mid, round(max(lex, emb), 3)))

    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked[:5]


_SPEC_FILE_PATTERN = re.compile(r"^Spec file:\s*(.+)$", re.MULTILINE)


def _build_generic_expectation_contract(task: Task) -> dict[str, Any]:
    expected_outcome = ["Task produces a material repository change"]
    expected_ux = ["Result is concrete enough for operator use"]
    constraints = []
    if task.acceptance_checks:
        expected_outcome.append("Acceptance checks pass")
    if task.task_type in {"architecture", "refactoring"}:
        expected_ux.append("Structure is clearer and easier to extend")
    if task.task_type in {"testing", "bug_fix"}:
        expected_outcome.append("Changed behavior is verifiable")
    return {
        "goal": task.title,
        "expected_outcome": expected_outcome,
        "expected_ux": expected_ux,
        "constraints": constraints,
        "non_goals": ["Do not return analysis-only output"],
        "validation_signals": list(task.acceptance_checks),
    }


def _load_expectation_contract_for_task(task: Task) -> Optional[dict[str, Any]]:
    match = _SPEC_FILE_PATTERN.search(task.description or "")
    if match:
        spec_path = Path(match.group(1).strip())
        if spec_path.exists():
            try:
                payload = json.loads(spec_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            contract = payload.get("expectation_contract")
            if isinstance(contract, dict) and contract.get("goal"):
                return contract
    return _build_generic_expectation_contract(task)


def _extract_structured_output(raw_output: Optional[Any]) -> Optional[dict[str, Any]]:
    if not raw_output:
        return None

    if isinstance(raw_output, dict):
        normalized = _extract_structured_payload(raw_output)
        if normalized is not None:
            return normalized
        raw_text = json.dumps(raw_output)
    elif isinstance(raw_output, list):
        text_parts: list[str] = []
        for item in raw_output:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict):
                for key in ("text", "content", "value", "output_text"):
                    value = item.get(key)
                    if isinstance(value, str):
                        text_parts.append(value)
                        break
        raw_text = "\n".join(text_parts) if text_parts else str(raw_output)
    else:
        raw_text = str(raw_output)

    candidates = [raw_text.strip()]
    patterns = [
        r"```json\s*(.*?)\s*```",
        r"```\s*(.*?)\s*```",
        r"(\{[\s\S]*\})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, raw_text, re.IGNORECASE):
            candidate = match.group(1).strip()
            if candidate and candidate not in candidates:
                candidates.append(candidate)

    for candidate in _extract_balanced_json_objects(raw_text):
        if candidate not in candidates:
            candidates.append(candidate)

    for candidate in candidates:
        parsers = (
            lambda text: _parse_json_response(text),
            lambda text: json.loads(text),
            lambda text: ast.literal_eval(text),
        )
        for parser in parsers:
            try:
                parsed = parser(candidate)
            except Exception:
                continue
            payload = _extract_structured_payload(parsed)
            if payload is not None:
                return payload

    return None


def _extract_balanced_json_objects(text: str) -> list[str]:
    """Extract balanced top-level JSON objects from arbitrary model output."""
    results: list[str] = []
    start: Optional[int] = None
    depth = 0
    in_string = False
    escaped = False

    for idx, ch in enumerate(text):
        if start is None:
            if ch == "{":
                start = idx
                depth = 1
                in_string = False
                escaped = False
            continue

        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                results.append(text[start : idx + 1].strip())
                start = None

    return results


def _extract_structured_payload(parsed: Any) -> Optional[dict[str, Any]]:
    """Find a dict containing structured file operations in parsed model output."""
    if isinstance(parsed, dict):
        for key in ("file_operations", "operations", "files", "changes", "edits"):
            value = parsed.get(key)
            if isinstance(value, list):
                return parsed
        for value in parsed.values():
            nested = _extract_structured_payload(value)
            if nested is not None:
                return nested
        return None

    if isinstance(parsed, list):
        # Some agents emit a bare list of operations.
        if parsed and all(isinstance(item, dict) for item in parsed):
            return {"file_operations": parsed}
        for item in parsed:
            nested = _extract_structured_payload(item)
            if nested is not None:
                return nested
    return None


def _counts_as_methodology_success(verification: VerificationResult) -> bool:
    """Only promote methodologies when the result met the expected quality bar."""
    if not verification.approved:
        return False
    if verification.expectation_match_score is not None and verification.expectation_match_score < 0.35:
        return False
    if verification.quality_score is not None and verification.quality_score < 0.35:
        return False
    return True


def _apply_structured_file_operations(
    workspace_dir: Optional[str],
    raw_output: Optional[str],
) -> tuple[bool, Optional[str]]:
    if not workspace_dir:
        return False, "workspace_missing"

    payload = _extract_structured_output(raw_output)
    if payload is None:
        return False, "structured_output_missing"

    operations = payload.get("file_operations")
    if not isinstance(operations, list):
        for key in ("operations", "files", "changes", "edits"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                operations = candidate
                break
    if not isinstance(operations, list) or not operations:
        return False, "file_operations_missing"

    root = Path(workspace_dir).resolve()
    for op in operations:
        if not isinstance(op, dict):
            return False, "file_operation_invalid"

        rel_path = ""
        for key in ("path", "file_path", "filepath", "filename", "target"):
            value = op.get(key)
            if isinstance(value, str) and value.strip():
                rel_path = value.strip()
                break
        action = str(op.get("action") or op.get("operation") or op.get("op") or "write").strip().lower()
        action_aliases = {
            "create": "write",
            "update": "write",
            "replace": "write",
            "overwrite": "write",
            "append": "append",
            "remove": "delete",
            "unlink": "delete",
        }
        action = action_aliases.get(action, action)
        if not rel_path:
            return False, "file_path_missing"

        rel = Path(rel_path)
        if rel.is_absolute() or ".." in rel.parts:
            return False, f"unsafe_path:{rel_path}"

        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return False, f"unsafe_path:{rel_path}"

        if action == "write":
            content = op.get("content")
            if content is None:
                for key in ("text", "data", "body", "value", "code"):
                    alt = op.get(key)
                    if alt is not None:
                        content = alt
                        break
            if not isinstance(content, str):
                return False, f"content_missing:{rel_path}"
            content = _strip_llm_tokens(content)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        elif action == "append":
            content = op.get("content")
            if content is None:
                for key in ("text", "data", "body", "value", "code"):
                    alt = op.get(key)
                    if alt is not None:
                        content = alt
                        break
            if not isinstance(content, str):
                return False, f"content_missing:{rel_path}"
            content = _strip_llm_tokens(content)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as f:
                f.write(content)
        elif action == "delete":
            if target.exists():
                target.unlink()
        else:
            return False, f"unsupported_action:{action}"

    return True, None


def _agent_can_modify_workspace(agent: Any) -> bool:
    capability = getattr(agent, "can_modify_workspace", None)
    if callable(capability):
        return bool(capability())
    return True


def _agent_can_use_internal_executor(agent: Any) -> bool:
    capability = getattr(agent, "can_use_internal_workspace_executor", None)
    if callable(capability):
        return bool(capability())
    return False


class ClawCycle(ABC):
    """Abstract base for all claw cycle levels."""

    def __init__(self, ctx: ClawContext, level: str):
        self.ctx = ctx
        self.level = level

    @abstractmethod
    async def grab(self) -> Any:
        """Select the next unit of work."""

    @abstractmethod
    async def evaluate(self, target: Any) -> Any:
        """Analyze the target for enhancement potential."""

    @abstractmethod
    async def decide(self, evaluation: Any) -> Any:
        """Choose the best approach/agent for the work."""

    @abstractmethod
    async def act(self, decision: Any) -> Any:
        """Execute the chosen approach."""

    @abstractmethod
    async def verify(self, result: Any) -> Any:
        """Validate the output (tests, quality gates)."""

    @abstractmethod
    async def learn(self, outcome: Any) -> None:
        """Update scores, memory, and routing from the outcome."""

    async def run_cycle(self, on_step=None) -> CycleResult:
        """Execute one complete grab->evaluate->decide->act->verify->learn cycle.

        Args:
            on_step: Optional callback ``(step_name: str, detail: str) -> None``
                     called at each phase transition for progress reporting.
        """
        def _step(name: str, detail: str = "") -> None:
            if on_step is not None:
                on_step(name, detail)

        start = time.monotonic()
        try:
            _step("grab", "Fetching next task...")
            target = await self.grab()
            if target is None:
                return CycleResult(cycle_level=self.level, success=False)

            _step("evaluate", f"Analyzing: {target.title[:60]}")
            evaluation = await self.evaluate(target)

            _step("decide", "Selecting best agent...")
            decision = await self.decide(evaluation)
            agent_id = decision[0] if isinstance(decision, tuple) else "unknown"
            _step("act", f"Agent '{agent_id}' working...")
            result = await self.act(decision)

            _step("verify", "Running verification checks...")
            verification = await self.verify(result)

            _step("learn", "Recording outcome...")
            await self.learn(verification)

            duration = time.monotonic() - start
            # Unpack the verification tuple for result fields
            v_agent_id = verification[0] if isinstance(verification, tuple) else None
            v_outcome = verification[2] if isinstance(verification, tuple) and len(verification) > 2 else TaskOutcome()
            v_result = verification[3] if isinstance(verification, tuple) and len(verification) > 3 else None
            _step("done", f"Cycle complete ({duration:.1f}s)")
            return CycleResult(
                cycle_level=self.level,
                task_id=getattr(target, "id", None),
                agent_id=v_agent_id,
                outcome=v_outcome,
                verification=v_result,
                success=True,
                tokens_used=v_outcome.tokens_used if v_outcome else 0,
                cost_usd=v_outcome.cost_usd if v_outcome else 0.0,
                duration_seconds=duration,
            )
        except Exception as e:
            duration = time.monotonic() - start
            logger.error("Cycle %s failed: %s", self.level, e, exc_info=True)
            return CycleResult(
                cycle_level=self.level,
                success=False,
                duration_seconds=duration,
            )


class MicroClaw(ClawCycle):
    """Single-task cycle: grab one task -> route to agent -> verify -> learn.

    This is the Phase 1 implementation. It processes one task from the
    work queue through the full pipeline.
    """

    def __init__(
        self,
        ctx: ClawContext,
        project_id: str,
        session_id: Optional[str] = None,
        target_task_id: Optional[str] = None,
    ):
        super().__init__(ctx, level="micro")
        self.project_id = project_id
        self.session_id = session_id or str(uuid.uuid4())
        # Optional pin to a specific task id — overrides priority-based grab().
        # Used by `cam enhance --task-id` to target a particular pending task.
        self.target_task_id: Optional[str] = target_task_id
        self._current_task: Optional[Task] = None
        self._current_context_brief: Optional[ContextBrief] = None
        self._current_outcome: Optional[TaskOutcome] = None
        self._current_verification: Optional[VerificationResult] = None
        self._ablation_label: Optional[str] = None
        self._suppress_cag_for_control = False
        # Maps methodology_id -> source db_path for rows from federation.
        # Cleared at start of every task in evaluate().
        self._current_source_map: dict[str, str] = {}
        self._auto_fix_engine: Any = None
        self._rl_escalation: Any = None
        self._last_auto_fixes: list[str] = []
        self._last_escalation_decision: Any = None

    async def grab(self) -> Optional[Task]:
        """Get the next pending task for the project.

        If ``target_task_id`` was set at construction, fetches that specific
        task (consumed once — cleared after first grab so subsequent cycles
        fall back to priority-based pickup).
        """
        if self.target_task_id:
            task = await self.ctx.repository.get_task(self.target_task_id)
            self.target_task_id = None  # Consume — only target once
            if task is None:
                logger.info("Targeted task not found; no task to run")
                return None
            if task.status != TaskStatus.PENDING:
                logger.info(
                    "Targeted task %s is %s (not PENDING); skipping",
                    task.id, task.status,
                )
                return None
        else:
            task = await self.ctx.repository.get_next_task(self.project_id)
        if task is None:
            logger.info("No pending tasks for project %s", self.project_id)
            return None

        self._current_task = task
        logger.info("Grabbed task: %s (priority=%d)", task.title, task.priority)

        # Log episode
        await self.ctx.repository.log_episode(
            session_id=self.session_id,
            event_type="task_grabbed",
            event_data={"task_id": task.id, "title": task.title},
            project_id=self.project_id,
            task_id=task.id,
            cycle_level="micro",
        )

        return task

    async def evaluate(self, task: Task) -> TaskContext:
        """Build enriched task context with forbidden approaches and hints."""
        # Reset federation source map for this task
        self._current_source_map = {}
        await self.ctx.repository.update_task_status(task.id, TaskStatus.EVALUATING)

        # Get failed approaches for this task
        failed = await self.ctx.repository.get_failed_approaches(task.id)
        forbidden = [h.approach_summary for h in failed]

        # Enrich with project-wide error KB forbidden approaches
        if self.ctx.error_kb is not None:
            try:
                enriched = await self.ctx.error_kb.get_enriched_forbidden_approaches(
                    task.id, self.project_id
                )
                forbidden = enriched
            except Exception as e:
                logger.warning(
                    "Error KB enrichment failed for task %s: %s", task.id, e
                )

        try:
            fk_entries = await self.ctx.repository.get_failure_knowledge_for_context(
                task_type=task.task_type,
                project_id=self.project_id,
                limit=5,
            )
            for fk in fk_entries:
                forbidden.append(
                    f"[PREVENTIVE] Avoid: {fk.get('error_signature', 'unknown')} - "
                    f"{fk.get('prevention_hint', '')[:200]}"
                )
        except Exception as e:
            logger.debug("Failure knowledge lookup failed: %s", e)

        # Query semantic memory for similar past solutions as hints
        hints: list[str] = []
        past_solutions: list[Any] = []
        retrieval_confidence = 0.0
        retrieval_conflicts: list[str] = []
        primary_methodology_id: str | None = None
        context_methodology_ids: list[str] = []
        # Path C Fix 2: reset source map for this task.  Federation merges
        # below will populate it for every ganglion-sourced methodology.
        self._current_source_map = {}
        if self.ctx.semantic_memory is not None:
            try:
                similar, signals = await self.ctx.semantic_memory.find_similar_with_signals(
                    task.description, limit=25
                )
                retrieval_confidence = float(signals.get("retrieval_confidence", 0.0) or 0.0)
                retrieval_conflicts = [str(item) for item in signals.get("conflicts", []) or []]

                # --- Forbidden-on-retry: exclude methods that failed ≥2 times for this task ---
                forbidden_method_ids: set[str] = set()
                try:
                    fail_counts = await self.ctx.repository.get_task_content_failure_counts(task.id)
                    forbidden_method_ids = {mid for mid, cnt in fail_counts.items() if cnt >= 2}
                    if forbidden_method_ids:
                        logger.info(
                            "Forbidden-on-retry: excluding %d methodologies for task %s",
                            len(forbidden_method_ids), task.id,
                        )
                except Exception:
                    pass  # Non-critical, proceed without filtering

                # Filter out forbidden; apply soft relevance floor with exploration tier
                RELEVANCE_FLOOR = 0.3
                EXPLORATION_FLOOR = 0.15
                eligible_core = []
                eligible_explore = []
                for s in (similar or []):
                    if not s.methodology or s.methodology.id in forbidden_method_ids:
                        continue
                    score = getattr(s, "combined_score", 0.0)
                    if score >= RELEVANCE_FLOOR:
                        eligible_core.append(s)
                    elif score >= EXPLORATION_FLOOR:
                        eligible_explore.append(s)
                # Combine: core candidates first, then exploration tier
                eligible = eligible_core + eligible_explore[:3]  # Cap explore to 3

                # --- Bandit selection: rank by epsilon-greedy / Thompson ---
                if eligible:
                    try:
                        from claw.memory.bandit import (
                            MethodologyBandit,
                            build_bandit_candidates,
                        )
                        task_type = task.task_type or "general"
                        candidates = await build_bandit_candidates(
                            eligible, self.ctx.repository, task_type
                        )
                        bandit = MethodologyBandit()
                        selected = bandit.select(candidates, task_type)
                        ranked = bandit.rank_all(candidates)

                        if selected:
                            primary_methodology_id = selected.methodology_id

                        # Map methodology_id → search result for easy lookup
                        result_by_id = {
                            s.methodology.id: s for s in eligible if s.methodology
                        }

                        # Build past_solutions: primary first, then context (rank 2-3)
                        seen_ids: set[str] = set()
                        if selected and selected.methodology_id in result_by_id:
                            sr = result_by_id[selected.methodology_id]
                            past_solutions.append(sr.methodology)
                            seen_ids.add(selected.methodology_id)
                            hints.append(
                                f"[PRIMARY] Recommended approach: {sr.methodology.methodology_notes}"
                                if sr.methodology.methodology_notes else ""
                            )
                            await self.ctx.semantic_memory.record_retrieval(sr.methodology.id)
                            await self.ctx.repository.log_methodology_usage(
                                MethodologyUsageEntry(
                                    task_id=task.id,
                                    methodology_id=sr.methodology.id,
                                    project_id=self.project_id,
                                    stage="retrieved_presented",
                                    relevance_score=getattr(sr, "combined_score", None),
                                    notes="Bandit-selected primary methodology",
                                )
                            )

                        # Add context methods (next 2 ranked, not the primary)
                        for rc in ranked:
                            if rc.methodology_id in seen_ids:
                                continue
                            if len(context_methodology_ids) >= 7:
                                break
                            if rc.methodology_id in result_by_id:
                                sr = result_by_id[rc.methodology_id]
                                past_solutions.append(sr.methodology)
                                context_methodology_ids.append(rc.methodology_id)
                                seen_ids.add(rc.methodology_id)
                                if sr.methodology.methodology_notes:
                                    hints.append(
                                        f"[CONTEXT] Alternative approach: {sr.methodology.methodology_notes}"
                                    )
                                await self.ctx.semantic_memory.record_retrieval(sr.methodology.id)
                                await self.ctx.repository.log_methodology_usage(
                                    MethodologyUsageEntry(
                                        task_id=task.id,
                                        methodology_id=sr.methodology.id,
                                        project_id=self.project_id,
                                        stage="retrieved_presented",
                                        relevance_score=getattr(sr, "combined_score", None),
                                        notes="Bandit-ranked context methodology",
                                    )
                                )
                    except Exception as e:
                        logger.warning("Bandit selection failed, falling back: %s", e)
                        # Fallback: use first 3 eligible results as before
                        for s in eligible[:3]:
                            if s.methodology and s.methodology not in past_solutions:
                                past_solutions.append(s.methodology)
                                if s.methodology.methodology_notes:
                                    hints.append(
                                        f"Similar past solution: {s.methodology.methodology_notes}"
                                    )
                                await self.ctx.semantic_memory.record_retrieval(s.methodology.id)
                                await self.ctx.repository.log_methodology_usage(
                                    MethodologyUsageEntry(
                                        task_id=task.id,
                                        methodology_id=s.methodology.id,
                                        project_id=self.project_id,
                                        stage="retrieved_presented",
                                        relevance_score=getattr(s, "combined_score", None),
                                        notes="Fallback retrieval (bandit unavailable)",
                                    )
                                )

                # Graph-enhanced: follow synergy edges for complementary capabilities
                for s in (eligible[:3] if eligible else []):
                    if s.methodology and self.ctx.assimilation_engine is not None:
                        try:
                            complements = await self.ctx.repository.get_complementary_capabilities(
                                s.methodology.id
                            )
                            for comp in complements[:2]:
                                hints.append(
                                    f"Complementary capability: {comp.problem_description[:200]}"
                                )
                        except Exception:
                            pass  # Non-critical enhancement
            except Exception as e:
                logger.warning(
                    "Semantic memory lookup failed for task %s: %s", task.id, e
                )

        # Cross-instance federation: query siblings if local knowledge is sparse
        if (
            self.ctx.config.instances.enabled
            and self.ctx.config.instances.siblings
            and retrieval_confidence < self.ctx.config.instances.federation_confidence_threshold
        ):
            try:
                from claw.community.federation import Federation
                primary_db = str(Path(self.ctx.config.database.db_path).resolve())
                federation = Federation(self.ctx.config.instances, primary_db_path=primary_db)
                fed_results = await federation.query(
                    task.description,
                    language=getattr(task, "language", None),
                    max_total=self.ctx.config.instances.federation_max_results,
                )
                for fr in fed_results:
                    if fr.methodology not in past_solutions:
                        past_solutions.append(fr.methodology)
                        # Track source DB for federation write-back
                        if fr.source_db_path and fr.source_db_path != primary_db:
                            self._current_source_map[fr.methodology.id] = fr.source_db_path
                        if fr.methodology.methodology_notes:
                            hints.append(
                                f"[from {fr.source_instance}] {fr.methodology.methodology_notes}"
                            )
                        # Record retrieval in source DB
                        ganglion_source = fr.source_db_path if fr.source_db_path != primary_db else None
                        if self.ctx.semantic_memory is not None:
                            await self.ctx.semantic_memory.record_retrieval(
                                fr.methodology.id,
                                source_db_path=ganglion_source,
                            )
                        logger.info(
                            "Federation: added methodology %s from sibling %s (relevance=%.3f)",
                            fr.methodology.id, fr.source_instance, fr.relevance_score,
                        )
            except Exception as e:
                logger.warning("Federation query failed: %s", e)

        # Surface top novel capabilities as hints (novelty >= 0.7)
        if self.ctx.repository is not None:
            try:
                novel = await self.ctx.repository.get_most_novel_methodologies(
                    limit=2, min_novelty=0.7
                )
                for nm in novel:
                    hints.append(
                        f"Novel capability (novelty={nm.novelty_score:.2f}): "
                        f"{nm.problem_description[:200]}"
                    )
            except Exception:
                pass  # Non-critical enhancement

        action_template = None
        if task.action_template_id:
            try:
                action_template = await self.ctx.repository.get_action_template(
                    task.action_template_id
                )
                if action_template is None:
                    logger.warning(
                        "Task %s references missing action template %s",
                        task.id,
                        task.action_template_id,
                    )
            except Exception as e:
                logger.warning(
                    "Failed to load action template %s for task %s: %s",
                    task.action_template_id,
                    task.id,
                    e,
                )

        # Add explicit runbook guidance for execution-oriented tasks.
        runbook_steps = list(task.execution_steps)
        runbook_checks = list(task.acceptance_checks)
        runbook_preconditions: list[str] = []
        runbook_rollback: list[str] = []
        if action_template is not None:
            if not runbook_steps:
                runbook_steps = list(action_template.execution_steps)
            if not runbook_checks:
                runbook_checks = list(action_template.acceptance_checks)
            runbook_preconditions = list(action_template.preconditions)
            runbook_rollback = list(action_template.rollback_steps)

        for precondition in runbook_preconditions[:3]:
            hints.append(f"Runbook precondition: {precondition}")
        for step in runbook_steps[:5]:
            hints.append(f"Runbook execute: {step}")
        for check in runbook_checks[:5]:
            hints.append(f"Runbook verify: {check}")
        for rollback in runbook_rollback[:2]:
            hints.append(f"Runbook rollback: {rollback}")

        # A/B ablation: decide whether to suppress knowledge for this task
        self._ablation_label = None
        if self.ctx.prompt_evolver is not None and past_solutions:
            try:
                self._ablation_label, _ = await self.ctx.prompt_evolver.select_variant_for_invocation(
                    "knowledge_ablation", agent_id=None
                )
                if self._ablation_label == "control":
                    logger.info(
                        "A/B ablation: suppressing ALL knowledge for task %s (control group)",
                        task.id,
                    )
                    past_solutions = []
                    self._suppress_cag_for_control = True
                else:
                    self._suppress_cag_for_control = False
            except (ValueError, Exception):
                self._ablation_label = None  # No ablation test scheduled

        # CAM-SEQ: build ApplicationPackets if feature is enabled and components exist
        built_packets: list[Any] = []
        if getattr(self.ctx.config, "feature_flags", None) and self.ctx.config.feature_flags.application_packets:
            try:
                from claw.planning.taskome import decompose_task
                from claw.planning.application_packet import build_application_packet
                from claw.memory.component_ranker import rank_components_for_slot

                workspace_dir = getattr(
                    list(self.ctx.agents.values())[0] if self.ctx.agents else None,
                    "workspace_dir", None,
                )
                plan = decompose_task(
                    task.description,
                    workspace_path=workspace_dir,
                    target_language=getattr(task, "language", None),
                )
                if plan.archetype_confidence >= 0.52 and plan.slots:
                    cards = await self.ctx.repository.list_component_cards_full(limit=500)
                    if cards:
                        for slot in plan.slots[:6]:
                            ranked = rank_components_for_slot(slot, cards)
                            if ranked and ranked[0].fit_bucket.value != "no_help":
                                packet = build_application_packet(
                                    plan.plan_id, plan.task_archetype, slot, ranked,
                                )
                                await self.ctx.repository.save_application_packet(packet)
                                built_packets.append(packet)
                        if built_packets:
                            logger.info(
                                "CAM-SEQ: built %d packets for archetype '%s' (%d slots)",
                                len(built_packets), plan.task_archetype, len(plan.slots),
                            )
            except Exception as e:
                logger.warning("CAM-SEQ packet construction failed: %s", e)

        task_ctx = TaskContext(
            task=task,
            forbidden_approaches=forbidden,
            hints=hints,
            action_template=action_template,
            expectation_contract=_load_expectation_contract_for_task(task),
        )
        self._current_context_brief = ContextBrief(
            task=task,
            past_solutions=past_solutions,
            forbidden_approaches=forbidden,
            retrieval_confidence=retrieval_confidence,
            retrieval_conflicts=retrieval_conflicts,
            retrieved_methodology_ids=[m.id for m in past_solutions],
            primary_methodology_id=primary_methodology_id,
            context_methodology_ids=context_methodology_ids,
            application_packets=built_packets,
        )

        logger.info(
            "Evaluated task: %d forbidden approaches, %d hints, %d packets",
            len(forbidden), len(hints), len(built_packets),
        )
        return task_ctx

    async def decide(self, task_ctx: TaskContext) -> tuple[str, TaskContext]:
        """Decide which agent to use via Dispatcher + Degradation checks."""
        await self.ctx.repository.update_task_status(task_ctx.task.id, TaskStatus.DISPATCHED)

        # Check degradation: ensure at least one agent is healthy
        if self.ctx.degradation_manager is not None:
            if self.ctx.degradation_manager.is_all_down():
                logger.error("All agents down — escalating to human")
                return ("none", task_ctx)

        # Use Dispatcher for Bayesian routing (with 10% exploration)
        if self.ctx.dispatcher is not None:
            try:
                agent_id = await self.ctx.dispatcher.route_task(task_ctx.task, task_ctx)
            except Exception as e:
                logger.warning("Dispatcher routing failed: %s, falling back", e)
                agent_id = task_ctx.task.recommended_agent or "claude"
        else:
            agent_id = task_ctx.task.recommended_agent or "claude"

        # Check degradation for the chosen agent; get fallback if needed
        if self.ctx.degradation_manager is not None:
            healthy = self.ctx.degradation_manager.get_healthy_agents()
            if agent_id not in healthy:
                fallback = self.ctx.degradation_manager.get_fallback_agent(agent_id)
                if fallback is not None:
                    logger.info("Agent '%s' degraded, falling back to '%s'", agent_id, fallback)
                    agent_id = fallback

        if agent_id not in self.ctx.agents:
            available = list(self.ctx.agents.keys())
            if available:
                agent_id = available[0]
            else:
                logger.error("No agents available")
                return ("none", task_ctx)

        await self.ctx.repository.update_task_agent(task_ctx.task.id, agent_id)
        logger.info("Decided: routing to agent '%s'", agent_id)

        return (agent_id, task_ctx)

    async def act(self, decision: tuple[str, TaskContext]) -> tuple[str, TaskContext, TaskOutcome]:
        """Execute the task through the chosen agent, with budget check."""
        agent_id, task_ctx = decision

        if agent_id == "none" or agent_id not in self.ctx.agents:
            return (agent_id, task_ctx, TaskOutcome(
                agent_id=agent_id,
                failure_reason="no_agent",
                failure_detail="No agent available to execute task",
            ))

        # Budget check before dispatch
        if self.ctx.budget_enforcer is not None:
            budget_results = await self.ctx.budget_enforcer.check_all(
                task_id=task_ctx.task.id,
                project_id=self.project_id,
                agent_id=agent_id,
            )
            exceeded = [r for r in budget_results if r.exceeded]
            if exceeded:
                first = exceeded[0]
                logger.warning(
                    "Budget exceeded (%s): %s",
                    first.check_type, first.entity_id,
                )
                return (agent_id, task_ctx, TaskOutcome(
                    agent_id=agent_id,
                    failure_reason="budget_exceeded",
                    failure_detail=f"Budget cap hit: {first.check_type} ({first.entity_id})",
                ))

        await self.ctx.repository.update_task_status(task_ctx.task.id, TaskStatus.CODING)
        await self.ctx.repository.increment_task_attempt(task_ctx.task.id)

        agent = self.ctx.agents[agent_id]
        can_modify_workspace = _agent_can_modify_workspace(agent)
        can_use_internal_executor = _agent_can_use_internal_executor(agent)
        if not can_modify_workspace and not can_use_internal_executor:
            outcome = TaskOutcome(
                agent_id=agent_id,
                failure_reason="agent_cannot_modify_workspace",
                failure_detail=(
                    "Selected agent mode cannot modify workspace files and has no internal CAM "
                    "executor path. Use a CLI-capable agent or a structured-output-capable mode."
                ),
                tests_passed=False,
            )
            self._current_outcome = outcome
            logger.warning(
                "Agent %s cannot modify workspace in current mode; refusing execution",
                agent_id,
            )
            return (agent_id, task_ctx, outcome)

        workspace_dir = getattr(agent, "workspace_dir", None)
        before_snapshot = _snapshot_workspace(workspace_dir)

        # Set token tracking context
        self.ctx.token_tracker.set_context(
            task_id=task_ctx.task.id,
            agent_id=agent_id,
            agent_role=agent_id,
        )

        # A/B ablation: suppress CAG corpus for control arm
        saved_cag_corpus = None
        if self._suppress_cag_for_control:
            saved_cag_corpus = getattr(agent, "_cag_corpus", None)
            if saved_cag_corpus is not None:
                agent._cag_corpus = ""
                logger.info("A/B ablation: CAG corpus suppressed for control arm")

        try:
            outcome = await agent.run(task_ctx, context=self._current_context_brief)
        except TypeError:
            outcome = await agent.run(task_ctx)

        # A/B ablation: restore CAG corpus after execution
        if saved_cag_corpus is not None:
            agent._cag_corpus = saved_cag_corpus
            logger.info("A/B ablation: CAG corpus restored")
        self._suppress_cag_for_control = False
        if not can_modify_workspace and can_use_internal_executor:
            applied, apply_error = _apply_structured_file_operations(workspace_dir, outcome.raw_output)
            if not applied and not outcome.failure_reason:
                outcome.failure_reason = "structured_execution_failed"
                outcome.failure_detail = (
                    "CAM could not apply structured file operations from the agent output: "
                    f"{apply_error}"
                )
                outcome.tests_passed = False
        after_snapshot = _snapshot_workspace(workspace_dir)
        actual_files_changed, actual_diff = _compute_workspace_change(before_snapshot, after_snapshot)

        # Trust the real workspace diff over model self-report.
        if workspace_dir and actual_files_changed:
            outcome.files_changed = actual_files_changed
            outcome.diff = actual_diff
        elif workspace_dir and not outcome.failure_reason:
            outcome.files_changed = []
            outcome.diff = ""
            outcome.failure_reason = "no_workspace_changes"
            outcome.failure_detail = (
                "Agent returned without modifying any workspace files."
            )
            outcome.tests_passed = False

        self._current_outcome = outcome

        logger.info(
            "Act complete: agent=%s, tests_passed=%s, files=%d",
            agent_id, outcome.tests_passed, len(outcome.files_changed),
        )

        return (agent_id, task_ctx, outcome)

    async def verify(self, result: tuple[str, TaskContext, TaskOutcome]) -> tuple[str, TaskContext, TaskOutcome, VerificationResult]:
        """Verify the agent's output using the full 7-check Verifier."""
        agent_id, task_ctx, outcome = result
        await self.ctx.repository.update_task_status(task_ctx.task.id, TaskStatus.REVIEWING)

        if self.ctx.verifier is not None and not outcome.failure_reason:
            # Use the full 7-check Verifier
            verification = await self.ctx.verifier.verify(
                outcome=outcome,
                task_context=task_ctx,
                workspace_dir=_resolve_workspace_dir(self.ctx.agents, agent_id, task_ctx),
            )
        else:
            # Fallback: basic checks if verifier unavailable or execution failed
            violations = []
            if outcome.failure_reason:
                violations.append({"check": "execution", "detail": outcome.failure_reason})
            if outcome.raw_output:
                for marker in ["TODO", "FIXME", "NotImplementedError", "placeholder", "mock"]:
                    if marker.lower() in outcome.raw_output.lower():
                        violations.append({"check": "placeholder_scan", "detail": f"Found '{marker}' in output"})

            verification = VerificationResult(
                approved=len(violations) == 0 and outcome.tests_passed,
                violations=violations,
                quality_score=1.0 if not violations else 0.5,
            )

        self._current_verification = verification

        logger.info(
            "Verify: approved=%s, violations=%d",
            verification.approved, len(verification.violations),
        )

        return (agent_id, task_ctx, outcome, verification)

    async def _act_with_correction(
        self,
        decision: tuple[str, TaskContext],
        on_step=None,
    ) -> tuple[str, TaskContext, TaskOutcome, VerificationResult]:
        """Execute act + verify with an inner correction loop.

        If verification fails with a correctable error, the workspace is restored
        to its pre-attempt state, the agent receives correction feedback describing
        the violations and test output, and act + verify are retried.

        The loop runs at most ``max_correction_attempts`` times (from config).
        After exhausting attempts, the last failed result is returned so learn()
        can record the failure normally.
        """
        agent_id, task_ctx = decision
        max_attempts = self.ctx.config.orchestrator.max_correction_attempts

        def _step(name: str, detail: str = "") -> None:
            if on_step is not None:
                on_step(name, detail)

        # Snapshot workspace CONTENT before first attempt for restoration
        workspace_dir = _resolve_workspace_dir(self.ctx.agents, agent_id, task_ctx)
        content_snapshot = _snapshot_workspace_content(workspace_dir)

        last_verification: Optional[VerificationResult] = None
        last_result: Optional[tuple[str, TaskContext, TaskOutcome]] = None

        for attempt in range(max_attempts):
            if attempt > 0:
                _step("correct", f"Correction attempt {attempt + 1}/{max_attempts}...")
                logger.info(
                    "Correction attempt %d/%d for task %s",
                    attempt + 1, max_attempts, task_ctx.task.id,
                )

                # Compute real code diff BEFORE restoring (agent's code is still on disk)
                code_diff = ""
                failing_tests = ""
                if workspace_dir and content_snapshot:
                    code_diff = _compute_content_diff(content_snapshot, workspace_dir)
                    test_output = last_verification.test_output if last_verification else ""
                    if test_output:
                        failing_tests = _read_failing_test_files(test_output, workspace_dir)

                # Restore workspace to pre-attempt state
                if workspace_dir and content_snapshot:
                    _restore_workspace(workspace_dir, content_snapshot)
                    logger.info("Workspace restored for correction attempt %d", attempt + 1)

                known_fix_hint: str | None = None
                if self.ctx.error_kb is not None:
                    error_sig = last_result[2].failure_reason if last_result else None
                    if error_sig:
                        try:
                            known_fix_hint = await self.ctx.error_kb.get_resolution_for_error(
                                error_sig, self.project_id,
                            )
                        except Exception as e:
                            logger.debug("ErrorKB resolution lookup failed: %s", e)

                # Build correction feedback from the previous failure
                auto_fixes = self._last_auto_fixes.copy()
                self._last_auto_fixes = []
                feedback = CorrectionFeedback(
                    attempt_number=attempt,
                    violations=last_verification.violations if last_verification else [],
                    test_output=last_verification.test_output if last_verification else "",
                    diff=last_result[2].diff if last_result else "",
                    code_diff=code_diff,
                    failing_test_content=failing_tests,
                    quality_score=last_verification.quality_score or 0.0 if last_verification else 0.0,
                    failure_reason=last_result[2].failure_reason if last_result else None,
                    failure_detail=last_result[2].failure_detail if last_result else None,
                    known_fix_hint=known_fix_hint,
                    auto_fixes_applied=auto_fixes,
                )

                # Inject into task context and context brief for prompt builder
                task_ctx.correction_feedback = feedback
                if self._current_context_brief is not None:
                    self._current_context_brief.correction_feedback = feedback

                # Log the correction episode
                await self.ctx.repository.log_episode(
                    session_id=self.session_id,
                    event_type="correction_attempt",
                    event_data={
                        "task_id": task_ctx.task.id,
                        "attempt": attempt + 1,
                        "violation_count": len(feedback.violations),
                        "failure_reason": feedback.failure_reason,
                    },
                    project_id=self.project_id,
                    task_id=task_ctx.task.id,
                    cycle_level="micro",
                )

            # Execute act + verify
            _step("act", f"Agent '{agent_id}' working{' (correction)' if attempt > 0 else ''}...")
            result = await self.act((agent_id, task_ctx))
            last_result = result

            # Post-act: validate critical JSON files and auto-repair from snapshot
            if workspace_dir and content_snapshot:
                repaired = _validate_and_repair_json(workspace_dir, content_snapshot)
                if repaired:
                    logger.warning(
                        "Auto-repaired %d corrupted JSON file(s) after agent edit: %s",
                        len(repaired), ", ".join(repaired),
                    )

            if (
                attempt == 0
                and workspace_dir
                and getattr(self.ctx.config.orchestrator, "auto_fix_enabled", True)
            ):
                if self._auto_fix_engine is None:
                    from claw.memory.auto_fix import build_default_engine
                    self._auto_fix_engine = build_default_engine()
                proactive_result = self._auto_fix_engine.try_auto_fix(
                    workspace_dir, "", None, proactive=True,
                )
                if proactive_result.fixes_applied:
                    logger.info(
                        "Proactive auto-fix applied %d fixes before verification: %s",
                        len(proactive_result.fixes_applied),
                        "; ".join(proactive_result.fixes_applied),
                    )

            _step("verify", "Running verification checks...")
            verification_tuple = await self.verify(result)
            agent_id_v, task_ctx_v, outcome_v, verification = verification_tuple
            last_verification = verification

            if verification.approved:
                if attempt > 0:
                    logger.info(
                        "Correction succeeded on attempt %d for task %s",
                        attempt + 1, task_ctx.task.id,
                    )
                    await self.ctx.repository.log_episode(
                        session_id=self.session_id,
                        event_type="correction_succeeded",
                        event_data={
                            "task_id": task_ctx.task.id,
                            "attempt": attempt + 1,
                            "quality_score": verification.quality_score,
                        },
                        project_id=self.project_id,
                        task_id=task_ctx.task.id,
                        cycle_level="micro",
                    )
                return verification_tuple

            if (
                workspace_dir
                and getattr(self.ctx.config.orchestrator, "auto_fix_enabled", True)
                and _is_correctable_failure(outcome_v, verification)
            ):
                if self._auto_fix_engine is None:
                    from claw.memory.auto_fix import build_default_engine
                    self._auto_fix_engine = build_default_engine()

                error_text = verification.test_output or ""
                if outcome_v.failure_detail:
                    error_text += "\n" + outcome_v.failure_detail
                auto_result = self._auto_fix_engine.try_auto_fix(
                    workspace_dir, error_text, verification.violations,
                )
                if auto_result.fixes_applied:
                    logger.info(
                        "Auto-fix applied %d fixes for task %s: %s",
                        len(auto_result.fixes_applied),
                        task_ctx.task.id,
                        "; ".join(auto_result.fixes_applied),
                    )
                    re_verify_tuple = await self.verify(result)
                    _, _, _, re_verification = re_verify_tuple
                    if re_verification.approved:
                        logger.info(
                            "Auto-fix resolved task %s (fixes: %s)",
                            task_ctx.task.id,
                            ", ".join(auto_result.fixes_applied),
                        )
                        await self.ctx.repository.log_episode(
                            session_id=self.session_id,
                            event_type="auto_fix_succeeded",
                            event_data={
                                "task_id": task_ctx.task.id,
                                "fixes": auto_result.fixes_applied,
                                "files_modified": auto_result.files_modified,
                            },
                            project_id=self.project_id,
                            task_id=task_ctx.task.id,
                            cycle_level="micro",
                        )
                        return re_verify_tuple
                    self._last_auto_fixes = auto_result.fixes_applied

            # Check if the failure is correctable
            if not _is_correctable_failure(outcome_v, verification):
                logger.info(
                    "Non-correctable failure for task %s: %s — skipping correction loop",
                    task_ctx.task.id, outcome_v.failure_reason,
                )
                return verification_tuple

            logger.info(
                "Attempt %d/%d failed for task %s with %d violations — will retry",
                attempt + 1, max_attempts, task_ctx.task.id,
                len(verification.violations),
            )

        # All attempts exhausted
        logger.warning(
            "All %d correction attempts exhausted for task %s",
            max_attempts, task_ctx.task.id,
        )
        await self.ctx.repository.log_episode(
            session_id=self.session_id,
            event_type="correction_exhausted",
            event_data={
                "task_id": task_ctx.task.id,
                "attempts": max_attempts,
                "final_violations": len(last_verification.violations) if last_verification else 0,
            },
            project_id=self.project_id,
            task_id=task_ctx.task.id,
            cycle_level="micro",
        )

        # Return the last failed result for learn() to process
        return (agent_id, task_ctx, last_result[2] if last_result else TaskOutcome(), last_verification or VerificationResult())

    async def run_cycle(self, on_step=None) -> CycleResult:
        """Execute one complete cycle with correction and escalation retries.

        Overrides the base ClawCycle.run_cycle() to use _act_with_correction()
        instead of separate act() + verify() calls. This allows the agent to
        self-correct when verification finds fixable issues.
        """
        max_escalation_retries = 3

        def _step(name: str, detail: str = "") -> None:
            if on_step is not None:
                on_step(name, detail)

        start = time.monotonic()
        escalation_retries = 0
        try:
            set_context(session_id=self.session_id, cycle_level=self.level)

            _step("grab", "Fetching next task...")
            target = await self.grab()
            if target is None:
                clear_context()
                return CycleResult(cycle_level=self.level, success=False)

            set_context(task_id=getattr(target, "id", None), project_id=self.project_id)

            while True:
                self._last_escalation_decision = None

                _step("evaluate", f"Analyzing: {target.title[:60]}")
                evaluation = await self.evaluate(target)

                _step("decide", "Selecting best agent...")
                decision = await self.decide(evaluation)
                agent_id = decision[0] if isinstance(decision, tuple) else "unknown"
                set_context(agent_id=agent_id)

                verification = await self._act_with_correction(decision, on_step=on_step)

                _step("learn", "Recording outcome...")
                await self.learn(verification)

                if (
                    self._last_escalation_decision is not None
                    and escalation_retries < max_escalation_retries
                ):
                    from claw.evolution.rl_escalation import EscalationAction
                    if self._last_escalation_decision.action == EscalationAction.ROTATE_AGENT:
                        escalation_retries += 1
                        logger.info(
                            "Escalation retry %d/%d for task %s: rotating away from '%s'",
                            escalation_retries, max_escalation_retries,
                            target.id, agent_id,
                        )
                        refreshed = await self.ctx.repository.get_task(target.id)
                        if refreshed is not None:
                            target = refreshed
                            self._current_task = target
                        continue

                break

            duration = time.monotonic() - start
            v_agent_id = verification[0] if isinstance(verification, tuple) else None
            v_outcome = verification[2] if isinstance(verification, tuple) and len(verification) > 2 else TaskOutcome()
            v_result = verification[3] if isinstance(verification, tuple) and len(verification) > 3 else None
            _step("done", f"Cycle complete ({duration:.1f}s)")
            clear_context()
            return CycleResult(
                cycle_level=self.level,
                task_id=getattr(target, "id", None),
                agent_id=v_agent_id,
                outcome=v_outcome,
                verification=v_result,
                success=True,
                tokens_used=v_outcome.tokens_used if v_outcome else 0,
                cost_usd=v_outcome.cost_usd if v_outcome else 0.0,
                duration_seconds=duration,
            )
        except Exception as e:
            duration = time.monotonic() - start
            logger.error("Cycle %s failed: %s", self.level, e, exc_info=True)
            clear_context()
            return CycleResult(
                cycle_level=self.level,
                success=False,
                duration_seconds=duration,
            )

    async def learn(self, verified: tuple[str, TaskContext, TaskOutcome, VerificationResult]) -> None:
        """Update memory, scores, error KB, and semantic memory from the outcome."""
        agent_id, task_ctx, outcome, verification = verified
        task = task_ctx.task
        used_methodologies = await _infer_used_methodology_ids(
            self._current_context_brief,
            outcome,
            embedding_engine=self.ctx.embeddings if getattr(
                self.ctx.config.memory, "attribution_embedding_enabled", False
            ) else None,
            memory_config=self.ctx.config.memory,
        )

        if verification.approved:
            methodology_success = _counts_as_methodology_success(verification)
            # Success path
            await self.ctx.repository.update_task_status(task.id, TaskStatus.DONE)

            # Log successful hypothesis
            attempt = await self.ctx.repository.get_next_hypothesis_attempt(task.id)
            await self.ctx.repository.log_hypothesis(HypothesisEntry(
                task_id=task.id,
                attempt_number=attempt,
                approach_summary=outcome.approach_summary[:500],
                outcome=HypothesisOutcome.SUCCESS,
                files_changed=outcome.files_changed,
                duration_seconds=outcome.duration_seconds,
                model_used=outcome.model_used,
                agent_id=agent_id,
            ))

            if task_ctx.correction_feedback is not None:
                try:
                    failed_entries = await self.ctx.repository.get_failed_approaches(task.id)
                    if failed_entries:
                        latest_fail = failed_entries[-1]
                        if latest_fail.error_signature:
                            fix_attempt = await self.ctx.repository.get_next_hypothesis_attempt(task.id)
                            await self.ctx.repository.log_hypothesis(HypothesisEntry(
                                task_id=task.id,
                                attempt_number=fix_attempt,
                                approach_summary=f"[CORRECTION_FIX] {outcome.approach_summary[:450]}",
                                outcome=HypothesisOutcome.SUCCESS,
                                error_signature=latest_fail.error_signature,
                                files_changed=outcome.files_changed,
                                duration_seconds=outcome.duration_seconds,
                                model_used=outcome.model_used,
                                agent_id=agent_id,
                            ))
                            try:
                                await self.ctx.repository.mark_failure_knowledge_resolved(
                                    latest_fail.error_signature,
                                    resolution_approach=outcome.approach_summary[:300],
                                )
                            except Exception:
                                pass
                except Exception as e:
                    logger.debug("Failed to record correction fix pair: %s", e)

            # Update agent score
            await self.ctx.repository.update_agent_score(
                agent_id=agent_id,
                task_type=task.task_type or "general",
                success=True,
                duration_seconds=outcome.duration_seconds,
                quality_score=verification.quality_score or 0.0,
                cost_usd=outcome.cost_usd,
            )

            # Save successful pattern to semantic memory + trigger assimilation
            if self.ctx.semantic_memory is not None and outcome.approach_summary:
                try:
                    saved_meth = await self.ctx.semantic_memory.save_solution(
                        problem_description=task.description,
                        solution_code=outcome.raw_output or outcome.approach_summary,
                        source_task_id=task.id,
                        methodology_notes=outcome.approach_summary,
                        tags=[task.task_type or "general"],
                    )
                    logger.info(
                        "Saved successful pattern to semantic memory for task %s",
                        task.title,
                    )
                    # Trigger capability assimilation on the newly saved methodology
                    if saved_meth and self.ctx.assimilation_engine is not None:
                        try:
                            await self.ctx.assimilation_engine.assimilate(saved_meth.id)
                        except Exception as ae:
                            logger.warning("Assimilation failed for %s: %s", saved_meth.id, ae)
                except Exception as e:
                    logger.warning(
                        "Failed to save pattern to semantic memory for task %s: %s",
                        task.id, e,
                    )

            # Extract cross-project patterns if enough completions
            if self.ctx.pattern_learner is not None:
                try:
                    patterns = await self.ctx.pattern_learner.extract_patterns(
                        self.project_id
                    )
                    if patterns:
                        logger.info(
                            "Extracted %d patterns from project %s",
                            len(patterns), self.project_id,
                        )
                except Exception as e:
                    logger.warning(
                        "Pattern extraction failed for project %s: %s",
                        self.project_id, e,
                    )

            if self.ctx.semantic_memory is not None:
                for methodology_id, relevance in used_methodologies:
                    try:
                        await self.ctx.repository.log_methodology_usage(
                            MethodologyUsageEntry(
                                task_id=task.id,
                                methodology_id=methodology_id,
                                project_id=self.project_id,
                                stage="used_in_outcome",
                                agent_id=agent_id,
                                success=methodology_success,
                                expectation_match_score=verification.expectation_match_score,
                                quality_score=verification.quality_score,
                                relevance_score=relevance,
                                notes="Retrieved methodology inferred in successful outcome",
                            )
                        )
                        await self.ctx.repository.log_methodology_usage(
                            MethodologyUsageEntry(
                                task_id=task.id,
                                methodology_id=methodology_id,
                                project_id=self.project_id,
                                stage="outcome_attributed",
                                agent_id=agent_id,
                                success=methodology_success,
                                expectation_match_score=verification.expectation_match_score,
                                quality_score=verification.quality_score,
                                relevance_score=relevance,
                                notes=(
                                    "Expectation-matched successful outcome attributed to retrieved methodology"
                                    if methodology_success else
                                    "Approved outcome fell below expectation/quality threshold for methodology promotion"
                                ),
                            )
                        )
                        await self.ctx.semantic_memory.record_outcome(
                            methodology_id,
                            success=methodology_success,
                            retrieval_relevance=relevance,
                            source_db_path=self._current_source_map.get(methodology_id),
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to record successful methodology usage for %s: %s",
                            methodology_id,
                            e,
                        )

            # Bandit: record success for used methodologies
            task_type = task.task_type or "general"
            for methodology_id, _rel in used_methodologies:
                try:
                    await self.ctx.repository.record_bandit_outcome(
                        methodology_id, task_type, success=True
                    )
                except Exception:
                    pass  # Non-critical

            # LCDE: extract latent capabilities from used methodologies
            if used_methodologies and methodology_success:
                try:
                    from claw.lcde import extract_capabilities, update_methodology_directives
                    for methodology_id, _rel in used_methodologies:
                        meth = await self.ctx.repository.get_methodology(methodology_id)
                        if meth is not None:
                            discovery = extract_capabilities(
                                methodology=meth,
                                task_description=task.description,
                                task_id=task.id,
                                outcome_notes=f"quality={verification.quality_score}, match={verification.expectation_match_score}",
                            )
                            updated_meth = update_methodology_directives(meth, discovery)
                            if updated_meth.use_immediately_as != meth.use_immediately_as:
                                await self.ctx.repository.update_methodology_directives(
                                    methodology_id,
                                    use_immediately_as=updated_meth.use_immediately_as,
                                )
                            logger.info(
                                "LCDE: methodology %s — %d capabilities, %d adjacent tasks, %d gaps",
                                methodology_id,
                                len(discovery.discovered_capabilities),
                                len(discovery.adjacent_tasks),
                                len(discovery.knowledge_gaps),
                            )
                except Exception as e:
                    logger.warning("LCDE capability extraction failed: %s", e)

            # CAM-SEQ: record RunConnectome events if packets were used
            if (
                getattr(self.ctx.config, "feature_flags", None)
                and self.ctx.config.feature_flags.connectome_seq
                and self._current_context_brief
                and self._current_context_brief.application_packets
            ):
                try:
                    from claw.core.models import RunConnectome, RunEvent
                    from datetime import datetime, timezone

                    run_id = f"run_{uuid.uuid4().hex[:12]}"
                    packets = self._current_context_brief.application_packets
                    archetype = packets[0].task_archetype if packets else "unknown"
                    connectome = RunConnectome(
                        id=f"conn_{uuid.uuid4().hex[:12]}",
                        run_id=run_id,
                        task_archetype=archetype,
                        status="completed" if verification.approved else "failed",
                        created_at=datetime.now(timezone.utc),
                    )
                    await self.ctx.repository.save_run_connectome(connectome)

                    for pkt in packets:
                        # Pair event: slot matched to component
                        await self.ctx.repository.save_run_event(RunEvent(
                            id=f"evt_{uuid.uuid4().hex[:12]}",
                            run_id=run_id,
                            slot_id=pkt.slot.slot_id,
                            event_type="paired",
                            payload_json=json.dumps({
                                "packet_id": pkt.packet_id,
                                "component_id": pkt.selected.component_id,
                                "confidence": pkt.selected.confidence,
                                "fit_bucket": pkt.selected.fit_bucket.value,
                            }),
                            created_at=datetime.now(timezone.utc),
                        ))
                        # Outcome event
                        await self.ctx.repository.save_run_event(RunEvent(
                            id=f"evt_{uuid.uuid4().hex[:12]}",
                            run_id=run_id,
                            slot_id=pkt.slot.slot_id,
                            event_type="outcome",
                            payload_json=json.dumps({
                                "packet_id": pkt.packet_id,
                                "success": verification.approved,
                                "quality_score": verification.quality_score,
                            }),
                            created_at=datetime.now(timezone.utc),
                        ))
                        # Build connectome edge
                        await self.ctx.repository.save_run_connectome_edge(
                            connectome_id=connectome.id,
                            source_node=pkt.slot.slot_id,
                            target_node=pkt.selected.component_id,
                            edge_type="paired",
                            metadata={"confidence": pkt.selected.confidence},
                        )

                    logger.info(
                        "CAM-SEQ: recorded connectome %s with %d pair events",
                        run_id, len(packets),
                    )
                except Exception as e:
                    logger.warning("CAM-SEQ connectome recording failed: %s", e)

            logger.info("Learned: task %s completed by %s", task.title, agent_id)

        else:
            # Failure path
            error_sig = outcome.failure_reason or "unknown"
            attempt = await self.ctx.repository.get_next_hypothesis_attempt(task.id)
            await self.ctx.repository.log_hypothesis(HypothesisEntry(
                task_id=task.id,
                attempt_number=attempt,
                approach_summary=outcome.approach_summary[:500] if outcome.approach_summary else "Failed attempt",
                outcome=HypothesisOutcome.FAILURE,
                error_signature=error_sig,
                error_full=outcome.failure_detail,
                files_changed=outcome.files_changed,
                duration_seconds=outcome.duration_seconds,
                model_used=outcome.model_used,
                agent_id=agent_id,
            ))

            # Update agent score (failure)
            await self.ctx.repository.update_agent_score(
                agent_id=agent_id,
                task_type=task.task_type or "general",
                success=False,
                duration_seconds=outcome.duration_seconds,
                quality_score=verification.quality_score or 0.0,
                cost_usd=outcome.cost_usd,
            )

            # ErrorKB reads from the shared hypothesis_log, so the direct write
            # above is sufficient and avoids double-inserting the same attempt.
            if self.ctx.error_kb is not None:
                logger.info(
                    "Recorded failure in hypothesis log for task %s (error: %s)",
                    task.id, error_sig,
                )

            try:
                if self._rl_escalation is None:
                    from claw.evolution.rl_escalation import RLEscalationStrategy
                    self._rl_escalation = RLEscalationStrategy()
                available_agents = list(self.ctx.agents.keys()) if self.ctx.agents else []
                escalation_decision = self._rl_escalation.diagnose_and_decide(
                    task_id=task.id,
                    error_signature=error_sig,
                    error_full=outcome.failure_detail,
                    current_agent_id=agent_id,
                    available_agents=available_agents,
                    excluded_agents=task.excluded_agents,
                )
                task_ctx.previous_escalation_diagnosis = escalation_decision.diagnosis
                self._last_escalation_decision = escalation_decision

                await self.ctx.repository.log_episode(
                    session_id=self.session_id,
                    event_type="rl_escalation_diagnosis",
                    event_data={
                        "task_id": task.id,
                        "tier": escalation_decision.tier,
                        "action": escalation_decision.action.value,
                        "category": escalation_decision.error_category,
                        "diagnosis": escalation_decision.diagnosis[:500],
                    },
                    project_id=self.project_id,
                    task_id=task.id,
                    cycle_level="micro",
                )

                from claw.evolution.rl_escalation import EscalationAction
                if escalation_decision.action == EscalationAction.ROTATE_AGENT:
                    for excluded_agent in escalation_decision.excluded_agents:
                        if excluded_agent not in task.excluded_agents:
                            task.excluded_agents.append(excluded_agent)
                    await self.ctx.repository.update_task_excluded_agents(
                        task.id, task.excluded_agents,
                    )

                try:
                    prevention_hint = (
                        f"[{escalation_decision.error_category}] "
                        f"{escalation_decision.diagnosis[:300]}"
                    )
                    await self.ctx.repository.record_failure_knowledge(
                        error_signature=error_sig,
                        error_category=escalation_decision.error_category,
                        diagnosis=escalation_decision.diagnosis[:500],
                        prevention_hint=prevention_hint,
                        agent_id=agent_id,
                        task_type=task.task_type,
                        project_id=self.project_id,
                        source_task_id=task.id,
                    )
                except Exception as fk_err:
                    logger.debug("Failed to record failure knowledge: %s", fk_err)
            except Exception as e:
                logger.debug("RL escalation diagnosis failed: %s", e)

            # Reset to PENDING for retry
            await self.ctx.repository.update_task_status(task.id, TaskStatus.PENDING)

            # Infrastructure failures (agent output format, missing API key, HTTP
            # errors) are NOT the methodology's fault.  Only penalize methodologies
            # when the failure is content-related (the approach itself was wrong).
            _INFRASTRUCTURE_ERRORS = frozenset({
                "structured_execution_failed",
                "structured_output_missing",
                "file_operations_missing",
                "no_model",
                "no_api_key",
                "timeout",
                "TimeoutError",
                "ConnectError",
            })
            is_infrastructure_failure = (
                error_sig in _INFRASTRUCTURE_ERRORS
                or error_sig.startswith("http_")
            )

            if self.ctx.semantic_memory is not None:
                for methodology_id, relevance in used_methodologies:
                    try:
                        if is_infrastructure_failure:
                            # Log for audit trail but do NOT penalize the methodology
                            await self.ctx.repository.log_methodology_usage(
                                MethodologyUsageEntry(
                                    task_id=task.id,
                                    methodology_id=methodology_id,
                                    project_id=self.project_id,
                                    stage="used_in_outcome",
                                    agent_id=agent_id,
                                    success=False,
                                    expectation_match_score=verification.expectation_match_score,
                                    quality_score=verification.quality_score,
                                    relevance_score=relevance,
                                    notes=f"Infrastructure failure ({error_sig}); methodology not penalized",
                                )
                            )
                            logger.info(
                                "Skipping methodology penalty for %s: infrastructure failure (%s)",
                                methodology_id[:8], error_sig,
                            )
                        else:
                            await self.ctx.repository.log_methodology_usage(
                                MethodologyUsageEntry(
                                    task_id=task.id,
                                    methodology_id=methodology_id,
                                    project_id=self.project_id,
                                    stage="used_in_outcome",
                                    agent_id=agent_id,
                                    success=False,
                                    expectation_match_score=verification.expectation_match_score,
                                    quality_score=verification.quality_score,
                                    relevance_score=relevance,
                                    notes="Retrieved methodology inferred in failed outcome",
                                )
                            )
                            await self.ctx.repository.log_methodology_usage(
                                MethodologyUsageEntry(
                                    task_id=task.id,
                                    methodology_id=methodology_id,
                                    project_id=self.project_id,
                                    stage="outcome_attributed",
                                    agent_id=agent_id,
                                    success=False,
                                    expectation_match_score=verification.expectation_match_score,
                                    quality_score=verification.quality_score,
                                    relevance_score=relevance,
                                    notes="Failed outcome attributed to retrieved methodology",
                                )
                            )
                            await self.ctx.semantic_memory.record_outcome(
                                methodology_id,
                                success=False,
                                retrieval_relevance=relevance,
                                source_db_path=self._current_source_map.get(methodology_id),
                            )
                    except Exception as e:
                        logger.warning(
                            "Failed to record failed methodology usage for %s: %s",
                            methodology_id,
                            e,
                        )

            # Bandit: record failure for content failures only (not infra)
            if not is_infrastructure_failure:
                task_type = task.task_type or "general"
                for methodology_id, _rel in used_methodologies:
                    try:
                        await self.ctx.repository.record_bandit_outcome(
                            methodology_id, task_type, success=False
                        )
                    except Exception:
                        pass  # Non-critical

            logger.info(
                "Learned: task %s failed by %s (error: %s)",
                task.title, agent_id, error_sig,
            )

        # Record co-retrieval outcome for stigmergic link strengthening
        if self.ctx.semantic_memory is not None and len(used_methodologies) >= 2:
            try:
                co_ids = [mid for mid, _ in used_methodologies]
                await self.ctx.semantic_memory.record_co_retrieval_outcome(
                    co_ids, success=verification.approved
                )
            except Exception as e:
                logger.warning("Failed to record co-retrieval outcome: %s", e)

        # A/B ablation: record sample for knowledge ablation test
        if self._ablation_label is not None and self.ctx.prompt_evolver is not None:
            try:
                await self.ctx.prompt_evolver.record_sample(
                    prompt_name="knowledge_ablation",
                    variant_label=self._ablation_label,
                    agent_id=None,
                    success=verification.approved,
                    quality_score=verification.quality_score or 0.0,
                )
                logger.info(
                    "A/B ablation sample: label=%s success=%s quality=%.2f",
                    self._ablation_label,
                    verification.approved,
                    verification.quality_score or 0.0,
                )
            except Exception as e:
                logger.warning("Failed to record ablation sample: %s", e)

        # Record multi-dimensional quality sample for enriched A/B analysis
        if self._ablation_label is not None:
            try:
                # Compute SWE dimensions using the verifier
                correction_attempts = getattr(task_ctx, "correction_feedback", None)
                attempt_count = (correction_attempts.attempt_number + 1) if correction_attempts else 1
                tokens_used = outcome.tokens_used or 0
                token_budget = getattr(self.ctx.config.orchestrator, "token_budget", 100000) or 100000

                if self.ctx.verifier is not None:
                    dims = self.ctx.verifier.compute_swe_dimensions(
                        verification,
                        correction_attempts=attempt_count,
                        tokens_used=tokens_used,
                        token_budget=token_budget,
                    )
                    verification.swe_dimensions = dims

                    # Determine error category for failure cases
                    error_category = None
                    if not verification.approved and outcome.failure_reason:
                        try:
                            from claw.evolution.rl_escalation import classify_error
                            error_category = classify_error(
                                outcome.failure_reason + " " + (outcome.failure_detail or "")
                            )
                        except ImportError:
                            error_category = outcome.failure_reason

                    await self.ctx.repository.record_quality_sample(
                        project_id=self.project_id,
                        task_id=task.id,
                        variant_label=self._ablation_label,
                        agent_id=agent_id,
                        d_functional_correctness=dims.functional_correctness,
                        d_structural_compliance=dims.structural_compliance,
                        d_intent_alignment=dims.intent_alignment,
                        d_correction_efficiency=dims.correction_efficiency,
                        d_token_economy=dims.token_economy,
                        d_expectation_match=dims.expectation_match,
                        composite_score=dims.composite_score,
                        correction_attempts=attempt_count,
                        escalation_tier=0,
                        tokens_used=tokens_used,
                        duration_seconds=outcome.duration_seconds or 0.0,
                        success=verification.approved,
                        error_category=error_category,
                    )
                    logger.info(
                        "Recorded quality sample: label=%s composite=%.3f dims=[%.2f,%.2f,%.2f,%.2f,%.2f,%.2f]",
                        self._ablation_label,
                        dims.composite_score,
                        dims.functional_correctness,
                        dims.structural_compliance,
                        dims.intent_alignment,
                        dims.correction_efficiency,
                        dims.token_economy,
                        dims.expectation_match,
                    )
            except Exception as e:
                logger.warning("Failed to record quality sample: %s", e)

        if task.action_template_id:
            try:
                await self.ctx.repository.update_action_template_outcome(
                    task.action_template_id,
                    verification.approved,
                )
            except Exception as e:
                logger.warning(
                    "Failed to update action template outcome for %s: %s",
                    task.action_template_id,
                    e,
                )

        # Governance sweep (periodic, amortized over cycles)
        if self.ctx.governance is not None:
            try:
                swept = await self.ctx.governance.maybe_run_sweep()
                if swept:
                    logger.info("Governance sweep completed during learn phase")
            except Exception as e:
                logger.warning("Governance sweep failed: %s", e)

        # Log episode
        await self.ctx.repository.log_episode(
            session_id=self.session_id,
            event_type="cycle_completed",
            event_data={
                "task_id": task.id,
                "agent_id": agent_id,
                "approved": verification.approved,
                "quality_score": verification.quality_score,
            },
            project_id=self.project_id,
            agent_id=agent_id,
            task_id=task.id,
            cycle_level="micro",
        )


class MesoClaw(ClawCycle):
    """Project-level cycle: evaluate repo -> plan tasks -> run MicroClaw for each.

    MesoClaw operates at the project level. It runs the evaluation battery
    against a repository to identify issues, plans tasks from the findings,
    stores the tasks, and then spawns MicroClaw cycles for each task.

    After all MicroClaw cycles complete, MesoClaw triggers prompt evolution
    if enough samples have been collected.
    """

    def __init__(
        self,
        ctx: ClawContext,
        project_id: str,
        repo_path: str,
        session_id: Optional[str] = None,
    ):
        super().__init__(ctx, level="meso")
        self.project_id = project_id
        self.repo_path = repo_path
        self.session_id = session_id or str(uuid.uuid4())

    async def grab(self) -> Any:
        """Return the repo path as the target."""
        return self.repo_path

    async def evaluate(self, target: Any) -> Any:
        """Run the evaluation battery against the repository.

        Uses the Evaluator to execute all 17 prompts (or as many as
        the dispatcher can handle) and collects the results into an
        EvaluationReport.
        """
        from claw.evaluator import Evaluator

        evaluator = Evaluator(
            repository=self.ctx.repository,
            dispatcher=self.ctx.dispatcher,
        )
        report = await evaluator.run_battery(self.project_id, str(target))

        logger.info(
            "MesoClaw evaluation complete: %d/%d prompts succeeded",
            report.successful_prompts, report.total_prompts,
        )
        return report

    async def decide(self, evaluation: Any) -> Any:
        """Plan tasks from evaluation results.

        Converts the EvaluationReport's phase/prompt results into
        EvaluationResult objects that the Planner can consume, then
        runs gap analysis to generate a prioritized task list.
        """
        from claw.planner import EvaluationResult, Planner

        planner = Planner(
            project_id=self.project_id,
            repository=self.ctx.repository,
        )

        # Convert EvaluationReport phases/prompts into EvaluationResult objects
        eval_results: list[EvaluationResult] = []
        for phase in evaluation.phases:
            for pr in phase.prompt_results:
                if pr.output:
                    eval_results.append(EvaluationResult(
                        prompt_name=pr.prompt_name,
                        findings=[pr.output],
                        severity="medium",
                        category=phase.phase_name,
                        raw_output=pr.output,
                    ))

        tasks = await planner.analyze_gaps(eval_results)
        logger.info(
            "MesoClaw planning complete: %d tasks generated from %d evaluation results",
            len(tasks), len(eval_results),
        )
        return tasks

    async def act(self, decision: Any) -> Any:
        """Store tasks and run MicroClaw for each.

        Creates each planned task in the database, then runs a MicroClaw
        cycle for each task in sequence. Collects all cycle results.
        """
        tasks = decision
        results: list[CycleResult] = []

        for task in tasks:
            await self.ctx.repository.create_task(task)

        micro = MicroClaw(
            ctx=self.ctx,
            project_id=self.project_id,
            session_id=self.session_id,
        )

        for _ in range(len(tasks)):
            result = await micro.run_cycle()
            results.append(result)

        logger.info(
            "MesoClaw executed %d MicroClaw cycles (%d successful)",
            len(results), sum(1 for r in results if r.success),
        )
        return results

    async def verify(self, result: Any) -> Any:
        """Aggregate MicroClaw results.

        Returns a tuple of (successes, total, results_list) for the
        learn phase to consume.
        """
        results: list[CycleResult] = result
        successes = sum(1 for r in results if r.success)
        total = len(results)

        logger.info(
            "MesoClaw verification: %d/%d MicroClaw cycles succeeded",
            successes, total,
        )
        return (successes, total, results)

    async def learn(self, outcome: Any) -> None:
        """Update routing and trigger prompt evolution after enough samples.

        After all MicroClaw cycles complete, evaluates A/B tests for
        all prompts that have both control and variant rows, and
        promotes winners. Also logs the meso-level cycle completion.
        """
        successes, total, results = outcome

        # Trigger prompt evolution after enough samples
        if self.ctx.prompt_evolver is not None and total >= 5:
            try:
                # Evaluate A/B tests for all prompts with active tests
                tests = await self.ctx.prompt_evolver.list_tests()
                for test_group in tests:
                    prompt_name = test_group["prompt_name"]
                    agent_id = test_group.get("agent_id")
                    eval_result = await self.ctx.prompt_evolver.evaluate_test(
                        prompt_name, agent_id
                    )
                    if eval_result.get("ready") and eval_result.get("winner"):
                        await self.ctx.prompt_evolver.promote_variant(
                            prompt_name,
                            eval_result["winner"],
                            agent_id,
                        )
                        logger.info(
                            "Promoted prompt variant '%s/%s' (agent=%s)",
                            prompt_name, eval_result["winner"], agent_id,
                        )
            except Exception as e:
                logger.warning("Prompt evolution failed: %s", e)

        await self.ctx.repository.log_episode(
            session_id=self.session_id,
            event_type="meso_cycle_completed",
            event_data={"successes": successes, "total": total},
            project_id=self.project_id,
            cycle_level="meso",
        )

        logger.info(
            "MesoClaw learn complete: %d/%d tasks succeeded", successes, total,
        )

    async def run_cycle(self, on_step=None) -> CycleResult:
        """Execute one complete MesoClaw cycle.

        Overrides the base run_cycle to handle MesoClaw-specific flow
        where grab() returns a string (repo_path) not a Task, and
        verify/learn return aggregated results.
        """
        def _step(name: str, detail: str = "") -> None:
            if on_step is not None:
                on_step(name, detail)

        start = time.monotonic()
        try:
            _step("grab", f"Targeting repo: {self.repo_path}")
            target = await self.grab()

            _step("evaluate", f"Running evaluation battery on {target}")
            evaluation = await self.evaluate(target)

            _step("decide", "Planning tasks from evaluation...")
            decision = await self.decide(evaluation)

            _step("act", f"Running {len(decision)} MicroClaw cycles...")
            result = await self.act(decision)

            _step("verify", "Aggregating results...")
            verification = await self.verify(result)

            _step("learn", "Updating routing and prompt evolution...")
            await self.learn(verification)

            duration = time.monotonic() - start
            successes, total, _results = verification
            _step("done", f"MesoClaw complete: {successes}/{total} ({duration:.1f}s)")

            return CycleResult(
                cycle_level=self.level,
                project_id=self.project_id,
                success=successes > 0,
                duration_seconds=duration,
            )
        except Exception as e:
            duration = time.monotonic() - start
            logger.error("MesoClaw cycle failed: %s", e, exc_info=True)
            return CycleResult(
                cycle_level=self.level,
                project_id=self.project_id,
                success=False,
                duration_seconds=duration,
            )


class NanoClaw(ClawCycle):
    """Self-improvement cycle: update scores, routing, prompt variants.

    NanoClaw runs after task cycles to optimize the system itself.
    It evaluates current routing/prompt performance, extracts patterns
    from completed work, evaluates A/B tests, and promotes winning
    prompt variants.

    Unlike MicroClaw and MesoClaw, NanoClaw does not process external
    work -- it improves the internal machinery.
    """

    def __init__(self, ctx: ClawContext, project_id: str):
        super().__init__(ctx, level="nano")
        self.project_id = project_id

    async def grab(self) -> Any:
        """Get recent cycle results to learn from.

        Returns the project_id as the target for self-improvement.
        """
        return self.project_id

    async def evaluate(self, target: Any) -> Any:
        """Assess current routing and prompt performance.

        Gathers task status summary and pattern extraction summary
        to understand what can be improved.
        """
        summary = await self.ctx.repository.get_task_status_summary(target)

        pattern_summary = None
        if self.ctx.pattern_learner is not None:
            try:
                pattern_summary = await self.ctx.pattern_learner.get_pattern_summary(
                    target
                )
            except Exception as e:
                logger.warning("Pattern summary failed: %s", e)

        return {
            "task_summary": summary,
            "pattern_summary": pattern_summary,
            "project_id": target,
        }

    async def decide(self, evaluation: Any) -> Any:
        """Determine what self-improvement actions to take.

        Based on the evaluation, decides which optimization actions
        are available and should be executed.
        """
        actions: list[str] = []

        if self.ctx.prompt_evolver is not None:
            actions.append("evolve_prompts")
        if self.ctx.pattern_learner is not None:
            actions.append("extract_patterns")
        if self.ctx.self_consumer is not None:
            actions.append("self_consume")
        if self.ctx.assimilation_engine is not None:
            actions.append("enrich_capabilities")

        return actions

    async def act(self, decision: Any) -> Any:
        """Execute self-improvement actions.

        Runs prompt evolution (A/B test evaluation + promotion),
        pattern extraction, and self-consumption based on the
        decided actions.
        """
        actions = decision
        results: dict[str, Any] = {}

        if "evolve_prompts" in actions and self.ctx.prompt_evolver is not None:
            try:
                tests = await self.ctx.prompt_evolver.list_tests()
                promoted_count = 0
                for test_group in tests:
                    prompt_name = test_group["prompt_name"]
                    agent_id = test_group.get("agent_id")
                    eval_result = await self.ctx.prompt_evolver.evaluate_test(
                        prompt_name, agent_id
                    )
                    if eval_result.get("ready") and eval_result.get("winner"):
                        await self.ctx.prompt_evolver.promote_variant(
                            prompt_name,
                            eval_result["winner"],
                            agent_id,
                        )
                        promoted_count += 1
                results["prompt_evolution"] = f"evaluated {len(tests)} tests, promoted {promoted_count}"
            except Exception as e:
                results["prompt_evolution"] = f"failed: {e}"
                logger.warning("NanoClaw prompt evolution failed: %s", e)

        if "extract_patterns" in actions and self.ctx.pattern_learner is not None:
            try:
                patterns = await self.ctx.pattern_learner.extract_patterns(
                    self.project_id
                )
                results["patterns_extracted"] = len(patterns)
            except Exception as e:
                results["patterns_extracted"] = f"failed: {e}"
                logger.warning("NanoClaw pattern extraction failed: %s", e)

        if "self_consume" in actions and self.ctx.self_consumer is not None:
            try:
                sc_report = await self.ctx.self_consumer.run_full_consumption(
                    self.project_id
                )
                results["self_consumption"] = {
                    "patterns_found": sc_report.patterns_found,
                    "patterns_stored": sc_report.patterns_stored,
                    "blocked_dedup": sc_report.patterns_blocked_dedup,
                    "blocked_generation": sc_report.patterns_blocked_generation,
                    "analysis_types": sc_report.analysis_types,
                }
                logger.info(
                    "NanoClaw self-consumption: found=%d, stored=%d",
                    sc_report.patterns_found, sc_report.patterns_stored,
                )
            except Exception as e:
                results["self_consumption"] = f"failed: {e}"
                logger.warning("NanoClaw self-consumption failed: %s", e)

        # Capability enrichment sweep: find unenriched methodologies and assimilate
        if "enrich_capabilities" in actions and self.ctx.assimilation_engine is not None:
            try:
                self.ctx.assimilation_engine.reset_cycle_counter()
                unenriched = await self.ctx.repository.get_methodologies_without_capability_data(
                    limit=5
                )
                enriched_count = 0
                for meth in unenriched:
                    try:
                        result_info = await self.ctx.assimilation_engine.assimilate(meth.id)
                        if result_info.get("enriched"):
                            enriched_count += 1
                    except Exception as e:
                        logger.debug("Enrichment failed for %s: %s", meth.id, e)
                results["capability_enrichment"] = {
                    "unenriched_found": len(unenriched),
                    "enriched": enriched_count,
                }
                logger.info(
                    "NanoClaw capability enrichment: %d/%d enriched",
                    enriched_count, len(unenriched),
                )
            except Exception as e:
                results["capability_enrichment"] = f"failed: {e}"
                logger.warning("NanoClaw capability enrichment failed: %s", e)

        return results

    async def verify(self, result: Any) -> Any:
        """Verify self-improvement results.

        Self-improvement is self-verifying through A/B tests and
        pattern confidence scores. The act results are passed through.
        """
        return result

    async def learn(self, outcome: Any) -> None:
        """Log self-improvement cycle completion."""
        await self.ctx.repository.log_episode(
            session_id=str(uuid.uuid4()),
            event_type="nano_cycle_completed",
            event_data=outcome if isinstance(outcome, dict) else {"result": str(outcome)},
            project_id=self.project_id,
            cycle_level="nano",
        )

        logger.info(
            "NanoClaw cycle complete for project %s: %s",
            self.project_id, outcome,
        )

    async def run_cycle(self, on_step=None) -> CycleResult:
        """Execute one complete NanoClaw self-improvement cycle.

        Overrides the base run_cycle because NanoClaw's grab() returns
        a string (project_id) not a Task, and the verify/learn flow
        differs from the micro-level tuple unpacking.
        """
        def _step(name: str, detail: str = "") -> None:
            if on_step is not None:
                on_step(name, detail)

        start = time.monotonic()
        try:
            _step("grab", f"Self-improvement for project {self.project_id}")
            target = await self.grab()

            _step("evaluate", "Assessing routing and prompt performance...")
            evaluation = await self.evaluate(target)

            _step("decide", "Determining optimization actions...")
            decision = await self.decide(evaluation)

            _step("act", f"Executing: {', '.join(decision)}")
            result = await self.act(decision)

            _step("verify", "Verifying self-improvement...")
            verification = await self.verify(result)

            _step("learn", "Logging self-improvement outcome...")
            await self.learn(verification)

            duration = time.monotonic() - start
            _step("done", f"NanoClaw complete ({duration:.1f}s)")

            return CycleResult(
                cycle_level=self.level,
                project_id=self.project_id,
                success=True,
                duration_seconds=duration,
            )
        except Exception as e:
            duration = time.monotonic() - start
            logger.error("NanoClaw cycle failed: %s", e, exc_info=True)
            return CycleResult(
                cycle_level=self.level,
                project_id=self.project_id,
                success=False,
                duration_seconds=duration,
            )
