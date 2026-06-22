# CAM-preMine v1 Implementation Notes

Date: 2026-06-22

## Implemented Surface

`cam premine` performs remote GitHub triage before clone/mining:

```bash
cam premine https://github.com/Egonex-AI/Understand-Anything
cam premine repos.txt --format markdown --report premine_report.md
cam premine repos.txt --format json --out premine_report.json --save-candidates data/premine/candidates.jsonl
```

The command accepts a single GitHub URL, `owner/repo`, SSH URL, or a text file
of URLs. Blank lines and `#` comments are ignored in URL files.

## Scoring Inputs

The implementation fetches public GitHub signals only:

- repository metadata
- default branch
- license
- topics
- language byte counts
- recursive tree paths
- README excerpt
- workflow names
- check-run names where available
- release tags
- recent commit messages

No clone is performed and no candidate code is executed.

## Scoring Model

The first version is intentionally explainable instead of opaque. It gives
credit for tests, CI/checks, manifests, docs, skill files, releases, research
artifacts, Docker/Helm packaging, recency, language data, and community signal.

Safety-sensitive repositories are detected before normal type scoring. If
dual-use terms such as steganography, covert channels, payloads, or red-team
language appear in README/tree metadata, the repo is routed to
`RESTRICTED_REMOTE_HARVEST`.

Custom, missing, or `NOASSERTION` licenses route to `CONDITIONAL_CLONE` when
the repo still has strong CAM value. The operator must review license terms
before local clone or source reuse.

## Example Outcomes Encoded In Tests

- `Egonex-AI/Understand-Anything`: `CLONE_NOW`
- `Leonxlnx/taste-skill`: `REMOTE_HARVEST`
- `iternal-technologies-partners/blockify-agentic-data-optimization`:
  `CONDITIONAL_CLONE`
- `elder-plinius/GLOSSOPETRAE`: `RESTRICTED_REMOTE_HARVEST`
- `elder-plinius/ST3GG`: `RESTRICTED_REMOTE_HARVEST`

## Follow-Up Layers

- Add a Forge/Dashboard view that can compare many preMine candidates.
- Persist preMine candidate records in a dedicated SQLite table once the CLI
  schema stabilizes.
- Add a remote file-harvest command for safe docs/skill-only ingestion.
- Add refresh/watchlist scheduling for repos that are not worth cloning yet.
