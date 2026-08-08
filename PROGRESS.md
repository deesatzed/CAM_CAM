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
- A current no-spend `--changed-only --scan-only` pass over `repo622sn` and
  `repos2mine` found 61 unique candidates and classified 59 as eligible after
  two iteration deduplications. Paid mining did not start because those repos
  require a separate budget beyond the comparison authorization.
