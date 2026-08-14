from __future__ import annotations

import hashlib
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
    VerificationEvidence,
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


def _verification_evidence(tmp_path, name: str = "verify.json") -> VerificationEvidence:
    receipt = tmp_path / name
    receipt.write_text('{"exit_code":0,"gate_id":"tests"}\n', encoding="utf-8")
    return VerificationEvidence(
        gate_id="tests",
        command_argv=["python", "-m", "pytest", "-q", "tests/test_client.py"],
        exit_code=0,
        receipt_path=str(receipt),
        receipt_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
    )


async def _mark_packet_verified(repository, packet: ApplicationPacket) -> None:
    packet.status = PacketStatus.VERIFIED
    for gate in packet.proof_plan:
        if gate.required:
            gate.status = "pass"
            gate.details = ["receipt-backed test command passed"]
    await repository.save_application_packet(packet)


async def test_managed_run_persists_source_to_outcome_chain(repository, tmp_path) -> None:
    plan, packet, card = await _seed_packet(repository)
    service = ManagedRunService(repository)

    started = await service.start_run("run_retry", plan)
    continued = await service.start_run("run_retry", plan)
    assert continued.run_id == started.run_id == "run_retry"

    mining_receipt = tmp_path / "mine-20260814.json"
    mining_receipt.write_text('{"run_id":"mine-20260814"}\n', encoding="utf-8")
    receipt = MiningReceiptLink(
        receipt_id="mine-20260814",
        receipt_path=str(mining_receipt),
        receipt_sha256=hashlib.sha256(mining_receipt.read_bytes()).hexdigest(),
        source_repositories=["example/donor@abc123"],
    )
    linked_receipt = await service.link_mining_receipt("run_retry", receipt)
    assert (await service.link_mining_receipt("run_retry", receipt)).id == linked_receipt.id

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
    persisted_decisions = [
        await service.record_candidate_decision("run_retry", decision)
        for decision in decisions
    ]
    assert (
        await service.record_candidate_decision("run_retry", decisions[0])
    ).id == persisted_decisions[0].id

    pair = await service.link_packet_pair("run_retry", packet.packet_id)
    assert (await service.link_packet_pair("run_retry", packet.packet_id)).id == pair.id
    landing = await service.record_landing(
        "run_retry",
        packet_id=packet.packet_id,
        slot_id=packet.slot.slot_id,
        file_path="src/client.py",
        symbol="request",
        diff_hunk_id="hunk_retry_1",
        origin=LandingOrigin.ADAPTED_COMPONENT,
    )
    repeated_landing = await service.record_landing(
        "run_retry",
        packet_id=packet.packet_id,
        slot_id=packet.slot.slot_id,
        file_path="src/client.py",
        symbol="request",
        diff_hunk_id="hunk_retry_1",
        origin=LandingOrigin.ADAPTED_COMPONENT,
    )
    assert repeated_landing.id == landing.id
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
    await _mark_packet_verified(repository, packet)
    passed = await service.record_outcome(
        "run_retry",
        packet_id=packet.packet_id,
        slot_id=packet.slot.slot_id,
        outcome=ManagedOutcome(
            status=OutcomeStatus.VERIFIED_SUCCESS,
            verifier_findings=[],
            test_refs=["tests/test_client.py::test_retry_cancellation"],
            verification_evidence=[_verification_evidence(tmp_path)],
            recipe_eligible=True,
            trust_delta=1,
            supersedes_outcome_id=failed.id,
        ),
    )
    repeated_passed = await service.record_outcome(
        "run_retry",
        packet_id=packet.packet_id,
        slot_id=packet.slot.slot_id,
        outcome=ManagedOutcome(
            status=OutcomeStatus.VERIFIED_SUCCESS,
            verifier_findings=[],
            test_refs=["tests/test_client.py::test_retry_cancellation"],
            verification_evidence=[_verification_evidence(tmp_path)],
            recipe_eligible=True,
            trust_delta=1,
            supersedes_outcome_id=failed.id,
        ),
    )
    assert repeated_passed.id == passed.id

    assert pair.component_id == card.id
    assert landing.packet_id == packet.packet_id
    assert failed.success is False
    assert failed.recipe_eligible is False
    assert passed.success is True
    assert passed.recipe_eligible is True
    refreshed = await repository.get_component_card(card.id)
    assert refreshed is not None
    assert refreshed.failure_count == 0
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


async def test_mining_receipt_digest_must_match_existing_file(
    repository, tmp_path
) -> None:
    plan, _packet, _card = await _seed_packet(repository)
    service = ManagedRunService(repository)
    await service.start_run("run_bad_receipt", plan)
    receipt_path = tmp_path / "mine.json"
    receipt_path.write_text('{"receipt":"real"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="digest"):
        await service.link_mining_receipt(
            "run_bad_receipt",
            MiningReceiptLink(
                receipt_id="mine_bad",
                receipt_path=str(receipt_path),
                receipt_sha256="0" * 64,
                source_repositories=["example/donor@abc123"],
            ),
        )

    assert all(
        event.event_type != ManagedRunService._RECEIPT_EVENT
        for event in await repository.list_run_events("run_bad_receipt")
    )


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


async def test_corrected_outcome_requires_explicit_latest_supersession(
    repository, tmp_path
) -> None:
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
    await _mark_packet_verified(repository, packet)

    with pytest.raises(ValueError, match="supersede"):
        await service.record_outcome(
            "run_supersede",
            packet_id=packet.packet_id,
            slot_id=packet.slot.slot_id,
            outcome=ManagedOutcome(
                status=OutcomeStatus.VERIFIED_SUCCESS,
                test_refs=["tests/test_client.py::test_retry"],
                verification_evidence=[_verification_evidence(tmp_path)],
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
            verification_evidence=[_verification_evidence(tmp_path)],
            trust_delta=1,
            supersedes_outcome_id=first.id,
        ),
    )
    assert corrected.success is True


async def test_positive_outcome_requires_stored_packet_and_receipt_proof(
    repository, tmp_path
) -> None:
    plan, packet, card = await _seed_packet(repository)
    service = ManagedRunService(repository)
    await service.start_run("run_unproved", plan)
    await service.record_candidate_decision(
        "run_unproved",
        CandidateDecision(
            candidate_id=card.id,
            label=AssessmentLabel.DIRECT_PRECEDENT,
            decision=SelectionDecision.SELECTED,
            reason="Reviewed selection.",
            provenance=["example/donor@abc123:src/retry.py:retry"],
            slot_id=packet.slot.slot_id,
        ),
    )
    await service.link_packet_pair("run_unproved", packet.packet_id)

    with pytest.raises(ValueError, match="stored verified application packet"):
        await service.record_outcome(
            "run_unproved",
            packet_id=packet.packet_id,
            slot_id=packet.slot.slot_id,
            outcome=ManagedOutcome(
                status=OutcomeStatus.VERIFIED_SUCCESS,
                test_refs=["caller asserted test string"],
                verification_evidence=[_verification_evidence(tmp_path)],
                recipe_eligible=True,
                trust_delta=1,
            ),
        )

    assert await repository.list_run_outcome_events("run_unproved") == []
    unchanged = await repository.get_component_card(card.id)
    assert unchanged is not None
    assert unchanged.success_count == 0


async def test_verified_success_is_final_inside_one_run(repository, tmp_path) -> None:
    plan, packet, card = await _seed_packet(repository)
    service = ManagedRunService(repository)
    await service.start_run("run_final", plan)
    await service.record_candidate_decision(
        "run_final",
        CandidateDecision(
            candidate_id=card.id,
            label=AssessmentLabel.DIRECT_PRECEDENT,
            decision=SelectionDecision.SELECTED,
            reason="Reviewed selection.",
            provenance=["example/donor@abc123:src/retry.py:retry"],
            slot_id=packet.slot.slot_id,
        ),
    )
    await service.link_packet_pair("run_final", packet.packet_id)
    await _mark_packet_verified(repository, packet)
    success = await service.record_outcome(
        "run_final",
        packet_id=packet.packet_id,
        slot_id=packet.slot.slot_id,
        outcome=ManagedOutcome(
            status=OutcomeStatus.VERIFIED_SUCCESS,
            test_refs=["tests/test_client.py::test_retry"],
            verification_evidence=[_verification_evidence(tmp_path)],
            recipe_eligible=True,
            trust_delta=1,
        ),
    )

    with pytest.raises(ValueError, match="final for this run"):
        await service.record_outcome(
            "run_final",
            packet_id=packet.packet_id,
            slot_id=packet.slot.slot_id,
            outcome=ManagedOutcome(
                status=OutcomeStatus.VERIFIED_FAILURE,
                verifier_findings=["later contradictory result"],
                test_refs=["tests/test_client.py::test_retry"],
                supersedes_outcome_id=success.id,
            ),
        )

    refreshed = await repository.get_component_card(card.id)
    assert refreshed is not None
    assert refreshed.success_count == 1
    assert refreshed.failure_count == 0
    assert len(await repository.list_run_outcome_events("run_final")) == 1


async def test_plan_binding_includes_approval_bearing_fields(repository) -> None:
    plan, _packet, _card = await _seed_packet(repository)
    service = ManagedRunService(repository)
    await service.start_run("run_bound", plan)
    changed = plan.model_copy(deep=True)
    changed.approved_slot_ids.append("slot_unreviewed")

    with pytest.raises(ValueError, match="different plan"):
        await service.start_run("run_bound", changed)

    saved = await repository.get_task_plan(plan.id)
    assert saved is not None
    assert saved.approved_slot_ids == ["slot_retry"]


async def test_pair_requires_latest_explicit_slot_selection(repository) -> None:
    plan, packet, card = await _seed_packet(repository)
    service = ManagedRunService(repository)
    await service.start_run("run_decision", plan)
    selected = await service.record_candidate_decision(
        "run_decision",
        CandidateDecision(
            candidate_id=card.id,
            label=AssessmentLabel.DIRECT_PRECEDENT,
            decision=SelectionDecision.SELECTED,
            reason="Initial reviewed selection.",
            provenance=["example/donor@abc123:src/retry.py:retry"],
            slot_id=packet.slot.slot_id,
        ),
    )
    await service.record_candidate_decision(
        "run_decision",
        CandidateDecision(
            candidate_id=card.id,
            label=AssessmentLabel.DIRECT_PRECEDENT,
            decision=SelectionDecision.REJECTED,
            reason="Later inspection found an incompatible cancellation boundary.",
            provenance=["example/donor@abc123:src/retry.py:retry"],
            slot_id=packet.slot.slot_id,
            supersedes_decision_id=selected.id,
        ),
    )

    with pytest.raises(ValueError, match="current slot selection"):
        await service.link_packet_pair("run_decision", packet.packet_id)

    assert await repository.list_run_pair_events("run_decision") == []


async def test_start_pair_and_outcome_roll_back_as_units_of_work(
    repository, monkeypatch
) -> None:
    plan, packet, card = await _seed_packet(repository)
    service = ManagedRunService(repository)
    real_edge = repository.save_run_connectome_edge

    async def fail_edge(*args, **kwargs):
        raise RuntimeError("fixture edge failure")

    monkeypatch.setattr(repository, "save_run_connectome_edge", fail_edge)
    with pytest.raises(RuntimeError, match="fixture edge failure"):
        await service.start_run("run_atomic_start", plan)
    assert await repository.get_run_connectome("run_atomic_start") is None
    assert await repository.get_task_plan(plan.id) is None

    monkeypatch.setattr(repository, "save_run_connectome_edge", real_edge)
    await service.start_run("run_atomic", plan)
    await service.record_candidate_decision(
        "run_atomic",
        CandidateDecision(
            candidate_id=card.id,
            label=AssessmentLabel.DIRECT_PRECEDENT,
            decision=SelectionDecision.SELECTED,
            reason="Reviewed selection.",
            provenance=["example/donor@abc123:src/retry.py:retry"],
            slot_id=packet.slot.slot_id,
        ),
    )
    monkeypatch.setattr(repository, "save_run_connectome_edge", fail_edge)
    with pytest.raises(RuntimeError, match="fixture edge failure"):
        await service.link_packet_pair("run_atomic", packet.packet_id)
    assert await repository.list_run_pair_events("run_atomic") == []

    monkeypatch.setattr(repository, "save_run_connectome_edge", real_edge)
    await service.link_packet_pair("run_atomic", packet.packet_id)
    real_run_event = repository.save_run_event

    async def fail_outcome_event(event):
        if event.event_type == ManagedRunService._OUTCOME_EVENT:
            raise RuntimeError("fixture outcome event failure")
        return await real_run_event(event)

    monkeypatch.setattr(repository, "save_run_event", fail_outcome_event)
    with pytest.raises(RuntimeError, match="fixture outcome event failure"):
        await service.record_outcome(
            "run_atomic",
            packet_id=packet.packet_id,
            slot_id=packet.slot.slot_id,
            outcome=ManagedOutcome(
                status=OutcomeStatus.VERIFIED_FAILURE,
                verifier_findings=["fixture failure"],
                test_refs=["tests/test_client.py::test_retry"],
            ),
        )
    assert await repository.list_run_outcome_events("run_atomic") == []
    refreshed = await repository.get_component_card(card.id)
    assert refreshed is not None
    assert refreshed.failure_count == 0


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


async def test_managed_run_cli_refuses_to_create_a_missing_database(tmp_path) -> None:
    from claw.cli import _managed_run_async

    config = tmp_path / "claw.toml"
    config.write_text('[database]\ndb_path = "typo.db"\n', encoding="utf-8")
    missing = tmp_path / "typo.db"

    with pytest.raises(ValueError, match="must already exist"):
        await _managed_run_async(
            json.dumps({"operation": "report", "run_id": "run_missing"}),
            str(config),
        )

    assert not missing.exists()
