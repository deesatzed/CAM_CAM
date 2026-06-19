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

## Safe Next Step

Do a launch refresh in this order:

1. Decide whether canonical public metrics come from the current checkout DB or the larger backup DB.
2. Upgrade/audit frontend dependencies.
3. Update README and static launch pages from one verified metrics table.
4. Run backend, frontend, static landing, and Repo Rescue Desk browser smoke checks.
