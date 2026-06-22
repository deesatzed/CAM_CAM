# CAM-preMine Feature Plan

Date: 2026-06-22

## Problem

CAM operators often clone a GitHub repository first, then run `cam mine`, and
only later learn whether the repo has enough reusable value, acceptable license
terms, or safe mining scope. That wastes local disk, time, and attention, and it
can pull dual-use or custom-license code into the local workspace before the
operator has made an explicit decision.

## Product Goal

Add a pre-clone triage step that answers:

> Is this GitHub repo worth cloning and CAM-mining, and under what license or
> safety scope?

The workflow must be useful before any `git clone` occurs. It should inspect
GitHub metadata, README, tree paths, languages, workflows, releases, checks, and
recent commit signals remotely.

## User Workflow

1. Operator finds a candidate repo URL.
2. Operator runs `cam premine <github-url>` or supplies a file of URLs.
3. CAM returns a verdict, CAM value score, repo type, risk gate, clone cost, and
   recommended next step.
4. Operator either clones, harvests remote docs/skills only, puts the repo on a
   watchlist, or skips it.
5. Optional report and JSONL candidate outputs feed later mining or dashboard
   work.

## Verdicts

- `CLONE_NOW`: high-value, runnable, acceptable risk for local CAM mining.
- `CONDITIONAL_CLONE`: useful but needs license, maintenance, or scope review.
- `REMOTE_HARVEST`: value is concentrated in docs, skills, examples, or research
  artifacts; harvest remotely before local clone.
- `RESTRICTED_REMOTE_HARVEST`: dual-use or safety-sensitive; only mine
  defensive taxonomy, validation evidence, and provenance unless a human expands
  scope.
- `WATCHLIST`: not enough evidence today, but worth refreshing later.
- `SKIP`: low expected CAM value.
- `NEEDS_HUMAN`: ambiguous enough that automation should not decide.

## Repo Type Classifier

CAM-preMine should classify at least:

- `runnable_tool`
- `app_product`
- `library`
- `agent_skill_corpus`
- `docs_methodology`
- `research_eval`
- `security_dual_use`
- `dataset_or_examples`
- `demo_only`
- `unknown`

## UX Requirements

- Default output is a compact table for quick interactive use.
- `--format json` returns machine-readable results with no extra stdout text.
- `--format markdown` emits a human-readable report.
- `--report <path>` writes the Markdown report.
- `--out <path>` writes JSON results.
- `--save-candidates <path>` appends JSONL records for later CAM workflows.
- The command must never clone or execute candidate code.

## v1 Acceptance Checks

- Fixture-based tests cover the five real example repos discussed on
  2026-06-22.
- CLI tests prove JSON output, Markdown report writing, and candidate JSONL
  writing.
- A live smoke run can assess a public GitHub URL without cloning it.
- The README shows the operator-facing command sequence.
