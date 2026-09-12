# AGENTS.md

**READ THIS FILE AFTER EVERY PROMPT.** It defines reusable coding-agent rules for production software work.

## Project Docs

Read local project docs when they exist. For this repository:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): module map, layers, and change placement.
- [docs/DATA_MODEL.md](docs/DATA_MODEL.md): tables, ownership, and persistence invariants.
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): stack, setup, env vars, migrations, commands, and cron tasks.
- [docs/ADMIN_WORKFLOWS.md](docs/ADMIN_WORKFLOWS.md): admin and scan workflow behavior.
- [docs/OBSERVABILITY.md](docs/OBSERVABILITY.md): logging, traceability, and diagnostics.
- [docs/CONVENTIONS.md](docs/CONVENTIONS.md): Inventory IQ-specific UI, flash, modal, and email conventions.
- [docs/TODO.md](docs/TODO.md): active plan, deferred work, and future improvements.
- [docs/CODE_QUALITY.md](docs/CODE_QUALITY.md): what each configured lint/type/security tool checks and why.

## Priority Order

**ALWAYS OPTIMIZE IN THIS EXACT ORDER:**

1. **SIMPLICITY FIRST:** choose the easiest correct implementation.
2. **DRY AND STRONG STRUCTURE:** centralize repeated logic, literals, schemas, validation, and cross-cutting behavior.
   - DRY is about knowledge, not text. Two functions that look identical today but encode different business rules are not duplication. Merging them creates false coupling. Confirm two code paths represent the *same* decision before deduplicating them.
   - **Rule of Three:** wait for a third real occurrence before extracting a shared abstraction, not the second. A single early duplication is often coincidence.
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
- **DESIGN DEEP MODULES:** a simple interface hiding real complexity, not a simple implementation exposing a complex one. A new parameter or public method is a red flag if it leaks an internal decision the caller shouldn't need to know.
- A design decision should live in exactly one module's implementation and never appear in its interface. If changing an internal detail forces a signature change elsewhere, it wasn't actually hidden.
- Ports (interfaces the domain/service layer depends on) belong to that layer; adapters (concrete implementations, e.g. a specific email provider or DB driver) belong to infrastructure. The dependency direction always points from infrastructure toward the domain, never the reverse.

## Pydantic & Schema Design

- Lock down boundary models: `model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)` on request/input models, so unknown fields raise instead of vanishing and stray whitespace can't sneak through.
- Use `@computed_field`, not a plain `@property`, for anything derived that must appear in `.model_dump()`/JSON output. A `@property` is invisible to serialization.
- One Pydantic model per boundary shape. Never reuse a request model as a response model, or let an ORM-facing model double as an API model.
- A shape with no external/untrusted data and no need for validation is a `@dataclass(frozen=True, slots=True)`, not a Pydantic model. Reserve Pydantic for boundaries that actually need parsing/validation. For a boundary shape that's just a bare list/primitive (not an object), validate it directly with `TypeAdapter`/`RootModel` instead of wrapping it in a model that exists only to hold one field.

## SQLAlchemy & Data Layer

- One session per request/task, explicit lifecycle: open at the start, commit on success, always close. Never let a session outlive its request/task boundary or get reused across unrelated units of work.
- Match eager-load strategy to the relationship shape: `selectinload` for collections, `joinedload` for scalar/to-one. This is the standing fix for N+1 queries; apply it as a rule, not something rediscovered per PR.
- Commit/rollback decisions stay at the route/task boundary, never inside a service function. A service takes a session and uses it; it does not decide when the transaction ends.

## Frontend & Responsive CSS

- **DYNAMIC OVER HARD-CODED:** express sizes with `clamp()`, viewport units (`vw`/`svh`/`dvh`), `%`, or `fr`, not flat `px`/`rem` literals repeated across the file. A value should scale by formula, not by enumerating breakpoints for it.
- Centralize repeated "magic" sizes as CSS custom properties on `:root` (a small design-token set) the same way a Python constant replaces a repeated literal.
- Prefer a container query (`@container`) over a viewport `@media` query when a component's own box size, not the viewport, is what should drive its layout.
- Use CSS Cascade Layers (`@layer`) to make override precedence explicit and independent of source-file position; never rely on "this rule must physically come after that one" as the mechanism for a rule to win.
- Component-scoped CSS lives in that component's own file; only truly global tokens/resets belong in the shared base stylesheet.
- Verify a responsive change against the project's real device/breakpoint matrix, not just one browser width, before calling it done.

## Implementation Checklist

Before writing code, verify:

1. **Design the schema first.** Nail down the Pydantic/SQLAlchemy model(s) for every domain concept the change touches, and check that shape actually covers every known use case, before designing any logic against it. Logic gets built on top of a finished schema, not alongside a shifting one.
2. What existing pattern should be reused?
3. What is the simplest correct implementation?
4. Can duplication be removed without hiding simple logic?
5. Which layer owns this change?
6. Should a Pydantic model, constant, enum, helper, or service function be introduced?
7. Are names precise and domain-specific?
8. Are failure modes explicit?
9. Are logs sufficient and safe?
10. Is the change easy to review, test, and revert?
11. Is the result easy for another engineer to modify later?

## Python Conventions

- Prefer composition over inheritance.
- Prefer pure functions where practical.
- **MINIMIZE SHARED MUTABLE STATE.** Keep side effects at the edges.
- Use f-strings for Python interpolation; do not use Loguru `{}` placeholders or `.format()`.
- Avoid filler names like `data`, `item`, `manager`, `helper`, `misc`, unless they are precise in context.
- Name functions after behavior, not implementation details.
- Use async only where it materially helps, and keep concurrency bounded and simple.
- Public names should read correctly out of context; no abbreviation that only makes sense inside the function it's declared in.
- No `@staticmethod` unless an existing library's interface forces it. If a "method" never touches `self`, it's a module-level function.
- One term, one meaning, everywhere in the codebase. If a word names one domain concept in one module, it cannot name a different one elsewhere.

## Comments

- **No multi-line `#` (or `//`) comment blocks, ever.** A comment is one line, placed directly above or beside the line it explains.
- **Keep that one line tiny:** a clause, not a paragraph packed onto one physical line. If it needs more, that is the docstring/smaller-function signal below, not permission to write a longer single line.
- If an explanation genuinely needs more than one line, it belongs in the function/class docstring (required on public APIs), not a stacked `#` paragraph. If it is not docstring-worthy either, that is a sign the code needs a better name or a smaller function, not a comment.
- No em-dash, and no `--` standing in for one (`--flag`/`--custom-property` are unaffected: those never have a space before the dashes). Use a period, semicolon, or plain `-`. `scripts/check_dashes.py` checks this.
- Comment only when the code cannot say it: a non-obvious helper (what + why, one line), a regex/bitmask/magic number, a non-obvious early return, an edge-case or workaround, an external call's (HTTP/DB/subprocess/file IO) side effect, a try/except's actual failure mode, a concurrency invariant, or a config/env read's meaning and default.
- Never comment what the code already says. No banner/divider comments, no commented-out code left behind, no restating the function name in prose.
- Never explain *why a change was made* (no "used to do X, now does Y because...", no referencing a past bug, ticket, or prior version). Comments describe the current logic and behavior only, as if the code had always been this way.

## Errors, Config, And Data

- **FAIL FAST** on invalid input with precise exceptions.
- Convert low-level errors to useful application-level errors at boundaries.
- Do not swallow exceptions silently.
- Reserve raised exceptions for genuinely unexpected/unrecoverable conditions. When the immediate caller is expected to branch on an outcome (not-found, validation failure), a typed return (e.g. `Item | None`) is more honest and cheaper to trace than throw-and-catch.
- Introduce a named exception (not a bare `ValueError`) only where a caller genuinely needs to distinguish failure types from another. Don't build an exception hierarchy speculatively.
- Return stable API shapes and consistent user-caused errors.
- Centralize settings in typed config models. Avoid scattered environment reads.
- Backing services (database, email provider, external APIs) are reachable purely through config; swapping one for another is a config change, never a code change.
- Keep defaults explicit and safe.
- **NEVER LOG OR EXPOSE SECRETS, TOKENS, PASSWORDS, RESET CODES, RAW PII, OR SENSITIVE PAYLOADS.**
- The app logs to stdout; local rotating log files (`app/shared/logging.py`) are a deliberate dev-only convenience, not a pattern to extend.
- Keep database queries explicit and transaction handling predictable.
- If raw SQL is ever written outside the SQLAlchemy query layer, keep it dialect-agnostic; dev runs SQLite, production runs Postgres.
- **ADD MIGRATIONS FOR SCHEMA CHANGES; DO NOT RELY ON IMPLICIT TABLE CREATION IN PRODUCTION.**
- Every scheduled/background job must be idempotent and guarded against overlapping runs; use the existing `claimed_scheduler_run`/`logged_task` pattern (`app/shared/scheduler.py`, `app/shared/task_logging.py`), not a new ad hoc mechanism.

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

Named smells worth flagging on sight:

- **Feature Envy**: a function reaching into another module's/object's internals more than its own belongs on the other side.
- **Primitive Obsession**: a bare `str`/`int` standing in for a domain concept (a UPC, a quantity-with-unit) should be a small typed value instead. This is the concrete case the "make invalid states hard to represent" rule exists to catch.
- **Data Clumps**: the same 3+ parameters traveling together across multiple signatures is an unmodeled type, not a coincidence.

**Removing an old shape or path (procedure, not just the principle above):**

1. Grep every caller first (`rg`/`grep` the symbol). Know the full blast radius before touching anything.
2. Change the definition and all call sites together, in the same pass. One shape, one commit.
3. Delete the old function/type/branch entirely - no alias kept "just in case," no ignored `kwargs`, no `if new_shape: ... else: <old>` straddling two designs.
4. Verify it is gone: a dead-code check (e.g. `ruff check --select F401,F841 .`) plus a grep of the old name, both clean.
5. If a clean removal is genuinely unsafe (an external consumer you cannot edit, a live contract you cannot break), stop and say why in one or two sentences instead of quietly adding a shim.

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

## Git Execution

- **Never run `git add`, `git commit`, `git push`, or `gh pr create`.** Always print the exact command for the human to run instead.
- The only exception is an explicit, same-message grant of permission for that specific action (e.g. "you have permission to run this," "run it yourself") - approving a plan, or saying "ok"/"looks good," is not that grant.
- For commit message, branch name, and split-vs-single-commit decisions, use `.agents/skills/git-change-workflow/` rather than improvising the format here.

## Explanations In Chat

- Be direct and condensed. Lead with the point, cut filler and hedging.
- Do not restate what the code already shows, and do not throat-clear ("I've gone ahead and...", "Let's dive into...").
- Say what changed and why (one layer of "why" is enough), then stop.

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

## Keeping This File Useful

This file grows over time. Keep it scannable, not overwhelming:

- Add a rule here only if it is generic and reusable across features. A project-specific fact (a table name, a UI wording rule, a deployment detail) belongs in `docs/*.md`, not here.
- One rule = one line wherever possible. A rule that needs more than 2-3 lines to state is usually better as a linter rule, or an example in `docs/*.md`, than as prose here.
- Add a new bullet to an existing section before creating a new heading. A new heading needs 3+ related rules to justify itself; that's why Pydantic and SQLAlchemy each got a section, but single ideas got folded into Architecture Rules, Python Conventions, and Errors/Config/Data instead.
- Name a known pattern or smell (and cite it) instead of re-explaining it from scratch; this file assumes the reader already knows the named concept once it's introduced.
- Before adding a rule, check whether it is already covered elsewhere in this file under different wording. Don't create near-duplicates.
- Cut anything a configured lint/type-check tool already enforces mechanically (see `docs/CODE_QUALITY.md`); don't duplicate a machine-checked rule in prose here.

**FINAL PRINCIPLE: OPTIMIZE FOR SIMPLE, TYPED, MODULAR, PRODUCTION-SAFE CODE THAT ANOTHER ENGINEER CAN UNDERSTAND IN ONE PASS. DO NOT OPTIMIZE FOR CLEVERNESS.**
