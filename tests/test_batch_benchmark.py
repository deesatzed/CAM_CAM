from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from claw.llm.client import LLMMessage
from claw.models.batch import (
    BatchCompatibilityReceipt,
    BatchJobError,
    BatchSubmission,
    OpenRouterBatchClient,
    _parse_batch_result,
)


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


async def test_openrouter_batch_client_uses_base_model_and_polls_inline_result() -> None:
    requests: list[httpx.Request] = []
    poll_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"id": "batch-123", "status": "validating"})
        poll_count += 1
        if poll_count == 1:
            return httpx.Response(200, json={"id": "batch-123", "status": "in_progress"})
        return httpx.Response(
            200,
            json={
                "id": "batch-123",
                "status": "completed",
                "results": [
                    {
                        "custom_id": "call-123",
                        "response": {
                            "status_code": 200,
                            "body": {
                                "id": "gen-123",
                                "model": "google/gemini-3.6-flash-20260721",
                                "choices": [
                                    {
                                        "message": {"content": "[]"},
                                        "finish_reason": "stop",
                                    }
                                ],
                                "usage": {
                                    "prompt_tokens": 100,
                                    "completion_tokens": 20,
                                    "total_tokens": 120,
                                    "cost": 0.00015,
                                },
                            },
                        },
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await OpenRouterBatchClient(
            api_key="test-key",
            http_client=http_client,
            poll_interval_seconds=0,
        ).complete(
            messages=[LLMMessage(role="user", content="mine this")],
            requested_model="google/gemini-3.6-flash:batch",
            custom_id="call-123",
            max_tokens=4096,
            response_format={"type": "json_object"},
            reasoning={"effort": "minimal", "exclude": True},
            seed=0,
        )

    submitted = json.loads(requests[0].content)
    assert str(requests[0].url) == "https://openrouter.ai/api/beta/batches"
    assert submitted["model"] == "google/gemini-3.6-flash"
    assert submitted["requests"][0]["body"]["model"] == "google/gemini-3.6-flash"
    assert submitted["requests"][0]["body"]["max_tokens"] == 4096
    assert submitted["requests"][0]["body"]["response_format"] == {
        "type": "json_object"
    }
    assert submitted["requests"][0]["body"]["reasoning"] == {
        "effort": "minimal",
        "exclude": True,
    }
    assert submitted["requests"][0]["body"]["seed"] == 0
    assert "temperature" not in submitted["requests"][0]["body"]
    assert result.job_id == "batch-123"
    assert result.response.content == "[]"
    assert result.response.cost_usd == pytest.approx(0.00015)
    assert result.compatibility.transport == "queued-job"
    assert result.compatibility.synchronous_latency_seconds is None
    assert result.compatibility.retention_days == 30


def test_batch_result_does_not_promote_reasoning_to_final_answer() -> None:
    result = _parse_batch_result(
        {
            "id": "batch-reasoning-only",
            "results": [
                {
                    "custom_id": "call-reasoning-only",
                    "response": {
                        "status_code": 200,
                        "body": {
                            "id": "gen-reasoning-only",
                            "model": "qwen/qwen3.8-max",
                            "choices": [
                                {
                                    "message": {
                                        "content": None,
                                        "reasoning": "analysis without a final answer",
                                    },
                                    "finish_reason": "length",
                                }
                            ],
                            "usage": {},
                        },
                    },
                }
            ],
        },
        custom_id="call-reasoning-only",
    )

    assert result.content == ""
    assert result.finish_reason == "length"


@pytest.mark.parametrize("status", ["failed", "cancelled", "expired"])
async def test_openrouter_batch_client_reports_terminal_failure(status: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "batch-bad", "status": "validating"})
        return httpx.Response(
            200,
            json={"id": "batch-bad", "status": status, "errors": ["provider failed"]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenRouterBatchClient(
            api_key="test-key",
            http_client=http_client,
            poll_interval_seconds=0,
        )
        with pytest.raises(RuntimeError, match=f"batch-bad.*{status}"):
            await client.complete(
                messages=[LLMMessage(role="user", content="mine")],
                requested_model="google/gemini-3.6-flash:batch",
                custom_id="call-bad",
                max_tokens=100,
            )


async def test_batch_timeout_preserves_submitted_job_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "batch-timeout", "status": "validating"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenRouterBatchClient(
            api_key="test-key",
            http_client=http_client,
            poll_interval_seconds=0,
            timeout_seconds=-1,
        )
        with pytest.raises(BatchJobError) as captured:
            await client.complete(
                messages=[LLMMessage(role="user", content="mine")],
                requested_model="google/gemini-3.6-flash:batch",
                custom_id="call-timeout",
                max_tokens=100,
            )

    assert captured.value.job_id == "batch-timeout"
    assert captured.value.status == "timed_out"


async def test_batch_poll_network_failure_preserves_submission_for_resume() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"id": "batch-resume", "status": "validating"},
            )
        raise httpx.ConnectError("temporary network failure", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenRouterBatchClient(
            api_key="test-key",
            http_client=http_client,
            poll_interval_seconds=0,
        )
        submission = await client.submit(
            messages=[LLMMessage(role="user", content="mine")],
            requested_model="google/gemini-3.6-flash:batch",
            custom_id="call-resume",
            max_tokens=100,
        )
        assert submission == BatchSubmission(
            job_id="batch-resume",
            requested_model="google/gemini-3.6-flash:batch",
            custom_id="call-resume",
        )
        with pytest.raises(BatchJobError) as captured:
            await client.poll(submission=submission)

    assert captured.value.job_id == "batch-resume"
    assert captured.value.status == "submitted"
    assert [request.method for request in requests] == ["POST", "GET"]
