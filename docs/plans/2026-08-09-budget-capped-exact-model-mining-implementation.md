# Budget-Capped Exact-Model Mining Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a resumable, fail-closed `$7` mining authorization that permits only `x-ai/grok-4.5` and stops before any unreserved OpenRouter request.

**Architecture:** A persistent `MiningBudgetController` reserves a conservative maximum for every HTTP attempt before submission and reconciles provider-reported usage afterward. `mine-workspace` builds the controller from a frozen live catalog entry, passes an exact-model override through `ClawFactory`, and treats budget exhaustion as a terminal workspace condition rather than a recoverable model error.

**Tech Stack:** Python 3.13, Typer, Pydantic, httpx, pytest, SQLite-backed CAM runtime, OpenRouter Chat Completions and model catalog.

---

### Task 1: Persistent request-budget controller

**Files:**
- Create: `src/claw/mining_budget.py`
- Create: `tests/test_mining_budget.py`

**Step 1: Write failing receipt and reservation tests**

Cover these behaviors with a fixture `ModelCatalogEntry`:

```python
def test_reserve_is_persisted_before_request(tmp_path: Path) -> None:
    controller = MiningBudgetController.create(
        receipt_path=tmp_path / "run.json",
        authorization_usd=7.0,
        exact_model="x-ai/grok-4.5",
        catalog_entry=grok_entry(),
    )
    attempt = controller.reserve_attempt(
        messages=[{"role": "user", "content": "mine this"}],
        max_tokens=4096,
    )
    restored = MiningBudgetReceipt.model_validate_json(
        (tmp_path / "run.json").read_text()
    )
    assert restored.attempts[-1].attempt_id == attempt.attempt_id
    assert restored.attempts[-1].status == "submitted"
    assert restored.conservative_spend_usd > 0
```

Add separate tests proving:

- the receipt is mode `0600` and atomically parseable;
- a request that does not fit raises `MiningBudgetExceeded` without appending an attempt;
- completed provider cost replaces the reserve;
- missing cost retains the full reserve;
- failed/ambiguous attempts retain the full reserve;
- every retry gets an independent reserve;
- resume restores all actual and conservative spend;
- resume rejects authorization, exact-model, or catalog-entry drift;
- provider preferences contain `allow_fallbacks=false`, price sorting,
  required-parameter enforcement, and frozen `max_price` values.

**Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=src pytest -q tests/test_mining_budget.py
```

Expected: collection/import failure because `claw.mining_budget` does not exist.

**Step 3: Implement the minimal controller**

Create immutable Pydantic receipt models and mutable controller operations:

```python
class MiningBudgetError(RuntimeError): ...
class MiningBudgetExceeded(MiningBudgetError): ...

class MiningAttemptReceipt(BaseModel):
    attempt_id: str
    repo_name: str | None
    status: Literal["submitted", "completed", "failed"]
    requested_model: str
    returned_model: str | None = None
    maximum_cost_usd: float
    actual_cost_usd: float | None = None
    cost_source: str = "missing"
    request_id: str | None = None
    error: str | None = None

class MiningBudgetReceipt(BaseModel):
    schema_version: int = 1
    authorization_usd: float
    exact_model: str
    model_catalog_digest: str
    status: Literal["running", "completed", "budget-exhausted", "failed"]
    attempts: list[MiningAttemptReceipt]

    @property
    def conservative_spend_usd(self) -> float:
        ...
```

Use UTF-8 serialized-message bytes plus fixed JSON overhead as a conservative
input-token upper bound. Include completion, reasoning, override, and request
prices. Write a temporary file, chmod it `0600`, replace the destination, and
chmod the destination `0600` after every transition.

**Step 4: Run tests and verify GREEN**

Run:

```bash
PYTHONPATH=src pytest -q tests/test_mining_budget.py
```

Expected: all Task 1 tests pass.

**Step 5: Commit**

```bash
git add src/claw/mining_budget.py tests/test_mining_budget.py
git commit -m "feat(mining): persist hard request budget receipts"
```

### Task 2: Enforce reservation at the OpenRouter HTTP-attempt boundary

**Files:**
- Modify: `src/claw/llm/client.py`
- Modify: `tests/test_llm.py`

**Step 1: Write failing HTTP-boundary tests**

Inject a fake controller into `LLMClient` and prove:

```python
async def test_budget_reserves_before_each_http_attempt():
    controller = FakeBudgetController()
    transport = RetryThenSuccessTransport()
    client = LLMClient(config, budget_controller=controller)
    client._client = httpx.AsyncClient(transport=transport)
    await client.complete(...)
    assert controller.events == [
        "reserve", "fail", "reserve", "complete"
    ]
```

Add tests that budget rejection makes zero HTTP calls, provider routing limits
are present in the submitted JSON, provider cost/request ID/returned model are
reconciled, returned-model drift is recorded then rejected, and legacy clients
without a controller produce the unchanged payload.

**Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=src pytest -q \
  tests/test_llm.py -k 'budget or exact_model or provider_limits'
```

Expected: failures because `LLMClient` has no budget-controller integration.

**Step 3: Implement the minimal request hooks**

Add an optional controller constructor argument. In `_request_with_retry`, copy
the payload, apply controller provider preferences, and reserve immediately
before every `client.post`. Reconcile only after parsing provider usage. Mark
ambiguous failures before retry. Re-raise `MiningBudgetError` without retry.

**Step 4: Run focused and complete LLM tests**

Run:

```bash
PYTHONPATH=src pytest -q tests/test_llm.py tests/test_mining_budget.py
```

Expected: all pass.

**Step 5: Commit**

```bash
git add src/claw/llm/client.py tests/test_llm.py
git commit -m "feat(llm): enforce budget before provider attempts"
```

### Task 3: Exact-model factory and terminal miner propagation

**Files:**
- Modify: `src/claw/models/profiles.py`
- Modify: `src/claw/core/factory.py`
- Modify: `src/claw/miner.py`
- Modify: `tests/test_model_profiles.py`
- Modify: `tests/test_miner_recovery.py`

**Step 1: Write failing exact-route tests**

Prove an exact override deep-copies the config, assigns the authorized model to
every enabled non-local agent, clears fallback models, and leaves the base
config untouched:

```python
def test_exact_mining_model_removes_alternate_routes(base_config):
    exact = resolve_exact_mining_config(base_config, "x-ai/grok-4.5")
    assert {
        cfg.model for cfg in exact.agents.values()
        if cfg.enabled and cfg.mode != "local"
    } == {"x-ai/grok-4.5"}
    assert exact.llm.fallback_models == []
```

Add a factory forwarding test for the controller and exact model. Add recovery
tests proving `MiningBudgetExceeded` escapes primary, reduction, and chunk
paths immediately instead of triggering another model request.

**Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=src pytest -q \
  tests/test_model_profiles.py tests/test_miner_recovery.py \
  -k 'exact or budget'
```

Expected: failures because exact routing and typed propagation do not exist.

**Step 3: Implement exact routing and propagation**

Add `resolve_exact_mining_config`, apply it in `ClawFactory.create` after the
profile overlay, pass the controller to `LLMClient`, and add explicit
`except MiningBudgetError: raise` branches at every mining recovery catch.

**Step 4: Run focused tests**

Run:

```bash
PYTHONPATH=src pytest -q \
  tests/test_model_profiles.py tests/test_miner_recovery.py \
  tests/test_integration_wiring.py tests/test_mining_budget.py tests/test_llm.py
```

Expected: all pass.

**Step 5: Commit**

```bash
git add src/claw/models/profiles.py src/claw/core/factory.py src/claw/miner.py \
  tests/test_model_profiles.py tests/test_miner_recovery.py
git commit -m "feat(mining): force exact model under hard budgets"
```

### Task 4: Expose fail-closed workspace CLI and terminal receipt

**Files:**
- Modify: `src/claw/cli/_monolith.py`
- Modify: `tests/test_miner.py`
- Modify: `tests/test_cli_ux.py`

**Step 1: Write failing CLI tests**

Add tests for:

- each partial combination of `--max-cost-usd`, `--exact-model`, and
  `--budget-receipt` exits before key/catalog/client work;
- non-positive budgets fail;
- scan-only remains no-spend;
- the async path fetches the live catalog, creates/resumes the receipt, and
  passes exact model plus controller into `ClawFactory.create`;
- budget exhaustion breaks the candidate loop, marks the receipt
  `budget-exhausted`, and never invokes the next repository;
- a fully completed plan marks the receipt `completed` and prints actual,
  conservative, and remaining spend;
- the no-budget CLI path preserves legacy behavior.

**Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=src pytest -q \
  tests/test_miner.py tests/test_cli_ux.py \
  -k 'budget or exact_model or mine_workspace'
```

Expected: new tests fail because the options and terminal handling are absent.

**Step 3: Implement the CLI contract**

Add the three options, validate them as an all-or-none contract, fetch the live
catalog only for a paid budgeted run, and build the controller before factory
creation. Set receipt repo context before each candidate. On
`MiningBudgetExceeded`, mark terminal state, print the reason and remaining
conservative authorization, and break. Disable task generation in the actual
operator command, not as a hidden global behavior.

**Step 4: Run CLI/miner regression tests**

Run:

```bash
PYTHONPATH=src pytest -q \
  tests/test_miner.py tests/test_cli_ux.py tests/test_miner_recovery.py \
  tests/test_model_profiles.py tests/test_mining_budget.py tests/test_llm.py
```

Expected: all pass.

**Step 5: Commit**

```bash
git add src/claw/cli/_monolith.py tests/test_miner.py tests/test_cli_ux.py
git commit -m "feat(cli): cap exact-model workspace mining spend"
```

### Task 5: Documentation, truth record, and release gate

**Files:**
- Modify: `README.md`
- Modify: `docs/benchmarks/2026-08-08-mining-model-tournament.md`
- Modify: `DECISIONS.md`
- Modify: `PROGRESS.md`

**Step 1: Document the exact operator command**

Include the pinned DB variables, `--no-tasks`, `--changed-only`, Grok exact
model, `$7` maximum, and an absolute ignored receipt path. State plainly that
the cap may stop before all 48 repositories fit.

**Step 2: Run the relevant verification gate**

Run:

```bash
PYTHONPATH=src pytest -q \
  tests/test_mining_budget.py tests/test_llm.py tests/test_model_profiles.py \
  tests/test_miner_recovery.py tests/test_miner.py tests/test_cli_ux.py \
  tests/test_models_cli.py tests/test_model_catalog.py
ruff check src/claw/mining_budget.py src/claw/llm/client.py \
  src/claw/models/profiles.py tests/test_mining_budget.py
git diff --check
```

Then run the broader mining/model gate recorded in `PROGRESS.md`. Report any
known full-suite baseline failures separately rather than calling them green.

**Step 3: Commit documentation**

```bash
git add README.md docs/benchmarks/2026-08-08-mining-model-tournament.md \
  DECISIONS.md PROGRESS.md
git commit -m "docs: explain hard-capped exact-model mining"
```

### Task 6: Integrate and execute the approved run

**Files:**
- Runtime receipt (ignored):
  `/Volumes/WS4TB/repo622sn/CAM_CAM/data/mining_runs/2026-08-09-grok-4.5-7usd.json`
- Live corpus:
  `/Volumes/WS4TB/repo622sn/CAM_CAM/claw.db`

**Step 1: Review, fetch, and fast-forward the live checkout**

Confirm the live checkout still contains only the previously documented
`claw.toml` modification and SQLite sidecars. Fetch first, merge with
`--ff-only`, and do not stage those live files.

**Step 2: Re-run preflight and no-spend scan**

Expect the authoritative eligible count to be 48 unless repositories changed
during implementation. Treat the fresh count as authoritative.

**Step 3: Run paid mining**

```bash
cam mine-workspace \
  /Volumes/WS4TB/repo622sn \
  /Volumes/WS4TB/waswiki/repos2mine \
  --changed-only --max-repos 200 --max-minutes 240 --no-tasks \
  --target /Volumes/WS4TB/repo622sn/CAM_CAM \
  --config /Volumes/WS4TB/repo622sn/CAM_CAM/claw.toml \
  --profiles /Volumes/WS4TB/repo622sn/CAM_CAM/model_profiles.toml \
  --exact-model x-ai/grok-4.5 \
  --max-cost-usd 7 \
  --budget-receipt /Volumes/WS4TB/repo622sn/CAM_CAM/data/mining_runs/2026-08-09-grok-4.5-7usd.json
```

**Step 4: Verify the live outcome**

Check the receipt terminal state and per-attempt returned models, reconcile
provider actual/conservative spend at or below `$7`, inspect
`mining_outcomes`, compare `mining_registry.json`, verify SQLite integrity, and
union root plus configured ganglion stores when reconciling inserted findings.

**Step 5: Update and publish final evidence**

Update `PROGRESS.md` with exact repositories, findings, failures, actual spend,
conservative spend, and corpus verification. Commit and push only tracked
evidence; never commit raw responses, secrets, the live DB, or ignored run
receipts.
