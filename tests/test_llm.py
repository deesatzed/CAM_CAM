"""Tests for CLAW LLM client and token tracker."""

import httpx
import pytest

from claw.llm.client import LLMClient, LLMMessage, LLMResponse, _backoff_delay, _parse_json_response
from claw.llm.token_tracker import TokenTracker
from claw.core.exceptions import ModelRejectedError, ResponseParseError


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
