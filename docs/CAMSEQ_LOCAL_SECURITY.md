# CAM-SEQ Local Security Setup

Default local mode for CAM-SEQ critical-slot policy uses the project `uv` venv plus Docker.

This path does **not** require:
- editing `~/.zshrc`
- installing CodeQL
- installing Semgrep globally

## Requirements

- project venv at `.venv`
- Docker Desktop running

## One-time setup

```bash
cd /Volumes/WS4TB/RNACAM/CAM-Pulse
source .venv/bin/activate
export CLAW_SECURITY_USE_DOCKER=1
```

Optional persistent repo-local env file:

```bash
cp .env.example .env
```

Then set in `.env`:

```bash
CLAW_SECURITY_USE_DOCKER=1
CLAW_CODEQL_MODE=deferred
```

## Verify Docker is available

```bash
docker ps
```

## Verify CAM-SEQ Docker Semgrep path

```bash
./scripts/camseq_semgrep.sh "$PWD" "$PWD/security/semgrep.yml" src/claw/security/policy_tools.py
```

This runs the repo-local Semgrep rules inside Docker.

## Advanced mode only

CodeQL is optional and is **not** required for the default local path.
Use CodeQL only if you want a heavier managed or advanced local security lane.

Set `CLAW_CODEQL_MODE` explicitly:

- `off`: do not run CodeQL and report it as skipped
- `deferred`: default local mode; report CodeQL as deferred unless the CLI, database, and query suite are configured
- `required`: hard security lane; report CodeQL as unavailable when the CLI, database, or query suite is missing

Required mode expects:

```bash
export CLAW_CODEQL_MODE=required
export CLAW_CODEQL_DATABASE=/path/to/codeql/database
export CLAW_CODEQL_QUERIES=/path/to/query-suite.qls
```
