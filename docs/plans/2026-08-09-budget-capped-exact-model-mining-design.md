# Budget-Capped Exact-Model Mining Design

## Status

Approved by the operator on 2026-08-09 for a new `$7.00` maximum mining run.
No paid mining request may be sent until this design is implemented and its
focused verification passes.

## Problem

`cam mine-workspace` currently reports repository cost only after mining, while
`RepoMiningResult.cost_usd` is zero on the production mining path. It therefore
cannot enforce a run-wide authorization. The selected profile also maps roles
onto agent slots; the recovery selector can still escalate from the selected
Grok 4.5 model to GPT-4.1-mini or Grok 4.3. A `$7 maximum` run must neither
overspend nor silently use an unbenchmarked fallback.

## Chosen approach

Add an opt-in, fail-closed mining budget controller and exact-model override to
`mine-workspace`:

```text
--max-cost-usd 7
--exact-model x-ai/grok-4.5
--budget-receipt data/mining_runs/<run>.json
```

The three options form one safety contract. A paid budgeted run refuses to
start unless all are present, the model exists in a live OpenRouter catalog,
the receipt can be created or safely resumed, and the requested budget/model
match the receipt.

## Request boundary

The controller sits at the OpenRouter HTTP-attempt boundary, not merely around
each repository. Before every POST it:

1. verifies the payload model equals the authorized exact model;
2. computes a conservative input bound from the UTF-8 bytes of the serialized
   messages plus JSON overhead;
3. combines that bound with `max_tokens`, frozen catalog pricing, reasoning
   pricing, per-request pricing, and long-context overrides;
4. atomically persists a `submitted` attempt receipt reserving that maximum;
5. refuses the POST when actual spend plus all unresolved reserves plus the new
   reserve would exceed the authorization.

The request also sends OpenRouter provider routing controls with
`allow_fallbacks=false`, `require_parameters=true`, price sorting, and
`max_price` equal to the frozen accepted prompt/completion prices.

After a completed response, provider-reported `usage.cost` replaces the
attempt reserve and the returned model is validated. A missing cost or an
ambiguous transport/provider failure retains the full reserve. Retry attempts
must obtain and persist their own reserve, so a timeout cannot create hidden
unaccounted spend.

## Runtime routing

For this invocation only, every enabled non-local mining agent slot is set to
the exact model and the LLM fallback chain is cleared. The persisted
`model_profiles.toml` remains the operator-selected profile; the exact override
is visible in the run receipt and does not rewrite the registry.

Budget exhaustion is a typed terminal condition. Miner recovery code re-raises
it immediately, and workspace mining stops before the next request rather than
treating it as an ordinary model failure or moving to another repository.

## Evidence and resume

The mode-600 JSON receipt contains:

- authorization and remaining conservative budget;
- exact model and frozen catalog/model digests;
- per-attempt repository context, maximum reserve, provider cost, request ID,
  returned model, status, and error classification;
- cumulative actual and conservative spend;
- terminal state: running, completed, budget-exhausted, or failed.

Receipt writes are atomic. Resuming with the same path reconstructs spend from
completed and unresolved attempts. Changing the budget, model, or frozen model
entry is rejected before any paid call.

## Mining behavior

- Pin `/Volumes/WS4TB/repo622sn/CAM_CAM/claw.db` through both DB environment
  variables and the absolute live config.
- Mine only ledger-eligible new/changed repositories.
- Preserve yield sorting so the highest-value repositories run first.
- Use `--no-tasks`; the authorization covers methodology mining only.
- Run one request at a time.
- Stop successfully with an explicit budget-exhausted receipt when the next
  conservative request does not fit. A `$7` cap does not guarantee all 48
  eligible repositories will fit.

## Alternatives rejected

1. **Manual one-repository batches:** rejected because post-hoc usage checks
   cannot bound a timeout, retry, or the final in-flight request.
2. **Rely only on the existing OpenRouter key limit:** rejected because the
   current key has a `$19` lifetime limit and more than `$7` remaining.
3. **Create a temporary provider-limited key:** useful defense in depth, but it
   requires a management credential or dashboard action that is not present in
   the approved local environment. The local controller must still work safely
   without it.

## Verification

Tests must prove red then green for:

- missing or partial budget CLI options fail before client execution;
- exact-model override removes all alternate mining models and fallback;
- an attempt is durably reserved before the HTTP POST;
- actual provider cost reconciles a completed reserve;
- missing cost and ambiguous failure retain the reserve;
- retry attempts reserve independently;
- a request that cannot fit never reaches the HTTP client;
- budget exhaustion propagates through recovery and stops the workspace loop;
- receipt resume rejects model/budget/catalog drift and never loses prior
  conservative spend;
- no-budget legacy mining behavior remains unchanged.

Focused model, LLM, miner, CLI, and recovery suites plus `git diff --check`
must pass before the first paid run.
