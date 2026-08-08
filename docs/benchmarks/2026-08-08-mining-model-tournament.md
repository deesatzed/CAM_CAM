# Mining Model Tournament - 2026-08-08

## Result

Use `x-ai/grok-4.5` for CAM repository mining when cloud mining is approved.
It was the only candidate to pass the first round, both held-out repositories,
and a same-prompt repeat with zero hard failures.

No model profile was changed automatically.

| Stage | Model | Quality | Hard failures | Recorded cost |
|---|---|---:|---:|---:|
| First round | Qwen 3.8 Max | 93.09 | 0 | $0.37821600 |
| First round | Grok 4.5 | 90.40 | 0 | $0.35646920 |
| First round | Kimi K3 | 83.67 | 0 | $0.53291520 |
| Held out | Grok 4.5 | 81.22 | 0 | $0.33309680 |
| Held out | Qwen 3.8 Max | 47.38 | 1 provenance failure | $0.35733600 |
| Repeat | Grok 4.5 | 87.20 | 0 | $0.01441200 |

Gemini 3.6 Flash Batch, Terra, Luna, GLM 5.2, and DeepSeek V4 Flash
were excluded by provenance or truncation gates. Kimi passed the first round
but was not advanced because three held-out candidates did not fit the budget.
No queued-batch model qualified.

Grok's repeat remained valid but scored 12.8 points below its original
Codx_LoopKit call. Treat it as the best tested choice, not a perfectly
deterministic one.

## Spend and immutability

- Prior conservative spend: `$2.0348919774`
- This tournament: `$2.6076943380`
- Provider-recorded cumulative spend: `$4.6425863154`
- Extra reserve for one ambiguous bounded Terra retry: `$0.1006900000`
- Operator-conservative cumulative spend: `$4.7432763154` of `$5.00`
- Operator-conservative remaining authorization: `$0.2567236846`

The pinned corpus remained
`/Volumes/WS4TB/repo622sn/CAM_CAM/claw.db`. Its SHA-256 stayed
`707f821fd20e504665ebf65934a146eb8e36b4b66245a63b753e33ce66a01ef3`.
`model_profiles.toml` also remained unchanged during the tournament.

GLM 5.2 cost `$0.27956364`, roughly 7.8 times its catalog-derived lane
maximum. Its nominal OpenRouter price is not reliable budget evidence until
the route/provider discrepancy is understood.

## Very simple operator instructions

After this branch is merged into the canonical CAM_CAM checkout:

1. Select Grok with rollback receipts:

   ```bash
   cam models set mining-quality x-ai/grok-4.5 \
     --profile legacy-import \
     --profiles model_profiles.toml \
     --receipt data/model_profiles/mining-quality-grok-4.5.json
   cam models set mining-budget x-ai/grok-4.5 \
     --profile legacy-import \
     --profiles model_profiles.toml \
     --receipt data/model_profiles/mining-budget-grok-4.5.json
   ```

2. Preview only new or changed repositories without LLM spend:

   ```bash
   cam mine-workspace \
     /Volumes/WS4TB/repo622sn \
     /Volumes/WS4TB/waswiki/repos2mine \
     --changed-only --scan-only --max-repos 200 \
     --config /Volumes/WS4TB/repo622sn/CAM_CAM/claw.toml
   ```

3. After approving a separate mining budget, run the same command without
   `--scan-only` and add the selected profile:

   ```bash
   cam mine-workspace \
     /Volumes/WS4TB/repo622sn \
     /Volumes/WS4TB/waswiki/repos2mine \
     --changed-only --max-repos 200 --max-minutes 120 \
     --target /Volumes/WS4TB/repo622sn/CAM_CAM \
     --config /Volumes/WS4TB/repo622sn/CAM_CAM/claw.toml \
     --profiles /Volumes/WS4TB/repo622sn/CAM_CAM/model_profiles.toml
   ```

The paid mining command is intentionally not executed by this tournament: the
remaining `$0.2567236846` belongs to the comparison authorization, and
`mine-workspace` does not yet expose a separate dollar cap.

The no-spend changed-only preview found 61 unique candidates and classified 59
as new or changed (37 under `repo622sn`, 22 under `repos2mine`, after two
deduplicated iterations). Mining all 59 requires a new dollar authorization;
the comparison budget is not silently reused.

## Evidence paths

Local raw responses and receipts remain mode-600 ignored artifacts under
`data/model_benchmarks/20260808-adaptive-tournament/`. The durable selection
artifact is `selection.md` in that directory. This tracked report contains the
decision without publishing raw repository prompts or model outputs.
