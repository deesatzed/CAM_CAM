# CAM-Pulse Parity Diff

Date: 2026-05-08

Compared:

- Source: `/Volumes/WS4TB/CCam/CAM-Pulse`
- Target: `/Volumes/WS4TB/CCam/CAM_CAM`

This is a classification document. It intentionally does not copy source code.

## Summary

`CAM_CAM` and `CAM-Pulse` share the same Python package identity (`src/claw`), CLI package, tests, and `pyproject.toml`. `pyproject.toml` is identical. The differences are mostly in core engine files, tests, docs, and CAM_CAM-only showpiece additions.

The right merge direction is not a wholesale replacement. `CAM_CAM` already contains showpiece, serial evolution, specialist exchange, and Repo Rescue Desk work that is not in `CAM-Pulse`. `CAM-Pulse` contains newer defense-chain and model-diverse README/proof updates that should be ported into `CAM_CAM` deliberately.

## Already Compatible

- `pyproject.toml` has no diff.
- Both repos expose the same `claw` package identity.
- Both repos use the same broad test layout.

## CAM_CAM-Only Material To Keep

These files are unique to `CAM_CAM` and should be preserved:

- `apps/repo_rescue_desk/`
- `docs/cam_cam_showpiece.html`
- `docs/CAM_SHOWPIECE_REPO_RESCUE_DESK.md`
- `docs/CAM_SHOWPIECE_REPO_RESCUE_DESK.html`
- `docs/showpieces/repo_rescue_desk/`
- `docs/CAM_CAM_POST_MERGE_CHECKPOINT_2026-05-06.md`
- `docs/CAM_CAM_PULSE_ASSIMILATION_GUIDE_2026-05-05.md`
- `docs/CAM_CAM_PULSE_CAMIFY_PLAN_2026-05-05.md`
- `docs/CAM_PULSE_SERIAL_EVOLUTION_CHECKPOINT_2026-05-05.md`
- `docs/CAM_PULSE_SERIAL_EVOLUTION_PLAN.md`
- `docs/plans/CAM_SEQ_M7_external_specialist_exchange_plan.md`
- `src/claw/community/specialist_exchange.py`
- `src/claw/evolution/serial.py`
- `tests/test_serial_evolution.py`
- `tests/test_specialist_exchange.py`

## Generated Files To Ignore

The `diff -qr` output shows many `__pycache__` directories present only in `CAM_CAM`. These are generated artifacts, not product differences, and should not drive the merge.

## Source Files Requiring Manual Port Review

These files differ between `CAM-Pulse` and `CAM_CAM`. They should be reviewed in slices, not copied over blindly:

- `src/claw/agents/interface.py`
- `src/claw/camify.py`
- `src/claw/cli/__init__.py`
- `src/claw/cli/_monolith.py`
- `src/claw/core/config.py`
- `src/claw/core/exceptions.py`
- `src/claw/core/models.py`
- `src/claw/cycle.py`
- `src/claw/db/embeddings.py`
- `src/claw/db/engine.py`
- `src/claw/db/repository.py`
- `src/claw/db/schema.sql`
- `src/claw/dispatcher.py`
- `src/claw/evolution/__init__.py`
- `src/claw/evolution/assimilation.py`
- `src/claw/evolution/pattern_learner.py`
- `src/claw/evolution/rl_escalation.py`
- `src/claw/llm/client.py`
- `src/claw/mcp_server.py`
- `src/claw/memory/error_kb.py`
- `src/claw/memory/fitness.py`
- `src/claw/miner.py`
- `src/claw/mining/component_extractor.py`
- `src/claw/planner.py`
- `src/claw/pulse/assimilator.py`
- `src/claw/security/policy_tools.py`
- `src/claw/tools/schemas.py`
- `src/claw/verifier.py`
- `src/claw/web/dashboard_server.py`

## Test Files Requiring Manual Port Review

These tests differ and should be used as the first source of truth for behavioral deltas:

- `tests/test_assimilation.py`
- `tests/test_assimilator_freshness.py`
- `tests/test_camify.py`
- `tests/test_cli_ux.py`
- `tests/test_component_extractor.py`
- `tests/test_config.py`
- `tests/test_create_benchmark_spec.py`
- `tests/test_cycle.py`
- `tests/test_cycle_evolution.py`
- `tests/test_dashboard_camseq.py`
- `tests/test_dispatcher.py`
- `tests/test_embeddings.py`
- `tests/test_failure_knowledge.py`
- `tests/test_llm.py`
- `tests/test_mcp_camseq_tools.py`
- `tests/test_miner.py`
- `tests/test_miner_brains.py`
- `tests/test_miner_polyglot.py`
- `tests/test_phase4.py`
- `tests/test_planner.py`
- `tests/test_policy_tools.py`
- `tests/test_pulse_cli.py`
- `tests/test_tier2_memory_services.py`
- `tests/test_validation_gate.py`
- `tests/test_verifier.py`

## Docs Requiring Manual Port Review

- `docs/CAMSEQ_LOCAL_SECURITY.md`
- `docs/CAM_IFY_REPO_GUIDE.md`
- `docs/PROOF_POINT_INDEX.md`
- `docs/index.html`
- `docs/plans/CAM_SEQ_live_status.md`
- `docs/plans/CAM_SEQ_milestone_table.md`
- `docs/site/index.html`

## First Import Candidates

Start with low-risk, high-signal updates:

1. README identity and defense-chain proof language from `CAM-Pulse`.
2. Proof docs and proof index updates that do not affect runtime behavior.
3. Tests that describe defense-chain behavior, especially failure knowledge and rotation.
4. Agent/model routing code after the tests are in place.
5. Protected core files last: verifier, factory/config, engine, schema.

## Merge Rule

Every source-code import should answer three questions before commit:

1. What CAM-Pulse behavior is missing from CAM_CAM?
2. Which test proves the behavior?
3. Which CAM_CAM-only showpiece or integration could this accidentally break?
