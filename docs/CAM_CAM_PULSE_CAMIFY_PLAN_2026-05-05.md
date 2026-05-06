---
camify_version: 1
target_repo: /Volumes/WS4TB/CCam/CAM_CAM
goals:
  - "assimilate CAM-Pulse defense-chain capabilities into CAM_CAM while preserving budget-bound serial evolution"
  - "identify missing auto-fix, failure-knowledge, verifier-hardening, and agent-rotation integration points"
guide_files:
  - docs/CAM_CAM_PULSE_ASSIMILATION_GUIDE_2026-05-05.md
  - README.md
source_repos:
  - /Volumes/WS4TB/CCam/CAM-Pulse
assimilation_targets:
  - A1: Deterministic auto-fix engine
  - A2: Auto-fix integration in MicroClaw
  - A3: Correction feedback hints
  - A4: Failure knowledge table and repository methods
  - A5: Agent rotation using excluded agents
  - A6: RL escalation retry loop
  - A7: Verifier hardening for model artifacts and test detection
  - A8: Structured file-operation token stripping
  - A9: Workspace resolution fallback chain
  - A10: Auto-fix rule suggestion mining
  - A11: Defense proof harness
  - A12: Defense-chain documentation
kb_matches_found: 10
kb_gaps:
  - knowledge
  - claw
  - tests
  - patterns
  - cam-pulse
created_at: "2026-05-05T22:08:55Z"
status: PENDING
---

# CAM-ify Plan: CAM_CAM

## Goals
1. assimilate CAM-Pulse defense-chain capabilities into CAM_CAM while preserving budget-bound serial evolution
2. identify missing auto-fix, failure-knowledge, verifier-hardening, and agent-rotation integration points

## KB Match Summary
- 10 relevant methodologies found
- Gaps: knowledge, claw, tests, patterns, cam-pulse

## Assimilation Targets

| ID | Capability | Source | Target | Acceptance |
|---|---|---|---|---|
| A1 | Deterministic auto-fix engine | /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/memory/auto_fix.py; /Volumes/WS4TB/CCam/CAM-Pulse/tests/test_auto_fix.py | Add src/claw/memory/auto_fix.py; add tests | PYTHONPATH=src python -m pytest tests/test_auto_fix.py -q |
| A2 | Auto-fix integration in MicroClaw | /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/cycle.py around build_default_engine, proactive auto-fix, re-verify | src/claw/cycle.py | PYTHONPATH=src python -m pytest tests/test_cycle.py -q |
| A3 | Correction feedback hints | /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/agents/interface.py known_fix_hint and auto_fixes_applied prompt sections | src/claw/agents/interface.py; src/claw/core/models.py | PYTHONPATH=src python -m pytest tests/test_failure_learning.py -q |
| A4 | Failure knowledge table and repository methods | /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/db/repository.py; /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/db/schema.sql; /Volumes/WS4TB/CCam/CAM-Pulse/tests/test_failure_knowledge.py | src/claw/db/repository.py; src/claw/db/schema.sql; src/claw/db/engine.py | PYTHONPATH=src python -m pytest tests/test_failure_knowledge.py -q |
| A5 | Agent rotation using excluded agents | /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/dispatcher.py; /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/cycle.py; /Volumes/WS4TB/CCam/CAM-Pulse/tests/test_dispatcher.py | src/claw/dispatcher.py; src/claw/cycle.py; src/claw/core/models.py | PYTHONPATH=src python -m pytest tests/test_dispatcher.py tests/test_cycle.py -q |
| A6 | RL escalation retry loop | /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/evolution/rl_escalation.py; cycle integration in src/claw/cycle.py | src/claw/evolution/rl_escalation.py; src/claw/cycle.py | PYTHONPATH=src python -m pytest tests/test_failure_learning.py tests/test_cycle.py -q |
| A7 | Verifier hardening for model artifacts and test detection | /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/verifier.py; /Volumes/WS4TB/CCam/CAM-Pulse/tests/test_verifier.py | src/claw/verifier.py | PYTHONPATH=src python -m pytest tests/test_verifier.py -q |
| A8 | Structured file-operation token stripping | /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/cycle.py _strip_llm_tokens and _apply_structured_file_operations | src/claw/cycle.py | PYTHONPATH=src python -m pytest tests/test_cycle.py -q |
| A9 | Workspace resolution fallback chain | /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/cycle.py _resolve_workspace_dir; /Volumes/WS4TB/CCam/CAM-Pulse/tests/test_cycle.py | src/claw/cycle.py | PYTHONPATH=src python -m pytest tests/test_cycle.py -q |
| A10 | Auto-fix rule suggestion mining | /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/evolution/pattern_learner.py generate_auto_fix_rule_suggestions | src/claw/evolution/pattern_learner.py | Add/port targeted test or verify through tests/test_failure_learning.py |
| A11 | Defense proof harness | /Volumes/WS4TB/CCam/CAM-Pulse/scripts/retest_rotation.py | scripts/retest_rotation.py | PYTHONPATH=src python scripts/retest_rotation.py --help or dry-run equivalent |
| A12 | Defense-chain documentation | CAM-Pulse README.md and docs/index.html defense-chain sections | New or updated CAM_CAM docs only | Docs diff reviewed manually |

## Step 1: Preflight
**Command**: `cam doctor environment`
**Purpose**: Verify CAM installation, API keys, and database health
**Verify**: Exit code 0, all checks green

## Step 2: Preflight
**Command**: `cam govern stats`
**Purpose**: Verify KB has methodologies to apply
**Verify**: Shows 95+ methodologies

## Step 3: Mine
**Command**: `cam mine /Volumes/WS4TB/CCam/CAM-Pulse --target /Volumes/WS4TB/CCam/CAM_CAM --max-repos 1 --depth 5 --max-minutes 30`
**Purpose**: Mine the source sibling named in the guide before enhancing the target champion
**Verify**: cam govern stats increases, and CAM records methodologies related to the guide's assimilation targets

## Step 4: Evaluate
**Command**: `cam enhance /Volumes/WS4TB/CCam/CAM_CAM --battery --dry-run --verbose`
**Purpose**: Generate a target-specific task plan and verify it mentions the guide's assimilation targets before code changes
**Verify**: Dry-run task list mentions auto-fix, failure knowledge, agent rotation, verifier hardening, or other A-targets

## Step 5: Enhance
**Command**: `cam enhance /Volumes/WS4TB/CCam/CAM_CAM --mode attended --max-tasks 1 --verbose`
**Purpose**: A1: Deterministic auto-fix engine. Source: /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/memory/auto_fix.py; /Volumes/WS4TB/CCam/CAM-Pulse/tests/test_auto_fix.py. Target: Add src/claw/memory/auto_fix.py; add tests. Reason: Fix shallow model bugs before spending LLM correction attempts
**Verify**: PYTHONPATH=src python -m pytest tests/test_auto_fix.py -q

## Step 6: Enhance
**Command**: `cam enhance /Volumes/WS4TB/CCam/CAM_CAM --mode attended --max-tasks 1 --verbose`
**Purpose**: A2: Auto-fix integration in MicroClaw. Source: /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/cycle.py around build_default_engine, proactive auto-fix, re-verify. Target: src/claw/cycle.py. Reason: Makes auto-fix part of act -> verify -> correction loop
**Verify**: PYTHONPATH=src python -m pytest tests/test_cycle.py -q

## Step 7: Enhance
**Command**: `cam enhance /Volumes/WS4TB/CCam/CAM_CAM --mode attended --max-tasks 1 --verbose`
**Purpose**: A3: Correction feedback hints. Source: /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/agents/interface.py known_fix_hint and auto_fixes_applied prompt sections. Target: src/claw/agents/interface.py; src/claw/core/models.py. Reason: Lets agents use prior successful fixes and know which deterministic fixes already ran
**Verify**: PYTHONPATH=src python -m pytest tests/test_failure_learning.py -q

## Step 8: Enhance
**Command**: `cam enhance /Volumes/WS4TB/CCam/CAM_CAM --mode attended --max-tasks 1 --verbose`
**Purpose**: A4: Failure knowledge table and repository methods. Source: /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/db/repository.py; /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/db/schema.sql; /Volumes/WS4TB/CCam/CAM-Pulse/tests/test_failure_knowledge.py. Target: src/claw/db/repository.py; src/claw/db/schema.sql; src/claw/db/engine.py. Reason: Stores unresolved recurring failures as preventive knowledge
**Verify**: PYTHONPATH=src python -m pytest tests/test_failure_knowledge.py -q

## Step 9: Enhance
**Command**: `cam enhance /Volumes/WS4TB/CCam/CAM_CAM --mode attended --max-tasks 1 --verbose`
**Purpose**: A5: Agent rotation using excluded agents. Source: /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/dispatcher.py; /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/cycle.py; /Volumes/WS4TB/CCam/CAM-Pulse/tests/test_dispatcher.py. Target: src/claw/dispatcher.py; src/claw/cycle.py; src/claw/core/models.py. Reason: Prevents repeated failed attempts by the same agent/model
**Verify**: PYTHONPATH=src python -m pytest tests/test_dispatcher.py tests/test_cycle.py -q

## Step 10: Enhance
**Command**: `cam enhance /Volumes/WS4TB/CCam/CAM_CAM --mode attended --max-tasks 1 --verbose`
**Purpose**: A6: RL escalation retry loop. Source: /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/evolution/rl_escalation.py; cycle integration in src/claw/cycle.py. Target: src/claw/evolution/rl_escalation.py; src/claw/cycle.py. Reason: Converts exhausted correction attempts into rotate/decompose/human-review decisions
**Verify**: PYTHONPATH=src python -m pytest tests/test_failure_learning.py tests/test_cycle.py -q

## Step 11: Enhance
**Command**: `cam enhance /Volumes/WS4TB/CCam/CAM_CAM --mode attended --max-tasks 1 --verbose`
**Purpose**: A7: Verifier hardening for model artifacts and test detection. Source: /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/verifier.py; /Volumes/WS4TB/CCam/CAM-Pulse/tests/test_verifier.py. Target: src/claw/verifier.py. Reason: Rejects leaked FIM tokens, detects pytest tests even without pyproject, scores environment failures correctly
**Verify**: PYTHONPATH=src python -m pytest tests/test_verifier.py -q

## Step 12: Enhance
**Command**: `cam enhance /Volumes/WS4TB/CCam/CAM_CAM --mode attended --max-tasks 1 --verbose`
**Purpose**: A8: Structured file-operation token stripping. Source: /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/cycle.py _strip_llm_tokens and _apply_structured_file_operations. Target: src/claw/cycle.py. Reason: Prevents generated source files from containing model control tokens
**Verify**: PYTHONPATH=src python -m pytest tests/test_cycle.py -q

## Step 13: Enhance
**Command**: `cam enhance /Volumes/WS4TB/CCam/CAM_CAM --mode attended --max-tasks 1 --verbose`
**Purpose**: A9: Workspace resolution fallback chain. Source: /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/cycle.py _resolve_workspace_dir; /Volumes/WS4TB/CCam/CAM-Pulse/tests/test_cycle.py. Target: src/claw/cycle.py. Reason: Ensures verification runs against the task or project repo even if the agent lacks workspace_dir
**Verify**: PYTHONPATH=src python -m pytest tests/test_cycle.py -q

## Step 14: Enhance
**Command**: `cam enhance /Volumes/WS4TB/CCam/CAM_CAM --mode attended --max-tasks 1 --verbose`
**Purpose**: A10: Auto-fix rule suggestion mining. Source: /Volumes/WS4TB/CCam/CAM-Pulse/src/claw/evolution/pattern_learner.py generate_auto_fix_rule_suggestions. Target: src/claw/evolution/pattern_learner.py. Reason: Turns repeated correction successes into proposed deterministic fix rules
**Verify**: Add/port targeted test or verify through tests/test_failure_learning.py

## Step 15: Enhance
**Command**: `cam enhance /Volumes/WS4TB/CCam/CAM_CAM --mode attended --max-tasks 1 --verbose`
**Purpose**: A11: Defense proof harness. Source: /Volumes/WS4TB/CCam/CAM-Pulse/scripts/retest_rotation.py. Target: scripts/retest_rotation.py. Reason: Provides an executable proof that rotation/failure knowledge works
**Verify**: PYTHONPATH=src python scripts/retest_rotation.py --help or dry-run equivalent

## Step 16: Enhance
**Command**: `cam enhance /Volumes/WS4TB/CCam/CAM_CAM --mode attended --max-tasks 1 --verbose`
**Purpose**: A12: Defense-chain documentation. Source: CAM-Pulse README.md and docs/index.html defense-chain sections. Target: New or updated CAM_CAM docs only. Reason: Documents the merged system without overwriting serial-evolution docs
**Verify**: Docs diff reviewed manually

## Step 17: Post
**Command**: `python -m pytest -q`
**Purpose**: Run full target validation after all accepted assimilation patches
**Verify**: Full suite passes, or unrelated pre-existing failures are documented separately from assimilation failures
