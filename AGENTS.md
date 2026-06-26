# AGENTS.md

**READ THIS FILE AFTER EVERY PROMPT.** It defines reusable coding-agent rules for production software work.

## Project Docs

Read local project docs when they exist. For this repository:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): module map, layers, and change placement.
- [docs/DATA_MODEL.md](docs/DATA_MODEL.md): tables, ownership, and persistence invariants.
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): stack, setup, env vars, migrations, commands, and cron tasks.
- [docs/ADMIN_WORKFLOWS.md](docs/ADMIN_WORKFLOWS.md): admin and scan workflow behavior.
- [docs/OBSERVABILITY.md](docs/OBSERVABILITY.md): logging, traceability, and diagnostics.
- [docs/REPO_CONVENTIONS.md](docs/REPO_CONVENTIONS.md): Inventory IQ-specific UI, flash, modal, and email conventions.
- [docs/TODO.md](docs/TODO.md): active plan, deferred work, and future improvements.

## Priority Order

**ALWAYS OPTIMIZE IN THIS EXACT ORDER:**

1. **SIMPLICITY FIRST:** choose the easiest correct implementation.
2. **DRY AND STRONG STRUCTURE:** centralize repeated logic, literals, schemas, validation, and cross-cutting behavior.
3. **LOW COMPLEXITY:** prefer straightforward control flow, early returns, and shallow nesting.
4. **SHORT FUNCTIONS AND FILES:** keep modules cohesive and split by responsibility before they get crowded.
5. **PRODUCTION-GRADE PYTHON:** favor correctness, explicitness, typing, maintainability, and operability.
6. **EXCELLENT TRACEABILITY:** make failures diagnosable without exposing secrets or PII.
7. **EASE OF UNDERSTANDING:** code should read naturally in one pass.

## Architecture Rules

- **PRESERVE BOUNDARIES:** routes -> schemas/DTOs -> services -> repositories/queries -> infrastructure.
- **KEEP HANDLERS THIN.** Put business decisions in services and persistence in query/repository-style modules.
- **VALIDATE UNTRUSTED INPUT AT BOUNDARIES** with Pydantic or existing typed validators.
- Keep external API/provider details behind adapters.
- Do not leak ORM or persistence details across layers unless the existing codebase clearly does so.
- **MAKE INVALID STATES HARD TO REPRESENT** with types, constants, enums, constraints, or focused models.
- **DO NOT KEEP BACKWARD-COMPATIBILITY SHIMS FOR DEAD CODE.** If there is no explicit live API, migration path, production data dependency, or user-facing contract requiring compatibility, prefer a clean full refactor over preserving old names, duplicate paths, or legacy adapters.

## Implementation Checklist

Before writing code, verify:

1. What existing pattern should be reused?
2. What is the simplest correct implementation?
3. Can duplication be removed without hiding simple logic?
4. Which layer owns this change?
5. Should a Pydantic model, constant, enum, helper, or service function be introduced?
6. Are names precise and domain-specific?
7. Are failure modes explicit?
8. Are logs sufficient and safe?
9. Is the change easy to review, test, and revert?
10. Is the result easy for another engineer to modify later?

## Python Conventions

- Prefer composition over inheritance.
- Prefer pure functions where practical.
- **MINIMIZE SHARED MUTABLE STATE.** Keep side effects at the edges.
- Use f-strings for Python interpolation; do not use Loguru `{}` placeholders or `.format()`.
- Avoid filler names like `data`, `item`, `manager`, `helper`, `misc`, unless they are precise in context.
- Name functions after behavior, not implementation details.
- Comment intent, not mechanics. Use docstrings for public APIs, tricky invariants, or non-obvious side effects.
- Use async only where it materially helps, and keep concurrency bounded and simple.

## Errors, Config, And Data

- **FAIL FAST** on invalid input with precise exceptions.
- Convert low-level errors to useful application-level errors at boundaries.
- Do not swallow exceptions silently.
- Return stable API shapes and consistent user-caused errors.
- Centralize settings in typed config models. Avoid scattered environment reads.
- Keep defaults explicit and safe.
- **NEVER LOG OR EXPOSE SECRETS, TOKENS, PASSWORDS, RESET CODES, RAW PII, OR SENSITIVE PAYLOADS.**
- Keep database queries explicit and transaction handling predictable.
- **ADD MIGRATIONS FOR SCHEMA CHANGES; DO NOT RELY ON IMPLICIT TABLE CREATION IN PRODUCTION.**

## Refactor Rules

- **PRESERVE BEHAVIOR FIRST.**
- Then simplify.
- Then deduplicate.
- Then tighten types.
- Then improve naming and structure.
- **DO NOT BUNDLE UNRELATED REFACTORS.**
- **DO NOT REWRITE WORKING CODE WITHOUT CONCRETE BENEFIT.**
- Prefer clean replacement over compatibility layers when old behavior is not a live contract.

Good refactors remove duplication, shorten a function, isolate side effects, improve type safety, replace magic literals with constants/enums, extract validation into models, or split overcrowded files.

Bad refactors introduce abstraction without reuse, hide simple logic behind generic machinery, change architecture without immediate payoff, or mix formatting churn with behavior changes.

## Review Standard

When reviewing or editing, look for:

- duplicated logic or literals
- oversized functions or files
- weak typing or unvalidated input
- route handlers doing too much
- hidden side effects or implicit DB work
- poor logging context or unsafe logs
- vague naming
- unnecessary abstraction
- missing tests or verification for risky behavior

## Output Expectations

- Prefer concrete diffs over broad theory.
- Explain the chosen approach briefly.
- Mention rejected alternatives only when relevant.
- Say what verification ran, or what could not be run.
- Do not pad responses.

## Default Quality Bar

Every change should be:

- simpler than before
- drier than before
- more typed where it matters
- easier to trace in production
- easier to understand later
- minimal in surface area
- unsurprising

**FINAL PRINCIPLE: OPTIMIZE FOR SIMPLE, TYPED, MODULAR, PRODUCTION-SAFE CODE THAT ANOTHER ENGINEER CAN UNDERSTAND IN ONE PASS. DO NOT OPTIMIZE FOR CLEVERNESS.**
