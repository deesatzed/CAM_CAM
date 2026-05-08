# Proof Point Index

How to reproduce every proof point CAM-PULSE claims.

<!-- Counts verified 2026-04-09. -->

## Statistical Proofs

| # | Proof | What It Shows | Reproduce | Detailed Doc |
|---|-------|---------------|-----------|--------------|
| 20 | **Paired A/B (p=0.015)** | KB-equipped agents: 92.3% vs 73.1% success, Cohen's dz=0.45 | `python scripts/run_ab_paired.py` | [ab-proof.html](ab-proof.html) |
| 21 | **Knowledge Budget A/B** | 24K vs 32K chars: no significant difference (p=1.000, dz=0.009). Token Economy slightly worse at 32K (p=0.042). | `python scripts/run_ab_knowledge_budget.py` | [AB_KNOWLEDGE_ABLATION_SHOWPIECE.md](AB_KNOWLEDGE_ABLATION_SHOWPIECE.md) |
| 17 | **SkyDate SWE A/B** | +33.6% composite quality, 100% vs 67% success, p<0.05 on 3/6 dimensions | `python scripts/run_skydate_ab.py execute` | [SKYDATE_KB_SHOWPIECE.md](SKYDATE_KB_SHOWPIECE.md) |
| 16 | **Retry Quality A/B** | KB-equipped wins 7/8 quality checks on retry logic | Manual — see detailed doc | [showcase_retry_backoff.md](showcase_retry_backoff.md) |
| 14 | **Adaptive A/B Margins** | Sample-size-aware win thresholds prevent premature conclusions | `python scripts/run_ab_minitrial.py` | [showcase_retry_backoff.md](showcase_retry_backoff.md) |

## Working Applications (Built from Knowledge)

| # | Proof | What It Shows | Reproduce | Detailed Doc |
|---|-------|---------------|-----------|--------------|
| 25 | **Repo Rescue Desk** | Useful local repo-universe dashboard with risk triage, opportunity ranking, GraphRAG context, and Markmap/Freeplane/Logseq mindmap exports | `./scripts/test_repo_rescue_desk_showpiece.sh` | [Showpiece landing](cam_cam_showpiece.html) / [proof note](CAM_SHOWPIECE_REPO_RESCUE_DESK.md) |
| 24 | **ClinSafer Governed Skill Router** | Updated 4 repos, applied medical skill libraries into ClinSafer, added safety-governed routing, and verified with 395 passing target-repo tests | Manual — see detailed doc | [CAM_SHOWPIECE_CLINSAFER_GOVERNED_SKILL_ROUTER.md](CAM_SHOWPIECE_CLINSAFER_GOVERNED_SKILL_ROUTER.md) |
| 23 | **TidyHome CLI** | Real zero-dep CLI scanned 1.35M files / 97.55 GB on real `~/`, 90% test coverage, 38 tests, 16/16 validation steps pass | `./scripts/test_tidyhome_showpiece.sh` | [CAM_SHOWPIECE_TIDYHOME.md](CAM_SHOWPIECE_TIDYHOME.md) |
| 8 | **Plugin Event System** | 3 repos synthesized into 1 module, 258 lines, 5/5 tests | `./scripts/test_plugin_event_showpiece.sh` | [CAM_SHOWPIECE_PLUGIN_EVENT_SYSTEM.md](CAM_SHOWPIECE_PLUGIN_EVENT_SYSTEM.md) |
| 6 | **PULSE Usage Proof** | Retrieved=3, Used=3, Attributed=3 — knowledge applied with provenance | `./scripts/test_pulse_usage_proof.sh` | [CAM_SHOWPIECE_PULSE_USAGE_PROOF.md](CAM_SHOWPIECE_PULSE_USAGE_PROOF.md) |
| 1 | **Repo Upgrade Advisor** | Ranked recommendations with confidence scores from mined knowledge | Manual — `cam evaluate /path/to/repo --mode quick` | [CAM_SHOWPIECE_REPO_UPGRADE_ADVISOR.md](CAM_SHOWPIECE_REPO_UPGRADE_ADVISOR.md) |
| 2 | **medCSS Modernizer** | End-to-end create, validate, postcheck on real CSS codebase | `./scripts/test_medcss_modernizer.sh` | [CAM_SHOWPIECE_MEDCSS_MODERNIZER.md](CAM_SHOWPIECE_MEDCSS_MODERNIZER.md) |
| 3 | **Expectation Ladder** | 5-level escalating complexity (health, build, validate, mine, self-improve) | `./scripts/test_expectation_ladder.sh` | [CAM_SHOWPIECE_EXPECTATION_LADDER.md](CAM_SHOWPIECE_EXPECTATION_LADDER.md) |
| 5 | **Cross-Repo Intelligence** | Semantic search finds shared patterns across repos from different domains | `./scripts/test_cross_repo_intelligence.sh` | [CAM_SHOWPIECE_CROSS_REPO_INTELLIGENCE.md](CAM_SHOWPIECE_CROSS_REPO_INTELLIGENCE.md) |
| 7 | **Multi-Pass Mining** | 3-pass pipeline: classify, overlap, extract with adaptive token budget | Manual — `cam pulse ingest <url>` | [CAM_SHOWPIECE_PULSE_KNOWLEDGE_LOOP.md](CAM_SHOWPIECE_PULSE_KNOWLEDGE_LOOP.md) |

## Self-Evolution Proofs

| # | Proof | What It Shows | Reproduce | Detailed Doc |
|---|-------|---------------|-----------|--------------|
| 9 | **Inner Correction Loop** | Workspace restore + agent re-prompt with violations. 3 retries then success. | `./scripts/run_cam_reliability_pipeline.sh` | README (Proven End-to-End section) |
| 13 | **Self-Enhancement Pipeline** | Clone, enhance, 7-gate validate, atomic swap. Quality 0.97, all tests pass. | `cam self-enhance start` | README (Self-Enhancement section) |
| 10 | **Metric Expectations** | Natural language specs become structured gates. 51 tests. | `pytest tests/test_metric_expectations.py -q` | README (Metric Expectations section) |

## Live Pipeline Proofs

| # | Proof | What It Shows | Reproduce | Detailed Doc |
|---|-------|---------------|-----------|--------------|
| 4 | **PULSE Knowledge Loop** | 16/16 repos discovered, cloned, mined, stored. Zero failures. | `./scripts/test_pulse_knowledge_loop.sh` | [CAM_SHOWPIECE_PULSE_KNOWLEDGE_LOOP.md](CAM_SHOWPIECE_PULSE_KNOWLEDGE_LOOP.md) |
| 11 | **Repo Freshness Monitor** | ETag caching + significance scoring. Phase 1 costs 0 rate limit for unchanged repos. | `cam pulse freshness --verbose` | README (Repo Freshness Monitor section) |
| 12 | **Pre-Assimilation Secret Scanner** | Two-gate TruffleHog + regex fallback blocks secrets before LLM. 73 tests. | `cam security scan /path/to/repo` | README (Pre-Assimilation Secret Scanning section) |

## Intelligence Infrastructure Proofs

| # | Proof | What It Shows | Reproduce | Detailed Doc |
|---|-------|---------------|-----------|--------------|
| 13 | **Bayesian Kelly Agent Routing** | Sukhov (2026) position-sizing for intelligent agent selection. 39 tests. | `pytest tests/test_kelly.py -q` | README (Bayesian Kelly Criterion section) |
| 15 | **Uncertainty-Aware Fitness** | Agent reliability discounts methodology rankings up to 30% | `pytest tests/test_kelly.py -q` | README (Bayesian Kelly Criterion section) |
| 18 | **RL Method Tournament** | Epsilon-greedy bandit + Thompson sampling selects best methodology per task type. 40 tests. | `pytest tests/test_bandit.py tests/test_bandit_integration.py -q` | README (RL Method Tournament section) |
| 19 | **Cross-Brain Pattern Atlas** | "defense-in-depth security" query returns 40 results from 5 brains, 2 universal patterns, 108 transferable insights | `cam federate "defense-in-depth security for a multi-tenant AI agent gateway"` | README (Cross-Brain Pattern Atlas section) |

## Visual Proof

| # | Proof | What It Shows | Reproduce | Detailed Doc |
|---|-------|---------------|-----------|--------------|
| 22 | **The Architect** | Same task built twice (no KB vs full KB), visual HTML report with brain topology, gate comparison, code diff, knowledge attribution, token cost | `python scripts/run_architect_showpiece.py` | [architect_showpiece_report.html](architect_showpiece_report.html) |

## End-to-End Proof

| # | Proof | What It Shows | Reproduce | Detailed Doc |
|---|-------|---------------|-----------|--------------|
| 14 | **Knowledge Application (TaskPulse)** | Mine, retrieve, inject, build, verify, learn — complete loop with real LLM | `cam create /tmp/taskpulse --execute --request "Build async task queue tracker" --check "pytest -q"` | README (Proven End-to-End section) |

---

**Full test suite** (validates nothing is broken): `PYTHONPATH=src python -m pytest tests/ -q` (3,734 tests)
