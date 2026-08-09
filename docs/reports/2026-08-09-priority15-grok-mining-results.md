# Priority 15 changed-only mining result

Date: 2026-08-09

## Outcome

- Exact model: `x-ai/grok-4.5`
- Authorization: `$5.00`
- Actual and conservative spend: `$3.0921648`
- Unused authorization: `$1.9078352`
- Receipt status: `completed`
- Calls: 96 completed, 0 failed, 0 submitted
- Repositories processed: 15
- Source-bearing repositories mined: 14
- Findings stored: 80
- Tokens: 1,124,515
- Tasks generated: 0
- Receipt: `data/mining_runs/2026-08-09-repos-txt-priority15-grok-4.5-5usd.json`

## Repository results

| Repository | Findings | Tokens | Result |
|---|---:|---:|---|
| `guild` | 5 | 86,443 | mined |
| `LocalRecall` | 5 | 78,242 | mined |
| `markmap` | 5 | 47,432 | mined |
| `repo-web` | 5 | 77,235 | mined |
| `taste-skill` | 0 | 0 | skipped: no recognizable source files |
| `Understand-Anything` | 5 | 82,576 | mined |
| `WhiskeySages` | 5 | 78,920 | mined |
| `XTtape` | 5 | 73,998 | mined |
| `blockify-agentic-data-optimization` | 5 | 67,861 | mined |
| `CAM_Codx` | 5 | 81,458 | mined |
| `careframe` | 5 | 78,115 | mined |
| `finESS` | 10 | 149,454 | mined in TypeScript and Python zones |
| `fractal` | 10 | 100,940 | mined in Python and TypeScript zones |
| `mydisasters` | 5 | 32,255 | mined |
| `SkillOpt` | 5 | 89,586 | mined |

## Verification

- The receipt file is mode `0600` and terminal `completed`.
- All 96 requested and returned model identities are exactly
  `x-ai/grok-4.5`.
- The live OpenRouter key moved from `$5.59391736` remaining before the run to
  `$2.50175256` after it, a `$3.0921648` delta matching the receipt exactly.
- All five SQLite databases returned `ok` from `pragma integrity_check`.
- New methodology rows by destination were: root/Python 30, Go 10,
  TypeScript 35, Rust 5, misc 0.
- All 80 ledger methodology IDs are unique and present in the union of the
  root and language ganglion databases.
- All 80 new rows have capability data, novelty score, and potential score;
  all entered the `embryonic` lifecycle state.
- `claw.toml` and `model_profiles.toml` hashes were unchanged by mining.
- The focused miner gate passed 107 tests under the authoritative current
  source path, with the known non-fatal aiosqlite event-loop cleanup warning.
  An initially unpinned command imported the older editable checkout at
  `/Volumes/WS4TB/WS4TBr/CAM_Codx/CAM_CAM`; pinning `PYTHONPATH` to this
  checkout removed that environment-only false failure.
- An immediate pinned changed-only scan excluded all 14 mined repositories.
  It retained only `taste-skill`, which discovery sees as a repository but the
  miner rejects before any LLM call because it has no recognizable source
  files. Repeating the same run would skip it again without spend.
