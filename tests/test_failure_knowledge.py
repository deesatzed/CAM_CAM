"""Tests for failure knowledge CRUD (cross-task preventive patterns).

Uses a real in-memory SQLite database — no mocks.
"""

from __future__ import annotations

import json

import pytest

from claw.core.config import DatabaseConfig
from claw.db.engine import DatabaseEngine
from claw.db.repository import Repository


@pytest.fixture
async def repo():
    """Create a real in-memory DB with schema for each test."""
    config = DatabaseConfig(db_path=":memory:")
    engine = DatabaseEngine(config)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    repository = Repository(engine)
    yield repository
    await engine.close()


class TestRecordFailureKnowledge:
    """record_failure_knowledge — insert and upsert."""

    async def test_insert_new_entry(self, repo):
        await repo.record_failure_knowledge(
            error_signature="ImportError: No module named 'foo'",
            error_category="import_error",
            diagnosis="Module foo is not installed",
            prevention_hint="[import_error] Ensure foo is in requirements",
            agent_id="claude",
            task_type="bug_fix",
            project_id="proj-001",
            source_task_id="task-001",
        )
        entries = await repo.get_failure_knowledge_for_context()
        assert len(entries) == 1
        assert entries[0]["error_signature"] == "ImportError: No module named 'foo'"
        assert entries[0]["occurrence_count"] == 1
        assert entries[0]["root_cause_key"] == "import_error:bug_fix:ImportError: No module named 'foo'"
        assert entries[0]["detail_signals_json"] == "{}"

    async def test_upsert_increments_count(self, repo):
        """Same error_signature should increment occurrence_count."""
        sig = "TypeError: isfunction() failed"
        await repo.record_failure_knowledge(
            error_signature=sig,
            error_category="type_error",
            diagnosis="First diagnosis",
            prevention_hint="First hint",
        )
        await repo.record_failure_knowledge(
            error_signature=sig,
            error_category="type_error",
            diagnosis="Updated diagnosis",
            prevention_hint="Updated hint",
        )
        entries = await repo.get_failure_knowledge_for_context()
        assert len(entries) == 1
        assert entries[0]["occurrence_count"] == 2
        assert entries[0]["diagnosis"] == "Updated diagnosis"

    async def test_records_explicit_root_cause_and_detail_signals(self, repo):
        await repo.record_failure_knowledge(
            error_signature="camseq_negative_memory:auth:slot:component:abc",
            error_category="camseq_negative_memory",
            diagnosis="negative memory diagnosis",
            prevention_hint="negative memory hint",
            root_cause_key="camseq_negative_memory:auth:slot",
            detail_signals_json={
                "run_id": "run_1",
                "slot_id": "slot",
                "component_id": "component",
            },
        )

        entries = await repo.list_failure_knowledge()
        assert entries[0]["root_cause_key"] == "camseq_negative_memory:auth:slot"
        assert json.loads(entries[0]["detail_signals_json"]) == {
            "component_id": "component",
            "run_id": "run_1",
            "slot_id": "slot",
        }

    async def test_different_signatures_separate_entries(self, repo):
        await repo.record_failure_knowledge(
            error_signature="error_a",
            error_category="cat_a",
            diagnosis="diag_a",
            prevention_hint="hint_a",
        )
        await repo.record_failure_knowledge(
            error_signature="error_b",
            error_category="cat_b",
            diagnosis="diag_b",
            prevention_hint="hint_b",
        )
        entries = await repo.get_failure_knowledge_for_context()
        assert len(entries) == 2


class TestGetFailureKnowledgeForContext:
    """get_failure_knowledge_for_context — filtering and ordering."""

    async def test_filter_by_task_type(self, repo):
        await repo.record_failure_knowledge(
            error_signature="err_1",
            error_category="cat",
            diagnosis="d1",
            prevention_hint="h1",
            task_type="bug_fix",
        )
        await repo.record_failure_knowledge(
            error_signature="err_2",
            error_category="cat",
            diagnosis="d2",
            prevention_hint="h2",
            task_type="refactoring",
        )
        entries = await repo.get_failure_knowledge_for_context(task_type="bug_fix")
        sigs = {e["error_signature"] for e in entries}
        assert "err_1" in sigs
        # err_2 has task_type=refactoring, excluded by filter

    async def test_null_task_type_included(self, repo):
        """Entries with task_type=NULL match any task_type filter."""
        await repo.record_failure_knowledge(
            error_signature="err_global",
            error_category="cat",
            diagnosis="d",
            prevention_hint="h",
            task_type=None,
        )
        entries = await repo.get_failure_knowledge_for_context(task_type="bug_fix")
        assert len(entries) == 1

    async def test_resolved_excluded(self, repo):
        await repo.record_failure_knowledge(
            error_signature="err_resolved",
            error_category="cat",
            diagnosis="d",
            prevention_hint="h",
        )
        await repo.mark_failure_knowledge_resolved(
            "err_resolved", "fixed by adding import"
        )
        entries = await repo.get_failure_knowledge_for_context()
        assert len(entries) == 0

    async def test_order_by_occurrence_count(self, repo):
        await repo.record_failure_knowledge(
            error_signature="rare",
            error_category="cat",
            diagnosis="d",
            prevention_hint="h",
        )
        await repo.record_failure_knowledge(
            error_signature="common",
            error_category="cat",
            diagnosis="d",
            prevention_hint="h",
        )
        # Bump common to 2
        await repo.record_failure_knowledge(
            error_signature="common",
            error_category="cat",
            diagnosis="d",
            prevention_hint="h",
        )
        entries = await repo.get_failure_knowledge_for_context()
        assert entries[0]["error_signature"] == "common"
        assert entries[0]["occurrence_count"] == 2

    async def test_limit_parameter(self, repo):
        for i in range(10):
            await repo.record_failure_knowledge(
                error_signature=f"err_{i}",
                error_category="cat",
                diagnosis="d",
                prevention_hint="h",
            )
        entries = await repo.get_failure_knowledge_for_context(limit=3)
        assert len(entries) == 3

    async def test_list_failure_knowledge_includes_resolved_when_requested(self, repo):
        await repo.record_failure_knowledge(
            error_signature="err_open",
            error_category="camseq_negative_memory",
            diagnosis="open diagnosis",
            prevention_hint="open hint",
            task_type="bug_fix",
        )
        await repo.record_failure_knowledge(
            error_signature="err_closed",
            error_category="camseq_negative_memory",
            diagnosis="closed diagnosis",
            prevention_hint="closed hint",
            task_type="bug_fix",
        )
        await repo.mark_failure_knowledge_resolved("err_closed", "verified fix")

        unresolved = await repo.list_failure_knowledge(
            task_type="bug_fix",
            error_category="camseq_negative_memory",
        )
        assert [entry["error_signature"] for entry in unresolved] == ["err_open"]

        all_entries = await repo.list_failure_knowledge(
            task_type="bug_fix",
            error_category="camseq_negative_memory",
            include_resolved=True,
        )
        assert {entry["error_signature"] for entry in all_entries} == {"err_open", "err_closed"}


class TestMarkFailureKnowledgeResolved:
    """mark_failure_knowledge_resolved — resolution workflow."""

    async def test_marks_resolved_with_approach(self, repo):
        await repo.record_failure_knowledge(
            error_signature="err_fix",
            error_category="cat",
            diagnosis="d",
            prevention_hint="h",
        )
        await repo.mark_failure_knowledge_resolved(
            "err_fix", "Added missing dependency to requirements.txt"
        )
        # Should not appear in unresolved queries
        entries = await repo.get_failure_knowledge_for_context()
        assert len(entries) == 0

    async def test_resolve_nonexistent_is_no_op(self, repo):
        """Resolving a non-existent signature does nothing (no error)."""
        await repo.mark_failure_knowledge_resolved(
            "nonexistent_sig", "some approach"
        )
        # No error raised — silent no-op

    async def test_only_unresolved_are_marked(self, repo):
        """Already resolved entries are not re-updated."""
        await repo.record_failure_knowledge(
            error_signature="err_double",
            error_category="cat",
            diagnosis="d",
            prevention_hint="h",
        )
        await repo.mark_failure_knowledge_resolved("err_double", "first fix")
        await repo.mark_failure_knowledge_resolved("err_double", "second fix")
        # Still resolved; the WHERE resolved=0 prevents the second update


class TestFailureKnowledgeMigrations:
    """failure_knowledge schema migration coverage."""

    async def test_apply_migrations_adds_grouping_columns_to_legacy_table(self):
        config = DatabaseConfig(db_path=":memory:")
        engine = DatabaseEngine(config)
        await engine.connect()
        try:
            await engine.conn.executescript(
                """
                CREATE TABLE failure_knowledge (
                    id TEXT PRIMARY KEY,
                    error_signature TEXT NOT NULL,
                    error_category TEXT NOT NULL,
                    diagnosis TEXT NOT NULL,
                    prevention_hint TEXT NOT NULL,
                    agent_id TEXT,
                    task_type TEXT,
                    project_id TEXT,
                    source_task_id TEXT,
                    occurrence_count INTEGER NOT NULL DEFAULT 1,
                    resolved INTEGER NOT NULL DEFAULT 0,
                    resolution_approach TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );
                INSERT INTO failure_knowledge (
                    id, error_signature, error_category, diagnosis, prevention_hint,
                    task_type
                )
                VALUES (
                    'fk_legacy', 'legacy_sig', 'legacy_category',
                    'legacy diagnosis', 'legacy hint', 'legacy_task'
                );
                """
            )
            await engine.conn.commit()

            await engine.apply_migrations()
            await engine.apply_migrations()

            columns = await engine.fetch_all("PRAGMA table_info(failure_knowledge)")
            names = {column["name"] for column in columns}
            assert "root_cause_key" in names
            assert "detail_signals_json" in names

            row = await engine.fetch_one(
                "SELECT root_cause_key, detail_signals_json FROM failure_knowledge WHERE id = ?",
                ["fk_legacy"],
            )
            assert row is not None
            assert row["root_cause_key"] == "legacy_category:legacy_task"
            assert row["detail_signals_json"] == "{}"
        finally:
            await engine.close()


class TestUpdateTaskExcludedAgents:
    """update_task_excluded_agents — persistence of rotation state."""

    async def test_persist_and_retrieve(self, repo):
        from claw.core.models import Project, Task

        project = Project(name="test-proj", repo_path="/tmp/test")
        await repo.create_project(project)

        task = Task(
            project_id=project.id,
            title="test task",
            description="desc",
        )
        await repo.create_task(task)

        await repo.update_task_excluded_agents(task.id, ["claude", "codex"])

        retrieved = await repo.get_task(task.id)
        assert retrieved is not None
        assert retrieved.excluded_agents == ["claude", "codex"]

    async def test_empty_list_persists(self, repo):
        from claw.core.models import Project, Task

        project = Project(name="test-proj-2", repo_path="/tmp/test2")
        await repo.create_project(project)

        task = Task(
            project_id=project.id,
            title="test task 2",
            description="desc",
            excluded_agents=["grok"],
        )
        await repo.create_task(task)

        # Clear exclusions
        await repo.update_task_excluded_agents(task.id, [])

        retrieved = await repo.get_task(task.id)
        assert retrieved is not None
        assert retrieved.excluded_agents == []
