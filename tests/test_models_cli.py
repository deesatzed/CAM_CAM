from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from claw.cli import app
from claw.llm.client import LLMClient, LLMResponse
from claw.models.benchmark import BenchmarkPlanner, BenchmarkSuite, MiningPromptFixture
from claw.models.catalog import ModelCatalog
from claw.models.scoring import (
    BenchmarkQualityReport,
    CallQualityReceipt,
    ModelQualitySummary,
)
from claw.models.tournament import TournamentStagePlan

runner = CliRunner()


def _quality_calls_for_plan(
    plan: TournamentStagePlan,
    model_id: str,
) -> list[CallQualityReceipt]:
    return [
        CallQualityReceipt(
            candidate_code=f"candidate-{call.call_id}",
            call_id=call.call_id,
            model_id=model_id,
            fixture_name=call.fixture_name,
            envelope="findings-wrapper",
            quality=95.0,
            finding_count=5,
            hard_failures=[],
            cost_usd=0.01,
            duration_seconds=2.0,
            transport="chat-completions",
            finish_reason="stop",
        )
        for call in plan.calls
        if call.model_id == model_id
    ]


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


def test_benchmark_plan_accepts_candidate_set_with_matching_baseline(tmp_path: Path) -> None:
    suite_path = Path(__file__).parent.parent / "benchmarks" / "mining-v1.toml"
    catalog_path = Path(__file__).parent / "fixtures" / "openrouter_models.json"
    fixture_path = tmp_path / "fixtures.json"
    candidate_set_path = tmp_path / "candidate-set.json"
    output_path = tmp_path / "run"
    names = ["Codx_LoopKit", "atomic-agent", "RedaktSafe", "OpenCLI", "OpenViking"]
    fixture_path.write_text(json.dumps([
        MiningPromptFixture(
            repo_path=f"/private/{name}", repo_name=name, git_head="a" * 40,
            dirty_paths=[], brain="python", prompt=f"prompt {name}",
            prompt_sha256=f"prompt-{name}", repo_content=f"source {name}",
            repo_content_sha256=f"content-{name}", source_manifest=["README.md"],
            repo_bytes=100, file_count=1, estimated_tokens=1000, token_budget=512,
            domain_info={}, overlap={},
        ).model_dump(mode="json") for name in names
    ]))
    candidate_set_path.write_text(json.dumps({
        "schema_version": 1,
        "catalog_fetched_at_utc": "2026-08-16T00:00:00Z",
        "lookback_start_utc": "2026-07-17T00:00:00Z",
        "lookback_end_utc": "2026-08-16T00:00:00Z",
        "baseline_model": "z-ai/glm-5.2",
        "selected_model_ids": ["z-ai/glm-5.2", "openai/gpt-5.6-luna"],
        "catalog_digest": "a" * 64,
    }))

    result = runner.invoke(
        app,
        [
            "models", "benchmark", "plan", str(suite_path), "--fixtures", str(fixture_path),
            "--catalog-snapshot", str(catalog_path), "--candidate-set", str(candidate_set_path),
            "--baseline-model", "z-ai/glm-5.2", "--budget-usd", "5", "--output", str(output_path),
        ],
    )

    assert result.exit_code == 0, result.output
    plan = TournamentStagePlan.model_validate_json((output_path / "plan.json").read_text())
    assert plan.selected_candidates == ["z-ai/glm-5.2", "openai/gpt-5.6-luna"]
    assert "NO PAID CALLS MADE" in result.output


def test_benchmark_compare_emits_non_promoting_baseline_verdict(tmp_path: Path) -> None:
    baseline = "z-ai/glm-5.2"
    candidate = "openai/gpt-5.6-luna"
    report_paths: dict[str, Path] = {}
    for stage in ("first-round", "heldout", "repeat"):
        report = BenchmarkQualityReport(
            run_id=stage,
            expected_fixtures=1,
            actual_cost_usd=0.04,
            calls=[],
            models=[
                ModelQualitySummary(
                    model_id=baseline,
                    completed_calls=1,
                    average_quality=80.0,
                    worst_quality=80.0,
                    total_cost_usd=0.02,
                    cost_per_finding_usd=0.004,
                    average_sync_latency_seconds=1.0,
                    finding_count=5,
                    hard_failures=[],
                    eligible=True,
                ),
                ModelQualitySummary(
                    model_id=candidate,
                    completed_calls=1,
                    average_quality=90.0,
                    worst_quality=90.0,
                    total_cost_usd=0.02,
                    cost_per_finding_usd=0.004,
                    average_sync_latency_seconds=1.0,
                    finding_count=5,
                    hard_failures=[],
                    eligible=True,
                ),
            ],
        )
        path = tmp_path / f"{stage}.json"
        path.write_text(report.model_dump_json())
        report_paths[stage] = path

    result = runner.invoke(
        app,
        [
            "models", "benchmark", "compare",
            "--baseline-model", baseline,
            "--candidate-model", candidate,
            "--first-round-report", str(report_paths["first-round"]),
            "--heldout-report", str(report_paths["heldout"]),
            "--repeat-report", str(report_paths["repeat"]),
        ],
    )

    assert result.exit_code == 0, result.output
    verdict = json.loads(result.output)
    assert verdict["status"] == "better"
    assert verdict["stage_evidence"] == ["first-round", "heldout", "repeat"]
    assert "promote" not in result.output.lower()


def test_benchmark_plan_and_advance_are_stage_specific_and_no_spend(
    tmp_path: Path,
) -> None:
    suite_path = Path(__file__).parent.parent / "benchmarks" / "mining-v1.toml"
    catalog_path = Path(__file__).parent / "fixtures" / "openrouter_models.json"
    fixture_path = tmp_path / "fixtures.json"
    first_output = tmp_path / "first"
    heldout_output = tmp_path / "heldout"
    repeat_output = tmp_path / "repeat"
    fixtures = []
    for name in ["Codx_LoopKit", "atomic-agent", "RedaktSafe", "OpenCLI", "OpenViking"]:
        fixtures.append(
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
                domain_info={},
                overlap={},
            )
        )
    fixture_path.write_text(
        json.dumps([fixture.model_dump(mode="json") for fixture in fixtures])
    )

    planned = runner.invoke(
        app,
        [
            "models",
            "benchmark",
            "plan",
            str(suite_path),
            "--stage",
            "first-round",
            "--fixtures",
            str(fixture_path),
            "--catalog-snapshot",
            str(catalog_path),
            "--budget-usd",
            "5",
            "--prior-spend-usd",
            "2",
            "--output",
            str(first_output),
        ],
    )

    assert planned.exit_code == 0, planned.output
    assert "NO PAID CALLS MADE" in planned.output
    parent = json.loads((first_output / "plan.json").read_text())
    assert parent["stage"] == "first-round"
    assert parent["prior_spend_usd"] == 2
    frozen_catalog = json.loads((first_output / "catalog.json").read_text())
    assert frozen_catalog["digest"] == parent["catalog_receipt"]["digest"]
    assert "openai/gpt-5.6-luna" in frozen_catalog["entries"]
    duplicate_plan = runner.invoke(
        app,
        [
            "models",
            "benchmark",
            "plan",
            str(suite_path),
            "--stage",
            "first-round",
            "--fixtures",
            str(fixture_path),
            "--catalog-snapshot",
            str(catalog_path),
            "--budget-usd",
            "5",
            "--prior-spend-usd",
            "2",
            "--output",
            str(first_output),
        ],
    )
    assert duplicate_plan.exit_code != 0
    assert "already contains frozen evidence" in duplicate_plan.output
    parent_plan = TournamentStagePlan.model_validate_json(
        (first_output / "plan.json").read_text()
    )
    report = BenchmarkQualityReport(
        run_id=parent["run_id"],
        expected_fixtures=3,
        actual_cost_usd=0.01,
        calls=_quality_calls_for_plan(parent_plan, "openai/gpt-5.6-luna"),
        models=[
            ModelQualitySummary(
                model_id="openai/gpt-5.6-luna",
                completed_calls=3,
                average_quality=95,
                worst_quality=90,
                total_cost_usd=0.01,
                cost_per_finding_usd=0.001,
                average_sync_latency_seconds=2,
                finding_count=10,
                hard_failures=[],
                eligible=True,
            )
        ],
    )
    report_path = tmp_path / "quality-report.json"
    report_path.write_text(report.model_dump_json())

    advanced = runner.invoke(
        app,
        [
            "models",
            "benchmark",
            "advance",
            str(first_output / "plan.json"),
            "--report",
            str(report_path),
            "--stage",
            "heldout",
            "--suite",
            str(suite_path),
            "--fixtures",
            str(fixture_path),
            "--catalog-snapshot",
            str(catalog_path),
            "--output",
            str(heldout_output),
        ],
    )

    assert advanced.exit_code == 0, advanced.output
    assert "NO PAID CALLS MADE" in advanced.output
    heldout = json.loads((heldout_output / "plan.json").read_text())
    assert heldout["stage"] == "heldout"
    assert heldout["parent_run_id"] == parent["run_id"]
    assert heldout["selected_candidates"] == ["openai/gpt-5.6-luna"]
    heldout_report = report.model_copy(
        update={
            "run_id": heldout["run_id"],
            "expected_fixtures": 2,
            "actual_cost_usd": 0.01,
            "calls": _quality_calls_for_plan(
                TournamentStagePlan.model_validate_json(
                    (heldout_output / "plan.json").read_text()
                ),
                "openai/gpt-5.6-luna",
            ),
            "models": [
                report.models[0].model_copy(update={"completed_calls": 2})
            ],
        }
    )
    heldout_report_path = tmp_path / "heldout-quality-report.json"
    heldout_report_path.write_text(heldout_report.model_dump_json())

    repeated = runner.invoke(
        app,
        [
            "models",
            "benchmark",
            "advance",
            str(heldout_output / "plan.json"),
            "--root-plan",
            str(first_output / "plan.json"),
            "--report",
            str(heldout_report_path),
            "--stage",
            "repeat",
            "--suite",
            str(suite_path),
            "--fixtures",
            str(fixture_path),
            "--catalog-snapshot",
            str(first_output / "catalog.json"),
            "--output",
            str(repeat_output),
        ],
    )

    assert repeated.exit_code == 0, repeated.output
    repeat_plan = json.loads((repeat_output / "plan.json").read_text())
    assert repeat_plan["stage"] == "repeat"
    original = next(
        call
        for call in parent["calls"]
        if call["model_id"] == "openai/gpt-5.6-luna"
        and call["fixture_name"] == "Codx_LoopKit"
    )
    assert repeat_plan["calls"][0]["prompt_sha256"] == original["prompt_sha256"]
    assert repeat_plan["calls"][0]["parameters"] == original["parameters"]


def test_benchmark_fixtures_capture_production_prompts_without_model_calls(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repos"
    repo_root.mkdir()
    names = ["Codx_LoopKit", "atomic-agent", "RedaktSafe", "OpenCLI", "OpenViking"]
    for name in names:
        repo = repo_root / name
        repo.mkdir()
        (repo / "README.md").write_text(f"# {name}\n\nRetry queue agent architecture.\n")
        (repo / "main.py").write_text("def run():\n    return True\n" + "# padding\n" * 100)
        (repo / "test_main.py").write_text(
            "def test_run():\n    assert True\n" + "# test padding\n" * 100
        )
    output_path = tmp_path / "fixtures.json"
    suite_path = Path(__file__).parent.parent / "benchmarks" / "mining-v1.toml"
    config_path = Path(__file__).parent.parent / "claw.toml"

    result = runner.invoke(
        app,
        [
            "models",
            "benchmark",
            "fixtures",
            str(suite_path),
            "--repo-root",
            str(repo_root),
            "--config",
            str(config_path),
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "NO MODEL CALLS MADE" in result.output
    fixtures = json.loads(output_path.read_text())
    assert {item["repo_name"] for item in fixtures} == set(names)
    assert all(item["prompt_sha256"] for item in fixtures)


def test_benchmark_run_executes_frozen_plan_with_exact_model(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import hashlib

    suite_path = Path(__file__).parent.parent / "benchmarks" / "mining-v1.toml"
    catalog_path = Path(__file__).parent / "fixtures" / "openrouter_models.json"
    catalog_payload = json.loads(catalog_path.read_text())
    catalog = ModelCatalog.from_payload(catalog_payload)
    fixtures = []
    for name in ["Codx_LoopKit", "atomic-agent", "RedaktSafe", "OpenCLI", "OpenViking"]:
        prompt = f"mine {name}"
        content = f"content {name}"
        fixtures.append(
            MiningPromptFixture(
                repo_path=f"/repo/{name}",
                repo_name=name,
                git_head="a" * 40,
                dirty_paths=[],
                brain="python",
                prompt=prompt,
                prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                repo_content=content,
                repo_content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                source_manifest=["README.md", "main.py"],
                repo_bytes=2000,
                file_count=2,
                estimated_tokens=100,
                token_budget=100,
                domain_info={"complexity": "small"},
                overlap={},
            )
        )
    plan = BenchmarkPlanner().plan(
        BenchmarkSuite.load(suite_path),
        fixtures,
        catalog,
        budget_usd=5.0,
    )
    plan_path = tmp_path / "plan.json"
    fixture_path = tmp_path / "fixtures.json"
    run_path = tmp_path / "run"
    plan_path.write_text(plan.model_dump_json())
    fixture_path.write_text(
        json.dumps([fixture.model_dump(mode="json") for fixture in fixtures])
    )
    called: list[str] = []

    async def fake_complete(self: LLMClient, messages, model, **kwargs) -> LLMResponse:
        called.append(model)
        return LLMResponse(
            content="[]",
            model=model,
            input_tokens=10,
            output_tokens=2,
            tokens_used=12,
            cost_usd=0.00001,
            cost_source="provider",
        )

    monkeypatch.setattr(LLMClient, "complete", fake_complete)
    result = runner.invoke(
        app,
        [
            "models",
            "benchmark",
            "run",
            str(plan_path),
            "--fixtures",
            str(fixture_path),
            "--catalog-snapshot",
            str(catalog_path),
            "--output",
            str(run_path),
                "--limit",
                "1",
                "--model",
                "openai/gpt-5.6-luna",
            ],
        env={"OPENROUTER_API_KEY": "test-key"},
    )

    assert result.exit_code == 0, result.output
    assert "Completed: 1" in result.output
    assert called == ["openai/gpt-5.6-luna"]

    different_plan = plan.model_copy(update={"run_id": "different-run"})
    different_plan_path = tmp_path / "different-plan.json"
    different_plan_path.write_text(different_plan.model_dump_json())
    reused = runner.invoke(
        app,
        [
            "models",
            "benchmark",
            "run",
            str(different_plan_path),
            "--fixtures",
            str(fixture_path),
            "--catalog-snapshot",
            str(catalog_path),
            "--output",
            str(run_path),
            "--limit",
            "1",
            "--model",
            "openai/gpt-5.6-luna",
        ],
        env={"OPENROUTER_API_KEY": "test-key"},
    )

    assert reused.exit_code != 0
    assert "different frozen plan" in reused.output


def test_benchmark_report_emits_machine_readable_quality_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import claw.cli.models as models_cli

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "plan.json").write_text(
        json.dumps(
            {"run_id": "run-1", "stage_policy": {"first_round_fixtures": 3}}
        )
    )
    fixture_path = tmp_path / "fixtures.json"
    fixture_path.write_text("[]")
    db_path = tmp_path / "claw.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """CREATE TABLE methodologies (
                problem_description TEXT NOT NULL,
                solution_code TEXT NOT NULL,
                lifecycle_state TEXT NOT NULL
            )"""
        )
        connection.execute(
            "INSERT INTO methodologies VALUES (?, ?, ?)",
            (
                "[Mined from fixture] Existing pattern: description",
                "## Existing pattern\n",
                "viable",
            ),
        )
    captured: dict = {}

    def fake_score(**kwargs):
        captured.update(kwargs)
        return BenchmarkQualityReport(
            run_id="run-1",
            expected_fixtures=3,
            actual_cost_usd=0.25,
            calls=[],
            models=[],
        )

    monkeypatch.setattr(
        models_cli,
        "score_benchmark_run",
        fake_score,
    )

    result = runner.invoke(
        app,
        [
            "models",
            "benchmark",
            "report",
            str(run_dir),
            "--fixtures",
            str(fixture_path),
            "--db",
            str(db_path),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["run_id"] == "run-1"
    assert payload["actual_cost_usd"] == 0.25
    assert captured["existing_titles"] == ["Existing pattern"]


def test_benchmark_select_writes_evidence_without_changing_profiles(
    tmp_path: Path,
) -> None:
    plan = TournamentStagePlan(
        run_id="first",
        created_at="2026-08-08T00:00:00+00:00",
        suite_name="mining-v1",
        stage="first-round",
        authorization_usd=5,
        prior_spend_usd=2,
        stage_maximum_cost_usd=0,
        catalog_receipt={"digest": "catalog", "model_digests": {}},
        fixtures=[],
        calls=[],
        selected_candidates=[],
    )
    report = BenchmarkQualityReport(
        run_id="first",
        expected_fixtures=3,
        actual_cost_usd=0,
        calls=[],
        models=[],
    )
    plan_path = tmp_path / "plan.json"
    report_path = tmp_path / "report.json"
    output_path = tmp_path / "selection.json"
    profiles_path = tmp_path / "model_profiles.toml"
    plan_path.write_text(plan.model_dump_json())
    report_path.write_text(report.model_dump_json())
    _write_profiles(profiles_path)
    before = profiles_path.read_bytes()

    result = runner.invoke(
        app,
        [
            "models",
            "benchmark",
            "select",
            "--plan",
            str(plan_path),
            "--report",
            str(report_path),
            "--profile",
            "selected",
            "--format",
            "json",
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output_path.read_text())
    assert payload["roles"]["quality"]["model_id"] is None
    assert profiles_path.read_bytes() == before
