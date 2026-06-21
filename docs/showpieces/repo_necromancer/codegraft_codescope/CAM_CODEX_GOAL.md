# CAM_Codx Repo Necromancer Goal

Build a working merged product from two source repos:

- Source A: `/Volumes/WS4TB/WS4TBr/codegraft`
- Source B: `/Volumes/WS4TB/WS4TBr/codescope`

Product name: **CodeGraftScope**

Promise:

> CodeGraftScope turns workspace inventory plus code-grafting logic into a local subsystem transplant desk: find reusable modules, preflight the target, and produce a patch plan before copying code.

## Required behavior

1. Keep both source repos read-only.
2. Create a new output repo or app directory.
3. Reuse source ideas only with provenance notes.
4. Implement a runnable MVP with CLI help, README, and at least one smoke test.
5. Include a merge ledger that maps each new subsystem to Source A, Source B, or new glue code.
6. Run tests and record results before claiming completion.

## Initial MVP features

- Read-only source repo profiler with git state receipts.
- Compatibility map showing which source repo contributes each subsystem.
- Safe merge plan with target files, tests to add, and rollback notes.
- Runnable demo app that explains the revived product in one command.
- Codex-ready goal brief for turning the packet into a real merged repo.

## Acceptance

- `python -m pytest -q` or the app's equivalent smoke test passes.
- README explains what was revived from each source repo.
- No source repo files are modified.
- The final report includes exact source paths and git heads.
