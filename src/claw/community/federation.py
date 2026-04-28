"""CAM Swarm — cross-ganglion federation for knowledge sharing.

The CAM Brain is made of specialized Ganglia (CAM instances), each with
its own claw.db and domain focus.  The Swarm layer connects them via
read-only FTS5 queries through brain manifests.

Opens read-only connections to sibling ganglion claw.db files, queries
their methodologies via FTS5 text search, and returns results tagged
with source ganglion metadata.  Vector search is avoided since ganglia
may use different embedding models.

Terminology:
    - **CAM Brain**: The full federated system (all ganglia together).
    - **CAM Ganglion**: A specialized instance with its own claw.db.
    - **CAM Swarm**: This module — the runtime coordination layer.

Usage:
    federation = Federation(config.instances)
    results = await federation.query("quantum error correction", language="python")
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from claw.community.manifest import load_manifest, score_manifest_relevance
from claw.core.models import Methodology

logger = logging.getLogger("claw.community.federation")


def _extract_keywords(text: str, max_keywords: int = 15) -> list[str]:
    """Extract meaningful keywords from a task description.

    Strips common stop words and short tokens, returns lowercased keywords.
    """
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "under", "again",
        "over", "further", "then", "once", "here", "there", "when", "where", "why",
        "how", "all", "each", "every", "both", "few", "more", "most", "other",
        "some", "such", "no", "nor", "not", "only", "own", "same", "so",
        "than", "too", "very", "and", "but", "or", "if", "this", "that",
        "these", "those", "it", "its", "we", "our", "they", "them", "their",
        "what", "which", "who", "whom", "about", "up", "out", "just", "also",
        "new", "use", "using", "used", "add", "create", "make", "implement",
        "need", "want", "like", "get", "set",
    }
    # Tokenize: split on non-alphanumeric, keep tokens >= 3 chars
    tokens = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    keywords = [t for t in tokens if len(t) >= 3 and t not in stop_words]
    # Deduplicate preserving order
    seen = set()
    unique = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)
    return unique[:max_keywords]


def _build_safe_fts5_query(keywords: list[str]) -> str:
    """Build a safe FTS5 query string from keywords.

    Uses OR to match any keyword. Returns empty string if no valid keywords.
    """
    safe = []
    for kw in keywords:
        # Only allow alphanumeric and underscores
        cleaned = re.sub(r"[^a-zA-Z0-9_]", "", kw)
        if cleaned and len(cleaned) >= 3:
            safe.append(f'"{cleaned}"')
    if not safe:
        return ""
    return " OR ".join(safe)


def _row_to_methodology(row: aiosqlite.Row) -> Methodology:
    """Convert a raw DB row to a Methodology model."""
    data = dict(row)
    # Parse JSON fields
    for field in ("tags", "tech_stack", "capability_data"):
        val = data.get(field)
        if isinstance(val, str):
            try:
                data[field] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                if field == "tags":
                    data[field] = []
                elif field == "tech_stack":
                    data[field] = []
                elif field == "capability_data":
                    data[field] = {}
    return Methodology(**data)


class FederationResult:
    """A methodology retrieved from a sibling instance."""

    def __init__(
        self,
        methodology: Methodology,
        source_instance: str,
        source_db_path: str,
        relevance_score: float = 0.0,
        fts_rank: float = 0.0,
    ):
        self.methodology = methodology
        self.source_instance = source_instance
        self.source_db_path = source_db_path
        self.relevance_score = relevance_score
        self.fts_rank = fts_rank

    def __repr__(self) -> str:
        return (
            f"FederationResult(id={self.methodology.id}, "
            f"source={self.source_instance}, "
            f"relevance={self.relevance_score:.3f})"
        )


@dataclass
class FederationPacketResult:
    """A component-card style result retrieved from a sibling instance."""

    component_id: str
    title: str
    component_type: str
    abstract_jobs: list[str]
    language: Optional[str]
    repo: str
    file_path: str
    symbol: Optional[str]
    family_barcode: str
    provenance_precision: str
    source_instance: str
    source_db_path: str
    relevance_score: float = 0.0
    match_score: float = 0.0
    match_type: str = "pattern_transfer"

    def as_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "title": self.title,
            "component_type": self.component_type,
            "abstract_jobs": self.abstract_jobs,
            "language": self.language,
            "repo": self.repo,
            "file_path": self.file_path,
            "symbol": self.symbol,
            "family_barcode": self.family_barcode,
            "provenance_precision": self.provenance_precision,
            "source_instance": self.source_instance,
            "source_db_path": self.source_db_path,
            "relevance_score": self.relevance_score,
            "match_score": self.match_score,
            "match_type": self.match_type,
        }


class Federation:
    """Cross-instance knowledge federation.

    Reads sibling manifests, scores relevance, and queries
    relevant siblings via read-only FTS5 search.
    """

    def __init__(self, instance_config: Any, primary_db_path: str = ""):
        """
        Args:
            instance_config: An InstanceRegistryConfig object.
            primary_db_path: Path to the primary claw.db. When provided,
                federation also searches the primary DB alongside siblings.
        """
        self.config = instance_config
        self.primary_db_path = primary_db_path

    async def query(
        self,
        task_description: str,
        language: Optional[str] = None,
        max_total: int = 5,
    ) -> list[FederationResult]:
        """Query sibling instances for relevant methodologies.

        1. Extract keywords from task description.
        2. Load each sibling's manifest and score relevance.
        3. Query siblings above relevance threshold via FTS5.
        4. Merge and deduplicate results.

        Args:
            task_description: The task to find knowledge for.
            language: Optional programming language filter.
            max_total: Maximum total results across all siblings.

        Returns:
            Sorted list of FederationResult (best first).
        """
        if not self.config.enabled:
            return []
        if not self.config.siblings and not self.primary_db_path:
            return []

        keywords = _extract_keywords(task_description)
        if not keywords:
            logger.debug("No meaningful keywords extracted, skipping federation")
            return []

        # Score siblings by manifest relevance
        scored_siblings = []
        for sibling in self.config.siblings:
            manifest = self._load_sibling_manifest(sibling)
            if manifest is None:
                logger.debug("No manifest for sibling %s, skipping", sibling.name)
                continue
            relevance = score_manifest_relevance(manifest, keywords, language)
            if relevance >= self.config.federation_relevance_threshold:
                scored_siblings.append((sibling, relevance, manifest))
                logger.info(
                    "Sibling %s relevance=%.3f (above threshold %.2f)",
                    sibling.name, relevance, self.config.federation_relevance_threshold,
                )
            else:
                logger.debug(
                    "Sibling %s relevance=%.3f (below threshold %.2f)",
                    sibling.name, relevance, self.config.federation_relevance_threshold,
                )

        # Sort by relevance descending
        scored_siblings.sort(key=lambda x: x[1], reverse=True)

        # Query each relevant sibling
        all_results: list[FederationResult] = []
        seen_ids: set[str] = set()

        for sibling, relevance, _manifest in scored_siblings:
            if len(all_results) >= max_total:
                break
            remaining = max_total - len(all_results)
            try:
                results = await self._query_sibling(
                    sibling, keywords, language,
                    limit=min(self.config.federation_max_results, remaining),
                )
                for r in results:
                    if r.methodology.id not in seen_ids:
                        r.relevance_score = relevance
                        all_results.append(r)
                        seen_ids.add(r.methodology.id)
            except Exception as e:
                logger.warning(
                    "Failed to query sibling %s (%s): %s",
                    sibling.name, sibling.db_path, e,
                )

        # Query primary DB if provided
        if self.primary_db_path and len(all_results) < max_total:
            try:
                remaining = max_total - len(all_results)
                primary_results = await self._query_by_path(
                    self.primary_db_path,
                    getattr(self.config, "instance_name", "general") or "general",
                    keywords, language, limit=remaining,
                )
                for r in primary_results:
                    if r.methodology.id not in seen_ids:
                        r.relevance_score = 1.0  # Primary DB is always maximally relevant
                        all_results.append(r)
                        seen_ids.add(r.methodology.id)
            except Exception as e:
                logger.warning("Failed to query primary DB: %s", e)

        # Sort by relevance * fts_rank
        all_results.sort(
            key=lambda r: r.relevance_score * max(r.fts_rank, 0.1),
            reverse=True,
        )
        return all_results[:max_total]

    async def query_component_packets(
        self,
        task_description: str,
        *,
        slot_name: Optional[str] = None,
        task_archetype: Optional[str] = None,
        language: Optional[str] = None,
        max_total: int = 5,
    ) -> list[FederationPacketResult]:
        """Query sibling ganglia for component-card style results.

        This is additive to methodology federation. It uses read-only SQL and
        metadata/text matching instead of embeddings so cross-brain results stay
        transparent and comparable.
        """
        if not self.config.enabled or not self.config.siblings:
            return []

        keywords = _extract_keywords(" ".join(item for item in [task_description, slot_name or "", task_archetype or ""] if item))
        if not keywords:
            return []

        scored_siblings = []
        for sibling in self.config.siblings:
            manifest = self._load_sibling_manifest(sibling)
            if manifest is None:
                continue
            relevance = score_manifest_relevance(manifest, keywords, language)
            if relevance >= self.config.federation_relevance_threshold:
                scored_siblings.append((sibling, relevance))

        scored_siblings.sort(key=lambda item: item[1], reverse=True)
        results: list[FederationPacketResult] = []
        seen: set[tuple[str, str]] = set()
        for sibling, relevance in scored_siblings:
            if len(results) >= max_total:
                break
            remaining = max_total - len(results)
            sibling_results = await self._query_sibling_component_cards(
                sibling,
                keywords=keywords,
                slot_name=slot_name,
                task_archetype=task_archetype,
                language=language,
                limit=min(self.config.federation_max_results, remaining),
            )
            for item in sibling_results:
                ident = (item.source_instance, item.component_id)
                if ident in seen:
                    continue
                item.relevance_score = relevance
                results.append(item)
                seen.add(ident)

        results.sort(key=lambda item: item.relevance_score * max(item.match_score, 0.1), reverse=True)
        return results[:max_total]

    def _load_sibling_manifest(self, sibling: Any) -> Optional[dict[str, Any]]:
        """Load a sibling's brain manifest."""
        manifest_path = sibling.manifest_path
        if not manifest_path:
            # Default: manifest sits next to the claw.db
            db_dir = Path(sibling.db_path).parent
            manifest_path = str(db_dir / "brain_manifest.json")
        return load_manifest(Path(manifest_path))

    async def _query_sibling(
        self,
        sibling: Any,
        keywords: list[str],
        language: Optional[str],
        limit: int = 3,
    ) -> list[FederationResult]:
        """Open a read-only connection to a sibling's claw.db and search via FTS5."""
        db_path = Path(sibling.db_path)
        if not db_path.exists():
            logger.warning("Sibling DB not found: %s", db_path)
            return []

        fts_query = _build_safe_fts5_query(keywords)
        if not fts_query:
            return []

        results: list[FederationResult] = []

        # Open read-only (no WAL, no extensions needed for FTS5)
        async with aiosqlite.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            conn.row_factory = aiosqlite.Row

            # FTS5 search
            rows = await conn.execute_fetchall(
                """SELECT methodology_id, rank
                   FROM methodology_fts
                   WHERE methodology_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                [fts_query, limit * 2],  # Fetch extra for language filtering
            )

            for row in rows:
                if len(results) >= limit:
                    break
                mid = row["methodology_id"] if isinstance(row, dict) else row[0]
                fts_rank = abs(float(row["rank"] if isinstance(row, dict) else row[1]))

                # Fetch full methodology
                meth_row = await conn.execute_fetchall(
                    "SELECT * FROM methodologies WHERE id = ?", [mid]
                )
                if not meth_row:
                    continue

                meth_dict = dict(meth_row[0])

                # Language filter
                if language and meth_dict.get("language"):
                    if meth_dict["language"].lower() != language.lower():
                        continue

                # Skip dead/dormant
                state = meth_dict.get("lifecycle_state", "")
                if state in ("dead", "dormant"):
                    continue

                # Parse JSON string fields
                json_list_fields = ("tags", "tech_stack", "files_affected", "parent_ids", "use_immediately_as", "tension_questions")
                json_dict_fields = ("capability_data", "fitness_vector", "prism_data")
                for field in json_list_fields:
                    val = meth_dict.get(field)
                    if isinstance(val, str):
                        try:
                            meth_dict[field] = json.loads(val)
                        except (json.JSONDecodeError, TypeError):
                            meth_dict[field] = []
                    elif val is None:
                        meth_dict[field] = []
                for field in json_dict_fields:
                    val = meth_dict.get(field)
                    if isinstance(val, str):
                        try:
                            meth_dict[field] = json.loads(val)
                        except (json.JSONDecodeError, TypeError):
                            meth_dict[field] = {}
                    elif val is None:
                        meth_dict[field] = {}

                # Ensure created_at has a value (Methodology requires datetime)
                if not meth_dict.get("created_at"):
                    meth_dict["created_at"] = "2026-01-01T00:00:00Z"

                try:
                    methodology = Methodology(**meth_dict)
                except Exception as e:
                    logger.debug("Failed to parse methodology %s from %s: %s", mid, sibling.name, e)
                    continue

                results.append(FederationResult(
                    methodology=methodology,
                    source_instance=sibling.name,
                    source_db_path=str(db_path),
                    fts_rank=fts_rank,
                ))

        logger.info(
            "Queried sibling %s: %d results for %d keywords",
            sibling.name, len(results), len(keywords),
        )
        return results

    async def _query_by_path(
        self,
        db_path_str: str,
        source_name: str,
        keywords: list[str],
        language: Optional[str],
        limit: int = 3,
    ) -> list[FederationResult]:
        """Query a DB by path (used for primary DB). Same logic as _query_sibling."""
        db_path = Path(db_path_str)
        if not db_path.exists():
            return []

        fts_query = _build_safe_fts5_query(keywords)
        if not fts_query:
            return []

        results: list[FederationResult] = []

        async with aiosqlite.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            conn.row_factory = aiosqlite.Row

            rows = await conn.execute_fetchall(
                """SELECT methodology_id, rank
                   FROM methodology_fts
                   WHERE methodology_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                [fts_query, limit * 2],
            )

            for row in rows:
                if len(results) >= limit:
                    break
                mid = row["methodology_id"] if isinstance(row, dict) else row[0]
                fts_rank = abs(float(row["rank"] if isinstance(row, dict) else row[1]))

                meth_row = await conn.execute_fetchall(
                    "SELECT * FROM methodologies WHERE id = ?", [mid]
                )
                if not meth_row:
                    continue

                meth_dict = dict(meth_row[0])

                if language and meth_dict.get("language"):
                    if meth_dict["language"].lower() != language.lower():
                        continue

                state = meth_dict.get("lifecycle_state", "")
                if state in ("dead", "dormant"):
                    continue

                json_list_fields = ("tags", "tech_stack", "files_affected", "parent_ids", "use_immediately_as", "tension_questions")
                json_dict_fields = ("capability_data", "fitness_vector", "prism_data")
                for field in json_list_fields:
                    val = meth_dict.get(field)
                    if isinstance(val, str):
                        try:
                            meth_dict[field] = json.loads(val)
                        except (json.JSONDecodeError, TypeError):
                            meth_dict[field] = []
                    elif val is None:
                        meth_dict[field] = []
                for field in json_dict_fields:
                    val = meth_dict.get(field)
                    if isinstance(val, str):
                        try:
                            meth_dict[field] = json.loads(val)
                        except (json.JSONDecodeError, TypeError):
                            meth_dict[field] = {}
                    elif val is None:
                        meth_dict[field] = {}

                if not meth_dict.get("created_at"):
                    meth_dict["created_at"] = "2026-01-01T00:00:00Z"

                try:
                    methodology = Methodology(**meth_dict)
                except Exception as e:
                    logger.debug("Failed to parse methodology %s from %s: %s", mid, source_name, e)
                    continue

                results.append(FederationResult(
                    methodology=methodology,
                    source_instance=source_name,
                    source_db_path=str(db_path),
                    fts_rank=fts_rank,
                ))

        logger.info(
            "Queried primary DB %s: %d results for %d keywords",
            source_name, len(results), len(keywords),
        )
        return results

    async def _query_sibling_component_cards(
        self,
        sibling: Any,
        *,
        keywords: list[str],
        slot_name: Optional[str],
        task_archetype: Optional[str],
        language: Optional[str],
        limit: int = 3,
    ) -> list[FederationPacketResult]:
        db_path = Path(sibling.db_path)
        if not db_path.exists():
            return []

        like_terms = [f"%{kw.lower()}%" for kw in keywords[:8]]
        if not like_terms:
            return []
        where = " OR ".join(
            [
                "LOWER(title) LIKE ?",
                "LOWER(component_type) LIKE ?",
                "LOWER(abstract_jobs_json) LIKE ?",
                "LOWER(keywords_json) LIKE ?",
            ]
            * len(like_terms)
        )
        params: list[Any] = []
        for term in like_terms:
            params.extend([term, term, term, term])
        if language:
            where = f"({where}) AND (language IS NULL OR LOWER(language) = ?)"
            params.append(language.lower())
        params.append(limit * 4)

        results: list[FederationPacketResult] = []
        async with aiosqlite.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            conn.row_factory = aiosqlite.Row
            try:
                rows = await conn.execute_fetchall(
                    f"""SELECT id, title, component_type, abstract_jobs_json, language,
                               repo, file_path, symbol, family_barcode,
                               provenance_precision, keywords_json
                        FROM component_cards
                        WHERE {where}
                        LIMIT ?""",
                    params,
                )
            except Exception:
                return []

            slot_tokens = set(_extract_keywords(" ".join(item for item in [slot_name or "", task_archetype or ""] if item), max_keywords=8))
            for row in rows:
                title = row["title"] or ""
                abstract_jobs = []
                keywords_json = []
                for field_name, default in (("abstract_jobs_json", []), ("keywords_json", [])):
                    raw = row[field_name]
                    try:
                        parsed = json.loads(raw) if isinstance(raw, str) else (raw or default)
                    except (json.JSONDecodeError, TypeError):
                        parsed = default
                    if field_name == "abstract_jobs_json":
                        abstract_jobs = parsed
                    else:
                        keywords_json = parsed
                match_basis = {title.lower(), (row["component_type"] or "").lower(), *[str(job).lower() for job in abstract_jobs], *[str(item).lower() for item in keywords_json]}
                match_score = 0.35
                if slot_tokens:
                    overlap = sum(1 for token in slot_tokens if any(token in basis for basis in match_basis))
                    match_score += min(overlap * 0.2, 0.5)
                match_type = "direct_fit" if slot_tokens and any(str(job).lower() in slot_tokens or any(token in str(job).lower() for token in slot_tokens) for job in abstract_jobs) else "pattern_transfer"
                results.append(
                    FederationPacketResult(
                        component_id=row["id"],
                        title=title,
                        component_type=row["component_type"] or "helper",
                        abstract_jobs=list(abstract_jobs),
                        language=row["language"],
                        repo=row["repo"] or sibling.name,
                        file_path=row["file_path"] or "",
                        symbol=row["symbol"],
                        family_barcode=row["family_barcode"] or "",
                        provenance_precision=row["provenance_precision"] or "file",
                        source_instance=sibling.name,
                        source_db_path=str(db_path),
                        match_score=match_score,
                        match_type=match_type,
                    )
                )
        results.sort(key=lambda item: item.match_score, reverse=True)
        return results[:limit]

    async def get_sibling_summaries(self) -> list[dict[str, Any]]:
        """Get manifest summaries for all registered siblings.

        Returns list of dicts with name, description, db_exists, manifest,
        relevance info. Used by CLI status commands.
        """
        summaries = []
        for sibling in self.config.siblings:
            db_exists = Path(sibling.db_path).exists()
            manifest = self._load_sibling_manifest(sibling)
            summaries.append({
                "name": sibling.name,
                "description": sibling.description,
                "db_path": sibling.db_path,
                "db_exists": db_exists,
                "manifest": manifest,
                "total_methodologies": manifest.get("total_methodologies", 0) if manifest else 0,
                "top_categories": list(manifest.get("top_categories", {}).keys())[:5] if manifest else [],
                "languages": list(manifest.get("language_breakdown", {}).keys())[:5] if manifest else [],
            })
        return summaries
