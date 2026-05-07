# CAM_CAM Post-Merge Checkpoint - 2026-05-06

## Current State

- Repository: `/Volumes/WS4TB/CCam/CAM_CAM`
- Branch: `main`
- Latest pushed commit: `f5b2d96 Move ganglion timeout setup outside timed miner`
- Current serial-evolution champion: `v4-candidate`
- Champion pointer: `instances/evolution/current_champion.json`
- Champion DB: `instances/evolution/challengers/v4-candidate/data/claw.db`
- Active evolution run: none

## Verified Merge Baseline

The CAM-Pulse defense and self-mitigation merge was committed and pushed as:

- `9744ad3 Merge CAM-Pulse defense chain into CAM_CAM`

The merge added and verified:

- failure knowledge persistence
- auto-fix rule suggestions
- correction hints
- agent rotation through `excluded_agents`
- RL escalation retry behavior
- verifier hardening
- structured-output token stripping
- workspace fallback
- serial evolution proof harness support

Full verification after the merge passed before follow-on evolution work.
Follow-on CI stabilization was also committed and pushed through `f5b2d96`.
Both GitHub workflows, `CI` and `Test Suite`, passed on that commit.

## Post-Merge Evolution Runs

### Cycle 1 - Prompt Config

- Run: `a73f5624-6d98-44ab-8fb1-5a2e23f43d89`
- Layer: `prompt_config`
- Decision: reject
- Reason: no accepted mined inputs
- Finding: CAM_CAM had no `prompt_variants` history, so the layer could run but could not ingest usable prompt/config evidence.

### Cycle 2 - Prompt Config

- Run: `80a87cc5-94d2-4669-b06b-d51163048c67`
- Layer: `prompt_config`
- Decision: reject
- Reason: score lift below threshold
- Finding: static prompt/config evidence was mined, but the gate used a neutral paired slice as primary evidence.

### Cycle 3 - Prompt Config

- Run: `a5bb3f21-b53b-4e62-aeb0-ab513774b7c9`
- Layer: `prompt_config`
- Decision: promote
- Promoted champion: `v3-candidate`
- Result: CAM_CAM can now bootstrap prompt/config evolution from local prompts and configs when no A/B history exists.

Code commit:

- `67aa764 Enable prompt config bootstrap evolution`

Verification:

- `tests/test_serial_evolution.py`: 42 passed
- full suite: 4160 passed, 23 skipped, 2 warnings

### Cycle 4 - Strategy Policy

- Run: `f4cfa035-aced-44cb-97b5-e7aeb8664879`
- Layer: `strategy_policy`
- Decision: promote
- Promoted champion: `v4-candidate`
- Result: CAM_CAM can now bootstrap strategy-policy evolution from routing config, Kelly config, eligible agent scores, and failure-policy signals.

Code commit:

- `9db0e8b Enable strategy policy bootstrap evolution`

Verification:

- `tests/test_serial_evolution.py`: 43 passed
- full suite: 4161 passed, 23 skipped, 2 warnings

### Cycle 5 - Data Feature

- Run: `72bf2d2a-6c02-40a4-8054-2d1d9a331199`
- Layer: `data_feature`
- Source: local sibling repo `CAM-Pulse`
- Decision: reject
- Reason: score lift below threshold
- Finding: the deterministic local repo summary was accepted, but it did not improve paired retrieval or task-readiness enough to promote. This is a healthy gate result, not a merge failure.

## What Is Actually Working

- CAM_CAM can register and maintain isolated champion/challenger instances.
- CAM_CAM can promote challengers automatically when layer-specific evidence passes gates.
- Prompt/config evolution works from cold start, without needing existing A/B samples.
- Strategy-policy evolution works from cold start, using local routing and failure evidence.
- Exact-batch gating still blocks weak or insufficient data-feature promotion.
- Runtime evolution artifacts are ignored by git, keeping commits focused on code and docs.

## Remaining Gaps

- Data-feature improvement from deterministic repo summaries is weak. Real gains likely require live mining into the isolated challenger DB, which can spend OpenRouter budget.
- Model-level evolution has no local evidence yet because `token_costs` is empty.
- `prompt_variants` and `ab_quality_samples` are still empty in the control DB, so future prompt A/B learning needs real task executions or seeded test samples.
- Most tasks in the control DB are still `PENDING`, so outcome-driven self-learning evidence remains limited.

## Recommended Next Actions

1. Continue the pre-merger CAM-SEQ plan from `M2` parser precision and proof gaps.
2. Run a budget-bound live data-feature mining cycle only when API spend is acceptable.
3. Generate real task outcomes so `agent_scores`, `prompt_variants`, `ab_quality_samples`, and failure knowledge become richer.
4. Keep model-layer evolution disabled until token/cost traces exist.
5. After new outcome evidence exists, rerun `strategy_policy` and `prompt_config` cycles to test whether CAM_CAM can promote based on real performance instead of bootstrap policy evidence.
6. Run the full suite after every code-level evolution improvement before committing.

## Returned Pre-Merger Plan Work

### M2 Parser Precision

- Issue found: the installed `tree_sitter_typescript` package exposes `language_typescript`, but the parser loader only looked for `language`.
- Fix: CAM_CAM now resolves the TypeScript grammar through `language_typescript` when needed.
- Follow-on fix: `.tsx` files now use the dedicated `language_tsx` grammar instead of plain TypeScript parsing.
- Follow-on fix: named `export default function` and `export default class` components are now unwrapped correctly in Tree-sitter extraction, with JavaScript fallback coverage for named default exports when Tree-sitter is unavailable.
- Follow-on fix: TypeScript/TSX `interface` and `type` declarations now ingest as `type_contract` components through Tree-sitter, with TypeScript fallback coverage when Tree-sitter is unavailable.
- Follow-on fix: JSX/TSX React wrapper declarations using `memo`, `React.memo`, and `forwardRef` now ingest as function components instead of falling back to module cards.
- Verification: `PYTHONPATH=src pytest tests/test_component_extractor.py -q` passed with `42 passed`.
- Result: real TypeScript, TSX, and JSX Tree-sitter extraction now use precision parser paths and preserve common default-exported, contract-symbol, and React-wrapper component shapes instead of silently falling back or degrading to module-level cards.

### M5 Negative Memory Persistence

- Issue found: CAM-SEQ distill returned negative-memory updates to the UI/API, but did not persist them into CAM's durable `failure_knowledge` table.
- Fix: failed reviewed-run negative-memory updates now become deterministic `camseq_negative_memory:*` failure-knowledge records.
- Effect: later CAM task evaluation can reuse those records as preventive context, and serial evolution can mine them as failure-policy signals.
- Verification: `PYTHONPATH=src pytest tests/test_dashboard_camseq.py -q` passed with `46 passed`.

### M5 Failure Knowledge Review Surface

- Issue found: durable negative memory could be stored, but not cleanly listed or resolved from the CAM-SEQ API surface.
- Fix: added `/api/v2/failure-knowledge` listing and `/api/v2/failure-knowledge/resolve` resolution endpoints, plus frontend API client bindings.
- Effect: operators and future UI workflow can inspect persisted negative memory, filter it by task/category/project, and mark resolved patterns without deleting history.
- Verification: `PYTHONPATH=src pytest tests/test_dashboard_camseq.py tests/test_failure_knowledge.py -q` passed with `61 passed`; `npm run lint` passed in `forge-ui`.

### M5 Failure Knowledge UI

- Fix: added `/knowledge/failure` and sidebar navigation for reviewing, filtering, and resolving persisted failure-knowledge records.
- Verification: `npm run lint` and `npx next build --webpack` passed in `forge-ui`.

### M5 Failure Knowledge Grouping

- Fix: added related-failure grouping to `/api/v2/failure-knowledge` and surfaced causal group cards in `/knowledge/failure`.
- Effect: repeated negative-memory signatures can now be reviewed as clusters with open/resolved counts, occurrence totals, representative diagnoses, and prevention hints.
- Verification: `PYTHONPATH=src pytest tests/test_dashboard_camseq.py tests/test_failure_knowledge.py -q` passed with `61 passed`; `npm run lint` and `npx next build --webpack` passed in `forge-ui`.

### M5 Durable Failure Detail Signals

- Fix: added `root_cause_key` and `detail_signals_json` to `failure_knowledge`, plus idempotent migration/backfill behavior and repository write defaults.
- Effect: related-failure grouping is now durable memory metadata instead of only a review-time API calculation.
- Verification: `PYTHONPATH=src pytest tests/test_failure_knowledge.py tests/test_dashboard_camseq.py -q` passed with `63 passed`; `npm run lint` and `npx next build --webpack` passed in `forge-ui`.

### M5 Negative-Memory Producer Signals

- Fix: CAM-SEQ distill now stores explicit root-cause keys and packet detail signals when failed reviewed-run negative memory becomes failure knowledge.
- Effect: each persisted negative-memory record carries slot, selected component, source barcode, proof gates, expected landing sites, transfer mode, fit bucket, confidence, and update text.
- Verification: `PYTHONPATH=src pytest tests/test_dashboard_camseq.py tests/test_failure_knowledge.py -q` passed with `63 passed`; `npm run lint` and `npx next build --webpack` passed in `forge-ui`.

### M5 Preventive-Memory Retrieval

- Fix: CAM task evaluation now groups retrieved failure knowledge by root cause and injects one representative preventive memory with persisted slot/component/proof detail signals.
- Effect: repeated CAM-SEQ negative-memory signatures no longer crowd the prompt as separate warnings; future CAM task attempts get the clearest root-cause warning with the concrete signals needed to avoid repeating it.
- Serial evolution: failure-policy mining now keeps `root_cause_key` and `detail_signals_json` in the mined payload and uses the root cause as `source_ref`.
- Verification: `PYTHONPATH=src pytest tests/test_cycle_evolution.py::TestMicroClawEvaluateEnrichment tests/test_serial_evolution.py::TestSerialEvolutionRunner::test_strategy_policy_cycle_bootstraps_routing_policy_and_skips_weak_rows -q` passed with `6 passed`.

### M5 Failure Group Priority Scoring

- Fix: failure-knowledge causal groups now receive a priority score, band, and ranking reasons based on unresolved state, recurrence, slot risk, proof-gate evidence, source trace, and detail-signal richness.
- Effect: repeated high-risk CAM-SEQ negative-memory clusters rank above generic lower-evidence runtime failures in the review API.
- Verification: `PYTHONPATH=src pytest tests/test_dashboard_camseq.py::test_failure_knowledge_list_and_resolve_endpoints -q` passed.

### M5 Failure Group Priority UI

- Fix: `/knowledge/failure` now surfaces high-priority group count, priority band, score, ranking reasons, slot risks, component files, and proof-gate evidence chips.
- Effect: operators can see why a failure group is important without reading raw JSON or individual rows first.
- Verification: `npm run lint` and `npx next build --webpack` passed in `forge-ui`.

### M6 Critical-Slot Pre-Write Blocking

- Fix: added `critical_slot_prewrite_block` / `CLAW_FEATURE_CRITICAL_SLOT_PREWRITE_BLOCK` as an optional stricter lane on top of `critical_slot_policy`.
- Effect: critical-slot reviewed runs can now stop before mutation when Semgrep fails or required CodeQL is unavailable, while the default reviewed-run proof lane remains available.
- Verification: `PYTHONPATH=src pytest tests/test_config.py::TestDefaults::test_feature_flags_default tests/test_dashboard_camseq.py::test_prewrite_policy_block_helpers_only_block_configured_critical_slots tests/test_dashboard_camseq.py::test_prewrite_policy_blocks_required_codeql_unavailable -q` passed.

### M6 Security Lane Visibility

- Fix: added `/api/v2/security/lane` and an Evolution Lab Security Lane panel.
- Effect: operators can now see CodeQL mode/readiness, Semgrep config/tool availability, reviewed-run proof-gate enforcement, and pre-write blocking state without inspecting environment variables.
- Verification: `PYTHONPATH=src pytest tests/test_policy_tools.py tests/test_dashboard_camseq.py::test_security_lane_endpoint_reports_flags_and_codeql_status -q`, `npm run lint`, and `npx next build --webpack` passed.

### M6 CodeQL Required-Mode Smoke

- Fix: added a mocked required-mode CodeQL SARIF smoke test for the configured analyzer path.
- Effect: the critical-slot policy lane now proves the `codeql database analyze` command shape, SARIF output handling, severity mapping, and finding parsing without requiring a local CodeQL install.
- Verification: `PYTHONPATH=src pytest tests/test_policy_tools.py -q` passed.

### M2 Parser Precision Coverage

- Fix: added real Tree-sitter regression coverage for Python property/classmethod methods, TypeScript function-expression variables, and JavaScript object literal methods.
- Effect: CAM-CAM has stronger evidence that component memory extraction handles more practical code shapes without falling back silently.
- Verification: `PYTHONPATH=src pytest tests/test_component_extractor.py -q` passed.

### M7 External Specialist Exchange Planning

- Fix: added a minimal external specialist exchange plan centered on schema-versioned request/reply envelopes.
- Effect: the next M7 implementation can start with a deterministic file-spool handoff before MCP-to-MCP or HTTP transport, while keeping external replies non-mutating until reviewed.
- Verification: docs-only change; no runtime validation required.

### M7 External Specialist Exchange Spool

- Fix: added feature-flagged export/list/import endpoints for file-based external specialist exchanges, durable exchange records, request/reply envelope helpers, and a Federation Hub exchange panel.
- Effect: CAM-CAM can now export bounded specialist handoff envelopes, import inbox replies idempotently, reject invalid or expired replies, and keep external advice non-mutating until reviewed.
- Verification: `PYTHONPATH=src pytest tests/test_specialist_exchange.py -q`, `npm run lint`, and `npm run build` passed.

## Operator Summary

The merger is complete and saved. CAM_CAM has now improved itself beyond the merge in three layers:

- prompt/config behavior
- strategy/self-mitigation policy behavior
- CAM-SEQ negative-memory persistence into durable failure knowledge

The latest champion is `v4-candidate`. The next meaningful autonomous improvement requires either live budgeted mining or real task executions to create stronger learning evidence.
