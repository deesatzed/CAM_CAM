#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="${PYTHON:-python3}"
RUN_ID="$(date +%Y%m%d-%H%M%S)"
OUT_DIR="$REPO_ROOT/tmp/repo_rescue_desk_showpiece/$RUN_ID"
FIXTURE_DIR="$OUT_DIR/fixture"
ARTIFACT_DIR="$OUT_DIR/artifacts"

mkdir -p "$FIXTURE_DIR" "$ARTIFACT_DIR"

make_repo() {
  local name="$1"
  local readme="$2"
  mkdir -p "$FIXTURE_DIR/$name"
  printf '%s\n' "$readme" > "$FIXTURE_DIR/$name/README.md"
  git -C "$FIXTURE_DIR/$name" init -q
  git -C "$FIXTURE_DIR/$name" add README.md
  git -C "$FIXTURE_DIR/$name" -c user.email=test@example.com -c user.name='Test User' \
    commit -q -m initial
}

make_repo "repowise-lite" "# RepoWise Lite

Multi-repo codebase intelligence, MCP tools, dependency graph, git history."
make_repo "agent-pidgin-lite" "# Agent Pidgin Lite

Policy receipts, audit trace, semantic preflight, sandbox guardrails."
make_repo "openkb-markmap-lite" "# OpenKB Markmap Lite

Knowledge wiki, retrieval graph, Logseq, Freeplane, Markmap, documents."
make_repo "medical-rag-lite" "# Medical RAG Lite

Clinical patient HIPAA PII knowledge retrieval and citation grounding."

PYTHONPATH="$REPO_ROOT/apps/repo_rescue_desk" \
  "$PYTHON" -m pytest "$REPO_ROOT/apps/repo_rescue_desk/tests" -q

PYTHONPATH="$REPO_ROOT/apps/repo_rescue_desk" \
  "$PYTHON" -m repo_rescue_desk.cli \
  --root "$FIXTURE_DIR" \
  --out-dir "$ARTIFACT_DIR"

test -f "$ARTIFACT_DIR/repo_inventory.json"
test -f "$ARTIFACT_DIR/repo_rescue_dashboard.html"
test -f "$ARTIFACT_DIR/opportunity_rankings.md"
test -f "$ARTIFACT_DIR/risk_report.md"
test -f "$ARTIFACT_DIR/repo_mindmap_markmap.md"
test -f "$ARTIFACT_DIR/repo_mindmap_freeplane.mm"
test -f "$ARTIFACT_DIR/repo_graph.json"
test -f "$ARTIFACT_DIR/graphrag_context.md"
test -f "$ARTIFACT_DIR/logseq/pages/CAM Repo Rescue Desk.md"

grep -q "Repo Rescue Desk" "$ARTIFACT_DIR/opportunity_rankings.md"
grep -q "CAM Repo Rescue Desk" "$ARTIFACT_DIR/repo_mindmap_markmap.md"
grep -q "<map" "$ARTIFACT_DIR/repo_mindmap_freeplane.mm"
grep -q "GraphRAG Context" "$ARTIFACT_DIR/graphrag_context.md"

echo "Repo Rescue Desk showpiece passed."
echo "Artifacts: $ARTIFACT_DIR"

