from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Repo Necromancer fused demo.")
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    print(f"Repo Necromancer Demo: {evidence['product_name']}")
    print(evidence["promise"])
    print()
    print("Source repos:")
    for repo in evidence["source_repos"]:
        print(f"- {repo['name']}: {', '.join(repo['signals']) or 'no signals'}")
    print()
    print("MVP features:")
    for feature in evidence["mvp_features"]:
        print(f"- {feature}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
