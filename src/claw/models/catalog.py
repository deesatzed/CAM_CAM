"""Typed access to OpenRouter's public model catalog."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field


def _per_million(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value) * 1_000_000


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class ModelPricing(BaseModel):
    """OpenRouter token prices normalized to US dollars per million tokens."""

    model_config = ConfigDict(frozen=True)

    prompt_per_million: float = 0.0
    completion_per_million: float = 0.0
    cached_input_per_million: float | None = None
    cached_input_write_per_million: float | None = None
    reasoning_per_million: float | None = None
    request_price: float | None = None
    overrides: list[dict[str, Any]] = Field(default_factory=list)


class ModelReasoning(BaseModel):
    """Normalized reasoning controls advertised by an OpenRouter model."""

    model_config = ConfigDict(frozen=True)

    mandatory: bool = False
    default_enabled: bool | None = None
    supported_efforts: tuple[str, ...] = ()
    default_effort: str | None = None
    supports_max_tokens: bool | None = None

    def lowest_supported_effort(self) -> str | None:
        """Choose the least expensive non-disabled effort the model accepts."""
        supported = set(self.supported_efforts)
        for effort in ("minimal", "low", "medium", "high", "max", "xhigh"):
            if effort in supported:
                return effort
        return self.default_effort


class ModelCatalogEntry(BaseModel):
    """Normalized facts for one OpenRouter model identifier."""

    model_config = ConfigDict(frozen=True)

    requested_id: str
    canonical_slug: str | None = None
    name: str
    context_length: int
    max_completion_tokens: int | None = None
    supported_parameters: frozenset[str] = Field(default_factory=frozenset)
    pricing: ModelPricing
    reasoning: ModelReasoning | None = None
    expiration_date: str | None = None
    catalog_digest: str

    @property
    def is_batch(self) -> bool:
        return self.requested_id.endswith(":batch")

    def supports(self, parameter: str) -> bool:
        return parameter in self.supported_parameters


class _RawCatalogEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    canonical_slug: str | None = None
    name: str
    context_length: int
    top_provider: dict[str, Any] = Field(default_factory=dict)
    pricing: dict[str, Any]
    supported_parameters: list[str] = Field(default_factory=list)
    reasoning: dict[str, Any] | None = None
    expiration_date: str | None = None


class _RawCatalogPayload(BaseModel):
    data: list[_RawCatalogEntry]


class ModelCatalog(BaseModel):
    """Stable, lookup-friendly snapshot of the OpenRouter model catalog."""

    model_config = ConfigDict(frozen=True)

    entries: dict[str, ModelCatalogEntry]
    digest: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ModelCatalog":
        raw_payload = _RawCatalogPayload.model_validate(payload)
        entries: dict[str, ModelCatalogEntry] = {}
        for raw in raw_payload.data:
            pricing = raw.pricing
            overrides: list[dict[str, Any]] = []
            for override in pricing.get("overrides", []):
                normalized: dict[str, Any] = {}
                if "min_prompt_tokens" in override:
                    normalized["min_prompt_tokens"] = int(override["min_prompt_tokens"])
                if "prompt" in override:
                    normalized["prompt_per_million"] = _per_million(override["prompt"])
                if "completion" in override:
                    normalized["completion_per_million"] = _per_million(
                        override["completion"]
                    )
                overrides.append(normalized)

            normalized_entry = {
                "requested_id": raw.id,
                "canonical_slug": raw.canonical_slug,
                "name": raw.name,
                "context_length": raw.context_length,
                "max_completion_tokens": raw.top_provider.get("max_completion_tokens"),
                "supported_parameters": sorted(set(raw.supported_parameters)),
                "pricing": {
                    "prompt_per_million": _per_million(pricing.get("prompt")) or 0.0,
                    "completion_per_million": (
                        _per_million(pricing.get("completion")) or 0.0
                    ),
                    "cached_input_per_million": _per_million(
                        pricing.get("input_cache_read")
                    ),
                    "cached_input_write_per_million": _per_million(
                        pricing.get("input_cache_write")
                    ),
                    "reasoning_per_million": _per_million(
                        pricing.get("internal_reasoning")
                    ),
                    "request_price": (
                        float(pricing["request"])
                        if pricing.get("request") not in (None, "")
                        else None
                    ),
                    "overrides": overrides,
                },
                "reasoning": raw.reasoning,
                "expiration_date": raw.expiration_date,
            }
            entries[raw.id] = ModelCatalogEntry(
                **normalized_entry,
                catalog_digest=_digest(normalized_entry),
            )

        digest_payload = {
            model_id: entries[model_id].model_dump(mode="json")
            for model_id in sorted(entries)
        }
        return cls(entries=entries, digest=_digest(digest_payload))

    def require(self, model_id: str) -> ModelCatalogEntry:
        try:
            return self.entries[model_id]
        except KeyError as exc:
            raise KeyError(f"Model not found in catalog: {model_id}") from exc


class OpenRouterCatalogClient:
    """Fetch the public OpenRouter catalog without sending credentials."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout_seconds: float = 20.0,
    ) -> None:
        self._http_client = http_client
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)

    async def fetch(self) -> ModelCatalog:
        if self._http_client is not None:
            response = await self._http_client.get(f"{self._base_url}/models")
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(f"{self._base_url}/models")
        response.raise_for_status()
        return ModelCatalog.from_payload(response.json())
