# Inventory IQ V1 TODO

## Active Plan

1. migrate both db files in instance/ to latest
2. now can you plz think hard, generate ideas, and create an entire smoke test db table based off a COPY PASTED version temp of current db (instance\inventory_iq.db) and make sure to repoint it to the new one. use DEV tools to change time / date, log events, act like a real user, create ROBUST test cases, ALL inside the tmp/ folder under a new subfolder to test this COMPHRENSIVELY and THOROUGHLY!! to perfection! think thru it all! test ALL edge cases! investigate code FIRST to gen the right ideas for edge case testing. basically all of the alert / email logic needs to be RE-TESTED. do not send real emails tho to the user! JUST look at instance/alerts OR a version of that in tmp/ instead to read what WOULD'VE been sent. also do freqent DB table checks to make sure all appearing as it SHOULD BE!!!!!!!!

- Review Changes screen NEEDS to be scrollable. also needs to be written as CONCISE / COMPACT as possible. instead of "Yes to No" maybe use ICONS (or just checkboxes that are UNEDITABLE maybe PREFERRED) that I approve AND "→". ALSO maybe I'll change.

- remove timezone COMPLETELY from ADMIN UI SETTINGS... just editable by me in DB TABLE manually!

- per each specific agency_notification_email enable a QUIET time hours range to suppress sending emails during that time. (like 10pm-7am or whatever). this is a per-agency per-email alerted setting, not global.

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
