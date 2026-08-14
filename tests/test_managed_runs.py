from __future__ import annotations

import json

import pytest

from claw.core.models import (
    AdaptationBurden,
    ApplicationPacket,
    CandidateSummary,
    ComponentCard,
    ComponentLineage,
    CoverageState,
    ExpectedLandingSite,
    FitBucket,
    LandingOrigin,
    PacketStatus,
    ProofGate,
    Receipt,
    SlotRisk,
    SlotSpec,
    TaskPlanRecord,
    TransferMode,
)
from claw.managed_runs import (
    AssessmentLabel,
    CandidateDecision,
    ManagedOutcome,
    ManagedRunService,
    MiningReceiptLink,
    OutcomeStatus,
    SelectionDecision,
)


async def _seed_packet(repository) -> tuple[TaskPlanRecord, ApplicationPacket, ComponentCard]:
    lineage = ComponentLineage(
        family_barcode="fam_retry",
        canonical_content_hash="sha256:component",
        canonical_title="Retry Helper",
        language="python",
    )
    await repository.upsert_component_lineage(lineage)
    card = await repository.upsert_component_card(
        ComponentCard(
            title="Retry Helper",
            component_type="retry_helper",
            abstract_jobs=["retry_with_backoff"],
            receipt=Receipt(
                source_barcode="source:retry",
                family_barcode=lineage.family_barcode,
                lineage_id=lineage.id,
                repo="example/donor",
                commit="abc123",
                file_path="src/retry.py",
                symbol="retry",
                line_start=10,
                line_end=42,
                content_hash="sha256:component",
                provenance_precision="precise_symbol",
            ),
            language="python",
            frameworks=["httpx"],
            constraints=["async"],
            applicability=["HTTP retries"],
            keywords=["retry", "backoff"],
            coverage_state=CoverageState.COVERED,
        )
    )
    slot = SlotSpec(
        slot_id="slot_retry",
        slot_barcode="slot:retry",
        name="retry transport",
        abstract_job="retry_with_backoff",
        risk=SlotRisk.NORMAL,
        constraints=["async"],
        target_stack=["python", "httpx"],
        proof_expectations=["tests"],
    )
    selected = CandidateSummary(
        component_id=card.id,
        title=card.title,
        fit_bucket=FitBucket.WILL_HELP,
        transfer_mode=TransferMode.DIRECT_FIT,
        confidence=0.9,
        confidence_basis=["exact source receipt"],
        receipt=card.receipt,
        why_fit=["same abstract job"],
        adaptation_burden=AdaptationBurden.LOW,
    )
    packet = ApplicationPacket(
        packet_id="packet_retry",
        plan_id="plan_retry",
        task_archetype="service_hardening",
        slot=slot,
        status=PacketStatus.APPROVED,
        selected=selected,
        why_selected=["direct precedent"],
        proof_plan=[ProofGate(gate_id="tests", gate_type="tests", required=True)],
        expected_landing_sites=[
            ExpectedLandingSite(file_path="src/client.py", symbol="request")
        ],
        confidence_basis=["precise source receipt"],
        coverage_state=CoverageState.COVERED,
    )
    await repository.save_application_packet(packet)
    plan = TaskPlanRecord(
        id="plan_retry",
        task_text="Harden the service HTTP client",
        workspace_dir="/tmp/target",
        branch="feature/retry",
        task_archetype="service_hardening",
        archetype_confidence=0.85,
        status="reviewed",
        summary={"total_slots": 1},
        approved_slot_ids=[slot.slot_id],
        plan_json={"plan_id": "plan_retry", "slots": [{"slot_id": slot.slot_id}]},
    )
    return plan, packet, card


async def test_managed_run_persists_source_to_outcome_chain(repository) -> None:
    plan, packet, card = await _seed_packet(repository)
    service = ManagedRunService(repository)

    started = await service.start_run("run_retry", plan)
    continued = await service.start_run("run_retry", plan)
    assert continued.run_id == started.run_id == "run_retry"

    receipt = MiningReceiptLink(
        receipt_id="mine-20260814",
        receipt_path="/tmp/receipts/mine-20260814.json",
        receipt_sha256="a" * 64,
        source_repositories=["example/donor@abc123"],
    )
    await service.link_mining_receipt("run_retry", receipt)

    decisions = [
        CandidateDecision(
            candidate_id=card.id,
            label=AssessmentLabel.DIRECT_PRECEDENT,
            decision=SelectionDecision.SELECTED,
            reason="Same HTTP retry boundary.",
            provenance=["example/donor@abc123:src/retry.py:retry"],
            limitations=["Adapt sync timing to async cancellation."],
            slot_id=packet.slot.slot_id,
        ),
        CandidateDecision(
            candidate_id="candidate_rejected",
            label=AssessmentLabel.TRANSFERABLE_ANALOGY,
            decision=SelectionDecision.REJECTED,
            reason="Assumes a blocking transport.",
            provenance=["example/old-client@def456:retry.go"],
            limitations=["Wrong runtime and cancellation semantics."],
        ),
        CandidateDecision(
            candidate_id="candidate_deferred",
            label=AssessmentLabel.NEW_HYPOTHESIS,
            decision=SelectionDecision.DEFERRED,
            reason="Potential adaptive backoff needs evidence.",
            provenance=["hypothesis:adaptive-backoff"],
            limitations=["Not supported by current mining evidence."],
        ),
        CandidateDecision(
            candidate_id="candidate_inspect",
            label=AssessmentLabel.TRANSFERABLE_ANALOGY,
            decision=SelectionDecision.NEEDS_INSPECTION,
            reason="Promising but source precision is only file-level.",
            provenance=["example/other-client@789abc:transport.py"],
            limitations=["Inspect symbol behavior before reuse."],
        ),
    ]
    for decision in decisions:
        await service.record_candidate_decision("run_retry", decision)

    pair = await service.link_packet_pair("run_retry", packet.packet_id)
    landing = await service.record_landing(
        "run_retry",
        packet_id=packet.packet_id,
        slot_id=packet.slot.slot_id,
        file_path="src/client.py",
        symbol="request",
        diff_hunk_id="hunk_retry_1",
        origin=LandingOrigin.ADAPTED_COMPONENT,
    )
    failed = await service.record_outcome(
        "run_retry",
        packet_id=packet.packet_id,
        slot_id=packet.slot.slot_id,
        outcome=ManagedOutcome(
            status=OutcomeStatus.VERIFIED_FAILURE,
            verifier_findings=["retry cancellation test failed"],
            test_refs=["tests/test_client.py::test_retry_cancellation"],
            negative_memory_updates=["Do not swallow CancelledError."],
        ),
    )
    passed = await service.record_outcome(
        "run_retry",
        packet_id=packet.packet_id,
        slot_id=packet.slot.slot_id,
        outcome=ManagedOutcome(
            status=OutcomeStatus.VERIFIED_SUCCESS,
            verifier_findings=[],
            test_refs=["tests/test_client.py::test_retry_cancellation"],
            recipe_eligible=True,
            trust_delta=1,
            supersedes_outcome_id=failed.id,
        ),
    )

    assert pair.component_id == card.id
    assert landing.packet_id == packet.packet_id
    assert failed.success is False
    assert failed.recipe_eligible is False
    assert passed.success is True
    assert passed.recipe_eligible is True
    refreshed = await repository.get_component_card(card.id)
    assert refreshed is not None
    assert refreshed.failure_count == 1
    assert refreshed.success_count == 1

    report = await service.source_to_outcome_report("run_retry")
    assert report["run_id"] == "run_retry"
    assert report["plan"]["id"] == plan.id
    assert report["mining_receipts"] == [receipt.model_dump(mode="json")]
    assert [item["decision"] for item in report["candidate_decisions"]] == [
        "selected",
        "rejected",
        "deferred",
        "needs-inspection",
    ]
    assert report["pairs"][0]["packet_id"] == packet.packet_id
    assert report["landings"][0]["file_path"] == "src/client.py"
    assert [item["status"] for item in report["outcomes"]] == [
        "verified_failure",
        "verified_success",
    ]
    assert report["active_outcomes"][packet.slot.slot_id]["status"] == "verified_success"
    assert report["positive_evidence_count"] == 1
    assert report == await service.source_to_outcome_report("run_retry")


@pytest.mark.parametrize(
    "status",
    [
        OutcomeStatus.VERIFIED_PARTIAL,
        OutcomeStatus.VERIFIED_FAILURE,
        OutcomeStatus.NOT_VERIFIED,
    ],
)
async def test_non_success_outcomes_cannot_create_positive_evidence(
    repository, status: OutcomeStatus
) -> None:
    plan, packet, card = await _seed_packet(repository)
    service = ManagedRunService(repository)
    await service.start_run("run_no_trust", plan)
    await service.record_candidate_decision(
        "run_no_trust",
        CandidateDecision(
            candidate_id=card.id,
            label=AssessmentLabel.DIRECT_PRECEDENT,
            decision=SelectionDecision.SELECTED,
            reason="Candidate selected for the reviewed slot.",
            provenance=["example/donor@abc123:src/retry.py:retry"],
            limitations=[],
            slot_id=packet.slot.slot_id,
        ),
    )
    await service.link_packet_pair("run_no_trust", packet.packet_id)

    with pytest.raises(ValueError, match="positive trust|recipe"):
        await service.record_outcome(
            "run_no_trust",
            packet_id=packet.packet_id,
            slot_id=packet.slot.slot_id,
            outcome=ManagedOutcome(
                status=status,
                verifier_findings=["proof is not a verified success"],
                test_refs=["tests/test_client.py::test_retry"],
                recipe_eligible=True,
                trust_delta=1,
            ),
        )

    assert await repository.list_run_outcome_events("run_no_trust") == []
    unchanged = await repository.get_component_card(card.id)
    assert unchanged is not None
    assert unchanged.success_count == 0
    assert unchanged.failure_count == 0


@pytest.mark.parametrize(
    ("status", "expected_failures"),
    [
        (OutcomeStatus.VERIFIED_PARTIAL, 0),
        (OutcomeStatus.VERIFIED_FAILURE, 1),
        (OutcomeStatus.NOT_VERIFIED, 0),
    ],
)
async def test_non_success_outcomes_remain_typed_negative_or_neutral_evidence(
    repository, status: OutcomeStatus, expected_failures: int
) -> None:
    plan, packet, card = await _seed_packet(repository)
    service = ManagedRunService(repository)
    await service.start_run("run_negative", plan)
    await service.record_candidate_decision(
        "run_negative",
        CandidateDecision(
            candidate_id=card.id,
            label=AssessmentLabel.DIRECT_PRECEDENT,
            decision=SelectionDecision.SELECTED,
            reason="Reviewed selection.",
            provenance=["example/donor@abc123:src/retry.py:retry"],
            slot_id=packet.slot.slot_id,
        ),
    )
    await service.link_packet_pair("run_negative", packet.packet_id)

    typed = await service.record_outcome(
        "run_negative",
        packet_id=packet.packet_id,
        slot_id=packet.slot.slot_id,
        outcome=ManagedOutcome(
            status=status,
            verifier_findings=["proof did not establish complete success"],
            test_refs=["tests/test_client.py::test_retry"],
            negative_memory_updates=["Retain the failed or incomplete proof."],
        ),
    )

    assert typed.success is False
    assert typed.recipe_eligible is False
    refreshed = await repository.get_component_card(card.id)
    assert refreshed is not None
    assert refreshed.success_count == 0
    assert refreshed.failure_count == expected_failures
    report = await service.source_to_outcome_report("run_negative")
    assert report["outcomes"][0]["status"] == status.value
    assert report["positive_evidence_count"] == 0


async def test_unapproved_packet_cannot_be_paired(repository) -> None:
    plan, packet, card = await _seed_packet(repository)
    packet.status = PacketStatus.DRAFT
    await repository.save_application_packet(packet)
    service = ManagedRunService(repository)
    await service.start_run("run_unapproved", plan)
    await service.record_candidate_decision(
        "run_unapproved",
        CandidateDecision(
            candidate_id=card.id,
            label=AssessmentLabel.DIRECT_PRECEDENT,
            decision=SelectionDecision.SELECTED,
            reason="Selection is proposed but its packet is not approved.",
            provenance=["example/donor@abc123:src/retry.py:retry"],
            slot_id=packet.slot.slot_id,
        ),
    )

    with pytest.raises(ValueError, match="approved"):
        await service.link_packet_pair("run_unapproved", packet.packet_id)

    assert await repository.list_run_pair_events("run_unapproved") == []


async def test_corrected_outcome_requires_explicit_latest_supersession(repository) -> None:
    plan, packet, card = await _seed_packet(repository)
    service = ManagedRunService(repository)
    await service.start_run("run_supersede", plan)
    await service.record_candidate_decision(
        "run_supersede",
        CandidateDecision(
            candidate_id=card.id,
            label=AssessmentLabel.DIRECT_PRECEDENT,
            decision=SelectionDecision.SELECTED,
            reason="Reviewed selection.",
            provenance=["example/donor@abc123:src/retry.py:retry"],
            slot_id=packet.slot.slot_id,
        ),
    )
    await service.link_packet_pair("run_supersede", packet.packet_id)
    first = await service.record_outcome(
        "run_supersede",
        packet_id=packet.packet_id,
        slot_id=packet.slot.slot_id,
        outcome=ManagedOutcome(
            status=OutcomeStatus.VERIFIED_FAILURE,
            verifier_findings=["failed"],
            test_refs=["tests/test_client.py::test_retry"],
        ),
    )

    with pytest.raises(ValueError, match="supersede"):
        await service.record_outcome(
            "run_supersede",
            packet_id=packet.packet_id,
            slot_id=packet.slot.slot_id,
            outcome=ManagedOutcome(
                status=OutcomeStatus.VERIFIED_SUCCESS,
                test_refs=["tests/test_client.py::test_retry"],
                trust_delta=1,
            ),
        )

    corrected = await service.record_outcome(
        "run_supersede",
        packet_id=packet.packet_id,
        slot_id=packet.slot.slot_id,
        outcome=ManagedOutcome(
            status=OutcomeStatus.VERIFIED_SUCCESS,
            test_refs=["tests/test_client.py::test_retry"],
            trust_delta=1,
            supersedes_outcome_id=first.id,
        ),
    )
    assert corrected.success is True


def test_hidden_managed_run_cli_uses_one_json_request_argument(monkeypatch) -> None:
    from typer.testing import CliRunner

    import claw.cli._monolith as cli
    from claw.cli import app
    from claw.cli.capability_manifest import build_capability_manifest

    captured: list[tuple[str, str]] = []

    async def fake_managed_run(request_json: str, config: str) -> dict[str, object]:
        captured.append((request_json, config))
        return {"run_id": "run_cli", "operation": "report"}

    monkeypatch.setattr(cli, "_managed_run_async", fake_managed_run)
    request = json.dumps({"operation": "report", "run_id": "run_cli"})
    result = CliRunner().invoke(
        app,
        ["managed-run", request, "--config", "/tmp/claw.toml"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"operation": "report", "run_id": "run_cli"}
    assert captured == [(request, "/tmp/claw.toml")]
    manifest = {item["path"]: item for item in build_capability_manifest(app)["items"]}
    assert manifest["managed-run"] == {
        "path": "managed-run",
        "kind": "command",
        "hidden": True,
    }
