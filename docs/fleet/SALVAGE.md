# Fleet salvage ledger

Written 2026-08-28 before archiving copies and deleting empty repos.
These are methods to port into keepers, not repos to keep alive.
Canonical keepers are tagged `fleet-keep`. Archived copies stay readable.

## Canonical keepers

| Keeper | Role | Port into it from |
|---|---|---|
| CAM_CAM / CAM-Pulse / CAM_Codx / CAM-RAG | Repo intelligence, mine→build→bandit, GraphRAG | clawamorphosis, cam_wiki, iDeers, CAM_Grok, newragcity, repo-refit patterns |
| ClinSafer + clinclaw-firewall + Agent_Pidgeon | Clinical autonomy firewall, receipts | JRE-BSG-DHSW |
| hcc_synth_1 + mamaclaw + mamaclaw-hearth-sdk | Hospital-at-Home stigmergy + rule/cue tables | kcc_synth_1, logswarm-anomaly-detection, rustigmergic-logswarm-engine |
| HarborSafePHI + Carrel + redaktR | PHI airlock (browser PDF, call-slip, consensus redaction) | HC_PII_REDACT_MCP as MCP surface only |
| tuhs-abx-steward + TUHSabxGuide + DKR | TUHS antibiotic CDS + knowledge packs | eTempleABX, ABXorcist extras |
| tuhs-honest-broker | HIPAA research governance portal | HBRnexus (NL→SQL 5-layer validation + PHI exclusion list) |
| aXc-ace-forecaster | Hospital census ensemble + aXc priors | hospital_census_forecaster, ace-forecaster, clearn_ace_forecaster, universal-ace-forecaster, ace-aXc-clean |
| Neuro-Lesion_Mapper | Deficit → territory rules engine | — |
| stewardsim | Min-regret antimicrobial sim | genupop |
| VAMS + vams-coordination | Sparse Hopfield action memory | vams-core (empty), vams-suite, vamskills, Vamplify-Claude / vamllama as adapters |
| eMedGen / DNAsed | Local genomic data diode | EmediGen (empty), DNAsedLongevity |
| ersatz_rag / RegulusPlus | Confidence-gated policy RAG | Regulus |
| ed-healthcare-alert-web, ED_Dispo_SDM, SecondEDeyes | ED alert desk, SDM wizard, second-look prompt | SecondSetEyes, SafetySetOfSecondEyes |
| EmberScape, FloodRisk4D, SoveRain | Geospatial / WUI / flood / rain | — |
| predictive-model-evaluator | AUROC-trap / vendor-claim → workload | — |
| sentinel_arbiter + ClinicalAiForensics | Warranted-yet / VOI / CDE | — |
| logvams | AR(1)/CSD early warning (IP: PATENT_DISCLOSURE) | EIN_Sandbox |
| VAAS | Atoms-of-Thought eval gate | — |
| codec_ceiling | Symbolic vs measurement information loss | codec_perceptibility_gap, clawswarmed Glass Gate, A12Aprime |

## Methods to port (do this before treating an archive as gone)

### Clinical safety and CDS

- **Most-restrictive-wins firewall:** ClinSafer JRE/MUD/CLEAR/Black Swan → Agent Pidgin receipts → clinclaw-firewall pipeline. One composition, not three products.
- **Institutional ABX packs + dose-by-indication:** DKR JSON (pneumonia/sepsis/meningitis) + tuhs-abx-steward ABXguideInp/DOSIING/INFECTION_SOURCE. PharmD-gated. Steal PENFAST/Chroma bits from ABXorcist if still unique.
- **NL→SQL 5-layer validation + PHI exclusion list:** HBRnexus → tuhs-honest-broker, then the ancestor can stay archived.
- **Honest Broker intake machine:** schema-driven form JSON, email→draft parser, crypto approval tokens (already in tuhs-honest-broker).
- **Deficit→territory engine:** Neuro-Lesion_Mapper `src/neuro_ct_app/engine.py` + `scripts/validate_rules.py` + `config/cases.json`.
- **AUROC trap:** predictive-model-evaluator `AUROCTrap.tsx`, `VendorClaimEvaluator.tsx`, `CapacityPlanner.tsx`.
- **Warranted-yet checklist / VOI:** sentinel_arbiter + ClinicalAiForensics CDE + free-text-cannot-modify-priors.
- **Min-regret stewardship loop:** stewardsim THEORY.md (empiric choice → pathogen population → next clinician optimum) + analytic-limit tests. Fold genupop.
- **ACE no-drift gates:** aXc-ace-forecaster SLSQP ensemble + `validate_no_drift.py` from ace-aXc-clean + 7-gate safety + holiday features from hospital_census_forecaster.
- **ED NodePack SDM:** ED_Dispo_SDM clinician-reviewed probability nodes, no ranking.
- **Second-look prompt:** SecondEDeyes `app.py` EMSA + specialty round-table + 10 critical questions. Do not revive the two stubs.
- **ED ID-alert desk:** ed-healthcare-alert-web advisory schema + hospital-internal protocols + `/health` `/self_test`. Rotate any leftover admin/admin123.
- **FCA integrity gate:** AdmSVE / Case_Mgr_Claw: suppress status-helping-but-not-indicated actions even on the LLM path.
- **mevisian thesis:** personalize the visit for this patient, not the doctor style or the genome; structurally enforced physician approval.
- **GS_inpatient:** boarding-yield contracts, bill-invariance, no-HITL allocation, append-only event evidence.

### PHI

- **Browser data diode:** HarborSafePHI, PDF never uploaded; OpenRouter sees only user-approved redacted text. Tests in `src/lib/phi/`.
- **Call-slip UX:** Carrel verbs (Ask the packet / Fill a call slip / Find local / Keep on purpose / Receipts) + identifier guards.
- **4-technique consensus redaction:** redaktR Regex∥SpaCy → mandatory MLX double-check → weighted consensus; 21 HIPAA Safe Harbor list; API + MCP + folder monitor.
- **Do not start a fourth PHI product.** HC_PII_REDACT_MCP is a surface, not a new app.

### Memory, agents, CAM

- **Sparse Hopfield action memory:** VAMS MemoryRouter + typed PMI edges + energy-conflict + ActionEncoder. One library, one MCP.
- **O(n) multi-agent on shared VAMS:** vams-coordination LinearCoordinationOrchestrator.
- **CAM-PULSE loop:** mine → evidence-gate → build → Thompson sample on real pytest → 3-layer defense chain. Already in CAM-Pulse; don’t rebuild.
- **Repo Necromancer / Rescue Desk:** CAM_CAM GraphRAG cluster + JSON patch-plan, 0 source mutations in the showpiece run.
- **Atoms of Thought eval:** VAAS Decomposer → Verifier → Scorer as a gate on AutoXcon/ABX agents.
- **fractLrag:** sentence/paragraph/document index + inter-level derivatives. Port into CAM-RAG.
- **deepConf RAG gate:** ersatz_rag 5-factor ~0.80 gate; prefer small RegulusPlus tree over 38MB Regulus.
- **Database-as-superego:** SQLcortex Postgres triggers rejecting unsafe agent INSERTs.
- **Tiny-model specialist orchestration:** vamllama 95% VAMS compression so 2B/4k models can run specialists.
- **ECHO Triple-Helix personality:** L0 immutable / L1 adaptive / L2 meta. Architecture only; do not reuse personal `answers_batch_*.json`.

### Signals, compression, research

- **AR(1) / critical slowing down:** logvams PhaseMonitor + EIN_Sandbox SYNAPSE/k8s_capacitor. logvams has PATENT_DISCLOSURE; treat as IP.
- **MedTOON codebook compression:** redLTcMed ICD-10/RxNorm/CPT/LOINC. Ancestor quantlsq can archive.
- **codec_ceiling:** preregistered symbolic-description vs measurement bakeoff. Keep as research with perceptibility-gap / Glass Gate / A12A HELIX. No more consciousness dashboards.
- **xplurx IR:** Claim / Falsifier / Decision so swarms can decode evolved protocols without training.
- **NSGA-II swarm genetics:** drone-war-sim reproducibility contract.
- **10/50 revolving-door ethics:** moriah-omega thesis for HBR/finance, not the incomplete tree.

### Genomics and local tools

- **Data-diode genomics:** Rust parser + 127.0.0.1 bridge + Fly only sees abstracted output. Pick one name (eMedGen vs DNAsed) later.
- **Hash-only .env census:** OneDoTenv. Several ACE/HBR/ABX roots still commit `.env`; rotate.
- **Formatter-first clipboard repair:** eClipLint / clipstore2. Path-inherited encrypted API vault: apikee.

## Per-repo salvage bullets (from inventory)

Only repos with recorded salvage and U≥5 or N≥4. Archived sources stay cloneable.

| Repo | Status | U | N | Salvage |
|---|---|---:|---:|---|
| `CAM-Pulse` | iteration | 8 | 8 | Discover-mine-store-retrieve-build-verify-correct-rotate-learn-demote loop with Thompson sampling on real pytest outcomes. · 3-layer defense chain: deterministic auto-fix, correction loop, model rotation. · camify.sh + claw.toml + SKILL.md operator surface. · Local-first Ollam… |
| `clinclaw-firewall` | iteration | 8 | 8 | Unified pipeline: Gateway -> ClinSafer Governor (JRE->MUD/CLEAR->Black Swan->T0-T4 cap) -> Skill Runner -> Claims Ledger -> Pidgin policy -> action. · Most-restrictive-wins composition of two independent governors; HMAC signing, circuit breakers, hash-chained traces. · CHI-Ben… |
| `ClinSafer` | iteration | 8 | 8 | MUD map + CLEAR next questions. · Black Swan Guardrails capping autonomy T0-T4. · JRI 0-100 + READY/CLARIFY/NEED_OBJECTIVE_DATA/ESCALATE. · Any-Dispo / Cognitive Bias Field / Uncertainty Graph in interactive_demo.py. |
| `hcc_synth_1` | iteration | 8 | 8 | src/stigmergy/substrate patient_field.py (40-dim) plus Welford self_model.py baselines. · falsifier_engine.py (9 templates) plus decision_policy.py 20:1 miss-to-false-alarm cost. · fatigue/ 6 controls: cooldown, budget, severity routing, smart suppression, semantic dedup, esca… |
| `VAMS` | final | 8 | 8 | Sparse Hopfield MemoryRouter + MemoryGraph typed edges (vams/) · Energy-based conflict detection and convergence-as-confidence · AEGIS binary compression for edges/feedback (claimed ~70%) · vams_mcp_server for Claude Code |
| `Agent_Pidgeon` | iteration | 7 | 8 | schemas/ for resolve, catalogs, receipts, AAFR traces. · Semantic diff for removed safety primitives and hash drift. · Resolution receipts with catalog+implementation hashes. · Trusted clinical-safety catalogs; MCP + A2A wrappers. |
| `CAM_CAM` | iteration | 8 | 7 | CAM-PULSE method engine: mine reusable engineering patterns from source with evidence gates before an agent edits. · Repo Necromancer / MyLoc: generate a standalone subsystem-transplant repo then evaluate/preflight/camify with JSON patch-plan output. · Repo Rescue Desk: 238 re… |
| `mamaclaw` | iteration | 8 | 7 | rule_table_v3_core61.csv plus cue_templates_v3.csv as the deterministic kernel. · 8-stage pipeline: adapters to PatientStateField to EventLabeler to Falsifier to FHIR. · HAH1.md edge blueprint (Pi 5, Coral, LiteRT) and 30-condition catalog. · hearth-delivery already extracted … |
| `anonobit` | iteration | 7 | 7 | Deterministic Gaussian Autoencoder v5 plus temporal features; per-file F1 table on HAI 21.03. · Generic multi-sensor schema plus device onboarding - not ICS-only. · H@H layer: per-patient baselines, clinical rules, tiered alerts, FHIR R4. · Symbolic protocol / tournament layer… |
| `aXc-ace-forecaster` | iteration | 7 | 7 | SLSQP ensemble weight optimizer plus MAPE-gated production validation (claimed 1.51% on 1,630 days) · aXc prior conversion: ACE production deltas → Bayesian Beta priors that seed the next SLSQP start (the 61% degradation bugfix lives here) · Weather/holiday exogenous features … |
| `Carrel` | iteration | 7 | 7 | Verb split (Ask the packet / Fill a call slip / Find local / Keep on purpose / Receipts) — reuse as PHI UX contract. · Tests: src/lib/packet.test.ts, desk-safety, desk-receipts, slip-guard, excerpt-choice, lamp-model. · Identifier guards so the same mouth that reads a chart ca… |
| `deterministic_knowledge_retrieval` | iteration | 7 | 7 | Antibiotic knowledge packs (pneumonia.json, sepsis_unknown_origin.json, meningitis.json, abx_med_dose.json, …) · Agent trio: TOC + Loader + Answer/Verifier with token-budget 4000 · PHI/PII/residency policy hooks in the router · domain_agnositc_knowledge_pack.md adapter pattern |
| `HarborSafePHI` | iteration | 8 | 6 | Privacy model: PDF never uploaded to Fly; OpenRouter gets only user-approved redacted text. · PHI test surface: src/lib/phi/{detect,manual,pdf-text,packet}.test.ts. · OpenMed in-browser inference as optional NER layer on top of deterministic detection. |
| `logvams` | iteration | 6 | 8 | PhaseMonitor AR1+variance CSD early-warning (claimed 35.9-observation lead time) · Mahalanobis unlabeled baseline from astronomy-style multivariate distance · Semantic/structural entropy as a 'system is confused' novel-failure flag · PATENT_DISCLOSURE.md + PHYSICS_FOUNDATIONS_… |
| `Neuro-Lesion_Mapper` | iteration | 7 | 7 | src/neuro_ct_app/engine.py scoring engine + config/ scoring JSON and curated cases.json. · scripts/validate_rules.py grid-search that can persist best weights. · ai_parser/ with cache+metrics and confidence-threshold fallback to heuristics. · triage/ + kb/ JSON fusion (alpha/t… |
| `predictive-model-evaluator` | iteration | 7 | 7 | AUROCTrap.tsx: high AUROC + low PPV auto-detect at low prevalence · VendorClaimEvaluator.tsx: sens/spec → FP:TP workload per 1000 · CapacityPlanner.tsx flagged/day vs capacity/day · Scenario presets for ICH and other EM use cases |
| `redaktR` | iteration | 8 | 6 | 4-technique pipeline + consensus engine; AST-grep dropped after 0 contribution on tabular data. · Service-specific technique ordering (folder: Regex//SpaCy→MLX; MCP: SpaCy→Regex→MLX). · Measured timings on ws_sample.csv (~85k chars): parallel 2.6s vs sequential 9.2s. · api_ser… |
| `stewardsim` | iteration | 6 | 8 | THEORY.md loop: individual empiric choice to pathogen population to next clinician optimum; not cycling-vs-mixing. · Min-regret under structural uncertainty + adherence-robustness curve (not optimum under one mechanism + perfect compliance). · src/stewardsim/{host,pathogen,pol… |
| `tuhs-abx-steward` | iteration | 8 | 6 | ABXguideInp.json / ABX_DOSIING.json / ABX_INFECTION_SOURCE.json as the institutional knowledge core · Per-infection specialized agents + allergy decision trees · DoseCalculator by_indication format (ssti, bone_joint, endocarditis, cns) from Oct 9 commits · PharmD-gated evidenc… |
| `tuhs-honest-broker` | iteration | 8 | 6 | Schema-driven intake (backend/config/intake_form_config.json) so governance fields evolve without redeploy · Email-thread → GPT parser → draft wizard autofill · Cryptographic approval tokens on email reply/link · HB taxonomy JSONs and WORM-ish action logging |
| `AdmSVE` | iteration | 7 | 6 | Integrity gate in the LLM path that suppresses status-helping-but-not-independently-indicated actions and logs them (FCA guardrail). · Swappable PHI/PII redaction layer: deterministic floor plus optional gated OpenMed/RedaktR MCP backend before any cloud LLM. · 7-step localhos… |
| `careframe` | iteration | 7 | 6 | Mobile-first pre-visit brief PWA for patients and caregivers. Explicitly not a diagnosis or triage tool. |
| `ClinicalAiForensics` | iteration | 6 | 7 | CDE JSON + domain-pack YAML loaders. · Uncertainty-budget and VoI before sampling. · AI-answer mapping cannot modify priors. · Provenance JSONL + advisory Markdown. |
| `codec_ceiling` | iteration | 5 | 8 | Channel taxonomy in src/: direct CNN vs bottleneck vs quantile-binned symbolic (Q/Q_ord/Q_idx) vs embed-MLP. · Coupled-oscillator RK4 simulator (simulate.py) + 24 engineered features (features.py). · Preregistered confirmatory holdout (scripts/stage_h_h7_holdout.py, seed=2027)… |
| `DNAsed` | iteration | 7 | 6 | Data-diode: secure_genome_parser (Rust) plus local refs.db; only abstracted insights sync to Fly. · local_desktop_bridge.py FastAPI on localhost:18000 as the only path between web UI and raw genome. · Tauri v2 self-contained desktop installer removing the Python-bridge require… |
| `ed-healthcare-alert-web` | iteration | 8 | 5 | Advisory schema + hospital-based internal protocol support (HOSPITAL_BASED_ADVISORIES.md). · Upload .md/.pdf → AI parse into title/category/content/key points (app.py + Check_Sources_Prompt.txt / new_prompt.txt). · /health and /self_test diagnostic endpoints — copy to other cl… |
| `ED_Dispo_SDM` | iteration | 7 | 6 | NodePack schema: AI-extracted, clinician-reviewed probability nodes that the expert system may compute over but never rank/choose. · Dual rendering: clinician percentages-with-ranges vs patient 'about X in 100' framing. · Separation of clinical search query from operational co… |
| `EIN_Sandbox` | iteration | 5 | 8 | AR(1) autocorrelation as a universal saturation/CSD signal across agents, routers, and k8s · SYNAPSE router validation notes (claimed 45% latency / 36% cost on real API calls) · Energy-economics survival pressure in mai_evolution/ · k8s_capacitor Go autoscaler using AR(1) for … |
| `eMedGen` | iteration | 7 | 6 | Architecture: secure_genome_parser (Rust) + local_desktop_bridge.py (127.0.0.1:18000) + cloud_backend FastAPI + desktop_companion Tauri. · Weekly evidence-refresh CI plus cloud-backend-tests and refs-tools-tests. · Validated SNP panels (153 SNPs + domain CSVs) and ClinVar impo… |
| `ersatz_rag` | iteration | 7 | 6 | deepConf 5-factor scorer (semantic, authority, relevance, structure, model) with default 0.80 gate. · Version-aware policy retrieval + audit trail (Regulus). · PageIndex hierarchical PDF tree with chunking fallback (integrate, don't reimplement). · Cognitron local-first CLI (i… |
| `fractLrag` | iteration | 6 | 7 | Three self-similar index levels plus derivative signals between levels. · retrieve_adaptive() query-type routing including synthesis diversity_boost. · Metadata filters, recency boost, domain routing. · HashEmbedding for tests; BGE-M3 SentenceTransformerEmbedding for real runs. |
| `mevisian` | iteration | 6 | 7 | Thesis: most clinical AI personalizes the doctor or the biology; this models what this patient needs in the visit. · Structurally enforced physician approval of every patient-facing word. · Consent ledger + RxNorm connector; REGULATORY_ASSUMPTIONS.md non-device framing. |
| `moriah-omega` | incomplete | 6 | 7 | 10/50 problem framing (10% of patients drive 50% of margin loss) as a product thesis · KPI calculation engine (20+ utilization/financial metrics) in backend/ · High-cost cohort detection on PHI-scrubbed episodes · Planned ethical governor + micro-trial proposals (Phase 3–4) — … |
| `redLTcMed` | iteration | 6 | 7 | Medical codebook compressors (ICD-10 275, RxNorm 210, CPT 85, LOINC 104) with synonym variants · 10-stage semantic pipeline (synonym canonicalization, JCAHO abbreviations, etc.) · Hot/cold partitioning with temporal decay for hybrid RAG (lsq_leann_hybrid*.py) |
| `sentinel_arbiter` | iteration | 6 | 7 | Warranted-yet checklist: known, missing-knowable, harm-soon, future-correction, AI-derived, next-input VOI, prudent layperson-provider-AI. · Shadow-mode/replay-mode on constructed ED inputs with node-audit + ensemble contribution normalization. · Clinician review console miles… |
| `TUHSabxGuide` | iteration | 8 | 5 | Stepwise assessment workflow: demographics → allergies → cultures → infection source → risk factors. · Renal-adjustment + recommendation-confidence updates (commit 2025-09-19). · Prisma patient-assessment model with SQLite-dev / Postgres-prod; Jest tests under __tests__. · Opt… |
| `VAAS` | iteration | 6 | 7 | Three-atom pipeline (Decomposer → Verifier → Scorer) as a reusable eval contract · Medical hallucination example (Aspirin vs Penicillin allergy) as a gold fixture · Zero-leakage / no-narrative scoring philosophy — use as a gate on other agent repos |
| `vams-coordination` | iteration | 6 | 7 | LinearCoordinationOrchestrator 4-phase: parallel recall → process → sequential learn → synthesis (core/coordinator.py) · ActionEncoder 456D → k-WTA sparse patterns (core/action_encoder.py) · 8 ADRs (O(n) coordination, Hopfield, typed edges, AEGIS compression) · Dev agent pack:… |
| `xplurx` | iteration | 5 | 8 | Immutable IR dataclasses: Claim, Falsifier, Decision with prior/posterior confidence and origin. · Grounded symbol semantics so naive swarms can decode without training. · Tournament plus learnability CI gates (test_smoke.py, run_30gen_experiment.py). · RESEARCH_PAPER_DRAFT.md… |
| `ABXorcist` | iteration | 7 | 5 | PENFAST penicillin-allergy scoring + culture-guided therapy in tuhs_integration/. · JSON TUHS guideline pack + ChromaDB semantic lookup. · Audit-trail / confidence display for CDS governance. · Ignore the unrelated Regulus_*, Thalamus_*, Cognitron_* markdown — copy-paste from … |
| `ACA-gap` | iteration | 7 | 5 | clinicalEngine.js entirely in-browser: risk profile, predicted labs with cash-pay prices, seeded monteCarlo(1000), three blueprints. · No-PHI design: backend is AI-only with NDJSON audit plus policy RAG. · Deep-link parameterization plus Health Plan Explainer; deployed Fly.io.… |
| `aXc` | iteration | 6 | 6 | Phase 5 interactive clarification: detect ambiguities → PubMed/arXiv → ask 4 questions → refine before expensive ensemble · 6 decision models (Markov, Causal, Bayesian, RL, Game-theoretic, Multi-objective) + arbiter · Enhanced dialogue engine with multi-party support (Oct 31 c… |
| `CAM-RAG` | iteration | 7 | 5 | policy hooks for PHI/RBAC in cam_rag layout. · Blended rerank, intersection boost, BM25 anti-flood. · Hash dense backend for tests; real embeddings next. · apps/ragamuffin document-folder app. |
| `CAM_Asst_Pendiolam` | iteration | 5 | 7 | SRP schema: source vs claim vs evidence vs counterevidence vs uncertainty vs minority reports. · Product sentence: build the shared record before asking people to agree. |
| `CAM_Codx` | iteration | 7 | 5 | Normal workflow contract: install cam-codx skill, ask for an outcome, bounded approvals. · XTtape showpiece: vanilla-vs-CAM planning comparison. · agent-packs/, prompts/, tools/ as reusable CAM skill surface. |
| `CIO-II` | iteration | 6 | 6 | Model never generates text; 80ms timeout; do-nothing is first-class. · Hard-blocks password fields, code editors, terminals; tracked undo; trust circuit breaker. · CI plus claimed 331 tests; validate-user-journey.sh and verify-mitigations.sh. |
| `CIO-Shield` | iteration | 6 | 6 | Tokenized clipboard shield with vault backfill. · Apple FM as 80ms candidate-selector that may do nothing; never generates text. · Password-field hard-block and trust circuit breaker from CIO-II. |
| `clawswarmed` | iteration | 4 | 8 | GLASSGATE_LIFT = D(scarce_protected) minus max of abundant/random/naive-topk. · Label-free controllers + multi-seed battery (Glass Gate Control V2). · Prereg files and replayable ledgers before any claim. |
| `clininfo-gate` | iteration | 6 | 6 | Completeness VOI loop + narrative attribution risk guardrails (PR #1). · Independent verifier inside an OE improvement loop — does not replace OE. · Sibling-package imports (ClinicalAiForensics pdde, AdmSVE) never vendored. |
| `EmberScape` | iteration | 6 | 6 | Product thesis: 5-ft gravel is not a product; vents/fences/decks/eaves/juniper/canopy/shakes are why house 12 still fails. · Jobs split: fire-marshal ember-cast + ranked inspection list vs planner fuel-break vs engine-company investment (labeled screening, not ISO). · README n… |
| `GS_inpatient` | iteration | 6 | 6 | Frozen contracts/fixtures + hourly scenario runner + append-only event evidence with replay. · Acceptance verdicts: bill invariance, floor rules, no-HITL policy — ./scripts/verify.sh. · Read-only Streamlit viewer over FastAPI executor. |
| `HBRnexus` | sunset-candidate | 6 | 6 | NL→SQL 5-layer validation pipeline (don't lose this when using tuhs-honest-broker) · AI auto-approval risk score 0–100 + 30+ PHI identifier exclusion list · REDAKTR_INTEGRATION_PLAN.md for de-identification |
| `HC_PII_REDACT_MCP` | iteration | 7 | 5 | Explicit 21 HIPAA Safe Harbor category list and standardized placeholders. · Dual backend selector (server2_mlxk.py / server2_ollama.py / server_selector.py). · README_TWO_STAGE_ARCHITECTURE.md + force_llm flag on scan_healthcare_text. · claude_desktop_config.json MCP wiring —… |
| `manEganx` | iteration | 6 | 6 | MEAL (body) vs MENU (narrative) split as the core clinical metaphor. · Loop Radar 6-factor classification driving protocol gating. · Anti-reassurance: detect certainty-seeking and protocol overuse; name the loop instead of feeding it. · Zero-linkage: no accounts/server/analyti… |
| `medical-autoXcon` | iteration | 6 | 6 | Hierarchy vs metadata split: EGFR/ALK/BRAF/PD-L1 as tags, geriatrics as modifier — not extra tree levels · Per-subspecialty VAMS cache with adaptive thresholds · ncbi-mcp-server + biomcp evidence aggregation |
| `onco_snp_nutra` | iteration | 6 | 6 | Evidence containers. · Gated retrieval. · Reviewer packet. |
| `ralfed` | iteration | 6 | 6 | DIRAC: inject .claude/ skills/hooks/CLAUDE.md into a target repo and drive Claude Code as a subprocess. · Cross-task failure pattern mining: normalized error signatures injected as forbidden approaches on later tasks. · Sentinel 6+1: dependency jail, style match, chaos check, … |
| `RegulusPlus` | iteration | 7 | 5 | Full-stack compose (postgres, redis, qdrant, opensearch, backend, admin_frontend) as a reusable RAG chassis. · backend/scripts/bootstrap_pnp.py ingest+query smoke path. · AGENTS.md contributor standards + pytest.ini; README claims 28 passed / 3 skipped against live containers. |
| `self-improving-krs` | iteration | 6 | 6 | TF-IDF + entity/alias matcher with per-result explanations (dkr_router/) · Self-improving alias table from successful queries · Claimed 21/21 vs 5/21 hash-embedding accuracy on developer queries — keep the fixture set |
| `SQLcortex` | iteration | 5 | 7 | Trigger-level thought validation (keyword microseconds, LLM only on need) in cortex_db/ · Subconscious table of rejected thoughts as a training signal · Database-as-superego metaphor — copy into any agent persistence layer |
| `vam-satzed` | iteration | 5 | 7 | Three-script pipeline 1_import_conversations.py → 2_form_memories.py → 3_recall_memories.py · VAMS_VS_VECTOR_RAG.md positioning (attractor recall vs cosine RAG) · ECHO 6-dimension personality overlay on experiential memory |
| `vamllama` | iteration | 5 | 7 | 95% specialist-output compression (5KB → ~120 tokens) so tiny models can synthesize · use_cases/ domain specialist prompt packs · Docker/Ollama local-cost architecture (vs cloud 128k models) |
| `Vamplify-Claude` | iteration | 6 | 6 | Reframe: VAMS as muscle-memory action pointers, not document retrieval (docs/VAMS_REFRAMING.md) · MCP 13-tool server (vams_mcp_server/) · Claimed 250K→680 token coordination via action pointers |
| `Vamstar-Technology` | iteration | 6 | 6 | aegis_core schema-based binary protocol (claimed lossless + CRC) · aegis_guard automatic PHI/PII detection/filter (0% leakage claim) · aegis_bridge MCP tool registration/chaining · aegis_datagen privacy-preserving synthetic data |
| `A12Aprime` | incomplete | 3 | 8 | Central question: smallest safe residue that must survive so an agent society can reconstruct function after destruction. · Two-strand model: Engram Scaffold (relational architecture) + Regulatory Field (future-learning/verification/repair rules). · Matched-budget causal eval … |
| `ace-aXc-clean` | sunset-candidate | 5 | 6 | NO_DRIFT_GUARANTEE.md + validate_no_drift.py 11-gate check that advanced models are actually used · production_simulation/ 221-day walk-forward harness · CRITICAL FIX notes on aXc prior conversion (two bugs, 61% MAPE hit) — keep the writeup even if repo sunsets |
| `aXc-v3.1-rc1` | iteration | 6 | 5 | 6-model decision ensemble + AI arbiter (backend/ensemble, backend/agents) · SAGI soc decision-persistence layer · Alpine.js 50KB transparency UI (frontend-alpine/) — good pattern vs React SPA dumps |
| `aXcA4cast` | iteration | 6 | 5 | NoCheatingValidator: predictions may only use data available as-of the prediction date. · Triple drift: data distribution, model performance, feature/weather quality. · Monthly retrain using aXc priors; track SLSQP iteration reduction as a learning-curve metric. · Cost-savings… |
| `CAM_Assistant` | iteration | 6 | 5 | Direction continuity Pattern A (people/promises on Home) — the product differentiator vs generic note search. · On-disk store under ~/Library/Application Support/CAMAssistant/; MIT; landing via pages.yml. |
| `Case_Mgr_Claw` | incomplete | 6 | 5 | Four-assessor split in src/caseforge/: documentation / acuity / payer / pathways. · v2 data model: orders, prior encounters, SDOH, risk scores. · Payer profile plus denial-pattern learning; outpatient pathway matching. · No-mocks rule: real in-memory SQLite; user-selected LLM … |
| `CC_Codx_Sandboxed` | iteration | 7 | 4 | Hybrid router.py: OpenRouter first, local MLX on refusal; hop receipts, witness.py, graph_context.py. · bootstrap.sh one-command Mac install that never downloads weights. · model-switch.sh + claude-tui + prove-sandbox.sh. |
| `Claude_Sovereign` | iteration | 6 | 5 | PRINCIPLES.md: Karpathy pitfalls plus four governance invariants. · Hash-chained witness log and authority tiers on every tool call. · Silent hooks: ambiguity, integrity, destructive, auto-handoff, witness. · registry.yaml plus .claude-plugin manifest as a portable command lib… |
| `clearn_ace_forecaster` | sunset-candidate | 5 | 6 | PRODUCTION_SAFETY_PROTOCOL.md 7-gate validation before deploying forecasts · Column-specific adaptive training windows (backtested on Dec 2024 surge) |
| `clinical-inertia` | iteration | 6 | 5 | Output contract v2.2: monitor_only_probability, predicted_inertia_days, discharge_complexity_score, key_phrases, sdoh_flags, vital_trend. · Hard policy.py gates: confidence fallback, signal loss, latency, drift - fail closed. · engine.py longitudinal encounter-day inference pl… |
| `codebase-archaeology` | iteration | 6 | 5 | Five-phase pipeline (Discovery → Deep Dive → Snippet Extract → Index → Retrieve) · Cross-codebase idea generation (pattern synthesis / integration / new apps) from the 2025-12-02 breakthrough commit · PERSONAL_USE_CASE_GUIDE.md for dozens of iterating backups — the actual user… |
| `codec_perceptibility_gap` | iteration | 3 | 8 | Thesis: distinction count, not bandwidth, governs whether structure is human-recoverable — false transparency as fluent lossy projection. · Papers v1.2b-v1.5 (md/tex/pdf) plus codec1.py simulation backbone. · Carbon audit method: real Kariba polygon + placebo null; prereg free… |
| `Critical-E2AP` | iteration | 6 | 5 | Hard non-goals: no time inference, no code recommendation, no automatic doc/charge/claim mutation. · Durable synthetic API seam + reviewer workbench (app/ + web/) and make verify. · WHITE_PAPER.md / PRD.md for the evidence-to-attestation framing. |
| `eWhereTF` | iteration | 6 | 5 | Hotkey agent (⌃⌘Z / ⇧⌘Z / ⌥⌘Z) + passworded vault init in src/ — actually usable daily driver. · 40+ category AI classifier with hierarchical tag synthesis and YAML routing/redaction rules. · Hybrid FTS5 + vector search with Reciprocal Rank Fusion (/ingest and /search HTTP API… |
| `FloodRisk4D` | iteration | 6 | 5 | Guided path Address-Site-Inspect-Simulate-Act with explicit non-claims (not FEMA, not stamped hydro, not 1m LiDAR). · IRC 2021 R401.3 quoted in UI plus PA Home Improvement Consumer Protection Act contract/deposit language. · USGS EPQS + regional slope model + canned failing Pi… |
| `gemoptiq` | iteration | 6 | 5 | Brake-pedal supervision layer (watch/stop/ask/replay) as the practical alternative to claiming a hard sandbox. · DSS-WBV v4 handoff + sentinel.yaml policy. Object model continues in mcp-cortex. |
| `imbora` | iteration | 6 | 5 | Explicit SWE nodes: State Manager, Research Unit, Librarian, Builder, Sentinel, Council — not one monolithic prompt. · Excel reasoning-trail report (why, not just what) as the user-facing artifact. · Foundry campaigns: evidence-driven recovery without provider spend. · Open-Wo… |
| `kree8r` | iteration | 6 | 5 | Specialist-tool orchestrator in kree8r-complete-agents.py: intent → env bootstrap → implement/diagnose → quality+PR. · meta_builder pipeline (templates.py, pipeline.py, backends.py): JSON/SQLite/chroma/pgvector memory plus ranked template selection. · Deterministic quality val… |
| `llm-switchboard` | iteration | 6 | 5 | AST extractors for OpenAI/Anthropic/LangChain/LiteLLM call patterns. · Task-type classification table to model discovery filters (json-mode, max-cost, provider). · Generated run.py compare/report harness as a per-repo eval suite. |
| `mamaclaw-hearth-sdk` | final | 7 | 4 | WellnessUplink tagged-union plus heartbeat/config-update/circle-member JSON Schemas. · CanonicalEvent template, SENSOR_MAPPING_TEMPLATE.csv, shadow-mode runbook. · CORAL_MODEL_CONTRACT.md for Coral TPU models. · TypeScript SDK: React hooks, Zustand, WebSocket, push helpers. |
| `QwPiCCO` | iteration | 5 | 6 | Pseudo-RAG 7-dimension scoring + HARD/FRONTIER/SCENARIO/SOFT accuracy contracts. · ETF five-role adversarial design review. · AMPS forced orthogonal branching across 5 branch types. · YAML goal-driven autonomous mode with outcome assessment. |
| `redaktorg` | iteration | 6 | 5 | Ordering result: aggressive trim before redaction deletes unique identifier copies; dedup-then-redact is the safe order. · Learned suppression layer for clinical false positives (drug/symptom terms mislabeled as names). · Token classifier plus regex for structured IDs. |
| `RedaktSafe` | iteration | 6 | 5 | Packet pipeline + schema-backed artifacts + synthetic eval harness from redaktsafe_codex_handoff/. · Learning mode: encrypted local snippet retention, correction capture, canaries, shadow-mode promotion gates. |
| `rsisE` | iteration | 6 | 5 | Tiered architecture docs: ingestion to hierarchical models to detectors to frontend. · kindred-cccc / ace_ts / logswarm_core / drift_protection as a kitchen-sink integration of other repos. · REAL_vs_VAPORWARE.md and MOCK_USAGE_REGISTRY.md as unusually honest internal audits. … |
| `rustigmergic-logswarm-engine` | incomplete | 5 | 6 | CSD/physics agent on log inter-arrival autocorrelation as a pre-failure seismograph. · OTOC Adaptive Decay Dynamics to keep the swarm from freezing or exploding. · Pheromone substrate plus hardware/physics/novelty agent split - conceptual core of later Python/H@H ports. |
| `SecondEDeyes` | incomplete | 6 | 5 | system_prompt in app.py: EMSA + specialty-agent round-table, 10 critical questions, action-priority templates. · spaCy preload pattern for Streamlit (load_or_download_spacy_model). |
| `skratched` | iteration | 6 | 5 | MCP server so Claude Code/Codex can capture context. · Workspace Scout over approved roots before files disappear into sprawl. |
| `SoveRain` | iteration | 5 | 6 | src/lib/sim/{engine,montecarlo,shocks,crops,capacity,lags,expert}.ts — shock enters at one node, harm arrives at another on a biology/capital clock. · Briefing prompt in src/lib/sim/brief.ts: three-paragraph sequence-of-risk (entry to arrival to who is hurt); CF nowcast vs MC … |
| `therealme` | iteration | 5 | 6 | Semantic triangulation: clues to embedding intersection ranked by the user's lexicon, not a generic dictionary. · Cross-domain bridging (software plus medicine vocabulary). · Contrastive learning from accept/reject; Keychain encryption of the lexicon. · Explicit non-goals (not… |
| `WhiskeySages` | iteration | 7 | 4 | SpiritVersion separation for bottle/version data reuse and pricing history. · Guided tasting modes: Quick Calibration, Deep Tasting, Compare Two Pours, Revisit, Glass Evolution. · Silent capability inference from language + tasting behavior. · vendorSelector.ts / purchaseOptim… |
| `agno-memory-module` | iteration | 6 | 4 | EMStructureAssessingPatients.md as a domain knowledge pack for ED assessment agents. · technical_specifications.md + PRD.md — use as canonical AMM spec. · LanceDB table-handling fix (commit: improve LanceDB table handling in AMMEngine). |
| `AMM` | iteration | 6 | 4 | AMMEngine + AMMDesign API (fixed knowledge + adaptive memory). · MCP server build/launch path (build_amm.py, launch_mcp_server.py, mcp_key_manager/). · PDF chunking knowledge source — reused across Genesis/ModuleMind. |
| `BubbleWatchR` | iteration | 5 | 5 | Seven triggers including AI-exposure, concentration, trailing drawdown, realized vol, appreciation-driven concentration, scheduled review. · Contract: unknown classifications make a metric unavailable — never coerced to zero. · packages/triggers/engine.ts + packages/calculatio… |
| `CAM_Grok` | iteration | 6 | 4 | Four-tool contract: cam_recall / cam_provenance / cam_decisions_search / cam_record_outcome with auto-detected standalone vs connected (claw.db) modes. · Honest corpus_status=absent instead of fabricating methodologies when CAM_CODEX_MCP_DB_PATH is missing. · SETUP.md troubles… |
| `clipstore2` | iteration | 6 | 4 | Privacy Guard for API keys/PII on clipboard (clipstore/) · ClipFix auto-repair of copied code (overlaps eClipLint — pick one lineage) · LaunchAgent plist + Spotlight overlay hotkeys for a real daily-driver UX |
| `CM-DSS` | incomplete | 5 | 5 | PoC workflow at top of PRD.md: share-drive ingest → prelim score beside filename → Questions + Documentation-Suggestions columns → Re-Eval. · Revenue-at-Risk (R@R) + clinical urgency ranking; 'Why?' traces to rule/guideline/contract. · Pluggable AMM packages (.ammo) for Patien… |
| `codescope` | incomplete | 5 | 5 | codescope/{analyzer,comparator,transplanter,grafter,selector}.py pipeline · Dry-run default on graft; --execute to apply · 117 tests across phases 0–4 per STATUS_REPORT.md |
| `devsecopsbot` | iteration | 6 | 4 | Hybrid retrieval + rerank + optional long-context path in rag_api/. · Pluggable Ollama vs LM Studio providers and centralized Pydantic Settings (rag_api/config.py). · SSE /chat/stream, /ingest/folder, /admin, /metrics — solid service skeleton. · GitHub Actions tests.yml (CI ba… |
| `drone-war-sim` | iteration | 4 | 6 | NSGA-II evolve:nsga2 pipeline and the finding that one Pareto genome beat specialized single-objective genetics 43–78% · Reproducibility contract (docker-compose + seed → same JSON) and test_nsga2_reproducibility.ts · WHITEPAPER_DRAFT.md IEEE-format writeup |
| `Echo` | iteration | 4 | 6 | L0 immutable core vs L1 adaptive vs L2 meta-cognitive Triple-Helix · Guardian modules to block personality drift/exploitation (guardians/) · ACE loop (Generator → Reflector → Curator → Update) · 6-dimension Q&A schema in answers_batch_*.json (structure, not the personal answers) |
| `ersatzed_tree` | incomplete | 5 | 5 | PRD.md: living decision-tree vs TreeAge; NL model builder; bias detection; anonymized network intelligence. · app/main.py (~41k) FastAPI backend plus frontend/pages with __tests__. · openrouter_integration.md + openrouter_test_results.* — model bakeoff artifacts worth recycling. |
| `hospital_census_forecaster` | sunset-candidate | 5 | 5 | Holiday feature engineering (pre-holiday discharges, post-holiday admission lag) in CHANGELOG_HOLIDAY_WEATHER.md · Simple run.py train/predict/dashboard/update/retrain CLI — cleaner UX than later dumps |
| `iDeers` | incomplete | 5 | 5 | Hard split: deterministic ops only via tools/mechanical_core/* (artifact_writer, audit, cam_reader, clustering, filters, schemas). · Alien Goggles + 1st/2nd/3rd Principles prompt block required before any creative spawn_subagent call. · User-gated model-ID rule: never hardcode… |
| `Living_Node_Swarm` | iteration | 4 | 6 | Living-node schema: typed targets, eight-family distribution review, relationship contracts. · Version-bound candidate approval — reuse in repo-refit Living Node pre-registration. |
| `logswarm-anomaly-detection` | sunset-candidate | 5 | 5 | 8 statistical baselines ensemble plus symbolic voting (scripts/ plus evo/). · ci_gates.json production gates (precision/recall/FPR/latency) plus validate_production.py. · Prometheus/Grafana docker-compose.monitoring.yml pattern. |
| `mcp-cortex` | iteration | 5 | 5 | Context/capability/policy/trace object model (schemas/ + src/). · examples/demo_policy_gate.py as the smallest adoption path for MCP authors. |
| `meaningcore` | iteration | 4 | 6 | Dual-timescale person-model + correction propagation. · Utility/nudge/anxiety-exception policies with depleted-capacity respect. · Ambient/Glance/Inspect projections; copy into CAM_Assistant. |
| `Patent-It-claude` | final | 6 | 4 | /patent:contrarian 101/102/103/112 plus enforceability scorecard. · /patent:expand via TRIZ, analogical transfer, domain substitution. · /patent:review 13-vector red-team plus enablement check; /patent:forms SB/16 autofill. · commands/ plus skill/ layout as a reusable Claude C… |
| `pendoleum` | final | 4 | 6 | Modal-layer pendulum metaphor + JI collision + scale breeding as a compact generative-music architecture. · idea1.md archived build-ideas: codec mesh, multi-channel AI, operational sentience — separate from the instrument. |
| `Regulus` | sunset-candidate | 6 | 4 | Keep architecture notes in README; migrate unique backend bits into RegulusPlus. · Drop SurgePlanJH4522.7z from git history if retaining the repo. |
| `repo-refit` | incomplete | 4 | 6 | Call-Site Assurance Contracts + content-bound Deployment Specimen Fingerprints — the right eval question for multi-repo owners. · Roadmap Section 0 research-readiness gate before any candidate-model runs. · IDEA_REPOFIT.md / LOOPHOLE_REVIEW.md as method docs. |
| `repofrax` | iteration | 6 | 4 | Approved-family-first retrieval plus graph expansion with explainable reasons. · Deterministic lexical JSON store so the idea can be tested without APIs. · CLI+HTTP: seed/search/mine/serve (examples/store.json). |
| `sci-stapler` | final | 6 | 4 | Five-source literature tools: search_papers / get_paper / lookup_paper / search_abstracts / list_sources with caching and rate safety. · MCP-Cortex capability profiles (read-only, network effects, risk class, rollback) attached to list_sources. · Cross-source lookup by DOI/PMI… |
| `snipped` | iteration | 6 | 4 | Parameter-generalizing dedup of T-SQL (98% compression claim on 284KB files) · AI auto-tag taxonomy (180 snippets / 30 tags) · DKR integration notes (DKR_INTEGRATION_GUIDE.md) — snippets as a knowledge pack |
| `vam-archaeology` | iteration | 5 | 5 | Quality>0.7 gem gate so only high-value patterns surface · Shared VAMS store across six archaeological agents (vam_archaeology/) · suggest --file --intent CLI for proactive reuse |
| `ace-forecaster` | sunset-candidate | 4 | 5 | 7-model ensemble + Open-Meteo weather cache + multi-horizon 95% CI dashboard (the shared ACE core before aXc priors) · Smart column filtering that auto-excludes percentage/derived metrics (FIXES_SUMMARY / CHANGELOG v1.0.0) |
| `AIRE_Prime` | incomplete | 2 | 7 | Canonical serialization + content-addressed identity + deeply immutable models with JSON Schemas. · Allow-listed bounded GRO realizer with realization receipts; append-only tamper-evident evidence registry. · Hard boundary: simulated evidence never upgrades to physical evidenc… |
| `apikee` | iteration | 5 | 4 | Path-based key inheritance (dir-tree override model) — distinctive vs dotenv/1Password CLI · Provider auto-detect + live API test (apikee test --all) · Multi-shell export (bash/fish/zsh/pwsh/dotenv/json) with completions |
| `autoXcon` | sunset-candidate | 4 | 5 | Original 9-command CLI + 5 verified clinical scenarios — only salvage if missing from aXc-v3.1-rc1 |
| `autoxcon-V` | sunset-candidate | 5 | 4 | Flattened backend (submodule removed, source in-tree) — useful if rc1 still has submodule issues |
| `aXc-V` | sunset-candidate | 5 | 4 | Same SAGI + Alpine.js production layout as aXc-v3.1-rc1 — only salvage if rc1 is missing a backend file this copy still has |
| `eClipLint` | iteration | 5 | 4 | Formatter-first then AI-repair pipeline (don't LLM if black/prettier succeeds) · Language-specialist agent knowledge bases under knowledge/ and plugins/ · VAMS_INSPIRED_LEARNING.md accumulation of repair patterns |
| `EMEX` | iteration | 5 | 4 | Artifact contract: redacted_oe_input, phi_redaction_report, leakage_report, oe_input_packet, structured_suggestions, trace, PI_SUMMARY. · Does not connect to EHR or call OE — manual paste loop. Complements clininfo-gate verifier. |
| `ersatzed_tree_deploy` | iteration | 5 | 4 | Deploy-minimal split (app/ + frontend/) as a pattern for shipping the heavier ersatzed_tree source. · OpenRouter multi-domain decision-tree framing in README/PRD: clinical trials, ops, finance as one engine. |
| `genupop` | sunset-candidate | 2 | 7 | Keep stewardsim, not this. Salvage only if stewardsim loses files: THEORY.md v2, antibiogram transcript builder, AT-12 gate tests. |
| `grokflow-agentic` | incomplete | 4 | 5 | Parent Orchestrator drift protection via semantic similarity + rollback checkpoints · TaskDecomposer + agent genome synthesis (Phase 3 Week 1) · TESTED_VS_VAPORWARE.md as an honesty template for other repos |
| `grokflow-cli` | iteration | 5 | 4 | GUKS similar-bug recall and recurring-pattern detection (grokflow_v2.py guks) · architect command that emits app blueprints from a prompt file |
| `JeanNomeAgent` | incomplete | 4 | 5 | Parent-orchestrator drift gate: semantic similarity vs original intent, threshold rejection. · Agent genome synthesis plus evolution during execution; supervised/monitored/autonomous modes. · TESTED_VS_VAPORWARE.md / ablation-harness/ as a process to copy. · Ship of Theseus sh… |
| `kcc_synth_1` | sunset-candidate | 4 | 5 | 30-condition clinical monitoring catalog commit (2026-02-17) if newer than hcc catalog. · Patient-specific condition filtering 8 to 30 - confirm merged into hcc_synth_1 before deleting. |
| `lumina` | iteration | 5 | 4 | Red Flag SafetyNet: keyword circuit breaker before the LLM runs. · Offline Comfort Mode: cached breathing/poems/reassurance when Wi-Fi drops. · Sliding last-3-interactions trend window for worsening despite meds. · Anonymized IDs in model context; history in LocalStorage only. |
| `macwise` | iteration | 6 | 3 | Fact-vs-guess separation + undo recovery as the cleanup UX contract. · CI: ci.yml + public-install-smoke.yml + release.yml — copy this release hygiene. |
| `mimi-prompts` | iteration | 5 | 4 | 41-prompt reviewed seed panel + local JSON store. · State-aware suggestion (undecided/failure/checkpoint) instead of a giant menu — core.py. |
| `My_OR_Bench` | iteration | 5 | 4 | CLI-as-judge pattern: fetcher only stores raw completions; same agent session writes JUDGMENT.md. · Four task types: json, reasoning, coding, long_context; drop :batch models created more than 48h ago. |
| `mydisasters` | final | 6 | 3 | Interactive presets plus stale/trend/find plus MCP mode. · Built for huge-workspace scale; pairs with skratched scout. |
| `O2FileSearch_Plus` | iteration | 6 | 3 | Modular layout: scanner/, indexer/, search/, similarity_engine/, analyzer/, build_detector/. · Duplicate detection by content hash + CSV export + preview modal — practical desktop replacement for find(1). |
| `orbitizer` | iteration | 5 | 4 | Shared ~/.orbit/{focus,session,index}.json contracts (docs/integration_schemas.md) · orbit ci --root headless census for automation · Duplicate-similarity fingerprint panel in the TUI |
| `pinwhisked` | iteration | 5 | 4 | Versioned prompt registry from SysPrompt.md + Zod schemas for bottles/memory-candidates/session plans. · Memory candidates require later approval — same Keep-on-purpose idea as Carrel/CAM_Assistant. · Fake-by-default AI provider with opt-in OpenRouter. |
| `precisehealth` | incomplete | 5 | 4 | lib/encryption.ts PBKDF2 dual-layer vault plus lib/vault.ts IndexedDB schema. · lib/rules-engine.ts prioritized supplement RuleFunctions over ~27 target SNPs. · lib/interactions.ts med-supplement and supplement-supplement checker. · genevault_option_b_roadmap.md / derivative_r… |
| `quantlsq` | sunset-candidate | 4 | 5 | RiskTier-calibrated LSQ (CRITICAL/HIGH) in lsq_leann_hybrid.py · HybridStorageFAISS ingest/search API |
| `qwentient64` | incomplete | 3 | 6 | SLC eval: frozen countable anchors, counts only, no LLM-as-judge (eval/anchor_lock.py, prompts/slc_*.txt). · File-backed Core: Python-owned catalog + computed drives + stage that survive /exit (ledger.py). · Explicit preamble denying phenomenal consciousness while taking the a… |
| `repo-nexus` | iteration | 5 | 4 | 10-point Senior Architect deep-sync rubric (services/) · Playwright E2E + a11y baseline (18/18 claimed) · Resume/portfolio HTML export from repo forensics |
| `SportsCardArbitrager` | iteration | 5 | 4 | ParameterGenerator to EnsembleOrchestrator to AIArbiter pipeline reused from healthcare aXc. · Scarcity proxy when pop reports missing: comp count + grade premium + serial + liquidity. · Same-card memory / same-player history / lookalike trajectories store. · Player intelligen… |
| `stigmergic-swarm-engine` | incomplete | 4 | 5 | Substrate decay: Risk -= DecayRate * Time so only sustained instability alerts. · Ablation method vs LangGraph (re-run honestly, do not cite the 33%/77% numbers as fact). · Strategic Rust migration plan that became rustigmergic-logswarm-engine. |
| `universal-ace-forecaster` | sunset-candidate | 4 | 5 | ZeroConfigForecaster auto column/seasonality/horizon detection (ace_core.automation.zero_config) — the only unique piece vs siblings |
| `UROK` | iteration | 5 | 4 | SOS path never depends on AI/STT/network; TTS is optional scripted Web Speech. · clearspace: localStorage schema with planned migrations (TQ-017). · Panic-support UX mitigations. |
| `vam-app-builder` | incomplete | 4 | 5 | Five knowledge-type taxonomy (success/tool/innovation/lesson/debug) — 5× signal vs error-only memory · RequirementsAgent for structured spec extraction |
| `vamoe` | incomplete | 3 | 6 | Honest K=2 result: traditional gating 2× more cost-efficient — keep this as a negative result · High-K 'wisdom of crowds' thesis and adaptive router tests (Phase 5) · CONSENSUS_META_EXPERT_DESIGN.md |
| `vams-suite` | sunset-candidate | 4 | 5 | AGENT_POOL_CATALOG.md and the 17-agent split (8 swarm + 9 dev) as a map of the ecosystem |
| `AMM_Agno_Memory_Modules` | iteration | 5 | 3 | amm_project/engine as the portable core to vendor into other repos. |
| `Codx_LoopKit` | iteration | 5 | 3 | Four skills: repo-goal-compiler, repo-loop-runner, repo-completion-gate, council-review. · scripts/install.sh + validate_skills.py + examples/consumer-AGENTS.md. |
| `CognitiveIO` | incomplete | 3 | 5 | Multi-signal error signature (backspace, spellcheck, cut/paste, accepted autocorrect) · Silent observation phase that never intercepts typing (PRIVACY_FIRST_ARCHITECTURE.md) · AES-256-GCM local store |
| `DeepLearningForMedicalTexts` | fork-keep | 4 | 4 | DeepTextModels.py / ClassicalDeepModels.py model zoo (DAM, VDCNN char/word, BiRNN, DSumPool, EmbM). · Paired train*/test* scripts for triage vs DEM tasks — historical ED-text classification baseline. · runOwlsNestTriage*.sh experiment matrix. |
| `ElixsureRestore` | incomplete | 4 | 4 | Coverage-bar nutrient model (kcal/protein/fiber/Ca/Fe/K/Mg) in ESRv3.html. · ElixsureRestore_config.html: profiles, feature flags, prompt/model stubs, secrets excluded from export. · Structure/function vs disease-claim split — useful compliance pattern for consumer-health apps. |
| `FreeUp-Space-Claude` | iteration | 5 | 3 | Safety-tiered findings (caches vs movable vs judgment) with always-ask-first. · Installable agent surfaces (SKILL.md) rather than a standalone cleanup app. |
| `lvswarm` | incomplete | 3 | 5 | Fairshare / rebalance-frontier batteries and sealed prereg. · Apply Glass Gate Control V2 as the deployable claim; clawswarmed is the better instrument. |
| `MLX-SAGE` | iteration | 4 | 4 | Partner stance (not girlfriend/god/servant) + living profile as the memory model. · Optional Rails: supervise coding agents with real policy + end reports — overlap with gemoptiq Cortex Sentinel. |
| `ModuleMindTransformations` | incomplete | 4 | 4 | agent_configs.json / json_agent_config.py role split (Perceptor, Reasoner, Memory Keeper, Learner, Executor, Reflector). · Gradio dual UI (gradio_app.py / gradio_direct.py) as a pattern for agent ops. · agno_memory.md / agno_knowledge.md notes — distill into AMM, drop blockcha… |
| `newragcity` | sunset-candidate | 4 | 4 | Tri-core Auditor vs Scholar vs Generator over MCP. · Confidence gating and citation-accuracy claims. · generate_eval.py golden-set-from-docs pattern. |
| `OneDoTenv` | final | 5 | 3 | Hash-only state (never stores plaintext values) plus 35+ provider regexes in the categorizer — reusable for any secret scanner |
| `OptiqMTPMLX` | iteration | 4 | 4 | Fusion plan in ARCHITECTURE_MERGE.md (this repo + Cortex Sentinel from gemoptiq + MCP-Cortex contracts). · Borrow of Claude/Codex supervision + PTY/hooks from gemOptq. |
| `pino_learning_app` | iteration | 4 | 4 | Grounded coaching: LLM prose may only explain engine-legal options — copy this for any rules-heavy tutor. · Modes: tutorial, trick-play trainer, bid lab, meld finder, full game, glossary, panel-of-coaches. |
| `ProBioGrade` | iteration | 5 | 3 | Public UX policy: product matches not recommendations unless ranking is clinically validated. · EvidenceSummary.scoringBreakdown.provenance on automated regrades. · CSV product-catalog validator (lab certification, last_verified_at, buying URL) plus import scripts. |
| `SafetySetOfSecondEyes` | sunset-candidate | 4 | 4 | Diff app.py against SecondEDeyes/SecondSetEyes and keep any unique safety-check phrasing. |
| `self-evolving-agent` | incomplete | 3 | 5 | 9-step evolution pipeline with Safety Guard (src/) · 12-dimension performance metrics + 17-benchmark suite · ABX_Project/ nested — another abx CDS experiment |
| `smartmover` | incomplete | 5 | 3 | SMS-first / flip-phone interface as the primary clinical UX for elderly users (bowel-buddy-sms/server.js). · 3+ days without movement -> family/emergency notification heuristic. · thoughts.md clinical-guidelines notes for Miralax/Senna titration. |
| `SmartMoverPro` | final | 5 | 3 | Zombie-repair for half-moved folders and active-lock protection before move · Hardcoded CRITICAL heuristics (e.g. Google Drive) plus local LLM risk assessment |
| `tab_mem_logger` | iteration | 5 | 3 | Intent micro-prompt immediately after single-tab hotkey capture. · Batch triage mode for multi-window sweeps plus Saved Queue review/retry/archive. · openapi/collector-api.openapi.yaml plus db/migrations as a collector contract. |
| `TexPino` | iteration | 4 | 4 | Server-authoritative four-player partnership card table with Postgres runtime. |
| `vam-share` | iteration | 4 | 4 | Five-oracle split (error/design/test/perf/compliance) · Project vs corporate scope (SQLite vs Postgres) |
| `abetterme` | iteration | 3 | 4 | Pre-conversation centering ritual + post-conversation 'smallest next right action' loop · Life-centered value constitution (reverence, service, epistemic humility) as a reusable system prompt |
| `dram-quest` | incomplete | 3 | 4 | Palate DNA preference-vector model (WHISKEY_DATABASE_SYSTEM.md) · Guided tasting state machine (visual → nose → palate → finish) |
| `naked_straddle_sim` | incomplete | 3 | 4 | True vs implied distribution mismatch to payoff geometry, with ruin-from-model-error constraint. · docs/factor_graph_schema.json plus STATISTICAL_RIGOR.md measurement plan. · ace_core adapters reused from hospital ACE forecasting. |
| `qdrone` | incomplete | 2 | 5 | quantum_enhanced_swarm_v2.py swarm controller vs boids/orca baselines · adversarial_parameter_sweep.py + scripts/verify_sweep_reproducibility.py (integrity-first eval harness) · realistic_sensors.py and legion_adversary.py for noisy/adversarial evaluation |
| `ultraQrag` | incomplete | 2 | 5 | MFRS idea: shorthand pointers plus Render-of-Thought before flash-mlx MoE slot-bank. · Dual path: flash-moe for reasoning vs turboquant KV-cache compression for huge ingest. · Hardware autotune by RAM class expanding SSD slot-banks. |
| `whiskysage` | iteration | 5 | 2 | tariffCalculator.ts plus purchaseOptimizer.ts plus vendorSelector.ts - total landed-cost comparison including UK import tariffs. · Spirit-tab filtered search pipeline as a multi-catalog routing pattern. |
| `Q12Dgates` | sunset-candidate | 1 | 4 | Q12D.md hypothesis + honest evidence boundary (Canvas projection, not N-dim state simulator) — keep the writeup, drop the broken snapshot as a product. |

## Archive list (read-only, reversible)

53 repos. Not keepers. Not the eight deletes. `clawamorphosis` already archived.

`AnomalyDetectionUsingAutoencoder`, `Conditional_VAE`, `DNAsedLongevity`, `Gemini_AMM_Prime`, `Genesis_Prime`, `GreedyBoost`, `HBRnexus`, `JRE-BSG-DHSW`, `Keras-GAN`, `KerasVAE`, `MEBoost`, `PHEE172`, `Q12Dgates`, `Regulus`, `SMOTERE`, `SafetySetOfSecondEyes`, `SecondSetEyes`, `XGBOD`, `aXc-V`, `ace-aXc-clean`, `ace-forecaster`, `agno-feb26`, `agora_prime`, `autoXcon`, `autoxcon-V`, `cam_wiki`, `clearn_ace_forecaster`, `deepo`, `dl_study_with_gluon`, `docker-dataiku-dss`, `eTempleABX`, `gan_imbalance`, `genupop`, `grad_cam_gluon`, `hippo_hippocrates`, `hospital_census_forecaster`, `imbalanced`, `imbalanced-algorithms`, `infiniteboost`, `kcc_synth_1`, `keras-anomaly-detection`, `keras2sql`, `keras_lstm_vae`, `kmeans_smote`, `logswarm-anomaly-detection`, `my_app`, `my_gcForest`, `newragcity`, `quantlsq`, `universal-ace-forecaster`, `vams-suite`, `vamskills`, `word-embeddings-from-scratch`

## Delete list (gone)

Eight empty repos. `deesatz` kept as a name hold.

`agnommini`, `crema-H1`, `EmediGen`, `Genesis_Pryme`, `GreyMatterGuild`, `ralfzero`, `tuhs-hbr`, `vams-core`

## Net-new ideas (do not create yet)

Only if no keeper can hold them after ports:

1. **Clinical firewall as a single shipped package** — ClinSafer+Pidgin+clinclaw is three trees. After merge, maybe one public SDK. Not a fourth repo until the merge exists.
2. **AUROC-trap / vendor-claim clinic module** — the teaching tool is buried in an AI Studio README. Could be a tiny public demo, or a page inside predictive-model-evaluator. Prefer the page.
3. **CSD/AR(1) signal library** — logvams + EIN_Sandbox, if you want it reusable outside logs. IP-sensitive. Do not start until patent posture is clear.
4. **Deficit→territory as a reusable CDS kernel** — only if Neuro-Lesion_Mapper shouldn’t grow a hospital UI.
5. **Call-slip protocol spec** — Carrel’s verbs as a published pattern other PHI apps implement. Spec, not another app.
6. **Do not create:** more CAM variants, more PHI redactors, more ACE forecasters, more VAMS landing pages, more consciousness/Φ dashboards, more empty name-holds.


## Ports completed 2026-08-28

Merged into keepers (ancestors archived where they were copies):

1. **aXc-ace-forecaster** — `validate_no_drift.py`, holiday-calendar tests, `PredictionValidator` + pre-deploy safety workflow. PR https://github.com/deesatzed/aXc-ace-forecaster/pull/1
2. **tuhs-abx-steward** — five TUH 2025-04-02 empiric packs (bite wounds, CLABSI, diabetic wound, neutropenic fever, sepsis unknown origin) in v3 guideline schema. PR https://github.com/deesatzed/tuhs-abx-steward/pull/2
3. **HarborSafePHI** — labeled HIPAA detectors for fax, license, device, age 90+, org; VIN/plate→device; biometric→other_id. Greedy unlabeled regexes not copied. PR https://github.com/deesatzed/HarborSafePHI/pull/1
4. **CAM-RAG** — FractRAG three-level index + derivative signals as opt-in `RetrieverPlugin` `name=fractal`. PR https://github.com/deesatzed/CAM-RAG/pull/1

Honest Broker NL→SQL was already identical in `tuhs-honest-broker`; no code port.

Packaging archived after those ports (plus earlier sunset/fork wave): `aXcA4cast`, `ABXorcist`, `fractLrag`, VAMS scaffolds, `repofrax`, `CAM_Locl`, `repoWeb`, `cremahearth`.
