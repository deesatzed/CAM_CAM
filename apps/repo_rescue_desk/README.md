# Repo Rescue Desk

Repo Rescue Desk is a local CAM_CAM showpiece app for turning a folder full of
repositories into an actionable map.

It scans a repo universe, classifies repositories into capability clusters,
flags risks, ranks useful app/showpiece opportunities, and exports the same
knowledge graph into several usable formats:

- HTML dashboard
- inventory JSON
- next-action recommendations
- git-safe preflight results
- repo-to-repo reuse matches
- plain-English executive report
- deterministic ask-my-repo index
- opportunity rankings
- risk report
- GraphRAG context markdown
- graph JSON
- Markmap markdown
- Freeplane `.mm`
- Logseq page folder
- optional CAM-RAG retrieval receipt with citations

## Run

```bash
PYTHONPATH=apps/repo_rescue_desk python -m repo_rescue_desk.cli \
  --root /Volumes/WS4TB/repo421sn \
  --out-dir tmp/repo_rescue_desk/latest
```

Open `tmp/repo_rescue_desk/latest/repo_rescue_dashboard.html` in a browser.

The same command also writes:

- `next_actions.md` / `next_actions.json`: ranked recommendations with effort,
  risk, payoff, evidence, and verification commands.
- `preflight_results.json`: `allow`, `warn`, or `block` decisions for scanned
  repos before agent mutation.
- `reuse_matches.md` / `reuse_matches.json`: local auth/retry/API reuse
  candidates with repo/path provenance and confidence.
- `executive_report.md`: plain-English report for a lead, client, or future
  maintainer.
- `ask_index.json`: deterministic answers for common follow-up questions.

Ask a saved scan:

```bash
PYTHONPATH=apps/repo_rescue_desk python -m repo_rescue_desk.cli ask \
  --report tmp/repo_rescue_desk/latest/repo_inventory.json \
  --question "Which repos have no tests?"
```

Preflight one repo before an agent edits it:

```bash
PYTHONPATH=apps/repo_rescue_desk python -m repo_rescue_desk.cli preflight \
  --repo /path/to/repo \
  --json-out tmp/repo_rescue_desk/preflight.json
```

Optional CAM-RAG bridge:

```bash
PYTHONPATH=src:apps/repo_rescue_desk python -m repo_rescue_desk.cli \
  --root /path/to/repo/folder \
  --out-dir tmp/repo_rescue_desk/latest \
  --rag-folder /path/to/context/docs \
  --rag-query "repo triage safety evidence"
```

When CAM-RAG is installed, Repo Rescue Desk indexes the text docs in
`--rag-folder`, retrieves cited context, emits `cam_rag_receipt.json` and
`cam_rag_receipt.md`, and adds RAG evidence nodes to the graph, Markmap,
Freeplane, Logseq, dashboard, and GraphRAG context outputs.

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
- `cam_rag_receipt.json` / `cam_rag_receipt.md`: optional cited retrieval receipt
  when `--rag-folder` is used.

## Tests

```bash
PYTHONPATH=apps/repo_rescue_desk python -m pytest apps/repo_rescue_desk/tests -q
```
