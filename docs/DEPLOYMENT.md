# Deployment

Runtime, environment, and operational commands for Inventory IQ. Architecture lives in [ARCHITECTURE.md](ARCHITECTURE.md).

## Stack

- Python 3.13
- Flask
- SQLAlchemy
- Alembic
- Pydantic Settings
- Loguru
- Gunicorn
- PostgreSQL in production; local default is SQLite.

## Local Setup

1. Copy `.env.example` to `.env`.
2. Set `SECRET_KEY`.
3. Run `alembic upgrade head`.
4. Start the app with `python run.py`.
5. Open `http://127.0.0.1:5000`.

## Config

All app settings live in `app/shared/config.py`.

Required production env vars:

- `APP_ENV`
- `SECRET_KEY`
- `DATABASE_URL`
- `PORT`
- `EMAIL_API_URL`
- `EMAIL_API_KEY`
- `EMAIL_SENDER_EMAIL`

Optional/runtime env vars:

- `CONTACT_PHONE`
- `ADMIN_ALERT_EMAIL`
- `EMAIL_SENDER_NAME`
- `EMAIL_TIMEOUT_SECONDS`
- `SCHEDULER_ENABLED`
- `SCHEDULER_POLL_SECONDS`
- `DEV_CLOCK_ENABLED`

Production rejects missing required values and rejects `DEV_CLOCK_ENABLED=true`.

## Migrations

- Dev app startup runs Alembic to `head`.
- Production must run migrations before the web process starts.
- Use `create_all()` only for dev/test helpers, never production schema management.

Railway pre-deploy:

```txt
alembic upgrade head
```

Railway web command:

```txt
gunicorn --log-config gunicorn_logging.conf run:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120
```

## Tasks

`tasks/` contains production cron/worker entrypoints. `scripts/` is local-only tooling.

Railway cron split, optimized for an EST agency operations day:

| Job | Command | Frequency | EST target | UTC cron |
| --- | --- | --- | --- | --- |
| Email delivery | `python -m tasks.process_email_alerts` | Every 10 minutes | All day | `*/10 * * * *` |
| Retrain forecasts | `python -m tasks.retrain_models` | Daily | `3:43am EST` | `43 8 * * *` |
| Reconcile balances | `python -m tasks.reconcile_inventory_balances` | Daily | `4:17am EST` | `17 9 * * *` |
| Generate safety alerts | `python -m tasks.generate_inventory_alerts` | Daily | `7:46am EST` | `46 12 * * *` |

Timing rules:

- `process_email_alerts` decides fresh every run: for each active recipient, it checks current alert eligibility (`alerts` + `alert_notifications`), their cadence, and quiet hours, then renders and sends immediately -- nothing is queued or claimed ahead of time.
- Instant-frequency recipients are checked every 10-minute tick. Hourly-frequency recipients are gated by "at least an hour since their last sent alert" (read from the `email_deliveries` audit log, not a stored timer). Daily-frequency alert emails and report emails both gate on the 9:00am agency-local window plus "not already sent today," using the same audit-log check.
- Per-recipient quiet hours are local clock preferences on `notification_recipients`; a recipient in quiet hours is skipped entirely for that run and re-checked on the next tick -- nothing is postponed or rescheduled.
- Alerts and reports always stay as separate outbound emails.
- Run retraining before balance reconciliation so forecast fields are fresh before the morning safety alert audit.
- Run the safety alert audit before the `9:00am` Eastern email window and off the 10-minute email grid so generated stale/rare events are ready for the next sender run.
- Keep scheduling and user-facing timestamps in each agency's local timezone, but store persisted timestamps in UTC or UTC-naive form in the database.

Railway cron expressions are configured in UTC here and mapped to EST targets. The every-10-minute email cron does not need seasonal adjustment.

The in-process scheduler is for dev/demo only and is disabled in production.

## Release Discipline

- Deploy one reviewed commit SHA at a time.
- Run migrations before serving new code.
- Keep local/staging/prod services as similar as practical, especially database behavior.
- Prefer fix-forward for low-risk production issues; use a hotfix branch only when urgent isolation is needed.
