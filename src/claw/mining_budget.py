"""Fail-closed, persistent cost authorization for live repository mining."""

from __future__ import annotations

import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from claw.models.catalog import ModelCatalogEntry


class MiningBudgetError(RuntimeError):
    """Base class for non-retriable mining budget failures."""


class MiningBudgetExceededError(MiningBudgetError):
    """Raised before a provider request that cannot fit the authorization."""


class MiningBudgetViolationError(MiningBudgetError):
    """Raised when a run no longer matches its frozen authorization."""


class MiningAttemptReceipt(BaseModel):
    """Durable evidence for one provider HTTP attempt."""

    model_config = ConfigDict(frozen=True)

    attempt_id: str
    repo_name: str | None = None
    status: Literal["submitted", "completed", "failed"]
    requested_model: str
    returned_model: str | None = None
    maximum_cost_usd: float
    actual_cost_usd: float | None = None
    cost_source: str = "missing"
    request_id: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str


class MiningBudgetReceipt(BaseModel):
    """Persistent authorization plus all charged or potentially charged attempts."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    authorization_usd: float
    exact_model: str
    model_catalog_digest: str
    status: Literal["running", "completed", "budget-exhausted", "failed"] = (
        "running"
    )
    attempts: list[MiningAttemptReceipt] = Field(default_factory=list)
    created_at: str
    updated_at: str

    @property
    def actual_spend_usd(self) -> float:
        return sum(
            attempt.actual_cost_usd or 0.0
            for attempt in self.attempts
        )

    @property
    def conservative_spend_usd(self) -> float:
        return sum(
            attempt.actual_cost_usd
            if attempt.actual_cost_usd is not None
            else attempt.maximum_cost_usd
            for attempt in self.attempts
        )

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.authorization_usd - self.conservative_spend_usd)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class MiningBudgetController:
    """Reserve worst-case request cost before every provider attempt."""

    _MESSAGE_OVERHEAD_BYTES = 1024

    def __init__(
        self,
        *,
        receipt_path: Path,
        receipt: MiningBudgetReceipt,
        catalog_entry: ModelCatalogEntry,
    ) -> None:
        self.receipt_path = receipt_path
        self.receipt = receipt
        self.catalog_entry = catalog_entry
        self._repo_name: str | None = None

    @classmethod
    def open(
        cls,
        *,
        receipt_path: Path,
        authorization_usd: float,
        exact_model: str,
        catalog_entry: ModelCatalogEntry,
    ) -> "MiningBudgetController":
        if authorization_usd <= 0:
            raise MiningBudgetViolationError("Mining authorization must be positive")
        if catalog_entry.requested_id != exact_model:
            raise MiningBudgetViolationError(
                "Catalog entry does not match the authorized exact model"
            )

        path = receipt_path.resolve()
        if path.exists():
            receipt = MiningBudgetReceipt.model_validate_json(path.read_text())
            if not math.isclose(
                receipt.authorization_usd,
                authorization_usd,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise MiningBudgetViolationError(
                    "Mining authorization changed on resume"
                )
            if receipt.exact_model != exact_model:
                raise MiningBudgetViolationError("Mining exact model changed on resume")
            if receipt.model_catalog_digest != catalog_entry.catalog_digest:
                raise MiningBudgetViolationError(
                    "Mining catalog entry changed on resume"
                )
        else:
            timestamp = _now()
            receipt = MiningBudgetReceipt(
                authorization_usd=authorization_usd,
                exact_model=exact_model,
                model_catalog_digest=catalog_entry.catalog_digest,
                created_at=timestamp,
                updated_at=timestamp,
            )

        controller = cls(
            receipt_path=path,
            receipt=receipt,
            catalog_entry=catalog_entry,
        )
        controller._persist()
        return controller

    def set_repo_context(self, repo_name: str | None) -> None:
        self._repo_name = repo_name

    @property
    def exact_model(self) -> str:
        return self.receipt.exact_model

    def reserve_attempt(
        self,
        payload: dict[str, Any],
    ) -> tuple[MiningAttemptReceipt, dict[str, Any]]:
        requested_model = str(payload.get("model") or "")
        if requested_model != self.receipt.exact_model:
            raise MiningBudgetViolationError(
                f"Request model {requested_model!r} violates exact model "
                f"{self.receipt.exact_model!r}"
            )

        maximum_cost, prompt_price, completion_price = self._maximum_cost(payload)
        projected = self.receipt.conservative_spend_usd + maximum_cost
        if projected > self.receipt.authorization_usd + 1e-12:
            self._replace_receipt(status="budget-exhausted")
            raise MiningBudgetExceededError(
                f"Request would cross mining budget: ${projected:.6f} > "
                f"${self.receipt.authorization_usd:.6f}"
            )

        timestamp = _now()
        attempt = MiningAttemptReceipt(
            attempt_id=str(uuid4()),
            repo_name=self._repo_name,
            status="submitted",
            requested_model=requested_model,
            maximum_cost_usd=maximum_cost,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._replace_receipt(
            status="running",
            attempts=[*self.receipt.attempts, attempt],
        )

        guarded = dict(payload)
        max_price: dict[str, float] = {
            "prompt": prompt_price,
            "completion": completion_price,
        }
        if self.catalog_entry.pricing.request_price is not None:
            max_price["request"] = self.catalog_entry.pricing.request_price
        guarded["provider"] = {
            "allow_fallbacks": False,
            "require_parameters": True,
            "sort": "price",
            "max_price": max_price,
        }
        return attempt, guarded

    def reconcile_completed(
        self,
        attempt_id: str,
        *,
        returned_model: str | None,
        actual_cost_usd: float | None,
        cost_source: str,
        request_id: str | None,
    ) -> None:
        attempt = self._find_attempt(attempt_id)
        completed = attempt.model_copy(
            update={
                "status": "completed",
                "returned_model": returned_model,
                "actual_cost_usd": actual_cost_usd,
                "cost_source": cost_source,
                "request_id": request_id,
                "updated_at": _now(),
            }
        )
        self._replace_attempt(completed)
        if self.receipt.conservative_spend_usd > self.receipt.authorization_usd + 1e-12:
            self._replace_receipt(status="failed")
            raise MiningBudgetViolationError(
                "Provider-reported cost exceeded the mining authorization"
            )

    def record_failure(self, attempt_id: str, error: str) -> None:
        attempt = self._find_attempt(attempt_id)
        failed = attempt.model_copy(
            update={
                "status": "failed",
                "error": error,
                "updated_at": _now(),
            }
        )
        self._replace_attempt(failed)

    def mark_status(
        self,
        status: Literal["running", "completed", "budget-exhausted", "failed"],
    ) -> None:
        self._replace_receipt(status=status)

    def _maximum_cost(self, payload: dict[str, Any]) -> tuple[float, float, float]:
        messages = payload.get("messages") or []
        serialized = json.dumps(messages, sort_keys=True, separators=(",", ":"))
        input_token_bound = len(serialized.encode("utf-8")) + self._MESSAGE_OVERHEAD_BYTES
        output_token_bound = int(payload.get("max_tokens") or 0)

        prompt_prices = [self.catalog_entry.pricing.prompt_per_million]
        completion_prices = [self.catalog_entry.pricing.completion_per_million]
        for override in self.catalog_entry.pricing.overrides:
            if input_token_bound >= int(override.get("min_prompt_tokens", 0)):
                prompt_prices.append(
                    float(
                        override.get(
                            "prompt_per_million",
                            self.catalog_entry.pricing.prompt_per_million,
                        )
                    )
                )
                completion_prices.append(
                    float(
                        override.get(
                            "completion_per_million",
                            self.catalog_entry.pricing.completion_per_million,
                        )
                    )
                )

        prompt_price = max(prompt_prices)
        completion_price = max(completion_prices)
        reasoning_price = self.catalog_entry.pricing.reasoning_per_million or 0.0
        request_price = self.catalog_entry.pricing.request_price or 0.0
        maximum = (
            input_token_bound * prompt_price
            + output_token_bound * (completion_price + reasoning_price)
        ) / 1_000_000 + request_price
        return maximum, prompt_price, completion_price

    def _find_attempt(self, attempt_id: str) -> MiningAttemptReceipt:
        for attempt in self.receipt.attempts:
            if attempt.attempt_id == attempt_id:
                return attempt
        raise MiningBudgetViolationError(
            f"Unknown mining attempt receipt: {attempt_id}"
        )

    def _replace_attempt(self, replacement: MiningAttemptReceipt) -> None:
        attempts = [
            replacement if attempt.attempt_id == replacement.attempt_id else attempt
            for attempt in self.receipt.attempts
        ]
        self._replace_receipt(attempts=attempts)

    def _replace_receipt(
        self,
        *,
        status: Literal["running", "completed", "budget-exhausted", "failed"]
        | None = None,
        attempts: list[MiningAttemptReceipt] | None = None,
    ) -> None:
        updates: dict[str, Any] = {"updated_at": _now()}
        if status is not None:
            updates["status"] = status
        if attempts is not None:
            updates["attempts"] = attempts
        self.receipt = self.receipt.model_copy(update=updates)
        self._persist()

    def _persist(self) -> None:
        self.receipt_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.receipt_path.with_suffix(".tmp")
        encoded = self.receipt.model_dump_json(indent=2) + "\n"
        temp_path.write_text(encoded)
        os.chmod(temp_path, 0o600)
        temp_path.replace(self.receipt_path)
        os.chmod(self.receipt_path, 0o600)
