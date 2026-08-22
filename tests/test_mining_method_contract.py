from __future__ import annotations

import json
from pathlib import Path
import subprocess

from claw.core.models import Methodology
from claw.memory.prompt_pack import build_prompt_pack
from claw.miner import MiningFinding, RepoMiner, parse_findings


PROMPTS = (
    "repo-mine.md",
    "repo-mine-typescript.md",
    "repo-mine-go.md",
    "repo-mine-rust.md",
    "repo-mine-misc.md",
)


def _finding_payload() -> dict[str, object]:
    return {
        "title": "Bounded state transition",
        "description": "Preserve a transition protocol instead of only its theme.",
        "category": "architecture",
        "source_files": ["src/state.py"],
        "source_symbols": [
            {
                "file_path": "src/state.py",
                "symbol_name": "advance",
                "symbol_kind": "function",
                "note": "carries the transition",
            }
        ],
        "implementation_sketch": "Adapt the state transition behind a typed boundary.",
        "augmentation_notes": "Verify compatibility before applying.",
        "method_contract": {
            "problem": "A retried transition must not apply twice.",
            "preconditions": ["stable operation identity"],
            "ordered_steps": ["read state", "validate identity", "write next state"],
            "invariants": ["one accepted transition per operation identity"],
            "failure_behavior": "Reject stale or conflicting identities.",
            "recovery_behavior": "Return the prior result for an exact replay.",
            "verification": ["replay the same operation", "submit a conflicting operation"],
            "discriminative_terms": ["exact replay", "conflicting identity"],
            "ignored_hidden_tests": ["must never be preserved"],
        },
        "relevance_score": 0.9,
        "language": "python",
    }


def test_all_mining_prompts_request_the_typed_method_contract() -> None:
    for prompt_name in PROMPTS:
        text = (Path("prompts") / prompt_name).read_text(encoding="utf-8")
        assert '"method_contract"' in text
        for field in (
            "problem",
            "preconditions",
            "ordered_steps",
            "invariants",
            "failure_behavior",
            "recovery_behavior",
            "verification",
            "discriminative_terms",
        ):
            assert f'"{field}"' in text


def test_parser_and_seed_preserve_only_bounded_method_contract_fields() -> None:
    finding = parse_findings(json.dumps({"findings": [_finding_payload()]}), "org/repo")[0]
    assert finding.method_contract["ordered_steps"] == [
        "read state",
        "validate identity",
        "write next state",
    ]
    assert "ignored_hidden_tests" not in finding.method_contract

    miner = object.__new__(RepoMiner)
    miner._current_mine_metadata = {
        "license_type": "MIT",
        "source_revision": "a" * 40,
    }
    capability = RepoMiner._seed_capability_data_from_finding(miner, finding)
    assert capability["method_contract"] == finding.method_contract
    assert capability["method_contract_provenance"] == {
        "source_repo": "org/repo",
        "source_revision": "a" * 40,
        "license_type": "MIT",
        "source_files": ["src/state.py"],
        "source_symbols": ["src/state.py:advance"],
    }


def test_parser_rejects_non_string_method_contract_list_items() -> None:
    payload = _finding_payload()
    contract = payload["method_contract"]
    assert isinstance(contract, dict)
    contract["preconditions"] = ["stable operation identity", {"secret": "no"}, 17]

    finding = parse_findings(json.dumps([payload]), "org/repo")[0]

    assert finding.method_contract["preconditions"] == ["stable operation identity"]


def test_prompt_pack_renders_method_semantics_but_not_unknown_contract_keys() -> None:
    finding = parse_findings(json.dumps([_finding_payload()]), "org/repo")[0]
    miner = object.__new__(RepoMiner)
    miner._current_mine_metadata = {"license_type": "MIT", "source_revision": "b" * 40}
    capability = RepoMiner._seed_capability_data_from_finding(miner, finding)
    capability["method_contract"]["hidden_tests"] = ["do not leak"]
    methodology = Methodology(
        problem_description="Replay-safe state transitions",
        solution_code="Use the mined transition protocol.",
        tags=["mined", "source:org/repo"],
        capability_data=capability,
    )

    packet = build_prompt_pack([methodology])
    assert "Method Contract:" in packet
    assert "Ordered Steps:" in packet
    assert "1. read state" in packet
    assert "Failure Behavior: Reject stale or conflicting identities." in packet
    assert "Verification: replay the same operation; submit a conflicting operation" in packet
    assert "Source Repository: org/repo" in packet
    assert "Source Revision: " + "b" * 40 in packet
    assert "Source Symbols: src/state.py:advance" in packet
    assert "hidden_tests" not in packet
    assert "do not leak" not in packet


def test_absent_method_contract_keeps_legacy_finding_and_pack_compatible() -> None:
    finding = MiningFinding(
        title="Legacy finding",
        description="A legacy finding without structured method semantics.",
        category="code_quality",
        source_repo="org/legacy",
    )
    miner = object.__new__(RepoMiner)
    miner._current_mine_metadata = {}
    capability = RepoMiner._seed_capability_data_from_finding(miner, finding)
    assert capability["method_contract"] is None

    methodology = Methodology(
        problem_description="Legacy finding",
        solution_code="Use legacy behavior.",
        capability_data=capability,
    )
    packet = build_prompt_pack([methodology])
    assert "Method Contract:" not in packet


def test_source_revision_is_bound_only_for_a_clean_git_checkout(tmp_path: Path) -> None:
    repository = tmp_path / "source"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    source = repository / "method.py"
    source.write_text("def method():\n    return True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "method.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=Method Contract Test",
            "-c",
            "user.email=method-contract@example.invalid",
            "commit",
            "-qm",
            "source",
        ],
        check=True,
    )
    expected = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert RepoMiner._clean_source_revision(repository) == expected
    source.write_text("def method():\n    return False\n", encoding="utf-8")
    assert RepoMiner._clean_source_revision(repository) == ""
