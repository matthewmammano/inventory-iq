# My TODO

- make it so that on scrolling in screens with tables... and stuff where pages are typically very large in scrolling... maybe just portions scroll instead... so admin-panel/data page... maybe JUST the table scrolls... that way we ALWAYS see the "Back to Admin" on top, the {"Items", "Locations", ...} selectors, and the table header {"Name", "Primary UPC", etc}.

- make header smaller height AND fixed top EVEN on scrolls! make sure nothing else affected / covered by this change!

- Wanna unify the CSS / HTML items way way more for all pages. Make it SUPER reusable, but also modular with different ways in CSS and stuff to MAKE A HUGE CUT IN LINES OF CODE! I also want to add some animations, shadows, etc. Things pressable interactions should have, etc. PERFECTION! do research on BEST UI practices, how to do this, using MOSTLY PURE CSS/HTML (unless there is something else that could allow me to go EVEN FEWER LOC)! Think hard, suggest MORE styling things to add, make sure CSS / HTML documented in the main.css or whatever so ALWAYS things are reused when possible instead of new similar styling created! And DYNAMIC EVERYTHING for all devices!!!

- Make all code SUPER OO design pattern, line number restricted, files in folder SOFT restricted (for modules). Attempt to create MORE modules AND submodules. Attempt to make `__init__.py` files to be best practice (I think I should be included smth like exports I forget). Makes editing easier if less LOC per file. Restrict function LOC too AND depth! JUST GENERAL CLEANUP ALL!

- Have IIQ logo AND Agency logo (both top corners... maybe)

- is there a way to make CUSTOM bad connection / 504 / etc pages WITHOUT railway / chrome defaults? save pages in cache for this?
  - Register a service worker on your frontend that intercepts fetch failures (also status checks) and serves a cached custom page instead of letting the browser/Railway show the default

- design a better favicon, logo, front page for NON USERS!!! like an about page with features and everything!

- update locations trends, graphs (fix for understanding), validate, etc
  - change trend to be USAGE instead in DB, so >=0 instead of opposite, i like better
    - [PARTIAL] Removed the duplicated negative-to-positive conversion code that existed in both `estimator.py` and `location_state_policy.py` (now one shared `daily_usage_from_trend` helper, no behavior change). The DB column itself is still stored negative - flipping that touches 11 files (training, alerts, bulk actions, history, the chart JS, the column) so it's deliberately left for its own reviewed task, not bundled into a quick fix.

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

## REVIEWED AND CLOSED

These came out of a 3-agent codebase audit (backend, frontend/UX, security/data) plus a Vercel/Next.js question, not from me directly. Every one has now been judged, so nothing here needs another decision: the first group is built, the second group was looked at and deliberately left alone, and the third is the only thing still outstanding (it already appears in my own list above too).

### Done

- [FIXED] Pending/Ignored barcode tables (`admin_pending_upcs.html`) didn't get a sticky table header on scroll like other admin tables. Fixed by broadening the sticky-thead CSS rule from `.tabbed-panel .panel thead th` to `.panel thead th` in `main.css` (also now applies to `admin_bulk_actions.html`'s bulk-combined-table, which is a bonus not a regression - confirm it still looks right there).
- [FIXED] Search field (`index.html`) auto-focused and popped the on-screen keyboard on kiosk load, covering results underneath it. Now skips autofocus on touch/coarse-pointer devices (`(pointer: coarse)` check in `inventory-search.js`), mouse/kiosk-with-keyboard devices still auto-focus.
- [FIXED] Double-submit risk: the loading-overlay click-guard had a ~180ms gap before it disabled input, so a fast double-tap on Save/Delete/Submit could double-fire. Submit buttons now disable synchronously (`loading-overlay.js`) instead of waiting for the visual overlay delay.
- [FIXED, with a correction] The audit said THREE fuzzy-search reimplementations. Really only two: `bulk-item-select.js` is a plain exact-substring row-hide with no fuzzy matching and its pages never load `fuse.min.js`, so folding it in would have changed its behavior - left alone. The two real ones (`inventory-search.js`, `admin-help.js`) now share `app/static/js/fuzzy-search.js` (`window.buildFuzzySearch`). Note this was done at two occurrences, not three, so it bends the Rule of Three: the tiebreaker was that both files declared a global named `buildSearch` with conflicting tuning, which silently breaks whichever loads second if a page ever loads both. Net -14 lines. Verified old-vs-new over 15 queries per call site, with and without Fuse loaded: identical results and scores.
- [FIXED] All 25 plain `@dataclass` declarations across 15 files now carry `slots=True` (24 were already frozen). The audit's claim that `balance_service.py`'s `BalanceState` should also be frozen is a FALSE POSITIVE: it is a genuine accumulator, mutated in `_computed_balance_state`, so it stays mutable. Since the repo has no real test suite, this was verified by exercising every one of these objects against the dev database (120 items, 240 audit rows, 240 alert evaluations, trend training, forecasting, bulk-location loaders), then rolling back. The alert-email send path is the one path left unexercised, because running it sends real mail.
- [FIXED] Icon-only edit buttons were missing from the touch-target media query. Half-stale as written: `.row-action-button` on the Data page already got 44px; the real gap was the trend-chart buttons on Restock and Inventory Counts. Fixed on the shared `.icon-button-sm` class instead of per-button, so every small icon button gets it, and the duplicate width/height in `admin-data.css` was dropped. Verified on the 1280x800 kiosk and laptop screenshot profiles.
- [DONE] Idle auto-return (my idea, not the audit's). One hour untouched shows an "Are you still here?" box counting down from 10, then moves you one step toward the front door: an admin sub-page goes to Admin Home, and Admin Home or any guest sub-page goes to Guest Home. Guest Home renders no timer at all, so it never loops. Any tap, mouse move, scroll, or key press resets the clock. `IDLE_TIMEOUT` and `IDLE_WARNING_SECONDS` live in `app/shared/constants.py`; `base.html` picks the destination with one Jinja line and hands it to `idle-timeout.js` as data attributes. Reuses the existing `.modal-backdrop`/`.modal` markup and the loading overlay, so zero new CSS. It never defers to unsaved edits, by choice. 41 lines of JS, smoke tested in a real browser (20 checks: every reset input, the countdown, all three destinations, and no loop on Guest Home).
- [PARTIALLY FIXED] `main.css` 2901 -> 2716 lines. Four page/component blocks pulled out into the existing `components/` + `pages/` convention: `pages/print-label-preview.css`, `pages/bulk-action-grid.css`, `components/bulk-item-select.css`, `components/scan-route-strip.css`, each linked only from the templates that use them (verified 1:1, no orphans). Pure relocation - the `main.css` diff is deletions only, zero insertions - and each file keeps its `@layer base` membership so load position cannot change precedence.
  - Deliberately SKIPPED as too order-coupled to move safely: the expiration-entry block (two-directional order dependencies on `.quiet-button`, `.field-hint`, `button:disabled`), and `.upc-*` / `.search` / `.required-cell` / `.suggested-row` / `.invalid-cell` / `.history-pagination` (multi-page, and `.invalid-cell` is applied by shared `form-validation.js`). Worth revisiting only with `@layer` applied more deliberately, which is its own separate task.

### Decided against or already fine - no action needed

- [CONFIRMED, NOT A GAP] `bindUpcScanner` (global barcode-scan capture) only needs to live on `index.html` - checked `scan_flow.py`/`admin_scan.py`: item lookup happens once on the home/search page, and admin's "Stock Actions" scan flow reuses that same `index.html` template, so it's already covered everywhere staff would scan.
- [WON'T DO, DECIDED] Home search (`inventory-search.js`) caps visible results at 7 items with no browse/category fallback. Not a trap in practice: every item is reachable by barcode scan as well as by typing, so the cap only limits the typed path, which already narrows as you type.
- [WON'T DO, DECIDED] The audit wanted a confirm modal on single-tap "Cancel" for a pending UPC scan. Decided against that: a per-row confirm makes the common case slower for no real protection, since cancelling one pending scan is cheap to redo. The bulk gate this was going to be traded for already exists: `admin_bulk_actions.html` opens a "Review Changes" modal listing every edit before submit, and warns on leaving with unsaved edits. Settings uses the same component, deletes use the "Yes, Delete" panel, and report emails go through a recipient picker. Deletes are soft (`active = False`), so nothing here destroys data.
- [WON'T DO, DELIBERATELY] The two +/- steppers (`counter.js`, `expiration-allocation.js`) must NOT be merged. They encode different rules: counter.js has a custom step size, a reset-to-1 sentinel, and only a lower bound; expiration-allocation.js is fixed +/-1 with a ceiling that depends on what the other rows hold (a cross-row cap), clears the row's date field at zero, and gates submit on an exact total. Merging would couple a single scan quantity to a multi-lot allocation invariant - the false coupling CLAUDE.md's DRY rule warns about.
- [FALSE ALARM, NO FIX NEEDED] The audit claimed the UPC-add field (`admin_pending_upcs.html`) lacks `inputmode="numeric"`. It does not. The field uses the shared `validation_attrs("upc12")` spec system, and the `UPC12` rule in `validation_types.py` already sets `inputmode="numeric"` plus `pattern="[0-9]{12}"` and `maxlength=12`. Verified by rendering the attributes directly. Every UPC field in the app gets a number pad already. The audit agent read the template without following the macro.
- [ACCEPTED FOR NOW] 10 files exceed the ~200-line soft cap (`scan_flow.py`, `alert_service.py`, `models.py`, `expiration_ui_service.py`, etc.). Nothing is broken; split each one only when it is being edited for another reason.
- **Vercel/Next.js migration - how hard would it be, and is it worth it?** Asked an AI about "best practices for a non-AI-SaaS, tablet/USB-scanner inventory app" and got generic Next.js + Vercel + Tailwind + Radix + TanStack Table advice. Current read: the actual valuable part of that answer (high-contrast borders, 48px+ touch targets, text labels over icons, big persistent status feedback, global USB-scanner keystroke capture, offline-tolerant optimistic UI) is framework-agnostic and mostly already built here in Flask/Jinja/vanilla JS (`upc-scanner.js` already does the global-scanner-capture pattern). A full Next.js rewrite would mean: re-platforming off Railway (stateful Postgres + cron jobs don't map cleanly to Vercel's serverless model), rebuilding every template/route/service in React, and re-doing all the demo-ready CSS work from scratch - all for a UI philosophy that doesn't actually require a new stack. Revisit this seriously only if a concrete need shows up (e.g. needing a native-app-like offline mode via IndexedDB sync, or a component ecosystem Flask genuinely can't match) - not as a default next move.

### Still open from the audit

- Alert-record and action-log retention cleanup confirmed still unbuilt (matches what's already above in this file - not a new finding, just re-confirmed true).
