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

- `process_email_alerts` prepares final rendered email rows and sends rows where `send_at <= now`.
- Email delivery rows use `send_at` as their due time; `delivery_kind` and `delivery_key` keep logical alert and report emails distinct even when both are due together.
- Scheduled alert emails use the next top-of-hour `send_at`.
- Daily alert emails and report emails target the 9:00am agency-local window, and alerts/reports always stay as separate outbound emails.
- Per-recipient quiet hours are local clock preferences on `notification_recipients`; email delivery timestamps are stored in UTC/UTC-naive form and postponed outside quiet windows before sending.
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
