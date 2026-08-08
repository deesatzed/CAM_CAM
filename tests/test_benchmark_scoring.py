from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import claw.models.scoring as scoring_module
from claw.models.benchmark import CallReceipt, MiningPromptFixture, PlannedCall
from claw.models.scoring import (
    QUALITY_WEIGHTS,
    build_blinded_packet,
    score_benchmark_run,
    score_candidate,
)


def _fixture(repo: Path) -> MiningPromptFixture:
    prompt = "mine fixture"
    content = "--- FILE: src/retry.py ---\ndef retry():\n    pass\n"
    return MiningPromptFixture(
        repo_path=str(repo),
        repo_name="fixture",
        git_head=None,
        dirty_paths=[],
        brain="python",
        prompt=prompt,
        prompt_sha256=__import__("hashlib").sha256(prompt.encode()).hexdigest(),
        repo_content=content,
        repo_content_sha256=__import__("hashlib").sha256(content.encode()).hexdigest(),
        source_manifest=["src/retry.py"],
        repo_bytes=len(content),
        file_count=1,
        estimated_tokens=20,
        token_budget=100,
        domain_info={"complexity": "small"},
        overlap={},
    )


def _response(source_file: str = "src/retry.py", title: str = "Bounded retry") -> str:
    return json.dumps(
        [
            {
                "title": title,
                "description": (
                    "A bounded retry helper preserves the final exception and limits attempts."
                ),
                "category": "code_quality",
                "source_files": [source_file],
                "source_symbols": [
                    {
                        "file_path": source_file,
                        "symbol_name": "retry",
                        "symbol_kind": "function",
                    }
                ],
                "implementation_sketch": (
                    "Extract retry(attempts) and preserve the final exception."
                ),
                "augmentation_notes": "Use only for idempotent operations.",
                "relevance_score": 0.9,
                "language": "python",
                "execution_steps": ["Add bounded loop", "Re-raise final exception"],
                "acceptance_checks": ["Test final exception", "Test maximum attempts"],
                "rollback_steps": ["Restore direct call"],
                "preconditions": ["Operation is idempotent"],
            }
        ]
    )


def test_scoring_weights_total_100_and_grounded_response_passes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "retry.py").write_text("def retry():\n    pass\n")

    score = score_candidate(_response(), _fixture(repo), existing_titles=[])

    assert sum(QUALITY_WEIGHTS.values()) == 100
    assert score.grounded_correctness == 35
    assert score.structured_reliability == 10
    assert score.hard_failures == []
    assert score.total > 80


def test_invented_or_escaping_provenance_and_secret_output_are_hard_failures(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    invented = score_candidate(_response("../secret.txt"), _fixture(repo), [])
    secret = score_candidate(_response() + " sk-or-v1-secretsecretsecret", _fixture(repo), [])

    assert "invalid_provenance" in invented.hard_failures
    assert "secret_like_output" in secret.hard_failures


def test_grounding_accepts_class_qualified_method_symbols(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "retry.py").write_text(
        "class Retryer:\n    def retry(self):\n        pass\n"
    )
    response = json.loads(_response())
    response[0]["source_symbols"][0]["symbol_name"] = "Retryer.retry"

    score = score_candidate(json.dumps(response), _fixture(repo), [])

    assert "invalid_provenance" not in score.hard_failures


def test_imprecise_symbol_lowers_grounding_without_hard_failing_valid_file(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "retry.py").write_text("def retry():\n    pass\n")
    response = json.loads(_response())
    response[0]["source_symbols"][0]["symbol_name"] = "Retry orchestration"

    score = score_candidate(json.dumps(response), _fixture(repo), [])

    assert "invalid_provenance" not in score.hard_failures
    assert 0 < score.grounded_correctness < QUALITY_WEIGHTS["grounded_correctness"]


def test_provenance_scoring_uses_frozen_fixture_content_not_mutated_repo(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "retry.py").write_text("def retry():\n    pass\n")
    fixture = _fixture(repo)
    (repo / "src" / "retry.py").write_text("def unrelated():\n    pass\n")

    score = score_candidate(_response(), fixture, [])

    assert score.grounded_correctness == QUALITY_WEIGHTS["grounded_correctness"]


def test_duplicates_reduce_novelty_and_malformed_output_reduces_reliability(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "retry.py").write_text("def retry():\n    pass\n")

    duplicate = score_candidate(_response(), _fixture(repo), ["Bounded retry"])
    malformed = score_candidate("not json", _fixture(repo), [])

    assert duplicate.novelty < 25
    assert malformed.structured_reliability == 0
    assert "malformed_findings" in malformed.hard_failures


def test_blinded_packet_contains_no_model_identity(tmp_path: Path) -> None:
    packet = build_blinded_packet(
        run_id="run-1",
        model_id="openai/gpt-5.6-luna",
        fixture_name="fixture",
        response_text=_response(),
    )
    serialized = packet.model_dump_json()

    assert packet.candidate_code.startswith("candidate-")
    assert "openai" not in serialized
    assert "gpt-5.6-luna" not in serialized


def test_score_run_aggregates_cost_quality_and_normalized_envelopes(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "retry.py").write_text("def retry():\n    pass\n")
    fixture = _fixture(repo)
    run_dir = tmp_path / "run"
    (run_dir / "receipts").mkdir(parents=True)
    (run_dir / "responses").mkdir()
    response_path = run_dir / "responses" / "call-1.txt"
    response_path.write_text(json.dumps({"findings": json.loads(_response())}))
    receipt = CallReceipt(
        call_id="call-1",
        status="completed",
        requested_model="openai/gpt-5.6-luna",
        returned_model="openai/gpt-5.6-luna",
        fixture_name="fixture",
        prompt_sha256=fixture.prompt_sha256,
        finish_reason="stop",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.001,
        cost_source="provider",
        duration_seconds=2.0,
        response_path="responses/call-1.txt",
    )
    (run_dir / "receipts" / "call-1.json").write_text(receipt.model_dump_json())

    report = score_benchmark_run(
        run_id="run-1",
        run_dir=run_dir,
        fixtures=[fixture],
        expected_fixtures=1,
        existing_titles=[],
    )

    assert report.actual_cost_usd == 0.001
    assert report.calls[0].envelope == "findings-wrapper"
    assert report.calls[0].hard_failures == []
    assert report.models[0].eligible is True
    assert report.models[0].average_quality > 80
    assert report.models[0].worst_quality == report.models[0].average_quality
    assert report.models[0].cost_per_finding_usd == 0.001


def test_fenced_json_accepted_by_production_parser_is_not_a_hard_failure(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "retry.py").write_text("def retry():\n    pass\n")
    fixture = _fixture(repo)
    run_dir = tmp_path / "run"
    (run_dir / "receipts").mkdir(parents=True)
    (run_dir / "responses").mkdir()
    wrapped = json.dumps({"findings": json.loads(_response())})
    (run_dir / "responses" / "fenced.txt").write_text(
        f"```json\n{wrapped}\n```"
    )
    receipt = CallReceipt(
        call_id="fenced",
        status="completed",
        requested_model="qwen/qwen3.8-max",
        returned_model="qwen/qwen3.8-max",
        fixture_name="fixture",
        prompt_sha256=fixture.prompt_sha256,
        cost_usd=0.001,
        cost_source="provider",
        response_path="responses/fenced.txt",
    )
    (run_dir / "receipts" / "fenced.json").write_text(receipt.model_dump_json())

    report = score_benchmark_run(
        run_id="fenced-run",
        run_dir=run_dir,
        fixtures=[fixture],
        expected_fixtures=1,
        existing_titles=[],
    )

    assert report.calls[0].envelope == "fenced-findings-wrapper"
    assert report.calls[0].hard_failures == []
    assert report.models[0].eligible is True


def test_load_existing_titles_uses_immutable_read_only_corpus(tmp_path: Path) -> None:
    db_path = tmp_path / "claw.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """CREATE TABLE methodologies (
                problem_description TEXT NOT NULL,
                solution_code TEXT NOT NULL,
                lifecycle_state TEXT NOT NULL
            )"""
        )
        connection.executemany(
            "INSERT INTO methodologies VALUES (?, ?, ?)",
            [
                (
                    "[Mined from retry-lib] Bounded retry: Preserves the final error.",
                    "## Bounded retry\n\nImplementation",
                    "viable",
                ),
                (
                    "[Mined from queue-lib] Durable queue: Survives restarts.",
                    "## Durable queue\n\nImplementation",
                    "dead",
                ),
            ],
        )

    titles = scoring_module.load_existing_mining_titles(db_path)

    assert titles == ["Bounded retry"]
    assert not db_path.with_name("claw.db-wal").exists()
    assert not db_path.with_name("claw.db-shm").exists()


def test_truncated_or_repaired_call_reports_zero_quality(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "retry.py").write_text("def retry():\n    pass\n")
    fixture = _fixture(repo)
    run_dir = tmp_path / "run"
    (run_dir / "receipts").mkdir(parents=True)
    (run_dir / "responses").mkdir()
    (run_dir / "responses" / "call-length.txt").write_text(_response())
    receipt = CallReceipt(
        call_id="call-length",
        status="completed",
        requested_model="qwen/qwen3.8-max",
        returned_model="qwen/qwen3.8-max",
        fixture_name="fixture",
        prompt_sha256=fixture.prompt_sha256,
        finish_reason="length",
        cost_usd=0.01,
        response_path="responses/call-length.txt",
    )
    (run_dir / "receipts" / "call-length.json").write_text(
        receipt.model_dump_json()
    )

    report = score_benchmark_run(
        run_id="run-length",
        run_dir=run_dir,
        fixtures=[fixture],
        expected_fixtures=1,
        existing_titles=[],
    )

    assert report.calls[0].finding_count == 1
    assert "truncated_response" in report.calls[0].hard_failures
    assert report.calls[0].quality == 0
    assert report.models[0].eligible is False


def test_failed_charged_receipt_counts_toward_report_spend(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "receipts").mkdir(parents=True)
    failed = CallReceipt(
        call_id="failed-call",
        status="failed",
        requested_model="openai/gpt-5.6-luna",
        returned_model="unexpected/model",
        fixture_name="fixture",
        prompt_sha256="prompt",
        cost_usd=0.02,
        cost_source="provider",
        error="returned model drift",
    )
    (run_dir / "receipts" / "failed-call.json").write_text(failed.model_dump_json())

    report = score_benchmark_run(
        run_id="failed-run",
        run_dir=run_dir,
        fixtures=[],
        expected_fixtures=1,
        existing_titles=[],
    )

    assert report.actual_cost_usd == 0.02
    assert report.conservative_cost_usd == 0.02
    assert report.calls == []
    assert report.models == []


def test_submitted_receipt_reserves_frozen_maximum_cost(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "receipts").mkdir(parents=True)
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "retry.py").write_text("def retry():\n    pass\n")
    fixture = _fixture(repo)
    submitted = CallReceipt(
        call_id="submitted-call",
        status="submitted",
        requested_model="google/gemini-3.6-flash:batch",
        fixture_name=fixture.repo_name,
        prompt_sha256=fixture.prompt_sha256,
        transport="queued-job",
        batch_job_id="batch-pending",
        retention_days=30,
    )
    (run_dir / "receipts" / "submitted-call.json").write_text(
        submitted.model_dump_json()
    )
    planned = PlannedCall(
        call_id="submitted-call",
        stage="first-round",
        model_id="google/gemini-3.6-flash:batch",
        fixture_name=fixture.repo_name,
        prompt_sha256=fixture.prompt_sha256,
        repo_content_sha256=fixture.repo_content_sha256,
        catalog_digest="catalog",
        maximum_input_tokens=100,
        maximum_output_tokens=100,
        maximum_cost_usd=0.03,
        parameters=[],
        transport="batch-compatibility",
    )

    report = score_benchmark_run(
        run_id="submitted-run",
        run_dir=run_dir,
        fixtures=[fixture],
        expected_fixtures=1,
        existing_titles=[],
        planned_calls=[planned],
    )

    assert report.actual_cost_usd == 0
    assert report.conservative_cost_usd == 0.03
    assert report.calls == []
    assert report.models == []


def test_scoring_rejects_receipts_outside_the_frozen_call_set(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "receipts").mkdir(parents=True)
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "retry.py").write_text("def retry():\n    pass\n")
    fixture = _fixture(repo)
    stale = CallReceipt(
        call_id="stale-call",
        status="failed",
        requested_model="openai/gpt-5.6-luna",
        fixture_name=fixture.repo_name,
        prompt_sha256=fixture.prompt_sha256,
        cost_usd=0.01,
        error="stale",
    )
    (run_dir / "receipts" / "stale-call.json").write_text(stale.model_dump_json())
    planned = PlannedCall(
        call_id="expected-call",
        stage="first-round",
        model_id="openai/gpt-5.6-luna",
        fixture_name=fixture.repo_name,
        prompt_sha256=fixture.prompt_sha256,
        repo_content_sha256=fixture.repo_content_sha256,
        catalog_digest="catalog",
        maximum_input_tokens=100,
        maximum_output_tokens=100,
        maximum_cost_usd=0.02,
        parameters=[],
    )

    with pytest.raises(ValueError, match="not in the frozen plan"):
        score_benchmark_run(
            run_id="run",
            run_dir=run_dir,
            fixtures=[fixture],
            expected_fixtures=1,
            existing_titles=[],
            planned_calls=[planned],
        )


def test_scoring_rejects_fixture_content_drift_from_frozen_plan(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "retry.py").write_text("def retry():\n    pass\n")
    fixture = _fixture(repo)
    planned = PlannedCall(
        call_id="expected-call",
        stage="first-round",
        model_id="openai/gpt-5.6-luna",
        fixture_name=fixture.repo_name,
        prompt_sha256=fixture.prompt_sha256,
        repo_content_sha256=fixture.repo_content_sha256,
        catalog_digest="catalog",
        maximum_input_tokens=100,
        maximum_output_tokens=100,
        maximum_cost_usd=0.02,
        parameters=[],
    )
    drifted = fixture.model_copy(update={"repo_content": "tampered content"})

    with pytest.raises(ValueError, match="Source drift"):
        score_benchmark_run(
            run_id="run",
            run_dir=tmp_path / "run",
            fixtures=[drifted],
            expected_fixtures=1,
            existing_titles=[],
            planned_calls=[planned],
        )
