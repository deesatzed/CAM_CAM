# CAM_CAM Top-Six Feature Enhancement Report - 2026-06-19

## Verdict

Implemented the top-six user-need enhancements inside the existing Repo Rescue Desk surface. The implementation is deterministic, local-first, and does not require LLM/API keys.

## Features Completed

1. **One-command workspace audit dashboard**
   - Existing scan command now emits additional product artifacts alongside the dashboard.
   - Dashboard now includes "What to do next", "Safe to edit", and "Reusable code and patterns" sections.

2. **Actionable next-step recommendations**
   - Added ranked `next_actions` with category, repos, why now, effort, risk, payoff, evidence, and verification command.
   - Outputs: `next_actions.json`, `next_actions.md`, dashboard section, executive report section.

3. **Git-safe agent preflight gate**
   - Added read-only `preflight_repo()` and CLI subcommand:
     `python -m repo_rescue_desk.cli preflight --repo <repo> --json-out <path>`.
   - Decisions are `allow`, `warn`, or `block`.
   - Checks include git cleanliness, branch, remote, tests, README, secret/API-key language, medical/PII language, security language, and Node dependency risk.

4. **Repo-to-repo reuse finder**
   - Added deterministic local reuse matching for auth, retry, and API/FastAPI signals.
   - Outputs include repo/path provenance, signals, confidence, and reason.
   - Outputs: `reuse_matches.json`, `reuse_matches.md`, dashboard section, executive report section.

5. **Plain-English executive/project report export**
   - Added `executive_report.md` with overview, next steps, risks, reuse candidates, repo inventory, and reproduction commands.

6. **Interactive "ask my repo universe" chat**
   - Added deterministic `answer_repo_question()` and CLI subcommand:
     `python -m repo_rescue_desk.cli ask --report <repo_inventory.json> --question "<question>"`.
   - Supported intents: dirty repos, no-test repos, FastAPI-looking repos, next actions, and reusable auth/retry/API patterns.
   - Output includes citations to the scan artifact family.

## New User Commands

Run a workspace scan:

```bash
PYTHONPATH=apps/repo_rescue_desk python -m repo_rescue_desk.cli \
  --root /path/to/folder/containing/git/repos \
  --out-dir tmp/repo_rescue_desk/latest
```

Open or read the main outputs:

```bash
open tmp/repo_rescue_desk/latest/repo_rescue_dashboard.html
cat tmp/repo_rescue_desk/latest/executive_report.md
cat tmp/repo_rescue_desk/latest/next_actions.md
cat tmp/repo_rescue_desk/latest/reuse_matches.md
```

Ask the saved scan:

```bash
PYTHONPATH=apps/repo_rescue_desk python -m repo_rescue_desk.cli ask \
  --report tmp/repo_rescue_desk/latest/repo_inventory.json \
  --question "What should I do next?"
```

Preflight one repo:

```bash
PYTHONPATH=apps/repo_rescue_desk python -m repo_rescue_desk.cli preflight \
  --repo /path/to/repo \
  --json-out tmp/repo_rescue_desk/preflight.json
```

## Changed Files

- `GOAL.md`
- `README.md`
- `apps/repo_rescue_desk/README.md`
- `apps/repo_rescue_desk/repo_rescue_desk/cli.py`
- `apps/repo_rescue_desk/repo_rescue_desk/rescue.py`
- `apps/repo_rescue_desk/tests/test_rescue.py`
- `docs/cam_cam_showpiece.html`
- `docs/reports/CAM_CAM_TOP6_FEATURES_2026-06-19.md`

## Smoke Evidence

Temporary smoke root:

- `/tmp/cam-top6-smoke.b25qJM`

Scan command generated:

- `repo_inventory.json`
- `repo_rescue_dashboard.html`
- `next_actions.json`
- `next_actions.md`
- `reuse_matches.json`
- `reuse_matches.md`
- `preflight_results.json`
- `executive_report.md`
- `ask_index.json`
- existing GraphRAG, Logseq, Markmap, Freeplane, risk, and opportunity artifacts

`ask` smoke:

```text
What to do next:
1. Add smoke tests before agent edits (add-tests): Repos without tests are the highest-friction place to let an agent mutate code.
2. Mine reusable auth/retry/API patterns (mine-reuse): The scan found reusable implementation signals that can seed CAM methods or guide refactors.
3. Preflight risky repos before mutation (isolate-risky): These repos need branch, test, privacy, secret, or dirty-tree remediation before agent edits.
4. Prototype: Local Knowledge Appliance (candidate-app): The highest-scoring opportunity is supported by the current repo universe.
Citations: next_actions
```

`preflight` smoke returned `clinical-agent: block` and wrote JSON containing the `git-clean` block plus remediation.

## Verification Results

Passed:

```bash
PYTHONPATH=apps/repo_rescue_desk python -m repo_rescue_desk.cli --help
PYTHONPATH=src python -m claw.cli --help
PYTHONPATH=src python -m claw.cli dashboard --help
python -m pytest apps/repo_rescue_desk/tests -q
PYTHONPATH=src python -m pytest tests/test_dashboard_server.py tests/test_dashboard_playground.py tests/test_cli_ux.py tests/test_miner.py -q
cd forge-ui && npm ci && npm run build
```

Observed results:

- Repo Rescue Desk tests: `11 passed in 2.39s`
- Focused Python suite: `257 passed in 1.45s`
- Frontend build: Next.js `16.2.9`, production build completed

Known inherited caveat:

- `npm ci` still reports `2 moderate` audit advisories for Next's bundled PostCSS. This was accepted and documented in `docs/reports/CAM_CAM_LAUNCH_REFRESH_2026-06-19.md` because npm's force fix would downgrade to `next@9.3.3`.

## Remaining Gaps

- The new "ask" mode is deterministic and local. LLM-backed natural-language Q&A is intentionally not added until it can cite scan artifacts and degrade safely without keys.
- Forge UI does not yet expose a native React page for the top-six outputs. The static dashboard and Markdown/JSON artifacts are the supported first implementation.
- Reuse detection is conservative string/signal matching over source and README text. Semantic matching against CAM methodologies can be a later enhancement.
- The scan still assumes a workspace whose direct children are git repositories.
