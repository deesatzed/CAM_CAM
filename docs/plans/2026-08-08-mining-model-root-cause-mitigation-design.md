# Mining-model root-cause mitigation design

Date: 2026-08-08

## Context and approval

The first live model comparison completed 24 calls but did not produce a
selection-grade ranking. Controlled A/B diagnostics showed that CAM's request
and scoring behavior caused most failures: the benchmark forced a JSON object
while the prompt required an array, model reasoning defaults consumed the
completion allowance, the prompt asked for more detailed findings than the
allowance could hold, repaired partial output was accepted by production, and
one imprecise symbol citation could hard-fail an otherwise grounded response.

The user approved mitigation after reviewing those findings. This design keeps
the active model profile and all `claw.db` files unchanged.

## Considered approaches

### 1. Patch only the benchmark harness

Remove the conflicting response format and increase benchmark token limits.
This is the smallest change, but production mining would still accept partial
responses, inherit costly reasoning defaults, and trust unverified symbols.

### 2. Align the benchmark and production mining contract

Use the same portable JSON instruction in both paths, explicitly control
reasoning, reduce requested finding count, reject incomplete responses, validate
symbols locally, and score novelty against an explicitly pinned read-only
corpus. This directly addresses every confirmed controllable cause without a
database migration. This is the selected approach.

### 3. Replace mining with a two-pass extraction pipeline

First ask a model for terse candidates, then run a second model/local pass for
provenance and execution detail. This could improve reliability, but roughly
doubles orchestration complexity and paid calls. It is deferred until the
single-pass contract is measured correctly.

## Design

### Request contract

Mining prompts will request a portable `{"findings": [...]}` JSON envelope and
3-5 high-value findings. CAM will not silently add a transport-level
`json_object` constraint in the benchmark when production does not use it.
Strict provider JSON Schema can be evaluated later after compatibility is
measured across the selected model set.

`LLMClient` and the queued-batch client will support explicit `reasoning` and
`seed` request fields. The model catalog will preserve reasoning capabilities
and choose the least expensive supported analysis effort (`minimal`, then
`low`) for benchmark calls. Synchronous and batch calls will both receive the
frozen seed when supported. Production mining will use a configurable low
reasoning effort and exclude reasoning text from the returned answer.

Internal reasoning must never be substituted for an absent final answer. A
null final answer remains empty and therefore triggers mining recovery.

### Completion and recovery gate

Only a complete JSON array, complete `findings` wrapper, or complete single
legacy finding may become stored findings. `finish_reason=length`, malformed
JSON repaired from fragments, and prose-only responses are incomplete. They
are recorded as unsuccessful and proceed through the existing escalation,
content-reduction, and chunk-recovery ladder.

### Provenance

Model-supplied source files remain mandatory and must resolve inside the
fixture/repository. Model-supplied symbols are advisory. Before storage, CAM
will compare them with locally extracted AST/SCIP symbols, discard imprecise
labels, retain validated symbols, and backfill locally grounded symbols.

Benchmark scoring will continue to penalize invalid symbol precision, but it
will reserve hard failure for missing, escaping, or nonexistent source files.

### Corpus-backed comparison

Benchmark reports must receive an explicit read-only `claw.db` path. Existing
mined titles will be loaded without WAL or sidecar writes and supplied to the
novelty scorer. Repaired/truncated/unsupported envelopes receive zero reported
quality even if a few partial findings can be extracted, preventing misleading
high rankings.

### Safety and observability

- No benchmark or test path writes to `claw.db`.
- No active model profile is changed automatically.
- Existing raw benchmark artifacts remain ignored and local.
- A paid validation rerun occurs only after focused and broad tests pass and
  the remaining approved budget can cover the newly frozen plan.

## Verification

Regression tests will prove:

1. benchmark calls no longer force `json_object`;
2. catalog reasoning metadata becomes a frozen low/minimal request;
3. seed and reasoning reach synchronous and batch transports;
4. null content never becomes reasoning prose;
5. truncated or repaired mining output cannot be stored as success;
6. invalid model symbols are dropped and locally backfilled;
7. prompt fixtures request 3-5 findings in a findings wrapper;
8. report novelty uses titles loaded from an explicit immutable corpus; and
9. hard-failed partial calls report zero quality.

Focused benchmark, LLM, miner, config, and CLI tests run first. The broader
CAM_CAM suite and `git diff --check` are the final local gates.
