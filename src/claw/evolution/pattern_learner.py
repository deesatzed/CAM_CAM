"""Cross-project pattern extraction and promotion.

After enough task completions, extracts successful patterns and
promotes them from project-scope to global-scope methodologies.
A pattern is a recurring successful approach:
- Same error_signature resolved the same way 2+ times
- High-fitness methodology used across 3+ tasks
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Optional

from claw.db.repository import Repository

logger = logging.getLogger("claw.evolution.pattern_learner")


class PatternLearner:
    """Cross-project pattern extraction and promotion.

    After enough task completions, extracts successful patterns and
    promotes them from project-scope to global-scope methodologies.
    """

    def __init__(
        self,
        repository: Repository,
        semantic_memory: Any = None,
    ) -> None:
        """
        Parameters
        ----------
        repository:
            The data access layer for direct DB queries.
        semantic_memory:
            Optional semantic memory instance for embedding-based
            similarity operations.  If None, pattern extraction
            relies solely on structural matching (error signatures,
            methodology metadata).
        """
        self.repository = repository
        self.semantic_memory = semantic_memory
        self._promotion_expectation_threshold = 0.65
        self._promotion_success_minimum = 3

    # ------------------------------------------------------------------
    # Pattern extraction
    # ------------------------------------------------------------------

    async def extract_patterns(
        self, project_id: str, min_completions: int = 5
    ) -> list[dict[str, Any]]:
        """Extract patterns from completed tasks in a project.

        A pattern is a recurring successful approach:
        - Same ``error_signature`` resolved the same way 2+ times
        - High-fitness methodology used across 3+ tasks

        Parameters
        ----------
        project_id:
            The project to analyse.
        min_completions:
            Minimum number of completed tasks required before
            pattern extraction is attempted.

        Returns
        -------
        list[dict]
            Each dict describes a discovered pattern with keys:
            ``pattern_type``, ``description``, ``evidence_count``,
            ``methodology_ids``, ``error_signature`` (if applicable),
            ``confidence``.
        """
        # Gate: enough completed tasks?
        completed_row = await self.repository.engine.fetch_one(
            """SELECT COUNT(*) AS cnt FROM tasks
               WHERE project_id = ? AND status = 'DONE'""",
            [project_id],
        )
        completed_count = int(completed_row["cnt"]) if completed_row else 0

        if completed_count < min_completions:
            logger.debug(
                "Project %s has only %d completed tasks (need %d); skipping pattern extraction",
                project_id,
                completed_count,
                min_completions,
            )
            return []

        patterns: list[dict[str, Any]] = []

        # --- Pattern type 1: recurring error-signature resolutions ---
        error_patterns = await self._extract_error_signature_patterns(project_id)
        patterns.extend(error_patterns)

        # --- Pattern type 2: high-fitness methodology reuse ---
        methodology_patterns = await self._extract_methodology_patterns(project_id)
        patterns.extend(methodology_patterns)

        logger.info(
            "Extracted %d patterns from project %s (%d completed tasks)",
            len(patterns),
            project_id,
            completed_count,
        )
        return patterns

    async def _extract_error_signature_patterns(
        self, project_id: str
    ) -> list[dict[str, Any]]:
        """Find error signatures that were resolved the same way 2+ times."""
        # Get error signatures that appear 2+ times with a SUCCESS resolution
        rows = await self.repository.engine.fetch_all(
            """SELECT h.error_signature,
                      COUNT(*) AS occurrence_count,
                      GROUP_CONCAT(DISTINCT h.approach_summary) AS approaches,
                      GROUP_CONCAT(DISTINCT h.task_id) AS task_ids
               FROM hypothesis_log h
               JOIN tasks t ON h.task_id = t.id
               WHERE t.project_id = ?
                 AND h.error_signature IS NOT NULL
                 AND h.outcome = 'SUCCESS'
               GROUP BY h.error_signature
               HAVING COUNT(*) >= 2
               ORDER BY occurrence_count DESC""",
            [project_id],
        )

        patterns: list[dict[str, Any]] = []
        for row in rows:
            error_sig = str(row["error_signature"])
            count = int(row["occurrence_count"])
            approaches = str(row["approaches"]) if row["approaches"] else ""
            task_ids_str = str(row["task_ids"]) if row["task_ids"] else ""
            task_ids = [t.strip() for t in task_ids_str.split(",") if t.strip()]

            # Look for methodologies linked to these successful resolutions
            methodology_ids = await self._find_methodologies_for_tasks(task_ids)

            confidence = min(1.0, count / 5.0)  # Saturates at 5 observations

            patterns.append({
                "pattern_type": "error_resolution",
                "description": (
                    f"Error signature '{error_sig}' has been successfully "
                    f"resolved {count} times with approach: {approaches}"
                ),
                "error_signature": error_sig,
                "evidence_count": count,
                "task_ids": task_ids,
                "methodology_ids": methodology_ids,
                "confidence": confidence,
                "approaches": approaches,
            })

        return patterns

    async def _extract_methodology_patterns(
        self, project_id: str
    ) -> list[dict[str, Any]]:
        """Find methodologies with high fitness that were used across 3+ tasks."""
        # Get methodologies linked to this project via source_task_id
        rows = await self.repository.engine.fetch_all(
            """SELECT m.id, m.problem_description, m.solution_code,
                      m.success_count, m.failure_count, m.retrieval_count,
                      m.lifecycle_state, m.scope, m.fitness_vector,
                      m.methodology_type, m.tags
               FROM methodologies m
               JOIN tasks t ON m.source_task_id = t.id
               WHERE t.project_id = ?
                 AND m.success_count >= 3
                 AND m.lifecycle_state IN ('viable', 'thriving')
               ORDER BY m.success_count DESC""",
            [project_id],
        )

        patterns: list[dict[str, Any]] = []
        for row in rows:
            meth_id = str(row["id"])
            success_count = int(row["success_count"])
            failure_count = int(row["failure_count"])
            lifecycle_state = str(row["lifecycle_state"])

            # Compute a simple fitness from success rate
            total = success_count + failure_count
            success_rate = success_count / total if total > 0 else 0.0
            confidence = min(1.0, success_count / 10.0)

            tags_raw = row.get("tags", "[]")
            if isinstance(tags_raw, str):
                try:
                    tags = json.loads(tags_raw)
                except (json.JSONDecodeError, TypeError):
                    tags = []
            else:
                tags = tags_raw

            patterns.append({
                "pattern_type": "methodology_reuse",
                "description": (
                    f"Methodology '{row['problem_description'][:80]}' "
                    f"succeeded {success_count} times (rate={success_rate:.0%})"
                ),
                "methodology_ids": [meth_id],
                "evidence_count": success_count,
                "success_rate": success_rate,
                "lifecycle_state": lifecycle_state,
                "confidence": confidence,
                "tags": tags,
            })

        return patterns

    async def _find_methodologies_for_tasks(
        self, task_ids: list[str]
    ) -> list[str]:
        """Find methodology IDs linked to given tasks via source_task_id."""
        if not task_ids:
            return []

        placeholders = ",".join("?" for _ in task_ids)
        rows = await self.repository.engine.fetch_all(
            f"SELECT DISTINCT id FROM methodologies WHERE source_task_id IN ({placeholders})",
            task_ids,
        )
        return [str(r["id"]) for r in rows]

    # ------------------------------------------------------------------
    # Promotion
    # ------------------------------------------------------------------

    async def promote_to_global(self, methodology_id: str) -> bool:
        """Promote a project-scope methodology to global scope.

        Requirements:
        - methodology must be in 'thriving' lifecycle state
        - attribution-backed success evidence must meet the global-promotion bar
        - methodology must currently have ``scope = 'project'``

        Parameters
        ----------
        methodology_id:
            The ID of the methodology to promote.

        Returns
        -------
        bool
            ``True`` if promotion succeeded, ``False`` if requirements
            were not met or the methodology does not exist.
        """
        methodology = await self.repository.get_methodology(methodology_id)
        if methodology is None:
            logger.warning(
                "Cannot promote methodology %s: not found", methodology_id
            )
            return False

        # Requirement: must be project scope (already global = no-op)
        if methodology.scope == "global":
            logger.info(
                "Methodology %s is already global scope", methodology_id
            )
            return True

        # Requirement: thriving lifecycle
        if methodology.lifecycle_state != "thriving":
            logger.info(
                "Cannot promote methodology %s: lifecycle_state=%s (need thriving)",
                methodology_id,
                methodology.lifecycle_state,
            )
            return False

        usage_stats = await self.repository.get_methodology_usage_stats_for_methodology(methodology_id)
        attributed_success_count = int(usage_stats.get("attributed_success_count", 0) or 0)
        avg_expectation_match_score = usage_stats.get("avg_expectation_match_score")

        # Requirement: expectation-matched attributed successes >= minimum.
        # Fall back to raw success_count only when no attribution history exists yet.
        effective_success_count = attributed_success_count or methodology.success_count
        if effective_success_count < self._promotion_success_minimum:
            logger.info(
                "Cannot promote methodology %s: effective_success_count=%d (need >= %d)",
                methodology_id,
                effective_success_count,
                self._promotion_success_minimum,
            )
            return False
        if attributed_success_count > 0 and (
            avg_expectation_match_score is None
            or float(avg_expectation_match_score) < self._promotion_expectation_threshold
        ):
            logger.info(
                "Cannot promote methodology %s: avg_expectation_match_score=%s (need >= %.2f)",
                methodology_id,
                avg_expectation_match_score,
                self._promotion_expectation_threshold,
            )
            return False

        # Optionally check cross-project usage (if we have enough data).
        # Check if the methodology's approach pattern (via error_signature
        # or similar problem_description) exists across 2+ projects.
        cross_project_count = await self._count_cross_project_usage(methodology)
        if cross_project_count < 2:
            logger.info(
                "Cannot promote methodology %s: cross-project usage=%d (need >= 2). "
                "Single-project methodology may still be promoted if this check "
                "is waived by the caller.",
                methodology_id,
                cross_project_count,
            )
            # We still allow promotion for single-project methodologies
            # that meet the other requirements, since requiring cross-project
            # usage could block valid promotions in single-repo setups.

        # Apply promotion
        await self.repository.engine.execute(
            "UPDATE methodologies SET scope = 'global' WHERE id = ?",
            [methodology_id],
        )

        logger.info(
            "Promoted methodology %s to global scope (effective_success_count=%d, "
            "cross_project_usage=%d, avg_expectation_match_score=%s)",
            methodology_id,
            effective_success_count,
            cross_project_count,
            avg_expectation_match_score,
        )
        return True

    async def _count_cross_project_usage(self, methodology: Any) -> int:
        """Count how many distinct projects have tasks similar to this methodology's source."""
        usage_rows = await self.repository.engine.fetch_all(
            """SELECT COUNT(DISTINCT project_id) AS project_count
               FROM methodology_usage_log
               WHERE methodology_id = ?
                 AND stage = 'outcome_attributed'
                 AND success = 1
                 AND project_id IS NOT NULL""",
            [methodology.id],
        )
        if usage_rows and usage_rows[0].get("project_count"):
            return int(usage_rows[0]["project_count"])

        if methodology.source_task_id is None:
            return 1

        # Find which project the source task belongs to
        source_task = await self.repository.get_task(methodology.source_task_id)
        if source_task is None:
            return 1

        # Find other tasks with the same error_signature or similar problem
        # resolved by the same approach across different projects.
        # We check the hypothesis_log for matching error_signatures.
        rows = await self.repository.engine.fetch_all(
            """SELECT COUNT(DISTINCT t.project_id) AS project_count
               FROM hypothesis_log h
               JOIN tasks t ON h.task_id = t.id
               WHERE h.outcome = 'SUCCESS'
                 AND h.error_signature IS NOT NULL
                 AND h.error_signature IN (
                     SELECT DISTINCT error_signature
                     FROM hypothesis_log
                     WHERE task_id = ? AND error_signature IS NOT NULL
                 )""",
            [methodology.source_task_id],
        )

        if rows and rows[0].get("project_count"):
            return int(rows[0]["project_count"])
        return 1

    # ------------------------------------------------------------------
    # Global patterns
    # ------------------------------------------------------------------

    async def get_global_patterns(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get all global-scope patterns (promoted methodologies).

        Returns methodologies with ``scope = 'global'``, ordered by
        success_count descending, enriched with attributed-usage evidence.
        """
        rows = await self.repository.engine.fetch_all(
            """SELECT id, problem_description, solution_code, methodology_notes,
                      success_count, failure_count, retrieval_count,
                      lifecycle_state, methodology_type, tags, fitness_vector,
                      created_at
               FROM methodologies
               WHERE scope = 'global'
               ORDER BY success_count DESC
               LIMIT ?""",
            [limit],
        )

        patterns: list[dict[str, Any]] = []
        for row in rows:
            tags_raw = row.get("tags", "[]")
            if isinstance(tags_raw, str):
                try:
                    tags = json.loads(tags_raw)
                except (json.JSONDecodeError, TypeError):
                    tags = []
            else:
                tags = tags_raw

            fitness_raw = row.get("fitness_vector", "{}")
            if isinstance(fitness_raw, str):
                try:
                    fitness = json.loads(fitness_raw)
                except (json.JSONDecodeError, TypeError):
                    fitness = {}
            else:
                fitness = fitness_raw

            success_count = int(row.get("success_count", 0))
            failure_count = int(row.get("failure_count", 0))
            total = success_count + failure_count
            success_rate = success_count / total if total > 0 else 0.0
            usage_stats = await self.repository.get_methodology_usage_stats_for_methodology(str(row["id"]))

            patterns.append({
                "methodology_id": str(row["id"]),
                "problem_description": str(row["problem_description"]),
                "solution_summary": str(row["solution_code"])[:200],
                "methodology_notes": row.get("methodology_notes"),
                "success_count": success_count,
                "failure_count": failure_count,
                "retrieval_count": int(row.get("retrieval_count", 0)),
                "success_rate": success_rate,
                "lifecycle_state": str(row.get("lifecycle_state", "viable")),
                "methodology_type": row.get("methodology_type"),
                "tags": tags,
                "fitness_vector": fitness,
                "created_at": row.get("created_at"),
                "attributed_success_count": int(usage_stats.get("attributed_success_count", 0) or 0),
                "attributed_failure_count": int(usage_stats.get("attributed_failure_count", 0) or 0),
                "avg_expectation_match_score": usage_stats.get("avg_expectation_match_score"),
                "avg_quality_score": usage_stats.get("avg_quality_score"),
                "evidence_source": "attribution" if int(usage_stats.get("attributed_success_count", 0) or 0) > 0 else "legacy",
            })

        return patterns

    # ------------------------------------------------------------------
    # Pattern summary
    # ------------------------------------------------------------------

    async def get_pattern_summary(self, project_id: str) -> dict[str, Any]:
        """Get pattern extraction summary for a project.

        Returns a dict with:
        - ``project_id``
        - ``completed_tasks``: number of completed tasks
        - ``total_methodologies``: number of methodologies sourced from this project
        - ``global_methodologies``: number of methodologies promoted to global scope
        - ``thriving_methodologies``: number in 'thriving' state
        - ``patterns_available``: whether enough data exists for extraction
        - ``error_signature_clusters``: number of distinct error signatures
          resolved successfully 2+ times
        - ``attribution_backed_methodologies``: high-trust methodologies with
          attributed evidence
        - ``legacy_evidence_methodologies``: high-trust methodologies still
          relying on legacy/raw-success evidence
        - ``low_expectation_methodologies``: high-trust methodologies with
          weak expectation-match evidence
        - ``demotion_candidate_methodologies``: high-trust methodologies with
          repeated attributed failures and no attributed success
        - ``flagged_methodologies``: total high-trust methodologies needing audit
        """
        # Completed tasks
        completed_row = await self.repository.engine.fetch_one(
            "SELECT COUNT(*) AS cnt FROM tasks WHERE project_id = ? AND status = 'DONE'",
            [project_id],
        )
        completed_tasks = int(completed_row["cnt"]) if completed_row else 0

        # Total methodologies from this project
        total_meth_row = await self.repository.engine.fetch_one(
            """SELECT COUNT(*) AS cnt FROM methodologies m
               JOIN tasks t ON m.source_task_id = t.id
               WHERE t.project_id = ?""",
            [project_id],
        )
        total_methodologies = int(total_meth_row["cnt"]) if total_meth_row else 0

        # Global-scope methodologies from this project
        global_meth_row = await self.repository.engine.fetch_one(
            """SELECT COUNT(*) AS cnt FROM methodologies m
               JOIN tasks t ON m.source_task_id = t.id
               WHERE t.project_id = ? AND m.scope = 'global'""",
            [project_id],
        )
        global_methodologies = int(global_meth_row["cnt"]) if global_meth_row else 0

        # Thriving methodologies from this project
        thriving_row = await self.repository.engine.fetch_one(
            """SELECT COUNT(*) AS cnt FROM methodologies m
               JOIN tasks t ON m.source_task_id = t.id
               WHERE t.project_id = ? AND m.lifecycle_state = 'thriving'""",
            [project_id],
        )
        thriving_methodologies = int(thriving_row["cnt"]) if thriving_row else 0

        # Error signature clusters (resolved 2+ times)
        error_cluster_row = await self.repository.engine.fetch_one(
            """SELECT COUNT(*) AS cnt FROM (
                   SELECT h.error_signature
                   FROM hypothesis_log h
                   JOIN tasks t ON h.task_id = t.id
                   WHERE t.project_id = ?
                     AND h.error_signature IS NOT NULL
                     AND h.outcome = 'SUCCESS'
                   GROUP BY h.error_signature
                   HAVING COUNT(*) >= 2
               )""",
            [project_id],
        )
        error_signature_clusters = int(error_cluster_row["cnt"]) if error_cluster_row else 0
        evidence_audit = await self.repository.get_methodology_evidence_audit(
            project_id=project_id,
            expectation_threshold=self._promotion_expectation_threshold,
        )
        audit_summary = evidence_audit["summary"]

        return {
            "project_id": project_id,
            "completed_tasks": completed_tasks,
            "total_methodologies": total_methodologies,
            "global_methodologies": global_methodologies,
            "thriving_methodologies": thriving_methodologies,
            "patterns_available": completed_tasks >= 5,
            "error_signature_clusters": error_signature_clusters,
            "attribution_backed_methodologies": audit_summary["attribution_backed_total"],
            "legacy_evidence_methodologies": audit_summary["legacy_backed_total"],
            "low_expectation_methodologies": audit_summary["low_expectation_total"],
            "demotion_candidate_methodologies": audit_summary["demotion_candidate_total"],
            "flagged_methodologies": audit_summary["flagged_total"],
        }

    async def generate_auto_fix_rule_suggestions(
        self,
        project_id: Optional[str] = None,
        min_occurrences: int = 3,
    ) -> list[dict[str, Any]]:
        """Suggest deterministic auto-fix rules from repeated correction successes."""
        if project_id:
            rows = await self.repository.engine.fetch_all(
                """SELECT h_fix.error_signature,
                          COUNT(*) AS fix_count,
                          GROUP_CONCAT(DISTINCT h_fix.approach_summary) AS approaches,
                          GROUP_CONCAT(DISTINCT h_fix.task_id) AS task_ids
                   FROM hypothesis_log h_fix
                   JOIN tasks t ON h_fix.task_id = t.id
                   WHERE t.project_id = ?
                     AND h_fix.outcome = 'SUCCESS'
                     AND h_fix.error_signature IS NOT NULL
                     AND EXISTS (
                         SELECT 1 FROM hypothesis_log h_fail
                         WHERE h_fail.task_id = h_fix.task_id
                           AND h_fail.outcome = 'FAILURE'
                           AND h_fail.error_signature = h_fix.error_signature
                           AND h_fail.attempt_number < h_fix.attempt_number
                     )
                   GROUP BY h_fix.error_signature
                   HAVING COUNT(*) >= ?
                   ORDER BY fix_count DESC""",
                [project_id, min_occurrences],
            )
        else:
            rows = await self.repository.engine.fetch_all(
                """SELECT h_fix.error_signature,
                          COUNT(*) AS fix_count,
                          GROUP_CONCAT(DISTINCT h_fix.approach_summary) AS approaches,
                          GROUP_CONCAT(DISTINCT h_fix.task_id) AS task_ids
                   FROM hypothesis_log h_fix
                   WHERE h_fix.outcome = 'SUCCESS'
                     AND h_fix.error_signature IS NOT NULL
                     AND EXISTS (
                         SELECT 1 FROM hypothesis_log h_fail
                         WHERE h_fail.task_id = h_fix.task_id
                           AND h_fail.outcome = 'FAILURE'
                           AND h_fail.error_signature = h_fix.error_signature
                           AND h_fail.attempt_number < h_fix.attempt_number
                     )
                   GROUP BY h_fix.error_signature
                   HAVING COUNT(*) >= ?
                   ORDER BY fix_count DESC""",
                [min_occurrences],
            )

        suggestions: list[dict[str, Any]] = []
        for row in rows:
            error_sig = str(row["error_signature"])
            fix_count = int(row["fix_count"])
            approaches_raw = str(row["approaches"]) if row["approaches"] else ""
            task_ids_raw = str(row["task_ids"]) if row["task_ids"] else ""

            from claw.evolution.rl_escalation import classify_error

            suggestions.append({
                "error_signature": error_sig,
                "correction_count": fix_count,
                "fix_approaches": [a.strip() for a in approaches_raw.split(",") if a.strip()],
                "category": classify_error(error_sig),
                "task_ids": [t.strip() for t in task_ids_raw.split(",") if t.strip()],
                "confidence": min(1.0, fix_count / 5.0),
            })

        if suggestions:
            logger.info(
                "Generated %d auto-fix rule suggestions (min_occurrences=%d)",
                len(suggestions), min_occurrences,
            )
        return suggestions
