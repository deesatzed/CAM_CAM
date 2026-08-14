from __future__ import annotations

import uuid

from claw.core.models import (
    AdaptationBurden,
    ApplicationPacket,
    CandidateSummary,
    ComponentCard,
    ComponentFit,
    ComponentLineage,
    CoverageState,
    ExpectedLandingSite,
    FitBucket,
    GovernancePolicy,
    LandingEvent,
    LandingOrigin,
    OutcomeEvent,
    PacketStatus,
    PairEvent,
    ProofGate,
    Receipt,
    RunConnectome,
    RunEvent,
    RunActionAudit,
    RunSlotExecution,
    SlotRisk,
    SlotSpec,
    TaskPlanRecord,
    TransferMode,
)


async def test_camseq_foundation_round_trip(repository):
    lineage = ComponentLineage(
        family_barcode="fam_retry_with_backoff",
        canonical_content_hash="sha256:abc123",
        canonical_title="Retry Helper",
        language="python",
    )
    await repository.upsert_component_lineage(lineage)

    receipt = Receipt(
        source_barcode="src_retry_001",
        family_barcode=lineage.family_barcode,
        lineage_id=lineage.id,
        repo="org/service",
        commit="deadbeef",
        file_path="app/retry.py",
        symbol="with_retry",
        line_start=10,
        line_end=42,
        content_hash="sha256:abc123",
        provenance_precision="precise_symbol",
    )
    card = ComponentCard(
        methodology_id=None,
        title="Retry With Backoff",
        component_type="retry_helper",
        abstract_jobs=["retry_with_backoff"],
        receipt=receipt,
        language="python",
        frameworks=["requests"],
        constraints=["sync"],
        applicability=["HTTP client retries"],
        keywords=["retry", "backoff"],
        coverage_state=CoverageState.COVERED,
    )
    saved_card = await repository.upsert_component_card(card)
    assert saved_card.receipt.source_barcode == receipt.source_barcode

    fit = ComponentFit(
        component_id=saved_card.id,
        task_archetype="oauth_session_management",
        component_type=saved_card.component_type,
        slot_signature="token_refresh",
        fit_bucket=FitBucket.WILL_HELP,
        transfer_mode=TransferMode.DIRECT_FIT,
        confidence=0.82,
        confidence_basis=["family_match", "exact_hash"],
        evidence_count=2,
    )
    await repository.save_component_fit(fit)
    fit_rows = await repository.find_component_fit(
        task_archetype="oauth_session_management",
        slot_signature="token_refresh",
        component_type=saved_card.component_type,
    )
    assert fit_rows
    assert fit_rows[0].fit_bucket == FitBucket.WILL_HELP

    slot = SlotSpec(
        slot_id="slot_refresh",
        slot_barcode="slot_barcode_refresh",
        name="token_refresh",
        abstract_job="retry_with_backoff",
        risk=SlotRisk.CRITICAL,
        constraints=["async"],
        target_stack=["python", "httpx"],
        proof_expectations=["tests", "verifier"],
    )
    candidate = CandidateSummary(
        component_id=saved_card.id,
        title=saved_card.title,
        fit_bucket=FitBucket.WILL_HELP,
        transfer_mode=TransferMode.DIRECT_FIT,
        confidence=0.82,
        confidence_basis=["family_match", "exact_hash"],
        receipt=saved_card.receipt,
        why_fit=["same abstract job"],
        adaptation_burden=AdaptationBurden.MEDIUM,
    )
    packet = ApplicationPacket(
        packet_id=f"pkt_{uuid.uuid4().hex[:8]}",
        plan_id="plan_001",
        task_archetype="oauth_session_management",
        slot=slot,
        status=PacketStatus.REVIEW_REQUIRED,
        selected=candidate,
        runner_ups=[],
        no_viable_runner_up_reason="single strong lineage in seed data",
        why_selected=["best exact lineage available"],
        proof_plan=[ProofGate(gate_id="tests", gate_type="tests", required=True)],
        expected_landing_sites=[
            ExpectedLandingSite(file_path="app/auth/session.py", symbol="refresh_session")
        ],
        reviewer_required=True,
        review_required_reasons=["critical_slot"],
        confidence_basis=["seeded_evidence"],
        coverage_state=CoverageState.WEAK,
    )
    await repository.save_application_packet(packet)

    fetched_packet = await repository.get_application_packet(packet.packet_id)
    assert fetched_packet is not None
    assert fetched_packet.slot.name == "token_refresh"
    assert fetched_packet.selected.component_id == saved_card.id

    summaries = await repository.list_packets_for_plan("plan_001")
    assert len(summaries) == 1
    assert summaries[0].selected_component_id == saved_card.id

    plan_record = TaskPlanRecord(
        id="plan_001",
        task_text="Add OAuth session handling",
        task_archetype="oauth_session_management",
        archetype_confidence=0.86,
        status="review_required",
        summary={"total_slots": 1, "critical_slots": 1, "weak_evidence_slots": 1},
        approved_slot_ids=[],
        plan_json={"plan_id": "plan_001", "slots": [{"slot_id": slot.slot_id}]},
    )
    await repository.save_task_plan(plan_record)
    loaded_plan = await repository.get_task_plan("plan_001")
    assert loaded_plan is not None
    assert loaded_plan.task_archetype == "oauth_session_management"
    await repository.save_slot_instance(slot, task_archetype="oauth_session_management")

    pair = PairEvent(
        run_id="run_001",
        slot_id=slot.slot_id,
        slot_barcode=slot.slot_barcode,
        packet_id=packet.packet_id,
        component_id=saved_card.id,
        source_barcode=saved_card.receipt.source_barcode,
        confidence=0.82,
        confidence_basis=["selected_packet"],
    )
    await repository.save_pair_event(pair)

    landing = LandingEvent(
        run_id="run_001",
        slot_id=slot.slot_id,
        packet_id=packet.packet_id,
        file_path="app/auth/session.py",
        symbol="refresh_session",
        diff_hunk_id="hunk_1",
        origin=LandingOrigin.ADAPTED_COMPONENT,
    )
    await repository.save_landing_event(landing)

    outcome = OutcomeEvent(
        run_id="run_001",
        slot_id=slot.slot_id,
        packet_id=packet.packet_id,
        success=True,
        verifier_findings=[],
        test_refs=["tests/test_auth.py::test_refresh"],
        recipe_eligible=False,
    )
    await repository.save_outcome_event(outcome)
    persisted_outcomes = await repository.list_run_outcome_events("run_001")
    assert persisted_outcomes[0].success is True
    assert persisted_outcomes[0].recipe_eligible is False

    connectome = RunConnectome(
        run_id="run_001",
        task_archetype="oauth_session_management",
        status="verified",
    )
    saved_connectome = await repository.save_run_connectome(connectome)
    await repository.save_run_connectome_edge(
        saved_connectome.id,
        source_node=slot.slot_id,
        target_node=saved_card.id,
        edge_type="paired",
        metadata={"packet_id": packet.packet_id},
    )

    assert len(await repository.list_run_pair_events("run_001")) == 1
    assert len(await repository.list_run_landing_events("run_001")) == 1
    assert len(await repository.list_run_outcome_events("run_001")) == 1
    assert await repository.get_run_connectome("run_001") is not None
    assert len(await repository.list_run_connectome_edges(saved_connectome.id)) == 1

    run_slot = RunSlotExecution(
        run_id="run_001",
        slot_id=slot.slot_id,
        packet_id=packet.packet_id,
        selected_component_id=saved_card.id,
        status="executing",
        current_step="verify",
        retry_count=1,
        last_retry_detail="style_match: mismatch",
        replacement_count=0,
    )
    await repository.save_run_slot_execution(run_slot)
    saved_slots = await repository.list_run_slot_executions("run_001")
    assert len(saved_slots) == 1
    assert saved_slots[0].slot_id == slot.slot_id
    assert saved_slots[0].current_step == "verify"

    run_event = RunEvent(
        run_id="run_001",
        slot_id=slot.slot_id,
        event_type="slot_paused",
        payload={"current_step": "verify"},
    )
    await repository.save_run_event(run_event)
    saved_events = await repository.list_run_events("run_001")
    assert len(saved_events) == 1
    assert saved_events[0].event_type == "slot_paused"

    audit = RunActionAudit(
        run_id="run_001",
        slot_id=slot.slot_id,
        action_type="block_slot",
        reason="manual intervention",
        action_payload={"status": "blocked"},
    )
    await repository.save_run_action_audit(audit)
    saved_audits = await repository.list_run_action_audits("run_001")
    assert len(saved_audits) == 1
    assert saved_audits[0].action_type == "block_slot"

    policy = GovernancePolicy(
        run_id="run_001",
        task_archetype="oauth_session_management",
        slot_id=slot.slot_id,
        family_barcode=saved_card.receipt.family_barcode,
        policy_kind="family_policy",
        severity="high",
        reason="Repeated family bans in async refresh slots",
        recommendation="Quarantine the family until direct-fit evidence improves.",
        evidence_json={"source": "distill"},
    )
    await repository.save_governance_policy(policy)
    saved_policies = await repository.list_governance_policies(active_only=True)
    assert len(saved_policies) == 1
    assert saved_policies[0].policy_kind == "family_policy"
