# Repo Rescue Desk Showpiece

## What This Proves

Repo Rescue Desk proves a more useful CAM_CAM showpiece shape:

1. CAM_CAM scans a real repo universe.
2. It classifies repos into capability clusters.
3. It identifies risk and governance concerns before acting.
4. It ranks useful app/showpiece opportunities.
5. It exports the result into human-usable dashboard and mindmap formats.
6. It emits GraphRAG-ready context for later CAM planning.
7. It leaves source repos untouched.

This is stronger than improving a single target app because it makes CAM_CAM
useful before any code mutation happens.

## App

Location:

- `apps/repo_rescue_desk`

Run against the local repo universe:

```bash
PYTHONPATH=apps/repo_rescue_desk python -m repo_rescue_desk.cli \
  --root /Volumes/WS4TB/repo421sn \
  --out-dir tmp/repo_rescue_desk/latest
```

## Outputs

The app writes:

- `repo_inventory.json`
- `repo_rescue_dashboard.html`
- `opportunity_rankings.md`
- `risk_report.md`
- `repo_mindmap_markmap.md`
- `repo_mindmap_freeplane.mm`
- `repo_graph.json`
- `graphrag_context.md`
- `logseq/pages/*.md`

## Mindmap And GraphRAG Support

The mindmap path is concrete, not conceptual:

- Markmap receives a nested Markdown outline.
- Freeplane receives a `.mm` XML map.
- Logseq receives page-oriented Markdown with wikilinks.
- GraphRAG receives node/edge JSON plus retrieval-friendly Markdown chunks.

## Why It Is Useful

The user has a large local repo collection with overlapping agent systems,
medical tools, RAG systems, memory systems, security tools, browser agents, and
research frameworks. Repo Rescue Desk turns that collection into a decision
surface:

- what to mine
- what to merge
- what to keep
- what is risky
- what app/showpiece should be built next

## Verification

Focused tests:

```bash
PYTHONPATH=apps/repo_rescue_desk python -m pytest apps/repo_rescue_desk/tests -q
```

Showpiece harness:

```bash
./scripts/test_repo_rescue_desk_showpiece.sh
```

The harness creates a controlled fixture repo universe, runs the unit tests,
runs the CLI, and verifies all dashboard, mindmap, Logseq, Freeplane, graph,
GraphRAG, inventory, risk, and opportunity artifacts exist.

## Limitations

The first version uses deterministic README, file, and git metadata analysis.
It does not yet perform embedding-based semantic clustering or ingest the
results into CAM's durable learning memory. Those are the next useful upgrades.

