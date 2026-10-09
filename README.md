# Inventory IQ

Inventory IQ is a field-friendly inventory system for EMS-style agencies that need fast scans at the shelf and clear oversight in the admin panel. Crews can count, restock, take out, or transfer supplies by location and storage area, while admins can review history, manage items and barcodes, send reports, track notification recipients, and see restock forecasts built from recent usage. The app is different from a plain spreadsheet because every scan writes auditable history, updates live balances, supports agency/location-specific workflows, and turns inventory activity into alerts, reports, and operational decisions.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and nothing else; it installs the right Python itself.

```bash
uv sync
cp .env.example .env   # then set SECRET_KEY
uv run alembic upgrade head
uv run python run.py
```

Dependencies live in `pyproject.toml` and are pinned in `uv.lock`. Do not use `pip`; see [Deployment](docs/DEPLOYMENT.md#dependencies).

## Docs

- [Architecture](docs/ARCHITECTURE.md)
- [Data model](docs/DATA_MODEL.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Admin workflows](docs/ADMIN_WORKFLOWS.md)
- [Repo conventions](docs/CONVENTIONS.md)
- [Observability](docs/OBSERVABILITY.md)
- [Product TODO](docs/TODO.md)
- [Agent guidance](CLAUDE.md)
- [Code quality tooling](docs/CODE_QUALITY.md)
