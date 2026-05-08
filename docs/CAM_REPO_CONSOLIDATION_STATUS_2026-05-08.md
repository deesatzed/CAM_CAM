# CAM Repo Consolidation Status

Date: 2026-05-08

This records the source state at the start of the consolidation work. No history rewrites or destructive file operations were performed.

## Repository Snapshot

| Repo | Local Path | Remote | Branch State | HEAD | Dirty State |
|---|---|---|---|---|---|
| `CAM_CAM` | `/Volumes/WS4TB/CCam/CAM_CAM` | `https://github.com/deesatzed/CAM_CAM.git` | `main...origin/main` | `772c31131fabf871701d64782a5e7f0b98b633ef` | Clean before this status update |
| `CAM-Pulse` | `/Volumes/WS4TB/CCam/CAM-Pulse` | `https://github.com/deesatzed/CAM-Pulse.git` | `main...origin/main` | `cd1f040372148c720c32648a2eef88ed8365b45d` | Clean |
| `CAM-RAG` | `/Volumes/WS4TB/repo421sn/CAM-RAG` | `https://github.com/deesatzed/CAM-RAG.git` | `main...origin/main` | `8170d05878f87d3e462973ab16544e74b336d86f` | Local uncommitted changes |

## Recent Heads

### CAM_CAM

- `772c311 Add CAM repo consolidation plan`
- `3c867ed Refresh CAM_CAM root redirect styling`
- `c007ae9 Improve CAM_CAM showpiece landing page`
- `013939e Refresh CAM_CAM landing page visual design`
- `12f361e Expand CAM_CAM showpiece landing page proof`

### CAM-Pulse

- `cd1f040 docs: update landing page + README with defense chain results, model-diverse branding`
- `3231a3c feat(defense): kill-chain fixes rescue 5/6 failing projects (5/10 -> 10/10)`
- `3940899 feat(landing): add batch proof section, Grok head-to-head, expand competitor table`
- `91bb489 feat(batch-proof): 30/30 passing + systemic import fix + Grok differentiation`
- `f588664 feat(mining): fast-mine architecture + ganglion fix + batch enrich`

### CAM-RAG

- `8170d05 Route strong embeddings to blended_rerank based on benchmark evidence`
- `88c3fb1 Add 4 pipeline scoring enhancements: blended reranker, intersection boost, BM25 anti-flood`
- `fcbeffa Update regression baselines with dense_only and latest benchmark scores`
- `a74a938 Route strong embeddings to dense_only on all corpus types`
- `305e821 Add dense_only strategy and product overview document`
- `5f0654e Add corpus-aware strategy routing and auto-calibration`

## CAM-RAG Local Changes

`CAM-RAG` is current with `origin/main`, but it has uncommitted local work:

- Modified: `src/cam_rag/__init__.py`
- Untracked: `src/cam_rag/deterministic.py`
- Untracked: `tests/__init__.py`
- Untracked: `tests/test_deterministic.py`

Consolidation rule: do not physically merge `CAM-RAG` into `CAM_CAM` until these local changes are either committed in `CAM-RAG`, intentionally discarded by the owner, or copied into a reviewed integration branch.

## Current Decision

`CAM_CAM` is the canonical umbrella repository. `CAM-Pulse` should be absorbed into `CAM_CAM` as the core learning engine after parity classification. `CAM-RAG` should remain separate and be connected through an adapter contract first.
