from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from claw.models.catalog import ModelCatalog, OpenRouterCatalogClient

CANDIDATES = {
    "google/gemini-3.6-flash:batch",
    "qwen/qwen3.8-max",
    "~deepseek/deepseek-v4-flash-latest",
    "x-ai/grok-4.5",
    "openai/gpt-5.6-terra",
    "openai/gpt-5.6-luna",
    "z-ai/glm-5.2",
    "moonshotai/kimi-k3",
}


@pytest.fixture
def payload() -> dict:
    path = Path(__file__).parent / "fixtures" / "openrouter_models.json"
    return json.loads(path.read_text())


def test_catalog_parses_all_requested_models_and_normalizes_prices(payload: dict) -> None:
    catalog = ModelCatalog.from_payload(payload)

    assert CANDIDATES == set(catalog.entries)
    luna = catalog.require("openai/gpt-5.6-luna")
    assert luna.canonical_slug == "openai/gpt-5.6-luna-20260709"
    assert luna.pricing.prompt_per_million == pytest.approx(0.10)
    assert luna.pricing.completion_per_million == pytest.approx(0.60)
    assert luna.pricing.cached_input_per_million == pytest.approx(0.01)
    assert luna.max_completion_tokens == 128000
    assert luna.supports("structured_outputs")


def test_catalog_preserves_alias_batch_and_threshold_override(payload: dict) -> None:
    catalog = ModelCatalog.from_payload(payload)

    deepseek = catalog.require("~deepseek/deepseek-v4-flash-latest")
    assert deepseek.requested_id.startswith("~")
    assert deepseek.pricing.prompt_per_million == pytest.approx(0.0896)

    gemini = catalog.require("google/gemini-3.6-flash:batch")
    assert gemini.is_batch is True

    grok = catalog.require("x-ai/grok-4.5")
    assert grok.pricing.overrides == [
        {
            "min_prompt_tokens": 200000,
            "prompt_per_million": 4.0,
            "completion_per_million": 12.0,
        }
    ]


def test_catalog_digest_is_stable_and_changes_with_material_data(payload: dict) -> None:
    first = ModelCatalog.from_payload(payload)
    reordered = {"data": list(reversed(payload["data"]))}
    second = ModelCatalog.from_payload(reordered)
    assert first.digest == second.digest

    changed = json.loads(json.dumps(payload))
    changed["data"][0]["pricing"]["prompt"] = "0.0000002"
    third = ModelCatalog.from_payload(changed)
    assert third.digest != first.digest


def test_catalog_rejects_malformed_payloads_and_unknown_models(payload: dict) -> None:
    with pytest.raises(ValidationError):
        ModelCatalog.from_payload({"not_data": []})
    with pytest.raises(ValidationError):
        ModelCatalog.from_payload({"data": [{"id": "broken"}]})
    with pytest.raises(KeyError, match="not/found"):
        ModelCatalog.from_payload(payload).require("not/found")


async def test_client_uses_public_models_endpoint_without_auth_headers(payload: dict) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        catalog = await OpenRouterCatalogClient(http_client=http_client).fetch()

    assert seen == {
        "url": "https://openrouter.ai/api/v1/models",
        "authorization": None,
    }
    assert catalog.require("z-ai/glm-5.2").context_length == 1048576
