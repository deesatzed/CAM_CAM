"""Role-based model profile registry with atomic promotion and rollback."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import toml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from claw.core.config import AgentConfig, ClawConfig

MODEL_ROLES = frozenset(
    {
        "mining-budget",
        "mining-quality",
        "mining-batch",
        "verification",
        "fallback",
    }
)

ROLE_AGENT_SLOTS = {
    "mining-quality": "claude",
    "mining-budget": "codex",
    "mining-batch": "gemini",
    "verification": "grok",
}


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class ModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roles: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_roles(self) -> "ModelProfile":
        unknown = sorted(set(self.roles) - MODEL_ROLES)
        if unknown:
            raise ValueError(f"Unknown model role(s): {', '.join(unknown)}")
        return self


class ModelProfileRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    active_profile: str
    profiles: dict[str, ModelProfile]

    @model_validator(mode="after")
    def validate_registry(self) -> "ModelProfileRegistry":
        if self.schema_version != 1:
            raise ValueError(f"Unsupported model profile schema: {self.schema_version}")
        if self.active_profile not in self.profiles:
            raise ValueError(f"Active profile does not exist: {self.active_profile}")
        return self

    def resolve(self, role: str, profile: str | None = None) -> str:
        if role not in MODEL_ROLES:
            raise ValueError(f"Unknown model role: {role}")
        profile_name = profile or self.active_profile
        try:
            selected = self.profiles[profile_name]
        except KeyError as exc:
            raise ValueError(f"Unknown model profile: {profile_name}") from exc
        try:
            return selected.roles[role]
        except KeyError as exc:
            raise ValueError(f"Role {role!r} is not assigned in profile {profile_name!r}") from exc


class PromotionReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    registry_path: str
    profile: str
    role: str
    previous_model: str
    new_model: str
    before_digest: str
    after_digest: str
    promoted_at: str


def load_model_profiles(path: Path) -> ModelProfileRegistry:
    """Load and validate one explicit model-profile registry."""
    raw = toml.load(path)
    return ModelProfileRegistry.model_validate(raw)


def resolve_effective_config(
    base: ClawConfig,
    registry: ModelProfileRegistry,
) -> ClawConfig:
    """Apply model roles to a deep copy without changing base runtime authority."""
    effective = base.model_copy(deep=True)
    active = registry.profiles[registry.active_profile]
    for role, agent_slot in ROLE_AGENT_SLOTS.items():
        model_id = active.roles.get(role)
        if not model_id:
            continue
        if agent_slot not in effective.agents:
            effective.agents[agent_slot] = AgentConfig()
        effective.agents[agent_slot].model = model_id

    fallback = active.roles.get("fallback")
    if fallback:
        effective.llm.fallback_models = [fallback]
    return effective


def resolve_exact_mining_config(base: ClawConfig, exact_model: str) -> ClawConfig:
    """Force every enabled remote mining route onto one exact model."""
    model_id = exact_model.strip()
    if not model_id:
        raise ValueError("Exact mining model must not be empty")

    effective = base.model_copy(deep=True)
    for agent in effective.agents.values():
        if agent.enabled and agent.mode != "local":
            agent.model = model_id
    effective.llm.fallback_models = []
    return effective


def _write_registry(path: Path, registry: ModelProfileRegistry) -> None:
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(toml.dumps(registry.model_dump(mode="python")))
    temp_path.replace(path)


def activate_profile(path: Path, profile: str) -> ModelProfileRegistry:
    """Atomically move the active pointer without changing any role assignments."""
    registry = load_model_profiles(path)
    if profile not in registry.profiles:
        raise ValueError(f"Unknown model profile: {profile}")
    registry.active_profile = profile
    _write_registry(path, registry)
    return registry


def promote_role(
    path: Path,
    profile: str,
    role: str,
    model_id: str,
    *,
    allowed_model_ids: set[str] | frozenset[str] | None = None,
) -> PromotionReceipt:
    """Atomically replace one role assignment and return rollback evidence."""
    if role not in MODEL_ROLES:
        raise ValueError(f"Unknown model role: {role}")
    if allowed_model_ids is not None and model_id not in allowed_model_ids:
        raise ValueError(f"Model is not in the approved catalog: {model_id}")

    registry = load_model_profiles(path)
    if profile not in registry.profiles:
        raise ValueError(f"Unknown model profile: {profile}")
    previous_model = registry.profiles[profile].roles.get(role, "")
    before_data = registry.model_dump(mode="json")
    registry.profiles[profile].roles[role] = model_id
    after_data = registry.model_dump(mode="json")
    receipt = PromotionReceipt(
        registry_path=str(path.resolve()),
        profile=profile,
        role=role,
        previous_model=previous_model,
        new_model=model_id,
        before_digest=_digest(before_data),
        after_digest=_digest(after_data),
        promoted_at=datetime.now(UTC).isoformat(),
    )
    _write_registry(path, registry)
    return receipt


def rollback_promotion(path: Path, receipt: PromotionReceipt) -> None:
    """Undo one promotion only if the registry still matches its receipt."""
    registry = load_model_profiles(path)
    current_digest = _digest(registry.model_dump(mode="json"))
    if current_digest != receipt.after_digest:
        raise ValueError("Registry changed after promotion; refusing rollback")
    current_model = registry.profiles[receipt.profile].roles.get(receipt.role, "")
    if current_model != receipt.new_model:
        raise ValueError("Promoted role no longer matches receipt; refusing rollback")
    registry.profiles[receipt.profile].roles[receipt.role] = receipt.previous_model
    _write_registry(path, registry)
