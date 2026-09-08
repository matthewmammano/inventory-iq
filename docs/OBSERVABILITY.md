# Observability

Logging, traceability, and safe diagnostics for Inventory IQ. User-facing message rules live in [CONVENTIONS.md](CONVENTIONS.md).

## Logging Setup

- `app/shared/logging.py`: Loguru sinks and console/JSON formatting.
- `app/shared/request_logging.py`: request lifecycle logging.
- `app/shared/task_logging.py`: task entrypoint logging.
- `gunicorn_logging.conf`: Gunicorn logging integration.
- Production uses JSON logs; local/dev uses readable console logs.

## Log Style

Use stable event messages plus structured context:

```python
logger.info("Inventory report email sent", extra={"agency_id": agency.id, "recipient_count": sent})
```

- Do not use Loguru `{}` placeholders or `.format()`.
- Prefer `extra` for IDs, counts, flags, and safe status.
- Never log secrets, tokens, reset PINs, passwords, full payloads, raw free text, or PII.
- Avoid raw email addresses; prefer recipient counts, row IDs, or domains only when safe.

## Levels

- `debug`: branch decisions, checkpoints, counts, skipped optional work.
- `info`: successful user-facing or scheduled events worth tracking.
- `warning`: handled but suspicious, invalid, degraded, or recoverable issue.
- `error`: operation failed after expected handling and no stack trace is needed.
- `exception`: unexpected failure inside `except` when stack trace is needed.
- `critical`: process, scheduler, database, or system health cannot continue normally.

## Context Keys

Prefer concrete identifiers and counts:

- IDs: `agency_id`, `item_id`, `notification_recipient_id`, `location_id`, `storage_id`, `alert_id`, `action_log_id`, `scheduler_run_id`.
- Counts: `changed_count`, `saved_count`, `recipient_count`, `pending_alerts`, `rows_checked`, `mismatch_count`, `repaired_row_count`.
- Flags: `force`, `admin_action`, `repair`, `active`.
- Task fields: `job_name`, `period_key`, `schedule_local_time`.

## Boundaries To Log

- App startup and config capability status.
- Request entry/exit and blocked access.
- Admin saves and bulk operations.
- Inventory writes and balance reconciliation.
- External email calls and delivery outcomes.
- Scheduler/task claim, success, skip, and failure.
- Unexpected exceptions with enough IDs to reproduce safely.

## Background Jobs

Every scheduled/background job must be idempotent (safe to run twice) and guarded against overlapping runs. This repo already has the pattern — new jobs reuse it rather than inventing a new mechanism:

- `app/shared/scheduler.py`'s `claimed_scheduler_run(job_name, period_key, agency_id)` atomically claims one time window per job via a DB-level `UniqueConstraint` on `(job_name, agency_id, period_key)` (`SchedulerRun` in `app/shared/models.py`) -- a second concurrent/duplicate attempt to claim the same window is rejected at the database, not just in-process.
- `app/shared/task_logging.py`'s `logged_task(task_name, **context)` wraps a run with a generated `task_run_id`, logging `"Task started"`/`"Task finished"`/`"Task failed"` with duration automatically -- see `tasks/retrain_models.py` for the standard shape a production cron entrypoint follows.
- `task_run_id` is already a recognized context key (`app/shared/logging.py`'s `CONTEXT_KEYS`), so any log line inside a `logged_task` block is automatically correlated to its run without adding it manually.

## Client Diagnostics

`POST /api/debug/report` ([app/diagnostics/](../app/diagnostics/)) logs one `"Client diagnostics received"` event per report: browser/device fields plus server-resolved `ip`/`country`/`city` under a nested `client_diagnostics` key, with `correlated_request_id` alongside it at the top level for grepping against the failing request's `X-Request-ID`. The client (`app/static/js/diagnostics.js`) sends once per browser session and again on unhandled JS errors/failed fetches — not on every request. Geo lookups are best-effort, cached per-process by IP (`app/diagnostics/geo_lookup.py`), and the endpoint is rate-limited per IP.

## Diagnostics

- Log what happened and the safe identifiers needed to find it.
- Do not make users report stack traces.
- Do not expose internal details in flash messages or templates.
- For production incidents, correlate request logs, task logs, scheduler run rows, alert rows, action logs, and balance rows.
