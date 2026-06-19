# CAM_CAM Launch Audit - 2026-06-19

## Executive Verdict

CAM_CAM is real and launchable as a technical proof, but the public story needs a truth refresh before promotion. The strongest current product is Repo Rescue Desk plus the CAM-PULSE knowledge engine behind it: a local-first system that scans a repo universe, mines reusable source-derived methods, retrieves them with provenance, applies them in builds, verifies outcomes, and adjusts method fitness over time.

The launch risk is not lack of substance. The risk is drift: the README, static landing pages, corpus counts, UI page counts, and competitor claims do not all reflect the live tree on 2026-06-19.

## Current Source Of Truth

| Surface | Finding |
|---|---|
| Canonical source checkout | `/Volumes/WS4TB/WS4TBr/CAM_Codx/CAM_CAM` |
| GitHub remote | `https://github.com/deesatzed/CAM_CAM.git` |
| GitHub `main` head | `2fd5e8558e907c3aa1f00f67f5b9e1756519b96e` |
| Current checkout state | `main...origin/main`, only untracked `CAM_Codx_last5291pm.txt` |
| Backup checkout | `/Volumes/WS4TB/camcxBU64/CAM_CAM` |
| Backup code state | Behind by one commit, but `claw.toml` and `src/claw/miner.py` match current `origin/main` as local edits |
| Backup corpus state | `data/claw.db` differs and is larger than canonical DB |

## Folder Structure Assessment

`/Volumes/WS4TB/WS4TBr/CAM_Codx` is a workspace container, not one product repo. Important children:

| Path | Role |
|---|---|
| `CAM_CAM/` | Canonical CAM_CAM product repo: CLI, engine, docs, static pages, dashboard, showpiece apps |
| `codex-cam-methodology-impl/` | Companion CAM_Codx MCP/methodology implementation repo; currently dirty and ahead of its remote branch |
| `codex-cam-methodology/` | Older/planning source for CAM_Codx methodology work |
| `showpiece-clones/` | External proof/demo repos and experiments |

Inside `CAM_CAM/`, the product splits into:

- `src/claw/`: main Python runtime.
- `forge-ui/`: Next.js dashboard/Forge UI.
- `apps/repo_rescue_desk/`: current flagship triage app.
- `docs/`, `cam_cam_showpiece.html`, `index.html`: public docs and static launch surfaces.
- `data/claw.db`: local knowledge/corpus DB.

## Current vs Backup

The backup path does not contain newer source code than GitHub. After `git fetch origin main`, `/Volumes/WS4TB/camcxBU64/CAM_CAM` is one commit behind but its two modified files are byte-identical to the current canonical checkout:

- `claw.toml`
- `src/claw/miner.py`

The backup path does contain a newer/larger corpus:

| DB | Size | Methodologies | Embryonic | Viable | Declining | Thriving |
|---|---:|---:|---:|---:|---:|---:|
| Canonical `CAM_CAM/data/claw.db` | 109 MB | 2,304 | 2,140 | 144 | 17 | 3 |
| Backup `camcxBU64/CAM_CAM/data/claw.db` | 114 MB | 2,427 | 2,263 | 144 | 17 | 3 |

Implication: GitHub/current source lives in the canonical checkout. The only more-current thing in `camcxBU64` is likely corpus data, not code.

## Verification Performed

| Check | Result |
|---|---|
| `git ls-remote origin refs/heads/main` | GitHub `main` is `2fd5e855...` |
| Focused Python tests | `257 passed in 2.19s` |
| CLI help | Passed |
| Dashboard help | Passed |
| Repo Rescue Desk help | Passed |
| Frontend build before install | Failed: `next: command not found` |
| `npm ci && npm run build` | Passed |
| `npm audit --audit-level=low --json` | 5 vulnerabilities: 1 low, 3 moderate, 1 high |

## Product/UX Review

### What CAM_CAM Can Do

- Mine local/source repositories into structured methodologies.
- Store methods in SQLite with lifecycle, novelty, potential, retrieval, and fitness metadata.
- Search/use prior methods through CLI, dashboard, and MCP surfaces.
- Execute create/enhance workflows with verification and correction loops.
- Run a FastAPI dashboard with 91 detected routes.
- Run a Next.js UI with 20 page components and a successful production build.
- Run Repo Rescue Desk as a deterministic, read-only repo-universe scanner with graph/mindmap/GraphRAG outputs.
- Maintain showpiece apps and proof docs for batch builds, A/B knowledge experiments, local-first workflows, and repo triage.

### UX Strengths

- CLI is broad and discoverable through Typer help.
- Repo Rescue Desk has a clear first-use story: point it at a folder of repos, get inventory, risks, clusters, opportunities, and agent-readable artifacts.
- Static showpiece pages are visually strong and immediately explain "before agents touch code, inspect the fleet."
- Next.js dashboard has substantial route coverage: dashboard, knowledge explorer, gaps, mining, costs, evolution, federation, Forge, playground, failure knowledge.

### UX Weaknesses

- The launch surface is split between CAM-PULSE general positioning and CAM_CAM Repo Rescue Desk positioning.
- README is too long and mixes beginner pitch, research proof, command manual, competitor comparison, architecture, and historical claims.
- First-time user path still feels heavy: Python install, optional API keys, database initialization, dashboard backend, frontend install, and local corpus ambiguity.
- Browser UI needs route-level screenshots and a real "what happens when I click this" launch walkthrough.
- The strongest "why someone cares" is Repo Rescue Desk, but the README quickly dives into old metrics and CAM-PULSE internals.

## Competitor Positioning

Competitors have caught up on memory language. Current official docs show:

- GitHub Copilot Memory stores repository facts and user preferences, and validates repository facts against citations before use.
- Windsurf Cascade can automatically store workspace memories and retrieve them when relevant.
- Devin DeepWiki auto-indexes repos into architecture docs/summaries, and Devin Knowledge stores instructions/tips across sessions.
- Aider has strong local git editing, repository maps, scripting, and broad model support.

CAM_CAM should not claim "others have no memory." The more defensible claim is:

CAM_CAM is for developers and teams with many repos, repeated agent failures, or domain-specific local code archives who want a source-mined, provenance-linked, locally inspectable method corpus that improves through verified build outcomes rather than chat/session memory alone.

Best-fit users:

- Solo builders with many unfinished/prototype repos.
- AI engineering teams building internal agents and needing reusable method memory.
- Research/prototype teams comparing models, methods, and build outcomes.
- Local-first/privacy-sensitive developers who want repo intelligence before cloud/agent mutation.
- Teams with repo sprawl that need preflight triage before deciding what to mine, modernize, archive, or launch.

Less-fit users:

- Someone who only wants inline autocomplete.
- A beginner who wants one-click cloud hosting.
- A team needing polished SaaS onboarding today.
- A user who does not want to manage local Python/Node dependencies.

## README, Docs, Landing Assessment

### Accurate/Strong

- Repo Rescue Desk showpiece is a strong launch hook.
- The CLI command surface is real and tested enough for a technical launch.
- The core "structured method memory with provenance/outcomes" is differentiated.
- Static launch pages are more compelling than a generic README-only launch.

### Stale Or Risky

- README headline says 2,274 methodologies; live canonical DB has 2,304 and backup DB has 2,427.
- Docs and announcements contain older counts including 1,877, 2,624 tests, 2,895, 2,994, 3,044, and 3,734.
- `forge-ui/README.md` says 15 interactive pages and 40+ endpoints; live count is 20 page components and 91 detected backend routes.
- Competitor table says some rivals lack memory/knowledge features; current official docs contradict that framing.
- `docs/site/index.html` is an older CAM-PULSE launch page, while root/docs redirects now point at Repo Rescue Desk.

## Recommended Launch Rewrite

Lead with this:

> CAM_CAM is a local repo-intelligence and coding-memory system. Before an AI agent edits anything, it can map your repo universe, find reusable engineering patterns, preserve provenance, and turn verified build outcomes into a memory that improves future work.

Primary public proof:

- Repo Rescue Desk: 238 repos scanned, 8 clusters, 249 nodes, 244 edges, 6 opportunities, 0 mutations.

Secondary proof:

- CAM-PULSE method engine: 2,304 canonical local methodologies today, lifecycle/fitness tracking, correction loop, dashboard/backend/UI.

Avoid:

- "No other tool has memory."
- "Everything is accessible through the browser" unless a browser smoke test is recorded.
- Any count not regenerated from the current DB/test run.

## Launch Blockers Before Public Attention Push

1. Reconcile or select the canonical `claw.db`.
2. Refresh README and static pages from one metrics table.
3. Update competitor comparison to acknowledge current memory systems.
4. Upgrade `next` to a non-vulnerable fixed version and rerun build/audit.
5. Run a browser smoke test across `docs/cam_cam_showpiece.html`, backend `/`, and `forge-ui`.

## Suggested Next Step

Perform a launch-doc refresh without changing product behavior:

- `README.md`: shorter, Repo Rescue Desk first, proof table second, quickstart third.
- `docs/cam_cam_showpiece.html`: keep as primary launch page, add one "How to run it in 2 minutes" band.
- `docs/site/index.html`: either redirect to current showpiece or label it as archived CAM-PULSE background.
- `forge-ui/README.md`: update routes/endpoints/build/audit facts.
- Add a single `docs/LAUNCH_METRICS_2026-06-19.md` generated from current commands.
