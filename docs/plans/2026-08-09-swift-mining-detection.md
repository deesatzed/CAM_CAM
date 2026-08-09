# Swift Mining Detection Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make pure-Swift repositories detectable and mine `ZoomitForMac` without exceeding the already-approved cumulative `$7` authorization.

**Architecture:** Extend the existing extension-to-language census so Swift is routed to the existing `misc` brain. Preserve all current prompts, databases, thresholds, and budget machinery.

**Tech Stack:** Python 3.13, pytest, Typer CAM CLI, SQLite, OpenRouter hard-cap receipts.

---

### Task 1: Add the failing pure-Swift regression

**Files:**
- Modify: `tests/test_miner_polyglot.py`

**Step 1: Write the failing test**

Create three `.swift` files in a temporary repository and assert that
`detect_all_repo_languages()` returns one `misc` zone containing `.swift` with
a file count of three.

**Step 2: Run the focused test to verify it fails**

Run:

```bash
PYTHONPATH=src /Users/o2satz/miniforge3/envs/py313/bin/python -m pytest \
  tests/test_miner_polyglot.py::TestDetectAllRepoLanguages::test_pure_swift_repo_uses_misc_brain -q
```

Expected: fail because the returned zones are empty.

### Task 2: Implement the minimal detection mapping

**Files:**
- Modify: `src/claw/miner.py`

**Step 1: Add only the necessary mappings**

Add `"swift": "misc"` to `_LANGUAGE_TO_BRAIN` and `".swift": "swift"` to
`_EXT_TO_LANGUAGE`.

**Step 2: Verify the regression and surrounding module**

Run:

```bash
PYTHONPATH=src /Users/o2satz/miniforge3/envs/py313/bin/python -m pytest \
  tests/test_miner_polyglot.py -q
git diff --check
```

Expected: all tests pass and diff check exits zero.

### Task 3: Verify and mine the canonical Swift repository

**Files:**
- Create at runtime: `data/mining_runs/2026-08-09-zoomit-grok-4.5-5.0998584usd.json`
- Update at runtime: `claw.db` or the routed `misc` ganglion database
- Update at runtime: `mining_registry.json`

**Step 1: Run scan-only against the exact repo root**

Pin both DB environment variables, current source via `PYTHONPATH`, the absolute
config, and explicit profiles. Require `ZoomitForMac` to be the only eligible
repository.

**Step 2: Run paid mining with the residual cap**

Use `--exact-model x-ai/grok-4.5`, `--max-cost-usd 5.0998584`, the fresh
receipt, `--no-tasks`, and `--max-repos 1`.

**Step 3: Verify durable results**

Validate receipt completion and exact returned model, sum cumulative receipt
authorization to no more than `$7`, query new methodologies and enrichment,
run SQLite integrity checks, confirm the canonical ledger record, and perform a
post-run changed-only scan.

### Task 4: Record operational evidence

**Files:**
- Modify: `PROGRESS.md`
- Modify if a durable architecture choice changed: `DECISIONS.md`

Record the root cause, regression result, mining receipt, cost, findings,
database routing, and any remaining changed-only caveats. Do not modify or
stage the pre-existing `claw.toml` changes or SQLite sidecars.
