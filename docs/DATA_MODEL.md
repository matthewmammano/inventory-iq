# Data Model

Core persistence rules for Inventory IQ. Schema changes require Alembic migrations; deploy rules live in [DEPLOYMENT.md](DEPLOYMENT.md).

## Ownership

- `agencies`: tenant/admin account root, including hashed login password and hashed admin PIN.
- `agency_locations`: top-level physical locations per agency.
- `agency_storages`: storage units inside locations.
- `agency_devices`: browser/device default location records.
- `notification_recipients`: notification/report recipients, separate from login identity.
- `notification_preferences`: one typed notification/report toggle per recipient and preference key.
- `items`: active/inactive inventory item master records.
- `item_secondary_upcs`: real package UPC aliases linked to items.
- `unknown_upc_scans`: unresolved UPCs awaiting admin review.
- `action_logs`: immutable inventory event history and source of truth.
- `action_log_expiration_lines`: expiration-date allocations captured for one inventory event.
- `inventory_storage_balances`: derived current per-item/per-storage quantity for fast reads.
- `inventory_expiration_balances`: derived current per-item/per-storage/per-expiration-date quantity for expiration-aware scans and alerts.
- `inventory_item_location_states`: derived per-item/per-location rollup, threshold, trend, forecast, and winning stock-alert state.
- `inventory_alert_events`: discrete non-stock alert facts such as unknown UPC, stale count, rare takeout, and scan activity.
- `notification_email_deliveries`: rendered notification emails with send status and retry diagnostics.
- `scheduler_runs`: idempotency markers for background job windows.
- `password_reset_pins`: hashed short-lived reset PIN records.

## Invariants

- `action_logs` is the inventory source of truth.
- `inventory_storage_balances` is derived state and must be updated in the same transaction as inventory writes.
- `inventory_expiration_balances` is derived state for tracked expiration dates and must stay in the same transaction as inventory writes when expiration allocations are provided.
- Admin expiration corrections may replace `inventory_expiration_balances` directly when the stored item count is already correct; they must not create `action_logs`.
- `inventory_item_location_states` is the current source of truth for stock, low-stock, and forecast email decisions.
- Stock/forecast alerts are current state, not alert event rows.
- `inventory_alert_events` stores discrete non-stock facts only.
- `notification_email_deliveries` stores rendered subject/body text as the sent-email audit record.
- Notification deliveries store final rendered outbound emails. `delivery_kind` is either `ALERT` or `REPORT`; `send_at` is the due time; `delivery_key` is the logical dedupe key per recipient so multiple emails may share a due timestamp.
- Time values are stored in the backend/database as UTC or UTC-naive timestamps for simplicity; convert to each agency's local timezone only when presenting, scheduling, or comparing against local business windows.
- Balance reconciliation may rebuild derived state from history when drift is detected.
- Inventory quantities are non-negative unless a future product decision explicitly changes that rule.
- Item soft delete uses `items.active`; do not hard-delete item history.
- Notification recipient state uses `notification_recipients.active`; do not conflate it with `agencies.email`.
- Notification recipient preferences live in `notification_preferences`; do not add new Boolean preference columns to `notification_recipients`.
- Notification recipient alert frequency and quiet hours live on `notification_recipients`; delivery timestamps remain UTC/UTC-naive and are grouped or shifted at planning/send time.
- Agency expiration notice days are a default; item-level `expiration_notice_days_override` only exists for item-specific exceptions.
- Primary item UPCs use the private generated prefix enforced by `Item`.
- Secondary UPCs are real package aliases and must not use the private generated prefix.
- Unknown UPCs are unique per agency and move through review statuses.

## Relationships

- Agency owns locations, storages, items, logs, notification recipients, alert events, notification deliveries, state rows, and devices.
- Storage belongs to one location.
- Action logs reference an item and optional from/to storages.
- Storage balances are unique by agency, item, and storage.
- Expiration balances are unique by agency, item, storage, and expiration date.
- Item/location states are unique by agency, item, and top-level location.
- Notification email deliveries target one agency notification recipient and snapshot the destination email.

## Data Access

- Open sessions through `app/shared/database.py`.
- Prefer `managed_session()` when the function owns commit/rollback.
- Use existing query/service modules before adding new SQL in routes.
- Keep ORM objects inside service/query boundaries when possible.
- Add indexes with migrations for new list, filter, sort, or scheduled-job paths.
