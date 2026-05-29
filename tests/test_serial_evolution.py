"""Tests for CAM-PULSE serial champion/challenger evolution."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from datetime import UTC, datetime, timedelta

import pytest
import toml

from dataclasses import dataclass, field

from claw.core.config import DatabaseConfig
from claw.core.models import ActionTemplate, Methodology
from claw.db.engine import DatabaseEngine
from claw.db.repository import Repository
from claw.evolution.serial import (
    APPROVED_MODEL_IDS,
    BudgetStatus,
    LiveProbeStatus,
    LiveMiningBinding,
    PromotionGateConfig,
    SerialEvolutionRunner,
    promotion_score,
    select_layer_for_cycle,
)


@pytest.fixture
async def evolution_engine():
    engine = DatabaseEngine(DatabaseConfig(db_path=":memory:"))
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    yield engine
    await engine.close()


@pytest.fixture
def mini_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "cam-pulse-mini"
    (repo / "src" / "claw").mkdir(parents=True)
    (repo / "prompts").mkdir()
    (repo / "config").mkdir()
    (repo / "src" / "claw" / "__init__.py").write_text("")
    (repo / "src" / "claw" / "demo.py").write_text("VALUE = 1\n")
    (repo / "prompts" / "demo.md").write_text("demo prompt\n")
    (repo / "claw.toml").write_text("[database]\ndb_path=':memory:'\n")
    (repo / "config" / "weights.yaml").write_text("x: 1\n")
    return repo


async def _seed_accepted_pulse_sources(engine: DatabaseEngine, count: int = 4) -> None:
    for idx in range(count):
        await engine.execute(
            """INSERT INTO pulse_discoveries
               (id, github_url, canonical_url, novelty_score, status, license_type)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                f"disc-{idx}",
                f"https://github.com/example/repo-{idx}",
                f"https://github.com/example/repo-{idx}",
                0.91,
                "assimilated",
                "mit",
            ],
        )


class _FakeBudgetClient:
    def __init__(
        self,
        statuses: list[BudgetStatus],
        probe_status: LiveProbeStatus | None = None,
    ):
        self.statuses = list(statuses)
        self.probe_status = probe_status
        self.calls = 0
        self.probe_calls = 0

    async def get_status(self, min_remaining_credits: float = 0.01) -> BudgetStatus:
        self.calls += 1
        if self.statuses:
            return self.statuses.pop(0)
        return BudgetStatus(
            can_continue=False,
            source="fake",
            remaining_credits=0.0,
            reason="fake budget exhausted",
        )

    async def probe_allowed_models(self):
        self.probe_calls += 1
        return self.probe_status or LiveProbeStatus(
            can_continue=True,
            source="fake_probe",
            model_used=APPROVED_MODEL_IDS[0],
            attempted_models=[APPROVED_MODEL_IDS[0]],
            reason="fake probe ok",
            tokens_used=2,
        )


@dataclass
class _FakeMiningResult:
    findings: list[str] = field(default_factory=lambda: ["finding"])
    methodology_ids: list[str] = field(default_factory=lambda: ["meth-1"])
    action_template_ids: list[str] = field(default_factory=list)
    tokens_used: int = 123
    cost_usd: float = 0.01
    error: str | None = None
    skipped: bool = False
    skip_reason: str | None = None


class _FakeRepoMiner:
    def __init__(self):
        self.calls: list[str] = []

    async def mine_repo(self, repo_path, repo_name, target_project_id):
        self.calls.append(repo_name)
        return _FakeMiningResult()


class TestSerialEvolutionSchema:
    async def test_evolution_tables_exist(self, evolution_engine: DatabaseEngine):
        for table_name in (
            "evolution_instances",
            "evolution_runs",
            "evolution_mined_inputs",
            "evolution_mutations",
            "evolution_evaluations",
            "evolution_decisions",
            "evolution_monitor_events",
        ):
            row = await evolution_engine.fetch_one(
                "SELECT COUNT(*) AS cnt FROM sqlite_master WHERE type='table' AND name = ?",
                [table_name],
            )
            assert row["cnt"] == 1


class TestSerialEvolutionRepository:
    async def test_repository_records_instance_run_and_decision(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
    ):
        repo = Repository(evolution_engine)
        instance = await repo.create_evolution_instance(
            {
                "role": "champion",
                "version_label": "v0",
                "repo_path": str(mini_repo),
                "notes": "test champion",
            }
        )
        run = await repo.create_evolution_run(
            {
                "champion_instance_id": instance["id"],
                "cycle_number": 1,
                "layer": "data_feature",
                "objective": "test cycle",
            }
        )
        decision = await repo.record_evolution_decision(
            {
                "run_id": run["id"],
                "decision": "pause",
                "reason": "manual approval required",
                "gate_report": {"relative_lift": 0.05},
            }
        )

        assert instance["role"] == "champion"
        assert run["status"] == "planned"
        assert decision["decision"] == "pause"
        assert json.loads(decision["gate_report"])["relative_lift"] == 0.05


class TestSerialEvolutionRunner:
    def test_promotion_score_and_rotation(self):
        assert select_layer_for_cycle(1) == ("data_feature", "rotation")
        assert select_layer_for_cycle(4) == ("model", "rotation")
        assert select_layer_for_cycle(7, "prompt_config") == (
            "prompt_config",
            "operator_override",
        )
        metrics = {key: 1.0 for key in (
            "functional_correctness",
            "structural_compliance",
            "intent_alignment",
            "expectation_match",
            "correction_efficiency",
            "retrieval_or_knowledge_lift",
            "cost_efficiency",
            "stability",
        )}
        assert promotion_score(metrics) == 1.0

    async def test_minimal_cycle_stages_artifacts_and_promotes_automatically(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
    ):
        await _seed_accepted_pulse_sources(evolution_engine)
        runner = SerialEvolutionRunner(
            Repository(evolution_engine),
            repo_path=mini_repo,
            instances_root=mini_repo / "instances" / "evolution",
        )

        result = await runner.run_minimal_cycle(layer_override="data_feature")

        assert result.layer == "data_feature"
        assert result.decision == "promote"
        assert result.report_path.exists()
        assert (result.artifact_dir / "mutation_manifest.json").exists()
        assert result.promotion_score_delta > 0
        pointer = mini_repo / "instances" / "evolution" / "current_champion.json"
        assert pointer.exists()
        pointer_payload = json.loads(pointer.read_text())
        assert pointer_payload["instance_id"] == result.challenger_instance_id

        run = await evolution_engine.fetch_one(
            "SELECT * FROM evolution_runs WHERE id = ?",
            [result.run_id],
        )
        assert run["status"] == "promoted"

        mined = await evolution_engine.fetch_all(
            "SELECT * FROM evolution_mined_inputs WHERE run_id = ?",
            [result.run_id],
        )
        assert len(mined) == 4
        assert all(row["accepted"] == 1 for row in mined)

    async def test_manual_approval_path_still_supports_paused_runs(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
    ):
        await _seed_accepted_pulse_sources(evolution_engine)
        repository = Repository(evolution_engine)
        runner = SerialEvolutionRunner(
            repository,
            repo_path=mini_repo,
            instances_root=mini_repo / "instances" / "evolution",
            gate_config=PromotionGateConfig(require_manual_approval=True),
        )
        result = await runner.run_minimal_cycle(layer_override="data_feature")

        decision = await runner.approve_paused_run(result.run_id, decided_by="test")

        assert decision["decision"] == "promote"
        old = await repository.get_evolution_instance(result.champion_instance_id)
        new = await repository.get_evolution_instance(result.challenger_instance_id)
        assert old["role"] == "archived"
        assert new["role"] == "champion"

    async def test_required_validation_gate_rejects_without_isolated_challenger_db(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
    ):
        await _seed_accepted_pulse_sources(evolution_engine)
        runner = SerialEvolutionRunner(
            Repository(evolution_engine),
            repo_path=mini_repo,
            instances_root=mini_repo / "instances" / "evolution",
            gate_config=PromotionGateConfig(require_validation_gate=True),
        )

        result = await runner.run_minimal_cycle(layer_override="data_feature")

        decision = await evolution_engine.fetch_one("SELECT * FROM evolution_decisions")
        gate_report = json.loads(decision["gate_report"])
        assert result.decision == "reject"
        assert result.decision_reason == "Challenger validation gate failed before promotion"
        assert gate_report["validation_gate"] == "required"
        assert gate_report["validation_report"]["passed"] is False
        assert gate_report["validation_report"]["checks"]["db_path_present"] is False

    async def test_cycle_rejects_when_no_mined_inputs_are_accepted(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
    ):
        runner = SerialEvolutionRunner(
            Repository(evolution_engine),
            repo_path=mini_repo,
            instances_root=mini_repo / "instances" / "evolution",
        )

        result = await runner.run_minimal_cycle(layer_override="data_feature")

        assert result.decision == "reject"
        assert "No accepted mined inputs" in result.decision_reason
        run = await evolution_engine.fetch_one(
            "SELECT status, failure_reason FROM evolution_runs WHERE id = ?",
            [result.run_id],
        )
        assert run["status"] == "rejected"
        assert "No accepted mined inputs" in run["failure_reason"]

    async def test_prompt_config_cycle_bootstraps_from_static_prompt_and_config_files(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
    ):
        (mini_repo / "prompts" / "verify.md").write_text("verify tests and fallback behavior\n")
        (mini_repo / "prompts" / "budget.md").write_text("model budget quality prompt\n")
        runner = SerialEvolutionRunner(
            Repository(evolution_engine),
            repo_path=mini_repo,
            instances_root=mini_repo / "instances" / "evolution",
        )

        result = await runner.run_minimal_cycle(layer_override="prompt_config")

        assert result.decision == "promote"
        mined = await evolution_engine.fetch_all(
            "SELECT source_type, source_uri, accepted, extracted_payload "
            "FROM evolution_mined_inputs WHERE run_id = ? ORDER BY source_uri",
            [result.run_id],
        )
        assert {row["source_type"] for row in mined} == {
            "config_file",
            "prompt_template",
        }
        assert all(row["accepted"] == 1 for row in mined)
        payloads = [json.loads(row["extracted_payload"]) for row in mined]
        assert all(payload["bootstrap_reason"] == "no_prompt_variant_history" for payload in payloads)
        assert any(payload["path"] == "prompts/demo.md" for payload in payloads)
        assert any(payload["path"] == "claw.toml" for payload in payloads)

    async def test_prompt_config_cycle_does_not_bootstrap_over_insufficient_ab_history(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
    ):
        await evolution_engine.execute(
            """INSERT INTO prompt_variants
               (id, prompt_name, variant_label, content, sample_count, success_count, avg_quality_score)
               VALUES ('pv-low', 'demo', 'variant', 'demo variant', 3, 2, 0.7)"""
        )
        runner = SerialEvolutionRunner(
            Repository(evolution_engine),
            repo_path=mini_repo,
            instances_root=mini_repo / "instances" / "evolution",
        )

        result = await runner.run_minimal_cycle(layer_override="prompt_config")

        assert result.decision == "reject"
        mined = await evolution_engine.fetch_all(
            "SELECT source_type, accepted, rejection_reason FROM evolution_mined_inputs WHERE run_id = ?",
            [result.run_id],
        )
        assert len(mined) == 1
        assert mined[0]["source_type"] == "prompt_variant"
        assert mined[0]["accepted"] == 0
        assert mined[0]["rejection_reason"] == "insufficient_samples"

    async def test_decision_rejects_partial_mined_batch_even_with_score_lift(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
        tmp_path: Path,
    ):
        repository = Repository(evolution_engine)
        champion = await repository.create_evolution_instance(
            {
                "role": "champion",
                "version_label": "v0",
                "repo_path": str(mini_repo),
                "db_path": str(tmp_path / "champion.db"),
            }
        )
        challenger_db = tmp_path / "challenger.db"
        challenger_engine = DatabaseEngine(DatabaseConfig(db_path=str(challenger_db)))
        await challenger_engine.connect()
        await challenger_engine.apply_migrations()
        await challenger_engine.initialize_schema()
        await challenger_engine.close()
        challenger = await repository.create_evolution_instance(
            {
                "role": "challenger",
                "version_label": "v1-candidate",
                "repo_path": str(mini_repo / "challenger"),
                "db_path": str(challenger_db),
            }
        )
        run = await repository.create_evolution_run(
            {
                "champion_instance_id": champion["id"],
                "challenger_instance_id": challenger["id"],
                "cycle_number": 1,
                "layer": "data_feature",
                "objective": "mine exact batch",
            }
        )
        runner = SerialEvolutionRunner(
            repository,
            repo_path=mini_repo,
            db_path=tmp_path / "primary.db",
            instances_root=mini_repo / "instances" / "evolution",
        )

        decision = await runner._decide(
            run,
            challenger,
            evaluations=[
                {
                    "eval_slice": "paired_task_readiness",
                    "champion_score": 0.70,
                    "challenger_score": 0.90,
                    "delta_score": 0.20,
                    "passed": 1,
                },
                {
                    "eval_slice": "layer_specific",
                    "champion_score": 0.70,
                    "challenger_score": 0.90,
                    "delta_score": 0.20,
                    "passed": 1,
                },
            ],
            mined=[
                {"accepted": 1, "extracted_payload": "{}"},
                {"accepted": 1, "extracted_payload": "{}"},
                {"accepted": 0, "extracted_payload": "{}"},
            ],
        )

        gate_report = json.loads(decision["gate_report"])
        assert decision["decision"] == "reject"
        assert "Not all mined inputs were accepted" in decision["reason"]
        assert gate_report["accepted_inputs"] == 2
        assert gate_report["rejected_inputs"] == 1
        assert gate_report["total_inputs"] == 3

    async def test_prompt_config_decision_uses_layer_specific_primary_slice(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
    ):
        repository = Repository(evolution_engine)
        champion = await repository.create_evolution_instance(
            {
                "role": "champion",
                "version_label": "v0",
                "repo_path": str(mini_repo),
            }
        )
        challenger = await repository.create_evolution_instance(
            {
                "role": "challenger",
                "version_label": "v1-candidate",
                "repo_path": str(mini_repo / "challenger"),
            }
        )
        run = await repository.create_evolution_run(
            {
                "champion_instance_id": champion["id"],
                "challenger_instance_id": challenger["id"],
                "cycle_number": 1,
                "layer": "prompt_config",
                "objective": "prompt config primary slice",
            }
        )
        runner = SerialEvolutionRunner(
            repository,
            repo_path=mini_repo,
            instances_root=mini_repo / "instances" / "evolution",
        )

        decision = await runner._decide(
            run,
            challenger,
            evaluations=[
                {
                    "eval_slice": "paired_task_readiness",
                    "champion_score": 0.768333,
                    "challenger_score": 0.768333,
                    "delta_score": 0.0,
                    "passed": 0,
                },
                {
                    "eval_slice": "layer_specific",
                    "champion_score": 0.685,
                    "challenger_score": 0.710,
                    "delta_score": 0.025,
                    "passed": 1,
                },
                {
                    "eval_slice": "holdout_proxy",
                    "champion_score": 0.685,
                    "challenger_score": 0.704,
                    "delta_score": 0.019,
                    "passed": 1,
                },
            ],
            mined=[
                {"accepted": 1, "extracted_payload": "{}"},
                {"accepted": 1, "extracted_payload": "{}"},
            ],
        )

        gate_report = json.loads(decision["gate_report"])
        assert decision["decision"] == "promote"
        assert gate_report["primary_champion_score"] == 0.685
        assert gate_report["primary_challenger_score"] == 0.71

    async def test_strategy_policy_cycle_bootstraps_routing_policy_and_skips_weak_rows(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
    ):
        (mini_repo / "claw.toml").write_text(
            "\n".join(
                [
                    "[database]",
                    "db_path=':memory:'",
                    "[routing]",
                    "exploration_rate = 0.10",
                    "score_decay_factor = 0.95",
                    "min_samples_for_routing = 5",
                    "[routing.static_priors]",
                    "analysis = 'claude'",
                    "quick_fixes = 'grok'",
                    "refactoring = 'codex'",
                    "[kelly]",
                    "enabled = true",
                    "kappa = 10.0",
                ]
            )
            + "\n"
        )
        await evolution_engine.execute(
            """INSERT INTO agent_scores
               (id, agent_id, task_type, successes, failures, total_attempts,
                avg_quality_score, avg_cost_usd)
               VALUES ('score-strong', 'claude', 'mining', 4, 2, 6, 0.7, 0.0)"""
        )
        await evolution_engine.execute(
            """INSERT INTO agent_scores
               (id, agent_id, task_type, successes, failures, total_attempts,
                avg_quality_score, avg_cost_usd)
               VALUES ('score-weak', 'grok', 'mining', 1, 1, 2, 0.5, 0.0)"""
        )
        await evolution_engine.execute(
            """INSERT INTO failure_knowledge
               (id, error_signature, error_category, diagnosis, prevention_hint,
                occurrence_count, root_cause_key, detail_signals_json)
               VALUES (
                'fk-1',
                'camseq_negative_memory:auth-refresh:slot-refresh:comp-high',
                'camseq_negative_memory',
                'agent timed out',
                'rotate agent',
                2,
                'camseq_negative_memory:auth-refresh:slot-refresh',
                '{"slot_name": "token_refresh", "component_file_path": "app/auth.py"}'
               )"""
        )
        runner = SerialEvolutionRunner(
            Repository(evolution_engine),
            repo_path=mini_repo,
            instances_root=mini_repo / "instances" / "evolution",
        )

        result = await runner.run_minimal_cycle(layer_override="strategy_policy")

        assert result.layer == "strategy_policy"
        assert result.decision == "promote"
        mined = await evolution_engine.fetch_all(
            "SELECT source_type, source_uri, source_ref, accepted, extracted_payload "
            "FROM evolution_mined_inputs WHERE run_id = ?",
            [result.run_id],
        )
        assert all(row["accepted"] == 1 for row in mined)
        source_types = {row["source_type"] for row in mined}
        assert "agent_score" in source_types
        assert "routing_policy_config" in source_types
        assert "routing_static_prior" in source_types
        assert "kelly_policy_config" in source_types
        assert "failure_policy_signal" in source_types
        failure_signal = next(
            row for row in mined if row["source_type"] == "failure_policy_signal"
        )
        assert failure_signal["source_ref"] == (
            "camseq_negative_memory:auth-refresh:slot-refresh"
        )
        payload = json.loads(failure_signal["extracted_payload"])
        assert payload["root_cause_key"] == (
            "camseq_negative_memory:auth-refresh:slot-refresh"
        )
        assert (
            json.loads(payload["detail_signals_json"])["component_file_path"]
            == "app/auth.py"
        )
        assert all(row["source_uri"] != "grok:mining" for row in mined)
        event = await evolution_engine.fetch_one(
            "SELECT * FROM evolution_monitor_events WHERE run_id = ? AND event_type = ?",
            [result.run_id, "strategy_policy_low_sample_rows_skipped"],
        )
        assert event is not None

    async def test_active_mutating_run_blocks_a_second_cycle(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
    ):
        repository = Repository(evolution_engine)
        champion = await repository.create_evolution_instance(
            {
                "role": "champion",
                "version_label": "v0",
                "repo_path": str(mini_repo),
            }
        )
        await repository.create_evolution_run(
            {
                "champion_instance_id": champion["id"],
                "cycle_number": 1,
                "layer": "data_feature",
                "status": "evaluating",
                "objective": "already running",
            }
        )
        runner = SerialEvolutionRunner(
            repository,
            repo_path=mini_repo,
            instances_root=mini_repo / "instances" / "evolution",
        )

        with pytest.raises(RuntimeError, match="already active"):
            await runner.run_minimal_cycle(layer_override="data_feature")

    async def test_stale_active_run_is_failed_before_next_cycle(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
    ):
        await _seed_accepted_pulse_sources(evolution_engine)
        repository = Repository(evolution_engine)
        champion = await repository.create_evolution_instance(
            {
                "role": "champion",
                "version_label": "v0",
                "repo_path": str(mini_repo),
            }
        )
        stale = await repository.create_evolution_run(
            {
                "champion_instance_id": champion["id"],
                "cycle_number": 1,
                "layer": "data_feature",
                "status": "mining",
                "objective": "abandoned run",
            }
        )
        old_started_at = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        await evolution_engine.execute(
            "UPDATE evolution_runs SET started_at = ? WHERE id = ?",
            [old_started_at, stale["id"]],
        )
        runner = SerialEvolutionRunner(
            repository,
            repo_path=mini_repo,
            instances_root=mini_repo / "instances" / "evolution",
            stale_run_timeout_seconds=1,
        )

        result = await runner.run_minimal_cycle(layer_override="data_feature")

        old_run = await repository.get_evolution_run(stale["id"])
        event = await evolution_engine.fetch_one(
            "SELECT * FROM evolution_monitor_events WHERE run_id = ?",
            [stale["id"]],
        )
        assert old_run["status"] == "failed"
        assert "stale_active_run_timeout_after_1s" in old_run["failure_reason"]
        assert event["event_type"] == "stale_active_run_recovered"
        assert result.cycle_number == 2

    async def test_invalid_layer_override_fails_before_run_creation(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
    ):
        runner = SerialEvolutionRunner(
            Repository(evolution_engine),
            repo_path=mini_repo,
            instances_root=mini_repo / "instances" / "evolution",
        )

        with pytest.raises(ValueError, match="Unknown evolution layer"):
            await runner.run_minimal_cycle(layer_override="bad_layer")

        rows = await evolution_engine.fetch_all("SELECT * FROM evolution_runs")
        assert rows == []

    async def test_model_layer_is_safety_overridden_by_default(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
    ):
        await _seed_accepted_pulse_sources(evolution_engine)
        runner = SerialEvolutionRunner(
            Repository(evolution_engine),
            repo_path=mini_repo,
            instances_root=mini_repo / "instances" / "evolution",
        )

        result = await runner.run_minimal_cycle(layer_override="model")

        assert result.layer == "data_feature"
        run = await evolution_engine.fetch_one(
            "SELECT layer, selected_by FROM evolution_runs WHERE id = ?",
            [result.run_id],
        )
        assert run["layer"] == "data_feature"
        assert run["selected_by"] == "safety_override_model_disabled"

    async def test_model_layer_mines_only_approved_models(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
    ):
        await evolution_engine.execute(
            """INSERT INTO token_costs
               (id, model_used, input_tokens, output_tokens, total_tokens, cost_usd)
               VALUES ('tc-allowed', ?, 100, 50, 150, 0.01)""",
            [APPROVED_MODEL_IDS[0]],
        )
        await evolution_engine.execute(
            """INSERT INTO token_costs
               (id, model_used, input_tokens, output_tokens, total_tokens, cost_usd)
               VALUES ('tc-blocked', 'unapproved/model-sentinel', 100, 50, 150, 0.01)"""
        )
        runner = SerialEvolutionRunner(
            Repository(evolution_engine),
            repo_path=mini_repo,
            instances_root=mini_repo / "instances" / "evolution",
            gate_config=PromotionGateConfig(allowed_layers={"model"}),
        )

        result = await runner.run_minimal_cycle(
            layer_override="model",
            allow_model_layer=True,
        )

        mined = await evolution_engine.fetch_all(
            "SELECT source_uri FROM evolution_mined_inputs WHERE run_id = ?",
            [result.run_id],
        )
        assert [row["source_uri"] for row in mined] == [APPROVED_MODEL_IDS[0]]

    async def test_allow_model_layer_bypasses_conservative_allowed_layer_default(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
    ):
        await evolution_engine.execute(
            """INSERT INTO token_costs
               (id, model_used, input_tokens, output_tokens, total_tokens, cost_usd)
               VALUES ('tc-allowed', ?, 100, 50, 150, 0.01)""",
            [APPROVED_MODEL_IDS[0]],
        )
        runner = SerialEvolutionRunner(
            Repository(evolution_engine),
            repo_path=mini_repo,
            instances_root=mini_repo / "instances" / "evolution",
        )

        result = await runner.run_minimal_cycle(
            layer_override="model",
            allow_model_layer=True,
        )

        assert result.layer == "model"
        run = await evolution_engine.fetch_one(
            "SELECT layer, selected_by FROM evolution_runs WHERE id = ?",
            [result.run_id],
        )
        assert run["layer"] == "model"
        assert run["selected_by"] == "operator_override"

    async def test_autonomous_loop_mines_three_folder_repos_per_round(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
        tmp_path: Path,
    ):
        mining_dir = tmp_path / "repo_pool"
        mining_dir.mkdir()
        for idx in range(6):
            repo = mining_dir / f"repo-{idx}"
            repo.mkdir()
            (repo / "README.md").write_text(f"# repo {idx}\n")
            (repo / "main.py").write_text("print('ok')\n")

        runner = SerialEvolutionRunner(
            Repository(evolution_engine),
            repo_path=mini_repo,
            instances_root=mini_repo / "instances" / "evolution",
        )
        budget = _FakeBudgetClient(
            [
                BudgetStatus(True, "fake", remaining_credits=1.0, reason="ok"),
                BudgetStatus(True, "fake", remaining_credits=0.5, reason="ok"),
                BudgetStatus(False, "fake", remaining_credits=0.0, reason="budget stop"),
            ]
        )

        result = await runner.run_autonomous_loop(
            mining_dir=mining_dir,
            repos_per_round=3,
            budget_client=budget,
        )

        assert result.rounds_attempted == 2
        assert result.stop_reason == "budget stop"
        assert [cycle.decision for cycle in result.cycle_results] == ["promote", "promote"]
        rows = await evolution_engine.fetch_all(
            """SELECT run_id, COUNT(*) AS cnt
               FROM evolution_mined_inputs
               WHERE source_type = 'folder_repo'
               GROUP BY run_id
               ORDER BY run_id"""
        )
        assert [row["cnt"] for row in rows] == [3, 3]

    async def test_autonomous_live_probe_runs_before_first_round(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
        tmp_path: Path,
    ):
        mining_dir = tmp_path / "repo_pool"
        mining_dir.mkdir()
        for idx in range(3):
            repo = mining_dir / f"repo-{idx}"
            repo.mkdir()
            (repo / "README.md").write_text(f"# repo {idx}\n")

        budget = _FakeBudgetClient(
            [BudgetStatus(True, "fake", remaining_credits=1.0, reason="ok")],
            probe_status=LiveProbeStatus(
                can_continue=True,
                source="fake_probe",
                model_used=APPROVED_MODEL_IDS[1],
                attempted_models=[APPROVED_MODEL_IDS[0], APPROVED_MODEL_IDS[1]],
                failures=[f"{APPROVED_MODEL_IDS[0]}: HTTP 400"],
                reason="fake probe ok",
                tokens_used=3,
            ),
        )
        runner = SerialEvolutionRunner(
            Repository(evolution_engine),
            repo_path=mini_repo,
            instances_root=mini_repo / "instances" / "evolution",
        )

        result = await runner.run_autonomous_loop(
            mining_dir=mining_dir,
            repos_per_round=3,
            max_rounds=1,
            budget_client=budget,
            require_live_probe=True,
        )

        assert budget.probe_calls == 1
        assert result.rounds_attempted == 1
        assert result.live_probe_status.model_used == APPROVED_MODEL_IDS[1]
        assert result.live_probe_status.tokens_used == 3

    async def test_autonomous_live_probe_failure_stops_before_mining(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
        tmp_path: Path,
    ):
        mining_dir = tmp_path / "repo_pool"
        mining_dir.mkdir()
        for idx in range(3):
            repo = mining_dir / f"repo-{idx}"
            repo.mkdir()
            (repo / "README.md").write_text(f"# repo {idx}\n")

        budget = _FakeBudgetClient(
            [BudgetStatus(True, "fake", remaining_credits=1.0, reason="ok")],
            probe_status=LiveProbeStatus(
                can_continue=False,
                source="fake_probe",
                attempted_models=list(APPROVED_MODEL_IDS),
                failures=["all failed"],
                reason="fake probe failed",
            ),
        )
        runner = SerialEvolutionRunner(
            Repository(evolution_engine),
            repo_path=mini_repo,
            instances_root=mini_repo / "instances" / "evolution",
        )

        result = await runner.run_autonomous_loop(
            mining_dir=mining_dir,
            repos_per_round=3,
            budget_client=budget,
            require_live_probe=True,
        )

        rows = await evolution_engine.fetch_all("SELECT * FROM evolution_runs")
        assert budget.probe_calls == 1
        assert result.rounds_attempted == 0
        assert "OpenRouter live probe failed" in result.stop_reason
        assert rows == []

    async def test_folder_repo_round_invokes_live_miner_when_configured(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
        tmp_path: Path,
    ):
        mining_dir = tmp_path / "repo_pool"
        mining_dir.mkdir()
        for idx in range(3):
            repo = mining_dir / f"repo-{idx}"
            repo.mkdir()
            (repo / "README.md").write_text(f"# repo {idx}\n")

        fake_miner = _FakeRepoMiner()
        runner = SerialEvolutionRunner(
            Repository(evolution_engine),
            repo_path=mini_repo,
            instances_root=mini_repo / "instances" / "evolution",
            repo_miner=fake_miner,
            target_project_id="project-1",
        )

        result = await runner.run_autonomous_loop(
            mining_dir=mining_dir,
            repos_per_round=3,
            max_rounds=1,
            budget_client=_FakeBudgetClient(
                [BudgetStatus(True, "fake", remaining_credits=1.0, reason="ok")]
            ),
        )

        assert result.rounds_attempted == 1
        assert fake_miner.calls == ["repo-0", "repo-1", "repo-2"]
        rows = await evolution_engine.fetch_all(
            "SELECT accepted, extracted_payload FROM evolution_mined_inputs"
        )
        assert all(row["accepted"] == 1 for row in rows)
        assert all(json.loads(row["extracted_payload"])["tokens_used"] == 123 for row in rows)

    async def test_live_folder_mining_uses_isolated_challenger_db(
        self,
        mini_repo: Path,
        tmp_path: Path,
    ):
        primary_db = tmp_path / "primary.db"
        engine = DatabaseEngine(DatabaseConfig(db_path=str(primary_db)))
        await engine.connect()
        await engine.apply_migrations()
        await engine.initialize_schema()
        try:
            await _seed_accepted_pulse_sources(engine, count=1)

            mining_dir = tmp_path / "repo_pool"
            mining_dir.mkdir()
            for idx in range(3):
                repo = mining_dir / f"repo-{idx}"
                repo.mkdir()
                (repo / "README.md").write_text(f"# repo {idx}\n")

            seen_challenger_dbs: list[Path] = []
            closed = False
            fake_miner = _FakeRepoMiner()

            async def live_factory(challenger: dict[str, str]) -> LiveMiningBinding:
                nonlocal closed
                challenger_db = Path(challenger["db_path"])
                seen_challenger_dbs.append(challenger_db)
                assert challenger_db.exists()
                assert challenger_db != primary_db

                clone_engine = DatabaseEngine(DatabaseConfig(db_path=str(challenger_db)))
                await clone_engine.connect()
                try:
                    row = await clone_engine.fetch_one(
                        "SELECT COUNT(*) AS cnt FROM pulse_discoveries"
                    )
                    assert row["cnt"] == 1
                finally:
                    await clone_engine.close()

                async def close() -> None:
                    nonlocal closed
                    closed = True

                return LiveMiningBinding(
                    repo_miner=fake_miner,
                    target_project_id="challenger-project",
                    db_path=challenger_db,
                    close=close,
                )

            runner = SerialEvolutionRunner(
                Repository(engine),
                repo_path=mini_repo,
                db_path=primary_db,
                instances_root=mini_repo / "instances" / "evolution",
                live_mining_factory=live_factory,
            )

            result = await runner.run_autonomous_loop(
                mining_dir=mining_dir,
                repos_per_round=3,
                max_rounds=1,
                budget_client=_FakeBudgetClient(
                    [BudgetStatus(True, "fake", remaining_credits=1.0, reason="ok")]
                ),
            )

            challenger = await Repository(engine).get_evolution_instance(
                result.cycle_results[0].challenger_instance_id
            )
            rows = await engine.fetch_all(
                "SELECT extracted_payload FROM evolution_mined_inputs"
            )
            payloads = [json.loads(row["extracted_payload"]) for row in rows]
            assert result.rounds_attempted == 1
            assert fake_miner.calls == ["repo-0", "repo-1", "repo-2"]
            assert closed is True
            assert Path(challenger["db_path"]) == seen_challenger_dbs[0]
            assert all(
                payload["target_db_path"] == str(seen_challenger_dbs[0])
                for payload in payloads
            )
        finally:
            await engine.close()

    async def test_live_folder_timeout_recovers_challenger_side_effects(
        self,
        mini_repo: Path,
        tmp_path: Path,
    ):
        primary_db = tmp_path / "primary.db"
        engine = DatabaseEngine(DatabaseConfig(db_path=str(primary_db)))
        await engine.connect()
        await engine.apply_migrations()
        await engine.initialize_schema()
        try:
            mining_dir = tmp_path / "repo_pool"
            mining_dir.mkdir()
            for idx in range(3):
                repo = mining_dir / f"repo-{idx}"
                repo.mkdir()
                (repo / "README.md").write_text(f"# repo {idx}\n")

            class SlowSideEffectMiner:
                def __init__(self, repository: Repository):
                    self.repository = repository

                async def mine_repo(self, repo_path, repo_name, target_project_id):
                    await self.repository.save_methodology(
                        Methodology(
                            problem_description=(
                                f"[Mined from {repo_name}] recovered timeout pattern"
                            ),
                            solution_code="Use the recovered pattern.",
                            tags=["mined", f"source:{repo_name}"],
                            scope="global",
                            methodology_type="PATTERN",
                        )
                    )
                    await asyncio.sleep(2.0)
                    return _FakeMiningResult(findings=[repo_name])

            async def live_factory(challenger: dict[str, str]) -> LiveMiningBinding:
                challenger_engine = DatabaseEngine(
                    DatabaseConfig(db_path=challenger["db_path"])
                )
                await challenger_engine.connect()
                await challenger_engine.apply_migrations()
                await challenger_engine.initialize_schema()
                challenger_repo = Repository(challenger_engine)

                async def close() -> None:
                    await challenger_engine.close()

                return LiveMiningBinding(
                    repo_miner=SlowSideEffectMiner(challenger_repo),
                    target_project_id="challenger-project",
                    db_path=Path(challenger["db_path"]),
                    close=close,
                )

            runner = SerialEvolutionRunner(
                Repository(engine),
                repo_path=mini_repo,
                db_path=primary_db,
                instances_root=mini_repo / "instances" / "evolution",
                live_mining_factory=live_factory,
                live_repo_timeout_seconds=1.0,
            )

            result = await runner.run_autonomous_loop(
                mining_dir=mining_dir,
                repos_per_round=3,
                max_rounds=1,
                budget_client=_FakeBudgetClient(
                    [BudgetStatus(True, "fake", remaining_credits=1.0, reason="ok")]
                ),
            )

            rows = await engine.fetch_all(
                "SELECT accepted, rejection_reason, extracted_payload "
                "FROM evolution_mined_inputs ORDER BY source_ref"
            )
            payloads = [json.loads(row["extracted_payload"]) for row in rows]
            events = await engine.fetch_all(
                "SELECT event_type FROM evolution_monitor_events "
                "WHERE event_type = 'live_mining_partial_timeout_recovered'"
            )
            assert result.rounds_attempted == 1
            assert all(row["accepted"] == 1 for row in rows)
            assert all(row["rejection_reason"] is None for row in rows)
            assert all(payload["partial_timeout"] is True for payload in payloads)
            assert all(payload["findings_count"] == 1 for payload in payloads)
            assert len(events) == 3
        finally:
            await engine.close()

    async def test_live_folder_timeout_recovers_ganglion_side_effects(
        self,
        mini_repo: Path,
        tmp_path: Path,
    ):
        primary_db = tmp_path / "primary.db"
        engine = DatabaseEngine(DatabaseConfig(db_path=str(primary_db)))
        await engine.connect()
        await engine.apply_migrations()
        await engine.initialize_schema()
        try:
            mining_dir = tmp_path / "repo_pool"
            mining_dir.mkdir()
            repo_path = mining_dir / "typescript-repo"
            repo_path.mkdir()
            (repo_path / "README.md").write_text("# typescript repo\n")

            class SlowGanglionSideEffectMiner:
                def __init__(self, repository: Repository):
                    self.repository = repository

                async def mine_repo(self, repo_path, repo_name, target_project_id):
                    await self.repository.save_methodology(
                        Methodology(
                            problem_description=(
                                f"[Mined from {repo_name}] recovered ganglion pattern"
                            ),
                            solution_code="Use the recovered TypeScript pattern.",
                            tags=["mined", f"source:{repo_name}"],
                            scope="global",
                            methodology_type="PATTERN",
                        )
                    )
                    await asyncio.sleep(2.0)
                    return _FakeMiningResult(findings=[repo_name])

            async def live_factory(challenger: dict[str, str]) -> LiveMiningBinding:
                challenger_db = Path(challenger["db_path"])
                ganglion_db = (
                    challenger_db.parent.parent / "instances" / "typescript" / "claw.db"
                )
                ganglion_engine = DatabaseEngine(DatabaseConfig(db_path=str(ganglion_db)))
                await ganglion_engine.connect()
                await ganglion_engine.apply_migrations()
                await ganglion_engine.initialize_schema()

                async def close() -> None:
                    await ganglion_engine.close()

                return LiveMiningBinding(
                    repo_miner=SlowGanglionSideEffectMiner(Repository(ganglion_engine)),
                    target_project_id="challenger-project",
                    db_path=challenger_db,
                    close=close,
                )

            runner = SerialEvolutionRunner(
                Repository(engine),
                repo_path=mini_repo,
                db_path=primary_db,
                instances_root=mini_repo / "instances" / "evolution",
                live_mining_factory=live_factory,
                live_repo_timeout_seconds=1.0,
            )

            result = await runner.run_autonomous_loop(
                mining_dir=mining_dir,
                repos_per_round=1,
                max_rounds=1,
                budget_client=_FakeBudgetClient(
                    [BudgetStatus(True, "fake", remaining_credits=1.0, reason="ok")]
                ),
            )

            row = await engine.fetch_one(
                "SELECT accepted, rejection_reason, extracted_payload "
                "FROM evolution_mined_inputs"
            )
            payload = json.loads(row["extracted_payload"])
            assert result.rounds_attempted == 1
            assert row["accepted"] == 1
            assert row["rejection_reason"] is None
            assert payload["partial_timeout"] is True
            assert payload["findings_count"] == 1
            assert payload["methodology_ids"]
            assert any(
                path.endswith("instances/typescript/claw.db")
                for path in payload["artifact_db_paths"]
            )
        finally:
            await engine.close()

    async def test_select_folder_repos_retries_rejected_sources(
        self,
        evolution_engine,
        mini_repo: Path,
        tmp_path: Path,
    ):
        repository = Repository(evolution_engine)
        mining_dir = tmp_path / "repo_pool"
        mining_dir.mkdir()
        rejected_repo = mining_dir / "rejected-repo"
        accepted_repo = mining_dir / "accepted-repo"
        fresh_repo = mining_dir / "fresh-repo"
        for path in (rejected_repo, accepted_repo, fresh_repo):
            path.mkdir()

        champion = await repository.create_evolution_instance(
            {
                "role": "champion",
                "version_label": "v1",
                "repo_path": str(mini_repo),
                "db_path": str(tmp_path / "champion.db"),
            }
        )
        run = await repository.create_evolution_run(
            {
                "champion_instance_id": champion["id"],
                "cycle_number": 1,
                "layer": "data_feature",
                "objective": "selection test",
                "status": "rejected",
            }
        )
        await repository.record_evolution_mined_input(
            {
                "run_id": run["id"],
                "source_type": "folder_repo",
                "source_uri": str(rejected_repo.resolve()),
                "source_ref": rejected_repo.name,
                "novelty_score": 0.0,
                "relevance_score": 0.0,
                "accepted": False,
                "rejection_reason": "timeout",
                "extracted_payload": {},
            }
        )
        await repository.record_evolution_mined_input(
            {
                "run_id": run["id"],
                "source_type": "folder_repo",
                "source_uri": str(accepted_repo.resolve()),
                "source_ref": accepted_repo.name,
                "novelty_score": 1.0,
                "relevance_score": 1.0,
                "accepted": True,
                "rejection_reason": None,
                "extracted_payload": {},
            }
        )

        runner = SerialEvolutionRunner(
            repository,
            repo_path=mini_repo,
            db_path=tmp_path / "control.db",
            instances_root=mini_repo / "instances" / "evolution",
        )
        selected = await runner._select_folder_repos(mining_dir, limit=None)

        assert rejected_repo.resolve() in selected
        assert fresh_repo.resolve() in selected
        assert accepted_repo.resolve() not in selected

    async def test_select_folder_repos_skips_permanent_no_source_rejections(
        self,
        evolution_engine,
        mini_repo: Path,
        tmp_path: Path,
    ):
        repository = Repository(evolution_engine)
        mining_dir = tmp_path / "repo_pool"
        mining_dir.mkdir()
        no_source_repo = mining_dir / "no-source-repo"
        fresh_repo = mining_dir / "fresh-repo"
        for path in (no_source_repo, fresh_repo):
            path.mkdir()

        champion = await repository.create_evolution_instance(
            {
                "role": "champion",
                "version_label": "v1",
                "repo_path": str(mini_repo),
                "db_path": str(tmp_path / "champion.db"),
            }
        )
        run = await repository.create_evolution_run(
            {
                "champion_instance_id": champion["id"],
                "cycle_number": 1,
                "layer": "data_feature",
                "objective": "selection test",
                "status": "rejected",
            }
        )
        await repository.record_evolution_mined_input(
            {
                "run_id": run["id"],
                "source_type": "folder_repo",
                "source_uri": str(no_source_repo.resolve()),
                "source_ref": no_source_repo.name,
                "novelty_score": 0.0,
                "relevance_score": 0.0,
                "accepted": False,
                "rejection_reason": "No recognizable source files found",
                "extracted_payload": {},
            }
        )

        runner = SerialEvolutionRunner(
            repository,
            repo_path=mini_repo,
            db_path=tmp_path / "control.db",
            instances_root=mini_repo / "instances" / "evolution",
        )
        selected = await runner._select_folder_repos(mining_dir, limit=None)

        assert fresh_repo.resolve() in selected
        assert no_source_repo.resolve() not in selected

    async def test_select_folder_repos_skips_consumed_source_refs_from_new_paths(
        self,
        evolution_engine,
        mini_repo: Path,
        tmp_path: Path,
    ):
        repository = Repository(evolution_engine)
        old_pool = tmp_path / "old_pool"
        mining_dir = tmp_path / "new_pool"
        old_pool.mkdir()
        mining_dir.mkdir()
        old_repo = old_pool / "same-repo"
        new_repo = mining_dir / "same-repo"
        fresh_repo = mining_dir / "fresh-repo"
        for path in (old_repo, new_repo, fresh_repo):
            path.mkdir()

        champion = await repository.create_evolution_instance(
            {
                "role": "champion",
                "version_label": "v1",
                "repo_path": str(mini_repo),
                "db_path": str(tmp_path / "champion.db"),
            }
        )
        run = await repository.create_evolution_run(
            {
                "champion_instance_id": champion["id"],
                "cycle_number": 1,
                "layer": "data_feature",
                "objective": "selection test",
                "status": "promoted",
            }
        )
        await repository.record_evolution_mined_input(
            {
                "run_id": run["id"],
                "source_type": "folder_repo",
                "source_uri": str(old_repo.resolve()),
                "source_ref": old_repo.name,
                "novelty_score": 1.0,
                "relevance_score": 1.0,
                "accepted": True,
                "rejection_reason": None,
                "extracted_payload": {},
            }
        )

        runner = SerialEvolutionRunner(
            repository,
            repo_path=mini_repo,
            db_path=tmp_path / "control.db",
            instances_root=mini_repo / "instances" / "evolution",
        )
        selected = await runner._select_folder_repos(mining_dir, limit=None)

        assert fresh_repo.resolve() in selected
        assert new_repo.resolve() not in selected

    async def test_select_folder_repos_live_preflight_skips_doc_only_repos(
        self,
        evolution_engine,
        mini_repo: Path,
        tmp_path: Path,
    ):
        mining_dir = tmp_path / "repo_pool"
        mining_dir.mkdir()
        doc_only_repo = mining_dir / "doc-only"
        source_repo = mining_dir / "source-repo"
        doc_only_repo.mkdir()
        source_repo.mkdir()
        (doc_only_repo / "README.md").write_text("# project playbook\n")
        (source_repo / "README.md").write_text("# source repo\n")
        for idx in range(3):
            (source_repo / f"module_{idx}.py").write_text(
                (
                    f"def value_{idx}():\n"
                    f"    return {idx}\n\n"
                    "# realistic source content for live-mining preflight\n" * 20
                )
            )

        runner = SerialEvolutionRunner(
            Repository(evolution_engine),
            repo_path=mini_repo,
            db_path=tmp_path / "control.db",
            instances_root=mini_repo / "instances" / "evolution",
            require_live_source_preflight=True,
        )
        selected = await runner._select_folder_repos(mining_dir, limit=None)

        assert source_repo.resolve() in selected
        assert doc_only_repo.resolve() not in selected

    async def test_paired_retrieval_evaluation_detects_challenger_lift(
        self,
        mini_repo: Path,
        tmp_path: Path,
    ):
        primary_db = tmp_path / "primary.db"
        engine = DatabaseEngine(DatabaseConfig(db_path=str(primary_db)))
        await engine.connect()
        await engine.apply_migrations()
        await engine.initialize_schema()
        try:
            mining_dir = tmp_path / "repo_pool"
            mining_dir.mkdir()
            for idx in range(3):
                repo = mining_dir / f"repo-{idx}"
                repo.mkdir()
                (repo / "README.md").write_text(f"# repo {idx}\n")

            class ChallengerWritingMiner:
                def __init__(self, repository: Repository):
                    self.repository = repository
                    self.calls: list[str] = []

                async def mine_repo(self, repo_path, repo_name, target_project_id):
                    self.calls.append(repo_name)
                    methodology = await self.repository.save_methodology(
                        Methodology(
                            problem_description=(
                                f"[Mined from {repo_name}] reusable pattern for {repo_name}"
                            ),
                            solution_code=f"Use the {repo_name} pattern.",
                            tags=["mined", f"source:{repo_name}"],
                            scope="global",
                            methodology_type="PATTERN",
                        )
                    )
                    return _FakeMiningResult(
                        findings=[repo_name],
                        methodology_ids=[methodology.id],
                    )

            miner_ref: dict[str, ChallengerWritingMiner] = {}

            async def live_factory(challenger: dict[str, str]) -> LiveMiningBinding:
                challenger_engine = DatabaseEngine(
                    DatabaseConfig(db_path=challenger["db_path"])
                )
                await challenger_engine.connect()
                await challenger_engine.apply_migrations()
                await challenger_engine.initialize_schema()
                challenger_repo = Repository(challenger_engine)
                miner = ChallengerWritingMiner(challenger_repo)
                miner_ref["miner"] = miner

                async def close() -> None:
                    await challenger_engine.close()

                return LiveMiningBinding(
                    repo_miner=miner,
                    target_project_id="challenger-project",
                    db_path=Path(challenger["db_path"]),
                    close=close,
                )

            runner = SerialEvolutionRunner(
                Repository(engine),
                repo_path=mini_repo,
                db_path=primary_db,
                instances_root=mini_repo / "instances" / "evolution",
                live_mining_factory=live_factory,
            )

            result = await runner.run_autonomous_loop(
                mining_dir=mining_dir,
                repos_per_round=3,
                max_rounds=1,
                budget_client=_FakeBudgetClient(
                    [BudgetStatus(True, "fake", remaining_credits=1.0, reason="ok")]
                ),
            )

            eval_row = await engine.fetch_one(
                "SELECT * FROM evolution_evaluations WHERE eval_slice = 'paired_retrieval'"
            )
            metrics = json.loads(eval_row["metrics_json"])
            assert result.cycle_results[0].decision == "promote"
            assert miner_ref["miner"].calls == ["repo-0", "repo-1", "repo-2"]
            assert eval_row["passed"] == 1
            assert eval_row["challenger_score"] > eval_row["champion_score"]
            assert metrics["avg_challenger_retrieval"] > metrics["avg_champion_retrieval"]
        finally:
            await engine.close()

    async def test_paired_task_readiness_rewards_actionable_challenger_coverage(
        self,
        mini_repo: Path,
        tmp_path: Path,
    ):
        primary_db = tmp_path / "primary.db"
        engine = DatabaseEngine(DatabaseConfig(db_path=str(primary_db)))
        await engine.connect()
        await engine.apply_migrations()
        await engine.initialize_schema()
        try:
            mining_dir = tmp_path / "repo_pool"
            mining_dir.mkdir()
            for idx in range(3):
                repo = mining_dir / f"repo-{idx}"
                repo.mkdir()
                (repo / "README.md").write_text(f"# repo {idx}\n")

            class ActionableMiner:
                def __init__(self, repository: Repository):
                    self.repository = repository

                async def mine_repo(self, repo_path, repo_name, target_project_id):
                    methodology = await self.repository.save_methodology(
                        Methodology(
                            problem_description=(
                                f"[Mined from {repo_name}] task-ready pattern for {repo_name}"
                            ),
                            solution_code=f"Use the {repo_name} implementation path.",
                            tags=["mined", f"source:{repo_name}"],
                            scope="global",
                            methodology_type="PATTERN",
                        )
                    )
                    template = await self.repository.create_action_template(
                        ActionTemplate(
                            title=f"Apply {repo_name} pattern",
                            problem_pattern=f"Apply {repo_name} as a reusable CAM enhancement pattern",
                            execution_steps=["inspect source", "adapt pattern"],
                            acceptance_checks=["tests pass", "retrieval improves"],
                            rollback_steps=["remove imported pattern"],
                            source_methodology_id=methodology.id,
                            source_repo=repo_name,
                            confidence=0.9,
                        )
                    )
                    return _FakeMiningResult(
                        findings=[repo_name],
                        methodology_ids=[methodology.id],
                        action_template_ids=[template.id],
                    )

            async def live_factory(challenger: dict[str, str]) -> LiveMiningBinding:
                challenger_engine = DatabaseEngine(
                    DatabaseConfig(db_path=challenger["db_path"])
                )
                await challenger_engine.connect()
                await challenger_engine.apply_migrations()
                await challenger_engine.initialize_schema()
                challenger_repo = Repository(challenger_engine)

                async def close() -> None:
                    await challenger_engine.close()

                return LiveMiningBinding(
                    repo_miner=ActionableMiner(challenger_repo),
                    target_project_id="challenger-project",
                    db_path=Path(challenger["db_path"]),
                    close=close,
                )

            runner = SerialEvolutionRunner(
                Repository(engine),
                repo_path=mini_repo,
                db_path=primary_db,
                instances_root=mini_repo / "instances" / "evolution",
                live_mining_factory=live_factory,
            )

            result = await runner.run_autonomous_loop(
                mining_dir=mining_dir,
                repos_per_round=3,
                max_rounds=1,
                budget_client=_FakeBudgetClient(
                    [BudgetStatus(True, "fake", remaining_credits=1.0, reason="ok")]
                ),
            )

            eval_row = await engine.fetch_one(
                "SELECT * FROM evolution_evaluations WHERE eval_slice = 'paired_task_readiness'"
            )
            decision = await engine.fetch_one("SELECT * FROM evolution_decisions")
            gate_report = json.loads(decision["gate_report"])
            metrics = json.loads(eval_row["metrics_json"])
            assert result.cycle_results[0].decision == "promote"
            assert eval_row["passed"] == 1
            assert gate_report["primary_challenger_score"] == eval_row["challenger_score"]
            assert metrics["avg_challenger_task_readiness"] > metrics["avg_champion_task_readiness"]
            assert metrics["avg_challenger_action_template_score"] > 0.0
            assert metrics["avg_challenger_action_template_application_score"] > 0.0
            report = metrics["task_reports"][0]
            assert report["champion"]["artifact_attribution_score"] == 0.0
            assert report["challenger"]["artifact_attribution_score"] > 0.0
            assert (
                report["challenger"]["action_template_application_trace"][0]
                ["checks"]["has_execution_steps"]
                is True
            )
            assert (
                report["challenger"]["action_template_application_trace"][0]
                ["checks"]["has_acceptance_checks"]
                is True
            )
        finally:
            await engine.close()

    async def test_paired_task_readiness_rewards_attributed_mined_methodologies_when_retrieval_ties(
        self,
        mini_repo: Path,
        tmp_path: Path,
    ):
        primary_db = tmp_path / "primary.db"
        engine = DatabaseEngine(DatabaseConfig(db_path=str(primary_db)))
        await engine.connect()
        await engine.apply_migrations()
        await engine.initialize_schema()
        try:
            repository = Repository(engine)
            await repository.save_methodology(
                Methodology(
                    problem_description="Apply repo-0 as a reusable CAM enhancement pattern",
                    solution_code="Generic champion coverage.",
                    tags=["source:baseline"],
                    scope="global",
                    methodology_type="PATTERN",
                )
            )

            mining_dir = tmp_path / "repo_pool"
            mining_dir.mkdir()
            for idx in range(3):
                repo = mining_dir / f"repo-{idx}"
                repo.mkdir()
                (repo / "README.md").write_text(f"# repo {idx}\n")

            class AttributedMiner:
                def __init__(self, repository: Repository):
                    self.repository = repository

                async def mine_repo(self, repo_path, repo_name, target_project_id):
                    methodology = await self.repository.save_methodology(
                        Methodology(
                            problem_description=(
                                f"[Mined from {repo_name}] Apply {repo_name} "
                                "as a reusable CAM enhancement pattern"
                            ),
                            solution_code=f"Use the attributed {repo_name} pattern.",
                            tags=["mined", f"source:{repo_name}"],
                            scope="global",
                            methodology_type="PATTERN",
                        )
                    )
                    return _FakeMiningResult(
                        findings=[repo_name],
                        methodology_ids=[methodology.id],
                    )

            async def live_factory(challenger: dict[str, str]) -> LiveMiningBinding:
                challenger_engine = DatabaseEngine(
                    DatabaseConfig(db_path=challenger["db_path"])
                )
                await challenger_engine.connect()
                await challenger_engine.apply_migrations()
                await challenger_engine.initialize_schema()
                challenger_repo = Repository(challenger_engine)

                async def close() -> None:
                    await challenger_engine.close()

                return LiveMiningBinding(
                    repo_miner=AttributedMiner(challenger_repo),
                    target_project_id="challenger-project",
                    db_path=Path(challenger["db_path"]),
                    close=close,
                )

            runner = SerialEvolutionRunner(
                Repository(engine),
                repo_path=mini_repo,
                db_path=primary_db,
                instances_root=mini_repo / "instances" / "evolution",
                live_mining_factory=live_factory,
            )

            result = await runner.run_autonomous_loop(
                mining_dir=mining_dir,
                repos_per_round=3,
                max_rounds=1,
                budget_client=_FakeBudgetClient(
                    [BudgetStatus(True, "fake", remaining_credits=1.0, reason="ok")]
                ),
            )

            eval_row = await engine.fetch_one(
                "SELECT * FROM evolution_evaluations WHERE eval_slice = 'paired_task_readiness'"
            )
            metrics = json.loads(eval_row["metrics_json"])
            first_report = metrics["task_reports"][0]
            assert result.cycle_results[0].decision == "promote"
            assert eval_row["passed"] == 1
            assert first_report["champion"]["retrieval_score"] > 0
            assert first_report["challenger"]["retrieval_score"] > 0
            assert first_report["champion"]["artifact_attribution_score"] == 0.0
            assert first_report["challenger"]["artifact_attribution_score"] == 1.0
            assert (
                first_report["challenger"]["action_template_application_score"]
                == 0.0
            )
        finally:
            await engine.close()

    async def test_paired_task_readiness_counts_successful_ganglion_artifacts(
        self,
        mini_repo: Path,
        tmp_path: Path,
    ):
        primary_db = tmp_path / "primary.db"
        engine = DatabaseEngine(DatabaseConfig(db_path=str(primary_db)))
        await engine.connect()
        await engine.apply_migrations()
        await engine.initialize_schema()
        try:
            repository = Repository(engine)
            await repository.save_methodology(
                Methodology(
                    problem_description="Apply repo-0 as a reusable CAM enhancement pattern",
                    solution_code="Generic champion coverage.",
                    tags=["source:baseline"],
                    scope="global",
                    methodology_type="PATTERN",
                )
            )

            mining_dir = tmp_path / "repo_pool"
            mining_dir.mkdir()
            for idx in range(3):
                repo = mining_dir / f"repo-{idx}"
                repo.mkdir()
                (repo / "README.md").write_text(f"# repo {idx}\n")

            class GanglionAttributedMiner:
                def __init__(self, challenger_db_path: Path):
                    self.challenger_db_path = challenger_db_path

                async def mine_repo(self, repo_path, repo_name, target_project_id):
                    ganglion_db = (
                        self.challenger_db_path.parent.parent
                        / "instances"
                        / "typescript"
                        / "claw.db"
                    )
                    ganglion_engine = DatabaseEngine(
                        DatabaseConfig(db_path=str(ganglion_db))
                    )
                    await ganglion_engine.connect()
                    await ganglion_engine.apply_migrations()
                    await ganglion_engine.initialize_schema()
                    try:
                        ganglion_repo = Repository(ganglion_engine)
                        methodology = await ganglion_repo.save_methodology(
                            Methodology(
                                problem_description=(
                                    f"[Mined from {repo_name}] Apply {repo_name} "
                                    "as a reusable CAM enhancement pattern"
                                ),
                                solution_code=f"Use the attributed {repo_name} pattern.",
                                tags=["mined", f"source:{repo_name}"],
                                scope="global",
                                methodology_type="PATTERN",
                            )
                        )
                    finally:
                        await ganglion_engine.close()
                    return _FakeMiningResult(
                        findings=[repo_name],
                        methodology_ids=[methodology.id],
                    )

            async def live_factory(challenger: dict[str, str]) -> LiveMiningBinding:
                challenger_db = Path(challenger["db_path"])
                return LiveMiningBinding(
                    repo_miner=GanglionAttributedMiner(challenger_db),
                    target_project_id="challenger-project",
                    db_path=challenger_db,
                    close=None,
                )

            runner = SerialEvolutionRunner(
                Repository(engine),
                repo_path=mini_repo,
                db_path=primary_db,
                instances_root=mini_repo / "instances" / "evolution",
                live_mining_factory=live_factory,
            )

            result = await runner.run_autonomous_loop(
                mining_dir=mining_dir,
                repos_per_round=3,
                max_rounds=1,
                budget_client=_FakeBudgetClient(
                    [BudgetStatus(True, "fake", remaining_credits=1.0, reason="ok")]
                ),
            )

            mined_row = await engine.fetch_one(
                "SELECT extracted_payload FROM evolution_mined_inputs "
                "WHERE source_ref = 'repo-0'"
            )
            payload = json.loads(mined_row["extracted_payload"])
            eval_row = await engine.fetch_one(
                "SELECT * FROM evolution_evaluations "
                "WHERE eval_slice = 'paired_task_readiness'"
            )
            metrics = json.loads(eval_row["metrics_json"])
            first_report = metrics["task_reports"][0]
            assert result.cycle_results[0].decision == "promote"
            assert payload["artifact_db_paths"]
            assert payload["artifact_db_paths"][0].endswith("instances/typescript/claw.db")
            assert eval_row["passed"] == 1
            assert first_report["champion"]["artifact_attribution_score"] == 0.0
            assert first_report["challenger"]["artifact_attribution_score"] == 1.0
            assert first_report["challenger"]["artifact_db_paths"]
        finally:
            await engine.close()

    async def test_required_validation_gate_allows_isolated_challenger_promotion(
        self,
        mini_repo: Path,
        tmp_path: Path,
    ):
        primary_db = tmp_path / "primary.db"
        engine = DatabaseEngine(DatabaseConfig(db_path=str(primary_db)))
        await engine.connect()
        await engine.apply_migrations()
        await engine.initialize_schema()
        try:
            mining_dir = tmp_path / "repo_pool"
            mining_dir.mkdir()
            for idx in range(3):
                repo = mining_dir / f"repo-{idx}"
                repo.mkdir()
                (repo / "README.md").write_text(f"# repo {idx}\n")

            class ValidatingMiner:
                def __init__(self, repository: Repository):
                    self.repository = repository

                async def mine_repo(self, repo_path, repo_name, target_project_id):
                    methodology = await self.repository.save_methodology(
                        Methodology(
                            problem_description=(
                                f"[Mined from {repo_name}] task-ready pattern for {repo_name}"
                            ),
                            solution_code=f"Use the {repo_name} implementation path.",
                            tags=["mined", f"source:{repo_name}"],
                            scope="global",
                            methodology_type="PATTERN",
                        )
                    )
                    template = await self.repository.create_action_template(
                        ActionTemplate(
                            title=f"Apply {repo_name} pattern",
                            problem_pattern=f"Apply {repo_name} as a reusable CAM enhancement pattern",
                            execution_steps=["inspect source", "adapt pattern"],
                            acceptance_checks=["tests pass"],
                            source_methodology_id=methodology.id,
                            source_repo=repo_name,
                            confidence=0.9,
                        )
                    )
                    return _FakeMiningResult(
                        findings=[repo_name],
                        methodology_ids=[methodology.id],
                        action_template_ids=[template.id],
                    )

            async def live_factory(challenger: dict[str, str]) -> LiveMiningBinding:
                challenger_engine = DatabaseEngine(
                    DatabaseConfig(db_path=challenger["db_path"])
                )
                await challenger_engine.connect()
                await challenger_engine.apply_migrations()
                await challenger_engine.initialize_schema()
                challenger_repo = Repository(challenger_engine)

                async def close() -> None:
                    await challenger_engine.close()

                return LiveMiningBinding(
                    repo_miner=ValidatingMiner(challenger_repo),
                    target_project_id="challenger-project",
                    db_path=Path(challenger["db_path"]),
                    close=close,
                )

            runner = SerialEvolutionRunner(
                Repository(engine),
                repo_path=mini_repo,
                db_path=primary_db,
                instances_root=mini_repo / "instances" / "evolution",
                gate_config=PromotionGateConfig(require_validation_gate=True),
                live_mining_factory=live_factory,
            )

            result = await runner.run_autonomous_loop(
                mining_dir=mining_dir,
                repos_per_round=3,
                max_rounds=1,
                budget_client=_FakeBudgetClient(
                    [BudgetStatus(True, "fake", remaining_credits=1.0, reason="ok")]
                ),
            )

            decision = await engine.fetch_one("SELECT * FROM evolution_decisions")
            gate_report = json.loads(decision["gate_report"])
            assert result.cycle_results[0].decision == "promote"
            assert gate_report["validation_gate"] == "required"
            assert gate_report["validation_report"]["passed"] is True
            assert gate_report["validation_report"]["checks"]["db_is_isolated"] is True
            assert (
                gate_report["validation_report"]["checks"]
                ["live_mining_targeted_challenger_db"]
                is True
            )
        finally:
            await engine.close()

    async def test_autonomous_loop_stops_before_partial_folder_batch(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
        tmp_path: Path,
    ):
        mining_dir = tmp_path / "repo_pool"
        mining_dir.mkdir()
        for idx in range(2):
            repo = mining_dir / f"repo-{idx}"
            repo.mkdir()
            (repo / "README.md").write_text(f"# repo {idx}\n")

        runner = SerialEvolutionRunner(
            Repository(evolution_engine),
            repo_path=mini_repo,
            instances_root=mini_repo / "instances" / "evolution",
        )
        result = await runner.run_autonomous_loop(
            mining_dir=mining_dir,
            repos_per_round=3,
            budget_client=_FakeBudgetClient(
                [BudgetStatus(True, "fake", remaining_credits=1.0, reason="ok")]
            ),
        )

        assert result.rounds_attempted == 0
        assert "fewer than 3 unmined repos remain" in result.stop_reason

    async def test_sync_champion_pointer_rewrites_current_champion_file(
        self,
        evolution_engine: DatabaseEngine,
        mini_repo: Path,
    ):
        runner = SerialEvolutionRunner(
            Repository(evolution_engine),
            repo_path=mini_repo,
            db_path=mini_repo / "data" / "claw.db",
            instances_root=mini_repo / "instances" / "evolution",
        )
        champion = await runner.register_current_workspace(version_label="v-pointer")

        pointer_path = mini_repo / "instances" / "evolution" / "current_champion.json"
        pointer_path.unlink()
        payload = await runner.sync_champion_pointer()

        pointer = json.loads(pointer_path.read_text())
        assert payload["champion"]["id"] == champion["id"]
        assert pointer["instance_id"] == champion["id"]
        assert pointer["db_path"] == str(mini_repo / "data" / "claw.db")


class TestApprovedModelConfig:
    @pytest.mark.parametrize(
        "config_path",
        [
            Path("claw.toml"),
            Path("claw_cheap.toml"),
            Path("claw_dspro.toml"),
            Path("claw_grok.toml"),
        ],
    )
    def test_openrouter_agents_and_fallbacks_use_only_approved_models(
        self,
        config_path: Path,
    ):
        cfg = toml.load(config_path)
        approved = set(APPROVED_MODEL_IDS)

        assert set(cfg["llm"].get("fallback_models", [])) <= approved

        for agent_name, agent_cfg in cfg.get("agents", {}).items():
            if not agent_cfg.get("enabled", False):
                continue
            if agent_cfg.get("mode") != "openrouter":
                continue
            assert agent_cfg.get("model") in approved, agent_name

    @pytest.mark.parametrize(
        "config_path",
        [
            Path("claw.toml"),
            Path("claw_cheap.toml"),
            Path("claw_dspro.toml"),
            Path("claw_grok.toml"),
        ],
    )
    def test_automation_embeddings_do_not_use_paid_openrouter_models(
        self,
        config_path: Path,
    ):
        cfg = toml.load(config_path)
        embeddings = cfg["embeddings"]

        assert embeddings["model"] == "hash-embedding-384"
        assert "/" not in embeddings["model"]
        assert embeddings["required_model"] == "hash-embedding-384"
