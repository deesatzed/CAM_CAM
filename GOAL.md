# GOAL.md

This file is the source of truth for the next autonomous launch-refresh run in
this repository.

## Outcome

Prepare `CAM_CAM` for a truthful public launch by refreshing stale metrics,
softening competitor claims, upgrading vulnerable frontend dependencies, and
polishing the README plus static launch pages so they reflect the verified
state of the repo.

The canonical source tree and corpus for this work are:

- Source repo: `/Volumes/WS4TB/WS4TBr/CAM_Codx/CAM_CAM`
- Canonical DB: `/Volumes/WS4TB/WS4TBr/CAM_Codx/CAM_CAM/data/claw.db`
- GitHub remote: `https://github.com/deesatzed/CAM_CAM.git`

The separate CAM_Codx GitHub repo must be treated as a companion repo, not as
the CAM_CAM product repo:

- CAM_Codx remote: `https://github.com/deesatzed/CAM_Codx.git`
- Local candidates:
  - `/Volumes/WS4TB/WS4TBr/CAM_Codx/codex-cam-methodology`
  - `/Volumes/WS4TB/WS4TBr/CAM_Codx/codex-cam-methodology-impl`

Do not copy, merge, or substitute data from
`/Volumes/WS4TB/camcxBU64/CAM_CAM/data/claw.db` during this launch refresh.
That backup DB may have schema and method-shape drift. It is useful only as a
read-only comparison note unless a separate migration/reconciliation goal is
created.

## Why This Goal Exists

The 2026-06-19 launch audit found that CAM_CAM is a real technical proof, but
the public story is drifting:

- README and docs contain stale methodology and test counts.
- Some competitor claims imply other tools lack memory, which is no longer
  accurate.
- `forge-ui` builds only after dependency installation and currently has npm
  audit findings.
- The launch surface is split between Repo Rescue Desk and older CAM-PULSE
  positioning.
- The strongest public hook is Repo Rescue Desk plus the underlying CAM-PULSE
  method engine.

Reference audit artifacts:

- `REPO_MAP.md`
- `RISK_NOTES.md`
- `docs/reports/CAM_CAM_LAUNCH_AUDIT_2026-06-19.md`

## Scope

Allowed modification paths:

- `GOAL.md`
- `README.md`
- `RISK_NOTES.md`
- `REPO_MAP.md`
- `docs/`
- `forge-ui/package.json`
- `forge-ui/package-lock.json`
- `forge-ui/README.md`
- `index.html`
- `cam_cam_showpiece.html`

Allowed companion-repo modification paths, only after confirming the target repo
is the correct local checkout for `https://github.com/deesatzed/CAM_Codx.git`:

- `/Volumes/WS4TB/WS4TBr/CAM_Codx/codex-cam-methodology/GOAL.md`
- `/Volumes/WS4TB/WS4TBr/CAM_Codx/codex-cam-methodology/README.md`
- `/Volumes/WS4TB/WS4TBr/CAM_Codx/codex-cam-methodology/docs/`
- `/Volumes/WS4TB/WS4TBr/CAM_Codx/codex-cam-methodology/meta/`
- `/Volumes/WS4TB/WS4TBr/CAM_Codx/codex-cam-methodology-impl/GOAL.md`
- `/Volumes/WS4TB/WS4TBr/CAM_Codx/codex-cam-methodology-impl/README.md`
- `/Volumes/WS4TB/WS4TBr/CAM_Codx/codex-cam-methodology-impl/docs/`
- `/Volumes/WS4TB/WS4TBr/CAM_Codx/codex-cam-methodology-impl/meta/`

Allowed new artifacts:

- `docs/LAUNCH_METRICS_2026-06-19.md`
- `docs/reports/CAM_CAM_LAUNCH_REFRESH_2026-06-19.md`
- screenshots or browser-smoke artifacts under `docs/reports/launch-smoke/`
  if generated during verification

Out of scope:

- Product behavior changes in `src/claw/`
- Schema changes or DB migrations
- Copying backup DB rows into the canonical DB
- Rewriting the repo architecture
- Rebranding the project away from CAM_CAM/CAM-PULSE without a separate
  product decision
- Publishing, deploying, or pushing to GitHub unless explicitly requested
- Changing CAM_Codx product code as part of this launch-doc cleanup unless a
  separate implementation goal is created

## Required Work

### 1. Lock The Metrics Source

Use only the canonical DB in this repo:

```bash
sqlite3 data/claw.db "select count(*) from methodologies;"
sqlite3 data/claw.db "select lifecycle_state, count(*) from methodologies group by lifecycle_state order by 2 desc;"
sqlite3 data/claw.db "select count(*) from projects;"
sqlite3 data/claw.db "select count(*) from pulse_discoveries;"
```

Create `docs/LAUNCH_METRICS_2026-06-19.md` with:

- git head and branch status
- canonical DB path and SHA-256
- methodology counts by lifecycle state
- project/discovery counts
- verified route/page counts for FastAPI and Next.js
- verification commands and results
- explicit note that `camcxBU64` was not used as the launch corpus

### 2. Upgrade Frontend Dependencies

In `forge-ui/`, resolve the npm audit findings without a major-version jump
unless unavoidable.

Minimum verification:

```bash
cd forge-ui
npm ci
npm audit --audit-level=moderate
npm run build
```

If `npm audit fix` or a targeted `next` upgrade changes lockfiles, keep the
change scoped to `forge-ui/package.json` and `forge-ui/package-lock.json`.

Do not commit `node_modules/`, `.next/`, or generated local build artifacts.

### 3. Refresh README

Rewrite the top of `README.md` so a new visitor understands the product in the
first screen:

1. CAM_CAM is a local repo-intelligence and coding-memory system.
2. Repo Rescue Desk is the current flagship proof.
3. CAM-PULSE is the method engine underneath: source-mined methods,
   provenance, verification, correction, and outcome-scored memory.
4. Use current launch metrics from `docs/LAUNCH_METRICS_2026-06-19.md`.
5. Give a short runnable quickstart before long architecture sections.

The README should keep real proof, but remove or reframe stale counts such as
older methodology totals, older test totals, and old page/route counts unless
they are clearly labeled as historical.

### 4. Soften Competitor Claims

Update competitor copy in `README.md`, `docs/cam_cam_showpiece.html`, and any
current launch page touched by this work.

Required positioning:

- Acknowledge that Copilot, Devin, Windsurf, Cursor-class tools, and Aider have
  memory, indexing, rules, or repo-map features.
- Do not claim "no one else has memory."
- Emphasize CAM_CAM's narrower defensible difference: source-mined reusable
  methods, local SQLite corpus, provenance, lifecycle/fitness tracking,
  verification evidence, method demotion, and repo-universe preflight.

Suggested claim:

> CAM_CAM is not trying to beat IDE assistants at autocomplete. It is for
> operators with many repos who need to map, mine, verify, and reuse engineering
> knowledge before an agent mutates code.

### 5. Polish Static Launch Pages

Make the launch surface coherent:

- Keep `docs/cam_cam_showpiece.html` as the primary static launch page unless a
  better existing page is selected.
- Ensure `index.html` and `docs/index.html` route intentionally to the selected
  primary page.
- Either redirect `docs/site/index.html` to the selected current page or label
  it as archived/background CAM-PULSE material.
- Add a concise "run it locally" band to the primary static page.
- Use current metrics only.
- Keep claims readable for a non-insider: problem first, proof second,
  commands third.

### 6. Update Forge UI README

Refresh `forge-ui/README.md` from live evidence:

- Current install/build commands.
- Current route/page count from `find forge-ui/src/app -name page.tsx`.
- Current backend route count from `src/claw/web/dashboard_server.py`.
- Note whether `npm audit` is clean after dependency work.

### 7. Make CAM_Codx Clean For A New User

Before final launch copy mentions CAM_Codx, verify that `deesatzed/CAM_Codx.git`
is understandable as a separate companion repo.

Run and record:

```bash
git -C /Volumes/WS4TB/WS4TBr/CAM_Codx/codex-cam-methodology remote -v
git -C /Volumes/WS4TB/WS4TBr/CAM_Codx/codex-cam-methodology status --short --branch
git -C /Volumes/WS4TB/WS4TBr/CAM_Codx/codex-cam-methodology log --oneline -5
git -C /Volumes/WS4TB/WS4TBr/CAM_Codx/codex-cam-methodology-impl remote -v
git -C /Volumes/WS4TB/WS4TBr/CAM_Codx/codex-cam-methodology-impl status --short --branch
git -C /Volumes/WS4TB/WS4TBr/CAM_Codx/codex-cam-methodology-impl log --oneline -5
```

Then perform a new-user audit:

- Identify which checkout is the public-facing `CAM_Codx` repo and which is an
  implementation branch/workspace.
- Ensure the first screen of the public README says what CAM_Codx does, how it
  relates to CAM_CAM, and what a new user should run first.
- Make the branch/status story explicit: branch name, remote branch, whether
  local work is ahead/dirty, and whether there are unresolved deletions.
- Remove or document confusing stale names such as old controller migrations,
  obsolete MCP tool names, or historical branches if they appear in active docs.
- Ensure any `GOAL.md` in CAM_Codx does not contradict the CAM_CAM launch goal.
- Add or update a small `docs/NEW_USER_AUDIT_2026-06-19.md` or
  `meta/HANDOFF_LATEST.md` in the correct CAM_Codx checkout if the current docs
  are not enough for a new user.
- Do not hide dirty-tree truth. If CAM_Codx is not clean enough to launch,
  document the exact blockers in the CAM_CAM launch-refresh report instead of
  presenting it as ready.

Minimum "makes sense to a new user" standard:

1. A visitor can tell CAM_Codx is separate from CAM_CAM.
2. A visitor can tell whether CAM_Codx is an MCP/methodology bridge, an
   implementation repo, or a historical scaffold.
3. The README explains the supported install/test/smoke path without requiring
   private local paths.
4. The README does not claim stale tool surfaces; the CAM-Codx MCP surface must
   match the current implementation or be labeled historical.
5. Git status and branch divergence are recorded honestly.

### 8. Verify

Run and record:

```bash
git status --short --branch
PYTHONPATH=src python -m claw.cli --help
PYTHONPATH=src python -m claw.cli dashboard --help
PYTHONPATH=src python -m pytest tests/test_dashboard_server.py tests/test_dashboard_playground.py tests/test_cli_ux.py tests/test_miner.py -q
PYTHONPATH=apps/repo_rescue_desk python -m repo_rescue_desk.cli --help
cd forge-ui && npm ci && npm audit --audit-level=moderate && npm run build
git diff --check
```

If practical, also run a browser smoke check for:

- `docs/cam_cam_showpiece.html`
- the FastAPI dashboard root
- `forge-ui` root and main navigation pages

## Acceptance Criteria

This launch refresh is complete only when all are true:

- `docs/LAUNCH_METRICS_2026-06-19.md` exists and uses only the canonical DB.
- README top section and metrics reflect the canonical launch metrics.
- Competitor comparisons no longer falsely imply that rivals lack memory.
- CAM_Codx has a recorded new-user audit and is either cleaned/documented as a
  separate companion repo or explicitly listed as a launch blocker.
- Frontend dependency audit is clean at `moderate` or higher, or any remaining
  advisory is documented with reason and mitigation.
- `npm run build` passes in `forge-ui`.
- Focused Python verification passes.
- Static launch pages point to one coherent current story.
- `docs/reports/CAM_CAM_LAUNCH_REFRESH_2026-06-19.md` records changed files,
  command outputs, remaining risks, and any intentionally deferred work.
- No backup DB data is copied into the canonical repo.

## Stop Conditions

Pause and report instead of continuing if:

- Fixing npm audit requires a major Next.js/React migration.
- The canonical DB cannot be read.
- Verification fails after three distinct repair attempts for the same failure.
- A browser smoke check exposes a major UI/runtime failure that requires product
  code changes outside the allowed paths.
- Updating claims requires a material product decision about branding,
  positioning, or launch audience.
- CAM_Codx has conflicting local checkouts or dirty state that cannot be safely
  explained without destructive cleanup.
- A production deploy, GitHub push, credential, account, or secret is required.

## Final Response Requirements

When this goal is executed, the final response must include:

- Whether the launch refresh is complete or blocked.
- The canonical DB count used.
- Files changed.
- Verification commands and results.
- Remaining launch risks.
- CAM_Codx new-user readiness verdict and the exact local checkout used.
- Explicit confirmation that `/Volumes/WS4TB/camcxBU64/CAM_CAM/data/claw.db`
  was not used as the launch corpus.
