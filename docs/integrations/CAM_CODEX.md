# CAM_Codx Integration

CAM_CAM is the runtime engine. CAM_Codx is the normal Codex-native control
plane:

```text
https://github.com/deesatzed/CAM_Codx
```

Use CAM_Codx for normal SWE, mining, knowledge, model, self-enhancement,
evolution, setup, and evidence workflows. Direct CAM_CAM commands are for
runtime troubleshooting, development, recovery, and regression isolation.

The approved 2026-08-12 target is now implemented and release-audited for
Tasks 1-13 as one `cam-codx` skill. The current evidence, limitations, and
unrelated baseline failures are recorded in the CAM_Codx release audit. This
does not claim a live MatrAIx/SESA product slice; that work is separately
governed by `CAM_Codx/GOAL_TASK_14_MATRAIX_SESA.md` after its target and product
boundaries are accepted.

## Development Brief Handoff

Use CAM_Codx's `cam-codx-development-brief` skill before implementation when a
developer needs to shape a new project from prior work, or decide whether an
in-progress project should **continue**, be **mitigated**, or be
**re-developed**.

CAM_Codx inspects the named target and turns the results into a concise brief.
CAM_CAM supplies only the raw, provenance-bearing primary-corpus hits through:

```bash
cam brief-query "durable import retry" --db /absolute/path/to/claw.db --json
```

The command opens the supplied SQLite database in read-only immutable mode. It
does not initialize schema, write retrieval telemetry, load embeddings, query
federated siblings, mine repositories, call a provider, run target tests, or
edit code. CAM_Codx labels resulting advice as a **direct precedent**,
**transferable analogy**, or **new hypothesis** rather than treating every hit
as proven reuse.

Additional repository roots are never implicit. CAM_Codx can render a later,
scan-only proposal only after the operator names an approved parent and the
relocation gate passes. See
[CAM Development Brief](https://github.com/deesatzed/CAM_Codx/blob/main/docs/CAM_DEVELOPMENT_BRIEF.md)
for the full workflow and boundaries.

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
