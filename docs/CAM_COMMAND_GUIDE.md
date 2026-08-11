# CAM Command Guide

This guide documents the current `cam` CLI as implemented in the repository. For each command, it explains:
- what the command is for
- what it actually does
- the basic syntax
- one concrete example use case

For evidence-backed examples, tested claims, and real command transcripts, also see [CAM_PROVEN_CAPABILITIES.md](CAM_PROVEN_CAPABILITIES.md).

## Before You Start

From the repo root:

```bash
cd /Users/o2satz/multiclaw
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Basic smoke test:

```bash
.venv/bin/cam --help
.venv/bin/cam govern stats
```

If you prefer not to activate the shell environment, use `.venv/bin/cam ...` directly.

## Mental Model

CAM has four main jobs:

1. Evaluate codebases
CAM studies a repo and decides what is worth changing.

2. Create or improve code
CAM can add goals, create a new task/spec, and execute work against a repo.

3. Learn from other repos
CAM can mine folders of repos, store reusable patterns, and let you search that knowledge later.

4. Validate and benchmark
CAM can check whether a created repo matches its requested spec and whether a Forge-style output performs acceptably.

## Best Front Door

If you do not already know which command and flags you need, start with:

```bash
cam chat
```

`cam chat` is the guided entry point. It asks the follow-up questions, builds the underlying command, and lets you review it before running.

If you already know you want a build or repair workflow but the request is still ambiguous, start with:

```bash
cam preflight <repo> --request "..."
```

`cam preflight` is the structured task clarifier. It turns a vague request into an explicit contract before execution.

## Quick Workflow Map

### If you want CAM to discover and learn from the world

```bash
# Scan X for new repos
cam pulse scan --keywords "AI agent"

# Start the perpetual discovery daemon
cam pulse daemon --interval 30

# View what CAM has learned
cam learn report --limit 10

# Scan a repo for secrets before manual review
cam security scan /path/to/repo

```

### If you want CAM to improve itself

```bash
# Assess if enough knowledge has accumulated
cam self-enhance status

# Run the full clone -> enhance -> validate -> swap pipeline
cam self-enhance start
```

### If you want CAM to study a repo and improve it

```bash
cam evaluate /path/to/repo
cam enhance /path/to/repo --dry-run
cam enhance /path/to/repo
```

### If you need early project or rescue evidence without changing anything

Use CAM_Codx's Development Brief for the decision and `cam brief-query` as its
read-only primary-corpus lookup. The command needs an explicit database path:

```bash
cam brief-query "durable import retry" --db /absolute/path/to/claw.db --json
```

It does not mine, call a provider, initialize schema, record retrieval usage,
query federated siblings, or edit a target repository. CAM_Codx adds the target
inspection and labels advice as direct precedent, transferable analogy, or new
hypothesis. See [CAM_Codx integration](integrations/CAM_CODEX.md).

### If you want CAM to study outside repos and create a new app

```bash
cam mine /path/to/repo-folder --target /path/to/new-app --max-repos 4
cam ideate /path/to/repo-folder --ideas 3
cam create /path/to/new-app --repo-mode new --request "Build the chosen app"
cam validate --spec-file data/create_specs/<spec-file>.json
```

### If you want CAM to improve itself from outside repos

```bash
cam mine /path/to/repo-folder --target /Users/o2satz/multiclaw --max-repos 4
cam kb insights
cam kb search "test generation"
```

## Preferred UX Surface

Use the flat top-level verbs for the main product workflows:

- `cam chat`
- `cam evaluate`
- `cam enhance`
- `cam mine`
- `cam ideate`
- `cam preflight`
- `cam create`
- `cam validate`

Use grouped commands for advanced or supporting workflows:

- `cam doctor ...`
  - preferred for preflight and diagnostics
  - examples: `cam doctor keycheck --for mine --live`, `cam doctor status`
- `cam learn ...`
  - preferred for learning visibility and reassessment
  - examples: `cam learn delta Repo2Eval`, `cam learn report`, `cam learn reassess --task "..."`
- `cam task ...`
  - preferred for explicit operator task management
  - examples: `cam task add ...`, `cam task quickstart ...`, `cam task runbook <id>`, `cam task results`
- `cam forge ...`
  - preferred for the standalone Forge subsystem
  - examples: `cam forge export ...`, `cam forge benchmark ...`
- `cam kb ...`
  - lower-level knowledge browser

The older flat commands still work. The grouped paths are the preferred UX.

## Top-Level Commands

## `cam brief-query`

Purpose:
Read a supplied primary `claw.db` for a narrow, provenance-bearing methodology
lookup without the normal retrieval side effects.

What it does:
- opens the exact `--db` path with SQLite read-only immutable access
- queries FTS rows directly and returns source/provenance fields
- avoids schema initialization, WAL, embeddings, telemetry, federation,
  provider calls, and mining

Syntax:

```bash
cam brief-query QUERY --db /absolute/path/to/claw.db --json
```

Example use case:
You are starting an import workflow and want CAM_Codx to find prior methods
without mutating the knowledge corpus.

```bash
cam brief-query "durable import retry" --db /absolute/path/to/claw.db --json
```

Use this as the runtime component of CAM_Codx's Development Brief, not as a
claim that a search result is automatically applicable. The Development Brief
adds target inspection, evidence labels, limitations, and a smallest next step.

## `cam chat`

Purpose:
Provide a conversational front door for common CAM workflows.

What it does:
- starts an interactive REPL
- detects workflow intent from plain language
- asks the minimum high-value follow-up questions
- prints the concrete `cam ...` command it recommends
- can run the generated command immediately

Current scope:
- mining workflow is wired end-to-end
- create/preflight guidance is present, but full guided execution for every workflow is not yet wired

Syntax:

```bash
cam chat
```

Example use case:
You want to mine a folder but do not want to remember the flag set.

```text
cam chat
cam> I want to mine the folder ./folderx
```

## `cam preflight`

Purpose:
Examine a requested task before build execution and produce a reusable task contract.

What it does:
- restates the task in concrete engineering terms
- identifies likely deliverable and definition of done
- surfaces hard blockers and unresolved assumptions
- asks clarifying questions, separated by importance
- estimates time, budget, and execution shape
- writes a reusable artifact under `data/preflights/`

Syntax:

```bash
cam preflight <repo> --request "..." [--repo-mode fixed|augment|new] [--spec "..."] [--answer "..."] [--preflight-file path.json] [--live]
```

Key options:
- `--answer`: record operator answers directly into the preflight artifact
- `--preflight-file`: reuse a prior preflight artifact and merge its answers
- `--live`: allow LLM-enriched preflight output instead of heuristic-only output

Example use case:
You want CAM to apply patterns from another repo but need the contract tightened before execution.

```bash
cam preflight /Users/o2satz/projects/health-intake \
  --repo-mode new \
  --request "Apply everything repo-A does to a related healthcare intake workflow" \
  --answer "Delivery surface: web app" \
  --answer "Compliance: no PHI or PII, standard security only"
```

## `cam evaluate`

Purpose:
Analyze a single repository and score its enhancement potential.

What it does:
- runs structural repo analysis
- can run a full or partial evaluation battery through agents
- stores evaluation results in the SQLite database
- helps CAM decide what is worth working on next

Syntax:

```bash
cam evaluate <repo> [--mode auto|full|quick|structural] [--config claw.toml]
```

Modes:
- `auto`: use full evaluation if agents are configured, otherwise structural only
- `full`: structural analysis plus the full evaluation battery
- `quick`: structural analysis plus a smaller prompt set
- `structural`: no agent calls; just inspect the repo structure

Example use case:
You found a repo and want to know if CAM thinks it is worth improving.

```bash
cam evaluate /Users/o2satz/projects/my-app --mode quick
```

## `cam enhance`

Purpose:
Run CAM’s main improvement loop on one repository.

What it does:
- evaluates the repo
- plans tasks
- dispatches tasks to agents
- verifies outcomes
- records results back into CAM memory

Syntax:

```bash
cam enhance <repo> [--mode attended|supervised|autonomous] [--max-tasks N] [--battery] [--dry-run] [--task-id <uuid>]
```

Key options:
- `--mode`: autonomy level
- `--max-tasks`: cap the number of tasks processed
- `--battery`: use the full evaluation battery first
- `--dry-run`: preview tasks without executing changes
- `--task-id <uuid>`: target a specific pending task id instead of the highest-priority task. Skips the evaluate/plan phases and runs exactly one cycle against that task. The task must already exist in `pending` state (created by `cam ab-test start`, manual seeding, or a prior evaluate run).

Example use case:
You want CAM to propose and then execute a bounded improvement pass on an app.

```bash
cam enhance /Users/o2satz/projects/my-app --mode attended --max-tasks 3
```

Targeted example: execute one specific pending task you seeded earlier:

```bash
cam enhance /Users/o2satz/projects/my-app --task-id 3f1e4b2c-9a21-4e5d-8c77-baf012345678
```

## `cam fleet-enhance`

Purpose:
Run enhancement across many repos in one folder.

What it does:
- scans a directory for repos
- ranks them by enhancement potential
- allocates budget across the fleet
- runs enhancement in ranked order
- works on branches, not directly on `main`

Syntax:

```bash
cam fleet-enhance <repos_dir> [--mode supervised] [--max-repos N] [--max-tasks N] [--budget USD] [--strategy proportional|equal]
```

Example use case:
You have 20 internal repos and want CAM to spend effort only on the highest-value ones.

```bash
cam fleet-enhance /Users/o2satz/workspace/repos --max-repos 5 --budget 30
```

## `cam results`

Purpose:
Show prior task execution results stored in the database.

What it does:
- lists recent task outcomes
- lets you filter by project
- helps you review what CAM already tried

Syntax:

```bash
cam results [--limit N] [--project PROJECT_ID]
```

Example use case:
You want to inspect recent CAM executions after a session.

```bash
cam results --limit 10
```

Preferred grouped alias:

```bash
cam task results --limit 10
```

## `cam status`

Purpose:
Show CAM system status.

What it does:
- prints overall CAM runtime/database status
- useful as a quick health check

Syntax:

```bash
cam status
```

---

## PULSE Discovery System

The PULSE (Perpetual Unified Learning Swarm Engine) commands handle autonomous repo discovery, ingestion, freshness monitoring, and knowledge maintenance.

### `cam pulse preflight`

Purpose: Validate xAI key and model configuration before scanning.

```bash
cam pulse preflight [--config PATH]
```

### `cam pulse scan`

Purpose: Scan X (formerly Twitter) for GitHub repos matching keywords. Uses Grok's native `x_search` via xAI Responses API.

```bash
cam pulse scan KEYWORDS... [--limit 50] [--mode auto|preview|live] [--novelty 0.85] [--force] [--skip-dedup] [--verbose] [--config PATH]
```

| Flag | Default | What it does |
|------|---------|--------------|
| `--limit` | 50 | Max repos to fetch |
| `--mode` | auto | `auto` (scan+mine), `preview` (scan only), `live` (full pipeline) |
| `--novelty` | 0.85 | Preset novelty score threshold (0.0-1.0) |
| `--force` | false | Re-scan even if URLs already known |
| `--skip-dedup` | false | Bypass novelty-filter dedup check |

Example:
```bash
cam pulse scan --keywords "AI agent framework" --mode auto --novelty 0.85
```

### `cam pulse daemon`

Purpose: Start a perpetual discovery loop that scans X and assimilates repos automatically.

```bash
cam pulse daemon [--interval 30] [--max-per-cycle 10] [--retries 3] [--verbose] [--config PATH]
```

| Flag | Default | What it does |
|------|---------|--------------|
| `--interval` | 30 | Polling interval in seconds |
| `--max-per-cycle` | 10 | Max repos per cycle |
| `--retries` | 3 | Retry failed assimilations |

### `cam pulse ingest`

Purpose: Ingest prescreened repos directly, bypassing X-Scout discovery. Accepts **both GitHub and HuggingFace URLs**.

```bash
cam pulse ingest URL... [--novelty 0.95] [--force] [--verbose] [--config PATH]
```

URL types supported:
- `https://github.com/owner/repo` — Standard GitHub mining
- `https://huggingface.co/owner/repo` — Tiered HF mining (micro: full clone, standard/large: metadata-only API)

Example:
```bash
# GitHub repo
cam pulse ingest https://github.com/bytedance/deer-flow

# HuggingFace model repo
cam pulse ingest https://huggingface.co/microsoft/phi-3-mini-4k-instruct

# Multiple URLs at once
cam pulse ingest https://github.com/org/repo1 https://huggingface.co/org/model2 --force
```

### `cam pulse ingest-hf`

Purpose: Ingest HuggingFace repos by ID (not URL) with revision control. Uses hf-mount or fallback download.

```bash
cam pulse ingest-hf REPO_IDS... [--revision main] [--force] [--verbose] [--config PATH]
```

| Flag | Default | What it does |
|------|---------|--------------|
| `--revision` | main | Git revision to mount (branch, tag, SHA) |
| `--force` | false | Re-ingest even if already assimilated |

Tier classification:
- **micro** (< 100 MB): Full clone — complete extraction
- **standard** (100 MB – 2 GB): Metadata-only — README + config.json via HF Hub API
- **large** (> 2 GB): Metadata-only — avoids multi-GB weight downloads

Example:
```bash
cam pulse ingest-hf d4data/biomedical-ner-all --revision main
```

### `cam pulse freshness`

Purpose: Check all tracked repos for staleness and report significance scores.

```bash
cam pulse freshness [--verbose] [--auto-refresh] [--seed] [--dry-run] [--config PATH]
```

| Flag | Default | What it does |
|------|---------|--------------|
| `--verbose` | false | Show significance scores and details |
| `--auto-refresh` | false | Automatically re-mine stale repos |
| `--seed` | false | Populate freshness metadata for repos with NULL values |
| `--dry-run` | false | Check freshness without modifying database |

How it works:
- **Phase 1**: ETag-cached metadata check. Unchanged repos cost 0 API rate limit points (HTTP 304).
- **Phase 2**: Significance scoring: commits since mine (30%), new releases (40%), README changes (20%), repo size delta (10%).
- Only repos with significance >= 0.4 (configurable in `claw.toml`) trigger re-mine.

Example:
```bash
# Check staleness
cam pulse freshness --verbose

# Seed metadata for existing repos, then check
cam pulse freshness --seed --verbose

# Auto-refresh stale repos
cam pulse freshness --auto-refresh
```

### `cam pulse refresh`

Purpose: Re-mine a specific repo or all stale repos. Old methodologies transition to `declining`.

```bash
cam pulse refresh [URL] [--all] [--force] [--dry-run] [--no-backup] [--verbose] [--config PATH]
```

| Flag | Default | What it does |
|------|---------|--------------|
| `--all` | false | Refresh all stale repos |
| `--force` | false | Skip significance check and confirmation prompts |
| `--dry-run` | false | Preview what would be refreshed without modifying |
| `--no-backup` | false | Skip pre-refresh database backup |

Example:
```bash
# Re-mine a specific repo
cam pulse refresh https://github.com/bytedance/deer-flow

# Re-mine all stale repos
cam pulse refresh --all

# Preview only
cam pulse refresh --all --dry-run
```

### `cam pulse status`

Purpose: Show current PULSE ingestion statistics.

```bash
cam pulse status
```

### `cam pulse discoveries`

Purpose: Browse recent X-scan discoveries with status.

```bash
cam pulse discoveries [--limit 20]
```

### `cam pulse scans`

Purpose: Show scan history.

```bash
cam pulse scans
```

### `cam pulse report`

Purpose: Daily assimilation report.

```bash
cam pulse report [--date YYYY-MM-DD]
```

---

## Security Scanner

The security commands handle pre-assimilation secret scanning to prevent leaked credentials from entering the knowledge base.

### `cam security scan`

Purpose: Scan a directory for hardcoded secrets, API keys, and credentials using TruffleHog (with regex fallback).

```bash
cam security scan PATH [--json] [--timeout 60]
```

| Flag | Default | What it does |
|------|---------|--------------|
| `PATH` | required | Directory to scan |
| `--json` | false | Output results as JSON |
| `--timeout` | 60 | TruffleHog subprocess timeout in seconds |

How it works:
- **TruffleHog available**: Runs `trufflehog filesystem <path> --json --no-verification` — detects 800+ credential types with high precision
- **TruffleHog not available**: Falls back to built-in regex scanner with 11 high-value patterns (AWS AKIA, GitHub PAT, Slack tokens, Stripe keys, PEM private keys, GCP service accounts, etc.)
- Findings are classified by severity: CRITICAL, HIGH, MEDIUM, LOW
- CRITICAL findings (verified credentials, private keys, Stripe live keys) are highlighted in red
- File paths are shown relative to the scanned directory

Example:
```bash
# Scan a directory for secrets
cam security scan /path/to/repo

# JSON output for CI integration
cam security scan /path/to/repo --json
```

### `cam security status`

Purpose: Show TruffleHog availability and current security scanner configuration.

```bash
cam security status
```

What it shows:
- Whether TruffleHog is installed and its version
- Current `[security]` config from `claw.toml`:
  - `secret_scan_enabled` — whether scanning is active
  - `secret_scan_fail_on_critical` — whether critical findings block assimilation
  - `secret_scan_timeout_seconds` — subprocess timeout
  - `secret_scan_filter_in_serializer` — whether Gate 2 file filtering is active

Example:
```bash
cam security status
# TruffleHog: AVAILABLE (v3.94.1)
# Secret scanning: ENABLED
# Fail on critical: YES
# Timeout: 60s
# Filter in serializer: YES
```


---

## `cam doctor expectations`

Show whether the current runtime satisfies CAM's core product expectations.

What it does:
- prints the current charter-level expectations
- checks whether learning, reassessment, and validation foundations are wired
- reports whether CAM currently has any real build execution path
- tells you whether `create --execute` / `enhance` should be treated as real build workflows or planning-only workflows

Syntax:

```bash
cam doctor expectations [--config claw.toml]
```

Example use case:

You want to know whether the current agent/runtime configuration can honestly be treated as a real builder before you spend time on `create --execute`.

```bash
cam doctor expectations
```

## `cam doctor audit`

Audit high-trust methodologies for evidence quality.

What it does:
- reviews promotion-sensitive methodologies:
  - `thriving`
  - or `global` methods that have real usage/success history
- shows how many are backed by attribution evidence vs legacy/raw-success counters
- flags methods with weak expectation-match evidence
- gives you a short list of the specific methodologies that need review

Syntax:

```bash
cam doctor audit [--limit 10] [--expectation-threshold 0.65] [--json-out audit.json] [--fail-on-flags] [--config claw.toml]
```

Use this after:
- a mine + reassess cycle
- a batch of create/enhance executions
- before treating promoted/global knowledge as trustworthy

Example:

```bash
cam doctor audit --limit 10
```

CI-style example:

```bash
cam doctor audit --limit 10 --json-out doctor_audit.json --fail-on-flags
```

Example use case:
You want to confirm CAM is configured and the database is reachable.

```bash
cam status
```

## `cam runbook`

Purpose:
Inspect the planned execution steps for a task.

What it does:
- shows the task’s execution steps
- shows acceptance checks
- helps you inspect what CAM intends to do before running it

Syntax:

```bash
cam runbook <task_id>
```

Example use case:
You created a task and want to inspect its plan before execution.

```bash
cam runbook task_abc123
```

Preferred grouped alias:

```bash
cam task runbook task_abc123
```

## `cam quickstart`

Purpose:
Create a goal quickly, preview the runbook, and optionally execute immediately.

What it does:
- creates a task for a repo
- lets you attach steps and checks
- previews the runbook
- can execute the task immediately

Syntax:

```bash
cam quickstart <repo> --title "..." --description "..." [--type bug_fix] [--step "..."] [--check "..."] [--execute]
```

Example use case:
You want a fast path to tell CAM, “fix this thing,” without manually building the task structure.

```bash
cam quickstart /Users/o2satz/projects/my-app \
  --title "Repair failing tests" \
  --description "Fix the broken auth tests and restore green CI" \
  --check "pytest -q" \
  --preview
```

Preferred grouped alias:

```bash
cam task quickstart /Users/o2satz/projects/my-app \
  --title "Repair failing tests" \
  --description "Fix the broken auth tests and restore green CI" \
  --check "pytest -q" \
  --preview
```

## `cam create`

Purpose:
Create a fixed repo, augmented repo, or brand-new repo from a requested outcome.

What it does:
- can auto-run preflight for risky, ambiguous, or expensive tasks
- writes a creation spec JSON under `data/create_specs/`
- creates a real CAM task tied to the target repo
- can preview the runbook
- can execute the task immediately
- can use prior mined CAM knowledge when relevant
- blocks `--execute` if hard blockers remain or if must-clarify questions are unresolved
- supports explicit operator override via `--accept-preflight-defaults`

Syntax:

```bash
cam create <repo> --request "..." [--repo-mode fixed|augment|new] [--spec "..."] [--step "..."] [--check "..."] [--preflight] [--preflight-live] [--answer "..."] [--preflight-file path.json] [--accept-preflight-defaults] [--namespace-safe-retry] [--execute] [--max-minutes N]
```

Repo modes:
- `fixed`: repair an existing repo
- `augment`: add capabilities to an existing repo
- `new`: create a new repo/project outcome

Important execution behavior:
- `--auto-preflight` is on by default
- risky `create --execute` requests will preflight first even if you do not pass `--preflight`
- if preflight finds unresolved must-clarify questions, execution stops until you answer them or explicitly pass `--accept-preflight-defaults`
- if preflight finds hard blockers, execution does not proceed
- in `repo-mode fixed`, CAM now rejects runs that introduce a new top-level source namespace unless that was explicitly requested
- `--namespace-safe-retry` (enabled by default) auto-runs one constrained retry in `repo-mode fixed` when execution is rejected for `new_source_namespace`

Example use case:
You want CAM to build a new standalone app using prior mined knowledge.

```bash
cam create /Users/o2satz/projects/embedding-worker \
  --repo-mode new \
  --request "Create a standalone CLI that reads a CAM knowledge pack and proposes finetuning jobs for small models" \
  --spec "Must be standalone" \
  --spec "Must not import CAM runtime code" \
  --check "pytest -q" \
  --max-minutes 20
```

Example with reusable preflight answers:

```bash
cam create /Users/o2satz/projects/health-intake \
  --repo-mode new \
  --request "Apply everything repo-A does to a related healthcare intake workflow" \
  --preflight-file data/preflights/<prior-artifact>.json \
  --answer "Acceptance checks: pytest -q and python -m app.cli --help" \
  --execute
```

### Metric Expectations in Specs

When you write natural language specs for `cam create`, CAM auto-extracts structured metric targets from the text:

| Natural Language | Extracted Metric |
|-----------------|-----------------|
| `"greater than 90 percent coverage"` | `MetricExpectation(min_coverage_pct, gte, 90, hard=True)` |
| `"at least 20 tests"` | `MetricExpectation(min_test_count, gte, 20, hard=True)` |
| `"no more than 5 files changed"` | `MetricExpectation(max_files_changed, lte, 5, hard=True)` |

Supported metrics:
- `min_coverage_pct` — Extracts from `pytest --cov` TOTAL line
- `min_test_count` — Extracts from `pytest` summary line
- `min_files_changed` / `max_files_changed` — Counts workspace diff

Operators: `gte` (>=), `gt` (>), `lte` (<=), `lt` (<), `eq` (==)

Enforcement:
- **Hard** expectations block approval if not met
- **Soft** expectations generate recommendations only

Example:
```bash
cam create /path/to/repo --repo-mode new \
  --request "Build a plugin system with at least 10 tests and greater than 80 percent coverage" \
  --check "pytest --cov=src tests/ -v" \
  --execute
```

CAM will auto-extract `min_test_count >= 10` and `min_coverage_pct >= 80` as hard gates.

---

## `cam add-goal`

Purpose:
Add a custom goal/task to a repository without going through full creation flow.

What it does:
- creates a task in CAM’s database
- records title, description, type, priority, steps, and checks
- is intended to be picked up by later enhancement runs

Syntax:

```bash
cam add-goal <repo> --title "..." --description "..." [--type analysis|testing|documentation|security|refactoring|bug_fix|architecture|dependency_analysis] [--step "..."] [--check "..."]
```

Example use case:
You know exactly what CAM should investigate next and want that stored as a task.

```bash
cam add-goal /Users/o2satz/multiclaw \
  --title "Evaluate finetuning path" \
  --description "Design a practical small-model finetuning path for CAM where it is clearly worth the cost" \
  --type architecture
```

Preferred grouped alias:

```bash
cam task add /Users/o2satz/multiclaw \
  --title "Evaluate finetuning path" \
  --description "Design a practical small-model finetuning path for CAM where it is clearly worth the cost" \
  --type architecture
```

## `cam ideate`

Purpose:
Generate novel app ideas using CAM’s stored knowledge plus candidate repos in a folder.

What it does:
- discovers repos or source trees in a directory
- pulls repo-specific findings CAM already mined
- pulls high-potential and high-novelty CAM methodologies
- asks an LLM for new standalone app concepts
- writes JSON and Markdown ideation artifacts to `data/ideation/`
- can optionally promote one idea into a real `cam create` task/spec

Syntax:

```bash
cam ideate <directory> [--focus "..."] [--ideas 3] [--max-repos 4] [--depth 3] [--agent claude|codex|gemini|grok] [--promote N --target-repo /path/to/repo --repo-mode new] [--max-minutes N]
```

Example use case:
You want CAM to propose three new app concepts from a folder of candidate repos.

```bash
cam ideate /Users/o2satz/multiclaw/Repo2Eval \
  --focus "Invent useful standalone apps that combine CAM knowledge with these repos" \
  --ideas 3 \
  --max-repos 4
```

Example with promotion:

```bash
cam ideate /Users/o2satz/multiclaw/Repo2Eval \
  --focus "Invent a standout standalone app around finetuning or build automation" \
  --ideas 3 \
  --promote 1 \
  --target-repo /Users/o2satz/projects/new-app-from-cam \
  --repo-mode new
```

## `cam mine`

Purpose:
Study a folder of repos and extract reusable patterns, features, and ideas.

What it does:
- scans a directory for git repos and source-tree style repos
- analyzes each repo via LLM
- stores transferable findings in CAM semantic memory
- can generate enhancement tasks for a target project
- supports scan-only preview mode with no model calls
- keeps a persistent mining ledger so unchanged repos are skipped by default

Syntax:

```bash
cam mine <directory> [--target /path/to/project] [--max-repos N] [--min-relevance 0.6] [--tasks/--no-tasks] [--depth N] [--dedup/--no-dedup] [--skip-known/--no-skip-known] [--force-rescan] [--scan-only] [--live-keycheck/--no-live-keycheck] [--max-minutes N]
```

Key options:
- `--target`: where the mined findings should be considered relevant
- `--min-relevance`: threshold for task generation
- `--scan-only`: preview discovered repos without spending model calls
- `--skip-known`: skip repos already mined when unchanged
- `--force-rescan`: ignore the mining ledger and rescan selected repos
- `--live-keycheck`: validate required provider keys with tiny real calls before live mining
- `--tasks`: whether to generate tasks from findings
- `--yield-sort/--no-yield-sort`: sort candidates by expected knowledge yield before mining (enabled by default). Yield-priority scoring ranks repos by recency, file count, source kind, canonical sibling overlap, and size efficiency. Data from 90+ mined repos shows 20-30x yield variance per token spent.

Example use case: improve CAM itself

```bash
cam keycheck --for mine --live
cam mine /Users/o2satz/multiclaw/Repo2Eval \
  --target /Users/o2satz/multiclaw \
  --max-repos 4 \
  --max-minutes 20
```

Example use case: check a folder again later without wasting tokens

```bash
cam mine /Users/o2satz/multiclaw/Repo2Eval \
  --scan-only \
  --max-repos 10
```

If CAM says `Will mine: 0`, the selected repos are unchanged and would be skipped.

By default, live `cam mine` also validates provider access before starting. If you want the preflight separately:

```bash
cam keycheck --for mine --live
```

If you know you want to rerun them anyway:

```bash
cam mine /Users/o2satz/multiclaw/Repo2Eval \
  --max-repos 10 \
  --force-rescan
```

If you explicitly want to skip the built-in live provider validation:

```bash
cam mine /path/to/repos --no-live-keycheck
```

## `cam mine-report`

Purpose:
Inspect a repo folder against CAM’s persistent mining ledger before spending tokens.

What it does:
- discovers repos/source trees in a directory
- compares each one against the mining ledger
- shows whether each repo is `new`, `changed`, or `unchanged`
- shows when a repo was last mined and how many findings/tokens were recorded

Syntax:

```bash
cam mine-report <directory> [--depth N] [--dedup/--no-dedup] [--changed-only]
```

Example use case:
You added more repos to `Repo2Eval` and want to know what actually needs scanning.

```bash
cam mine-report /Users/o2satz/multiclaw/Repo2Eval --depth 3
```

Example use case: only show the repos that would justify fresh work

```bash
cam mine-report /Users/o2satz/multiclaw/Repo2Eval --depth 3 --changed-only
```

## `cam keycheck`

Purpose:
Preflight API keys before you start a live model-backed command.

What it does:
- checks whether the required env vars are present for a command path
- with `--live`, runs tiny real provider calls so invalid keys fail before longer work starts
- currently supports `mine` and `ideate`

Syntax:

```bash
cam keycheck --for mine|ideate [--live]
```

Example use case:
You want to confirm `mine` will not fail on missing or invalid provider credentials.

```bash
cam keycheck --for mine --live
```

Preferred grouped alias:

```bash
cam doctor keycheck --for mine --live
```

## `cam assimilation-delta`

Purpose:
Show what recent mine runs actually added, not just how mature the existing memory is.

What it does:
- reads the mining ledger for recently mined repos
- resolves methodologies created by those mine runs
- resolves action templates created by those mine runs
- summarizes:
  - new capabilities/domains
  - possible new features or updates
  - top new methodologies that are candidates for operationalization

Syntax:

```bash
cam assimilation-delta [directory] [--depth N] [--since-hours 24] [--latest N]
```

Example use case:
You want to know whether the last mine run added anything concrete or just noise.

```bash
cam assimilation-delta /Users/o2satz/multiclaw/Repo2Eval --depth 4 --since-hours 24 --latest 10
```

Preferred grouped alias:

```bash
cam learn delta /Users/o2satz/multiclaw/Repo2Eval --depth 4 --since-hours 24 --latest 10
```

## `cam assimilation-report`

Purpose:
Show whether CAM’s assimilated knowledge is merely stored, actively reused, operationalized, or proven useful.

What it does:
- classifies methodologies into continuum stages:
  - `stored`
  - `enriched`
  - `retrieved`
  - `operationalized`
  - `proven`
- separately flags high-potential methodologies that may become useful later
- uses existing metadata like:
  - retrieval counts
  - success counts
  - capability metadata
  - potential score
  - linked action templates

Syntax:

```bash
cam assimilation-report [--limit N] [--future-threshold 0.65]
```

Example use case:
You want to know whether CAM’s mined knowledge is real operational fuel or just archived memory.

```bash
cam assimilation-report --limit 10
```

Example use case:
You want to raise the bar for what counts as a future candidate.

```bash
cam assimilation-report --limit 15 --future-threshold 0.75
```

Preferred grouped alias:

```bash
cam learn report --limit 10
```

## `cam reassess`

Purpose:
Actively re-score old methodologies against a new task so CAM can decide what prior knowledge should be revived now.

What it does:
- takes a task description and optional repo context
- derives activation triggers from prior methodologies
- scores methodologies against the new task using:
  - task/repo keyword overlap
  - potential score
  - novelty
  - retrieval evidence
  - success evidence
  - action-template presence
- separates “recommended now” from “future watchlist”
- explains why each recommendation was surfaced

Syntax:

```bash
cam reassess [repo] --task "..." [--limit N] [--min-score 0.2] [--future-threshold 0.65]
```

Example use case:
You want CAM to reactivate prior knowledge for a repo repair task instead of just showing stored memory.

```bash
cam reassess --task "repair broken tests with ast-based refactoring" --limit 10
```

Example use case:
You want repo context to influence what CAM revives.

```bash
cam reassess /path/to/repo --task "add evaluation and rollback for finetuning pipeline" --limit 10
```

Preferred grouped alias:

```bash
cam learn reassess /path/to/repo --task "add evaluation and rollback for finetuning pipeline" --limit 10
```

Example use case: support a new app build

```bash
cam mine /Users/o2satz/multiclaw/Repo2Eval \
  --target /Users/o2satz/projects/new-app \
  --max-repos 4 \
  --max-minutes 20
```

## `cam forge-export`

Purpose:
Export CAM memory into a standalone Forge knowledge pack.

What it does:
- reads CAM methodologies and tasks from the database
- writes a neutral JSONL knowledge pack
- gives outside tools/apps a way to use CAM knowledge without importing CAM runtime

Syntax:

```bash
cam forge-export [--out data/cam_knowledge_pack.jsonl] [--db path/to/claw.db] [--max-methodologies N] [--max-tasks N] [--max-minutes N]
```

Example use case:
You want a standalone app to consume CAM’s learned knowledge.

```bash
cam forge-export \
  --out data/cam_knowledge_pack.jsonl \
  --max-methodologies 200 \
  --max-tasks 200
```

Preferred grouped alias:

```bash
cam forge export \
  --out data/cam_knowledge_pack.jsonl \
  --max-methodologies 200 \
  --max-tasks 200
```

## `cam forge-benchmark`

Purpose:
Run the standalone Forge regression benchmark with a wall-clock limit.

What it does:
- executes the standalone benchmark harness
- compares Forge-style output against the baseline retrieval path
- writes benchmark summary artifacts to an output directory

Syntax:

```bash
cam forge-benchmark [--repo PATH] [--note PATH] [--knowledge-pack PATH] [--out PATH] [--max-minutes N]
```

Example use case:
You changed the standalone Forge flow and want a fixed regression check.

```bash
cam forge-benchmark --max-minutes 5
```

Preferred grouped alias:

```bash
cam forge benchmark --max-minutes 5
```

## `cam validate`

Purpose:
Check whether a created repo actually matches the saved creation spec.

What it does:
- loads a `cam create` spec JSON
- checks repo existence and baseline state
- runs executable acceptance checks
- distinguishes between shell checks and plain-English manual checks
- fails if the repo never materially changed

Syntax:

```bash
cam validate --spec-file data/create_specs/<spec-file>.json [--max-minutes N]
```

Example use case:
You asked CAM to build something and want to know whether it actually delivered.

```bash
cam validate --spec-file data/create_specs/20260314-my-app-create-spec.json
```

## `cam benchmark`

Purpose:
Benchmark Forge output after validation.

What it does:
- runs the benchmark harness on a repo, note, and knowledge pack
- writes output metrics
- is intended to be a performance/quality step, not the first validation step

Syntax:

```bash
cam benchmark [--repo PATH] [--note PATH] [--knowledge-pack PATH] [--out PATH] [--max-minutes N]
```

Example use case:
You already validated a created app and now want a quality score comparison.

```bash
cam benchmark --out data/forge_benchmark_after_validation
```

## `cam govern`

Purpose:
Manage and inspect CAM’s memory governance layer.

What it does:
Depending on the action, it can:
- show memory counts and DB usage
- run a governance sweep
- garbage-collect dead methodologies
- enforce quota
- prune old episodes

Syntax:

```bash
cam govern [stats|sweep|gc|quota|prune|bandit-stats]
```

Actions:
- `stats`: show current governance stats
- `sweep`: run a full governance sweep
- `gc`: garbage collect dead methodologies
- `quota`: enforce methodology quota
- `prune`: prune old episodes
- `bandit-stats`: show RL bandit statistics — top methodology x task_type pairs, win rates, Thompson graduation status

Example use case:
You want to see whether CAM’s memory database is healthy.

```bash
cam govern stats
```

You want to see which methodologies are winning per task type and whether Thompson sampling has activated.

```bash
cam govern bandit-stats
```

## `cam setup`

Purpose:
Configure API keys, models, and agent settings interactively.

What it does:
- walks through agent/provider configuration
- writes settings into `claw.toml`

Syntax:

```bash
cam setup
```

Example use case:
You cloned CAM on a new machine and need to configure models and keys.

```bash
cam setup
```

## `cam synergies`

Purpose:
Show CAM’s capability synergy graph summary.

What it does:
- reports synergy relationships between learned capabilities
- can show detailed edge lists with `--verbose`
- helps identify which ideas combine well across repos/domains

Syntax:

```bash
cam synergies [--verbose]
```

Example use case:
You want to see which learned capabilities are reinforcing each other.

```bash
cam synergies --verbose
```

## `cam prism-demo`

Purpose:
Demonstrate CAM’s PRISM multi-scale embedding concept.

What it does:
- runs the PRISM demonstration path
- is mainly a demo/inspection command rather than a normal production workflow

Syntax:

```bash
cam prism-demo [--verbose]
```

Example use case:
You want to inspect the PRISM embedding demo behavior.

```bash
cam prism-demo
```

## `cam kb` Knowledge Browser

The `kb` group lets you inspect what CAM has already learned.

### `cam kb insights`

Purpose:
Show the high-level knowledge summary.

What it does:
- top capabilities
- domain map
- synergy highlights
- score distributions

Syntax:

```bash
cam kb insights
```

Example:

```bash
cam kb insights
```

### `cam kb search`

Purpose:
Search learned capabilities with natural language.

What it does:
- uses hybrid vector plus full-text search
- returns relevant learned capabilities from CAM memory

Syntax:

```bash
cam kb search "<query>" [--limit N]
```

Example:

```bash
cam kb search "repo repair and test generation" --limit 5
```

### `cam kb capability`

Purpose:
Inspect one specific capability in detail.

What it does:
- shows the full capability record
- shows related items and synergies
- accepts a full ID or an ID prefix

Syntax:

```bash
cam kb capability <capability_id_or_prefix>
```

Example:

```bash
cam kb capability 4f1d2a
```

### `cam kb domains`

Purpose:
Show the domain landscape of CAM’s learned knowledge.

What it does:
- groups capabilities into domains
- highlights bridge areas between domains

Syntax:

```bash
cam kb domains
```

Example:

```bash
cam kb domains
```

### `cam kb synergies`

Purpose:
Show the strongest synergy edges in CAM memory.

What it does:
- surfaces cross-repo and cross-domain combinations
- helps identify promising syntheses

Syntax:

```bash
cam kb synergies [--limit N]
```

Example:

```bash
cam kb synergies --limit 15
```

### `cam kb seed`

Purpose:
Load built-in seed knowledge into the methodology store. Runs automatically on first startup.

What it does:
- discovers seed packs in `src/claw/data/seed/` (shipped with the package)
- parses JSONL records and tags each with `origin:seed`
- checks if seeding is needed (skips if seed records already exist)
- imports each record into methodologies + FTS5 + embeddings (3-part write)
- records content hashes for idempotent dedup

Syntax:

```bash
cam kb seed [--force] [--repair-embeddings] [--verbose] [--config PATH]
```

Key options:
- `--force`: re-seed even if seed records already exist in the database
- `--repair-embeddings`: generate missing embeddings for existing methodologies (useful when first run had no `GOOGLE_API_KEY`)
- `--verbose`: show detailed import progress and debug output

Example: first-time seeding (happens automatically):

```bash
cam govern stats    # This triggers factory startup, which auto-seeds
```

Example: re-seed after data reset:

```bash
cam kb seed --force --verbose
```

Example: fix missing embeddings after adding an API key:

```bash
cam kb seed --repair-embeddings
```

Note: Seed knowledge is protected from lifecycle decay — `origin:seed` tagged methodologies never drop below `viable` but can promote to `thriving` when proven through real use. The seed pack ships 31 curated methodologies covering CAM's own algorithms.

## Recommended Workflows

## Workflow 0: Let CAM guide you to the right command

```bash
cam chat
```

Use this when:
- you know the goal but not the right flags
- you want CAM to ask the missing high-value questions first

## Workflow A: Review a repo before asking CAM to change it

```bash
cam evaluate /path/to/repo --mode quick
cam enhance /path/to/repo --dry-run
cam runbook <task_id>
```

## Workflow B: Improve CAM using outside repos

```bash
cam mine /path/to/repo-folder --target /Users/o2satz/multiclaw --max-repos 4
cam kb insights
cam kb search "small model finetuning"
cam synergies
```

## Workflow C: Use CAM to help design a new non-CAM app

```bash
cam mine /path/to/repo-folder --target /path/to/new-app --max-repos 4
cam ideate /path/to/repo-folder --ideas 3
cam preflight /path/to/new-app --repo-mode new --request "Build the selected concept"
cam create /path/to/new-app --repo-mode new --request "Build the selected concept"
cam validate --spec-file data/create_specs/<spec-file>.json
```

## Workflow D: Export CAM knowledge to a standalone tool

```bash
cam forge-export --out data/cam_knowledge_pack.jsonl
cam benchmark --knowledge-pack data/cam_knowledge_pack.jsonl
```

## Practical Notes

- `cam mine` is for learning from repos. It does not itself create the new app.
- `cam ideate` is for proposing new app concepts from learned knowledge plus repo inputs.
- `cam preflight` is the contract-clarifier for ambiguous or expensive tasks.
- `cam create` is the command that turns a requested outcome into a task/spec and optional execution.
- `cam validate` should happen before `cam benchmark`.
- `cam benchmark` is about quality/performance measurement, not first-pass correctness.
- `cam forge-export` is the clean bridge from CAM memory into a standalone non-CAM app.

## One-Line Summary Per Command

- `chat`: guided conversational entry point
- `evaluate`: inspect one repo and score it
- `enhance`: run CAM’s improvement loop on one repo
- `fleet-enhance`: run enhancement across many repos
- `results`: show prior task outcomes
- `status`: show system health/status
- `runbook`: inspect a task’s execution plan
- `quickstart`: create a goal and optionally run it fast
- `preflight`: clarify a task, estimate work, and save the task contract
- `create`: define and optionally execute a requested repo outcome
- `add-goal`: manually add a task to a repo
- `ideate`: invent app concepts from CAM memory plus candidate repos
- `mine`: learn from a folder of repos
- `forge-export`: export CAM memory for outside use
- `forge-benchmark`: benchmark the standalone Forge path
- `validate`: check whether a created repo meets its saved spec
- `benchmark`: measure Forge quality after validation
- `govern`: inspect and maintain CAM memory governance
- `setup`: configure keys and models
- `synergies`: inspect capability interactions
- `prism-demo`: run the PRISM embedding demo
- `kb insights/search/capability/domains/synergies`: browse CAM’s learned knowledge
- `pulse preflight`: validate xAI key and model before scanning
- `pulse scan`: scan X for repos developers are sharing
- `pulse daemon`: start perpetual discovery polling loop
- `pulse ingest`: ingest prescreened GitHub/HuggingFace repos
- `pulse ingest-hf`: ingest HuggingFace repos by ID with revision
- `pulse freshness`: check tracked repos for staleness
- `pulse refresh`: re-mine stale repos with methodology retirement
- `pulse status`: show PULSE ingestion statistics
- `pulse discoveries`: browse recent discoveries
- `pulse scans`: show scan history
- `pulse report`: daily assimilation report
- `security scan`: scan a directory for hardcoded secrets and credentials
- `security status`: show TruffleHog availability and scanner configuration
- `ab-test start`: schedule an A/B knowledge ablation test with adaptive margins
- `ab-test status`: check progress, sample counts, and Bayesian winner probability
- `ab-test stop`: remove the ablation test and show final results

### Kelly Routing (Infrastructure — no dedicated CLI command)

Bayesian Kelly routing is enabled via `[kelly] enabled = true` in `claw.toml`. When active, it automatically overrides static agent assignment during `cam create --execute` and task execution. Kelly computes routing weights from the `agent_scores` table in the database.

```bash
# Check agent performance data (Kelly input):
sqlite3 data/claw.db "SELECT agent_id, task_type, successes, failures, avg_quality_score FROM agent_scores ORDER BY task_type"

# Enable Kelly:
# Edit claw.toml → [kelly] → enabled = true

# Kelly routing appears in execution logs:
# "Kelly routing: task_type='architecture' -> agent 'claude' (weights: ...)"
```
