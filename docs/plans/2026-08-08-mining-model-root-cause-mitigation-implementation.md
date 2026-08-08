# Mining-model Root-cause Mitigation Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make CAM mining-model comparisons selection-grade and prevent production mining from storing truncated, reasoning-only, or imprecisely grounded findings.

**Architecture:** Keep the existing single-pass miner and recovery ladder. Align benchmark requests with production prompts, add explicit reasoning/seed controls at the transport boundary, gate storage on complete JSON, validate model symbols against local extraction, and require an explicitly pinned read-only corpus for novelty scoring.

**Tech Stack:** Python 3.12+, Pydantic, httpx, Typer, SQLite, pytest, OpenRouter chat and queued Batch APIs.

---

### Task 1: Freeze reasoning and seed controls

**Files:**
- Modify: `src/claw/llm/client.py`
- Modify: `src/claw/models/batch.py`
- Modify: `src/claw/models/catalog.py`
- Test: `tests/test_llm.py`
- Test: `tests/test_batch_benchmark.py`
- Test: `tests/test_model_catalog.py`

**Step 1: Write failing tests**

Add tests that require:

```python
await client.complete(
    [LLMMessage("user", "mine")],
    model="qwen/qwen3.8-max",
    reasoning={"effort": "minimal", "exclude": True},
    seed=0,
)
assert fake.payload["reasoning"] == {"effort": "minimal", "exclude": True}
assert fake.payload["seed"] == 0
```

Also require queued batch bodies to preserve the same reasoning and seed fields,
catalog entries to preserve `mandatory`, `supported_efforts`, and
`default_effort`, and null final content to remain empty rather than becoming
reasoning prose.

**Step 2: Run tests to verify RED**

Run:

```bash
uv run pytest -q tests/test_llm.py tests/test_batch_benchmark.py tests/test_model_catalog.py
```

Expected: failures for unsupported `reasoning`/`seed`, missing catalog metadata,
and reasoning being substituted as content.

**Step 3: Implement minimal transport and catalog support**

Add optional `reasoning` and `seed` parameters to `LLMClient.complete` and its
fallback path. Add `reasoning` to `OpenRouterBatchClient.complete`. Introduce a
frozen `ModelReasoning` Pydantic model and preserve the raw catalog reasoning
object. Do not substitute `message.reasoning` for `message.content`.

**Step 4: Run tests to verify GREEN**

Run the Task 1 command and require zero failures.

**Step 5: Commit**

```bash
git add src/claw/llm/client.py src/claw/models/batch.py src/claw/models/catalog.py tests/test_llm.py tests/test_batch_benchmark.py tests/test_model_catalog.py
git commit -m "fix(models): control reasoning and deterministic requests"
```

### Task 2: Make benchmark calls faithful and reproducible

**Files:**
- Modify: `src/claw/models/benchmark.py`
- Modify: `tests/test_benchmark_planner.py`
- Modify: `tests/test_benchmark_runner.py`

**Step 1: Write failing tests**

Require planned calls to freeze a least-cost supported reasoning effort and
require the runner to send `response_format=None`, the frozen reasoning
request, and `seed=0` for both synchronous and queued calls.

**Step 2: Run tests to verify RED**

```bash
uv run pytest -q tests/test_benchmark_planner.py tests/test_benchmark_runner.py
```

Expected: runner still sends `json_object`, omits synchronous seed, and has no
reasoning plan field.

**Step 3: Implement minimal benchmark changes**

Add `reasoning_effort` to `PlannedCall`. Prefer `minimal`, then `low`, then the
least expensive supported non-disabled effort. Remove `structured_outputs`
from requested parameters. Never add a response format that is absent from the
production call. Send the frozen seed and reasoning request through both
transports.

**Step 4: Run tests to verify GREEN**

Run the Task 2 command and require zero failures.

**Step 5: Commit**

```bash
git add src/claw/models/benchmark.py tests/test_benchmark_planner.py tests/test_benchmark_runner.py
git commit -m "fix(benchmark): align model request controls"
```

### Task 3: Right-size the production mining contract

**Files:**
- Modify: `prompts/repo-mine.md`
- Modify: `prompts/repo-mine-misc.md`
- Modify: `prompts/repo-mine-rust.md`
- Modify: `prompts/repo-mine-typescript.md`
- Modify: `prompts/repo-mine-go.md`
- Modify: `src/claw/core/config.py`
- Modify: `src/claw/miner.py`
- Test: `tests/test_mining_prompt_fixture.py`
- Test: `tests/test_miner_recovery.py`

**Step 1: Write failing tests**

Require captured production prompts to contain a `findings` wrapper and the
3-5 finding limit. Require mining LLM calls to receive configured low reasoning
with reasoning excluded from final content.

**Step 2: Run tests to verify RED**

```bash
uv run pytest -q tests/test_mining_prompt_fixture.py tests/test_miner_recovery.py
```

Expected: prompt still asks for an array and 6-15 findings; mining calls omit
reasoning controls.

**Step 3: Implement minimal prompt/config changes**

Change the five prompt templates to:

```json
{"findings": [{"title": "..."}]}
```

and request 3-5 findings. Add `reasoning_effort="low"` and
`reasoning_exclude=true` to `MiningRecoveryConfig`; centralize the mining
reasoning payload and pass it to all primary, escalation, reduction, and chunk
calls.

**Step 4: Run tests to verify GREEN**

Run the Task 3 command and require zero failures.

**Step 5: Commit**

```bash
git add prompts/repo-mine*.md src/claw/core/config.py src/claw/miner.py tests/test_mining_prompt_fixture.py tests/test_miner_recovery.py
git commit -m "fix(mining): right-size structured finding requests"
```

### Task 4: Reject partial and reasoning-only mining output

**Files:**
- Modify: `src/claw/miner.py`
- Test: `tests/test_miner.py`
- Test: `tests/test_miner_recovery.py`

**Step 1: Write failing tests**

Add a complete-envelope parser status test and recovery tests where a response
contains one repairable finding but has `finish_reason="length"`. Require the
attempt to be recorded unsuccessful and require no findings to be returned for
storage.

**Step 2: Run tests to verify RED**

```bash
uv run pytest -q tests/test_miner.py tests/test_miner_recovery.py
```

Expected: repair returns partial findings and recovery treats them as success.

**Step 3: Implement the completion gate**

Keep tolerant `parse_findings` for diagnostics/backward compatibility. Add a
strict complete-envelope helper for paid mining. Use it at every response
boundary and reject `finish_reason="length"` before findings enter storage.

**Step 4: Run tests to verify GREEN**

Run the Task 4 command and require zero failures.

**Step 5: Commit**

```bash
git add src/claw/miner.py tests/test_miner.py tests/test_miner_recovery.py
git commit -m "fix(mining): reject incomplete model responses"
```

### Task 5: Validate and backfill symbol provenance locally

**Files:**
- Modify: `src/claw/miner.py`
- Modify: `src/claw/models/scoring.py`
- Test: `tests/test_miner.py`
- Test: `tests/test_benchmark_scoring.py`

**Step 1: Write failing tests**

Create a fixture where a model supplies `"Frontmatter validation"` as a symbol
but the file contains `validate_frontmatter`. Require CAM to remove the label
and attach the extracted function. Require the scorer to penalize the bad symbol
without a hard failure when every source file is valid; missing/escaping files
must remain hard failures.

**Step 2: Run tests to verify RED**

```bash
uv run pytest -q tests/test_miner.py::TestSymbolExtraction tests/test_benchmark_scoring.py
```

Expected: miner trusts the supplied label and scoring hard-fails it.

**Step 3: Implement local validation**

Extract AST/SCIP candidates for cited files, retain only supplied symbols that
map to local candidates (including qualified class methods), then fill remaining
slots with relevance-ranked local candidates. Split file-grounding failure from
symbol-precision penalty in scoring.

**Step 4: Run tests to verify GREEN**

Run the Task 5 command and require zero failures.

**Step 5: Commit**

```bash
git add src/claw/miner.py src/claw/models/scoring.py tests/test_miner.py tests/test_benchmark_scoring.py
git commit -m "fix(mining): validate symbol provenance locally"
```

### Task 6: Require corpus-backed novelty and zero hard-failed quality

**Files:**
- Modify: `src/claw/models/scoring.py`
- Modify: `src/claw/cli/models.py`
- Modify: `tests/test_benchmark_scoring.py`
- Modify: `tests/test_models_cli.py`

**Step 1: Write failing tests**

Build a temporary SQLite corpus containing a mined methodology title. Require a
read-only loader to extract it, require `cam models benchmark report --db` to
pass it to scoring, and require a truncated/repaired call to report quality
zero even when recoverable findings exist.

**Step 2: Run tests to verify RED**

```bash
uv run pytest -q tests/test_benchmark_scoring.py tests/test_models_cli.py
```

Expected: reporting supplies an empty title list and partial calls retain high
numeric quality.

**Step 3: Implement corpus-backed reporting**

Open the explicit corpus with SQLite URI `mode=ro&immutable=1`, extract mined
titles from problem descriptions/solution headings, pass them to
`score_benchmark_run`, and set call quality to zero whenever any hard failure
is present. Require `--db` for benchmark reports.

**Step 4: Run tests to verify GREEN**

Run the Task 6 command and require zero failures.

**Step 5: Commit**

```bash
git add src/claw/models/scoring.py src/claw/cli/models.py tests/test_benchmark_scoring.py tests/test_models_cli.py
git commit -m "fix(benchmark): score against the pinned CAM corpus"
```

### Task 7: Verify, document, and prepare the corrected rerun

**Files:**
- Modify: `DECISIONS.md`
- Modify: `PROGRESS.md`
- Modify: `docs/reports/model-benchmark/20260808T172212Z-4ce70e93-RESULTS.md` in the CAM_Codx manager worktree if an addendum is needed

**Step 1: Run focused verification**

```bash
uv run pytest -q tests/test_llm.py tests/test_batch_benchmark.py tests/test_model_catalog.py tests/test_benchmark_planner.py tests/test_benchmark_runner.py tests/test_mining_prompt_fixture.py tests/test_miner.py tests/test_miner_recovery.py tests/test_benchmark_scoring.py tests/test_models_cli.py
```

Expected: zero failures.

**Step 2: Run broader verification**

```bash
uv run pytest -q tests/test_model_profiles.py tests/test_miner_brains.py tests/test_miner_multipass.py tests/test_miner_polyglot.py
git diff --check
```

Expected: zero failures and no whitespace errors.

**Step 3: Update durable truth**

Record the implementation decisions, exact verification receipts, unchanged
corpus/profile state, and the requirement to capture fresh fixtures and a fresh
plan before spending more budget.

**Step 4: Commit and push**

```bash
git add DECISIONS.md PROGRESS.md
git commit -m "docs: record mining benchmark mitigation evidence"
git push origin codex/cam-model-benchmark-runtime
```

**Step 5: Gate paid rerun**

Capture fresh fixtures into a new ignored run directory, freeze a new live
catalog and cost plan, and compare its worst-case cost with the remaining
approved budget. Do not execute paid calls if tests, source cleanliness, model
identity, explicit corpus pinning, or budget authorization is missing.
