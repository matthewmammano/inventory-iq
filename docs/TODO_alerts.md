# Alerts And Notification Delivery TODO

Implementation plan for replacing the current recipient-specific `alert_records` flow with a simpler state-driven alert and email system.

## Decisions Locked

- [x] Use current inventory state for stock, low-stock, and forecast math instead of generating stock alert rows.
- [x] Merge trend fields into the item/location state table; do not keep a separate long-term trend table.
- [x] Store discrete non-stock alert facts separately from email deliveries.
- [x] Do not add `notification_email_alert_events` or `notification_email_stock_states`.
- [x] Treat rendered email content as the sent-email audit record.
- [x] Store `alert_event_ids_json` on delivery rows only as internal status plumbing, not as an audit/link table.
- [x] Remove any `MANUAL_TEST` alert enum idea; test with real alert types in non-production data.

## Final Table Responsibilities

- [ ] `inventory_storage_balances`: current quantity per agency, item, and storage.
- [ ] `inventory_item_location_states`: current per-agency, per-item, per-top-level-location rollup, thresholds, trend, forecast, and winning stock-alert state.
- [ ] `inventory_alert_events`: discrete non-stock alert facts that may be queued into an email.
- [ ] `notification_email_deliveries`: one rendered email to one recipient, with delivery status and retry details.

## Enum Plan

- [ ] Use all-uppercase enum values in the database.
- [ ] Define `AlertType` for stock state and discrete events:
  - `STOCKOUT`
  - `STOCKOUT_FORECAST`
  - `LOW_STOCK`
  - `LOW_STOCK_FORECAST`
  - `STALE_COUNT`
  - `RARE_TAKEOUT`
  - `UNKNOWN_UPC`
  - `COUNT_ACTION`
  - `RESTOCK_ACTION`
  - `TAKEOUT_ACTION`
  - `TRANSFER_ACTION`
- [ ] Define `AlertSeverity`:
  - `INFO`
  - `NOTICE`
  - `WARNING`
  - `HIGH`
  - `CRITICAL`
- [ ] Define `InventoryAlertEventStatus`:
  - `PENDING`: generated and eligible to be included in an email.
  - `QUEUED`: included in a pending email delivery; prevents duplicate queueing.
  - `NOTIFIED`: at least one generated delivery for this event was sent successfully.
  - `CANCELLED`: intentionally not sent because it was invalidated before queue/send.
  - `ERROR`: event could not be queued/rendered because of an application failure.
- [ ] Define `NotificationEmailStatus`:
  - `PENDING`: rendered and waiting for `send_at`.
  - `SENT`: email provider accepted the message.
  - `ERROR`: send failed; retry later.
  - `CANCELLED`: recipient disabled, preferences changed, or developer override before send.
- [ ] Define `NotificationKind` by content:
  - `ALERTS`: alert-driven email content.
  - `RECAPS`: periodic recap/report email content.
- [ ] Define `NotificationDelivery` by timing:
  - `IMMEDIATE`: due on the next sender run.
  - `SCHEDULED`: due at the stored `send_at`.

## Schema Plan

- [ ] Rename or replace `inventory_balances` conceptually with `inventory_storage_balances`.
  - Keep one row per agency, item, and storage.
  - Keep `quantity`, `last_counted_at`, `last_activity_at`, and `last_takeout_at`.
  - Preserve existing balance reconciliation behavior.
- [ ] Add `inventory_item_location_states`.
  - Keys: `agency_id`, `item_id`, `agency_location_id`.
  - Current values: `total_quantity`, `last_counted_at`, `last_activity_at`, `last_takeout_at`.
  - Threshold snapshots: `min_quantity_snapshot`, `lead_time_days_snapshot`, `restock_delivery_days_snapshot`.
  - Trend fields: `trend_per_day`, `confidence_percent`, `segment_count`, `data_signature`, `trained_at`.
  - Forecast fields: `days_until_low`, `days_until_stockout`.
  - Current stock state: `stock_status`, `forecast_status`, `effective_alert_type`, `effective_alert_rank`, `effective_severity`.
  - Trace fields: `state_version_at`, `updated_at`.
  - Unique constraint: agency, item, agency location.
- [ ] Add `inventory_alert_events`.
  - Store only discrete non-stock events: unknown UPC, rare takeout, stale count if kept event-like, and scan/action notification events.
  - Fields: `agency_id`, `alert_type`, `severity`, `status`, `source_type`, `source_id`, `payload_json`, `event_at`, `created_at`, `queued_at`, `notified_at`, `cancelled_at`, `last_error_type`, `last_error_message`, `last_error_at`.
  - Do not store stockout, low-stock, or forecast rows here.
- [ ] Add `notification_email_deliveries`.
  - One row per recipient email.
  - Fields: `agency_id`, `agency_email_id`, `recipient_email_snapshot`, `notification_kind`, `delivery`, `status`, `send_at`, `next_attempt_at`, `dedupe_key`, `alert_event_ids_json`, `subject`, `preview_text`, `body_html`, `body_text`, `attempt_count`, `last_error_type`, `last_error_message`, `last_error_at`, `created_at`, `sent_at`.
  - Constraint: `next_attempt_at` must be null or greater than/equal to `send_at`.
  - Effective retry time is `max(send_at, next_attempt_at or send_at)`.

## State Propagation Rules

- [ ] Recompute `inventory_item_location_states` whenever inventory quantity changes.
  - Count, restock, takeout, transfer.
  - Only recompute affected agency/item/location rows.
- [ ] Recompute affected state rows when item settings change.
  - `min_quantity`
  - `restock_delivery_days`
  - item active/inactive state
- [ ] Recompute affected state rows when agency settings change.
  - `lead_time_days`
  - count/stale-count thresholds
  - rare-takeout thresholds
- [ ] Recompute trend and forecast fields after model retraining.
  - Write trend fields directly to `inventory_item_location_states`.
  - Recalculate `days_until_low`, `days_until_stockout`, and effective stock alert fields.
- [ ] Keep `inventory_storage_balances` and `inventory_item_location_states` updated in the same transaction when practical.
- [ ] Keep a safety rebuild/audit job to repair derived state from `action_logs` and storage balances.

## Stock Alert Logic

- [ ] Use current item/location state as the source of truth for stock alert decisions.
- [ ] Apply stock priority in this order:
  - `STOCKOUT`
  - `STOCKOUT_FORECAST`
  - `LOW_STOCK`
  - `LOW_STOCK_FORECAST`
- [ ] Store the winning stock alert on `inventory_item_location_states`.
- [ ] Forecast tiers:
  - `CRITICAL`: stockout/low threshold within 1 day.
  - `HIGH`: within 3 days.
  - `WARNING`: within 7 days.
  - `NOTICE`: within configured lead time.
- [ ] Do not renotify for small forecast movement within the same tier.
- [ ] Do not renotify when a forecast becomes less urgent unless a new count/action creates a new current state worth sending.
- [ ] If pending email content would be stale, build from the latest state before rendering/sending.

## Discrete Alert Event Logic

- [ ] Generate `inventory_alert_events` for non-stock facts only.
- [ ] Use `source_type` and `source_id` for traceability when a real source row exists.
  - `ACTION_LOG` -> `action_logs.id`
  - `UNKNOWN_UPC_SCAN` -> `unknown_upc_scans.id`
  - no fake source IDs
- [ ] Store event-specific details in `payload_json`.
- [ ] Do not store rendered email text in `inventory_alert_events`.
- [ ] Mark events `QUEUED` when included in a rendered pending email.
- [ ] Mark events `NOTIFIED` after at least one related generated delivery sends successfully.
- [ ] Mark events `ERROR` only for queue/render failures, not provider send failures.
- [ ] Keep provider send failures on `notification_email_deliveries`.

## Email Generation Logic

- [ ] Email builder reads two sources:
  - current stock rows from `inventory_item_location_states`
  - pending discrete events from `inventory_alert_events`
- [ ] Apply recipient preferences and location filters before rendering.
- [ ] Render email content once and store it on `notification_email_deliveries`.
- [ ] Use `recipient_email_snapshot` so sent history keeps the actual destination even if the recipient record changes later.
- [ ] Keep content type separate from delivery timing.
  - Alert emails: `notification_kind=ALERTS`.
  - Recap/report emails: `notification_kind=RECAPS`.
  - Next-cron alerts: `delivery=IMMEDIATE`, `send_at=now`.
  - Scheduled alerts: `delivery=SCHEDULED`, `send_at` rounded to the next hour.
  - Periodic recaps: `delivery=SCHEDULED`, prepared during the configured morning window.
- [ ] When a periodic recap includes alerts, render alert sections first and recap sections second.
- [ ] Make combined recap email header/body text explicitly say it includes both current alerts and periodic recap content.
- [x] Do not create link tables; the stored email body is the audit record.

## Email Sending Logic

- [ ] Sender runs every 10 minutes.
- [ ] Send only deliveries with due effective send time.
- [ ] Try each due delivery once per cron run.
- [ ] On success, mark delivery `SENT` and set `sent_at`.
- [ ] On failure, mark delivery `ERROR`, increment `attempt_count`, set `last_error_type`, `last_error_message`, `last_error_at`, and future `next_attempt_at`.
- [ ] Send developer urgent email for major send/render/system errors using a dedicated admin-alert mechanism, not through `notification_email_deliveries`.
- [ ] Retry errored delivery rows on a later cron when `next_attempt_at` is due.

## Cron Plan

- [ ] On inventory actions: update storage balance, item/location state, and affected discrete events immediately.
- [ ] On unknown UPC scan: create/update pending discrete event immediately.
- [ ] On item/settings edits: recompute affected item/location states immediately.
- [ ] On model retraining: update trend fields and forecast fields in `inventory_item_location_states`.
- [ ] Every 10 minutes: send due `notification_email_deliveries`.
- [ ] Run daily operational jobs off the 10-minute email grid.
  - Retraining: 3:43am Eastern.
  - Reconciliation: 4:17am Eastern.
  - Safety alert audit: 7:46am Eastern.
- [ ] Hourly or daily: safety audit/rebuild derived state only; do not make this the primary alert source.

## Migration Order

- [ ] Add new enums and models.
- [ ] Add Alembic migration for new tables/constraints/indexes.
- [ ] Backfill `inventory_item_location_states` from current balances, locations, items, and trends.
- [ ] Port stock/forecast calculation to write item/location state.
- [ ] Port discrete alert generation to `inventory_alert_events`.
- [ ] Port email rendering to `notification_email_deliveries`.
- [ ] Port email sender to delivery rows.
- [ ] Cut over scheduled tasks.
- [ ] Remove old `alert_records` logic after verified replacement.
- [ ] Update docs: `DATA_MODEL.md`, `DEPLOYMENT.md`, and `TODO.md`.

## Code Quality Rules For Implementation

- [ ] Keep routes thin; alert work belongs in services/query modules.
- [ ] Keep derived-state writes explicit and transactionally predictable.
- [ ] Use typed enums/constants instead of string literals.
- [ ] Use small policy functions for timing, severity, and stock priority.
- [ ] Log successful operations at `INFO`, branch decisions at `DEBUG`, suspicious recoverable issues at `WARNING`, send/render failures at `ERROR` or `EXCEPTION`.
- [ ] Never log raw email bodies, secrets, or sensitive recipient payloads.
- [ ] Add focused tests for state propagation, forecast priority, send timing, retry behavior, and event status transitions.
