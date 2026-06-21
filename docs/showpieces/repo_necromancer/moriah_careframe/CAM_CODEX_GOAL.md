# CAM_Codx Repo Necromancer Goal

Build a working merged product from two source repos:

- Source A: `/Volumes/WS4TB/WS4TBr/MORIAH/moriah_omega`
- Source B: `/Volumes/WS4TB/careframe/Proto_Dev_Req`

Product name: **MoriahCareFrame**

Promise:

> MoriahCareFrame turns workspace inventory plus code-grafting logic into a local subsystem transplant desk: find reusable modules, preflight the target, and produce a patch plan before copying code.

## Standalone repo requirement

The task is incomplete unless this exact directory exists and contains its own
runtime code, tests, README, provenance docs, and smoke command:

`/Volumes/WS4TB/WS4TBr/MoriahCareFrame`

Do not count `docs/showpieces/repo_necromancer/.../fused_app` as the output
repo. That directory is only the packet demo.


## Required behavior

1. Keep both source repos read-only.
2. Create a new standalone output repo or app directory outside the packet.
3. Reuse source ideas only with provenance notes.
4. Implement a runnable MVP with CLI help, README, and at least one smoke test.
5. Include a merge ledger that maps each new subsystem to Source A, Source B, or new glue code.
6. Run tests and record results before claiming completion.
7. Do not mark the goal complete by only updating the packet directory.

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
- If a standalone repo path is named above, that path exists and contains runtime code.
