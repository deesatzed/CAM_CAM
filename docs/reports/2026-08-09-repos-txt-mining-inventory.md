# repos.txt Mining Inventory — 2026-08-09

## Scope and controls

- Source list: `/Volumes/WS4TB/repos.txt`
- Roots listed and present: 11 of 11
- Database: `/Volumes/WS4TB/repo622sn/CAM_CAM/claw.db`
- Scan: `--changed-only --scan-only --depth 8 --dedup`
- Model calls and spend: none
- Complete eligible-repository inventory:
  `docs/reports/2026-08-09-repos-txt-eligible.json`

## Inventory result

| State | Count |
|---|---:|
| Unique discovered paths | 352 |
| Canonical candidates after iteration deduplication | 334 |
| Duplicate iterations removed | 18 |
| Never mined | 316 |
| Changed since last mining | 7 |
| Total eligible | 323 |

Eligible candidates by selected source root:

| Root | Eligible |
|---|---:|
| `/Volumes/WS4TB/repo421sn` | 289 |
| `/Volumes/WS4TB/repo622sn` | 26 |
| `/Volumes/WS4TB/WS4TBr/repoWeb` | 2 |
| `/Volumes/WS4TB/repoArk` | 1 |
| `/Volumes/WS4TB/CAM_ARCHIVE/WS4TB__MyGhRepos_CAM_CAM` | 1 |
| `/Volumes/WS4TB/CAM_ARCHIVE/WS4TB_repo421sn_CAM_CAM` | 1 |
| `/Volumes/WS4TB/WS4TBr/CP_FPE/repofractL` | 1 |
| `/Volumes/WS4TB/WS4TBr/Git_Repo_Nexus` | 1 |
| `/Volumes/WS4TB/WS4TBr/myrepoweb` | 1 |

The other two listed roots contributed only candidates deduplicated in favor of
newer or stronger canonical iterations from the roots above.

## Changed repositories

1. `/Volumes/WS4TB/repo622sn/CAM_Codx`
2. `/Volumes/WS4TB/repo622sn/SkillOpt`
3. `/Volumes/WS4TB/repo622sn/blockify-agentic-data-optimization`
4. `/Volumes/WS4TB/repo622sn/mydisasters`
5. `/Volumes/WS4TB/repo622sn/fractal`
6. `/Volumes/WS4TB/repo622sn/careframe`
7. `/Volumes/WS4TB/repo622sn/finESS`

## Proposed first paid batch

The proposal prioritizes every changed repo, then fills the batch with eight
new, recent, size-efficient repositories. A second scan of these exact paths
confirmed 15 of 15 remain eligible.

| # | Repository | State |
|---:|---|---|
| 1 | `/Volumes/WS4TB/repo622sn/CAM_Codx` | changed |
| 2 | `/Volumes/WS4TB/repo622sn/SkillOpt` | changed |
| 3 | `/Volumes/WS4TB/repo622sn/blockify-agentic-data-optimization` | changed |
| 4 | `/Volumes/WS4TB/repo622sn/mydisasters` | changed |
| 5 | `/Volumes/WS4TB/repo622sn/fractal` | changed |
| 6 | `/Volumes/WS4TB/repo622sn/careframe` | changed |
| 7 | `/Volumes/WS4TB/repo622sn/finESS` | changed |
| 8 | `/Volumes/WS4TB/repo622sn/taste-skill` | new |
| 9 | `/Volumes/WS4TB/repo622sn/Understand-Anything` | new |
| 10 | `/Volumes/WS4TB/repo421sn/WhiskeySages` | new |
| 11 | `/Volumes/WS4TB/WS4TBr/myrepoweb/repo-web` | new |
| 12 | `/Volumes/WS4TB/repo622sn/XTtape` | new |
| 13 | `/Volumes/WS4TB/repo421sn/LocalRecall` | new |
| 14 | `/Volumes/WS4TB/repo421sn/guild` | new |
| 15 | `/Volumes/WS4TB/repo421sn/markmap` | new |

Recommended controls if approved:

- exact model: `x-ai/grok-4.5`;
- fresh receipt and hard `$5` maximum;
- current key-specific funds at assessment time: approximately `$5.61`;
- authoritative DB and model profiles pinned;
- `--changed-only`, `--max-repos 15`, `--no-tasks`, no fast mode, no
  self-assessment;
- the hard cap may stop before all 15 finish; completed repos remain durable and
  the receipt will identify exactly where it stopped.

`tabfm` is intentionally excluded because its prior four attempts ended without
a durable mining record.
