"""SQLite database engine for CLAW.

Manages async connections via aiosqlite and handles schema initialization.
All queries flow through this engine; the Repository class builds on top.
WAL mode is enabled on connect for concurrent read/write performance.
busy_timeout=5000 is set at the connection level so SQLite internally
retries for up to 5 seconds before raising SQLITE_BUSY.  Application-level
retry logic (_retry_on_locked) provides a second defense layer with
exponential backoff for prolonged contention (federation, PULSE scans, etc.).
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, TypeVar

import aiosqlite
import sqlite_vec

from claw.core.config import DatabaseConfig
from claw.core.exceptions import ConnectionError, DatabaseError, SchemaInitError

logger = logging.getLogger("claw.db")

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Retry helper for SQLite write contention
# ---------------------------------------------------------------------------

async def _retry_on_locked(
    func: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 0.5,
    **kwargs: Any,
) -> Any:
    """Call *func* and retry on 'database is locked' OperationalError.

    This catches sqlite3.OperationalError (surfaced through aiosqlite) that
    contain "database is locked" and retries with exponential backoff:
        attempt 1 delay: 0.5s
        attempt 2 delay: 1.0s
        attempt 3 delay: 2.0s
    If the final attempt still fails, the exception is re-raised.

    Note: busy_timeout=5000 at the PRAGMA level is the *first* line of defense.
    This helper only fires when busy_timeout itself is exhausted -- i.e. the
    lock was held for >5 seconds continuously.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except sqlite3.OperationalError as exc:
            if "database is locked" not in str(exc):
                raise
            last_exc = exc
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "database is locked (attempt %d/%d), retrying in %.1fs",
                    attempt + 1,
                    max_retries + 1,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "database is locked after %d attempts, giving up",
                    max_retries + 1,
                )
        except Exception as exc:
            # aiosqlite may wrap sqlite3 errors -- check the cause chain
            cause = exc.__cause__ or exc
            if (
                isinstance(cause, sqlite3.OperationalError)
                and "database is locked" in str(cause)
            ):
                last_exc = exc
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "database is locked (wrapped, attempt %d/%d), retrying in %.1fs",
                        attempt + 1,
                        max_retries + 1,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "database is locked (wrapped) after %d attempts, giving up",
                        max_retries + 1,
                    )
            else:
                raise
    # All retries exhausted
    raise last_exc  # type: ignore[misc]


class DatabaseEngine:
    """SQLite engine wrapping aiosqlite.

    Usage:
        engine = DatabaseEngine(config)
        await engine.connect()
        rows = await engine.fetch_all("SELECT * FROM tasks WHERE status = ?", ["PENDING"])

        async with engine.transaction():
            await engine.execute("INSERT INTO tasks ...")
            await engine.execute("UPDATE projects ...")

    Connection pooling note:
        This engine uses a single aiosqlite connection.  aiosqlite serializes
        all operations through a dedicated background thread, so a pool of
        connections would not improve write throughput (SQLite allows only one
        writer at a time).  If read-heavy workloads become a bottleneck, consider
        opening separate read-only connections with PRAGMA query_only=ON.
    """

    def __init__(self, config: DatabaseConfig):
        self.config = config
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """Open the SQLite connection with WAL mode and dict row factory."""
        try:
            db_path = Path(self.config.db_path)
            if self.config.db_path != ":memory:":
                db_path.parent.mkdir(parents=True, exist_ok=True)

            self._conn = await aiosqlite.connect(str(db_path))
            self._conn.row_factory = aiosqlite.Row

            # Load sqlite-vec extension for vector search
            # Must run in aiosqlite's thread since sqlite3 objects are thread-bound
            def _load_vec(conn):
                conn.enable_load_extension(True)
                sqlite_vec.load(conn)
                conn.enable_load_extension(False)

            await self._conn._execute(_load_vec, self._conn._conn)

            # Enable WAL mode for concurrent reads
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA foreign_keys=ON")
            # busy_timeout: SQLite will internally retry for up to 5 seconds
            # before surfacing SQLITE_BUSY as an OperationalError.
            await self._conn.execute("PRAGMA busy_timeout=5000")

            logger.info("Connected to SQLite at %s (sqlite-vec loaded)", self.config.db_path)
        except Exception as e:
            if self._conn is not None:
                try:
                    await self._conn.close()
                except Exception:
                    pass
                self._conn = None
            raise ConnectionError(f"Failed to connect to database: {e}") from e

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise ConnectionError("Database not connected. Call connect() first.")
        return self._conn

    async def initialize_schema(self) -> None:
        """Run schema.sql to create all tables and indexes."""
        if not SCHEMA_PATH.exists():
            raise SchemaInitError(f"Schema file not found: {SCHEMA_PATH}")

        sql = SCHEMA_PATH.read_text()
        try:
            await self.conn.executescript(sql)
            await self.conn.commit()
            logger.info("Database schema initialized successfully")
        except Exception as e:
            raise SchemaInitError(f"Failed to initialize schema: {e}") from e

    async def apply_migrations(self) -> None:
        """Apply incremental schema migrations idempotently.

        Each migration checks whether the target change already exists before
        applying it, so this method is safe to call on every startup.
        Called before initialize_schema() so existing DBs get new columns
        before schema.sql tries to create indexes on them.
        """
        # Guard: skip migrations if methodologies table doesn't exist yet (fresh DB)
        row = await self.fetch_one(
            "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name='methodologies'"
        )
        tables_exist = row and row["cnt"] > 0

        if tables_exist:
            # Migration 1: add prism_data column to methodologies
            row = await self.fetch_one(
                "SELECT COUNT(*) as cnt FROM pragma_table_info('methodologies') WHERE name = 'prism_data'"
            )
            if row and row["cnt"] == 0:
                await self.conn.execute(
                    "ALTER TABLE methodologies ADD COLUMN prism_data TEXT"
                )
                await self.conn.commit()
                logger.info("Migration applied: methodologies.prism_data column added")

        # Migration 2: create governance_log table (safe even on fresh DB)
        row = await self.fetch_one(
            "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name='governance_log'"
        )
        if row and row["cnt"] == 0:
            await self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS governance_log (
                    id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    methodology_id TEXT,
                    details TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                );
                CREATE INDEX IF NOT EXISTS idx_governance_log_action ON governance_log(action_type);
                CREATE INDEX IF NOT EXISTS idx_governance_log_created ON governance_log(created_at DESC);
            """)
            await self.conn.commit()
            logger.info("Migration applied: governance_log table created")

        if tables_exist:
            # Migration 3: add capability_data column to methodologies
            row = await self.fetch_one(
                "SELECT COUNT(*) as cnt FROM pragma_table_info('methodologies') WHERE name = 'capability_data'"
            )
            if row and row["cnt"] == 0:
                await self.conn.execute(
                    "ALTER TABLE methodologies ADD COLUMN capability_data TEXT"
                )
                await self.conn.commit()
                logger.info("Migration applied: methodologies.capability_data column added")

        # Migration 4: create synergy_exploration_log table (safe even on fresh DB)
        row = await self.fetch_one(
            "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name='synergy_exploration_log'"
        )
        if row and row["cnt"] == 0:
            await self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS synergy_exploration_log (
                    id TEXT PRIMARY KEY,
                    cap_a_id TEXT NOT NULL,
                    cap_b_id TEXT NOT NULL,
                    explored_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                    result TEXT NOT NULL DEFAULT 'pending'
                        CHECK (result IN ('pending','synergy','no_match','error','stale')),
                    synergy_score REAL,
                    synergy_type TEXT,
                    edge_id TEXT,
                    exploration_method TEXT,
                    details TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(cap_a_id, cap_b_id)
                );
                CREATE INDEX IF NOT EXISTS idx_synergy_log_cap_a ON synergy_exploration_log(cap_a_id);
                CREATE INDEX IF NOT EXISTS idx_synergy_log_cap_b ON synergy_exploration_log(cap_b_id);
                CREATE INDEX IF NOT EXISTS idx_synergy_log_result ON synergy_exploration_log(result);
            """)
            await self.conn.commit()
            logger.info("Migration applied: synergy_exploration_log table created")

        if tables_exist:
            # Migration 5: add novelty_score and potential_score columns to methodologies
            row = await self.fetch_one(
                "SELECT COUNT(*) as cnt FROM pragma_table_info('methodologies') WHERE name = 'novelty_score'"
            )
            if row and row["cnt"] == 0:
                await self.conn.execute(
                    "ALTER TABLE methodologies ADD COLUMN novelty_score REAL"
                )
                await self.conn.execute(
                    "ALTER TABLE methodologies ADD COLUMN potential_score REAL"
                )
                await self.conn.executescript(
                    "CREATE INDEX IF NOT EXISTS idx_meth_novelty ON methodologies(novelty_score DESC);"
                )
                await self.conn.commit()
                logger.info("Migration applied: methodologies.novelty_score + potential_score columns added")

        if tables_exist:
            # Migration 6: add action-template fields to tasks
            tasks_exists = await self.fetch_one(
                "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name='tasks'"
            )
            if tasks_exists and tasks_exists["cnt"] > 0:
                row = await self.fetch_one(
                    "SELECT COUNT(*) as cnt FROM pragma_table_info('tasks') WHERE name = 'action_template_id'"
                )
                if row and row["cnt"] == 0:
                    await self.conn.execute(
                        "ALTER TABLE tasks ADD COLUMN action_template_id TEXT REFERENCES action_templates(id) ON DELETE SET NULL"
                    )
                    await self.conn.commit()
                    logger.info("Migration applied: tasks.action_template_id column added")

                row = await self.fetch_one(
                    "SELECT COUNT(*) as cnt FROM pragma_table_info('tasks') WHERE name = 'execution_steps'"
                )
                if row and row["cnt"] == 0:
                    await self.conn.execute(
                        "ALTER TABLE tasks ADD COLUMN execution_steps TEXT NOT NULL DEFAULT '[]'"
                    )
                    await self.conn.commit()
                    logger.info("Migration applied: tasks.execution_steps column added")

                row = await self.fetch_one(
                    "SELECT COUNT(*) as cnt FROM pragma_table_info('tasks') WHERE name = 'acceptance_checks'"
                )
                if row and row["cnt"] == 0:
                    await self.conn.execute(
                        "ALTER TABLE tasks ADD COLUMN acceptance_checks TEXT NOT NULL DEFAULT '[]'"
                    )
                    await self.conn.commit()
                    logger.info("Migration applied: tasks.acceptance_checks column added")

        # Migration 7: create action_templates table (safe even on fresh DB)
        row = await self.fetch_one(
            "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name='action_templates'"
        )
        if row and row["cnt"] == 0:
            await self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS action_templates (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    problem_pattern TEXT NOT NULL,
                    execution_steps TEXT NOT NULL DEFAULT '[]',
                    acceptance_checks TEXT NOT NULL DEFAULT '[]',
                    rollback_steps TEXT NOT NULL DEFAULT '[]',
                    preconditions TEXT NOT NULL DEFAULT '[]',
                    source_methodology_id TEXT REFERENCES methodologies(id) ON DELETE SET NULL,
                    source_repo TEXT,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                );
                CREATE INDEX IF NOT EXISTS idx_action_templates_repo ON action_templates(source_repo);
                CREATE INDEX IF NOT EXISTS idx_action_templates_confidence ON action_templates(confidence DESC);
            """)
            tasks_row = await self.fetch_one(
                "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name='tasks'"
            )
            if tasks_row and tasks_row["cnt"] > 0:
                await self.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_tasks_action_template ON tasks(action_template_id)"
                )
            await self.conn.commit()
            logger.info("Migration applied: action_templates table created")

        # Migration 8: create methodology_usage_log table
        row = await self.fetch_one(
            "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name='methodology_usage_log'"
        )
        if row and row["cnt"] == 0:
            await self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS methodology_usage_log (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    methodology_id TEXT NOT NULL REFERENCES methodologies(id) ON DELETE CASCADE,
                    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
                    stage TEXT NOT NULL DEFAULT 'retrieved_presented',
                    agent_id TEXT,
                    success INTEGER,
                    expectation_match_score REAL,
                    quality_score REAL,
                    relevance_score REAL,
                    notes TEXT,
                    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                );
                CREATE INDEX IF NOT EXISTS idx_meth_usage_task ON methodology_usage_log(task_id);
                CREATE INDEX IF NOT EXISTS idx_meth_usage_methodology ON methodology_usage_log(methodology_id);
                CREATE INDEX IF NOT EXISTS idx_meth_usage_stage ON methodology_usage_log(stage);
            """)
            await self.conn.commit()
            logger.info("Migration applied: methodology_usage_log table created")

        # Migration 9: create pulse_discoveries table (CAM-PULSE)
        row = await self.fetch_one(
            "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name='pulse_discoveries'"
        )
        if row and row["cnt"] == 0:
            await self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS pulse_discoveries (
                    id TEXT PRIMARY KEY,
                    github_url TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    x_post_url TEXT,
                    x_post_text TEXT,
                    x_author_handle TEXT,
                    discovered_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                    novelty_score REAL,
                    status TEXT NOT NULL DEFAULT 'discovered'
                        CHECK (status IN ('discovered','cloning','mounting','mining','assimilated','failed','skipped','queued_enhance','refreshing')),
                    scan_id TEXT,
                    keywords_matched TEXT NOT NULL DEFAULT '[]',
                    mine_result TEXT,
                    methodology_ids TEXT NOT NULL DEFAULT '[]',
                    error_detail TEXT,
                    UNIQUE(canonical_url)
                );
                CREATE INDEX IF NOT EXISTS idx_pulse_disc_status ON pulse_discoveries(status);
                CREATE INDEX IF NOT EXISTS idx_pulse_disc_novelty ON pulse_discoveries(novelty_score DESC);
                CREATE INDEX IF NOT EXISTS idx_pulse_disc_discovered ON pulse_discoveries(discovered_at DESC);
            """)
            await self.conn.commit()
            logger.info("Migration applied: pulse_discoveries table created")

        # Migration 10: create pulse_scan_log table (CAM-PULSE)
        row = await self.fetch_one(
            "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name='pulse_scan_log'"
        )
        if row and row["cnt"] == 0:
            await self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS pulse_scan_log (
                    id TEXT PRIMARY KEY,
                    scan_type TEXT NOT NULL DEFAULT 'x_search',
                    keywords TEXT NOT NULL DEFAULT '[]',
                    started_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                    completed_at TEXT,
                    repos_discovered INTEGER NOT NULL DEFAULT 0,
                    repos_novel INTEGER NOT NULL DEFAULT 0,
                    repos_assimilated INTEGER NOT NULL DEFAULT 0,
                    cost_usd REAL NOT NULL DEFAULT 0.0,
                    tokens_used INTEGER NOT NULL DEFAULT 0,
                    error_detail TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_pulse_scan_started ON pulse_scan_log(started_at DESC);
            """)
            await self.conn.commit()
            logger.info("Migration applied: pulse_scan_log table created")

        # Migration 11: add freshness tracking columns to pulse_discoveries
        # Uses pragma_table_info to check column existence (idempotent pattern)
        existing_cols = set()
        rows = await self.fetch_all(
            "SELECT name FROM pragma_table_info('pulse_discoveries')"
        )
        for r in rows:
            existing_cols.add(r["name"])

        freshness_columns = [
            ("last_checked_at", "TEXT"),
            ("last_pushed_at", "TEXT"),
            ("head_sha_at_mine", "TEXT"),
            ("etag", "TEXT"),
            ("stars_at_mine", "INTEGER"),
            ("latest_release_tag", "TEXT"),
            ("freshness_status", "TEXT DEFAULT 'unknown'"),
            ("source_kind", "TEXT DEFAULT 'github'"),
        ]

        added = []
        for col_name, col_type in freshness_columns:
            if col_name not in existing_cols:
                await self.conn.execute(
                    f"ALTER TABLE pulse_discoveries ADD COLUMN {col_name} {col_type}"
                )
                added.append(col_name)

        if added:
            await self.conn.commit()
            logger.info("Migration 11 applied: added freshness columns: %s", ", ".join(added))

        # Migration 12: add size_at_mine column to pulse_discoveries
        if "size_at_mine" not in existing_cols:
            # Re-check in case migration 11 just ran
            re_rows = await self.fetch_all(
                "SELECT name FROM pragma_table_info('pulse_discoveries')"
            )
            re_cols = {r["name"] for r in re_rows}
            if "size_at_mine" not in re_cols:
                await self.conn.execute(
                    "ALTER TABLE pulse_discoveries ADD COLUMN size_at_mine INTEGER"
                )
                await self.conn.commit()
                logger.info("Migration 12 applied: added size_at_mine column")

        # Migration 13: add license_type column to pulse_discoveries
        re_rows_13 = await self.fetch_all(
            "SELECT name FROM pragma_table_info('pulse_discoveries')"
        )
        pd_cols_13 = {r["name"] for r in re_rows_13}
        if "license_type" not in pd_cols_13:
            await self.conn.execute(
                "ALTER TABLE pulse_discoveries ADD COLUMN license_type TEXT"
            )
            await self.conn.commit()
            logger.info("Migration 13 applied: added license_type column")

        # Migration 14: create methodology_fitness_log table
        mfl_check = await self.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='methodology_fitness_log'"
        )
        if not mfl_check:
            await self.conn.execute("""
                CREATE TABLE IF NOT EXISTS methodology_fitness_log (
                    id TEXT PRIMARY KEY,
                    methodology_id TEXT NOT NULL REFERENCES methodologies(id) ON DELETE CASCADE,
                    fitness_total REAL NOT NULL,
                    fitness_vector TEXT NOT NULL DEFAULT '{}',
                    trigger_event TEXT NOT NULL DEFAULT 'recompute',
                    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                )
            """)
            await self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fitness_log_meth ON methodology_fitness_log(methodology_id)"
            )
            await self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fitness_log_created ON methodology_fitness_log(created_at DESC)"
            )
            await self.conn.commit()
            logger.info("Migration 14 applied: created methodology_fitness_log table")

        # Migration 15: create community sharing tables
        ci_check = await self.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='community_imports'"
        )
        if not ci_check:
            await self.conn.execute("""
                CREATE TABLE IF NOT EXISTS community_imports (
                    id TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    contributor_instance_id TEXT NOT NULL,
                    contributor_alias TEXT,
                    origin_id TEXT,
                    status TEXT DEFAULT 'quarantined'
                        CHECK (status IN ('quarantined','approved','rejected')),
                    gate_results TEXT NOT NULL DEFAULT '{}',
                    sanitized_record TEXT NOT NULL,
                    imported_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                    approved_at TEXT,
                    UNIQUE(content_hash)
                )
            """)
            await self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_community_imports_status ON community_imports(status)"
            )
            await self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_community_imports_contributor ON community_imports(contributor_instance_id)"
            )
            await self.conn.execute("""
                CREATE TABLE IF NOT EXISTS community_import_audit (
                    id TEXT PRIMARY KEY,
                    contributor_instance_id TEXT,
                    action TEXT NOT NULL,
                    gate_name TEXT,
                    detail TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                )
            """)
            await self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_community_audit_action ON community_import_audit(action)"
            )
            await self.conn.commit()
            logger.info("Migration 15 applied: created community sharing tables")

        # Migration 16: bandit outcomes table for RL method selection
        bandit_check = await self.fetch_one(
            "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name='methodology_bandit_outcomes'"
        )
        if bandit_check and bandit_check["cnt"] == 0:
            await self.conn.execute("""
                CREATE TABLE IF NOT EXISTS methodology_bandit_outcomes (
                    methodology_id TEXT NOT NULL REFERENCES methodologies(id) ON DELETE CASCADE,
                    task_type TEXT NOT NULL,
                    successes INTEGER NOT NULL DEFAULT 0,
                    failures INTEGER NOT NULL DEFAULT 0,
                    last_updated TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                    PRIMARY KEY (methodology_id, task_type)
                )
            """)
            await self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_bandit_task_type ON methodology_bandit_outcomes(task_type)"
            )
            await self.conn.commit()
            logger.info("Migration 16 applied: created methodology_bandit_outcomes table")

        # Migration 17: mining_outcomes table for RL mining model selection
        mining_out_check = await self.fetch_one(
            "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name='mining_outcomes'"
        )
        if mining_out_check and mining_out_check["cnt"] == 0:
            await self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS mining_outcomes (
                    id TEXT PRIMARY KEY,
                    model_used TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    brain TEXT NOT NULL DEFAULT 'python',
                    repo_name TEXT NOT NULL,
                    repo_size_bytes INTEGER NOT NULL DEFAULT 0,
                    prompt_tokens_estimated INTEGER NOT NULL DEFAULT 0,
                    strategy TEXT NOT NULL DEFAULT 'primary',
                    success INTEGER NOT NULL DEFAULT 0,
                    findings_count INTEGER NOT NULL DEFAULT 0,
                    tokens_used INTEGER NOT NULL DEFAULT 0,
                    duration_seconds REAL NOT NULL DEFAULT 0.0,
                    error_type TEXT,
                    error_detail TEXT,
                    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                );
                CREATE INDEX IF NOT EXISTS idx_mining_outcomes_model ON mining_outcomes(model_used);
                CREATE INDEX IF NOT EXISTS idx_mining_outcomes_strategy ON mining_outcomes(strategy);
                CREATE INDEX IF NOT EXISTS idx_mining_outcomes_brain ON mining_outcomes(brain);
                CREATE INDEX IF NOT EXISTS idx_mining_outcomes_size ON mining_outcomes(prompt_tokens_estimated);
            """)
            await self.conn.commit()
            logger.info("Migration 17 applied: created mining_outcomes table")

        # Migration 18: coverage_snapshots table for gap analysis
        cov_check = await self.fetch_one(
            "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name='coverage_snapshots'"
        )
        if cov_check and cov_check["cnt"] == 0:
            await self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS coverage_snapshots (
                    id TEXT PRIMARY KEY,
                    snapshot_data TEXT NOT NULL,
                    sparse_cells TEXT NOT NULL DEFAULT '[]',
                    total_methodologies INTEGER NOT NULL,
                    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                );
                CREATE INDEX IF NOT EXISTS idx_coverage_snapshots_created
                    ON coverage_snapshots(created_at DESC);
            """)
            await self.conn.commit()
            logger.info("Migration 18 applied: created coverage_snapshots table")

        # Migration 19: create methodology_contradictions table
        mc_check = await self.fetch_one(
            "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name='methodology_contradictions'"
        )
        if mc_check and mc_check["cnt"] == 0:
            await self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS methodology_contradictions (
                    id TEXT PRIMARY KEY,
                    methodology_a_id TEXT NOT NULL REFERENCES methodologies(id) ON DELETE CASCADE,
                    methodology_b_id TEXT NOT NULL REFERENCES methodologies(id) ON DELETE CASCADE,
                    problem_similarity REAL NOT NULL,
                    solution_divergence REAL NOT NULL,
                    detected_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                    resolution TEXT,
                    resolved_by TEXT,
                    resolved_at TEXT,
                    UNIQUE(methodology_a_id, methodology_b_id)
                );
                CREATE INDEX IF NOT EXISTS idx_contradictions_a ON methodology_contradictions(methodology_a_id);
                CREATE INDEX IF NOT EXISTS idx_contradictions_b ON methodology_contradictions(methodology_b_id);
            """)
            await self.conn.commit()
            logger.info("Migration 19 applied: created methodology_contradictions table")

        # Migration 20: add accuracy_contract, concept_type, use_immediately_as,
        # tension_questions, triage_score columns to methodologies (pseudo-RAG operational cards)
        if tables_exist:
            row = await self.fetch_one(
                "SELECT COUNT(*) as cnt FROM pragma_table_info('methodologies') WHERE name = 'accuracy_contract'"
            )
            if row and row["cnt"] == 0:
                await self.conn.execute(
                    "ALTER TABLE methodologies ADD COLUMN accuracy_contract TEXT NOT NULL DEFAULT 'soft'"
                )
                await self.conn.execute(
                    "ALTER TABLE methodologies ADD COLUMN concept_type TEXT"
                )
                await self.conn.execute(
                    "ALTER TABLE methodologies ADD COLUMN use_immediately_as TEXT NOT NULL DEFAULT '[]'"
                )
                await self.conn.execute(
                    "ALTER TABLE methodologies ADD COLUMN tension_questions TEXT NOT NULL DEFAULT '[]'"
                )
                await self.conn.execute(
                    "ALTER TABLE methodologies ADD COLUMN triage_score REAL"
                )
                await self.conn.commit()
                logger.info("Migration 20 applied: methodologies pseudo-RAG columns (accuracy_contract, concept_type, use_immediately_as, tension_questions, triage_score)")

    # ------------------------------------------------------------------
    # Write operations — wrapped with _retry_on_locked for contention
    # ------------------------------------------------------------------

    async def execute(
        self, query: str, params: Optional[Sequence[Any]] = None
    ) -> None:
        """Execute a query without returning results.

        Retries up to 3 times with exponential backoff if the database is
        locked beyond the 5-second busy_timeout window.
        """
        async def _do() -> None:
            await self.conn.execute(query, params or [])
            await self.conn.commit()

        try:
            await _retry_on_locked(_do)
        except (sqlite3.OperationalError, DatabaseError):
            raise
        except Exception as e:
            raise DatabaseError(f"Query failed: {e}") from e

    async def execute_returning_lastrowid(
        self, query: str, params: Optional[Sequence[Any]] = None
    ) -> int:
        """Execute an INSERT and return lastrowid.

        Retries up to 3 times with exponential backoff if the database is
        locked beyond the 5-second busy_timeout window.
        """
        async def _do() -> int:
            cursor = await self.conn.execute(query, params or [])
            await self.conn.commit()
            return cursor.lastrowid or 0

        try:
            return await _retry_on_locked(_do)
        except (sqlite3.OperationalError, DatabaseError):
            raise
        except Exception as e:
            raise DatabaseError(f"Query failed: {e}") from e

    # ------------------------------------------------------------------
    # Read operations — no retry needed (WAL allows concurrent readers)
    # ------------------------------------------------------------------

    async def fetch_one(
        self, query: str, params: Optional[Sequence[Any]] = None
    ) -> Optional[dict[str, Any]]:
        """Execute a query and return the first row as a dict, or None."""
        try:
            cursor = await self.conn.execute(query, params or [])
            row = await cursor.fetchone()
            if row is None:
                return None
            return dict(row)
        except Exception as e:
            raise DatabaseError(f"Query failed: {e}") from e

    async def fetch_all(
        self, query: str, params: Optional[Sequence[Any]] = None
    ) -> list[dict[str, Any]]:
        """Execute a query and return all rows as dicts."""
        try:
            cursor = await self.conn.execute(query, params or [])
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            raise DatabaseError(f"Query failed: {e}") from e

    # ------------------------------------------------------------------
    # Transaction context manager
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def transaction(self):
        """Context manager for explicit transactions.

        The BEGIN and COMMIT are retried if the database is locked. If lock
        contention occurs *during* the transaction body (between BEGIN and
        COMMIT), individual execute() calls inside the block handle their own
        retries.  If COMMIT itself fails after retries, the transaction is
        rolled back and the exception propagates.
        """
        await _retry_on_locked(self.conn.execute, "BEGIN")
        try:
            yield self
            await _retry_on_locked(self.conn.commit)
        except Exception:
            await self.conn.rollback()
            raise

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("Database connection closed")
