# My TODO

## MVP Priority — Fix These First (In Order)

Must follow AGENTS.md exactly: modular, DRY, compact, clean, KISS, production-grade. Go one item at a time; each gets its own `type(scope): description` commit.

1. DONE - **Count/Restock suggested-fillout highlighting** — On Count/Restock (bulk or single), highlight rows that are stale/suggested for fillout. Leaving a suggested Restock quantity blank must still be allowed.
2. DONE - **Expiration-aware restock math** — Exclude EXPIRED quantity from `current_total` before computing suggested reorder amount in `BulkService._analyze_item`/`_calculate_order_amount` (`app/prediction/bulk_service.py`), since expired stock isn't real usable inventory. Leave "expiring soon" stock out of the math (still usable) — keep it informational-only on the restock page as it is today.
3. DONE - **Expiration alert latency fix** — Remove the `expires_on is None` gate in `app/inventory/mutation_service.py` and `app/inventory/bulk_edit_service.py` so `sync_expiration_alerts` always runs after any expiration allocation save, not only "Other/Not Listed" entries. Today a restock/count against a known, specific expiring-soon date waits up to ~24h for the daily cron instead of alerting immediately. De-duplicate the repeated conditional into one shared helper.
4. DONE - **Expiration entry: restrict RESTOCK to new dates only** — RESTOCK's interstitial (`app/templates/expiration_entry.html`, `app/inventory/expiration_ui_service.py`) should only allow entering brand-new expiration dates for the delivered delta, not reallocate into pre-existing known lots. COUNT (full reconciliation across all known lots + new dates + Other) and TAKEOUT/TRANSFER (select from existing lots + Other only) already behave correctly — no change needed there. While in this page, also apply: compact grouping across locations/storages, and keep expiration date inputs and quantity steppers aligned in compact two-column rows.
5. **Dedupe `location_state_service.py` single-item vs. bulk queries** — `_load_location_rollup`/`_location_rollups_by_key` and `_location_state_settings`/`_load_location_state_rebuild_rows` run the same SQL shape twice (single-row vs. grouped-by-key). Consolidate each pair into one shared query so a future field change can't drift between the two paths.
6. **Delete confirmed-dead CSS + fix broken variable** — Delete the CSS files under `app/static/css/core/`, `layouts/`, `components/`, `pages/` confirmed to have zero references anywhere in the codebase (`variables.css`, `reset.css`, `admin-layout.css`, `scan-storages.css`, `scanning.css`, `bulk-quantity.css`, `buttons.css`, `flash-messages.css`, `inventory-thresholds.css`, `navigation.css`, `tables.css`, `tags.css`, `auth.css`, `errors.css`, `index.css` — ~1,099 lines total). Fix `--color-surface-highlight` referenced in `app/static/css/components/item-trend-modal.css:82`, which is never defined anywhere — the trend-scale button's active-state highlight silently renders nothing.

---

- make url agency id instead of name!

- remove the (est.) from USAGE bc it already has it on COL HEADER!

- Wanna unify the CSS / HTML items way way more for all pages. Make it SUPER reusable, but also modular with different ways in CSS and stuff to MAKE A HUGE CUT IN LINES OF CODE! I also want to add some animations, shadows, etc. Things pressable interactions should have, etc. PERFECTION! do research on BEST UI practices, how to do this, using MOSTLY PURE CSS/HTML (unless there is something else that could allow me to go EVEN FEWER LOC)! Think hard, suggest MORE styling things to add, make sure CSS / HTML documented in the main.css or whatever so ALWAYS things are reused when possible instead of new similar styling created! And DYNAMIC EVERYTHING for all devices!!!

- Make all code SUPER OO design pattern, line number restricted, files in folder SOFT restricted (for modules). Attempt to create MORE modules AND submodules. Attempt to make `__init__.py` files to be best practice (I think I should be included smth like exports I forget). Makes editing easier if less LOC per file. Restrict function LOC too AND depth! JUST GENERAL CLEANUP ALL!

- Have IIQ logo AND Agency logo (both top corners... maybe)

- Relook at the HELP docs, re-create all using a NEW agent call better. Make one for spam / important marking help on email accounts!

- is there a way to make CUSTOM bad connection / 504 / etc pages WITHOUT railway / chrome defaults? save pages in cache for this?
  - Register a service worker on your frontend that intercepts fetch failures (also status checks) and serves a cached custom page instead of letting the browser/Railway show the default

- design a better favicon, logo, front page for NON USERS!!! like an about page with features and everything!

- update locations trends, graphs (fix for understanding), validate, etc
  - change trend to be USAGE instead in DB, so >=0 instead of opposite, i like better

- Improve scheduled report email presentation:
  - PLAN AND THINK: how to add expiration risk summaries and stuff ALL HERE and where to add!
  - THINK and PLANOUT in an MD what is ALERTs jobs VS auto REPORTs jobs! differences! no overlap! how to make great!
  - PENDING TASKS THINK AND PLAN TOO!
  - All periods:
    - Group at-risk status by location when agencies have multiple locations.
    - Add reorder plan: item, location, suggested quantity, urgency reason, confidence/estimate note.
  - Daily AND longer:
    - Keep short: new unresolved risks and resolved risks
    - Add readiness snapshot: good/low/stockout/predicted low/predicted stockout counts and percentages WITH A PIE CHART!!!
  - Weekly AND longer:
    - Add takeout leaders: highest-use items during the period by COUNTS. also trends by ML learning shown (IF at least >60% of items are ML and not the PRIOR ones ONLY).
  - Monthly AND longer:
    - Add restock coverage: restocked quantity vs takeout quantity.
    - Add replenishment health: under-restocked, over-restocked, or balanced in PIE CHART!.
    - Add longer trend notes only when they are clearer than raw alert tables.
  - MANDATORY:
    - Trends to promote the AI use, reviewed by ME beforehand, to describe how much benefit I am providing, etc.

- certain pages REQUIRE keyboard use (as touchscreen / on-screen keyboard not best UI). investigate restricting some pages to keyboard-only use and make sure it is clear to users that they need a keyboard for that page. how to do? how to NOT ban users with keyboard AND touchscreen, only non-keyboard users.

- RAILWAY combine ENV vars and secrets into ONE place for all my COMPUTE (crons and web and DB) and make sure they are all in sync. maybe web-1. figure out which services even need which ENVs.

- `class AlertSeverity(StrEnum)` is the BEST coding work of art I have ever done! Can you check EVERY OTHER class, datatype, and function in the codebase to see if they can be improved to be as elegant and maintainable as that one? (like using different Enum types, or dataclasses, or Pydantic models, computed fields, etc). Make sure you check THOROUGHLY with agents AND/OR regex searching marking each as possible refactoring candidate. Then make a list of all the candidates and we can review together with LOC saved estimates AND clear coding clarity benefits.

- research better AGENTS.md, combine with that, mainintable code and using PY latest features, never outdated

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

- Alert-record retention cleanup for old sent, suppressed, and cleared alert rows.

- USER ID CARD SCANS for guest operations (for later accountability features).

- Per-location item min/max/fallback usage overrides (bc BEACH has more calls then BORO for example). different reorder, nums needed, etc for ALL locations. WE NEVER rec transfers between locations, that is USER DISCREPENCY!
