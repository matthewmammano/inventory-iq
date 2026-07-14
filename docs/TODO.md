# My TODO

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
