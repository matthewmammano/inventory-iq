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

Railway cron split, optimized for an Eastern-time agency operations day:

| Job | Command | Frequency | Eastern target | UTC cron during EDT (UTC-4) | UTC cron during EST (UTC-5) |
| --- | --- | --- | --- | --- | --- |
| Email delivery | `python -m tasks.process_email_alerts` | Every 10 minutes | All day | `*/10 * * * *` | `*/10 * * * *` |
| Retrain forecasts | `python -m tasks.retrain_models` | Daily | `3:40am` | `40 7 * * *` | `40 8 * * *` |
| Reconcile balances | `python -m tasks.reconcile_inventory_balances` | Daily | `4:10am` | `10 8 * * *` | `10 9 * * *` |
| Generate safety alerts | `python -m tasks.generate_inventory_alerts` | Daily | `7:50am` | `50 11 * * *` | `50 12 * * *` |

Timing rules:

- `process_email_alerts` prepares email rows and sends rows where `send_at <= now`.
- Immediate alert emails use `send_at = now`, so they send on the next 10-minute cron run.
- Hourly digest emails use the next top-of-hour `send_at`.
- Daily digest emails use `8:00am` in the agency timezone and are picked up by the next 10-minute email cron.
- Run retraining before balance reconciliation so forecast fields are fresh before the morning safety alert audit.
- Run the safety alert audit shortly before `8:00am` Eastern so daily notification preparation sees current state.

Railway cron expressions are typically configured in UTC. If the scheduler cannot use an America/New_York timezone setting, update the three daily UTC cron expressions when Eastern time switches between EDT and EST. The every-10-minute email cron does not need seasonal adjustment.

The in-process scheduler is for dev/demo only and is disabled in production.

## Release Discipline

- Deploy one reviewed commit SHA at a time.
- Run migrations before serving new code.
- Keep local/staging/prod services as similar as practical, especially database behavior.
- Prefer fix-forward for low-risk production issues; use a hotfix branch only when urgent isolation is needed.
