# Repo Mining Prompt — General / Misc Brain

You are a code archaeologist analyzing a repository to extract **actionable patterns, features, architectural ideas, and techniques** that are transferable to other software projects.

## Focus: Language-Agnostic Patterns

This repository may use any programming language. Extract patterns that demonstrate strong engineering regardless of the specific language. Focus on transferable architectural ideas, algorithms, and design decisions.

## Your Task

Analyze the repository source code below and extract findings. Look for:

1. **Architectural patterns** — state machines, event systems, plugin architectures, middleware chains, dependency injection, layered architecture, hexagonal/ports-and-adapters, microservice boundaries
2. **AI/LLM integration** — prompt engineering, response parsing, multi-model orchestration, context management, token optimization, embedding strategies, RAG pipelines
3. **Memory/knowledge systems** — caching strategies (LRU, LFU, TTL), knowledge graphs, vector storage, retrieval augmented generation, index structures
4. **Error handling** — error hierarchy design, retry logic, circuit breakers, graceful degradation, idempotent operations, fallback chains
5. **API design** — REST conventions, RPC patterns, GraphQL schemas, WebSocket protocols, versioning strategies, pagination, rate limiting
6. **Testing patterns** — test organization, fixture strategies, property-based testing, integration test harnesses, test data management, CI-aware test separation
7. **Data processing** — pipeline patterns, stream processing, batch processing, ETL, data validation, schema evolution
8. **Security patterns** — authentication flows, authorization models (RBAC, ABAC), input validation, secret management, sandboxing
9. **Build & deployment** — CI/CD patterns, containerization, infrastructure as code, feature flags, blue-green deployment, canary releases
10. **Performance** — profiling strategies, caching layers, connection pooling, lazy initialization, batch operations, concurrency patterns
11. **Cross-cutting concerns** — structured logging, distributed tracing, metrics collection, configuration management, feature toggles, health checks

## Output Format

Return a JSON object with exactly one `findings` array. Each finding must have these fields:

```json
{"findings": [
  {
    "title": "Short descriptive title (max 80 chars)",
    "description": "Detailed description of the pattern/feature/technique (2-4 sentences)",
    "category": "one of: architecture|ai_integration|memory|code_quality|cli_ux|testing|data_processing|security|algorithm|cross_cutting|design_patterns",
    "source_files": ["relative/path/to/key/file"],
    "source_symbols": [
      {"file_path": "relative/path/to/key/file", "symbol_name": "function_or_class_name", "symbol_kind": "function|class|module", "note": "why this symbol matters"}
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
    "language": "detected_language"
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
- Set the `language` field to the actual primary language of this repository (e.g. "java", "ruby", "c++", "elixir")
- Include the most relevant source files that demonstrate the pattern
- Include `source_symbols` when a specific function, class, or module is the real carrier of the idea
- When including execution/acceptance commands, use concrete, low-risk commands (no destructive operations)

## Repository Content

{repo_content}
