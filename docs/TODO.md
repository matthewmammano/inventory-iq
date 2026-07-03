# TODO

- Expiration tracking across inventory, alerts, reports, and UI.

- design a better favicon, logo, front page for NON USERS!!! like an about page with features and everything!

- lets create a HELP sorta wiki page for admins with bunch of articles, fuzzy search, and TAGS per article. so reworded better, but things like "why am i not receiving emails", "why is this prediction wrong", "how do predictions work", "what is best pattern for COUNT / RESTOCK / TAKEOUT / etc", ... think of WAY more, write in a simple and predictable way each article maybe not even in html. maybe simple MD instead translated to HTML article. IDK just needs to be simple and easily writable!!!

- update locations trends, graphs (fix for understanding), validate, etc
  - change trend to be USAGE instead in DB, so >=0 instead of opposite, i like better

- Improve scheduled report email presentation: preview daily, weekly, and monthly report examples, then add graphs only if they keep the email simple and useful.

- certain pages REQUIRE keyboard use (as touchscreen / on-screen keyboard not best UI). investigate restricting some pages to keyboard-only use and make sure it is clear to users that they need a keyboard for that page. how to do? how to NOT ban users with keyboard AND touchscreen, only non-keyboard users.

- RAILWAY combine ENV vars and secrets into ONE place for all my COMPUTE (crons and web and DB) and make sure they are all in sync.

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

- Tighten Production Safety
  - Keep schema/bootstrap and local QA setup scripts explicit and documented.
  - Extra security hardening beyond core v1 needs.
  - CSP hardening: move inline scripts/styles to static assets, then remove `unsafe-inline`.

- Alert-record retention cleanup for old sent, suppressed, and cleared alert rows.

- USER ID CARD SCANS for guest operations (for later accountability features).

- Per-location item min/max/fallback usage overrides (bc BEACH has more calls then BORO for example).
