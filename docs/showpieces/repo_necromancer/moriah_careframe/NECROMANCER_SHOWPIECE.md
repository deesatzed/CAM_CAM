# Repo Necromancer: MoriahCareFrame

MoriahCareFrame turns workspace inventory plus code-grafting logic into a local subsystem transplant desk: find reusable modules, preflight the target, and produce a patch plan before copying code.

## Why this is a social-media-worthy CAM_Codx demo

- It starts with two existing repos instead of a blank prompt.
- It extracts purpose, signals, git state, entrypoints, and test posture from both.
- It produces a runnable fused-app packet plus a Codex-ready build goal.
- It keeps source repos read-only and records provenance.

## Source repos

### moriah_omega

- Path: `/Volumes/WS4TB/WS4TBr/MORIAH/moriah_omega`
- Summary: No README summary found.
- Signals: clinical, dashboard, graft, knowledge, safety, workspace
- Languages: JSON=2, JavaScript=7, Markdown=22, Python=15, YAML=1
- Tests found: False
- Git repo: `False`
- Branch: `not available`
- Head: `not available`
- Remote: `not available`
- Dirty: `False`
- Status receipt:

```text
clean or unavailable
```

### Proto_Dev_Req

- Path: `/Volumes/WS4TB/careframe/Proto_Dev_Req`
- Summary: No README summary found.
- Signals: clinical, dashboard, graft, safety, workspace
- Languages: JavaScript=12, Markdown=1
- Tests found: False
- Git repo: `True`
- Branch: `main`
- Head: `194fc54`
- Remote: `https://github.com/deesatzed/careframe.git`
- Dirty: `True`
- Status receipt:

```text
M ../docs/qa/mobile-visual/report.json
?? ../HANDOFF_2026-06-20.md
?? ../HANDOFF_LATEST.md
?? ../instances/
```

## Merge ledger

| Subsystem | Source | Provenance | Revived as |
|---|---|---|---|
| Workspace inventory and repo signal profiler | Source A / moriah_omega | path=/Volumes/WS4TB/WS4TBr/MORIAH/moriah_omega<br>signals=clinical, dashboard, graft, knowledge, safety, workspace<br>git_head=not available | A read-only scanner that turns source trees into evidence JSON before any graft. |
| Care-oriented preflight and rollback framing | Source B / Proto_Dev_Req | path=/Volumes/WS4TB/careframe/Proto_Dev_Req<br>signals=clinical, dashboard, graft, safety, workspace<br>git_head=194fc54 | A target-safety review that names warnings, required checks, and rollback steps. |
| Transplant desk glue | New glue / MoriahCareFrame | generated_by=CAM_CAM scripts/repo_necromancer.py<br>inputs=read-only source profiles | A merged CLI/report packet that explains what to borrow before copying code. |

## Safe merge plan

| Phase | Target files | Tests to add | Rollback | Risk |
|---|---|---|---|---|
| 1. Freeze source receipts | `docs/source_receipts.md`<br>`evidence/source_profiles.json` | `tests/test_source_receipts.py` | Delete generated receipts; no source repo rollback needed because inputs are read-only. | Low. Fails only if source paths disappear or git commands time out. |
| 2. Build transplant planner | `moriah_careframe/planner.py`<br>`moriah_careframe/cli.py` | `tests/test_planner.py`<br>`tests/test_cli_demo.py` | Revert planner and CLI files; keep receipts for audit continuity. | Medium. Planner must label weak matches instead of implying safe copyability. |
| 3. Add reviewable patch output | `patch_plan.md`<br>`patches/README.md` | `tests/test_patch_plan_contract.py` | Discard generated patch plan and rerun from unchanged receipts. | Medium. Human review is required before any file copy into a real target repo. |

## MVP feature sketch

- Read-only source repo profiler with git state receipts.
- Compatibility map showing which source repo contributes each subsystem.
- Safe merge plan with target files, tests to add, and rollback notes.
- Runnable demo app that explains the revived product in one command.
- Codex-ready goal brief for turning the packet into a real merged repo.

## Run the fused demo

```bash
python fused_app/repo_necromancer_demo.py --evidence evidence.json
open fused_app/index.html
```

## Verification

See `TEST_RESULTS.md` for the latest smoke, test, and read-only source receipts.
