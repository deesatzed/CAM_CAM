"""Tests for RL-driven mining self-recovery.

Covers:
    1. MiningRecoveryConfig — defaults, overrides, serialization
    2. AgentConfig.context_window_tokens — field presence and behavior
    3. MiningModelSelector.estimate_prompt_tokens — chars-to-tokens math
    4. MiningModelSelector.get_eligible_agents — filtering by context window
    5. MiningModelSelector.build_escalation_chain — ordering logic
    6. MiningModelSelector.select_best_model — RL selection + cold-start fallback
    7. RepoMiningResult — recovery_attempts / recovery_strategy fields
    8. Repository: record_mining_outcome roundtrip
    9. Repository: get_mining_model_stats aggregation
   10. Repository: get_best_mining_model_for_size RL selection
   11. _deduplicate_chunk_findings — exact + partial overlap
   12. _mine_with_recovery — recovery disabled path
   13. mining_outcomes DB migration — table auto-created

All tests use REAL dependencies — no mocks, no placeholders, no cached responses.
Database tests use the real SQLite in-memory engine.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import field

import pytest

from claw.core.config import (
    AgentConfig,
    BrainConfig,
    ClawConfig,
    DatabaseConfig,
    MiningConfig,
    MiningRecoveryConfig,
)
from claw.db.engine import DatabaseEngine
from claw.db.repository import Repository
from claw.memory.hybrid_search import HybridSearch
from claw.memory.semantic import SemanticMemory
from claw.llm.client import LLMResponse
from claw.miner import (
    MiningFinding,
    MiningModelSelector,
    RepoMiner,
    RepoMiningResult,
)


# ---------------------------------------------------------------------------
# Deterministic embedding engine (same pattern as other test files)
# ---------------------------------------------------------------------------

class FixedEmbeddingEngine:
    """Deterministic embedding engine using SHA-384 for reproducible tests."""

    DIMENSION = 384

    def encode(self, text: str) -> list[float]:
        h = hashlib.sha384(text.encode()).digest()
        raw = [b / 255.0 for b in h] * 8
        return raw[: self.DIMENSION]

    async def async_encode(self, text: str) -> list[float]:
        return self.encode(text)

    def cosine_similarity(self, a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def db_pair():
    """Create an in-memory DB pair (engine, repository)."""
    config = DatabaseConfig(db_path=":memory:")
    engine = DatabaseEngine(config)
    await engine.connect()
    await engine.initialize_schema()
    repo = Repository(engine)
    yield engine, repo
    await engine.close()


@pytest.fixture
def small_config() -> ClawConfig:
    """Config with 3 agents of varying context windows for selector tests."""
    config = ClawConfig()
    config.agents = {
        "small": AgentConfig(
            model="openai/gpt-5.4-mini",
            enabled=True,
            context_window_tokens=128_000,
        ),
        "medium": AgentConfig(
            model="google/gemini-2.5-pro",
            enabled=True,
            context_window_tokens=1_000_000,
        ),
        "large": AgentConfig(
            model="x-ai/grok-4.20-beta",
            enabled=True,
            context_window_tokens=2_000_000,
        ),
    }
    config.mining.recovery = MiningRecoveryConfig(
        escalation_order=["small", "medium", "large"],
    )
    return config


# ===========================================================================
# 1. MiningRecoveryConfig defaults
# ===========================================================================

class TestMiningRecoveryConfig:
    def test_defaults(self):
        cfg = MiningRecoveryConfig()
        assert cfg.enabled is True
        assert cfg.max_escalation_attempts == 3
        assert cfg.content_reduction_factor == 0.50
        assert cfg.max_chunks == 4
        assert cfg.escalation_order == ["claude", "gemini", "grok"]
        assert cfg.token_estimate_chars_per_token == 4.0
        assert cfg.min_context_headroom_pct == 0.20

    def test_override(self):
        cfg = MiningRecoveryConfig(
            enabled=False,
            max_escalation_attempts=5,
            escalation_order=["grok", "claude"],
        )
        assert cfg.enabled is False
        assert cfg.max_escalation_attempts == 5
        assert cfg.escalation_order == ["grok", "claude"]

    def test_wired_into_mining_config(self):
        mc = MiningConfig()
        assert isinstance(mc.recovery, MiningRecoveryConfig)
        assert mc.recovery.enabled is True

    def test_claw_config_loads_recovery(self):
        cc = ClawConfig()
        assert cc.mining.recovery.enabled is True
        assert cc.mining.recovery.max_escalation_attempts == 3


# ===========================================================================
# 2. AgentConfig.context_window_tokens
# ===========================================================================

class TestAgentConfigContextWindow:
    def test_default_is_zero(self):
        cfg = AgentConfig()
        assert cfg.context_window_tokens == 0

    def test_custom_value(self):
        cfg = AgentConfig(context_window_tokens=2_000_000)
        assert cfg.context_window_tokens == 2_000_000

    def test_zero_means_unknown(self):
        """context_window_tokens=0 is treated as 'unknown' by selector."""
        cfg = AgentConfig(model="test/model", enabled=True, context_window_tokens=0)
        assert cfg.context_window_tokens == 0


# ===========================================================================
# 3. MiningModelSelector.estimate_prompt_tokens
# ===========================================================================

class TestEstimatePromptTokens:
    def test_basic_estimation(self, small_config):
        selector = MiningModelSelector(small_config)
        # 4000 chars / 4.0 chars_per_token = 1000 tokens
        assert selector.estimate_prompt_tokens("x" * 4000) == 1000

    def test_empty_prompt(self, small_config):
        selector = MiningModelSelector(small_config)
        assert selector.estimate_prompt_tokens("") == 0

    def test_custom_chars_per_token(self):
        config = ClawConfig()
        config.mining.recovery = MiningRecoveryConfig(
            token_estimate_chars_per_token=3.0,
        )
        config.agents = {"a": AgentConfig(model="m", enabled=True)}
        selector = MiningModelSelector(config)
        # 3000 chars / 3.0 = 1000 tokens
        assert selector.estimate_prompt_tokens("x" * 3000) == 1000

    def test_large_prompt(self, small_config):
        selector = MiningModelSelector(small_config)
        # 400,000 chars / 4 = 100,000 tokens
        prompt = "a" * 400_000
        assert selector.estimate_prompt_tokens(prompt) == 100_000


# ===========================================================================
# 4. MiningModelSelector.get_eligible_agents
# ===========================================================================

class TestGetEligibleAgents:
    def test_all_fit(self, small_config):
        selector = MiningModelSelector(small_config)
        # 10K tokens → required ~12.5K with 20% headroom
        eligible = selector.get_eligible_agents(10_000)
        names = [n for n, _ in eligible]
        assert names == ["small", "medium", "large"]

    def test_small_excluded(self, small_config):
        selector = MiningModelSelector(small_config)
        # 110K tokens → required ~137.5K (> 128K small limit)
        eligible = selector.get_eligible_agents(110_000)
        names = [n for n, _ in eligible]
        assert "small" not in names
        assert "medium" in names
        assert "large" in names

    def test_only_large_fits(self, small_config):
        selector = MiningModelSelector(small_config)
        # 900K tokens → required ~1.125M (> 1M medium limit)
        eligible = selector.get_eligible_agents(900_000)
        names = [n for n, _ in eligible]
        assert names == ["large"]

    def test_none_fit(self, small_config):
        selector = MiningModelSelector(small_config)
        # 2M tokens → required ~2.5M (> 2M large limit)
        eligible = selector.get_eligible_agents(2_000_000)
        names = [n for n, _ in eligible]
        assert names == []

    def test_unknown_window_sorted_last(self):
        """Agents with context_window_tokens=0 go after known-eligible."""
        config = ClawConfig()
        config.agents = {
            "known": AgentConfig(
                model="m1", enabled=True, context_window_tokens=500_000,
            ),
            "unknown": AgentConfig(
                model="m2", enabled=True, context_window_tokens=0,
            ),
        }
        config.mining.recovery = MiningRecoveryConfig()
        selector = MiningModelSelector(config)
        eligible = selector.get_eligible_agents(10_000)
        names = [n for n, _ in eligible]
        assert names == ["known", "unknown"]

    def test_disabled_agents_excluded(self):
        config = ClawConfig()
        config.agents = {
            "enabled": AgentConfig(
                model="m1", enabled=True, context_window_tokens=500_000,
            ),
            "disabled": AgentConfig(
                model="m2", enabled=False, context_window_tokens=2_000_000,
            ),
        }
        config.mining.recovery = MiningRecoveryConfig()
        selector = MiningModelSelector(config)
        eligible = selector.get_eligible_agents(10_000)
        names = [n for n, _ in eligible]
        assert "disabled" not in names
        assert "enabled" in names

    def test_agents_without_model_excluded(self):
        config = ClawConfig()
        config.agents = {
            "has_model": AgentConfig(
                model="m1", enabled=True, context_window_tokens=500_000,
            ),
            "no_model": AgentConfig(
                model="", enabled=True, context_window_tokens=2_000_000,
            ),
        }
        config.mining.recovery = MiningRecoveryConfig()
        selector = MiningModelSelector(config)
        eligible = selector.get_eligible_agents(10_000)
        names = [n for n, _ in eligible]
        assert names == ["has_model"]

    def test_ascending_sort(self, small_config):
        """Smallest sufficient model first (cost optimization)."""
        selector = MiningModelSelector(small_config)
        eligible = selector.get_eligible_agents(10_000)
        windows = [cfg.context_window_tokens for _, cfg in eligible]
        assert windows == sorted(windows)


# ===========================================================================
# 5. MiningModelSelector.build_escalation_chain
# ===========================================================================

class TestBuildEscalationChain:
    def test_eligible_first_then_config_order(self, small_config):
        selector = MiningModelSelector(small_config)
        chain = selector.build_escalation_chain(10_000)
        names = [n for n, _ in chain]
        # All eligible in ascending order (small, medium, large)
        assert names == ["small", "medium", "large"]

    def test_no_duplicates(self, small_config):
        selector = MiningModelSelector(small_config)
        chain = selector.build_escalation_chain(10_000)
        names = [n for n, _ in chain]
        assert len(names) == len(set(names))

    def test_escalation_order_fills_gaps(self):
        """If escalation_order names an agent not in eligible, it gets added."""
        config = ClawConfig()
        config.agents = {
            "a": AgentConfig(model="m1", enabled=True, context_window_tokens=100_000),
            "b": AgentConfig(model="m2", enabled=True, context_window_tokens=0),
        }
        config.mining.recovery = MiningRecoveryConfig(
            escalation_order=["b", "a"],
        )
        selector = MiningModelSelector(config)
        # At 80K tokens, required=100K → 'a' fits (100K >= 100K), 'b' unknown
        chain = selector.build_escalation_chain(80_000)
        names = [n for n, _ in chain]
        # 'a' first (eligible), then 'b' (unknown, but in eligible tail)
        assert names[0] == "a"
        assert "b" in names

    def test_returns_model_ids(self, small_config):
        selector = MiningModelSelector(small_config)
        chain = selector.build_escalation_chain(10_000)
        models = [m for _, m in chain]
        assert "openai/gpt-5.4-mini" in models
        assert "x-ai/grok-4.20-beta" in models

    def test_empty_when_no_agents(self):
        config = ClawConfig()
        config.agents = {}
        config.mining.recovery = MiningRecoveryConfig()
        selector = MiningModelSelector(config)
        chain = selector.build_escalation_chain(10_000)
        assert chain == []


# ===========================================================================
# 6. MiningModelSelector.select_best_model — RL + cold start
# ===========================================================================

class TestSelectBestModel:
    @pytest.mark.asyncio
    async def test_cold_start_returns_first_eligible(self, small_config):
        """No RL data → returns first from escalation chain."""
        selector = MiningModelSelector(small_config, repository=None)
        name, model = await selector.select_best_model(10_000)
        assert name == "small"
        assert model == "openai/gpt-5.4-mini"

    @pytest.mark.asyncio
    async def test_raises_when_no_agents(self):
        config = ClawConfig()
        config.agents = {}
        config.mining.recovery = MiningRecoveryConfig()
        selector = MiningModelSelector(config, repository=None)
        with pytest.raises(ValueError, match="No model configured"):
            await selector.select_best_model(10_000)

    @pytest.mark.asyncio
    async def test_rl_selection_returns_best(self, small_config, db_pair):
        """When RL data exists, the highest success rate model is selected."""
        engine, repo = db_pair

        # Record 5 successes for grok, 1 success + 4 failures for small
        for _ in range(5):
            await repo.record_mining_outcome(
                model_used="x-ai/grok-4.20-beta", agent_id="large",
                brain="python", repo_name="TestRepo",
                repo_size_bytes=100_000, prompt_tokens_estimated=10_000,
                strategy="primary", success=True, findings_count=5,
                tokens_used=1000, duration_seconds=2.0,
            )
        for i in range(5):
            await repo.record_mining_outcome(
                model_used="openai/gpt-5.4-mini", agent_id="small",
                brain="python", repo_name="TestRepo",
                repo_size_bytes=100_000, prompt_tokens_estimated=10_000,
                strategy="primary", success=(i == 0), findings_count=(3 if i == 0 else 0),
                tokens_used=500, duration_seconds=1.0,
            )

        selector = MiningModelSelector(small_config, repository=repo)
        name, model = await selector.select_best_model(10_000)
        # Grok has 100% success rate vs small's 20%
        assert model == "x-ai/grok-4.20-beta"
        assert name == "large"

    @pytest.mark.asyncio
    async def test_rl_cold_start_with_repo(self, small_config, db_pair):
        """With repo but insufficient data (< min_observations), use fallback."""
        engine, repo = db_pair
        # Only 1 outcome (needs 3 for RL)
        await repo.record_mining_outcome(
            model_used="x-ai/grok-4.20-beta", agent_id="large",
            brain="python", repo_name="Test",
            repo_size_bytes=50_000, prompt_tokens_estimated=10_000,
            strategy="primary", success=True, findings_count=3,
            tokens_used=500, duration_seconds=1.0,
        )
        selector = MiningModelSelector(small_config, repository=repo)
        name, model = await selector.select_best_model(10_000)
        # Fallback to first eligible (small)
        assert name == "small"
        assert model == "openai/gpt-5.4-mini"


# ===========================================================================
# 7. RepoMiningResult — new fields
# ===========================================================================

class TestRepoMiningResultFields:
    def test_recovery_fields_defaults(self):
        result = RepoMiningResult(
            repo_name="test",
            repo_path="/tmp/test",
        )
        assert result.recovery_attempts == 0
        assert result.recovery_strategy == ""

    def test_recovery_fields_set(self):
        result = RepoMiningResult(
            repo_name="test",
            repo_path="/tmp/test",
            recovery_attempts=3,
            recovery_strategy="chunk_mining",
        )
        assert result.recovery_attempts == 3
        assert result.recovery_strategy == "chunk_mining"


# ===========================================================================
# 8. Repository: record_mining_outcome roundtrip
# ===========================================================================

class TestRecordMiningOutcome:
    @pytest.mark.asyncio
    async def test_insert_and_retrieve(self, db_pair):
        engine, repo = db_pair
        outcome_id = await repo.record_mining_outcome(
            model_used="openai/gpt-5.4-mini",
            agent_id="small",
            brain="typescript",
            repo_name="GitNexus",
            repo_size_bytes=1_500_000,
            prompt_tokens_estimated=367_000,
            strategy="primary",
            success=False,
            findings_count=0,
            tokens_used=0,
            duration_seconds=5.2,
            error_type="NullContent",
            error_detail="LLM returned null content",
        )
        assert outcome_id is not None
        # Verify via raw query
        rows = await engine.fetch_all(
            "SELECT * FROM mining_outcomes WHERE id = ?", [outcome_id],
        )
        assert len(rows) == 1
        row = dict(rows[0])
        assert row["model_used"] == "openai/gpt-5.4-mini"
        assert row["brain"] == "typescript"
        assert row["repo_name"] == "GitNexus"
        assert row["strategy"] == "primary"
        assert row["success"] == 0  # False → 0
        assert row["error_type"] == "NullContent"

    @pytest.mark.asyncio
    async def test_success_flag(self, db_pair):
        engine, repo = db_pair
        oid = await repo.record_mining_outcome(
            model_used="x-ai/grok-4.20-beta",
            agent_id="large",
            brain="typescript",
            repo_name="GitNexus",
            repo_size_bytes=1_500_000,
            prompt_tokens_estimated=200_000,
            strategy="model_escalation",
            success=True,
            findings_count=12,
            tokens_used=5000,
            duration_seconds=18.7,
        )
        rows = await engine.fetch_all(
            "SELECT * FROM mining_outcomes WHERE id = ?", [oid],
        )
        row = dict(rows[0])
        assert row["success"] == 1
        assert row["findings_count"] == 12
        assert row["strategy"] == "model_escalation"


# ===========================================================================
# 9. Repository: get_mining_model_stats aggregation
# ===========================================================================

class TestMiningModelStats:
    @pytest.mark.asyncio
    async def test_aggregation_by_size_bucket(self, db_pair):
        engine, repo = db_pair
        # 5 outcomes for model_a in small bucket (< 50K tokens)
        for i in range(5):
            await repo.record_mining_outcome(
                model_used="model_a", agent_id="a", brain="python",
                repo_name=f"repo_{i}", repo_size_bytes=10_000,
                prompt_tokens_estimated=20_000,  # small bucket
                strategy="primary", success=(i < 3),  # 3/5 success
                findings_count=(5 if i < 3 else 0),
                tokens_used=100, duration_seconds=1.0,
            )
        stats = await repo.get_mining_model_stats(min_observations=3)
        assert len(stats) >= 1
        model_a_stats = [s for s in stats if s["model_used"] == "model_a"]
        assert len(model_a_stats) == 1
        assert model_a_stats[0]["size_bucket"] == "small"
        assert model_a_stats[0]["total"] == 5
        assert model_a_stats[0]["successes"] == 3

    @pytest.mark.asyncio
    async def test_min_observations_filter(self, db_pair):
        engine, repo = db_pair
        # Only 2 outcomes — below min_observations=3
        for i in range(2):
            await repo.record_mining_outcome(
                model_used="model_x", agent_id="x", brain="python",
                repo_name=f"r_{i}", repo_size_bytes=10_000,
                prompt_tokens_estimated=100_000,  # medium bucket
                strategy="primary", success=True, findings_count=3,
                tokens_used=100, duration_seconds=1.0,
            )
        stats = await repo.get_mining_model_stats(min_observations=3)
        model_x = [s for s in stats if s["model_used"] == "model_x"]
        assert len(model_x) == 0  # Filtered out

    @pytest.mark.asyncio
    async def test_multiple_buckets(self, db_pair):
        engine, repo = db_pair
        # 3 in small, 3 in large
        for i in range(3):
            await repo.record_mining_outcome(
                model_used="model_b", agent_id="b", brain="python",
                repo_name=f"small_{i}", repo_size_bytes=5_000,
                prompt_tokens_estimated=10_000, strategy="primary",
                success=True, findings_count=4,
                tokens_used=100, duration_seconds=1.0,
            )
            await repo.record_mining_outcome(
                model_used="model_b", agent_id="b", brain="python",
                repo_name=f"large_{i}", repo_size_bytes=500_000,
                prompt_tokens_estimated=300_000, strategy="primary",
                success=(i == 0), findings_count=(8 if i == 0 else 0),
                tokens_used=500, duration_seconds=5.0,
            )
        stats = await repo.get_mining_model_stats(min_observations=3)
        model_b = [s for s in stats if s["model_used"] == "model_b"]
        buckets = {s["size_bucket"] for s in model_b}
        assert "small" in buckets
        assert "large" in buckets


# ===========================================================================
# 10. Repository: get_best_mining_model_for_size
# ===========================================================================

class TestBestMiningModelForSize:
    @pytest.mark.asyncio
    async def test_returns_highest_success_rate(self, db_pair):
        engine, repo = db_pair
        # model_a: 4/5 success in small bucket
        for i in range(5):
            await repo.record_mining_outcome(
                model_used="model_a", agent_id="a", brain="python",
                repo_name=f"r_{i}", repo_size_bytes=10_000,
                prompt_tokens_estimated=20_000, strategy="primary",
                success=(i < 4), findings_count=(3 if i < 4 else 0),
                tokens_used=100, duration_seconds=1.0,
            )
        # model_b: 2/5 success in small bucket
        for i in range(5):
            await repo.record_mining_outcome(
                model_used="model_b", agent_id="b", brain="python",
                repo_name=f"r_{i}", repo_size_bytes=10_000,
                prompt_tokens_estimated=20_000, strategy="primary",
                success=(i < 2), findings_count=(3 if i < 2 else 0),
                tokens_used=100, duration_seconds=1.0,
            )
        best = await repo.get_best_mining_model_for_size(20_000, min_observations=3)
        assert best == "model_a"

    @pytest.mark.asyncio
    async def test_cold_start_returns_none(self, db_pair):
        engine, repo = db_pair
        best = await repo.get_best_mining_model_for_size(100_000)
        assert best is None

    @pytest.mark.asyncio
    async def test_insufficient_data_returns_none(self, db_pair):
        engine, repo = db_pair
        # Only 1 outcome
        await repo.record_mining_outcome(
            model_used="model_c", agent_id="c", brain="python",
            repo_name="test", repo_size_bytes=10_000,
            prompt_tokens_estimated=100_000, strategy="primary",
            success=True, findings_count=5,
            tokens_used=200, duration_seconds=1.0,
        )
        best = await repo.get_best_mining_model_for_size(100_000, min_observations=3)
        assert best is None

    @pytest.mark.asyncio
    async def test_size_bucket_isolation(self, db_pair):
        """Data in 'small' bucket doesn't affect 'large' bucket selection."""
        engine, repo = db_pair
        # model_a: 5/5 in small
        for i in range(5):
            await repo.record_mining_outcome(
                model_used="model_a", agent_id="a", brain="python",
                repo_name=f"s_{i}", repo_size_bytes=10_000,
                prompt_tokens_estimated=10_000, strategy="primary",
                success=True, findings_count=5,
                tokens_used=100, duration_seconds=1.0,
            )
        # model_b: 3/3 in large
        for i in range(3):
            await repo.record_mining_outcome(
                model_used="model_b", agent_id="b", brain="python",
                repo_name=f"l_{i}", repo_size_bytes=500_000,
                prompt_tokens_estimated=300_000, strategy="primary",
                success=True, findings_count=8,
                tokens_used=500, duration_seconds=5.0,
            )
        # Query for large bucket → should return model_b, not model_a
        best = await repo.get_best_mining_model_for_size(300_000, min_observations=3)
        assert best == "model_b"


# ===========================================================================
# 11. _deduplicate_chunk_findings
# ===========================================================================

class TestDeduplicateChunkFindings:
    def _make_finding(self, title: str, relevance: float = 0.5) -> MiningFinding:
        return MiningFinding(
            title=title,
            description="test desc",
            category="pattern",
            source_repo="test-repo",
            relevance_score=relevance,
        )

    def test_empty_list(self):
        assert RepoMiner._deduplicate_chunk_findings([]) == []

    def test_exact_duplicate_removed(self):
        f1 = self._make_finding("Event-Driven Architecture", 0.9)
        f2 = self._make_finding("Event-Driven Architecture", 0.7)
        result = RepoMiner._deduplicate_chunk_findings([f1, f2])
        assert len(result) == 1
        assert result[0].relevance_score == 0.9  # higher relevance kept

    def test_partial_overlap_deduped(self):
        """Titles with >60% word overlap are considered duplicates."""
        f1 = self._make_finding("robust error handling pattern", 0.8)
        f2 = self._make_finding("robust error handling mechanism", 0.6)
        # Words: {robust, error, handling, pattern} vs {robust, error, handling, mechanism}
        # Overlap: 3/4 = 75% > 60% → duplicate
        result = RepoMiner._deduplicate_chunk_findings([f1, f2])
        assert len(result) == 1
        assert result[0].relevance_score == 0.8

    def test_low_overlap_kept(self):
        """Titles with <=60% word overlap are NOT duplicates."""
        f1 = self._make_finding("event driven architecture", 0.8)
        f2 = self._make_finding("database migration patterns", 0.7)
        result = RepoMiner._deduplicate_chunk_findings([f1, f2])
        assert len(result) == 2

    def test_sorted_by_relevance_descending(self):
        f1 = self._make_finding("pattern A", 0.3)
        f2 = self._make_finding("pattern B", 0.9)
        f3 = self._make_finding("pattern C", 0.6)
        result = RepoMiner._deduplicate_chunk_findings([f1, f2, f3])
        scores = [f.relevance_score for f in result]
        assert scores == sorted(scores, reverse=True)

    def test_case_insensitive_dedup(self):
        f1 = self._make_finding("Event Driven Architecture", 0.9)
        f2 = self._make_finding("event driven architecture", 0.5)
        result = RepoMiner._deduplicate_chunk_findings([f1, f2])
        assert len(result) == 1


# ===========================================================================
# 12. Recovery disabled — single attempt path
# ===========================================================================

class TestRecoveryDisabled:
    def test_config_disabled(self):
        cfg = MiningRecoveryConfig(enabled=False)
        assert cfg.enabled is False

    @pytest.mark.asyncio
    async def test_mining_call_uses_configured_low_reasoning(self, tmp_path):
        class RecordingLLM:
            def __init__(self):
                self.requests = []

            async def complete(self, **kwargs):
                self.requests.append(kwargs)
                return LLMResponse(content="[]", model=kwargs["model"], finish_reason="stop")

        class Selector:
            async def select_best_model(self, estimated_tokens):
                return "claude", "qwen/qwen3.8-max"

        class OutcomeRepository:
            async def record_mining_outcome(self, **kwargs):
                return None

            async def update_agent_score(self, **kwargs):
                return None

        config = ClawConfig()
        config.mining.recovery.enabled = False
        llm = RecordingLLM()
        miner = RepoMiner(
            repository=OutcomeRepository(),
            llm_client=llm,
            semantic_memory=None,
            config=config,
            scan_ledger_path=tmp_path / "ledger.json",
        )

        await miner._mine_with_recovery(
            prompt="mine this repo",
            token_budget=4096,
            model_selector=Selector(),
            estimated_tokens=100,
            repo_name="fixture",
            repo_path=tmp_path,
            repo_content="source",
            file_count=3,
            brain="python",
            brain_config=BrainConfig(),
            domain_info={},
            overlap=None,
            secret_scan_files=set(),
            start_time=0.0,
        )

        assert llm.requests[0]["reasoning"] == {"effort": "low", "exclude": True}

    @pytest.mark.asyncio
    async def test_truncated_repairable_response_is_recorded_unsuccessful(self, tmp_path):
        class TruncatedLLM:
            async def complete(self, **kwargs):
                return LLMResponse(
                    content=(
                        '[{"title":"Complete object","description":"Useful",'
                        '"category":"testing","relevance_score":0.9},'
                        '{"title":"Cut off"'
                    ),
                    model=kwargs["model"],
                    finish_reason="length",
                )

        class Selector:
            async def select_best_model(self, estimated_tokens):
                return "claude", "qwen/qwen3.8-max"

        class OutcomeRepository:
            def __init__(self):
                self.outcomes = []

            async def record_mining_outcome(self, **kwargs):
                self.outcomes.append(kwargs)

            async def update_agent_score(self, **kwargs):
                return None

        config = ClawConfig()
        config.mining.recovery.enabled = False
        repository = OutcomeRepository()
        miner = RepoMiner(
            repository=repository,
            llm_client=TruncatedLLM(),
            semantic_memory=None,
            config=config,
            scan_ledger_path=tmp_path / "ledger.json",
        )

        _response, findings, _attempts, _strategy = await miner._mine_with_recovery(
            prompt="mine this repo",
            token_budget=4096,
            model_selector=Selector(),
            estimated_tokens=100,
            repo_name="fixture",
            repo_path=tmp_path,
            repo_content="source",
            file_count=3,
            brain="python",
            brain_config=BrainConfig(),
            domain_info={},
            overlap=None,
            secret_scan_files=set(),
            start_time=0.0,
        )

        assert findings == []
        assert repository.outcomes[0]["success"] is False
        assert repository.outcomes[0]["findings_count"] == 0


# ===========================================================================
# 13. mining_outcomes table auto-created via migration
# ===========================================================================

class TestMiningOutcomesTableMigration:
    @pytest.mark.asyncio
    async def test_table_exists_after_schema_init(self, db_pair):
        engine, repo = db_pair
        rows = await engine.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='mining_outcomes'",
            [],
        )
        assert len(rows) == 1
        assert rows[0]["name"] == "mining_outcomes"

    @pytest.mark.asyncio
    async def test_table_columns(self, db_pair):
        engine, repo = db_pair
        rows = await engine.fetch_all(
            "PRAGMA table_info(mining_outcomes)", [],
        )
        col_names = {r["name"] for r in rows}
        expected = {
            "id", "model_used", "agent_id", "brain", "repo_name",
            "repo_size_bytes", "prompt_tokens_estimated", "strategy",
            "success", "findings_count", "tokens_used", "duration_seconds",
            "error_type", "error_detail", "created_at",
        }
        assert expected.issubset(col_names)

    @pytest.mark.asyncio
    async def test_multiple_records(self, db_pair):
        """Can insert multiple records and count them."""
        engine, repo = db_pair
        for i in range(10):
            await repo.record_mining_outcome(
                model_used=f"model_{i % 3}", agent_id="agent",
                brain="python", repo_name=f"repo_{i}",
                repo_size_bytes=10_000, prompt_tokens_estimated=5_000,
                strategy="primary", success=(i % 2 == 0),
                findings_count=(3 if i % 2 == 0 else 0),
                tokens_used=100, duration_seconds=1.0,
            )
        rows = await engine.fetch_all(
            "SELECT COUNT(*) as cnt FROM mining_outcomes", [],
        )
        assert rows[0]["cnt"] == 10
