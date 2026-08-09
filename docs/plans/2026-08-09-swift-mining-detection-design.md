# Swift Mining Detection Design

## Problem

CAM accepts `.swift` through `mining.extra_code_extensions`, but repository
language detection counts only extensions present in `_EXT_TO_LANGUAGE`.
Because `.swift` is absent there, a pure-Swift repository reaches
`RepoMiner.mine_repo()` with no detected language zone and is rejected as
`No recognizable source files found` before serialization.

This was reproduced with `/Volumes/WS4TB/waswiki/zoomcam/ZoomitForMac`, which
contains 38 tracked Swift files and was skipped without making a paid model
call. Mixed repositories can hide the defect when another recognized language
causes a `misc` mining pass.

## Approved approach

Add Swift to the existing language census and route it to the existing `misc`
brain. Do not add a new brain, prompt, agent, database, or CLI control.

The minimal production change is:

- map `.swift` to the language label `swift` in `_EXT_TO_LANGUAGE`;
- map `swift` to the existing `misc` brain in `_LANGUAGE_TO_BRAIN`.

## Alternatives rejected

- Force `cam mine --brain misc`: the single-directory command does not expose
  the persistent aggregate budget receipt used by the approved workspace run.
- Add a marker file or temporary source copy: this would distort source
  provenance and leave the canonical changed-only ledger incomplete.
- Skip `ZoomitForMac`: this would leave a source-bearing approved repository
  unmined even though the defect is local and safely fixable.

## Verification and spending boundary

1. Add a pure-Swift regression fixture in `tests/test_miner_polyglot.py` and
   prove it fails before changing production code.
2. Apply only the two mapping entries and prove the focused test passes.
3. Run the existing polyglot test module and `git diff --check`.
4. Run a pinned scan-only command against `ZoomitForMac` and require one
   eligible `misc` repository.
5. Use a fresh terminal receipt capped at `$5.0998584`, the unused portion of
   the already-approved `$7` batch authorization. Combined authorization across
   the completed receipt and the follow-up receipt cannot exceed `$7`.
6. Pin `x-ai/grok-4.5`, the authoritative `claw.db`, explicit model profiles,
   `--no-tasks`, and changed-only behavior.

`ScreenSage` remains excluded because it contains plans and evidence but no
recognized source code.
