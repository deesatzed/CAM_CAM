"""Repo Mining for CLAW.

Scans local repositories, extracts patterns/features/ideas via LLM analysis,
stores findings in semantic memory, and generates enhancement tasks.

Usage:
    miner = RepoMiner(repository, llm_client, semantic_memory, config)
    report = await miner.mine_directory("/path/to/repos", project_id)
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import re
import time
import hashlib
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from claw.core.config import AgentConfig, BrainConfig, ClawConfig, DatabaseConfig
from claw.core.models import (
    ActionTemplate,
    ComponentCard,
    ComponentFit,
    CoverageState,
    FitBucket,
    Methodology,
    Project,
    Receipt,
    Task,
    TaskStatus,
    TransferMode,
)
from claw.connectome.barcodes import build_family_barcode, build_source_barcode
from claw.connectome.lineage import build_initial_lineage, rebuild_lineage_stats
from claw.db.engine import DatabaseEngine
from claw.db.repository import Repository
from claw.llm.client import LLMClient, LLMMessage, LLMResponse
from claw.core.exceptions import ModelNotFoundError
from claw.mining.component_extractor import extract_components_from_file
from claw.mining.scip_loader import load_repo_scip
from claw.memory.semantic import SemanticMemory
from claw.memory.cag_staleness import maybe_mark_cag_stale

logger = logging.getLogger("claw.miner")


# ---------------------------------------------------------------------------
# Ganglion auto-provisioning for language-specific brains
# ---------------------------------------------------------------------------

async def ensure_language_ganglion(
    brain_name: str,
    brain_config: BrainConfig,
    primary_repository: Repository,
    primary_semantic: SemanticMemory,
    config: ClawConfig,
) -> tuple[Repository, SemanticMemory]:
    """Get or create the ganglion DB for a language brain.

    For the Python brain (ganglion_name == ""), returns the primary
    repository and semantic memory unchanged.

    For non-Python brains, auto-provisions a ganglion at
    ``data/instances/{ganglion_name}/claw.db`` if it doesn't exist,
    initializes the schema, and returns a connected Repository +
    SemanticMemory pair targeting that ganglion.

    Args:
        brain_name: Brain identifier (e.g. "typescript", "go").
        brain_config: BrainConfig for this brain.
        primary_repository: The primary (Python) Repository.
        primary_semantic: The primary SemanticMemory.
        config: Full ClawConfig (for embedding config, etc.).

    Returns:
        (Repository, SemanticMemory) targeting the correct ganglion DB.
    """
    ganglion_name = brain_config.ganglion_name
    if not ganglion_name:
        # Python brain → use primary DB.
        return primary_repository, primary_semantic

    # Determine ganglion DB path relative to the project root.
    project_root = Path(config.database.db_path).parent.parent
    ganglion_dir = project_root / "instances" / ganglion_name
    ganglion_db_path = ganglion_dir / "claw.db"

    needs_init = not ganglion_db_path.exists()

    # Create engine + connect
    db_config = DatabaseConfig(db_path=str(ganglion_db_path))
    engine = DatabaseEngine(db_config)
    await engine.connect()

    # Always run migrations so existing ganglion DBs pick up new columns
    # (e.g. accuracy_contract added in migration 20).
    await engine.apply_migrations()

    if needs_init:
        await engine.initialize_schema()
        logger.info(
            "Auto-provisioned ganglion '%s' at %s",
            ganglion_name, ganglion_db_path,
        )

        # Auto-register as sibling in claw.toml if not already registered.
        _register_sibling_if_needed(
            ganglion_name, str(ganglion_db_path.resolve()), config,
        )
    else:
        logger.debug(
            "Reusing existing ganglion '%s' at %s",
            ganglion_name, ganglion_db_path,
        )

    repo = Repository(engine)

    # Build a SemanticMemory for this ganglion.
    # Reuse the primary's embedding engine (model is shared).
    from claw.memory.hybrid_search import HybridSearch
    hybrid = HybridSearch(
        repository=repo,
        embedding_engine=primary_semantic.embedding_engine,
    )
    sem = SemanticMemory(
        repository=repo,
        embedding_engine=primary_semantic.embedding_engine,
        hybrid_search=hybrid,
    )

    return repo, sem


async def _close_temporary_ganglion_repository(
    target_repository: Repository,
    primary_repository: Repository,
) -> None:
    """Close a mining-created ganglion engine without touching primary DB."""
    if (
        target_repository is primary_repository
        or target_repository.engine is primary_repository.engine
    ):
        return
    try:
        await target_repository.engine.close()
    except Exception as e:
        logger.warning("Failed to close temporary ganglion repository: %s", e)


def _register_sibling_if_needed(
    name: str, db_path: str, config: ClawConfig,
) -> None:
    """Append a [[instances.siblings]] entry to claw.toml if not already there."""
    # Check if already registered.
    for sib in config.instances.siblings:
        if sib.name == name:
            return

    toml_path = Path("claw.toml")
    if not toml_path.exists():
        logger.warning("claw.toml not found — cannot auto-register ganglion '%s'", name)
        return

    entry = (
        f'\n[[instances.siblings]]\n'
        f'name = "{name}"\n'
        f'db_path = "{db_path}"\n'
        f'description = "{name.title()} language patterns mined by CAM {name} brain"\n'
    )
    with toml_path.open("a") as f:
        f.write(entry)
    logger.info("Auto-registered ganglion '%s' in claw.toml", name)

# ---------------------------------------------------------------------------
# Application-domain keywords for automatic classification
# ---------------------------------------------------------------------------

_APPLICATION_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "medical": [
        "fhir", "hl7", "hipaa", "dicom", "ehr", "emr", "clinical",
        "patient", "diagnosis", "pharmacy", "icd10", "snomed", "loinc",
        "healthcare", "medical", "radiology", "pathology",
    ],
    "finance": [
        "trading", "portfolio", "hedge", "market", "ticker", "forex",
        "fintech", "banking", "payment", "ledger", "accounting",
        "blockchain", "defi", "invoice", "kyc", "aml",
    ],
    "ai_ml": [
        "transformer", "embedding", "llm", "rag", "vector", "agent",
        "diffusion", "tokenizer", "fine-tune", "finetune", "lora",
        "langchain", "openai", "anthropic", "huggingface",
    ],
    "devtools": [
        "cli", "linter", "formatter", "bundler", "compiler", "debugger",
        "profiler", "repl", "scaffold", "boilerplate", "template",
        "plugin", "extension", "vscode", "neovim",
    ],
    "infrastructure": [
        "kubernetes", "docker", "terraform", "ansible", "helm",
        "ci-cd", "pipeline", "deploy", "monitor", "observability",
        "prometheus", "grafana", "nginx", "caddy",
    ],
    "web_apps": [
        "nextjs", "react", "vue", "angular", "svelte", "remix",
        "express", "fastapi", "django", "flask", "rails",
        "graphql", "rest-api", "oauth", "jwt",
    ],
    "data_science": [
        "pandas", "numpy", "scipy", "matplotlib", "seaborn",
        "jupyter", "notebook", "etl", "warehouse", "spark",
        "airflow", "dbt", "bigquery", "snowflake",
    ],
}


@dataclass
class RepoProfile:
    """Classification + scoring metadata for a repo candidate."""
    candidate: RepoCandidate
    primary_brain: str = "python"
    technical_domains: list[str] = field(default_factory=list)
    application_domain: str = "general"
    complexity: str = "medium"
    yield_score: float = 0.5
    gap_score: float = 0.0
    ledger_status: str = "new"  # "new", "changed", "unchanged", "content-duplicate"


def classify_repo_domain(
    repo_path: Path,
    readme_text: str = "",
) -> str:
    """Classify a repo's application domain using keyword matching."""
    # Combine readme + filenames for classification
    readme_lower = readme_text.lower()
    filenames = ""
    try:
        for entry in os.scandir(repo_path):
            filenames += entry.name.lower() + " "
    except (PermissionError, OSError):
        pass
    corpus = f"{readme_lower} {filenames}"

    scores: dict[str, int] = {}
    for domain, keywords in _APPLICATION_DOMAIN_KEYWORDS.items():
        scores[domain] = sum(1 for kw in keywords if kw in corpus)

    if not scores or max(scores.values()) == 0:
        return "general"
    return max(scores, key=lambda d: scores[d])


async def ensure_domain_ganglion(
    domain_name: str,
    primary_repository: Repository,
    primary_semantic: SemanticMemory,
    config: ClawConfig,
) -> tuple[Repository, SemanticMemory]:
    """Get or create a ganglion DB for an application domain.

    Modeled on ensure_language_ganglion but for domain-specific ganglia
    (e.g., data/instances/domain-medical/claw.db).
    """
    ganglion_name = f"domain-{domain_name}"
    project_root = Path(config.database.db_path).parent.parent
    ganglion_dir = project_root / "instances" / ganglion_name
    ganglion_db_path = ganglion_dir / "claw.db"

    needs_init = not ganglion_db_path.exists()

    db_config = DatabaseConfig(db_path=str(ganglion_db_path))
    engine = DatabaseEngine(db_config)
    await engine.connect()

    # Always run migrations so existing ganglion DBs pick up new columns.
    await engine.apply_migrations()

    if needs_init:
        await engine.initialize_schema()
        logger.info(
            "Auto-provisioned domain ganglion '%s' at %s",
            ganglion_name, ganglion_db_path,
        )
        _register_sibling_if_needed(
            ganglion_name, str(ganglion_db_path.resolve()), config,
        )
    else:
        logger.debug(
            "Reusing existing domain ganglion '%s' at %s",
            ganglion_name, ganglion_db_path,
        )

    repo = Repository(engine)

    from claw.memory.hybrid_search import HybridSearch
    hybrid = HybridSearch(
        repository=repo,
        embedding_engine=primary_semantic.embedding_engine,
    )
    sem = SemanticMemory(
        repository=repo,
        embedding_engine=primary_semantic.embedding_engine,
        hybrid_search=hybrid,
    )

    return repo, sem


# Extensions to include when serializing a repo for mining.
_CODE_EXTENSIONS: set[str] = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".java",
    ".md", ".yaml", ".yml", ".toml", ".json", ".sql",
}

# Directories to skip during repo serialization.
_SKIP_DIRS: set[str] = {
    ".git", "node_modules", "__pycache__", ".venv",
    "venv", "dist", "build", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "egg-info",
    ".next", ".nuxt", "coverage", ".cache",
    "target",  # Rust/Java build output
    ".history",  # VS Code local history — wastes serialization budget
}

# Maximum serialized repo size in bytes (900 KB).
_MAX_REPO_BYTES: int = 900 * 1024

# Maximum bytes for a single file to be included in full during serialization.
# Files larger than this are reduced to a skeleton (signatures + docstrings).
_MAX_FILE_BYTES_FULL: int = 60 * 1024

# First-N-lines included verbatim in skeleton extraction (imports/docstring/module-level).
_SKELETON_HEAD_LINES: int = 30

# Max per-mining-call LLM timeout in seconds (prevents indefinite stalls
# from huge or malformed inputs). Wraps llm_client.complete() via asyncio.wait_for.
_MINING_LLM_TIMEOUT_SECONDS: float = 600.0  # 10 minutes

# Maximum bytes to read per file for content hashing (4 KB).
_CONTENT_HASH_CHUNK: int = 4096

# Maximum files to hash during content-level dedup.
_CONTENT_HASH_MAX_FILES: int = 200

# fnmatch patterns for machine-generated / vendored files — zero learning value.
_SKIP_FILE_PATTERNS: tuple[str, ...] = (
    "*.min.js", "*.min.css", "*.bundle.js", "*.chunk.js",
    "*-bundle.js", "*bundle*.js",
    "*.js.map", "*.css.map",
    "*_pb2.py", "*.pb.go", "*.pb.ts",
    "*.generated.*", "*.auto.*",
    "acl-manifests.json", "desktop-schema.json", "macOS-schema.json",
)

# Exact filenames to skip — lock files, legal boilerplate, linter config.
_SKIP_FILENAMES: set[str] = {
    # Lock files
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Pipfile.lock", "poetry.lock", "composer.lock",
    "Gemfile.lock", "Cargo.lock",
    # Legal / meta
    "LICENSE", "LICENSE.md", "LICENSE.txt",
    "CONTRIBUTING.md", "CONTRIBUTORS.md", "CODEOWNERS", ".mailmap",
    # Linter / formatter config
    ".prettierrc", ".prettierrc.json", ".eslintrc", ".eslintrc.json",
    ".eslintrc.js", ".editorconfig", ".gitattributes", ".gitignore",
    ".npmignore", ".dockerignore",
    # Bot config
    "renovate.json", "dependabot.yml", ".mergify.yml",
    # Documentation with zero mining value
    "CHANGELOG.md", "CHANGES.md", "HISTORY.md",
    "CODE_OF_CONDUCT.md", "SECURITY.md", "SUPPORT.md",
    "FUNDING.yml", ".github",
}

# fnmatch patterns for .md documentation files that waste serialization budget.
# PRDs, build checklists, status reports, white papers, executive briefings, etc.
# are verbose prose with no extractable code patterns. README.md and CLAUDE.md
# are kept (handled by _README_NAMES / explicit allowlist in filter).
# NOTE: all patterns are lowercase — matched against filepath.name.lower().
_SKIP_MD_PATTERNS: tuple[str, ...] = (
    "*prd*.md", "*_prd.md",
    "*checklist*.md",
    "*status*.md",
    "*report*.md",
    "*briefing*.md",
    "*white_paper*.md", "*whitepaper*.md",
    "*versionspec*.md", "*_spec.md", "*spec_*.md",
    "*_plan.md", "*plan_*.md",
    "*_guide.md", "*guide_*.md",
    "*_notes.md", "*notes_*.md",
    "*_log.md", "*log_*.md",
    "*meeting*.md",
    "*roadmap*.md",
    "*release*.md",
    "*migration*.md",
    "*tutorial*.md",
    "*blog*.md",
    "*faq*.md",
    "*troubleshoot*.md",
    "*decision*.md",
    "*retrospective*.md",
    "*onboarding*.md",
    "*postmortem*.md",
    "*runbook*.md",
    "*playbook*.md",
    "*governance*.md",
    "*compliance*.md",
    "*performance*.md",
    "*benchmark*.md",
    "*proposal*.md",
    "rfc_*.md", "rfc-*.md",
    "*enhancement*.md",
    "*pre_files*",
    "*action_plan*.md",
    "*handoff*.md",
    "*deployment*.md",
    "*testing_results*.md",
    "*_integration.md", "*_integration_*.md", "*integration_*.md",
    "*_implementation.md", "*_implementation_*.md", "*implementation_*.md",
    "*_infrastructure.md", "*_infrastructure_*.md", "*infrastructure_*.md",
    "*_documentation.md", "*_documentation_*.md",
    "*_summary.md", "*_summary_*.md",
    "*_validation.md", "*_validation_*.md", "validation_*.md",
    "*_breakthrough.md", "*_breakthrough_*.md",
)

# .md filenames explicitly allowed through the .md filter (mining-valuable docs).
_KEEP_MD_NAMES: set[str] = {
    "readme.md", "claude.md", "architecture.md", "design.md",
    "api.md", "contributing.md",  # contributing has code style info
}

# Maximum bytes for data-heavy files (.json, .yaml, .yml, .sql, .csv)
# before they are skipped entirely (data fixtures have no useful signatures).
_MAX_DATA_FILE_BYTES: int = 200 * 1024

# Extensions treated as data-heavy (subject to _MAX_DATA_FILE_BYTES gate).
_DATA_EXTENSIONS: set[str] = {".json", ".yaml", ".yml", ".sql", ".csv"}

# Maximum size for .md files to be serialized (15KB). Most useful .md docs
# (README, architecture) are under 15KB; large ones are prose-heavy docs.
_MAX_MD_FILE_BYTES: int = 15 * 1024


def _get_code_extensions(config: ClawConfig | None = None) -> set[str]:
    """Return merged code extensions: base defaults + config extras."""
    merged = set(_CODE_EXTENSIONS)
    if config and config.mining.extra_code_extensions:
        merged |= {ext if ext.startswith(".") else f".{ext}"
                    for ext in config.mining.extra_code_extensions}
    return merged


def _get_skip_dirs(config: ClawConfig | None = None) -> set[str]:
    """Return merged skip dirs: base defaults + config extras."""
    merged = set(_SKIP_DIRS)
    if config and config.mining.extra_skip_dirs:
        merged |= set(config.mining.extra_skip_dirs)
    return merged


def _load_mineignore(base_path: Path) -> list[str]:
    """Load .mineignore patterns from a directory.

    Supports gitignore-style patterns:
      - Lines starting with # are comments
      - Blank lines are ignored
      - Patterns are matched against relative paths
    """
    ignore_file = base_path / ".mineignore"
    if not ignore_file.is_file():
        return []
    try:
        patterns = []
        for line in ignore_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)
        return patterns
    except OSError:
        return []


def _is_mineignored(rel_path: str, patterns: list[str]) -> bool:
    """Check if a relative path matches any .mineignore pattern."""
    from fnmatch import fnmatch
    for pattern in patterns:
        # Strip trailing slash for directory patterns
        clean = pattern.rstrip("/")
        # Match against full relative path and individual path components
        if fnmatch(rel_path, pattern) or fnmatch(rel_path, f"**/{pattern}"):
            return True
        # Check if any path component matches exactly
        parts = rel_path.replace("\\", "/").split("/")
        if clean in parts:
            return True
        # Check fnmatch against each component
        for part in parts:
            if fnmatch(part, clean):
                return True
    return False

# Valid categories for findings.
_VALID_CATEGORIES: set[str] = {
    "architecture", "ai_integration", "memory", "code_quality",
    "cli_ux", "testing", "data_processing", "security",
    "algorithm", "cross_cutting", "design_patterns",
}

# Maximum findings per repo.
_MAX_FINDINGS_PER_REPO: int = 15

_CATEGORY_TRIGGER_MAP: dict[str, list[str]] = {
    "architecture": ["missing_packaging", "repo_structure", "entrypoint_clarity"],
    "ai_integration": ["model_integration", "agent_orchestration", "prompt_flow"],
    "memory": ["retrieval_quality", "knowledge_pack", "memory_schema"],
    "code_quality": ["quality_gate", "documentation_gap", "type_safety"],
    "cli_ux": ["cli_entrypoint", "operator_experience", "workflow_clarity"],
    "testing": ["missing_tests", "regression_risk", "verification_gap"],
    "data_processing": ["pipeline_gap", "ingestion_flow", "structured_data_flow"],
    "security": ["dynamic_execution_risk", "input_validation", "compliance_gap"],
    "algorithm": ["scoring_logic", "matching_strategy", "heuristic_refinement"],
    "cross_cutting": ["cross_domain_reuse", "observability_gap", "operationalization"],
}


@dataclass
class MiningFinding:
    """A single extracted pattern/feature/idea from a mined repo."""
    title: str
    description: str
    category: str
    source_repo: str
    source_files: list[str] = field(default_factory=list)
    source_symbols: list[dict[str, str]] = field(default_factory=list)
    implementation_sketch: str = ""
    augmentation_notes: str = ""
    relevance_score: float = 0.5
    language: str = "python"
    execution_steps: list[str] = field(default_factory=list)
    acceptance_checks: list[str] = field(default_factory=list)
    rollback_steps: list[str] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    action_template_id: Optional[str] = None


@dataclass
class KnowledgeOverlap:
    """Structured result of knowledge-base overlap assessment (Pass 2)."""
    repo_known_titles: list[str] = field(default_factory=list)
    domain_known_titles: list[str] = field(default_factory=list)
    domain_known_categories: list[str] = field(default_factory=list)
    overlap_score: float = 0.0
    suggested_focus: list[str] = field(default_factory=list)


# Domain keyword signals for rule-based classification (Pass 1).
# Each key is a category from _VALID_CATEGORIES; values are keywords to scan for.
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "ai_integration": [
        "agent", "llm", "prompt", "model", "openai", "anthropic", "gpt",
        "claude", "gemini", "langchain", "transformer", "inference",
        "chat", "completion", "embedding", "fine-tune", "rag",
    ],
    "architecture": [
        "middleware", "plugin", "router", "pipeline", "microservice",
        "event-driven", "message queue", "dependency injection", "decorator",
        "state machine", "orchestrat", "workflow", "dispatcher",
    ],
    "memory": [
        "embedding", "vector", "rag", "retrieval", "knowledge graph",
        "cache", "index", "faiss", "chromadb", "pinecone", "weaviate",
        "semantic search", "similarity",
    ],
    "code_quality": [
        "lint", "format", "type check", "mypy", "ruff", "eslint",
        "prettier", "refactor", "code review", "static analysis",
    ],
    "cli_ux": [
        "cli", "command line", "terminal", "argparse", "typer", "click",
        "rich", "tui", "interactive", "prompt_toolkit",
    ],
    "testing": [
        "test", "pytest", "jest", "unittest", "fixture", "coverage",
        "property-based", "hypothesis", "mock", "integration test",
    ],
    "data_processing": [
        "etl", "pipeline", "stream", "batch", "transform", "ingest",
        "dataframe", "pandas", "polars", "spark", "parquet", "csv",
    ],
    "security": [
        "auth", "encrypt", "token", "permission", "oauth", "jwt",
        "rbac", "cors", "csrf", "sanitiz", "xss", "injection",
        "certificate", "tls", "ssl",
    ],
    "algorithm": [
        "sort", "search", "graph", "tree", "optimization", "heuristic",
        "dynamic programming", "backtrack", "a-star", "dijkstra",
        "genetic", "bayesian", "monte carlo",
    ],
    "cross_cutting": [
        "logging", "metrics", "observability", "feature flag",
        "config", "telemetry", "tracing", "monitoring",
    ],
    "design_patterns": [
        "protocol", "frozen", "dataclass", "immutable", "idempotent",
        "dependency injection", "precedence", "fallback", "normalize",
        "result normalization", "backward compat", "hybrid protocol",
        "perf_counter", "duration_ms", "structured log",
    ],
}

# Config file names that signal specific languages.
_LANGUAGE_SIGNALS: dict[str, str] = {
    "pyproject.toml": "python", "setup.py": "python", "setup.cfg": "python",
    "requirements.txt": "python", "pipfile": "python",
    "package.json": "javascript", "tsconfig.json": "typescript",
    "cargo.toml": "rust", "go.mod": "go", "go.sum": "go",
    "pom.xml": "java", "build.gradle": "java", "build.gradle.kts": "kotlin",
    "gemfile": "ruby", "mix.exs": "elixir", "project.clj": "clojure",
}

# Map detected language strings to brain names (many-to-one).
_LANGUAGE_TO_BRAIN: dict[str, str] = {
    "python": "python",
    "typescript": "typescript",
    "javascript": "typescript",  # JS repos use the TS brain
    "go": "go",
    "rust": "rust",
    # Everything else → misc
    "java": "misc", "kotlin": "misc", "ruby": "misc",
    "elixir": "misc", "clojure": "misc", "unknown": "misc",
}

# Extension → language for the file-census tiebreaker.
_EXT_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java", ".kt": "kotlin",
    ".rb": "ruby", ".ex": "elixir", ".exs": "elixir",
    ".c": "misc", ".cpp": "misc", ".cc": "misc", ".h": "misc", ".hpp": "misc",
}

# Valid brain names that the user can pass via --brain.
VALID_BRAIN_NAMES: set[str] = {"python", "typescript", "go", "rust", "misc"}

# Reverse mapping: brain → set of file extensions that belong to it.
_BRAIN_EXTENSIONS: dict[str, set[str]] = {}
for _ext, _lang in _EXT_TO_LANGUAGE.items():
    _brain = _LANGUAGE_TO_BRAIN.get(_lang, "misc")
    _BRAIN_EXTENSIONS.setdefault(_brain, set()).add(_ext)

# Minimum thresholds for a language zone to be mined separately.
_MIN_ZONE_FILES: int = 3
_MIN_ZONE_PCT: float = 5.0


@dataclass
class LanguageZone:
    """A language zone detected within a repository."""

    brain: str  # Brain name: "python", "typescript", "go", "rust", "misc"
    file_count: int  # Number of source files in this zone
    file_extensions: set[str]  # Extensions in this zone (e.g. {".ts", ".tsx"})
    pct: float  # Percentage of total code files in repo


def should_skip_polyglot_zone(zone: LanguageZone, total_zones: int) -> bool:
    """Return True when a secondary polyglot zone is too small for a paid pass."""
    return total_zones > 1 and zone.file_count < _MIN_ZONE_FILES


def detect_all_repo_languages(
    repo_path: Path,
    config: ClawConfig | None = None,
) -> dict[str, LanguageZone]:
    """Detect ALL languages present in a repository.

    Walks the repo once, counts files per extension, aggregates by brain.
    Config-file signals (tsconfig.json, go.mod, etc.) ensure their language
    zone is always included even if file count is low.
    Skips zones below _MIN_ZONE_FILES or _MIN_ZONE_PCT thresholds
    (unless the zone has a config-file signal).

    Returns dict keyed by brain name (e.g. {"python": LanguageZone(...), "go": ...}).
    """
    if not repo_path.is_dir():
        return {}

    skip_dirs = _get_skip_dirs(config)
    code_exts = _get_code_extensions(config)

    # Collect config-file signals + count source files in one pass
    config_signal_langs: set[str] = set()
    ext_counts: dict[str, int] = {}
    for filepath in repo_path.rglob("*"):
        if not filepath.is_file():
            continue
        rel = filepath.relative_to(repo_path)
        if any(part in skip_dirs for part in rel.parts):
            continue
        name_lower = filepath.name.lower()
        if name_lower in _LANGUAGE_SIGNALS:
            config_signal_langs.add(_LANGUAGE_SIGNALS[name_lower])
        suffix = filepath.suffix.lower()
        if suffix in code_exts and suffix in _EXT_TO_LANGUAGE:
            ext_counts[suffix] = ext_counts.get(suffix, 0) + 1

    if not ext_counts and not config_signal_langs:
        return {}

    total_files = max(sum(ext_counts.values()), 1)

    # Aggregate by brain
    brain_files: dict[str, int] = {}
    brain_exts: dict[str, set[str]] = {}
    for ext, count in ext_counts.items():
        lang = _EXT_TO_LANGUAGE[ext]
        brain = _LANGUAGE_TO_BRAIN.get(lang, "misc")
        brain_files[brain] = brain_files.get(brain, 0) + count
        brain_exts.setdefault(brain, set()).add(ext)

    # Ensure config-signal languages are represented
    config_signal_brains: set[str] = set()
    for lang in config_signal_langs:
        brain = _LANGUAGE_TO_BRAIN.get(lang, "misc")
        config_signal_brains.add(brain)
        if brain not in brain_files:
            brain_files[brain] = 0
            brain_exts.setdefault(brain, set())
        # Add known extensions for this brain
        if brain in _BRAIN_EXTENSIONS:
            brain_exts[brain] |= _BRAIN_EXTENSIONS[brain]

    # Build zones, applying thresholds.
    # Config-signal brains bypass thresholds (tsconfig.json = always include TS zone).
    zones: dict[str, LanguageZone] = {}
    for brain, count in brain_files.items():
        pct = (count / total_files) * 100.0
        has_config_signal = brain in config_signal_brains
        if has_config_signal or (count >= _MIN_ZONE_FILES and pct >= _MIN_ZONE_PCT):
            zones[brain] = LanguageZone(
                brain=brain,
                file_count=count,
                file_extensions=brain_exts[brain],
                pct=round(pct, 1),
            )

    # If thresholds eliminated everything, include the largest zone anyway
    if not zones and brain_files:
        dominant_brain = max(brain_files, key=brain_files.get)  # type: ignore[arg-type]
        count = brain_files[dominant_brain]
        zones[dominant_brain] = LanguageZone(
            brain=dominant_brain,
            file_count=count,
            file_extensions=brain_exts[dominant_brain],
            pct=round((count / total_files) * 100.0, 1),
        )

    return zones


def detect_repo_language(
    repo_path: Path,
    config: ClawConfig | None = None,
) -> str:
    """Detect the primary language of a repository and return its brain name.

    Thin wrapper over detect_all_repo_languages() — returns the dominant brain.
    Config-file signals take priority: if tsconfig.json is present, TypeScript
    wins even when Python has more files (matching the old behavior).

    Returns one of: "python", "typescript", "go", "rust", "misc".
    """
    zones = detect_all_repo_languages(repo_path, config)
    if not zones:
        return "misc"

    # Config-file signal priority: check for authoritative config files
    # that should override pure file-count dominance.
    if not repo_path.is_dir():
        return "misc"
    skip_dirs = _get_skip_dirs(config)
    signal_brains: list[str] = []
    for filepath in repo_path.iterdir():
        if filepath.is_file():
            rel = filepath.relative_to(repo_path)
            if any(part in skip_dirs for part in rel.parts):
                continue
            name_lower = filepath.name.lower()
            if name_lower in _LANGUAGE_SIGNALS:
                lang = _LANGUAGE_SIGNALS[name_lower]
                brain = _LANGUAGE_TO_BRAIN.get(lang, "misc")
                if brain != "misc" and brain in zones:
                    signal_brains.append(brain)

    # TypeScript signal trumps all (tsconfig.json is authoritative).
    if "typescript" in signal_brains:
        return "typescript"
    # Other non-misc config signals take priority over file count.
    for brain in signal_brains:
        if brain != "misc":
            return brain

    # Fall back to file-count dominance.
    dominant = max(zones.values(), key=lambda z: z.file_count)
    return dominant.brain


# ---------------------------------------------------------------------------
# Context-aware mining model selector with RL learning
# ---------------------------------------------------------------------------

class MiningModelSelector:
    """Context-aware model selector for mining with RL learning.

    Responsibilities:
    1. Estimate prompt token count from serialized content length.
    2. Filter agents whose context_window_tokens can fit the prompt + headroom.
    3. Among eligible agents, prefer the one with the best learned success rate.
    4. On cold start (no data), use the escalation_order from config.
    5. Provide an ordered escalation chain for retry logic.
    """

    def __init__(
        self,
        config: ClawConfig,
        repository: Repository | None = None,
    ) -> None:
        self.config = config
        self.repository = repository

    def estimate_prompt_tokens(self, prompt: str) -> int:
        """Estimate token count from prompt character count.

        Uses configurable chars_per_token (default 4.0). Intentionally
        conservative — overestimating is safer than underestimating.
        """
        cpt = self.config.mining.recovery.token_estimate_chars_per_token
        return int(len(prompt) / cpt)

    def get_eligible_agents(
        self, estimated_tokens: int,
    ) -> list[tuple[str, AgentConfig]]:
        """Return agents whose context window can fit the prompt.

        Reserves headroom_pct for output tokens. Agents with
        context_window_tokens=0 (unknown) are included last as fallback.

        Returns list of (agent_name, agent_config) sorted by context
        window ascending (prefer smallest sufficient model for cost).
        """
        headroom = self.config.mining.recovery.min_context_headroom_pct
        required = int(estimated_tokens / (1.0 - headroom))

        eligible: list[tuple[str, AgentConfig, int]] = []
        unknown: list[tuple[str, AgentConfig]] = []

        for name, cfg in self.config.agents.items():
            if not cfg.enabled or not cfg.model:
                continue
            # Local agents use a different endpoint; the mining LLM client
            # only supports the OpenRouter base_url.
            if cfg.mode == "local":
                continue
            if cfg.context_window_tokens == 0:
                unknown.append((name, cfg))
                continue
            if cfg.context_window_tokens >= required:
                eligible.append((name, cfg, cfg.context_window_tokens))

        eligible.sort(key=lambda x: x[2])
        result = [(n, c) for n, c, _ in eligible]
        result.extend(unknown)
        return result

    def build_escalation_chain(
        self, estimated_tokens: int,
    ) -> list[tuple[str, str]]:
        """Build ordered (agent_name, model_id) escalation chain.

        Priority:
        1. Agents with sufficient context window (ascending by size)
        2. Agents from config escalation_order not yet included
        3. All remaining enabled agents
        """
        eligible = self.get_eligible_agents(estimated_tokens)
        chain: list[tuple[str, str]] = []
        seen_agents: set[str] = set()
        seen_models: set[str] = set()

        for name, cfg in eligible:
            if name not in seen_agents and cfg.model not in seen_models:
                chain.append((name, cfg.model))
                seen_agents.add(name)
                seen_models.add(cfg.model)

        for name in self.config.mining.recovery.escalation_order:
            if name not in seen_agents:
                cfg = self.config.agents.get(name)
                if cfg and cfg.enabled and cfg.model and cfg.model not in seen_models:
                    chain.append((name, cfg.model))
                    seen_agents.add(name)
                    seen_models.add(cfg.model)

        for name, cfg in self.config.agents.items():
            if (
                name not in seen_agents
                and cfg.enabled
                and cfg.model
                and cfg.model not in seen_models
            ):
                chain.append((name, cfg.model))
                seen_agents.add(name)
                seen_models.add(cfg.model)

        return chain

    async def select_best_model(
        self, estimated_tokens: int,
    ) -> tuple[str, str]:
        """Select best (agent_name, model_id) using RL data.

        If sufficient outcome data exists, returns the model with
        the highest success rate for this token-size bucket.
        Otherwise, falls back to the first eligible agent.

        Raises ValueError if no agents are available.
        """
        if self.repository:
            try:
                best_model = await self.repository.get_best_mining_model_for_size(
                    estimated_tokens, min_observations=3,
                )
                if best_model:
                    for name, cfg in self.config.agents.items():
                        if cfg.model == best_model and cfg.enabled:
                            logger.info(
                                "RL selected model %s (agent=%s) for ~%dK tokens",
                                best_model, name, estimated_tokens // 1000,
                            )
                            return name, best_model
            except Exception as e:
                logger.debug("RL model selection failed, using fallback: %s", e)

        chain = self.build_escalation_chain(estimated_tokens)
        if not chain:
            raise ValueError("No model configured in any agent. Set a model in claw.toml.")

        name, model = chain[0]
        logger.info(
            "Selected model %s (agent=%s) for ~%dK tokens (no RL data)",
            model, name, estimated_tokens // 1000,
        )
        return name, model


@dataclass
class PolyglotMiningResult:
    """Per-brain breakdown within a multi-pass polyglot mining result."""

    brain: str
    findings_count: int = 0
    methodology_ids: list[str] = field(default_factory=list)
    tokens_used: int = 0
    duration_seconds: float = 0.0
    error: str | None = None


@dataclass
class RepoMiningResult:
    """Results from mining a single repo."""
    repo_name: str
    repo_path: str
    findings: list[MiningFinding] = field(default_factory=list)
    files_analyzed: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    error: Optional[str] = None
    skipped: bool = False
    skip_reason: Optional[str] = None
    methodology_ids: list[str] = field(default_factory=list)
    action_template_ids: list[str] = field(default_factory=list)
    recovery_attempts: int = 0
    recovery_strategy: str = ""
    brain_breakdown: list[PolyglotMiningResult] = field(default_factory=list)


@dataclass
class MiningReport:
    """Aggregate results from mining a directory of repos."""
    repos_scanned: int = 0
    total_findings: int = 0
    tasks_generated: int = 0
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    total_duration_seconds: float = 0.0
    repos_skipped: int = 0
    repo_results: list[RepoMiningResult] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)


@dataclass
class RepoCandidate:
    """A discovered repo candidate with metadata for dedup decisions."""
    path: Path
    name: str                # directory name (e.g., "ace-forecaster-v3")
    canonical_name: str      # stripped name (e.g., "ace-forecaster")
    depth: int               # nesting depth from scan root
    source_kind: str = "git" # "git" or "source_tree"
    file_count: int = 0      # number of source files (proxy for completeness)
    last_commit_ts: float = 0.0  # timestamp of last git activity
    total_bytes: int = 0     # approximate source size
    scan_signature: str = "" # lightweight content/mtime signature for incremental mining
    content_hash: str = ""   # SHA-256 of file contents for cross-repo dedup


@dataclass
class RepoScanRecord:
    """Ledger entry for a previously mined repo."""
    repo_path: str
    repo_name: str
    canonical_name: str
    source_kind: str
    scan_signature: str
    file_count: int
    total_bytes: int
    last_commit_ts: float
    last_mined_at: float
    findings_count: int = 0
    tokens_used: int = 0
    content_hash: str = ""
    methodology_ids: list[str] = field(default_factory=list)
    action_template_ids: list[str] = field(default_factory=list)


class RepoScanLedger:
    """Persistent repo-mining ledger used to skip unchanged repos."""

    def __init__(self, path: Path):
        self.path = path
        self._records: dict[str, RepoScanRecord] = {}
        self._content_hash_index: dict[str, str] = {}  # content_hash → repo_path
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to load mining ledger %s", self.path)
            return

        raw_records = payload.get("records", {})
        if not isinstance(raw_records, dict):
            return

        for key, value in raw_records.items():
            if not isinstance(value, dict):
                continue
            try:
                self._records[key] = RepoScanRecord(**value)
                # Build content hash reverse index
                ch = value.get("content_hash", "")
                if ch:
                    self._content_hash_index[ch] = key
            except TypeError:
                continue

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "records": {
                key: record.__dict__
                for key, record in sorted(self._records.items())
            },
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def repo_key(repo_path: Path) -> str:
        try:
            return str(repo_path.resolve())
        except OSError:
            return str(repo_path)

    def get_record(self, repo_path: Path) -> Optional[RepoScanRecord]:
        self._load()
        return self._records.get(self.repo_key(repo_path))

    def list_records(self) -> list[RepoScanRecord]:
        self._load()
        return list(self._records.values())

    def should_mine(
        self,
        candidate: RepoCandidate,
        *,
        skip_known: bool = True,
        force_rescan: bool = False,
    ) -> tuple[bool, str]:
        if force_rescan:
            return True, "forced"
        if not skip_known:
            return True, "skip-known disabled"

        existing = self.get_record(candidate.path)
        if existing is None:
            # Check if any OTHER record has the same content_hash
            if candidate.content_hash:
                self._load()
                dup_path = self._content_hash_index.get(candidate.content_hash)
                if dup_path and dup_path != self.repo_key(candidate.path):
                    return False, f"content-duplicate of {dup_path}"
            return True, "new"
        if existing.scan_signature != candidate.scan_signature:
            return True, "changed"
        return False, "unchanged"

    def record_result(self, candidate: RepoCandidate, result: RepoMiningResult) -> None:
        self._load()
        key = self.repo_key(candidate.path)
        self._records[key] = RepoScanRecord(
            repo_path=key,
            repo_name=candidate.name,
            canonical_name=candidate.canonical_name,
            source_kind=candidate.source_kind,
            scan_signature=candidate.scan_signature,
            file_count=candidate.file_count,
            total_bytes=candidate.total_bytes,
            last_commit_ts=candidate.last_commit_ts,
            last_mined_at=time.time(),
            findings_count=len(result.findings),
            tokens_used=result.tokens_used,
            content_hash=candidate.content_hash,
            methodology_ids=list(result.methodology_ids),
            action_template_ids=list(result.action_template_ids),
        )
        # Update content hash index
        if candidate.content_hash:
            self._content_hash_index[candidate.content_hash] = key
        self._save()


# File names that should appear first so the LLM understands the repo's purpose.
_README_NAMES: set[str] = {"readme.md", "readme.rst", "readme.txt", "readme"}

# Config/manifest files that reveal project structure and dependencies.
_CONFIG_NAMES: set[str] = {
    "pyproject.toml", "setup.py", "setup.cfg", "package.json",
    "cargo.toml", "go.mod", "pom.xml", "build.gradle",
}

# Directories containing tests, docs, examples — lower priority.
_LOW_PRIORITY_DIRS: set[str] = {
    "tests", "test", "spec", "specs", "docs", "doc", "examples", "example",
    "benchmarks", "benchmark", "fixtures", "scripts", "tools", "demo",
}


def _file_priority(rel_path: Path) -> int:
    """Return sort priority for a file (lower = earlier in serialization).

    Tier 0: README — the repo's self-description
    Tier 1: Config/manifest files — project structure
    Tier 2: Core source files (src/, lib/, top-level modules)
    Tier 3: Tests, docs, examples, scripts
    """
    name_lower = rel_path.name.lower()
    if name_lower in _README_NAMES:
        return 0
    if name_lower in _CONFIG_NAMES:
        return 1
    if any(part in _LOW_PRIORITY_DIRS for part in rel_path.parts):
        return 3
    return 2


def _extract_skeleton(content: str, rel_path: Path) -> str:
    """Extract a compact skeleton from an oversized source file.

    Skeleton = first N lines verbatim (imports/docstring/module-level code)
    + all top-level class/function/def signatures with their docstrings
    + total line count + truncation marker.

    Supported languages: Python (.py), TypeScript/JavaScript (.ts/.tsx/.js/.jsx),
    Go (.go), Rust (.rs). For others, falls back to head-only truncation.
    """
    lines = content.splitlines()
    total_lines = len(lines)
    suffix = rel_path.suffix.lower()

    parts: list[str] = []
    parts.append(f"[SKELETON — full file is {total_lines} lines, "
                 f"{len(content.encode('utf-8')) // 1024}KB; showing head + signatures]")

    # Head: first N lines (imports, module docstring, top-level constants)
    head_lines = lines[:_SKELETON_HEAD_LINES]
    parts.append("\n".join(head_lines))
    parts.append(f"\n# ... ({total_lines - _SKELETON_HEAD_LINES} more lines) ...\n")

    # Signature extraction — language-specific regex
    sig_patterns: list[re.Pattern[str]] = []
    if suffix == ".py":
        # class Foo: / def bar( / async def baz(
        sig_patterns.append(re.compile(r"^(class\s+\w+|(?:async\s+)?def\s+\w+)"))
    elif suffix in {".ts", ".tsx", ".js", ".jsx"}:
        # class Foo / export class Foo / function bar / export function bar / const baz = (
        sig_patterns.append(re.compile(
            r"^(export\s+)?(abstract\s+)?(class|interface|type|function|async\s+function)\s+\w+"
        ))
        sig_patterns.append(re.compile(r"^(export\s+)?const\s+\w+\s*[:=]\s*(async\s+)?\("))
    elif suffix == ".go":
        # func Foo( / type Foo struct { / type Foo interface {
        sig_patterns.append(re.compile(r"^(func\s+(\(\w+\s+\*?\w+\)\s+)?\w+|type\s+\w+\s+(struct|interface))"))
    elif suffix == ".rs":
        # fn foo( / pub fn foo( / impl Foo { / struct Foo / enum Foo / trait Foo
        sig_patterns.append(re.compile(r"^(pub\s+)?(fn\s+\w+|impl(\s+<.*>)?\s+\w+|struct\s+\w+|enum\s+\w+|trait\s+\w+)"))

    if sig_patterns:
        signatures: list[str] = []
        for idx, line in enumerate(lines[_SKELETON_HEAD_LINES:], start=_SKELETON_HEAD_LINES):
            stripped = line.lstrip()
            # Skip deeply nested definitions (keep top-level + one indent level)
            indent = len(line) - len(stripped)
            if indent > 4:
                continue
            if any(p.match(stripped) for p in sig_patterns):
                # Take the signature line (may span multiple lines if args wrap)
                sig = line.rstrip()
                # Grab next line if docstring
                if idx + 1 < total_lines:
                    next_line = lines[idx + 1].lstrip()
                    if next_line.startswith(('"""', "'''", "//", "///", "/*")):
                        sig += "\n" + lines[idx + 1].rstrip()
                signatures.append(sig)
                if len(signatures) >= 80:  # Cap at 80 signatures per file
                    signatures.append("# ... (more signatures truncated) ...")
                    break

        if signatures:
            parts.append("\n# --- Top-level signatures ---")
            parts.append("\n".join(signatures))

    return "\n".join(parts) + "\n"


def serialize_repo(
    repo_path: str | Path,
    max_bytes: int = _MAX_REPO_BYTES,
    exclude_files: set[str] | None = None,
    config: ClawConfig | None = None,
    language_filter: set[str] | None = None,
) -> tuple[str, int]:
    """Read all source files in a directory and concatenate with file headers.

    Files are ordered by priority: README first, then config files, then core
    source, then tests/docs/examples. This ensures the LLM sees the project's
    self-description and structure before diving into code.

    Filters by common code extensions, skips binary/build directories,
    and limits total size to max_bytes.

    Args:
        repo_path: Absolute path to the repository root.
        max_bytes: Maximum serialized size in bytes.
        exclude_files: Set of relative file paths to skip (from secret scanner).
        config: Optional ClawConfig for extra extensions/skip dirs.
        language_filter: If set, only include files whose extension is in this
            set. README, config, and documentation files (.md, .toml, .yaml,
            .yml, .json) are always included for project context.

    Returns:
        Tuple of (serialized content, number of files read).
    """
    # Extensions always included regardless of language_filter (project context).
    _CONTEXT_EXTENSIONS: set[str] = {
        ".md", ".toml", ".yaml", ".yml", ".json", ".cfg", ".ini", ".txt",
    }

    root = Path(repo_path)
    if not root.is_dir():
        logger.warning("Repo path is not a directory: %s", repo_path)
        return "", 0

    code_exts = _get_code_extensions(config)
    skip_dirs = _get_skip_dirs(config)
    ignore_patterns = _load_mineignore(root)

    # Collect eligible files with priority ordering
    eligible: list[tuple[int, Path, Path]] = []  # (priority, rel_path, abs_path)
    for filepath in root.rglob("*"):
        if not filepath.is_file():
            continue
        rel = filepath.relative_to(root)
        if any(part in skip_dirs for part in rel.parts):
            continue
        suffix = filepath.suffix.lower()
        if suffix not in code_exts:
            continue
        # Skip generated/vendored/boilerplate files
        if filepath.name in _SKIP_FILENAMES:
            continue
        if any(fnmatch.fnmatch(filepath.name, pat) for pat in _SKIP_FILE_PATTERNS):
            continue
        # Skip non-essential .md documentation (PRDs, checklists, reports, etc.)
        if suffix == ".md":
            name_lower = filepath.name.lower()
            if name_lower not in _KEEP_MD_NAMES:
                if any(fnmatch.fnmatch(name_lower, pat) for pat in _SKIP_MD_PATTERNS):
                    continue
                # Also skip oversized .md files (>15KB = prose-heavy docs)
                try:
                    if filepath.stat().st_size > _MAX_MD_FILE_BYTES:
                        continue
                except OSError:
                    pass
        # Language filter: skip source files not in the target language,
        # but always keep context files (README, config, docs).
        if language_filter is not None:
            name_lower = filepath.name.lower()
            is_context = (
                suffix in _CONTEXT_EXTENSIONS
                or name_lower in _README_NAMES
                or name_lower in _CONFIG_NAMES
            )
            if not is_context and suffix not in language_filter:
                continue
        if ignore_patterns and _is_mineignored(str(rel), ignore_patterns):
            continue
        eligible.append((_file_priority(rel), rel, filepath))

    # Sort by priority then alphabetically within each tier
    eligible.sort(key=lambda t: (t[0], str(t[1])))

    parts: list[str] = []
    total_bytes = 0
    file_count = 0

    for _prio, rel, filepath in eligible:
        # Gate 2: Skip files flagged by secret scanner
        if exclude_files and str(rel) in exclude_files:
            logger.info("Skipping file with secret findings: %s", rel)
            continue

        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
        except (OSError, PermissionError) as exc:
            logger.debug("Skipping unreadable file %s: %s", filepath, exc)
            continue

        # Gate: skip oversized data files entirely (no useful signatures)
        if filepath.suffix.lower() in _DATA_EXTENSIONS:
            raw_size = filepath.stat().st_size
            if raw_size > _MAX_DATA_FILE_BYTES:
                logger.debug(
                    "Skipping large data file %s (%.0fKB > %dKB limit)",
                    rel, raw_size / 1024, _MAX_DATA_FILE_BYTES // 1024,
                )
                continue

        # Pre-screen oversized files: replace with a compact skeleton
        # (head + signatures) to avoid a single file eating the whole budget
        # and to prevent LLM stalls on monolithic modules.
        raw_bytes = len(content.encode("utf-8"))
        if raw_bytes > _MAX_FILE_BYTES_FULL:
            skeleton = _extract_skeleton(content, rel)
            skeleton_bytes = len(skeleton.encode("utf-8"))
            logger.info(
                "Skeleton-extracting oversized file %s (%.0fKB -> %.0fKB)",
                rel, raw_bytes / 1024, skeleton_bytes / 1024,
            )
            content = skeleton

        header = f"--- FILE: {rel} ---\n"
        chunk = header + content + "\n"
        chunk_bytes = len(chunk.encode("utf-8"))

        if total_bytes + chunk_bytes > max_bytes:
            parts.append(
                f"\n--- TRUNCATED: repo serialization exceeded {max_bytes // 1024}KB limit ---\n"
            )
            break

        parts.append(chunk)
        total_bytes += chunk_bytes
        file_count += 1

    return "".join(parts), file_count


def _repair_json(text: str) -> Optional[list]:
    """Attempt to repair common LLM JSON errors.

    Tries progressively more aggressive fixes:
    1. Strip trailing commas before ] or }
    2. Truncate at last valid ] and re-parse
    3. Parse individual objects from the array
    """
    import re as _re

    # Fix 1: Remove trailing commas (e.g., {"a": 1,} or [1, 2,])
    fixed = _re.sub(r",\s*([}\]])", r"\1", text)
    try:
        result = json.loads(fixed)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Fix 2: Truncate at last complete array bracket
    last_bracket = fixed.rfind("]")
    if last_bracket > 0:
        truncated = fixed[:last_bracket + 1]
        try:
            result = json.loads(truncated)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    # Fix 3: Extract individual JSON objects and build array
    objects = []
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{" and depth == 0:
            start = i
            depth = 1
        elif ch == "{":
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                fragment = text[start:i + 1]
                try:
                    obj = json.loads(fragment)
                    objects.append(obj)
                except json.JSONDecodeError:
                    pass
                start = None

    if objects:
        return objects

    return None


def parse_findings(llm_response: str, repo_name: str) -> list[MiningFinding]:
    """Extract MiningFinding objects from LLM JSON response.

    Handles ```json fences, validates required fields, filters by
    relevance score, and caps at _MAX_FINDINGS_PER_REPO.

    Args:
        llm_response: Raw text from the LLM containing a JSON array.
        repo_name: Name of the source repo (injected into each finding).

    Returns:
        List of validated MiningFinding objects.
    """
    if not llm_response:
        logger.warning("Empty or None LLM response for %s — returning no findings", repo_name)
        return []
    cleaned = llm_response.strip()

    # Strip markdown code fences if present
    fence_pattern = r"^```(?:json)?\s*\n?(.*?)\n?```$"
    match = re.match(fence_pattern, cleaned, re.DOTALL)
    if match:
        cleaned = match.group(1).strip()

    # Try to find a JSON array in the response
    if not cleaned.startswith("["):
        # Look for array start in the response
        arr_start = cleaned.find("[")
        arr_end = cleaned.rfind("]")
        if arr_start != -1 and arr_end != -1 and arr_end > arr_start:
            cleaned = cleaned[arr_start:arr_end + 1]

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Attempt JSON repair for common LLM errors
        repaired = _repair_json(cleaned)
        if repaired is not None:
            data = repaired
            logger.info("Repaired malformed JSON from LLM (original error: %s)", e)
        else:
            logger.warning("Failed to parse mining findings JSON: %s", e)
            return []

    if not isinstance(data, list):
        logger.warning("Mining findings response is not a JSON array")
        return []

    def _text(value: Any, default: str = "") -> str:
        if value is None:
            return default
        if isinstance(value, str):
            return value
        return str(value)

    findings: list[MiningFinding] = []
    for item in data:
        if not isinstance(item, dict):
            continue

        # Required fields
        title = _text(item.get("title", ""), "").strip()
        description = _text(item.get("description", ""), "").strip()
        if not title or not description:
            continue

        # Category validation
        raw_category = _text(item.get("category", ""), "").strip().lower()
        if raw_category not in _VALID_CATEGORIES:
            logger.info(
                "Invalid category '%s' from LLM (title='%s') → defaulting to cross_cutting",
                raw_category, title[:80],
            )
            category = "cross_cutting"
        else:
            category = raw_category

        # Relevance filter
        try:
            relevance = float(item.get("relevance_score", 0.0))
        except (TypeError, ValueError):
            relevance = 0.0
        if relevance < 0.4:
            continue

        # Clamp relevance to [0.4, 1.0]
        relevance = min(max(relevance, 0.4), 1.0)

        # Source files
        source_files = item.get("source_files", [])
        if not isinstance(source_files, list):
            source_files = []
        source_files = [str(f) for f in source_files if f]

        source_symbols = item.get("source_symbols", [])
        if not isinstance(source_symbols, list):
            source_symbols = []
        normalized_symbols: list[dict[str, str]] = []
        for symbol in source_symbols:
            if isinstance(symbol, dict):
                file_path = str(symbol.get("file_path", "")).strip()
                symbol_name = str(symbol.get("symbol_name", "")).strip()
                symbol_kind = str(symbol.get("symbol_kind", "symbol")).strip() or "symbol"
                if file_path and symbol_name:
                    normalized_symbols.append(
                        {
                            "file_path": file_path,
                            "symbol_name": symbol_name,
                            "symbol_kind": symbol_kind,
                            "note": str(symbol.get("note", "")).strip(),
                        }
                    )

        # Optional execution plan fields
        execution_steps = item.get("execution_steps", [])
        if not isinstance(execution_steps, list):
            execution_steps = []
        execution_steps = [str(s).strip() for s in execution_steps if str(s).strip()]

        acceptance_checks = item.get("acceptance_checks", [])
        if not isinstance(acceptance_checks, list):
            acceptance_checks = []
        acceptance_checks = [str(s).strip() for s in acceptance_checks if str(s).strip()]

        rollback_steps = item.get("rollback_steps", [])
        if not isinstance(rollback_steps, list):
            rollback_steps = []
        rollback_steps = [str(s).strip() for s in rollback_steps if str(s).strip()]

        preconditions = item.get("preconditions", [])
        if not isinstance(preconditions, list):
            preconditions = []
        preconditions = [str(s).strip() for s in preconditions if str(s).strip()]

        finding = MiningFinding(
            title=title[:200],
            description=description[:2000],
            category=category,
            source_repo=repo_name,
            source_files=source_files[:20],
            source_symbols=normalized_symbols[:20],
            implementation_sketch=_text(item.get("implementation_sketch", ""), "")[:2000],
            augmentation_notes=_text(item.get("augmentation_notes", ""), "")[:1000],
            relevance_score=relevance,
            language=_text(item.get("language", "python"), "python")[:20],
            execution_steps=execution_steps[:10],
            acceptance_checks=acceptance_checks[:10],
            rollback_steps=rollback_steps[:10],
            preconditions=preconditions[:10],
        )
        findings.append(finding)

        if len(findings) >= _MAX_FINDINGS_PER_REPO:
            break

    return findings


class RepoMiner:
    """Mines local repositories for patterns, features, and ideas.

    Uses LLMClient.complete() directly (not through agents/Dispatcher)
    since mining is analytical — a single large-context call per repo.

    Args:
        repository: Database access for creating tasks.
        llm_client: OpenRouter client for LLM calls.
        semantic_memory: For storing findings as methodologies.
        config: CLAW config for model selection.
    """

    def __init__(
        self,
        repository: Repository,
        llm_client: LLMClient,
        semantic_memory: SemanticMemory,
        config: ClawConfig,
        governance: Any = None,
        assimilation_engine: Any = None,
        scan_ledger_path: Optional[Path] = None,
    ):
        self.repository = repository
        self.llm_client = llm_client
        self.semantic_memory = semantic_memory
        self.config = config
        self.governance = governance
        self.assimilation_engine = assimilation_engine
        self._prompt_cache: dict[str, str] = {}
        self.scan_ledger = RepoScanLedger(
            scan_ledger_path or _default_scan_ledger_path(config)
        )
        # Assimilation parallelism: read from config, default 8, cap 16
        mining_parallel = getattr(config.mining, "assimilation_parallelism", None)
        if mining_parallel is None:
            mining_parallel = 8
        self._assimilation_parallelism = max(1, min(int(mining_parallel), 16))
        self._fast_mine: bool = False  # When True, skip assimilation during mining
        self._scenario_enricher: Any = None  # Lazy-init ScenarioEnricher
        self._quarantined_mining_models: set[str] = set()

    @staticmethod
    def _extract_symbols_from_file(repo_path: Path, relative_path: str, max_symbols: int = 8) -> list[dict[str, Any]]:
        """Extract concrete class/function/module references from a source file."""
        components = extract_components_from_file(
            repo_path,
            relative_path,
            max_components=max_symbols,
        )
        return [
            {
                "file_path": component.file_path,
                "symbol_name": component.symbol_name,
                "symbol_kind": component.symbol_kind,
                "line_start": component.line_start,
                "line_end": component.line_end,
                "provenance_precision": "precise_symbol" if component.line_start else "symbol",
                "note": component.note,
            }
            for component in components
        ]

    @staticmethod
    def _apply_scip_precision(
        symbols: list[dict[str, Any]],
        repo_path: Path,
    ) -> list[dict[str, Any]]:
        _index_path, scip_symbols = load_repo_scip(repo_path)
        if not scip_symbols:
            return symbols

        by_key: dict[tuple[str, str], Any] = {}
        for record in scip_symbols:
            symbol_key = record.symbol.split()[-1] if record.symbol else record.symbol
            by_key[(record.file_path, symbol_key)] = record

        upgraded: list[dict[str, Any]] = []
        for symbol in symbols:
            item = dict(symbol)
            match = by_key.get((item.get("file_path", ""), item.get("symbol_name", "")))
            if match is not None:
                if getattr(match, "line_start", None) is not None:
                    item["line_start"] = match.line_start
                if getattr(match, "line_end", None) is not None:
                    item["line_end"] = match.line_end
                item["provenance_precision"] = "precise_symbol"
                note = item.get("note", "")
                item["note"] = f"{note}; scip_matched".strip("; ")
            upgraded.append(item)
        return upgraded

    @staticmethod
    def _score_symbol_relevance(symbol: dict[str, str], finding: MiningFinding) -> int:
        text = " ".join(
            [
                finding.title.lower(),
                finding.description.lower(),
                finding.implementation_sketch.lower(),
                finding.augmentation_notes.lower(),
            ]
        )
        name = symbol.get("symbol_name", "").lower()
        score = 0
        if name and name in text:
            score += 4
        name_tokens = {token for token in re.findall(r"[a-z0-9_]+", name) if len(token) >= 3}
        text_tokens = {token for token in re.findall(r"[a-z0-9_]+", text) if len(token) >= 3}
        score += len(name_tokens & text_tokens)
        kind = symbol.get("symbol_kind", "")
        if kind in {"class", "function"}:
            score += 1
        return score

    def _attach_symbol_provenance(self, findings: list[MiningFinding], repo_path: Path, per_finding_limit: int = 8) -> None:
        """Attach concrete symbol references from mined source files."""
        for finding in findings:
            if finding.source_symbols:
                continue
            candidates: list[dict[str, Any]] = []
            for relative_path in finding.source_files:
                candidates.extend(self._extract_symbols_from_file(repo_path, relative_path))
            candidates = self._apply_scip_precision(candidates, repo_path)
            candidates.sort(key=lambda item: self._score_symbol_relevance(item, finding), reverse=True)
            deduped: list[dict[str, Any]] = []
            seen: set[tuple[str, str, str]] = set()
            for item in candidates:
                ident = (item["file_path"], item["symbol_name"], item["symbol_kind"])
                if ident in seen:
                    continue
                seen.add(ident)
                deduped.append(item)
                if len(deduped) >= per_finding_limit:
                    break
            finding.source_symbols = deduped

    def _seed_capability_data_from_finding(self, finding: MiningFinding) -> dict[str, Any]:
        """Create retrieval-friendly seed capability metadata from a mining finding.

        This adds provenance and trigger metadata immediately, before the richer
        LLM-based assimilation pass fills in IO/domain/composability details.
        """
        applicability = [finding.description.strip(), finding.implementation_sketch.strip()]
        applicability = [item for item in applicability if item]

        source_artifacts = [
            {
                "file_path": path,
                "symbol_name": None,
                "symbol_kind": "file",
                "line_start": None,
                "line_end": None,
                "provenance_precision": "file",
                "note": f"Mined from {finding.source_repo}",
            }
            for path in finding.source_files
        ]
        for symbol in finding.source_symbols:
            source_artifacts.append(
                {
                    "file_path": symbol.get("file_path", ""),
                    "symbol_name": symbol.get("symbol_name"),
                    "symbol_kind": symbol.get("symbol_kind", "symbol"),
                    "line_start": symbol.get("line_start"),
                    "line_end": symbol.get("line_end"),
                    "provenance_precision": symbol.get("provenance_precision", "symbol"),
                    "note": symbol.get("note", ""),
                }
            )

        triggers = list(_CATEGORY_TRIGGER_MAP.get(finding.category, []))
        triggers.append("has_action_template_candidate")
        if finding.execution_steps or finding.acceptance_checks:
            triggers.append("has_explicit_runbook")
        if finding.relevance_score >= 0.8:
            triggers.append("high_relevance")

        non_applicability: list[str] = []
        if finding.augmentation_notes.strip():
            non_applicability.append(
                "Requires adaptation to the target repo; do not apply blindly."
            )

        return {
            "schema_version": 2,
            "enrichment_status": "seeded",
            "inputs": [],
            "outputs": [],
            "domain": [finding.category],
            "composability": {
                "can_chain_after": [],
                "can_chain_before": [],
                "standalone": True,
            },
            "capability_type": "validation" if finding.category in {"testing", "security", "code_quality"} else "transformation",
            "source_repos": [finding.source_repo],
            "source_artifacts": source_artifacts,
            "applicability": applicability,
            "non_applicability": non_applicability,
            "activation_triggers": sorted(set(triggers)),
            "dependencies": list(finding.preconditions),
            "risks": [finding.augmentation_notes.strip()] if finding.augmentation_notes.strip() else [],
            "composition_candidates": [],
            "evidence": [f"source_file:{path}" for path in finding.source_files],
            "license_type": getattr(self, "_current_mine_metadata", {}).get("license_type", ""),
        }

    @staticmethod
    def _build_action_template_from_finding(
        finding: MiningFinding,
        methodology_id: str,
    ) -> ActionTemplate:
        """Create a source-linked action template for an accepted finding.

        Model-provided runbooks are preserved. Findings without explicit steps
        still get a conservative adaptation template so serial evolution can
        measure whether mined artifacts are actually usable for later CAM tasks.
        """
        execution_steps = [step.strip() for step in finding.execution_steps if step.strip()]
        acceptance_checks = [check.strip() for check in finding.acceptance_checks if check.strip()]
        rollback_steps = [step.strip() for step in finding.rollback_steps if step.strip()]
        preconditions = [item.strip() for item in finding.preconditions if item.strip()]

        if execution_steps or acceptance_checks:
            confidence = finding.relevance_score
        else:
            source_files = [path.strip() for path in finding.source_files if path.strip()]
            source_hint = ", ".join(source_files[:5]) if source_files else "the mined methodology and source context"
            category = finding.category or "cross_cutting"
            title = finding.title.strip() or "mined pattern"

            execution_steps = [
                f"Inspect source artifacts from {finding.source_repo}: {source_hint}",
                f"Map the pattern '{title}' to the target task constraints",
                "Adapt the implementation sketch while preserving rollback boundaries",
            ]
            acceptance_checks = [
                f"Retrieved methodology {methodology_id} is cited in the task rationale",
                "Adapted change satisfies the task's existing tests or verification command",
                "No unrelated files are changed",
            ]
            rollback_steps = [
                "Remove the adapted change and any generated config or test additions",
                "Re-run the verification command that failed or changed",
            ]
            preconditions = [
                f"Source repo {finding.source_repo} was mined and accepted",
                f"Target task matches category {category}",
                *preconditions,
            ]
            confidence = min(finding.relevance_score, 0.75)

        return ActionTemplate(
            title=finding.title[:200],
            problem_pattern=finding.description[:2000],
            execution_steps=execution_steps,
            acceptance_checks=acceptance_checks,
            rollback_steps=rollback_steps,
            preconditions=preconditions,
            source_methodology_id=methodology_id,
            source_repo=finding.source_repo,
            confidence=confidence,
        )

    @staticmethod
    def _infer_component_type(text: str, symbol_kind: str, category: str) -> str:
        lowered = text.lower()
        if "fixture" in lowered or category == "testing":
            return "test_fixture"
        if any(tok in lowered for tok in ("validate", "validator", "schema", "clean")):
            return "validator"
        if any(tok in lowered for tok in ("worker", "queue", "consumer", "processor", "job")):
            return "queue_worker"
        if any(tok in lowered for tok in ("client", "oauth", "token", "auth", "session")):
            return "api_client"
        if any(tok in lowered for tok in ("route", "router", "endpoint", "handler")):
            return "route_handler"
        if any(tok in lowered for tok in ("config", "settings", "option")):
            return "config_helper"
        if any(tok in lowered for tok in ("parse", "parser", "transform", "csv", "json")):
            return "parser"
        if symbol_kind == "class":
            return "class_component"
        return "helper"

    @staticmethod
    def _infer_abstract_jobs(component_type: str, text: str) -> list[str]:
        lowered = text.lower()
        jobs: list[str] = []
        if component_type == "api_client":
            if "token" in lowered or "refresh" in lowered:
                jobs.append("token_refresh_serialization")
            if "auth" in lowered or "oauth" in lowered:
                jobs.append("authenticated_api_client")
        if component_type == "queue_worker":
            jobs.append("idempotent_event_processor")
        if component_type == "test_fixture":
            jobs.append("tempdir_test_fixture")
        if component_type == "parser":
            jobs.append("streaming_response_normalization" if "stream" in lowered else "parser_transform")
        if "retry" in lowered or "backoff" in lowered:
            jobs.append("retry_with_backoff")
        if not jobs:
            jobs.append(component_type)
        return list(dict.fromkeys(jobs))

    @staticmethod
    def _artifact_content_hash(methodology: Methodology, artifact: dict[str, Any]) -> str:
        payload = "|".join(
            [
                methodology.id,
                str(artifact.get("file_path", "")),
                str(artifact.get("symbol_name", "")),
                methodology.problem_description or "",
                methodology.solution_code[:500] if methodology.solution_code else "",
            ]
        )
        return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"

    async def _upsert_component_from_artifact(
        self,
        methodology: Methodology,
        artifact: dict[str, Any],
        *,
        repository: Repository,
    ) -> tuple[str, Optional[ComponentCard]]:
        file_path = str(artifact.get("file_path", "")).strip()
        if not file_path:
            return "skipped", None

        symbol_name = str(artifact.get("symbol_name", "")).strip() or None
        symbol_kind = str(artifact.get("symbol_kind", "file")).strip() or "file"
        line_start = artifact.get("line_start")
        line_end = artifact.get("line_end")
        provenance_precision = str(
            artifact.get("provenance_precision")
            or ("precise_symbol" if line_start is not None else ("symbol" if symbol_name else "file"))
        )
        source_repo = (
            ((methodology.capability_data or {}).get("source_repos") or [None])[0]
            or next((tag.split(":", 1)[1] for tag in methodology.tags if tag.startswith("source:")), "unknown")
        )
        title = symbol_name or Path(file_path).stem or methodology.problem_description[:80]
        descriptor = " ".join(
            [
                title,
                methodology.problem_description,
                methodology.methodology_notes or "",
                " ".join(methodology.tags or []),
                symbol_kind,
            ]
        )
        component_type = self._infer_component_type(
            descriptor,
            symbol_kind=symbol_kind,
            category=((methodology.capability_data or {}).get("domain") or [""])[0],
        )
        abstract_jobs = self._infer_abstract_jobs(component_type, descriptor)
        family_barcode = build_family_barcode(component_type, abstract_jobs[0])
        content_hash = self._artifact_content_hash(methodology, artifact)
        source_barcode = build_source_barcode(
            source_repo,
            file_path,
            content_hash,
            symbol_name=symbol_name,
        )

        existing = await repository.find_component_by_source_barcode(source_barcode)
        if existing is not None:
            return "updated", await repository.upsert_component_card(existing.model_copy(
                update={
                    "methodology_id": methodology.id,
                    "title": title,
                    "component_type": component_type,
                    "abstract_jobs": abstract_jobs,
                    "language": methodology.language,
                    "frameworks": list((methodology.capability_data or {}).get("dependencies", [])),
                    "constraints": list((methodology.capability_data or {}).get("non_applicability", [])),
                    "applicability": list((methodology.capability_data or {}).get("applicability", [])),
                    "non_applicability": list((methodology.capability_data or {}).get("non_applicability", [])),
                    "adaptation_notes": [methodology.methodology_notes] if methodology.methodology_notes else [],
                    "risk_notes": list((methodology.capability_data or {}).get("risks", [])),
                    "keywords": list(dict.fromkeys([*abstract_jobs, component_type, *(methodology.tags or [])])),
                }
            ))

        lineage = await repository.find_lineage_by_hash(content_hash)
        if lineage is None or lineage.family_barcode != family_barcode:
            lineage = build_initial_lineage(
                ComponentCard(
                    methodology_id=methodology.id,
                    title=title,
                    component_type=component_type,
                    abstract_jobs=abstract_jobs,
                    receipt=Receipt(
                        source_barcode=source_barcode,
                        family_barcode=family_barcode,
                        lineage_id="pending",
                        repo=source_repo,
                        file_path=file_path,
                        symbol=symbol_name,
                        line_start=line_start,
                        line_end=line_end,
                        content_hash=content_hash,
                        provenance_precision=provenance_precision,
                    ),
                    language=methodology.language,
                )
            )
            await repository.upsert_component_lineage(lineage)

        receipt = Receipt(
            source_barcode=source_barcode,
            family_barcode=family_barcode,
            lineage_id=lineage.id,
            repo=source_repo,
            file_path=file_path,
            symbol=symbol_name,
            line_start=line_start,
            line_end=line_end,
            content_hash=content_hash,
            provenance_precision=provenance_precision,
        )
        card = ComponentCard(
            methodology_id=methodology.id,
            title=title,
            component_type=component_type,
            abstract_jobs=abstract_jobs,
            receipt=receipt,
            language=methodology.language,
            frameworks=list((methodology.capability_data or {}).get("dependencies", [])),
            dependencies=list((methodology.capability_data or {}).get("dependencies", [])),
            constraints=list((methodology.capability_data or {}).get("non_applicability", [])),
            test_evidence=list((methodology.capability_data or {}).get("evidence", [])),
            applicability=list((methodology.capability_data or {}).get("applicability", [])),
            non_applicability=list((methodology.capability_data or {}).get("non_applicability", [])),
            adaptation_notes=[methodology.methodology_notes] if methodology.methodology_notes else [],
            risk_notes=list((methodology.capability_data or {}).get("risks", [])),
            keywords=list(dict.fromkeys([*abstract_jobs, component_type, *(methodology.tags or [])])),
            coverage_state=CoverageState.WEAK if symbol_name else CoverageState.UNCOVERED,
        )
        saved = await repository.upsert_component_card(card)

        lineage_components = await repository.list_lineage_components(lineage.id)
        if lineage_components:
            full_cards: list[ComponentCard] = []
            for item in lineage_components:
                found = await repository.get_component_card(item.id)
                if found is not None:
                    full_cards.append(found)
            if full_cards:
                rebuilt = rebuild_lineage_stats(lineage, full_cards)
                await repository.upsert_component_lineage(rebuilt)

        existing_fit = await repository.find_component_fit(
            task_archetype=None,
            slot_signature=abstract_jobs[0],
            component_type=component_type,
            limit=10,
        )
        if not any(row.component_id == saved.id for row in existing_fit):
            await repository.save_component_fit(
                ComponentFit(
                    component_id=saved.id,
                    task_archetype=None,
                    component_type=component_type,
                    slot_signature=abstract_jobs[0],
                    fit_bucket=FitBucket.MAY_HELP,
                    transfer_mode=TransferMode.HEURISTIC_FALLBACK,
                    confidence=0.55 if symbol_name else 0.35,
                    confidence_basis=["methodology_backfill", "source_artifact"],
                    evidence_count=max(1, len((methodology.capability_data or {}).get("evidence", []))),
                    notes=["seeded from methodology capability_data"],
                )
            )
        return "created", saved

    async def backfill_components(
        self,
        *,
        methodology_ids: Optional[list[str]] = None,
        limit: int = 100,
        repository: Optional[Repository] = None,
    ) -> dict[str, Any]:
        repo = repository or self.repository
        if methodology_ids:
            methodologies = []
            for methodology_id in methodology_ids:
                methodology = await repo.get_methodology(methodology_id)
                if methodology is not None:
                    methodologies.append(methodology)
        else:
            methodologies = await repo.get_methodologies_with_capabilities(limit=limit)

        summary = {"created": 0, "updated": 0, "skipped": 0, "methodologies": len(methodologies), "skip_reasons": []}
        for methodology in methodologies:
            capability_data = methodology.capability_data or {}
            artifacts = list(capability_data.get("source_artifacts") or [])
            if not artifacts:
                artifacts = [
                    {
                        "file_path": path,
                        "symbol_name": None,
                        "symbol_kind": "file",
                        "note": "files_affected fallback",
                    }
                    for path in (methodology.files_affected or [])
                    if path
                ]
            if not artifacts:
                summary["skipped"] += 1
                summary["skip_reasons"].append(
                    {"methodology_id": methodology.id, "reason": "no_source_artifacts"}
                )
                continue

            method_created = 0
            method_updated = 0
            for artifact in artifacts:
                status, _card = await self._upsert_component_from_artifact(
                    methodology,
                    artifact,
                    repository=repo,
                )
                if status == "created":
                    summary["created"] += 1
                    method_created += 1
                elif status == "updated":
                    summary["updated"] += 1
                    method_updated += 1
                else:
                    summary["skipped"] += 1
            if method_created == 0 and method_updated == 0:
                summary["skip_reasons"].append(
                    {"methodology_id": methodology.id, "reason": "artifacts_not_actionable"}
                )
        return summary

    def _get_prompt_template(self, prompt_name: str = "repo-mine.md") -> str:
        """Load a mining prompt template from the prompts/ directory.

        Caches by filename so multiple brains can each load their own
        prompt without redundant disk reads.
        """
        if prompt_name not in self._prompt_cache:
            prompt_path = Path(__file__).parent.parent.parent / "prompts" / prompt_name
            if not prompt_path.exists():
                raise FileNotFoundError(f"Mining prompt not found: {prompt_path}")
            self._prompt_cache[prompt_name] = prompt_path.read_text(encoding="utf-8")
        return self._prompt_cache[prompt_name]

    def _build_repo_mining_prompt(
        self,
        repo_content: str,
        brain_config: BrainConfig,
        domain_info: dict[str, Any],
        overlap: Any,
    ) -> str:
        template = self._get_prompt_template(brain_config.prompt)
        prompt = template.replace("{repo_content}", repo_content)
        context_lines = self._build_mining_context(domain_info, overlap)
        if context_lines:
            prompt = "\n".join(context_lines) + "\n\n" + prompt
        return prompt

    def _estimate_prompt_tokens(self, prompt: str) -> int:
        cpt = self.config.mining.recovery.token_estimate_chars_per_token
        return int(len(prompt) / cpt)

    def _cap_repo_content_for_prompt_budget(
        self,
        *,
        repo_path: str | Path,
        repo_name: str,
        repo_content: str,
        file_count: int,
        brain: str,
        brain_config: BrainConfig,
        domain_info: dict[str, Any],
        overlap: Any,
        secret_scan_files: set[str] | None,
        language_filter: Optional[set[str]] = None,
    ) -> tuple[str, int, str, int]:
        """Shrink serialized content before the first paid call if prompt is too large."""
        prompt = self._build_repo_mining_prompt(
            repo_content, brain_config, domain_info, overlap,
        )
        estimated_tokens = self._estimate_prompt_tokens(prompt)
        max_prompt_tokens = self.config.mining.recovery.max_prompt_tokens
        if max_prompt_tokens <= 0 or estimated_tokens <= max_prompt_tokens:
            return repo_content, file_count, prompt, estimated_tokens

        original_bytes = len(repo_content.encode("utf-8"))
        scale = max_prompt_tokens / max(estimated_tokens, 1)
        capped_bytes = max(65_536, int(original_bytes * scale * 0.90))
        capped_bytes = min(capped_bytes, max(original_bytes - 1, 0))
        if capped_bytes <= 0 or capped_bytes >= original_bytes:
            return repo_content, file_count, prompt, estimated_tokens

        capped_content, capped_count = serialize_repo(
            repo_path,
            max_bytes=capped_bytes,
            exclude_files=secret_scan_files,
            config=self.config,
            language_filter=language_filter,
        )
        if not capped_content:
            return repo_content, file_count, prompt, estimated_tokens

        capped_prompt = self._build_repo_mining_prompt(
            capped_content, brain_config, domain_info, overlap,
        )
        capped_estimate = self._estimate_prompt_tokens(capped_prompt)
        logger.info(
            "Capped %s prompt for %s from ~%dK to ~%dK tokens "
            "(%dKB -> %dKB)",
            brain,
            repo_name,
            estimated_tokens // 1000,
            capped_estimate // 1000,
            original_bytes // 1024,
            len(capped_content.encode("utf-8")) // 1024,
        )
        return capped_content, capped_count, capped_prompt, capped_estimate

    def _get_mining_model(self) -> str:
        """Get the model to use for mining from config.

        Uses the claude agent's model since mining is analytical work.
        Falls back through other agents if claude is not configured.
        """
        for agent_name in ("claude", "gemini", "codex", "grok"):
            agent_cfg = self.config.agents.get(agent_name)
            if agent_cfg and agent_cfg.enabled and agent_cfg.model:
                return agent_cfg.model
        raise ValueError("No model configured in any agent. Set a model in claw.toml.")

    def _available_escalation_chain(
        self,
        model_selector: MiningModelSelector,
        estimated_tokens: int,
    ) -> list[tuple[str, str]]:
        """Build a mining chain with hard-failed models removed."""
        chain = model_selector.build_escalation_chain(estimated_tokens)
        if not self._quarantined_mining_models:
            return chain
        return [
            (agent_name, model)
            for agent_name, model in chain
            if model not in self._quarantined_mining_models
        ]

    async def _select_non_quarantined_model(
        self,
        model_selector: MiningModelSelector,
        estimated_tokens: int,
    ) -> tuple[str, str]:
        """Select a model, falling back when RL points at a quarantined route."""
        agent_name, model = await model_selector.select_best_model(estimated_tokens)
        if model not in self._quarantined_mining_models:
            return agent_name, model

        chain = self._available_escalation_chain(model_selector, estimated_tokens)
        if chain:
            return chain[0]
        raise ValueError("No mining models remain after quarantine")

    def _quarantine_model_if_hard_failure(self, model: str, error: Exception) -> None:
        """Skip a model for the rest of this miner lifetime after hard provider failure."""
        if not model:
            return
        message = str(error).lower()
        is_hard_failure = isinstance(error, ModelNotFoundError) or any(
            marker in message
            for marker in (
                "provider rejected model request",
                "model not found",
                "unsupported model",
                "invalid model",
                "no endpoints found",
            )
        )
        if not is_hard_failure:
            return
        if model not in self._quarantined_mining_models:
            logger.warning(
                "Quarantining mining model '%s' for this run after %s",
                model,
                type(error).__name__,
            )
        self._quarantined_mining_models.add(model)

    # ------------------------------------------------------------------
    # Self-recovery mining loop
    # ------------------------------------------------------------------

    async def _mine_with_recovery(
        self,
        *,
        prompt: str,
        token_budget: int,
        model_selector: MiningModelSelector,
        estimated_tokens: int,
        repo_name: str,
        repo_path: str | Path,
        repo_content: str,
        file_count: int,
        brain: str,
        brain_config: BrainConfig,
        domain_info: dict[str, Any],
        overlap: Any,
        secret_scan_files: set[str] | None,
        start_time: float,
    ) -> tuple[LLMResponse | None, list[MiningFinding], int, str]:
        """Mine with automatic self-recovery on null/empty LLM responses.

        Recovery strategies (tried in order):
          1. MODEL ESCALATION: Try models with larger context windows.
          2. CONTENT REDUCTION: Re-serialize at 50% of max_bytes, retry.
          3. CHUNK MINING: Split content, mine each chunk, merge findings.

        Returns:
            (response, findings, recovery_attempts, winning_strategy)
        """
        recovery = self.config.mining.recovery

        if not recovery.enabled:
            agent_name, model = await self._select_non_quarantined_model(
                model_selector,
                estimated_tokens,
            )
            try:
                resp = await asyncio.wait_for(
                    self.llm_client.complete(
                        messages=[LLMMessage(role="user", content=prompt)],
                        model=model, temperature=0.3, max_tokens=token_budget,
                    ),
                    timeout=_MINING_LLM_TIMEOUT_SECONDS,
                )
                findings = parse_findings(resp.content, repo_name)
                await self._record_mining_outcome(
                    model=model, agent_id=agent_name, brain=brain,
                    repo_name=repo_name, estimated_tokens=estimated_tokens,
                    repo_size_bytes=len(repo_content.encode()),
                    file_count=file_count, strategy="primary",
                    success=bool(findings), findings_count=len(findings),
                    response=resp, start_time=start_time,
                )
                return resp, findings, 0, "primary"
            except Exception as e:
                await self._record_mining_outcome(
                    model=model, agent_id=agent_name, brain=brain,
                    repo_name=repo_name, estimated_tokens=estimated_tokens,
                    repo_size_bytes=len(repo_content.encode()),
                    file_count=file_count, strategy="primary",
                    success=False, findings_count=0, response=None,
                    start_time=start_time, error=e,
                )
                self._quarantine_model_if_hard_failure(model, e)
                return None, [], 0, "primary"

        escalation_chain = self._available_escalation_chain(model_selector, estimated_tokens)
        attempts = 0

        # --- STRATEGY 1: Model escalation ---
        for agent_name, model in escalation_chain:
            if attempts >= recovery.max_escalation_attempts:
                break

            attempts += 1
            strategy = "primary" if attempts == 1 else "model_escalation"
            logger.info(
                "Mining %s: attempt %d/%d, model=%s (agent=%s, strategy=%s)",
                repo_name, attempts, recovery.max_escalation_attempts,
                model, agent_name, strategy,
            )

            try:
                resp = await asyncio.wait_for(
                    self.llm_client.complete(
                        messages=[LLMMessage(role="user", content=prompt)],
                        model=model, temperature=0.3, max_tokens=token_budget,
                    ),
                    timeout=_MINING_LLM_TIMEOUT_SECONDS,
                )
            except Exception as e:
                logger.warning(
                    "Mining %s: model %s threw %s — escalating",
                    repo_name, model, type(e).__name__,
                )
                await self._record_mining_outcome(
                    model=model, agent_id=agent_name, brain=brain,
                    repo_name=repo_name, estimated_tokens=estimated_tokens,
                    repo_size_bytes=len(repo_content.encode()),
                    file_count=file_count, strategy=strategy,
                    success=False, findings_count=0, response=None,
                    start_time=start_time, error=e,
                )
                self._quarantine_model_if_hard_failure(model, e)
                continue

            findings = parse_findings(resp.content, repo_name)
            success = bool(findings)
            await self._record_mining_outcome(
                model=model, agent_id=agent_name, brain=brain,
                repo_name=repo_name, estimated_tokens=estimated_tokens,
                repo_size_bytes=len(repo_content.encode()),
                file_count=file_count, strategy=strategy,
                success=success, findings_count=len(findings),
                response=resp, start_time=start_time,
            )

            if success:
                if attempts > 1:
                    logger.info(
                        "Mining %s: recovered after %d attempts with model %s",
                        repo_name, attempts, model,
                    )
                return resp, findings, attempts - 1, strategy

            logger.warning(
                "Mining %s: model %s returned 0 findings — escalating",
                repo_name, model,
            )

        # --- STRATEGY 2: Content reduction ---
        # Always attempt after model escalation exhausts.
        attempts += 1
        reduced_max = int(brain_config.max_bytes * recovery.content_reduction_factor)
        logger.info(
            "Mining %s: STRATEGY 2 — reducing content from %dKB to %dKB",
            repo_name, brain_config.max_bytes // 1024, reduced_max // 1024,
        )

        reduced_content, reduced_count = serialize_repo(
            repo_path, max_bytes=reduced_max,
            exclude_files=secret_scan_files, config=self.config,
        )
        if reduced_content:
            template = self._get_prompt_template(brain_config.prompt)
            reduced_prompt = template.replace("{repo_content}", reduced_content)
            ctx_lines = self._build_mining_context(domain_info, overlap)
            if ctx_lines:
                reduced_prompt = "\n".join(ctx_lines) + "\n\n" + reduced_prompt

            reduced_est = model_selector.estimate_prompt_tokens(reduced_prompt)
            try:
                best_agent, best_model = await self._select_non_quarantined_model(
                    model_selector,
                    reduced_est,
                )
            except ValueError:
                fresh_chain = self._available_escalation_chain(model_selector, reduced_est)
                best_agent, best_model = fresh_chain[0] if fresh_chain else ("", "")

            if best_model:
                try:
                    resp = await asyncio.wait_for(
                        self.llm_client.complete(
                            messages=[LLMMessage(role="user", content=reduced_prompt)],
                            model=best_model, temperature=0.3,
                            max_tokens=token_budget,
                        ),
                        timeout=_MINING_LLM_TIMEOUT_SECONDS,
                    )
                    findings = parse_findings(resp.content, repo_name)
                    success = bool(findings)
                    await self._record_mining_outcome(
                        model=best_model, agent_id=best_agent, brain=brain,
                        repo_name=repo_name, estimated_tokens=reduced_est,
                        repo_size_bytes=len(reduced_content.encode()),
                        file_count=reduced_count,
                        strategy="content_reduction",
                        success=success, findings_count=len(findings),
                        response=resp, start_time=start_time,
                    )
                    if success:
                        logger.info(
                            "Mining %s: recovered via content reduction "
                            "(%dKB → %dKB, model=%s)",
                            repo_name, brain_config.max_bytes // 1024,
                            reduced_max // 1024, best_model,
                        )
                        return resp, findings, attempts, "content_reduction"
                except Exception as e:
                    logger.warning(
                        "Mining %s: content reduction failed: %s",
                        repo_name, e,
                    )
                    await self._record_mining_outcome(
                        model=best_model, agent_id=best_agent, brain=brain,
                        repo_name=repo_name, estimated_tokens=reduced_est,
                        repo_size_bytes=len(reduced_content.encode()),
                        file_count=reduced_count,
                        strategy="content_reduction",
                        success=False, findings_count=0, response=None,
                        start_time=start_time, error=e,
                    )
                    self._quarantine_model_if_hard_failure(best_model, e)

        # --- STRATEGY 3: Chunk mining ---
        # Always attempt as last resort.
        attempts += 1
        logger.info("Mining %s: STRATEGY 3 — chunk mining", repo_name)

        chunk_findings = await self._mine_in_chunks(
            repo_content=repo_content,
            repo_name=repo_name,
            repo_path=repo_path,
            brain=brain,
            brain_config=brain_config,
            domain_info=domain_info,
            overlap=overlap,
            model_selector=model_selector,
            token_budget=token_budget,
            file_count=file_count,
            start_time=start_time,
        )
        if chunk_findings:
            logger.info(
                "Mining %s: recovered via chunk mining — %d findings",
                repo_name, len(chunk_findings),
            )
            return None, chunk_findings, attempts, "chunk_mining"

        logger.error(
            "Mining %s: ALL %d recovery attempts exhausted — 0 findings",
            repo_name, attempts,
        )
        return None, [], attempts, ""

    async def _mine_in_chunks(
        self,
        *,
        repo_content: str,
        repo_name: str,
        repo_path: str | Path,
        brain: str,
        brain_config: BrainConfig,
        domain_info: dict[str, Any],
        overlap: Any,
        model_selector: MiningModelSelector,
        token_budget: int,
        file_count: int,
        start_time: float,
    ) -> list[MiningFinding]:
        """Split repo content into chunks, mine each, merge findings."""
        recovery = self.config.mining.recovery

        # Split at file boundaries
        file_sections = re.split(r'(?=--- FILE: )', repo_content)
        file_sections = [s for s in file_sections if s.strip()]
        if not file_sections:
            return []

        # Determine chunk size from first eligible model
        chain = self._available_escalation_chain(model_selector, 0)
        if not chain:
            return []

        agent_name, model = chain[0]
        agent_cfg = self.config.agents.get(agent_name)
        max_chunk_chars = 200_000  # ~50K tokens default
        if agent_cfg and agent_cfg.context_window_tokens > 0:
            headroom = recovery.min_context_headroom_pct
            available = int(agent_cfg.context_window_tokens * (1.0 - headroom))
            available = max(available - 2000, 10000)
            max_chunk_chars = int(
                available * recovery.token_estimate_chars_per_token,
            )

        # Build chunks from file sections
        chunks: list[str] = []
        current_chunk: list[str] = []
        current_size = 0

        for section in file_sections:
            section_size = len(section)
            if current_size + section_size > max_chunk_chars and current_chunk:
                chunks.append("".join(current_chunk))
                current_chunk = []
                current_size = 0
            current_chunk.append(section)
            current_size += section_size

        if current_chunk:
            chunks.append("".join(current_chunk))

        chunks = chunks[:recovery.max_chunks]
        logger.info(
            "Mining %s: split into %d chunks (max_chars=%dK per chunk)",
            repo_name, len(chunks), max_chunk_chars // 1000,
        )

        # Mine each chunk
        all_findings: list[MiningFinding] = []
        template = self._get_prompt_template(brain_config.prompt)
        ctx_lines = self._build_mining_context(domain_info, overlap)

        for i, chunk in enumerate(chunks):
            chunk_prompt = template.replace("{repo_content}", chunk)
            if ctx_lines:
                chunk_prompt = "\n".join(ctx_lines) + "\n\n" + chunk_prompt
            chunk_prompt = (
                f"# CHUNK {i+1}/{len(chunks)}: Partial view of the repo.\n"
                f"# Focus on patterns visible in THIS chunk.\n\n"
                + chunk_prompt
            )

            est = model_selector.estimate_prompt_tokens(chunk_prompt)
            try:
                best_agent, best_model = await self._select_non_quarantined_model(
                    model_selector,
                    est,
                )
            except ValueError:
                break

            try:
                resp = await asyncio.wait_for(
                    self.llm_client.complete(
                        messages=[LLMMessage(role="user", content=chunk_prompt)],
                        model=best_model, temperature=0.3, max_tokens=token_budget,
                    ),
                    timeout=_MINING_LLM_TIMEOUT_SECONDS,
                )
                chunk_findings = parse_findings(resp.content, repo_name)
                await self._record_mining_outcome(
                    model=best_model, agent_id=best_agent, brain=brain,
                    repo_name=repo_name, estimated_tokens=est,
                    repo_size_bytes=len(chunk.encode()),
                    file_count=file_count, strategy="chunk_mining",
                    success=bool(chunk_findings),
                    findings_count=len(chunk_findings),
                    response=resp, start_time=start_time,
                )
                all_findings.extend(chunk_findings)
                logger.info(
                    "Mining %s chunk %d/%d: %d findings (model=%s)",
                    repo_name, i + 1, len(chunks),
                    len(chunk_findings), best_model,
                )
            except Exception as e:
                logger.warning(
                    "Mining %s chunk %d/%d failed: %s",
                    repo_name, i + 1, len(chunks), e,
                )
                self._quarantine_model_if_hard_failure(best_model, e)

        deduped = self._deduplicate_chunk_findings(all_findings)
        return deduped[:_MAX_FINDINGS_PER_REPO]

    @staticmethod
    def _deduplicate_chunk_findings(
        findings: list[MiningFinding],
    ) -> list[MiningFinding]:
        """Deduplicate findings from multiple chunks by title similarity."""
        if not findings:
            return []

        findings.sort(key=lambda f: f.relevance_score, reverse=True)
        deduped: list[MiningFinding] = []
        seen_titles: set[str] = set()

        for finding in findings:
            normalized = finding.title.lower().strip()
            if normalized in seen_titles:
                continue
            title_words = set(normalized.split())
            is_dup = False
            for seen in seen_titles:
                seen_words = set(seen.split())
                if title_words and seen_words:
                    overlap = len(title_words & seen_words) / max(
                        len(title_words), len(seen_words),
                    )
                    if overlap > 0.6:
                        is_dup = True
                        break
            if not is_dup:
                deduped.append(finding)
                seen_titles.add(normalized)

        return deduped

    async def _record_mining_outcome(
        self,
        *,
        model: str,
        agent_id: str,
        brain: str,
        repo_name: str,
        estimated_tokens: int,
        repo_size_bytes: int,
        file_count: int,
        strategy: str,
        success: bool,
        findings_count: int,
        response: LLMResponse | None,
        start_time: float,
        error: Exception | None = None,
    ) -> None:
        """Record a mining outcome for RL learning. Fire-and-forget."""
        try:
            duration = time.monotonic() - start_time
            tokens_used = response.tokens_used if response else 0
            error_type = type(error).__name__ if error else None
            error_detail = str(error)[:500] if error else None

            await self.repository.record_mining_outcome(
                model_used=model,
                agent_id=agent_id,
                brain=brain,
                repo_name=repo_name,
                repo_size_bytes=repo_size_bytes,
                prompt_tokens_estimated=estimated_tokens,
                strategy=strategy,
                success=success,
                findings_count=findings_count,
                tokens_used=tokens_used,
                duration_seconds=duration,
                error_type=error_type,
                error_detail=error_detail,
            )

            # Also update agent_scores for Dispatcher RL learning
            await self.repository.update_agent_score(
                agent_id=agent_id,
                task_type="mining",
                success=success,
                duration_seconds=duration,
                quality_score=1.0 if success else 0.0,
            )
        except Exception as e:
            logger.debug("Failed to record mining outcome: %s", e)

    async def mine_directory(
        self,
        base_path: str | Path,
        target_project_id: str,
        max_repos: int = 10,
        min_relevance: float = 0.6,
        generate_tasks: bool = True,
        on_repo_complete: Optional[Any] = None,
        max_depth: int = 6,
        dedup_iterations: bool = True,
        skip_known: bool = True,
        force_rescan: bool = False,
        yield_sort: bool = True,
        brain: str | None = None,
        fast: bool = False,
    ) -> MiningReport:
        """Discover repos in a directory and mine each.

        Args:
            base_path: Root directory to scan for git repos.
            target_project_id: Project ID to create tasks under.
            max_repos: Maximum repos to mine.
            min_relevance: Minimum relevance for task generation.
            generate_tasks: Whether to create enhancement tasks.
            on_repo_complete: Optional callback(repo_name, result) for progress.
            max_depth: Maximum directory depth for repo discovery.
            dedup_iterations: If True, dedup repo iterations by canonical name.

        Returns:
            MiningReport with aggregate results.
        """
        base = Path(base_path).resolve()
        if not base.exists():
            raise FileNotFoundError(f"Directory not found: {base}")
        if not base.is_dir():
            raise NotADirectoryError(f"Not a directory: {base}")

        # Discover repos by looking for .git directories
        candidates = _discover_repos(base, max_depth=max_depth, config=self.config)
        if not candidates:
            logger.info("No git repos found in %s", base)
            return MiningReport()

        # Dedup iterations if requested
        if dedup_iterations:
            candidates, skipped = _dedup_iterations(candidates)
            if skipped:
                logger.info(
                    "Dedup: %d selected, %d skipped",
                    len(candidates), len(skipped),
                )

        mining_plan: list[tuple[RepoCandidate, str]] = []
        skipped_candidates: list[tuple[RepoCandidate, str]] = []
        for candidate in candidates:
            should_mine, reason = self.scan_ledger.should_mine(
                candidate,
                skip_known=skip_known,
                force_rescan=force_rescan,
            )
            if should_mine:
                mining_plan.append((candidate, reason))
            else:
                skipped_candidates.append((candidate, reason))

        # Sort by expected yield before selecting top-N
        if yield_sort and mining_plan:
            mining_plan.sort(
                key=lambda item: _score_yield_priority(item[0], self.scan_ledger),
                reverse=True,
            )
            for cand, _r in mining_plan[:min(5, len(mining_plan))]:
                s = _score_yield_priority(cand, self.scan_ledger)
                age = (time.time() - cand.last_commit_ts) / 86400 if cand.last_commit_ts > 0 else -1
                logger.info(
                    "Yield-priority: %s score=%.1f (files=%d, kind=%s, age=%.0fd)",
                    cand.name, s, cand.file_count, cand.source_kind, age,
                )

        selected_candidates = mining_plan[:max_repos]
        logger.info(
            "Found %d repos to mine in %s (%d skipped as unchanged)",
            len(selected_candidates), base, len(skipped_candidates),
        )

        # Enable/disable fast-mine (deferred assimilation)
        self._fast_mine = fast

        report = MiningReport()
        start = time.monotonic()
        report.repos_skipped = len(skipped_candidates)

        for candidate, _reason in selected_candidates:
            repo_path = candidate.path
            repo_name = candidate.name
            try:
                result = await self.mine_repo(repo_path, repo_name, target_project_id, brain=brain)
                report.repo_results.append(result)
                report.repos_scanned += 1
                report.total_findings += len(result.findings)
                report.total_cost_usd += result.cost_usd
                report.total_tokens += result.tokens_used
                if not result.error and not result.skipped:
                    self.scan_ledger.record_result(candidate, result)

                if on_repo_complete:
                    on_repo_complete(repo_name, result)

            except Exception as e:
                logger.error("Failed to mine repo %s: %s", repo_name, e)
                report.repo_results.append(RepoMiningResult(
                    repo_name=repo_name,
                    repo_path=str(repo_path),
                    error=str(e),
                ))
                report.repos_scanned += 1

        # Generate tasks from all findings
        if generate_tasks:
            all_findings = []
            for result in report.repo_results:
                all_findings.extend(result.findings)

            tasks = await self._generate_tasks(
                all_findings, target_project_id, min_relevance
            )
            report.tasks = tasks
            report.tasks_generated = len(tasks)

        report.total_duration_seconds = time.monotonic() - start
        if report.total_findings > 0:
            maybe_mark_cag_stale(self.config)
            # Refresh manifests for any non-primary ganglia that received findings
            await self._refresh_ganglion_manifests(report)

        if fast and report.total_findings > 0:
            logger.info(
                "Fast-mine complete: %d findings stored as embryonic. "
                "Run `cam enrich` to complete assimilation.",
                report.total_findings,
            )

        return report

    async def _refresh_ganglion_manifests(self, report: MiningReport) -> None:
        """Refresh brain manifests for ganglia that received new findings."""
        try:
            from claw.community.manifest import save_manifest

            ganglions_touched: set[str] = set()
            for result in report.repo_results:
                # Use brain_breakdown (polyglot) if available, else detect
                if result.brain_breakdown:
                    for bp in result.brain_breakdown:
                        if bp.methodology_ids:
                            brain_cfg = self.config.mining.brains.get(bp.brain)
                            if brain_cfg and brain_cfg.ganglion_name:
                                ganglions_touched.add(brain_cfg.ganglion_name)
                elif result.findings:
                    brain_name = detect_repo_language(
                        Path(result.repo_path), self.config,
                    )
                    brain_cfg = self.config.mining.brains.get(brain_name)
                    if brain_cfg and brain_cfg.ganglion_name:
                        ganglions_touched.add(brain_cfg.ganglion_name)

            project_root = Path(self.config.database.db_path).parent.parent
            for ganglion_name in ganglions_touched:
                ganglion_db = project_root / "instances" / ganglion_name / "claw.db"
                if ganglion_db.exists():
                    db_config = DatabaseConfig(db_path=str(ganglion_db))
                    engine = DatabaseEngine(db_config)
                    await engine.connect()
                    try:
                        manifest_path = (
                            project_root / "instances" / ganglion_name / "brain_manifest.json"
                        )
                        await save_manifest(
                            engine, manifest_path,
                            ganglion_name,
                            f"{ganglion_name.title()} language patterns mined by CAM {ganglion_name} brain",
                        )
                        logger.info("Refreshed manifest for ganglion '%s'", ganglion_name)
                    finally:
                        await engine.close()
        except Exception as e:
            logger.warning("Failed to refresh ganglion manifests: %s", e)

    async def mine_repo(
        self,
        repo_path: str | Path,
        repo_name: str,
        target_project_id: str,
        metadata: dict[str, str] | None = None,
        secret_scan_files: set[str] | None = None,
        brain: str | None = None,
    ) -> RepoMiningResult:
        """Mine a single repository for patterns and features.

        Args:
            repo_path: Path to the repo root.
            repo_name: Human-readable repo name.
            target_project_id: Project ID for storing findings.
            metadata: Optional metadata to inject into stored methodologies
                (e.g., license_type from the assimilation pipeline).
            secret_scan_files: Set of relative file paths to exclude from
                serialization (flagged by pre-mine secret scanner).
            brain: Brain name override (e.g. "typescript", "go").
                When None, auto-detects from repo contents.

        Returns:
            RepoMiningResult with findings and metadata.
        """
        self._current_mine_metadata = metadata or {}
        start = time.monotonic()
        repo_path = Path(repo_path)

        # --- Brain selection and polyglot detection ---
        if brain is not None and brain != "auto":
            # Explicit brain override → single-brain path
            return await self._mine_single_brain(
                repo_path=repo_path, repo_name=repo_name,
                target_project_id=target_project_id,
                brain=brain, secret_scan_files=secret_scan_files,
                start=start,
            )

        # Auto-detect all language zones
        zones = detect_all_repo_languages(repo_path, self.config)
        if not zones:
            return RepoMiningResult(
                repo_name=repo_name, repo_path=str(repo_path),
                error="No recognizable source files found",
            )
        nonempty_zones = {
            brain_name: zone
            for brain_name, zone in zones.items()
            if zone.file_count > 0
        }
        if nonempty_zones:
            zones = nonempty_zones

        if len(zones) == 1:
            # Single-language repo → standard single-brain path
            single_brain = next(iter(zones.keys()))
            return await self._mine_single_brain(
                repo_path=repo_path, repo_name=repo_name,
                target_project_id=target_project_id,
                brain=single_brain, secret_scan_files=secret_scan_files,
                start=start,
            )

        # --- POLYGLOT MULTI-PASS MINING ---
        logger.info(
            "Polyglot repo %s detected: %s",
            repo_name,
            ", ".join(f"{b}({z.file_count} files, {z.pct}%%)" for b, z in
                      sorted(zones.items(), key=lambda x: -x[1].file_count)),
        )

        all_findings: list[MiningFinding] = []
        all_methodology_ids: list[str] = []
        all_action_template_ids: list[str] = []
        brain_breakdown: list[PolyglotMiningResult] = []
        total_files = 0
        total_tokens = 0

        # Mine each zone with its brain (largest zone first)
        for zone_brain, zone in sorted(zones.items(), key=lambda x: -x[1].file_count):
            zone_start = time.monotonic()
            if should_skip_polyglot_zone(zone, len(zones)):
                logger.info(
                    "Skipping %s zone=%s (%d files) below paid polyglot threshold",
                    repo_name, zone_brain, zone.file_count,
                )
                brain_breakdown.append(PolyglotMiningResult(
                    brain=zone_brain,
                    error=(
                        f"skipped_small_polyglot_zone: "
                        f"{zone.file_count} < {_MIN_ZONE_FILES}"
                    ),
                    duration_seconds=0.0,
                ))
                continue

            brain_config = self.config.mining.brains.get(
                zone_brain,
                self.config.mining.brains.get("misc", BrainConfig()),
            )
            if not brain_config.enabled:
                logger.info("Skipping disabled brain %s for %s", zone_brain, repo_name)
                continue

            logger.info(
                "Mining %s zone=%s (%d files, %.1f%%)",
                repo_name, zone_brain, zone.file_count, zone.pct,
            )

            # Language-filtered serialization
            repo_content, file_count = serialize_repo(
                repo_path,
                max_bytes=brain_config.max_bytes,
                exclude_files=secret_scan_files,
                config=self.config,
                language_filter=zone.file_extensions,
            )
            if not repo_content:
                brain_breakdown.append(PolyglotMiningResult(
                    brain=zone_brain, error="No content after serialization",
                ))
                continue

            total_files += file_count

            # Pass 1: Domain classification
            domain_info = self._classify_repo_domain(repo_content, file_count)

            # Pass 2: Knowledge overlap
            overlap = await self._assess_knowledge_overlap(repo_name, domain_info)

            token_budget = {
                "small": 4096, "medium": 6144, "large": 8192,
            }.get(domain_info["complexity"], 6144)

            model_selector = MiningModelSelector(self.config, self.repository)
            repo_content, file_count, prompt, estimated_tokens = (
                self._cap_repo_content_for_prompt_budget(
                    repo_path=repo_path,
                    repo_name=repo_name,
                    repo_content=repo_content,
                    file_count=file_count,
                    brain=zone_brain,
                    brain_config=brain_config,
                    domain_info=domain_info,
                    overlap=overlap,
                    secret_scan_files=secret_scan_files,
                    language_filter=zone.file_extensions,
                )
            )

            response, findings, recovery_attempts, recovery_strategy = (
                await self._mine_with_recovery(
                    prompt=prompt, token_budget=token_budget,
                    model_selector=model_selector,
                    estimated_tokens=estimated_tokens,
                    repo_name=repo_name, repo_path=repo_path,
                    repo_content=repo_content, file_count=file_count,
                    brain=zone_brain, brain_config=brain_config,
                    domain_info=domain_info, overlap=overlap,
                    secret_scan_files=secret_scan_files, start_time=zone_start,
                )
            )

            if findings:
                self._attach_symbol_provenance(findings, repo_path)

                # Store in brain's ganglion
                target_repo, target_sem = await ensure_language_ganglion(
                    zone_brain, brain_config,
                    self.repository, self.semantic_memory, self.config,
                )

                zone_meth_ids: list[str] = []
                try:
                    for finding in findings:
                        try:
                            mid = await self.store_finding(
                                finding, target_project_id,
                                run_assimilation=False, brain=zone_brain,
                                target_repository=target_repo,
                                target_semantic_memory=target_sem,
                            )
                            if mid:
                                zone_meth_ids.append(mid)
                            if finding.action_template_id:
                                all_action_template_ids.append(finding.action_template_id)
                        except Exception as e:
                            logger.warning("Failed to store finding '%s': %s", finding.title, e)

                    # Per-zone assimilation with ganglion-aware repo binding
                    if zone_meth_ids and self.assimilation_engine is not None and not self._fast_mine:
                        await self._assimilate_methodologies(
                            zone_meth_ids, repository=target_repo,
                        )
                finally:
                    await _close_temporary_ganglion_repository(
                        target_repo, self.repository,
                    )

                all_findings.extend(findings)
                all_methodology_ids.extend(zone_meth_ids)
                tokens_used = response.tokens_used if response else 0
                total_tokens += tokens_used

                brain_breakdown.append(PolyglotMiningResult(
                    brain=zone_brain,
                    findings_count=len(findings),
                    methodology_ids=zone_meth_ids,
                    tokens_used=tokens_used,
                    duration_seconds=time.monotonic() - zone_start,
                ))
            else:
                brain_breakdown.append(PolyglotMiningResult(
                    brain=zone_brain,
                    error=f"0 findings (recovery={recovery_attempts})",
                    duration_seconds=time.monotonic() - zone_start,
                ))

        duration = time.monotonic() - start
        breakdown_summary = ", ".join(
            f"{bp.brain}:{bp.findings_count}" for bp in brain_breakdown
        )
        logger.info(
            "Polyglot mining complete for %s: %d total findings [%s] in %.1fs",
            repo_name, len(all_findings), breakdown_summary, duration,
        )

        return RepoMiningResult(
            repo_name=repo_name,
            repo_path=str(repo_path),
            findings=all_findings,
            files_analyzed=total_files,
            tokens_used=total_tokens,
            duration_seconds=duration,
            methodology_ids=all_methodology_ids,
            action_template_ids=all_action_template_ids,
            brain_breakdown=brain_breakdown,
        )

    async def _mine_single_brain(
        self,
        *,
        repo_path: Path,
        repo_name: str,
        target_project_id: str,
        brain: str,
        secret_scan_files: set[str] | None,
        start: float,
    ) -> RepoMiningResult:
        """Mine a repo with a single brain (original code path)."""
        brain_config = self.config.mining.brains.get(
            brain,
            self.config.mining.brains.get("misc", BrainConfig()),
        )
        logger.info("Brain selected for %s: %s (max_bytes=%d, prompt=%s)",
                     repo_name, brain, brain_config.max_bytes, brain_config.prompt)

        # Serialize repo content with brain-specific limit
        repo_content, file_count = serialize_repo(
            repo_path,
            max_bytes=brain_config.max_bytes,
            exclude_files=secret_scan_files,
            config=self.config,
        )
        if not repo_content:
            return RepoMiningResult(
                repo_name=repo_name,
                repo_path=str(repo_path),
                error="No source files found",
            )

        # Gate: skip trivial repos that would waste an LLM call
        if file_count < 3:
            return RepoMiningResult(
                repo_name=repo_name,
                repo_path=str(repo_path),
                error=f"Too few source files ({file_count} < 3)",
            )
        if len(repo_content.encode("utf-8")) < 1024:
            return RepoMiningResult(
                repo_name=repo_name,
                repo_path=str(repo_path),
                error="Insufficient code content",
            )

        logger.info(
            "Serialized %s: %d files, %d bytes (brain=%s, limit=%dKB)",
            repo_name, file_count, len(repo_content.encode()),
            brain, brain_config.max_bytes // 1024,
        )

        # === PASS 1: Domain Classification (rule-based, free) ===
        domain_info = self._classify_repo_domain(repo_content, file_count)
        logger.info(
            "Pass 1 — domain: %s, language: %s, complexity: %s",
            domain_info["primary_domain"],
            domain_info["language"],
            domain_info["complexity"],
        )

        # === PASS 2: Knowledge Overlap Assessment (embedding search, cheap) ===
        overlap = await self._assess_knowledge_overlap(repo_name, domain_info)
        logger.info(
            "Pass 2 — repo-known: %d, domain-known: %d, overlap: %.2f, focus: %s",
            len(overlap.repo_known_titles),
            len(overlap.domain_known_titles),
            overlap.overlap_score,
            overlap.suggested_focus,
        )

        # Adaptive token budget based on repo complexity
        token_budget = {
            "small": 4096,
            "medium": 6144,
            "large": 8192,
        }.get(domain_info["complexity"], 6144)

        # --- Self-recovering LLM call with model escalation ---
        model_selector = MiningModelSelector(self.config, self.repository)
        repo_content, file_count, prompt, estimated_tokens = (
            self._cap_repo_content_for_prompt_budget(
                repo_path=repo_path,
                repo_name=repo_name,
                repo_content=repo_content,
                file_count=file_count,
                brain=brain,
                brain_config=brain_config,
                domain_info=domain_info,
                overlap=overlap,
                secret_scan_files=secret_scan_files,
            )
        )
        logger.info(
            "Estimated prompt tokens for %s: ~%dK (brain=%s)",
            repo_name, estimated_tokens // 1000, brain,
        )

        response, findings, recovery_attempts, recovery_strategy = (
            await self._mine_with_recovery(
                prompt=prompt,
                token_budget=token_budget,
                model_selector=model_selector,
                estimated_tokens=estimated_tokens,
                repo_name=repo_name,
                repo_path=repo_path,
                repo_content=repo_content,
                file_count=file_count,
                brain=brain,
                brain_config=brain_config,
                domain_info=domain_info,
                overlap=overlap,
                secret_scan_files=secret_scan_files,
                start_time=start,
            )
        )

        if not findings:
            duration = time.monotonic() - start
            return RepoMiningResult(
                repo_name=repo_name,
                repo_path=str(repo_path),
                files_analyzed=file_count,
                duration_seconds=duration,
                error="All recovery strategies exhausted — 0 findings",
                recovery_attempts=recovery_attempts,
                recovery_strategy=recovery_strategy,
            )

        self._attach_symbol_provenance(findings, Path(repo_path))
        logger.info(
            "Extracted %d findings from %s (brain=%s, recovery=%d, strategy=%s)",
            len(findings), repo_name, brain, recovery_attempts, recovery_strategy,
        )

        # --- Ganglion routing: get or create target ganglion ---
        target_repo, target_sem = await ensure_language_ganglion(
            brain, brain_config,
            self.repository, self.semantic_memory, self.config,
        )

        # Store each finding in the brain's ganglion
        methodology_ids: list[str] = []
        action_template_ids: list[str] = []
        try:
            for finding in findings:
                try:
                    methodology_id = await self.store_finding(
                        finding,
                        target_project_id,
                        run_assimilation=False,
                        brain=brain,
                        target_repository=target_repo,
                        target_semantic_memory=target_sem,
                    )
                    if methodology_id:
                        methodology_ids.append(methodology_id)
                    if finding.action_template_id:
                        action_template_ids.append(finding.action_template_id)
                except Exception as e:
                    logger.warning("Failed to store finding '%s': %s", finding.title, e)

            if methodology_ids and self.assimilation_engine is not None and not self._fast_mine:
                await self._assimilate_methodologies(
                    methodology_ids, repository=target_repo,
                )
        finally:
            await _close_temporary_ganglion_repository(
                target_repo, self.repository,
            )

        duration = time.monotonic() - start
        return RepoMiningResult(
            repo_name=repo_name,
            repo_path=str(repo_path),
            findings=findings,
            files_analyzed=file_count,
            tokens_used=response.tokens_used if response else 0,
            cost_usd=0.0,
            duration_seconds=duration,
            methodology_ids=methodology_ids,
            action_template_ids=action_template_ids,
        )

    async def store_finding(
        self,
        finding: MiningFinding,
        target_project_id: str,
        *,
        run_assimilation: bool = True,
        brain: str | None = None,
        target_repository: Repository | None = None,
        target_semantic_memory: SemanticMemory | None = None,
    ) -> Optional[str]:
        """Store a mining finding in semantic memory as a Methodology.

        Applies enhanced quality gate and pre-save dedup before storing.

        Args:
            finding: The extracted finding.
            target_project_id: Project to associate with (unused in methodology but tracked via tags).
            brain: Brain name for tagging (e.g. "typescript").
            target_repository: Optional ganglion-specific Repository.
            target_semantic_memory: Optional ganglion-specific SemanticMemory.

        Returns:
            The methodology ID, or None if blocked by quality gate or dedup.
        """
        # Enhanced quality gate
        passes, reason = self._enhanced_quality_gate(finding)
        if not passes:
            logger.info("Quality gate blocked finding '%s': %s", finding.title, reason)
            return None

        # Build a rich problem description for embedding
        problem_desc = (
            f"[Mined from {finding.source_repo}] {finding.title}: "
            f"{finding.description}"
        )

        # Build solution code from implementation sketch
        solution = (
            f"## {finding.title}\n\n"
            f"**Category:** {finding.category}\n"
            f"**Source:** {finding.source_repo}\n"
            f"**Relevance:** {finding.relevance_score:.2f}\n\n"
            f"### Description\n{finding.description}\n\n"
            f"### Implementation Sketch\n{finding.implementation_sketch}\n\n"
            f"### Augmentation Notes\n{finding.augmentation_notes}\n"
        )

        tags = [
            "mined",
            f"source:{finding.source_repo}",
            f"category:{finding.category}",
        ]
        if brain:
            tags.append(f"brain:{brain}")

        sem = target_semantic_memory or self.semantic_memory
        repo = target_repository or self.repository

        methodology = await sem.save_solution(
            problem_description=problem_desc,
            solution_code=solution,
            methodology_notes=finding.augmentation_notes,
            tags=tags,
            language=finding.language,
            scope="global",
            methodology_type="PATTERN",
            files_affected=finding.source_files,
        )

        capability_data = self._seed_capability_data_from_finding(finding)
        await repo.update_methodology_capability_data(
            methodology.id,
            capability_data,
        )
        methodology.capability_data = capability_data

        # Apply pseudo-RAG triage scoring and operational card enrichment
        try:
            from claw.knowledge_triage import compute_triage_score
            from claw.memory.prompt_pack import (
                classify_accuracy_contract,
                extract_use_immediately_directives,
                generate_tension_questions,
            )
            triage_result = compute_triage_score(methodology)
            accuracy_contract = classify_accuracy_contract(methodology)
            use_directives = extract_use_immediately_directives(methodology)
            tension_qs = generate_tension_questions(methodology)

            # Scenario-anchored enrichment: override generic directives with
            # grounded, KB-aware directives when scenarios are available.
            try:
                enrichment = await self._scenario_enrich(methodology, repo)
                if enrichment and enrichment.directives:
                    use_directives = enrichment.directives
                    logger.debug(
                        "Scenario enrichment: %d grounded directives for %s",
                        len(use_directives), methodology.id,
                    )
                if enrichment and enrichment.tension_questions:
                    tension_qs = enrichment.tension_questions
            except Exception as se:
                logger.debug("Scenario enrichment skipped for %s: %s", methodology.id, se)

            await repo.update_methodology_directives(
                methodology.id,
                accuracy_contract=accuracy_contract,
                concept_type=triage_result.concept_type,
                use_immediately_as=use_directives,
                tension_questions=tension_qs,
                triage_score=triage_result.composite_score,
            )
            methodology.accuracy_contract = accuracy_contract
            methodology.concept_type = triage_result.concept_type
            methodology.use_immediately_as = use_directives
            methodology.tension_questions = tension_qs
            methodology.triage_score = triage_result.composite_score
            logger.debug(
                "Triage: %s — score=%.2f, contract=%s, type=%s, directives=%d",
                methodology.id, triage_result.composite_score,
                accuracy_contract, triage_result.concept_type,
                len(use_directives),
            )
        except Exception as e:
            logger.warning("Triage scoring failed for %s: %s", methodology.id, e)

        logger.debug("Stored finding '%s' as methodology %s", finding.title, methodology.id)

        action_template = self._build_action_template_from_finding(
            finding,
            methodology.id,
        )
        await repo.create_action_template(action_template)
        finding.action_template_id = action_template.id
        logger.debug(
            "Created action template %s for finding '%s'",
            action_template.id,
            finding.title,
        )

        # Trigger capability assimilation
        if run_assimilation and self.assimilation_engine is not None:
            try:
                await self.assimilation_engine.assimilate(methodology.id)
            except Exception as e:
                logger.warning("Assimilation failed for %s: %s", methodology.id, e)

        if getattr(self.config.feature_flags, "component_cards", False):
            try:
                await self.backfill_components(
                    methodology_ids=[methodology.id],
                    repository=repo,
                )
            except Exception as e:
                logger.warning(
                    "Component backfill failed for methodology %s: %s",
                    methodology.id,
                    e,
                )

        return methodology.id

    async def _scenario_enrich(
        self,
        methodology: Methodology,
        repository: Repository,
    ) -> Any:
        """Apply scenario-anchored enrichment to a methodology.

        Lazy-initializes the ScenarioEnricher and builds scenarios once per
        mining session (cached on the enricher instance). Returns an
        EnrichmentResult or None if enrichment is not available.
        """
        from claw.scenario_enrichment import ScenarioEnricher

        if self._scenario_enricher is None:
            self._scenario_enricher = ScenarioEnricher()

        enricher: ScenarioEnricher = self._scenario_enricher

        # Build scenarios once (cached after first call)
        if enricher._cached_scenarios is None:
            embed_engine = getattr(self.semantic_memory, "embedding_engine", None)
            await enricher.build_scenarios(repository, embed_engine)

        # Get methodology embedding for cosine scoring
        meth_embedding: list[float] | None = None
        embed_engine = getattr(self.semantic_memory, "embedding_engine", None)
        if embed_engine is not None:
            try:
                meth_embedding = embed_engine.encode(methodology.problem_description[:2000])
            except Exception:
                pass

        return enricher.enrich(
            methodology,
            methodology_embedding=meth_embedding,
        )

    async def _assimilate_methodologies(
        self,
        methodology_ids: list[str],
        *,
        repository: Repository | None = None,
    ) -> None:
        if self.assimilation_engine is None or not methodology_ids:
            return

        # When a ganglion repository is provided, create a temporary
        # assimilation engine bound to that repo so lookups succeed.
        engine = self.assimilation_engine
        if repository is not None and repository is not self.repository:
            from claw.evolution.assimilation import CapabilityAssimilationEngine
            engine = CapabilityAssimilationEngine(
                repository, self.llm_client, self.config,
            )

        limit = max(1, min(self._assimilation_parallelism, len(methodology_ids)))
        semaphore = asyncio.Semaphore(limit)

        async def _run(methodology_id: str) -> None:
            async with semaphore:
                try:
                    await engine.assimilate(methodology_id)
                except Exception as e:
                    logger.warning("Assimilation failed for %s: %s", methodology_id, e)

        await asyncio.gather(*(_run(methodology_id) for methodology_id in methodology_ids))

    # ------------------------------------------------------------------
    # Multi-pass mining helpers
    # ------------------------------------------------------------------

    def _classify_repo_domain(
        self, repo_content: str, file_count: int
    ) -> dict[str, Any]:
        """Pass 1: Lightweight domain classification from serialized repo content.

        Uses keyword matching on README + config files (already serialized first
        due to priority ordering) to classify the repo's domain. No LLM call.

        Returns:
            Dict with primary_domain, secondary_domains, language, complexity,
            and readme_summary.
        """
        content_lower = repo_content[:20_000].lower()  # scan first ~20KB

        # --- Extract README section ---
        readme_summary = ""
        readme_marker = "--- file: readme"
        idx = content_lower.find(readme_marker)
        if idx != -1:
            # Find end of README section (next file marker or 3000 chars)
            next_file = repo_content.find("--- FILE:", idx + 10)
            end = next_file if next_file != -1 else min(idx + 3000, len(repo_content))
            readme_summary = repo_content[idx:end].strip()

        # --- Detect language from config files ---
        language = "unknown"
        for config_name, lang in _LANGUAGE_SIGNALS.items():
            if f"--- file: {config_name}" in content_lower or f"/{config_name}" in content_lower:
                language = lang
                break

        # --- Keyword-based domain scoring ---
        scores: dict[str, int] = {}
        scan_text = (readme_summary + "\n" + repo_content[:10_000]).lower()
        for category, keywords in _DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in scan_text)
            if score > 0:
                scores[category] = score

        # Sort by score descending
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        primary_domain = ranked[0][0] if ranked else "cross_cutting"
        secondary_domains = [cat for cat, _ in ranked[1:4] if _ >= 2]

        # --- Complexity estimate ---
        if file_count < 50:
            complexity = "small"
        elif file_count <= 200:
            complexity = "medium"
        else:
            complexity = "large"

        return {
            "primary_domain": primary_domain,
            "secondary_domains": secondary_domains,
            "language": language,
            "complexity": complexity,
            "readme_summary": readme_summary[:2000],
        }

    async def _assess_knowledge_overlap(
        self, repo_name: str, domain_info: dict[str, Any]
    ) -> KnowledgeOverlap:
        """Pass 2: Structured assessment of what the KB already covers in this domain.

        Combines repo-specific dedup (what we mined from this repo before) with
        domain-wide semantic search (what we know about similar topics from other repos).

        Returns:
            KnowledgeOverlap with scores and suggested focus categories.
        """
        # Repo-specific: what we already mined from this exact repo
        repo_known = await self._check_already_mined(repo_name)

        # Domain-wide: semantic search using README excerpt
        domain_titles: list[str] = []
        domain_categories: list[str] = []
        readme_excerpt = domain_info.get("readme_summary", "")
        if self.semantic_memory and readme_excerpt.strip():
            try:
                similar = await self.semantic_memory.find_similar(
                    readme_excerpt[:2000], limit=10
                )
                for s in similar:
                    if s.methodology and s.methodology.problem_description:
                        domain_titles.append(s.methodology.problem_description[:120])
                        # Extract category from tags
                        for tag in (s.methodology.tags or []):
                            if tag.startswith("category:"):
                                cat = tag.removeprefix("category:")
                                if cat not in domain_categories:
                                    domain_categories.append(cat)
            except Exception as e:
                logger.debug("Domain overlap search failed: %s", e)

        # Compute overlap score: ratio of covered categories
        all_categories = list(_VALID_CATEGORIES)
        covered = set(domain_categories)
        overlap_score = len(covered) / len(all_categories) if all_categories else 0.0

        # Suggested focus: categories not well-covered AND relevant to this repo
        repo_domains = set(
            [domain_info["primary_domain"]]
            + domain_info.get("secondary_domains", [])
        )
        # Include all categories but prioritize those related to the repo's domain
        suggested = [
            cat for cat in all_categories
            if cat not in covered
        ]
        # Put repo-relevant gaps first
        relevant_gaps = [c for c in suggested if c in repo_domains]
        other_gaps = [c for c in suggested if c not in repo_domains]
        suggested_focus = relevant_gaps + other_gaps

        return KnowledgeOverlap(
            repo_known_titles=repo_known,
            domain_known_titles=domain_titles,
            domain_known_categories=domain_categories,
            overlap_score=round(overlap_score, 2),
            suggested_focus=suggested_focus[:5],  # top 5 gaps
        )

    def _build_mining_context(
        self, domain_info: dict[str, Any], overlap: KnowledgeOverlap
    ) -> list[str]:
        """Build structured context lines for the mining LLM prompt.

        Combines Pass 1 domain classification and Pass 2 overlap assessment
        into directives that guide the mining LLM to focus on novel findings.
        """
        lines: list[str] = []

        # Domain classification (Pass 1)
        lines.append("# Domain Classification")
        lines.append(f"Primary domain: {domain_info['primary_domain']}")
        if domain_info.get("secondary_domains"):
            lines.append(f"Secondary domains: {', '.join(domain_info['secondary_domains'])}")
        lines.append(f"Language: {domain_info['language']}")
        lines.append(f"Complexity: {domain_info['complexity']}")

        # Knowledge overlap (Pass 2)
        if overlap.repo_known_titles:
            lines.append(
                f"\n# Already mined from this repo ({len(overlap.repo_known_titles)} patterns):"
            )
            for title in overlap.repo_known_titles:
                lines.append(f"- {title}")

        if overlap.domain_known_titles:
            lines.append("\n# CLAW knows these related patterns from OTHER repos:")
            for title in overlap.domain_known_titles[:8]:
                lines.append(f"- {title}")

        # Focus directives
        if overlap.suggested_focus:
            lines.append("\n# PRIORITY: Focus mining on these under-represented categories:")
            for cat in overlap.suggested_focus:
                lines.append(f"- {cat}")

        lines.append(
            "\n# Instructions: DO NOT repeat known patterns. "
            "Prioritize novel findings in under-represented categories. "
            "ALSO extract novel implementation techniques from well-covered categories "
            "— e.g. structured logging with perf_counter timing, idempotent operation "
            "patterns, or result normalization even if similar categories exist."
        )
        return lines

    async def _find_domain_knowledge(self, readme_excerpt: str) -> list[str]:
        """Search existing knowledge base for patterns similar to this repo's domain.

        Uses the first ~2000 chars of repo content (typically README) as a semantic
        query to find what we already know in this domain across ALL repos.

        Returns:
            List of methodology titles/descriptions (max 5, truncated to 120 chars).
        """
        if not self.semantic_memory or not readme_excerpt.strip():
            return []
        try:
            similar = await self.semantic_memory.find_similar(
                readme_excerpt[:2000], limit=5
            )
            titles = []
            for s in similar:
                if s.methodology and s.methodology.problem_description:
                    titles.append(s.methodology.problem_description[:120])
            return titles
        except Exception as e:
            logger.debug("Domain knowledge search failed: %s", e)
            return []

    async def _check_already_mined(self, repo_name: str) -> list[str]:
        """Check what CLAW already knows from a repo.

        Searches semantic memory for methodologies tagged with source:{repo_name}.

        Returns:
            List of existing finding titles/descriptions.
        """
        try:
            existing = await self.repository.get_methodologies_by_tag(
                f"source:{repo_name}", limit=50
            )
            titles = [m.problem_description[:200] for m in existing]
            if titles:
                logger.info(
                    "Found %d existing findings from %s", len(titles), repo_name
                )
            return titles
        except Exception as e:
            logger.warning("Failed to check already-mined for %s: %s", repo_name, e)
            return []

    def _enhanced_quality_gate(
        self, finding: MiningFinding
    ) -> tuple[bool, str]:
        """Multi-dimensional quality gate beyond simple relevance.

        Checks:
        1. Relevance score >= 0.4 (existing minimum)
        2. Description length >= configured minimum
        3. Category is valid

        Returns:
            (passes, rejection_reason).
        """
        if finding.relevance_score < 0.4:
            return False, f"relevance too low ({finding.relevance_score:.2f} < 0.4)"

        min_desc = getattr(self.config, "governance", None)
        min_desc_len = 50
        if min_desc and hasattr(min_desc, "mining_min_description_length"):
            min_desc_len = min_desc.mining_min_description_length

        if len(finding.description) < min_desc_len:
            return False, f"description too short ({len(finding.description)} < {min_desc_len})"

        if finding.category not in _VALID_CATEGORIES:
            return False, f"invalid category: {finding.category}"

        return True, ""

    async def _generate_tasks(
        self,
        findings: list[MiningFinding],
        target_project_id: str,
        min_relevance: float = 0.6,
    ) -> list[Task]:
        """Create enhancement tasks from high-relevance findings.

        Args:
            findings: All findings from mining.
            target_project_id: Project to create tasks under.
            min_relevance: Minimum relevance_score to generate a task.

        Returns:
            List of created Task objects.
        """
        tasks: list[Task] = []

        # Filter and sort by relevance
        eligible = [f for f in findings if f.relevance_score >= min_relevance]
        eligible.sort(key=lambda f: f.relevance_score, reverse=True)

        for finding in eligible:
            priority = _relevance_to_priority(finding.relevance_score)
            execution_steps = [s.strip() for s in finding.execution_steps if s.strip()]
            acceptance_checks = [s.strip() for s in finding.acceptance_checks if s.strip()]
            rollback_steps = [s.strip() for s in finding.rollback_steps if s.strip()]
            preconditions = [s.strip() for s in finding.preconditions if s.strip()]

            runbook_sections: list[str] = []
            if preconditions:
                runbook_sections.append(
                    "### Preconditions\n" + "\n".join(f"- {p}" for p in preconditions)
                )
            if execution_steps:
                runbook_sections.append(
                    "### Execution Steps\n" + "\n".join(f"- `{cmd}`" for cmd in execution_steps)
                )
            if acceptance_checks:
                runbook_sections.append(
                    "### Acceptance Checks\n" + "\n".join(f"- `{cmd}`" for cmd in acceptance_checks)
                )
            if rollback_steps:
                runbook_sections.append(
                    "### Rollback\n" + "\n".join(f"- `{cmd}`" for cmd in rollback_steps)
                )

            runbook_text = "\n\n".join(runbook_sections)

            task = Task(
                project_id=target_project_id,
                title=f"[Mined:{finding.source_repo}] {finding.title}"[:200],
                description=(
                    f"## Enhancement from {finding.source_repo}\n\n"
                    f"**Category:** {finding.category}\n"
                    f"**Relevance:** {finding.relevance_score:.2f}\n"
                    f"**Language:** {finding.language}\n\n"
                    f"### What\n{finding.description}\n\n"
                    f"### How\n{finding.implementation_sketch}\n\n"
                    f"### Why\n{finding.augmentation_notes}\n\n"
                    f"### Source Files\n"
                    + "\n".join(f"- `{f}`" for f in finding.source_files)
                    + (f"\n\n{runbook_text}" if runbook_text else "")
                ),
                status=TaskStatus.PENDING,
                priority=priority,
                task_type=finding.category,
                recommended_agent=_category_to_agent(finding.category),
                action_template_id=finding.action_template_id,
                execution_steps=execution_steps,
                acceptance_checks=acceptance_checks,
            )

            try:
                saved = await self.repository.create_task(task)
                tasks.append(saved)
                logger.info(
                    "Created task '%s' (priority=%d) from finding in %s",
                    saved.title[:60], priority, finding.source_repo,
                )
            except Exception as e:
                logger.warning("Failed to create task for '%s': %s", finding.title, e)

        return tasks


def _canonicalize_name(name: str) -> str:
    """Strip version/variant suffixes from a repo directory name.

    Iteratively removes common suffixes like -v2, -final, -backup, _old,
    trailing digits after a dash, etc.

    Examples:
        "ace-forecaster-v3"  -> "ace-forecaster"
        "grokflow-cli-final" -> "grokflow-cli"
        "my-project-2"       -> "my-project"
        "tool-wip"           -> "tool"
        "tool-dev-v2"        -> "tool"
    """
    result = name.lower().strip()
    suffix_re = re.compile(
        r'[-_](v?\d+|final|latest|old|backup|copy|wip|dev|test|staging|prod|new|orig)$'
    )
    while True:
        new = suffix_re.sub('', result)
        if new == result:
            break
        result = new
    return result


def _collect_repo_metadata(
    repo_path: Path,
    code_extensions: set[str] | None = None,
    skip_dirs: set[str] | None = None,
) -> tuple[int, float, int, str, str]:
    """Collect lightweight metadata for a repo (no subprocess calls).

    Returns:
        (file_count, last_commit_ts, total_bytes, scan_signature, content_hash)
    """
    exts = code_extensions or _CODE_EXTENSIONS
    dirs = skip_dirs or _SKIP_DIRS

    file_count = 0
    total_bytes = 0
    latest_source_ts = 0.0
    fingerprint = hashlib.sha1()
    content_hasher = hashlib.sha256()
    content_files_hashed = 0

    try:
        for path in sorted(repo_path.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(repo_path)
            if any(part in dirs for part in rel.parts):
                continue
            if path.suffix.lower() not in exts:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            file_count += 1
            total_bytes += stat.st_size
            latest_source_ts = max(latest_source_ts, stat.st_mtime)
            # Metadata fingerprint (mtime-based, for incremental skip)
            fingerprint.update(str(rel).encode("utf-8", errors="replace"))
            fingerprint.update(b":")
            fingerprint.update(str(stat.st_size).encode())
            fingerprint.update(b":")
            fingerprint.update(str(stat.st_mtime_ns).encode())
            fingerprint.update(b"\n")
            # Content hash (first 4KB per file, for cross-repo dedup)
            if content_files_hashed < _CONTENT_HASH_MAX_FILES:
                try:
                    with open(path, "rb") as fh:
                        chunk = fh.read(_CONTENT_HASH_CHUNK)
                    content_hasher.update(str(rel).encode("utf-8", errors="replace"))
                    content_hasher.update(b":")
                    content_hasher.update(chunk)
                    content_hasher.update(b"\n")
                    content_files_hashed += 1
                except (OSError, PermissionError):
                    pass
    except (PermissionError, OSError):
        pass

    # Use .git directory mtime as proxy for last commit timestamp
    last_commit_ts = 0.0
    git_dir = repo_path / ".git"
    for ref_name in ("refs/heads/main", "refs/heads/master", "HEAD"):
        ref_path = git_dir / ref_name
        try:
            last_commit_ts = max(last_commit_ts, ref_path.stat().st_mtime)
        except OSError:
            pass
    if last_commit_ts == 0.0:
        try:
            last_commit_ts = git_dir.stat().st_mtime
        except OSError:
            pass
    last_commit_ts = max(last_commit_ts, latest_source_ts)
    scan_signature = hashlib.sha1(
        f"{file_count}:{total_bytes}:{last_commit_ts:.6f}:{fingerprint.hexdigest()}".encode("utf-8")
    ).hexdigest()
    content_hash = content_hasher.hexdigest() if content_files_hashed > 0 else ""

    return file_count, last_commit_ts, total_bytes, scan_signature, content_hash


def _discover_repos(
    base: Path,
    max_depth: int = 6,
    config: ClawConfig | None = None,
) -> list[RepoCandidate]:
    """Find repositories or repo-like source trees under a base directory using BFS.

    Scans up to max_depth levels deep using os.scandir() for performance.
    Stops descending into a directory once a repo candidate is found.
    Collects metadata for each repo to support iteration dedup.

    Args:
        base: Root directory to scan.
        max_depth: Maximum directory depth to search (default 6).
        config: Optional ClawConfig for extra extensions/skip dirs.

    Returns:
        List of RepoCandidate objects sorted by canonical_name then name.
    """
    code_exts = _get_code_extensions(config)
    skip_dirs = _get_skip_dirs(config)
    ignore_patterns = _load_mineignore(base)

    candidates: list[RepoCandidate] = []
    seen: set[str] = set()  # resolved path strings for dedup

    # BFS queue: (directory_path, current_depth)
    frontier: list[tuple[Path, int]] = [(base, 0)]

    while frontier:
        next_frontier: list[tuple[Path, int]] = []

        for dir_path, depth in frontier:
            # Check .mineignore against relative path from base
            if ignore_patterns and dir_path != base:
                try:
                    rel_str = str(dir_path.relative_to(base))
                except ValueError:
                    rel_str = dir_path.name
                if _is_mineignored(rel_str, ignore_patterns):
                    continue

            # Check if this directory is a git repo or extracted source tree
            git_marker = dir_path / ".git"
            try:
                is_repo = git_marker.exists()
            except (PermissionError, OSError):
                is_repo = False

            is_source_tree = False
            if not is_repo:
                is_source_tree = _looks_like_source_tree(dir_path, code_exts, skip_dirs)

            if is_repo or (is_source_tree and dir_path != base):
                try:
                    resolved = str(dir_path.resolve())
                except OSError:
                    resolved = str(dir_path)

                if resolved not in seen:
                    seen.add(resolved)
                    name = dir_path.name
                    file_count, last_commit_ts, total_bytes, scan_signature, content_hash = (
                        _collect_repo_metadata(dir_path, code_exts, skip_dirs)
                    )
                    candidates.append(RepoCandidate(
                        path=dir_path,
                        name=name,
                        canonical_name=_canonicalize_name(name),
                        depth=depth,
                        source_kind="git" if is_repo else "source_tree",
                        file_count=file_count,
                        last_commit_ts=last_commit_ts,
                        total_bytes=total_bytes,
                        scan_signature=scan_signature,
                        content_hash=content_hash,
                    ))
                # Don't descend into candidate repos — they're leaf nodes
                continue

            # Not a repo — descend if within depth limit
            if depth >= max_depth:
                continue

            try:
                with os.scandir(dir_path) as entries:
                    for entry in sorted(entries, key=lambda e: e.name):
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                        if entry.name.startswith("."):
                            continue
                        if entry.name in skip_dirs:
                            continue
                        next_frontier.append((Path(entry.path), depth + 1))
            except (PermissionError, OSError):
                continue

        frontier = next_frontier

    # Sort by canonical_name, then by name for deterministic ordering
    candidates.sort(key=lambda c: (c.canonical_name, c.name))
    return candidates


def _looks_like_source_tree(
    dir_path: Path,
    code_extensions: set[str] | None = None,
    skip_dirs: set[str] | None = None,
) -> bool:
    """Heuristic for extracted source folders that are not git repos.

    A directory is considered mineable if it has at least one common project
    marker file and at least one code/config/document file near the root, or
    if it contains multiple source files near the root.
    """
    exts = code_extensions or _CODE_EXTENSIONS
    dirs = skip_dirs or _SKIP_DIRS

    marker_names = {
        "README.md", "README.rst", "README.txt",
        "pyproject.toml", "package.json", "Cargo.toml", "go.mod",
        "requirements.txt", "setup.py", "Makefile", "Dockerfile",
    }

    root_code_hits = 0
    nested_code_hits = 0
    has_marker = False

    try:
        with os.scandir(dir_path) as entries:
            for entry in entries:
                name = entry.name
                if name.startswith(".") and name != ".git":
                    continue
                if entry.is_file(follow_symlinks=False):
                    if name in marker_names:
                        has_marker = True
                    _, ext = os.path.splitext(name)
                    if ext.lower() in exts:
                        root_code_hits += 1
                elif entry.is_dir(follow_symlinks=False) and name not in dirs:
                    try:
                        with os.scandir(entry.path) as sub_entries:
                            for sub in sub_entries:
                                if not sub.is_file(follow_symlinks=False):
                                    continue
                                _, ext = os.path.splitext(sub.name)
                                if ext.lower() in exts:
                                    nested_code_hits += 1
                                    if nested_code_hits >= 2:
                                        break
                    except (PermissionError, OSError):
                        continue
                if has_marker and (root_code_hits + nested_code_hits) >= 1:
                    return True
                if root_code_hits >= 2:
                    return True
    except (PermissionError, OSError):
        return False

    return False


def _dedup_iterations(
    candidates: list[RepoCandidate],
) -> tuple[list[RepoCandidate], list[tuple[RepoCandidate, str]]]:
    """Deduplicate repo iterations by canonical name.

    Groups candidates by canonical_name and picks the best version
    based on: last_commit_ts (primary), file_count (secondary),
    total_bytes (tertiary).

    Args:
        candidates: All discovered repo candidates.

    Returns:
        (selected, skipped) where skipped includes (candidate, reason) tuples.
    """
    from collections import defaultdict

    groups: dict[str, list[RepoCandidate]] = defaultdict(list)
    for c in candidates:
        groups[c.canonical_name].append(c)

    selected: list[RepoCandidate] = []
    skipped: list[tuple[RepoCandidate, str]] = []

    for canonical, group in sorted(groups.items()):
        if len(group) == 1:
            selected.append(group[0])
            continue

        # Score: sort by (last_commit_ts, file_count, total_bytes) descending
        group.sort(
            key=lambda c: (c.last_commit_ts, c.file_count, c.total_bytes),
            reverse=True,
        )

        winner = group[0]
        selected.append(winner)

        for loser in group[1:]:
            skipped.append((
                loser,
                f"superseded by {winner.name} ({winner.path})",
            ))

        if len(group) > 1:
            logger.info(
                "Dedup '%s': selected '%s' (%d files, ts=%.0f), skipped %d iterations",
                canonical, winner.name, winner.file_count, winner.last_commit_ts,
                len(group) - 1,
            )

    # Second pass: content hash dedup across different canonical names
    content_groups: dict[str, list[RepoCandidate]] = defaultdict(list)
    for c in selected:
        if c.content_hash:
            content_groups[c.content_hash].append(c)

    content_deduped: list[RepoCandidate] = []
    content_seen: set[str] = set()
    for c in selected:
        if not c.content_hash or c.content_hash not in content_groups:
            content_deduped.append(c)
            continue
        if c.content_hash in content_seen:
            continue  # already processed this group
        content_seen.add(c.content_hash)
        group = content_groups[c.content_hash]
        if len(group) == 1:
            content_deduped.append(group[0])
        else:
            group.sort(
                key=lambda x: (x.last_commit_ts, x.file_count, x.total_bytes),
                reverse=True,
            )
            winner = group[0]
            content_deduped.append(winner)
            for loser in group[1:]:
                skipped.append((loser, f"content-duplicate of {winner.name} ({winner.path})"))
            logger.info(
                "Content dedup: '%s' matches %d other repos, kept '%s'",
                winner.content_hash[:12], len(group) - 1, winner.name,
            )

    content_deduped.sort(key=lambda c: (c.canonical_name, c.name))
    return content_deduped, skipped


def _score_yield_priority(
    candidate: RepoCandidate,
    ledger: "RepoScanLedger",
    *,
    now: float | None = None,
) -> float:
    """Score a repo candidate by expected mining yield.

    Higher score = mine first.  Max theoretical score = 100.

    Factors (data-driven from 90 mined repos — findings/token ratio
    does NOT scale linearly with repo size):
      1. Recency          (0–40)  recently active repos yield better patterns
      2. File-count sweet spot (0–25)  20-500 files is goldilocks
      3. Source kind       (0–10)  git > loose source tree
      4. Canonical sibling (-20)  if another iteration was already mined
      5. Size efficiency   (0–25)  smaller repos are cheaper per finding
    """
    _now = now or time.time()
    score = 0.0

    # --- Factor 1: Recency (0-40 points) ---
    if candidate.last_commit_ts > 0:
        age_days = (_now - candidate.last_commit_ts) / 86400
        if age_days <= 90:
            score += 40.0
        elif age_days <= 365:
            score += 40.0 * (1.0 - (age_days - 90) / 275)
        elif age_days <= 730:
            score += 10.0 * (1.0 - (age_days - 365) / 365)

    # --- Factor 2: File count sweet spot (0-25 points) ---
    fc = candidate.file_count
    if 20 <= fc <= 500:
        score += 25.0
    elif 10 <= fc < 20:
        score += 15.0
    elif 500 < fc <= 2000:
        score += 15.0
    elif fc < 10:
        score += 5.0
    else:
        score += 5.0

    # --- Factor 3: Source kind (0-10 points) ---
    if candidate.source_kind == "git":
        score += 10.0
    else:
        score += 3.0

    # --- Factor 4: Canonical sibling already mined (-20 penalty) ---
    ledger._load()
    for _key, record in ledger._records.items():
        if record.canonical_name == candidate.canonical_name:
            score -= 20.0
            break

    # --- Factor 5: Size efficiency (0-25 points) ---
    if candidate.total_bytes > 0:
        mb = candidate.total_bytes / (1024 * 1024)
        if mb <= 10:
            score += 25.0
        elif mb <= 50:
            score += 20.0
        elif mb <= 200:
            score += 10.0
        else:
            score += 2.0

    return score


def _relevance_to_priority(relevance: float) -> int:
    """Map relevance score to task priority (0-10 scale)."""
    if relevance >= 0.9:
        return 9
    if relevance >= 0.8:
        return 7
    if relevance >= 0.7:
        return 5
    if relevance >= 0.6:
        return 3
    return 1


def _category_to_agent(category: str) -> str:
    """Suggest an agent based on finding category."""
    mapping = {
        "architecture": "claude",
        "ai_integration": "claude",
        "memory": "claude",
        "code_quality": "codex",
        "cli_ux": "codex",
        "testing": "codex",
        "data_processing": "gemini",
        "security": "claude",
        "algorithm": "gemini",
        "cross_cutting": "grok",
    }
    return mapping.get(category, "claude")


def _default_scan_ledger_path(config: ClawConfig) -> Path:
    db_path = str(config.database.db_path)
    if db_path == ":memory:":
        return Path("data") / "mining_registry.json"
    return Path(db_path).resolve().parent / "mining_registry.json"


async def assess_findings_against_existing(
    report: MiningReport,
    embedding_engine: Any,
    repository: Repository,
    semantic_memory: SemanticMemory,
) -> list[dict[str, Any]]:
    """Classify mined findings as DUPLICATE, PARTIAL_GAP, or NOVEL.

    For each finding in the mining report, computes embedding similarity
    against all existing methodologies in semantic memory.  Returns a list
    of assessment dicts with classification, similarity score, and the
    title of the closest existing methodology.

    Thresholds:
        cosine > 0.85  →  DUPLICATE
        0.60 - 0.85    →  PARTIAL_GAP
        < 0.60         →  NOVEL
    """
    assessments: list[dict[str, Any]] = []

    for result in report.repo_results:
        if result.skipped or result.error:
            continue
        for finding in result.findings:
            query_text = f"{finding.title}: {finding.description[:200]}"

            # Search for similar existing methodologies
            try:
                similar = await semantic_memory.search(
                    query=query_text,
                    limit=1,
                )
            except Exception as e:
                logger.warning("Self-assess search failed for '%s': %s", finding.title[:40], e)
                assessments.append({
                    "title": finding.title,
                    "classification": "NOVEL",
                    "similarity": 0.0,
                    "closest_match": f"(search error: {e})",
                })
                continue

            if similar and len(similar) > 0:
                best = similar[0]
                # SemanticMemory.search returns Methodology objects or dicts
                if hasattr(best, "problem_description"):
                    match_title = (best.problem_description or "")[:80]
                    sim_score = getattr(best, "similarity", 0.0)
                elif isinstance(best, dict):
                    match_title = (best.get("problem_description") or best.get("title", ""))[:80]
                    sim_score = best.get("similarity", best.get("score", 0.0))
                else:
                    match_title = str(best)[:80]
                    sim_score = 0.0
            else:
                match_title = "-"
                sim_score = 0.0

            if sim_score > 0.85:
                classification = "DUPLICATE"
            elif sim_score >= 0.60:
                classification = "PARTIAL_GAP"
            else:
                classification = "NOVEL"

            assessments.append({
                "title": finding.title,
                "classification": classification,
                "similarity": sim_score,
                "closest_match": match_title,
                "source_repo": finding.source_repo,
            })

    return assessments
