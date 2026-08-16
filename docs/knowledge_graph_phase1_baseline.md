# Sparse Evidence Graph: Phase 1 Baseline

Date: 2026-08-16

This report is a local fixture-backed design baseline. It does not measure the
live CAM corpus, assert extraction accuracy, or change `claw.db`.

## Current Graph-Like Surfaces

| Existing surface | Current meaning | Phase 1 classification | Factual-path default |
| --- | --- | --- | --- |
| `methodology_links:co_retrieval` | Repeated retrieval/outcome association | association | excluded |
| `methodology_links:contradicts` | Embedding/text-derived contradiction heuristic | inferred | excluded until each edge has a receipt |
| `methodology_links:competes_with` | High-similarity niche-collision heuristic | inferred | excluded until each edge has a receipt |
| `feeds_into`, `enhances`, `synergy` | Assimilation-selected capability relationship | inferred | excluded until evidence semantics are attached |
| Repo Rescue Desk cluster/duplicate graph | Repository inventory/presentation topology | presentation-only | excluded |
| Hybrid vector/FTS retrieval | Candidate-document ranking | retrieval signal | not an edge source by itself |

The Phase 1 contract intentionally does not reinterpret legacy rows as facts.
Legacy edges may later be imported as `association` or upgraded only through a
receipt-backed re-extraction/review path.

## Contract Introduced

`claw.knowledge_graph.contract` defines:

- stable node IDs and allowed node types;
- directed typed edges with confidence and factual-path eligibility;
- immutable source URI, source revision, content SHA-256, and extraction method
  for every edge and entity-resolution decision;
- `explicit`, `inferred`, and `association` evidence classes; and
- deterministic Phase 1 graph-health metrics.

The contract is pure and has no database, filesystem mutation, provider,
embedding, extraction, or traversal side effect.

## Deterministic Fixture Baseline

The local fixture includes a Python source file, test, verified outcome,
methodology records, and one legacy `co_retrieval` edge. Its expected metrics
are:

| Metric | Value |
| --- | ---: |
| Nodes | 6 |
| Edges | 5 |
| Average degree | 1.667 |
| Hub dominance | 0.300 |
| Explicit / inferred / association edges | 4 / 0 / 1 |
| Unresolved entity decisions | 1 |

These are fixture baseline metrics only. They are not live-corpus accuracy,
entity-resolution quality, or a production graph-health claim.

## Deferred To Phase 2+

- Structured AST/import/test/outcome extractors and content hashes from actual
  source files. **The first local-fixture slice is now implemented:**
  `extract_evidence_graph` reads exact bytes and emits only explicit Python
  declaration, imported-test-call, and named-outcome edges; unsupported
  relationships are omitted rather than inferred.
- Entity blocking, similarity scoring, merge/split review ledger, and optional
  bounded model review.
- Persistent graph tables/migration decision and a backward-compatible legacy
  link importer.
- Degree-capped, two-hop retrieval, blast-radius queries, pruning, and
  CAM_Codx routing.
