---
name: git-change-workflow
description: Generate production-safe git change guidance after inspecting the real repository changes. Use when the user asks for a Conventional Commit message/header/string, branch name, change summary, commit split strategy, release/deploy flow advice, or dev-to-prod git strategy for Python web app work.
---

# Git Change Workflow

## Overview

Produce git guidance from evidence, not memory. Inspect the worktree first, classify the real intent, and output the smallest useful answer the user requested.

## Required Inspection

1. Read repository instructions first, especially `AGENTS.md` and any files it references.
2. Run `git status --short`.
3. Inspect staged and unstaged changes:
   - `git diff --cached --stat`
   - `git diff --stat`
   - `git diff --cached`
   - `git diff`
4. Inspect untracked files before naming the change. Use `git ls-files --others --exclude-standard`, then read concise contents for relevant text files.
5. Treat deletions, moves, generated files, docs, migrations, config, tests, and UI copy as part of the same intent until the diff proves they are unrelated.
6. If the user asks for "all uncommitted files", include staged, unstaged, deleted, renamed, and untracked files.

## Commit Message Rules

Use Conventional Commits:

```text
<type>(<scope>): <description>
```

Prefer these types:

- `feat`: user-visible capability or meaningful workflow addition.
- `fix`: bug fix or incorrect behavior corrected.
- `refactor`: internal restructuring without behavior change.
- `perf`: performance improvement.
- `test`: tests only.
- `docs`: documentation only.
- `build`: dependencies, packaging, build system.
- `ci`: CI/CD config.
- `style`: formatting-only source changes.
- `chore`: maintenance that does not fit better elsewhere.
- `revert`: revert of previous commit(s).

Choose the scope from the dominant changed area like a concrete module change in Python. Do not invent broad scopes like `app` when a tighter scope is clear.

Descriptions must be lowercase, imperative, no trailing period, and ideally 50 characters or fewer. Keep one-line output when the user asks for a concise string. Use a body only when the user asks for a full commit message or the change has non-obvious risk, migration, deploy, or rollback context.

When multiple unrelated intents are present, say so briefly and either provide multiple commit messages or, if the user demanded one string, choose the safest umbrella type/scope. Prefer splitting commits when the diff mixes behavior, docs, formatting, and infrastructure without one clear product intent. Try to only split when a CLEAR split is available and you can say the `git add` command to stage each commit separately WITHOUT breaking up a file in the middle of a change. If you cannot split cleanly, use a single commit with a body that explains the multiple intents.

## Python Production Gate

For Python web app changes, account for production risk in the wording and recommendations:

- Prefer small, reviewable commits with one behavioral intent.
- Mention migrations, config, dependency, scheduler, auth, email, logging, or data-safety changes when they dominate the diff.
- Before suggesting a commit is ready, prefer repo-native checks: tests, lint, type checks, migrations, and any documented smoke test.
- Do not imply checks passed unless they actually ran.
- Do not include secrets, raw PII, stack traces, or env values in commit bodies.
- For generated artifacts, distinguish source changes from generated output.

## Branch Names

When asked for a branch name, use lowercase kebab-case:

```text
<kind>/<short-change>
```

Use `feat/`, `fix/`, `refactor/`, `docs/`, `chore/`, `hotfix/`, or `release/`. Keep branches short-lived. Prefer `main` as the deployable trunk for small teams and live apps; use release or hotfix branches only when deployment control needs them.

Examples:

- `feat/admin-history-print-scope`
- `fix/logging-context-format`
- `docs/repo-agent-practices`
- `chore/git-change-workflow`

## Dev To Prod Guidance

Prefer this default for a small production Python web app:

1. Short-lived branch from `main`.
2. Small commits with Conventional Commit messages.
3. PR or local review with tests and migration/deploy notes.
4. Merge to `main` only when green.
5. Deploy the same commit SHA through staging or production.
6. Prefer fix-forward for low-risk issues; use `hotfix/` from `main` for urgent production fixes.
7. Keep local, staging, and production services as similar as practical, especially database engine and env-driven config.

## Output Modes

If the user says "output just the string", output only the commit message or branch name. Otherwise keep the answer concise:

- proposed commit message
- optional branch name when relevant
- one-sentence rationale if useful
- checks not run, only if the user needs readiness status
