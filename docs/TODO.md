# Inventory IQ V1 TODO

## Active Plan

- design a better favicon, logo, front page for NON USERS!!! like an about page with features and everything!

- for INVENTORY LEVELS and RESTOCK admin panel pages, can you add an option to EMAIL to any of those email accounts using HTML or EXCEL output. ALSO add this option for HISTORY just email as EXCEL. idk best plan to do all these at once please.

- Improve scheduled report email presentation: preview daily, weekly, and monthly report examples, then add graphs only if they keep the email simple and useful.

- certain pages REQUIRE keyboard use (as touchscreen / on-screen keyboard not best UI). investigate restricting some pages to keyboard-only use and make sure it is clear to users that they need a keyboard for that page. how to do? how to NOT ban users with keyboard AND touchscreen, only non-keyboard users.

- RAILWAY combine ENV vars and secrets into ONE place for all my COMPUTE (crons and web and DB) and make sure they are all in sync.

- why are there errors in the DB set for emails sending?

- on a scan of a new item, anything without a COUNT ever, then alert the user that ADMIN must provide a COUNT operation... but scan still went through fine.

- `class AlertSeverity(StrEnum)` is the BEST coding work of art I have ever done! Can you check EVERY OTHER class, datatype, and function in the codebase to see if they can be improved to be as elegant and maintainable as that one? (like using different Enum types, or dataclasses, or Pydantic models, computed fields, etc). Make sure you check THOROUGHLY with agents AND/OR regex searching marking each as possible refactoring candidate. Then make a list of all the candidates and we can review together with LOC saved estimates AND clear coding clarity benefits.

- research better AGENTS.md, combine with that, mainintable code and using PY latest features, never outdated

- under VIEW in admin, add section for viewing ALL sent notifications (regardless of who too, but filtered so no dups shown).

- @scheduler.py page has SO much ugly code
  - is there a way to have elegant code for cron setting logic maintainable? for dev?
  - maybe even managing Railway prod crons times too, but idk if possible
  - just abstracting the TIMES from the code would be helpful. having a config file or something instead... IDK LOOKUP BEST PRACTICES!

- Replace Deleted Local-Only Tasks Later
  - Rebuild backups for Railway/Postgres using managed backups or a Postgres-native backup/export process.
  - Rebuild DB-size reporting with Railway/Postgres metrics instead of local SQLite file size.
  - Rebuild action-log retention/archive with audited DB-native retention rules before deleting production rows.
  - Add session cleanup only if server-side sessions are introduced; current Flask sessions are cookie-based.
  - ALERTS cleanup for old sent/suppressed/cleared rows can be done with a scheduled background task or Railway cron job that runs a cleanup function on the database. Different cleanups PER each table (some never get cleanup).

- Tighten Production Safety
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
  - Production observability: searchable structured logs, request IDs, uptime/error alerts, and a per-agency support/debug workflow.
  - Alert-record retention cleanup for old sent, suppressed, and cleared alert rows.
  - PWA/kiosk mode with service worker, app manifest, offline queue/sync, and touch optimization.
  - CSP hardening: move inline scripts/styles to static assets, then remove `unsafe-inline`.
  - Build independent EMS squad reporting emails for daily, weekly, monthly, and yearly analytics.
  - Expiration tracking across inventory, alerts, reports, and UI.
  - Unit tracking (what does this mean?).
  - USER ID CARD SCANS for guest operations (for later accountability features).
  - Per-location item min/max/fallback usage overrides (bc BEACH has more calls then BORO for example).
  - Extra security hardening beyond core v1 needs.
  - Non-essential background task improvements.
