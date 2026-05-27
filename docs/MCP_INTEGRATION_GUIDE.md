# MCP Integration Guide

CAM-PULSE exposes its knowledge base, verification, and agent routing capabilities as an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server. This allows external tools — Claude Code, Cursor, Windsurf, or any MCP-compatible client — to query CAM's learned patterns, store new findings, verify claims, route tasks, and escalate to human review.

## Quick Start

```bash
# Start the MCP server (stdio transport, default)
cam mcp --transport stdio

# Or run directly as a Python module
python -m claw.mcp_server
```

## Exposed Tools (17, partially documented)

> **Note:** The live server exposes 17 tools. This guide documents 5 of them in detail. The full list is always discoverable at runtime: start the server with `cam mcp --transport stdio` and call `tools/list` from any MCP client. The 12 undocumented tools follow the same JSON-RPC conventions shown below.

### 1. `claw_query_memory`

Query CAM's semantic memory for similar past solutions, patterns, and techniques.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | yes | — | Search query describing the problem or pattern needed |
| `limit` | integer | no | 3 | Maximum results (1-20) |
| `language` | string | no | — | Filter results by programming language |

**Example:** "retry logic with exponential backoff" returns ranked methodologies with combined_score, vector_score, and text_score from hybrid BM25 + cosine search.

### 2. `claw_store_finding`

Store a discovered pattern, fix, or technique in CAM's semantic memory for reuse.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `problem_description` | string | yes | — | Description of the problem this finding solves |
| `solution_code` | string | yes | — | The solution code, pattern, or technique |
| `tags` | array[string] | no | [] | Categorization tags |
| `methodology_type` | string | no | — | One of: `PATTERN`, `FIX`, `ARCHITECTURE`, `TECHNIQUE` |

**Example:** Store a retry pattern you just wrote so CAM remembers it for future builds.

### 3. `claw_verify_claim`

Verify a code assertion by scanning for placeholders, TODOs, and unsubstantiated claims.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `claim` | string | yes | — | The claim to verify (e.g., "all tests pass") |
| `workspace_dir` | string | no | — | Path to workspace for file-level scanning |

**Returns:** `PASS`, `FAIL`, or `PARTIAL` with violation details. Scans `.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.go`, `.rs`, `.rb`, `.java` files for placeholder patterns.

### 4. `claw_request_specialist`

Request a different AI agent (claude, codex, gemini, grok) to handle a subtask.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `task_description` | string | yes | — | Description of the subtask to delegate |
| `preferred_agent` | string | no | — | One of: `claude`, `codex`, `gemini`, `grok` |

**Returns:** The selected agent and routing rationale based on Bayesian Kelly Criterion. Does NOT execute the subtask — returns the routing decision only.

### 5. `claw_escalate`

Flag a task as beyond AI capability and escalate to human review.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `reason` | string | yes | — | Why this task cannot be completed autonomously |
| `context` | object | no | — | Additional context for the human reviewer |
| `task_id` | string | no | — | ID of the task being escalated |

**Returns:** Escalation ID and episode ID. Task processing pauses until human review.

## Connect from Claude Code

Add to `~/.claude/mcp_servers.json`:

```json
{
  "cam-pulse": {
    "command": "cam",
    "args": ["mcp", "--transport", "stdio"],
    "env": {
      "CLAW_CONFIG": "/path/to/your/claw.toml",
      "CLAW_DB_PATH": "/path/to/your/data/claw.db"
    }
  }
}
```

After adding, restart Claude Code. CAM's 17 tools will appear as available MCP tools.

## Connect from Cursor

Add to Cursor settings (`.cursor/mcp.json` or global settings):

```json
{
  "mcpServers": {
    "cam-pulse": {
      "command": "cam",
      "args": ["mcp", "--transport", "stdio"],
      "env": {
        "CLAW_CONFIG": "/path/to/your/claw.toml",
        "CLAW_DB_PATH": "/path/to/your/data/claw.db"
      }
    }
  }
}
```

## Connect from Any MCP Client

CAM's MCP server speaks the standard MCP protocol over stdio. Any MCP-compatible client can connect by spawning:

```bash
cam mcp --transport stdio
```

The server reads from stdin and writes to stdout (JSON-RPC). Logs go to stderr.

## Configuration

### claw.toml

```toml
[mcp]
enabled = true
transport = "stdio"              # "stdio" (recommended) or "http"
host = "127.0.0.1"              # HTTP only
port = 3100                      # HTTP only
auth_token_env = "CLAW_MCP_AUTH_TOKEN"  # Optional bearer token
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `CLAW_CONFIG` | no | Path to claw.toml (default: `claw.toml` in project root) |
| `CLAW_DB_PATH` | no | Path to claw.db (default: `data/claw.db`) |
| `CLAW_MCP_AUTH_TOKEN` | no | Bearer token for authentication |
| `GOOGLE_API_KEY` | no | Enables semantic search (embedding-based retrieval) |

## Authentication

Authentication is optional. If `CLAW_MCP_AUTH_TOKEN` is set, all tool calls must include a matching token. If not set, the server runs without authentication.

## Example Usage Flow

1. **Developer asks Claude Code:** "Add retry logic with exponential backoff"
2. **Claude Code calls `claw_query_memory`:** query="retry logic exponential backoff"
3. **CAM returns:** 3 ranked methodologies from mined repos (e.g., jitter patterns from zeph, error classification from deer-flow)
4. **Claude Code uses the patterns** to write production-grade retry logic with attribution
5. **Claude Code calls `claw_verify_claim`:** claim="all tests pass", workspace_dir="/path/to/project"
6. **CAM returns:** PASS/FAIL with details
7. **Claude Code calls `claw_store_finding`:** stores the new retry pattern for future reuse

## Fallback Behavior

Each tool has a graceful fallback chain:

- **Query:** Semantic memory (vector + text) → FTS5 text search only
- **Store:** Semantic memory with embeddings → Raw database insert
- **Verify:** Full verifier pipeline → Placeholder pattern scan + test execution
- **Request Specialist:** Bayesian Kelly routing → Static routing table
- **Escalate:** Database logging + escalation counter

If the `mcp` Python SDK is not installed, the server logs a warning and exits gracefully.

## Test Coverage

MCP server functionality is covered by:

```bash
pytest tests/test_tool_schemas.py tests/test_integration_wiring.py -q
# Tests cover: input validation, schema generation, authentication, tool dispatch
```

## Source Files

| File | Description |
|------|-------------|
| `src/claw/mcp_server.py` | Server implementation (1,054 lines) |
| `src/claw/tools/schemas.py` | Pydantic input validation schemas |
| `src/claw/cli/_monolith.py` | CLI entry point (`cam mcp` command) |
| `src/claw/core/factory.py` | Factory instantiation of MCP server |
