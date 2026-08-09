"""Tests for CLAW LLM client and token tracker."""

from types import SimpleNamespace

import httpx
import pytest

from claw.core.config import LLMConfig
from claw.core.exceptions import ModelRejectedError, ResponseParseError
from claw.llm.client import LLMClient, LLMMessage, LLMResponse, _backoff_delay, _parse_json_response
from claw.llm.token_tracker import TokenTracker
from claw.mining_budget import MiningBudgetExceededError, MiningBudgetViolationError


class TestLLMMessage:
    def test_to_dict(self):
        msg = LLMMessage("user", "Hello")
        assert msg.to_dict() == {"role": "user", "content": "Hello"}


class TestLLMResponse:
    def test_fields(self):
        resp = LLMResponse(
            content="answer",
            model="test-model",
            tokens_used=100,
            input_tokens=60,
            output_tokens=40,
        )
        assert resp.content == "answer"
        assert resp.model == "test-model"
        assert resp.tokens_used == 100


class TestBackoff:
    def test_exponential(self):
        # Base delay is exponential; jitter adds up to 25%
        d0 = _backoff_delay(0)
        d1 = _backoff_delay(1)
        d2 = _backoff_delay(2)
        assert 2.0 <= d0 <= 2.5   # 2.0 + up to 0.5 jitter
        assert 4.0 <= d1 <= 5.0   # 4.0 + up to 1.0 jitter
        assert 8.0 <= d2 <= 10.0  # 8.0 + up to 2.0 jitter

    def test_cap_at_60(self):
        d = _backoff_delay(10)
        assert 60.0 <= d <= 75.0  # 60.0 + up to 15.0 jitter (25%)


class TestParseJson:
    def test_plain_json(self):
        result = _parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_markdown_fenced_json(self):
        result = _parse_json_response('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_invalid_json_raises(self):
        with pytest.raises(ResponseParseError):
            _parse_json_response("not json")

    def test_recovers_from_raw_newline_inside_json_string(self):
        raw = '{"ideas": [{"title": "Agent Benchmark Orchestrator", "tagline": "line one\nline two"}]}'
        result = _parse_json_response(raw)
        assert result["ideas"][0]["tagline"] == "line one\nline two"

    def test_recovers_from_raw_tab_inside_json_string(self):
        raw = '{"ideas": [{"title": "Tabbed", "tagline": "alpha\tbeta"}]}'
        result = _parse_json_response(raw)
        assert result["ideas"][0]["tagline"] == "alpha\tbeta"


class TestLLMClientCooldown:
    async def test_complete_sends_explicit_reasoning_and_seed(self):
        class FakeHTTPClient:
            is_closed = False

            def __init__(self):
                self.payload = None

            async def post(self, url, json, headers):
                self.payload = json
                return httpx.Response(
                    200,
                    request=httpx.Request("POST", url),
                    json={
                        "id": "gen-controlled",
                        "model": "qwen/qwen3.8-max",
                        "choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
                    },
                )

        fake = FakeHTTPClient()
        client = LLMClient(api_key="test-key")
        client._client = fake

        await client.complete(
            [LLMMessage("user", "mine")],
            model="qwen/qwen3.8-max",
            reasoning={"effort": "minimal", "exclude": True},
            seed=0,
        )

        assert fake.payload["reasoning"] == {"effort": "minimal", "exclude": True}
        assert fake.payload["seed"] == 0

    async def test_null_content_does_not_promote_reasoning_to_final_answer(self):
        class FakeHTTPClient:
            is_closed = False

            async def post(self, url, json, headers):
                return httpx.Response(
                    200,
                    request=httpx.Request("POST", url),
                    json={
                        "id": "gen-reasoning-only",
                        "model": "qwen/qwen3.8-max",
                        "choices": [
                            {
                                "message": {
                                    "content": None,
                                    "reasoning": "I should eventually return JSON",
                                },
                                "finish_reason": "length",
                            }
                        ],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
                    },
                )

        client = LLMClient(api_key="test-key")
        client._client = FakeHTTPClient()

        response = await client.complete(
            [LLMMessage("user", "mine")],
            model="qwen/qwen3.8-max",
        )

        assert response.content == ""
        assert response.finish_reason == "length"

    async def test_complete_can_omit_unsupported_temperature_parameter(self):
        class FakeHTTPClient:
            is_closed = False

            def __init__(self):
                self.payload = None

            async def post(self, url, json, headers):
                self.payload = json
                return httpx.Response(
                    200,
                    request=httpx.Request("POST", url),
                    json={
                        "id": "gen-batch",
                        "model": "google/gemini-3.6-flash:batch",
                        "choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
                    },
                )

        fake = FakeHTTPClient()
        client = LLMClient(api_key="test-key")
        client._client = fake
        await client.complete(
            [LLMMessage("user", "hello")],
            model="google/gemini-3.6-flash:batch",
            include_temperature=False,
        )

        assert "temperature" not in fake.payload

    async def test_response_parses_openrouter_usage_and_cost_receipt(self):
        class FakeHTTPClient:
            is_closed = False

            async def post(self, url, json, headers):
                return httpx.Response(
                    200,
                    request=httpx.Request("POST", url),
                    json={
                        "id": "gen-123",
                        "model": "deepseek/deepseek-v4-flash-0731",
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
                            "cost": 0.00123,
                            "prompt_tokens_details": {"cached_tokens": 10},
                            "completion_tokens_details": {"reasoning_tokens": 5},
                        },
                    },
                )

        client = LLMClient(api_key="test-key")
        client._client = FakeHTTPClient()
        response = await client.complete(
            [LLMMessage("user", "hello")],
            model="~deepseek/deepseek-v4-flash-latest",
        )

        assert response.input_tokens == 100
        assert response.output_tokens == 20
        assert response.reasoning_tokens == 5
        assert response.cached_input_tokens == 10
        assert response.cost_usd == 0.00123
        assert response.cost_source == "provider"
        assert response.request_id == "gen-123"
        assert response.finish_reason == "stop"

    async def test_provider_400_is_non_retryable_model_rejection(self):
        class FakeHTTPClient:
            is_closed = False

            def __init__(self):
                self.calls = 0

            async def post(self, url, json, headers):
                self.calls += 1
                return httpx.Response(
                    400,
                    request=httpx.Request("POST", url),
                    json={"error": {"message": "bad model route"}},
                )

        fake = FakeHTTPClient()
        client = LLMClient(api_key="test-key")
        client._client = fake

        with pytest.raises(ModelRejectedError, match="bad model route"):
            await client.complete(
                [LLMMessage("user", "hello")],
                model="openai/gpt-mini-latest",
            )

        assert fake.calls == 1

    async def test_budget_reserves_before_each_http_attempt(self):
        class RecordingBudget:
            exact_model = "x-ai/grok-4.5"

            def __init__(self):
                self.events = []
                self.next_attempt = 0

            def reserve_attempt(self, payload):
                self.events.append("reserve")
                self.next_attempt += 1
                guarded = dict(payload)
                guarded["provider"] = {"allow_fallbacks": False}
                return SimpleNamespace(attempt_id=str(self.next_attempt)), guarded

            def record_failure(self, attempt_id, error):
                self.events.append("fail")

            def reconcile_completed(self, attempt_id, **kwargs):
                self.events.append("complete")

        class RetryThenSuccessClient:
            is_closed = False

            def __init__(self):
                self.calls = 0

            async def post(self, url, json, headers):
                self.calls += 1
                if self.calls == 1:
                    return httpx.Response(
                        500,
                        request=httpx.Request("POST", url),
                        json={"error": {"message": "transient"}},
                    )
                return httpx.Response(
                    200,
                    request=httpx.Request("POST", url),
                    json={
                        "id": "gen-budgeted",
                        "model": "x-ai/grok-4.5",
                        "choices": [
                            {"message": {"content": "[]"}, "finish_reason": "stop"}
                        ],
                        "usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 2,
                            "total_tokens": 12,
                            "cost": 0.001,
                        },
                    },
                )

        budget = RecordingBudget()
        client = LLMClient(
            LLMConfig(max_retries=2, backoff_base=0),
            api_key="test-key",
            budget_controller=budget,
        )
        client._client = RetryThenSuccessClient()

        await client.complete(
            [LLMMessage("user", "mine")],
            model="x-ai/grok-4.5",
        )

        assert budget.events == ["reserve", "fail", "reserve", "complete"]

    async def test_budget_rejection_makes_no_http_call(self):
        class RejectingBudget:
            exact_model = "x-ai/grok-4.5"

            def reserve_attempt(self, payload):
                raise MiningBudgetExceededError("no room")

        class NeverCalledClient:
            is_closed = False

            def __init__(self):
                self.calls = 0

            async def post(self, url, json, headers):
                self.calls += 1
                raise AssertionError("HTTP must not be called")

        transport = NeverCalledClient()
        client = LLMClient(
            api_key="test-key",
            budget_controller=RejectingBudget(),
        )
        client._client = transport

        with pytest.raises(MiningBudgetExceededError, match="no room"):
            await client.complete(
                [LLMMessage("user", "mine")],
                model="x-ai/grok-4.5",
            )

        assert transport.calls == 0

    async def test_budget_guarded_provider_payload_and_provider_receipt(self):
        class RecordingBudget:
            exact_model = "x-ai/grok-4.5"

            def __init__(self):
                self.completed = None

            def reserve_attempt(self, payload):
                guarded = dict(payload)
                guarded["provider"] = {
                    "allow_fallbacks": False,
                    "max_price": {"prompt": 3.0, "completion": 15.0},
                }
                return SimpleNamespace(attempt_id="attempt-1"), guarded

            def record_failure(self, attempt_id, error):
                raise AssertionError(error)

            def reconcile_completed(self, attempt_id, **kwargs):
                self.completed = (attempt_id, kwargs)

        class CapturingClient:
            is_closed = False

            def __init__(self):
                self.payload = None

            async def post(self, url, json, headers):
                self.payload = json
                return httpx.Response(
                    200,
                    request=httpx.Request("POST", url),
                    json={
                        "id": "gen-actual",
                        "model": "x-ai/grok-4.5",
                        "choices": [
                            {"message": {"content": "[]"}, "finish_reason": "stop"}
                        ],
                        "usage": {
                            "prompt_tokens": 100,
                            "completion_tokens": 20,
                            "total_tokens": 120,
                            "cost": 0.0123,
                        },
                    },
                )

        budget = RecordingBudget()
        transport = CapturingClient()
        client = LLMClient(api_key="test-key", budget_controller=budget)
        client._client = transport

        await client.complete(
            [LLMMessage("user", "mine")],
            model="x-ai/grok-4.5",
        )

        assert transport.payload["provider"]["allow_fallbacks"] is False
        assert budget.completed == (
            "attempt-1",
            {
                "returned_model": "x-ai/grok-4.5",
                "actual_cost_usd": 0.0123,
                "cost_source": "provider",
                "request_id": "gen-actual",
            },
        )

    async def test_returned_model_drift_is_reconciled_then_rejected(self):
        class RecordingBudget:
            exact_model = "x-ai/grok-4.5"

            def __init__(self):
                self.events = []

            def reserve_attempt(self, payload):
                self.events.append("reserve")
                return SimpleNamespace(attempt_id="attempt-1"), dict(payload)

            def record_failure(self, attempt_id, error):
                self.events.append("fail")

            def reconcile_completed(self, attempt_id, **kwargs):
                self.events.append("complete")

        class DriftClient:
            is_closed = False

            async def post(self, url, json, headers):
                return httpx.Response(
                    200,
                    request=httpx.Request("POST", url),
                    json={
                        "id": "gen-drift",
                        "model": "x-ai/grok-4.3",
                        "choices": [
                            {"message": {"content": "[]"}, "finish_reason": "stop"}
                        ],
                        "usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 2,
                            "total_tokens": 12,
                            "cost": 0.001,
                        },
                    },
                )

        budget = RecordingBudget()
        client = LLMClient(api_key="test-key", budget_controller=budget)
        client._client = DriftClient()

        with pytest.raises(MiningBudgetViolationError, match="returned model"):
            await client.complete(
                [LLMMessage("user", "mine")],
                model="x-ai/grok-4.5",
            )

        assert budget.events == ["reserve", "complete"]

    async def test_legacy_client_payload_has_no_provider_budget_controls(self):
        class CapturingClient:
            is_closed = False

            def __init__(self):
                self.payload = None

            async def post(self, url, json, headers):
                self.payload = json
                return httpx.Response(
                    200,
                    request=httpx.Request("POST", url),
                    json={
                        "id": "gen-legacy",
                        "model": "x-ai/grok-4.5",
                        "choices": [
                            {"message": {"content": "[]"}, "finish_reason": "stop"}
                        ],
                        "usage": {"total_tokens": 0},
                    },
                )

        transport = CapturingClient()
        client = LLMClient(api_key="test-key")
        client._client = transport

        await client.complete(
            [LLMMessage("user", "mine")],
            model="x-ai/grok-4.5",
        )

        assert "provider" not in transport.payload

    def test_cooldown_mechanism(self):
        client = LLMClient()
        # Simulate failures
        error = Exception("fail")
        client._record_model_failure("model-a", error)
        assert client._cooldown_remaining_seconds("model-a") == 0.0  # Not yet at threshold

        client._record_model_failure("model-a", error)
        assert client._cooldown_remaining_seconds("model-a") > 0.0  # Now in cooldown

    def test_success_clears_cooldown(self):
        client = LLMClient()
        error = Exception("fail")
        client._record_model_failure("model-a", error)
        client._record_model_failure("model-a", error)
        assert client._cooldown_remaining_seconds("model-a") > 0.0

        client._record_model_success("model-a")
        assert client._cooldown_remaining_seconds("model-a") == 0.0

    def test_failover_state(self):
        client = LLMClient()
        error = Exception("fail")
        client._record_model_failure("model-a", error)
        client._record_model_failure("model-a", error)

        state = client.get_model_failover_state()
        assert "model-a" in state
        assert state["model-a"]["cooldown_remaining_seconds"] > 0


class TestTokenTracker:
    async def test_record_and_totals(self):
        tracker = TokenTracker()
        tracker.set_context(task_id="t1", agent_id="claude", agent_role="builder")

        r = await tracker.record("test-model", input_tokens=1000, output_tokens=500)
        assert r.input_tokens == 1000
        assert r.total_tokens == 1500
        assert r.cost_usd > 0

        session = tracker.get_session_totals()
        assert session["call_count"] == 1
        assert session["total_input_tokens"] == 1000

    async def test_per_agent_totals(self):
        tracker = TokenTracker()
        tracker.set_context(task_id="t1", agent_id="claude")
        await tracker.record("model", input_tokens=100, output_tokens=50)

        tracker.set_context(task_id="t1", agent_id="codex")
        await tracker.record("model", input_tokens=200, output_tokens=100)

        claude_totals = tracker.get_agent_totals("claude")
        assert claude_totals["total_input_tokens"] == 100

        codex_totals = tracker.get_agent_totals("codex")
        assert codex_totals["total_input_tokens"] == 200

    async def test_cost_estimation(self):
        tracker = TokenTracker(cost_per_1k_input=0.01, cost_per_1k_output=0.03)
        tracker.set_context(agent_id="test")
        r = await tracker.record("model", input_tokens=1000, output_tokens=1000)
        expected = 0.01 + 0.03
        assert abs(r.cost_usd - expected) < 0.001
