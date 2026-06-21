# Repo Necromancer User Guide

Repo Necromancer is a CAM_CAM showpiece workflow for turning two existing repos
into a concrete "revived product" brief.

It does not blindly copy files from one repo into another. It profiles two
source repos read-only, records evidence, proposes a merged product, creates a
runnable demo packet, and writes a `CAM_CODEX_GOAL.md` file that CAM_Codx can
use to perform the actual fusion build.

## What a User Gets

After running Repo Necromancer, the user gets:

- `NECROMANCER_SHOWPIECE.md`: the plain-English product story and source repo evidence.
- `CAM_CODEX_GOAL.md`: the build contract for CAM_Codx/Codex to execute next.
- `evidence.json`: machine-readable repo profiles and synthesis signals.
- `fused_app/README.md`: quick instructions for the generated demo.
- `fused_app/repo_necromancer_demo.py`: a runnable local demo.
- `fused_app/index.html`: a static browser page showing the revived product idea.

The important distinction is:

- CAM_CAM runs the profiler and creates the packet.
- CAM_Codx consumes the generated goal and builds the real merged app or repo.

## Why the Script Lives in CAM_CAM

The executable generator lives in `CAM_CAM` because `CAM_CAM` is the runnable
repo-analysis codebase. It can inspect local repos, collect git/file/test
signals, and write evidence-backed artifacts.

`CAM_Codx` is the companion execution/planning repo. The generated
`CAM_CODEX_GOAL.md` is intentionally formatted as a Codex-ready build packet so
a Codex session can take the evidence and implement the actual fused product.

This keeps the roles clean:

- `CAM_CAM`: discover, profile, explain, and package.
- `CAM_Codx`: execute the build goal created by the packet.

## How to Choose Two Repos

Pick two repos that create a useful product when combined, not just two repos
that happen to exist in the same folder.

Good pairs usually have:

- One repo with a valuable core idea, even if it is small, stale, or incomplete.
- One repo with complementary implementation strength, such as tests, UI,
  scanning, safety checks, search, or workflow glue.
- A shared problem domain or compatible vocabulary.
- Enough source material to infer a product promise from README text, file
  names, code, tests, and git state.
- A plausible user who would understand the merged result in one sentence.

Avoid pairs where:

- Both repos are empty shells.
- Neither repo has a README, tests, source files, or recognizable domain terms.
- The result would require secrets, private accounts, production deployment, or
  sensitive data.
- The only connection is a forced word association.

## The Pair Chosen for This Run

For the first run, we chose:

- Repo A: `/Volumes/WS4TB/WS4TBr/codegraft`
- Repo B: `/Volumes/WS4TB/WS4TBr/codescope`
- Product name: `CodeGraftScope`

Why this pair makes sense:

- `codegraft` has a direct code-reuse promise: graft valuable code from external sources.
- `codescope` has a larger Python footprint and test coverage.
- Both repos share workspace, grafting, knowledge, and dashboard-adjacent signals.
- The combined product is self-evident: a local subsystem transplant desk that
  finds reusable modules, checks the target repo, and produces a patch plan
  before any files are copied.

The resulting product promise is:

> CodeGraftScope turns workspace inventory plus code-grafting logic into a
> local subsystem transplant desk: find reusable modules, preflight the target,
> and produce a patch plan before copying code.

## Run the Generator

Run from the CAM_CAM repo root:

```bash
cd /Volumes/WS4TB/WS4TBr/CAM_Codx/CAM_CAM

python scripts/repo_necromancer.py \
  --repo-a /Volumes/WS4TB/WS4TBr/codegraft \
  --repo-b /Volumes/WS4TB/WS4TBr/codescope \
  --out-dir docs/showpieces/repo_necromancer/codegraft_codescope \
  --product-name CodeGraftScope
```

Expected output:

```text
Repo Necromancer created: CodeGraftScope
showpiece: docs/showpieces/repo_necromancer/codegraft_codescope/NECROMANCER_SHOWPIECE.md
codex_goal: docs/showpieces/repo_necromancer/codegraft_codescope/CAM_CODEX_GOAL.md
evidence: docs/showpieces/repo_necromancer/codegraft_codescope/evidence.json
app_readme: docs/showpieces/repo_necromancer/codegraft_codescope/fused_app/README.md
demo_py: docs/showpieces/repo_necromancer/codegraft_codescope/fused_app/repo_necromancer_demo.py
index_html: docs/showpieces/repo_necromancer/codegraft_codescope/fused_app/index.html
```

## Inspect the Generated Packet

Start with the showpiece:

```bash
sed -n '1,220p' docs/showpieces/repo_necromancer/codegraft_codescope/NECROMANCER_SHOWPIECE.md
```

Then inspect the Codex build goal:

```bash
sed -n '1,240p' docs/showpieces/repo_necromancer/codegraft_codescope/CAM_CODEX_GOAL.md
```

The goal file is the handoff artifact. It tells CAM_Codx/Codex:

- which two repos were analyzed,
- what product to build,
- which source repos must remain read-only,
- what MVP behaviors are required,
- what acceptance checks must pass,
- what provenance must be recorded.

## Run the Demo Packet

Run the generated demo:

```bash
python docs/showpieces/repo_necromancer/codegraft_codescope/fused_app/repo_necromancer_demo.py \
  --evidence docs/showpieces/repo_necromancer/codegraft_codescope/evidence.json
```

Open the static page:

```bash
open docs/showpieces/repo_necromancer/codegraft_codescope/fused_app/index.html
```

The demo proves that the generated packet is runnable and understandable. It is
not yet the final merged product.

## Hand the Goal to CAM_Codx

Use this file as the next execution target:

```text
/Volumes/WS4TB/WS4TBr/CAM_Codx/CAM_CAM/docs/showpieces/repo_necromancer/codegraft_codescope/CAM_CODEX_GOAL.md
```

In a Codex session rooted where you want the fused product built, tell Codex to
execute that goal file. If your Codex environment supports slash goals, use:

```text
/goal /Volumes/WS4TB/WS4TBr/CAM_Codx/CAM_CAM/docs/showpieces/repo_necromancer/codegraft_codescope/CAM_CODEX_GOAL.md
```

If slash goals are not available, open the file and paste its contents into the
Codex session as the build contract.

The CAM_Codx execution session should create a new output repo or app directory.
It should not mutate either source repo.

## Safety Rules

Repo Necromancer is designed to be read-only against source repos. The generated
goal repeats that rule because the actual fusion build should also treat source
repos as evidence, not as mutable working directories.

Before claiming the fused product is complete, the CAM_Codx execution session
must verify:

- source repos were not modified,
- the new output app or repo exists,
- the README explains what was revived from each source,
- tests or smoke checks pass,
- the final report includes source paths and git heads.

## Verification Commands

Validate the generator itself:

```bash
python -m pytest tests/test_repo_necromancer.py -q
```

Validate the generated demo:

```bash
python docs/showpieces/repo_necromancer/codegraft_codescope/fused_app/repo_necromancer_demo.py \
  --evidence docs/showpieces/repo_necromancer/codegraft_codescope/evidence.json
```

Check for whitespace issues before commit:

```bash
git diff --check
```

## Reusing the Workflow on Another Pair

Change only the two source repo paths, output directory, and product name:

```bash
python scripts/repo_necromancer.py \
  --repo-a /path/to/first/source-repo \
  --repo-b /path/to/second/source-repo \
  --out-dir docs/showpieces/repo_necromancer/my_new_pair \
  --product-name MyRevivedProduct
```

A strong second run should use the same standard:

- the merged product should be obvious in one sentence,
- the generated `CAM_CODEX_GOAL.md` should be specific enough to execute,
- the demo should run without API keys,
- source repos should stay read-only,
- evidence should be saved before any real fusion work begins.
