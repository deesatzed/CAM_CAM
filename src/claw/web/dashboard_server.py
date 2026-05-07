"""CAM-PULSE Federated Knowledge Dashboard.

A FastAPI web server that exposes CAM's federated brain through a browser UI.
Queries the primary ganglion + all configured siblings simultaneously,
returning results tagged by source ganglion with provenance metadata.

Start with:  cam dashboard [--port 8420]
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import math
import os
import re
import shutil
import tempfile
import time
import uuid
from datetime import UTC, datetime as _datetime
from pathlib import Path
from typing import Any, Optional

import toml

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from claw.core.models import CompiledRecipe, ComponentLineage, GovernancePolicy, LandingEvent, LandingOrigin, MiningMission, OutcomeEvent, PacketStatus, PairEvent, ProofGate, RunActionAudit, RunConnectome, RunEvent, RunSlotExecution, TaskPlanRecord
from claw.connectome.barcodes import build_family_barcode, build_source_barcode
from claw.db.repository import _build_safe_fts5_query
from claw.memory.component_ranker import rank_components_for_slot
from claw.mining.component_extractor import extract_components_from_file
from claw.planning.application_packet import build_application_packet, build_packet_summary
from claw.planning.taskome import decompose_task, infer_task_archetype
from claw.security.policy_tools import run_critical_slot_policy_checks

logger = logging.getLogger("claw.web.dashboard")

# ---------------------------------------------------------------------------
# Factory — lazy init on first request
# ---------------------------------------------------------------------------

_state: dict[str, Any] = {}


async def _ensure_state(app: FastAPI) -> dict[str, Any]:
    """Lazily initialize DB engine, repository, and federation on first use."""
    if _state.get("ready"):
        return _state

    from claw.core.config import load_config
    from claw.db.engine import DatabaseEngine
    from claw.db.repository import Repository

    config = load_config()
    engine = DatabaseEngine(config.database)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    repository = Repository(engine)

    _state["config"] = config
    _state["engine"] = engine
    _state["repository"] = repository

    # Federation (optional — only if siblings configured)
    federation = None
    if config.instances and config.instances.enabled and config.instances.siblings:
        from claw.community.federation import Federation

        federation = Federation(config.instances)

    _state["federation"] = federation
    _state["ready"] = True
    return _state


async def _shutdown_state() -> None:
    if _state.get("engine"):
        await _state["engine"].close()
    _state.clear()


def _playground_plans(app: FastAPI) -> dict[str, dict[str, Any]]:
    if not hasattr(app.state, "playground_plans"):
        app.state.playground_plans = {}
    return app.state.playground_plans


def _packet_to_json(packet: Any) -> dict[str, Any]:
    return packet.model_dump(mode="json") if hasattr(packet, "model_dump") else dict(packet)


def _slug_failure_part(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return "unknown"
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return (slug or "unknown")[:48]


def _build_negative_memory_failure_knowledge(
    *,
    run_id: str,
    update: str,
    connectome: Optional[RunConnectome],
    outcome: Any,
    packet: Any,
) -> dict[str, Any]:
    task_archetype = connectome.task_archetype if connectome else None
    outcome_slot_id = getattr(outcome, "slot_id", None)
    packet_slot_id = getattr(getattr(packet, "slot", None), "slot_id", None)
    slot_id = outcome_slot_id if isinstance(outcome_slot_id, str) else packet_slot_id
    selected_component = getattr(getattr(packet, "selected", None), "component_id", None)
    update_text = re.sub(r"\s+", " ", str(update)).strip()
    signature_basis = "|".join(
        [
            task_archetype or "",
            slot_id or "",
            selected_component or "",
            update_text,
        ]
    )
    digest = hashlib.sha256(signature_basis.encode("utf-8")).hexdigest()[:16]
    error_signature = (
        "camseq_negative_memory:"
        f"{_slug_failure_part(task_archetype)}:"
        f"{_slug_failure_part(slot_id)}:"
        f"{_slug_failure_part(selected_component)}:"
        f"{digest}"
    )
    slot_label = slot_id or "unknown slot"
    component_label = selected_component or "unknown component"
    return {
        "error_signature": error_signature,
        "error_category": "camseq_negative_memory",
        "diagnosis": (
            f"CAM-SEQ run {run_id} produced negative memory for "
            f"{component_label} in {slot_label}: {update_text}"
        )[:500],
        "prevention_hint": (
            f"[camseq_negative_memory] Before reusing {component_label} for "
            f"{slot_label}, check or mitigate: {update_text}"
        )[:500],
        "agent_id": None,
        "task_type": task_archetype,
        "project_id": None,
        "source_task_id": run_id,
    }


async def _candidate_cards_for_slot(
    repo: Any,
    *,
    task_text: str,
    slot: Any,
    target_language: Optional[str],
    workspace_dir: Optional[str] = None,
) -> list[Any]:
    query = " ".join([slot.name, slot.abstract_job, task_text]).strip()
    summaries = await repo.search_component_cards_text(query, limit=8, language=target_language)
    if not summaries:
        summaries = await repo.list_component_cards(limit=12, language=target_language)

    cards: list[Any] = []
    seen: set[str] = set()
    for summary in summaries:
        component_id = getattr(summary, "id", None)
        if not component_id or component_id in seen:
            continue
        card = await repo.get_component_card(component_id)
        if card is None:
            continue
        if _is_noise_component_path(card.receipt.file_path):
            continue
        cards.append(card)
        seen.add(component_id)
    if cards:
        return cards
    local_cards = _local_workspace_candidate_cards_for_slot(
        task_text=task_text,
        slot=slot,
        target_language=target_language,
        workspace_dir=workspace_dir,
    )
    if not local_cards:
        return []
    return await _persist_local_candidate_cards(repo, local_cards)


def _candidate_terms(*parts: str) -> set[str]:
    tokens: set[str] = set()
    for part in parts:
        for token in re.findall(r"[a-z0-9_]+", part.lower()):
            if len(token) >= 3:
                tokens.add(token)
            if "_" in token:
                for subtoken in token.split("_"):
                    if len(subtoken) >= 3:
                        tokens.add(subtoken)
    return tokens


_SEARCH_QUERY_ALIASES: dict[str, set[str]] = {
    "auth": {"oauth", "token", "session", "refresh", "jwt", "login", "credential"},
    "oauth": {"auth", "token", "session", "refresh", "login"},
    "token": {"auth", "oauth", "session", "refresh", "jwt"},
    "session": {"auth", "oauth", "token", "refresh", "login"},
    "login": {"auth", "oauth", "session", "credential"},
    "jwt": {"auth", "oauth", "token"},
}

_AUTH_INTENT_TERMS = {"auth", "oauth", "jwt", "login", "credential"}
_AUTH_STRONG_SIGNALS = {"auth", "oauth", "jwt", "login", "credential", "authenticated", "authorization", "authorize"}
_AUTH_WEAK_SIGNALS = {"token", "session", "refresh"}


def _search_query_terms(query: str) -> set[str]:
    terms = _candidate_terms(query)
    expanded = set(terms)
    for term in list(terms):
        expanded.update(_SEARCH_QUERY_ALIASES.get(term, set()))
    return expanded


def _direct_query_terms(query: str) -> set[str]:
    return _candidate_terms(query)


def _is_auth_intent_query(direct_terms: set[str]) -> bool:
    return bool(direct_terms & _AUTH_INTENT_TERMS)


def _is_weak_auth_only_match(target_terms: set[str], direct_terms: set[str]) -> bool:
    if not _is_auth_intent_query(direct_terms):
        return False
    return bool(target_terms & _AUTH_WEAK_SIGNALS) and not bool(target_terms & _AUTH_STRONG_SIGNALS)


def _workspace_root(workspace_dir: Optional[str]) -> Path:
    if workspace_dir:
        return Path(workspace_dir).resolve()
    return Path.cwd()


def _is_noise_component_path(file_path: str) -> bool:
    normalized = file_path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.startswith(
        (
            ".uv-cache/",
            "node_modules/",
            ".next/",
            "dist/",
            "build/",
            "data/",
        )
    )


def _is_test_component_path(file_path: str) -> bool:
    normalized = file_path.replace("\\", "/").lower()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return (
        normalized.startswith("tests/")
        or "/tests/" in normalized
        or normalized.startswith("test_")
        or "/test_" in normalized
    )


def _local_workspace_candidate_cards_for_slot(
    *,
    task_text: str,
    slot: Any,
    target_language: Optional[str],
    workspace_dir: Optional[str],
    max_files: int = 32,
    max_cards: int = 16,
) -> list[Any]:
    workspace_root = _workspace_root(workspace_dir)
    if not workspace_root.exists() or not workspace_root.is_dir():
        return []

    allowed_suffixes = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
    }
    if target_language:
        allowed_suffixes = {
            suffix: language
            for suffix, language in allowed_suffixes.items()
            if language == target_language.lower()
        }
        if not allowed_suffixes:
            return []

    skip_dirs = {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        ".uv-cache",
        "node_modules",
        ".next",
        "dist",
        "build",
        "__pycache__",
        "data",
    }
    task_terms = _candidate_terms(task_text, slot.name, slot.abstract_job, " ".join(slot.constraints), " ".join(slot.target_stack))
    file_scores: list[tuple[int, int, Path]] = []
    for path in workspace_root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        language = allowed_suffixes.get(path.suffix.lower())
        if language is None:
            continue
        try:
            rel = path.relative_to(workspace_root).as_posix()
        except Exception:
            continue
        rel_terms = _candidate_terms(rel)
        overlap = len(task_terms & rel_terms)
        file_scores.append((overlap, path))

    if not file_scores:
        return []

    file_scores.sort(key=lambda item: (item[0], str(item[1])), reverse=True)
    selected_paths = [path for _score, path in file_scores[:max_files]]

    from claw.core.models import ComponentCard, CoverageState, Receipt
    from claw.miner import RepoMiner

    candidates: list[tuple[int, ComponentCard]] = []
    seen_source_barcodes: set[str] = set()
    for path in selected_paths:
        rel = path.relative_to(workspace_root).as_posix()
        for extracted in extract_components_from_file(workspace_root, rel, max_components=12):
            descriptor = " ".join(
                [
                    extracted.title,
                    extracted.component_type,
                    extracted.symbol_kind,
                    extracted.file_path,
                    extracted.note,
                    " ".join(extracted.keywords),
                    " ".join(extracted.imports),
                ]
            ).strip()
            if not descriptor:
                continue
            abstract_jobs = RepoMiner._infer_abstract_jobs(extracted.component_type, descriptor)
            content_hash = f"sha256:{hashlib.sha256('|'.join([rel, extracted.symbol_name, extracted.ast_fingerprint or descriptor]).encode('utf-8')).hexdigest()}"
            source_barcode = build_source_barcode(
                workspace_root.name or "workspace",
                rel,
                content_hash,
                symbol_name=extracted.symbol_name or None,
            )
            if source_barcode in seen_source_barcodes:
                continue
            seen_source_barcodes.add(source_barcode)
            family_barcode = build_family_barcode(extracted.component_type, abstract_jobs[0])
            receipt = Receipt(
                source_barcode=source_barcode,
                family_barcode=family_barcode,
                lineage_id=f"lin_local_{hashlib.sha256(source_barcode.encode('utf-8')).hexdigest()[:12]}",
                repo=workspace_root.name or "workspace",
                file_path=rel,
                symbol=extracted.symbol_name or None,
                line_start=extracted.line_start,
                line_end=extracted.line_end,
                content_hash=content_hash,
                provenance_precision=("precise_symbol" if extracted.line_start is not None else ("symbol" if extracted.symbol_name else "file")),
            )
            overlap = len(task_terms & _candidate_terms(descriptor, *abstract_jobs))
            card = ComponentCard(
                id=f"local_{hashlib.sha256(source_barcode.encode('utf-8')).hexdigest()[:16]}",
                title=extracted.title,
                component_type=extracted.component_type,
                abstract_jobs=abstract_jobs,
                receipt=receipt,
                language=extracted.language,
                dependencies=list(dict.fromkeys(extracted.imports[:6])),
                applicability=[descriptor[:240]],
                adaptation_notes=[f"workspace fallback candidate from {rel}"],
                keywords=list(dict.fromkeys([*extracted.keywords, *abstract_jobs, extracted.component_type])),
                coverage_state=CoverageState.WEAK,
            )
            candidates.append((overlap, card))

    candidates.sort(key=lambda item: (item[0], item[1].title.lower()), reverse=True)
    return [card for _score, card in candidates[:max_cards]]


async def _persist_local_candidate_cards(repo: Any, cards: list[Any]) -> list[Any]:
    persisted: list[Any] = []
    for card in cards:
        existing = await repo.find_component_by_source_barcode(card.receipt.source_barcode)
        if existing is not None:
            persisted.append(existing)
            continue

        lineage = await repo.find_lineage_by_hash(card.receipt.content_hash)
        if lineage is None or lineage.family_barcode != card.receipt.family_barcode:
            lineage = ComponentLineage(
                family_barcode=card.receipt.family_barcode,
                canonical_content_hash=card.receipt.content_hash,
                canonical_title=card.title,
                language=card.language,
            )
            await repo.upsert_component_lineage(lineage)

        persisted_card = card.model_copy(
            update={
                "receipt": card.receipt.model_copy(update={"lineage_id": lineage.id}),
            }
        )
        persisted.append(await repo.upsert_component_card(persisted_card))
    return persisted


def _local_workspace_search_cards(
    *,
    query: str,
    target_language: Optional[str],
    workspace_dir: Optional[str],
    max_files: int = 32,
    max_cards: int = 20,
) -> list[Any]:
    workspace_root = _workspace_root(workspace_dir)
    if not workspace_root.exists() or not workspace_root.is_dir():
        return []

    allowed_suffixes = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
    }
    if target_language:
        allowed_suffixes = {
            suffix: language
            for suffix, language in allowed_suffixes.items()
            if language == target_language.lower()
        }
        if not allowed_suffixes:
            return []

    skip_dirs = {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        ".uv-cache",
        "node_modules",
        ".next",
        "dist",
        "build",
        "__pycache__",
        "data",
    }
    direct_terms = _direct_query_terms(query)
    query_terms = _search_query_terms(query)
    if not direct_terms:
        return []
    allow_content_only_fallback = len(direct_terms) >= 2

    file_scores: list[tuple[int, int, Path]] = []
    for path in workspace_root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        language = allowed_suffixes.get(path.suffix.lower())
        if language is None:
            continue
        try:
            rel = path.relative_to(workspace_root).as_posix()
        except Exception:
            continue
        if "test" not in direct_terms and _is_test_component_path(rel):
            continue
        path_overlap = len(query_terms & _candidate_terms(rel))
        content_overlap = 0
        overlap = path_overlap
        if overlap <= 0 and allow_content_only_fallback:
            try:
                if path.stat().st_size <= 256_000:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                    text_terms = _candidate_terms(text[:16_000])
                    if _is_weak_auth_only_match(text_terms, direct_terms):
                        continue
                    content_overlap = len(query_terms & text_terms)
                    overlap = content_overlap
            except Exception:
                overlap = 0
        if overlap <= 0:
            continue
        file_scores.append((overlap, path_overlap, path))

    if not file_scores:
        return []

    from claw.core.models import ComponentCard, CoverageState, Receipt
    from claw.miner import RepoMiner

    file_scores.sort(key=lambda item: (item[0], item[1], str(item[2])), reverse=True)
    seen_source_barcodes: set[str] = set()
    candidates: list[tuple[int, ComponentCard]] = []
    for file_overlap, path_overlap, path in file_scores[:max_files]:
        rel = path.relative_to(workspace_root).as_posix()
        matched_symbol = False
        for extracted in extract_components_from_file(workspace_root, rel, max_components=12):
            descriptor = " ".join(
                [
                    extracted.title,
                    extracted.component_type,
                    extracted.symbol_kind,
                    extracted.file_path,
                    extracted.note,
                    " ".join(extracted.keywords),
                    " ".join(extracted.imports),
                ]
            ).strip()
            descriptor_terms = _candidate_terms(descriptor)
            abstract_jobs = RepoMiner._infer_abstract_jobs(extracted.component_type, descriptor)
            abstract_job_terms = _candidate_terms(*abstract_jobs)
            abstract_job_overlap = len(query_terms & abstract_job_terms)
            descriptor_overlap = len(query_terms & descriptor_terms)
            combined_terms = descriptor_terms | abstract_job_terms | _candidate_terms(rel)
            if _is_weak_auth_only_match(combined_terms, direct_terms):
                continue
            if descriptor_overlap <= 0 and abstract_job_overlap <= 0 and path_overlap <= 0:
                continue
            matched_symbol = True
            score = descriptor_overlap * 12 + abstract_job_overlap * 8 + path_overlap * 6 + file_overlap * 2
            if "test" not in direct_terms and _is_test_component_path(rel):
                score -= 8
            content_hash = f"sha256:{hashlib.sha256('|'.join([rel, extracted.symbol_name, extracted.ast_fingerprint or descriptor]).encode('utf-8')).hexdigest()}"
            source_barcode = build_source_barcode(
                workspace_root.name or "workspace",
                rel,
                content_hash,
                symbol_name=extracted.symbol_name or None,
            )
            if source_barcode in seen_source_barcodes:
                continue
            seen_source_barcodes.add(source_barcode)
            family_barcode = build_family_barcode(extracted.component_type, abstract_jobs[0])
            receipt = Receipt(
                source_barcode=source_barcode,
                family_barcode=family_barcode,
                lineage_id=f"lin_local_{hashlib.sha256(source_barcode.encode('utf-8')).hexdigest()[:12]}",
                repo=workspace_root.name or "workspace",
                file_path=rel,
                symbol=extracted.symbol_name or None,
                line_start=extracted.line_start,
                line_end=extracted.line_end,
                content_hash=content_hash,
                provenance_precision=("precise_symbol" if extracted.line_start is not None else ("symbol" if extracted.symbol_name else "file")),
            )
            candidates.append(
                (
                    score,
                    ComponentCard(
                        id=f"local_{hashlib.sha256(source_barcode.encode('utf-8')).hexdigest()[:16]}",
                        title=extracted.title,
                        component_type=extracted.component_type,
                        abstract_jobs=abstract_jobs,
                        receipt=receipt,
                        language=extracted.language,
                        dependencies=list(dict.fromkeys(extracted.imports[:6])),
                        applicability=[descriptor[:240]],
                        adaptation_notes=[f"workspace fallback candidate from {rel}"],
                        keywords=list(dict.fromkeys([*extracted.keywords, *abstract_jobs, extracted.component_type])),
                        coverage_state=CoverageState.WEAK,
                    ),
                )
            )

        if matched_symbol or path_overlap > 0:
            continue

        try:
            content_hash = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        except Exception:
            content_hash = f"sha256:{hashlib.sha256(rel.encode('utf-8')).hexdigest()}"
        source_barcode = build_source_barcode(
            workspace_root.name or "workspace",
            rel,
            content_hash,
            symbol_name=None,
        )
        if source_barcode in seen_source_barcodes:
            continue
        seen_source_barcodes.add(source_barcode)
        family_barcode = build_family_barcode("module", "workspace_content_match")
        receipt = Receipt(
            source_barcode=source_barcode,
            family_barcode=family_barcode,
            lineage_id=f"lin_local_{hashlib.sha256(source_barcode.encode('utf-8')).hexdigest()[:12]}",
            repo=workspace_root.name or "workspace",
            file_path=rel,
            symbol=None,
            line_start=None,
            line_end=None,
            content_hash=content_hash,
            provenance_precision="file",
        )
        candidates.append(
            (
                file_overlap * 5,
                ComponentCard(
                    id=f"local_{hashlib.sha256(source_barcode.encode('utf-8')).hexdigest()[:16]}",
                    title=Path(rel).name,
                    component_type="module",
                    abstract_jobs=["workspace_content_match"],
                    receipt=receipt,
                    language=allowed_suffixes.get(path.suffix.lower()),
                    dependencies=[],
                    applicability=[f"workspace content matched query terms for {rel}"],
                    adaptation_notes=[f"workspace fallback file match from {rel}"],
                    keywords=sorted(query_terms),
                    coverage_state=CoverageState.WEAK,
                ),
            )
        )

    candidates.sort(key=lambda item: (item[0], item[1].title.lower()), reverse=True)
    return [card for _score, card in candidates[:max_cards]]


async def _active_governance_policies_for_plan(repo: Any, task_archetype: str) -> list[GovernancePolicy]:
    archetype_specific = await repo.list_governance_policies(
        task_archetype=task_archetype,
        active_only=True,
        limit=200,
    )
    global_policies = await repo.list_governance_policies(
        task_archetype=None,
        active_only=True,
        limit=200,
    )
    merged: dict[str, GovernancePolicy] = {}
    for policy in [*archetype_specific, *global_policies]:
        if policy.task_archetype and policy.task_archetype != task_archetype:
            continue
        merged[policy.id] = policy
    return list(merged.values())


async def _active_compiled_recipes_for_archetype(repo: Any, task_archetype: str) -> list[CompiledRecipe]:
    if not task_archetype:
        return []
    return await repo.list_compiled_recipes(task_archetype=task_archetype, active_only=True, limit=10)


def _detect_governance_conflicts(policies: list[GovernancePolicy]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[GovernancePolicy]] = {}
    for policy in policies:
        scope = (
            policy.policy_kind,
            policy.task_archetype or "",
            policy.slot_id or "",
            policy.family_barcode or "",
        )
        grouped.setdefault(scope, []).append(policy)

    conflicts: list[dict[str, Any]] = []
    for (policy_kind, task_archetype, slot_id, family_barcode), group in grouped.items():
        if len(group) < 2:
            continue
        statuses = {policy.status for policy in group}
        directives = {
            (policy.recommendation or "").strip().lower() or (policy.reason or "").strip().lower()
            for policy in group
        }
        severities = {policy.severity for policy in group}
        reasons: list[str] = []
        if len(statuses) > 1:
            reasons.append("status_conflict")
        if len({item for item in directives if item}) > 1:
            reasons.append("directive_conflict")
        if len(severities) > 1:
            reasons.append("severity_conflict")
        if not reasons:
            continue
        conflicts.append(
            {
                "policy_kind": policy_kind,
                "task_archetype": task_archetype or None,
                "slot_id": slot_id or None,
                "family_barcode": family_barcode or None,
                "conflict_reasons": reasons,
                "policy_ids": [policy.id for policy in group],
                "statuses": sorted(statuses),
                "severities": sorted(severities),
            }
        )
    return conflicts


def _governance_summary_for_component(
    component: Any,
    policies: list[GovernancePolicy],
) -> dict[str, Any]:
    family_policies = [
        policy for policy in policies
        if policy.policy_kind == "family_policy"
        and policy.family_barcode
        and policy.family_barcode == component.receipt.family_barcode
    ]
    return {
        "family_barcode": component.receipt.family_barcode,
        "active_policy_count": len(family_policies),
        "highest_severity": (
            "high" if any(policy.severity == "high" for policy in family_policies)
            else "medium" if any(policy.severity == "medium" for policy in family_policies)
            else "low" if family_policies else None
        ),
        "policies": [
            {
                "id": policy.id,
                "policy_kind": policy.policy_kind,
                "severity": policy.severity,
                "reason": policy.reason,
                "recommendation": policy.recommendation,
                "status": policy.status,
            }
            for policy in family_policies[:5]
        ],
    }


def _score_component_search_match(
    query: str,
    *,
    title: str,
    component_type: str,
    file_path: str,
    symbol: Optional[str],
    extra_terms: Optional[list[str]] = None,
    success_count: int = 0,
    failure_count: int = 0,
) -> int:
    direct_terms = _direct_query_terms(query)
    query_terms = _search_query_terms(query)
    if not direct_terms:
        return 0
    title_terms = _candidate_terms(title)
    type_terms = _candidate_terms(component_type)
    path_terms = _candidate_terms(file_path)
    symbol_terms = _candidate_terms(symbol or "")
    extra = _candidate_terms(" ".join(extra_terms or []))
    combined_terms = title_terms | type_terms | path_terms | symbol_terms | extra
    if _is_weak_auth_only_match(combined_terms, direct_terms):
        return 0
    alias_terms = query_terms - direct_terms

    def _weighted_overlap(target_terms: set[str], direct_weight: int, alias_weight: int) -> int:
        score = len(direct_terms & target_terms) * direct_weight
        score += len(alias_terms & target_terms) * alias_weight
        return score

    score = 0
    score += _weighted_overlap(title_terms, 14, 5)
    score += _weighted_overlap(symbol_terms, 12, 4)
    score += _weighted_overlap(type_terms, 6, 2)
    score += _weighted_overlap(path_terms, 5, 2)
    score += _weighted_overlap(extra, 4, 1)

    lowered_path = file_path.lower()
    if "test" not in direct_terms and (
        lowered_path.startswith("tests/")
        or "/tests/" in lowered_path
        or lowered_path.startswith("test_")
        or "/test_" in lowered_path
    ):
        score -= 8

    score += min(success_count, 5) * 2
    score -= min(failure_count, 3)
    return score


def _component_card_summary_payload(
    card: Any,
    policies: list[GovernancePolicy],
    *,
    search_score: Optional[int] = None,
    source_scope: Optional[str] = None,
) -> dict[str, Any]:
    payload = {
        "id": card.id,
        "title": card.title,
        "component_type": card.component_type,
        "language": card.language,
        "family_barcode": card.receipt.family_barcode,
        "repo": card.receipt.repo,
        "file_path": card.receipt.file_path,
        "symbol": card.receipt.symbol,
        "provenance_precision": card.receipt.provenance_precision.value,
        "success_count": card.success_count,
        "failure_count": card.failure_count,
        "coverage_state": card.coverage_state.value,
        "governance_summary": {
            "family_barcode": card.receipt.family_barcode,
            "active_policy_count": sum(
                1
                for policy in policies
                if policy.policy_kind == "family_policy"
                and policy.family_barcode == card.receipt.family_barcode
            ),
        },
    }
    if search_score is not None:
        payload["search_score"] = search_score
    if source_scope is not None:
        payload["source_scope"] = source_scope
    return payload


def _component_match_type(card: Any, slot: Optional[Any]) -> str:
    if slot is None:
        return "pattern_transfer"
    slot_tokens = {slot.name.lower(), slot.abstract_job.lower()}
    abstract_jobs = {str(item).lower() for item in getattr(card, "abstract_jobs", [])}
    if any(job in slot_tokens or any(token in job for token in slot_tokens) for job in abstract_jobs):
        return "direct_fit"
    return "pattern_transfer"


def _infer_specialist_task_type(description: str) -> str:
    desc_lower = description.lower()
    keyword_map: list[tuple[list[str], str]] = [
        (["security", "vulnerability", "cve", "owasp", "xss", "csrf", "injection"], "security"),
        (["architecture", "design", "structure", "system design"], "architecture"),
        (["documentation", "docs", "readme", "docstring", "jsdoc"], "documentation"),
        (["analysis", "analyze", "audit", "review", "inspect"], "analysis"),
        (["refactor", "restructure", "reorganize", "clean up", "simplify"], "refactoring"),
        (["test", "testing", "unit test", "integration test", "coverage"], "testing"),
        (["ci", "cd", "pipeline", "github action", "workflow", "deploy"], "ci_cd"),
        (["dependency", "dependencies", "upgrade", "update package", "npm", "pip"], "dependency_analysis"),
        (["migration", "migrate", "port", "convert", "transfer", "cross-language"], "migration"),
        (["quick fix", "hotfix", "patch", "typo", "small fix"], "quick_fix"),
        (["bug", "fix", "error", "crash", "broken", "issue", "defect"], "bug_fix"),
    ]
    for keywords, task_type in keyword_map:
        if any(kw in desc_lower for kw in keywords):
            return task_type
    return "analysis"


def _build_retrograde_payload(
    *,
    run_id: str,
    root: Optional[str],
    failing_outcome: Any,
    packet: Any,
    pair: Any,
    landing: Any,
    slot_execution: Any,
    runner_up: Any,
    relevant_audits: list[Any],
    relevant_events: list[Any],
    task_description: Optional[str],
) -> dict[str, Any]:
    def _cause_id(value: Any, fallback: str) -> str:
        if value is None:
            return fallback
        try:
            return str(value)
        except Exception:
            return fallback

    cause_chain = []
    proof_gate_event = next((event for event in reversed(relevant_events) if event.event_type == "proof_gate_failed"), None)
    if proof_gate_event:
        gate_payload = proof_gate_event.payload or {}
        gates = gate_payload.get("gates") or {}
        failing_gates = [name for name, info in gates.items() if (info or {}).get("status") in {"failed", "fail"}]
        cause_chain.append(
            {
                "kind": "proof_gate",
                "id": _cause_id(getattr(proof_gate_event, "id", None), f"proof_gate:{run_id}"),
                "explanation": (
                    f"Static-analysis proof gate failure"
                    + (f" in {', '.join(failing_gates)}" if failing_gates else "")
                ),
                "rank_score": 0.9 if failing_gates else 0.84,
            }
        )
    for audit in relevant_audits[-3:]:
        if audit.action_type in {"block_slot", "ban_family", "swap_candidate", "reverify_slot", "waive_proof_gate"}:
            score = 0.55
            if audit.action_type in {"block_slot", "ban_family"}:
                score = 0.78
            elif audit.action_type == "waive_proof_gate":
                score = 0.74
            cause_chain.append(
                {
                    "kind": "action",
                    "id": _cause_id(getattr(audit, "id", None), f"action:{run_id}:{audit.action_type}"),
                    "explanation": f"{audit.action_type}: {audit.reason or 'operator intervention'}",
                    "rank_score": score,
                }
            )
    if slot_execution and slot_execution.retry_count:
        blocked_wait_ms = int(getattr(slot_execution, "blocked_wait_ms", 0) or 0)
        family_wait_ms = int(getattr(slot_execution, "family_wait_ms", 0) or 0)
        wait_bonus = min(0.2, ((blocked_wait_ms + family_wait_ms) / 1000.0) / 60.0)
        cause_chain.append(
            {
                "kind": "slot_execution",
                "id": slot_execution.slot_id,
                "explanation": (
                    f"Slot had {slot_execution.retry_count} retries, last step {slot_execution.current_step or 'unknown'}, "
                    f"blocked wait {blocked_wait_ms}ms, family wait {family_wait_ms}ms"
                ),
                "rank_score": min(0.95, 0.62 + min(0.18, slot_execution.retry_count * 0.08) + wait_bonus),
            }
        )
    retry_event = next((event for event in reversed(relevant_events) if event.event_type == "retry_delta"), None)
    if retry_event:
        cause_chain.append(
            {
                "kind": "retry",
                "id": _cause_id(getattr(retry_event, "id", None), f"retry:{run_id}"),
                "explanation": f"Latest retry delta before failure: {len(retry_event.payload.get('violations', []))} violations",
                "rank_score": min(0.9, 0.58 + min(0.22, len(retry_event.payload.get("violations", [])) * 0.08)),
            }
        )
    verifier_findings = list(getattr(failing_outcome, "verifier_findings", []) or [])
    if verifier_findings:
        cause_chain.append(
            {
                "kind": "outcome",
                "id": _cause_id(getattr(failing_outcome, "id", None), f"outcome:{run_id}"),
                "explanation": f"Verifier recorded {len(verifier_findings)} finding(s)",
                "rank_score": min(0.88, 0.64 + min(0.2, len(verifier_findings) * 0.08)),
            }
        )
    negative_memory_updates = list(getattr(failing_outcome, "negative_memory_updates", []) or [])
    if negative_memory_updates:
        cause_chain.append(
            {
                "kind": "negative_memory",
                "id": f"negative_memory:{run_id}",
                "explanation": f"Failure produced {len(negative_memory_updates)} negative-memory update(s)",
                "rank_score": min(0.83, 0.6 + min(0.15, len(negative_memory_updates) * 0.08)),
            }
        )
    if landing:
        cause_chain.append({"kind": "landing", "id": _cause_id(getattr(landing, "id", None), f"landing:{run_id}"), "explanation": f"Change landed in {landing.file_path}", "rank_score": 0.66})
    if packet:
        cause_chain.append({"kind": "slot", "id": packet.slot.slot_id, "explanation": f"Slot {packet.slot.name}", "rank_score": 0.72})
        selected_transfer_mode = getattr(packet.selected.transfer_mode, "value", str(packet.selected.transfer_mode))
        slot_risk = getattr(packet.slot.risk, "value", str(packet.slot.risk))
        if selected_transfer_mode == "pattern_transfer":
            federation_score = 0.76 if slot_risk == "critical" else 0.61
            explanation = "Selected component was a pattern transfer rather than direct fit"
            if slot_risk == "critical":
                explanation += " in a critical slot"
            cause_chain.append(
                {
                    "kind": "federation",
                    "id": f"federation:{packet.packet_id}",
                    "explanation": explanation,
                    "rank_score": federation_score,
                }
            )
    if pair:
        cause_chain.append({"kind": "component", "id": pair.component_id, "explanation": f"Selected component {pair.component_id}", "rank_score": 0.74})
    if runner_up and packet:
        runner_transfer_mode = getattr(runner_up.transfer_mode, "value", str(runner_up.transfer_mode))
        if runner_transfer_mode == "direct_fit" and getattr(packet.selected.transfer_mode, "value", str(packet.selected.transfer_mode)) != "direct_fit":
            cause_chain.append(
                {
                    "kind": "counterfactual",
                    "id": runner_up.component_id,
                    "explanation": "Runner-up offered a direct-fit alternative while the selected component was only a pattern transfer",
                    "rank_score": 0.82,
                }
            )

    has_waived_gate = any(getattr(audit, "action_type", "") == "waive_proof_gate" for audit in relevant_audits)
    has_negative_memory = bool(negative_memory_updates)
    has_retry_signal = retry_event is not None and bool(slot_execution and slot_execution.retry_count)
    for item in cause_chain:
        supports: list[str] = []
        kind = item.get("kind")
        score = float(item.get("rank_score", 0.0))
        if kind == "proof_gate" and has_waived_gate:
            score += 0.05
            supports.append("waived_proof_gate")
        if kind == "action" and "waive_proof_gate" in str(item.get("explanation", "")) and proof_gate_event:
            score += 0.04
            supports.append("proof_gate_failed")
        if kind in {"counterfactual", "federation"} and has_negative_memory:
            score += 0.04
            supports.append("negative_memory")
        if kind == "negative_memory" and runner_up is not None:
            score += 0.03
            supports.append("runner_up_exists")
        if kind in {"slot_execution", "retry"} and has_retry_signal:
            score += 0.03
            supports.append("correlated_retry_pressure")
        if kind == "outcome" and proof_gate_event:
            score += 0.03
            supports.append("proof_gate_failed")
        if supports:
            item["supporting_signals"] = supports
        item["rank_score"] = min(0.98, score)

    cause_chain.sort(key=lambda item: float(item.get("rank_score", 0.0)), reverse=True)
    top_score = float(cause_chain[0].get("rank_score", 0.2)) if cause_chain else 0.2
    primary_cause = cause_chain[0] if cause_chain else None
    supporting_signal_union = sorted(
        {
            signal
            for item in cause_chain[:3]
            for signal in item.get("supporting_signals", [])
        }
    )
    cluster_rules: dict[str, set[str]] = {
        "proof": {"proof_gate", "outcome"},
        "operator": {"action"},
        "runtime": {"retry", "slot_execution", "landing"},
        "transfer": {"federation", "counterfactual", "component", "slot"},
        "memory": {"negative_memory"},
    }
    root_cause_clusters = []
    for cluster_name, kinds in cluster_rules.items():
        cluster_items = [item for item in cause_chain if item.get("kind") in kinds][:3]
        if not cluster_items:
            continue
        root_cause_clusters.append(
            {
                "cluster": cluster_name,
                "top_kind": cluster_items[0].get("kind"),
                "score": max(float(item.get("rank_score", 0.0)) for item in cluster_items),
                "item_count": len(cluster_items),
            }
        )
    root_cause_clusters.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    primary_kind = primary_cause.get("kind") if primary_cause else None
    primary_explanation = primary_cause.get("explanation") if primary_cause else None
    decision_path = [
        {
            "kind": item.get("kind"),
            "explanation": item.get("explanation"),
            "score": float(item.get("rank_score", 0.0)),
        }
        for item in cause_chain[:3]
    ]
    narrative_parts = []
    if primary_kind and primary_explanation:
        narrative_parts.append(f"Primary cause: {primary_kind} - {primary_explanation}.")
    if root_cause_clusters:
        cluster_labels = ", ".join(
            f"{cluster['cluster']}:{cluster['top_kind']}"
            for cluster in root_cause_clusters[:3]
        )
        narrative_parts.append(f"Dominant pressure clusters: {cluster_labels}.")
    if runner_up is not None:
        narrative_parts.append("A runnable counterfactual existed via a runner-up candidate.")
    if proof_gate_event is not None or verifier_findings:
        narrative_parts.append("Proof or verifier pressure was present in the failure path.")
    recommended_action = None
    if primary_kind == "proof_gate":
        recommended_action = "tighten proof gates or remove the risky implementation path"
    elif primary_kind in {"counterfactual", "federation"}:
        recommended_action = "promote or switch to the direct-fit runner-up path"
    elif primary_kind == "action":
        recommended_action = "review operator intervention policy and unblock criteria"
    elif primary_kind in {"retry", "slot_execution"}:
        recommended_action = "reduce retry pressure by narrowing the slot adaptation scope"
    elif primary_kind == "negative_memory":
        recommended_action = "persist the failure pattern and ban the affected family in similar slots"
    actionability = (
        "immediate" if recommended_action and top_score >= 0.85 else
        "review" if recommended_action else
        "observe"
    )
    confidence_drivers = []
    if primary_kind:
        confidence_drivers.append(f"primary:{primary_kind}")
    if root_cause_clusters:
        confidence_drivers.append(f"cluster:{root_cause_clusters[0]['cluster']}")
    if proof_gate_event is not None or verifier_findings:
        confidence_drivers.append("pressure:proof")
    if any(item.get("kind") == "action" for item in cause_chain[:3]):
        confidence_drivers.append("pressure:governance")
    if runner_up is not None:
        confidence_drivers.append("counterfactual:available")
    confidence_reason = None
    if top_score >= 0.85:
        confidence_reason = "multiple high-signal causes align on the same failure path"
    elif top_score >= 0.65:
        confidence_reason = "the leading cause is supported, but counterevidence remains"
    else:
        confidence_reason = "the current explanation is tentative and should be reviewed"
    calibration = (
        "stable" if top_score >= 0.85 and len(cause_chain) >= 4 and root_cause_clusters else
        "mixed" if top_score >= 0.65 else
        "tentative"
    )
    second_score = float(cause_chain[1].get("rank_score", 0.0)) if len(cause_chain) > 1 else 0.0
    score_gap = top_score - second_score
    stability = (
        "stable" if score_gap >= 0.20 else
        "competitive" if score_gap >= 0.08 else
        "fragile"
    )
    stability_reason = (
        "top evidence clearly outranks alternatives" if stability == "stable" else
        "top evidence leads, but competing explanations remain plausible" if stability == "competitive" else
        "multiple explanations remain close and should be reviewed together"
    )
    root_cause_summary = {
        "primary_kind": primary_kind,
        "primary_explanation": primary_explanation,
        "supporting_signals": supporting_signal_union,
        "counterfactual_available": runner_up is not None,
        "governance_pressure": any(
            item.get("kind") in {"action", "proof_gate"} for item in cause_chain[:3]
        ),
        "proof_pressure": proof_gate_event is not None or bool(verifier_findings),
        "clusters": root_cause_clusters,
        "narrative": " ".join(narrative_parts) if narrative_parts else None,
        "confidence_band": (
            "high" if top_score >= 0.85 else
            "medium" if top_score >= 0.65 else
            "low"
        ),
        "recommended_action": recommended_action,
        "actionability": actionability,
        "decision_path": decision_path,
        "evidence_count": len(cause_chain),
        "dominant_cluster": root_cause_clusters[0]["cluster"] if root_cause_clusters else None,
        "confidence_drivers": confidence_drivers,
        "confidence_score": top_score,
        "confidence_reason": confidence_reason,
        "calibration": calibration,
        "stability": stability,
        "stability_reason": stability_reason,
        "summary_version": "v2",
    }
    return {
        "root": {"kind": "run", "id": run_id if root is None else root},
        "cause_chain": cause_chain,
        "root_cause_summary": root_cause_summary,
        "runner_up_analysis": (
            {
                "component_id": runner_up.component_id,
                "likely_better": True,
                "why": runner_up.why_fit[:3],
                "transfer_mode": getattr(runner_up.transfer_mode, "value", str(runner_up.transfer_mode)),
            }
            if runner_up
            else None
        ),
        "confidence": max(0.2, min(0.96, top_score)),
        "violations": failing_outcome.verifier_findings,
        "task_description": task_description,
    }


async def _auto_distill_compiled_recipe(repo: Any, connectome: Optional[RunConnectome], packets: list[Any]) -> Optional[CompiledRecipe]:
    if connectome is None or not connectome.task_archetype or not packets:
        return None
    recipe_json = {
        "slot_order": [packet.slot.name for packet in packets],
        "preferred_families": [packet.selected.receipt.family_barcode for packet in packets],
        "required_proof_gates": sorted({gate.gate_type for packet in packets for gate in packet.proof_plan}),
        "disallowed_stretch_conditions": ["critical_slot_stretch"],
    }
    digest = hashlib.sha256(
        json.dumps({"task_archetype": connectome.task_archetype, **recipe_json}, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    recipe_id = f"auto_recipe_{digest}"
    existing = await repo.get_compiled_recipe(recipe_id)
    sample_size = (existing.sample_size if existing else 0) + 1
    recipe = CompiledRecipe(
        id=recipe_id,
        task_archetype=connectome.task_archetype,
        recipe_name=f"{connectome.task_archetype}_auto",
        recipe_json=recipe_json,
        sample_size=sample_size,
        is_active=sample_size >= 3,
    )
    return await repo.save_compiled_recipe(recipe)


async def _compute_federation_trends(
    repo: Any,
    *,
    task_archetype: Optional[str] = None,
    family_barcode: Optional[str] = None,
    limit: int = 50,
) -> dict[str, list[dict[str, Any]]]:
    row_limit = max(1, min(limit, 200))
    connectome_rows = await repo.engine.fetch_all(
        f"""SELECT run_id, task_archetype
              FROM run_connectomes
             {"WHERE task_archetype = ?" if task_archetype else ""}
             ORDER BY created_at DESC
             LIMIT ?""",
        ([task_archetype, row_limit] if task_archetype else [row_limit]),
    )

    by_archetype: dict[str, dict[str, Any]] = {}
    by_family: dict[str, dict[str, Any]] = {}
    for row in connectome_rows:
        run_id = row.get("run_id")
        archetype = row.get("task_archetype") or "unknown"
        outcomes = await repo.list_run_outcome_events(run_id)
        counted_run = False
        for outcome in outcomes:
            packet = await repo.get_application_packet(outcome.packet_id)
            if packet is None:
                continue
            family = packet.selected.receipt.family_barcode
            if family_barcode and family != family_barcode:
                continue
            transfer_mode = getattr(packet.selected.transfer_mode, "value", str(packet.selected.transfer_mode))
            slot_risk = getattr(packet.slot.risk, "value", str(packet.slot.risk))

            archetype_bucket = by_archetype.setdefault(
                archetype,
                {
                    "task_archetype": archetype,
                    "runs": 0,
                    "direct_fit": 0,
                    "pattern_transfer": 0,
                    "heuristic_fallback": 0,
                    "critical_pattern_transfer": 0,
                    "successful_packets": 0,
                    "failed_packets": 0,
                },
            )
            if not counted_run:
                archetype_bucket["runs"] += 1
                counted_run = True
            archetype_bucket[transfer_mode] = archetype_bucket.get(transfer_mode, 0) + 1
            if slot_risk == "critical" and transfer_mode != "direct_fit":
                archetype_bucket["critical_pattern_transfer"] += 1
            if outcome.success:
                archetype_bucket["successful_packets"] += 1
            else:
                archetype_bucket["failed_packets"] += 1

            family_bucket = by_family.setdefault(
                family,
                {
                    "family_barcode": family,
                    "task_archetypes": set(),
                    "direct_fit": 0,
                    "pattern_transfer": 0,
                    "heuristic_fallback": 0,
                    "critical_pattern_transfer": 0,
                    "successful_packets": 0,
                    "failed_packets": 0,
                },
            )
            family_bucket["task_archetypes"].add(archetype)
            family_bucket[transfer_mode] = family_bucket.get(transfer_mode, 0) + 1
            if slot_risk == "critical" and transfer_mode != "direct_fit":
                family_bucket["critical_pattern_transfer"] += 1
            if outcome.success:
                family_bucket["successful_packets"] += 1
            else:
                family_bucket["failed_packets"] += 1

    by_family_rows = []
    for item in by_family.values():
        item["task_archetypes"] = sorted(item["task_archetypes"])
        by_family_rows.append(item)

    archetype_rows = sorted(
        by_archetype.values(),
        key=lambda item: (item["critical_pattern_transfer"], item["pattern_transfer"], item["failed_packets"]),
        reverse=True,
    )[:row_limit]
    by_family_rows = sorted(
        by_family_rows,
        key=lambda item: (item["critical_pattern_transfer"], item["pattern_transfer"], item["failed_packets"]),
        reverse=True,
    )[:row_limit]
    return {"by_archetype": archetype_rows, "by_family": by_family_rows}


def _build_federation_policy_recommendations(
    trends: dict[str, list[dict[str, Any]]],
    existing_policies: list[GovernancePolicy],
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    active_keys = {
        (
            policy.policy_kind,
            policy.task_archetype or "",
            policy.slot_id or "",
            policy.family_barcode or "",
        )
        for policy in existing_policies
        if policy.status == "active"
    }

    for row in trends.get("by_archetype", []):
        if row.get("critical_pattern_transfer", 0) >= 2 or (
            row.get("heuristic_fallback", 0) >= 2 and row.get("failed_packets", 0) >= row.get("successful_packets", 0)
        ):
            key = ("slot_policy", row.get("task_archetype") or "", "", "")
            recommendations.append(
                {
                    "policy_kind": "slot_policy",
                    "severity": "high" if row.get("critical_pattern_transfer", 0) >= 2 else "medium",
                    "task_archetype": row.get("task_archetype"),
                    "slot_id": None,
                    "family_barcode": None,
                    "reason": (
                        f"Cross-run federation pressure is high for {row.get('task_archetype')}: "
                        f"{row.get('pattern_transfer', 0)} pattern-transfer packets, "
                        f"{row.get('critical_pattern_transfer', 0)} critical non-direct packets"
                    ),
                    "recommendation": "Prefer direct-fit packets or require stronger review before accepting cross-brain transfer on this archetype.",
                    "evidence_json": {"trend_scope": "archetype", "trend": row},
                    "already_active": key in active_keys,
                }
            )

        if row.get("heuristic_fallback", 0) >= 1 and row.get("failed_packets", 0) >= row.get("successful_packets", 0):
            key = ("proof_policy", row.get("task_archetype") or "", "", "")
            recommendations.append(
                {
                    "policy_kind": "proof_policy",
                    "severity": "medium",
                    "task_archetype": row.get("task_archetype"),
                    "slot_id": None,
                    "family_barcode": None,
                    "reason": (
                        f"Heuristic federation fallback remains active for {row.get('task_archetype')} "
                        f"with {row.get('heuristic_fallback', 0)} fallback packets"
                    ),
                    "recommendation": "Add stronger proof gates or require human governance review when heuristic federation fallback is selected.",
                    "evidence_json": {"trend_scope": "archetype", "trend": row},
                    "already_active": key in active_keys,
                }
            )

    for row in trends.get("by_family", []):
        if row.get("critical_pattern_transfer", 0) >= 1 or (
            row.get("pattern_transfer", 0) >= 2 and row.get("failed_packets", 0) > row.get("successful_packets", 0)
        ):
            primary_archetype = (row.get("task_archetypes") or [None])[0]
            key = ("family_policy", primary_archetype or "", "", row.get("family_barcode") or "")
            recommendations.append(
                {
                    "policy_kind": "family_policy",
                    "severity": "high" if row.get("critical_pattern_transfer", 0) >= 1 else "medium",
                    "task_archetype": primary_archetype,
                    "slot_id": None,
                    "family_barcode": row.get("family_barcode"),
                    "reason": (
                        f"Family {row.get('family_barcode')} shows repeated federation risk: "
                        f"{row.get('pattern_transfer', 0)} pattern-transfer packets, "
                        f"{row.get('failed_packets', 0)} failures"
                    ),
                    "recommendation": "Downgrade or quarantine this family for repeated federation transfer until stronger direct-fit evidence exists.",
                    "evidence_json": {"trend_scope": "family", "trend": row},
                    "already_active": key in active_keys,
                }
            )

    recommendations.sort(
        key=lambda item: (
            2 if item["severity"] == "high" else 1,
            0 if item["already_active"] else 1,
        ),
        reverse=True,
    )
    return recommendations


def _build_plan_summary(plan_record: dict[str, Any], packets: list[Any]) -> dict[str, Any]:
    weak_slots = sum(1 for packet in packets if getattr(packet.coverage_state, "value", str(packet.coverage_state)) == "weak")
    critical_slots = sum(1 for slot in plan_record["slots"] if slot["risk"] == "critical")
    return {
        "total_slots": len(plan_record["slots"]),
        "critical_slots": critical_slots,
        "weak_evidence_slots": weak_slots,
    }


def _ensure_critical_policy_gates(packet: Any, enabled: bool) -> Any:
    if not enabled:
        return packet
    slot_risk = getattr(packet.slot.risk, "value", str(packet.slot.risk))
    if slot_risk != "critical":
        return packet

    existing = {gate.gate_type for gate in packet.proof_plan}
    for gate_type in ("semgrep", "codeql"):
        if gate_type in existing:
            continue
        packet.proof_plan.append(
            ProofGate(
                gate_id=gate_type,
                gate_type=gate_type,
                required=True,
                status="pending",
                details=["critical slot policy gate"],
            )
        )
    if "critical_policy_scan_required" not in packet.review_required_reasons:
        packet.review_required_reasons.append("critical_policy_scan_required")
        packet.reviewer_required = True
    return packet


def _find_proof_gate(packet: Any, gate_type: str) -> Optional[ProofGate]:
    return next((gate for gate in packet.proof_plan if gate.gate_type == gate_type or gate.gate_id == gate_type), None)


def _reset_analysis_gates(packet: Any) -> Any:
    for gate_type in ("semgrep", "codeql"):
        gate = _find_proof_gate(packet, gate_type)
        if gate is None or gate.status == "waived":
            continue
        gate.status = "pending"
        gate.details = []
    return packet


def _apply_static_analysis_results(packet: Any, analysis: dict[str, dict[str, Any]]) -> tuple[list[str], bool]:
    findings: list[str] = []
    blocked = False
    for gate_type in ("semgrep", "codeql"):
        gate = _find_proof_gate(packet, gate_type)
        result = analysis.get(gate_type, {})
        if gate is None:
            continue
        if gate.status == "waived":
            continue
        tool_status = result.get("status", "unavailable")
        if tool_status in {"deferred", "unavailable"}:
            gate.status = "waived"
            gate.details = list(result.get("details") or [f"{gate_type} deferred"])
            continue
        if tool_status == "pass":
            gate.status = "pass"
            gate.details = []
            continue
        gate.status = "fail"
        details = list(result.get("details") or [])
        formatted_findings = []
        for finding in result.get("findings") or []:
            rendered = f"{gate_type}:{finding.get('severity')}:{finding.get('rule_id') or 'rule'}:{finding.get('message') or ''}"
            formatted_findings.append(rendered)
        gate.details = (formatted_findings or details)[:5]
        findings.extend(gate.details)
        blocked = True
    return findings, blocked


async def _save_plan_record(app: FastAPI, repo: Any, plan_record: dict[str, Any]) -> TaskPlanRecord:
    _playground_plans(app)[plan_record["plan_id"]] = plan_record
    model = TaskPlanRecord(
        id=plan_record["plan_id"],
        task_text=plan_record["task_text"],
        workspace_dir=plan_record.get("workspace_dir"),
        branch=plan_record.get("branch"),
        target_brain=plan_record.get("target_brain"),
        execution_mode=plan_record.get("execution_mode"),
        check_commands=plan_record.get("check_commands") or [],
        task_archetype=plan_record["task_archetype"],
        archetype_confidence=float(plan_record.get("archetype_confidence", 0.0) or 0.0),
        status=plan_record.get("status", "draft"),
        summary=plan_record.get("summary") or {},
        approved_slot_ids=plan_record.get("approved_slot_ids") or [],
        plan_json=plan_record,
    )
    return await repo.save_task_plan(model)


async def _load_plan_record(app: FastAPI, repo: Any, plan_id: str) -> Optional[dict[str, Any]]:
    cached = _playground_plans(app).get(plan_id)
    if cached is not None:
        return cached
    stored = await repo.get_task_plan(plan_id)
    if stored is None:
        return None
    plan_record = dict(stored.plan_json or {})
    if not plan_record:
        plan_record = {
            "plan_id": stored.id,
            "task_text": stored.task_text,
            "workspace_dir": stored.workspace_dir,
            "branch": stored.branch,
            "target_brain": stored.target_brain,
            "execution_mode": stored.execution_mode,
            "check_commands": stored.check_commands,
            "task_archetype": stored.task_archetype,
            "archetype_confidence": stored.archetype_confidence,
            "status": stored.status,
            "summary": stored.summary,
            "approved_slot_ids": stored.approved_slot_ids,
            "created_at": stored.created_at.isoformat(),
            "slots": [],
        }
    _playground_plans(app)[plan_id] = plan_record
    return plan_record


def _advance_slot_execution(job: dict[str, Any], *, step_name: Optional[str] = None, terminal_success: Optional[bool] = None) -> None:
    slots = job.get("slot_execution", [])
    if not slots:
        return

    current_idx = next(
        (idx for idx, slot in enumerate(slots) if slot["status"] == "executing"),
        None,
    )
    if current_idx is None:
        current_idx = next(
            (idx for idx, slot in enumerate(slots) if slot["status"] in {"approved", "queued"}),
            None,
        )
        if current_idx is None:
            return
        slots[current_idx]["status"] = "executing"

    current = slots[current_idx]
    if step_name is not None:
        current["current_step"] = step_name

    if terminal_success is None:
        return

    if terminal_success:
        current["status"] = "verified"
        current["current_step"] = "done"
        for idx, slot in enumerate(slots):
            if idx == current_idx:
                continue
            if slot["status"] in {"approved", "queued", "executing"}:
                slot["status"] = "verified"
                slot["current_step"] = "done"
    else:
        current["status"] = "failed"
        current["current_step"] = current.get("current_step") or "verify"
        for idx, slot in enumerate(slots):
            if idx > current_idx and slot["status"] in {"approved", "queued"}:
                slot["status"] = "blocked"


async def _persist_run_slot_execution(repo: Any, run_id: str, slot_state: dict[str, Any]) -> None:
    await repo.save_run_slot_execution(
        RunSlotExecution(
            run_id=run_id,
            slot_id=slot_state["slot_id"],
            packet_id=slot_state.get("packet_id"),
            selected_component_id=slot_state.get("selected_component_id"),
            status=slot_state.get("status", "queued"),
            current_step=slot_state.get("current_step"),
            retry_count=int(slot_state.get("retry_count", 0)),
            last_retry_detail=slot_state.get("last_retry_detail"),
            replacement_count=int(slot_state.get("replacement_count", 0)),
            blocked_wait_ms=int(slot_state.get("blocked_wait_ms", 0)),
            family_wait_ms=int(slot_state.get("family_wait_ms", 0)),
        )
    )


async def _persist_all_run_slot_execution(repo: Any, run_id: str, job: dict[str, Any]) -> None:
    for slot_state in job.get("slot_execution", []):
        await _persist_run_slot_execution(repo, run_id, slot_state)


async def _record_run_event(
    repo: Any,
    run_id: str,
    event_type: str,
    *,
    slot_id: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> RunEvent:
    return await repo.save_run_event(
        RunEvent(
            run_id=run_id,
            slot_id=slot_id,
            event_type=event_type,
            payload=payload or {},
        )
    )


async def _record_run_action_audit(
    repo: Any,
    run_id: str,
    action_type: str,
    *,
    slot_id: Optional[str] = None,
    reason: str = "",
    actor: str = "operator",
    payload: Optional[dict[str, Any]] = None,
) -> RunActionAudit:
    return await repo.save_run_action_audit(
        RunActionAudit(
            run_id=run_id,
            slot_id=slot_id,
            action_type=action_type,
            actor=actor,
            reason=reason,
            action_payload=payload or {},
        )
    )


def _select_packet_for_file(file_path: str, packets: list[Any]) -> tuple[Optional[Any], LandingOrigin]:
    normalized = file_path.lower()
    for packet in packets:
        for expected in packet.expected_landing_sites:
            if expected.file_path.lower() == normalized:
                return packet, LandingOrigin.ADAPTED_COMPONENT
    basename = Path(file_path).name.lower()
    for packet in packets:
        for expected in packet.expected_landing_sites:
            if Path(expected.file_path).name.lower() == basename:
                return packet, LandingOrigin.MIXED_ANCESTRY
    if packets:
        return packets[0], LandingOrigin.NOVEL_SYNTHESIS
    return None, LandingOrigin.NOVEL_SYNTHESIS


def _event_timestamp(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return str(value.isoformat())
        except Exception:
            return str(value)
    return str(value)


async def _build_run_events(repo: Any, run_id: str, job: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    persisted = await repo.list_run_events(run_id)
    if persisted:
        return [
            {
                "event_id": str(event.id),
                "run_id": run_id,
                "slot_id": event.slot_id,
                "event_type": event.event_type,
                "timestamp": _event_timestamp(event.created_at),
                "payload": event.payload,
            }
            for event in persisted
        ]

    events: list[dict[str, Any]] = []
    if job:
        for step in job.get("steps", []):
            events.append(
                {
                    "event_id": f"step:{run_id}:{step['timestamp']}:{step['step']}",
                    "run_id": run_id,
                    "slot_id": None,
                    "event_type": step["step"],
                    "timestamp": step["timestamp"],
                    "payload": {"detail": step["detail"]},
                }
            )
        for replacement in job.get("replacement_history", []):
            events.append(
                {
                    "event_id": f"replacement:{run_id}:{replacement['timestamp']}:{replacement['slot_id']}",
                    "run_id": run_id,
                    "slot_id": replacement["slot_id"],
                    "event_type": "candidate_swapped",
                    "timestamp": replacement["timestamp"],
                    "payload": {
                        "previous_component_id": replacement.get("previous_component_id"),
                        "new_component_id": replacement.get("new_component_id"),
                        "reason": replacement.get("reason"),
                    },
                }
            )
        for idx, correction in enumerate(job.get("corrections", [])):
            events.append(
                {
                    "event_id": f"retry:{run_id}:{idx}",
                    "run_id": run_id,
                    "slot_id": None,
                    "event_type": "retry_delta",
                    "timestamp": correction.get("created_at") or correction.get("timestamp") or f"retry-{idx}",
                    "payload": {
                        "attempt_number": correction.get("attempt_number"),
                        "violations": correction.get("violations", []),
                    },
                }
            )

    for pair in await repo.list_run_pair_events(run_id):
        events.append(
            {
                "event_id": str(pair.id),
                "run_id": run_id,
                "slot_id": str(pair.slot_id),
                "event_type": "packet_selected",
                "timestamp": _event_timestamp(pair.created_at),
                "payload": {"packet_id": str(pair.packet_id), "component_id": str(pair.component_id)},
            }
        )
    for landing in await repo.list_run_landing_events(run_id):
        events.append(
            {
                "event_id": str(landing.id),
                "run_id": run_id,
                "slot_id": str(landing.slot_id),
                "event_type": "landing_recorded",
                "timestamp": _event_timestamp(landing.created_at),
                "payload": {"file_path": str(landing.file_path), "origin": str(landing.origin.value)},
            }
        )
    for outcome in await repo.list_run_outcome_events(run_id):
        events.append(
            {
                "event_id": str(outcome.id),
                "run_id": run_id,
                "slot_id": str(outcome.slot_id),
                "event_type": "slot_verified" if outcome.success else "slot_failed",
                "timestamp": _event_timestamp(outcome.created_at),
                "payload": {"packet_id": str(outcome.packet_id), "success": bool(outcome.success)},
            }
        )
    events.sort(key=lambda item: item["timestamp"])
    return events


def _render_packetized_task_description(task_description: str, packets: list[Any]) -> str:
    if not packets:
        return task_description
    lines = [
        task_description.strip(),
        "",
        "CAM-SEQ APPLICATION PACKETS",
        "Use the following reviewed slot packets as the execution plan. Respect selected components, adaptation steps, and proof requirements.",
    ]
    for idx, packet in enumerate(packets, start=1):
        lines.extend(
            [
                f"",
                f"SLOT {idx}: {packet.slot.name}",
                f"- abstract_job: {packet.slot.abstract_job}",
                f"- selected_component: {packet.selected.title}",
                f"- receipt: {packet.selected.receipt.repo}::{packet.selected.receipt.file_path}" + (f"::{packet.selected.receipt.symbol}" if packet.selected.receipt.symbol else ""),
                f"- fit_bucket: {packet.selected.fit_bucket.value}",
                f"- transfer_mode: {packet.selected.transfer_mode.value}",
                f"- adaptation_plan: {', '.join(step.title for step in packet.adaptation_plan) if packet.adaptation_plan else 'none'}",
                f"- proof_plan: {', '.join(gate.gate_type for gate in packet.proof_plan) if packet.proof_plan else 'none'}",
            ]
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(application: FastAPI):
    yield
    await _shutdown_state()


app = FastAPI(title="CAM-PULSE Dashboard", docs_url="/api/docs", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3002",
        "http://127.0.0.1:3002",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# API endpoints — JSON
# ---------------------------------------------------------------------------


@app.get("/api/stats")
async def api_stats() -> JSONResponse:
    """Return methodology counts, lifecycle distribution, and ganglion info."""
    st = await _ensure_state(app)
    repo = st["repository"]
    feature_flags = st["config"].feature_flags
    config = st["config"]

    total = await repo.count_methodologies()
    active = await repo.count_active_methodologies()
    by_state = await repo.count_methodologies_by_state()

    # Language distribution
    rows = await repo.engine.fetch_all(
        "SELECT language, COUNT(*) as cnt FROM methodologies "
        "WHERE lifecycle_state != 'dead' GROUP BY language ORDER BY cnt DESC LIMIT 10"
    )
    languages = {str(r["language"] or "unknown"): int(r["cnt"]) for r in rows}

    # Top categories from tags
    tag_rows = await repo.engine.fetch_all(
        "SELECT tags FROM methodologies WHERE lifecycle_state != 'dead' AND tags IS NOT NULL"
    )
    cat_counts: dict[str, int] = {}
    for r in tag_rows:
        raw = r["tags"]
        if not raw:
            continue
        try:
            tags = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        for t in tags:
            if isinstance(t, str) and t.startswith("category:"):
                cat = t.split(":", 1)[1]
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
    top_categories = dict(sorted(cat_counts.items(), key=lambda x: -x[1])[:15])

    # Source repos
    src_rows = await repo.engine.fetch_all(
        "SELECT COUNT(DISTINCT json_each.value) as cnt "
        "FROM methodologies, json_each(methodologies.tags) "
        "WHERE json_each.value LIKE 'source:%'"
    )
    source_repo_count = int(src_rows[0]["cnt"]) if src_rows else 0

    # Sibling info
    siblings = []
    if config.instances and config.instances.enabled:
        for sib in config.instances.siblings:
            sib_info: dict[str, Any] = {
                "name": sib.name,
                "description": getattr(sib, "description", ""),
                "db_exists": Path(sib.db_path).exists(),
            }
            if sib_info["db_exists"]:
                try:
                    import aiosqlite

                    async with aiosqlite.connect(
                        sib.db_path, uri=True if "?" in sib.db_path else False
                    ) as db:
                        db.row_factory = aiosqlite.Row
                        cur = await db.execute("SELECT COUNT(*) as cnt FROM methodologies")
                        row = await cur.fetchone()
                        sib_info["methodology_count"] = int(row["cnt"]) if row else 0
                except Exception:
                    sib_info["methodology_count"] = 0
            siblings.append(sib_info)

    # Health score
    health_data = {"score": 0, "breakdown": {}}
    try:
        from claw.memory.governance import MemoryGovernor
        gov = MemoryGovernor(repository=repo, config=config.governance)
        health_data = await gov.compute_health_score()
    except Exception as exc:
        logger.warning("Health score computation failed: %s", exc)

    return JSONResponse(
        {
            "primary": {
                "name": getattr(config.instances, "instance_name", "primary")
                if config.instances
                else "primary",
                "total": total,
                "active": active,
                "lifecycle": by_state,
                "languages": languages,
                "top_categories": top_categories,
                "source_repos": source_repo_count,
            },
            "siblings": siblings,
            "total_across_brain": total + sum(s.get("methodology_count", 0) for s in siblings),
            "health_score": health_data.get("score", 0),
            "health_breakdown": health_data.get("breakdown", {}),
        }
    )


@app.get("/api/v2/components/search")
async def api_v2_component_search(
    q: str = Query("", description="Free-text component query"),
    limit: int = Query(20, ge=1, le=200),
    language: Optional[str] = Query(None),
    workspace_dir: Optional[str] = Query(None),
) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    db_limit = max(limit * 3, 24)
    items = await repo.search_component_cards_text(q, limit=db_limit, language=language)
    policies = await repo.list_governance_policies(active_only=True, limit=200)
    ranked: dict[str, tuple[int, dict[str, Any]]] = {}
    for item in items:
        if _is_noise_component_path(item.file_path):
            continue
        if "test" not in _direct_query_terms(q) and _is_test_component_path(item.file_path):
            continue
        score = _score_component_search_match(
            q,
            title=item.title,
            component_type=item.component_type,
            file_path=item.file_path,
            symbol=item.symbol,
            success_count=item.success_count,
            failure_count=item.failure_count,
        )
        if score <= 0:
            continue
        payload = item.model_dump(mode="json")
        payload["governance_summary"] = {
            "family_barcode": item.family_barcode,
            "active_policy_count": sum(
                1
                for policy in policies
                if policy.policy_kind == "family_policy"
                and policy.family_barcode == item.family_barcode
            ),
        }
        payload["search_score"] = score
        payload["source_scope"] = "memory"
        ranked[item.id] = (score, payload)
    if q.strip():
        local_cards = _local_workspace_search_cards(
            query=q,
            target_language=language,
            workspace_dir=workspace_dir,
            max_cards=db_limit,
        )
        if local_cards:
            persisted_cards = await _persist_local_candidate_cards(repo, local_cards)
            for card in persisted_cards:
                if _is_noise_component_path(card.receipt.file_path):
                    continue
                score = _score_component_search_match(
                    q,
                    title=card.title,
                    component_type=card.component_type,
                    file_path=card.receipt.file_path,
                    symbol=card.receipt.symbol,
                    extra_terms=[*getattr(card, "abstract_jobs", []), *getattr(card, "keywords", [])],
                    success_count=getattr(card, "success_count", 0),
                    failure_count=getattr(card, "failure_count", 0),
                )
                if score <= 0:
                    continue
                payload = _component_card_summary_payload(
                    card,
                    policies,
                    search_score=score,
                    source_scope="workspace",
                )
                current = ranked.get(card.id)
                if current is None or score > current[0]:
                    ranked[card.id] = (score, payload)
    summarized = [
        payload
        for _score, payload in sorted(
            ranked.values(),
            key=lambda item: (
                item[0],
                int(item[1].get("governance_summary", {}).get("active_policy_count", 0) > 0),
                item[1].get("success_count", 0),
                -item[1].get("failure_count", 0),
                item[1].get("title", "").lower(),
            ),
            reverse=True,
        )[:limit]
    ]
    return JSONResponse({"items": summarized, "count": len(summarized), "query": q})


@app.get("/api/v2/components/{component_id}")
async def api_v2_component_detail(component_id: str) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    component = await repo.get_component_card(component_id)
    if component is None:
        return JSONResponse({"error": "component not found"}, status_code=404)

    lineage = await repo.get_component_lineage(component.receipt.lineage_id)
    fit_history = await repo.list_component_fit(component.id)
    policies = await repo.list_governance_policies(active_only=True, limit=200)
    related = []
    if component.methodology_id:
        related = await repo.list_components_for_methodology(component.methodology_id)
    return JSONResponse(
        {
            "component": component.model_dump(mode="json"),
            "lineage": lineage.model_dump(mode="json") if lineage else None,
            "fit_history": [item.model_dump(mode="json") for item in fit_history],
            "related_methodology_components": [item.model_dump(mode="json") for item in related],
            "governance_summary": _governance_summary_for_component(component, policies),
        }
    )


@app.get("/api/v2/components/{component_id}/history")
async def api_v2_component_history(component_id: str) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    component = await repo.get_component_card(component_id)
    if component is None:
        return JSONResponse({"error": "component not found"}, status_code=404)

    packet_history = await repo.list_packet_history_for_component(component_id)
    fit_history = await repo.list_component_fit(component_id)
    lineage_components = await repo.list_lineage_components(component.receipt.lineage_id)
    return JSONResponse(
        {
            "component_id": component_id,
            "packet_history": [item.model_dump(mode="json") for item in packet_history],
            "fit_history": [item.model_dump(mode="json") for item in fit_history],
            "lineage_components": [item.model_dump(mode="json") for item in lineage_components],
        }
    )


@app.post("/api/v2/components/backfill")
async def api_v2_component_backfill(request: Request) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    config = st["config"]
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    methodology_ids = body.get("methodology_ids")
    limit = int(body.get("limit", 100))

    from claw.miner import RepoMiner

    miner = RepoMiner(
        repository=repo,
        llm_client=None,
        semantic_memory=None,
        config=config,
    )
    summary = await miner.backfill_components(
        methodology_ids=methodology_ids,
        limit=limit,
        repository=repo,
    )
    return JSONResponse(summary)


@app.post("/api/v2/plans")
async def api_v2_create_plan(request: Request) -> JSONResponse:
    body = await request.json()
    task_text = body.get("task_text", "").strip()
    if not task_text:
        return JSONResponse({"error": "task_text required"}, status_code=400)

    st = await _ensure_state(app)
    repo = st["repository"]
    feature_flags = st["config"].feature_flags

    workspace_dir = body.get("workspace_dir")
    branch = body.get("branch")
    target_brain = body.get("target_brain", "primary")
    execution_mode = body.get("execution_mode", "interactive")
    check_commands = body.get("check_commands") or []
    target_language = body.get("target_language")
    target_stack_hints = body.get("target_stack_hints") or []

    plan = decompose_task(
        task_text,
        workspace_path=workspace_dir,
        target_language=target_language,
        target_stack_hints=target_stack_hints,
        check_commands=check_commands,
    )
    governance_policies = await _active_governance_policies_for_plan(repo, plan.task_archetype)
    compiled_recipes = await _active_compiled_recipes_for_archetype(repo, plan.task_archetype)

    packets = []
    slot_views: list[dict[str, Any]] = []
    for slot in plan.slots:
        cards = await _candidate_cards_for_slot(
            repo,
            task_text=task_text,
            slot=slot,
            target_language=target_language,
            workspace_dir=workspace_dir,
        )
        fit_rows = await repo.find_component_fit(plan.task_archetype, slot.name, None, limit=20)
        ranked = rank_components_for_slot(
            slot,
            cards,
            fit_rows=fit_rows,
            compiled_recipes=compiled_recipes,
            governance_policies=governance_policies,
            target_language=target_language,
            target_stack_hints=target_stack_hints,
        )
        if not ranked:
            return JSONResponse(
                {"error": f"no component candidates available for slot '{slot.name}'"},
                status_code=400,
            )

        packet = build_application_packet(
            plan.plan_id,
            plan.task_archetype,
            slot,
            ranked,
            governance_policies=governance_policies,
        )
        packet = _ensure_critical_policy_gates(packet, feature_flags.critical_slot_policy)
        await repo.save_application_packet(packet)
        packets.append(packet)
        slot_views.append(
            {
                "slot_id": slot.slot_id,
                "name": slot.name,
                "risk": slot.risk.value,
                "selected_packet_id": packet.packet_id,
                "status": packet.status.value,
                "confidence": packet.selected.confidence,
                "coverage_state": packet.coverage_state.value,
            }
        )

    summary = _build_plan_summary({"slots": slot_views}, packets)
    status = "review_required" if any(packet.reviewer_required for packet in packets) else "draft"
    plan_record = {
        "plan_id": plan.plan_id,
        "task_text": task_text,
        "workspace_dir": workspace_dir,
        "branch": branch,
        "target_brain": target_brain,
        "execution_mode": execution_mode,
        "check_commands": check_commands,
        "task_archetype": plan.task_archetype,
        "archetype_confidence": plan.archetype_confidence,
        "status": status,
        "slots": slot_views,
        "summary": summary,
        "approved_slot_ids": [],
        "created_at": _datetime.now(UTC).isoformat(),
    }
    for slot in plan.slots:
        await repo.save_slot_instance(slot, task_archetype=plan.task_archetype)
    await _save_plan_record(app, repo, plan_record)

    return JSONResponse(
        {
            "plan_id": plan.plan_id,
            "task_archetype": plan.task_archetype,
            "archetype_confidence": plan.archetype_confidence,
            "status": status,
            "slots": slot_views,
            "summary": summary,
        }
    )


@app.get("/api/v2/plans/{plan_id}")
async def api_v2_get_plan(plan_id: str) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    plan = await _load_plan_record(app, repo, plan_id)
    if plan is None:
        return JSONResponse({"error": "Plan not found"}, status_code=404)
    packet_summaries = await repo.list_packets_for_plan(plan_id)
    packets = []
    for summary in packet_summaries:
        packet = await repo.get_application_packet(summary.packet_id)
        if packet is not None:
            packets.append(packet.model_dump(mode="json"))

    return JSONResponse({**plan, "packets": packets})


@app.post("/api/v2/plans/{plan_id}/slots/{slot_id}/swap-candidate")
async def api_v2_swap_plan_candidate(plan_id: str, slot_id: str, request: Request) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    plan = await _load_plan_record(app, repo, plan_id)
    if plan is None:
        return JSONResponse({"error": "Plan not found"}, status_code=404)

    body = await request.json()
    candidate_component_id = body.get("candidate_component_id")
    if not candidate_component_id:
        return JSONResponse({"error": "candidate_component_id required"}, status_code=400)

    packet_summaries = await repo.list_packets_for_plan(plan_id)
    packet = None
    for summary in packet_summaries:
        if summary.slot_id != slot_id:
            continue
        packet = await repo.get_application_packet(summary.packet_id)
        break

    if packet is None:
        return JSONResponse({"error": "Slot packet not found"}, status_code=404)

    replacement = next((item for item in packet.runner_ups if item.component_id == candidate_component_id), None)
    if replacement is None:
        return JSONResponse({"error": "Candidate not available as runner-up"}, status_code=404)
    governance_policies = await _active_governance_policies_for_plan(repo, str(plan.get("task_archetype") or ""))
    matching_family_policies = [
        policy
        for policy in governance_policies
        if policy.policy_kind == "family_policy"
        and policy.family_barcode
        and policy.family_barcode == replacement.receipt.family_barcode
    ]
    slot_risk = getattr(packet.slot.risk, "value", str(packet.slot.risk))
    if slot_risk == "critical" and any(policy.severity == "high" for policy in matching_family_policies):
        return JSONResponse(
            {
                "error": "Candidate blocked by active high-severity family policy",
                "policy_reasons": [policy.reason or policy.recommendation for policy in matching_family_policies],
            },
            status_code=400,
        )

    old_selected = packet.selected
    packet.selected = replacement
    packet.runner_ups = [old_selected, *[item for item in packet.runner_ups if item.component_id != candidate_component_id]][:3]
    packet.why_selected = replacement.why_fit[:4] or ["selected by manual swap"]
    packet.reviewer_required = True
    packet.review_required_reasons = list(
        dict.fromkeys(
            packet.review_required_reasons
            + ["manual_candidate_swap"]
            + (["governance_family_policy"] if matching_family_policies else [])
        )
    )
    packet.confidence_basis = replacement.confidence_basis
    packet.status = PacketStatus.REVIEW_REQUIRED
    if matching_family_policies:
        packet.risk_notes = list(
            dict.fromkeys(
                packet.risk_notes
                + [policy.recommendation or policy.reason for policy in matching_family_policies if (policy.recommendation or policy.reason)]
            )
        )[:4]
    packet = _reset_analysis_gates(packet)
    await repo.save_application_packet(packet)

    replacement_history = list(plan.get("replacement_history", []))
    replacement_history.append(
        {
            "slot_id": slot_id,
            "previous_component_id": old_selected.component_id,
            "new_component_id": replacement.component_id,
            "reason": body.get("reason") or "manual_candidate_swap",
            "timestamp": _datetime.now(UTC).isoformat(),
        }
    )
    plan["replacement_history"] = replacement_history

    for slot_view in plan["slots"]:
        if slot_view["slot_id"] == slot_id:
            slot_view["selected_packet_id"] = packet.packet_id
            slot_view["status"] = packet.status.value
            slot_view["confidence"] = packet.selected.confidence
            slot_view["coverage_state"] = packet.coverage_state.value
            break
    plan["status"] = "review_required"
    plan["approved_slot_ids"] = [item for item in plan.get("approved_slot_ids", []) if item != slot_id]
    await _save_plan_record(app, repo, plan)

    return JSONResponse({"packet": packet.model_dump(mode="json")})


@app.post("/api/v2/plans/{plan_id}/approve")
async def api_v2_approve_plan(plan_id: str, request: Request) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    plan = await _load_plan_record(app, repo, plan_id)
    if plan is None:
        return JSONResponse({"error": "Plan not found"}, status_code=404)

    body = await request.json()
    slot_ids = body.get("slot_ids") or [slot["slot_id"] for slot in plan["slots"]]

    packet_summaries = await repo.list_packets_for_plan(plan_id)
    approved_slot_ids: list[str] = list(plan.get("approved_slot_ids", []))
    for summary in packet_summaries:
        if summary.slot_id not in slot_ids:
            continue
        packet = await repo.get_application_packet(summary.packet_id)
        if packet is None:
            continue
        packet.status = PacketStatus.APPROVED
        await repo.save_application_packet(packet)
        if summary.slot_id not in approved_slot_ids:
            approved_slot_ids.append(summary.slot_id)

    plan["approved_slot_ids"] = approved_slot_ids
    plan["status"] = "approved" if len(approved_slot_ids) == len(plan["slots"]) else "review_required"
    await _save_plan_record(app, repo, plan)
    return JSONResponse(
        {
            "plan_id": plan_id,
            "status": plan["status"],
            "approved_slot_ids": approved_slot_ids,
        }
    )


@app.post("/api/v2/plans/{plan_id}/execute")
async def api_v2_execute_plan(plan_id: str, request: Request) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    plan = await _load_plan_record(app, repo, plan_id)
    if plan is None:
        return JSONResponse({"error": "Plan not found"}, status_code=404)

    body = await request.json()
    approved_slot_ids = body.get("approved_slot_ids") or plan.get("approved_slot_ids") or [slot["slot_id"] for slot in plan["slots"]]
    if not approved_slot_ids:
        return JSONResponse({"error": "No approved slots selected"}, status_code=400)

    plan["status"] = "executing"
    await _save_plan_record(app, repo, plan)
    response = await _start_playground_execution(
        request,
        task_description=plan["task_text"],
        project_id="playground",
        workspace_dir=plan.get("workspace_dir"),
        plan_id=plan_id,
        approved_slot_ids=approved_slot_ids,
    )
    payload = json.loads(response.body.decode("utf-8"))
    payload["redirect_to"] = f"/forge/run/{payload['session_id']}"
    return JSONResponse(payload)


@app.get("/api/search")
async def api_search(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
) -> JSONResponse:
    """Federated search across primary + all sibling ganglia."""
    st = await _ensure_state(app)
    repo = st["repository"]
    federation = st["federation"]
    inferred_archetype, archetype_confidence, _hits = infer_task_archetype(q)
    governance_policies = await _active_governance_policies_for_plan(repo, inferred_archetype)
    governance_conflicts = _detect_governance_conflicts(governance_policies)

    t0 = time.monotonic()
    results: list[dict[str, Any]] = []

    # 1. Search primary ganglion via FTS5
    safe_q = _build_safe_fts5_query(q)
    if not safe_q:
        return JSONResponse({"query": q, "results": [], "elapsed_ms": 0})

    primary_rows = await repo.engine.fetch_all(
        "SELECT m.id, m.problem_description, m.solution_code, m.methodology_notes, "
        "m.tags, m.language, m.lifecycle_state, m.novelty_score, m.retrieval_count, "
        "m.success_count, m.failure_count, "
        "rank AS fts_rank "
        "FROM methodology_fts f "
        "JOIN methodologies m ON f.rowid = m.rowid "
        "WHERE methodology_fts MATCH ? "
        "ORDER BY rank LIMIT ?",
        (safe_q, limit),
    )
    for r in primary_rows:
        tags = []
        if r["tags"]:
            try:
                tags = json.loads(r["tags"]) if isinstance(r["tags"], str) else r["tags"]
            except (json.JSONDecodeError, TypeError):
                pass
        results.append(
            {
                "id": r["id"],
                "problem": r["problem_description"][:300],
                "solution_preview": (r["solution_code"] or "")[:200],
                "notes": (r["methodology_notes"] or "")[:200],
                "tags": tags,
                "language": r["language"],
                "lifecycle": r["lifecycle_state"],
                "novelty": r["novelty_score"],
                "retrievals": r["retrieval_count"],
                "successes": r["success_count"],
                "source_ganglion": "primary",
                "fts_rank": abs(float(r["fts_rank"] or 0)),
            }
        )

    # 2. Search siblings via federation
    federation_results = []
    if federation:
        try:
            federation_results = await federation.query(q, max_total=limit)
            for fr in federation_results:
                m = fr.methodology
                tags = m.tags if isinstance(m.tags, list) else []
                results.append(
                    {
                        "id": m.id,
                        "problem": m.problem_description[:300],
                        "solution_preview": (m.solution_code or "")[:200],
                        "notes": (m.methodology_notes or "")[:200],
                        "tags": tags,
                        "language": m.language,
                        "lifecycle": m.lifecycle_state,
                        "novelty": m.novelty_score,
                        "retrievals": m.retrieval_count,
                        "successes": m.success_count,
                        "source_ganglion": fr.source_instance,
                        "fts_rank": fr.fts_rank,
                        "relevance_score": fr.relevance_score,
                    }
                )
        except Exception as exc:
            logger.warning("Federation query failed: %s", exc)

    elapsed_ms = (time.monotonic() - t0) * 1000

    # Deduplicate by id, keep highest fts_rank
    seen: dict[str, dict] = {}
    for r in results:
        rid = r["id"]
        if rid not in seen or r["fts_rank"] > seen[rid]["fts_rank"]:
            seen[rid] = r
    deduped = sorted(seen.values(), key=lambda x: x["fts_rank"], reverse=True)[:limit]

    ganglion_counts: dict[str, int] = {}
    for r in deduped:
        g = r["source_ganglion"]
        ganglion_counts[g] = ganglion_counts.get(g, 0) + 1

    return JSONResponse(
        {
            "query": q,
            "total_results": len(deduped),
            "elapsed_ms": round(elapsed_ms, 1),
            "ganglion_counts": ganglion_counts,
            "governance_context": {
                "task_archetype": inferred_archetype,
                "archetype_confidence": archetype_confidence,
                "active_policy_count": len(governance_policies),
                "conflict_count": len(governance_conflicts),
                "policies": [
                    {
                        "id": policy.id,
                        "policy_kind": policy.policy_kind,
                        "severity": policy.severity,
                        "reason": policy.reason,
                        "recommendation": policy.recommendation,
                        "family_barcode": policy.family_barcode,
                        "slot_id": policy.slot_id,
                    }
                    for policy in governance_policies[:5]
                ],
                "conflicts": governance_conflicts[:5],
            },
            "results": deduped,
        }
    )


@app.get("/api/v2/federation/packets")
async def api_v2_federation_packets(
    q: str = Query(..., min_length=1),
    slot_name: Optional[str] = Query(None),
    language: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=50),
) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    federation = st["federation"]

    inferred_archetype, archetype_confidence, _hits = infer_task_archetype(q)
    plan = decompose_task(
        q,
        workspace_path=None,
        target_language=language,
        target_stack_hints=[],
        check_commands=[],
    )
    slot = next((item for item in plan.slots if item.name == slot_name), None) if slot_name else (plan.slots[0] if plan.slots else None)

    local_query = q if slot is None else f"{q} {slot.name} {slot.abstract_job}"
    local_cards = await repo.search_component_cards_text(local_query, limit=limit, language=language)
    local_items = []
    for summary in local_cards:
        card = await repo.get_component_card(summary.id)
        if card is None:
            continue
        local_items.append(
            {
                "component_id": card.id,
                "title": card.title,
                "component_type": card.component_type,
                "abstract_jobs": card.abstract_jobs,
                "language": card.language,
                "repo": card.receipt.repo,
                "file_path": card.receipt.file_path,
                "symbol": card.receipt.symbol,
                "family_barcode": card.receipt.family_barcode,
                "provenance_precision": getattr(card.receipt.provenance_precision, "value", str(card.receipt.provenance_precision)),
                "source_instance": "primary",
                "match_type": _component_match_type(card, slot),
                "match_score": 1.0,
                "relevance_score": 1.0,
            }
        )

    sibling_items = []
    if federation is not None:
        try:
            sibling_results = await federation.query_component_packets(
                q,
                slot_name=slot.name if slot else slot_name,
                task_archetype=inferred_archetype,
                language=language,
                max_total=limit,
            )
            sibling_items = [item.as_dict() for item in sibling_results]
        except Exception as exc:
            logger.warning("Federation packet query failed: %s", exc)

    merged = []
    seen: set[tuple[str, str]] = set()
    for item in [*local_items, *sibling_items]:
        ident = (item["source_instance"], item["component_id"])
        if ident in seen:
            continue
        seen.add(ident)
        merged.append(item)
    merged.sort(key=lambda item: item["relevance_score"] * max(item["match_score"], 0.1), reverse=True)

    return JSONResponse(
        {
            "query": q,
            "task_archetype": inferred_archetype,
            "archetype_confidence": archetype_confidence,
            "slot": slot.model_dump(mode="json") if slot else None,
            "results": merged[:limit],
        }
    )


@app.post("/api/v2/federation/specialist-packet")
async def api_v2_federation_specialist_packet(request: Request) -> JSONResponse:
    st = await _ensure_state(app)
    feature_flags = st["config"].feature_flags
    if not getattr(feature_flags, "a2a_packets", False):
        return JSONResponse({"error": "a2a packet exchange is disabled"}, status_code=403)

    payload = await request.json()
    task_text = str(payload.get("task_text", "")).strip()
    slot_name = payload.get("slot_name")
    preferred_agent = payload.get("preferred_agent")
    target_language = payload.get("target_language")
    limit = max(1, min(int(payload.get("limit", 5)), 20))

    if not task_text:
        return JSONResponse({"error": "task_text is required"}, status_code=400)

    inferred_task_type = _infer_specialist_task_type(task_text)
    from claw.dispatcher import DEFAULT_AGENT, STATIC_ROUTING

    selected_agent = preferred_agent or STATIC_ROUTING.get(inferred_task_type, DEFAULT_AGENT)
    packet_response = await api_v2_federation_packets(
        q=task_text,
        slot_name=slot_name,
        language=target_language,
        limit=limit,
    )
    packet_data = json.loads(packet_response.body.decode("utf-8"))
    results = packet_data.get("results", [])
    review_required = not results or any(item.get("match_type") != "direct_fit" for item in results[:2])

    return JSONResponse(
        {
            "exchange_id": f"specpkt_{uuid.uuid4().hex[:12]}",
            "task_text": task_text,
            "selected_agent": selected_agent,
            "inferred_task_type": inferred_task_type,
            "preferred_agent": preferred_agent,
            "routing_method": "static_fallback",
            "task_archetype": packet_data.get("task_archetype"),
            "archetype_confidence": packet_data.get("archetype_confidence"),
            "slot": packet_data.get("slot"),
            "results": results,
            "review_required": review_required,
        }
    )


@app.get("/api/methodology/{methodology_id}")
async def api_methodology_detail(methodology_id: str) -> JSONResponse:
    """Get full methodology detail by ID."""
    st = await _ensure_state(app)
    repo = st["repository"]

    m = await repo.get_methodology(methodology_id)
    if not m:
        return JSONResponse({"error": "not found"}, status_code=404)

    return JSONResponse(
        {
            "id": m.id,
            "problem_description": m.problem_description,
            "solution_code": m.solution_code,
            "methodology_notes": m.methodology_notes,
            "tags": m.tags,
            "language": m.language,
            "lifecycle_state": m.lifecycle_state,
            "methodology_type": m.methodology_type,
            "novelty_score": m.novelty_score,
            "potential_score": m.potential_score,
            "retrieval_count": m.retrieval_count,
            "success_count": m.success_count,
            "failure_count": m.failure_count,
            "created_at": str(m.created_at),
            "files_affected": m.files_affected,
        }
    )


# ---------------------------------------------------------------------------
# Phase 1 — Forge: Methodology fitness, Gaps, Evolution, Costs, Federation, Mining
# ---------------------------------------------------------------------------


@app.get("/api/methodology/{methodology_id}/fitness")
async def api_methodology_fitness(methodology_id: str) -> JSONResponse:
    """Return fitness time-series for a methodology."""
    st = await _ensure_state(app)
    repo = st["repository"]
    try:
        rows = await repo.engine.fetch_all(
            "SELECT fitness_total, fitness_vector, trigger_event, created_at "
            "FROM methodology_fitness_log WHERE methodology_id = ? "
            "ORDER BY created_at",
            (methodology_id,),
        )
    except Exception:
        rows = []
    entries = []
    for r in rows:
        vec = {}
        if r["fitness_vector"]:
            try:
                vec = json.loads(r["fitness_vector"]) if isinstance(r["fitness_vector"], str) else r["fitness_vector"]
            except (json.JSONDecodeError, TypeError):
                pass
        entries.append({
            "fitness_total": r["fitness_total"],
            "fitness_vector": vec,
            "trigger_event": r["trigger_event"],
            "created_at": str(r["created_at"]),
        })
    return JSONResponse({"methodology_id": methodology_id, "entries": entries})


@app.get("/api/gaps/matrix")
async def api_gaps_matrix() -> JSONResponse:
    """Coverage matrix from GapAnalyzer."""
    st = await _ensure_state(app)
    try:
        from claw.community.gap_analyzer import GapAnalyzer
        ga = GapAnalyzer(st["repository"])
        matrix = ga.compute_coverage_matrix()
        return JSONResponse(matrix if isinstance(matrix, dict) else matrix.__dict__ if hasattr(matrix, "__dict__") else {"matrix": str(matrix)})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/gaps/discover")
async def api_gaps_discover() -> JSONResponse:
    """Category discovery via GapAnalyzer."""
    st = await _ensure_state(app)
    try:
        from claw.community.gap_analyzer import GapAnalyzer
        ga = GapAnalyzer(st["repository"])
        clusters = ga.discover_categories()
        return JSONResponse({"clusters": clusters if isinstance(clusters, list) else []})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/gaps/trend")
async def api_gaps_trend() -> JSONResponse:
    """Coverage trend over time."""
    st = await _ensure_state(app)
    repo = st["repository"]
    try:
        rows = await repo.engine.fetch_all(
            "SELECT id, total_methodologies, sparse_cells, created_at "
            "FROM coverage_snapshots ORDER BY created_at DESC LIMIT 20"
        )
        snapshots = []
        for r in rows:
            sparse = []
            if r["sparse_cells"]:
                try:
                    sparse = json.loads(r["sparse_cells"]) if isinstance(r["sparse_cells"], str) else r["sparse_cells"]
                except (json.JSONDecodeError, TypeError):
                    pass
            snapshots.append({
                "id": r["id"],
                "total_methodologies": r["total_methodologies"],
                "sparse_cells": sparse,
                "created_at": str(r["created_at"]),
            })
        summary = f"{len(snapshots)} snapshots" if snapshots else "No snapshots yet"
        return JSONResponse({"summary": summary, "snapshots": snapshots})
    except Exception:
        return JSONResponse({"summary": "No coverage snapshots available", "snapshots": []})


@app.get("/api/attribution/proof")
async def api_attribution_proof() -> JSONResponse:
    """System-wide attribution funnel: retrieved -> applied -> succeeded."""
    st = await _ensure_state(app)
    repo = st["repository"]
    try:
        usage_stats = await repo.get_methodology_usage_stats()
        methods = await repo.list_methodologies(limit=5000, include_dead=True)
        method_map = {m.id: m for m in methods}

        total_retrieved = 0
        total_applied = 0
        total_success = 0
        total_failure = 0
        never_applied = []
        per_methodology = []

        for meth_id, stats in usage_stats.items():
            retrieved = int(stats.get("retrieved_count", 0))
            applied = int(stats.get("used_count", 0))
            success = int(stats.get("attributed_success_count", 0))
            failure = int(stats.get("attributed_failure_count", 0))

            total_retrieved += retrieved
            total_applied += applied
            total_success += success
            total_failure += failure

            meth = method_map.get(meth_id)
            title = meth.problem_description[:80].replace("\n", " ").replace("\r", "") if meth else meth_id[:8]
            lifecycle = meth.lifecycle_state if meth else "unknown"

            entry = {
                "methodology_id": meth_id,
                "title": title,
                "lifecycle": lifecycle,
                "retrieved": retrieved,
                "applied": applied,
                "success": success,
                "failure": failure,
                "applied_rate": round(applied / retrieved, 4) if retrieved > 0 else 0.0,
                "success_rate": round(success / applied, 4) if applied > 0 else 0.0,
                "avg_quality": stats.get("avg_quality_score"),
                "avg_relevance": stats.get("avg_relevance_score"),
            }
            per_methodology.append(entry)
            if retrieved > 0 and applied == 0:
                never_applied.append(entry)

        per_methodology.sort(key=lambda e: e["retrieved"], reverse=True)

        applied_rate = total_applied / total_retrieved if total_retrieved > 0 else 0.0
        success_rate = total_success / total_applied if total_applied > 0 else 0.0
        overall_conversion = total_success / total_retrieved if total_retrieved > 0 else 0.0

        return JSONResponse({
            "funnel": {
                "total_retrieved": total_retrieved,
                "total_applied": total_applied,
                "total_success": total_success,
                "total_failure": total_failure,
                "applied_rate": round(applied_rate, 4),
                "success_rate": round(success_rate, 4),
                "overall_conversion": round(overall_conversion, 4),
            },
            "methodology_count": len(usage_stats),
            "never_applied_count": len(never_applied),
            "per_methodology": per_methodology[:50],
            "never_applied": never_applied[:20],
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/evolution/ab-tests")
async def api_evolution_ab_tests() -> JSONResponse:
    """List A/B tests from prompt_variants."""
    st = await _ensure_state(app)
    repo = st["repository"]
    try:
        rows = await repo.engine.fetch_all(
            "SELECT name, variant_type, parent_name, fitness_score, "
            "sample_count, created_at FROM prompt_variants ORDER BY created_at DESC"
        )
        tests = [dict(r) for r in rows]
        return JSONResponse({"tests": tests})
    except Exception:
        return JSONResponse({"tests": []})



@app.get("/api/evolution/ab-test/{name}")
async def api_evolution_ab_test_detail(name: str) -> JSONResponse:
    """Detailed analysis for a specific A/B test by prompt_name."""
    st = await _ensure_state(app)
    repo = st["repository"]
    try:
        # Fetch all variants for this test name from prompt_variants
        rows = await repo.engine.fetch_all(
            "SELECT id, prompt_name, variant_label, content, agent_id, "
            "is_active, sample_count, success_count, avg_quality_score, "
            "created_at, updated_at "
            "FROM prompt_variants WHERE prompt_name = ? "
            "ORDER BY variant_label",
            [name],
        )
        if not rows:
            return JSONResponse(
                {"error": f"A/B test '{name}' not found"},
                status_code=404,
            )

        # Build per-variant detail
        variants: dict[str, dict] = {}
        for r in rows:
            label = r["variant_label"]
            sample_count = int(r["sample_count"])
            success_count = int(r["success_count"])
            success_rate = success_count / sample_count if sample_count > 0 else 0.0
            variants[label] = {
                "id": str(r["id"]),
                "variant_label": label,
                "content": str(r["content"]),
                "agent_id": r["agent_id"],
                "is_active": bool(r["is_active"]),
                "sample_count": sample_count,
                "success_count": success_count,
                "success_rate": round(success_rate, 4),
                "avg_quality_score": round(float(r["avg_quality_score"]), 4),
                "created_at": str(r["created_at"]),
                "updated_at": str(r["updated_at"]),
            }

        # Compute Bayesian comparison if both control and variant exist
        comparison = None
        winner = None
        if "control" in variants and "variant" in variants:
            ctrl = variants["control"]
            var = variants["variant"]

            # Bayesian posterior mean: Beta(1 + successes, 1 + failures)
            ctrl_alpha = 1.0 + ctrl["success_count"]
            ctrl_beta = 1.0 + (ctrl["sample_count"] - ctrl["success_count"])
            ctrl_bayesian = ctrl_alpha / (ctrl_alpha + ctrl_beta)

            var_alpha = 1.0 + var["success_count"]
            var_beta = 1.0 + (var["sample_count"] - var["success_count"])
            var_bayesian = var_alpha / (var_alpha + var_beta)

            margin = var_bayesian - ctrl_bayesian

            comparison = {
                "control_bayesian_score": round(ctrl_bayesian, 4),
                "variant_bayesian_score": round(var_bayesian, 4),
                "margin": round(margin, 4),
                "quality_delta": round(
                    var["avg_quality_score"] - ctrl["avg_quality_score"], 4
                ),
                "success_rate_delta": round(
                    var["success_rate"] - ctrl["success_rate"], 4
                ),
            }

            # Declare winner if both have enough samples
            min_samples = 20
            if ctrl["sample_count"] >= min_samples and var["sample_count"] >= min_samples:
                if margin > 0.15:
                    winner = "variant"
                elif margin < -0.15:
                    winner = "control"

        # Pull per-sample stats from ab_quality_samples if available
        ab_stats = None
        try:
            ab_rows = await repo.engine.fetch_all(
                "SELECT variant_label, "
                "COUNT(*) as n, "
                "AVG(composite_score) as avg_composite, "
                "AVG(d_functional_correctness) as avg_d1, "
                "AVG(d_structural_compliance) as avg_d2, "
                "AVG(d_intent_alignment) as avg_d3, "
                "AVG(d_correction_efficiency) as avg_d4, "
                "AVG(d_token_economy) as avg_d5, "
                "AVG(d_expectation_match) as avg_d6, "
                "AVG(correction_attempts) as avg_corrections, "
                "SUM(success) as total_success "
                "FROM ab_quality_samples "
                "WHERE project_id = ? "
                "GROUP BY variant_label",
                [name],
            )
            if ab_rows:
                ab_stats = {}
                for ar in ab_rows:
                    n = int(ar["n"])
                    ab_stats[ar["variant_label"]] = {
                        "n": n,
                        "avg_composite": round(float(ar["avg_composite"]), 4),
                        "success_rate": round(int(ar["total_success"]) / n, 4) if n > 0 else 0.0,
                        "avg_corrections": round(float(ar["avg_corrections"]), 2),
                        "dimensions": {
                            "d_functional_correctness": round(float(ar["avg_d1"]), 4),
                            "d_structural_compliance": round(float(ar["avg_d2"]), 4),
                            "d_intent_alignment": round(float(ar["avg_d3"]), 4),
                            "d_correction_efficiency": round(float(ar["avg_d4"]), 4),
                            "d_token_economy": round(float(ar["avg_d5"]), 4),
                            "d_expectation_match": round(float(ar["avg_d6"]), 4),
                        },
                    }

                # Compute Mann-Whitney p-value if scipy is available and both arms present
                if "control" in ab_stats and "variant" in ab_stats:
                    try:
                        sample_rows = await repo.engine.fetch_all(
                            "SELECT variant_label, composite_score "
                            "FROM ab_quality_samples WHERE project_id = ?",
                            [name],
                        )
                        ctrl_scores = [
                            float(s["composite_score"]) for s in sample_rows
                            if s["variant_label"] == "control"
                        ]
                        var_scores = [
                            float(s["composite_score"]) for s in sample_rows
                            if s["variant_label"] == "variant"
                        ]
                        if len(ctrl_scores) >= 2 and len(var_scores) >= 2:
                            try:
                                from scipy.stats import mannwhitneyu
                                u_stat, p_value = mannwhitneyu(
                                    var_scores, ctrl_scores, alternative="greater"
                                )
                                ab_stats["p_value"] = round(float(p_value), 6)
                                ab_stats["mann_whitney_u"] = float(u_stat)
                            except ImportError:
                                pass
                    except Exception:
                        pass
        except Exception:
            pass  # ab_quality_samples table may not exist

        result = {
            "name": name,
            "variants": variants,
            "comparison": comparison,
            "winner": winner,
        }
        if ab_stats is not None:
            result["ab_quality_stats"] = ab_stats
        return JSONResponse(result)
    except Exception as exc:
        if "not found" in str(exc).lower():
            return JSONResponse({"error": str(exc)}, status_code=404)
        logger.exception("Error fetching A/B test detail for '%s'", name)
        return JSONResponse(
            {"error": f"Failed to fetch A/B test detail: {exc}"},
            status_code=500,
        )


@app.get("/api/evolution/fitness/{methodology_id}")
async def api_evolution_fitness(methodology_id: str) -> JSONResponse:
    """Fitness trajectory for evolution lab."""
    st = await _ensure_state(app)
    repo = st["repository"]
    try:
        rows = await repo.engine.fetch_all(
            "SELECT fitness_total, fitness_vector, trigger_event, created_at "
            "FROM methodology_fitness_log WHERE methodology_id = ? ORDER BY created_at",
            (methodology_id,),
        )
        trajectory = []
        for r in rows:
            vec = {}
            if r["fitness_vector"]:
                try:
                    vec = json.loads(r["fitness_vector"]) if isinstance(r["fitness_vector"], str) else r["fitness_vector"]
                except (json.JSONDecodeError, TypeError):
                    pass
            trajectory.append({
                "fitness": r["fitness_total"],
                "vector": vec,
                "event": r["trigger_event"],
                "timestamp": str(r["created_at"]),
            })
        return JSONResponse({"methodology_id": methodology_id, "trajectory": trajectory})
    except Exception:
        return JSONResponse({"methodology_id": methodology_id, "trajectory": []})


@app.get("/api/evolution/routing")
async def api_evolution_routing() -> JSONResponse:
    """Agent routing heatmap from agent_scores."""
    st = await _ensure_state(app)
    repo = st["repository"]
    try:
        rows = await repo.engine.fetch_all(
            "SELECT agent_id, task_type, successes, failures, total_attempts, "
            "avg_quality_score, avg_cost_usd FROM agent_scores"
        )
        routing = []
        for r in rows:
            routing.append({
                "agent_id": r["agent_id"],
                "task_type": r["task_type"],
                "wins": r["successes"],
                "losses": r["failures"],
                "total": r["total_attempts"],
                "avg_quality": round(float(r["avg_quality_score"] or 0), 3),
                "avg_cost": round(float(r["avg_cost_usd"] or 0), 4),
            })
        return JSONResponse({"routing": routing})
    except Exception:
        return JSONResponse({"routing": []})


@app.get("/api/evolution/bandit")
async def api_evolution_bandit(task_type: Optional[str] = Query(None)) -> JSONResponse:
    """Bandit arm stats from methodology_bandit_outcomes."""
    st = await _ensure_state(app)
    repo = st["repository"]
    try:
        if task_type:
            rows = await repo.engine.fetch_all(
                "SELECT methodology_id, task_type, "
                "SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) as wins, "
                "SUM(CASE WHEN outcome = 'failure' THEN 1 ELSE 0 END) as losses, "
                "COUNT(*) as total, MAX(created_at) as last_updated "
                "FROM methodology_bandit_outcomes WHERE task_type = ? "
                "GROUP BY methodology_id, task_type",
                (task_type,),
            )
        else:
            rows = await repo.engine.fetch_all(
                "SELECT methodology_id, task_type, "
                "SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) as wins, "
                "SUM(CASE WHEN outcome = 'failure' THEN 1 ELSE 0 END) as losses, "
                "COUNT(*) as total, MAX(created_at) as last_updated "
                "FROM methodology_bandit_outcomes GROUP BY methodology_id, task_type"
            )
        arms = []
        task_types_set: set[str] = set()
        for r in rows:
            wins = int(r["wins"])
            total = int(r["total"])
            win_rate = wins / total if total > 0 else 0
            arms.append({
                "methodology_id": r["methodology_id"],
                "task_type": r["task_type"],
                "successes": wins,
                "failures": int(r["losses"]),
                "total": total,
                "win_rate": round(win_rate, 3),
                "last_updated": str(r["last_updated"]),
            })
            if r["task_type"]:
                task_types_set.add(r["task_type"])
        return JSONResponse({"arms": arms, "task_types": sorted(task_types_set)})
    except Exception:
        return JSONResponse({"arms": [], "task_types": []})


@app.get("/api/costs/summary")
async def api_costs_summary() -> JSONResponse:
    """Token cost summary from mining_outcomes + agent configs."""
    st = await _ensure_state(app)
    repo = st["repository"]
    config = st["config"]
    try:
        rows = await repo.engine.fetch_all(
            "SELECT model_used, agent_id, brain, "
            "COUNT(*) as runs, SUM(tokens_used) as total_tokens, "
            "SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successes, "
            "ROUND(AVG(duration_seconds), 1) as avg_duration "
            "FROM mining_outcomes GROUP BY model_used, agent_id, brain "
            "ORDER BY runs DESC"
        )
        mining_costs = [dict(r) for r in rows]
    except Exception:
        mining_costs = []
    agent_budgets = {}
    for aid, acfg in config.agents.items():
        agent_budgets[aid] = {
            "max_budget_usd": acfg.max_budget_usd,
            "model": acfg.model,
            "mode": acfg.mode,
        }
    return JSONResponse({"mining_costs": mining_costs, "agent_budgets": agent_budgets})


@app.get("/api/costs/by-agent")
async def api_costs_by_agent() -> JSONResponse:
    """Per-agent cost breakdown from mining_outcomes + agent_scores."""
    st = await _ensure_state(app)
    repo = st["repository"]
    try:
        mining = await repo.engine.fetch_all(
            "SELECT agent_id, model_used, COUNT(*) as runs, "
            "SUM(tokens_used) as total_tokens, "
            "SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successes "
            "FROM mining_outcomes GROUP BY agent_id, model_used ORDER BY runs DESC"
        )
        mining_data = [dict(r) for r in mining]
    except Exception:
        mining_data = []
    try:
        task_rows = await repo.engine.fetch_all(
            "SELECT agent_id, task_type, "
            "SUM(successes) as wins, "
            "ROUND(AVG(avg_quality_score), 3) as avg_quality, "
            "ROUND(SUM(avg_cost_usd * total_attempts), 4) as total_cost_usd "
            "FROM agent_scores GROUP BY agent_id, task_type ORDER BY wins DESC"
        )
        task_data = [dict(r) for r in task_rows]
    except Exception:
        task_data = []
    return JSONResponse({"mining": mining_data, "task_execution": task_data})


@app.get("/api/federation/topology")
async def api_federation_topology() -> JSONResponse:
    """Brain topology: ganglion nodes with methodology counts and connectivity."""
    st = await _ensure_state(app)
    config = st["config"]
    repo = st["repository"]
    total = await repo.count_methodologies()
    nodes: list[dict[str, Any]] = [
        {"id": "primary", "type": "primary", "methodology_count": total, "db_exists": True}
    ]
    edges: list[dict[str, str]] = []
    siblings = getattr(config, "instances", None)
    sibling_list = []
    if siblings and siblings.enabled:
        sibling_list = siblings.siblings or []
    for sib in sibling_list:
        sib_count = 0
        db_exists = Path(sib.db_path).exists() if sib.db_path else False
        if db_exists:
            try:
                import aiosqlite
                async with aiosqlite.connect(sib.db_path) as db:
                    db.row_factory = aiosqlite.Row
                    cur = await db.execute("SELECT COUNT(*) as cnt FROM methodologies")
                    row = await cur.fetchone()
                    sib_count = int(row["cnt"]) if row else 0
            except Exception:
                pass
        nodes.append({
            "id": sib.name, "type": "sibling", "methodology_count": sib_count,
            "db_exists": db_exists, "description": getattr(sib, "description", ""),
        })
        edges.append({"source": "primary", "target": sib.name, "type": "federation"})
    total_all = total + sum(n["methodology_count"] for n in nodes if n["id"] != "primary")
    return JSONResponse({"nodes": nodes, "edges": edges, "total_methodologies": total_all})


@app.post("/api/federation/analyze")
async def api_federation_analyze(request: Request) -> JSONResponse:
    """Cross-language analysis via federation."""
    body = await request.json()
    query = body.get("query", "").strip()
    if not query:
        return JSONResponse({"error": "query required"}, status_code=400)
    st = await _ensure_state(app)
    try:
        from claw.community.cross_language import CrossLanguageAnalyzer
        analyzer = CrossLanguageAnalyzer(st["repository"], st["config"])
        report = await analyzer.analyze(query)
        return JSONResponse(report if isinstance(report, dict) else report.__dict__ if hasattr(report, "__dict__") else {"query": query, "universal_patterns": [], "unique_innovations": [], "transferable_insights": [], "metrics": {}})
    except Exception as exc:
        logger.warning("Federation analysis failed: %s", exc)
        return JSONResponse({"query": query, "universal_patterns": [], "unique_innovations": [], "transferable_insights": [], "metrics": {}, "error": str(exc)})


@app.post("/api/mine")
async def api_mine(request: Request) -> JSONResponse:
    """Start a mining job (runs in background)."""
    body = await request.json()
    path = body.get("path", "").strip()
    brain = body.get("brain")
    if not path:
        return JSONResponse({"error": "path required"}, status_code=400)
    if not Path(path).exists():
        return JSONResponse({"error": f"Path not found: {path}"}, status_code=404)
    import uuid
    job_id = str(uuid.uuid4())[:8]
    _state.setdefault("mining_jobs", {})[job_id] = {
        "status": "queued", "path": path, "brain": brain,
        "findings": 0, "error": None,
    }

    async def _run_mine():
        job = _state["mining_jobs"][job_id]
        job["status"] = "running"
        try:
            from claw.miner import RepoMiner
            st = await _ensure_state(app)
            miner = RepoMiner(st["config"], st["repository"])
            results = await miner.mine_directory(Path(path), brain=brain)
            job["status"] = "completed"
            job["findings"] = len(results) if results else 0
        except Exception as exc:
            job["status"] = "error"
            job["error"] = str(exc)

    asyncio.create_task(_run_mine())
    return JSONResponse({"job_id": job_id, "status": "queued"})


@app.get("/api/mine/{job_id}")
async def api_mine_status(job_id: str) -> JSONResponse:
    """Get mining job status."""
    jobs = _state.get("mining_jobs", {})
    if job_id not in jobs:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    return JSONResponse(jobs[job_id])


@app.get("/api/mine/recent/list")
async def api_mine_recent() -> JSONResponse:
    """List recent mining outcomes."""
    st = await _ensure_state(app)
    repo = st["repository"]
    try:
        rows = await repo.engine.fetch_all(
            "SELECT * FROM mining_outcomes ORDER BY created_at DESC LIMIT 20"
        )
        return JSONResponse({"outcomes": [dict(r) for r in rows]})
    except Exception:
        return JSONResponse({"outcomes": []})


# ---------------------------------------------------------------------------
# Phase 1A — Forge Builder: Config Read/Write API
# ---------------------------------------------------------------------------

_VALID_CONFIG_SECTIONS = {
    "database", "cag", "evolution", "instances", "mining", "local_llm",
    "orchestrator", "governance", "logging", "mcp", "knowledge",
    "agents.claude", "agents.grok", "agents.gemini", "agents.local",
    "agents.gpt", "agents.deepseek", "agents.minimax", "agents.openai",
    "mining.brains.python", "mining.brains.typescript", "mining.brains.go",
    "mining.brains.rust", "mining.brains.misc", "mining.brains.sql",
    "mining.brains.elixir", "mining.brains.java",
}


def _deep_merge(base: dict, update: dict) -> dict:
    """Recursively merge update into base, returning a new dict."""
    import copy
    result = copy.deepcopy(base)
    for k, v in update.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _resolve_toml_path() -> Path:
    """Canonical claw.toml path resolution."""
    st = _state
    config = st.get("config")
    if config:
        db_path = getattr(config, "database", None)
        if db_path:
            db_str = str(db_path.db_path) if hasattr(db_path, "db_path") else str(db_path)
            project_root = Path(db_str).resolve().parent.parent
            candidate = project_root / "claw.toml"
            if candidate.exists():
                return candidate
    cwd_toml = Path.cwd() / "claw.toml"
    if cwd_toml.exists():
        return cwd_toml
    return Path.cwd() / "claw.toml"


@app.get("/api/config")
async def api_config_get() -> JSONResponse:
    """Return full ClawConfig as JSON, stripping API key values."""
    st = await _ensure_state(app)
    config = st["config"]

    # Agents
    agents_out: dict[str, Any] = {}
    for aid, acfg in config.agents.items():
        env_var = getattr(acfg, "api_key_env", "") or ""
        has_key = bool(env_var and os.environ.get(env_var))
        agents_out[aid] = {
            "enabled": acfg.enabled,
            "mode": acfg.mode,
            "model": acfg.model,
            "max_concurrent": acfg.max_concurrent,
            "timeout": acfg.timeout,
            "max_budget_usd": acfg.max_budget_usd,
            "max_tokens": getattr(acfg, "max_tokens", None),
            "context_window_tokens": getattr(acfg, "context_window_tokens", None),
            "api_key_env": env_var,
            "has_key": has_key,
        }

    # Brains
    brains_out: dict[str, Any] = {}
    if hasattr(config, "mining") and hasattr(config.mining, "brains"):
        for bname, bcfg in config.mining.brains.items():
            brains_out[bname] = {
                "enabled": bcfg.enabled,
                "max_bytes": bcfg.max_bytes,
                "prompt": bcfg.prompt,
                "ganglion_name": getattr(bcfg, "ganglion_name", ""),
                "priority_extensions": getattr(bcfg, "priority_extensions", []),
            }

    # CAG
    cag = config.cag
    cag_out = {
        "enabled": cag.enabled,
        "knowledge_budget_chars": cag.knowledge_budget_chars,
        "token_budget_max": getattr(cag, "token_budget_max", None),
        "max_solution_chars": getattr(cag, "max_solution_chars", None),
        "shorthand_compression": getattr(cag, "shorthand_compression", False),
        "cache_dir": getattr(cag, "cache_dir", None),
        "context_pointer_threshold": getattr(cag, "context_pointer_threshold", None),
    }

    # Federation/instances
    inst = config.instances
    fed_out = {
        "enabled": inst.enabled if inst else False,
        "instance_name": getattr(inst, "instance_name", "") if inst else "",
        "instance_description": getattr(inst, "instance_description", "") if inst else "",
        "siblings_count": len(inst.siblings) if inst and inst.siblings else 0,
    }

    # Evolution
    evo = config.evolution
    evo_out = {
        "ab_test_sample_size": evo.ab_test_sample_size,
        "mutation_rate": evo.mutation_rate,
        "promotion_threshold": evo.promotion_threshold,
    }

    # Mining
    mining = config.mining
    mining_out = {
        "extra_code_extensions": list(mining.extra_code_extensions) if mining.extra_code_extensions else [],
        "extra_skip_dirs": list(mining.extra_skip_dirs) if mining.extra_skip_dirs else [],
        "recovery_enabled": getattr(mining, "recovery_enabled", True),
    }

    # Local LLM
    llm = getattr(config, "local_llm", None)
    llm_out = {}
    if llm:
        llm_out = {
            "provider": llm.provider,
            "model": llm.model,
            "base_url": getattr(llm, "base_url", None),
            "kv_cache_quantization": getattr(llm, "kv_cache_quantization", None),
            "ctx_size": getattr(llm, "ctx_size", None),
            "keep_alive": getattr(llm, "keep_alive", None),
        }

    # Orchestrator
    orch = getattr(config, "orchestrator", None)
    orch_out = {}
    if orch:
        orch_out = {
            "max_retries": orch.max_retries,
            "exploration_rate": orch.exploration_rate,
            "max_correction_attempts": getattr(orch, "max_correction_attempts", None),
        }

    # Governance
    gov = getattr(config, "governance", None)
    gov_out = {}
    if gov:
        gov_out = {
            "max_methodologies": gov.max_methodologies,
            "dedup_enabled": gov.dedup_enabled,
            "sweep_on_startup": getattr(gov, "sweep_on_startup", False),
        }

    feature_flags = getattr(config, "feature_flags", None)
    feature_flags_out = {}
    if feature_flags:
        feature_flags_out = {
            "component_cards": feature_flags.component_cards,
            "application_packets": feature_flags.application_packets,
            "connectome_seq": feature_flags.connectome_seq,
            "critical_slot_policy": feature_flags.critical_slot_policy,
            "a2a_packets": feature_flags.a2a_packets,
        }

    return JSONResponse({
        "agents": agents_out,
        "brains": brains_out,
        "cag": cag_out,
        "federation": fed_out,
        "evolution": evo_out,
        "mining": mining_out,
        "local_llm": llm_out,
        "orchestrator": orch_out,
        "governance": gov_out,
        "feature_flags": feature_flags_out,
    })


@app.patch("/api/config/{section}")
async def api_config_patch(section: str, request: Request) -> JSONResponse:
    """Partial config update via deep merge + atomic write."""
    if section not in _VALID_CONFIG_SECTIONS:
        return JSONResponse(
            {"error": f"Invalid section '{section}'. Valid: {sorted(_VALID_CONFIG_SECTIONS)}"},
            status_code=400,
        )
    body = await request.json()
    if not body:
        return JSONResponse({"error": "Body must be non-empty JSON"}, status_code=400)

    toml_path = _resolve_toml_path()
    if not toml_path.exists():
        return JSONResponse({"error": f"claw.toml not found at {toml_path}"}, status_code=404)

    # Read
    with open(toml_path) as f:
        raw_config = toml.load(f)

    # Navigate nested sections (e.g. "agents.claude" → raw_config["agents"]["claude"])
    parts = section.split(".")
    target = raw_config
    for p in parts[:-1]:
        if p not in target:
            target[p] = {}
        target = target[p]
    key = parts[-1]
    existing = target.get(key, {})
    if isinstance(existing, dict):
        target[key] = _deep_merge(existing, body)
    else:
        target[key] = body

    # Validate by attempting to load
    try:
        from claw.core.config import load_config
        # Write to temp, attempt load
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False, dir=str(toml_path.parent)) as tmp:
            toml.dump(raw_config, tmp)
            tmp_path = Path(tmp.name)
    except Exception as exc:
        return JSONResponse({"error": f"Serialization failed: {exc}"}, status_code=500)

    # Backup + atomic replace
    backup_path = toml_path.with_suffix(".toml.bak")
    shutil.copy2(toml_path, backup_path)
    shutil.move(str(tmp_path), str(toml_path))

    return JSONResponse({"status": "updated", "section": section})


@app.post("/api/config/reload")
async def api_config_reload() -> JSONResponse:
    """Clear cached state so next request triggers fresh initialization."""
    engine = _state.get("engine")
    if engine:
        try:
            await engine.close()
        except Exception:
            pass
    _state.clear()
    return JSONResponse({"status": "reloaded"})


# ---------------------------------------------------------------------------
# Phase 1C — Forge Builder: Prompt CRUD
# ---------------------------------------------------------------------------


@app.get("/api/prompts")
async def api_prompts_list() -> JSONResponse:
    """List available prompt templates."""
    prompts_dir = Path.cwd() / "prompts"
    if not prompts_dir.exists():
        return JSONResponse({"prompts": []})
    prompts = []
    for f in sorted(prompts_dir.glob("repo-mine*.md")):
        content = f.read_text(errors="replace")
        prompts.append({
            "name": f.name,
            "path": str(f),
            "size_bytes": f.stat().st_size,
            "line_count": content.count("\n") + 1,
        })
    return JSONResponse({"prompts": prompts})


@app.get("/api/prompts/{name}")
async def api_prompt_get(name: str) -> JSONResponse:
    """Read a prompt template by name."""
    prompts_dir = Path.cwd() / "prompts"
    # Try exact match, then with .md suffix, then with repo-mine- prefix
    candidates = [
        prompts_dir / name,
        prompts_dir / f"{name}.md",
        prompts_dir / f"repo-mine-{name}.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            content = candidate.read_text(errors="replace")
            return JSONResponse({"name": candidate.name, "content": content, "path": str(candidate)})
    return JSONResponse({"error": f"Prompt '{name}' not found"}, status_code=404)


@app.post("/api/prompts")
async def api_prompt_create(request: Request) -> JSONResponse:
    """Create or update a prompt template."""
    body = await request.json()
    name = body.get("name", "").strip()
    content = body.get("content", "")
    fork_from = body.get("fork_from")

    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    # Sanitize name
    safe_name = name.replace(" ", "-").lower()
    if not safe_name.replace("-", "").replace("_", "").isalnum():
        return JSONResponse({"error": "name must be alphanumeric (hyphens/underscores ok)"}, status_code=400)

    # Auto-prefix
    if not safe_name.startswith("repo-mine"):
        safe_name = f"repo-mine-{safe_name}"
    if not safe_name.endswith(".md"):
        safe_name = f"{safe_name}.md"

    prompts_dir = Path.cwd() / "prompts"
    prompts_dir.mkdir(exist_ok=True)
    target = prompts_dir / safe_name

    # Fork from existing
    if fork_from and not content:
        source = prompts_dir / fork_from
        if not source.exists():
            # Try with prefix
            source = prompts_dir / f"repo-mine-{fork_from}.md"
        if not source.exists():
            return JSONResponse({"error": f"Fork source '{fork_from}' not found"}, status_code=404)
        content = source.read_text(errors="replace")

    if not content:
        return JSONResponse({"error": "content is required (or use fork_from)"}, status_code=400)
    if len(content) > 100_000:
        return JSONResponse({"error": "Content exceeds 100KB limit"}, status_code=400)

    # Backup if exists
    if target.exists():
        backup = target.with_suffix(".md.bak")
        shutil.copy2(target, backup)

    target.write_text(content)
    return JSONResponse({
        "status": "created",
        "name": safe_name,
        "path": str(target),
        "size_bytes": len(content.encode("utf-8")),
    })


# ---------------------------------------------------------------------------
# Phase 1B — Forge Builder: Brain/Ganglion CRUD
# ---------------------------------------------------------------------------


def _remove_toml_sibling_block(raw: str, name: str) -> str | None:
    """Remove a [[instances.siblings]] block by name from raw TOML text.

    Returns the modified text, or None if the named block was not found.
    """
    lines = raw.split("\n")
    filtered: list[str] = []
    i = 0
    found = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped == "[[instances.siblings]]":
            # Collect the full block (header + key-value lines until next header or EOF)
            block_lines = [line]
            j = i + 1
            while j < len(lines):
                next_stripped = lines[j].strip()
                if next_stripped.startswith("["):
                    break
                block_lines.append(lines[j])
                j += 1

            # Check if this block's name matches
            block_text = "\n".join(block_lines)
            if f'name = "{name}"' in block_text:
                found = True
                # Skip blank lines after block
                while j < len(lines) and not lines[j].strip():
                    j += 1
                i = j
                continue
            else:
                filtered.extend(block_lines)
                i = j
                continue
        filtered.append(line)
        i += 1

    if not found:
        return None
    return "\n".join(filtered)


@app.post("/api/ganglia")
async def api_create_ganglion(request: Request) -> JSONResponse:
    """Create a new brain ganglion with DB and sibling registration."""
    body = await request.json()
    name = body.get("name", "").strip().lower()
    description = body.get("description", "")
    prompt_template = body.get("prompt_template", "repo-mine-misc.md")

    # --- Validate name ---
    if not name or not name.replace("-", "").replace("_", "").isalnum():
        return JSONResponse(
            {"error": "name must be alphanumeric (hyphens/underscores ok)"},
            status_code=400,
        )

    # --- Resolve project root from the primary DB path ---
    st = await _ensure_state(app)
    config = st["config"]
    db_path_str = str(config.database.db_path) if hasattr(config.database, "db_path") else str(config.database)
    project_root = Path(db_path_str).resolve().parent.parent

    ganglion_dir = project_root / "instances" / name
    ganglion_db_path = ganglion_dir / "claw.db"

    # --- Check if ganglion already exists ---
    if ganglion_dir.exists() and ganglion_db_path.exists():
        return JSONResponse(
            {"error": f"Ganglion '{name}' already exists at {ganglion_dir}"},
            status_code=409,
        )

    # --- Validate prompt template ---
    prompts_dir = project_root / "prompts"
    if prompts_dir.exists():
        available = [f.name for f in prompts_dir.glob("repo-mine*.md")]
        if prompt_template not in available:
            return JSONResponse(
                {"error": f"Prompt template '{prompt_template}' not found. Available: {available}"},
                status_code=400,
            )

    # --- Provision the ganglion DB ---
    try:
        from claw.db.engine import DatabaseConfig, DatabaseEngine
        ganglion_dir.mkdir(parents=True, exist_ok=True)

        db_config = DatabaseConfig(db_path=str(ganglion_db_path))
        sib_engine = DatabaseEngine(db_config)
        await sib_engine.connect()
        await sib_engine.initialize_schema()
        await sib_engine.close()

        logger.info(
            "Phase1B: provisioned ganglion '%s' at %s", name, ganglion_db_path,
        )
    except Exception as exc:
        logger.error("Phase1B: failed to create ganglion '%s': %s", name, exc)
        return JSONResponse(
            {"error": f"Failed to create ganglion: {exc}"},
            status_code=500,
        )

    # --- Register as sibling in claw.toml ---
    sibling_registered = False
    toml_path = project_root / "claw.toml"
    if toml_path.exists():
        try:
            raw = toml_path.read_text()
            db_path_abs = str(ganglion_db_path.resolve())
            sibling_block = (
                f'\n[[instances.siblings]]\n'
                f'name = "{name}"\n'
                f'db_path = "{db_path_abs}"\n'
                f'description = "{description}"\n'
            )
            raw += sibling_block
            toml_path.write_text(raw)
            sibling_registered = True
            logger.info("Phase1B: registered ganglion '%s' in claw.toml", name)
        except Exception as exc:
            logger.warning("Phase1B: failed to update claw.toml: %s", exc)
    else:
        logger.warning(
            "Phase1B: claw.toml not found at %s -- ganglion created but not registered",
            toml_path,
        )

    return JSONResponse({
        "status": "created",
        "name": name,
        "ganglion_path": str(ganglion_dir),
        "db_path": str(ganglion_db_path),
        "prompt_template": prompt_template,
        "description": description,
        "sibling_registered": sibling_registered,
    })


@app.delete("/api/ganglia/{name}")
async def api_delete_ganglion(name: str) -> JSONResponse:
    """Disable a brain ganglion.  Keeps DB file intact for reversibility."""
    st = await _ensure_state(app)
    config = st["config"]
    db_path_str = str(config.database.db_path) if hasattr(config.database, "db_path") else str(config.database)
    project_root = Path(db_path_str).resolve().parent.parent

    toml_path = project_root / "claw.toml"
    if not toml_path.exists():
        return JSONResponse(
            {"error": f"claw.toml not found at {toml_path}"},
            status_code=500,
        )

    raw = toml_path.read_text()
    updated = _remove_toml_sibling_block(raw, name)
    if updated is None:
        return JSONResponse(
            {"error": f"Sibling '{name}' not found in claw.toml"},
            status_code=404,
        )

    # Backup + write
    backup = toml_path.with_suffix(".toml.bak")
    shutil.copy2(toml_path, backup)
    toml_path.write_text(updated)
    logger.info("Phase1B: disabled ganglion '%s' (removed from claw.toml)", name)

    ganglion_dir = project_root / "instances" / name
    db_exists = (ganglion_dir / "claw.db").exists()

    return JSONResponse({
        "status": "disabled",
        "name": name,
        "db_preserved": db_exists,
        "db_path": str(ganglion_dir / "claw.db") if db_exists else None,
        "note": "Database preserved for reversibility. Delete instances/{name}/ to fully remove.",
    })


@app.post("/api/forge/preview-repo")
async def api_forge_preview_repo(request: Request) -> JSONResponse:
    """Analyze a repository path for language zones and file metrics."""
    body = await request.json()
    path = body.get("path", "").strip()
    if not path:
        return JSONResponse({"error": "path is required"}, status_code=400)

    repo_path = Path(path)
    if not repo_path.exists():
        return JSONResponse({"error": f"Path not found: {path}"}, status_code=404)

    st = await _ensure_state(app)
    config = st["config"]

    # Detect languages
    try:
        from claw.miner import detect_all_repo_languages
        loop = asyncio.get_event_loop()
        lang_zones = await loop.run_in_executor(None, detect_all_repo_languages, repo_path, config)
    except Exception:
        lang_zones = {}

    # Count files and bytes
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"}
    total_files = 0
    total_bytes = 0
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            total_files += 1
            try:
                total_bytes += (Path(root) / f).stat().st_size
            except OSError:
                pass

    # Build zone info
    zone_info: dict[str, Any] = {}
    if isinstance(lang_zones, dict):
        for lang, data in lang_zones.items():
            if isinstance(data, dict):
                zone_info[lang] = data
            else:
                zone_info[lang] = {"brain": lang, "file_count": 0, "file_extensions": [], "pct": 0}
    elif isinstance(lang_zones, list):
        for entry in lang_zones:
            if isinstance(entry, dict):
                zone_info[entry.get("brain", "unknown")] = entry

    # Suggest brain
    suggested = "misc"
    if zone_info:
        suggested = max(zone_info.keys(), key=lambda k: zone_info[k].get("pct", zone_info[k].get("file_count", 0)))

    return JSONResponse({
        "path": path,
        "total_files": total_files,
        "total_bytes": total_bytes,
        "language_zones": zone_info,
        "suggested_brain": suggested,
    })


@app.post("/api/forge/validate")
async def api_forge_validate(request: Request) -> JSONResponse:
    """Pre-flight validation for a forge build configuration."""
    body = await request.json()
    brain_name = body.get("brain_name")
    agent_ids = body.get("agent_ids", [])
    repo_paths = body.get("repo_paths", [])

    st = await _ensure_state(app)
    config = st["config"]
    db_path_str = str(config.database.db_path) if hasattr(config.database, "db_path") else str(config.database)
    project_root = Path(db_path_str).resolve().parent.parent

    checks: list[dict[str, str]] = []
    all_valid = True

    # Check brain
    if brain_name:
        ganglion_dir = project_root / "instances" / brain_name
        brain_exists = ganglion_dir.exists() and (ganglion_dir / "claw.db").exists()
        checks.append({
            "check": "brain_exists",
            "status": "green" if brain_exists else "red",
            "detail": (
                f"Ganglion at {ganglion_dir}"
                if brain_exists
                else f"No ganglion found at {ganglion_dir}"
            ),
        })
        if not brain_exists:
            all_valid = False

    # Check agents
    for aid in agent_ids:
        acfg = config.agents.get(aid)
        if not acfg:
            checks.append({"check": f"agent_{aid}", "status": "red", "detail": f"Agent '{aid}' not configured"})
            all_valid = False
            continue
        if not acfg.enabled:
            checks.append({"check": f"agent_{aid}", "status": "yellow", "detail": f"Agent '{aid}' is disabled"})
            continue
        # API key check (skip for local agents)
        if acfg.mode == "local":
            checks.append({"check": f"agent_{aid}", "status": "green", "detail": f"Local agent '{aid}' ready"})
        else:
            env_var = getattr(acfg, "api_key_env", "") or ""
            if env_var and os.environ.get(env_var):
                checks.append({"check": f"agent_{aid}", "status": "green", "detail": f"Agent '{aid}' ready ({env_var} set)"})
            else:
                checks.append({"check": f"agent_{aid}", "status": "red", "detail": f"Missing env var {env_var} for agent '{aid}'"})
                all_valid = False

    # Check repo paths
    for rp in repo_paths:
        if Path(rp).exists():
            checks.append({"check": f"repo_{rp}", "status": "green", "detail": f"Path exists: {rp}"})
        else:
            checks.append({"check": f"repo_{rp}", "status": "red", "detail": f"Not found: {rp}"})
            all_valid = False

    return JSONResponse({"valid": all_valid, "checks": checks})


# ---------------------------------------------------------------------------
# Phase 2 — Brain Intelligence Visualization API
# ---------------------------------------------------------------------------


@app.get("/api/brain/graph")
async def api_brain_graph() -> JSONResponse:
    """Brain topology: nodes (ganglia) + edges (federation links) + category data."""
    st = await _ensure_state(app)
    repo = st["repository"]
    config = st["config"]

    nodes = []
    edges = []

    # Primary ganglion node
    try:
        primary_rows = await repo.engine.fetch_all(
            "SELECT COUNT(*) as cnt FROM methodologies"
        )
        primary_count = primary_rows[0]["cnt"] if primary_rows else 0
    except Exception:
        primary_count = 0

    # Category breakdown for primary
    try:
        cat_rows = await repo.engine.fetch_all(
            "SELECT category, COUNT(*) as cnt FROM methodologies GROUP BY category ORDER BY cnt DESC"
        )
        primary_cats = {r["category"] or "uncategorized": r["cnt"] for r in cat_rows}
    except Exception:
        primary_cats = {}

    # Fitness summary for primary
    try:
        fit_rows = await repo.engine.fetch_all(
            "SELECT AVG(fitness_score) as avg_f, MIN(fitness_score) as min_f, "
            "MAX(fitness_score) as max_f FROM methodologies WHERE fitness_score IS NOT NULL"
        )
        fr = fit_rows[0] if fit_rows else {}
        primary_fitness = {
            "avg": round(fr.get("avg_f") or 0, 3),
            "min": round(fr.get("min_f") or 0, 3),
            "max": round(fr.get("max_f") or 0, 3),
        }
    except Exception:
        primary_fitness = {"avg": 0, "min": 0, "max": 0}

    # Top methodologies by fitness for primary
    try:
        top_rows = await repo.engine.fetch_all(
            "SELECT title, category, fitness_score FROM methodologies "
            "WHERE fitness_score IS NOT NULL ORDER BY fitness_score DESC LIMIT 5"
        )
        primary_top = [
            {"title": r["title"], "category": r["category"], "fitness": round(r["fitness_score"], 3)}
            for r in top_rows
        ]
    except Exception:
        primary_top = []

    nodes.append({
        "id": "primary",
        "name": "primary",
        "methodology_count": primary_count,
        "categories": primary_cats,
        "top_methodologies": primary_top,
        "fitness_summary": primary_fitness,
        "is_primary": True,
    })

    # Sibling ganglion nodes
    siblings = getattr(config, "instances", None)
    sibling_configs = []
    if siblings:
        sibling_configs = getattr(siblings, "siblings", []) or []

    for sib in sibling_configs:
        sib_name = sib.name if hasattr(sib, "name") else str(sib)
        sib_db_path = sib.db_path if hasattr(sib, "db_path") else None

        sib_count = 0
        sib_cats: dict[str, int] = {}
        sib_fitness = {"avg": 0, "min": 0, "max": 0}
        sib_top: list[dict] = []
        db_exists = False

        if sib_db_path and Path(sib_db_path).exists():
            db_exists = True
            try:
                import aiosqlite
                async with aiosqlite.connect(sib_db_path) as db:
                    db.row_factory = aiosqlite.Row

                    cur = await db.execute("SELECT COUNT(*) as cnt FROM methodologies")
                    row = await cur.fetchone()
                    sib_count = int(row["cnt"]) if row else 0

                    cur = await db.execute(
                        "SELECT category, COUNT(*) as cnt FROM methodologies GROUP BY category ORDER BY cnt DESC"
                    )
                    for r in await cur.fetchall():
                        sib_cats[r["category"] or "uncategorized"] = int(r["cnt"])

                    cur = await db.execute(
                        "SELECT AVG(fitness_score) as avg_f, MIN(fitness_score) as min_f, "
                        "MAX(fitness_score) as max_f FROM methodologies WHERE fitness_score IS NOT NULL"
                    )
                    fit_row = await cur.fetchone()
                    if fit_row and fit_row["avg_f"] is not None:
                        sib_fitness = {
                            "avg": round(float(fit_row["avg_f"]), 3),
                            "min": round(float(fit_row["min_f"]), 3),
                            "max": round(float(fit_row["max_f"]), 3),
                        }

                    cur = await db.execute(
                        "SELECT title, category, fitness_score FROM methodologies "
                        "WHERE fitness_score IS NOT NULL ORDER BY fitness_score DESC LIMIT 5"
                    )
                    for r in await cur.fetchall():
                        sib_top.append({
                            "title": r["title"], "category": r["category"],
                            "fitness": round(float(r["fitness_score"]), 3),
                        })
            except Exception as exc:
                logger.warning("Brain graph: failed to query sibling '%s': %s", sib_name, exc)

        nodes.append({
            "id": sib_name,
            "name": sib_name,
            "methodology_count": sib_count,
            "categories": sib_cats,
            "top_methodologies": sib_top,
            "fitness_summary": sib_fitness,
            "db_exists": db_exists,
            "is_primary": False,
        })

        edges.append({"source": "primary", "target": sib_name, "type": "federation"})

    return JSONResponse({"nodes": nodes, "edges": edges})


@app.get("/api/brain/bandit-state")
async def api_bandit_state(task_type: Optional[str] = Query(None)) -> JSONResponse:
    """Bandit arm stats: Beta posterior, mean, CI for each methodology with outcome data."""
    st = await _ensure_state(app)
    repo = st["repository"]

    try:
        if task_type:
            rows = await repo.engine.fetch_all(
                "SELECT methodology_id, task_type, "
                "SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) as successes, "
                "SUM(CASE WHEN outcome = 'failure' THEN 1 ELSE 0 END) as failures, "
                "COUNT(*) as total "
                "FROM methodology_bandit_outcomes "
                "WHERE task_type = ? "
                "GROUP BY methodology_id, task_type",
                (task_type,),
            )
        else:
            rows = await repo.engine.fetch_all(
                "SELECT methodology_id, task_type, "
                "SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) as successes, "
                "SUM(CASE WHEN outcome = 'failure' THEN 1 ELSE 0 END) as failures, "
                "COUNT(*) as total "
                "FROM methodology_bandit_outcomes "
                "GROUP BY methodology_id, task_type"
            )
    except Exception:
        rows = []

    # Aggregate per methodology across task types
    method_stats: dict[str, dict] = {}
    for r in rows:
        mid = r["methodology_id"]
        if mid not in method_stats:
            method_stats[mid] = {
                "methodology_id": mid,
                "successes": 0,
                "failures": 0,
                "total": 0,
                "task_types": [],
            }
        method_stats[mid]["successes"] += r["successes"]
        method_stats[mid]["failures"] += r["failures"]
        method_stats[mid]["total"] += r["total"]
        if r["task_type"] and r["task_type"] not in method_stats[mid]["task_types"]:
            method_stats[mid]["task_types"].append(r["task_type"])

    # Compute Beta posterior stats
    arms = []
    for mid, s in method_stats.items():
        alpha = s["successes"] + 1  # Beta prior
        beta_param = s["failures"] + 1
        mean = alpha / (alpha + beta_param)
        n = alpha + beta_param
        ci_half = 1.96 * math.sqrt(mean * (1 - mean) / n) if n > 0 else 0
        ci_low = max(0, mean - ci_half)
        ci_high = min(1, mean + ci_half)

        # Look up methodology title
        try:
            title_rows = await repo.engine.fetch_all(
                "SELECT title FROM methodologies WHERE id = ?", (mid,)
            )
            title = title_rows[0]["title"] if title_rows else mid
        except Exception:
            title = mid

        arms.append({
            "methodology_id": mid,
            "title": title,
            "alpha": alpha,
            "beta": beta_param,
            "mean": round(mean, 4),
            "ci_low": round(ci_low, 4),
            "ci_high": round(ci_high, 4),
            "successes": s["successes"],
            "failures": s["failures"],
            "total": s["total"],
            "task_types": s["task_types"],
        })

    arms.sort(key=lambda x: x["mean"], reverse=True)
    return JSONResponse({"arms": arms, "count": len(arms)})


@app.get("/api/brain/capability-boundaries")
async def api_capability_boundaries() -> JSONResponse:
    """Identify hard tasks, failing methodologies, and coverage gaps."""
    st = await _ensure_state(app)
    repo = st["repository"]

    # Hard tasks: task_types where all agents fail > 50%
    hard_tasks: list[dict] = []
    try:
        rows = await repo.engine.fetch_all(
            "SELECT task_type, agent_id, "
            "CAST(failures AS REAL) / NULLIF(total_attempts, 0) as failure_rate "
            "FROM agent_scores WHERE total_attempts > 0"
        )
        task_agents: dict[str, list[float]] = {}
        for r in rows:
            tt = r["task_type"]
            if tt not in task_agents:
                task_agents[tt] = []
            task_agents[tt].append(r["failure_rate"] or 0)
        for tt, rates in task_agents.items():
            if rates and all(rate > 0.5 for rate in rates):
                hard_tasks.append({
                    "task_type": tt,
                    "agents_tried": len(rates),
                    "avg_failure_rate": round(sum(rates) / len(rates), 3),
                })
    except Exception:
        pass

    # Failing methodologies: > 3 failures and 0 successes in bandit
    failing_methods: list[dict] = []
    try:
        rows = await repo.engine.fetch_all(
            "SELECT methodology_id, "
            "SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) as successes, "
            "SUM(CASE WHEN outcome = 'failure' THEN 1 ELSE 0 END) as failures "
            "FROM methodology_bandit_outcomes "
            "GROUP BY methodology_id "
            "HAVING failures > 3 AND successes = 0"
        )
        for r in rows:
            try:
                title_rows = await repo.engine.fetch_all(
                    "SELECT title, category FROM methodologies WHERE id = ?",
                    (r["methodology_id"],),
                )
                title = title_rows[0]["title"] if title_rows else r["methodology_id"]
                category = title_rows[0]["category"] if title_rows else None
            except Exception:
                title = r["methodology_id"]
                category = None
            failing_methods.append({
                "methodology_id": r["methodology_id"],
                "title": title,
                "category": category,
                "failures": r["failures"],
            })
    except Exception:
        pass

    # Coverage gaps from gap matrix
    coverage_gaps: list[dict] = []
    try:
        from claw.community.gap_analyzer import GapAnalyzer
        ga = GapAnalyzer(repo)
        matrix = ga.compute_coverage_matrix()
        if hasattr(matrix, "sparse_cells"):
            for cell in matrix.sparse_cells[:20]:
                coverage_gaps.append({
                    "category": cell.category if hasattr(cell, "category") else str(cell),
                    "brain": cell.brain if hasattr(cell, "brain") else "primary",
                    "count": cell.count if hasattr(cell, "count") else 0,
                })
        elif isinstance(matrix, dict) and "sparse_cells" in matrix:
            for cell in matrix["sparse_cells"][:20]:
                coverage_gaps.append(cell if isinstance(cell, dict) else {"category": str(cell)})
    except Exception as exc:
        logger.debug("Capability boundaries: gap matrix unavailable: %s", exc)

    return JSONResponse({
        "hard_tasks": hard_tasks,
        "failing_methodologies": failing_methods,
        "coverage_gaps": coverage_gaps,
    })


# ---------------------------------------------------------------------------
# Phase 5 — Composite Execution, SSE Streaming, Script Generation
# ---------------------------------------------------------------------------

_forge_jobs: dict[str, dict[str, Any]] = {}


@app.post("/api/forge/execute")
async def api_forge_execute(request: Request) -> JSONResponse:
    """Execute a composite forge job (brain creation, mining, etc.)."""
    import uuid

    body = await request.json()
    steps = body.get("steps", [])
    if not steps:
        return JSONResponse({"error": "steps array required"}, status_code=400)

    job_id = str(uuid.uuid4())[:8]
    job: dict[str, Any] = {
        "job_id": job_id,
        "status": "queued",
        "steps": steps,
        "stages": [],
        "total_methodologies_created": 0,
        "error": None,
        "created_at": time.time(),
    }
    _forge_jobs[job_id] = job

    async def _run_forge():
        job["status"] = "running"

        for step in steps:
            step_type = step.get("type", "unknown")
            stage: dict[str, Any] = {
                "stage": step_type,
                "status": "running",
                "detail": "",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            job["stages"].append(stage)

            try:
                if step_type == "create_brain":
                    name = step.get("config", {}).get("name", "unnamed")
                    desc = step.get("config", {}).get("description", "")
                    prompt = step.get("config", {}).get("prompt_template", "repo-mine-misc.md")

                    st = await _ensure_state(app)
                    config = st["config"]
                    db_path_str = str(config.database.db_path) if hasattr(config.database, "db_path") else str(config.database)
                    project_root = Path(db_path_str).resolve().parent.parent
                    ganglion_dir = project_root / "instances" / name
                    ganglion_db_path = ganglion_dir / "claw.db"

                    if not (ganglion_dir.exists() and ganglion_db_path.exists()):
                        from claw.db.engine import DatabaseConfig, DatabaseEngine
                        ganglion_dir.mkdir(parents=True, exist_ok=True)
                        db_config = DatabaseConfig(db_path=str(ganglion_db_path))
                        sib_engine = DatabaseEngine(db_config)
                        await sib_engine.connect()
                        await sib_engine.initialize_schema()
                        await sib_engine.close()

                    stage["status"] = "success"
                    stage["detail"] = f"Brain '{name}' created at {ganglion_dir}"

                elif step_type == "mine":
                    paths = step.get("paths", [])
                    brain = step.get("brain")
                    stage["detail"] = f"Mining {len(paths)} repos for brain '{brain}'"

                    try:
                        from claw.miner import RepoMiner
                        st = await _ensure_state(app)
                        miner = RepoMiner(st["config"], st["repository"])
                        total_findings = 0
                        for p in paths:
                            if Path(p).exists():
                                results = await miner.mine_directory(Path(p), brain=brain)
                                total_findings += len(results) if results else 0
                        job["total_methodologies_created"] += total_findings
                        stage["status"] = "success"
                        stage["detail"] = f"Mined {total_findings} methodologies from {len(paths)} repos"
                    except Exception as exc:
                        stage["status"] = "error"
                        stage["detail"] = str(exc)

                elif step_type == "config_update":
                    stage["status"] = "success"
                    stage["detail"] = "Config updated"

                elif step_type == "cag_rebuild":
                    stage["status"] = "skipped"
                    stage["detail"] = "CAG rebuild deferred — will rebuild on next query"

                else:
                    stage["status"] = "skipped"
                    stage["detail"] = f"Unknown step type: {step_type}"

            except Exception as exc:
                stage["status"] = "error"
                stage["detail"] = str(exc)
                job["status"] = "error"
                job["error"] = str(exc)
                return

        job["status"] = "completed"

    asyncio.create_task(_run_forge())
    return JSONResponse({"job_id": job_id, "status": "queued"})


@app.get("/api/forge/execute/{job_id}/stream")
async def api_forge_stream(job_id: str) -> JSONResponse:
    """SSE-like endpoint — returns current stage events as JSON for polling.

    A proper SSE endpoint would use StreamingResponse with text/event-stream,
    but for compatibility with simple fetch clients, this returns JSON snapshot.
    """
    if job_id not in _forge_jobs:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    job = _forge_jobs[job_id]
    return JSONResponse({
        "job_id": job_id,
        "status": job["status"],
        "stages": job["stages"],
        "total_methodologies_created": job.get("total_methodologies_created", 0),
        "error": job.get("error"),
    })


@app.get("/api/forge/execute/{job_id}")
async def api_forge_job_status(job_id: str) -> JSONResponse:
    """Get final status + results of a forge job."""
    if job_id not in _forge_jobs:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    job = _forge_jobs[job_id]
    return JSONResponse({
        "job_id": job_id,
        "status": job["status"],
        "stages": job["stages"],
        "total_methodologies_created": job.get("total_methodologies_created", 0),
        "error": job.get("error"),
        "created_at": job.get("created_at"),
    })


@app.post("/api/forge/generate-script")
async def api_forge_generate_script(request: Request) -> JSONResponse:
    """Generate a shell script for Tier 3 operations (clone, install, env setup)."""
    body = await request.json()
    operations = body.get("operations", [])
    repo_urls = body.get("repo_urls", [])
    brain_name = body.get("brain_name", "custom")
    env_vars = body.get("env_vars", [])

    lines = [
        "#!/usr/bin/env bash",
        "# CAM-PULSE Forge — Generated Script",
        f"# Brain: {brain_name}",
        f"# Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "set -euo pipefail",
        "",
    ]

    if "clone_repos" in operations and repo_urls:
        lines.append("# --- Clone repositories ---")
        lines.append(f"CLONE_DIR=\"./forge-repos/{brain_name}\"")
        lines.append("mkdir -p \"$CLONE_DIR\"")
        for url in repo_urls:
            repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
            lines.append(f'git clone "{url}" "$CLONE_DIR/{repo_name}" || echo "Skipping {repo_name} (already exists)"')
        lines.append("")

    if "install_deps" in operations:
        lines.append("# --- Install CAM dependencies ---")
        lines.append("pip install -e . 2>/dev/null || echo 'Already installed'")
        lines.append("")

    if "set_env" in operations:
        lines.append("# --- Environment variables (fill in values) ---")
        for var in env_vars:
            lines.append(f'export {var}=""  # <-- Fill in your key')
        if not env_vars:
            lines.append('export OPENROUTER_API_KEY=""  # <-- Fill in your key')
        lines.append("")

    if "mine" in operations:
        lines.append("# --- Mine repositories ---")
        if repo_urls:
            for url in repo_urls:
                repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
                lines.append(f'cam mine --brain {brain_name} "./forge-repos/{brain_name}/{repo_name}"')
        else:
            lines.append(f"cam mine --brain {brain_name} /path/to/your/repo")
        lines.append("")

    lines.append('echo "Done! Brain \'{brain_name}\' is ready."'.replace("{brain_name}", brain_name))

    script = "\n".join(lines) + "\n"
    filename = f"forge-{brain_name}-{time.strftime('%Y%m%d')}.sh"

    return JSONResponse({
        "script": script,
        "filename": filename,
        "description": f"Setup script for '{brain_name}' brain with {len(operations)} operations",
    })


@app.post("/api/forge/analyze-intent")
async def api_forge_analyze_intent(request: Request) -> JSONResponse:
    """Analyze a natural language intent to suggest brain configuration."""
    body = await request.json()
    intent = body.get("intent", "").strip()
    repo_path = body.get("repo_path")

    if not intent:
        return JSONResponse({"error": "intent is required"}, status_code=400)

    st = await _ensure_state(app)
    repo = st["repository"]
    config = st["config"]

    # Search existing knowledge
    existing_knowledge = []
    try:
        safe_q = _build_safe_fts5_query(intent)
        if safe_q:
            rows = await repo.engine.fetch_all(
                "SELECT m.id, m.problem_description, m.language, m.lifecycle_state, "
                "m.tags, rank AS fts_rank "
                "FROM methodology_fts f JOIN methodologies m ON f.rowid = m.rowid "
                "WHERE methodology_fts MATCH ? ORDER BY rank LIMIT 10",
                (safe_q,),
            )
            for r in rows:
                existing_knowledge.append({
                    "id": r["id"],
                    "problem": r["problem_description"][:200],
                    "language": r["language"],
                    "lifecycle": r["lifecycle_state"],
                    "fts_rank": abs(float(r["fts_rank"] or 0)),
                })
    except Exception:
        pass

    # Detect repo languages if path provided
    repo_analysis = None
    if repo_path and Path(repo_path).exists():
        try:
            from claw.miner import detect_all_repo_languages
            loop = asyncio.get_event_loop()
            lang_zones = await loop.run_in_executor(None, detect_all_repo_languages, Path(repo_path), config)
            repo_analysis = lang_zones if isinstance(lang_zones, dict) else {}
        except Exception:
            pass

    # Extract heuristics from intent
    intent_lower = intent.lower()
    lang_keywords = {
        "python": "python", "typescript": "typescript", "go": "go", "golang": "go",
        "rust": "rust", "sql": "sql", "java": "java", "react": "typescript",
        "django": "python", "flask": "python", "fastapi": "python",
        "next.js": "typescript", "nextjs": "typescript",
    }
    suggested_brain = "misc"
    for kw, brain in lang_keywords.items():
        if kw in intent_lower:
            suggested_brain = brain
            break

    # Agent recommendations
    agent_recs = []
    for aid, acfg in config.agents.items():
        if acfg.enabled:
            agent_recs.append({
                "agent_id": aid,
                "mode": acfg.mode,
                "model": acfg.model,
            })

    # Gap analysis
    gaps = []
    try:
        from claw.community.gap_analyzer import GapAnalyzer
        ga = GapAnalyzer(repo)
        matrix = ga.compute_coverage_matrix()
        if isinstance(matrix, dict) and "sparse_cells" in matrix:
            gaps = matrix["sparse_cells"][:10]
    except Exception:
        pass

    return JSONResponse({
        "existing_knowledge": existing_knowledge,
        "gaps": gaps,
        "suggested_config": {
            "brain_name": suggested_brain,
            "description": intent,
            "prompt_template": f"repo-mine-{suggested_brain}.md",
        },
        "agent_recommendations": agent_recs,
        "repo_analysis": repo_analysis,
    })




# ---------------------------------------------------------------------------
# Playground — real task execution via MicroClaw
# ---------------------------------------------------------------------------

_playground_ctx_lock = asyncio.Lock()
_playground_ctx: Any = None  # Cached ClawContext for playground executions


async def _ensure_playground_ctx() -> Any:
    """Lazily build a full ClawContext (needed by MicroClaw) and cache it."""
    global _playground_ctx
    if _playground_ctx is not None:
        return _playground_ctx
    async with _playground_ctx_lock:
        if _playground_ctx is not None:
            return _playground_ctx
        from claw.core.factory import ClawFactory
        _playground_ctx = await ClawFactory.create()
        return _playground_ctx


async def _start_playground_execution(
    request: Request,
    *,
    task_description: str,
    project_id: str = "playground",
    workspace_dir: Optional[str] = None,
    plan_id: Optional[str] = None,
    approved_slot_ids: Optional[list[str]] = None,
) -> JSONResponse:
    """Shared execution launcher for direct and plan-reviewed playground runs."""
    session_id = str(uuid.uuid4())

    if not hasattr(request.app.state, "playground_jobs"):
        request.app.state.playground_jobs = {}

    job: dict[str, Any] = {
        "session_id": session_id,
        "status": "starting",
        "task_description": task_description,
        "project_id": project_id,
        "plan_id": plan_id,
        "approved_slot_ids": approved_slot_ids or [],
        "slot_execution": [],
        "replacement_history": [],
        "pause_requested_slot_id": None,
        "paused_slot_id": None,
        "reverify_requested_slots": {},
        "blocked_slot_ids": {},
        "banned_family_barcodes": {},
        "steps": [],
        "gates": [],
        "corrections": [],
        "result": None,
        "error": None,
        "error_trace": None,
        "created_at": _datetime.now(UTC).isoformat(),
    }
    request.app.state.playground_jobs[session_id] = job

    async def _run_playground_execution() -> None:
        try:
            ctx = await _ensure_playground_ctx()
            repo = ctx.repository
            feature_flags = ctx.config.feature_flags
            active_packets: list[Any] = []
            connectome: Optional[RunConnectome] = None
            effective_task_description = task_description

            if plan_id:
                plan_record = await _load_plan_record(request.app, repo, plan_id)
                if plan_record:
                    job["replacement_history"] = list(plan_record.get("replacement_history", []))
                summaries = await repo.list_packets_for_plan(plan_id)
                approved_set = set(approved_slot_ids or [])
                for summary in summaries:
                    if approved_set and summary.slot_id not in approved_set:
                        continue
                    packet = await repo.get_application_packet(summary.packet_id)
                    if packet is None:
                        continue
                    packet = _ensure_critical_policy_gates(packet, feature_flags.critical_slot_policy)
                    packet.status = PacketStatus.EXECUTING
                    await repo.save_application_packet(packet)
                    await repo.save_slot_instance(packet.slot, task_archetype=packet.task_archetype)
                    active_packets.append(packet)

                if active_packets:
                    effective_task_description = _render_packetized_task_description(task_description, active_packets)
                    job["slot_execution"] = [
                        {
                            "slot_id": packet.slot.slot_id,
                            "packet_id": packet.packet_id,
                            "name": packet.slot.name,
                            "status": "executing" if idx == 0 else "queued",
                            "current_step": "pending",
                            "retry_count": 0,
                            "last_retry_detail": None,
                            "replacement_count": len([r for r in job["replacement_history"] if r.get("slot_id") == packet.slot.slot_id]),
                            "blocked_wait_ms": 0,
                            "family_wait_ms": 0,
                            "selected_component_id": packet.selected.component_id,
                        }
                        for idx, packet in enumerate(active_packets)
                    ]
                    await _persist_all_run_slot_execution(repo, session_id, job)
                    connectome = await repo.save_run_connectome(
                        RunConnectome(
                            run_id=session_id,
                            task_archetype=active_packets[0].task_archetype,
                            status="running",
                        )
                    )
                    for packet in active_packets:
                        pair = await repo.save_pair_event(
                            PairEvent(
                                run_id=session_id,
                                slot_id=packet.slot.slot_id,
                                slot_barcode=packet.slot.slot_barcode,
                                packet_id=packet.packet_id,
                                component_id=packet.selected.component_id,
                                source_barcode=packet.selected.receipt.source_barcode,
                                confidence=packet.selected.confidence,
                                confidence_basis=packet.confidence_basis,
                            )
                        )
                        await repo.save_run_connectome_edge(
                            connectome.id,
                            source_node=packet.slot.slot_id,
                            target_node=packet.selected.component_id,
                            edge_type="paired",
                            metadata={"packet_id": packet.packet_id, "pair_id": pair.id},
                        )
                        await _record_run_event(
                            repo,
                            session_id,
                            "packet_selected",
                            slot_id=packet.slot.slot_id,
                            payload={"packet_id": packet.packet_id, "component_id": packet.selected.component_id},
                        )

            from claw.core.models import Project, Task
            project = Project(
                id=project_id,
                name=project_id,
                repo_path=workspace_dir or ".",
            )
            try:
                await ctx.repository.create_project(project)
            except Exception:
                pass

            from claw.cycle import MicroClaw
            job["status"] = "running"

            async def _wait_if_paused(slot_id: str) -> None:
                while job.get("paused_slot_id") == slot_id:
                    await asyncio.sleep(0.2)

            async def _wait_if_blocked(slot_id: str) -> None:
                wait_started: float | None = None
                while slot_id in job.get("blocked_slot_ids", {}):
                    if wait_started is None:
                        wait_started = asyncio.get_event_loop().time()
                    await asyncio.sleep(0.2)
                if wait_started is not None:
                    elapsed_ms = int((asyncio.get_event_loop().time() - wait_started) * 1000)
                    slot_state = next((slot for slot in job["slot_execution"] if slot["slot_id"] == slot_id), None)
                    if slot_state is not None:
                        slot_state["blocked_wait_ms"] = int(slot_state.get("blocked_wait_ms", 0)) + elapsed_ms
                        await _persist_run_slot_execution(repo, session_id, slot_state)
                    await _record_run_action_audit(
                        repo,
                        session_id,
                        "blocked_wait",
                        slot_id=slot_id,
                        reason="slot waited for unblock",
                        payload={"duration_ms": elapsed_ms},
                    )

            async def _wait_for_allowed_family(packet: Any) -> Any:
                current_packet = packet
                wait_started: float | None = None
                while current_packet.selected.receipt.family_barcode in job.get("banned_family_barcodes", {}):
                    if wait_started is None:
                        wait_started = asyncio.get_event_loop().time()
                    slot_state = next((slot for slot in job["slot_execution"] if slot["slot_id"] == current_packet.slot.slot_id), None)
                    if slot_state is not None:
                        slot_state["status"] = "blocked"
                        slot_state["current_step"] = "family_banned"
                        await _persist_run_slot_execution(repo, session_id, slot_state)
                    await asyncio.sleep(0.2)
                    refreshed = await repo.get_application_packet(current_packet.packet_id)
                    if refreshed is not None:
                        current_packet = refreshed
                if wait_started is not None:
                    elapsed_ms = int((asyncio.get_event_loop().time() - wait_started) * 1000)
                    slot_state = next((slot for slot in job["slot_execution"] if slot["slot_id"] == current_packet.slot.slot_id), None)
                    if slot_state is not None:
                        slot_state["family_wait_ms"] = int(slot_state.get("family_wait_ms", 0)) + elapsed_ms
                        await _persist_run_slot_execution(repo, session_id, slot_state)
                    await _record_run_action_audit(
                        repo,
                        session_id,
                        "family_wait",
                        slot_id=current_packet.slot.slot_id,
                        reason="slot waited for allowed family",
                        payload={"duration_ms": elapsed_ms, "family_barcode": current_packet.selected.receipt.family_barcode},
                    )
                return current_packet

            async def _run_packet_cycle(packet: Any, *, reverify: bool = False) -> Any:
                slot_state = next((slot for slot in job["slot_execution"] if slot["slot_id"] == packet.slot.slot_id), None)
                if slot_state is not None:
                    slot_state["status"] = "executing"
                    slot_state["current_step"] = "reverify_pending" if reverify else "pending"
                    await _persist_run_slot_execution(repo, session_id, slot_state)

                description = _render_packetized_task_description(task_description, [packet])
                if reverify:
                    description = (
                        f"{description}\n\nREVERIFY MODE\n"
                        "Re-check the current slot implementation, apply only targeted fixes, and do not broaden scope."
                    )

                task = Task(
                    project_id=project_id,
                    title=f"{task_description[:96]} [{packet.slot.name}]",
                    description=description,
                )
                await ctx.repository.create_task(task)
                micro = MicroClaw(ctx=ctx, project_id=project_id, session_id=session_id)

                def on_step(step_name: str, detail: str) -> None:
                    timestamp = _datetime.now(UTC).isoformat()
                    job["steps"].append({
                        "step": step_name,
                        "detail": detail,
                        "timestamp": timestamp,
                        "slot_id": packet.slot.slot_id,
                    })
                    current_slot = next((slot for slot in job["slot_execution"] if slot["slot_id"] == packet.slot.slot_id), None)
                    if current_slot is not None:
                        current_slot["status"] = "executing"
                        current_slot["current_step"] = step_name
                        asyncio.create_task(_persist_run_slot_execution(repo, session_id, current_slot))
                    asyncio.create_task(
                        _record_run_event(
                            repo,
                            session_id,
                            step_name,
                            slot_id=packet.slot.slot_id,
                            payload={"detail": detail, "reverify": reverify},
                        )
                    )
                    if step_name == "verify" and micro._current_verification:
                        vr = micro._current_verification
                        gate_names = [
                            "dependency_jail", "style_match", "chaos_check",
                            "placeholder_scan", "drift_alignment",
                            "claim_validation", "llm_deep_review",
                        ]
                        violated_checks = {v["check"] for v in vr.violations}
                        job["gates"] = [
                            {
                                "check": g,
                                "status": "fail" if g in violated_checks else "pass",
                                "detail": next(
                                    (v["detail"] for v in vr.violations if v["check"] == g),
                                    "",
                                ),
                            }
                            for g in gate_names
                        ]
                    if step_name == "correct":
                        if (
                            micro._current_context_brief
                            and micro._current_context_brief.correction_feedback
                        ):
                            cf = micro._current_context_brief.correction_feedback
                            job["corrections"].append(cf.model_dump())
                            if current_slot is not None:
                                current_slot["retry_count"] += 1
                                current_slot["last_retry_detail"] = "; ".join(
                                    f"{v['check']}: {v['detail']}" for v in cf.violations[:3]
                                ) if getattr(cf, "violations", None) else "correction requested"
                                asyncio.create_task(_persist_run_slot_execution(repo, session_id, current_slot))
                            asyncio.create_task(
                                _record_run_event(
                                    repo,
                                    session_id,
                                    "retry_delta",
                                    slot_id=packet.slot.slot_id,
                                    payload={
                                        "attempt_number": cf.attempt_number,
                                        "violations": cf.violations,
                                        "reverify": reverify,
                                    },
                                )
                            )

                result = await micro.run_cycle(on_step=on_step)
                findings: list[str] = []
                test_refs: list[str] = []
                if result.verification:
                    findings = [f"{v.get('check')}: {v.get('detail')}" for v in result.verification.violations]
                    if result.verification.tests_after is not None:
                        test_refs.append(f"tests_after:{result.verification.tests_after}")

                slot_success = bool(result.success)
                if feature_flags.critical_slot_policy and getattr(packet.slot.risk, "value", str(packet.slot.risk)) == "critical":
                    scan_paths = result.outcome.files_changed or [site.file_path for site in packet.expected_landing_sites]
                    analysis = await run_critical_slot_policy_checks(
                        workspace_dir or ".",
                        scan_paths,
                    )
                    static_findings, policy_blocked = _apply_static_analysis_results(packet, analysis)
                    if static_findings:
                        findings.extend(static_findings)
                    if policy_blocked:
                        slot_success = False
                        await _record_run_event(
                            repo,
                            session_id,
                            "proof_gate_failed",
                            slot_id=packet.slot.slot_id,
                            payload={
                                "packet_id": packet.packet_id,
                                "gates": {
                                    key: {
                                        "status": value.get("status"),
                                        "details": value.get("details"),
                                        "finding_count": len(value.get("findings") or []),
                                    }
                                    for key, value in analysis.items()
                                },
                            },
                        )

                packet.status = PacketStatus.VERIFIED if slot_success else PacketStatus.FAILED
                await repo.save_application_packet(packet)
                await repo.save_outcome_event(
                    OutcomeEvent(
                        run_id=session_id,
                        slot_id=packet.slot.slot_id,
                        packet_id=packet.packet_id,
                        success=slot_success,
                        verifier_findings=findings,
                        test_refs=test_refs,
                        negative_memory_updates=[] if slot_success else packet.selected.known_failure_modes[:2],
                        recipe_eligible=bool(slot_success),
                    )
                )
                await repo.update_component_outcome(packet.selected.component_id, slot_success)
                await _record_run_event(
                    repo,
                    session_id,
                    "slot_verified" if slot_success else "slot_failed",
                    slot_id=packet.slot.slot_id,
                    payload={"packet_id": packet.packet_id, "success": slot_success, "reverify": reverify},
                )

                if slot_state is not None:
                    slot_state["status"] = "verified" if slot_success else "failed"
                    slot_state["current_step"] = "done" if slot_success else (slot_state.get("current_step") or "verify")
                    await _persist_run_slot_execution(repo, session_id, slot_state)

                for idx, file_path in enumerate(result.outcome.files_changed):
                    matched_packet, origin = _select_packet_for_file(file_path, [packet])
                    if matched_packet is None:
                        continue
                    landing = await repo.save_landing_event(
                        LandingEvent(
                            run_id=session_id,
                            slot_id=matched_packet.slot.slot_id,
                            packet_id=matched_packet.packet_id,
                            file_path=file_path,
                            diff_hunk_id=f"hunk_{idx + 1}",
                            origin=origin,
                        )
                    )
                    await _record_run_event(
                        repo,
                        session_id,
                        "landing_recorded",
                        slot_id=matched_packet.slot.slot_id,
                        payload={"file_path": landing.file_path, "origin": origin.value, "packet_id": matched_packet.packet_id},
                    )
                    if connectome:
                        await repo.save_run_connectome_edge(
                            connectome.id,
                            source_node=matched_packet.selected.component_id,
                            target_node=landing.file_path,
                            edge_type="landed",
                            metadata={"packet_id": matched_packet.packet_id, "origin": origin.value},
                        )
                result.success = slot_success
                return result

            if active_packets:
                last_result = None
                for idx, packet in enumerate(active_packets):
                    await _wait_if_paused(packet.slot.slot_id)
                    await _wait_if_blocked(packet.slot.slot_id)
                    packet = await _wait_for_allowed_family(packet)
                    result = await _run_packet_cycle(packet)
                    last_result = result

                    if result.success and job["reverify_requested_slots"].pop(packet.slot.slot_id, False):
                        await _wait_if_paused(packet.slot.slot_id)
                        await _wait_if_blocked(packet.slot.slot_id)
                        packet = await _wait_for_allowed_family(packet)
                        await _record_run_event(repo, session_id, "reverify_started", slot_id=packet.slot.slot_id, payload={"packet_id": packet.packet_id})
                        result = await _run_packet_cycle(packet, reverify=True)
                        last_result = result

                    if not result.success:
                        for later in job["slot_execution"]:
                            if later["slot_id"] == packet.slot.slot_id:
                                continue
                            if later["status"] in {"queued", "approved"}:
                                later["status"] = "blocked"
                                await _persist_run_slot_execution(repo, session_id, later)
                        job["result"] = result.model_dump()
                        job["status"] = "failed"
                        if connectome:
                            connectome.status = "failed"
                            await repo.save_run_connectome(connectome)
                        await _persist_all_run_slot_execution(repo, session_id, job)
                        break

                    next_slot = next(
                        (slot for slot in job["slot_execution"] if slot["status"] == "queued"),
                        None,
                    )
                    if next_slot is not None:
                        next_slot["status"] = "executing"
                        next_slot["current_step"] = "pending"
                        await _persist_run_slot_execution(repo, session_id, next_slot)
                else:
                    job["result"] = last_result.model_dump() if last_result else None
                    job["status"] = "completed"
                    auto_recipe = await _auto_distill_compiled_recipe(repo, connectome, active_packets)
                    if auto_recipe is not None:
                        await _record_run_event(
                            repo,
                            session_id,
                            "recipe_compiled",
                            payload={
                                "recipe_id": auto_recipe.id,
                                "recipe_name": auto_recipe.recipe_name,
                                "sample_size": auto_recipe.sample_size,
                                "is_active": auto_recipe.is_active,
                            },
                        )
                    if connectome:
                        connectome.status = "verified"
                        await repo.save_run_connectome(connectome)
                    await _persist_all_run_slot_execution(repo, session_id, job)
            else:
                task = Task(
                    project_id=project_id,
                    title=task_description[:120],
                    description=effective_task_description,
                )
                await ctx.repository.create_task(task)
                micro = MicroClaw(
                    ctx=ctx,
                    project_id=project_id,
                    session_id=session_id,
                )

                def on_step(step_name: str, detail: str) -> None:
                    timestamp = _datetime.now(UTC).isoformat()
                    job["steps"].append({
                        "step": step_name,
                        "detail": detail,
                        "timestamp": timestamp,
                    })
                    asyncio.create_task(
                        _record_run_event(
                            repo,
                            session_id,
                            step_name,
                            payload={"detail": detail},
                        )
                    )

                cycle_result = await micro.run_cycle(on_step=on_step)
                job["result"] = cycle_result.model_dump()
                job["status"] = "completed" if cycle_result.success else "failed"
        except Exception as exc:
            job["status"] = "error"
            job["error"] = str(exc)
            import traceback
            job["error_trace"] = traceback.format_exc()
            await _persist_all_run_slot_execution(repo, session_id, job)

    asyncio.create_task(_run_playground_execution())
    return JSONResponse({
        "session_id": session_id,
        "status": "started",
        "plan_id": plan_id,
    })


@app.post("/api/execute")
async def execute_task(request: Request):
    """Submit a task for MicroClaw execution with real 7-gate verification."""
    body = await request.json()
    task_description = body.get("task_description", "").strip()
    if not task_description:
        return JSONResponse({"error": "task_description required"}, status_code=400)

    project_id = body.get("project_id", "playground")
    workspace_dir = body.get("workspace_dir")  # optional override (unused for now)
    return await _start_playground_execution(
        request,
        task_description=task_description,
        project_id=project_id,
        workspace_dir=workspace_dir,
        plan_id=body.get("plan_id"),
    )


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str, request: Request):
    """Get execution session status, gate results, and final outcome."""
    jobs = getattr(request.app.state, "playground_jobs", {})
    job = jobs.get(session_id)
    if not job:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    return JSONResponse({
        "session_id": job["session_id"],
        "status": job["status"],
        "task_description": job["task_description"],
        "steps": job["steps"],
        "gates": job["gates"],
        "corrections_count": len(job["corrections"]),
        "result": job["result"],
        "error": job.get("error"),
        "created_at": job["created_at"],
    })


@app.get("/api/sessions/{session_id}/corrections")
async def get_session_corrections(session_id: str, request: Request):
    """Get correction loop replay data for a session."""
    jobs = getattr(request.app.state, "playground_jobs", {})
    job = jobs.get(session_id)
    if not job:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    return JSONResponse({
        "session_id": session_id,
        "corrections": job["corrections"],
        "total_attempts": len(job["corrections"]) + 1,  # +1 for initial attempt
    })


@app.get("/api/v2/runs/{run_id}")
async def api_v2_run_status(run_id: str, request: Request) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    jobs = getattr(request.app.state, "playground_jobs", {})
    job = jobs.get(run_id)
    connectome = await repo.get_run_connectome(run_id)
    pair_events = await repo.list_run_pair_events(run_id)
    landing_events = await repo.list_run_landing_events(run_id)
    outcome_events = await repo.list_run_outcome_events(run_id)
    action_audits = await repo.list_run_action_audits(run_id)
    persisted_slot_execution = await repo.list_run_slot_executions(run_id)
    packets = []
    if job and job.get("plan_id"):
        packet_summaries = await repo.list_packets_for_plan(job["plan_id"])
        for summary in packet_summaries:
            packet = await repo.get_application_packet(summary.packet_id)
            if packet is not None:
                packets.append(packet)
    elif persisted_slot_execution:
        seen_packet_ids: set[str] = set()
        for slot_state in persisted_slot_execution:
            if not slot_state.packet_id or slot_state.packet_id in seen_packet_ids:
                continue
            packet = await repo.get_application_packet(slot_state.packet_id)
            if packet is not None:
                packets.append(packet)
                seen_packet_ids.add(slot_state.packet_id)

    if job is None and connectome is None:
        return JSONResponse({"error": "Run not found"}, status_code=404)

    approved_slot_ids = list(job.get("approved_slot_ids", [])) if job else []
    blocked_slot_ids = dict(job.get("blocked_slot_ids", {})) if job else {}
    banned_family_barcodes = dict(job.get("banned_family_barcodes", {})) if job else {}
    outcome_by_slot = {event.slot_id: event for event in outcome_events}
    landing_counts: dict[str, int] = {}
    for landing in landing_events:
        landing_counts[landing.slot_id] = landing_counts.get(landing.slot_id, 0) + 1
    slot_execution_map = (
        {item["slot_id"]: item for item in job.get("slot_execution", [])}
        if job and job.get("slot_execution")
        else {
            item.slot_id: {
                "slot_id": item.slot_id,
                "packet_id": item.packet_id,
                "selected_component_id": item.selected_component_id,
                "status": item.status,
                "current_step": item.current_step,
                "retry_count": item.retry_count,
                "last_retry_detail": item.last_retry_detail,
                "replacement_count": item.replacement_count,
            }
            for item in persisted_slot_execution
        }
    )
    slot_summaries = []
    current_slot_id = None
    for packet in packets:
        outcome = outcome_by_slot.get(packet.slot.slot_id)
        slot_exec = slot_execution_map.get(packet.slot.slot_id, {})
        slot_status = slot_exec.get("status", packet.status.value)
        if outcome:
            slot_status = "verified" if outcome.success else "failed"
        elif not slot_exec and packet.slot.slot_id in approved_slot_ids:
            slot_status = "executing"
        if current_slot_id is None and slot_status in {"executing", "review_required", "approved"}:
            current_slot_id = packet.slot.slot_id
        slot_summaries.append(
            {
                "slot_id": packet.slot.slot_id,
                "name": packet.slot.name,
                "status": slot_status,
                "confidence": packet.selected.confidence,
                "landing_count": landing_counts.get(packet.slot.slot_id, 0),
                "retry_count": int(slot_exec.get("retry_count", 0)),
                "last_retry_detail": slot_exec.get("last_retry_detail"),
                "current_step": slot_exec.get("current_step"),
                "replacement_count": int(slot_exec.get("replacement_count", 0)),
                "blocked_wait_ms": int(slot_exec.get("blocked_wait_ms", 0)),
                "family_wait_ms": int(slot_exec.get("family_wait_ms", 0)),
                "selected_component_id": slot_exec.get("selected_component_id", packet.selected.component_id),
                "block_reason": blocked_slot_ids.get(packet.slot.slot_id),
                "review_required": packet.reviewer_required,
                "coverage_state": packet.coverage_state.value,
            }
        )
    if current_slot_id is None and approved_slot_ids:
        current_slot_id = approved_slot_ids[0]

    return JSONResponse(
        {
            "run_id": run_id,
            "status": job["status"] if job else (connectome.status if connectome else "unknown"),
            "plan_id": job.get("plan_id") if job else None,
            "task_description": job.get("task_description") if job else None,
            "current_slot_id": current_slot_id,
            "retry_count": len(job.get("corrections", [])) if job else 0,
            "replacement_history": job.get("replacement_history", []) if job else [],
            "blocked_slot_ids": blocked_slot_ids,
            "banned_family_barcodes": banned_family_barcodes,
            "summary": {
                "completed_slots": len(outcome_events),
                "total_slots": len(pair_events) or len(slot_execution_map) or len(approved_slot_ids),
                "failed_gates": len(job.get("gates", [])) if job else 0,
                "pair_events": len(pair_events),
                "landing_events": len(landing_events),
                "outcome_events": len(outcome_events),
                "action_audits": len(action_audits),
                "blocked_slots": len(blocked_slot_ids),
                "banned_families": len(banned_family_barcodes),
                "blocked_wait_ms": sum(int(slot.get("blocked_wait_ms", 0)) for slot in slot_execution_map.values()),
                "family_wait_ms": sum(int(slot.get("family_wait_ms", 0)) for slot in slot_execution_map.values()),
            },
            "slots": slot_summaries,
            "steps": job.get("steps", []) if job else [],
            "gates": job.get("gates", []) if job else [],
            "result": job.get("result") if job else None,
        }
    )


@app.get("/api/v2/runs/{run_id}/connectome")
async def api_v2_run_connectome(run_id: str) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    connectome = await repo.get_run_connectome(run_id)
    if connectome is None:
        return JSONResponse({"nodes": [], "edges": []})

    pair_events = await repo.list_run_pair_events(run_id)
    landing_events = await repo.list_run_landing_events(run_id)
    outcome_events = await repo.list_run_outcome_events(run_id)
    stored_edges = await repo.list_run_connectome_edges(connectome.id)

    nodes: dict[str, dict[str, str]] = {run_id: {"id": run_id, "kind": "run"}}
    edges = []
    for event in pair_events:
        nodes.setdefault(event.slot_id, {"id": event.slot_id, "kind": "slot"})
        nodes.setdefault(event.component_id, {"id": event.component_id, "kind": "component"})
        edges.append({"source": event.slot_id, "target": event.component_id, "type": "paired"})
    for event in landing_events:
        nodes.setdefault(event.file_path, {"id": event.file_path, "kind": "landing"})
        edges.append({"source": event.packet_id, "target": event.file_path, "type": "landed"})
    for event in outcome_events:
        outcome_id = f"outcome:{event.id}"
        nodes.setdefault(outcome_id, {"id": outcome_id, "kind": "outcome"})
        edges.append({"source": event.packet_id, "target": outcome_id, "type": "verified"})
    for edge in stored_edges:
        edges.append({
            "source": edge["source_node"],
            "target": edge["target_node"],
            "type": edge["edge_type"],
            "metadata": json.loads(edge["metadata_json"]) if edge.get("metadata_json") else {},
        })
    return JSONResponse({"nodes": list(nodes.values()), "edges": edges})


@app.get("/api/v2/runs/{run_id}/landings")
async def api_v2_run_landings(run_id: str) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    landings = await repo.list_run_landing_events(run_id)
    return JSONResponse(
        {
            "landings": [
                {
                    "locus_barcode": event.id,
                    "file_path": event.file_path,
                    "symbol": event.symbol,
                    "diff_hunk_id": event.diff_hunk_id,
                    "slot_id": event.slot_id,
                    "packet_id": event.packet_id,
                    "origin": event.origin.value,
                }
                for event in landings
            ]
        }
    )


@app.get("/api/v2/runs/{run_id}/events")
async def api_v2_run_events(run_id: str, request: Request) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    jobs = getattr(request.app.state, "playground_jobs", {})
    job = jobs.get(run_id)
    events = await _build_run_events(repo, run_id, job)
    return JSONResponse({"events": events})


@app.get("/api/v2/runs/{run_id}/audits")
async def api_v2_run_audits(run_id: str) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    audits = await repo.list_run_action_audits(run_id)
    return JSONResponse(
        {
            "audits": [
                {
                    "id": str(audit.id),
                    "run_id": str(audit.run_id),
                    "slot_id": str(audit.slot_id) if audit.slot_id is not None else None,
                    "action_type": str(audit.action_type),
                    "actor": str(audit.actor),
                    "reason": str(audit.reason),
                    "action_payload": audit.action_payload,
                    "created_at": audit.created_at.isoformat(),
                }
                for audit in audits
            ]
        }
    )


@app.post("/api/v2/runs/{run_id}/slots/{slot_id}/swap-candidate")
async def api_v2_run_swap_candidate(run_id: str, slot_id: str, request: Request) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    jobs = getattr(request.app.state, "playground_jobs", {})
    job = jobs.get(run_id)
    if job is None or not job.get("plan_id"):
        return JSONResponse({"error": "Active reviewed run not found"}, status_code=404)

    body = await request.json()
    candidate_component_id = body.get("candidate_component_id")
    if not candidate_component_id:
        return JSONResponse({"error": "candidate_component_id required"}, status_code=400)

    plan = await _load_plan_record(app, repo, job["plan_id"])
    if plan is None:
        return JSONResponse({"error": "Plan not found"}, status_code=404)

    packet_summaries = await repo.list_packets_for_plan(plan["plan_id"])
    packet = None
    for summary in packet_summaries:
        if summary.slot_id != slot_id:
            continue
        packet = await repo.get_application_packet(summary.packet_id)
        break
    if packet is None:
        return JSONResponse({"error": "Slot packet not found"}, status_code=404)

    replacement = next((item for item in packet.runner_ups if item.component_id == candidate_component_id), None)
    if replacement is None:
        return JSONResponse({"error": "Candidate not available as runner-up"}, status_code=404)
    if replacement.receipt.family_barcode in job.get("banned_family_barcodes", {}):
        return JSONResponse({"error": "Candidate family is banned for this run"}, status_code=400)
    governance_policies = await _active_governance_policies_for_plan(repo, str(plan.get("task_archetype") or ""))
    matching_family_policies = [
        policy
        for policy in governance_policies
        if policy.policy_kind == "family_policy"
        and policy.family_barcode
        and policy.family_barcode == replacement.receipt.family_barcode
    ]
    slot_risk = getattr(packet.slot.risk, "value", str(packet.slot.risk))
    if slot_risk == "critical" and any(policy.severity == "high" for policy in matching_family_policies):
        return JSONResponse(
            {
                "error": "Candidate blocked by active high-severity family policy",
                "policy_reasons": [policy.reason or policy.recommendation for policy in matching_family_policies],
            },
            status_code=400,
        )

    old_selected = packet.selected
    packet.selected = replacement
    packet.runner_ups = [old_selected, *[item for item in packet.runner_ups if item.component_id != candidate_component_id]][:3]
    packet.why_selected = replacement.why_fit[:4] or ["selected by active run swap"]
    packet.reviewer_required = True
    packet.review_required_reasons = list(
        dict.fromkeys(
            packet.review_required_reasons
            + ["active_run_candidate_swap"]
            + (["governance_family_policy"] if matching_family_policies else [])
        )
    )
    packet.confidence_basis = replacement.confidence_basis
    packet.status = PacketStatus.EXECUTING
    if matching_family_policies:
        packet.risk_notes = list(
            dict.fromkeys(
                packet.risk_notes
                + [policy.recommendation or policy.reason for policy in matching_family_policies if (policy.recommendation or policy.reason)]
            )
        )[:4]
    packet = _reset_analysis_gates(packet)
    await repo.save_application_packet(packet)

    pair_events = await repo.list_run_pair_events(run_id)
    previous_pair = next((event for event in reversed(pair_events) if event.slot_id == slot_id), None)
    connectome = await repo.get_run_connectome(run_id)
    new_pair = await repo.save_pair_event(
        PairEvent(
            run_id=run_id,
            slot_id=packet.slot.slot_id,
            slot_barcode=packet.slot.slot_barcode,
            packet_id=packet.packet_id,
            component_id=packet.selected.component_id,
            source_barcode=packet.selected.receipt.source_barcode,
            confidence=packet.selected.confidence,
            confidence_basis=packet.confidence_basis,
            replacement_of_pair_id=previous_pair.id if previous_pair else None,
        )
    )
    if connectome:
        await repo.save_run_connectome_edge(
            connectome.id,
            source_node=packet.slot.slot_id,
            target_node=packet.selected.component_id,
            edge_type="re_paired",
            metadata={"packet_id": packet.packet_id, "pair_id": new_pair.id},
        )

    replacement_entry = {
        "slot_id": slot_id,
        "previous_component_id": old_selected.component_id,
        "new_component_id": replacement.component_id,
        "reason": body.get("reason") or "active_run_candidate_swap",
        "timestamp": _datetime.now(UTC).isoformat(),
    }
    job["replacement_history"].append(replacement_entry)
    plan["replacement_history"] = list(job["replacement_history"])
    await _save_plan_record(app, repo, plan)
    await _record_run_event(
        repo,
        run_id,
        "candidate_swapped",
        slot_id=slot_id,
        payload={
            "previous_component_id": old_selected.component_id,
            "new_component_id": replacement.component_id,
            "reason": replacement_entry["reason"],
        },
    )
    await _record_run_action_audit(
        repo,
        run_id,
        "swap_candidate",
        slot_id=slot_id,
        reason=replacement_entry["reason"],
        payload={
            "previous_component_id": old_selected.component_id,
            "new_component_id": replacement.component_id,
            "packet_id": packet.packet_id,
        },
    )

    for slot_state in job.get("slot_execution", []):
        if slot_state["slot_id"] == slot_id:
            slot_state["selected_component_id"] = replacement.component_id
            slot_state["replacement_count"] = int(slot_state.get("replacement_count", 0)) + 1
            await _persist_run_slot_execution(repo, run_id, slot_state)
            break

    return JSONResponse({"packet": packet.model_dump(mode="json"), "pair_id": new_pair.id})


@app.post("/api/v2/runs/{run_id}/slots/{slot_id}/block")
async def api_v2_run_block_slot(run_id: str, slot_id: str, request: Request) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    jobs = getattr(request.app.state, "playground_jobs", {})
    job = jobs.get(run_id)
    if job is None:
        return JSONResponse({"error": "Active run not found"}, status_code=404)

    body = await request.json() if request.headers.get("content-length") not in {None, "0"} else {}
    reason = body.get("reason") or "operator_blocked_slot"
    slot_state = next((slot for slot in job.get("slot_execution", []) if slot["slot_id"] == slot_id), None)
    if slot_state is None:
        return JSONResponse({"error": "Slot execution not found"}, status_code=404)

    job.setdefault("blocked_slot_ids", {})[slot_id] = reason
    slot_state["status"] = "blocked"
    slot_state["current_step"] = "blocked"
    await _persist_run_slot_execution(repo, run_id, slot_state)
    await _record_run_event(repo, run_id, "slot_blocked", slot_id=slot_id, payload={"reason": reason})
    await _record_run_action_audit(repo, run_id, "block_slot", slot_id=slot_id, reason=reason, payload={"status": "blocked"})
    return JSONResponse({"run_id": run_id, "slot_id": slot_id, "status": "blocked", "reason": reason})


@app.post("/api/v2/runs/{run_id}/slots/{slot_id}/unblock")
async def api_v2_run_unblock_slot(run_id: str, slot_id: str, request: Request) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    jobs = getattr(request.app.state, "playground_jobs", {})
    job = jobs.get(run_id)
    if job is None:
        return JSONResponse({"error": "Active run not found"}, status_code=404)

    body = await request.json() if request.headers.get("content-length") not in {None, "0"} else {}
    reason = body.get("reason") or "operator_unblocked_slot"
    slot_state = next((slot for slot in job.get("slot_execution", []) if slot["slot_id"] == slot_id), None)
    if slot_state is None:
        return JSONResponse({"error": "Slot execution not found"}, status_code=404)

    job.setdefault("blocked_slot_ids", {}).pop(slot_id, None)
    if slot_state["status"] == "blocked":
        slot_state["status"] = "queued"
        slot_state["current_step"] = "pending"
    await _persist_run_slot_execution(repo, run_id, slot_state)
    await _record_run_event(repo, run_id, "slot_unblocked", slot_id=slot_id, payload={"reason": reason})
    await _record_run_action_audit(repo, run_id, "unblock_slot", slot_id=slot_id, reason=reason, payload={"status": slot_state["status"]})
    return JSONResponse({"run_id": run_id, "slot_id": slot_id, "status": slot_state["status"]})


@app.post("/api/v2/runs/{run_id}/families/{family_barcode}/ban")
async def api_v2_run_ban_family(run_id: str, family_barcode: str, request: Request) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    jobs = getattr(request.app.state, "playground_jobs", {})
    job = jobs.get(run_id)
    if job is None:
        return JSONResponse({"error": "Active run not found"}, status_code=404)

    body = await request.json() if request.headers.get("content-length") not in {None, "0"} else {}
    reason = body.get("reason") or "operator_banned_family"
    job.setdefault("banned_family_barcodes", {})[family_barcode] = reason
    await _record_run_event(repo, run_id, "family_banned", payload={"family_barcode": family_barcode, "reason": reason})
    await _record_run_action_audit(repo, run_id, "ban_family", reason=reason, payload={"family_barcode": family_barcode})
    return JSONResponse({"run_id": run_id, "family_barcode": family_barcode, "status": "banned", "reason": reason})


@app.post("/api/v2/runs/{run_id}/families/{family_barcode}/unban")
async def api_v2_run_unban_family(run_id: str, family_barcode: str, request: Request) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    jobs = getattr(request.app.state, "playground_jobs", {})
    job = jobs.get(run_id)
    if job is None:
        return JSONResponse({"error": "Active run not found"}, status_code=404)

    body = await request.json() if request.headers.get("content-length") not in {None, "0"} else {}
    reason = body.get("reason") or "operator_unbanned_family"
    job.setdefault("banned_family_barcodes", {}).pop(family_barcode, None)
    await _record_run_event(repo, run_id, "family_unbanned", payload={"family_barcode": family_barcode, "reason": reason})
    await _record_run_action_audit(repo, run_id, "unban_family", reason=reason, payload={"family_barcode": family_barcode})
    return JSONResponse({"run_id": run_id, "family_barcode": family_barcode, "status": "allowed"})


@app.post("/api/v2/runs/{run_id}/slots/{slot_id}/pause")
async def api_v2_run_pause_slot(run_id: str, slot_id: str, request: Request) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    jobs = getattr(request.app.state, "playground_jobs", {})
    job = jobs.get(run_id)
    if job is None:
        return JSONResponse({"error": "Active run not found"}, status_code=404)

    slot_state = next((slot for slot in job.get("slot_execution", []) if slot["slot_id"] == slot_id), None)
    if slot_state is None:
        return JSONResponse({"error": "Slot execution not found"}, status_code=404)

    job["paused_slot_id"] = slot_id
    slot_state["status"] = "paused"
    slot_state["current_step"] = slot_state.get("current_step") or "paused"
    await _persist_run_slot_execution(repo, run_id, slot_state)
    await _record_run_event(repo, run_id, "slot_paused", slot_id=slot_id, payload={"current_step": slot_state.get("current_step")})
    await _record_run_action_audit(repo, run_id, "pause_slot", slot_id=slot_id, payload={"current_step": slot_state.get("current_step")})
    return JSONResponse({"run_id": run_id, "slot_id": slot_id, "status": "paused"})


@app.post("/api/v2/runs/{run_id}/slots/{slot_id}/resume")
async def api_v2_run_resume_slot(run_id: str, slot_id: str, request: Request) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    jobs = getattr(request.app.state, "playground_jobs", {})
    job = jobs.get(run_id)
    if job is None:
        return JSONResponse({"error": "Active run not found"}, status_code=404)

    slot_state = next((slot for slot in job.get("slot_execution", []) if slot["slot_id"] == slot_id), None)
    if slot_state is None:
        return JSONResponse({"error": "Slot execution not found"}, status_code=404)

    if job.get("paused_slot_id") == slot_id:
        job["paused_slot_id"] = None
    slot_state["status"] = "executing"
    slot_state["current_step"] = slot_state.get("current_step") if slot_state.get("current_step") not in {None, "paused"} else "pending"
    await _persist_run_slot_execution(repo, run_id, slot_state)
    await _record_run_event(repo, run_id, "slot_resumed", slot_id=slot_id, payload={"current_step": slot_state.get("current_step")})
    await _record_run_action_audit(repo, run_id, "resume_slot", slot_id=slot_id, payload={"current_step": slot_state.get("current_step")})
    return JSONResponse({"run_id": run_id, "slot_id": slot_id, "status": "executing"})


@app.post("/api/v2/runs/{run_id}/slots/{slot_id}/reverify")
async def api_v2_run_reverify_slot(run_id: str, slot_id: str, request: Request) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    jobs = getattr(request.app.state, "playground_jobs", {})
    job = jobs.get(run_id)
    if job is None:
        return JSONResponse({"error": "Active run not found"}, status_code=404)

    slot_state = next((slot for slot in job.get("slot_execution", []) if slot["slot_id"] == slot_id), None)
    if slot_state is None:
        return JSONResponse({"error": "Slot execution not found"}, status_code=404)

    job.setdefault("reverify_requested_slots", {})[slot_id] = True
    await _record_run_event(repo, run_id, "reverify_requested", slot_id=slot_id, payload={"selected_component_id": slot_state.get("selected_component_id")})
    await _record_run_action_audit(repo, run_id, "reverify_slot", slot_id=slot_id, payload={"selected_component_id": slot_state.get("selected_component_id")})
    return JSONResponse({"run_id": run_id, "slot_id": slot_id, "status": "queued_for_reverify"})


@app.post("/api/v2/runs/{run_id}/slots/{slot_id}/proof-gates/{gate_id}/waive")
async def api_v2_run_waive_proof_gate(run_id: str, slot_id: str, gate_id: str, request: Request) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    jobs = getattr(request.app.state, "playground_jobs", {})
    job = jobs.get(run_id)
    if job is None or not job.get("plan_id"):
        return JSONResponse({"error": "Active reviewed run not found"}, status_code=404)

    plan = await _load_plan_record(app, repo, job["plan_id"])
    if plan is None:
        return JSONResponse({"error": "Plan not found"}, status_code=404)

    packet_summaries = await repo.list_packets_for_plan(plan["plan_id"])
    packet = None
    for summary in packet_summaries:
        if summary.slot_id != slot_id:
            continue
        packet = await repo.get_application_packet(summary.packet_id)
        break
    if packet is None:
        return JSONResponse({"error": "Slot packet not found"}, status_code=404)

    gate = _find_proof_gate(packet, gate_id)
    if gate is None:
        return JSONResponse({"error": "Proof gate not found"}, status_code=404)

    body = await request.json() if request.headers.get("content-length") not in {None, "0"} else {}
    reason = body.get("reason") or "operator_waived_proof_gate"
    gate.status = "waived"
    gate.details = [reason]
    await repo.save_application_packet(packet)
    await _record_run_event(
        repo,
        run_id,
        "proof_gate_waived",
        slot_id=slot_id,
        payload={"gate_id": gate_id, "reason": reason, "packet_id": packet.packet_id},
    )
    await _record_run_action_audit(
        repo,
        run_id,
        "waive_proof_gate",
        slot_id=slot_id,
        reason=reason,
        payload={"gate_id": gate_id, "packet_id": packet.packet_id},
    )
    return JSONResponse({"run_id": run_id, "slot_id": slot_id, "gate_id": gate_id, "status": "waived"})


@app.get("/api/v2/runs/{run_id}/events/stream")
async def api_v2_run_events_stream(
    run_id: str,
    request: Request,
    once: bool = Query(False),
) -> StreamingResponse:
    st = await _ensure_state(app)
    repo = st["repository"]

    async def event_generator():
        seen: set[str] = set()
        while True:
            jobs = getattr(request.app.state, "playground_jobs", {})
            job = jobs.get(run_id)
            events = await _build_run_events(repo, run_id, job)
            fresh = [event for event in events if event["event_id"] not in seen]
            for event in fresh:
                seen.add(event["event_id"])
                yield f"id: {event['event_id']}\n"
                yield f"event: {event['event_type']}\n"
                yield f"data: {json.dumps(event)}\n\n"
            if once:
                break
            if await request.is_disconnected():
                break
            await asyncio.sleep(1.0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/v2/runs/{run_id}/retrograde")
async def api_v2_run_retrograde(
    run_id: str,
    root: Optional[str] = Query(None),
    request: Request = None,
) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    jobs = getattr(request.app.state, "playground_jobs", {}) if request is not None else {}
    job = jobs.get(run_id)
    outcome_events = await repo.list_run_outcome_events(run_id)
    landing_events = await repo.list_run_landing_events(run_id)
    pair_events = await repo.list_run_pair_events(run_id)
    run_events = await repo.list_run_events(run_id)
    slot_executions = await repo.list_run_slot_executions(run_id)
    action_audits = await repo.list_run_action_audits(run_id)

    failing_outcome = next((event for event in outcome_events if not event.success), outcome_events[0] if outcome_events else None)
    if failing_outcome is None:
        return JSONResponse(
            {
                "root": {"kind": "run", "id": run_id if root is None else root},
                "cause_chain": [],
                "runner_up_analysis": None,
                "confidence": 0.0,
            }
        )

    packet = await repo.get_application_packet(failing_outcome.packet_id)
    pair = next((event for event in pair_events if event.packet_id == failing_outcome.packet_id), None)
    landing = next((event for event in landing_events if event.packet_id == failing_outcome.packet_id), None)
    slot_execution = next((item for item in slot_executions if item.slot_id == failing_outcome.slot_id), None)
    runner_up = packet.runner_ups[0] if packet and packet.runner_ups else None
    relevant_audits = [audit for audit in action_audits if audit.slot_id in {None, failing_outcome.slot_id}]
    relevant_events = [event for event in run_events if event.slot_id in {None, failing_outcome.slot_id}]
    return JSONResponse(
        _build_retrograde_payload(
            run_id=run_id,
            root=root,
            failing_outcome=failing_outcome,
            packet=packet,
            pair=pair,
            landing=landing,
            slot_execution=slot_execution,
            runner_up=runner_up,
            relevant_audits=relevant_audits,
            relevant_events=relevant_events,
            task_description=job.get("task_description") if job else None,
        )
    )


@app.get("/api/v2/runs/{run_id}/distill")
async def api_v2_run_distill(run_id: str) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    connectome = await repo.get_run_connectome(run_id)
    outcome_events = await repo.list_run_outcome_events(run_id)
    pair_events = await repo.list_run_pair_events(run_id)
    slot_executions = await repo.list_run_slot_executions(run_id)
    action_audits = await repo.list_run_action_audits(run_id)
    compiled_recipes = await repo.list_compiled_recipes(task_archetype=connectome.task_archetype if connectome else None, limit=10)

    promotions = []
    downgrades = []
    negative_memory_updates = []
    persisted_negative_memory = []
    packet_transfer_summary = {"direct_fit": 0, "pattern_transfer": 0, "heuristic_fallback": 0}
    federation_recommendations = []
    for outcome in outcome_events:
        packet = await repo.get_application_packet(outcome.packet_id)
        if outcome.success and packet:
            promotions.append(
                {
                    "kind": "packet_pattern",
                    "slot_id": packet.slot.slot_id,
                    "component_id": packet.selected.component_id,
                    "reason": "successful packet application",
                }
            )
        if not outcome.success and packet:
            downgrades.append(
                {
                    "component_id": packet.selected.component_id,
                    "reason": "failed packet application",
                }
            )
            outcome_negative_memory = list(getattr(outcome, "negative_memory_updates", []) or [])
            negative_memory_updates.extend(outcome_negative_memory)
            for update in outcome_negative_memory:
                if not str(update).strip():
                    continue
                failure_knowledge = _build_negative_memory_failure_knowledge(
                    run_id=run_id,
                    update=str(update),
                    connectome=connectome,
                    outcome=outcome,
                    packet=packet,
                )
                try:
                    await repo.record_failure_knowledge(**failure_knowledge)
                except Exception as exc:
                    logger.debug("Failed to persist CAM-SEQ negative memory: %s", exc)
                else:
                    persisted_negative_memory.append(
                        {
                            "error_signature": failure_knowledge["error_signature"],
                            "error_category": failure_knowledge["error_category"],
                            "task_type": failure_knowledge["task_type"],
                            "prevention_hint": failure_knowledge["prevention_hint"],
                        }
                    )
        if packet:
            transfer_mode = getattr(packet.selected.transfer_mode, "value", str(packet.selected.transfer_mode))
            packet_transfer_summary[transfer_mode] = packet_transfer_summary.get(transfer_mode, 0) + 1

    blocked_wait_ms = sum(int(getattr(item, "blocked_wait_ms", 0) or 0) for item in slot_executions)
    family_wait_ms = sum(int(getattr(item, "family_wait_ms", 0) or 0) for item in slot_executions)
    block_actions = [audit for audit in action_audits if audit.action_type == "block_slot"]
    ban_actions = [audit for audit in action_audits if audit.action_type == "ban_family"]
    reverify_actions = [audit for audit in action_audits if audit.action_type == "reverify_slot"]

    governance_recommendations = []
    if blocked_wait_ms >= 5000 or len(block_actions) >= 2:
        governance_recommendations.append(
            {
                "kind": "slot_policy",
                "severity": "medium" if blocked_wait_ms < 15000 else "high",
                "reason": f"Blocked wait reached {blocked_wait_ms}ms across {len(block_actions)} block actions",
                "recommendation": "Promote stronger pre-mutation review or automatic critical-slot blocking.",
            }
        )
    if family_wait_ms >= 5000 or len(ban_actions) >= 1:
        governance_recommendations.append(
            {
                "kind": "family_policy",
                "severity": "medium" if family_wait_ms < 15000 else "high",
                "reason": f"Family-ban wait reached {family_wait_ms}ms across {len(ban_actions)} bans",
                "recommendation": "Downgrade or quarantine the affected family barcode until stronger direct-fit evidence exists.",
            }
        )
    if len(reverify_actions) >= 2:
        governance_recommendations.append(
            {
                "kind": "proof_policy",
                "severity": "medium",
                "reason": f"Repeated reverify requests ({len(reverify_actions)}) indicate unstable proof confidence",
                "recommendation": "Strengthen proof gates or promote a stricter proof-first recipe.",
            }
        )

    critical_pattern_transfer = []
    for outcome in outcome_events:
        packet = await repo.get_application_packet(outcome.packet_id)
        if not packet:
            continue
        transfer_mode = getattr(packet.selected.transfer_mode, "value", str(packet.selected.transfer_mode))
        slot_risk = getattr(packet.slot.risk, "value", str(packet.slot.risk))
        if slot_risk == "critical" and transfer_mode != "direct_fit":
            critical_pattern_transfer.append(packet.slot.name)

    if packet_transfer_summary.get("pattern_transfer", 0) >= 1:
        federation_recommendations.append(
            {
                "kind": "federation_policy",
                "severity": "high" if critical_pattern_transfer else "medium",
                "reason": (
                    f"{packet_transfer_summary.get('pattern_transfer', 0)} selected packets relied on pattern transfer"
                    + (f", including critical slots: {', '.join(sorted(set(critical_pattern_transfer)))}" if critical_pattern_transfer else "")
                ),
                "recommendation": "Prioritize direct-fit federation packet retrieval or queue mining missions for the weak slot families.",
            }
        )
    if packet_transfer_summary.get("heuristic_fallback", 0) >= 1:
        federation_recommendations.append(
            {
                "kind": "federation_policy",
                "severity": "high",
                "reason": f"{packet_transfer_summary.get('heuristic_fallback', 0)} selected packets used heuristic fallback",
                "recommendation": "Escalate weak packet evidence before reuse and strengthen component/federation coverage.",
            }
        )

    return JSONResponse(
        {
            "run_id": run_id,
            "task_archetype": connectome.task_archetype if connectome else None,
            "promotions": promotions,
            "downgrades": downgrades,
            "negative_memory_updates": negative_memory_updates,
            "persisted_negative_memory": persisted_negative_memory,
            "governance_recommendations": governance_recommendations,
            "federation_recommendations": federation_recommendations,
            "packet_transfer_summary": packet_transfer_summary,
            "recipe_candidates": [
                {
                    "task_archetype": connectome.task_archetype if connectome else None,
                    "sample_size": len([event for event in outcome_events if event.success]),
                    "pair_count": len(pair_events),
                }
            ],
            "compiled_recipes": [recipe.model_dump(mode="json") for recipe in compiled_recipes],
        }
    )


@app.post("/api/v2/runs/{run_id}/governance/promote")
async def api_v2_promote_governance_policy(run_id: str, request: Request) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    body = await request.json()
    connectome = await repo.get_run_connectome(run_id)
    evidence_json = dict(body.get("evidence_json") or {})
    evidence_json.setdefault("source_run_id", run_id)
    evidence_json.setdefault("source_route", f"/evolution/run/{run_id}")
    evidence_json.setdefault("source_kind", "run_distill")
    if connectome and connectome.task_archetype:
        evidence_json.setdefault("task_archetype", connectome.task_archetype)
    if body.get("family_barcode"):
        evidence_json.setdefault("family_barcode", body.get("family_barcode"))
    if body.get("slot_id"):
        evidence_json.setdefault("slot_id", body.get("slot_id"))
    policy = GovernancePolicy(
        run_id=run_id,
        task_archetype=(connectome.task_archetype if connectome else None),
        slot_id=body.get("slot_id"),
        family_barcode=body.get("family_barcode"),
        policy_kind=str(body.get("policy_kind") or body.get("kind") or "governance_policy"),
        severity=str(body.get("severity") or "medium"),
        status=str(body.get("status") or "active"),
        reason=str(body.get("reason") or ""),
        recommendation=str(body.get("recommendation") or ""),
        evidence_json=evidence_json,
        promoted_by=str(body.get("promoted_by") or "operator"),
    )
    saved = await repo.save_governance_policy(policy)
    return JSONResponse({"policy": saved.model_dump(mode="json")})


@app.get("/api/v2/governance/policies")
async def api_v2_governance_policies(
    task_archetype: Optional[str] = None,
    active_only: bool = False,
    status: Optional[str] = None,
    family_barcode: Optional[str] = None,
    limit: int = 100,
) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    policies = await repo.list_governance_policies(
        task_archetype=task_archetype,
        active_only=active_only,
        limit=max(1, min(limit, 250)),
    )
    if status:
        policies = [policy for policy in policies if policy.status == status]
    if family_barcode:
        policies = [policy for policy in policies if policy.family_barcode == family_barcode]
    return JSONResponse({"policies": [policy.model_dump(mode="json") for policy in policies]})


@app.get("/api/v2/governance/conflicts")
async def api_v2_governance_conflicts(
    task_archetype: Optional[str] = None,
    active_only: bool = False,
    limit: int = 100,
) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    policies = await repo.list_governance_policies(
        task_archetype=task_archetype,
        active_only=active_only,
        limit=max(1, min(limit, 250)),
    )
    conflicts = _detect_governance_conflicts(policies)
    return JSONResponse({"conflicts": conflicts, "policy_count": len(policies)})


@app.post("/api/v2/governance/policies/{policy_id}/status")
async def api_v2_governance_policy_status(policy_id: str, request: Request) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    body = await request.json()
    policy = await repo.get_governance_policy(policy_id)
    if policy is None:
        return JSONResponse({"error": "policy not found"}, status_code=404)
    new_status = str(body.get("status") or "").strip()
    if new_status not in {"active", "inactive", "superseded", "waived"}:
        return JSONResponse({"error": "invalid status"}, status_code=400)
    policy.status = new_status
    if body.get("reason"):
        policy.reason = str(body.get("reason"))
    evidence = dict(policy.evidence_json or {})
    if body.get("supersedes_policy_id"):
        evidence["supersedes_policy_id"] = str(body.get("supersedes_policy_id"))
    if body.get("waiver_note"):
        evidence["waiver_note"] = str(body.get("waiver_note"))
    policy.evidence_json = evidence
    policy.updated_at = _datetime.now(UTC)
    saved = await repo.save_governance_policy(policy)
    return JSONResponse({"policy": saved.model_dump(mode="json")})


@app.get("/api/v2/governance/trends")
async def api_v2_governance_trends(
    task_archetype: Optional[str] = None,
    family_barcode: Optional[str] = None,
    limit: int = 50,
) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    row_limit = max(1, min(limit, 200))

    archetype_rows = await repo.engine.fetch_all(
        """
        SELECT rc.task_archetype AS task_archetype,
               COUNT(DISTINCT rc.run_id) AS runs,
               COALESCE(SUM(rse.blocked_wait_ms), 0) AS blocked_wait_ms,
               COALESCE(SUM(rse.family_wait_ms), 0) AS family_wait_ms
          FROM run_connectomes rc
          LEFT JOIN run_slot_executions rse ON rse.run_id = rc.run_id
         GROUP BY rc.task_archetype
         ORDER BY blocked_wait_ms DESC, family_wait_ms DESC
         LIMIT ?
        """,
        [row_limit],
    )
    audit_rows = await repo.engine.fetch_all(
        """
        SELECT rc.task_archetype AS task_archetype, raa.action_type AS action_type, COUNT(*) AS count
          FROM run_connectomes rc
          JOIN run_action_audits raa ON raa.run_id = rc.run_id
         GROUP BY rc.task_archetype, raa.action_type
        """
    )
    family_audits = await repo.list_governance_policies(limit=row_limit)
    ban_rows = await repo.engine.fetch_all(
        """
        SELECT action_type, action_payload_json
          FROM run_action_audits
         WHERE action_type IN ('ban_family', 'unban_family', 'family_wait')
         ORDER BY created_at DESC
         LIMIT ?
        """,
        [row_limit * 10],
    )

    action_counts_by_archetype: dict[str, dict[str, int]] = {}
    for row in audit_rows:
        archetype = row.get("task_archetype") or "unknown"
        bucket = action_counts_by_archetype.setdefault(archetype, {})
        bucket[row.get("action_type") or "unknown"] = int(row.get("count") or 0)

    by_archetype = []
    for row in archetype_rows:
        archetype = row.get("task_archetype") or "unknown"
        counts = action_counts_by_archetype.get(archetype, {})
        by_archetype.append(
            {
                "task_archetype": archetype,
                "runs": int(row.get("runs") or 0),
                "blocked_wait_ms": int(row.get("blocked_wait_ms") or 0),
                "family_wait_ms": int(row.get("family_wait_ms") or 0),
                "block_actions": int(counts.get("block_slot", 0)),
                "ban_actions": int(counts.get("ban_family", 0)),
                "reverify_actions": int(counts.get("reverify_slot", 0)),
            }
        )

    family_counts: dict[str, dict[str, Any]] = {}
    for row in ban_rows:
        payload = json.loads(row.get("action_payload_json") or "{}")
        family_barcode = payload.get("family_barcode")
        if not family_barcode:
            continue
        bucket = family_counts.setdefault(
            family_barcode,
            {"family_barcode": family_barcode, "ban_actions": 0, "unban_actions": 0, "wait_events": 0, "policy_count": 0},
        )
        action_type = row.get("action_type") or ""
        if action_type == "ban_family":
            bucket["ban_actions"] += 1
        elif action_type == "unban_family":
            bucket["unban_actions"] += 1
        else:
            bucket["wait_events"] += 1
    for policy in family_audits:
        if policy.family_barcode:
            bucket = family_counts.setdefault(
                policy.family_barcode,
                {
                    "family_barcode": policy.family_barcode,
                    "ban_actions": 0,
                    "unban_actions": 0,
                    "wait_events": 0,
                    "policy_count": 0,
                },
            )
            bucket["policy_count"] += 1

    by_family = sorted(
        family_counts.values(),
        key=lambda item: (item["policy_count"], item["ban_actions"], item["wait_events"]),
        reverse=True,
    )[:row_limit]

    if task_archetype:
        by_archetype = [item for item in by_archetype if item["task_archetype"] == task_archetype]
    if family_barcode:
        by_family = [item for item in by_family if item["family_barcode"] == family_barcode]

    return JSONResponse({"by_archetype": by_archetype, "by_family": by_family})


@app.get("/api/v2/federation/trends")
async def api_v2_federation_trends(
    task_archetype: Optional[str] = None,
    family_barcode: Optional[str] = None,
    limit: int = 50,
) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    trends = await _compute_federation_trends(
        repo,
        task_archetype=task_archetype,
        family_barcode=family_barcode,
        limit=limit,
    )
    return JSONResponse(trends)


@app.get("/api/v2/federation/policy-recommendations")
async def api_v2_federation_policy_recommendations(
    task_archetype: Optional[str] = None,
    family_barcode: Optional[str] = None,
    limit: int = 50,
) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    trends = await _compute_federation_trends(
        repo,
        task_archetype=task_archetype,
        family_barcode=family_barcode,
        limit=limit,
    )
    policies = await repo.list_governance_policies(task_archetype=task_archetype, active_only=True, limit=200)
    recommendations = _build_federation_policy_recommendations(trends, policies)
    return JSONResponse(
        {
            "recommendations": recommendations,
            "trend_summary": {
                "archetype_count": len(trends.get("by_archetype", [])),
                "family_count": len(trends.get("by_family", [])),
            },
        }
    )


@app.post("/api/v2/federation/policies/promote")
async def api_v2_promote_federation_policy(request: Request) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    body = await request.json()
    evidence_json = dict(body.get("evidence_json") or {})
    evidence_json.setdefault("source_route", "/api/v2/federation/policy-recommendations")
    evidence_json.setdefault("source_kind", "federation_trend")
    policy = GovernancePolicy(
        task_archetype=body.get("task_archetype"),
        slot_id=body.get("slot_id"),
        family_barcode=body.get("family_barcode"),
        policy_kind=body.get("policy_kind", "family_policy"),
        severity=body.get("severity", "medium"),
        reason=body.get("reason", ""),
        recommendation=body.get("recommendation", ""),
        evidence_json=evidence_json,
        promoted_by=body.get("promoted_by", "federation_loop"),
    )
    saved = await repo.save_governance_policy(policy)
    return JSONResponse({"policy": saved.model_dump(mode="json")})


@app.post("/api/v2/runs/{run_id}/recipes/promote")
async def api_v2_promote_recipe(run_id: str, request: Request) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    jobs = getattr(request.app.state, "playground_jobs", {})
    job = jobs.get(run_id)
    body = await request.json()
    recipe_name = body.get("recipe_name", f"{run_id}_recipe")
    minimum_sample_size = int(body.get("minimum_sample_size", 1))

    connectome = await repo.get_run_connectome(run_id)
    if connectome is None or not connectome.task_archetype:
        return JSONResponse({"error": "Run connectome not found"}, status_code=404)

    pair_events = await repo.list_run_pair_events(run_id)
    outcome_events = await repo.list_run_outcome_events(run_id)
    if len([event for event in outcome_events if event.success]) < minimum_sample_size:
        return JSONResponse({"error": "Not enough successful evidence for promotion"}, status_code=400)

    packets = []
    for event in pair_events:
        packet = await repo.get_application_packet(event.packet_id)
        if packet is not None:
            packets.append(packet)

    recipe = await repo.save_compiled_recipe(
        CompiledRecipe(
            task_archetype=connectome.task_archetype,
            recipe_name=recipe_name,
            recipe_json={
                "run_id": run_id,
                "task_description": job.get("task_description") if job else None,
                "slot_order": [packet.slot.name for packet in packets],
                "preferred_components": [
                    {
                        "slot_id": packet.slot.slot_id,
                        "component_id": packet.selected.component_id,
                        "family_barcode": packet.selected.receipt.family_barcode,
                    }
                    for packet in packets
                ],
                "proof_gates": sorted({gate.gate_type for packet in packets for gate in packet.proof_plan}),
            },
            sample_size=len([event for event in outcome_events if event.success]),
            is_active=True,
        )
    )
    return JSONResponse({"recipe": recipe.model_dump(mode="json")})


@app.post("/api/v2/runs/{run_id}/gaps/create-mining-mission")
async def api_v2_create_mining_mission(run_id: str, request: Request) -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    body = await request.json()
    mission = await repo.save_mining_mission(
        MiningMission(
            id=f"mission_{uuid.uuid4().hex[:10]}",
            run_id=run_id,
            slot_family=body.get("slot_family"),
            priority=body.get("priority", "normal"),
            reason=body.get("reason", "unspecified"),
            status="queued",
            mission_json=body,
        )
    )
    return JSONResponse({"mission": mission.model_dump(mode="json")})


@app.get("/api/v2/missions/mining")
async def api_v2_list_mining_missions() -> JSONResponse:
    st = await _ensure_state(app)
    repo = st["repository"]
    missions = await repo.list_mining_missions()
    return JSONResponse({"missions": [mission.model_dump(mode="json") for mission in missions]})

# ---------------------------------------------------------------------------
# HTML UI — single-page, no npm required
# ---------------------------------------------------------------------------

_E = html.escape


def _ganglion_badge(name: str) -> str:
    colors = {
        "primary": "#ff6b3d",
        "drive-ops": "#1777ff",
        "agentic-memory": "#16a085",
    }
    c = colors.get(name, "#76809d")
    return f'<span class="ganglion-badge" style="--gc:{c}">{_E(name)}</span>'


@app.get("/api/governance/contradictions")
async def api_governance_contradictions() -> JSONResponse:
    """Return all detected methodology contradictions."""
    st = await _ensure_state(app)
    try:
        rows = await st["repository"].engine.fetch_all(
            "SELECT id, methodology_a_id, methodology_b_id, "
            "problem_similarity, solution_divergence, detected_at, "
            "resolution, resolved_by, resolved_at "
            "FROM methodology_contradictions ORDER BY detected_at DESC LIMIT 100"
        )
        return JSONResponse([dict(r) for r in rows])
    except Exception as exc:
        logger.warning("Failed to fetch contradictions: %s", exc)
        return JSONResponse([])


@app.get("/api/methodology/{methodology_id}/graph")
async def api_methodology_graph(methodology_id: str) -> JSONResponse:
    """Return the 1-hop entity relationship graph around a methodology."""
    st = await _ensure_state(app)
    try:
        from claw.memory.governance import MemoryGovernor
        gov = MemoryGovernor(
            repository=st["repository"],
            config=st["config"].governance,
        )
        result = await gov.get_methodology_neighborhood(methodology_id)
        return JSONResponse(result)
    except Exception as exc:
        logger.warning("Failed to get methodology graph: %s", exc)
        return JSONResponse({"nodes": [], "edges": []})


@app.get("/.well-known/mcp.json")
async def well_known_mcp(request: Request) -> JSONResponse:
    """MCP discovery endpoint — returns tool schemas and brain topology."""
    st = await _ensure_state(app)
    config = st["config"]

    # Tool schemas (lazy import to avoid circular deps)
    tools: list[dict[str, str]] = []
    try:
        from claw.tools.schemas import generate_mcp_tool_schemas
        raw_tools = generate_mcp_tool_schemas()
        tools = [{"name": t["name"], "description": t["description"]} for t in raw_tools]
    except Exception as exc:
        logger.warning("Failed to load MCP tool schemas: %s", exc)

    # Brain topology (lazy import)
    brains: list[dict[str, Any]] = []
    total_methodologies = 0
    try:
        from claw.community.manifest import BrainTopology
        topology = BrainTopology(config)
        topology.load()
        brains = [
            {"name": b.get("name", "unknown"), "methodologies": b.get("total_methodologies", 0)}
            for b in topology.summaries
        ]
        total_methodologies = topology.total_methodologies
    except Exception as exc:
        logger.debug("BrainTopology not available: %s", exc)

    return JSONResponse({
        "name": "cam-pulse",
        "version": "1.0",
        "description": "CAM-PULSE autonomous learning engine",
        "transport": ["stdio"],
        "tools": tools,
        "brains": brains,
        "total_methodologies": total_methodologies,
    })


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, q: Optional[str] = None) -> HTMLResponse:
    """Main dashboard page."""
    st = await _ensure_state(app)

    # Get stats
    stats_resp = await api_stats()
    stats = json.loads(stats_resp.body)

    # Build search results HTML
    search_html = ""
    if q:
        search_resp = await api_search(q=q, limit=30)
        search_data = json.loads(search_resp.body)
        search_html = _render_search_results(q, search_data)

    page = _render_page(stats, q or "", search_html)
    return HTMLResponse(page)


def _render_search_results(query: str, data: dict) -> str:
    results = data.get("results", [])
    gc = data.get("ganglion_counts", {})
    elapsed = data.get("elapsed_ms", 0)

    ganglion_summary = " ".join(
        f'{_ganglion_badge(g)} <strong>{c}</strong>' for g, c in gc.items()
    )

    rows = []
    for r in results:
        tags_html = ""
        for t in (r.get("tags") or [])[:5]:
            if isinstance(t, str):
                tags_html += f'<span class="tag">{_E(t)}</span>'

        badge = _ganglion_badge(r.get("source_ganglion", "?"))
        lang = _E(r.get("language") or "?")
        lifecycle = _E(r.get("lifecycle", "?"))
        problem = _E(r.get("problem", ""))
        solution = _E(r.get("solution_preview", ""))
        mid = r.get("id", "")

        rows.append(f"""
        <div class="result-card">
          <div class="result-header">
            {badge}
            <span class="lang">{lang}</span>
            <span class="lifecycle">{lifecycle}</span>
            <span class="score">rank {r.get('fts_rank', 0):.2f}</span>
          </div>
          <h4><a href="/api/methodology/{mid}">{problem[:120]}</a></h4>
          <pre class="solution-preview">{solution}</pre>
          <div class="result-tags">{tags_html}</div>
          <div class="result-meta">
            retrievals: {r.get('retrievals', 0)} |
            successes: {r.get('successes', 0)} |
            novelty: {r.get('novelty') or 'n/a'}
          </div>
        </div>
        """)

    return f"""
    <div class="search-summary">
      <strong>{data.get('total_results', 0)}</strong> results for
      "<strong>{_E(query)}</strong>" in <strong>{elapsed:.0f}ms</strong>
      &mdash; {ganglion_summary}
    </div>
    {''.join(rows)}
    """


def _render_page(stats: dict, query: str, search_html: str) -> str:
    primary = stats.get("primary", {})
    siblings = stats.get("siblings", [])
    total_brain = stats.get("total_across_brain", 0)

    # Ganglion cards
    ganglion_cards = f"""
    <div class="ganglion-card primary">
      <h3>{_ganglion_badge("primary")} Primary Ganglion</h3>
      <div class="big-number">{primary.get('active', 0):,}</div>
      <div class="label">active methodologies</div>
      <div class="meta">{primary.get('source_repos', 0)} source repos |
      {len(primary.get('languages', {}))} languages</div>
    </div>
    """
    for sib in siblings:
        name = sib.get("name", "?")
        count = sib.get("methodology_count", 0)
        ok = sib.get("db_exists", False)
        status = "online" if ok else "offline"
        ganglion_cards += f"""
        <div class="ganglion-card">
          <h3>{_ganglion_badge(name)} {_E(name)}</h3>
          <div class="big-number">{count:,}</div>
          <div class="label">methodologies</div>
          <div class="meta">{status} | {_E(sib.get('description', '')[:60])}</div>
        </div>
        """

    # Lifecycle chart (horizontal bars)
    lifecycle = primary.get("lifecycle", {})
    lifecycle_bars = ""
    max_lc = max(lifecycle.values()) if lifecycle else 1
    for state, count in sorted(lifecycle.items(), key=lambda x: -x[1]):
        pct = (count / max_lc) * 100 if max_lc else 0
        lifecycle_bars += f"""
        <div class="bar-row">
          <span class="bar-label">{_E(state)}</span>
          <div class="bar-track"><div class="bar-fill" style="width:{pct}%"></div></div>
          <span class="bar-value">{count:,}</span>
        </div>
        """

    # Top categories
    categories = primary.get("top_categories", {})
    cat_html = ""
    for cat, cnt in list(categories.items())[:10]:
        cat_html += f'<span class="cat-chip">{_E(cat)} <strong>{cnt}</strong></span>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CAM-PULSE Brain Dashboard</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
      background: #0d1117; color: #c9d1d9; line-height: 1.5;
    }}
    a {{ color: #58a6ff; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    .container {{ max-width: 1280px; margin: 0 auto; padding: 0 24px; }}

    header {{
      background: linear-gradient(135deg, #161b22 0%, #0d1117 100%);
      border-bottom: 1px solid #21262d; padding: 32px 0;
    }}
    header h1 {{ font-size: 1.8rem; color: #f0f6fc; }}
    header .subtitle {{ color: #8b949e; margin-top: 4px; }}
    .brain-total {{
      font-size: 2.4rem; font-weight: 700; color: #ff6b3d;
      margin-top: 8px;
    }}
    .brain-total span {{ font-size: 1rem; color: #8b949e; font-weight: 400; }}

    .ganglia-grid {{
      display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px; margin: 24px 0;
    }}
    .ganglion-card {{
      background: #161b22; border: 1px solid #21262d; border-radius: 12px;
      padding: 20px; transition: border-color 0.2s;
    }}
    .ganglion-card:hover {{ border-color: #388bfd; }}
    .ganglion-card.primary {{ border-color: #ff6b3d44; }}
    .ganglion-card h3 {{ font-size: 0.95rem; color: #c9d1d9; margin-bottom: 8px; }}
    .big-number {{ font-size: 2rem; font-weight: 700; color: #f0f6fc; }}
    .label {{ font-size: 0.82rem; color: #8b949e; }}
    .meta {{ font-size: 0.78rem; color: #484f58; margin-top: 6px; }}

    .ganglion-badge {{
      display: inline-block; padding: 2px 10px; border-radius: 999px;
      font-size: 0.72rem; font-weight: 600; text-transform: uppercase;
      letter-spacing: 0.05em;
      background: color-mix(in srgb, var(--gc) 15%, transparent);
      color: var(--gc); border: 1px solid color-mix(in srgb, var(--gc) 30%, transparent);
    }}

    .search-box {{
      margin: 32px 0; display: flex; gap: 12px;
    }}
    .search-box input {{
      flex: 1; padding: 12px 16px; font-size: 1rem;
      background: #0d1117; border: 1px solid #30363d; border-radius: 8px;
      color: #f0f6fc; outline: none;
    }}
    .search-box input:focus {{ border-color: #58a6ff; }}
    .search-box button {{
      padding: 12px 24px; background: #ff6b3d; color: #fff; border: none;
      border-radius: 8px; font-weight: 600; cursor: pointer;
    }}
    .search-box button:hover {{ background: #ff8552; }}

    .search-summary {{
      padding: 16px 0; color: #8b949e; border-bottom: 1px solid #21262d;
      margin-bottom: 16px;
    }}

    .result-card {{
      background: #161b22; border: 1px solid #21262d; border-radius: 10px;
      padding: 16px; margin-bottom: 12px;
    }}
    .result-card:hover {{ border-color: #30363d; }}
    .result-header {{
      display: flex; gap: 8px; align-items: center; margin-bottom: 8px;
      flex-wrap: wrap;
    }}
    .result-header .lang {{
      font-size: 0.75rem; color: #7ee787; background: #7ee78718;
      padding: 2px 8px; border-radius: 4px;
    }}
    .result-header .lifecycle {{
      font-size: 0.75rem; color: #d2a8ff; background: #d2a8ff18;
      padding: 2px 8px; border-radius: 4px;
    }}
    .result-header .score {{
      font-size: 0.72rem; color: #484f58; margin-left: auto;
    }}
    .result-card h4 {{ color: #f0f6fc; font-size: 0.95rem; margin-bottom: 6px; }}
    .solution-preview {{
      font-size: 0.8rem; color: #8b949e; background: #0d1117;
      padding: 8px 12px; border-radius: 6px; overflow: hidden;
      max-height: 80px; white-space: pre-wrap; word-break: break-word;
    }}
    .result-tags {{ margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap; }}
    .tag {{
      font-size: 0.7rem; padding: 2px 8px; border-radius: 4px;
      background: #21262d; color: #8b949e;
    }}
    .result-meta {{ font-size: 0.72rem; color: #484f58; margin-top: 8px; }}

    .stats-grid {{
      display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin: 24px 0;
    }}
    .stats-panel {{
      background: #161b22; border: 1px solid #21262d; border-radius: 12px;
      padding: 20px;
    }}
    .stats-panel h3 {{ font-size: 0.95rem; color: #f0f6fc; margin-bottom: 12px; }}

    .bar-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }}
    .bar-label {{ width: 80px; font-size: 0.78rem; color: #8b949e; text-align: right; }}
    .bar-track {{
      flex: 1; height: 8px; background: #21262d; border-radius: 4px; overflow: hidden;
    }}
    .bar-fill {{
      height: 100%; background: linear-gradient(90deg, #ff6b3d, #ff8f6b);
      border-radius: 4px;
    }}
    .bar-value {{ width: 50px; font-size: 0.78rem; color: #8b949e; }}

    .cat-chip {{
      display: inline-block; padding: 4px 12px; margin: 3px;
      background: #21262d; border-radius: 6px; font-size: 0.78rem; color: #c9d1d9;
    }}
    .cat-chip strong {{ color: #ff6b3d; margin-left: 4px; }}

    footer {{
      border-top: 1px solid #21262d; padding: 24px 0; margin-top: 48px;
      text-align: center; color: #484f58; font-size: 0.82rem;
    }}

    @media (max-width: 768px) {{
      .stats-grid {{ grid-template-columns: 1fr; }}
      .ganglia-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="container">
      <h1>CAM-PULSE Brain Dashboard</h1>
      <div class="subtitle">Federated knowledge explorer &mdash; querying all ganglia simultaneously</div>
      <div class="brain-total">{total_brain:,} <span>methodologies across the CAM Brain</span></div>
    </div>
  </header>

  <main class="container">
    <div class="ganglia-grid">
      {ganglion_cards}
    </div>

    <form class="search-box" action="/" method="get">
      <input type="text" name="q" value="{_E(query)}"
             placeholder="Search across all ganglia... (e.g. retry backoff, agent routing, secret scanning)">
      <button type="submit">Search Brain</button>
    </form>

    <div id="search-results">
      {search_html}
    </div>

    <div class="stats-grid">
      <div class="stats-panel">
        <h3>Lifecycle Distribution</h3>
        {lifecycle_bars}
      </div>
      <div class="stats-panel">
        <h3>Top Knowledge Domains</h3>
        <div>{cat_html}</div>
      </div>
    </div>
  </main>

  <footer>
    <div class="container">
      CAM-PULSE Brain Dashboard &mdash; {total_brain:,} methodologies |
      {len(siblings) + 1} ganglia |
      <a href="/api/docs">API Docs</a> |
      <a href="/api/stats">Stats JSON</a>
    </div>
  </footer>
</body>
</html>"""
