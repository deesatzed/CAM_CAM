from __future__ import annotations

from pathlib import Path

import pytest

from claw.core.config import AgentConfig, ClawConfig, DatabaseConfig, LLMConfig, load_config
from claw.models.profiles import (
    ModelProfileRegistry,
    load_model_profiles,
    promote_role,
    resolve_effective_config,
    rollback_promotion,
)


def _write_registry(path: Path) -> None:
    path.write_text(
        """
schema_version = 1
active_profile = "legacy-import"

[profiles.legacy-import.roles]
mining-budget = "z-ai/glm-5.2"
mining-quality = "z-ai/glm-5.2"
mining-batch = "google/gemini-3.6-flash:batch"
verification = "x-ai/grok-4.3"
fallback = "openai/gpt-4.1-mini"
""".strip()
        + "\n"
    )


def test_loads_versioned_role_registry(tmp_path: Path) -> None:
    path = tmp_path / "model_profiles.toml"
    _write_registry(path)

    registry = load_model_profiles(path)

    assert registry.schema_version == 1
    assert registry.active_profile == "legacy-import"
    assert registry.resolve("mining-budget") == "z-ai/glm-5.2"
    assert registry.resolve("mining-batch") == "google/gemini-3.6-flash:batch"


def test_registry_rejects_unknown_roles_and_missing_active_profile() -> None:
    with pytest.raises(ValueError, match="Unknown model role"):
        ModelProfileRegistry.model_validate(
            {
                "schema_version": 1,
                "active_profile": "bad",
                "profiles": {"bad": {"roles": {"root-db": "not/a-model"}}},
            }
        )

    with pytest.raises(ValueError, match="Active profile"):
        ModelProfileRegistry.model_validate(
            {
                "schema_version": 1,
                "active_profile": "missing",
                "profiles": {"present": {"roles": {"fallback": "model/fallback"}}},
            }
        )


def test_effective_config_maps_roles_without_changing_database() -> None:
    base = ClawConfig(
        database=DatabaseConfig(db_path="/absolute/live/claw.db"),
        llm=LLMConfig(fallback_models=["legacy/fallback"]),
        agents={
            "claude": AgentConfig(model="legacy/quality"),
            "codex": AgentConfig(model="legacy/budget"),
            "gemini": AgentConfig(model="legacy/batch"),
            "grok": AgentConfig(model="legacy/verify"),
        },
    )
    registry = ModelProfileRegistry.model_validate(
        {
            "schema_version": 1,
            "active_profile": "selected",
            "profiles": {
                "selected": {
                    "roles": {
                        "mining-budget": "new/budget",
                        "mining-quality": "new/quality",
                        "mining-batch": "new/batch",
                        "verification": "new/verify",
                        "fallback": "new/fallback",
                    }
                }
            },
        }
    )

    effective = resolve_effective_config(base, registry)

    assert effective.database.db_path == "/absolute/live/claw.db"
    assert base.agents["claude"].model == "legacy/quality"
    assert effective.agents["claude"].model == "new/quality"
    assert effective.agents["codex"].model == "new/budget"
    assert effective.agents["gemini"].model == "new/batch"
    assert effective.agents["grok"].model == "new/verify"
    assert effective.llm.fallback_models == ["new/fallback"]


def test_load_config_applies_profiles_only_when_explicitly_selected(tmp_path: Path) -> None:
    config_path = tmp_path / "claw.toml"
    config_path.write_text(
        """
[database]
db_path = "/pinned/corpus/claw.db"

[agents.claude]
model = "legacy/quality"
""".strip()
        + "\n"
    )
    profile_path = tmp_path / "model_profiles.toml"
    _write_registry(profile_path)

    legacy = load_config(config_path)
    selected = load_config(config_path, model_profiles_path=profile_path)

    assert legacy.agents["claude"].model == "legacy/quality"
    assert selected.agents["claude"].model == "z-ai/glm-5.2"
    assert selected.database.db_path == "/pinned/corpus/claw.db"


async def test_factory_forwards_explicit_model_profile_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from claw.core.factory import ClawFactory

    captured = {}

    class ConfigStopError(RuntimeError):
        pass

    def fake_load_config(config_path, *, model_profiles_path=None):
        captured["config_path"] = config_path
        captured["model_profiles_path"] = model_profiles_path
        raise ConfigStopError

    monkeypatch.setattr("claw.core.factory.load_config", fake_load_config)

    with pytest.raises(ConfigStopError):
        await ClawFactory.create(
            config_path=tmp_path / "claw.toml",
            model_profiles_path=tmp_path / "model_profiles.toml",
        )

    assert captured == {
        "config_path": tmp_path / "claw.toml",
        "model_profiles_path": tmp_path / "model_profiles.toml",
    }


def test_promote_and_rollback_are_atomic_and_validate_model(tmp_path: Path) -> None:
    path = tmp_path / "model_profiles.toml"
    _write_registry(path)

    with pytest.raises(ValueError, match="not in the approved catalog"):
        promote_role(
            path,
            "legacy-import",
            "mining-budget",
            "unknown/model",
            allowed_model_ids={"known/model"},
        )

    receipt = promote_role(
        path,
        "legacy-import",
        "mining-budget",
        "openai/gpt-5.6-luna",
        allowed_model_ids={"openai/gpt-5.6-luna"},
    )
    assert receipt.previous_model == "z-ai/glm-5.2"
    assert receipt.new_model == "openai/gpt-5.6-luna"
    assert load_model_profiles(path).resolve("mining-budget") == "openai/gpt-5.6-luna"
    assert not path.with_suffix(".tmp").exists()

    rollback_promotion(path, receipt)
    assert load_model_profiles(path).resolve("mining-budget") == "z-ai/glm-5.2"
