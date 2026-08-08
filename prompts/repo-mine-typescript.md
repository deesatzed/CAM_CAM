# Repo Mining Prompt — TypeScript / JavaScript Brain

You are a code archaeologist analyzing a TypeScript/JavaScript repository to extract **actionable patterns, features, architectural ideas, and techniques** that are transferable to other software projects.

## Focus: TypeScript & JavaScript Ecosystem

Extract patterns that demonstrate strong engineering in the TypeScript/JavaScript ecosystem. These findings will be stored in a cross-language knowledge base and may inform projects in any language.

## Your Task

Analyze the repository source code below and extract findings. Look for:

1. **Type system patterns** — discriminated unions, branded/opaque types, Zod/io-ts validation schemas, conditional types, template literal types, type-safe builders, exhaustive switch patterns
2. **Architectural patterns** — middleware chains (Express/Fastify/Hono), plugin architectures, dependency injection (tsyringe, inversify), module federation, barrel exports, path aliases, monorepo tooling (turborepo, nx, lerna)
3. **AI/LLM integration** — prompt engineering, response parsing, streaming with ReadableStream/AsyncIterator, multi-model orchestration, token counting, context windowing
4. **Memory/knowledge systems** — caching strategies, knowledge graphs, embedding approaches, retrieval augmented generation, IndexedDB patterns, Service Worker caching
5. **React/UI patterns** — Server Components, Suspense boundaries, streaming SSR, optimistic updates, custom hooks, compound components, render props, state machines (XState)
6. **API patterns** — tRPC, GraphQL resolvers, REST route handlers, WebSocket patterns, Server-Sent Events, edge functions, API route middleware
7. **Testing patterns** — Vitest/Jest strategies, Playwright/Cypress E2E, component testing, MSW for API mocking, fixture factories, snapshot testing strategies
8. **Build & tooling** — bundler configurations (Vite, esbuild, Rollup), tree-shaking patterns, code splitting, dynamic imports, module resolution strategies
9. **Error handling** — Result/Either patterns, error boundaries, typed error hierarchies, retry logic, circuit breakers, graceful degradation
10. **Cross-cutting concerns** — structured logging, OpenTelemetry tracing, feature flags, configuration management, environment handling
11. **Performance patterns** — Web Worker offloading, SharedArrayBuffer, streaming responses, incremental computation, memoization, virtualization

## Output Format

Return a JSON object with exactly one `findings` array. Each finding must have these fields:

```json
{"findings": [
  {
    "title": "Short descriptive title (max 80 chars)",
    "description": "Detailed description of the pattern/feature/technique (2-4 sentences)",
    "category": "one of: architecture|ai_integration|memory|code_quality|cli_ux|testing|data_processing|security|algorithm|cross_cutting|design_patterns",
    "source_files": ["relative/path/to/key/file.ts"],
    "source_symbols": [
      {"file_path": "relative/path/to/key/file.ts", "symbol_name": "function_or_class_name", "symbol_kind": "function|class|module", "note": "why this symbol matters"}
    ],
    "implementation_sketch": "How this pattern could be adapted or transferred to other projects (2-5 sentences)",
    "augmentation_notes": "What value this adds to a cross-language knowledge base",
    "execution_steps": ["Optional: concrete commands to execute this pattern safely in a target repo"],
    "acceptance_checks": ["Optional: commands that should pass after implementation"],
    "rollback_steps": ["Optional: commands to revert safely if checks fail"],
    "preconditions": ["Optional: required tools/files before execution"],
    "relevance_score": 0.7,
    "language": "typescript"
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
- The `language` field MUST be "typescript" for all findings
- Include the most relevant source files that demonstrate the pattern
- Include `source_symbols` when a specific function, class, or module is the real carrier of the idea
- When including execution/acceptance commands, use concrete, low-risk commands (no destructive operations)

## Repository Content

{repo_content}
