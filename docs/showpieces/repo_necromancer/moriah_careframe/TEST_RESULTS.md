# MoriahCareFrame Test Results

Date: 2026-06-20

## Packet smoke tests

```bash
python -m pytest -q tests/test_repo_necromancer.py
```

Result: PASS

```text
4 passed in 0.68s
```

```bash
python docs/showpieces/repo_necromancer/moriah_careframe/fused_app/repo_necromancer_demo.py --help
```

Result: PASS. The generated CLI exposes argparse help and the required
`--evidence` option.

```bash
python docs/showpieces/repo_necromancer/moriah_careframe/fused_app/repo_necromancer_demo.py --evidence docs/showpieces/repo_necromancer/moriah_careframe/evidence.json
```

Result: PASS. The demo prints the product promise, source repos, MVP features,
merge ledger, and safe merge plan.

## Report receipt coverage

```bash
python -m pytest -q tests/test_repo_necromancer.py
```

Result: PASS. The packet tests now cover that generated reports include explicit
git-state receipts for source repos, including non-git sources, git heads,
dirty status, and raw status receipt text.

## Full CAM_CAM test suite

```bash
python -m pytest -q
```

Result: FAIL outside the repo-necromancer packet.

```text
3 failed, 4232 passed, 14 skipped, 5 warnings in 105.26s (0:01:45)
```

Observed failures:

- `tests/test_cag_convert.py::TestReadLanceDB::test_read_lancedb_table`
  failed because installed LanceDB returned a `LanceDataset` without
  `to_pandas`.
- `tests/test_novelty.py::TestNearestNeighborNovelty::test_with_similar_neighbors`
  failed while the embedding stack attempted a HuggingFace HEAD request for
  `sentence-transformers/all-MiniLM-L6-v2` in an offline/no-DNS environment,
  then raised `RuntimeError: Cannot send a request, as the client has been
  closed`.
- `tests/test_serial_evolution.py::TestApprovedModelConfig::test_openrouter_agents_and_fallbacks_use_only_approved_models[config_path0]`
  failed because `claw.toml` lists `moonshotai/kimi-k2.7-code` and
  `nvidia/nemotron-3-ultra-550b-a55b` as fallback models that are not present
  in `APPROVED_MODEL_IDS`.

These failures were not introduced by the MoriahCareFrame packet work, but
they mean the repository-wide `python -m pytest -q` gate is not currently
green.

## Read-only source receipts

Source A:

- Path: `/Volumes/WS4TB/WS4TBr/MORIAH/moriah_omega`
- Git status: not a git repository at this path
- Profiled file count after generation: `56`

Source B:

- Path: `/Volumes/WS4TB/careframe/Proto_Dev_Req`
- Git head recorded in `evidence.json`: `194fc54`
- Git status before and after generation:

```text
 M ../docs/qa/mobile-visual/report.json
?? ../HANDOFF_2026-06-20.md
?? ../HANDOFF_LATEST.md
?? ../instances/
```

No source repo files were intentionally modified by the packet generator.
