"""MCP (Model Context Protocol) server exposing CLAW tools to agents mid-task.

Per clawpre.md section 8b, CLAW exposes itself as an MCP server so that any of the
four agents (Claude Code, Codex, Gemini, Grok) can, mid-task, query CLAW's memory,
store findings, verify claims, request specialist agents, or escalate to a human.

Original tools are exposed, plus CAM-SEQ packet/connectome tools:
    1. claw_query_memory    -- query semantic memory for similar past solutions
    2. claw_store_finding   -- store a new finding/methodology in memory
    3. claw_verify_claim    -- verify a claim about code (placeholder scan, validation)
    4. claw_request_specialist -- request a different agent for a subtask
    5. claw_escalate        -- escalate to human with context
    6. claw_decompose_task -- infer archetype and slot graph
    7. claw_build_application_packet -- construct a packet for one slot
    8. claw_get_run_connectome -- inspect stored run connectome
    9. claw_trace_failure -- inspect stored retrograde trace
    10. claw_promote_recipe -- persist a compiled recipe
    11. claw_queue_mining_mission -- persist a mining mission
    12. claw_request_specialist_packet -- request a structured specialist packet exchange
    13. claw_export_specialist_exchange -- export an external handoff envelope
    14. claw_import_specialist_exchange -- import external specialist replies
    15. claw_list_specialist_exchanges -- list external specialist exchanges
    16. claw_bridge_specialist_exchange -- send an exchange to an external MCP tool
    17. claw_submit_specialist_webhook -- send an exchange to a signed HTTPS webhook

Design:
    The ClawMCPServer class contains tool handler methods and schema definitions.
    The start_server() factory function attempts to load the ``mcp`` Python SDK
    and register tools on a proper MCP Server instance. If the SDK is unavailable,
    it logs a warning and returns None.

    All tool handlers are async and interact with real CLAW subsystems (Repository,
    SemanticMemory, Verifier, Dispatcher). No mocks, no placeholders, no cached
    responses.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from claw.community.specialist_exchange import (
    archive_reply,
    build_request_envelope,
    call_stdio_mcp_tool,
    candidate_reply_paths,
    deadline_from_seconds,
    load_reply_envelope,
    mcp_bridge_arguments,
    new_exchange_id,
    new_request_id,
    normalize_mcp_bridge_reply,
    specialist_exchange_spool_dir,
    submit_signed_http_exchange,
    validate_reply_envelope,
    write_inbox_reply,
    write_request_envelope,
)
from claw.core.models import CompiledRecipe, ExternalSpecialistExchange, MiningMission
from claw.db.repository import Repository
from claw.memory.component_ranker import rank_components_for_slot
from claw.planning.application_packet import build_application_packet
from claw.planning.taskome import decompose_task
from claw.verifier import PLACEHOLDER_PATTERNS

if TYPE_CHECKING:
    from claw.dispatcher import Dispatcher
    from claw.memory.semantic import SemanticMemory
    from claw.verifier import Verifier

logger = logging.getLogger("claw.mcp_server")


# ---------------------------------------------------------------------------
# Tool schemas — generated from Pydantic models in claw.tools.schemas
# ---------------------------------------------------------------------------

from claw.tools.schemas import generate_mcp_tool_schemas, validate_tool_input

TOOL_SCHEMAS: list[dict[str, Any]] = generate_mcp_tool_schemas()


# ---------------------------------------------------------------------------
# ClawMCPServer
# ---------------------------------------------------------------------------

class ClawMCPServer:
    """MCP server that exposes CLAW tools to agents.

    This class owns all tool handler methods and dispatches incoming tool
    calls by name. It is instantiated by the coordinator and either served
    through the ``mcp`` Python SDK or used directly in-process.

    Args:
        repository: Data access layer for CLAW's SQLite database.
        semantic_memory: Optional SemanticMemory for methodology persistence
            and hybrid search. If None, query/store operations fall back to
            Repository text search.
        verifier: Optional Verifier for claim validation. If None, claim
            verification uses only the built-in placeholder pattern scan.
        dispatcher: Optional Dispatcher for routing specialist requests.
            If None, specialist requests return a recommendation without
            actually dispatching.
    """

    def __init__(
        self,
        repository: Repository,
        semantic_memory: Optional[SemanticMemory] = None,
        verifier: Optional[Verifier] = None,
        dispatcher: Optional[Dispatcher] = None,
        federation: Optional[Any] = None,
        auth_token: Optional[str] = None,
        mcp_bridge_caller: Optional[Any] = None,
        http_webhook_sender: Optional[Any] = None,
    ):
        self.repository = repository
        self.semantic_memory = semantic_memory
        self.verifier = verifier
        self.dispatcher = dispatcher
        self.federation = federation
        self._auth_token = auth_token
        self.mcp_bridge_caller = mcp_bridge_caller
        self.http_webhook_sender = http_webhook_sender

        # Mapping of tool name -> handler coroutine
        self._handlers: dict[str, Any] = {
            "claw_query_memory": self.handle_query_memory,
            "claw_store_finding": self.handle_store_finding,
            "claw_verify_claim": self.handle_verify_claim,
            "claw_request_specialist": self.handle_request_specialist,
            "claw_escalate": self.handle_escalate,
            "claw_decompose_task": self.handle_decompose_task,
            "claw_build_application_packet": self.handle_build_application_packet,
            "claw_get_run_connectome": self.handle_get_run_connectome,
            "claw_trace_failure": self.handle_trace_failure,
            "claw_promote_recipe": self.handle_promote_recipe,
            "claw_queue_mining_mission": self.handle_queue_mining_mission,
            "claw_request_specialist_packet": self.handle_request_specialist_packet,
            "claw_export_specialist_exchange": self.handle_export_specialist_exchange,
            "claw_import_specialist_exchange": self.handle_import_specialist_exchange,
            "claw_list_specialist_exchanges": self.handle_list_specialist_exchanges,
            "claw_bridge_specialist_exchange": self.handle_bridge_specialist_exchange,
            "claw_submit_specialist_webhook": self.handle_submit_specialist_webhook,
        }

        logger.info(
            "ClawMCPServer initialized: semantic_memory=%s, verifier=%s, dispatcher=%s, federation=%s",
            "connected" if semantic_memory else "none",
            "connected" if verifier else "none",
            "connected" if dispatcher else "none",
            "connected" if federation else "none",
        )

    # ===================================================================
    # Schema access
    # ===================================================================

    @staticmethod
    def get_tool_schemas() -> list[dict[str, Any]]:
        """Return the MCP-compatible JSON Schema definitions for all tools.

        Returns:
            List of tool schema dicts, each containing 'name', 'description',
            and 'inputSchema' keys compatible with the MCP tool registration
            protocol.
        """
        return list(TOOL_SCHEMAS)

    # ===================================================================
    # Dispatch
    # ===================================================================

    async def dispatch_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        auth_token: Optional[str] = None,
    ) -> dict[str, Any]:
        """Route an incoming tool call to the appropriate handler.

        Args:
            tool_name: One of the 5 registered tool names.
            arguments: The tool arguments matching the inputSchema.
            auth_token: Bearer token that must match the server's configured
                token (if one was set). Rejected with an error if invalid.

        Returns:
            A dict with at least a ``status`` key ("ok" or "error") and
            tool-specific result data.

        Raises:
            ValueError: If tool_name is not recognized.
        """
        if self._auth_token and auth_token != self._auth_token:
            logger.warning("MCP auth failure for tool '%s'", tool_name)
            return {
                "status": "error",
                "tool": tool_name,
                "error": "authentication failed",
                "error_type": "AuthError",
            }

        handler = self._handlers.get(tool_name)
        if handler is None:
            valid_names = sorted(self._handlers.keys())
            raise ValueError(
                f"Unknown tool '{tool_name}'. Valid tools: {valid_names}"
            )

        logger.info("Dispatching MCP tool call: %s(%s)", tool_name, _truncate_args(arguments))

        # Validate inputs through Pydantic schemas
        try:
            validated = validate_tool_input(tool_name, arguments)
            validated_args = validated.model_dump(exclude_none=True)
        except KeyError:
            validated_args = arguments  # unknown tool — pass through
        except Exception as ve:
            logger.warning("MCP tool '%s' input validation failed: %s", tool_name, ve)
            return {
                "status": "error",
                "tool": tool_name,
                "error": f"Input validation failed: {ve}",
                "error_type": "ValidationError",
            }

        try:
            result = await handler(**validated_args)
            logger.info("MCP tool '%s' completed successfully", tool_name)
            return result
        except Exception as exc:
            logger.error("MCP tool '%s' failed: %s", tool_name, exc, exc_info=True)
            return {
                "status": "error",
                "tool": tool_name,
                "error": str(exc),
                "error_type": type(exc).__name__,
            }

    # ===================================================================
    # Tool 1: claw_query_memory
    # ===================================================================

    async def handle_query_memory(
        self,
        query: str,
        limit: int = 3,
        language: Optional[str] = None,
    ) -> dict[str, Any]:
        """Query CLAW's semantic memory for similar past solutions.

        Uses SemanticMemory.find_similar() for hybrid (vector + text) search
        when available, falling back to Repository.search_methodologies_text()
        for FTS5-only search.

        Args:
            query: Problem description or search terms.
            limit: Maximum number of results (default 3).
            language: Optional programming language filter.

        Returns:
            Dict with status, results list, and metadata.
        """
        if not query or not query.strip():
            return {
                "status": "error",
                "error": "Query string must not be empty.",
                "results": [],
            }

        limit = max(1, min(limit, 20))  # Clamp to [1, 20]

        results_data: list[dict[str, Any]] = []

        if self.semantic_memory is not None:
            # Full hybrid search through SemanticMemory
            try:
                search_results = await self.semantic_memory.find_similar(
                    query=query,
                    limit=limit,
                    language=language,
                )
                for sr in search_results:
                    meth = sr.methodology
                    results_data.append({
                        "methodology_id": meth.id,
                        "problem_description": meth.problem_description,
                        "solution_code": meth.solution_code,
                        "methodology_notes": meth.methodology_notes,
                        "tags": meth.tags,
                        "language": meth.language,
                        "methodology_type": meth.methodology_type,
                        "lifecycle_state": meth.lifecycle_state,
                        "combined_score": sr.combined_score,
                        "vector_score": sr.vector_score,
                        "text_score": sr.text_score,
                    })
                    # Record retrieval for outcome tracking
                    await self.semantic_memory.record_retrieval(meth.id)

                logger.info(
                    "query_memory (hybrid): query='%s', limit=%d, language=%s, found=%d",
                    query[:60], limit, language, len(results_data),
                )
            except Exception as exc:
                logger.warning(
                    "Hybrid search failed, falling back to text search: %s", exc,
                )
                results_data = await self._fallback_text_search(query, limit)
        else:
            # Fallback: FTS5 text search only
            results_data = await self._fallback_text_search(query, limit)

        return {
            "status": "ok",
            "query": query,
            "language_filter": language,
            "result_count": len(results_data),
            "results": results_data,
        }

    async def _fallback_text_search(
        self, query: str, limit: int
    ) -> list[dict[str, Any]]:
        """Fallback: search methodologies using FTS5 text search only.

        Args:
            query: Search terms.
            limit: Maximum number of results.

        Returns:
            List of result dicts.
        """
        results_data: list[dict[str, Any]] = []
        try:
            methodologies = await self.repository.search_methodologies_text(query, limit=limit)
            for meth, bm25_rank in methodologies:
                results_data.append({
                    "methodology_id": meth.id,
                    "problem_description": meth.problem_description,
                    "solution_code": meth.solution_code,
                    "methodology_notes": meth.methodology_notes,
                    "tags": meth.tags,
                    "language": meth.language,
                    "methodology_type": meth.methodology_type,
                    "lifecycle_state": meth.lifecycle_state,
                    "combined_score": None,
                    "vector_score": None,
                    "text_score": bm25_rank,
                })
                # Record retrieval
                await self.repository.update_methodology_retrieval(meth.id)

            logger.info(
                "query_memory (text fallback): query='%s', limit=%d, found=%d",
                query[:60], limit, len(results_data),
            )
        except Exception as exc:
            logger.error("Text search failed: %s", exc)
        return results_data

    async def _candidate_cards_for_slot(
        self,
        *,
        task_text: str,
        slot: Any,
        target_language: Optional[str],
    ) -> list[Any]:
        query = " ".join([slot.name, slot.abstract_job, task_text]).strip()
        summaries = await self.repository.search_component_cards_text(
            query,
            limit=8,
            language=target_language,
        )
        if not summaries:
            summaries = await self.repository.list_component_cards(limit=12, language=target_language)

        cards: list[Any] = []
        seen: set[str] = set()
        for summary in summaries:
            component_id = getattr(summary, "id", None)
            if not component_id or component_id in seen:
                continue
            card = await self.repository.get_component_card(component_id)
            if card is None:
                continue
            cards.append(card)
            seen.add(component_id)
        return cards

    async def _active_governance_policies(self, task_archetype: str) -> list[Any]:
        task_policies = await self.repository.list_governance_policies(
            task_archetype=task_archetype,
            active_only=True,
            limit=200,
        )
        global_policies = await self.repository.list_governance_policies(
            task_archetype=None,
            active_only=True,
            limit=200,
        )
        merged: dict[str, Any] = {}
        for policy in [*task_policies, *global_policies]:
            if policy.task_archetype and policy.task_archetype != task_archetype:
                continue
            merged[policy.id] = policy
        return list(merged.values())

    # ===================================================================
    # CAM-SEQ tool extensions
    # ===================================================================

    async def handle_decompose_task(
        self,
        task_text: str,
        workspace_dir: Optional[str] = None,
        target_language: Optional[str] = None,
        target_stack_hints: Optional[list[str]] = None,
        check_commands: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        plan = decompose_task(
            task_text,
            workspace_path=workspace_dir,
            target_language=target_language,
            target_stack_hints=target_stack_hints or [],
            check_commands=check_commands or [],
        )
        return {
            "status": "ok",
            "plan_id": plan.plan_id,
            "task_archetype": plan.task_archetype,
            "archetype_confidence": plan.archetype_confidence,
            "slots": [slot.model_dump(mode="json") for slot in plan.slots],
        }

    async def handle_build_application_packet(
        self,
        workspace_dir: str,
        task_text: str,
        slot_name: str,
        target_language: Optional[str] = None,
        target_stack_hints: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        plan = decompose_task(
            task_text,
            workspace_path=workspace_dir,
            target_language=target_language,
            target_stack_hints=target_stack_hints or [],
            check_commands=[],
        )
        slot = next((item for item in plan.slots if item.name == slot_name), None)
        if slot is None:
            return {"status": "error", "error": f"slot '{slot_name}' not found"}

        cards = await self._candidate_cards_for_slot(
            task_text=task_text,
            slot=slot,
            target_language=target_language,
        )
        fit_rows = await self.repository.find_component_fit(plan.task_archetype, slot.name, None, limit=20)
        compiled_recipes = await self.repository.list_compiled_recipes(
            task_archetype=plan.task_archetype,
            active_only=True,
            limit=10,
        )
        governance_policies = await self._active_governance_policies(plan.task_archetype)
        ranked = rank_components_for_slot(
            slot,
            cards,
            fit_rows=fit_rows,
            compiled_recipes=compiled_recipes,
            governance_policies=governance_policies,
            target_language=target_language,
            target_stack_hints=target_stack_hints or [],
        )
        if not ranked:
            return {"status": "error", "error": f"no candidates available for slot '{slot_name}'"}

        packet = build_application_packet(
            plan.plan_id,
            plan.task_archetype,
            slot,
            ranked,
            governance_policies=governance_policies,
        )
        return {
            "status": "ok",
            "schema_version": packet.schema_version,
            "review_required": packet.reviewer_required,
            "confidence_basis": packet.confidence_basis,
            "packet": packet.model_dump(mode="json"),
        }

    async def handle_get_run_connectome(self, run_id: str) -> dict[str, Any]:
        connectome = await self.repository.get_run_connectome(run_id)
        if connectome is None:
            return {"status": "error", "error": "run connectome not found", "run_id": run_id}
        pair_events = await self.repository.list_run_pair_events(run_id)
        landing_events = await self.repository.list_run_landing_events(run_id)
        outcome_events = await self.repository.list_run_outcome_events(run_id)
        stored_edges = await self.repository.list_run_connectome_edges(connectome.id)

        nodes: dict[str, dict[str, str]] = {run_id: {"id": run_id, "kind": "run"}}
        edges: list[dict[str, Any]] = []
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
            edges.append(
                {
                    "source": edge["source_node"],
                    "target": edge["target_node"],
                    "type": edge["edge_type"],
                    "metadata": json.loads(edge["metadata_json"]) if edge.get("metadata_json") else {},
                }
            )
        return {
            "status": "ok",
            "run_id": run_id,
            "connectome": {
                "id": connectome.id,
                "task_archetype": connectome.task_archetype,
                "status": connectome.status,
                "nodes": list(nodes.values()),
                "edges": edges,
            },
        }

    async def handle_trace_failure(self, run_id: str, root: Optional[str] = None) -> dict[str, Any]:
        outcome_events = await self.repository.list_run_outcome_events(run_id)
        landing_events = await self.repository.list_run_landing_events(run_id)
        pair_events = await self.repository.list_run_pair_events(run_id)
        slot_executions = await self.repository.list_run_slot_executions(run_id)
        action_audits = await self.repository.list_run_action_audits(run_id)
        run_events = await self.repository.list_run_events(run_id)

        failing_outcome = next((event for event in outcome_events if not event.success), outcome_events[0] if outcome_events else None)
        if failing_outcome is None:
            return {
                "status": "ok",
                "run_id": run_id,
                "root": {"kind": "run", "id": run_id if root is None else root},
                "cause_chain": [],
                "runner_up_analysis": None,
                "confidence": 0.0,
            }

        packet = await self.repository.get_application_packet(failing_outcome.packet_id)
        pair = next((event for event in pair_events if event.packet_id == failing_outcome.packet_id), None)
        landing = next((event for event in landing_events if event.packet_id == failing_outcome.packet_id), None)
        slot_execution = next((item for item in slot_executions if item.slot_id == failing_outcome.slot_id), None)
        relevant_audits = [audit for audit in action_audits if audit.slot_id in {None, failing_outcome.slot_id}]
        relevant_events = [event for event in run_events if event.slot_id in {None, failing_outcome.slot_id}]

        cause_chain: list[dict[str, Any]] = []
        if slot_execution is not None:
            cause_chain.append(
                {
                    "kind": "slot_execution",
                    "id": failing_outcome.slot_id,
                    "explanation": f"retry_count={slot_execution.retry_count}, blocked_wait_ms={slot_execution.blocked_wait_ms}, family_wait_ms={slot_execution.family_wait_ms}",
                    "rank_score": 0.65 + min(slot_execution.retry_count * 0.05, 0.2),
                }
            )
        for audit in relevant_audits[-3:]:
            cause_chain.append(
                {
                    "kind": "audit",
                    "id": audit.id,
                    "explanation": f"{audit.action_type}: {audit.reason}",
                    "rank_score": 0.78 if audit.action_type in {"block_slot", "ban_family"} else 0.58,
                }
            )
        if landing is not None:
            cause_chain.append(
                {
                    "kind": "landing",
                    "id": landing.id,
                    "explanation": f"landing at {landing.file_path}",
                    "rank_score": 0.72,
                }
            )
        if pair is not None and packet is not None:
            cause_chain.append(
                {
                    "kind": "component",
                    "id": pair.component_id,
                    "explanation": f"selected component {packet.selected.title}",
                    "rank_score": 0.74,
                }
            )
        for event in relevant_events[-2:]:
            if event.event_type == "retry_delta":
                cause_chain.append(
                    {
                        "kind": "retry_delta",
                        "id": event.id,
                        "explanation": "retry delta recorded before failure",
                        "rank_score": 0.7,
                    }
                )

        cause_chain.sort(key=lambda item: item["rank_score"], reverse=True)
        runner_up = packet.runner_ups[0] if packet and packet.runner_ups else None
        return {
            "status": "ok",
            "run_id": run_id,
            "root": {"kind": "outcome", "id": failing_outcome.id if root is None else root},
            "cause_chain": cause_chain[:5],
            "runner_up_analysis": (
                {
                    "component_id": runner_up.component_id,
                    "likely_better": True,
                    "why": runner_up.why_fit[:3],
                }
                if runner_up
                else None
            ),
            "confidence": cause_chain[0]["rank_score"] if cause_chain else 0.0,
        }

    async def handle_promote_recipe(
        self,
        run_id: str,
        recipe_name: str,
        minimum_sample_size: int = 5,
    ) -> dict[str, Any]:
        connectome = await self.repository.get_run_connectome(run_id)
        if connectome is None:
            return {"status": "error", "error": "run connectome not found", "run_id": run_id}
        pair_events = await self.repository.list_run_pair_events(run_id)
        packets = [
            await self.repository.get_application_packet(event.packet_id)
            for event in pair_events
        ]
        packets = [packet for packet in packets if packet is not None]
        recipe = await self.repository.save_compiled_recipe(
            CompiledRecipe(
                task_archetype=connectome.task_archetype or "unknown",
                recipe_name=recipe_name,
                recipe_json={
                    "slot_order": [packet.slot.name for packet in packets],
                    "preferred_families": [packet.selected.receipt.family_barcode for packet in packets],
                    "required_proof_gates": sorted({gate.gate_type for packet in packets for gate in packet.proof_plan}),
                    "disallowed_stretch_conditions": ["critical_slot_stretch"],
                },
                sample_size=len(packets),
                is_active=len(packets) >= minimum_sample_size,
            )
        )
        return {"status": "ok", "recipe": recipe.model_dump(mode="json")}

    async def handle_queue_mining_mission(
        self,
        run_id: str,
        slot_family: str,
        priority: str,
        reason: str,
    ) -> dict[str, Any]:
        mission = await self.repository.save_mining_mission(
            MiningMission(
                run_id=run_id,
                slot_family=slot_family,
                priority=priority,
                reason=reason,
                mission_json={
                    "run_id": run_id,
                    "slot_family": slot_family,
                    "priority": priority,
                    "reason": reason,
                    "created_via": "mcp",
                },
            )
        )
        return {"status": "ok", "mission": mission.model_dump(mode="json")}

    # ===================================================================
    # Tool 2: claw_store_finding
    # ===================================================================

    async def handle_store_finding(
        self,
        problem_description: str,
        solution_code: str,
        tags: Optional[list[str]] = None,
        methodology_type: Optional[str] = None,
    ) -> dict[str, Any]:
        """Store a new finding/methodology in CLAW's semantic memory.

        Saves via SemanticMemory.save_solution() when available (which generates
        embeddings automatically), falling back to Repository.save_methodology()
        for direct database insert without embeddings.

        Args:
            problem_description: Natural language description of the problem.
            solution_code: The code or procedure that solves the problem.
            tags: Optional list of categorization tags.
            methodology_type: Optional type (BUG_FIX, PATTERN, DECISION, GOTCHA).

        Returns:
            Dict with status and the saved methodology's ID.
        """
        if not problem_description or not problem_description.strip():
            return {
                "status": "error",
                "error": "problem_description must not be empty.",
            }
        if not solution_code or not solution_code.strip():
            return {
                "status": "error",
                "error": "solution_code must not be empty.",
            }

        # Validate methodology_type if provided
        valid_types = {"BUG_FIX", "PATTERN", "DECISION", "GOTCHA"}
        if methodology_type and methodology_type not in valid_types:
            return {
                "status": "error",
                "error": f"Invalid methodology_type '{methodology_type}'. Must be one of: {sorted(valid_types)}",
            }

        tags = tags or []

        if self.semantic_memory is not None:
            try:
                methodology = await self.semantic_memory.save_solution(
                    problem_description=problem_description,
                    solution_code=solution_code,
                    tags=tags,
                    methodology_type=methodology_type,
                )
                logger.info(
                    "store_finding (semantic): saved methodology %s, type=%s, tags=%s",
                    methodology.id, methodology_type, tags,
                )
                return {
                    "status": "ok",
                    "methodology_id": methodology.id,
                    "lifecycle_state": methodology.lifecycle_state,
                    "has_embedding": methodology.problem_embedding is not None,
                    "message": "Finding stored successfully with embedding.",
                }
            except Exception as exc:
                logger.warning(
                    "SemanticMemory save failed, falling back to repository: %s", exc,
                )

        # Fallback: direct repository save without embedding
        try:
            from claw.core.models import Methodology

            methodology = Methodology(
                problem_description=problem_description,
                solution_code=solution_code,
                tags=tags,
                methodology_type=methodology_type,
                lifecycle_state="embryonic",
            )
            saved = await self.repository.save_methodology(methodology)
            logger.info(
                "store_finding (repository fallback): saved methodology %s",
                saved.id,
            )
            return {
                "status": "ok",
                "methodology_id": saved.id,
                "lifecycle_state": saved.lifecycle_state,
                "has_embedding": False,
                "message": "Finding stored without embedding (semantic memory unavailable).",
            }
        except Exception as exc:
            logger.error("Failed to store finding: %s", exc)
            return {
                "status": "error",
                "error": f"Failed to store finding: {exc}",
            }

    # ===================================================================
    # Tool 3: claw_verify_claim
    # ===================================================================

    async def handle_verify_claim(
        self,
        claim: str,
        workspace_dir: Optional[str] = None,
    ) -> dict[str, Any]:
        """Verify a claim about code by scanning for placeholder patterns and
        running basic validation.

        Checks the claim text for placeholder indicators (TODO, FIXME, stubs,
        etc.) and, if a workspace directory is provided, scans the workspace
        files for placeholder patterns.

        If a full Verifier is available, delegates to its claim validation
        and test running capabilities.

        Args:
            claim: The claim to verify (e.g. "all tests pass", "no placeholders").
            workspace_dir: Optional path to workspace for file-level scanning.

        Returns:
            Dict with status, verdict ("PASS"/"FAIL"/"PARTIAL"), and details.
        """
        if not claim or not claim.strip():
            return {
                "status": "error",
                "error": "Claim text must not be empty.",
            }

        violations: list[dict[str, str]] = []
        checks_performed: list[str] = []

        # Check 1: Scan the claim text itself for contradictions
        claim_lower = claim.lower()
        claim_analysis = self._analyze_claim_text(claim_lower)
        checks_performed.append("claim_text_analysis")

        # Check 2: If workspace_dir provided, scan workspace files for placeholders
        if workspace_dir:
            workspace_violations = await self._scan_workspace_placeholders(workspace_dir)
            violations.extend(workspace_violations)
            checks_performed.append("workspace_placeholder_scan")

            # If claim asserts completion/readiness, placeholders are a violation
            completion_keywords = {
                "complete", "done", "finished", "ready", "production ready",
                "no placeholders", "no todos", "fully implemented",
            }
            if any(kw in claim_lower for kw in completion_keywords) and workspace_violations:
                violations.append({
                    "check": "claim_contradiction",
                    "detail": (
                        f"Claim '{claim[:80]}' asserts completion, but "
                        f"{len(workspace_violations)} placeholder(s) found in workspace."
                    ),
                })

        # Check 3: If Verifier available and workspace_dir provided, run tests
        test_result: Optional[dict[str, Any]] = None
        if self.verifier is not None and workspace_dir:
            test_claims = {"tests pass", "all tests pass", "tested", "test"}
            if any(tc in claim_lower for tc in test_claims):
                try:
                    passed, output, test_count = await self.verifier.run_tests(workspace_dir)
                    test_result = {
                        "tests_passed": passed,
                        "test_count": test_count,
                        "output_snippet": output[:500] if output else "",
                    }
                    checks_performed.append("test_execution")
                    if not passed:
                        violations.append({
                            "check": "test_execution",
                            "detail": f"Tests failed ({test_count} tests): {output[:200]}",
                        })
                except Exception as exc:
                    logger.warning("Test execution during claim verification failed: %s", exc)
                    test_result = {
                        "tests_passed": None,
                        "error": str(exc),
                    }
                    checks_performed.append("test_execution_attempted")

        # Determine verdict
        if violations:
            verdict = "FAIL"
        elif claim_analysis.get("unsubstantiated"):
            verdict = "PARTIAL"
        else:
            verdict = "PASS"

        return {
            "status": "ok",
            "claim": claim,
            "verdict": verdict,
            "violations": violations,
            "violation_count": len(violations),
            "claim_analysis": claim_analysis,
            "test_result": test_result,
            "checks_performed": checks_performed,
        }

    def _analyze_claim_text(self, claim_lower: str) -> dict[str, Any]:
        """Analyze the claim text for known claim patterns and flag
        unsubstantiated assertions.

        Args:
            claim_lower: The lowercased claim text.

        Returns:
            Dict with analysis results.
        """
        from claw.verifier import CLAIM_PATTERNS

        matched_claims: list[dict[str, str]] = []
        unsubstantiated = False

        for claim_def in CLAIM_PATTERNS:
            for phrase in claim_def["claims"]:
                pattern = r"\b" + re.escape(phrase) + r"\b"
                if re.search(pattern, claim_lower):
                    matched_claims.append({
                        "phrase": phrase,
                        "required_evidence": claim_def["evidence"],
                    })
                    # Claims like "production ready" are always flagged
                    if phrase in ("production ready", "prod ready", "ready for production"):
                        unsubstantiated = True
                    break

        return {
            "matched_claim_patterns": matched_claims,
            "claim_count": len(matched_claims),
            "unsubstantiated": unsubstantiated,
        }

    async def _scan_workspace_placeholders(
        self, workspace_dir: str
    ) -> list[dict[str, str]]:
        """Scan workspace files for placeholder patterns.

        Walks Python, TypeScript, and JavaScript files in the workspace and
        checks each line against PLACEHOLDER_PATTERNS.

        Args:
            workspace_dir: Path to the workspace root directory.

        Returns:
            List of violation dicts with check name and detail.
        """
        import os

        violations: list[dict[str, str]] = []
        workspace = Path(workspace_dir)

        if not workspace.is_dir():
            logger.warning("Workspace directory does not exist: %s", workspace_dir)
            return violations

        # Scan code files only (limit scope to avoid scanning binaries)
        code_extensions = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".rb", ".java"}
        scanned_files = 0
        max_files = 500  # Safety limit

        for root, _dirs, files in os.walk(str(workspace)):
            # Skip hidden dirs and common non-code dirs
            root_path = Path(root)
            skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", "dist", "build"}
            if any(part in skip_dirs for part in root_path.parts):
                continue

            for filename in files:
                if scanned_files >= max_files:
                    break

                file_path = root_path / filename
                if file_path.suffix not in code_extensions:
                    continue

                scanned_files += 1
                try:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                    for line_num, line in enumerate(content.splitlines(), start=1):
                        for pattern in PLACEHOLDER_PATTERNS:
                            if re.search(pattern, line, re.IGNORECASE):
                                rel_path = file_path.relative_to(workspace)
                                violations.append({
                                    "check": "placeholder_scan",
                                    "detail": (
                                        f"Placeholder found in {rel_path}:{line_num}: "
                                        f"{line.strip()[:100]}"
                                    ),
                                })
                                break  # One violation per line
                except Exception as exc:
                    logger.debug("Could not read %s: %s", file_path, exc)

            if scanned_files >= max_files:
                break

        logger.info(
            "Workspace placeholder scan: %d files scanned, %d violations found",
            scanned_files, len(violations),
        )
        return violations

    # ===================================================================
    # Tool 4: claw_request_specialist
    # ===================================================================

    async def handle_request_specialist(
        self,
        task_description: str,
        preferred_agent: Optional[str] = None,
    ) -> dict[str, Any]:
        """Request a different agent for a subtask.

        When a Dispatcher is available, uses its Bayesian routing to select
        the best-fit agent for the described subtask. Otherwise, returns a
        recommendation based on the static routing table.

        This tool does not execute the subtask itself -- it routes and returns
        the routing decision. The orchestrator is responsible for actually
        dispatching the work to the selected agent.

        Args:
            task_description: Description of the subtask needing a specialist.
            preferred_agent: Optional preferred agent ID.

        Returns:
            Dict with status, selected agent, and routing rationale.
        """
        if not task_description or not task_description.strip():
            return {
                "status": "error",
                "error": "task_description must not be empty.",
            }

        valid_agents = {"claude", "codex", "gemini", "grok"}
        if preferred_agent and preferred_agent not in valid_agents:
            return {
                "status": "error",
                "error": (
                    f"Invalid preferred_agent '{preferred_agent}'. "
                    f"Must be one of: {sorted(valid_agents)}"
                ),
            }

        # Infer task type from description for routing
        inferred_type = self._infer_task_type(task_description)

        if self.dispatcher is not None:
            # Use real Dispatcher routing with Bayesian scores
            try:
                from claw.core.models import Task

                routing_task = Task(
                    project_id="mcp_specialist_request",
                    title=f"Specialist request: {task_description[:80]}",
                    description=task_description,
                    task_type=inferred_type,
                    recommended_agent=preferred_agent,
                )

                selected_agent = await self.dispatcher.route_task(routing_task)
                routing_info = self.dispatcher.get_routing_info(inferred_type)

                logger.info(
                    "request_specialist: routed to '%s' (inferred_type='%s', preferred='%s')",
                    selected_agent, inferred_type, preferred_agent,
                )

                return {
                    "status": "ok",
                    "selected_agent": selected_agent,
                    "inferred_task_type": inferred_type,
                    "preferred_agent": preferred_agent,
                    "routing_method": "dispatcher_bayesian",
                    "routing_info": routing_info,
                    "message": (
                        f"Agent '{selected_agent}' selected for subtask. "
                        f"The orchestrator will dispatch the work."
                    ),
                }
            except Exception as exc:
                logger.warning(
                    "Dispatcher routing failed, falling back to static: %s", exc,
                )

        # Fallback: static routing recommendation
        from claw.dispatcher import DEFAULT_AGENT, STATIC_ROUTING

        static_agent = STATIC_ROUTING.get(inferred_type, DEFAULT_AGENT)
        selected = preferred_agent if preferred_agent else static_agent

        logger.info(
            "request_specialist (static fallback): recommending '%s' (type='%s')",
            selected, inferred_type,
        )

        return {
            "status": "ok",
            "selected_agent": selected,
            "inferred_task_type": inferred_type,
            "preferred_agent": preferred_agent,
            "routing_method": "static_fallback",
            "routing_info": {
                "static_route": static_agent,
                "inferred_type": inferred_type,
                "note": "Dispatcher unavailable; recommendation based on static routing table.",
            },
            "message": (
                f"Agent '{selected}' recommended for subtask (static routing). "
                f"The orchestrator will dispatch the work."
            ),
        }

    def _infer_task_type(self, description: str) -> str:
        """Infer a task_type from a natural language description.

        Maps keywords in the description to CLAW's task_type taxonomy used
        by the Dispatcher's static routing table.

        Args:
            description: Task description text.

        Returns:
            Inferred task_type string.
        """
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
            (["migration", "migrate", "port", "convert"], "migration"),
            (["comprehension", "understand", "context", "full repo"], "full_repo_review"),
            (["quick fix", "hotfix", "patch", "typo", "small fix"], "quick_fix"),
            (["bug", "fix", "error", "crash", "broken", "issue", "defect"], "bug_fix"),
            (["web", "search", "lookup", "research", "find out"], "web_lookup"),
            (["bulk", "batch", "mass change", "many files"], "bulk_changes"),
            (["fast", "quick", "rapid", "iterate"], "fast_iteration"),
        ]

        for keywords, task_type in keyword_map:
            if any(kw in desc_lower for kw in keywords):
                return task_type

        return "analysis"  # Default task type

    async def handle_request_specialist_packet(
        self,
        task_text: str,
        slot_name: Optional[str] = None,
        preferred_agent: Optional[str] = None,
        target_language: Optional[str] = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        if not task_text or not task_text.strip():
            return {"status": "error", "error": "task_text must not be empty."}

        routing = await self.handle_request_specialist(
            task_description=task_text,
            preferred_agent=preferred_agent,
        )
        if routing.get("status") != "ok":
            return routing

        plan = decompose_task(
            task_text,
            workspace_path=None,
            target_language=target_language,
            target_stack_hints=[],
            check_commands=[],
        )
        slot = next((item for item in plan.slots if item.name == slot_name), None) if slot_name else (plan.slots[0] if plan.slots else None)

        local_results: list[dict[str, Any]] = []
        cards = await self._candidate_cards_for_slot(
            task_text=task_text,
            slot=slot,
            target_language=target_language,
        ) if slot is not None else []
        for card in cards[:limit]:
            local_results.append(
                {
                    "component_id": card.id,
                    "title": card.title,
                    "component_type": card.component_type,
                    "abstract_jobs": list(card.abstract_jobs),
                    "language": card.language,
                    "repo": card.receipt.repo,
                    "file_path": card.receipt.file_path,
                    "symbol": card.receipt.symbol,
                    "family_barcode": card.receipt.family_barcode,
                    "provenance_precision": getattr(card.receipt.provenance_precision, "value", str(card.receipt.provenance_precision)),
                    "source_instance": "primary",
                    "match_type": "direct_fit" if slot and any(slot.abstract_job in str(job) or slot.name in str(job) for job in card.abstract_jobs) else "pattern_transfer",
                    "match_score": 1.0,
                    "relevance_score": 1.0,
                }
            )

        sibling_results: list[dict[str, Any]] = []
        if self.federation is not None:
            try:
                sibling_results = [
                    item.as_dict()
                    for item in await self.federation.query_component_packets(
                        task_text,
                        slot_name=slot.name if slot else slot_name,
                        task_archetype=plan.task_archetype,
                        language=target_language,
                        max_total=limit,
                    )
                ]
            except Exception as exc:
                logger.warning("specialist packet federation query failed: %s", exc)

        merged = [*local_results, *sibling_results]
        merged = merged[:limit]
        review_required = not merged or any(item.get("match_type") != "direct_fit" for item in merged[:2])

        return {
            "status": "ok",
            "exchange_id": f"specpkt_{uuid.uuid4().hex[:12]}",
            "selected_agent": routing.get("selected_agent"),
            "inferred_task_type": routing.get("inferred_task_type"),
            "preferred_agent": preferred_agent,
            "routing_method": routing.get("routing_method"),
            "task_archetype": plan.task_archetype,
            "archetype_confidence": plan.archetype_confidence,
            "slot": slot.model_dump(mode="json") if slot else None,
            "review_required": review_required,
            "packet_candidates": merged,
        }

    def _exchange_payload(self, exchange: ExternalSpecialistExchange) -> dict[str, Any]:
        payload = exchange.model_dump(mode="json")
        request_json = payload.get("request_json") if isinstance(payload.get("request_json"), dict) else {}
        payload["exchange_id"] = exchange.id
        payload["selected_agent"] = exchange.specialist_identity
        payload["preferred_agent"] = request_json.get("selected_agent")
        payload["request_envelope"] = request_json
        if exchange.reconciliation_outcome:
            payload["outcome"] = (
                "reconciled"
                if exchange.reconciliation_outcome.startswith(("accepted_", "stored_"))
                else exchange.reconciliation_outcome
            )
        return payload

    async def handle_export_specialist_exchange(
        self,
        task_text: str,
        slot_name: Optional[str] = None,
        preferred_agent: Optional[str] = None,
        target_language: Optional[str] = None,
        deadline_seconds: Optional[int] = None,
        workspace_dir: Optional[str] = None,
        plan_id: Optional[str] = None,
        slot_id: Optional[str] = None,
        packet_id: Optional[str] = None,
        allowed_context: Optional[dict[str, Any]] = None,
        redaction_summary: str = "",
    ) -> dict[str, Any]:
        if not task_text or not task_text.strip():
            return {"status": "error", "error": "task_text must not be empty."}

        packet_result = await self.handle_request_specialist_packet(
            task_text=task_text,
            slot_name=slot_name,
            preferred_agent=preferred_agent,
            target_language=target_language,
            limit=5,
        )
        if packet_result.get("status") != "ok":
            return packet_result

        exchange = ExternalSpecialistExchange(
            id=new_exchange_id(),
            request_id=new_request_id(),
            plan_id=plan_id,
            slot_id=slot_id,
            packet_id=packet_id,
            task_text=task_text.strip(),
            specialty=str(packet_result.get("inferred_task_type") or "analysis"),
            specialist_identity=str(packet_result.get("selected_agent") or ""),
            status="awaiting_reply",
            deadline_at=deadline_from_seconds(deadline_seconds),
        )
        envelope = build_request_envelope(
            exchange,
            selected_agent=str(packet_result.get("selected_agent") or ""),
            task_archetype=packet_result.get("task_archetype"),
            archetype_confidence=packet_result.get("archetype_confidence"),
            slot=packet_result.get("slot"),
            packet_candidates=packet_result.get("packet_candidates", []),
            allowed_context=allowed_context or {},
            redaction_summary=redaction_summary,
        )
        spool_dir = specialist_exchange_spool_dir(workspace_dir)
        request_path = write_request_envelope(spool_dir, envelope)
        exchange.request_path = str(request_path)
        exchange.request_json = envelope
        saved = await self.repository.save_external_specialist_exchange(exchange)
        return {
            "status": "ok",
            "exchange": self._exchange_payload(saved),
            "request_envelope": envelope,
            "request_path": str(request_path),
        }

    async def handle_import_specialist_exchange(
        self,
        reply_path: Optional[str] = None,
        workspace_dir: Optional[str] = None,
    ) -> dict[str, Any]:
        await self.repository.expire_external_specialist_exchanges()
        spool_dir = specialist_exchange_spool_dir(workspace_dir)
        imported: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        try:
            paths = candidate_reply_paths(spool_dir, reply_path)
        except ValueError as exc:
            return {"status": "error", "imported": [], "rejected": [{"reason": str(exc)}]}

        for path in paths:
            try:
                reply = load_reply_envelope(path)
                validate_reply_envelope(reply)
                exchange = await self.repository.get_external_specialist_exchange_by_request(
                    reply["request_id"]
                )
                if exchange is None:
                    raise ValueError("no matching specialist exchange request")
                if exchange.status == "expired":
                    raise ValueError("matching specialist exchange is expired")
                if exchange.reply_id and exchange.reply_id == reply["reply_id"]:
                    imported.append(self._exchange_payload(exchange))
                    continue
                if exchange.reply_id and exchange.reply_id != reply["reply_id"]:
                    raise ValueError("matching specialist exchange already has a different reply")
                outcome = str(reply.get("recommendation_kind") or "reply_received")
                archive_path = archive_reply(spool_dir, path, exchange.request_id, reply["reply_id"])
                exchange.reply_id = str(reply["reply_id"])
                exchange.reply_path = str(archive_path)
                exchange.reply_json = reply
                exchange.specialist_identity = str(
                    reply.get("specialist_identity") or exchange.specialist_identity or ""
                )
                exchange.reconciliation_outcome = outcome
                exchange.status = (
                    "reconciled"
                    if outcome.startswith(("accepted_", "stored_"))
                    else "reply_received"
                )
                exchange.failure_reason = ""
                exchange.updated_at = datetime.now(UTC)
                saved = await self.repository.save_external_specialist_exchange(exchange)
                imported.append(self._exchange_payload(saved))
            except Exception as exc:
                rejected.append({"reply_path": str(path), "reason": str(exc)})

        return {"status": "ok", "imported": imported, "rejected": rejected}

    async def handle_list_specialist_exchanges(
        self,
        status: Optional[str] = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        await self.repository.expire_external_specialist_exchanges()
        exchanges = await self.repository.list_external_specialist_exchanges(
            status=status,
            limit=limit,
        )
        return {
            "status": "ok",
            "exchanges": [self._exchange_payload(exchange) for exchange in exchanges],
        }

    async def handle_bridge_specialist_exchange(
        self,
        exchange_id: str,
        command: Optional[str] = None,
        args: Optional[list[str]] = None,
        tool_name: str = "claw_request_specialist_packet",
        workspace_dir: Optional[str] = None,
        timeout_seconds: int = 60,
        max_reply_bytes: int = 65536,
        specialist_identity: str = "mcp_bridge",
    ) -> dict[str, Any]:
        exchange = await self.repository.get_external_specialist_exchange(exchange_id)
        if exchange is None:
            return {"status": "error", "error": "specialist exchange not found"}
        if not exchange.request_json:
            return {"status": "error", "error": "specialist exchange has no request envelope"}
        if exchange.status == "expired":
            return {"status": "error", "error": "specialist exchange is expired"}
        if exchange.reply_id:
            return {
                "status": "ok",
                "exchange": self._exchange_payload(exchange),
                "already_replied": True,
            }

        arguments = mcp_bridge_arguments(exchange.request_json)
        caller = self.mcp_bridge_caller
        if caller is not None:
            result = await caller(tool_name, arguments)
        else:
            if not command:
                return {
                    "status": "error",
                    "error": "command is required when no MCP bridge caller is configured",
                }
            result = await call_stdio_mcp_tool(
                command=command,
                args=args or [],
                tool_name=tool_name,
                arguments=arguments,
                timeout_seconds=timeout_seconds,
            )

        reply = normalize_mcp_bridge_reply(
            exchange.request_json,
            result,
            specialist_identity=specialist_identity,
            max_reply_bytes=max_reply_bytes,
        )
        spool_dir = specialist_exchange_spool_dir(workspace_dir)
        reply_path = write_inbox_reply(spool_dir, reply)
        import_result = await self.handle_import_specialist_exchange(
            reply_path=reply_path.name,
            workspace_dir=workspace_dir,
        )
        return {
            "status": import_result.get("status", "ok"),
            "bridge_status": "submitted",
            "reply_path": str(reply_path),
            "reply_envelope": reply,
            "imported": import_result.get("imported", []),
            "rejected": import_result.get("rejected", []),
        }

    async def handle_submit_specialist_webhook(
        self,
        exchange_id: str,
        endpoint_url: str,
        shared_secret: str,
        timeout_seconds: int = 30,
        allow_http: bool = False,
    ) -> dict[str, Any]:
        exchange = await self.repository.get_external_specialist_exchange(exchange_id)
        if exchange is None:
            return {"status": "error", "error": "specialist exchange not found"}
        if not exchange.request_json:
            return {"status": "error", "error": "specialist exchange has no request envelope"}
        if exchange.status == "expired":
            return {"status": "error", "error": "specialist exchange is expired"}
        if exchange.reply_id:
            return {
                "status": "ok",
                "exchange": self._exchange_payload(exchange),
                "already_replied": True,
            }

        try:
            submit_result = await submit_signed_http_exchange(
                endpoint_url=endpoint_url,
                request_envelope=exchange.request_json,
                shared_secret=shared_secret,
                timeout_seconds=timeout_seconds,
                allow_http=allow_http,
                sender=self.http_webhook_sender,
            )
        except Exception as exc:
            exchange.failure_reason = f"signed webhook submit failed: {exc}"
            exchange.updated_at = datetime.now(UTC)
            await self.repository.save_external_specialist_exchange(exchange)
            return {
                "status": "error",
                "error": str(exc),
                "exchange": self._exchange_payload(exchange),
            }

        exchange.status = "awaiting_reply"
        exchange.request_json = {
            **exchange.request_json,
            "http_transport": {
                "endpoint_url": endpoint_url,
                "status": "submitted",
                "submitted_at": datetime.now(UTC).isoformat(),
            },
        }
        exchange.failure_reason = ""
        exchange.updated_at = datetime.now(UTC)
        saved = await self.repository.save_external_specialist_exchange(exchange)
        return {
            "status": "ok",
            "transport_status": "submitted",
            "exchange": self._exchange_payload(saved),
            "submit_result": submit_result,
        }

    # ===================================================================
    # Tool 5: claw_escalate
    # ===================================================================

    async def handle_escalate(
        self,
        reason: str,
        context: Optional[dict[str, Any]] = None,
        task_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Escalate to human with full context.

        Logs the escalation event in the database's episode log for
        traceability, and returns an acknowledgment. In attended mode,
        the human operator will be notified. In supervised/autonomous mode,
        the task will be paused until human review.

        Args:
            reason: Why human intervention is needed.
            context: Additional context (what was attempted, errors, etc.).
            task_id: Optional task ID for traceability.

        Returns:
            Dict with status, escalation ID, and acknowledgment.
        """
        if not reason or not reason.strip():
            return {
                "status": "error",
                "error": "Escalation reason must not be empty.",
            }

        escalation_id = str(uuid.uuid4())
        timestamp = datetime.now(UTC).isoformat()
        context = context or {}

        # Build the escalation event payload
        event_data = {
            "escalation_id": escalation_id,
            "reason": reason,
            "context": context,
            "task_id": task_id,
            "timestamp": timestamp,
        }

        # Log the escalation to the episode log
        try:
            episode_id = await self.repository.log_episode(
                session_id=f"mcp_escalation_{escalation_id}",
                event_type="escalation",
                event_data=event_data,
                task_id=task_id,
                cycle_level="micro",
            )
            logger.warning(
                "ESCALATION [%s]: %s (task_id=%s, episode_id=%s)",
                escalation_id, reason, task_id, episode_id,
            )
        except Exception as exc:
            logger.error("Failed to log escalation event: %s", exc)
            episode_id = None

        # If we have a task_id and repository, increment the task's escalation counter
        if task_id:
            try:
                await self.repository.increment_task_escalation(task_id)
            except Exception as exc:
                logger.warning("Failed to increment escalation count for task %s: %s", task_id, exc)

        return {
            "status": "ok",
            "escalation_id": escalation_id,
            "episode_id": episode_id,
            "task_id": task_id,
            "timestamp": timestamp,
            "message": (
                "Escalation logged. Task processing is paused pending human review. "
                f"Reason: {reason}"
            ),
        }


# ---------------------------------------------------------------------------
# start_server() — factory/entry point for MCP SDK integration
# ---------------------------------------------------------------------------

def start_server(
    claw_mcp: ClawMCPServer,
    host: str = "127.0.0.1",
    port: int = 3100,
) -> Any:
    """Create and configure an MCP server with CLAW's tools registered.

    Attempts to import the ``mcp`` Python SDK and configure a Server instance
    with all 5 CLAW tools registered as tool handlers. If the ``mcp`` SDK is
    not installed, logs a warning and returns None.

    This function is a synchronous factory/entry point. It creates and
    configures the server but does NOT start the event loop. The caller is
    responsible for running the server (e.g. via ``server.run()`` or integrating
    into an existing asyncio loop).

    Args:
        claw_mcp: The ClawMCPServer instance with all dependencies wired.
        host: Host to bind the MCP server to (default 127.0.0.1).
        port: Port for the MCP server (default 3100).

    Returns:
        The configured MCP Server object if the SDK is available, or None
        if the SDK could not be imported.
    """
    try:
        from mcp.server import Server
        from mcp.types import Tool
    except ImportError:
        logger.warning(
            "MCP Python SDK not installed. Install with: pip install mcp "
            "The ClawMCPServer can still be used in-process via dispatch_tool(). "
            "MCP server will not be available for external agent connections."
        )
        return None

    server = Server("claw-mcp-server")
    logger.info("MCP SDK available. Configuring CLAW MCP server on %s:%d", host, port)

    # Register the list_tools handler
    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """Return the list of available CLAW tools."""
        tools = []
        for schema in claw_mcp.get_tool_schemas():
            tools.append(
                Tool(
                    name=schema["name"],
                    description=schema["description"],
                    inputSchema=schema["inputSchema"],
                )
            )
        return tools

    # Register the call_tool handler
    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
        """Handle incoming tool calls by dispatching to ClawMCPServer."""
        from mcp.types import TextContent

        result = await claw_mcp.dispatch_tool(name, arguments)
        return [TextContent(type="text", text=json.dumps(result, default=str))]

    logger.info(
        "CLAW MCP server configured with %d tools: %s",
        len(TOOL_SCHEMAS),
        [s["name"] for s in TOOL_SCHEMAS],
    )

    return server


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _truncate_args(args: dict[str, Any], max_len: int = 100) -> str:
    """Truncate argument values for logging without exposing full content.

    Args:
        args: The arguments dict to summarize.
        max_len: Maximum length for each value string.

    Returns:
        A compact string representation of the arguments.
    """
    parts = []
    for key, value in args.items():
        val_str = str(value)
        if len(val_str) > max_len:
            val_str = val_str[:max_len] + "..."
        parts.append(f"{key}={val_str}")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Stdio entry point — for use as an external MCP server subprocess
# ---------------------------------------------------------------------------

def main() -> int:
    """Run the CLAW MCP server over stdio transport.

    This is the entry point for external consumers (e.g. DeepScientist) that
    launch CLAW as a subprocess via ``python -m claw.mcp_server``.

    Environment variables:
        CLAW_DB_PATH: Path to claw.db (default: data/claw.db)
        CLAW_CONFIG: Path to claw.toml (default: claw.toml)
        CLAW_MCP_AUTH_TOKEN: Optional bearer token for authentication
        GOOGLE_API_KEY: Required for embedding-based semantic search
    """
    import asyncio
    import os
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,  # MCP uses stdout for protocol; logs go to stderr
    )

    config_path = os.environ.get("CLAW_CONFIG", "claw.toml")
    db_path = os.environ.get("CLAW_DB_PATH", "data/claw.db")
    auth_token = os.environ.get("CLAW_MCP_AUTH_TOKEN")

    async def _run() -> int:
        from claw.core.config import load_config
        from claw.db.embeddings import EmbeddingEngine
        from claw.db.engine import DatabaseEngine
        from claw.db.repository import Repository

        # Load config
        config = load_config(Path(config_path))

        # Override db_path if env var is set
        if db_path != "data/claw.db":
            config.database.db_path = db_path

        # Build minimal dependency graph (no agents, no orchestrator)
        engine = DatabaseEngine(config.database)
        await engine.connect()
        repository = Repository(engine)

        # Embeddings for semantic search
        embeddings = EmbeddingEngine(config.embeddings)

        # Semantic memory (for claw_query_memory / claw_store_finding)
        semantic_memory = None
        try:
            from claw.memory.hybrid_search import HybridSearch
            from claw.memory.semantic import SemanticMemory
            hybrid_search = HybridSearch(
                repository=repository,
                embedding_engine=embeddings,
            )
            semantic_memory = SemanticMemory(
                repository=repository,
                embedding_engine=embeddings,
                hybrid_search=hybrid_search,
            )
        except Exception as e:
            logger.warning("SemanticMemory unavailable: %s (text-only search)", e)

        # Create MCP server
        mcp_srv = ClawMCPServer(
            repository=repository,
            semantic_memory=semantic_memory,
            verifier=None,  # No verifier in stdio mode
            dispatcher=None,  # No dispatcher in stdio mode
            auth_token=auth_token,
        )

        # Start over stdio
        server = start_server(mcp_srv)
        if server is None:
            logger.error("MCP SDK not installed. Cannot start stdio server.")
            return 1

        logger.info("CLAW MCP server starting on stdio transport...")
        from mcp.server.stdio import stdio_server
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
        return 0

    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
