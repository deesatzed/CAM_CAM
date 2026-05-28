"""Component factory and dependency injection for CLAW.

ClawFactory.create() builds the full dependency graph and returns
a ClawContext dataclass with all wired components.

Sub-factory helpers group related components:
  - _build_search_stack:   Repository, PRISM, HybridSearch, SemanticMemory, Governance
  - _build_cag_stack:      CAGRetriever, corpus injection, KV cache, token budget
  - _build_feedback_stack: ErrorKB, PromptEvolver, PatternLearner, Miner, SelfConsumer, Assimilation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple, Optional

from claw.core.config import ClawConfig, load_config
from claw.core.models import AgentMode
from claw.db.engine import DatabaseEngine
from claw.db.embeddings import EmbeddingEngine
from claw.db.repository import Repository
from claw.llm.client import LLMClient
from claw.llm.token_tracker import TokenTracker
from claw.security.policy import AutonomyLevel, SecurityPolicy
from claw.agents.interface import AgentInterface

logger = logging.getLogger("claw.factory")


# ---------------------------------------------------------------------------
# Sub-factory return types
# ---------------------------------------------------------------------------


class SearchComponents(NamedTuple):
    """Components for search and retrieval."""
    repository: Repository
    prism_engine: Any  # PrismEngine
    hybrid_search: Any  # HybridSearch
    semantic_memory: Any  # SemanticMemory
    governance: Any  # MemoryGovernor


class CAGComponents(NamedTuple):
    """Components for Cache-Augmented Generation."""
    cag_retriever: Any  # CAGRetriever | None
    cag_loaded: bool
    token_budget: int


class FeedbackComponents(NamedTuple):
    """Components for the feedback / evolution loop."""
    error_kb: Any  # ErrorKB
    prompt_evolver: Any  # PromptEvolver
    pattern_learner: Any  # PatternLearner
    miner: Any  # RepoMiner
    self_consumer: Any  # SelfConsumer
    assimilation_engine: Any  # CapabilityAssimilationEngine


# ---------------------------------------------------------------------------
# Main context dataclass (public API — unchanged)
# ---------------------------------------------------------------------------


@dataclass
class ClawContext:
    """All wired components for a CLAW session."""
    config: ClawConfig
    engine: DatabaseEngine
    repository: Repository
    embeddings: EmbeddingEngine
    llm_client: LLMClient
    token_tracker: TokenTracker
    security: SecurityPolicy
    agents: dict[str, AgentInterface] = field(default_factory=dict)
    prism_engine: Any = None
    gap_analyzer: Any = None  # GapAnalyzer — coverage matrix, gap scoring
    dispatcher: Any = None
    verifier: Any = None
    budget_enforcer: Any = None
    degradation_manager: Any = None
    health_monitor: Any = None
    error_kb: Any = None
    semantic_memory: Any = None
    prompt_evolver: Any = None
    pattern_learner: Any = None
    miner: Any = None
    governance: Any = None
    self_consumer: Any = None
    assimilation_engine: Any = None
    mcp_server: Any = None  # ClawMCPServer — exposed via MCP protocol for external agents
    ganglion_pool: Any = None  # GanglionRepositoryPool — Path C Fix 2 write-back for federation outcomes

    async def close(self) -> None:
        """Cleanly shut down all components."""
        # Close ganglion pool (releases sibling DB engines)
        if self.ganglion_pool is not None:
            try:
                await self.ganglion_pool.close_all()
            except Exception as e:
                logger.debug("GanglionRepositoryPool close error (non-fatal): %s", e)

        # Close embedding engine (releases Gemini httpx transport → prevents CLOSE_WAIT)
        try:
            self.embeddings.close()
        except Exception as e:
            logger.debug("EmbeddingEngine close error (non-fatal): %s", e)

        # Close agent backends (releases aiohttp/httpx sessions)
        for name, agent in self.agents.items():
            try:
                close_fn = getattr(agent, "close", None)
                if close_fn is not None:
                    import asyncio
                    result = close_fn()
                    if asyncio.iscoroutine(result):
                        await result
            except Exception as e:
                logger.debug("Agent '%s' close error (non-fatal): %s", name, e)

        # Close ganglion pool before primary engine so any write-back
        # pending on a ganglion finishes cleanly.
        if self.ganglion_pool is not None:
            try:
                await self.ganglion_pool.close_all()
            except Exception as e:
                logger.debug("GanglionRepositoryPool close error (non-fatal): %s", e)

        await self.llm_client.close()
        await self.engine.close()
        logger.info("ClawContext closed")


# ---------------------------------------------------------------------------
# Sub-factory helpers
# ---------------------------------------------------------------------------


def _build_search_stack(
    config: ClawConfig,
    engine: DatabaseEngine,
    embeddings: EmbeddingEngine,
) -> SearchComponents:
    """Build the search / retrieval layer.

    Creates: Repository, PrismEngine, MemoryGovernor, HybridSearch,
    SemanticMemory — all wired together.
    """
    repository = Repository(engine)

    # PRISM multi-scale embeddings
    from claw.embeddings.prism import PrismEngine
    prism_engine = PrismEngine(embedding_engine=embeddings)

    # Memory Governance
    from claw.memory.governance import MemoryGovernor
    governance = MemoryGovernor(
        repository=repository,
        config=config.governance,
        claw_config=config,
    )

    # HybridSearch
    from claw.memory.hybrid_search import HybridSearch
    hybrid_search = HybridSearch(
        repository=repository,
        embedding_engine=embeddings,
        prism_engine=prism_engine,
        novelty_retrieval_boost=config.assimilation.novelty_retrieval_boost,
        potential_retrieval_boost=config.assimilation.potential_retrieval_boost,
        deep_conf_config=config.deep_conf,
    )

    # Semantic Memory
    from claw.memory.semantic import SemanticMemory
    semantic_memory = SemanticMemory(
        repository=repository,
        embedding_engine=embeddings,
        hybrid_search=hybrid_search,
        prism_engine=prism_engine,
        governance=governance,
    )

    return SearchComponents(
        repository=repository,
        prism_engine=prism_engine,
        hybrid_search=hybrid_search,
        semantic_memory=semantic_memory,
        governance=governance,
    )


async def _build_cag_stack(
    config: ClawConfig,
    agents: dict[str, AgentInterface],
) -> CAGComponents:
    """Build the CAG (Cache-Augmented Generation) layer.

    Loads the CAG corpus (if enabled), injects it into agents,
    computes token budget, and optionally sets up the KV cache manager
    for local agents.
    """
    cag_loaded = False
    cag_retriever = None
    token_budget = 100_000

    if config.cag.enabled:
        from claw.memory.cag_retriever import CAGRetriever
        cag_retriever = CAGRetriever(config.cag)
        ganglion = (
            config.instances.instance_name
            if hasattr(config, "instances")
            else "general"
        )
        cag_loaded = await cag_retriever.load_cache(ganglion)
        if cag_loaded:
            corpus = cag_retriever.get_corpus(ganglion)
            budget = config.cag.knowledge_budget_chars
            for agent in agents.values():
                agent.set_cag_corpus(corpus, knowledge_budget_chars=budget)
            logger.info(
                "CAG corpus loaded into %d agents (budget=%d chars)",
                len(agents), budget,
            )

    # Token budget — derive from local model ctx_size or CAG config
    # Priority: local agent config ctx_size (if a "local" agent is enabled)
    #           > cag.token_budget_max (when CAG is enabled)
    #           > default 100_000
    local_agent_cfg = config.agents.get("local")
    if local_agent_cfg and local_agent_cfg.enabled and local_agent_cfg.mode == "local":
        token_budget = config.cag.token_budget_max
    elif config.cag.enabled:
        token_budget = config.cag.token_budget_max
    else:
        token_budget = 100_000

    for agent in agents.values():
        agent.set_token_budget(token_budget)

    if token_budget != 100_000:
        logger.info(
            "Token budget set to %d for %d agents",
            token_budget, len(agents),
        )

    # KV cache manager — enable prefix caching for local agents
    # when CAG is loaded and a local agent is configured.
    # Tier 1: TurboQuant (turboq) — ~4.9x compression, near-lossless
    # Tier 2: Ollama 0.19 MLX — 2x (q8_0) or 4x (q4_0) compression
    # Both tiers use the same stable system message prefix strategy.
    if config.cag.enabled and local_agent_cfg and local_agent_cfg.enabled:
        from claw.memory.kv_cache_manager import KVCacheManager
        local_llm_cfg = config.local_llm if hasattr(config, "local_llm") else None
        keep_alive = local_llm_cfg.keep_alive if local_llm_cfg else -1
        kv_quant = local_llm_cfg.kv_cache_quantization if local_llm_cfg else "q8_0"
        provider = local_llm_cfg.provider if local_llm_cfg else "ollama"
        kv_mgr = KVCacheManager(
            keep_alive=keep_alive,
            kv_cache_quantization=kv_quant,
            provider=provider,
        )

        # Build the stable system message from the CAG corpus
        corpus_for_kv = ""
        if cag_loaded and cag_retriever is not None:
            ganglion = (
                config.instances.instance_name
                if hasattr(config, "instances")
                else "general"
            )
            corpus_for_kv = cag_retriever.get_corpus(ganglion)
        if corpus_for_kv:
            # Build brain topology for KV cache system message
            _topo_text = ""
            if hasattr(config, "instances") and config.instances.enabled:
                try:
                    from claw.community.manifest import BrainTopology as _BT
                    _pdb = str(Path(config.database.db_path).resolve())
                    _topo = _BT(config.instances, primary_db_path=_pdb)
                    _topo.load()
                    _topo_text = _topo.build_summary_text()
                except Exception:
                    pass
            kv_mgr.build_system_message(corpus_for_kv, config.cag.knowledge_budget_chars, brain_topology=_topo_text)
            for agent in agents.values():
                agent.set_kv_cache_manager(kv_mgr)
            logger.info(
                "KV cache manager enabled: provider=%s, quant=%s (%.1fx), "
                "keep_alive=%d, system_msg=%d chars",
                provider, kv_quant, kv_mgr.compression_ratio,
                keep_alive, len(kv_mgr.system_message),
            )

    return CAGComponents(
        cag_retriever=cag_retriever,
        cag_loaded=cag_loaded,
        token_budget=token_budget,
    )


def _build_feedback_stack(
    config: ClawConfig,
    repository: Repository,
    llm_client: LLMClient,
    semantic_memory: Any,
    governance: Any,
    error_kb: Any,
) -> FeedbackComponents:
    """Build the feedback / evolution layer.

    Creates: PromptEvolver, PatternLearner, RepoMiner, SelfConsumer,
    CapabilityAssimilationEngine — all wired together.  Assimilation is
    cross-wired into miner and self_consumer before returning.
    """
    # Prompt Evolver
    from claw.evolution.prompt_evolver import PromptEvolver
    prompt_evolver = PromptEvolver(
        repository=repository,
        semantic_memory=semantic_memory,
        error_kb=error_kb,
        ab_test_kappa=config.evolution.ab_test_kappa,
    )

    # Pattern Learner
    from claw.evolution.pattern_learner import PatternLearner
    pattern_learner = PatternLearner(
        repository=repository,
        semantic_memory=semantic_memory,
    )

    # Repo Miner
    from claw.miner import RepoMiner
    miner = RepoMiner(
        repository=repository,
        llm_client=llm_client,
        semantic_memory=semantic_memory,
        config=config,
        governance=governance,
    )

    # Self-Consumer
    from claw.self_consumer import SelfConsumer
    self_consumer = SelfConsumer(
        repository=repository,
        llm_client=llm_client,
        semantic_memory=semantic_memory,
        config=config,
        governance_config=config.governance,
    )

    # Capability Assimilation Engine
    from claw.evolution.assimilation import CapabilityAssimilationEngine
    assimilation_engine = CapabilityAssimilationEngine(
        repository=repository,
        llm_client=llm_client,
        config=config,
    )

    # Wire assimilation into miner and self-consumer
    miner.assimilation_engine = assimilation_engine
    self_consumer.assimilation_engine = assimilation_engine

    return FeedbackComponents(
        error_kb=error_kb,
        prompt_evolver=prompt_evolver,
        pattern_learner=pattern_learner,
        miner=miner,
        self_consumer=self_consumer,
        assimilation_engine=assimilation_engine,
    )


# ---------------------------------------------------------------------------
# Main factory (public API — unchanged)
# ---------------------------------------------------------------------------


class ClawFactory:
    """Builds the complete CLAW dependency graph."""

    @staticmethod
    async def create(
        config_path: Optional[Path] = None,
        workspace_dir: Optional[Path] = None,
    ) -> ClawContext:
        """Create a fully wired ClawContext.

        Args:
            config_path: Path to claw.toml. Defaults to ./claw.toml.
            workspace_dir: Working directory for agent operations.
        """
        config = load_config(config_path)
        active_camseq_flags = [
            name
            for name, enabled in config.feature_flags.model_dump().items()
            if enabled
        ]
        if active_camseq_flags:
            logger.info(
                "CAM-SEQ feature flags active: %s",
                ", ".join(sorted(active_camseq_flags)),
            )

        # ── Infrastructure ─────────────────────────────────────────
        engine = DatabaseEngine(config.database)
        await engine.connect()
        await engine.apply_migrations()
        await engine.initialize_schema()

        embeddings = EmbeddingEngine(config.embeddings)

        # Seed knowledge — auto-import on first run (after schema + embeddings)
        # Kept in the main factory per design: it touches both engine and
        # embeddings before search/repo layers exist.
        try:
            from claw.community.seeder import run_seed
            seed_summary = await run_seed(
                engine=engine,
                embedding_engine=embeddings,
                config=config,
            )
            if seed_summary.get("imported", 0) > 0:
                logger.info(
                    "Seed knowledge loaded: %d methodologies imported",
                    seed_summary["imported"],
                )
        except Exception as e:
            logger.warning("Seed knowledge loading failed (non-fatal): %s", e)

        # ── Search / Retrieval layer ───────────────────────────────
        search = _build_search_stack(config, engine, embeddings)

        # ── LLM client + token tracker ─────────────────────────────
        llm_client = LLMClient(config.llm)

        token_tracker = TokenTracker(
            repository=search.repository,
            jsonl_path=config.token_tracking.jsonl_path if config.token_tracking.enabled else None,
            cost_per_1k_input=config.token_tracking.cost_per_1k_input,
            cost_per_1k_output=config.token_tracking.cost_per_1k_output,
        )

        # ── Security ───────────────────────────────────────────────
        ws = workspace_dir or Path(".").resolve()
        autonomy = AutonomyLevel.SUPERVISED
        sec_cfg = config.security
        if sec_cfg.autonomy_level.upper() == "FULL":
            autonomy = AutonomyLevel.FULL
        elif sec_cfg.autonomy_level.upper() == "READ_ONLY":
            autonomy = AutonomyLevel.READ_ONLY

        security = SecurityPolicy(
            autonomy=autonomy,
            workspace_dir=ws,
            allowed_commands=sec_cfg.allowed_commands,
            forbidden_paths=sec_cfg.forbidden_paths,
            max_actions_per_hour=sec_cfg.rate_limit_per_hour,
            safe_env_vars=sec_cfg.safe_env_vars,
        )

        # ── Agents ─────────────────────────────────────────────────
        agents: dict[str, AgentInterface] = {}
        # SDK fallback model chain from [llm] config
        sdk_fallback_models = config.llm.fallback_models or []

        for agent_name, agent_cfg in config.agents.items():
            if not agent_cfg.enabled:
                continue
            agent = _create_agent(agent_name, agent_cfg, workspace_dir=str(ws))
            if agent:
                agent._max_concurrent = getattr(agent_cfg, "max_concurrent", 2)
                if sdk_fallback_models:
                    agent.set_fallback_models(sdk_fallback_models)
                agents[agent_name] = agent

        # ── CAG layer (corpus, budget, KV cache) ──────────────────
        cag = await _build_cag_stack(config, agents)

        # ── Brain topology awareness ────────────────────────────────
        if hasattr(config, "instances") and config.instances.enabled:
            try:
                from claw.community.manifest import BrainTopology
                primary_db = str(Path(config.database.db_path).resolve())
                topo = BrainTopology(config.instances, primary_db_path=primary_db)
                topo.load()
                topology_text = topo.build_summary_text()
                if topology_text:
                    for agent in agents.values():
                        agent.set_brain_topology(topology_text)
                    logger.info(
                        "Brain topology injected into %d agents: %d brains, %d total methodologies",
                        len(agents), len(topo.brain_names), topo.total_methodologies,
                    )
            except Exception as e:
                logger.warning("Brain topology injection failed (non-fatal): %s", e)

        # ── Dispatcher (with optional Kelly sizer) ─────────────────
        from claw.dispatcher import Dispatcher
        kelly_sizer = None
        if config.kelly.enabled:
            from claw.evolution.kelly import BayesianKellySizer
            kelly_sizer = BayesianKellySizer(
                kappa=config.kelly.kappa,
                f_max=config.kelly.f_max,
                min_exploration_floor=config.kelly.min_exploration_floor,
                payoff_default=config.kelly.payoff_default,
                prior_alpha=config.kelly.prior_alpha,
                prior_beta=config.kelly.prior_beta,
                local_quality_multiplier=config.kelly.local_quality_multiplier,
            )
            logger.info("Kelly sizer enabled: kappa=%.1f, f_max=%.2f", config.kelly.kappa, config.kelly.f_max)
        dispatcher = Dispatcher(
            agents=agents,
            exploration_rate=config.orchestrator.exploration_rate,
            repository=search.repository,
            kelly_sizer=kelly_sizer,
        )

        # ── Verifier ──────────────────────────────────────────────
        # The corpus uses hash-embedding-384 for fast retrieval, but the verifier's
        # drift alignment check requires real semantic embeddings. Use the default
        # all-MiniLM-L6-v2 model (no required_model constraint) for the verifier.
        from claw.core.config import EmbeddingsConfig as _EmbeddingsConfig
        _verifier_embed_cfg = _EmbeddingsConfig()
        verifier_embeddings = EmbeddingEngine(_verifier_embed_cfg)
        from claw.verifier import Verifier
        sentinel_cfg = config.sentinel if hasattr(config, "sentinel") else None
        verifier = Verifier(
            embedding_engine=verifier_embeddings,
            banned_dependencies=getattr(sentinel_cfg, "banned_dependencies", []) if sentinel_cfg else [],
            drift_threshold=getattr(sentinel_cfg, "drift_threshold", 0.40) if sentinel_cfg else 0.40,
            llm_client=llm_client,
            min_test_count=getattr(sentinel_cfg, "min_test_count", 0) if sentinel_cfg else 0,
            sentinel_config=sentinel_cfg,
        )

        # ── Health / Budget / Degradation ──────────────────────────
        from claw.orchestrator.health_monitor import HealthMonitor
        health_monitor = HealthMonitor(
            repository=search.repository,
            config=config.orchestrator,
        )

        from claw.budget import BudgetEnforcer
        budget_enforcer = BudgetEnforcer(
            repository=search.repository,
            config=config,
        )

        from claw.degradation import DegradationManager
        degradation_manager = DegradationManager(
            health_monitor=health_monitor,
            dispatcher=dispatcher,
            all_agent_ids=list(agents.keys()) if agents else None,
        )

        # ── Error KB ──────────────────────────────────────────────
        from claw.memory.error_kb import ErrorKB
        error_kb = ErrorKB(repository=search.repository)

        # ── Feedback / Evolution layer ─────────────────────────────
        feedback = _build_feedback_stack(
            config=config,
            repository=search.repository,
            llm_client=llm_client,
            semantic_memory=search.semantic_memory,
            governance=search.governance,
            error_kb=error_kb,
        )

        # ── Startup governance sweep ───────────────────────────────
        if config.governance.sweep_on_startup:
            try:
                sweep_report = await search.governance.run_full_sweep()
                logger.info(
                    "Startup governance sweep: gc=%d, culled=%d",
                    sweep_report.dead_collected,
                    sweep_report.quota_culled,
                )
            except Exception as e:
                logger.warning("Startup governance sweep failed: %s", e)

        # ── MCP server (optional) ─────────────────────────────────
        mcp_srv = None
        if config.mcp.enabled:
            import os
            from claw.mcp_server import ClawMCPServer
            auth_token = os.environ.get(config.mcp.auth_token_env)
            mcp_srv = ClawMCPServer(
                repository=search.repository,
                semantic_memory=search.semantic_memory,
                verifier=verifier,
                dispatcher=dispatcher,
                auth_token=auth_token,
            )
            logger.info("MCP server created (transport=%s)", config.mcp.transport)

        # ── Gap Analyzer (optional) ────────────────────────────────
        gap_analyzer_inst = None
        if config.gap_analyzer.enabled and config.instances.enabled:
            try:
                from claw.community.gap_analyzer import GapAnalyzer
                primary_db = str(Path(config.database.db_path).resolve())
                gap_analyzer_inst = GapAnalyzer(
                    repository=search.repository,
                    instances_config=config.instances,
                    primary_db_path=primary_db,
                    gap_config=config.gap_analyzer,
                )
                logger.info("GapAnalyzer enabled: threshold=%d", config.gap_analyzer.sparse_cell_threshold)
            except Exception as e:
                logger.warning("GapAnalyzer creation failed (non-fatal): %s", e)

        # -- Ganglion repository pool (Path C Fix 2) ----------------
        # Federation returns methodologies from sibling ganglion DBs,
        # but outcomes need to be written back to the *source* ganglion
        # so those rows can mature organically.  The pool caches one
        # write-mode engine per ganglion for the lifetime of this ctx.
        ganglion_pool = None
        if config.instances.enabled:
            from claw.memory.ganglion_pool import GanglionRepositoryPool
            primary_db_abs = str(Path(config.database.db_path).resolve())
            ganglion_pool = GanglionRepositoryPool(primary_db_path=primary_db_abs)
            # Inject into SemanticMemory so record_outcome routes to correct DB
            if hasattr(search.semantic_memory, "set_ganglion_pool"):
                search.semantic_memory.set_ganglion_pool(ganglion_pool)
            logger.info("GanglionRepositoryPool created for federation write-back")

        # ── Assemble context ───────────────────────────────────────
        ctx = ClawContext(
            config=config,
            engine=engine,
            repository=search.repository,
            embeddings=embeddings,
            llm_client=llm_client,
            token_tracker=token_tracker,
            security=security,
            agents=agents,
            prism_engine=search.prism_engine,
            gap_analyzer=gap_analyzer_inst,
            dispatcher=dispatcher,
            verifier=verifier,
            budget_enforcer=budget_enforcer,
            degradation_manager=degradation_manager,
            health_monitor=health_monitor,
            error_kb=error_kb,
            semantic_memory=search.semantic_memory,
            prompt_evolver=feedback.prompt_evolver,
            pattern_learner=feedback.pattern_learner,
            miner=feedback.miner,
            governance=search.governance,
            self_consumer=feedback.self_consumer,
            assimilation_engine=feedback.assimilation_engine,
            mcp_server=mcp_srv,
            ganglion_pool=ganglion_pool,
        )

        # SemanticMemory needs a reference to the pool so record_outcome
        # can route ganglion writes.  We do this after ctx construction to
        # keep the existing _build_search_stack signature stable.
        if hasattr(search.semantic_memory, "set_ganglion_pool"):
            search.semantic_memory.set_ganglion_pool(ganglion_pool)

        agent_names = list(agents.keys()) if agents else ["none"]
        logger.info(
            "ClawContext created: db=%s, agents=[%s], evolution=[error_kb, semantic_memory, prompt_evolver, pattern_learner]",
            config.database.db_path,
            ", ".join(agent_names),
        )
        return ctx


# ---------------------------------------------------------------------------
# Agent creation (unchanged — used by tests via direct import)
# ---------------------------------------------------------------------------


def _create_agent(
    name: str,
    agent_cfg: Any,
    workspace_dir: Optional[str] = None,
) -> Optional[AgentInterface]:
    """Create a single agent by name."""
    import os

    mode = AgentMode(agent_cfg.mode)
    api_key = os.getenv(agent_cfg.api_key_env, "") if agent_cfg.api_key_env else ""

    if name == "claude":
        from claw.agents.claude import ClaudeCodeAgent
        return ClaudeCodeAgent(
            mode=mode,
            api_key=api_key,
            model=agent_cfg.model,
            timeout=agent_cfg.timeout,
            max_budget_usd=agent_cfg.max_budget_usd,
            workspace_dir=workspace_dir,
            max_tokens=agent_cfg.max_tokens,
        )

    if name == "codex":
        from claw.agents.codex import CodexAgent
        return CodexAgent(
            mode=mode,
            api_key=api_key,
            model=agent_cfg.model,
            timeout=agent_cfg.timeout,
            max_tokens=agent_cfg.max_tokens,
            workspace_dir=workspace_dir,
        )

    if name == "gemini":
        from claw.agents.gemini import GeminiAgent
        return GeminiAgent(
            mode=mode,
            api_key=api_key,
            model=agent_cfg.model,
            timeout=agent_cfg.timeout,
            workspace_dir=workspace_dir,
            max_tokens=agent_cfg.max_tokens,
        )

    if name == "grok":
        from claw.agents.grok import GrokAgent
        return GrokAgent(
            mode=mode,
            api_key=api_key,
            model=agent_cfg.model,
            timeout=agent_cfg.timeout,
            max_budget_usd=agent_cfg.max_budget_usd,
            workspace_dir=workspace_dir,
            max_tokens=agent_cfg.max_tokens,
        )

    if name == "local":
        from claw.agents.local_agent import LocalAgent
        return LocalAgent(
            model=agent_cfg.model,
            local_base_url=agent_cfg.local_base_url or "http://localhost:11434/v1",
            timeout=agent_cfg.timeout,
            max_tokens=agent_cfg.max_tokens,
            workspace_dir=workspace_dir,
        )

    logger.warning("Unknown agent name: '%s'", name)
    return None
