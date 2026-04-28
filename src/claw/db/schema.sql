-- CLAW — Database Schema
-- SQLite with WAL mode, FTS5, and sqlite-vec

-- 1. PROJECTS
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    repo_path TEXT NOT NULL,
    tech_stack TEXT NOT NULL DEFAULT '{}',       -- JSON string
    project_rules TEXT,
    banned_dependencies TEXT NOT NULL DEFAULT '[]', -- JSON array string
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- 2. TASKS (Work Queue)
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING','EVALUATING','PLANNING','DISPATCHED','CODING','REVIEWING','STUCK','DONE')),
    priority INTEGER NOT NULL DEFAULT 0,
    task_type TEXT,
    recommended_agent TEXT,
    assigned_agent TEXT,
    action_template_id TEXT REFERENCES action_templates(id) ON DELETE SET NULL,
    execution_steps TEXT NOT NULL DEFAULT '[]',       -- JSON array string
    acceptance_checks TEXT NOT NULL DEFAULT '[]',     -- JSON array string
    context_snapshot_id TEXT,
    attempt_count INTEGER DEFAULT 0,
    escalation_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(project_id, priority DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_action_template ON tasks(action_template_id);

-- 2b. ACTION_TEMPLATES (Reusable executable runbooks)
CREATE TABLE IF NOT EXISTS action_templates (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    problem_pattern TEXT NOT NULL,
    execution_steps TEXT NOT NULL DEFAULT '[]',      -- JSON array string
    acceptance_checks TEXT NOT NULL DEFAULT '[]',    -- JSON array string
    rollback_steps TEXT NOT NULL DEFAULT '[]',       -- JSON array string
    preconditions TEXT NOT NULL DEFAULT '[]',        -- JSON array string
    source_methodology_id TEXT REFERENCES methodologies(id) ON DELETE SET NULL,
    source_repo TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_action_templates_repo ON action_templates(source_repo);
CREATE INDEX IF NOT EXISTS idx_action_templates_confidence ON action_templates(confidence DESC);

-- 3. HYPOTHESIS_LOG (Trial & Error Memory)
CREATE TABLE IF NOT EXISTS hypothesis_log (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL,
    approach_summary TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'FAILURE'
        CHECK (outcome IN ('SUCCESS','FAILURE')),
    error_signature TEXT,
    error_full TEXT,
    files_changed TEXT NOT NULL DEFAULT '[]',     -- JSON array string
    duration_seconds REAL,
    model_used TEXT,
    agent_id TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(task_id, attempt_number)
);
CREATE INDEX IF NOT EXISTS idx_hyp_task ON hypothesis_log(task_id);
CREATE INDEX IF NOT EXISTS idx_hyp_error_sig ON hypothesis_log(error_signature);

-- 3b. METHODOLOGY_USAGE_LOG (Attribution of retrieved/used knowledge)
CREATE TABLE IF NOT EXISTS methodology_usage_log (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    methodology_id TEXT NOT NULL REFERENCES methodologies(id) ON DELETE CASCADE,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    stage TEXT NOT NULL DEFAULT 'retrieved_presented',
    agent_id TEXT,
    success INTEGER,
    expectation_match_score REAL,
    quality_score REAL,
    relevance_score REAL,
    notes TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_meth_usage_task ON methodology_usage_log(task_id);
CREATE INDEX IF NOT EXISTS idx_meth_usage_methodology ON methodology_usage_log(methodology_id);
CREATE INDEX IF NOT EXISTS idx_meth_usage_stage ON methodology_usage_log(stage);

-- 4. METHODOLOGIES (Long-Term Memory / RAG)
CREATE TABLE IF NOT EXISTS methodologies (
    id TEXT PRIMARY KEY,
    problem_description TEXT NOT NULL,
    solution_code TEXT NOT NULL,
    methodology_notes TEXT,
    source_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    tags TEXT NOT NULL DEFAULT '[]',               -- JSON array string
    language TEXT,
    scope TEXT NOT NULL DEFAULT 'project',
    methodology_type TEXT,
    files_affected TEXT NOT NULL DEFAULT '[]',      -- JSON array string
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    -- MEE lifecycle fields
    lifecycle_state TEXT NOT NULL DEFAULT 'viable'
        CHECK (lifecycle_state IN ('embryonic','viable','thriving','declining','dormant','dead')),
    retrieval_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_retrieved_at TEXT,
    generation INTEGER NOT NULL DEFAULT 0,
    fitness_vector TEXT NOT NULL DEFAULT '{}',      -- JSON string
    parent_ids TEXT NOT NULL DEFAULT '[]',          -- JSON array string
    superseded_by TEXT,
    prism_data TEXT,                                  -- JSON: PrismEmbedding (nullable)
    capability_data TEXT,                              -- JSON: CapabilityData (nullable)
    novelty_score REAL,                                -- 0.0-1.0: how different from existing KB
    potential_score REAL,                               -- 0.0-1.0: future composability/value
    accuracy_contract TEXT NOT NULL DEFAULT 'soft',     -- hard|frontier|scenario|soft
    concept_type TEXT,                                  -- invariant|failure_mode|protocol|novel_abstraction|decision_rule|bridge
    use_immediately_as TEXT NOT NULL DEFAULT '[]',      -- JSON array: operational directives
    tension_questions TEXT NOT NULL DEFAULT '[]',       -- JSON array: epistemic tension questions
    triage_score REAL                                   -- 0.0-1.0: 7-dim composite ingest triage score
);
CREATE INDEX IF NOT EXISTS idx_meth_scope ON methodologies(scope);
CREATE INDEX IF NOT EXISTS idx_meth_lifecycle ON methodologies(lifecycle_state);
CREATE INDEX IF NOT EXISTS idx_meth_novelty ON methodologies(novelty_score DESC);

-- Methodology embeddings (sqlite-vec virtual table)
-- Stores 384-dimensional float32 vectors for semantic search
-- Queried as: SELECT rowid, distance FROM methodology_embeddings WHERE embedding MATCH ?
CREATE VIRTUAL TABLE IF NOT EXISTS methodology_embeddings USING vec0(
    methodology_id TEXT PRIMARY KEY,
    embedding float[384]
);

-- Methodology full-text search (FTS5)
CREATE VIRTUAL TABLE IF NOT EXISTS methodology_fts USING fts5(
    methodology_id UNINDEXED,
    problem_description,
    methodology_notes,
    tags
);

-- 5. PEER_REVIEWS (Escalation Diagnoses)
CREATE TABLE IF NOT EXISTS peer_reviews (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    model_used TEXT NOT NULL,
    diagnosis TEXT NOT NULL,
    recommended_approach TEXT,
    reasoning TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_peer_task ON peer_reviews(task_id);

-- 6. CONTEXT_SNAPSHOTS (Checkpoint/Rewind State)
CREATE TABLE IF NOT EXISTS context_snapshots (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL,
    git_ref TEXT NOT NULL,
    file_manifest TEXT,                            -- JSON string
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_snap_task ON context_snapshots(task_id);

-- 7. METHODOLOGY_LINKS (Stigmergic co-retrieval)
CREATE TABLE IF NOT EXISTS methodology_links (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES methodologies(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES methodologies(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL DEFAULT 'co_retrieval',
    strength REAL NOT NULL DEFAULT 1.0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(source_id, target_id, link_type)
);
CREATE INDEX IF NOT EXISTS idx_meth_links_source ON methodology_links(source_id);
CREATE INDEX IF NOT EXISTS idx_meth_links_target ON methodology_links(target_id);

-- 8. TOKEN_COSTS (Per-call LLM cost tracking)
CREATE TABLE IF NOT EXISTS token_costs (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    run_id TEXT,
    agent_role TEXT NOT NULL DEFAULT '',
    agent_id TEXT,
    model_used TEXT NOT NULL DEFAULT '',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_token_costs_task ON token_costs(task_id);
CREATE INDEX IF NOT EXISTS idx_token_costs_agent ON token_costs(agent_id);
CREATE INDEX IF NOT EXISTS idx_token_costs_created ON token_costs(created_at DESC);

-- =========================================================================
-- CLAW-specific tables (not in ralfed)
-- =========================================================================

-- 9. AGENT_SCORES (Bayesian routing scores per task_type + agent)
CREATE TABLE IF NOT EXISTS agent_scores (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    successes INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    total_attempts INTEGER NOT NULL DEFAULT 0,
    avg_duration_seconds REAL NOT NULL DEFAULT 0.0,
    avg_quality_score REAL NOT NULL DEFAULT 0.0,
    avg_cost_usd REAL NOT NULL DEFAULT 0.0,
    last_used_at TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(agent_id, task_type)
);
CREATE INDEX IF NOT EXISTS idx_agent_scores_agent ON agent_scores(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_scores_type ON agent_scores(task_type);

-- 10. PROMPT_VARIANTS (A/B testing for prompt evolution)
CREATE TABLE IF NOT EXISTS prompt_variants (
    id TEXT PRIMARY KEY,
    prompt_name TEXT NOT NULL,
    variant_label TEXT NOT NULL DEFAULT 'control',
    content TEXT NOT NULL,
    agent_id TEXT,
    is_active INTEGER NOT NULL DEFAULT 0,
    sample_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    avg_quality_score REAL NOT NULL DEFAULT 0.0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(prompt_name, variant_label, agent_id)
);

-- 11. CAPABILITY_BOUNDARIES (Tasks that all agents fail)
CREATE TABLE IF NOT EXISTS capability_boundaries (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    task_description TEXT NOT NULL,
    agents_attempted TEXT NOT NULL DEFAULT '[]',    -- JSON array string
    failure_signatures TEXT NOT NULL DEFAULT '[]',  -- JSON array string
    discovered_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    last_retested_at TEXT,
    retest_result TEXT,
    escalated_to_human INTEGER NOT NULL DEFAULT 0,
    resolved INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cap_bounds_type ON capability_boundaries(task_type);

-- 12. FLEET_REPOS (Fleet repo tracking)
CREATE TABLE IF NOT EXISTS fleet_repos (
    id TEXT PRIMARY KEY,
    repo_path TEXT NOT NULL UNIQUE,
    repo_name TEXT NOT NULL,
    priority REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','evaluating','enhancing','completed','failed','skipped')),
    enhancement_branch TEXT,
    last_evaluated_at TEXT,
    evaluation_score REAL,
    budget_allocated_usd REAL NOT NULL DEFAULT 0.0,
    budget_used_usd REAL NOT NULL DEFAULT 0.0,
    tasks_created INTEGER NOT NULL DEFAULT 0,
    tasks_completed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_fleet_repos_status ON fleet_repos(status);
CREATE INDEX IF NOT EXISTS idx_fleet_repos_priority ON fleet_repos(priority DESC);

-- 13. EPISODES (Episodic memory — session event log)
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_data TEXT NOT NULL DEFAULT '{}',          -- JSON string
    agent_id TEXT,
    task_id TEXT,
    cycle_level TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_episodes_project ON episodes(project_id);
CREATE INDEX IF NOT EXISTS idx_episodes_session ON episodes(session_id);
CREATE INDEX IF NOT EXISTS idx_episodes_type ON episodes(event_type);
CREATE INDEX IF NOT EXISTS idx_episodes_created ON episodes(created_at DESC);

-- 14. SYNERGY_EXPLORATION_LOG (Tracks explored capability pairs — SMART dedup)
CREATE TABLE IF NOT EXISTS synergy_exploration_log (
    id TEXT PRIMARY KEY,
    cap_a_id TEXT NOT NULL,
    cap_b_id TEXT NOT NULL,
    explored_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    result TEXT NOT NULL DEFAULT 'pending'
        CHECK (result IN ('pending','synergy','no_match','error','stale')),
    synergy_score REAL,
    synergy_type TEXT,
    edge_id TEXT,
    exploration_method TEXT,
    details TEXT NOT NULL DEFAULT '{}',
    UNIQUE(cap_a_id, cap_b_id)
);
CREATE INDEX IF NOT EXISTS idx_synergy_log_cap_a ON synergy_exploration_log(cap_a_id);
CREATE INDEX IF NOT EXISTS idx_synergy_log_cap_b ON synergy_exploration_log(cap_b_id);
CREATE INDEX IF NOT EXISTS idx_synergy_log_result ON synergy_exploration_log(result);

-- 15. GOVERNANCE_LOG (Audit trail for governance actions)
CREATE TABLE IF NOT EXISTS governance_log (
    id TEXT PRIMARY KEY,
    action_type TEXT NOT NULL,
    methodology_id TEXT,
    details TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_governance_log_action ON governance_log(action_type);
CREATE INDEX IF NOT EXISTS idx_governance_log_created ON governance_log(created_at DESC);

-- 16. PULSE_DISCOVERIES (X-discovered repos via CAM-PULSE)
CREATE TABLE IF NOT EXISTS pulse_discoveries (
    id TEXT PRIMARY KEY,
    github_url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    x_post_url TEXT,
    x_post_text TEXT,
    x_author_handle TEXT,
    discovered_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    novelty_score REAL,
    status TEXT NOT NULL DEFAULT 'discovered'
        CHECK (status IN ('discovered','cloning','scanning','mounting','mining','assimilated','failed','skipped','queued_enhance','refreshing')),
    scan_id TEXT,
    keywords_matched TEXT NOT NULL DEFAULT '[]',
    mine_result TEXT,
    methodology_ids TEXT NOT NULL DEFAULT '[]',
    error_detail TEXT,
    last_checked_at TEXT,
    last_pushed_at TEXT,
    head_sha_at_mine TEXT,
    etag TEXT,
    stars_at_mine INTEGER,
    latest_release_tag TEXT,
    freshness_status TEXT DEFAULT 'unknown',
    source_kind TEXT DEFAULT 'github',
    size_at_mine INTEGER,
    license_type TEXT,
    UNIQUE(canonical_url)
);
CREATE INDEX IF NOT EXISTS idx_pulse_disc_status ON pulse_discoveries(status);
CREATE INDEX IF NOT EXISTS idx_pulse_disc_novelty ON pulse_discoveries(novelty_score DESC);
CREATE INDEX IF NOT EXISTS idx_pulse_disc_discovered ON pulse_discoveries(discovered_at DESC);

-- 17. PULSE_SCAN_LOG (Scan session tracking for CAM-PULSE)
CREATE TABLE IF NOT EXISTS pulse_scan_log (
    id TEXT PRIMARY KEY,
    scan_type TEXT NOT NULL DEFAULT 'x_search',
    keywords TEXT NOT NULL DEFAULT '[]',
    started_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at TEXT,
    repos_discovered INTEGER NOT NULL DEFAULT 0,
    repos_novel INTEGER NOT NULL DEFAULT 0,
    repos_assimilated INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    error_detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_pulse_scan_started ON pulse_scan_log(started_at DESC);

-- 18. METHODOLOGY_FITNESS_LOG (Fitness score history for time-series analysis)
CREATE TABLE IF NOT EXISTS methodology_fitness_log (
    id TEXT PRIMARY KEY,
    methodology_id TEXT NOT NULL REFERENCES methodologies(id) ON DELETE CASCADE,
    fitness_total REAL NOT NULL,
    fitness_vector TEXT NOT NULL DEFAULT '{}',
    trigger_event TEXT NOT NULL DEFAULT 'recompute',
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_fitness_log_meth ON methodology_fitness_log(methodology_id);
CREATE INDEX IF NOT EXISTS idx_fitness_log_created ON methodology_fitness_log(created_at DESC);

-- 18.5 COMMUNITY_IMPORTS (Quarantine staging for community knowledge)
CREATE TABLE IF NOT EXISTS community_imports (
    id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    contributor_instance_id TEXT NOT NULL,
    contributor_alias TEXT,
    origin_id TEXT,
    status TEXT DEFAULT 'quarantined'
        CHECK (status IN ('quarantined','approved','rejected')),
    gate_results TEXT NOT NULL DEFAULT '{}',
    sanitized_record TEXT NOT NULL,
    imported_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    approved_at TEXT,
    UNIQUE(content_hash)
);
CREATE INDEX IF NOT EXISTS idx_community_imports_status ON community_imports(status);
CREATE INDEX IF NOT EXISTS idx_community_imports_contributor ON community_imports(contributor_instance_id);

-- 18.6 COMMUNITY_IMPORT_AUDIT (Audit trail for community imports)
CREATE TABLE IF NOT EXISTS community_import_audit (
    id TEXT PRIMARY KEY,
    contributor_instance_id TEXT,
    action TEXT NOT NULL,
    gate_name TEXT,
    detail TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_community_audit_action ON community_import_audit(action);

-- 19. AB_QUALITY_SAMPLES (Per-sample multi-dimensional quality metrics for A/B testing)
CREATE TABLE IF NOT EXISTS ab_quality_samples (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    variant_label TEXT NOT NULL,
    agent_id TEXT,
    d_functional_correctness REAL NOT NULL DEFAULT 0.0,
    d_structural_compliance REAL NOT NULL DEFAULT 0.0,
    d_intent_alignment REAL NOT NULL DEFAULT 0.0,
    d_correction_efficiency REAL NOT NULL DEFAULT 0.0,
    d_token_economy REAL NOT NULL DEFAULT 0.0,
    d_expectation_match REAL NOT NULL DEFAULT 0.0,
    composite_score REAL NOT NULL DEFAULT 0.0,
    correction_attempts INTEGER NOT NULL DEFAULT 1,
    escalation_tier INTEGER NOT NULL DEFAULT 0,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    duration_seconds REAL NOT NULL DEFAULT 0.0,
    success INTEGER NOT NULL DEFAULT 0,
    error_category TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_ab_samples_project ON ab_quality_samples(project_id);
CREATE INDEX IF NOT EXISTS idx_ab_samples_variant ON ab_quality_samples(variant_label);
CREATE INDEX IF NOT EXISTS idx_ab_samples_task ON ab_quality_samples(task_id);

-- 20. METHODOLOGY_BANDIT_OUTCOMES (RL bandit stats per methodology × task_type)
CREATE TABLE IF NOT EXISTS methodology_bandit_outcomes (
    methodology_id TEXT NOT NULL REFERENCES methodologies(id) ON DELETE CASCADE,
    task_type TEXT NOT NULL,
    successes INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    last_updated TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (methodology_id, task_type)
);
CREATE INDEX IF NOT EXISTS idx_bandit_task_type ON methodology_bandit_outcomes(task_type);

-- 21. MINING_OUTCOMES (RL tracking for mining model selection)
CREATE TABLE IF NOT EXISTS mining_outcomes (
    id TEXT PRIMARY KEY,
    model_used TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    brain TEXT NOT NULL DEFAULT 'python',
    repo_name TEXT NOT NULL,
    repo_size_bytes INTEGER NOT NULL DEFAULT 0,
    prompt_tokens_estimated INTEGER NOT NULL DEFAULT 0,
    strategy TEXT NOT NULL DEFAULT 'primary',
    success INTEGER NOT NULL DEFAULT 0,
    findings_count INTEGER NOT NULL DEFAULT 0,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    duration_seconds REAL NOT NULL DEFAULT 0.0,
    error_type TEXT,
    error_detail TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_mining_outcomes_model ON mining_outcomes(model_used);
CREATE INDEX IF NOT EXISTS idx_mining_outcomes_strategy ON mining_outcomes(strategy);
CREATE INDEX IF NOT EXISTS idx_mining_outcomes_brain ON mining_outcomes(brain);
CREATE INDEX IF NOT EXISTS idx_mining_outcomes_size ON mining_outcomes(prompt_tokens_estimated);

-- 22. METHODOLOGY_CONTRADICTIONS (detected opposing methodology pairs)
CREATE TABLE IF NOT EXISTS methodology_contradictions (
    id TEXT PRIMARY KEY,
    methodology_a_id TEXT NOT NULL REFERENCES methodologies(id) ON DELETE CASCADE,
    methodology_b_id TEXT NOT NULL REFERENCES methodologies(id) ON DELETE CASCADE,
    problem_similarity REAL NOT NULL,
    solution_divergence REAL NOT NULL,
    detected_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    resolution TEXT,
    resolved_by TEXT,
    resolved_at TEXT,
    UNIQUE(methodology_a_id, methodology_b_id)
);
CREATE INDEX IF NOT EXISTS idx_contradictions_a ON methodology_contradictions(methodology_a_id);
CREATE INDEX IF NOT EXISTS idx_contradictions_b ON methodology_contradictions(methodology_b_id);

-- 23. COVERAGE_SNAPSHOTS (gap analysis periodic snapshots)
CREATE TABLE IF NOT EXISTS coverage_snapshots (
    id TEXT PRIMARY KEY,
    snapshot_data TEXT NOT NULL,
    sparse_cells TEXT NOT NULL DEFAULT '[]',
    total_methodologies INTEGER NOT NULL,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_coverage_snapshots_created
    ON coverage_snapshots(created_at DESC);

-- =========================================================================
-- CAM-SEQ additive tables
-- =========================================================================

-- 24. COMPONENT_LINEAGES (deduplicated lineage families across near-duplicate components)
CREATE TABLE IF NOT EXISTS component_lineages (
    id TEXT PRIMARY KEY,
    family_barcode TEXT NOT NULL,
    canonical_content_hash TEXT NOT NULL,
    canonical_title TEXT,
    language TEXT,
    lineage_size INTEGER NOT NULL DEFAULT 1,
    deduped_support_count INTEGER NOT NULL DEFAULT 1,
    clone_inflated INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_component_lineages_family ON component_lineages(family_barcode);
CREATE INDEX IF NOT EXISTS idx_component_lineages_hash ON component_lineages(canonical_content_hash);

-- 25. COMPONENT_CARDS (precise reusable implementation units with receipts)
CREATE TABLE IF NOT EXISTS component_cards (
    id TEXT PRIMARY KEY,
    methodology_id TEXT REFERENCES methodologies(id) ON DELETE SET NULL,
    lineage_id TEXT NOT NULL REFERENCES component_lineages(id) ON DELETE CASCADE,
    source_barcode TEXT NOT NULL UNIQUE,
    family_barcode TEXT NOT NULL,
    title TEXT NOT NULL,
    component_type TEXT NOT NULL,
    abstract_jobs_json TEXT NOT NULL DEFAULT '[]',
    repo TEXT NOT NULL,
    commit_sha TEXT,
    file_path TEXT NOT NULL,
    symbol_name TEXT,
    line_start INTEGER,
    line_end INTEGER,
    content_hash TEXT NOT NULL,
    provenance_precision TEXT NOT NULL,
    language TEXT,
    frameworks_json TEXT NOT NULL DEFAULT '[]',
    dependencies_json TEXT NOT NULL DEFAULT '[]',
    constraints_json TEXT NOT NULL DEFAULT '[]',
    inputs_json TEXT NOT NULL DEFAULT '[]',
    outputs_json TEXT NOT NULL DEFAULT '[]',
    test_evidence_json TEXT NOT NULL DEFAULT '[]',
    applicability_json TEXT NOT NULL DEFAULT '[]',
    non_applicability_json TEXT NOT NULL DEFAULT '[]',
    adaptation_notes_json TEXT NOT NULL DEFAULT '[]',
    risk_notes_json TEXT NOT NULL DEFAULT '[]',
    keywords_json TEXT NOT NULL DEFAULT '[]',
    coverage_state TEXT NOT NULL DEFAULT 'weak',
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_component_cards_family ON component_cards(family_barcode);
CREATE INDEX IF NOT EXISTS idx_component_cards_lineage ON component_cards(lineage_id);
CREATE INDEX IF NOT EXISTS idx_component_cards_repo ON component_cards(repo);
CREATE INDEX IF NOT EXISTS idx_component_cards_type ON component_cards(component_type);
CREATE INDEX IF NOT EXISTS idx_component_cards_language ON component_cards(language);

-- 26. COMPONENT_FIT (heuristic or learned fit for a component under a slot/task pattern)
CREATE TABLE IF NOT EXISTS component_fit (
    id TEXT PRIMARY KEY,
    component_id TEXT NOT NULL REFERENCES component_cards(id) ON DELETE CASCADE,
    task_archetype TEXT,
    component_type TEXT,
    slot_signature TEXT,
    fit_bucket TEXT NOT NULL,
    transfer_mode TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    confidence_basis_json TEXT NOT NULL DEFAULT '[]',
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    notes_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_component_fit_component ON component_fit(component_id);
CREATE INDEX IF NOT EXISTS idx_component_fit_archetype ON component_fit(task_archetype);
CREATE INDEX IF NOT EXISTS idx_component_fit_slot_signature ON component_fit(slot_signature);

-- 27. TASK_PLANS (durable reviewed plan records)
CREATE TABLE IF NOT EXISTS task_plans (
    id TEXT PRIMARY KEY,
    task_text TEXT NOT NULL,
    workspace_dir TEXT,
    branch TEXT,
    target_brain TEXT,
    execution_mode TEXT,
    check_commands_json TEXT NOT NULL DEFAULT '[]',
    task_archetype TEXT NOT NULL,
    archetype_confidence REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'draft',
    summary_json TEXT NOT NULL DEFAULT '{}',
    approved_slot_ids_json TEXT NOT NULL DEFAULT '[]',
    plan_json TEXT NOT NULL,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_task_plans_archetype ON task_plans(task_archetype);
CREATE INDEX IF NOT EXISTS idx_task_plans_status ON task_plans(status);

-- 28. SLOT_INSTANCES (persisted slot definitions for reviewed plans and later runs)
CREATE TABLE IF NOT EXISTS slot_instances (
    id TEXT PRIMARY KEY,
    slot_barcode TEXT NOT NULL,
    task_archetype TEXT,
    name TEXT NOT NULL,
    abstract_job TEXT NOT NULL,
    risk TEXT NOT NULL DEFAULT 'normal',
    constraints_json TEXT NOT NULL DEFAULT '[]',
    target_stack_json TEXT NOT NULL DEFAULT '[]',
    proof_expectations_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_slot_instances_barcode ON slot_instances(slot_barcode);
CREATE INDEX IF NOT EXISTS idx_slot_instances_archetype ON slot_instances(task_archetype);

-- 29. APPLICATION_PACKETS (durable packet records for plan review and reuse)
CREATE TABLE IF NOT EXISTS application_packets (
    id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    task_archetype TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    status TEXT NOT NULL,
    packet_json TEXT NOT NULL,
    selected_component_id TEXT NOT NULL REFERENCES component_cards(id) ON DELETE RESTRICT,
    review_required INTEGER NOT NULL DEFAULT 0,
    coverage_state TEXT NOT NULL DEFAULT 'weak',
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_application_packets_plan ON application_packets(plan_id);
CREATE INDEX IF NOT EXISTS idx_application_packets_slot ON application_packets(slot_id);
CREATE INDEX IF NOT EXISTS idx_application_packets_selected ON application_packets(selected_component_id);

-- 30. PAIR_EVENTS (runtime slot-to-component selection events)
CREATE TABLE IF NOT EXISTS pair_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    slot_barcode TEXT NOT NULL,
    packet_id TEXT NOT NULL REFERENCES application_packets(id) ON DELETE CASCADE,
    component_id TEXT NOT NULL REFERENCES component_cards(id) ON DELETE RESTRICT,
    source_barcode TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    confidence_basis_json TEXT NOT NULL DEFAULT '[]',
    replacement_of_pair_id TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_pair_events_run ON pair_events(run_id);
CREATE INDEX IF NOT EXISTS idx_pair_events_slot ON pair_events(slot_id);
CREATE INDEX IF NOT EXISTS idx_pair_events_packet ON pair_events(packet_id);

-- 31. LANDING_EVENTS (where packet-guided changes landed in the target repo)
CREATE TABLE IF NOT EXISTS landing_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    packet_id TEXT NOT NULL REFERENCES application_packets(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    symbol_name TEXT,
    diff_hunk_id TEXT,
    origin TEXT NOT NULL,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_landing_events_run ON landing_events(run_id);
CREATE INDEX IF NOT EXISTS idx_landing_events_slot ON landing_events(slot_id);
CREATE INDEX IF NOT EXISTS idx_landing_events_file ON landing_events(file_path);

-- 32. OUTCOME_EVENTS (sequenced proof and verification result per slot)
CREATE TABLE IF NOT EXISTS outcome_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    packet_id TEXT NOT NULL REFERENCES application_packets(id) ON DELETE CASCADE,
    success INTEGER NOT NULL,
    verifier_findings_json TEXT NOT NULL DEFAULT '[]',
    test_refs_json TEXT NOT NULL DEFAULT '[]',
    negative_memory_updates_json TEXT NOT NULL DEFAULT '[]',
    recipe_eligible INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_outcome_events_run ON outcome_events(run_id);
CREATE INDEX IF NOT EXISTS idx_outcome_events_slot ON outcome_events(slot_id);
CREATE INDEX IF NOT EXISTS idx_outcome_events_packet ON outcome_events(packet_id);

-- 33. RUN_CONNECTOMES (run-level connectome metadata)
CREATE TABLE IF NOT EXISTS run_connectomes (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    task_archetype TEXT,
    status TEXT NOT NULL,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- 34. RUN_CONNECTOME_EDGES (persisted graph edges for a run connectome)
CREATE TABLE IF NOT EXISTS run_connectome_edges (
    id TEXT PRIMARY KEY,
    connectome_id TEXT NOT NULL REFERENCES run_connectomes(id) ON DELETE CASCADE,
    source_node TEXT NOT NULL,
    target_node TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_run_connectome_edges_connectome ON run_connectome_edges(connectome_id);
CREATE INDEX IF NOT EXISTS idx_run_connectome_edges_type ON run_connectome_edges(edge_type);

-- 35. RUN_SLOT_EXECUTIONS (durable slot-level runtime state for reviewed runs)
CREATE TABLE IF NOT EXISTS run_slot_executions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    packet_id TEXT REFERENCES application_packets(id) ON DELETE SET NULL,
    selected_component_id TEXT REFERENCES component_cards(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    current_step TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_retry_detail TEXT,
    replacement_count INTEGER NOT NULL DEFAULT 0,
    blocked_wait_ms INTEGER NOT NULL DEFAULT 0,
    family_wait_ms INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(run_id, slot_id)
);
CREATE INDEX IF NOT EXISTS idx_run_slot_executions_run ON run_slot_executions(run_id);
CREATE INDEX IF NOT EXISTS idx_run_slot_executions_status ON run_slot_executions(status);

-- 36. RUN_EVENTS (durable event stream for reviewed run supervision)
CREATE TABLE IF NOT EXISTS run_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    slot_id TEXT,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_run_events_run ON run_events(run_id);
CREATE INDEX IF NOT EXISTS idx_run_events_slot ON run_events(slot_id);
CREATE INDEX IF NOT EXISTS idx_run_events_type ON run_events(event_type);

-- 37. RUN_ACTION_AUDITS (durable operator/governance actions)
CREATE TABLE IF NOT EXISTS run_action_audits (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    slot_id TEXT,
    action_type TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'operator',
    reason TEXT NOT NULL DEFAULT '',
    action_payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_run_action_audits_run ON run_action_audits(run_id);
CREATE INDEX IF NOT EXISTS idx_run_action_audits_slot ON run_action_audits(slot_id);
CREATE INDEX IF NOT EXISTS idx_run_action_audits_type ON run_action_audits(action_type);

-- 38. COMPILED_RECIPES (distilled reusable build patterns)
CREATE TABLE IF NOT EXISTS compiled_recipes (
    id TEXT PRIMARY KEY,
    task_archetype TEXT NOT NULL,
    recipe_name TEXT NOT NULL,
    recipe_json TEXT NOT NULL DEFAULT '{}',
    sample_size INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_compiled_recipes_archetype ON compiled_recipes(task_archetype);
CREATE INDEX IF NOT EXISTS idx_compiled_recipes_active ON compiled_recipes(is_active);

-- 39. MINING_MISSIONS (targeted acquisition backlog from review or evolution)
CREATE TABLE IF NOT EXISTS mining_missions (
    id TEXT PRIMARY KEY,
    run_id TEXT,
    slot_family TEXT,
    priority TEXT NOT NULL DEFAULT 'normal',
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    mission_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_mining_missions_run ON mining_missions(run_id);
CREATE INDEX IF NOT EXISTS idx_mining_missions_slot_family ON mining_missions(slot_family);

-- 40. GOVERNANCE_POLICIES (durable promoted governance memory)
CREATE TABLE IF NOT EXISTS governance_policies (
    id TEXT PRIMARY KEY,
    run_id TEXT,
    task_archetype TEXT,
    slot_id TEXT,
    family_barcode TEXT,
    policy_kind TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'active',
    reason TEXT NOT NULL DEFAULT '',
    recommendation TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    promoted_by TEXT NOT NULL DEFAULT 'operator',
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_governance_policies_kind ON governance_policies(policy_kind);
CREATE INDEX IF NOT EXISTS idx_governance_policies_archetype ON governance_policies(task_archetype);
CREATE INDEX IF NOT EXISTS idx_governance_policies_family ON governance_policies(family_barcode);
CREATE INDEX IF NOT EXISTS idx_governance_policies_status ON governance_policies(status);
CREATE INDEX IF NOT EXISTS idx_mining_missions_run ON mining_missions(run_id);
CREATE INDEX IF NOT EXISTS idx_mining_missions_status ON mining_missions(status);
