"""All Pydantic data models for CLAW.

Defines the data contracts used across all agents, database operations,
and orchestration. Every table row and inter-agent message has a model here.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


def _new_id() -> str:
    """Generate a new string UUID for SQLite TEXT PRIMARY KEY."""
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TaskStatus(str, enum.Enum):
    PENDING = "PENDING"
    EVALUATING = "EVALUATING"
    PLANNING = "PLANNING"
    DISPATCHED = "DISPATCHED"
    CODING = "CODING"
    REVIEWING = "REVIEWING"
    STUCK = "STUCK"
    DONE = "DONE"


class HypothesisOutcome(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class LifecycleState(str, enum.Enum):
    EMBRYONIC = "embryonic"
    VIABLE = "viable"
    THRIVING = "thriving"
    DECLINING = "declining"
    DORMANT = "dormant"
    DEAD = "dead"


class MethodologyType(str, enum.Enum):
    BUG_FIX = "BUG_FIX"
    PATTERN = "PATTERN"
    DECISION = "DECISION"
    GOTCHA = "GOTCHA"


class ComplexityTier(str, enum.Enum):
    TRIVIAL = "TRIVIAL"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class AgentMode(str, enum.Enum):
    """How an agent is invoked."""
    CLI = "cli"
    API = "api"
    CLOUD = "cloud"
    OPENROUTER = "openrouter"
    LOCAL = "local"


class OperationalMode(str, enum.Enum):
    """CLAW operational modes."""
    ATTENDED = "attended"
    SUPERVISED = "supervised"
    AUTONOMOUS = "autonomous"


class FitBucket(str, enum.Enum):
    WILL_HELP = "will_help"
    MAY_HELP = "may_help"
    STRETCH = "stretch"
    NO_HELP = "no_help"


class TransferMode(str, enum.Enum):
    DIRECT_FIT = "direct_fit"
    PATTERN_TRANSFER = "pattern_transfer"
    HEURISTIC_FALLBACK = "heuristic_fallback"


class ProvenancePrecision(str, enum.Enum):
    PRECISE_SYMBOL = "precise_symbol"
    SYMBOL = "symbol"
    FILE = "file"
    CHUNK = "chunk"


class SlotRisk(str, enum.Enum):
    NORMAL = "normal"
    CRITICAL = "critical"


class CoverageState(str, enum.Enum):
    COVERED = "covered"
    WEAK = "weak"
    UNCOVERED = "uncovered"
    QUARANTINED = "quarantined"
    CLONE_INFLATED = "clone_inflated"


class AdaptationBurden(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LandingOrigin(str, enum.Enum):
    ADAPTED_COMPONENT = "adapted_component"
    NOVEL_SYNTHESIS = "novel_synthesis"
    MIXED_ANCESTRY = "mixed_ancestry"
    MANUAL_OVERRIDE = "manual_override"


class PacketStatus(str, enum.Enum):
    DRAFT = "draft"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    BLOCKED = "blocked"
    EXECUTING = "executing"
    VERIFIED = "verified"
    FAILED = "failed"
    QUARANTINED = "quarantined"


# ---------------------------------------------------------------------------
# Database row models
# ---------------------------------------------------------------------------


class Receipt(BaseModel):
    """Precise or partial source identity for a reusable component."""
    source_barcode: str
    family_barcode: str
    lineage_id: str
    repo: str
    commit: Optional[str] = None
    file_path: str
    symbol: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    content_hash: str
    provenance_precision: ProvenancePrecision


class ComponentLineage(BaseModel):
    """Deduplicated lineage family across cloned or near-duplicate components."""
    id: str = Field(default_factory=_new_id)
    family_barcode: str
    canonical_content_hash: str
    canonical_title: Optional[str] = None
    language: Optional[str] = None
    lineage_size: int = 1
    deduped_support_count: int = 1
    clone_inflated: bool = False
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class ComponentCard(BaseModel):
    """Precise reusable implementation unit derived from mining or backfill."""
    id: str = Field(default_factory=_new_id)
    methodology_id: Optional[str] = None
    title: str
    component_type: str
    abstract_jobs: list[str] = Field(default_factory=list)
    receipt: Receipt
    language: Optional[str] = None
    frameworks: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    outputs: list[dict[str, Any]] = Field(default_factory=list)
    test_evidence: list[str] = Field(default_factory=list)
    applicability: list[str] = Field(default_factory=list)
    non_applicability: list[str] = Field(default_factory=list)
    adaptation_notes: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    coverage_state: CoverageState = CoverageState.WEAK
    success_count: int = 0
    failure_count: int = 0
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class ComponentFit(BaseModel):
    """Learned or heuristic fit estimate for a component under a slot/task pattern."""
    id: str = Field(default_factory=_new_id)
    component_id: str
    task_archetype: Optional[str] = None
    component_type: Optional[str] = None
    slot_signature: Optional[str] = None
    fit_bucket: FitBucket
    transfer_mode: TransferMode
    confidence: float = 0.0
    confidence_basis: list[str] = Field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    evidence_count: int = 0
    notes: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=_now)


class ComponentCardSummary(BaseModel):
    """Lightweight list/search payload for component explorer views."""
    id: str
    title: str
    component_type: str
    language: Optional[str] = None
    family_barcode: str
    repo: str
    file_path: str
    symbol: Optional[str] = None
    provenance_precision: ProvenancePrecision
    success_count: int = 0
    failure_count: int = 0
    coverage_state: CoverageState = CoverageState.WEAK


class SlotSpec(BaseModel):
    """Concrete part of the current task that must be solved."""
    slot_id: str
    slot_barcode: str
    name: str
    abstract_job: str
    risk: SlotRisk = SlotRisk.NORMAL
    constraints: list[str] = Field(default_factory=list)
    target_stack: list[str] = Field(default_factory=list)
    proof_expectations: list[str] = Field(default_factory=list)


class CandidateSummary(BaseModel):
    """Lightweight ranked candidate view for packet construction."""
    component_id: str
    title: str
    fit_bucket: FitBucket
    transfer_mode: TransferMode
    confidence: float
    confidence_basis: list[str] = Field(default_factory=list)
    receipt: Receipt
    why_fit: list[str] = Field(default_factory=list)
    known_failure_modes: list[str] = Field(default_factory=list)
    prior_success_count: int = 0
    prior_failure_count: int = 0
    deduped_lineage_count: int = 0
    adaptation_burden: AdaptationBurden = AdaptationBurden.MEDIUM


class AdaptationStep(BaseModel):
    """Single adaptation action required to fit a selected component."""
    step_id: str = Field(default_factory=_new_id)
    title: str
    rationale: str = ""
    blocking: bool = False
    status: str = "pending"  # pending, applied, failed, skipped


class ProofGate(BaseModel):
    """Single proof requirement attached to a packet."""
    gate_id: str
    gate_type: str  # tests, verifier, semgrep, codeql, human_review
    required: bool = True
    status: str = "pending"  # pending, pass, fail, waived
    details: list[str] = Field(default_factory=list)


class ExpectedLandingSite(BaseModel):
    """Expected landing site for a selected packet."""
    file_path: str
    symbol: Optional[str] = None
    rationale: str = ""


class ApplicationPacketSummary(BaseModel):
    """Lightweight packet view for slot lists and plan summaries."""
    packet_id: str
    plan_id: str
    task_archetype: str
    slot_id: str
    slot_name: str
    status: PacketStatus = PacketStatus.DRAFT
    selected_component_id: str
    fit_bucket: FitBucket
    transfer_mode: TransferMode
    confidence: float
    review_required: bool = False
    coverage_state: CoverageState = CoverageState.WEAK


class ApplicationPacket(BaseModel):
    """Primary pre-mutation decision artifact for one slot."""
    packet_id: str = Field(default_factory=_new_id)
    schema_version: str = "cam.packet.v1"
    plan_id: str
    task_archetype: str
    slot: SlotSpec
    status: PacketStatus = PacketStatus.DRAFT
    selected: CandidateSummary
    runner_ups: list[CandidateSummary] = Field(default_factory=list)
    no_viable_runner_up_reason: Optional[str] = None
    why_selected: list[str] = Field(default_factory=list)
    why_runner_up_lost: dict[str, list[str]] = Field(default_factory=dict)
    adaptation_plan: list[AdaptationStep] = Field(default_factory=list)
    proof_plan: list[ProofGate] = Field(default_factory=list)
    expected_landing_sites: list[ExpectedLandingSite] = Field(default_factory=list)
    negative_memory: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    reviewer_required: bool = False
    review_required_reasons: list[str] = Field(default_factory=list)
    confidence_basis: list[str] = Field(default_factory=list)
    coverage_state: CoverageState = CoverageState.WEAK


class TaskPlanRecord(BaseModel):
    """Durable reviewed task plan record for pre-mutation packet workflows."""
    id: str
    task_text: str
    workspace_dir: Optional[str] = None
    branch: Optional[str] = None
    target_brain: Optional[str] = None
    execution_mode: Optional[str] = None
    check_commands: list[str] = Field(default_factory=list)
    task_archetype: str
    archetype_confidence: float = 0.0
    status: str = "draft"
    summary: dict[str, int] = Field(default_factory=dict)
    approved_slot_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    plan_json: dict[str, Any] = Field(default_factory=dict)


class PairEvent(BaseModel):
    """Runtime record that a slot was paired with a selected component."""
    id: str = Field(default_factory=_new_id)
    run_id: str
    slot_id: str
    slot_barcode: str
    packet_id: str
    component_id: str
    source_barcode: str
    confidence: float = 0.0
    confidence_basis: list[str] = Field(default_factory=list)
    replacement_of_pair_id: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)


class LandingEvent(BaseModel):
    """Runtime record of where a packet-guided change landed in the target repo."""
    id: str = Field(default_factory=_new_id)
    run_id: str
    slot_id: str
    packet_id: str
    file_path: str
    symbol: Optional[str] = None
    diff_hunk_id: Optional[str] = None
    origin: LandingOrigin
    created_at: datetime = Field(default_factory=_now)


class OutcomeEvent(BaseModel):
    """Sequenced result of verification and proof for one slot."""
    id: str = Field(default_factory=_new_id)
    run_id: str
    slot_id: str
    packet_id: str
    success: bool = False
    verifier_findings: list[str] = Field(default_factory=list)
    test_refs: list[str] = Field(default_factory=list)
    negative_memory_updates: list[str] = Field(default_factory=list)
    recipe_eligible: bool = False
    created_at: datetime = Field(default_factory=_now)


class RunConnectome(BaseModel):
    """Persisted run-level connectome record."""
    id: str = Field(default_factory=_new_id)
    run_id: str
    task_archetype: Optional[str] = None
    status: str = "pending"
    created_at: datetime = Field(default_factory=_now)


class RunSlotExecution(BaseModel):
    """Persisted runtime execution state for one slot inside a reviewed run."""
    id: str = Field(default_factory=_new_id)
    run_id: str
    slot_id: str
    packet_id: Optional[str] = None
    selected_component_id: Optional[str] = None
    status: str = "queued"
    current_step: Optional[str] = None
    retry_count: int = 0
    last_retry_detail: Optional[str] = None
    replacement_count: int = 0
    blocked_wait_ms: int = 0
    family_wait_ms: int = 0
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class RunEvent(BaseModel):
    """Durable event stream entry for CAM-SEQ run supervision."""
    id: str = Field(default_factory=_new_id)
    run_id: str
    slot_id: Optional[str] = None
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class RunActionAudit(BaseModel):
    """Durable operator/governance action taken against a reviewed run."""
    id: str = Field(default_factory=_new_id)
    run_id: str
    slot_id: Optional[str] = None
    action_type: str
    actor: str = "operator"
    reason: str = ""
    action_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class CompiledRecipe(BaseModel):
    """Distilled reusable build pattern learned from repeated success."""
    id: str = Field(default_factory=_new_id)
    task_archetype: str
    recipe_name: str
    recipe_json: dict[str, Any] = Field(default_factory=dict)
    sample_size: int = 0
    is_active: bool = False
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class MiningMission(BaseModel):
    """Targeted acquisition job emitted from plan review or post-run analysis."""
    id: str = Field(default_factory=_new_id)
    run_id: Optional[str] = None
    slot_family: Optional[str] = None
    priority: str = "normal"
    reason: str = ""
    status: str = "queued"
    mission_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class ExternalSpecialistExchange(BaseModel):
    """Durable request/reply state for external specialist packet handoffs."""
    id: str = Field(default_factory=_new_id)
    request_id: str = Field(default_factory=_new_id)
    reply_id: Optional[str] = None
    plan_id: Optional[str] = None
    slot_id: Optional[str] = None
    packet_id: Optional[str] = None
    task_text: str
    specialty: str = "general"
    specialist_identity: Optional[str] = None
    status: str = "draft"
    reconciliation_outcome: Optional[str] = None
    request_path: Optional[str] = None
    reply_path: Optional[str] = None
    request_json: dict[str, Any] = Field(default_factory=dict)
    reply_json: dict[str, Any] = Field(default_factory=dict)
    failure_reason: str = ""
    deadline_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class GovernancePolicy(BaseModel):
    """Durable governance recommendation promoted into active policy memory."""
    id: str = Field(default_factory=_new_id)
    run_id: Optional[str] = None
    task_archetype: Optional[str] = None
    slot_id: Optional[str] = None
    family_barcode: Optional[str] = None
    policy_kind: str
    severity: str = "medium"
    status: str = "active"
    reason: str = ""
    recommendation: str = ""
    evidence_json: dict[str, Any] = Field(default_factory=dict)
    promoted_by: str = "operator"
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Project(BaseModel):
    id: str = Field(default_factory=_new_id)
    name: str
    repo_path: str
    tech_stack: dict[str, Any] = Field(default_factory=dict)
    project_rules: Optional[str] = None
    banned_dependencies: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Task(BaseModel):
    id: str = Field(default_factory=_new_id)
    project_id: str
    title: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 0
    task_type: Optional[str] = None
    recommended_agent: Optional[str] = None
    assigned_agent: Optional[str] = None
    action_template_id: Optional[str] = None
    execution_steps: list[str] = Field(default_factory=list)
    acceptance_checks: list[str] = Field(default_factory=list)
    context_snapshot_id: Optional[str] = None
    attempt_count: int = 0
    escalation_count: int = 0
    excluded_agents: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    completed_at: Optional[datetime] = None


class HypothesisEntry(BaseModel):
    id: str = Field(default_factory=_new_id)
    task_id: str
    attempt_number: int
    approach_summary: str
    outcome: HypothesisOutcome = HypothesisOutcome.FAILURE
    error_signature: Optional[str] = None
    error_full: Optional[str] = None
    files_changed: list[str] = Field(default_factory=list)
    duration_seconds: Optional[float] = None
    model_used: Optional[str] = None
    agent_id: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)


class MethodologyUsageEntry(BaseModel):
    """Attribution log for methodologies retrieved and used during a task."""
    id: str = Field(default_factory=_new_id)
    task_id: str
    methodology_id: str
    project_id: Optional[str] = None
    stage: str = "retrieved_presented"  # retrieved_presented, used_in_outcome, outcome_attributed
    agent_id: Optional[str] = None
    success: Optional[bool] = None
    expectation_match_score: Optional[float] = None
    quality_score: Optional[float] = None
    relevance_score: Optional[float] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)


class CapabilityIO(BaseModel):
    """Single input or output port of a capability."""
    name: str
    type: str  # "text", "code_patch", "metrics_data", "event_list", etc.
    required: bool = True
    description: str = ""


class CapabilityArtifactReference(BaseModel):
    """Concrete source artifact that backs a reusable capability."""
    file_path: str
    symbol_name: Optional[str] = None
    symbol_kind: str = "file"  # file, function, class, module, workflow, config_pattern
    note: str = ""


class ComposabilityInterface(BaseModel):
    """Describes how a capability can chain with others."""
    can_chain_after: list[str] = Field(default_factory=list)  # domain tags
    can_chain_before: list[str] = Field(default_factory=list)
    standalone: bool = True


class CapabilityData(BaseModel):
    """Structured capability metadata stored as JSON in methodologies.capability_data."""
    schema_version: int = 2
    enrichment_status: str = "enriched"  # seeded, partial, enriched, merged
    inputs: list[CapabilityIO] = Field(default_factory=list)
    outputs: list[CapabilityIO] = Field(default_factory=list)
    domain: list[str] = Field(default_factory=list)
    composability: ComposabilityInterface = Field(default_factory=ComposabilityInterface)
    capability_type: str = "transformation"  # transformation, analysis, generation, validation
    source_repos: list[str] = Field(default_factory=list)
    source_artifacts: list[CapabilityArtifactReference] = Field(default_factory=list)
    applicability: list[str] = Field(default_factory=list)
    non_applicability: list[str] = Field(default_factory=list)
    activation_triggers: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    composition_candidates: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class SynergyEdgeType(str, enum.Enum):
    DEPENDS_ON = "depends_on"
    ENHANCES = "enhances"
    COMPETES_WITH = "competes_with"
    FEEDS_INTO = "feeds_into"
    SYNERGY = "synergy"
    CO_RETRIEVAL = "co_retrieval"


class SynergyExploration(BaseModel):
    """A record of an explored capability pair."""
    id: str = Field(default_factory=_new_id)
    cap_a_id: str
    cap_b_id: str
    explored_at: datetime = Field(default_factory=_now)
    result: str = "pending"  # pending, synergy, no_match, error, stale
    synergy_score: Optional[float] = None
    synergy_type: Optional[str] = None
    edge_id: Optional[str] = None
    exploration_method: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)


class Methodology(BaseModel):
    id: str = Field(default_factory=_new_id)
    problem_description: str
    problem_embedding: Optional[list[float]] = None
    solution_code: str
    methodology_notes: Optional[str] = None
    source_task_id: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    language: Optional[str] = None
    scope: str = "project"
    methodology_type: Optional[str] = None
    files_affected: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    lifecycle_state: str = "viable"
    retrieval_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    last_retrieved_at: Optional[datetime] = None
    generation: int = 0
    fitness_vector: dict[str, Any] = Field(default_factory=dict)
    parent_ids: list[str] = Field(default_factory=list)
    superseded_by: Optional[str] = None
    prism_data: Optional[dict] = None
    capability_data: Optional[dict] = None
    novelty_score: Optional[float] = None
    potential_score: Optional[float] = None
    accuracy_contract: str = "soft"  # hard|frontier|scenario|soft
    concept_type: Optional[str] = None  # invariant|failure_mode|protocol|novel_abstraction|decision_rule|bridge
    use_immediately_as: list[str] = Field(default_factory=list)  # operational directives
    tension_questions: list[str] = Field(default_factory=list)  # epistemic tension questions
    triage_score: Optional[float] = None  # 7-dim composite ingest triage score


class ActionTemplate(BaseModel):
    """Reusable executable runbook mined from successful patterns."""
    id: str = Field(default_factory=_new_id)
    title: str
    problem_pattern: str
    execution_steps: list[str] = Field(default_factory=list)
    acceptance_checks: list[str] = Field(default_factory=list)
    rollback_steps: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    source_methodology_id: Optional[str] = None
    source_repo: Optional[str] = None
    confidence: float = 0.5
    success_count: int = 0
    failure_count: int = 0
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class MetricExpectation(BaseModel):
    """A single measurable metric that the build must satisfy."""
    name: str
    metric: str  # "min_test_count", "min_coverage_pct", "max_files_changed", "min_files_changed"
    operator: str = "gte"  # "gte", "lte", "eq", "gt", "lt"
    value: float = 0.0
    hard: bool = True  # True = violation blocks approval; False = recommendation only


class ExpectationContract(BaseModel):
    """User-visible contract for what counts as a useful result."""
    goal: str
    expected_outcome: list[str] = Field(default_factory=list)
    expected_ux: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    validation_signals: list[str] = Field(default_factory=list)
    metric_expectations: list[MetricExpectation] = Field(default_factory=list)


class ExpectationAssessment(BaseModel):
    """Assessment of how closely a result matched the expectation contract."""
    score: float = 0.0
    matched: list[str] = Field(default_factory=list)
    unmet: list[str] = Field(default_factory=list)
    summary: str = ""


class PeerReview(BaseModel):
    id: str = Field(default_factory=_new_id)
    task_id: str
    model_used: str
    diagnosis: str
    recommended_approach: Optional[str] = None
    reasoning: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)


class ContextSnapshot(BaseModel):
    id: str = Field(default_factory=_new_id)
    task_id: str
    attempt_number: int
    git_ref: str
    file_manifest: Optional[dict[str, str]] = None
    created_at: datetime = Field(default_factory=_now)


class MethodologyLink(BaseModel):
    id: str = Field(default_factory=_new_id)
    source_id: str
    target_id: str
    link_type: str = "co_retrieval"
    strength: float = 1.0
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Token cost tracking
# ---------------------------------------------------------------------------

class TokenCostRecord(BaseModel):
    id: str = Field(default_factory=_new_id)
    task_id: Optional[str] = None
    run_id: Optional[str] = None
    agent_role: str = ""
    agent_id: Optional[str] = None
    model_used: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Inter-agent message models (CLAW-specific)
# ---------------------------------------------------------------------------

class AgentResult(BaseModel):
    """Standardized output from any agent."""
    agent_name: str
    status: str  # "success", "failure", "blocked"
    data: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    duration_seconds: float = 0.0


class TaskOutcome(BaseModel):
    """Output of any agent executing a task (replaces BuildResult)."""
    files_changed: list[str] = Field(default_factory=list)
    test_output: str = ""
    tests_passed: bool = False
    diff: str = ""
    approach_summary: str = ""
    model_used: Optional[str] = None
    agent_id: Optional[str] = None
    failure_reason: Optional[str] = None
    failure_detail: Optional[str] = None
    self_audit: str = ""
    raw_output: Optional[str] = None
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_seconds: float = 0.0


class VerificationResult(BaseModel):
    """Output of Verifier — audit gate decision (replaces SentinelVerdict)."""
    approved: bool = False
    violations: list[dict[str, str]] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    quality_score: Optional[float] = None
    expectation_match_score: Optional[float] = None
    expectation_findings: list[str] = Field(default_factory=list)
    tests_before: Optional[int] = None
    tests_after: Optional[int] = None
    test_output: str = ""
    swe_dimensions: Optional[SWEQualityDimensions] = None
    drift_cosine_score: Optional[float] = None


class SWEQualityDimensions(BaseModel):
    """6-dimensional SWE quality metric for A/B comparison.

    Each dimension is 0.0-1.0. Composite score is the weighted geometric mean.
    Weights: D1=0.30, D2=0.15, D3=0.20, D4=0.15, D5=0.10, D6=0.10
    """
    functional_correctness: float = 0.0    # D1: tests pass? 1.0=all, 0.5=some, 0.0=none
    structural_compliance: float = 0.0     # D2: 1.0 - violation penalty
    intent_alignment: float = 0.0          # D3: drift cosine similarity
    correction_efficiency: float = 0.0     # D4: 1.0/attempts_needed
    token_economy: float = 0.0             # D5: 1.0 - tokens_used/budget
    expectation_match: float = 0.0         # D6: expectation contract score

    _WEIGHTS = {
        "functional_correctness": 0.30,
        "structural_compliance": 0.15,
        "intent_alignment": 0.20,
        "correction_efficiency": 0.15,
        "token_economy": 0.10,
        "expectation_match": 0.10,
    }

    @property
    def composite_score(self) -> float:
        """Weighted geometric mean of all dimensions.

        Geometric mean penalizes zeroes — code that fails tests
        gets a low composite regardless of other dimensions.
        Uses a floor of 0.01 to avoid log(0).
        """
        import math
        log_sum = 0.0
        for dim_name, weight in self._WEIGHTS.items():
            val = max(getattr(self, dim_name), 0.01)  # floor to avoid log(0)
            log_sum += weight * math.log(val)
        return math.exp(log_sum)


class EscalationDiagnosis(BaseModel):
    """Output of escalation — peer review strategy (replaces CouncilDiagnosis)."""
    strategy_shift: str
    new_approach: str
    reasoning: str
    model_used: str


class AgentHealth(BaseModel):
    """Health check result for an agent."""
    agent_id: str
    available: bool = False
    mode: Optional[AgentMode] = None
    version: Optional[str] = None
    error: Optional[str] = None
    latency_ms: Optional[float] = None


class CycleResult(BaseModel):
    """Result of one claw cycle iteration."""
    cycle_level: str  # "micro", "meso", "macro", "nano"
    task_id: Optional[str] = None
    project_id: Optional[str] = None
    agent_id: Optional[str] = None
    outcome: TaskOutcome = Field(default_factory=TaskOutcome)
    verification: Optional[VerificationResult] = None
    success: bool = False
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_seconds: float = 0.0


class FleetTask(BaseModel):
    """A repo in the fleet queue."""
    id: str = Field(default_factory=_new_id)
    repo_path: str
    repo_name: str
    priority: float = 0.0
    status: str = "pending"
    enhancement_branch: Optional[str] = None
    last_evaluated: Optional[datetime] = None
    evaluation_score: Optional[float] = None
    budget_allocated_usd: float = 0.0
    budget_used_usd: float = 0.0
    created_at: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Context models (pipeline flow)
# ---------------------------------------------------------------------------

class CorrectionFeedback(BaseModel):
    """Feedback from a failed verification attempt, sent back to the agent for correction."""
    attempt_number: int = 0
    violations: list[dict[str, str]] = Field(default_factory=list)
    test_output: str = ""
    diff: str = ""
    code_diff: str = ""          # Unified diff showing what the agent actually wrote
    failing_test_content: str = ""  # Content of the test file(s) the agent must pass
    quality_score: float = 0.0
    failure_reason: Optional[str] = None
    failure_detail: Optional[str] = None
    known_fix_hint: Optional[str] = None
    auto_fixes_applied: list[str] = Field(default_factory=list)


class TaskContext(BaseModel):
    """Enriched task context for the pipeline."""
    task: Task
    forbidden_approaches: list[str] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)
    action_template: Optional[ActionTemplate] = None
    expectation_contract: Optional[ExpectationContract] = None
    checkpoint_ref: Optional[str] = None
    previous_escalation_diagnosis: Optional[str] = None
    correction_feedback: Optional[CorrectionFeedback] = None


class ContextBrief(BaseModel):
    """Full context assembled for agent execution."""
    task: Task
    past_solutions: list[Methodology] = Field(default_factory=list)
    forbidden_approaches: list[str] = Field(default_factory=list)
    project_rules: Optional[str] = None
    escalation_diagnosis: Optional[str] = None
    retrieval_confidence: float = 0.0
    retrieval_conflicts: list[str] = Field(default_factory=list)
    retrieval_strategy_hint: Optional[str] = None
    complexity_tier: Optional[str] = None
    sentinel_feedback: list[dict[str, str]] = Field(default_factory=list)
    retrieved_methodology_ids: list[str] = Field(default_factory=list)
    correction_feedback: Optional[CorrectionFeedback] = None
    # Bandit-selected primary methodology (highest bandit score)
    primary_methodology_id: Optional[str] = None
    # Context methodology IDs (rank 2-3, lighter weight in prompt)
    context_methodology_ids: list[str] = Field(default_factory=list)
    # CAM-SEQ: ApplicationPackets built during evaluate (structured component guidance)
    application_packets: list["ApplicationPacket"] = Field(default_factory=list)


class ExecutionState(BaseModel):
    """Shared typed execution state passed through the agent pipeline."""
    task_id: str
    run_id: Optional[str] = None
    trace_id: Optional[str] = None
    current_phase: str = "init"
    attempt_number: int = 0
    token_budget_remaining: int = 100_000
    tokens_used: int = 0
    complexity_tier: Optional[ComplexityTier] = None
    quality_score: Optional[float] = None
    agent_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Cross-brain analysis models
# ---------------------------------------------------------------------------

class UniversalPattern(BaseModel):
    """A pattern found across 2+ brain ganglia."""
    pattern_name: str = ""
    implementations: dict[str, str] = Field(default_factory=dict)
    evidence_ids: dict[str, list[str]] = Field(default_factory=dict)
    domain_overlap: float = 0.0
    source_categories: list[str] = Field(default_factory=list)


class UniqueInnovation(BaseModel):
    """A methodology unique to a single brain with no equivalent elsewhere."""
    brain: str = ""
    methodology_id: str = ""
    problem_summary: str = ""
    solution_summary: str = ""
    why_unique: str = ""
    category: str = ""


class TransferableInsight(BaseModel):
    """A pattern from one brain that could benefit another."""
    source_brain: str = ""
    target_brain: str = ""
    source_methodology_id: str = ""
    rationale: str = ""
    pattern_name: str = ""


class CompositionLayer(BaseModel):
    """A layer in a multi-brain composed architecture."""
    layer_number: int = 0
    layer_name: str = ""
    contributing_brain: str = ""
    methodology_id: str = ""
    methodology_summary: str = ""


class CoverageMatrix(BaseModel):
    """Category x brain coverage matrix for gap analysis."""
    matrix: dict[str, dict[str, int]] = Field(default_factory=dict)
    sparse_cells: list[tuple[str, str]] = Field(default_factory=list)
    empty_cells: list[tuple[str, str]] = Field(default_factory=list)
    total_by_category: dict[str, int] = Field(default_factory=dict)
    total_by_brain: dict[str, int] = Field(default_factory=dict)


class CrossBrainMetrics(BaseModel):
    """Metrics from a cross-brain analysis run."""
    query: str = ""
    brains_queried: int = 0
    brains_with_results: int = 0
    total_results: int = 0
    cross_brain_coverage: float = 0.0
    universal_pattern_count: int = 0
    novelty_count: int = 0
    unique_innovations_per_brain: dict[str, int] = Field(default_factory=dict)
    trace_count: int = 0


class CrossLanguageReport(BaseModel):
    """Full report from a cross-language analysis."""
    query: str = ""
    domains_queried: list[str] = Field(default_factory=list)
    universal_patterns: list[UniversalPattern] = Field(default_factory=list)
    unique_innovations: list[UniqueInnovation] = Field(default_factory=list)
    transferable_insights: list[TransferableInsight] = Field(default_factory=list)
    composition_layers: list[CompositionLayer] = Field(default_factory=list)
    metrics: CrossBrainMetrics = Field(default_factory=CrossBrainMetrics)
    raw_results_by_brain: dict[str, list[str]] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=_now)
