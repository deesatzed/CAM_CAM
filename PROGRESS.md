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
