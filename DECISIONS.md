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
