# v2 Rewrite - Active Plan

Branch `v2`. `demo-v1` tag is the Tuesday demo and must keep working untouched.

## Locked Decisions

| Area | Decision |
|---|---|
| Frontend | Vite + React + TypeScript |
| UI library | Fragments (`@usefragments/ui`), Base UI primitives, MIT |
| Data fetching | TanStack Query |
| Routing | React Router v8 |
| Backend API | Flask + APIFlask 3.1.2, Pydantic schemas |
| TS codegen | Hey API, generates types and TanStack hooks from OpenAPI |
| Dark mode | None. One look ships. |
| URLs | Change only when meaningful. Page never reloads. Flow steps get no URL. |
| Marketing site | Separate repo, GitHub Pages |
| Search rows | Name and tags only. No on-hand count. |
| First slice | Guest scan |
| Rejected | Next.js, HTMX, Reflex, NiceGUI, FastHTML, FastAPI |

Rejection basis: 2,480 lines of existing client JS proves this is a genuinely interactive app, so HTMX round trips fight the scanner and the expiration allocation. Reflex would cost us Fragments.

## Departures From Fragments Defaults

All three set once in the theme layer, never per page.

1. Type scale shifted up. Their scale is desktop SaaS density. Kiosk body lands near 18px, touch targets 46px minimum.
2. Brand stays v1 amber. Their default indigo `#3d5ae8` is banned by global CLAUDE.md.
3. Palette. `web/src/theme/palette.css` names every color once as `--iq-*`, then hands those
   values to Fragments' own `--fui-*` tokens. One file recolors every screen. Our CSS never
   spells a Fragments token name twice, so a rename upstream is a one-block fix.

## Approved Scan Screen Look

Locked from artifact review: amber v1 palette, hairline borders, soft corners, v1 type size, name-only rows, bare X to clear the field, icon-only admin link using lucide `key-round`.

Second pass, after the first build read as all white:
- Amber page ground, filled amber header bar over a dark amber hairline, white rows on the wash.
- The agency logo is a bare image with slightly rounded corners, where the mock had an "IQ" square.
- A chevron closes every result row.
- Match count stays in the field's `count` slot, not a separate line under it.
- Rejected from the mock: the "Scanner ready" status dot, and the highlight on the top match.
- Row names stay in the body face, bold, not the heading face.

Third pass, from screenshots:
- `radius` dropped from 8 to 4 in `tokens.ts`. Fragments derives surface radius as `radius * 2.4`,
  so 8 made every row, tile and chip a pill.
- Fragments' focus ring defaults to indigo `#3d5ae8`. It is dark amber now, at zero offset on the
  search field, so focus reads as one thicker edge instead of a second outline around the border.
- The page header is our own `<header>`, not Fragments' `Header`. Header.Brand caps its type at
  15px, which left the screen title smaller than the row names.

Fourth pass, from screenshots:
- The search field and results sit in a centered measure, `clamp(600px, 74vw, 1080px)`, not the full
  screen width.
- Row hover is `#ffeab0`, far enough off the `#fff8df` ground to read as a change on a kiosk.
- The field border is the softer ink, and the focus ring is 2px, so the resting field is thinner.

## Environment Rules

Python, already in place:
- `uv` only. Never system Python, never `pip`, never `python3 -m`.
- Deps in `pyproject.toml`, pinned in `uv.lock`, both committed.
- Everything runs through `uv run`.

JavaScript, to add:
- `npm` only. Never a global install.
- Deps in `web/package.json`, pinned in `web/package-lock.json`, both committed.
- `web/node_modules/` gitignored.
- Everything runs through `npm run <script>`.

Prerequisite on this machine: `sudo pacman -Syu` then `sudo pacman -S nodejs npm`.

## Target Layout

```
app/
  api/v1/            APIFlask JSON endpoints
  <domain>/
    schema.py        request models
    response.py      response models (new, separate per CLAUDE.md)
    service.py       business decisions
    queries.py       persistence
web/
  src/
    theme/           design tokens, the 2 departures above
    components/      shared wrappers
    routes/          one folder per screen
    api/             generated, never hand edited
docs/v2/
```

## Shared Component Layer

Built once, used everywhere. Changing a token or a wrapper changes every screen.

Where a visual value lives, in order: a color goes in `theme/palette.css`, a size or spacing in
`theme/kiosk.css`, anything about the page frame in `components/Page.css`. A screen's own CSS file
never spells a raw color or a raw pixel size.

| Component | Role |
|---|---|
| `Page` | header, title, back/home rule |
| `ScanField` | Fragments Input plus scanner focus handling |
| `ItemRow` | the approved result row |
| `DataTable` | Fragments table plus sort and paginate |
| `FormField` | label, control, error text |
| `Modal` | Fragments Dialog, our sizing |
| `Toast` | ours end to end, our flash categories |
| `EmptyState` | no results, no permission, offline |

## Speed

Two rules, both set once.

1. Every query is fresh for `QUERY_STALE_MS` (`web/src/constants.ts`), applied as the `QueryClient`
   default in `main.tsx`. Walking back a step re-reads the cache instead of the network.
2. A step prefetches the next step's list as soon as it knows which one that is. `ScanFlow` fetches
   storages (or locations, when the device has none) while the person is still searching for an item.

Not prefetched: `scan-context` and `expirations`, because both key off a quantity or a route the
person has not picked yet, so a prefetch would fire a request per tap and still miss.

## Phases

A page's old template, CSS and JS are deleted only after its React replacement works.

### Phase 0 - Foundation
No visible change. v1 keeps serving every page.

- [x] Install nodejs and npm (node 26.12.1, npm 12.2.1)
- [x] `uv add apiflask` (3.1.2)
- [x] `web/` scaffold: Vite 8, React 19, TypeScript 6, React Router 8, TanStack Query 5
- [x] Install Fragments, wrap app in `Theme`, `TooltipProvider`, `ToastProvider`
- [x] Hey API wired to the generated OpenAPI spec
- [x] Flask serves the built bundle at `/v2`. One URL, one deploy, no CORS.
- [x] Drift checks in pre-commit: `openapi-drift`, `web-typecheck`, `web-lint`
- [x] `web/node_modules/` and `app/static/v2/` in `.gitignore`

### Phase 1 - Safety Net
18,496 lines of Python across 139 files had zero tests. Nothing proved behavior except clicking.

- [x] pytest with a throwaway database: a fresh SQLite file per test, no network, no real email path
- [x] 58 tests covering scan save (11), expiration allocation (12), alert firing (11), auth and PIN gating (24)
- [x] `pytest` runs as a pre-commit gate; `pyright` and `mypy` now cover `tests/` too
- [x] Every test drives the real services, so the rules are pinned where Phase 2 will move them

Run them with `uv run pytest tests/ -q`.

Rules the tests uncovered and now pin down:
- RESTOCK is refused until every storage in the location was counted inside 90 days.
- A tracked item's COUNT must allocate every unit across expiration dates.
- Stock counted before expiration tracking was switched on needs a follow-up count.

Coupling the tests exposed, both cleaned up in Phase 2:
- `get_device_location_id` read the device cookie off the Flask request. It takes the token as an argument now, and `request_device_location_id` is the only thing that touches the cookie. `ScanActor` carries the location, so no service reaches for a request.
- Email validation did a live DNS deliverability lookup on every save. Format only now.

### Phase 2 - Backend
54 routes become JSON endpoints. Business rules move and get cleaned, never reinvented. Models and migrations are not touched.

- [x] Response models per boundary, separate from request models, each with its own `of(...)` builder:
      `app/auth/response.py`, `app/inventory/response.py`, `admin_items_response.py`, `overview_response.py`,
      `reports_response.py`, `bulk_response.py`, `upc_review_response.py`, `app/admin_help/response.py`
- [x] Guest scan endpoints, all five live and covered by 23 tests:
      `GET /api/v1/agencies/{id}/locations`
      `GET .../storages?location_id=`
      `GET .../items`
      `GET .../items/lookup?upc=`
      `POST .../scans`
- [x] Account session and admin PIN endpoints, all six live and covered by 25 tests:
      `POST /api/v1/session`
      `DELETE /api/v1/session`
      `GET /api/v1/agencies/{id}/admin-session`
      `POST .../admin-session`
      `DELETE .../admin-session`
      `POST .../admin-session/temporary-pin`
- [x] Remaining admin endpoints by domain, 34 live behind the admin PIN unlock and covered by 162 tests:
      items, tags and notification recipients, 12 endpoints, 28 tests
      `GET|POST .../admin/items`, `PATCH|DELETE .../admin/items/{id}`, same shape for `/admin/tags` and `/admin/notification-recipients`
      overview, 5 endpoints, 28 tests
      `GET .../admin/dashboard`, `GET|PUT .../admin/settings`, `GET|POST .../admin/pending-expirations`
      reports, 7 endpoints, 26 tests
      `GET .../reports/stock-levels`, `/restock`, `/history`, a `POST .../email` beside each, and `GET .../items/{id}/locations/{id}/trend`
      bulk edit, 2 endpoints, 24 tests
      `GET|POST .../locations/{id}/bulk-edit`
      unknown barcodes, 6 endpoints, 28 tests
      `GET|POST .../admin/unknown-barcodes`, `DELETE .../{id}`, `POST .../{id}/item`, `/ignore`, `/pending`
      help articles, 2 endpoints, 9 tests
      `GET .../admin/help/articles`, `GET .../admin/help/articles/{slug}`
- [x] Thin handlers, decisions in services, persistence in queries. Every v1 route file the move touched came
      out net shorter, and `tests/test_v1_pages_render.py` holds all 19 v1 admin pages at 200 so nothing was lost.

Every agency-scoped route is gated once in `app/api/agency_access.py`: signed in, own agency, account active.
Admin routes carry a second gate, `app/api/admin_access.py`. `@admin_only` only marks the view; the check runs in a
blueprint `before_request`, so a locked browser is refused before APIFlask parses its body and is never told what
else was wrong with the request. A view wrapper ran after validation and answered 422 instead of 403.

Picked up while building these:
- A list response is declared as a Pydantic `RootModel`, not `list[Model]`. APIFlask accepts both, only one type-checks.
- `build_item_search_payload` needs tags attached first, so `_attach_tags` is now the public `attach_item_tags`.
- Hey API's prettier step was removed; prettier was never installed, so the client had never generated.
- The admin unlock rule lived inline in `app/shared/utils.py`, half of it duplicated as hand-rolled
  `session.pop("admin", ...)` calls in two route files. It is one module now, `app/auth/admin_session.py`,
  returning why a request was refused; v1 turns that into a flash and a redirect, the API into JSON.
  Nothing outside that module names the session keys.
- Same for the credential check: `app/auth/sign_in_service.py` owns it, and the v1 login route uses it too,
  so an unknown email, an inactive account and a wrong password stay one indistinguishable refusal in both.
- `failed_auth_only` counts a rate-limit attempt by "did not redirect", which is backwards for JSON, where
  success is a 201. `refused_json_auth_only` is the 4xx-and-up twin, so a correct sign-in is never charged.
- An account with no password set has no redirect to send in JSON, so it answers 409 and the screen sends
  the person to the reset flow itself.
- A PIN that is not 4 digits is refused at the schema, not by hashing it. It can never match, and that keeps
  the hash comparison off a path that was never going to succeed.
- The v1 PIN page also set the device cookie, because it carried a location picker. v2 has its own
  device-location endpoint, so the PIN endpoint stays about the PIN.

### Phase 3 - Guest Scan Screen
**Approval gate.** Artifact first, then build.

- [x] Theme token file
- [x] The 4 shared components this screen needs: `Page`, `ScanField`, `ItemRow`, `Note`.
      `DataTable`, `FormField`, `Modal` and `Toast` get built with the first screen that needs them.
- [x] Scan screen live at `/v2`, running against the real endpoints
- [x] Verified on kiosk 1280x800, laptop 1440x900, TV 1920x1080, iPhone 393x852
- [ ] Barcode scanner tested with real hardware. Fast keystroke dumps into a React input are the known risk.

Picked up while building it:
- Nothing told the frontend which agency it is. `GET /api/v1/me` does now, and it is the one API route
  outside the agency-scoped gate, so it checks the session itself.
- The agency logo URL resolution moved out of the Jinja filter into `app/shared/image_paths.py`,
  so the template and the API answer with the same URL.
- Fragments `Badge` only takes a fixed set of tones, and tag colors come from the database, so the
  tag chip is our own markup with the stored colors inline.
- Fuse matches `tags.name`. v1 pointed at `tags`, which is an array of objects, so tag matching never fired.
- A barcode no item carries is recorded by `POST .../unknown-barcodes` and answered with a `Toast`, so
  an unreadable label never throws the scanner back to a v1 page. The admin review record is unchanged.
- The scanner reads a digit burst anywhere on the page, focused or not, at any length. A length rule at
  capture time dropped a short code silently; the lookup refuses it with a message instead.

### Phase 4 - Rest Of Guest Flow
Artifact approval per screen, in this order.

- [ ] Location pick
- [ ] Storage pick
- [ ] Item detail
- [ ] Expiration allocation (223 lines of JS today, no library equivalent, full custom work)

### Phase 5 - Admin
Component layer is proven by now, so these compose faster than they look.

- [ ] Admin login and PIN
- [ ] Admin hub and dashboard
- [ ] Items and tags
- [ ] Reports (16 routes)
- [ ] Bulk edit
- [ ] Settings
- [ ] Help
- [ ] Item trend modal (295 lines today, chart from Fragments, interaction custom)
- [ ] Notifications table, 23 columns. Each row is a plain text preview of that recipient; tapping it opens
      the editable modal, the same interaction as the pencil on the Items screen. Decided, no layout question left.

### Phase 6 - Delete v1
- [ ] 34 templates
- [ ] 12 CSS files, 3,885 lines
- [ ] 36 JS files, 2,480 lines
- [ ] Print views stay server rendered Flask. Not deleted.

### Phase 7 - Marketing Site
- [ ] Separate repo, GitHub Pages, static. No contact form.

## Scale Reference

| Thing | Count |
|---|---|
| Python files / lines | 150 / 19,552 |
| Tests | 393 |
| Routes | 54 v1 + 51 JSON endpoints across 37 rules |
| Templates | 34 |
| CSS files / lines | 31 / 4,892 (12 v1 `app/static/css`, 19 v2 `web/src`) |
| Client JS files / lines | 36 / 2,480 |
| Migrations | 1 |
| Fragments components available | 71 across 9 categories |

## Work Split

I proceed without asking on: endpoints, schemas, services, queries, types, tests, file structure, naming, drift checks, anything Python.

I stop for approval on: every screen, every layout, anything that changes what a person sees or presses, anything that behaves differently across kiosk, laptop/TV or iPhone.

## Device Priority

Kiosk touchscreen first. Laptop and TV tied second. iPhone last.

## Guest Scan Flow

One route, no URL per step. `ScanFlow.tsx` holds the draft and swaps the body; `Page` draws the
frame and the Back control. Steps: item, location, route, quantity, dates. A saved scan has no
step of its own: it drops the guest straight back on the item list with a `Toast` confirming
what it did, the way v1's bottom flash does, so nobody confirms a screen they never wanted.

The location step only appears when the device cookie has no location yet. The route step hides
TAKE once a virtual from-choice is picked, and drops the chosen shelf out of the to-list, so an
impossible route cannot be built. When only one choice is left on a side it is picked for the
scanner, and when the whole location can only make one route the step is passed through; Back
from the quantity step then skips it, the same rules v1 applies server side.

New shared pieces: `ChoiceCard`, `StepBar`, `Stepper`, `RouteStrip`, `Panel`, `ItemPhoto`, `Toast`.
Four JSON endpoints back it: device location read/write, scan context, expiration options.

## Open

- [x] Real barcode scanner session. Not needed: a scanner sends the same keystrokes as a paste, and paste works.
