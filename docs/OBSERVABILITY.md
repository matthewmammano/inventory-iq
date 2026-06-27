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

- IDs: `agency_id`, `item_id`, `agency_email_id`, `location_id`, `storage_id`, `alert_id`, `action_log_id`, `scheduler_run_id`.
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

## Diagnostics

- Log what happened and the safe identifiers needed to find it.
- Do not make users report stack traces.
- Do not expose internal details in flash messages or templates.
- For production incidents, correlate request logs, task logs, scheduler run rows, alert rows, action logs, and balance rows.
