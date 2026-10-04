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

## MADE BY AI (unreviewed - judge each one yourself before acting)

These came out of a 3-agent codebase audit (backend, frontend/UX, security/data) plus a Vercel/Next.js question, not from me directly. Keeping them separate so I know which items I haven't personally vetted yet.

- [FIXED] Pending/Ignored barcode tables (`admin_pending_upcs.html`) didn't get a sticky table header on scroll like other admin tables. Fixed by broadening the sticky-thead CSS rule from `.tabbed-panel .panel thead th` to `.panel thead th` in `main.css` (also now applies to `admin_bulk_actions.html`'s bulk-combined-table, which is a bonus not a regression - confirm it still looks right there).
- Search field (`index.html`) auto-focuses and pops the on-screen keyboard on kiosk load, covering results underneath it. Should skip autofocus on touch/coarse-pointer devices.
- Confirm `bindUpcScanner` (global barcode-scan capture in `upc-scanner.js`) is actually wired on every page where staff would scan, not just the home search page.
- Home search (`inventory-search.js`) caps visible results at 7 items with no browse/category fallback, so anything past that is only reachable by typing - this is the "keyboard-only trap" issue, now located concretely.
- Double-submit risk: the loading-overlay click-guard has a ~180ms gap before it disables input, so a fast double-tap on Save/Delete/Submit can double-fire. Button should disable synchronously on first click instead.
- "Cancel" on a pending UPC scan deletes it with a single tap, no confirm modal, unlike every other delete in the app. Should route through the existing delete-confirm pattern.
- Three separate reimplementations of "fuzzy search w/ substring fallback" exist (`inventory-search.js`, `admin-help.js`, `bulk-item-select.js`) - candidate to extract into one shared helper.
- Two separate reimplementations of the +/- quantity stepper exist (`counter.js`, `expiration-allocation.js`) - same idea, candidate for one shared `stepper.js`.
- ~25 files use plain `@dataclass` where repo convention is `slots=True` (one, `balance_service.py`'s `BalanceState`, isn't even frozen) - mechanical cleanup pass, low risk.
- Alert-record and action-log retention cleanup confirmed still unbuilt (matches what's already above in this file - not a new finding, just re-confirmed true).
- Icon-only edit buttons (`.icon-button-sm`, 28px) are missing from the touch-target media query that already bumps other small controls to 44px+ on coarse pointers.
- UPC-add input field (`admin_pending_upcs.html`) lacks `inputmode="numeric"` for a digit-only on-screen keyboard when typed manually.
- 10 files exceed the ~200-line soft cap (`scan_flow.py`, `alert_service.py`, `models.py`, `expiration_ui_service.py`, etc.) - not broken, just split-candidates next time each is touched.
- `main.css` is still ~2900 lines as one file; component-file extraction pattern exists (`admin-data.css`) but hasn't been applied yet to expiration/scan/bulk-action CSS blocks.
- **Vercel/Next.js migration - how hard would it be, and is it worth it?** Asked an AI about "best practices for a non-AI-SaaS, tablet/USB-scanner inventory app" and got generic Next.js + Vercel + Tailwind + Radix + TanStack Table advice. Current read: the actual valuable part of that answer (high-contrast borders, 48px+ touch targets, text labels over icons, big persistent status feedback, global USB-scanner keystroke capture, offline-tolerant optimistic UI) is framework-agnostic and mostly already built here in Flask/Jinja/vanilla JS (`upc-scanner.js` already does the global-scanner-capture pattern). A full Next.js rewrite would mean: re-platforming off Railway (stateful Postgres + cron jobs don't map cleanly to Vercel's serverless model), rebuilding every template/route/service in React, and re-doing all the demo-ready CSS work from scratch - all for a UI philosophy that doesn't actually require a new stack. Revisit this seriously only if a concrete need shows up (e.g. needing a native-app-like offline mode via IndexedDB sync, or a component ecosystem Flask genuinely can't match) - not as a default next move.
