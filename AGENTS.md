# AGENTS.md

## Purpose

This file defines how the coding agent should work in this repository.

Target: a live Python web application already in progress.

Optimize for production-safe progress with minimal churn.

## Priority Order

Always optimize in this exact order:

1. **Simplicity first (KISS)**
   - Implement or refactor in the easiest correct way.
   - Prefer straightforward control flow over clever abstractions.
   - Choose the fewest moving parts that solve the problem well.

2. **DRY and strong structure**
   - Eliminate repeated logic, repeated literals, repeated schemas, and repeated validation.
   - Reuse helpers, constants, typed utilities, shared adapters, and Pydantic models.
   - Centralize cross-cutting behavior.

3. **Low complexity**
   - Minimize branching, nesting, statefulness, and hidden behavior.
   - Reduce cognitive load before optimizing for elegance.

4. **Short functions and short files**
   - Keep functions focused and small.
   - Split files before they become crowded.
   - Prefer composable modules over large mixed-responsibility files.

5. **Production-grade Python practices**
   - Use modern Python 3.13 best practices throughout.
   - Favor correctness, explicitness, maintainability, and operability.

6. **Excellent logging and traceability**
   - Log clearly across debug, info, warning, error, and exception paths.
   - Make production failures easy to diagnose.

7. **Ease of understanding**
   - Write code that reads naturally.
   - Use short inline comments only when they add value.
   - Use concise docstrings for public or non-obvious behavior.

## Core Application Principles

These directly implement the Priority Order and serve as the decision-making filter.

### Boundaries & Structure

- **Layers**: routes (thin) → schemas/DTOs → services (logic) → repositories (data) → infrastructure.
- **Isolation**: Persistence does not leak across boundaries. External API details are behind adapters.
- **Pydantic for shape**: request validation, response models, config, domain payloads, untrusted data.
- **Keep models focused**: reusable, composed, validators only where they belong.

### File & Function Discipline

- One thing per function. Early returns. Avoid nesting.
- Break files when responsibilities diverge. Keep modules cohesive.
- If hard to name simply, doing too much. If logic repeats twice, extract it.

### Comments & Docstrings

- Comment intent, not obvious mechanics.
- Docstrings for public APIs, tricky invariants, non-obvious side effects only.
- Remove stale comments immediately.

### Logging (Production-Ready)

Structured logging with context:

- `debug`: diagnostics, branch decisions, checkpoints
- `info`: successful events worth tracking
- `warning`: recoverable issues, suspicious input
- `error`: failed operations with clear context
- `exception`: unexpected failures with stack trace

Style: `logger.info("event", extra={"key": value})`. Never log secrets/PII. Log at boundaries: request entry, service decisions, external calls, DB ops, failures.

## Implementation Checklist

Before writing code, verify:

1. Is there an existing pattern in the codebase to reuse?
2. What is the simplest correct implementation?
3. Can this be more DRY without harming readability?
4. Should this live in a route, service, repository, or utility?
5. Should a Pydantic model, constant, enum, or helper be introduced?
6. Can function/file size be reduced?
7. Are names precise and descriptive?
8. Are failure modes explicit?
9. Are logs sufficient for production debugging?
10. Is the code easy for another engineer to modify later?

## Preferred Coding Conventions

### Design & Naming

- Prefer composition over inheritance.
- Prefer pure functions where practical.
- Minimize shared mutable state. Keep side effects at edges.
- Make invalid states hard to represent.
- Use clear, literal names. Favor domain language.
- Avoid filler names like `data`, `item`, `manager`, `helper`, `misc`.
- Name functions after behavior, not implementation.

### Errors & Validation

- Fail fast on invalid input. Raise precise exceptions.
- Convert low-level errors to useful application-level errors at boundaries.
- Do not swallow exceptions silently.
- Return clear API errors for user-caused failures.
- Validate inputs at the boundary with Pydantic.

### Config & Secrets

- Centralize all settings.
- Use environment variables through typed settings models.
- Avoid scattered config reads.
- Keep defaults explicit and safe.
- Never log or expose secrets, tokens, or PII.

### Data Access

- Keep queries explicit.
- Avoid leaking ORM objects across boundaries.
- Keep transaction handling predictable.
- Minimize hidden DB work.

### APIs

- Keep handlers thin.
- Return stable response shapes.
- Make error responses consistent.
- Preserve backward compatibility unless deliberately changing.

### Async

- Use async only where it materially helps.
- Do not mix sync and async carelessly.
- Keep concurrency simple and bounded.

## Refactor Rules

- First preserve behavior.
- Then simplify.
- Then deduplicate.
- Then tighten types.
- Then improve naming and structure.
- Do not bundle unrelated refactors.
- Do not rewrite working code without concrete benefit.

Good refactors: remove duplication, shorten a function, isolate side effects, improve type safety, replace magic literals with constants or enums, extract validation into Pydantic models, split overcrowded files.

Bad refactors: introduce abstraction without reuse, hide simple logic behind layers, convert readable code into generic machinery, change architecture without immediate payoff.

## Code Quality Standards

### When Adding New Code

1. Reuse an existing pattern if good.
2. Add the smallest viable implementation.
3. Extract shared pieces only when repetition is real.
4. Add or improve types.
5. Add targeted logging.
6. Add concise tests if the repo includes tests.

### When Reviewing Existing Code

Look for duplicated logic, oversized functions/files, weak typing, route handlers doing too much, unvalidated external input, hidden side effects, poor logging context, vague naming, unnecessary abstraction.

### Output Expectations

- Explain the chosen approach briefly.
- Mention rejected alternatives only if relevant.
- Keep explanations compact.
- Prefer concrete diffs over broad theory.
- Do not pad responses.

## Default Quality Bar

Every change should aim for:

- simpler than before
- drier than before
- more typed than before
- easier to trace in production
- easier to understand later
- minimal surface area
- minimal surprise

**Final principle: Optimize for simple, typed, modular, production-safe Python that another engineer can understand in one pass. Do not optimize for cleverness.**
