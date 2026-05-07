# CAM-SEQ Milestone Table

Last updated: 2026-05-07
Owner: Codex + user
Purpose: canonical progress ledger for CAM-SEQ execution status against the tracked build plan

Status values:
- `done`: milestone exit intent is satisfied for the current additive implementation path
- `partial`: milestone has meaningful implementation, but one or more planned pillars are still missing
- `not started`: milestone has only planning or negligible implementation

Progress estimate rules:
- percentages are milestone-weighted engineering estimates, not claims of research completion
- `done` milestones are tracked at `100%`
- `partial` milestones are updated when concrete gap area shrinks

## Completion Tally

- overall estimated completion: `99%`
- done milestones: `4/9`
- partial milestones: `5/9`
- not started milestones: `0/9`

## Summary

| Milestone | Status | Est. % | Current level | Evidence | Main gaps |
| --- | --- | --- | --- | --- | --- |
| `M0` Contracts Frozen | `done` | `100%` | Frozen object/API/flag vocabulary exists and is governing implementation | [CAM_SEQ_M0_contract.md](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/plans/CAM_SEQ_M0_contract.md), [models.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/core/models.py), [config.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/core/config.py) | None blocking |
| `M1` Foundation and Data Layer | `done` | `100%` | Additive schema, repository, flags, barcodes, lineage baseline are implemented and tested | [CAM_SEQ_M1_spec.md](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/plans/CAM_SEQ_M1_spec.md), [schema.sql](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/db/schema.sql), [repository.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/db/repository.py), [test_camseq_foundation.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_camseq_foundation.py) | None blocking |
| `M2` Component Memory and Backfill | `partial` | `99%` | Component cards, backfill, semantic bridge, HTTP APIs, UI, optional SCIP loader, and optional Tree-sitter backend are real; Tree-sitter is installed in the project `uv` venv and verified against real Python decorated/async shapes, Python class methods including decorated async class methods, property methods, `@classmethod` methods, and `@staticmethod` methods with real-parser verification, plus TypeScript function/class/arrow/method/function-expression-variable/object-method,string-key-object-method,private-method,getter-method,static-method,setter-method,class-field-method/default-export-class/interface/type-alias shapes, TSX function/default-export-function/contract-symbol/React-wrapper shapes, JSX React-wrapper shapes, and JavaScript object literal methods. The parser loader now supports `tree_sitter_typescript.language_typescript` for `.ts` and `tree_sitter_typescript.language_tsx` for `.tsx`, so TypeScript and TSX extraction use the appropriate Tree-sitter precision path instead of silently falling back. Repo-local SCIP JSON/JSONL metadata now upgrades component receipt precision into stored cards | [CAM_SEQ_M2_spec.md](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/plans/CAM_SEQ_M2_spec.md), [component_extractor.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/mining/component_extractor.py), [miner.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/miner.py), [semantic.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/memory/semantic.py), [knowledge/components/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/knowledge/components/page.tsx), [test_component_extractor.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_component_extractor.py) | Broaden real-parser coverage beyond the currently verified Python/TypeScript/TSX/JSX/JavaScript symbol families and remaining framework-specific wrappers |
| `M3` Planning and Application Packets | `done` | `100%` | Plan creation, slot decomposition, ranking, packet review, approvals, swaps, execute handoff are implemented | [CAM_SEQ_M3_spec.md](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/plans/CAM_SEQ_M3_spec.md), [taskome.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/planning/taskome.py), [component_ranker.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/memory/component_ranker.py), [application_packet.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/planning/application_packet.py), [playground/plan/[planId]/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/playground/plan/[planId]/page.tsx) | None blocking for v1 path |
| `M4` Packet-Aware Execution and Sequencing | `done` | `100%` | Reviewed runs are slot-by-slot, durable, observable, controllable, and have sequencing UI | [CAM_SEQ_M4_spec.md](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/plans/CAM_SEQ_M4_spec.md), [dashboard_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/web/dashboard_server.py), [forge/run/[id]/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/forge/run/[id]/page.tsx) | Native executor replacement is still deferred; additive slot loop is in place |
| `M5` Retrograde, Distill, and Knowledge History | `partial` | `99%` | Retrograde, distill, audits, run analysis UI, packet/component history, and federation-aware post-run signals all exist; retrograde now ranks proof-gate failures, verifier findings, negative-memory emissions, and operator actions alongside retries and landings, adds correlated-signal boosts for waivers, retry pressure, and counterfactual evidence, and emits a richer root-cause summary with clustered cause buckets, a narrative explanation, a confidence band, explicit recommended next action, actionability state, a dominant cluster, evidence count, a causal decision path, confidence drivers, confidence score, confidence reason, calibration state, stability signal, stability reason, and summary versioning for proof, operator, runtime, transfer, and memory pressure. Distill now persists failed reviewed-run negative-memory updates into durable `failure_knowledge` with explicit root-cause keys and packet detail signals; CAM task evaluation now collapses retrieved failure knowledge by root cause and injects representative detail signals as preventive memory; serial evolution mining preserves root-cause keys and detail signals as failure-policy input; `/api/v2/failure-knowledge` exposes listing, resolution, related-failure grouping, and priority-scored causal groups; and `/knowledge/failure` surfaces grouped review, filtering, resolution, priority bands, scores, reasons, and evidence chips | [dashboard_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/web/dashboard_server.py), [evolution/run/[runId]/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/evolution/run/[runId]/page.tsx), [knowledge/components/[componentId]/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/knowledge/components/[componentId]/page.tsx), [knowledge/failure/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/knowledge/failure/page.tsx), [test_seeded_retrograde.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/test_seeded_retrograde.py), [test_dashboard_camseq.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_dashboard_camseq.py) | Causal weighting is still heuristic rather than learned from a larger outcome corpus |
| `M6` Critical-Slot Policy Lane | `partial` | `90%` | Durable governance memory, conflicts, trends, severity, policy lifecycle, policy-aware planning/swaps, static-analysis proof gates, waiver route, repo-local Semgrep rules, verified Docker-based Semgrep execution, explicit CodeQL mode control, optional pre-write critical-slot blocking, and security-lane visibility are implemented. `/api/v2/security/lane` reports Semgrep availability, CodeQL mode/readiness, proof-gate enforcement, and pre-write blocking; Evolution Lab surfaces that lane state for operators. Required-mode CodeQL now has a mocked SARIF smoke test proving the configured `codeql database analyze` path and finding parser behavior | [dashboard_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/web/dashboard_server.py), [component_ranker.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/memory/component_ranker.py), [application_packet.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/planning/application_packet.py), [policy_tools.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/security/policy_tools.py), [security/semgrep.yml](/Volumes/WS4TB/RNACAM/CAM-Pulse/security/semgrep.yml), [camseq_semgrep.sh](/Volumes/WS4TB/RNACAM/CAM-Pulse/scripts/camseq_semgrep.sh), [evolution/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/evolution/page.tsx), [test_camseq_policy_benchmark.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_camseq_policy_benchmark.py), [test_dashboard_camseq.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_dashboard_camseq.py), [test_policy_tools.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_policy_tools.py) | Full CodeQL analysis still requires an external CodeQL database and query suite; a live managed CodeQL run remains future work |
| `M7` Federation, Mining Missions, MCP, Recipes | `partial` | `93%` | Mining missions are durable, CAM-SEQ MCP tools are implemented, packet-native federation API/UI exist, specialist packet exchange is available, federation supervision feeds both per-run and repeated-run analysis, and cross-run federation trends now emit promotable policy recommendations. The first true external specialist exchange slice is implemented as a feature-flagged, schema-versioned file spool: CAM exports bounded request envelopes, imports inbox replies idempotently, records durable lifecycle state, rejects invalid/expired replies, surfaces exchange status in Federation Hub, exposes MCP tools for export/import/list over the same ledger, and can bridge an existing exchange to an external MCP stdio tool before importing the normalized reply | [dashboard_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/web/dashboard_server.py), [federation.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/community/federation.py), [specialist_exchange.py](/Volumes/WS4TB/CCam/CAM_CAM/src/claw/community/specialist_exchange.py), [mcp_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/mcp_server.py), [schemas.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/tools/schemas.py), [federation/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/federation/page.tsx), [evolution/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/evolution/page.tsx), [CAM_SEQ_M7_external_specialist_exchange_plan.md](/Volumes/WS4TB/CCam/CAM_CAM/docs/plans/CAM_SEQ_M7_external_specialist_exchange_plan.md), [test_specialist_exchange.py](/Volumes/WS4TB/CCam/CAM_CAM/tests/test_specialist_exchange.py), [test_mcp_camseq_tools.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_mcp_camseq_tools.py), [test_dashboard_camseq.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_dashboard_camseq.py) | Signed HTTP webhook transport remains future work |
| `M8` Benchmarks and Proof | `partial` | `89%` | Regression coverage exists, the six-task pilot harness is executable, the 24-task suite is defined, seeded retrograde cases execute including waived-proof-gate/negative-memory cases, planning/ranking/packet/connectome/recipe ablation scaffolds exist, deterministic benchmark report artifacts can be generated and are now materialized under `docs/benchmarks` in markdown, structured JSON, a manifest file with summary metadata, a compact headlines JSON artifact, and a compact status markdown artifact; the checked-in report now includes recommended-action, dominant-cluster, confidence-band, calibration, and stability distributions from the seeded retrograde suite alongside causal and root-summary distributions; the lightweight end-to-end reviewed-run harness exercises the real plan/execute/distill API flow while mutating a real temp workspace file | [test_dashboard_camseq.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_dashboard_camseq.py), [test_camseq_policy_benchmark.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_camseq_policy_benchmark.py), [pilot_suite.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/pilot_suite.py), [full_suite.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/full_suite.py), [harness.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/harness.py), [ablation.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/ablation.py), [multi_layer_ablation.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/multi_layer_ablation.py), [connectome_recipe_ablation.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/connectome_recipe_ablation.py), [live_run_harness.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/live_run_harness.py), [report.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/report.py), [generate_artifacts.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/generate_artifacts.py), [camseq_connectome_report.md](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/benchmarks/camseq_connectome_report.md), [camseq_connectome_report.json](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/benchmarks/camseq_connectome_report.json), [camseq_connectome_manifest.json](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/benchmarks/camseq_connectome_manifest.json), [camseq_connectome_headlines.json](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/benchmarks/camseq_connectome_headlines.json), [camseq_connectome_status.md](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/benchmarks/camseq_connectome_status.md), [seeded_failures.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/seeded_failures.py), [test_pilot_harness.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/test_pilot_harness.py), [test_full_suite.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/test_full_suite.py), [test_ablation.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/test_ablation.py), [test_multi_layer_ablation.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/test_multi_layer_ablation.py), [test_connectome_recipe_ablation.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/test_connectome_recipe_ablation.py), [test_live_run_harness.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/test_live_run_harness.py), [test_report.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/test_report.py), [test_generate_artifacts.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/test_generate_artifacts.py), [test_seeded_retrograde.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/test_seeded_retrograde.py) | No benchmark harness over broader real repository mutations and no polished demo artifacts |

## Detailed Status

### `M0` Contracts Frozen
Status: `done`

Implemented:
- canonical object chain frozen in docs and reflected in code
- `/api/v2` boundary established
- feature flags defined
- packet/event vocabulary stabilized

Evidence:
- [CAM_SEQ_M0_contract.md](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/plans/CAM_SEQ_M0_contract.md)
- [models.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/core/models.py)
- [config.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/core/config.py)

Remaining:
- none blocking

### `M1` Foundation and Data Layer
Status: `done`

Implemented:
- additive schema and repository methods
- barcode generation
- lineage baseline
- feature flags in runtime
- round-trip persistence tests

Evidence:
- [schema.sql](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/db/schema.sql)
- [repository.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/db/repository.py)
- [barcodes.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/connectome/barcodes.py)
- [lineage.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/connectome/lineage.py)
- [test_camseq_foundation.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_camseq_foundation.py)

Remaining:
- none blocking

### `M2` Component Memory and Backfill
Status: `partial`

Implemented:
- component extractor with optional Tree-sitter backend
- methodology-to-component backfill
- semantic bridge
- component APIs and minimal Knowledge UI
- optional SCIP JSON/JSONL path with receipt precision upgrade into component cards
- verified Tree-sitter coverage for decorated async Python class methods, property methods, `@classmethod` methods, and `@staticmethod` methods, plus TypeScript setter methods with real-parser verification
- TypeScript Tree-sitter parser loading now supports the installed `language_typescript` factory exposed by `tree_sitter_typescript`
- TSX Tree-sitter parser loading now supports the installed `language_tsx` factory exposed by `tree_sitter_typescript`
- named `export default function` and `export default class` extraction is verified for Tree-sitter paths, with JavaScript fallback coverage when Tree-sitter is unavailable
- TypeScript/TSX `interface` and `type` declarations now ingest as `type_contract` components through Tree-sitter, with TypeScript fallback coverage when Tree-sitter is unavailable
- JSX/TSX React wrapper declarations using `memo`, `React.memo`, and `forwardRef` now ingest as function components through Tree-sitter, with JSX fallback coverage when Tree-sitter is unavailable

Evidence:
- [component_extractor.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/mining/component_extractor.py)
- [scip_loader.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/mining/scip_loader.py)
- [miner.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/miner.py)
- [semantic.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/memory/semantic.py)
- [knowledge/components/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/knowledge/components/page.tsx)

Remaining:
- broaden real-parser coverage beyond the currently verified Python/TypeScript/TSX/JSX method, top-level, named default-export, contract-symbol, and React-wrapper shapes into more nested or language-specific constructs

### `M3` Planning and Application Packets
Status: `done`

Implemented:
- deterministic archetype inference
- slot decomposition
- candidate ranking
- packet construction
- plan create/get/approve/swap/execute APIs
- pre-mutation review route and Playground handoff

Evidence:
- [taskome.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/planning/taskome.py)
- [component_ranker.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/memory/component_ranker.py)
- [application_packet.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/planning/application_packet.py)
- [playground/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/playground/page.tsx)
- [playground/plan/[planId]/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/playground/plan/[planId]/page.tsx)

Remaining:
- none blocking for the current v1 milestone

### `M4` Packet-Aware Execution and Sequencing
Status: `done`

Implemented:
- durable plan/run persistence
- slot-by-slot reviewed execution loop
- run connectome, landings, events, audits
- SSE event stream
- Forge Run sequencing console with slot controls

Evidence:
- [dashboard_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/web/dashboard_server.py)
- [forge/run/[id]/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/forge/run/[id]/page.tsx)

Remaining:
- native executor replacement is still deferred

### `M5` Retrograde, Distill, and Knowledge History
Status: `partial`

Implemented:
- retrograde route and UI
- distill route and UI
- audits route and tabs
- run-level analysis using events, slot executions, audits, pair/landing/outcome records
- federation-aware retrograde/distill signals for pattern-transfer versus direct-fit pressure
- retrograde root-cause summary object for primary cause, supporting signals, governance pressure, proof pressure, dominant cluster, evidence count, causal decision path, confidence drivers, confidence score, confidence reason, calibration, stability, and summary versioning
- distill persistence of reviewed-run negative-memory updates into `failure_knowledge`, which the task cycle can reuse as preventive context and serial evolution can mine as failure-policy signal
- failure-knowledge listing and resolution API for inspecting durable negative memory and marking resolved patterns
- first Failure Knowledge UI page for filtering, reading, and resolving durable negative memory
- related-failure grouping in the Failure Knowledge API and UI so repeated signatures can be reviewed as causal clusters
- durable root-cause and detail-signal fields in `failure_knowledge`, including idempotent migration/backfill coverage and repository write defaults
- CAM-SEQ distill producer wiring so failed reviewed-run negative memory stores packet-level detail signals
- root-cause grouped preventive-memory retrieval in the task cycle, plus serial-evolution failure-policy mining that preserves detail signals
- priority scoring for failure-knowledge causal groups using unresolved state, recurrence, slot risk, proof-gate evidence, source trace, and detail-signal richness
- priority review UI for failure-knowledge groups, including bands, scores, reasons, slot risks, component files, and proof gate chips

Evidence:
- [dashboard_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/web/dashboard_server.py)
- [evolution/run/[runId]/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/evolution/run/[runId]/page.tsx)
- [seeded_failures.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/seeded_failures.py)
- [test_seeded_retrograde.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/test_seeded_retrograde.py)

Remaining:
- stronger causal ranking model beyond the current proof-gate/verifier-aware heuristic
- further UI polish and causal grouping for negative-memory review on top of the durable `failure_knowledge` bridge

### `M6` Critical-Slot Policy Lane
Status: `partial`

Implemented:
- durable governance policy memory
- policy lifecycle and provenance
- policy conflicts and trends
- policy-aware ranking, packet review, and active-run swaps
- static-analysis proof gates for critical slots
- explicit proof-gate waiver route for active reviewed runs
- governance summary surfaces in Evolution and Forge
- explicit `CLAW_CODEQL_MODE` control for skipped, deferred, and required CodeQL lanes
- optional pre-write critical-slot blocking before mutation when Semgrep fails or required CodeQL is unavailable
- `/api/v2/security/lane` and Evolution Lab security-lane panel for CodeQL mode/readiness, Semgrep availability, proof-gate enforcement, and pre-write blocking

Evidence:
- [dashboard_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/web/dashboard_server.py)
- [component_ranker.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/memory/component_ranker.py)
- [application_packet.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/planning/application_packet.py)
- [policy_tools.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/security/policy_tools.py)
- [evolution/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/evolution/page.tsx)

Remaining:
- full CodeQL analysis still needs a managed/advanced setup with CLI, database, and query suite
- mocked required-mode CodeQL SARIF smoke testing is covered; a live managed CodeQL run remains future work

### `M7` Federation, Mining Missions, MCP, Recipes
Status: `partial`

Implemented:
- durable mining missions
- recipe promotion action
- policy/governance context on merged search and component detail
- CAM-SEQ MCP additive tools for decompose, packet build, connectome, retrograde, recipe promotion, and mining mission queue
- packet-native federation API for component-card style cross-brain results
- Federation Hub packet query UI with direct-fit versus pattern-transfer result labeling
- specialist packet exchange route, MCP tool, and Federation Hub operator panel
- feature-flagged external specialist exchange file spool with durable request/reply lifecycle
- Federation Hub exchange status panel with export/import controls
- MCP export/import/list tools over the same external exchange ledger
- MCP-to-MCP bridge submission for an existing exchange, with normalized reply import
- federation-aware retrograde/distill supervision for pattern-transfer pressure
- repeated-run federation trend summaries in Evolution Lab
- automated federation policy recommendations from repeated-run trend pressure, with promotion into durable governance memory
- automatic compiled-recipe distillation on repeated successful reviewed-run signatures

Evidence:
- [dashboard_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/web/dashboard_server.py)
- [federation.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/community/federation.py)
- [mcp_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/mcp_server.py)
- [schemas.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/tools/schemas.py)
- [specialist_exchange.py](/Volumes/WS4TB/CCam/CAM_CAM/src/claw/community/specialist_exchange.py)
- [test_specialist_exchange.py](/Volumes/WS4TB/CCam/CAM_CAM/tests/test_specialist_exchange.py)
- [test_mcp_camseq_tools.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_mcp_camseq_tools.py)
- [federation/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/federation/page.tsx)
- [evolution/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/evolution/page.tsx)

Remaining:
- signed HTTP webhook transport remains future work

### `M8` Benchmarks and Proof
Status: `partial`

Implemented:
- regression coverage
- policy-focused benchmark-style tests
- six-task pilot benchmark scaffold
- executable pilot benchmark harness for slot decomposition accuracy against the seeded suite
- full 24-task benchmark grid definition
- lightweight planning ablation scaffold against a naive baseline
- lightweight ranking/packet ablation scaffold for fit-history and governance effects
- connectome-learning and recipe-reuse ablation scaffold using repeated recipe distillation plus recipe-aware ranking
- deterministic benchmark report artifact generator covering pilot, full-suite, ablation, seeded-retrograde, and local-security summaries in both markdown and structured JSON forms
- compact benchmark status artifact for fast inspection
- dominant-cluster reporting in the seeded retrograde proof artifacts
- confidence-band reporting in the seeded retrograde proof artifacts
- calibration reporting in the seeded retrograde proof artifacts
- stability reporting in the seeded retrograde proof artifacts
- lightweight end-to-end reviewed-run benchmark harness covering real plan/approve/execute/distill flow with controlled execution
- seeded retrograde failure cases that execute against the shared retrograde ranking helper

Evidence:
- [test_dashboard_camseq.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_dashboard_camseq.py)
- [test_camseq_policy_benchmark.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_camseq_policy_benchmark.py)
- [pilot_suite.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/pilot_suite.py)
- [full_suite.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/full_suite.py)
- [test_pilot_suite.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/test_pilot_suite.py)
- [harness.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/harness.py)
- [test_pilot_harness.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/test_pilot_harness.py)
- [ablation.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/ablation.py)
- [multi_layer_ablation.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/multi_layer_ablation.py)
- [report.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/report.py)
- [test_full_suite.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/test_full_suite.py)
- [test_ablation.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/test_ablation.py)
- [test_multi_layer_ablation.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/test_multi_layer_ablation.py)
- [seeded_failures.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/seeded_failures.py)
- [test_seeded_retrograde.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/test_seeded_retrograde.py)
- [test_report.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/test_report.py)

Remaining:
- benchmark harness over broader real repository mutations than the current temp-workspace reviewed-run path
- polished demo artifacts

## Update Rules

Update this file whenever one of these changes:
- a milestone changes status
- a milestone’s main gaps materially change
- a new route/API closes a tracked milestone item
- a benchmark/proof artifact changes `M8`

When updating:
- keep status values limited to `done`, `partial`, `not started`
- add evidence links to concrete files or tests, not vague claims
- do not mark `done` unless the current additive implementation path satisfies the milestone intent
- record remaining gaps explicitly even when status is `partial`

## Next Focus

Recommended next work order from the current state:
1. finish `M2` precision gap with broader Tree-sitter parser coverage
2. tighten `M5` causal reasoning beyond the current heuristic retrograde layer
3. finish `M7` with deeper federation supervision and any true external specialist exchange you still want
4. extend `M8` with proof/demo artifacts and broader live-system benchmark execution
