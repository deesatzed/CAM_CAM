# How to CAM-ify a Repository

**What this means**: Take an existing repo, analyze it for tools and patterns CAM knows, then enhance it to perform its original purpose — but better, smarter, and with battle-tested patterns from 250+ mined codebases.

**Audience**: CAM operators who want to upgrade a target repo using CAM's knowledge base.

---

## Automated: `cam camify`

The `cam camify` command automates this entire guide in one step:

```bash
# Basic — analyze repo and generate enhancement plan
cam camify /path/to/target-repo

# With explicit goals
cam camify /path/to/repo --goal "enhance error handling" --goal "learn for CAM KB"

# With a domain guide file
cam camify /path/to/repo --guide /path/to/repo/AI_Augment.md
```

This discovers what the repo does, cross-references with CAM's KB, and generates a step-by-step plan with concrete `cam` commands saved as markdown. Continue reading below for the manual process.

---

## The Three-Phase Pipeline

```
Phase 1: MINE   — Study the target repo, extract what it does
Phase 2: MATCH  — Cross-reference with CAM's 2,895+ learned methodologies
Phase 3: ENHANCE — Rebuild/upgrade the repo using CAM-grade patterns
```

Each phase has validation gates. No phase advances without passing.

---

## Before You Start

### Prerequisites

| Requirement | Check Command | Why |
|---|---|---|
| CAM installed and working | `cam --help` | Core tooling |
| API keys configured | `cam doctor keycheck --for mine --live` | LLM + embeddings |
| CAM KB has methodologies | `cam govern stats` | Need knowledge to apply |
| Target repo accessible | `ls /path/to/target-repo` | Must exist on disk |
| Target repo is git-managed | `cd /path/to/target-repo && git status` | Snapshot + rollback safety |

### Pre-Flight Checklist

```bash
# 1. Verify CAM is healthy
cam doctor environment

# 2. Check KB is populated (should show > 0 methodologies)
cam govern stats

# 3. Verify CAG cache is current (optional but recommended)
cam cag status

# 4. Snapshot the target repo before touching it
cd /path/to/target-repo
git stash  # or commit current work
git log --oneline -3  # note the HEAD commit for rollback
```

**Target write policy**: CAM-ify runs should default to a target branch or a CAM-owned patch artifact. Direct pushes to the target repo's `main` branch require explicit user approval for that target repo.

---

## Phase 1: MINE — Study the Target Repo

### Goal

Let CAM analyze the target repo to understand:
- What the repo does (domain, purpose, architecture)
- What tools and patterns it already uses
- What gaps exist (missing error handling, no tests, weak logging, etc.)
- What CAM knows that could upgrade it

### Step 1.1: Mine the Target Repo

```bash
cam mine /path/to/target-repo \
  --target /path/to/target-repo \
  --max-repos 1 \
  --depth 5 \
  --max-minutes 30
```

**What each flag means:**
- `--target /path/to/target-repo` — CAM learns with this repo as the enhancement target
- `--max-repos 1` — Only process this single repo
- `--depth 5` — Search 5 directories deep (increase for large monorepos)
- `--max-minutes 30` — Time cap

**What happens internally:**
1. CAM serializes all code files into context windows (900KB limit)
2. Runs 3-pass analysis:
   - **Pass 1**: Domain classification (what kind of project is this?)
   - **Pass 2**: Overlap assessment (what does CAM already know about this domain?)
   - **Pass 3**: LLM deep-dive (extract findings, identify gaps, generate tasks)
3. Stores findings as methodologies in the KB
4. Generates enhancement tasks

### Step 1.2: Inspect What CAM Learned

```bash
# See the overall picture
cam kb insights

# Search for domain-specific patterns CAM found
cam kb search "the repo's primary function"

# See what domains CAM categorized this repo under
cam kb domains

# Check for cross-pattern opportunities
cam kb synergies
```

### Step 1.3: Validate Phase 1

**Gate**: CAM must have generated findings. Check:

```bash
cam govern stats
```

- Methodology count should have increased from the pre-mine baseline
- If 0 new methodologies: the repo may be too small, or the depth was too shallow — increase `--depth` and retry

---

## Phase 2: MATCH — Cross-Reference with CAM's KB

### Goal

Identify which of CAM's 2,895+ battle-tested patterns can upgrade the target repo.

### Step 2.1: Run the Full Evaluation Battery

```bash
cam enhance /path/to/target-repo \
  --battery \
  --dry-run \
  --verbose
```

**Critical**: Use `--dry-run` first. This generates the evaluation and task plan without writing any code.

**What `--battery` does** (18-prompt deep analysis):

| Phase | Prompts | What They Detect |
|---|---|---|
| Orientation | project-context, workspace-scan | Architecture, entry points, dependencies |
| Deep Analysis | deepdive, agonyofdefeatures, driftx | Dead code, feature gaps, spec drift |
| Truth Verification | claim-gate, outcome-audit, assumption-registry | False claims, unverified assumptions |
| Quality Assessment | debt-tracker, endUXRedo, regression-scan | Tech debt, UX gaps, regression risk |
| Documentation | docsRedo, handoff | Missing docs, stale README |
| Remediation | app__mitigen | Concrete fix roadmap |

### Step 2.2: Review the Task Plan

The battery generates prioritized enhancement tasks. Review them:

```bash
# The dry-run output shows generated tasks
# Each task has: title, type, priority, recommended agent, acceptance criteria
```

**Task types CAM generates:**

| Task Type | What CAM Fixes | Agent Routed To |
|---|---|---|
| `security` | Input validation, secret leaks, auth gaps | claude |
| `testing` | Missing tests, low coverage, no fixtures | codex |
| `refactoring` | Code duplication, poor abstraction, dead code | codex |
| `error_handling` | Bare excepts, missing retry, no error classification | claude |
| `documentation` | Missing README, no API docs, stale comments | claude |
| `ci_cd` | No CI pipeline, missing lint/test gates | codex |
| `performance` | Missing caching, N+1 queries, no connection pooling | claude |
| `architecture` | Unclear boundaries, missing dependency injection | claude |
| `dependency_analysis` | Outdated deps, version conflicts, unused packages | gemini |

### Step 2.3: Validate Phase 2

**Gate**: Tasks must exist and make sense for the repo.

- Review each generated task for relevance
- Remove or skip tasks that don't apply (e.g., CI/CD tasks if the repo is a library)
- Confirm the task plan before executing

---

## Phase 3: ENHANCE — Upgrade the Repo

### Goal

Execute the enhancement tasks. CAM's agents write real code, informed by KB patterns, validated by the 7-check audit gate.

### Step 3.1: Run Enhancement (Attended Mode)

```bash
cam enhance /path/to/target-repo \
  --mode attended \
  --max-tasks 10 \
  --verbose
```

**Modes:**

| Mode | Human Involvement | When to Use |
|---|---|---|
| `attended` | Approve each task before execution | First CAM-ification, critical repos |
| `supervised` | Review results after each task | Repos you trust CAM with directionally |
| `autonomous` | CAM runs full pipeline solo | Well-tested domains, non-critical repos |

**Recommendation**: Always start with `attended` for the first CAM-ification of any repo.

### Step 3.2: What Happens Per Task

For each enhancement task, CAM runs the MicroClaw cycle:

```
1. GRAB     — Fetch next pending task
2. EVALUATE — Enrich with KB context:
             → Hybrid search (vector + BM25) across 2,895+ methodologies
             → Top-5 relevant patterns injected as context
             → Forbidden approaches from error KB (what NOT to try)
             → Novel capabilities surfaced (novelty ≥ 0.7)
3. DECIDE   — Route to best agent via Kelly Bayesian scoring:
             → claude (analysis, architecture, security)
             → codex (refactoring, testing, CI/CD)
             → gemini (dependency analysis)
             → grok (quick bug fixes)
             → local (bulk classification, mining extraction)
4. ACT      — Agent writes code with correction loop:
             → Workspace snapshot before changes
             → Agent runs with KB-informed context
             → JSON auto-repair if config files corrupted
             → If verification fails: restore → feedback → retry
             → Up to max_correction_attempts retries
5. VERIFY   — 7-check audit gate:
             → Dependency jail (no unauthorized imports)
             → Style match (follows project conventions)
             → Chaos check (no bare except, no eval, no hardcoded creds)
             → Placeholder scan (rejects TODO, FIXME, NotImplementedError)
             → Drift alignment (semantic match to task intent)
             → Claim validation (no unsubstantiated "production ready")
             → LLM deep review (optional final pass)
6. LEARN    — Record outcome, update agent scores, promote/demote patterns
```

### Step 3.3: Patterns CAM Injects

During enhancement, CAM retrieves and applies these categories of battle-tested patterns:

| Category | What Gets Injected | Source |
|---|---|---|
| **Error Handling** | Exception classification (retryable vs permanent), custom error types, error accumulation | 4+ mined repos |
| **Retry + Backoff** | Exponential backoff with jitter, Retry-After header parsing, 30s delay cap, circuit breakers | MiroFish, agents, claw-code, meta-harness |
| **Structured Logging** | JSON logging, correlation IDs, perf_counter timing, context-aware levels | Seed + mined patterns |
| **JSON Repair** | Self-healing parser, trailing comma recovery, truncation recovery, control char sanitization | Proven 100% repair rate on 12/16 repos |
| **Test Generation** | Pytest fixtures, parameterization, isolation patterns, coverage gates | codex agent + seed knowledge |
| **CI/CD Pipelines** | GitHub Actions workflows, test gates, lint integration, coverage thresholds | Mined from real repos |
| **API Client Design** | Request wrapping, auth handling, rate limit detection, timeout config, connection pooling | API-domain methodologies |
| **Security Hardening** | Input validation, secret scanning (73 credential types), auth checks | Security seed + TruffleHog patterns |
| **Plugin/Middleware** | Chain-of-responsibility, plugin discovery, lifecycle hooks, loop detection | Cross-repo synthesis |
| **Documentation** | README generation, API docs, type hints, docstrings | docsRedo prompt battery |

### Step 3.4: Validate Phase 3

**Gate**: The 7-gate validation battery runs automatically after enhancement.

```
Gate 1: Syntax Check      — All modified files parse without errors
Gate 2: Config Compat     — Config files load correctly
Gate 3: Import Smoke Test — All modules import without errors
Gate 4: DB Schema Compat  — Database migrations still work
Gate 5: CLI Smoke Test    — CLI commands execute (if applicable)
Gate 6: Full Test Suite   — All tests pass, no regressions
Gate 7: Diff Summary      — Verify files actually changed (anti-vaporware)
```

**If any gate fails**: CAM restores the workspace to pre-enhancement state and reports the specific failure.

---

## Post-Enhancement: Rebuild CAG Cache

After enhancement, rebuild the CAG cache so future operations benefit from the new patterns:

```bash
cam cag rebuild
cam cag status
```

---

## Complete CAM-ification Runbook

Copy-paste ready. Replace paths with your actual repo.

```bash
#!/bin/bash
set -e

TARGET="/path/to/target-repo"

echo "=== PRE-FLIGHT ==="
cam doctor environment
cam govern stats
cd "$TARGET" && git log --oneline -3 && cd -

echo "=== PHASE 1: MINE ==="
cam mine "$TARGET" \
  --target "$TARGET" \
  --max-repos 1 \
  --depth 5 \
  --max-minutes 30

cam kb insights
cam govern stats

echo "=== PHASE 2: MATCH (dry-run) ==="
cam enhance "$TARGET" \
  --battery \
  --dry-run \
  --verbose

echo ">>> Review the task plan above."
echo ">>> Press Enter to proceed or Ctrl+C to abort."
read

echo "=== PHASE 3: ENHANCE ==="
cam enhance "$TARGET" \
  --mode attended \
  --max-tasks 10 \
  --verbose

echo "=== POST-ENHANCE ==="
cam cag rebuild
cam cag status

echo "=== DONE ==="
echo "Review the enhanced repo at: $TARGET"
echo "Rollback: cd $TARGET && git checkout ."
```

---

## Decision Tree: When to CAM-ify

```
Is the repo small (< 500 lines)?
  YES → Manual improvement may be faster
  NO  → Continue

Does CAM's KB have relevant domain knowledge?
  Check: cam kb search "repo's domain keywords"
  NO  → Mine similar repos first to build KB, then CAM-ify
  YES → Continue

Is the repo production-critical?
  YES → Use --mode attended, review every task
  NO  → Use --mode supervised

Does the repo have tests?
  YES → CAM can validate its changes against existing tests
  NO  → CAM will generate tests as part of enhancement

Is the repo a monorepo?
  YES → Increase --depth to 7+, increase --max-minutes
  NO  → Default settings work
```

---

## What "CAM-ified" Looks Like

A repo that has been CAM-ified will typically gain:

| Before | After CAM-ification |
|---|---|
| Bare `try/except` blocks | Classified error handling with retryable vs permanent errors |
| No retry logic | Exponential backoff with jitter, Retry-After headers, delay caps |
| `print()` debugging | Structured JSON logging with correlation IDs and perf timers |
| Manual JSON parsing | Self-healing parser with corruption recovery |
| No tests or low coverage | Pytest fixtures, parameterized tests, coverage gates |
| No CI pipeline | GitHub Actions with test + lint gates |
| Hardcoded config | Environment-aware configuration extraction |
| No input validation | Security-hardened input validation, secret scanning |
| Monolithic functions | Extracted helpers following DRY, middleware chains |
| Missing docs | Auto-generated README, API docs, type hints |

---

## Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| 0 findings after mining | Repo too small or depth too shallow | Increase `--depth`, try `--max-minutes 45` |
| No relevant KB patterns found | CAM's KB doesn't cover this domain yet | Mine similar repos first: `cam pulse ingest <similar-repo-url>` |
| Enhancement tasks irrelevant | Battery prompts generic for this repo type | Use `--mode attended` and skip irrelevant tasks |
| Validation gate 6 fails (tests) | Enhancement broke existing tests | CAM auto-restores and retries; if persistent, review the specific test failure |
| Agent writes placeholder code | Correction loop should catch this | If it persists, the task may be too ambiguous — refine the task description |
| Enhancement is slow | Large repo + full battery | Reduce `--max-tasks`, use lighter mode without `--battery` |
| "Database is locked" error | Another CAM process has DB open | Close other terminals running CAM |

---

## Advanced: Mining External Repos to Build Domain KB First

If CAM's KB is thin in the target repo's domain, build it up first:

```bash
# Step 1: Find similar repos to mine
cam pulse scan --keywords "domain keywords from target repo"

# Step 2: Ingest the best matches
cam pulse ingest \
  https://github.com/org/similar-repo-1 \
  https://github.com/org/similar-repo-2 \
  https://github.com/org/similar-repo-3

# Step 3: Verify KB grew in relevant domain
cam kb search "target domain"
cam kb domains

# Step 4: Rebuild CAG cache with new knowledge
cam cag rebuild

# Step 5: Now CAM-ify the target repo (richer context available)
cam enhance /path/to/target-repo --battery --mode attended --max-tasks 10
```

---

## Advanced: Feeding Results Back

After CAM-ification, the target repo's improvements become learnable:

```bash
# Mine the now-enhanced repo back into CAM
cam mine /path/to/target-repo \
  --target /path/to/cam \
  --max-repos 1 \
  --depth 5

# CAM assimilates the enhanced patterns for future use
cam kb insights
```

This creates a **compounding knowledge loop**: each CAM-ified repo makes the next CAM-ification better.

---

## Summary

**CAM-ify = Mine → Match → Enhance → Validate → Learn**

The target repo keeps doing what it was designed to do. It just does it with:
- Patterns extracted from 250+ real codebases
- 7-gate validation ensuring no regressions
- Self-correcting agents that retry on failure
- Bayesian routing to the best agent per task type
- Persistent learning that compounds across every project
