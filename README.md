# CAM_CAM

### The repo-universe operating layer for CAM-PULSE.

CAM_CAM is the canonical umbrella repo. CAM-PULSE is the closed-loop learning engine inside it. Repo Rescue Desk is the read-only triage layer that scans a local universe of repositories, classifies reusable systems, flags risk before an agent edits code, ranks what should be built next, and exports GraphRAG / Logseq / Markmap / Freeplane artifacts.

**Current showpiece:** [Repo Rescue Desk](docs/cam_cam_showpiece.html) proves the CAM_CAM layer on a real local run: 238 git repos scanned, 8 capability clusters found, 249 GraphRAG nodes emitted, 244 edges emitted, 6 ranked app opportunities, and 0 source mutations.

**MCP-Cortex showpiece:** CAM_Codx also proved a smaller MCP-Cortex adoption path: mine MCP-Cortex methodologies, recall and cite them through native `cam_cam`, apply the pattern to a real MCP server, and record the outcome. The external `agentmedq` / `sci-stapler` server now exposes static MCP-Cortex-style capability profiles through its existing `list_sources` tool, preserving the same five public MCP tools while labeling read-only network effects, local metadata reads, data flow, risk class, rollback expectations, and applied methodology IDs. This is capability metadata today; policy enforcement is the next layer.

CAM-PULSE **autonomously mines** error handling, retry logic, API design, and testing patterns from real GitHub repos. It stores them as structured, novelty-scored, lifecycle-tracked methodologies and uses that knowledge to build working software across multiple models via OpenRouter. Build outcomes feed back into pattern quality scores via a Thompson-sampling bandit tournament: patterns that help builds pass get promoted, patterns that hurt builds get demoted. When a build fails, a 3-layer defense chain - deterministic auto-fix, correction loop, and agent rotation - tries to repair the failure without human intervention.

**2,274 methodologies** | **266 source repos mined** | **30/30 batch builds passing** | **5/6 failures rescued by defense chain** | **5/10 -> 10/10 with rotation** | **$0 - MIT licensed**

<!-- Counts verified 2026-05-29. Source: CAM-Pulse data/claw.db queries + batch_run/results/compare_overnight/ + retest_rotation/ -->

> **No other tool closes this loop:** discover -> mine -> store -> retrieve -> build -> verify -> correct -> rotate -> learn -> demote. Copilot remembers conventions. Cursor stores rules. Devin indexes wikis. CAM-PULSE mines patterns autonomously, scores them by real build outcomes, rotates failing agents to different models, and demotes what fails. CAM_CAM adds the repo-universe triage layer around that engine.

## Repository Roles

| Repo | Role | Consolidation Status |
|---|---|---|
| `CAM_CAM` | Canonical public repo, showpiece layer, repo-universe triage, and future integration home | Active canonical repo |
| `CAM-Pulse` | Core learning engine lineage: mining, memory, defense chain, routing, self-correction | Being absorbed into `CAM_CAM` by parity-tested slices |
| `CAM-RAG` | Specialist RAG platform for grounded retrieval, citations, and corpus strategy | Kept separate first; integrate through an adapter contract |

Migration plan: [CAM Repo Consolidation Plan](docs/CAM_REPO_CONSOLIDATION_PLAN_2026-05-08.md). Current inventory: [CAM Repo Consolidation Status](docs/CAM_REPO_CONSOLIDATION_STATUS_2026-05-08.md). Parity diff: [CAM-Pulse Parity Diff](docs/CAM_PULSE_PARITY_DIFF_2026-05-08.md).

---

### Proven: 30-Project Batch Build

CAM built 30 software projects autonomously using patterns mined from 266 repos. Every project was verified with real `python -c "import ..."` and `pytest` — no mock, no manual intervention. 6 initial bugs (1-5 line fixes each) were diagnosed and patched; the most common (missing `__init__.py` exports) was fixed systemically in CAM's verifier so future builds self-correct.

| What Happened | Number |
|--------------|--------|
| Projects built autonomously | 30 |
| Fully passing (imports + tests) | 30 |
| Patterns retrieved during builds | 72 (up from 19) |
| Fitness scores recorded | 135 (up from 11) |
| Patterns demoted (learned they hurt builds) | 11 |
| Bugs found and fixed (1-5 line edits each) | 6 |

### Model-Diverse By Design - Defense Chain Proves It

CAM is model-configurable: Claude, GPT, Gemini, Grok, Qwen, DeepSeek via OpenRouter, or local Ollama/MLX-LM. The default budget-diverse configuration runs multiple models so one model's failure does not become the system's failure.

| What | Result |
|------|--------|
| **Overnight comparison (10 projects)** | Single model: 5/10 PASS |
| **With defense chain + rotation** | **10/10 PASS** (5 rescued) |
| **Auto-fix rules** | 5 deterministic rules, no LLM cost |
| **Correction loop** | Feeds exact test output back to the model |
| **Agent rotation** | Different model on `test_failure` / `syntax_error` |
| **Failure knowledge** | Cross-task preventive patterns |

The 3-layer defense chain rescued 5 of 6 projects that failed all single-model configs. The lesson is straightforward: no single model wins every task. Model diversity plus deterministic repair, correction feedback, and rotation is more robust than betting the whole system on one model.

**Previous head-to-head (Grok 4.3 era):**

| | Grok 4.3 | DeepSeek V4 Flash | DeepSeek V4 Pro |
|---|:---:|:---:|:---:|
| **7 empty-dir projects** | **7/7 PASS** | 0/7 (empty output) | -- |
| **5-project head-to-head** | 1/5 PASS, 1788s | -- | 1/5 PASS, 4731s |

<p align="center">
  <img src="demos/cam-pulse-demo.gif" alt="CAM-PULSE demo: cam mine-self --quick showing language breakdown, domain signals, and test results" width="700">
</p>

**[Quick Start](#quick-start)** | **[How It Compares](#how-it-compares)** | **[Web UI](#web-ui--forge-builder)** | **[What You Can Do](#what-you-can-do)** | **[Novel Technology](#novel-technology)** | **[Architecture](#architecture)**

---

## Who Is This For?

- **Solo devs** who want an AI that remembers what worked across sessions — not a chat that forgets everything when you close the tab
- **ML/AI teams** mining GitHub + HuggingFace for architecture patterns, training configs, and deployment recipes — stored with provenance, not bookmarks
- **Teams running domain specialists** — spin up a quantum-physics CAM, a web-design CAM, a medical-AI CAM, and federate them so each expert can answer questions outside its niche
- **Anyone tired of stateless AI** that generates the same boilerplate every time, ignores your past builds, and can't tell you where its suggestions came from

Free, MIT-licensed, runs 100% local if you want (Ollama + MLX-LM, zero API keys needed).

### Use Case 1: Mine Your Own Forgotten Code

You have 50 old repos on your drive gathering dust. CAM extracts the good parts.

```bash
cam mine-workspace ~/Projects ~/Archive --scan-only   # Preview: see what's there
cam mine-workspace ~/Projects ~/Archive --max-repos 15 # Extract patterns
cam learn search "error handling"                       # Find what YOU already wrote
```

### Use Case 2: Build with Battle-Tested Patterns

You need retry logic. Instead of writing from scratch, CAM retrieves patterns from real repos.

```bash
cam create /path/to/my-api --execute \
  --request "Add retry logic with exponential backoff" \
  --check "pytest -q"
# CAM retrieves patterns, builds code, runs tests, attributes sources
```

### Use Case 3: Discover What's Trending

CAM scans X/Twitter for repos developers are sharing, mines them automatically.

```bash
cam pulse scan --keywords "AI agent framework"
# → Discovered: 18 | Novel: 16 | Assimilated: 16 | New patterns: 86
cam learn search "agent routing"   # Search the new knowledge
```

---

## How It Compares

| | CAM-PULSE core inside CAM_CAM | Copilot | Cursor | Windsurf | Devin | Aider |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Mines patterns from source code** | Autonomous, structured | No | No | No | Indexes repos | No |
| **Cross-project knowledge base** | 2,274 methodologies, federated ganglia | Repo-scoped memory | .cursorrules (manual) | Session memories | Wikis + playbooks (manual) | None |
| **Patterns scored by build outcomes** | RL bandit tournament | No | No | No | No | No |
| **Self-improves (demotes failures)** | 11 patterns demoted, lifecycle tracking | No | No | No | No | No |
| **Statistically validated KB uplift** | Cohen's d = 0.843, p < 0.05 | No data published | No data published | No data published | No data published | No data published |
| **Batch build proof** | 30/30 pass | No data published | No data published | No data published | No data published | No data published |
| **Defense chain (auto-fix + rotation)** | 3-layer, 5/6 rescued | No | No | No | Retry (no rotation) | No |
| **Multi-agent routing** | 4 models, Kelly routing, rotation on failure | 1 | 1 | Cascade | Multi-agent | 1 |
| **Runs 100% local (zero cloud)** | Ollama + MLX-LM | No | No | No | No | Partial |
| **Cost** | **Free + MIT** | $19/mo | $20/mo | $0-40/mo | $500/mo | Free + API |

> **Key distinction:** Copilot, Cursor, and Windsurf all have "memory" features (2025-2026), but these store session observations and user-written rules. CAM-PULSE autonomously extracts structured patterns from source code, assigns novelty scores and lifecycle states, and uses build outcomes to rank them. When a build fails, a 3-layer defense chain - deterministic auto-fix, ErrorKB-enriched correction, and RL-driven agent rotation - ensures different models attempt the task. Devin comes closest with multi-agent retry, but without model rotation or cross-task failure knowledge.

---

## Web UI & Forge Builder

Everything CAM does is now accessible through a browser. No CLI memorization required -- search knowledge, watch agents execute, build new brains, track evolution, and mine repos from a single interface.

<p align="center">

```text
┌─ CAM-PULSE ──────────────────────────────────────────────────────┐
│                                                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │  2,274   │  │  Grok    │  │   266    │  │  30/30   │        │
│  │ Methods  │  │  4.3     │  │  Repos   │  │ Passing  │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
│                                                                   │
│  Lifecycle Distribution        Languages                         │
│  ████████████░░░░ active       Python ████████░░ 68%             │
│  ████░░░░░░░░░░░ matured       TypeScript ███░░░ 28%             │
│  ██░░░░░░░░░░░░░ retired       Rust ██░░░░░░░░ 3%               │
│                                 Go █░░░░░░░░░░ 1%               │
└──────────────────────────────────────────────────────────────────┘
```

</p>

<p align="center">

```text
┌─ Playground ─────────────────────────────────────────────────────┐
│                                                                   │
│  Task: "Add retry logic with exponential backoff"                │
│  ┌──────────────────────────────────────────────┐                │
│  │ ▶ Execute Task                               │                │
│  └──────────────────────────────────────────────┘                │
│                                                                   │
│  7-Gate Verification Pipeline                                    │
│  [✓ Deps] [✓ Style] [✓ Chaos] [✓ Placeholders] [⟳ Drift] [○] [○]│
│                                                                   │
│  Step Log                         │  Corrections                 │
│  14:32:01 grab    ✓ retrieved 5   │  Attempt 1: 2 violations     │
│  14:32:03 evaluate ✓ assessed     │   - style_match: missing     │
│  14:32:05 decide  ✓ selected      │   - chaos_check: no jitter   │
│  14:32:12 act     ✓ 3 files       │  Attempt 2: ✓ all gates pass │
│  14:32:15 verify  ✓ 7/7 gates     │                              │
│  14:32:16 learn   ✓ fitness +0.02 │  [View Diff] [View Tests]    │
└──────────────────────────────────────────────────────────────────┘
```

</p>

<p align="center">

```text
┌─ Gap Heatmap ────────────────────────────────────────────────────┐
│                                                                   │
│         Python  TypeScript  Rust    Go     Misc                  │
│  arch    ████    ███░       ██      █░     -                     │
│  test    ████    ██░        █       ░      -                     │
│  api     ███░    ████       -       ██     -                     │
│  perf    ██      █░         ███     -      -                     │
│  sec     █░      -          ██░     █░     -                     │
│                                                                   │
│  ████ = strong coverage   ░ = sparse   - = gap (click to mine)  │
│                                                                   │
│  Clicked: [security × Go] → 1 methodology                       │
│  [Mine this gap] [Search related knowledge]                      │
└──────────────────────────────────────────────────────────────────┘
```

</p>

<p align="center">

```text
┌─ Evolution Lab ──────────────────────────────────────────────────┐
│                                                                   │
│  [A/B Tests] [Agent Routing] [Fitness Trajectories] [Bandit]     │
│                                                                   │
│  Fitness Trajectory: retry_backoff_8a3f                          │
│  1.0 ┤                                    ●                     │
│  0.8 ┤              ●───●───●───●───●──●                        │
│  0.6 ┤         ●──●                                             │
│  0.4 ┤    ●──●                                                  │
│  0.2 ┤  ●                                                       │
│      └──────────────────────────────────────────                 │
│        Apr 1    Apr 3    Apr 5    Apr 7    Apr 9                 │
│                                                                   │
│  Vector: novelty 0.82 | reuse 0.91 | correctness 0.88           │
└──────────────────────────────────────────────────────────────────┘
```

</p>

### Page Index

| Page | Route | What It Does |
|------|-------|-------------|
| Dashboard | `/` | Brain stats, lifecycle distribution, language breakdown |
| Knowledge Explorer | `/knowledge` | Federated search across all brains with filters |
| Methodology Detail | `/knowledge/{id}` | Solution code, fitness history, usage attribution |
| Gap Heatmap | `/knowledge/gaps` | Interactive coverage matrix, click-to-mine gaps |
| Playground | `/playground` | Execute tasks, watch 7-gate verification, correction replay |
| Evolution Lab | `/evolution` | A/B tests, agent routing heatmap, fitness trajectories, bandit arms |
| Mining Console | `/mining` | Mine repos from browser, watch extraction progress |
| Federation Hub | `/federation` | Brain topology graph, cross-brain analysis |
| Costs | `/costs` | Token costs, budget utilization, per-agent efficiency |
| Brain Graph | `/forge` | D3 force-directed brain visualization |
| Build Brain | `/forge/build` | 4-step wizard: name, repos, agents, prompts |
| Script Generator | `/forge/script` | Generate executable shell scripts for CAM operations |
| Brain Detail | `/forge/brain/{name}` | Per-ganglion methodology explorer |
| Forge Run | `/forge/run/{id}` | Execution session detail viewer |
| Build Wizard | `/forge/build` | Persistent wizard with sessionStorage |

### Start the Web UI

```bash
cam dashboard &                            # FastAPI backend on :8420
cd forge-ui && npm install && npm run dev  # Next.js on :3000
# Open http://localhost:3000
```

---

## Quick Start

### One-command quickstart (recommended for first-time users)

```bash
git clone https://github.com/deesatzed/CAM-Pulse.git
cd CAM-Pulse
./camify.sh
```

`camify.sh` walks you through every stage: preflight checks, venv + install (prefers `uv`, falls back to `pip`), interactive `.env` wizard with **real OpenRouter key validation**, target selection, and end-to-end evaluation. It's idempotent and resumable:

```bash
./camify.sh --resume                  # Pick up after a failure
./camify.sh --stop-at install         # Install only, no further stages
./camify.sh --dry-run --yes           # Print every command without executing
./camify.sh --reinstall               # Rebuild the venv from scratch
```

### Guided onboarding with `cam init`

Once installed, `cam init` is a Python-native wizard that verifies your config, checks API keys, bootstraps domain-specific knowledge packs, and runs a smoke test:

```bash
cam init                              # Interactive wizard
cam init --non-interactive --domain python   # Scripted / CI-safe
```

`cam init` supports four curated domains: **python**, **webdev**, **devsecops**, and **all** — each seeds the knowledge base with the matching starter pack (51 Python methodologies, 12 DevSecOps, 1 WebDev, plus `core_v1`) and reports exactly which categories landed. Full bootstrap playbooks (pack contents, layering tips, dedup guarantees, and troubleshooting) live in [`docs/KB_BOOTSTRAP_PLAYBOOKS.md`](docs/KB_BOOTSTRAP_PLAYBOOKS.md).

### See it work before you install anything

```bash
cam mine-self --quick    # Shows file stats, language breakdown, domain signals — no LLM calls
```

No API keys needed. Runs instantly in any directory.

### Verify system health

```bash
cam doctor status    # Agent health, DB path, KB count, Ollama probe, task summary
cam doctor routing   # Kelly weights per agent, with cold-start warnings
cam doctor keycheck --live   # Real provider round-trip (OpenRouter + Gemini)
```

**Verified**: Fresh clone → `./camify.sh` → `cam init --domain python` → `cam doctor status` returns a clean report with **3760 tests passing, zero failures**.

**Web UI** (optional):

```bash
cam dashboard &                            # FastAPI backend on :8420
cd forge-ui && npm install && npm run dev  # Next.js frontend on :3000
open http://localhost:3000
```

On first startup, CAM automatically loads **31 curated seed methodologies** covering its own algorithms (yield-priority mining, Kelly routing, EMA fitness, lifecycle management, correction loop, and more). No configuration needed — `cam govern stats` triggers seeding if the database is empty.

### Other Install Options

| Method | Command | Notes |
|--------|---------|-------|
| **Lightweight** (no torch) | `pip install -e .` | Uses Gemini API for embeddings |
| **Docker** | `docker compose up --build` | Full containerized deployment |
| **Ollama** (zero cloud) | `pip install -e ".[local]"` | No API keys needed |
| **MLX-LM** (Apple Silicon) | `pip install -e ".[mlx]"` | Native M-series acceleration |
| **Developer** (with tests) | `pip install -e ".[dev]"` | Adds pytest, ruff, coverage tools |

### API Keys

| Key | What For | Get It |
|-----|----------|--------|
| `OPENROUTER_API_KEY` | Multi-agent LLM routing | [openrouter.ai/keys](https://openrouter.ai/keys) |
| `GOOGLE_API_KEY` | Embeddings (gemini-embedding-2-preview) | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `XAI_API_KEY` | X-Scout scanning via Grok | [console.x.ai](https://console.x.ai/) |
| `GITHUB_TOKEN` | Freshness monitor (higher rate limits) | [github.com/settings/tokens](https://github.com/settings/tokens) |
| `HF_TOKEN` | HuggingFace model repo mining | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |

For **local-only mode** (Ollama/MLX-LM), no API keys are required.

---

## Proof Points

### What Can CAM Build From Learned Patterns?

CAM retrieved patterns from **3 different mined repos** and synthesized them into one working module:

```
Task: "Build a plugin event system with typed event bus, middleware
       chain, plugin loader with lifecycle hooks, and loop detection."

What happened:
  1. Semantic search retrieved 3 methodologies from 3 repos
  2. Agent built 258 lines of working code across 5 modules
  3. All 5 tests passed
  4. CLI demo runs with visible output

Results:
  Retrieved=3 | Used=3 | Attributed=3 | Quality=0.82
```

| Module | Lines | Pattern Source |
|--------|------:|----------------|
| `event_bus.py` | 71 | Priority ordering + fnmatch wildcards from **pascalorg/editor** |
| `middleware.py` | 56 | Inspect/modify/block chain from **bytedance/deer-flow** |
| `plugin_loader.py` | 56 | Directory discovery + lifecycle hooks from **heroui-inc/heroui** |
| `loop_detector.py` | 22 | Infinite re-emission prevention from **bytedance/deer-flow** |
| `core.py` | 53 | Event dataclass, Plugin protocol, type definitions |

```
$ python -m pytest tests/ -v
tests/test_events.py::test_priority_and_wildcard_delivery_order     PASSED
tests/test_events.py::test_middleware_can_modify_and_block           PASSED
tests/test_events.py::test_loop_detection_prevents_re_emission      PASSED
tests/test_events.py::test_plugin_loader_lifecycle                  PASSED
tests/test_events.py::test_cli_help_version_and_invalid_args        PASSED
5 passed
```

Every module traces back to a specific mined methodology. This isn't code generation — it's **knowledge application with provenance**.

---

### Does CAM's Knowledge Actually Help?

Does CAM's knowledge base actually make agent output better? We ran **two independent experiments** — code quality and full-stack SWE — and the answer is unambiguous: **yes, and the effect is large**.

### Experiment 1: Retry Logic (Qualitative, April 2026)

**Task:** Add retry logic with exponential backoff to a Python API client with no error handling.

- **Run A (Base):** Empty knowledge base — agent sees only the task description
- **Run B (KB-Equipped):** Full knowledge base — 2,274 mined methodologies available

Run B retrieved 5 battle-tested retry patterns from 4 real source repos in 1.4 seconds.

| Quality Check | Run A (Base) | Run B (KB-Equipped) |
|---|:---:|:---:|
| Retryable error classification | Retries all errors | Only 429, 5xx, connect errors |
| 429 Retry-After header | Ignored | Reads and respects it |
| Delay cap | None (grows forever) | 30s maximum |
| Jitter (prevent thundering herd) | None | Random 0-50% of delay |
| Shared retry helper | No (copy-pasted) | Yes (reusable `with_retry()`) |
| Error context preserved | Lost | `RetriesExhausted` + count + cause |
| Structured logging | None | Warning per retry with attempt count |
| Fast-fail on non-retryable | No (wastes retries on 400/404) | Yes (immediate failure) |

**Result: KB-equipped wins 7 out of 8 quality checks.** Run A produces demo-grade code. Run B produces production-grade code.

### Experiment 2: SkyDate SWE Enhancement (Statistical, April 2026)

**Target:** Full-stack SWE code generation on the SkyDate history exploration app (Next.js, PostgreSQL, calendar conversion logic).

**Design:** Blind 50/50 A/B routing via Bayesian allocation. Control arm suppresses **all** knowledge — both HybridSearch `past_solutions` AND the full CAG corpus (~976K tokens, 2,000 methodologies). 23 tasks executed autonomously across 6 MesoClaw evaluation phases.

**6-Dimensional SWE Quality Metric:** Each task scored on Functional Correctness (D1, w=0.30), Structural Compliance (D2, w=0.15), Intent Alignment (D3, w=0.20), Correction Efficiency (D4, w=0.15), Token Economy (D5, w=0.10), Expectation Match (D6, w=0.10). Composite = weighted geometric mean.

| Metric | Control (no KB) | Variant (w/ KB) | Delta | Significance |
|---|:---:|:---:|:---:|:---:|
| **Composite Score** | 0.523 ± 0.256 | **0.699 ± 0.001** | **+33.6%** | Cohen's d = 0.843 (large) |
| **Success Rate** | 10/15 (67%) | **8/8 (100%)** | **+33 pp** | — |
| D1 Functional Correctness | 0.333 | **0.500** | +50% | **p = 0.039** |
| D2 Structural Compliance | 0.811 | **0.970** | +19.6% | **p = 0.024** |
| D3 Intent Alignment | 0.750 | **0.750** | — | n.s. |
| D4 Correction Efficiency | 0.867 | **0.867** | — | n.s. |
| D5 Token Economy | 0.815 | **0.939** | +15.2% | p = 0.191 |
| D6 Expectation Match | 0.833 | **1.000** | +20% | **p = 0.039** |

**Three of six dimensions reach statistical significance (p < 0.05).** The variant arm achieved **zero failures** and **near-zero variance** (± 0.001) — KB injection doesn't just improve average quality, it eliminates inconsistency.

Key files: `scripts/run_skydate_ab.py`, `knowledge/skydate_kb.md`, `src/claw/evolution/ab_analyzer.py`

### Experiment 3: Paired Within-Subject A/B (Definitive, April 2026)

**Design:** 26-pair within-subject blind trial eliminating all confounders. Each pair runs the **same task** with the **same agent** under both arms (knowledge-equipped vs knowledge-suppressed), with randomized arm order. Curated tasks with ≥50% historical success to avoid floor effects.

| Metric | Control (no KB) | Variant (w/ KB) | Significance |
|---|:---:|:---:|:---:|
| **Success Rate** | 19/26 (73.1%) | **24/26 (92.3%)** | McNemar: 6:1 discordant |
| **Mean Composite** | 0.660 | **0.804** | Wilcoxon p=0.015 |
| **Effect Size** | — | — | Cohen's dz = 0.45 (medium) |
| **Bootstrap 95% CI** | — | **[+0.023, +0.270]** | CI excludes zero |
| **W / T / L** | — | **9 / 15 / 2** | — |

All 5 agents (Claude, Codex, Gemini, Grok, Local) show positive mean difference.

Key files: `scripts/run_ab_paired.py` | [Interactive proof →](docs/ab-proof.html)

### What This Proves

Three independent experiments. Three different designs (qualitative, unpaired statistical, paired within-subject). Same conclusion: **agents equipped with CAM's mined knowledge base produce materially better code than agents starting from zero.** The paired study (Experiment 3) is definitive — by testing the same task with the same agent under both conditions, it eliminates agent confounding, task difficulty variance, and sample imbalance.

No other AI coding tool — Copilot, Cursor, Windsurf, Devin, or Aider — publishes controlled ablation studies showing their knowledge system's impact on code quality. CAM's is fully reproducible: `scripts/run_ab_paired.py`.

Full writeup: [docs/showcase_retry_backoff.md](docs/showcase_retry_backoff.md) | [docs/SKYDATE_KB_SHOWPIECE.md](docs/SKYDATE_KB_SHOWPIECE.md) | [docs/ab-proof.html](docs/ab-proof.html)

---

## CAM Brain: Federated Knowledge at Scale

CAM doesn't keep everything in one database. It operates as a **federated brain** — multiple specialist knowledge nodes (ganglia) that share knowledge through read-only cross-queries.

```
CAM Brain (2,274 methodologies, 266 source repos)
├── Python Ganglion (primary) — 3,234 methodologies
├── TypeScript Ganglion — 142 methodologies (Next.js, React, Node patterns)
├── Rust Ganglion — 154 methodologies (WASM, safety, CLI, systems)
├── Go Ganglion — 47 methodologies (concurrency, networking, cloud)
└── Misc Ganglion — 13 methodologies (polyglot, cross-cutting)
    └── Connected via CAM Swarm (read-only FTS5 cross-queries + enriched manifests)
```

Federation is internal tooling for cross-ganglion search. Each ganglion publishes a brain manifest summarizing its expertise; during builds, if local confidence is low, the swarm automatically queries sibling ganglia.

### How It Works

1. **Scan** — Walk the filesystem, find anything that looks like a code project
2. **Dedup** — Content-hash (SHA-256 of first 4KB per file) catches copies with different names
3. **Mine** — LLM extracts reusable patterns: retry logic, API design, testing strategies, architecture decisions
4. **Embed** — 384-dimensional vectors enable semantic search ("find patterns about error handling" works even if no methodology literally says "error handling")
5. **Federate** — Each ganglion publishes a brain manifest summarizing its expertise. During builds, if local confidence is low, the swarm automatically queries sibling ganglia

### Create Your Own Specialist Ganglion

```bash
# Create a new ganglion for your domain
export CLAW_DB_PATH=data/instances/my-specialist.db
cam govern stats  # Initializes empty ganglion

# Feed it
cam pulse ingest https://github.com/some/repo https://github.com/another/repo

# Generate its brain manifest
cam kb instances manifest

# Register it in the swarm
unset CLAW_DB_PATH
cam kb instances add my-specialist data/instances/my-specialist.db \
  --description "Your domain description here"

# Test cross-ganglion query
cam kb instances query "your search terms"
```

See [CAM_STANDALONE_INSTANCE_GUIDE.md](docs/CAM_STANDALONE_INSTANCE_GUIDE.md) for the full walkthrough.

---

## Self-Enhancement: CAM Improves Its Own Code

After mining new knowledge, CAM can assess whether it should **rebuild itself** using the patterns it just learned. This follows the compiler-bootstrap pattern: build the new version with the old version, validate it, then swap.

### Trigger Conditions

CAM monitors two thresholds (either one fires the pipeline):

| Condition | Threshold | After Drive-Ops Mining |
|-----------|-----------|----------------------|
| New methodologies since last enhance | ≥ 10 | 1,046 |
| Average novelty score | ≥ 0.75 | 0.45 (not met, but count alone triggers) |

### The 7-Gate Validation Pipeline

Before any self-modification takes effect, the enhanced copy must pass **all 7 gates**:

| Gate | Check | Tolerance |
|------|-------|-----------|
| 1. Syntax | Every `.py` file parses | Zero errors |
| 2. Config | `claw.toml` loads cleanly | No regressions |
| 3. Imports | All `claw.*` modules import | Zero failures |
| 4. DB Schema | Can open and query live database | Full compatibility |
| 5. CLI Smoke | Core commands execute | Zero crashes |
| 6. Full Pytest | Complete test suite | **All 30/30 builds passing** |
| 7. Diff Summary | Human-readable change report | Informational |

**One failure at any gate = no swap.** The live installation is never touched until all gates pass.

### Protected Files

Changes to these critical files require human review even if all gates pass:

- `verifier.py` — the quality judge
- `factory.py` — the build pipeline constructor
- `engine.py` — the database layer
- `schema.sql` — the database structure
- `config.py` — the configuration model

```bash
cam self-enhance status   # Check if trigger conditions are met
cam self-enhance start    # Run the full pipeline (clone → enhance → validate → swap)
```

---

## Proven End-to-End: Knowledge Application to Self-Enhancement

The sections above describe the mechanisms. This section documents **actual results** from a live run where CAM applied mined knowledge to build a real microservice, then used the same knowledge pipeline to improve its own source code.

### Knowledge Application: Building TaskPulse

CAM was given a single instruction: build "TaskPulse", an async task queue tracker microservice. No scaffolding, no templates — just the task description and whatever CAM could retrieve from its knowledge base.

**What CAM retrieved and injected:**

| Source | Count | Role |
|--------|------:|------|
| PULSE methodology patterns | 3 | Injected directly into agent prompt as `## Retrieved Knowledge` |
| Semantic memory hints | 12 | Evaluation context from semantic search |

**Build execution:**

| Metric | Value |
|--------|-------|
| Files created (first pass) | 12 |
| Drift alignment (attempt 1) | 0.894 |
| Drift alignment (attempt 2) | 0.858 |
| Drift alignment (attempt 3) | 0.883 |
| Correction loop attempts | 3 (with workspace restore and feedback re-injection) |
| Final test result | 6/6 passing after 2 minor environment-specific fixes |
| EMA fitness updates recorded | 6 |

**Patterns from mined repos visible in the output:**

- Endpoint separation (`status_router` vs `task_router`) -- from **Aegis_Atlas**
- Idempotent task IDs -- from **Aegis_Atlas**
- CORS middleware configuration -- from **CLI-Anything**
- Async SQLite via `aiosqlite` -- from **ClawTeam** (workspace isolation patterns)
- CLI generation patterns -- from **CLI-Anything**

The correction loop worked as designed: attempt 1 produced code with drift violations, CAM restored the workspace to a clean state, injected the violation feedback into the next prompt, and re-attempted with the same 3 PULSE patterns. Each attempt improved or maintained alignment scores.

### Self-Enhancement: CAM Rebuilds Itself

Immediately after the knowledge application run, CAM assessed its trigger conditions (1,046 new methodologies since last enhance) and initiated self-enhancement — using the same knowledge pipeline to improve its own source code.

**Pipeline execution:**

| Phase | Result |
|-------|--------|
| Clone | Clean copy of live installation |
| Enhance | Agent: gemini (exploration mode), 3 PULSE patterns injected |
| Enhancement quality | 0.97 |
| Drift alignment | 0.898 |
| Validate | All 7 gates passed (see below) |
| Swap | Atomic replacement of live installation |
| Post-swap smoke | Passed |
| Total duration | 203.4 seconds |

**7-gate validation results:**

| Gate | Check | Result |
|------|-------|--------|
| 1 | Syntax (every `.py` parses) | 82 files OK |
| 2 | Config compatibility | 4 agents loaded |
| 3 | Import (all `claw.*` modules) | 82/82 imported |
| 4 | DB schema (open + query live DB) | 35 tables, 40,703 rows |
| 5 | CLI smoke test | Core commands executed |
| 6 | Batch build proof | 30/30 projects pass (code + import + tests) |
| 7 | Diff summary | Clean |

After the atomic swap completed, a live install verification confirmed 30/30 builds passing on the new codebase.

### The Full Loop

This is what makes CAM different from code generators that start from zero every time:

```
Mine 2,274 patterns from 266 repos across 4 Grok-powered agents
  --> Retrieve and inject relevant patterns into agent prompts
    --> Produce code informed by those patterns
      --> Verify quality and drift alignment
        --> Learn from outcomes (EMA fitness updates)
          --> Use that same knowledge to improve CAM's own source code
            --> Validate through 7 gates
              --> Hot-swap live
```

Every step in this chain ran with real data, real LLM calls, and real validation. The knowledge that helped build TaskPulse is the same knowledge that helped CAM rebuild itself — and the fitness scores from both runs feed back into future retrievals.

---

## How Does the Discovery Pipeline Work?

### First Live Scan: 16/16 Repos Assimilated

```
$ cam pulse scan --keywords "AI agent framework"

=== PULSE Scan Report ===
  Keywords:     github.com new AI agent repo
  Discovered:   18
  Novel:        16  (2 already known)
  Assimilated:  16
  Failed:       0
  New patterns: 86
  JSON repair:  100%  (every repo's LLM output was malformed; all recovered)
```

| Repo | Patterns | What CAM Learned |
|------|:--------:|------------------|
| `7abar/nastar-protocol` | 8 | On-chain reputation scoring, AI dispute judge, 8-state deal machine |
| `cronusl-1141/ai-company` | 8 | Multi-agent role system, versioned prompt registry, failure alchemy |
| `devwebxyn/securemcp-lite` | 7 | Sliding window rate limiter, protocol error classification |
| `bug-ops/zeph` | 5 | Thompson sampling for agent routing, BM25+cosine hybrid RAG |
| `egeuysall/brain` | 6 | Atomic write pattern, tiered knowledge retrieval |
| + 11 more repos | 52 | Various patterns across middleware, auth, state machines |

Then prescreened repos (bytedance/deer-flow, github/spec-kit, heroui-inc/heroui, Kludex/starlette, pascalorg/editor, claude-peers-mcp, MegaMemory) added **36 more methodologies** via `cam pulse ingest`.

---

## What You Can Do

### Discover and Learn
```bash
# Scan X for repos developers are sharing
cam pulse scan --keywords "AI agent framework"

# Ingest a specific repo directly
cam pulse ingest https://github.com/bytedance/deer-flow

# Ingest a HuggingFace model repo (tiered mining: micro/standard/large)
cam pulse ingest https://huggingface.co/microsoft/phi-3-mini-4k-instruct

# Search what CAM has learned
cam learn search "middleware chain" -v -n 10

# View discovery stats
cam pulse status
cam pulse discoveries --limit 20

# Check repo freshness — detect stale knowledge
cam pulse freshness --verbose

# Re-mine repos with significant changes
cam pulse refresh --all
```

### Build with Knowledge
```bash
# Create a new project using learned patterns
cam create /path/to/repo --execute \
  --request "Build a plugin event system with middleware chain" \
  --check "pytest -q"

# Evaluate a repo before modifying it
cam evaluate /path/to/repo --mode quick

# Mine patterns from a folder of repos
cam mine /path/to/repos --max-repos 10 --depth 2
```

### Mine Your Own Code

Most AI tools only learn from the internet. CAM learns from **your own forgotten codebases,
unfinished builds, and archived projects** sitting on your drives.

```bash
# Quick preview: see what CAM finds in your own project (no LLM calls)
cam mine-self --quick

# Full self-mining: extract reusable patterns from your own code
cam mine-self

# Scan multiple directories at once — your entire workspace
cam mine-workspace /Volumes/Projects /Volumes/Archive --scan-only    # preview first
cam mine-workspace /Volumes/Projects /Volumes/Archive --max-repos 15 # mine them

# Search patterns mined from your own code
cam learn search "multiclaw-self"
```

**What makes this different:**
- **`mine-workspace`** scans multiple directories, deduplicates across paths (handles symlinks/overlapping roots), and uses higher defaults for workspace-scale scanning
- **`mine-self`** mines the current project and tags findings with `[self]` for filtering
- **`--quick`** mode shows file stats, language breakdown, and domain signals — zero LLM cost
- Cross-path dedup means `project-v1` in `/old/` and `project-v2` in `/new/` collapse to the best version

### Run Perpetual Discovery
```bash
# Start the daemon — scans X every 30 minutes, mines new repos automatically
cam pulse daemon

# Custom interval
cam pulse daemon --interval 15

# View scan history
cam pulse scans
cam pulse report

# Docker swarm deployment with multiple scouts
docker compose -f pulse/docker-compose.pulse.yml up -d
```

### Self-Enhancement
```bash
# Check if enough new knowledge has accumulated to justify self-enhancement
cam self-enhance status

# Run the full pipeline: clone → enhance → validate (7 gates) → swap
cam self-enhance start

# Validate an enhanced copy without swapping
cam self-enhance validate /path/to/enhanced-copy

# Manually swap a validated copy into production
cam self-enhance swap /path/to/enhanced-copy

# Roll back to the most recent backup
cam self-enhance rollback /path/to/backup
```

### Verify and Audit
```bash
# Validate that changes actually happened
cam validate --spec-file data/create_specs/latest.json

# Check methodology trust levels
cam doctor audit --limit 10

# See knowledge lifecycle state
cam learn report --limit 10

# Run the full test suite
pytest tests/ -q
# → 3,707 passed, 8 skipped, 0 failed

# Scan for secrets before ingestion
cam security scan /path/to/repo
cam security status
```

### Explore and Plan
```bash
# Interactive guide — don't know where to start? Just chat
cam chat

# Generate novel app ideas from your knowledge base
cam ideate /path/to/repos --focus "real-time data"

# Preview a task before committing to a build
cam preflight /path/to/repo --request "Add retry logic"

# Auto-generate an enhancement plan for any repo
cam camify /path/to/repo --goal "modernize error handling"

# Search ALL brains simultaneously
cam federate "distributed caching patterns"

# Expose CAM as an MCP server for Claude Code, Cursor, etc.
cam mcp --transport stdio

# See which agent CAM would pick for each task type
cam doctor routing
```

---

## The Knowledge Loop

This is what makes CAM-PULSE different from every other AI coding tool. It's not a chat wrapper. It's a closed-loop learning system:

```
                          X / Twitter
                              |
                    +---------v----------+
                    |    X-Scout         |  Grok x_search scans for
                    |    (xAI API)       |  GitHub repos developers
                    +---------+----------+  are sharing
                              |
                    +---------v----------+
                    |  Novelty Filter    |  URL dedup + Google Gemini
                    |  (384-dim vectors) |  embedding distance scoring
                    +---------+----------+
                              |
                    +---------v----------+
                    |  3-Pass Mining     |  1. Rule-based domain classify
                    |  Pipeline          |  2. KB overlap assessment
                    |                    |  3. Focused LLM extraction
                    +---------+----------+
                              |
                    +---------v----------+
                    |  SQLite + Vectors  |  2,274 methodologies with
                    |  Knowledge Base    |  provenance, lifecycle state,
                    |  (claw.db)         |  and 384-dim embeddings
                    +---------+----------+
                              |
                    +---------v----------+
                    |  Hybrid Search     |  BM25 text + cosine vector
                    |  & Retrieval       |  similarity, cross-domain
                    +---------+----------+  synergy scoring
                              |
                    +---------v----------+
                    |  Knowledge         |  Full patterns injected as
                    |  Injection         |  ## Retrieved Knowledge in
                    +---------+----------+  agent prompts
                              |
                    +---------v----------+
                    |  Multi-Agent       |  Claude, Codex, Gemini, Grok
                    |  Build             |  via OpenRouter (or Ollama
                    +---------+----------+  / MLX-LM locally)
                              |
                    +---------v----------+
                    |  Verification      |  7 checks + metric gates:
                    |  & Attribution     |  tests, coverage, drift,
                    +---------+----------+  placeholders, claims, style,
                              |             MetricExpectation enforcement
                              |
                     fails?───┘
                       │ yes
                    +---------v----------+
                    |  Inner Correction  |  Workspace restored, agent
                    |  Loop (up to 3x)   |  re-prompted with violations
                    +---------+----------+  + test output as feedback
                              |
                     passes or budget exhausted
                              |
              enough new knowledge accumulated?
                              │ yes
                    +---------v----------+
                    |  Self-Enhancement  |  Clone → enhance copy →
                    |  Pipeline          |  7-gate validation →
                    +---------+----------+  atomic swap + backup
                              |
              repo knowledge going stale?
                              │ yes
                    +---------v----------+
                    |  Freshness Monitor |  ETag caching, significance
                    |  (Phase 1 + 2)     |  scoring, auto re-mine
                    +--------------------+
```

---

## How CAM Thinks: The Brain Transplant Analogy

GitHub Copilot remembers your workspace conventions (28-day expiry). Cursor stores `.cursorrules` you wrote yourself. Devin indexes repos into wikis. **None of them autonomously mine patterns, score them by build outcomes, or demote what fails.** CAM-PULSE is a **brain transplant hospital for coding knowledge**:

```
┌─────────────────────────────────────────────────────────────────┐
│  THE CODE (public, on GitHub)                                    │
│  44K lines of Python, 30/30 builds passing, CLI, prompts, schema         │
│  = the body — same for every CAM ganglion                        │
├─────────────────────────────────────────────────────────────────┤
│  THE BRAIN (local only, never pushed)                            │
│  data/claw.db — 2,274 methodologies, agent scores,               │
│  task history, 384-dim embeddings, lifecycle states               │
│  = unique to YOUR ganglion — YOUR learned experience             │
├─────────────────────────────────────────────────────────────────┤
│  THE KEYS (local only)                                           │
│  .env — API keys for OpenRouter, Google, xAI                     │
│  = credentials — never shared                                    │
├─────────────────────────────────────────────────────────────────┤
│  THE CONFIG (public, with your model picks)                      │
│  claw.toml — model choices, thresholds, feature flags            │
│  = personality — how this ganglion behaves                        │
└─────────────────────────────────────────────────────────────────┘
```

**When you clone CAM from GitHub, you get an empty brain.** Zero methodologies, zero agent scores, zero task history. The schema creates the empty tables on first run.

**This ganglion's brain has learned from experience:**

| Metric | This Ganglion | Fresh Clone |
|--------|:------------:|:-----------:|
| Learned methodologies | 2,274 | 0 |
| Source repos mined | 266 | 0 |
| Tasks executed | 1,668 | 0 |
| Lifecycle promotions (embryonic → viable) | 140 | 0 |
| Brains (language ganglia) | 5 | 0 |
| Agent quality scores | Bayesian-tracked | Uniform prior (0.5) |

**The knowledge evolves through use.** When CAM retrieves a methodology and uses it for a task:
- **Success** → methodology's fitness increases, lifecycle advances (embryonic → viable → thriving)
- **Failure** → fitness decreases, lifecycle may decline, routing shifts to other methodologies
- **Retrieval patterns** → co-retrieval stigmergic links strengthen synergistic knowledge pairs

This is not a static lookup table. The knowledge base is a **living system** that rewards what works and deprioritizes what doesn't.

### CAM Swarm: Ganglion Federation

Why have one generalist brain when you can have a **team of domain experts**?

The **CAM Brain** is the full federated system. Each specialized instance is a **CAM Ganglion** — a semi-autonomous node with its own claw.db, its own learned knowledge, and its own domain focus. The **CAM Swarm** connects ganglia via read-only FTS5 queries through brain manifests.

```
┌───────────────────── CAM Brain ─────────────────────┐
│                                                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │ Python   │ │TypeScript│ │  Rust    │ │  Go    │ │
│  │ (primary)│ │ Ganglion │ │ Ganglion │ │Ganglion│ │
│  │ 3234 mth │ │ 142 mth  │ │ 154 mth  │ │ 47 mth │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬────┘ │
│       └────── CAM Swarm (FTS5) ──────────────┘      │
│             read-only · no copying                   │
└──────────────────────────────────────────────────────┘
```

Each ganglion generates a **brain manifest** — a compact JSON summary of its expertise. When one ganglion works on a task outside its domain, the swarm scores sibling manifests for relevance and queries the best match. No data is copied — the sibling's brain stays intact.

```bash
# Generate this ganglion's brain manifest
cam kb instances manifest

# Register a sibling ganglion
cam kb instances add "quantum-physics" /path/to/quantum/data/claw.db \
    --description "Quantum computing, qubits, error correction"

# Query the swarm
cam kb instances query "quantum error correction for stabilizer codes"

# List all ganglia in the swarm
cam kb instances list
```

See the [Ganglion Guide](docs/CAM_STANDALONE_INSTANCE_GUIDE.md) for full setup — from clone to running specialist ganglion.

### Community Knowledge Sharing (Coming Soon)

CAM ganglia will be able to share their knowledge safely via HuggingFace datasets:

```
cam kb community publish     # Export proven knowledge (7-gate validated)
cam kb community browse      # Preview others' knowledge before importing
cam kb community import      # Pull through 7 validation gates + quarantine
cam kb community approve     # Review quarantined imports before activation
```

The infrastructure is built and tested (44 tests) — imports go through 7 validation gates (schema, field allowlist, content safety, manifest hash, dedup, niche collision, lifecycle reset). All imported knowledge starts as **embryonic** regardless of the source. The community hub HuggingFace dataset will be published when the first wave of users establishes diverse knowledge bases worth sharing.

---

## Novel Technology

**Why this section matters:** Every feature below is absent from GitHub Copilot, Cursor, Windsurf, and Aider. Devin comes closest with repo indexing, but its knowledge is manually authored — not autonomously mined, not novelty-scored, not fitness-ranked by build outcomes. These are the capabilities that make the 30/30 batch build result possible.

### Autonomous X-Scout Discovery
CAM-PULSE uses xAI's Responses API with Grok's native `x_search` tool to find GitHub repos that developers are sharing on X/Twitter. No scraping, no RSS — native server-side search through Grok. Results are filtered by semantic novelty (embedding distance via Google's `gemini-embedding-2-preview`, 384 dimensions) so CAM only assimilates what it doesn't already know.

### 3-Pass Mining Pipeline
Repos aren't mined with a single monolithic LLM call. CAM uses three passes:

1. **Domain Classification** (rule-based, zero cost) — Keyword matching across 10 categories to determine what kind of repo this is
2. **Knowledge Overlap Assessment** (embedding search) — Compares against existing knowledge base to find what's novel vs. already known, computes overlap score and suggested focus areas
3. **Focused LLM Extraction** (adaptive budget) — Sends only the novel parts to the LLM with domain-specific directives. Token budget adapts: small repos get 2K, medium 4K, large 6K. README-first file ordering ensures the LLM sees project context before code.

### Multi-Model Architecture
CAM routes tasks to 4 different AI backends through OpenRouter. Each agent slot is independently configurable — swap models weekly as new ones launch without changing code:

```bash
# .env — you pick the models
CAM_MODEL_CLAUDE=anthropic/claude-sonnet-4-6      # Analysis, reasoning
CAM_MODEL_CODEX=openai/gpt-4.1-mini               # Code generation
CAM_MODEL_GEMINI=google/gemini-2.5-flash           # Repo comprehension
CAM_MODEL_GROK=x-ai/grok-4-1-fast-non-reasoning   # Quick fixes, web lookup
```

### Google Gemini Embeddings
All semantic search uses `gemini-embedding-2-preview` (384 dimensions) via Google API. This powers novelty scoring, knowledge retrieval, and cross-domain synergy detection. For local-only mode, CAM falls back to sentence-transformers or MLX embeddings — no cloud needed.

### Self-Healing JSON Parser
LLM mining output is malformed ~75% of the time. CAM's 3-stage `_repair_json()` achieves **100% repair rate**:
1. Strip trailing commas (regex: `,}` and `,]`)
2. Truncation recovery (find last complete `]` bracket)
3. Individual object extraction (character-by-character `{...}` walking)

Without this, 12 out of 16 repos in the first scan would have been lost.

### Knowledge Injection with Attribution
When you run `cam create --execute`, CAM doesn't just generate code from scratch. It:
1. Searches the knowledge base for relevant patterns (hybrid BM25 + cosine)
2. Retrieves full methodology content (implementation sketch, solution code, activation triggers)
3. Injects it into the agent prompt as a `## Retrieved Knowledge` section
4. After the build, traces which patterns influenced which output via token overlap

Proven result: `Retrieved=3 | Used=3 | Attributed=3 | Tests: 5/5 passing`

### Mission Profiles
Focus your CAM ganglion on a specific domain. Profile-enriched keywords boost relevance:

```toml
[pulse.profile]
name = "agent-memory"
mission = "Discover repos that enhance agent memory, RAG, and knowledge persistence"
domains = ["memory", "RAG", "vector-db", "embeddings"]

[pulse.profile.novelty_bias]
memory = 0.15
RAG = 0.10
```

### Self-Enhancement Pipeline
CAM can improve itself. After mining or PULSE ingestion accumulates enough new knowledge (configurable thresholds: methodology count, novelty score), CAM:

1. **Clones** its own live install (excluding data, caches, evaluation artifacts)
2. **Enhances** the copy using its own multi-agent system with knowledge injection
3. **Validates** through 7 gates: Python syntax → config compatibility → import smoke → DB schema → CLI smoke → full pytest suite → diff summary
4. **Swaps** atomically — renames live to backup, enhanced copy becomes live
5. **Rolls back** automatically if post-swap verification fails

Protected files (`verifier.py`, `factory.py`, `engine.py`, `schema.sql`, `config.py`) require human review even when all gates pass. Cooldown period prevents runaway self-modification.

Proven end-to-end: clone → enhance (1 task, quality 0.97) → all 7 gates PASS → all tests pass on enhanced copy.

### Inner Correction Loop
When verification catches correctable failures (test failures, insufficient coverage, placeholder code), CAM doesn't just log the failure — it retries with full context:

1. **Snapshot** — Full byte-level workspace backup before each attempt (`cycle.py:_snapshot_workspace_content()`)
2. **Verify** — Run all checks (tests, drift, coverage, metric expectations)
3. **Diagnose** — Classify failure: correctable (test failures, placeholders, drift) vs. infrastructure (API timeout, budget)
4. **Restore** — Byte-level workspace rollback to pre-attempt state
5. **Re-prompt** — Agent receives a `## Correction Required` section with specific violations, test output, and failure reasons
6. **Retry** — Up to `max_correction_attempts` (default 3) before learning from the failure

Proven: Run 1 triggered correction 3x (workspace restore + feedback injection working). Run 2 succeeded first attempt: 10/10 tests, drift 0.868, quality 0.76, 2 PULSE patterns injected, lifecycle transition embryonic→viable.

### Metric Expectations Enforcement
The verifier auto-extracts structured metric targets from natural language specs:

- `"greater than 90 percent coverage"` → `MetricExpectation(min_coverage_pct, gte, 90, hard=True)`
- `"at least 20 tests"` → `MetricExpectation(min_test_count, gte, 20, hard=True)`
- Hard expectations block approval; soft expectations generate recommendations

Supported metrics: `min_coverage_pct`, `min_test_count`, `min_files_changed`, `max_files_changed`. Operators: `gte/gt/lte/lt/eq`. Coverage extraction parses `TOTAL` line from `pytest --cov` output.

### Knowledge Gap Analyzer and Category Discovery
CAM identifies blind spots in its knowledge base. `cam gaps` generates a coverage matrix showing methodology density across categories and brains. Sparse cells indicate mining targets — categories where a brain has few or no patterns.

```bash
cam gaps                    # Show category x brain coverage matrix
cam gaps --discover         # Detect emergent categories from cross_cutting overflow
cam gaps --brain rust       # Filter to a specific brain
```

**Category Discovery** (`--discover`) analyzes the `cross_cutting` bin for methodology clusters that deserve their own category. When a cluster exceeds the emergence threshold, it is surfaced as a candidate for reclassification.

### Exploratory KB Search and Stratified CAG Corpus
Knowledge retrieval includes an exploration mechanism: 15% epsilon re-ranking with blended novelty scoring and two-tier relevance filtering. This prevents the knowledge base from converging on a narrow set of high-fitness methodologies while ignoring newer or niche patterns.

The CAG (Cache-Augmented Generation) corpus builder uses stratified sampling: 40% fitness-ranked + 30% category-balanced + 20% novelty-weighted + 10% random. This ensures every agent prompt contains a representative cross-section of the full knowledge base, not just the top-N by retrieval score.

### HuggingFace Model Repository Mining

**Why this matters:** HuggingFace is where the ML community publishes models, datasets, and spaces — not just weights, but training configs, architecture code, and README documentation that encode design decisions. Without HF integration, CAM was blind to half the AI ecosystem.

**How fast this shipped:** HF mining went from concept to production-tested in 2 days — `hf-mount` FUSE adapter, tiered size classification, fallback to `snapshot_download()`, URL routing (`huggingface.co/` auto-detected), and full test coverage. CAM's own knowledge injection pipeline accelerated the build: retrieved patterns from previously-mined repos informed the adapter architecture.

CAM mines HuggingFace model repos alongside GitHub using `hf-mount` (lazy FUSE filesystem) with automatic fallback to `huggingface_hub.snapshot_download()`. The `HFMountAdapter` classifies repos into 3 tiers to avoid downloading multi-GB weight files:

| Tier | Size | Strategy | What's Mined |
|------|------|----------|-------------|
| **micro** | < 100 MB | Full clone | README, config, code — complete extraction |
| **standard** | 100 MB – 2 GB | Metadata-only | README + config.json via HF Hub API (no weights downloaded) |
| **large** | > 2 GB | Metadata-only | Same API approach, avoids multi-GB weight downloads |

The `hf-mount` integration streams files on-demand over FUSE — CAM reads what it needs without materializing the full repo. Falls back gracefully to `snapshot_download()` when `hf-mount` isn't installed.

```bash
# Ingest a HuggingFace model repo — same command, different URL
cam pulse ingest https://huggingface.co/microsoft/phi-3-mini-4k-instruct
cam pulse ingest https://github.com/bytedance/deer-flow

# Configure in claw.toml:
# [pulse.hf_mount]
# enabled = true
# mount_base = "data/hf_mounts"
# cache_size_bytes = 1073741824  # 1GB per mount
# fallback_to_download = true
```

### Repo Freshness Monitor
Previously-mined repos go stale when they ship major rewrites. CAM detects this automatically:

**Phase 1 — Cheap metadata check** (1 GitHub API call per repo, 0 if ETag-cached):
- `GET /repos/{owner}/{repo}` with `If-None-Match: {stored_etag}` — 304s cost 0 rate limit
- Compare `pushed_at` timestamp against stored value

**Phase 2 — Significance scoring** (only for changed repos):
- Commit count since last mine (`/compare/{stored_sha}...HEAD` → `ahead_by`)
- New releases (`/releases/latest`)
- README changes (`/commits?path=README.md&since=...`)
- Repo size delta (stored `size_at_mine` vs. current)

```
significance = commits * 0.3 + new_release * 0.4 + readme_changed * 0.2 + size_delta * 0.1
```

Only repos with `significance >= 0.4` trigger re-mine. Old methodologies transition to `declining`; new ones are stored normally.

```bash
cam pulse freshness           # Check all tracked repos
cam pulse freshness --verbose # Show significance scores
cam pulse refresh <URL>       # Re-mine a specific repo
cam pulse refresh --all       # Re-mine all stale repos
```

### deepConf 6-Factor Confidence Scoring
Every methodology retrieval gets a confidence score beyond simple cosine similarity:

| Factor | Weight | What It Measures |
|--------|--------|-----------------|
| Cosine similarity | 0.30 | Semantic match to query |
| BM25 text match | 0.20 | Keyword relevance |
| Fitness score | 0.20 | Methodology track record (outcomes, lifecycle state) |
| Freshness | 0.10 | Recency of the methodology |
| Cross-domain synergy | 0.10 | Bonus for applying patterns across domains |
| Source diversity | 0.10 | Bonus for patterns from underrepresented repos |

Configurable via `[deep_conf]` in `claw.toml`. Weights sum to 1.0.

### Co-Retrieval Stigmergic Links
When multiple methodologies are retrieved together and the build succeeds, CAM records stigmergic links between them (`memory/semantic.py:record_co_retrieval_outcome()`). Future retrievals boost co-proven methodology pairs — patterns that work together surface together.

### Seed Knowledge — Self-Aware from First Run

Every fresh install of CAM ships with **31 curated seed methodologies** in `src/claw/data/seed/core_v1.jsonl`. On first startup, the factory auto-loads these into the methodology store with real embeddings — CAM immediately knows its own algorithms:

- Yield-priority mining scoring
- Kelly criterion routing
- EMA fitness scoring
- Lifecycle state machine
- Inner correction loop
- Knowledge injection with attribution
- Content-hash dedup
- Mining optimizations (README-first, .mineignore)

Seed knowledge is tagged `origin:seed` and protected from lifecycle decay — seeds never drop below `viable` but can promote to `thriving` when proven through real use. Idempotent: running `cam kb seed` twice skips duplicates via content-hash dedup.

```bash
cam kb seed                      # Load seed knowledge (auto-runs on first startup)
cam kb seed --force              # Re-seed even if seeds already exist
cam kb seed --repair-embeddings  # Generate missing embeddings for existing records
cam kb search "yield priority"   # Verify seed knowledge is searchable
```

### Yield-Priority Mining

Mining repositories in alphabetical order wastes tokens on low-yield targets. Data from 90+ mined repos shows top yield at 0.7-1.25 findings per 1K tokens (small, focused repos) vs bottom yield at 0.00-0.035 (bloated or empty repos).

CAM's `_score_yield_priority()` ranks candidates by expected knowledge yield before mining. 5-factor scoring (max 100 points):

| Factor | Points | What It Measures |
|--------|--------|-----------------|
| **Recency** | 0-40 | Repos modified < 90 days get full points, linear decay to 2 years |
| **File count sweet spot** | 0-25 | 20-500 files = goldilocks zone; < 10 or > 2000 penalized |
| **Source kind** | 0-10 | Git repos score higher than loose source trees |
| **Canonical sibling** | -20 | If another iteration already mined, marginal value drops |
| **Size efficiency** | 0-25 | < 10 MB full points, > 200 MB nearly zero |

Applied automatically before `mining_plan[:max_repos]` selection. Opt out with `--no-yield-sort`.

```bash
cam mine /path/to/repos --max-repos 10             # Yield-sorted by default
cam mine /path/to/repos --no-yield-sort             # Alphabetical order
cam mine-workspace /path --max-repos 20             # Workspace mining, also yield-sorted
```

### Safety Mitigations
- **`--dry-run`** on all destructive PULSE commands — preview without executing
- **Auto-backup** before self-enhancement swaps
- **Confirmation prompts** before re-mining (which retires old methodologies)
- **Infrastructure failure isolation** — API timeouts and rate limits never penalize methodology fitness scores
- **Pre-assimilation secret scanning** — TruffleHog (800+ detectors) blocks repos with critical credentials; regex fallback when binary absent

### Budget Controls (3 Layers)
- **Per-scan**: `max_cost_per_scan_usd = 0.50`
- **Per-day**: `max_cost_per_day_usd = 10.0`
- **Per-agent**: `max_budget_usd` in each agent section

### CAM Swarm Federation

See [CAM Swarm: Ganglion Federation](#cam-swarm-ganglion-federation) above for the full picture and CLI commands.

The swarm works in three steps:
1. **Manifest generation** — Each ganglion summarizes its expertise (categories, languages, source repos, lifecycle distribution) into a lightweight JSON manifest
2. **Relevance scoring** — Keyword overlap (60%), language match (20%), and maturity (20%) determine which sibling ganglia to query
3. **FTS5 cross-query** — Read-only full-text search against relevant ganglia, results tagged with source ganglion

```toml
# claw.toml — CAM Swarm configuration
[instances]
enabled = true
instance_name = "general"                    # This ganglion's name
instance_description = "General-purpose AI development patterns"

[[instances.siblings]]                       # A sibling ganglion
name = "drive-ops"
db_path = "/data/instances/drive-ops.db"
description = "Drive scanning, repo dedup, code organization"
```

### Community Knowledge Hub Infrastructure

See [Community Knowledge Sharing](#community-knowledge-sharing-coming-soon) above for user-facing commands.

The **7 validation gates** (in order):
1. **Schema** — Required fields, format version, instance ID length, text size limit (32KB)
2. **Field allowlist** — Strips unknown metadata keys, redacts remaining secrets
3. **Content safety** — Blocks `exec`, `eval`, `__import__`, `subprocess`, `os.system`, shell injection
4. **Manifest hash** — Recomputes SHA-256 content hash, rejects on mismatch (tamper detection)
5. **Dedup** — Checks against existing knowledge base by content hash
6. **Niche collision** — Soft warning when imported knowledge overlaps existing domain
7. **Lifecycle reset** — Forces embryonic state, zeroes counters, sets project scope (trust must be earned)

### Fitness History Tracking
Every fitness recomputation is logged with its full 6-dimensional vector and trigger event (`outcome_success`, `outcome_failure`, `lifecycle_transition`). This enables analysis of how specific methodologies evolved over time — which ones improved with use and which declined.

### Bayesian Kelly Criterion — Adaptive Agent Routing

CAM implements the Bayesian Kelly Criterion (Sukhov, 2026) for intelligent agent routing. Instead of random exploration or static round-robin, Kelly sizing computes optimal "position sizes" (task allocation fractions) from each agent's win/loss posterior:

```
f* = (p̄ - (1-p̄)/b) × n_eff / (n_eff + κ)
```

**How it works:**
- Each agent's success/failure history builds a Beta(α,β) posterior
- Kelly computes the optimal fraction of tasks each agent should handle
- **Kappa shrinkage** (κ=10) prevents overconfidence with small samples
- **Exploration floor** (2%) ensures new agents always get some tasks
- **Uncertainty discount**: unreliable agents' methodology fitness scores are reduced up to 30%
- **Adaptive A/B margins**: `base_margin × n_eff / (n_eff + κ)` — demands bigger effects from small samples

**Routing priority chain:** Kelly (when data exists) → recommended_agent → exploration → learned history → static fallback

**Proven with real data** (3 rounds, 5 task types, 4 agents):
```
architecture:  claude 37.6% | gemini 26.1% | grok 26.1% | codex 10.2%
analysis:      claude 61.5% | codex 17.7%  | gemini 17.7% | grok 3.1%
bug_fix:       grok 35.7%   | claude 21.4% | codex 21.4% | gemini 21.4%
testing:       codex 54.3%  | claude 15.2% | gemini 15.2% | grok 15.2%
```

```toml
[kelly]
enabled = true
kappa = 10.0        # shrinkage — higher = more conservative
f_max = 0.40        # max fraction any single agent gets
min_exploration_floor = 0.02  # 2% floor for all agents
```

39 tests in `test_kelly.py` covering fraction computation, posterior estimation, routing weights, dispatcher integration, adaptive margins, and fitness discounting.

### License-Aware Mining
Before mining a repository, CAM detects its license from LICENSE/COPYING files and classifies it as `permissive`, `copyleft`, `unknown`, or `none`. The license type is stored in both `pulse_discoveries` and methodology `capability_data`, so downstream consumers can filter by license compatibility.

### Pre-Assimilation Secret Scanning (TruffleHog + Regex Fallback)
Before any repository enters the mining pipeline, CAM scans it for hardcoded secrets using a two-gate architecture:

**Gate 1 — TruffleHog filesystem scan** (in `assimilator.py`, before `mine_repo()`):
- Runs `trufflehog filesystem <path> --json --no-verification` on the cloned/mounted repo
- CRITICAL findings (private keys, verified credentials, Stripe live keys) → assimilation blocked, status = `blocked_secrets`
- Non-critical findings → logged, assimilation continues with Gate 2 filtering
- Falls back to built-in regex scanner (11 patterns: AWS AKIA, GitHub PAT, Slack tokens, Stripe keys, PEM private keys, GCP service accounts, OpenAI keys, etc.) when TruffleHog is not installed

**Gate 2 — Serializer file filtering** (in `miner.py:serialize_repo()`):
- Files with any secret findings are excluded from the serialized content sent to the LLM
- Prevents leaked credentials from entering methodology `solution_code` or agent prompts

Both GitHub and HuggingFace ingestion paths are protected. Configurable via `[security]` in `claw.toml`:

```toml
[security]
secret_scan_enabled = true
secret_scan_fail_on_critical = true
secret_scan_timeout_seconds = 60
```

```bash
# Manual scan — check any directory
cam security scan /path/to/repo

# Check scanner status
cam security status
```

---

## 21 Proven Showpieces

Not demos. Not mockups. Each has a harness script you can run yourself.

| # | Showpiece | What It Proves |
|---|-----------|----------------|
| 21 | **TidyHome CLI** | Real zero-dep Python CLI built by `cam create`. Scanned **1,346,855 files / 97.55 GB** on an actual `~/`. 38 tests, 90% coverage, 16/16 validation steps pass. Flagged 4.8 GB clearly reclaimable + 27.9 GB in ML models. [Details →](docs/CAM_SHOWPIECE_TIDYHOME.md) |
| 1 | **Repo Upgrade Advisor** | Ranked recommendations with confidence scores from mined knowledge |
| 2 | **medCSS Modernizer** | End-to-end create → validate → postcheck on a real CSS codebase |
| 3 | **Expectation Ladder** | 5-level escalating complexity (health → build → validate → mine → self-improve) |
| 4 | **PULSE Knowledge Loop** | 16/16 repos discovered, cloned, mined, stored. Zero failures. |
| 5 | **Cross-Repo Intelligence** | Semantic search across repos from different domains finding shared patterns |
| 6 | **PULSE Usage Proof** | Retrieved=3, Used=3, Attributed=3 — knowledge applied with full provenance |
| 7 | **Multi-Pass Mining** | 3-pass pipeline: classify → overlap → extract with adaptive token budget |
| 8 | **Plugin Event System** | 3 repos → 1 cohesive module. 258 lines. 5/5 tests. Full attribution chain. |
| 9 | **Inner Correction Loop** | Workspace restore + agent re-prompt with violations. Proven: 3 retries → success on next run. |
| 10 | **Metric Expectations** | Natural language → structured gates. "90% coverage" auto-extracted and enforced. 51 tests. |
| 11 | **Repo Freshness Monitor** | ETag caching + significance scoring. Phase 1 costs 0 rate limit for unchanged repos. |
| 12 | **Pre-Assimilation Secret Scanner** | Two-gate TruffleHog + regex fallback blocks secrets before they reach the LLM. 73 tests. |
| 13 | **Bayesian Kelly Agent Routing** | Sukhov (2026) position-sizing for intelligent agent selection with kappa-shrinkage |
| 14 | **Adaptive A/B Test Margins** | Sample-size-aware win thresholds — no premature conclusions from thin data |
| 15 | **Uncertainty-Aware Fitness** | Agent reliability discounts methodology rankings — trustworthy sources rank higher |
| 16 | **KB Quality A/B** | KB-equipped wins 7/8 quality checks on retry logic. Production-grade vs demo-grade. |
| 17 | **SkyDate SWE A/B** | Blind statistical test: +33.6% composite quality, 100% vs 67% success rate, p<0.05 on 3/6 dimensions. |
| 18 | **RL Method Tournament** | Epsilon-greedy bandit + Thompson sampling selects best methodology per task type. Forbidden-on-retry forces iteration. 40 tests. |
| 19 | **Cross-Brain Pattern Atlas** | "defense-in-depth security" → 40 results from 4 brains, 2 universal patterns across languages, 108 transferable insights, 8-layer composition. Real query, real DBs, zero mock. |
| 20 | **Paired A/B Knowledge Proof** | 26-pair within-subject blind trial: 92.3% vs 73.1% success (p=0.015 Wilcoxon), Cohen's dz=0.45, 6:1 discordant ratio. Same task × same agent × both arms. [Interactive proof →](docs/ab-proof.html) |

Run any showpiece:
```bash
# Example: TidyHome — real CLI tool built from mined knowledge
./scripts/test_tidyhome_showpiece.sh

# Example: Plugin Event System (cross-repo synthesis)
./scripts/test_plugin_event_showpiece.sh

# Example: Full reliability pipeline
./scripts/run_cam_reliability_pipeline.sh
```

---

## Architecture

```
src/claw/
  cli.py              # Typer CLI — 80+ commands across 10 subapps (10,300+ lines)
  miner.py            # 3-pass mining pipeline + _repair_json()
  cycle.py            # 4-level orchestration + inner correction loop + RL bandit method selection
  verifier.py         # 7 checks + MetricExpectation enforcement (coverage, test count, file count)
  reconstruct.py      # Self-enhancement: clone → enhance → validate → swap
  validation_gate.py  # 7-gate validation (syntax, config, import, DB, CLI, pytest, diff)
  budget.py           # 3-layer budget enforcement (per-scan, per-day, per-agent)
  agents/
    interface.py      # Multi-agent routing via OpenRouter (Claude/Codex/Gemini/Grok)
  pulse/
    scout.py          # X-Scout: xAI Responses API + x_search
    novelty.py        # Embedding-based novelty filter
    orchestrator.py   # Scan orchestration + circuit breaker
    assimilator.py    # Clone → license detect → mine → store pipeline
    freshness.py      # Repo freshness monitor: ETag caching + significance scoring + auto re-mine
    hf_adapter.py     # HuggingFace model repo mining (hf-mount FUSE + fallback)
    pr_bridge.py      # PR-based fleet registration and enhancement queuing
    models.py         # Pydantic models for PULSE data
  security/
    scanner.py        # TruffleHog + regex fallback secret scanner (Gate 1 + Gate 2)
  community/
    manifest.py       # Brain manifest generation + relevance scoring + BrainTopology
    cross_language.py # Cross-brain analysis: universal patterns, unique innovations, composition
    federation.py     # CAM Swarm — cross-ganglion FTS5 search with read-only queries
    packer.py         # Export methodologies to JSONL with provenance + hash integrity
    validator.py      # 7-gate import validation (schema, safety, dedup, lifecycle reset)
    importer.py       # Quarantine-first import with approve/reject workflow
    hub.py            # HuggingFace dataset push/pull operations
    gap_analyzer.py   # Knowledge gap detection: category x brain coverage matrix + category discovery
  memory/
    hybrid_search.py  # BM25 text + cosine vector + deepConf 6-factor confidence scoring
    bandit.py         # RL method tournament: epsilon-greedy + Thompson sampling selection
    kv_cache_manager.py # KV cache prefix caching with brain topology awareness
    semantic.py       # Semantic memory, co-retrieval stigmergic links, outcome feedback
    fitness.py        # 6-dimensional fitness scoring + history logging
    lifecycle.py      # Gause competitive exclusion state machine
  db/
    engine.py         # SQLite + sqlite-vec (WAL mode), 15 migrations
  evolution/
    assimilation.py   # Methodology lifecycle management + synergy discovery
    prompt_evolver.py # Bayesian A/B testing + deterministic prompt mutations
  training/
    trace_extractor.py # RLMHT trace generation: routing, grouping, composition ChatML
```

**Database**: SQLite with `sqlite-vec` extension for vector similarity search. WAL mode for concurrent reads. Stores methodologies, embeddings (384-dim), provenance, lifecycle state, fitness history, community imports, usage logs, scan history, and discovery records. 15 migrations applied automatically.

---

## The Validation-First Difference

Most AI coding tools say "I updated the files" and you trust them. CAM doesn't.

- `cam create --execute` checks the **actual workspace diff**. If no files changed, the run is marked **FAILED**.
- `cam validate` runs your acceptance checks (`pytest`, build commands) against the saved spec.
- **Metric enforcement**: The verifier extracts test count and coverage targets from your spec text ("at least 20 tests", ">90% coverage") and rejects builds that don't meet them. Structured `MetricExpectation` objects support `gte/gt/lte/lt/eq` operators with hard (blocks approval) or soft (recommendation) enforcement.
- **Self-correction**: When verification fails with correctable issues (test failures, insufficient test count, low coverage, placeholder code), the workspace is byte-level restored and the agent is re-prompted with the violations and test output. Up to 3 correction attempts before learning from failure.
- `cam forge-benchmark` reports "0% lift" when that's the truth — not a dressed-up number.
- Every methodology tracks its lifecycle: `stored → enriched → retrieved → operationalized → proven`
- Infrastructure failures (API timeouts, rate limits) are logged but **never penalize** methodology fitness.

---

## Honest Limits

- `cam create --execute` is gated behind preflight checks — not yet fully autonomous
- Local mode (Ollama/MLX-LM) works but hasn't been battle-tested as deeply as OpenRouter mode
- Knowledge retrieval quality depends on the diversity of mined repos
- Mined methodologies record source repo URL, discovery date, and license type (permissive/copyleft/unknown/none)

---

## Roadmap

| Phase | Status |
|-------|--------|
| **Phase 1**: Core Engine — evaluate, mine, create, validate, benchmark | **Complete** |
| **Phase 2**: Local-First — Docker, Ollama, MLX-LM, torch-free install | **Complete** |
| **Phase 3**: PULSE — X-Scout discovery, multi-pass mining, knowledge injection, attribution | **Complete** |
| **Phase 3.5**: Self-Enhancement — Clone → enhance → 7-gate validate → atomic swap | **Complete** |
| **Phase 3.75**: Resilience — Inner correction loop, metric expectations, HF-mount, freshness monitor, deepConf scoring, co-retrieval links, safety mitigations | **Complete** |
| **Phase 3.9**: Knowledge Infrastructure — License-aware mining, A/B knowledge ablation, fitness history, community sharing (7-gate validated), CAM Swarm ganglion federation with brain manifests, pre-assimilation secret scanning (TruffleHog + regex) | **Complete** |
| **Phase 4**: Drive-Ops — 1.5TB ganglion mining marathon, content-hash dedup, brain federation proven at scale | **Complete** |
| **Phase 4.5**: Self-Awareness — Seed knowledge system (31 curated methodologies ship with install), yield-priority mining (5-factor scoring), `_approve_record()` FTS5+embedding fix, `origin:seed` lifecycle protection | **Complete** |
| **Phase 4.75**: RL Method Tournament — Epsilon-greedy bandit + Thompson sampling selection, forbidden-on-retry iteration, FTS5 hybrid search fix (AND→OR), `cam govern bandit-stats` CLI | **Complete** |
| **Phase 4.9**: Knowledge Exploration — Gap analyzer (`cam gaps`), category discovery, exploratory epsilon re-ranking, stratified CAG corpus, batch mining across 4 Grok-powered agents | **Complete** |
| **Phase 5.0**: Web UI -- 14-page Next.js frontend, Forge Builder, real-time execution playground, gap heatmap, evolution lab, brain graph | **Complete** |
| **Phase 6**: Enterprise — Sandbox enforcement, audit logs, webhook notifications | Planned |
| **Phase 7**: Premier — Community hub launch, fleet-scale self-enhancement, embedding hot-swap | Planned |

---

## Documentation

**Landing page**: [deesatzed.github.io/CAM-Pulse](https://deesatzed.github.io/CAM-Pulse/)

### Getting Started

| Doc | Purpose |
|-----|---------|
| [Getting Started](docs/GETTING_STARTED.md) | First 30 minutes: install, mine, see results |
| [Command Guide](docs/CAM_COMMAND_GUIDE.md) | Every command, every flag |
| [Operator Cheatsheet](docs/CAM_OPERATOR_CHEATSHEET.md) | Quick reference for daily use |
| [Beginner Assimilation Guide](docs/CAM_BEGINNER_ASSIMILATION_GUIDE.md) | Two-path workflows for learning and building |
| [Decision Tree](docs/CAM_COMMAND_DECISION_TREE.md) | Which command to use first |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | Common errors and fixes |

### Feature Guides

| Doc | Purpose |
|-----|---------|
| [CAG Guide](docs/CAG_GUIDE.md) | Cache-Augmented Generation: vectorless, zero-latency knowledge retrieval |
| [Local LLM Setup](docs/LOCAL_LLM_SETUP.md) | Ollama, TurboQuant, MLX-LM — zero cloud cost inference |
| [KV Cache Guide](docs/KV_CACHE_GUIDE.md) | KV cache compression, TurboQuant turbo3/turbo4, A/B test results |
| [Advanced Features](docs/ADVANCED_FEATURES.md) | Kelly routing, deepConf, prompt evolution, error KB, budget, pattern learning |
| [Governance Tuning](docs/GOVERNANCE_TUNING.md) | Memory lifecycle, quotas, methodology management |
| [Ganglion Guide](docs/CAM_STANDALONE_INSTANCE_GUIDE.md) | Clone CAM, create a specialist ganglion |
| [MCP Integration Guide](docs/MCP_INTEGRATION_GUIDE.md) | Connect CAM to Claude Code, Cursor, or any MCP client |

### Proof and Examples

| Doc | Purpose |
|-----|---------|
| [Proven Capabilities](docs/CAM_PROVEN_CAPABILITIES.md) | Evidence-backed claims |
| [TidyHome CLI](docs/CAM_SHOWPIECE_TIDYHOME.md) | Real CLI tool built from mined knowledge — verified on 1.35M files |
| [Plugin Event System](docs/CAM_SHOWPIECE_PLUGIN_EVENT_SYSTEM.md) | Cross-repo synthesis proof |
| [PULSE Knowledge Loop](docs/CAM_SHOWPIECE_PULSE_KNOWLEDGE_LOOP.md) | 16/16 scan proof |
| [PULSE Usage Proof](docs/CAM_SHOWPIECE_PULSE_USAGE_PROOF.md) | Knowledge application proof |
| [Blog: First Live Scan](docs/blog/2026-03-22-pulse-first-live-scan.md) | Full writeup with results |
| [Proof Point Index](docs/PROOF_POINT_INDEX.md) | Reproduction commands for all 21 proof points |

---

## When to Push a New Version

CAM uses the same validation-first philosophy for its own releases. Before pushing to GitHub:

### Release Checklist

```
1. TESTS         — All 30/30 builds passing collected (pytest tests/ -q)
                   Zero failures. No new skips without documented reason.

2. SELF-ENHANCE  — If self-enhance was run, all 7 gates passed
                   Gate 6 (full pytest) is the hard gate. No exceptions.

3. SMOKE TEST    — Core commands work on a fresh terminal:
                   cam --help
                   cam govern stats
                   cam kb search "any query"
                   cam kb instances list

4. PROTECTED     — No uncommitted changes to protected files without review:
                   src/claw/verifier.py
                   src/claw/core/factory.py
                   src/claw/db/engine.py
                   src/claw/db/schema.sql
                   src/claw/core/config.py

5. SECRETS       — No API keys, tokens, or credentials in staged files:
                   cam security scan src/ tests/

6. DOCS SYNC     — README stats match reality (test count, methodology count)
                   Landing page (docs/index.html) reflects current state

7. CHANGELOG     — Commit messages describe what changed and why
```

### When NOT to Push

- Tests failing or skipping unexpectedly
- Self-enhance produced changes you haven't reviewed
- API keys are committed anywhere (even in test fixtures)
- The landing page claims capabilities that aren't proven
- Database schema changed without a migration

### Version Progression

CAM doesn't use semantic versioning yet — it uses **phase-based milestones**. Each phase is a natural push point:

| Signal | Action |
|--------|--------|
| New phase completed (e.g., Drive-Ops mining) | Push with phase summary commit |
| Self-enhance passed all 7 gates | Push — CAM improved itself with proof |
| Bug fix with regression test | Push immediately |
| Documentation-only update | Push — keeps landing page current |
| Mining marathon completed | Push if it changed code (dedup fixes, federation bugs) |

The simplest rule: **if the test suite passes and the changes are reviewed, push.**

---

## Development

```bash
# Run tests (3,707 passed, 8 skipped, 0 failed)
pytest tests/ -q

# CLI help
cam --help
cam pulse --help
cam learn --help
```

---

**License**: MIT

**Created by** [deesatzed](https://github.com/deesatzed)
