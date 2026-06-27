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
- `inventory_storage_balances`: derived current per-item/per-storage quantity for fast reads.
- `inventory_item_location_states`: derived per-item/per-location rollup, threshold, trend, forecast, and winning stock-alert state.
- `inventory_alert_events`: discrete non-stock alert facts such as unknown UPC, stale count, rare takeout, and scan activity.
- `notification_email_deliveries`: rendered notification emails with send status and retry diagnostics.
- `scheduler_runs`: idempotency markers for background job windows.
- `password_reset_pins`: hashed short-lived reset PIN records.

## Invariants

- `action_logs` is the inventory source of truth.
- `inventory_storage_balances` is derived state and must be updated in the same transaction as inventory writes.
- `inventory_item_location_states` is the current source of truth for stock, low-stock, and forecast email decisions.
- Stock/forecast alerts are current state, not alert event rows.
- `inventory_alert_events` stores discrete non-stock facts only.
- `notification_email_deliveries` stores rendered subject/body text as the sent-email audit record.
- Notification deliveries separate content (`notification_kind`: `ALERTS` or `RECAPS`) from timing (`delivery`: `IMMEDIATE` or `SCHEDULED`) and always use `send_at` as the due time.
- Time values are stored in the backend/database as UTC or UTC-naive timestamps for simplicity; convert to each agency's local timezone only when presenting, scheduling, or comparing against local business windows.
- Balance reconciliation may rebuild derived state from history when drift is detected.
- Inventory quantities are non-negative unless a future product decision explicitly changes that rule.
- Item soft delete uses `items.active`; do not hard-delete item history.
- Notification recipient state uses `agency_emails.active`; do not conflate it with `agencies.email`.
- Primary item UPCs use the private generated prefix enforced by `Items`.
- Secondary UPCs are real package aliases and must not use the private generated prefix.
- Unknown UPCs are unique per agency and move through review statuses.

## Relationships

- Agency owns locations, storages, items, logs, notification recipients, alert events, notification deliveries, state rows, and devices.
- Storage belongs to one location.
- Action logs reference an item and optional from/to storages.
- Storage balances are unique by agency, item, and storage.
- Item/location states are unique by agency, item, and top-level location.
- Notification email deliveries target one agency notification recipient and snapshot the destination email.

## Data Access

- Open sessions through `app/shared/database.py`.
- Prefer `managed_session()` when the function owns commit/rollback.
- Use existing query/service modules before adding new SQL in routes.
- Keep ORM objects inside service/query boundaries when possible.
- Add indexes with migrations for new list, filter, sort, or scheduled-job paths.
