# Repo Necromancer: CodeGraftScope

CodeGraftScope turns workspace inventory plus code-grafting logic into a local subsystem transplant desk: find reusable modules, preflight the target, and produce a patch plan before copying code.

## Why this is a social-media-worthy CAM_Codx demo

- It starts with two existing repos instead of a blank prompt.
- It extracts purpose, signals, git state, entrypoints, and test posture from both.
- It produces a runnable fused-app packet plus a Codex-ready build goal.
- It keeps source repos read-only and records provenance.

## Source repos

### codegraft

- Path: `/Volumes/WS4TB/WS4TBr/codegraft`
- Summary: Improve your Python codebase by grafting valuable code from external sources.
- Signals: dashboard, graft, knowledge, workspace
- Languages: Markdown=1, Python=1
- Tests found: False
- Git: branch `main`, head `39fcf40`, dirty `True`

### codescope

- Path: `/Volumes/WS4TB/WS4TBr/codescope`
- Summary: No README summary found.
- Signals: dashboard, graft, knowledge, safety, workspace
- Languages: Markdown=1, Python=20, TOML=1
- Tests found: True
- Git: branch `main`, head `565d8e4`, dirty `False`

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
