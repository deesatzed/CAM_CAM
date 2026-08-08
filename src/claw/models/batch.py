"""Compatibility state for OpenRouter model identifiers using a batch variant."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

BatchStatus = Literal[
    "unsupported",
    "submitted",
    "queued",
    "running",
    "completed",
    "failed",
    "timed_out",
]


class BatchCompatibilityReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str
    status: BatchStatus
    transport: str | None = None
    job_id: str | None = None
    synchronous_latency_seconds: float | None = None
    detail: str | None = None

    @model_validator(mode="after")
    def reject_sync_latency_for_queued_jobs(self) -> "BatchCompatibilityReceipt":
        if self.transport == "queued-job" and self.synchronous_latency_seconds is not None:
            raise ValueError("Queued batch jobs cannot receive synchronous latency rankings")
        return self
