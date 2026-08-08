from __future__ import annotations

import json
from pathlib import Path

from claw.models.benchmark import MiningPromptFixture
from claw.models.scoring import QUALITY_WEIGHTS, build_blinded_packet, score_candidate


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
