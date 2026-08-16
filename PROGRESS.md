# PROGRESS.md

## 2026-06-20

- Continued the active MoriahCareFrame Repo Necromancer goal from
  `docs/showpieces/repo_necromancer/moriah_careframe/CAM_CODEX_GOAL.md`.
- Added test coverage for required `merge_ledger` and `safe_merge_plan`
  evidence fields.
- Updated `scripts/repo_necromancer.py` so generated packets include source git
  receipts, a merge ledger, a safe merge plan, README provenance, and a demo
  output that prints the ledger and plan.
- Regenerated `docs/showpieces/repo_necromancer/moriah_careframe/`.
- Verified the packet smoke tests and recorded broader full-suite failures in
  `docs/showpieces/repo_necromancer/moriah_careframe/TEST_RESULTS.md`.
- Rechecked the packet on the live 2026-06-20 source state: Source A remains a
  non-git filesystem source with 56 profiled files; Source B remains at git
  head `194fc54` with pre-existing dirty state now including `../instances/`.
- Added regression coverage that generated reports expose source git-state
  receipts, including non-git source status, git heads, dirty flags, and raw
  status receipt text.
- Regenerated the MoriahCareFrame packet after strengthening receipt rendering.
- Verified `python -m pytest -q tests/test_repo_necromancer.py` passes with
  4 tests, the generated CLI `--help` exits 0, and the generated demo exits 0.
- Reran full `python -m pytest -q`; it still fails outside the packet with
  3 failures and now reports `4232 passed, 14 skipped, 5 warnings`.
- Added `--standalone-repo` support to `scripts/repo_necromancer.py` so future
  Repo Necromancer runs can create a real output repo scaffold instead of only
  a packet demo.
- Added regression coverage that proves `--standalone-repo` creates README,
  pyproject, runtime package code, tests, source receipts, evidence JSON, and a
  patch plan, and that the generated CLI smoke path exits 0.
- Re-ran `python -m pytest -q tests/test_repo_necromancer.py`; all 5 tests
  passed.
- Confirmed `/Volumes/WS4TB/WS4TBr/MoriahCareFrame` exists as a standalone git
  repo with local commit `a82e42c Initial MoriahCareFrame runtime`.
- Verified the standalone repo:
  `python -m pytest -q` passed 5 tests;
  `PYTHONPATH=src python -m moriah_careframe demo` exited 0;
  `PYTHONPATH=src python -m moriah_careframe --help` exited 0;
  `PYTHONPATH=src python -m moriah_careframe write-patch-plan --out /tmp/moriah_patch_plan_check.md` exited 0;
  `PYTHONPATH=src python -m moriah_careframe preflight /Volumes/WS4TB/WS4TBr/MoriahCareFrame --json` exited 0.
- Added unrelated-pair regression coverage using `CodeGraftScope` semantics so
  generated standalone repos are not hardcoded to MoriahCareFrame names.
- Proved a fresh unrelated E2E with real repos
  `/Volumes/WS4TB/WS4TBr/codegraft` and
  `/Volumes/WS4TB/WS4TBr/codescope`: Repo Necromancer generated a standalone
  `/tmp/.../CodeGraftScope` repo, that repo's generated pytest test passed, its
  CLI ran with `evidence/source_profiles.json`, and the packet demo ran.
- Re-ran `python -m pytest -q tests/test_repo_necromancer.py`; all 6 tests
  passed.

Assumptions:

- Source A is treated as a filesystem source, not a git repo, because
  `git -C /Volumes/WS4TB/WS4TBr/MORIAH/moriah_omega` reports that it is not a
  git repository.
- Source B had pre-existing dirty state outside `Proto_Dev_Req`; the generator
  did not intentionally modify it.
- The existing standalone repo path is non-empty, so the updated generator
  correctly refuses to overwrite it. Use a fresh path or remove/rename the
  existing repo only after an explicit destructive-action decision.

## Outcome - step `moriah-careframe-transplant-packet` - `green`

- Cited methodologies: `f3e564c3-a10c-4fc8-a2ce-ec945eed6f99`,
  `34cb9a68-3cce-48fd-b1c4-986c23bded63`
- Outcome row: `35879a3b-e25b-4dfd-9a9f-f6158d05cbf8`
- run_hash: `4f9f2f50a96c2219`
- Evidence: `python -m pytest -q tests/test_repo_necromancer.py` passed
  3 tests; generated CLI help and demo run exited 0; full `python -m pytest -q`
  still fails in three pre-existing non-packet areas recorded in
  `docs/showpieces/repo_necromancer/moriah_careframe/TEST_RESULTS.md`.

## 2026-06-21 Public Cleanup

- Under the active CAM_Codx final public cleanup goal, classified stale CAM_CAM
  launch snapshots, generated batch results, and the old coverage baseline for
  removal from public Git tracking.
- Removed only files listed in
  `/Volumes/WS4TB/repo622sn/CAM_Codx/docs/repo_inventory/PUBLIC_REPO_CLEANUP_MANIFEST.json`.
- Updated README/showpiece/GOAL references so no public doc points at the
  removed launch snapshot files.
- Left pre-existing untracked `CAM_Codx_last5291pm.txt` untouched.

## 2026-06-21 Repo Necromancer Merger Guidance

- Added `--merger-brief` and `--merger-brief-file` to
  `scripts/repo_necromancer.py` so users can supply product-owner expectations
  for the merged output before the packet is handed to CAM_Codx.
- The generator now writes the merger guidance into `evidence.json`,
  `NECROMANCER_SHOWPIECE.md`, `CAM_CODEX_GOAL.md`, the fused app README, the
  demo output, and the generated standalone repo README.
- Added regression coverage proving the merger guidance survives packet and
  standalone repo generation.

## 2026-06-22 CAM-preMine

- Added `claw.premine`, a remote GitHub assessment module that scores candidate
  repos before local clone/mining.
- Added `cam premine` with table, JSON, Markdown report, JSON output, and JSONL
  candidate-queue output modes.
- Encoded the 2026-06-22 example repos as fixture-based regression tests:
  `Understand-Anything`, `taste-skill`, `blockify-agentic-data-optimization`,
  `GLOSSOPETRAE`, and `ST3GG`.
- Added docs under `docs/plans/` and a README workflow for pre-clone triage.
- Assumption: v1 is CLI-first. Forge/Dashboard UX, durable SQLite persistence,
  watchlist scheduling, and remote safe-harvest ingestion are follow-up layers.
- Verified `python -m pytest -q tests/test_premine.py` passed with 7 tests
  after implementation.

## 2026-08-08 Mining-model benchmark execution and compatibility fixes

- Executed run `20260808T172212Z-4ce70e93`: 24 exact-model calls across three
  frozen production mining prompts, with no fallback and no corpus writes.
- Recorded provider spend was `$1.9039158408`; a discarded DeepSeek rolling-
  alias probe has a conservative maximum possible charge of `$0.0015407616`,
  so the evidence-backed upper bound is `$1.9054566024` under the `$5` cap.
- Fixed OpenRouter `:batch` routing to use queued `/api/beta/batches` jobs with
  the base model ID, polling, job receipts, and explicit 30-day retention.
- Fixed rolling `~...-latest` validation to accept only same-provider,
  same-family dated resolutions while continuing to reject arbitrary model
  drift. Failed identity checks now retain response text, tokens, and cost.
- Added selected-model resume lanes, deterministic JSON/Markdown benchmark
  reports, conservative spend receipts, and batch-aware latency reporting.
- Normalized two safe mining envelopes (one valid finding object and a
  `{"findings": [...]}` wrapper) and retained rejection of arbitrary text.
- Corrected provenance scoring for class-qualified method names such as
  `Class.method`; file existence and component identifiers remain mandatory.
- No candidate passed the hard promotion gate. Luna had the strongest
  cost/quality balance, GLM 5.2 was cheapest and fast, but both retained at
  least one invalid-provenance result. No profile was promoted.
- Focused verification passed: 206 tests. Full verification: 4,284 passed,
  22 skipped, and four unrelated/baseline failures (LanceDB API mismatch,
  committed `claw.db` versus stale `data/claw.db` assertion, and two live
  ganglion tests unable to open external databases).

## 2026-08-08 Adaptive mining-model tournament harness

- Added immutable stage plans for `first-round`, `heldout`, and `repeat`
  execution under one cumulative authorization.
- Changed new tournament planning to price only executable calls in the current
  stage. Existing historical `BenchmarkPlan` artifacts remain readable.
- Added deterministic advancement using zero-hard-failure eligibility, quality
  floor, average quality, cost per accepted finding, total cost, and stable
  tie-breakers.
- Added adaptive candidate contraction when fewer finalists fit the remaining
  budget; the planner never increases the authorization.
- Generalized execution to run any frozen stage with exact models, no fallback,
  returned-model validation, redacted receipts, and resume accounting that does
  not double charge completed calls.
- Added `cam models benchmark advance` and stage-aware `plan`, `run`, and
  `report` behavior.
- Added `cam models benchmark select`, which emits distinct quality, budget,
  fast, and batch candidates and explicit promotion commands without changing
  a profile.
- Persisted the normalized catalog snapshot beside each plan so execution uses
  the exact availability, capabilities, and prices that were authorized.
- Independent review initially blocked paid execution on charged-failure resume,
  repeat-control identity, exact receipt/catalog binding, and conservative-cost
  gaps. Added regression tests and mitigated every Critical and Important
  pre-spend finding.
- Failed receipts are now non-retriable during normal resume, their actual cost
  is counted, and unreconciled failures reserve their frozen maximum. Batch
  submission and polling are separate: the queued job ID is atomically written
  before polling, local timeout/network failures remain resumable, and restart
  polls the same job without a second submission.
- Repeat plans now require the root first-round plan, copy its prompt, source,
  token, reasoning, seed, transport, price, and catalog controls, and report
  same-fixture quality, finding-count, validity, and cost deltas.
- Reports now reject extraneous/stale receipt IDs and prompt/source lineage
  drift. Provenance is scored from the content-addressed frozen fixture rather
  than a repository that may have changed after execution.
- Normalized catalog snapshots recompute entry and full-catalog digests before
  execution. Tournament runs use the sibling frozen catalog by default and
  refuse output directories bound to another plan.
- Provider costs that exceed the cap are reconciled exactly once and written to
  a failed receipt before the cap error propagates, preventing hidden spend or
  an automatic charged retry.
- Current implementation verification: 224 focused tests and 455 tests in the
  available broader mining/model gate pass. Targeted static checks and `git diff
  --check` pass. The broader gate retains one pre-existing aiosqlite event-loop
  cleanup warning.
- The full repository suite reports 4,326 passed and 22 skipped with the same
  four unrelated baseline failures: one LanceDB API mismatch, one local
  `claw.toml` path expectation, and two unavailable Ganglia fixture databases.
- The first execution attempt stopped before client execution because the
  frozen full-catalog digest changed across Python hash seeds. Root cause was
  unordered `frozenset` serialization inside the aggregate digest. Added a
  three-process hash-seed regression test, canonicalized the digest payload,
  preserved the rejected artifacts as `first-round-stale-digest`, and froze a
  fresh validating plan with unchanged per-model prices and cost ceilings.
- The hard cumulative authorization remains `$5.00`; conservative prior spend
  is `$2.0348919774`, leaving `$2.9651080226` before the corrected tournament.
- Paid first round `20260808T212139Z-9f299170-first-round` completed all 24
  exact calls with zero failed/resumed calls and `$1.902849538` recorded spend.
  The corpus and `model_profiles.toml` hashes remained unchanged.
- Initial scoring incorrectly hard-failed complete fenced JSON even though the
  production `parse_findings` path explicitly accepts that envelope. Added a
  regression test and aligned the benchmark classifier with the production
  parser; malformed, truncated, unsupported, secret-like, and invalid-
  provenance outputs remain hard failures.
- Corrected first-round leaders are Qwen 3.8 Max (quality `93.09`), Grok 4.5
  (`90.40`), and Kimi K3 (`83.67`), all with zero hard failures. The remaining
  models are excluded by provenance or truncation gates.
- GLM 5.2 provider cost was `$0.27956364`, about 7.8 times its frozen catalog
  lane maximum of `$0.035829352`; do not treat its nominal price as reliable
  budget evidence until OpenRouter routing/pricing is reconciled.
- The zero-spend held-out plan advances Qwen and Grok for four calls with a
  `$0.68782` stage maximum and `$4.6255615154` cumulative maximum. Kimi was
  eligible but excluded because all three did not fit the remaining budget.
- Held-out execution completed four calls for `$0.6904328`. Grok passed both
  unseen repositories at `81.22` average quality with zero hard failures; Qwen
  failed OpenCLI provenance and was excluded.
- Grok's same-prompt repeat completed for `$0.014412`, remained valid, and
  scored `87.20` versus `100.00` originally (`-12.80`). The final selector
  assigns Grok to quality, budget, and synchronous-speed roles without changing
  the active profile.
- Tournament spend was `$2.607694338`; provider-recorded cumulative spend was
  `$4.6425863154`. Reserving `$0.10069` for one ambiguous bounded Terra retry
  yields an operator-conservative `$4.7432763154`, below the `$5` authorization.
- Added explicit `mine-workspace --profiles` propagation through
  `ClawFactory.create`, so a deliberate role promotion now controls the actual
  mining runtime. Without it, `claw.toml` remains authoritative. Scan-only
  workspace discovery now honors its explicit `--config` path.
- The initial no-spend `--changed-only --scan-only` pass from the isolated
  benchmark worktree found 61 candidates and reported 59 eligible, but that
  shell did not pin the live DB variables and consulted an empty worktree-local
  ledger. Treat that count as superseded.
- On 2026-08-09, fast-forwarded the tested branch to the canonical CAM_CAM
  `main`, promoted `x-ai/grok-4.5` for `mining-quality` and `mining-budget` with
  separate rollback receipts, and verified 162 focused model/profile/miner
  tests. The pre-existing modified `claw.toml` and SQLite sidecars were
  preserved.
- The authoritative live no-spend scan pinned both DB environment variables,
  the absolute config, and the explicit profile. It found 61 candidates and 48
  eligible (36 under `repo622sn`, 12 under `repos2mine`), after two iteration
  deduplications and 11 unchanged-ledger exclusions. Paid mining has not
  started because no separate maximum dollar authorization was specified.

## 2026-08-09 Hard-capped exact-model mining

- Added a persistent request-level mining budget receipt that reserves a
  conservative maximum before every OpenRouter HTTP attempt and reconciles
  provider-reported cost after each response.
- Added exact-model enforcement for enabled remote mining routes, disabled LLM
  fallbacks, rejected returned-model drift, and made budget failures terminal
  across primary, escalation, content-reduction, and chunk recovery paths.
- Added all-or-none `mine-workspace` controls: `--max-cost-usd`,
  `--exact-model`, and `--budget-receipt`. Scan-only remains no-spend and the
  legacy no-budget path remains unchanged.
- Removed the existing unreserved live LLM probe from capped runs. Environment
  key checks still run; the first live model call validates access inside the
  receipt authorization.
- Focused Task 4 regression gate passed 289 tests across CLI, miner, recovery,
  profiles, LLM accounting, and budget receipt behavior. CLI help exposes all
  three controls, targeted fatal/static checks passed, and `git diff --check`
  passed.
- No paid changed-only mining calls were made during implementation. The
  authorized live run remains capped at `$7` and exact model
  `x-ai/grok-4.5`; final repository, finding, and spend evidence will be added
  after integration and execution.
- Release verification passed 308 focused tests and 538 tests in the current
  broader mining/model gate. The broader gate retained the previously recorded
  non-fatal aiosqlite event-loop cleanup warning. Targeted Ruff checks and
  `git diff --check` passed.
- Independent pre-merge review found fail-open boundary risks in receipt
  concurrency, non-finite accounting, terminal-state reuse, remote embeddings,
  assimilation exception handling, and missing returned-model evidence. All
  were accepted and mitigated with lifecycle file locking, atomic unique-temp
  writes plus fsync, strict monetary validation, terminal-state monotonicity,
  one in-flight capped request, local-only embeddings for capped runs, and
  budget-error propagation.
- Added adversarial regressions for corrupt resumed receipts, a second live
  runner, terminal receipts, factory and empty-discovery exits, remote
  embeddings, missing returned-model metadata, request serialization, and
  assimilation stopping at its first cap boundary. The updated focused gate
  passes 413 tests and the expanded mining/model regression gate passes in
  full. No paid provider request has been made by these tests.
- Fresh full-suite verification completed with `4382 passed`, `22 skipped`,
  and the same four known baseline failures: one installed LanceDB API
  mismatch, one stale `claw.toml` path expectation, and two unavailable
  Ganglia fixture databases. Independent re-review of the completed mitigation
  reported no Critical or Important findings and a merge verdict of yes.

## Rescue Ladder - step `hard-capped-mining-release-gate` - attempt 1

### Rung 1: alternate pattern
- Searched: `pytest broader mining model verification gate fails because planned test file paths no longer exist`
- Considered: `03b2c0af-318d-45b5-8ffb-d9f525add8df`
- Selected / Rejected: rejected because the recalled methodology was stale and
  concerned parametrized fixtures rather than verification-command drift.

### Rung 2: bisect
- Diff hunks tried: 0; `rg --files tests` proved the implementation-plan names
  `tests/test_llm_client.py` and `tests/test_miner_prompts.py` were stale.
- Smallest failing hunk: none; the failure was in the historical command, not
  the current code diff.

### Rung 3: escalate
- BLOCKER.md updated: no
- User question: none; the corrected gate used the current `test_llm.py` and
  mining prompt fixture coverage and passed.

## 2026-08-09 Zoomcam mining and Swift detection follow-up

- A pinned no-spend scan of `/Volumes/WS4TB/waswiki/zoomcam` found seven
  eligible projects. The hard-capped Grok 4.5 run completed 54 provider calls
  with zero failures and stored 45 enriched findings from `MLX-SAGE`,
  `sage-wiki`, `CAM_Assistant`, `prime-agent`, and `semantica`.
- The main zoomcam receipt recorded `$1.9001416` actual spend. `ScreenSage`
  contained documentation only. `ZoomitForMac` contained 38 tracked Swift
  files but was rejected before serialization because Swift was missing from
  the language census.
- Added a pure-Swift regression that failed with an empty zone set, then added
  the minimal Swift-to-`misc` mappings. The focused regression passed, and
  `tests/test_miner_polyglot.py tests/test_miner_brains.py` passed 107 tests
  with the known aiosqlite event-loop cleanup warning.
- A follow-up scan detected `ZoomitForMac` as one eligible `misc` repo. Its
  fresh receipt capped maximum exposure at `$5.0998584`, so prior actual spend
  plus the follow-up maximum was exactly `$7`.
- The follow-up completed six Grok 4.5 calls with zero failures, spent
  `$0.191138`, and stored five enriched, novelty-scored methodologies in the
  misc ganglion. SQLite integrity passed, the canonical ledger contains all
  five IDs, and an immediate changed-only scan returned zero eligible repos.

## 2026-08-09 repos.txt no-spend mining inventory

- Read all 11 existing roots in `/Volumes/WS4TB/repos.txt` and ran one combined
  authoritative `--changed-only --scan-only` pass with depth 8.
- The scan found 352 unique paths, retained 334 canonical candidates after 18
  iteration deduplications, and classified 323 as eligible: 316 never mined and
  seven changed since their last ledger record.
- The seven changed repos are `CAM_Codx`, `SkillOpt`,
  `blockify-agentic-data-optimization`, `mydisasters`, `fractal`, `careframe`,
  and `finESS`.
- Prepared and re-scanned a bounded 15-repo proposal consisting of all seven
  changed repos plus eight high-yield new repos. All 15 remain eligible; no paid
  call was made for this proposed batch pending explicit user approval.
- `tabfm` remains eligible but is excluded from the proposal because the prior
  capped run repeatedly timed out without a durable result.

## 2026-08-09 Priority 15 changed-only mining

- After explicit user approval, re-scanned the exact 15-repository proposal
  against the pinned live corpus and confirmed 15 discovered / 15 eligible
  before spending.
- Executed one single-writer hard-capped run with exact model
  `x-ai/grok-4.5`, `$5.00` authorization, no fallback, no generated tasks, and
  a fresh receipt at
  `data/mining_runs/2026-08-09-repos-txt-priority15-grok-4.5-5usd.json`.
- The run completed 96 of 96 calls with zero failures, spent `$3.0921648`,
  processed all 15 entries, and stored 80 enriched findings from 14
  source-bearing repositories. `taste-skill` incurred no call and was skipped
  because serialization found no recognizable source files.
- Verified the receipt is terminal and mode `0600`; every requested and
  returned model is Grok 4.5; all five SQLite integrity checks are `ok`; all 80
  unique ledger IDs exist across the root and language ganglia; and all 80 new
  rows have capability, novelty, and potential data.
- The live key reported `$2.50175256` remaining after the run. The exact key
  usage delta matched the receipt spend.
- The focused current-source miner gate passed 107 tests with the known
  aiosqlite cleanup warning. A bare test command was proven to import an older
  editable CAM checkout, so verification was rerun with this checkout's
  absolute `PYTHONPATH` before publication.
- An immediate authoritative changed-only scan excluded the 14 mined repos and
  retained only `taste-skill`. Re-running it unchanged would skip again without
  spend; supporting documentation/skill-only repos requires a separate product
  decision or scanner/miner eligibility fix.
- Full evidence is recorded in
  `docs/reports/2026-08-09-priority15-grok-mining-results.md`.

## 2026-08-10 CAM_Codx manager integration gate

- CAM_Codx now owns the packet/approval workflow; CAM_CAM remains the runtime
  owner. No model profile or live corpus write occurs from the manager itself.
- Hardened tournament advancement to reject quality reports whose fixture count,
  receipt IDs, model IDs, or fixture IDs do not match the frozen parent plan.
- Repeat-stage fixture selection now follows the root first-round plan even if a
  later suite file changes fixture ordering.
- Focused model/profile/tournament/self-enhancement verification passed with
  `88 passed`; no paid provider request was made by these tests.
- A manager-approved, supervised self-enhancement run executed one task in a
  disposable copy with `--max-tasks 1 --skip-swap`. CAM's candidate validation
  rejected the generated `src/claw/memory/auto_fix.py` change after its focused
  regression failed 5 tests. No live source, database, model profile, or
  configuration was swapped; the failed candidate is not being adopted.

## 2026-08-10 Read-only Development Brief query

- Added `cam brief-query QUERY --db /absolute/path/to/claw.db --json` as the
  narrow runtime seam for CAM_Codx Development Brief recall.
- The command opens only the explicitly supplied primary database using a
  read-only immutable SQLite URI, returns FTS provenance JSON, and does not
  initialize schema, enable WAL, record retrieval usage, load embeddings, call
  a provider, or query sibling corpora.
- Fixture-backed proof passed `4` query tests. Final focused verification ran
  `tests/test_read_only_brief_query.py`, `tests/test_tool_schemas.py`, and
  `tests/test_integration_wiring.py` with `78 passed`; `brief-query --help`
  passed. The no-mutation assertion covers only a synthetic test database, not
  a live corpus.

## 2026-08-11 Development Brief Documentation Alignment

- Updated the runtime README, CAM_Codx integration handoff, command guide,
  operator cheat sheet, and changelog to make `cam brief-query` discoverable as
  the runtime component of CAM_Codx's Development Brief.
- The operator surfaces now state the explicit-primary-database, read-only
  boundary and direct users to CAM_Codx for target inspection, evidence labels,
  and continue/mitigate/re-develop guidance.
- Re-verified the focused Development Brief gate (`78 passed`) and
  `PYTHONPATH=src python -m claw.cli brief-query --help`; `git diff --check`
  passed.
- This documentation pass changed no runtime code, SQLite database, model
  profile, provider configuration, or mining state.

## 2026-08-12 CAM_Codx Control-Plane Documentation Alignment

- Audited the complete registered Typer command tree, nested groups, and hidden
  compatibility aliases for the CAM_Codx capability inventory.
- Confirmed that `cam chat` executes the mining route but reports build/create
  and fix/enhance routes as not wired.
- Approved CAM_Codx as the normal manager for all CAM_CAM capabilities while
  preserving direct CAM_CAM usage for troubleshooting, runtime development,
  recovery, regression isolation, and existing expert scripts.
- Updated the README, raw command decision tree, operator cheat sheet,
  CAM_Codx integration guide, historical GOAL pointer, and decision record.
- These are truth-alignment changes only. No runtime command, database, model,
  provider, configuration, or feature flag changed; the unified CAM_Codx skill
  is not yet implemented.
- Focused documentation-truth verification passed `51` CLI UX and read-only
  brief-query tests with `PYTHONPATH=src`, followed by `git diff --check`.
  CAM_CAM's `.venv` does not include pytest, so the test runner was the system
  Python with imports pinned to this checkout.

## 2026-08-12 CAM command capability manifest

- Added a deterministic schema-version-1 inventory of all registered Typer
  command and group paths, including effective hidden status and nested paths.
- Exposed the inventory through read-only `cam doctor capabilities --json`;
  regression coverage blocks config, database, provider, and filesystem side
  effects.
- TDD RED failed on the missing helper and command as expected. Focused GREEN
  passed `3` manifest tests, and the combined manifest/CLI UX gate passed
  `50` tests.
- Review hardening added regressions for Typer's unnamed-group flattening and
  actionable, deterministically sorted duplicate-path diagnostics. A fresh
  subprocess proof now installs filesystem, SQLite, network, and child-process
  tripwires before importing the CLI, with isolated home/config/cache/temp
  paths and content-hashed sentinels.

## 2026-08-14 managed source-to-outcome SWE runs

- Added `claw.managed_runs`, a persistence-only service over existing CAM-SEQ
  task plans, application packets, pair events, landing events, outcome events,
  run connectomes, edges, and run events. No table, migration, provider client,
  build path, or parallel knowledge store was added.
- A run can be started or safely continued with one plan; attach a pinned
  mining receipt; record direct-precedent, transferable-analogy, or
  new-hypothesis candidates as selected, rejected, deferred, or
  needs-inspection; link an approved packet/pair; record target-relative
  landings; and render a deterministic source-to-outcome report.
- Outcomes preserve the approved four-state vocabulary: `verified_success`,
  `verified_partial`, `verified_failure`, and `not_verified`. Only a verified
  success may increment positive component evidence or be recipe-eligible.
  Failed verification increments negative evidence; partial and unverified
  results remain non-positive. A corrected proof must name the exact latest
  outcome it supersedes, so the failed evidence remains visible.
- Added hidden `cam managed-run JSON --config PATH` for CAM_Codx and direct
  runtime troubleshooting. The JSON is one subprocess-list argument; the seam
  initializes no agent/provider layer and does not execute build, enhance,
  validation, mining, promotion, or configuration logic.
- TDD RED stopped at the intended missing `claw.managed_runs` module. GREEN is
  `11 passed` for managed-run and CAM-SEQ foundation coverage and `67 passed`
  across the selected CLI manifest/UX, managed-run, CAM-SEQ, and application
  packet surface. Focused Ruff checks for the new module/tests, CLI help, and
  `git diff --check` pass. Tests used only in-memory fixture databases.
- The hidden command increases the live manifest to `140` paths with `16`
  hidden entries. The CAM_Codx registry remains pinned to the Task 2 manifest;
  Task 8 must register this canonical managed seam before cross-repository
  gates can pass. This is recorded as planned integration work, not current
  cross-repo compatibility.
- The approved release-plan path `tests/planning/test_application_packet.py`
  does not exist in this checkout; verification used the current
  `tests/test_application_packet.py` truth path.
- Specification and quality review rejected the first implementation because
  plan identity omitted approval-bearing fields, the plan was duplicated in a
  run event, proof was caller-asserted, revisions accumulated recall counters,
  and repository calls committed each half of multi-record operations.
- The hardened implementation binds the complete reviewed plan by SHA-256 on
  its connectome edge. Candidate decisions explicitly supersede the latest
  slot decision, exact receipt/decision/pair/landing/outcome retries are
  idempotent, pairing uses the latest slot selection, and all supplied mining
  and verification receipts must exist and match their recorded SHA-256.
- Positive evidence now requires a stored `VERIFIED` application packet,
  every required packet proof gate in `pass`, a matching receipt-backed gate
  record with list-form argv and exit code zero, and at least one test
  reference. Caller text alone cannot strengthen trust or enable a recipe.
- Failure-to-success correction atomically replaces the active component
  counters (`failure -1`, `success +1`) while keeping the original failed
  outcome as history. A success cannot be superseded inside the same run;
  contradictory later evidence must start a new run, preventing older CAM
  consumers from seeing a superseded positive row.
- Fixed `DatabaseEngine.transaction()` so repository-style writes no longer
  auto-commit inside a transaction. `BEGIN IMMEDIATE` plus an engine lock makes
  validation and writes one unit, hides partial state from other tasks, rolls
  back normal errors and cancellation, and rejects nested transactions. Forced
  start-edge, pair-edge, and outcome-event failures leave no partial rows.
- Aggregate run status is derived from all approved slots instead of the most
  recently written slot. The hidden CLI refuses missing config/database paths
  rather than creating a database at a typo, and does not initialize providers.
- Hardened verification passes `40` database/managed-run/CAM-SEQ tests and `96`
  selected database, CLI manifest/UX, managed-run, CAM-SEQ, and application
  packet tests. New-module Ruff checks, CLI help, and `git diff --check` pass.
- The first hardened quality re-review found two remaining defects: successful
  multi-slot runs stored status from only the current slot, and a caller could
  hash an unrelated file while separately asserting gate/command/result data.
- Added RED regressions for two-slot success, partial, and failure aggregation;
  unrelated JSON receipts; and mismatches in each gate, argv, exit, target, and
  target-revision field. `cam.verification-receipt.v1` is now parsed and must
  match the outcome and digest-bound plan target identity exactly. Stored run
  status is recomputed from every slot's active classified outcome.
- Final second-review remediation verification passes `51` focused
  database/managed-run/CAM-SEQ tests and `107` selected database, CLI
  manifest/UX, managed-run, CAM-SEQ, and application-packet tests. Focused Ruff
  and `git diff --check` also pass.

## 2026-08-15 Task 7 crash-recovery receipt hardening

- Recreated the lost temporary feature worktree from the durable local
  `feat/cam-codx-control-plane` branch without modifying the SSD checkout.
- Added RED/GREEN regression proof that verification reads a receipt once: the
  exact captured bytes are SHA-256 hashed, UTF-8 decoded, and JSON parsed
  without reopening the path. This closes the receipt TOCTOU gap identified by
  the recovered autonomous goal.
- `cam.verification-receipt.v1` and typed verification evidence now each bind
  the exact `plan_id` and full SHA-256 of the authorization-bearing managed
  plan, in addition to gate, list-form argv, exit code, canonical target, and
  immutable target revision.
- Focused Task 7 gate: `31 passed` for `test_managed_runs.py` and
  `test_camseq_foundation.py`; `git diff --check` passed. Pytest could not
  create its optional `.pytest_cache` inside the recovery clone because of the
  managed sandbox, but test execution and fixture database writes succeeded.

## 2026-08-16 Model comparison verdict command

- Added the read-only `cam models benchmark compare` adapter over the existing
  evidence-only baseline comparison. It accepts the three completed stage
  reports and emits a `better`, `not_better`, `rejected`, or `inconclusive`
  verdict; it cannot call a provider, write a profile, or promote a model.
- Test-first evidence: the CLI test initially failed because `compare` was not
  registered. After the adapter, `tests/test_models_cli.py`,
  `tests/test_model_comparison.py`, and `tests/test_cli_capability_manifest.py`
  passed (`22 passed`). Optional pytest-cache creation remains sandbox-blocked.
- Next action: pin this new canonical command in the CAM_Codx capability
  registry and expose only its read-only manager packet.

## 2026-08-16 Sparse evidence graph: Phase 1 baseline

- Created the pure `claw.knowledge_graph.contract` versioned contract and a
  deterministic six-node fixture corpus with source, test, outcome,
  methodology, and legacy-association evidence. It neither accesses `claw.db`
  nor changes current hybrid retrieval.
- TDD RED was the absent `claw.knowledge_graph` module. GREEN proves explicit
  and association edges remain distinct, association cannot be factual-path
  eligible, and fixture health metrics are deterministic (`3 passed`).
- Recorded the inventory/classification in
  `docs/knowledge_graph_phase1_baseline.md`: `co_retrieval` remains
  association-only; contradiction, competition, and assimilation edges remain
  inferred and excluded until receipt-backed; repository topology remains
  presentation-only.
- Next action: run the adjacent legacy graph regressions and inspect the Phase
  1 diff. Phase 2 is deferred: no extractor, migration, live-data scan, or
  CAM_Codx graph packet has been started.

## 2026-08-16 Sparse evidence graph: Phase 2 local extraction slice

- Added `extract_evidence_graph(root, source_revision=...)`, a deterministic
  local-only Python extractor. It emits receipt-backed explicit `declares`,
  `covered_by`, and `verified_by` edges from AST structure, imported test calls,
  and named outcome references.
- TDD RED was the missing extractor module. GREEN proves fixture nodes and
  edges, exact SHA-256 provenance from the source bytes read, explicit-only
  evidence class, and factual-path eligibility (`4` graph-specific tests).
- Broader adjacent graph verification passed `269` tests with Ruff and
  `git diff --check` green. No database migration, live corpus scan, provider
  call, embedding, model-assisted resolution, graph traversal, or CAM_Codx
  route was added.
- Next decision: design an additive persistence/import seam for the extracted
  contract and legacy association labels, with a rollback path, before any
  live-data ingestion or graph query surface.
