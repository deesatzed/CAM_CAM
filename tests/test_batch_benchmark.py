from __future__ import annotations

import pytest
from pydantic import ValidationError

from claw.models.batch import BatchCompatibilityReceipt


@pytest.mark.parametrize(
    "status",
    ["unsupported", "submitted", "queued", "running", "completed", "failed", "timed_out"],
)
def test_batch_receipt_accepts_explicit_states(status: str) -> None:
    receipt = BatchCompatibilityReceipt(
        model_id="google/gemini-3.6-flash:batch",
        status=status,
        transport="chat-completions-batch-variant" if status == "completed" else None,
    )
    assert receipt.status == status


def test_batch_receipt_rejects_unknown_state_and_sync_latency_rank() -> None:
    with pytest.raises(ValidationError):
        BatchCompatibilityReceipt(
            model_id="google/gemini-3.6-flash:batch",
            status="mystery",
        )
    with pytest.raises(ValidationError, match="latency"):
        BatchCompatibilityReceipt(
            model_id="google/gemini-3.6-flash:batch",
            status="completed",
            transport="queued-job",
            synchronous_latency_seconds=1.5,
        )
