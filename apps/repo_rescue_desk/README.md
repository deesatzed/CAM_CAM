# Repo Rescue Desk

Repo Rescue Desk is a local CAM_CAM showpiece app for turning a folder full of
repositories into an actionable map.

It scans a repo universe, classifies repositories into capability clusters,
flags risks, ranks useful app/showpiece opportunities, and exports the same
knowledge graph into several usable formats:

- HTML dashboard
- inventory JSON
- opportunity rankings
- risk report
- GraphRAG context markdown
- graph JSON
- Markmap markdown
- Freeplane `.mm`
- Logseq page folder

## Run

```bash
PYTHONPATH=apps/repo_rescue_desk python -m repo_rescue_desk.cli \
  --root /Volumes/WS4TB/repo421sn \
  --out-dir tmp/repo_rescue_desk/latest
```

Open `tmp/repo_rescue_desk/latest/repo_rescue_dashboard.html` in a browser.

## Why This Is Useful

This is not just a proof artifact. It solves a real local problem: when a
workspace contains hundreds of overlapping repos, backups, experiments, medical
apps, RAG tools, agent tools, memory systems, and security layers, it becomes
hard to know what to keep, mine, merge, or use next.

Repo Rescue Desk gives CAM_CAM an operator-facing map before it acts.

## Mindmap And GraphRAG Outputs

- `repo_mindmap_markmap.md`: paste into Markmap or render with the Markmap CLI.
- `repo_mindmap_freeplane.mm`: open in Freeplane.
- `logseq/pages/*.md`: copy or symlink into a Logseq graph.
- `repo_graph.json`: nodes and edges for future graph visualization.
- `graphrag_context.md`: retrieval-friendly chunks for CAM planning.

## Tests

```bash
PYTHONPATH=apps/repo_rescue_desk python -m pytest apps/repo_rescue_desk/tests -q
```

