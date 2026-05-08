# CAM Repo Consolidation Plan

Date: 2026-05-08

## Decision

Use `CAM_CAM` as the canonical umbrella repository.

Merge `CAM-Pulse` into `CAM_CAM` as the core CAM engine, because both repositories already share the same package identity (`claw`), CLI shape, source layout, and product claims.

Keep `CAM-RAG` separate for now as a specialist RAG package. Integrate it through a stable adapter first. Only physically merge it after its API, tests, benchmark story, and local changes are reconciled.

## Target Product Shape

```text
CAM_CAM
├── src/claw/                     # CAM-PULSE core engine
│   ├── pulse/                    # discovery, mining, freshness, assimilation
│   ├── memory/                   # KB, retrieval, lifecycle, bandit, fitness
│   ├── agents/                   # OpenRouter/local model adapters
│   ├── evolution/                # self-correction, routing, learning
│   ├── verifier.py               # validation gates
│   └── ...
├── apps/
│   ├── repo_rescue_desk/         # CAM_CAM public showpiece
│   ├── embedding_forge/
│   └── other app proofs
├── integrations/
│   └── cam_rag/                  # thin adapter contract, not full copy yet
├── docs/
│   ├── cam_cam_showpiece.html
│   ├── proof notes
│   └── consolidation history
└── tests/
```

`CAM-Pulse` becomes either archived or a redirect repository after parity is proven.

`CAM-RAG` remains:

```text
CAM-RAG
├── src/cam_rag/                  # reusable RAG platform
├── apps/ragamuffin/              # first RAG app
├── benchmarks/
└── tests/
```

## Guiding Rules

1. Do not rewrite public git history.
2. Do not delete or archive `CAM-Pulse` until `CAM_CAM` passes parity tests.
3. Do not merge `CAM-RAG` code while its local copy is behind origin or has uncommitted changes.
4. Preserve evidence: every consolidation phase needs a commit, test output, and a short note.
5. Public messaging must use one identity:
   - `CAM_CAM` = umbrella/showpiece repo
   - `CAM-PULSE` = core learning engine inside CAM_CAM
   - `CAM-RAG` = specialist RAG capability integrated by contract

## Phase 0: Freeze And Inventory

Goal: establish exact source state before moving anything.

Actions:

1. Confirm remotes and branches for all three repos.
2. Fetch latest `origin/main` for all three.
3. Record commit SHAs:
   - `CAM_CAM`
   - `CAM-Pulse`
   - `CAM-RAG`
4. Record dirty state.
5. Save inventory to `docs/CAM_REPO_CONSOLIDATION_STATUS_2026-05-08.md`.

Current observed state:

- `CAM_CAM`: clean and tracking `origin/main`.
- `CAM-Pulse`: clean and tracking `origin/main`.
- `CAM-RAG`: local copy is behind `origin/main` by 6 commits and has uncommitted/untracked local changes.

Exit gate:

- Status document exists.
- No destructive operations performed.

## Phase 1: Make CAM_CAM The Canonical Public Entry

Goal: remove identity ambiguity before code consolidation.

Already mostly done:

- GitHub Pages root points to CAM_CAM Repo Rescue Desk.
- Showpiece explains `CAM_CAM`, `CAM-PULSE`, and `Repo Rescue Desk`.
- Public sample artifacts exist.
- CI, Test Suite, and Pages passed after the landing-page repair.

Remaining actions:

1. Update `README.md` top section so it no longer reads as only `CAM-PULSE`.
2. Add a short "Repository Roles" section:
   - `CAM_CAM`: canonical repo and public showpiece layer.
   - `CAM-PULSE`: core engine lineage.
   - `CAM-RAG`: specialist RAG platform.
3. Add a "Migration Status" note linking to this plan.

Exit gate:

- `README.md` and GitHub Pages tell the same story.
- `python -m html.parser docs/cam_cam_showpiece.html` passes.
- CI passes.

## Phase 2: CAM-Pulse Parity Diff

Goal: identify exactly what `CAM-Pulse` has that `CAM_CAM` lacks.

Actions:

1. Compare core code:

   ```bash
   diff -qr /Volumes/WS4TB/CCam/CAM-Pulse/src /Volumes/WS4TB/CCam/CAM_CAM/src
   diff -qr /Volumes/WS4TB/CCam/CAM-Pulse/tests /Volumes/WS4TB/CCam/CAM_CAM/tests
   diff -qr /Volumes/WS4TB/CCam/CAM-Pulse/docs /Volumes/WS4TB/CCam/CAM_CAM/docs
   ```

2. Classify differences:
   - already absorbed into `CAM_CAM`
   - newer in `CAM-Pulse`, should import
   - newer in `CAM_CAM`, should keep
   - conflicting, needs manual review
   - generated/cache, should ignore
3. Produce `docs/CAM_PULSE_PARITY_DIFF_2026-05-08.md`.

Known high-risk areas from initial comparison:

- `src/claw/agents/interface.py`
- `src/claw/cycle.py`
- `src/claw/db/schema.sql`
- `src/claw/db/engine.py`
- `src/claw/memory/error_kb.py`
- `src/claw/memory/fitness.py`
- `src/claw/miner.py`
- `src/claw/pulse/assimilator.py`
- `src/claw/verifier.py`
- `src/claw/web/dashboard_server.py`

Exit gate:

- No code copied yet.
- Diff classification is complete.

## Phase 3: Import CAM-Pulse Engine Improvements

Goal: bring missing `CAM-Pulse` core improvements into `CAM_CAM` without losing CAM_CAM showpiece work.

Merge order:

1. Tests and proof artifacts first.
2. Low-risk docs and config.
3. Agent/model routing changes.
4. Defense chain:
   - deterministic auto-fix
   - correction loop
   - agent rotation
   - failure knowledge
5. Memory and fitness changes.
6. Mining and assimilation changes.
7. Protected core files last:
   - `src/claw/verifier.py`
   - `src/claw/core/factory.py`
   - `src/claw/db/engine.py`
   - `src/claw/db/schema.sql`
   - `src/claw/core/config.py`

Rules:

- Use small commits.
- After each high-risk slice, run focused tests.
- Never replace `CAM_CAM` wholesale with `CAM-Pulse`; cherry-pick or port changes consciously.

Exit gate:

```bash
python -m pytest apps/repo_rescue_desk/tests -q
./scripts/test_repo_rescue_desk_showpiece.sh
pytest tests/ -q
python -m html.parser docs/cam_cam_showpiece.html
git diff --check
```

## Phase 4: Deprecate CAM-Pulse As A Separate Public Product

Goal: eliminate two competing public repos claiming to be the main CAM.

Actions after Phase 3 passes:

1. Update `CAM-Pulse` README with a clear notice:

   ```text
   CAM-Pulse has moved into CAM_CAM as the core learning engine.
   Canonical repo: https://github.com/deesatzed/CAM_CAM
   ```

2. Keep source code intact for historical reference.
3. Optionally archive `CAM-Pulse` on GitHub after at least one successful CAM_CAM release.

Exit gate:

- No user or landing page path points to `CAM-Pulse` as the active canonical repo.
- `CAM-Pulse` remains recoverable.

## Phase 5: CAM-RAG Contract Integration

Goal: let CAM_CAM use CAM-RAG without prematurely merging codebases.

Actions:

1. Reconcile local `CAM-RAG` state:
   - review local uncommitted changes
   - pull or merge latest `origin/main`
   - run `python -m pytest`
2. Define a minimal RAG adapter contract in `CAM_CAM`, likely:

   ```text
   src/claw/memory/rag_adapter.py
   integrations/cam_rag/
   tests/test_cam_rag_adapter.py
   ```

3. Contract should expose:
   - ingest documents/folders
   - retrieve grounded chunks
   - return citations
   - return confidence/grounding metadata
   - emit receipts CAM can store
4. Add optional dependency docs:

   ```bash
   pip install -e ../CAM-RAG
   ```

5. Add one proof:
   - Repo Rescue Desk identifies a RAG need.
   - CAM_CAM calls CAM-RAG adapter.
   - CAM-RAG returns cited context.
   - CAM_CAM stores/exports the result.

Exit gate:

- CAM_CAM tests pass without CAM-RAG installed.
- CAM_RAG integration tests pass when CAM-RAG is installed.
- No duplicate RAG implementation is copied into `src/claw`.

## Phase 6: Decide Whether To Physically Merge CAM-RAG

Only consider a full CAM-RAG merge if all are true:

1. CAM-RAG is required for default CAM workflows.
2. CAM-RAG API stabilizes.
3. CAM-RAG tests are consistently green.
4. CAM-RAG benchmarks are documented.
5. Keeping it separate causes real friction.

If yes, use a monorepo package layout:

```text
packages/
  cam-rag-platform/
    pyproject.toml
    src/cam_rag/
    tests/
apps/
  ragamuffin/
```

If no, keep CAM-RAG separate and document it as an official specialist ganglion/package.

## Release Criteria For The Consolidated CAM_CAM

The consolidation is done when:

1. `CAM_CAM` is the only repo presented as canonical.
2. `CAM-Pulse` functionality is present in `CAM_CAM`.
3. Repo Rescue Desk still passes.
4. CAM-PULSE defense chain claims remain backed by tests/proof docs.
5. CAM-RAG is callable through a documented adapter or intentionally deferred.
6. GitHub Pages, CI, and Test Suite pass.
7. README and landing page agree on product identity.

## Recommended Next Step

Start with Phase 0 and Phase 1.

Do not start copying `CAM-Pulse` code until the parity diff document exists. The highest risk is overwriting `CAM_CAM` showpiece work with an older or differently branded `CAM-Pulse` file.
