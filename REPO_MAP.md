# REPO_MAP.md

## Project Type

Python CLI, FastAPI dashboard backend, Next.js browser UI, static launch pages, and local SQLite knowledge/corpus store.

## Tech Stack

- Python 3.12 package: `claw`
- CLI: Typer/Rich
- Backend: FastAPI in `src/claw/web/dashboard_server.py`
- Frontend: Next.js 16, React 19, TypeScript, Tailwind, D3, Recharts in `forge-ui/`
- Data: SQLite `data/claw.db`, plus sqlite-vec/FTS tables
- Docs/site: Markdown docs and static HTML under `docs/`, root `index.html`, and `cam_cam_showpiece.html`

## Package Manager

| Area | Manager |
|---|---|
| Python | `pip install -e ".[dev]"` from `pyproject.toml` |
| Frontend | `npm ci` from `forge-ui/package-lock.json` |

## Commands

| Purpose | Command | Verified |
|---|---|---|
| CLI smoke | `PYTHONPATH=src python -m claw.cli --help` | yes |
| Dashboard help | `PYTHONPATH=src python -m claw.cli dashboard --help` | yes |
| Focused backend/CLI tests | `PYTHONPATH=src python -m pytest tests/test_dashboard_server.py tests/test_dashboard_playground.py tests/test_cli_ux.py tests/test_miner.py -q` | yes, 257 passed |
| Frontend install/build | `cd forge-ui && npm ci && npm run build` | yes, build passed |
| Frontend audit | `cd forge-ui && npm audit --audit-level=low --json` | yes, 5 vulnerabilities |
| Repo Rescue Desk CLI smoke | `PYTHONPATH=apps/repo_rescue_desk python -m repo_rescue_desk.cli --help` | yes |

## Entry Points

- `cam` script: `claw.cli:app_main`
- Main CLI package: `src/claw/cli/__init__.py`
- CLI implementation: `src/claw/cli/_monolith.py`
- Dashboard backend: `src/claw/web/dashboard_server.py`
- MCP server: `src/claw/mcp_server.py`
- Next.js UI: `forge-ui/src/app/`
- Repo Rescue Desk: `apps/repo_rescue_desk/repo_rescue_desk/cli.py`
- Static public entry: `index.html` redirects to `docs/cam_cam_showpiece.html`

## Major Folders

| Path | Purpose |
|---|---|
| `src/claw/` | Core CAM runtime, mining, memory, agents, dashboard, CLI, MCP, evolution |
| `tests/` | Python regression suite |
| `docs/` | Product docs, proof notes, launch pages, showpieces, plans |
| `docs/site/` | Older CAM-PULSE static landing page |
| `forge-ui/` | Next.js dashboard/Forge UI |
| `apps/repo_rescue_desk/` | Current flagship local repo-universe triage app |
| `apps/assimilation_repo_upgrade_advisor/` | Standalone advisory app |
| `apps/embedding_forge/` | Embedding Forge experiments/showpiece |
| `apps/medcss_modernizer_showpiece/` | Standalone modernization showpiece |
| `data/` | Local SQLite DB and generated knowledge/cache artifacts |
| `batch_run/results/` | Batch-build proof artifacts |

## Existing Patterns To Preserve

- Evidence-first docs with reproducible commands and proof artifacts.
- Local-first defaults where possible, with OpenRouter/API paths documented explicitly.
- No source mutation in Repo Rescue Desk first pass.
- Knowledge items are structured methodologies with lifecycle/fitness state rather than raw chat notes.
- Static launch pages are directly hostable without adding a frontend build requirement.

## Tests and Verification

- Focused test run passed: `257 passed in 2.19s`.
- Frontend production build passed after installing locked dependencies.
- `npm audit` reports 5 vulnerabilities: 1 low, 3 moderate, 1 high; Next.js can be upgraded within semver to `16.2.9`.
- Current local DB count: 2,304 methodologies in `/Volumes/WS4TB/WS4TBr/CAM_Codx/CAM_CAM/data/claw.db`.
- Backup DB count: 2,427 methodologies in `/Volumes/WS4TB/camcxBU64/CAM_CAM/data/claw.db`.

## Likely Files For Current Task

- `README.md`
- `docs/cam_cam_showpiece.html`
- `cam_cam_showpiece.html`
- `docs/site/index.html`
- `forge-ui/README.md`
- `docs/PROOF_POINT_INDEX.md`
- `docs/CAM_PROVEN_CAPABILITIES.md`
- `docs/GETTING_STARTED.md`
- `docs/reports/CAM_CAM_LAUNCH_AUDIT_2026-06-19.md`

## Unknowns

- Full `pytest tests/ -q` was not run in this audit.
- The backup DB has 123 more methodology rows; it has not been reconciled into the canonical checkout.
- Public GitHub Pages target should be confirmed before final launch copy is updated.
- External competitor claims should stay conservative because Copilot, Devin, Windsurf, and Aider continue to change quickly.
