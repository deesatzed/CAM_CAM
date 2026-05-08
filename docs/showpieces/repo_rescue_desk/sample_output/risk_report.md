# Repo Rescue Desk Risk Report

Risk flags are conservative heuristics. They are not proof of leaked secrets or PHI; they identify repos that need deeper review before LLM ingestion or code mutation.

| Flag | Count | Meaning | Next action |
|---|---:|---|---|
| llm-key-sensitive | 154 | API key, token, secret, OpenRouter, or env language appears | Run a secret scan and redact before cloud LLM ingestion |
| security-sensitive | 124 | Security, sandbox, proxy, audit, or credential language appears | Route to guarded branch-first edits with receipts |
| no-tests | 117 | No obvious tests directory or test file was found | Add smoke tests before migration, mining, or self-modification |
| medical-sensitive | 72 | Medical, clinical, patient, HIPAA, PHI, or PII language appears | Use local-only review until PHI/PII exposure is ruled out |
| dirty-worktree | 58 | Repo has uncommitted or untracked changes | Commit, stash, or copy before any agent writes |
| no-readme | 7 | Purpose is not self-evident from README | Generate or write a short project summary before clustering |
