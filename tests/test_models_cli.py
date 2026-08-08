from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from claw.cli import app
from claw.models.benchmark import MiningPromptFixture

runner = CliRunner()


def _write_config(path: Path) -> None:
    path.write_text(
        """
[database]
db_path = "/explicit/corpus/claw.db"

[agents.claude]
enabled = true
model = "legacy/quality"

[agents.codex]
enabled = true
model = "legacy/budget"
""".strip()
        + "\n"
    )


def _write_profiles(path: Path) -> None:
    path.write_text(
        """
schema_version = 1
active_profile = "selected"

[profiles.selected.roles]
mining-budget = "openai/gpt-5.6-luna"
mining-quality = "openai/gpt-5.6-terra"
mining-batch = "google/gemini-3.6-flash:batch"
verification = "x-ai/grok-4.5"
fallback = "~deepseek/deepseek-v4-flash-latest"

[profiles.alternate.roles]
mining-budget = "z-ai/glm-5.2"
mining-quality = "z-ai/glm-5.2"
verification = "x-ai/grok-4.3"
fallback = "openai/gpt-4.1-mini"
""".strip()
        + "\n"
    )


def test_models_group_exposes_expected_commands() -> None:
    result = runner.invoke(app, ["models", "--help"])

    assert result.exit_code == 0, result.output
    for command in ("current", "catalog", "profile", "set", "rollback", "benchmark"):
        assert command in result.output


def test_current_reports_paths_and_roles_without_environment_values(tmp_path: Path) -> None:
    config_path = tmp_path / "claw.toml"
    profiles_path = tmp_path / "model_profiles.toml"
    _write_config(config_path)
    _write_profiles(profiles_path)

    result = runner.invoke(
        app,
        [
            "models",
            "current",
            "--config",
            str(config_path),
            "--profiles",
            str(profiles_path),
            "--format",
            "json",
        ],
        env={"OPENROUTER_API_KEY": "must-not-be-rendered"},
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["database_path"] == "/explicit/corpus/claw.db"
    assert output["active_profile"] == "selected"
    assert output["roles"]["mining-budget"] == "openai/gpt-5.6-luna"
    assert "must-not-be-rendered" not in result.output


def test_profile_list_and_show_are_read_only(tmp_path: Path) -> None:
    profiles_path = tmp_path / "model_profiles.toml"
    _write_profiles(profiles_path)
    before = profiles_path.read_bytes()

    listed = runner.invoke(
        app,
        ["models", "profile", "list", "--profiles", str(profiles_path), "--format", "json"],
    )
    shown = runner.invoke(
        app,
        ["models", "profile", "show", "selected", "--profiles", str(profiles_path)],
    )

    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output)[0]["active"] is True
    assert shown.exit_code == 0, shown.output
    assert "openai/gpt-5.6-terra" in shown.output
    assert profiles_path.read_bytes() == before


def test_profile_use_changes_only_active_pointer(tmp_path: Path) -> None:
    profiles_path = tmp_path / "model_profiles.toml"
    _write_profiles(profiles_path)

    result = runner.invoke(
        app,
        ["models", "profile", "use", "alternate", "--profiles", str(profiles_path)],
    )

    assert result.exit_code == 0, result.output
    assert "alternate" in result.output
    assert 'active_profile = "alternate"' in profiles_path.read_text()
    assert 'mining-quality = "openai/gpt-5.6-terra"' in profiles_path.read_text()


def test_set_validates_live_catalog_and_rollback_restores_role(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from claw.models.catalog import ModelCatalog, OpenRouterCatalogClient

    profiles_path = tmp_path / "model_profiles.toml"
    receipt_path = tmp_path / "promotion.json"
    _write_profiles(profiles_path)
    payload = {
        "data": [
            {
                "id": "z-ai/glm-5.2",
                "canonical_slug": "z-ai/glm-5.2-20260616",
                "name": "Z.ai: GLM 5.2",
                "context_length": 1048576,
                "top_provider": {"max_completion_tokens": 128000},
                "pricing": {"prompt": "0.0000002058", "completion": "0.0000006468"},
                "supported_parameters": ["max_tokens", "structured_outputs"],
            }
        ]
    }

    async def fake_fetch(_self: OpenRouterCatalogClient) -> ModelCatalog:
        return ModelCatalog.from_payload(payload)

    monkeypatch.setattr(OpenRouterCatalogClient, "fetch", fake_fetch)
    promoted = runner.invoke(
        app,
        [
            "models",
            "set",
            "mining-budget",
            "z-ai/glm-5.2",
            "--profile",
            "selected",
            "--profiles",
            str(profiles_path),
            "--receipt",
            str(receipt_path),
        ],
    )

    assert promoted.exit_code == 0, promoted.output
    assert receipt_path.exists()
    assert 'mining-budget = "z-ai/glm-5.2"' in profiles_path.read_text()

    rolled_back = runner.invoke(
        app,
        [
            "models",
            "rollback",
            str(receipt_path),
            "--profiles",
            str(profiles_path),
        ],
    )
    assert rolled_back.exit_code == 0, rolled_back.output
    assert 'mining-budget = "openai/gpt-5.6-luna"' in profiles_path.read_text()


def test_benchmark_plan_is_no_spend_and_writes_hashed_manifest(tmp_path: Path) -> None:
    suite_path = Path(__file__).parent.parent / "benchmarks" / "mining-v1.toml"
    catalog_path = Path(__file__).parent / "fixtures" / "openrouter_models.json"
    fixture_path = tmp_path / "fixtures.json"
    output_path = tmp_path / "run"
    suite_names = ["Codx_LoopKit", "atomic-agent", "RedaktSafe", "OpenCLI", "OpenViking"]
    fixtures = [
        MiningPromptFixture(
            repo_path=f"/private/{name}",
            repo_name=name,
            git_head="a" * 40,
            dirty_paths=[],
            brain="python",
            prompt=f"private prompt for {name}",
            prompt_sha256=f"prompt-{name}",
            repo_content=f"private source for {name}",
            repo_content_sha256=f"content-{name}",
            source_manifest=["README.md", "main.py"],
            repo_bytes=4096,
            file_count=2,
            estimated_tokens=1000,
            token_budget=512,
            domain_info={"complexity": "small"},
            overlap={},
        ).model_dump(mode="json")
        for name in suite_names
    ]
    fixture_path.write_text(json.dumps(fixtures))

    result = runner.invoke(
        app,
        [
            "models",
            "benchmark",
            "plan",
            str(suite_path),
            "--fixtures",
            str(fixture_path),
            "--catalog-snapshot",
            str(catalog_path),
            "--budget-usd",
            "5",
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "NO PAID CALLS MADE" in result.output
    plan_path = output_path / "plan.json"
    assert plan_path.exists()
    plan_text = plan_path.read_text()
    assert "private prompt" not in plan_text
    assert "private source" not in plan_text
