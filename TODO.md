# Inventory IQ V1 TODO

## GENERAL NOTES

- Remember to Loguru logs so I can easily debug user issues in production.

## Active Plan

- Tighten Production Safety
  - Improve structured logging context at service and boundary layers.
  - Keep schema/bootstrap and local QA setup scripts explicit and documented.

## Future Plan

- Admin DB CLI
  - Build one central interactive CLI for validated DB edits across supported tables.
  - Include table/row selection, typed validation, confirmation prompts, audit logging, and transaction rollback.

- Item Management
  - Add proper item create/edit/delete flow later.
  - Use `Items.active` for soft delete/disable, not hard delete.
  - Define required schemas, validation, and admin UI before reintroducing item management.
  - Do not ship partial item-management behavior in v1.
  - SAME FOR REALLY MOST THINGS IN DB. Colors, etc.... maybe BESIDES locations and storages bc that's how I will CHARGE THEM!!!

- Later Features
  - PWA/kiosk mode with service worker, app manifest, offline queue/sync, and touch optimization.
  - CSP hardening: move inline scripts/styles to static assets, then remove `unsafe-inline`.
  - Build independent EMS squad reporting emails for daily, weekly, monthly, and yearly analytics.
  - Expiration tracking across inventory, alerts, reports, and UI.
  - Unit tracking.
  - USER ID CARD SCANS for guest operations (for later accountability features).
  - Per-location item min/max/fallback usage overrides.
  - Prediction cache/persistence tuning if DB trend rows are not enough.
  - Broader template cleanup/reorganization.
  - Extra security hardening beyond core v1 needs.
  - Non-essential background task improvements.
