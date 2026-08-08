# Adaptive Mining-Model Tournament Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a resumable, stage-specific CAM mining-model tournament that advances only eligible models, enforces the original cumulative budget, and emits explicit quality/value/speed/batch role candidates without changing profiles.

**Architecture:** Preserve the existing `BenchmarkPlan` and its historical first-round artifacts. Add tournament plan, advancement, lineage, and selection types in a focused `claw.models.tournament` module; generalize the runner to execute an explicit list of frozen calls; and expose no-spend `advance` and `select` CLI commands around the existing plan/run/report flow. Each later stage is frozen only after the preceding quality report exists, and every stage carries cumulative prior spend against one authorization cap.

**Tech Stack:** Python 3.11+, Pydantic v2, Typer, pytest, existing OpenRouter catalog/client and CAM grounded scoring.

---

### Task 1: Add tournament plan and lineage types

**Files:**
- Create: `src/claw/models/tournament.py`
- Create: `tests/test_tournament_planner.py`

**Step 1: Write the failing tests**

Cover a frozen `TournamentStagePlan` with:

```python
plan = TournamentStagePlan(
    schema_version=1,
    run_id="stage-1",
    created_at="2026-08-08T00:00:00+00:00",
    suite_name="mining-v1",
    stage="first-round",
    authorization_usd=5.0,
    prior_spend_usd=2.0,
    stage_maximum_cost_usd=1.5,
    catalog_receipt=catalog_receipt,
    fixtures=fixture_receipts,
    calls=calls,
    selected_candidates=["model/a"],
)
assert plan.cumulative_maximum_cost_usd == 3.5
assert plan.remaining_after_maximum_usd == 1.5
```

Also prove validation rejects a stage whose cumulative maximum crosses the
authorization, negative prior spend, call stages that differ from the plan,
and duplicate candidates.

**Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src python -m pytest -q tests/test_tournament_planner.py`

Expected: FAIL because `claw.models.tournament` does not exist.

**Step 3: Implement the minimal immutable types**

Add:

```python
TournamentStage = Literal["first-round", "heldout", "repeat"]

class TournamentStagePlan(BaseModel):
    model_config = ConfigDict(frozen=True)
    schema_version: int = 1
    run_id: str
    created_at: str
    suite_name: str
    stage: TournamentStage
    authorization_usd: float
    prior_spend_usd: float
    stage_maximum_cost_usd: float
    parent_run_id: str | None = None
    catalog_receipt: CatalogReceipt
    fixtures: list[FixtureReceipt]
    calls: list[PlannedCall]
    selected_candidates: list[str]
    excluded_candidates: dict[str, list[str]] = Field(default_factory=dict)
    no_fallback: bool = True

    @property
    def cumulative_maximum_cost_usd(self) -> float:
        return self.prior_spend_usd + self.stage_maximum_cost_usd

    @property
    def remaining_after_maximum_usd(self) -> float:
        return self.authorization_usd - self.cumulative_maximum_cost_usd
```

Use an after-validator for schema, nonnegative monetary fields, hard budget,
stage agreement, unique candidates, and call-model membership.

**Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest -q tests/test_tournament_planner.py`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/claw/models/tournament.py tests/test_tournament_planner.py
git commit -m "feat(benchmark): add tournament stage plans"
```

### Task 2: Freeze first-round plans one stage at a time

**Files:**
- Modify: `src/claw/models/tournament.py`
- Modify: `tests/test_tournament_planner.py`

**Step 1: Write the failing planner tests**

Use the existing mining suite, frozen prompt fixtures, and catalog fixture to
prove:

```python
plan = TournamentPlanner().plan_first_round(
    suite,
    fixtures,
    catalog,
    authorization_usd=5.0,
    prior_spend_usd=2.0348919774,
)
assert plan.stage == "first-round"
assert len(plan.calls) == 24
assert plan.selected_candidates == suite.candidates
assert plan.stage_maximum_cost_usd == pytest.approx(
    sum(call.maximum_cost_usd for call in plan.calls)
)
assert plan.cumulative_maximum_cost_usd <= 5.0
```

Prove the plan does not reserve smoke, held-out, or repeat calls, contains no
raw prompt/repository content, and rejects insufficient remaining budget.

**Step 2: Run the targeted test to verify failure**

Run: `PYTHONPATH=src python -m pytest -q tests/test_tournament_planner.py -k first_round`

Expected: FAIL because `TournamentPlanner.plan_first_round` is absent.

**Step 3: Implement shared call freezing and first-round planning**

Move no existing public behavior. Reuse `_maximum_call_cost` and introduce a
small private helper that freezes `PlannedCall` objects for a supplied stage,
model list, and fixture list. Keep seed/reasoning/transport logic identical to
the repaired `BenchmarkPlanner`.

`plan_first_round` must:

- validate fixture names and clean Git state;
- select the three `first-round` fixtures;
- preserve suite candidate order;
- price only those 24 calls;
- compute the stage and cumulative maximum; and
- freeze catalog and fixture receipts without raw content.

**Step 4: Run tests**

Run: `PYTHONPATH=src python -m pytest -q tests/test_tournament_planner.py tests/test_benchmark_planner.py`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/claw/models/tournament.py tests/test_tournament_planner.py
git commit -m "feat(benchmark): plan isolated first rounds"
```

### Task 3: Rank eligible models and plan adaptive advancement

**Files:**
- Modify: `src/claw/models/tournament.py`
- Modify: `src/claw/models/scoring.py`
- Modify: `tests/test_tournament_planner.py`
- Modify: `tests/test_benchmark_scoring.py`

**Step 1: Write failing scoring and advancement tests**

Extend each `ModelQualitySummary` with `worst_quality` and
`cost_per_finding_usd`. Verify failed calls and absent candidates remain
ineligible and that ranking follows:

```python
ordered = rank_eligible_models(report)
assert [item.model_id for item in ordered] == [
    "model/high-floor",
    "model/high-average",
    "model/cheap",
]
```

Test held-out advancement across both held-out fixtures, top-four contraction
to the largest ranked prefix that fits, exclusion reasons for ineligible and
budget-excluded candidates, exact `parent_run_id`, and cumulative spend based
on the parent plan's prior spend plus its provider-reported stage spend.

Test repeat advancement selects at most two eligible held-out finalists and one
deterministically chosen first-round fixture.

**Step 2: Run the tests to verify failure**

Run: `PYTHONPATH=src python -m pytest -q tests/test_benchmark_scoring.py tests/test_tournament_planner.py`

Expected: FAIL on missing metrics and advancement functions.

**Step 3: Add metrics and deterministic ranking**

In `score_benchmark_run`, calculate:

```python
worst_quality = min(call.quality for call in model_calls)
cost_per_finding = (
    sum(call.cost_usd for call in model_calls) / sum(call.finding_count for call in model_calls)
    if sum(call.finding_count for call in model_calls)
    else None
)
```

In the tournament module add a stable rank key: descending worst quality,
descending average quality, ascending cost per finding (`inf` when absent),
ascending total cost, synchronous latency with batch separated, then model ID.

**Step 4: Implement `plan_advance`**

Accept the parent stage plan, its quality report, suite, full fixtures, current
catalog, and next stage. Validate run identity and expected stage transition.
Build the ranked eligible prefix, decreasing the prefix length until the
stage's worst-case calls fit the original authorization. Record explicit
reasons such as `hard_failure`, `missing_expected_calls`, `quality_below_gate`,
and `not_selected_within_remaining_budget`.

Do not create an empty paid stage: raise a clear no-eligible-candidates error.

**Step 5: Run tests**

Run: `PYTHONPATH=src python -m pytest -q tests/test_benchmark_scoring.py tests/test_tournament_planner.py`

Expected: PASS.

**Step 6: Commit**

```bash
git add src/claw/models/tournament.py src/claw/models/scoring.py tests/test_tournament_planner.py tests/test_benchmark_scoring.py
git commit -m "feat(benchmark): advance eligible model finalists"
```

### Task 4: Execute arbitrary frozen stages safely and resumably

**Files:**
- Modify: `src/claw/models/benchmark.py`
- Modify: `src/claw/models/tournament.py`
- Modify: `tests/test_benchmark_runner.py`
- Create: `tests/test_tournament_runner.py`

**Step 1: Write failing runner tests**

Construct a held-out `TournamentStagePlan` and prove:

```python
summary = await runner.run_calls(plan.calls)
assert summary.completed == len(plan.calls)
assert summary.actual_cost_usd == pytest.approx(expected_stage_cost)
```

Run the same directory again and prove all calls are skipped, no provider
client is called, and actual spend is reconstructed once from receipts. Prove
the runner's available ledger is `authorization - prior_spend`, returned-model
drift fails closed, and a receipt whose prompt/catalog digest differs from the
plan is rejected.

**Step 2: Run tests to verify failure**

Run: `PYTHONPATH=src python -m pytest -q tests/test_tournament_runner.py tests/test_benchmark_runner.py`

Expected: FAIL because generic stage execution is absent.

**Step 3: Generalize the existing runner**

Extract the body of `run_first_round` into:

```python
async def run_calls(
    self,
    calls: list[PlannedCall],
    *,
    limit: int | None = None,
    models: set[str] | None = None,
) -> BenchmarkRunSummary:
    ...
```

Retain `run_first_round` as a compatibility wrapper. Add a tournament runner
factory or constructor path that initializes `BudgetLedger` with the stage's
remaining authorization and validates the frozen plan before calls. Do not
duplicate provider call logic.

When resuming, sum completed receipt costs once for the returned stage summary;
do not add the same receipt repeatedly to a persistent cumulative ledger.

**Step 4: Run tests**

Run: `PYTHONPATH=src python -m pytest -q tests/test_tournament_runner.py tests/test_benchmark_runner.py tests/test_batch_benchmark.py`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/claw/models/benchmark.py src/claw/models/tournament.py tests/test_benchmark_runner.py tests/test_tournament_runner.py
git commit -m "feat(benchmark): execute frozen tournament stages"
```

### Task 5: Add no-spend stage advancement and stage-aware reporting CLI

**Files:**
- Modify: `src/claw/cli/models.py`
- Modify: `tests/test_models_cli.py`

**Step 1: Write failing CLI tests**

Prove the CLI supports:

```text
cam models benchmark plan ... --stage first-round --prior-spend-usd 2.0348919774
cam models benchmark advance PARENT --report REPORT --stage heldout ...
cam models benchmark run PLAN ...
cam models benchmark report RUN ...
```

Assert plan and advance output contains `NO PAID CALLS MADE`, the run command
accepts any stage plan, the report uses the stage's expected fixture count, and
all output plans have mode `0600`. Test a mismatched report/run ID and budget
failure.

**Step 2: Run tests to verify failure**

Run: `PYTHONPATH=src python -m pytest -q tests/test_models_cli.py -k benchmark`

Expected: FAIL because the new options and command are absent.

**Step 3: Implement CLI wiring**

Keep the legacy `BenchmarkPlan` parser as a compatibility fallback for old run
directories. New `plan` output uses `TournamentPlanner.plan_first_round` when
`--stage first-round` is supplied. `advance` loads the parent plan/report,
refreshes or loads the explicit catalog snapshot, writes a new stage plan, and
makes no model calls. `run` dispatches the plan's explicit calls. `report`
derives expected fixture count from the stage plan rather than hardcoding the
first round.

Print stage maximum, cumulative conservative maximum, authorization, and
remaining budget on every no-spend plan.

**Step 4: Run tests**

Run: `PYTHONPATH=src python -m pytest -q tests/test_models_cli.py tests/test_tournament_planner.py tests/test_tournament_runner.py`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/claw/cli/models.py tests/test_models_cli.py
git commit -m "feat(cli): expose adaptive model tournament"
```

### Task 6: Emit final role-selection evidence without promotion

**Files:**
- Modify: `src/claw/models/tournament.py`
- Modify: `src/claw/cli/models.py`
- Create: `tests/test_tournament_selection.py`
- Modify: `tests/test_models_cli.py`

**Step 1: Write failing selection tests**

Use first-round, held-out, and repeat quality reports to prove:

- quality selects the highest held-out floor among repeat-eligible finalists;
- budget selects the lowest cumulative cost per accepted finding;
- fast excludes batch transports and chooses lowest synchronous latency;
- batch selects only queued-batch candidates;
- repeat instability is reported and can disqualify a role candidate;
- no eligible model yields `model_id = null` and a reason;
- generated commands are exact `cam models set ...` commands; and
- creating JSON/Markdown reports does not alter a profile file.

**Step 2: Run tests to verify failure**

Run: `PYTHONPATH=src python -m pytest -q tests/test_tournament_selection.py tests/test_models_cli.py -k select`

Expected: FAIL because selection evidence is absent.

**Step 3: Implement selection types and policy**

Add immutable `RoleCandidate` and `TournamentSelectionReport` types. Aggregate
call-level evidence by model across supplied reports. Use held-out evidence for
quality, cumulative accepted findings/cost for budget, synchronous receipts for
fast, and queued-job receipts for batch. Treat a repeat hard failure or quality
drop greater than 20 points as unstable and report the exclusion.

The generated promotion mapping is informational only:

```python
ROLE_TO_PROFILE_ROLE = {
    "quality": "mining-quality",
    "budget": "mining-budget",
    "batch": "mining-batch",
}
```

Do not map `fast` automatically because there is no existing `mining-fast`
profile role.

**Step 4: Add `benchmark select`**

Accept one or more stage report paths and plan paths, validate lineage, and
write deterministic JSON or Markdown. Include total recorded tournament spend,
the pre-tournament prior spend, cumulative spend, model exclusions, role
evidence, and explicit promotion commands.

**Step 5: Run tests**

Run: `PYTHONPATH=src python -m pytest -q tests/test_tournament_selection.py tests/test_models_cli.py`

Expected: PASS.

**Step 6: Commit**

```bash
git add src/claw/models/tournament.py src/claw/cli/models.py tests/test_tournament_selection.py tests/test_models_cli.py
git commit -m "feat(benchmark): select evidence-backed model roles"
```

### Task 7: Document, verify, and execute the bounded tournament

**Files:**
- Modify: `README.md`
- Modify: `PROGRESS.md`
- Modify: `DECISIONS.md`
- Create locally/ignored: `data/model_benchmarks/<run>/...`

**Step 1: Document the operator workflow**

Add a short README section with the four-stage commands, explicit corpus path,
no-write/no-promotion guarantees, and how to inspect or promote a reported role
candidate. Update `DECISIONS.md` with stage budgeting and explicit promotion.
Record implementation and evidence in `PROGRESS.md`, distinguishing local test
proof from paid comparison results.

**Step 2: Run focused verification**

Run:

```bash
PYTHONPATH=src python -m pytest -q \
  tests/test_tournament_planner.py \
  tests/test_tournament_runner.py \
  tests/test_tournament_selection.py \
  tests/test_benchmark_planner.py \
  tests/test_benchmark_runner.py \
  tests/test_benchmark_scoring.py \
  tests/test_models_cli.py \
  tests/test_batch_benchmark.py
```

Expected: PASS.

**Step 3: Run the broader local gate**

Run:

```bash
PYTHONPATH=src python -m pytest -q \
  tests/test_models_cli.py tests/test_model_profiles.py \
  tests/test_benchmark_planner.py tests/test_benchmark_runner.py \
  tests/test_benchmark_scoring.py tests/test_batch_benchmark.py \
  tests/test_openrouter.py tests/test_llm_client.py \
  tests/test_miner.py tests/test_miner_prompts.py
git diff --check
```

Expected: PASS and no whitespace errors.

**Step 4: Commit implementation documentation**

```bash
git add README.md PROGRESS.md DECISIONS.md
git commit -m "docs: explain adaptive model comparison"
```

**Step 5: Capture fresh no-spend inputs**

From the authoritative CAM_CAM checkout/worktree, load the API key by name
without printing it. Fetch and save the current catalog, capture all five
production prompts from the two approved repo roots, and create a first-round
plan using:

```text
authorization_usd = 5.0
prior_spend_usd = 2.0348919774
```

Verify fixture repositories are clean, model IDs resolve, the pinned corpus is
`/Volumes/WS4TB/repo622sn/CAM_CAM/claw.db`, and the cumulative maximum does not
exceed `$5.00`.

**Step 6: Execute and score the first round**

Run the frozen first-round plan. Score it against the immutable live corpus.
If no candidate is eligible, stop honestly and publish the failure report; do
not spend on later stages.

**Step 7: Advance through affordable stages**

If eligible candidates exist, prepare and execute held-out, then repeat plans.
Before each paid stage, verify its cumulative maximum remains within `$5.00`.
Allow the planner to contract the candidate count; never override the cap.

**Step 8: Generate the final selection report**

Generate JSON and Markdown reports. Do not promote profiles. Update
`PROGRESS.md` and `DECISIONS.md` with actual provider spend, hard failures,
eligible models, role candidates, and any stopped stage.

**Step 9: Final verification and publish**

Run the focused and broader gates again, `git diff --check`, inspect `git status
--short --branch`, commit only intended tracked files, fetch, push the branch,
and verify the upstream head. Never add raw responses, `.env`, catalog secrets,
or local database files.
