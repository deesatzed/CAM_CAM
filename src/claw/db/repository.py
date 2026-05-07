"""Data access layer for CLAW.

All SQL queries live here. Agents never write raw SQL — they call Repository
methods that return Pydantic models. This keeps the SQL in one place and
makes the dual-backend (sqlite-vec + FTS5) transparent.
"""

from __future__ import annotations

import json
import re
import struct
import uuid
from datetime import UTC, datetime
from typing import Any, Optional

from claw.core.models import (
    ActionTemplate,
    ApplicationPacket,
    ApplicationPacketSummary,
    CompiledRecipe,
    ComponentCard,
    ComponentCardSummary,
    ComponentFit,
    ComponentLineage,
    ContextSnapshot,
    GovernancePolicy,
    HypothesisEntry,
    HypothesisOutcome,
    LandingEvent,
    Methodology,
    MethodologyUsageEntry,
    MiningMission,
    OutcomeEvent,
    PairEvent,
    PeerReview,
    Project,
    Receipt,
    RunActionAudit,
    RunConnectome,
    RunEvent,
    RunSlotExecution,
    SynergyExploration,
    Task,
    TaskPlanRecord,
    TaskStatus,
    TokenCostRecord,
    SlotSpec,
)
from claw.db.engine import DatabaseEngine


def _build_safe_fts5_query(query: str) -> str:
    """Convert free-form text into a safe FTS5 MATCH query.

    SQLite FTS treats `token:` as a column-qualified search, which breaks on
    natural-language strings like `Creation mode: new`. We sanitise tokens and
    join with OR so that any keyword match surfaces results (AND was too
    restrictive for multi-token queries and returned zero hits)."""

    tokens = re.findall(r"[A-Za-z0-9_]+", query.lower())
    if not tokens:
        return ""
    return " OR ".join(f'"{token}"' for token in tokens)


def _json_dumps(value: Any) -> str:
    return json.dumps(value)


def _json_loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _failure_root_cause_key(
    error_signature: str,
    error_category: str,
    task_type: str | None = None,
) -> str:
    """Build a stable, compact grouping key for related failure records."""
    category = (error_category or "unknown").strip() or "unknown"
    task = (task_type or "global").strip() or "global"
    signature = (error_signature or "").strip()
    if not signature:
        return f"{category}:{task}"

    parts = [part for part in signature.split(":") if part]
    if category == "camseq_negative_memory" and len(parts) >= 3:
        return ":".join(parts[:3])
    if len(parts) >= 2:
        return f"{category}:{task}:{parts[0]}:{parts[1]}"
    return f"{category}:{task}:{signature[:80]}"


def _json_object(value: dict[str, Any] | str | None) -> str:
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value.strip() or "{}"
    return json.dumps(value, sort_keys=True)


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


class Repository:
    """Async data access layer wrapping DatabaseEngine with typed methods."""

    def __init__(self, engine: DatabaseEngine):
        self.engine = engine

    # -------------------------------------------------------------------
    # Serial evolution
    # -------------------------------------------------------------------

    async def create_evolution_instance(self, instance: dict[str, Any]) -> dict[str, Any]:
        """Create a champion/challenger/archive lineage record."""
        instance_id = instance.get("id") or str(uuid.uuid4())
        await self.engine.execute(
            """INSERT INTO evolution_instances
               (id, parent_instance_id, role, version_label, repo_path, db_path,
                git_ref, config_hash, code_hash, knowledge_hash, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                instance_id,
                instance.get("parent_instance_id"),
                instance["role"],
                instance["version_label"],
                instance["repo_path"],
                instance.get("db_path"),
                instance.get("git_ref"),
                instance.get("config_hash"),
                instance.get("code_hash"),
                instance.get("knowledge_hash"),
                instance.get("notes"),
            ],
        )
        row = await self.get_evolution_instance(instance_id)
        return row or {**instance, "id": instance_id}

    async def get_evolution_instance(self, instance_id: str) -> Optional[dict[str, Any]]:
        return await self.engine.fetch_one(
            "SELECT * FROM evolution_instances WHERE id = ?",
            [instance_id],
        )

    async def get_current_evolution_champion(self) -> Optional[dict[str, Any]]:
        return await self.engine.fetch_one(
            """SELECT * FROM evolution_instances
               WHERE role = 'champion'
               ORDER BY created_at DESC
               LIMIT 1"""
        )

    async def list_evolution_instances(
        self,
        role: Optional[str] = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        if role:
            return await self.engine.fetch_all(
                """SELECT * FROM evolution_instances
                   WHERE role = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                [role, limit],
            )
        return await self.engine.fetch_all(
            """SELECT * FROM evolution_instances
               ORDER BY created_at DESC
               LIMIT ?""",
            [limit],
        )

    async def update_evolution_instance_role(
        self,
        instance_id: str,
        role: str,
        notes: Optional[str] = None,
    ) -> None:
        archived_at_expr = (
            "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
            if role in {"archived", "rejected"}
            else "NULL"
        )
        await self.engine.execute(
            f"""UPDATE evolution_instances
                SET role = ?, notes = COALESCE(?, notes), archived_at = {archived_at_expr}
                WHERE id = ?""",
            [role, notes, instance_id],
        )

    async def create_evolution_run(self, run: dict[str, Any]) -> dict[str, Any]:
        run_id = run.get("id") or str(uuid.uuid4())
        await self.engine.execute(
            """INSERT INTO evolution_runs
               (id, champion_instance_id, challenger_instance_id, cycle_number,
                layer, status, objective, selected_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                run_id,
                run["champion_instance_id"],
                run.get("challenger_instance_id"),
                run["cycle_number"],
                run["layer"],
                run.get("status", "planned"),
                run["objective"],
                run.get("selected_by", "rotation"),
            ],
        )
        row = await self.get_evolution_run(run_id)
        return row or {**run, "id": run_id}

    async def get_evolution_run(self, run_id: str) -> Optional[dict[str, Any]]:
        return await self.engine.fetch_one(
            "SELECT * FROM evolution_runs WHERE id = ?",
            [run_id],
        )

    async def get_active_evolution_run(self) -> Optional[dict[str, Any]]:
        return await self.engine.fetch_one(
            """SELECT * FROM evolution_runs
               WHERE status IN ('planned','mining','mutating','training','evaluating','paused')
               ORDER BY started_at DESC
               LIMIT 1"""
        )

    async def get_latest_evolution_run(self) -> Optional[dict[str, Any]]:
        return await self.engine.fetch_one(
            """SELECT * FROM evolution_runs
               ORDER BY cycle_number DESC, started_at DESC
               LIMIT 1"""
        )

    async def list_evolution_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self.engine.fetch_all(
            """SELECT * FROM evolution_runs
               ORDER BY cycle_number DESC, started_at DESC
               LIMIT ?""",
            [limit],
        )

    async def update_evolution_run_status(
        self,
        run_id: str,
        status: str,
        failure_reason: Optional[str] = None,
    ) -> None:
        completed_statuses = {"promoted", "rejected", "failed", "paused"}
        completed_expr = (
            "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
            if status in completed_statuses
            else "completed_at"
        )
        await self.engine.execute(
            f"""UPDATE evolution_runs
                SET status = ?, failure_reason = COALESCE(?, failure_reason),
                    completed_at = {completed_expr}
                WHERE id = ?""",
            [status, failure_reason, run_id],
        )

    async def attach_evolution_challenger(self, run_id: str, challenger_instance_id: str) -> None:
        await self.engine.execute(
            "UPDATE evolution_runs SET challenger_instance_id = ? WHERE id = ?",
            [challenger_instance_id, run_id],
        )

    async def record_evolution_mined_input(self, item: dict[str, Any]) -> dict[str, Any]:
        item_id = item.get("id") or str(uuid.uuid4())
        payload = item.get("extracted_payload", {})
        await self.engine.execute(
            """INSERT INTO evolution_mined_inputs
               (id, run_id, source_type, source_uri, source_ref, license_type,
                novelty_score, relevance_score, accepted, rejection_reason, extracted_payload)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                item_id,
                item["run_id"],
                item["source_type"],
                item["source_uri"],
                item.get("source_ref"),
                item.get("license_type"),
                item.get("novelty_score"),
                item.get("relevance_score"),
                1 if item.get("accepted") else 0,
                item.get("rejection_reason"),
                _json_dumps(payload),
            ],
        )
        row = await self.engine.fetch_one(
            "SELECT * FROM evolution_mined_inputs WHERE id = ?",
            [item_id],
        )
        return row or {**item, "id": item_id}

    async def list_evolution_mined_inputs(self, run_id: str) -> list[dict[str, Any]]:
        return await self.engine.fetch_all(
            """SELECT * FROM evolution_mined_inputs
               WHERE run_id = ?
               ORDER BY created_at ASC""",
            [run_id],
        )

    async def record_evolution_mutation(self, mutation: dict[str, Any]) -> dict[str, Any]:
        mutation_id = mutation.get("id") or str(uuid.uuid4())
        await self.engine.execute(
            """INSERT INTO evolution_mutations
               (id, run_id, layer, mutation_type, target_ref, before_hash, after_hash,
                mutation_manifest, rollback_manifest)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                mutation_id,
                mutation["run_id"],
                mutation["layer"],
                mutation["mutation_type"],
                mutation["target_ref"],
                mutation.get("before_hash"),
                mutation.get("after_hash"),
                _json_dumps(mutation.get("mutation_manifest", {})),
                _json_dumps(mutation.get("rollback_manifest", {})),
            ],
        )
        row = await self.engine.fetch_one(
            "SELECT * FROM evolution_mutations WHERE id = ?",
            [mutation_id],
        )
        return row or {**mutation, "id": mutation_id}

    async def list_evolution_mutations(self, run_id: str) -> list[dict[str, Any]]:
        return await self.engine.fetch_all(
            """SELECT * FROM evolution_mutations
               WHERE run_id = ?
               ORDER BY created_at ASC""",
            [run_id],
        )

    async def record_evolution_evaluation(self, evaluation: dict[str, Any]) -> dict[str, Any]:
        evaluation_id = evaluation.get("id") or str(uuid.uuid4())
        await self.engine.execute(
            """INSERT INTO evolution_evaluations
               (id, run_id, eval_slice, champion_score, challenger_score,
                delta_score, p_value, effect_size, bootstrap_ci_low,
                bootstrap_ci_high, passed, metrics_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                evaluation_id,
                evaluation["run_id"],
                evaluation["eval_slice"],
                evaluation["champion_score"],
                evaluation["challenger_score"],
                evaluation["delta_score"],
                evaluation.get("p_value"),
                evaluation.get("effect_size"),
                evaluation.get("bootstrap_ci_low"),
                evaluation.get("bootstrap_ci_high"),
                1 if evaluation.get("passed") else 0,
                _json_dumps(evaluation.get("metrics", evaluation.get("metrics_json", {}))),
            ],
        )
        row = await self.engine.fetch_one(
            "SELECT * FROM evolution_evaluations WHERE id = ?",
            [evaluation_id],
        )
        return row or {**evaluation, "id": evaluation_id}

    async def list_evolution_evaluations(self, run_id: str) -> list[dict[str, Any]]:
        return await self.engine.fetch_all(
            """SELECT * FROM evolution_evaluations
               WHERE run_id = ?
               ORDER BY created_at ASC""",
            [run_id],
        )

    async def record_evolution_decision(self, decision: dict[str, Any]) -> dict[str, Any]:
        decision_id = decision.get("id") or str(uuid.uuid4())
        await self.engine.execute(
            """INSERT INTO evolution_decisions
               (id, run_id, decision, decided_by, reason, gate_report,
                promoted_instance_id, rollback_instance_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                decision_id,
                decision["run_id"],
                decision["decision"],
                decision.get("decided_by", "promotion_gate"),
                decision["reason"],
                _json_dumps(decision.get("gate_report", {})),
                decision.get("promoted_instance_id"),
                decision.get("rollback_instance_id"),
            ],
        )
        row = await self.engine.fetch_one(
            "SELECT * FROM evolution_decisions WHERE id = ?",
            [decision_id],
        )
        return row or {**decision, "id": decision_id}

    async def list_evolution_decisions(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self.engine.fetch_all(
            """SELECT * FROM evolution_decisions
               ORDER BY created_at DESC
               LIMIT ?""",
            [limit],
        )

    async def record_evolution_monitor_event(self, event: dict[str, Any]) -> dict[str, Any]:
        event_id = event.get("id") or str(uuid.uuid4())
        await self.engine.execute(
            """INSERT INTO evolution_monitor_events
               (id, run_id, instance_id, severity, event_type, message, payload)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                event_id,
                event.get("run_id"),
                event.get("instance_id"),
                event["severity"],
                event["event_type"],
                event["message"],
                _json_dumps(event.get("payload", {})),
            ],
        )
        row = await self.engine.fetch_one(
            "SELECT * FROM evolution_monitor_events WHERE id = ?",
            [event_id],
        )
        return row or {**event, "id": event_id}

    # -------------------------------------------------------------------
    # Projects
    # -------------------------------------------------------------------

    async def create_project(self, project: Project) -> Project:
        await self.engine.execute(
            """INSERT INTO projects (id, name, repo_path, tech_stack, project_rules, banned_dependencies)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                project.id,
                project.name,
                project.repo_path,
                json.dumps(project.tech_stack),
                project.project_rules,
                json.dumps(project.banned_dependencies),
            ],
        )
        return project

    async def get_project(self, project_id: str) -> Optional[Project]:
        row = await self.engine.fetch_one(
            "SELECT * FROM projects WHERE id = ?", [project_id]
        )
        if row is None:
            return None
        return _row_to_project(row)

    async def list_projects(self) -> list[Project]:
        """List all projects, most recent first."""
        rows = await self.engine.fetch_all(
            "SELECT * FROM projects ORDER BY created_at DESC"
        )
        return [_row_to_project(r) for r in rows]

    async def get_project_by_name(self, name: str) -> Optional[Project]:
        """Get a project by its name."""
        row = await self.engine.fetch_one(
            "SELECT * FROM projects WHERE name = ? LIMIT 1", [name]
        )
        if row is None:
            return None
        return _row_to_project(row)

    async def get_project_by_repo_path(self, repo_path: str) -> Optional[Project]:
        """Get a project by its repo_path.

        Used by CLI commands (evaluate, enhance) to reuse an existing
        project row instead of creating a duplicate when the same
        repository is processed more than once.
        """
        row = await self.engine.fetch_one(
            "SELECT * FROM projects WHERE repo_path = ? ORDER BY created_at ASC LIMIT 1",
            [repo_path],
        )
        if row is None:
            return None
        return _row_to_project(row)

    # -------------------------------------------------------------------
    # Tasks
    # -------------------------------------------------------------------

    async def create_task(self, task: Task) -> Task:
        await self.engine.execute(
            """INSERT INTO tasks (id, project_id, title, description, status, priority,
               task_type, recommended_agent, assigned_agent, action_template_id,
               execution_steps, acceptance_checks, excluded_agents)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                task.id,
                task.project_id,
                task.title,
                task.description,
                task.status.value,
                task.priority,
                task.task_type,
                task.recommended_agent,
                task.assigned_agent,
                task.action_template_id,
                json.dumps(task.execution_steps),
                json.dumps(task.acceptance_checks),
                json.dumps(task.excluded_agents),
            ],
        )
        return task

    async def get_next_task(self, project_id: str) -> Optional[Task]:
        """Get the highest-priority PENDING task for a project."""
        row = await self.engine.fetch_one(
            """SELECT * FROM tasks
               WHERE project_id = ? AND status = 'PENDING'
               ORDER BY priority DESC, created_at ASC
               LIMIT 1""",
            [project_id],
        )
        if row is None:
            return None
        return _row_to_task(row)

    async def get_task(self, task_id: str) -> Optional[Task]:
        row = await self.engine.fetch_one("SELECT * FROM tasks WHERE id = ?", [task_id])
        if row is None:
            return None
        return _row_to_task(row)

    async def update_task_status(self, task_id: str, status: TaskStatus) -> None:
        now = datetime.now(UTC).isoformat()
        completed_at = now if status == TaskStatus.DONE else None
        await self.engine.execute(
            "UPDATE tasks SET status = ?, updated_at = ?, completed_at = ? WHERE id = ?",
            [status.value, now, completed_at, task_id],
        )

    async def update_task_agent(self, task_id: str, agent_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        await self.engine.execute(
            "UPDATE tasks SET assigned_agent = ?, updated_at = ? WHERE id = ?",
            [agent_id, now, task_id],
        )

    async def increment_task_attempt(self, task_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        await self.engine.execute(
            "UPDATE tasks SET attempt_count = attempt_count + 1, updated_at = ? WHERE id = ?",
            [now, task_id],
        )

    async def increment_task_escalation(self, task_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        await self.engine.execute(
            "UPDATE tasks SET escalation_count = escalation_count + 1, updated_at = ? WHERE id = ?",
            [now, task_id],
        )

    async def update_task_excluded_agents(self, task_id: str, excluded: list[str]) -> None:
        """Persist excluded_agents list for a task (agent rotation bookkeeping)."""
        now = datetime.now(UTC).isoformat()
        await self.engine.execute(
            "UPDATE tasks SET excluded_agents = ?, updated_at = ? WHERE id = ?",
            [json.dumps(excluded), now, task_id],
        )

    # ------------------------------------------------------------------
    # Failure Knowledge — cross-task preventive patterns
    # ------------------------------------------------------------------

    async def record_failure_knowledge(
        self,
        error_signature: str,
        error_category: str,
        diagnosis: str,
        prevention_hint: str,
        agent_id: str | None = None,
        task_type: str | None = None,
        project_id: str | None = None,
        source_task_id: str | None = None,
        root_cause_key: str | None = None,
        detail_signals_json: dict[str, Any] | str | None = None,
    ) -> None:
        """Upsert a failure knowledge entry.

        If an entry with the same error_signature already exists, increment
        occurrence_count and update diagnosis/prevention_hint. Otherwise insert.
        """
        existing = await self.engine.fetch_one(
            """SELECT id, occurrence_count, root_cause_key, detail_signals_json
               FROM failure_knowledge WHERE error_signature = ?""",
            [error_signature],
        )
        root_key = root_cause_key or _failure_root_cause_key(
            error_signature, error_category, task_type,
        )
        detail_signals = _json_object(detail_signals_json)
        now = datetime.now(UTC).isoformat()
        if existing:
            if not root_cause_key and existing["root_cause_key"]:
                root_key = existing["root_cause_key"]
            if detail_signals_json is None and existing["detail_signals_json"]:
                detail_signals = existing["detail_signals_json"]
            await self.engine.execute(
                """UPDATE failure_knowledge
                   SET occurrence_count = occurrence_count + 1,
                       diagnosis = ?,
                       prevention_hint = ?,
                       root_cause_key = ?,
                       detail_signals_json = ?,
                       updated_at = ?
                   WHERE id = ?""",
                [
                    diagnosis,
                    prevention_hint,
                    root_key,
                    detail_signals,
                    now,
                    existing["id"],
                ],
            )
        else:
            import uuid as _uuid
            fk_id = str(_uuid.uuid4())
            await self.engine.execute(
                """INSERT INTO failure_knowledge
                   (id, error_signature, error_category, diagnosis, prevention_hint,
                    agent_id, task_type, project_id, source_task_id, root_cause_key,
                    detail_signals_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    fk_id,
                    error_signature,
                    error_category,
                    diagnosis,
                    prevention_hint,
                    agent_id,
                    task_type,
                    project_id,
                    source_task_id,
                    root_key,
                    detail_signals,
                ],
            )

    async def get_failure_knowledge_for_context(
        self,
        task_type: str | None = None,
        project_id: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Retrieve unresolved failure knowledge entries for enrichment.

        Filters by task_type and/or project_id if provided. Returns the most
        frequently occurring patterns first.
        """
        conditions = ["resolved = 0"]
        params: list = []
        if task_type:
            conditions.append("(task_type = ? OR task_type IS NULL)")
            params.append(task_type)
        if project_id:
            conditions.append("(project_id = ? OR project_id IS NULL)")
            params.append(project_id)
        where_clause = " AND ".join(conditions)
        params.append(limit)
        rows = await self.engine.fetch_all(
            f"SELECT * FROM failure_knowledge WHERE {where_clause} ORDER BY occurrence_count DESC LIMIT ?",
            params,
        )
        return rows

    async def list_failure_knowledge(
        self,
        *,
        task_type: str | None = None,
        project_id: str | None = None,
        error_category: str | None = None,
        include_resolved: bool = False,
        limit: int = 50,
    ) -> list[dict]:
        """List failure knowledge entries for review and operator resolution."""
        conditions: list[str] = []
        params: list = []
        if not include_resolved:
            conditions.append("resolved = 0")
        if task_type:
            conditions.append("(task_type = ? OR task_type IS NULL)")
            params.append(task_type)
        if project_id:
            conditions.append("(project_id = ? OR project_id IS NULL)")
            params.append(project_id)
        if error_category:
            conditions.append("error_category = ?")
            params.append(error_category)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(max(1, min(int(limit or 50), 250)))
        rows = await self.engine.fetch_all(
            f"""SELECT * FROM failure_knowledge
                {where_clause}
                ORDER BY resolved ASC, occurrence_count DESC, updated_at DESC
                LIMIT ?""",
            params,
        )
        return [dict(row) for row in rows]

    async def mark_failure_knowledge_resolved(
        self, error_signature: str, resolution_approach: str
    ) -> None:
        """Mark a failure knowledge entry as resolved."""
        now = datetime.now(UTC).isoformat()
        await self.engine.execute(
            """UPDATE failure_knowledge
               SET resolved = 1, resolution_approach = ?, updated_at = ?
               WHERE error_signature = ? AND resolved = 0""",
            [resolution_approach, now, error_signature],
        )

    async def get_tasks_by_status(self, project_id: str, status: TaskStatus) -> list[Task]:
        rows = await self.engine.fetch_all(
            "SELECT * FROM tasks WHERE project_id = ? AND status = ? ORDER BY priority DESC",
            [project_id, status.value],
        )
        return [_row_to_task(r) for r in rows]

    async def get_in_progress_tasks(self) -> list[Task]:
        rows = await self.engine.fetch_all(
            "SELECT * FROM tasks WHERE status IN ('EVALUATING', 'PLANNING', 'DISPATCHED', 'CODING', 'REVIEWING')"
        )
        return [_row_to_task(r) for r in rows]

    async def list_tasks(self, project_id: str, include_done: bool = True) -> list[Task]:
        if include_done:
            rows = await self.engine.fetch_all(
                "SELECT * FROM tasks WHERE project_id = ? ORDER BY created_at DESC",
                [project_id],
            )
        else:
            rows = await self.engine.fetch_all(
                "SELECT * FROM tasks WHERE project_id = ? AND status != 'DONE' ORDER BY created_at DESC",
                [project_id],
            )
        return [_row_to_task(r) for r in rows]

    async def get_project_results(self, project_id: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        """Get tasks with their latest hypothesis entry for results display.

        Returns a list of dicts with task + hypothesis fields joined together.
        """
        if project_id:
            rows = await self.engine.fetch_all(
                """SELECT t.id AS task_id, t.title, t.status, t.task_type,
                          t.assigned_agent, t.attempt_count, t.created_at AS task_created,
                          t.completed_at,
                          h.approach_summary, h.outcome AS hypothesis_outcome,
                          h.error_signature, h.files_changed, h.duration_seconds,
                          h.model_used, h.agent_id, h.created_at AS hypothesis_created
                   FROM tasks t
                   LEFT JOIN hypothesis_log h ON h.task_id = t.id
                       AND h.attempt_number = (
                           SELECT MAX(h2.attempt_number)
                           FROM hypothesis_log h2
                           WHERE h2.task_id = t.id
                       )
                   WHERE t.project_id = ?
                   ORDER BY t.created_at DESC
                   LIMIT ?""",
                [project_id, limit],
            )
        else:
            rows = await self.engine.fetch_all(
                """SELECT t.id AS task_id, t.title, t.status, t.task_type,
                          t.assigned_agent, t.attempt_count, t.created_at AS task_created,
                          t.completed_at,
                          h.approach_summary, h.outcome AS hypothesis_outcome,
                          h.error_signature, h.files_changed, h.duration_seconds,
                          h.model_used, h.agent_id, h.created_at AS hypothesis_created
                   FROM tasks t
                   LEFT JOIN hypothesis_log h ON h.task_id = t.id
                       AND h.attempt_number = (
                           SELECT MAX(h2.attempt_number)
                           FROM hypothesis_log h2
                           WHERE h2.task_id = t.id
                       )
                   ORDER BY t.created_at DESC
                   LIMIT ?""",
                [limit],
            )
        return [dict(r) for r in rows]

    async def get_task_status_summary(self, project_id: Optional[str] = None) -> dict[str, int]:
        if project_id is None:
            rows = await self.engine.fetch_all(
                "SELECT status, COUNT(*) AS cnt FROM tasks GROUP BY status"
            )
        else:
            rows = await self.engine.fetch_all(
                "SELECT status, COUNT(*) AS cnt FROM tasks WHERE project_id = ? GROUP BY status",
                [project_id],
            )
        return {str(row["status"]): int(row["cnt"]) for row in rows}

    async def get_next_hypothesis_attempt(self, task_id: str) -> int:
        row = await self.engine.fetch_one(
            "SELECT COALESCE(MAX(attempt_number), 0) + 1 AS next_attempt FROM hypothesis_log WHERE task_id = ?",
            [task_id],
        )
        return int(row["next_attempt"]) if row else 1

    async def log_methodology_usage(self, entry: MethodologyUsageEntry) -> MethodologyUsageEntry:
        await self.engine.execute(
            """INSERT INTO methodology_usage_log
               (id, task_id, methodology_id, project_id, stage, agent_id, success,
                expectation_match_score, quality_score, relevance_score, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                entry.id,
                entry.task_id,
                entry.methodology_id,
                entry.project_id,
                entry.stage,
                entry.agent_id,
                None if entry.success is None else int(entry.success),
                entry.expectation_match_score,
                entry.quality_score,
                entry.relevance_score,
                entry.notes,
                entry.created_at.isoformat(),
            ],
        )
        return entry

    async def get_methodology_usage_for_task(self, task_id: str) -> list[MethodologyUsageEntry]:
        rows = await self.engine.fetch_all(
            """SELECT * FROM methodology_usage_log
               WHERE task_id = ?
               ORDER BY created_at ASC""",
            [task_id],
        )
        return [_row_to_methodology_usage_entry(r) for r in rows]

    async def get_methodology_usage_for_methodology(
        self,
        methodology_id: str,
        limit: int = 20,
    ) -> list[MethodologyUsageEntry]:
        rows = await self.engine.fetch_all(
            """SELECT * FROM methodology_usage_log
               WHERE methodology_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            [methodology_id, limit],
        )
        return [_row_to_methodology_usage_entry(r) for r in rows]

    async def get_methodology_usage_stats(self) -> dict[str, dict[str, Any]]:
        rows = await self.engine.fetch_all(
            """SELECT methodology_id,
                      SUM(CASE WHEN stage = 'retrieved_presented' THEN 1 ELSE 0 END) AS retrieved_count,
                      SUM(CASE WHEN stage = 'used_in_outcome' THEN 1 ELSE 0 END) AS used_count,
                      SUM(CASE WHEN stage = 'outcome_attributed' AND success = 1 THEN 1 ELSE 0 END) AS attributed_success_count,
                      SUM(CASE WHEN stage = 'outcome_attributed' AND success = 0 THEN 1 ELSE 0 END) AS attributed_failure_count,
                      AVG(CASE WHEN stage = 'outcome_attributed' THEN expectation_match_score END) AS avg_expectation_match_score,
                      AVG(CASE WHEN stage = 'outcome_attributed' THEN quality_score END) AS avg_quality_score,
                      AVG(CASE WHEN stage = 'retrieved_presented' THEN relevance_score END) AS avg_relevance_score,
                      MAX(created_at) AS last_used_at
               FROM methodology_usage_log
               GROUP BY methodology_id"""
        )
        return {
            str(row["methodology_id"]): {
                "retrieved_count": int(row["retrieved_count"] or 0),
                "used_count": int(row["used_count"] or 0),
                "attributed_success_count": int(row["attributed_success_count"] or 0),
                "attributed_failure_count": int(row["attributed_failure_count"] or 0),
                "avg_expectation_match_score": row["avg_expectation_match_score"],
                "avg_quality_score": row["avg_quality_score"],
                "avg_relevance_score": row["avg_relevance_score"],
                "last_used_at": row["last_used_at"],
            }
            for row in rows
            if row.get("methodology_id")
        }

    async def get_methodology_usage_stats_for_methodology(self, methodology_id: str) -> dict[str, Any]:
        row = await self.engine.fetch_one(
            """SELECT methodology_id,
                      SUM(CASE WHEN stage = 'retrieved_presented' THEN 1 ELSE 0 END) AS retrieved_count,
                      SUM(CASE WHEN stage = 'used_in_outcome' THEN 1 ELSE 0 END) AS used_count,
                      SUM(CASE WHEN stage = 'outcome_attributed' THEN 1 ELSE 0 END) AS attributed_count,
                      SUM(CASE WHEN stage = 'outcome_attributed' AND success = 1 THEN 1 ELSE 0 END) AS attributed_success_count,
                      SUM(CASE WHEN stage = 'outcome_attributed' AND success = 0 THEN 1 ELSE 0 END) AS attributed_failure_count,
                      AVG(CASE WHEN stage = 'outcome_attributed' THEN expectation_match_score END) AS avg_expectation_match_score,
                      AVG(CASE WHEN stage = 'outcome_attributed' THEN quality_score END) AS avg_quality_score,
                      AVG(CASE WHEN stage = 'retrieved_presented' THEN relevance_score END) AS avg_relevance_score,
                      MAX(created_at) AS last_used_at
               FROM methodology_usage_log
               WHERE methodology_id = ?
               GROUP BY methodology_id""",
            [methodology_id],
        )
        if row is None:
            return {
                "retrieved_count": 0,
                "used_count": 0,
                "attributed_count": 0,
                "attributed_success_count": 0,
                "attributed_failure_count": 0,
                "avg_expectation_match_score": None,
                "avg_quality_score": None,
                "avg_relevance_score": None,
                "last_used_at": None,
            }
        return {
            "retrieved_count": int(row["retrieved_count"] or 0),
            "used_count": int(row["used_count"] or 0),
            "attributed_count": int(row["attributed_count"] or 0),
            "attributed_success_count": int(row["attributed_success_count"] or 0),
            "attributed_failure_count": int(row["attributed_failure_count"] or 0),
            "avg_expectation_match_score": row["avg_expectation_match_score"],
            "avg_quality_score": row["avg_quality_score"],
            "avg_relevance_score": row["avg_relevance_score"],
            "last_used_at": row["last_used_at"],
        }

    async def get_methodology_usage_summary_for_tasks(self, task_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not task_ids:
            return {}
        placeholders = ", ".join("?" for _ in task_ids)
        rows = await self.engine.fetch_all(
            f"""SELECT task_id,
                       COUNT(*) AS total_events,
                       COUNT(DISTINCT methodology_id) AS methodology_count,
                       SUM(CASE WHEN stage = 'retrieved_presented' THEN 1 ELSE 0 END) AS retrieved_count,
                       SUM(CASE WHEN stage = 'used_in_outcome' THEN 1 ELSE 0 END) AS used_count,
                       SUM(CASE WHEN stage = 'outcome_attributed' THEN 1 ELSE 0 END) AS attributed_count,
                       SUM(CASE WHEN stage = 'outcome_attributed' AND success = 1 THEN 1 ELSE 0 END) AS attributed_success_count,
                       AVG(CASE WHEN stage = 'outcome_attributed' THEN expectation_match_score END) AS avg_expectation_match_score
                FROM methodology_usage_log
                WHERE task_id IN ({placeholders})
                GROUP BY task_id""",
            task_ids,
        )
        return {
            str(row["task_id"]): {
                "total_events": int(row["total_events"] or 0),
                "methodology_count": int(row["methodology_count"] or 0),
                "retrieved_count": int(row["retrieved_count"] or 0),
                "used_count": int(row["used_count"] or 0),
                "attributed_count": int(row["attributed_count"] or 0),
                "attributed_success_count": int(row["attributed_success_count"] or 0),
                "avg_expectation_match_score": row["avg_expectation_match_score"],
            }
            for row in rows
            if row.get("task_id")
        }

    async def get_methodology_evidence_audit(
        self,
        project_id: Optional[str] = None,
        limit: int = 20,
        expectation_threshold: float = 0.65,
    ) -> dict[str, Any]:
        """Audit high-trust methodologies for attribution-backed evidence quality."""
        params: list[Any] = []
        project_filter = ""
        if project_id is not None:
            project_filter = "AND t.project_id = ?"
            params.append(project_id)

        rows = await self.engine.fetch_all(
            f"""SELECT m.id,
                       m.problem_description,
                       m.lifecycle_state,
                       m.scope,
                       m.success_count,
                       m.retrieval_count,
                       SUM(CASE WHEN mul.stage = 'outcome_attributed' THEN 1 ELSE 0 END) AS attributed_count,
                       SUM(CASE WHEN mul.stage = 'outcome_attributed' AND mul.success = 1 THEN 1 ELSE 0 END) AS attributed_success_count,
                       SUM(CASE WHEN mul.stage = 'outcome_attributed' AND mul.success = 0 THEN 1 ELSE 0 END) AS attributed_failure_count,
                       AVG(CASE WHEN mul.stage = 'outcome_attributed' THEN mul.expectation_match_score END) AS avg_expectation_match_score,
                       AVG(CASE WHEN mul.stage = 'outcome_attributed' THEN mul.quality_score END) AS avg_quality_score,
                       MAX(mul.created_at) AS last_used_at
                FROM methodologies m
                LEFT JOIN tasks t ON m.source_task_id = t.id
                LEFT JOIN methodology_usage_log mul ON mul.methodology_id = m.id
                WHERE (
                    m.lifecycle_state = 'thriving'
                    OR (m.scope = 'global' AND m.success_count > 0)
                )
                  {project_filter}
                GROUP BY m.id, m.problem_description, m.lifecycle_state, m.scope, m.success_count, m.retrieval_count
                ORDER BY
                  CASE WHEN m.scope = 'global' THEN 0 ELSE 1 END,
                  CASE WHEN m.lifecycle_state = 'thriving' THEN 0 ELSE 1 END,
                  COALESCE(attributed_success_count, 0) DESC,
                  m.success_count DESC,
                  m.retrieval_count DESC,
                  m.problem_description ASC""",
            params,
        )

        items: list[dict[str, Any]] = []
        summary = {
            "total_reviewed": 0,
            "thriving_total": 0,
            "global_total": 0,
            "attribution_backed_total": 0,
            "legacy_backed_total": 0,
            "low_expectation_total": 0,
            "demotion_candidate_total": 0,
            "flagged_total": 0,
        }

        for row in rows:
            attributed_count = int(row["attributed_count"] or 0)
            attributed_success_count = int(row["attributed_success_count"] or 0)
            attributed_failure_count = int(row["attributed_failure_count"] or 0)
            success_count = int(row["success_count"] or 0)
            avg_expectation_match_score = row["avg_expectation_match_score"]
            evidence_source = "attribution" if attributed_count > 0 else "legacy"
            flags: list[str] = []

            if evidence_source != "attribution":
                flags.append("legacy_evidence")
            if (
                avg_expectation_match_score is not None
                and float(avg_expectation_match_score) < expectation_threshold
            ):
                flags.append("low_expectation_match")
            if row["scope"] == "global" and attributed_success_count == 0:
                flags.append("global_without_attributed_success")
            elif row["lifecycle_state"] == "thriving" and attributed_success_count == 0:
                flags.append("thriving_without_attributed_success")
            if attributed_failure_count >= 2 and attributed_success_count == 0:
                flags.append("demotion_candidate")

            item = {
                "id": str(row["id"]),
                "problem_description": str(row["problem_description"] or ""),
                "lifecycle_state": str(row["lifecycle_state"] or ""),
                "scope": str(row["scope"] or ""),
                "success_count": success_count,
                "retrieval_count": int(row["retrieval_count"] or 0),
                "attributed_count": attributed_count,
                "attributed_success_count": attributed_success_count,
                "attributed_failure_count": attributed_failure_count,
                "avg_expectation_match_score": avg_expectation_match_score,
                "avg_quality_score": row["avg_quality_score"],
                "last_used_at": row["last_used_at"],
                "evidence_source": evidence_source,
                "flags": flags,
            }
            items.append(item)

            summary["total_reviewed"] += 1
            if item["lifecycle_state"] == "thriving":
                summary["thriving_total"] += 1
            if item["scope"] == "global":
                summary["global_total"] += 1
            if evidence_source == "attribution":
                summary["attribution_backed_total"] += 1
            elif evidence_source == "legacy":
                summary["legacy_backed_total"] += 1
            if "low_expectation_match" in flags:
                summary["low_expectation_total"] += 1
            if "demotion_candidate" in flags:
                summary["demotion_candidate_total"] += 1
            if flags:
                summary["flagged_total"] += 1

        flagged = [item for item in items if item["flags"]][: max(limit, 0)]
        return {
            "summary": summary,
            "flagged": flagged,
            "items": items,
            "expectation_threshold": expectation_threshold,
        }

    # -------------------------------------------------------------------
    # Action Templates
    # -------------------------------------------------------------------

    async def create_action_template(self, template: ActionTemplate) -> ActionTemplate:
        await self.engine.execute(
            """INSERT INTO action_templates
               (id, title, problem_pattern, execution_steps, acceptance_checks,
                rollback_steps, preconditions, source_methodology_id, source_repo,
                confidence, success_count, failure_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                template.id,
                template.title,
                template.problem_pattern,
                json.dumps(template.execution_steps),
                json.dumps(template.acceptance_checks),
                json.dumps(template.rollback_steps),
                json.dumps(template.preconditions),
                template.source_methodology_id,
                template.source_repo,
                template.confidence,
                template.success_count,
                template.failure_count,
                template.created_at.isoformat(),
                template.updated_at.isoformat(),
            ],
        )
        return template

    async def get_action_template(self, template_id: str) -> Optional[ActionTemplate]:
        row = await self.engine.fetch_one(
            "SELECT * FROM action_templates WHERE id = ?",
            [template_id],
        )
        if row is None:
            return None
        return _row_to_action_template(row)

    async def list_action_templates(
        self,
        source_repo: Optional[str] = None,
        limit: int = 50,
    ) -> list[ActionTemplate]:
        if source_repo:
            rows = await self.engine.fetch_all(
                """SELECT * FROM action_templates
                   WHERE source_repo = ?
                   ORDER BY confidence DESC, updated_at DESC
                   LIMIT ?""",
                [source_repo, limit],
            )
        else:
            rows = await self.engine.fetch_all(
                """SELECT * FROM action_templates
                   ORDER BY confidence DESC, updated_at DESC
                   LIMIT ?""",
                [limit],
            )
        return [_row_to_action_template(r) for r in rows]

    async def update_action_template_outcome(self, template_id: str, success: bool) -> None:
        now = datetime.now(UTC).isoformat()
        if success:
            await self.engine.execute(
                """UPDATE action_templates
                   SET success_count = success_count + 1,
                       confidence = MIN(1.0, confidence + 0.03),
                       updated_at = ?
                   WHERE id = ?""",
                [now, template_id],
            )
        else:
            await self.engine.execute(
                """UPDATE action_templates
                   SET failure_count = failure_count + 1,
                       confidence = MAX(0.0, confidence - 0.05),
                       updated_at = ?
                   WHERE id = ?""",
                [now, template_id],
            )

    # -------------------------------------------------------------------
    # Hypothesis Log
    # -------------------------------------------------------------------

    async def log_hypothesis(self, entry: HypothesisEntry) -> HypothesisEntry:
        await self.engine.execute(
            """INSERT INTO hypothesis_log
               (id, task_id, attempt_number, approach_summary, outcome,
                error_signature, error_full, files_changed, duration_seconds, model_used, agent_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                entry.id,
                entry.task_id,
                entry.attempt_number,
                entry.approach_summary,
                entry.outcome.value,
                entry.error_signature,
                entry.error_full,
                json.dumps(entry.files_changed),
                entry.duration_seconds,
                entry.model_used,
                entry.agent_id,
            ],
        )
        return entry

    async def get_failed_approaches(self, task_id: str) -> list[HypothesisEntry]:
        rows = await self.engine.fetch_all(
            """SELECT * FROM hypothesis_log
               WHERE task_id = ? AND outcome = 'FAILURE'
               ORDER BY attempt_number ASC""",
            [task_id],
        )
        return [_row_to_hypothesis(r) for r in rows]

    async def get_hypothesis_count(self, task_id: str) -> int:
        row = await self.engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM hypothesis_log WHERE task_id = ?",
            [task_id],
        )
        return row["cnt"] if row else 0

    async def has_duplicate_error(self, task_id: str, error_signature: str) -> bool:
        row = await self.engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM hypothesis_log WHERE task_id = ? AND error_signature = ? AND outcome = 'FAILURE'",
            [task_id, error_signature],
        )
        return (row["cnt"] if row else 0) > 0

    async def count_error_signature(self, task_id: str, error_signature: str) -> int:
        row = await self.engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM hypothesis_log WHERE task_id = ? AND error_signature = ?",
            [task_id, error_signature],
        )
        return int(row["cnt"]) if row else 0

    async def get_hypothesis_error_stats(self, project_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Get error signature statistics across tasks."""
        if project_id:
            rows = await self.engine.fetch_all(
                """SELECT h.error_signature, COUNT(*) as cnt
                   FROM hypothesis_log h
                   JOIN tasks t ON h.task_id = t.id
                   WHERE t.project_id = ? AND h.error_signature IS NOT NULL
                   GROUP BY h.error_signature
                   ORDER BY cnt DESC
                   LIMIT 20""",
                [project_id],
            )
        else:
            rows = await self.engine.fetch_all(
                """SELECT error_signature, COUNT(*) as cnt
                   FROM hypothesis_log
                   WHERE error_signature IS NOT NULL
                   GROUP BY error_signature
                   ORDER BY cnt DESC
                   LIMIT 20"""
            )
        return [dict(r) for r in rows]

    # -------------------------------------------------------------------
    # Methodologies
    # -------------------------------------------------------------------

    async def save_methodology(self, methodology: Methodology) -> Methodology:
        await self.engine.execute(
            """INSERT INTO methodologies
               (id, problem_description, solution_code, methodology_notes,
                source_task_id, tags, language, scope, methodology_type, files_affected,
                lifecycle_state, generation, fitness_vector, parent_ids, superseded_by,
                prism_data, capability_data, novelty_score, potential_score,
                accuracy_contract, concept_type, use_immediately_as, tension_questions, triage_score)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                methodology.id,
                methodology.problem_description,
                methodology.solution_code,
                methodology.methodology_notes,
                methodology.source_task_id,
                json.dumps(methodology.tags),
                methodology.language,
                methodology.scope,
                methodology.methodology_type,
                json.dumps(methodology.files_affected),
                methodology.lifecycle_state,
                methodology.generation,
                json.dumps(methodology.fitness_vector),
                json.dumps(methodology.parent_ids),
                methodology.superseded_by,
                json.dumps(methodology.prism_data) if methodology.prism_data else None,
                json.dumps(methodology.capability_data) if methodology.capability_data else None,
                methodology.novelty_score,
                methodology.potential_score,
                methodology.accuracy_contract,
                methodology.concept_type,
                json.dumps(methodology.use_immediately_as),
                json.dumps(methodology.tension_questions),
                methodology.triage_score,
            ],
        )

        # Insert into FTS5 index
        await self.engine.execute(
            "INSERT INTO methodology_fts (methodology_id, problem_description, methodology_notes, tags) VALUES (?, ?, ?, ?)",
            [
                methodology.id,
                methodology.problem_description,
                methodology.methodology_notes or "",
                json.dumps(methodology.tags),
            ],
        )

        # Insert embedding into sqlite-vec if available
        if methodology.problem_embedding:
            vec_bytes = struct.pack(f"<{len(methodology.problem_embedding)}f", *methodology.problem_embedding)
            await self.engine.execute(
                "INSERT INTO methodology_embeddings (methodology_id, embedding) VALUES (?, ?)",
                [methodology.id, vec_bytes],
            )

        return methodology

    async def find_similar_methodologies(
        self, embedding: list[float], limit: int = 3
    ) -> list[tuple[Methodology, float]]:
        """Find methodologies by vector similarity. Returns (methodology, similarity) pairs."""
        vec_bytes = struct.pack(f"<{len(embedding)}f", *embedding)
        rows = await self.engine.fetch_all(
            """SELECT methodology_id, distance
               FROM methodology_embeddings
               WHERE embedding MATCH ?
               ORDER BY distance ASC
               LIMIT ?""",
            [vec_bytes, limit],
        )

        results = []
        for row in rows:
            mid = row["methodology_id"]
            distance = row["distance"]
            similarity = 1.0 - distance
            meth = await self.get_methodology(mid)
            if meth:
                results.append((meth, similarity))
        return results

    async def search_methodologies_text(
        self, query: str, limit: int = 5
    ) -> list[tuple[Methodology, float]]:
        """Full-text search on methodologies using FTS5.

        Returns list of (Methodology, bm25_rank) tuples. FTS5 rank is
        negative (more negative = better match). Callers should normalize
        before fusion.
        """
        safe_query = _build_safe_fts5_query(query)
        if not safe_query:
            return []
        rows = await self.engine.fetch_all(
            """SELECT methodology_id, rank
               FROM methodology_fts
               WHERE methodology_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            [safe_query, limit],
        )

        results: list[tuple[Methodology, float]] = []
        for row in rows:
            meth = await self.get_methodology(row["methodology_id"])
            if meth:
                results.append((meth, float(row["rank"])))
        return results

    async def get_methodology(self, methodology_id: str) -> Optional[Methodology]:
        row = await self.engine.fetch_one(
            "SELECT * FROM methodologies WHERE id = ?", [methodology_id]
        )
        if row is None:
            return None
        return _row_to_methodology(row)

    async def get_methodologies_by_state(self, state: str, limit: int = 50) -> list[Methodology]:
        rows = await self.engine.fetch_all(
            "SELECT * FROM methodologies WHERE lifecycle_state = ? LIMIT ?",
            [state, limit],
        )
        return [_row_to_methodology(r) for r in rows]

    async def list_methodologies(
        self,
        limit: int = 2000,
        include_dead: bool = False,
    ) -> list[Methodology]:
        """List methodologies for reporting/analysis."""
        if include_dead:
            rows = await self.engine.fetch_all(
                """SELECT * FROM methodologies
                   ORDER BY created_at DESC
                   LIMIT ?""",
                [limit],
            )
        else:
            rows = await self.engine.fetch_all(
                """SELECT * FROM methodologies
                   WHERE lifecycle_state != 'dead'
                   ORDER BY created_at DESC
                   LIMIT ?""",
                [limit],
            )
        return [_row_to_methodology(r) for r in rows]

    async def update_methodology_retrieval(self, methodology_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        await self.engine.execute(
            "UPDATE methodologies SET retrieval_count = retrieval_count + 1, last_retrieved_at = ? WHERE id = ?",
            [now, methodology_id],
        )

    async def update_methodology_outcome(self, methodology_id: str, success: bool) -> None:
        if success:
            await self.engine.execute(
                "UPDATE methodologies SET success_count = success_count + 1 WHERE id = ?",
                [methodology_id],
            )
        else:
            await self.engine.execute(
                "UPDATE methodologies SET failure_count = failure_count + 1 WHERE id = ?",
                [methodology_id],
            )

    async def update_methodology_fitness(self, methodology_id: str, fitness_vector: dict[str, float]) -> None:
        await self.engine.execute(
            "UPDATE methodologies SET fitness_vector = ? WHERE id = ?",
            [json.dumps(fitness_vector), methodology_id],
        )

    async def update_methodology_lifecycle(self, methodology_id: str, new_state: str) -> None:
        await self.engine.execute(
            "UPDATE methodologies SET lifecycle_state = ? WHERE id = ?",
            [new_state, methodology_id],
        )

        # Update vmf_kappa in stored PRISM data to match new lifecycle
        row = await self.engine.fetch_one(
            "SELECT prism_data FROM methodologies WHERE id = ?", [methodology_id]
        )
        if row and row.get("prism_data"):
            try:
                from claw.embeddings.prism import _DEFAULT_KAPPA, _LIFECYCLE_KAPPA
                prism_dict = json.loads(row["prism_data"])
                prism_dict["vmf_kappa"] = _LIFECYCLE_KAPPA.get(new_state, _DEFAULT_KAPPA)
                await self.engine.execute(
                    "UPDATE methodologies SET prism_data = ? WHERE id = ?",
                    [json.dumps(prism_dict), methodology_id],
                )
            except (json.JSONDecodeError, KeyError):
                pass  # Corrupt prism_data — leave as-is

    async def update_methodology_scope(self, methodology_id: str, new_scope: str) -> None:
        await self.engine.execute(
            "UPDATE methodologies SET scope = ? WHERE id = ?",
            [new_scope, methodology_id],
        )

    async def update_methodology_prism_data(self, methodology_id: str, prism_data: dict) -> None:
        """Store or replace the PRISM embedding for an existing methodology."""
        await self.engine.execute(
            "UPDATE methodologies SET prism_data = ? WHERE id = ?",
            [json.dumps(prism_data), methodology_id],
        )

    async def update_methodology_directives(
        self,
        methodology_id: str,
        use_immediately_as: list[str] | None = None,
        tension_questions: list[str] | None = None,
        accuracy_contract: str | None = None,
        concept_type: str | None = None,
        triage_score: float | None = None,
    ) -> None:
        """Update pseudo-RAG operational fields on a methodology."""
        updates: list[str] = []
        params: list[Any] = []
        if use_immediately_as is not None:
            updates.append("use_immediately_as = ?")
            params.append(json.dumps(use_immediately_as))
        if tension_questions is not None:
            updates.append("tension_questions = ?")
            params.append(json.dumps(tension_questions))
        if accuracy_contract is not None:
            updates.append("accuracy_contract = ?")
            params.append(accuracy_contract)
        if concept_type is not None:
            updates.append("concept_type = ?")
            params.append(concept_type)
        if triage_score is not None:
            updates.append("triage_score = ?")
            params.append(triage_score)
        if updates:
            params.append(methodology_id)
            await self.engine.execute(
                f"UPDATE methodologies SET {', '.join(updates)} WHERE id = ?",
                params,
            )

    async def count_methodologies(self) -> int:
        row = await self.engine.fetch_one("SELECT COUNT(*) as cnt FROM methodologies")
        return row["cnt"] if row else 0

    async def count_active_methodologies(self) -> int:
        """Count non-dead methodologies."""
        row = await self.engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM methodologies WHERE lifecycle_state != 'dead'"
        )
        return int(row["cnt"]) if row else 0

    async def count_methodologies_by_state(self) -> dict[str, int]:
        """Count methodologies grouped by lifecycle state."""
        rows = await self.engine.fetch_all(
            "SELECT lifecycle_state, COUNT(*) as cnt FROM methodologies GROUP BY lifecycle_state"
        )
        return {str(r["lifecycle_state"]): int(r["cnt"]) for r in rows}

    async def get_dead_methodologies(self, limit: int = 100) -> list[Methodology]:
        """Get dead methodologies for garbage collection."""
        rows = await self.engine.fetch_all(
            "SELECT * FROM methodologies WHERE lifecycle_state = 'dead' LIMIT ?",
            [limit],
        )
        return [_row_to_methodology(r) for r in rows]

    async def get_lowest_fitness_methodologies(
        self, states: list[str], limit: int = 50
    ) -> list[Methodology]:
        """Get methodologies with lowest fitness in given states, ordered for culling."""
        placeholders = ",".join("?" for _ in states)
        rows = await self.engine.fetch_all(
            f"""SELECT * FROM methodologies
                WHERE lifecycle_state IN ({placeholders})
                ORDER BY
                    CASE lifecycle_state
                        WHEN 'dead' THEN 0
                        WHEN 'dormant' THEN 1
                        WHEN 'declining' THEN 2
                        WHEN 'embryonic' THEN 3
                        WHEN 'viable' THEN 4
                        WHEN 'thriving' THEN 5
                    END ASC,
                    json_extract(fitness_vector, '$.total') ASC
                LIMIT ?""",
            [*states, limit],
        )
        return [_row_to_methodology(r) for r in rows]

    async def delete_methodology(self, methodology_id: str) -> bool:
        """Delete a methodology and its associated FTS5, embedding, and synergy entries."""
        existing = await self.get_methodology(methodology_id)
        if existing is None:
            return False

        await self.engine.execute(
            "DELETE FROM methodology_embeddings WHERE methodology_id = ?",
            [methodology_id],
        )
        await self.engine.execute(
            "DELETE FROM methodology_fts WHERE methodology_id = ?",
            [methodology_id],
        )
        await self.engine.execute(
            "DELETE FROM methodology_links WHERE source_id = ? OR target_id = ?",
            [methodology_id, methodology_id],
        )
        # Mark synergy explorations as stale rather than deleting
        await self.engine.execute(
            """UPDATE synergy_exploration_log SET result = 'stale'
               WHERE cap_a_id = ? OR cap_b_id = ?""",
            [methodology_id, methodology_id],
        )
        await self.engine.execute(
            "DELETE FROM methodologies WHERE id = ?",
            [methodology_id],
        )
        return True

    async def get_db_size_bytes(self) -> int:
        """Get the SQLite database file size in bytes."""
        row = await self.engine.fetch_one(
            "SELECT page_count * page_size as size FROM pragma_page_count, pragma_page_size"
        )
        return int(row["size"]) if row else 0

    async def get_methodologies_by_tag(self, tag: str, limit: int = 50) -> list[Methodology]:
        """Get methodologies containing a specific tag."""
        rows = await self.engine.fetch_all(
            "SELECT * FROM methodologies WHERE tags LIKE ? LIMIT ?",
            [f'%"{tag}"%', limit],
        )
        return [_row_to_methodology(r) for r in rows]

    async def log_governance_action(
        self,
        action_type: str,
        methodology_id: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> str:
        """Log a governance action for audit trail."""
        action_id = str(uuid.uuid4())
        await self.engine.execute(
            """INSERT INTO governance_log (id, action_type, methodology_id, details)
               VALUES (?, ?, ?, ?)""",
            [action_id, action_type, methodology_id, json.dumps(details or {})],
        )
        return action_id

    async def count_episodes(self) -> int:
        """Count total episodes."""
        row = await self.engine.fetch_one("SELECT COUNT(*) as cnt FROM episodes")
        return int(row["cnt"]) if row else 0

    async def delete_old_episodes(self, before_date: str) -> int:
        """Delete episodes older than the given ISO date. Returns count deleted."""
        row = await self.engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM episodes WHERE created_at < ?",
            [before_date],
        )
        count = int(row["cnt"]) if row else 0
        if count > 0:
            await self.engine.execute(
                "DELETE FROM episodes WHERE created_at < ?",
                [before_date],
            )
        return count

    # -------------------------------------------------------------------
    # Methodology Links (Stigmergic co-retrieval)
    # -------------------------------------------------------------------

    async def upsert_methodology_link(
        self, source_id: str, target_id: str, link_type: str = "co_retrieval", strength: float = 1.0
    ) -> None:
        link_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        await self.engine.execute(
            """INSERT INTO methodology_links (id, source_id, target_id, link_type, strength, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source_id, target_id, link_type)
               DO UPDATE SET strength = strength + ?, updated_at = ?""",
            [link_id, source_id, target_id, link_type, strength, now, now, strength, now],
        )

    async def get_methodology_links(self, methodology_id: str) -> list[dict[str, Any]]:
        rows = await self.engine.fetch_all(
            "SELECT * FROM methodology_links WHERE source_id = ? OR target_id = ?",
            [methodology_id, methodology_id],
        )
        return [dict(r) for r in rows]

    async def get_methodology_links_by_type(
        self, methodology_id: str, link_type: str
    ) -> list[dict[str, Any]]:
        """Get links of a specific type for a methodology."""
        rows = await self.engine.fetch_all(
            """SELECT * FROM methodology_links
               WHERE (source_id = ? OR target_id = ?) AND link_type = ?""",
            [methodology_id, methodology_id, link_type],
        )
        return [dict(r) for r in rows]

    # -------------------------------------------------------------------
    # Capability Data
    # -------------------------------------------------------------------

    async def update_methodology_capability_data(
        self, methodology_id: str, capability_data: dict
    ) -> None:
        """Store or replace structured capability_data for a methodology."""
        await self.engine.execute(
            "UPDATE methodologies SET capability_data = ? WHERE id = ?",
            [json.dumps(capability_data), methodology_id],
        )

    async def get_methodologies_with_capabilities(self, limit: int = 100) -> list[Methodology]:
        """Get methodologies that have capability_data populated."""
        rows = await self.engine.fetch_all(
            """SELECT * FROM methodologies
               WHERE capability_data IS NOT NULL AND lifecycle_state != 'dead'
               LIMIT ?""",
            [limit],
        )
        return [_row_to_methodology(r) for r in rows]

    async def get_methodologies_without_capability_data(self, limit: int = 50) -> list[Methodology]:
        """Get methodologies missing capability_data for enrichment."""
        rows = await self.engine.fetch_all(
            """SELECT * FROM methodologies
               WHERE capability_data IS NULL AND lifecycle_state != 'dead'
               ORDER BY created_at ASC
               LIMIT ?""",
            [limit],
        )
        return [_row_to_methodology(r) for r in rows]

    async def get_unenriched_methodologies(self, limit: int = 100) -> list[Methodology]:
        """Get methodologies that need assimilation enrichment.

        Returns methodologies where capability_data is NULL (no extraction yet),
        or novelty_score is NULL (no scoring yet), ordered oldest first.
        """
        rows = await self.engine.fetch_all(
            """SELECT * FROM methodologies
               WHERE lifecycle_state != 'dead'
                 AND (capability_data IS NULL
                      OR json_extract(capability_data, '$.enrichment_status') IN ('seeded', 'partial')
                      OR novelty_score IS NULL)
               ORDER BY created_at ASC
               LIMIT ?""",
            [limit],
        )
        return [_row_to_methodology(r) for r in rows]

    # -------------------------------------------------------------------
    # Novelty Scoring
    # -------------------------------------------------------------------

    async def update_methodology_novelty_scores(
        self, methodology_id: str, novelty: float, potential: float
    ) -> None:
        """Persist novelty and potential scores for a methodology."""
        await self.engine.execute(
            "UPDATE methodologies SET novelty_score = ?, potential_score = ? WHERE id = ?",
            [novelty, potential, methodology_id],
        )

    async def get_most_novel_methodologies(
        self, limit: int = 10, min_novelty: float = 0.0
    ) -> list[Methodology]:
        """Get methodologies ordered by novelty_score DESC."""
        rows = await self.engine.fetch_all(
            """SELECT * FROM methodologies
               WHERE novelty_score IS NOT NULL AND novelty_score >= ?
                 AND lifecycle_state != 'dead'
               ORDER BY novelty_score DESC
               LIMIT ?""",
            [min_novelty, limit],
        )
        return [_row_to_methodology(r) for r in rows]

    async def get_high_potential_methodologies(
        self, limit: int = 10, min_potential: float = 0.0
    ) -> list[Methodology]:
        """Get methodologies ordered by potential_score DESC."""
        rows = await self.engine.fetch_all(
            """SELECT * FROM methodologies
               WHERE potential_score IS NOT NULL AND potential_score >= ?
                 AND lifecycle_state != 'dead'
               ORDER BY potential_score DESC
               LIMIT ?""",
            [min_potential, limit],
        )
        return [_row_to_methodology(r) for r in rows]

    async def get_embedding_centroid(self) -> list[float]:
        """Compute mean embedding vector from all methodology_embeddings.

        Returns a centroid vector (dimension inferred from data), or empty list if no embeddings.
        """
        rows = await self.engine.fetch_all(
            "SELECT embedding FROM methodology_embeddings"
        )
        if not rows:
            return []

        dim: int | None = None
        centroid: list[float] = []
        count = 0
        for row in rows:
            raw = row["embedding"]
            if raw is None:
                continue
            if dim is None:
                dim = len(raw) // 4  # float32 = 4 bytes each
                centroid = [0.0] * dim
            vec = list(struct.unpack(f"<{dim}f", raw))
            for i in range(dim):
                centroid[i] += vec[i]
            count += 1

        if count == 0 or dim is None:
            return []
        return [c / count for c in centroid]

    async def get_domain_distribution(self) -> dict[str, int]:
        """Count occurrences of each domain tag across all capability_data.

        Parses the domain list from capability_data JSON for each methodology.
        """
        rows = await self.engine.fetch_all(
            """SELECT capability_data FROM methodologies
               WHERE capability_data IS NOT NULL AND lifecycle_state != 'dead'"""
        )
        dist: dict[str, int] = {}
        for row in rows:
            raw = row["capability_data"]
            if not raw:
                continue
            try:
                cap = json.loads(raw) if isinstance(raw, str) else raw
                for domain in cap.get("domain", []):
                    dist[domain] = dist.get(domain, 0) + 1
            except (json.JSONDecodeError, TypeError):
                continue
        return dist

    async def get_type_distribution(self) -> dict[str, int]:
        """Count occurrences of each capability_type across methodologies."""
        rows = await self.engine.fetch_all(
            """SELECT capability_data FROM methodologies
               WHERE capability_data IS NOT NULL AND lifecycle_state != 'dead'"""
        )
        dist: dict[str, int] = {}
        for row in rows:
            raw = row["capability_data"]
            if not raw:
                continue
            try:
                cap = json.loads(raw) if isinstance(raw, str) else raw
                ctype = cap.get("capability_type", "transformation")
                dist[ctype] = dist.get(ctype, 0) + 1
            except (json.JSONDecodeError, TypeError):
                continue
        return dist

    # -------------------------------------------------------------------
    # Synergy Exploration Log
    # -------------------------------------------------------------------

    async def record_synergy_exploration(self, exploration: SynergyExploration) -> None:
        """Record an explored capability pair. Canonical ordering enforced by caller."""
        await self.engine.execute(
            """INSERT INTO synergy_exploration_log
               (id, cap_a_id, cap_b_id, explored_at, result,
                synergy_score, synergy_type, edge_id, exploration_method, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(cap_a_id, cap_b_id) DO UPDATE SET
                   result = excluded.result,
                   synergy_score = excluded.synergy_score,
                   synergy_type = excluded.synergy_type,
                   edge_id = excluded.edge_id,
                   exploration_method = excluded.exploration_method,
                   details = excluded.details,
                   explored_at = excluded.explored_at""",
            [
                exploration.id,
                exploration.cap_a_id,
                exploration.cap_b_id,
                exploration.explored_at.isoformat() if exploration.explored_at else None,
                exploration.result,
                exploration.synergy_score,
                exploration.synergy_type,
                exploration.edge_id,
                exploration.exploration_method,
                json.dumps(exploration.details),
            ],
        )

    async def get_synergy_exploration(
        self, cap_a_id: str, cap_b_id: str
    ) -> Optional[SynergyExploration]:
        """Get exploration record for a canonical pair (a < b alphabetically)."""
        a, b = (cap_a_id, cap_b_id) if cap_a_id < cap_b_id else (cap_b_id, cap_a_id)
        row = await self.engine.fetch_one(
            "SELECT * FROM synergy_exploration_log WHERE cap_a_id = ? AND cap_b_id = ?",
            [a, b],
        )
        if row is None:
            return None
        return _row_to_synergy_exploration(row)

    async def get_unexplored_pairs(
        self, cap_id: str, candidate_ids: list[str]
    ) -> list[str]:
        """Filter candidate_ids to only those NOT yet explored with cap_id."""
        if not candidate_ids:
            return []
        unexplored = []
        for cid in candidate_ids:
            a, b = (cap_id, cid) if cap_id < cid else (cid, cap_id)
            row = await self.engine.fetch_one(
                "SELECT 1 FROM synergy_exploration_log WHERE cap_a_id = ? AND cap_b_id = ?",
                [a, b],
            )
            if row is None:
                unexplored.append(cid)
        return unexplored

    async def get_synergy_stats(self) -> dict[str, Any]:
        """Get aggregate stats from the synergy exploration log."""
        total_row = await self.engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM synergy_exploration_log"
        )
        total = int(total_row["cnt"]) if total_row else 0

        by_result = await self.engine.fetch_all(
            "SELECT result, COUNT(*) as cnt FROM synergy_exploration_log GROUP BY result"
        )
        result_counts = {str(r["result"]): int(r["cnt"]) for r in by_result}

        avg_row = await self.engine.fetch_one(
            "SELECT AVG(synergy_score) as avg_score FROM synergy_exploration_log WHERE synergy_score IS NOT NULL"
        )
        avg_score = float(avg_row["avg_score"]) if avg_row and avg_row["avg_score"] else 0.0

        edge_row = await self.engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM methodology_links WHERE link_type != 'co_retrieval'"
        )
        synergy_edges = int(edge_row["cnt"]) if edge_row else 0

        return {
            "total_explored": total,
            "by_result": result_counts,
            "avg_synergy_score": round(avg_score, 4),
            "synergy_edges": synergy_edges,
        }

    async def mark_stale_explorations(self, methodology_id: str) -> int:
        """Mark explorations as stale when a methodology is deleted."""
        rows = await self.engine.fetch_all(
            """SELECT id FROM synergy_exploration_log
               WHERE cap_a_id = ? OR cap_b_id = ?""",
            [methodology_id, methodology_id],
        )
        count = len(rows)
        if count > 0:
            await self.engine.execute(
                """UPDATE synergy_exploration_log SET result = 'stale'
                   WHERE cap_a_id = ? OR cap_b_id = ?""",
                [methodology_id, methodology_id],
            )
        return count

    # -------------------------------------------------------------------
    # Capability Graph Traversal
    # -------------------------------------------------------------------

    async def get_synergy_graph(
        self, methodology_id: str, depth: int = 2
    ) -> dict[str, Any]:
        """BFS traversal of synergy edges from a starting methodology.

        depth=1 means follow one hop (root + direct neighbors).
        Returns a dict with 'nodes' (set of methodology IDs) and
        'edges' (list of (source, target, link_type, strength) tuples).
        """
        visited: set[str] = set()
        edges: list[tuple[str, str, str, float]] = []
        current_level = {methodology_id}

        for _ in range(depth + 1):
            if not current_level:
                break
            next_level: set[str] = set()
            for node_id in current_level:
                if node_id in visited:
                    continue
                visited.add(node_id)
                links = await self.engine.fetch_all(
                    """SELECT source_id, target_id, link_type, strength
                       FROM methodology_links
                       WHERE source_id = ? OR target_id = ?""",
                    [node_id, node_id],
                )
                for link in links:
                    src = link["source_id"]
                    tgt = link["target_id"]
                    edge_tuple = (src, tgt, link["link_type"], link["strength"])
                    if edge_tuple not in edges:
                        edges.append(edge_tuple)
                    neighbor = tgt if src == node_id else src
                    if neighbor not in visited:
                        next_level.add(neighbor)
            current_level = next_level

        return {
            "nodes": visited,
            "edges": edges,
        }

    async def get_complementary_capabilities(
        self, methodology_id: str
    ) -> list[Methodology]:
        """Follow feeds_into, enhances, and synergy edges to find complementary capabilities."""
        complementary_ids: set[str] = set()
        target_link_types = ("feeds_into", "enhances", "synergy")

        for lt in target_link_types:
            links = await self.engine.fetch_all(
                """SELECT source_id, target_id FROM methodology_links
                   WHERE (source_id = ? OR target_id = ?) AND link_type = ?""",
                [methodology_id, methodology_id, lt],
            )
            for link in links:
                neighbor = link["target_id"] if link["source_id"] == methodology_id else link["source_id"]
                complementary_ids.add(neighbor)

        results = []
        for cid in complementary_ids:
            meth = await self.get_methodology(cid)
            if meth and meth.lifecycle_state != "dead":
                results.append(meth)
        return results

    # -------------------------------------------------------------------
    # Knowledge Browser Queries
    # -------------------------------------------------------------------

    async def get_top_synergy_edges(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get top synergy edges ordered by score, with capability summaries."""
        rows = await self.engine.fetch_all(
            """SELECT sel.cap_a_id, sel.cap_b_id, sel.synergy_score,
                      sel.synergy_type, sel.details
               FROM synergy_exploration_log sel
               WHERE sel.result = 'synergy'
               ORDER BY sel.synergy_score DESC
               LIMIT ?""",
            [limit],
        )
        results = []
        for row in rows:
            cap_a = await self.get_methodology(row["cap_a_id"])
            cap_b = await self.get_methodology(row["cap_b_id"])
            details_raw = row["details"]
            details = json.loads(details_raw) if isinstance(details_raw, str) else (details_raw or {})
            results.append({
                "cap_a_id": row["cap_a_id"],
                "cap_b_id": row["cap_b_id"],
                "cap_a_summary": (cap_a.problem_description[:80] if cap_a else "(deleted)"),
                "cap_b_summary": (cap_b.problem_description[:80] if cap_b else "(deleted)"),
                "cap_a_domains": (cap_a.capability_data or {}).get("domain", []) if cap_a else [],
                "cap_b_domains": (cap_b.capability_data or {}).get("domain", []) if cap_b else [],
                "synergy_score": row["synergy_score"] or 0.0,
                "synergy_type": row["synergy_type"] or "",
                "details": details,
            })
        return results

    async def get_novelty_potential_distribution(self) -> dict[str, Any]:
        """Get summary statistics for novelty and potential scores."""
        row = await self.engine.fetch_one(
            """SELECT
                  COUNT(*) as total,
                  AVG(novelty_score) as avg_novelty,
                  MAX(novelty_score) as max_novelty,
                  MIN(novelty_score) as min_novelty,
                  AVG(potential_score) as avg_potential,
                  MAX(potential_score) as max_potential,
                  MIN(potential_score) as min_potential
               FROM methodologies
               WHERE novelty_score IS NOT NULL"""
        )
        if row is None or row["total"] == 0:
            return {
                "total": 0, "avg_novelty": 0.0, "max_novelty": 0.0,
                "min_novelty": 0.0, "avg_potential": 0.0,
                "max_potential": 0.0, "min_potential": 0.0,
            }
        return {
            "total": int(row["total"]),
            "avg_novelty": round(float(row["avg_novelty"] or 0), 4),
            "max_novelty": round(float(row["max_novelty"] or 0), 4),
            "min_novelty": round(float(row["min_novelty"] or 0), 4),
            "avg_potential": round(float(row["avg_potential"] or 0), 4),
            "max_potential": round(float(row["max_potential"] or 0), 4),
            "min_potential": round(float(row["min_potential"] or 0), 4),
        }

    async def get_cross_domain_capabilities(
        self, min_domains: int = 2, limit: int = 20
    ) -> list[Methodology]:
        """Get capabilities spanning multiple knowledge domains (bridge capabilities)."""
        rows = await self.engine.fetch_all(
            """SELECT * FROM methodologies
               WHERE capability_data IS NOT NULL AND lifecycle_state != 'dead'"""
        )
        bridges = []
        for row in rows:
            raw = row["capability_data"]
            if not raw:
                continue
            try:
                cap = json.loads(raw) if isinstance(raw, str) else raw
                domains = cap.get("domain", [])
                if len(domains) >= min_domains:
                    bridges.append(_row_to_methodology(row))
            except (json.JSONDecodeError, TypeError):
                continue
        # Sort by number of domains descending, then by novelty_score descending
        bridges.sort(
            key=lambda m: (
                len((m.capability_data or {}).get("domain", [])),
                m.novelty_score or 0,
            ),
            reverse=True,
        )
        return bridges[:limit]

    async def get_methodology_by_prefix(self, prefix: str) -> Optional[Methodology]:
        """Find a methodology by ID prefix (first 6+ chars)."""
        rows = await self.engine.fetch_all(
            "SELECT * FROM methodologies WHERE id LIKE ? LIMIT 2",
            [f"{prefix}%"],
        )
        if len(rows) == 1:
            return _row_to_methodology(rows[0])
        if len(rows) > 1:
            # Ambiguous prefix — try exact match first
            for row in rows:
                if row["id"] == prefix:
                    return _row_to_methodology(row)
            # Return first match as best effort
            return _row_to_methodology(rows[0])
        return None

    # -------------------------------------------------------------------
    # Peer Reviews
    # -------------------------------------------------------------------

    async def save_peer_review(self, review: PeerReview) -> PeerReview:
        await self.engine.execute(
            """INSERT INTO peer_reviews
               (id, task_id, model_used, diagnosis, recommended_approach, reasoning)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                review.id,
                review.task_id,
                review.model_used,
                review.diagnosis,
                review.recommended_approach,
                review.reasoning,
            ],
        )
        return review

    async def get_peer_reviews(self, task_id: str) -> list[PeerReview]:
        rows = await self.engine.fetch_all(
            "SELECT * FROM peer_reviews WHERE task_id = ? ORDER BY created_at DESC",
            [task_id],
        )
        return [_row_to_peer_review(r) for r in rows]

    # -------------------------------------------------------------------
    # Context Snapshots
    # -------------------------------------------------------------------

    async def save_context_snapshot(self, snapshot: ContextSnapshot) -> ContextSnapshot:
        await self.engine.execute(
            """INSERT INTO context_snapshots
               (id, task_id, attempt_number, git_ref, file_manifest)
               VALUES (?, ?, ?, ?, ?)""",
            [
                snapshot.id,
                snapshot.task_id,
                snapshot.attempt_number,
                snapshot.git_ref,
                json.dumps(snapshot.file_manifest) if snapshot.file_manifest else None,
            ],
        )
        return snapshot

    async def get_latest_snapshot(self, task_id: str) -> Optional[ContextSnapshot]:
        row = await self.engine.fetch_one(
            "SELECT * FROM context_snapshots WHERE task_id = ? ORDER BY attempt_number DESC LIMIT 1",
            [task_id],
        )
        if row is None:
            return None
        return _row_to_context_snapshot(row)

    # -------------------------------------------------------------------
    # Token Costs
    # -------------------------------------------------------------------

    async def save_token_cost(self, record: TokenCostRecord) -> TokenCostRecord:
        await self.engine.execute(
            """INSERT INTO token_costs
               (id, task_id, run_id, agent_role, agent_id, model_used,
                input_tokens, output_tokens, total_tokens, cost_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                record.id,
                record.task_id,
                record.run_id,
                record.agent_role,
                record.agent_id,
                record.model_used,
                record.input_tokens,
                record.output_tokens,
                record.total_tokens,
                record.cost_usd,
            ],
        )
        return record

    async def get_token_cost_summary(self, task_id: Optional[str] = None) -> dict[str, Any]:
        if task_id:
            row = await self.engine.fetch_one(
                """SELECT COUNT(*) as calls, SUM(input_tokens) as input_tok,
                   SUM(output_tokens) as output_tok, SUM(total_tokens) as total_tok,
                   SUM(cost_usd) as total_cost
                   FROM token_costs WHERE task_id = ?""",
                [task_id],
            )
        else:
            row = await self.engine.fetch_one(
                """SELECT COUNT(*) as calls, SUM(input_tokens) as input_tok,
                   SUM(output_tokens) as output_tok, SUM(total_tokens) as total_tok,
                   SUM(cost_usd) as total_cost
                   FROM token_costs"""
            )
        if row is None:
            return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "total_cost_usd": 0.0}
        return {
            "calls": row["calls"] or 0,
            "input_tokens": row["input_tok"] or 0,
            "output_tokens": row["output_tok"] or 0,
            "total_tokens": row["total_tok"] or 0,
            "total_cost_usd": row["total_cost"] or 0.0,
        }

    # -------------------------------------------------------------------
    # CLAW-specific: Agent Scores
    # -------------------------------------------------------------------

    async def get_agent_scores(self, agent_id: Optional[str] = None) -> list[dict[str, Any]]:
        if agent_id:
            rows = await self.engine.fetch_all(
                "SELECT * FROM agent_scores WHERE agent_id = ?", [agent_id]
            )
        else:
            rows = await self.engine.fetch_all("SELECT * FROM agent_scores")
        return [dict(r) for r in rows]

    async def update_agent_score(
        self,
        agent_id: str,
        task_type: str,
        success: bool,
        duration_seconds: float = 0.0,
        quality_score: float = 0.0,
        cost_usd: float = 0.0,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        score_id = str(uuid.uuid4())

        # Upsert: update if exists, insert if not
        existing = await self.engine.fetch_one(
            "SELECT * FROM agent_scores WHERE agent_id = ? AND task_type = ?",
            [agent_id, task_type],
        )

        if existing:
            total = existing["total_attempts"] + 1
            new_avg_dur = (existing["avg_duration_seconds"] * existing["total_attempts"] + duration_seconds) / total
            new_avg_qual = (existing["avg_quality_score"] * existing["total_attempts"] + quality_score) / total
            new_avg_cost = (existing["avg_cost_usd"] * existing["total_attempts"] + cost_usd) / total

            await self.engine.execute(
                """UPDATE agent_scores SET
                   successes = successes + ?, failures = failures + ?,
                   total_attempts = total_attempts + 1,
                   avg_duration_seconds = ?, avg_quality_score = ?, avg_cost_usd = ?,
                   last_used_at = ?, updated_at = ?
                   WHERE agent_id = ? AND task_type = ?""",
                [
                    1 if success else 0,
                    0 if success else 1,
                    new_avg_dur, new_avg_qual, new_avg_cost,
                    now, now,
                    agent_id, task_type,
                ],
            )
        else:
            await self.engine.execute(
                """INSERT INTO agent_scores
                   (id, agent_id, task_type, successes, failures, total_attempts,
                    avg_duration_seconds, avg_quality_score, avg_cost_usd,
                    last_used_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)""",
                [
                    score_id, agent_id, task_type,
                    1 if success else 0,
                    0 if success else 1,
                    duration_seconds, quality_score, cost_usd,
                    now, now, now,
                ],
            )

    # -------------------------------------------------------------------
    # Mining Outcomes (RL model selection for mining pipeline)
    # -------------------------------------------------------------------

    async def record_mining_outcome(
        self,
        *,
        model_used: str,
        agent_id: str,
        brain: str,
        repo_name: str,
        repo_size_bytes: int,
        prompt_tokens_estimated: int,
        strategy: str,
        success: bool,
        findings_count: int,
        tokens_used: int,
        duration_seconds: float,
        error_type: str | None = None,
        error_detail: str | None = None,
    ) -> str:
        """Record a mining attempt outcome for RL learning."""
        outcome_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        await self.engine.execute(
            """INSERT INTO mining_outcomes
               (id, model_used, agent_id, brain, repo_name,
                repo_size_bytes, prompt_tokens_estimated, strategy,
                success, findings_count, tokens_used, duration_seconds,
                error_type, error_detail, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                outcome_id, model_used, agent_id, brain, repo_name,
                repo_size_bytes, prompt_tokens_estimated, strategy,
                1 if success else 0, findings_count, tokens_used,
                duration_seconds, error_type, error_detail, now,
            ],
        )
        return outcome_id

    async def get_mining_model_stats(
        self, min_observations: int = 3
    ) -> list[dict[str, Any]]:
        """Get per-model mining success rates grouped by size bucket.

        Size buckets: small (<50K tokens), medium (50K-200K), large (>200K).
        """
        rows = await self.engine.fetch_all(
            """SELECT
                 model_used,
                 CASE
                   WHEN prompt_tokens_estimated < 50000 THEN 'small'
                   WHEN prompt_tokens_estimated < 200000 THEN 'medium'
                   ELSE 'large'
                 END as size_bucket,
                 COUNT(*) as total,
                 SUM(success) as successes,
                 AVG(CASE WHEN success = 1 THEN findings_count ELSE NULL END) as avg_findings,
                 AVG(duration_seconds) as avg_duration_seconds
               FROM mining_outcomes
               GROUP BY model_used, size_bucket
               HAVING total >= ?
               ORDER BY model_used, size_bucket""",
            [min_observations],
        )
        return [dict(r) for r in rows]

    async def get_best_mining_model_for_size(
        self, estimated_tokens: int, min_observations: int = 3
    ) -> str | None:
        """Return the model with highest success rate for this token-size bucket.

        Returns None if insufficient data (cold start).
        """
        if estimated_tokens < 50000:
            condition = "prompt_tokens_estimated < 50000"
        elif estimated_tokens < 200000:
            condition = "prompt_tokens_estimated BETWEEN 50000 AND 200000"
        else:
            condition = "prompt_tokens_estimated > 200000"

        row = await self.engine.fetch_one(
            f"""SELECT model_used,
                      CAST(SUM(success) AS REAL) / COUNT(*) as success_rate,
                      COUNT(*) as total
               FROM mining_outcomes
               WHERE {condition}
               GROUP BY model_used
               HAVING total >= ?
               ORDER BY success_rate DESC, total DESC
               LIMIT 1""",
            [min_observations],
        )
        return row["model_used"] if row else None

    # -------------------------------------------------------------------
    # CLAW-specific: Prompt Variants
    # -------------------------------------------------------------------

    async def save_prompt_variant(
        self,
        prompt_name: str,
        variant_label: str,
        content: str,
        agent_id: Optional[str] = None,
        is_active: bool = False,
    ) -> str:
        variant_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        await self.engine.execute(
            """INSERT INTO prompt_variants
               (id, prompt_name, variant_label, content, agent_id, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [variant_id, prompt_name, variant_label, content, agent_id, 1 if is_active else 0, now, now],
        )
        return variant_id

    # -------------------------------------------------------------------
    # CLAW-specific: Fleet Repos
    # -------------------------------------------------------------------

    async def get_fleet_repos(self, status: Optional[str] = None) -> list[dict[str, Any]]:
        if status:
            rows = await self.engine.fetch_all(
                "SELECT * FROM fleet_repos WHERE status = ? ORDER BY priority DESC",
                [status],
            )
        else:
            rows = await self.engine.fetch_all(
                "SELECT * FROM fleet_repos ORDER BY priority DESC"
            )
        return [dict(r) for r in rows]

    # -------------------------------------------------------------------
    # CLAW-specific: Episodes
    # -------------------------------------------------------------------

    async def log_episode(
        self,
        session_id: str,
        event_type: str,
        event_data: dict[str, Any],
        project_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        task_id: Optional[str] = None,
        cycle_level: Optional[str] = None,
    ) -> str:
        episode_id = str(uuid.uuid4())
        await self.engine.execute(
            """INSERT INTO episodes
               (id, project_id, session_id, event_type, event_data, agent_id, task_id, cycle_level)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [episode_id, project_id, session_id, event_type, json.dumps(event_data), agent_id, task_id, cycle_level],
        )
        return episode_id

    async def record_quality_sample(
        self,
        *,
        project_id: str,
        task_id: str,
        variant_label: str,
        agent_id: Optional[str] = None,
        d_functional_correctness: float = 0.0,
        d_structural_compliance: float = 0.0,
        d_intent_alignment: float = 0.0,
        d_correction_efficiency: float = 0.0,
        d_token_economy: float = 0.0,
        d_expectation_match: float = 0.0,
        composite_score: float = 0.0,
        correction_attempts: int = 1,
        escalation_tier: int = 0,
        tokens_used: int = 0,
        duration_seconds: float = 0.0,
        success: bool = False,
        error_category: Optional[str] = None,
    ) -> str:
        """Record a multi-dimensional quality sample for A/B analysis."""
        sample_id = str(uuid.uuid4())
        await self.engine.execute(
            """INSERT INTO ab_quality_samples
               (id, project_id, task_id, variant_label, agent_id,
                d_functional_correctness, d_structural_compliance,
                d_intent_alignment, d_correction_efficiency,
                d_token_economy, d_expectation_match,
                composite_score, correction_attempts, escalation_tier,
                tokens_used, duration_seconds, success, error_category)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [sample_id, project_id, task_id, variant_label, agent_id,
             d_functional_correctness, d_structural_compliance,
             d_intent_alignment, d_correction_efficiency,
             d_token_economy, d_expectation_match,
             composite_score, correction_attempts, escalation_tier,
             tokens_used, duration_seconds, 1 if success else 0, error_category],
        )
        return sample_id

    # ------------------------------------------------------------------
    # Bandit: RL method selection stats
    # ------------------------------------------------------------------

    async def record_bandit_outcome(
        self, methodology_id: str, task_type: str, success: bool
    ) -> None:
        """Upsert a bandit outcome for (methodology, task_type)."""
        col = "successes" if success else "failures"
        await self.engine.execute(
            f"""INSERT INTO methodology_bandit_outcomes
                (methodology_id, task_type, {col}, last_updated)
                VALUES (?, ?, 1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                ON CONFLICT(methodology_id, task_type) DO UPDATE SET
                    {col} = {col} + 1,
                    last_updated = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            """,
            [methodology_id, task_type],
        )

    async def get_bandit_stats(
        self, methodology_id: str, task_type: str
    ) -> tuple[int, int]:
        """Return (successes, failures) for a methodology × task_type pair."""
        row = await self.engine.fetch_one(
            "SELECT successes, failures FROM methodology_bandit_outcomes "
            "WHERE methodology_id = ? AND task_type = ?",
            [methodology_id, task_type],
        )
        if row:
            return (row["successes"], row["failures"])
        return (0, 0)

    async def get_bandit_stats_batch(
        self, methodology_ids: list[str], task_type: str
    ) -> dict[str, tuple[int, int]]:
        """Batch fetch bandit stats for multiple methodologies."""
        if not methodology_ids:
            return {}
        placeholders = ",".join("?" for _ in methodology_ids)
        rows = await self.engine.fetch_all(
            f"SELECT methodology_id, successes, failures "
            f"FROM methodology_bandit_outcomes "
            f"WHERE methodology_id IN ({placeholders}) AND task_type = ?",
            [*methodology_ids, task_type],
        )
        return {r["methodology_id"]: (r["successes"], r["failures"]) for r in rows}

    async def get_task_content_failure_counts(
        self, task_id: str
    ) -> dict[str, int]:
        """Get content-failure counts per methodology for a task.

        Only counts failures where the stage is 'outcome_attributed' and
        success=0 (content failures, not infrastructure).
        """
        rows = await self.engine.fetch_all(
            """SELECT methodology_id, COUNT(*) as fail_count
               FROM methodology_usage_log
               WHERE task_id = ? AND stage = 'outcome_attributed' AND success = 0
               GROUP BY methodology_id""",
            [task_id],
        )
        return {r["methodology_id"]: r["fail_count"] for r in rows}

    async def get_bandit_summary(self) -> list[dict]:
        """Get bandit stats summary: top methodology x task_type pairs."""
        rows = await self.engine.fetch_all(
            """SELECT methodology_id, task_type, successes, failures,
                      (successes + failures) as total,
                      CASE WHEN (successes + failures) > 0
                           THEN ROUND(CAST(successes AS REAL) / (successes + failures), 3)
                           ELSE 0.0 END as win_rate,
                      CASE WHEN (successes + failures) >= 5 THEN 1 ELSE 0 END as thompson_graduated,
                      last_updated
               FROM methodology_bandit_outcomes
               ORDER BY (successes + failures) DESC
               LIMIT 50"""
        )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Coverage Analysis
    # ------------------------------------------------------------------

    async def get_coverage_matrix(self) -> dict[str, dict[str, int]]:
        """Live category x brain counts from active methodologies.

        Returns dict[category, dict[language, count]].  Categories are
        extracted from 'category:*' tags.  Language comes from the
        ``language`` column (NULL → 'unknown').
        """
        rows = await self.engine.fetch_all(
            """SELECT SUBSTR(je.value, 10) AS category,
                      COALESCE(m.language, 'unknown') AS lang,
                      COUNT(*) AS cnt
               FROM methodologies m, json_each(m.tags) je
               WHERE m.lifecycle_state NOT IN ('dead', 'dormant')
                 AND je.value LIKE 'category:%'
               GROUP BY category, lang"""
        )
        matrix: dict[str, dict[str, int]] = {}
        for r in rows:
            cat = r["category"]
            lang = r["lang"]
            matrix.setdefault(cat, {})[lang] = r["cnt"]
        return matrix

    async def save_coverage_snapshot(
        self,
        snapshot_id: str,
        snapshot_data: str,
        sparse_cells: str,
        total_methodologies: int,
    ) -> None:
        """Persist a coverage snapshot."""
        await self.engine.execute(
            """INSERT INTO coverage_snapshots
               (id, snapshot_data, sparse_cells, total_methodologies)
               VALUES (?, ?, ?, ?)""",
            [snapshot_id, snapshot_data, sparse_cells, total_methodologies],
        )

    async def get_latest_coverage_snapshot(self) -> Optional[dict[str, Any]]:
        """Return the most recent coverage snapshot, or None."""
        row = await self.engine.fetch_one(
            """SELECT id, snapshot_data, sparse_cells, total_methodologies, created_at
               FROM coverage_snapshots
               ORDER BY created_at DESC
               LIMIT 1"""
        )
        return dict(row) if row else None

    async def get_coverage_trend(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return the last N coverage snapshots (newest first)."""
        rows = await self.engine.fetch_all(
            """SELECT id, snapshot_data, sparse_cells, total_methodologies, created_at
               FROM coverage_snapshots
               ORDER BY created_at DESC
               LIMIT ?""",
            [limit],
        )
        return [dict(r) for r in rows]

    async def reclassify_methodologies(
        self,
        methodology_ids: list[str],
        old_category: str,
        new_category: str,
    ) -> int:
        """Batch re-tag methodologies from one category to another.

        Updates the JSON tags array, replacing 'category:{old}' with 'category:{new}'.
        Returns count of updated rows.
        """
        updated = 0
        old_tag = f"category:{old_category}"
        new_tag = f"category:{new_category}"
        for mid in methodology_ids:
            row = await self.engine.fetch_one(
                "SELECT tags FROM methodologies WHERE id = ?", [mid]
            )
            if not row:
                continue
            tags_raw = row["tags"]
            try:
                tags = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
            except (json.JSONDecodeError, TypeError):
                continue
            if old_tag in tags:
                tags = [new_tag if t == old_tag else t for t in tags]
                await self.engine.execute(
                    "UPDATE methodologies SET tags = ? WHERE id = ?",
                    [json.dumps(tags), mid],
                )
                updated += 1
        return updated


# ---------------------------------------------------------------------------
# Row → Model converters
# ---------------------------------------------------------------------------

    # -------------------------------------------------------------------
    # CAM-SEQ additive entities
    # -------------------------------------------------------------------

    async def save_component_lineage(self, lineage: ComponentLineage) -> ComponentLineage:
        await self.engine.execute(
            """INSERT INTO component_lineages
               (id, family_barcode, canonical_content_hash, canonical_title, language,
                lineage_size, deduped_support_count, clone_inflated, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                lineage.id,
                lineage.family_barcode,
                lineage.canonical_content_hash,
                lineage.canonical_title,
                lineage.language,
                lineage.lineage_size,
                lineage.deduped_support_count,
                int(lineage.clone_inflated),
                lineage.created_at.isoformat(),
                lineage.updated_at.isoformat(),
            ],
        )
        return lineage

    async def upsert_component_lineage(self, lineage: ComponentLineage) -> ComponentLineage:
        await self.engine.execute(
            """INSERT INTO component_lineages
               (id, family_barcode, canonical_content_hash, canonical_title, language,
                lineage_size, deduped_support_count, clone_inflated, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   family_barcode = excluded.family_barcode,
                   canonical_content_hash = excluded.canonical_content_hash,
                   canonical_title = excluded.canonical_title,
                   language = excluded.language,
                   lineage_size = excluded.lineage_size,
                   deduped_support_count = excluded.deduped_support_count,
                   clone_inflated = excluded.clone_inflated,
                   updated_at = excluded.updated_at""",
            [
                lineage.id,
                lineage.family_barcode,
                lineage.canonical_content_hash,
                lineage.canonical_title,
                lineage.language,
                lineage.lineage_size,
                lineage.deduped_support_count,
                int(lineage.clone_inflated),
                lineage.created_at.isoformat(),
                lineage.updated_at.isoformat(),
            ],
        )
        return lineage

    async def get_component_lineage(self, lineage_id: str) -> Optional[ComponentLineage]:
        row = await self.engine.fetch_one(
            "SELECT * FROM component_lineages WHERE id = ?", [lineage_id]
        )
        return _row_to_component_lineage(row) if row else None

    async def find_lineage_by_hash(self, canonical_content_hash: str) -> Optional[ComponentLineage]:
        row = await self.engine.fetch_one(
            "SELECT * FROM component_lineages WHERE canonical_content_hash = ? LIMIT 1",
            [canonical_content_hash],
        )
        return _row_to_component_lineage(row) if row else None

    async def list_lineage_components(
        self, lineage_id: str, limit: int = 100
    ) -> list[ComponentCardSummary]:
        rows = await self.engine.fetch_all(
            """SELECT * FROM component_cards
               WHERE lineage_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            [lineage_id, limit],
        )
        return [_row_to_component_card_summary(r) for r in rows]

    async def save_component_card(self, card: ComponentCard) -> ComponentCard:
        receipt = card.receipt
        await self.engine.execute(
            """INSERT INTO component_cards
               (id, methodology_id, lineage_id, source_barcode, family_barcode, title,
                component_type, abstract_jobs_json, repo, commit_sha, file_path, symbol_name,
                line_start, line_end, content_hash, provenance_precision, language,
                frameworks_json, dependencies_json, constraints_json, inputs_json, outputs_json,
                test_evidence_json, applicability_json, non_applicability_json,
                adaptation_notes_json, risk_notes_json, keywords_json, coverage_state,
                success_count, failure_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                card.id,
                card.methodology_id,
                receipt.lineage_id,
                receipt.source_barcode,
                receipt.family_barcode,
                card.title,
                card.component_type,
                _json_dumps(card.abstract_jobs),
                receipt.repo,
                receipt.commit,
                receipt.file_path,
                receipt.symbol,
                receipt.line_start,
                receipt.line_end,
                receipt.content_hash,
                receipt.provenance_precision.value,
                card.language,
                _json_dumps(card.frameworks),
                _json_dumps(card.dependencies),
                _json_dumps(card.constraints),
                _json_dumps(card.inputs),
                _json_dumps(card.outputs),
                _json_dumps(card.test_evidence),
                _json_dumps(card.applicability),
                _json_dumps(card.non_applicability),
                _json_dumps(card.adaptation_notes),
                _json_dumps(card.risk_notes),
                _json_dumps(card.keywords),
                card.coverage_state.value,
                card.success_count,
                card.failure_count,
                card.created_at.isoformat(),
                card.updated_at.isoformat(),
            ],
        )
        return card

    async def upsert_component_card(self, card: ComponentCard) -> ComponentCard:
        receipt = card.receipt
        await self.engine.execute(
            """INSERT INTO component_cards
               (id, methodology_id, lineage_id, source_barcode, family_barcode, title,
                component_type, abstract_jobs_json, repo, commit_sha, file_path, symbol_name,
                line_start, line_end, content_hash, provenance_precision, language,
                frameworks_json, dependencies_json, constraints_json, inputs_json, outputs_json,
                test_evidence_json, applicability_json, non_applicability_json,
                adaptation_notes_json, risk_notes_json, keywords_json, coverage_state,
                success_count, failure_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source_barcode) DO UPDATE SET
                   methodology_id = excluded.methodology_id,
                   lineage_id = excluded.lineage_id,
                   family_barcode = excluded.family_barcode,
                   title = excluded.title,
                   component_type = excluded.component_type,
                   abstract_jobs_json = excluded.abstract_jobs_json,
                   repo = excluded.repo,
                   commit_sha = excluded.commit_sha,
                   file_path = excluded.file_path,
                   symbol_name = excluded.symbol_name,
                   line_start = excluded.line_start,
                   line_end = excluded.line_end,
                   content_hash = excluded.content_hash,
                   provenance_precision = excluded.provenance_precision,
                   language = excluded.language,
                   frameworks_json = excluded.frameworks_json,
                   dependencies_json = excluded.dependencies_json,
                   constraints_json = excluded.constraints_json,
                   inputs_json = excluded.inputs_json,
                   outputs_json = excluded.outputs_json,
                   test_evidence_json = excluded.test_evidence_json,
                   applicability_json = excluded.applicability_json,
                   non_applicability_json = excluded.non_applicability_json,
                   adaptation_notes_json = excluded.adaptation_notes_json,
                   risk_notes_json = excluded.risk_notes_json,
                   keywords_json = excluded.keywords_json,
                   coverage_state = excluded.coverage_state,
                   success_count = excluded.success_count,
                   failure_count = excluded.failure_count,
                   updated_at = excluded.updated_at""",
            [
                card.id,
                card.methodology_id,
                receipt.lineage_id,
                receipt.source_barcode,
                receipt.family_barcode,
                card.title,
                card.component_type,
                _json_dumps(card.abstract_jobs),
                receipt.repo,
                receipt.commit,
                receipt.file_path,
                receipt.symbol,
                receipt.line_start,
                receipt.line_end,
                receipt.content_hash,
                receipt.provenance_precision.value,
                card.language,
                _json_dumps(card.frameworks),
                _json_dumps(card.dependencies),
                _json_dumps(card.constraints),
                _json_dumps(card.inputs),
                _json_dumps(card.outputs),
                _json_dumps(card.test_evidence),
                _json_dumps(card.applicability),
                _json_dumps(card.non_applicability),
                _json_dumps(card.adaptation_notes),
                _json_dumps(card.risk_notes),
                _json_dumps(card.keywords),
                card.coverage_state.value,
                card.success_count,
                card.failure_count,
                card.created_at.isoformat(),
                card.updated_at.isoformat(),
            ],
        )
        row = await self.engine.fetch_one(
            "SELECT * FROM component_cards WHERE source_barcode = ?",
            [receipt.source_barcode],
        )
        return _row_to_component_card(row) if row else card

    async def find_component_by_source_barcode(self, source_barcode: str) -> Optional[ComponentCard]:
        row = await self.engine.fetch_one(
            "SELECT * FROM component_cards WHERE source_barcode = ?",
            [source_barcode],
        )
        return _row_to_component_card(row) if row else None

    async def get_component_card(self, component_id: str) -> Optional[ComponentCard]:
        row = await self.engine.fetch_one(
            "SELECT * FROM component_cards WHERE id = ?", [component_id]
        )
        return _row_to_component_card(row) if row else None

    async def list_component_cards(
        self, limit: int = 100, language: Optional[str] = None
    ) -> list[ComponentCardSummary]:
        if language:
            rows = await self.engine.fetch_all(
                """SELECT * FROM component_cards
                   WHERE language = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                [language, limit],
            )
        else:
            rows = await self.engine.fetch_all(
                """SELECT * FROM component_cards
                   ORDER BY created_at DESC
                   LIMIT ?""",
                [limit],
            )
        return [_row_to_component_card_summary(r) for r in rows]

    async def list_component_cards_full(
        self, limit: int = 100, language: Optional[str] = None
    ) -> list[ComponentCard]:
        """Return full ComponentCard objects (used by component ranker)."""
        if language:
            rows = await self.engine.fetch_all(
                """SELECT * FROM component_cards
                   WHERE language = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                [language, limit],
            )
        else:
            rows = await self.engine.fetch_all(
                """SELECT * FROM component_cards
                   ORDER BY created_at DESC
                   LIMIT ?""",
                [limit],
            )
        return [_row_to_component_card(r) for r in rows]

    async def list_components_for_methodology(
        self, methodology_id: str
    ) -> list[ComponentCardSummary]:
        rows = await self.engine.fetch_all(
            """SELECT * FROM component_cards
               WHERE methodology_id = ?
               ORDER BY created_at DESC""",
            [methodology_id],
        )
        return [_row_to_component_card_summary(r) for r in rows]

    async def search_component_cards_text(
        self, query: str, limit: int = 20, language: Optional[str] = None
    ) -> list[ComponentCardSummary]:
        tokens = re.findall(r"[A-Za-z0-9_]+", query.lower())
        if not tokens:
            return []
        clauses: list[str] = []
        params: list[Any] = []
        for token in tokens:
            like = f"%{token}%"
            clauses.append(
                "(lower(title) LIKE ? OR lower(component_type) LIKE ? OR lower(file_path) LIKE ? "
                "OR lower(COALESCE(symbol_name, '')) LIKE ? OR lower(abstract_jobs_json) LIKE ? "
                "OR lower(keywords_json) LIKE ? OR lower(applicability_json) LIKE ?)"
            )
            params.extend([like, like, like, like, like, like, like])

        sql = "SELECT * FROM component_cards WHERE (" + " OR ".join(clauses) + ")"
        if language:
            sql += " AND language = ?"
            params.append(language)
        sql += " ORDER BY success_count DESC, created_at DESC LIMIT ?"
        params.append(limit)

        rows = await self.engine.fetch_all(sql, params)
        return [_row_to_component_card_summary(r) for r in rows]

    async def update_component_outcome(self, component_id: str, success: bool) -> None:
        if success:
            await self.engine.execute(
                "UPDATE component_cards SET success_count = success_count + 1 WHERE id = ?",
                [component_id],
            )
        else:
            await self.engine.execute(
                "UPDATE component_cards SET failure_count = failure_count + 1 WHERE id = ?",
                [component_id],
            )

    async def save_component_fit(self, fit: ComponentFit) -> ComponentFit:
        await self.engine.execute(
            """INSERT INTO component_fit
               (id, component_id, task_archetype, component_type, slot_signature,
                fit_bucket, transfer_mode, confidence, confidence_basis_json,
                success_count, failure_count, evidence_count, notes_json, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                fit.id,
                fit.component_id,
                fit.task_archetype,
                fit.component_type,
                fit.slot_signature,
                fit.fit_bucket.value,
                fit.transfer_mode.value,
                fit.confidence,
                _json_dumps(fit.confidence_basis),
                fit.success_count,
                fit.failure_count,
                fit.evidence_count,
                _json_dumps(fit.notes),
                fit.updated_at.isoformat(),
            ],
        )
        return fit

    async def list_component_fit(self, component_id: str) -> list[ComponentFit]:
        rows = await self.engine.fetch_all(
            """SELECT * FROM component_fit
               WHERE component_id = ?
               ORDER BY updated_at DESC""",
            [component_id],
        )
        return [_row_to_component_fit(r) for r in rows]

    async def find_component_fit(
        self,
        task_archetype: Optional[str],
        slot_signature: Optional[str],
        component_type: Optional[str],
        limit: int = 20,
    ) -> list[ComponentFit]:
        clauses = ["1=1"]
        params: list[Any] = []
        if task_archetype:
            clauses.append("task_archetype = ?")
            params.append(task_archetype)
        if slot_signature:
            clauses.append("slot_signature = ?")
            params.append(slot_signature)
        if component_type:
            clauses.append("component_type = ?")
            params.append(component_type)
        params.append(limit)
        rows = await self.engine.fetch_all(
            f"""SELECT * FROM component_fit
                WHERE {' AND '.join(clauses)}
                ORDER BY confidence DESC, evidence_count DESC
                LIMIT ?""",
            params,
        )
        return [_row_to_component_fit(r) for r in rows]

    async def save_task_plan(self, plan: TaskPlanRecord) -> TaskPlanRecord:
        await self.engine.execute(
            """INSERT INTO task_plans
               (id, task_text, workspace_dir, branch, target_brain, execution_mode,
                check_commands_json, task_archetype, archetype_confidence, status,
                summary_json, approved_slot_ids_json, plan_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   task_text = excluded.task_text,
                   workspace_dir = excluded.workspace_dir,
                   branch = excluded.branch,
                   target_brain = excluded.target_brain,
                   execution_mode = excluded.execution_mode,
                   check_commands_json = excluded.check_commands_json,
                   task_archetype = excluded.task_archetype,
                   archetype_confidence = excluded.archetype_confidence,
                   status = excluded.status,
                   summary_json = excluded.summary_json,
                   approved_slot_ids_json = excluded.approved_slot_ids_json,
                   plan_json = excluded.plan_json,
                   updated_at = excluded.updated_at""",
            [
                plan.id,
                plan.task_text,
                plan.workspace_dir,
                plan.branch,
                plan.target_brain,
                plan.execution_mode,
                _json_dumps(plan.check_commands),
                plan.task_archetype,
                plan.archetype_confidence,
                plan.status,
                _json_dumps(plan.summary),
                _json_dumps(plan.approved_slot_ids),
                _json_dumps(plan.plan_json),
                plan.created_at.isoformat(),
                plan.updated_at.isoformat(),
            ],
        )
        row = await self.engine.fetch_one("SELECT * FROM task_plans WHERE id = ?", [plan.id])
        return _row_to_task_plan_record(row) if row else plan

    async def get_task_plan(self, plan_id: str) -> Optional[TaskPlanRecord]:
        row = await self.engine.fetch_one("SELECT * FROM task_plans WHERE id = ?", [plan_id])
        return _row_to_task_plan_record(row) if row else None

    async def save_slot_instance(self, slot: SlotSpec, task_archetype: Optional[str] = None) -> SlotSpec:
        await self.engine.execute(
            """INSERT INTO slot_instances
               (id, slot_barcode, task_archetype, name, abstract_job, risk,
                constraints_json, target_stack_json, proof_expectations_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   slot_barcode = excluded.slot_barcode,
                   task_archetype = excluded.task_archetype,
                   name = excluded.name,
                   abstract_job = excluded.abstract_job,
                   risk = excluded.risk,
                   constraints_json = excluded.constraints_json,
                   target_stack_json = excluded.target_stack_json,
                   proof_expectations_json = excluded.proof_expectations_json""",
            [
                slot.slot_id,
                slot.slot_barcode,
                task_archetype,
                slot.name,
                slot.abstract_job,
                slot.risk.value,
                _json_dumps(slot.constraints),
                _json_dumps(slot.target_stack),
                _json_dumps(slot.proof_expectations),
            ],
        )
        return slot

    async def save_application_packet(self, packet: ApplicationPacket) -> None:
        await self.engine.execute(
            """INSERT INTO application_packets
               (id, schema_version, plan_id, task_archetype, slot_id, status, packet_json,
                selected_component_id, review_required, coverage_state, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   schema_version = excluded.schema_version,
                   task_archetype = excluded.task_archetype,
                   status = excluded.status,
                   packet_json = excluded.packet_json,
                   selected_component_id = excluded.selected_component_id,
                   review_required = excluded.review_required,
                   coverage_state = excluded.coverage_state,
                   updated_at = excluded.updated_at""",
            [
                packet.packet_id,
                packet.schema_version,
                packet.plan_id,
                packet.task_archetype,
                packet.slot.slot_id,
                packet.status.value,
                _json_dumps(_model_dump(packet)),
                packet.selected.component_id,
                int(packet.reviewer_required),
                packet.coverage_state.value,
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
            ],
        )

    async def get_application_packet(self, packet_id: str) -> Optional[ApplicationPacket]:
        row = await self.engine.fetch_one(
            "SELECT packet_json FROM application_packets WHERE id = ?",
            [packet_id],
        )
        if row is None:
            return None
        raw = _json_loads(row["packet_json"], {})
        return ApplicationPacket.model_validate(raw) if raw else None

    async def list_packets_for_plan(self, plan_id: str) -> list[ApplicationPacketSummary]:
        rows = await self.engine.fetch_all(
            """SELECT * FROM application_packets
               WHERE plan_id = ?
               ORDER BY created_at ASC""",
            [plan_id],
        )
        return [_row_to_application_packet_summary(r) for r in rows]

    async def list_packet_history_for_component(
        self, component_id: str, limit: int = 50
    ) -> list[ApplicationPacketSummary]:
        rows = await self.engine.fetch_all(
            """SELECT * FROM application_packets
               WHERE selected_component_id = ?
               ORDER BY updated_at DESC
               LIMIT ?""",
            [component_id, limit],
        )
        return [_row_to_application_packet_summary(r) for r in rows]

    async def save_pair_event(self, event: PairEvent) -> PairEvent:
        await self.engine.execute(
            """INSERT INTO pair_events
               (id, run_id, slot_id, slot_barcode, packet_id, component_id,
                source_barcode, confidence, confidence_basis_json, replacement_of_pair_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                event.id,
                event.run_id,
                event.slot_id,
                event.slot_barcode,
                event.packet_id,
                event.component_id,
                event.source_barcode,
                event.confidence,
                _json_dumps(event.confidence_basis),
                event.replacement_of_pair_id,
                event.created_at.isoformat(),
            ],
        )
        return event

    async def save_landing_event(self, event: LandingEvent) -> LandingEvent:
        await self.engine.execute(
            """INSERT INTO landing_events
               (id, run_id, slot_id, packet_id, file_path, symbol_name, diff_hunk_id, origin, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                event.id,
                event.run_id,
                event.slot_id,
                event.packet_id,
                event.file_path,
                event.symbol,
                event.diff_hunk_id,
                event.origin.value,
                event.created_at.isoformat(),
            ],
        )
        return event

    async def save_outcome_event(self, event: OutcomeEvent) -> OutcomeEvent:
        await self.engine.execute(
            """INSERT INTO outcome_events
               (id, run_id, slot_id, packet_id, success, verifier_findings_json,
                test_refs_json, negative_memory_updates_json, recipe_eligible, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                event.id,
                event.run_id,
                event.slot_id,
                event.packet_id,
                int(event.success),
                _json_dumps(event.verifier_findings),
                _json_dumps(event.test_refs),
                _json_dumps(event.negative_memory_updates),
                int(event.recipe_eligible),
                event.created_at.isoformat(),
            ],
        )
        return event

    async def list_run_pair_events(self, run_id: str) -> list[PairEvent]:
        rows = await self.engine.fetch_all(
            "SELECT * FROM pair_events WHERE run_id = ? ORDER BY created_at ASC",
            [run_id],
        )
        return [_row_to_pair_event(r) for r in rows]

    async def list_run_landing_events(self, run_id: str) -> list[LandingEvent]:
        rows = await self.engine.fetch_all(
            "SELECT * FROM landing_events WHERE run_id = ? ORDER BY created_at ASC",
            [run_id],
        )
        return [_row_to_landing_event(r) for r in rows]

    async def list_run_outcome_events(self, run_id: str) -> list[OutcomeEvent]:
        rows = await self.engine.fetch_all(
            "SELECT * FROM outcome_events WHERE run_id = ? ORDER BY created_at ASC",
            [run_id],
        )
        return [_row_to_outcome_event(r) for r in rows]

    async def save_run_connectome(self, connectome: RunConnectome) -> RunConnectome:
        await self.engine.execute(
            """INSERT INTO run_connectomes (id, run_id, task_archetype, status, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(run_id) DO UPDATE SET
                   task_archetype = excluded.task_archetype,
                   status = excluded.status""",
            [
                connectome.id,
                connectome.run_id,
                connectome.task_archetype,
                connectome.status,
                connectome.created_at.isoformat(),
            ],
        )
        row = await self.engine.fetch_one(
            "SELECT * FROM run_connectomes WHERE run_id = ?",
            [connectome.run_id],
        )
        return _row_to_run_connectome(row) if row else connectome

    async def get_run_connectome(self, run_id: str) -> Optional[RunConnectome]:
        row = await self.engine.fetch_one(
            "SELECT * FROM run_connectomes WHERE run_id = ?",
            [run_id],
        )
        return _row_to_run_connectome(row) if row else None

    async def save_run_slot_execution(self, execution: RunSlotExecution) -> RunSlotExecution:
        await self.engine.execute(
            """INSERT INTO run_slot_executions
               (id, run_id, slot_id, packet_id, selected_component_id, status, current_step,
                retry_count, last_retry_detail, replacement_count, blocked_wait_ms, family_wait_ms, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(run_id, slot_id) DO UPDATE SET
                   packet_id = excluded.packet_id,
                   selected_component_id = excluded.selected_component_id,
                   status = excluded.status,
                   current_step = excluded.current_step,
                   retry_count = excluded.retry_count,
                   last_retry_detail = excluded.last_retry_detail,
                   replacement_count = excluded.replacement_count,
                   blocked_wait_ms = excluded.blocked_wait_ms,
                   family_wait_ms = excluded.family_wait_ms,
                   updated_at = excluded.updated_at""",
            [
                execution.id,
                execution.run_id,
                execution.slot_id,
                execution.packet_id,
                execution.selected_component_id,
                execution.status,
                execution.current_step,
                execution.retry_count,
                execution.last_retry_detail,
                execution.replacement_count,
                execution.blocked_wait_ms,
                execution.family_wait_ms,
                execution.created_at.isoformat(),
                execution.updated_at.isoformat(),
            ],
        )
        row = await self.engine.fetch_one(
            "SELECT * FROM run_slot_executions WHERE run_id = ? AND slot_id = ?",
            [execution.run_id, execution.slot_id],
        )
        return _row_to_run_slot_execution(row) if row else execution

    async def list_run_slot_executions(self, run_id: str) -> list[RunSlotExecution]:
        rows = await self.engine.fetch_all(
            """SELECT * FROM run_slot_executions
               WHERE run_id = ?
               ORDER BY created_at ASC, updated_at ASC""",
            [run_id],
        )
        return [_row_to_run_slot_execution(r) for r in rows]

    async def save_run_event(self, event: RunEvent) -> RunEvent:
        await self.engine.execute(
            """INSERT INTO run_events
               (id, run_id, slot_id, event_type, payload_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                event.id,
                event.run_id,
                event.slot_id,
                event.event_type,
                _json_dumps(event.payload),
                event.created_at.isoformat(),
            ],
        )
        return event

    async def list_run_events(self, run_id: str) -> list[RunEvent]:
        rows = await self.engine.fetch_all(
            """SELECT * FROM run_events
               WHERE run_id = ?
               ORDER BY created_at ASC""",
            [run_id],
        )
        return [_row_to_run_event(r) for r in rows]

    async def save_run_action_audit(self, audit: RunActionAudit) -> RunActionAudit:
        await self.engine.execute(
            """INSERT INTO run_action_audits
               (id, run_id, slot_id, action_type, actor, reason, action_payload_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                audit.id,
                audit.run_id,
                audit.slot_id,
                audit.action_type,
                audit.actor,
                audit.reason,
                _json_dumps(audit.action_payload),
                audit.created_at.isoformat(),
            ],
        )
        return audit

    async def list_run_action_audits(self, run_id: str) -> list[RunActionAudit]:
        rows = await self.engine.fetch_all(
            """SELECT * FROM run_action_audits
               WHERE run_id = ?
               ORDER BY created_at ASC""",
            [run_id],
        )
        return [_row_to_run_action_audit(r) for r in rows]

    async def save_run_connectome_edge(
        self,
        connectome_id: str,
        source_node: str,
        target_node: str,
        edge_type: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        edge_id = str(uuid.uuid4())
        await self.engine.execute(
            """INSERT INTO run_connectome_edges
               (id, connectome_id, source_node, target_node, edge_type, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [edge_id, connectome_id, source_node, target_node, edge_type, _json_dumps(metadata or {})],
        )
        return edge_id

    async def list_run_connectome_edges(self, connectome_id: str) -> list[dict[str, Any]]:
        rows = await self.engine.fetch_all(
            """SELECT * FROM run_connectome_edges
               WHERE connectome_id = ?""",
            [connectome_id],
        )
        return [dict(r) for r in rows]

    async def save_compiled_recipe(self, recipe: CompiledRecipe) -> CompiledRecipe:
        await self.engine.execute(
            """INSERT INTO compiled_recipes
               (id, task_archetype, recipe_name, recipe_json, sample_size, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   task_archetype = excluded.task_archetype,
                   recipe_name = excluded.recipe_name,
                   recipe_json = excluded.recipe_json,
                   sample_size = excluded.sample_size,
                   is_active = excluded.is_active,
                   updated_at = excluded.updated_at""",
            [
                recipe.id,
                recipe.task_archetype,
                recipe.recipe_name,
                _json_dumps(recipe.recipe_json),
                recipe.sample_size,
                int(recipe.is_active),
                recipe.created_at.isoformat(),
                recipe.updated_at.isoformat(),
            ],
        )
        row = await self.engine.fetch_one("SELECT * FROM compiled_recipes WHERE id = ?", [recipe.id])
        return _row_to_compiled_recipe(row) if row else recipe

    async def get_compiled_recipe(self, recipe_id: str) -> Optional[CompiledRecipe]:
        row = await self.engine.fetch_one("SELECT * FROM compiled_recipes WHERE id = ?", [recipe_id])
        return _row_to_compiled_recipe(row) if row else None

    async def list_compiled_recipes(
        self,
        task_archetype: Optional[str] = None,
        active_only: bool = False,
        limit: int = 50,
    ) -> list[CompiledRecipe]:
        clauses = ["1=1"]
        params: list[Any] = []
        if task_archetype:
            clauses.append("task_archetype = ?")
            params.append(task_archetype)
        if active_only:
            clauses.append("is_active = 1")
        params.append(limit)
        rows = await self.engine.fetch_all(
            f"""SELECT * FROM compiled_recipes
                WHERE {' AND '.join(clauses)}
                ORDER BY updated_at DESC
                LIMIT ?""",
            params,
        )
        return [_row_to_compiled_recipe(r) for r in rows]

    async def save_mining_mission(self, mission: MiningMission) -> MiningMission:
        await self.engine.execute(
            """INSERT INTO mining_missions
               (id, run_id, slot_family, priority, reason, status, mission_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   run_id = excluded.run_id,
                   slot_family = excluded.slot_family,
                   priority = excluded.priority,
                   reason = excluded.reason,
                   status = excluded.status,
                   mission_json = excluded.mission_json,
                   updated_at = excluded.updated_at""",
            [
                mission.id,
                mission.run_id,
                mission.slot_family,
                mission.priority,
                mission.reason,
                mission.status,
                _json_dumps(mission.mission_json),
                mission.created_at.isoformat(),
                mission.updated_at.isoformat(),
            ],
        )
        row = await self.engine.fetch_one("SELECT * FROM mining_missions WHERE id = ?", [mission.id])
        return _row_to_mining_mission(row) if row else mission

    async def list_mining_missions(
        self,
        run_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list[MiningMission]:
        clauses = ["1=1"]
        params: list[Any] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        params.append(limit)
        rows = await self.engine.fetch_all(
            f"""SELECT * FROM mining_missions
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC
                LIMIT ?""",
            params,
        )
        return [_row_to_mining_mission(r) for r in rows]

    async def save_governance_policy(self, policy: GovernancePolicy) -> GovernancePolicy:
        await self.engine.execute(
            """INSERT INTO governance_policies
               (id, run_id, task_archetype, slot_id, family_barcode, policy_kind, severity, status,
                reason, recommendation, evidence_json, promoted_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   run_id = excluded.run_id,
                   task_archetype = excluded.task_archetype,
                   slot_id = excluded.slot_id,
                   family_barcode = excluded.family_barcode,
                   policy_kind = excluded.policy_kind,
                   severity = excluded.severity,
                   status = excluded.status,
                   reason = excluded.reason,
                   recommendation = excluded.recommendation,
                   evidence_json = excluded.evidence_json,
                   promoted_by = excluded.promoted_by,
                   updated_at = excluded.updated_at""",
            [
                policy.id,
                policy.run_id,
                policy.task_archetype,
                policy.slot_id,
                policy.family_barcode,
                policy.policy_kind,
                policy.severity,
                policy.status,
                policy.reason,
                policy.recommendation,
                _json_dumps(policy.evidence_json),
                policy.promoted_by,
                policy.created_at.isoformat(),
                policy.updated_at.isoformat(),
            ],
        )
        row = await self.engine.fetch_one(
            "SELECT * FROM governance_policies WHERE id = ?",
            [policy.id],
        )
        return _row_to_governance_policy(row) if row else policy

    async def list_governance_policies(
        self,
        *,
        task_archetype: Optional[str] = None,
        active_only: bool = False,
        limit: int = 100,
    ) -> list[GovernancePolicy]:
        clauses = ["1=1"]
        params: list[Any] = []
        if task_archetype:
            clauses.append("task_archetype = ?")
            params.append(task_archetype)
        if active_only:
            clauses.append("status = 'active'")
        params.append(limit)
        rows = await self.engine.fetch_all(
            f"""SELECT * FROM governance_policies
                WHERE {' AND '.join(clauses)}
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ?""",
            params,
        )
        return [_row_to_governance_policy(r) for r in rows]

    async def get_governance_policy(self, policy_id: str) -> Optional[GovernancePolicy]:
        row = await self.engine.fetch_one(
            "SELECT * FROM governance_policies WHERE id = ?",
            [policy_id],
        )
        return _row_to_governance_policy(row) if row else None


def _row_to_project(row: dict[str, Any]) -> Project:
    tech_stack = row.get("tech_stack", "{}")
    if isinstance(tech_stack, str):
        tech_stack = json.loads(tech_stack)
    banned = row.get("banned_dependencies", "[]")
    if isinstance(banned, str):
        banned = json.loads(banned)
    return Project(
        id=row["id"],
        name=row["name"],
        repo_path=row["repo_path"],
        tech_stack=tech_stack,
        project_rules=row.get("project_rules"),
        banned_dependencies=banned,
        created_at=_parse_dt(row.get("created_at")),
        updated_at=_parse_dt(row.get("updated_at")),
    )


def _row_to_task(row: dict[str, Any]) -> Task:
    execution_steps = row.get("execution_steps", "[]")
    if isinstance(execution_steps, str):
        execution_steps = json.loads(execution_steps)

    acceptance_checks = row.get("acceptance_checks", "[]")
    if isinstance(acceptance_checks, str):
        acceptance_checks = json.loads(acceptance_checks)

    excluded_agents = row.get("excluded_agents", "[]")
    if isinstance(excluded_agents, str):
        excluded_agents = json.loads(excluded_agents)

    return Task(
        id=row["id"],
        project_id=row["project_id"],
        title=row["title"],
        description=row["description"],
        status=TaskStatus(row["status"]),
        priority=row.get("priority", 0),
        task_type=row.get("task_type"),
        recommended_agent=row.get("recommended_agent"),
        assigned_agent=row.get("assigned_agent"),
        action_template_id=row.get("action_template_id"),
        execution_steps=execution_steps,
        acceptance_checks=acceptance_checks,
        context_snapshot_id=row.get("context_snapshot_id"),
        attempt_count=row.get("attempt_count", 0),
        escalation_count=row.get("escalation_count", 0),
        excluded_agents=excluded_agents,
        created_at=_parse_dt(row.get("created_at")),
        updated_at=_parse_dt(row.get("updated_at")),
        completed_at=_parse_dt(row.get("completed_at")),
    )


def _row_to_hypothesis(row: dict[str, Any]) -> HypothesisEntry:
    files = row.get("files_changed", "[]")
    if isinstance(files, str):
        files = json.loads(files)
    return HypothesisEntry(
        id=row["id"],
        task_id=row["task_id"],
        attempt_number=row["attempt_number"],
        approach_summary=row["approach_summary"],
        outcome=HypothesisOutcome(row["outcome"]),
        error_signature=row.get("error_signature"),
        error_full=row.get("error_full"),
        files_changed=files,
        duration_seconds=row.get("duration_seconds"),
        model_used=row.get("model_used"),
        agent_id=row.get("agent_id"),
        created_at=_parse_dt(row.get("created_at")),
    )


def _row_to_methodology(row: dict[str, Any]) -> Methodology:
    tags = row.get("tags", "[]")
    if isinstance(tags, str):
        tags = json.loads(tags)
    files = row.get("files_affected", "[]")
    if isinstance(files, str):
        files = json.loads(files)
    fv = row.get("fitness_vector", "{}")
    if isinstance(fv, str):
        fv = json.loads(fv)
    parents = row.get("parent_ids", "[]")
    if isinstance(parents, str):
        parents = json.loads(parents)

    raw_prism = row.get("prism_data")
    prism_data = json.loads(raw_prism) if isinstance(raw_prism, str) else None

    raw_cap = row.get("capability_data")
    capability_data = json.loads(raw_cap) if isinstance(raw_cap, str) else None

    use_imm = row.get("use_immediately_as", "[]")
    if isinstance(use_imm, str):
        use_imm = json.loads(use_imm)
    tension_q = row.get("tension_questions", "[]")
    if isinstance(tension_q, str):
        tension_q = json.loads(tension_q)

    return Methodology(
        id=row["id"],
        problem_description=row["problem_description"],
        solution_code=row["solution_code"],
        methodology_notes=row.get("methodology_notes"),
        source_task_id=row.get("source_task_id"),
        tags=tags,
        language=row.get("language"),
        scope=row.get("scope", "project"),
        methodology_type=row.get("methodology_type"),
        files_affected=files,
        created_at=_parse_dt(row.get("created_at")),
        lifecycle_state=row.get("lifecycle_state", "viable"),
        retrieval_count=row.get("retrieval_count", 0),
        success_count=row.get("success_count", 0),
        failure_count=row.get("failure_count", 0),
        last_retrieved_at=_parse_dt(row.get("last_retrieved_at")),
        generation=row.get("generation", 0),
        fitness_vector=fv,
        parent_ids=parents,
        superseded_by=row.get("superseded_by"),
        prism_data=prism_data,
        capability_data=capability_data,
        novelty_score=row.get("novelty_score"),
        potential_score=row.get("potential_score"),
        accuracy_contract=row.get("accuracy_contract", "soft"),
        concept_type=row.get("concept_type"),
        use_immediately_as=use_imm if isinstance(use_imm, list) else [],
        tension_questions=tension_q if isinstance(tension_q, list) else [],
        triage_score=row.get("triage_score"),
    )


def _row_to_action_template(row: dict[str, Any]) -> ActionTemplate:
    execution_steps = row.get("execution_steps", "[]")
    if isinstance(execution_steps, str):
        execution_steps = json.loads(execution_steps)

    acceptance_checks = row.get("acceptance_checks", "[]")
    if isinstance(acceptance_checks, str):
        acceptance_checks = json.loads(acceptance_checks)

    rollback_steps = row.get("rollback_steps", "[]")
    if isinstance(rollback_steps, str):
        rollback_steps = json.loads(rollback_steps)

    preconditions = row.get("preconditions", "[]")
    if isinstance(preconditions, str):
        preconditions = json.loads(preconditions)

    return ActionTemplate(
        id=row["id"],
        title=row["title"],
        problem_pattern=row["problem_pattern"],
        execution_steps=execution_steps,
        acceptance_checks=acceptance_checks,
        rollback_steps=rollback_steps,
        preconditions=preconditions,
        source_methodology_id=row.get("source_methodology_id"),
        source_repo=row.get("source_repo"),
        confidence=float(row.get("confidence", 0.5) or 0.5),
        success_count=int(row.get("success_count", 0) or 0),
        failure_count=int(row.get("failure_count", 0) or 0),
        created_at=_parse_dt(row.get("created_at")),
        updated_at=_parse_dt(row.get("updated_at")),
    )


def _row_to_peer_review(row: dict[str, Any]) -> PeerReview:
    return PeerReview(
        id=row["id"],
        task_id=row["task_id"],
        model_used=row["model_used"],
        diagnosis=row["diagnosis"],
        recommended_approach=row.get("recommended_approach"),
        reasoning=row.get("reasoning"),
        created_at=_parse_dt(row.get("created_at")),
    )


def _row_to_context_snapshot(row: dict[str, Any]) -> ContextSnapshot:
    manifest = row.get("file_manifest")
    if isinstance(manifest, str):
        manifest = json.loads(manifest)
    return ContextSnapshot(
        id=row["id"],
        task_id=row["task_id"],
        attempt_number=row["attempt_number"],
        git_ref=row["git_ref"],
        file_manifest=manifest,
        created_at=_parse_dt(row.get("created_at")),
    )


def _row_to_methodology_usage_entry(row: dict[str, Any]) -> MethodologyUsageEntry:
    success = row.get("success")
    if success is not None:
        success = bool(success)
    return MethodologyUsageEntry(
        id=row["id"],
        task_id=row["task_id"],
        methodology_id=row["methodology_id"],
        project_id=row.get("project_id"),
        stage=row.get("stage", "retrieved_presented"),
        agent_id=row.get("agent_id"),
        success=success,
        expectation_match_score=row.get("expectation_match_score"),
        quality_score=row.get("quality_score"),
        relevance_score=row.get("relevance_score"),
        notes=row.get("notes"),
        created_at=_parse_dt(row.get("created_at")),
    )


def _row_to_synergy_exploration(row: dict[str, Any]) -> SynergyExploration:
    details = row.get("details", "{}")
    if isinstance(details, str):
        details = json.loads(details)
    return SynergyExploration(
        id=row["id"],
        cap_a_id=row["cap_a_id"],
        cap_b_id=row["cap_b_id"],
        explored_at=_parse_dt(row.get("explored_at")),
        result=row.get("result", "pending"),
        synergy_score=row.get("synergy_score"),
        synergy_type=row.get("synergy_type"),
        edge_id=row.get("edge_id"),
        exploration_method=row.get("exploration_method"),
        details=details,
    )


def _row_to_receipt(row: dict[str, Any]) -> Receipt:
    return Receipt(
        source_barcode=row["source_barcode"],
        family_barcode=row["family_barcode"],
        lineage_id=row["lineage_id"],
        repo=row["repo"],
        commit=row.get("commit_sha"),
        file_path=row["file_path"],
        symbol=row.get("symbol_name"),
        line_start=row.get("line_start"),
        line_end=row.get("line_end"),
        content_hash=row["content_hash"],
        provenance_precision=row["provenance_precision"],
    )


def _row_to_component_lineage(row: dict[str, Any]) -> ComponentLineage:
    return ComponentLineage(
        id=row["id"],
        family_barcode=row["family_barcode"],
        canonical_content_hash=row["canonical_content_hash"],
        canonical_title=row.get("canonical_title"),
        language=row.get("language"),
        lineage_size=int(row.get("lineage_size", 1) or 1),
        deduped_support_count=int(row.get("deduped_support_count", 1) or 1),
        clone_inflated=bool(row.get("clone_inflated", 0)),
        created_at=_parse_dt(row.get("created_at")) or datetime.now(UTC),
        updated_at=_parse_dt(row.get("updated_at")) or datetime.now(UTC),
    )


def _row_to_component_card(row: dict[str, Any]) -> ComponentCard:
    return ComponentCard(
        id=row["id"],
        methodology_id=row.get("methodology_id"),
        title=row["title"],
        component_type=row["component_type"],
        abstract_jobs=_json_loads(row.get("abstract_jobs_json"), []),
        receipt=_row_to_receipt(row),
        language=row.get("language"),
        frameworks=_json_loads(row.get("frameworks_json"), []),
        dependencies=_json_loads(row.get("dependencies_json"), []),
        constraints=_json_loads(row.get("constraints_json"), []),
        inputs=_json_loads(row.get("inputs_json"), []),
        outputs=_json_loads(row.get("outputs_json"), []),
        test_evidence=_json_loads(row.get("test_evidence_json"), []),
        applicability=_json_loads(row.get("applicability_json"), []),
        non_applicability=_json_loads(row.get("non_applicability_json"), []),
        adaptation_notes=_json_loads(row.get("adaptation_notes_json"), []),
        risk_notes=_json_loads(row.get("risk_notes_json"), []),
        keywords=_json_loads(row.get("keywords_json"), []),
        coverage_state=row.get("coverage_state", "weak"),
        success_count=int(row.get("success_count", 0) or 0),
        failure_count=int(row.get("failure_count", 0) or 0),
        created_at=_parse_dt(row.get("created_at")) or datetime.now(UTC),
        updated_at=_parse_dt(row.get("updated_at")) or datetime.now(UTC),
    )


def _row_to_component_card_summary(row: dict[str, Any]) -> ComponentCardSummary:
    return ComponentCardSummary(
        id=row["id"],
        title=row["title"],
        component_type=row["component_type"],
        language=row.get("language"),
        family_barcode=row["family_barcode"],
        repo=row["repo"],
        file_path=row["file_path"],
        symbol=row.get("symbol_name"),
        provenance_precision=row["provenance_precision"],
        success_count=int(row.get("success_count", 0) or 0),
        failure_count=int(row.get("failure_count", 0) or 0),
        coverage_state=row.get("coverage_state", "weak"),
    )


def _row_to_component_fit(row: dict[str, Any]) -> ComponentFit:
    return ComponentFit(
        id=row["id"],
        component_id=row["component_id"],
        task_archetype=row.get("task_archetype"),
        component_type=row.get("component_type"),
        slot_signature=row.get("slot_signature"),
        fit_bucket=row["fit_bucket"],
        transfer_mode=row["transfer_mode"],
        confidence=float(row.get("confidence", 0.0) or 0.0),
        confidence_basis=_json_loads(row.get("confidence_basis_json"), []),
        success_count=int(row.get("success_count", 0) or 0),
        failure_count=int(row.get("failure_count", 0) or 0),
        evidence_count=int(row.get("evidence_count", 0) or 0),
        notes=_json_loads(row.get("notes_json"), []),
        updated_at=_parse_dt(row.get("updated_at")) or datetime.now(UTC),
    )


def _row_to_application_packet_summary(row: dict[str, Any]) -> ApplicationPacketSummary:
    packet = _json_loads(row.get("packet_json"), {})
    if packet:
        raw_selected = packet.get("selected", {})
        return ApplicationPacketSummary(
            packet_id=row["id"],
            plan_id=row["plan_id"],
            task_archetype=row["task_archetype"],
            slot_id=row["slot_id"],
            slot_name=packet.get("slot", {}).get("name", row["slot_id"]),
            status=row.get("status", "draft"),
            selected_component_id=row["selected_component_id"],
            fit_bucket=raw_selected.get("fit_bucket", "may_help"),
            transfer_mode=raw_selected.get("transfer_mode", "heuristic_fallback"),
            confidence=float(raw_selected.get("confidence", 0.0) or 0.0),
            review_required=bool(row.get("review_required", 0)),
            coverage_state=row.get("coverage_state", "weak"),
        )
    return ApplicationPacketSummary(
        packet_id=row["id"],
        plan_id=row["plan_id"],
        task_archetype=row["task_archetype"],
        slot_id=row["slot_id"],
        slot_name=row["slot_id"],
        status=row.get("status", "draft"),
        selected_component_id=row["selected_component_id"],
        fit_bucket="may_help",
        transfer_mode="heuristic_fallback",
        confidence=0.0,
        review_required=bool(row.get("review_required", 0)),
        coverage_state=row.get("coverage_state", "weak"),
    )


def _row_to_task_plan_record(row: dict[str, Any]) -> TaskPlanRecord:
    return TaskPlanRecord(
        id=row["id"],
        task_text=row["task_text"],
        workspace_dir=row.get("workspace_dir"),
        branch=row.get("branch"),
        target_brain=row.get("target_brain"),
        execution_mode=row.get("execution_mode"),
        check_commands=_json_loads(row.get("check_commands_json"), []),
        task_archetype=row["task_archetype"],
        archetype_confidence=float(row.get("archetype_confidence", 0.0) or 0.0),
        status=row.get("status", "draft"),
        summary=_json_loads(row.get("summary_json"), {}),
        approved_slot_ids=_json_loads(row.get("approved_slot_ids_json"), []),
        created_at=_parse_dt(row.get("created_at")) or datetime.now(UTC),
        updated_at=_parse_dt(row.get("updated_at")) or datetime.now(UTC),
        plan_json=_json_loads(row.get("plan_json"), {}),
    )


def _row_to_compiled_recipe(row: dict[str, Any]) -> CompiledRecipe:
    return CompiledRecipe(
        id=row["id"],
        task_archetype=row["task_archetype"],
        recipe_name=row["recipe_name"],
        recipe_json=_json_loads(row.get("recipe_json"), {}),
        sample_size=int(row.get("sample_size", 0) or 0),
        is_active=bool(row.get("is_active", 0)),
        created_at=_parse_dt(row.get("created_at")) or datetime.now(UTC),
        updated_at=_parse_dt(row.get("updated_at")) or datetime.now(UTC),
    )


def _row_to_mining_mission(row: dict[str, Any]) -> MiningMission:
    return MiningMission(
        id=row["id"],
        run_id=row.get("run_id"),
        slot_family=row.get("slot_family"),
        priority=row.get("priority") or "normal",
        reason=row.get("reason") or "",
        status=row.get("status") or "queued",
        mission_json=_json_loads(row.get("mission_json"), {}),
        created_at=_parse_dt(row.get("created_at")) or datetime.now(UTC),
        updated_at=_parse_dt(row.get("updated_at")) or datetime.now(UTC),
    )


def _row_to_pair_event(row: dict[str, Any]) -> PairEvent:
    return PairEvent(
        id=row["id"],
        run_id=row["run_id"],
        slot_id=row["slot_id"],
        slot_barcode=row["slot_barcode"],
        packet_id=row["packet_id"],
        component_id=row["component_id"],
        source_barcode=row["source_barcode"],
        confidence=float(row.get("confidence", 0.0) or 0.0),
        confidence_basis=_json_loads(row.get("confidence_basis_json"), []),
        replacement_of_pair_id=row.get("replacement_of_pair_id"),
        created_at=_parse_dt(row.get("created_at")) or datetime.now(UTC),
    )


def _row_to_landing_event(row: dict[str, Any]) -> LandingEvent:
    return LandingEvent(
        id=row["id"],
        run_id=row["run_id"],
        slot_id=row["slot_id"],
        packet_id=row["packet_id"],
        file_path=row["file_path"],
        symbol=row.get("symbol_name"),
        diff_hunk_id=row.get("diff_hunk_id"),
        origin=row["origin"],
        created_at=_parse_dt(row.get("created_at")) or datetime.now(UTC),
    )


def _row_to_outcome_event(row: dict[str, Any]) -> OutcomeEvent:
    return OutcomeEvent(
        id=row["id"],
        run_id=row["run_id"],
        slot_id=row["slot_id"],
        packet_id=row["packet_id"],
        success=bool(row.get("success", 0)),
        verifier_findings=_json_loads(row.get("verifier_findings_json"), []),
        test_refs=_json_loads(row.get("test_refs_json"), []),
        negative_memory_updates=_json_loads(row.get("negative_memory_updates_json"), []),
        recipe_eligible=bool(row.get("recipe_eligible", 0)),
        created_at=_parse_dt(row.get("created_at")) or datetime.now(UTC),
    )


def _row_to_run_connectome(row: dict[str, Any]) -> RunConnectome:
    return RunConnectome(
        id=row["id"],
        run_id=row["run_id"],
        task_archetype=row.get("task_archetype"),
        status=row.get("status", "pending"),
        created_at=_parse_dt(row.get("created_at")) or datetime.now(UTC),
    )


def _row_to_run_slot_execution(row: dict[str, Any]) -> RunSlotExecution:
    return RunSlotExecution(
        id=row["id"],
        run_id=row["run_id"],
        slot_id=row["slot_id"],
        packet_id=row.get("packet_id"),
        selected_component_id=row.get("selected_component_id"),
        status=row.get("status") or "queued",
        current_step=row.get("current_step"),
        retry_count=int(row.get("retry_count", 0) or 0),
        last_retry_detail=row.get("last_retry_detail"),
        replacement_count=int(row.get("replacement_count", 0) or 0),
        blocked_wait_ms=int(row.get("blocked_wait_ms", 0) or 0),
        family_wait_ms=int(row.get("family_wait_ms", 0) or 0),
        created_at=_parse_dt(row.get("created_at")) or datetime.now(UTC),
        updated_at=_parse_dt(row.get("updated_at")) or datetime.now(UTC),
    )


def _row_to_run_event(row: dict[str, Any]) -> RunEvent:
    return RunEvent(
        id=row["id"],
        run_id=row["run_id"],
        slot_id=row.get("slot_id"),
        event_type=row["event_type"],
        payload=_json_loads(row.get("payload_json"), {}),
        created_at=_parse_dt(row.get("created_at")) or datetime.now(UTC),
    )


def _row_to_run_action_audit(row: dict[str, Any]) -> RunActionAudit:
    return RunActionAudit(
        id=row["id"],
        run_id=row["run_id"],
        slot_id=row.get("slot_id"),
        action_type=row["action_type"],
        actor=row.get("actor") or "operator",
        reason=row.get("reason") or "",
        action_payload=_json_loads(row.get("action_payload_json"), {}),
        created_at=_parse_dt(row.get("created_at")) or datetime.now(UTC),
    )


def _row_to_governance_policy(row: dict[str, Any]) -> GovernancePolicy:
    return GovernancePolicy(
        id=row["id"],
        run_id=row.get("run_id"),
        task_archetype=row.get("task_archetype"),
        slot_id=row.get("slot_id"),
        family_barcode=row.get("family_barcode"),
        policy_kind=row["policy_kind"],
        severity=row.get("severity") or "medium",
        status=row.get("status") or "active",
        reason=row.get("reason") or "",
        recommendation=row.get("recommendation") or "",
        evidence_json=_json_loads(row.get("evidence_json"), {}),
        promoted_by=row.get("promoted_by") or "operator",
        created_at=_parse_dt(row.get("created_at")) or datetime.now(UTC),
        updated_at=_parse_dt(row.get("updated_at")) or datetime.now(UTC),
    )


def _parse_dt(val: Any) -> Optional[datetime]:
    """Parse ISO-8601 datetime string from SQLite TEXT column."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return None
