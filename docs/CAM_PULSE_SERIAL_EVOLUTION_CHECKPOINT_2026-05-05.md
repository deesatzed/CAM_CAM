# CAM-PULSE Serial Evolution Checkpoint - 2026-05-05

## Status

- Current champion: `v21-candidate`
- Champion pointer: `instances/evolution/current_champion.json`
- Control DB: `data/claw.db`
- Latest promoted run: cycle 21, run `691dda1c-d4db-45e0-953b-c657c1a7b350`
- Active run: none
- OpenRouter budget remaining after cycle 21: approximately `$14.4436`
- Latest verification: `176 passed`

## What Was Proven

- Autonomous folder mining runs without a human in the loop.
- The loop consumes exactly three repos per round.
- Challenger DBs are isolated from the champion.
- Live mining artifacts are attributed across primary challenger DBs and ganglion DBs.
- Exact-batch coverage is enforced: any rejected repo blocks promotion.
- A fully accepted batch can promote automatically.
- Current champion advanced from `v17-candidate` to `v21-candidate`.

## Model Path

Allowed models remain:

- `qwen/qwen3.6-flash`
- `deepseek/deepseek-v4-flash`
- `deepseek/deepseek-v4-pro`
- `openai/gpt-mini-latest`

Observed behavior:

- Live probe succeeded with `qwen/qwen3.6-flash`.
- Most mining calls succeeded on `deepseek/deepseek-v4-flash`.
- `WhiskeySages` validated model-quality escalation: DeepSeek returned zero findings, then `qwen/qwen3.6-flash` recovered useful findings.
- `deepseek/deepseek-v4-pro` and `openai/gpt-mini-latest` were not needed in the latest promoted round.

## Recent Round Outcomes

- Cycle 19: rejected because `sciwrite` had no recognizable source files.
- Cycle 20: rejected because `project-playbook` had no recognizable source files.
- Cycle 21: promoted after `DataDesigner`, `wikiwise`, and `WhiskeySages` all accepted.

## Hardened Failure Points

- Consumed repo selection now excludes by both resolved path and `source_ref`.
- No-source repos are treated as permanently skipped after detection.
- Live mining now preflights repos for recognizable source before paid model calls.
- Prompt capping keeps oversized repos under the configured token budget.
- Capability enrichment is deterministic in budget mode.
- Model escalation is deduped by model ID, not just agent label.
- Secondary polyglot zones below the 3-file threshold are skipped before paid calls.
- Generated bundles and generated Tauri schema JSON are skipped during serialization.

## Known Remaining Gaps

- The loop is still primarily evolving `data_feature` knowledge.
- Prompt/config CAM-enhancing-CAM is the next major layer to automate.
- Some large repos still approach the prompt cap and can cause high latency.
- The selection/staging flow is partly external; deeper integration with `repo421sn.txt` freshness ordering would reduce manual staging.

## Next Intended Step

Move from stabilized repo mining into budget-bound `prompt_config` evolution, while preserving the exact-batch, isolated-challenger, and auto-promotion gates already proven in data-feature cycles.
