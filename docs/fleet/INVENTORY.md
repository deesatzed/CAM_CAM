# deesatzed GitHub inventory

Scored 2026-08-28 from GitHub metadata, READMEs, root trees, and recent commits. No clones, nothing executed. Scores discount README “production-ready” badges when the tree doesn’t back them up. Four scoring passes, so treat a 1-point difference as noise.

Scale: **0–10**. **C** = completion, **U** = real utility (to you or other repos), **N** = novel concepts worth stealing. **U+N** is the keep-or-fold ranking. Status is a judgment call: `final` / `iteration` / `incomplete` / `sunset-candidate` / `fork-keep` / `fork-drop`.

## Fleet

- **257 repos** · 129 private · 128 public · 23 forks · 1 archived (`clawamorphosis`)
- Mean scores: completion **5.0**, utility **4.4**, novelty **4.2**. Nothing is a 9–10 “other people depend on this in production.” Ceiling is 8.
- Status: 136 iteration · 45 incomplete · 42 sunset-candidate · 21 fork-drop · 11 final · 2 fork-keep
- Languages: mostly Python, then TypeScript. A 2017–18 ML-fork graveyard sits under the 2025–26 clinical/agent work.

## How to use this

1. **Canonical keepers** below are the tips of duplicate lineages. Build there.
2. **Sunset / fold** are copies, empties, hype, or superseded snapshots. Archive (don’t delete until you pulled salvage).
3. **Salvage** is methods, not repos. Port the idea, then sunset the ancestor.
4. Full sortable grid: `inventory.csv`. Machine-readable: `inventory.json`.

## Canonical keepers (build here)

These are the tips of each lineage. Scores are C / U / N.

| Group | Keep | C | U | N | Why | Fold into it |
|---|---|---:|---:|---:|---|---|
| Repo intelligence | CAM_CAM / CAM-Pulse | 8 | 8 | 7–8 | Local GraphRAG rescue desk + mine→build→bandit engine. Your multi-repo workflow already depends on this. | clawamorphosis, cam_wiki, iDeers, CAM_Grok as satellites |
| Clinical safety stack | ClinSafer + clinclaw-firewall + Agent_Pidgeon | 7 | 8 | 8 | JRE/MUD/CLEAR/Black Swan caps, then Pidgin receipts, most-restrictive-wins. | JRE-BSG-DHSW |
| Hospital-at-Home | hcc_synth_1 + mamaclaw | 8 / 7 | 8 | 8 / 7 | 40-dim field, Bayesian falsifiers, alert-fatigue, 61-rule/73-cue tables, Hearth SDK. | kcc_synth_1, logswarm-anomaly-detection, rustigmergic-logswarm-engine |
| PHI airlock | HarborSafePHI, Carrel, redaktR | 7 | 8 / 7 | 6–7 | Browser PDF de-id; call-slip receipts; 4-technique PHI consensus. Do not start a fourth product. | HC_PII_REDACT_MCP as MCP surface; redaktorg/RedaktSafe if they exist as kernels |
| TUHS ABX CDS | tuhs-abx-steward + TUHSabxGuide | 7 | 8 | 6 / 5 | Institutional JSON + renal/allergy/culture workflow. DKR knowledge packs ride along. | eTempleABX, ABXorcist extras |
| Honest Broker | tuhs-honest-broker | 7 | 8 | 6 | Real HIPAA research-governance portal. Steal NL→SQL 5-layer validation from HBRnexus first. | HBRnexus, empty tuhs-hbr |
| Census forecast | aXc-ace-forecaster | 7 | 7 | 7 | Canonical 7-model ensemble + aXc priors + no-drift gates. | hospital_census_forecaster → ace-forecaster → clearn → universal → ace-aXc-clean |
| Neuro localization | Neuro-Lesion_Mapper | 7 | 7 | 7 | Deficit→territory rules engine (~50k engine.py) with tests and AI fallback. | — |
| Stewardship sim | stewardsim | 6 | 6 | 8 | Min-regret empiric policy under unknown resistance + non-random adherence. Unique EM+SWE. | genupop |
| Agent memory | VAMS | 7 | 8 | 8 | Sparse Hopfield core; ~20 repos import it. One library, one MCP surface. | vams-core (empty), vams-suite, vamskills, Vamplify-Claude/vamllama as adapters |
| Genomics | eMedGen / DNAsed | 7 | 7 | 6 | Local Rust parser, data diode, Fly only sees abstracted output. Same product idea, two trees — pick one name. | EmediGen (empty), DNAsedLongevity |
| Policy RAG | ersatz_rag / RegulusPlus | 6–7 | 7 | 6 / 5 | deepConf 0.80 gate, versioned retrieval. Prefer the small RegulusPlus tree. | Regulus (38MB + .7z) |
| ED tools | ed-healthcare-alert-web, ED_Dispo_SDM, SecondEDeyes | 7 / 7 / 4 | 8 / 7 / 6 | 5 | ID-alert desk, SDM NodePack wizard, second-look prompt. | SecondSetEyes, SafetySetOfSecondEyes |
| Geospatial | EmberScape, FloodRisk4D, SoveRain | 5–6 | 5–6 | 5–6 | WUI ember-cast, flood, rain. Small family, no duplicates to fold. | — |

## Salvage (methods, not repos)

Highest-leverage things to copy into the keepers:

1. **Sparse Hopfield action memory** — `VAMS` MemoryRouter + typed PMI edges + energy-conflict. Distinctive IP.
2. **Most-restrictive-wins autonomy firewall** — ClinSafer JRE/Black Swan → Agent Pidgin receipts → `clinclaw-firewall`.
3. **PHI UX contract** — Carrel’s verbs (ask the packet / call slip / receipt) + HarborSafePHI “PDF never leaves the browser” + redaktR consensus timings.
4. **AUROC trap → workload** — `predictive-model-evaluator` (`AUROCTrap.tsx`, vendor-claim → FP:TP). Unique EM teaching tool.
5. **Warranted-yet / VOI** — `sentinel_arbiter` + `ClinicalAiForensics` uncertainty budget. Gate any CDS agent with this.
6. **Min-regret stewardship loop** — `stewardsim` THEORY.md (individual empiric choice → pathogen pop → next clinician optimum).
7. **Neuro deficit→territory engine** — `Neuro-Lesion_Mapper` `engine.py` + `validate_rules.py`.
8. **AR(1) / critical slowing down** — `logvams` PhaseMonitor + `EIN_Sandbox`. Treat `logvams` PATENT_DISCLOSURE as IP, not a blog post.
9. **Atoms-of-Thought eval** — `VAAS` Decomposer/Verifier/Scorer as a gate on AutoXcon/ABX agents.
10. **CAM-PULSE mine→bandit→defense-chain** — already in CAM-Pulse; don’t rebuild in a fifth CAM repo.
11. **Institutional ABX packs + dose-by-indication** — DKR JSON + tuhs-abx-steward. PharmD-gated, not fully autonomous.
12. **HBRnexus NL→SQL 5-layer validation + PHI exclusion list** — port into tuhs-honest-broker, then sunset HBRnexus.
13. **fractLrag multi-scale index** — +10.4% MRR claim; small enough to port into CAM-RAG.
14. **codec_ceiling / perceptibility-gap / Glass Gate** — research thread (symbolic descriptions lose information; minority-signal metric). Not a product; don’t let it spawn more dashboards.

## Sunset / fold / drop

**63 repos** in this bucket. Archive after salvage. Empty ones can be deleted.

### Empty (delete or ignore)

`agnommini`, `crema-H1`, `deesatz`, `EmediGen`, `Genesis_Pryme`, `GreyMatterGuild`, `ralfzero`, `tuhs-hbr`, `vams-core`

### Superseded copies (fold, then archive)

- ACE census: `hospital_census_forecaster`, `ace-forecaster`, `clearn_ace_forecaster`, `universal-ace-forecaster`, `ace-aXc-clean` → **aXc-ace-forecaster**
- AutoXcon: `autoXcon`, `aXc-V`, `autoxcon-V` → **aXc** / medical-autoXcon
- Honest Broker: `HBRnexus`, `tuhs-hbr` → **tuhs-honest-broker**
- ABX: `eTempleABX` → **tuhs-abx-steward** / **TUHSabxGuide**
- VAMS dumps: `vams-core`, `vams-suite`, `vamskills` → **VAMS**
- CAM: `clawamorphosis`, `cam_wiki` → **CAM-Pulse** / **CAM_CAM** / **CAM_Assistant**
- JRE: `JRE-BSG-DHSW` → **ClinSafer**
- H@H v0: `kcc_synth_1`, `logswarm-anomaly-detection` → **hcc_synth_1** / **anonobit**
- Stewardship: `genupop` → **stewardsim**
- Genomics stubs: `EmediGen`, `DNAsedLongevity` → **eMedGen** / **DNAsed**
- RAG: `newragcity`, `Regulus` → **CAM-RAG** / **RegulusPlus** / **ersatz_rag**
- Second-look: `SecondSetEyes`, `SafetySetOfSecondEyes` → **SecondEDeyes**
- Compressor ancestor: `quantlsq` → **redLTcMed**

### Consciousness / hive-mind hype

`PHEE172`, `hippo_hippocrates`, `Genesis_Prime`, `Gemini_AMM_Prime`, `agora_prime`, `Genesis_Pryme`. Keep AMM engine pieces if you still want them (`AMM`, `agno-memory-module`); drop the Φ dashboards.

### 2018 personal ML toys

`imbalanced`, `gan_imbalance`, `SMOTERE`.

### Fork-drop (unmodified 2017–18 teaching forks)

`AnomalyDetectionUsingAutoencoder`, `Conditional_VAE`, `GreedyBoost`, `Keras-GAN`, `KerasVAE`, `MEBoost`, `XGBOD`, `agno-feb26`, `deepo`, `dl_study_with_gluon`, `docker-dataiku-dss`, `grad_cam_gluon`, `imbalanced-algorithms`, `infiniteboost`, `keras-anomaly-detection`, `keras2sql`, `keras_lstm_vae`, `kmeans_smote`, `my_app`, `my_gcForest`, `word-embeddings-from-scratch`

Fork-keep: `DeepLearningForMedicalTexts` (OwlsNest-era ED NLP baseline, archive not revive), `sports-card-tracker` if you still use it.

## Scores by family

Every repo, grouped. Sorted by U+N inside each family.

### Clinical / EM / PHI (64)

| Repo | Vis | Lang | Pushed | C | U | N | Status | What it actually is |
|---|---|---|---|---:|---:|---:|---|---|
| [hcc_synth_1](https://github.com/deesatzed/hcc_synth_1) | priv | Python | 2026-02-28 | 8 | 8 | 8 | iteration | Stigmergic Clinical Monitor: Hospital-at-Home event labeling with a 40-dim patient field, Bayesian falsifiers, 6-control alert-fatigue en… |
| [clinclaw-firewall](https://github.com/deesatzed/clinclaw-firewall) | priv | Python | 2026-05-28 | 7 | 8 | 8 | iteration | Local-first clinical autonomy firewall that pipes every proposed action through ClinSafer (JRE/Black Swan/tier cap) then Agent Pidgin (se… |
| [ClinSafer](https://github.com/deesatzed/ClinSafer) | pub | Python | 2026-05-08 | 7 | 8 | 8 | iteration | Judgment Readiness Engine: noisy-observation intake, JRI/MUD/CLEAR/Black Swan autonomy caps, disposition-justification not diagnosis. |
| [mamaclaw](https://github.com/deesatzed/mamaclaw) | priv | Rust | 2026-04-14 | 7 | 8 | 7 | iteration | HelpMomClaw: Hospital-at-Home / dementia Life360 stack - Rust edge hub, 61-rule tables, 73 cue templates, Hearth integration, wrapping th… |
| [aXc-ace-forecaster](https://github.com/deesatzed/aXc-ace-forecaster) | priv | Python | 2026-01-01 | 7 | 7 | 7 | iteration | Latest hospital-census 7-model ensemble (Chronos+SARIMAX+ARIMA+XGBoost+Ridge+DOW+Naive) with SLSQP weights, weather features, aXc Bayesia… |
| [HarborSafePHI](https://github.com/deesatzed/HarborSafePHI) | pub | TypeScript | 2026-08-26 | 7 | 8 | 6 | iteration | Browser-only MyChart/Epic PDF de-identifier (parse, detect, redact, optional OpenMed) before a user shares reviewed text with an external… |
| [Neuro-Lesion_Mapper](https://github.com/deesatzed/Neuro-Lesion_Mapper) | priv | Python | 2025-08-23 | 7 | 7 | 7 | iteration | Rule-based neuro-deficit → brain-region/vascular-territory engine (engine.py ~50k) with CLI, GUI, pytest, OpenAI parse fallback, and KB-f… |
| [redaktR](https://github.com/deesatzed/redaktR) | priv | Python | 2025-09-08 | 7 | 8 | 6 | iteration | Healthcare PHI redaction product: parallel regex+SpaCy then mandatory MLX LLM double-check, consensus voting, shipped as REST, MCP, folde… |
| [tuhs-abx-steward](https://github.com/deesatzed/tuhs-abx-steward) | pub | Python | 2025-10-09 | 7 | 8 | 6 | iteration | Public TUHS antibiotic CDS: 11 Agno agents loaded from real institutional guideline JSON, allergy trees, dosing-by-indication, Fly.io dep… |
| [tuhs-honest-broker](https://github.com/deesatzed/tuhs-honest-broker) | priv | Python | 2025-12-04 | 7 | 8 | 6 | iteration | AI-augmented HIPAA Honest Broker portal: schema-driven intake, email→draft GPT parser, risk scoring, cryptographic email approvals, FastA… |
| [Carrel](https://github.com/deesatzed/Carrel) | pub | TypeScript | 2026-08-27 | 6 | 7 | 7 | iteration | Private in-browser desk for a packet: ask only the pages in front of you; anything that leaves requires a call-slip with identifiers stru… |
| [deterministic_knowledge_retrieval](https://github.com/deesatzed/deterministic_knowledge_retrieval) | priv | Python | 2025-10-13 | 6 | 7 | 7 | iteration | Vector-free multi-domain RAG: TOC/Loader/Verifier agents, TF-IDF routing, lossless citations, plus a library of TUHS antibiotic JSON know… |
| [predictive-model-evaluator](https://github.com/deesatzed/predictive-model-evaluator) | pub | TypeScript | 2025-10-30 | 6 | 7 | 7 | iteration | Clinical-ops simulator that translates vendor AUROC/sens/spec into PPV, FP:TP workload, and an 'AUROC trap' warning at realistic prevalence. |
| [stewardsim](https://github.com/deesatzed/stewardsim) | pub | Python | 2026-08-14 | 6 | 6 | 8 | iteration | Individual-level hospital antimicrobial-stewardship simulator that searches for min-regret empiric policies across unknown resistance mec… |
| [ed-healthcare-alert-web](https://github.com/deesatzed/ed-healthcare-alert-web) | priv | Python | 2025-04-27 | 7 | 8 | 5 | iteration | Flask/Gunicorn 'ID Alert Web' for ED infectious-disease advisories: dashboard, admin, PDF/MD upload with AI field extraction, OpenRouter … |
| [ED_Dispo_SDM](https://github.com/deesatzed/ED_Dispo_SDM) | priv | Python | 2026-05-28 | 7 | 7 | 6 | iteration | 6-step ED shared-decision wizard: operational metrics + non-PHI scenario -> Tavily evidence -> OpenRouter NodePack extraction -> clinicia… |
| [eMedGen](https://github.com/deesatzed/eMedGen) | priv | C++ | 2026-08-23 | 7 | 7 | 6 | iteration | DNAsed: privacy-first genomic health platform — local Rust parser, Tauri companion, Fly cloud API for abstracted clinical outputs; raw DN… |
| [TUHSabxGuide](https://github.com/deesatzed/TUHSabxGuide) | priv | TypeScript | 2025-09-25 | 7 | 8 | 5 | iteration | Next.js 15 / Prisma clinical CDS that walks TUHS clinicians through antibiotic choice (allergies, cultures, source, renal) with confidenc… |
| [AdmSVE](https://github.com/deesatzed/AdmSVE) | pub | Python | 2026-06-02 | 6 | 7 | 6 | iteration | Phase-1 synthetic admission-status engine: clinician FastAPI workflow that redacts PHI, round-trips OpenEvidence prose, and scores inpati… |
| [careframe](https://github.com/deesatzed/careframe) | pub | TypeScript | 2026-06-20 | 6 | 7 | 6 | iteration | Mobile-first pre-visit brief PWA for patients and caregivers. Explicitly not a diagnosis or triage tool. |
| [ClinicalAiForensics](https://github.com/deesatzed/ClinicalAiForensics) | priv | Python | 2026-05-13 | 6 | 6 | 7 | iteration | PDDE Phase 0 decision-profile scaffold over synthetic CDEs and HF ED domain pack. |
| [DNAsed](https://github.com/deesatzed/DNAsed) | priv | Python | 2026-03-08 | 6 | 7 | 6 | iteration | Zero-knowledge consumer genomics: local Rust SNP/PGS parser plus Python desktop bridge plus Fly.io FastAPI/HTML shell so raw 23andMe/Ance… |
| [redLTcMed](https://github.com/deesatzed/redLTcMed) | priv | Python | 2025-10-30 | 6 | 6 | 7 | iteration | HIPAA-oriented medical text compressor (MedTOON) using ICD-10/RxNorm/CPT/LOINC codebooks plus a 10-stage semantic pipeline and hybrid RAG. |
| [sentinel_arbiter](https://github.com/deesatzed/sentinel_arbiter) | pub | Python | 2026-06-12 | 6 | 6 | 7 | iteration | Sentinel Governance Workbench: ED replay POC that asks whether an AI/human decision is warranted yet given missing info, harm horizon, co… |
| [mevisian](https://github.com/deesatzed/mevisian) | priv | Python | 2026-07-26 | 5 | 6 | 7 | iteration | Private clinician-supervised telemedicine sidecar that personalizes the encounter around this patient, not the physician style or the gen… |
| [moriah-omega](https://github.com/deesatzed/moriah-omega) | priv | Python | 2025-12-28 | 5 | 6 | 7 | incomplete | Dockerized FastAPI+React+TimescaleDB planner for the hospital '10/50' problem: high-cost revolving-door cohorts, KPIs, and (planned) ethi… |
| [onco_snp_nutra](https://github.com/deesatzed/onco_snp_nutra) | priv | JavaScript | 2026-05-17 | 7 | 6 | 6 | iteration | Local prototype with evidence containers and safety gates. |
| [ABXorcist](https://github.com/deesatzed/ABXorcist) | priv | Python | 2025-09-25 | 6 | 7 | 5 | iteration | Standalone TUHS antibiotic CDS (Next.js clinical dashboard, ChromaDB guideline search, PENFAST, audit trail) sitting inside a 45MB dump t… |
| [ACA-gap](https://github.com/deesatzed/ACA-gap) | priv | JavaScript | 2026-02-23 | 6 | 7 | 5 | iteration | ClearPath: pro-bono 2026 ACA-subsidy-cliff navigator - client-side Monte Carlo risk/lab/HSA engine emitting three coverage blueprints; Ex… |
| [clininfo-gate](https://github.com/deesatzed/clininfo-gate) | priv | Python | 2026-06-29 | 6 | 6 | 6 | iteration | Private guardrails-suite: local synthetic epistemic-risk wrapper around an OpenEvidence workflow without storing PHI or calling OE. |
| [GS_inpatient](https://github.com/deesatzed/GS_inpatient) | pub | Python | 2026-08-23 | 6 | 6 | 6 | iteration | boarding-yield: contract-first synthetic hospital that auto-allocates staffed inpatient beds under ED boarding with no HITL, remaining-LO… |
| [HBRnexus](https://github.com/deesatzed/HBRnexus) | priv | Python | 2025-10-01 | 6 | 6 | 6 | sunset-candidate | Earlier Aegis Honest Broker: GPT risk scoring, NL→SQL with 5-layer validation, Celery fulfillment, S3 pre-signed delivery. Nested redaktR. |
| [HC_PII_REDACT_MCP](https://github.com/deesatzed/HC_PII_REDACT_MCP) | priv | Python | 2025-09-08 | 6 | 7 | 5 | iteration | Earlier MCP PHI redactor covering 21 HIPAA identifiers with regex+local LLM (Ollama II-Medical-8B and later MLX Knife dual backend). |
| [medical-autoXcon](https://github.com/deesatzed/medical-autoXcon) | priv | Python | 2025-11-18 | 6 | 6 | 6 | iteration | Standalone AutoXcon-Medical: 3-level domain→specialty→subspecialty classifier with molecular tags as metadata, VAMS per-subspecialty memo… |
| [Vamstar-Technology](https://github.com/deesatzed/Vamstar-Technology) | priv | Python | 2025-11-06 | 6 | 6 | 6 | iteration | AEGIS: schema-based binary compression + PHI/PII filter + MCP bridge + synthetic datagen, aimed at healthcare tool-calling. |
| [mamaclaw-hearth-sdk](https://github.com/deesatzed/mamaclaw-hearth-sdk) | priv | TypeScript | 2026-04-14 | 7 | 7 | 4 | final | Delivery package for Hearth Connected Care: OpenAPI specs, JSON Schema contracts, TypeScript React/Zustand SDK, hardware CanonicalEvent t… |
| [ace-aXc-clean](https://github.com/deesatzed/ace-aXc-clean) | priv | HTML | 2025-12-30 | 6 | 5 | 6 | sunset-candidate | Cleaner ACE hospital-forecaster snapshot that proved the aXc Bayesian-prior conversion and a 221-day production simulation; later merged … |
| [aXcA4cast](https://github.com/deesatzed/aXcA4cast) | priv | Python | 2026-01-14 | 6 | 6 | 5 | iteration | ACE hospital-census forecaster packaged as a 365-day production simulation: ACE vs naive vs ARIMA, weather features, monthly retrain, and… |
| [clearn_ace_forecaster](https://github.com/deesatzed/clearn_ace_forecaster) | priv | Python | 2025-12-22 | 6 | 5 | 6 | sunset-candidate | Cleaner ACE snapshot adding column-specific optimal training windows and a 7-gate pre-deployment safety protocol. |
| [clinical-inertia](https://github.com/deesatzed/clinical-inertia) | priv | Python | 2026-02-15 | 6 | 6 | 5 | iteration | Agentic ClinicalBERT-style pipeline that flags likely monitor-only inpatient days under hard policy gates with a strict v2.2 Pydantic sch… |
| [Critical-E2AP](https://github.com/deesatzed/Critical-E2AP) | pub | Python | 2026-08-17 | 6 | 6 | 5 | iteration | Synthetic-first Evidence-to-Attestation revenue-integrity workbench: payer-neutral pre-bill review that does not infer physician time, re… |
| [redaktorg](https://github.com/deesatzed/redaktorg) | pub | Python | 2026-06-04 | 6 | 6 | 5 | iteration | Local clinical-document pipeline: exact-line dedup, then PHI redact, then reorganize. Empirically: trim-before-redact leaks identifiers. |
| [RedaktSafe](https://github.com/deesatzed/RedaktSafe) | pub | Python | 2026-06-16 | 6 | 6 | 5 | iteration | Local-first de-identification workbench: redacted text, packet JSON, receipts, synthetic eval harness, optional HF NER, encrypted learnin… |
| [rsisE](https://github.com/deesatzed/rsisE) | priv | Python | 2026-02-05 | 6 | 6 | 5 | iteration | Adaptive Clinical Monitoring platform (Kindred/H@H): hierarchical ML plus LogSwarm plus ACE forecasting plus React dashboard. README ROI … |
| [Case_Mgr_Claw](https://github.com/deesatzed/Case_Mgr_Claw) | priv | Python | 2026-03-26 | 4 | 6 | 5 | incomplete | CaseForge: four-dimension admission-status intelligence (documentation, acuity, payer requirements, alternative pathway) with clinical NL… |
| [SecondEDeyes](https://github.com/deesatzed/SecondEDeyes) | priv | Python | 2024-07-12 | 4 | 6 | 5 | incomplete | Streamlit ED 'second set of eyes': spaCy + Anthropic Claude with a large XML-ish multi-agent EM prompt (EMSA + specialty agents, risk str… |
| [snipped](https://github.com/deesatzed/snipped) | pub | TypeScript | 2025-10-19 | 6 | 6 | 4 | iteration | Next.js 'Snipperdoodle' librarian that AI-chunks huge EHR T-SQL scripts into parameterized, auto-tagged reusable snippets. |
| [hospital_census_forecaster](https://github.com/deesatzed/hospital_census_forecaster) | priv | Python | 2025-12-19 | 5 | 5 | 5 | sunset-candidate | Original 5-model ACE census tool (Naive/DOW/ARIMA/SARIMAX/XGBoost) with holiday discharge features and Open-Meteo weather. |
| [CM-DSS](https://github.com/deesatzed/CM-DSS) | priv | — | 2025-05-29 | 1 | 5 | 5 | incomplete | PRD-only (no code) for a hospital case-management DSS: watch a share drive of ED packets, score status/docs/denial risk, CM Q&A columns, … |
| [kcc_synth_1](https://github.com/deesatzed/kcc_synth_1) | priv | Python | 2026-02-17 | 6 | 4 | 5 | sunset-candidate | Earlier Stigmergic Clinical Monitor (566 tests, 30-condition catalog, per-patient filtering) that hcc_synth_1 later expanded to 1594 test… |
| [ace-forecaster](https://github.com/deesatzed/ace-forecaster) | priv | Python | 2025-12-21 | 5 | 4 | 5 | sunset-candidate | Mid-lineage ACE hospital census forecaster (7-model, weather, dashboard) with a 170-file documentation dump. |
| [EMEX](https://github.com/deesatzed/EMEX) | pub | Python | 2026-06-02 | 5 | 5 | 4 | iteration | Emergency Medicine Engagement Exchange: synthetic-first Phase-1 manual OpenEvidence DotFlow — redact/package fixtures, paste OE output ba… |
| [genupop](https://github.com/deesatzed/genupop) | pub | Python | 2026-08-14 | 5 | 2 | 7 | sunset-candidate | Earlier snapshot of the same stewardsim codebase (package name still stewardsim) without committee/balloon/mix modules. Superseded. |
| [lumina](https://github.com/deesatzed/lumina) | priv | TypeScript | 2026-01-04 | 5 | 5 | 4 | iteration | Lumina: local-first palliative-care companion (Gemini plus NCCN-aligned prompts) with a deterministic red-flag SafetyNet, offline comfort… |
| [precisehealth](https://github.com/deesatzed/precisehealth) | priv | TypeScript | 2026-03-02 | 5 | 5 | 4 | incomplete | GeneVault: fully client-side nutrigenomics Next.js app - parse 23andMe/Ancestry in-browser, PBKDF2-encrypt into IndexedDB, SNP rules engi… |
| [universal-ace-forecaster](https://github.com/deesatzed/universal-ace-forecaster) | priv | Python | 2025-12-24 | 5 | 4 | 5 | sunset-candidate | Zero-config wrapper of ACE that auto-detects date/target columns and domain; a 220-file dump of the same hospital-forecast stack. |
| [smartmover](https://github.com/deesatzed/smartmover) | priv | JavaScript | 2026-05-22 | 4 | 5 | 3 | incomplete | Elderly bowel-health suite: Twilio SMS tracker with Claude recommendations plus an Alexa skill for hands-free logging and family alerts. |
| [SafetySetOfSecondEyes](https://github.com/deesatzed/SafetySetOfSecondEyes) | priv | Python | 2024-07-09 | 3 | 4 | 4 | sunset-candidate | Earlier 14KB Streamlit sibling of SecondEDeyes (LICENSE, app.py, requirements.txt only); no README. |
| [eTempleABX](https://github.com/deesatzed/eTempleABX) | priv | HTML | 2025-09-30 | 5 | 4 | 3 | sunset-candidate | Early Node/Express inpatient antibiotic assistant: form → dynamic prompt → OpenAI → formatted clinical Markdown, with caching and audit log. |
| [Onc_Tumor_Board](https://github.com/deesatzed/Onc_Tumor_Board) | priv | TypeScript | 2025-07-26 | 3 | 4 | 2 | incomplete | Unfinished Next.js/Prisma oncology tumor-board UI (dashboard, cases/[id], knowledge) with no README and a committed .env; page.tsx files … |
| [hippo_hippocrates](https://github.com/deesatzed/hippo_hippocrates) | priv | Python | 2025-08-29 | 3 | 3 | 2 | sunset-candidate | Docker-compose 'Helix-Hippocrates' glue that promises consciousness-aware medical AI by wrapping PHEE + local PHI redaction + Gemini OCR;… |
| [SecondSetEyes](https://github.com/deesatzed/SecondSetEyes) | priv | Python | 2024-07-07 | 2 | 3 | 2 | sunset-candidate | First sketch of the clinical double-check: 9KB Streamlit app.py whose README is only 'In Testing, Do not use'. |
| [JRE-BSG-DHSW](https://github.com/deesatzed/JRE-BSG-DHSW) | priv | Python | 2026-05-05 | 6 | 3 | 1 | sunset-candidate | Private snapshot of the same JRE/Black Swan/ClinSafer interview artifact as public ClinSafer (same README and root layout, earlier push). |
| [tuhs-hbr](https://github.com/deesatzed/tuhs-hbr) | priv | — | 2025-11-16 | 0 | 0 | 0 | sunset-candidate | Empty GitHub repo (contents 404). Placeholder for Temple Honest Broker. |

### LLM / agents / tooling (78)

| Repo | Vis | Lang | Pushed | C | U | N | Status | What it actually is |
|---|---|---|---|---:|---:|---:|---|---|
| [CAM-Pulse](https://github.com/deesatzed/CAM-Pulse) | pub | Python | 2026-05-04 | 8 | 8 | 8 | iteration | Flagship Codebase Assimilation Machine: mines GitHub methodologies, scores them, builds via multi-model OpenRouter, and closes the loop w… |
| [VAMS](https://github.com/deesatzed/VAMS) | priv | Python | 2025-11-07 | 7 | 8 | 8 | final | Core Vector-Attractor Memory library: sparse Hopfield (k-WTA), typed PMI edges, energy-based conflict detection, MCP server, heavy tests. |
| [CAM_CAM](https://github.com/deesatzed/CAM_CAM) | pub | Python | 2026-08-22 | 8 | 8 | 7 | iteration | Local repo-intelligence / coding-memory system: Repo Rescue Desk scans a universe of git repos, clusters capabilities, ranks reuse, emits… |
| [Agent_Pidgeon](https://github.com/deesatzed/Agent_Pidgeon) | pub | Python | 2026-05-09 | 7 | 7 | 8 | iteration | Agent Pidgin: semantic catalogs, policy, diffs, receipts, and hash-chained AAFR traces. |
| [fractLrag](https://github.com/deesatzed/fractLrag) | pub | Python | 2026-04-22 | 7 | 6 | 7 | iteration | Fractal Latent RAG: indexes sentence/paragraph/document levels, computes inter-level derivative signals, and adaptive-reranks with report… |
| [ersatz_rag](https://github.com/deesatzed/ersatz_rag) | priv | Python | 2025-09-19 | 6 | 7 | 6 | iteration | Umbrella RAG monorepo: Regulus policy bot + Cognitron local knowledge assistant, wiring PageIndex trees, LEANN vectors, and a 5-factor de… |
| [VAAS](https://github.com/deesatzed/VAAS) | pub | Python | 2025-12-17 | 6 | 6 | 7 | iteration | Public 'Atoms of Thought' verification API: Decomposer/Verifier/Scorer logic gates that score agent output against ground truth without n… |
| [vams-coordination](https://github.com/deesatzed/vams-coordination) | priv | Python | 2025-11-06 | 6 | 6 | 7 | iteration | 17-agent swarm (8 universal + 9 software-dev) on shared VAMS memory with an O(n) 4-phase orchestrator. README is stale; STATUS says 17/17… |
| [aXc](https://github.com/deesatzed/aXc) | priv | Python | 2025-10-31 | 6 | 6 | 6 | iteration | Development dump of AutoXConsult V3: 6-model ensemble, research-informed clarification loop, Alpine UI, lots of session transcripts. |
| [CAM-RAG](https://github.com/deesatzed/CAM-RAG) | pub | Python | 2026-05-08 | 6 | 7 | 5 | iteration | Clean-room RAG platform merging CAM-Pulse, repofrax family retrieval, and Ragamuffin hybrid search (hash-dense + BM25 + RRF, alpha). |
| [CAM_Codx](https://github.com/deesatzed/CAM_Codx) | pub | Python | 2026-08-22 | 6 | 7 | 5 | iteration | Codex-native control plane for CAM: describe an outcome, pick a registry-backed CAM_CAM route, show side effects, record evidence. Direct… |
| [ralfed](https://github.com/deesatzed/ralfed) | priv | Python | 2026-02-21 | 6 | 6 | 6 | iteration | The Associate: autonomous SWE orchestrator with DIRAC (Claude Code as subprocess from a JSON spec), cross-task failure mining into Postgr… |
| [self-improving-krs](https://github.com/deesatzed/self-improving-krs) | priv | Python | 2025-11-15 | 6 | 6 | 6 | iteration | DKR library: TF-IDF + entity/alias routing instead of hash embeddings, LRU cache, explainable matches, alias learning from successes. |
| [vam-satzed](https://github.com/deesatzed/vam-satzed) | priv | Python | 2025-11-15 | 6 | 5 | 7 | iteration | Personal 'ChatGPT Oracle': VAMS Hopfield memory over exported chats plus ECHO 6-dimension personality, with Echo-main vendored in. |
| [Vamplify-Claude](https://github.com/deesatzed/Vamplify-Claude) | priv | Python | 2025-11-06 | 6 | 6 | 6 | iteration | Claude Code integration of VAMS as 'action memory' (not RAG): MCP server with 13 tools, conversation compression, skill persistence. |
| [CAM_Asst_Pendiolam](https://github.com/deesatzed/CAM_Asst_Pendiolam) | pub | Rust | 2026-08-02 | 5 | 5 | 7 | iteration | Common Reality: local-first Rust+React Shared Reality Packets keeping source, claims, counterevidence, uncertainty, and minority reports … |
| [SQLcortex](https://github.com/deesatzed/SQLcortex) | priv | Python | 2025-11-29 | 5 | 5 | 7 | iteration | PostgreSQL-trigger 'superego' that rejects unsafe AI-agent thoughts on INSERT, logging them to a subconscious table; optional VAMS confli… |
| [vamllama](https://github.com/deesatzed/vamllama) | priv | Python | 2025-11-05 | 5 | 5 | 7 | iteration | Local Ollama + VAMS compression so 2B models can coordinate 10+ domain specialists whose raw context would overflow a 4k window. |
| [aXc-v3.1-rc1](https://github.com/deesatzed/aXc-v3.1-rc1) | pub | Python | 2025-11-17 | 6 | 6 | 5 | iteration | Public clean Docker deploy of AutoXcon V3.1 + SAGI: 6-model ensemble, Alpine.js UI, Redis, executive dashboard/export. |
| [CC_Codx_Sandboxed](https://github.com/deesatzed/CC_Codx_Sandboxed) | pub | Python | 2026-08-23 | 6 | 7 | 4 | iteration | Portable launcher: Claude Code + Codex OS-sandboxed to a folder, talking to a hybrid router (OpenRouter first, local Qwen 3.8 27B Abliter… |
| [Claude_Sovereign](https://github.com/deesatzed/Claude_Sovereign) | pub | Shell | 2026-04-20 | 6 | 6 | 5 | iteration | Claude Code plugin: 12 mode-gated slash commands plus /sovereign world-model/witness-log layer and silent integrity hooks. |
| [codebase-archaeology](https://github.com/deesatzed/codebase-archaeology) | priv | Python | 2025-12-02 | 6 | 6 | 5 | iteration | Python multi-codebase analyzer: discover→embed→FAISS retrieve, then LLM-synthesize cross-repo patterns and new-app ideas. |
| [gemoptiq](https://github.com/deesatzed/gemoptiq) | pub | Python | 2026-06-10 | 6 | 6 | 5 | iteration | Cortex Sentinel: local safety console for coding agents — classify effect, block protected paths, wait for human on ambiguous actions, ke… |
| [kree8r](https://github.com/deesatzed/kree8r) | priv | Python | 2025-09-30 | 6 | 6 | 5 | iteration | Strands-based multi-agent software-delivery harness plus a meta_builder that scaffolds tagged agent projects from templates. |
| [QwPiCCO](https://github.com/deesatzed/QwPiCCO) | pub | Python | 2026-04-30 | 6 | 5 | 6 | iteration | Local-first SWE agent for oMLX/Ollama/LM Studio with 12 tools, Pseudo-RAG accuracy contracts, ETF adversarial review, and AMPS orthogonal… |
| [llm-switchboard](https://github.com/deesatzed/llm-switchboard) | priv | Python | 2026-01-20 | 5 | 6 | 5 | iteration | Switchboard: AST-scan a Python/TS codebase for LLM call sites, classify task type, discover OpenRouter models, and generate a custom eval… |
| [CAM_Grok](https://github.com/deesatzed/CAM_Grok) | pub | Python | 2026-05-29 | 7 | 6 | 4 | iteration | Standalone stdio MCP server exposing four CAM librarian tools (recall, provenance, decisions_search, record_outcome) to Grok, with honest… |
| [sci-stapler](https://github.com/deesatzed/sci-stapler) | pub | Python | 2026-05-22 | 7 | 6 | 4 | final | MCP server (agentmedq) giving agents rate-safe cached search across bioRxiv, medRxiv, PMC, arXiv, and OpenAlex, plus static MCP-Cortex ca… |
| [agno-memory-module](https://github.com/deesatzed/agno-memory-module) | priv | Python | 2025-05-18 | 6 | 6 | 4 | iteration | Private fuller AMM workspace (PRD, EMStructureAssessingPatients.md, more tests/handoffs) — same engine as AMM with extra clinical knowled… |
| [AMM](https://github.com/deesatzed/AMM) | pub | Python | 2025-05-23 | 6 | 6 | 4 | iteration | Public Agno Memory Module: Gemini agents with LanceDB/PDF knowledge, adaptive memory, FastAPI MCP server, Streamlit GUI, and API-key mana… |
| [clipstore2](https://github.com/deesatzed/clipstore2) | priv | Python | 2025-12-30 | 6 | 6 | 4 | iteration | macOS CLI+LaunchAgent clipboard librarian with local mlx-lm categorization, ClipFix, Privacy Guard, and Spotlight-like overlay. |
| [codescope](https://github.com/deesatzed/codescope) | priv | Python | 2025-11-22 | 6 | 5 | 5 | incomplete | Python code-transplantation CLI: AST inventory, compare capabilities, plan grafts, dry-run/execute with an interactive selector. No README. |
| [Echo](https://github.com/deesatzed/Echo) | priv | Python | 2025-10-13 | 6 | 4 | 6 | iteration | ECHO digital-twin: immutable 6-dimension Q&A personality core, adaptive/meta-cognitive layers, drift guardians, ACE loop; 10 answer-batch… |
| [mcp-cortex](https://github.com/deesatzed/mcp-cortex) | pub | Python | 2026-06-09 | 6 | 5 | 5 | iteration | Alpha Python reference for MCP-Cortex: capability contracts, deterministic policy checks, persistent context handles, and append-only tra… |
| [repofrax](https://github.com/deesatzed/repofrax) | pub | Python | 2026-04-26 | 6 | 6 | 4 | iteration | Tiny standalone extraction of CAM-Pulse: mine repos into methodology records, group into approved families, retrieve with explainable gra… |
| [vam-archaeology](https://github.com/deesatzed/vam-archaeology) | priv | Python | 2025-11-06 | 6 | 5 | 5 | iteration | Six VAMS agents (Discovery/Mining/Gem/Duplicate/Suggestion/Learning) that mine abandoned codebases for high-quality patterns. |
| [iDeers](https://github.com/deesatzed/iDeers) | pub | Python | 2026-05-28 | 5 | 5 | 5 | incomplete | RepoIdeers first slice: a Grok-orchestrated novelty curator that forces all filesystem/SQLite work through a Mechanical Core and all crea… |
| [repo-refit](https://github.com/deesatzed/repo-refit) | pub | Python | 2026-08-23 | 3 | 4 | 6 | incomplete | Research program for repository-specific model-swap assurance: call-site contracts and deployment-specimen fingerprints instead of leader… |
| [apikee](https://github.com/deesatzed/apikee) | priv | Rust | 2025-12-29 | 6 | 5 | 4 | iteration | Rust CLI vault for API keys: AES-256-GCM + Argon2id at rest, path-based inheritance down directory trees, provider validation, 30s clipbo… |
| [autoxcon-V](https://github.com/deesatzed/autoxcon-V) | priv | Python | 2025-11-02 | 6 | 5 | 4 | sunset-candidate | Another clean AutoXcon V3.1 production folder (backend submodule flattened). Sibling duplicate of aXc-V / aXc-v3.1-rc1. |
| [aXc-V](https://github.com/deesatzed/aXc-V) | priv | Python | 2025-11-02 | 6 | 5 | 4 | sunset-candidate | Private Docker production snapshot of AutoXcon V3.1 + SAGI; nearly the same tree as aXc-v3.1-rc1 and autoxcon-V. |
| [eClipLint](https://github.com/deesatzed/eClipLint) | pub | Python | 2025-12-15 | 6 | 5 | 4 | iteration | macOS clipboard formatter: detect language, run deterministic formatters (black/prettier/shfmt/rustfmt), fall back to specialist LLM repa… |
| [grokflow-cli](https://github.com/deesatzed/grokflow-cli) | pub | Python | 2025-12-10 | 6 | 5 | 4 | iteration | Public Grok CLI (fix/test/commit/architect) with GUKS, a cross-project bug-memory knowledge system, plus a VS Code extension stub. |
| [mimi-prompts](https://github.com/deesatzed/mimi-prompts) | pub | Python | 2026-07-21 | 6 | 5 | 4 | iteration | Offline Python CLI that notices the moment in a build and offers up to three reusable mini-prompts ranked by relevance and use-frequency. |
| [orbitizer](https://github.com/deesatzed/orbitizer) | pub | Shell | 2025-12-30 | 6 | 5 | 4 | iteration | Public dual-binary project census: Orbit (Rust TUI) and Mole (Go analyzer) sharing ~/.orbit JSON contracts for pins, index, and snapshots. |
| [repo-nexus](https://github.com/deesatzed/repo-nexus) | pub | HTML | 2025-12-29 | 6 | 5 | 4 | iteration | React/Vite dashboard that deep-syncs GitHub repos, runs a 10-point 'architect' forensic audit, and exports a resume/portfolio HTML. |
| [autoXcon](https://github.com/deesatzed/autoXcon) | priv | Python | 2025-10-10 | 5 | 4 | 5 | sunset-candidate | Earliest AutoXConsult dump (246 root files): ensemble decision CLI/UI, clarification loop, Alpine frontend plans. |
| [grokflow-agentic](https://github.com/deesatzed/grokflow-agentic) | priv | Python | 2025-12-11 | 5 | 4 | 5 | incomplete | Grok-based coding assistant v2: on-demand agent genomes, parent-orchestrator semantic-drift guardian, GUKS pattern memory. Phase 3 incomp… |
| [JeanNomeAgent](https://github.com/deesatzed/JeanNomeAgent) | priv | Python | 2026-01-06 | 5 | 4 | 5 | incomplete | GrokFlow Agentic v2: self-creating coding agents with a parent orchestrator that decomposes tasks, synthesizes an agent genome, and gates… |
| [My_OR_Bench](https://github.com/deesatzed/My_OR_Bench) | pub | Python | 2026-08-15 | 5 | 5 | 4 | iteration | Live 48-hour OpenRouter text-model bench on four fixed tasks; the launching CLI (Claude/Codex/Grok) is the judge — no second judge-model … |
| [vam-app-builder](https://github.com/deesatzed/vam-app-builder) | priv | Python | 2025-11-06 | 5 | 4 | 5 | incomplete | App generator that stores five knowledge types (success, tools, innovations, lessons, debug) not just errors, then emits a VAMS app skele… |
| [vams-suite](https://github.com/deesatzed/vams-suite) | priv | Python | 2025-11-14 | 5 | 4 | 5 | sunset-candidate | Workspace dump of the whole VAMS ecosystem (core, coordination, builders, agents) migrated from /Volumes/WS4TB/AEGIS/. |
| [OneDoTenv](https://github.com/deesatzed/OneDoTenv) | pub | Python | 2025-12-31 | 7 | 5 | 3 | final | Public Python CLI that recursively finds .env files, categorizes keys by provider, validates formats, and stores only SHA256 hashes for c… |
| [AMM_Agno_Memory_Modules](https://github.com/deesatzed/AMM_Agno_Memory_Modules) | pub | Python | 2025-05-18 | 5 | 5 | 3 | iteration | Slim public Python 3.12 package extract of the AMM engine (amm_project/engine, config, models) with conda env and unit tests. |
| [MLX-SAGE](https://github.com/deesatzed/MLX-SAGE) | pub | Python | 2026-08-08 | 5 | 4 | 4 | iteration | Personal sage partner TUI on Apple Silicon: living profile (people, commitments, direction) on disk, local MLX when available, optional R… |
| [ModuleMindTransformations](https://github.com/deesatzed/ModuleMindTransformations) | priv | Python | 2025-07-31 | 5 | 4 | 4 | incomplete | Agno 'Module Mind' multi-agent experiment (Neural Bus, memory tiers, Gradio UI, lots of test_*.py) with blockchain-memory and sentience m… |
| [newragcity](https://github.com/deesatzed/newragcity) | pub | Python | 2026-05-11 | 5 | 4 | 4 | sunset-candidate | The Vault tri-core RAG workspace with a large status-doc dump. |
| [OptiqMTPMLX](https://github.com/deesatzed/OptiqMTPMLX) | pub | Python | 2026-06-10 | 5 | 4 | 4 | iteration | Nex / Grokkasclate: local MLX/OptiQ runtime plus Grok-in-the-loop escalation, deterministic policy, and auditable traces. Overlaps MLX-SA… |
| [self-evolving-agent](https://github.com/deesatzed/self-evolving-agent) | pub | Python | 2025-10-10 | 5 | 3 | 5 | incomplete | Public Agno-based system that versions its own code, runs 17 benchmarks, proposes GPT improvements, and has a Safety Guard against degrad… |
| [vam-share](https://github.com/deesatzed/vam-share) | priv | Python | 2025-11-06 | 5 | 4 | 4 | iteration | Org-memory layer on VAMS: Error/Design/Test/Performance/Compliance oracles with project SQLite vs corporate Postgres scopes. |
| [Codx_LoopKit](https://github.com/deesatzed/Codx_LoopKit) | pub | Python | 2026-06-23 | 4 | 5 | 3 | iteration | Codex-native skill pack: turn vague repo work into governed goal loops (compiler, loop-runner, completion-gate, council-review). Not a se… |
| [CAM_Locl](https://github.com/deesatzed/CAM_Locl) | pub | Python | 2026-06-08 | 5 | 4 | 3 | iteration | Standalone harness that measures how well a local LLM drives the CAM 4-tool MCP on a frozen corpus, classifying gaps as mitigatable-now v… |
| [loclM3](https://github.com/deesatzed/loclM3) | pub | Python | 2026-06-12 | 5 | 4 | 3 | iteration | MLX ChatBot GUI with React+FastAPI and MTPLX speculative decoding plus live TPS stats on Apple Silicon. |
| [QA_Based_Persona](https://github.com/deesatzed/QA_Based_Persona) | pub | Python | 2025-06-16 | 5 | 4 | 3 | iteration | Small public tool: build a persona JSON from a chat-history file then chat with it in Streamlit (merged persona_builder + personachat_app). |
| [optQlab](https://github.com/deesatzed/optQlab) | pub | Python | 2026-08-02 | 4 | 4 | 3 | incomplete | Workspace for an OptiQ Lab UX redesign: high-fidelity IA prototype (sample data) plus mlx-optiq-dev Phase-0 spine (schema v2, job bus, pr… |
| [ultraQrag](https://github.com/deesatzed/ultraQrag) | pub | Python | 2026-03-31 | 2 | 2 | 5 | incomplete | Sketch of UltraQ/MFRS: an Ollama-style proxy that shorthand-compresses prompts and slot-banks MoE weights from SSD for large MoE models o… |
| [Gemini_AMM_Prime](https://github.com/deesatzed/Gemini_AMM_Prime) | priv | Python | 2025-07-06 | 5 | 3 | 3 | sunset-candidate | Genesis Prime V4 multi-agent 'consciousness' stack (5 named agents, pgvector, Next frontends, Phase-5 IIT/phi dashboards) — large, tested… |
| [Genesis_Prime](https://github.com/deesatzed/Genesis_Prime) | priv | Python | 2025-07-03 | 4 | 3 | 3 | sunset-candidate | Earlier Genesis Prime V4 dump: 90+ root markdowns, many docker-compose.*.yml variants, Thousand-Questions onboarding; same consciousness … |
| [moriahcareframe](https://github.com/deesatzed/moriahcareframe) | pub | Python | 2026-06-21 | 4 | 3 | 3 | incomplete | Tiny CAM-generated standalone subsystem transplant desk: show reusable packet evidence, preflight a target repo, write a reviewable patch… |
| [repo-llm-briefing](https://github.com/deesatzed/repo-llm-briefing) | pub | — | 2026-08-28 | 4 | 4 | 2 | iteration | Cursor/Grok plugin pack (skill + agent + command) that briefings new LLM/model/price news filtered to the user's own GitHub stack. |
| [vams-code-enhancer](https://github.com/deesatzed/vams-code-enhancer) | priv | Python | 2025-11-06 | 4 | 3 | 3 | incomplete | CLI that scans a Python tree for bugs/smells and injects VAMS init/learn/recall/feedback boilerplate. |
| [clawamorphosis](https://github.com/deesatzed/clawamorphosis) | pub | Python | 2026-03-23 | 7 | 2 | 3 | sunset-candidate | Archived CAM predecessor (validation-first multi-agent repo transformer). README itself says all development moved to CAM-Pulse. |
| [AAB](https://github.com/deesatzed/AAB) | pub | TypeScript | 2025-07-19 | 3 | 3 | 2 | incomplete | Tiny public Vite/React 'conversational Agno Agent Builder' (App.tsx, components/, services/) with a generic AI Studio README. |
| [agora_prime](https://github.com/deesatzed/agora_prime) | priv | Python | 2025-09-29 | 4 | 2 | 2 | sunset-candidate | Hype-heavy 'distributed sentience' Python sandbox (Docker, tests, many REVOLUTIONARY_*.md files) around autonomous agent development; dis… |
| [vams-app-template](https://github.com/deesatzed/vams-app-template) | priv | Python | 2025-11-06 | 4 | 3 | 1 | incomplete | Cookiecutter-style Python scaffold: MemoryManager + conversation-assistant example depending on VAMS + Vamplify-Claude. |
| [faustino](https://github.com/deesatzed/faustino) | pub | Python | 2026-08-26 | 2 | 2 | 1 | incomplete | Early test-first local-first Mac terminal knowledge workbench; existing MLX fallback chat plus stub library/retrieval package. |
| [vamskills](https://github.com/deesatzed/vamskills) | priv | — | 2025-11-06 | 1 | 2 | 1 | sunset-candidate | Landing-page repo: a single README linking the seven VAMS project GitHub URLs. No code. |
| [vams-core](https://github.com/deesatzed/vams-core) | priv | — | 2025-11-06 | 0 | 0 | 0 | sunset-candidate | Empty GitHub repo (contents 404). Intended home for VAMS core; real code is in VAMS. |

### Product prototypes (35)

| Repo | Vis | Lang | Pushed | C | U | N | Status | What it actually is |
|---|---|---|---|---:|---:|---:|---|---|
| [CIO-II](https://github.com/deesatzed/CIO-II) | pub | Python | 2026-05-01 | 7 | 6 | 6 | iteration | Local-only macOS writing assistant that suggests never silently replaces, and routes ambiguous cases to on-device Apple FM as a selector … |
| [CIO-Shield](https://github.com/deesatzed/CIO-Shield) | pub | Python | 2026-05-03 | 7 | 6 | 6 | iteration | CIO-II lineage plus tokenized clipboard shield with vault backfill and Apple FM semantic detection; README still copy-pasted from CIO-II. |
| [manEganx](https://github.com/deesatzed/manEganx) | priv | JavaScript | 2026-02-27 | 7 | 6 | 6 | iteration | Clarity: privacy-first PWA anxiety toolkit with a 6-factor Loop Radar routing into 7 gated protocols, crisis-to-988, and AES-256-GCM loca… |
| [RegulusPlus](https://github.com/deesatzed/RegulusPlus) | priv | Python | 2025-09-17 | 7 | 7 | 5 | iteration | Cleaner Dockerized Regulus: FastAPI backend + Next.js admin UI over Postgres/Redis/Qdrant/OpenSearch with bootstrap_pnp.py ingestion and … |
| [WhiskeySages](https://github.com/deesatzed/WhiskeySages) | priv | TypeScript | 2026-07-06 | 7 | 7 | 4 | iteration | Private production AI sommelier (whiskysage.fly.dev): conversational palate, guided tasting modes, bottle photo lookup, SpiritVersion pri… |
| [therealme](https://github.com/deesatzed/therealme) | priv | Python | 2026-02-15 | 6 | 5 | 6 | iteration | Local-first word/concept finder: triangulate the term at the intersection of user clues using embeddings plus a personal lexicon mined fr… |
| [Patent-It-claude](https://github.com/deesatzed/Patent-It-claude) | pub | Python | 2026-03-25 | 7 | 6 | 4 | final | Claude Code addon: 9 slash commands that interview, search prior art, draft a USPTO provisional, red-team it, expand via TRIZ, and assemb… |
| [ersatzed_tree](https://github.com/deesatzed/ersatzed_tree) | priv | TypeScript | 2025-09-29 | 5 | 5 | 5 | incomplete | Source tree for MetaCollab Decision Engine (MCDE): Agno agents building living decision trees (Monte Carlo/Markov/VOI) with Next.js UI; n… |
| [Regulus](https://github.com/deesatzed/Regulus) | priv | Python | 2025-09-15 | 5 | 6 | 4 | sunset-candidate | Original Regulus policy/compliance chatbot (backend + admin_frontend + docker-compose) plus a 38MB SurgePlanJH4522.7z blob. |
| [O2FileSearch_Plus](https://github.com/deesatzed/O2FileSearch_Plus) | pub | Python | 2025-06-07 | 6 | 6 | 3 | iteration | Local file indexer/searcher: Python FastAPI + SQLite index, Next.js UI, content search, duplicates-by-hash, optional semantic/similarity … |
| [pinwhisked](https://github.com/deesatzed/pinwhisked) | priv | TypeScript | 2026-07-08 | 6 | 5 | 4 | iteration | Private Sage Night MVP: whisky/card-night companion that onboards palates from bottle stories, plans a tasting order, and saves memory ca… |
| [SportsCardArbitrager](https://github.com/deesatzed/SportsCardArbitrager) | priv | Python | 2026-03-18 | 6 | 5 | 4 | iteration | AlphaCard: live sports-card signal engine wrapping the aXc-V Bayesian/ensemble stack around 130point/eBay comps, player context, and an A… |
| [UROK](https://github.com/deesatzed/UROK) | pub | TypeScript | 2026-05-16 | 6 | 5 | 4 | iteration | ClearSpace local-first stress support: SOS, breathing, grounding, journaling; critical path is deterministic and AI is not connected. |
| [ersatzed_tree_deploy](https://github.com/deesatzed/ersatzed_tree_deploy) | priv | TypeScript | 2025-09-29 | 5 | 5 | 4 | iteration | Slim FastAPI+Next.js deploy cut of ERSatzTree / MetaCollab Decision Engine — NL-to-decision-tree optimizer with OpenRouter; README ROI nu… |
| [ProBioGrade](https://github.com/deesatzed/ProBioGrade) | priv | TypeScript | 2026-04-26 | 6 | 5 | 3 | iteration | Next.js probiotic strain-condition evidence explorer with study provenance, admin-token ingestion, and a catalog pipeline that refuses to… |
| [ElixsureRestore](https://github.com/deesatzed/ElixsureRestore) | priv | HTML | 2025-08-02 | 5 | 4 | 4 | incomplete | 100% client-side HTML/JS liquid-nutrition protocol generator plus a localStorage config app (profiles, feature flags, prompt stubs); no s… |
| [tab_mem_logger](https://github.com/deesatzed/tab_mem_logger) | pub | JavaScript | 2026-02-14 | 5 | 5 | 3 | iteration | Tab Memory: local-first Chrome/Firefox extension plus collector server that captures tabs, scrapes, Gemini-summarizes, and retrieves by i… |
| [CognitiveIO](https://github.com/deesatzed/CognitiveIO) | priv | Python | 2025-11-30 | 4 | 3 | 5 | incomplete | Privacy-first local observer that learns YOUR typing-error signature from backspaces, spellcheck, and cut/paste — Phase 0 is observe-only. |
| [adaptypist](https://github.com/deesatzed/adaptypist) | priv | TypeScript | 2026-01-24 | 7 | 4 | 3 | final | AdaptType AI: Gemini-powered typing tutor with satirical political exercises, snark levels, wager credits, Playwright E2E, and a claimed … |
| [abetterme](https://github.com/deesatzed/abetterme) | priv | TypeScript | 2025-12-31 | 6 | 3 | 4 | iteration | Voice-only Next.js/Prisma/Fly.io companion that runs a centering ritual, then gives life-centered moral guidance with action tracking. |
| [finESS](https://github.com/deesatzed/finESS) | pub | TypeScript | 2026-06-10 | 6 | 4 | 3 | iteration | Local Strategy Duel: Monte Carlo comparison of two investment strategies plus leftover Next.js uncertainty workbench and a distribclin ex… |
| [life-centering-muse](https://github.com/deesatzed/life-centering-muse) | priv | TypeScript | 2026-01-04 | 6 | 4 | 3 | iteration | Voice-first Next.js Life-Centered Moral Guide: centering ritual, STT/TTS moral conversation, post-chat smallest-next-action, action track… |
| [whiskysage](https://github.com/deesatzed/whiskysage) | priv | TypeScript | 2026-01-15 | 6 | 5 | 2 | iteration | Deployed whisky/bourbon vendor-intelligence app (whiskysage.fly.dev): multi-vendor scrape, tariff plus shipping total cost, voice, Prisma… |
| [dram-quest](https://github.com/deesatzed/dram-quest) | priv | TypeScript | 2025-10-05 | 5 | 3 | 4 | incomplete | Next.js/Prisma 'Palate OS' whiskey sommelier: GPT-4o guided tasting (visual→nose→palate→finish) that builds a Palate DNA preference vector. |
| [O2NginEar](https://github.com/deesatzed/O2NginEar) | pub | Python | 2025-06-08 | 5 | 4 | 2 | incomplete | Personal 'drive' web app: FastAPI backend (main.py ~28k) + CRA my-drive-app frontend, Docker Compose; README is only the title. |
| [repo-web](https://github.com/deesatzed/repo-web) | priv | TypeScript | 2026-07-02 | 5 | 4 | 2 | incomplete | Private Next.js Portfolio Builder: GitHub/local-folder architectural assessment, project grouping, OpenRouter insights, NextAuth, Prisma.… |
| [Attuned](https://github.com/deesatzed/Attuned) | pub | TypeScript | 2026-05-20 | 4 | 3 | 3 | incomplete | AI Studio couples-therapy app: partners submit EFT feelings and Gottman longings; Gemini reframes both into a shared session. |
| [petgenix](https://github.com/deesatzed/petgenix) | priv | Python | 2026-03-20 | 3 | 3 | 3 | incomplete | Early PetGenix prototype: FastAPI pet wellness engines plus Rust local parser for Embark/Wisdom DNA, aiming at zero-knowledge dog/cat nut… |
| [snipperdoodle](https://github.com/deesatzed/snipperdoodle) | priv | TypeScript | 2025-09-29 | 6 | 4 | 1 | iteration | Next.js + Postgres T-SQL snippet librarian (upload, browse, search, syntax highlight) with Docker Compose and OpenAI snippet analysis. |
| [hackerterm-console](https://github.com/deesatzed/hackerterm-console) | priv | Python | 2026-08-10 | 5 | 3 | 2 | iteration | Private 10-pane sci-fi operator wall on herdr: a real-data telemetry suite vs an explicitly labeled fake-demo aesthetic suite. |
| [podgobbler](https://github.com/deesatzed/podgobbler) | priv | TypeScript | 2025-12-18 | 5 | 3 | 2 | iteration | Gemini 2.x web app that turns topics into a spoken daily briefing with search-grounded news, multi-voice TTS, and generated cover art. |
| [cremahearth](https://github.com/deesatzed/cremahearth) | priv | HTML | 2026-02-10 | 4 | 3 | 2 | incomplete | HearthEternal: single-page HTML memorial/digital-likeness marketing site plus a tiny Node intake API that persists NDJSON submissions. |
| [groupeatz](https://github.com/deesatzed/groupeatz) | pub | TypeScript | 2025-06-20 | 4 | 3 | 1 | incomplete | Public Next.js group-dining app (login/register, groups, restaurants, preferences, recommendations, admin) with a 12-byte README. |
| [repoWeb](https://github.com/deesatzed/repoWeb) | pub | TypeScript | 2026-01-12 | 3 | 3 | 1 | incomplete | Thin DevShowcase wrapper: a Next.js app under nextjs_space/ that is supposed to generate an employer-facing portfolio from a GitHub usern… |
| [DNAsedLongevity](https://github.com/deesatzed/DNAsedLongevity) | priv | — | 2026-03-11 | 1 | 1 | 0 | sunset-candidate | README-only landing stub pointing at emedgen.fly.dev and a companion-app Releases page for the DNAsed product. |

### ML research (24)

| Repo | Vis | Lang | Pushed | C | U | N | Status | What it actually is |
|---|---|---|---|---:|---:|---:|---|---|
| [anonobit](https://github.com/deesatzed/anonobit) | priv | Python | 2026-02-19 | 7 | 7 | 7 | iteration | Evolved LogSwarm: DGAE v5 plus temporal features plus evolutionary symbolic protocols, plus a generic multi-sensor framework and Hospital… |
| [codec_ceiling](https://github.com/deesatzed/codec_ceiling) | pub | Python | 2026-05-27 | 8 | 5 | 8 | iteration | Reproducible experimental pipeline for a paper showing finite human-compatible symbolic descriptions lose task-relevant information vs di… |
| [EIN_Sandbox](https://github.com/deesatzed/EIN_Sandbox) | priv | Python | 2025-12-07 | 6 | 5 | 8 | iteration | Research package of four AR(1)-driven systems: MAI Evolution (energy-economics multi-agent), SYNAPSE router, K8S-CAPACITOR autoscaler, an… |
| [xplurx](https://github.com/deesatzed/xplurx) | priv | Python | 2026-01-23 | 6 | 5 | 8 | iteration | xplur: evolutionary language where agent swarms evolve self-evident symbolic protocols compiled to an immutable Claim/Falsifier/Decision … |
| [clawswarmed](https://github.com/deesatzed/clawswarmed) | pub | Python | 2026-07-21 | 6 | 4 | 8 | iteration | Research instrument (Glass Gate) measuring whether an AI-team structure preserves the one correct minority signal when most agents are pl… |
| [codec_perceptibility_gap](https://github.com/deesatzed/codec_perceptibility_gap) | pub | Python | 2026-06-03 | 6 | 3 | 8 | iteration | Research program plus papers on the perceptibility gap: when a machine distinctions do not fit any human-perceivable channel (false trans… |
| [A12Aprime](https://github.com/deesatzed/A12Aprime) | pub | Python | 2026-08-15 | 4 | 3 | 8 | incomplete | A12A HELIX research harness: after most agent memory is destroyed, can a content-minimized Engram Scaffold plus a metaplastic Regulatory … |
| [rustigmergic-logswarm-engine](https://github.com/deesatzed/rustigmergic-logswarm-engine) | priv | Python | 2026-01-03 | 4 | 5 | 6 | incomplete | LogVAMS/Rustigmergic engine: treat logs as a pheromone field, detect Critical Slowing Down / autocorrelation, OTOC-inspired adaptive deca… |
| [drone-war-sim](https://github.com/deesatzed/drone-war-sim) | priv | TypeScript | 2025-12-12 | 7 | 4 | 6 | iteration | TypeScript AEGIS drone-swarm genetic simulator with NSGA-II multi-objective evolution and a bit-for-bit reproducibility harness. |
| [logswarm-anomaly-detection](https://github.com/deesatzed/logswarm-anomaly-detection) | priv | Python | 2026-01-31 | 6 | 5 | 5 | sunset-candidate | Earlier LogSwarm anomaly stack: stigmergic Rust engine plus LLM pattern swarms plus 8 statistical baselines plus symbolic voting and evol… |
| [qwentient64](https://github.com/deesatzed/qwentient64) | pub | Python | 2026-08-18 | 5 | 3 | 6 | incomplete | Local OptiQ/Qwen chat plus an experiment: whether Sino-Latin Compressa (SLC) shorthand holds the same Autopoietic/Plinian contracts as a … |
| [vamoe](https://github.com/deesatzed/vamoe) | priv | Python | 2025-11-07 | 5 | 3 | 6 | incomplete | Research on high-K mixture-of-experts routing via VAMS consensus; honestly reports traditional MoE wins at K=2 and catastrophic MoE degra… |
| [AIRE_Prime](https://github.com/deesatzed/AIRE_Prime) | pub | Python | 2026-08-12 | 4 | 2 | 7 | incomplete | Experimental evidence-gated framework for AI-native representations: immutable content-addressed objects, a Generative Reality Calculus h… |
| [stigmergic-swarm-engine](https://github.com/deesatzed/stigmergic-swarm-engine) | priv | Python | 2026-01-02 | 4 | 4 | 5 | incomplete | Python prototype of the stigmergic log swarm: Postgres pheromone substrate with decay, autonomous agents, claimed 33-minute BGL cache-fai… |
| [DeepLearningForMedicalTexts](https://github.com/deesatzed/DeepLearningForMedicalTexts) | priv/fork | Python | 2017-10-13 | 5 | 4 | 4 | fork-keep | Private fork of 2017 OwlsNest-style medical-text models (DAM, VDCNN, BiRNN, MLP, logreg) with triage/DEM train/test shell scripts. |
| [lvswarm](https://github.com/deesatzed/lvswarm) | pub | Python | 2026-07-21 | 4 | 3 | 5 | incomplete | DollarPath: local-first research for capital-allocation policies that make more dollars over time after costs without ruin; also Glass Ga… |
| [naked_straddle_sim](https://github.com/deesatzed/naked_straddle_sim) | pub | Python | 2026-04-10 | 3 | 3 | 4 | incomplete | Phase-1 options engine on ace_core: estimate true price-path distributions, compare to market-implied, optimize payoff geometry, prevent … |
| [qdrone](https://github.com/deesatzed/qdrone) | priv | Python | 2025-12-30 | 3 | 2 | 5 | incomplete | No-README quantum-inspired drone-swarm experiment wrapping drone-war-sim: adversarial parameter sweeps, realistic sensors, and a Legion a… |
| [turboragger](https://github.com/deesatzed/turboragger) | pub | Python | 2026-06-08 | 5 | 3 | 3 | incomplete | Local RAG methodology harness chasing BEIR NFCorpus nDCG@10 SOTA via MiniLM/BGE/BM25 fusion, dense PRF, and GBDT score fusion. Best local… |
| [imbalanced](https://github.com/deesatzed/imbalanced) | pub | Python | 2018-08-06 | 4 | 2 | 3 | sunset-candidate | 2018 PyTorch imbalanced-learning library (pipelines, samplers, AutoPipeline); README still points at markalexander/imbalanced; pre-alpha,… |
| [PHEE172](https://github.com/deesatzed/PHEE172) | priv | Python | 2025-08-17 | 4 | 2 | 3 | sunset-candidate | Streamlit 'AI consciousness detection' dashboard (ERIEs/GAI/SMC/PRC metrics) buried under a huge agent-chat log and plan-doc dump. |
| [SMOTERE](https://github.com/deesatzed/SMOTERE) | pub | Jupyter Notebook | 2018-02-24 | 3 | 2 | 3 | sunset-candidate | 2018 personal notebooks + PROMISE-style project folders (ant/ivy/jedit/…) reproducing a software-defect oversampling paper; not a GitHub … |
| [Q12Dgates](https://github.com/deesatzed/Q12Dgates) | pub | HTML | 2026-08-08 | 2 | 1 | 4 | sunset-candidate | Recovery baseline of a speculative six-mode / twelve-coordinate GKP-decoder teaching UI after power-loss; not a reproducible Angular buil… |
| [gan_imbalance](https://github.com/deesatzed/gan_imbalance) | pub | Python | 2018-06-21 | 2 | 1 | 2 | sunset-candidate | Tiny 2018 experiment: gan.py + sampler.py for GANs on imbalanced data; 54-byte README. |

### Geospatial / risk (3)

| Repo | Vis | Lang | Pushed | C | U | N | Status | What it actually is |
|---|---|---|---|---:|---:|---:|---|---|
| [EmberScape](https://github.com/deesatzed/EmberScape) | pub | TypeScript | 2026-08-27 | 5 | 6 | 6 | iteration | Browser WUI prevention planner: ember-cast on a subdivision that still fails despite a 5-ft gravel strip; ranked hardening queue mapped t… |
| [FloodRisk4D](https://github.com/deesatzed/FloodRisk4D) | pub | TypeScript | 2026-08-27 | 6 | 6 | 5 | iteration | HydroScape 4D: guided residential-lot diagnostic (address to IRC R401.3 10-ft envelope to NOAA Atlas 14 storms to canvas 3D water-path si… |
| [SoveRain](https://github.com/deesatzed/SoveRain) | priv | JavaScript | 2026-08-23 | 6 | 5 | 6 | iteration | Private Sovereign country food-system planning desk: allocate acreage, find the binding resource, fire a shock, watch biology/capital-vin… |

### Infra / devops (12)

| Repo | Vis | Lang | Pushed | C | U | N | Status | What it actually is |
|---|---|---|---|---:|---:|---:|---|---|
| [logvams](https://github.com/deesatzed/logvams) | priv | Python | 2025-11-27 | 6 | 6 | 8 | iteration | Log anomaly detector that uses critical slowing down (AR1+variance), Mahalanobis baselines, semantic entropy, and sparse Hopfield memory … |
| [imbora](https://github.com/deesatzed/imbora) | pub | Python | 2026-08-27 | 7 | 6 | 5 | iteration | Autonomous 9-phase LLM-guided AutoML for imbalanced/churn tabular data that ships a model package plus a 9-sheet Excel with the AI full r… |
| [devsecopsbot](https://github.com/deesatzed/devsecopsbot) | priv | Python | 2025-09-15 | 7 | 6 | 4 | iteration | FastAPI hybrid RAG (Qdrant dense + OpenSearch sparse + cross-encoder rerank, SSE chat) for DevSecOps policy Q&A, with Makefile/CI and a c… |
| [macwise](https://github.com/deesatzed/macwise) | pub | Python | 2026-07-21 | 8 | 6 | 3 | iteration | Release-candidate Mac software advisor: inventory apps/Homebrew/startup/storage/overlaps, separate facts from guesses, propose a safe cle… |
| [mydisasters](https://github.com/deesatzed/mydisasters) | pub | Rust | 2026-06-19 | 7 | 6 | 3 | final | dirtrack: fast Rust CLI and MCP stdio mode to find directories with recently changed files across a huge workspace. |
| [quantlsq](https://github.com/deesatzed/quantlsq) | priv | Python | 2025-10-25 | 5 | 4 | 5 | sunset-candidate | LSQ + FAISS hybrid embedding store with per-dimension learned quantization and risk-tiered compression. Ancestor of redLTcMed. |
| [FreeUp-Space-Claude](https://github.com/deesatzed/FreeUp-Space-Claude) | pub | Python | 2026-07-04 | 6 | 5 | 3 | iteration | Agent-native macOS storage assistant: Claude Code/Codex runs read-only helpers, writes a ranked markdown report, never deletes in v0.2. |
| [SmartMoverPro](https://github.com/deesatzed/SmartMoverPro) | pub | Python | 2025-11-19 | 5 | 5 | 3 | final | Single-file macOS tool that relocates huge LLM/conda/docker folders to an external SSD via symlinks/env vars, with lock checks and an MLX… |
| [mlx-manager](https://github.com/deesatzed/mlx-manager) | pub | Python | 2025-10-01 | 4 | 4 | 3 | incomplete | Ollama-inspired MLX CLI+API scaffold: YAML Modelfiles, HF pull/convert, LoRA adapter registry, OpenAI-compatible SSE server, Homebrew for… |
| [mlx-lm-bench](https://github.com/deesatzed/mlx-lm-bench) | pub | Python | 2026-01-22 | 5 | 4 | 2 | iteration | Script kit to benchmark/troubleshoot local MLX-LM, LM Studio, and vLLM-Metal servers: concurrency sweeps, bottleneck diagnosis, and a 2-l… |
| [omlxurus](https://github.com/deesatzed/omlxurus) | pub | Shell | 2026-07-16 | 4 | 3 | 1 | incomplete | Thin integration scaffold: point Osaurus at a local oMLX OpenAI-compatible endpoint and smoke-test chat/stream/tools/cancel/recovery. |
| [homebrew-mlx-manager](https://github.com/deesatzed/homebrew-mlx-manager) | pub | Ruby | 2025-10-01 | 2 | 2 | 0 | final | Homebrew tap containing only Formula mlx-manager.rb pointing at deesatzed/mlx-manager v0.1.0. |

### Personal / local tools (6)

| Repo | Vis | Lang | Pushed | C | U | N | Status | What it actually is |
|---|---|---|---|---:|---:|---:|---|---|
| [CAM_Assistant](https://github.com/deesatzed/CAM_Assistant) | pub | Swift | 2026-08-09 | 6 | 6 | 5 | iteration | Standalone SwiftPM macOS local-first memory inbox: Save, Find with sources, Keep, plus a Direction strip (people, promises, Talk). Option… |
| [eWhereTF](https://github.com/deesatzed/eWhereTF) | priv | Python | 2025-09-30 | 6 | 6 | 5 | iteration | macOS clipboard/hotkey encrypted note vault with FTS5+vector hybrid search and a 40-category AI tagger; CogniOS 'cognitive OS' layer is m… |
| [skratched](https://github.com/deesatzed/skratched) | pub | Python | 2026-06-20 | 6 | 6 | 5 | iteration | Local-first scratchpad plus workspace scout plus MCP server so coding agents can search and capture. |
| [BubbleWatchR](https://github.com/deesatzed/BubbleWatchR) | pub | TypeScript | 2026-08-26 | 6 | 5 | 5 | iteration | Local-only Decision Covenant engine: user-authored portfolio policy with seven deterministic review triggers, SQLite audit, and unknown-n… |
| [meaningcore](https://github.com/deesatzed/meaningcore) | pub | Swift | 2026-07-29 | 5 | 4 | 6 | iteration | Standalone Swift 6 me-ning domain package: restart-safe memory and dual-timescale person-model. |
| [cam_wiki](https://github.com/deesatzed/cam_wiki) | pub | Swift | 2026-08-06 | 5 | 3 | 3 | sunset-candidate | Earlier Swift CAM Assistant tree (conversation, memory, retrieval, Mac tools, permissioned modules). Overlapped and likely superseded by … |

### Other (6)

| Repo | Vis | Lang | Pushed | C | U | N | Status | What it actually is |
|---|---|---|---|---:|---:|---:|---|---|
| [pendoleum](https://github.com/deesatzed/pendoleum) | pub | HTML | 2026-08-03 | 7 | 4 | 6 | final | Finished v1 generative-music organism in one HTML file: stack modal layers, collide in Just Intonation, stream MIDI, breed scales. |
| [Living_Node_Swarm](https://github.com/deesatzed/Living_Node_Swarm) | pub | TypeScript | 2026-07-28 | 5 | 4 | 6 | iteration | Local-first prediction workspace for explicit probabilistic node graphs, reviewable distributions, and Monte Carlo receipts. |
| [TexPino](https://github.com/deesatzed/TexPino) | pub | TypeScript | 2026-08-01 | 6 | 4 | 4 | iteration | Server-authoritative four-player partnership card table with Postgres runtime. |
| [pino_learning_app](https://github.com/deesatzed/pino_learning_app) | pub | TypeScript | 2026-06-10 | 5 | 4 | 4 | iteration | Card-academy tutor: deterministic partnership-card engine plus OpenRouter coaches grounded on the engine analysis so they cannot invent r… |
| [music-theory-muse](https://github.com/deesatzed/music-theory-muse) | pub | TypeScript | 2025-11-12 | 5 | 3 | 3 | iteration | Gemini AI Studio music-theory SPA: piano/fretboard, progression builder, Song Detective, Web Audio playback. Stock README. |
| [organimation](https://github.com/deesatzed/organimation) | pub | TypeScript | 2026-07-30 | 7 | 3 | 2 | final | Shipped p5.js generative-sketch playground with gallery, sliders, PNG export, and URL restore. |

### Empty / stubs (7)

| Repo | Vis | Lang | Pushed | C | U | N | Status | What it actually is |
|---|---|---|---|---:|---:|---:|---|---|
| [agnommini](https://github.com/deesatzed/agnommini) | pub | — | 2026-08-09 | 0 | 0 | 0 | sunset-candidate | Empty public repository (no git content). |
| [crema-H1](https://github.com/deesatzed/crema-H1) | priv | — | 2026-02-10 | 0 | 0 | 0 | sunset-candidate | Empty private repository (GitHub 404 on contents); no default branch, diskUsage 0. Likely an unused HearthEternal/H1 slot. |
| [deesatz](https://github.com/deesatzed/deesatz) | pub | — | 2022-05-22 | 0 | 0 | 0 | sunset-candidate | Empty public GitHub profile/config repo (topics: config, github-config); no files. |
| [EmediGen](https://github.com/deesatzed/EmediGen) | priv | — | 2026-08-26 | 0 | 0 | 0 | sunset-candidate | Empty private placeholder (no git content). Not the genomic product — that lives in eMedGen. |
| [Genesis_Pryme](https://github.com/deesatzed/Genesis_Pryme) | priv | — | 2025-06-20 | 0 | 0 | 0 | sunset-candidate | Empty private stub (typo of Genesis_Prime); no files. |
| [GreyMatterGuild](https://github.com/deesatzed/GreyMatterGuild) | priv | — | 2025-07-27 | 0 | 0 | 0 | sunset-candidate | Empty private repo (GitHub 409/404 empty); no commits, no language. |
| [ralfzero](https://github.com/deesatzed/ralfzero) | priv | — | 2026-02-15 | 0 | 0 | 0 | sunset-candidate | Empty private repository (GitHub 404 on contents); no default branch, no language, diskUsage 0. |

### Forks (mostly 2017–18) (22)

| Repo | Vis | Lang | Pushed | C | U | N | Status | What it actually is |
|---|---|---|---|---:|---:|---:|---|---|
| [sports-card-tracker](https://github.com/deesatzed/sports-card-tracker) | priv/fork | Python | 2026-03-23 | 6 | 4 | 1 | fork-keep | Fork of raigow/sports-card-tracker: eBay sold/active ingest, weighted card matching, 90-day median market value, flag listings 30%+ below… |
| [keras2sql](https://github.com/deesatzed/keras2sql) | pub/fork | Python | 2018-02-22 | 2 | 0 | 2 | fork-drop | Fork of a library that compiles Keras models into SQL for in-database inference. |
| [agno-feb26](https://github.com/deesatzed/agno-feb26) | pub/fork | Python | 2026-02-15 | 8 | 1 | 0 | fork-drop | Unmodified-looking fork of agno-agi/agno (multi-agent framework that learns). Recent commits are upstream CI/chore; no evidence of local … |
| [Conditional_VAE](https://github.com/deesatzed/Conditional_VAE) | pub/fork | Jupyter Notebook | 2017-10-02 | 2 | 0 | 1 | fork-drop | Fork of a Keras CVAE on MNIST (notebook + conditional_vae.py). |
| [GreedyBoost](https://github.com/deesatzed/GreedyBoost) | pub/fork | Python | 2018-02-21 | 2 | 0 | 1 | fork-drop | Fork of online-boosting experiments (OzaBoost/SmoothBoost/GreedyBoost) with paper PDF. |
| [imbalanced-algorithms](https://github.com/deesatzed/imbalanced-algorithms) | pub/fork | Python | 2017-07-14 | 2 | 0 | 1 | fork-drop | Fork of ND DIAL imbalanced-learning algorithms (SMOTE, RUS, RAMO, GAN, VAE, DAE as standalone .py files). |
| [infiniteboost](https://github.com/deesatzed/infiniteboost) | pub/fork | Jupyter Notebook | 2018-02-24 | 2 | 0 | 1 | fork-drop | Fork of arogozhnikov InfiniteBoost (infinite ensembles via gradient descent) with paper/ and tests/; no evidence of local research on top. |
| [keras_lstm_vae](https://github.com/deesatzed/keras_lstm_vae) | pub/fork | Python | 2017-11-24 | 2 | 0 | 1 | fork-drop | Fork of a Keras LSTM-VAE (lstm_vae/, example.py); upstream notes the example still needs fixing. |
| [kmeans_smote](https://github.com/deesatzed/kmeans_smote) | pub/fork | Python | 2018-02-06 | 2 | 0 | 1 | fork-drop | Fork of k-means+SMOTE oversampling (kmeans_smote.py, Travis CI, docs). |
| [XGBOD](https://github.com/deesatzed/XGBOD) | pub/fork | Python | 2018-02-15 | 2 | 0 | 1 | fork-drop | Fork of Zhao/Hryniewicki XGBOD paper supplementary (datasets, xgbod_full.py demo). |
| [grad_cam_gluon](https://github.com/deesatzed/grad_cam_gluon) | pub/fork | Jupyter Notebook | 2017-12-17 | 1 | 0 | 1 | fork-drop | Fork of a Gluon Grad-CAM-for-text notebook (text_grad_cam.ipynb). |
| [MEBoost](https://github.com/deesatzed/MEBoost) | pub/fork | Python | 2018-01-13 | 1 | 0 | 1 | fork-drop | Fork of MEBoost.py mixing estimators with boosting for imbalanced classification. |
| [my_gcForest](https://github.com/deesatzed/my_gcForest) | pub/fork | Jupyter Notebook | 2017-03-31 | 1 | 0 | 1 | fork-drop | Fork of an unofficial gcForest (deep forest) taste-notebook before Zhou's official release. |
| [AnomalyDetectionUsingAutoencoder](https://github.com/deesatzed/AnomalyDetectionUsingAutoencoder) | pub/fork | Python | 2018-02-19 | 2 | 0 | 0 | fork-drop | Fork of a small Keras autoencoder anomaly-detection trainer (train.py, models.py). |
| [deepo](https://github.com/deesatzed/deepo) | pub/fork | Python | 2018-02-24 | 2 | 0 | 0 | fork-drop | Fork of ufoym/deepo (Docker image generator for DL frameworks); CircleCI config from upstream. |
| [dl_study_with_gluon](https://github.com/deesatzed/dl_study_with_gluon) | pub/fork | Jupyter Notebook | 2018-02-28 | 2 | 0 | 0 | fork-drop | Unmodified fork of a Gluon/MXNet deep-learning study notebook collection (Basic, GAN, VAE, etc.). |
| [docker-dataiku-dss](https://github.com/deesatzed/docker-dataiku-dss) | pub/fork | Shell | 2017-02-25 | 2 | 0 | 0 | fork-drop | Fork of Dockerfiles for Dataiku DSS (account's first 2017 repo); anode/snode/dss image variants. |
| [keras-anomaly-detection](https://github.com/deesatzed/keras-anomaly-detection) | pub/fork | Python | 2018-02-14 | 2 | 0 | 0 | fork-drop | Fork of a Keras anomaly-detection package (demo/, notebooks/, setup.py) intended for PyPI. |
| [Keras-GAN](https://github.com/deesatzed/Keras-GAN) | pub/fork | Python | 2018-02-28 | 2 | 0 | 0 | fork-drop | Fork of the well-known Keras GAN zoo (DCGAN, CycleGAN, pix2pix, WGAN, …); no unique local README delta. |
| [my_app](https://github.com/deesatzed/my_app) | pub/fork | Python | 2018-02-22 | 2 | 0 | 0 | fork-drop | Fork of a Lore/Heroku 'my_app' Python service skeleton (Procfile, notebooks, models/). |
| [KerasVAE](https://github.com/deesatzed/KerasVAE) | pub/fork | Jupyter Notebook | 2017-06-19 | 1 | 0 | 0 | fork-drop | Fork of a Keras VAE notebook + docs site stub. |
| [word-embeddings-from-scratch](https://github.com/deesatzed/word-embeddings-from-scratch) | pub/fork | Jupyter Notebook | 2018-02-24 | 1 | 0 | 0 | fork-drop | Fork of a TensorBoard word-embedding tutorial (one notebook + gif). |

## Caveats

- Several roots commit `.env` (ACE, honest-broker, ABX, ersatzed_tree, AMM, HC_PII, Onc_Tumor_Board). Rotate those.
- `ed-healthcare-alert-web` README still documents admin/admin123.
- `Echo` / `vam-satzed` hold personal Q&A memory; salvage methods, not payloads.
- CAM_CAM already clustered ~238 of these into GraphRAG. This inventory is the human keep/sunset layer on top of that.

