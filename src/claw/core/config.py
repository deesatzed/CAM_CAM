"""Configuration loader for CLAW.

Loads config from claw.toml (TOML format), with environment variable overrides.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import json
import toml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from claw.core.exceptions import ConfigError


# ---------------------------------------------------------------------------
# Config schema
# ---------------------------------------------------------------------------

class DatabaseConfig(BaseModel):
    db_path: str = "data/claw.db"


class LLMConfig(BaseModel):
    provider: str = "openrouter"
    base_url: str = "https://openrouter.ai/api/v1"
    default_temperature: float = 0.3
    default_max_tokens: int = 4096
    timeout: int = 120
    max_retries: int = 3
    backoff_base: float = 2.0
    backoff_cap: float = 60.0
    fallback_models: list[str] = Field(default_factory=list)
    model_failure_threshold: int = 2
    model_cooldown_seconds: int = 90


class EmbeddingsConfig(BaseModel):
    model: str = "all-MiniLM-L6-v2"
    dimension: int = 384
    api_key_env: str = "GOOGLE_API_KEY"
    task_type: Optional[str] = "RETRIEVAL_DOCUMENT"
    required_model: Optional[str] = None


class MemoryConfig(BaseModel):
    mmr_enabled: bool = True
    mmr_lambda: float = 0.7
    vector_weight: float = 0.6
    text_weight: float = 0.4
    attribution_embedding_enabled: bool = False
    attribution_embedding_weight: float = 0.6
    attribution_embedding_threshold: float = 0.35
    category_weights: dict[str, float] = Field(default_factory=dict)


class OrchestratorConfig(BaseModel):
    max_retries: int = 5
    council_trigger: int = 2
    max_council: int = 3
    max_tokens_per_task: int = 100_000
    exploration_rate: float = 0.10
    loop_guard_max_repeats: int = 2
    pipeline_adaptation_enabled: bool = True
    max_correction_attempts: int = 3
    auto_fix_enabled: bool = True


class SentinelConfig(BaseModel):
    llm_deep_check: bool = True
    drift_threshold: float = 0.40
    quality_score_threshold: float = 0.60
    min_test_count: int = 0
    auto_install_deps: bool = True
    auto_recovery_timeout: int = 120


class SecurityConfig(BaseModel):
    autonomy_level: str = "SUPERVISED"
    rate_limit_per_hour: int = 200
    allowed_commands: list[str] = Field(
        default_factory=lambda: [
            "git", "pytest", "python3", "pip", "npm", "npx",
            "cargo", "rustc", "go", "make", "ls", "find", "grep",
            "cat", "head", "tail", "wc", "diff", "ruff", "mypy",
        ]
    )
    forbidden_paths: list[str] = Field(
        default_factory=lambda: [
            "/etc", "/root", "/var", "/tmp",
            "/System", "/Library", "/Applications",
            "/usr/bin", "/usr/sbin",
        ]
    )
    safe_env_vars: list[str] = Field(
        default_factory=lambda: [
            "PATH", "HOME", "USER", "SHELL", "LANG", "LC_ALL",
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
            "GOOGLE_API_KEY", "XAI_API_KEY",
            "OPENROUTER_API_KEY",
        ]
    )
    # Pre-assimilation secret scanning
    secret_scan_enabled: bool = True
    secret_scan_fail_on_critical: bool = True
    secret_scan_timeout_seconds: int = 60
    secret_scan_no_verification: bool = True
    secret_scan_filter_in_serializer: bool = True


class TokenTrackingConfig(BaseModel):
    enabled: bool = True
    jsonl_path: str = "data/token_costs.jsonl"
    cost_per_1k_input: float = 0.003
    cost_per_1k_output: float = 0.015


class LocalLLMConfig(BaseModel):
    """Configuration for local LLM providers.

    Providers:
        ollama      — Ollama 0.19+, MLX on Apple Silicon, native q8_0/q4_0 KV cache (2-4x).
        turboq      — TurboQuant via llama-server-turboq (TheTom fork), turbo3 KV cache
                      (~4.9x compression, near-zero quality loss). Ollama-compatible API.
        mlx-server  — MLX-LM native server.
        atomic-chat — Atomic Chat with tauri-plugin-llamacpp (port 1337).
        llama-cpp   — Vanilla llama.cpp server.

    KV cache quantization tiers (kv_cache_quantization):
        f16     — Full precision, 1x (baseline).
        q8_0    — 8-bit, 2x compression (Ollama default, safe quality).
        q4_0    — 4-bit, 4x compression (Ollama, measurable quality loss).
        turbo3  — TurboQuant 3.25-bit, ~4.9x compression, near-zero quality loss.
        turbo4  — TurboQuant 4-bit variant, ~6x compression, near-zero quality loss.

    TurboQuant (turbo3) is the recommended tier for long-context CAG workloads
    on Apple Silicon. It provides 2.5x better compression than Ollama q8_0 with
    no measurable quality degradation.
    """
    provider: str = "ollama"  # ollama | turboq | mlx-server | atomic-chat | llama-cpp
    base_url: str = "http://localhost:11434/v1"
    model: str = ""
    timeout: int = 300
    ctx_size: int = 32768  # 64GB default; set 131072 for 128GB
    kv_cache_type: str = "f16"  # f16 | q4_0 | q8_0 (legacy, prefer kv_cache_quantization)
    keep_alive: int = -1  # -1 = never unload (keeps KV cache hot)
    kv_cache_quantization: str = "q8_0"  # f16 | q8_0 | q4_0 | turbo3 | turbo4
    turboq_binary: str = "llama-server-turboq"  # Path to TurboQuant server binary


class AgentConfig(BaseModel):
    """Per-agent configuration."""
    enabled: bool = False
    mode: str = "cli"  # cli, api, cloud, openrouter, local
    api_key_env: str = ""
    max_concurrent: int = 2
    timeout: int = 300
    model: Optional[str] = None  # User-set; never hardcoded
    max_budget_usd: float = 1.0
    local_base_url: Optional[str] = None  # Override base_url for local mode
    max_tokens: int = 16384  # Token limit for model responses
    context_window_tokens: int = 0  # Model's total context window. 0 = unknown.


class RoutingConfig(BaseModel):
    exploration_rate: float = 0.10
    score_decay_factor: float = 0.95
    min_samples_for_routing: int = 5
    static_priors: dict[str, str] = Field(default_factory=lambda: {
        "analysis": "claude",
        "documentation": "claude",
        "refactoring": "codex",
        "bulk_tests": "codex",
        "dependency_analysis": "gemini",
        "full_repo_comprehension": "gemini",
        "quick_fixes": "grok",
        "web_lookup": "grok",
    })


class KellyConfig(BaseModel):
    """Bayesian Kelly Criterion position-sizing for agent routing."""
    enabled: bool = False
    kappa: float = 10.0          # Robustness shrinkage (higher = more conservative)
    f_max: float = 0.40          # Hard cap on any single agent's fraction
    min_exploration_floor: float = 0.02  # Minimum sampling probability per agent
    payoff_default: float = 2.0  # Default payoff ratio when no cost data available
    prior_alpha: float = 1.0     # Beta prior alpha (uniform default)
    prior_beta: float = 1.0      # Beta prior beta (uniform default)
    local_quality_multiplier: float = 2.0  # Payoff multiplier for $0-cost local agents


class EvolutionConfig(BaseModel):
    ab_test_sample_size: int = 20
    mutation_rate: float = 0.1
    promotion_threshold: float = 0.6
    ab_test_kappa: float = 10.0  # Kelly kappa-shrinkage for adaptive A/B margin


class BrainConfig(BaseModel):
    """Per-language mining brain configuration.

    A brain is a mining lens: it defines the prompt template, serialization
    limits, and target ganglion for a specific programming language.  The
    miner's ``detect_repo_language()`` selects the brain; the brain's
    ``ganglion_name`` determines which ganglion DB stores the findings.
    """
    enabled: bool = True
    max_bytes: int = 921_600              # Serialization cap (default 900 KB)
    prompt: str = "repo-mine.md"          # Prompt template filename in prompts/
    priority_extensions: list[str] = []   # Extensions to prioritize in serialization
    extra_skip_dirs: list[str] = []       # Brain-specific dirs to skip
    ganglion_name: str = ""               # Target ganglion (empty → primary DB)


def _default_brains() -> dict[str, BrainConfig]:
    """Built-in brain configurations for supported language families."""
    return {
        "python": BrainConfig(
            max_bytes=921_600,
            prompt="repo-mine.md",
            ganglion_name="",  # primary DB
        ),
        "typescript": BrainConfig(
            max_bytes=1_536_000,  # 1500 KB — TS projects are larger
            prompt="repo-mine-typescript.md",
            priority_extensions=[".ts", ".tsx", ".js", ".jsx"],
            ganglion_name="typescript",
        ),
        "go": BrainConfig(
            max_bytes=1_228_800,  # 1200 KB
            prompt="repo-mine-go.md",
            priority_extensions=[".go"],
            ganglion_name="go",
        ),
        "rust": BrainConfig(
            max_bytes=1_228_800,  # 1200 KB
            prompt="repo-mine-rust.md",
            priority_extensions=[".rs"],
            ganglion_name="rust",
        ),
        "misc": BrainConfig(
            max_bytes=921_600,
            prompt="repo-mine-misc.md",
            ganglion_name="misc",
        ),
    }


class MiningRecoveryConfig(BaseModel):
    """Self-recovery configuration for mining LLM calls.

    When the LLM returns null/empty (e.g., context overflow), the miner
    tries escalation strategies instead of quitting:
      1. Model escalation — try models with larger context windows
      2. Content reduction — re-serialize at reduced max_bytes
      3. Chunk mining — split content, mine each chunk, merge findings
    """
    enabled: bool = True
    max_escalation_attempts: int = 3
    content_reduction_factor: float = 0.50
    max_chunks: int = 4
    escalation_order: list[str] = Field(
        default_factory=lambda: ["claude", "gemini", "grok"],
    )
    token_estimate_chars_per_token: float = 4.0
    min_context_headroom_pct: float = 0.20
    max_prompt_tokens: int = 80_000


class DomainBrainConfig(BaseModel):
    """Configuration for an application-domain ganglion (medical, finance, etc.)."""
    ganglion_name: str = ""
    keywords: list[str] = []
    min_cluster_size: int = 5  # Minimum repos to auto-provision a ganglion


class MiningConfig(BaseModel):
    """Mining and serialization configuration."""
    extra_code_extensions: list[str] = []  # e.g. [".cpp", ".rb", ".swift"]
    extra_skip_dirs: list[str] = []        # e.g. ["migrations", "vendor"]
    brains: dict[str, BrainConfig] = Field(default_factory=_default_brains)
    recovery: MiningRecoveryConfig = Field(default_factory=MiningRecoveryConfig)
    domain_brains: dict[str, DomainBrainConfig] = Field(default_factory=dict)
    assimilation_parallelism: int = 8  # concurrent assimilation tasks (max 16)


class GovernanceConfig(BaseModel):
    """Memory governance configuration."""
    max_methodologies: int = 5000  # 0 = unlimited; set higher as your instance grows
    quota_warning_pct: float = 0.80
    gc_dead_on_sweep: bool = True
    dedup_similarity_threshold: float = 0.88
    dedup_enabled: bool = True
    episodic_retention_days: int = 90
    sweep_interval_cycles: int = 10
    sweep_on_startup: bool = True
    self_consume_enabled: bool = True
    self_consume_min_tasks: int = 10
    self_consume_max_generation: int = 3
    self_consume_lookback: int = 20
    max_db_size_mb: int = 500
    mining_min_description_length: int = 20


class AssimilationConfig(BaseModel):
    """Capability assimilation configuration."""
    enabled: bool = True
    capability_llm_enabled: bool = True
    synergy_candidate_limit: int = 20
    synergy_score_threshold: float = 0.6
    auto_compose_threshold: float = 0.8
    max_compositions_per_cycle: int = 3
    io_compatibility_weight: float = 0.3
    domain_overlap_weight: float = 0.2
    embedding_similarity_weight: float = 0.3
    llm_analysis_weight: float = 0.2
    # Novelty scoring
    novelty_enabled: bool = True
    novelty_nearest_neighbor_k: int = 5
    novelty_nn_weight: float = 0.35
    novelty_domain_uniqueness_weight: float = 0.25
    novelty_type_rarity_weight: float = 0.15
    novelty_centroid_distance_weight: float = 0.25
    # Potential scoring
    potential_io_generality_weight: float = 0.30
    potential_composability_weight: float = 0.25
    potential_domain_breadth_weight: float = 0.20
    potential_standalone_weight: float = 0.10
    potential_llm_weight: float = 0.15
    potential_llm_threshold: float = 0.4
    # Lifecycle + retrieval
    novelty_lifecycle_protection_days: int = 90
    novelty_protection_threshold: float = 0.7
    novelty_retrieval_boost: float = 0.15
    potential_retrieval_boost: float = 0.10


class FleetConfig(BaseModel):
    max_concurrent_repos: int = 4
    enhancement_branch_prefix: str = "claw/enhancement"
    max_cost_per_repo_usd: float = 5.0
    max_cost_per_day_usd: float = 50.0


class PulseProfileConfig(BaseModel):
    """Mission profile for a PULSE instance."""
    name: str = "general"
    mission: str = ""
    domains: list[str] = Field(default_factory=list)
    novelty_bias: dict[str, float] = Field(default_factory=dict)


class HFMountConfig(BaseModel):
    """hf-mount adapter configuration."""
    enabled: bool = True
    binary_path: str = "~/.local/bin/hf-mount"
    mount_base: str = "data/hf_mounts"
    cache_size_bytes: int = 1_073_741_824  # 1GB per mount
    cache_dir: str = "/tmp/hf-mount-cache"
    hf_token_env: str = "HF_TOKEN"
    poll_interval_secs: int = 0  # disabled for mining (pin revision)
    mount_timeout_secs: int = 30
    fallback_to_download: bool = True


class FreshnessConfig(BaseModel):
    """Repo freshness monitor configuration."""
    check_interval_hours: int = 12
    significance_commit_threshold: int = 20
    significance_release_weight: float = 0.4
    significance_readme_weight: float = 0.2
    significance_size_delta_pct: int = 20
    significance_threshold: float = 0.4
    github_token_env: str = "GITHUB_TOKEN"
    max_repos_per_check: int = 50
    rate_limit_buffer: int = 10


class DeepConfConfig(BaseModel):
    """6-factor confidence scoring weights."""
    retrieval_weight: float = 0.25
    authority_weight: float = 0.20
    accuracy_weight: float = 0.20
    novelty_weight: float = 0.10
    provenance_weight: float = 0.10
    verification_weight: float = 0.15
    min_critical_threshold: float = 0.15


class CAGConfig(BaseModel):
    """Cache-Augmented Generation configuration."""
    enabled: bool = False
    cache_dir: str = "data/cag_caches"
    auto_rebuild_on_stale: bool = False
    max_methodologies_per_cache: int = 2000
    serialization_format: str = "structured_text"
    max_solution_chars: int = 2000
    knowledge_budget_chars: int = 16000
    token_budget_max: int = 100_000  # Max tokens for full context assembly
    context_pointer_threshold: int = 2000  # Solutions > this get pointer format; 0 = disabled
    shorthand_compression: bool = False  # Enable BART shorthand compression
    shorthand_max_solution_chars: int = 800  # Max chars per solution after compression


class PulseConfig(BaseModel):
    """CAM-PULSE: Perpetual Unified Learning Swarm Engine configuration."""
    enabled: bool = False
    poll_interval_minutes: int = 30
    max_scouts: int = 4
    novelty_threshold: float = 0.70
    max_cost_per_scan_usd: float = 0.50
    max_cost_per_day_usd: float = 10.0
    max_repos_per_scan: int = 20
    clone_workspace: str = "data/pulse_clones"
    auto_mine: bool = True
    auto_queue_enhance: bool = False
    enhance_novelty_threshold: float = 0.85
    self_improve_interval_hours: int = 24
    xai_model: str = ""  # User-set, never hardcoded
    xai_api_key_env: str = "XAI_API_KEY"
    keywords: list[str] = Field(default_factory=lambda: [
        "github.com new repo",
        "github.com just released open source",
        "github.com dropped today AI agent",
        "github.com framework new 2026",
    ])
    profile: PulseProfileConfig = Field(default_factory=PulseProfileConfig)
    hf_mount: HFMountConfig = Field(default_factory=HFMountConfig)
    freshness: FreshnessConfig = Field(default_factory=FreshnessConfig)


class SelfEnhanceConfig(BaseModel):
    """Self-enhancement pipeline configuration."""
    enabled: bool = False
    workspace_parent: str = ""  # Where to create enhanced copies; defaults to same volume as live
    max_backup_count: int = 3
    validation_test_timeout_seconds: int = 600
    require_user_confirmation: bool = True  # Require human approval before swap
    protected_files: list[str] = Field(default_factory=lambda: [
        "src/claw/verifier.py",
        "src/claw/core/factory.py",
        "src/claw/db/engine.py",
        "src/claw/db/schema.sql",
        "src/claw/core/config.py",
    ])
    # Trigger conditions — self-enhance when ANY of these thresholds are met
    min_new_methodologies: int = 10  # Trigger after N new methodologies since last enhance
    min_avg_novelty_score: float = 0.75  # Trigger when avg novelty of new methodologies exceeds this
    trigger_after_mine: bool = False  # Auto-assess trigger after cam mine
    trigger_after_pulse_ingest: bool = False  # Auto-assess trigger after cam pulse ingest
    cooldown_hours: int = 24  # Minimum hours between self-enhance runs
    max_enhance_tasks: int = 10  # Max enhancement tasks per run


class CommunityConfig(BaseModel):
    """Community knowledge sharing configuration."""
    hf_repo: str = "cam-community/knowledge-hub"
    hf_token_env: str = "HF_TOKEN"
    novelty_threshold: float = 0.70
    min_lifecycle_to_publish: str = "viable"
    auto_approve: bool = False
    max_import_per_session: int = 200
    max_publish_count: int = 500
    instance_id_file: str = "data/community_state.json"


class InstanceConfig(BaseModel):
    """Configuration for a single CAM Ganglion (sibling instance).

    CAM Terminology:
        - **CAM Brain**: The full federated system (all ganglia together).
        - **CAM Ganglion**: A specialized instance with its own claw.db and focus area.
        - **CAM Swarm**: The runtime coordination layer connecting ganglia.
    """
    name: str  # Ganglion name (e.g. "drive-ops", "quantum-physics")
    db_path: str  # Absolute path to this ganglion's claw.db
    description: str = ""  # Domain focus description
    manifest_path: str = ""  # Path to cached manifest JSON (auto-set if empty)


# Alias for clarity in the new terminology
GanglionConfig = InstanceConfig


class InstanceRegistryConfig(BaseModel):
    """CAM Swarm configuration — federation of CAM Ganglia.

    Each ganglion is a semi-autonomous CAM instance with its own claw.db,
    its own specialty, and its own learned knowledge.  Ganglia communicate
    via read-only FTS5 queries through brain manifests.  Together, all
    ganglia form the CAM Brain.

    CAM Terminology:
        - **CAM Brain**: The full federated system (all ganglia together).
        - **CAM Ganglion**: A specialized instance with its own claw.db.
        - **CAM Swarm**: The runtime coordination that connects them.
    """
    enabled: bool = False
    manifest_path: str = "data/brain_manifest.json"  # This ganglion's manifest
    instance_name: str = ""  # This ganglion's human-readable name
    instance_description: str = ""  # This ganglion's domain focus
    federation_confidence_threshold: float = 0.3  # Min local confidence to skip federation
    federation_relevance_threshold: float = 0.2  # Min manifest relevance to query sibling ganglion
    federation_max_results: int = 3  # Max results per sibling ganglion query
    siblings: list[InstanceConfig] = Field(default_factory=list)


# Alias for clarity in the new terminology
SwarmConfig = InstanceRegistryConfig


class MCPConfig(BaseModel):
    """MCP server configuration for exposing CLAW tools externally."""
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 3100
    transport: str = "stdio"  # "stdio" or "http"
    auth_token_env: str = "CLAW_MCP_AUTH_TOKEN"


class GapAnalyzerConfig(BaseModel):
    """Knowledge gap analysis configuration.

    Controls the coverage matrix computation, sparse cell detection,
    and repo prioritization for gap-filling mining runs.
    """
    enabled: bool = True
    sparse_cell_threshold: int = 3  # category x brain cells below this = sparse


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    json_mode: bool = False
    log_file: str = ""


class FeatureFlagsConfig(BaseModel):
    """Additive rollout controls for CAM-SEQ subsystems."""
    component_cards: bool = False
    application_packets: bool = False
    connectome_seq: bool = False
    critical_slot_policy: bool = False
    critical_slot_prewrite_block: bool = False
    a2a_packets: bool = False


class ClawConfig(BaseModel):
    """Top-level CLAW configuration."""
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    orchestrator: OrchestratorConfig = Field(default_factory=OrchestratorConfig)
    sentinel: SentinelConfig = Field(default_factory=SentinelConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    token_tracking: TokenTrackingConfig = Field(default_factory=TokenTrackingConfig)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    kelly: KellyConfig = Field(default_factory=KellyConfig)
    evolution: EvolutionConfig = Field(default_factory=EvolutionConfig)
    fleet: FleetConfig = Field(default_factory=FleetConfig)
    mining: MiningConfig = Field(default_factory=MiningConfig)
    governance: GovernanceConfig = Field(default_factory=GovernanceConfig)
    assimilation: AssimilationConfig = Field(default_factory=AssimilationConfig)
    pulse: PulseConfig = Field(default_factory=PulseConfig)
    deep_conf: DeepConfConfig = Field(default_factory=DeepConfConfig)
    cag: CAGConfig = Field(default_factory=CAGConfig)
    self_enhance: SelfEnhanceConfig = Field(default_factory=SelfEnhanceConfig)
    community: CommunityConfig = Field(default_factory=CommunityConfig)
    instances: InstanceRegistryConfig = Field(default_factory=InstanceRegistryConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    feature_flags: FeatureFlagsConfig = Field(default_factory=FeatureFlagsConfig)
    local_llm: LocalLLMConfig = Field(default_factory=LocalLLMConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    gap_analyzer: GapAnalyzerConfig = Field(default_factory=GapAnalyzerConfig)
    agents: dict[str, AgentConfig] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Prompt loader
# ---------------------------------------------------------------------------

class PromptLoader:
    """Loads prompt templates from prompts/ directory."""

    def __init__(self, prompts_dir: Optional[Path] = None):
        if prompts_dir is None:
            prompts_dir = Path(__file__).parent.parent.parent.parent / "prompts"
        self.prompts_dir = prompts_dir

    def load(self, name: str, default: str = "") -> str:
        path = self.prompts_dir / name
        if path.exists():
            return path.read_text().strip()
        return default


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_runtime_env(config_path: Path) -> None:
    """Load local .env files for CLI/runtime subprocess consistency.

    This keeps shell-exported values authoritative (`override=False`) while
    letting direct CLI subprocesses pick up keys from the repo-level `.env`.
    """
    candidates: list[Path] = []
    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        candidates.append(cwd_env)
    repo_env = config_path.parent / ".env"
    if repo_env.exists() and repo_env not in candidates:
        candidates.append(repo_env)

    for env_path in candidates:
        load_dotenv(env_path, override=False)


def _env_flag(name: str) -> Optional[bool]:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return None


def _resolve_evolution_champion_db(config_path: Path) -> Optional[str]:
    """Resolve the current champion DB pointer for opt-in downstream commands."""
    pointer_path = config_path.parent / "instances" / "evolution" / "current_champion.json"
    if not pointer_path.exists():
        return None
    try:
        data = json.loads(pointer_path.read_text())
    except Exception:
        return None
    db_path = data.get("db_path")
    if not db_path:
        return None
    path = Path(str(db_path))
    if not path.is_absolute():
        path = (config_path.parent / path).resolve()
    if not path.exists():
        return None
    return str(path)


def load_config(config_path: Optional[Path] = None) -> ClawConfig:
    """Load CLAW config from TOML file.

    Args:
        config_path: Path to claw.toml. Defaults to ./claw.toml relative to project root.

    Returns:
        Validated ClawConfig instance.
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent.parent / "claw.toml"

    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    _load_runtime_env(config_path)

    with open(config_path) as f:
        raw = toml.load(f)

    # Convert agents section: TOML nested tables -> dict[str, AgentConfig]
    agents_raw = raw.pop("agents", {})
    agents = {}
    for agent_name, agent_data in agents_raw.items():
        if isinstance(agent_data, dict):
            agents[agent_name] = AgentConfig(**agent_data)

    # Convert instances.siblings: list of TOML tables -> list[InstanceConfig]
    instances_raw = raw.get("instances", {})
    if isinstance(instances_raw, dict) and "siblings" in instances_raw:
        siblings_raw = instances_raw.get("siblings", [])
        if isinstance(siblings_raw, list):
            instances_raw["siblings"] = [
                InstanceConfig(**s) if isinstance(s, dict) else s
                for s in siblings_raw
            ]

    # Environment variable overrides
    db_path_env = os.getenv("CLAW_DB_PATH")
    if db_path_env:
        raw.setdefault("database", {})["db_path"] = db_path_env
    elif _env_flag("CLAW_USE_EVOLUTION_CHAMPION") is True:
        champion_db = _resolve_evolution_champion_db(config_path)
        if champion_db:
            raw.setdefault("database", {})["db_path"] = champion_db

    flag_env_map = {
        "CLAW_FEATURE_COMPONENT_CARDS": "component_cards",
        "CLAW_FEATURE_APPLICATION_PACKETS": "application_packets",
        "CLAW_FEATURE_CONNECTOME_SEQ": "connectome_seq",
        "CLAW_FEATURE_CRITICAL_SLOT_POLICY": "critical_slot_policy",
        "CLAW_FEATURE_CRITICAL_SLOT_PREWRITE_BLOCK": "critical_slot_prewrite_block",
        "CLAW_FEATURE_A2A_PACKETS": "a2a_packets",
    }
    for env_name, key in flag_env_map.items():
        value = _env_flag(env_name)
        if value is not None:
            raw.setdefault("feature_flags", {})[key] = value

    config = ClawConfig(**raw, agents=agents)
    return config
