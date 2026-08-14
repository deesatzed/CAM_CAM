# DECISIONS.md

## 2026-06-20: Repo Necromancer must support a standalone output repo

Decision: Repo Necromancer packets are not enough when the user asks for a new
repo. `scripts/repo_necromancer.py` now supports `--standalone-repo` so the
generator can create a real repo scaffold outside
`docs/showpieces/repo_necromancer/`.

Reason: The earlier packet-only interpretation caused repeated false
completion: the generated `fused_app/` demo was counted as the output app even
though the user expected `/Volumes/WS4TB/WS4TBr/MoriahCareFrame`. The corrected
contract requires runtime code, tests, README, provenance docs, and a smoke
command in the standalone repo path.

Safety: Source repos remain read-only evidence. The generator refuses to
overwrite a non-empty standalone repo path.

## Rejected pattern: cbe25ded-3ead-4d75-b1c8-13939f31a14f

Reason: The retrieved permission-lattice methodology was stale and too generic
to drive implementation. Its relevant principle, explicit read-only boundaries,
was covered by source receipts and generator behavior.

## Rejected pattern: 21a33670-268e-4e92-96a4-067680214d5b

Reason: Duplicate of the stale permission-lattice methodology.

## Rejected pattern: 6e01fcd4-4a72-41e0-baa0-bac233d91f96

Reason: Stale creation-mode result with lower fitness than the applied
creation-mode pattern.

## Rejected pattern: c05ecc45-74dd-4641-b7b2-d43773ad70a7

Reason: Creation-mode methodology for a different domain; not specific enough
for source-repo transplant planning.

## 2026-06-21: Carry merger guidance into Repo Necromancer packets

Decision: Repo Necromancer accepts `--merger-brief` and
`--merger-brief-file`, then embeds that guidance in packet evidence, showpiece
docs, the Codex goal, and generated standalone repo docs.

Reason: Source profiles can suggest a product direction, but the user often
knows the intended merger outcome and constraints. Carrying those expectations
inside the packet prevents the next Codex run from guessing, overbuilding, or
counting a packet-only artifact as the merged product.

Safety: The guidance is plain text and does not relax source read-only
boundaries, test requirements, provenance requirements, or standalone repo
acceptance checks.

## 2026-06-22: Add CAM-preMine before clone/mining

Decision: CAM_CAM now has a CLI-first `cam premine` workflow that inspects
public GitHub metadata remotely before the operator clones a candidate repo.

Reason: The operator often does not know whether a repo will add CAM value until
after cloning and mining it. A remote preMine gate reduces wasted clones and
makes license/safety scope explicit before candidate code enters the local
workspace.

UX: v1 returns a table by default and supports JSON, Markdown report output, and
JSONL candidate queue output. The verdict set is `CLONE_NOW`,
`CONDITIONAL_CLONE`, `REMOTE_HARVEST`, `RESTRICTED_REMOTE_HARVEST`,
`WATCHLIST`, `SKIP`, and `NEEDS_HUMAN`.

Safety: `cam premine` does not clone or execute candidate code. Dual-use
security/steganography signals route to restricted remote harvest with
defensive-only scope.

## 2026-08-08: Do not promote a mining model from partial benchmark evidence

Decision: keep the active model profile unchanged after the first live
comparison. Report Luna as the provisional budget leader and GLM 5.2 as the
cost/speed leader, but require a corrected-prompt validation round with zero
hard failures before either can be promoted.

Reason: all eight candidates completed their exact calls, but every candidate
had at least one truncated, malformed, or invalid-provenance result under the
current production prompt. High average scores do not override hard failures.

Safety: OpenRouter batch jobs use the provider's queued API and record its
30-day input/result retention. Rolling aliases may resolve only within the
same provider and model family. Benchmark execution never falls back, writes
to `claw.db`, or changes a model profile automatically.

## 2026-08-08: Authorize mining-model comparisons one stage at a time

Decision: replace the all-future-stages reserve with an adaptive tournament.
The first round compares every configured candidate. Only eligible models may
advance to held-out and repeat stages, and every later plan must fit the
original cumulative authorization after provider-reported prior spend.

Reason: the earlier planner reserved the most expensive possible top four and
top two before knowing which models were viable. That prevented a corrected
first round from running inside the remaining authorization even though later
spend could be selected safely from first-round evidence.

Selection: reports expose separate quality, budget, synchronous-speed, and
queued-batch candidates. They do not collapse different operator priorities
into one opaque winner. `cam models set` remains the only promotion boundary.

Safety: every stage freezes exact prompt and catalog digests, persists the
normalized catalog used for pricing, disables fallback, resumes completed
receipts without double charging, reads the novelty corpus immutably, and never
writes to `claw.db` or `model_profiles.toml`.

## 2026-08-08: Failed benchmark calls are evidence, not automatic retries

Decision: a normal resume never resubmits a call that already has either a
completed or failed receipt. Provider-reported failed-call cost counts toward
actual and cumulative spend. A failed call without a reconciled provider cost
retains its entire frozen maximum as a conservative reserve.

Reason: overwriting a failed receipt could both double charge a provider call
and understate the remaining budget. Queued batches are especially sensitive
because submission may succeed before polling times out.

Safety: batch submission and polling are separate operations. A `submitted`
receipt persists the job ID and 30-day retention fact before the first poll;
transient polling failures preserve that receipt and resume the same job rather
than POSTing a duplicate. Terminal provider failures remain non-retriable.
Exact planned call IDs, fixture hashes, catalog digests, and output-plan
identity are validated before execution or scoring. Repeat trials must copy
their root first-round call controls and are compared with that same
model/fixture call.

## 2026-08-08: Catalog authorization hashes must be process-independent

Decision: canonicalize set-valued model capabilities before computing both
entry and full-catalog digests, and test the same payload under multiple Python
hash seeds.

Reason: a normalized snapshot created in one process could fail validation in
another because `frozenset` iteration order is hash-seed dependent. The failure
was safe and pre-spend, but made valid frozen plans unusable.

Safety: catalog verification still rejects material entry or aggregate
tampering. Any plan whose legacy aggregate digest cannot validate is retained
only as rejected evidence; it is never repaired in place or executed.

## 2026-08-08: Score complete fenced JSON as production-compatible

Decision: distinguish complete fenced JSON objects/arrays from malformed or
repaired JSON. A complete supported payload inside a standard `json` code fence
is recorded as a fenced envelope and does not create a hard failure.

Reason: CAM's production `parse_findings` intentionally strips standard code
fences before JSON validation. Treating the same response as invalid in the
benchmark measured stricter formatting preference rather than actual mining
compatibility and incorrectly excluded otherwise grounded candidates.

Safety: incomplete fences, truncation, unsupported JSON shapes, secret-like
output, and missing/escaping provenance remain hard failures. The envelope type
stays visible in per-call evidence; no raw response or profile is rewritten.

## 2026-08-08: Model profiles affect mining only when explicitly supplied

Decision: `mine-workspace` accepts `--profiles PATH` and passes that registry
through live key validation and `ClawFactory.create`. The selected profile is
an explicit overlay on the pinned `claw.toml`; omitting the option retains the
legacy config models.

Reason: selecting a tournament winner must be able to change the subsequent
mining runtime, but silently auto-discovering a profile would weaken operator
control and make the effective model ambiguous.

Safety: the profile overlay does not change the database path, authorization,
or fallback policy beyond its declared roles. Promotion remains a separate,
receipt-backed `cam models set` action, and the tournament itself never writes
the profile.

## 2026-08-09: Changed-only scans must pin the live corpus environment

Decision: workspace scans that determine a paid mining batch must export both
`CLAW_DB_PATH` and `CAM_CODEX_MCP_DB_PATH` to the authoritative absolute
`claw.db` before running, even when an absolute `--config` is supplied.

Reason: the live config intentionally stores `db_path = "claw.db"`. The scan
ledger path is derived from the resolved database directory, so a command run
from an isolated worktree without the DB environment override consults a
worktree-local ledger and overstates the number of new repositories.

Safety: the authoritative scan is read-only, uses the live
`mining_registry.json`, and must precede every paid `--changed-only` run. The
2026-08-09 correction reduced the eligible set from the worktree-local 59 to
the live-ledger 48 without writing to the corpus.

## 2026-08-09: Paid workspace mining requires a persistent exact-model cap

Decision: a hard-capped `mine-workspace` run must provide
`--max-cost-usd`, `--exact-model`, and `--budget-receipt` together. Each LLM
HTTP attempt reserves its conservative maximum in the mode-`0600` receipt
before submission, provider-reported cost is reconciled afterward, and normal
model fallback and recovery cannot bypass a budget stop.

Reason: production mining previously reported zero aggregate cost and could
route recovery through models other than the selected profile. A chat-only
authorization was therefore not an enforceable spending boundary.

Safety: the live OpenRouter catalog entry is frozen into the receipt;
authorization, model, and catalog drift fail closed on resume. Returned-model
drift is charged once and rejected. The legacy CLI path is unchanged when the
three controls are omitted, scan-only never creates a receipt, and the existing
unbudgeted live LLM key probe is skipped for capped runs so the first paid
request is always reserved.

## 2026-08-09: A capped mining receipt is a single-writer terminal contract

Decision: hold an OS-level exclusive lock for the full controller lifetime,
serialize capped LLM requests, and prohibit new reservations or backward state
transitions after `completed`, `budget-exhausted`, or `failed`. A terminal run
requires a new receipt. Resume validates every persisted monetary value and
rejects non-finite, negative, or over-authorization state.

Reason: separate processes, concurrent assimilation calls, or poisoned
provider/accounting values could otherwise reserve from stale state, overwrite
attempts, or make cap comparisons fail open.

Safety: capped mining rejects remote embedding routes because those provider
charges are not represented in the LLM receipt. Every paid response must name
the returned model explicitly; missing or different model evidence is charged
once and fails terminally. Budget errors propagate through assimilation, and
the CLI releases the receipt lock on normal completion, early exit, timeout,
factory failure, and other exceptions.

## 2026-08-09: Route Swift repositories through the misc mining brain

Decision: include `.swift` in the repository language census and route the
language label `swift` to the existing `misc` brain.

Reason: Swift was already allowed by `mining.extra_code_extensions`, but it was
absent from `_EXT_TO_LANGUAGE`. Pure-Swift repositories were therefore rejected
as having no recognizable source files before serialization, while mixed repos
could hide the defect behind another recognized language.

Safety: this adds no model, prompt, database, or fallback path. A pure-Swift
regression test proves the existing `misc` path is selected. Paid verification
used the residual exposure from the already-approved `$7` batch, with
`x-ai/grok-4.5`, a fresh terminal receipt, and the authoritative database pinned.

## 2026-08-10: Tournament reports must prove parent-plan lineage

Decision: adaptive tournament advancement rejects a report unless its fixture
count and every quality receipt match the frozen parent plan's call IDs, model
IDs, and fixture IDs. Repeat-stage fixture identity comes from the root plan,
not a mutable suite ordering.

Reason: a hand-edited eligible summary or changed suite ordering could otherwise
advance a model without selection-grade evidence or compare repeat output to a
different first-round request.

Safety: this is a fail-closed validation change only. It does not change model
selection, provider routing, profile activation, or the live corpus.

## 2026-08-12: Treat Direct CAM_CAM Use As The Troubleshooting Surface

Decision: CAM_Codx is the normal user-facing control plane for every CAM_CAM
capability. Direct CAM_CAM commands remain supported for runtime
troubleshooting, development, recovery, regression isolation, and expert
scripts.

Reason: the runtime has a broad, useful command surface, but requiring normal
users to choose among low-level commands and overlapping Codex skills exposes
internal architecture instead of desired outcomes.

Safety: CAM_CAM retains runtime, provider, model, database, CAM-SEQ,
self-enhancement, and evolution ownership. The CAM_Codx manager does not grant
implicit mining, spend, promotion, swap, rollback, or code-mutation authority.

## 2026-08-14: Managed SWE runs reuse CAM-SEQ persistence

Decision: expose a persistence-only managed-run service over the existing
`task_plans`, `application_packets`, `pair_events`, `landing_events`,
`outcome_events`, `run_connectomes`, edges, and `run_events`. Candidate
decisions and mining-receipt links use typed `run_events` because no dedicated
table represents them. No parallel reuse database or schema migration is
introduced.

Reason: CAM_Codx needs one visible chain from mined source evidence through
selection, landing, verification, and later recall. The runtime already owns
the necessary evidence structures; a second store would create duplicate truth
and drift.

Safety: the hidden `managed-run` CLI accepts one JSON argument as a list-form
subprocess value and performs persistence only. It does not mine, call a
provider, edit a target, build, enhance, validate, promote, or change runtime
configuration. Only `verified_success` may add positive component evidence or
be recipe-eligible; partial, failed, and unverified outcomes remain neutral or
negative evidence. Corrections must explicitly supersede the latest outcome.
