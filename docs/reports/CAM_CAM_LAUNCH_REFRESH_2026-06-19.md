# CAM_CAM Launch Refresh Report - 2026-06-19

## Verdict

Complete with one documented frontend audit caveat.

CAM_CAM's public launch surface now points at one current story: Repo Rescue Desk as the flagship proof, CAM-PULSE as the local mined-method engine, and CAM_Codx as a separate companion repo.

## Canonical Metrics

- Canonical DB: `/Volumes/WS4TB/WS4TBr/CAM_Codx/CAM_CAM/data/claw.db`
- DB SHA-256: `c2b67ea97d6798199c5f31784fecdcac0a7a707c3fa21b24ad5f461b1a5765b0`
- Methodologies: `2,304`
- Lifecycle states: `2,140 embryonic`, `144 viable`, `17 declining`, `3 thriving`
- Projects: `110`
- Pulse discoveries: `0`
- FastAPI dashboard routes: `91`
- Next.js page files: `20`

The backup DB at `/Volumes/WS4TB/camcxBU64/CAM_CAM/data/claw.db` was not used as the launch corpus.

## Changed Files

CAM_CAM:

- `GOAL.md`
- `REPO_MAP.md`
- `RISK_NOTES.md`
- `README.md`
- `docs/LAUNCH_METRICS_2026-06-19.md`
- `docs/cam_cam_showpiece.html`
- `docs/site/index.html`
- `docs/reports/CAM_CAM_LAUNCH_AUDIT_2026-06-19.md`
- `docs/reports/CAM_CAM_LAUNCH_REFRESH_2026-06-19.md`
- `forge-ui/README.md`
- `forge-ui/package.json`
- `forge-ui/package-lock.json`

CAM_Codx companion repo:

- `/Volumes/WS4TB/WS4TBr/CAM_Codx/codex-cam-methodology/README.md`
- `/Volumes/WS4TB/WS4TBr/CAM_Codx/codex-cam-methodology/docs/NEW_USER_AUDIT_2026-06-19.md`

Pre-existing untracked file left untouched:

- `CAM_Codx_last5291pm.txt`

## Documentation Refresh

- Rewrote the top of `README.md` so a new user sees the product, flagship proof, current metrics, quickstart, and CAM_Codx boundary before older proof material.
- Added `docs/LAUNCH_METRICS_2026-06-19.md` as the canonical metrics source.
- Softened competitor claims in `README.md` and `docs/cam_cam_showpiece.html`.
- Verified current competitor positioning against official docs:
  - GitHub Copilot Memory: `https://docs.github.com/copilot/concepts/agents/copilot-memory`
  - Windsurf/Cascade memories: `https://docs.devin.ai/desktop/cascade/memories`
  - Devin DeepWiki: `https://docs.devin.ai/work-with-devin/deepwiki`
  - Aider repo map: `https://aider.chat/docs/repomap.html`
- Replaced old `docs/site/index.html` CAM-PULSE landing content with a compatibility redirect to `docs/cam_cam_showpiece.html`.
- Updated `forge-ui/README.md` with current page count, route count, install/build commands, Next version, and audit caveat.

## Frontend Dependency Work

- Updated `next` from `16.2.2` to `16.2.9`.
- Ran `npm audit fix` without `--force`.
- Resolved the prior high-severity advisory and transitive advisories for `@babel/core`, `brace-expansion`, `js-yaml`, and root `postcss`.
- Remaining audit result: `2 moderate` advisories for Next's bundled `postcss`.
- Reason not force-fixed: `npm audit fix --force` would install `next@9.3.3`, a breaking downgrade from the Next 16 / React 19 app stack.
- Mitigation: keep `next@16.2.9`, do not route untrusted CSS through the launch path, and rerun audit after a Next release bundles `postcss>=8.5.10`.

## CAM_Codx New-User Verdict

Public-facing checkout:

- Path: `/Volumes/WS4TB/WS4TBr/CAM_Codx/codex-cam-methodology`
- Remote: `https://github.com/deesatzed/CAM_Codx.git`
- Branch: `main`
- Status before edits: clean and aligned with `origin/main`
- Verdict: understandable as the separate CAM_Codx front door after README update and audit artifact.

Implementation workspace:

- Path: `/Volumes/WS4TB/WS4TBr/CAM_Codx/codex-cam-methodology-impl`
- Remote: `https://github.com/deesatzed/CAM_Codx.git`
- Branch: `feature/initial-impl`
- Status: ahead of remote by 1 commit and dirty with deleted files, modified README/code/tests, and untracked data/instance artifacts.
- Verdict: not launch-clean. It is documented as a separate implementation workspace, not folded into CAM_CAM.

## Verification Results

Passed:

```bash
git status --short --branch
PYTHONPATH=src python -m claw.cli --help
PYTHONPATH=src python -m claw.cli dashboard --help
PYTHONPATH=apps/repo_rescue_desk python -m repo_rescue_desk.cli --help
PYTHONPATH=src python -m pytest tests/test_dashboard_server.py tests/test_dashboard_playground.py tests/test_cli_ux.py tests/test_miner.py -q
npm ci
npm run build
git diff --check
```

Key outputs:

- CLI help: exit `0`
- Dashboard help: exit `0`
- Repo Rescue Desk help: exit `0`
- Focused Python tests: `257 passed in 1.27s`
- `npm ci`: exit `0`, reproduced the documented `2 moderate` advisories
- `npm run build`: exit `0`, Next.js `16.2.9`, production build completed
- `git diff --check`: exit `0`

Expected nonzero:

```bash
npm audit --audit-level=moderate
```

Result: exit `1`, `2 moderate` advisories for Next's bundled `postcss`; npm's only automated fix is the breaking `next@9.3.3` downgrade.

HTTP smoke checks:

- Static showpiece: `http://127.0.0.1:8765/cam_cam_showpiece.html` returned `200 text/html`
- FastAPI dashboard root: `http://127.0.0.1:8421/` returned `200 text/html; charset=utf-8`
- Forge UI root: `http://127.0.0.1:3300/` returned `200 text/html; charset=utf-8`

All local smoke servers were stopped after the checks.

## Remaining Launch Risks

- The README still preserves long historical proof sections. The top section now clearly marks current metrics, but a later full README simplification would improve scanability.
- `forge-ui` depends on a current Next line affected by npm's PostCSS advisory until upstream releases a safe nonbreaking fix.
- CAM_Codx implementation branch is not launch-clean; it needs a separate reconciliation goal before being marketed as an implementation release.
- `CAM_Codx_last5291pm.txt` remains untracked in CAM_CAM and was intentionally left untouched.

