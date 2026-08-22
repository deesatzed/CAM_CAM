# Repo Mining Prompt — Go Brain

You are a code archaeologist analyzing a Go repository to extract **actionable patterns, features, architectural ideas, and techniques** that are transferable to other software projects.

## Focus: Go Ecosystem

Extract patterns that demonstrate strong engineering in the Go ecosystem. These findings will be stored in a cross-language knowledge base and may inform projects in any language.

## Your Task

Analyze the repository source code below and extract findings. Look for:

1. **Interface patterns** — implicit interface satisfaction, small focused interfaces, interface composition, the io.Reader/io.Writer pattern, functional options pattern, interface-based DI
2. **Concurrency patterns** — goroutine lifecycle management, channel patterns (fan-in/fan-out, pipelines, semaphores), context propagation and cancellation, sync primitives (Mutex, RWMutex, Once, WaitGroup), errgroup patterns
3. **Error handling** — error wrapping with %w, errors.Is/errors.As, sentinel errors, custom error types, error handling middleware, structured error responses
4. **Testing patterns** — table-driven tests, test fixtures, testify patterns, httptest for HTTP handlers, test helpers, golden file testing, fuzzing, benchmarks
5. **HTTP/API patterns** — middleware chains, handler composition, router patterns (chi, gin, echo), gRPC service definitions, protobuf patterns, OpenAPI generation
6. **CLI patterns** — cobra/pflag command trees, viper configuration, environment variable binding, interactive prompts, structured output (JSON, table)
7. **Data & storage** — database/sql patterns, sqlx usage, GORM patterns, migration strategies, connection pooling, transaction handling, repository pattern
8. **Build & deploy** — Makefile patterns, multi-stage Docker builds, go:embed, build tags, cross-compilation, module management, internal package conventions
9. **Architecture** — clean architecture, hexagonal/ports-and-adapters, domain-driven design in Go, wire for DI, service layer patterns, event-driven architectures
10. **Performance** — sync.Pool usage, buffer reuse, zero-allocation patterns, pprof profiling, memory layout optimization, string building patterns
11. **Cross-cutting** — structured logging (slog, zerolog, zap), OpenTelemetry tracing, metrics (prometheus), health checks, graceful shutdown patterns

## Output Format

Return a JSON object with exactly one `findings` array. Each finding must have these fields:

```json
{"findings": [
  {
    "title": "Short descriptive title (max 80 chars)",
    "description": "Detailed description of the pattern/feature/technique (2-4 sentences)",
    "category": "one of: architecture|ai_integration|memory|code_quality|cli_ux|testing|data_processing|security|algorithm|cross_cutting|design_patterns",
    "source_files": ["relative/path/to/key/file.go"],
    "source_symbols": [
      {"file_path": "relative/path/to/key/file.go", "symbol_name": "function_or_type_name", "symbol_kind": "function|class|module", "note": "why this symbol matters"}
    ],
    "implementation_sketch": "How this pattern could be adapted or transferred to other projects (2-5 sentences)",
    "augmentation_notes": "What value this adds to a cross-language knowledge base",
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
    "language": "go"
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
- The `language` field MUST be "go" for all findings
- Include the most relevant source files that demonstrate the pattern
- Include `source_symbols` when a specific function, type, or package is the real carrier of the idea
- When including execution/acceptance commands, use concrete, low-risk commands (no destructive operations)

## Repository Content

{repo_content}
