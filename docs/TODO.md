# My TODO

`P1` is the top open tier right now. `P3` whenever. Tags: `[OPEN]` `[PARTIAL]` `[PLAN]` needs a decision first, `[INVESTIGATE]` unknown scope.
Finished items move to **Done** as one line; items judged not worth doing are deleted, not kept.

---

## P1 - High value, needs a decision first

### P1.1 Public landing / about page [OPEN] semi-urgent
`/` is a bare login form. A prospect who looks you up after the meeting sees a password field. Wants features, screenshots, the value story. Pairs with P1.8.

### P1.2 22 help articles are unreachable by the people who need them [PLAN]
`app/admin_help/articles/` has 601 lines of help, served only by `admin_bp` at `/<agency>/admin-panel/help`. Zero help links on any guest template, so kiosk volunteers can never open it.
Decide: a guest-visible subset under a guest route, or a persistent Help affordance in `base.html`, or both.

### P1.3 Search shows a silent blank on zero matches [OPEN]
Search is already fuzzy (`fuzzy-search.js`); that is not the issue. `showResults` calls `list.replaceChildren()` and appends nothing when there are no matches, so the dropdown empties with no message. Add a non-clickable "No items match X" row plus a hint to scan the barcode. `inventory-search.js`.

### P1.4 Every error page shows a giant "!" [INVESTIGATE]
`error.html:17` renders `{{ error_code | default("!") }}` and `:28` gates on `error_help`; no Python file passes either. All five handlers (404, CSRF, 403, 429, 500) render the same blank page.
Pass a real code and a per-error help line from `_err()` in `errors.py`. 429 especially needs "you tried too many times, wait a minute."

### P1.5 "RESTOCK / COUNT / TAKE" are presented as if they were places [PLAN]
`scan_storages.html` lists them as `.radio-card` options beside real storage names under From/To, but they are actions (`VirtualLocation.RESTOCK=-1`, `COUNT=-2`, `TAKEOUT=-3`). "From: RESTOCK" is a mental-model problem for a volunteer.
Decide: split action from place into two steps, or keep one list with plain-English labels and a visual divider. No routing capability may be lost.

### P1.6 Admin panel is 10 undifferentiated tiles [PLAN]
`admin_panel.html`: equal weight, no grouping, and "Stock Actions" / "Restock" / "Bulk Action" read as the same thing. No Alerts or readiness tile, which is the best story in the product.
Decide: grouping (Daily work / Reports / Setup?), renames, and whether readiness gets a tile.

### P1.7 Missing empty states [PLAN]
Several bulk and print templates render a headers-only table instead of "nothing here yet." Need the list, then one shared component.

### P1.8 App name, favicon, and SEO [PLAN]
`site.webmanifest` says `"name": "Priority One Technologies"` while the app titles itself "Inventory IQ". Only 2 icons, no `purpose: maskable`, so the Android home-screen icon can render wrong.
Settle company-vs-product naming and apply it to `<title>`, the manifest, and emails. Same task: `<meta name="description">`, Open Graph + Twitter cards, per-page titles, `robots.txt`, `sitemap.xml`, JSON-LD `SoftwareApplication`. Only pays off once P1.1 exists.

### P1.9 `/health` reports healthy with a dead database [PLAN]
Returns only a status string and a timestamp, so Railway keeps routing to a broken app. Add a `SELECT 1` and return 503 on failure; confirm the poll interval first. The naive-timestamp half of this is already fixed.

### P1.10 Align login failure handling [OPEN] blocks a security fix
The wrong-password path does `flash()` + `redirect()` (302), discarding the typed email; the pydantic path re-renders via `_render_login(email, field_errors)` and keeps it. Align on re-rendering.
Not just cosmetic: because failure returns 302 it is indistinguishable from success by status code, which is why `failed_auth_only` could not be applied to this route (see Done).

### P1.11 JS failure leaves a silently dead screen [PLAN]
No `<noscript>` anywhere, and Settings / Bulk Save start `hidden` and are revealed only by JS. A script that fails to load or throws leaves a page that looks fine with no working buttons and no explanation.
Options: (1) `<noscript>` banner in `base.html`, cheapest, misses a script that throws; (2) invert the default so those controls render visible and JS hides them; (3) inline `<head>` script sets `data-js-ready`, CSS keys the reveal off it, plus a `window.onerror` bar. Leaning (2) for the buttons, (3)'s error bar later with P2.5.

### P1.12 "Total After Lead Time" can display negative [PLAN]
`bulk_service.py:188` does `round(current_quantity - daily_usage * lead_time_days)` with no floor, unlike `estimator.py:70` which clamps. Rendered raw at `admin_restock.html:74`.
Measured minimum across all 240 location states is -0.007, which rounds to 0, so today's data never shows it. Live scanning during the demo can surface it.
Decide first: is 0 the right floor, or is "you will be 12 short" useful information that needs different wording instead?

### P1.13 Logout is a plain GET [INVESTIGATE]
Any link, prefetch or embedded image can end a session. Convert to POST with the existing CSRF token, or document as accepted.

---

## P2 - Investigate, scope unknown

### P2.1 Restock Report print layout [INVESTIGATE]
`main.css:2033-2160` sets `table-layout: fixed; width: 100%` at 8pt with no `@page { size: landscape }`, against 16 columns and 120 rows. Long names share a cell with the trend button. Print-preview `admin.restock_print` for real before concluding; likely fix is landscape scoped to `.printing-report`, or fewer print columns. Check `admin_inventory_counts.html` for the same pattern.

### P2.2 Table-only scrolling, smaller pinned header [PARTIAL]
Scroll only the table so the Back bar, tab selectors and table header stay put.
Shipped: sticky `thead` on all panels (`2cf01a7`), `100svh` shell with `body{overflow:hidden}` + `main{overflow-y:auto}`. Open: shorten the header itself and confirm nothing clips on the kiosk.

### P2.3 Dead code sweep [INVESTIGATE]
~20 symbols across 13 files have no call sites. Confirmed dead: `list_agencies` (`auth/queries.py:29`), `parse_bool` (`shared/utils.py:14`), `build_item_search_payload` (`inventory/search_payload.py:34`). Get the full list from `vulture` (already a dev dep) plus `ruff --select F401,F841`, then remove per the CLAUDE.md procedure.

### P2.4 Zero-quantity expiration rows [INVESTIGATE]
11 rows in `inventory_expiration_balances` have `quantity = 0` (depleted lots never cleaned up). `audit_queries.py:144` filters them from alerts; not verified that every UI read path does. Check, then choose a cleanup task or a constraint.

### P2.5 Custom offline / 504 pages [INVESTIGATE]
Avoid Railway and Chrome defaults. Service worker intercepting fetch failures and status checks, serving a cached page. Overlaps P1.11 option 3.

### P2.6 Alerts table shows lifetime history, not current state [INVESTIGATE]
Only 3 rows / 12 units are expired today (Chest Seal 3, Epi Pen Child 7, Glucose 2) and 1 row / 3 units expires within 30 days, but the alerts table holds 105 `EXPIRED_STOCK` + 107 `EXPIRING_SOON` lifetime rows. A raw alerts view reads as a crisis. Find which surfaces show lifetime vs open counts and label them. For the demo, show the `admin_restock.html:82-83` columns.

### P2.7 Stale docs [INVESTIGATE]
`DEPLOYMENT.md:56` claims no third-party CDN remains; true for scripts, but fonts still load from Google via `main.css:6`. `INSTANCE_PATH` (`config.py:36`) is missing from its env var list.

### P2.8 Dev reruns migrations every app start [INVESTIGATE]
`_run_dev_migrations()` calls `command.upgrade(..., "head")` on every dev boot. Slow, and it can hide a broken migration until prod. Gate it or move it next to `scripts/bootstrap_schema.py`.

### P2.9 `admin_pending_tasks` swallows every exception [INVESTIGATE]
`except Exception: logger.debug(...)` in a context processor that runs on every page, so a broken query renders as "no pending tasks."

### P2.10 `image_src` hits the filesystem per image [INVESTIGATE]
`(Path(static_folder) / filename).exists()` on every image, every request. Cache or drop it.

### P2.11 Restock sort treats `None` like `0` [INVESTIGATE]
`bulk_service.py:100` sorts by `-(row.order_amount or 0)`, so "N/A" rows interleave with items needing nothing.

### P2.12 Demo data does not match its own plan [INVESTIGATE]
Intended: normal entries, standard miss-scan rates, then exactly 1-2 of each admin edge case injected at the very end (guest scan-out with no expiration date, scan of a nonexistent UPC, etc.).
Actual: `scripts/demo_data/` spreads error rates (`GUEST_FORGOT_RATE`, `GUEST_UNDER_RATE`, `RAPID_DOUBLE_SCAN_RATE`, `forgot_log_rate`, `wrong_pick_rate`) across the whole 4-year window. `UNKNOWN_UPC_SEED` is hardcoded to 5 (5 rows confirmed) but scheduled across the window too.
So no edge case exists as a recent, timestamped-last event. Also self-disclosed in its README: per-storage (Cage vs Shelf) usage is not modeled, one level deeper than the P3.5 location gap.

---

## P3 - Deferred

### P3.1 Test suite [OPEN] knowingly skipped
`tests/` holds one empty `__init__.py`. `pytest` is in no config file. Main risk multiplier for P3.2. Revisit right after the demo.

### P3.2 Unify CSS and HTML much further [OPEN]
Super reusable but still modular, big LOC cut. Add animations, shadows, real pressed-state feedback on anything tappable. Mostly pure CSS/HTML. Document the conventions in `main.css` so styles get reused, not re-invented. Dynamic for all devices.
The CSS is already well built (`:root` tokens, `@layer`, `clamp()` scale, `100svh` shell), so this is a ~110-130 line consolidation, not a rewrite.

### P3.3 More OO and modular [OPEN]
Line-restricted files, soft folder limits per module, more submodules, best-practice `__init__.py` exports, restricted function length and nesting depth.

### P3.4 IIQ logo plus agency logo, both top corners [OPEN]
Agency logos already work (`base.html:24-26` renders `current_user.image`); only the IIQ side and the two-corner layout are new.

### P3.5 Per-location min/max/fallback usage overrides [OPEN]
BEACH takes more calls than BORO, so reorder points differ per location. Never recommend transfers between locations; that is a user discrepancy.

### P3.6 Trend stored as usage instead of negative trend [PARTIAL]
Flip the column to `>= 0`.
Done: one shared `daily_usage_from_trend` helper replaced the duplicate conversion in `estimator.py` and `location_state_policy.py`.
Open: the column is still negative. Flipping touches exactly 11 files (`alert_service`, `location_state_policy`, `location_state_service`, `inventory/models`, `bulk_service`, `estimator`, `history_service`, `prediction/schema`, `prediction/segments`, `usage_model`, `item-trend-modal.js`).
Staying deferred is correct: every display path already flips the sign (`format_usage_rate` takes `abs()`, the chart never prints raw `trend_per_day`), so no buyer sees a backwards number.

### P3.7 Scheduled report emails [OPEN]
- Plan where expiration risk summaries go.
- Write an MD defining ALERTS vs auto REPORTS: clear split, no overlap. Pending tasks too.
- All periods: group at-risk status by location; add a reorder plan (item, location, suggested quantity, urgency reason, confidence note).
- Daily+: keep short (new unresolved, resolved); readiness snapshot with good/low/stockout/predicted counts and percentages, with a pie chart.
- Weekly+: takeout leaders by count, plus ML trends only if >60% of items are ML-trained.
- Monthly+: restock coverage (restocked vs taken out); replenishment health (under/over/balanced) as a pie chart; longer trend notes only when clearer than raw tables.
- Mandatory: trends that show the AI value, reviewed by me first.

### P3.8 Keyboard-only pages [OPEN]
Some pages need a physical keyboard. Restrict those and say so clearly, without banning users who have both a keyboard and a touchscreen.

### P3.9 Railway env consolidation [OPEN]
One place for env vars and secrets across crons, web and DB, kept in sync, probably `web-1`. Work out which services need which.

### P3.10 Audit every class for elegance [OPEN]
`AlertSeverity(StrEnum)` is the best design here. Check every other class, dataclass and function for the same treatment (enum types, dataclasses, Pydantic models, computed fields) with agents and regex, then review a candidate list with LOC-saved estimates.

### P3.11 Better CLAUDE.md [OPEN]
Research improvements, keep it on current Python features.

### P3.12 `scheduler.py` is ugly [OPEN]
Elegant maintainable cron logic for dev; possibly Railway prod times too; at minimum move the TIMES into config.

### P3.13 Replace deleted local-only tasks [OPEN]
- Railway/Postgres managed backups or a Postgres-native export.
- DB-size reporting from Railway/Postgres metrics, not SQLite file size.
- Action-log retention/archive with audited DB-native rules before deleting prod rows.
- Session cleanup only if server-side sessions are introduced; sessions are cookie-based today.
- Alerts cleanup for old sent/suppressed/cleared rows, a different rule per table (some never get cleaned).

### P3.14 User ID card scans for guest operations [OPEN]
For later accountability features.

---

## Done

### 2026-10-13 timezone pipeline

- [FIXED] **P0 every datetime sent to the browser was read as device-local.** The database stores naive UTC correctly, but `isoformat()` on a naive value produces `2026-09-12T01:34:34` with no offset, and JS `new Date()` treats an offsetless string as local time. A 01:34 UTC scan rendered as "Sep 12, 1:34 AM" on every device instead of Sep 11, 9:34 PM in New York, so trend-chart points, axis labels and tooltips were off by the UTC offset and scans near UTC midnight landed on the wrong day.
  New `utc_isoformat` in `timezone_utils.py` stamps the offset before anything crosses to the browser, applied at `history_service.py` (chart points) and `search_payload.py` (`last_accessed`). The chart already calls `toLocaleDateString`, so it now converts per device with no JS change.
  Three server-rendered tables were also printing raw UTC or re-implementing the conversion inline. New `local_datetime` Jinja filter (one `format_local_datetime` helper) replaced all of them: `admin_pending_upcs.html` was showing unconverted UTC in both date columns, while `macros.html` and `admin_data.html` each hand-rolled `get_*_local(...).strftime(...)`. `Item.get_last_accessed_local` became dead and was deleted. Display format is now one constant, `%Y-%m-%d %H:%M`; seconds were dropped as noise on a kiosk.
  `/health` returned `datetime.now()`, server-local with no offset; it returns aware UTC now.
  Decoupling bug found and fixed on the way: `_last_known_point` parsed its own serialized output back with `datetime.fromisoformat`, so stamping the string made it compare an aware datetime against a naive one and raise. `_operation_points` now reports its newest `(datetime, quantity)` directly and nothing re-parses the wire format.
  Verified: all 240 item/location charts produce byte-identical quantities, `trend_per_day`, confidence and count/operation points before and after, with the only difference being the trendline's `utc_now()` endpoint moving between runs; 512 of 512 chart points carry `+00:00` where none did before; and real Chromium at three device timezones renders Sep 11 9:34 PM (New York), Sep 11 6:34 PM (Los Angeles), Sep 12 1:34 AM (UTC) from the same stored instant. All 25 pre-commit hooks pass.

### 2026-10-12 demo fixes

- [FIXED] **P0 double-tap recorded the item twice.** `scan_item.html:73` Submit was `type="button"` outside `#hidden-form`, so the shared guard in `loading-overlay.js` found no submit button to disable. Now `type="submit" form="hidden-form"`, which is the native way to bind a control to a form it does not sit inside; `counter.js` lost its manual-submit block (-8 lines) and keeps only a submit-time value sync. `disableSubmitButtons` now walks `form.elements` instead of `querySelectorAll`, because only `form.elements` includes controls bound by the `form` attribute: that one change is what makes the existing guard cover this screen and any future one built the same way.
  Verified in Chromium against the real `counter.js` + `loading-overlay.js`: four rapid taps produce exactly one POST with `counter_value=7`, three Enter presses produce one POST, and reset posts 1.
- [FIXED] **P0 admin PIN limit locked out the presenter.** Flask-Limiter charged every POST to `/<agency>/admin`, success included, so 10 correct PINs in a minute or 50 in an hour locked you out with only an app restart to clear it; `guest.py:46-48` forces a fresh PIN on every guest route, so that is reachable in one demo. Now `deduct_when=failed_auth_only` charges the limit only when the response is not a 302, i.e. only when `check_pin` rejected. Brute force is made of wrong guesses, so protection is unchanged.
  Verified against the real app and dev data: 25 correct PINs in a row give 0 blocks (previously blocked at 11), and 11 wrong PINs still block at the 11th.
  Deliberately NOT applied to `auth.login`, `forgot_password` or `reset_password`: the login failure path returns 302 (see P1.10), so the flag would have read failures as successes and silently removed brute-force protection on the main form, and the two reset routes send email on success so every attempt must keep counting. Fix P1.10 first if you want it on login.
  No `DEMO_MODE` env flag: with failed-only counting there is no lockout left to rescue, and a flag whose only job is disabling a safety feature is one that gets left on in prod.
- [FIXED] **P0 "i" tooltips were unopenable on the kiosk.** The bubble was hover / `:focus-visible` only with zero JS. New `info-tip.js` (29 lines) toggles `.is-open` and `aria-expanded` on click for every device, closes on a tap elsewhere or Escape, and `stopPropagation` keeps the click from sorting the column header it sits in. Escape also blurs the button, without which `:focus-visible` holds the bubble on screen. On coarse pointers an `::before` gives a 44px tap target while the visible circle stays 29px, so no table header reflows.
  Verified in Chromium on touch and mouse profiles: open, close, switch, Escape, tap-away, no accidental sort, and a tap 20px off-centre registers on touch only.
- [FIXED] CI never ran: `astral-sh/setup-uv@v10` does not exist. That action publishes floating major tags only through `v7`; 10 exists solely as exact releases. Pinned to `v10.3.0`. `actions/checkout@v7` and `actions/cache@v6` do have floating tags and were fine.

### Earlier

- [FIXED] Sticky table headers generalized from `.tabbed-panel .panel thead th` to `.panel thead th`, so Pending UPCs and bulk-combined tables get them too.
- [FIXED] Search no longer autofocuses on coarse-pointer devices, so the on-screen keyboard stops covering kiosk results.
- [FIXED] Submit buttons disable synchronously in `loading-overlay.js` instead of waiting out the 180ms overlay delay.
- [FIXED] Two real fuzzy-search copies (`inventory-search.js`, `admin-help.js`) now share `fuzzy-search.js`; net -14 lines, identical results over 15 queries per call site with and without Fuse. `bulk-item-select.js` was left alone: it is exact-substring row-hiding and never loads Fuse. Done at two occurrences rather than three because both files declared a global `buildSearch` with conflicting tuning.
- [FIXED] All 25 `@dataclass` declarations across 15 files carry `slots=True`. `BalanceState` stays mutable: it is a genuine accumulator. Verified by exercising every object against the dev DB and rolling back; the email send path was left unexercised because running it sends real mail.
- [FIXED] Touch targets for small icon buttons moved onto the shared `.icon-button-sm` class, fixing the trend-chart buttons on Restock and Inventory Counts and dropping a duplicate rule in `admin-data.css`.
- [DONE] Idle auto-return: one hour untouched shows a 10-second countdown, then steps one level toward the front door (admin sub-page to Admin Home, Admin Home or guest sub-page to Guest Home). Guest Home renders no timer, so it never loops. Any input resets it. `IDLE_TIMEOUT` / `IDLE_WARNING_SECONDS` in `shared/constants.py`; reuses the existing modal and overlay markup, so zero new CSS. 41 lines, 20 browser checks.
- [PARTIAL] `main.css` 2901 to 2716 lines: four blocks moved to `pages/print-label-preview.css`, `pages/bulk-action-grid.css`, `components/bulk-item-select.css`, `components/scan-route-strip.css`, each linked only from its own templates, deletions only, `@layer base` membership kept.
  Skipped as too order-coupled: the expiration-entry block, and `.upc-*` / `.search` / `.required-cell` / `.suggested-row` / `.invalid-cell` / `.history-pagination`. Revisit with `@layer` applied more deliberately.

### Closed, no action

- Google Fonts over the internet via `main.css:6` (typography degrades on bad venue wifi): accepted.
- 77 of 120 items give guests single-step `-`/`+` only; 43 have `guest_quick_adjust`: accepted.
- Login tells strangers an email exists ("Use the emailed PIN to set your password" instead of a generic error): accepted, the audience is a few known agencies.
- Home search caps at 7 visible results with no browse fallback: every item is also reachable by barcode.
- Per-row confirm on cancelling a pending UPC scan: a confirm slows the common case for no protection, and bulk edits already go through a Review Changes modal. Deletes are soft (`active = False`).
- Merging `counter.js` and `expiration-allocation.js` steppers: different rules (custom step and lower bound vs fixed ±1 with a cross-row cap, date clearing at zero, and an exact-total submit gate). Merging would couple a scan quantity to a multi-lot invariant.
- `inputmode="numeric"` missing on the UPC field: false alarm, `validation_attrs("upc12")` already sets it plus `pattern` and `maxlength`.
- `bindUpcScanner` only on `index.html`: correct, admin Stock Actions reuses that template.
- 10 files over the ~200-line soft cap: split each when it is edited for another reason.
- Prediction math: bounded usage (`MIN/MAX_EFFECTIVE_DAILY_USAGE` 0.0 to 99.0), `days_to_threshold` returns 0.0 at threshold and `None` when flat or rising, `reorder_date` clamps at 0, `_build_segment` requires >=1 day between counts. Checked against real magnitudes (-0.0017 to -0.07/day). No nonsensical forecast is reachable.
- Trend data: all 240 `inventory_item_location_states` rows have a non-null `trend_per_day`, `segment_count` 7-26. Every item renders a real trendline; a brand-new item correctly shows "No history yet."
- `batch_email.html` inline styles: correct for email clients, the `font-size: 0` plus fixed-width `inline-block` grid is standard.
- Vercel/Next.js migration: the valuable part of that advice (high-contrast borders, 48px+ targets, text labels, persistent status feedback, global scanner capture, offline-tolerant UI) is framework-agnostic and mostly already built. A rewrite means leaving Railway (stateful Postgres and crons do not map to serverless), rebuilding every route in React, and redoing the demo CSS. Revisit only for a concrete need like IndexedDB offline sync.

---

## Operations

- [ACTION REQUIRED] Before the next prod deploy, run `alembic stamp --purge 20261008_0001` on prod, or `alembic upgrade head` fails with "Can't locate revision identified by '20260723_0027'". Rewrites a version number only; no data touched.
