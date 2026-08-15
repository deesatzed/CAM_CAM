"""Managed source-to-outcome runs over the existing CAM-SEQ persistence model.

This module is an orchestration seam for CAM_Codx.  It does not build, edit,
verify, mine, promote, or create a parallel knowledge store.
"""

from __future__ import annotations

import enum
import hashlib
import json
import math
import re
from pathlib import Path, PurePath, PurePosixPath
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from claw.core.models import (
    LandingEvent,
    LandingOrigin,
    OutcomeEvent,
    PacketStatus,
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
    supersedes_decision_id: str | None = None

    @model_validator(mode="after")
    def selected_candidate_names_slot(self) -> "CandidateDecision":
        if self.decision is SelectionDecision.SELECTED and not self.slot_id:
            raise ValueError("a selected candidate must name its target slot_id")
        return self


class VerificationEvidence(BaseModel):
    gate_id: str = Field(min_length=1)
    command_argv: list[str] = Field(min_length=1)
    exit_code: int
    target_path: str = Field(min_length=1)
    target_revision: str = Field(min_length=1)
    plan_id: str | None = None
    plan_sha256: str | None = None
    receipt_path: str = Field(min_length=1)
    receipt_sha256: str

    @field_validator("gate_id", "target_revision")
    @classmethod
    def validate_identity_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("verification identity fields must not be blank")
        return value

    @field_validator("exit_code", mode="before")
    @classmethod
    def validate_exit_code(cls, value: Any) -> int:
        if type(value) is not int:
            raise ValueError("verification exit_code must be an integer")
        return value

    @field_validator("command_argv")
    @classmethod
    def validate_argv(cls, value: list[str]) -> list[str]:
        if not all(isinstance(item, str) and item for item in value):
            raise ValueError("verification command_argv must contain non-empty strings")
        return value

    @field_validator("target_path")
    @classmethod
    def validate_target_path(cls, value: str) -> str:
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("verification target_path must be absolute")
        return str(path.resolve(strict=False))

    @field_validator("receipt_path")
    @classmethod
    def validate_receipt_path(cls, value: str) -> str:
        if not PurePath(value).is_absolute():
            raise ValueError("verification receipt_path must be absolute")
        return value

    @field_validator("receipt_sha256")
    @classmethod
    def validate_receipt_sha256(cls, value: str) -> str:
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError(
                "verification receipt_sha256 must be 64 lowercase hexadecimal characters"
            )
        return value

    @model_validator(mode="after")
    def plan_identity_is_complete_when_supplied(self) -> "VerificationEvidence":
        if (self.plan_id is None) != (self.plan_sha256 is None):
            raise ValueError("verification plan identity must include both plan_id and plan_sha256")
        if self.plan_sha256 is not None and re.fullmatch(r"[0-9a-f]{64}", self.plan_sha256) is None:
            raise ValueError("verification plan_sha256 must be 64 lowercase hexadecimal characters")
        return self


class ManagedOutcome(BaseModel):
    status: OutcomeStatus
    verifier_findings: list[str] = Field(default_factory=list)
    test_refs: list[str] = Field(default_factory=list)
    negative_memory_updates: list[str] = Field(default_factory=list)
    verification_evidence: list[VerificationEvidence] = Field(default_factory=list)
    recipe_eligible: bool = False
    trust_delta: float = 0.0
    supersedes_outcome_id: str | None = None

    @field_validator("trust_delta")
    @classmethod
    def validate_trust_delta(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("trust_delta must be finite")
        if value < -1 or value > 1:
            raise ValueError("trust_delta must be between -1 and 1")
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
    return plan.model_dump(
        mode="json",
        exclude={"created_at", "updated_at"},
    )


def _digest_json(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _stable_id(prefix: str, payload: Any) -> str:
    return f"{prefix}_{_digest_json(payload)[:24]}"


def _read_verified_file(
    path_value: str, expected_sha256: str, label: str
) -> tuple[Path, bytes]:
    path = Path(path_value).expanduser()
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f"{label} must name an existing absolute file")
    try:
        contents = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{label} could not be read") from exc
    actual = hashlib.sha256(contents).hexdigest()
    if actual != expected_sha256:
        raise ValueError(f"{label} digest does not match the stored receipt")
    return path, contents


def _verified_file(path_value: str, expected_sha256: str, label: str) -> Path:
    path, _contents = _read_verified_file(path_value, expected_sha256, label)
    return path


def _verify_execution_receipt(
    evidence: VerificationEvidence,
    plan: TaskPlanRecord,
) -> None:
    """Bind a hashed verification receipt to its exact asserted execution."""
    _path, receipt_bytes = _read_verified_file(
        evidence.receipt_path,
        evidence.receipt_sha256,
        f"verification receipt for gate {evidence.gate_id}",
    )
    try:
        payload = json.loads(receipt_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("verification receipt must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("verification receipt must be one JSON object")
    if payload.get("schema_version") != "cam.verification-receipt.v1":
        raise ValueError("verification receipt has an unsupported schema_version")

    receipt_gate = payload.get("gate_id")
    receipt_argv = payload.get("command_argv")
    receipt_exit = payload.get("exit_code")
    receipt_revision = payload.get("target_revision")
    receipt_plan_id = payload.get("plan_id")
    receipt_plan_sha256 = payload.get("plan_sha256")
    if not isinstance(receipt_gate, str) or not receipt_gate.strip():
        raise ValueError("verification receipt gate_id must be a non-empty string")
    if not isinstance(receipt_argv, list) or not receipt_argv or not all(
        isinstance(item, str) and item for item in receipt_argv
    ):
        raise ValueError("verification receipt command_argv must be a non-empty string list")
    if type(receipt_exit) is not int:
        raise ValueError("verification receipt exit_code must be an integer")
    if not isinstance(receipt_revision, str) or not receipt_revision.strip():
        raise ValueError("verification receipt target_revision must be a non-empty string")
    if not isinstance(receipt_plan_id, str) or not receipt_plan_id.strip():
        raise ValueError("verification receipt lacks managed plan identity")
    if not isinstance(receipt_plan_sha256, str) or re.fullmatch(
        r"[0-9a-f]{64}", receipt_plan_sha256
    ) is None:
        raise ValueError("verification receipt lacks managed plan identity")
    raw_receipt_target = payload.get("target_path")
    if not isinstance(raw_receipt_target, str):
        raise ValueError("verification receipt target_path must be a string")
    receipt_target = Path(raw_receipt_target).expanduser()
    if not receipt_target.is_absolute():
        raise ValueError("verification receipt target_path must be absolute")
    receipt_target_path = str(receipt_target.resolve(strict=False))
    if (
        receipt_gate != evidence.gate_id
        or receipt_argv != evidence.command_argv
        or receipt_exit != evidence.exit_code
        or receipt_target_path != evidence.target_path
        or receipt_revision != evidence.target_revision
    ):
        raise ValueError(
            "verification receipt does not match its gate, argv, exit, target, or revision"
        )

    if plan.workspace_dir is None:
        raise ValueError("verification receipt requires a managed plan target path")
    expected_plan_sha256 = _digest_json(_plan_identity(plan))
    if (
        evidence.plan_id != plan.id
        or evidence.plan_sha256 != expected_plan_sha256
        or receipt_plan_id != plan.id
        or receipt_plan_sha256 != expected_plan_sha256
        or receipt_plan_id != evidence.plan_id
        or receipt_plan_sha256 != evidence.plan_sha256
    ):
        raise ValueError("verification receipt managed plan identity differs from the managed plan")
    plan_target = str(Path(plan.workspace_dir).expanduser().resolve(strict=False))
    plan_revision = plan.plan_json.get("target_revision")
    if not isinstance(plan_revision, str) or not plan_revision:
        raise ValueError("verification receipt requires a managed plan target revision")
    if evidence.target_path != plan_target or evidence.target_revision != plan_revision:
        raise ValueError("verification receipt target identity differs from the managed plan")


def _evidence_delta(status: OutcomeStatus) -> tuple[int, int]:
    if status is OutcomeStatus.VERIFIED_SUCCESS:
        return 1, 0
    if status is OutcomeStatus.VERIFIED_FAILURE:
        return 0, 1
    return 0, 0


def _aggregate_status(
    plan: TaskPlanRecord,
    active_outcomes: dict[str, OutcomeStatus],
) -> str:
    if not active_outcomes:
        return "planning"
    values = list(active_outcomes.values())
    if OutcomeStatus.VERIFIED_FAILURE in values:
        return OutcomeStatus.VERIFIED_FAILURE.value
    if OutcomeStatus.VERIFIED_PARTIAL in values:
        return OutcomeStatus.VERIFIED_PARTIAL.value
    approved = set(plan.approved_slot_ids)
    if approved and approved.issubset(active_outcomes) and all(
        active_outcomes[slot] is OutcomeStatus.VERIFIED_SUCCESS for slot in approved
    ):
        return OutcomeStatus.VERIFIED_SUCCESS.value
    return OutcomeStatus.NOT_VERIFIED.value


class ManagedRunService:
    """Persist and render one reviewed SWE Run using Repository methods."""

    _RECEIPT_EVENT = "managed_mining_receipt_linked"
    _DECISION_EVENT = "managed_candidate_decision"
    _OUTCOME_EVENT = "managed_outcome_classified"

    def __init__(self, repository: Any):
        self.repository = repository

    async def _context(self, run_id: str) -> tuple[RunConnectome, TaskPlanRecord]:
        connectome = await self.repository.get_run_connectome(run_id)
        if connectome is None:
            raise ValueError(f"unknown managed run: {run_id}")
        plan_edges = [
            edge
            for edge in await self.repository.list_run_connectome_edges(connectome.id)
            if edge["edge_type"] == "managed_plan"
        ]
        if len(plan_edges) != 1:
            raise ValueError(f"run is not bound to exactly one managed plan edge: {run_id}")
        try:
            metadata = json.loads(plan_edges[0]["metadata_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("managed plan edge metadata is invalid") from exc
        plan_id = metadata.get("plan_id")
        plan_sha256 = metadata.get("plan_sha256")
        if not isinstance(plan_id, str) or not isinstance(plan_sha256, str):
            raise ValueError("managed plan edge lacks its plan identity and digest")
        plan = await self.repository.get_task_plan(plan_id)
        if plan is None:
            raise ValueError(f"managed run plan is missing: {plan_id}")
        if _digest_json(_plan_identity(plan)) != plan_sha256:
            raise ValueError("managed run plan changed after it was bound")
        if connectome.task_archetype != plan.task_archetype:
            raise ValueError("managed run and plan task archetypes do not match")
        return connectome, plan

    async def start_run(self, run_id: str, plan: TaskPlanRecord) -> RunConnectome:
        if not run_id.strip():
            raise ValueError("run_id must not be empty")
        async with self.repository.engine.transaction():
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
                metadata={
                    "plan_id": plan.id,
                    "plan_sha256": _digest_json(_plan_identity(plan)),
                },
            )
            return connectome

    async def link_mining_receipt(
        self, run_id: str, receipt: MiningReceiptLink
    ) -> RunEvent:
        _verified_file(
            receipt.receipt_path,
            receipt.receipt_sha256,
            "mining receipt path",
        )
        payload = receipt.model_dump(mode="json")
        async with self.repository.engine.transaction():
            await self._context(run_id)
            existing = [
                event
                for event in await self.repository.list_run_events(run_id)
                if event.event_type == self._RECEIPT_EVENT
                and event.payload.get("receipt_id") == receipt.receipt_id
            ]
            if existing:
                if len(existing) != 1 or existing[0].payload != payload:
                    raise ValueError(
                        "mining receipt id is already bound to different evidence"
                    )
                return existing[0]
            return await self.repository.save_run_event(
                RunEvent(
                    id=_stable_id("receipt", {"run_id": run_id, **payload}),
                    run_id=run_id,
                    event_type=self._RECEIPT_EVENT,
                    payload=payload,
                )
            )

    async def record_candidate_decision(
        self, run_id: str, decision: CandidateDecision
    ) -> RunEvent:
        payload = decision.model_dump(mode="json")
        event_id = _stable_id("decision", {"run_id": run_id, **payload})
        async with self.repository.engine.transaction():
            await self._context(run_id)
            if decision.decision is SelectionDecision.SELECTED:
                card = await self.repository.get_component_card(decision.candidate_id)
                if card is None:
                    raise ValueError("selected candidate does not exist in component cards")
            decisions = [
                event
                for event in await self.repository.list_run_events(run_id)
                if event.event_type == self._DECISION_EVENT
            ]
            exact = [event for event in decisions if event.id == event_id]
            if exact:
                if len(exact) != 1 or exact[0].payload != payload:
                    raise ValueError("candidate decision identity collision")
                return exact[0]
            if decision.slot_id is not None:
                slot_history = [
                    event for event in decisions if event.slot_id == decision.slot_id
                ]
                if slot_history:
                    if decision.supersedes_decision_id != slot_history[-1].id:
                        raise ValueError(
                            "a changed slot decision must explicitly supersede the latest decision"
                        )
                elif decision.supersedes_decision_id is not None:
                    raise ValueError("superseded slot decision does not exist")
            elif decision.supersedes_decision_id is not None:
                raise ValueError("decision supersession requires a slot_id")
            return await self.repository.save_run_event(
                RunEvent(
                    id=event_id,
                    run_id=run_id,
                    slot_id=decision.slot_id,
                    event_type=self._DECISION_EVENT,
                    payload=payload,
                )
            )

    async def link_packet_pair(self, run_id: str, packet_id: str) -> PairEvent:
        async with self.repository.engine.transaction():
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
            slot_decisions = [
                event
                for event in await self.repository.list_run_events(run_id)
                if event.event_type == self._DECISION_EVENT
                and event.slot_id == packet.slot.slot_id
            ]
            if (
                not slot_decisions
                or slot_decisions[-1].payload.get("decision")
                != SelectionDecision.SELECTED.value
                or slot_decisions[-1].payload.get("candidate_id")
                != packet.selected.component_id
            ):
                raise ValueError("packet component is not the current slot selection")

            pair_payload = {
                "run_id": run_id,
                "slot_id": packet.slot.slot_id,
                "packet_id": packet.packet_id,
                "component_id": packet.selected.component_id,
            }
            pair_id = _stable_id("pair", pair_payload)
            existing = await self.repository.list_run_pair_events(run_id)
            same_slot = [
                event for event in existing if event.slot_id == packet.slot.slot_id
            ]
            if same_slot:
                pair = same_slot[-1]
                if pair.id != pair_id:
                    raise ValueError(
                        "managed run slot is already paired to different evidence"
                    )
            else:
                pair = await self.repository.save_pair_event(
                    PairEvent(
                        id=pair_id,
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
            edges = await self.repository.list_run_connectome_edges(connectome.id)
            if not any(
                edge["edge_type"] == "selected_for_slot"
                and json.loads(edge["metadata_json"]).get("pair_id") == pair.id
                for edge in edges
            ):
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
        relative = PurePosixPath(file_path)
        if not file_path or relative.is_absolute() or ".." in relative.parts:
            raise ValueError("landing file_path must be a safe target-relative path")
        payload = {
            "run_id": run_id,
            "packet_id": packet_id,
            "slot_id": slot_id,
            "file_path": file_path,
            "symbol": symbol,
            "diff_hunk_id": diff_hunk_id,
            "origin": origin.value,
        }
        landing_id = _stable_id("landing", payload)
        async with self.repository.engine.transaction():
            await self._context(run_id)
            pairs = await self.repository.list_run_pair_events(run_id)
            if not any(
                pair.packet_id == packet_id and pair.slot_id == slot_id
                for pair in pairs
            ):
                raise ValueError("landing does not match a managed packet/slot pair")
            existing = await self.repository.list_run_landing_events(run_id)
            exact = [event for event in existing if event.id == landing_id]
            if exact:
                if len(exact) != 1 or _model_json(exact[0]) | {
                    "created_at": None
                } != payload | {"id": landing_id, "created_at": None}:
                    raise ValueError("landing identity collision")
                return exact[0]
            return await self.repository.save_landing_event(
                LandingEvent(
                    id=landing_id,
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
        outcome_payload = outcome.model_dump(mode="json")
        outcome_id = _stable_id(
            "outcome",
            {
                "run_id": run_id,
                "packet_id": packet_id,
                "slot_id": slot_id,
                "outcome": outcome_payload,
            },
        )
        async with self.repository.engine.transaction():
            connectome, plan = await self._context(run_id)
            packet = await self.repository.get_application_packet(packet_id)
            if packet is None or packet.slot.slot_id != slot_id:
                raise ValueError("outcome packet/slot identity is missing or inconsistent")
            pairs = await self.repository.list_run_pair_events(run_id)
            matching_pairs = [
                pair
                for pair in pairs
                if pair.packet_id == packet_id and pair.slot_id == slot_id
            ]
            if len(matching_pairs) != 1:
                raise ValueError(
                    "outcome does not match exactly one managed packet/slot pair"
                )
            if (
                packet.plan_id != plan.id
                or packet.task_archetype != plan.task_archetype
                or packet.selected.component_id != matching_pairs[0].component_id
            ):
                raise ValueError("outcome packet changed after the managed pair was bound")

            if outcome.status is OutcomeStatus.VERIFIED_SUCCESS:
                if packet.status is not PacketStatus.VERIFIED:
                    raise ValueError(
                        "positive evidence requires a stored verified application packet"
                    )
                required_gates = {
                    gate.gate_id
                    for gate in packet.proof_plan
                    if gate.required
                }
                passed_gates = {
                    gate.gate_id
                    for gate in packet.proof_plan
                    if gate.required and gate.status == "pass"
                }
                if required_gates != passed_gates:
                    raise ValueError(
                        "positive evidence requires every stored packet proof gate to pass"
                    )
                evidence_gates: set[str] = set()
                for evidence in outcome.verification_evidence:
                    _verify_execution_receipt(evidence, plan)
                    if evidence.exit_code != 0:
                        raise ValueError("verified_success evidence must have exit_code 0")
                    if evidence.gate_id in evidence_gates:
                        raise ValueError(
                            "positive evidence cannot duplicate a verification gate"
                        )
                    evidence_gates.add(evidence.gate_id)
                if not required_gates or not required_gates.issubset(evidence_gates):
                    raise ValueError(
                        "positive evidence requires receipt-backed proof for every gate"
                    )

            events = await self.repository.list_run_events(run_id)
            all_classified = [
                event
                for event in events
                if event.event_type == self._OUTCOME_EVENT
            ]
            classified = [
                event
                for event in all_classified
                if event.payload.get("packet_id") == packet_id
                and event.slot_id == slot_id
            ]
            typed_outcomes = await self.repository.list_run_outcome_events(run_id)
            typed_by_id = {event.id: event for event in typed_outcomes}
            exact = [event for event in classified if event.payload.get("outcome_id") == outcome_id]
            if exact:
                typed = typed_by_id.get(outcome_id)
                if len(exact) != 1 or typed is None:
                    raise ValueError("managed outcome identity is incomplete or duplicated")
                return typed
            unclassified = [
                event
                for event in typed_outcomes
                if event.packet_id == packet_id
                and event.slot_id == slot_id
                and event.id not in {item.payload.get("outcome_id") for item in classified}
            ]
            if unclassified:
                raise ValueError("unclassified typed outcome requires operator recovery")

            previous_status: OutcomeStatus | None = None
            if classified:
                latest = classified[-1]
                latest_id = latest.payload.get("outcome_id")
                previous_status = OutcomeStatus(latest.payload.get("status"))
                if outcome.supersedes_outcome_id != latest_id:
                    raise ValueError(
                        "a corrected outcome must explicitly supersede the latest outcome"
                    )
                if previous_status is OutcomeStatus.VERIFIED_SUCCESS:
                    raise ValueError(
                        "verified_success is final for this run; reverify in a new run"
                    )
                if outcome.status is not OutcomeStatus.VERIFIED_SUCCESS:
                    raise ValueError(
                        "only verified_success may correct a prior non-success outcome"
                    )
            elif outcome.supersedes_outcome_id is not None:
                raise ValueError("superseded outcome does not exist in this managed run")

            typed = OutcomeEvent(
                id=outcome_id,
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
            classification = RunEvent(
                id=_stable_id("outcome-classification", outcome_id),
                run_id=run_id,
                slot_id=slot_id,
                event_type=self._OUTCOME_EVENT,
                payload={
                    "outcome_id": typed.id,
                    "packet_id": packet_id,
                    "status": outcome.status.value,
                    "trust_delta": outcome.trust_delta,
                    "recipe_eligible": outcome.recipe_eligible,
                    "verification_evidence": [
                        item.model_dump(mode="json")
                        for item in outcome.verification_evidence
                    ],
                    "supersedes_outcome_id": outcome.supersedes_outcome_id,
                },
            )
            await self.repository.save_run_event(classification)

            old_success, old_failure = (
                _evidence_delta(previous_status)
                if previous_status is not None
                else (0, 0)
            )
            new_success, new_failure = _evidence_delta(outcome.status)
            await self.repository.adjust_component_outcome_counts(
                matching_pairs[0].component_id,
                success_delta=new_success - old_success,
                failure_delta=new_failure - old_failure,
            )
            active_statuses: dict[str, OutcomeStatus] = {}
            for event in [*all_classified, classification]:
                active_statuses[event.slot_id] = OutcomeStatus(event.payload["status"])
            connectome.status = _aggregate_status(plan, active_statuses)
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
                    "recipe_eligible": event.payload.get("recipe_eligible", False),
                    "verification_evidence": event.payload.get(
                        "verification_evidence", []
                    ),
                    "supersedes_outcome_id": event.payload.get("supersedes_outcome_id"),
                }
            )
            outcomes.append(rendered)
            active[typed.slot_id] = rendered

        aggregate = _aggregate_status(
            plan,
            {
                slot_id: OutcomeStatus(item["status"])
                for slot_id, item in active.items()
            },
        )
        if connectome.status != aggregate:
            raise ValueError(
                "managed run stored status disagrees with its active slot outcomes"
            )

        return {
            "schema_version": 1,
            "run_id": run_id,
            "status": aggregate,
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
