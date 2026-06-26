# Data Model

Core persistence rules for Inventory IQ. Schema changes require Alembic migrations; deploy rules live in [DEPLOYMENT.md](DEPLOYMENT.md).

## Ownership

- `agencies`: tenant/admin account root.
- `agency_locations`: top-level physical locations per agency.
- `agency_storages`: storage units inside locations.
- `agency_devices`: browser/device default location records.
- `agency_emails`: notification/report recipients, separate from login identity.
- `items`: active/inactive inventory item master records.
- `item_secondary_upcs`: real package UPC aliases linked to items.
- `unknown_upc_scans`: unresolved UPCs awaiting admin review.
- `action_logs`: immutable inventory event history and source of truth.
- `inventory_balances`: derived current per-item/per-storage quantity for fast reads.
- `alert_records`: alert state and email decision history.
- `inventory_trends`: learned per-item/per-location usage trend.
- `scheduler_runs`: idempotency markers for background job windows.
- `password_reset_pins`: hashed short-lived reset PIN records.

## Invariants

- `action_logs` is the inventory source of truth.
- `inventory_balances` is derived state and must be updated in the same transaction as inventory writes.
- Balance reconciliation may rebuild derived state from history when drift is detected.
- Inventory quantities are non-negative unless a future product decision explicitly changes that rule.
- Item soft delete uses `items.active`; do not hard-delete item history.
- Notification recipient state uses `agency_emails.active`; do not conflate it with `agencies.email`.
- Primary item UPCs use the private generated prefix enforced by `Items`.
- Secondary UPCs are real package aliases and must not use the private generated prefix.
- Unknown UPCs are unique per agency and move through review statuses.

## Relationships

- Agency owns locations, storages, items, logs, notification recipients, alerts, trends, and devices.
- Storage belongs to one location.
- Action logs reference an item and optional from/to storages.
- Balances are unique by agency, item, and storage.
- Trends are unique by agency, item, and top-level location.
- Alert records target one agency notification recipient.

## Data Access

- Open sessions through `app/shared/database.py`.
- Prefer `managed_session()` when the function owns commit/rollback.
- Use existing query/service modules before adding new SQL in routes.
- Keep ORM objects inside service/query boundaries when possible.
- Add indexes with migrations for new list, filter, sort, or scheduled-job paths.
