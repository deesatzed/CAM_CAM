"""Command-line interface for Repo Rescue Desk."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .rescue import (
    RepoProfile,
    RescueReport,
    answer_repo_question,
    enrich_with_cam_rag,
    preflight_repo,
    scan_universe,
    write_artifacts,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inventory a repo universe and emit CAM Repo Rescue Desk artifacts.",
        epilog=(
            "Subcommands: preflight --repo PATH [--json-out PATH]; "
            "ask --report repo_inventory.json --question QUESTION"
        ),
    )
    parser.add_argument("--root", required=True, type=Path, help="Directory containing git repos.")
    parser.add_argument("--out-dir", required=True, type=Path, help="Directory to write artifacts.")
    parser.add_argument(
        "--max-repos",
        type=int,
        default=None,
        help="Optional scan cap for demos/tests.",
    )
    parser.add_argument(
        "--rag-folder",
        type=Path,
        default=None,
        help="Optional folder of text docs to index with CAM-RAG for cited context.",
    )
    parser.add_argument(
        "--rag-query",
        default=None,
        help="Optional CAM-RAG query. Defaults to a query generated from the scan.",
    )
    parser.add_argument(
        "--rag-module",
        default="cam_rag",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def parse_preflight_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="repo_rescue_desk.cli preflight",
        description="Run a read-only git-safe agent preflight for one repo.",
    )
    parser.add_argument("--repo", required=True, type=Path, help="Repository to inspect.")
    parser.add_argument("--json-out", type=Path, default=None, help="Optional JSON output path.")
    return parser.parse_args(argv)


def parse_ask_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="repo_rescue_desk.cli ask",
        description="Answer deterministic questions from a saved Repo Rescue Desk inventory.",
    )
    parser.add_argument("--report", required=True, type=Path, help="Path to repo_inventory.json.")
    parser.add_argument("--question", required=True, help="Question to answer from scan artifacts.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    if argv and argv[0] == "preflight":
        return run_preflight(argv[1:])
    if argv and argv[0] == "ask":
        return run_ask(argv[1:])
    args = parse_args(argv)
    try:
        report = scan_universe(args.root, max_repos=args.max_repos)
        if args.rag_folder is not None:
            enrich_with_cam_rag(
                report,
                args.rag_folder,
                query=args.rag_query,
                module_name=args.rag_module,
            )
        artifacts = write_artifacts(report, args.out_dir)
        print(f"Repo Rescue Desk scanned {len(report.repos)} repos")
        print(f"Clusters: {len(report.clusters)}")
        print(f"Opportunities: {len(report.opportunities)}")
        for name, path in artifacts.items():
            print(f"{name}: {path}")
        print(f"logseq_pages: {args.out_dir / 'logseq' / 'pages'}")
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def run_preflight(argv: list[str]) -> int:
    try:
        args = parse_preflight_args(argv)
        result = preflight_repo(args.repo)
        payload = json.dumps(result, indent=2, sort_keys=True)
        if args.json_out:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(payload + "\n", encoding="utf-8")
        print(f"{result['repo']}: {result['decision']}")
        for item in result["remediation"]:
            print(f"- {item}")
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def run_ask(argv: list[str]) -> int:
    try:
        args = parse_ask_args(argv)
        report = load_report(args.report)
        response = answer_repo_question(report, args.question)
        print(response["answer"])
        if response.get("citations"):
            print("Citations: " + ", ".join(response["citations"]))
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def load_report(path: Path) -> RescueReport:
    payload = json.loads(path.read_text(encoding="utf-8"))
    repos = [RepoProfile(**repo) for repo in payload.get("repos", [])]
    return RescueReport(
        root=payload.get("root", ""),
        generated_at=payload.get("generated_at", ""),
        repos=repos,
        clusters=payload.get("clusters", {}),
        duplicate_groups=payload.get("duplicate_groups", []),
        opportunities=payload.get("opportunities", []),
        next_actions=payload.get("next_actions", []),
        reuse_matches=payload.get("reuse_matches", []),
        preflight_results=payload.get("preflight_results", []),
        graph=payload.get("graph", {"nodes": [], "edges": []}),
        receipts=payload.get("receipts", []),
    )


if __name__ == "__main__":
    raise SystemExit(main())
