# CAM-SEQ Milestone Table

Last updated: 2026-05-06
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
| `M2` Component Memory and Backfill | `partial` | `97%` | Component cards, backfill, semantic bridge, HTTP APIs, UI, optional SCIP loader, and optional Tree-sitter backend are real; Tree-sitter is installed in the project `uv` venv and verified against real Python decorated/async shapes, Python class methods including decorated async class methods, property methods, `@classmethod` methods, and `@staticmethod` methods with real-parser verification, plus TypeScript function/class/arrow/method/object-method,string-key-object-method,private-method,getter-method,static-method,setter-method,class-field-method/default-export-class shapes and TSX function/default-export-function shapes. The parser loader now supports `tree_sitter_typescript.language_typescript` for `.ts` and `tree_sitter_typescript.language_tsx` for `.tsx`, so TypeScript and TSX extraction use the appropriate Tree-sitter precision path instead of silently falling back. Repo-local SCIP JSON/JSONL metadata now upgrades component receipt precision into stored cards | [CAM_SEQ_M2_spec.md](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/plans/CAM_SEQ_M2_spec.md), [component_extractor.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/mining/component_extractor.py), [miner.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/miner.py), [semantic.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/memory/semantic.py), [knowledge/components/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/knowledge/components/page.tsx), [test_component_extractor.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_component_extractor.py) | Broaden real-parser coverage beyond the currently verified Python/TypeScript/TSX symbol families and named default-export shapes |
| `M3` Planning and Application Packets | `done` | `100%` | Plan creation, slot decomposition, ranking, packet review, approvals, swaps, execute handoff are implemented | [CAM_SEQ_M3_spec.md](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/plans/CAM_SEQ_M3_spec.md), [taskome.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/planning/taskome.py), [component_ranker.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/memory/component_ranker.py), [application_packet.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/planning/application_packet.py), [playground/plan/[planId]/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/playground/plan/[planId]/page.tsx) | None blocking for v1 path |
| `M4` Packet-Aware Execution and Sequencing | `done` | `100%` | Reviewed runs are slot-by-slot, durable, observable, controllable, and have sequencing UI | [CAM_SEQ_M4_spec.md](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/plans/CAM_SEQ_M4_spec.md), [dashboard_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/web/dashboard_server.py), [forge/run/[id]/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/forge/run/[id]/page.tsx) | Native executor replacement is still deferred; additive slot loop is in place |
| `M5` Retrograde, Distill, and Knowledge History | `partial` | `93%` | Retrograde, distill, audits, run analysis UI, packet/component history, and federation-aware post-run signals all exist; retrograde now ranks proof-gate failures, verifier findings, negative-memory emissions, and operator actions alongside retries and landings, adds correlated-signal boosts for waivers, retry pressure, and counterfactual evidence, and emits a richer root-cause summary with clustered cause buckets, a narrative explanation, a confidence band, explicit recommended next action, actionability state, a dominant cluster, evidence count, a causal decision path, confidence drivers, confidence score, confidence reason, calibration state, stability signal, stability reason, and summary versioning for proof, operator, runtime, transfer, and memory pressure | [dashboard_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/web/dashboard_server.py), [evolution/run/[runId]/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/evolution/run/[runId]/page.tsx), [knowledge/components/[componentId]/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/knowledge/components/[componentId]/page.tsx), [test_seeded_retrograde.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/test_seeded_retrograde.py), [test_dashboard_camseq.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_dashboard_camseq.py) | Causal reasoning is still heuristic; negative memory is not yet a deeper standalone subsystem |
| `M6` Critical-Slot Policy Lane | `partial` | `83%` | Durable governance memory, conflicts, trends, severity, policy lifecycle, policy-aware planning/swaps, static-analysis proof gates, waiver route, repo-local Semgrep rules, and verified Docker-based Semgrep execution are implemented | [dashboard_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/web/dashboard_server.py), [component_ranker.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/memory/component_ranker.py), [application_packet.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/planning/application_packet.py), [policy_tools.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/security/policy_tools.py), [security/semgrep.yml](/Volumes/WS4TB/RNACAM/CAM-Pulse/security/semgrep.yml), [camseq_semgrep.sh](/Volumes/WS4TB/RNACAM/CAM-Pulse/scripts/camseq_semgrep.sh), [evolution/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/evolution/page.tsx), [test_camseq_policy_benchmark.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_camseq_policy_benchmark.py), [test_dashboard_camseq.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_dashboard_camseq.py), [test_policy_tools.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_policy_tools.py) | CodeQL is still deferred locally unless a managed/advanced setup provides the CLI, database, and query suite |
| `M7` Federation, Mining Missions, MCP, Recipes | `partial` | `86%` | Mining missions are durable, CAM-SEQ MCP tools are implemented, packet-native federation API/UI exist, specialist packet exchange is available, federation supervision feeds both per-run and repeated-run analysis, and cross-run federation trends now emit promotable policy recommendations | [dashboard_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/web/dashboard_server.py), [federation.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/community/federation.py), [mcp_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/mcp_server.py), [schemas.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/tools/schemas.py), [federation/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/federation/page.tsx), [evolution/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/evolution/page.tsx), [test_mcp_camseq_tools.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_mcp_camseq_tools.py), [test_dashboard_camseq.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_dashboard_camseq.py) | No true A2A transport/external specialist exchange yet |
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

Evidence:
- [component_extractor.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/mining/component_extractor.py)
- [scip_loader.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/mining/scip_loader.py)
- [miner.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/miner.py)
- [semantic.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/memory/semantic.py)
- [knowledge/components/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/knowledge/components/page.tsx)

Remaining:
- broaden real-parser coverage beyond the currently verified Python/TypeScript/TSX method, top-level, and named default-export shapes into more nested or language-specific constructs

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

Evidence:
- [dashboard_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/web/dashboard_server.py)
- [evolution/run/[runId]/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/evolution/run/[runId]/page.tsx)
- [seeded_failures.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/seeded_failures.py)
- [test_seeded_retrograde.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite/test_seeded_retrograde.py)

Remaining:
- stronger causal ranking model beyond the current proof-gate/verifier-aware heuristic
- deeper standalone negative-memory subsystem

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

Evidence:
- [dashboard_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/web/dashboard_server.py)
- [component_ranker.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/memory/component_ranker.py)
- [application_packet.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/planning/application_packet.py)
- [policy_tools.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/security/policy_tools.py)
- [evolution/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/evolution/page.tsx)

Remaining:
- CodeQL remains optional advanced/managed mode if you want full hard-lane static analysis
- stricter pre-write blocking flow if you want static analysis before mutation rather than reviewed-run proof enforcement

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
- federation-aware retrograde/distill supervision for pattern-transfer pressure
- repeated-run federation trend summaries in Evolution Lab
- automated federation policy recommendations from repeated-run trend pressure, with promotion into durable governance memory
- automatic compiled-recipe distillation on repeated successful reviewed-run signatures

Evidence:
- [dashboard_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/web/dashboard_server.py)
- [federation.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/community/federation.py)
- [mcp_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/mcp_server.py)
- [schemas.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/tools/schemas.py)
- [test_mcp_camseq_tools.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/test_mcp_camseq_tools.py)
- [federation/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/federation/page.tsx)
- [evolution/page.tsx](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/evolution/page.tsx)

Remaining:
- true A2A transport or external specialist exchange if that remains in scope

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
