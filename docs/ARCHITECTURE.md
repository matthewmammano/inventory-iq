# Architecture

Inventory IQ is a Flask app organized by domain. Runtime/setup details live in [DEPLOYMENT.md](DEPLOYMENT.md); data rules live in [DATA_MODEL.md](DATA_MODEL.md).

## App Entry

- `run.py`: WSGI entrypoint.
- `app/__init__.py`: app factory, extension setup, blueprint registration, health check, template filters.
- `app/errors.py`: shared Flask error handlers.

## Domains

- `app/auth/`: agencies, login/admin auth, reset PINs, devices, locations, storages, notification recipients.
- `app/inventory/`: guest/admin scan flows, item data, balances, action history, bulk actions, UPC review, reports.
- `app/alerts/`: alert generation, recipient filtering, email rendering/delivery.
- `app/prediction/`: usage trends, restock forecasting, model retraining.
- `app/shared/`: config, database/session setup, logging, scheduler, validators, email client, time utilities, security headers, rate limiting.

## Layers

Use this direction for new code:

```text
routes -> schemas/DTOs -> services -> query/repository-style modules -> shared infrastructure
```

- Routes parse request context, call services, flash/redirect/render, and stay thin.
- Schemas validate external or form-like shapes before service logic depends on them.
- Services own business decisions and transaction boundaries when practical.
- Query/repository-style modules keep SQL explicit and avoid leaking persistence details.
- Shared infrastructure owns cross-cutting concerns only.

## Frontend

- Templates live in `app/templates/`.
- CSS lives under `app/static/css/`; prefer component/page/core separation already present.
- JavaScript lives under `app/static/js/`; keep scripts page-specific unless behavior is truly shared.
- Shared form validation metadata lives in `app/shared/validation_types.py` and `app/shared/form_validation.py`.
- Pydantic field aliases and validators own the canonical rules; templates consume those rules through `validation_attrs(...)`.
- Frontend validation scripts may enforce the same rule earlier in the browser, but they should not become the primary source of truth.
- UI copy rules live in [CONVENTIONS.md](CONVENTIONS.md).

## Change Placement

- New route endpoint: route module plus service/schema if logic is non-trivial.
- New persistent field: model, Alembic migration, service validation, UI/report references.
- New scheduled work: task entrypoint under `tasks/` plus shared service function.
- New local-only tool: `scripts/`.
- New reusable agent workflow: `.agents/skills/<skill-name>/SKILL.md`.
