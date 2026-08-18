# Goal: Sparse, Evidence-Backed CAM Knowledge Graph

> Status (2026-08-18): the sparse graph contract, health report, bounded query,
> review-first resolver, CAM_Codx route, and fixture gates are implemented and
> published. This is fixture/isolated proof; it does not claim high-precision
> live-corpus ingestion or production accuracy. The bounded live-import seam
> is separately governed by `GOAL_LIVE_IMPORT.md`.

This is a successor build contract. It derives from the graph audit of
`/Volumes/WS4TB/KGraph.md`: CAM_CAM currently has hybrid vector/FTS retrieval,
methodology association links, and a separate repository inventory graph. It
does **not** yet have the high-precision entity/relationship graph described
there. This goal makes that gap explicit and closes it in bounded phases.

Current implementation ownership:

- CAM_CAM owns graph extraction, persistence, retrieval, evidence, and graph
  health measurement.
- CAM_Codx owns the normal outcome-facing packet and must invoke CAM_CAM; it
  must not duplicate CAM_CAM graph, retrieval, or provider logic.
- Work from the consolidated canonical checkouts only:
  `/Volumes/WS4TB/waswiki/CAM_CAM` and
  `/Volumes/WS4TB/waswiki/CAM_Codx`. The Downloads worktrees are recovery
  references, not a second runtime or state location.

/goal

OUTCOME: Build a sparse, high-precision, evidence-backed CAM knowledge graph
that augments—not replaces—hybrid vector/FTS retrieval. It must let CAM_Codx
request a small, provenance-cited, degree-capped subgraph for a planning or
impact question without treating co-retrieval association as factual evidence.

PROOF OF DONE:

1. A versioned graph contract defines stable canonical node IDs, node types,
   directed edge types, source revision, extraction method, confidence,
   validity/lifecycle, timestamps, and immutable evidence receipt references.
   It distinguishes explicit facts, high-confidence inferences, and
   association-only signals.
2. CAM_CAM ingests a deterministic fixture corpus containing source files,
   documentation, tests, and methodology/outcome records. Structured signals
   (AST/import/test/reference where supported) create explicit relationships;
   text-only extraction cannot silently create factual edges.
3. Entity resolution uses blocking, aggressive within-block similarity, and a
   review-required ambiguity path. Every merge/split has confidence,
   provenance, and a reproducible decision record. A model is optional and is
   never called for fixture proof or more than the configured ambiguous budget.
4. Existing `co_retrieval` edges remain available as labelled association
   signals, but are excluded from factual impact paths by default. Existing
   `contradicts`, `competes_with`, `feeds_into`, and related links are migrated
   or mapped only where their evidence semantics can be stated truthfully.
5. The graph query API returns a minimal seed subgraph by default: maximum two
   hops, typed-edge filtering, relevance-plus-degree ranking, configurable hub
   fan-out cap, deterministic ordering, and a token/size budget. Expansion is
   explicit. A blast-radius query returns only relevant callers/importers/tests
   or an honest unsupported result.
6. Every returned node and edge includes source provenance; every inferred edge
   includes confidence and its basis. Failed, stale, unresolved, synthetic, or
   association-only evidence cannot be presented as verified factual context.
7. A graph-health report measures node count, edge count, average degree, hub
   dominance, edge-type mix, unresolved entity candidates, query subgraph size,
   and retrieval token estimate. It records before/after fixture metrics and
   rejects graph growth that violates configured sparsity budgets.
8. CAM_Codx has one fixed list-form, read-only manager packet for the supported
   graph-question route. Normal UX says `Use CAM_Codx to assess the impact of
   ...`; direct CAM_CAM graph commands remain runtime/troubleshooting surfaces.
9. RED-then-GREEN unit, integration, provenance, regression, and CLI/packet
   tests pass. Focused and applicable full suites run; caused regressions are
   repaired and unrelated baselines are recorded exactly. `git diff --check`
   passes in both repositories.
10. `GOAL.md`, `IMPLEMENT.md`, `DECISIONS.md`, `PROGRESS.md`, documentation,
    and an honest fixture-proof report record the final behavior, limitations,
    commands, metrics, and commits. Fixture proof is never described as live
    accuracy or production acceptance.

SCOPE:

- CAM_CAM: graph contract, schema/migration only if proven necessary, graph
  repository/query service, structured extractors, entity-resolution ledger,
  CLI, tests, fixtures, health report, and runtime/troubleshooting docs.
- CAM_Codx: registry entry, manager packet, outcome-facing documentation, and
  integration tests required for the read-only graph-question route.
- Reuse existing methodology records, source receipts, lifecycle/fitness data,
  and hybrid retrieval as candidate selection signals where their semantics are
  preserved.
- Do not modify live `claw.db`, configurations, model profiles, provider
  settings, deployed services, or unrelated target repositories.

CONSTRAINTS:

- Read `GOAL.md`, `STANDARDS.md`, `IMPLEMENT.md`, `DECISIONS.md`,
  `PROGRESS.md`, and `TASK_QUEUE.md` when present before each repository phase.
- Begin every behavior change with a failing regression test. Do not delete,
  weaken, skip, or relabel tests for a green result.
- Prefer explicit code/document relations over NLP; no edge exists merely from
  co-occurrence, proximity, embedding similarity, or repeated retrieval.
- Use stable IDs, exact list-form subprocess argv, existing wrappers, and no
  shell execution paths. Do not add provider clients, broad dependencies,
  duplicate runtime logic, public API breaks, or a schema migration without a
  documented necessity and rollback plan.
- Preserve backward compatibility for existing methodology links. Unknown
  legacy evidence must be labelled as association/legacy, not upgraded.
- Keep graph output compact and machine-readable; never dump a whole corpus or
  unbounded neighborhood into an agent prompt.

SAFETY / PROVENANCE:

- Resolve and display the exact checkout, configuration, database identity,
  target/repository revision, and source receipt before any mutation or paid
  operation. This goal is read-only against targets and uses fixtures by
  default.
- Hash and parse each source receipt from one captured byte buffer. Preserve
  license/source metadata for reused materials.
- Fail closed on missing/stale source identity, mutable revision labels,
  ambiguous entity identity, missing confidence/provenance, malformed graph
  records, secret-bearing input, or a request exceeding hop/fan-out/token
  limits.
- No live mining, provider call, model-based ambiguity resolution, production
  deployment, model/profile promotion, live CAM mutation, or destructive action
  without separate explicit authorization and bounds.

ITERATION:

1. Baseline and design: inventory all current graph-like data paths, classify
   each edge source as factual, inferred, association, or presentation-only,
   then write the versioned contract and migration/compatibility decision.
2. Build fixtures and tests first: create a small known code/document/outcome
   corpus with canonical entities, aliases, expected edges, rejected noisy
   edges, a hub, and multi-hop impact questions. Establish baseline metrics.
3. Implement the minimal persistence and extraction path for explicit evidence
   edges, then entity blocking/merge ledger. Add no model path until the local
   ambiguity budget and review semantics are proven.
4. Implement sparse query/traversal: two-hop default, typed filters, degree
   cap, relevance-plus-degree ordering, progressive expansion, and output
   budget. Ensure association edges are opt-in only.
5. Add health reporting and pruning/decay rules. Exercise graph updates with
   changed fixture source revisions and prove stale edges lose eligibility.
6. Add the CAM_CAM CLI and CAM_Codx manager packet only after the service is
   proven locally. Validate fixed argv, registry routing, read-only identity,
   and outcome-first help/documentation.
7. Run focused then full release gates, inspect diffs, update truth documents,
   commit each repository separately, and record exact receipts and remaining
   limitations in `PROGRESS.md` after every batch.

STOP:

Pause and report the exact blocker only if a required source is unavailable;
license/privacy/ownership is uncertain; a schema change cannot be safely
migrated and rolled back; an external model/provider or live operation requires
authorization that is absent; required verification has no safe local/fixture
alternative; or the same blocker persists after three distinct documented
repair strategies. Do not stop for ordinary RED tests, review findings, or
repairable baseline failures.

COMPLETE:

Mark complete only when every proof item is supported by current command output
and inspected artifacts; graph facts and associations are visibly distinct;
fixture metrics show bounded sparse retrieval; CAM_Codx can request the
read-only graph context through its registry; relevant suites and diff checks
pass or exact unrelated baselines are recorded; owning-repository commits are
present; and all user-facing documentation accurately states the graph's
limitations and evidence status.
