# CAM_CAM <- CAM-Pulse Assimilation Guide - 2026-05-05

## Purpose

Use CAM itself to evaluate, ingest, and assimilate the useful capabilities from:

- Source sibling: `/Volumes/WS4TB/CCam/CAM-Pulse`
- Target champion: `/Volumes/WS4TB/CCam/CAM_CAM`

The intended result is not a wholesale copy. CAM_CAM must remain the surviving
instance because it contains the budget-bound serial evolution loop. CAM-Pulse
is the source of defense-chain improvements that should be mined, matched,
ported, verified, and then learned back into CAM_CAM.

## Non-Negotiable Preservation Rules

CAM must preserve these CAM_CAM capabilities:

- Budget-bound serial evolution loop in `src/claw/evolution/serial.py`
- Champion/challenger isolation semantics
- Exact-batch mining and promotion gates
- Budget-specific model and embedding settings in `claw.toml`
- Checkpoint intent in `docs/CAM_PULSE_SERIAL_EVOLUTION_CHECKPOINT_2026-05-05.md`

CAM must not blindly overwrite these files from CAM-Pulse:

- `claw.toml`
- `README.md`
- `docs/index.html`
- `src/claw/evolution/serial.py`
- `src/claw/miner.py`
- `src/claw/evolution/assimilation.py`
- `src/claw/db/repository.py`
- `src/claw/db/schema.sql`

Those files may be edited only through narrow, test-backed patches.

## Primary Assimilation Targets

| ID | Capability to ingest | Source evidence in CAM-Pulse | Target area in CAM_CAM | Why it matters | Acceptance checks |
|---|---|---|---|---|---|
| A1 | Deterministic auto-fix engine | `/Volumes/WS4TB/CCam/CAM-Pulse/src/claw/memory/auto_fix.py`; `/Volumes/WS4TB/CCam/CAM-Pulse/tests/test_auto_fix.py` | Add `src/claw/memory/auto_fix.py`; add tests | Fix shallow model bugs before spending LLM correction attempts | `PYTHONPATH=src python -m pytest tests/test_auto_fix.py -q` |
| A2 | Auto-fix integration in MicroClaw | `/Volumes/WS4TB/CCam/CAM-Pulse/src/claw/cycle.py` around `build_default_engine`, proactive auto-fix, re-verify | `src/claw/cycle.py` | Makes auto-fix part of act -> verify -> correction loop | `PYTHONPATH=src python -m pytest tests/test_cycle.py -q` |
| A3 | Correction feedback hints | `/Volumes/WS4TB/CCam/CAM-Pulse/src/claw/agents/interface.py` `known_fix_hint` and `auto_fixes_applied` prompt sections | `src/claw/agents/interface.py`; `src/claw/core/models.py` | Lets agents use prior successful fixes and know which deterministic fixes already ran | `PYTHONPATH=src python -m pytest tests/test_failure_learning.py -q` |
| A4 | Failure knowledge table and repository methods | `/Volumes/WS4TB/CCam/CAM-Pulse/src/claw/db/repository.py`; `/Volumes/WS4TB/CCam/CAM-Pulse/src/claw/db/schema.sql`; `/Volumes/WS4TB/CCam/CAM-Pulse/tests/test_failure_knowledge.py` | `src/claw/db/repository.py`; `src/claw/db/schema.sql`; `src/claw/db/engine.py` | Stores unresolved recurring failures as preventive knowledge | `PYTHONPATH=src python -m pytest tests/test_failure_knowledge.py -q` |
| A5 | Agent rotation using excluded agents | `/Volumes/WS4TB/CCam/CAM-Pulse/src/claw/dispatcher.py`; `/Volumes/WS4TB/CCam/CAM-Pulse/src/claw/cycle.py`; `/Volumes/WS4TB/CCam/CAM-Pulse/tests/test_dispatcher.py` | `src/claw/dispatcher.py`; `src/claw/cycle.py`; `src/claw/core/models.py` | Prevents repeated failed attempts by the same agent/model | `PYTHONPATH=src python -m pytest tests/test_dispatcher.py tests/test_cycle.py -q` |
| A6 | RL escalation retry loop | `/Volumes/WS4TB/CCam/CAM-Pulse/src/claw/evolution/rl_escalation.py`; cycle integration in `src/claw/cycle.py` | `src/claw/evolution/rl_escalation.py`; `src/claw/cycle.py` | Converts exhausted correction attempts into rotate/decompose/human-review decisions | `PYTHONPATH=src python -m pytest tests/test_failure_learning.py tests/test_cycle.py -q` |
| A7 | Verifier hardening for model artifacts and test detection | `/Volumes/WS4TB/CCam/CAM-Pulse/src/claw/verifier.py`; `/Volumes/WS4TB/CCam/CAM-Pulse/tests/test_verifier.py` | `src/claw/verifier.py` | Rejects leaked FIM tokens, detects pytest tests even without pyproject, scores environment failures correctly | `PYTHONPATH=src python -m pytest tests/test_verifier.py -q` |
| A8 | Structured file-operation token stripping | `/Volumes/WS4TB/CCam/CAM-Pulse/src/claw/cycle.py` `_strip_llm_tokens` and `_apply_structured_file_operations` | `src/claw/cycle.py` | Prevents generated source files from containing model control tokens | `PYTHONPATH=src python -m pytest tests/test_cycle.py -q` |
| A9 | Workspace resolution fallback chain | `/Volumes/WS4TB/CCam/CAM-Pulse/src/claw/cycle.py` `_resolve_workspace_dir`; `/Volumes/WS4TB/CCam/CAM-Pulse/tests/test_cycle.py` | `src/claw/cycle.py` | Ensures verification runs against the task or project repo even if the agent lacks `workspace_dir` | `PYTHONPATH=src python -m pytest tests/test_cycle.py -q` |
| A10 | Auto-fix rule suggestion mining | `/Volumes/WS4TB/CCam/CAM-Pulse/src/claw/evolution/pattern_learner.py` `generate_auto_fix_rule_suggestions` | `src/claw/evolution/pattern_learner.py` | Turns repeated correction successes into proposed deterministic fix rules | Add/port targeted test or verify through `tests/test_failure_learning.py` |
| A11 | Defense proof harness | `/Volumes/WS4TB/CCam/CAM-Pulse/scripts/retest_rotation.py` | `scripts/retest_rotation.py` | Provides an executable proof that rotation/failure knowledge works | `PYTHONPATH=src python scripts/retest_rotation.py --help` or dry-run equivalent |
| A12 | Defense-chain documentation | CAM-Pulse `README.md` and `docs/index.html` defense-chain sections | New or updated CAM_CAM docs only | Documents the merged system without overwriting serial-evolution docs | Docs diff reviewed manually |

## Already Partially Assimilated In CAM_CAM

These pieces are already present or partly present in CAM_CAM and must be
checked for consistency before CAM attempts deeper edits:

- `src/claw/db/repository.py` includes `excluded_agents` persistence and `failure_knowledge` methods.
- `src/claw/db/schema.sql` includes `tasks.excluded_agents` and `failure_knowledge`.
- `src/claw/evolution/rl_escalation.py` includes escalation actions and excluded agent state.
- `src/claw/core/config.py` includes `orchestrator.auto_fix_enabled`.
- `src/claw/core/models.py` now includes `Task.excluded_agents`.
- `src/claw/core/models.py` now includes `CorrectionFeedback.known_fix_hint` and `auto_fixes_applied`.
- `src/claw/db/engine.py` now includes guarded migrations for `excluded_agents` and `failure_knowledge`.

CAM should prefer detecting and filling missing integration points over copying
whole files.

## Merge Status - 2026-05-06

The defense-chain merge was performed as a gap-fill into CAM_CAM, not as a
wholesale replacement from CAM-Pulse.

| ID | Status | Notes |
|---|---|---|
| A1 | Merged | Ported `src/claw/memory/auto_fix.py` and `tests/test_auto_fix.py`. |
| A2 | Merged | Wired proactive and reactive deterministic auto-fix into `MicroClaw._act_with_correction`. |
| A3 | Merged | Correction feedback now carries `known_fix_hint` and `auto_fixes_applied`; agent prompt support was already present in CAM_CAM-compatible interfaces. |
| A4 | Merged | CAM_CAM already had repository methods; guarded migrations and tests were added/verified. |
| A5 | Merged | Dispatcher now respects `Task.excluded_agents`; `MicroClaw.learn` persists rotation exclusions. |
| A6 | Merged | RL escalation now rotates on import/API/async/connection/test/syntax failures and `run_cycle` retries rotated tasks. |
| A7 | Merged | Verifier now runs tests even with prior violations, detects leaked LLM special tokens, detects pytest-only repos, and treats environment setup as a functional failure. |
| A8 | Merged | Structured file operations strip leaked model control tokens before writing/appending content. |
| A9 | Merged | Verification and correction now resolve workspace from agent, task, then project context. |
| A10 | Merged | `PatternLearner.generate_auto_fix_rule_suggestions` suggests deterministic rule candidates from repeated correction successes. |
| A11 | Merged | Ported `scripts/retest_rotation.py` proof harness. |
| A12 | Merged | This status section documents the transferred behavior without overwriting CAM_CAM serial-evolution docs. |

Verification run:

```bash
PYTHONPATH=src python -m pytest \
  tests/test_auto_fix.py \
  tests/test_failure_learning.py \
  tests/test_failure_knowledge.py \
  tests/test_verifier.py \
  tests/test_planner.py \
  tests/test_camify.py \
  tests/test_config.py \
  tests/test_dispatcher.py \
  tests/test_cycle.py -q
```

Result: `309 passed, 1 skipped`.

## Expected CAM Behavior During The Trial

CAM should be asked to do three things in order:

1. Mine CAM-Pulse as a source of methodologies relevant to CAM_CAM defense-chain enhancement.
2. Generate a CAM-ify plan for CAM_CAM using this guide as the domain guide.
3. Produce or execute narrow enhancement tasks only for the accepted assimilation targets above.

The first trial should be dry-run/planning-first. Do not let CAM modify broad
areas until we inspect its generated tasks.

## Trial Commands

Run from `/Volumes/WS4TB/CCam/CAM_CAM`:

```bash
PYTHONPATH=src python -m claw.cli camify /Volumes/WS4TB/CCam/CAM_CAM \
  --guide /Volumes/WS4TB/CCam/CAM_CAM/docs/CAM_CAM_PULSE_ASSIMILATION_GUIDE_2026-05-05.md \
  --goal "assimilate CAM-Pulse defense-chain capabilities into CAM_CAM while preserving budget-bound serial evolution" \
  --goal "identify missing auto-fix, failure-knowledge, verifier-hardening, and agent-rotation integration points" \
  --output /Volumes/WS4TB/CCam/CAM_CAM/docs/CAM_CAM_PULSE_CAMIFY_PLAN_2026-05-05.md \
  --config /Volumes/WS4TB/CCam/CAM_CAM/claw.toml
```

If the plan is relevant, mine CAM-Pulse into CAM_CAM's knowledge base:

```bash
PYTHONPATH=src python -m claw.cli mine /Volumes/WS4TB/CCam/CAM-Pulse \
  --target /Volumes/WS4TB/CCam/CAM_CAM \
  --max-repos 1 \
  --depth 5 \
  --max-minutes 30 \
  --config /Volumes/WS4TB/CCam/CAM_CAM/claw.toml
```

Then run a dry enhancement pass:

```bash
PYTHONPATH=src python -m claw.cli enhance /Volumes/WS4TB/CCam/CAM_CAM \
  --battery \
  --dry-run \
  --verbose \
  --config /Volumes/WS4TB/CCam/CAM_CAM/claw.toml
```

## How To Judge Whether CAM Succeeded

CAM succeeds at the assimilation planning stage if it identifies at least these
six capability groups:

- deterministic auto-fix
- correction feedback hints
- failure knowledge storage/retrieval
- agent rotation via excluded agents
- verifier hardening
- proof tests/harnesses

CAM fails or needs improvement if its generated plan:

- recommends overwriting CAM_CAM from CAM-Pulse wholesale
- ignores `src/claw/memory/auto_fix.py`
- ignores `failure_knowledge`
- ignores `excluded_agents`
- ignores tests from CAM-Pulse
- suggests changing `claw.toml` without preserving CAM_CAM budget constraints
- treats README/docs branding as more important than defense-chain behavior

## If CAM Misses A Target

Use the miss as feedback to improve CAM itself:

| Miss | What it means | CAM improvement to make |
|---|---|---|
| Does not identify `auto_fix.py` | Diff-aware feature discovery is weak | Add a source-file novelty detector for new modules with dense tests |
| Does not link tests to features | Test-to-capability attribution is weak | Teach CAM to pair source files with same-named tests during mining |
| Suggests config overwrite | Preservation constraints are not respected | Add "protected target invariants" to CAM-ify planning |
| Ignores partial existing implementation | Merge planning is too copy-oriented | Add "gap-fill mode" comparing source/target capability surfaces |
| Misses `excluded_agents` routing | Cross-file behavior tracing is weak | Improve graph extraction from model -> repository -> dispatcher -> cycle |
| Misses verifier changes | Behavioral diff extraction is weak | Add diff classifiers for validation/quality gate changes |

## Final Promotion Gates

The merger is not done until these pass in CAM_CAM:

```bash
PYTHONPATH=src python -m pytest tests/test_auto_fix.py -q
PYTHONPATH=src python -m pytest tests/test_failure_learning.py tests/test_failure_knowledge.py -q
PYTHONPATH=src python -m pytest tests/test_dispatcher.py tests/test_cycle.py tests/test_verifier.py -q
PYTHONPATH=src python -m pytest -q
```

If the full suite still has unrelated known failures, record them separately and
do not count them as defense-chain assimilation failures unless they touch the
files in this guide.
