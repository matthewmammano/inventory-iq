# Code Quality Tooling

What every configured lint/type/security tool actually checks, why it's there, and which `AGENTS.md` rule it backs. Config lives in `pyproject.toml` and `.pre-commit-config.yaml`; install/run everything with `pre-commit run --all-files`.

## Ruff

One tool, many rule groups (`[tool.ruff.lint].select`). Each group maps to a reason:

| Group | Checks | Backs |
| --- | --- | --- |
| `E`, `F`, `I`, `UP`, `B`, `C4`, `SIM`, `RUF`, `NPY`, `PTH`, `N`, `ERA` | Baseline correctness, import order, modern syntax, bugbear traps, comprehension style, dead commented-out code | General Python hygiene |
| `C90` (mccabe) | Cyclomatic complexity per function, capped at 10 (`[tool.ruff.lint.mccabe]`) | "SHORT FUNCTIONS AND FILES" / "LOW COMPLEXITY" |
| `PLR0911/0912/0913/0915` | Too many returns / branches / arguments / statements in one function | Same: the concrete length/complexity signal, deliberately scoped to just these four codes rather than the full noisy `PLR` family (which also includes style opinions like magic-value comparisons) |
| `ARG` | Unused function arguments | Catches leftover params after a refactor |
| `A` | Shadowing a Python builtin (`id`, `type`, `list` as a variable name) | Naming precision |

Run: `ruff check .` / `ruff format .` (also runs automatically via pre-commit).

**Not enforced by ruff:** "docstrings required on public APIs" (`AGENTS.md`, Comments section) stays a written rule only. Turning on `D101/102/103` surfaced 380 pre-existing gaps across the codebase, and pre-commit lints a changed file's whole content, not just touched lines; an unrelated one-line fix would fail over pre-existing gaps in that file. Not worth the friction right now.

## Pyright + Mypy

Both run in CI/pre-commit against `app`, `scripts`, `tasks`. Redundant on purpose during the transition to full typing: pyright is faster and IDE-aligned, mypy catches a few things pyright doesn't. Backs "PRODUCTION-GRADE PYTHON: favor correctness, explicitness, typing."

## Bandit

Static security scanner for `app/` (SQL injection patterns, `eval`/`exec` use, hardcoded passwords, insecure deserialization, etc.). Backs the "NEVER LOG OR EXPOSE SECRETS" spirit at the static-analysis level, not just logging.

## Gitleaks

Scans every commit's diff for accidentally-committed secrets (API keys, tokens, private keys) before they land in history.

## djLint

Jinja template linter (`app/**/templates/**/*.html`): catches malformed/inconsistent template markup. Backs `docs/CONVENTIONS.md`'s Templates And Modals rules.

## Vulture

Dead-code detector (`[tool.vulture]`, `paths = ["app", "scripts", "tasks"]`, `min_confidence = 80`). Directly enforces "DO NOT KEEP BACKWARD-COMPATIBILITY SHIMS FOR DEAD CODE" instead of relying on someone noticing during review.

**Known false-positive source:** Vulture can't see a function called only from a Flask route decorator's dispatch table or only referenced from a Jinja template (`{{ some_macro(...) }}`). If it flags a route handler or a Jinja-called helper as "unused," that's expected for this stack; confirm it's genuinely dead (grep for the route/template reference) before deleting. Vulture's own `whitelist.py` mechanism exists for recurring false positives if this gets noisy.

## Import Linter

Encodes part of the Architecture Rules layering as a mechanically-checked contract (`[tool.importlinter]`) instead of only a written rule. Currently one narrow, verified-passing contract: `app.shared.config`, `app.shared.database`, `app.shared.clock`, and `app.shared.validators` (the genuinely foundational modules) may never import from any domain package (`app.inventory`, `app.auth`, `app.prediction`, `app.alerts`, `app.diagnostics`, `app.admin_help`).

This is intentionally a starting contract, not the full `routes -> services -> queries -> infra` layering from `AGENTS.md`; expressing that fully would need `app/inventory/`'s flat service/query files reorganized into dedicated subpackages first (a separate, larger change, not done as a side effect of adding this tool). `app/shared/scheduler.py` and `app/shared/utils.py` are legitimate cross-domain orchestrators and are deliberately excluded from the contract's source modules.

Run: `lint-imports`.

## Flask App Import (local smoke check)

`python -c "from app import create_app; create_app()"`: the cheapest possible check that the app still boots (catches import cycles, missing config, broken blueprint registration) before anything more expensive runs.

## Pre-commit Housekeeping Hooks

Trailing whitespace, end-of-file newline, YAML/TOML/JSON syntax, merge-conflict markers, case conflicts, AST validity, `breakpoint()`/`pdb` leftovers, private-key detection, LF line endings, large-file guard. Standard hygiene, not project-specific.
