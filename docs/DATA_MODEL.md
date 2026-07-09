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
- `inventory_item_location_states`: derived per-item/per-location rollup, threshold, trend, and forecast *numbers* only -- no alert-lifecycle fields at all. Alert type and severity are computed live from these numbers wherever needed, never stored.
- `alerts`: every notifiable problem, stock and discrete alike (stockout/low-stock conditions as well as unknown UPC, stale count, rare takeout, scan activity, and expiration facts). Lifecycle is `status` `OPEN`/`CLOSED` plus a `closed_reason`; severity is derived from `alert_type` and never stored. Stock alerts carry an empty `detail` and render live from state; discrete alerts snapshot their `detail`.
- `alert_notifications`: append-only per-recipient ledger (`alert_id`, `notification_recipient_id`, `email_delivery_id`, `notified_at`). The absence of a row for a (recipient, alert) pair is what makes a recipient due.
- `email_deliveries`: write-once send audit (subject/preview only, no body). Never a queue or content cache.
- `scheduler_runs`: idempotency markers for background job windows.
- `password_reset_pins`: hashed short-lived reset PIN records.

## Invariants

- `action_logs` is the inventory source of truth.
- `inventory_storage_balances` is derived state and must be updated in the same transaction as inventory writes.
- `inventory_expiration_balances` is derived state for tracked expiration dates and must stay in the same transaction as inventory writes when expiration allocations are provided.
- Admin expiration corrections may replace `inventory_expiration_balances` directly when the stored item count is already correct; they must not create `action_logs`.
- `inventory_item_location_states` is the current source of truth for stock, low-stock, and forecast *numbers* (quantity, trend, forecast). It carries no alert-lifecycle fields; alert type/severity are recomputed on demand from these numbers, and alert lifecycle lives entirely in `alerts`.
- Alerts are never edited across a real change: any worsening, resolution, or recurrence closes the current row and opens a fresh one. A new row starts with no `alert_notifications`, so escalation (low stock -> stockout) and recurrence (restocked, then depleted again) are due immediately with no episode bookkeeping.
- Condition alerts (stock, stale, rare, expiration) are reconciled from current state: a stable dedupe key locates the open row, a changed `alert_type` closes it `SUPERSEDED` and opens a new one, and a vanished condition closes it `RESOLVED`. Stock uses a type-agnostic key (`STOCK:{item}:{location}`) so low-stock and stockout share one slot; expiration uses a type-agnostic key so expiring/expired share one slot.
- Occurrence alerts (scan activity, unknown UPC) are opened directly. Unknown UPC closes `RESOLVED` when the UPC is assigned or dismissed; scan-activity alerts close `SENT` by an age sweep once every recipient has had a chance to be notified.
- Per-alert-type resend behavior is one config value, `AlertDefinition.resend_after` (`ALERT_DEFINITIONS` in `app/alerts/constants.py`): `None` means notify once and never again (e.g. rare takeout, scan activity); a duration means re-notify while the alert stays open past that cooldown (e.g. 7 days for stock alerts and stale counts).
- Eligibility is one rule for every alert type: a recipient is due if they have no `alert_notifications` row for the alert, or if `resend_after` is set and that long has passed since their last notification for it.
- `email_deliveries` stores subject/preview only, never body content, and only records an actual send attempt; it is a lightweight audit record, never a queue or a content cache. `kind` is `ALERT` or `REPORT`.
- There is no claim/open-row concept for email: each cron run decides fresh, per recipient, whether any alert is due (via `alerts` + `alert_notifications`) and whether their cadence/quiet-hours window allows sending now, then sends and writes one audit row plus a ledger row per alert covered. This is what prevents duplicate alert emails; nothing is queued ahead of time.
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

- Agency owns locations, storages, items, logs, notification recipients, alerts, email deliveries, state rows, and devices.
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
