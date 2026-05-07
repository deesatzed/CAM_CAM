const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8420";

async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${path} failed (${res.status}): ${body}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------

export interface BrainStats {
  primary: {
    name: string;
    total: number;
    active: number;
    lifecycle: Record<string, number>;
    languages: Record<string, number>;
    top_categories: Record<string, number>;
    source_repos: number;
  };
  siblings: Array<{
    name: string;
    description: string;
    db_exists: boolean;
    methodology_count: number;
  }>;
  total_across_brain: number;
}

export function getStats(): Promise<BrainStats> {
  return fetchAPI("/api/stats");
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

export interface SearchResult {
  id: string;
  problem: string;
  solution_preview: string;
  notes: string;
  tags: string[];
  language: string;
  lifecycle: string;
  novelty: number | null;
  retrievals: number;
  successes: number;
  source_ganglion: string;
  fts_rank: number;
  relevance_score?: number;
}

export interface SearchResponse {
  query: string;
  total_results: number;
  elapsed_ms: number;
  ganglion_counts: Record<string, number>;
  governance_context?: {
    task_archetype: string;
    archetype_confidence: number;
    active_policy_count: number;
    conflict_count: number;
    policies: Array<Record<string, unknown>>;
    conflicts: Array<Record<string, unknown>>;
  };
  results: SearchResult[];
}

export function searchKnowledge(q: string, limit = 30): Promise<SearchResponse> {
  return fetchAPI(`/api/search?q=${encodeURIComponent(q)}&limit=${limit}`);
}

// ---------------------------------------------------------------------------
// Methodology
// ---------------------------------------------------------------------------

export interface Methodology {
  id: string;
  problem_description: string;
  solution_code: string;
  methodology_notes: string;
  tags: string[];
  language: string;
  lifecycle_state: string;
  methodology_type: string;
  novelty_score: number | null;
  potential_score: number | null;
  retrieval_count: number;
  success_count: number;
  failure_count: number;
  created_at: string;
  files_affected: string | null;
}

export function getMethodology(id: string): Promise<Methodology> {
  return fetchAPI(`/api/methodology/${id}`);
}

export interface FitnessEntry {
  fitness_total: number;
  fitness_vector: Record<string, number>;
  trigger_event: string;
  created_at: string;
}

export function getMethodologyFitness(id: string): Promise<{ methodology_id: string; entries: FitnessEntry[] }> {
  return fetchAPI(`/api/methodology/${id}/fitness`);
}

// ---------------------------------------------------------------------------
// CAM-SEQ Components
// ---------------------------------------------------------------------------

export type ProvenancePrecision = "precise_symbol" | "symbol" | "file" | "chunk";
export type CoverageState =
  | "covered"
  | "weak"
  | "uncovered"
  | "quarantined"
  | "clone_inflated";
export type FitBucket = "will_help" | "may_help" | "stretch" | "no_help";
export type TransferMode = "direct_fit" | "pattern_transfer" | "heuristic_fallback";
export type SlotRisk = "normal" | "critical";
export type PacketStatus =
  | "draft"
  | "review_required"
  | "approved"
  | "blocked"
  | "executing"
  | "verified"
  | "failed"
  | "quarantined";

export interface Receipt {
  source_barcode: string;
  family_barcode: string;
  lineage_id: string;
  repo: string;
  commit?: string | null;
  file_path: string;
  symbol?: string | null;
  line_start?: number | null;
  line_end?: number | null;
  content_hash: string;
  provenance_precision: ProvenancePrecision;
}

export interface ComponentCardSummary {
  id: string;
  title: string;
  component_type: string;
  language?: string | null;
  family_barcode: string;
  repo: string;
  file_path: string;
  symbol?: string | null;
  provenance_precision: ProvenancePrecision;
  success_count: number;
  failure_count: number;
  coverage_state: CoverageState;
  search_score?: number;
  source_scope?: "memory" | "workspace";
  governance_summary?: {
    family_barcode: string;
    active_policy_count: number;
  };
}

export interface ComponentCard {
  id: string;
  methodology_id?: string | null;
  title: string;
  component_type: string;
  abstract_jobs: string[];
  receipt: Receipt;
  language?: string | null;
  frameworks: string[];
  dependencies: string[];
  constraints: string[];
  inputs: Array<Record<string, unknown>>;
  outputs: Array<Record<string, unknown>>;
  test_evidence: string[];
  applicability: string[];
  non_applicability: string[];
  adaptation_notes: string[];
  risk_notes: string[];
  keywords: string[];
  coverage_state: CoverageState;
  success_count: number;
  failure_count: number;
  created_at: string;
  updated_at: string;
}

export interface ComponentLineage {
  id: string;
  family_barcode: string;
  canonical_content_hash: string;
  canonical_title?: string | null;
  language?: string | null;
  lineage_size: number;
  deduped_support_count: number;
  clone_inflated: boolean;
  created_at: string;
  updated_at: string;
}

export interface ComponentFit {
  id: string;
  component_id: string;
  task_archetype?: string | null;
  component_type?: string | null;
  slot_signature?: string | null;
  fit_bucket: FitBucket;
  transfer_mode: TransferMode;
  confidence: number;
  confidence_basis: string[];
  success_count: number;
  failure_count: number;
  evidence_count: number;
  notes: string[];
  updated_at: string;
}

export interface ApplicationPacketSummary {
  packet_id: string;
  plan_id: string;
  task_archetype: string;
  slot_id: string;
  slot_name: string;
  status: string;
  selected_component_id: string;
  fit_bucket: FitBucket;
  transfer_mode: TransferMode;
  confidence: number;
  review_required: boolean;
  coverage_state: CoverageState;
}

export interface SlotSpec {
  slot_id: string;
  slot_barcode: string;
  name: string;
  abstract_job: string;
  risk: SlotRisk;
  constraints: string[];
  target_stack: string[];
  proof_expectations: string[];
}

export interface CandidateSummary {
  component_id: string;
  title: string;
  fit_bucket: FitBucket;
  transfer_mode: TransferMode;
  confidence: number;
  confidence_basis: string[];
  receipt: Receipt;
  why_fit: string[];
  known_failure_modes: string[];
  prior_success_count: number;
  prior_failure_count: number;
  deduped_lineage_count: number;
  adaptation_burden: "low" | "medium" | "high";
}

export interface AdaptationStep {
  step_id: string;
  title: string;
  rationale: string;
  blocking: boolean;
  status: "pending" | "applied" | "failed" | "skipped";
}

export interface ProofGate {
  gate_id: string;
  gate_type: string;
  required: boolean;
  status: "pending" | "pass" | "fail" | "waived";
  details: string[];
}

export interface ExpectedLandingSite {
  file_path: string;
  symbol?: string | null;
  rationale: string;
}

export interface ApplicationPacket {
  packet_id: string;
  schema_version: "cam.packet.v1";
  plan_id: string;
  task_archetype: string;
  slot: SlotSpec;
  status: PacketStatus;
  selected: CandidateSummary;
  runner_ups: CandidateSummary[];
  no_viable_runner_up_reason?: string | null;
  why_selected: string[];
  why_runner_up_lost: Record<string, string[]>;
  adaptation_plan: AdaptationStep[];
  proof_plan: ProofGate[];
  expected_landing_sites: ExpectedLandingSite[];
  negative_memory: string[];
  risk_notes: string[];
  reviewer_required: boolean;
  review_required_reasons: string[];
  confidence_basis: string[];
  coverage_state: CoverageState;
}

export interface PlanSlotSummary {
  slot_id: string;
  name: string;
  risk: SlotRisk;
  selected_packet_id: string;
  status: string;
  confidence: number;
  coverage_state: CoverageState;
}

export interface PlanSummary {
  total_slots: number;
  critical_slots: number;
  weak_evidence_slots: number;
}

export interface PlanDetail {
  plan_id: string;
  task_text: string;
  workspace_dir?: string | null;
  branch?: string | null;
  target_brain?: string | null;
  execution_mode?: string | null;
  check_commands: string[];
  task_archetype: string;
  archetype_confidence: number;
  status: string;
  slots: PlanSlotSummary[];
  summary: PlanSummary;
  approved_slot_ids: string[];
  created_at: string;
  packets: ApplicationPacket[];
}

export interface CreatePlanResponse {
  plan_id: string;
  task_archetype: string;
  archetype_confidence: number;
  status: string;
  slots: PlanSlotSummary[];
  summary: PlanSummary;
}

export interface RunStatusResponse {
  run_id: string;
  status: string;
  plan_id?: string | null;
  task_description?: string | null;
  current_slot_id?: string | null;
  retry_count: number;
  replacement_history: Array<{
    slot_id: string;
    previous_component_id?: string | null;
    new_component_id?: string | null;
    reason?: string | null;
    timestamp: string;
  }>;
  blocked_slot_ids: Record<string, string>;
  banned_family_barcodes: Record<string, string>;
  summary: {
    completed_slots: number;
    total_slots: number;
    failed_gates: number;
    pair_events: number;
    landing_events: number;
    outcome_events: number;
    action_audits: number;
    blocked_slots: number;
    banned_families: number;
    blocked_wait_ms: number;
    family_wait_ms: number;
  };
    slots: Array<{
      slot_id: string;
    name: string;
    status: string;
    confidence: number;
    landing_count: number;
    retry_count: number;
    last_retry_detail?: string | null;
    current_step?: string | null;
    replacement_count: number;
    blocked_wait_ms: number;
    family_wait_ms: number;
    selected_component_id?: string | null;
    block_reason?: string | null;
    review_required: boolean;
    coverage_state: CoverageState;
  }>;
  steps: Array<{ step: string; detail: string; timestamp: string }>;
  gates: Array<{ check: string; status: string; detail: string }>;
  result?: unknown;
}

export interface RunConnectomeResponse {
  nodes: Array<{ id: string; kind: string }>;
  edges: Array<{ source: string; target: string; type: string; metadata?: Record<string, unknown> }>;
}

export interface RunLandingsResponse {
  landings: Array<{
    locus_barcode: string;
    file_path: string;
    symbol?: string | null;
    diff_hunk_id?: string | null;
    slot_id: string;
    packet_id: string;
    origin: string;
  }>;
}

export interface RunEventsResponse {
  events: Array<{
    event_id: string;
    run_id: string;
    slot_id?: string | null;
    event_type: string;
    timestamp: string;
    payload: Record<string, unknown>;
  }>;
}

export interface RetrogradeResponse {
  root: { kind: string; id: string };
  cause_chain: Array<{ kind: string; id: string; explanation: string; rank_score?: number; supporting_signals?: string[] }>;
  root_cause_summary?: {
    primary_kind?: string | null;
    primary_explanation?: string | null;
    supporting_signals: string[];
    counterfactual_available: boolean;
    governance_pressure: boolean;
    proof_pressure: boolean;
    narrative?: string | null;
    confidence_band?: "low" | "medium" | "high";
    recommended_action?: string | null;
    actionability?: "immediate" | "review" | "observe";
    evidence_count?: number;
    dominant_cluster?: string | null;
    confidence_drivers?: string[];
    confidence_score?: number;
    confidence_reason?: string | null;
    calibration?: "stable" | "mixed" | "tentative" | string;
    stability?: "stable" | "competitive" | "fragile" | string;
    stability_reason?: string | null;
    summary_version?: string;
    decision_path?: Array<{
      kind?: string;
      explanation?: string;
      score: number;
    }>;
    clusters?: Array<{
      cluster: string;
      top_kind?: string;
      score: number;
      item_count: number;
    }>;
  };
  runner_up_analysis: {
    component_id: string;
    likely_better: boolean;
    why: string[];
    transfer_mode?: string;
  } | null;
  confidence: number;
  violations?: string[];
  task_description?: string | null;
}

export interface RunActionAudit {
  id: string;
  run_id: string;
  slot_id?: string | null;
  action_type: string;
  actor: string;
  reason: string;
  action_payload: Record<string, unknown>;
  created_at: string;
}

export interface DistillResponse {
  run_id: string;
  task_archetype?: string | null;
  promotions: Array<Record<string, unknown>>;
  downgrades: Array<Record<string, unknown>>;
  negative_memory_updates: string[];
  persisted_negative_memory?: Array<{
    error_signature: string;
    error_category: string;
    task_type?: string | null;
    prevention_hint: string;
  }>;
  governance_recommendations: Array<{
    kind: string;
    severity: "low" | "medium" | "high";
    reason: string;
    recommendation: string;
  }>;
  federation_recommendations: Array<{
    kind: string;
    severity: "low" | "medium" | "high";
    reason: string;
    recommendation: string;
  }>;
  packet_transfer_summary: Record<string, number>;
  recipe_candidates: Array<Record<string, unknown>>;
}

export interface FailureKnowledgeEntry {
  id: string;
  error_signature: string;
  error_category: string;
  diagnosis: string;
  prevention_hint: string;
  agent_id?: string | null;
  task_type?: string | null;
  project_id?: string | null;
  source_task_id?: string | null;
  root_cause_key?: string | null;
  detail_signals_json?: string | null;
  occurrence_count: number;
  resolved: number;
  resolution_approach?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface FailureKnowledgeGroup {
  causal_key: string;
  error_category: string;
  task_type: string;
  entry_count: number;
  occurrence_total: number;
  unresolved_count: number;
  resolved_count: number;
  latest_updated_at?: string | null;
  agent_ids: string[];
  source_task_ids: string[];
  sample_signatures: string[];
  diagnosis_samples: string[];
  prevention_hints: string[];
}

export interface FailureKnowledgeResponse {
  items: FailureKnowledgeEntry[];
  count: number;
  groups: FailureKnowledgeGroup[];
  filters: {
    task_type?: string | null;
    project_id?: string | null;
    error_category?: string | null;
    include_resolved: boolean;
  };
  summary: {
    unresolved_count: number;
    resolved_count: number;
    category_counts: Record<string, number>;
    group_count?: number;
  };
}

export interface MiningMission {
  id: string;
  run_id: string;
  slot_family?: string | null;
  priority: string;
  reason: string;
  status: string;
  created_at: string;
}

export interface GovernancePolicy {
  id: string;
  run_id?: string | null;
  task_archetype?: string | null;
  slot_id?: string | null;
  family_barcode?: string | null;
  policy_kind: string;
  severity: "low" | "medium" | "high" | string;
  status: string;
  reason: string;
  recommendation: string;
  evidence_json: Record<string, unknown>;
  promoted_by: string;
  created_at: string;
  updated_at: string;
}

export interface GovernanceTrendsResponse {
  by_archetype: Array<{
    task_archetype: string;
    runs: number;
    blocked_wait_ms: number;
    family_wait_ms: number;
    block_actions: number;
    ban_actions: number;
    reverify_actions: number;
  }>;
  by_family: Array<{
    family_barcode: string;
    ban_actions: number;
    unban_actions: number;
    wait_events: number;
    policy_count: number;
  }>;
}

export interface FederationTrendsResponse {
  by_archetype: Array<{
    task_archetype: string;
    runs: number;
    direct_fit: number;
    pattern_transfer: number;
    heuristic_fallback: number;
    critical_pattern_transfer: number;
    successful_packets: number;
    failed_packets: number;
  }>;
  by_family: Array<{
    family_barcode: string;
    task_archetypes: string[];
    direct_fit: number;
    pattern_transfer: number;
    heuristic_fallback: number;
    critical_pattern_transfer: number;
    successful_packets: number;
    failed_packets: number;
  }>;
}

export interface FederationPolicyRecommendationsResponse {
  recommendations: Array<{
    policy_kind: string;
    severity: "low" | "medium" | "high" | string;
    task_archetype?: string | null;
    slot_id?: string | null;
    family_barcode?: string | null;
    reason: string;
    recommendation: string;
    evidence_json: Record<string, unknown>;
    already_active: boolean;
  }>;
  trend_summary: {
    archetype_count: number;
    family_count: number;
  };
}

export interface GovernanceConflictsResponse {
  conflicts: Array<{
    policy_kind: string;
    task_archetype?: string | null;
    slot_id?: string | null;
    family_barcode?: string | null;
    conflict_reasons: string[];
    policy_ids: string[];
    statuses: string[];
    severities: string[];
  }>;
  policy_count: number;
}

export interface ComponentSearchResponse {
  items: ComponentCardSummary[];
  count: number;
  query: string;
}

export interface ComponentDetailResponse {
  component: ComponentCard;
  lineage: ComponentLineage | null;
  fit_history: ComponentFit[];
  related_methodology_components: ComponentCardSummary[];
  governance_summary?: {
    family_barcode: string;
    active_policy_count: number;
    highest_severity?: string | null;
    policies: Array<Record<string, unknown>>;
  };
}

export interface ComponentHistoryResponse {
  component_id: string;
  packet_history: ApplicationPacketSummary[];
  fit_history: ComponentFit[];
  lineage_components: ComponentCardSummary[];
}

export interface ComponentBackfillResponse {
  created: number;
  updated: number;
  skipped: number;
  methodologies: number;
  skip_reasons: Array<Record<string, string>>;
}

export function searchComponents(
  q: string,
  options?: { limit?: number; language?: string }
): Promise<ComponentSearchResponse> {
  const params = new URLSearchParams({ q });
  if (options?.limit) params.set("limit", String(options.limit));
  if (options?.language) params.set("language", options.language);
  return fetchAPI(`/api/v2/components/search?${params.toString()}`);
}

export function getComponent(componentId: string): Promise<ComponentDetailResponse> {
  return fetchAPI(`/api/v2/components/${componentId}`);
}

export function getComponentHistory(componentId: string): Promise<ComponentHistoryResponse> {
  return fetchAPI(`/api/v2/components/${componentId}/history`);
}

export function backfillComponents(body?: {
  methodology_ids?: string[];
  limit?: number;
}): Promise<ComponentBackfillResponse> {
  return fetchAPI("/api/v2/components/backfill", {
    method: "POST",
    body: JSON.stringify(body || {}),
  });
}

export function createPlan(body: {
  workspace_dir?: string;
  branch?: string;
  task_text: string;
  target_brain?: string;
  execution_mode?: string;
  check_commands?: string[];
  target_language?: string;
  target_stack_hints?: string[];
}): Promise<CreatePlanResponse> {
  return fetchAPI("/api/v2/plans", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getPlan(planId: string): Promise<PlanDetail> {
  return fetchAPI(`/api/v2/plans/${planId}`);
}

export function approvePlan(planId: string, slotIds?: string[]): Promise<{
  plan_id: string;
  status: string;
  approved_slot_ids: string[];
}> {
  return fetchAPI(`/api/v2/plans/${planId}/approve`, {
    method: "POST",
    body: JSON.stringify({ slot_ids: slotIds }),
  });
}

export function swapPlanCandidate(
  planId: string,
  slotId: string,
  candidateComponentId: string,
  reason?: string,
): Promise<{ packet: ApplicationPacket }> {
  return fetchAPI(`/api/v2/plans/${planId}/slots/${slotId}/swap-candidate`, {
    method: "POST",
    body: JSON.stringify({
      candidate_component_id: candidateComponentId,
      reason,
    }),
  });
}

export function executePlan(planId: string, approvedSlotIds?: string[]): Promise<{
  session_id: string;
  status: string;
  plan_id?: string;
  redirect_to: string;
}> {
  return fetchAPI(`/api/v2/plans/${planId}/execute`, {
    method: "POST",
    body: JSON.stringify({ approved_slot_ids: approvedSlotIds }),
  });
}

export function getRunStatus(runId: string): Promise<RunStatusResponse> {
  return fetchAPI(`/api/v2/runs/${runId}`);
}

export function getRunConnectome(runId: string): Promise<RunConnectomeResponse> {
  return fetchAPI(`/api/v2/runs/${runId}/connectome`);
}

export function getRunLandings(runId: string): Promise<RunLandingsResponse> {
  return fetchAPI(`/api/v2/runs/${runId}/landings`);
}

export function getRunEvents(runId: string): Promise<RunEventsResponse> {
  return fetchAPI(`/api/v2/runs/${runId}/events`);
}

export function getRunAudits(runId: string): Promise<{ audits: RunActionAudit[] }> {
  return fetchAPI(`/api/v2/runs/${runId}/audits`);
}

export function getRunEventsStreamUrl(runId: string): string {
  return `${API_BASE}/api/v2/runs/${runId}/events/stream`;
}

export function getRunRetrograde(runId: string, root?: string): Promise<RetrogradeResponse> {
  const params = root ? `?root=${encodeURIComponent(root)}` : "";
  return fetchAPI(`/api/v2/runs/${runId}/retrograde${params}`);
}

export function getRunDistill(runId: string): Promise<DistillResponse> {
  return fetchAPI(`/api/v2/runs/${runId}/distill`);
}

export function promoteRunRecipe(
  runId: string,
  body: { recipe_name: string; minimum_sample_size?: number },
): Promise<{ recipe: Record<string, unknown> }> {
  return fetchAPI(`/api/v2/runs/${runId}/recipes/promote`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function createMiningMission(
  runId: string,
  body: { slot_family: string; priority?: string; reason: string },
): Promise<{ mission: MiningMission }> {
  return fetchAPI(`/api/v2/runs/${runId}/gaps/create-mining-mission`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function listMiningMissions(): Promise<{ missions: MiningMission[] }> {
  return fetchAPI("/api/v2/missions/mining");
}

export function getGovernancePolicies(options?: {
  task_archetype?: string;
  active_only?: boolean;
  status?: string;
  family_barcode?: string;
  limit?: number;
}): Promise<{ policies: GovernancePolicy[] }> {
  const params = new URLSearchParams();
  if (options?.task_archetype) params.set("task_archetype", options.task_archetype);
  if (options?.active_only) params.set("active_only", "true");
  if (options?.status) params.set("status", options.status);
  if (options?.family_barcode) params.set("family_barcode", options.family_barcode);
  if (options?.limit) params.set("limit", String(options.limit));
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return fetchAPI(`/api/v2/governance/policies${suffix}`);
}

export function getGovernanceTrends(options?: {
  limit?: number;
  task_archetype?: string;
  family_barcode?: string;
}): Promise<GovernanceTrendsResponse> {
  const params = new URLSearchParams();
  params.set("limit", String(options?.limit ?? 50));
  if (options?.task_archetype) params.set("task_archetype", options.task_archetype);
  if (options?.family_barcode) params.set("family_barcode", options.family_barcode);
  return fetchAPI(`/api/v2/governance/trends?${params.toString()}`);
}

export function getFederationTrends(options?: {
  limit?: number;
  task_archetype?: string;
  family_barcode?: string;
}): Promise<FederationTrendsResponse> {
  const params = new URLSearchParams();
  params.set("limit", String(options?.limit ?? 50));
  if (options?.task_archetype) params.set("task_archetype", options.task_archetype);
  if (options?.family_barcode) params.set("family_barcode", options.family_barcode);
  return fetchAPI(`/api/v2/federation/trends?${params.toString()}`);
}

export function getFederationPolicyRecommendations(options?: {
  limit?: number;
  task_archetype?: string;
  family_barcode?: string;
}): Promise<FederationPolicyRecommendationsResponse> {
  const params = new URLSearchParams();
  params.set("limit", String(options?.limit ?? 50));
  if (options?.task_archetype) params.set("task_archetype", options.task_archetype);
  if (options?.family_barcode) params.set("family_barcode", options.family_barcode);
  return fetchAPI(`/api/v2/federation/policy-recommendations?${params.toString()}`);
}

export function promoteFederationPolicy(body: {
  policy_kind: string;
  severity?: string;
  task_archetype?: string;
  slot_id?: string;
  family_barcode?: string;
  reason: string;
  recommendation: string;
  evidence_json?: Record<string, unknown>;
  promoted_by?: string;
}): Promise<{ policy: GovernancePolicy }> {
  return fetchAPI("/api/v2/federation/policies/promote", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getGovernanceConflicts(options?: {
  task_archetype?: string;
  active_only?: boolean;
  limit?: number;
}): Promise<GovernanceConflictsResponse> {
  const params = new URLSearchParams();
  if (options?.task_archetype) params.set("task_archetype", options.task_archetype);
  if (options?.active_only) params.set("active_only", "true");
  params.set("limit", String(options?.limit ?? 100));
  return fetchAPI(`/api/v2/governance/conflicts?${params.toString()}`);
}

export function promoteGovernancePolicy(
  runId: string,
  body: {
    policy_kind: string;
    severity?: string;
    reason: string;
    recommendation: string;
    slot_id?: string;
    family_barcode?: string;
    evidence_json?: Record<string, unknown>;
    promoted_by?: string;
  },
): Promise<{ policy: GovernancePolicy }> {
  return fetchAPI(`/api/v2/runs/${runId}/governance/promote`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateGovernancePolicyStatus(
  policyId: string,
  body: { status: "active" | "inactive" | "superseded" | "waived"; reason?: string; supersedes_policy_id?: string; waiver_note?: string },
): Promise<{ policy: GovernancePolicy }> {
  return fetchAPI(`/api/v2/governance/policies/${policyId}/status`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getFailureKnowledge(options?: {
  task_type?: string;
  project_id?: string;
  error_category?: string;
  include_resolved?: boolean;
  limit?: number;
}): Promise<FailureKnowledgeResponse> {
  const params = new URLSearchParams();
  if (options?.task_type) params.set("task_type", options.task_type);
  if (options?.project_id) params.set("project_id", options.project_id);
  if (options?.error_category) params.set("error_category", options.error_category);
  if (options?.include_resolved) params.set("include_resolved", "true");
  params.set("limit", String(options?.limit ?? 50));
  return fetchAPI(`/api/v2/failure-knowledge?${params.toString()}`);
}

export function resolveFailureKnowledge(body: {
  error_signature: string;
  resolution_approach?: string;
}): Promise<{ status: string; error_signature: string; resolution_approach: string }> {
  return fetchAPI("/api/v2/failure-knowledge/resolve", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function swapRunCandidate(
  runId: string,
  slotId: string,
  candidateComponentId: string,
  reason?: string,
): Promise<{ packet: ApplicationPacket; pair_id: string }> {
  return fetchAPI(`/api/v2/runs/${runId}/slots/${slotId}/swap-candidate`, {
    method: "POST",
    body: JSON.stringify({
      candidate_component_id: candidateComponentId,
      reason,
    }),
  });
}

export function pauseRunSlot(runId: string, slotId: string): Promise<{ run_id: string; slot_id: string; status: string }> {
  return fetchAPI(`/api/v2/runs/${runId}/slots/${slotId}/pause`, {
    method: "POST",
  });
}

export function resumeRunSlot(runId: string, slotId: string): Promise<{ run_id: string; slot_id: string; status: string }> {
  return fetchAPI(`/api/v2/runs/${runId}/slots/${slotId}/resume`, {
    method: "POST",
  });
}

export function reverifyRunSlot(runId: string, slotId: string): Promise<{ run_id: string; slot_id: string; status: string }> {
  return fetchAPI(`/api/v2/runs/${runId}/slots/${slotId}/reverify`, {
    method: "POST",
  });
}

export function blockRunSlot(runId: string, slotId: string, reason?: string): Promise<{ run_id: string; slot_id: string; status: string; reason?: string }> {
  return fetchAPI(`/api/v2/runs/${runId}/slots/${slotId}/block`, {
    method: "POST",
    body: JSON.stringify(reason ? { reason } : {}),
  });
}

export function unblockRunSlot(runId: string, slotId: string, reason?: string): Promise<{ run_id: string; slot_id: string; status: string }> {
  return fetchAPI(`/api/v2/runs/${runId}/slots/${slotId}/unblock`, {
    method: "POST",
    body: JSON.stringify(reason ? { reason } : {}),
  });
}

export function banRunFamily(runId: string, familyBarcode: string, reason?: string): Promise<{ run_id: string; family_barcode: string; status: string; reason?: string }> {
  return fetchAPI(`/api/v2/runs/${runId}/families/${encodeURIComponent(familyBarcode)}/ban`, {
    method: "POST",
    body: JSON.stringify(reason ? { reason } : {}),
  });
}

export function unbanRunFamily(runId: string, familyBarcode: string, reason?: string): Promise<{ run_id: string; family_barcode: string; status: string }> {
  return fetchAPI(`/api/v2/runs/${runId}/families/${encodeURIComponent(familyBarcode)}/unban`, {
    method: "POST",
    body: JSON.stringify(reason ? { reason } : {}),
  });
}

// ---------------------------------------------------------------------------
// Gaps
// ---------------------------------------------------------------------------

export interface CoverageMatrix {
  matrix: Record<string, Record<string, number>>;
  sparse_cells: Array<[string, string]>;
  empty_cells: Array<[string, string]>;
  total_by_category: Record<string, number>;
  total_by_brain: Record<string, number>;
}

export function getGapsMatrix(): Promise<CoverageMatrix> {
  return fetchAPI("/api/gaps/matrix");
}

export interface GapCluster {
  theme: string;
  count: number;
  sample_titles: string[];
  suggested_name: string;
  methodology_ids: string[];
}

export function getGapsDiscover(): Promise<{ clusters: GapCluster[] }> {
  return fetchAPI("/api/gaps/discover");
}

export interface GapTrendSnapshot {
  id: string;
  total_methodologies: number;
  sparse_cells: Array<[string, string]>;
  created_at: string;
}

export function getGapsTrend(): Promise<{ summary: string; snapshots: GapTrendSnapshot[] }> {
  return fetchAPI("/api/gaps/trend");
}

// ---------------------------------------------------------------------------
// Attribution
// ---------------------------------------------------------------------------

export interface AttributionMethodologyEntry {
  methodology_id: string;
  title: string;
  lifecycle: string;
  retrieved: number;
  applied: number;
  success: number;
  failure: number;
  applied_rate: number;
  success_rate: number;
  avg_quality: number | null;
  avg_relevance: number | null;
}

export interface AttributionProof {
  funnel: {
    total_retrieved: number;
    total_applied: number;
    total_success: number;
    total_failure: number;
    applied_rate: number;
    success_rate: number;
    overall_conversion: number;
  };
  methodology_count: number;
  never_applied_count: number;
  per_methodology: AttributionMethodologyEntry[];
  never_applied: AttributionMethodologyEntry[];
}

export function getAttributionProof(): Promise<AttributionProof> {
  return fetchAPI("/api/attribution/proof");
}

// ---------------------------------------------------------------------------
// Evolution
// ---------------------------------------------------------------------------

export function getABTests(): Promise<{ tests: Record<string, unknown>[] }> {
  return fetchAPI("/api/evolution/ab-tests");
}

export interface FitnessTrajectoryEntry {
  fitness: number;
  vector: Record<string, number>;
  event: string;
  timestamp: string;
}

export function getEvolutionFitness(methodologyId: string): Promise<{ methodology_id: string; trajectory: FitnessTrajectoryEntry[] }> {
  return fetchAPI(`/api/evolution/fitness/${methodologyId}`);
}

export interface RoutingEntry {
  agent_id: string;
  task_type: string;
  wins: number;
  losses: number;
  total: number;
  avg_quality: number;
  avg_cost: number;
}

export function getRouting(): Promise<{ routing: RoutingEntry[] }> {
  return fetchAPI("/api/evolution/routing");
}

export interface BanditArm {
  methodology_id: string;
  task_type: string;
  successes: number;
  failures: number;
  total: number;
  win_rate: number;
  last_updated: string;
}

export function getBanditArms(taskType?: string): Promise<{ arms: BanditArm[]; task_types: string[] }> {
  const params = taskType ? `?task_type=${encodeURIComponent(taskType)}` : "";
  return fetchAPI(`/api/evolution/bandit${params}`);
}

// ---------------------------------------------------------------------------
// Costs
// ---------------------------------------------------------------------------

export interface CostSummary {
  mining_costs: Array<{
    model_used: string;
    agent_id: string;
    brain: string;
    runs: number;
    total_tokens: number;
    successes: number;
    avg_duration: number;
  }>;
  agent_budgets: Record<string, { max_budget_usd: number; model: string | null; mode: string }>;
}

export function getCostsSummary(): Promise<CostSummary> {
  return fetchAPI("/api/costs/summary");
}

export function getCostsByAgent(): Promise<{
  mining: Array<Record<string, unknown>>;
  task_execution: Array<Record<string, unknown>>;
}> {
  return fetchAPI("/api/costs/by-agent");
}

// ---------------------------------------------------------------------------
// Federation
// ---------------------------------------------------------------------------

export interface TopologyNode {
  id: string;
  type: "primary" | "sibling";
  methodology_count: number;
  db_exists: boolean;
  description?: string;
}

export interface TopologyEdge {
  source: string;
  target: string;
  type: string;
}

export function getFederationTopology(): Promise<{
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  total_methodologies: number;
}> {
  return fetchAPI("/api/federation/topology");
}

export interface CrossLanguageReport {
  query: string;
  universal_patterns: Array<{
    pattern_name: string;
    implementations: Record<string, string>;
    evidence_ids: string[];
    domain_overlap: number;
  }>;
  unique_innovations: Array<{
    brain: string;
    methodology_id: string;
    problem_summary: string;
    why_unique: string;
  }>;
  transferable_insights: Array<{
    source_brain: string;
    target_brain: string;
    rationale: string;
  }>;
  metrics: Record<string, unknown>;
}

export function analyzeFederation(query: string): Promise<CrossLanguageReport> {
  return fetchAPI("/api/federation/analyze", {
    method: "POST",
    body: JSON.stringify({ query }),
  });
}

export interface FederationPacketResult {
  component_id: string;
  title: string;
  component_type: string;
  abstract_jobs: string[];
  language?: string | null;
  repo: string;
  file_path: string;
  symbol?: string | null;
  family_barcode: string;
  provenance_precision: ProvenancePrecision;
  source_instance: string;
  match_type: "direct_fit" | "pattern_transfer";
  match_score: number;
  relevance_score: number;
}

export interface FederationPacketResponse {
  query: string;
  task_archetype: string;
  archetype_confidence: number;
  slot: SlotSpec | null;
  results: FederationPacketResult[];
}

export function getFederationPackets(
  query: string,
  options?: { slotName?: string; language?: string; limit?: number }
): Promise<FederationPacketResponse> {
  const params = new URLSearchParams({ q: query });
  if (options?.slotName) params.set("slot_name", options.slotName);
  if (options?.language) params.set("language", options.language);
  if (options?.limit) params.set("limit", String(options.limit));
  return fetchAPI(`/api/v2/federation/packets?${params.toString()}`);
}

export interface SpecialistPacketExchangeResponse {
  exchange_id: string;
  task_text: string;
  selected_agent: string;
  inferred_task_type: string;
  preferred_agent?: string | null;
  routing_method: string;
  task_archetype: string;
  archetype_confidence: number;
  slot: SlotSpec | null;
  results: FederationPacketResult[];
  review_required: boolean;
}

export function requestSpecialistPacketExchange(input: {
  taskText: string;
  slotName?: string;
  preferredAgent?: "claude" | "codex" | "gemini" | "grok";
  targetLanguage?: string;
  limit?: number;
}): Promise<SpecialistPacketExchangeResponse> {
  return fetchAPI("/api/v2/federation/specialist-packet", {
    method: "POST",
    body: JSON.stringify({
      task_text: input.taskText,
      slot_name: input.slotName,
      preferred_agent: input.preferredAgent,
      target_language: input.targetLanguage,
      limit: input.limit ?? 5,
    }),
  });
}

// ---------------------------------------------------------------------------
// Mining
// ---------------------------------------------------------------------------

export function startMining(path: string, brain?: string): Promise<{ job_id: string; status: string }> {
  return fetchAPI("/api/mine", {
    method: "POST",
    body: JSON.stringify({ path, brain }),
  });
}

export function getMiningStatus(jobId: string): Promise<Record<string, unknown>> {
  return fetchAPI(`/api/mine/${jobId}`);
}

export function getRecentMining(): Promise<{ outcomes: Array<Record<string, unknown>> }> {
  return fetchAPI("/api/mine/recent/list");
}

// ---------------------------------------------------------------------------
// Brain Intelligence (Forge)
// ---------------------------------------------------------------------------

export interface BrainGraphNode {
  id: string;
  name: string;
  methodology_count: number;
  categories: Record<string, number>;
  top_methodologies: Array<{ title: string; category: string; fitness: number }>;
  fitness_summary: { avg: number; min: number; max: number };
  is_primary: boolean;
  db_exists?: boolean;
}

export interface BrainGraphEdge {
  source: string;
  target: string;
  type: string;
}

export function getBrainGraph(): Promise<{ nodes: BrainGraphNode[]; edges: BrainGraphEdge[] }> {
  return fetchAPI("/api/brain/graph");
}

export interface BanditArmState {
  methodology_id: string;
  title: string;
  alpha: number;
  beta: number;
  mean: number;
  ci_low: number;
  ci_high: number;
  successes: number;
  failures: number;
  total: number;
  task_types: string[];
}

export function getBrainBanditState(taskType?: string): Promise<{ arms: BanditArmState[]; count: number }> {
  const params = taskType ? `?task_type=${encodeURIComponent(taskType)}` : "";
  return fetchAPI(`/api/brain/bandit-state${params}`);
}

export interface CapabilityBoundaries {
  hard_tasks: Array<{ task_type: string; agents_tried: number; avg_failure_rate: number }>;
  failing_methodologies: Array<{ methodology_id: string; title: string; category: string | null; failures: number }>;
  coverage_gaps: Array<{ category: string; brain?: string; count?: number }>;
}

export function getCapabilityBoundaries(): Promise<CapabilityBoundaries> {
  return fetchAPI("/api/brain/capability-boundaries");
}

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

export function getConfig(): Promise<Record<string, unknown>> {
  return fetchAPI("/api/config");
}

export function patchConfig(section: string, update: Record<string, unknown>): Promise<Record<string, unknown>> {
  return fetchAPI(`/api/config/${section}`, {
    method: "PATCH",
    body: JSON.stringify(update),
  });
}

export function reloadConfig(): Promise<{ status: string }> {
  return fetchAPI("/api/config/reload", { method: "POST" });
}

// ---------------------------------------------------------------------------
// Prompts
// ---------------------------------------------------------------------------

export interface PromptInfo {
  name: string;
  path: string;
  size_bytes: number;
  line_count: number;
}

export function getPrompts(): Promise<{ prompts: PromptInfo[] }> {
  return fetchAPI("/api/prompts");
}

export function getPrompt(name: string): Promise<{ name: string; content: string; path: string }> {
  return fetchAPI(`/api/prompts/${encodeURIComponent(name)}`);
}

export function createPrompt(name: string, content: string, forkFrom?: string): Promise<Record<string, unknown>> {
  const body: Record<string, string> = { name, content };
  if (forkFrom) body.fork_from = forkFrom;
  return fetchAPI("/api/prompts", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// ---------------------------------------------------------------------------
// Ganglia (Brain CRUD)
// ---------------------------------------------------------------------------

export function createGanglion(name: string, description?: string, promptTemplate?: string): Promise<Record<string, unknown>> {
  return fetchAPI("/api/ganglia", {
    method: "POST",
    body: JSON.stringify({ name, description, prompt_template: promptTemplate }),
  });
}

export function deleteGanglion(name: string): Promise<Record<string, unknown>> {
  return fetchAPI(`/api/ganglia/${encodeURIComponent(name)}`, { method: "DELETE" });
}

export function previewRepo(path: string): Promise<Record<string, unknown>> {
  return fetchAPI("/api/forge/preview-repo", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

export function validateForge(brainName: string, agentIds: string[], repoPaths: string[]): Promise<Record<string, unknown>> {
  return fetchAPI("/api/forge/validate", {
    method: "POST",
    body: JSON.stringify({ brain_name: brainName, agent_ids: agentIds, repo_paths: repoPaths }),
  });
}

// ---------------------------------------------------------------------------
// Forge Execution (Phase 5)
// ---------------------------------------------------------------------------

export function analyzeIntent(intent: string, repoPath?: string): Promise<Record<string, unknown>> {
  return fetchAPI("/api/forge/analyze-intent", {
    method: "POST",
    body: JSON.stringify({ intent, repo_path: repoPath }),
  });
}

export function executeForge(steps: Array<Record<string, unknown>>): Promise<{ job_id: string; status: string }> {
  return fetchAPI("/api/forge/execute", {
    method: "POST",
    body: JSON.stringify({ steps }),
  });
}

export function getForgeJobStatus(jobId: string): Promise<Record<string, unknown>> {
  return fetchAPI(`/api/forge/execute/${jobId}`);
}

export function generateScript(operations: string[]): Promise<{ script: string; filename: string; description: string }> {
  return fetchAPI("/api/forge/generate-script", {
    method: "POST",
    body: JSON.stringify({ operations }),
  });
}

// ---------------------------------------------------------------------------
// Playground — Task Execution (MicroClaw)
// ---------------------------------------------------------------------------

export interface GateResult {
  check: string;
  status: "pass" | "fail";
  detail: string;
}

export interface StepEvent {
  step: string;
  detail: string;
  timestamp: string;
}

export interface CorrectionEntry {
  attempt_number: number;
  violations: Array<{ check: string; detail: string }>;
  test_output: string;
  code_diff: string;
  failing_test_content: string;
  quality_score: number;
  failure_reason: string | null;
}

export interface ExecutionResult {
  cycle_level: string;
  task_id: string | null;
  project_id: string | null;
  agent_id: string | null;
  success: boolean;
  tokens_used: number;
  cost_usd: number;
  duration_seconds: number;
  outcome: {
    files_changed: string[];
    test_output: string;
    tests_passed: boolean;
    diff: string;
    approach_summary: string;
    model_used: string | null;
    agent_id: string | null;
    failure_reason: string | null;
    failure_detail: string | null;
    tokens_used: number;
    cost_usd: number;
    duration_seconds: number;
  };
  verification: {
    approved: boolean;
    violations: Array<{ check: string; detail: string }>;
    recommendations: string[];
    quality_score: number | null;
    tests_before: number | null;
    tests_after: number | null;
    test_output: string;
    drift_cosine_score: number | null;
  } | null;
}

export interface SessionStatus {
  session_id: string;
  status: "starting" | "running" | "completed" | "failed" | "error";
  task_description: string;
  steps: StepEvent[];
  gates: GateResult[];
  corrections_count: number;
  result: ExecutionResult | null;
  error: string | null;
  created_at: string;
}

export interface SessionCorrections {
  session_id: string;
  corrections: CorrectionEntry[];
  total_attempts: number;
}

export function executeTask(
  taskDescription: string,
  projectId?: string,
  workspaceDir?: string,
): Promise<{ session_id: string; status: string }> {
  return fetchAPI("/api/execute", {
    method: "POST",
    body: JSON.stringify({
      task_description: taskDescription,
      project_id: projectId,
      workspace_dir: workspaceDir,
    }),
  });
}

export function getSessionStatus(sessionId: string): Promise<SessionStatus> {
  return fetchAPI(`/api/sessions/${sessionId}`);
}

export function getSessionCorrections(sessionId: string): Promise<SessionCorrections> {
  return fetchAPI(`/api/sessions/${sessionId}/corrections`);
}
