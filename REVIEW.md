# REVIEW.md

## Review Scope

Task 7 crash-recovery hardening of `claw.managed_runs` verification receipts.

## Summary Judgment

Proceed.

## Findings

| Severity | Category | Finding | Why It Matters | Required Fix |
|---|---|---|---|---|
| Critical | Correctness | Receipt bytes were hashed and then the path was reopened for parsing. | A replacement could make the parsed record differ from the hashed record. | Fixed and regression-tested. |
| Critical | Provenance | The receipt omitted plan ID and full managed-plan digest. | Verification evidence could not independently bind to the authorization-bearing plan. | Fixed and regression-tested. |

## Correctness

The final implementation reads receipt bytes once, verifies their digest,
decodes and parses that same buffer, and requires matching plan identity in the
typed evidence, receipt payload, and persisted managed plan.

## Security and Privacy

The change adds no command execution, provider use, database schema change, or
secret-bearing fields.

## Tests

Focused Task 7 tests passed: 31 tests in `test_managed_runs.py` and
`test_camseq_foundation.py`. The added regressions independently prove the
one-read property and missing-plan-identity rejection.

## Maintainability

The shared verified-file reader avoids duplicate receipt-read logic while
preserving the existing mining-receipt verifier API.

## Performance

Receipt verification removes an unnecessary second filesystem read.

## UI/UX Impact

None; this is a hidden persistence seam.

## Regression Risk

Low. Existing focused persistence and CAM-SEQ tests passed.

## Scope Creep Check

No runtime ownership, migration, provider, or target-mutation behavior changed.

## Required Fixes Before Done

None.

## Optional Improvements

Run the complete cross-repository gate in Task 12 after Tasks 8-11 are complete.
