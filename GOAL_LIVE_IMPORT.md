# Bounded Live-Import Adapter Contract

## Outcome

Provide a CAM_CAM runtime adapter that can assess and, only after a separate
bounded authorization, import a local evidence-graph source into an existing
CAM database. CAM_Codx remains the normal manager; this adapter is a runtime
seam and is not a second mining, provider, model, or retrieval implementation.

## Required proof

1. A request names an absolute source checkout, an exact 40-character Git
   revision, an existing database path, a snapshot ID, and positive file,
   byte, and time limits.
2. Preview verifies the source is a clean checkout at that revision, hashes a
   deterministic bounded file manifest, extracts only the existing explicit
   evidence-graph contract, and returns graph/content digests without opening
   the database.
3. A write requires an expiring authorization whose digest exactly matches the
   request. The operation ID is single-use within the process and is consumed
   before persistence. Changed source content, stale authorization, missing
   graph schema, and snapshot conflicts fail closed.
4. Persistence uses the existing transactional graph service. The adapter
   never initializes or migrates the target database, invokes a provider,
   loads a model, executes source code, or changes the legacy corpus.
5. Tests use temporary Git repositories and temporary databases only. Their
   results are fixture proof, not live-product accuracy or production
   acceptance.

## Scope and stop rules

- The source and target are local and explicitly named; no directory-wide
  discovery is permitted.
- The default operation is preview/read-only. A real database import requires
  a separate product approval naming the source, revision, target database,
  snapshot, limits, and rollback/retention plan.
- Do not run the adapter against the canonical `claw.db` in this development
  phase. Do not add a provider, embedding, model-selection, or automatic
  promotion path.
- Stop on missing ownership/license/privacy authority, a live mutation without
  approval, a source that is not a clean immutable checkout, or inability to
  establish bounded local proof.

## Success boundary

This contract is complete when focused tests, the existing graph gate, lint,
and diff checks pass; the adapter is committed and pushed; and a fixture-only
authorized import produces an immutable snapshot receipt. No live import is
claimed or executed by this goal.
