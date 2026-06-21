# MyLoc Repo Necromancer Showpiece

MyLoc is the current dogfood proof for Repo Necromancer: CAM generated a
standalone product repo, then CAM used its own evaluation, planning, mining, and
security checks to harden that generated output.

## Product

- Name: `MyLoc`
- Local repo: `/Volumes/CAMADA/CAM_ALL/repos/MyLoc`
- Role: local subsystem transplant desk
- Promise: find reusable modules, preflight a target, and produce a patch plan
  before copying code.

## CAM Evidence

| CAM function | MyLoc result |
|---|---|
| `evaluate --mode structural` | Python repo, README, tests, `pyproject.toml`, expectation score `1.000`. |
| `preflight` | Low complexity, medium confidence, `proceed_now`. |
| `camify` | Generated `docs/camify_myloc_plan.md` and `.json` with 10 KB matches. |
| `mine-self --quick` | Classified as `cli_ux` with secondary `ai_integration`, `testing`, and `algorithm`. |
| `security scan` | `CLEAN - 0 findings`. |

## Hardened Output

MyLoc now has:

- `my_loc/boundary.py` for source-receipt drift checks,
- `python -m my_loc.cli plan --json` for machine-readable merge plans,
- `python -m my_loc.cli verify-boundaries` for read-only source proof,
- patch-plan contract validation in `my_loc/planner.py`,
- a repo-local showpiece at `docs/MYLOC_SHOWPIECE.md`.

## Why It Belongs In CAM_CAM

CAM_CAM owns the Repo Necromancer generator and CAM runtime checks. MyLoc proves
that the generator output is not just a packet; it can become a standalone repo
that CAM can inspect, improve, and verify again.
