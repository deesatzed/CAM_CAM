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
