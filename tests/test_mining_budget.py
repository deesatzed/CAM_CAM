from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from claw.mining_budget import (
    MiningBudgetController,
    MiningBudgetExceededError,
    MiningBudgetReceipt,
    MiningBudgetViolationError,
)
from claw.models.catalog import ModelCatalogEntry, ModelPricing


def _grok_entry(*, digest: str = "grok-digest") -> ModelCatalogEntry:
    return ModelCatalogEntry(
        requested_id="x-ai/grok-4.5",
        canonical_slug="x-ai/grok-4.5",
        name="Grok 4.5",
        context_length=1_000_000,
        max_completion_tokens=32_768,
        supported_parameters=frozenset({"max_tokens", "reasoning"}),
        pricing=ModelPricing(
            prompt_per_million=3.0,
            completion_per_million=15.0,
            reasoning_per_million=1.0,
            request_price=0.001,
            overrides=[
                {
                    "min_prompt_tokens": 100_000,
                    "prompt_per_million": 4.0,
                    "completion_per_million": 16.0,
                }
            ],
        ),
        catalog_digest=digest,
    )


def _payload(content: str = "mine this", *, max_tokens: int = 4096) -> dict:
    return {
        "model": "x-ai/grok-4.5",
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
    }


def _controller(tmp_path: Path, *, authorization: float = 7.0):
    return MiningBudgetController.open(
        receipt_path=tmp_path / "run.json",
        authorization_usd=authorization,
        exact_model="x-ai/grok-4.5",
        catalog_entry=_grok_entry(),
    )


def test_reserve_is_persisted_before_request(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    controller.set_repo_context("example-repo")

    attempt, guarded = controller.reserve_attempt(_payload())

    restored = MiningBudgetReceipt.model_validate_json(
        (tmp_path / "run.json").read_text()
    )
    assert restored.attempts[-1].attempt_id == attempt.attempt_id
    assert restored.attempts[-1].status == "submitted"
    assert restored.attempts[-1].repo_name == "example-repo"
    assert restored.conservative_spend_usd > 0
    assert guarded["model"] == "x-ai/grok-4.5"


def test_receipt_is_private_and_atomic_json(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    controller.reserve_attempt(_payload())

    mode = stat.S_IMODE((tmp_path / "run.json").stat().st_mode)
    assert mode == 0o600
    assert json.loads((tmp_path / "run.json").read_text())["schema_version"] == 1
    assert not (tmp_path / "run.tmp").exists()


def test_request_that_does_not_fit_is_not_appended(tmp_path: Path) -> None:
    controller = _controller(tmp_path, authorization=0.000001)

    with pytest.raises(MiningBudgetExceededError, match="would cross mining budget"):
        controller.reserve_attempt(_payload())

    restored = MiningBudgetReceipt.model_validate_json(
        (tmp_path / "run.json").read_text()
    )
    assert restored.attempts == []
    assert restored.status == "budget-exhausted"


def test_provider_cost_replaces_completed_reserve(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    attempt, _ = controller.reserve_attempt(_payload())
    reserved = controller.receipt.conservative_spend_usd

    controller.reconcile_completed(
        attempt.attempt_id,
        returned_model="x-ai/grok-4.5",
        actual_cost_usd=0.0123,
        cost_source="provider",
        request_id="gen-1",
    )

    completed = controller.receipt.attempts[-1]
    assert completed.status == "completed"
    assert completed.actual_cost_usd == pytest.approx(0.0123)
    assert controller.receipt.actual_spend_usd == pytest.approx(0.0123)
    assert controller.receipt.conservative_spend_usd == pytest.approx(0.0123)
    assert controller.receipt.conservative_spend_usd < reserved


def test_missing_cost_retains_completed_reserve(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    attempt, _ = controller.reserve_attempt(_payload())
    reserved = attempt.maximum_cost_usd

    controller.reconcile_completed(
        attempt.attempt_id,
        returned_model="x-ai/grok-4.5",
        actual_cost_usd=None,
        cost_source="missing",
        request_id="gen-2",
    )

    assert controller.receipt.attempts[-1].status == "completed"
    assert controller.receipt.actual_spend_usd == 0
    assert controller.receipt.conservative_spend_usd == pytest.approx(reserved)


def test_ambiguous_failure_retains_reserve(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    attempt, _ = controller.reserve_attempt(_payload())

    controller.record_failure(attempt.attempt_id, "network timeout")

    failed = controller.receipt.attempts[-1]
    assert failed.status == "failed"
    assert failed.actual_cost_usd is None
    assert controller.receipt.conservative_spend_usd == pytest.approx(
        attempt.maximum_cost_usd
    )


def test_retry_attempts_reserve_independently(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    first, _ = controller.reserve_attempt(_payload())
    controller.record_failure(first.attempt_id, "timeout")
    second, _ = controller.reserve_attempt(_payload())

    assert second.attempt_id != first.attempt_id
    assert controller.receipt.conservative_spend_usd == pytest.approx(
        first.maximum_cost_usd + second.maximum_cost_usd
    )


def test_resume_restores_prior_spend(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    first, _ = controller.reserve_attempt(_payload())
    controller.record_failure(first.attempt_id, "timeout")
    second, _ = controller.reserve_attempt(_payload("another"))
    controller.reconcile_completed(
        second.attempt_id,
        returned_model="x-ai/grok-4.5",
        actual_cost_usd=0.02,
        cost_source="provider",
        request_id="gen-3",
    )

    resumed = _controller(tmp_path)

    assert resumed.receipt.actual_spend_usd == pytest.approx(0.02)
    assert resumed.receipt.conservative_spend_usd == pytest.approx(
        first.maximum_cost_usd + 0.02
    )


@pytest.mark.parametrize(
    ("authorization", "model", "entry", "message"),
    [
        (6.0, "x-ai/grok-4.5", _grok_entry(), "authorization"),
        (7.0, "x-ai/grok-4.4", _grok_entry(), "exact model"),
        (7.0, "x-ai/grok-4.5", _grok_entry(digest="changed"), "catalog"),
    ],
)
def test_resume_rejects_contract_drift(
    tmp_path: Path,
    authorization: float,
    model: str,
    entry: ModelCatalogEntry,
    message: str,
) -> None:
    _controller(tmp_path)

    with pytest.raises(MiningBudgetViolationError, match=message):
        MiningBudgetController.open(
            receipt_path=tmp_path / "run.json",
            authorization_usd=authorization,
            exact_model=model,
            catalog_entry=entry,
        )


def test_provider_preferences_are_frozen_into_guarded_payload(tmp_path: Path) -> None:
    controller = _controller(tmp_path)

    _attempt, guarded = controller.reserve_attempt(_payload())

    assert guarded["provider"] == {
        "allow_fallbacks": False,
        "require_parameters": True,
        "sort": "price",
        "max_price": {
            "prompt": 3.0,
            "completion": 15.0,
            "request": 0.001,
        },
    }


def test_exact_model_mismatch_fails_before_reservation(tmp_path: Path) -> None:
    controller = _controller(tmp_path)

    with pytest.raises(MiningBudgetViolationError, match="exact model"):
        controller.reserve_attempt({**_payload(), "model": "openai/gpt-4.1-mini"})

    assert controller.receipt.attempts == []
