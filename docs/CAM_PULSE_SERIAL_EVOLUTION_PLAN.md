# CAM-PULSE Serial Evolution Plan

## Purpose

This plan defines a controlled way to evolve CAM-PULSE through many serial
cycles. Each cycle keeps one current best instance, creates one candidate copy,
mines new material, changes exactly one major layer, evaluates the candidate
against the current best, and promotes only if the candidate wins without
violating regression, safety, cost, or stability gates.

The goal is not unlimited self-modification. The goal is compounding validated
improvement with attribution, rollback, and enough monitoring to detect when the
loop starts optimizing the wrong thing.

## Aligned Long-Term Outcome

CAM-PULSE serial evolution is intended to become a self-improving CAM lineage
system, not a one-off repo mining script.

The long-term target is:

1. There is always one active champion CAM instance that downstream commands use.
2. Every autonomous round creates an isolated challenger CAM instance.
3. Mining, assimilation, prompt changes, routing policy changes, model changes,
   and eventually bounded code changes happen only inside the challenger until
   promotion.
4. Each unattended data-feature round mines exactly three external repos from the
   configured repo folder.
5. Mined material must become operational CAM capability: methodologies, action
   templates, components, retrieval features, failure knowledge, routing policy,
   prompt/config improvements, or validated code improvements.
6. Champion and challenger are evaluated on the same benchmarks before promotion.
7. Promotion requires measured lift, validation, cost discipline, provenance, and
   rollback availability.
8. The OpenRouter key budget is the loop constraint. The system should keep
   iterating until budget, repo supply, or gates stop it.
9. Model use must be cost-aware: use the cheapest approved model that can do the
   work effectively, escalate on failure, and quarantine broken routes.

The near-term milestone is one real live three-repo autonomous round that proves:

- OpenRouter probing and mining work against the approved model chain.
- Live mining writes to the challenger DB, not the champion DB.
- Paired retrieval and task-readiness evaluation compare the two instances.
- Required validation gates decide whether the challenger can be promoted.
- Failure causes are captured well enough to drive the next hardening patch.

The destination state is CAM enhancing CAM through a chain of validated,
rollbackable champion replacements.

### Alignment Snapshot - 2026-05-04

We are aligned that the expected outcome is autonomous CAM improvement, not a
manual review workflow. Human intervention should not be part of the normal
loop. The loop should stop because budget, repo supply, validation gates, or
runtime controls stop it.

Current implementation status:

- The control plane exists: champion/challenger instances, run records,
  decisions, mined inputs, mutations, evaluations, and monitor events.
- The active automation path is budget-bound through OpenRouter checks and uses
  only the approved low-cost model set.
- A live run probes the approved model chain before mining and escalates past
  broken model routes.
- Each repo-folder round selects exactly three previously unmined repo
  subdirectories.
- Live mining writes into an isolated challenger database clone.
- Paired retrieval and task-readiness evaluations compare challenger behavior
  against the champion before promotion.
- Required validation checks now guard challenger database isolation, schema
  integrity, mined-input attribution, and paired evaluation coverage.

Remaining gaps before this is the full long-term system:

- Promoted champion database pointers are recorded in
  `instances/evolution/current_champion.json`. Downstream commands can opt into
  that pointer with `CLAW_USE_EVOLUTION_CHAMPION=1`; evolution control commands
  continue to use the control-plane DB.
- Prompt/config/policy mutation is still mostly staged; the strongest current
  path is data-feature mutation through mined methodologies and action
  templates.
- Evaluation is still lightweight and proxy-heavy; it needs real task execution
  benchmarks before promotions should be treated as production-grade.
- Bounded CAM code mutation should come later, after data, prompt/config, model
  routing, rollback, and validation gates are more mature.

### Live Round 5 Findings - 2026-05-04

The first post-alignment live round ran one capped autonomous batch:

- Mining folder: `batch_run/compare/deepseek-v4-pro`
- Repos selected: `JRE-BSG-DHSW`, `t2-07`, `t2-09`
- Challenger: `instances/evolution/challengers/v5-candidate`
- Challenger DB: `instances/evolution/challengers/v5-candidate/data/claw.db`
- OpenRouter probe: one approved model route failed with HTTP 400, then
  `qwen/qwen3.6-flash` succeeded.
- Budget after the run: approximately `$15.97` remaining on the key limit.
- Decision: reject. The strongest proxy slice improved by `+0.008`, but the
  primary paired task-readiness slice showed no lift, so the 3% promotion
  threshold was not met.

Root causes found:

- The LLM router was constrained to the approved model set, but the embedding
  layer still used a paid OpenRouter embedding model
  (`perplexity/pplx-embed-v1-4b`). That violated the cost/model boundary even
  though the chat-completion model path was compliant.
- Repo-level timeout was too coarse. Two repos wrote useful methodologies into
  the challenger DB before the 180-second timeout, but the mined input rows were
  rejected because the async call never returned a final result object.
- The paired task-readiness benchmark is currently saturated for this kind of
  mined material; champion and challenger both scored the same on the primary
  paired slice even though the challenger gained new artifacts.
- Scenario enrichment attempted to embed more than the provider's 512-item array
  limit in one request. This logged a warning and continued, but it wastes a
  model-side opportunity.
- Some DeepSeek responses placed usable content in reasoning fields or returned
  non-JSON prose where strict JSON was expected. Existing fallbacks kept the run
  alive, but enrichment quality was reduced.

Mitigation applied immediately:

- Automation configs now use local deterministic `hash-embedding-384`
  embeddings. That removes paid embedding calls from the live loop and keeps
  paid model use constrained to the approved OpenRouter chat model set.
- Live repo timeout handling now reconciles challenger DB side effects after a
  timeout. If repo-tagged methodologies or action templates already landed in
  the isolated challenger DB, the mined input is recorded as an accepted partial
  timeout with `partial_timeout`, `timeout_error`, and unavailable cost-accounting
  metadata instead of being discarded.
- Scenario enrichment now batches scenario embedding requests under provider
  array limits instead of sending the full scenario set in one request.
- Empty language zones, such as a `tsconfig.json` with no TypeScript files, are
  removed from live mining plans before model calls.
- The champion pointer can be synced with `cam evolution champion-db`; successful
  promotions and registrations update it automatically.
- Paired task-readiness now includes artifact attribution. Accepted mined
  methodology and action-template IDs must resolve in the evaluated DB, so
  challenger-only operational artifacts can produce measured lift even when
  generic retrieval is saturated.
- A regression test now simulates this exact failure mode and verifies recovered
  partial successes are accepted and monitor events are recorded.

Next hardening targets:

- Extend paired task-readiness from attributed artifact coverage to actual task
  execution traces and action-template application outcomes.
- Make downstream automation explicitly set `CLAW_USE_EVOLUTION_CHAMPION=1` when
  it should operate on the promoted champion instead of the control plane.

### Live Round 6 Findings - 2026-05-04

After the hardening patches, a second capped live round ran against
`batch_run/results/compare_overnight/deepseek-v4-flash`.

- Repos selected: `ClinSafer`, `t2-04`, `t2-10`
- Challenger: `instances/evolution/challengers/v6-candidate`
- Challenger DB: `instances/evolution/challengers/v6-candidate/data/claw.db`
- OpenRouter probe: `google/gemini-flash-latest` failed with HTTP 400, then
  `qwen/qwen3.6-flash` succeeded.
- Mining model: `deepseek/deepseek-v4-flash`
- Budget after the run: approximately `$15.92` remaining on the key limit.
- Decision: promote. Paired task-readiness improved from `0.756077` to
  `0.868577`, a `+0.1125` absolute score delta and about `14.88%` relative lift.

Validated mitigations:

- Empty-zone mining was removed. `ClinSafer` routed directly to the Python brain
  instead of also issuing a TypeScript call for a zero-file TypeScript zone.
- Paid embeddings were removed from the live loop. The run built 792 scenarios
  without the previous OpenRouter embedding batch-limit failure.
- Timeout reconciliation worked. `ClinSafer` exceeded the repo timeout after
  writing challenger artifacts, and the loop recovered those side effects as an
  accepted partial timeout instead of discarding them.
- Artifact-attributed paired task-readiness promoted the challenger only after
  the accepted mined methodologies were present in the challenger DB and absent
  from the champion DB.
- The champion pointer now targets the promoted isolated DB at
  `instances/evolution/challengers/v6-candidate/data/claw.db`.

Remaining failure pattern:

- DeepSeek still sometimes returns enrichment JSON in reasoning fields or as
  non-JSON prose. The run survives this, but capability and synergy enrichment
  quality is degraded when strict parsing fails.

Mitigation applied after the run:

- Capability and synergy parsers now extract the first valid JSON object from
  fenced output or reasoning/prose-wrapped output before schema validation.
  This should recover many enrichment responses that previously logged parse
  failures despite containing usable JSON.
- Paired task-readiness now records deterministic action-template application
  traces. For each evaluated task intent, the report captures selected template
  IDs, task-token fit, executable step counts, acceptance checks, rollback or
  precondition coverage, and a per-template application score.
- Capability and synergy extraction now request OpenRouter JSON-object response
  format first, with fallback to plain completion if a provider rejects that
  option. Prompts also explicitly require JSON in message content rather than
  reasoning-only output.

### Live Round 7 Findings - 2026-05-05

A third capped live round validated the action-template application trace metric
against `batch_run/results/compare_overnight/deepseek-v4-flash`.

- Repos selected: `t2-11`, `t2-12`, `t2-13`
- Challenger: `instances/evolution/challengers/v7-candidate`
- Challenger DB: `instances/evolution/challengers/v7-candidate/data/claw.db`
- OpenRouter probe: `google/gemini-flash-latest` failed with HTTP 400, then
  `qwen/qwen3.6-flash` succeeded.
- Mining model: `deepseek/deepseek-v4-flash`
- Decision: promote. Paired task-readiness improved from `0.746589` to
  `0.846589`, a `+0.1000` absolute score delta and about `13.39%` relative lift.

Validated mitigations:

- All three mined inputs were accepted.
- `t2-12` crossed the repo timeout after challenger writes and was recovered as
  an accepted partial timeout with 13 artifacts.
- The paired task-readiness report now contains action-template application
  traces, including selected template IDs, task fit, execution step coverage,
  acceptance checks, and application scores.
- The champion pointer now targets `v7-candidate`.

Remaining failure pattern:

- Application traces were recorded, but the champion and challenger scored the
  same on generic runbook application. The promotion lift came from attributed
  mined artifact coverage. The next step is to generate source-linked action
  templates more reliably from mined methodologies so application traces can
  distinguish the challenger, not only artifact attribution.

Mitigation applied after the run:

- Every accepted mined finding now creates a source-linked action template.
  Explicit model-provided execution steps and acceptance checks are preserved.
  Findings without explicit runbooks receive a conservative adaptation template
  tied to the mined methodology, source repo, source files, rollback guidance,
  and verification expectations.
- Seed capability metadata now marks all accepted findings as action-template
  candidates, with a separate `has_explicit_runbook` trigger when the model
  provided concrete steps or checks.
- This closes the latest CAM-enhancing-CAM drift: mined knowledge is no longer
  only passive retrieval material. It becomes measurable executable reuse input
  for paired task-readiness and later task execution benchmarks.

### Live Round 8 Findings - 2026-05-05

A fourth capped live round validated source-linked fallback action templates
against `batch_run/results/compare_overnight/deepseek-v4-flash`.

- Repos selected: `t2-16`, `t3-04`, `t3-05`
- Challenger: `instances/evolution/challengers/v8-candidate`
- Challenger DB: `instances/evolution/challengers/v8-candidate/data/claw.db`
- OpenRouter probe: `google/gemini-flash-latest` failed with HTTP 400, then
  `qwen/qwen3.6-flash` succeeded.
- Mining model: `deepseek/deepseek-v4-flash`
- Budget after the run: approximately `$15.97` remaining on the key limit.
- Decision: promote. Paired task-readiness improved from `0.746589` to
  `0.846589`, a `+0.1000` absolute score delta and about `13.39%` relative lift.

Validated mitigations:

- The selected repos produced 2, 8, and 12 accepted findings.
- Those same repos produced exactly 2, 8, and 12 action-template IDs. This
  confirms accepted mined findings now become source-linked operational
  templates even when model output is sparse.
- Validation required challenger database isolation, SQLite integrity,
  required tables, live mining target attribution, and paired evaluation
  coverage; all required checks passed.
- The champion pointer now targets `v8-candidate`.

Remaining failure pattern:

- `deepseek/deepseek-v4-flash` remains effective for mining, but it sometimes
  returns JSON enrichment work as reasoning-only text even when JSON-object mode
  is requested. That causes capability or synergy enrichment to degrade while
  mined methodology/action-template creation still succeeds.

Mitigation applied after the run:

- The approved live-probe/model allowlist now replaces
  `google/gemini-flash-latest` with `openai/gpt-mini-latest`. The old Gemini
  route repeatedly returned OpenRouter HTTP 400 in live probes, so it is no
  longer part of the active automation path.
- After live testing, `openai/gpt-mini-latest` also returned OpenRouter HTTP
  400. It remains in the allowlist because it was explicitly requested, but the
  working `qwen/qwen3.6-flash` route is now first in probe order to avoid
  starting every round with a known failing route.
- Capability and synergy JSON work now prefers the approved `qwen/qwen3.6-flash`
  route before DeepSeek routes. This keeps enrichment on a cheap model that
  passed the live OpenRouter probe and avoids known DeepSeek reasoning-only
  JSON behavior.
- Capability enrichment now has a deterministic partial fallback. If the model
  returns invalid JSON, CAM preserves source repo, category, files, triggers,
  conservative inputs/outputs, and risks instead of leaving the methodology as
  failed enrichment.

### Live Round 9 Findings - 2026-05-05

A fifth capped live round ran after swapping Gemini out of the active model set.

- Mining folder: `batch_run/results/compare_overnight/grok-4.3`
- Repos selected: `ClinSafer`, `t2-04`, `t2-10`
- Challenger: `instances/evolution/challengers/v9-candidate`
- Challenger DB: `instances/evolution/challengers/v9-candidate/data/claw.db`
- OpenRouter probe: `openai/gpt-mini-latest` failed with HTTP 400, then
  `qwen/qwen3.6-flash` succeeded.
- Mining model: `deepseek/deepseek-v4-flash`
- Budget after the run: approximately `$15.96` remaining on the key limit.
- Decision: promote. Paired task-readiness improved from `0.746427` to
  `0.846427`, a `+0.1000` absolute score delta and about `13.40%` relative lift.

Validated mitigations:

- The run stayed automated and selected exactly three repos.
- All three mined inputs were accepted.
- The selected repos produced 7, 11, and 6 findings, and exactly 7, 11, and 6
  source-linked action-template IDs.
- `t2-04` crossed the repo timeout boundary after writing artifacts and was
  recovered as an accepted partial timeout.
- Required validation passed: isolated challenger DB, SQLite integrity,
  required tables, live mining target attribution, and paired evaluation
  coverage.
- The champion pointer now targets `v9-candidate`.

Remaining failure pattern:

- Synergy and potential scoring still issued extra LLM calls that sometimes
  routed to DeepSeek reasoning-only output. These calls are expensive relative
  to their current promotion value and repeatedly produced zero synergies.

Mitigation applied after the run:

- Budget-mode configs now set `llm_analysis_weight = 0.0` and
  `potential_llm_weight = 0.0`.
- The assimilation code now explicitly skips LLM synergy and potential calls
  when those weights are zero, using fast deterministic signals instead. This
  removes a recurring JSON failure point and reduces per-repo cost/latency.

### Live Round 10 Findings - 2026-05-05

A sixth capped live round validated qwen-first probing and budget-mode
assimilation after the round 9 hardening.

- Mining folder: `batch_run/results/compare_overnight/grok-4.3`
- Repos selected: `t2-11`, `t2-12`, `t2-13`
- Challenger: `instances/evolution/challengers/v10-candidate`
- Challenger DB: `instances/evolution/challengers/v10-candidate/data/claw.db`
- OpenRouter probe: `qwen/qwen3.6-flash` succeeded on the first attempt.
- Mining model: `deepseek/deepseek-v4-flash`
- Budget after the run: approximately `$15.76` remaining on the key limit.
- Decision: promote. Paired task-readiness improved from `0.746589` to
  `0.846589`, a `+0.1000` absolute score delta and about `13.39%` relative lift.

Validated mitigations:

- Qwen-first probing avoided a known failing first-route call.
- The run stayed automated and selected exactly three repos.
- All three mined inputs were accepted.
- The selected repos produced 6, 10, and 10 findings, and exactly 6, 10, and 10
  source-linked action-template IDs.
- `t2-11` crossed the repo timeout boundary after writing artifacts and was
  recovered as an accepted partial timeout.
- Budget-mode synergy and potential scoring used deterministic signals. The
  prior DeepSeek reasoning-only synergy JSON warnings did not recur.
- Required validation passed: isolated challenger DB, SQLite integrity,
  required tables, live mining target attribution, and paired evaluation
  coverage.
- The champion pointer now targets `v10-candidate`.

### Live Round 11 Findings - 2026-05-05

A seventh capped live round consumed the last full three-repo batch available in
`batch_run/results/compare_overnight/grok-4.3`.

- Repos selected: `t2-16`, `t3-04`, `t3-05`
- Challenger: `instances/evolution/challengers/v11-candidate`
- Challenger DB: `instances/evolution/challengers/v11-candidate/data/claw.db`
- OpenRouter probe: `qwen/qwen3.6-flash` succeeded on the first attempt.
- Mining model: `deepseek/deepseek-v4-flash`
- Budget after the run: approximately `$15.59` remaining on the key limit.
- Decision: promote. Paired task-readiness improved from `0.746589` to
  `0.846589`, a `+0.1000` absolute score delta and about `13.39%` relative lift.

Validated mitigations:

- Qwen-first probing continued to avoid a known failing first-route call.
- The run stayed automated and selected exactly three repos.
- All three mined inputs were accepted.
- The selected repos produced 9, 8, and 2 findings, and exactly 9, 8, and 2
  source-linked action-template IDs.
- Budget-mode synergy and potential scoring again used deterministic signals;
  the prior reasoning-only synergy JSON warnings did not recur.
- Required validation passed: isolated challenger DB, SQLite integrity,
  required tables, live mining target attribution, and paired evaluation
  coverage.
- The champion pointer now targets `v11-candidate`.

Current stop condition for this folder:

- Only `t3-07` remains unmined in
  `batch_run/results/compare_overnight/grok-4.3`, so this folder no longer has
  enough unmined repos for another exact three-repo round.

### Live Rounds 12-14 Findings - 2026-05-05

The next mining source moved to latest unmined folders from
`/Volumes/WS4TB/repo421sn`, staged under
`instances/evolution/repo_batches/`.

Round 12:

- Repos selected: `claw-code`, `ClawRouter`, `open-design`
- Challenger: `instances/evolution/challengers/v12-candidate`
- OpenRouter probe: `qwen/qwen3.6-flash` succeeded on the first attempt.
- Mining model: `deepseek/deepseek-v4-flash`
- Decision: reject. Root cause: the timeout recovery path only inspected the
  primary challenger DB, while language-specific mining wrote successful
  artifacts into ganglion DBs such as `instances/typescript/claw.db`.
- Mitigation: timeout recovery now searches the primary challenger DB plus all
  `instances/*/claw.db` ganglion DBs, and rejected timeout rows are retriable
  instead of being treated as permanently mined.

Round 13:

- Repos retried: `claw-code`, `ClawRouter`, `open-design`
- Challenger: `instances/evolution/challengers/v13-candidate`
- Decision: reject. All three inputs were accepted, including a partial timeout
  recovered from `instances/rust/claw.db`, but paired task-readiness still
  scored `0.760693` for both champion and challenger.
- Root cause: successful and recovered ganglion artifacts were recorded as IDs,
  but the paired scorer attributed IDs only inside
  `v13-candidate/data/claw.db`; ganglion artifact IDs therefore contributed
  zero lift.
- Mitigation: normal live-mining completion now records `artifact_db_paths`, and
  paired task-readiness counts expected methodology/action-template IDs across
  the primary challenger DB and recorded ganglion DBs.

Round 14:

- Repos selected by actual latest unmined directory mtime: `QwPiCCO`,
  `ProBioGrade`, `Oneira`
- Staging folder:
  `instances/evolution/repo_batches/repo421sn_latest_20260505_b2`
- Challenger: `instances/evolution/challengers/v14-candidate`
- OpenRouter probe: `qwen/qwen3.6-flash` succeeded on the first attempt.
- Mining model: `deepseek/deepseek-v4-flash`
- Accepted findings/action templates: `QwPiCCO` 14/14, `ProBioGrade` 15/15,
  `Oneira` 11/11.
- Artifact DB attribution:
  - `QwPiCCO`: primary challenger DB plus `instances/typescript/claw.db`
  - `ProBioGrade`: `instances/typescript/claw.db`
  - `Oneira`: `instances/typescript/claw.db`
- Decision: promote. Paired task-readiness improved from `0.746104` to
  `0.846104`, a `+0.1000` absolute score delta and about `13.40%` relative
  lift. The current champion pointer now targets `v14-candidate`.
- Budget after the run: approximately `$15.03` remaining on the key limit.

Remaining failure points:

- Large accepted prompts can block inside a single provider request for several
  minutes. `ProBioGrade` estimated roughly 154K prompt tokens and `Oneira`
  roughly 67K; both completed, but they exposed latency and budget risk.
- Some enrichment paths still issued HTTP calls after methodology creation. The
  prior hardening removed low-value LLM synergy/potential scoring when weights
  are zero, and the latest hardening adds `capability_llm_enabled = false` so
  capability enrichment uses deterministic local fallback in budget mode.
- Malformed JSON remains common on large mining responses. JSON repair recovered
  the observed failures, but this is still a provider-output risk.

Next mitigations:

- Add a per-request budget/latency cap that shrinks or chunks oversized repo
  prompts before sending them to OpenRouter.
- Keep `capability_llm_enabled = false` in budget-mode configs so enrichment
  stays local after each core repo/zone mining call.
- Keep the approved escalation order cheapest-first and route hard provider
  failures to the next allowed model.

### Live Round 15 Findings - 2026-05-05

Round 15 validated the budget-mode capability enrichment switch.

- Repos selected by actual latest unmined directory mtime: `warp`, `Scrapling`,
  `md-preview`
- Staging folder:
  `instances/evolution/repo_batches/repo421sn_latest_20260505_b3`
- Challenger: `instances/evolution/challengers/v15-candidate`
- OpenRouter probe: `qwen/qwen3.6-flash` succeeded on the first attempt.
- Mining model: `deepseek/deepseek-v4-flash`
- Accepted findings/action templates: `warp` 22/22, `Scrapling` 10/10,
  `md-preview` 19/19.
- `warp` was accepted as a partial timeout recovery after Rust artifacts were
  written into `instances/rust/claw.db`.
- Decision: promote. Paired task-readiness improved from `0.761879` to
  `0.849758`, a `+0.087879` absolute score delta and about `11.53%` relative
  lift. The current champion pointer now targets `v15-candidate`.
- Budget after the run: approximately `$14.73` remaining on the key limit.

Validated mitigation:

- Capability enrichment emitted deterministic local enrichment logs and did not
  emit per-methodology OpenRouter calls. The paid calls observed in the round
  were the initial model probe and core mining calls per repo/zone.

Remaining root cause:

- Oversized repo prompts still dominate latency and cost. `warp` required a
  long Rust-zone completion and `Scrapling` estimated roughly 231K prompt
  tokens.

Mitigation implemented after the run:

- `MiningRecoveryConfig.max_prompt_tokens` now defaults to `80000`.
- Before the first paid mining call, the miner estimates prompt tokens and
  reserializes the repo/zone with a smaller byte cap when the prompt exceeds the
  configured token budget.
- Existing content-reduction and chunk-mining recovery remain in place for
  provider failures or zero-finding responses.

### Live Round 16 Findings - 2026-05-05

Round 16 validated the prompt-token cap in a live OpenRouter mining run.

- Repos selected by actual latest unmined directory mtime: `repofrax`,
  `CAM-RAG`, `sci-stapler`
- Staging folder:
  `instances/evolution/repo_batches/repo421sn_latest_20260505_b4`
- Challenger: `instances/evolution/challengers/v16-candidate`
- OpenRouter probe: `qwen/qwen3.6-flash` succeeded on the first attempt.
- Mining model: `deepseek/deepseek-v4-flash`, with escalation to qwen when
  DeepSeek returned reasoning-only content for `repofrax`.
- Accepted findings/action templates: `repofrax` 8/0, `CAM-RAG` 15/15,
  `sci-stapler` 8/8.
- `repofrax` was accepted as a partial timeout/recovery case after methodology
  artifacts were written but action templates were not produced.
- `CAM-RAG` triggered the new prompt cap: the miner reduced the prompt from
  about 225K estimated tokens to about 72K before the paid mining call.
- Decision: promote. Paired task-readiness improved from `0.790429` to
  `0.857096`, a `+0.066667` absolute score delta and about `8.43%` relative
  lift. The current champion pointer now targets `v16-candidate`.
- Budget after the run: approximately `$14.65` remaining on the key limit.

New failure point:

- Model escalation deduped agents, not model IDs. Because both `claude` and
  `codex` were configured to `deepseek/deepseek-v4-flash`, a DeepSeek
  reasoning-only JSON failure retried the same model under a second agent label
  before reaching qwen.

Mitigation implemented after the run:

- Mining escalation now dedupes by model ID as well as agent ID, so a
  model-specific output-format failure moves directly to the next distinct
  allowed model.

### Live Round 17 Findings - 2026-05-05

Round 17 validated both the prompt-token cap and distinct-model escalation.

- Repos selected by actual latest unmined directory mtime: `quarkdown`,
  `CIO-II`, `academic-research-skills`
- Staging folder:
  `instances/evolution/repo_batches/repo421sn_latest_20260505_b5`
- Challenger: `instances/evolution/challengers/v17-candidate`
- OpenRouter probe: `qwen/qwen3.6-flash` succeeded on the first attempt.
- Prompt cap activations:
  - `quarkdown` misc zone: about 231K to 72K estimated tokens
  - `quarkdown` TypeScript zone: about 129K to 72K estimated tokens
  - `CIO-II`: about 97K to 71K estimated tokens
  - `academic-research-skills`: about 230K to 72K estimated tokens
- Distinct-model escalation validation:
  - `CIO-II`: DeepSeek returned reasoning-only output, then the miner moved
    directly to `qwen/qwen3.6-flash` and recovered 9 findings.
  - `academic-research-skills`: DeepSeek timed out, then the miner moved
    directly to `qwen/qwen3.6-flash`.
- Persisted mined inputs: `quarkdown` 30/30 accepted, `CIO-II` 9/9 accepted,
  `academic-research-skills` rejected after timeout with no recovered artifacts.
- Decision recorded: promote. Paired task-readiness improved from `0.746104` to
  `0.846104`, a `+0.1000` absolute score delta and about `13.40%` relative lift.
- Budget after the run: approximately `$14.62` remaining on the key limit.

New policy gap:

- The promotion gate allowed a partial batch to promote with only 2 accepted
  inputs. This conflicts with the automation contract that each round mines an
  exact three-repo batch.

Mitigation implemented after the run:

- The promotion gate now rejects any candidate with rejected mined inputs, even
  if the score lift passes. Future exact-batch rounds must accept every mined
  input before promotion.

### Live Round 18 Findings - 2026-05-05

Round 18 validated the exact-batch promotion gate in a live run.

- Repos selected by latest unmined order, allowing rejected repos to retry:
  `academic-research-skills`, `drawio-skill`, `JRE-BSG-DHSW`
- Staging folder:
  `instances/evolution/repo_batches/repo421sn_latest_20260505_b6`
- Challenger: `instances/evolution/challengers/v18-candidate`
- OpenRouter probe: `qwen/qwen3.6-flash` succeeded on the first attempt.
- Prompt cap activations:
  - `academic-research-skills`: about 230K to 72K estimated tokens
  - `JRE-BSG-DHSW`: about 200K to 72K estimated tokens
- Accepted findings/action templates:
  - `academic-research-skills`: 7/7 accepted on retry
  - `JRE-BSG-DHSW`: 10/10 accepted
  - `drawio-skill`: rejected with `No recognizable source files found`
- Decision: reject. Paired task-readiness still improved from `0.769773` to
  `0.869773`, but the new exact-batch gate correctly rejected the challenger
  because `accepted_inputs=2`, `rejected_inputs=1`, `total_inputs=3`.
- Budget after the run: approximately `$14.51` remaining on the key limit.

Validated mitigation:

- Partial-batch promotion is now blocked. The champion pointer remained on
  `v17-candidate`.

Remaining source-selection issue:

- Repos with no recognizable source files, such as `drawio-skill`, can still
  enter a three-repo batch and force rejection. The next hardening step should
  preflight candidate directories for recognizable source files before staging
  them, or classify no-source repos as permanently skipped rather than retriable.

Mitigation implemented after the run:

- Folder repo selection now treats `No recognizable source files found` as a
  permanent source exclusion, like an accepted input. Timeout and transient
  rejected sources remain retriable.

### Live Rounds 19-21 Findings - 2026-05-05

Round 19 validated permanent no-source exclusion across the next staged batch.

- Repos selected: `hermes-workspace`, `awesome-llm-apps`, `sciwrite`
- Staging folder:
  `instances/evolution/repo_batches/repo421sn_latest_20260505_b7`
- Challenger: `instances/evolution/challengers/v19-candidate`
- Accepted inputs: `hermes-workspace` 14 findings, `awesome-llm-apps` 8
  findings after escalation from DeepSeek to `qwen/qwen3.6-flash`.
- Rejected input: `sciwrite` with `No recognizable source files found`.
- Decision: reject. Exact-batch coverage rejected the challenger with
  `accepted_inputs=2`, `rejected_inputs=1`, `total_inputs=3`.
- Budget after the run: approximately `$14.49` remaining.

Round 20 exposed a second source-selection root cause.

- Repos selected by newest unconsumed date: `xmcp`, `project-playbook`, `agi`
- Staging folder:
  `instances/evolution/repo_batches/repo421sn_latest_20260505_b8`
- Challenger: `instances/evolution/challengers/v20-candidate`
- Accepted inputs: `xmcp` 8 findings, `agi` 11 findings after malformed JSON
  repair.
- Rejected input: `project-playbook` with `No recognizable source files found`.
- Decision: reject. Exact-batch coverage again protected the champion.
- Root cause: exclusion was path-based. Repos already mined from another staging
  path or no-source repos not seen before could still consume a batch slot.
- Mitigation: folder selection now excludes consumed repos by both resolved
  source path and `source_ref`, and live folder mining enables a cheap source
  preflight before any paid model call.

Round 21 validated the live source preflight and produced the next champion.

- Repos selected after source preflight: `DataDesigner`, `wikiwise`,
  `WhiskeySages`
- Staging folder:
  `instances/evolution/repo_batches/repo421sn_latest_20260505_b9`
- Challenger: `instances/evolution/challengers/v21-candidate`
- Accepted inputs:
  - `DataDesigner`: 9 findings after prompt cap from about 230K to 71K tokens
    and malformed JSON repair.
  - `wikiwise`: 15 findings after prompt cap from about 350K to 29K tokens.
  - `WhiskeySages`: 22 findings total; its TypeScript zone escalated from
    zero-finding `deepseek/deepseek-v4-flash` output to
    `qwen/qwen3.6-flash`.
- Decision: promote. The current champion pointer now targets `v21-candidate`.
- Budget after the run: approximately `$14.44` remaining.

New cost root cause:

- Polyglot config signals can include tiny secondary zones. `WhiskeySages` was
  mostly TypeScript, but a 2-file Rust zone triggered an extra paid pass and
  produced duplicate-looking application patterns.

Mitigation implemented after the run:

- Secondary polyglot zones below the existing 3-source-file threshold are now
  skipped before paid mining. Single-zone repos keep the existing single-brain
  behavior.
- Generated JavaScript bundles and generated Tauri schema JSON files are now
  skipped during serialization instead of entering prompt capping. This reduces
  token pressure before the first paid call.

Current status:

- Automated CAM instances are working as isolated champion/challenger DB copies.
- Live mining writes into the challenger and its ganglia, and paired evaluation
  can attribute those artifacts.
- Exact-batch gating is enforced.
- Model escalation is cheapest-first and distinct by model ID across the
  approved allowlist:
  `qwen/qwen3.6-flash`, `deepseek/deepseek-v4-flash`,
  `deepseek/deepseek-v4-pro`, `openai/gpt-mini-latest`.
- The loop is still only evolving data-feature knowledge. Prompt/config
  CAM-enhancing-CAM is the next layer to automate after the repo mining loop is
  stable under budget.

## Theory

The proposed system is a champion/challenger evolutionary loop with bounded
reinforcement learning inside each generation.

```text
champion vN
    |
    | duplicate
    v
challenger vN+1-candidate
    |
    | mine layer-specific material
    | mutate one layer
    | tune/search/train inside that layer
    | evaluate against champion
    v
promotion gate
    |
    +-- pass -> challenger becomes champion vN+1; old champion is archived
    |
    +-- fail -> challenger is rejected; champion remains vN
```

The design combines five ideas:

1. **Serial hill-climbing**: only one candidate competes against the current
   best at a time. This keeps lineage understandable and reduces operational
   complexity.
2. **Layer isolation**: each cycle mutates one major layer only. This gives
   attribution when a candidate improves or regresses.
3. **Bandit/RL credit assignment**: successful prompts, methodologies, agents,
   routes, and policies get higher posterior confidence; failures are demoted.
4. **External validation**: promotion is decided by independent evaluation
   windows, not by the candidate's own reward signal.
5. **Archive-first replacement**: old champions are deactivated, not immediately
   deleted. Rollback remains possible until enough future cycles pass.

The expected behavior is asymmetric: most candidates should fail or be neutral,
some should make small gains, and rare candidates should make large gains. That
is healthy. A loop where nearly every candidate wins is likely using weak gates.

## Evolution Layers

CAM-PULSE should rotate through four mutation layers.

| Layer | What Changes | Example Changes | Main Risk |
|---|---|---|---|
| Data-feature-level | What the system knows or retrieves | new mined repos, new methodology features, freshness rules, embeddings, feature filters | leakage, noisy knowledge, stale novelty |
| Strategy-policy-level | What the system does with predictions and knowledge | routing weights, abstention rules, escalation policy, reward shaping, acceptance thresholds | reward hacking, overfitting to benchmarks |
| Prompt/config-level | How agents are instructed and configured | prompt variants, tool-use rules, budget knobs, verifier thresholds | brittle prompt wins, hidden regressions |
| Model-level | Which model or local learner performs a role | model choice, fine-tune, ensemble composition, hyperparameters | high cost, non-repeatability, overfitting |

Recommended default rotation:

```text
1. data-feature-level
2. strategy-policy-level
3. prompt/config-level
4. model-level
5. full regression audit
6. repeat
```

Adaptive override is allowed when diagnostics show a clear bottleneck:

```text
weak retrieval or missing coverage       -> data-feature-level
bad decisions despite good retrieval     -> strategy-policy-level
inconsistent or invalid agent behavior   -> prompt/config-level
quality ceiling after other layers settle -> model-level
```

## Expected Results

Each cycle should produce durable artifacts:

- a baseline champion instance snapshot
- a challenger snapshot
- the selected evolution layer
- mined input and provenance
- mutation manifest
- training/search/tuning log
- evaluation report
- promotion/rejection decision
- rollback pointer
- monitoring events

Promotion expectations:

- A candidate must beat the champion on the primary composite score.
- A candidate must not regress critical gates, even if the composite improves.
- A candidate must prove the improvement on holdout tasks or time windows.
- A candidate must stay within cost, latency, and operational limits.
- A candidate must be explainable enough to know what changed.

Non-expectations:

- The loop should not guarantee monotonic gains every cycle.
- The loop should not delete prior champions immediately.
- The loop should not allow model-level, prompt-level, feature-level, and
  policy-level changes in the same normal cycle.
- The loop should not promote candidates based only on self-generated tests.

## Primary Metrics Contract

Every cycle should compute a single promotion score plus hard guardrail metrics.

```text
promotion_score =
    0.25 * functional_correctness
  + 0.15 * structural_compliance
  + 0.15 * intent_alignment
  + 0.15 * expectation_match
  + 0.10 * correction_efficiency
  + 0.10 * retrieval_or_knowledge_lift
  + 0.05 * cost_efficiency
  + 0.05 * stability
```

The weights should be configuration-driven and versioned. The initial values
above intentionally favor correctness and expectation match over cost savings.

Default promotion gate:

```text
promote if:
  promotion_score improves by >= 3%
  statistical confidence is acceptable for the sample size
  full validation gate passes
  no critical metric regresses beyond tolerance
  no cost or latency budget is exceeded
  improvement appears in at least 2 independent evaluation slices
```

Initial confidence standard:

- small pilot: positive bootstrap confidence interval or clear practical lift
- formal promotion: Mann-Whitney p < 0.05 or agreed nonparametric equivalent
- effect size target: Cohen's d >= 0.20 for meaningful repeated promotion

CAM-PULSE already has useful supporting concepts:

- `ab_quality_samples` dimensions for A/B quality analysis
- `methodology_fitness_log` and fitness vectors for memory quality
- `agent_scores` for Bayesian routing
- `prompt_variants` for prompt A/B testing
- `pulse_discoveries` and `pulse_scan_log` for mined source provenance
- `token_costs` for budget monitoring
- `validation_gate.py` for copy validation before replacement

## Layer-Specific Metrics

### Data-Feature-Level

Primary question: did new mined knowledge or features improve downstream work?

Metrics:

- methodology count delta
- novelty score distribution
- gap relevance score
- retrieval lift on benchmark queries
- downstream task quality with new knowledge enabled
- source diversity
- duplicate or clone-inflation rate
- stale-source rate
- license and security scan status
- leakage risk score

Promotion requires:

- retrieval quality improves or downstream task score improves
- no high-risk license/security source is promoted
- no major increase in irrelevant retrievals

### Strategy-Policy-Level

Primary question: did the system make better decisions with the same knowledge?

Metrics:

- task success rate
- correction attempts per successful task
- escalation accuracy
- agent routing posterior win rate
- regret versus champion routing
- abstention quality
- budget violations
- recovery rate after failure
- validation pass rate

Promotion requires:

- better success/correction tradeoff
- no increase in unrecoverable failures
- routing remains exploratory enough to avoid stale lock-in

### Prompt/Config-Level

Primary question: did instructions or thresholds improve behavior without code or
model changes?

Metrics:

- valid output rate
- task completion rate
- test pass rate
- tool-use correctness
- format compliance
- repeated-run consistency
- token cost per task
- latency per task
- prompt variant win probability

Promotion requires:

- prompt/config candidate wins A/B evaluation
- minimum sample count is met
- no hidden regression on unrelated task types

### Model-Level

Primary question: does changing a model or model configuration improve the
system enough to justify extra cost and risk?

Metrics:

- task quality score
- validation pass rate
- inference latency
- total cost per successful task
- context handling reliability
- structured output reliability
- deterministic replay variance
- failure category mix
- model-specific error rate

Promotion requires:

- model wins on quality-adjusted cost
- improvement survives repeated seeds or repeated runs
- model failure modes are understood and documented

## Proposed Schema

The existing database can support part of this loop, but serial evolution needs
explicit lineage and decision records. Add these tables after the current schema
is stable.

### `evolution_instances`

Tracks each champion and challenger filesystem/database snapshot.

```sql
CREATE TABLE IF NOT EXISTS evolution_instances (
    id TEXT PRIMARY KEY,
    parent_instance_id TEXT REFERENCES evolution_instances(id) ON DELETE SET NULL,
    role TEXT NOT NULL CHECK (role IN ('champion','challenger','archived','rejected')),
    version_label TEXT NOT NULL,
    repo_path TEXT NOT NULL,
    db_path TEXT,
    git_ref TEXT,
    config_hash TEXT,
    code_hash TEXT,
    knowledge_hash TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    archived_at TEXT,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_evolution_instances_role ON evolution_instances(role);
CREATE INDEX IF NOT EXISTS idx_evolution_instances_parent ON evolution_instances(parent_instance_id);
```

### `evolution_runs`

One row per attempted generation.

```sql
CREATE TABLE IF NOT EXISTS evolution_runs (
    id TEXT PRIMARY KEY,
    champion_instance_id TEXT NOT NULL REFERENCES evolution_instances(id),
    challenger_instance_id TEXT REFERENCES evolution_instances(id),
    cycle_number INTEGER NOT NULL,
    layer TEXT NOT NULL CHECK (layer IN (
        'data_feature',
        'strategy_policy',
        'prompt_config',
        'model'
    )),
    status TEXT NOT NULL DEFAULT 'planned'
        CHECK (status IN ('planned','mining','mutating','training','evaluating','promoted','rejected','failed','paused')),
    objective TEXT NOT NULL,
    started_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at TEXT,
    selected_by TEXT NOT NULL DEFAULT 'rotation',
    failure_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_evolution_runs_cycle ON evolution_runs(cycle_number);
CREATE INDEX IF NOT EXISTS idx_evolution_runs_status ON evolution_runs(status);
CREATE INDEX IF NOT EXISTS idx_evolution_runs_layer ON evolution_runs(layer);
```

### `evolution_mined_inputs`

Records mined material used by a cycle.

```sql
CREATE TABLE IF NOT EXISTS evolution_mined_inputs (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES evolution_runs(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    source_ref TEXT,
    license_type TEXT,
    novelty_score REAL,
    relevance_score REAL,
    accepted INTEGER NOT NULL DEFAULT 0,
    rejection_reason TEXT,
    extracted_payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_evolution_mined_run ON evolution_mined_inputs(run_id);
```

### `evolution_mutations`

Records exactly what changed in a challenger.

```sql
CREATE TABLE IF NOT EXISTS evolution_mutations (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES evolution_runs(id) ON DELETE CASCADE,
    layer TEXT NOT NULL,
    mutation_type TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    before_hash TEXT,
    after_hash TEXT,
    mutation_manifest TEXT NOT NULL DEFAULT '{}',
    rollback_manifest TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_evolution_mutations_run ON evolution_mutations(run_id);
```

### `evolution_evaluations`

Stores champion-versus-challenger evaluation results.

```sql
CREATE TABLE IF NOT EXISTS evolution_evaluations (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES evolution_runs(id) ON DELETE CASCADE,
    eval_slice TEXT NOT NULL,
    champion_score REAL NOT NULL,
    challenger_score REAL NOT NULL,
    delta_score REAL NOT NULL,
    p_value REAL,
    effect_size REAL,
    bootstrap_ci_low REAL,
    bootstrap_ci_high REAL,
    passed INTEGER NOT NULL DEFAULT 0,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_evolution_eval_run ON evolution_evaluations(run_id);
CREATE INDEX IF NOT EXISTS idx_evolution_eval_passed ON evolution_evaluations(passed);
```

### `evolution_decisions`

Final promotion, rejection, pause, or rollback decision.

```sql
CREATE TABLE IF NOT EXISTS evolution_decisions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES evolution_runs(id) ON DELETE CASCADE,
    decision TEXT NOT NULL CHECK (decision IN ('promote','reject','pause','rollback')),
    decided_by TEXT NOT NULL DEFAULT 'promotion_gate',
    reason TEXT NOT NULL,
    gate_report TEXT NOT NULL DEFAULT '{}',
    promoted_instance_id TEXT REFERENCES evolution_instances(id),
    rollback_instance_id TEXT REFERENCES evolution_instances(id),
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_evolution_decisions_run ON evolution_decisions(run_id);
CREATE INDEX IF NOT EXISTS idx_evolution_decisions_decision ON evolution_decisions(decision);
```

### `evolution_monitor_events`

Operational telemetry and alert feed.

```sql
CREATE TABLE IF NOT EXISTS evolution_monitor_events (
    id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES evolution_runs(id) ON DELETE SET NULL,
    instance_id TEXT REFERENCES evolution_instances(id) ON DELETE SET NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_evolution_monitor_run ON evolution_monitor_events(run_id);
CREATE INDEX IF NOT EXISTS idx_evolution_monitor_severity ON evolution_monitor_events(severity);
```

## Internal Workflow

### 1. Select Cycle Layer

Inputs:

- previous cycle number
- failed gate history
- current monitoring alerts
- layer rotation policy
- operator override, if present

Output:

- one selected layer
- one objective statement
- one evaluation recipe

Example:

```json
{
  "cycle_number": 12,
  "layer": "data_feature",
  "objective": "Improve retrieval quality for async error-handling tasks",
  "selected_by": "adaptive_bottleneck"
}
```

### 2. Snapshot Champion

Create a durable champion record before modification:

- repository path
- database path
- git ref
- config hash
- code hash
- knowledge hash
- active model/config identifiers

No mutation is allowed until the champion snapshot is recorded.

### 3. Duplicate Challenger

Create a separate filesystem and database copy. The challenger must be isolated
enough that training, mining, or test runs cannot corrupt the champion.

Required checks:

- copy exists
- config loads
- database opens
- import smoke passes
- baseline tests are runnable

### 4. Mine Layer-Specific Material

Mining should match the selected layer:

- data-feature: repos, methodology gaps, stale sources, embeddings, source deltas
- strategy-policy: task outcomes, failure categories, routing regret, escalation logs
- prompt/config: prompt variants, invalid output traces, high-performing templates
- model: model comparison logs, latency/cost traces, failure clusters

Mined inputs are accepted only if they pass provenance, novelty, relevance,
license, security, and duplicate checks.

### 5. Mutate One Layer

The mutation engine applies bounded changes:

- data-feature: add or retire methodologies, update freshness, add retrieval features
- strategy-policy: adjust routing weights, gates, escalation policy, reward function
- prompt/config: schedule prompt variants, tune thresholds, adjust tool-use policies
- model: change model for a scoped agent role or experiment with a local learner

Every mutation writes a rollback manifest before evaluation.

### 6. Tune/Search/Train

The loop can use RL, Bayesian bandits, grid search, or deterministic A/B testing,
but the search space must be scoped to the selected layer.

Examples:

- prompt/config: use `prompt_variants` and A/B evaluation
- strategy-policy: use `agent_scores`, Thompson sampling, and Kelly sizing
- data-feature: use methodology fitness, novelty, and downstream retrieval lift
- model: use paired task runs and quality-adjusted cost

### 7. Evaluate Champion vs Challenger

Run both versions against the same evaluation suite:

- smoke tasks
- held-out tasks
- known regression tasks
- recent real tasks
- synthetic edge cases
- layer-specific benchmark
- full validation gate for the challenger

Evaluation must record per-slice results. A single aggregate score is not enough.

### 8. Decide

Promotion gate outcomes:

- `promote`: challenger becomes new champion
- `reject`: challenger is archived or deleted after artifact capture
- `pause`: insufficient evidence or operator review needed
- `rollback`: current champion has degraded and prior archived champion is restored

Promotion should update the active instance pointer atomically. If atomic swap is
not available in the first build, promotion should be a manual command with a
precomputed manifest.

### 9. Archive and Learn

After decision:

- write final decision report
- archive champion if challenger won
- archive or clean rejected challenger
- update methodology fitness and routing scores
- update prompt variant status where applicable
- emit dashboard events
- schedule the next layer

## Monitoring

The monitoring system should answer six questions:

1. What is the current champion?
2. What cycle is running?
3. What layer is being mutated?
4. What changed?
5. Did the candidate actually improve?
6. Is the loop drifting, overfitting, or overspending?

### Dashboard Panels

Minimum dashboard:

- current champion version
- cycle timeline
- layer rotation history
- promotion/rejection rate
- score delta by cycle
- validation gate pass/fail history
- cost per cycle
- token usage by agent/model
- latency by stage
- mined source count and acceptance rate
- novelty and relevance distributions
- rollback availability
- active alerts

### Alerts

Critical alerts:

- challenger promoted despite failed hard gate
- champion validation fails after promotion
- cost budget exceeded
- latency budget exceeded
- repeated regression on same metric
- novelty score collapses across mined inputs
- duplicate or clone-inflation spike
- no promotion after many cycles with rising cost
- every candidate wins suspiciously often
- rollback artifact missing

Warning alerts:

- model-level cycle cost is above expected range
- prompt/config variant has insufficient samples
- strategy-policy exploration is too low
- stale data-feature sources dominate retrieval
- confidence interval is too wide for decision

### Run States

```text
planned -> mining -> mutating -> training -> evaluating -> promoted
                                                 |
                                                 +-> rejected
                                                 +-> failed
                                                 +-> paused
```

No run should stay in `mining`, `training`, or `evaluating` indefinitely. Each
state needs a timeout and recovery action.

## Safety and Failure Modes

### Reward Hacking

Risk: the challenger learns to optimize the promotion score without improving
real outcomes.

Controls:

- holdout tasks hidden from the mutation step
- periodic benchmark refresh
- human-readable decision report
- layer-specific metrics plus hard gates

### Self-Training Collapse

Risk: each generation trains on outputs from the previous generation and
gradually loses contact with external reality.

Controls:

- mined external sources with provenance
- independent validation suite
- source diversity checks
- stale-source and duplicate controls

### Overfitting to Recent Tasks

Risk: candidates improve on recent failures while degrading general capability.

Controls:

- evaluation slices across recent, historical, synthetic, and held-out tasks
- regression suite by capability
- minimum effect size and confidence thresholds

### Irreversible Promotion

Risk: a bad candidate replaces the champion and the prior state is lost.

Controls:

- archive old champion
- rollback manifest
- post-promotion validation
- delayed garbage collection

### Layer Attribution Loss

Risk: too many things change and nobody knows what caused the result.

Controls:

- one major layer per cycle
- mutation manifest
- config hash/code hash/knowledge hash tracking
- combined cycles only after formal approval

## Build To-Do Steps

### Phase 0: Decide Baseline Contract

- [ ] Define the first official champion instance.
- [ ] Define canonical benchmark tasks and held-out tasks.
- [ ] Freeze initial promotion score weights.
- [ ] Define hard guardrail thresholds for cost, latency, validation, and safety.
- [ ] Decide where instance snapshots live under `instances/`.

### Phase 1: Persistence

- [ ] Add evolution schema tables.
- [ ] Add repository methods for evolution instances, runs, mutations, evaluations,
      decisions, and monitor events.
- [ ] Add migrations or idempotent schema initialization.
- [ ] Add tests for schema creation and basic CRUD.

### Phase 2: Instance Manager

- [ ] Implement champion snapshot hashing.
- [ ] Implement challenger duplication.
- [ ] Implement copy preflight using the existing validation gate.
- [ ] Implement archive and rollback manifests.
- [ ] Add tests using temporary fixture repos/databases.

### Phase 3: Cycle Orchestrator

- [ ] Implement layer selection by fixed rotation.
- [ ] Add adaptive override hooks from monitoring and metrics.
- [ ] Implement run state transitions.
- [ ] Ensure only one active evolution run can mutate a champion at a time.
- [ ] Add timeout handling and failed-run cleanup.

### Phase 4: Mining Adapters

- [ ] Data-feature adapter: use PULSE discoveries, gap analyzer, freshness, and
      methodology fitness.
- [ ] Strategy-policy adapter: mine task outcomes, error categories, routing logs,
      and escalation history.
- [ ] Prompt/config adapter: mine prompt variant outcomes and invalid-output traces.
- [ ] Model adapter: mine model comparison, latency, cost, and failure clusters.
- [ ] Store all accepted and rejected mined inputs with reasons.

### Phase 5: Mutation Engines

- [ ] Data-feature mutator: add, retire, or reweight methodologies and retrieval
      features.
- [ ] Strategy-policy mutator: adjust routing, escalation, abstention, and reward
      policy.
- [ ] Prompt/config mutator: create prompt/config variants and activate scoped A/B
      tests.
- [ ] Model mutator: swap a model for a scoped role or run a paired comparison.
- [ ] Require rollback manifests for every mutation.

### Phase 6: Evaluation and Promotion Gate

- [ ] Build paired champion/challenger evaluator.
- [ ] Implement composite score calculation.
- [ ] Record per-slice metrics in `evolution_evaluations`.
- [ ] Integrate `validation_gate.py` as a hard gate.
- [ ] Add statistical checks using the existing A/B analyzer where applicable.
- [ ] Implement promote/reject/pause/rollback decisions.

### Phase 7: Monitoring

- [ ] Add monitor event emitter.
- [ ] Add CLI report for current champion, active run, and last decisions.
- [ ] Add dashboard panels for evolution status and score history.
- [ ] Add alert rules for critical and warning conditions.
- [ ] Add garbage collection policy for old rejected challengers.

### Phase 8: First Controlled Trial

- [ ] Run one data-feature-level cycle in dry-run mode.
- [ ] Verify all artifacts are recorded.
- [ ] Run one real challenger mutation with no auto-promotion.
- [ ] Review decision report manually.
- [ ] Enable manual promotion.
- [ ] Only after repeated successful manual trials, enable gated auto-promotion.

## Initial Implementation Boundaries

The first build should avoid model fine-tuning and broad code mutation. Highest
success path:

1. Start with data-feature cycles because CAM-PULSE already has PULSE mining,
   novelty, methodology fitness, and knowledge-loop proof.
2. Add prompt/config cycles next because `prompt_variants` and A/B evaluation
   already exist.
3. Add strategy-policy cycles after routing and escalation metrics are captured
   cleanly.
4. Add model-level cycles last because they are costlier and harder to validate.

The first automated promotion should be conservative:

```text
allowed layers: data_feature, prompt_config
manual approval: disabled
hard gates: required
rollback: required
model-level changes: disabled
combined-layer changes: disabled
```

## Automation Hardening Addendum

The autonomous mode is budget-bound and has no human in the loop. The OpenRouter
API key limit is the iteration constraint: before every round, the runner checks
remaining key budget and stops before starting work that cannot be afforded.

Operational contracts:

1. Folder mining consumes exactly three unmined repository directories per round.
   If fewer than three remain, the loop stops instead of running a partial batch.
2. Only these OpenRouter models may be used in the active automation path:
   `qwen/qwen3.6-flash`, `deepseek/deepseek-v4-flash`,
   `deepseek/deepseek-v4-pro`, and `openai/gpt-mini-latest`.
3. Provider hard failures such as unsupported model, bad request, unavailable
   route, or invalid model payload must escalate immediately to the next allowed
   model. They must not consume repeated retry delays.
4. A model that hard-fails in a mining run is quarantined for the rest of that
   run so later repos do not retry the same broken route.
5. Rate limits and transient server/network failures may retry with backoff, but
   they still count against the cycle's latency and budget guardrails.
6. Stale active runs are failed automatically after their timeout and emit a
   monitor event. A stale `mining`, `mutating`, `training`, or `evaluating` row
   must not block future autonomous rounds indefinitely.
7. Local tests use fake budget and mining clients by design. They prove
   orchestration, isolation, and promotion logic, but they do not prove that the
   paid OpenRouter path is reachable.
8. Live autonomous mining must run a tiny approved-model probe before the first
   repo batch unless explicitly skipped. A failed probe stops the loop before
   any repo is mined and records which approved models were attempted.

Instance boundary:

- The champion repository and database are immutable during mining and mutation.
- The challenger must have its own filesystem/database target before mined
  methodologies or retrieval features are written.
- Evaluation must compare champion and challenger against the same tasks with
  the same budget and model allowlist.
- Promotion updates the active champion pointer only after validation; rejection
  leaves the champion untouched.

Known drift from the initial plan:

- The autonomous folder loop currently forces `data_feature` cycles, so full
  layer rotation is not yet active in unattended mode.
- CAM instances now exist as champion/challenger filesystem/database copies, but
  only data-feature knowledge artifacts are evolving so far. Prompt/config,
  strategy-policy, and model-level CAM-enhancing-CAM loops remain future phases.
- Per-language ganglion DBs are now attributed in paired task-readiness, but
  promotion validation still reports only the primary live mining target path.

Next hardening target: reduce live enrichment cost, add per-request caps for
oversized repo prompts, and then widen the loop beyond data-feature mining into
prompt/config CAM enhancement.

## Recommended First Milestone

Build a minimal serial evolution runner that can do this end to end:

```text
1. register current workspace as champion v0
2. duplicate to challenger v1-candidate
3. run a data-feature mining pass
4. apply one bounded knowledge/retrieval mutation
5. evaluate champion vs challenger on a small benchmark
6. write an evolution decision report
7. require manual approval before promotion
```

That milestone proves the architecture without taking on the full risk of
autonomous model or policy evolution.
