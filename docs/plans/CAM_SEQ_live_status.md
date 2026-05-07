# CAM-SEQ Live Status

Last updated: 2026-05-07

This file is the short answer to:
- what is actively being worked
- what just finished
- what artifacts should be inspected

For the full ledger, use:
- [CAM_SEQ_milestone_table.md](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/plans/CAM_SEQ_milestone_table.md)

## Current Slice

Active work:
- resumed the pre-merger plan after the CAM_CAM/CAM-Pulse defense-chain merge
- `M2`: close component parser precision gaps with focused real-parser coverage; added coverage for Python property/classmethod methods, TypeScript function-expression variables, and JavaScript object methods
- app troubleshooting: verify frontend/backend runtime behavior and separate app defects from environment/tooling failures
- `M6`: explicit CodeQL mode control, optional pre-write critical-slot blocking, security-lane API/UI visibility, and mocked required-mode CodeQL SARIF smoke coverage are implemented; full CodeQL analysis still needs managed CodeQL assets
- `M7`: external/specialist exchange planning has started with a minimal A2A packet handoff plan; implementation remains pending
- milestone ledger remains available in the long-form tracker below

Just finished:
- fixed the TypeScript Tree-sitter parser loader so `tree_sitter_typescript.language_typescript` is used when the package does not expose a generic `language` factory
- added regression coverage that the declared TypeScript Tree-sitter parser loads
- added dedicated TSX parser selection through `tree_sitter_typescript.language_tsx` for `.tsx` component extraction
- added Tree-sitter and fallback coverage for named default-exported JavaScript/TypeScript/TSX components
- added Tree-sitter and fallback coverage for TypeScript/TSX interface and type-alias contract components
- added Tree-sitter and fallback coverage for JSX/TSX React wrapper components using `memo`, `React.memo`, and `forwardRef`
- verified `tests/test_component_extractor.py` with `42 passed`
- wired CAM-SEQ distill negative-memory updates into durable `failure_knowledge` records so failed reviewed runs become preventive context for later CAM tasks
- added `/api/v2/failure-knowledge` list and resolve endpoints plus frontend API client bindings so durable negative memory is inspectable and resolvable
- added the `/knowledge/failure` UI page and sidebar entry for reviewing, filtering, and resolving durable failure-knowledge records
- added related-failure grouping to `/api/v2/failure-knowledge` and surfaced those causal groups in `/knowledge/failure`
- added durable `root_cause_key` and `detail_signals_json` columns to `failure_knowledge`, with migration/backfill coverage and repository defaults for existing callers
- wired CAM-SEQ negative-memory distill to persist explicit root-cause keys and packet detail signals for failed reviewed-run memories
- wired CAM task evaluation and serial evolution mining to use root-cause grouped failure knowledge with persisted detail signals as preventive memory
- added priority scoring for failure-knowledge causal groups using unresolved state, recurrence, slot risk, proof-gate evidence, source trace, and detail-signal richness
- surfaced failure-knowledge priority bands, scores, reasons, and detail-signal chips in `/knowledge/failure`
- verified the focused dashboard CAM-SEQ tests with `46 passed`
- installed `forge-ui` local dependencies
- fixed frontend lint errors across Evolution, Forge Run, Knowledge, Playground, and Layout
- verified production build with `next build --webpack`
- fixed backend runtime import path so the live server uses this repo's `src` tree instead of another installed `claw` checkout
- enabled CAM-SEQ feature flags in the shared `.env` and verified they load in `/api/config`
- backfilled component cards into `data/claw.db` and confirmed live plan creation works for a matching task
- added local-workspace component fallback so `POST /api/v2/plans` no longer hard-fails when the DB lacks relevant candidates
- persisted local fallback cards before packet creation, fixing the component foreign-key failure
- filtered noisy cache paths like `.uv-cache` out of component search and candidate lookup
- added local-workspace fallback to component search, plus content-aware file matching, so search is no longer limited to pre-existing persisted DB cards by implementation
- improved local search ranking to prefer non-test files and propagate file-level relevance into extracted candidates
- changed component search from `DB first, workspace fallback second` to a single merged scored result set
- added component search metadata in the UI so results now expose `memory` vs `workspace` origin plus match score
- added regression coverage proving a workspace auth hit can outrank a weaker persisted DB hit
- fixed workspace search leakage so a file-content hit now yields one explicit file-level fallback result instead of every unrelated symbol in that file

Latest validation:
- backend: `PYTHONPATH=src pytest tests/test_component_extractor.py -q` passed (`42 passed`)
- backend: `PYTHONPATH=src pytest tests/test_dashboard_camseq.py -q` passed (`46 passed`)
- backend: `PYTHONPATH=src pytest tests/test_dashboard_camseq.py tests/test_failure_knowledge.py -q` passed (`61 passed`)
- backend: `PYTHONPATH=src pytest tests/ --cov=src/claw --cov-report=xml --cov-fail-under=60 -q` passed (`4184 passed, 18 skipped`, coverage `63.93%`)
- frontend: `npm run lint` passed
- frontend: `npx next build --webpack` passed
- backend: focused `tests/test_dashboard_camseq.py` passes (`41 passed`)
- backend live smoke:
  - `/api/v2/*` routes now appear in OpenAPI
  - `/api/v2/components/search?q=word&limit=5` returns component cards
  - `POST /api/v2/plans` succeeds for `Create a Python module for counting words in text with tests`
  - `POST /api/v2/plans` also succeeds for `Add OAuth session handling with token refresh` against `/Volumes/WS4TB/RNACAM/CAM-Pulse`
  - `/api/v2/components/search?q=auth&limit=10` now returns repo-local results instead of an empty list
  - live verification of the new merged-scoring search path still requires restarting the already-running backend process after this latest search fix

## Completion Tally

- overall estimated completion: `99%`

Milestones:
- `M0`: `100%`
- `M1`: `100%`
- `M2`: `99%`
- `M3`: `100%`
- `M4`: `100%`
- `M5`: `99%`
- `M6`: `89%`
- `M7`: `86%`
- `M8`: `89%`

## What To Inspect

Short-form progress:
- [CAM_SEQ_live_status.md](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/plans/CAM_SEQ_live_status.md)

Long-form milestone ledger:
- [CAM_SEQ_milestone_table.md](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/plans/CAM_SEQ_milestone_table.md)

Current proof artifacts:
- [camseq_connectome_report.md](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/benchmarks/camseq_connectome_report.md)
- [camseq_connectome_report.json](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/benchmarks/camseq_connectome_report.json)
- [camseq_connectome_manifest.json](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/benchmarks/camseq_connectome_manifest.json)
- [camseq_connectome_headlines.json](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/benchmarks/camseq_connectome_headlines.json)
- [camseq_connectome_status.md](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/benchmarks/camseq_connectome_status.md)

M7 planning:
- [CAM_SEQ_M7_external_specialist_exchange_plan.md](/Volumes/WS4TB/CCam/CAM_CAM/docs/plans/CAM_SEQ_M7_external_specialist_exchange_plan.md)

## How To Read My Updates

- commentary messages are checkpoint summaries, not permission requests
- the real source of truth is the repo files above
- if you only want the shortest possible status view, read this file

## Current Open Gaps

- app: Turbopack build still crashes in this sandbox with a port-binding permission error; webpack build is clean
- app: component search now uses merged scoring and explicit file-level fallback for content matches; the live backend needs a restart before the latest fix can be re-smoke-tested outside the test client
- `M2`: broader verified parser coverage beyond the currently tested Python/TypeScript/TSX/JSX families, named default-export shapes, TypeScript contract symbols, React wrapper components, function-expression variables, and JavaScript object methods
- `M5`: stronger causal model beyond heuristic weighting, grouped summaries, decision traces, confidence drivers, calibration, stability, and discrimination; negative-memory persistence/listing/resolution plus priority review UI now exist
- `M6`: full CodeQL analysis still needs managed/advanced assets; local mode now exposes `off`, `deferred`, `required`, optional pre-write blocking, lane visibility, and required-mode SARIF parser smoke coverage
- `M7`: no true external/A2A specialist transport yet; first docs plan favors a file-based packet handoff spool before MCP-to-MCP or HTTP transport
- `M8`: broader real-repo mutation benchmark coverage and more polished demo artifacts
