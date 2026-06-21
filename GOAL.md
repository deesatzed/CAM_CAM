# GOAL.md

This file records the 2026-06-19 CAM_CAM product enhancement run. That run is
historical context for the current public repo; the active final public cleanup
contract lives in `/Volumes/WS4TB/repo622sn/CAM_Codx/GOAL.md`.

## Outcome

Build and document the six highest-probability user-needed features for
CAM_CAM's likely audience: operators with many repos who need evidence,
triage, reuse, and safe next actions before letting AI agents modify code.

The six target enhancements are:

1. One-command workspace audit dashboard.
2. Actionable next-step recommendations.
3. Git-safe agent preflight gate.
4. Repo-to-repo reuse finder.
5. Plain-English executive/project report export.
6. Interactive "ask my repo universe" chat.

The goal is not to add another generic coding assistant. The goal is to make
CAM_CAM immediately useful to a new user who points it at a messy repo folder
and asks: "What do I have, what is risky, what can I reuse, and what should I
do next?"

## Product Thesis

Likely users include:

- Solo developers with years of abandoned or half-finished repos.
- Engineering leads inheriting a folder or org full of unknown projects.
- AI tooling builders preparing safe agentic workflows.
- Consultants who need a client-readable repo portfolio report.
- Research engineers who want mined methods and provenance before code changes.

Their most urgent need is not autocomplete. It is a trustworthy local map of a
repo universe, with risks and opportunities ranked before mutation.

## Source Boundary

Canonical repo and corpus:

- Source repo: `/Volumes/WS4TB/WS4TBr/CAM_Codx/CAM_CAM`
- Canonical DB: `/Volumes/WS4TB/WS4TBr/CAM_Codx/CAM_CAM/data/claw.db`
- GitHub remote: `https://github.com/deesatzed/CAM_CAM.git`

Do not copy, merge, or substitute data from
`/Volumes/WS4TB/camcxBU64/CAM_CAM/data/claw.db`.

CAM_Codx is a separate companion repo at
`https://github.com/deesatzed/CAM_Codx.git`. Do not modify CAM_Codx for this
goal unless a specific integration doc needs a link update and the change is
explicitly recorded.

## Current Baseline

Use these existing artifacts as baseline context:

- `README.md`
- `REPO_MAP.md`
- `RISK_NOTES.md`
- current runtime docs and showpieces under `docs/`
- `docs/cam_cam_showpiece.html`
- `apps/repo_rescue_desk/`
- `src/claw/web/dashboard_server.py`
- `forge-ui/`

Before implementation, inspect the current CLI, FastAPI, and Forge UI routes to
reuse existing patterns instead of inventing parallel systems.

## Scope

Allowed modification paths:

- `GOAL.md`
- `README.md`
- `docs/`
- `apps/repo_rescue_desk/`
- `src/claw/web/`
- `src/claw/cli.py`
- `src/claw/`
- `tests/`
- `forge-ui/src/`
- `forge-ui/README.md`
- `forge-ui/package.json`
- `forge-ui/package-lock.json`

Historical artifacts from the original enhancement run:

- `docs/reports/top6-smoke/` if screenshots or smoke outputs are generated
- focused test fixtures under `tests/fixtures/` or `apps/repo_rescue_desk/tests/fixtures/`

Out of scope:

- DB migrations unless absolutely required and covered by tests.
- Copying backup DB rows into the canonical DB.
- Rebranding CAM_CAM away from CAM_CAM/CAM-PULSE/Repo Rescue Desk.
- Production deployment.
- GitHub push unless explicitly requested after the work is verified.
- Broad rewrites of unrelated CAM-PULSE mining, model routing, or bandit code.

## Required Feature Work

### 1. One-Command Workspace Audit Dashboard

Probability wanted: `0.90`.

User need: "I pointed this at a folder. Show me what I have without making me
read raw JSON."

Build or enhance:

- A single CLI command that scans a workspace and produces a dashboard-ready
  artifact set.
- A browser-visible dashboard route or static HTML artifact that summarizes:
  repo count, dirty repos, no-test repos, no-README repos, risky language,
  duplicate repo families, capability clusters, and generated artifacts.
- A first-run path that works on a small fixture repo universe without API keys.

Acceptance:

- A new user can run one documented command against a folder of repos.
- Output path is printed clearly.
- The dashboard can be opened locally and does not require private local paths.
- Tests cover the command on a fixture repo universe.

### 2. Actionable Next-Step Recommendations

Probability wanted: `0.86`.

User need: "Do not just describe my repos. Tell me what to do next and why."

Build or enhance:

- A ranked recommendation engine that produces next actions with:
  title, repo(s), why now, estimated effort, risk, expected payoff, evidence,
  and a suggested verification command.
- Recommendation categories should include at least:
  add tests, mine for reusable methods, consolidate duplicates, isolate risky
  repos, generate docs, and candidate app/build opportunities.
- The dashboard should surface the top recommendations clearly.

Acceptance:

- Recommendations are deterministic for fixture inputs.
- Each recommendation includes evidence links or source repo names.
- Ranking is explained in plain language.
- Tests cover at least three recommendation categories.

### 3. Git-Safe Agent Preflight Gate

Probability wanted: `0.84`.

User need: "Before an AI edits code, tell me if this repo is safe to touch."

Build or enhance:

- A preflight gate for a target repo that checks:
  git cleanliness, branch name, remote status if cheap, tests present, README
  present, likely secret/API-key terms, medical/PII language, package-lock or
  large dependency risk, and rollback hints.
- Output should be a clear decision:
  `allow`, `warn`, or `block`.
- The gate should return machine-readable JSON and human-readable summary text.

Acceptance:

- Dirty worktree and missing tests are detected in tests.
- Blocking vs warning behavior is covered by tests.
- The gate never mutates the target repo.
- The user sees exact remediation steps.

### 4. Repo-To-Repo Reuse Finder

Probability wanted: `0.82`.

User need: "I probably already solved this in another repo. Find it."

Build or enhance:

- A local reuse finder that identifies reusable patterns across scanned repos:
  shared file names, common functions/classes, framework-specific modules,
  README-described capabilities, and mined CAM methodologies when available.
- It should answer questions like:
  "Where do I already have retry logic?"
  "Which repos contain FastAPI auth?"
  "What can this repo borrow from nearby repos?"
- Output should include provenance: repo, path, signal, and confidence.

Acceptance:

- Fixture repos demonstrate at least two reuse matches.
- Results include repo/path provenance.
- False confidence is avoided; weak matches are labeled weak.
- No LLM/API key is required for the baseline reuse scan.

### 5. Plain-English Executive/Project Report Export

Probability wanted: `0.78`.

User need: "Give me something I can send to a client, manager, or future me."

Build or enhance:

- Export a polished Markdown report from a workspace scan.
- Include:
  overview, repo inventory, top risks, top opportunities, reuse candidates,
  recommended next steps, preflight warnings, and commands to reproduce.
- Keep it understandable to non-insiders while preserving evidence.

Acceptance:

- Report generation is covered by tests.
- Report has no machine-specific absolute paths unless explicitly in a
  reproducibility appendix.
- Report links or references generated JSON/artifacts.
- README documents how to generate it.

### 6. Interactive "Ask My Repo Universe" Chat

Probability wanted: `0.76`.

User need: "After the scan, let me ask follow-up questions."

Build or enhance:

- A local question-answering surface over the scan artifacts.
- Must work in a baseline deterministic mode without LLM keys for common
  questions:
  - "Which repos are dirty?"
  - "Which repos have no tests?"
  - "Which repos look like FastAPI apps?"
  - "What should I do next?"
  - "Where are reusable auth/retry/API patterns?"
- If an LLM-backed mode exists or is added, it must cite scan artifacts and
  degrade gracefully when keys are missing.

Acceptance:

- CLI or UI chat entrypoint is documented.
- At least five deterministic query intents are tested.
- Answers cite repo names and source artifacts.
- Missing/unknown answers are honest instead of fabricated.

## UX Requirements

- The first successful run should feel like a useful product, not a library
  demo.
- Commands must print the next thing to open or run.
- Dashboard and reports must lead with problems and decisions, not internal
  CAM terminology.
- Feature labels should use plain language:
  "Risk", "What to do next", "Reusable code", "Safe to edit", "Report".
- Avoid marketing-only pages. Build usable surfaces first.

## Documentation Requirements

Update:

- `README.md` with the new top-six workflow.
- `docs/cam_cam_showpiece.html` only if the new features are demonstrably
  runnable and should be reflected in the public launch page.
- `forge-ui/README.md` if Forge UI routes or setup change.
- Historical top-six verification was recorded during the enhancement run. The
  final public cleanup pass no longer keeps the stale dated report in CAM_CAM.

## Verification

Minimum commands:

```bash
git status --short --branch
PYTHONPATH=apps/repo_rescue_desk python -m repo_rescue_desk.cli --help
PYTHONPATH=src python -m claw.cli --help
PYTHONPATH=src python -m claw.cli dashboard --help
PYTHONPATH=src python -m pytest tests/test_dashboard_server.py tests/test_dashboard_playground.py tests/test_cli_ux.py tests/test_miner.py -q
python -m pytest apps/repo_rescue_desk/tests -q
cd forge-ui && npm ci && npm run build
git diff --check
```

Add focused tests for each feature touched. If a feature is intentionally
implemented as CLI-only or static-report-only in this pass, document that in
the final report instead of implying UI parity.

## Acceptance Criteria

This goal is complete only when all are true:

- The one-command workspace audit path runs on a fixture repo universe.
- The dashboard or generated HTML exposes the audit summary clearly.
- Ranked next-step recommendations exist and are tested.
- Git-safe preflight returns `allow`, `warn`, or `block` with evidence.
- Repo-to-repo reuse finder returns provenance-backed matches.
- Plain-English report export exists and is documented.
- Ask-my-repo deterministic queries answer at least five common intents.
- README documents the top-six workflow.
- Final report existed during the enhancement run; the final public cleanup pass
  now records cleanup provenance in CAM_Codx manifests instead of keeping stale
  launch snapshots in CAM_CAM.
- Required verification passes, except any documented npm audit advisory already
  accepted in the launch-refresh report.

## Stop Conditions

Pause and report instead of continuing if:

- Implementing one of the top-six features requires a schema migration that
  cannot be covered safely in this goal.
- A required UI path needs a frontend dependency major upgrade.
- Verification fails after three distinct mitigation attempts for the same root
  cause.
- The implementation would require copying backup DB data.
- A product decision is needed that materially changes CAM_CAM positioning.
- Credentials, API keys, production deploy, or GitHub account actions are
  required.

## Final Response Requirements

When this goal is executed, the final response must include:

- Which of the six features were completed.
- Exact commands a new user should run.
- Verification command results.
- Files changed.
- Remaining gaps and deferred work.
- Whether changes were committed or pushed.
