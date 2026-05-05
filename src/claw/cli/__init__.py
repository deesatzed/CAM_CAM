"""CAM CLI — Typer-based command line interface for CAM-PULSE.

This package was split from a single cli.py module into a package.
All public symbols are re-exported here for backward compatibility.

Primary workflows:
  evaluate <repo>        — inspect one repo and score improvement potential
  enhance <repo>         — improve one existing repo in a bounded loop
  mine <dir>             — learn from outside repos into CAM memory
  ideate <dir>           — invent standalone app concepts from mined knowledge
  preflight <repo>       — clarify a requested task before execution starts
  create <repo>          — create or augment a repo from a requested outcome
  validate               — verify a created repo against its saved spec/checks

Advanced groups:
  learn <subcommand>     — learning continuum, delta, reassessment, synergies
  task <subcommand>      — goal/task setup, runbooks, and task results
  forge <subcommand>     — standalone Forge export and benchmark workflow
  doctor <subcommand>    — preflight and environment diagnostics
  kb <subcommand>        — low-level knowledge browser
  self-enhance <sub>     — self-enhancement pipeline (clone, validate, swap)
  evolution <subcommand> — serial champion/challenger evolution
  cag <subcommand>       — CAG cache-augmented generation (vectorless retrieval)
"""

from __future__ import annotations

# Re-export everything from the monolith for backward compatibility.
# The star-import covers all non-underscore names (public API).
from claw.cli._monolith import *  # noqa: F401, F403

# Explicit re-exports of underscore-prefixed names that tests and
# production code access via `from claw.cli import _xxx` or `cli._xxx`.
# The star-import above does NOT include these because Python's import *
# skips names starting with underscore unless __all__ is defined.
from claw.cli._monolith import (  # noqa: F811
    # Core app and entry point
    app,
    app_main,
    console,
    ROOT_DIR,
    # Sub-app Typer instances
    learn_app,
    task_app,
    forge_app,
    doctor_app,
    pulse_app,
    self_enhance_app,
    ab_test_app,
    evolution_app,
    security_app,
    cag_app,
    kb_app,
    # Constants (underscore-prefixed)
    _IDEA_DIR,
    _PREFLIGHT_DIR,
    _CAMIFY_DIR,
    _FOUNDATION_CHARTER,
    _TRIGGER_KEYWORDS,
    _STOPWORDS,
    _TRIGGER_OPPORTUNITY_MAP,
    # ---------------------------------------------------------------
    # Helper functions used by tests via `from claw.cli import _xxx`
    # ---------------------------------------------------------------
    _setup_logging,
    _required_api_keys_for_command,
    _display_task_status,
    _classify_assimilation_stage,
    _is_future_candidate,
    _doctor_routing_async,
    _normalize_repo_url,
    _normalize_github_url,
    _backup_database,
    _infer_feature_opportunities,
    _recently_created_near_mine,
    _summarize_new_capabilities,
    _derive_activation_triggers,
    _score_methodology_for_task,
    _tokenize_reassessment_text,
    # ---------------------------------------------------------------
    # Helper functions used by tests via `cli._xxx` attribute access
    # ---------------------------------------------------------------
    _resolve_operator_path,
    _agent_supports_workspace_execution,
    _answer_covers_question,
    _apply_answers_to_preflight,
    _build_create_spec,
    _build_expectation_contract,
    _build_foundation_expectation_report,
    _create_async,
    _enforce_quickstart_execution_guard,
    _load_preflight_artifact,
    _merge_preflight_answers,
    _normalize_ideation_payload,
    _quickstart_async,
    _run_live_key_checks,
    _run_preflight_async,
    _snapshot_repo_state,
    _validate_benchmark_against_spec,
    _validate_create_spec,
    _write_create_spec,
    _write_ideation_artifacts,
    # ---------------------------------------------------------------
    # Other underscore-prefixed helpers that may be useful
    # ---------------------------------------------------------------
    _run_python_script_with_timeout,
    _uses_remote_gemini_embeddings,
    _select_live_llm_model,
    _print_api_key_check,
    _fail_if_missing_api_keys,
    _render_live_key_check_results,
    _fail_if_live_key_checks_fail,
    _workspace_execution_agents,
    _print_workspace_execution_preflight,
    _scan_for_cam_runtime_imports,
    _extract_source_namespaces_from_snapshot,
    _scan_for_new_source_namespaces,
    _list_added_repo_files,
    _rollback_added_repo_files,
    _assess_expectation_contract,
    _seed_create_runbook,
    _write_preflight_artifact,
    _build_create_description,
    _infer_preflight_task_kind,
    _estimate_preflight_complexity,
    _time_estimate_for_complexity,
    _budget_estimate_for_complexity,
    _build_preflight_questions,
    _normalize_preflight_answers,
    _should_auto_preflight,
    _build_preflight_prompt,
    _normalize_preflight_report,
    _generate_llm_preflight_report,
    _display_preflight_report,
    _detect_chat_intent,
    _extract_chat_path,
    _chat_prompt,
    _chat_confirm,
    _build_mine_command_preview,
    _chat_handle_mine,
    _select_ideation_model,
    _summarize_repo_tree,
    _summarize_methodology,
    _build_reassessment_expectation_contract,
    _summarize_methodology_usage,
    _build_ideation_prompt,
    _render_ideation_markdown,
    _run_validation_check,
    _looks_like_shell_command,
    _analyze_repo,
    _display_analysis,
    _assess_repo_expectation_baseline,
    _display_evaluation_report,
    _enhance_async,
    _enhance_battery_async,
    _analysis_to_eval_results,
    _display_task_result,
    _display_planned_tasks,
    _fleet_enhance_async,
    _display_fleet_summary,
    _results_async,
    _status_async,
    _expectations_async,
    _doctor_audit_async,
    _display_runbook_details,
    _runbook_async,
    _learn_usage_async,
    _ideate_async,
    _mine_scan_only,
    _mine_async,
    _mine_workspace_scan_only,
    _mine_workspace_async,
    _mine_self_quick,
    _mine_self_async,
    _govern_async,
    _evaluate_async,
    _learn_search_async,
    _confirm_retirement,
    _kb_engine,
    _pulse_engine,
    _pulse_orchestrator,
    _stats_async,
    _add_goal_async,
    _prism_demo_async,
    # ---------------------------------------------------------------
    # Command functions imported by tests
    # ---------------------------------------------------------------
    pulse_freshness,
    pulse_refresh,
    mine_workspace,
    mine_self,
    pulse_ingest_hf,
    # Top-level commands (used by grouped aliases and tests)
    camify,
    _camify_async,
    evaluate,
    enhance,
    fleet_enhance,
    results,
    status,
    chat,
    mine,
    mine_report,
    quickstart,
    preflight,
    create,
    add_goal,
    ideate,
    keycheck,
    validate,
    benchmark,
    govern,
    setup,
    synergies,
    assimilation_report,
    assimilation_delta,
    reassess,
    forge_export,
    forge_benchmark,
    runbook,
    prism_demo,
    stats,
)
