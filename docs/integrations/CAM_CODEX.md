# CAM_Codx Integration

CAM_CAM is the runtime engine. CAM_Codx is the Codex-native workflow hub:

```text
https://github.com/deesatzed/CAM_Codx
```

Use CAM_Codx when a Codex session should consume CAM outputs, continue from a
generated `CAM_CODEX_GOAL.md`, or harden a standalone generated product repo.

## Repo Necromancer Handoff

Repo Necromancer lives in CAM_CAM and writes packet artifacts such as:

- `CAM_CODEX_GOAL.md`
- `NECROMANCER_SHOWPIECE.md`
- `evidence.json`
- optional `fused_app/` demo files

The tested standalone command shape is:

```bash
python scripts/repo_necromancer.py \
  --repo-a /path/to/source-a \
  --repo-b /path/to/source-b \
  --out-dir docs/showpieces/repo_necromancer/my_pair \
  --product-name MyProduct \
  --standalone-repo /path/to/MyProduct \
  --merger-brief "Build a small, inspectable CLI first; show what was borrowed, why, and what is safe to touch next."
```

Use `--merger-brief-file /path/to/brief.md` for longer product expectations.
The brief is embedded in the packet and generated standalone repo so CAM_Codx
does not have to infer the desired outcome from source profiles alone.

## Boundary Rules

- Source repos are read-only evidence unless a goal explicitly allows edits.
- Packet demos are not standalone product completion.
- A generated product repo needs runtime code, tests, README, provenance docs,
  and a smoke command.
- CAM_Codx should record changed files and verification output before claiming
  completion.

## CAM_Codx Docs To Read

- `docs/WORKFLOW_REPO_NECROMANCER.md`
- `templates/goals/repo-necromancer-standalone.md`
- `docs/examples/MORIAH_CAREFRAME_CASE_STUDY.md`
