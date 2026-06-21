# Inventory IQ

Flask inventory app for EMS-style agencies with guest/admin scan flows, counts, restocks, alerts, and inventory forecasting.

## Stack

- Python 3.13
- Flask
- SQLAlchemy
- Alembic
- Pydantic Settings
- Loguru

## Local Setup

1. Copy `.env.example` to `.env`.
2. Set `SECRET_KEY`.
3. Run `alembic upgrade head`.
4. Start the app with `python run.py`.

Local default:

- `http://127.0.0.1:5000`

## Config

Important env vars:

- `APP_ENV`
- `SECRET_KEY`
- `DATABASE_URL`
- `DEBUG`
- `PORT`
- `EMAIL_API_URL`
- `EMAIL_API_KEY`
- `EMAIL_SENDER_EMAIL`
- `SCHEDULER_ENABLED`

Notes:

- Production must provide required env vars.
- `SCHEDULER_ENABLED` is for local/dev only.
- Production should use Railway cron/worker tasks, not the in-process scheduler.

## Production Web Command

```txt
alembic upgrade head && gunicorn --log-config gunicorn_logging.conf run:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120
```

## Tasks vs Scripts

- `tasks/` is for production cron/worker entrypoints.
- `scripts/` is for local testing, seeding, benchmarking, and one-off utilities.

## Railway Cron Split

- `4:10am` local: `python -m tasks.reconcile_inventory_balances`
- `7:50am` local: `python -m tasks.generate_inventory_alerts`
- `11:40am` local: `python -m tasks.retrain_models`
- hourly: `python -m tasks.process_email_alerts`

## Data Safety

- `action_logs` is the source of truth.
- `inventory_balances` is derived live state for fast reads.
- Inventory writes update history and live state in the same transaction.
- The daily balance audit logs mismatches and rebuilds full agency balance state from history when drift is found.
