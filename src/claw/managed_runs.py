"""Managed source-to-outcome runs over the existing CAM-SEQ persistence model.

This module is an orchestration seam for CAM_Codx.  It does not build, edit,
verify, mine, promote, or create a parallel knowledge store.
"""

from __future__ import annotations

import enum
import math
import re
from pathlib import PurePath, PurePosixPath
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from claw.core.models import (
    LandingEvent,
    LandingOrigin,
    OutcomeEvent,
    PairEvent,
    RunConnectome,
    RunEvent,
    TaskPlanRecord,
)


class AssessmentLabel(str, enum.Enum):
    DIRECT_PRECEDENT = "direct_precedent"
    TRANSFERABLE_ANALOGY = "transferable_analogy"
    NEW_HYPOTHESIS = "new_hypothesis"


class SelectionDecision(str, enum.Enum):
    SELECTED = "selected"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    NEEDS_INSPECTION = "needs-inspection"


class OutcomeStatus(str, enum.Enum):
    VERIFIED_SUCCESS = "verified_success"
    VERIFIED_PARTIAL = "verified_partial"
    VERIFIED_FAILURE = "verified_failure"
    NOT_VERIFIED = "not_verified"


class MiningReceiptLink(BaseModel):
    receipt_id: str = Field(min_length=1)
    receipt_path: str = Field(min_length=1)
    receipt_sha256: str
    source_repositories: list[str] = Field(min_length=1)

    @field_validator("receipt_path")
    @classmethod
    def validate_receipt_path(cls, value: str) -> str:
        if not PurePath(value).is_absolute():
            raise ValueError("receipt_path must be absolute")
        return value

    @field_validator("receipt_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("receipt_sha256 must be 64 lowercase hexadecimal characters")
        return value


class CandidateDecision(BaseModel):
    candidate_id: str = Field(min_length=1)
    label: AssessmentLabel
    decision: SelectionDecision
    reason: str = Field(min_length=1)
    provenance: list[str] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)
    slot_id: str | None = None

    @model_validator(mode="after")
    def selected_candidate_names_slot(self) -> "CandidateDecision":
        if self.decision is SelectionDecision.SELECTED and not self.slot_id:
            raise ValueError("a selected candidate must name its target slot_id")
        return self


class ManagedOutcome(BaseModel):
    status: OutcomeStatus
    verifier_findings: list[str] = Field(default_factory=list)
    test_refs: list[str] = Field(default_factory=list)
    negative_memory_updates: list[str] = Field(default_factory=list)
    recipe_eligible: bool = False
    trust_delta: float = 0.0
    supersedes_outcome_id: str | None = None

    @field_validator("trust_delta")
    @classmethod
    def validate_trust_delta(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("trust_delta must be finite")
        return value

    @model_validator(mode="after")
    def positive_evidence_requires_verified_success(self) -> "ManagedOutcome":
        if self.status is not OutcomeStatus.VERIFIED_SUCCESS:
            if self.recipe_eligible or self.trust_delta > 0:
                raise ValueError(
                    "positive trust or recipe eligibility requires verified_success"
                )
        elif not self.test_refs:
            raise ValueError("verified_success requires at least one test reference")
        return self


def _model_json(value: Any) -> dict[str, Any]:
    return value.model_dump(mode="json")


def _plan_identity(plan: TaskPlanRecord) -> dict[str, Any]:
    return {
        "id": plan.id,
        "task_text": plan.task_text,
        "workspace_dir": plan.workspace_dir,
        "branch": plan.branch,
        "target_brain": plan.target_brain,
        "execution_mode": plan.execution_mode,
        "check_commands": plan.check_commands,
        "task_archetype": plan.task_archetype,
        "plan_json": plan.plan_json,
    }


class ManagedRunService:
    """Persist and render one reviewed SWE Run using Repository methods."""

    _START_EVENT = "managed_run_started"
    _RECEIPT_EVENT = "managed_mining_receipt_linked"
    _DECISION_EVENT = "managed_candidate_decision"
    _OUTCOME_EVENT = "managed_outcome_classified"

    def __init__(self, repository: Any):
        self.repository = repository

    async def _context(self, run_id: str) -> tuple[RunConnectome, TaskPlanRecord]:
        connectome = await self.repository.get_run_connectome(run_id)
        if connectome is None:
            raise ValueError(f"unknown managed run: {run_id}")
        starts = [
            event
            for event in await self.repository.list_run_events(run_id)
            if event.event_type == self._START_EVENT
        ]
        if len(starts) != 1 or not starts[0].payload.get("plan_id"):
            raise ValueError(f"run is not bound to exactly one managed plan: {run_id}")
        plan = await self.repository.get_task_plan(str(starts[0].payload["plan_id"]))
        if plan is None:
            raise ValueError(f"managed run plan is missing: {starts[0].payload['plan_id']}")
        if connectome.task_archetype != plan.task_archetype:
            raise ValueError("managed run and plan task archetypes do not match")
        return connectome, plan

    async def start_run(self, run_id: str, plan: TaskPlanRecord) -> RunConnectome:
        if not run_id.strip():
            raise ValueError("run_id must not be empty")
        existing = await self.repository.get_run_connectome(run_id)
        if existing is not None:
            _connectome, saved_plan = await self._context(run_id)
            if _plan_identity(saved_plan) != _plan_identity(plan):
                raise ValueError("managed run already belongs to a different plan")
            return existing

        saved_plan = await self.repository.get_task_plan(plan.id)
        if saved_plan is not None and _plan_identity(saved_plan) != _plan_identity(plan):
            raise ValueError("plan id already exists with different content")
        await self.repository.save_task_plan(plan)
        connectome = await self.repository.save_run_connectome(
            RunConnectome(
                run_id=run_id,
                task_archetype=plan.task_archetype,
                status="planning",
            )
        )
        await self.repository.save_run_connectome_edge(
            connectome.id,
            source_node=f"plan:{plan.id}",
            target_node=f"run:{run_id}",
            edge_type="managed_plan",
            metadata={"plan_id": plan.id},
        )
        await self.repository.save_run_event(
            RunEvent(
                run_id=run_id,
                event_type=self._START_EVENT,
                payload={"plan_id": plan.id},
            )
        )
        return connectome

    async def link_mining_receipt(
        self, run_id: str, receipt: MiningReceiptLink
    ) -> RunEvent:
        await self._context(run_id)
        existing = [
            event
            for event in await self.repository.list_run_events(run_id)
            if event.event_type == self._RECEIPT_EVENT
            and event.payload.get("receipt_id") == receipt.receipt_id
        ]
        payload = receipt.model_dump(mode="json")
        if existing:
            if len(existing) != 1 or existing[0].payload != payload:
                raise ValueError("mining receipt id is already bound to different evidence")
            return existing[0]
        return await self.repository.save_run_event(
            RunEvent(run_id=run_id, event_type=self._RECEIPT_EVENT, payload=payload)
        )

    async def record_candidate_decision(
        self, run_id: str, decision: CandidateDecision
    ) -> RunEvent:
        await self._context(run_id)
        if decision.decision is SelectionDecision.SELECTED:
            card = await self.repository.get_component_card(decision.candidate_id)
            if card is None:
                raise ValueError("selected candidate does not exist in component cards")
        return await self.repository.save_run_event(
            RunEvent(
                run_id=run_id,
                slot_id=decision.slot_id,
                event_type=self._DECISION_EVENT,
                payload=decision.model_dump(mode="json"),
            )
        )

    async def link_packet_pair(self, run_id: str, packet_id: str) -> PairEvent:
        connectome, plan = await self._context(run_id)
        packet = await self.repository.get_application_packet(packet_id)
        if packet is None:
            raise ValueError(f"unknown application packet: {packet_id}")
        if packet.plan_id != plan.id or packet.task_archetype != plan.task_archetype:
            raise ValueError("application packet does not belong to the managed plan")
        if packet.status.value not in {"approved", "executing", "verified"}:
            raise ValueError("application packet must be approved before pairing")
        if packet.slot.slot_id not in plan.approved_slot_ids:
            raise ValueError("application packet slot is not approved by the managed plan")
        decisions = [
            event
            for event in await self.repository.list_run_events(run_id)
            if event.event_type == self._DECISION_EVENT
            and event.payload.get("candidate_id") == packet.selected.component_id
            and event.payload.get("slot_id") == packet.slot.slot_id
        ]
        if (
            not decisions
            or decisions[-1].payload.get("decision")
            != SelectionDecision.SELECTED.value
        ):
            raise ValueError("packet component lacks a current selected decision")

        existing = await self.repository.list_run_pair_events(run_id)
        same_slot = [event for event in existing if event.slot_id == packet.slot.slot_id]
        if same_slot:
            pair = same_slot[-1]
            if pair.packet_id == packet_id and pair.component_id == packet.selected.component_id:
                return pair
            raise ValueError("managed run slot is already paired to different evidence")

        pair = await self.repository.save_pair_event(
            PairEvent(
                run_id=run_id,
                slot_id=packet.slot.slot_id,
                slot_barcode=packet.slot.slot_barcode,
                packet_id=packet.packet_id,
                component_id=packet.selected.component_id,
                source_barcode=packet.selected.receipt.source_barcode,
                confidence=packet.selected.confidence,
                confidence_basis=packet.selected.confidence_basis,
            )
        )
        await self.repository.save_run_connectome_edge(
            connectome.id,
            source_node=packet.selected.component_id,
            target_node=packet.slot.slot_id,
            edge_type="selected_for_slot",
            metadata={"packet_id": packet.packet_id, "pair_id": pair.id},
        )
        return pair

    async def record_landing(
        self,
        run_id: str,
        *,
        packet_id: str,
        slot_id: str,
        file_path: str,
        origin: LandingOrigin,
        symbol: str | None = None,
        diff_hunk_id: str | None = None,
    ) -> LandingEvent:
        await self._context(run_id)
        relative = PurePosixPath(file_path)
        if not file_path or relative.is_absolute() or ".." in relative.parts:
            raise ValueError("landing file_path must be a safe target-relative path")
        pairs = await self.repository.list_run_pair_events(run_id)
        if not any(
            pair.packet_id == packet_id and pair.slot_id == slot_id for pair in pairs
        ):
            raise ValueError("landing does not match a managed packet/slot pair")
        return await self.repository.save_landing_event(
            LandingEvent(
                run_id=run_id,
                slot_id=slot_id,
                packet_id=packet_id,
                file_path=file_path,
                symbol=symbol,
                diff_hunk_id=diff_hunk_id,
                origin=origin,
            )
        )

    async def record_outcome(
        self,
        run_id: str,
        *,
        packet_id: str,
        slot_id: str,
        outcome: ManagedOutcome,
    ) -> OutcomeEvent:
        connectome, _plan = await self._context(run_id)
        pairs = await self.repository.list_run_pair_events(run_id)
        matching_pairs = [
            pair
            for pair in pairs
            if pair.packet_id == packet_id and pair.slot_id == slot_id
        ]
        if len(matching_pairs) != 1:
            raise ValueError("outcome does not match exactly one managed packet/slot pair")

        classified = [
            event
            for event in await self.repository.list_run_events(run_id)
            if event.event_type == self._OUTCOME_EVENT
            and event.payload.get("packet_id") == packet_id
            and event.slot_id == slot_id
        ]
        if classified:
            latest_id = classified[-1].payload.get("outcome_id")
            if outcome.supersedes_outcome_id != latest_id:
                raise ValueError(
                    "a corrected outcome must explicitly supersede the latest outcome"
                )
        elif outcome.supersedes_outcome_id is not None:
            raise ValueError("superseded outcome does not exist in this managed run")

        typed = OutcomeEvent(
            run_id=run_id,
            slot_id=slot_id,
            packet_id=packet_id,
            success=outcome.status is OutcomeStatus.VERIFIED_SUCCESS,
            verifier_findings=outcome.verifier_findings,
            test_refs=outcome.test_refs,
            negative_memory_updates=outcome.negative_memory_updates,
            recipe_eligible=outcome.recipe_eligible,
        )
        await self.repository.save_outcome_event(typed)
        await self.repository.save_run_event(
            RunEvent(
                run_id=run_id,
                slot_id=slot_id,
                event_type=self._OUTCOME_EVENT,
                payload={
                    "outcome_id": typed.id,
                    "packet_id": packet_id,
                    "status": outcome.status.value,
                    "trust_delta": outcome.trust_delta,
                    "supersedes_outcome_id": outcome.supersedes_outcome_id,
                },
            )
        )
        component_id = matching_pairs[0].component_id
        if outcome.status is OutcomeStatus.VERIFIED_SUCCESS:
            await self.repository.update_component_outcome(component_id, True)
        elif outcome.status is OutcomeStatus.VERIFIED_FAILURE:
            await self.repository.update_component_outcome(component_id, False)
        connectome.status = outcome.status.value
        await self.repository.save_run_connectome(connectome)
        return typed

    async def source_to_outcome_report(self, run_id: str) -> dict[str, Any]:
        connectome, plan = await self._context(run_id)
        events = await self.repository.list_run_events(run_id)
        pairs = await self.repository.list_run_pair_events(run_id)
        landings = await self.repository.list_run_landing_events(run_id)
        typed_outcomes = await self.repository.list_run_outcome_events(run_id)
        typed_by_id = {event.id: event for event in typed_outcomes}

        receipts = [
            event.payload
            for event in events
            if event.event_type == self._RECEIPT_EVENT
        ]
        decisions = [
            event.payload
            for event in events
            if event.event_type == self._DECISION_EVENT
        ]
        outcomes: list[dict[str, Any]] = []
        active: dict[str, dict[str, Any]] = {}
        for event in events:
            if event.event_type != self._OUTCOME_EVENT:
                continue
            outcome_id = str(event.payload.get("outcome_id", ""))
            typed = typed_by_id.get(outcome_id)
            if typed is None:
                raise ValueError(
                    "managed outcome classification is missing typed row: "
                    f"{outcome_id}"
                )
            rendered = _model_json(typed)
            rendered.update(
                {
                    "status": event.payload["status"],
                    "trust_delta": event.payload["trust_delta"],
                    "supersedes_outcome_id": event.payload.get("supersedes_outcome_id"),
                }
            )
            outcomes.append(rendered)
            active[typed.slot_id] = rendered

        return {
            "schema_version": 1,
            "run_id": run_id,
            "status": connectome.status,
            "plan": _model_json(plan),
            "mining_receipts": receipts,
            "candidate_decisions": decisions,
            "pairs": [_model_json(pair) for pair in pairs],
            "landings": [_model_json(landing) for landing in landings],
            "outcomes": outcomes,
            "active_outcomes": active,
            "positive_evidence_count": sum(
                item["status"] == OutcomeStatus.VERIFIED_SUCCESS.value
                for item in active.values()
            ),
        }
