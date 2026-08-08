"""OpenRouter queued-batch transport and compatibility evidence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, model_validator

from claw.llm.client import LLMMessage, LLMResponse

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
    retention_days: int | None = None
    detail: str | None = None

    @model_validator(mode="after")
    def reject_sync_latency_for_queued_jobs(self) -> "BatchCompatibilityReceipt":
        if self.transport == "queued-job" and self.synchronous_latency_seconds is not None:
            raise ValueError("Queued batch jobs cannot receive synchronous latency rankings")
        return self


@dataclass(frozen=True)
class BatchCompletion:
    """One completed response plus evidence about its queued transport."""

    response: LLMResponse
    job_id: str
    compatibility: BatchCompatibilityReceipt


@dataclass(frozen=True)
class BatchSubmission:
    """Durable identity needed to poll a previously submitted batch."""

    job_id: str
    requested_model: str
    custom_id: str
    retention_days: int = 30


class BatchJobError(RuntimeError):
    """A submitted batch that did not yield a usable completion."""

    def __init__(self, message: str, *, job_id: str, status: str) -> None:
        super().__init__(message)
        self.job_id = job_id
        self.status = status


class OpenRouterBatchClient:
    """Submit one chat request through OpenRouter's asynchronous Batch API."""

    _TERMINAL = frozenset({"completed", "failed", "cancelled", "expired"})

    def __init__(
        self,
        *,
        api_key: str,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = "https://openrouter.ai/api",
        poll_interval_seconds: float = 10.0,
        timeout_seconds: float = 3600.0,
    ) -> None:
        self.api_key = api_key
        self._http_client = http_client
        self.base_url = base_url.rstrip("/")
        self.poll_interval_seconds = poll_interval_seconds
        self.timeout_seconds = timeout_seconds

    @property
    def client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
        return self._http_client

    @property
    def headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/claw",
            "X-Title": "CLAW",
        }

    async def submit(
        self,
        *,
        messages: list[LLMMessage],
        requested_model: str,
        custom_id: str,
        max_tokens: int,
        response_format: dict | None = None,
        reasoning: dict | None = None,
        seed: int | None = None,
    ) -> BatchSubmission:
        """Submit one batch and return the identity that must be persisted."""
        if not requested_model.endswith(":batch"):
            raise ValueError("Batch transport requires a model ID ending in ':batch'")
        base_model = requested_model.removesuffix(":batch")
        body: dict[str, Any] = {
            "model": base_model,
            "messages": [message.to_dict() for message in messages],
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            body["response_format"] = response_format
        if reasoning is not None:
            body["reasoning"] = reasoning
        if seed is not None:
            body["seed"] = seed
        payload = {
            "endpoint": "/v1/chat/completions",
            "model": base_model,
            "requests": [{"custom_id": custom_id, "body": body}],
        }
        created_response = await self.client.post(
            f"{self.base_url}/beta/batches",
            headers=self.headers,
            json=payload,
        )
        created_response.raise_for_status()
        created = created_response.json()
        job_id = str(created.get("id") or "")
        if not job_id:
            raise RuntimeError("OpenRouter Batch API returned no job id")
        return BatchSubmission(
            job_id=job_id,
            requested_model=requested_model,
            custom_id=custom_id,
        )

    async def poll(self, *, submission: BatchSubmission) -> BatchCompletion:
        """Poll a new or restored submission without creating another job."""
        job_id = submission.job_id
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout_seconds
        batch: dict[str, Any] = {"id": job_id, "status": "submitted"}
        while str(batch.get("status")) not in self._TERMINAL:
            if loop.time() >= deadline:
                raise BatchJobError(
                    f"OpenRouter batch {job_id} timed out",
                    job_id=job_id,
                    status="timed_out",
                )
            if self.poll_interval_seconds:
                await asyncio.sleep(self.poll_interval_seconds)
            try:
                response = await self.client.get(
                    f"{self.base_url}/beta/batches/{job_id}",
                    headers=self.headers,
                )
                response.raise_for_status()
                batch = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise BatchJobError(
                    f"OpenRouter batch {job_id} polling failed: {exc}",
                    job_id=job_id,
                    status="submitted",
                ) from exc

        status = str(batch.get("status"))
        if status != "completed":
            detail = batch.get("errors") or batch.get("error") or "no provider detail"
            raise BatchJobError(
                f"OpenRouter batch {job_id} ended {status}: {detail}",
                job_id=job_id,
                status=status,
            )
        try:
            response = _parse_batch_result(batch, custom_id=submission.custom_id)
        except Exception as exc:
            raise BatchJobError(
                str(exc),
                job_id=job_id,
                status="failed",
            ) from exc
        compatibility = BatchCompatibilityReceipt(
            model_id=submission.requested_model,
            status="completed",
            transport="queued-job",
            job_id=job_id,
            synchronous_latency_seconds=None,
            retention_days=submission.retention_days,
            detail="OpenRouter retains batch inputs and results for 30 days",
        )
        return BatchCompletion(
            response=response,
            job_id=job_id,
            compatibility=compatibility,
        )

    async def complete(
        self,
        *,
        messages: list[LLMMessage],
        requested_model: str,
        custom_id: str,
        max_tokens: int,
        response_format: dict | None = None,
        reasoning: dict | None = None,
        seed: int | None = None,
    ) -> BatchCompletion:
        """Compatibility wrapper for callers that do not persist submissions."""
        submission = await self.submit(
            messages=messages,
            requested_model=requested_model,
            custom_id=custom_id,
            max_tokens=max_tokens,
            response_format=response_format,
            reasoning=reasoning,
            seed=seed,
        )
        return await self.poll(submission=submission)

    async def close(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None


def _parse_batch_result(batch: dict[str, Any], *, custom_id: str) -> LLMResponse:
    results = batch.get("results") or []
    result = next(
        (item for item in results if str(item.get("custom_id")) == custom_id),
        None,
    )
    if result is None:
        raise RuntimeError(f"Completed batch has no result for {custom_id}")
    if result.get("error"):
        raise RuntimeError(f"Batch result {custom_id} failed: {result['error']}")
    response = result.get("response") or result.get("body") or {}
    status_code = response.get("status_code", 200) if isinstance(response, dict) else 200
    body = response.get("body", response) if isinstance(response, dict) else {}
    if int(status_code) >= 400:
        raise RuntimeError(f"Batch result {custom_id} returned HTTP {status_code}: {body}")
    if not isinstance(body, dict) or not body.get("choices"):
        raise RuntimeError(f"Batch result {custom_id} has no chat completion body")

    choice = body["choices"][0]
    message = choice.get("message") or {}
    content = message.get("content")
    if content is None:
        content = ""
    usage = body.get("usage") or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    completion_details = usage.get("completion_tokens_details") or {}
    raw_cost = usage.get("cost")
    cost_usd = float(raw_cost) if raw_cost not in (None, "") else None
    return LLMResponse(
        content=content,
        model=str(body.get("model") or "unknown"),
        tokens_used=int(usage.get("total_tokens") or 0),
        raw=body,
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
        reasoning_tokens=int(completion_details.get("reasoning_tokens") or 0),
        cached_input_tokens=int(prompt_details.get("cached_tokens") or 0),
        cost_usd=cost_usd,
        cost_source="provider" if cost_usd is not None else "missing",
        request_id=body.get("id"),
        finish_reason=choice.get("finish_reason"),
        routing_metadata={"batch_id": batch.get("id")},
    )
