# CAM_CAM Launch Metrics - 2026-06-19

This file is the canonical launch-metrics source for the 2026-06-19 launch refresh.

## Source Boundary

- Source repo: `/Volumes/WS4TB/WS4TBr/CAM_Codx/CAM_CAM`
- Branch: `main`
- Git head: `2fd5e8558e907c3aa1f00f67f5b9e1756519b96e`
- GitHub remote: `https://github.com/deesatzed/CAM_CAM.git`
- Canonical DB: `/Volumes/WS4TB/WS4TBr/CAM_Codx/CAM_CAM/data/claw.db`
- Canonical DB SHA-256: `c2b67ea97d6798199c5f31784fecdcac0a7a707c3fa21b24ad5f461b1a5765b0`
- Canonical DB size/date: `109M`, `Jun 18 07:27`

The backup DB at `/Volumes/WS4TB/camcxBU64/CAM_CAM/data/claw.db` was not used as the launch corpus. It was treated only as a read-only comparison candidate because it may have schema and method-shape drift.

## Corpus Counts

Commands:

```bash
sqlite3 data/claw.db "select count(*) from methodologies;"
sqlite3 data/claw.db "select lifecycle_state, count(*) from methodologies group by lifecycle_state order by 2 desc;"
sqlite3 data/claw.db "select count(*) from projects;"
sqlite3 data/claw.db "select count(*) from pulse_discoveries;"
```

Results:

| Metric | Count |
|---|---:|
| Methodologies | 2,304 |
| Projects | 110 |
| Pulse discoveries | 0 |

Lifecycle distribution:

| Lifecycle state | Count |
|---|---:|
| embryonic | 2,140 |
| viable | 144 |
| declining | 17 |
| thriving | 3 |

Top stored methodology languages:

| Language | Count |
|---|---:|
| python | 2,047 |
| blank / unset | 142 |
| yaml | 25 |
| markdown | 24 |
| typescript | 18 |
| rust | 15 |
| json | 10 |
| swift | 8 |
| bash | 4 |

## App Surface

FastAPI route count from `src/claw/web/dashboard_server.py`:

| Method | Count |
|---|---:|
| GET | 54 |
| POST | 35 |
| DELETE | 1 |
| PATCH | 1 |
| PUT | 0 |
| Total | 91 |

Next.js page files under `forge-ui/src/app`: `20`.

## Frontend Dependency Audit

`forge-ui` was updated from `next@16.2.2` to `next@16.2.9`, then `npm audit fix` was run without `--force`.

Resolved:

- Removed the prior high-severity advisory.
- Fixed transitive advisories for `@babel/core`, `brace-expansion`, `js-yaml`, and root `postcss`.

Remaining:

- `npm audit --audit-level=moderate` reports `2 moderate` advisories: `next` via Next's bundled `postcss`.
- npm's only automated fix is `npm audit fix --force`, which would install `next@9.3.3` and is a breaking downgrade from the current Next 16 app stack.

Mitigation:

- Keep `next@16.2.9`.
- Do not use untrusted CSS as a launch input path.
- Re-run `npm audit` after the next Next.js release that bundles `postcss>=8.5.10`.

## Verification Commands

These commands are required for the final launch-refresh report:

```bash
git status --short --branch
PYTHONPATH=src python -m claw.cli --help
PYTHONPATH=src python -m claw.cli dashboard --help
PYTHONPATH=src python -m pytest tests/test_dashboard_server.py tests/test_dashboard_playground.py tests/test_cli_ux.py tests/test_miner.py -q
PYTHONPATH=apps/repo_rescue_desk python -m repo_rescue_desk.cli --help
cd forge-ui && npm ci && npm audit --audit-level=moderate && npm run build
git diff --check
```

