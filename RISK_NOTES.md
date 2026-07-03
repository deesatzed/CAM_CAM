# RISK_NOTES.md

## Risks

| Risk | Severity | Why It Matters | Mitigation |
|---|---|---|---|
| Backup corpus is ahead of canonical corpus | High | `/Volumes/WS4TB/camcxBU64/CAM_CAM/data/claw.db` has 2,427 methodologies, while canonical `CAM_CAM/data/claw.db` has 2,304. Launch metrics will be wrong unless one corpus is chosen. | Reconcile/export the 123-row delta or explicitly state which DB backs public claims. |
| README and landing metrics are stale/inconsistent | High | README says 2,274 methodologies and docs mention 2,624/3,734 tests in different places; live DB says 2,304 in canonical and 2,427 in backup. | Refresh README/site from a generated metrics block before launch. |
| Competitor comparison overclaims | High | GitHub Copilot Memory, Devin Knowledge/DeepWiki, and Windsurf Cascade Memories all now provide memory/knowledge features. | Reframe as CAM's source-mined, provenance-linked, outcome-scored local method corpus, not simply "others have no memory." |
| Frontend dependency audit is not clean | Medium | `npm audit` reports 5 vulnerabilities, including high-severity Next.js advisories. | Upgrade `next` to at least the audited fixed semver target and rerun `npm ci && npm run build && npm audit`. |
| Browser UX proof is build-level only in this audit | Medium | Next.js builds, but no Playwright/manual browser walk was performed for key workflows. | Run local backend/frontend and smoke the routes before launch screenshots. |
| Current launch surface is split | Medium | Root `index.html` and `docs/index.html` redirect to Repo Rescue Desk, while `docs/site/index.html` is older CAM-PULSE positioning. | Pick one canonical public launch route and make other pages clearly secondary. |
| Repo contains local generated/untracked artifacts | Low | Canonical checkout has untracked `CAM_Codx_last5291pm.txt`; backup checkout has the same plus local source edits matching current `origin/main`. | Do not commit stray local artifacts; fast-forward backup checkout after deciding whether to preserve its DB. |
| Root-only reconcile gives false "missing findings" signal | Medium | A reconcile of `mining_registry.json` IDs against root `claw.db` alone showed 38/99 missing for the 2026-06-28 mine. Investigation found the polyglot brain routes findings to per-language ganglion DBs (`instances/typescript/claw.db`, `instances/rust/claw.db`); recovery mine reconciled 62/62 across all DBs. No data was lost. See Error Log E-001. | Any registry-vs-DB reconcile must union root + all `instances/*/claw.db`. Use `cam enrich --include-ganglia`. |
| Active config db_path diverged from real corpus | High | `claw.toml` had `db_path = "data/claw.db"`, but the live 2,449-methodology corpus is at repo-root `claw.db`. An empty 0-byte `data/claw.db` was auto-created, so mining would have written to the wrong/empty DB and split the corpus. | Fixed: `db_path` set to `claw.db` and empty `data/claw.db` removed. Keep config db_path and corpus path in sync; consider absolute db_path. |

## Error Log

### E-001 — Silent mining persistence loss (registry over-reports vs DB)

- **Date observed:** 2026-06-28 mine (07:37–07:52 local); diagnosed 2026-06-29.
- **Signature:** `mining_outcomes.success=1` and `mining_registry.json` records N methodology IDs, but only M (< N) rows exist in `methodologies`; no `error_type`/`error_detail` recorded.
- **Evidence:** 99 findings returned by LLM (sum of `mining_outcomes.findings_count`), 99 IDs in registry, 61 rows in `claw.db`. Methodologies and their `action_templates` are lost together in identical per-repo counts. Loss is clustered on the repos mined later in the run (careframe, finESS, fractal, mydisasters); the run spanned ~15 min against the default `--max-minutes 15`.
- **Initial (incorrect) hypothesis:** mining wall-clock guardrail truncated DB writes. This was wrong — see corrected root cause below.
- **Corrected root cause:** the polyglot/language-brain miner routes findings into **per-language ganglion DBs** (`instances/<brain>/claw.db`), not only the root corpus `claw.db`. When findings are reconciled against the root DB *alone*, repos mined under the `typescript`/`rust` brains appear to have "lost" methodologies that were in fact persisted to the ganglion DB. The ganglion DBs are created/populated at mine time, so they were absent when the root-only reconcile first ran. No data was lost.
- **Verification (recovery run 2026-06-29):** re-mined careframe, mydisasters, finESS, fractal with `--force-rescan --max-minutes 20`. Registry recorded 62 methodology IDs; reconcile across all three DBs found 62/62 (root=25, typescript=29, rust=8). careframe→typescript, mydisasters→rust, finESS/fractal→split python(root)+typescript. Zero gap.
- **Mitigation (applied):** none needed for data recovery; the corrected reconcile must scan root **and** all `instances/*/claw.db` ganglion DBs.
- **Mitigation (tooling, recommended):** (1) any registry-vs-DB reconcile / audit must union the root corpus with all ganglion DBs before declaring drift; (2) `cam enrich --include-ganglia` to assimilate embryonic findings across ganglia, not just root.
- **Status:** Resolved — all findings accounted for; the only real defect found was that a root-only reconcile gives false "missing" signals.

## Safe Next Step

Do a launch refresh in this order:

1. Decide whether canonical public metrics come from the current checkout DB or the larger backup DB.
2. Upgrade/audit frontend dependencies.
3. Update README and static launch pages from one verified metrics table.
4. Run backend, frontend, static landing, and Repo Rescue Desk browser smoke checks.
