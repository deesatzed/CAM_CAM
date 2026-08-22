# Repo Mining Prompt

You are a code archaeologist analyzing a repository to extract **actionable patterns, features, architectural ideas, and techniques** that could enhance a target project called **CLAW** (Codebase Learning & Autonomous Workforce).

## About CLAW

CLAW is a multi-model autonomous codebase enhancement system written in Python 3.12. Key subsystems:
- **Multi-agent orchestration** — 4 AI agents (Claude, Codex, Gemini, Grok) coordinated via Bayesian routing
- **Memory system** — 6 typed stores (working, episodic, semantic, procedural, error, meta) with sqlite-vec embeddings
- **Evaluation battery** — 18 prompt-driven analysis passes (deepdive, driftx, claim-gate, etc.)
- **Self-improvement** — prompt A/B testing, pattern learning, agent score evolution
- **Fleet mode** — scans and enhances multiple repos autonomously with budget caps
- **Verification** — claim-gate + drift detection + regression scanning before any change merges

CLAW's tech stack: Python asyncio, SQLite + aiosqlite, sqlite-vec, typer CLI, Rich, httpx, pydantic.

## Your Task

Analyze the repository source code below and extract findings that could improve CLAW. Look for:

1. **Architectural patterns** — state machines, event systems, plugin architectures, middleware chains, dependency injection patterns, Protocol-based abstractions (Python typing.Protocol for DI), frozen/immutable data contracts (frozen dataclasses with __post_init__ validation)
2. **AI/LLM integration techniques** — prompt engineering, response parsing, multi-model orchestration, context management, token optimization
3. **Memory/knowledge systems** — caching strategies, knowledge graphs, embedding approaches, retrieval augmented generation
4. **Code quality patterns** — error handling strategies, retry logic, circuit breakers, graceful degradation, idempotent operations (safe to replay/retry), explicit precedence/fallback chains for configuration resolution
5. **CLI/UX patterns** — progress display, configuration management, interactive workflows, structured CLI entrypoints separating demos from operational flows
6. **Testing patterns** — fixture strategies, property-based testing, integration test harnesses, environment-gated test separation (fast default suite vs opt-in live integration tests)
7. **Data processing** — pipeline patterns, stream processing, batch processing, ETL patterns
8. **Security patterns** — auth flows, permission systems, sandboxing, input validation
9. **Novel algorithms** — unique approaches to common problems, optimization techniques
10. **Cross-cutting concerns** — logging with structured context and millisecond timing (perf_counter + duration_ms), metrics, observability, feature flags
11. **Design patterns** — result normalization (handling multiple response formats gracefully), protocol-based dependency injection, immutable message contracts, hybrid protocol versioning for backward compatibility

## Output Format

Return a JSON object with exactly one `findings` array. Each finding must have these fields:

```json
{"findings": [
  {
    "title": "Short descriptive title (max 80 chars)",
    "description": "Detailed description of the pattern/feature/technique (2-4 sentences)",
    "category": "one of: architecture|ai_integration|memory|code_quality|cli_ux|testing|data_processing|security|algorithm|cross_cutting|design_patterns",
    "source_files": ["relative/path/to/key/file.py"],
    "source_symbols": [
      {"file_path": "relative/path/to/key/file.py", "symbol_name": "function_or_class_name", "symbol_kind": "function|class|module", "note": "why this symbol matters"}
    ],
    "implementation_sketch": "How this could be adapted for CLAW (2-5 sentences with specific file/class suggestions)",
    "augmentation_notes": "What CLAW currently lacks that this addresses",
    "execution_steps": ["Optional: concrete commands to execute this pattern safely in a target repo"],
    "acceptance_checks": ["Optional: commands that should pass after implementation"],
    "rollback_steps": ["Optional: commands to revert safely if checks fail"],
    "preconditions": ["Optional: required tools/files before execution"],
    "method_contract": {
      "problem": "The exact reusable engineering problem solved by the source",
      "preconditions": ["Conditions that must hold before applying the method"],
      "ordered_steps": ["Ordered operations whose sequence affects correctness"],
      "invariants": ["Properties that must remain true"],
      "failure_behavior": "How the source fails or rejects invalid state",
      "recovery_behavior": "How retry, replay, rollback, or later work recovers",
      "verification": ["Deterministic checks that distinguish a correct implementation"],
      "decision_predicates": ["Exact source-grounded branch conditions and outcomes, preserving truthiness, presence, equality, default/fallback, null, and empty-value distinctions when relevant"],
      "discriminative_terms": ["Source terms and synonyms that identify this exact method"]
    },
    "relevance_score": 0.7,
    "language": "python"
  }
]}
```

## Rules

- Return ONLY the JSON object, no additional text before or after
- Maximum 5 findings per repo; aim for at least 3 when the repo has diverse patterns
- Minimum relevance_score of 0.4 (skip trivial/irrelevant patterns)
- relevance_score range: 0.4 (marginally useful) to 1.0 (directly applicable, high impact)
- Focus on **transferable ideas**, not repo-specific business logic
- Prefer patterns that are **novel or well-implemented**, not obvious boilerplate
- Do NOT skip subtle operational patterns: idempotent operations (safe re-entry, "already exists" handling), structured logging with timing (perf_counter + duration_ms), and result normalization (handling multiple response formats) are high-value even if the category is already represented
- Include the most relevant source files that demonstrate the pattern
- Include `source_symbols` when a specific function, class, or module is the real carrier of the idea
- implementation_sketch should reference specific CLAW modules where the pattern could be integrated
- When including execution/acceptance commands, use concrete, low-risk commands (no destructive operations)

## Repository Content

{repo_content}
