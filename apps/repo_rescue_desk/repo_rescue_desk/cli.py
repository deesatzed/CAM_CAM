"""Command-line interface for Repo Rescue Desk."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .rescue import scan_universe, write_artifacts


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inventory a repo universe and emit CAM Repo Rescue Desk artifacts.",
    )
    parser.add_argument("--root", required=True, type=Path, help="Directory containing git repos.")
    parser.add_argument("--out-dir", required=True, type=Path, help="Directory to write artifacts.")
    parser.add_argument(
        "--max-repos",
        type=int,
        default=None,
        help="Optional scan cap for demos/tests.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = scan_universe(args.root, max_repos=args.max_repos)
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


if __name__ == "__main__":
    raise SystemExit(main())
